// Decode a Chrome-minted EVT~KB token, check both ES256 sigs, report header/claim bytes and high-s.
// node analyze.mjs token.txt issuer-jwk.json
import { readFileSync } from "node:fs";
import { webcrypto as C, createHash } from "node:crypto";
const tok = readFileSync(process.argv[2], "utf8").trim();
const ij = JSON.parse(readFileSync(process.argv[3], "utf8"));
const N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551n;
const [evt, kb] = tok.split("~");
const dec = (s) => Buffer.from(s, "base64url").toString("utf8");
const part = (jwt) => { const [h, p, s] = jwt.split("."); return { h, p, s, hj: dec(h), pj: dec(p), sig: Buffer.from(s, "base64url") }; };
const E = part(evt), K = part(kb);
const verify = async (jwk, x) => {
  const k = await C.subtle.importKey("jwk", { kty: "EC", crv: "P-256", x: jwk.x, y: jwk.y }, { name: "ECDSA", namedCurve: "P-256" }, false, ["verify"]);
  return C.subtle.verify({ name: "ECDSA", hash: "SHA-256" }, k, x.sig, Buffer.from(x.h + "." + x.p));
};
const hs = (x) => { const s = BigInt("0x" + x.sig.subarray(32).toString("hex")); return { sigLen: x.sig.length, highS: s > N / 2n }; };
const cnf = JSON.parse(E.pj).cnf.jwk;
const kp = JSON.parse(K.pj);
const out = {
  tokenBytes: tok.length,
  evtHeader: E.hj, evtPayload: E.pj, evtSig: { ...hs(E), ok: await verify(ij, E) },
  kbHeader: K.hj, kbPayload: K.pj, kbClaimOrder: Object.keys(kp), kbSig: { ...hs(K), okWithCnf: await verify(cnf, K) },
  sdHashOk: kp.sd_hash === createHash("sha256").update(evt + "~").digest("base64url"),
};
console.log(JSON.stringify(out, null, 1));
