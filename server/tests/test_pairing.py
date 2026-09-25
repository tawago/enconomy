import json
import threading
import time

from pop import invite
from pop.crypto import key_hint
from tests.phones import Phone


def _create(a):
    r = a.post("/v1/session")
    assert r.status_code == 200, r.text
    return r.json()


def _paired(phones):
    a, b = phones
    c = _create(a)
    r = b.post(f"/v1/session/{c['session_id']}/join", {"join_token": c["join_token"]})
    assert r.status_code == 200, r.text
    return c["session_id"]


def test_create_invite(phones, clock):
    a, _ = phones
    c = _create(a)
    assert len(c["session_id"]) == 32 and len(c["join_token"]) == 32
    assert c["expires_at_ms"] == clock() + 120_000
    raw = invite.from_qr(c["invite_qr"])
    assert c["invite_qr"] == "pop1:" + c["invite_b64url"]
    d = invite.decode(raw)
    assert d["session_id"] == c["session_id"] and d["join_token"] == c["join_token"]
    assert d["expires_at_s"] == c["expires_at_ms"] // 1000 and d["host_hint"] == key_hint(a.pub)


def test_join_and_partner_view(phones):
    a, b = phones
    c = _create(a)
    r = b.post(f"/v1/session/{c['session_id']}/join", {"join_token": c["join_token"]})
    v = r.json()
    assert v["role"] == "B" and v["state"] == "joined" and v["nonce"] is None
    assert v["partner"]["device_id"] == a.device_id and v["partner"]["display_name"] == "Alice"
    assert v["partner"]["model"] == "Pixel 8" and v["partner"]["attested"] is True
    # guest checks invite hint against partner pubkey
    hint = invite.decode(invite.from_qr(c["invite_qr"]))["host_hint"]
    assert key_hint(bytes.fromhex(v["partner"]["pubkey"])) == hint
    va = a.get(f"/v1/session/{c['session_id']}").json()
    assert va["role"] == "A" and va["partner"]["device_id"] == b.device_id and va["partner"]["model"] == "Galaxy S23"


def test_join_unknown_session(phones):
    _, b = phones
    r = b.post(f"/v1/session/{'ab' * 16}/join", {"join_token": "00" * 16})
    assert r.status_code == 404 and r.json()["error"] == "not_found"


def test_self_join(phones):
    a, _ = phones
    c = _create(a)
    r = a.post(f"/v1/session/{c['session_id']}/join", {"join_token": c["join_token"]})
    assert r.status_code == 400 and r.json()["error"] == "self_join"


def test_wrong_token(phones):
    a, b = phones
    c = _create(a)
    r = b.post(f"/v1/session/{c['session_id']}/join", {"join_token": "00" * 16})
    assert r.status_code == 403 and r.json()["error"] == "bad_token"
    # the real token still works afterwards
    assert b.post(f"/v1/session/{c['session_id']}/join", {"join_token": c["join_token"]}).status_code == 200


def test_expired_token(phones, clock):
    a, b = phones
    c = _create(a)
    clock.advance(121)
    r = b.post(f"/v1/session/{c['session_id']}/join", {"join_token": c["join_token"]})
    assert r.status_code == 410 and r.json()["error"] == "token_expired"
    v = a.get(f"/v1/session/{c['session_id']}").json()
    assert v["state"] == "aborted" and v["error"] == "timeout"


def test_token_just_before_expiry(phones, clock):
    a, b = phones
    c = _create(a)
    clock.advance(119)
    assert b.post(f"/v1/session/{c['session_id']}/join", {"join_token": c["join_token"]}).status_code == 200


def test_reused_token(phones, client, clock):
    a, b = phones
    c = _create(a)
    body = {"join_token": c["join_token"]}
    assert b.post(f"/v1/session/{c['session_id']}/join", body).status_code == 200
    eve = Phone(client, clock, "Eve")
    assert eve.enroll().status_code == 200
    r = eve.post(f"/v1/session/{c['session_id']}/join", body)
    assert r.status_code == 409 and r.json()["error"] == "already_joined"
    r = b.post(f"/v1/session/{c['session_id']}/join", body)
    assert r.status_code == 409 and r.json()["error"] == "already_joined"
    r = eve.get(f"/v1/session/{c['session_id']}")
    assert r.status_code == 403 and r.json()["error"] == "not_member"


def test_confirm_flow(phones):
    a, b = phones
    sid = _paired(phones)
    v = a.post(f"/v1/session/{sid}/confirm").json()
    assert v["state"] == "joined" and v["confirmed"] == {"A": True, "B": False} and v["nonce"] is None
    v = b.post(f"/v1/session/{sid}/confirm").json()
    assert v["state"] == "confirmed" and v["confirmed"] == {"A": True, "B": True}
    assert len(v["nonce"]) == 64 and v["self"]["pubkey"] == b.pub.hex() and v["partner"]["pubkey"] == a.pub.hex()
    va = a.get(f"/v1/session/{sid}").json()
    assert va["nonce"] == v["nonce"] and va["self"]["pubkey"] == a.pub.hex()
    # idempotent
    assert a.post(f"/v1/session/{sid}/confirm").json()["state"] == "confirmed"


def test_confirm_before_join(phones):
    a, _ = phones
    c = _create(a)
    r = a.post(f"/v1/session/{c['session_id']}/confirm")
    assert r.status_code == 409 and r.json()["error"] == "bad_state"


def test_seq_and_longpoll(phones):
    a, b = phones
    c = _create(a)
    sid = c["session_id"]
    v0 = a.get(f"/v1/session/{sid}").json()
    # nothing new: returns after timeout with the same seq
    t = time.monotonic()
    v = a.get(f"/v1/session/{sid}?after={v0['seq']}&timeout_s=0.3").json()
    assert v["seq"] == v0["seq"] and time.monotonic() - t >= 0.25
    # a join during the poll wakes it up
    out = {}
    th = threading.Thread(target=lambda: out.update(v=a.get(f"/v1/session/{sid}?after={v0['seq']}&timeout_s=5").json()))
    th.start()
    time.sleep(0.2)
    assert b.post(f"/v1/session/{sid}/join", {"join_token": c["join_token"]}).status_code == 200
    th.join(5)
    assert out["v"]["seq"] > v0["seq"] and out["v"]["state"] == "joined"


def test_abort(phones):
    a, b = phones
    sid = _paired(phones)
    v = b.post(f"/v1/session/{sid}/abort").json()
    assert v["state"] == "aborted" and v["error"] == "aborted"
    assert a.get(f"/v1/session/{sid}").json()["state"] == "aborted"
    assert a.post(f"/v1/session/{sid}/confirm").json()["error"] == "bad_state"


def test_session_max_age(phones, clock):
    a, _ = phones
    sid = _paired(phones)
    clock.advance(601)
    v = a.get(f"/v1/session/{sid}").json()
    assert v["state"] == "aborted" and v["error"] == "timeout"


def test_seed_never_sent(phones):
    a, b = phones
    c = _create(a)
    sid = c["session_id"]
    texts = [json.dumps(c)]
    texts.append(b.post(f"/v1/session/{sid}/join", {"join_token": c["join_token"]}).text)
    texts += [a.post(f"/v1/session/{sid}/confirm").text, b.post(f"/v1/session/{sid}/confirm").text,
              a.get(f"/v1/session/{sid}").text, b.get(f"/v1/session/{sid}").text]
    seed = a.client.app.state.store.get_session(sid)["seed_hex"]
    assert all(seed not in t and "seed" not in t for t in texts)
