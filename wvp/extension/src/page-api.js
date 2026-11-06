// Runs in the page's own world, on the approval page only. Sites don't get this. A login there needs no API at all.
(() => {
  let seq = 0;
  const pend = new Map();
  window.addEventListener("message", (e) => {
    if (e.source !== window || e.data?.__wvp !== "res") return;
    const p = pend.get(e.data.id);
    if (!p) return;
    pend.delete(e.data.id);
    if (e.data.err) p.no(Object.assign(new Error(e.data.err.message), { code: e.data.err.code })); else p.ok(e.data.ok);
  });
  const call = (method) => (args = {}) => new Promise((ok, no) => {
    const id = `${Date.now()}-${++seq}`;
    pend.set(id, { ok, no });
    window.postMessage({ __wvp: "req", id, method, args }, location.origin);
  });
  const api = Object.freeze({ enrollBegin: call("enrollBegin"), enrollFinish: call("enrollFinish") });
  Object.defineProperty(window, "wvp", { value: api, writable: false, configurable: false });
})();
