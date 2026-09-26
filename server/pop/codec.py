"""Fixed-layout binary records (contract §7, docs/pop-transcript-v2.md §1, §4) and the PCM wire format (§5.3).

Commitment (71 bytes): "POPC" | version | role | attempt u8 | session_nonce 32 | rec 32
  (v1 rec = rec_sha256, v2 rec = rec_root, a Poseidon7 root < p).
Transcript v1 (269 bytes, §7.1): "POPT" | 0x01 | role | attempt u8 | session_nonce 32 | pk_self 65 |
  pk_partner 65 | sample_rate u32 | half i32 | rec_sha256 32 | play_frame_position u64 |
  play_nano_time u64 | rec_frame0_nano_time u64 | self_os_delta i32 | commit_hash 32.  All big-endian.
Transcript v2 (311 bytes): v1 with 0x02 and rec_sha256 -> rec_root, then a_self u32 | p_partner u32 |
  delta u16 | code_commit 32. decode derives p_self = a_self - self_os_delta and
  a_partner = a_self + half (A) / a_self - half (B).
Decoders dispatch on (version, length). v1 dicts carry no "version" key (version_of() says 1).
"""
from __future__ import annotations

import base64
import binascii
import struct

import numpy as np

from pop.poseidon7 import P as FIELD_P

COMMIT_MAGIC, COMMIT_LEN = b"POPC", 71
VERSION = 1
VERSION2 = 2
_COMMIT = struct.Struct(">4sBcB32s32s")
TRANSCRIPT_MAGIC, TRANSCRIPT_LEN = b"POPT", 269
TRANSCRIPT2_LEN = 311
_TX = struct.Struct(">4sBcB32s65s65sIi32sQQQi32s")
_TX2X = struct.Struct(">IIH32s")
TX_FIELDS = ("role", "attempt", "nonce", "pk_self", "pk_partner", "sample_rate", "half", "rec_sha256",
             "play_frame_position", "play_nano_time", "rec_frame0_nano_time", "self_os_delta", "commit_hash")
TX2_FIELDS = tuple("rec_root" if k == "rec_sha256" else k for k in TX_FIELDS)
TX2_EXTRA = ("a_self", "p_partner", "delta", "code_commit")
REC_KEY = {1: "rec_sha256", 2: "rec_root"}
assert _TX.size == TRANSCRIPT_LEN and _TX.size + _TX2X.size == TRANSCRIPT2_LEN


def version_of(d: dict) -> int:
    return d.get("version", VERSION)


def _root_ok(rec: bytes) -> None:
    if int.from_bytes(rec, "big") >= FIELD_P:
        raise ValueError("rec_root not < p")


def encode_commit(role: str, attempt: int, nonce: bytes, rec: bytes, version: int = VERSION) -> bytes:
    if version not in (VERSION, VERSION2):
        raise ValueError("bad version")
    return _COMMIT.pack(COMMIT_MAGIC, version, role.encode(), attempt, nonce, rec)


def decode_commit(raw: bytes) -> dict:
    """ValueError on wrong length / magic / version / role (v2: rec_root >= p)."""
    if len(raw) != COMMIT_LEN:
        raise ValueError(f"commit must be {COMMIT_LEN} bytes, got {len(raw)}")
    magic, ver, role, attempt, nonce, rec = _COMMIT.unpack(raw)
    if magic != COMMIT_MAGIC or ver not in (VERSION, VERSION2):
        raise ValueError("bad magic/version")
    if role not in (b"A", b"B"):
        raise ValueError("bad role")
    c = {"role": role.decode(), "attempt": attempt, "nonce": nonce, REC_KEY[ver]: rec}
    if ver == VERSION2:
        _root_ok(rec)
        c["version"] = VERSION2
    return c


def encode_transcript(t: dict) -> bytes:
    """t has TX_FIELDS (v1) or version 2 + TX2_FIELDS + TX2_EXTRA; role 'A'|'B', byte fields raw.
    struct.error on out-of-range ints."""
    ver = version_of(t)
    v = [t[k] for k in (TX2_FIELDS if ver == VERSION2 else TX_FIELDS)]
    v[0] = v[0].encode()
    raw = _TX.pack(TRANSCRIPT_MAGIC, ver, *v)
    if ver == VERSION2:
        raw += _TX2X.pack(*(t[k] for k in TX2_EXTRA))
    elif ver != VERSION:
        raise ValueError("bad version")
    return raw


def decode_transcript(raw: bytes) -> dict:
    """ValueError on wrong length / magic / version / role (v2: rec_root >= p)."""
    if len(raw) not in (TRANSCRIPT_LEN, TRANSCRIPT2_LEN):
        raise ValueError(f"transcript must be {TRANSCRIPT_LEN} or {TRANSCRIPT2_LEN} bytes, got {len(raw)}")
    magic, ver, *v = _TX.unpack(raw[:TRANSCRIPT_LEN])
    if magic != TRANSCRIPT_MAGIC or (ver, len(raw)) not in ((VERSION, TRANSCRIPT_LEN), (VERSION2, TRANSCRIPT2_LEN)):
        raise ValueError("bad magic/version")
    if v[0] not in (b"A", b"B"):
        raise ValueError("bad role")
    if ver == VERSION:
        t = dict(zip(TX_FIELDS, v))
    else:
        t = {"version": VERSION2, **dict(zip(TX2_FIELDS, v)), **dict(zip(TX2_EXTRA, _TX2X.unpack(raw[TRANSCRIPT_LEN:])))}
        _root_ok(t["rec_root"])
    t["role"] = t["role"].decode()
    if ver == VERSION2:
        t["p_self"] = t["a_self"] - t["self_os_delta"]
        t["a_partner"] = t["a_self"] + (t["half"] if t["role"] == "A" else -t["half"])
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
