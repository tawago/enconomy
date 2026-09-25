"""Python reference of the phone DSP (contract §6). numpy only. The Kotlin port must match it (§6.7).

  null_template   §6.2  SHA-256-stream random-phase multisine, 4 Hz grid over 2-18 kHz, faded
  measure_arrival §6.3  masked correlation envelope, normalized score, 64-null Gumbel bar, "first" rule
  gumbel_isf      §6.4  Gumbel MLE (Newton on beta), isf(p)
  flat_runs       §6.5  constant int16 runs (dropped blocks)
  half            §6.6  A: t_BA - t_AA ; B: t_BB - t_AB

Choices the contract leaves open (the Kotlin side must do the same):
  - every "round(...)" is Python round (half to even), as jbl250/fieldprobes; Kotlin kotlin.math.round.
    Only matters at .5, e.g. FADE_S * 44100 = 220.5 -> 220.
  - k_hi = min(4500, n // 2 - 1).
  - flat run = maximal run of consecutive t with x[t+1] == x[t]; returned as [first t, last t + 1),
    kept if its length >= round(FLAT_RUN_MIN_S * sr). So a 20 ms block of zeros of N frames
    gives a run of N - 1 (plus any equal neighbours).
  - std in the Gumbel start is the population std (ddof 0); exponentials are shifted by min(s).
"""
from __future__ import annotations

import functools
import hashlib
import math
from dataclasses import dataclass

import numpy as np

from pop import constants as K

K_LO, K_HI_MAX = 500, 4500


def _r(x: float) -> int:
    return int(round(x))


def code_len(sr: int) -> int:
    return _r(K.CODE_S * sr)


def fade(x: np.ndarray, sr: int) -> np.ndarray:
    f = max(1, _r(K.FADE_S * sr))
    r = 0.5 * (1.0 - np.cos(np.pi * (np.arange(f) + 0.5) / f))
    x[:f] *= r
    x[-f:] *= r[::-1]
    return x


@functools.lru_cache(maxsize=512)
def _null(session_id_hex: str, emitter: str, attempt: int, i: int, sr: int) -> np.ndarray:
    seed = hashlib.sha256(f"pop-null-v1|{session_id_hex}|{emitter}|{attempt}|{i}".encode()).digest()
    n = code_len(sr)
    k_hi = min(K_HI_MAX, n // 2 - 1)
    m = k_hi - K_LO + 1
    stream = b"".join(hashlib.sha256(seed + j.to_bytes(4, "big")).digest() for j in range((m + 7) // 8))
    w = np.frombuffer(stream, dtype=">u4")[:m].astype(np.float64)
    spec = np.zeros(n // 2 + 1, dtype=np.complex128)
    spec[K_LO:k_hi + 1] = np.exp(1j * (2 * np.pi * w / 2.0 ** 32))
    x = fade(np.fft.irfft(spec, n), sr)
    x.setflags(write=False)
    return x


def null_template(session_id_hex: str, emitter: str, attempt: int, i: int, sr: int) -> np.ndarray:
    return _null(session_id_hex.lower(), emitter, int(attempt), int(i), int(sr))


def nulls(session_id_hex: str, emitter: str, attempt: int, sr: int) -> list[np.ndarray]:
    return [null_template(session_id_hex, emitter, attempt, i, sr) for i in range(K.N_NULL)]


def gumbel_fit(s) -> tuple[float, float]:
    """(mu, beta) MLE, §6.4. ValueError if it does not converge to something finite."""
    s = np.asarray(s, dtype=np.float64)
    lo, mean = float(s.min()), float(s.mean())
    beta = float(s.std()) * math.sqrt(6) / math.pi
    if not beta > 0:
        raise ValueError("degenerate sample")

    def g(b):
        e = np.exp(-(s - lo) / b)
        return b - mean + float(np.dot(s, e) / e.sum())

    for _ in range(200):
        h = 1e-6 * beta
        d = (g(beta + h) - g(beta - h)) / (2 * h)
        if not math.isfinite(d) or d == 0:
            raise ValueError("bad derivative")
        step = g(beta) / d
        nb = beta - step
        if not nb > 0 or not math.isfinite(nb):
            nb = beta / 2
        done = abs(nb - beta) < 1e-10 * beta
        beta = nb
        if done:
            break
    mu = lo - beta * math.log(float(np.mean(np.exp(-(s - lo) / beta))))
    if not (math.isfinite(mu) and math.isfinite(beta)):
        raise ValueError("non-finite fit")
    return mu, beta


def gumbel_isf(s, p: float) -> float:
    mu, beta = gumbel_fit(s)
    return mu - beta * math.log(-math.log1p(-p))


def bar(null_max) -> float:
    p = K.NULL_P / K.NULL_P_SAFETY
    try:
        tg = gumbel_isf(null_max, p)
        if not math.isfinite(tg):
            raise ValueError
    except ValueError:
        tg = float(np.max(null_max))
    return max(tg, float(np.max(null_max)), K.FLOOR_SCORE)


@dataclass
class Arrival:
    found: bool
    frame: int
    score: float
    bar: float
    null_max: float
    window_lo: int
    window_hi: int
    strongest_frame: int
    strongest_score: float
    why: str | None


def window(expected: float, sr: int, n_capture: int) -> tuple[int, int]:
    w0 = max(0, _r(expected - K.SEARCH_PRE_S * sr))
    w1 = min(n_capture, _r(expected + K.SEARCH_POST_S * sr))
    return w0, w1


def measure_arrival(capture, sr: int, template, null_templates, expected: float) -> Arrival:
    """§6.3, one window. capture int16, templates float."""
    x = np.asarray(capture, dtype=np.int16).astype(np.float64) / 32768.0
    c0 = np.asarray(template, dtype=np.float64)
    L, N = c0.size, x.size
    w0, w1 = window(expected, sr, N)
    if w1 - w0 < 3:
        return Arrival(False, -1, 0.0, K.FLOOR_SCORE, 0.0, w0, w1, -1, 0.0, "window_outside_capture")
    M = _r(K.SEGMENT_MARGIN_S * sr)
    a, b = max(0, w0 - M), min(N, w1 + L + M)
    nfft = 1 << ((b - a) + L - 1).bit_length()
    f = np.arange(nfft // 2 + 1) * sr / nfft
    mask = ((f >= K.BAND_HZ[0]) & (f <= K.BAND_HZ[1])).astype(np.float64)
    X = np.fft.rfft(x[a:b], nfft) * mask
    xm = np.fft.irfft(X, nfft)[: b - a]
    cs = np.concatenate([[0.0], np.cumsum(xm * xm)])
    idx = np.arange(w0 - a, w1 - a)
    nx = np.sqrt(np.maximum(cs[np.minimum(idx + L, b - a)] - cs[idx], 0.0))

    def env_score(c):
        C = np.fft.rfft(np.asarray(c, dtype=np.float64), nfft) * mask
        p = np.abs(C) ** 2
        norm = math.sqrt((p[0] + 2 * p[1:-1].sum() + p[-1]) / nfft)
        Z = np.zeros(nfft, dtype=np.complex128)
        Z[: nfft // 2 + 1] = 2 * X * np.conj(C)
        env = np.abs(np.fft.ifft(Z))[idx]
        return env, env / (nx * norm + 1e-30)

    env, score = env_score(c0)
    nmax = np.array([env_score(c)[1].max() for c in null_templates])
    T = bar(nmax)
    look = _r(K.HALF_LOOKAHEAD_S * sr)
    W = env.size
    frame, sc = -1, 0.0
    for n in range(1, W - 1):
        if env[n] >= env[n - 1] and env[n] > env[n + 1] and score[n] >= T:
            if env[n] >= K.HALF_FRAC * env[n: min(W, n + look + 1)].max():
                frame, sc = w0 + n, float(score[n])
                break
    j = int(np.argmax(score))
    found = frame >= 0
    why = None if found else ("below_bar" if score.max() < T else "no_peak")
    return Arrival(found, frame, sc, T, float(nmax.max()), w0, w1, w0 + j, float(score[j]), why)


def flat_runs(capture, sr: int) -> list[tuple[int, int]]:
    x = np.asarray(capture, dtype=np.int16)
    min_n = _r(K.FLAT_RUN_MIN_S * sr)
    eq = np.concatenate([[False], x[1:] == x[:-1], [False]]).astype(np.int8)
    d = np.diff(eq)
    starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    return [(int(s), int(e)) for s, e in zip(starts, ends) if e - s >= min_n]


def glitch(runs, lo: int, hi: int) -> bool:
    return any(s < hi and e > lo for s, e in runs)


def half(self_arrival: int, partner_arrival: int, role: str) -> int:
    """A: t_BA - t_AA ; B: t_BB - t_AB (frames at my sr)."""
    return partner_arrival - self_arrival if role == "A" else self_arrival - partner_arrival
