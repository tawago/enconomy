"""Android Key Attestation (contract §2.2).

Checked: chain signatures (each cert by the next), last cert's public key is a pinned Google root,
every non-leaf cert has BasicConstraints ca=true and no KeyDescription, leaf pubkey == enrolled pubkey,
KeyDescription present, attestationSecurityLevel is tee or strongbox, attestationChallenge == nonce.

Why the non-leaf rule: the leaf key is app-controlled, so a real phone can sign a child cert for any key
and any KeyDescription under its own Google-rooted leaf. Google's root alone doesn't stop that.

NOT checked:
- revocation (android.googleapis.com/attestation/status) and RKP state, so a leaked batch key still passes.
- attestationApplicationId, so any app on a real phone can attest, not just ours.
- verified boot state, so an unlocked or rooted phone can pass.
- validity dates, on purpose for now: Google's first root cert expired 2026-05-24 but its key is still a
  live trust anchor, and older phones may still carry that cert in their chains. Pinning the key handles it.
"""
from __future__ import annotations

import base64
import hashlib

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from pop.crypto import pub_bytes

KEY_DESCRIPTION_OID = x509.ObjectIdentifier("1.3.6.1.4.1.11129.2.1.17")
SECURITY_LEVELS = {0: "software", 1: "tee", 2: "strongbox"}
HARDWARE_LEVELS = {"tee", "strongbox"}

# Google's attestation roots, by sha256 of SubjectPublicKeyInfo: Google has reissued certs with the same key.
# Fetched 2026-11-06 from https://android.googleapis.com/attestation/root (the two current certs) and
# https://developer.android.com/privacy-and-security/security-key-attestation (those two, plus "Previously Issued").
# Copy of the JSON: tests/fixtures/google-attestation-roots.json.
# feb2ea75... RSA-4096, serialNumber=f92009e853b6b045. Cert sha256 by validity:
#   cedb1cb6dc896ae5ec797348bce9286753c2b38ee71ce0fbe34a9a1248800dfc  2022-03-20..2042-03-15 (current)
#   c1984a3ef45c1e2a918551de10603c86f7051b2249c4891cae3230eabd0c97d5  2016-05-26..2026-05-24
#   1ef1a04b8ba58ab94589ac498c8982a783f24ea7307e0159a0c3a73b377d87cc  2019-11-22..2034-11-18
#   ab6641178a36e179aa0c1cdddf9a16eb45fa20943e2b8cd7c7c05c26cf8b487a  2021-11-17..2036-11-13
# 3ee44512... P-384, CN=Key Attestation CA1, signs chains from 2026-02-01. Cert sha256:
#   6d9db4ce6c5c0b293166d08986e05774a8776ceb525d9e4329520de12ba4bcc0  2025-07-17..2035-07-15 (current)
GOOGLE_ANDROID_ROOTS = frozenset({
    "feb2ea7551ee316ed4bb443c8293b884dbfdea40b603ee3e4f4a897e4580fbae",
    "3ee44512a1af2beb39c889490c60ea3f82e43f5d5a5532f5ab9419f676cd07ec",
})


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


def spki_sha256(cert: x509.Certificate) -> str:
    spki = cert.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return hashlib.sha256(spki).hexdigest()


def roots_from_pem(pem: bytes) -> frozenset:
    """Every cert in a PEM file -> SPKI pins. Raises on a file with no certs."""
    return frozenset(spki_sha256(c) for c in x509.load_pem_x509_certificates(pem))


def _check_path(certs: list[x509.Certificate], roots: frozenset) -> None:
    """Signatures, root pin, and the non-leaf rule (see the header)."""
    for child, issuer in zip(certs, certs[1:]):
        try:
            child.verify_directly_issued_by(issuer)
        except Exception as e:  # noqa: BLE001
            raise AttestationError("enroll_bad_chain", f"signature: {child.subject.rfc4514_string()}: {e}") from e
    try:
        pinned = spki_sha256(certs[-1]) in roots
    except Exception as e:  # noqa: BLE001
        raise AttestationError("enroll_bad_chain", f"root key: {e}") from e
    if not pinned:
        raise AttestationError("enroll_bad_chain", "root key not pinned")
    for c in certs[1:]:
        try:
            exts = c.extensions
        except Exception as e:  # noqa: BLE001
            raise AttestationError("enroll_bad_chain", f"extensions: {e}") from e
        try:
            ca = exts.get_extension_for_class(x509.BasicConstraints).value.ca
        except x509.ExtensionNotFound:
            ca = False
        if not ca:
            raise AttestationError("enroll_bad_chain", f"not a CA: {c.subject.rfc4514_string()}")
        if any(e.oid == KEY_DESCRIPTION_OID for e in exts):
            raise AttestationError("enroll_bad_chain", f"KeyDescription above the leaf: {c.subject.rfc4514_string()}")


def _leaf_description(leaf: x509.Certificate) -> dict:
    try:
        ext = leaf.extensions.get_extension_for_oid(KEY_DESCRIPTION_OID).value
    except x509.ExtensionNotFound as e:
        raise AttestationError("enroll_bad_chain", "no attestation extension on leaf") from e
    except Exception as e:  # noqa: BLE001
        raise AttestationError("enroll_bad_chain", f"extensions: {e}") from e
    try:
        kd = parse_key_description(ext.value)
    except ValueError as e:
        raise AttestationError("enroll_bad_chain", f"KeyDescription: {e}") from e
    if kd["attestation_security_level"] not in HARDWARE_LEVELS:
        raise AttestationError("enroll_bad_chain", f"attestation level {kd['attestation_security_level']}")
    return kd


def verify_chain(chain_b64: list[str], pub65: bytes, nonce: bytes, roots: frozenset) -> dict:
    """roots: SPKI pins (GOOGLE_ANDROID_ROOTS unless overridden).
    -> {security_level, chain_pem, root_sha256, attestation_version}. Raises AttestationError."""
    if not isinstance(chain_b64, list) or len(chain_b64) < 2:
        raise AttestationError("enroll_bad_chain", "chain needs leaf + at least one issuer")
    try:
        certs = [x509.load_der_x509_certificate(base64.b64decode(c, validate=True)) for c in chain_b64]
    except Exception as e:  # noqa: BLE001
        raise AttestationError("enroll_bad_chain", f"cert parse: {e}") from e
    _check_path(certs, roots)
    leaf = certs[0]
    try:
        leaf_pub = pub_bytes(leaf.public_key())
    except Exception as e:  # noqa: BLE001
        raise AttestationError("enroll_key_mismatch", f"leaf key not EC: {e}") from e
    if leaf_pub != pub65:
        raise AttestationError("enroll_key_mismatch", "leaf cert key != pubkey")
    kd = _leaf_description(leaf)
    if kd["challenge"] != nonce:
        raise AttestationError("enroll_bad_challenge", "attestationChallenge != nonce")
    pem = "".join(c.public_bytes(serialization.Encoding.PEM).decode() for c in certs)
    return {
        "security_level": kd["attestation_security_level"],
        "attestation_version": kd["attestation_version"],
        "root_sha256": hashlib.sha256(certs[-1].public_bytes(serialization.Encoding.DER)).hexdigest(),
        "chain_pem": pem,
    }


def device_attested(dev: dict, roots: frozenset) -> bool:
    """Is a stored device row attested under the pins? Old android rows got attested=1 before the pin, so the
    flag alone doesn't count: their chain_pem is checked again. The enroll nonce isn't stored, so the challenge
    can't be rechecked. iOS rows were always checked against the pinned Apple root."""
    if not dev.get("attested"):
        return False
    platform = dev.get("platform")
    if platform == "ios":
        return True
    if platform != "android" or not dev.get("chain_pem"):
        return False
    try:
        certs = x509.load_pem_x509_certificates(dev["chain_pem"].encode())
        if len(certs) < 2 or pub_bytes(certs[0].public_key()).hex() != dev.get("pubkey"):
            return False
        _check_path(certs, roots)
        _leaf_description(certs[0])
    except Exception:  # noqa: BLE001
        return False
    return True
