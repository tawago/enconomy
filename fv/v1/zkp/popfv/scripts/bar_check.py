"""BAR layer 2: recompute g from the 63 integer taps and check B = round(g^2 / T0^2).

Definition of g (git show 53604e3^:research/sound-bound/spikes/zk/optionA-v2/oa_rate.py, fir()):
    hi = round(firwin(63, [2000, 18000], pass_zero=False, fs=sr, window=("kaiser", 6)) * 127 / max|h|)
    w, H = freqz(hi, worN=4096, fs=sr)          # w_k = k * (sr/2) / 4096, k = 0..4095
    band = (w > 3000) & (w < 16000)              # strict on both sides
    g = sqrt(mean |H(w_k)|^2 over band)
    B = round(g^2 / 0.09^2)
Here: taps from server/pop/popt2.py RATES (the deployed constants), |H|^2 summed with mpmath at 60 digits.
The band test uses exact rationals (k * sr / 8192), so no float edge case can move a bin in or out.
Also: re-derive the taps with scipy firwin (catches a typo'd tap) and compare to the float spike value.

Run: uv run --with mpmath --with numpy --with scipy python scripts/bar_check.py
"""
from __future__ import annotations

import sys
from fractions import Fraction
from pathlib import Path

import mpmath as mp

ROOT = Path(__file__).resolve().parents[5]          # repo root (fv/v1/zkp/popfv/scripts -> ..)
sys.path.insert(0, str(ROOT / "server"))
from pop.popt2 import RATES                         # noqa: E402
from pop import constants as K                      # noqa: E402

LIB_NR = ROOT / "research/worldid/prototypes/optA-noir/noir/oalib/src/lib.nr"
mp.mp.dps = 60
T0 = Fraction(9, 100)
assert Fraction(K.T0_V2).limit_denominator(1000) == T0
N = 4096                                             # freqz worN


def g2_exact(h: list[int], sr: int) -> mp.mpf:
    """mean over band bins of |sum_n h_n e^{-i pi k n / N}|^2, high precision."""
    bins = [k for k in range(N) if Fraction(3000) < Fraction(k * sr, 2 * N) < Fraction(16000)]
    tot = mp.mpf(0)
    for k in bins:
        th = mp.pi * k / N
        re = mp.fsum(hn * mp.cos(th * n) for n, hn in enumerate(h) if hn)
        im = mp.fsum(hn * mp.sin(th * n) for n, hn in enumerate(h) if hn)
        tot += re * re + im * im
    return tot / len(bins), len(bins)


def spike_float(sr: int):
    import numpy as np
    from scipy.signal import firwin, freqz
    h = firwin(K.FIR_TAPS, list(K.BAND_HZ), pass_zero=False, fs=sr, window=("kaiser", 6.0))
    hi = np.round(h * 127 / np.abs(h).max()).astype(np.int64)
    w, H = freqz(hi.astype(float), worN=N, fs=sr)
    band = (w > 3000) & (w < 16000)
    return [int(v) for v in hi], float(np.sqrt(np.mean(np.abs(H[band]) ** 2)))


def main() -> int:
    ok = True
    bar_nr = None
    for line in LIB_NR.read_text().splitlines():
        if line.strip().startswith("pub global BAR"):
            bar_nr = int(line.split("=")[1].split(";")[0])
    print(f"lib.nr BAR = {bar_nr}")
    import re
    src = LIB_NR.read_text()
    nzt = [int(v) for v in re.search(r"NZT: \[u32; 31\] =\s*\[([^\]]*)\]", src).group(1).split(",") if v.strip()]
    nzh = [int(v) for v in re.search(r"NZH: \[Field; 31\] = \[([^\]]*)\]", src).group(1).split(",") if v.strip()]
    h48 = RATES[48000]["h"]
    nz_ok = [(i, v) for i, v in enumerate(h48) if v] == list(zip(nzt, nzh))
    print(f"lib.nr NZT/NZH == nonzero 48 kHz taps: {nz_ok}")
    ok &= nz_ok
    for sr in (48000, 44100):
        r = RATES[sr]
        h, B = r["h"], r["B"]
        assert len(h) == 63
        g2, nb = g2_exact(h, sr)
        x = g2 / (mp.mpf(T0.numerator) / T0.denominator) ** 2       # g^2 / T0^2
        Bc = int(mp.floor(x + mp.mpf(1) / 2))                         # round half up; exact tie impossible here
        frac = x - mp.floor(x)
        margin = mp.mpf(1) / 2 - abs(x - Bc)                          # distance to the nearest rounding edge
        hi_spike, g_spike = spike_float(sr)
        taps_ok = hi_spike == list(h)
        t0eff = mp.sqrt(g2) / mp.sqrt(B)
        print(f"\nsr = {sr}: {nb} band bins")
        print(f"  g            = {mp.nstr(mp.sqrt(g2), 30)}")
        print(f"  g (spike f64)= {g_spike!r}")
        print(f"  g^2/T0^2     = {mp.nstr(x, 30)}")
        print(f"  round        = {Bc}   RATES B = {B}   {'OK' if Bc == B else 'MISMATCH'}")
        print(f"  margin to rounding edge = {mp.nstr(margin, 10)} (of 0.5)")
        print(f"  T0eff = g/sqrt(B) = {mp.nstr(t0eff, 25)}   T0eff - T0 = {mp.nstr(t0eff - mp.mpf('0.09'), 6)}")
        print(f"  firwin re-derived taps == RATES h: {taps_ok}")
        ok &= Bc == B and taps_ok
    if bar_nr != RATES[48000]["B"]:
        print("lib.nr BAR != 48 kHz B"); ok = False
    print("\nlib.nr hard-codes only the 48 kHz BAR; no 44.1 kHz Noir circuit carries 3792174.")
    print("ALL OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
