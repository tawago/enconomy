const socket = io();

let deviceId = null;
let role = null;
let mediaStream = null;
let isRecording = false;
let audioContext = null;

// Seeded random number generator (mulberry32)
function seededRandom(seed) {
    return function() {
        let t = seed += 0x6D2B79F5;
        t = Math.imul(t ^ t >>> 15, t | 1);
        t ^= t + Math.imul(t ^ t >>> 7, t | 61);
        return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
}

// Generate deterministic chirp parameters from seed
function generateChirpParams(seed) {
    const rng = seededRandom(seed);
    // Base frequencies with some randomness
    const startFreq = 500 + rng() * 500;  // 500-1000 Hz
    const endFreq = 3000 + rng() * 1000;  // 3000-4000 Hz
    const sweepUp = rng() > 0.5;  // Random direction
    return {
        startFreq: sweepUp ? startFreq : endFreq,
        endFreq: sweepUp ? endFreq : startFreq,
        duration: 0.2  // 200ms
    };
}

// Play a deterministic chirp based on seed
async function playChirp(seed) {
    // Ensure audio context exists and is resumed (for autoplay policy)
    if (!audioContext) {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (audioContext.state === 'suspended') {
        await audioContext.resume();
    }

    const params = generateChirpParams(seed);
    const oscillator = audioContext.createOscillator();
    const gainNode = audioContext.createGain();

    oscillator.type = 'sine';
    oscillator.frequency.setValueAtTime(params.startFreq, audioContext.currentTime);
    oscillator.frequency.exponentialRampToValueAtTime(params.endFreq, audioContext.currentTime + params.duration);

    // Envelope to avoid clicks
    gainNode.gain.setValueAtTime(0, audioContext.currentTime);
    gainNode.gain.linearRampToValueAtTime(0.5, audioContext.currentTime + 0.01);
    gainNode.gain.setValueAtTime(0.5, audioContext.currentTime + params.duration - 0.01);
    gainNode.gain.linearRampToValueAtTime(0, audioContext.currentTime + params.duration);

    oscillator.connect(gainNode);
    gainNode.connect(audioContext.destination);

    oscillator.start(audioContext.currentTime);
    oscillator.stop(audioContext.currentTime + params.duration);

    log(`Playing chirp (seed=${seed}, ${params.startFreq.toFixed(0)}Hz -> ${params.endFreq.toFixed(0)}Hz)`);

    return new Promise(resolve => {
        oscillator.onended = resolve;
    });
}

const roleEl = document.getElementById('role');
const deviceIdEl = document.getElementById('device-id');
const micStatusEl = document.getElementById('mic-status');
const peerStatusEl = document.getElementById('peer-status');
const trialStateEl = document.getElementById('trial-state');
const startBtn = document.getElementById('start-btn');
const conditionInput = document.getElementById('condition-label');
const resultsPanel = document.getElementById('results-panel');
const logEl = document.getElementById('log');

function log(msg) {
    const entry = document.createElement('div');
    entry.className = 'log-entry';
    entry.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
    logEl.appendChild(entry);
    logEl.scrollTop = logEl.scrollHeight;
}

function setTrialState(state) {
    trialStateEl.textContent = state;
}

async function requestMicrophone() {
    try {
        mediaStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                echoCancellation: false,
                noiseSuppression: false,
                autoGainControl: false,
            }
        });
        micStatusEl.textContent = 'Granted';
        micStatusEl.className = 'value success';
        log('Microphone access granted');
        return true;
    } catch (err) {
        micStatusEl.textContent = 'Denied';
        micStatusEl.className = 'value error';
        log(`Microphone error: ${err.message}`);
        return false;
    }
}

async function recordAudio(durationMs) {
    return new Promise((resolve, reject) => {
        const chunks = [];
        const recorder = new MediaRecorder(mediaStream, { mimeType: 'audio/webm' });

        recorder.ondataavailable = (e) => {
            if (e.data.size > 0) chunks.push(e.data);
        };

        recorder.onstop = async () => {
            const webmBlob = new Blob(chunks, { type: 'audio/webm' });
            try {
                const wavBlob = await convertToWav(webmBlob);
                resolve(wavBlob);
            } catch (err) {
                reject(err);
            }
        };

        recorder.onerror = reject;
        recorder.start();

        setTimeout(() => {
            recorder.stop();
        }, durationMs);
    });
}

async function convertToWav(webmBlob) {
    const audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const arrayBuffer = await webmBlob.arrayBuffer();
    const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);

    const sampleRate = 16000;
    const numChannels = 1;
    const offlineContext = new OfflineAudioContext(numChannels, audioBuffer.duration * sampleRate, sampleRate);

    const source = offlineContext.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(offlineContext.destination);
    source.start();

    const renderedBuffer = await offlineContext.startRendering();
    const wavData = encodeWav(renderedBuffer);

    return new Blob([wavData], { type: 'audio/wav' });
}

function encodeWav(audioBuffer) {
    const numChannels = audioBuffer.numberOfChannels;
    const sampleRate = audioBuffer.sampleRate;
    const format = 1;
    const bitDepth = 16;

    const samples = audioBuffer.getChannelData(0);
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);

    function writeString(offset, string) {
        for (let i = 0; i < string.length; i++) {
            view.setUint8(offset + i, string.charCodeAt(i));
        }
    }

    writeString(0, 'RIFF');
    view.setUint32(4, 36 + samples.length * 2, true);
    writeString(8, 'WAVE');
    writeString(12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, format, true);
    view.setUint16(22, numChannels, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * numChannels * bitDepth / 8, true);
    view.setUint16(32, numChannels * bitDepth / 8, true);
    view.setUint16(34, bitDepth, true);
    writeString(36, 'data');
    view.setUint32(40, samples.length * 2, true);

    let offset = 44;
    for (let i = 0; i < samples.length; i++) {
        const s = Math.max(-1, Math.min(1, samples[i]));
        view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
        offset += 2;
    }

    return buffer;
}

socket.on('connect', () => {
    log('Connected to server');
    socket.emit('join', { user_agent: navigator.userAgent });
});

socket.on('joined', (data) => {
    deviceId = data.device_id;
    role = data.role;

    roleEl.textContent = role.charAt(0).toUpperCase() + role.slice(1);
    roleEl.className = role === 'initiator' ? 'value success' : 'value';
    deviceIdEl.textContent = deviceId;

    log(`Joined as ${role} (${deviceId})`);

    if (role === 'initiator') {
        startBtn.style.display = 'block';
    }

    requestMicrophone();
});

socket.on('join_error', (data) => {
    roleEl.textContent = 'Error';
    roleEl.className = 'value error';
    log(`Join error: ${data.message}`);
});

socket.on('peer_status', (data) => {
    const canStart = data.can_start;

    if (data.count === 2) {
        peerStatusEl.textContent = 'Connected';
        peerStatusEl.className = 'value success';
    } else {
        peerStatusEl.textContent = 'Waiting...';
        peerStatusEl.className = 'value warning';
    }

    if (role === 'initiator') {
        startBtn.disabled = !canStart || isRecording;
    }
});

socket.on('start_recording', async (data) => {
    const { trial_id, start_at, duration_ms, chirp_seed } = data;
    isRecording = true;
    startBtn.disabled = true;

    const commandReceived = Date.now();
    log(`Trial ${trial_id}: Recording scheduled (chirp_seed=${chirp_seed})`);
    setTrialState('Scheduled');

    // Pre-initialize audio context to handle autoplay policy
    if (role === 'initiator' && chirp_seed !== undefined) {
        if (!audioContext) {
            audioContext = new (window.AudioContext || window.webkitAudioContext)();
        }
        if (audioContext.state === 'suspended') {
            try {
                await audioContext.resume();
                log('Audio context resumed for chirp playback');
            } catch (err) {
                log(`Warning: Could not resume audio context: ${err.message}`);
            }
        }
    }

    const delay = start_at - Date.now();
    if (delay > 0) {
        await new Promise(r => setTimeout(r, delay));
    }

    setTrialState('Recording');
    log('Recording...');

    const actualStart = Date.now();
    let chirpPlayedAt = null;

    try {
        // Start recording
        const recordingPromise = recordAudio(duration_ms);

        // Initiator plays chirp 100ms after recording starts
        if (role === 'initiator' && chirp_seed !== undefined) {
            setTimeout(async () => {
                try {
                    chirpPlayedAt = Date.now();
                    await playChirp(chirp_seed);
                } catch (err) {
                    log(`Chirp playback error: ${err.message}`);
                }
            }, 100);
        }

        const audioBlob = await recordingPromise;
        const actualStop = Date.now();

        setTrialState('Uploading');
        log('Uploading audio...');

        const uploadStart = Date.now();
        const arrayBuffer = await audioBlob.arrayBuffer();
        const base64 = btoa(String.fromCharCode(...new Uint8Array(arrayBuffer)));

        socket.emit('audio_data', {
            trial_id: trial_id,
            audio: base64,
            chirp_seed: chirp_seed,
            timings: {
                command_received: commandReceived,
                actual_start: actualStart,
                actual_stop: actualStop,
                upload_start: uploadStart,
                chirp_played_at: chirpPlayedAt,
            }
        });

        setTrialState('Analyzing');
        log('Waiting for analysis...');

    } catch (err) {
        log(`Recording error: ${err.message}`);
        setTrialState('Error');
        isRecording = false;
        startBtn.disabled = false;
    }
});

socket.on('upload_received', (data) => {
    log(`Upload received: ${data.device_id}`);
});

socket.on('trial_result', (data) => {
    isRecording = false;
    startBtn.disabled = false;
    setTrialState('Done');

    resultsPanel.style.display = 'block';

    document.getElementById('hamming-dist').textContent = data.hamming_distance;
    document.getElementById('disagreement').textContent = `${data.disagreement_pct}%`;
    document.getElementById('bch-threshold').textContent = data.bch_threshold;
    document.getElementById('corrected').textContent = data.corrected_errors ?? '-';
    document.getElementById('lag-ms').textContent = data.lag_ms ?? '-';

    const reproduceEl = document.getElementById('reproduce-result');
    reproduceEl.textContent = data.reproduce_success ? 'Success' : 'Failed';
    reproduceEl.className = data.reproduce_success ? 'value success' : 'value error';

    const keyMatchEl = document.getElementById('key-match');
    keyMatchEl.textContent = data.key_match ? 'Match' : 'Mismatch';
    keyMatchEl.className = data.key_match ? 'value success' : 'value error';

    log(`Trial complete: Hamming=${data.hamming_distance}, ${data.reproduce_success ? 'SUCCESS' : 'FAILED'}`);
});

socket.on('trial_error', (data) => {
    isRecording = false;
    startBtn.disabled = false;
    setTrialState('Error');
    log(`Trial error: ${data.message}`);
});

startBtn.addEventListener('click', () => {
    const condition = conditionInput.value.trim();
    socket.emit('start_trial', { condition_label: condition || null });
    log('Starting trial...');
});
