import base64
import json
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from pop.attestation import GOOGLE_ANDROID_ROOTS, device_attested, parse_key_description, roots_from_pem, spki_sha256
from pop.main import Settings
from tests.phones import TEST_ANDROID_ROOTS, TEST_ROOT_SK, Phone, _cert, b64_cert, key_description, make_chain

ROOTS_JSON = Path(__file__).parent / "fixtures" / "google-attestation-roots.json"


def _nonce(client):
    return client.get("/v1/enroll/nonce").json()["nonce"]


def test_key_description_roundtrip():
    kd = parse_key_description(key_description(b"\x01" * 32, level=2))
    assert kd["challenge"] == b"\x01" * 32 and kd["attestation_security_level"] == "strongbox"


def test_enroll_attested(client, clock):
    p = Phone(client, clock)
    r = p.enroll()
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["device_id"] == p.device_id and j["attested"] is True and j["security_level"] == "tee"
    assert client.app.state.store.get_device(p.device_id)["chain_pem"].count("BEGIN CERTIFICATE") == 3


def test_enroll_level_from_attestation(client, clock):
    p = Phone(client, clock)
    n = _nonce(client)
    chain = make_chain(p.sk.public_key(), bytes.fromhex(n), level=2)
    r = client.post("/v1/enroll", json=p.enroll_body(n, chain, level="software"))
    assert r.json()["security_level"] == "strongbox"


@pytest.mark.parametrize("case,code", [
    ("wrong_challenge", "enroll_bad_challenge"),
    ("other_leaf_key", "enroll_key_mismatch"),
    ("broken_link", "enroll_bad_chain"),
    ("no_extension", "enroll_bad_chain"),
    ("leaf_only", "enroll_bad_chain"),
    ("garbage", "enroll_bad_chain"),
])
def test_enroll_bad_chain(client, clock, case, code):
    p = Phone(client, clock)
    n = _nonce(client)
    nb = bytes.fromhex(n)
    chain = {
        "wrong_challenge": lambda: make_chain(p.sk.public_key(), b"\x00" * 32),
        "other_leaf_key": lambda: make_chain(ec.generate_private_key(ec.SECP256R1()).public_key(), nb),
        "broken_link": lambda: make_chain(p.sk.public_key(), nb, break_link=True),
        "no_extension": lambda: make_chain(p.sk.public_key(), nb, with_ext=False),
        "leaf_only": lambda: make_chain(p.sk.public_key(), nb)[:1],
        "garbage": lambda: ["bm90IGEgY2VydA==", "AAAA"],
    }[case]()
    r = client.post("/v1/enroll", json=p.enroll_body(n, chain))
    assert r.status_code == 400 and r.json()["error"] == code, r.text
    assert client.app.state.store.get_device(p.device_id) is None


def test_enroll_device_id_mismatch(client, clock):
    p = Phone(client, clock)
    n = _nonce(client)
    body = p.enroll_body(n, make_chain(p.sk.public_key(), bytes.fromhex(n)))
    body["device_id"] = "00" * 16
    r = client.post("/v1/enroll", json=body)
    assert r.status_code == 400 and r.json()["error"] == "enroll_key_mismatch"


def test_enroll_bad_pubkey(client, clock):
    p = Phone(client, clock)
    body = p.enroll_body(_nonce(client), None)
    body["pubkey"] = "04" + "00" * 64
    r = client.post("/v1/enroll", json=body)
    assert r.json()["error"] == "enroll_key_mismatch"


def test_nonce_single_use(client, clock):
    p = Phone(client, clock)
    n = _nonce(client)
    chain = make_chain(p.sk.public_key(), bytes.fromhex(n))
    assert client.post("/v1/enroll", json=p.enroll_body(n, chain)).status_code == 200
    r = client.post("/v1/enroll", json=p.enroll_body(n, chain))
    assert r.status_code == 400 and r.json()["error"] == "enroll_bad_nonce"


def test_nonce_expired(client, clock):
    p = Phone(client, clock)
    n = _nonce(client)
    clock.advance(601)
    r = client.post("/v1/enroll", json=p.enroll_body(n, make_chain(p.sk.public_key(), bytes.fromhex(n))))
    assert r.json()["error"] == "enroll_bad_nonce"


def test_nonce_unknown(client, clock):
    p = Phone(client, clock)
    r = client.post("/v1/enroll", json=p.enroll_body("ab" * 32, None))
    assert r.json()["error"] == "enroll_bad_nonce"


def test_unattested_rejected_by_default(client, clock):
    r = Phone(client, clock).enroll(attested=False)
    assert r.status_code == 400 and r.json()["error"] == "enroll_bad_chain"


def test_unattested_allowed_with_flag(make_client, clock):
    c = make_client(allow_unattested=True)
    assert c.get("/v1/config").json()["allow_unattested"] is True
    r = Phone(c, clock).enroll(attested=False)
    assert r.status_code == 200 and r.json()["attested"] is False and r.json()["security_level"] == "tee"


def test_reenroll_same_key_replaces(client, clock):
    p = Phone(client, clock, name="first")
    assert p.enroll().status_code == 200
    p.name = "second"
    assert p.enroll().status_code == 200
    assert client.app.state.store.get_device(p.device_id)["display_name"] == "second"


@pytest.mark.parametrize("name", ["", "   ", "x" * 33])
def test_display_name_bounds(client, clock, name):
    r = Phone(client, clock, name=name).enroll()
    assert r.status_code == 400 and r.json()["error"] == "bad_request"


# -- Google root pin

def _pem(chain: list[str]) -> str:
    certs = [x509.load_der_x509_certificate(base64.b64decode(c)) for c in chain]
    return "".join(c.public_bytes(serialization.Encoding.PEM).decode() for c in certs)


def _refused(client, p, n, chain, detail):
    r = client.post("/v1/enroll", json=p.enroll_body(n, chain))
    assert r.status_code == 400 and r.json()["error"] == "enroll_bad_chain" and detail in r.json()["detail"], r.text
    assert client.app.state.store.get_device(p.device_id) is None


def test_pins_are_the_published_roots():
    pems = json.loads(ROOTS_JSON.read_text())
    assert len(pems) == 2
    for pem in pems:
        c = x509.load_pem_x509_certificate(pem.encode())
        c.verify_directly_issued_by(c)
    assert frozenset().union(*(roots_from_pem(p.encode()) for p in pems)) == GOOGLE_ANDROID_ROOTS


def test_unknown_root_refused(client, clock):
    p = Phone(client, clock)
    n = _nonce(client)
    chain = make_chain(p.sk.public_key(), bytes.fromhex(n), root_sk=ec.generate_private_key(ec.SECP256R1()))
    _refused(client, p, n, chain, "not pinned")


@pytest.mark.parametrize("allow", [False, True])
def test_google_pins_refuse_test_chain(make_client, clock, allow):
    c = make_client(allow_unattested=allow, android_roots=GOOGLE_ANDROID_ROOTS)
    p = Phone(c, clock)
    n = _nonce(c)
    _refused(c, p, n, make_chain(p.sk.public_key(), bytes.fromhex(n)), "not pinned")


def test_google_pins_keep_unattested_path(make_client, clock):
    c = make_client(allow_unattested=True, android_roots=GOOGLE_ANDROID_ROOTS)
    r = Phone(c, clock).enroll(attested=False)
    assert r.status_code == 200 and r.json()["attested"] is False


def test_pinned_key_in_a_cert_signed_by_someone_else_refused(client, clock):
    """Only the last cert's key is pinned, so its own signature doesn't matter: nothing below it can verify."""
    p = Phone(client, clock)
    n = _nonce(client)
    evil = ec.generate_private_key(ec.SECP256R1())
    root = _cert("Fake Root", TEST_ROOT_SK.public_key(), "Fake Root", evil, ca=True)
    inter_sk = ec.generate_private_key(ec.SECP256R1())
    inter = _cert("Fake Inter", inter_sk.public_key(), "Fake Root", evil, ca=True)
    leaf = _cert("Android Keystore Key", p.sk.public_key(), "Fake Inter", inter_sk, ext=key_description(bytes.fromhex(n)))
    _refused(client, p, n, [b64_cert(x) for x in (leaf, inter, root)], "signature")


def test_forged_child_under_a_real_leaf_refused(client, clock):
    """A real phone signs a cert for another key with its own attested key, which the app controls."""
    real = Phone(client, clock, "real")
    fake = Phone(client, clock, "fake")
    n = _nonce(client)
    nb = bytes.fromhex(n)
    chain = make_chain(real.sk.public_key(), nb)
    child = _cert("Forged", fake.sk.public_key(), "Android Keystore Key", real.sk, ext=key_description(nb))
    _refused(client, fake, n, [b64_cert(child), *chain], "not a CA")


@pytest.mark.parametrize("kw,detail", [
    ({"inter_ca": False}, "not a CA"),
    ({"inter_ca": None}, "not a CA"),
    ({"inter_ext": key_description(b"\x01" * 32)}, "KeyDescription above the leaf"),
])
def test_bad_intermediate_refused(client, clock, kw, detail):
    p = Phone(client, clock)
    n = _nonce(client)
    _refused(client, p, n, make_chain(p.sk.public_key(), bytes.fromhex(n), **kw), detail)


@pytest.mark.parametrize("level", [0, 3])
def test_non_hardware_level_refused(client, clock, level):
    p = Phone(client, clock)
    n = _nonce(client)
    _refused(client, p, n, make_chain(p.sk.public_key(), bytes.fromhex(n), level=level), "attestation level")


def test_android_root_pem_override(tmp_path, monkeypatch):
    sk = ec.generate_private_key(ec.SECP256R1())
    cert = _cert("Other Root", sk.public_key(), "Other Root", sk, ca=True)
    path = tmp_path / "root.pem"
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    monkeypatch.delenv("POP_ANDROID_ROOT_PEM", raising=False)
    assert Settings().android_roots == GOOGLE_ANDROID_ROOTS
    monkeypatch.setenv("POP_ANDROID_ROOT_PEM", str(path))
    assert Settings().android_roots == frozenset({spki_sha256(cert)})


# -- stored rows

def _row(client, clock):
    p = Phone(client, clock)
    assert p.enroll().status_code == 200
    return p, client.app.state.store.get_device(p.device_id)


def test_row_enrolled_under_the_pin_is_attested(client, clock):
    _, row = _row(client, clock)
    assert row["attested"] is True and device_attested(row, TEST_ANDROID_ROOTS)


def test_old_row_from_before_the_pin_not_attested(client, clock):
    """attested=1 in an old pop.sqlite, chain from a root nobody pinned, read back through the store."""
    p, row = _row(client, clock)
    store = client.app.state.store
    chain = make_chain(p.sk.public_key(), b"\x00" * 32, root_sk=ec.generate_private_key(ec.SECP256R1()))
    store.put_device({**row, "chain_pem": _pem(chain)})
    old = store.get_device(p.device_id)
    assert old["attested"] is True and not device_attested(old, TEST_ANDROID_ROOTS)


def test_row_under_test_root_not_attested_under_google_pins(client, clock):
    _, row = _row(client, clock)
    assert not device_attested(row, GOOGLE_ANDROID_ROOTS)


def test_old_row_with_forged_child_not_attested(client, clock):
    real, row = _row(client, clock)
    fake = Phone(client, clock, "fake")
    chain = make_chain(real.sk.public_key(), b"\x00" * 32)
    child = _cert("Forged", fake.sk.public_key(), "Android Keystore Key", real.sk, ext=key_description(b"\x00" * 32))
    forged = {**row, "pubkey": fake.pub.hex(), "chain_pem": _pem([b64_cert(child), *chain])}
    assert not device_attested(forged, TEST_ANDROID_ROOTS)


@pytest.mark.parametrize("change,want", [
    ({"pubkey": "04" + "00" * 64}, False),
    ({"attested": False}, False),
    ({"chain_pem": None}, False),
    ({"chain_pem": "not a cert"}, False),
    ({"platform": "web"}, False),
    ({"platform": "ios", "chain_pem": None}, True),
    ({"platform": "ios", "attested": False}, False),
])
def test_device_attested_table(client, clock, change, want):
    _, row = _row(client, clock)
    assert device_attested({**row, **change}, TEST_ANDROID_ROOTS) is want
