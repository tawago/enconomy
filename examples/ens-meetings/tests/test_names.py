"""Name claims: the four cases from the core's old test_ens, then the checks a signed claim adds."""
import base64

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from backend.main import SKEW_MS
from tests.helpers import Phone, settled, sign_raw, wait_for

N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551


def test_claim_once(client, clock):
    p = Phone(client, clock)
    assert p.read().json() == {"label": None, "name": None, "status": "none", "tx": None}
    r = p.claim("carol")
    assert r.status_code == 200, r.text
    assert r.json() == {"label": "carol", "name": "carol.enconomy.eth", "status": "pending", "tx": None}
    assert p.read().json()["label"] == "carol"
    again = p.claim("dave")
    assert again.status_code == 409 and again.json()["error"] == "already_claimed"
    assert p.read().json()["label"] == "carol"


def test_label_taken(client, clock):
    a, b = Phone(client, clock), Phone(client, clock)
    assert a.claim("carol").status_code == 200
    r = b.claim("carol")
    assert r.status_code == 409 and r.json()["error"] == "label_taken"
    assert b.claim("erin").status_code == 200


def test_bad_label_and_unsigned(client, clock):
    p = Phone(client, clock)
    for label in ("ab", "Alice", "a.b", "x" * 33, None, 5):
        r = p.claim(label)
        assert r.status_code == 400 and r.json()["error"] == "bad_label", label
    assert client.post("/v1/names/claim", json={"label": "carol"}).status_code == 401
    assert client.post("/v1/names/read", json={}).status_code == 401


def test_failed_claim_can_retry(client, clock, chain):
    p = Phone(client, clock)
    chain.fail = "boom"
    assert p.claim("carol").status_code == 200
    wait_for(lambda: p.read().json()["status"] == "failed")
    chain.fail = None
    r = p.claim("carla")
    assert r.status_code == 200 and r.json()["label"] == "carla" and r.json()["status"] == "pending"


def test_failed_retry_onto_a_taken_label_keeps_the_row(client, clock, chain):
    a, b = Phone(client, clock), Phone(client, clock)
    assert a.claim("erin").status_code == 200
    wait_for(lambda: settled(client.app))
    chain.fail = "boom"
    assert b.claim("carol").status_code == 200
    wait_for(lambda: b.read().json()["status"] == "failed")
    assert b.claim("erin").json()["error"] == "label_taken"
    assert b.read().json()["label"] == "carol"


def test_web_and_unattested_refused(client, clock, chain):
    web = Phone(client, clock, platform="web", attested=False)
    r = web.claim("webby")
    assert r.status_code == 403 and r.json()["error"] == "not_allowed"
    un = Phone(client, clock, attested=False)
    r = un.claim("nobody")
    assert r.status_code == 403 and r.json()["error"] == "not_attested"
    odd = Phone(client, clock, platform="desktop")   # only phones, even if something says attested
    assert odd.claim("oddone").status_code == 403
    assert not client.app.state.store.names_with_status("pending") and not chain.calls


def test_web_is_refused_before_the_label_is_looked_at(client, clock):
    r = Phone(client, clock, platform="web", attested=False).claim("x")
    assert r.status_code == 403 and r.json()["error"] == "not_allowed"


def test_foreign_key_statement_refused(client, clock, chain):
    p = Phone(client, clock, core_key=ec.generate_private_key(ec.SECP256R1()))
    r = p.claim("carol")
    assert r.status_code == 401 and r.json()["error"] == "bad_statement"
    assert not chain.calls


def test_tampered_statement_refused(client, clock):
    p = Phone(client, clock, attested=False)
    st = p.statement()
    st["body"]["attested"] = True
    r = p.claim("carol", statement=st)
    assert r.status_code == 401 and r.json()["error"] == "bad_statement"


def test_statement_checks(client, clock, settings):
    p = Phone(client, clock)
    max_ms = settings.statement_max_age_s * 1000
    for over, code in (({"format": "other"}, "bad_statement"),
                       ({"issued_at_ms": clock.ms - max_ms - 1000}, "statement_stale"),
                       ({"issued_at_ms": clock.ms + 10 * SKEW_MS}, "statement_stale"),
                       ({"issued_at_ms": str(clock.ms)}, "statement_stale"),
                       ({"pubkey": "zz"}, "bad_statement"),
                       ({"device_id": "0" * 32}, "bad_statement")):
        r = p.claim("carol", statement=p.statement(**over))
        assert r.status_code == 401 and r.json()["error"] == code, over


def test_someone_elses_statement_refused(client, clock):
    """A statement is not secret, so it proves nothing without that device's signature."""
    victim, thief = Phone(client, clock), Phone(client, clock)
    req = thief.signed("carol", statement=victim.statement())
    r = client.post("/v1/names/claim", json=req)
    assert r.status_code == 401 and r.json()["error"] == "auth_bad_signature"


def test_signature_covers_label_and_ts(client, clock):
    p = Phone(client, clock)
    req = p.signed("carol")
    assert client.post("/v1/names/claim", json={**req, "label": "carla"}).json()["error"] == "auth_bad_signature"
    assert client.post("/v1/names/claim", json={**req, "ts": req["ts"] + 1}).json()["error"] == "auth_bad_signature"
    for ts in ("1", 1.5, True, None):
        assert client.post("/v1/names/claim", json={**req, "ts": ts}).json()["error"] == "auth_bad_signature"


def test_read_signature_cannot_claim_and_core_request_tag_refused(client, clock):
    p = Phone(client, clock)
    read = p.signed(None)
    assert client.post("/v1/names/claim", json={**read, "label": "carol"}).json()["error"] == "auth_bad_signature"
    ts = clock()
    core_style = "\n".join(["pop-req-v1", "POST", "/v1/names/claim", "0" * 64, str(ts)]).encode()
    sig = base64.b64encode(sign_raw(p.sk, core_style)).decode()
    r = client.post("/v1/names/claim", json={"device_statement": p.statement(), "label": "carol", "ts": ts, "sig_b64": sig})
    assert r.json()["error"] == "auth_bad_signature"


def test_skew_and_replay(client, clock, chain):
    p = Phone(client, clock)
    assert p.claim("carol", ts=clock.ms - SKEW_MS - 5000).json()["error"] == "auth_stale"
    assert p.claim("carol", ts=clock.ms + SKEW_MS + 5000).json()["error"] == "auth_stale"
    req = p.signed("carol")
    assert client.post("/v1/names/claim", json=req).status_code == 200
    assert client.post("/v1/names/claim", json=req).json()["error"] == "auth_replay"
    # the same signature with s flipped is valid too, and still a replay
    raw = base64.b64decode(req["sig_b64"])
    flipped = raw[:32] + (N - int.from_bytes(raw[32:], "big")).to_bytes(32, "big")
    r = client.post("/v1/names/claim", json={**req, "sig_b64": base64.b64encode(flipped).decode()})
    assert r.json()["error"] == "auth_replay"


def test_check_order(client, clock):
    """Signature problems answer before anything about the name, so nobody learns labels unsigned."""
    a, b = Phone(client, clock), Phone(client, clock)
    assert a.claim("carol").status_code == 200
    req = b.signed("carol")
    r = client.post("/v1/names/claim", json={**req, "sig_b64": base64.b64encode(b"\0" * 64).decode()})
    assert r.status_code == 401
    assert b.claim("carol").json()["error"] == "label_taken"


@pytest.mark.parametrize("raw", [b"not json", b"[]", b"5"])
def test_bad_bodies(client, raw):
    for path in ("/v1/names/claim", "/v1/names/read", "/v1/presence"):
        assert client.post(path, content=raw).status_code == 400
