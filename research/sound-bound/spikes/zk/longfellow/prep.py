#!/usr/bin/env python3
"""Fixture JSON -> witness/public text files for sbzk, plus tamper variants.

Usage: prep.py <fixture.json> <outdir> [--tamper KIND] [--prover A|B] [--now UNIX]

Writes <outdir>/witness.txt (all inputs, private and public) and <outdir>/public.txt
(public inputs only). Format: one "key hex" per line.

Before writing, it rebuilds both transcripts and credentials from the fields and checks
them byte-for-byte against transcript_hex / cred_hex, and checks all four ECDSA
signatures in pure Python (so a fixture problem is caught before the circuit).

Tamper kinds (private side, the prover must fail):
  half      A's half_samples + 1 (signature kept)
  role      swap all A and B role data
  nonce_w   witness uses a different nonce than the one the phones signed
  sig       flip one bit of A's device signature s
  credsig   flip one bit of B's issuer signature s
  expired   public now = cred expiry + 1
Informational (still a valid signature, expected to PROVE):
  highs     replace A's device sig s by n - s (ECDSA malleability)
Public-side tamper (verifier side) is done by pub_tamper.py on public.txt.
"""
import hashlib
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "enclave"))
from common import transcript, credential  # noqa: E402

P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
GX = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
GY = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5
A_ = P - 3


def _add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % P == 0:
        return None
    if p1 == p2:
        lam = (3 * x1 * x1 + A_) * pow(2 * y1, -1, P) % P
    else:
        lam = (y2 - y1) * pow(x2 - x1, -1, P) % P
    x3 = (lam * lam - x1 - x2) % P
    return x3, (lam * (x1 - x3) - y1) % P


def _mul(k, pt):
    r = None
    while k:
        if k & 1:
            r = _add(r, pt)
        pt = _add(pt, pt)
        k >>= 1
    return r


def ecdsa_ok(qx, qy, digest: bytes, r, s):
    if not (0 < r < N and 0 < s < N):
        return False
    e = int.from_bytes(digest, "big") % N
    w = pow(s, -1, N)
    pt = _add(_mul(e * w % N, (GX, GY)), _mul(r * w % N, (qx, qy)))
    return pt is not None and pt[0] % N == r


def h(x):
    return bytes.fromhex(x)


def main():
    args = sys.argv[1:]
    fx, outdir = Path(args[0]), Path(args[1])
    tamper = args[args.index("--tamper") + 1] if "--tamper" in args else None
    prover = args[args.index("--prover") + 1] if "--prover" in args else "A"
    now = int(args[args.index("--now") + 1]) if "--now" in args else 1790467200  # 2026-09-26
    d = json.loads(fx.read_text())
    nonce = h(d["nonce_hex"])
    attempt = d["attempt"]
    sr = d["sr"]
    ipk = (int(d["issuer"]["pub_x"], 16), int(d["issuer"]["pub_y"], 16))
    roles = {k: dict(v) for k, v in d["roles"].items()}

    # --- sanity: rebuild bytes and check signatures on the untampered fixture
    for R, other in (("A", "B"), ("B", "A")):
        r = roles[R]
        own = h(r["device_pub_x"] + r["device_pub_y"])
        par = h(roles[other]["device_pub_x"] + roles[other]["device_pub_y"])
        tr = transcript(nonce, attempt, R, own, par, sr, r["half_samples"], h(r["rec_hash_hex"]), r["os_ts"])
        assert tr.hex() == r["transcript_hex"], f"{R}: transcript rebuild mismatch"
        assert len(tr) == 215, len(tr)
        assert hashlib.sha256(tr).hexdigest() == r["digest_hex"]
        cred = credential(own, r["cred_expiry_unix"])
        assert cred.hex() == r["cred_hex"], f"{R}: cred rebuild mismatch"
        qx, qy = int(r["device_pub_x"], 16), int(r["device_pub_y"], 16)
        assert ecdsa_ok(qx, qy, hashlib.sha256(tr).digest(), int(r["sig_r_hex"], 16), int(r["sig_s_hex"], 16)), f"{R}: device sig bad"
        assert ecdsa_ok(*ipk, hashlib.sha256(cred).digest(), int(r["cred_sig_r_hex"], 16), int(r["cred_sig_s_hex"], 16)), f"{R}: cred sig bad"
    halfA, halfB = roles["A"]["half_samples"], roles["B"]["half_samples"]
    flight = 34300 / 2 * (halfA - halfB) / sr
    assert abs(flight - d["flight_cm"]) < 1e-9

    # --- tampering (private side)
    wnonce = nonce
    if tamper == "half":
        roles["A"]["half_samples"] += 1
    elif tamper == "role":
        roles["A"], roles["B"] = roles["B"], roles["A"]
    elif tamper == "nonce_w":
        wnonce = hashlib.sha256(b"other" + nonce).digest()
    elif tamper == "sig":
        roles["A"]["sig_s_hex"] = "%064x" % (int(roles["A"]["sig_s_hex"], 16) ^ 1)
    elif tamper == "credsig":
        roles["B"]["cred_sig_s_hex"] = "%064x" % (int(roles["B"]["cred_sig_s_hex"], 16) ^ 1)
    elif tamper == "highs":
        roles["A"]["sig_s_hex"] = "%064x" % (N - int(roles["A"]["sig_s_hex"], 16))
    elif tamper == "expired":
        now = roles["A"]["cred_expiry_unix"] + 1
    elif tamper is not None:
        sys.exit(f"unknown tamper {tamper}")

    # holder secret: throwaway dev value derived from the prover's device key.
    # (Real: a random software secret on the phone, see README gaps.)
    pr = roles[prover]
    holder = hashlib.sha256(b"SBholder-dev" + h(pr["device_pub_x"] + pr["device_pub_y"])).digest()
    nullifier = hashlib.sha256(holder + nonce).digest()

    lines = [
        ("issuer_x", "%064x" % ipk[0]), ("issuer_y", "%064x" % ipk[1]),
        ("nonce", wnonce.hex()), ("attempt", "%02x" % attempt),
        ("now", struct.pack(">Q", now).hex()), ("nullifier", nullifier.hex()),
        ("sr", struct.pack(">I", sr).hex()), ("holder", holder.hex()),
    ]
    for R in ("A", "B"):
        r = roles[R]
        lines += [
            (f"{R}.dpk", r["device_pub_x"] + r["device_pub_y"]),
            (f"{R}.half", struct.pack(">i", r["half_samples"]).hex()),
            (f"{R}.rec", r["rec_hash_hex"]),
            (f"{R}.ts", struct.pack(">Q", r["os_ts"][0]).hex()),
            (f"{R}.exp", struct.pack(">Q", r["cred_expiry_unix"]).hex()),
            (f"{R}.sig_r", r["sig_r_hex"]), (f"{R}.sig_s", r["sig_s_hex"]),
            (f"{R}.cred_r", r["cred_sig_r_hex"]), (f"{R}.cred_s", r["cred_sig_s_hex"]),
        ]
    assert all(len(roles[R]["os_ts"]) == 1 for R in "AB"), "circuit fixes n_ts = 1"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "witness.txt").write_text("".join(f"{k} {v}\n" for k, v in lines))
    pub = [(k, v) for k, v in lines if k in ("issuer_x", "issuer_y", "nonce", "attempt", "now", "nullifier")]
    # the verifier always holds the TRUE session nonce
    pub = [(k, nonce.hex() if k == "nonce" else v) for k, v in pub]
    (outdir / "public.txt").write_text("".join(f"{k} {v}\n" for k, v in pub))
    fl = 34300 / 2 * (roles["A"]["half_samples"] - roles["B"]["half_samples"]) / sr
    print(f"prep {fx.stem} label={d['label_cm']} flight={fl:.2f}cm verdict={d['verdict']} tamper={tamper} prover={prover}")


if __name__ == "__main__":
    main()
