const socket = io();

let deviceId = null;
let role = null;
let mediaStream = null;
let audioContext = null;
let isBusy = false;

const roleEl = document.getElementById('role');
const deviceIdEl = document.getElementById('device-id');
const micStatusEl = document.getElementById('mic-status');
const peerStatusEl = document.getElementById('peer-status');
const trialStateEl = document.getElementById('trial-state');
const audioSettingsEl = document.getElementById('audio-settings');
const startBtn = document.getElementById('start-btn');
const armBtn = document.getElementById('arm-btn');
const armStatusEl = document.getElementById('arm-status');
const peerArmStatusEl = document.getElementById('peer-arm-status');
const ctxStateEl = document.getElementById('ctx-state');
const chirpStartEl = document.getElementById('chirp-start');
const chirpEndEl = document.getElementById('chirp-end');
const chirpStartValueEl = document.getElementById('chirp-start-value');
const chirpEndValueEl = document.getElementById('chirp-end-value');
const testStatusEl = document.getElementById('test-status');
const testLowBtn = document.getElementById('test-low-btn');
const testMidBtn = document.getElementById('test-mid-btn');
const testBeepBtn = document.getElementById('test-beep-btn');
const testLoopBtn = document.getElementById('test-loop-btn');
const emitToneBtn = document.getElementById('emit-tone-btn');
const micListenBtn = document.getElementById('mic-listen-btn');
const micLevelEl = document.getElementById('mic-level');
const micPeakEl = document.getElementById('mic-peak');

let continuousTone = null;
let listenAnalyser = null;
let listenInterval = null;
let listenSource = null;
let listenPeak1s = 0;
let listenPeakDecayHandle = null;
const conditionInput = document.getElementById('condition-label');
const conditionDistanceEl = document.getElementById('condition-distance');
const bandPresetEl = document.getElementById('band-preset');
const hwTierEl = document.getElementById('hw-tier');
const hwNotesEl = document.getElementById('hw-notes');
const micBandLabelEl = document.getElementById('mic-band-label');
const linkTestBtn = document.getElementById('link-test-btn');
const linkGateBadgeEl = document.getElementById('link-gate-badge');
const linkTestResultsEl = document.getElementById('link-test-results');
const resultsPanel = document.getElementById('results-panel');
const logEl = document.getElementById('log');
const screenAwakeStatusEl = document.getElementById('screen-awake-status');
const screenAwake = createScreenAwakeController((message, tone) => {
    screenAwakeStatusEl.textContent = message;
    screenAwakeStatusEl.className = `value ${tone}`;
    log(`Screen awake: ${message}`);
});

let audioArmed = false;
let peerArmed = false;
let canStart = false;
// True while the in-flight trial is a link-test probe (server echoes link_test in start_trial),
// so the client renders the gate result instead of a proximity score.
let pendingLinkTest = false;

// Band presets for the tier ladder (fix-plan §E1). T2 is the 4-9 kHz band drop.
const BAND_PRESETS = {
    default: { start: 6, end: 12 },
    t2: { start: 4, end: 9 },
};

function currentBandKhz() {
    return {
        start_khz: Number(chirpStartEl?.value ?? 6),
        end_khz: Number(chirpEndEl?.value ?? 12),
    };
}

function currentCondition() {
    const distance = conditionDistanceEl?.value ?? 'touch';
    const label = distance === 'other'
        ? (conditionInput.value.trim() || null)
        : distance;
    return { condition_distance: distance, condition_label: label };
}

// One place that assembles the tier/condition/band stamp for both a real trial and a link test.
function trialPayload(extra) {
    const cond = currentCondition();
    return {
        condition_label: cond.condition_label,
        condition_distance: cond.condition_distance,
        hardware_tier: hwTierEl?.value ?? null,
        hardware_notes: hwNotesEl?.value.trim() || null,
        ...currentBandKhz(),
        ...(extra || {}),
    };
}

function fmtRatio(value) {
    return (value === null || value === undefined) ? 'indeterminate' : Number(value).toFixed(3);
}

// Reflect the session link-test gate on the always-visible badge next to Start.
function renderGateBadge(linkTest) {
    if (!linkGateBadgeEl) return;
    if (!linkTest || !linkTest.present) {
        linkGateBadgeEl.className = 'gate-badge none';
        linkGateBadgeEl.textContent = 'Not checked';
        return;
    }
    if (linkTest.stale) {
        // Present + internally passing, but measured under a different hardware tier / beep band
        // than this trial, so it never gated it. Server-flagged; analysis treats it as not-passed.
        linkGateBadgeEl.className = 'gate-badge fail';
        linkGateBadgeEl.textContent = 'Audio link needs recheck after setup change';
        return;
    }
    if (linkTest.passed) {
        linkGateBadgeEl.className = 'gate-badge pass';
        linkGateBadgeEl.textContent = 'Audio link ready';
    } else {
        linkGateBadgeEl.className = 'gate-badge fail';
        linkGateBadgeEl.textContent = 'Audio link weak or unresolved';
    }
}

function syncBandControls(changed = null) {
    if (!chirpStartEl || !chirpEndEl) {
        return;
    }
    let start = Number(chirpStartEl.value);
    let end = Number(chirpEndEl.value);
    if (end <= start) {
        if (changed === 'start') {
            end = Math.min(16, start + 0.5);
            chirpEndEl.value = String(end);
        } else {
            start = Math.max(4, end - 0.5);
            chirpStartEl.value = String(start);
        }
    }
    chirpStartValueEl.textContent = `${Number(chirpStartEl.value).toFixed(1)} kHz`;
    chirpEndValueEl.textContent = `${Number(chirpEndEl.value).toFixed(1)} kHz`;
    if (micBandLabelEl) {
        micBandLabelEl.textContent = `${Number(chirpStartEl.value).toFixed(1)}–${Number(chirpEndEl.value).toFixed(1)} kHz`;
    }
}

function applyBandPreset(name) {
    const preset = BAND_PRESETS[name];
    if (!preset || !chirpStartEl || !chirpEndEl) return;
    chirpStartEl.value = String(preset.start);
    chirpEndEl.value = String(preset.end);
    syncBandControls();
}

if (bandPresetEl) {
    bandPresetEl.addEventListener('change', () => {
        if (bandPresetEl.value !== 'custom') {
            applyBandPreset(bandPresetEl.value);
        }
        // Keep the T2 preset and tier in sync when either is selected.
        // Later manual band changes remain available for custom experiments.
        if (bandPresetEl.value === 't2' && hwTierEl) {
            hwTierEl.value = 'T2';
        }
    });
}

if (hwTierEl) {
    hwTierEl.addEventListener('change', () => {
        if (hwTierEl.value === 'T2') {
            if (bandPresetEl) bandPresetEl.value = 't2';
            applyBandPreset('t2');
        }
    });
}

if (conditionDistanceEl && conditionInput) {
    const syncConditionInput = () => {
        conditionInput.style.display = conditionDistanceEl.value === 'other' ? 'block' : 'none';
    };
    conditionDistanceEl.addEventListener('change', syncConditionInput);
    syncConditionInput();
}

function log(message) {
    const entry = document.createElement('div');
    entry.className = 'log-entry';
    entry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
    logEl.appendChild(entry);
    logEl.scrollTop = logEl.scrollHeight;
}

function setTrialState(state) {
    trialStateEl.textContent = state;
}

function ensureAudioContext() {
    if (!audioContext) {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (ctxStateEl) {
        ctxStateEl.textContent = `${audioContext.state} @ ${audioContext.sampleRate}Hz`;
        ctxStateEl.className = audioContext.state === 'running' ? 'value success' : 'value warning';
    }
    return audioContext;
}

function refreshCtxState() {
    if (audioContext && ctxStateEl) {
        ctxStateEl.textContent = `${audioContext.state} @ ${audioContext.sampleRate}Hz`;
        ctxStateEl.className = audioContext.state === 'running' ? 'value success' : 'value warning';
    }
}

async function ensureRunning() {
    const context = ensureAudioContext();
    if (context.state === 'suspended') {
        try {
            await context.resume();
        } catch (error) {
            log(`Resume failed: ${error.message}`);
        }
    }
    refreshCtxState();
    return context;
}

function buildToneBuffer(context, freqHz, durationS = 0.4, amplitude = 0.25) {
    const sampleRate = context.sampleRate;
    const frameCount = Math.max(1, Math.round(sampleRate * durationS));
    const buffer = context.createBuffer(1, frameCount, sampleRate);
    const samples = buffer.getChannelData(0);
    for (let i = 0; i < frameCount; i += 1) {
        samples[i] = amplitude * Math.sin(2 * Math.PI * freqHz * i / sampleRate);
    }
    const fade = Math.min(Math.round(sampleRate * 0.005), Math.floor(frameCount / 2));
    for (let i = 0; i < fade; i += 1) {
        const g = i / fade;
        samples[i] *= g;
        samples[frameCount - 1 - i] *= g;
    }
    return buffer;
}

if (chirpStartEl && chirpEndEl) {
    const onManualBand = (which) => {
        if (bandPresetEl) bandPresetEl.value = 'custom';
        syncBandControls(which);
    };
    chirpStartEl.addEventListener('input', () => onManualBand('start'));
    chirpEndEl.addEventListener('input', () => onManualBand('end'));
    syncBandControls();
}

async function playToneTest(label, buffer, scheduledTimes = [0]) {
    const context = await ensureRunning();
    const startBase = context.currentTime + 0.05;
    for (const offsetS of scheduledTimes) {
        const source = context.createBufferSource();
        source.buffer = buffer;
        source.connect(context.destination);
        source.start(startBase + offsetS);
    }
    testStatusEl.textContent = `Played ${label} (${scheduledTimes.length}× via audio clock, ctx=${context.state})`;
    testStatusEl.className = 'value success';
    log(`Speaker test: ${label}, ${scheduledTimes.length} buffer(s) scheduled, ctx state=${context.state}`);
}

async function requestMicrophone() {
    try {
        mediaStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                echoCancellation: false,
                noiseSuppression: false,
                autoGainControl: false,
                channelCount: 1,
            },
        });
        const track = mediaStream.getAudioTracks()[0];
        const settings = track.getSettings ? track.getSettings() : {};
        micStatusEl.textContent = 'Granted';
        micStatusEl.className = 'value success';
        const dspGranted = ['echoCancellation', 'noiseSuppression', 'autoGainControl']
            .map((key) => `${key}=${settings[key] ?? '?'}`)
            .join(', ');
        audioSettingsEl.textContent = dspGranted;
        log(`Microphone ready. Granted DSP: ${dspGranted}`);
        log(`Full track settings: ${JSON.stringify(settings || {})}`);
        return true;
    } catch (error) {
        micStatusEl.textContent = 'Denied';
        micStatusEl.className = 'value error';
        audioSettingsEl.textContent = error.message;
        log(`Microphone request failed: ${error.message}`);
        return false;
    }
}

function buildBeepBuffer(context, spec) {
    const sampleRate = spec.sample_rate;
    const frameCount = Math.max(1, Math.round(sampleRate * spec.duration_ms / 1000));
    const audioBuffer = context.createBuffer(1, frameCount, sampleRate);
    const samples = audioBuffer.getChannelData(0);

    const durationSec = spec.duration_ms / 1000;
    const slope = (spec.end_freq_hz - spec.start_freq_hz) / durationSec;
    for (let i = 0; i < frameCount; i += 1) {
        const t = i / sampleRate;
        const phase = 2 * Math.PI * (spec.start_freq_hz * t + 0.5 * slope * t * t);
        samples[i] = spec.amplitude * Math.sin(phase);
    }

    const fadeSamples = Math.min(Math.round(sampleRate * spec.fade_ms / 1000), Math.floor(frameCount / 2));
    for (let i = 0; i < fadeSamples; i += 1) {
        const gain = 0.5 - 0.5 * Math.cos(Math.PI * i / Math.max(1, fadeSamples - 1));
        samples[i] *= gain;
        samples[frameCount - 1 - i] *= gain;
    }

    return audioBuffer;
}

function encodeMonoWav(samples, sampleRate) {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);

    function writeString(offset, value) {
        for (let index = 0; index < value.length; index += 1) {
            view.setUint8(offset + index, value.charCodeAt(index));
        }
    }

    writeString(0, 'RIFF');
    view.setUint32(4, 36 + samples.length * 2, true);
    writeString(8, 'WAVE');
    writeString(12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeString(36, 'data');
    view.setUint32(40, samples.length * 2, true);

    let offset = 44;
    for (let index = 0; index < samples.length; index += 1) {
        const sample = Math.max(-1, Math.min(1, samples[index]));
        view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
        offset += 2;
    }
    return new Blob([buffer], { type: 'audio/wav' });
}

async function captureAudio(recordWindowMs, schedule, beepSpec) {
    return new Promise((resolve, reject) => {
        const context = ensureAudioContext();
        const beepBuffer = buildBeepBuffer(context, beepSpec);
        const source = context.createMediaStreamSource(mediaStream);
        const processor = context.createScriptProcessor(4096, 1, 1);
        const sink = context.createGain();
        sink.gain.value = 0;
        const chunks = [];
        const playbackTimings = [];
        const timings = {
            actual_record_start_ms: null,
            actual_record_stop_ms: null,
            // A3.1: AudioContext.currentTime at record start — the clock each beep's
            // scheduled_audio_time is relative to. Server converts scheduled_audio_time to a
            // WAV sample via the capture_anchor below and adds the measured self_offset_ms.
            record_start_audio_time: null,
            // A3.2: the first onaudioprocess callback stamps WAV sample 0 with a
            // (Date.now, AudioContext.currentTime) pair, pinning the recording clock to
            // wall-clock time so the server can compute the inter-device record-start skew.
            capture_anchor: null,
            playbacks: playbackTimings,
        };
        let stopped = false;

        function cleanup() {
            try {
                processor.disconnect();
                source.disconnect();
                sink.disconnect();
            } catch (error) {
                log(`Audio cleanup warning: ${error.message}`);
            }
        }

        function finalize() {
            if (stopped) {
                return;
            }
            stopped = true;
            timings.actual_record_stop_ms = Date.now();
            cleanup();

            const sampleCount = chunks.reduce((total, chunk) => total + chunk.length, 0);
            const samples = new Float32Array(sampleCount);
            let offset = 0;
            for (const chunk of chunks) {
                samples.set(chunk, offset);
                offset += chunk.length;
            }

            const rms = sampleCount > 0
                ? Math.sqrt(samples.reduce((acc, sample) => acc + sample * sample, 0) / sampleCount)
                : 0;
            log(`Captured ${sampleCount} samples at ${context.sampleRate}Hz, rms=${rms.toFixed(6)}`);

            resolve({
                wav: encodeMonoWav(samples, context.sampleRate),
                timings,
            });
        }

        processor.onaudioprocess = (event) => {
            if (!timings.capture_anchor) {
                // WAV sample 0 is the first sample of the first callback; pin it to both
                // clocks (A3.2). Date.now here is the wall-clock time of sample 0 within one
                // render-quantum; the server pairs it across devices to get the record-start
                // skew that centers the cross-offset prior.
                timings.capture_anchor = {
                    date_now_ms: Date.now(),
                    audio_time_s: context.currentTime,
                };
            }
            const input = event.inputBuffer.getChannelData(0);
            chunks.push(new Float32Array(input));
        };

        timings.actual_record_start_ms = Date.now();
        const recordStartAudioTime = context.currentTime;
        timings.record_start_audio_time = recordStartAudioTime;
        source.connect(processor);
        processor.connect(sink);
        sink.connect(context.destination);

        // Schedule ALL beeps up front via the audio clock instead of setTimeout —
        // on iOS Safari setTimeout-driven start() can fall outside an active gesture
        // window and silently fail; pre-scheduled BufferSource.start(when) does not.
        let myEmissions = 0;
        const schedulingErrors = [];
        for (const entry of schedule) {
            if (role !== entry.emitter_role) {
                continue;
            }
            myEmissions += 1;
            const beepIndex = entry.beep_index;
            const startWhen = recordStartAudioTime + entry.offset_ms / 1000;
            try {
                const beepSource = context.createBufferSource();
                beepSource.buffer = beepBuffer;
                beepSource.connect(context.destination);
                beepSource.start(startWhen);
                playbackTimings.push({
                    beep_index: beepIndex,
                    scheduled_offset_ms: entry.offset_ms,
                    scheduled_audio_time: startWhen,
                });
            } catch (error) {
                schedulingErrors.push(`beep ${beepIndex}: ${error.message}`);
            }
        }
        log(`Scheduled ${myEmissions} beeps via audio clock (context state=${context.state}, baseTime=${recordStartAudioTime.toFixed(3)}s)`);
        if (schedulingErrors.length) {
            log(`Scheduling errors: ${schedulingErrors.join(', ')}`);
        }

        setTimeout(finalize, recordWindowMs);
    });
}

function getMetadata() {
    const track = mediaStream?.getAudioTracks?.()[0];
    const settings = track?.getSettings ? track.getSettings() : {};
    const constraints = track?.getConstraints ? track.getConstraints() : {};
    const context = ensureAudioContext();

    return {
        user_agent: navigator.userAgent,
        requested_constraints: {
            echoCancellation: false,
            noiseSuppression: false,
            autoGainControl: false,
            channelCount: 1,
        },
        granted_track_settings: settings,
        track_constraints: constraints,
        base_latency: context.baseLatency ?? null,
        output_latency: context.outputLatency ?? null,
        recorder_path: 'webaudio_scriptprocessor_pcm',
    };
}

// ── A3.2 websocket clock sync ────────────────────────────────────────────────
// Fire N time_probe round trips; keep the min-RTT sample (least queueing noise) and its
// server-vs-local clock offset. offset_vs_server = t_server - (t0 + t1) / 2 assumes a
// symmetric path, best approximated by the smallest RTT. The result rides on the trial
// upload so the server can bound the cross-offset sweep to the measured clock skew (A3.3).
const TIME_PROBE_COUNT = 8;
const TIME_PROBE_GAP_MS = 40;
let latestTimingProbe = null;
const pendingProbes = new Map();

socket.on('time_probe_response', (data) => {
    const t1 = Date.now();
    const entry = pendingProbes.get(data.seq);
    if (!entry) return;
    pendingProbes.delete(data.seq);
    const rtt = t1 - entry.t0;
    const offset = data.t_server_ms - (entry.t0 + t1) / 2;
    entry.resolve({ rtt, offset });
});

function sendOneProbe(seq) {
    return new Promise((resolve) => {
        const t0 = Date.now();
        pendingProbes.set(seq, { t0, resolve });
        socket.emit('time_probe', { seq, t0 });
        // Guard against a dropped response so the burst can never hang the trial.
        setTimeout(() => {
            if (pendingProbes.has(seq)) {
                pendingProbes.delete(seq);
                resolve(null);
            }
        }, 2000);
    });
}

async function runTimeProbes() {
    const samples = [];
    for (let i = 0; i < TIME_PROBE_COUNT; i += 1) {
        const sample = await sendOneProbe(`${Date.now()}_${i}`);
        if (sample) samples.push(sample);
        await new Promise((r) => setTimeout(r, TIME_PROBE_GAP_MS));
    }
    if (!samples.length) {
        latestTimingProbe = null;
        log('Time probe: no responses — falling back to full-sweep alignment');
        return null;
    }
    let best = samples[0];
    for (const s of samples) {
        if (s.rtt < best.rtt) best = s;
    }
    latestTimingProbe = {
        offset_vs_server_ms: best.offset,
        min_rtt_ms: best.rtt,
        n_probes: samples.length,
    };
    log(`Time probe: ${samples.length}/${TIME_PROBE_COUNT} ok, min_rtt=${best.rtt.toFixed(1)}ms, offset=${best.offset.toFixed(1)}ms`);
    return latestTimingProbe;
}

socket.on('connect', () => {
    log('Connected to server');
    socket.emit('join', { user_agent: navigator.userAgent });
});

socket.on('joined', async (data) => {
    deviceId = data.id;
    role = data.role;
    roleEl.textContent = role;
    roleEl.className = role === 'initiator' ? 'value success' : 'value';
    deviceIdEl.textContent = deviceId;
    log(`Joined as ${role} (${deviceId})`);

    if (role === 'initiator') {
        startBtn.style.display = 'block';
        if (linkTestBtn) linkTestBtn.style.display = 'block';
    }

    await requestMicrophone();
});

socket.on('join_error', (data) => {
    roleEl.textContent = 'Error';
    roleEl.className = 'value error';
    log(`Join failed: ${data.message}`);
});

function updateStartButton() {
    if (role !== 'initiator') return;
    const ready = (canStart && audioArmed && peerArmed) && !isBusy;
    startBtn.disabled = !ready;
    if (linkTestBtn) linkTestBtn.disabled = !ready;
}

socket.on('peer_status', (data) => {
    peerStatusEl.textContent = data.count === 2 ? 'Connected' : 'Waiting';
    peerStatusEl.className = data.count === 2 ? 'value success' : 'value warning';
    canStart = !!data.can_start;
    const peerArm = data.armed_roles || [];
    const otherRole = role === 'initiator' ? 'observer' : 'initiator';
    peerArmed = peerArm.includes(otherRole);
    peerArmStatusEl.textContent = peerArmed ? 'Yes' : 'No';
    peerArmStatusEl.className = peerArmed ? 'value success' : 'value warning';
    updateStartButton();
});

socket.on('arm_status', (data) => {
    const armed = data.armed_roles || [];
    const otherRole = role === 'initiator' ? 'observer' : 'initiator';
    peerArmed = armed.includes(otherRole);
    peerArmStatusEl.textContent = peerArmed ? 'Yes' : 'No';
    peerArmStatusEl.className = peerArmed ? 'value success' : 'value warning';
    updateStartButton();
});

if (testLowBtn) {
    testLowBtn.addEventListener('click', async () => {
        const ctx = await ensureRunning();
        await playToneTest('1 kHz tone', buildToneBuffer(ctx, 1000, 0.4, 0.25));
    });
}
if (testMidBtn) {
    testMidBtn.addEventListener('click', async () => {
        const ctx = await ensureRunning();
        await playToneTest('8 kHz tone', buildToneBuffer(ctx, 8000, 0.4, 0.25));
    });
}
if (testBeepBtn) {
    testBeepBtn.addEventListener('click', async () => {
        const ctx = await ensureRunning();
        const band = currentBandKhz();
        const beepSpec = {
            sample_rate: ctx.sampleRate,
            duration_ms: 250,
            start_freq_hz: band.start_khz * 1000,
            end_freq_hz: band.end_khz * 1000,
            amplitude: 0.6,
            fade_ms: 8,
        };
        const buffer = buildBeepBuffer(ctx, beepSpec);
        await playToneTest(`${band.start_khz.toFixed(1)}–${band.end_khz.toFixed(1)} kHz chirp`, buffer);
    });
}
if (testLoopBtn) {
    testLoopBtn.addEventListener('click', async () => {
        const ctx = await ensureRunning();
        const band = currentBandKhz();
        const beepSpec = {
            sample_rate: ctx.sampleRate,
            duration_ms: 40,
            start_freq_hz: band.start_khz * 1000,
            end_freq_hz: band.end_khz * 1000,
            amplitude: 0.6,
            fade_ms: 3,
        };
        const buffer = buildBeepBuffer(ctx, beepSpec);
        await playToneTest(`${band.start_khz.toFixed(1)}–${band.end_khz.toFixed(1)} kHz beep ×5`, buffer, [0, 0.5, 1.0, 1.5, 2.0]);
    });
}

if (emitToneBtn) {
    emitToneBtn.addEventListener('click', async () => {
        if (continuousTone) {
            try {
                continuousTone.osc.stop();
                continuousTone.osc.disconnect();
                continuousTone.gain.disconnect();
            } catch (e) { /* ignore */ }
            continuousTone = null;
            emitToneBtn.textContent = 'Start Emitting 8 kHz Tone';
            emitToneBtn.style.background = '';
            log('Stopped continuous tone emission');
            return;
        }
        const ctx = await ensureRunning();
        const osc = ctx.createOscillator();
        osc.type = 'sine';
        osc.frequency.value = 8000;
        const gain = ctx.createGain();
        gain.gain.value = 0.25;
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start();
        continuousTone = { osc, gain };
        emitToneBtn.textContent = 'Stop Emitting 8 kHz Tone';
        emitToneBtn.style.background = '#f87171';
        log(`Emitting continuous 8 kHz tone (ctx=${ctx.state})`);
    });
}

if (micListenBtn) {
    micListenBtn.addEventListener('click', async () => {
        if (listenInterval) {
            clearInterval(listenInterval);
            listenInterval = null;
            if (listenSource) { try { listenSource.disconnect(); } catch (e) {} listenSource = null; }
            if (listenAnalyser) { try { listenAnalyser.disconnect(); } catch (e) {} listenAnalyser = null; }
            if (listenPeakDecayHandle) { clearInterval(listenPeakDecayHandle); listenPeakDecayHandle = null; }
            micListenBtn.textContent = 'Start Listening (in-band level meter)';
            micListenBtn.style.background = '';
            micLevelEl.textContent = '-';
            micPeakEl.textContent = '-';
            log('Stopped mic listening');
            return;
        }
        if (!mediaStream) {
            log('Mic listen: no microphone stream available');
            return;
        }
        const ctx = await ensureRunning();
        listenSource = ctx.createMediaStreamSource(mediaStream);
        listenAnalyser = ctx.createAnalyser();
        listenAnalyser.fftSize = 4096;
        listenAnalyser.smoothingTimeConstant = 0.0;
        listenSource.connect(listenAnalyser);

        const binCount = listenAnalyser.frequencyBinCount;
        const sampleRate = ctx.sampleRate;
        // Follow the selected chirp band (was hardcoded 6-12 kHz — wrong under a 4-9 kHz T2 preset).
        const band = currentBandKhz();
        const lowBin = Math.floor(band.start_khz * 1000 / (sampleRate / 2) * binCount);
        const highBin = Math.ceil(band.end_khz * 1000 / (sampleRate / 2) * binCount);
        const dataArray = new Uint8Array(binCount);
        listenPeak1s = 0;

        listenInterval = setInterval(() => {
            listenAnalyser.getByteFrequencyData(dataArray);
            // sum normalized magnitudes in 6-12kHz band
            let sum = 0;
            let max = 0;
            for (let i = lowBin; i <= highBin && i < binCount; i++) {
                sum += dataArray[i];
                if (dataArray[i] > max) max = dataArray[i];
            }
            const avg = sum / Math.max(1, (highBin - lowBin + 1));
            // dB-ish scale (getByteFrequencyData is already 0-255 ~= -100 to -30 dB)
            const level = avg / 255;
            micLevelEl.textContent = level.toFixed(4);
            micLevelEl.className = level > 0.05 ? 'value success' : (level > 0.01 ? 'value warning' : 'value');
            const peakNow = max / 255;
            if (peakNow > listenPeak1s) listenPeak1s = peakNow;
            micPeakEl.textContent = listenPeak1s.toFixed(4);
            micPeakEl.className = listenPeak1s > 0.1 ? 'value success' : (listenPeak1s > 0.02 ? 'value warning' : 'value');
        }, 100);
        listenPeakDecayHandle = setInterval(() => { listenPeak1s *= 0.6; }, 1000);

        micListenBtn.textContent = 'Stop Listening';
        micListenBtn.style.background = '#fbbf24';
        log(`Listening for in-band signal (${band.start_khz.toFixed(1)}–${band.end_khz.toFixed(1)} kHz, FFT=4096, ctx=${ctx.state})`);
    });
}

armBtn.addEventListener('click', async () => {
    try {
        const context = ensureAudioContext();
        if (context.state === 'suspended') {
            await context.resume();
        }
        // Play a brief silent buffer to fully unlock audio output (iOS Safari quirk).
        const silentBuffer = context.createBuffer(1, Math.round(context.sampleRate * 0.05), context.sampleRate);
        const source = context.createBufferSource();
        source.buffer = silentBuffer;
        source.connect(context.destination);
        source.start();
        // Audible test pip so the user can verify the speaker actually plays.
        const pipBuffer = context.createBuffer(1, Math.round(context.sampleRate * 0.08), context.sampleRate);
        const pipSamples = pipBuffer.getChannelData(0);
        for (let i = 0; i < pipSamples.length; i += 1) {
            pipSamples[i] = 0.25 * Math.sin(2 * Math.PI * 8000 * i / context.sampleRate);
        }
        const fade = Math.round(context.sampleRate * 0.005);
        for (let i = 0; i < fade; i += 1) {
            const g = i / fade;
            pipSamples[i] *= g;
            pipSamples[pipSamples.length - 1 - i] *= g;
        }
        const pipSource = context.createBufferSource();
        pipSource.buffer = pipBuffer;
        pipSource.connect(context.destination);
        pipSource.start(context.currentTime + 0.06);

        audioArmed = true;
        armStatusEl.textContent = 'Yes';
        armStatusEl.className = 'value success';
        armBtn.disabled = true;
        armBtn.textContent = 'Audio Armed';
        log(`Audio armed (context state=${context.state}, sampleRate=${context.sampleRate}). You should hear a brief test pip.`);
        socket.emit('audio_armed', {});
        updateStartButton();
    } catch (error) {
        armStatusEl.textContent = 'Failed';
        armStatusEl.className = 'value error';
        log(`Audio arm failed: ${error.message}`);
    }
});

socket.on('start_trial', async (data) => {
    const { trial_id, start_at_ms, record_window_ms, beep_spec, schedule } = data;
    isBusy = true;
    startBtn.disabled = true;
    if (linkTestBtn) linkTestBtn.disabled = true;
    pendingLinkTest = !!data.link_test;
    setTrialState(pendingLinkTest ? 'Audio link check scheduled' : 'Proximity trial scheduled');
    log(`${pendingLinkTest ? 'Audio link check' : 'Proximity trial'} ${trial_id} scheduled with ${schedule.length} beeps over ${record_window_ms}ms`);

    const screenSession = screenAwake.start();
    try {
        await ensureRunning();
        log(`Trial start: AudioContext state=${audioContext.state}, sampleRate=${audioContext.sampleRate}Hz`);

        // A3.2: measure the clock skew now, in the pre-recording lead-in. Best-effort — if it
        // yields nothing the server uses the full-sweep fallback (A3.3 dual-mode).
        await runTimeProbes();

        const waitMs = Math.max(0, start_at_ms - Date.now());
        if (waitMs > 0) {
            await new Promise((resolve) => setTimeout(resolve, waitMs));
        }

        setTrialState(pendingLinkTest ? 'Recording audio link check' : 'Recording proximity trial');
        const { wav, timings } = await captureAudio(record_window_ms, schedule, beep_spec);

        setTrialState('Uploading');
        const audioBytes = new Uint8Array(await wav.arrayBuffer());
        let binary = '';
        for (let index = 0; index < audioBytes.byteLength; index += 1) {
            binary += String.fromCharCode(audioBytes[index]);
        }
        socket.emit('audio_upload', {
            trial_id,
            audio_base64: btoa(binary),
            metadata: {
                ...getMetadata(),
                trial_timings: timings,
                timing_probe: latestTimingProbe,
                local_role: role,
                schedule,
                beep_spec,
                screen_awake: screenSession.snapshot(),
            },
        });
        setTrialState('Analyzing');
        log('Upload complete, awaiting server analysis');
    } catch (error) {
        isBusy = false;
        pendingLinkTest = false;
        updateStartButton();
        setTrialState('Error');
        log(`Capture failed: ${error.message}`);
    } finally {
        screenSession.finish();
    }
});

socket.on('upload_received', (data) => {
    log(`Server stored upload from ${data.device_id}`);
});

// C2: turn a machine reason/warning slug into a human-readable sentence. Known Phase-2
// guard reasons get a curated phrase; anything unrecognised de-slugs gracefully so a reason
// is NEVER shown as an empty or opaque token ("withheld without a reason" must be impossible).
const REASON_PHRASES = {
    // capture / DSP (A2.7, D3.7)
    clipped: 'Recording saturated (clipping) — level too hot',
    echo_cancellation_enabled: 'Echo cancellation was ON — it destroys the echo signal',
    voice_isolation_enabled: 'Voice isolation was ON — it destroys the echo signal',
    noise_suppression_enabled: 'Noise suppression was ON',
    auto_gain_control_enabled: 'Auto gain control was ON',
    capture_settings_unreported: 'Browser did not report the capture settings',
    echo_cancellation_unreported: 'Echo-cancellation setting not reported by the browser',
    voice_isolation_unreported: 'Voice-isolation setting not reported by the browser',
    possible_aec_suppression: 'Weak self echo; possible audio processing, not confirmed',
    // cross-offset resolution (A2.6/A2.8)
    partner_inaudible: 'Partner device was inaudible (deaf channel)',
    cross_offset_ambiguous: 'Cross-device alignment was ambiguous',
    cross_offset_unresolved: 'Cross-device alignment could not be resolved',
    cross_offset_below_floor: 'Cross-device signal fell below the detection floor',
    // self-alias family (A2.1/A2.2/A2.3/A2.5)
    cross_selection_self_aliased: 'Cross channel locked onto this device’s own echo (self-alias)',
    cross_grid_coherent: 'Cross offset coincides with the device’s own emission grid (self-alias risk)',
    cross_self_similar: 'Cross echo is spectrally identical to the device’s own echo (self-alias)',
    cross_offset_sum_inconsistent: 'The two devices’ offsets violate the timing sum identity',
    self_train_ambiguous: 'This device’s own beep train was ambiguous',
    // channel recovery
    low_period_recovery: 'Too few usable echo periods recovered',
    weak_direct_path: 'Direct chirp was too weak',
    missing_beeps: 'No beeps were recovered',
    insufficient_signature_frequency_points: 'Too few frequency points to form a signature',
    // A3 warnings / alignment notes
    cross_offset_outside_prior: 'Measured alignment disagrees with the timing prior',
    cross_self_energy_implausible: 'Cross/self energy ratio is implausible',
    sweep_train_disagreement: 'Sweep and train alignment disagree',
    sweep_unresolved_train_assigned: 'Independent sweep found no partner although one was assigned',
    sweep_unresolved_under_prior: 'Sweep found no partner within the timing prior’s window',
    cross_partner_in_self_tail: 'Partner beep sits inside this device’s echo tail',
    unassigned_train_in_self_tail: 'An unassigned arrival sits inside the echo tail',
    self_lock_failed: 'Could not lock onto this device’s own beeps',
    no_self_train_in_window: 'No self beep train fell inside the expected latency window',
    no_self_train: 'Could not detect this device’s own beep train',
    self_latency_outside_prior: 'Measured playout latency is outside the expected range',
    no_self_structure_mask: 'No self-echo structure could be masked',
    train_assignment_ambiguous: 'Self/partner beep assignment was ambiguous',
};

function humanizeReason(slug) {
    let core = slug;
    let prefix = '';
    if (core.startsWith('device_a_')) { prefix = 'Device A: '; core = core.slice('device_a_'.length); }
    else if (core.startsWith('device_b_')) { prefix = 'Device B: '; core = core.slice('device_b_'.length); }
    // channel-scoped reasons (AA/AB/BA/BB_...)
    const chanMatch = core.match(/^(AA|AB|BA|BB)_(.*)$/);
    if (chanMatch) { prefix = `Channel ${chanMatch[1]}: `; core = chanMatch[2]; }
    // clipping-localized warning carries a count: clipping_localized_<n>_beeps
    const clipMatch = core.match(/^clipping_localized_(\d+)_beeps$/);
    if (clipMatch) return `${prefix}${clipMatch[1]} beep window(s) dropped for local clipping`;
    let phrase = REASON_PHRASES[core];
    if (!phrase) {
        phrase = core.replace(/_/g, ' ');
        phrase = phrase.charAt(0).toUpperCase() + phrase.slice(1);
    }
    return `${prefix}${phrase}`;
}

function renderReasonList(elementId, blockId, slugs) {
    const list = document.getElementById(elementId);
    const block = document.getElementById(blockId);
    list.innerHTML = '';
    if (!slugs || !slugs.length) {
        block.style.display = 'none';
        return;
    }
    for (const slug of slugs) {
        const li = document.createElement('li');
        li.textContent = humanizeReason(slug);
        const code = document.createElement('span');
        code.className = 'reason-slug';
        code.textContent = ` (${slug})`;
        li.appendChild(code);
        list.appendChild(li);
    }
    block.style.display = 'block';
}

socket.on('trial_result', (data) => {
    isBusy = false;
    pendingLinkTest = false;
    updateStartButton();
    // Keep the always-visible gate badge in sync with the trial's stamped link-test state.
    renderGateBadge(data.link_test);
    const withheld = data.capture_valid === false;
    setTrialState(withheld ? 'Withheld' : (data.success ? 'Accept' : 'Reject'));
    resultsPanel.style.display = 'block';

    document.getElementById('c-a').textContent = data.c_a ?? '-';
    document.getElementById('c-b').textContent = data.c_b ?? '-';
    document.getElementById('pair-score').textContent = data.score ?? '-';
    document.getElementById('pair-verdict').textContent = data.verdict === null ? 'Withheld' : (data.verdict ? 'Accept' : 'Reject');
    document.getElementById('beeps-a').textContent = data.n_beeps_a ?? '-';
    document.getElementById('beeps-b').textContent = data.n_beeps_b ?? '-';

    const capEl = document.getElementById('capture-valid');
    const pill = capEl.querySelector('.capture-pill') || capEl;
    pill.className = `capture-pill ${withheld ? 'invalid' : 'valid'}`;
    pill.textContent = withheld ? 'Invalid — verdict withheld' : 'Valid';

    const alignEl = document.getElementById('alignment-mode');
    if (data.alignment_mode) {
        alignEl.textContent = data.alignment_mode === 'prior_bounded' ? 'Prior-bounded (A3 timing)' : 'Full sweep';
        alignEl.className = 'value';
    } else {
        alignEl.textContent = '-';
    }

    document.getElementById('overall-status').textContent = data.message;
    document.getElementById('overall-status').className = data.success ? 'value success' : 'value warning';

    // C2: surface EVERY failure reason and warning. Guarantee a withheld trial always shows
    // at least one reason, even if the server sent an empty list for some reason.
    let failures = data.measurement_failure_reasons || [];
    if (withheld && !failures.length) {
        failures = ['measurement_invalid_unspecified'];
    }
    renderReasonList('failure-reasons', 'reasons-block', failures);
    renderReasonList('measurement-warnings', 'warnings-block', data.measurement_warnings || []);

    const verdictLabel = data.verdict === null ? 'withheld' : (data.verdict ? 'accept' : 'reject');
    const nFail = failures.length;
    const nWarn = (data.measurement_warnings || []).length;
    log(`Trial ${data.trial_id}: ${data.message}, c_a=${data.c_a}, c_b=${data.c_b}, score=${data.score}, verdict=${verdictLabel}, reasons=${nFail}, warnings=${nWarn}, align=${data.alignment_mode || 'n/a'}`);
});

socket.on('trial_error', (data) => {
    isBusy = false;
    pendingLinkTest = false;
    updateStartButton();
    setTrialState('Error');
    log(`Trial error: ${data.message}`);
});

startBtn.addEventListener('click', () => {
    const payload = trialPayload({});
    socket.emit('start_trial', payload);
    log(`Requested a proximity trial using echo comparison at ${payload.start_khz.toFixed(1)}–${payload.end_khz.toFixed(1)} kHz (tier ${payload.hardware_tier || 'unset'})`);
});

if (linkTestBtn) {
    linkTestBtn.addEventListener('click', () => {
        const payload = trialPayload({ link_test: true });
        socket.emit('start_trial', payload);
        log(`Requested an audio link check for audibility at ${payload.start_khz.toFixed(1)}–${payload.end_khz.toFixed(1)} kHz (tier ${payload.hardware_tier || 'unset'})`);
    });
}

socket.on('link_test_result', (data) => {
    isBusy = false;
    pendingLinkTest = false;
    updateStartButton();
    setTrialState(data.passed ? 'Audio link ready' : 'Audio link weak or unresolved');

    if (linkTestResultsEl) linkTestResultsEl.style.display = 'block';
    const overall = document.getElementById('lt-overall');
    if (overall) {
        overall.className = `gate-badge ${data.passed ? 'pass' : 'fail'}`;
        overall.textContent = data.passed ? 'Audio link ready' : 'Audio link weak or unresolved';
    }
    const ratioAEl = document.getElementById('lt-ratio-a');
    const ratioBEl = document.getElementById('lt-ratio-b');
    if (ratioAEl) {
        ratioAEl.innerHTML = `${fmtRatio(data.ratio_a_hears_b)} <span class="dir-pill ${data.passed_a_hears_b ? 'pass' : 'fail'}">${data.passed_a_hears_b ? 'ready' : 'weak or unresolved'}</span>`;
    }
    if (ratioBEl) {
        ratioBEl.innerHTML = `${fmtRatio(data.ratio_b_hears_a)} <span class="dir-pill ${data.passed_b_hears_a ? 'pass' : 'fail'}">${data.passed_b_hears_a ? 'ready' : 'weak or unresolved'}</span>`;
    }
    const thrEl = document.getElementById('lt-threshold');
    if (thrEl) thrEl.textContent = `R ≥ ${data.min_ratio}`;

    renderGateBadge(data);
    log(`Audio link check ${data.trial_id}: ${data.passed ? 'Audio link ready' : 'Audio link weak or unresolved'}, R_A(A hears B)=${fmtRatio(data.ratio_a_hears_b)}, R_B(B hears A)=${fmtRatio(data.ratio_b_hears_a)}, audibility threshold=${data.min_ratio}`);
});

socket.on('link_test_error', (data) => {
    isBusy = false;
    pendingLinkTest = false;
    updateStartButton();
    setTrialState('Audio link check error');
    log(`Audio link check error: ${data.message}`);
});

// ── Self-echo pipeline test ──────────────────────────────────────────────────

const selfEchoBtn = document.getElementById('self-echo-btn');
const selfEchoResults = document.getElementById('self-echo-results');

let selfEchoBeepSpec = null;
let selfEchoOffsetMs = 200;
let selfEchoRecordMs = 1500;
let selfEchoStartAtMs = 0;

if (selfEchoBtn) {
    selfEchoBtn.addEventListener('click', async () => {
        if (!mediaStream) {
            log('Self-echo: microphone not available — tap Arm Audio first');
            return;
        }
        await ensureRunning();
        log('Requesting self-echo test from server...');
        selfEchoBtn.disabled = true;
        selfEchoBtn.textContent = 'Running...';
        socket.emit('self_echo_test', currentBandKhz());
    });
}

socket.on('prepare_self_echo_test', async (data) => {
    const screenSession = screenAwake.start();
    try {
        selfEchoBeepSpec = data.beep_spec;
        selfEchoOffsetMs = data.beep_offset_ms;
        selfEchoRecordMs = data.record_window_ms;
        selfEchoStartAtMs = data.start_at_ms;

        log(`Self-echo test: beep at +${selfEchoOffsetMs}ms, recording ${selfEchoRecordMs}ms total`);

        const waitMs = Math.max(0, selfEchoStartAtMs - Date.now());
        if (waitMs > 0) {
            await new Promise((resolve) => setTimeout(resolve, waitMs));
        }

        const context = await ensureRunning();
        const beepBuffer = buildBeepBuffer(context, selfEchoBeepSpec);

        const source = context.createMediaStreamSource(mediaStream);
        const processor = context.createScriptProcessor(4096, 1, 1);
        const sink = context.createGain();
        sink.gain.value = 0;
        const chunks = [];
        let stopped = false;

        function cleanup() {
            try { processor.disconnect(); source.disconnect(); sink.disconnect(); } catch (e) { /* ignore */ }
        }

        processor.onaudioprocess = (event) => {
            if (!stopped) {
                chunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));
            }
        };

        source.connect(processor);
        processor.connect(sink);
        sink.connect(context.destination);

        const recordStartAudioTime = context.currentTime;
        const beepSource = context.createBufferSource();
        beepSource.buffer = beepBuffer;
        beepSource.connect(context.destination);
        beepSource.start(recordStartAudioTime + selfEchoOffsetMs / 1000);
        log(`Self-echo: scheduled beep at audio clock +${selfEchoOffsetMs}ms`);

        await new Promise((resolve) => setTimeout(resolve, selfEchoRecordMs));

        stopped = true;
        cleanup();

        const sampleCount = chunks.reduce((total, c) => total + c.length, 0);
        const samples = new Float32Array(sampleCount);
        let offset = 0;
        for (const chunk of chunks) { samples.set(chunk, offset); offset += chunk.length; }

        const rms = sampleCount > 0
            ? Math.sqrt(samples.reduce((acc, s) => acc + s * s, 0) / sampleCount)
            : 0;
        log(`Self-echo captured ${sampleCount} samples, rms=${rms.toFixed(6)}`);

        const wav = encodeMonoWav(samples, context.sampleRate);
        const audioBytes = new Uint8Array(await wav.arrayBuffer());
        let binary = '';
        for (let i = 0; i < audioBytes.byteLength; i++) {
            binary += String.fromCharCode(audioBytes[i]);
        }

        socket.emit('self_echo_upload', {
            audio_base64: btoa(binary),
            beep_spec: selfEchoBeepSpec,
            beep_offset_ms: selfEchoOffsetMs,
        });
        log('Self-echo upload sent, awaiting analysis...');
    } catch (error) {
        selfEchoBtn.disabled = false;
        selfEchoBtn.textContent = 'Test Self-Echo';
        log(`Self-echo capture failed: ${error.message}`);
    } finally {
        screenSession.finish();
    }
});

socket.on('self_echo_result', (data) => {
    selfEchoBtn.disabled = false;
    selfEchoBtn.textContent = 'Test Self-Echo';
    selfEchoResults.style.display = 'block';

    const chirpPeakEl = document.getElementById('se-chirp-peak');
    const echoPeakEl = document.getElementById('se-echo-peak');
    const echoEnergyEl = document.getElementById('se-echo-energy');
    const selOkEl = document.getElementById('se-selection-ok');

    chirpPeakEl.textContent = data.chirp_peak ?? '-';
    chirpPeakEl.className = (data.chirp_peak > 5) ? 'value success' : (data.chirp_peak > 0.5 ? 'value warning' : 'value error');

    echoPeakEl.textContent = data.echo_peak ?? '-';
    echoPeakEl.className = (data.echo_peak > 1) ? 'value success' : (data.echo_peak > 0 ? 'value warning' : 'value');

    echoEnergyEl.textContent = data.echo_energy ?? '-';
    echoEnergyEl.className = (data.echo_energy > 0) ? 'value success' : 'value warning';

    selOkEl.textContent = data.selection_ok ? 'Yes' : 'No';
    selOkEl.className = data.selection_ok ? 'value success' : 'value warning';

    // Draw spectrum on canvas
    const canvas = document.getElementById('se-spectrum-canvas');
    if (canvas && data.spectrum_energy && data.spectrum_energy.length > 0) {
        const ctx = canvas.getContext('2d');
        const W = canvas.width;
        const H = canvas.height;
        ctx.clearRect(0, 0, W, H);

        const energies = data.spectrum_energy;
        const freqs = data.spectrum_freqs;
        const maxE = Math.max(...energies, 1e-12);
        const n = energies.length;
        const barW = Math.max(1, Math.floor(W / n));

        for (let i = 0; i < n; i++) {
            const barH = Math.round((energies[i] / maxE) * (H - 4));
            const x = Math.round((i / n) * W);
            const hue = 200 + Math.round((i / n) * 60); // blue → teal
            ctx.fillStyle = `hsl(${hue}, 80%, 55%)`;
            ctx.fillRect(x, H - barH, barW - 1, barH);
        }

        // Frequency labels at start and end
        ctx.fillStyle = '#94a3b8';
        ctx.font = '11px monospace';
        if (freqs && freqs.length > 0) {
            ctx.fillText(`${Math.round(freqs[0])} Hz`, 3, H - 3);
            const lastLabel = `${Math.round(freqs[freqs.length - 1])} Hz`;
            ctx.fillText(lastLabel, W - ctx.measureText(lastLabel).width - 3, H - 3);
        }
    }

    log(`Self-echo result: chirp_peak=${data.chirp_peak}, echo_peak=${data.echo_peak}, echo_energy=${data.echo_energy}, ok=${data.selection_ok}`);
});

socket.on('self_echo_error', (data) => {
    if (selfEchoBtn) {
        selfEchoBtn.disabled = false;
        selfEchoBtn.textContent = 'Test Self-Echo';
    }
    log(`Self-echo error: ${data.message}`);
});
