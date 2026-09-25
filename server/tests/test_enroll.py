import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from pop.attestation import parse_key_description
from tests.phones import Phone, key_description, make_chain


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
