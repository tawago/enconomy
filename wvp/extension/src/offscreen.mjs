// Hosts the prover Worker. A service worker can't start Workers, and threads need this page's isolation headers.
const w = new Worker("/coordinator.js", { type: "module", name: "coordinator" });
let seq = 0;
const pend = new Map();
w.onmessage = ({ data }) => { const p = pend.get(data.id); pend.delete(data.id); p(data); };
w.onerror = (e) => { for (const p of pend.values()) p({ err: `worker: ${e.message}` }); pend.clear(); };
chrome.runtime.onMessage.addListener((m, sender, reply) => {
  if (m.to !== "offscreen" || sender.id !== chrome.runtime.id) return;
  const id = ++seq;
  pend.set(id, reply);
  w.postMessage({ id, fn: m.fn, arg: m.arg });
  return true;
});
