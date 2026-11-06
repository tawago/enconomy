"""World ID per (nonce, role), with the sidecar and the Portal mocked by FakeWorld."""
import pytest

from backend import popctx, worldid_rp
from backend.human import expected_signal_hash
from tests.helpers import NONCE, SID

OTHER_NONCE = "d2" * 32
OTHER_SID = "cd" * 16


def state(client, role, nonce=NONCE):
    return client.app.state.store.get(nonce, role)


def rows(client):
    return client.app.state.store.nullifier_rows()


def result_of(fw, role, nonce=NONCE):
    return next(e["terminal"]["result"] for e in fw.reqs.values()
                if e["role"] == role and e["b"]["signal"][2:66] == nonce)


# -- known-answer vectors: rp_context signer (parity with @worldcoin/idkit-core/signing 4.2.4 via the spike), signal

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


@pytest.mark.parametrize("nonce,hash_a,hash_b", [
    ("2b9a8528bf222c8cf60dd97fb416183376bd4bc5425b29c02583518590ef75c9",
     "0x002916db5141cfe5584c6de9cf6f45579e83422ecdf3260c31e30bc7f2b964c6",
     "0x0097c2b664c193be4b2699e4224cd1c6c3bb1f8de93919ebee7d7e346f25ff2b"),
    ("9fc7507c663ae43d4f8d56ba4b805fdf9e928e565141666a47630aa7fd04b121",
     "0x008f770c3f6700ffa8277d98ae286f59448b26c40ecc9b59eb4236aec76f5637",
     "0x00e9c210433251df53d3a8650bc8f0b54e5ad84ffcc0593e2785d0778f92199a"),
])
def test_signal_vectors(nonce, hash_a, hash_b):
    n = bytes.fromhex(nonce)
    assert popctx.signal_str(n, "A") == "0x" + nonce + "41"
    assert popctx.signal_hash_hex(popctx.signal(n, "A")) == hash_a
    assert popctx.signal_hash_hex(popctx.signal(n, "B")) == hash_b


def test_action_vector():
    sid = "00112233445566778899aabbccddeeff"
    assert popctx.action(sid) == "pop:" + sid and len(popctx.action(sid)) == 36
    assert popctx.signal_hash_hex(popctx.action(sid).encode()) == \
        "0x003d0a5a51f4fe9954190e3c33adb92f760da336203f33ee63a29ad4ee6fd8ae"


# -- happy path

def test_two_humans_verified(client, phones, fw, clock):
    a, b = phones
    ra = a.start()
    assert ra.status_code == 200, ra.text
    ra = ra.json()
    assert ra["connector_uri"].startswith("https://world.org/verify") and ra["expires_at_s"] == clock() // 1000 + 300
    # what the sidecar was asked for
    sent = fw.reqs[ra["request_id"]]["b"]
    assert sent["action"] == "pop:" + SID and sent["signal"] == "0x" + NONCE + "41"
    assert sent["rp_context"]["rp_id"] == "rp_0123456789abcdef" and sent["environment"] == "production"
    # one request while it's live
    assert a.start().json()["request_id"] == ra["request_id"]
    assert b.start().json()["request_id"] != ra["request_id"]

    assert a.status().json()["status"] == "waiting"
    assert a.status().json()["status"] == "awaiting"
    st = a.status().json()
    assert st["status"] == "verified" and st["partner"]["status"] == "requested"
    assert b.until("verified").json()["partner"]["status"] == "verified"

    sa, sb = state(client, "A"), state(client, "B")
    assert sa["nullifier"] and sb["nullifier"] and sa["nullifier"] != sb["nullifier"]
    assert sa["pubkey"] == a.pub.hex() and sa["session_id"] == SID
    assert len(rows(client)) == 2
    # the Portal gets the hash we computed, so a proof for another signal fails there
    assert [x["responses"][0]["signal_hash"] for x in fw.portal_bodies] == \
        [expected_signal_hash(NONCE, "A"), expected_signal_hash(NONCE, "B")]
    r = a.start()
    assert r.status_code == 409 and r.json()["error"] == "already_verified"


# -- check 1: two different humans

def test_same_human_refused(client, phones, fw):
    a, b = phones
    fw.same_human = True
    assert a.start().status_code == 200
    # another session_id would mean another action, so another nullifier for the same human: refused at the door
    before = len(fw.reqs)
    r = b.start(sid=OTHER_SID)
    assert r.status_code == 409 and r.json()["error"] == "session_id_mismatch"
    assert len(fw.reqs) == before and state(client, "B") is None
    r = b.status(sid=OTHER_SID)
    assert r.status_code == 409 and r.json()["error"] == "session_id_mismatch"

    assert a.until("verified").json()["status"] == "verified"
    assert b.start().status_code == 200
    r = b.until("verified")
    assert r.status_code == 409 and r.json()["error"] == "same_human"
    assert state(client, "B")["status"] == "failed" and state(client, "B")["nullifier"] is None
    assert state(client, "A")["status"] == "verified" and len(rows(client)) == 1
    assert b.status().json() | {"partner": None} == {"role": "B", "status": "failed", "error": "same_human", "partner": None}
    # B retries with another human: new request, same action
    fw.same_human = False
    assert b.start().json()["status"] == "requested"
    assert b.until("verified").json()["status"] == "verified"


# -- check 2: the signal and the action bind a proof to this nonce and role

@pytest.mark.parametrize("name,detail", [
    ("other_session", "action mismatch"),
    ("other_nonce", "signal_hash mismatch"),
    ("other_role", "signal_hash mismatch"),
    ("other_role_rp_nonce", "nonce was not issued"),
])
def test_proof_from_elsewhere_fails(client, phones, fw, name, detail):
    a, b = phones
    # session 1: nonce NONCE, sid SID, A is verified
    assert a.start().status_code == 200
    assert a.until("verified").status_code == 200
    stolen = result_of(fw, "A")

    def own_rp_nonce(res, e, **r0):
        return {**stolen, "nonce": e["b"]["rp_context"]["nonce"], "responses": [{**stolen["responses"][0], **r0}]}

    def mutate(res, e):
        if name == "other_session":
            return own_rp_nonce(res, e)
        if name == "other_nonce":
            return own_rp_nonce(res, e, signal_hash=expected_signal_hash(OTHER_NONCE, "B"))
        if name == "other_role":
            return own_rp_nonce(res, e, signal_hash=expected_signal_hash(NONCE, "A"))
        return stolen
    fw.mutate = mutate
    held = len(rows(client))
    portal = len(fw.portal_bodies)

    kw = {"nonce": OTHER_NONCE, "sid": OTHER_SID} if name == "other_session" else {}
    assert b.start(**kw).status_code == 200
    r = b.until("verified", **kw)
    assert r.status_code == 400 and r.json()["error"] == "human_invalid" and detail in r.json()["detail"], r.text
    s = state(client, "B", kw.get("nonce", NONCE))
    assert s["status"] == "failed" and s["nullifier"] is None
    assert len(rows(client)) == held and len(fw.portal_bodies) == portal


@pytest.mark.parametrize("change,code", [
    ({"responses": []}, "human_invalid"),
    ({"environment": "staging"}, "human_invalid"),
    ({"responses": [{"identifier": "orb", "issuer_schema_id": 1, "nullifier": "0x1"}]}, "human_level"),
])
def test_bad_result(client, phones, fw, change, code):
    a, _ = phones
    fw.mutate = lambda res, e: {**res, **change}
    a.start()
    r = a.until("verified")
    assert r.status_code == 400 and r.json()["error"] == code
    assert state(client, "A")["status"] == "failed" and rows(client) == []


# -- the Portal

def test_portal_rejection_releases_the_nullifier(client, phones, fw):
    a, _ = phones
    fw.portal = [(400, {"code": "invalid_proof"})]
    a.start()
    r = a.until("verified")
    assert r.status_code == 400 and "invalid_proof" in r.json()["detail"]
    assert rows(client) == []
    a.start()
    assert a.until("verified").json()["status"] == "verified"


def test_portal_must_say_production(client, phones, fw):
    a, _ = phones
    fw.portal = [(200, {"success": True, "environment": "staging"})]
    a.start()
    assert a.until("verified").status_code == 400
    assert state(client, "A")["status"] == "failed" and rows(client) == []


# -- device requests

def test_device_key_is_pinned(client, phones):
    a, b = phones
    assert a.start().status_code == 200
    # B's key tries to take role A
    r = b.start(role="A")
    assert r.status_code == 409 and r.json()["error"] == "pubkey_mismatch"
    r = b.status(role="A")
    assert r.status_code == 409 and r.json()["error"] == "pubkey_mismatch"
    assert state(client, "A")["pubkey"] == a.pub.hex()


def test_device_signature(phones, client, clock):
    a, b = phones
    for req in (a.signed(ts=1), a.signed(pubkey=b.pub.hex())):      # changed after signing
        r = client.post("/v1/worldid/start", json=req)
        assert r.status_code == 401 and r.json()["error"] == "bad_device_signature"
    old = a.signed()
    clock.advance(301)
    r = client.post("/v1/worldid/start", json=old)
    assert r.status_code == 401 and r.json()["error"] == "stale_request"


@pytest.mark.parametrize("over", [
    {"session_nonce": "C1" * 32},
    {"session_nonce": "c1" * 31},
    {"session_id": "AB" * 16},
    {"session_id": "ab" * 15},
    {"role": "C"},
    {"role": ["A"]},
    {"pubkey": "04" + "00" * 64},
    {"ts": "1"},
    {"sig_b64": "not base64"},
])
def test_bad_requests(phones, client, over):
    a, _ = phones
    r = client.post("/v1/worldid/start", json=a.signed(**over))
    assert r.status_code == 400 and r.json()["error"] == "bad_request", r.text


def test_expired_then_restart(client, phones, fw, clock):
    a, _ = phones
    fw.polls = 100
    r1 = a.start().json()
    clock.advance(241)
    assert a.start().json()["request_id"] != r1["request_id"]    # older than 240 s: re-signed
    clock.advance(301)
    st = a.status().json()
    assert st["status"] == "failed" and st["error"] == "human_expired"
    fw.polls = 0
    assert a.start().json()["status"] == "requested"
    assert a.until("verified").json()["status"] == "verified"
    s = state(client, "A")
    assert len(s["issued_nonces"]) == 3 and s["rp_nonce"] == s["issued_nonces"][-1]
