"""JBL250 generator (contract §5.1). Vendored port of fieldprobes' JBL250 path.

Source: research/sound-bound/spikes/melody/fieldtest/fieldprobes.py (_jingle_low250, _jb_parts,
generate, render, template) + melody_probes._multisine/_fade. Same math, one change: the bed
PCG64 is seeded by a caller-supplied 32-byte `bed_key` instead of fieldprobes._sub(seed, probe,
role, part), so the key can carry the attempt (bed_key() below).

  sound    = scale * (fade(tune) + fade(bed)),  RMS = TARGET_RMS
  tune     public two-note ding-dong, every partial < 1800 Hz (nothing inside BAND_HZ)
  bed      secret 0.25 s random-phase multisine on the 4 Hz grid over 2-18 kHz, -6 dB re tune
  template = scale * fade(bed)   (what the receiver correlates with)
  render   = template + g*scale*fade(tune), g = 10**(tune_db/20) peak-limited on the tune only

Golden: bed_key = sha256("fieldtest-v1|<seed>|JBL250|<role>|bed") reproduces
fieldprobes.generate/template(seed, "JBL250", role, sr); see tests/golden/make_golden.py.
"""
from __future__ import annotations

import functools
import hashlib

import numpy as np

from pop import constants as K

ROLES = ("A", "B")
BED_REL_DB = -6.0
NOTE_HZ = {"C4": 261.626, "D4": 293.665, "E4": 329.628, "G4": 391.995, "A4": 440.0, "C5": 523.251}
PARTIAL_MAX_HZ = 1800.0
TUNE = {"A": ["E4", "A4"],    # A: rising fourth
        "B": ["C5", "G4"]}    # B: falling fourth
HARM_AMP = (1.0, 0.25, 0.08)
START_S = 0.01
STEP_S = 0.10
ATTACK_S = 0.012
RELEASE_S = 0.04
TAU_S = 0.10
END_S = 0.24


def bed_key(seed_hex: str, role: str, attempt: int) -> bytes:
    """Per (session, role, attempt) bed key. Server only; never sent."""
    if role not in ROLES:
        raise ValueError(f"role must be A or B, got {role!r}")
    if not 0 <= int(attempt) < K.MAX_ATTEMPTS:
        raise ValueError(f"attempt must be 0..{K.MAX_ATTEMPTS - 1}, got {attempt!r}")
    return hashlib.sha256(f"{K.PROTO}|{seed_hex.strip().lower()}|JBL250|{role}|{int(attempt)}|bed".encode()).digest()


def n_samples(sr: int) -> int:
    return int(round(K.CODE_S * sr))


def _check(role: str, sr) -> int:
    if role not in ROLES:
        raise ValueError(f"role must be A or B, got {role!r}")
    sr = int(sr)
    if not K.SR_MIN <= sr <= K.SR_MAX:
        raise ValueError(f"sample rate {sr} outside {K.SR_MIN}..{K.SR_MAX}")
    return sr


def _rng(key: bytes) -> np.random.Generator:
    if len(key) != 32:
        raise ValueError("bed_key must be 32 bytes")
    return np.random.Generator(np.random.PCG64(int.from_bytes(key, "big")))


def _rms(x) -> float:
    return float(np.sqrt(np.mean(np.asarray(x, dtype=np.float64) ** 2)))


def _fade(x: np.ndarray, sr: int) -> np.ndarray:
    n = max(1, int(round(K.FADE_S * sr)))
    r = 0.5 * (1.0 - np.cos(np.pi * (np.arange(n) + 0.5) / n))
    x[:n] *= r
    x[-n:] *= r[::-1]
    return x


def _multisine(rng, sr: int, band, dur_s: float) -> np.ndarray:
    """Random-phase multisine on a 1/dur Hz grid over exactly dur_s (rate-independent)."""
    n = int(round(dur_s * sr))
    spec = np.zeros(n // 2 + 1, dtype=np.complex128)
    k = np.arange(int(np.ceil(band[0] * dur_s)), int(band[1] * dur_s) + 1)
    k = k[k < n // 2]
    spec[k] = np.exp(1j * rng.uniform(0, 2 * np.pi, k.size))
    return np.fft.irfft(spec, n)


def _raised(t, T):
    return 0.5 * (1 - np.cos(np.pi * np.clip(t / T, 0.0, 1.0)))


@functools.lru_cache(maxsize=8)
def _tune(role: str, sr: int) -> np.ndarray:
    """Public ding-dong, fixed phases, RMS = TARGET_RMS, fully released by END_S."""
    n = n_samples(sr)
    t_all = np.arange(n) / sr
    out = np.zeros(n)
    notes = TUNE[role]
    for j, name in enumerate(notes):
        f0 = NOTE_HZ[name]
        on = START_S + j * STEP_S
        off = (END_S - RELEASE_S) if j == len(notes) - 1 else on + STEP_S
        t = t_all - on
        env = _raised(t, ATTACK_S) * np.exp(-np.clip(t, 0, None) / TAU_S)
        env *= 1.0 - _raised(t_all - off, RELEASE_S)
        env[t < 0] = 0.0
        for k, a in enumerate(HARM_AMP, start=1):
            if k * f0 >= PARTIAL_MAX_HZ:
                break
            out += a * env * np.sin(2 * np.pi * k * f0 * t)
    out *= K.TARGET_RMS / _rms(out)
    out.setflags(write=False)
    return out


def _parts(key: bytes, role: str, sr: int):
    """(scale, faded tune, faded bed): the sound is scale*(tune+bed)."""
    jin = _tune(role, sr)
    j = _fade(jin.copy(), sr)
    b = _multisine(_rng(key), sr, K.BAND_HZ, K.CODE_S)
    b *= _rms(jin) * 10 ** (BED_REL_DB / 20) / _rms(b)
    b = _fade(b, sr)
    return K.TARGET_RMS / _rms(j + b), j, b


def generate(key: bytes, role: str, sr: int) -> np.ndarray:
    sr = _check(role, sr)
    s, j, b = _parts(key, role, sr)
    return (s * (j + b)).astype(np.float32)


def tune_limit(bed: np.ndarray, tune: np.ndarray, tune_db: float = 0.0, max_peak: float = K.MAX_PEAK):
    """Largest tune gain g <= 10**(tune_db/20) with max|bed + g*tune| <= max_peak; the bed is never touched.

    Exact per sample: |b + g t| <= P  <=>  g <= (P - b*sign(t)) / |t|  (for g >= 0, |b| < P). If the
    requested gain fits it is returned as is; otherwise the bound times 0.999 (same margin as gain_db).
    Returns (g, g_max) with g_max the exact peak bound (inf if the tune is silent)."""
    b = np.asarray(bed, dtype=np.float64)
    t = np.asarray(tune, dtype=np.float64)
    nz = t != 0
    g_max = float(np.min((max_peak - b[nz] * np.sign(t[nz])) / np.abs(t[nz]))) if nz.any() else float("inf")
    g = 10 ** (float(tune_db or 0.0) / 20)
    return (g if g <= g_max else max(0.0, g_max * 0.999)), g_max


def _db(g: float) -> float:
    return float(20 * np.log10(g)) if g > 0 else float("-inf")


def render(key: bytes, role: str, sr: int, gain_db: float = 0.0, tune_db: float = 0.0):
    """play = gain * (bed + g_tune * tune), bed = template() exactly (same scale as the tune_db=0 sound).

    tune_db boosts only the public tune; if that would push the peak over MAX_PEAK the tune gain is
    reduced (never the bed, never a hard clip). gain_db is applied afterwards as before and scales both
    parts; its own peak limit can therefore still pull the bed down when gain_db > 0 (leave it at 0 when
    the bed level matters). tune_db = 0 gives the exact pre-tune_db output."""
    sr = _check(role, sr)
    s, j, b = _parts(key, role, sr)
    t_req = float(tune_db or 0.0)
    if t_req == 0.0:
        x = s * (j + b)
        gt, gt_max = 1.0, tune_limit(s * b, s * j)[1]
    else:
        bed = s * b
        gt, gt_max = tune_limit(bed, s * j, t_req)
        x = bed + gt * (s * j)
    req = float(gain_db or 0.0)
    g = 10 ** (req / 20)
    pk = float(np.max(np.abs(x)))
    if pk * g > K.MAX_PEAK:
        g = K.MAX_PEAK / pk * 0.999
    y = (x * g).astype(np.float32)
    info = {"gain_db_requested": req, "gain_db_applied": float(20 * np.log10(g)),
            "peak": float(np.max(np.abs(y))), "rms": _rms(y), "n": int(y.size), "sr": sr}
    if t_req != 0.0:
        info.update(tune_db_requested=t_req, tune_db_applied=_db(gt), tune_db_max=_db(gt_max))
    return y, info


@functools.lru_cache(maxsize=4)
def max_safe_tune_db(sr: int, n_keys: int = 32) -> dict:
    """Peak-limited tune_db per role at `sr`: min over n_keys sample bed keys (the bed varies per key)."""
    out = {}
    for role in ROLES:
        v = []
        for i in range(n_keys):
            key = hashlib.sha256(f"tune-max|{i}".encode()).digest()
            s, j, b = _parts(key, role, _check(role, sr))
            v.append(_db(tune_limit(s * b, s * j)[1]))
        out[role] = round(min(v), 2)
    return out


def template(key: bytes, role: str, sr: int) -> np.ndarray:
    sr = _check(role, sr)
    s, _, b = _parts(key, role, sr)
    return s * b
