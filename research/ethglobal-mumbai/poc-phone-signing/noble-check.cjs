// Cross-check the vectors the JVM test wrote, with the same library the sidecar uses for scheme 2
// (@noble/curves p256.verify, lowS:false, prehash off) plus viem keccak256 for the signer.
// Uses the noble/viem already installed in ../../../relayer (our repo). No network, no keys.
// Usage: node noble-check.cjs   (after ./jvm-test/gradlew test)
const { createRequire } = require("module");
const path = require("path");
const fs = require("fs");
const req = createRequire(path.join(__dirname, "../../../relayer/package.json"));
const { p256 } = req("@noble/curves/p256");
const { keccak256 } = req("viem");
const N = p256.CURVE.n;
const b = (h) => Uint8Array.from(Buffer.from(h, "hex"));
let ok = 0, fail = 0;
for (const f of ["jvm-vectors.json", "apple-vectors.json"]) {
  const p = path.join(__dirname, "vectors", f);
  if (!fs.existsSync(p)) { console.log("skip", f); continue; }
  for (const v of JSON.parse(fs.readFileSync(p, "utf8"))) {
    const sig = b(v.scheme2);
    const r = BigInt("0x" + v.scheme2.slice(0, 64)), s = BigInt("0x" + v.scheme2.slice(64, 128));
    const qxqy = v.scheme2.slice(128);
    const pub = b("04" + qxqy);
    const signer = "0x" + keccak256("0x" + qxqy).slice(26);
    const checks = {
      lowS: s <= N / 2n,
      signer: signer === v.signer.toLowerCase(),
      pubMatches: v.pub === "04" + qxqy,
      // sidecar call: raw 32-byte msg, no prehash, lowS:false
      sidecarVerify: p256.verify({ r, s }, b(v.digest), pub, { lowS: false, prehash: false }),
      strictLowS: p256.verify({ r, s }, b(v.digest), pub, { lowS: true, prehash: false }),
      // raw (maybe high-s) sig is valid ECDSA but would fail lowS:true
      rawValidEcdsa: p256.verify(b(v.rsRaw), b(v.digest), pub, { lowS: false, prehash: false }),
      rawStrict: p256.verify(b(v.rsRaw), b(v.digest), pub, { lowS: true, prehash: false }) === !v.wasHighS,
      // and NOT valid if a verifier hashes the digest again (message mode)
      notPrehashed: !p256.verify({ r, s }, b(v.digest), pub, { lowS: false, prehash: true }),
    };
    const bad = Object.entries(checks).filter(([, x]) => !x).map(([k]) => k);
    if (bad.length) { fail++; console.log("FAIL", v.src, v.digest.slice(0, 16), bad.join(",")); } else ok++;
  }
}
console.log(`noble ${JSON.parse(fs.readFileSync(path.join(__dirname, "../../../relayer/node_modules/@noble/curves/package.json"))).version}: ${ok} ok, ${fail} fail`);
process.exit(fail ? 1 : 0);
