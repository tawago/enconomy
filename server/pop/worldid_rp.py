"""World ID 4.0 rp_context signer (worldid 01 §6.3). Port of the spike's eth-account signer
(~/dev/worldid-spike/backend/app/signing.py, itself checked against @worldcoin/idkit-core/signing 4.2.4)
to pure Python: secp256k1 + RFC 6979 (HMAC-SHA256, as eth-keys) + keccak from pycryptodome.

message = 0x01 || nonce32 || created_at u64be || expires_at u64be [|| hash_to_field(utf8(action))]
digest  = keccak256("\\x19Ethereum Signed Message:\\n" + len(message) + message)   (EIP-191 personal_sign)
sig     = r || s || v, low-s, v = 27/28
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from pathlib import Path

from pop.popctx import keccak

DEFAULT_TTL = 300

# secp256k1
P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
G = (0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
     0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8)


def _add(a, b):
    if a is None:
        return b
    if b is None:
        return a
    if a[0] == b[0]:
        if (a[1] + b[1]) % P == 0:
            return None
        lam = 3 * a[0] * a[0] * pow(2 * a[1], -1, P) % P
    else:
        lam = (b[1] - a[1]) * pow(b[0] - a[0], -1, P) % P
    x = (lam * lam - a[0] - b[0]) % P
    return x, (lam * (a[0] - x) - a[1]) % P


def _mul(k: int, pt=G):
    out = None
    while k:
        if k & 1:
            out = _add(out, pt)
        pt = _add(pt, pt)
        k >>= 1
    return out


def hash_to_field(b: bytes) -> bytes:
    return (int.from_bytes(keccak(b), "big") >> 8).to_bytes(32, "big")


def rp_message(nonce: bytes, created_at: int, expires_at: int, action: str | None) -> bytes:
    m = b"\x01" + nonce + created_at.to_bytes(8, "big") + expires_at.to_bytes(8, "big")
    if action is not None:
        m += hash_to_field(action.encode("utf-8"))
    return m


def _key(key_hex: str) -> bytes:
    k = bytes.fromhex(key_hex.strip().removeprefix("0x"))
    if len(k) != 32 or not 0 < int.from_bytes(k, "big") < N:
        raise ValueError("bad secp256k1 private key")
    return k


def _rfc6979_k(h: bytes, priv: bytes) -> int:
    v, k = b"\x01" * 32, b"\x00" * 32
    k = hmac.new(k, v + b"\x00" + priv + h, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    k = hmac.new(k, v + b"\x01" + priv + h, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    return int.from_bytes(hmac.new(k, v, hashlib.sha256).digest(), "big")


def personal_sign(key_hex: str, msg: bytes) -> bytes:
    priv = _key(key_hex)
    h = keccak(b"\x19Ethereum Signed Message:\n" + str(len(msg)).encode() + msg)
    z, d = int.from_bytes(h, "big"), int.from_bytes(priv, "big")
    k = _rfc6979_k(h, priv)
    r, y = _mul(k)
    r %= N
    s = pow(k, -1, N) * (z + r * d) % N
    high = s * 2 >= N
    v = 27 + ((y & 1) ^ int(high))
    if high:
        s = N - s
    return r.to_bytes(32, "big") + s.to_bytes(32, "big") + bytes([v])


def address_of(key_hex: str) -> str:
    x, y = _mul(int.from_bytes(_key(key_hex), "big"))
    return "0x" + keccak(x.to_bytes(32, "big") + y.to_bytes(32, "big"))[-20:].hex()


def new_nonce(rand: bytes | None = None) -> bytes:
    """hash_to_field(random32): a raw random 32 bytes can exceed the BN254 field (01 §6.3)."""
    return hash_to_field(rand if rand is not None else os.urandom(32))


def sign_request(key_hex: str, action: str | None = None, ttl: int = DEFAULT_TTL, rand: bytes | None = None,
                 now: int | None = None) -> dict:
    nonce = new_nonce(rand)
    created_at = int(time.time()) if now is None else now
    expires_at = created_at + ttl
    msg = rp_message(nonce, created_at, expires_at, action)
    return {"sig": "0x" + personal_sign(key_hex, msg).hex(), "nonce": "0x" + nonce.hex(),
            "created_at": created_at, "expires_at": expires_at, "msg": msg.hex()}


def load_key(path: str | None, env_key: str | None, autogen: bool) -> str | None:
    """env hex wins; else the file (hex, 0600); autogen (fake mode only) writes a fresh key when missing."""
    if env_key:
        _key(env_key)
        return env_key.strip()
    if path and Path(path).is_file():
        k = Path(path).read_text().strip()
        _key(k)
        return k
    if autogen and path:
        k = "0x" + os.urandom(32).hex()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(k + "\n")
        return k
    return None
