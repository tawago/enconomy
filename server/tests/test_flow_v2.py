"""POPT v2 over HTTP with fake phones (tests/sim2.py): popt switch at arm, codes, POPC v2 / POPT v2 checks,
mixed v1 + v2 pair, rec_root upload check. The captures and verdict math are tests/sim.py's."""
import base64
import io
import wave

import numpy as np
import pytest

from pop import popt2, poseidon7
from pop.codec import b64d, decode_transcript, encode_commit
from pop.crypto import sign_raw
from pop.verdict import verify_record
from tests.sim import Knobs, b64
from tests.sim2 import World2, code_of
from tests.test_flow_fake_phones import _upload


@pytest.fixture
def world(make_client, clock):
    def make(d, ka=None, kb=None, **kw):
        w = World2(make_client(allow_unattested=True), clock, d, ka or Knobs(),
                   kb or Knobs(sr=44100, mono_off_ns=9_000_000_000, sync_err_ms=-3, out_lat_ms=25), **kw)
        w.pair()
        return w
    return make


def test_near_v2_real_root(world):
    w = world(30)
    out = w.run_attempt(0)
    assert out["A"].status_code == 200 and out["B"].json()["state"] == "done", out["B"].text
    rec = w.result().json()
    assert rec["verdict"] == "NEAR" and rec["flight_cm"] == pytest.approx(30, abs=2)
    assert {r: rec["devices"][r]["popt"] for r in "AB"} == {"A": 2, "B": 2}
    for p in w.phones:
        raw = b64d(rec["transcripts"][p.role]["transcript_b64"])
        t = decode_transcript(raw)
        assert len(raw) == 311 and t["version"] == 2 and t["rec_root"] == poseidon7.rec_root(p.last["capture"])
        assert t["a_partner"] == p.last["a_partner"] and t["p_self"] == p.last["p_self"]
        assert abs(t["self_os_delta"]) <= t["delta"]      # provable: inside the circuit's 2 ms window
        assert b64d(rec["commits"][p.role]["commit_b64"])[4] == 2
    assert verify_record(rec)["verdict"] == "NEAR"
    assert w.view()["popt"] == {"A": 2, "B": 2}


def test_codes_on_the_wire(world):
    w = world(30, real_root=False)
    ja = w.a.arm(0)
    seed = w.doc()["seed_hex"]
    from pop import jbl250
    ka, kb = jbl250.bed_key(seed, "A", 0), jbl250.bed_key(seed, "B", 0)
    assert code_of(ja["own_code"]) == popt2.code(ka, "A", 48000) and ja["own_code"]["n"] == 12000
    assert "partner_code" not in ja and "partner_bed" not in ja
    w.b.arm(0)
    t0 = w.view()["t0_ms"]
    w.clock.ms = t0 + 1500
    cap = w.capture(w.a, t0, 0)
    commit = encode_commit("A", 0, w.a.nonce, poseidon7.rec_root(cap[:5000]), version=2)
    r = w.a.post(f"/v1/session/{w.sid}/commit", {"commit_b64": b64(commit), "sig_b64": b64(sign_raw(w.a.sk, commit))})
    assert r.status_code == 200 and code_of(r.json()["partner_code"]) == popt2.code(kb, "B", 48000)
    # B listens at 44.1 kHz: its own code is at its rate
    assert w.b.own_code == popt2.code(kb, "B", 44100) and len(w.b.own_code[0]) == 11025


@pytest.mark.parametrize("d", [100])
def test_far_v2(world, d):
    w = world(d, real_root=False)
    w.run_attempt(0)
    rec = w.result().json()
    assert rec["verdict"] == "NOT_NEAR" and rec["reason"] == "too_far" and rec["flight_cm"] == pytest.approx(d, abs=2)


def test_mixed_v1_v2(world):
    w = world(30, v1=("B",), real_root=False)
    w.run_attempt(0)
    rec = w.result().json()
    assert rec["verdict"] == "NEAR" and {r: rec["devices"][r]["popt"] for r in "AB"} == {"A": 2, "B": 1}
    assert len(b64d(rec["transcripts"]["B"]["transcript_b64"])) == 269
    assert verify_record(rec)["verdict"] == "NEAR"


def test_bad_code_commit_final(world):
    w = world(30, real_root=False)
    w.b.code_commit_override = b"\x00" * 32
    out = w.run_attempt(0)
    assert out["B"].status_code == 400 and out["B"].json()["error"] == "transcript_mismatch"
    assert "code_commit" in out["B"].json()["detail"]
    assert w.result().json()["reason"] == "transcript_mismatch"


def test_bad_delta_final(world):
    w = world(30, real_root=False)
    w.a.delta_override = 97
    out = w.run_attempt(0)
    assert out["A"].status_code == 400 and "delta" in out["A"].json()["detail"]


def test_self_os_tolerance_shared(world):
    """|sod| <= SELF_OS_TOL_MS passes the plaintext verdict even outside the circuit's 2 ms; beyond it retries."""
    w = world(30, ka=Knobs(self_os_delta_override=2400), real_root=False)   # exactly 50 ms at 48 kHz
    w.run_attempt(0)
    assert w.view()["state"] == "done"
    w2 = world(30, ka=Knobs(self_os_delta_override=2401), real_root=False)
    w2.run_attempt(0)
    v = w2.view()
    assert v["attempt"] == 1 and v["last_failure"]["reason"] == "self_timestamp_mismatch"


def test_commit_version_must_match_arm(world):
    w = world(30, real_root=False)
    w.a.commit_version = 1
    out = w.run_attempt(0)
    assert out["A"].status_code == 400 and "POPC version" in out["A"].json()["detail"]
    assert w.view()["committed"]["A"] is False      # a bad commit changes nothing


def test_v1_armed_phone_cannot_send_v2(world):
    w = world(30, v1=("A",), real_root=False)
    w.a.arm(0)
    w.b.arm(0)
    t0 = w.view()["t0_ms"]
    w.clock.ms = t0 + 1500
    commit = encode_commit("A", 0, w.a.nonce, b"\x01" * 32, version=2)
    r = w.a.post(f"/v1/session/{w.sid}/commit", {"commit_b64": b64(commit), "sig_b64": b64(sign_raw(w.a.sk, commit))})
    assert r.status_code == 400 and r.json()["error"] == "transcript_mismatch"


def test_arm_popt_validation(world):
    w = world(30, real_root=False)
    base = {"attempt": 0, "sample_rate": 48000, "rtt_min_ms": 5}
    for bad in (0, 3, "2", True, 2.0):
        r = w.a.post(f"/v1/session/{w.sid}/arm", base | {"popt": bad})
        assert r.status_code == 400, bad
    assert w.a.post(f"/v1/session/{w.sid}/arm", base | {"popt": 2}).status_code == 200
    assert w.a.post(f"/v1/session/{w.sid}/arm", base | {"popt": 2}).status_code == 200     # idempotent
    r = w.a.post(f"/v1/session/{w.sid}/arm", base | {"popt": 1})
    assert r.status_code == 409 and "popt" in r.json()["detail"]
    r = w.a.post(f"/v1/session/{w.sid}/arm", base)          # omitted = 1
    assert r.status_code == 409


def test_rec_root_commit_must_be_canonical(world):
    w = world(30, real_root=False)
    w.a.arm(0)
    w.b.arm(0)
    w.clock.ms = w.view()["t0_ms"] + 1500
    commit = encode_commit("A", 0, w.a.nonce, poseidon7.P.to_bytes(32, "big"), version=2)
    r = w.a.post(f"/v1/session/{w.sid}/commit", {"commit_b64": b64(commit), "sig_b64": b64(sign_raw(w.a.sk, commit))})
    assert r.status_code == 400 and "rec_root" in r.json()["detail"]


def _wav(x: np.ndarray, sr: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sr)
        f.writeframes(x.astype("<i2").tobytes())
    return buf.getvalue()


def test_recording_upload_rec_root(world):
    w = world(30)
    w.run_attempt(0, skip=("A",))
    x = w.b.last["capture"]
    r = _upload(w.b, w.sid, _wav(x, 44100), {"attempt": 0})
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    y = x.copy()
    y[5000] ^= 1
    r = _upload(w.b, w.sid, _wav(y, 44100), {"attempt": 0})
    assert r.status_code == 400 and "rec_root" in r.json()["detail"]
