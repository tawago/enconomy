// One site, one process. Each page load gets a fresh challenge in the markup. The proof check is siteCheck.
// Origin is fixed at startup, never read from a request. `now` comes from the token, and must be near this server's clock.
// Usage: node site/serve.mjs --origin http://blobzon.test:8802 --port 8802 --issuer http://127.0.0.1:8801 --brand blobzon
//   --brand  blobzon or blobchannel, from site/brands/. Both are fictional. The page around the form comes from there.
//   --name-only  refuse logins that read no ENS: a typed address, or a proof for a named claim. Anonymous is unaffected.
//   --no-proofs  don't load the verifying keys, about 1.1 GiB. Anonymous is refused, named login works.
//   --org blob.eth  refuse any claim not under this name, not_in_org, before any lookup. Anonymous is unaffected. Default off.
import { createServer } from "node:http";
import { readFileSync } from "node:fs";
import { randomBytes, createHash } from "node:crypto";
import { siteCheck } from "./site-check.mjs";
import { loadFastProver } from "../lib/openac-fast.mjs";
import { parseIdentifier } from "../lib/identifier.mjs";
import { thirdParty } from "../lib/third-party.mjs";
import { verifyDirect } from "./direct-verify.mjs";
import { tableLookup, mainnetLookup, chainLookup } from "../lib/ens-lookup.mjs";
import * as blobzon from "./brands/blobzon.mjs";
import * as blobchannel from "./brands/blobchannel.mjs";
const opt = (n, d) => { const i = process.argv.indexOf(`--${n}`); return i < 0 ? d : process.argv[i + 1]; };
const BRANDS = { blobzon, blobchannel };
const brand = BRANDS[opt("brand", "blobzon")];
if (!brand) throw new Error(`--brand ${opt("brand")}: use ${Object.keys(BRANDS).join(" or ")}`);
const origin = opt("origin"), port = Number(opt("port")), issuerUrl = opt("issuer"), title = brand.title;
const nameOnly = process.argv.includes("--name-only"), noProofs = process.argv.includes("--no-proofs"), org = opt("org");
const log = (o) => console.log(JSON.stringify({ t: Date.now(), ...o }));

// Non-threaded opt-level 3 wrapper, verifying keys decoded once. Digests are the ones the SDK pins.
const VK = { prepare: ["1k_prepare_verifying.key", "f1fcc1d5036ef6ca9efb538b3510a5a492518018beb217c50ee2c014d7351add"], show: ["1k_show_verifying.key", "f0c447a9757d182e8aa23083bc3dba5a9a22f3e0fcbb344724568cc3c83352d8"] };
const t0 = performance.now();
const readKey = ([f, sha]) => { const b = readFileSync(thirdParty("keys", f)); const d = createHash("sha256").update(b).digest("hex"); if (d !== sha) throw new Error(`${f} digest ${d}`); return new Uint8Array(b); };
const empty = new Uint8Array(0);
let sdk = null, openac = null;
if (!noProofs) {
  ({ sdk } = await import("../lib/openac.mjs"));
  const prover = await loadFastProver(readFileSync(thirdParty("p2-cached/openac_plain2.wasm")));
  prover.cacheKeys({ prepareProvingKey: empty, showProvingKey: empty, prepareVerifyingKey: readKey(VK.prepare), showVerifyingKey: readKey(VK.show) });
  openac = await sdk.OpenAC.init({ wasmModule: prover });
}
const vks = { prepareVerifyingKey: empty, showVerifyingKey: empty };
// The issuer only matters for anonymous proofs. A site must still start and log people in by name with it gone.
const issuerKey = () => fetch(`${issuerUrl}/jwks`, { signal: AbortSignal.timeout(1000) }).then((r) => r.json()).then((j) => j.keys[0]).catch(() => null);
let trustedIssuer = await issuerKey();
// --ens table --name alice.eth --owner 0x... or --table file.json (default), --ens mainnet --rpc https://... or --ens deployment --deployment file.json with { rpc, chainId, universalResolver }. All read-only, and read again at each login.
const ens = opt("ens", "table");
const makeLookup = () => {
  if (ens === "table") return tableLookup(opt("table") ?? { [opt("name", "alice.eth")]: opt("owner") });
  if (ens === "mainnet") return mainnetLookup(opt("rpc", "https://ethereum-rpc.publicnode.com"));
  if (ens === "deployment") { const { rpc, chainId, universalResolver } = JSON.parse(readFileSync(opt("deployment"), "utf8")); return chainLookup({ rpcUrl: rpc, chainId, universalResolver }); }
  throw new Error(`--ens ${ens}: use table, mainnet or deployment`);
};
const lookup = makeLookup();
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
  // A typed address counts as outside the org too: it reads no ENS, so it would walk past this check.
  if (org && claim !== null && !(typeof claim === "string" && claim.endsWith(`.${org}`))) return { accepted: false, reason: "not_in_org" };
  if (direct) { const t = performance.now(); const r = await verifyDirect({ tok, origin, lookup, approveDomains, nowSec: clock(), nameOnly }); return { ...r, verifyMs: performance.now() - t }; }
  // A proof for a named claim reads no ENS either.
  if (nameOnly && claim !== null) return { accepted: false, reason: "name_only" };
  if (noProofs) return { accepted: false, reason: "no_proofs" };
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
const short = (a) => (a ? `${a.slice(0, 6)}\u2026${a.slice(-4)}` : "");
const ENS_NOTE = { table: "a local table", mainnet: "mainnet ENS", deployment: "our test ENS on devnet 1337" }[ens];
// What every brand shares: the field, its end-of-field mark, and the status lines. A brand only sets the variables and its own page around this.
const BASE = `
  * { box-sizing: border-box; }
  html { scrollbar-gutter: stable; scrollbar-width: thin; scrollbar-color: color-mix(in srgb, var(--ink) 28%, transparent) transparent; }
  body { margin: 0; }
  [hidden] { display: none !important; }
  #login label.name { display: block; }
  .field { position: relative; display: block; }
  .field input { width: 100%; padding-right: 40px; }
  .tick { position: absolute; right: 11px; top: 50%; width: 22px; height: 22px; margin-top: -11px; pointer-events: none; }
  [data-state="working"] .tick { border: 2px solid color-mix(in srgb, var(--accent) 25%, transparent); border-top-color: var(--accent); border-radius: 50%; animation: wvp-spin .7s linear infinite; }
  .tick svg { display: none; width: 22px; height: 22px; }
  [data-state="ok"] .tick .yes, [data-state="error"] .tick .no { display: block; }
  .tick path { fill: none; stroke-width: 2.4; stroke-linecap: round; stroke-linejoin: round; }
  .yes path { stroke: var(--accent); }
  [data-state="ok"] .tick .yes { animation: wvp-pop .16s ease-out both; }
  .no path { stroke: var(--error); }
  #login[data-state="error"] #who { border-color: var(--error); }
  [data-state="working"] #go, [data-state="ok"] #go { opacity: .55; }
  [data-state="ok"] #go { pointer-events: none; }
  #go:disabled { cursor: default; }
  .msgs { display: grid; gap: 4px; align-content: start; min-height: 62px; margin-top: 4px; }
  #status { color: var(--error); min-height: 20px; }
  #status:empty { display: none; }
  #status.hint { color: inherit; opacity: .75; }
  .share { margin: 0; opacity: .72; }
  .switch { display: inline-flex; align-items: center; gap: 8px; cursor: pointer; user-select: none; }
  #view { animation: wvp-fade .24s ease-out; }
  @keyframes wvp-spin { to { transform: rotate(360deg); } }
  @keyframes wvp-pop { from { opacity: 0; transform: scale(.72); } }
  @keyframes wvp-fade { from { opacity: 0; } }
  @media (prefers-reduced-motion: reduce) { .tick, .tick .yes, #view { animation-duration: .001s !important; } [data-state="working"] .tick { animation-duration: 2s !important; } }
`;
// The whole login is this markup. Nothing here calls the extension. wvp/README.md says what each attribute means.
const form = (nonce, signedIn = false) => `<form id="login" onsubmit="return false"${signedIn ? " hidden" : ""}>
  <label class="name" for="who">ENS name</label>
  <div class="entry">
    <span class="field"><input id="who" type="text" autocomplete="wvp" placeholder="yourname.eth" spellcheck="false" autocapitalize="off"${signedIn ? " readonly" : ""}><span class="tick" aria-hidden="true"><svg class="yes" viewBox="0 0 18 18"><path d="M3 9.6l4 4 8-9"/></svg><svg class="no" viewBox="0 0 18 18"><path d="M4.5 4.5l9 9M13.5 4.5l-9 9"/></svg></span></span>
    <button id="go" type="button" data-wvp-signin${signedIn ? " hidden" : ""}>Sign in</button>
  </div>
  ${noProofs ? "" : `<label class="switch"><input id="anon" type="checkbox" data-wvp-anonymous>${esc(brand.anonLabel)}</label>`}
  <p class="share">Signing in shares your name and wallet address with ${esc(title)}.</p>
  <div class="msgs"><div id="status" role="status"></div><div data-wvp-status></div></div>
  <input id="token" type="hidden" autocomplete="wvp-token" nonce="${nonce}">
</form>`;
const account = (s) => `<span class="acct" title="${esc(s.address ?? "")}"><b>${s.name ? esc(s.name) : "Member, no name shared"}</b>${s.address ? `<code>${esc(short(s.address))}</code>` : ""}</span><button id="out" type="button">Sign out</button>`;
const member = (s) => brand.signedIn({ name: s.name, address: s.address, short: short(s.address) }, esc);
const PAGE = (nonce, s) => `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>${esc(title)}</title><link rel="icon" href="data:image/svg+xml,${encodeURIComponent(brand.favicon)}"><style>${BASE}${brand.css}</style>
<body data-view="${s ? "in" : "out"}">${brand.header(`<div id="account">${s ? account(s) : ""}</div>`, esc)}
<main id="view">${s ? member(s) : brand.signedOut(form(nonce), esc)}</main>
${s ? `<div hidden>${form(nonce, true)}</div>` : ""}
<footer class="colophon">${esc(title)} is a demo site, not a real ${esc(brand.kind)}, and isn't affiliated with any company. Names come from ${esc(ENS_NOTE)}.</footer>
<script src="/site.js?v=2"></script></body></html>`;
// Same form, no site script at all, for tests that want the raw token. The field fills with no page JS.
const BARE = (nonce) => `<!doctype html><meta charset="utf-8"><title>${esc(title)} bare</title>${form(nonce)}`;
const JS = `
const $ = (id) => document.getElementById(id);
const tok = $("token"), who = $("who"), anon = $("anon"), status = $("status"), form = $("login");
const SITE = ${JSON.stringify(title)};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const post = (u, b) => fetch(u, { method: "POST", body: b ?? "" }).then((r) => r.json());
const say = (text, hint) => { status.textContent = text; status.className = hint ? "hint" : ""; };
const REFUSED = {
  not_owner: (n) => n + " now points to a different wallet.",
  name_only: () => SITE + " signs in by ENS name. Type your name, not an address.",
  not_in_org: () => SITE + " only takes names under " + ${JSON.stringify(org ?? "")} + ".",
  expired: () => "That approval has expired. Sign in again.",
  lookup_failed: () => SITE + " couldn't read that name right now. Try again.",
  challenge_used: () => "This sign-in went stale. Try again.", challenge_expired: () => "This sign-in went stale. Try again.", unknown_challenge: () => "This sign-in went stale. Try again.", bad_time: () => "This sign-in went stale. Try again.",
};
let t0 = 0, signedIn = false;
window.__result = null;
const short = (a) => a.slice(0, 6) + "\\u2026" + a.slice(-4);
const signOut = async () => { await post("/logout"); location.reload(); };
$("out")?.addEventListener("click", signOut);
// The members' page comes from the server, and only with a session.
const enter = async (r) => {
  signedIn = true;
  $("go").hidden = true; who.readOnly = true; if (anon) anon.disabled = true;
  const html = await fetch("/members").then((x) => x.text());
  const acct = $("account"); acct.textContent = "";
  const a = document.createElement("span"); a.className = "acct"; a.title = r.address ?? "";
  const b = document.createElement("b"); b.textContent = r.name ?? "Member, no name shared"; a.append(b);
  if (r.address) { const c = document.createElement("code"); c.textContent = short(r.address); a.append(c); }
  const o = document.createElement("button"); o.id = "out"; o.type = "button"; o.textContent = "Sign out"; o.onclick = signOut;
  acct.append(a, o);
  const parked = document.createElement("div"); parked.hidden = true; parked.append(form); document.body.append(parked);
  const view = $("view"); view.style.animation = "none"; void view.offsetWidth; view.style.animation = "";
  view.innerHTML = html; document.body.dataset.view = "in";
};
// The extension marks the token at once on a real press. No mark means it isn't in this tab, and nothing else would tell the user.
const noExtension = (e) => { if (e.isTrusted) setTimeout(() => { if (!tok.hasAttribute("data-wvp-state")) say("This site needs the WVP browser extension. If you just added it, reload this page."); }, 1000); };
$("go").addEventListener("click", noExtension);
who.addEventListener("keydown", (e) => { if (e.key === "Enter") noExtension(e); });
// Page-only hint when leaving the field. Starts nothing: leaving a field isn't asking to sign in.
who.addEventListener("blur", () => { if (who.value.startsWith("0x")) say(SITE + " signs in by name. Addresses won't work here.", true); });
who.addEventListener("input", () => { if (status.className === "hint") say(""); if (form.dataset.state === "error") { form.dataset.state = ""; say(""); } });
anon?.addEventListener("change", () => { document.querySelector(".share").textContent = anon.checked ? SITE + " sees only that you hold a valid approval, nothing else." : "Signing in shares your name and wallet address with " + SITE + "."; });
form.addEventListener("wvp-state", async () => {
  const st = tok.dataset.wvpState;
  if (st === "working") { t0 = performance.now(); form.dataset.state = "working"; return say(""); }
  if (st === "none") { form.dataset.state = ""; window.__result = { none: true }; return; }
  if (st === "idle") { form.dataset.state = ""; window.__result = null; if (signedIn) { signedIn = false; await post("/logout"); await fresh(); } return say(""); }
  if (st === "done") {
    const tProof = performance.now();
    const r = await post("/submit", tok.value);
    // Tells the extension why, same way the extension tells us: an attribute and an event. It acts only on not_owner, for a token it just made.
    if (!r.accepted) { tok.setAttribute("data-wvp-verdict", r.reason); tok.dispatchEvent(new Event("wvp-verdict", { bubbles: true })); }
    await fresh();
    const res = { ...r, proofMs: tProof - t0, totalMs: performance.now() - t0 };
    if (r.accepted) {
      // A named login takes about 0.1 s. Long enough to see the spinner and the check, no longer.
      await sleep(Math.max(0, 350 - (performance.now() - t0)));
      form.dataset.state = "ok";
      await sleep(700);
      await enter(r);
    } else {
      signedIn = false;
      form.dataset.state = "error";
      say((REFUSED[r.reason] ?? (() => SITE + " couldn't check that sign-in. Try again."))(who.value));
    }
    // Last. A script playing the user acts the moment this appears.
    window.__result = res;
  }
});
const fresh = async () => { const { challenge } = await post("/challenge"); tok.setAttribute("nonce", challenge); };
fetch("/me").then((r) => r.json()).then((m) => { if (m.loggedIn) { window.__me = m; signedIn = true; } });
`;
createServer((req, res) => {
  const send = (status, obj, h = {}) => { res.writeHead(status, { "content-type": "application/json", ...h }); res.end(JSON.stringify(obj)); };
  const html = (body, h = {}) => { res.writeHead(200, { "content-type": "text/html; charset=utf-8", ...h }); res.end(body); };
  const path = new URL(req.url, "http://x").pathname;
  const sidOf = () => (req.headers.cookie ?? "").match(/sid=([0-9a-f]+)/)?.[1];
  if (req.method === "GET" && path === "/") return html(PAGE(newChallenge(), sessions.get(sidOf())));
  if (req.method === "GET" && path === "/members") { const s = sessions.get(sidOf()); if (!s) return send(401, { error: "not_signed_in" }); return html(member(s)); }
  if (req.method === "GET" && path === "/bare") return html(BARE(newChallenge()));
  // A header CSP makes the browser blank a nonce attribute that came in the markup. Here to test that.
  if (req.method === "GET" && path === "/csp") return html(BARE(newChallenge()), { "content-security-policy": "default-src 'self'" });
  // no-store: a CDN in front would hold this script for hours past a redeploy. The ?v= only gets past copies already out there.
  if (req.method === "GET" && path === "/site.js") { res.writeHead(200, { "content-type": "text/javascript", "cache-control": "no-store" }); return res.end(JS); }
  if (req.method === "POST" && path === "/challenge") return send(200, { challenge: newChallenge() });
  if (req.method === "POST" && path === "/submit") {
    let body = "", big = false;
    req.on("data", (d) => { body += d; if (body.length > 400000) { big = true; req.destroy(); } });
    req.on("end", async () => {
      if (big) return;
      let r;
      try { r = await submit(body); } catch (e) { r = { accepted: false, reason: "bad_request", detail: String(e.message).slice(0, 200) }; }
      let h = {};
      if (r.accepted) { const sid = randomBytes(16).toString("hex"); sessions.set(sid, { name: r.name ?? null, address: r.address ?? null }); h["set-cookie"] = `sid=${sid}; HttpOnly; SameSite=Strict; Path=/`; }
      log({ op: "submit", accepted: r.accepted, reason: r.reason, ms: r.ms, verifyMs: r.verifyMs, name: r.name ?? null, kind: r.kind ?? null, tokenBytes: body.length });
      send(200, r, h);
    });
    return;
  }
  if (req.method === "GET" && path === "/me") return send(200, { loggedIn: sessions.has(sidOf()), name: sessions.get(sidOf())?.name ?? null });
  if (req.method === "POST" && path === "/logout") { sessions.delete(sidOf()); return send(200, {}, { "set-cookie": "sid=; Max-Age=0; Path=/" }); }
  send(404, { error: "not_found" });
}).listen(port, "127.0.0.1", () => log({ ready: true, origin, port, startMs: Math.round(performance.now() - t0), rssMB: Math.round(process.memoryUsage().rss / 1048576) }));
