// Service worker: the only place that decides anything. Holds K through IndexedDB and takes the site's origin from the browser
// (port.sender.origin). It does not read an origin from any message, on purpose. No popup and no wallet here: a login that can go
// ahead just goes, and one that can't sends the user to enrollment once.
import { createSiweMessage } from "viem/siwe";
import { parseIdentifier, addressSlot, siweStatement } from "../../lib/identifier.mjs";

const enc = new TextEncoder();
const hex = (b) => [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, "0")).join("");
const sha256hex = async (s) => hex(await crypto.subtle.digest("SHA-256", enc.encode(s)));
const b64u = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const now_ = () => performance.now();
const ms = (t) => Math.round((now_() - t) * 10) / 10;
class Refuse extends Error { constructor(code, message) { super(message ?? code); this.code = code; } }

// Same rules as lib/wvp.mjs.
const bindNonce = (origin, challenge) => sha256hex(JSON.stringify([origin, challenge]));
const thumbprint = async (jwk) => b64u(await crypto.subtle.digest("SHA-256", enc.encode(JSON.stringify({ crv: jwk.crv, kty: jwk.kty, x: jwk.x, y: jwk.y }))));
const THUMB_URN = "urn:ietf:params:oauth:jwk-thumbprint:sha-256:", NAME_URN = "urn:wvp:ens:";

let cfgP;
const config = () => (cfgP ??= fetch(chrome.runtime.getURL("config.json")).then((r) => r.json()));

// K and the credentials. Extension origin only. K can sign but can't be exported.
const idb = () => new Promise((ok, no) => { const r = indexedDB.open("wvp-holder", 1); r.onupgradeneeded = () => r.result.createObjectStore("s"); r.onsuccess = () => ok(r.result); r.onerror = () => no(r.error); });
const tx = (db, mode, f) => new Promise((ok, no) => { const t = db.transaction("s", mode); const r = f(t.objectStore("s")); t.oncomplete = () => ok(r.result); t.onerror = () => no(t.error); });
const dbGet = async (k) => { const db = await idb(); const v = await tx(db, "readonly", (s) => s.get(k)); db.close(); return v; };
const dbPut = async (k, v) => { const db = await idb(); await tx(db, "readwrite", (s) => s.put(v, k)); db.close(); };
const dbDel = async (k) => { const db = await idb(); await tx(db, "readwrite", (s) => s.delete(k)); db.close(); };

// ---- prover, in the offscreen document ----
async function rpc(fn, arg) {
  const r = await chrome.runtime.sendMessage({ to: "offscreen", fn, arg });
  if (!r) throw new Error(`offscreen gave no answer to ${fn}`);
  if (r.err) throw new Error(r.err);
  return r.ok;
}
async function ensureProver() {
  const out = { createdOffscreen: false, bootedNow: false };
  const t = now_();
  if (!(await chrome.offscreen.hasDocument())) {
    await chrome.offscreen.createDocument({ url: "offscreen.html", reasons: ["WORKERS"], justification: "Runs the proof in Workers. Service workers can't start them." });
    out.createdOffscreen = true;
  }
  out.offscreenMs = ms(t);
  const st = await rpc("status");
  if (!st.booted) {
    const cfg = await config();
    out.boot = await rpc("boot", { assetBase: cfg.assetBase, threads: cfg.threads });
    out.bootedNow = true;
  }
  out.totalMs = ms(t);
  return out;
}

// ---- enrollment. Only the pinned issuer's page may start it. ----
async function enrollBegin(args, origin) {
  const cfg = await config();
  if (origin !== cfg.issuerOrigin) throw new Refuse("not_issuer", `enrollment is only for ${cfg.issuerOrigin}`);
  const { name, address } = args ?? {};
  if (typeof name !== "string" || typeof address !== "string") throw new Refuse("bad_request", "name and address are required");
  const id = parseIdentifier(name);
  if (id?.kind !== "name") throw new Refuse("bad_name", "that isn't an ENS name");
  const k = await crypto.subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, false, ["sign", "verify"]);
  const { kty, crv, x, y } = await crypto.subtle.exportKey("jwk", k.publicKey);
  const jwk = { kty, crv, x, y };
  const { nonce } = await (await fetch(`${cfg.issuerOrigin}/nonce`)).json();
  const thumb = await thumbprint(jwk);
  const nowSec = Math.floor(Date.now() / 1000);
  const issuedAt = new Date(nowSec * 1000), expirationTime = new Date((nowSec + 86400) * 1000);
  const { host } = new URL(cfg.issuerOrigin);
  const message = createSiweMessage({
    address, chainId: 1, domain: host, uri: `${cfg.issuerOrigin}/`, version: "1", nonce, issuedAt, expirationTime,
    statement: siweStatement(id.claim, address, thumb, expirationTime.toISOString()),
    resources: [NAME_URN + encodeURIComponent(id.claim), THUMB_URN + thumb],
  });
  await dbPut("pending", { k: k.privateKey, jwk, message, name: id.claim, address });
  return { message };
}

async function enrollFinish(args, origin) {
  const cfg = await config();
  if (origin !== cfg.issuerOrigin) throw new Refuse("not_issuer", `enrollment is only for ${cfg.issuerOrigin}`);
  const p = await dbGet("pending");
  if (!p) throw new Refuse("no_pending", "call enrollBegin first");
  const t0 = now_();
  const r = await fetch(`${cfg.issuerOrigin}/issue`, { method: "POST", body: JSON.stringify({ message: p.message, signature: args?.signature, deviceKey: p.jwk }) });
  const body = await r.json();
  if (r.status !== 200) throw new Refuse(body.error ?? "issuer_refused", body.why ?? "the issuer refused");
  const issueMs = ms(t0);
  const { keys: [issuerJwk] } = await (await fetch(`${cfg.issuerOrigin}/jwks`)).json();
  // New credentials replace the old ones and their state.
  if (await chrome.offscreen.hasDocument()) await chrome.offscreen.closeDocument();
  const prover = await ensureProver();
  const prepared = await rpc("prepare", { issuerJwk, creds: [{ id: "name", sdJwt: body.sdJwt, slot: p.name }, { id: "address", sdJwt: body.sdJwtAddress, slot: addressSlot(p.address) }] });
  await dbPut("holder", { K: p.k, jwk: p.jwk, exp: body.exp, name: p.name, address: p.address, issuerJwk });
  await dbDel("pending");
  const out = { name: p.name, exp: body.exp, issueMs, prover, prepare: prepared, totalMs: ms(t0) };
  await chrome.storage.session.set({ lastEnroll: out });
  return out;
}

// ---- going to enrollment, once, and coming back. In session storage: the worker can die while the user reads their wallet. ----
const getResume = async () => (await chrome.storage.session.get("resume")).resume ?? null;
const tabAlive = (id) => chrome.tabs.get(id).then(() => true, () => false);
async function sendToEnrollment(tabId, typedName) {
  const cfg = await config();
  const r = await getResume();
  if (r && await tabAlive(r.enrollTabId)) {
    // One enrollment tab, ever. The newest login is the one that resumes.
    await chrome.storage.session.set({ resume: { ...r, tabId } });
    await chrome.tabs.update(r.enrollTabId, { active: true });
    return;
  }
  // The site's origin stays out of this URL. A fragment doesn't reach the issuer's server.
  const url = `${cfg.issuerOrigin}/enroll${typedName ? `#name=${encodeURIComponent(typedName)}` : ""}`;
  const tab = await chrome.tabs.create({ url, active: true });
  await chrome.storage.session.set({ resume: { tabId, enrollTabId: tab.id } });
}
async function resumeAfterEnroll() {
  const r = await getResume();
  if (!r) return;
  await chrome.storage.session.remove("resume");
  await chrome.tabs.update(r.tabId, { active: true }).catch(() => {});
  await chrome.tabs.remove(r.enrollTabId).catch(() => {});
  resumeGrants.add(r.tabId);
  setTimeout(() => resumeGrants.delete(r.tabId), 5000); // Same life as a real gesture. Unused, it must not wait for a later page in this tab.
  await chrome.tabs.sendMessage(r.tabId, { to: "wvp-login", kind: "resume" }).catch(() => {});
}
chrome.tabs.onRemoved.addListener(async (closed) => {
  const r = await getResume();
  if (!r || (closed !== r.enrollTabId && closed !== r.tabId)) return;
  await chrome.storage.session.remove("resume");
  if (closed === r.enrollTabId) await chrome.tabs.sendMessage(r.tabId, { to: "wvp-login", kind: "enroll-closed" }).catch(() => {});
});

// ---- login ----
const bump = async (k) => { const { counts = { requests: 0, proofs: 0 } } = await chrome.storage.session.get("counts"); counts[k]++; await chrome.storage.session.set({ counts }); };
let busy = false;
// Fork only. chrome.wvpPrivate exists only for a component extension, so the same build still runs as a plain unpacked one.
const browserAsk = (tabId, fields) => new Promise((ok, no) => chrome.wvpPrivate.approve({ tabId, requireActivation: false, askUser: false, mode: "named", text: "", x: 0, y: 0, width: 0, height: 0, ...fields }, (a) => chrome.runtime.lastError ? no(new Error(chrome.runtime.lastError.message)) : ok(a)));
const resumeGrants = new Set(); // A login already gated before it went to enrollment. The user's gesture was in the other tab.
const num = (x) => Number.isFinite(x) ? x : 0;
async function prove(args, origin, tabId) {
  const tAll = now_();
  await bump("requests");
  const { mode, typed, nonce, rect } = args ?? {};
  if (mode !== "name" && mode !== "anon") throw new Refuse("bad_request", "mode");
  if (!/^[0-9a-f]{64}$/.test(nonce ?? "")) throw new Refuse("bad_nonce", "nonce must be 32 bytes of hex");
  const id = mode === "name" ? parseIdentifier(typed) : null;
  if (mode === "name" && !id) throw new Refuse("invalid", "not a name or address");
  if (chrome.wvpPrivate) {
    // The browser process decides: a real gesture in this tab's top frame, and whose origin that is.
    const resumed = resumeGrants.delete(tabId);
    const g = await browserAsk(tabId, { requireActivation: !resumed });
    if (!g.allowed) throw new Refuse(g.reason, "no real user gesture");
    if (g.origin !== origin) throw new Refuse("bad_origin", "the tab's origin isn't the sender's");
  }
  const h = await dbGet("holder");
  const now = Math.floor(Date.now() / 1000);
  if (!h || h.exp < now) {
    await sendToEnrollment(tabId, id?.kind === "name" ? id.claim : null);
    return { enroll: true };
  }
  if (id && id.claim !== h.name && id.claim !== h.address.toLowerCase()) throw new Refuse("no_match", "typed value isn't this credential's");
  if (busy) throw new Refuse("busy", "another proof is running");
  busy = true;
  try {
    if (chrome.wvpPrivate) {
      const a = await browserAsk(tabId, { askUser: true, mode: id ? "named" : "anonymous", text: id ? id.claim : "a valid credential, nothing else", x: num(rect?.x), y: num(rect?.y), width: num(rect?.width), height: num(rect?.height) });
      if (!a.allowed) throw new Refuse("user_denied", "you said no");
      if (a.origin !== origin) throw new Refuse("bad_origin", "the tab's origin isn't the sender's");
    }
    await bump("proofs");
    const tProve = now_();
    const prover = await ensureProver();
    const bound = await bindNonce(origin, nonce);
    const tSign = now_();
    const signature = b64u(await crypto.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, h.K, enc.encode(bound)));
    const signMs = ms(tSign);
    const cred = id?.kind === "address" ? "address" : "name";
    const s = await rpc("show", { nonce: bound, signature, now, cred, slot: id?.slot ?? null });
    const claim = id?.claim ?? null;
    const token = JSON.stringify({ v: 1, challenge: nonce, now, claim, bundle: s.bundle });
    await record(origin, claim, { cred, signMs, showWallMs: s.wallMs, proveTotalMs: ms(tProve), swTotalMs: ms(tAll), prover, restored: s.restored, swapped: s.swapped, stages: s.stages, sdk: s.timing, bundleBytes: s.bundleBytes, canonicalProblem: s.canonicalProblem, expressionResult: s.expressionResult, mem: s.mem });
    return { token, revealed: claim };
  } finally { busy = false; }
}
// A list the page can't touch, and a badge the page can't draw over.
async function record(origin, revealed, timing) {
  const { proofs = [] } = await chrome.storage.local.get("proofs");
  proofs.unshift({ t: Math.floor(Date.now() / 1000), origin, revealed });
  await chrome.storage.local.set({ proofs: proofs.slice(0, 20) });
  const { unseen = 0 } = await chrome.storage.session.get("unseen");
  await chrome.storage.session.set({ unseen: unseen + 1, lastTiming: { origin, revealed, ...timing } });
  await chrome.action.setBadgeBackgroundColor({ color: "#15803d" });
  await chrome.action.setBadgeText({ text: String(unseen + 1) });
}

// ---- action popup ----
async function revoke() {
  await dbDel("holder"); await dbDel("pending");
  if (await chrome.offscreen.hasDocument()) await chrome.offscreen.closeDocument();
  await new Promise((ok) => { const d = indexedDB.deleteDatabase("wvp-prover"); d.onsuccess = d.onerror = d.onblocked = () => ok(); });
  await chrome.storage.local.remove("proofs");
  await chrome.storage.session.set({ unseen: 0 });
  await chrome.action.setBadgeText({ text: "" });
}
chrome.runtime.onMessage.addListener((m, sender, reply) => {
  if (m.to !== "sw") return;
  // Only our own pages may ask. Content scripts carry the page's origin here, so they don't pass.
  if (sender.id !== chrome.runtime.id || sender.origin !== `chrome-extension://${chrome.runtime.id}`) { reply(null); return; }
  (async () => {
    if (m.kind === "popup-status") {
      const h = await dbGet("holder");
      const { proofs = [] } = await chrome.storage.local.get("proofs");
      await chrome.storage.session.set({ unseen: 0 });
      await chrome.action.setBadgeText({ text: "" });
      return h ? { enrolled: true, name: h.name, address: h.address, exp: h.exp, expired: h.exp < Date.now() / 1000, proofs } : { enrolled: false, proofs };
    }
    if (m.kind === "revoke") { await revoke(); return true; }
    return null;
  })().then(reply, () => reply(null));
  return true;
});

// Pages reach this only through a content script. There's no externally_connectable.
chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== "wvp") return;
  const { sender } = port;
  port.onMessage.addListener(async ({ method, args }) => {
    const answer = (m) => { try { port.postMessage(m); } catch {} };
    try {
      // The origin comes from the browser and nothing else. `args` can say whatever it likes.
      if (sender.id !== chrome.runtime.id || sender.frameId !== 0) throw new Refuse("bad_sender", "top frames only");
      const origin = sender.origin;
      if (!origin || origin === "null" || !/^https?:\/\//.test(origin)) throw new Refuse("bad_origin", `no usable origin: ${origin}`);
      if (method === "prove") return answer({ ok: await prove(args, origin, sender.tab?.id) });
      if (method === "enrollBegin") return answer({ ok: await enrollBegin(args, origin) });
      if (method === "enrollFinish") { answer({ ok: await enrollFinish(args, origin) }); return await resumeAfterEnroll(); }
      throw new Refuse("bad_method", method);
    } catch (e) { answer({ err: { code: e.code ?? "error", message: String(e.message ?? e).slice(0, 500) } }); }
  });
});

// Test harness reads these over CDP. Pages can't reach them. Only expireNow changes anything, and only the local copy of exp.
globalThis.__debug = {
  keyFacts: async () => {
    const h = await dbGet("holder");
    if (!h) return null;
    let exportErr = "EXPORT WORKED";
    try { await crypto.subtle.exportKey("jwk", h.K); } catch (e) { exportErr = `${e.name}: ${e.message}`; }
    return { extractable: h.K.extractable, type: h.K.type, usages: h.K.usages, exportErr, name: h.name, address: h.address, exp: h.exp, issuerX: h.issuerJwk.x, keyX: h.jwk.x };
  },
  counts: async () => (await chrome.storage.session.get("counts")).counts ?? { requests: 0, proofs: 0 },
  lastEnroll: async () => (await chrome.storage.session.get("lastEnroll")).lastEnroll ?? null,
  lastTiming: async () => (await chrome.storage.session.get("lastTiming")).lastTiming ?? null,
  proofLog: async () => (await chrome.storage.local.get("proofs")).proofs ?? [],
  badge: () => chrome.action.getBadgeText({}),
  resume: getResume,
  expireNow: async () => { const h = await dbGet("holder"); h.exp = Math.floor(Date.now() / 1000) - 3600; await dbPut("holder", h); return h.exp; },
  proverStatus: async () => (await chrome.offscreen.hasDocument()) ? rpc("status") : { offscreen: false },
  closeOffscreen: async () => { if (await chrome.offscreen.hasDocument()) await chrome.offscreen.closeDocument(); return true; },
  proverDb: async () => (await indexedDB.databases()).map((d) => d.name),
  hasWorker: () => typeof Worker,
  isolated: () => self.crossOriginIsolated,
};
