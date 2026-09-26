#!/usr/bin/env python3
"""Reviewer tool: synthetic SBv1 fixtures signed with THROWAWAY software keys
(fresh random each run, never saved), in the same JSON schema as ../fixtures,
so prep.py can consume them. Used to probe the threshold boundary, integer
extremes and same-device-both-roles, which real fixtures cannot reach.

usage: synth.py <out.json> <halfA> <halfB> [--same-key] [--sr N]   (sr > 0)
"""
import hashlib, json, secrets, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "enclave"))
from prep import N, GX, GY, _mul  # noqa: E402
from common import transcript, credential, low_s  # noqa: E402

def keygen():
    d = secrets.randbelow(N - 1) + 1
    return d, _mul(d, (GX, GY))

def sign(d, digest):
    e = int.from_bytes(digest, "big") % N
    while True:
        k = secrets.randbelow(N - 1) + 1
        r = _mul(k, (GX, GY))[0] % N
        s = pow(k, -1, N) * (e + r * d) % N
        if r and s:
            return low_s(r, s)[:2]

def main():
    out, hA, hB = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    same = "--same-key" in sys.argv
    sr = int(sys.argv[sys.argv.index("--sr") + 1]) if "--sr" in sys.argv else 48000
    isk, ipk = keygen()
    kA = keygen(); kB = kA if same else keygen()
    nonce = secrets.token_bytes(32)
    pub = lambda k: k[1][0].to_bytes(32, "big") + k[1][1].to_bytes(32, "big")
    roles = {}
    for R, k, o, h in (("A", kA, kB, hA), ("B", kB, kA, hB)):
        rec = secrets.token_bytes(32); ts = [1790355456394831872]; exp = 1792947425
        tr = transcript(nonce, 0, R, pub(k), pub(o), sr, h, rec, ts)
        cr = credential(pub(k), exp)
        r, s = sign(k[0], hashlib.sha256(tr).digest())
        cr_r, cr_s = sign(isk, hashlib.sha256(cr).digest())
        roles[R] = dict(device_pub_x="%064x" % k[1][0], device_pub_y="%064x" % k[1][1],
                        half_samples=h, rec_hash_hex=rec.hex(), os_ts=ts, transcript_hex=tr.hex(),
                        digest_hex=hashlib.sha256(tr).hexdigest(), sig_r_hex="%064x" % r,
                        sig_s_hex="%064x" % s, cred_hex=cr.hex(), cred_expiry_unix=exp,
                        cred_sig_r_hex="%064x" % cr_r, cred_sig_s_hex="%064x" % cr_s)
    fl = 34300 / 2 * (hA - hB) / sr
    d = dict(label_cm=-1, sr=sr, nonce_hex=nonce.hex(), attempt=0,
             issuer=dict(pub_x="%064x" % ipk[0], pub_y="%064x" % ipk[1]), roles=roles,
             flight_cm=fl, verdict="NEAR" if -20 < fl < 60 else "NOT_NEAR")
    Path(out).write_text(json.dumps(d, indent=1))
    print(f"synth {Path(out).stem}: d={hA-hB} flight={fl:.3f} cm verdict={d['verdict']} same_key={same}")

if __name__ == "__main__":
    main()
