// A static page, shown in a small window the extension opens. The wallet needs a real web page to inject into. It holds no secrets and makes no decisions: the extension builds the message and checks the signature.
// Its host is the domain in the wallet message, so sites pin it. Usage: node issuer/serve-approve.mjs --port 8806 --name alice.eth [--anonymous]
//   --anonymous  an issuer is running, so say what anonymous sign-in shows and costs.
import { createServer } from "node:http";
const opt = (n, d) => { const i = process.argv.indexOf(`--${n}`); return i < 0 ? d : process.argv[i + 1]; };
const port = Number(opt("port", 8806)), name = opt("name", "alice.eth"), anonymous = process.argv.includes("--anonymous");
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const PAGE = `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Sign in with your wallet</title>
<style>
:root{--bg:#FFF;--ink:#1C1C1C;--on:#FFF;--muted:#6B6B6B;--rule:#BDBDBD;color-scheme:light dark}
@media (prefers-color-scheme:dark){:root{--bg:#1C1C1A;--ink:#ECECE8;--on:#1C1C1A;--muted:#A8A8A4;--rule:#55554F}}
*{box-sizing:border-box}html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,sans-serif;display:flex;flex-direction:column}
main{flex:1;min-height:0;overflow:auto;display:flex;padding:14px 24px}
.box{margin:auto;width:100%;max-width:330px;text-align:center}
h1{font-size:20px;line-height:1.3;font-weight:600;margin:0 0 10px}
p{margin:0}
.name{font-size:17px;font-weight:600;margin-bottom:12px;word-break:break-word}
.fine{margin-top:8px;font-size:12.5px;line-height:1.4;color:var(--muted)}
[hidden]{display:none!important}
main:has(#n:not([hidden])) .name{display:none}
label{display:block;margin-bottom:4px;font-size:13px;color:var(--muted)}
#n{display:block;width:100%;margin-bottom:12px;font:15px/1.4 system-ui,sans-serif;text-align:center;color:var(--ink);background:none;border:1px solid var(--rule);border-radius:6px;padding:8px 10px;outline:none}
#n:focus{border-color:var(--ink)}
#out{min-height:20px;margin:10px 0 6px;word-break:break-word}
button{font:inherit;cursor:pointer;max-width:100%}
#go{display:block;width:100%;font-weight:600;padding:10px 16px;border-radius:6px;background:var(--ink);color:var(--on);border:0}
#go:disabled{opacity:.6;cursor:default}
#no{margin-top:4px;padding:5px 12px;font-size:13px;color:var(--muted);background:none;border:0}
</style>
<main><div class="box">
<h1>Sign in with your wallet, once</h1>
<p class="name"><span id="t">${esc(name)}</span></p>
<label for="n" id="nl" hidden>Your ENS name</label><input id="n" value="${esc(name)}" spellcheck="false" autocapitalize="off" hidden>
<p>Your wallet signs once and it costs nothing. After that, this browser can sign you in to sites as <span id="t2">${esc(name)}</span> for about a day.</p>
<p class="fine">Sites you sign in to see your name and wallet address.</p>
${anonymous ? `<p class="fine">You can also sign in without showing a name. To set that up, our sign-in service sees your name and address once.</p>` : ""}
<div id="out" role="status"></div>
<button id="go" type="button">Continue with wallet</button>
<button id="no" type="button">Not now</button>
</div></main><script src="/enroll.js"></script></html>`;
const JS = `
const out = document.getElementById("out"), go = document.getElementById("go"), input = document.getElementById("n");
const typed = new URLSearchParams(location.hash.slice(1)).get("name");
// The name is already in the title, so there's nothing to ask. A field only when nobody typed one: anonymous, first time.
if (typed) input.value = typed; else document.getElementById("nl").hidden = input.hidden = false;
const title = () => { for (const id of ["t", "t2"]) document.getElementById(id).textContent = input.value || "this name"; };
input.oninput = title; title();
const short = (a) => a.slice(0, 6) + "\\u2026" + a.slice(-4);
document.getElementById("no").onclick = () => window.close();
go.onclick = async () => {
  go.disabled = true;
  out.textContent = "";
  try {
    if (!window.ethereum) throw new Error("No wallet on this page. Turn one on in this browser, then reload.");
    if (!window.wvp) throw new Error("Sign-in isn't active on this page. Reload it, or start the demo again.");
    out.textContent = "Check your wallet.";
    const [address] = await window.ethereum.request({ method: "eth_requestAccounts" });
    const { message } = await window.wvp.enrollBegin({ name: input.value, address });
    const hex = "0x" + [...new TextEncoder().encode(message)].map((b) => b.toString(16).padStart(2, "0")).join("");
    out.textContent = "Check your wallet and sign as " + short(address) + ".";
    const signature = await window.ethereum.request({ method: "personal_sign", params: [hex, address] });
    await window.wvp.enrollFinish({ signature });
    out.textContent = "All set. You can close this window.";
    go.hidden = document.getElementById("no").hidden = true;
  } catch (e) {
    out.textContent = e?.code === 4001 ? "No problem, nothing was signed. Try again when you're ready."
      : e?.code === -32002 ? "Your wallet already has a request open. Look for its window."
      : e?.code === "bad_name" ? "That doesn't look like an ENS name. Check it and try again."
      : e?.code === "wrong_wallet" ? "That signature came from a different wallet. Try again."
      : e?.code === "no_pending" ? "That took a little too long. Try again."
      : e?.code === "not_approval_page" ? "Sign-in can't start from this page."
      : (e?.message ?? String(e));
    go.disabled = false;
  }
};`;
createServer((req, res) => {
  const path = new URL(req.url, "http://x").pathname;
  if (path === "/enroll.js") { res.writeHead(200, { "content-type": "text/javascript" }); return res.end(JS); }
  if (path === "/enroll") { res.writeHead(200, { "content-type": "text/html; charset=utf-8" }); return res.end(PAGE); }
  res.writeHead(404); res.end();
}).listen(port, "127.0.0.1", () => console.log(JSON.stringify({ ready: true, port, server: "approve" })));
