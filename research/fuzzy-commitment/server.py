"""Flask + SocketIO server for fuzzy commitment audio validation."""

import os
import uuid
import time
import random
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

from audio_features import extract_bits, extract_bits_aligned, extract_bits_from_room, hamming_distance, TARGET_SR, get_target_bits
from bch_codec import get_params, BCH_T
from fuzzy_commitment import generate_commitment, reproduce_commitment, compute_raw_hamming
from trial_logger import log_trial_dict

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=50 * 1024 * 1024, async_mode='threading')

AUDIO_DIR = Path(__file__).parent / "audio"
AUDIO_DIR.mkdir(exist_ok=True)

participants = {}
current_trial = None
MAX_PARTICIPANTS = 2
RECORDING_DURATION_MS = 2500
START_DELAY_MS = 1500
UPLOAD_TIMEOUT_MS = 30000


class Trial:
    def __init__(self, trial_id: str, initiator_id: str, responder_id: str, chirp_seed: int):
        self.trial_id = trial_id
        self.initiator_id = initiator_id
        self.responder_id = responder_id
        self.chirp_seed = chirp_seed
        self.scheduled_start = int(time.time() * 1000) + START_DELAY_MS
        self.duration_ms = RECORDING_DURATION_MS
        self.uploads = {}
        self.client_timings = {}
        self.condition_label = None
        self.created_at = datetime.utcnow().isoformat()

    def add_upload(self, device_id: str, audio_data: bytes, timings: dict):
        self.uploads[device_id] = audio_data
        self.client_timings[device_id] = timings

    def is_complete(self) -> bool:
        return len(self.uploads) == 2


def get_participant_role(sid: str) -> str:
    return participants.get(sid, {}).get('role')


def broadcast_peer_status():
    roles = {p['role']: {'id': p['id'], 'ready': p.get('ready', False)}
             for p in participants.values()}
    socketio.emit('peer_status', {
        'participants': roles,
        'count': len(participants),
        'can_start': len(participants) == 2,
    })


@app.route('/')
def index():
    return render_template('index.html')


@socketio.on('connect')
def on_connect():
    pass


@socketio.on('join')
def on_join(data):
    global participants

    if len(participants) >= MAX_PARTICIPANTS:
        emit('join_error', {'message': 'Room is full (max 2 participants)'})
        return

    device_id = str(uuid.uuid4())[:8]
    role = 'initiator' if len(participants) == 0 else 'responder'

    participants[request.sid] = {
        'id': device_id,
        'role': role,
        'ready': True,
        'user_agent': data.get('user_agent', ''),
    }

    emit('joined', {
        'device_id': device_id,
        'role': role,
    })

    broadcast_peer_status()


@socketio.on('disconnect')
def on_disconnect():
    if request.sid in participants:
        del participants[request.sid]
        broadcast_peer_status()


@socketio.on('start_trial')
def on_start_trial(data):
    global current_trial

    if get_participant_role(request.sid) != 'initiator':
        emit('trial_error', {'message': 'Only initiator can start trial'})
        return

    if len(participants) != 2:
        emit('trial_error', {'message': 'Need exactly 2 participants'})
        return

    if current_trial is not None:
        emit('trial_error', {'message': 'Trial already in progress'})
        return

    trial_id = str(uuid.uuid4())[:8]
    chirp_seed = random.randint(0, 2**32 - 1)
    participant_list = list(participants.values())
    initiator = next(p for p in participant_list if p['role'] == 'initiator')
    responder = next(p for p in participant_list if p['role'] == 'responder')

    current_trial = Trial(trial_id, initiator['id'], responder['id'], chirp_seed)
    current_trial.condition_label = data.get('condition_label')

    socketio.emit('start_recording', {
        'trial_id': trial_id,
        'start_at': current_trial.scheduled_start,
        'duration_ms': current_trial.duration_ms,
        'sample_rate': TARGET_SR,
        'chirp_seed': chirp_seed,
    })


@socketio.on('audio_data')
def on_audio_data(data):
    global current_trial

    if current_trial is None:
        emit('trial_error', {'message': 'No active trial'})
        return

    if data.get('trial_id') != current_trial.trial_id:
        emit('trial_error', {'message': 'Trial ID mismatch'})
        return

    device_id = participants.get(request.sid, {}).get('id')
    if not device_id:
        emit('trial_error', {'message': 'Unknown device'})
        return

    audio_bytes = data.get('audio')
    if isinstance(audio_bytes, str):
        import base64
        audio_bytes = base64.b64decode(audio_bytes)

    timings = data.get('timings', {})
    current_trial.add_upload(device_id, audio_bytes, timings)

    audio_path = AUDIO_DIR / f"{current_trial.trial_id}_{device_id}.wav"
    with open(audio_path, 'wb') as f:
        f.write(audio_bytes)

    socketio.emit('upload_received', {
        'trial_id': current_trial.trial_id,
        'device_id': device_id,
    })

    if current_trial.is_complete():
        process_trial()


def process_trial():
    global current_trial
    trial = current_trial

    try:
        initiator_audio = trial.uploads[trial.initiator_id]
        responder_audio = trial.uploads[trial.responder_id]

        # v3: Use room acoustic features from chirp response
        bits_a, bits_b, lag_samples = extract_bits_from_room(
            initiator_audio, responder_audio, trial.chirp_seed
        )
        lag_ms = lag_samples / TARGET_SR * 1000

        raw_distance, raw_pct = compute_raw_hamming(bits_a, bits_b)

        commitment_result = generate_commitment(bits_a)

        reproduction_result = reproduce_commitment(
            commitment_result.commitment,
            bits_b,
            commitment_result.secret_hash,
        )

        bch_params = get_params()

        result = {
            'trial_id': trial.trial_id,
            'success': True,
            'hamming_distance': raw_distance,
            'disagreement_pct': round(raw_pct, 2),
            'bch_threshold': BCH_T,
            'reproduce_success': reproduction_result.success,
            'key_match': reproduction_result.key_match,
            'corrected_errors': reproduction_result.corrected_errors,
            'lag_ms': round(lag_ms, 1),
            'message': reproduction_result.message,
        }

        socketio.emit('trial_result', result)

        initiator_timings = trial.client_timings.get(trial.initiator_id, {})
        responder_timings = trial.client_timings.get(trial.responder_id, {})
        initiator_participant = next((p for p in participants.values() if p['id'] == trial.initiator_id), {})
        responder_participant = next((p for p in participants.values() if p['id'] == trial.responder_id), {})

        log_trial_dict({
            'trial_id': trial.trial_id,
            'timestamp': trial.created_at,
            'condition_label': trial.condition_label,
            'device_a_id': trial.initiator_id,
            'device_a_user_agent': initiator_participant.get('user_agent'),
            'device_b_id': trial.responder_id,
            'device_b_user_agent': responder_participant.get('user_agent'),
            'scheduled_start_ms': trial.scheduled_start,
            'device_a_actual_start_ms': initiator_timings.get('actual_start'),
            'device_a_actual_stop_ms': initiator_timings.get('actual_stop'),
            'device_a_upload_ms': initiator_timings.get('upload_start'),
            'device_b_actual_start_ms': responder_timings.get('actual_start'),
            'device_b_actual_stop_ms': responder_timings.get('actual_stop'),
            'device_b_upload_ms': responder_timings.get('upload_start'),
            'audio_duration_a_ms': RECORDING_DURATION_MS,
            'audio_duration_b_ms': RECORDING_DURATION_MS,
            'lag_ms': round(lag_ms, 1),
            'chirp_seed': trial.chirp_seed,
            'feature_params': {
                'sample_rate': TARGET_SR,
                'target_bits': get_target_bits(),
                'version': 3,
                'mode': 'chirp_room_ir',
            },
            'bch_params': bch_params,
            'hamming_distance': raw_distance,
            'disagreement_pct': round(raw_pct, 2),
            'bch_correction_threshold': BCH_T,
            'reproduce_success': reproduction_result.success,
            'key_match': reproduction_result.key_match,
            'corrected_errors': reproduction_result.corrected_errors,
            'error_reason': None,
        })

    except Exception as e:
        error_msg = str(e)
        socketio.emit('trial_error', {
            'trial_id': trial.trial_id,
            'message': f'Analysis failed: {error_msg}',
        })

        log_trial_dict({
            'trial_id': trial.trial_id,
            'timestamp': trial.created_at,
            'condition_label': trial.condition_label,
            'error_reason': error_msg,
            'reproduce_success': False,
            'key_match': False,
        })

    finally:
        current_trial = None


if __name__ == '__main__':
    print("Starting fuzzy commitment server...")
    print("Open https://192.168.0.29:5001 on two devices")
    print("You'll need to accept the self-signed certificate warning")
    socketio.run(app, host='0.0.0.0', port=5001, debug=False,
                 ssl_context=('cert.pem', 'key.pem'))
