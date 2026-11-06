// Issuer, plus the enrollment page. Logic in issuer.mjs. 127.0.0.1 only. Throwaway key, made fresh each start.
// Usage: node issuer/serve.mjs --port 8801 --name alice.eth --owner 0x...
import { createServer } from "node:http";
import { createIssuer, newIssuerKey, Refusal } from "./issuer.mjs";
import { tableLookup } from "../lib/ens-lookup.mjs";
const opt = (n, d) => { const i = process.argv.indexOf(`--${n}`); return i < 0 ? d : process.argv[i + 1]; };
const port = Number(opt("port", 8801)), name = opt("name", "alice.eth"), owner = opt("owner");
if (!owner) throw new Error("--owner is required");
const origin = `http://issuer.test:${port}`;
const issuer = createIssuer({ key: await newIssuerKey(), lookup: tableLookup({ [name]: owner }), domain: `issuer.test:${port}`, uri: `${origin}/` });
const log = (o) => console.log(JSON.stringify({ t: Date.now(), ...o }));
const PAGE = `<!doctype html><meta charset="utf-8"><title>WVP issuer: approve this browser</title>
<style>
  body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #f4f4f6; font: 15px/1.5 system-ui, sans-serif; color: #18181b; }
  main { background: #fff; border-radius: 14px; box-shadow: 0 8px 30px #0001; padding: 32px; width: 460px; box-sizing: border-box; }
  h1 { font-size: 20px; margin: 0 0 6px; } p { margin: 0 0 16px; color: #52525b; }
  input { width: 100%; box-sizing: border-box; font: inherit; padding: 11px 12px; border: 1px solid #d4d4d8; border-radius: 9px; margin-bottom: 12px; }
  button { width: 100%; font: 600 15px system-ui; padding: 11px; border: 0; border-radius: 9px; background: #18181b; color: #fff; cursor: pointer; }
  button:disabled { opacity: .5; cursor: default; }
  #out { margin-top: 14px; min-height: 22px; color: #52525b; word-break: break-word; }
</style>
<main><h1>Approve this browser</h1><p>Your wallet signs once. Then this browser proves your name and address to sites, with no more wallet prompts, until the credential expires.</p>
<input id="n" value="${name}" aria-label="ENS name" spellcheck="false" autocapitalize="off"><button id="go">Connect wallet and approve</button><div id="out"></div></main>
<script src="/enroll.js"></script>`;
const JS = `
const out = document.getElementById("out"), go = document.getElementById("go"), input = document.getElementById("n");
const typed = new URLSearchParams(location.hash.slice(1)).get("name");
if (typed) input.value = typed;
window.enroll = async (name) => {
  if (!window.ethereum) throw Object.assign(new Error("No wallet on this page."), { code: "" });
  const t0 = performance.now();
  const [address] = await window.ethereum.request({ method: "eth_requestAccounts" });
  const { message } = await window.wvp.enrollBegin({ name, address });
  const hex = "0x" + [...new TextEncoder().encode(message)].map((b) => b.toString(16).padStart(2, "0")).join("");
  out.textContent = "Waiting for your wallet...";
  const tw = performance.now();
  const signature = await window.ethereum.request({ method: "personal_sign", params: [hex, address] });
  const walletMs = performance.now() - tw;
  out.textContent = "Signed. Preparing this browser, about 20 s. Don't close this tab.";
  const r = await window.wvp.enrollFinish({ signature });
  out.textContent = "Done: " + r.name + " and " + address + " until " + new Date(r.exp * 1000).toISOString();
  return window.__enroll = { address, message, walletMs, pageTotalMs: performance.now() - t0, ...r };
};
go.onclick = () => { go.disabled = true; window.enroll(input.value).catch((e) => { out.textContent = (e.code ? e.code + ": " : "") + e.message; go.disabled = false; }); };
`;
const cors = { "access-control-allow-origin": "*", "cross-origin-resource-policy": "cross-origin" };
createServer((req, res) => {
  const send = (status, obj) => { res.writeHead(status, { "content-type": "application/json", ...cors }); res.end(JSON.stringify(obj)); };
  log({ method: req.method, url: req.url, origin: req.headers.origin ?? null, referer: req.headers.referer ?? null });
  if (req.method === "GET" && req.url === "/enroll") { res.writeHead(200, { "content-type": "text/html; charset=utf-8" }); return res.end(PAGE); }
  if (req.method === "GET" && req.url === "/enroll.js") { res.writeHead(200, { "content-type": "text/javascript" }); return res.end(JS); }
  if (req.method === "GET" && req.url === "/nonce") return send(200, { nonce: issuer.newNonce() });
  if (req.method === "GET" && req.url === "/jwks") return send(200, { keys: [issuer.publicJwk] });
  if (req.method === "POST" && req.url === "/issue") {
    let body = "";
    req.on("data", (d) => { body += d; if (body.length > 65536) req.destroy(); });
    req.on("end", async () => {
      try { const r = await issuer.issue(JSON.parse(body)); log({ issued: name, credentials: 2, exp: r.exp }); send(200, r); }
      catch (e) { log({ refused: e.code ?? e.message }); send(e instanceof Refusal ? 403 : 400, { error: e.code ?? "bad_request", why: e.why ?? e.message }); }
    });
    return;
  }
  send(404, { error: "not_found" });
}).listen(port, "127.0.0.1", () => log({ ready: true, port, origin }));
