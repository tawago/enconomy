"""False-accept budget of the one-sided partner check for the pinned partner window.

A cheater gains only by claiming a partner arrival EARLIER than the real one. The proof accepts any lag in
[p_partner - WPRE, p_partner + WPOST] with score >= 9 %, so the gain needs a chance lag >= 9 % before the real
arrival. Chance level: the same recording scored against N_NULL wrong codes (fieldprobes.null_template, the
fieldanalysis null family), with the twin's normalization (FIR energy, 8-bit templates, float FFT here).
Per window: Gumbel fit to the 64 null maxima over the full 19,200-lag web window -> P(max > T0) per 19,200
lags; for an n-lag window P ~ n / 19,200 * P_19200 (union bound over disjoint sub-windows).

  $PY fa_budget.py            # -> logs/fa_budget.txt
"""
from __future__ import annotations

import json
import math

import numpy as np
from scipy.stats import gumbel_r

from common2 import HERE, HM, L, PARTNER_WINDOWS_MS, SR, T0
import twin2
import fieldprobes as fp

N_NULL = 64
tw1 = twin2.tw1


def q_template(c):
    """Same masking / Hilbert / 8-bit quantization as optionA-jbl250 twin.templates()."""
    nfft = 1 << 17
    C = np.fft.rfft(c, nfft) * fp.rx_mask("JBL250", nfft, SR)
    cm = np.fft.irfft(C, nfft)
    A = np.zeros(nfft, dtype=complex)
    A[: nfft // 2 + 1] = C
    A[1: nfft // 2] *= 2.0
    a = np.fft.ifft(A)
    cI, cQ = cm[:L], a.imag[:L]
    s = 127 / max(np.abs(cI).max(), np.abs(cQ).max())
    return np.round(cI * s), np.round(cQ * s)


def scores(xw, cI, cQ, K):
    """Float version of the twin score over K lags (xw = x[lo-HM : lo+K+L-1+HM])."""
    xc = xw[HM: HM + K + L - 1].astype(np.float64)
    n = 1 << int(math.ceil(math.log2(len(xc) + L)))
    X = np.fft.rfft(xc, n)
    I = np.fft.irfft(X * np.conj(np.fft.rfft(cI, n)), n)[:K]
    Q = np.fft.irfft(X * np.conj(np.fft.rfft(cQ, n)), n)[:K]
    y = np.convolve(xw.astype(np.float64), twin2.H[::-1].astype(np.float64), mode="valid")
    cs = np.concatenate([[0.0], np.cumsum(y * y)])
    E = cs[L: L + K] - cs[:K]
    cn2 = float(np.dot(cI, cI))
    return np.sqrt((I * I + Q * Q) * twin2.G ** 2 / (E * cn2))


def main():
    out = []
    lines = []
    for d in tw1.sessions():
        s8 = d.name[:8]
        _, session, res, rec, x, tpl = twin2.load(s8)
        seed = session["seed_hex"]
        wins = tw1.windows(session, rec, 0)
        for key in ("B_at_A", "A_at_B"):          # cross arrivals: the partner windows
            E_, Lr = key.split("_at_")
            lo, hi = wins[(E_, Lr)]
            K = hi - lo
            xw = x[Lr][lo - HM: lo + K + L - 1 + HM]
            mx = []
            for i in range(N_NULL):
                cI, cQ = q_template(fp.null_template(seed, "JBL250", E_, SR, i).astype(np.float64))
                mx.append(float(scores(xw, cI, cQ, K).max()))
            loc, sc = gumbel_r.fit(mx)
            p = float(gumbel_r.sf(T0, loc, sc))
            out.append({"session": s8, "key": key, "K": K, "null_max": max(mx), "null_median": float(np.median(mx)),
                        "gumbel_loc": loc, "gumbel_scale": sc, "p_window": p})
            lines.append(f"{s8} {key}: null max {100*max(mx):.2f}%  median {100*np.median(mx):.2f}%  "
                         f"P(max over 19,200 lags > 9%) = {p:.2e}")
            print(lines[-1], flush=True)
    ps = np.array([o["p_window"] for o in out])
    lines.append(f"\nwindows {len(ps)}; all null maxima {100*max(o['null_max'] for o in out):.2f}% max; "
                 f"P per 19,200 lags: median {np.median(ps):.2e}, max {ps.max():.2e}")
    for w, (pre, post) in PARTNER_WINDOWS_MS.items():
        n = (pre + post) * SR // 1000
        f = n / 19200
        lines.append(f"window {w} [-{pre}, +{post}] ms = {n} lags: per-attempt false-accept (chance lag >= 9% anywhere "
                     f"in the window, upper bound) median {f*np.median(ps):.1e}, worst window {f*ps.max():.1e}; "
                     f"with one retry x2: worst {2*f*ps.max():.1e}")
    print("\n".join(lines[-4:]))
    (HERE / "logs" / "fa_budget.txt").write_text("\n".join(lines) + "\n")
    (HERE / "build" / "fa_budget.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
