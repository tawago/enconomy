// One rayon thread. Own wasm instance on the shared memory, own stack and TLS, then it stays in rayon's loop for good.
self.onmessage = (m) => {
  const { module, memory, stack, stackSize, tls } = m.data;
  self.onmessage = null;
  let mem = memory;
  const u8 = () => new Uint8Array(mem.buffer);
  const host = {
    host_random(p, n) {
      const tmp = new Uint8Array(Math.min(65536, n));
      for (let off = 0; off < n; off += 65536) { const part = tmp.subarray(0, Math.min(65536, n - off)); crypto.getRandomValues(part); u8().set(part, p + off); }
    },
    host_now_ms: () => performance.now(),
    host_log(p, n) { self.postMessage({ log: "[wasm panic in pool] " + new TextDecoder().decode(u8().slice(p, p + n)) }); },
  };
  const x = new WebAssembly.Instance(module, { env: { memory }, openac_host: host }).exports;
  x.__stack_pointer.value = stack + stackSize;
  x.__wasm_init_tls(tls);
  self.postMessage({ up: true });
  x.oa_worker_loop();
};
