#!/usr/bin/env python3
"""Replays the arrival rule of self_side (lib.nr 353-405), exact integers, on real server-derived codes.

Independent cross-check of the witnesses in Popfv/Arrival.lean. Blind recordings only: none of them
looks at the code. u[j]=1 before a, so `a` is the first lag with BAR*env2 >= big_c.
Run from anywhere: python3 scripts/arrival_real_template.py
"""
import os, sys
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "server"))
from pop import popt2  # noqa: E402

L, K, HM, NS, BAR = 12000, 193, 31, 12254, 4474747
NZT = [9, 11, 12, 14, 15, 17, 18, 20, 21, 23, 24, 26, 27, 29, 30, 31, 32, 33, 35, 36, 38, 39, 41, 42, 44, 45, 47, 48, 50, 51, 53]
NZH = [1, 1, 2, 2, 2, 4, -1, 2, -7, -5, -13, -19, -13, -45, 27, 127, 27, -45, -13, -19, -13, -5, -7, 2, -1, 4, 2, 2, 2, 1, 1]
h = np.zeros(54, dtype=np.int64)
h[NZT] = NZH
assert popt2.RATES[48000]["h"][:54] == list(h) and popt2.RATES[48000]["B"] == BAR


def arrival(w, cI, cQ):
    """first lag with BAR*env2 >= big_c, plus its (E, env2); None if every lag is below the bar."""
    assert len(w) == NS and w.min() >= -32768 and w.max() <= 32767
    y = np.array([int(np.dot(h, w[m:m + 54])) for m in range(K + L - 1)], dtype=np.int64)
    ey = np.concatenate([[0], np.cumsum(y * y)])
    cna = int(np.dot(cI, cI))
    for j in range(K):
        seg = w[j + HM:j + HM + L]
        I, Q = int(np.dot(cI, seg)), int(np.dot(cQ, seg))
        E = int(ey[j + L] - ey[j])
        env2 = I * I + Q * Q
        if E * cna - BAR * env2 <= 0:
            return j, E, env2
    return None


def main():
    for seed in range(3):
        key = bytes([seed + 1]) * 32
        for role in ("A", "B"):
            ci, cq = popt2.code(key, role, 48000)
            cI = np.frombuffer(ci, dtype=np.int8).astype(np.int64)
            cQ = np.frombuffer(cq, dtype=np.int8).astype(np.int64)
            assert len(cI) == L
            cna = int(np.dot(cI, cI))
            print(f"key {seed} role {role}: cna={cna} (Lean needs >= 9100000: {cna >= 9100000}) "
                  f"max|c|={max(abs(cI).max(), abs(cQ).max())} sum cI={cI.sum()} sum cQ={cQ.sum()}")
            sil = np.zeros(NS, dtype=np.int64)
            print("  silence ->", arrival(sil, cI, cQ))
            for a in (1, 50, 192):
                w = sil.copy()
                w[a + 8] = 1
                print(f"  click at {a + 8} (want a={a}) ->", arrival(w, cI, cQ))
            # energy-floor question: recordings with big_c >= 1 everywhere, still blind to the code
            print("  dc 1000 ->", arrival(sil + 1000, cI, cQ))
            n = np.arange(NS)
            for f in (20, 100, 500, 1000):
                tone = np.round(10000 * np.sin(2 * np.pi * f * n / 48000)).astype(np.int64)
                print(f"  tone {f} Hz ->", arrival(tone, cI, cQ))
            rng = np.random.default_rng(seed)
            print("  white noise ->", arrival(rng.integers(-1000, 1001, NS), cI, cQ))
            w = sil.copy()
            w[100] = 1000
            print("  one big click at 100, nothing else (a is forced to be before silence) ->", arrival(w, cI, cQ))


def sweep(nkeys=20):
    """Blind tones: fixed frequency list and phases chosen before the key. Does any pass with real energy?"""
    n = np.arange(NS)
    codes = []
    for seed in range(100, 100 + nkeys):
        ci, cq = popt2.code(seed.to_bytes(32, "big"), "A", 48000)
        codes.append((np.frombuffer(ci, dtype=np.int8).astype(np.int64), np.frombuffer(cq, dtype=np.int8).astype(np.int64)))
    freqs = (50, 100, 200, 300, 400, 500, 600, 700, 800, 1000, 1200, 1500, 2000, 4000, 8000)
    print(f"blind tone, amplitude 10000, {nkeys} fresh keys, 3 phases each: passes / trials, first lags seen")
    for f in freqs:
        hits, trials, lags, scale = 0, 0, [], []
        y_gain = abs(np.sum(h * np.exp(-2j * np.pi * f * np.arange(54) / 48000)))
        for cI, cQ in codes:
            for ph in (0.0, 2.1, 4.2):
                tone = np.round(10000 * np.sin(2 * np.pi * f * n / 48000 + ph)).astype(np.int64)
                r = arrival(tone, cI, cQ)
                trials += 1
                if r is not None:
                    hits += 1
                    lags.append(r[0])
                    assert r[1] > 0 and r[2] > 0  # real energy and real match, so an energy floor does not stop it
        print(f"  {f:5d} Hz  FIR gain {y_gain:7.1f}  {hits:3d}/{trials}  lags {sorted(set(lags))[:8]}")


def noise_margin(nkeys=20):
    """Same 500 Hz blind tone, at near full scale, plus white noise: how quiet must the rest of the recording be?"""
    n = np.arange(NS)
    print("500 Hz tone, amplitude 30000, plus white noise of the given rms (int16 steps), 20 keys, 3 phases")
    for rms in (0, 1, 2, 5, 10, 20, 50):
        hits = 0
        for seed in range(100, 100 + nkeys):
            ci, cq = popt2.code(seed.to_bytes(32, "big"), "A", 48000)
            cI = np.frombuffer(ci, dtype=np.int8).astype(np.int64)
            cQ = np.frombuffer(cq, dtype=np.int8).astype(np.int64)
            rng = np.random.default_rng(seed)
            for ph in (0.0, 2.1, 4.2):
                w = 30000 * np.sin(2 * np.pi * 500 * n / 48000 + ph) + rms * rng.standard_normal(NS)
                hits += arrival(np.round(w).astype(np.int64), cI, cQ) is not None
        print(f"  noise rms {rms:3d}: {hits}/{3 * nkeys} pass")


if __name__ == "__main__":
    main()
    sweep()
    noise_margin()
