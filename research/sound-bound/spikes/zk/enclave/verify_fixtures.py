"""Independently verify every fixture (OpenSSL via `cryptography`, no CryptoKit), plus tamper tests.

Usage: .venv/bin/python verify_fixtures.py
"""
import glob
import hashlib
import json
import os
import struct
import sys

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed, encode_dss_signature

from common import P256_N, credential, flight_cm, transcript, verdict

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")


def pub(x: str, y: str) -> ec.EllipticCurvePublicKey:
    return ec.EllipticCurvePublicNumbers(int(x, 16), int(y, 16), ec.SECP256R1()).public_key()


def ok_digest(pk, digest: bytes, r: int, s: int) -> bool:
    """ECDSA P-256 over a 32-byte digest (what a circuit would check)."""
    try:
        pk.verify(encode_dss_signature(r, s), digest, ec.ECDSA(Prehashed(hashes.SHA256())))
        return True
    except InvalidSignature:
        return False


def check_role(fx: dict, role: str) -> list[str]:
    e = []
    rr = fx["roles"][role]
    other = fx["roles"]["B" if role == "A" else "A"]
    own = bytes.fromhex(rr["device_pub_x"] + rr["device_pub_y"])
    par = bytes.fromhex(other["device_pub_x"] + other["device_pub_y"])
    tr = transcript(bytes.fromhex(fx["nonce_hex"]), fx["attempt"], role, own, par, fx["sr"],
                    rr["half_samples"], bytes.fromhex(rr["rec_hash_hex"]), rr["os_ts"])
    if tr.hex() != rr["transcript_hex"]:
        e.append("transcript bytes != rebuilt from fields")
    d = hashlib.sha256(bytes.fromhex(rr["transcript_hex"])).digest()
    if d.hex() != rr["digest_hex"]:
        e.append("digest != sha256(transcript)")
    r, s = int(rr["sig_r_hex"], 16), int(rr["sig_s_hex"], 16)
    if not s <= P256_N // 2:
        e.append("sig not low-S")
    if not ok_digest(pub(rr["device_pub_x"], rr["device_pub_y"]), d, r, s):
        e.append("device sig invalid")
    cred = credential(own, rr["cred_expiry_unix"])
    if cred.hex() != rr["cred_hex"]:
        e.append("cred bytes != rebuilt")
    cd = hashlib.sha256(cred).digest()
    if cd.hex() != rr["cred_digest_hex"]:
        e.append("cred digest mismatch")
    cr, cs = int(rr["cred_sig_r_hex"], 16), int(rr["cred_sig_s_hex"], 16)
    if not cs <= P256_N // 2:
        e.append("cred sig not low-S")
    if not ok_digest(pub(fx["issuer"]["pub_x"], fx["issuer"]["pub_y"]), cd, cr, cs):
        e.append("issuer sig invalid")
    return e


def check(fx: dict) -> list[str]:
    e = check_role(fx, "A") + check_role(fx, "B")
    # Combiner rules (decision doc sec 3): same nonce/attempt/pair, one A one B, flight in window.
    ta, tb = (bytes.fromhex(fx["roles"][r]["transcript_hex"]) for r in "AB")
    if ta[4:37] != tb[4:37]:
        e.append("nonce/attempt differ")
    if (ta[37], tb[37]) != (0x41, 0x42):
        e.append("roles not A,B")
    if ta[38:102] != tb[102:166] or ta[102:166] != tb[38:102]:
        e.append("key pair not crossed")
    ha = struct.unpack(">i", ta[170:174])[0]
    hb = struct.unpack(">i", tb[170:174])[0]
    fl = flight_cm(ha, hb, fx["sr"])
    if abs(fl - fx["flight_cm"]) > 1e-9 or verdict(fl) != fx["verdict"]:
        e.append("flight/verdict mismatch")
    return e


def tamper_tests(fx: dict) -> dict:
    """Each tamper must be rejected by check()."""
    res = {}

    def run(name, mut):
        f = json.loads(json.dumps(fx))
        mut(f)
        res[name] = bool(check(f))

    def half(f):  # bump B's half by 30 samples (~10 cm) without re-signing
        rb = f["roles"]["B"]
        rb["half_samples"] += 30
        rb["transcript_hex"] = transcript_from(f, "B").hex()
        rb["digest_hex"] = hashlib.sha256(bytes.fromhex(rb["transcript_hex"])).hexdigest()
    run("half+30", half)
    run("swap roles", lambda f: f["roles"].update(A=f["roles"]["B"], B=f["roles"]["A"]))
    run("sig bit flip", lambda f: f["roles"]["A"].update(
        sig_s_hex=f"{int(f['roles']['A']['sig_s_hex'], 16) ^ 1:064x}"))
    run("high-S", lambda f: f["roles"]["A"].update(
        sig_s_hex=f"{P256_N - int(f['roles']['A']['sig_s_hex'], 16):064x}"))
    run("other issuer", lambda f: f["issuer"].update(pub_x=f["roles"]["A"]["device_pub_x"],
                                                      pub_y=f["roles"]["A"]["device_pub_y"]))
    run("nonce change", lambda f: f.update(nonce_hex="00" * 32))
    return res


def transcript_from(f, role):
    rr = f["roles"][role]
    o = f["roles"]["B" if role == "A" else "A"]
    return transcript(bytes.fromhex(f["nonce_hex"]), f["attempt"], role,
                      bytes.fromhex(rr["device_pub_x"] + rr["device_pub_y"]),
                      bytes.fromhex(o["device_pub_x"] + o["device_pub_y"]),
                      f["sr"], rr["half_samples"], bytes.fromhex(rr["rec_hash_hex"]), rr["os_ts"])


def main():
    files = sorted(glob.glob(os.path.join(OUT, "*.json")))
    bad = 0
    tam_fail = 0
    counts = {}
    for p in files:
        fx = json.load(open(p))
        e = check(fx)
        t = tamper_tests(fx)
        missed = [k for k, v in t.items() if not v]
        bad += bool(e)
        tam_fail += bool(missed)
        key = (fx["label_cm"], fx["verdict"])
        counts[key] = counts.get(key, 0) + 1
        print(f"{os.path.basename(p)[:8]} {fx['roles']['A']['key_kind']:15} label {fx['label_cm']:5.0f} "
              f"flight {fx['flight_cm']:8.3f} {fx['verdict']:8} {'OK' if not e else 'FAIL ' + ';'.join(e)} "
              f"tamper-rejected {sum(t.values())}/{len(t)}{' MISSED ' + ','.join(missed) if missed else ''}")
    print(f"fixtures {len(files)}  valid {len(files) - bad}  tamper-all-rejected {len(files) - tam_fail}")
    print("label -> verdict:", {f"{k[0]:.0f}cm {k[1]}": v for k, v in sorted(counts.items())})
    sys.exit(1 if bad or tam_fail else 0)


if __name__ == "__main__":
    main()
