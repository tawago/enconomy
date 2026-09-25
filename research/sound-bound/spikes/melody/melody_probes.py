"""Melody probes for the sound-bound spike.

The idea under test: people hear the tune, not the phases.  So the tune is
public and fixed; every partial's phase (and its slow phase wander) comes
from the session seed.  The attacker can know the notes and still not know
the waveform.

  generate(seed_hex, role, sr, variant) -> float32, RMS = TARGET_RMS

Variants
  N30     current sound-bound probe (probes.generate), rescaled to TARGET_RMS
  N250    same design, 250 ms, 4 Hz grid (added: reverb caps the gain of
          length beyond ~RT60/14, so a mid length may keep most of it)
  N1s     same random-phase multisine design, 1 s, 1 Hz grid 2-18 kHz
  M-harm  1 s five-note tune, harmonic partials, secret phases + wander
  M-bell  same tune, stretched (inharmonic) partials f_k = f0 * k**BELL_STRETCH
  M-air   M-bell + quiet secret shaker/air layer 6-16 kHz at AIR_REL_DB

Every waveform is a function of physical time only, so 44.1 and 48 kHz give
the same sound.  Randomness: a numpy PCG64 stream keyed by
sha256(seed|role|variant|part).  Fine for a spike; a real build would use a
CSPRNG (ChaCha) so the phases are not predictable from each other.
"""

from __future__ import annotations

import hashlib
import pathlib
import sys

import numpy as np
from scipy.signal import butter, sosfilt

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import probes  # noqa: E402  (read-only sibling import)

VARIANTS = ("N30", "N250", "N1s", "M-harm", "M-bell", "M-air")
TARGET_RMS = 0.15            # same digital RMS for every candidate
DUR_S = 1.0                  # long candidates
FADE_S = 0.005               # hard edges of the 1 s codes

# The tune: E major pentatonic.  A asks (rising), B answers (falling home).
NOTE_HZ = {"E5": 659.255, "F#5": 739.989, "G#5": 830.609, "B5": 987.767,
           "C#6": 1108.731}
TUNE = {"A": ["E5", "G#5", "B5", "C#6", "B5"],
        "B": ["C#6", "B5", "G#5", "F#5", "E5"]}
NOTE_STEP_S = 0.17           # onset spacing; notes ring over each other
ATTACK_S = 0.008             # soft raised-cosine attack
TAU0_S = 0.35                # decay time of the lowest partial
TAU_KNEE_HZ = 3000.0         # higher partials decay faster: tau = TAU0/(1+f/knee)
PARTIAL_SLOPE = 0.9          # amplitude ~ k**-slope (bright, celesta-like)
F_MAX_HZ = 16000.0           # no partial above what a phone speaker plays
BELL_STRETCH = 1.07          # inharmonic partials: f_k = f0 * k**1.07

# Phase wander ("re-randomize every few ms, by construction"): each partial's
# phase is a raised-cosine-interpolated random walk with knots every KNOT_S
# and increments U(-pi, pi) * depth.  Depth ramps from 0 at WANDER_LO_HZ to 1
# at WANDER_HI_HZ, so the pitch-carrying low partials stay clean and the
# sparkle above carries the entropy.
KNOT_S = 0.005
WANDER_LO_HZ = 1500.0
WANDER_HI_HZ = 4000.0

AIR_BAND_HZ = (6000.0, 16000.0)
AIR_REL_DB = -12.0           # air RMS relative to melody RMS
AIR_HIT_TAU_S = 0.06         # shaker hit decay at each note onset
AIR_BED = 0.3                # constant bed under the hits (fraction of hit peak)

SPEAKER_HP_HZ = 400.0
SPEAKER_LP_HZ = 16000.0


def _rng(seed_hex: str, role: str, variant: str, part: str) -> np.random.Generator:
    if role not in ("A", "B"):
        raise ValueError(f"role must be A or B, got {role!r}")
    key = f"melody-spike-v1|{str(seed_hex).strip().lower()}|{role}|{variant}|{part}"
    d = hashlib.sha256(key.encode()).digest()
    return np.random.Generator(np.random.PCG64(int.from_bytes(d, "big")))


def _fade(x: np.ndarray, sr: int, fade_s: float = FADE_S) -> np.ndarray:
    n = max(1, int(round(fade_s * sr)))
    r = 0.5 * (1.0 - np.cos(np.pi * (np.arange(n) + 0.5) / n))
    x[:n] *= r
    x[-n:] *= r[::-1]
    return x


def _norm(x: np.ndarray) -> np.ndarray:
    return x * (TARGET_RMS / np.sqrt(np.mean(x * x)))


def _multisine(rng, sr: int, band, dur_s: float = DUR_S) -> np.ndarray:
    """Random-phase multisine on a 1/dur Hz grid over exactly dur_s (rate-independent)."""
    n = int(round(dur_s * sr))
    spec = np.zeros(n // 2 + 1, dtype=np.complex128)
    k = np.arange(int(np.ceil(band[0] * dur_s)), int(band[1] * dur_s) + 1)
    k = k[k < n // 2]
    spec[k] = np.exp(1j * rng.uniform(0, 2 * np.pi, k.size))
    return np.fft.irfft(spec, n)


def partials(f0: float, variant: str) -> np.ndarray:
    k = np.arange(1, 64, dtype=np.float64)
    f = f0 * (k if variant == "M-harm" else k ** BELL_STRETCH)
    return f[f <= F_MAX_HZ]


def _melody(seed_hex: str, role: str, sr: int, variant: str) -> np.ndarray:
    n = int(round(DUR_S * sr))
    t_all = np.arange(n) / sr
    out = np.zeros(n)
    rng = _rng(seed_hex, role, variant, "phases")
    n_knots = int(np.ceil(DUR_S / KNOT_S)) + 2
    for j, name in enumerate(TUNE[role]):
        f0 = NOTE_HZ[name]
        on = j * NOTE_STEP_S
        i0 = int(round(on * sr))
        t = t_all[i0:] - on
        fk = partials(f0, variant)
        kk = np.arange(1, fk.size + 1)
        amp = kk ** -PARTIAL_SLOPE
        tau = TAU0_S / (1.0 + fk / TAU_KNEE_HZ)
        phi0 = rng.uniform(0, 2 * np.pi, fk.size)
        steps = rng.uniform(-np.pi, np.pi, (fk.size, n_knots))
        depth = np.clip((fk - WANDER_LO_HZ) / (WANDER_HI_HZ - WANDER_LO_HZ), 0, 1)
        walk = np.cumsum(steps, axis=1) * depth[:, None]
        g = t / KNOT_S
        gi = np.floor(g).astype(int)
        s = 0.5 * (1.0 - np.cos(np.pi * (g - gi)))
        wander = walk[:, gi] + s[None, :] * (walk[:, gi + 1] - walk[:, gi])
        att = np.where(t < ATTACK_S, 0.5 * (1 - np.cos(np.pi * t / ATTACK_S)), 1.0)
        env = amp[:, None] * np.exp(-t[None, :] / tau[:, None]) * att[None, :]
        ph = 2 * np.pi * fk[:, None] * t[None, :] + phi0[:, None] + wander
        out[i0:] += (env * np.cos(ph)).sum(axis=0)
    return out


def _air(seed_hex: str, role: str, sr: int) -> np.ndarray:
    noise = _multisine(_rng(seed_hex, role, "M-air", "air"), sr, AIR_BAND_HZ)
    t = np.arange(noise.size) / sr
    env = np.full(noise.size, AIR_BED)
    for j in range(len(TUNE[role])):
        on = j * NOTE_STEP_S
        tt = t - on
        hit = np.where(tt >= 0, np.exp(-np.clip(tt, 0, None) / AIR_HIT_TAU_S), 0.0)
        hit *= np.where(tt < 0.003, np.clip(tt, 0, None) / 0.003, 1.0)
        env += hit
    return noise * env


def generate(seed_hex: str, role: str, sr: int, variant: str) -> np.ndarray:
    sr = int(sr)
    if variant == "N30":
        return _norm(probes.generate(seed_hex, role, sr).astype(np.float64)).astype(np.float32)
    if variant in ("N1s", "N250"):
        dur = DUR_S if variant == "N1s" else 0.25
        x = _multisine(_rng(seed_hex, role, variant, "tones"), sr, probes.BAND_HZ, dur)
        return _norm(_fade(x, sr)).astype(np.float32)
    if variant in ("M-harm", "M-bell"):
        return _norm(_fade(_melody(seed_hex, role, sr, variant), sr)).astype(np.float32)
    if variant == "M-air":
        m = _norm(_melody(seed_hex, role, sr, "M-bell"))
        a = _air(seed_hex, role, sr)
        a *= TARGET_RMS * 10 ** (AIR_REL_DB / 20) / np.sqrt(np.mean(a * a))
        return _norm(_fade(m + a, sr)).astype(np.float32)
    raise ValueError(f"variant must be one of {VARIANTS}, got {variant!r}")


def pitch_periods_s(role: str) -> list[float]:
    return sorted({1.0 / NOTE_HZ[n] for n in TUNE[role]})


def speaker(x: np.ndarray, sr: int) -> np.ndarray:
    """Phone speaker: 2nd-order highpass 400 Hz, gentle 2nd-order rolloff at 16 kHz."""
    hp = butter(2, SPEAKER_HP_HZ, "highpass", fs=sr, output="sos")
    lp = butter(2, min(SPEAKER_LP_HZ, 0.45 * sr), "lowpass", fs=sr, output="sos")
    return sosfilt(lp, sosfilt(hp, np.asarray(x, dtype=np.float64)))


if __name__ == "__main__":
    for v in VARIANTS:
        for sr in (48000, 44100):
            x = generate("ab" * 32, "A", sr, v).astype(np.float64)
            print(f"{v:7s} sr={sr} n={x.size} rms={np.sqrt(np.mean(x*x)):.3f} "
                  f"crest={20*np.log10(np.max(np.abs(x))/np.sqrt(np.mean(x*x))):.1f} dB")
