#!/usr/bin/env python3
"""Test-key signer for anvil smoke runs (real phones sign on-device, the real server signs POP2).

  pub <key>                       -> 0x04||X||Y
  sigs --h H --safe S --chain C --owner-a ADDR --key-a K --owner-b ADDR --key-b K --issuer K [--expiry T]
                                  -> execTransaction.signatures: ownerSigs | POP2 tail | u32 len | "POPV"
Keys are ints (hex ok). Needs `cryptography` (uv run --with cryptography python3 script/pop_sigs.py ...).
"""
import argparse, hashlib, struct, sys, time
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed, decode_dss_signature

def key(k): return ec.derive_private_key(int(k, 0), ec.SECP256R1())
def pub65(k):
    n = key(k).public_key().public_numbers()
    return b"\x04" + n.x.to_bytes(32, "big") + n.y.to_bytes(32, "big")
def rs(der): r, s = decode_dss_signature(der); return r.to_bytes(32, "big") + s.to_bytes(32, "big")
def b32(h): return bytes.fromhex(h[2:] if h.startswith("0x") else h).rjust(32, b"\0")

def main():
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pub"); p.add_argument("k")
    s = sub.add_parser("sigs")
    for a in ("h", "safe", "chain", "owner-a", "key-a", "owner-b", "key-b", "issuer"): s.add_argument("--" + a, required=True)
    s.add_argument("--expiry", type=int, default=int(time.time()) + 900)
    s.add_argument("--pair-tag", default="0x" + "33" * 32)
    a = ap.parse_args()
    if a.cmd == "pub": print("0x" + pub65(a.k).hex()); return
    h = b32(a.h)
    # owner sigs: phone signs M = "pop-safe-owner-v1" || safeTxHash with SHA256withECDSA
    own = []
    for addr, k in ((a.owner_a, a.key_a), (a.owner_b, a.key_b)):
        own.append((int(addr, 16), rs(key(k).sign(b"pop-safe-owner-v1" + h, ec.ECDSA(hashes.SHA256())))))
    own.sort()
    static, dyn = b"", b""
    for addr, sig in own:
        static += addr.to_bytes(32, "big") + (130 + len(dyn)).to_bytes(32, "big") + b"\0"
        dyn += (64).to_bytes(32, "big") + sig
    # POP2 attestation (spec 01 §8.2), devX = sha256(pub65)
    devA, devB = hashlib.sha256(pub65(a.key_a)).digest(), hashlib.sha256(pub65(a.key_b)).digest()
    tag = b32(a.pair_tag); exp = struct.pack(">Q", a.expiry)
    pre = b"pop-safe-v2" + int(a.chain, 0).to_bytes(32, "big") + bytes.fromhex(a.safe[2:]) + h + tag + devA + devB + exp
    assert len(pre) == 199
    d = hashlib.sha256(pre).digest()
    tail = tag + devA + devB + exp + rs(key(a.issuer).sign(d, ec.ECDSA(Prehashed(hashes.SHA256())))) + b"POP2"
    assert len(tail) == 172
    print("0x" + (static + dyn + tail + struct.pack(">I", len(tail)) + b"POPV").hex())

if __name__ == "__main__":
    sys.exit(main())
