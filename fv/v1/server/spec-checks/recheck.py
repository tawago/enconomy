"""Rechecks the code facts that fv/v1/server/spec.md cites. Runs the real server code through its real HTTP routes.

This is not the walk test. It only pins the facts the spec leans on, so nobody has to trust a reading.
It shows the server follows its rules on signed numbers. It says nothing about the air (CN1).

Run from fv/v1/server, with the repo's top-level server/ folder at commit 9db1490 (see fv/v1/server/README.md):
  python spec-checks/recheck.py
It imports the server from that top-level folder, so what is checked is whatever commit sits there.
Each line is  [PASS|FAIL] id: what. Exit code 1 if any line fails.
"""
from __future__ import annotations

import base64
import copy
import json
import random
import struct
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

SERVER = Path(__file__).resolve().parents[4] / "server"
sys.path.insert(0, str(SERVER))

from fastapi.testclient import TestClient  # noqa: E402

from pop import constants as K, jbl250, verdict as V  # noqa: E402
from pop.auth import Authenticator  # noqa: E402
from pop.codec import decode_transcript, encode_commit, encode_transcript  # noqa: E402
from pop.crypto import P256_N, sign_raw  # noqa: E402
from pop.main import Settings, create_app  # noqa: E402
from pop.store import SqliteStore  # noqa: E402
from tests.phones import Clock, Phone  # noqa: E402

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

fails = 0


def check(cid: str, what: str, ok: bool, extra="") -> None:
    global fails
    fails += 0 if ok else 1
    print(f"[{'PASS' if ok else 'FAIL'}] {cid}: {what}" + (f"  ({extra})" if extra != "" else ""), flush=True)


def b64(x: bytes) -> str:
    return base64.b64encode(x).decode()


class TickClock(Clock):
    """A clock that can move by itself on each read, to show two reads inside one handler can differ."""
    tick = 0

    def __call__(self) -> int:
        self.ms += self.tick
        return self.ms


class Walk:
    """Two enrolled phones and one session, driven through HTTP. No audio anywhere: the numbers are chosen."""

    def __init__(self, raise_500=True):
        self.tmp = tempfile.mkdtemp()
        self.clock = TickClock()
        cfg = Settings(db=":memory:", allow_unattested=True, now_ms=self.clock, data_dir=self.tmp,
                       issuer_key_file=f"{self.tmp}/issuer.pem", worldid_signing_key_file=f"{self.tmp}/rp.key",
                       attest_key_file=f"{self.tmp}/attest.pem", worldid_bg_poll=False, worldid_poll_s=0.0)
        self.store = SqliteStore(":memory:")
        self.app = create_app(cfg, self.store)
        self.client = TestClient(self.app, raise_server_exceptions=raise_500)
        self.a, self.b = Phone(self.client, self.clock, "A"), Phone(self.client, self.clock, "B")
        assert self.a.enroll(attested=False).status_code == 200
        assert self.b.enroll(attested=False).status_code == 200
        self.seen: list[str] = []   # every response body any phone got

    def req(self, p, method, path, body=None, **kw):
        r = p.call(method, path, body, **kw)
        self.seen.append(r.text)
        return r

    def post(self, p, path, body=None, **kw):
        return self.req(p, "POST", f"/v1/session/{self.sid}{path}", body, **kw)

    def view(self, p):
        return self.req(p, "GET", f"/v1/session/{self.sid}").json()

    def doc(self):
        return self.store.get_session(self.sid)

    def pair(self):
        r = self.req(self.a, "POST", "/v1/session", {})
        self.created = r.json()
        self.sid = self.created["session_id"]
        self.nonce = bytes.fromhex(self.created["nonce"])
        self.join_view = self.post(self.b, "/join", {"join_token": self.created["join_token"]}).json()
        self.post(self.a, "/confirm")
        self.post(self.b, "/confirm")
        return self

    def arm(self, attempt=0, sr_a=48000, sr_b=48000, popt=1):
        ra = self.post(self.a, "/arm", {"attempt": attempt, "sample_rate": sr_a, "rtt_min_ms": 10, "popt": popt})
        rb = self.post(self.b, "/arm", {"attempt": attempt, "sample_rate": sr_b, "rtt_min_ms": 10, "popt": popt})
        self.t0 = self.doc()["t0_ms"]
        return ra, rb

    def commit_body(self, p, role, attempt, rec=b"\x11" * 32, version=1):
        raw = encode_commit(role, attempt, self.nonce, rec, version)
        return raw, {"commit_b64": b64(raw), "sig_b64": b64(sign_raw(p.sk, raw))}

    def commit(self, p, role, attempt, rec=b"\x11" * 32, version=1):
        raw, body = self.commit_body(p, role, attempt, rec, version)
        import hashlib
        self.__dict__.setdefault("csha", {})[role] = hashlib.sha256(raw).digest()
        return self.post(p, "/commit", body)

    def tx(self, p, other, role, attempt, half, sr=48000, delta=0, rec=b"\x11" * 32, sign=None, **over):
        t = {"role": role, "attempt": attempt, "nonce": self.nonce, "pk_self": p.pub, "pk_partner": other.pub,
             "sample_rate": sr, "half": half, "rec_sha256": rec, "play_frame_position": 0, "play_nano_time": 0,
             "rec_frame0_nano_time": 0, "self_os_delta": delta, "commit_hash": self.csha[role], **over}
        raw = encode_transcript(t)
        return {"transcript_b64": b64(raw), "sig_b64": b64(sign_raw(sign or p.sk, raw))}

    def submit(self, p, other, role, attempt, half, **kw):
        return self.post(p, "/transcript", self.tx(p, other, role, attempt, half, **kw))

    def attempt(self, attempt, ha, hb, da=0, db=0, sr_a=48000, sr_b=48000):
        self.arm(attempt, sr_a, sr_b)
        self.clock.ms = self.t0 + 1200
        self.commit(self.a, "A", attempt)
        self.commit(self.b, "B", attempt)
        r1 = self.submit(self.a, self.b, "A", attempt, ha, sr=sr_a, delta=da)
        r2 = self.submit(self.b, self.a, "B", attempt, hb, sr=sr_b, delta=db)
        return r1, r2

    def result(self):
        return self.req(self.a, "GET", f"/v1/session/{self.sid}/result").json()


def halves_for(f_cm: Fraction, sr=48000):
    """hA, hB at equal rates with flight exactly f_cm, when representable."""
    n = f_cm * 2 * sr / K.SPEED_OF_SOUND_CM_S
    return int(round(n)), 0


# ---- V1, V2, V3, V4: the numbers
def numbers():
    for f, want in [(-21, (None, "impossible_flight")), (-20, (None, "impossible_flight")),
                    (Fraction(-19999, 1000), ("NEAR", None)), (0, ("NEAR", None)), (Fraction(59999, 1000), ("NEAR", None)),
                    (60, ("NOT_NEAR", "too_far")), (61, ("NOT_NEAR", "too_far"))]:
        check("V2", f"decide({f})", V.decide(f) == want, V.decide(f))
    check("V2-note", "decide(float nan) says NEAR; only a direct float call can reach it, combine passes a Fraction",
          V.decide(float("nan")) == ("NEAR", None))
    rng, bad = random.Random(20261106), 0
    N = 200000
    for _ in range(N):
        sa, sb = rng.randint(K.SR_MIN, K.SR_MAX), rng.randint(K.SR_MIN, K.SR_MAX)
        if rng.random() < 0.5:   # close to the band, or the test only sees big numbers
            hb = rng.randint(-2 ** 31, 2 ** 31 - 1)
            ha = min(2 ** 31 - 1, max(-2 ** 31, int(hb * sa / sb) + rng.randint(-700, 700)))
        else:
            ha, hb = rng.randint(-2 ** 31, 2 ** 31 - 1), rng.randint(-2 ** 31, 2 ** 31 - 1)
        n, s = ha * sb - hb * sa, sa * sb
        exact = V.decide(V.flight_exact(ha, sa, hb, sb))[0] == "NEAR"
        bad += exact != (-40 * s < 34300 * n < 120 * s)
    check("V3", f"integer form equals exact form on {N} random inputs", bad == 0, f"{bad} disagree")
    # ties: flight exactly -20 and 60. 34300 N = -40 S at sr_a = sr_b = 34300, outside the rate range, so use 68600.
    sr = 68600
    check("V3", "tie at exactly -20 is not NEAR", V.flight_exact(-80, sr, 0, sr) == -20 and
          V.decide(V.flight_exact(-80, sr, 0, sr))[0] is None)
    check("V3", "tie at exactly 60 is not NEAR", V.flight_exact(240, sr, 0, sr) == 60 and
          V.decide(V.flight_exact(240, sr, 0, sr))[0] == "NOT_NEAR")
    for ha, sa, hb, sb, shown in [(95, 48000, -67, 44100, 60.0), (79, 48000, 124, 44100, -20.0)]:
        f = V.flight_exact(ha, sa, hb, sb)
        check("V1-note", f"NEAR can show flight_cm {shown}", V.decide(f)[0] == "NEAR" and round(float(f), 2) == shown, float(f))
    # V4
    check("V4", "no cal, 48000: 2400 frames ok, 2401 not", V.self_os_ok(2400, 48000) and not V.self_os_ok(2401, 48000))
    check("V4", "no cal, 48000: -2400 ok, -2401 not", V.self_os_ok(-2400, 48000) and not V.self_os_ok(-2401, 48000))
    check("V4", "cal 10000 us, 48000: 480+2400 ok, 480+2401 not, 480-2400 ok, 480-2401 not",
          V.self_os_ok(2880, 48000, 10000) and not V.self_os_ok(2881, 48000, 10000)
          and V.self_os_ok(-1920, 48000, 10000) and not V.self_os_ok(-1921, 48000, 10000))
    check("V4", "44100: 2205 ok, 2206 not", V.self_os_ok(2205, 44100) and not V.self_os_ok(2206, 44100))
    check("V4", "commit gate is 1200 ms by the same float sum the code uses", int((K.B_PLAY_S + K.CODE_S) * 1000) == 1200)
    t = lambda role, me, pa, half, d, version=None: {  # noqa: E731
        "role": role, "nonce": b"n" * 32, "attempt": 0, "pk_self": me, "pk_partner": pa, "half": half,
        "sample_rate": 48000, "self_os_delta": d, **({"version": version} if version else {})}
    ka, kb = b"a" * 65, b"b" * 65
    # delta 2880 frames = 60 ms. v1 with 10 ms cal passes at the 50 ms edge. v2 ignores cal and fails.
    check("V4", "v1 uses cal", V.combine(t("A", ka, kb, 0, 2880), t("B", kb, ka, 0, 0), {"A": 10000})["verdict"] == "NEAR")
    r = V.combine(t("A", ka, kb, 0, 2880, 2), t("B", kb, ka, 0, 0, 2), {"A": 10000})
    check("V4", "v2 ignores cal", r["reason"] == "self_timestamp_mismatch" and r["by"] == "A", r)
    # V5 on combine
    try:
        V.combine(t("B", kb, ka, 0, 0), t("A", ka, kb, 0, 0))
        check("V5", "combine refuses swapped arguments", False)
    except V.Reject as e:
        check("V5", "combine refuses swapped arguments", e.reason == "transcript_mismatch", e.reason)
    try:
        V.combine({**t("A", ka, kb, 0, 0), "sample_rate": 0}, t("B", kb, ka, 0, 0))
        check("doc-combine", "combine alone with rate 0 stays a clean result", True)
    except ZeroDivisionError:
        check("doc-combine", "combine has no rate check of its own: rate 0 raises ZeroDivisionError, only a direct call", True)


# ---- walks
def x1_no_audio():
    w = Walk().pair()
    r1, r2 = w.attempt(0, 100, 0)
    rec = w.result()
    check("X1", "v1: two signers, chosen numbers, no audio: NEAR", rec["verdict"] == "NEAR" and r2.status_code == 200, rec["flight_cm"])
    check("V7", "verify_record agrees on a NEAR record", V.verify_record(rec) ==
          {"flight_cm": rec["flight_cm"], "verdict": "NEAR", "reason": None, "by": None})
    check("M11", "single-read clock: finished_ms <= t0 + 20 s and >= t0 + 1200", w.t0 + 1200 <= w.doc()["finished_ms"] <= w.t0 + 20000)
    # replay facts
    bad = copy.deepcopy(rec); bad["verdict"] = "NOT_NEAR"
    check("V7", "verify_record does not read the record's verdict field", V.verify_record(bad)["verdict"] == "NEAR")
    bad = copy.deepcopy(rec); bad["devices"]["A"]["half"] = 999999; bad["flight_cm"] = 1.0
    check("V7", "verify_record does not read the record's devices.half or flight_cm", V.verify_record(bad)["flight_cm"] == rec["flight_cm"])
    bad = copy.deepcopy(rec); bad["devices"]["A"]["cal_us"] = 200000
    check("V7", "cal_us in the record is unsigned and moves a v1 replay", V.verify_record(bad)["reason"] == "self_timestamp_mismatch")
    # V5 on the record
    sw = copy.deepcopy(rec); sw["transcripts"]["A"], sw["transcripts"]["B"] = sw["transcripts"]["B"], sw["transcripts"]["A"]
    try:
        V.verify_record(sw); check("V5", "record with transcripts swapped is refused", False)
    except V.Reject as e:
        check("V5", "record with transcripts swapped is refused, reason is signature_invalid", e.reason == "signature_invalid", e.reason)
    sw = copy.deepcopy(rec)
    for k in ("transcripts", "commits", "devices"):
        sw[k]["A"], sw[k]["B"] = sw[k]["B"], sw[k]["A"]
    try:
        V.verify_record(sw); check("V5", "record with transcripts, commits and keys all swapped is refused", False)
    except V.Reject as e:
        check("V5", "record with transcripts, commits and keys all swapped is refused, transcript_mismatch", e.reason == "transcript_mismatch", e.reason)
    # seed and token
    d = w.doc()
    check("M5", "seed is in no response of a NEAR walk", not any(d["seed_hex"] in x for x in w.seen))
    check("M5", "join token only in the create response", sum(d["join_token"] in x for x in w.seen) == 1)
    check("M6", "last_flight_cm and per_role are in no response", not any("last_flight_cm" in x or '"per_role"' in x for x in w.seen))
    r = w.submit(w.a, w.b, "A", 0, 100)
    check("doc-resend", "a resend after done is 409 bad_state, not idempotent", r.status_code == 409 and r.json()["error"] == "bad_state", r.text)
    # abort is a no-op on done
    before = w.doc(); w.post(w.a, "/abort"); after = w.doc()
    check("M1", "abort on done changes nothing", before == after)
    r = w.post(w.a, "/fail", {"attempt": 0, "reason": "glitch"})
    check("M1", "fail on done is 409", r.status_code == 409)


def x1_v2():
    w = Walk().pair()
    w.arm(0, popt=2)
    w.clock.ms = w.t0 + 1200
    rec = b"\x01" * 32
    ra = w.commit(w.a, "A", 0, rec, 2).json()
    rb = w.commit(w.b, "B", 0, rec, 2).json()
    from pop.popt2 import delta
    def sub(p, o, role, half, cc):
        t = {"version": 2, "role": role, "attempt": 0, "nonce": w.nonce, "pk_self": p.pub, "pk_partner": o.pub,
             "sample_rate": 48000, "half": half, "rec_root": rec, "play_frame_position": 0, "play_nano_time": 0,
             "rec_frame0_nano_time": 0, "self_os_delta": 0, "commit_hash": w.csha[role], "a_self": 100, "p_partner": 200,
             "delta": delta(48000), "code_commit": bytes.fromhex(cc)}
        raw = encode_transcript(t)
        return w.post(p, "/transcript", {"transcript_b64": b64(raw), "sig_b64": b64(sign_raw(p.sk, raw))})
    sub(w.a, w.b, "A", 100, ra["code_commit"]); sub(w.b, w.a, "B", 0, rb["code_commit"])
    r = w.result()
    check("X1", "v2: two signers, chosen numbers, no audio: NEAR", r["verdict"] == "NEAR", r["flight_cm"])
    check("V7", "verify_record agrees, v2", V.verify_record(r)["verdict"] == "NEAR")


def far_and_map():
    w = Walk().pair()
    w.attempt(0, 48000, 0)
    rec = w.result()
    check("V7", "too_far: record and replay agree", rec["verdict"] == "NOT_NEAR" and rec["reason"] == "too_far"
          and V.verify_record(rec)["verdict"] == "NOT_NEAR" and V.verify_record(rec)["reason"] == "too_far")
    check("M7", "too_far never retries", rec["attempt"] == 0 and w.doc()["state"] == "done")

    w = Walk().pair()
    w.attempt(0, -987654, 0)
    d = w.doc()
    check("M7", "impossible_flight at attempt 0 retries", d["state"] == "confirmed" and d["attempt"] == 1, d["last_failure"]["reason"])
    va = w.view(w.a)
    check("M6", "retry view shows reason and no number", va["last_failure"]["reason"] == "impossible_flight"
          and "987654" not in json.dumps(va), va["last_failure"])
    check("M9", "retry resets flags and t0, keeps confirmed", not any(d["armed"].values()) and not any(d["committed"].values())
          and not any(d["submitted"].values()) and d["t0_ms"] is None and all(d["confirmed"].values()) and d["per_role"] == {"A": {}, "B": {}})
    check("M6", "old numbers stay inside the document", d["attempts"][0]["per_role"]["A"]["half"] == -987654 and d["last_flight_cm"] is not None)
    w.attempt(1, -987654, 0)
    rec = w.result()
    check("V7", "impossible_flight twice: record NOT_NEAR, replay verdict None, same reason",
          rec["verdict"] == "NOT_NEAR" and rec["reason"] == "impossible_flight" and
          V.verify_record(rec)["verdict"] is None and V.verify_record(rec)["reason"] == "impossible_flight")
    check("M7", "second failure is final, attempt stays 1", rec["attempt"] == 1 and w.doc()["state"] == "done")

    w = Walk().pair()
    w.attempt(0, -987654, 0)
    w.attempt(1, 100, 0)
    rec = w.result()
    check("M8", "NEAR at attempt 1 after a failed attempt 0", rec["verdict"] == "NEAR" and rec["attempt"] == 1)
    check("M6", "attempt 0's half is nowhere in the final record or any response",
          "987654" not in json.dumps(rec) and not any("987654" in x for x in w.seen))
    check("M6", "the failed attempt's flight is not in the record", set(rec["attempts"][0]) == {"attempt", "outcome", "reason", "by"})

    w = Walk().pair()
    w.attempt(0, 0, 0, da=5000)
    w.attempt(1, 0, 0, db=5000)
    rec = w.result()
    check("V7", "self_timestamp_mismatch twice: record NOT_NEAR by B, replay verdict None with by B",
          rec["verdict"] == "NOT_NEAR" and rec["reason"] == "self_timestamp_mismatch" and
          V.verify_record(rec)["verdict"] is None and V.verify_record(rec)["by"] == "B", rec["attempts"][-1])

    # bad transcript: final, and the record can't replay
    w = Walk().pair(); w.arm(); w.clock.ms = w.t0 + 1200
    w.commit(w.a, "A", 0); w.commit(w.b, "B", 0)
    w.submit(w.a, w.b, "A", 0, 4242)
    r = w.post(w.b, "/transcript", w.tx(w.b, w.a, "B", 0, 0, sign=w.a.sk))
    rec = w.view(w.b)["result"]
    check("T-bad", "bad transcript from a member: 400 and done NOT_NEAR, at attempt 0", r.status_code == 400 and rec["verdict"] == "NOT_NEAR"
          and rec["reason"] == "signature_invalid", r.text)
    check("M6", "session over: the partner now reads A's half (C18)", rec["devices"]["A"]["half"] == 4242)
    try:
        V.verify_record(rec); check("V7", "rejected record raises", False)
    except V.Reject as e:
        check("V7", "rejected record raises", True, e.detail)

    # fail: from confirmed, no measurement; partner_mismatch final
    w = Walk().pair()
    r = w.post(w.b, "/fail", {"attempt": 0, "reason": "partner_mismatch"})
    d = w.doc()
    check("T-fail", "partner_mismatch from confirmed is final with no measurement", d["state"] == "done" and d["result"]["verdict"] == "NOT_NEAR", r.status_code)
    w = Walk().pair()
    w.post(w.b, "/fail", {"attempt": 0, "reason": "glitch"})
    w.post(w.b, "/fail", {"attempt": 1, "reason": "glitch"})
    d = w.doc()
    check("X2", "one member alone ends the session NOT_NEAR with no measurement", d["state"] == "done" and d["result"]["reason"] == "glitch" and d["t0_ms"] is None)
    # final fail after the partner's transcript
    w = Walk().pair(); w.post(w.b, "/fail", {"attempt": 0, "reason": "glitch"}); w.arm(1); w.clock.ms = w.t0 + 1200
    w.commit(w.a, "A", 1); w.submit(w.a, w.b, "A", 1, 777)
    v = w.view(w.b)
    check("M6", "live: B sees submitted A and no half", v["submitted"]["A"] and v["result"] is None and "777" not in json.dumps({k: v[k] for k in ("result", "last_failure", "submitted", "committed")}))
    w.post(w.b, "/fail", {"attempt": 1, "reason": "glitch"})
    check("M6", "final fail: B then reads A's half in the result", w.view(w.b)["result"]["devices"]["A"]["half"] == 777)


def gates():
    w = Walk().pair()
    check("doc-nonce", "create returns the nonce to the host at once", len(w.created["nonce"]) == 64)
    check("doc-nonce", "view hides it until both confirm, join_view had it null", w.join_view["nonce"] is None)
    ra, rb = w.arm()
    check("M5", "arm response has own code only", "partner_bed" not in ra.json() and "partner_code" not in ra.json() and "own_bed" in ra.json())
    w.clock.ms = w.t0 + 1199
    r = w.commit(w.a, "A", 0)
    check("M5", "commit at t0 + 1199 is 409 too_early, no change", r.status_code == 409 and r.json()["error"] == "too_early" and not w.doc()["committed"]["A"])
    w.clock.ms = w.t0 + 1200
    r = w.commit(w.a, "A", 0)
    check("M5", "commit at t0 + 1200 returns the partner's bed", r.status_code == 200 and "partner_bed" in r.json())
    want = jbl250.bed_key(w.doc()["seed_hex"], "B", 0)
    check("M5", "released bed is B's for attempt 0", r.json()["partner_bed"]["pcm_b64"] == __import__("pop.codec", fromlist=["pcm"]).pcm(jbl250.template(want, "B", 48000))["pcm_b64"])
    # idempotent commit, other sig
    raw, body = w.commit_body(w.a, "A", 0)
    before = w.doc()
    r = w.post(w.a, "/commit", body)
    check("M10", "same commit, fresh signature: partner bed again, no change", r.status_code == 200 and "partner_bed" in r.json() and before == w.doc())
    r = w.post(w.a, "/commit", w.commit_body(w.a, "A", 0, b"\x22" * 32)[1])
    check("M10", "other commit is 409 already_committed, no change", r.status_code == 409 and r.json()["error"] == "already_committed" and before == w.doc())
    r = w.post(w.a, "/commit", w.commit_body(w.a, "A", 1)[1])
    check("T-commit", "commit for the wrong attempt is 400, no change", r.status_code == 400 and before == w.doc())
    r = w.post(w.b, "/transcript", {"transcript_b64": "AAAA", "sig_b64": "AAAA"})
    check("T-tx", "transcript before own commit is 409 even if junk, no change", r.status_code == 409 and r.json()["detail"] == "commit first")
    # second key: B's code differs per attempt
    keys = {jbl250.bed_key(w.doc()["seed_hex"], ro, at) for ro in "AB" for at in (0, 1)}
    check("M8", "four distinct keys per (role, attempt)", len(keys) == 4)
    # non-member, join rules
    c = Phone(w.client, w.clock, "C"); c.enroll(attested=False)
    for path in ("/confirm", "/abort", "/commit", "/transcript", "/fail", "/arm"):
        body = {"commit_b64": "", "sig_b64": ""} if path == "/commit" else {"transcript_b64": "", "sig_b64": ""} if path == "/transcript" else {}
        before = w.doc()
        r = c.post(f"/v1/session/{w.sid}{path}", body)
        check("M12", f"non-member {path} is 403, no change", r.status_code == 403 and before == w.doc(), r.status_code)
    r = c.post(f"/v1/session/{w.sid}/join", {"join_token": w.created["join_token"]})
    check("M12", "second join is 409 already_joined even with the token", r.status_code == 409)
    w2 = Walk(); w2.sid = None
    r = w2.a.post("/v1/session", {}); w2.sid = r.json()["session_id"]
    r2 = w2.a.post(f"/v1/session/{w2.sid}/join", {"join_token": r.json()["join_token"]})
    check("M12", "host can't join itself", r2.status_code == 400 and r2.json()["error"] == "self_join")
    r = w.client.post(f"/v1/session/{w.sid}/confirm")
    check("M12", "no auth headers: 401", r.status_code == 401)

    # stale transcript and stale fail after a retry
    w = Walk().pair(); w.arm(); w.clock.ms = w.t0 + 1200; w.commit(w.a, "A", 0)
    old = w.tx(w.a, w.b, "A", 0, 5)
    w.post(w.b, "/fail", {"attempt": 0, "reason": "glitch"})
    before = w.doc()
    r = w.post(w.a, "/transcript", old)
    check("M8", "signed transcript of the old attempt: 409 stale_attempt, no change", r.status_code == 409 and r.json()["error"] == "stale_attempt" and before == w.doc())
    r = w.post(w.a, "/fail", {"attempt": 0, "reason": "glitch"})
    check("M8", "fail for the old attempt: 409 stale_attempt, no change", r.status_code == 409 and r.json()["error"] == "stale_attempt" and before == w.doc())
    # same at attempt 1 and committed: commit of attempt 0 refused
    w.arm(1); w.clock.ms = w.t0 + 1200
    r = w.post(w.a, "/commit", w.commit_body(w.a, "A", 0)[1])
    check("M8", "commit of the old attempt: 400, no change", r.status_code == 400 and not w.doc()["committed"]["A"])


def timing():
    # M12 note: anyone with the session id can fire the lazy timeout, no auth
    w = Walk().pair(); w.arm(); w.clock.ms = w.t0 + 20001
    r = w.client.get(f"/v1/session/{w.sid}/relay")
    d = w.doc()
    check("M12-restated", "unauthenticated /relay fires the lazy timeout", d["attempt"] == 1 and d["state"] == "confirmed" and d["last_failure"]["reason"] == "timeout", r.status_code)
    w = Walk().pair(); w.arm(); w.clock.ms = w.t0 + 20000
    w.view(w.a)
    check("M11", "exactly t0 + 20 s is not late", w.doc()["state"] == "started")
    c = Phone(w.client, w.clock, "C"); c.enroll(attested=False)
    w.clock.ms = w.t0 + 20001
    r = c.get(f"/v1/session/{w.sid}")
    check("M12-restated", "non-member gets 403 and the timeout still fired", r.status_code == 403 and w.doc()["attempt"] == 1)
    # age and token aborts
    w = Walk(); r = w.a.post("/v1/session", {}); w.sid = r.json()["session_id"]; w.clock.ms += 120001
    w.a.get(f"/v1/session/{w.sid}")
    d = w.doc()
    check("T-expire", "created past the token: aborted timeout, no finished_ms, no attempts row", d["state"] == "aborted" and d["error"] == "timeout" and d["finished_ms"] is None and d["attempts"] == [])
    w = Walk().pair(); w.arm(); w.clock.ms = d["created_ms"]
    d0 = w.doc(); w.clock.ms = d0["created_ms"] + 600001
    w.view(w.a)
    d = w.doc()
    check("T-expire", "started past 600 s: aborted timeout, not done, no result", d["state"] == "aborted" and d["result"] is None and d["finished_ms"] is None)
    w = Walk().pair(); d0 = w.doc(); w.clock.ms = d0["created_ms"] + 600000; w.view(w.a)
    check("M11", "exactly created + 600 s is not late", w.doc()["state"] == "confirmed")
    # M11: two clock reads
    done = None
    for off in range(-12, 1):
        w = Walk().pair(); w.arm(); w.clock.ms = w.t0 + 1200
        w.commit(w.a, "A", 0); w.commit(w.b, "B", 0); w.submit(w.a, w.b, "A", 0, 100)
        body = w.tx(w.b, w.a, "B", 0, 0)
        w.clock.ms = w.t0 + 20000 + off; w.clock.tick = 1
        r = w.post(w.b, "/transcript", body)
        w.clock.tick = 0
        d = w.doc()
        if d["state"] == "done" and d["result"]["verdict"] == "NEAR" and d["finished_ms"] > w.t0 + 20000:
            done = d["finished_ms"] - w.t0 - 20000
    check("M11-restated", "real clock moves inside a handler: finished_ms can pass t0 + 20 s by the handler's run time", done is not None, f"by {done} ticks")


def auth_replay():
    w = Walk().pair()
    path = "/v1/session"
    raw = json.dumps({}).encode()
    h = w.a.headers("POST", path, raw)
    r1 = w.client.post(path, content=raw, headers=h)
    r2 = w.client.post(path, content=raw, headers=h)
    check("R1", "exact replay is 401 auth_replay", r1.status_code == 200 and r2.status_code == 401 and r2.json()["error"] == "auth_replay", r2.text)
    sig = h["X-Pop-Sig"]
    alpha = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    assert sig.endswith("==")
    i = alpha.index(sig[-3])
    other = sig[:-3] + alpha[i ^ 1] + "=="
    r3 = w.client.post(path, content=raw, headers={**h, "X-Pop-Sig": other})
    check("R1-gap", "same signature, other base64 spelling, is accepted as new", r3.status_code == 200, r3.status_code)
    s = base64.b64decode(sig)
    flipped = s[:32] + (P256_N - int.from_bytes(s[32:], "big")).to_bytes(32, "big")
    r4 = w.client.post(path, content=raw, headers={**h, "X-Pop-Sig": b64(flipped)})
    check("R1-gap", "same message, s flipped to n - s, is accepted as new", r4.status_code == 200, r4.status_code)


def route_edges():
    """The number edges again, this time through the real routes and not by calling decide directly."""
    sr = 68600   # flight is a whole number of cm at this rate: 240 frames = 60, -80 frames = -20
    for ha, want in [(239, "NEAR"), (240, "NOT_NEAR"), (-79, "NEAR")]:
        w = Walk().pair(); w.attempt(0, ha, 0, sr_a=sr, sr_b=sr)
        r = w.doc()["result"]
        check("V1-route", f"halves {ha}, 0 at {sr}: {want}", r["verdict"] == want, f"flight_cm {r['flight_cm']}, reason {r['reason']}")
    w = Walk().pair(); w.attempt(0, -80, 0, sr_a=sr, sr_b=sr)
    d = w.doc()
    check("V1-route", f"halves -80, 0 at {sr}: flight exactly -20 retries", d["attempt"] == 1 and d["last_failure"]["reason"] == "impossible_flight")
    w = Walk().pair(); w.attempt(0, 240, 0, sr_a=sr, sr_b=sr)
    check("V1-route", f"halves 240, 0 at {sr}: flight exactly 60 is too_far", w.doc()["result"]["reason"] == "too_far")
    for ha, sa, hb, sb, shown in [(95, 48000, -67, 44100, 60.0), (79, 48000, 124, 44100, -20.0)]:
        w = Walk().pair(); w.attempt(0, ha, hb, sr_a=sa, sr_b=sb)
        r = w.doc()["result"]
        check("V8", f"through the routes: NEAR shown as {shown}", r["verdict"] == "NEAR" and r["flight_cm"] == shown, r["flight_cm"])
    for da, db, near in [(2400, -2400, True), (2401, 0, False), (0, -2401, False)]:
        w = Walk().pair(); w.attempt(0, 100, 0, da=da, db=db)
        d = w.doc()
        if near:
            check("V1-route", f"self deltas {da}, {db} at 48000: NEAR", d["result"]["verdict"] == "NEAR")
        else:
            check("V1-route", f"self deltas {da}, {db} at 48000: retry, right role named", d["attempt"] == 1
                  and d["last_failure"]["reason"] == "self_timestamp_mismatch" and d["last_failure"]["by"] == ("A" if da else "B"), d["last_failure"]["by"])
    # X1 domain: both ends of the wire field and both ends of the rate range
    for h in (2 ** 31 - 1, -2 ** 31):
        w = Walk().pair(); w.attempt(0, h, h)
        check("X1", f"halves both {h}: NEAR, no audio", w.doc()["result"]["verdict"] == "NEAR", w.doc()["result"]["flight_cm"])
    w = Walk().pair(); w.attempt(0, 0, 0, sr_a=36000, sr_b=96000)
    check("X1", "rates 36000 and 96000: NEAR, no audio", w.doc()["result"]["verdict"] == "NEAR")
    w = Walk().pair(); w.arm(); w.clock.ms = w.t0 + 1200; w.commit(w.a, "A", 0)
    try:
        w.tx(w.a, w.b, "A", 0, 2 ** 31); check("X1", "half 2^31 can't be encoded", False)
    except struct.error as e:
        check("X1", "half 2^31 can't be encoded, so no such run exists", True, e)


def table_paths():
    # arm: popt
    for label, extra, code, popt in [("absent", {}, 200, 1), ("null", {"popt": None}, 200, 1), ("2", {"popt": 2}, 200, 2)]:
        w = Walk().pair()
        r = w.post(w.a, "/arm", {"attempt": 0, "sample_rate": 48000, "rtt_min_ms": 10, **extra})
        check("T-arm", f"popt {label}: arms at {popt}", r.status_code == code and w.doc()["per_role"]["A"]["popt"] == popt)
    for bad in (3, "2", True):
        w = Walk().pair(); before = w.doc()
        r = w.post(w.a, "/arm", {"attempt": 0, "sample_rate": 48000, "rtt_min_ms": 10, "popt": bad})
        check("T-arm", f"popt {bad!r}: 400, no change", r.status_code == 400 and before == w.doc())
    # transcript: bad base64 is final once the sender has committed, and is 409 before that
    for field in ("transcript_b64", "sig_b64"):
        w = Walk().pair(); w.arm(); w.clock.ms = w.t0 + 1200; w.commit(w.a, "A", 0)
        r = w.post(w.a, "/transcript", {**w.tx(w.a, w.b, "A", 0, 1), field: "!!!"})
        d = w.doc()
        check("T-tx", f"bad base64 in {field} after commit: 400, final, outcome rejected", r.status_code == 400
              and r.json()["error"] == "transcript_mismatch" and d["state"] == "done" and d["attempts"][-1]["outcome"] == "rejected")
    w = Walk().pair(); w.arm(); w.clock.ms = w.t0 + 1200; before = w.doc()
    r = w.post(w.a, "/transcript", {"transcript_b64": "!!!", "sig_b64": "!!!"})
    check("T-tx", "bad base64 before commit: 409, no change", r.status_code == 409 and before == w.doc())
    # M10: which different one gets which answer
    w = Walk().pair(); w.arm(); w.clock.ms = w.t0 + 1200; w.commit(w.a, "A", 0); before = w.doc()
    raw = encode_commit("A", 0, w.nonce, b"\x22" * 32, 1)
    r = w.post(w.a, "/commit", {"commit_b64": b64(raw), "sig_b64": b64(sign_raw(w.b.sk, raw))})
    check("M10", "different commit, wrong signature: 400 signature_invalid, not 409, no change", r.status_code == 400
          and r.json()["error"] == "signature_invalid" and before == w.doc())
    body = w.tx(w.a, w.b, "A", 0, 5)
    r1 = w.post(w.a, "/transcript", body); before = w.doc()
    r2 = w.post(w.a, "/transcript", body)
    check("M10", "same transcript strings: accepted again, no change", r1.status_code == 200 and r2.status_code == 200 and before == w.doc())
    r = w.post(w.a, "/transcript", w.tx(w.a, w.b, "A", 0, 6))
    check("M10", "different transcript: 409 already_submitted, no change", r.status_code == 409 and r.json()["error"] == "already_submitted" and before == w.doc())
    r = w.post(w.a, "/transcript", {**w.tx(w.a, w.b, "A", 0, 6), "sig_b64": b64(b"x" * 64)})
    check("M10", "different transcript, bad signature: also 409, the signature isn't read here", r.status_code == 409 and before == w.doc())
    # X2: abort needs nobody else, even in created. The others need the partner to have moved first.
    w = Walk(); w.sid = w.a.post("/v1/session", {}).json()["session_id"]
    r = w.post(w.a, "/abort"); d = w.doc()
    check("X2", "host alone, right after create: /abort ends the session", r.status_code == 200 and d["state"] == "aborted" and d["error"] == "aborted")
    w = Walk(); c = w.a.post("/v1/session", {}).json(); w.sid = c["session_id"]
    r = w.post(w.a, "/fail", {"attempt": 0, "reason": "partner_mismatch"})
    check("X2", "host alone, right after create: /fail is 409", r.status_code == 409 and w.doc()["state"] == "created")
    w = Walk().pair(); w.post(w.a, "/arm", {"attempt": 0, "sample_rate": 48000, "rtt_min_ms": 10}); before = w.doc()
    r = w.post(w.a, "/transcript", {"transcript_b64": "!!!", "sig_b64": "!!!"})
    check("X2", "partner not armed: a bad transcript is only 409, no change", r.status_code == 409 and before == w.doc())


def order_before_handler():
    # Past the deadline, so any load would fire _expire and change the document.
    w = Walk().pair(); w.arm(); w.clock.ms = w.t0 + 20001
    before = w.doc()
    for path in ("/join", "/arm", "/commit", "/transcript", "/fail"):
        r = w.client.post(f"/v1/session/{w.sid}{path}", content=b"{not json", headers={"content-type": "application/json"})
        check("Order", f"{path}: bad JSON, no auth: 400 before auth, no load", r.status_code == 400 and r.json()["error"] == "bad_request"
              and "json_invalid" in r.json()["detail"] and before == w.doc(), r.status_code)
    r = w.client.post("/v1/session/00/join", content=b"{not json", headers={"content-type": "application/json"})
    check("Order", "unknown session, bad JSON, no auth: still 400, not 404", r.status_code == 400)
    for path in ("/confirm", "/abort"):
        r = w.client.post(f"/v1/session/{w.sid}{path}", content=b"{not json", headers={"content-type": "application/json"})
        check("Order", f"{path} takes no body: bad JSON, no auth is 401", r.status_code == 401 and before == w.doc(), r.status_code)
    r = w.client.post(f"/v1/session/{w.sid}/join", content=b"{not json", headers={"content-type": "text/plain"})
    check("Order", "bad JSON sent as text/plain, no auth: not parsed, so auth answers", r.status_code == 401, r.status_code)
    r = w.client.post(f"/v1/session/{w.sid}/join", content=b"{not json")
    check("Order", "bad JSON with no content type, no auth: not parsed, so auth answers", r.status_code == 401, r.status_code)
    r = w.client.post(f"/v1/session/{w.sid}/join", content=b"{}", headers={"content-type": "application/json"})
    check("Order", "valid JSON of the wrong shape, no auth: 401", r.status_code == 401 and before == w.doc(), r.status_code)
    r = w.post(w.a, "/commit", {"wrong": 1})
    check("Order", "wrong shape, good auth: 400, no load", r.status_code == 400 and before == w.doc(), r.status_code)
    r = w.req(w.a, "POST", "/v1/session/00/join", {"wrong": 1})
    check("Order", "wrong shape, good auth, unknown session: 400, not 404", r.status_code == 400, r.status_code)
    raw = json.dumps({"join_token": "x"}).encode()
    r = w.client.post("/v1/session/00/join", content=raw, headers={**w.a.headers("POST", "/v1/session/00/join", raw), "content-type": "text/plain"})
    check("Order", "good JSON sent as text/plain, good auth, unknown session: 400 at the shape step, not 404", r.status_code == 400, r.status_code)
    r = w.req(w.a, "POST", "/v1/session/00/join", {"join_token": "x"})
    check("Order", "right shape, good auth, unknown session: 404", r.status_code == 404, r.status_code)
    r = w.post(w.a, "/confirm")
    check("Order", "good request: the load fires the timeout, and the change is saved", r.status_code == 200 and w.doc()["attempt"] == 1, r.status_code)


def auth_edges():
    def first(d):
        w = Walk(); path = "/v1/session"; raw = b"{}"
        t = w.clock.ms
        h = w.a.headers("POST", path, raw, ts=t + d)
        return w, path, raw, h, t, w.client.post(path, content=raw, headers=h)
    w, path, raw, h, t, r = first(60000)
    check("R1-edge", "ts = now + 60 s is accepted", r.status_code == 200)
    w.clock.ms = t + 119999
    r = w.client.post(path, content=raw, headers=h)
    check("R1-edge", "same headers at + 119999 ms: 401 auth_replay", r.status_code == 401 and r.json()["error"] == "auth_replay", r.json()["error"])
    w.clock.ms = t + 120000
    r = w.client.post(path, content=raw, headers=h)
    check("R1-edge", "same headers at exactly + 120000 ms: 200, accepted a second time", r.status_code == 200, r.status_code)
    w, path, raw, h, t, r = first(60000)
    w.clock.ms = t + 120001
    r = w.client.post(path, content=raw, headers=h)
    check("R1-edge", "same headers at + 120001 ms: 401 auth_stale", r.status_code == 401 and r.json()["error"] == "auth_stale", r.json()["error"])
    w, path, raw, h, t, r = first(59999)
    w.clock.ms = t + 120000
    r = w.client.post(path, content=raw, headers=h)
    check("R1-edge", "ts = now + 59999 ms, same headers at + 120000 ms: 401 auth_stale", r.status_code == 401 and r.json()["error"] == "auth_stale", r.json()["error"])
    w = Walk(raise_500=False)
    ts = "1" * 5000
    r = w.client.post("/v1/session", content=b"{}", headers={"X-Pop-Device": w.a.device_id, "X-Pop-Ts": ts, "X-Pop-Sig": "AAAA"})
    check("E500-ts", "known device, X-Pop-Ts of 5000 digits: uncaught, a 500 and not a 401 (TestClient)", r.status_code == 500, r.status_code)
    r = w.client.post("/v1/session", content=b"{}", headers={"X-Pop-Device": "00" * 16, "X-Pop-Ts": ts, "X-Pop-Sig": "AAAA"})
    check("E500-ts", "unknown device, same ts: 401", r.status_code == 401, r.status_code)
    # Direct call: the test client re-encodes header bytes, so this one can't go through it.
    a = Authenticator(w.store, w.clock)
    try:
        a.check("POST", "/v1/session", b"{}", {"x-pop-device": w.a.device_id, "x-pop-ts": "\u00b2", "x-pop-sig": "AAAA"})
        check("E500-ts", "X-Pop-Ts = superscript 2 is refused", False)
    except ValueError as e:
        check("E500-ts", "direct call, X-Pop-Ts = superscript 2: isdigit passes, int raises ValueError", True, e)


def junk():
    w = Walk().pair()
    try:
        r = w.post(w.a, "/fail", {"attempt": 0, "reason": []})
        check("E500", "reason = [] gets a clean 400", r.status_code == 400, r.status_code)
    except TypeError as e:
        check("E500", "fail with reason = [] is an uncaught TypeError, a 500; document unchanged", w.doc()["state"] == "confirmed", e)
    w = Walk(); r = w.a.post("/v1/session", {}); w.sid = r.json()["session_id"]
    try:
        r = w.post(w.b, "/join", {"join_token": "é"})
        check("E500", "non-ascii join token gets a clean 403", r.status_code == 403, r.status_code)
    except TypeError as e:
        check("E500", "non-ascii join token is an uncaught TypeError, a 500; document unchanged", w.doc()["state"] == "created", e)


def create_and_query():
    """Create's own refusals, and the query check on view. Only the paths a context=None, human=none session can take."""
    w = Walk()
    count = lambda: w.store._db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]  # noqa: E731
    path, n = "/v1/session", count()
    for label, raw, code, err in [("not JSON", b"{not json", 400, "bad_request"), ("a list, not an object", b"[1]", 400, "bad_request"),
                                  ("bad policy", b'{"policy":{"human":"x"}}', 400, "bad_policy"),
                                  ("policy not an object", b'{"policy":3}', 400, "bad_policy")]:
        r = w.client.post(path, content=raw, headers=w.a.headers("POST", path, raw))
        check("T-create", f"create, {label}: {code} {err}, nothing stored", r.status_code == code and r.json()["error"] == err and count() == n, r.text[:60])
    r = w.client.post(path, content=b"{not json", headers={"content-type": "application/json"})
    check("T-create", "create, not JSON, no auth: 401, auth comes first here", r.status_code == 401 and count() == n, r.status_code)
    r = w.client.post(path, content=b"", headers=w.a.headers("POST", path, b""))
    check("T-create", "create, empty body: 200, plain session", r.status_code == 200 and count() == n + 1, r.status_code)
    w = Walk().pair()
    good = f"/v1/session/{w.sid}?after=x"
    r = w.client.get(good, headers=w.a.headers("GET", good, b""))
    check("Order", "view, after=x, good auth: 400", r.status_code == 400 and r.json()["error"] == "bad_request", r.status_code)
    r = w.client.get(good)
    check("Order", "view, after=x, no auth: 401, auth first", r.status_code == 401, r.status_code)
    bad = "/v1/session/00?after=x"
    r = w.client.get(bad, headers=w.a.headers("GET", bad, b""))
    check("Order", "view, after=x, good auth, unknown session: 400, not 404, so no load", r.status_code == 400, r.status_code)
    late = f"/v1/session/{w.sid}?after=x"
    w.arm(); w.clock.ms = w.t0 + 20001; before = w.doc()
    r = w.client.get(late, headers=w.a.headers("GET", late, b""))
    check("Order", "view, after=x, past the deadline: 400, timeout not fired", r.status_code == 400 and before == w.doc(), r.status_code)


def join_edges():
    done = False
    for off in range(-12, 1):
        w = Walk(); c = w.a.post("/v1/session", {}).json(); w.sid = c["session_id"]
        w.clock.ms = w.doc()["token_expires_ms"] + off; w.clock.tick = 1
        r = w.post(w.b, "/join", {"join_token": c["join_token"]})
        w.clock.tick = 0
        d = w.doc()
        if r.status_code == 410 and d["state"] == "created":
            done = True
    check("T-join", "token runs out between the load's clock read and join's own: 410, state stays created", done)
    w = Walk(); c = w.a.post("/v1/session", {}).json(); w.sid = c["session_id"]
    r = w.post(w.b, "/join", {"join_token": c["join_token"].upper()})
    check("T-join", "join token in upper case is accepted, it's lowered first", r.status_code == 200, r.status_code)
    upper = f"/v1/session/{w.sid.upper()}"
    r = w.client.get(upper, headers=w.a.headers("GET", upper, b""))
    check("T-join", "session id in upper case finds the session, load lowers it", r.status_code == 200, r.status_code)


def resend_and_v5_live():
    # resend after a retry: the stale check comes first
    w = Walk().pair(); w.arm(); w.clock.ms = w.t0 + 1200; w.commit(w.a, "A", 0)
    body = w.tx(w.a, w.b, "A", 0, 5)
    check("doc-resend", "first send accepted", w.post(w.a, "/transcript", body).status_code == 200)
    w.post(w.b, "/fail", {"attempt": 0, "reason": "glitch"})
    before = w.doc()
    r = w.post(w.a, "/transcript", body)
    check("doc-resend", "same transcript after a retry, state confirmed: 409 stale_attempt, no change", r.status_code == 409 and r.json()["error"] == "stale_attempt" and before == w.doc(), r.json()["error"])
    w.arm(1); before = w.doc()
    r = w.post(w.a, "/transcript", body)
    check("doc-resend", "same transcript after a retry, state started: 409 stale_attempt, no change", r.status_code == 409 and r.json()["error"] == "stale_attempt" and before == w.doc(), r.json()["error"])
    w = Walk().pair(); w.arm(); w.clock.ms = w.t0 + 1200; w.commit(w.a, "A", 0)
    body = w.tx(w.a, w.b, "A", 0, 5); w.post(w.a, "/transcript", body); w.post(w.b, "/abort")
    r = w.post(w.a, "/transcript", body)
    check("doc-resend", "same transcript after an abort: 409 bad_state", r.status_code == 409 and r.json()["error"] == "bad_state", r.json()["error"])
    # V5, the live row: A signs a transcript that says role B
    w = Walk().pair(); w.arm(); w.clock.ms = w.t0 + 1200; w.commit(w.a, "A", 0); w.commit(w.b, "B", 0)
    r = w.post(w.a, "/transcript", w.tx(w.a, w.b, "B", 0, 1))
    d = w.doc()
    check("V5", "live: A signs a transcript with role B: 400 transcript_mismatch, final NOT_NEAR", r.status_code == 400
          and r.json()["error"] == "transcript_mismatch" and d["state"] == "done" and d["result"]["verdict"] == "NOT_NEAR", r.json()["error"])


def v7_one_sided():
    def raises(rec):
        try:
            V.verify_record(rec)
            return False
        except V.Reject:
            return True
    w = Walk().pair(); w.post(w.b, "/fail", {"attempt": 0, "reason": "glitch"}); w.arm(1); w.clock.ms = w.t0 + 1200
    w.commit(w.a, "A", 1); w.submit(w.a, w.b, "A", 1, 777); w.post(w.b, "/fail", {"attempt": 1, "reason": "glitch"})
    rec = w.result()
    check("V7", "final fail, one transcript in: replay raises Reject", rec["attempts"][-1]["outcome"] == "failed" and rec["reason"] == "glitch" and raises(rec))
    w = Walk().pair(); w.post(w.b, "/fail", {"attempt": 0, "reason": "glitch"}); w.arm(1); w.clock.ms = w.t0 + 1200
    w.commit(w.a, "A", 1); w.submit(w.a, w.b, "A", 1, 777); w.clock.ms = w.t0 + 20001
    rec = w.result()
    check("V7", "final timeout, one transcript in: replay raises Reject", rec["reason"] == "timeout" and rec["attempts"][-1]["by"] == "B" and raises(rec))
    w = Walk().pair(); w.post(w.b, "/fail", {"attempt": 0, "reason": "partner_mismatch"})
    check("V7", "final fail, no transcript at all: replay raises Reject", raises(w.result()))


def m6_leak():
    """What a retry report says. combine checks A's self delta, then B's, then flight, and stops at the first that fails."""
    for da, db, ha, reason, by in [(5000, 5000, -987654, "self_timestamp_mismatch", "A"), (5000, 0, -987654, "self_timestamp_mismatch", "A"),
                                   (0, 5000, -987654, "self_timestamp_mismatch", "B"), (0, 0, -987654, "impossible_flight", None)]:
        w = Walk().pair(); w.attempt(0, ha, 0, da=da, db=db)
        va, vb = w.view(w.a), w.view(w.b)
        lf = va["last_failure"]
        check("M6-leak", f"self deltas {da}, {db}, flight far below -20: {reason}, by {by}", lf["reason"] == reason and lf["by"] == by
              and va["last_failure"] == vb["last_failure"] and va["state"] == "confirmed" and "987654" not in json.dumps(va), lf)


def deep_meta():
    """A meta that is too deep for a later save. depth counts containers, the outer dict included."""
    def post_deep(w, depth):
        path = f"/v1/session/{w.sid}/transcript"
        b = w.tx(w.a, w.b, "A", 0, 100)
        meta = '{"x":' + "[" * (depth - 1) + "]" * (depth - 1) + "}"
        raw = ('{"transcript_b64":"%s","sig_b64":"%s","meta":%s}' % (b["transcript_b64"], b["sig_b64"], meta)).encode()
        return w.client.post(path, content=raw, headers=w.a.headers("POST", path, raw))

    def setup():
        w = Walk(raise_500=False).pair(); w.arm(); w.clock.ms = w.t0 + 1200
        w.commit(w.a, "A", 0); w.commit(w.b, "B", 0)
        return w

    band, unreadable = [], []
    for depth in [5000, 9000] + list(range(9980, 10000)):
        w = setup()
        r = post_deep(w, depth)
        saved = w.doc()["submitted"]["A"]
        va = w.req(w.a, "GET", f"/v1/session/{w.sid}").status_code
        rb = w.submit(w.b, w.a, "B", 0, 0)
        d = w.doc()
        print(f"[INFO] E500-meta scan: depth {depth}: A {r.status_code}{'' if r.status_code == 200 else ' ' + r.text[:40]}, stored {saved}, A view {va}, "
              f"B {rb.status_code}, then state {d['state']}, verdict {(d['result'] or {}).get('verdict')}", flush=True)
        if saved and va != 200:
            unreadable.append(depth)
        if r.status_code == 200 and rb.status_code == 500:
            band.append(depth)
    check("E500-meta", "a depth exists where A gets 200 and B's good transcript gets 500", bool(band), band)
    check("E500-meta", "no accepted depth leaves a document that can't be read back", not unreadable, unreadable)
    for depth in band:
        w = setup()
        check("E500-meta", f"depth {depth}: A 200", post_deep(w, depth).status_code == 200)
        before = w.doc()
        b = w.tx(w.b, w.a, "B", 0, 0)
        r1, r2 = w.post(w.b, "/transcript", b), w.post(w.b, "/transcript", b)
        check("E500-meta", f"depth {depth}: B's transcript, good numbers, and its resend: 500, stored document unchanged",
              r1.status_code == 500 and r2.status_code == 500 and before == w.doc() and before["state"] == "started")
        r = w.post(w.b, "/fail", {"attempt": 0, "reason": "glitch"})
        check("E500-meta", f"depth {depth}: B's fail: 500, unchanged", r.status_code == 500 and before == w.doc(), r.status_code)
        r = w.post(w.b, "/transcript", {"transcript_b64": "!!!", "sig_b64": "!!!"})
        check("E500-meta", f"depth {depth}: B's bad transcript: 500 and not the usual 400, unchanged", r.status_code == 500 and before == w.doc(), r.status_code)
        w.clock.ms = w.t0 + 20000
        check("E500-meta", f"depth {depth}: at t0 + 20000 view still works", w.req(w.a, "GET", f"/v1/session/{w.sid}").status_code == 200)
        w.clock.ms = w.t0 + 20001
        rv, rab, rel = w.req(w.b, "GET", f"/v1/session/{w.sid}"), w.post(w.b, "/abort"), w.client.get(f"/v1/session/{w.sid}/relay")
        check("E500-meta", f"depth {depth}: from t0 + 20001 view and abort: 500, as is the no-auth relay, unchanged",
              rv.status_code == 500 and rab.status_code == 500 and rel.status_code == 500 and before == w.doc(), (rv.status_code, rab.status_code, rel.status_code))
        w.clock.ms = before["created_ms"] + 600001
        rv = w.req(w.b, "GET", f"/v1/session/{w.sid}")
        d = w.doc()
        check("E500-meta", f"depth {depth}: after created + 600001: view 200, aborted, timeout, no result",
              rv.status_code == 200 and d["state"] == "aborted" and d["error"] == "timeout" and d["result"] is None, d["state"])
        w = setup(); post_deep(w, depth)
        r = w.post(w.b, "/abort")
        check("E500-meta", f"depth {depth}: abort before the deadline works, its row holds no per_role", r.status_code == 200 and w.doc()["state"] == "aborted", r.status_code)
    w = setup(); post_deep(w, 9000); w.submit(w.b, w.a, "B", 0, 0)
    check("E500-meta", "depth 9000: the session finishes as usual", w.doc()["result"]["verdict"] == "NEAR")
    w = setup(); r = post_deep(w, 100000)
    check("E500-meta", "depth 100000: refused on A's own request, unchanged", r.status_code >= 400 and not w.doc()["submitted"]["A"], f"{r.status_code} {r.text[:60]}")


if __name__ == "__main__":
    print("spec recheck. Says the server follows its rules on signed numbers. Says nothing about the air (CN1).")
    numbers(); x1_no_audio(); x1_v2(); far_and_map(); gates(); timing(); auth_replay(); junk()
    route_edges(); table_paths(); order_before_handler(); auth_edges()
    create_and_query(); join_edges(); resend_and_v5_live(); v7_one_sided(); m6_leak(); deep_meta()
    print(f"done, {fails} failed")
    sys.exit(1 if fails else 0)
