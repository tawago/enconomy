"""Python reference of the phone DSP, contract docs/pop-contract.md section 6.

numpy (+ scipy.stats.gumbel_r for the bar, as the contract's golden).  Mirrors the Kotlin
port in app/composeApp/src/commonMain/kotlin/com/enconomy/pop/dsp line by line; the
fixtures' expected values come from here.

Choices the contract leaves open (same in Kotlin):
  - round() is Python's (ties to even); Kotlin uses kotlin.math.round, also ties to even.
  - mask frequencies are np.fft.rfftfreq(nfft, 1/sr) exactly (bin * (1 / (nfft * (1/sr)))).
  - flat runs: a run of equal consecutive samples counts its samples (analysis.py rule):
    diff run [i, j) -> span [i, j + 1), kept when j + 1 - i >= min_n.
  - not found -> frame -1.
"""

from __future__ import annotations

import hashlib
import math

import numpy as np
from scipy.stats import gumbel_r

CODE_S = 0.25
BAND_HZ = (2000.0, 18000.0)
FADE_S = 0.005
SEARCH_PRE_S, SEARCH_POST_S = 0.150, 0.250
SEGMENT_MARGIN_S = 0.1
N_NULL = 64
NULL_P = 1e-4
NULL_P_SAFETY = 3.0
FLOOR_SCORE = 0.05
HALF_FRAC = 0.5
HALF_LOOKAHEAD_S = 0.005
FLAT_RUN_MIN_S = 0.008


def null_seed(session_id_hex: str, emitter: str, attempt: int, i: int) -> bytes:
    return hashlib.sha256(f"pop-null-v1|{session_id_hex}|{emitter}|{attempt}|{i}".encode()).digest()


def _words(seed: bytes, count: int) -> np.ndarray:
    out = []
    j = 0
    while len(out) < count:
        d = hashlib.sha256(seed + j.to_bytes(4, "big")).digest()
        out.extend(int.from_bytes(d[4 * q: 4 * q + 4], "big") for q in range(8))
        j += 1
    return np.array(out[:count], dtype=np.float64)


def fade(x: np.ndarray, sr: int) -> np.ndarray:
    F = max(1, int(round(FADE_S * sr)))
    r = 0.5 * (1.0 - np.cos(np.pi * (np.arange(F) + 0.5) / F))
    x[:F] *= r
    x[-F:] *= r[::-1]
    return x


def null_template(session_id_hex: str, emitter: str, attempt: int, i: int, sr: int) -> np.ndarray:
    n = int(round(CODE_S * sr))
    k_lo = 500
    k_hi = min(4500, n // 2 - 1)
    w = _words(null_seed(session_id_hex, emitter, attempt, i), k_hi - k_lo + 1)
    spec = np.zeros(n // 2 + 1, dtype=np.complex128)
    spec[k_lo: k_hi + 1] = np.exp(1j * (2 * np.pi * w / 2.0 ** 32))
    return fade(np.fft.irfft(spec, n), sr)


def gumbel_bar(maxima) -> float:
    s = np.asarray(maxima, dtype=np.float64)
    p = NULL_P / NULL_P_SAFETY
    try:
        loc, scale = gumbel_r.fit(s)
        tg = float(gumbel_r.isf(p, loc, scale))
        if not math.isfinite(tg):
            raise ValueError
    except Exception:
        tg = float(s.max())
    return max(tg, float(s.max()), FLOOR_SCORE)


def window(expected: float, sr: int, n_cap: int):
    w0 = int(round(expected - SEARCH_PRE_S * sr))
    w1 = int(round(expected + SEARCH_POST_S * sr))
    return max(0, w0), min(n_cap, w1)


def correlate(capture: np.ndarray, sr: int, template: np.ndarray, nulls, expected: float) -> dict:
    """Section 6.3 steps 1-7: env/score of the real template over the window, null maxima."""
    x = capture.astype(np.float64) / 32768.0
    w0, w1 = window(expected, sr, len(x))
    if w1 - w0 < 3:
        return {"w0": w0, "w1": w1, "ok": False}
    L = int(round(CODE_S * sr))
    M = int(round(SEGMENT_MARGIN_S * sr))
    a, b = max(0, w0 - M), min(len(x), w1 + L + M)
    nfft = 1
    while nfft < (b - a) + L:
        nfft *= 2
    f = np.fft.rfftfreq(nfft, 1.0 / sr)
    m = ((f >= BAND_HZ[0]) & (f <= BAND_HZ[1])).astype(np.float64)
    X = np.fft.rfft(x[a:b], nfft) * m
    xm = np.fft.irfft(X, nfft)[: b - a]
    cs = np.concatenate([[0.0], np.cumsum(xm * xm)])
    idx = np.arange(w0 - a, w1 - a)
    nx = np.sqrt(np.maximum(cs[np.minimum(idx + L, b - a)] - cs[idx], 0.0))
    half = nfft // 2 + 1

    def one(c):
        C = np.fft.rfft(np.asarray(c, dtype=np.float64), nfft) * m
        p2 = np.abs(C) ** 2
        cn = math.sqrt((p2[0] + 2 * p2[1:-1].sum() + p2[-1]) / nfft)
        Z = np.zeros(nfft, dtype=np.complex128)
        Z[:half] = 2.0 * X * np.conj(C)
        env = np.abs(np.fft.ifft(Z)[w0 - a: w1 - a])
        return env, env / (nx * cn + 1e-30)

    env, sc = one(template)
    nmax = np.array([float(np.max(one(c)[1])) for c in nulls])
    return {"ok": True, "w0": w0, "w1": w1, "a": a, "b": b, "nfft": nfft, "env": env, "score": sc,
            "null_maxima": nmax}


def first_arrival(env, sc, T, look):
    if len(env) < 3:
        return None
    for n in range(1, len(env) - 1):
        if env[n] >= env[n - 1] and env[n] > env[n + 1] and sc[n] >= T:
            if env[n] >= HALF_FRAC * float(np.max(env[n: n + look + 1])):
                return n
    return None


def measure_arrival(capture, sr, template, nulls, expected) -> dict:
    r = correlate(capture, sr, template, nulls, expected)
    if not r["ok"]:
        return {"found": False, "frame": -1, "score": 0.0, "bar": 0.0, "null_max": 0.0,
                "window_lo": r["w0"], "window_hi": r["w1"], "strongest_frame": -1,
                "strongest_score": 0.0, "why": "window_outside_capture"}
    env, sc, nmax = r["env"], r["score"], r["null_maxima"]
    T = gumbel_bar(nmax)
    look = int(round(HALF_LOOKAHEAD_S * sr))
    n = first_arrival(env, sc, T, look)
    s = int(np.argmax(sc))
    out = {"bar": T, "null_max": float(nmax.max()), "window_lo": r["w0"], "window_hi": r["w1"],
           "strongest_frame": r["w0"] + s, "strongest_score": float(sc[s])}
    if n is None:
        out.update({"found": False, "frame": -1, "score": 0.0,
                    "why": "below_bar" if float(sc.max()) < T else "no_peak"})
    else:
        out.update({"found": True, "frame": r["w0"] + n, "score": float(sc[n]), "why": None})
    out["_corr"] = r
    return out


def flat_runs(capture: np.ndarray, sr: int):
    x = np.asarray(capture, dtype=np.int16)
    min_n = int(round(FLAT_RUN_MIN_S * sr))
    if len(x) < min_n or min_n < 2:
        return []
    same = x[1:] == x[:-1]
    runs = []
    i, n = 0, len(same)
    while i < n:
        if not same[i]:
            i += 1
            continue
        j = i
        while j < n and same[j]:
            j += 1
        if j + 1 - i >= min_n:
            runs.append((i, j + 1))
        i = j
    return runs


def runs_hit(runs, lo: int, hi: int) -> bool:
    return any(s < hi and lo < e for s, e in runs)


def half(self_arrival: int, partner_arrival: int, role: str) -> int:
    # A: t_BA - t_AA ; B: t_BB - t_AB
    return partner_arrival - self_arrival if role == "A" else self_arrival - partner_arrival
