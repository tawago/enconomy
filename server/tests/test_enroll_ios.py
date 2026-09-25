"""iOS enroll: App Attest with a self-made chain (real Apple vectors need a paid team) and unattested SE keys."""
import base64
import datetime as dt
import hashlib

import cbor2
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from pop.appattest import APPLE_ROOT_PEM, NONCE_OID, client_data_hash, parse_nonce_ext
from pop.crypto import pub_bytes
from tests.phones import Phone, _der

APP_ID = "ABCDE12345.com.enconomy.pop"
DEV_AAGUID = b"appattestdevelop"


def _cert(cn, pub, issuer_cn, issuer_sk, ext=None, ca=False):
    now = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    b = (x509.CertificateBuilder()
         .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)]))
         .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer_cn)]))
         .public_key(pub).serial_number(x509.random_serial_number())
         .not_valid_before(now).not_valid_after(now + dt.timedelta(days=3650))
         .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
    if ext is not None:
        b = b.add_extension(x509.UnrecognizedExtension(NONCE_OID, ext), critical=False)
    return b.sign(issuer_sk, hashes.SHA384() if ca else hashes.SHA256())


class FakeApple:
    """Root + intermediate standing in for Apple's App Attestation CA."""

    def __init__(self):
        self.root_sk, self.inter_sk = ec.generate_private_key(ec.SECP384R1()), ec.generate_private_key(ec.SECP384R1())
        self.root = _cert("Fake App Attestation Root CA", self.root_sk.public_key(), "Fake App Attestation Root CA",
                          self.root_sk, ca=True)
        self.inter = _cert("Fake App Attestation CA 1", self.inter_sk.public_key(), "Fake App Attestation Root CA",
                           self.root_sk, ca=True)

    @property
    def root_pem(self) -> bytes:
        return self.root.public_bytes(serialization.Encoding.PEM)

    def attest(self, nonce: bytes, pub65: bytes, app_id: str = APP_ID, aaguid: bytes = DEV_AAGUID, counter: int = 0,
               fmt: str = "apple-appattest", tamper_nonce: bool = False, cred_id: bytes | None = None,
               inter_sk=None, with_ext: bool = True) -> dict:
        """-> app_attest body {key_id, attestation} as DCAppAttestService would hand the app."""
        att_sk = ec.generate_private_key(ec.SECP256R1())  # the App Attest key, not the signing key
        key_id = hashlib.sha256(pub_bytes(att_sk.public_key())).digest()
        cid = key_id if cred_id is None else cred_id
        auth_data = (hashlib.sha256(app_id.encode()).digest() + b"\x40" + counter.to_bytes(4, "big") + aaguid
                     + len(cid).to_bytes(2, "big") + cid + cbor2.dumps({1: 2, 3: -7}))
        n = hashlib.sha256(auth_data + client_data_hash(nonce, pub65)).digest()
        if tamper_nonce:
            n = bytes([n[0] ^ 1]) + n[1:]
        ext = _der(0x30, _der(0xA1, _der(0x04, n))) if with_ext else None
        cred = _cert("cred", att_sk.public_key(), "Fake App Attestation CA 1", inter_sk or self.inter_sk, ext=ext)
        der = lambda c: c.public_bytes(serialization.Encoding.DER)
        att = {"fmt": fmt, "attStmt": {"x5c": [der(cred), der(self.inter)], "receipt": b"r"}, "authData": auth_data}
        return {"key_id": base64.b64encode(key_id).decode(), "attestation": base64.b64encode(cbor2.dumps(att)).decode()}


@pytest.fixture
def apple():
    return FakeApple()


@pytest.fixture
def ios_client(make_client, apple):
    return make_client(ios_app_id=APP_ID, ios_root_pem=apple.root_pem)


def _nonce(client):
    return client.get("/v1/enroll/nonce").json()["nonce"]


def _body(p: Phone, nonce: str, app_attest: dict | None, key_kind: str = "secure_enclave") -> dict:
    return {**p.enroll_body(nonce, None, level=key_kind), "model": "iPhone16,1", "platform": "ios",
            "key_kind": key_kind, "app_attest": app_attest}


def test_apple_root_embedded():
    root = x509.load_pem_x509_certificate(APPLE_ROOT_PEM)
    root.verify_directly_issued_by(root)
    assert root.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == "Apple App Attestation Root CA"
    assert hashlib.sha256(root.public_bytes(serialization.Encoding.DER)).hexdigest() == \
        "1cb9823ba28ba6ad2d33a006941de2ae4f513ef1d4e831b9f7e0fa7b6242c932"


def test_nonce_ext_parse():
    assert parse_nonce_ext(_der(0x30, _der(0xA1, _der(0x04, b"\x07" * 32)))) == b"\x07" * 32


def test_client_data_hash_definition():
    n, pub = bytes(range(32)), b"\x04" + bytes(64)
    assert client_data_hash(n, pub) == hashlib.sha256(n + hashlib.sha256(pub).digest()).digest()


def test_ios_app_attest_ok(ios_client, clock, apple):
    p = Phone(ios_client, clock, "Ivy")
    n = _nonce(ios_client)
    aa = apple.attest(bytes.fromhex(n), p.pub)
    r = ios_client.post("/v1/enroll", json=_body(p, n, aa))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["attested"] is True and j["platform"] == "ios" and j["key_kind"] == "secure_enclave"
    dev = ios_client.app.state.store.get_device(p.device_id)
    assert dev["platform"] == "ios" and dev["attest_key_id"] == base64.b64decode(aa["key_id"]).hex()
    assert dev["chain_pem"].count("BEGIN CERTIFICATE") == 2
    assert dev["root_sha256"] == hashlib.sha256(apple.root.public_bytes(serialization.Encoding.DER)).hexdigest()
    # enrolled key signs requests like any other device
    assert p.post("/v1/session").status_code == 200


def test_ios_production_aaguid(ios_client, clock, apple):
    p = Phone(ios_client, clock)
    n = _nonce(ios_client)
    r = ios_client.post("/v1/enroll", json=_body(p, n, apple.attest(bytes.fromhex(n), p.pub, aaguid=b"appattest" + bytes(7))))
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("case,code", [
    ("wrong_nonce", "enroll_bad_challenge"),
    ("other_pubkey", "enroll_bad_challenge"),
    ("tampered_nonce", "enroll_bad_challenge"),
    ("wrong_app_id", "enroll_bad_attestation"),
    ("bad_aaguid", "enroll_bad_attestation"),
    ("counter", "enroll_bad_attestation"),
    ("fmt", "enroll_bad_attestation"),
    ("cred_id", "enroll_bad_attestation"),
    ("key_id", "enroll_bad_attestation"),
    ("other_root", "enroll_bad_attestation"),
    ("no_extension", "enroll_bad_attestation"),
    ("garbage", "enroll_bad_attestation"),
])
def test_ios_app_attest_rejects(ios_client, clock, apple, case, code):
    p = Phone(ios_client, clock)
    n = _nonce(ios_client)
    nb = bytes.fromhex(n)
    other = pub_bytes(ec.generate_private_key(ec.SECP256R1()).public_key())
    aa = {
        "wrong_nonce": lambda: apple.attest(b"\x00" * 32, p.pub),
        "other_pubkey": lambda: apple.attest(nb, other),
        "tampered_nonce": lambda: apple.attest(nb, p.pub, tamper_nonce=True),
        "wrong_app_id": lambda: apple.attest(nb, p.pub, app_id="OTHER12345.com.enconomy.pop"),
        "bad_aaguid": lambda: apple.attest(nb, p.pub, aaguid=b"x" * 16),
        "counter": lambda: apple.attest(nb, p.pub, counter=1),
        "fmt": lambda: apple.attest(nb, p.pub, fmt="packed"),
        "cred_id": lambda: apple.attest(nb, p.pub, cred_id=b"\x01" * 32),
        "key_id": lambda: {**apple.attest(nb, p.pub), "key_id": base64.b64encode(b"\x02" * 32).decode()},
        "other_root": lambda: apple.attest(nb, p.pub, inter_sk=ec.generate_private_key(ec.SECP384R1())),
        "no_extension": lambda: apple.attest(nb, p.pub, with_ext=False),
        "garbage": lambda: {"key_id": "AAAA", "attestation": "bm90IGNib3I="},
    }[case]()
    r = ios_client.post("/v1/enroll", json=_body(p, n, aa))
    assert r.status_code == 400 and r.json()["error"] == code, r.text
    assert ios_client.app.state.store.get_device(p.device_id) is None


def test_ios_real_apple_root_rejects_fake_chain(make_client, clock, apple):
    c = make_client(ios_app_id=APP_ID)  # default root = Apple's
    p = Phone(c, clock)
    n = _nonce(c)
    r = c.post("/v1/enroll", json=_body(p, n, apple.attest(bytes.fromhex(n), p.pub)))
    assert r.status_code == 400 and r.json()["error"] == "enroll_bad_attestation"


def test_ios_no_app_id_configured(make_client, clock, apple):
    c = make_client(ios_root_pem=apple.root_pem)
    p = Phone(c, clock)
    n = _nonce(c)
    r = c.post("/v1/enroll", json=_body(p, n, apple.attest(bytes.fromhex(n), p.pub)))
    assert r.status_code == 400 and "POP_IOS_APP_ID" in r.json()["detail"]


def test_ios_nonce_single_use(ios_client, clock, apple):
    p = Phone(ios_client, clock)
    n = _nonce(ios_client)
    aa = apple.attest(bytes.fromhex(n), p.pub)
    assert ios_client.post("/v1/enroll", json=_body(p, n, aa)).status_code == 200
    r = ios_client.post("/v1/enroll", json=_body(p, n, aa))
    assert r.status_code == 400 and r.json()["error"] == "enroll_bad_nonce"


def test_ios_unattested_rejected_by_default(ios_client, clock):
    p = Phone(ios_client, clock)
    r = ios_client.post("/v1/enroll", json=_body(p, _nonce(ios_client), None))
    assert r.status_code == 400 and r.json()["error"] == "enroll_bad_attestation"


@pytest.mark.parametrize("kind,want", [("secure_enclave", "secure_enclave"), ("software", "software"), ("tee", "unknown")])
def test_ios_unattested_allowed_with_flag(make_client, clock, kind, want):
    c = make_client(allow_unattested=True)
    p = Phone(c, clock)
    r = c.post("/v1/enroll", json=_body(p, _nonce(c), None, key_kind=kind))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["attested"] is False and j["key_kind"] == want and j["security_level"] == want
    dev = c.app.state.store.get_device(p.device_id)
    assert dev["platform"] == "ios" and dev["attested"] is False and dev["key_kind"] == want


def test_ios_unattested_wrong_nonce(make_client, clock):
    c = make_client(allow_unattested=True)
    r = c.post("/v1/enroll", json=_body(Phone(c, clock), "ab" * 32, None))
    assert r.status_code == 400 and r.json()["error"] == "enroll_bad_nonce"


def test_ios_chain_field_refused(make_client, clock):
    c = make_client(allow_unattested=True)
    p = Phone(c, clock)
    body = {**_body(p, _nonce(c), None), "chain": ["AAAA"]}
    assert c.post("/v1/enroll", json=body).json()["error"] == "bad_request"


def test_unknown_platform(make_client, clock):
    c = make_client(allow_unattested=True)
    p = Phone(c, clock)
    body = {**_body(p, _nonce(c), None), "platform": "symbian"}
    assert c.post("/v1/enroll", json=body).json()["error"] == "bad_request"


def test_android_default_platform(client, clock):
    p = Phone(client, clock)
    assert p.enroll().json()["platform"] == "android"
    assert client.app.state.store.get_device(p.device_id)["key_kind"] == "android_keystore"


def test_old_db_migrates(tmp_path):
    import sqlite3
    from pop.store import SqliteStore
    path = tmp_path / "old.sqlite"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE devices (device_id TEXT PRIMARY KEY, pubkey TEXT NOT NULL, display_name TEXT NOT NULL, "
               "model TEXT NOT NULL, security_level TEXT NOT NULL, security_level_reported TEXT NOT NULL, "
               "attested INTEGER NOT NULL, chain_pem TEXT, root_sha256 TEXT, enrolled_at TEXT NOT NULL)")
    db.execute("INSERT INTO devices VALUES ('d', 'p', 'n', 'm', 'tee', 'tee', 1, NULL, NULL, 't')")
    db.commit()
    db.close()
    assert SqliteStore(path).get_device("d")["platform"] == "android"
