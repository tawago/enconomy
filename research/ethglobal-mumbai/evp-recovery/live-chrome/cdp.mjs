// Tiny CDP client, Node 24 global WebSocket, no deps.
//   node cdp.mjs open <url>                 open a new tab
//   node cdp.mjs eval <urlPart> <js>        Runtime.evaluate in the first tab whose URL contains urlPart
//   node cdp.mjs shot <urlPart> <file>      screenshot
//   node cdp.mjs targets                    list targets
//   node cdp.mjs login                      sign in at https://tawago.test/login
//   node cdp.mjs flow [email] [nonce]       run the EVP flow on https://recover.tawago.test/
import { readFileSync, writeFileSync } from "node:fs";

const PORT = 9333;
const here = new URL(".", import.meta.url);

export async function connect() {
  const v = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json();
  const ws = new WebSocket(v.webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  let id = 0; const pending = new Map(); const listeners = [];
  ws.onmessage = (m) => {
    const d = JSON.parse(m.data);
    if (d.id && pending.has(d.id)) { const { r, j } = pending.get(d.id); pending.delete(d.id); d.error ? j(new Error(JSON.stringify(d.error))) : r(d.result); }
    else listeners.forEach((f) => f(d));
  };
  const send = (method, params = {}, sessionId) => new Promise((r, j) => {
    const i = ++id; pending.set(i, { r, j }); ws.send(JSON.stringify({ id: i, method, params, sessionId }));
  });
  return { ws, send, on: (f) => listeners.push(f), version: v };
}

export async function attach(c, urlPart) {
  const { targetInfos } = await c.send("Target.getTargets");
  const t = targetInfos.find((x) => x.type === "page" && x.url.includes(urlPart));
  if (!t) throw new Error("no target " + urlPart + " in " + targetInfos.map((x) => x.url).join(" "));
  const { sessionId } = await c.send("Target.attachToTarget", { targetId: t.targetId, flatten: true });
  const s = (m, p) => c.send(m, p, sessionId);
  return { s, sessionId, targetId: t.targetId };
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
export const evaluate = async (s, js) => {
  const r = await s("Runtime.evaluate", { expression: js, awaitPromise: true, returnByValue: true, userGesture: true });
  if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails));
  return r.result.value;
};
async function nav(c, url) {
  const { targetId } = await c.send("Target.createTarget", { url });
  const { sessionId } = await c.send("Target.attachToTarget", { targetId, flatten: true });
  const s = (m, p) => c.send(m, p, sessionId);
  await s("Page.enable");
  await s("Page.bringToFront");
  await s("Emulation.setFocusEmulationEnabled", { enabled: true });
  for (let i = 0; i < 50; i++) { await sleep(200); try { if ((await evaluate(s, "document.readyState")) === "complete") break; } catch {} }
  return { s, targetId };
}

const [cmd, ...args] = process.argv.slice(2);
const c = await connect();
if (cmd === "targets") {
  const { targetInfos } = await c.send("Target.getTargets");
  console.log(targetInfos.map((t) => `${t.type}\t${t.url}\t${t.title}`).join("\n"));
} else if (cmd === "open") {
  await nav(c, args[0]); console.log("opened", args[0]);
} else if (cmd === "eval") {
  const { s } = await attach(c, args[0]); console.log(JSON.stringify(await evaluate(s, args[1]), null, 1));
} else if (cmd === "shot") {
  const { s } = await attach(c, args[0]);
  const { data } = await s("Page.captureScreenshot", { format: "png" });
  writeFileSync(args[1], Buffer.from(data, "base64")); console.log("wrote", args[1]);
} else if (cmd === "login") {
  const { s } = await nav(c, "https://tawago.test/login");
  await evaluate(s, `document.querySelector('input[name=secret]').value='local-test-secret'; document.forms[0].submit(); 1`);
  await sleep(1500);
  console.log(await evaluate(s, "location.href + ' | ' + document.body.innerText"));
} else if (cmd === "flow") {
  const email = args[0] || "alice@tawago.test"; // "" means default, like nonce
  const nonce = args[1] || JSON.parse(readFileSync(new URL("../ctx-vector.json", here))).evpNonce;
  const { s } = await nav(c, "https://recover.tawago.test/?" + Date.now());
  // SETTER=attr|idl isolates one path; default both (rp.html setNonce).
  const setter = process.env.SETTER ?? "both";
  const setJs = setter === "attr" ? `document.getElementById('tok').setAttribute('nonce', ${JSON.stringify(nonce)}); 'attr'`
    : setter === "idl" ? `document.getElementById('tok').nonce = ${JSON.stringify(nonce)}; 'idl'`
    : `setNonce(${JSON.stringify(nonce)})`;
  console.log("nonce set:", setter, await evaluate(s, setJs));
  // Under a header CSP Blink may blank nonce content attributes. Show what the renderer will read.
  console.log("attr after set:", JSON.stringify(await evaluate(s, `document.getElementById('tok').getAttribute('nonce')`)));
  console.log("csp header:", await evaluate(s, `fetch(location.href).then(r => r.headers.get('content-security-policy') || '(none)')`));
  const { root } = await s("DOM.getDocument");
  const { nodeId } = await s("DOM.querySelector", { nodeId: root.nodeId, selector: "#email" });
  await s("DOM.focus", { nodeId });
  for (const ch of email) {
    await s("Input.dispatchKeyEvent", { type: "keyDown", key: ch, text: ch });
    await s("Input.dispatchKeyEvent", { type: "keyUp", key: ch });
  }
  await s("Input.dispatchKeyEvent", { type: "rawKeyDown", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 });
  await s("Input.dispatchKeyEvent", { type: "keyUp", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 });
  console.log("typed + tabbed; waiting", args[2] ?? 8000, "ms");
  await sleep(Number(args[2] ?? 8000));
  await evaluate(s, `document.getElementById('f').requestSubmit(); 1`);
  await sleep(500);
  const tok = await evaluate(s, "window.lastToken");
  console.log("token:", tok || "(empty)");
  if (tok) writeFileSync(new URL("tmp/token-latest.txt", here), tok + "\n");
}
c.ws.close();
process.exit(0);
