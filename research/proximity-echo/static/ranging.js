/* Separate namespace and artifacts from the legacy echo experiment. */
(function () {
    'use strict';
    const $ = id => document.getElementById(id);
    const savedMode = new URLSearchParams(location.search).has('trial') || new URLSearchParams(location.search).has('report');
    const socket = savedMode ? null : io('/ranging');
    const num = RangingView.number;
    let role = null, armed = false, arming = false, peerState = null, active = null, lastResult = null;
    let requestedProfile = null, observedProfile = null;
    let waveToken = 0;
    const waves = {};
    function log(message) {
        const line = document.createElement('div');
        line.textContent = `${new Date().toLocaleTimeString()}  ${message}`;
        $('event-log').prepend(line);
        while ($('event-log').children.length > 80) $('event-log').lastChild.remove();
    }
    const awake = createScreenAwakeController((message, tone) => {
        $('awake').textContent = message; $('awake').className = tone;
    });
    function state(message, tone = '') { $('state').textContent = message; $('state').className = tone; }
    function updateControls() {
        const busy = !!active || !!requestedProfile || (peerState && peerState.state !== 'idle');
        $('arm').disabled = !role || !socket?.connected || busy || armed || arming;
        $('arm').textContent = armed ? 'Microphone enabled' : arming ? 'Enabling microphone…' : 'Enable microphone on this device';
        $('experiment').disabled = role !== 'initiator' || busy;
        $('start').disabled = role !== 'initiator' || !armed || busy || !peerState?.can_start;
        $('stop').disabled = !active || peerState?.state === 'processing';
        $('output-channel').disabled = !role || !socket?.connected || busy || arming;
        updateOutputStatus(); updateProfileStatus();
    }
    function updateProfileStatus() {
        const profile = active?.protocol?.profile || (active?.protocol?.version === 'ranging-v1' ? 'coded-probes' : null)
            || requestedProfile || (role === 'observer' ? observedProfile : $('profile').value);
        const details = RangingView.profileDetails(profile);
        $('profile-summary').textContent = details
            ? `${role === 'observer' && !active ? 'Last prepared profile. ' : ''}${details.description}`
            : 'Device A selects the signal profile. This device will show the selected signal and duration before recording.';
    }
    function updateOutputStatus() {
        if (!armed) { $('output-status').textContent = 'Enable the microphone to check browser output support.'; return; }
        try {
            const output = RangingAudio.checkOutputChannel($('output-channel').value);
            $('output-status').textContent = `${$('output-channel').selectedOptions[0].textContent} selected. Browser output: ${output.destination_channel_count ?? 'unknown'} channels. Physical speaker mapping is unverified.`;
            $('output-status').className = 'muted';
        } catch (error) { $('output-status').textContent = error.message; $('output-status').className = 'warning'; }
    }
    $('output-channel').addEventListener('change', updateOutputStatus);
    $('profile').addEventListener('change', updateProfileStatus);
    function finishActive() {
        requestedProfile = null;
        if (active) {
            active.controller.abort('Measurement ended'); active.wake.finish(); active = null;
        }
        $('progress').hidden = true; updateControls();
    }
    function nullableNumber(id) {
        return $(id).value.trim() === '' ? null : Number($(id).value);
    }
    function experimentMetadata() {
        return {
            measured_body_gap_cm: nullableNumber('measured-gap'), room: $('room').value.trim(), pose: $('pose').value.trim(),
            session_label: $('session-label').value.trim(), device_a_label: $('device-a-label').value.trim(), device_b_label: $('device-b-label').value.trim(),
            self_speaker_mic_a_cm: nullableNumber('self-a'), self_speaker_mic_b_cm: nullableNumber('self-b'),
        };
    }
    function base64(blob) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader(); reader.onerror = () => reject(new Error('Unable to encode recording'));
            reader.onload = () => resolve(String(reader.result).split(',')[1]); reader.readAsDataURL(blob);
        });
    }
    socket?.on('connect', () => {
        role = null; armed = false; peerState = null; observedProfile = null; finishActive();
        window.RangingAudio?.release();
        socket.emit('join', { user_agent: navigator.userAgent, device_label: navigator.userAgentData?.platform || navigator.platform || 'Browser' });
        state('Connected'); updateControls();
    });
    socket?.on('joined', message => {
        role = message.role;
        $('role').textContent = role === 'initiator' ? 'A · controls the measurement' : 'B · records and responds';
        $('instructions').textContent = role === 'initiator' ? 'Enable both microphones, enter the measured placement below, then start.' : 'Enable this microphone. Device A will start the measurement on both devices.';
        updateControls();
    });
    socket?.on('peer_status', message => {
        peerState = message;
        $('peers').textContent = `${(message.armed_roles || []).length} ready / ${message.count || 0} connected`;
        if (message.state === 'processing') state('Analyzing saved recordings…');
        updateControls();
    });
    socket?.on('disconnect', () => {
        finishActive(); role = null; armed = false; peerState = null;
        window.RangingAudio?.release(); state('Disconnected. Reconnect and enable the microphone again.', 'error'); updateControls();
    });
    socket?.on('error', message => {
        const text = message.message || message.error || message.reason || String(message);
        if (message.trial_id && active && message.trial_id !== active.id) { log(text); return; }
        if (!active) requestedProfile = null;
        state(text, 'error'); log(text); updateControls();
        if (message.code === 'upload_rejected' && active?.id === message.trial_id) {
            socket.emit('abort', { trial_id: active.id, reason: text }); finishActive();
        }
    });
    $('arm').addEventListener('click', async () => {
        arming = true; updateControls();
        try {
            const metadata = await RangingAudio.arm();
            if (!socket?.connected || !role) { RangingAudio.release(); return; }
            armed = true; socket.emit('arm', { armed: true, metadata }); state('Microphone ready'); log('Microphone enabled; no probes played.');
        } catch (error) { state(error.message, 'error'); log(error.message); }
        finally { arming = false; updateControls(); }
    });
    $('trial-form').addEventListener('submit', event => {
        event.preventDefault();
        if ($('start').disabled || !$('trial-form').reportValidity()) return;
        const metadata = experimentMetadata();
        if ((metadata.self_speaker_mic_a_cm === null) !== (metadata.self_speaker_mic_b_cm === null)) {
            state('Enter both speaker-to-microphone lengths, or leave both blank.', 'warning'); return;
        }
        const profile = $('profile').value;
        if (!RangingView.profileDetails(profile)) { state('Select a supported signal profile.', 'warning'); return; }
        requestedProfile = profile;
        state('Preparing both devices…'); updateControls(); socket.emit('start_trial', { metadata, profile });
    });
    socket?.on('prepare_trial', async message => {
        if (!armed || active) { socket.emit('abort', { trial_id: message.trial_id, reason: 'client_not_ready' }); return; }
        const outputChannel = $('output-channel').value;
        const trial = { id: message.trial_id, socketId: socket.id, protocol: message.protocol,
            protocolJSON: JSON.stringify(message.protocol), outputChannel, controller: new AbortController(), wake: awake.start(), capturing: false, ready: false };
        active = trial;
        $('result').hidden = true; state('Checking the signal and schedule…'); updateControls();
        try {
            const playback = RangingAudio.checkOutputChannel(outputChannel);
            const protocolMetadata = await RangingAudio.prepare(trial.protocol);
            if (active !== trial || trial.controller.signal.aborted) return;
            if (requestedProfile && requestedProfile !== protocolMetadata.profile) throw new Error('The prepared profile does not match the selected profile');
            observedProfile = protocolMetadata.profile; $('profile').value = protocolMetadata.profile;
            trial.ready = true;
            state('Waiting for both devices…'); updateControls();
            socket.emit('ready', { trial_id: message.trial_id, metadata: { ...protocolMetadata, page_visible: document.visibilityState === 'visible', playback } });
        } catch (error) {
            if (active !== trial) return;
            socket.emit('abort', { trial_id: message.trial_id, reason: error.message });
            state(error.message, 'warning'); log(error.message); finishActive();
        }
    });
    socket?.on('trial_start', async message => {
        const trial = active;
        if (!trial || !trial.ready || trial.id !== message.trial_id || trial.capturing) return;
        trial.capturing = true; $('progress').hidden = false; $('progress').value = 0;
        state('Recording. Keep both devices still.'); log(`Trial ${trial.id.slice(0, 8)} started. Profile: ${RangingView.profileDetails(observedProfile).name}. Local playback: ${trial.outputChannel}.`);
        try {
            if (message.protocol && JSON.stringify(message.protocol) !== trial.protocolJSON) throw new Error('The signal protocol changed after both devices prepared');
            const capture = await RangingAudio.capture(trial.protocol, role, {
                startAfterMs: message.start_after_ms ?? 600, signal: trial.controller.signal, outputChannel: trial.outputChannel,
                coordinationTargetUnixMs: message.start_at_unix_ms,
                onProgress: progress => { if (active === trial) $('progress').value = typeof progress === 'number' ? progress : progress.fraction || 0; },
            });
            if (active !== trial || trial.controller.signal.aborted) return;
            state('Saving recording…');
            const audio_base64 = await base64(capture.wav);
            if (active !== trial || trial.controller.signal.aborted) return;
            socket.emit('upload', { trial_id: trial.id, role, audio_base64, metadata: { ...capture.metadata, screen_awake: trial.wake.snapshot() } });
        } catch (error) {
            log(`Capture stopped: ${error.message}`);
            // A peer abort can finish the trial before this worklet has flushed its
            // samples. The server still retains late partials from the same socket.
            if (error.partial?.wav && socket.connected && socket.id === trial.socketId) {
                try {
                    const audio_base64 = await base64(error.partial.wav);
                    socket.emit('upload', { trial_id: trial.id, role, audio_base64, metadata: { ...error.partial.metadata, partial: true, capture_error: error.message, screen_awake: trial.wake.snapshot() } });
                } catch (encodingError) { log(encodingError.message); }
            }
            if (active !== trial) return;
            socket.emit('abort', { trial_id: trial.id, reason: error.message || 'capture_failed' });
            state(`Recording stopped: ${error.message}`, 'warning'); finishActive();
            armed = false; RangingAudio.release(); socket.emit('arm', { armed: false }); updateControls();
        }
    });
    socket?.on('upload_received', message => { if (active?.id === message.trial_id && !message.late) state('Recording saved. Waiting for analysis…'); });
    socket?.on('trial_aborted', message => {
        if (!active || active.id === message.trial_id) finishActive();
        state(`Attempt ended: ${message.reason}`, 'warning'); log(message.reason);
    });
    $('stop').addEventListener('click', () => {
        if (!active) return;
        state('Stopping…', 'warning');
        // Let capture reject with partial PCM, which is uploaded before the abort.
        if (active.capturing) active.controller.abort('Stopped by user');
        else { socket.emit('abort', { trial_id: active.id, reason: 'stopped_by_user' }); finishActive(); }
    });
    function addLink(parent, label, url) {
        if (typeof url !== 'string' || !url.startsWith('/ranging/trials/')) return;
        const link = document.createElement('a'); link.textContent = label; link.href = url; link.target = '_blank'; link.rel = 'noopener'; parent.append(link);
    }
    function showDownloads(message) {
        $('downloads').replaceChildren(); addLink($('downloads'), 'Download analysis JSON', message.artifact_url);
        addLink($('downloads'), 'All saved artifacts', message.manifest_url);
        addLink($('downloads'), 'Device A WAV', message.recordings?.initiator); addLink($('downloads'), 'Device B WAV', message.recordings?.observer);
        const match = message.artifact_url?.match(/^\/ranging\/trials\/([0-9a-f]{32})\/(report|reanalysis_[0-9a-f]{32})\.json$/);
        if (match) {
            const link = document.createElement('a'); link.textContent = 'Open saved view';
            link.href = `/ranging?trial=${match[1]}&report=${match[2]}.json`; $('downloads').append(link);
        }
    }
    socket?.on('artifacts_updated', message => {
        if (lastResult?.trial_id !== message.trial_id) return;
        lastResult = { ...lastResult, recordings: message.recordings, manifest_url: message.manifest_url };
        showDownloads(lastResult); void loadWaves(lastResult);
    });
    function draw() {
        const arrivals = lastResult?.report?.arrivals || [];
        for (const [receiver, id] of [['A', 'wave-a'], ['B', 'wave-b']]) {
            RangingView.drawWave($(id), waves[receiver], arrivals.filter(a => a.receiver === receiver), $('waveform-view').value,
                lastResult?.report?.recordings?.[receiver]?.pcm_integrity?.spans || []);
        }
    }
    function row(parent, values) {
        const tr = document.createElement('tr');
        for (const value of values) { const td = document.createElement('td'); td.textContent = value ?? '—'; tr.append(td); }
        parent.append(tr);
    }
    function drawPeaks() {
        const arrival = lastResult?.report?.arrivals?.[Number($('peak-view').value)];
        const diagnostics = arrival?.close_peak_diagnostics;
        RangingView.drawProfile($('peak-profile'), arrival); $('peak-alternatives').replaceChildren();
        $('peak-status').textContent = diagnostics?.local_profiles?.length ? (diagnostics.unresolved
            ? `Unresolved close peaks span ${num(diagnostics.ambiguity_span_ms)} ms. Arrival time withheld.`
            : 'No unresolved close peaks under the current diagnostic checks. Physical arrival bias remains uncalibrated.')
            : 'This report has no close-peak profile.';
        for (const peak of diagnostics?.alternatives || []) {
            row($('peak-alternatives'), [num(peak.offset_ms), num(peak.relative_amplitude), num(peak.reference_relative_amplitude), peak.classification?.replaceAll('_', ' ')]);
        }
    }
    function showDiagnostics(report) {
        $('analysis-version').textContent = `${report.analysis_version || 'Unknown analysis version'}${report.reanalysis ? ' · reanalysis of saved audio' : ''}`;
        $('recorded-profile').textContent = RangingView.recordedProfileDescription(report);
        $('recorded-playback').textContent = RangingView.playbackDescription(report);
        const beep = RangingView.beepDiagnosticView(report);
        $('beep-details').hidden = !beep;
        $('beep-arrivals').replaceChildren();
        if (beep) {
            $('beep-status').textContent = beep.summary;
            for (const values of beep.rows) row($('beep-arrivals'), values);
        }
        $('peak-details').hidden = !!beep;
        $('arrival-note-heading').textContent = beep ? 'Detector note' : 'Close-peak span, ms';
        const response = RangingView.responseDiagnosticView(report);
        $('response-details').hidden = !response;
        $('response-bands').replaceChildren(); $('response-channels').replaceChildren();
        $('response-steps').replaceChildren(); $('response-reasons').replaceChildren();
        if (response) {
            $('response-version').textContent = response.version;
            $('response-status').textContent = response.summary;
            $('response-status').className = response.available ? 'muted' : 'warning';
            $('response-values').hidden = !response.available;
            for (const values of response.bands) row($('response-bands'), values);
            for (const values of response.channels) row($('response-channels'), values);
            for (const text of response.stepCandidates) { const li = document.createElement('li'); li.textContent = text; $('response-steps').append(li); }
            $('response-step-notes').hidden = !response.stepCandidates.length;
            for (const text of response.reasons) { const li = document.createElement('li'); li.textContent = text; $('response-reasons').append(li); }
            $('response-reasons').hidden = !response.reasons.length;
        }
        $('diagnostic-overview').replaceChildren();
        for (const note of RangingView.diagnosticNotes(report)) { const li = document.createElement('li'); li.textContent = note; $('diagnostic-overview').append(li); }
        $('integrity-spans').replaceChildren();
        const spans = RangingView.integritySpans(report);
        for (const span of spans) row($('integrity-spans'), [span.receiver, span.kind?.replaceAll('_', ' '), num(span.start_s), num(span.duration_ms, 2), span.position]);
        const haveScan = ['A', 'B'].some(receiver => report.recordings?.[receiver]?.pcm_integrity);
        $('integrity-status').textContent = haveScan ? `${spans.length} zero or constant span(s) shown. Full scan details and any output limits are in the JSON.` : 'This report has no whole-recording content scan.';
        $('peak-view').replaceChildren();
        let preferred = null;
        (report.arrivals || []).forEach((arrival, index) => {
            if (!arrival.close_peak_diagnostics?.local_profiles?.length) return;
            $('peak-view').append(new Option(`${arrival.emission_id} · receiver ${arrival.receiver} · ${arrival.quality}`, index));
            if (preferred === null && arrival.close_peak_diagnostics.unresolved) preferred = index;
        });
        if (preferred !== null) $('peak-view').value = preferred;
        $('peak-view').disabled = !$('peak-view').options.length;
        if (!beep) drawPeaks();
    }
    async function loadWaves(message) {
        const token = ++waveToken; delete waves.A; delete waves.B;
        $('waveform-status').textContent = 'Loading saved recordings…'; draw();
        let loaded = 0;
        await Promise.all(['initiator', 'observer'].map(async (key, index) => {
            const url = message.recordings?.[key];
            if (typeof url !== 'string' || !url.startsWith('/ranging/trials/')) return;
            try {
                const response = await fetch(url);
                if (!response.ok) throw new Error(`Recording download returned ${response.status}`);
                const wave = RangingView.decodeWav(await response.arrayBuffer());
                if (token !== waveToken) return;
                waves[index === 0 ? 'A' : 'B'] = wave; loaded += 1;
            } catch (error) { if (token === waveToken) log(error.message); }
        }));
        if (token !== waveToken) return;
        $('waveform-status').textContent = loaded ? `${loaded} saved recording(s) loaded. Each plot scales its own amplitude.` : 'No complete recordings available for preview.'; draw();
    }
    function renderResult(message) {
        if (active && active.id !== message.trial_id) return;
        finishActive(); lastResult = message;
        const report = message.report || {}, summary = report.summary || {}, fit = report.clock_fit || {};
        $('result').hidden = false;
        $('result-title').textContent = `Trial ${message.trial_id.slice(0, 8)} · ${report.status === 'diagnostic' ? 'timing diagnostic' : 'measurement inconclusive'}`;
        $('result-description').textContent = 'Device body gap: INCONCLUSIVE. Physical distance requires calibration and validation of this setup. Any displayed path length refers to the active speakers and microphones.';
        showDiagnostics(report);
        $('timing').textContent = `${num(summary.timing_difference_ms)} ms`;
        $('uncorrected-metric').hidden = RangingView.reportProfile(report) !== 'beepbeep-reference';
        $('uncorrected-equivalent').textContent = Number.isFinite(summary.uncorrected_equivalent_cm)
            ? `${num(summary.uncorrected_equivalent_cm, 2)} cm` : 'Unavailable';
        $('path-distance').textContent = summary.acoustic_path_cm != null ? `${num(summary.acoustic_path_cm, 2)} cm`
            : summary.timing_difference_ms == null ? 'Unavailable' : 'Needs self-path lengths';
        $('repeatability').textContent = `${num(summary.repeatability_cm, 2)} cm`;
        $('clock-skew').textContent = fit.valid ? `${num(fit.relative_rate_ppm, 1)} ppm` : 'Fit unavailable';
        const beepProfile = RangingView.reportProfile(report) === 'beepbeep-reference';
        const countLabel = beepProfile ? 'detector candidates' : 'arrival windows detected';
        const detected = summary.detected_arrivals == null ? '' : `${summary.detected_arrivals} / ${summary.total_arrivals} ${countLabel}. `;
        const usableArrivals = (report.arrivals || []).filter(arrival => arrival.quality === 'usable').length;
        const usableCounts = beepProfile
            ? `${usableArrivals} / ${summary.total_arrivals ?? (report.arrivals || []).length} arrivals usable. ${summary.usable_exchanges ?? 0} / ${summary.total_exchanges ?? 0} exchanges usable. `
            : '';
        $('measurement-count').textContent = `${detected}${usableCounts}${summary.usable_emissions ?? 0} / ${summary.total_emissions ?? 0} emissions usable. Clock-fit residual: ${num(fit.residual_ms)} ms.`;
        $('reasons').replaceChildren();
        const reasons = [...new Set([...(report.reasons || []), ...(report.quality_warnings || []), ...(report.decision?.reasons || [])])];
        $('reasons-summary').textContent = `Measurement notes (${reasons.length})`;
        for (const reason of reasons) { const li = document.createElement('li'); li.textContent = String(reason).replaceAll('_', ' '); $('reasons').append(li); }
        showDownloads(message);
        $('arrivals').replaceChildren(); $('waveform-view').replaceChildren(new Option('Entire recording', 'all'));
        const emissions = new Set();
        for (const arrival of report.arrivals || []) {
            const tr = document.createElement('tr');
            const note = RangingView.reportProfile(report) === 'beepbeep-reference'
                ? (arrival.detector?.reason?.replaceAll('_', ' ') || 'See beep and slot checks')
                : num(arrival.close_peak_diagnostics?.ambiguity_span_ms);
            for (const value of [arrival.emission_id, arrival.receiver, num(arrival.onset_ms), num(arrival.uncertainty_ms), arrival.quality, note]) {
                const td = document.createElement('td'); td.textContent = value ?? '—'; tr.append(td);
            }
            $('arrivals').append(tr);
            if (!emissions.has(arrival.emission_id)) { emissions.add(arrival.emission_id); $('waveform-view').append(new Option(`${arrival.emission_id} · zoom to arrival`, arrival.emission_id)); }
        }
        state(report.status === 'diagnostic' ? 'Measurement saved. Review the timing diagnostic.' : 'Attempt saved; measurement inconclusive.', report.status === 'diagnostic' ? 'success' : 'warning');
        log(`Saved trial ${message.trial_id}.`); void loadWaves(message); updateControls();
    }
    socket?.on('result', renderResult);
    $('waveform-view').addEventListener('change', draw);
    $('peak-view').addEventListener('change', drawPeaks);
    $('peak-details').addEventListener('toggle', drawPeaks);
    window.addEventListener('resize', drawPeaks);
    if (savedMode) {
        $('connection').hidden = true; $('trial-form').hidden = true; $('saved-context').hidden = false;
        $('saved-context').textContent = 'Loading saved analysis…';
        (async () => {
            try {
                const spec = RangingView.savedReportSpec(location.search);
                const [reportResponse, manifestResponse] = await Promise.all([fetch(spec.reportUrl), fetch(spec.manifestUrl)]);
                if (!reportResponse.ok || !manifestResponse.ok) throw new Error('Saved report or recordings could not be loaded');
                const [report, manifest] = await Promise.all([reportResponse.json(), manifestResponse.json()]);
                if (report.trial_id !== spec.trialId || manifest.trial_id !== spec.trialId) throw new Error('Saved report identifiers do not match');
                renderResult({ trial_id: spec.trialId, report, artifact_url: spec.reportUrl, manifest_url: spec.manifestUrl, recordings: manifest.artifacts?.recordings });
                $('saved-context').textContent = 'Saved analysis. This page does not join a recording session or use the microphone.';
            } catch (error) { $('saved-context').textContent = error.message; $('saved-context').className = 'error'; }
        })();
    }
    window.addEventListener('pagehide', () => { if (active) socket.emit('abort', { trial_id: active.id, reason: 'page_closed' }); finishActive(); window.RangingAudio?.release(); });
    updateProfileStatus();
})();
