import base64
import hashlib
import json

import numpy as np
import pytest

from pop import constants as K
from pop import jbl250
from pop.codec import encode_commit, pcm_decode
from pop.crypto import sign_raw
from tests.phones import Phone


def confirmed(phones):
    a, b = phones
    c = a.post("/v1/session").json()
    sid = c["session_id"]
    assert b.post(f"/v1/session/{sid}/join", {"join_token": c["join_token"]}).status_code == 200
    a.post(f"/v1/session/{sid}/confirm")
    v = b.post(f"/v1/session/{sid}/confirm").json()
    assert v["state"] == "confirmed"
    return sid, v["nonce"]


def arm(p, sid, sr=48000, attempt=0, rtt=12.5):
    return p.post(f"/v1/session/{sid}/arm", {"attempt": attempt, "sample_rate": sr, "rtt_min_ms": rtt})


def commit_body(p, role, attempt, nonce_hex, rec=b"\x11" * 32, sk=None):
    raw = encode_commit(role, attempt, bytes.fromhex(nonce_hex), rec)
    sig = sign_raw(sk or p.sk, raw)
    return {"commit_b64": base64.b64encode(raw).decode(), "sig_b64": base64.b64encode(sig).decode()}


def started(phones, clock, sr_a=48000, sr_b=44100):
    a, b = phones
    sid, nonce = confirmed(phones)
    ra, rb = arm(a, sid, sr_a), arm(b, sid, sr_b)
    assert ra.status_code == 200 and rb.status_code == 200, (ra.text, rb.text)
    return sid, nonce, ra.json(), rb.json()


def store_doc(client, sid):
    return client.app.state.store.get_session(sid)


def test_time_ping(client, clock):
    assert client.get("/v1/time").json()["server_ms"] == clock()
    clock.advance(1.5)
    assert client.get("/v1/time").json()["server_ms"] == clock()


def test_arm_material_and_t0(phones, client, clock):
    a, b = phones
    sid, nonce = confirmed(phones)
    ra = arm(a, sid, 48000).json()
    v = a.get(f"/v1/session/{sid}").json()
    assert v["state"] == "confirmed" and v["armed"] == {"A": True, "B": False} and v["t0_ms"] is None
    rb = arm(b, sid, 44100).json()
    v = b.get(f"/v1/session/{sid}").json()
    assert v["state"] == "started" and v["armed"] == {"A": True, "B": True} and v["t0_ms"] == clock() + 3000
    seed = store_doc(client, sid)["seed_hex"]
    for r, role, sr in ((ra, "A", 48000), (rb, "B", 44100)):
        assert r["attempt"] == 0 and r["sample_rate"] == sr and set(r) == {"attempt", "sample_rate", "play", "own_bed"}
        n = round(0.25 * sr)
        for part in ("play", "own_bed"):
            assert r[part]["n"] == n and len(base64.b64decode(r[part]["pcm_b64"])) == 4 * n
        key = jbl250.bed_key(seed, role, 0)
        assert np.array_equal(pcm_decode(r["play"]), jbl250.render(key, role, sr)[0])
        assert np.allclose(pcm_decode(r["own_bed"]), jbl250.template(key, role, sr), atol=1e-7)
    # own bed is not the partner's, and play is not the partner's sound
    pb = jbl250.template(jbl250.bed_key(seed, "B", 0), "B", 48000)
    assert abs(np.dot(pcm_decode(ra["own_bed"]), pb)) / (np.linalg.norm(pb) * np.linalg.norm(pcm_decode(ra["own_bed"]))) < 0.05
    assert seed not in json.dumps([ra, rb])


@pytest.mark.parametrize("sr", [36000, 44100, 48000, 96000])
def test_arm_sample_rates(phones, sr):
    a, _ = phones
    sid, _ = confirmed(phones)
    r = arm(a, sid, sr).json()
    n = round(0.25 * sr)
    assert r["sample_rate"] == sr and r["play"]["n"] == r["own_bed"]["n"] == n
    x = pcm_decode(r["play"])
    assert x.size == n and np.max(np.abs(x)) <= K.MAX_PEAK
    assert float(np.sqrt(np.mean(x.astype(float) ** 2))) == pytest.approx(K.TARGET_RMS, rel=1e-3)


@pytest.mark.parametrize("sr", [35999, 96001, 0, "48000", 48000.0, None, True])
def test_arm_bad_sample_rate(phones, sr):
    a, _ = phones
    sid, _ = confirmed(phones)
    r = arm(a, sid, sr)
    assert r.status_code == 400 and r.json()["error"] == "bad_sample_rate"


def test_arm_errors(phones):
    a, b = phones
    c = a.post("/v1/session").json()
    sid = c["session_id"]
    r = arm(a, sid)
    assert r.status_code == 409 and r.json()["error"] == "bad_state"   # not confirmed yet
    b.post(f"/v1/session/{sid}/join", {"join_token": c["join_token"]})
    a.post(f"/v1/session/{sid}/confirm")
    b.post(f"/v1/session/{sid}/confirm")
    for att in (1, -1, "0", None):
        r = arm(a, sid, attempt=att)
        assert r.status_code == 400 and r.json()["error"] == "bad_attempt"
    r = arm(a, sid, rtt=301)
    assert r.status_code == 400 and r.json()["error"] == "bad_request"
    # idempotent at the same rate, refused at another
    r1, r2 = arm(a, sid).json(), arm(a, sid).json()
    assert r1 == r2
    r = arm(a, sid, 44100)
    assert r.status_code == 409 and r.json()["error"] == "bad_state"


def test_rearm_after_start_same_t0(phones, clock):
    a, b = phones
    sid, _, ra, _ = started(phones, clock)
    t0 = a.get(f"/v1/session/{sid}").json()["t0_ms"]
    clock.advance(1)
    assert arm(a, sid).json() == ra
    assert a.get(f"/v1/session/{sid}").json()["t0_ms"] == t0


def test_unauthenticated_refused(phones, client, clock):
    a, b = phones
    sid, nonce, _, _ = started(phones, clock)
    clock.advance(2)
    body = json.dumps({"attempt": 0, "sample_rate": 48000, "rtt_min_ms": 1}).encode()
    for path, raw in ((f"/v1/session/{sid}/arm", body),
                      (f"/v1/session/{sid}/commit", json.dumps(commit_body(a, "A", 0, nonce)).encode())):
        r = client.post(path, content=raw, headers={"content-type": "application/json"})
        assert r.status_code == 401 and r.json()["error"] == "auth_bad_signature"
        # signed by B's key but claiming to be A
        h = a.headers("POST", path, raw, sk=b.sk)
        r = client.post(path, content=raw, headers=h)
        assert r.status_code == 401 and r.json()["error"] == "auth_bad_signature"
    # an enrolled stranger
    eve = Phone(client, clock, "Eve")
    assert eve.enroll().status_code == 200
    assert eve.post(f"/v1/session/{sid}/arm", {"attempt": 0, "sample_rate": 48000, "rtt_min_ms": 1}).json()["error"] == "not_member"
    r = eve.post(f"/v1/session/{sid}/commit", commit_body(eve, "A", 0, nonce))
    assert r.status_code == 403 and r.json()["error"] == "not_member"
    assert not any(store_doc(client, sid)["committed"].values())


def test_partner_bed_only_after_commit(phones, client, clock):
    a, b = phones
    sid, nonce, ra, rb = started(phones, clock, 48000, 44100)
    seed = store_doc(client, sid)["seed_hex"]
    bed_b = jbl250.template(jbl250.bed_key(seed, "B", 0), "B", 48000).astype("<f4").tobytes()
    bed_a = jbl250.template(jbl250.bed_key(seed, "A", 0), "A", 44100).astype("<f4").tobytes()
    b64_bed_b, b64_bed_a = base64.b64encode(bed_b).decode(), base64.b64encode(bed_a).decode()
    seen = [json.dumps(ra), json.dumps(rb)]
    # no route hands out partner material before commit
    for p in (a, b):
        seen += [p.get(f"/v1/session/{sid}").text, p.get(f"/v1/session/{sid}?after=0").text]
        assert p.get(f"/v1/session/{sid}/partner_bed").status_code in (404, 405)
    # too early: sounds are not over yet
    r = a.post(f"/v1/session/{sid}/commit", commit_body(a, "A", 0, nonce))
    assert r.status_code == 409 and r.json()["error"] == "too_early"
    seen.append(r.text)
    clock.advance(3 + 1.2)
    # A commits; B still has nothing of A's
    r = a.post(f"/v1/session/{sid}/commit", commit_body(a, "A", 0, nonce, rec=b"\xaa" * 32))
    assert r.status_code == 200, r.text
    pb = r.json()["partner_bed"]
    assert pb["n"] == 12000 and pb["pcm_b64"] == b64_bed_b
    seen.append(b.get(f"/v1/session/{sid}").text)
    assert all(b64_bed_a not in t and b64_bed_b not in t and seed not in t for t in seen)
    v = b.get(f"/v1/session/{sid}").json()
    assert v["committed"] == {"A": True, "B": False}
    # B commits and gets A's bed at B's own rate
    r = b.post(f"/v1/session/{sid}/commit", commit_body(b, "B", 0, nonce))
    assert r.status_code == 200 and r.json()["partner_bed"]["pcm_b64"] == b64_bed_a
    assert r.json()["partner_bed"]["n"] == 11025
    doc = store_doc(client, sid)
    assert doc["per_role"]["A"]["rec_sha256"] == "aa" * 32
    raw_a = base64.b64decode(commit_body(a, "A", 0, nonce, rec=b"\xaa" * 32)["commit_b64"])
    assert doc["per_role"]["A"]["commit_sha256"] == hashlib.sha256(raw_a).hexdigest()


def test_commit_before_start(phones):
    a, _ = phones
    sid, nonce = confirmed(phones)
    arm(a, sid)
    r = a.post(f"/v1/session/{sid}/commit", commit_body(a, "A", 0, nonce))
    assert r.status_code == 409 and r.json()["error"] == "bad_state"


def test_commit_checks(phones, client, clock):
    a, b = phones
    sid, nonce, _, _ = started(phones, clock)
    clock.advance(5)
    cases = [
        (commit_body(a, "A", 0, nonce, sk=b.sk), "signature_invalid"),        # signed by the partner key
        (commit_body(a, "B", 0, nonce), "transcript_mismatch"),                 # A claims role B
        (commit_body(a, "A", 1, nonce), "transcript_mismatch"),                 # wrong attempt
        (commit_body(a, "A", 0, "00" * 32), "transcript_mismatch"),             # wrong nonce
        ({"commit_b64": "not base64!", "sig_b64": "AA=="}, "transcript_mismatch"),
        ({"commit_b64": base64.b64encode(b"POPC" + b"\0" * 10).decode(), "sig_b64": "AA=="}, "transcript_mismatch"),
    ]
    for body, err in cases:
        r = a.post(f"/v1/session/{sid}/commit", body)
        assert r.status_code == 400 and r.json()["error"] == err, (err, r.text)
    good = commit_body(a, "A", 0, nonce)
    tampered = dict(good, commit_b64=base64.b64encode(
        base64.b64decode(good["commit_b64"])[:-1] + b"\x00").decode())
    r = a.post(f"/v1/session/{sid}/commit", tampered)
    assert r.status_code == 400 and r.json()["error"] == "signature_invalid"
    assert not store_doc(client, sid)["committed"]["A"]
    # idempotent resend; a second different commit is refused
    r1 = a.post(f"/v1/session/{sid}/commit", good)
    r2 = a.post(f"/v1/session/{sid}/commit", good)
    assert r1.status_code == r2.status_code == 200 and r1.json() == r2.json()
    r = a.post(f"/v1/session/{sid}/commit", commit_body(a, "A", 0, nonce, rec=b"\x22" * 32))
    assert r.status_code == 409 and r.json()["error"] == "already_committed"


def test_attempt_codes_differ(phones, client, clock):
    a, b = phones
    sid, nonce, ra0, rb0 = started(phones, clock, 48000, 48000)
    clock.advance(5)
    pb0 = a.post(f"/v1/session/{sid}/commit", commit_body(a, "A", 0, nonce)).json()["partner_bed"]
    sessions = client.app.state.sessions
    s = sessions.next_attempt(sessions.load(sid), "glitch", "B")
    assert s["state"] == "confirmed" and s["attempt"] == 1
    v = a.get(f"/v1/session/{sid}").json()
    assert v["attempt"] == 1 and v["armed"] == v["committed"] == {"A": False, "B": False} and v["t0_ms"] is None
    # old attempt number is now refused
    assert arm(a, sid, attempt=0).json()["error"] == "bad_attempt"
    ra1, rb1 = arm(a, sid, 48000, attempt=1).json(), arm(b, sid, 48000, attempt=1).json()
    assert ra1["attempt"] == 1
    for r0, r1 in ((ra0, ra1), (rb0, rb1)):
        for part in ("play", "own_bed"):
            x0, x1 = pcm_decode(r0[part]).astype(float), pcm_decode(r1[part]).astype(float)
            assert r0[part]["pcm_b64"] != r1[part]["pcm_b64"]
        b0, b1 = pcm_decode(r0["own_bed"]).astype(float), pcm_decode(r1["own_bed"]).astype(float)
        assert abs(np.dot(b0, b1)) / (np.linalg.norm(b0) * np.linalg.norm(b1)) < 0.05
    # the public tune is the same across attempts: play - bed is unchanged
    tune0 = pcm_decode(ra0["play"]).astype(float) - pcm_decode(ra0["own_bed"]).astype(float)
    tune1 = pcm_decode(ra1["play"]).astype(float) - pcm_decode(ra1["own_bed"]).astype(float)
    assert np.corrcoef(tune0, tune1)[0, 1] > 0.99
    clock.advance(5)
    # attempt-0 commit bytes do not work for attempt 1
    r = a.post(f"/v1/session/{sid}/commit", commit_body(a, "A", 0, nonce))
    assert r.status_code == 400 and r.json()["error"] == "transcript_mismatch"
    pb1 = a.post(f"/v1/session/{sid}/commit", commit_body(a, "A", 1, nonce)).json()["partner_bed"]
    assert pb1["pcm_b64"] != pb0["pcm_b64"]
    assert pb1["pcm_b64"] != rb0["own_bed"]["pcm_b64"] and pb1["pcm_b64"] == rb1["own_bed"]["pcm_b64"]
    with pytest.raises(Exception):
        sessions.next_attempt(sessions.load(sid), "glitch", "A")   # no attempt 2
    assert store_doc(client, sid)["attempts"][0]["reason"] == "glitch"


@pytest.mark.parametrize("tune_db", [0.0, 4.0, 8.0])
def test_arm_tune_boost_keeps_bed_and_codes(make_client, clock, tune_db):
    client = make_client(tune_db=tune_db)
    a, b = Phone(client, clock, "Alice", "Pixel 8"), Phone(client, clock, "Bob", "Galaxy S23")
    assert a.enroll().status_code == 200 and b.enroll().status_code == 200
    sid, _ = confirmed((a, b))
    r = a.post(f"/v1/session/{sid}/arm", {"attempt": 0, "sample_rate": 48000, "rtt_min_ms": 10, "popt": 2}).json()
    key = jbl250.bed_key(store_doc(client, sid)["seed_hex"], "A", 0)
    from pop import popt2
    assert np.array_equal(pcm_decode(r["own_bed"]), jbl250.template(key, "A", 48000).astype(np.float32))
    assert r["own_code"] == popt2.code_wire(key, "A", 48000)
    play = pcm_decode(r["play"])
    assert np.max(np.abs(play)) <= K.MAX_PEAK
    if tune_db:
        assert r["tune_db"]["requested"] == tune_db and r["tune_db"]["applied"] <= tune_db
        s, j, bb = jbl250._parts(key, "A", 48000)
        g = 10 ** (r["tune_db"]["applied"] / 20)
        assert np.max(np.abs(play - g * s * j - s * bb)) <= 1e-4   # applied is rounded to 1e-3 dB
    else:
        assert "tune_db" not in r
    cfg = client.get("/v1/config").json()
    assert cfg["tune_db"] == tune_db and set(cfg["tune_db_max"]) == {"44100", "48000"}
