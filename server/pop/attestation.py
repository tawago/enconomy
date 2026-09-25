"""Android Key Attestation, hackathon grade (contract §2.2).

Checked: chain signatures (each cert by the next), leaf pubkey == enrolled pubkey,
KeyDescription extension present, attestationChallenge == nonce.
NOT checked: Google root pin, revocation/RKP, attestationApplicationId, verified boot,
minimum security level, validity dates.
"""
from __future__ import annotations

import base64
import hashlib

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from pop.crypto import pub_bytes

KEY_DESCRIPTION_OID = x509.ObjectIdentifier("1.3.6.1.4.1.11129.2.1.17")
SECURITY_LEVELS = {0: "software", 1: "tee", 2: "strongbox"}


class AttestationError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code, self.detail = code, detail


def _tlv(buf: bytes, i: int) -> tuple[int, bytes, int]:
    """One DER TLV at i -> (tag byte, value, next index). Single-byte tags only (enough for the
    first KeyDescription fields; AuthorizationList is skipped as a whole)."""
    if i + 2 > len(buf):
        raise ValueError("truncated")
    tag = buf[i]
    if tag & 0x1F == 0x1F:
        raise ValueError("multi-byte tag")
    ln = buf[i + 1]
    j = i + 2
    if ln & 0x80:
        k = ln & 0x7F
        if k == 0 or k > 4 or j + k > len(buf):
            raise ValueError("bad length")
        ln = int.from_bytes(buf[j:j + k], "big")
        j += k
    if j + ln > len(buf):
        raise ValueError("truncated value")
    return tag, buf[j:j + ln], j + ln


def parse_key_description(der: bytes) -> dict:
    """KeyDescription ::= SEQUENCE { attestationVersion INTEGER, attestationSecurityLevel ENUMERATED,
    keyMintVersion INTEGER, keyMintSecurityLevel ENUMERATED, attestationChallenge OCTET STRING, ... }"""
    tag, seq, _ = _tlv(der, 0)
    if tag != 0x30:
        raise ValueError("KeyDescription not a SEQUENCE")
    fields, i = [], 0
    while i < len(seq) and len(fields) < 5:
        t, v, i = _tlv(seq, i)
        fields.append((t, v))
    if len(fields) < 5:
        raise ValueError("KeyDescription too short")
    want = [0x02, 0x0A, 0x02, 0x0A, 0x04]
    if [t for t, _ in fields] != want:
        raise ValueError("KeyDescription field types")
    as_int = lambda v: int.from_bytes(v, "big", signed=True)
    return {
        "attestation_version": as_int(fields[0][1]),
        "attestation_security_level": SECURITY_LEVELS.get(as_int(fields[1][1]), "unknown"),
        "keymint_version": as_int(fields[2][1]),
        "keymint_security_level": SECURITY_LEVELS.get(as_int(fields[3][1]), "unknown"),
        "challenge": fields[4][1],
    }


def verify_chain(chain_b64: list[str], pub65: bytes, nonce: bytes) -> dict:
    """-> {security_level, chain_pem, root_sha256, attestation_version}. Raises AttestationError."""
    if not isinstance(chain_b64, list) or len(chain_b64) < 2:
        raise AttestationError("enroll_bad_chain", "chain needs leaf + at least one issuer")
    try:
        certs = [x509.load_der_x509_certificate(base64.b64decode(c, validate=True)) for c in chain_b64]
    except Exception as e:  # noqa: BLE001
        raise AttestationError("enroll_bad_chain", f"cert parse: {e}") from e
    for child, issuer in zip(certs, certs[1:]):
        try:
            child.verify_directly_issued_by(issuer)
        except Exception as e:  # noqa: BLE001
            raise AttestationError("enroll_bad_chain", f"signature: {child.subject.rfc4514_string()}: {e}") from e
    leaf = certs[0]
    try:
        leaf_pub = pub_bytes(leaf.public_key())
    except Exception as e:  # noqa: BLE001
        raise AttestationError("enroll_key_mismatch", f"leaf key not EC: {e}") from e
    if leaf_pub != pub65:
        raise AttestationError("enroll_key_mismatch", "leaf cert key != pubkey")
    try:
        ext = leaf.extensions.get_extension_for_oid(KEY_DESCRIPTION_OID).value
    except x509.ExtensionNotFound as e:
        raise AttestationError("enroll_bad_chain", "no attestation extension on leaf") from e
    try:
        kd = parse_key_description(ext.value)
    except ValueError as e:
        raise AttestationError("enroll_bad_chain", f"KeyDescription: {e}") from e
    if kd["challenge"] != nonce:
        raise AttestationError("enroll_bad_challenge", "attestationChallenge != nonce")
    pem = "".join(c.public_bytes(serialization.Encoding.PEM).decode() for c in certs)
    return {
        "security_level": kd["attestation_security_level"],
        "attestation_version": kd["attestation_version"],
        "root_sha256": hashlib.sha256(certs[-1].public_bytes(serialization.Encoding.DER)).hexdigest(),
        "chain_pem": pem,
    }
