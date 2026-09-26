"""ENS name claims (pop/ens.py): one label per device, no renames, labels unique, unsigned refused."""
from tests.phones import Phone, make_chain


def _enrolled(client, clock, name="phone"):
    p = Phone(client, clock, name)
    n = client.get("/v1/enroll/nonce").json()["nonce"]
    assert client.post("/v1/enroll", json=p.enroll_body(n, make_chain(p.sk.public_key(), bytes.fromhex(n)))).status_code == 200
    return p


def test_claim_once(client, clock):
    p = _enrolled(client, clock)
    assert p.get("/v1/device/ens").json() == {"label": None, "name": None, "status": "none", "tx": None}
    r = p.post("/v1/device/ens", {"label": "carol"})
    assert r.status_code == 200, r.text
    assert r.json() == {"label": "carol", "name": "carol.enconomy.eth", "status": "pending", "tx": None}
    assert p.get("/v1/device/ens").json()["label"] == "carol"
    again = p.post("/v1/device/ens", {"label": "dave"})
    assert again.status_code == 409 and again.json()["error"] == "already_claimed"
    assert p.get("/v1/device/ens").json()["label"] == "carol"


def test_label_taken(client, clock):
    a, b = _enrolled(client, clock, "a"), _enrolled(client, clock, "b")
    assert a.post("/v1/device/ens", {"label": "carol"}).status_code == 200
    r = b.post("/v1/device/ens", {"label": "carol"})
    assert r.status_code == 409 and r.json()["error"] == "label_taken"
    assert b.post("/v1/device/ens", {"label": "erin"}).status_code == 200


def test_bad_label_and_unsigned(client, clock):
    p = _enrolled(client, clock)
    for label in ("ab", "Alice", "a.b", "x" * 33, None, 5):
        r = p.post("/v1/device/ens", {"label": label})
        assert r.status_code == 400 and r.json()["error"] == "bad_label", label
    assert client.post("/v1/device/ens", json={"label": "carol"}).status_code == 401
    assert client.get("/v1/device/ens").status_code == 401


def test_failed_claim_can_retry(client, clock):
    p = _enrolled(client, clock)
    assert p.post("/v1/device/ens", {"label": "carol"}).status_code == 200
    client.app.state.store._db.execute("UPDATE ens_names SET status = 'failed'")   # what the bridge writes
    r = p.post("/v1/device/ens", {"label": "carla"})
    assert r.status_code == 200 and r.json()["label"] == "carla" and r.json()["status"] == "pending"
