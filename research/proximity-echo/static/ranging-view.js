(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.RangingView = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';
    function number(value, digits = 3) {
        return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—';
    }
    function savedReportSpec(search) {
        const params = new URLSearchParams(search);
        if (!params.has('trial') && !params.has('report')) return null;
        const trialId = params.get('trial'), filename = params.get('report') || 'report.json';
        if (!/^[0-9a-f]{32}$/.test(trialId || '') || !/^(report|reanalysis_[0-9a-f]{32})\.json$/.test(filename)) {
            throw new Error('Invalid saved report link');
        }
        const base = `/ranging/trials/${trialId}`;
        return { trialId, filename, reportUrl: `${base}/${filename}`, manifestUrl: `${base}/manifest.json` };
    }
    function integritySpans(report) {
        return ['A', 'B'].flatMap(receiver => (report.recordings?.[receiver]?.pcm_integrity?.spans || [])
            .map(span => ({ ...span, receiver })));
    }
    function playbackDescription(report) {
        const names = { default: 'Default mono', left: 'Left only', right: 'Right only' };
        return ['A', 'B'].map(receiver => {
            const playback = report.recordings?.[receiver]?.playback;
            const mode = names[playback?.requested_output_channel] || 'not recorded';
            return `Device ${receiver}: ${mode}`;
        }).join(' · ') + '. Requested audio channels, not verified physical speakers.';
    }
    function profileDetails(profile) {
        if (profile === 'beepbeep-reference') return {
            name: 'BeepBeep reference', version: 'beepbeep-v1', duration: 17.055,
            description: 'BeepBeep reference · 17.055 s capture · 2 to 6 kHz. Sixteen identical beeps alternate between devices, one second apart. Each beep has a 5 ms warmup and a 50 ms chirp.',
        };
        if (profile === 'coded-probes') return {
            name: 'Coded probes', version: 'ranging-v1', duration: 8.542,
            description: 'Coded probes · 8.542 s capture · 4 to 9 kHz. Sixteen distinct 32 ms probes alternate between devices.',
        };
        return null;
    }
    function reportProfile(report) {
        if (report?.profile != null) return report.profile;
        if (report?.protocol_version === 'ranging-v1') return 'coded-probes';
        if (report?.protocol_version === 'beepbeep-v1') return 'beepbeep-reference';
        return null;
    }
    function recordedProfileDescription(report) {
        const details = profileDetails(reportProfile(report));
        return details ? `Recorded profile: ${details.description} Protocol ${report.protocol_version || details.version}.`
            : 'This report does not identify its recorded profile.';
    }
    function beepDiagnosticView(report) {
        if (reportProfile(report) !== 'beepbeep-reference') return null;
        return {
            summary: 'Times locate the start of the 50 ms chirp, after the 5 ms warmup. Repeated beeps share one template; slot attribution checks scheduling consistency and cannot verify the sound source. These checks do not calibrate physical distance.',
            rows: (report.arrivals || []).map(arrival => {
                const detector = arrival.detector || {};
                const window = arrival.attribution?.search_window_s;
                const slot = Array.isArray(window) && window.length === 2 ? `${number(window[0])} to ${number(window[1])}` : '—';
                const reasons = [...new Set([
                    ...(Array.isArray(arrival.reasons) ? arrival.reasons : []),
                    ...(Array.isArray(arrival.attribution?.reasons) ? arrival.attribution.reasons : []),
                    detector.reason,
                ].filter(reason => typeof reason === 'string' && reason))].map(reason => reason.replaceAll('_', ' '));
                return [arrival.emission_id, arrival.receiver, arrival.quality || 'Not recorded', slot, number(arrival.attribution?.event_count, 0),
                    detector.noise_is_exact_zero === true ? 'Exact zero background' : number(detector.signal_noise_norm_ratio),
                    number(detector.selected_relative_to_strongest_samples, 0), reasons.join('; ') || 'No detector reason recorded'];
            }),
        };
    }
    function responseDiagnosticView(report) {
        const diagnostic = report?.response_diagnostic;
        if (!diagnostic || typeof diagnostic !== 'object' || Array.isArray(diagnostic)) return null;
        const object = value => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
        const available = diagnostic.status === 'exploratory';
        const view = {
            available,
            version: typeof diagnostic.version === 'string' ? diagnostic.version : 'Unknown response analysis version',
            summary: 'Independent response analysis is unavailable.',
            bands: [], channels: [], stepCandidates: [],
            reasons: Array.isArray(diagnostic.reasons) ? diagnostic.reasons.filter(reason => typeof reason === 'string').map(reason => reason.replaceAll('_', ' ')) : [],
        };
        if (!available) return view;
        const clocks = object(diagnostic.clock_by_band), full = object(clocks['4250-8750']);
        view.summary = `Full band, 4250-8750 Hz. Alignment drift ${number(full.relative_rate_ppm)} ppm. `
            + `Model-fit residual RMS ${number(full.rms_ms, 6)} ms; maximum ${number(full.max_abs_ms, 6)} ms. `
            + 'These residuals do not measure physical timing accuracy.';
        const bands = Object.keys(clocks).sort((a, b) => a === b ? 0 : a === '4250-8750' ? -1 : b === '4250-8750' ? 1 : a.localeCompare(b));
        for (const band of bands) {
            const clock = object(clocks[band]), emitters = object(clock.by_emitter_ppm);
            view.bands.push([band, number(clock.relative_rate_ppm), number(emitters.A), number(emitters.B), number(clock.rms_ms, 6), number(clock.max_abs_ms, 6)]);
            if (clock.best_step_diagnostic && typeof clock.best_step_diagnostic === 'object' && !Array.isArray(clock.best_step_diagnostic)) {
                const step = clock.best_step_diagnostic;
                const boundary = typeof step.first_after_emission === 'string' ? `before ${step.first_after_emission}` : 'at an unspecified boundary';
                view.stepCandidates.push(`${band} Hz: candidate step ${number(step.step_ms, 6)} ms ${boundary}; model-fit RMS with step ${number(step.residual_rms_ms, 6)} ms.`);
            }
        }
        const channels = object(diagnostic.channels);
        for (const path of ['AA', 'AB', 'BA', 'BB']) {
            const channel = object(channels[path]);
            view.channels.push([`${path[0]} to ${path[1]}`, number(channel.complex_coherence_across_probes?.median), number(channel.held_out_band_waveform_explained_energy?.median)]);
        }
        return view;
    }
    function diagnosticNotes(report) {
        const notes = [];
        const unresolved = (report.arrivals || []).filter(arrival => arrival.close_peak_diagnostics?.unresolved).length;
        if (unresolved) notes.push(`${unresolved} arrival window(s) contain unresolved close peaks. No arrival time is selected for these windows.`);
        for (const receiver of ['A', 'B']) {
            const spans = integritySpans(report).filter(span => span.receiver === receiver && span.position === 'internal');
            if (spans.length) notes.push(`Device ${receiver}: ${spans.length} internal zero or constant span(s) shown, longest ${number(Math.max(...spans.map(span => span.duration_ms)), 2)} ms. These are observations of the recording; their cause is unverified.`);
            const scan = report.recordings?.[receiver]?.pcm_integrity;
            if (scan?.spans_truncated) notes.push(`Device ${receiver}: ${scan.omitted_span_count} additional span(s) omitted from the preview. Whole-recording counts are retained in the JSON.`);
        }
        return notes;
    }
    function arrivalFocus(arrival) {
        if (Number.isFinite(arrival?.onset_ms)) return arrival.onset_ms;
        const profile = arrival?.close_peak_diagnostics?.local_profiles?.find(item => item.unresolved)
            || arrival?.close_peak_diagnostics?.local_profiles?.[0];
        if (Number.isFinite(profile?.anchor_onset_ms)) return profile.anchor_onset_ms;
        return arrival?.candidates?.find(item => Number.isFinite(item.onset_ms))?.onset_ms;
    }
    function decodeWav(buffer) {
        const view = new DataView(buffer);
        const text = (at, length) => String.fromCharCode(...new Uint8Array(buffer, at, length));
        if (view.byteLength < 44 || text(0, 4) !== 'RIFF' || text(8, 4) !== 'WAVE') throw new Error('Unsupported WAV file');
        let format, channels, rate, bits, data;
        for (let at = 12; at + 8 <= view.byteLength;) {
            const size = view.getUint32(at + 4, true);
            const start = at + 8;
            if (start + size > view.byteLength) throw new Error('Truncated WAV file');
            if (text(at, 4) === 'fmt ' && size >= 16) {
                format = view.getUint16(start, true); channels = view.getUint16(start + 2, true);
                rate = view.getUint32(start + 4, true); bits = view.getUint16(start + 14, true);
            } else if (text(at, 4) === 'data') data = { start, size };
            at = start + size + size % 2;
        }
        if (!data || channels !== 1 || !rate || !((format === 3 && bits === 32) || (format === 1 && bits === 16))) throw new Error('Expected mono float32 or PCM16 WAV');
        const bytes = bits / 8;
        if (data.size % bytes) throw new Error('Incomplete WAV sample');
        const samples = new Float32Array(data.size / bytes);
        for (let i = 0; i < samples.length; i++) {
            samples[i] = format === 3 ? view.getFloat32(data.start + i * bytes, true) : view.getInt16(data.start + i * bytes, true) / 32768;
            if (!Number.isFinite(samples[i])) throw new Error('Non-finite WAV sample');
        }
        return { samples, sampleRate: rate };
    }
    function drawWave(canvas, wave, arrivals, emissionId, spans = []) {
        const ctx = canvas.getContext('2d');
        if (!ctx) return;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        if (!wave) return;
        const selected = arrivals.find(a => a.emission_id === emissionId);
        const focus = arrivalFocus(selected);
        let low = 0, high = wave.samples.length;
        if (emissionId !== 'all' && Number.isFinite(focus)) {
            low = Math.max(0, Math.floor((focus / 1000 - .005) * wave.sampleRate));
            high = Math.min(high, Math.ceil((focus / 1000 + (selected?.detector ? .060 : .045)) * wave.sampleRate));
        }
        if (high <= low) return;
        const width = canvas.width, height = canvas.height, span = high - low;
        ctx.fillStyle = '#ae4a5555';
        for (const interval of spans) {
            const left = Math.max(low, interval.start_frame), right = Math.min(high, interval.end_frame_exclusive);
            if (right > left) ctx.fillRect((left - low) / span * width, 0, Math.max(2, (right - left) / span * width), height);
        }
        let peak = .001;
        for (let i = low; i < high; i++) peak = Math.max(peak, Math.abs(wave.samples[i]));
        ctx.strokeStyle = '#33435a'; ctx.beginPath(); ctx.moveTo(0, height / 2); ctx.lineTo(width, height / 2); ctx.stroke();
        ctx.strokeStyle = '#7acbff'; ctx.beginPath();
        for (let x = 0; x < width; x++) {
            const start = low + Math.floor(x * span / width);
            const end = Math.min(high, Math.max(start + 1, low + Math.floor((x + 1) * span / width)));
            let min = Infinity, max = -Infinity;
            for (let i = start; i < end; i++) { min = Math.min(min, wave.samples[i]); max = Math.max(max, wave.samples[i]); }
            ctx.moveTo(x, height / 2 - min / peak * height * .38); ctx.lineTo(x, height / 2 - max / peak * height * .38);
        }
        ctx.stroke(); ctx.strokeStyle = '#ffcf80';
        for (const arrival of arrivals) {
            if (!Number.isFinite(arrival.onset_ms)) continue;
            const sample = arrival.onset_ms / 1000 * wave.sampleRate;
            if (sample < low || sample > high) continue;
            const x = (sample - low) / span * width;
            ctx.beginPath(); ctx.moveTo(x, 25); ctx.lineTo(x, height - 25); ctx.stroke();
        }
        ctx.fillStyle = '#aebcd0'; ctx.font = '22px system-ui';
        ctx.fillText(`${number(low / wave.sampleRate * 1000, 1)} to ${number(high / wave.sampleRate * 1000, 1)} ms · peak ${number(peak, 3)}`, 12, height - 7);
    }
    function drawProfile(canvas, arrival) {
        const scale = Math.min(2, globalThis.devicePixelRatio || 1);
        const displayWidth = canvas.clientWidth || canvas.parentElement?.clientWidth || 800;
        canvas.width = Math.round(displayWidth * scale); canvas.height = Math.round(180 * scale);
        const ctx = canvas.getContext('2d');
        if (!ctx) return;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        const profiles = arrival?.close_peak_diagnostics?.local_profiles || [];
        const profile = profiles.find(item => item.unresolved) || profiles[0];
        if (!profile?.offset_ms?.length) return;
        const offsets = profile.offset_ms, observed = profile.relative_amplitude, reference = profile.reference_relative_amplitude;
        const low = offsets[0], high = offsets[offsets.length - 1];
        if (!(high > low)) return;
        const peak = Math.max(1, ...observed, ...reference);
        const x = value => 12 * scale + (value - low) / (high - low) * (canvas.width - 24 * scale);
        const y = value => canvas.height - 30 * scale - value / peak * (canvas.height - 42 * scale);
        for (const [values, color] of [[reference, '#8bd3ff'], [observed, '#ffcf80']]) {
            ctx.strokeStyle = color; ctx.lineWidth = 1.5 * scale; ctx.beginPath();
            offsets.forEach((offset, i) => { if (i) ctx.lineTo(x(offset), y(values[i])); else ctx.moveTo(x(offset), y(values[i])); });
            ctx.stroke();
        }
        ctx.lineWidth = 1; ctx.strokeStyle = '#ffadad';
        for (const item of arrival.close_peak_diagnostics.alternatives || []) {
            if (!item.unresolved) continue;
            const offset = item.onset_ms - profile.anchor_onset_ms;
            if (offset < low || offset > high) continue;
            ctx.beginPath(); ctx.moveTo(x(offset), 10 * scale); ctx.lineTo(x(offset), canvas.height - 28 * scale); ctx.stroke();
        }
        ctx.fillStyle = '#aebcd0'; ctx.font = `${11 * scale}px system-ui`;
        ctx.fillText(`${number(low, 2)} to ${number(high, 2)} ms relative to candidate`, 12 * scale, canvas.height - 8 * scale);
    }
    return { number, decodeWav, drawWave, drawProfile, arrivalFocus, savedReportSpec, integritySpans, diagnosticNotes, playbackDescription,
        profileDetails, reportProfile, recordedProfileDescription, beepDiagnosticView, responseDiagnosticView };
});
