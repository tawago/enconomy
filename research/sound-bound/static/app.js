/* sound-bound — browser side.
 *
 * Join -> get a role, a seed, and this device's own probe. Arm -> mic opens and the
 * recorder runs. Start -> the server's epoch time is mapped into AudioContext time,
 * every probe slot is scheduled ahead of time, the capture is trimmed to the agreed
 * window, uploaded, and the result comes back over the socket.
 */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const socket = io({ transports: ['websocket', 'polling'] });

  const state = {
    sessionId: null,
    role: null,
    schedule: null,
    probe: null,           // Float32Array
    probeRate: 48000,
    offsetMs: null,        // server_ms - performance.now()
    rttMs: null,
    pingSamples: 0,
    ctx: null,
    stream: null,
    track: null,
    worklet: null,
    blocks: [],
    blockCount: 0,
    discontinuities: 0,
    expectedFrame: null,
    firstFrame: null,
    events: [],
    uploaded: false,
    wakeLock: null,
  };

  function log(msg) {
    const el = $('log');
    const line = `${new Date().toISOString().slice(11, 23)} ${msg}\n`;
    el.textContent = line + el.textContent;
    console.log('[sound-bound]', msg);
  }

  function show(id, visible) { $(id).classList.toggle('hidden', !visible); }
  function note(kind, t) { state.events.push({ t_ctx_s: state.ctx ? state.ctx.currentTime : null, kind: kind + (t ? `:${t}` : '') }); }

  // ------------------------------------------------------------ clock sync

  async function syncClock(rounds = 10) {
    let best = Infinity;
    let offset = null;
    for (let i = 0; i < rounds; i += 1) {
      const t0 = performance.now();
      let serverMs = null;
      try {
        const response = await fetch('/api/time', { cache: 'no-store' });
        serverMs = (await response.json()).server_ms;
      } catch (err) {
        log(`ping failed: ${err}`);
        continue;
      }
      const t1 = performance.now();
      const rtt = t1 - t0;
      if (rtt < best) {
        best = rtt;
        offset = serverMs - (t0 + rtt / 2);
      }
      state.pingSamples += 1;
    }
    if (offset === null) throw new Error('clock sync failed');
    state.offsetMs = offset;
    state.rttMs = best;
    $('offset').textContent = `${offset.toFixed(1)} ms`;
    $('rtt').textContent = `${best.toFixed(1)} ms`;
    log(`clock: offset ${offset.toFixed(1)} ms, min rtt ${best.toFixed(1)} ms`);
  }

  // ------------------------------------------------------------ join

  function openContext() {
    // Created here, inside the Join click, because iOS only allows it from a user
    // gesture — and because the server needs the real rate before it makes the probe.
    const AC = window.AudioContext || window.webkitAudioContext;
    const ctx = new AC({ latencyHint: 'interactive', sampleRate: 48000 });
    ctx.resume().catch((err) => log(`resume deferred: ${err}`));
    return ctx;
  }

  $('btn-join').addEventListener('click', async () => {
    $('btn-join').disabled = true;
    let rate = 48000;
    try {
      state.ctx = openContext();
      rate = state.ctx.sampleRate;
      log(`AudioContext ${rate} Hz, state ${state.ctx.state}`);
    } catch (err) {
      log(`WARNING: could not open AudioContext (${err}); reporting 48000`);
      state.ctx = null;
    }
    try {
      await syncClock();
    } catch (err) {
      log(String(err));
      $('btn-join').disabled = false;
      return;
    }
    const labelRaw = $('label').value.trim();
    socket.emit('join', {
      label_cm: labelRaw === '' ? null : Number(labelRaw),
      note: $('note').value.trim(),
      sample_rate: rate,
      user_agent: navigator.userAgent,
    });
  });

  socket.on('connect', () => log('socket connected'));
  socket.on('disconnect', () => log('socket disconnected'));
  socket.on('error_msg', (data) => { log(`server: ${data.message}`); $('btn-join').disabled = false; });
  socket.on('pair_reset', (data) => log(`pair reset (${data.why}) — reload to start over`));

  socket.on('joined', (data) => {
    state.sessionId = data.session_id;
    state.role = data.role;
    state.schedule = data.schedule;
    state.probeRate = data.probe_sample_rate;
    $('role').textContent = data.role;
    $('sid').textContent = data.session_id.slice(0, 8);
    $('partner').textContent = data.partner_present ? 'here' : 'waiting';
    show('card-join', false);
    show('card-status', true);
    const afterArm = Boolean(state.armed);

    if (data.probe_b64) {
      state.probe = decodeFloat32(data.probe_b64);
      $('probe').textContent = `${state.probe.length} samples @ ${state.probeRate}`;
      if (!afterArm) show('card-arm', true);
    } else {
      state.probe = null;
      $('probe').innerHTML = `<span class="bad">missing</span>`;
      log(`no probe from server: ${data.probe_error || 'unknown'}`);
    }
    log(`joined as ${data.role}, session ${data.session_id.slice(0, 8)}`);
  });

  socket.on('armed', (data) => {
    $('partner').textContent = `armed: ${data.armed.join(', ')}`;
    log(`armed: ${data.armed.join(', ')}`);
  });

  function decodeFloat32(b64) {
    const binary = atob(b64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return new Float32Array(bytes.buffer);
  }

  // ------------------------------------------------------------ arm

  $('btn-arm').addEventListener('click', async () => {
    $('btn-arm').disabled = true;
    try {
      // The context was opened at Join; resume it again here, inside this gesture,
      // in case the browser suspended it in the meantime.
      if (!state.ctx) state.ctx = openContext();
      await state.ctx.resume();
      log(`AudioContext ${state.ctx.sampleRate} Hz, state ${state.ctx.state}`);
      if (state.ctx.sampleRate !== state.probeRate) {
        log(`context rate ${state.ctx.sampleRate} != probe rate ${state.probeRate}; asking for a new probe`);
      }

      state.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: { ideal: 1 },
          sampleRate: { ideal: 48000 },
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false,
        },
        video: false,
      });
      state.track = state.stream.getAudioTracks()[0];
      renderTrackSettings();
      state.track.addEventListener('ended', () => { note('track_ended'); log('mic track ended!'); });

      await state.ctx.audioWorklet.addModule('/static/recorder-worklet.js');
      const source = state.ctx.createMediaStreamSource(state.stream);
      state.worklet = new AudioWorkletNode(state.ctx, 'sound-bound-recorder', {
        numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1],
      });
      state.worklet.port.onmessage = onBlock;
      const silent = state.ctx.createGain();
      silent.gain.value = 0;
      source.connect(state.worklet).connect(silent).connect(state.ctx.destination);

      await keepAwake();
      show('card-arm', false);
      show('card-run', true);
      $('countdown').textContent = 'waiting for partner';
      state.armed = true;
      socket.emit('arm', { session_id: state.sessionId, sample_rate: state.ctx.sampleRate });
      log('armed; recording');
    } catch (err) {
      log(`arm failed: ${err}`);
      $('btn-arm').disabled = false;
    }
  });

  function renderTrackSettings() {
    const s = state.track.getSettings ? state.track.getSettings() : {};
    state.trackSettings = s;
    const rows = ['echoCancellation', 'noiseSuppression', 'autoGainControl', 'sampleRate', 'channelCount']
      .map((key) => {
        const value = s[key];
        const bad = (key === 'echoCancellation' || key === 'noiseSuppression' || key === 'autoGainControl') && value === true;
        return `<div class="kv"><span>${key}</span><span class="${bad ? 'bad' : 'ok'}">${value}</span></div>`;
      }).join('');
    const ec = s.echoCancellation === true
      ? '<p class="warn">Echo cancellation is ON — this phone may erase its own probe from the recording.</p>' : '';
    $('track-settings').innerHTML = rows + ec;
    log(`track settings: ${JSON.stringify(s)}`);
  }

  function onBlock({ data }) {
    if (!data || data.type !== 'block') return;
    if (state.firstFrame === null) {
      state.firstFrame = data.contextFrame;
      state.expectedFrame = data.contextFrame;
    }
    if (data.contextFrame !== state.expectedFrame) state.discontinuities += 1;
    state.expectedFrame = data.contextFrame + data.frames;
    state.blockCount += 1;
    state.blocks.push({ frame: data.contextFrame, samples: data.samples, hasInput: data.hasInput });
    if (state.blockCount % 20 === 0) {
      $('blocks').textContent = String(state.blockCount);
      $('discont').textContent = String(state.discontinuities);
    }
  }

  async function keepAwake() {
    try {
      if ('wakeLock' in navigator) {
        state.wakeLock = await navigator.wakeLock.request('screen');
        log('screen wake lock held');
        return;
      }
    } catch (err) {
      log(`wakeLock refused: ${err}`);
    }
    // Fallback: a silent looping buffer keeps the audio session (and on some
    // phones the screen) alive for the length of the run.
    try {
      const buffer = state.ctx.createBuffer(1, state.ctx.sampleRate, state.ctx.sampleRate);
      const node = state.ctx.createBufferSource();
      node.buffer = buffer; node.loop = true;
      node.connect(state.ctx.destination); node.start();
      state.silentLoop = node;
      log('silent keep-alive loop started');
    } catch (err) {
      log(`keep-alive failed: ${err}`);
    }
  }

  document.addEventListener('visibilitychange', () => {
    note('visibility', document.visibilityState);
    log(`visibility: ${document.visibilityState}`);
  });

  // ------------------------------------------------------------ start

  socket.on('start', (data) => {
    if (!state.ctx || data.session_id !== state.sessionId) return;
    const schedule = data.schedule || state.schedule;
    state.schedule = schedule;

    // Sample performance.now() and AudioContext.currentTime together, then map.
    const perfNow = performance.now();
    const ctxNow = state.ctx.currentTime;
    const serverNow = perfNow + state.offsetMs;
    const startCtx = ctxNow + (data.start_server_ms - serverNow) / 1000;
    state.startCtx = startCtx;
    log(`start in ${(startCtx - ctxNow).toFixed(3)} s (ctx ${startCtx.toFixed(3)})`);

    const offsetS = state.role === 'B' ? schedule.b_offset_s : 0;
    const plays = [];
    for (let k = 0; k < schedule.rounds; k += 1) {
      const when = startCtx + offsetS + k * schedule.period_s;
      plays.push(when);
      schedulePlay(when);
    }
    state.plays = plays;

    const stopAt = startCtx + schedule.record_total_s - schedule.record_lead_s;
    const msToStop = Math.max(0, (stopAt - state.ctx.currentTime) * 1000) + 120;
    setTimeout(finishAndUpload, msToStop);
    runCountdown(startCtx, stopAt);
  });

  function schedulePlay(whenCtx) {
    if (!state.probe) { log('no probe to play'); return; }
    const buffer = state.ctx.createBuffer(1, state.probe.length, state.ctx.sampleRate);
    buffer.copyToChannel(state.probe, 0);
    const node = state.ctx.createBufferSource();
    node.buffer = buffer;
    node.connect(state.ctx.destination);
    node.start(Math.max(whenCtx, state.ctx.currentTime + 0.01));
  }

  function runCountdown(startCtx, stopAt) {
    const tick = () => {
      if (state.uploaded) return;
      const t = state.ctx.currentTime;
      if (t < startCtx) $('countdown').textContent = `${(startCtx - t).toFixed(1)} s`;
      else if (t < stopAt) $('countdown').textContent = `recording ${(stopAt - t).toFixed(1)} s`;
      else $('countdown').textContent = 'uploading…';
      $('blocks').textContent = String(state.blockCount);
      $('discont').textContent = String(state.discontinuities);
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  // ------------------------------------------------------------ finish

  function assembleCapture() {
    const rate = state.ctx.sampleRate;
    const lead = state.schedule.record_lead_s;
    const total = state.schedule.record_total_s;
    const startFrame = Math.round((state.startCtx - lead) * rate);
    const frames = Math.round(total * rate);
    const out = new Float32Array(frames);
    let covered = 0;
    for (const block of state.blocks) {
      const from = Math.max(block.frame, startFrame);
      const to = Math.min(block.frame + block.samples.length, startFrame + frames);
      if (to <= from) continue;
      out.set(block.samples.subarray(from - block.frame, to - block.frame), from - startFrame);
      covered += to - from;
    }
    return { samples: out, rate, startCtxS: startFrame / rate, missing: frames - covered };
  }

  function wavFromFloat32(samples, rate) {
    // IEEE float32 WAV: nothing is quantized or clipped on the way out.
    const bytes = samples.length * 4;
    const buffer = new ArrayBuffer(44 + bytes);
    const view = new DataView(buffer);
    const ascii = (offset, text) => { for (let i = 0; i < text.length; i += 1) view.setUint8(offset + i, text.charCodeAt(i)); };
    ascii(0, 'RIFF'); view.setUint32(4, 36 + bytes, true); ascii(8, 'WAVE');
    ascii(12, 'fmt '); view.setUint32(16, 16, true);
    view.setUint16(20, 3, true);            // IEEE float
    view.setUint16(22, 1, true);            // mono
    view.setUint32(24, rate, true);
    view.setUint32(28, rate * 4, true);
    view.setUint16(32, 4, true);
    view.setUint16(34, 32, true);
    ascii(36, 'data'); view.setUint32(40, bytes, true);
    let offset = 44;
    for (const value of samples) { view.setFloat32(offset, value, true); offset += 4; }
    return new Blob([buffer], { type: 'audio/wav' });
  }

  async function finishAndUpload() {
    if (state.uploaded) return;
    state.uploaded = true;
    try { state.worklet.port.postMessage({ type: 'stop' }); } catch (err) { /* already gone */ }

    const capture = assembleCapture();
    const meta = {
      role: state.role,
      sample_rate: capture.rate,
      capture_start_ctx_s: capture.startCtxS,
      start_ctx_s: state.startCtx,
      scheduled_plays_ctx_s: state.plays || [],
      clock: { server_offset_ms: state.offsetMs, rtt_ms_min: state.rttMs, samples: state.pingSamples },
      context: {
        base_latency_s: state.ctx.baseLatency ?? null,
        output_latency_s: state.ctx.outputLatency ?? null,
        state: state.ctx.state,
      },
      track_settings: state.trackSettings || {},
      blocks: {
        count: state.blockCount,
        frames: capture.samples.length,
        discontinuities: state.discontinuities,
        missing_frames: capture.missing,
      },
      events: state.events,
    };
    log(`captured ${capture.samples.length} frames, ${capture.missing} missing, ${state.discontinuities} discontinuities`);

    const form = new FormData();
    form.append('wav', wavFromFloat32(capture.samples, capture.rate), `recording_${state.role}.wav`);
    form.append('meta', JSON.stringify(meta));
    $('countdown').textContent = 'uploading…';
    try {
      const response = await fetch(`/api/upload/${state.sessionId}/${state.role}`, { method: 'POST', body: form });
      const body = await response.json();
      log(`upload ${response.status}: ${JSON.stringify(body)}`);
      $('countdown').textContent = body.both_uploaded ? 'analyzing…' : 'waiting for the other phone…';
    } catch (err) {
      log(`upload failed: ${err}`);
      $('countdown').textContent = 'upload failed';
    }
    releaseHardware();
  }

  function releaseHardware() {
    try { state.stream.getTracks().forEach((t) => t.stop()); } catch (err) { /* ignore */ }
    try { if (state.silentLoop) state.silentLoop.stop(); } catch (err) { /* ignore */ }
    try { if (state.wakeLock) state.wakeLock.release(); } catch (err) { /* ignore */ }
  }

  // ------------------------------------------------------------ result

  socket.on('result', (payload) => {
    const result = payload.result || {};
    show('card-result', true);
    show('card-run', false);
    renderResult(result);
    log(`result: ${result.status} ${(result.decision || {}).label || ''}`);
  });

  const num = (v, d = 1) => (typeof v === 'number' && isFinite(v) ? v.toFixed(d) : '—');

  function renderResult(result) {
    const decision = result.decision || {};
    const label = decision.label || (result.status === 'failed' ? 'FAILED' : 'UNDECIDED');
    $('decision').textContent = `${label} · PROVISIONAL`;
    $('rule').textContent = decision.rule || '';

    const summary = result.summary || {};
    $('summary').innerHTML = [
      ['usable rounds', summary.usable_rounds ?? '—'],
      ['flight cm (median)', num(summary.flight_cm_median)],
      ['flight cm (spread)', num(summary.flight_cm_spread)],
      ['DRR dB (median)', num(summary.drr_db_median)],
      ['crossfire dB (min)', num(summary.crossfire_db_min)],
    ].map(([k, v]) => `<div class="kv"><span>${k}</span><span>${v}</span></div>`).join('');

    const rounds = Array.isArray(result.rounds) ? result.rounds : [];
    const head = '<tr><th>k</th><th>Δ ms</th><th>cm</th><th>DRR A→B</th><th>DRR B→A</th><th>x-fire</th><th>ok</th><th>reasons</th></tr>';
    const body = rounds.map((r) => {
      const cross = r.crossfire_db || {};
      const values = Object.values(cross).filter((v) => typeof v === 'number');
      const minCross = values.length ? Math.min(...values) : null;
      return `<tr><td>${r.k}</td><td>${num(r.delta_ms, 3)}</td><td>${num(r.flight_cm)}</td>`
        + `<td>${num(r.drr_AB_db)}</td><td>${num(r.drr_BA_db)}</td><td>${num(minCross)}</td>`
        + `<td class="${r.usable ? 'ok' : 'bad'}">${r.usable ? 'yes' : 'no'}</td>`
        + `<td>${(r.reasons || []).join(', ')}</td></tr>`;
    }).join('');
    $('rounds').innerHTML = head + (body || '<tr><td colspan="8">no rounds</td></tr>');

    const warnings = [];
    for (const [role, q] of Object.entries(result.quality || {})) {
      for (const [key, value] of Object.entries(q || {})) {
        if (value === true || (typeof value === 'number' && value > 0)) warnings.push(`${role}: ${key} = ${value}`);
      }
    }
    for (const reason of result.reasons || []) warnings.push(reason);
    $('quality').innerHTML = warnings.length
      ? `<p class="warn">${warnings.join('<br>')}</p>`
      : '<p class="hint">no quality flags</p>';
  }

  $('btn-again').addEventListener('click', () => window.location.reload());
})();
