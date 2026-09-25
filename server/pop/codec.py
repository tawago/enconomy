"""Fixed-layout binary records (contract §7) and the PCM wire format (§5.3).

Commitment (71 bytes): "POPC" | 0x01 | role | attempt u8 | session_nonce 32 | rec_sha256 32.
Transcript (269 bytes, §7.1): "POPT" | 0x01 | role | attempt u8 | session_nonce 32 | pk_self 65 |
  pk_partner 65 | sample_rate u32 | half i32 | rec_sha256 32 | play_frame_position u64 |
  play_nano_time u64 | rec_frame0_nano_time u64 | self_os_delta i32 | commit_hash 32.  All big-endian.
"""
from __future__ import annotations

import base64
import binascii
import struct

import numpy as np

COMMIT_MAGIC, COMMIT_LEN = b"POPC", 71
VERSION = 1
_COMMIT = struct.Struct(">4sBcB32s32s")
TRANSCRIPT_MAGIC, TRANSCRIPT_LEN = b"POPT", 269
_TX = struct.Struct(">4sBcB32s65s65sIi32sQQQi32s")
TX_FIELDS = ("role", "attempt", "nonce", "pk_self", "pk_partner", "sample_rate", "half", "rec_sha256",
             "play_frame_position", "play_nano_time", "rec_frame0_nano_time", "self_os_delta", "commit_hash")
assert _TX.size == TRANSCRIPT_LEN


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


def encode_transcript(t: dict) -> bytes:
    """t has TX_FIELDS; role 'A'|'B', byte fields raw. struct.error on out-of-range ints."""
    v = [t[k] for k in TX_FIELDS]
    v[0] = v[0].encode()
    return _TX.pack(TRANSCRIPT_MAGIC, VERSION, *v)


def decode_transcript(raw: bytes) -> dict:
    """ValueError on wrong length / magic / version / role."""
    if len(raw) != TRANSCRIPT_LEN:
        raise ValueError(f"transcript must be {TRANSCRIPT_LEN} bytes, got {len(raw)}")
    magic, ver, *v = _TX.unpack(raw)
    if magic != TRANSCRIPT_MAGIC or ver != VERSION:
        raise ValueError("bad magic/version")
    if v[0] not in (b"A", b"B"):
        raise ValueError("bad role")
    t = dict(zip(TX_FIELDS, v))
    t["role"] = t["role"].decode()
    return t


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
