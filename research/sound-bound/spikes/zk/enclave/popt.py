"""POPT / POPC byte layouts shared by the ZK spikes (fixtures, witness prep, verifier).

v1 = docs/pop-contract.md §7.1 / §7.2, exactly what the app signs today (server/pop/codec.py is the
reference; tests compare against it). v2 = the option A proposal in docs/pop-transcript-v2.md.

POPT v1 (269 B, big-endian):
  0 "POPT" | 4 0x01 | 5 role | 6 attempt u8 | 7 nonce(32) | 39 pk_self(65, 04||X||Y) | 104 pk_partner(65)
  | 169 sample_rate u32 | 173 half i32 | 177 rec_sha256(32) | 209 play_frame_position u64
  | 217 play_nano_time u64 | 225 rec_frame0_nano_time u64 | 233 self_os_delta i32 | 237 commit_hash(32)
POPT v2 (311 B): v1 with version 0x02 and rec_sha256 -> rec_root (Poseidon7 Merkle root, < p), then
  | 269 a_self u32 | 273 p_partner u32 | 277 delta u16 | 279 code_commit(32)
  (p_self = a_self - self_os_delta, a_partner = a_self + half (A) / a_self - half (B): implied, signed)
POPC v1/v2 (71 B): "POPC" | version | role | attempt u8 | nonce(32) | rec_sha256 (v1) / rec_root (v2)
"""
from __future__ import annotations

import hashlib
import struct

P256_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
P256_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551

V1_LEN, V2_LEN, POPC_LEN = 269, 311, 71
_V1 = struct.Struct(">4sBcB32s65s65sIi32sQQQi32s")
_V2X = struct.Struct(">IIH32s")
_POPC = struct.Struct(">4sBcB32s32s")
assert _V1.size == V1_LEN and _V1.size + _V2X.size == V2_LEN and _POPC.size == POPC_LEN

V1_FIELDS = ("role", "attempt", "nonce", "pk_self", "pk_partner", "sample_rate", "half", "rec",
             "play_frame_position", "play_nano_time", "rec_frame0_nano_time", "self_os_delta", "commit_hash")
V2_EXTRA = ("a_self", "p_partner", "delta", "code_commit")
OFFSETS = {"magic": 0, "version": 4, "role": 5, "attempt": 6, "nonce": 7, "pk_self": 39, "pk_partner": 104,
           "sample_rate": 169, "half": 173, "rec": 177, "play_frame_position": 209, "play_nano_time": 217,
           "rec_frame0_nano_time": 225, "self_os_delta": 233, "commit_hash": 237,
           "a_self": 269, "p_partner": 273, "delta": 277, "code_commit": 279}


def pub65(x_hex: str, y_hex: str) -> bytes:
    return b"\x04" + bytes.fromhex(x_hex) + bytes.fromhex(y_hex)


def popc(version: int, role: str, attempt: int, nonce: bytes, rec: bytes) -> bytes:
    return _POPC.pack(b"POPC", version, role.encode(), attempt, nonce, rec)


def encode(t: dict, version: int = 1) -> bytes:
    """t: V1_FIELDS (+ V2_EXTRA for version 2). rec = rec_sha256 (v1) or rec_root bytes (v2)."""
    v = [t[k] for k in V1_FIELDS]
    v[0] = v[0].encode()
    raw = _V1.pack(b"POPT", version, *v)
    if version == 2:
        raw += _V2X.pack(*(t[k] for k in V2_EXTRA))
    return raw


def decode(raw: bytes) -> dict:
    if len(raw) not in (V1_LEN, V2_LEN):
        raise ValueError(f"bad POPT length {len(raw)}")
    magic, ver, *v = _V1.unpack(raw[:V1_LEN])
    if magic != b"POPT" or (ver, len(raw)) not in ((1, V1_LEN), (2, V2_LEN)):
        raise ValueError("bad magic/version/length")
    t = dict(zip(V1_FIELDS, v))
    t["role"] = t["role"].decode()
    t["version"] = ver
    if ver == 2:
        t.update(zip(V2_EXTRA, _V2X.unpack(raw[V1_LEN:])))
        t["p_self"] = t["a_self"] - t["self_os_delta"]
        t["a_partner"] = t["a_self"] + (t["half"] if t["role"] == "A" else -t["half"])
    return t


def sha256(b: bytes) -> bytes:
    return hashlib.sha256(b).digest()


def low_s(s: int) -> bool:
    return s <= P256_N // 2
