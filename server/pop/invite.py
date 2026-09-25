"""Invite codec (contract §3.2): 49 bytes, QR form "pop1:" + base64url(no pad).

 0  4  magic "POP1"
 4  1  version 0x01
 5 16  session_id
21 16  join_token
37  4  expires_at, unix s, u32 BE
41  8  sha256(host pubkey65)[:8]
"""
from __future__ import annotations

import base64
import struct

MAGIC = b"POP1"
VERSION = 1
SIZE = 49
QR_PREFIX = "pop1:"


def encode(session_id_hex: str, join_token_hex: str, expires_at_s: int, host_hint: bytes) -> bytes:
    sid, tok = bytes.fromhex(session_id_hex), bytes.fromhex(join_token_hex)
    assert len(sid) == 16 and len(tok) == 16 and len(host_hint) == 8
    out = MAGIC + bytes([VERSION]) + sid + tok + struct.pack(">I", expires_at_s) + host_hint
    assert len(out) == SIZE
    return out


def decode(b: bytes) -> dict:
    if len(b) != SIZE or b[:4] != MAGIC or b[4] != VERSION:
        raise ValueError("not a POP1 invite")
    return {
        "session_id": b[5:21].hex(),
        "join_token": b[21:37].hex(),
        "expires_at_s": struct.unpack(">I", b[37:41])[0],
        "host_hint": b[41:49],
    }


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def to_qr(b: bytes) -> str:
    return QR_PREFIX + b64url(b)


def from_qr(s: str) -> bytes:
    if not s.startswith(QR_PREFIX):
        raise ValueError("missing pop1: prefix")
    body = s[len(QR_PREFIX):]
    return base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
