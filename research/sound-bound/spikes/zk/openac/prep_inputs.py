"""Fixture -> circuit input JSON + expected public values, for the sound-bound OpenAC circuits.

Run with the enclave venv (needs `cryptography` only for re-issuing v2 credentials):
  ../enclave/.venv/bin/python prep_inputs.py <session8> [--variant pair_v1|pair_v2|half_v1|half_v2]
      [--role A|B] [--tamper NAME] [--out DIR]

v1 uses the fixture's own SBcred1 credentials (real issuer sig) and device sigs as they are.
v2 re-issues SBcred2 credentials (adds holder_commit) with the throwaway dev issuer key in
../enclave/keys/issuer_dev.pem. Device transcript sigs (Secure Enclave) are reused unchanged:
the transcript does not contain the credential.

Writes <out>/<name>.input.json (witness input) and <out>/<name>.public.json (what the verifier
expects, in circom public-signal order: outputs first, then public inputs in declaration order).
"""
import argparse
import hashlib
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ZK = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ZK, "enclave"))
from common import credential, transcript  # noqa: E402  (byte layouts, shared with the enclave track)

P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF   # P-256 base field = circuit field
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551   # P-256 order
C_HALF = 17150  # c/2 in cm/s (c = 34300 cm/s)
LO_CM, HI_CM = -20, 60
VALID_AT = 1790000000  # dev "now" for the expiry check (2026-09-22)
TAMPERS = ["none", "half", "swap", "nonce", "badsig", "issuer", "expired", "holder"]


def fe(x: int) -> str:
    return str(x % P)


def bounds(sr: int) -> tuple[int, int]:
    """Strict sample bounds: LO_CM < c/2*d/sr < HI_CM  <=>  dLo < d < dHi (d integer)."""
    lo = (LO_CM * sr) // C_HALF            # floor
    hi = -((-HI_CM * sr) // C_HALF)        # ceil
    return lo, hi


def holder_secret(fx: dict, role: str) -> bytes:
    """Throwaway dev holder secret (real app: random, kept on the phone, never sent to the issuer)."""
    return hashlib.sha256(b"SBholder-dev|" + fx["session_id"].encode() + role.encode()).digest()


def holder_commit(secret: bytes) -> bytes:
    return hashlib.sha256(b"SBhold1" + secret).digest()


def cred_v2(pub: bytes, expiry: int, commit: bytes) -> bytes:
    return b"SBcred2" + pub + struct.pack(">Q", expiry) + commit


def issue_v2(fx: dict) -> dict:
    """Re-issue SBcred2 credentials with the dev issuer key. Returns {role: (r, s)}."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import Prehashed, decode_dss_signature
    with open(os.path.join(ZK, "enclave", "keys", "issuer_dev.pem"), "rb") as f:
        sk = serialization.load_pem_private_key(f.read(), None)
    pn = sk.public_key().public_numbers()
    assert (f"{pn.x:064x}", f"{pn.y:064x}") == (fx["issuer"]["pub_x"], fx["issuer"]["pub_y"]), \
        "issuer_dev.pem does not match the fixture issuer"
    out = {}
    for role in "AB":
        rr = fx["roles"][role]
        pub = bytes.fromhex(rr["device_pub_x"] + rr["device_pub_y"])
        c = cred_v2(pub, rr["cred_expiry_unix"], holder_commit(holder_secret(fx, role)))
        sig = sk.sign(hashlib.sha256(c).digest(), ec.ECDSA(Prehashed(hashes.SHA256())))
        out[role] = decode_dss_signature(sig)
    return out


def role_fields(fx: dict, role: str, v2sigs=None) -> dict:
    rr = fx["roles"][role]
    pub = bytes.fromhex(rr["device_pub_x"] + rr["device_pub_y"])
    if v2sigs:
        cr, cs = v2sigs[role]
    else:
        cr, cs = int(rr["cred_sig_r_hex"], 16), int(rr["cred_sig_s_hex"], 16)
    return {
        "pub": list(pub),
        "half": list(struct.pack(">i", rr["half_samples"])),
        "rec": list(bytes.fromhex(rr["rec_hash_hex"])),
        "ts": [list(struct.pack(">Q", t)) for t in rr["os_ts"]],
        "r": int(rr["sig_r_hex"], 16),
        "s": int(rr["sig_s_hex"], 16),
        "exp": list(struct.pack(">Q", rr["cred_expiry_unix"])),
        "cr": cr,
        "cs": cs,
        "commit": list(holder_commit(holder_secret(fx, role))),
        "half_int": rr["half_samples"],
    }


def sinv(s: int) -> str:
    return str(pow(s % N, -1, N)) if s % N else "0"


def nullifier(secret: bytes, nonce: bytes) -> int:
    return int.from_bytes(hashlib.sha256(secret + nonce).digest()[:31], "big")


def build(fx: dict, variant: str, role: str = "A", tamper: str = "none"):
    v = 2 if variant.endswith("v2") else 1
    v2sigs = issue_v2(fx) if v == 2 else None
    nonce = bytes.fromhex(fx["nonce_hex"])
    sr = fx["sr"]
    F = {r: role_fields(fx, r, v2sigs) for r in "AB"}
    prover = role                       # whose holder secret / credential backs the nullifier
    secret = holder_secret(fx, prover)
    issuer = (int(fx["issuer"]["pub_x"], 16), int(fx["issuer"]["pub_y"], 16))
    valid_at = VALID_AT
    pub_nonce = nonce

    # --- tampering (prover-side inputs; expected public values stay the honest ones) ---
    if tamper == "half":        # B claims 30 samples (~10.7 cm) less flight without re-signing
        F["B"]["half"] = list(struct.pack(">i", F["B"]["half_int"] + 30))
    elif tamper == "swap":      # put A's signed half in the B slot and vice versa
        F["A"], F["B"] = F["B"], F["A"]
    elif tamper == "nonce":     # prove against another session's nonce
        pub_nonce = bytes(32 * [0x11])
    elif tamper == "badsig":    # flip one bit of A's device signature s
        F["A"]["s"] ^= 1
    elif tamper == "issuer":    # claim a different issuer key (A's device key)
        issuer = (int.from_bytes(bytes(F["A"]["pub"][:32]), "big"), int.from_bytes(bytes(F["A"]["pub"][32:]), "big"))
    elif tamper == "expired":   # verify at a time after the credential expiry
        valid_at = int.from_bytes(bytes(F["A"]["exp"]), "big") + 1
    elif tamper == "holder":    # nullifier from a secret not committed in the prover's credential
        secret = hashlib.sha256(b"not-my-secret").digest()
    elif tamper != "none":
        raise SystemExit(f"unknown tamper {tamper}")

    lo, hi = bounds(sr)
    common = {
        "nonceHi": str(int.from_bytes(pub_nonce[:16], "big")),
        "nonceLo": str(int.from_bytes(pub_nonce[16:], "big")),
        "attempt": str(fx["attempt"]),
        "issuerX": str(issuer[0]),
        "issuerY": str(issuer[1]),
        "sr": str(sr),
    }
    honest_nf = nullifier(holder_secret(fx, prover), nonce)
    honest_pub = [str(int.from_bytes(nonce[:16], "big")), str(int.from_bytes(nonce[16:], "big")),
                  str(fx["attempt"]), fe(int(fx["issuer"]["pub_x"], 16)), fe(int(fx["issuer"]["pub_y"], 16)), str(sr)]

    if variant.startswith("pair"):
        A, B = F["A"], F["B"]
        inp = dict(common)
        inp.update({
            "dLo": fe(lo), "dHi": fe(hi), "validAt": str(valid_at),
            "pubA": A["pub"], "pubB": B["pub"], "halfA": A["half"], "halfB": B["half"],
            "recA": A["rec"], "recB": B["rec"], "tsA": A["ts"], "tsB": B["ts"],
            "sigA_r": str(A["r"]), "sigA_sInv": sinv(A["s"]), "sigB_r": str(B["r"]), "sigB_sInv": sinv(B["s"]),
            "expA": A["exp"], "expB": B["exp"],
            "credA_r": str(A["cr"]), "credA_sInv": sinv(A["cs"]), "credB_r": str(B["cr"]), "credB_sInv": sinv(B["cs"]),
            "holderSecret": list(secret),
            "commitA": A["commit"] if v == 2 else [0] * 32,
            "commitB": B["commit"] if v == 2 else [0] * 32,
            "me": "0" if prover == "A" else "1",
        })
        expected = [fe(honest_nf)] + honest_pub + [fe(lo), fe(hi), str(VALID_AT)]
        d = fx["roles"]["A"]["half_samples"] - fx["roles"]["B"]["half_samples"]
        info = {"d_samples": d, "dLo": lo, "dHi": hi, "near_expected": lo < d < hi}
    else:
        own, par = F[role], F["B" if role == "A" else "A"]
        inp = dict(common)
        inp.update({
            "roleB": "1" if role == "B" else "0", "validAt": str(valid_at),
            "ownPub": own["pub"], "partnerPub": par["pub"], "halfBytes": own["half"], "rec": own["rec"],
            "ts": own["ts"], "sig_r": str(own["r"]), "sig_sInv": sinv(own["s"]), "exp": own["exp"],
            "cred_r": str(own["cr"]), "cred_sInv": sinv(own["cs"]),
            "holderSecret": list(secret), "commit": own["commit"] if v == 2 else [0] * 32,
        })
        expected = [fe(honest_nf), fe(fx["roles"][role]["half_samples"])] + honest_pub + \
                   ["1" if role == "B" else "0", str(VALID_AT)]
        info = {"half": fx["roles"][role]["half_samples"]}
    info.update({"session": fx["session_id"][:8], "label_cm": fx["label_cm"], "verdict": fx["verdict"],
                 "flight_cm": fx["flight_cm"], "variant": variant, "role": role, "tamper": tamper,
                 "key_kind": {r: fx["roles"][r]["key_kind"] for r in "AB"}})
    return inp, expected, info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--variant", default="pair_v1")
    ap.add_argument("--role", default="A")
    ap.add_argument("--tamper", default="none", choices=TAMPERS)
    ap.add_argument("--out", default=os.path.join(HERE, "inputs"))
    a = ap.parse_args()
    fx = json.load(open(os.path.join(ZK, "fixtures", a.session[:8] + ".json")))
    # sanity: our transcript rebuild matches what the device signed
    for r in "AB":
        rr, o = fx["roles"][r], fx["roles"]["B" if r == "A" else "A"]
        tr = transcript(bytes.fromhex(fx["nonce_hex"]), fx["attempt"], r,
                        bytes.fromhex(rr["device_pub_x"] + rr["device_pub_y"]),
                        bytes.fromhex(o["device_pub_x"] + o["device_pub_y"]), fx["sr"], rr["half_samples"],
                        bytes.fromhex(rr["rec_hash_hex"]), rr["os_ts"])
        assert tr.hex() == rr["transcript_hex"], "transcript layout mismatch"
        assert credential(bytes.fromhex(rr["device_pub_x"] + rr["device_pub_y"]),
                          rr["cred_expiry_unix"]).hex() == rr["cred_hex"]
    inp, expected, info = build(fx, a.variant, a.role, a.tamper)
    os.makedirs(a.out, exist_ok=True)
    name = f"{a.session[:8]}_{a.variant}" + (f"_{a.role}" if a.variant.startswith("half") else "") + \
           ("" if a.tamper == "none" else f"_t-{a.tamper}")
    json.dump(inp, open(os.path.join(a.out, name + ".input.json"), "w"))
    json.dump({"public": expected, "info": info}, open(os.path.join(a.out, name + ".public.json"), "w"), indent=1)
    print(name, json.dumps(info))


if __name__ == "__main__":
    main()
