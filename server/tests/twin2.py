"""Test-side integer arrival rule of POPT v2 (docs/pop-transcript-v2.md §3), port of optionA-v2/oa_rate.py
curve/earliest. What the app computes for a_self / a_partner; the server never runs it.

  I_k = sum cI[n] x[k+n], Q_k likewise, y = h * x (63 taps, centred), E_k = sum_{m<L} y[k+m]^2
  pass(k) <=> (I_k^2 + Q_k^2) * B >= E_k * sum cI^2       earliest k in [lo, hi) with pass
x[i] = 0 past the end of the capture (as the tree pads).
"""
from __future__ import annotations

import numpy as np

from pop import popt2

HM = 31


def earliest(x, cI, cQ, lo: int, hi: int, sr: int, chunk: int = 512):
    """-> (lag or None, score). Exact Python-int compare; I/Q in int64 (|I| < 2^36)."""
    p = popt2.RATES[sr]
    L, B = p["L"], p["B"]
    h = np.asarray(p["h"], dtype=np.int64)
    cI = np.frombuffer(cI, dtype=np.int8).astype(np.int64) if isinstance(cI, bytes) else np.asarray(cI, np.int64)
    cQ = np.frombuffer(cQ, dtype=np.int8).astype(np.int64) if isinstance(cQ, bytes) else np.asarray(cQ, np.int64)
    cn2 = int((cI * cI).sum())
    if lo - HM < 0:
        raise ValueError("window starts before the capture")
    need = hi + L - 1 + HM
    xx = np.zeros(max(need, len(x)), dtype=np.int64)
    xx[: len(x)] = np.asarray(x, dtype=np.int64)
    for k0 in range(lo, hi, chunk):
        k1 = min(hi, k0 + chunk)
        K = k1 - k0
        xw = xx[k0 - HM: k1 + L - 1 + HM]
        v = np.lib.stride_tricks.sliding_window_view(xw[HM: HM + K + L - 1], L)
        I, Q = v @ cI, v @ cQ
        y = np.convolve(xw, h[::-1], mode="valid")
        yo = y.astype(object)
        cs = np.concatenate([[0], np.cumsum(yo * yo)])     # Python ints: full-scale sums pass int64
        E = cs[L: L + K] - cs[:K]
        for j in range(K):
            i, q, e = int(I[j]), int(Q[j]), int(E[j])
            if (i * i + q * q) * B >= e * cn2:
                return k0 + j, (float(np.sqrt((i * i + q * q) / (e * cn2) * B)) * 0.09 if e else 0.0)
    return None, 0.0
