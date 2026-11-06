// Runs in the prover Worker, inside the offscreen document. Holder side only:
// no verifying keys, no site check. Never sees K: signatures come in from the service worker.
// One Prepare state per credential, "name" and "address". A hidden proof always uses "name".
import { Prover, deserializePrecomputed } from "openac-sdk/src/prover.ts";
import { WasmBridge } from "openac-sdk/src/wasm-bridge.ts";
import builder from "openac-sdk/assets/witness_calculator.js";
import { loadFastProver } from "../../lib/openac-fast.mjs";
import { scrubBundle, canonicalProblem } from "../../lib/browser-bundle.mjs";
import { nameDigest } from "../../lib/name-digest.mjs";

const enc = new TextEncoder();
const hex = (b) => [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, "0")).join("");
const sha256hex = async (s) => hex(await crypto.subtle.digest("SHA-256", enc.encode(s)));
const b64 = (u8) => { let s = ""; for (let i = 0; i < u8.length; i += 32768) s += String.fromCharCode(...u8.subarray(i, i + 32768)); return btoa(s); };
const now_ = () => performance.now();
const ms = (t) => Math.round((now_() - t) * 10) / 10;

// Same digests the SDK pins in wasm-bridge.ts. The SDK's loader fetches all four keys, and a holder only needs these two.
const KEYS = {
  prepare: { file: "1k_prepare_proving.key", sha: "095f9c253274a831eb5d8225b6d7b855ab8471621968e773c041c83f32c46e8a" },
  show: { file: "1k_show_proving.key", sha: "809f24ca6ee003b684e2282b77f5a47279528edee7654a3801770a2ffca67831" },
};
const namedPolicy = async (name, now) => ({ all: [{ claim: "name", op: "==", value: await nameDigest(name) }, { claim: "exp", op: ">=", value: now }] });
const hiddenPolicy = (now) => ({ claim: "exp", op: ">=", value: now });
const splitSdJwt = (s) => { const [jwt, ...rest] = s.split("~"); return { jwt, disclosures: rest.filter(Boolean) }; };

class BrowserWitness {
  constructor(jwtBytes, showBytes) { this.src = { jwt_1k: jwtBytes, show: showBytes }; this.c = {}; }
  async get(n) { return (this.c[n] ??= await builder(this.src[n], { sanityCheck: true })); }
  async calculateJwtWitness(i, size) { return (await this.get(`jwt_${size}`)).calculateWitness(i, true); }
  async calculateShowWitness(i) { return (await this.get("show")).calculateWitness(i, true); }
  async calculateJwtWitnessWtns(i, size) { return (await this.get(`jwt_${size}`)).calculateWTNSBin(i, true); }
  async calculateShowWitnessWtns(i) { return (await this.get("show")).calculateWTNSBin(i, true); }
}

const S = {};
const mem = () => ({ wasmBytes: S.mod?.wasmMemoryBytes?.() ?? null });

async function localBytes(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return new Uint8Array(await r.arrayBuffer());
}
// Key from the Cache API, or from the key host on first use. Digest checked every time.
async function getKey(base, { file, sha }) {
  const t = now_();
  const url = `${base}/${file}`;
  const cache = await caches.open("wvp-keys-v1");
  let hit = await cache.match(url), from = "cache", downloadMs = 0;
  if (!hit) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`${url}: ${r.status}`);
    await cache.put(url, r);
    hit = await cache.match(url); from = "network"; downloadMs = ms(t);
  }
  const b = new Uint8Array(await hit.arrayBuffer());
  const t2 = now_();
  const d = hex(await crypto.subtle.digest("SHA-256", b));
  if (d !== sha) { await cache.delete(url); throw new Error(`key ${file} failed the digest check: ${d}`); }
  return { b, from, downloadMs, digestMs: ms(t2), totalMs: ms(t) };
}

export async function boot(cfg) {
  if (S.bootPromise) { await S.bootPromise; return { already: true, ...S.bootInfo }; }
  S.bootPromise = (async () => {
    S.cfg = cfg;
    const t0 = now_();
    const out = { isolated: self.crossOriginIsolated, origin: location.origin, inWorker: typeof document === "undefined" };
    const pw = await localBytes("/wasm/openac_plain2.wasm"), jw = await localBytes("/wasm/jwt_1k.wasm"), sw = await localBytes("/wasm/show.wasm");
    let t = now_();
    S.mod = await loadFastProver(pw, { threads: cfg.threads });
    out.poolSize = S.mod.poolSize; out.proverInstantiateMs = ms(t);
    S.bridge = new WasmBridge();
    S.bridge.initWithModule(S.mod);
    S.prover = new Prover(S.bridge, new BrowserWitness(jw, sw));
    t = now_();
    const pk = await getKey(cfg.assetBase, KEYS.prepare), spk = await getKey(cfg.assetBase, KEYS.show);
    out.keys = { prepare: { from: pk.from, bytes: pk.b.length, downloadMs: pk.downloadMs, digestMs: pk.digestMs, totalMs: pk.totalMs }, show: { from: spk.from, bytes: spk.b.length, downloadMs: spk.downloadMs, digestMs: spk.digestMs, totalMs: spk.totalMs } };
    out.keysTotalMs = ms(t);
    t = now_();
    const empty = new Uint8Array(0);
    out.keyDecode = S.mod.cacheKeys({ prepareProvingKey: pk.b, showProvingKey: spk.b, prepareVerifyingKey: empty, showVerifyingKey: empty });
    out.keyDecodeMs = ms(t);
    // The shim ignores key bytes once decoded, so the JS copies can go.
    S.keys = { prepareProvingKey: empty, showProvingKey: empty, prepareVerifyingKey: empty, showVerifyingKey: empty };
    out.totalMs = ms(t0); out.mem = mem();
    S.bootInfo = out;
  })();
  await S.bootPromise;
  return S.bootInfo;
}

const idb = () => new Promise((ok, no) => { const r = indexedDB.open("wvp-prover", 1); r.onupgradeneeded = () => r.result.createObjectStore("s"); r.onsuccess = () => ok(r.result); r.onerror = () => no(r.error); });
const tx = (db, mode, f) => new Promise((ok, no) => { const t = db.transaction("s", mode); const r = f(t.objectStore("s")); t.oncomplete = () => ok(r.result); t.onerror = () => no(t.error); });

const stateKey = (id) => `state:${id}`;

export async function prepare({ creds, issuerJwk }) {
  const t = now_();
  S.pres = {};
  const each = {};
  const db = await idb();
  for (const { id, sdJwt, slot } of creds) {
    const { jwt, disclosures } = splitSdJwt(sdJwt);
    const t1 = now_();
    const pre = await S.prover.precompute({ jwt, disclosures, issuerPublicKey: issuerJwk, keys: S.keys, predicates: await namedPolicy(slot, 0) });
    S.mod.setPrepareState(pre.prepareInstance, pre.prepareWitness);
    S.pres[id] = pre;
    const wallMs = ms(t1);
    const t2 = now_();
    const saved = pre.serialize();
    await tx(db, "readwrite", (s) => s.put({ saved }, stateKey(id)));
    each[id] = { wallMs, timing: pre.timing, stages: S.mod.timings?.(), savedBytes: saved.length, persistMs: ms(t2) };
  }
  db.close();
  return { wallMs: ms(t), each, mem: mem() };
}

async function stateFor(id) {
  if (S.pres?.[id]) return { pre: S.pres[id], restored: null };
  const t = now_();
  const db = await idb();
  const v = await tx(db, "readonly", (s) => s.get(stateKey(id)));
  db.close();
  if (!v) throw new Error(`no saved Prepare state for ${id}`);
  (S.pres ??= {})[id] = deserializePrecomputed(v.saved);
  return { pre: S.pres[id], restored: { totalMs: ms(t), savedBytes: v.saved.length } };
}

// slot null means a hidden proof. Otherwise it's the string behind the name slot's digest.
export async function show({ nonce, signature, now, cred, slot }) {
  const t = now_();
  const { pre, restored } = await stateFor(cred);
  const swapped = S.lastCred !== cred;
  S.lastCred = cred;
  const predicates = slot ? await namedPolicy(slot, now) : hiddenPolicy(now);
  const proof = await S.prover.present({ precomputed: pre, verifierNonce: nonce, keys: S.keys, predicates, deviceSignature: signature });
  const bundle = scrubBundle(proof.serialize());
  return { wallMs: ms(t), restored, swapped, stages: S.mod.timings?.(), timing: proof.timing, expressionResult: proof.publicValues.expressionResult, bundleBytes: bundle.length, canonicalProblem: canonicalProblem(bundle), mem: mem(), bundle: b64(bundle) };
}

export const status = () => ({ booted: !!S.bootInfo, states: Object.keys(S.pres ?? {}), isolated: self.crossOriginIsolated, mem: mem() });
