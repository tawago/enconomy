"""SBcred3 issuer: binds an enrolled device key to an expiry and a holder commitment for the option A prover.

cred = "SBcred3" || X || Y || expiry u64 BE (unix s) || holder_commit 32 BE    (111 bytes)
sig  = ECDSA P-256 over SHA-256(cred), raw r||s. Layout = research/sound-bound/spikes/zk/optionA-v2
(build_fixtures_popt2.cred3, circuit gen_popt2.py Sha256(8*111)). The circuit checks the signature against the
public issuerX/issuerY and validAt <= expiry; it never opens holder_commit (only the _nf variant does).

Code attestation (Noir option A: the templates are private, the proof only exposes their Poseidon2 code_commit, so
the issuer vouches that code_commit is the codes this server sent for that session, attempt and role):
  msg = "POPCC1" || session_nonce 32 || attempt u8 || role 'A'|'B' || code_commit 32 BE     (72 bytes)
  sig = ECDSA P-256 over SHA-256(msg) by the issuer key, raw r||s, low-S.

Key: POP_ISSUER_KEY (PEM, or 64 hex = private scalar) wins over POP_ISSUER_KEY_FILE (default data/issuer.pem,
created 0600 on first run unless POP_ISSUER_AUTOGEN=0). data/ and *.pem are gitignored.
"""
from __future__ import annotations

import os
import re
import struct
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from pop.crypto import pub_bytes, sign_raw, verify_raw

MAGIC = b"SBcred3"
CRED_LEN = 111
P256_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
CRED_TTL_S = 30 * 86400
CODE_ATTEST_MAGIC = b"POPCC1"


def code_attest_msg(nonce: bytes, attempt: int, role: str, code_commit: bytes) -> bytes:
    if len(nonce) != 32 or len(code_commit) != 32 or role not in ("A", "B") or not 0 <= attempt < 256:
        raise ValueError("bad code attestation fields")
    return CODE_ATTEST_MAGIC + nonce + bytes([attempt]) + role.encode() + code_commit
_HEX64 = re.compile(r"^(0x)?[0-9a-fA-F]{64}$")


class CredError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def parse_holder_commit(v) -> bytes:
    """64 hex (optional 0x), a canonical field element < p. -> 32 bytes BE."""
    if not isinstance(v, str) or not _HEX64.match(v.strip()):
        raise CredError("bad_holder_commit", "holder_commit must be 64 hex chars")
    b = bytes.fromhex(v.strip()[-64:])
    if int.from_bytes(b, "big") >= P256_P:
        raise CredError("bad_holder_commit", "holder_commit must be < p (P-256 base field)")
    return b


def build(pub65: bytes, expiry_s: int, holder_commit: bytes) -> bytes:
    if len(pub65) != 65 or pub65[0] != 4:
        raise ValueError("pub must be 65-byte SEC1 uncompressed")
    if len(holder_commit) != 32:
        raise ValueError("holder_commit must be 32 bytes")
    return MAGIC + pub65[1:] + struct.pack(">Q", expiry_s) + holder_commit


def parse(cred: bytes) -> dict:
    if len(cred) != CRED_LEN or cred[:7] != MAGIC:
        raise CredError("bad_credential", "not an SBcred3")
    return {"pub": b"\x04" + cred[7:71], "expiry": struct.unpack(">Q", cred[71:79])[0],
            "holder_commit": cred[79:111]}


def check(cred: bytes, sig64: bytes, issuer_pub65: bytes, valid_at: int) -> dict:
    """What the circuit enforces on the credential: issuer signature, validAt <= expiry."""
    c = parse(cred)
    if not verify_raw(issuer_pub65, cred, sig64):
        raise CredError("issuer_unknown", "credential not signed by this issuer")
    if valid_at > c["expiry"]:
        raise CredError("credential_expired", f"validAt {valid_at} > expiry {c['expiry']}")
    return c


class Issuer:
    def __init__(self, sk: ec.EllipticCurvePrivateKey, ttl_s: int = CRED_TTL_S):
        if not isinstance(sk.curve, ec.SECP256R1):
            raise ValueError("issuer key must be P-256")
        self.sk, self.ttl_s = sk, ttl_s
        self.pub = pub_bytes(sk.public_key())

    def issue(self, pub65: bytes, holder_commit: bytes, now_s: int) -> dict:
        exp = now_s + self.ttl_s
        cred = build(pub65, exp, holder_commit)
        return {"cred": cred, "sig": sign_raw(self.sk, cred), "expiry": exp}

    def attest_code(self, nonce: bytes, attempt: int, role: str, code_commit: bytes) -> dict:
        msg = code_attest_msg(nonce, attempt, role, code_commit)
        return {"code_commit": code_commit.hex(), "msg_hex": msg.hex(), "sig_hex": sign_raw(self.sk, msg).hex(),
                "issuer_pubkey": self.pub.hex(), "format": "POPCC1"}

    def public(self) -> dict:
        return {"alg": "ES256", "pubkey": self.pub.hex(), "pub_x": self.pub[1:33].hex(), "pub_y": self.pub[33:].hex(),
                "cred_format": "SBcred3", "cred_ttl_s": self.ttl_s}


def _from_text(s: str) -> ec.EllipticCurvePrivateKey:
    s = s.strip()
    if _HEX64.match(s):
        return ec.derive_private_key(int(s[-64:], 16), ec.SECP256R1())
    sk = serialization.load_pem_private_key(s.encode(), password=None)
    if not isinstance(sk, ec.EllipticCurvePrivateKey):
        raise ValueError("issuer key is not an EC key")
    return sk


def load_key(env_value: str | None, path: str | Path, autogen: bool = True) -> ec.EllipticCurvePrivateKey:
    if env_value:
        return _from_text(env_value)
    p = Path(path)
    if p.exists():
        return _from_text(p.read_text())
    if not autogen:
        raise FileNotFoundError(f"issuer key {p} missing (POP_ISSUER_AUTOGEN=0)")
    sk = ec.generate_private_key(ec.SECP256R1())
    pem = sk.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                           serialization.NoEncryption())
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    return sk
