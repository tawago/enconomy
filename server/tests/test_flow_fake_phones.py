"""Two fake phones through the whole HTTP flow (contract §10.1 test_flow_fake_phones).

Captures: white noise (or a real field recording crop, POP_FIELD_DATA) + the session's own
rendered JBL250 sounds at the true arrival frames. DSP = pop.dsp_ref. Software P-256 keys.
"""
import copy
import hashlib
import io
import json
import os
import wave
from pathlib import Path

import numpy as np
import pytest

from pop import constants as K
from pop.codec import b64d, decode_transcript, encode_commit, encode_transcript
from pop.crypto import sign_raw
from pop.verdict import Reject, verify_record
from tests.sim import Knobs, World, b64


@pytest.fixture
def world(make_client, clock):
    def make(d, ka=None, kb=None, **kw):
        w = World(make_client(allow_unattested=True), clock, d, ka or Knobs(),
                  kb or Knobs(sr=44100, mono_off_ns=9_000_000_000, sync_err_ms=-3, out_lat_ms=25), **kw)
        w.pair()
        return w
    return make


def outcomes(rec):
    return [(a["attempt"], a["outcome"], a["reason"], a["by"]) for a in rec["attempts"]]


@pytest.mark.parametrize("d", [0, 30])
def test_near(world, tmp_path, d):
    w = world(d)
    out = w.run_attempt(0)
    assert out["A"].json() == {"accepted": True, "state": "started", "attempt": 0}
    assert out["B"].json()["state"] == "done"
    v = w.view(w.b)
    assert v["state"] == "done" and v["error"] is None
    r = w.result()
    assert r.status_code == 200
    rec = r.json()
    assert rec["verdict"] == "NEAR" and rec["reason"] is None and rec["flight_cm"] == pytest.approx(d, abs=2)
    assert rec == v["result"] == w.result(w.b).json()
    assert outcomes(rec) == [(0, "verdict", None, None)]
    assert rec["proto"] == "pop-v1" and rec["session_nonce"] == w.a.nonce.hex() and rec["t0_ms"]
    for p in w.phones:
        dv = rec["devices"][p.role]
        assert dv["pubkey"] == p.pub.hex() and dv["sample_rate"] == p.k.sr and dv["half"] == p.last["transcript"]["half"]
        tr = rec["transcripts"][p.role]
        assert b64d(tr["transcript_b64"]) == p.last["raw"] and tr["sha256"] == hashlib.sha256(p.last["raw"]).hexdigest()
    # stored on disk, and re-verifiable offline from the record alone
    on_disk = json.loads((tmp_path / "sessions" / w.sid / "result.json").read_text())
    assert on_disk == rec
    assert verify_record(rec)["verdict"] == "NEAR"
    # meta kept for debugging, never in the record
    assert w.doc()["attempts"][-1]["per_role"]["A"]["meta"]["model"] == "Pixel 8"
    assert "meta" not in json.dumps(rec["transcripts"])


@pytest.mark.parametrize("d", [100, 200])
def test_far_never_retries(world, d):
    w = world(d)
    w.run_attempt(0)
    rec = w.result().json()
    assert rec["verdict"] == "NOT_NEAR" and rec["reason"] == "too_far" and rec["attempt"] == 0
    assert rec["flight_cm"] == pytest.approx(d, abs=2) and rec["user_text"].startswith("Too far")
    assert outcomes(rec) == [(0, "verdict", "too_far", None)]
    v = w.view()
    assert v["state"] == "done" and v["error"] == "too_far" and v["last_failure"] is None
    assert w.a.post(f"/v1/session/{w.sid}/arm", {"attempt": 1, "sample_rate": 48000, "rtt_min_ms": 1}).status_code == 409


def test_glitch_retry_then_verdict(world):
    # 20 ms zero block in B between A's sound and B's own sound
    w = world(30, kb=Knobs(sr=48000, mono_off_ns=5, zero_block=(0.95, 0.02)))
    out = w.run_attempt(0)
    assert w.b.log == [(0, "glitch")]
    v = out["B"].json()
    assert v["state"] == "confirmed" and v["attempt"] == 1 and v["t0_ms"] is None
    assert v["last_failure"] == {"attempt": 0, "reason": "glitch", "by": "B", "text": "Recording glitch, trying again."}
    assert w.result().json()["error"] == "no_result"
    # A's attempt-0 transcript already went in; it is not carried over
    assert v["submitted"] == {"A": False, "B": False}
    w.run_attempt(1)
    rec = w.result().json()
    assert rec["verdict"] == "NEAR" and rec["attempt"] == 1 and rec["flight_cm"] == pytest.approx(30, abs=2)
    assert outcomes(rec) == [(0, "failed", "glitch", "B"), (1, "verdict", None, None)]
    assert verify_record(rec)["verdict"] == "NEAR"


def test_two_failures_final(world):
    w = world(30, ka=Knobs(fail_at={0: "partner_not_heard", 1: "partner_not_heard"}))
    w.run_attempt(0, skip=("B",))    # B would find its commit refused (state already back to confirmed)
    assert w.view()["attempt"] == 1
    w.run_attempt(1, skip=("B",))
    rec = w.result().json()
    assert rec["verdict"] == "NOT_NEAR" and rec["reason"] == "partner_not_heard"
    assert outcomes(rec) == [(0, "failed", "partner_not_heard", "A"), (1, "failed", "partner_not_heard", "A")]


def test_both_fail_first_reason_wins(world):
    w = world(30, ka=Knobs(fail_at={0: "self_not_heard"}), kb=Knobs(sr=48000, fail_at={0: "glitch"}))
    out = w.run_attempt(0)
    assert out["A"].json()["attempt"] == 1
    assert out["B"].status_code == 409 and out["B"].json()["error"] == "stale_attempt"
    assert w.doc()["attempts"][0]["reason"] == "self_not_heard"


def test_timeout_retry(world, clock):
    w = world(30)
    w.run_attempt(0, skip=("B",))
    assert w.view()["submitted"] == {"A": True, "B": False}
    t0 = w.view()["t0_ms"]
    clock.ms = t0 + K.TRANSCRIPT_DEADLINE_S * 1000 + 1
    v = w.view()
    assert v["state"] == "confirmed" and v["attempt"] == 1
    assert v["last_failure"]["reason"] == "timeout" and v["last_failure"]["by"] == "B"
    w.run_attempt(1)
    rec = w.result().json()
    assert rec["verdict"] == "NEAR" and outcomes(rec)[0] == (0, "failed", "timeout", "B")


def test_stale_transcript_after_retry(world):
    w = world(30, ka=Knobs(fail_at={0: "glitch"}))
    out = w.run_attempt(0, submit_order=("B", "A"))
    assert out["B"].json()["state"] == "started" and out["A"].json()["attempt"] == 1
    body = {"transcript_b64": b64(w.b.last["raw"]), "sig_b64": b64(sign_raw(w.b.sk, w.b.last["raw"]))}
    r = w.b.post(f"/v1/session/{w.sid}/transcript", body)
    assert r.status_code == 409 and r.json()["error"] == "stale_attempt"
    r = w.b.post(f"/v1/session/{w.sid}/fail", {"attempt": 0, "reason": "glitch"})
    assert r.status_code == 409 and r.json()["error"] == "stale_attempt"
    for p in w.phones:
        p.arm(1)
    r = w.b.post(f"/v1/session/{w.sid}/transcript", body)       # still stale once attempt 1 started
    assert r.status_code == 409 and r.json()["error"] == "stale_attempt"
    assert w.view()["state"] == "started"


def signed(p, t: dict) -> dict:
    raw = encode_transcript(t)
    return {"transcript_b64": b64(raw), "sig_b64": b64(sign_raw(p.sk, raw)), "meta": {}}


@pytest.fixture
def pending(world, monkeypatch):
    """Session where both committed and A submitted; B's honest transcript is in w.b.last, unsent."""
    w = world(30)
    sent = {}
    orig = w.b.post

    def hold(path, body=None, **kw):
        if path.endswith("/transcript") and "held" not in sent:
            sent["held"] = body
            return None
        return orig(path, body, **kw)
    monkeypatch.setattr(w.b, "post", hold)
    w.run_attempt(0)
    monkeypatch.setattr(w.b, "post", orig)
    assert w.view()["submitted"] == {"A": True, "B": False}
    return w, sent["held"]


def final(w, reason):
    rec = w.result().json()
    assert rec["verdict"] == "NOT_NEAR" and rec["reason"] == reason and rec["attempt"] == 0, rec
    assert w.view()["state"] == "done"
    return rec


def test_honest_pending_completes(pending):
    w, body = pending
    r = w.b.post(f"/v1/session/{w.sid}/transcript", body)
    assert r.status_code == 200 and r.json()["state"] == "done"
    r2 = w.b.post(f"/v1/session/{w.sid}/transcript", body)      # resend after done
    assert r2.status_code == 409


def test_swapped_roles_rejected(pending):
    """B signs a transcript claiming role A with the keys swapped (the sign-flip attack)."""
    w, _ = pending
    t = dict(w.b.last["transcript"], role="A")
    r = w.b.post(f"/v1/session/{w.sid}/transcript", signed(w.b, t))
    assert r.status_code == 400 and r.json()["error"] == "transcript_mismatch"
    rec = final(w, "transcript_mismatch")
    assert outcomes(rec) == [(0, "rejected", "transcript_mismatch", "B")]
    assert w.a.post(f"/v1/session/{w.sid}/arm", {"attempt": 1, "sample_rate": 48000, "rtt_min_ms": 1}).status_code == 409


def test_submitting_partner_transcript_rejected(pending):
    """B relays A's (validly signed) transcript as its own: signature is not B's."""
    w, _ = pending
    raw = w.a.last["raw"]
    r = w.b.post(f"/v1/session/{w.sid}/transcript", {"transcript_b64": b64(raw), "sig_b64": b64(sign_raw(w.a.sk, raw))})
    assert r.status_code == 400 and r.json()["error"] == "signature_invalid"
    final(w, "signature_invalid")


@pytest.mark.parametrize("off", [173, 176, 233, 7, 200])
def test_tampered_bytes_rejected(pending, off):
    w, body = pending
    raw = bytearray(b64d(body["transcript_b64"]))
    raw[off] ^= 0x01
    r = w.b.post(f"/v1/session/{w.sid}/transcript", dict(body, transcript_b64=b64(bytes(raw))))
    assert r.status_code == 400 and r.json()["error"] == "signature_invalid"
    final(w, "signature_invalid")


@pytest.mark.parametrize("field,val,why", [
    ("nonce", b"\x00" * 32, "transcript_mismatch"),
    ("attempt", 1, "transcript_mismatch"),
    ("pk_partner", b"\x04" + b"\x01" * 64, "transcript_mismatch"),
    ("pk_self", b"\x04" + b"\x01" * 64, "signature_invalid"),
    ("rec_sha256", b"\x55" * 32, "transcript_mismatch"),
    ("commit_hash", b"\x55" * 32, "transcript_mismatch"),
    ("sample_rate", 47999, "transcript_mismatch"),
])
def test_field_checks(pending, field, val, why):
    w, _ = pending
    t = dict(w.b.last["transcript"], **{field: val})
    r = w.b.post(f"/v1/session/{w.sid}/transcript", signed(w.b, t))
    assert r.status_code == 400 and r.json()["error"] == why, r.text
    final(w, why)


def test_garbage_transcript_rejected(pending):
    w, body = pending
    r = w.b.post(f"/v1/session/{w.sid}/transcript", dict(body, transcript_b64=b64(b"POPT" + b"\0" * 10)))
    assert r.status_code == 400 and r.json()["error"] == "transcript_mismatch"
    final(w, "transcript_mismatch")


def test_replay_from_another_session(world):
    w1 = world(30)
    w1.run_attempt(0)
    old = w1.b.last["raw"]
    # replay B's old transcript (right key, wrong nonce/partner) into a fresh session of the same devices
    a, b = w1.phones
    c = a.post("/v1/session").json()
    sid = c["session_id"]
    b.post(f"/v1/session/{sid}/join", {"join_token": c["join_token"]})
    a.post(f"/v1/session/{sid}/confirm")
    v = b.post(f"/v1/session/{sid}/confirm").json()
    w1.sid = sid
    for p in w1.phones:
        p.sid, p.nonce = sid, bytes.fromhex(v["nonce"])
    for p in w1.phones:
        p.arm(0)
    t0 = w1.view()["t0_ms"]
    w1.clock.ms = t0 + 1500
    t_old = decode_transcript(old)
    cm = encode_commit("B", 0, w1.b.nonce, t_old["rec_sha256"])
    assert b.post(f"/v1/session/{sid}/commit", {"commit_b64": b64(cm), "sig_b64": b64(sign_raw(b.sk, cm))}).status_code == 200
    r = b.post(f"/v1/session/{sid}/transcript", {"transcript_b64": b64(old), "sig_b64": b64(sign_raw(b.sk, old))})
    assert r.status_code == 400 and r.json()["error"] == "transcript_mismatch"


def test_transcript_before_commit(world):
    w = world(30)
    for p in w.phones:
        p.arm(0)
    w.clock.ms = w.view()["t0_ms"] + 1500
    t = {"role": "A", "attempt": 0, "nonce": w.a.nonce, "pk_self": w.a.pub, "pk_partner": w.b.pub, "sample_rate": 48000,
         "half": 1, "rec_sha256": b"\0" * 32, "play_frame_position": 0, "play_nano_time": 0, "rec_frame0_nano_time": 0,
         "self_os_delta": 0, "commit_hash": b"\0" * 32}
    r = w.a.post(f"/v1/session/{w.sid}/transcript", signed(w.a, t))
    assert r.status_code == 409 and r.json()["error"] == "bad_state"
    assert w.view()["state"] == "started"
    assert w.a.get(f"/v1/session/{w.sid}/partner_bed").status_code in (404, 405)


def test_impossible_flight_retries(world):
    # B reports a half 4 ms too long: flight ~ 30 - 68 cm
    w = world(30, kb=Knobs(sr=48000, half_bias=192))
    w.run_attempt(0)
    v = w.view()
    assert v["attempt"] == 1 and v["last_failure"]["reason"] == "impossible_flight"
    w.b.k.half_bias = 0
    w.run_attempt(1)
    assert w.result().json()["verdict"] == "NEAR"


def test_self_timestamp_mismatch_retries(world):
    w = world(30, kb=Knobs(sr=48000, self_os_delta_override=5000))
    w.run_attempt(0)
    v = w.view()
    assert v["attempt"] == 1 and v["last_failure"] == {"attempt": 0, "reason": "self_timestamp_mismatch", "by": "B",
                                                       "text": "Audio timing off, trying again."}


def test_fail_endpoint_checks(world):
    w = world(30)
    for reason, code, err in (("nope", 400, "bad_reason"), ("too_far", 400, "bad_reason"), ("timeout", 400, "bad_reason")):
        r = w.a.post(f"/v1/session/{w.sid}/fail", {"attempt": 0, "reason": reason})
        assert r.status_code == code and r.json()["error"] == err
    r = w.a.post(f"/v1/session/{w.sid}/fail", {"attempt": 1, "reason": "glitch"})
    assert r.status_code == 400 and r.json()["error"] == "bad_attempt"
    # a failure while arming (before start) is allowed
    r = w.a.post(f"/v1/session/{w.sid}/fail", {"attempt": 0, "reason": "capture_failed"})
    assert r.status_code == 200 and r.json()["attempt"] == 1 and r.json()["state"] == "confirmed"


def test_partner_mismatch_is_final(world):
    w = world(30)
    r = w.b.post(f"/v1/session/{w.sid}/fail", {"attempt": 0, "reason": "partner_mismatch"})
    assert r.status_code == 200 and r.json()["state"] == "done"
    assert w.result().json()["reason"] == "partner_mismatch"


def test_result_access(world, make_client, clock):
    w = world(30)
    r = w.result()
    assert r.status_code == 404 and r.json()["error"] == "no_result"
    w.run_attempt(0)
    from tests.phones import Phone
    eve = Phone(w.client, clock, "Eve")
    assert eve.enroll(attested=False).status_code == 200
    r = eve.get(f"/v1/session/{w.sid}/result")
    assert r.status_code == 403 and r.json()["error"] == "not_member"
    assert w.client.get(f"/v1/session/{w.sid}/result").status_code == 401


def test_offline_verify_rejects_swaps(world):
    w = world(100)
    w.run_attempt(0)
    rec = w.result().json()
    assert verify_record(rec)["flight_cm"] == pytest.approx(100, abs=2)
    # swap the two transcripts (and commits): -100 cm would read NEAR if nothing pinned the roles
    sw = copy.deepcopy(rec)
    sw["transcripts"] = {"A": rec["transcripts"]["B"], "B": rec["transcripts"]["A"]}
    sw["commits"] = {"A": rec["commits"]["B"], "B": rec["commits"]["A"]}
    with pytest.raises(Reject) as e:
        verify_record(sw)
    assert e.value.reason == "signature_invalid"
    # swap devices too: signatures now check out, the role byte does not
    sw["devices"] = {"A": rec["devices"]["B"], "B": rec["devices"]["A"]}
    with pytest.raises(Reject) as e:
        verify_record(sw)
    assert e.value.reason == "transcript_mismatch"
    # a different nonce
    bad = copy.deepcopy(rec)
    bad["session_nonce"] = "00" * 32
    with pytest.raises(Reject):
        verify_record(bad)


def _wav(pcm: np.ndarray, sr: int) -> bytes:
    bio = io.BytesIO()
    with wave.open(bio, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sr)
        f.writeframes(pcm.astype("<i2").tobytes())
    return bio.getvalue()


def _upload(p, sid, wav: bytes, meta: dict):
    from pop.auth import request_message
    boundary = "popboundary"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"meta\"\r\n\r\n{json.dumps(meta)}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"wav\"; filename=\"r.wav\"\r\n"
            f"Content-Type: audio/wav\r\n\r\n").encode() + wav + f"\r\n--{boundary}--\r\n".encode()
    path = f"/v1/session/{sid}/recording"
    h = p.headers("POST", path, body)
    h["content-type"] = f"multipart/form-data; boundary={boundary}"
    return p.client.post(path, content=body, headers=h)


def test_recording_upload(world, tmp_path):
    w = world(30)
    w.run_attempt(0)
    cap = w.a.last["capture"]
    r = _upload(w.a, w.sid, _wav(cap, 48000), {"attempt": 0})
    assert r.status_code == 200 and r.json() == {"ok": True, "stored": True}
    assert (tmp_path / "sessions" / w.sid / "recording_A_0.wav").exists()
    bad = cap.copy()
    bad[100] ^= 1
    r = _upload(w.a, w.sid, _wav(bad, 48000), {"attempt": 0})
    assert r.status_code == 400 and r.json()["error"] == "transcript_mismatch"


FIELD = Path(os.environ.get("POP_FIELD_DATA", Path(__file__).resolve().parents[2]
                            / "research/sound-bound/spikes/melody/fieldtest/data/sessions"))


def _field_bg(session_prefix: str):
    wf = pytest.importorskip("scipy.io.wavfile")
    hits = sorted(FIELD.glob(f"{session_prefix}*/recording_B.wav")) if FIELD.is_dir() else []
    if not hits:
        pytest.skip("field recordings absent")
    sr0, x = wf.read(str(hits[0]))
    x = np.asarray(x, dtype=np.float64)

    def bg(n, sr, rng):
        assert sr == sr0
        i0 = int(22.2 * sr)                     # the JBL250 rounds of that walk (old seed = interference)
        return x[i0:i0 + n].copy()
    return bg


@pytest.mark.parametrize("prefix,d,verdict", [("b9e4dd4b", 30, "NEAR"), ("d1ee4fb0", 100, "NOT_NEAR")])
def test_real_room_background(world, prefix, d, verdict):
    w = world(d, kb=Knobs(sr=48000, mono_off_ns=7, sync_err_ms=-4, out_lat_ms=30), background=_field_bg(prefix))
    w.run_attempt(0)
    rec = w.result().json()
    assert rec["verdict"] == verdict and rec["flight_cm"] == pytest.approx(d, abs=3)
