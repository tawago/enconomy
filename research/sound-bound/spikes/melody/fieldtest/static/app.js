/* fieldtest: browser side. No DSP here: play the server's float32 buffers, record.
 *
 * Join -> role + schedule + probe list (server's order). Arm -> fetch every probe at
 * ctx.sampleRate, open the mic, start the worklet recorder, emit arm. Start -> map
 * start_server_ms into ctx time, schedule all own plays, trim capture to
 * [t0 - lead, t0 - lead + total), upload.
 */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const socket = io({ transports: ['websocket', 'polling'] });
  let PROBES = ['N250', 'N500', 'N1s', 'JBL', 'JBL250'];   // replaced by the server's list at join
  const LS_KEY = 'fieldtest.labels.v1';

  const state = {
    sessionId: null, role: null, schedule: null, partner: false,
    probes: {}, probesLoaded: {},
    offsetMs: null, rttMs: null, pingSamples: 0,
    ctx: null, stream: null, track: null, worklet: null, trackSettings: {},
    blocks: [], blockCount: 0, discontinuities: 0, expectedFrame: null,
    events: [], plays: [], armed: false, uploaded: false, wakeLock: null,
    labelCm: null, result: null, openProbe: null,
  };

  function log(msg) {
    const el = $('log');
    el.textContent = `${new Date().toISOString().slice(11, 23)} ${msg}\n` + el.textContent;
    console.log('[fieldtest]', msg);
  }
  function show(id, visible) { $(id).classList.toggle('hidden', !visible); }
  function note(kind, t) {
    state.events.push({ t_ctx_s: state.ctx ? state.ctx.currentTime : null, kind: kind + (t ? `:${t}` : '') });
  }
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const num = (v, d = 1) => (typeof v === 'number' && isFinite(v) ? v.toFixed(d) : '—');

  // ------------------------------------------------------------ labels (no typing)

  function selectDist(value) {
    for (const b of document.querySelectorAll('#dist button')) b.classList.toggle('on', b.dataset.cm === String(value));
    const other = value === 'other';
    show('label-other', other);
    state.labelCm = other ? 'other' : Number(value);
  }
  for (const b of document.querySelectorAll('#dist button')) {
    b.addEventListener('click', () => selectDist(b.dataset.cm));
  }

  function currentLabels() {
    let cm = state.labelCm;
    if (cm === 'other') {
      const raw = $('label-other').value.trim();
      cm = raw === '' ? null : Number(raw);
    }
    if (typeof cm === 'number' && !isFinite(cm)) cm = null;
    return {
      label_cm: cm, room: $('room').value, pose: $('pose').value, noise: $('noise').value,
      note: $('note').value.trim(), prefer_role: $('prefer').value,
    };
  }

  function saveLabels() {
    try {
      const l = currentLabels();
      localStorage.setItem(LS_KEY, JSON.stringify({ ...l, dist: state.labelCm, other: $('label-other').value }));
    } catch (err) { /* storage blocked */ }
  }

  function restoreLabels() {
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem(LS_KEY) || 'null'); } catch (err) { saved = null; }
    if (!saved) { selectDist('30'); return; }
    for (const key of ['room', 'pose', 'noise']) if (saved[key]) $(key).value = saved[key];
    if (saved.prefer_role) $('prefer').value = saved.prefer_role;
    if (typeof saved.note === 'string') $('note').value = saved.note;
    if (saved.other) $('label-other').value = saved.other;
    selectDist(saved.dist === undefined || saved.dist === null ? '30' : String(saved.dist));
  }
  restoreLabels();

  // ------------------------------------------------------------ listen

  let previewAudio = null;
  const running = () => state.armed && !state.uploaded;
  function setPreviewEnabled(on) {
    for (const b of document.querySelectorAll('[data-preview]')) b.disabled = !on;
    if (!on) { try { if (previewAudio) previewAudio.pause(); } catch (err) { /* ignore */ } }
  }
  for (const b of document.querySelectorAll('[data-preview]')) {
    b.addEventListener('click', () => {
      if (running()) { log('preview blocked: a run is recording'); return; }
      try { if (previewAudio) previewAudio.pause(); } catch (err) { /* ignore */ }
      previewAudio = new Audio(`/preview/${b.dataset.preview}.wav?role=A&t=${Date.now()}`);
      previewAudio.play().catch((err) => log(`preview failed: ${err}`));
    });
  }

  // ------------------------------------------------------------ clock sync

  async function syncClock(rounds = 10) {
    let best = Infinity; let offset = null;
    for (let i = 0; i < rounds; i += 1) {
      const t0 = performance.now();
      let serverMs = null;
      try {
        const response = await fetch('/api/time', { cache: 'no-store' });
        serverMs = (await response.json()).server_ms;
      } catch (err) { log(`ping failed: ${err}`); continue; }
      const rtt = performance.now() - t0;
      if (rtt < best) { best = rtt; offset = serverMs - (t0 + rtt / 2); }
      state.pingSamples += 1;
    }
    if (offset === null) throw new Error('clock sync failed');
    state.offsetMs = offset; state.rttMs = best;
    $('clock').textContent = `${offset.toFixed(1)} / ${best.toFixed(1)} ms`;
    log(`clock: offset ${offset.toFixed(1)} ms, min rtt ${best.toFixed(1)} ms`);
  }

  // ------------------------------------------------------------ join

  function openContext() {
    const AC = window.AudioContext || window.webkitAudioContext;
    const ctx = new AC({ latencyHint: 'interactive', sampleRate: 48000 });
    ctx.resume().catch((err) => log(`resume deferred: ${err}`));
    return ctx;
  }

  $('btn-join').addEventListener('click', async () => {
    const labels = currentLabels();
    if (state.labelCm === 'other' && labels.label_cm === null) { log('type a distance for "other"'); return; }
    $('btn-join').disabled = true;
    saveLabels();
    try {
      state.ctx = openContext();
      log(`AudioContext ${state.ctx.sampleRate} Hz, state ${state.ctx.state}`);
    } catch (err) {
      log(`WARNING: AudioContext failed (${err})`);
      state.ctx = null;
    }
    try { await syncClock(); } catch (err) { log(String(err)); $('btn-join').disabled = false; return; }
    socket.emit('join', { ...labels, user_agent: navigator.userAgent });
  });

  socket.on('connect', () => log('socket connected'));
  socket.on('disconnect', () => log('socket disconnected'));
  function nextRun() { saveLabels(); window.location.reload(); }

  function stopRun(message) {
    // Dead run (server rejected arm, pair reset, upload lost): say so, free the mic, offer Next run.
    show('card-run', true);
    $('countdown').textContent = message;
    show('btn-next-run', true);
    if (state.armed && !state.uploaded) {
      state.uploaded = true;   // stops countdown + scheduled upload
      try { state.worklet.port.postMessage({ type: 'stop' }); } catch (err) { /* gone */ }
      releaseHardware();
    }
    setPreviewEnabled(true);
  }

  socket.on('error_msg', (data) => {
    log(`server: ${data.message}`);
    if (!state.sessionId) $('btn-join').disabled = false;
    else if (state.armed && !state.result) stopRun(`server: ${data.message}`);
  });
  socket.on('pair_reset', (data) => {
    if (state.result || !state.sessionId) return;
    if (data.session_id && data.session_id !== state.sessionId) return;
    log(`pair reset (${data.why}); tap Next run`);
    stopRun(`pair reset: ${data.why}`);
  });

  $('btn-abort').addEventListener('click', () => {
    if (!window.confirm('Abort this run and reset the pair on the server?')) return;
    socket.emit('abort', {});
    nextRun();
  });
  $('btn-next-run').addEventListener('click', nextRun);

  function labelsText(l) {
    if (!l) return '—';
    const cm = l.label_cm === 0 ? 'touch' : (l.label_cm === null || l.label_cm === undefined ? '?' : `${l.label_cm} cm`);
    return `${cm} · ${l.room} · ${l.pose} · ${l.noise}`;
  }

  socket.on('joined', (data) => {
    state.sessionId = data.session_id;
    state.role = data.role;
    state.schedule = data.schedule;
    state.partner = Boolean(data.partner_present);
    $('role').textContent = data.role;
    $('sid').textContent = data.session_id.slice(0, 8);
    $('partner').textContent = state.partner ? 'here' : 'waiting';
    $('labels').textContent = labelsText(data.labels);
    if (Array.isArray(data.probes) && data.probes.length) PROBES = data.probes.slice();
    buildProbeSlots();
    show('card-join', false);
    show('card-status', true);
    if (!state.armed) {
      show('card-arm', true);
      $('btn-arm').disabled = !state.partner;
      $('btn-arm').textContent = state.partner ? 'Arm' : 'Arm (waiting for partner)';
    }
    log(`joined as ${data.role}, session ${data.session_id.slice(0, 8)}, partner ${state.partner}`);
  });

  socket.on('armed', (data) => {
    $('partner').textContent = `armed: ${data.armed.join(', ')}`;
    log(`armed: ${data.armed.join(', ')}`);
  });

  function buildProbeSlots() {
    // status rows "n @ sr" and the running steps, one per probe in play order
    $('probe-loads').innerHTML = PROBES.map((p) => `<div class="kv"><span>${esc(p)}</span>`
      + `<span id="p-${esc(p)}">${state.probesLoaded[p] ? `${state.probesLoaded[p].n} @ ${state.probesLoaded[p].sr}` : '—'}</span></div>`).join('');
    $('steps').innerHTML = PROBES.map((p) => `<div id="st-${esc(p)}">${esc(p)}</div>`).join('');
  }

  // ------------------------------------------------------------ arm

  async function fetchProbe(probe, sr) {
    const response = await fetch(`/api/probe/${state.sessionId}/${state.role}/${probe}.f32?sr=${sr}`, { cache: 'no-store' });
    if (!response.ok) {
      let msg = `${response.status}`;
      try { msg += ` ${(await response.json()).error}`; } catch (err) { /* not json */ }
      throw new Error(`probe ${probe}: ${msg}`);
    }
    const samples = new Float32Array(await response.arrayBuffer());
    const n = Number(response.headers.get('X-Samples') || samples.length);
    if (n !== samples.length) throw new Error(`probe ${probe}: length ${samples.length} != header ${n}`);
    state.probes[probe] = samples;
    state.probesLoaded[probe] = { n: samples.length, sr };
    $(`p-${probe}`).textContent = `${samples.length} @ ${sr}`;
  }

  $('btn-arm').addEventListener('click', async () => {
    $('btn-arm').disabled = true;
    try {
      if (!state.ctx) state.ctx = openContext();
      await state.ctx.resume();
      const sr = state.ctx.sampleRate;
      log(`AudioContext ${sr} Hz, state ${state.ctx.state}`);
      for (const p of PROBES) await fetchProbe(p, sr);

      state.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: { ideal: 1 }, sampleRate: { ideal: 48000 },
          echoCancellation: false, noiseSuppression: false, autoGainControl: false,
        },
        video: false,
      });
      state.track = state.stream.getAudioTracks()[0];
      renderTrackSettings();
      state.track.addEventListener('ended', () => { note('track_ended'); log('mic track ended!'); });

      await state.ctx.audioWorklet.addModule('/static/recorder-worklet.js');
      const source = state.ctx.createMediaStreamSource(state.stream);
      state.worklet = new AudioWorkletNode(state.ctx, 'fieldtest-recorder', {
        numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1],
      });
      state.worklet.port.onmessage = onBlock;
      const silent = state.ctx.createGain();
      silent.gain.value = 0;
      source.connect(state.worklet).connect(silent).connect(state.ctx.destination);

      await keepAwake();
      setPreviewEnabled(false);
      show('card-run', true);
      $('countdown').textContent = 'waiting for partner';
      state.armed = true;
      socket.emit('arm', { session_id: state.sessionId, sample_rate: sr });
      log('armed; recording');
    } catch (err) {
      log(`arm failed: ${err}`);
      $('btn-arm').disabled = false;
    }
  });

  function renderTrackSettings() {
    const s = state.track.getSettings ? state.track.getSettings() : {};
    state.trackSettings = s;
    const rows = ['echoCancellation', 'noiseSuppression', 'autoGainControl', 'sampleRate', 'channelCount'].map((key) => {
      const value = s[key];
      const bad = ['echoCancellation', 'noiseSuppression', 'autoGainControl'].includes(key) && value === true;
      return `<div class="kv"><span>${key}</span><span class="${bad ? 'bad' : 'ok'}">${value}</span></div>`;
    }).join('');
    const ec = s.echoCancellation === true
      ? '<p class="warn"><strong>ECHO CANCELLATION IS ON.</strong> This phone may erase its own probe. Results are suspect.</p>' : '';
    $('track-settings').innerHTML = rows + ec;
    log(`track settings: ${JSON.stringify(s)}`);
  }

  function onBlock({ data }) {
    if (!data || data.type !== 'block') return;
    if (state.expectedFrame !== null && data.contextFrame !== state.expectedFrame) state.discontinuities += 1;
    state.expectedFrame = data.contextFrame + data.frames;
    state.blockCount += 1;
    state.blocks.push({ frame: data.contextFrame, samples: data.samples });
  }

  async function keepAwake() {
    try {
      if ('wakeLock' in navigator) {
        state.wakeLock = await navigator.wakeLock.request('screen');
        log('screen wake lock held');
        return;
      }
    } catch (err) { log(`wakeLock refused: ${err}`); }
    try {
      const buffer = state.ctx.createBuffer(1, state.ctx.sampleRate, state.ctx.sampleRate);
      const node = state.ctx.createBufferSource();
      node.buffer = buffer; node.loop = true;
      node.connect(state.ctx.destination); node.start();
      state.silentLoop = node;
      log('silent keep-alive loop started');
    } catch (err) { log(`keep-alive failed: ${err}`); }
  }

  document.addEventListener('visibilitychange', () => {
    note('visibility', document.visibilityState);
    log(`visibility: ${document.visibilityState}`);
  });

  // ------------------------------------------------------------ start

  function ownPlays(schedule, role) {
    // Mirrors fieldprobes.plays(): A at start_s + k*period_s, B adds b_offset_s.
    const out = [];
    for (const probe of schedule.order || PROBES) {
      const p = schedule.probes[probe];
      for (let k = 0; k < p.rounds; k += 1) {
        out.push({ probe, k, offset_s: p.start_s + k * p.period_s + (role === 'B' ? p.b_offset_s : 0) });
      }
    }
    return out.sort((a, b) => a.offset_s - b.offset_s);
  }

  socket.on('start', (data) => {
    if (!state.ctx || data.session_id !== state.sessionId || state.startCtx !== undefined) return;
    const schedule = data.schedule || state.schedule;
    state.schedule = schedule;
    const perfNow = performance.now();
    const ctxNow = state.ctx.currentTime;
    const serverNow = perfNow + state.offsetMs;
    const startCtx = ctxNow + (data.start_server_ms - serverNow) / 1000;
    state.startCtx = startCtx;
    log(`start in ${(startCtx - ctxNow).toFixed(3)} s (ctx ${startCtx.toFixed(3)})`);

    state.plays = ownPlays(schedule, state.role).map((pl) => {
      const want = startCtx + pl.offset_s;
      const floor = state.ctx.currentTime + 0.01;
      const clamped = want < floor;
      const when = clamped ? floor : want;
      playAt(pl.probe, when);
      return { probe: pl.probe, k: pl.k, ctx_s: when, clamped };
    });
    const nClamped = state.plays.filter((p) => p.clamped).length;
    if (nClamped) log(`WARNING ${nClamped} plays clamped (start came late)`);

    const stopAt = startCtx - schedule.lead_s + schedule.record_total_s;
    const msToStop = Math.max(0, (stopAt - state.ctx.currentTime) * 1000) + 150;
    setTimeout(finishAndUpload, msToStop);
    runCountdown(startCtx, stopAt, schedule);
  });

  function playAt(probe, when) {
    const samples = state.probes[probe];
    if (!samples) { log(`no ${probe} buffer to play`); return; }
    const buffer = state.ctx.createBuffer(1, samples.length, state.ctx.sampleRate);
    buffer.copyToChannel(samples, 0);
    const node = state.ctx.createBufferSource();
    node.buffer = buffer;
    node.connect(state.ctx.destination);
    node.start(when);
  }

  function liveProbe(schedule, t) {
    // t = seconds since t0. A probe is "live" from its start_s until the next one's.
    const order = schedule.order || PROBES;
    let live = null;
    for (const p of order) if (t >= schedule.probes[p].start_s) live = p;
    return live;
  }

  function soundingNow(schedule, t) {
    // which play (either phone) should be sounding at t s after t0, e.g. "N500 · B round 2"
    for (const p of schedule.order || PROBES) {
      const s = schedule.probes[p];
      const dur = s.dur_s || 1.0;
      for (let k = 0; k < s.rounds; k += 1) {
        for (const r of ['A', 'B']) {
          const off = s.start_s + k * s.period_s + (r === 'B' ? s.b_offset_s : 0);
          if (t >= off && t < off + dur) return `${p} · ${r}${r === state.role ? ' (you)' : ''} round ${k + 1}`;
        }
      }
    }
    return null;
  }

  function runCountdown(startCtx, stopAt, schedule) {
    const t0Capture = startCtx - schedule.lead_s;
    const tick = () => {
      if (state.uploaded) return;
      const now = state.ctx.currentTime;
      const t = now - startCtx;
      const live = now >= startCtx ? liveProbe(schedule, t) : null;
      const order = schedule.order || PROBES;
      for (const p of order) {
        const el = $(`st-${p}`);
        if (!el) continue;
        const idx = order.indexOf(p); const liveIdx = live ? order.indexOf(live) : -1;
        el.className = p === live ? 'live' : (idx < liveIdx ? 'done' : '');
      }
      if (now < startCtx) $('countdown').textContent = `starts in ${(startCtx - now).toFixed(1)} s`;
      else if (now < stopAt) {
        const playing = soundingNow(schedule, t);
        $('countdown').textContent = `${playing || `${live || '—'} · quiet`} · ${(stopAt - now).toFixed(1)} s left`;
      }
      else $('countdown').textContent = 'uploading…';
      const frac = Math.min(1, Math.max(0, (now - t0Capture) / schedule.record_total_s));
      $('progress').style.width = `${(frac * 100).toFixed(1)}%`;
      $('blocks').textContent = `${state.blockCount} / ${state.discontinuities}`;
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  // ------------------------------------------------------------ finish

  function assembleCapture() {
    const rate = state.ctx.sampleRate;
    const startFrame = Math.round((state.startCtx - state.schedule.lead_s) * rate);
    const frames = Math.round(state.schedule.record_total_s * rate);
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
    const bytes = samples.length * 4;
    const buffer = new ArrayBuffer(44 + bytes);
    const view = new DataView(buffer);
    const ascii = (o, s) => { for (let i = 0; i < s.length; i += 1) view.setUint8(o + i, s.charCodeAt(i)); };
    ascii(0, 'RIFF'); view.setUint32(4, 36 + bytes, true); ascii(8, 'WAVE');
    ascii(12, 'fmt '); view.setUint32(16, 16, true);
    view.setUint16(20, 3, true); view.setUint16(22, 1, true);
    view.setUint32(24, rate, true); view.setUint32(28, rate * 4, true);
    view.setUint16(32, 4, true); view.setUint16(34, 32, true);
    ascii(36, 'data'); view.setUint32(40, bytes, true);
    new Float32Array(buffer, 44).set(samples);  // little-endian on every phone we target
    return new Blob([buffer], { type: 'audio/wav' });
  }

  async function finishAndUpload() {
    if (state.uploaded) return;
    state.uploaded = true;
    try { state.worklet.port.postMessage({ type: 'stop' }); } catch (err) { /* gone */ }
    const capture = assembleCapture();
    const meta = {
      role: state.role,
      sample_rate: capture.rate,
      capture_start_ctx_s: capture.startCtxS,
      capture_frames: capture.samples.length,
      start_ctx_s: state.startCtx,
      plays: state.plays,
      clock: { server_offset_ms: state.offsetMs, rtt_ms_min: state.rttMs, samples: state.pingSamples },
      context: {
        base_latency_s: state.ctx.baseLatency ?? null,
        output_latency_s: state.ctx.outputLatency ?? null,
        state: state.ctx.state,
      },
      track_settings: state.trackSettings || {},
      blocks: {
        count: state.blockCount, frames: capture.samples.length,
        discontinuities: state.discontinuities, missing_frames: capture.missing,
      },
      probes_loaded: state.probesLoaded,
      user_agent: navigator.userAgent,
      events: state.events,
    };
    log(`captured ${capture.samples.length} frames, ${capture.missing} missing, ${state.discontinuities} discontinuities`);
    // Keep the WAV + meta until the server acknowledges, so a failed upload can be retried.
    state.pending = { wav: wavFromFloat32(capture.samples, capture.rate), meta };
    state.blocks = [];
    releaseHardware();
    setPreviewEnabled(true);
    await uploadPending();
  }

  async function uploadPending() {
    if (!state.pending) return;
    show('btn-retry', false);
    $('countdown').textContent = 'uploading…';
    const form = new FormData();
    form.append('wav', state.pending.wav, `recording_${state.role}.wav`);
    form.append('meta', JSON.stringify(state.pending.meta));
    let msg = null;
    try {
      const response = await fetch(`/api/upload/${state.sessionId}/${state.role}`, { method: 'POST', body: form });
      let body = {};
      try { body = await response.json(); } catch (err) { body = {}; }
      log(`upload ${response.status}: ${JSON.stringify(body)}`);
      if (response.ok && body.ok) {
        state.pending = null;
        if (!state.result) $('countdown').textContent = body.both_uploaded ? 'analyzing…' : 'waiting for the other phone…';
        return;
      }
      msg = `upload failed: HTTP ${response.status}${body.error ? ` ${body.error}` : ''}`;
    } catch (err) {
      msg = `upload failed: ${err}`;
    }
    log(msg);
    if (!state.result) {
      $('countdown').textContent = msg;
      show('btn-retry', true);
      show('btn-next-run', true);
    }
  }
  $('btn-retry').addEventListener('click', () => { uploadPending(); });

  function releaseHardware() {
    try { state.stream.getTracks().forEach((t) => t.stop()); } catch (err) { /* ignore */ }
    try { if (state.silentLoop) state.silentLoop.stop(); } catch (err) { /* ignore */ }
    try { if (state.wakeLock) state.wakeLock.release(); } catch (err) { /* ignore */ }
  }

  // ------------------------------------------------------------ result

  socket.on('analyzing', (data) => {
    if (data.session_id !== state.sessionId) return;
    $('countdown').textContent = 'analyzing…';
    log('analyzing');
  });

  socket.on('result', (payload) => {
    if (payload.session_id !== state.sessionId) return;
    state.result = payload.result || {};
    show('card-run', false);
    show('card-arm', false);
    show('card-result', true);
    renderResult(state.result);
    log(`result: ${state.result.status}`);
  });

  function decisionOf(pr, result) {
    if (pr && pr.decision && pr.decision.label) return pr.decision.label;
    return result.status === 'failed' ? 'FAILED' : 'UNDECIDED';
  }

  function renderResult(result) {
    const probes = result.probes || {};
    const reasons = result.reasons || [];
    $('res-status').textContent = `${result.status || '?'} · ${labelsText(result.labels)} · ${num(result.runtime_s)} s`
      + (reasons.length ? ` · ${reasons.join('; ')}` : '');
    const names = Object.keys(probes).length ? PROBES.filter((p) => probes[p]).concat(Object.keys(probes).filter((p) => !PROBES.includes(p))) : PROBES;
    const usableOf = (s) => (s.usable_rounds === undefined || s.usable_rounds === null ? '' : ` ${s.usable_rounds}/${s.total_rounds}`);
    const head = '<tr><th>probe</th><th>first</th><th>ownwalk</th><th>flight</th><th>spread</th><th>min dB</th></tr>';
    const body = names.map((p) => {
      const pr = probes[p] || {};
      const s = pr.summary || {};
      const so = pr.summary_ownwalk || {};
      const dec = decisionOf(pr, result);
      const ow = pr.decision_ownwalk && pr.decision_ownwalk.label ? pr.decision_ownwalk.label : '—';
      return `<tr class="probe${state.openProbe === p ? ' sel' : ''}" data-probe="${esc(p)}">`
        + `<td class="name">${esc(p)}</td>`
        + `<td class="dec ${esc(dec)}">${esc(dec)}<small>${usableOf(s)}</small></td>`
        + `<td class="dec ${esc(ow)}">${esc(ow)}<small>${usableOf(so)}</small></td>`
        + `<td>${num(s.flight_median)}<small>${so.flight_median !== undefined ? ` / ${num(so.flight_median)}` : ''}</small></td>`
        + `<td>${num(s.spread)}<small>${so.spread !== undefined ? ` / ${num(so.spread)}` : ''}</small></td>`
        + `<td>${num(s.min_margin_db)}<small>${so.min_margin_db !== undefined ? ` / ${num(so.min_margin_db)}` : ''}</small></td>`
        + '</tr>';
    }).join('');
    $('probes').innerHTML = `<table class="restab">${head}${body}</table>`
      + '<p class="hint">first / ownwalk: decision + usable rounds. flight, spread (cm), min margin (dB): first / ownwalk.</p>';
    for (const el of document.querySelectorAll('#probes .probe')) {
      el.addEventListener('click', () => {
        state.openProbe = state.openProbe === el.dataset.probe ? null : el.dataset.probe;
        renderResult(result);
      });
    }
    $('detail').innerHTML = state.openProbe ? renderRounds(state.openProbe, probes[state.openProbe] || {}) : '<p class="hint">tap a probe for rounds</p>';

    const warnings = [];
    for (const [role, q] of Object.entries(result.quality || {})) {
      for (const f of (q && q.flags) || []) warnings.push(`${role}: ${f}`);
      if (q && q.flat_runs && q.flat_runs.length) warnings.push(`${role}: ${q.flat_runs.length} flat run(s)`);
      if (q && q.worklet_discontinuities) warnings.push(`${role}: ${q.worklet_discontinuities} worklet discontinuities`);
    }
    $('quality').innerHTML = warnings.length
      ? `<p class="warn">${warnings.map(esc).join('<br>')}</p>` : '<p class="hint">no quality flags</p>';
  }

  const ARR = ['A_at_A', 'B_at_A', 'B_at_B', 'A_at_B'];

  function arrivalCell(round, key) {
    const a = (round.arrivals || {})[key];
    if (a) return `<span class="ok">${num(a.right_pct)}</span>/${num(a.T)}`;
    const m = (round.misses || {})[key];
    if (m) return `<span class="bad">${num(m.right_max_pct)}</span>/${num(m.T)}`;
    return '—';
  }

  function renderRounds(probe, pr) {
    const rounds = pr.rounds || [];
    const rule = pr.decision && pr.decision.rule ? `<p class="hint">${esc(probe)}: ${esc(pr.decision.rule)}</p>` : '';
    const head = `<tr><th>k</th><th>cm</th><th>ow cm</th>${ARR.map((k) => `<th>${k.replace('_at_', '→')}</th>`).join('')}<th>ok / reasons</th></tr>`;
    const body = rounds.map((r) => `<tr><td>${r.k}</td><td>${num(r.flight_cm)}</td><td>${num((r.ownwalk || {}).flight_cm)}</td>`
      + ARR.map((k) => `<td>${arrivalCell(r, k)}</td>`).join('')
      + `<td class="${r.usable ? 'ok' : 'bad'}">${r.usable ? 'yes' : 'no'} ${esc((r.reasons || []).join(', '))}</td></tr>`).join('');
    const ow = pr.decision_ownwalk && pr.decision_ownwalk.rule ? `<p class="hint">ownwalk: ${esc(pr.decision_ownwalk.rule)}</p>` : '';
    return `${rule}${ow}<div style="overflow-x:auto"><table>${head}${body || '<tr><td colspan="8">no rounds</td></tr>'}</table></div>`
      + '<p class="hint">cells (first rule): right % / null bar T %. Red = missed. ow cm = ownwalk flight.</p>';
  }

  $('btn-again').addEventListener('click', nextRun);
})();
