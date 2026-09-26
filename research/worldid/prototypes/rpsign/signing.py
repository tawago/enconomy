"""World ID 4.0 RP request signing (port of idkit js/packages/server/src/lib/signing.ts).

message = 0x01 || nonce(32) || created_at u64be || expires_at u64be || [hash_to_field(utf8(action))]
digest  = EIP-191 personal_sign over message
sig     = r || s || v (v = 27/28), 0x-hex
"""
from __future__ import annotations

import os
import time

from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import keccak

DEFAULT_TTL = 300


def hash_to_field(b: bytes) -> bytes:
    return (int.from_bytes(keccak(b), "big") >> 8).to_bytes(32, "big")


def rp_message(nonce: bytes, created_at: int, expires_at: int, action: str | None) -> bytes:
    m = b"\x01" + nonce + created_at.to_bytes(8, "big") + expires_at.to_bytes(8, "big")
    if action is not None:
        m += hash_to_field(action.encode("utf-8"))
    return m


def sign_request(
    key_hex: str,
    action: str | None = None,
    ttl: int = DEFAULT_TTL,
    rand: bytes | None = None,
    now: int | None = None,
) -> dict:
    nonce = hash_to_field(rand if rand is not None else os.urandom(32))
    created_at = int(time.time()) if now is None else now
    expires_at = created_at + ttl
    msg = rp_message(nonce, created_at, expires_at, action)
    s = Account.sign_message(encode_defunct(primitive=msg), key_hex)
    sig = s.r.to_bytes(32, "big") + s.s.to_bytes(32, "big") + bytes([s.v])
    return {
        "sig": "0x" + sig.hex(),
        "nonce": "0x" + nonce.hex(),
        "created_at": created_at,
        "expires_at": expires_at,
        "msg": msg.hex(),
    }


def recover_signer(msg_hex: str, sig_hex: str) -> str:
    return Account.recover_message(encode_defunct(primitive=bytes.fromhex(msg_hex)), signature=sig_hex)


def address_of(key_hex: str) -> str:
    return Account.from_key(key_hex).address
