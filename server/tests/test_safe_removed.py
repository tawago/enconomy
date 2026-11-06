"""Safe left the core for examples/safe. The core keeps a plain context: bound into the nonce and the signed record."""
from pop import presence, popctx
from tests.phones import Phone
from tests.sim import Knobs, World

SAFE = "0x5afe5afe5afe5afe5afe5afe5afe5afe5afe5afe"
CTX_HASH = bytes(range(0xa0, 0xc0))
CTX = {"chain_id": 11155111, "consumer": SAFE, "ctx_hash": "0x" + CTX_HASH.hex()}


def test_routes_are_gone(client, clock):
    p = Phone(client, clock)
    assert p.enroll().status_code == 200
    sid = p.post("/v1/session").json()["session_id"]
    assert client.get(f"/v1/session/{sid}/attestation").status_code == 404
    assert client.get(f"/v1/session/{sid}/relay").status_code == 404
    assert p.post(f"/v1/session/{sid}/safe/owner-sig", {"sig": "0x" + "00" * 64}).status_code == 404


def test_config_has_no_safe_or_attest(client):
    assert not {"safe", "attest"} & set(client.get("/v1/config").json())


def test_extra_context_key_refused(client, clock):
    p = Phone(client, clock)
    assert p.enroll().status_code == 200
    r = p.post("/v1/session", {"context": {**CTX, "kind": "safe-tx"}})
    assert r.status_code == 400 and r.json()["error"] == "bad_context"


def test_plain_context_lands_in_the_signed_record(client, clock):
    w = World(client, clock, 30, Knobs(), Knobs(sr=44100, mono_off_ns=9_000_000_000, sync_err_ms=-3, out_lat_ms=25))
    a, b = w.phones
    for p in w.phones:
        assert p.enroll(attested=True).status_code == 200
    c = a.post("/v1/session", {"context": CTX}).json()
    sid = c["session_id"]
    assert c["nonce"] == popctx.nonce(11155111, SAFE, CTX_HASH, c["not_before"], sid).hex()
    assert b.post(f"/v1/session/{sid}/join", {"join_token": c["join_token"]}).status_code == 200
    a.post(f"/v1/session/{sid}/confirm")
    v = b.post(f"/v1/session/{sid}/confirm").json()
    for p, q in ((a, b), (b, a)):
        p.sid, p.nonce, p.partner_pub = sid, bytes.fromhex(v["nonce"]), q.pub
    w.sid = sid
    w.run_attempt(0)
    res = w.result().json()
    assert res["verdict"] == "NEAR", res
    signed = res["presence"]
    pub = bytes.fromhex(client.get("/v1/config").json()["presence"]["pubkey"])
    assert presence.verify(pub, presence.TAG_RECORD, signed)
    assert signed["body"]["context"] == CTX and signed["body"]["session_nonce"] == c["nonce"]
