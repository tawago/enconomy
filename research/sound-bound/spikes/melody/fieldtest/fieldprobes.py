"""fieldtest probes.  CONTRACT.md section 2-3 (+ v2 probes, README "Probes v2").

Default session (SEQUENCE): N250 -> N500 -> N1s -> JBL -> JBL250, 2 rounds each.
N30, JB and JBQ stay generatable so older sessions still reanalyze.

  N250 / N500 / N1s   random-phase multisine 2-18 kHz, 0.25 / 0.5 / 1 s
  JB    public M-bell jingle + secret 2-18 kHz bed at -6 dB re jingle; rx notches jingle partials
  JBQ   same jingle and bed design, bed at +6 dB re jingle (jingle 12 dB quieter); rx as JB
  JBL   public soft low tune (every partial <= JBL_PARTIAL_MAX_HZ) + secret bed at -6 dB;
        rx = bed only over BAND_HZ, no notches (the tune has no partial in the band)
  JBL250 0.25 s: two-note soft "ding-dong" (A rises, B falls, partials < JBL_PARTIAL_MAX_HZ)
        + secret 0.25 s bed (grid 4 Hz) at -6 dB; rx as JBL

Every waveform is a function of physical time on a fixed Hz grid, so 44.1 k and
48 k phones play the same sound.  Secret material comes from
sha256("fieldtest-v1|seed|probe|role|part") used as a PCG64 seed (spike-grade;
a real build would use a CSPRNG stream).

Choices not pinned by the contract:
  - N1s uses part="tones".
  - JB jingle: per note, per partial, one fixed phase drawn in order from
    melody_probes._rng("00"*32, role, "JB", "jingle"); no wander draws at all.
  - The jingle is normalized to TARGET_RMS before the bed is sized against it.
"""

from __future__ import annotations

import functools
import hashlib
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
MELODY = HERE.parent
SB_ROOT = HERE.parents[2]
for _p in (str(SB_ROOT), str(MELODY)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import probes  # noqa: E402  read-only
import melody_probes as mp  # noqa: E402  read-only (only its pure helpers are used)

VERSION = "fieldtest-v1"
PROBES = ("N30", "N250", "N500", "N1s", "JB", "JBQ", "JBL", "JBL250")   # everything generate() knows
SEQUENCE = ["N250", "N500", "N1s", "JBL", "JBL250"]   # the default session, in play order
ROLES = ("A", "B")
TARGET_RMS = 0.15            # equal digital RMS for every probe before gain
MAX_PEAK = 0.95              # render() never exceeds this (no clipping on the DAC)
BAND_HZ = (2000.0, 18000.0)  # what phone speakers and mics both carry
FADE_S = 0.005               # raised-cosine edges of the 1 s codes, no click
JB_BED_REL_DB = -6.0         # bed RMS re jingle RMS: audible texture, tune on top
JB_NOTCH_HZ = 15.0           # +-Hz around each public jingle partial (both roles' tunes)
LONG_S = 1.0                 # N1s / JB* length
MULTISINE_S = {"N250": 0.25, "N500": 0.5, "N1s": 1.0}   # multisine probes: length (grid = 1/len Hz)
JB_FAMILY = {                # probe -> (tune, bed RMS re jingle RMS dB, notch jingle partials at rx)
    "JB":  ("bell", -6.0, True),
    "JBQ": ("bell", +6.0, True),    # jingle 12 dB quieter relative to the bed than JB
    "JBL": ("low", -6.0, False),    # low tune has nothing in BAND_HZ -> no notches
    "JBL250": ("low250", -6.0, False),  # short two-note ding-dong, same rule as JBL
}
JB_LEN_S = {"JBL250": 0.25}   # JB* length when not LONG_S (bed grid = 1/len Hz)
# JBL tune: soft ocarina/flute-like, few harmonics, pentatonic C major around C4-C5.
JBL_NOTE_HZ = {"C4": 261.626, "D4": 293.665, "E4": 329.628, "G4": 391.995, "A4": 440.0,
               "C5": 523.251}
JBL_TUNE = {"A": ["C4", "E4", "G4", "A4", "G4"],    # A rises
            "B": ["C5", "A4", "G4", "E4", "D4"]}    # B answers, falling
JBL_HARM_AMP = (1.0, 0.35, 0.12, 0.04)  # harmonic k=1..4 amplitudes: mellow, nearly pure
JBL_PARTIAL_MAX_HZ = 1800.0  # no partial at or above this (2 kHz band edge + attack spread margin)
JBL_START_S = 0.02           # first note onset
JBL_STEP_S = 0.18            # note onset spacing
JBL_ATTACK_S = 0.03          # raised-cosine attack: no click, negligible spectral spread
JBL_RELEASE_S = 0.06         # raised-cosine release, notes overlap by this much
JBL_TAU_S = 0.6              # gentle exponential decay while a note holds
JBL_END_S = 0.97             # last note fully released by here (inside the 1 s buffer)
# JBL250 tune: two soft mallet notes (marimba-ish: fast attack, quick decay), same note table.
JBL250_TUNE = {"A": ["E4", "A4"],    # A: rising fourth ("ding-DONG" up)
               "B": ["C5", "G4"]}    # B: falling fourth
JBL250_HARM_AMP = (1.0, 0.25, 0.08)  # rounder than JBL: mallet on wood
JBL250_START_S = 0.01        # first note onset
JBL250_STEP_S = 0.10         # second note onset
JBL250_ATTACK_S = 0.012      # raised-cosine attack: soft mallet, spread ~ +-100 Hz
JBL250_RELEASE_S = 0.04      # raised-cosine release
JBL250_TAU_S = 0.10          # mallet decay
JBL250_END_S = 0.24          # last note fully released by here (inside the 0.25 s buffer)
SR_MIN, SR_MAX = 36000, 96000  # below 36 k the 18 kHz band edge does not fit
JINGLE_SEED = "00" * 32      # public: same jingle for every session

ROUNDS = 2                   # rounds per probe (A then B, turn-taking)
GAP_S = 0.7                  # silence after every sound: >= 0.6 s reverb settle + 0.1 s latency skew
TAIL_S = 1.2                 # capture continues this long after the last sound ends


def build_schedule(sequence, rounds=ROUNDS, gap_s=GAP_S, lead_s=0.5, tail_s=TAIL_S) -> dict:
    """A plays k at start + k*period, B at + b_offset; every sound followed by gap_s of silence."""
    probes_ = {}
    t = 0.0
    for p in sequence:
        d = {"N30": 0.03}.get(p) or MULTISINE_S.get(p) or JB_LEN_S.get(p, LONG_S)
        b_off = round(d + gap_s, 6)
        probes_[p] = {"start_s": round(t, 6), "rounds": rounds, "period_s": round(2 * b_off, 6),
                      "b_offset_s": b_off, "dur_s": d}
        t += rounds * 2 * b_off
    last_end = t - gap_s
    return {
        "lead_s": lead_s,                                   # capture starts at t0 - lead_s
        "record_total_s": round(lead_s + last_end + tail_s, 3),
        "search_pre_s": 0.150,                              # window around expected onset
        "search_post_s": 0.250,
        "order": list(sequence),
        "probes": probes_,
    }


SCHEDULE = build_schedule(SEQUENCE)
# N250 0/0.95/1.9/2.85, N500 3.8.., N1s 8.6.., JBL 15.4.., JBL250 22.2..25.05 (ends 25.3); capture 27.0 s


def _check(probe: str, role: str, sr) -> int:
    if probe not in PROBES:
        raise ValueError(f"probe must be one of {PROBES}, got {probe!r}")
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}, got {role!r}")
    sr = int(sr)
    if not SR_MIN <= sr <= SR_MAX:
        raise ValueError(f"sample rate {sr} outside {SR_MIN}..{SR_MAX}")
    return sr


def _sub(seed_hex: str, probe: str, role: str, part: str):
    return hashlib.sha256(
        f"{VERSION}|{str(seed_hex).strip().lower()}|{probe}|{role}|{part}".encode())


def _rng(seed_hex, probe, role, part) -> np.random.Generator:
    d = _sub(seed_hex, probe, role, part).digest()
    return np.random.Generator(np.random.PCG64(int.from_bytes(d, "big")))


def _fade(x: np.ndarray, sr: int) -> np.ndarray:
    return mp._fade(x, sr, FADE_S)


def _rms(x) -> float:
    return float(np.sqrt(np.mean(np.asarray(x, dtype=np.float64) ** 2)))


@functools.lru_cache(maxsize=8)
def _jingle(role: str, sr: int) -> np.ndarray:
    """Public steady-partial M-bell tune, fixed phases, RMS = TARGET_RMS (read-only)."""
    n = int(round(LONG_S * sr))
    t_all = np.arange(n) / sr
    out = np.zeros(n)
    rng = mp._rng(JINGLE_SEED, role, "JB", "jingle")
    for j, name in enumerate(mp.TUNE[role]):
        f0 = mp.NOTE_HZ[name]
        on = j * mp.NOTE_STEP_S
        i0 = int(round(on * sr))
        t = t_all[i0:] - on
        fk = mp.partials(f0, "M-bell")
        amp = np.arange(1, fk.size + 1) ** -mp.PARTIAL_SLOPE
        tau = mp.TAU0_S / (1.0 + fk / mp.TAU_KNEE_HZ)
        phi0 = rng.uniform(0, 2 * np.pi, fk.size)
        att = np.where(t < mp.ATTACK_S, 0.5 * (1 - np.cos(np.pi * t / mp.ATTACK_S)), 1.0)
        env = amp[:, None] * np.exp(-t[None, :] / tau[:, None]) * att[None, :]
        out[i0:] += (env * np.cos(2 * np.pi * fk[:, None] * t[None, :] + phi0[:, None])).sum(axis=0)
    out *= TARGET_RMS / _rms(out)
    out.setflags(write=False)
    return out


@functools.lru_cache(maxsize=1)
def jingle_partials_hz() -> np.ndarray:
    """Every public jingle partial of both roles (what the JB receiver notches)."""
    return np.array(sorted({float(f) for r in ROLES for name in mp.TUNE[r]
                            for f in mp.partials(mp.NOTE_HZ[name], "M-bell")}))


def _raised(t, T):
    """0 -> 1 raised cosine over [0, T], clipped outside."""
    return 0.5 * (1 - np.cos(np.pi * np.clip(t / T, 0.0, 1.0)))


@functools.lru_cache(maxsize=8)
def _jingle_low(role: str, sr: int) -> np.ndarray:
    """Public JBL tune: few-harmonic soft notes, all partials < JBL_PARTIAL_MAX_HZ, RMS = TARGET_RMS.

    Fixed cosine phases (public), so no secret material; starts and ends at exact zero.
    """
    n = int(round(LONG_S * sr))
    t_all = np.arange(n) / sr
    out = np.zeros(n)
    notes = JBL_TUNE[role]
    for j, name in enumerate(notes):
        f0 = JBL_NOTE_HZ[name]
        on = JBL_START_S + j * JBL_STEP_S
        off = (JBL_END_S - JBL_RELEASE_S) if j == len(notes) - 1 else on + JBL_STEP_S
        t = t_all - on
        env = _raised(t, JBL_ATTACK_S) * np.exp(-np.clip(t, 0, None) / JBL_TAU_S)
        env *= 1.0 - _raised(t_all - off, JBL_RELEASE_S)
        env[t < 0] = 0.0
        for k, a in enumerate(JBL_HARM_AMP, start=1):
            if k * f0 >= JBL_PARTIAL_MAX_HZ:
                break
            out += a * env * np.sin(2 * np.pi * k * f0 * t)
    out *= TARGET_RMS / _rms(out)
    out.setflags(write=False)
    return out


@functools.lru_cache(maxsize=8)
def _jingle_low250(role: str, sr: int) -> np.ndarray:
    """Public JBL250 ding-dong: two soft mallet notes, partials < JBL_PARTIAL_MAX_HZ, RMS = TARGET_RMS.

    Fixed phases (public); starts at exact zero and is fully released by JBL250_END_S.
    """
    n = int(round(JB_LEN_S["JBL250"] * sr))
    t_all = np.arange(n) / sr
    out = np.zeros(n)
    notes = JBL250_TUNE[role]
    for j, name in enumerate(notes):
        f0 = JBL_NOTE_HZ[name]
        on = JBL250_START_S + j * JBL250_STEP_S
        off = (JBL250_END_S - JBL250_RELEASE_S) if j == len(notes) - 1 else on + JBL250_STEP_S
        t = t_all - on
        env = _raised(t, JBL250_ATTACK_S) * np.exp(-np.clip(t, 0, None) / JBL250_TAU_S)
        env *= 1.0 - _raised(t_all - off, JBL250_RELEASE_S)
        env[t < 0] = 0.0
        for k, a in enumerate(JBL250_HARM_AMP, start=1):
            if k * f0 >= JBL_PARTIAL_MAX_HZ:
                break
            out += a * env * np.sin(2 * np.pi * k * f0 * t)
    out *= TARGET_RMS / _rms(out)
    out.setflags(write=False)
    return out


@functools.lru_cache(maxsize=1)
def jingle_low_partials_hz() -> np.ndarray:
    return np.array(sorted({k * JBL_NOTE_HZ[nm] for r in ROLES for nm in JBL_TUNE[r]
                            for k in range(1, len(JBL_HARM_AMP) + 1)
                            if k * JBL_NOTE_HZ[nm] < JBL_PARTIAL_MAX_HZ}))


def _jb_parts(seed_hex, role, sr, probe="JB"):
    """(scale, faded jingle, faded bed): the JB* waveform is scale*(jingle+bed)."""
    tune, rel_db, _ = JB_FAMILY[probe]
    jin = {"bell": _jingle, "low": _jingle_low, "low250": _jingle_low250}[tune](role, sr)
    j = _fade(jin.copy(), sr)
    b = mp._multisine(_rng(seed_hex, probe, role, "bed"), sr, BAND_HZ, JB_LEN_S.get(probe, LONG_S))
    b *= _rms(jin) * 10 ** (rel_db / 20) / _rms(b)
    b = _fade(b, sr)
    scale = TARGET_RMS / _rms(j + b)
    return scale, j, b


def _generate64(seed_hex, probe, role, sr) -> np.ndarray:
    if probe == "N30":
        sub_hex = _sub(seed_hex, "N30", role, "tones").hexdigest()
        x = probes.generate(sub_hex, role, sr).astype(np.float64)
        return x * (TARGET_RMS / _rms(x))
    if probe in MULTISINE_S:
        x = _fade(mp._multisine(_rng(seed_hex, probe, role, "tones"), sr, BAND_HZ,
                                MULTISINE_S[probe]), sr)
        return x * (TARGET_RMS / _rms(x))
    s, j, b = _jb_parts(seed_hex, role, sr, probe)
    return s * (j + b)


def generate(seed_hex: str, probe: str, role: str, sr: int) -> np.ndarray:
    sr = _check(probe, role, sr)
    return _generate64(seed_hex, probe, role, sr).astype(np.float32)


def render(seed_hex, probe, role, sr, gain_db=0.0):
    sr = _check(probe, role, sr)
    x = _generate64(seed_hex, probe, role, sr)
    req = float(gain_db or 0.0)
    g = 10 ** (req / 20)
    pk = float(np.max(np.abs(x)))
    if pk * g > MAX_PEAK:
        g = MAX_PEAK / pk * 0.999
    y = (x * g).astype(np.float32)
    info = {"gain_db_requested": req, "gain_db_applied": float(20 * np.log10(g)),
            "peak": float(np.max(np.abs(y))), "rms": _rms(y), "n": int(y.size), "sr": sr}
    return y, info


def template(seed_hex, probe, role, sr) -> np.ndarray:
    """What the receiver correlates with. N*: the code. JB*: the bed only."""
    sr = _check(probe, role, sr)
    if probe in JB_FAMILY:
        s, _, b = _jb_parts(seed_hex, role, sr, probe)
        return s * b
    return _generate64(seed_hex, probe, role, sr)


def null_seed(seed_hex, probe, role, i) -> str:
    return hashlib.sha256(f"fieldtest-null|{seed_hex}|{probe}|{role}|{i}".encode()).hexdigest()


def null_template(seed_hex, probe, role, sr, i: int) -> np.ndarray:
    return template(null_seed(seed_hex, probe, role, i), probe, role, sr)


def rx_mask(probe: str, nfft: int, sr: int) -> np.ndarray:
    if probe not in PROBES:
        raise ValueError(f"probe must be one of {PROBES}, got {probe!r}")
    f = np.fft.rfftfreq(int(nfft), 1.0 / sr)
    m = ((f >= BAND_HZ[0]) & (f <= BAND_HZ[1])).astype(np.float64)
    if probe in JB_FAMILY and JB_FAMILY[probe][2]:
        for fk in jingle_partials_hz():
            lo, hi = np.searchsorted(f, [fk - JB_NOTCH_HZ, fk + JB_NOTCH_HZ + 1e-9])
            m[lo:hi] = 0.0
    return m


def offset_s(schedule: dict, probe: str, role: str, k: int) -> float:
    p = schedule["probes"][probe]
    return float(p["start_s"]) + k * float(p["period_s"]) + (float(p["b_offset_s"]) if role == "B" else 0.0)


def plays(schedule: dict, role: str) -> list:
    out = [{"probe": p, "k": k, "offset_s": offset_s(schedule, p, role, k)}
           for p in schedule.get("order", list(schedule["probes"])) for k in range(int(schedule["probes"][p]["rounds"]))]
    return sorted(out, key=lambda d: d["offset_s"])


def duration_s(probe) -> float:
    if probe == "N30":
        return probes.PROBE_DURATION_S
    if probe in MULTISINE_S:
        return MULTISINE_S[probe]
    if probe in PROBES:
        return JB_LEN_S.get(probe, LONG_S)
    raise ValueError(f"probe must be one of {PROBES}, got {probe!r}")


def _xcorr_margin_db(a, b) -> float:
    from scipy.signal import fftconvolve
    auto = np.max(np.abs(fftconvolve(a, a[::-1])))
    cross = np.max(np.abs(fftconvolve(a, b[::-1])))
    return float(20 * np.log10(auto / cross))


if __name__ == "__main__":
    seed = "5b" * 32
    for p in PROBES:
        for sr in (44100, 48000):
            x = generate(seed, p, "A", sr).astype(np.float64)
            ta, tb = template(seed, p, "A", sr), template(seed, p, "B", sr)
            print(f"{p:4s} sr={sr} n={x.size} rms={_rms(x):.4f} peak={np.max(np.abs(x)):.3f} "
                  f"crest={20*np.log10(np.max(np.abs(x))/_rms(x)):.1f} dB "
                  f"A/B template xcorr margin={_xcorr_margin_db(ta, tb):.1f} dB")
    print("plays A:", [(d["probe"], d["k"], d["offset_s"]) for d in plays(SCHEDULE, "A")])
    print("plays B:", [(d["probe"], d["k"], d["offset_s"]) for d in plays(SCHEDULE, "B")])
