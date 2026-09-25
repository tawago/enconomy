(function (root, factory) {
    const api = factory(root);
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.RangingAudio = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
    'use strict';

    const REQUESTED_AUDIO = {
        channelCount: { ideal: 1 }, sampleRate: { ideal: 48000 },
        echoCancellation: false, noiseSuppression: false, autoGainControl: false,
    };
    const WORKLET_URL = '/static/ranging-recorder-worklet.js';
    let context = null;
    let stream = null;
    let arming = null;
    let active = null;
    let generation = 0;
    const pendingContexts = new Set();

    function errorWithCode(message, code) {
        const error = new Error(message);
        error.code = code;
        return error;
    }

    function abortError(reason) {
        const error = errorWithCode(String(reason || 'Capture cancelled'), 'capture_cancelled');
        error.name = 'AbortError';
        return error;
    }

    function outputStatus(audioContext) {
        const destination = audioContext?.destination;
        return {
            destination_channel_count: destination?.channelCount ?? null,
            destination_max_channel_count: destination?.maxChannelCount ?? null,
            destination_channel_interpretation: destination?.channelInterpretation ?? null,
        };
    }

    function checkOutputChannel(outputChannel = 'default') {
        if (!['default', 'left', 'right'].includes(outputChannel)) {
            throw errorWithCode('Unknown playback channel', 'invalid_output_channel');
        }
        const output = outputStatus(context);
        if (outputChannel !== 'default' && (output.destination_channel_count !== 2
                || !(output.destination_max_channel_count >= 2))) {
            throw errorWithCode('Left/right playback requires a stereo browser output. Keep this result for review; do not substitute another mode.', 'stereo_output_unavailable');
        }
        return { requested_output_channel: outputChannel,
            source_channel_count: outputChannel === 'default' ? 1 : 2,
            source_channel_gains: outputChannel === 'default' ? [1] : outputChannel === 'left' ? [1, 0] : [0, 1],
            physical_speaker_mapping: 'unknown; the operating system or hardware may remix channels',
            ...output };
    }

    function status() {
        const track = stream?.getAudioTracks()[0];
        return {
            armed: Boolean(context?.state === 'running' && track?.readyState === 'live' && !track.muted),
            context_state: context?.state || 'absent',
            sample_rate: context?.sampleRate || null,
            audio_worklet: Boolean(context?.audioWorklet),
            track_settings: track?.getSettings?.() || {},
            requested_constraints: REQUESTED_AUDIO,
            capture_active: Boolean(active),
            output: outputStatus(context),
        };
    }

    async function closeResources(audioContext, mediaStream) {
        for (const track of mediaStream?.getTracks() || []) track.stop();
        if (audioContext && audioContext.state !== 'closed') await audioContext.close();
    }

    function arm() {
        if (arming) return arming;
        if (status().armed) return Promise.resolve(status());
        if (active) return Promise.reject(errorWithCode('A capture is already running', 'capture_busy'));
        if (root.isSecureContext === false) {
            return Promise.reject(errorWithCode('Microphone capture requires HTTPS or localhost', 'secure_context_required'));
        }
        const AudioContext = root.AudioContext || root.webkitAudioContext;
        if (!AudioContext || !root.AudioWorkletNode || !root.navigator?.mediaDevices?.getUserMedia) {
            return Promise.reject(errorWithCode('This browser does not support AudioWorklet microphone capture', 'audio_worklet_unavailable'));
        }
        const token = ++generation;
        const previousContext = context;
        const previousStream = stream;
        context = null;
        stream = null;
        // Create and resume in the user's click handler, before awaiting permission.
        let candidate;
        try {
            candidate = new AudioContext({ latencyHint: 'interactive', sampleRate: 48000 });
        } catch (error) {
            return closeResources(previousContext, previousStream).then(() => { throw error; });
        }
        if (!candidate.audioWorklet) {
            return Promise.all([closeResources(candidate), closeResources(previousContext, previousStream)]).then(() => {
                throw errorWithCode('AudioWorklet is unavailable; no alternate recorder will be used', 'audio_worklet_unavailable');
            });
        }
        pendingContexts.add(candidate);
        const resumed = candidate.resume();
        arming = (async () => {
            let candidateStream = null;
            try {
                const results = await Promise.allSettled([
                    resumed,
                    candidate.audioWorklet.addModule(WORKLET_URL),
                    root.navigator.mediaDevices.getUserMedia({ audio: REQUESTED_AUDIO, video: false }).then((value) => {
                        candidateStream = value;
                        if (token !== generation) for (const track of value.getTracks()) track.stop();
                        return value;
                    }),
                    closeResources(previousContext, previousStream),
                ]);
                if (results[2].status === 'fulfilled') candidateStream = results[2].value;
                const failure = results.find((result) => result.status === 'rejected');
                if (failure) throw failure.reason;
                if (token !== generation) throw abortError('Audio arming was cancelled');
                const track = candidateStream?.getAudioTracks()[0];
                if (candidate.state !== 'running' || track?.readyState !== 'live' || track.muted) {
                    throw errorWithCode('Audio did not become ready; tap Arm again', 'audio_not_running');
                }
                context = candidate;
                stream = candidateStream;
                return status();
            } catch (error) {
                await closeResources(candidate, candidateStream);
                throw error;
            } finally {
                pendingContexts.delete(candidate);
                if (token === generation) arming = null;
            }
        })();
        return arming;
    }

    function decodeSamples(encoded, frameCount) {
        if (typeof encoded !== 'string' || encoded.length !== Math.ceil(frameCount * 4 / 3) * 4
                || !/^[A-Za-z0-9+/]+={0,2}$/.test(encoded)) {
            throw errorWithCode('Invalid encoded template length', 'invalid_protocol');
        }
        let binary;
        try { binary = root.atob(encoded); }
        catch (_) { throw errorWithCode('Invalid encoded template', 'invalid_protocol'); }
        if (binary.length !== frameCount * 4) {
            throw errorWithCode('Template sample count does not match the protocol', 'invalid_protocol');
        }
        const bytes = new Uint8Array(binary.length);
        for (let index = 0; index < binary.length; index++) bytes[index] = binary.charCodeAt(index);
        const view = new DataView(bytes.buffer);
        const samples = new Float32Array(frameCount);
        for (let index = 0; index < frameCount; index++) {
            const value = view.getFloat32(index * 4, true);
            if (!Number.isFinite(value) || Math.abs(value) > 0.2) {
                throw errorWithCode('Template contains invalid or excessive samples', 'invalid_protocol');
            }
            samples[index] = value;
        }
        return { bytes, samples };
    }

    function protocolMetadata(protocol) {
        return {
            protocol_version: protocol.version,
            profile: protocol.profile || 'coded-probes',
            protocol_id: protocol.protocol_id,
            session_id: protocol.session_id,
            protocol_duration_s: protocol.duration_s,
            protocol_probe_frames: protocol.probe_frames,
            protocol_band_hz: [...protocol.band_hz],
            reference_offset_frames: protocol.reference_offset_frames ?? 0,
        };
    }

    async function prepareTemplates(protocol) {
        const reference = protocol?.version === 'beepbeep-v1';
        const legacy = protocol?.version === 'ranging-v1';
        const pairGaps = [.26, .40, .55, .70, .30, .65, .45, .80];
        const expectedOffsets = [];
        let nextFrame = reference ? 48000 : 38400;
        for (let index = 0; index < 16; index++) {
            expectedOffsets.push(nextFrame);
            nextFrame += reference ? 48000 : Math.round((index % 2 ? .40 : pairGaps[Math.floor(index / 2)]) * 48000);
        }
        const probeFrames = reference ? 2640 : 1536;
        const durationFrames = expectedOffsets[15] + probeFrames + (reference ? 48000 : 38400);
        if ((!reference && !legacy) || protocol.sample_format !== 'float32-le'
                || (reference ? protocol.profile !== 'beepbeep-reference' : ![undefined, 'coded-probes'].includes(protocol.profile))
                || protocol.sample_rate !== 48000 || protocol.probe_frames !== probeFrames
                || protocol.duration_frames !== durationFrames || protocol.duration_s !== durationFrames / 48000
                || protocol.pre_roll_s !== (reference ? 1 : .8) || protocol.post_roll_s !== (reference ? 1 : .8)
                || protocol.peak_amplitude !== .16
                || !Array.isArray(protocol.band_hz) || protocol.band_hz.length !== 2
                || protocol.band_hz[0] !== (reference ? 2000 : 4000) || protocol.band_hz[1] !== (reference ? 6000 : 9000)
                || !/^[0-9a-f]{64}$/.test(protocol.protocol_id || '')
                || typeof protocol.session_id !== 'string' || !protocol.session_id || protocol.session_id.length > 256
                || typeof protocol.seed !== 'string' || protocol.seed.length > 256
                || (reference && (protocol.reference_offset_frames !== 240 || protocol.reference_frames !== 2400))
                || !Array.isArray(protocol.pair_gaps_s) || protocol.pair_gaps_s.length !== 8
                || protocol.pair_gaps_s.some((gap, index) => gap !== (reference ? 1 : pairGaps[index]))
                || (reference && (protocol.slot_interval_s !== 1
                    || protocol.attribution?.window_origin !== 'first_sample_of_each_original_recording'
                    || protocol.attribution?.window_target !== 'chirp_onset'
                    || protocol.attribution?.precontext_s !== .060 || protocol.attribution?.boundary_guard_s !== .010
                    || protocol.attribution?.early_bound_s !== .20 || protocol.attribution?.late_bound_s !== .45
                    || protocol.attribution?.identity !== 'schedule_consistent_only_not_acoustically_verified'
                    || protocol.attribution?.acoustic_freshness !== false))
                || !Array.isArray(protocol.emissions) || protocol.emissions.length !== 16) {
            throw errorWithCode('Unsupported or malformed ranging protocol', 'invalid_protocol');
        }
        if (!root.crypto?.subtle) throw errorWithCode('Template checksum verification is unavailable', 'checksum_unavailable');
        const checksums = new Set();
        return Promise.all(protocol.emissions.map(async (emission, index) => {
            if (!emission || emission.id !== `e${String(index).padStart(2, '0')}` || emission.index !== index
                    || emission.pair_index !== Math.floor(index / 2)
                    || emission.emitter !== (index % 2 ? 'B' : 'A')
                    || emission.role !== (index % 2 ? 'observer' : 'initiator')
                    || emission.offset_samples !== expectedOffsets[index]
                    || emission.offset_s !== expectedOffsets[index] / protocol.sample_rate
                    || !/^[0-9a-f]{64}$/.test(emission.sha256 || '')
                    || (reference && (!Array.isArray(emission.search_window_s) || emission.search_window_s.length !== 2
                        || !emission.search_window_s.every(Number.isFinite)
                        || Math.abs(emission.search_window_s[0] - (emission.offset_s - .20)) > 1e-9
                        || Math.abs(emission.search_window_s[1] - (emission.offset_s + .45)) > 1e-9))) {
                throw errorWithCode('Invalid emission identity or schedule', 'invalid_protocol');
            }
            if (reference ? emission.sha256 !== protocol.emissions[0]?.sha256 : checksums.has(emission.sha256)) {
                throw errorWithCode(reference ? 'Reference probes must all contain identical bytes' : 'Coded probes must have distinct templates', 'invalid_protocol');
            }
            checksums.add(emission.sha256);
            const { bytes, samples } = decodeSamples(emission.samples_b64, protocol.probe_frames);
            const digest = new Uint8Array(await root.crypto.subtle.digest('SHA-256', bytes));
            const checksum = Array.from(digest, (value) => value.toString(16).padStart(2, '0')).join('');
            if (checksum !== emission.sha256) throw errorWithCode('Template checksum mismatch', 'invalid_protocol');
            return { emission, samples };
        }));
    }

    async function prepare(protocol) {
        await prepareTemplates(protocol);
        return protocolMetadata(protocol);
    }

    function floatWav(chunks, frameCount, sampleRate) {
        // IEEE float WAV preserves AudioWorklet PCM, including amplitudes beyond 1.
        const buffer = new ArrayBuffer(56 + frameCount * 4);
        const view = new DataView(buffer);
        const ascii = (offset, value) => {
            for (let index = 0; index < value.length; index++) view.setUint8(offset + index, value.charCodeAt(index));
        };
        ascii(0, 'RIFF'); view.setUint32(4, buffer.byteLength - 8, true); ascii(8, 'WAVE');
        ascii(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 3, true);
        view.setUint16(22, 1, true); view.setUint32(24, sampleRate, true);
        view.setUint32(28, sampleRate * 4, true); view.setUint16(32, 4, true); view.setUint16(34, 32, true);
        ascii(36, 'fact'); view.setUint32(40, 4, true); view.setUint32(44, frameCount, true);
        ascii(48, 'data'); view.setUint32(52, frameCount * 4, true);
        let offset = 56;
        for (const chunk of chunks) {
            for (const value of chunk) {
                view.setFloat32(offset, value, true);
                offset += 4;
            }
        }
        if (offset !== buffer.byteLength) throw errorWithCode('WAV sample count mismatch', 'capture_corrupt');
        return new root.Blob([buffer], { type: 'audio/wav' });
    }

    async function capture(protocol, role, options = {}) {
        if (role !== 'initiator' && role !== 'observer') throw errorWithCode('Unknown participant role', 'invalid_role');
        if (active) throw errorWithCode('A capture is already running', 'capture_busy');
        if (!status().armed) throw errorWithCode('Tap Arm before recording', 'audio_not_armed');
        const output = checkOutputChannel(options.outputChannel ?? 'default');
        const audioContext = context;
        const mediaStream = stream;
        const track = mediaStream.getAudioTracks()[0];
        const controller = new root.AbortController();
        const operation = { cancel: (reason) => controller.abort(reason) };
        active = operation;
        const chunks = [];
        const removers = [];
        const sources = [];
        let recorder = null;
        let microphone = null;
        let silentOutput = null;
        let frameCount = 0;
        let expectedContextFrame = null;
        let timeout = null;
        let stopTimeout = null;
        const startedAtMs = Date.now();
        const requestedDelayMs = options.startAtUnixMs !== undefined
            ? Number(options.startAtUnixMs) - startedAtMs : Number(options.startAfterMs ?? 200);
        const startFrame = Math.ceil((audioContext.currentTime + requestedDelayMs / 1000) * audioContext.sampleRate);
        const metadata = {
            recorder_version: 'audio-worklet-v2',
            protocol_id: protocol?.protocol_id,
            session_id: protocol?.session_id,
            role, emitter: role === 'initiator' ? 'A' : 'B',
            sample_rate: audioContext.sampleRate, channel_count: 1, sample_format: 'float32-le',
            pcm_source: 'AudioWorklet microphone input after browser processing and any capture resampling',
            continuity_scope: 'AudioWorklet frame continuity only; underlying driver loss or resampling cannot be inferred from these counters',
            channel_selection: 'first input channel; mono requested',
            recording_complete: false,
            capture_start_context_frame: startFrame,
            capture_start_context_time: startFrame / audioContext.sampleRate,
            frame_count: 0, expected_frame_count: 0,
            requested_at_unix_ms: startedAtMs,
            schedule: { start_after_ms: requestedDelayMs, start_at_unix_ms: options.startAtUnixMs ?? null,
                coordination_target_unix_ms: options.coordinationTargetUnixMs ?? null,
                timing_use: 'Coordination only; wall time is not an acoustic arrival timestamp' },
            requested_constraints: REQUESTED_AUDIO,
            track_settings: track.getSettings?.() || {},
            track_constraints: track.getConstraints?.() || {},
            route: { input_label: track.label || null, input_id: track.getSettings?.().deviceId || null,
                output_sink_id: audioContext.sinkId ?? null, output_route_known: Boolean(audioContext.sinkId) },
            context: { sample_rate: audioContext.sampleRate, base_latency_s: audioContext.baseLatency ?? null,
                output_latency_s: audioContext.outputLatency ?? null, initial_state: audioContext.state },
            browser: { user_agent: root.navigator.userAgent || '', platform: root.navigator.platform || '',
                language: root.navigator.language || '' },
            playback: { sample_rate: protocol?.sample_rate, gain: 1, source_samples: 'server float32 bytes',
                context_resampling: protocol?.sample_rate !== audioContext.sampleRate, ...output, emissions: [] },
            blocks: [], discontinuities: [], missing_frames: 0, missing_input_frames: 0,
            clipping: { threshold: 0.999, peak: 0, clipped_samples: 0, fraction: 0 },
            nonfinite_samples: 0, context_events: [], visibility_events: [], track_events: [], route_events: [],
            page_hidden: root.document?.visibilityState === 'hidden',
        };
        const eventStamp = () => ({ unix_ms: Date.now(), context_time: audioContext.currentTime });
        const outputChanged = () => Object.entries(outputStatus(audioContext)).some(([key, value]) => output[key] !== value);
        const listen = (target, name, handler) => {
            target?.addEventListener?.(name, handler);
            removers.push(() => target?.removeEventListener?.(name, handler));
        };
        const onExternalAbort = () => controller.abort(options.signal.reason);
        if (options.signal?.aborted) controller.abort(options.signal.reason);
        else listen(options.signal, 'abort', onExternalAbort);
        function stopPlayback() {
            for (const source of sources) {
                try { source.stop(); } catch (_) { /* A source may already have ended. */ }
            }
        }
        function result() {
            metadata.frame_count = frameCount;
            metadata.clipping.fraction = frameCount ? metadata.clipping.clipped_samples / frameCount : 0;
            metadata.track_settings_end = track.getSettings?.() || {};
            metadata.context.final_state = audioContext.state;
            metadata.playback.output_at_end = outputStatus(audioContext);
            return { wav: floatWav(chunks, frameCount, audioContext.sampleRate), metadata };
        }
        try {
            if (!Number.isFinite(requestedDelayMs) || requestedDelayMs < 50 || requestedDelayMs > 10000) {
                throw errorWithCode('Capture start must be between 50 ms and 10 seconds in the future', 'invalid_start_time');
            }
            if (options.coordinationTargetUnixMs != null
                    && (!Number.isFinite(options.coordinationTargetUnixMs) || options.coordinationTargetUnixMs <= 0)) {
                throw errorWithCode('Invalid server coordination target', 'invalid_start_time');
            }
            const templates = await prepareTemplates(protocol);
            Object.assign(metadata, protocolMetadata(protocol));
            if (controller.signal.aborted) throw abortError(controller.signal.reason);
            if (audioContext.state !== 'running' || audioContext.currentTime > startFrame / audioContext.sampleRate - 0.02) {
                throw errorWithCode('Audio was not ready before the scheduled recording start', 'late_capture_start');
            }
            const expectedFrames = Math.round(protocol.duration_s * audioContext.sampleRate);
            metadata.expected_frame_count = expectedFrames;
            metadata.capture_end_context_frame = startFrame + expectedFrames;
            expectedContextFrame = startFrame;
            recorder = new root.AudioWorkletNode(audioContext, 'ranging-recorder', {
                numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1],
                channelCount: 1, channelCountMode: 'explicit', channelInterpretation: 'discrete',
                processorOptions: { startFrame, endFrame: startFrame + expectedFrames },
            });
            microphone = audioContext.createMediaStreamSource(mediaStream);
            silentOutput = audioContext.createGain();
            silentOutput.gain.value = 0;
            // A connected output keeps the processor active; it carries only silence.
            microphone.connect(recorder);
            recorder.connect(silentOutput);
            silentOutput.connect(audioContext.destination);

            return await new Promise((resolve, reject) => {
                let finished = false;
                let failure = null;
                const finish = (complete) => {
                    if (finished) return;
                    finished = true;
                    stopPlayback();
                    if (outputChanged() && !failure) {
                        metadata.playback.output_changed = true;
                        failure = errorWithCode('Browser output channels changed during capture', 'output_route_changed');
                    }
                    if (complete && expectedContextFrame < startFrame + expectedFrames) {
                        const gap = startFrame + expectedFrames - expectedContextFrame;
                        metadata.discontinuities.push({ expected_context_frame: expectedContextFrame,
                            actual_context_frame: startFrame + expectedFrames, gap_frames: gap, position: 'end' });
                        metadata.missing_frames += gap;
                    }
                    metadata.finished_at_unix_ms = Date.now();
                    metadata.recording_complete = complete && !failure && frameCount === expectedFrames
                        && metadata.discontinuities.length === 0 && metadata.missing_input_frames === 0
                        && metadata.nonfinite_samples === 0;
                    if (failure) reject(failure);
                    else resolve(result());
                };
                const fail = (error) => {
                    if (finished || failure) return;
                    failure = error;
                    metadata.capture_error = { code: error.code || error.name, message: error.message };
                    stopPlayback();
                    recorder.port.postMessage({ type: 'stop' });
                    // A suspended worklet may not acknowledge. Retain delivered blocks.
                    stopTimeout = root.setTimeout(() => finish(false), 150);
                };
                listen(controller.signal, 'abort', () => fail(abortError(controller.signal.reason)));
                listen(audioContext, 'statechange', () => {
                    metadata.context_events.push({ ...eventStamp(), state: audioContext.state });
                    if (audioContext.state !== 'running') fail(errorWithCode('Audio context was interrupted', 'context_interrupted'));
                });
                listen(audioContext, 'sinkchange', () => {
                    metadata.route_events.push({ ...eventStamp(), state: 'sinkchange', output: outputStatus(audioContext) });
                    metadata.playback.output_changed = true;
                    fail(errorWithCode('Audio output changed during capture', 'output_route_changed'));
                });
                metadata.context_events.push({ ...eventStamp(), state: audioContext.state });
                listen(root.document, 'visibilitychange', () => {
                    const visibility = root.document.visibilityState;
                    metadata.visibility_events.push({ ...eventStamp(), state: visibility });
                    if (visibility !== 'visible') metadata.page_hidden = true;
                });
                metadata.visibility_events.push({ ...eventStamp(), state: root.document?.visibilityState || 'unknown' });
                for (const event of ['mute', 'unmute', 'ended']) {
                    listen(track, event, () => {
                        metadata.track_events.push({ ...eventStamp(), state: event, type: event });
                        if (event !== 'unmute') fail(errorWithCode(`Microphone ${event}`, 'microphone_interrupted'));
                    });
                }
                listen(root.navigator.mediaDevices, 'devicechange', () => {
                    metadata.route_events.push({ ...eventStamp(), state: 'devicechange', settings: track.getSettings?.() || {} });
                });
                listen(root, 'pagehide', () => fail(errorWithCode('Page left during capture', 'page_left')));
                listen(recorder, 'processorerror', () => fail(errorWithCode('AudioWorklet recorder failed', 'worklet_failed')));
                recorder.port.onmessage = ({ data }) => {
                    if (finished) return;
                    if (data.type === 'samples') {
                        const samples = data.samples;
                        if (!(samples instanceof Float32Array) || !Array.isArray(data.blocks)) {
                            fail(errorWithCode('Recorder returned invalid PCM data', 'capture_corrupt'));
                            return;
                        }
                        let packetFrames = 0;
                        for (const block of data.blocks) {
                            if (block.start_frame !== frameCount + packetFrames || block.index !== metadata.blocks.length
                                    || !Number.isSafeInteger(block.frame_count) || block.frame_count <= 0) {
                                fail(errorWithCode('Recorder block sequence is inconsistent', 'capture_corrupt'));
                                return;
                            }
                            if (block.context_frame !== expectedContextFrame) {
                                const gap = block.context_frame - expectedContextFrame;
                                metadata.discontinuities.push({ block_index: block.index, expected_context_frame: expectedContextFrame,
                                    actual_context_frame: block.context_frame, gap_frames: gap });
                                metadata.missing_frames += Math.max(0, gap);
                            }
                            expectedContextFrame = block.context_frame + block.frame_count;
                            packetFrames += block.frame_count;
                            metadata.missing_input_frames += block.missing_input_frames || 0;
                            metadata.nonfinite_samples += block.nonfinite_samples || 0;
                            metadata.clipping.peak = Math.max(metadata.clipping.peak, block.peak);
                            metadata.clipping.clipped_samples += block.clipped_samples;
                            metadata.blocks.push(block);
                        }
                        if (packetFrames !== samples.length || frameCount + samples.length > expectedFrames) {
                            fail(errorWithCode('Recorder packet length is inconsistent', 'capture_corrupt'));
                            return;
                        }
                        chunks.push(samples);
                        frameCount += samples.length;
                        if (outputChanged()) {
                            metadata.playback.output_changed = true;
                            fail(errorWithCode('Browser output channels changed during capture', 'output_route_changed'));
                            return;
                        }
                        if (typeof options.onProgress === 'function') {
                            try {
                                options.onProgress({ frame_count: frameCount, expected_frame_count: expectedFrames,
                                    fraction: frameCount / expectedFrames });
                            } catch (error) { fail(error); }
                        }
                    } else if (data.type === 'complete') {
                        if (data.frame_count !== frameCount) fail(errorWithCode('Recorder completion count is inconsistent', 'capture_corrupt'));
                        else finish(true);
                    } else if (data.type === 'stopped') finish(false);
                };
                for (const { emission, samples } of templates) {
                    if (emission.role !== role) continue;
                    // Preserve the exact probe amplitude. A stereo buffer's other
                    // channel stays zero; a mono buffer keeps the original upmix.
                    const buffer = audioContext.createBuffer(output.source_channel_count, samples.length, protocol.sample_rate);
                    buffer.getChannelData(output.requested_output_channel === 'right' ? 1 : 0).set(samples);
                    const source = audioContext.createBufferSource();
                    source.buffer = buffer;
                    source.connect(audioContext.destination);
                    const scheduledTime = startFrame / audioContext.sampleRate + emission.offset_samples / protocol.sample_rate;
                    sources.push(source);
                    source.start(scheduledTime);
                    metadata.playback.emissions.push({ id: emission.id, pair_index: emission.pair_index,
                        scheduled_context_time: scheduledTime, source_sample_rate: protocol.sample_rate, sha256: emission.sha256 });
                }
                timeout = root.setTimeout(() => fail(errorWithCode('Recorder did not finish by its deadline', 'capture_timeout')),
                    requestedDelayMs + protocol.duration_s * 1000 + 2500);
                if (controller.signal.aborted) fail(abortError(controller.signal.reason));
            });
        } catch (error) {
            metadata.recording_complete = false;
            metadata.capture_error = { code: error.code || error.name, message: error.message };
            metadata.finished_at_unix_ms = Date.now();
            const partial = result();
            error.metadata = metadata;
            if (frameCount) error.partial = partial;
            throw error;
        } finally {
            stopPlayback();
            for (const remove of removers) remove();
            if (timeout !== null) root.clearTimeout(timeout);
            if (stopTimeout !== null) root.clearTimeout(stopTimeout);
            if (recorder) {
                recorder.port.onmessage = null;
                recorder.port.postMessage({ type: 'stop' });
                recorder.port.close();
                recorder.disconnect();
            }
            microphone?.disconnect();
            silentOutput?.disconnect();
            for (const source of sources) source.disconnect();
            if (active === operation) active = null;
        }
    }

    function cancel(reason) {
        if (!active) return false;
        active.cancel(reason || 'Capture cancelled');
        return true;
    }

    async function release() {
        generation += 1;
        arming = null;
        cancel('Audio released');
        const oldContext = context;
        const oldStream = stream;
        context = null;
        stream = null;
        await Promise.all([closeResources(oldContext, oldStream),
            ...Array.from(pendingContexts, (candidate) => closeResources(candidate))]);
    }

    root.addEventListener?.('pagehide', () => { void release(); });
    return { arm, prepare, capture, cancel, release, getStatus: status, checkOutputChannel };
}));
