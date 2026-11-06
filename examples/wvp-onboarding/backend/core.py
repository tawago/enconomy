"""Checking what the core signs: presence records. Copied, not imported: the core's format
is its public API, and tests/fixtures/presence_vector.json is the same vector the core tests against.

Signature: SHA256withECDSA, raw r||s base64, over a domain tag + canonical(body).
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

TAG_RECORD = b"pop-presence-v1\n"
RECORD_FORMAT = "pop-presence-v1"
SID_RE = re.compile(r"^[0-9a-f]{32}$")
ROLES = ("A", "B")


def device_id(pub65: bytes) -> str:
    return hashlib.sha256(pub65).digest()[:16].hex()


def load_pub(pub65: bytes) -> ec.EllipticCurvePublicKey:
    """Raises ValueError unless pub65 is an uncompressed point on P-256."""
    if len(pub65) != 65 or pub65[0] != 0x04:
        raise ValueError("pubkey must be 65-byte SEC1 uncompressed")
    return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), pub65)


def verify_raw(pub65: bytes, msg: bytes, sig64: bytes) -> bool:
    if len(sig64) != 64:
        return False
    try:
        der = encode_dss_signature(int.from_bytes(sig64[:32], "big"), int.from_bytes(sig64[32:], "big"))
        load_pub(pub65).verify(der, msg, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError):
        return False


def _check_value(v) -> None:
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


def canonical(body) -> bytes:
    """Strings, ints, bools, null, lists, objects. A float raises: its text isn't the same across languages."""
    _check_value(body)
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def verify_signed(pub65: bytes, tag: bytes, signed) -> bool:
    """{body, sig_b64} under the pinned key. False for anything malformed, a missing signature included."""
    try:
        if not isinstance(signed["body"], dict):
            return False
        sig = base64.b64decode(signed["sig_b64"], validate=True)
        return verify_raw(pub65, tag + canonical(signed["body"]), sig)
    except (KeyError, TypeError, ValueError, binascii.Error, RecursionError):
        return False


def record_problem(body: dict) -> str | None:
    """The record is core-signed already; this redoes what the core's word covers. None if all of it holds.
    A NEAR needs both halves. Other verdicts carry whatever they have."""
    if body.get("format") != RECORD_FORMAT:
        return "format"
    sid = body.get("session_id")
    if not isinstance(sid, str) or not SID_RE.fullmatch(sid):
        return "session_id"
    devices, transcripts = body.get("devices"), body.get("transcripts")
    if not isinstance(devices, dict) or not isinstance(transcripts, dict):
        return "devices or transcripts missing"
    if body.get("verdict") == "NEAR" and not all(r in devices and r in transcripts for r in ROLES):
        return "NEAR without both devices and transcripts"
    pubs = {}
    for role, d in devices.items():
        try:
            pubs[role] = bytes.fromhex(d["pubkey"])
            load_pub(pubs[role])
        except (KeyError, TypeError, ValueError):
            return f"{role}: bad pubkey"
        if d.get("device_id") != device_id(pubs[role]):
            return f"{role}: device_id is not sha256(pubkey)[:16]"
    for role, t in transcripts.items():
        if role not in pubs:
            return f"{role}: transcript without a device"
        try:
            raw = base64.b64decode(t["transcript_b64"], validate=True)
            sig = base64.b64decode(t["sig_b64"], validate=True)
        except (KeyError, TypeError, ValueError, binascii.Error):
            return f"{role}: bad transcript encoding"
        if hashlib.sha256(raw).hexdigest() != t.get("sha256"):
            return f"{role}: transcript sha256"
        if not verify_raw(pubs[role], raw, sig):
            return f"{role}: transcript signature"
    return None
