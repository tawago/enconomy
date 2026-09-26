"""World ID gate (worldid 01 §6, §7.2, §9 rows 4/5/7, §6.10 fake mode).

The IDKit sidecar and the Portal are mocked with one httpx.MockTransport (FakeWorld below), which behaves
like server/idkit-sidecar/fake.mjs. Background polls are off in tests; the status GET drives one poll each.
"""
import asyncio
import hashlib
import json
import uuid
from pathlib import Path

import httpx
import pytest

from pop import popctx, worldid_rp
from pop.human import HumanError, pair_tag
from tests.phones import Phone
from tests.sim import Knobs
from tests.sim2 import World2

CANNED = json.loads((Path(__file__).parent / "fixtures" / "worldid-canned.json").read_text())
SAFE = "0x5afe5afe5afe5afe5afe5afe5afe5afe5afe5afe"
CTX = {"kind": "test", "chain_id": 11155111, "consumer": SAFE, "ctx_hash": "0x" + bytes(range(0xa0, 0xc0)).hex()}
RP = "rp_0123456789abcdef"


def fake_nullifier(who: str, action: str) -> str:
    return "0x00" + hashlib.sha256(f"fake-human:{who}:{action}".encode()).hexdigest()[:62]


class FakeWorld:
    """Sidecar (POST /requests, GET /requests/:id, /health) + Portal (/api/v4/verify, rp-status)."""

    def __init__(self):
        self.reqs: dict[str, dict] = {}
        self.polls = 2
        self.same_human = False
        self.reject: str | None = None
        self.env = "fake"
        self.mutate = None                 # fn(result) -> result
        self.portal: list = []             # queued (status, body) answers; default success
        self.portal_bodies: list = []
        self.portal_delay = 0.0
        self.sidecar_down = False

    async def __call__(self, req: httpx.Request) -> httpx.Response:
        p = req.url.path
        if req.url.port == 8787 or req.url.host == "127.0.0.1":
            if self.sidecar_down:
                raise httpx.ConnectError("down")
            if p == "/health":
                return httpx.Response(200, json={"ok": True, "idkit": "fake"})
            if p == "/requests" and req.method == "POST":
                b = json.loads(req.content)
                rid = str(uuid.uuid4())
                self.reqs[rid] = {"b": b, "role": "A" if b["signal"][-2:] == "41" else "B", "polls": 0, "terminal": None}
                return httpx.Response(200, json={"request_id": rid, "connector_uri": f"https://world.org/verify?t={rid}"})
            if p.startswith("/requests/"):
                e = self.reqs.get(p.split("/")[-1])
                if e is None:
                    return httpx.Response(404, json={"error": "unknown_request"})
                if e["terminal"]:
                    return httpx.Response(200, json=e["terminal"])
                e["polls"] += 1
                if e["polls"] <= self.polls:
                    st = "waiting_for_connection" if e["polls"] == 1 else "awaiting_confirmation"
                    return httpx.Response(200, json={"status": st, "error": None, "result": None})
                if self.reject:
                    e["terminal"] = {"status": "failed", "error": self.reject, "result": None}
                else:
                    b = e["b"]
                    who = "X" if self.same_human else e["role"]
                    res = {"protocol_version": "4.0", "nonce": b["rp_context"]["nonce"], "action": b["action"],
                           "environment": self.env,
                           "responses": [{"identifier": "proof_of_human", "issuer_schema_id": 1,
                                          "nullifier": fake_nullifier(who, b["action"]),
                                          "expires_at_min": b["rp_context"]["created_at"],
                                          "proof": ["1", "2", "3", "4", "5"]}]}
                    if self.mutate:
                        res = self.mutate(res)
                    e["terminal"] = {"status": "confirmed", "error": None, "result": res}
                return httpx.Response(200, json=e["terminal"])
        if "/api/v4/verify/" in p:
            body = json.loads(req.content)
            self.portal_bodies.append(body)
            if self.portal_delay:
                await asyncio.sleep(self.portal_delay)
            if self.portal:
                st, out = self.portal.pop(0)
                return httpx.Response(st, json=out)
            return httpx.Response(200, json={"success": True, "environment": "production", "action": body["action"],
                                             "nullifier": body["responses"][0]["nullifier"]})
        if "/api/v4/rp-status/" in p:
            return httpx.Response(200, json={"production_status": "registered"})
        return httpx.Response(404)


@pytest.fixture
def fw():
    return FakeWorld()


@pytest.fixture
def wid(make_client, clock, fw):
    """-> make(fake=True, **settings) -> (client, A, B); both phones enrolled."""
    def make(fake: bool = True, **kw):
        kw.setdefault("test_kinds", True)
        kw.setdefault("worldid_fake", fake)
        kw.setdefault("worldid_rp_id", RP)
        kw.setdefault("worldid_app_id", "app_test")
        c = make_client(allow_unattested=True, worldid_transport=httpx.MockTransport(fw), **kw)
        if not fake:
            fw.env = "production"
        a, b = Phone(c, clock, "Alice", "Pixel 8"), Phone(c, clock, "Bob", "Galaxy S23")
        assert a.enroll(attested=False).status_code == 200 and b.enroll(attested=False).status_code == 200

        async def nosleep(_s):
            return None
        c.app.state.worldid.sleep = nosleep
        return c, a, b
    return make


def paired(a, b, body=None):
    c = a.post("/v1/session", body if body is not None else {"context": CTX}).json()
    sid = c["session_id"]
    assert b.post(f"/v1/session/{sid}/join", {"join_token": c["join_token"]}).status_code == 200
    return sid


def status(p, sid):
    return p.get(f"/v1/session/{sid}/worldid").json()


def until(p, sid, want, n=10):
    for _ in range(n):
        st = status(p, sid)
        if st["status"] == want:
            return st
    raise AssertionError(st)


def verified_pair(c, a, b, body=None):
    sid = paired(a, b, body)
    for p in (a, b):
        r = p.post(f"/v1/session/{sid}/worldid/start")
        assert r.status_code == 200, r.text
    until(a, sid, "verified")
    until(b, sid, "verified")
    return sid


def doc(c, sid):
    return c.app.state.store.get_session(sid)


# -- rp_context signer (§6.3 vectors; parity with @worldcoin/idkit-core/signing 4.2.4 via the spike)

def test_rp_vectors():
    k, rand = "0x" + "ab" * 32, bytes(range(32))
    assert worldid_rp.hash_to_field(b"").hex() == "00c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a4"
    assert worldid_rp.hash_to_field(b"test_signal").hex() == \
        "00c1636e0a961a3045054c4d61374422c31a95846b8442f0927ad2ff1d6112ed"
    s = worldid_rp.sign_request(k, None, rand=rand, now=1700000000)
    assert s["nonce"] == "0x008ae1aa597fa146ebd3aa2ceddf360668dea5e526567e92b0321816a4e895bd"
    assert s["sig"] == ("0x14f693175773aed912852a601e9c0fd30f2afe2738d31388316232ce6f64ae9e4edbfb19d81c4229ba9c9fca78e"
                        "de4b28956b7ba4415f08d957cbc1b3bdaa4021b")
    s = worldid_rp.sign_request(k, "test-action", rand=rand, now=1700000000)
    assert s["sig"] == ("0x05594adb6c1495768a38d523d7d6ee6356b2c31231919198794ed022ade7d08f73753f83bd167067d99c9b969d2"
                        "8e9222315837c66af25867b041273a6d5056f1b")
    assert s["expires_at"] - s["created_at"] == 300
    # a well-known key/address pair (private key 1)
    assert worldid_rp.address_of("0x" + "00" * 31 + "01") == "0x7e5f4552091a69125d5dfcb7b8c2659029395bdf"


def test_nonce_is_field_element():
    for _ in range(100):
        assert worldid_rp.new_nonce()[0] == 0


def test_pair_tag_vectors():
    assert pair_tag("0x1", "0x2") == "0x9eccbe820eacbc4318003754ca3c32201ce343eff5afd6b8393a09fb769e0e49"
    na, nb = CANNED["A"]["responses"][0]["nullifier"], CANNED["B"]["responses"][0]["nullifier"]
    assert pair_tag(na, nb) == pair_tag(nb, na) == CANNED["expected_pair_tag"]
    assert fake_nullifier("A", "pop:" + CANNED["session_id"]) == na


# -- happy path (fake mode) + arm gate

def test_happy_path_fake(wid, fw):
    c, a, b = wid()
    sid = paired(a, b)
    v = b.get(f"/v1/session/{sid}").json()
    assert v["human"] == {"A": {"status": "idle"}, "B": {"status": "idle"}, "pair_tag": None}
    ra = a.post(f"/v1/session/{sid}/worldid/start").json()
    rb = b.post(f"/v1/session/{sid}/worldid/start").json()
    assert ra["connector_uri"].startswith("https://world.org/verify") and ra["request_id"] != rb["request_id"]
    assert ra["expires_at_s"] == a.clock() // 1000 + 300
    # the sidecar got the §6.3 request
    ba = fw.reqs[ra["request_id"]]["b"]
    n = doc(c, sid)["nonce_hex"]
    assert ba["action"] == "pop:" + sid and ba["signal"] == "0x" + n + "41" and ba["return_to"] == "enconomy://worldid"
    assert ba["rp_context"]["rp_id"] == RP and ba["rp_context"]["expires_at"] - ba["rp_context"]["created_at"] == 300
    # same start again within 240 s: same request
    assert a.post(f"/v1/session/{sid}/worldid/start").json()["request_id"] == ra["request_id"]
    # confirm is not gated, arm is
    a.post(f"/v1/session/{sid}/confirm")
    b.post(f"/v1/session/{sid}/confirm")
    arm = {"attempt": 0, "sample_rate": 48000, "rtt_min_ms": 20}
    r = a.post(f"/v1/session/{sid}/arm", arm)
    assert r.status_code == 409 and r.json()["error"] == "human_missing"
    assert status(a, sid)["status"] == "waiting"
    assert status(a, sid)["status"] == "awaiting"
    st = status(a, sid)
    assert st["status"] == "verified" and st["partner"]["status"] == "requested" and st["pair_tag"] is None
    r = a.post(f"/v1/session/{sid}/arm", arm)
    assert r.status_code == 409 and r.json()["error"] == "human_missing"      # B still missing
    until(b, sid, "verified")
    h = doc(c, sid)["human"]
    assert h["A"]["environment"] == "fake" and h["A"]["signal_hash"] == popctx.signal_hash_hex(
        popctx.signal(bytes.fromhex(n), "A"))
    assert h["A"]["rp_nonce"] == ba["rp_context"]["nonce"] and h["A"]["proof"] == ["1", "2", "3", "4", "5"]
    assert h["pair_tag"] == pair_tag(h["A"]["nullifier"], h["B"]["nullifier"])
    assert "raw" not in h["A"] and len(c.app.state.worldid.nullifiers.rows()) == 2
    v = b.get(f"/v1/session/{sid}").json()
    assert v["human"]["A"] == {"status": "verified"} and v["human"]["pair_tag"] == h["pair_tag"]
    assert "proof" not in json.dumps(v["human"])
    r = a.post(f"/v1/session/{sid}/worldid/start")
    assert r.status_code == 409 and r.json()["error"] == "already_verified"
    assert a.post(f"/v1/session/{sid}/arm", arm).status_code == 200


def test_full_flow_near_with_worldid(make_client, clock, fw):
    """sim2 fake phones: context + fake World ID on both roles -> NEAR; the record carries humans + pair_tag."""
    c = make_client(allow_unattested=True, test_kinds=True, worldid_fake=True, worldid_rp_id=RP,
                    worldid_app_id="app_test", worldid_transport=httpx.MockTransport(fw))
    w = World2(c, clock, 30, Knobs(), Knobs(sr=44100, mono_off_ns=9_000_000_000, sync_err_ms=-3, out_lat_ms=25))
    a, b = w.phones
    for p in w.phones:
        assert p.enroll(attested=False).status_code == 200
    sid = verified_pair(c, a, b)
    a.post(f"/v1/session/{sid}/confirm")
    v = b.post(f"/v1/session/{sid}/confirm").json()
    for p, q in ((a, b), (b, a)):
        p.sid, p.nonce, p.partner_pub = sid, bytes.fromhex(v["nonce"]), q.pub
    w.sid = sid
    w.run_attempt(0)
    res = w.result().json()
    assert res["verdict"] == "NEAR", res
    assert res["policy"] == {"human": "worldid"} and res["context"] == CTX
    assert res["pair_tag"] == res["human"]["pair_tag"] and res["pair_tag"].startswith("0x")
    assert res["human"]["A"]["status"] == "verified" and res["human"]["B"]["nullifier"]
    assert "connector_uri" not in res["human"]["A"]


# -- nullifier reuse and same_human

def test_same_human(wid, fw):
    c, a, b = wid()
    fw.same_human = True
    sid = paired(a, b)
    a.post(f"/v1/session/{sid}/worldid/start")
    b.post(f"/v1/session/{sid}/worldid/start")
    until(a, sid, "verified")
    st = until(b, sid, "failed")
    assert st["error"] == "same_human"
    assert b.get(f"/v1/session/{sid}").json()["human"]["B"] == {"status": "failed", "error": "same_human"}
    a.post(f"/v1/session/{sid}/confirm")
    b.post(f"/v1/session/{sid}/confirm")
    r = b.post(f"/v1/session/{sid}/arm", {"attempt": 0, "sample_rate": 48000, "rtt_min_ms": 20})
    assert r.status_code == 409 and r.json()["error"] == "human_missing"
    assert len(c.app.state.worldid.nullifiers.rows()) == 1
    # B retries with another human: new request, same action
    fw.same_human = False
    rb = b.post(f"/v1/session/{sid}/worldid/start").json()
    assert rb["status"] == "requested"
    until(b, sid, "verified")
    assert doc(c, sid)["human"]["pair_tag"] is not None


def test_same_nullifier_race_and_idempotent(wid, fw):
    """A verified; the same proof again for A = idempotent; A's nullifier for B = same_human; A stays verified."""
    c, a, b = wid()
    sid = paired(a, b)
    ra = a.post(f"/v1/session/{sid}/worldid/start").json()
    b.post(f"/v1/session/{sid}/worldid/start")
    until(a, sid, "verified")
    res_a = fw.reqs[ra["request_id"]]["terminal"]["result"]
    w = c.app.state.worldid
    before = doc(c, sid)["human"]["A"]
    assert asyncio.run(w.verify(sid, "A", res_a)) == before
    nb = doc(c, sid)["human"]["B"]["issued_nonces"][0]
    stolen = {**res_a, "nonce": nb}
    with pytest.raises(HumanError) as e:
        asyncio.run(w.verify(sid, "B", stolen))
    assert e.value.code == "same_human" and e.value.status == 409
    h = doc(c, sid)["human"]
    assert h["A"]["status"] == "verified" and h["B"]["status"] == "failed"


def test_reuse_across_sessions_refused(wid, fw):
    """A proof from session 1 replayed into session 2: other action -> human_invalid."""
    c, a, b = wid()
    sid1 = verified_pair(c, a, b)
    res = next(e["terminal"]["result"] for e in fw.reqs.values() if e["b"]["action"] == "pop:" + sid1)
    sid2 = paired(a, b)
    a.post(f"/v1/session/{sid2}/worldid/start")
    with pytest.raises(HumanError) as e:
        asyncio.run(c.app.state.worldid.verify(sid2, "A", res))
    assert e.value.code == "human_invalid"


# -- bad results

@pytest.mark.parametrize("mutate,code", [
    (lambda r: {**r, "responses": [{**r["responses"][0], "signal_hash": "0x" + "00" * 31 + "01"}]}, "human_invalid"),
    (lambda r: {**r, "action": "pop:" + "00" * 16}, "human_invalid"),
    (lambda r: {**r, "nonce": "0x" + "00" * 31 + "07"}, "human_invalid"),
    (lambda r: {**r, "responses": r["responses"] * 2}, "human_invalid"),
    (lambda r: {**r, "responses": [{**r["responses"][0], "issuer_schema_id": 128}]}, "human_level"),
    (lambda r: {**r, "responses": [{**r["responses"][0], "identifier": "orb"}]}, "human_level"),
])
def test_bad_result(wid, fw, mutate, code):
    c, a, b = wid()
    fw.mutate = mutate
    sid = paired(a, b)
    a.post(f"/v1/session/{sid}/worldid/start")
    st = until(a, sid, "failed")
    assert st["error"] == code
    assert c.app.state.worldid.nullifiers.rows() == []


def test_good_signal_hash_passes(wid, fw):
    c, a, b = wid()
    sid = paired(a, b)
    n = doc(c, sid)["nonce_hex"]
    want = popctx.signal_hash_hex(popctx.signal(bytes.fromhex(n), "A"))
    fw.mutate = lambda r: {**r, "responses": [{**r["responses"][0], "signal_hash": want}]}
    a.post(f"/v1/session/{sid}/worldid/start")
    until(a, sid, "verified")


def test_user_rejected(wid, fw):
    c, a, b = wid()
    fw.reject = "user_rejected"
    sid = paired(a, b)
    a.post(f"/v1/session/{sid}/worldid/start")
    assert until(a, sid, "failed")["error"] == "user_rejected"


# -- expiry and session lifecycle

def test_expired_then_restart(wid, fw, clock):
    c, a, b = wid()
    fw.polls = 100
    sid = paired(a, b)
    r1 = a.post(f"/v1/session/{sid}/worldid/start").json()
    clock.advance(241)
    r2 = a.post(f"/v1/session/{sid}/worldid/start").json()      # older than 240 s: re-signed
    assert r2["request_id"] != r1["request_id"]
    clock.advance(301)
    st = status(a, sid)
    assert st["status"] == "failed" and st["error"] == "human_expired"
    fw.polls = 0
    r3 = a.post(f"/v1/session/{sid}/worldid/start").json()
    assert r3["status"] == "requested"
    until(a, sid, "verified")
    h = doc(c, sid)["human"]["A"]
    assert len(h["issued_nonces"]) == 3 and h["rp_nonce"] == h["issued_nonces"][-1]


def test_start_rules(wid, fw):
    c, a, b = wid()
    s = a.post("/v1/session", {"context": CTX}).json()
    r = a.post(f"/v1/session/{s['session_id']}/worldid/start")
    assert r.status_code == 409 and r.json()["error"] == "not_joined"
    plain = paired(a, b, {})
    r = a.post(f"/v1/session/{plain}/worldid/start")
    assert r.status_code == 409 and r.json()["error"] == "bad_state"
    sid = paired(a, b)
    outsider = Phone(c, a.clock, "Eve")
    outsider.enroll(attested=False)
    assert outsider.post(f"/v1/session/{sid}/worldid/start").status_code == 403
    # a failed run needs a new session: an aborted session refuses World ID
    a.post(f"/v1/session/{sid}/abort")
    r = a.post(f"/v1/session/{sid}/worldid/start")
    assert r.status_code == 409 and r.json()["error"] == "bad_state"


def test_sidecar_down(wid, fw):
    c, a, b = wid()
    fw.sidecar_down = True
    sid = paired(a, b)
    r = a.post(f"/v1/session/{sid}/worldid/start")
    assert r.status_code == 503 and r.json()["error"] == "worldid_unavailable"
    h = c.get("/health").json()["worldid"]
    assert h["enabled"] and h["fake"] and h["sidecar_ok"] is False


def test_world_id_policy_without_context(wid, fw):
    c, a, b = wid()
    sid = verified_pair(c, a, b, {"policy": {"human": "worldid"}})
    assert doc(c, sid)["human"]["pair_tag"]


def test_config_and_health(wid):
    c, a, b = wid()
    cfg = c.get("/v1/config").json()
    assert cfg["worldid"] == {"app_id": "app_test", "rp_id": RP, "environment": "fake", "fake": True, "enabled": True}
    assert cfg["chain"] == {"chain_id": 11155111}
    assert c.get("/health").json()["worldid"]["sidecar_ok"] is True


def test_fake_requires_test_kinds(make_client):
    with pytest.raises(RuntimeError, match="POP_TEST_KINDS"):
        make_client(worldid_fake=True, test_kinds=False)


def test_no_key_means_unavailable(wid, tmp_path):
    """Production mode with an RP id but no signing key file: World ID start is 503."""
    c, a, b = wid(fake=False, worldid_signing_key_file=str(tmp_path / "missing.key"))
    sid = paired(a, b)
    r = a.post(f"/v1/session/{sid}/worldid/start")
    assert r.status_code == 503 and r.json()["error"] == "worldid_unavailable"


# -- production path through the (mocked) Portal

@pytest.fixture
def prod(wid, tmp_path):
    kf = tmp_path / "rp.key"
    kf.write_text("0x" + "ab" * 32)
    return lambda: wid(fake=False, worldid_signing_key_file=str(kf))


def test_portal_success_overwrites_signal(prod, fw):
    c, a, b = prod()
    sid = verified_pair(c, a, b)
    n = doc(c, sid)["nonce_hex"]
    assert len(fw.portal_bodies) == 2
    for body in fw.portal_bodies:
        role = "A" if body["nonce"] in doc(c, sid)["human"]["A"]["issued_nonces"] else "B"
        assert body["responses"][0]["signal_hash"] == popctx.signal_hash_hex(popctx.signal(bytes.fromhex(n), role))
    h = doc(c, sid)["human"]
    assert h["A"]["environment"] == "production" and h["pair_tag"]
    hl = c.get("/health").json()["worldid"]
    assert hl["rp_status"] == "registered" and hl["fake"] is False


def test_portal_retry_then_ok(prod, fw):
    c, a, b = prod()
    fw.portal = [(503, {}), (503, {})]
    sid = paired(a, b)
    a.post(f"/v1/session/{sid}/worldid/start")
    until(a, sid, "verified")
    assert len(fw.portal_bodies) == 3


def test_portal_reject_releases_nullifier(prod, fw):
    c, a, b = prod()
    fw.portal = [(400, {"code": "invalid_proof", "detail": "nope"})]
    sid = paired(a, b)
    a.post(f"/v1/session/{sid}/worldid/start")
    st = until(a, sid, "failed")
    assert st["error"] == "human_invalid" and "invalid_proof" in doc(c, sid)["human"]["A"]["detail"]
    assert c.app.state.worldid.nullifiers.rows() == []
    a.post(f"/v1/session/{sid}/worldid/start")                   # retry works
    until(a, sid, "verified")


def test_portal_wrong_environment(prod, fw):
    c, a, b = prod()
    fw.portal = [(200, {"success": True, "environment": "staging"})]
    sid = paired(a, b)
    a.post(f"/v1/session/{sid}/worldid/start")
    assert until(a, sid, "failed")["error"] == "human_invalid"


def test_prod_rejects_staging_result(prod, fw):
    c, a, b = prod()
    fw.mutate = lambda r: {**r, "environment": "staging"}
    sid = paired(a, b)
    a.post(f"/v1/session/{sid}/worldid/start")
    assert until(a, sid, "failed")["error"] == "human_invalid"
    assert fw.portal_bodies == []


def test_concurrent_verifies(prod, fw):
    """Both roles' verifies in flight together with a slow Portal, a confirm in between: nothing is lost."""
    c, a, b = prod()
    fw.portal_delay = 0.05
    sid = paired(a, b)
    ra = a.post(f"/v1/session/{sid}/worldid/start").json()
    rb = b.post(f"/v1/session/{sid}/worldid/start").json()
    fw.polls = 0
    res = {}
    for r, rid in (("A", ra["request_id"]), ("B", rb["request_id"])):
        fw.reqs[rid]["polls"] = 99
        e = fw.reqs[rid]
        res[r] = {"protocol_version": "4.0", "nonce": e["b"]["rp_context"]["nonce"], "action": e["b"]["action"],
                  "environment": "production",
                  "responses": [{"identifier": "proof_of_human", "issuer_schema_id": 1,
                                 "nullifier": fake_nullifier(r, e["b"]["action"]), "expires_at_min": 1, "proof": ["1"] * 5}]}
    w, sessions = c.app.state.worldid, c.app.state.sessions

    async def confirm_later():
        await asyncio.sleep(0.02)
        sessions.confirm(sessions.load(sid), "A")

    async def run():
        await asyncio.gather(w.verify(sid, "A", res["A"]), w.verify(sid, "B", res["B"]), confirm_later())
    asyncio.run(run())
    d = doc(c, sid)
    assert d["human"]["A"]["status"] == d["human"]["B"]["status"] == "verified"
    assert d["human"]["pair_tag"] and d["confirmed"]["A"] is True


# -- per-role sandbox (POP_WORLDID_SANDBOX): simulator request, nullifier taken without verification

def test_sandbox_one_role_other_production(prod, fw):
    c, a, b = prod()
    c.app.state.worldid.cfg.worldid_sandbox = True
    sid = paired(a, b)
    r = b.post(f"/v1/session/{sid}/worldid/start", {"env": "sandbox"})
    assert r.status_code == 200, r.text
    assert r.json()["connector_uri"].startswith("https://simulator.worldcoin.org/?connect_url=https%3A%2F%2F")
    rb = next(e for e in fw.reqs.values() if e["role"] == "B")
    assert rb["b"]["environment"] == "staging"
    assert a.post(f"/v1/session/{sid}/worldid/start").status_code == 200
    ra = next(e for e in fw.reqs.values() if e["role"] == "A")
    assert ra["b"]["environment"] == "production"
    n_portal = len(fw.portal_bodies)
    until(b, sid, "verified")
    assert len(fw.portal_bodies) == n_portal, "sandbox role never reaches the Portal"
    until(a, sid, "verified")
    d = doc(c, sid)["human"]
    assert d["B"]["environment"] == "sandbox" and d["A"]["environment"] == "production"
    assert d["B"]["nullifier"] == fake_nullifier("B", popctx.action(sid))
    assert d["pair_tag"] is not None
    h = a.get(f"/v1/session/{sid}").json()["human"]
    assert h["A"] == {"status": "verified"} and h["B"] == {"status": "verified", "env": "sandbox"}
    envs = sorted(r["env"] for r in c.app.state.worldid.nullifiers.rows())
    assert envs == ["production", "sandbox"]


def test_sandbox_mock_nullifier_and_gate(wid, fw):
    c, a, b = wid()
    sid = paired(a, b)
    r = a.post(f"/v1/session/{sid}/worldid/start", {"env": "sandbox"})
    assert r.status_code == 403 and r.json()["error"] == "sandbox_not_allowed"
    c.app.state.worldid.cfg.worldid_sandbox = True
    fw.mutate = lambda res: {**res, "responses": [{"identifier": "proof_of_human"}]}   # no nullifier in the proof
    assert a.post(f"/v1/session/{sid}/worldid/start", {"env": "sandbox"}).status_code == 200
    until(a, sid, "verified")
    want = "0x" + hashlib.sha256(b"pop-mock-v1" + a.device_id.encode() + sid.encode()).hexdigest()
    assert doc(c, sid)["human"]["A"]["nullifier"] == want
    sid2 = paired(a, b)
    d = doc(c, sid2)
    d["context"] = {**d["context"], "kind": "safe"}   # a real consumer kind
    c.app.state.worldid.sessions._save(d)
    r = a.post(f"/v1/session/{sid2}/worldid/start", {"env": "sandbox"})
    assert r.status_code == 403 and r.json()["error"] == "sandbox_not_allowed"
