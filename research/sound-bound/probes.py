"""sound-bound probe waveforms.

Two roles, A and B, each get a distinct wideband multisine ("code").
The tone grid is fixed in Hz and independent of the sample rate, and every
tone's phase comes from a sha256 stream keyed by (seed_hex, role).  So the
same seed gives the same physical waveform on a 44100 Hz phone and a 48000 Hz
phone -- only the sampling of it differs.
"""

from __future__ import annotations

import hashlib
import struct

import numpy as np

PROBE_DURATION_S = 0.030
BAND_HZ = (2000, 18000)

# Tone spacing = 1 / PROBE_DURATION_S: every tone completes a whole number of
# cycles inside the probe, so the multisine is periodic over its own length and
# the ramps are the only thing that breaks periodicity.
TONE_SPACING_HZ = 1.0 / PROBE_DURATION_S
N_TONES = int(round((BAND_HZ[1] - BAND_HZ[0]) / TONE_SPACING_HZ))  # 480
RAMP_S = 0.005
PEAK = 0.8
_ROLES = ("A", "B")


def _phase_stream(seed_hex: str, role: str, count: int) -> np.ndarray:
    """count phases in [0, 2pi), deterministic in (seed_hex, role)."""
    if role not in _ROLES:
        raise ValueError(f"role must be one of {_ROLES}, got {role!r}")
    seed_hex = str(seed_hex).strip().lower()
    out = np.empty(count, dtype=np.float64)
    i = 0
    block = 0
    while i < count:
        digest = hashlib.sha256(
            f"sound-bound-v1|{seed_hex}|{role}|{block}".encode("utf-8")
        ).digest()
        for off in range(0, 32, 8):
            if i >= count:
                break
            word = struct.unpack(">Q", digest[off : off + 8])[0]
            out[i] = (word / 2.0**64) * 2.0 * np.pi
            i += 1
        block += 1
    return out


def tone_frequencies() -> np.ndarray:
    return BAND_HZ[0] + TONE_SPACING_HZ * np.arange(N_TONES, dtype=np.float64)


def generate(seed_hex: str, role: str, sample_rate: int) -> np.ndarray:
    """The probe for (seed, role) sampled at sample_rate. float32, peak 0.8."""
    sample_rate = int(sample_rate)
    if sample_rate <= 2 * BAND_HZ[1]:
        raise ValueError(f"sample_rate {sample_rate} cannot carry {BAND_HZ[1]} Hz")
    n = int(round(PROBE_DURATION_S * sample_rate))
    t = np.arange(n, dtype=np.float64) / sample_rate
    freqs = tone_frequencies()
    phases = _phase_stream(seed_hex, role, N_TONES)
    # direct summation: 480 x ~1440, cheap and exact
    x = np.cos(2.0 * np.pi * freqs[:, None] * t[None, :] + phases[:, None]).sum(axis=0)

    ramp_n = max(1, int(round(RAMP_S * sample_rate)))
    ramp_n = min(ramp_n, n // 2)
    w = np.ones(n, dtype=np.float64)
    r = 0.5 * (1.0 - np.cos(np.pi * (np.arange(ramp_n) + 0.5) / ramp_n))
    w[:ramp_n] = r
    w[n - ramp_n :] = r[::-1]
    x *= w

    peak = np.max(np.abs(x))
    if peak > 0:
        x *= PEAK / peak
    return x.astype(np.float32)


def crosscorr_margin_db(seed_hex: str, sample_rate: int) -> float:
    """20*log10(autocorr peak / worst cross-corr peak) for this seed."""
    from scipy.signal import fftconvolve

    a = generate(seed_hex, "A", sample_rate).astype(np.float64)
    b = generate(seed_hex, "B", sample_rate).astype(np.float64)
    auto = float(np.max(np.abs(fftconvolve(a, a[::-1], mode="full"))))
    cross = float(np.max(np.abs(fftconvolve(a, b[::-1], mode="full"))))
    if cross <= 0:
        return float("inf")
    return 20.0 * np.log10(auto / cross)


if __name__ == "__main__":
    from scipy.signal import resample

    seed = "a" * 64
    print(f"duration       {PROBE_DURATION_S*1000:.1f} ms")
    print(f"band           {BAND_HZ[0]}-{BAND_HZ[1]} Hz, {N_TONES} tones @ {TONE_SPACING_HZ:.3f} Hz")
    print(f"ramps          {RAMP_S*1000:.1f} ms raised cosine, peak {PEAK}")
    for sr in (48000, 44100):
        x = generate(seed, "A", sr)
        print(
            f"sr={sr}  n={len(x)}  peak={np.max(np.abs(x)):.4f}  rms={np.sqrt(np.mean(x.astype(np.float64)**2)):.4f}  "
            f"crosscorr margin A/B = {crosscorr_margin_db(seed, sr):.2f} dB"
        )
    # same physical waveform: resample 44100 -> 48000 and compare
    x44 = generate(seed, "A", 44100).astype(np.float64)
    x48 = generate(seed, "A", 48000).astype(np.float64)
    up = resample(x44, len(x48))
    edge = int(0.002 * 48000)  # ignore resampler edge ringing
    diff = np.max(np.abs(up[edge:-edge] - x48[edge:-edge]))
    print(
        f"44100->48000 resample vs native 48000: max abs diff = {diff:.5f} "
        f"({20*np.log10(diff/np.max(np.abs(x48))):.1f} dB below peak, interior only)"
    )
