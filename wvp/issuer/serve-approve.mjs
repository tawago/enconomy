// A static page. The wallet needs a real web page to inject into. It holds no secrets and makes no decisions: the extension builds the message and checks the signature.
// Its host is the domain in the wallet message, so sites pin it. Usage: node issuer/serve-approve.mjs --port 8806 --name alice.eth
import { createServer } from "node:http";
const opt = (n, d) => { const i = process.argv.indexOf(`--${n}`); return i < 0 ? d : process.argv[i + 1]; };
const port = Number(opt("port", 8806)), name = opt("name", "alice.eth");
const PAGE = `<!doctype html><meta charset="utf-8"><title>Approve this browser</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f4f4f6;font:15px/1.5 system-ui,sans-serif;color:#18181b}main{background:#fff;border-radius:14px;box-shadow:0 8px 30px #0001;padding:32px;width:460px;box-sizing:border-box}h1{font-size:20px;margin:0 0 6px}p{margin:0 0 16px;color:#52525b}input{width:100%;box-sizing:border-box;font:inherit;padding:11px 12px;border:1px solid #d4d4d8;border-radius:9px;margin-bottom:12px}button{width:100%;font:600 15px system-ui;padding:11px;border:0;border-radius:9px;background:#18181b;color:#fff;cursor:pointer}button:disabled{opacity:.5}#out{margin-top:14px;min-height:22px;color:#52525b;word-break:break-word}</style>
<main><h1>Approve this browser</h1><p>Your wallet signs once. This browser can then log in for you.</p><ul style="margin:0 0 12px;padding-left:20px;color:#52525b"><li>Named login shows the site your name and address.</li><li>Anonymous shows only that you hold a valid credential.</li></ul><p>The wallet won't ask again until this expires, in 24 hours. To set up anonymous, the issuer sees your name and address once.</p>
<input id="n" value="${name}" aria-label="ENS name" spellcheck="false" autocapitalize="off"><button id="go">Connect wallet and approve</button><div id="out"></div></main><script src="/enroll.js"></script>`;
const JS = `
const out = document.getElementById("out"), go = document.getElementById("go"), input = document.getElementById("n");
const typed = new URLSearchParams(location.hash.slice(1)).get("name");
if (typed) input.value = typed;
go.onclick = async () => {
  go.disabled = true;
  try {
    if (!window.ethereum) throw new Error("No wallet on this page.");
    const [address] = await window.ethereum.request({ method: "eth_requestAccounts" });
    const { message } = await window.wvp.enrollBegin({ name: input.value, address });
    const hex = "0x" + [...new TextEncoder().encode(message)].map((b) => b.toString(16).padStart(2, "0")).join("");
    out.textContent = "Waiting for your wallet...";
    const signature = await window.ethereum.request({ method: "personal_sign", params: [hex, address] });
    const r = await window.wvp.enrollFinish({ signature });
    out.textContent = "Done: " + r.name + " until " + new Date(r.exp * 1000).toISOString();
  } catch (e) { out.textContent = (e.code ? e.code + ": " : "") + e.message; go.disabled = false; }
};`;
createServer((req, res) => {
  const path = new URL(req.url, "http://x").pathname;
  if (path === "/enroll.js") { res.writeHead(200, { "content-type": "text/javascript" }); return res.end(JS); }
  if (path === "/enroll") { res.writeHead(200, { "content-type": "text/html; charset=utf-8" }); return res.end(PAGE); }
  res.writeHead(404); res.end();
}).listen(port, "127.0.0.1", () => console.log(JSON.stringify({ ready: true, port, server: "approve" })));
