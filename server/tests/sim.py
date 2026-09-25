"""Fake phones that run the whole pop-v1 flow over HTTP (contract §3-§8), DSP = pop.dsp_ref.

World: one true timeline (server clock, ns). Each phone has its own monotonic clock
(mono = true + mono_off_ns), a clock-sync error, an output latency and a sample rate.
The harness (not the phones) renders both sounds into each phone's capture at the true
arrival frames: onset + distance / c. It reads the partner's PCM from the server's own
jbl250 (a phone never gets it). Background = white noise, or a real field recording crop.
"""
from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field

import numpy as np

from pop import constants as K
from pop import dsp_ref as D
from pop import jbl250
from pop.codec import encode_commit, encode_transcript, pcm_decode
from pop.crypto import sign_raw
from tests.phones import Phone

C_CM_S = K.SPEED_OF_SOUND_CM_S
OTHER = {"A": "B", "B": "A"}


def b64(x: bytes) -> str:
    return base64.b64encode(x).decode()


@dataclass
class Knobs:
    sr: int = 48000
    mono_off_ns: int = 123_456_789_000
    sync_err_ms: float = 2.0         # clock-sync error (only moves the search windows)
    out_lat_ms: float = 15.0         # speaker path latency, seen by getTimestamp
    self_gain: float = 0.3
    partner_gain: float = 0.12
    zero_block: tuple[float, float] | None = None   # (start_s, dur_s) in the capture, attempt 0 only
    # misbehaviour, for negative tests
    half_bias: int = 0
    self_os_delta_override: int | None = None
    fail_at: dict = field(default_factory=dict)      # attempt -> reason posted instead of measuring


class FakePhone(Phone):
    def __init__(self, client, clock, name, model, role: str, knobs: Knobs | None = None):
        super().__init__(client, clock, name, model)
        self.role, self.k = role, knobs or Knobs()
        self.sid = self.nonce = None
        self.partner_pub: bytes | None = None
        self.offset_ns = 0
        self.log: list = []

    # monotonic clock
    def mono(self, true_ns: float) -> float:
        return true_ns + self.k.mono_off_ns

    def clock_sync(self):
        best = None
        for _ in range(10):
            t0 = self.mono(self.clock() * 1e6)
            srv = self.client.get("/v1/time").json()["server_ms"]
            t1 = self.mono(self.clock() * 1e6)
            if best is None or t1 - t0 < best[0]:
                best = (t1 - t0, t0, srv)
        rtt, t0, srv = best
        self.offset_ns = srv * 1e6 - (t0 + rtt / 2) + self.k.sync_err_ms * 1e6
        return rtt / 1e6

    def arm(self, attempt: int):
        rtt = self.clock_sync()
        r = self.post(f"/v1/session/{self.sid}/arm", {"attempt": attempt, "sample_rate": self.k.sr, "rtt_min_ms": rtt})
        assert r.status_code == 200, r.text
        j = r.json()
        self.attempt, self.play, self.own_bed = attempt, pcm_decode(j["play"]), pcm_decode(j["own_bed"]).astype(float)
        return j

    # the true times the world needs
    def true_onset_ns(self, t0_ms: int) -> float:
        """Sound onset on the true timeline: phone schedules by its (slightly wrong) t0 estimate."""
        rel = K.A_PLAY_S if self.role == "A" else K.B_PLAY_S
        return t0_ms * 1e6 - self.k.sync_err_ms * 1e6 + rel * 1e9 + self.k.out_lat_ms * 1e6

    def true_cap0_ns(self, t0_ms: int) -> float:
        return t0_ms * 1e6 - self.k.sync_err_ms * 1e6 - K.LEAD_S * 1e9

    # -- per-phone procedure (§6.6), after the world handed us the capture
    def measure_and_submit(self, t0_ms: int, capture: np.ndarray, attempt: int):
        sr, role, other = self.k.sr, self.role, OTHER[self.role]
        if attempt in self.k.fail_at:
            return self.post(f"/v1/session/{self.sid}/fail", {"attempt": attempt, "reason": self.k.fail_at[attempt]})
        rec_sha = hashlib.sha256(capture.astype("<i2").tobytes()).digest()
        rec_frame0_ns = self.mono(self.true_cap0_ns(t0_ms))
        play_onset_ns = self.mono(self.true_onset_ns(t0_ms))
        primer = round(K.PRIMER_S * sr)
        play_frame_position = primer + 2 * round(K.CODE_S * sr)      # after the track drained
        play_nano_time = play_onset_ns + (play_frame_position - primer) * 1e9 / sr
        L = self.own_bed.size
        exp_self = (play_onset_ns - rec_frame0_ns) * sr / 1e9
        runs = D.flat_runs(capture, sr)
        w0, w1 = D.window(exp_self, sr, capture.size)
        if D.glitch(runs, w0, w1 + L):
            return self._fail(attempt, "glitch")
        a_self = D.measure_arrival(capture, sr, self.own_bed, D.nulls(self.sid, role, attempt, sr), exp_self)
        if not a_self.found:
            return self._fail(attempt, "self_not_heard")
        delta = int(round(a_self.frame - exp_self))
        if self.k.self_os_delta_override is not None:
            delta = self.k.self_os_delta_override
        elif not abs(delta) <= K.SELF_OS_TOL_MS * sr / 1000:
            return self._fail(attempt, "self_timestamp_mismatch")
        commit = encode_commit(role, attempt, self.nonce, rec_sha)
        r = self.post(f"/v1/session/{self.sid}/commit", {"commit_b64": b64(commit), "sig_b64": b64(sign_raw(self.sk, commit))})
        assert r.status_code == 200, r.text
        partner_bed = pcm_decode(r.json()["partner_bed"]).astype(float)
        t0_mono = t0_ms * 1e6 - self.offset_ns
        p_off = K.B_PLAY_S if role == "A" else K.A_PLAY_S
        exp_partner = (t0_mono + p_off * 1e9 - rec_frame0_ns) * sr / 1e9
        v0, v1 = D.window(exp_partner, sr, capture.size)
        if D.glitch(runs, min(w0, v0), max(w1, v1) + L):
            return self._fail(attempt, "glitch")
        a_p = D.measure_arrival(capture, sr, partner_bed, D.nulls(self.sid, other, attempt, sr), exp_partner)
        if not a_p.found:
            return self._fail(attempt, "partner_not_heard")
        half = D.half(a_self.frame, a_p.frame, role) + self.k.half_bias
        t = {"role": role, "attempt": attempt, "nonce": self.nonce, "pk_self": self.pub, "pk_partner": self.partner_pub,
             "sample_rate": sr, "half": half, "rec_sha256": rec_sha, "play_frame_position": play_frame_position,
             "play_nano_time": int(play_nano_time), "rec_frame0_nano_time": int(rec_frame0_ns),
             "self_os_delta": delta, "commit_hash": hashlib.sha256(commit).digest()}
        raw = encode_transcript(t)
        meta = {"t_self": a_self.frame, "t_partner": a_p.frame, "expected_self": exp_self, "expected_partner": exp_partner,
                "score_self": a_self.score, "bar_self": a_self.bar, "score_partner": a_p.score, "bar_partner": a_p.bar,
                "null_max_self": a_self.null_max, "null_max_partner": a_p.null_max, "ts_source": "timestamp",
                "security_level": "software", "flat_runs": runs, "model": self.model}
        self.last = {"transcript": t, "raw": raw, "commit": commit, "capture": capture, "meta": meta}
        body = {"transcript_b64": b64(raw), "sig_b64": b64(sign_raw(self.sk, raw)), "meta": meta}
        return self.post(f"/v1/session/{self.sid}/transcript", body)

    def _fail(self, attempt, reason):
        self.log.append((attempt, reason))
        return self.post(f"/v1/session/{self.sid}/fail", {"attempt": attempt, "reason": reason})


class World:
    """Two fake phones, distance_cm apart, one server."""

    def __init__(self, client, clock, distance_cm: float, ka: Knobs | None = None, kb: Knobs | None = None,
                 background=None, seed: int = 7):
        self.client, self.clock, self.d = client, clock, distance_cm
        self.a = FakePhone(client, clock, "Alice", "Pixel 8", "A", ka)
        self.b = FakePhone(client, clock, "Bob", "Galaxy S23", "B", kb)
        self.rng = np.random.default_rng(seed)
        self.background = background   # callable(n, sr, rng) -> float array, or None for noise

    @property
    def phones(self):
        return self.a, self.b

    def pair(self):
        a, b = self.phones
        for p in self.phones:
            assert p.enroll(attested=False).status_code == 200
        c = a.post("/v1/session").json()
        sid = c["session_id"]
        assert b.post(f"/v1/session/{sid}/join", {"join_token": c["join_token"]}).status_code == 200
        a.post(f"/v1/session/{sid}/confirm")
        v = b.post(f"/v1/session/{sid}/confirm").json()
        assert v["state"] == "confirmed"
        for p, q in ((a, b), (b, a)):
            p.sid, p.nonce, p.partner_pub = sid, bytes.fromhex(v["nonce"]), q.pub
        self.sid = sid
        return sid

    def doc(self):
        return self.client.app.state.store.get_session(self.sid)

    def capture(self, listener: FakePhone, t0_ms: int, attempt: int) -> np.ndarray:
        sr = listener.k.sr
        n = round(K.CAPTURE_S * sr)
        x = (self.background(n, sr, self.rng) if self.background else self.rng.normal(0, 0.003, n)).astype(np.float64)
        seed = self.doc()["seed_hex"]
        cap0 = listener.true_cap0_ns(t0_ms)
        for em in self.phones:
            key = jbl250.bed_key(seed, em.role, attempt)
            s = jbl250.render(key, em.role, sr)[0].astype(np.float64)
            path_cm = 0.0 if em is listener else self.d
            g = listener.k.self_gain if em is listener else listener.k.partner_gain
            at = int(round((em.true_onset_ns(t0_ms) + path_cm / C_CM_S * 1e9 - cap0) * sr / 1e9))
            lo, hi = max(0, at), min(n, at + s.size)
            if hi > lo:
                x[lo:hi] += g * s[lo - at:hi - at]
        pcm = np.clip(np.round(x * 32767), -32768, 32767).astype(np.int16)
        zb = listener.k.zero_block
        if zb is not None and attempt == 0:
            i0 = round(zb[0] * sr)
            pcm[i0:i0 + round(zb[1] * sr)] = 0
        return pcm

    def run_attempt(self, attempt: int, submit_order=("A", "B"), skip=()):
        """arm both, wait for t0, record, commit, measure, submit. Returns {role: response}."""
        a, b = self.phones
        for p in self.phones:
            p.arm(attempt)
        t0 = a.get(f"/v1/session/{self.sid}").json()["t0_ms"]
        assert t0 is not None
        caps = {p.role: self.capture(p, t0, attempt) for p in self.phones}
        self.clock.ms = t0 + int((K.B_PLAY_S + K.CODE_S + 0.3) * 1000)
        out = {}
        for r in submit_order:
            if r in skip:
                continue
            p = a if r == "A" else b
            out[r] = p.measure_and_submit(t0, caps[r], attempt)
        return out

    def view(self, p=None):
        return (p or self.a).get(f"/v1/session/{self.sid}").json()

    def result(self, p=None):
        return (p or self.a).get(f"/v1/session/{self.sid}/result")
