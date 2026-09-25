"""Test helpers: fake clock, software-key phones, synthetic Android attestation chains."""
from __future__ import annotations

import base64
import datetime as dt
import json

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from pop.attestation import KEY_DESCRIPTION_OID
from pop.auth import request_message
from pop.crypto import device_id, pub_bytes, sign_raw


class Clock:
    def __init__(self, ms: int = 1_790_000_000_000):
        self.ms = ms

    def __call__(self) -> int:
        return self.ms

    def advance(self, s: float) -> None:
        self.ms += int(s * 1000)


# -- minimal DER for the KeyDescription extension
def _der(tag: int, v: bytes) -> bytes:
    n = len(v)
    ln = bytes([n]) if n < 0x80 else bytes([0x80 | ((n.bit_length() + 7) // 8)]) + n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([tag]) + ln + v


def _int(tag: int, x: int) -> bytes:
    return _der(tag, x.to_bytes(max(1, (x.bit_length() + 8) // 8), "big", signed=True))


def key_description(challenge: bytes, level: int = 1) -> bytes:
    return _der(0x30, _int(0x02, 200) + _int(0x0A, level) + _int(0x02, 200) + _int(0x0A, level)
                + _der(0x04, challenge) + _der(0x04, b"") + _der(0x30, b"") + _der(0x30, b""))


def _cert(subject: str, pub, issuer: str, issuer_sk, ext: bytes | None = None, ca: bool = False) -> x509.Certificate:
    now = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    b = (x509.CertificateBuilder()
         .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)]))
         .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer)]))
         .public_key(pub).serial_number(x509.random_serial_number())
         .not_valid_before(now).not_valid_after(now + dt.timedelta(days=3650))
         .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
    if ext is not None:
        b = b.add_extension(x509.UnrecognizedExtension(KEY_DESCRIPTION_OID, ext), critical=False)
    return b.sign(issuer_sk, hashes.SHA256())


def make_chain(leaf_pub, challenge: bytes, level: int = 1, with_ext: bool = True, break_link: bool = False) -> list[str]:
    """leaf (attested key) <- intermediate <- self-signed root, base64 DER, leaf first."""
    root_sk, inter_sk, other_sk = (ec.generate_private_key(ec.SECP256R1()) for _ in range(3))
    root = _cert("Fake Root", root_sk.public_key(), "Fake Root", root_sk, ca=True)
    inter = _cert("Fake Inter", inter_sk.public_key(), "Fake Root", other_sk if break_link else root_sk, ca=True)
    leaf = _cert("Android Keystore Key", leaf_pub, "Fake Inter", inter_sk,
                 ext=key_description(challenge, level) if with_ext else None)
    return [base64.b64encode(c.public_bytes(serialization.Encoding.DER)).decode() for c in (leaf, inter, root)]


class Phone:
    def __init__(self, client, clock: Clock, name: str = "phone", model: str = "Pixel Test"):
        self.client, self.clock, self.name, self.model = client, clock, name, model
        self.sk = ec.generate_private_key(ec.SECP256R1())
        self.pub = pub_bytes(self.sk.public_key())
        self.device_id = device_id(self.pub)

    def enroll_body(self, nonce: str, chain: list[str] | None, level: str = "tee") -> dict:
        return {"nonce": nonce, "device_id": self.device_id, "pubkey": self.pub.hex(), "display_name": self.name,
                "model": self.model, "security_level": level, "chain": chain}

    def enroll(self, attested: bool = True):
        nonce = self.client.get("/v1/enroll/nonce").json()["nonce"]
        chain = make_chain(self.sk.public_key(), bytes.fromhex(nonce)) if attested else None
        return self.client.post("/v1/enroll", json=self.enroll_body(nonce, chain))

    def headers(self, method: str, path: str, body: bytes, ts: int | None = None, sk=None) -> dict:
        ts = str(self.clock() if ts is None else ts)
        sig = sign_raw(sk or self.sk, request_message(method, path, body, ts))
        return {"X-Pop-Device": self.device_id, "X-Pop-Ts": ts, "X-Pop-Sig": base64.b64encode(sig).decode(),
                "content-type": "application/json"}

    def call(self, method: str, path: str, body: dict | None = None, **kw):
        raw = b"" if body is None and method == "GET" else json.dumps(body or {}).encode()
        return self.client.request(method, path, content=raw, headers=self.headers(method, path, raw, **kw))

    def get(self, path: str, **kw):
        return self.call("GET", path, **kw)

    def post(self, path: str, body: dict | None = None, **kw):
        return self.call("POST", path, body, **kw)
