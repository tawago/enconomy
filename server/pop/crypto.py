"""P-256 helpers: SEC1 pubkeys, raw r||s signatures, device ids (contract §2.1)."""
from __future__ import annotations

import hashlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature, encode_dss_signature


def device_id(pub65: bytes) -> str:
    return hashlib.sha256(pub65).digest()[:16].hex()


def key_hint(pub65: bytes) -> bytes:
    return hashlib.sha256(pub65).digest()[:8]


def load_pub(pub65: bytes) -> ec.EllipticCurvePublicKey:
    """Raises ValueError unless pub65 is an uncompressed point on P-256."""
    if len(pub65) != 65 or pub65[0] != 0x04:
        raise ValueError("pubkey must be 65-byte SEC1 uncompressed")
    return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), pub65)


def pub_bytes(pk: ec.EllipticCurvePublicKey) -> bytes:
    return pk.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def verify_raw(pub65: bytes, msg: bytes, sig64: bytes) -> bool:
    """SHA256withECDSA over msg, sig = raw r||s (64 bytes). Low-s not required."""
    if len(sig64) != 64:
        return False
    try:
        pk = load_pub(pub65)
        der = encode_dss_signature(int.from_bytes(sig64[:32], "big"), int.from_bytes(sig64[32:], "big"))
        pk.verify(der, msg, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError):
        return False


P256_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551


def low_s(sig64: bytes) -> bytes:
    """r||s with s <= n/2 (the bb secp256r1 blackbox rejects high-S; anyone can flip s -> n - s)."""
    s = int.from_bytes(sig64[32:], "big")
    return sig64 if s <= P256_N // 2 else sig64[:32] + (P256_N - s).to_bytes(32, "big")


def sign_raw(sk: ec.EllipticCurvePrivateKey, msg: bytes) -> bytes:
    """DER -> r||s, always low-S (issuer credentials and code attestations must be provable in Noir).
    Also what tests / fake phones use."""
    r, s = decode_dss_signature(sk.sign(msg, ec.ECDSA(hashes.SHA256())))
    return low_s(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
