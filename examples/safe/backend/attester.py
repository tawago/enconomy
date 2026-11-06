"""Chain attester: P-256 over a sha256 digest, raw r||s, no low-s normalization. Same format the deployed guard takes.

The key is loaded, never generated: Safes pin its qx/qy, so a new key means BadAttestation on chain.
PAIR_TAG is fixed because this example proves no humans. PopAttestationVerifier hashes pairTag without checking it,
and PopSafeGuard doesn't read it, so the deployed contracts accept it as is.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed, decode_dss_signature

from backend.safe_tx import TAG

MAGIC_POP2 = b"POP2"
PAIR_TAG = hashlib.sha256(b"pop-safe-no-human-v1").digest()


def load_key(path: str | Path) -> ec.EllipticCurvePrivateKey:
    """Raises FileNotFoundError if it isn't there."""
    p = Path(path)
    sk = serialization.load_pem_private_key(p.read_bytes(), password=None)
    if not isinstance(sk, ec.EllipticCurvePrivateKey) or not isinstance(sk.curve, ec.SECP256R1):
        raise ValueError(f"{p}: not a P-256 key")
    return sk


def public(sk: ec.EllipticCurvePrivateKey) -> dict:
    n = sk.public_key().public_numbers()
    return {"alg": "p256", "qx": "0x%064x" % n.x, "qy": "0x%064x" % n.y}


def public_bytes(sk: ec.EllipticCurvePrivateKey) -> bytes:
    return sk.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def _b(x: str | bytes, n: int, what: str) -> bytes:
    raw = bytes.fromhex(x[2:] if x[:2] in ("0x", "0X") else x) if isinstance(x, str) else x
    if len(raw) != n:
        raise ValueError(f"{what} must be {n} bytes")
    return raw


def preimage(tag: bytes, chain_id: int, consumer, ctx_hash, pair_tag, dev_a, dev_b, expiry: int) -> bytes:
    """tag(11) | u256 chainId | consumer(20) | ctxHash | pairTag | devA | devB | u64 expiry BE (199 B for 11 B tags)."""
    return (tag + chain_id.to_bytes(32, "big") + _b(consumer, 20, "consumer") + _b(ctx_hash, 32, "ctx_hash")
            + _b(pair_tag, 32, "pair_tag") + _b(dev_a, 32, "dev_a") + _b(dev_b, 32, "dev_b")
            + expiry.to_bytes(8, "big"))


def tagged_digest(tag: bytes, chain_id: int, consumer, ctx_hash, pair_tag, dev_a, dev_b, expiry: int) -> bytes:
    return hashlib.sha256(preimage(tag, chain_id, consumer, ctx_hash, pair_tag, dev_a, dev_b, expiry)).digest()


def sign(sk: ec.EllipticCurvePrivateKey, digest: bytes) -> tuple[bytes, bytes]:
    r, s = decode_dss_signature(sk.sign(digest, ec.ECDSA(Prehashed(hashes.SHA256()))))
    return r.to_bytes(32, "big"), s.to_bytes(32, "big")


def tail(pair_tag, dev_a, dev_b, expiry: int, r: bytes, s: bytes) -> bytes:
    """172 B: pairTag | devA | devB | expiry(8) | r | s | "POP2" (what PopAttestationVerifier reads)."""
    t = (_b(pair_tag, 32, "pair_tag") + _b(dev_a, 32, "dev_a") + _b(dev_b, 32, "dev_b") + expiry.to_bytes(8, "big")
         + r + s + MAGIC_POP2)
    assert len(t) == 172
    return t


def dev_hash(pub_hex: str) -> bytes:
    return hashlib.sha256(bytes.fromhex(pub_hex)).digest()


def attestation(sk: ec.EllipticCurvePrivateKey, context: dict, pub_a: str, pub_b: str, expiry: int) -> dict:
    """The fields relay.mjs reads, signed once by the caller: ECDSA is randomized, so keep what this returns."""
    dev_a, dev_b = dev_hash(pub_a), dev_hash(pub_b)
    d = tagged_digest(TAG, context["chain_id"], context["consumer"], context["ctx_hash"], PAIR_TAG, dev_a, dev_b, expiry)
    r, s = sign(sk, d)
    return {"v": TAG.decode(), "pair_tag": "0x" + PAIR_TAG.hex(), "dev_a": "0x" + dev_a.hex(), "dev_b": "0x" + dev_b.hex(),
            "expiry": expiry, "digest": "0x" + d.hex(), "r": "0x" + r.hex(), "s": "0x" + s.hex(),
            "tail_hex": "0x" + tail(PAIR_TAG, dev_a, dev_b, expiry, r, s).hex()}
