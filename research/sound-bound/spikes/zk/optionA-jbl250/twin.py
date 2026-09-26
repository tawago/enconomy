"""Integer "circuit twin" of the JBL250 receiver (research/2026-09-26-sound-bound-decision.md).

What the circuit computes, done in exact integers in Python, compared with fieldanalysis.py.

Receiver (fieldanalysis, probe JBL250, round 0):
  - masked (2-18 kHz brick-wall) analytic correlation of the recording with the secret bed,
    env = |corr|, score = env / (||masked x[n:n+L]|| * ||masked c||), L = 12,000
  - window -150/+250 ms around the expected onset: K = 19,200 lags
  - bar T = Gumbel fit over 64 null codes (live), ppm bank on cross arrivals
  - "first": earliest local max of env with score >= T and env >= 0.5 * max env[i .. i+240]

Twin (what the circuit proves), all integers:
  x      int16 PCM (Mac float32 files are rounded to int16; Android files are int16-exact)
  cI,cQ  masked template and its Hilbert pair, truncated to L, quantized to BC bits (same scale)
  I_k = sum_n x[k+n] cI[n],  Q_k = sum_n x[k+n] cQ[n],  env2_k = I_k^2 + Q_k^2
  y      = h * x, an M-tap integer band-pass FIR (constant in the circuit); E_k = sum_{m<L} y[k+m]^2
  score >= T   <=>   env2_k * B >= E_k * cn2        (cn2 = sum cI^2, B = round(g^2/T^2), g = FIR gain)
  T      fixed public floor T0 (no live bar, no ppm bank)
  rule   same "first" rule on env2 (local max, half rule as 4*env2_i >= env2_m)

  python twin.py                      # all JBL250 sessions: twin vs result.json arrivals
  python twin.py --dump <sess8> <key> <K'> out.json   # circuit input for one arrival sub-window
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np
import scipy.fft as sfft
from scipy.signal import firwin, freqz

HERE = Path(__file__).resolve().parent
FIELD = HERE.parents[1] / "melody" / "fieldtest"
sys.path.insert(0, str(FIELD))
import fieldprobes as fp  # noqa: E402
import fieldanalysis as fa  # noqa: E402

SESS = FIELD / "data" / "sessions"
P = "JBL250"
SR = 48_000
L = 12_000                  # 250 ms template
LOOK = 240                  # 5 ms half-rule lookahead (fieldanalysis HALF_LOOKAHEAD_S * sr)
import os
BC = int(os.environ.get("TWIN_BC", 8))   # template bits (signed): |cI|,|cQ| <= 2^(BC-1)-1
M = int(os.environ.get("TWIN_M", 63))     # FIR taps (odd, linear phase)
BH = int(os.environ.get("TWIN_BH", 8))   # FIR coefficient bits (signed)
T0 = 0.09                   # fixed floor: above every live T seen on the JBL250 walk (6.9-8.3 %),
                            # below every arrival score (>= 16.9 %)
KEYS = ("A_at_A", "B_at_A", "B_at_B", "A_at_B")   # (emitter)_at_(listener)


def sessions():
    out = []
    for d in sorted(SESS.iterdir()):
        r = d / "result.json"
        if not r.exists():
            continue
        res = json.loads(r.read_text())
        if P in (res.get("probes") or {}):
            out.append(d)
    return out


def load(d: Path):
    session = json.loads((d / "session.json").read_text())
    res = json.loads((d / "result.json").read_text())
    rec = {}
    for Lr in fp.ROLES:
        x, sr = fa._read_wav(d / f"recording_{Lr}.wav")
        assert sr == SR
        meta = json.loads((d / f"meta_{Lr}.json").read_text())
        rec[Lr] = {"x": x, "meta": meta}
    return session, res, rec


def windows(session, rec, k=0):
    """(E, L) -> (lo, hi) absolute sample span of the lag window, as fieldanalysis._analyze."""
    sched = session["schedule"]
    pre, post = float(sched["search_pre_s"]), float(sched["search_post_s"])
    out = {}
    for Lr in fp.ROLES:
        meta = rec[Lr]["meta"]
        cap, start = float(meta["capture_start_ctx_s"]), float(meta["start_ctx_s"])
        own = {(d.get("probe"), int(d.get("k"))): float(d["ctx_s"]) for d in meta.get("plays") or []}
        for E in fp.ROLES:
            if E == Lr:
                exp = own.get((P, k), start + fp.offset_s(sched, P, E, k)) - cap
            else:
                exp = start + fp.offset_s(sched, P, E, k) - cap
            out[(E, Lr)] = (int(round((exp - pre) * SR)), int(round((exp + post) * SR)))
    return out


def q16(x):
    return np.clip(np.round(x * 32768.0), -32768, 32767).astype(np.int64)


def templates(seed, E):
    """cI, cQ (int, BC bits, common scale) and the float masked template norm."""
    c = fp.template(seed, P, E, SR).astype(np.float64)
    assert len(c) == L
    nfft = 1 << 17
    C = np.fft.rfft(c, nfft) * fp.rx_mask(P, nfft, SR)
    cm = np.fft.irfft(C, nfft)
    A = np.zeros(nfft, dtype=complex)            # analytic signal of the masked template
    A[: nfft // 2 + 1] = C
    A[1: nfft // 2] *= 2.0
    a = np.fft.ifft(A)
    cI, cQ = cm[:L], a.imag[:L]
    s = (2 ** (BC - 1) - 1) / max(np.abs(cI).max(), np.abs(cQ).max())
    return np.round(cI * s).astype(np.int64), np.round(cQ * s).astype(np.int64)


def fir():
    h = firwin(M, [fp.BAND_HZ[0], fp.BAND_HZ[1]], pass_zero=False, fs=SR, window=("kaiser", 6.0))
    hi = np.round(h * (2 ** (BH - 1) - 1) / np.abs(h).max()).astype(np.int64)
    w, H = freqz(hi.astype(float), worN=4096, fs=SR)
    band = (w > 3000) & (w < 16000)
    g = float(np.sqrt(np.mean(np.abs(H[band]) ** 2)))     # rms passband gain of the int filter
    return hi, g


def bconst(g, T=T0):
    """score >= T  <=>  env2 * B >= E * cn2, B = round(g^2 / T^2) (public circuit constant)."""
    return int(round(g * g / (T * T)))


def corr_exact(x, c, K):
    """I_k = sum_n x[k+n] c[n] for k < K, exact int64 (|I| < 2^15 * 2^9 * 12000 < 2^38)."""
    v = np.lib.stride_tricks.sliding_window_view(x[: K + L - 1], L)
    out = np.empty(K, dtype=np.int64)
    for k0 in range(0, K, 1024):
        out[k0: k0 + 1024] = v[k0: k0 + 1024] @ c
    return out


def twin_arrival(xw, cI, cQ, h, g, K, T=T0, full=False):
    """xw: int16 samples covering y-support: len K + L - 1 + M - 1 (FIR centered).

    Returns dict with the integer curve and the first-rule arrival (window-relative)."""
    hm = (M - 1) // 2
    I = corr_exact(xw[hm:], cI, K)
    Q = corr_exact(xw[hm:], cQ, K)
    y = np.convolve(xw, h[::-1], mode="valid")        # y[m] = sum_t h[t] x[m+t], len K+L-1
    assert len(y) == K + L - 1
    y2 = y.astype(object) ** 2 if full else (y.astype(np.float64)) ** 2
    cs = np.concatenate([[0], np.cumsum(y2)])
    E = cs[L: L + K] - cs[:K]
    cn2 = int(np.dot(cI, cI))
    B = bconst(g, T)
    env2 = I.astype(object) ** 2 + Q.astype(object) ** 2 if full else I.astype(np.float64) ** 2 + Q.astype(np.float64) ** 2
    ok = [e * B >= En * cn2 for e, En in zip(env2, E)] if full else (env2 * B >= E * cn2)
    ok = np.asarray(ok, dtype=bool)
    e = np.asarray(env2, dtype=np.float64)
    inner = e[1:-1]
    lm = np.zeros(K, bool)
    lm[1:-1] = (inner >= e[:-2]) & (inner > e[2:])
    cand = np.nonzero(lm & ok)[0]
    arr, rej = None, []
    for i in cand:
        ref = e[i: i + LOOK + 1].max()
        if 4 * e[i] >= ref:
            arr = int(i)
            break
        rej.append(int(i))
    score = np.sqrt(e * g * g / (np.asarray(E, dtype=np.float64) * cn2))
    return {"I": I, "Q": Q, "y": y, "E": E, "env2": env2, "ok": ok, "lm": lm, "arr": arr,
            "half_rejected": rej, "score": score, "cn2": cn2, "B": B}


def run_all(T=T0):
    h, g = fir()
    rows = []
    for d in sessions():
        session, res, rec = load(d)
        seed = session["seed_hex"]
        wins = windows(session, rec)
        r0 = res["probes"][P]["rounds"][0]
        tpl = {E: templates(seed, E) for E in fp.ROLES}
        t_twin = {}
        for key in KEYS:
            E, Lr = key.split("_at_")
            lo, hi = wins[(E, Lr)]
            K = hi - lo
            x = q16(rec[Lr]["x"])
            hm = (M - 1) // 2
            xw = x[lo - hm: lo + K + L - 1 + hm]
            tw = twin_arrival(xw, *tpl[E], h, g, K, T)
            ref = r0["arrivals"][key]
            ref_n = int(round(ref["t"] * SR))
            n = None if tw["arr"] is None else lo + tw["arr"]
            t_twin[key] = n
            pre = 0 if tw["arr"] is None else tw["arr"]
            rows.append({
                "session": d.name[:8], "label": session["labels"].get("label_cm"), "key": key, "K": K,
                "ref_n": ref_n, "twin_n": n, "diff": None if n is None else n - ref_n,
                "ref_pct": ref["right_pct"], "twin_pct": None if n is None else 100 * float(tw["score"][tw["arr"]]),
                "ref_T": ref["T"], "ref_ppm": ref["ppm"], "ref_hr": ref["half_rejected"],
                "twin_hr": len(tw["half_rejected"]), "pre_lags": pre,
                "ok_before": int(tw["ok"][:pre].sum()),
                "lm_ok_before": int((tw["ok"] & tw["lm"])[:pre].sum()),
                "max_score_before": 100 * float(tw["score"][: max(pre - 3, 1)].max()),
                "bits_env2": int(max(tw["env2"])).bit_length(),
                "bits_C": int(max(float(En) * tw["cn2"] for En in tw["E"])).bit_length(),
                "bits_env2B": int(max(tw["env2"]) * tw["B"]).bit_length(),
                "bits_I": int(np.abs(tw["I"]).max()).bit_length(),
            })
        if all(v is not None for v in t_twin.values()):
            hA = t_twin["B_at_A"] - t_twin["A_at_A"]
            hB = t_twin["B_at_B"] - t_twin["A_at_B"]
            fl = fa.SPEED_OF_SOUND_CM_S / 2 * (hA - hB) / SR
            rows.append({"session": d.name[:8], "flight_twin": fl, "flight_ref": r0["flight_cm"],
                         "halfA": hA, "halfB": hB})
    return rows


def dump(sess8, key, Kp, out, T=T0, lead=None, mode="exact", nhr=2):
    """Circuit input for one arrival: a K'-lag sub-window starting `lead` lags before the arrival."""
    d = next(SESS.glob(sess8 + "*"))
    session, res, rec = load(d)
    wins = windows(session, rec)
    E, Lr = key.split("_at_")
    lo, hi = wins[(E, Lr)]
    cI, cQ = templates(session["seed_hex"], E)
    h, g = fir()
    x = q16(rec[Lr]["x"])
    hm = (M - 1) // 2
    K = hi - lo
    tw = twin_arrival(x[lo - hm: lo + K + L - 1 + hm], cI, cQ, h, g, K, T)
    i = tw["arr"]
    if lead is None:
        lead = min(i, Kp // 2)
    s0 = i - lead                      # sub-window start (window-relative lag)
    assert 0 <= s0 and s0 + Kp <= K, (s0, Kp, K)
    xs = x[lo + s0 - hm: lo + s0 + Kp + L - 1 + hm]
    sub = twin_arrival(xs, cI, cQ, h, g, Kp, T, full=True)
    # the sub-window rule must agree with the full-window rule when the sub-window starts at the
    # window start; otherwise it proves "first within the sub-window"
    ia = lead
    assert sub["arr"] == ia, ("sub-window rule disagrees", sub["arr"], ia)
    assert Kp - ia > LOOK, "half-rule lookahead must fit in the sub-window"
    env2 = [int(v) for v in sub["env2"]]
    E_ = [int(v) for v in sub["E"]]
    B, cn2 = sub["B"], sub["cn2"]
    # per-lag reasons for lags before the arrival: 0 = score < T, 1 = env2_j <= env2_{j+1},
    # 2 = env2_j < env2_{j-1}, 3 = half-rule reject (needs a witness m)
    reasons, hrw = [], []
    for j in range(Kp):
        if j >= ia:
            reasons.append(0)
            continue
        if env2[j] * B < E_[j] * cn2:
            reasons.append(0)
        elif j + 1 < Kp and env2[j] <= env2[j + 1]:
            reasons.append(1)
        elif j == 0 or env2[j] < env2[j - 1]:
            reasons.append(2)
        else:
            m = max(range(j, min(j + LOOK + 1, Kp)), key=lambda t: env2[t])
            assert 4 * env2[j] < env2[m]
            reasons.append(3)
            hrw.append((j, m))
    inp = {
        "cI": [int(v) for v in cI], "cQ": [int(v) for v in cQ],
        "x": [int(v) for v in xs],
        "I": [int(v) for v in sub["I"]], "Q": [int(v) for v in sub["Q"]],
    }
    if mode in ("exact", "cand"):
        inp["arr"] = ia
        inp["sel"] = [1 if k <= ia else 0 for k in range(Kp + 1)]
    if mode == "exact":
        assert len(hrw) <= nhr, (len(hrw), nhr)
        inp["rsn"] = [[int(k < ia and r == 0), int(k < ia and r == 1), int(k < ia and r == 2)]
                      for k, r in enumerate(reasons)]
        inp["hr_f"] = [[int(w < len(hrw) and k == hrw[w][0]) for k in range(Kp)] for w in range(nhr)]
        inp["hr_g"] = [[int(w < len(hrw) and k == hrw[w][1]) for k in range(Kp)] for w in range(nhr)]
    meta = {"session": d.name, "key": key, "window_lo": lo, "sub_start_lag": s0, "arr_window": i,
            "arr_abs": lo + i, "ref_t_n": int(round(res["probes"][P]["rounds"][0]["arrivals"][key]["t"] * SR)),
            "Kp": Kp, "L": L, "M": M, "fir": [int(v) for v in h], "fir_gain": g, "T0": T,
            "score_at_arr": float(sub["score"][ia]), "n_half_reject_witness": len(hrw),
            "reasons_hist": {r: reasons[:ia].count(r) for r in range(4)},
            "B": B, "cn2": cn2,
            "bits": {"env2": max(env2).bit_length(), "C": max(e * cn2 for e in E_).bit_length(),
                     "env2B": (max(env2) * B).bit_length(),
                     "I": max(abs(v) for v in inp["I"] + inp["Q"]).bit_length()}}
    Path(out).write_text(json.dumps(inp))
    Path(out).with_suffix(".meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta)[:2000])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", nargs=4, metavar=("SESS8", "KEY", "KP", "OUT"))
    ap.add_argument("--lead", type=int, default=None)
    ap.add_argument("--T", type=float, default=T0)
    ap.add_argument("--mode", default="exact", choices=("exact", "cand", "core"))
    ap.add_argument("--nhr", type=int, default=2)
    a = ap.parse_args()
    if a.dump:
        dump(a.dump[0], a.dump[1], int(a.dump[2]), a.dump[3], a.T, a.lead, a.mode, a.nhr)
    else:
        rows = run_all(a.T)
        for r in rows:
            print(json.dumps(r))
