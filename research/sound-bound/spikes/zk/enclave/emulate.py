"""Turn a JBL250 fieldtest session into what the pop-v1 app would have captured and signed.

Needs numpy, scipy, soundfile: run with research/proximity-echo/.venv/bin/python3.

What is real and what is emulated (docs/pop-contract.md §4.4, §7.1):
  capture      REAL audio. The contract keeps CAPTURE_S = 2.5 s starting LEAD_S = 0.5 s before t0 (A's
               sound onset). t0 in listener L's file = the fieldtest's expected onset of A's JBL250
               round 0 in that file (result.json arrivals["A_at_<L>"]["expected"]). Float32 WAV -> int16
               (round(x * 32768), clipped), as twin.q16.
  44.1 kHz     "mix" mode: the listener's 48 kHz float file is resampled to 44,100 Hz (scipy
               resample_poly 147/160, 4,800-sample margin on each side, exact frame alignment since
               4,800 * 147/160 = 4,410), then rounded to int16. The capture is 110,250 frames.
  arrivals     v1: the fieldtest's own arrival times (result.json, "first" rule, seconds) mapped to capture
               frames: round((t - capture_start_s) * sr). At 48 kHz this is exact (arrivals sit on the
               sample grid); at 44.1 kHz it is rounded (<= 0.5 frame = 0.19 cm per arrival).
               v2 (option A): the integer twin run on the int16 capture (see ../optionA-v2).
  timestamps   EMULATED (no native OS timestamps in the web fieldtest). Per device a monotonic clock
               base (a plausible uptime, seeded); capture frame 0 = base + capture_start_s.
               self_os_delta = t_self - expected_self is drawn uniformly in [-1 ms, +1 ms] (integer
               frames, seeded per session/role/mode): what an OS-timestamped playback path should give.
               The AudioTrack timestamp is built so the contract's formula reproduces it exactly:
                 play_frame_position = PRIMER_FRAMES + n_play       (track drained)
                 play_nano_time      = play_onset_ns + (fp - PRIMER_FRAMES) * 1e9 / sr
                 play_onset_ns       = rec_frame0_ns + round((t_self - self_os_delta) * 1e9 / sr)
               so expected_self = (play_onset_ns - rec_frame0_ns) * sr / 1e9 rounds back to
               t_self - self_os_delta.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ZK = HERE.parent
SESSIONS = ZK.parent / "melody" / "fieldtest" / "data" / "sessions"
SR_FILE = 48_000
LEAD_S, CAPTURE_S, PRIMER_S, CODE_S = 0.5, 2.5, 0.3, 0.25
MARGIN48 = 4_800
KEYS = ("A_at_A", "B_at_A", "B_at_B", "A_at_B")


def sessions():
    out = []
    for d in sorted(SESSIONS.iterdir()):
        r = d / "result.json"
        if r.exists() and "JBL250" in (json.loads(r.read_text()).get("probes") or {}):
            out.append(d)
    return out


def session_dir(s8):
    return next(SESSIONS.glob(s8 + "*"))


def read_wav(path):
    import soundfile as sf
    x, sr = sf.read(str(path), dtype="float32", always_2d=True)
    assert sr == SR_FILE
    return np.ascontiguousarray(x[:, 0].astype(np.float64))


def q16(x):
    return np.clip(np.round(np.asarray(x) * 32768.0), -32768, 32767).astype(np.int64)


def capture_frames(sr):
    return int(round(CAPTURE_S * sr))


def load(d: Path):
    session = json.loads((d / "session.json").read_text())
    res = json.loads((d / "result.json").read_text())
    return session, res


def capture(d: Path, listener: str, sr: int):
    """-> (int16 capture as int64 array, capture_start_s in the listener's file, s48 start frame)."""
    session, res = load(d)
    t0 = float(res["probes"]["JBL250"]["rounds"][0]["arrivals"][f"A_at_{listener}"]["expected"])
    s48 = int(round((t0 - LEAD_S) * SR_FILE))
    x = read_wav(d / f"recording_{listener}.wav")
    n = capture_frames(sr)
    if sr == SR_FILE:
        seg = x[s48: s48 + n]
    elif sr == 44_100:
        from scipy.signal import resample_poly
        wide = x[s48 - MARGIN48: s48 + capture_frames(SR_FILE) + MARGIN48]
        y = resample_poly(wide, 147, 160)
        off = MARGIN48 * 147 // 160
        seg = y[off: off + n]
    else:
        raise ValueError(sr)
    assert len(seg) == n
    return q16(seg), s48 / SR_FILE, s48


def field_arrivals(d: Path, listener: str, sr: int, cap_start_s: float):
    """v1 arrivals (fieldtest 'first' rule) as capture frames at sr: {'self': t, 'partner': t}."""
    _, res = load(d)
    a = res["probes"]["JBL250"]["rounds"][0]["arrivals"]
    other = "B" if listener == "A" else "A"
    fr = {}
    for kind, key in (("self", f"{listener}_at_{listener}"), ("partner", f"{other}_at_{listener}")):
        v = (float(a[key]["t"]) - cap_start_s) * sr
        if sr == SR_FILE:
            assert abs(v - round(v)) < 1e-3, (key, v)
        fr[kind] = int(round(v))
    return fr


def expected_partner_frame(d: Path, listener: str, sr: int, cap_start_s: float) -> int:
    """Schedule-derived expected partner arrival (contract §4.4 expected_partner), capture frames."""
    _, res = load(d)
    other = "B" if listener == "A" else "A"
    e = float(res["probes"]["JBL250"]["rounds"][0]["arrivals"][f"{other}_at_{listener}"]["expected"])
    return int(round((e - cap_start_s) * sr))


def half(role: str, t_self: int, t_partner: int) -> int:
    """A: t_BA - t_AA ; B: t_BB - t_AB  (contract §6.6 step 8)."""
    return t_partner - t_self if role == "A" else t_self - t_partner


def _rng(*parts):
    return random.Random("|".join(map(str, parts)))


def timestamps(sid: str, role: str, mode: str, sr: int, cap_start_s: float, t_self: int, sod: int | None = None):
    """Emulated POPT timestamp fields. Returns dict with the 4 signed fields + diagnostics."""
    rng = _rng("pop-ts-dev", sid, role, mode)
    base_ns = (3_600 + rng.randint(0, 20 * 3_600)) * 1_000_000_000 + rng.randint(0, 999_999_999)
    if sod is None:
        tol1 = int(round(0.001 * sr))
        sod = rng.randint(-tol1, tol1)
    rf0 = base_ns + int(round(cap_start_s * 1e9))
    exp_self = t_self - sod
    onset = rf0 + int(round(exp_self * 1e9 / sr))
    primer = int(round(PRIMER_S * sr))
    n_play = int(round(CODE_S * sr))
    fp = primer + n_play
    pnt = onset + int(round((fp - primer) * 1e9 / sr))
    # contract §4.4 recomputation
    onset2 = pnt + (primer - fp) * 1e9 / sr
    exp2 = (onset2 - rf0) * sr / 1e9
    assert int(round(exp2)) == exp_self, (exp2, exp_self)
    assert t_self - int(round(exp2)) == sod
    return {"play_frame_position": fp, "play_nano_time": pnt, "rec_frame0_nano_time": rf0,
            "self_os_delta": sod, "expected_self": exp2, "clock_base_ns": base_ns}


def dev_nonce(sid: str, mode: str) -> bytes:
    return hashlib.sha256(f"POPnonce-dev|{sid}|{mode}".encode()).digest()
