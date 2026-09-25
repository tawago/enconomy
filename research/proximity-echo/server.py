"""Browser harness for the Proximity-Echo (Ren et al., INFOCOM'21) reproduction.

Per session: L beeps from device A, alternating with L beeps from device B, at the
paper's 0.5 s inter-beep interval. Both devices record the entire window. Server runs
period selection per scheduled emission, energy compensation across the four
direction pairs, smoothed Pearson correlation, and accept/reject at threshold 0.78.
"""

from __future__ import annotations

import base64
import os
import random
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

from alignment import (
    bandpass_filter,
    canonicalize_audio,
    select_periods_for_beep,
)
from challenge_generator import BeepSpec, make_beep_spec
from pipeline_constants import (
    LINK_TEST_BEEPS_PER_DEVICE,
    LINK_TEST_MIN_AUDIBILITY_RATIO,
    PIPELINE_VERSION,
    bandpass_edges_hz,
    constants_snapshot,
)
from clipping import apply_clipping_exclusion, detect_clipping
from compensation import compute_compensated_signatures
from feature_extraction import (
    FEATURE_VERSION,
    _energy_spectrum,
    extract_pair_recording_spectra,
    platform_hint_from_user_agent,
)
from scoring import DEFAULT_VERDICT_THRESHOLD, cross_self_similarity, score_proximity
from trial_logger import LOG_SCHEMA_VERSION, log_trial
from validity import assess_capture_validity


def provenance_block(
    alignment_mode: str | None = None,
    classifier_version: str | None = None,
    validity_version: str | None = None,
) -> dict:
    """Record pipeline, constants, and algorithm versions for later analysis.

    Older saved records may also contain discontinued regression coverage fields.
    New recordings do not depend on an automated test run.
    """
    snap = constants_snapshot()
    return {
        "pipeline_version": PIPELINE_VERSION,
        "constants_hash": snap["constants_hash"],
        "constants": snap["constants"],
        "feature_version": FEATURE_VERSION,
        "classifier_version": classifier_version,
        "validity_version": validity_version,
        "log_schema_version": LOG_SCHEMA_VERSION,
        "alignment_mode": alignment_mode,
    }


BASE_DIR = Path(__file__).parent
AUDIO_DIR = BASE_DIR / "data" / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
SSL_CERT_PATH = BASE_DIR.parent / "fuzzy-commitment" / "cert.pem"
SSL_KEY_PATH = BASE_DIR.parent / "fuzzy-commitment" / "key.pem"

MAX_PARTICIPANTS = 2
BEEPS_PER_DEVICE = 20
INTER_BEEP_INTERVAL_MS = 500
LEAD_IN_MS = 1000
TAIL_MS = 1000
START_DELAY_MS = 1500


@dataclass(frozen=True)
class ScheduledBeep:
    beep_index: int
    emitter_role: str
    offset_ms: int

    def to_dict(self) -> dict:
        return asdict(self)


def build_schedule(beeps_per_device: int = BEEPS_PER_DEVICE, interval_ms: int = INTER_BEEP_INTERVAL_MS, lead_in_ms: int = LEAD_IN_MS) -> list[ScheduledBeep]:
    schedule: list[ScheduledBeep] = []
    a_index = 0
    b_index = 0
    for slot in range(beeps_per_device * 2):
        offset = lead_in_ms + slot * interval_ms
        if slot % 2 == 0:
            schedule.append(ScheduledBeep(beep_index=a_index, emitter_role="initiator", offset_ms=offset))
            a_index += 1
        else:
            schedule.append(ScheduledBeep(beep_index=b_index, emitter_role="observer", offset_ms=offset))
            b_index += 1
    return schedule


def total_record_window_ms(schedule: list[ScheduledBeep]) -> int:
    if not schedule:
        return LEAD_IN_MS + TAIL_MS
    return schedule[-1].offset_ms + TAIL_MS


app = Flask(__name__)
app.config["SECRET_KEY"] = os.urandom(24)
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=200 * 1024 * 1024, async_mode="threading")

# The timing diagnostic has its own namespace, state, and artifact directory.
from ranging_server import register_ranging
ranging_service = register_ranging(app, socketio)

participants: dict[str, dict] = {}
current_trial: "Trial | None" = None
# Serializes every mutation of `current_trial` (start, upload-accumulate, completion-claim,
# disconnect-abort). With async_mode="threading" each socket event runs in its own thread, so two
# near-simultaneous audio_upload handlers (the norm: both browsers upload at the same scheduled
# capture end) could otherwise BOTH observe is_complete()==True after their add_upload and BOTH
# invoke process_* — double-logging the trial and double-counting it in the go/no-go statistics.
# The completed trial is CLAIMED (popped to a local, current_trial set None) under this lock so
# exactly one thread processes it; processing then runs OUTSIDE the lock.
trial_lock = threading.RLock()
# Workstream E (fix-plan §E1): the session's most recent completed reciprocal-audibility
# link-test result, stamped onto every subsequent trial's record so a trial collected under a
# failed/absent audibility check is visible in the log.
# None until the first link test runs; reset when a link test is re-run.
last_link_test: "dict | None" = None


@dataclass
class Trial:
    trial_id: str
    initiator_id: str
    observer_id: str
    schedule: list[ScheduledBeep]
    beep_spec: BeepSpec
    record_window_ms: int
    condition_label: str | None
    # Workstream E tier/condition stamping (fix-plan §E1). All optional so pre-E clients that
    # send none still start a valid trial.
    is_link_test: bool = False
    hardware_tier: str | None = None
    hardware_notes: str | None = None
    condition_distance: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    start_at_ms: int = field(default_factory=lambda: int(time.time() * 1000) + START_DELAY_MS)
    uploads: dict[str, bytes] = field(default_factory=dict)
    metadata: dict[str, dict] = field(default_factory=dict)

    def add_upload(self, device_id: str, audio_bytes: bytes, metadata: dict) -> None:
        self.uploads[device_id] = audio_bytes
        self.metadata[device_id] = metadata

    def is_complete(self) -> bool:
        return len(self.uploads) == 2


def current_participant() -> dict | None:
    return participants.get(request.sid)


def device_by_role(role: str) -> dict:
    return next(participant for participant in participants.values() if participant["role"] == role)


def armed_roles() -> list[str]:
    return [p["role"] for p in participants.values() if p.get("armed")]


def _parse_beep_overrides(data: dict | None) -> dict:
    data = data or {}
    start_khz = data.get("start_khz")
    end_khz = data.get("end_khz")
    if start_khz is None and end_khz is None:
        return {}

    start_hz = float(start_khz) * 1000.0 if start_khz is not None else None
    end_hz = float(end_khz) * 1000.0 if end_khz is not None else None
    if start_hz is None or end_hz is None:
        raise ValueError("Both start_khz and end_khz are required when overriding the chirp band")
    if end_hz <= start_hz:
        raise ValueError("end_khz must be greater than start_khz")

    return {
        "start_freq_hz": start_hz,
        "end_freq_hz": end_hz,
    }


def broadcast_peer_status() -> None:
    socketio.emit(
        "peer_status",
        {
            "participants": {participant["role"]: participant["id"] for participant in participants.values()},
            "count": len(participants),
            "armed_roles": armed_roles(),
            "can_start": len(participants) == 2 and current_trial is None and len(armed_roles()) == 2,
        },
    )


@app.route("/")
def index():
    return render_template("index.html")


@socketio.on("join")
def on_join(data=None):
    data = data or {}
    if len(participants) >= MAX_PARTICIPANTS:
        emit("join_error", {"message": "Room is full (max 2 participants)"})
        return

    # Assign by the currently-UNHELD role, not by participant count: after an initiator
    # disconnects (incl. mid-trial), a rejoiner beside a surviving observer must reclaim the
    # 'initiator' slot, or the room soft-locks (two observers, start_trial permanently
    # refused, no Start button anywhere) until BOTH clients reload.
    existing_roles = {participant["role"] for participant in participants.values()}
    role = "observer" if "initiator" in existing_roles else "initiator"
    participants[request.sid] = {
        "id": str(uuid.uuid4())[:8],
        "role": role,
        "user_agent": data.get("user_agent"),
    }
    emit("joined", participants[request.sid])
    broadcast_peer_status()


@socketio.on("disconnect")
def on_disconnect():
    global current_trial
    if request.sid in participants:
        participant = participants.pop(request.sid)
        aborted_id = None
        with trial_lock:
            if current_trial and participant["id"] in {current_trial.initiator_id, current_trial.observer_id}:
                # C2 deadlock fix: a peer vanishing mid-trial used to clear current_trial
                # silently, leaving the surviving client latched in isBusy (Start disabled,
                # state stuck on "Recording"/"Analyzing") forever. Tell the survivor so its
                # trial_error handler resets. Broadcast to the room — the leaver is already gone.
                aborted_id = current_trial.trial_id
                current_trial = None
        if aborted_id is not None:
            socketio.emit(
                "trial_error",
                {"trial_id": aborted_id, "message": "Peer disconnected mid-trial; trial aborted"},
            )
        broadcast_peer_status()


@socketio.on("time_probe")
def on_time_probe(data=None):
    """A3.2 websocket clock sync. The client fires 5-10 of these before a trial, timestamping
    t0 on send and t1 on receipt of the echo; it keeps the min-RTT sample and computes
    offset_vs_server = t_server - (t0 + t1) / 2. The server only needs to echo t0 back with
    its own send time. Stateless and trial-independent."""
    t0 = (data or {}).get("t0")
    seq = (data or {}).get("seq")
    emit("time_probe_response", {"t0": t0, "seq": seq, "t_server_ms": time.time() * 1000.0})


@socketio.on("audio_armed")
def on_audio_armed(_data=None):
    participant = current_participant()
    if not participant:
        return
    participant["armed"] = True
    socketio.emit("arm_status", {"armed_roles": armed_roles()})
    broadcast_peer_status()


@socketio.on("self_echo_test")
def on_self_echo_test(_data=None):
    participant = current_participant()
    if not participant:
        emit("self_echo_error", {"message": "Unknown participant"})
        return

    try:
        overrides = _parse_beep_overrides(_data)
        beep_spec = make_beep_spec(seed=random.randint(0, 2**32 - 1), **overrides)
    except ValueError as exc:
        emit("self_echo_error", {"message": str(exc)})
        return

    # Single beep: lead-in 200 ms, then one beep at offset=200 ms, record for 1500 ms total.
    SELF_ECHO_OFFSET_MS = 200
    SELF_ECHO_RECORD_MS = 1500
    START_DELAY = 1200

    emit(
        "prepare_self_echo_test",
        {
            "beep_spec": beep_spec.to_dict(),
            "beep_offset_ms": SELF_ECHO_OFFSET_MS,
            "record_window_ms": SELF_ECHO_RECORD_MS,
            "start_at_ms": int(time.time() * 1000) + START_DELAY,
        },
    )


@socketio.on("self_echo_upload")
def on_self_echo_upload(data):
    participant = current_participant()
    if not participant:
        emit("self_echo_error", {"message": "Unknown participant"})
        return

    encoded_audio = data.get("audio_base64")
    if not encoded_audio:
        emit("self_echo_error", {"message": "Missing audio payload"})
        return

    beep_spec_dict = data.get("beep_spec")
    beep_offset_ms = float(data.get("beep_offset_ms", 200))

    if not beep_spec_dict:
        emit("self_echo_error", {"message": "Missing beep_spec"})
        return

    try:
        audio_bytes = base64.b64decode(encoded_audio)
        beep_spec = BeepSpec(**beep_spec_dict)

        audio, _, canonical_rate = canonicalize_audio(audio_bytes, beep_spec.sample_rate)
        # D3.5: band from this trial's beep_spec (identical to BANDPASS_LOW/HIGH_HZ at 6-12 kHz).
        band_low_hz, band_high_hz = bandpass_edges_hz(beep_spec.start_freq_hz, beep_spec.end_freq_hz)
        filtered = bandpass_filter(audio, canonical_rate, low_hz=band_low_hz, high_hz=band_high_hz)

        selection = select_periods_for_beep(
            filtered,
            canonical_rate,
            beep_spec,
            expected_offset_ms=beep_offset_ms,
            search_pad_before_ms=20.0,
            search_pad_after_ms=400.0,
            already_filtered=True,
        )

        # Echo energy spectrum (restricted to the beep band)
        import numpy as np
        echo_segment = (
            filtered[selection.echo_start:selection.echo_end]
            if selection.echo_end > selection.echo_start
            else np.zeros(0, dtype=np.float32)
        )
        echo_freqs, echo_energy = _energy_spectrum(
            echo_segment,
            canonical_rate,
            beep_spec.start_freq_hz,
            beep_spec.end_freq_hz,
        )
        echo_total_energy = float(np.sum(echo_energy)) if len(echo_energy) > 0 else 0.0

        # Downsample spectrum to at most 40 points for a compact display
        if len(echo_freqs) > 40:
            indices = np.round(np.linspace(0, len(echo_freqs) - 1, 40)).astype(int)
            spectrum_freqs = [float(echo_freqs[i]) for i in indices]
            spectrum_energy = [float(echo_energy[i]) for i in indices]
        else:
            spectrum_freqs = [float(f) for f in echo_freqs]
            spectrum_energy = [float(e) for e in echo_energy]

        emit(
            "self_echo_result",
            {
                "chirp_peak": round(selection.chirp_peak_value, 4),
                "echo_peak": round(selection.echo_peak_value, 4),
                "echo_energy": round(echo_total_energy, 4),
                "selection_ok": selection.selection_ok,
                "spectrum_freqs": spectrum_freqs,
                "spectrum_energy": spectrum_energy,
            },
        )
    except Exception as exc:
        emit("self_echo_error", {"message": f"Self-echo analysis failed: {exc}"})


@socketio.on("start_trial")
def on_start_trial(data):
    global current_trial

    participant = current_participant()
    if not participant or participant["role"] != "initiator":
        emit("trial_error", {"message": "Only the initiator can start a trial"})
        return

    if len(participants) != 2:
        emit("trial_error", {"message": "Exactly two connected devices are required"})
        return

    if len(armed_roles()) != 2:
        emit("trial_error", {"message": "Both devices must tap 'Arm Audio' before a trial can start"})
        return

    trial_id = str(uuid.uuid4())[:8]
    # Workstream E: the link-test probe is a lightweight (fewer-beep) trial through the SAME
    # capture + alignment path, so the gate measures the identical quantity a real trial does.
    is_link_test = bool(data.get("link_test"))
    schedule = build_schedule(
        beeps_per_device=LINK_TEST_BEEPS_PER_DEVICE if is_link_test else BEEPS_PER_DEVICE
    )
    try:
        overrides = _parse_beep_overrides(data)
        beep_spec = make_beep_spec(seed=random.randint(0, 2**32 - 1), **overrides)
    except ValueError as exc:
        emit("trial_error", {"message": str(exc)})
        return
    record_window_ms = total_record_window_ms(schedule)

    initiator = device_by_role("initiator")
    observer = device_by_role("observer")
    # Claim the trial slot under the lock: the not-None check and the assignment must be atomic
    # w.r.t. an upload thread that clears current_trial on completion.
    with trial_lock:
        if current_trial is not None:
            emit("trial_error", {"message": "A trial is already in progress"})
            return
        trial = Trial(
            trial_id=trial_id,
            initiator_id=initiator["id"],
            observer_id=observer["id"],
            schedule=schedule,
            beep_spec=beep_spec,
            record_window_ms=record_window_ms,
            condition_label=(data.get("condition_label") or None),
            is_link_test=is_link_test,
            hardware_tier=(data.get("hardware_tier") or None),
            hardware_notes=(data.get("hardware_notes") or None),
            condition_distance=(data.get("condition_distance") or None),
        )
        current_trial = trial

    socketio.emit(
        "start_trial",
        {
            "trial_id": trial_id,
            "start_at_ms": trial.start_at_ms,
            "record_window_ms": record_window_ms,
            "beep_spec": beep_spec.to_dict(),
            "schedule": [item.to_dict() for item in schedule],
            "link_test": is_link_test,
        },
    )
    broadcast_peer_status()


@socketio.on("audio_upload")
def on_audio_upload(data):
    global current_trial

    participant = current_participant()
    if not participant:
        emit("trial_error", {"message": "Unknown participant"})
        return

    encoded_audio = data.get("audio_base64")
    if not encoded_audio:
        emit("trial_error", {"message": "Missing audio payload"})
        return

    audio_bytes = base64.b64decode(encoded_audio)
    metadata = data.get("metadata") or {}
    device_id = participant["id"]

    # Accumulate this upload and CLAIM the trial for processing atomically. Everything that reads
    # or mutates current_trial happens under the lock so two near-simultaneous uploads cannot both
    # observe completion and double-process. Exactly one thread walks away with `claimed` set (and
    # current_trial already cleared); the heavy processing then runs OUTSIDE the lock.
    claimed: "Trial | None" = None
    with trial_lock:
        if current_trial is None:
            emit("trial_error", {"message": "No active trial"})
            return
        if data.get("trial_id") != current_trial.trial_id:
            emit("trial_error", {"message": "Trial ID mismatch"})
            return

        current_trial.add_upload(device_id, audio_bytes, metadata)
        output_path = AUDIO_DIR / f"{current_trial.trial_id}_{device_id}.wav"
        output_path.write_bytes(audio_bytes)
        socketio.emit("upload_received", {"trial_id": current_trial.trial_id, "device_id": device_id})

        if current_trial.is_complete():
            claimed = current_trial
            current_trial = None  # release the slot at claim time, not after processing

    if claimed is not None:
        # Slot is already free: re-enable Start on both clients BEFORE the (slower) analysis + log,
        # so a fast next start_trial is not spuriously refused with "A trial is already in progress".
        broadcast_peer_status()
        if claimed.is_link_test:
            process_link_test(claimed)
        else:
            process_trial(claimed)


def _align_pair(trial: Trial) -> dict:
    """Run the joint alignment + per-device summaries shared by the full scored trial
    (process_trial) and the lightweight link-test probe (process_link_test). Factored so the
    gate measures partner audibility off the EXACT same alignment a real trial scores from."""
    schedule_dicts = [item.to_dict() for item in trial.schedule]

    audio_a, _, _ = canonicalize_audio(trial.uploads[trial.initiator_id], trial.beep_spec.sample_rate)
    audio_b, _, _ = canonicalize_audio(trial.uploads[trial.observer_id], trial.beep_spec.sample_rate)
    clipping_a = detect_clipping(audio_a)
    clipping_b = detect_clipping(audio_b)

    initiator_info = next((p for p in participants.values() if p["id"] == trial.initiator_id), {})
    observer_info = next((p for p in participants.values() if p["id"] == trial.observer_id), {})

    # A3.3 dual-mode: pass the client timing metadata (websocket-probe skew + capture
    # anchor) through so the cross-offset sweep is prior-bounded when it is present, and
    # falls back to the full masked sweep when it is not (pre-A3 clients / archive).
    timing_meta_a = _client_timing_meta(trial.metadata.get(trial.initiator_id, {}))
    timing_meta_b = _client_timing_meta(trial.metadata.get(trial.observer_id, {}))

    # Joint alignment: self/partner train assignment needs BOTH recordings
    # (replica-findings §4.1.2), so the two devices are extracted together.
    spectra_a, spectra_b = extract_pair_recording_spectra(
        trial.uploads[trial.initiator_id],
        trial.uploads[trial.observer_id],
        schedule_dicts,
        trial.beep_spec,
        platform_hint_a=platform_hint_from_user_agent(initiator_info.get("user_agent")),
        platform_hint_b=platform_hint_from_user_agent(observer_info.get("user_agent")),
        timing_meta_a=timing_meta_a,
        timing_meta_b=timing_meta_b,
    )
    # Trial-level alignment mode for the log / golden pins: prior_bounded iff at least one
    # device's sweep was actually prior-bounded this trial.
    alignment_mode = (
        "prior_bounded"
        if "prior_bounded" in (spectra_a.get("alignment_mode"), spectra_b.get("alignment_mode"))
        else "masked_full_sweep"
    )

    # D3.7: drop only the beep windows a (non-fatal) clip actually corrupts, so a
    # self-chirp clip does not invalidate the cross echo periods.
    exclusion_a = apply_clipping_exclusion(audio_a, spectra_a)
    exclusion_b = apply_clipping_exclusion(audio_b, spectra_b)

    return {
        "schedule_dicts": schedule_dicts,
        "clipping_a": clipping_a,
        "clipping_b": clipping_b,
        "initiator_info": initiator_info,
        "observer_info": observer_info,
        "spectra_a": spectra_a,
        "spectra_b": spectra_b,
        "alignment_mode": alignment_mode,
        "device_a_summary": build_device_summary(
            "initiator", spectra_a, clipping_a, trial.metadata.get(trial.initiator_id, {}), exclusion_a
        ),
        "device_b_summary": build_device_summary(
            "observer", spectra_b, clipping_b, trial.metadata.get(trial.observer_id, {}), exclusion_b
        ),
    }


def _link_audibility_ratio(summary: dict) -> float | None:
    """Normalized partner audibility R_dir for one listening device (fix-plan §E1):

        R = partner_train.median_amplitude / self_train.median_amplitude

    the peak matched-filter amplitude of the ASSIGNED partner beep train over the peak
    matched-filter amplitude of the device's OWN beep train. Both are the SAME measurement
    (EventTrain median peak amplitude) taken on the partner vs the self grid, so the ratio is
    the correctly-calibrated peak-vs-peak "how loud does the partner arrive vs my own beep" —
    exactly the partner/self amplitude ratio replica-findings §3 surveyed (median 0.62 mac /
    0.97 android). Returns None (an indeterminate direction the gate treats as a FAIL) when the
    joint alignment produced no assigned partner train (a deaf/ambiguous link — the pipeline
    could not confidently place the partner) or no self reference.

    NOTE the earlier draft used cross_offset_score, but that is a ±window MEAN of the masked
    envelope, ~20-30x smaller than a peak, so cross_offset_score/self_peak was mis-scaled
    against §3's peak/peak survey; the train medians are the apples-to-apples quantity."""
    self_train = summary.get("self_train") or {}
    partner_train = summary.get("partner_train") or {}
    self_amp = self_train.get("median_amplitude")
    partner_amp = partner_train.get("median_amplitude")
    if not self_amp or float(self_amp) <= 0.0 or partner_amp is None:
        return None
    return float(partner_amp) / float(self_amp)


def _round_opt(value: float | None, ndigits: int = 4) -> float | None:
    return round(value, ndigits) if value is not None else None


def _build_link_test_stamp(trial: Trial, summary_a: dict, summary_b: dict) -> dict:
    """The session link-test snapshot: per-direction normalized audibility + gate verdict,
    stamped both into the emitted link_test_result and onto every subsequent trial record so a
    trial collected under a failed/absent gate is self-evident in the log."""
    ratio_a = _link_audibility_ratio(summary_a)  # device A hears device B
    ratio_b = _link_audibility_ratio(summary_b)  # device B hears device A
    passed_a = ratio_a is not None and ratio_a >= LINK_TEST_MIN_AUDIBILITY_RATIO
    passed_b = ratio_b is not None and ratio_b >= LINK_TEST_MIN_AUDIBILITY_RATIO
    return {
        "present": True,
        "passed": bool(passed_a and passed_b),
        "min_ratio": LINK_TEST_MIN_AUDIBILITY_RATIO,
        "ratio_a_hears_b": _round_opt(ratio_a),
        "ratio_b_hears_a": _round_opt(ratio_b),
        "passed_a_hears_b": bool(passed_a),
        "passed_b_hears_a": bool(passed_b),
        "hardware_tier": trial.hardware_tier,
        "beep_band_khz": [
            round(trial.beep_spec.start_freq_hz / 1000.0, 3),
            round(trial.beep_spec.end_freq_hz / 1000.0, 3),
        ],
        "beeps_per_device": LINK_TEST_BEEPS_PER_DEVICE,
        "trial_id": trial.trial_id,
        "measured_at": trial.created_at,
    }


def _bands_match(band_a: "list | None", band_b: "list | None", tol_khz: float = 0.05) -> bool:
    """Two [lowcut_khz, highcut_khz] band pairs match if both edges agree within tol_khz.
    Distinct tier bands (e.g. 6-12 vs 4-9 kHz) differ by >=1 kHz, so a 50 Hz tolerance
    separates them cleanly while absorbing float rounding on the stored edges."""
    if not band_a or not band_b or len(band_a) != 2 or len(band_b) != 2:
        return band_a == band_b
    return all(abs(float(x) - float(y)) <= tol_khz for x, y in zip(band_a, band_b))


def _link_test_stamp_for(trial: Trial) -> dict:
    """The link-test gate snapshot to stamp onto a NON-link-test trial (fix-plan §E1,
    data-integrity follow-up). `last_link_test` is session-global: a user who runs the link
    test under one hardware tier / beep band and then switches (e.g. T1/6-12 kHz -> T2/4-9 kHz)
    would otherwise get trials stamped gate-PASSED that were never gated for THIS tier/band.

    So compare the stamp's hardware_tier AND beep band against the trial's own before stamping;
    on a mismatch return a shallow copy marked `stale: True` + `stale_reason` (additive to the
    schema) so analysis (experiment_power.gate_state) treats it as not-passed, campaign_status
    itemizes it in the gate accounting, and the client badge reflects the stale state. A matching
    stamp is returned unchanged (no `stale` key), so gate_state keeps reading it as 'passed'."""
    stamp = last_link_test
    if not stamp:
        return {"present": False}
    trial_band = [
        round(trial.beep_spec.start_freq_hz / 1000.0, 3),
        round(trial.beep_spec.end_freq_hz / 1000.0, 3),
    ]
    tier_mismatch = stamp.get("hardware_tier") != trial.hardware_tier
    band_mismatch = not _bands_match(stamp.get("beep_band_khz"), trial_band)
    if not (tier_mismatch or band_mismatch):
        return stamp
    reasons = []
    if tier_mismatch:
        reasons.append(f"tier {stamp.get('hardware_tier')!r} != trial {trial.hardware_tier!r}")
    if band_mismatch:
        reasons.append(f"band {stamp.get('beep_band_khz')} != trial {trial_band} kHz")
    stale = dict(stamp)
    stale["stale"] = True
    stale["stale_reason"] = "; ".join(reasons)
    return stale


def process_link_test(trial: Trial) -> None:
    """Reciprocal-audibility gate (fix-plan §E1). Runs the joint alignment off both probe
    recordings, computes the per-direction normalized audibility R, records the pass/fail
    stamp for the session, emits it to both browsers, and logs a marked link-test record.
    Never scores/verdicts a proximity result — this only measures whether the link is loud
    enough in BOTH directions to admit the current hardware tier."""
    global last_link_test
    # The trial slot was already claimed + released by on_audio_upload, so this function must NOT
    # touch current_trial (clearing it here could stomp a trial started meanwhile). It emits the
    # result only AFTER the record is written, so a client that starts a new trial the instant the
    # result renders races neither the slot nor the log.
    try:
        aligned = _align_pair(trial)
        stamp = _build_link_test_stamp(trial, aligned["device_a_summary"], aligned["device_b_summary"])
        last_link_test = stamp

        log_trial(
            {
                "trial_id": trial.trial_id,
                "timestamp": trial.created_at,
                "is_link_test": True,
                "condition_label": trial.condition_label,
                "condition_distance": trial.condition_distance,
                "hardware_tier": trial.hardware_tier,
                "hardware_notes": trial.hardware_notes,
                "link_test": stamp,
                "challenge_family": "paper_repro_link_test_v1",
                "feature_version": FEATURE_VERSION,
                "log_schema_version": LOG_SCHEMA_VERSION,
                "provenance": provenance_block(alignment_mode=aligned["alignment_mode"]),
                "beep_spec": trial.beep_spec.to_dict(),
                "schedule": aligned["schedule_dicts"],
                "alignment_mode": aligned["alignment_mode"],
                "device_a": {"id": trial.initiator_id, "user_agent": aligned["initiator_info"].get("user_agent"), **aligned["device_a_summary"]},
                "device_b": {"id": trial.observer_id, "user_agent": aligned["observer_info"].get("user_agent"), **aligned["device_b_summary"]},
                "failure_reason": None,
            }
        )
        socketio.emit("link_test_result", {"trial_id": trial.trial_id, **stamp})
    except Exception as exc:
        error_message = str(exc)
        socketio.emit("link_test_error", {"trial_id": trial.trial_id, "message": f"Link test failed: {error_message}"})


def process_trial(trial: Trial) -> None:
    # The slot was already claimed + released by on_audio_upload; do NOT touch current_trial here
    # (see process_link_test). The result is emitted only AFTER the record is logged.
    try:
        aligned = _align_pair(trial)
        schedule_dicts = aligned["schedule_dicts"]
        clipping_a, clipping_b = aligned["clipping_a"], aligned["clipping_b"]
        initiator_info, observer_info = aligned["initiator_info"], aligned["observer_info"]
        spectra_a, spectra_b = aligned["spectra_a"], aligned["spectra_b"]
        alignment_mode = aligned["alignment_mode"]
        device_a_summary = aligned["device_a_summary"]
        device_b_summary = aligned["device_b_summary"]

        # Stamp the session link-test gate, marking it stale if its tier/band no longer matches
        # this trial (a stamp from a different tier/band never gated THIS trial — §E1 follow-up).
        link_test_stamp = _link_test_stamp_for(trial)

        signatures = compute_compensated_signatures(
            spectra_a["per_beep"], spectra_b["per_beep"],
            low_hz=trial.beep_spec.start_freq_hz, high_hz=trial.beep_spec.end_freq_hz,
        )
        score = score_proximity(signatures.to_dict(), verdict_threshold=DEFAULT_VERDICT_THRESHOLD)
        validity = assess_capture_validity(
            device_a_summary,
            device_b_summary,
            signature_freq_points=len(signatures.freqs_hz),
            raw_score=score.score,
            raw_verdict=score.verdict,
            cross_self_similarity=cross_self_similarity(signatures.to_dict()),
            compensation_dropped_beeps=signatures.n_grid_mismatch_dropped,
        )

        result = {
            "trial_id": trial.trial_id,
            "success": bool(validity.capture_valid and score.verdict),
            "capture_valid": validity.capture_valid,
            "measurement_failure_reasons": validity.failure_reasons,
            "measurement_warnings": validity.warnings,
            "score": score.score,
            "c_a": score.c_a,
            "c_b": score.c_b,
            "verdict": validity.proximity_verdict,
            "raw_verdict": score.verdict,
            "classifier_version": score.classifier_version,
            "threshold": score.threshold,
            "n_beeps_a": signatures.n_beeps_a,
            "n_beeps_b": signatures.n_beeps_b,
            "alignment_mode": alignment_mode,
            "message": (
                "Measurement invalid; proximity verdict withheld"
                if not validity.capture_valid
                else "Pearson(echo signatures) >= threshold"
                if score.verdict
                else "Pearson(echo signatures) below threshold"
            ),
            "clipping_warning": clipping_a["clipped"] or clipping_b["clipped"],
            # Workstream E: surface the session's link-test gate state + this trial's tier so the
            # browser can show whether the trial was collected under a passing reciprocal-
            # audibility gate (never blocks — diagnostic trials under a failed gate are allowed).
            "hardware_tier": trial.hardware_tier,
            "link_test": link_test_stamp,
        }

        log_trial(
            {
                "trial_id": trial.trial_id,
                "timestamp": trial.created_at,
                "is_link_test": False,
                "condition_label": trial.condition_label,
                "condition_distance": trial.condition_distance,
                "hardware_tier": trial.hardware_tier,
                "hardware_notes": trial.hardware_notes,
                "link_test": link_test_stamp,
                "challenge_family": "paper_repro_alternating_beeps_v1",
                "feature_version": FEATURE_VERSION,
                "log_schema_version": LOG_SCHEMA_VERSION,
                "provenance": provenance_block(
                    alignment_mode=alignment_mode,
                    classifier_version=score.classifier_version,
                    validity_version=validity.validity_version,
                ),
                "scheduled_start_ms": trial.start_at_ms,
                "record_window_ms": trial.record_window_ms,
                "alignment_mode": alignment_mode,
                "beep_spec": trial.beep_spec.to_dict(),
                "schedule": schedule_dicts,
                "device_a": {
                    "id": trial.initiator_id,
                    "user_agent": initiator_info.get("user_agent"),
                    **device_a_summary,
                },
                "device_b": {
                    "id": trial.observer_id,
                    "user_agent": observer_info.get("user_agent"),
                    **device_b_summary,
                },
                "signatures": {
                    "n_beeps_a": signatures.n_beeps_a,
                    "n_beeps_b": signatures.n_beeps_b,
                    "n_freq_points": len(signatures.freqs_hz),
                },
                "pair": validity.to_dict(),
                "score": {
                    "classifier_version": score.classifier_version,
                    "threshold": score.threshold,
                    "c_a": score.c_a,
                    "c_b": score.c_b,
                    "score": score.score,
                    "raw_verdict": score.verdict,
                    "capture_valid": validity.capture_valid,
                    "verdict": validity.proximity_verdict,
                },
                "ground_truth_label": trial.condition_label,
                "failure_reason": None,
            }
        )
        socketio.emit("trial_result", result)
    except Exception as exc:
        error_message = str(exc)
        log_trial(
            {
                "trial_id": trial.trial_id,
                "timestamp": trial.created_at,
                "condition_label": trial.condition_label,
                "challenge_family": "paper_repro_alternating_beeps_v1",
                "log_schema_version": LOG_SCHEMA_VERSION,
                "provenance": provenance_block(),
                "beep_spec": trial.beep_spec.to_dict(),
                "schedule": [item.to_dict() for item in trial.schedule],
                "failure_reason": error_message,
            }
        )
        socketio.emit("trial_error", {"trial_id": trial.trial_id, "message": f"Analysis failed: {error_message}"})


def build_device_summary(role: str, spectra: dict, clipping: dict, metadata: dict, clipping_exclusion: dict | None = None) -> dict:
    """Assemble the per-device summary consumed by validity checks and the trial log.
    Shared with analysis/rescore_archive.py so offline re-scores match live trials."""
    return {
        "role": role,
        "clipping": clipping,
        "clipping_exclusion": clipping_exclusion or {},
        "metadata": metadata,
        "self_offset_ms": spectra.get("self_offset_ms"),
        "self_locked": spectra.get("self_locked"),
        "self_train": spectra.get("self_train"),
        "partner_train": spectra.get("partner_train"),
        "detected_trains": spectra.get("detected_trains"),
        "train_assignment": spectra.get("train_assignment"),
        "cross_offset_ms": spectra.get("cross_offset_ms"),
        "cross_offset_source": spectra.get("cross_offset_source"),
        "cross_offset_score": spectra.get("cross_offset_score"),
        "cross_status": spectra.get("cross_status"),
        "alignment_mode": spectra.get("alignment_mode"),
        "cross_offset_prior": spectra.get("cross_offset_prior"),
        "sweep": spectra.get("sweep"),
        "self_structure_positions_ms": spectra.get("self_structure_positions_ms"),
        "self_mask_intervals_ms": spectra.get("self_mask_intervals_ms"),
        "alignment_warnings": spectra.get("alignment_warnings"),
        "per_beep_summary": _summarize_per_beep(spectra["per_beep"], spectra["canonical_sample_rate"]),
    }


def _client_timing_meta(metadata: dict) -> dict | None:
    """Pull the A3 timing prior inputs out of an upload's metadata (dual-mode: returns None
    for pre-A3 clients that sent none, so the sweep falls back to the full search).

    The client uploads `timing_probe` (min-RTT websocket clock sync: offset_vs_server_ms,
    min_rtt_ms) and, under `trial_timings`, `capture_anchor` (the first onaudioprocess
    (Date.now, AudioContext.currentTime) pair that pins WAV sample 0 to wall-clock time) and
    `record_start_audio_time`. feature_extraction consumes offset_vs_server_ms + min_rtt_ms +
    capture_anchor.date_now_ms; the rest is carried for forensics (A3.1)."""
    metadata = metadata or {}
    probe = metadata.get("timing_probe") or {}
    timings = metadata.get("trial_timings") or {}
    anchor = timings.get("capture_anchor")
    if probe.get("offset_vs_server_ms") is None or probe.get("min_rtt_ms") is None or not anchor:
        return None
    return {
        "offset_vs_server_ms": probe.get("offset_vs_server_ms"),
        "min_rtt_ms": probe.get("min_rtt_ms"),
        "n_probes": probe.get("n_probes"),
        "capture_anchor": anchor,
        "record_start_audio_time": timings.get("record_start_audio_time"),
    }


def _summarize_per_beep(per_beep: list[dict], canonical_sample_rate: int) -> list[dict]:
    summaries = []
    for entry in per_beep:
        summaries.append({
            "beep_index": entry["beep_index"],
            "emitter_role": entry["emitter_role"],
            "offset_ms": entry["offset_ms"],
            "selection_ok": entry["selection"]["selection_ok"],
            "chirp_start": entry["selection"]["chirp_start"],
            "canonical_sample_rate": int(canonical_sample_rate),
            "chirp_peak_value": entry["selection"]["chirp_peak_value"],
            "echo_peak_value": entry["selection"]["echo_peak_value"],
            "selection_failure_reason": entry["selection"].get("failure_reason"),
            "echo_noise_median": entry["selection"].get("echo_noise_median", 0.0),
            "echo_threshold": entry["selection"].get("echo_threshold", 0.0),
            "chirp_total_energy": entry["spectra"]["chirp_total_energy"],
            "echo_total_energy": entry["spectra"]["echo_total_energy"],
        })
    return summaries


if __name__ == "__main__":
    if not SSL_CERT_PATH.exists() or not SSL_KEY_PATH.exists():
        raise FileNotFoundError(
            "Missing TLS certificate files. Expected cert.pem and key.pem in research/fuzzy-commitment/."
        )

    print("Starting proximity-echo paper-repro harness on https://0.0.0.0:5002")
    print("Using TLS certs from research/fuzzy-commitment/")
    socketio.run(
        app,
        host="0.0.0.0",
        port=5002,
        debug=False,
        ssl_context=(str(SSL_CERT_PATH), str(SSL_KEY_PATH)),
    )
