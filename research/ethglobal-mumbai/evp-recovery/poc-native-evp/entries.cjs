// Step 1: carry the two ES256 JWS signatures of an EVP token as EIP-8141 scheme-2 entries with explicit msg.
// Checks every entry with a line-by-line port of the sidecar rule (signature.ts) AND frame-lib's p256Check.
// No network, no tx. Keys: fresh test keys from ./mint.mjs (keys/meta.json).
const { readFileSync } = require("fs");
const { createHash } = require("crypto");
const L = require("../../poc/clients/frame-lib.cjs");
const { p256, viem } = L;
const { keccak256, concat, toHex, pad, encodeFunctionData } = viem;

const meta = JSON.parse(readFileSync(__dirname + "/keys/meta.json", "utf8"));
const tok = meta.token;
const N = p256.CURVE.n, HALF = N / 2n;
const SECP256R1N = N;

// ---- port of sidecar packages/executor/src/services/FrameTxService/signature.ts (P256 + msg branch), sync ----
function sidecarValidateSignature(sig, txSender, sigHash) {
  let msg;
  if (sig.msg === "0x") msg = sigHash;
  else {
    const m = sig.msg.slice(2);
    if (m.length !== 64) return false;
    if (/^0{64}$/.test(m)) return false;
    msg = sig.msg;
  }
  let resolvedSigner;
  if (sig.signer === "0x") resolvedSigner = txSender;
  else if (sig.signer.length === 42) resolvedSigner = sig.signer;
  else return false;
  if (Number(sig.scheme) !== 2) throw new Error("port covers scheme 2 only");
  const bytes = sig.signature.slice(2);
  if (bytes.length !== 256) return false;
  const r = BigInt("0x" + bytes.slice(0, 64)), s = BigInt("0x" + bytes.slice(64, 128));
  const qx = "0x" + bytes.slice(128, 192), qy = "0x" + bytes.slice(192, 256);
  if (!(r > 0n && r < SECP256R1N) || !(s > 0n && s <= SECP256R1N / 2n)) return false;
  const expectedSigner = "0x" + keccak256("0x" + qx.slice(2) + qy.slice(2)).slice(26);
  if (expectedSigner.toLowerCase() !== resolvedSigner.toLowerCase()) return false;
  // noble 1.x verify(): msgHash is used as the hash (prehash defaults to false). Sidecar pins 1.8.1, ethrex calls
  // the P256VERIFY math with h = msg. So msg must be sha256(JWS signing input), exactly what ES256 signs.
  return p256.verify({ r, s }, msg.slice(2), "04" + qx.slice(2) + qy.slice(2), { lowS: false, prehash: false });
}

const sha = (s) => "0x" + createHash("sha256").update(s, "ascii").digest("hex");
const b64 = (s) => Buffer.from(s, "base64url");
const h32 = (b) => "0x" + Buffer.from(b).toString("hex").padStart(64, "0");

// ---- split the token ----
const d1 = tok.indexOf("."), d2 = tok.indexOf(".", d1 + 1), t = tok.indexOf("~");
const k1 = tok.indexOf(".", t + 1), k2 = tok.indexOf(".", k1 + 1);
const evtInput = tok.slice(0, d2), kbInput = tok.slice(t + 1, k2);
const evtSig = b64(tok.slice(d2 + 1, t)), kbSig = b64(tok.slice(k2 + 1));
const evtPayload = JSON.parse(b64(tok.slice(d1 + 1, d2)).toString());
const cnfX = h32(b64(evtPayload.cnf.jwk.x)), cnfY = h32(b64(evtPayload.cnf.jwk.y));
if (cnfX !== meta.browserX || cnfY !== meta.browserY) throw new Error("cnf mismatch");

// Build the entry. normalize=false keeps the JWS s as is (to show what the sidecar does with high-s).
function entry(sigBytes, qx, qy, input, { normalize = true, forceHigh = false } = {}) {
  const r = BigInt("0x" + sigBytes.subarray(0, 32).toString("hex"));
  let s = BigInt("0x" + sigBytes.subarray(32, 64).toString("hex"));
  const rawHigh = s > HALF;
  if (forceHigh && s <= HALF) s = N - s;
  if (normalize && s > HALF) s = N - s;
  return {
    rawHigh,
    e: { scheme: 2, signer: L.p256Address(qx, qy), msg: sha(input),
         signature: concat([pad(toHex(r), { size: 32 }), pad(toHex(s), { size: 32 }), qx, qy]) },
    plainEcdsa: p256.verify({ r, s }, sha(input).slice(2), "04" + qx.slice(2) + qy.slice(2), { lowS: false, prehash: false }),
  };
}

const out = [];
const log = (k, v) => { out.push([k, v]); console.log(k.padEnd(62), v); };
let fails = 0;
const expect = (k, got, want) => { log(k, got); if (got !== want) { fails++; console.log("   ^^ FAIL, want", want); } };

const SENDER = "0x00000000000000000000000000000000000ec0e1"; // placeholder account address
for (const [name, sig, qx, qy, input] of [
  ["EVT (issuer key)", evtSig, meta.issuerX, meta.issuerY, evtInput],
  ["KB-JWT (Chrome cnf key)", kbSig, cnfX, cnfY, kbInput],
]) {
  console.log(`\n== ${name}: signing input ${input.length} B, signer ${L.p256Address(qx, qy)}`);
  const raw = entry(sig, qx, qy, input, { normalize: false });
  log(`${name}: JWS s is high-s?`, raw.rawHigh);
  const hi = entry(sig, qx, qy, input, { normalize: false, forceHigh: true });
  expect(`${name}: high-s form, plain ECDSA (P256VERIFY math)`, hi.plainEcdsa, true);
  expect(`${name}: high-s form, sidecar port`, sidecarValidateSignature(hi.e, SENDER, L.ZERO32), false);
  expect(`${name}: high-s form, frame-lib p256Check`, L.p256Check(hi.e, SENDER, L.ZERO32), "range/high-s");
  const lo = entry(sig, qx, qy, input);
  expect(`${name}: normalized (n-s), plain ECDSA`, lo.plainEcdsa, true);
  expect(`${name}: normalized, sidecar port`, sidecarValidateSignature(lo.e, SENDER, L.ZERO32), true);
  expect(`${name}: normalized, frame-lib p256Check`, L.p256Check(lo.e, SENDER, L.ZERO32), "ok");
  // negatives
  const tam = { ...lo.e, msg: sha(input.slice(0, -1) + (input.endsWith("A") ? "B" : "A")) };
  expect(`${name}: msg = sha256(tampered input)`, sidecarValidateSignature(tam, SENDER, L.ZERO32), false);
  const pre = { ...lo.e, msg: sha(Buffer.from(sha(input).slice(2), "hex").toString("latin1")) };
  expect(`${name}: msg double-hashed (prehash mistake)`, sidecarValidateSignature(pre, SENDER, L.ZERO32), false);
  const wrongSigner = { ...lo.e, signer: L.p256Address(meta.ownerX, meta.ownerY) };
  expect(`${name}: signer != keccak(qx||qy)[12:]`, sidecarValidateSignature(wrongSigner, SENDER, L.ZERO32), false);
  if (name.startsWith("EVT")) globalThis.EVT = lo.e; else globalThis.KB = lo.e;
}
// The token string itself is untouched: the JWS still verifies off chain (Chrome, RP) with its original s.

// ---- full tx shape: [0] issuer explicit, [1] KB explicit, [2] new key over sig hash ----
const newKey = { priv: meta.ownerD, qx: meta.ownerX, qy: meta.ownerY, address: L.p256Address(meta.ownerX, meta.ownerY) };
const deadline = BigInt(meta.iat) + 600n;
const recoverData = encodeFunctionData({
  abi: [{ type: "function", name: "recover", inputs: [{ type: "bytes" }, { type: "uint256" }, { type: "bytes" }], outputs: [] }],
  functionName: "recover", args: [toHex(Buffer.from(tok, "ascii")), 0n, meta.newKey],
});
const tx = {
  chainId: 1337, nonceKeys: [0], nonceSeq: 0, sender: SENDER,
  frames: [
    { mode: L.MODE.VERIFY, flags: 0, target: L.EXPIRY_VERIFIER, limits: { execution: 4000, state: 0 }, value: 0, data: pad(toHex(deadline), { size: 8 }) },
    { mode: L.MODE.VERIFY, flags: 3, target: null, limits: { execution: 75900, state: 0 }, value: 0, data: recoverData },
    { mode: L.MODE.SENDER, flags: 0, target: SENDER, limits: { execution: 200000, state: 0 }, value: 0, data: "0x" },
  ],
  signatures: [], fees: { maxPriorityFeePerGas: 1, maxFeePerGas: 2e9, maxFeePerBlobGas: 0 },
};
const sh = L.signAll(tx, [
  { key: { address: EVT.signer }, msg: EVT.msg, signature: EVT.signature },
  { key: { address: KB.signer }, msg: KB.msg, signature: KB.signature },
  { key: newKey },
]);
console.log("\n== full tx, sig hash", sh);
tx.signatures.forEach((s, i) => {
  expect(`entry[${i}] sidecar port`, sidecarValidateSignature(s, SENDER, sh), true);
  expect(`entry[${i}] frame-lib checkEntry`, L.checkEntry(s, SENDER, sh), "ok");
});
const sigCost = tx.signatures.length * 6700;
const prefix = tx.frames.filter((f) => f.mode === L.MODE.VERIFY).reduce((a, f) => a + f.limits.execution, 0);
log("sidecar FRA-040 sum: prefix limits + 3 x 6,700", `${prefix} + ${sigCost} = ${prefix + sigCost} (cap 100000)`);
log("frame 1 data bytes (token + offs + newKey, ABI)", (recoverData.length - 2) / 2);
log("raw tx bytes", (L.rawTx(tx).length - 2) / 2);
console.log(fails ? `\n${fails} FAILED` : "\nall checks pass");
process.exit(fails ? 1 : 0);
