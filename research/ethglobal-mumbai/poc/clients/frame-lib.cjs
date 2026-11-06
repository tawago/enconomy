// Frame tx helpers for the chain-1337 "tracer" envelope (9 items). No network code here.
// Uses viem + @noble/curves 1.9 from ../../../../relayer/node_modules (nothing installed locally).
const { createRequire } = require("module");
const req = createRequire(require("path").join(__dirname, "../../../../relayer/package.json"));
const { toRlp, keccak256, toHex, hexToBigInt, concat, encodeAbiParameters, pad } = req("viem");
const { p256 } = req("@noble/curves/p256");
const { secp256k1 } = req("@noble/curves/secp256k1");

const N256 = p256.CURVE.n;
const ZERO32 = "0x" + "00".repeat(32);
const ENTRY_POINT = "0x00000000000000000000000000000000000000aa";
const EXPIRY_VERIFIER = "0x0000000000000000000000000000000000008141"; // EIP-8141 expiry predeploy (ethrex system_contracts.rs)
const MODE = { DEFAULT: 0, VERIFY: 1, SENDER: 2 };
const SCHEME = { ARBITRARY: 0, SECP256K1: 1, P256: 2 };

// RLP integer: 0 -> empty string, else minimal big-endian. Accepts bigint/number/hex.
function n(v) {
  if (v === undefined || v === null || v === "0x") return "0x";
  const b = typeof v === "bigint" ? v : typeof v === "number" ? BigInt(v) : hexToBigInt(v);
  return b === 0n ? "0x" : toHex(b);
}

// Internal tx shape = the sidecar wire shape (eth_sendFrameTransaction JSON):
// { chainId, nonceKeys[], nonceSeq, sender, frames[{mode,flags,target,limits{execution,state},value,data}],
//   signatures[{scheme,signer,msg,signature}], fees{maxPriorityFeePerGas,maxFeePerGas,maxFeePerBlobGas},
//   blobVersionedHashes[], recentRootReferences[{sourceId,slot,root}] }
function envelope(tx, elide) {
  return [
    n(tx.chainId),
    tx.nonceKeys.map(n),
    n(tx.nonceSeq),
    tx.sender,
    tx.frames.map((f) => [n(f.mode), n(f.flags), f.target ?? "0x", [n(f.limits.execution), n(f.limits.state)], n(f.value), f.data ?? "0x"]),
    tx.signatures.map((s) => [n(s.scheme), s.signer ?? "0x", s.msg ?? "0x", elide && (s.msg ?? "0x") === "0x" ? "0x" : s.signature ?? "0x"]),
    [n(tx.fees.maxPriorityFeePerGas), n(tx.fees.maxFeePerGas), n(tx.fees.maxFeePerBlobGas)],
    tx.blobVersionedHashes ?? [],
    (tx.recentRootReferences ?? []).map((r) => [n(r.sourceId), n(r.slot), r.root]),
  ];
}
const rawTx = (tx) => concat(["0x06", toRlp(envelope(tx, false))]);
const txHash = (tx) => keccak256(rawTx(tx));
// EIP-8141 sig hash: signature bytes elided only for entries whose msg is empty.
// Entries with an explicit msg stay in, so they must be final before signing the sig hash.
const sigHash = (tx) => keccak256(concat(["0x06", toRlp(envelope(tx, true))]));

// eth_getTransactionByHash JSON (ethrex) -> internal shape
function fromRpc(t) {
  return {
    chainId: t.chainId, nonceKeys: t.nonceKeys, nonceSeq: t.nonceSeq, sender: t.sender,
    frames: t.frames.map((f) => ({ mode: f.mode, flags: f.flags, target: f.to ?? null, limits: { execution: f.gasLimit, state: f.stateLimit }, value: f.value, data: f.data })),
    signatures: t.signatures.map((s) => ({ scheme: s.scheme, signer: s.signer ?? "0x", msg: s.msg ?? "0x", signature: s.signature })),
    fees: { maxPriorityFeePerGas: t.maxPriorityFeePerGas, maxFeePerGas: t.maxFeePerGas, maxFeePerBlobGas: t.maxFeePerBlobGas },
    blobVersionedHashes: t.blobVersionedHashes ?? [],
    recentRootReferences: t.recentRootReferences ?? [],
  };
}

// JSON for eth_sendFrameTransaction / eth_estimateFrameTransactionGas: hex everywhere, mode/flags numbers.
const hx = (v) => (typeof v === "string" ? v : toHex(BigInt(v)));
function toWire(tx) {
  return {
    chainId: hx(tx.chainId), nonceKeys: tx.nonceKeys.map(hx), nonceSeq: hx(tx.nonceSeq), sender: tx.sender,
    frames: tx.frames.map((f) => ({ mode: Number(f.mode), flags: Number(f.flags), target: f.target ?? null,
      limits: { execution: hx(f.limits.execution), state: hx(f.limits.state) }, value: hx(f.value ?? 0), data: f.data ?? "0x" })),
    signatures: tx.signatures.map((s) => ({ scheme: Number(s.scheme), signer: s.signer ?? "0x", msg: s.msg ?? "0x", signature: s.signature ?? "0x" })),
    fees: { maxPriorityFeePerGas: hx(tx.fees.maxPriorityFeePerGas), maxFeePerGas: hx(tx.fees.maxFeePerGas), maxFeePerBlobGas: hx(tx.fees.maxFeePerBlobGas) },
    blobVersionedHashes: tx.blobVersionedHashes ?? [],
    recentRootReferences: (tx.recentRootReferences ?? []).map((r) => ({ sourceId: r.sourceId, slot: hx(r.slot), root: r.root })),
  };
}

// ---- P-256 ----
// Deterministic TEST keys from a label. Never use for anything with value.
function testKey(label) {
  let d = hexToBigInt(keccak256(toHex("chirpgas-test-key:" + label))) % N256;
  if (d === 0n) d = 1n;
  const priv = pad(toHex(d), { size: 32 });
  const pub = p256.getPublicKey(priv.slice(2), false); // 65 bytes 04||x||y
  const qx = toHex(pub.slice(1, 33)), qy = toHex(pub.slice(33, 65));
  return { label, priv, qx, qy, address: p256Address(qx, qy) };
}
// EIP-8141: signer = keccak256(qx || qy)[12:]
const p256Address = (qx, qy) => "0x" + keccak256(concat([qx, qy])).slice(26);

// Sign a raw 32-byte digest (no prehash), force low-s, return 128-byte r||s||qx||qy.
function p256SignDigest(key, digest) {
  const sig = p256.sign(digest.slice(2), key.priv.slice(2), { lowS: true, prehash: false });
  let s = sig.s;
  if (s > N256 / 2n) s = N256 - s; // belt and braces; noble lowS already does this
  const r = pad(toHex(sig.r), { size: 32 }), ss = pad(toHex(s), { size: 32 });
  if (!p256.verify({ r: sig.r, s }, digest.slice(2), "04" + key.qx.slice(2) + key.qy.slice(2), { lowS: true, prehash: false }))
    throw new Error("self-verify failed");
  return concat([r, ss, key.qx, key.qy]);
}
// Same check the sidecar runs (signature.ts): length, range, low-s, signer binding, raw-digest verify.
function p256Check(entry, sender, sh) {
  const b = entry.signature.slice(2);
  if (b.length !== 256) return "bad length";
  const r = BigInt("0x" + b.slice(0, 64)), s = BigInt("0x" + b.slice(64, 128));
  const qx = "0x" + b.slice(128, 192), qy = "0x" + b.slice(192, 256);
  if (!(r > 0n && r < N256 && s > 0n && s <= N256 / 2n)) return "range/high-s";
  const signer = entry.signer === "0x" ? sender : entry.signer;
  if (p256Address(qx, qy).toLowerCase() !== signer.toLowerCase()) return "signer mismatch";
  const msg = entry.msg === "0x" ? sh : entry.msg;
  return p256.verify({ r, s }, msg.slice(2), "04" + qx.slice(2) + qy.slice(2), { lowS: false, prehash: false }) ? "ok" : "bad sig";
}

// ---- secp256k1 (scheme 1): the attester's co-sign entry (09-gap-fixes.md item 1) ----
// EIP-8141 layout (ethrex vm.rs validate_frame_signatures, sidecar signature.ts): 65 bytes v || r || s, v is the
// bare recovery id 0/1 (NOT 27/28), 0 < r < n, 0 < s <= n/2. Signer must be explicit or it resolves to tx.sender.
const NK1 = secp256k1.CURVE.n;
// Deterministic TEST key from a label. Never the relayer key (SECURITY-TODO F10), never anything with value.
function testSecpKey(label) {
  const priv = keccak256(toHex(label)); // GoldenVector.t.sol: uint256(keccak256("chirpgas-test-attester"))
  const pub = secp256k1.getPublicKey(priv.slice(2), false);
  return { label, priv, address: "0x" + keccak256(toHex(pub.slice(1))).slice(26) };
}
// Real attester key from a file (keeper/keys.mjs eoa attester -> keys/attester.key, one 0x hex line).
function secpKeyFromFile(path) {
  const priv = require("fs").readFileSync(path, "utf8").trim();
  if (!/^0x[0-9a-fA-F]{64}$/.test(priv)) throw new Error("attester key file: expected one 0x + 64 hex line");
  const pub = secp256k1.getPublicKey(priv.slice(2), false);
  return { label: path, priv, address: "0x" + keccak256(toHex(pub.slice(1))).slice(26) };
}
function secpSignDigest(key, digest) {
  const sig = secp256k1.sign(digest.slice(2), key.priv.slice(2), { lowS: true, prehash: false }); // RFC 6979
  if (sig.s > NK1 / 2n) throw new Error("high-s"); // noble lowS normalizes and flips recovery; belt and braces
  const out = concat([toHex(sig.recovery, { size: 1 }), pad(toHex(sig.r), { size: 32 }), pad(toHex(sig.s), { size: 32 })]);
  if (secpCheck({ signer: key.address, msg: digest, signature: out }, key.address, digest) !== "ok") throw new Error("self-verify failed");
  return out;
}
// Same check as the sidecar (signature.ts) and ethrex: length, v in {0,1}, range, low-s, recover == signer.
function secpCheck(entry, sender, sh) {
  const b = entry.signature.slice(2);
  if (b.length !== 130) return "bad length";
  const v = parseInt(b.slice(0, 2), 16), r = BigInt("0x" + b.slice(2, 66)), s = BigInt("0x" + b.slice(66, 130));
  if (v > 1 || !(r > 0n && r < NK1) || !(s > 0n && s <= NK1 / 2n)) return "v/range/high-s";
  const msg = entry.msg === "0x" ? sh : entry.msg;
  let rec;
  try { rec = new secp256k1.Signature(r, s).addRecoveryBit(v).recoverPublicKey(msg.slice(2)).toRawBytes(false); }
  catch { return "bad sig"; }
  const addr = "0x" + keccak256(toHex(rec.slice(1))).slice(26);
  const signer = entry.signer === "0x" ? sender : entry.signer;
  return addr.toLowerCase() === signer.toLowerCase() ? "ok" : "signer mismatch";
}
const checkEntry = (entry, sender, sh) =>
  Number(entry.scheme) === SCHEME.SECP256K1 ? secpCheck(entry, sender, sh) : p256Check(entry, sender, sh);

// ChirpGas partner digest. Must match ChirpGasSponsor.digest (poc-validation-rules/src/ChirpGasSponsor.sol):
// keccak(abi.encode(DOMAIN, chainid, sponsor, sender, seq, S, R, A_device, B_device, transcriptHash))
// sender + seq added 2026-11-02 (05-design-fixes F1): one partner signature = one sponsored tx for one account.
// Golden vector: poc-validation-rules/test/GoldenVector.t.sol, checked in build-frame-tx.cjs selftest.
const CHIRP_DOMAIN = keccak256(toHex("enconomy.ChirpGas.v1"));
function partnerDigest({ chainId, sponsor, sender, seq, slot, root, aDevice, bDevice, transcript, domain = CHIRP_DOMAIN }) {
  if (sender === undefined || seq === undefined) throw new Error("partnerDigest needs sender and seq");
  return keccak256(encodeAbiParameters(
    [{ type: "bytes32" }, { type: "uint256" }, { type: "address" }, { type: "address" }, { type: "uint256" }, { type: "uint256" },
     { type: "bytes32" }, { type: "address" }, { type: "address" }, { type: "bytes32" }],
    [domain, BigInt(chainId), sponsor, sender, BigInt(seq), BigInt(slot), root, aDevice, bDevice, transcript]));
}
const epochKey = (sponsor, epoch, domain = CHIRP_DOMAIN) =>
  keccak256(encodeAbiParameters([{ type: "bytes32" }, { type: "address" }, { type: "uint256" }], [domain, sponsor, BigInt(epoch)]));
// EIP-8250 TXPARAM 0x0F for one key: keccak(be32(1) || be32(key))
const keySetHash = (key) => keccak256(encodeAbiParameters([{ type: "uint256" }, { type: "uint256" }], [1n, BigInt(key)]));
// ChirpHumansRegistry.beaconValue: R = keccak(abi.encode(T, beaconSalt))
const beaconValue = (T, salt) => keccak256(encodeAbiParameters([{ type: "uint256" }, { type: "bytes32" }], [BigInt(T), salt]));
// ChirpGasSponsor.deadlineFor: the ONLY deadline frame 0 may carry (05-design-fixes S3)
function deadlineFor(T, window = 900n, epochSeconds = 86400n) {
  T = BigInt(T); const d = T + window, last = (T / epochSeconds + 1n) * epochSeconds - 1n;
  return d < last ? d : last;
}

// Fill signatures: explicit-msg entries first, then sig-hash entries (they commit to the former).
// plan entry: {key, msg?, scheme?}; scheme defaults to P256, SCHEME.SECP256K1 uses secpSignDigest (attester).
// A real flow gets the explicit entries from elsewhere (B's phone, the server): pass {signature} to use them as is.
function signAll(tx, plan /* [{key, msg, scheme, signature}] in entry order */) {
  const sign = (p, m) => (p.scheme ?? SCHEME.P256) === SCHEME.SECP256K1 ? secpSignDigest(p.key, m) : p256SignDigest(p.key, m);
  tx.signatures = plan.map((p) => ({ scheme: p.scheme ?? SCHEME.P256, signer: p.key.address, msg: p.msg ?? "0x", signature: "0x" }));
  plan.forEach((p, i) => { if ((p.msg ?? "0x") !== "0x") tx.signatures[i].signature = p.signature ?? sign(p, p.msg); });
  const sh = sigHash(tx);
  plan.forEach((p, i) => { if ((p.msg ?? "0x") === "0x") tx.signatures[i].signature = sign(p, sh); });
  if (sigHash(tx) !== sh) throw new Error("sig hash moved after signing");
  return sh;
}

async function rpc(url, method, params) {
  const r = await fetch(url, { method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }) });
  const text = await r.text();
  try { return JSON.parse(text); } catch { return { httpStatus: r.status, body: text.slice(0, 300) }; }
}

module.exports = { envelope, rawTx, txHash, sigHash, fromRpc, toWire, testKey, p256Address, p256SignDigest, p256Check,
  testSecpKey, secpKeyFromFile, secpSignDigest, secpCheck, checkEntry, NK1, secp256k1,
  partnerDigest, epochKey, keySetHash, beaconValue, deadlineFor, signAll, rpc, CHIRP_DOMAIN, EXPIRY_VERIFIER, MODE, SCHEME, ENTRY_POINT, ZERO32, N256, viem: req("viem"), p256 };
