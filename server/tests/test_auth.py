import base64

from cryptography.hazmat.primitives.asymmetric import ec

from pop.crypto import sign_raw, verify_raw
from tests.phones import Phone


def test_raw_sig_roundtrip():
    sk = ec.generate_private_key(ec.SECP256R1())
    from pop.crypto import pub_bytes
    pub = pub_bytes(sk.public_key())
    sig = sign_raw(sk, b"hello")
    assert len(sig) == 64 and verify_raw(pub, b"hello", sig) and not verify_raw(pub, b"hellO", sig)


def test_good(phones):
    a, _ = phones
    assert a.post("/v1/session").status_code == 200


def test_missing_headers(client, phones):
    r = client.post("/v1/session", json={})
    assert r.status_code == 401 and r.json()["error"] == "auth_bad_signature"


def test_unknown_device(client, clock):
    p = Phone(client, clock)  # never enrolled
    r = p.post("/v1/session")
    assert r.status_code == 401 and r.json()["error"] == "auth_unknown_device"


def test_stale(phones, clock):
    a, _ = phones
    for dt in (-61_000, 61_000):
        r = a.post("/v1/session", ts=clock() + dt)
        assert r.status_code == 401 and r.json()["error"] == "auth_stale"
    assert a.post("/v1/session", ts=clock() - 59_000).status_code == 200


def test_replay(phones):
    a, _ = phones
    raw = b"{}"
    h = a.headers("POST", "/v1/session", raw)
    assert a.client.post("/v1/session", content=raw, headers=h).status_code == 200
    r = a.client.post("/v1/session", content=raw, headers=h)
    assert r.status_code == 401 and r.json()["error"] == "auth_replay"


def test_replay_cache_expires_but_ts_goes_stale_first(phones, clock):
    a, _ = phones
    raw = b"{}"
    h = a.headers("POST", "/v1/session", raw)
    assert a.client.post("/v1/session", content=raw, headers=h).status_code == 200
    clock.advance(121)
    assert a.client.post("/v1/session", content=raw, headers=h).json()["error"] == "auth_stale"


def test_wrong_key(phones):
    a, _ = phones
    other = ec.generate_private_key(ec.SECP256R1())
    r = a.post("/v1/session", sk=other)
    assert r.status_code == 401 and r.json()["error"] == "auth_bad_signature"


def test_tampered_body(phones):
    a, _ = phones
    sid = a.post("/v1/session").json()["session_id"]
    h = a.headers("POST", f"/v1/session/{sid}/abort", b"{}")
    r = a.client.post(f"/v1/session/{sid}/abort", content=b'{"x":1}', headers=h)
    assert r.json()["error"] == "auth_bad_signature"


def test_query_is_signed(phones):
    a, _ = phones
    sid = a.post("/v1/session").json()["session_id"]
    path = f"/v1/session/{sid}"
    h = a.headers("GET", path + "?after=0", b"")
    r = a.client.get(path + "?after=5", headers=h)
    assert r.json()["error"] == "auth_bad_signature"
    h = a.headers("GET", path + "?after=0&timeout_s=0", b"")
    assert a.client.get(path + "?after=0&timeout_s=0", headers=h).status_code == 200


def test_bad_sig_encoding(phones):
    a, _ = phones
    h = a.headers("POST", "/v1/session", b"{}")
    h["X-Pop-Sig"] = "!!!"
    assert a.client.post("/v1/session", content=b"{}", headers=h).json()["error"] == "auth_bad_signature"
    h["X-Pop-Sig"] = base64.b64encode(b"\x00" * 64).decode()
    assert a.client.post("/v1/session", content=b"{}", headers=h).json()["error"] == "auth_bad_signature"
