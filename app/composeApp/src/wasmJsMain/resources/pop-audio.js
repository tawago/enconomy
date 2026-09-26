/* PoP web audio glue (window.popAudio), used by WebAudioEngine (AudioEngine.web.kt).
 *
 * One AudioContext at 48 kHz for the tab's lifetime. The mic stream (EC/NS/AGC requested off) feeds an
 * AudioWorklet recorder that posts every block with its context frame; blocks go into a ring buffer keyed by
 * context frame, and frame gaps are remembered as drops. Playback is AudioBufferSourceNode.start(when).
 *
 * Clocks: ctxToPerf / perfToCtx map context seconds <-> performance.now() ms through getOutputTimestamp()
 * ({contextTime, performanceTime}: when that context frame is heard at the output). Before the output clock
 * runs, a fallback from currentTime + outputLatency is used.
 */
(function () {
  'use strict';
  const RING_S = 16;
  let ctx = null, stream = null, source = null, node = null, sink = null, track = null;
  let settings = {}, micOk = false, unlocking = null, lastError = '';
  let ring = null, ringN = 0, endFrame = -1, firstFrame = -1;
  const gaps = []; // [start, end) context frames with no mic data
  let drops = 0, blocks = 0;
  const waiters = new Set();
  const sources = new Set();
  const offs = []; // recent (performanceTime - contextTime·1000) samples

  function onBlock(ev) {
    const d = ev.data;
    if (!d || d.type !== 'block') return;
    const f = d.frame, s = d.samples, n = s.length;
    if (firstFrame < 0) firstFrame = f;
    if (endFrame >= 0 && f !== endFrame) {
      if (f > endFrame) { gaps.push([endFrame, f]); drops += 1; }
    }
    for (let i = 0; i < n; i += 1) ring[(f + i) % ringN] = s[i];
    endFrame = Math.max(endFrame, f + n);
    blocks += 1;
    const t = outputTs();
    if (t) { offs.push(t.performanceTime - t.contextTime * 1000); if (offs.length > 400) offs.shift(); }
    if (gaps.length > 64) gaps.splice(0, gaps.length - 64);
    for (const w of Array.from(waiters)) w();
  }

  async function doUnlock() {
    if (!ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      ctx = new AC({ sampleRate: 48000, latencyHint: 'interactive' });
      ringN = ctx.sampleRate * RING_S;
      ring = new Float32Array(ringN);
    }
    try { if (navigator.audioSession) navigator.audioSession.type = 'play-and-record'; } catch (e) { /* optional API */ }
    await ctx.resume();
    if (!stream) {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: false, noiseSuppression: false, autoGainControl: false,
          channelCount: { ideal: 1 }, sampleRate: { ideal: 48000 },
        },
        video: false,
      });
      micOk = true;
      track = stream.getAudioTracks()[0];
      settings = track && track.getSettings ? track.getSettings() : {};
      track && track.addEventListener('ended', () => { micOk = false; lastError = 'mic track ended'; });
      await ctx.audioWorklet.addModule(new URL('pop-recorder-worklet.js', location.href).href);
      source = ctx.createMediaStreamSource(stream);
      node = new AudioWorkletNode(ctx, 'pop-recorder', { numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1] });
      node.port.onmessage = onBlock;
      sink = ctx.createGain();
      sink.gain.value = 0; // keeps the worklet pulled; the mic never reaches the speaker
      source.connect(node).connect(sink).connect(ctx.destination);
    }
    return info();
  }

  function unlock() {
    if (!unlocking) {
      unlocking = doUnlock().catch((e) => { lastError = String(e && e.message || e); unlocking = null; throw e; });
    } else if (ctx && ctx.state !== 'running') {
      ctx.resume();
    }
    return unlocking;
  }

  function outputTs() {
    if (ctx && ctx.getOutputTimestamp) {
      const t = ctx.getOutputTimestamp();
      if (t && t.performanceTime > 0 && t.contextTime > 0) return t;
    }
    return null;
  }

  function outLatency() { return ctx ? (ctx.outputLatency || 0) : 0; }

  /** perf ms − context s·1000, median of the recent output timestamps (null before the output clock runs). */
  function clockOffsetMs() {
    if (offs.length === 0) return null;
    const a = offs.slice().sort((x, y) => x - y);
    return a[a.length >> 1];
  }

  function fallbackOffsetMs() {
    return performance.now() + outLatency() * 1000 - ctx.currentTime * 1000;
  }

  function offsetMs() {
    const o = clockOffsetMs();
    return o === null ? fallbackOffsetMs() : o;
  }

  function ctxToPerf(ctxS) { return ctxS * 1000 + offsetMs(); }
  function perfToCtx(perfMs) { return (perfMs - offsetMs()) / 1000; }

  function info() {
    return JSON.stringify({
      unlocked: !!ctx && ctx.state === 'running' && micOk,
      state: ctx ? ctx.state : 'none',
      sampleRate: ctx ? ctx.sampleRate : 0,
      baseLatency: ctx ? (ctx.baseLatency || 0) : 0,
      outputLatency: ctx ? (ctx.outputLatency || 0) : 0,
      inputLatency: typeof settings.latency === 'number' ? settings.latency : null,
      outputTs: !!outputTs(),
      clockOffsetMs: clockOffsetMs(),
      clockSamples: offs.length,
      settings: {
        echoCancellation: settings.echoCancellation, noiseSuppression: settings.noiseSuppression,
        autoGainControl: settings.autoGainControl, sampleRate: settings.sampleRate, channelCount: settings.channelCount,
      },
      drops, blocks, endFrame, lastError,
      audioSession: navigator.audioSession ? navigator.audioSession.type : null,
    });
  }

  function schedule(buf, whenS) {
    const b = ctx.createBuffer(1, buf.length, ctx.sampleRate);
    b.copyToChannel(buf, 0);
    const n = ctx.createBufferSource();
    n.buffer = b;
    n.connect(ctx.destination);
    const at = Math.max(whenS, ctx.currentTime + 0.005);
    n.onended = () => sources.delete(n);
    sources.add(n);
    n.start(at);
    return at;
  }

  function stopAll() {
    for (const n of Array.from(sources)) { try { n.stop(); } catch (e) { /* not started */ } }
    sources.clear();
  }

  /** Float32Array of n mic frames from context frame start; rejects on overwrite, drop or timeout. */
  function collect(start, n, timeoutMs) {
    start = Math.round(start);
    return new Promise((resolve, reject) => {
      let timer = null;
      const done = (err, val) => {
        waiters.delete(check);
        if (timer) clearTimeout(timer);
        if (err) reject(new Error(err)); else resolve(val);
      };
      const check = () => {
        if (endFrame < start + n) return;
        if (start < endFrame - ringN || start < firstFrame) return done(`capture [${start}, ${start + n}) not in ring (first ${firstFrame}, end ${endFrame})`);
        for (const g of gaps) if (g[0] < start + n && g[1] > start) return done(`dropped mic blocks [${g[0]}, ${g[1]})`);
        const out = new Float32Array(n);
        for (let i = 0; i < n; i += 1) out[i] = ring[(start + i) % ringN];
        done(null, out);
      };
      waiters.add(check);
      timer = setTimeout(() => done(`mic stalled (end ${endFrame}, wanted ${start + n}, ctx ${ctx ? ctx.state : 'none'})`), timeoutMs);
      check();
    });
  }

  window.popAudio = {
    unlock,
    unlocked: () => !!ctx && ctx.state === 'running' && micOk,
    micGranted: () => micOk,
    info,
    ctxToPerf,
    perfToCtx,
    ctxNow: () => (ctx ? ctx.currentTime : 0),
    offsetMs,
    schedule,
    stopAll,
    collect,
  };
})();
