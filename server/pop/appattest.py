"""iOS App Attest attestation, hackathon grade (contract §2.2 iOS).

The App Attest key (DCAppAttestService) is not the Secure Enclave signing key; the app cannot
choose it. The signing key is bound through clientDataHash = sha256(nonce || sha256(pubkey65)),
so the attestation proves: a genuine app instance with this appId saw this nonce and this pubkey.

Checked: fmt "apple-appattest", x5c = [credCert, intermediate] chains to the pinned Apple App
Attestation Root CA, credCert extension 1.2.840.113635.100.8.2 nonce == sha256(authData ||
clientDataHash), sha256(credCert pubkey) == keyId == credentialId, rpIdHash == sha256(appId),
signCount == 0, aaguid appattestdevelop / appattest.
NOT checked: cert validity dates, the receipt (fraud metric), revocation.
"""
from __future__ import annotations

import base64
import hashlib

import cbor2
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from pop.attestation import AttestationError, _tlv
from pop.crypto import pub_bytes

NONCE_OID = x509.ObjectIdentifier("1.2.840.113635.100.8.2")
AAGUIDS = {b"appattestdevelop": "development", b"appattest" + b"\x00" * 7: "production"}

# Apple App Attestation Root CA, https://www.apple.com/certificateauthority/Apple_App_Attestation_Root_CA.pem
# sha256(DER) 1cb9823ba28ba6ad2d33a006941de2ae4f513ef1d4e831b9f7e0fa7b6242c932
APPLE_ROOT_PEM = b"""-----BEGIN CERTIFICATE-----
MIICITCCAaegAwIBAgIQC/O+DvHN0uD7jG5yH2IXmDAKBggqhkjOPQQDAzBSMSYw
JAYDVQQDDB1BcHBsZSBBcHAgQXR0ZXN0YXRpb24gUm9vdCBDQTETMBEGA1UECgwK
QXBwbGUgSW5jLjETMBEGA1UECAwKQ2FsaWZvcm5pYTAeFw0yMDAzMTgxODMyNTNa
Fw00NTAzMTUwMDAwMDBaMFIxJjAkBgNVBAMMHUFwcGxlIEFwcCBBdHRlc3RhdGlv
biBSb290IENBMRMwEQYDVQQKDApBcHBsZSBJbmMuMRMwEQYDVQQIDApDYWxpZm9y
bmlhMHYwEAYHKoZIzj0CAQYFK4EEACIDYgAERTHhmLW07ATaFQIEVwTtT4dyctdh
NbJhFs/Ii2FdCgAHGbpphY3+d8qjuDngIN3WVhQUBHAoMeQ/cLiP1sOUtgjqK9au
Yen1mMEvRq9Sk3Jm5X8U62H+xTD3FE9TgS41o0IwQDAPBgNVHRMBAf8EBTADAQH/
MB0GA1UdDgQWBBSskRBTM72+aEH/pwyp5frq5eWKoTAOBgNVHQ8BAf8EBAMCAQYw
CgYIKoZIzj0EAwMDaAAwZQIwQgFGnByvsiVbpTKwSga0kP0e8EeDS4+sQmTvb7vn
53O5+FRXgeLhpJ06ysC5PrOyAjEAp5U4xDgEgllF7En3VcE3iexZZtKeYnpqtijV
oyFraWVIyd/dganmrduC1bmTBGwD
-----END CERTIFICATE-----
"""


def client_data_hash(nonce: bytes, pub65: bytes) -> bytes:
    return hashlib.sha256(nonce + hashlib.sha256(pub65).digest()).digest()


def parse_nonce_ext(der: bytes) -> bytes:
    """SEQUENCE { [1] EXPLICIT OCTET STRING nonce }"""
    tag, seq, _ = _tlv(der, 0)
    if tag != 0x30:
        raise ValueError("not a SEQUENCE")
    tag, inner, _ = _tlv(seq, 0)
    if tag != 0xA1:
        raise ValueError("no [1] tag")
    tag, nonce, _ = _tlv(inner, 0)
    if tag != 0x04:
        raise ValueError("no OCTET STRING")
    return nonce


def parse_auth_data(ad: bytes) -> dict:
    """rpIdHash 32 | flags 1 | signCount u32 | aaguid 16 | credIdLen u16 | credId | COSE key"""
    if len(ad) < 55:
        raise ValueError("authData too short")
    n = int.from_bytes(ad[53:55], "big")
    if len(ad) < 55 + n:
        raise ValueError("authData credentialId truncated")
    return {"rp_id_hash": ad[:32], "flags": ad[32], "sign_count": int.from_bytes(ad[33:37], "big"),
            "aaguid": ad[37:53], "credential_id": ad[55:55 + n]}


def _bad(detail: str) -> AttestationError:
    return AttestationError("enroll_bad_attestation", detail)


def verify_app_attest(attestation_b64: str, key_id_b64: str, pub65: bytes, nonce: bytes, app_id: str | None,
                      root_pem: bytes = APPLE_ROOT_PEM) -> dict:
    """-> {chain_pem, root_sha256, key_id, environment}. Raises AttestationError."""
    if not app_id:
        raise _bad("server has no POP_IOS_APP_ID")
    try:
        att = cbor2.loads(base64.b64decode(attestation_b64, validate=True))
        key_id = base64.b64decode(key_id_b64, validate=True)
    except Exception as e:  # noqa: BLE001
        raise _bad(f"decode: {e}") from e
    if not isinstance(att, dict) or att.get("fmt") != "apple-appattest":
        raise _bad("fmt != apple-appattest")
    stmt, auth_data = att.get("attStmt"), att.get("authData")
    x5c = stmt.get("x5c") if isinstance(stmt, dict) else None
    if not isinstance(auth_data, bytes) or not isinstance(x5c, list) or len(x5c) < 2:
        raise _bad("attStmt.x5c needs credCert + intermediate, authData bytes")
    try:
        certs = [x509.load_der_x509_certificate(c) for c in x5c]
        root = x509.load_pem_x509_certificate(root_pem)
    except Exception as e:  # noqa: BLE001
        raise _bad(f"cert parse: {e}") from e
    for child, issuer in zip(certs, certs[1:] + [root]):
        try:
            child.verify_directly_issued_by(issuer)
        except Exception as e:  # noqa: BLE001
            raise _bad(f"chain: {child.subject.rfc4514_string()}: {e}") from e
    cred = certs[0]
    try:
        ext = cred.extensions.get_extension_for_oid(NONCE_OID).value
        got = parse_nonce_ext(ext.value)
    except (x509.ExtensionNotFound, ValueError) as e:
        raise _bad(f"nonce extension: {e}") from e
    if got != hashlib.sha256(auth_data + client_data_hash(nonce, pub65)).digest():
        raise AttestationError("enroll_bad_challenge", "credCert nonce != sha256(authData || clientDataHash)")
    try:
        cred_pub = pub_bytes(cred.public_key())
    except Exception as e:  # noqa: BLE001
        raise _bad(f"credCert key not EC: {e}") from e
    if hashlib.sha256(cred_pub).digest() != key_id:
        raise _bad("keyId != sha256(credCert pubkey)")
    try:
        ad = parse_auth_data(auth_data)
    except ValueError as e:
        raise _bad(str(e)) from e
    if ad["rp_id_hash"] != hashlib.sha256(app_id.encode()).digest():
        raise _bad("rpIdHash != sha256(appId)")
    if ad["sign_count"] != 0:
        raise _bad("signCount != 0")
    env = AAGUIDS.get(ad["aaguid"])
    if env is None:
        raise _bad("aaguid not appattest / appattestdevelop")
    if ad["credential_id"] != key_id:
        raise _bad("credentialId != keyId")
    der = lambda c: c.public_bytes(serialization.Encoding.DER)
    return {
        "chain_pem": "".join(c.public_bytes(serialization.Encoding.PEM).decode() for c in certs),
        "root_sha256": hashlib.sha256(der(root)).hexdigest(),
        "key_id": key_id.hex(),
        "environment": env,
    }
