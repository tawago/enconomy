"""Fake phones on POPT v2 (docs/pop-transcript-v2.md): arm with popt 2, integer arrival rule (tests/twin2.py)
with the server's int8 codes, rec_root commit (POPC v2), 311-byte transcript. World/capture as tests/sim.py.
"""
from __future__ import annotations

import base64
import hashlib

import numpy as np

from pop import constants as K
from pop import popt2, poseidon2
from pop.codec import encode_commit, encode_transcript
from pop.crypto import sign_raw
from tests import sim, twin2
from tests.sim import Knobs, b64


def code_of(d: dict) -> tuple[bytes, bytes]:
    return base64.b64decode(d["cI_b64"]), base64.b64decode(d["cQ_b64"])


def fake_root(capture: np.ndarray) -> bytes:
    """Stand-in rec_root (< p) for tests that never upload: the server only compares it with the commit."""
    return (int.from_bytes(hashlib.sha256(capture.tobytes()).digest(), "big") >> 3).to_bytes(32, "big")


class FakePhone2(sim.FakePhone):
    real_root = True
    code_commit_override: bytes | None = None
    delta_override: int | None = None
    commit_version = 2

    def arm(self, attempt: int):
        rtt = self.clock_sync()
        r = self.post(f"/v1/session/{self.sid}/arm",
                      {"attempt": attempt, "sample_rate": self.k.sr, "rtt_min_ms": rtt, "popt": 2})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["popt"] == 2 and j["delta"] == popt2.delta(self.k.sr)
        self.attempt, self.own_code = attempt, code_of(j["own_code"])
        return j

    def measure_and_submit(self, t0_ms: int, capture: np.ndarray, attempt: int):
        sr, role = self.k.sr, self.role
        p = popt2.RATES[sr]
        rec_frame0_ns = self.mono(self.true_cap0_ns(t0_ms))
        play_onset_ns = self.mono(self.true_onset_ns(t0_ms))
        primer = round(K.PRIMER_S * sr)
        play_frame_position = primer + 2 * round(K.CODE_S * sr)
        play_nano_time = play_onset_ns + (play_frame_position - primer) * 1e9 / sr
        p_self = round((play_onset_ns - rec_frame0_ns) * sr / 1e9)
        a_self, _ = twin2.earliest(capture, *self.own_code, p_self - p["wpre"], p_self + p["wpost"], sr)
        if a_self is None:
            return self._fail(attempt, "self_not_heard")
        sod = a_self - p_self
        if self.k.self_os_delta_override is not None:
            sod = self.k.self_os_delta_override      # a wrong OS timestamp: p_self = a_self - sod moves
        root = poseidon2.to_bytes32(poseidon2.rec_root(capture)) if self.real_root else fake_root(capture)
        commit = encode_commit(role, attempt, self.nonce, root, version=self.commit_version)
        r = self.post(f"/v1/session/{self.sid}/commit", {"commit_b64": b64(commit), "sig_b64": b64(sign_raw(self.sk, commit))})
        if r.status_code != 200:
            return r
        partner_code = code_of(r.json()["partner_code"])
        t0_mono = t0_ms * 1e6 - self.offset_ns
        p_off = K.B_PLAY_S if role == "A" else K.A_PLAY_S
        p_partner = round((t0_mono + p_off * 1e9 - rec_frame0_ns) * sr / 1e9)
        a_p, _ = twin2.earliest(capture, *partner_code, p_partner - p["wpre"], p_partner + p["wpost"], sr)
        if a_p is None:
            return self._fail(attempt, "partner_not_heard")
        half = (a_p - a_self if role == "A" else a_self - a_p) + self.k.half_bias
        t = {"version": 2, "role": role, "attempt": attempt, "nonce": self.nonce, "pk_self": self.pub,
             "pk_partner": self.partner_pub, "sample_rate": sr, "half": half, "rec_root": root,
             "play_frame_position": play_frame_position, "play_nano_time": int(play_nano_time),
             "rec_frame0_nano_time": int(rec_frame0_ns), "self_os_delta": sod,
             "commit_hash": hashlib.sha256(commit).digest(), "a_self": a_self, "p_partner": p_partner,
             "delta": popt2.delta(sr) if self.delta_override is None else self.delta_override,
             "code_commit": self.code_commit_override or popt2.code_commit(self.own_code, partner_code)}
        raw = encode_transcript(t)
        self.last = {"transcript": t, "raw": raw, "commit": commit, "capture": capture,
                     "a_partner": a_p, "p_self": p_self}
        body = {"transcript_b64": b64(raw), "sig_b64": b64(sign_raw(self.sk, raw)), "meta": {"rule": "popt2"}}
        return self.post(f"/v1/session/{self.sid}/transcript", body)


class World2(sim.World):
    """Both phones on v2 unless v1=('A',) etc. picks plain pop-v1 phones for those roles."""

    def __init__(self, client, clock, distance_cm, ka: Knobs | None = None, kb: Knobs | None = None,
                 v1=(), real_root=True, **kw):
        super().__init__(client, clock, distance_cm, ka, kb, **kw)
        for p in self.phones:
            if p.role not in v1:
                p.__class__ = FakePhone2
                p.real_root = real_root
