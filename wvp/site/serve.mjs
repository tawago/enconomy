// One site, one process. Each page load gets a fresh challenge in the markup. The proof check is siteCheck.
// Origin is fixed at startup, never read from a request. `now` comes from the token, and must be near this server's clock.
// Usage: node site/serve.mjs --origin http://site-a.test:8802 --port 8802 --issuer http://127.0.0.1:8801 --title "Site A" [--accent "#2563eb"]
import { createServer } from "node:http";
import { readFileSync } from "node:fs";
import { randomBytes, createHash } from "node:crypto";
import { siteCheck } from "./site-check.mjs";
import { sdk } from "../lib/openac.mjs";
import { loadFastProver } from "../lib/openac-fast.mjs";
import { parseIdentifier } from "../lib/identifier.mjs";
import { thirdParty } from "../lib/third-party.mjs";
import { verifyDirect } from "./direct-verify.mjs";
import { tableLookup, mainnetLookup } from "../lib/ens-lookup.mjs";
const opt = (n, d) => { const i = process.argv.indexOf(`--${n}`); return i < 0 ? d : process.argv[i + 1]; };
const origin = opt("origin"), port = Number(opt("port")), issuerUrl = opt("issuer"), title = opt("title", origin), accent = opt("accent", "#2563eb");
const log = (o) => console.log(JSON.stringify({ t: Date.now(), ...o }));

// Non-threaded opt-level 3 wrapper, verifying keys decoded once. Digests are the ones the SDK pins.
const VK = { prepare: ["1k_prepare_verifying.key", "f1fcc1d5036ef6ca9efb538b3510a5a492518018beb217c50ee2c014d7351add"], show: ["1k_show_verifying.key", "f0c447a9757d182e8aa23083bc3dba5a9a22f3e0fcbb344724568cc3c83352d8"] };
const t0 = performance.now();
const readKey = ([f, sha]) => { const b = readFileSync(thirdParty("keys", f)); const d = createHash("sha256").update(b).digest("hex"); if (d !== sha) throw new Error(`${f} digest ${d}`); return new Uint8Array(b); };
const prover = await loadFastProver(readFileSync(thirdParty("p2-cached/openac_plain2.wasm")));
const empty = new Uint8Array(0);
prover.cacheKeys({ prepareProvingKey: empty, showProvingKey: empty, prepareVerifyingKey: readKey(VK.prepare), showVerifyingKey: readKey(VK.show) });
const openac = await sdk.OpenAC.init({ wasmModule: prover });
const vks = { prepareVerifyingKey: empty, showVerifyingKey: empty };
// The issuer only matters for anonymous proofs. A site must still start and log people in by name with it gone.
const issuerKey = () => fetch(`${issuerUrl}/jwks`, { signal: AbortSignal.timeout(1000) }).then((r) => r.json()).then((j) => j.keys[0]).catch(() => null);
let trustedIssuer = await issuerKey();
// --ens table --name alice.eth --owner 0x... (default), or --ens mainnet --rpc https://... (read-only).
const lookup = opt("ens", "table") === "mainnet" ? mainnetLookup(opt("rpc", "https://ethereum-rpc.publicnode.com")) : tableLookup({ [opt("name", "alice.eth")]: opt("owner") });
const approveDomains = opt("approve-domain", "enroll.test:8806").split(",");

const open = new Map(), used = new Set(), sessions = new Map();
const TTL = 900, SKEW = 300;
const clock = () => Math.floor(Date.now() / 1000);
const newChallenge = () => { const challenge = randomBytes(32).toString("hex"); open.set(challenge, clock() + TTL); log({ op: "challenge", challenge: challenge.slice(0, 12) }); return challenge; };

async function submit(raw) {
  let tok;
  try { tok = JSON.parse(raw); } catch { return { accepted: false, reason: "bad_token" }; }
  const { v, challenge, now, claim, bundle } = tok ?? {};
  const direct = v === 2 && tok.kind === "direct";
  if ((v !== 1 && !direct) || typeof challenge !== "string" || (!direct && typeof bundle !== "string") || !Number.isInteger(now)) return { accepted: false, reason: "bad_token" };
  if (used.has(challenge)) return { accepted: false, reason: "challenge_used" };
  const expires = open.get(challenge);
  if (expires === undefined) return { accepted: false, reason: "unknown_challenge" };
  open.delete(challenge); used.add(challenge);
  if (expires <= clock()) return { accepted: false, reason: "challenge_expired" };
  // The holder picks now, so a site can't probe the expiry. The cost: a cheater gets SKEW seconds of slack.
  if (Math.abs(now - clock()) > SKEW) return { accepted: false, reason: "bad_time" };
  if (direct) { const t = performance.now(); const r = await verifyDirect({ tok, origin, lookup, approveDomains, nowSec: clock() }); return { ...r, verifyMs: performance.now() - t }; }
  // A demo issuer makes a new key at each start. Use its current key, or the last one seen if it's down.
  trustedIssuer = (await issuerKey()) ?? trustedIssuer;
  if (!trustedIssuer) return { accepted: false, reason: "no_issuer" };
  let id = null;
  if (claim !== null) {
    id = parseIdentifier(claim);
    if (!id || id.claim !== claim) return { accepted: false, reason: "bad_claim" };
  }
  const r = await siteCheck({ openac, sdk, vks, trustedIssuer, origin, ctx: { challenge, now, name: id?.slot ?? null }, bundle: new Uint8Array(Buffer.from(bundle, "base64")) });
  return { ...r, name: id?.claim ?? null, kind: id?.kind ?? "anonymous" };
}

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const CSS = `
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #f4f4f6; font: 15px/1.5 system-ui, sans-serif; color: #18181b; }
  main { background: #fff; border-radius: 16px; box-shadow: 0 8px 30px #0001; padding: 36px; width: 560px; }
  h1 { font-size: 22px; margin: 0 0 4px; } .sub { color: #71717a; margin: 0 0 22px; }
  .row { display: flex; align-items: center; gap: 14px; }
  #who { flex: 1; min-width: 0; font: 15px ui-monospace, SFMono-Regular, Menlo, monospace; padding: 12px 14px; border: 1px solid #d4d4d8; border-radius: 10px; outline: none; }
  #who:focus { border-color: ${accent}; box-shadow: 0 0 0 3px ${accent}22; }
  #who[readonly] { background: #f4f4f5; color: #a1a1aa; }
  .switch { display: flex; align-items: center; gap: 8px; cursor: pointer; user-select: none; color: #3f3f46; }
  #anon { appearance: none; width: 42px; height: 24px; border-radius: 12px; background: #d4d4d8; position: relative; margin: 0; cursor: pointer; transition: background .15s; }
  #anon::after { content: ""; position: absolute; top: 2px; left: 2px; width: 20px; height: 20px; border-radius: 50%; background: #fff; box-shadow: 0 1px 2px #0003; transition: left .15s; }
  #anon:checked { background: ${accent}; } #anon:checked::after { left: 20px; }
  #anon:focus-visible { outline: 2px solid ${accent}; outline-offset: 2px; }
  #status { min-height: 26px; margin-top: 18px; display: flex; align-items: center; gap: 8px; color: #52525b; }
  #status.ok { color: #15803d; font-weight: 600; } #status.bad { color: #b91c1c; }
  .spin { width: 15px; height: 15px; border: 2px solid #d4d4d8; border-top-color: ${accent}; border-radius: 50%; animation: s .8s linear infinite; }
  @keyframes s { to { transform: rotate(360deg); } }
  .who-text { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; word-break: break-all; }
  #go { width: 100%; margin-top: 14px; font: 600 15px system-ui, sans-serif; padding: 12px; border: 0; border-radius: 10px; background: ${accent}; color: #fff; cursor: pointer; }
  #go:disabled { opacity: .5; cursor: default; } #go[hidden] { display: none; }
  #out { background: none; border: 0; padding: 0; margin-left: auto; font: inherit; color: #71717a; text-decoration: underline; cursor: pointer; }
`;
// The whole login is this markup. Nothing here calls the extension. wvp/README.md says what each attribute means.
const form = (nonce) => `<form id="login" onsubmit="return false">
  <div class="row">
    <input id="who" type="text" autocomplete="wvp" placeholder="alice.eth or 0x..." aria-label="Your address or ENS" spellcheck="false" autocapitalize="off">
    <label class="switch"><input id="anon" type="checkbox" data-wvp-anonymous>Anonymous</label>
  </div>
  <button id="go" type="button" data-wvp-signin>Sign in</button>
  <input id="token" type="hidden" autocomplete="wvp-token" nonce="${nonce}">
</form>`;
const PAGE = (nonce) => `<!doctype html><meta charset="utf-8"><title>${esc(title)}</title><style>${CSS}</style>
<main><h1>${esc(title)}</h1><p class="sub">Type your address or ENS.</p>${form(nonce)}<div id="status" role="status"></div></main><script src="/site.js"></script>`;
// Same form, no site script at all, for tests that want the raw token. The field fills with no page JS.
const BARE = (nonce) => `<!doctype html><meta charset="utf-8"><title>${esc(title)} bare</title>${form(nonce)}`;
const JS = `
const $ = (id) => document.getElementById(id);
const tok = $("token"), who = $("who"), anon = $("anon"), status = $("status");
const show = (cls, html) => { status.className = cls; status.innerHTML = html; };
const say = (cls, text, spin) => { show(cls, spin ? '<span class="spin"></span>' : ""); status.append(text); };
const post = (u, b) => fetch(u, { method: "POST", body: b ?? "" }).then((r) => r.json());
let t0 = 0, signedIn = false;
window.__result = null;
const verified = (name, ms) => {
  signedIn = true;
  // Signed in: Sign out is the only thing left to do.
  $("go").hidden = true; who.readOnly = true; anon.disabled = true;
  show("ok", "");
  const b = document.createElement("span"); b.className = name ? "who-text" : ""; b.textContent = "\\u2713 Verified: " + (name ?? "anonymous");
  status.append(b);
  if (ms != null) { const s = document.createElement("span"); s.style = "font-weight:400;color:#71717a"; s.textContent = (ms / 1000).toFixed(1) + " s"; status.append(s); }
  const o = document.createElement("button"); o.id = "out"; o.type = "button"; o.textContent = "Sign out"; o.onclick = signOut; status.append(o);
};
const signOut = async () => { await post("/logout"); location.reload(); };
const fresh = async () => { const { challenge } = await post("/challenge"); tok.setAttribute("nonce", challenge); };
tok.closest("form").addEventListener("wvp-state", async () => {
  const st = tok.dataset.wvpState;
  if (st === "working") { t0 = performance.now(); return say("", "Proving in your browser...", true); }
  if (st === "none") { window.__result = { none: true }; return say("bad", "No proof was made."); }
  if (st === "idle") { window.__result = null; if (signedIn) { signedIn = false; await post("/logout"); await fresh(); } return say("", ""); }
  if (st === "done") {
    say("", "Checking the proof...", true);
    const tProof = performance.now();
    const r = await post("/submit", tok.value);
    window.__result = { ...r, proofMs: tProof - t0, totalMs: performance.now() - t0 };
    await fresh();
    if (r.accepted) { verified(r.name, performance.now() - t0); if (r.mode === "direct") { $("direct")?.remove(); const a = document.createElement("div"); a.id = "direct"; a.style = "font-weight:400;font-size:13px;color:#71717a;margin-top:6px;word-break:break-all"; a.textContent = "No issuer, no proof. This site sees your wallet: " + r.address + (r.lookup ? " (ENS: " + r.lookup + ")" : ""); status.after(a); } } else { signedIn = false; say("bad", "Rejected: " + r.reason); }
  }
});
fetch("/me").then((r) => r.json()).then((m) => { if (m.loggedIn) { window.__me = m; verified(m.name); who.readOnly = true; if (m.name) who.value = m.name; else anon.checked = true; } });
`;
createServer((req, res) => {
  const send = (status, obj, h = {}) => { res.writeHead(status, { "content-type": "application/json", ...h }); res.end(JSON.stringify(obj)); };
  const html = (body, h = {}) => { res.writeHead(200, { "content-type": "text/html; charset=utf-8", ...h }); res.end(body); };
  const path = new URL(req.url, "http://x").pathname;
  if (req.method === "GET" && path === "/") return html(PAGE(newChallenge()));
  if (req.method === "GET" && path === "/bare") return html(BARE(newChallenge()));
  // A header CSP makes the browser blank a nonce attribute that came in the markup. Here to test that.
  if (req.method === "GET" && path === "/csp") return html(BARE(newChallenge()), { "content-security-policy": "default-src 'self'" });
  if (req.method === "GET" && path === "/site.js") { res.writeHead(200, { "content-type": "text/javascript" }); return res.end(JS); }
  if (req.method === "POST" && path === "/challenge") return send(200, { challenge: newChallenge() });
  if (req.method === "POST" && path === "/submit") {
    let body = "", big = false;
    req.on("data", (d) => { body += d; if (body.length > 400000) { big = true; req.destroy(); } });
    req.on("end", async () => {
      if (big) return;
      let r;
      try { r = await submit(body); } catch (e) { r = { accepted: false, reason: "bad_request", detail: String(e.message).slice(0, 200) }; }
      let h = {};
      if (r.accepted) { const sid = randomBytes(16).toString("hex"); sessions.set(sid, { name: r.name ?? null }); h["set-cookie"] = `sid=${sid}; HttpOnly; SameSite=Strict; Path=/`; }
      log({ op: "submit", accepted: r.accepted, reason: r.reason, ms: r.ms, verifyMs: r.verifyMs, name: r.name ?? null, kind: r.kind ?? null, tokenBytes: body.length });
      send(200, r, h);
    });
    return;
  }
  const sidOf = () => (req.headers.cookie ?? "").match(/sid=([0-9a-f]+)/)?.[1];
  if (req.method === "GET" && path === "/me") return send(200, { loggedIn: sessions.has(sidOf()), name: sessions.get(sidOf())?.name ?? null });
  if (req.method === "POST" && path === "/logout") { sessions.delete(sidOf()); return send(200, {}, { "set-cookie": "sid=; Max-Age=0; Path=/" }); }
  send(404, { error: "not_found" });
}).listen(port, "127.0.0.1", () => log({ ready: true, origin, port, startMs: Math.round(performance.now() - t0), rssMB: Math.round(process.memoryUsage().rss / 1048576) }));
