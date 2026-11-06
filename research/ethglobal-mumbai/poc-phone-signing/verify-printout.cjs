// Nov 5 gate: paste the "Sign test digest" printout from a phone (or `adb logcat -s System.out` lines
// after "PopFrameKey:") into a file and run:  node verify-printout.cjs printout.txt
// Checks the EIP-8141 scheme-2 rules the sidecar applies (signature.ts, P256 branch), with the same noble
// library: 0<r<n, 0<s<=n/2, signer == keccak(qx||qy)[12:], p256.verify over the RAW digest (lowS:false,
// no prehash). Prints a scheme-2 entry JSON you can drop into a frame-tx envelope. No network.
const { createRequire } = require("module");
const fs = require("fs");
const req = createRequire(require("path").join(__dirname, "../../../relayer/package.json"));
const { p256 } = req("@noble/curves/p256");
const { keccak256, sha256 } = req("viem");

const txt = fs.readFileSync(process.argv[2] || 0, "utf8");
const get = (k) => (txt.match(new RegExp(`^\\s*(?:.*\\s)?${k} (\\S+)\\s*$`, "m")) || [])[1];
const [digest, rs, qxqy, claimed, level] = ["digest", "rs", "qxqy", "signer", "frame-key"].map(get);
if (!digest || !rs || !qxqy) { console.error("need digest, rs, qxqy lines"); process.exit(2); }
const b = (h) => Uint8Array.from(Buffer.from(h, "hex"));
const N = p256.CURVE.n;
const r = BigInt("0x" + rs.slice(0, 64)), s = BigInt("0x" + rs.slice(64, 128));
const signer = "0x" + keccak256("0x" + qxqy).slice(26);
const expectDigest = sha256(new TextEncoder().encode("pop-frame-test-v1")).slice(2);
const pub = b("04" + qxqy);
const res = {
  securityLevel: level,
  digestIsTestDigest: digest === expectDigest,
  lengths: rs.length === 128 && qxqy.length === 128 && digest.length === 64,
  rRange: r > 0n && r < N,
  lowS: s > 0n && s <= N / 2n,
  signerMatches: !claimed || claimed.toLowerCase() === signer,
  verifiesRawDigest: p256.verify({ r, s }, b(digest), pub, { lowS: false, prehash: false }),
  // if this is true and the line above false, the phone hashed again (message mode): the trap
  verifiesSha256OfDigest: p256.verify({ r, s }, b(digest), pub, { lowS: false, prehash: true }),
};
console.log(JSON.stringify(res, null, 2));
console.log("scheme-2 entry:", JSON.stringify({ scheme: "0x2", signer, msg: "0x" + digest, signature: "0x" + rs + qxqy }));
const pass = res.lengths && res.rRange && res.lowS && res.signerMatches && res.verifiesRawDigest;
console.log(pass ? "PASS: scheme-2 valid against the raw digest" : "FAIL");
process.exit(pass ? 0 : 1);
