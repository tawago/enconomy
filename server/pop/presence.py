"""What the core signs for outsiders: device statements and presence records (server/README.md).

Own P-256 key, POP_PRESENCE_KEY_FILE (default data/presence.pem), never the attest or issuer key. An outside party
pins the public key from /v1/config `presence`, so back it up.

Signature: crypto.sign_raw (SHA256withECDSA, raw r||s, low-S) over a domain tag + canonical(body).
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from pop.attestation import device_attested
from pop.crypto import pub_bytes, sign_raw, verify_raw

log = logging.getLogger("pop")

TAG_STATEMENT = b"pop-device-statement-v1\n"
TAG_RECORD = b"pop-presence-v1\n"
STATEMENT_FORMAT = "pop-device-statement-v1"
HARDWARE_LEVELS = {"tee", "strongbox"}


def load_key(path: str | Path) -> ec.EllipticCurvePrivateKey:
    """PEM file if it exists, else a new key written 0600."""
    p = Path(path)
    if p.exists():
        sk = serialization.load_pem_private_key(p.read_bytes(), password=None)
        if not isinstance(sk, ec.EllipticCurvePrivateKey) or not isinstance(sk.curve, ec.SECP256R1):
            raise ValueError(f"{p}: not a P-256 key")
        return sk
    sk = ec.generate_private_key(ec.SECP256R1())
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(sk.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                 serialization.NoEncryption()))
    log.warning("generated a NEW presence key at %s (back it up; whoever reads presence records pins it)", p)
    return sk


def public(sk: ec.EllipticCurvePrivateKey) -> dict:
    return {"alg": "p256", "pubkey": pub_bytes(sk.public_key()).hex()}


def _check_value(v) -> None:
    """Strings, ints, bools, null, lists and objects with string keys. Anything else raises, floats above all:
    their text isn't the same across languages."""
    if v is None or isinstance(v, (str, int, bool)):
        return
    if isinstance(v, list):
        for x in v:
            _check_value(x)
        return
    if isinstance(v, dict):
        for k, x in v.items():
            if not isinstance(k, str):
                raise ValueError(f"canonical: key {k!r} is not a string")
            _check_value(x)
        return
    raise ValueError(f"canonical: {type(v).__name__} not allowed")


def canonical(body: dict) -> bytes:
    _check_value(body)
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def sign(sk: ec.EllipticCurvePrivateKey, tag: bytes, body: dict) -> dict:
    return {"body": body, "sig_b64": base64.b64encode(sign_raw(sk, tag + canonical(body))).decode()}


def verify(pub65: bytes, tag: bytes, signed: dict) -> bool:
    """False for anything malformed, a missing signature included."""
    try:
        sig = base64.b64decode(signed["sig_b64"], validate=True)
        return verify_raw(pub65, tag + canonical(signed["body"]), sig)
    except (KeyError, TypeError, ValueError, binascii.Error):
        return False


def trust_tier(dev: dict, attested: bool) -> str:
    """attested: from attestation.device_attested. An unattested level is self-reported, so it never counts.
    iOS is app_attest, not secure_enclave: App Attest binds the key but the key kind is only reported."""
    platform = dev.get("platform")
    if platform == "web":
        return "software"
    if attested and platform == "android" and dev.get("security_level") in HARDWARE_LEVELS:
        return dev["security_level"]
    if attested and platform == "ios":
        return "app_attest"
    return "unattested"


def device_statement(sk: ec.EllipticCurvePrivateKey, dev: dict, roots: frozenset, now_ms: int) -> dict:
    """dev: a stored device row. The core vouching for a device, for those with no device table of their own."""
    attested = device_attested(dev, roots)
    return sign(sk, TAG_STATEMENT, {
        "format": STATEMENT_FORMAT, "device_id": dev["device_id"], "pubkey": dev["pubkey"], "attested": attested,
        "platform": dev["platform"], "trust_tier": trust_tier(dev, attested), "issued_at_ms": now_ms})
