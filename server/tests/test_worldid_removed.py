"""World ID left the core for examples/world-id. A session needs no human data, and the core keeps none."""
from tests.phones import Phone
from tests.sim import Knobs, World

GONE = {"policy", "human", "pair_tag"}


def test_routes_are_gone(client, clock):
    p = Phone(client, clock)
    assert p.enroll().status_code == 200
    sid = p.post("/v1/session").json()["session_id"]
    assert p.post(f"/v1/session/{sid}/worldid/start").status_code == 404
    assert p.get(f"/v1/session/{sid}/worldid").status_code == 404


def test_health_and_config_have_no_worldid(client):
    assert "worldid" not in client.get("/health").json()
    assert "worldid" not in client.get("/v1/config").json()


def test_session_runs_with_no_worldid(client, clock):
    """An old client's policy is ignored like any unknown key, so it arms ungated, and nothing shows it."""
    w = World(client, clock, 30, Knobs(), Knobs(sr=44100, mono_off_ns=9_000_000_000, sync_err_ms=-3, out_lat_ms=25))
    a, b = w.phones
    for p in w.phones:
        assert p.enroll(attested=True).status_code == 200
    c = a.post("/v1/session", {"policy": {"human": "worldid"}}).json()
    assert not GONE & set(c)
    sid = c["session_id"]
    view = b.post(f"/v1/session/{sid}/join", {"join_token": c["join_token"]}).json()
    assert not GONE & set(view)
    a.post(f"/v1/session/{sid}/confirm")
    v = b.post(f"/v1/session/{sid}/confirm").json()
    for p, q in ((a, b), (b, a)):
        p.sid, p.nonce, p.partner_pub = sid, bytes.fromhex(v["nonce"]), q.pub
    w.sid = sid
    w.run_attempt(0)
    res = w.result().json()
    assert res["verdict"] == "NEAR", res
    assert not GONE & set(res) and not GONE & set(res["presence"]["body"])
    assert not GONE & set(a.get(f"/v1/session/{sid}").json())
