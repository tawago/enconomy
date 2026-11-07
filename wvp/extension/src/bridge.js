// Isolated world, the approval page only. One new port per request, so a restarted service worker doesn't leave a dead port behind.
// It never reads or sends an origin. The browser stamps the port with the real one.
const ALLOWED = new Set(["enrollBegin", "enrollFinish"]);
window.addEventListener("message", (e) => {
  if (e.source !== window || e.data?.__wvp !== "req" || !ALLOWED.has(e.data.method)) return;
  const { id, method, args } = e.data;
  const reply = (m) => window.postMessage({ __wvp: "res", id, ...m }, location.origin);
  let done = false;
  const port = chrome.runtime.connect({ name: "wvp" });
  port.onMessage.addListener((m) => { done = true; reply(m); port.disconnect(); });
  port.onDisconnect.addListener(() => { if (!done) reply({ err: { code: "extension_restarted", message: "the extension went away mid-request" } }); });
  port.postMessage({ method, args });
});
