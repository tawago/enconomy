"""Fixed-layout binary records (contract §7) and the PCM wire format (§5.3).

Commitment (71 bytes): "POPC" | 0x01 | role | attempt u8 | session_nonce 32 | rec_sha256 32.
"""
from __future__ import annotations

import base64
import binascii
import struct

import numpy as np

COMMIT_MAGIC, COMMIT_LEN = b"POPC", 71
VERSION = 1
_COMMIT = struct.Struct(">4sBcB32s32s")


def encode_commit(role: str, attempt: int, nonce: bytes, rec_sha256: bytes) -> bytes:
    return _COMMIT.pack(COMMIT_MAGIC, VERSION, role.encode(), attempt, nonce, rec_sha256)


def decode_commit(raw: bytes) -> dict:
    """ValueError on wrong length / magic / version / role."""
    if len(raw) != COMMIT_LEN:
        raise ValueError(f"commit must be {COMMIT_LEN} bytes, got {len(raw)}")
    magic, ver, role, attempt, nonce, rec = _COMMIT.unpack(raw)
    if magic != COMMIT_MAGIC or ver != VERSION:
        raise ValueError("bad magic/version")
    if role not in (b"A", b"B"):
        raise ValueError("bad role")
    return {"role": role.decode(), "attempt": attempt, "nonce": nonce, "rec_sha256": rec}


def b64d(s) -> bytes:
    """Strict std base64; ValueError otherwise."""
    if not isinstance(s, str):
        raise ValueError("expected base64 string")
    try:
        return base64.b64decode(s, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("bad base64") from None


def pcm(x) -> dict:
    """{pcm_b64, n}: float32 LE mono."""
    a = np.asarray(x, dtype="<f4")
    return {"pcm_b64": base64.b64encode(a.tobytes()).decode(), "n": int(a.size)}


def pcm_decode(d: dict) -> np.ndarray:
    return np.frombuffer(base64.b64decode(d["pcm_b64"]), dtype="<f4")
