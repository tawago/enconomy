// JS side of prover-wasm. Same shape as the wasm-bindgen module the SDK's WasmBridge expects.
export async function loadPlainProver(wasmBytes, opts = {}) {
  let mem;
  const u8 = () => new Uint8Array(mem.buffer);
  const host = {
    host_random(p, n) {
      for (let off = 0; off < n; off += 65536) {
        crypto.getRandomValues(new Uint8Array(mem.buffer, p + off, Math.min(65536, n - off)));
      }
    },
    host_now_ms: () => performance.now(),
    host_log(p, n) {
      console.error("[wasm panic]", new TextDecoder().decode(u8().slice(p, p + n)));
    },
  };
  const { instance } = await WebAssembly.instantiate(wasmBytes, { openac_host: host });
  const x = instance.exports;
  mem = x.memory;
  x.oa_init();

  // Copy buffers into wasm memory, call, read the framed result, free everything.
  function call(fn, buffers) {
    const args = [];
    const held = [];
    for (const b of buffers) {
      const p = x.oa_alloc(b.length);
      u8().set(b, p);
      args.push(p, b.length);
      held.push([p, b.length]);
    }
    const r = fn(...args);
    const view = new DataView(mem.buffer);
    const status = view.getUint32(r, true);
    const count = view.getUint32(r + 4, true);
    const parts = [];
    let off = r + 8;
    for (let i = 0; i < count; i++) {
      const n = view.getUint32(off, true);
      off += 4;
      parts.push(u8().slice(off, off + n));
      off += n;
    }
    x.oa_result_free();
    for (const [p, n] of held) x.oa_free(p, n);
    if (opts.onPeak) opts.onPeak(mem.buffer.byteLength);
    return { status, parts };
  }
  const txt = (b) => new TextDecoder().decode(b);
  const three = (r, what) => {
    if (r.status !== 0) throw new Error(txt(r.parts[0]));
    return { proof: r.parts[0], instance: r.parts[1], witness: r.parts[2] };
  };
  return {
    wasmMemoryBytes: () => mem.buffer.byteLength,
    init() {},
    precompute_from_witness: (pk, w, size) =>
      three(call(x.oa_precompute_from_witness, [pk, w, new TextEncoder().encode(size)])),
    precompute_show_from_witness: (pk, w) => three(call(x.oa_precompute_show_from_witness, [pk, w])),
    present(ppk, pi, pw, spk, si, sw) {
      const r = call(x.oa_present, [ppk, pi, pw, spk, si, sw]);
      if (r.status !== 0) throw new Error(txt(r.parts[0]));
      return {
        prepare_proof: r.parts[0], prepare_instance: r.parts[1],
        show_proof: r.parts[2], show_instance: r.parts[3],
      };
    },
    verify(pp, pvk, pi, sp, svk, si) {
      const r = call(x.oa_verify, [pp, pvk, pi, sp, svk, si]);
      if (r.status === 1) throw new Error(txt(r.parts[0]));
      if (r.status === 2) return { valid: false, prepare_public_values: [], show_public_values: [], error: txt(r.parts[0]) };
      const lines = (b) => { const s = txt(b); return s ? s.split("\n") : []; };
      return { valid: true, prepare_public_values: lines(r.parts[0]), show_public_values: lines(r.parts[1]), error: null };
    },
  };
}
