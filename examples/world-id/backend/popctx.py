"""The World ID signal for a session: the nonce and the role, so a proof is bound to both.
Copied, not imported: phones and the known-answer vectors depend on these exact bytes.

keccak is pycryptodome's Keccak-256, not hashlib.sha3_256 (different padding).
"""
from __future__ import annotations

from Crypto.Hash import keccak as _keccak

ROLE_BYTE = {"A": b"\x41", "B": b"\x42"}


def keccak(b: bytes) -> bytes:
    h = _keccak.new(digest_bits=256)
    h.update(b)
    return h.digest()


def signal(n: bytes, role: str | bytes) -> bytes:
    """abi.encodePacked(bytes32 session_nonce, bytes1 role): 33 bytes."""
    rb = ROLE_BYTE[role] if isinstance(role, str) else role
    assert len(n) == 32 and rb in (b"\x41", b"\x42")
    return n + rb


def signal_str(n: bytes, role: str | bytes) -> str:
    """The IDKit signal string: lowercase 0x + even-length hex (decoded to raw bytes by IDKit)."""
    return "0x" + signal(n, role).hex()


def signal_hash_hex(b: bytes) -> str:
    return "0x%064x" % (int.from_bytes(keccak(b), "big") >> 8)


def action(sid: str) -> str:
    return "pop:" + sid
