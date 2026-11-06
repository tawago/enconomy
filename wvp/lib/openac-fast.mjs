// JS side of prover/fast. Same call shape as the wasm-bindgen module the SDK's WasmBridge expects, so the SDK
// is untouched. Keys are decoded once. The SDK still passes key bytes on each call. They're ignored here.
export async function loadFastProver(wasmBytes, opts = {}) {
  const threads = opts.threads ?? 0;
  const module = await WebAssembly.compile(wasmBytes);
  const imports = WebAssembly.Module.imports(module);
  const shared = imports.some((i) => i.kind === "memory");
  const memory = shared ? new WebAssembly.Memory({ initial: 40, maximum: 65536, shared: true }) : null;
  let mem;
  const u8 = () => new Uint8Array(mem.buffer);
  const host = {
    host_random(p, n) {
      // getRandomValues refuses shared memory, so it fills a private buffer first.
      const tmp = new Uint8Array(Math.min(65536, n));
      for (let off = 0; off < n; off += 65536) {
        const part = tmp.subarray(0, Math.min(65536, n - off));
        crypto.getRandomValues(part);
        u8().set(part, p + off);
      }
    },
    host_now_ms: () => performance.now(),
    host_log(p, n) { console.error("[wasm panic]", new TextDecoder().decode(u8().slice(p, p + n))); },
  };
  const inst = new WebAssembly.Instance(module, shared ? { env: { memory }, openac_host: host } : { openac_host: host });
  const x = inst.exports;
  mem = memory ?? x.memory;
  if (shared) {
    // Every instance on shared memory needs its own TLS block. This one is the coordinator's.
    x.__wasm_init_tls(x.oa_alloc_aligned(x.__tls_size.value, x.__tls_align.value));
  }
  x.oa_init();
  let poolSize = 1;
  if (threads > 0) {
    if (!shared) throw new Error("this wasm has no atomics");
    const STACK = 8 << 20;
    const up = threads.toString();
    await Promise.all(Array.from({ length: threads }, (_, i) => new Promise((ok, fail) => {
      const w = new Worker("/pool-worker.js", { type: "module", name: `pool-${i}` });
      w.onerror = (e) => fail(new Error(`pool worker ${i}: ${e.message}`));
      w.onmessage = (m) => { if (m.data.up) ok(); else if (m.data.log) console.error(m.data.log); };
      w.postMessage({ module, memory, stack: x.oa_alloc(STACK), stackSize: STACK, tls: x.oa_alloc_aligned(x.__tls_size.value, x.__tls_align.value), id: i });
      (self.__pool ??= []).push(w);
    })));
    poolSize = x.oa_pool_build(threads);
    if (poolSize !== threads) throw new Error(`pool build returned ${poolSize}`);
  }

  let lastTimings = {};
  const readTimings = () => {
    const s = new TextDecoder().decode(u8().slice(x.oa_timings_ptr(), x.oa_timings_ptr() + x.oa_timings_len()));
    lastTimings = Object.fromEntries(s.split(";").filter(Boolean).map((p) => { const [k, v] = p.split("="); return [k, Number(v)]; }));
  };
  function call(fn, buffers) {
    const args = [], held = [];
    for (const b of buffers) {
      const p = b.length ? x.oa_alloc(b.length) : 0;
      if (b.length) u8().set(b, p);
      args.push(p, b.length);
      if (b.length) held.push([p, b.length]);
    }
    const r = fn(...args);
    const view = new DataView(mem.buffer);
    const status = view.getUint32(r, true), count = view.getUint32(r + 4, true);
    const parts = [];
    let off = r + 8;
    for (let i = 0; i < count; i++) {
      const n = view.getUint32(off, true); off += 4;
      parts.push(u8().slice(off, off + n)); off += n;
    }
    x.oa_result_free();
    for (const [p, n] of held) x.oa_free(p, n);
    readTimings();
    return { status, parts };
  }
  const txt = (b) => new TextDecoder().decode(b);
  const three = (r) => {
    if (r.status !== 0) throw new Error(txt(r.parts[0]));
    return { proof: r.parts[0], instance: r.parts[1], witness: r.parts[2] };
  };
  let cachedState = null, pending = false;
  return {
    poolSize, shared,
    wasmMemoryBytes: () => mem.buffer.byteLength,
    timings: () => lastTimings,
    init() {},
    cacheKeys(k) {
      const r = call(x.oa_cache_keys, [k.prepareProvingKey, k.showProvingKey, k.prepareVerifyingKey, k.showVerifyingKey]);
      if (r.status !== 0) throw new Error(txt(r.parts[0]));
      return lastTimings;
    },
    precompute_from_witness: (_pk, w, size) => three(call(x.oa_precompute_from_witness, [w, new TextEncoder().encode(size)])),
    precompute_show_from_witness: (_pk, w) => three(call(x.oa_precompute_show_from_witness, [w])),
    setPrepareState(pi, pw) {
      const c = call(x.oa_cache_prepare_state, [pi, pw]);
      if (c.status !== 0) throw new Error(txt(c.parts[0]));
      cachedState = pw;
    },
    beginReblind() {
      const c = call(x.oa_present_begin, []);
      if (c.status !== 0) throw new Error(txt(c.parts[0]));
      pending = true;
    },
    reblindReady: () => x.oa_present_ready() === 1,
    present(_ppk, pi, pw, _spk, si, sw) {
      if (pending) {
        pending = false;
        const r = call(x.oa_present_finish, [si, sw]);
        if (r.status !== 0) throw new Error(txt(r.parts[0]));
        return { prepare_proof: r.parts[0], prepare_instance: r.parts[1], show_proof: r.parts[2], show_instance: r.parts[3] };
      }
      if (cachedState !== pw) {
        const c = call(x.oa_cache_prepare_state, [pi, pw]);
        if (c.status !== 0) throw new Error(txt(c.parts[0]));
        cachedState = pw;
      }
      const r = call(x.oa_present, [si, sw]);
      if (r.status !== 0) throw new Error(txt(r.parts[0]));
      return { prepare_proof: r.parts[0], prepare_instance: r.parts[1], show_proof: r.parts[2], show_instance: r.parts[3] };
    },
    verify(pp, _pvk, pi, sp, _svk, si) {
      const r = call(x.oa_verify, [pp, pi, sp, si]);
      if (r.status === 1) throw new Error(txt(r.parts[0]));
      if (r.status === 2) return { valid: false, prepare_public_values: [], show_public_values: [], error: txt(r.parts[0]) };
      const lines = (b) => { const s = txt(b); return s ? s.split("\n") : []; };
      return { valid: true, prepare_public_values: lines(r.parts[0]), show_public_values: lines(r.parts[1]), error: null };
    },
  };
}
