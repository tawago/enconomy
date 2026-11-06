// Mint EVP test tokens (EVT~KB-JWT, ES256) whose KB nonce is the DESIGN.md ctx, then write test/Fixture.sol.
// Node 24, stdlib only. keccak256 is implemented below (no cast, no npm) and checked against ../ctx-vector.json.
// Fresh test keys every run, written to keys/ (gitignored *.pem). Never real keys.
// Usage: node script/mint-fixtures.mjs
import { generateKeyPairSync, createHash, sign } from "node:crypto";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");

// ---------------- keccak256 (Keccak-f[1600], pad 0x01) ----------------
const RC = [
  0x0000000000000001n, 0x0000000000008082n, 0x800000000000808an, 0x8000000080008000n, 0x000000000000808bn,
  0x0000000080000001n, 0x8000000080008081n, 0x8000000000008009n, 0x000000000000008an, 0x0000000000000088n,
  0x0000000080008009n, 0x000000008000000an, 0x000000008000808bn, 0x800000000000008bn, 0x8000000000008089n,
  0x8000000000008003n, 0x8000000000008002n, 0x8000000000000080n, 0x000000000000800an, 0x800000008000000an,
  0x8000000080008081n, 0x8000000000008080n, 0x0000000080000001n, 0x8000000080008008n,
];
const ROT = [0, 1, 62, 28, 27, 36, 44, 6, 55, 20, 3, 10, 43, 25, 39, 41, 45, 15, 21, 8, 18, 2, 61, 56, 14];
const M = (1n << 64n) - 1n;
const rotl = (x, n) => (n === 0 ? x : ((x << BigInt(n)) | (x >> BigInt(64 - n))) & M);
function f1600(s) {
  for (let r = 0; r < 24; r++) {
    const c = [0, 1, 2, 3, 4].map((x) => s[x] ^ s[x + 5] ^ s[x + 10] ^ s[x + 15] ^ s[x + 20]);
    for (let x = 0; x < 5; x++) {
      const d = c[(x + 4) % 5] ^ rotl(c[(x + 1) % 5], 1);
      for (let y = 0; y < 25; y += 5) s[x + y] ^= d;
    }
    const b = new Array(25);
    for (let x = 0; x < 5; x++) for (let y = 0; y < 5; y++) b[y + 5 * ((2 * x + 3 * y) % 5)] = rotl(s[x + 5 * y], ROT[x + 5 * y]);
    for (let x = 0; x < 5; x++) for (let y = 0; y < 5; y++) s[x + 5 * y] = b[x + 5 * y] ^ (~b[((x + 1) % 5) + 5 * y] & M & b[((x + 2) % 5) + 5 * y]);
    s[0] ^= RC[r];
  }
}
function keccak256(bytes) {
  const rate = 136;
  const p = Buffer.alloc(Math.ceil((bytes.length + 1) / rate) * rate);
  Buffer.from(bytes).copy(p);
  p[bytes.length] ^= 0x01;
  p[p.length - 1] ^= 0x80;
  const s = new Array(25).fill(0n);
  for (let off = 0; off < p.length; off += rate) {
    for (let i = 0; i < rate / 8; i++) s[i] ^= p.readBigUInt64LE(off + 8 * i);
    f1600(s);
  }
  const out = Buffer.alloc(32);
  for (let i = 0; i < 4; i++) out.writeBigUInt64LE(s[i], 8 * i);
  return out;
}
const hx = (b) => "0x" + Buffer.from(b).toString("hex");
const word = (v) => Buffer.from(BigInt(v).toString(16).padStart(64, "0"), "hex");
const addrWord = (a) => Buffer.concat([Buffer.alloc(12), Buffer.from(a.slice(2), "hex")]);

// ---------------- ctx, exactly DESIGN.md section 3 ----------------
const DOMAIN = keccak256(Buffer.from("enconomy.EvpRecover.v1"));
// sessionTag: the bytes32 slot the vector file still calls transcriptHash.
function ctxOf({ chainId, account, newKey, recoveryNonce, transcriptHash: sessionTag, deadline }) {
  const pre = Buffer.concat([
    DOMAIN, word(chainId), addrWord(account), addrWord(newKey), word(recoveryNonce),
    Buffer.from(sessionTag.slice(2), "hex"), word(deadline),
  ]);
  return { pre, ctx: keccak256(pre) };
}

const vec = JSON.parse(readFileSync(join(root, "..", "ctx-vector.json"), "utf8"));
{
  const { pre, ctx } = ctxOf(vec.inputs);
  const want = (k, got, exp) => { if (got !== exp) throw new Error(`${k}: ${got} != ${exp}`); };
  want("DOMAIN", hx(DOMAIN), vec.DOMAIN);
  want("preimage", hx(pre), vec.preimage);
  want("ctx", hx(ctx), vec.ctx);
  want("audHash", hx(keccak256(Buffer.from(vec.audHash.origin))), vec.audHash.keccak);
  want("emailHash", hx(keccak256(Buffer.from(vec.emailHash.email))), vec.emailHash.keccak);
  want("keccak('')", hx(keccak256(Buffer.alloc(0))), "0xc5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470");
}

// ---------------- ES256 tokens ----------------
const N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551n;
const b64u = (buf) => Buffer.from(buf).toString("base64url");
const jwtPart = (obj) => b64u(Buffer.from(JSON.stringify(obj), "utf8"));
const newP256 = () => {
  const { privateKey, publicKey } = generateKeyPairSync("ec", { namedCurve: "P-256" });
  return { privateKey, jwk: publicKey.export({ format: "jwk" }) };
};
const es256 = (key, input) => sign("sha256", Buffer.from(input, "ascii"), { key, dsaEncoding: "ieee-p1363" });
const sOf = (sig) => BigInt(hx(sig.subarray(32)));
const withS = (sig, s) => Buffer.concat([sig.subarray(0, 32), word(s)]);
// force the signature's s into the high half (> n/2) or the low half
const forceS = (sig, high) => {
  const s = sOf(sig);
  const isHigh = s > N / 2n;
  return isHigh === high ? sig : withS(sig, N - s);
};
const jwkXY = (jwk) => [hx(Buffer.from(jwk.x, "base64url")), hx(Buffer.from(jwk.y, "base64url"))];

mkdirSync(join(root, "keys"), { recursive: true });
const keys = { issuer: newP256(), browser: newP256(), otherIssuer: newP256(), otherBrowser: newP256() };
for (const [n, k] of Object.entries(keys))
  writeFileSync(join(root, "keys", `${n}.pem`), k.privateKey.export({ format: "pem", type: "pkcs8" }));

const ISS = "https://evp.tawago.com";
const EMAIL = vec.emailHash.email; // alice@tawago.com
const AUD = vec.audHash.origin; // https://recover.tawago.com
const DEADLINE = vec.inputs.deadline; // 1793000900
const IAT = DEADLINE - 900; // the laptop sets deadline = mint time + 15 min

function mint(o = {}) {
  const issuer = o.issuer ?? keys.issuer;
  const email = o.email ?? EMAIL;
  const aud = o.aud ?? AUD;
  const nonce = o.nonce ?? vec.evpNonce;
  const iat = o.iat ?? IAT;
  const kbIat = o.kbIat ?? iat;
  // header and claim order like issuer-worker/worker.mjs
  const evtHeader = { alg: "ES256", typ: "evt+jwt", kid: "tawago-1" };
  const evtPayload = {
    iss: ISS, iat, exp: iat + 300,
    cnf: { jwk: { kty: "EC", crv: "P-256", x: keys.browser.jwk.x, y: keys.browser.jwk.y } },
    email, email_verified: true,
  };
  const evtInput = jwtPart(evtHeader) + "." + jwtPart(evtPayload);
  let isig = es256(issuer.privateKey, evtInput);
  if (o.issuerHighS !== undefined) isig = forceS(isig, o.issuerHighS);
  const it = evtInput + "." + b64u(isig) + "~";
  const kbH = { alg: "ES256", typ: "kb+jwt" };
  const kbP = { aud, nonce, iat: kbIat, sd_hash: b64u(createHash("sha256").update(it, "ascii").digest()) };
  const kbInput = jwtPart(kbH) + "." + jwtPart(kbP);
  let ksig = es256((o.kbKey ?? keys.browser).privateKey, kbInput);
  if (o.kbHighS !== undefined) ksig = forceS(ksig, o.kbHighS);
  const token = it + kbInput + "." + b64u(ksig);
  return { token, offs: offsets(token, email, o.hintAud ?? aud), kbS: sOf(ksig), issS: sOf(isig) };
}

// offs: 16 x uint16. Fields 0..14 as in the PoC verifier, field 15 = byte length of the aud string.
function offsets(token, email, aud) {
  const d1 = token.indexOf(".");
  const d2 = token.indexOf(".", d1 + 1);
  const t = token.indexOf("~");
  const k1 = token.indexOf(".", t + 1);
  const k2 = token.indexOf(".", k1 + 1);
  const ep = Buffer.from(token.slice(d1 + 1, d2), "base64url").toString("utf8");
  const kp = Buffer.from(token.slice(k1 + 1, k2), "base64url").toString("utf8");
  const at = (s, needle) => { const i = s.indexOf(needle); if (i < 0) throw new Error(needle); return i; };
  const f = [
    d1, d2, t, k1, k2,
    at(ep, '"email":"'), Buffer.byteLength(email), at(ep, '"email_verified":true'), at(ep, '"iat":'),
    at(ep, '"x":"'), at(ep, '"y":"'),
    at(kp, '"aud":"'), at(kp, '"nonce":"'), at(kp, '"iat":'), at(kp, '"sd_hash":"'),
    Buffer.byteLength(aud),
  ];
  f.forEach((v) => { if (v < 0 || v > 0xffff) throw new Error("offset range"); });
  return "0x" + f.reduce((acc, v, i) => acc | (BigInt(v) << BigInt(16 * i)), 0n).toString(16);
}

const nonceFor = (over) => hx(ctxOf({ ...vec.inputs, ...over }).ctx);
// A real P-256 new phone. 0xeeee.. in the vector has no (qx, qy), and VERIFY now checks keccak(qx||qy)[12:] == newKey.
const phone = newP256();
const [phoneX, phoneY] = jwkXY(phone.jwk);
const phoneAddr = "0x" + keccak256(Buffer.concat([Buffer.from(phoneX.slice(2), "hex"), Buffer.from(phoneY.slice(2), "hex")])).subarray(12).toString("hex");
const fx = {
  GOOD: mint({ kbHighS: false, issuerHighS: false }),
  WRONG_AUD: mint({ aud: "https://evil.example" }),
  // the honest origin is a prefix; the hint claims the honest length, the closing-quote check must catch it
  AUD_PREFIX: mint({ aud: AUD + ".evil.example", hintAud: AUD }),
  WRONG_NONCE: mint({ nonce: nonceFor({ newKey: "0xdddddddddddddddddddddddddddddddddddddddd" }) }),
  NONCE_PLAIN_KEY: mint({ nonce: "0x" + "ee".repeat(32) }), // not a ctx at all
  STALE: mint({ iat: IAT - 1000 }),
  FUTURE: mint({ iat: IAT + 200 }),
  OTHER_ISSUER: mint({ issuer: keys.otherIssuer }),
  OTHER_EMAIL: mint({ email: "bob@tawago.com" }),
  KB_OTHER_KEY: mint({ kbKey: keys.otherBrowser }),
  HIGH_S_KB: mint({ kbHighS: true, issuerHighS: false }),
  HIGH_S_ISSUER: mint({ kbHighS: false, issuerHighS: true }),
  NONCE9: mint({ nonce: nonceFor({ recoveryNonce: 9 }) }),
  GOOD_PHONE: mint({ nonce: nonceFor({ newKey: phoneAddr }), kbHighS: false, issuerHighS: false }),
  NONCE9_PHONE: mint({ nonce: nonceFor({ newKey: phoneAddr, recoveryNonce: 9 }) }),
};
if (fx.HIGH_S_KB.kbS <= N / 2n || fx.GOOD.kbS > N / 2n || fx.HIGH_S_ISSUER.issS <= N / 2n) throw new Error("high-s");

const [ix, iy] = jwkXY(keys.issuer.jwk);
const [ox, oy] = jwkXY(keys.otherIssuer.jwk);
const lines = Object.entries(fx).flatMap(([k, v]) => [
  `    bytes constant ${k} = "${v.token}";`,
  `    uint256 constant OFFS_${k} = ${v.offs};`,
]);
const sol = `// SPDX-License-Identifier: MIT
// GENERATED by script/mint-fixtures.mjs at ${new Date().toISOString()}. Fresh test keys only.
// Every token's KB nonce is evpNonce(ctx) from ../ctx-vector.json unless the name says otherwise.
// *_PHONE tokens: same inputs with newKey = keccak(PHONE_X||PHONE_Y)[12:].
pragma solidity ^0.8.28;

library Fixture {
${lines.join("\n")}
    uint256 constant ISSUER_X = ${ix};
    uint256 constant ISSUER_Y = ${iy};
    uint256 constant OTHER_ISSUER_X = ${ox};
    uint256 constant OTHER_ISSUER_Y = ${oy};
    uint256 constant PHONE_X = ${phoneX};
    uint256 constant PHONE_Y = ${phoneY};
    uint160 constant PHONE_ADDR = uint160(${BigInt(phoneAddr).toString()});
    bytes constant EMAIL = "${EMAIL}";
    bytes constant AUD = "${AUD}";
    uint256 constant IAT = ${IAT};
    uint256 constant DEADLINE = ${DEADLINE};
}
`;
writeFileSync(join(root, "test", "Fixture.sol"), sol);
writeFileSync(join(root, "results", "sample-token.txt"), fx.GOOD.token + "\n");
console.log(JSON.stringify({ ctx: vec.ctx, tokenBytes: fx.GOOD.token.length, fixtures: Object.keys(fx), checked: "keccak, DOMAIN, preimage, ctx, audHash, emailHash vs ctx-vector.json" }, null, 2));
