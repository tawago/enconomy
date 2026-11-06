// What can a laptop browser key sign that an EIP-8141 native P256 entry (scheme 2) accepts?
// Node built-ins only (globalThis.crypto.subtle = the WebCrypto API, node:crypto for sha256).
// Own keccak256 and own P-256 verify (BigInt), so nothing third-party runs.
// Keys are fresh, in memory, thrown away at exit. Run: node sigcheck.mjs
import { createHash, randomBytes } from "node:crypto";
import { writeFileSync } from "node:fs";

const subtle = globalThis.crypto.subtle;
const hex = (b) => Buffer.from(b).toString("hex");
const h2b = (h) => Buffer.from(h.replace(/^0x/, ""), "hex");
const sha256 = (b) => createHash("sha256").update(b).digest();
const b64url = (b) => Buffer.from(b).toString("base64url");
let fails = 0;
const check = (name, got, want) => {
  const ok = got === want;
  if (!ok) fails++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : `  got=${got} want=${want}`}`);
};

// ---------------------------------------------------------------- keccak256 (Ethereum, pad 0x01)
const RC = [
  0x0000000000000001n, 0x0000000000008082n, 0x800000000000808an, 0x8000000080008000n, 0x000000000000808bn,
  0x0000000080000001n, 0x8000000080008081n, 0x8000000000008009n, 0x000000000000008an, 0x0000000000000088n,
  0x0000000080008009n, 0x000000008000000an, 0x000000008000808bn, 0x800000000000008bn, 0x8000000000008089n,
  0x8000000000008003n, 0x8000000000008002n, 0x8000000000000080n, 0x000000000000800an, 0x800000008000000an,
  0x8000000080008081n, 0x8000000000008080n, 0x0000000080000001n, 0x8000000080008008n,
];
const ROT = [0, 1, 62, 28, 27, 36, 44, 6, 55, 20, 3, 10, 43, 25, 39, 41, 45, 15, 21, 8, 18, 2, 61, 56, 14];
const M64 = (1n << 64n) - 1n;
const rotl = (x, n) => (n === 0 ? x : ((x << BigInt(n)) | (x >> BigInt(64 - n))) & M64);
function keccakF(s) {
  for (let r = 0; r < 24; r++) {
    const C = [0, 1, 2, 3, 4].map((x) => s[x] ^ s[x + 5] ^ s[x + 10] ^ s[x + 15] ^ s[x + 20]);
    for (let x = 0; x < 5; x++) {
      const d = C[(x + 4) % 5] ^ rotl(C[(x + 1) % 5], 1);
      for (let y = 0; y < 25; y += 5) s[x + y] ^= d;
    }
    const B = new Array(25);
    for (let x = 0; x < 5; x++) for (let y = 0; y < 5; y++) B[y + 5 * ((2 * x + 3 * y) % 5)] = rotl(s[x + 5 * y], ROT[x + 5 * y]);
    for (let x = 0; x < 5; x++) for (let y = 0; y < 5; y++) s[x + 5 * y] = B[x + 5 * y] ^ (~B[((x + 1) % 5) + 5 * y] & M64 & B[((x + 2) % 5) + 5 * y]);
    s[0] ^= RC[r];
  }
}
function keccak256(data) {
  const rate = 136;
  const msg = Buffer.from(data);
  const padLen = rate - (msg.length % rate);
  const p = Buffer.concat([msg, Buffer.alloc(padLen)]);
  p[msg.length] ^= 0x01;
  p[p.length - 1] ^= 0x80;
  const s = new Array(25).fill(0n);
  for (let off = 0; off < p.length; off += rate) {
    for (let i = 0; i < rate / 8; i++) s[i] ^= p.readBigUInt64LE(off + 8 * i);
    keccakF(s);
  }
  const out = Buffer.alloc(32);
  for (let i = 0; i < 4; i++) out.writeBigUInt64LE(s[i], 8 * i);
  return out;
}

// ---------------------------------------------------------------- abi words
const word = (v) => { const b = Buffer.alloc(32); let x = BigInt(v); for (let i = 31; i >= 0; i--) { b[i] = Number(x & 0xffn); x >>= 8n; } return b; };
const addrWord = (a) => Buffer.concat([Buffer.alloc(12), h2b(a)]);
const b32 = (h) => { const b = h2b(h); if (b.length !== 32) throw new Error("need 32 bytes"); return b; };
const sidWord = (h) => { const b = h2b(h); if (b.length !== 16) throw new Error("sid is 16 bytes"); return Buffer.concat([b, Buffer.alloc(16)]); };

// ---------------------------------------------------------------- PopCtx (docs/worldid/01 s5), reused as is
const POPCTX_DOMAIN = keccak256(Buffer.from("pop-ctx-v1"));
function popCtxNonce(chainId, consumer, ctxHash, notBefore, sid) {
  const pre = Buffer.concat([POPCTX_DOMAIN, word(chainId), addrWord(consumer), b32(ctxHash), word(notBefore), sidWord(sid)]);
  if (pre.length !== 192) throw new Error("PopCtx preimage must be 192 B");
  return keccak256(pre);
}

// ---------------------------------------------------------------- P-256 (verify + raw-digest sign)
const P = 0xffffffff00000001000000000000000000000000ffffffffffffffffffffffffn;
const A = P - 3n;
const N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551n;
const G = [0x6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296n, 0x4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5n];
const mod = (a, m) => ((a % m) + m) % m;
const inv = (a, m) => { let [r0, r1, s0, s1] = [mod(a, m), m, 1n, 0n]; while (r1) { const q = r0 / r1; [r0, r1] = [r1, r0 - q * r1]; [s0, s1] = [s1, s0 - q * s1]; } return mod(s0, m); };
function add(p1, p2) {
  if (!p1) return p2; if (!p2) return p1;
  if (p1[0] === p2[0] && mod(p1[1] + p2[1], P) === 0n) return null;
  const l = p1[0] === p2[0] && p1[1] === p2[1]
    ? mod((3n * p1[0] * p1[0] + A) * inv(2n * p1[1], P), P)
    : mod((p2[1] - p1[1]) * inv(p2[0] - p1[0], P), P);
  const x = mod(l * l - p1[0] - p2[0], P);
  return [x, mod(l * (p1[0] - x) - p1[1], P)];
}
function mul(k, pt) { let r = null; let q = pt; while (k > 0n) { if (k & 1n) r = add(r, q); q = add(q, q); k >>= 1n; } return r; }
const big = (b) => BigInt("0x" + hex(b));
// Scheme 2 as the sidecar checks it (signature.ts 58-79 per poc-phone-signing/README): no prehash, 0<r<n, 0<s<=n/2.
function scheme2Verify(msg32, r, s, Q) {
  if (!(r > 0n && r < N && s > 0n && s <= N / 2n)) return false;
  const e = big(msg32); const w = inv(s, N);
  const R = add(mul(mod(e * w, N), G), mul(mod(r * w, N), Q));
  return !!R && mod(R[0], N) === r;
}
function rawDigestSign(d, msg32) { // software key: what the PoP web build does with noble p256SignHash
  const e = big(msg32);
  for (;;) {
    const k = mod(big(randomBytes(32)), N); if (k === 0n) continue;
    const r = mod(mul(k, G)[0], N); if (r === 0n) continue;
    const s = mod(inv(k, N) * (e + r * d), N); if (s === 0n) continue;
    return { r, s };
  }
}
const lowS = (s) => (s > N / 2n ? N - s : s);
const signerOf = (Q) => "0x" + hex(keccak256(Buffer.concat([word(Q[0]), word(Q[1])])).subarray(12));

// ================================================================ 1. self-tests against pinned vectors
check("keccak256('')", hex(keccak256(Buffer.alloc(0))), "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470");
check("PopCtx DOMAIN", hex(POPCTX_DOMAIN), "2c71bde9118937099ebb172d5845794f571cc2982d44a563b229d1ea0db2af2f");
const ctxG = "0x" + Array.from({ length: 32 }, (_, i) => (0xa0 + i).toString(16)).join("");
check("PopCtx G nonce (docs/worldid/01 s5)",
  hex(popCtxNonce(480, "0x" + "5afe".repeat(10), ctxG, 1790000000, "00112233445566778899aabbccddeeff")),
  "2b9a8528bf222c8cf60dd97fb416183376bd4bc5425b29c02583518590ef75c9");

// ================================================================ 2. the rotation binding, one worked vector
const ROT_DOMAIN = keccak256(Buffer.from("enconomy/evp-rotate/v1"));
const GUARD_DOMAIN = keccak256(Buffer.from("enconomy/evp-rotate/guardian/v1"));
const fixed = {
  chainId: 1337,
  account: "0x" + "ac".repeat(20),
  newKey: "0x" + "ee".repeat(20),
  recoveryNonce: 7,
  deadline: 1793000900,
  notBefore: 1793000000,
  sid: "00112233445566778899aabbccddeeff",
  transcriptHash: "0x" + "77".repeat(32), // keccak(POPT_laptop || POPT_phone) in the real flow
};
const ctxHash = keccak256(Buffer.concat([ROT_DOMAIN, addrWord(fixed.newKey), word(fixed.recoveryNonce), word(fixed.deadline)]));
const sessionNonce = popCtxNonce(fixed.chainId, fixed.account, "0x" + hex(ctxHash), fixed.notBefore, fixed.sid);
const evpNonce = hex(sessionNonce); // the string put in <input autocomplete="email-verification-token" nonce=...>
const D = keccak256(Buffer.concat([GUARD_DOMAIN, word(fixed.chainId), addrWord(fixed.account), addrWord(fixed.newKey),
  word(fixed.recoveryNonce), sessionNonce, b32(fixed.transcriptHash), word(fixed.deadline)]));
console.log(`ctxHash      0x${hex(ctxHash)}\nsessionNonce 0x${hex(sessionNonce)}\nevpNonce     ${evpNonce}\nD (guardian) 0x${hex(D)}`);

// ================================================================ 3. WebCrypto non-extractable P-256
const kp = await subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, false, ["sign", "verify"]);
let exportErr = "none";
try { await subtle.exportKey("pkcs8", kp.privateKey); } catch (e) { exportErr = e.name; }
check("non-extractable private key refuses export", exportErr, "InvalidAccessError");
const pubRaw = Buffer.from(await subtle.exportKey("raw", kp.publicKey)); // 65 B, 04||x||y
const Qw = [big(pubRaw.subarray(1, 33)), big(pubRaw.subarray(33, 65))];
const sigW = Buffer.from(await subtle.sign({ name: "ECDSA", hash: "SHA-256" }, kp.privateKey, D)); // IEEE P1363 r||s
const rW = big(sigW.subarray(0, 32)); const sW = lowS(big(sigW.subarray(32)));
check("WebCrypto sig, scheme 2 with msg = D", scheme2Verify(D, rW, sW, Qw), false);
check("WebCrypto sig, scheme 2 with msg = sha256(D)", scheme2Verify(sha256(D), rW, sW, Qw), true);
const wasHigh = big(sigW.subarray(32)) > N / 2n;
console.log(`      (WebCrypto s was ${wasHigh ? "HIGH, normalized" : "low"}; anyone can normalize, the key is not needed)`);

// ================================================================ 4. software key, raw digest (PoP web build today)
const d = mod(big(randomBytes(32)), N - 1n) + 1n;
const Qs = mul(d, G);
const sigS = rawDigestSign(d, D);
check("software raw-digest sig, scheme 2 with msg = D", scheme2Verify(D, sigS.r, lowS(sigS.s), Qs), true);

// ================================================================ 5. WebAuthn-shaped assertion (simulated authenticator)
// Authenticator signs authenticatorData || sha256(clientDataJSON) with ES256 = ECDSA over sha256 of that.
const cdj = Buffer.from(JSON.stringify({ type: "webauthn.get", challenge: b64url(D), origin: "https://recover.example", crossOrigin: false }));
const authData = Buffer.concat([sha256(Buffer.from("recover.example")), Buffer.from([0x05]), Buffer.from([0, 0, 0, 1])]); // UP|UV, signCount 1
const signed = Buffer.concat([authData, sha256(cdj)]);
const sigA = Buffer.from(await subtle.sign({ name: "ECDSA", hash: "SHA-256" }, kp.privateKey, signed));
const rA = big(sigA.subarray(0, 32)); const sA = lowS(big(sigA.subarray(32)));
const mA = sha256(signed);
check("passkey-shaped sig, scheme 2 with msg = D", scheme2Verify(D, rA, sA, Qw), false);
check("passkey-shaped sig, scheme 2 with msg = sha256(authData||sha256(cdj))", scheme2Verify(mA, rA, sA, Qw), true);

const out = {
  note: "Public vectors only. Keys were in-memory test keys and are gone. Body-frame checks: m == sha256(D) (WebCrypto) or m == sha256(authData||sha256(cdj)) with cdj.challenge == b64url(D) (passkey).",
  inputs: fixed,
  ROT_DOMAIN: "0x" + hex(ROT_DOMAIN), GUARD_DOMAIN: "0x" + hex(GUARD_DOMAIN),
  ctxHash: "0x" + hex(ctxHash), sessionNonce: "0x" + hex(sessionNonce), evpNonce, D: "0x" + hex(D),
  webcrypto: { signer: signerOf(Qw), msg: "0x" + hex(sha256(D)), r: "0x" + rW.toString(16).padStart(64, "0"), s: "0x" + sW.toString(16).padStart(64, "0") },
  passkey: { clientDataJSON: cdj.toString(), authenticatorData: "0x" + hex(authData), msg: "0x" + hex(mA) },
};
writeFileSync(new URL("./vectors.json", import.meta.url), JSON.stringify(out, null, 2) + "\n");
console.log(fails ? `\n${fails} FAILED` : "\nall checks passed; vectors.json written");
process.exit(fails ? 1 : 0);
