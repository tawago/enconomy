"""Few-bit complex baseband (2-18 kHz, /3 -> 16 k complex) on real N1s data: 1, 2, 3 bits,
and 1 bit with white dither added before the sign (what the app would commit).

  $PY bits_baseband.py
"""
import sys
import numpy as np

sys.path.insert(0, __import__("os").path.dirname(__file__))
import receiver_variants as rv  # noqa: E402

rv.N_NULL = 4
keep = {"V0 full 1s float (baseline repro)", "baseband 2-18 kHz /3 float", "baseband 2-18 kHz /3 1-bit",
        "1-bit diff(RAW x), 1-bit template"}
for k in list(rv.VARIANTS):
    if k not in keep:
        del rv.VARIANTS[k]


def mk(bits, dither_db=None, tbits=1):
    def f(xm, xr, ts, sr, nl):
        xb = rv.baseband(xr, sr, 2000, 18000, 3)
        if dither_db is not None:
            g = np.random.default_rng(1)
            s = np.std(xb) * 10 ** (dither_db / 20) / np.sqrt(2)
            xb = xb + s * (g.standard_normal(len(xb)) + 1j * g.standard_normal(len(xb)))
        xq = rv.q1(xb) if bits == 1 else rv.qb(xb, bits)
        return [rv.scores(xq, rv.q1(rv.baseband(t, sr, 2000, 18000, 3)), nl // 3) for t in ts], 3, 0
    return f


for b in (2, 3):
    rv.VARIANTS[f"baseband /3 {b}-bit x, 1-bit template"] = mk(b)
for d in (-6, 0):
    rv.VARIANTS[f"baseband /3 1-bit x + dither {d} dB, 1-bit template"] = mk(1, d)

if __name__ == "__main__":
    rv.main(99)
