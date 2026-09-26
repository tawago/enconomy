"""PopCtx (worldid spec 01 §5): the one context-binding formula.

session_nonce = keccak256(abi.encode(bytes32 DOMAIN, uint256 chainId, address consumer,
                                     bytes32 ctxHash, uint64 notBefore, bytes16 sid))
Preimage is built by hand as 6 x 32-byte words (192 bytes). keccak is pycryptodome's Keccak-256,
not hashlib.sha3_256 (different padding).
"""
from __future__ import annotations

from Crypto.Hash import keccak as _keccak


def keccak(b: bytes) -> bytes:
    h = _keccak.new(digest_bits=256)
    h.update(b)
    return h.digest()


DOMAIN = keccak(b"pop-ctx-v1")
ROLE_BYTE = {"A": b"\x41", "B": b"\x42"}


def _addr(a: str | bytes) -> bytes:
    raw = bytes.fromhex(a[2:] if a[:2] in ("0x", "0X") else a) if isinstance(a, str) else a
    if len(raw) != 20:
        raise ValueError("address must be 20 bytes")
    return raw


def _b32(x: str | bytes) -> bytes:
    raw = bytes.fromhex(x[2:] if x[:2] in ("0x", "0X") else x) if isinstance(x, str) else x
    if len(raw) != 32:
        raise ValueError("ctx_hash must be 32 bytes")
    return raw


def preimage(chain_id: int, consumer: str | bytes, ctx_hash: str | bytes, not_before: int, sid: str | bytes) -> bytes:
    sid_b = bytes.fromhex(sid) if isinstance(sid, str) else sid
    if len(sid_b) != 16:
        raise ValueError("sid must be 16 bytes")
    if not (0 <= not_before < 1 << 64) or not (0 <= chain_id < 1 << 256):
        raise ValueError("chain_id/not_before out of range")
    pre = (DOMAIN
           + chain_id.to_bytes(32, "big")
           + bytes(12) + _addr(consumer)
           + _b32(ctx_hash)
           + not_before.to_bytes(32, "big")        # uint64, left zero pad
           + sid_b + bytes(16))                    # bytes16, left-aligned, right zero pad
    assert len(pre) == 192
    return pre


def nonce(chain_id: int, consumer: str | bytes, ctx_hash: str | bytes, not_before: int, sid: str | bytes) -> bytes:
    return keccak(preimage(chain_id, consumer, ctx_hash, not_before, sid))


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


def action_field_hex(sid: str) -> str:
    return signal_hash_hex(action(sid).encode())
