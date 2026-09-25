"""Receiver variants on real fieldtest recordings (N1s), to see which circuit-shrinking
changes keep the 30 cm vs 100 cm separation.

For every found arrival in result.json (baseline) this re-scores the recording with a
variant receiver in the same search window, finds the first arrival with the same rule
(T from 8 live nulls, Rayleigh tail: T = sqrt(E[s^2] * ln(K / p))), and rebuilds the
round flight.  Prints per variant: score loss, margin, |dt| vs baseline, flight error,
decision changes.  Also the self-arrival "late-claim" budget for a relaxed first-peak
check that only looks D lags back.

  PY=../../../../proximity-echo/.venv/bin/python3
  $PY receiver_variants.py [n_sessions]
"""
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import scipy.fft as sfft
from scipy.signal import fftconvolve

HERE = Path(__file__).resolve().parent
FIELD = HERE.parents[1] / "melody" / "fieldtest"
sys.path.insert(0, str(FIELD))
import fieldprobes as fp  # noqa: E402
from fieldanalysis import _read_wav, _stretch, _first_arrival  # noqa: E402

PROBE = "N1s"
N_NULL = 8
P_FA = 1e-4 / 3          # same per-window false-accept target as fieldanalysis
C = 34300.0
SKIP_S = 0.010           # short slices start after the 5 ms fade
D_LIST_MS = (0.25, 0.5, 1, 2, 5, 10, 20)


def masked(x, sr, mask_fn=None):
    n = sfft.next_fast_len(len(x))
    X = sfft.rfft(x, n) * fp.rx_mask(PROBE, n, sr)
    return sfft.irfft(X, n)[: len(x)]


def analytic(x):
    n = sfft.next_fast_len(len(x))
    X = sfft.fft(x, n)
    h = np.zeros(n); h[0] = 1; h[1:(n + 1) // 2] = 2
    if n % 2 == 0: h[n // 2] = 1
    return sfft.ifft(X * h)[: len(x)]


def baseband(x, sr, f1, f2, D):
    """analytic sub-band [f1,f2], shifted to 0 Hz, every D-th sample."""
    n = sfft.next_fast_len(len(x))
    X = sfft.fft(x, n)
    f = sfft.fftfreq(n, 1 / sr)
    X[(f < f1) | (f > f2)] = 0
    xa = sfft.ifft(2 * X)[: len(x)]
    fc = 0.5 * (f1 + f2)
    return (xa * np.exp(-2j * np.pi * fc * np.arange(len(x)) / sr))[::D]


def q1(z):
    if np.iscomplexobj(z):
        return np.sign(z.real) + 1j * np.sign(z.imag)
    return np.sign(z)


def qb(z, bits):
    def one(v):
        s = 3 * np.std(v) + 1e-30
        lv = 2 ** (bits - 1)
        return np.clip(np.round(v / s * lv), -lv, lv - 1)
    return one(z.real) + 1j * one(z.imag) if np.iscomplexobj(z) else one(z)


def scores(x, t, nlags):
    """normalized |<x[n:n+L], t>| / (||x[n:n+L]|| ||Re t||) for n in [0, nlags).  x real or complex,
    t analytic (real input) or complex baseband."""
    L = len(t)
    y = fftconvolve(x[: nlags + L - 1], np.conj(t[::-1]), mode="valid")[:nlags]
    cs = np.concatenate([[0], np.cumsum(np.abs(x[: nlags + L - 1]) ** 2)])
    nx = np.sqrt(np.maximum(cs[L: L + nlags] - cs[:nlags], 1e-30))
    tn = np.linalg.norm(t.real) if not np.iscomplexobj(x) else np.linalg.norm(t)
    env = np.abs(y)
    return env, env / (nx * tn)


def seg_nc(x, t, nlags, M):
    """noncoherent sum over M equal slices of t, at lag n slice m sits at n + m*Ls."""
    Ls = len(t) // M
    acc = np.zeros(nlags); accenv = np.zeros(nlags)
    for m in range(M):
        tm = t[m * Ls:(m + 1) * Ls]
        env, sc = scores(x[m * Ls:], tm, nlags)
        acc += sc ** 2; accenv += env ** 2
    return np.sqrt(accenv), np.sqrt(acc / M)


def ray_T(null_sc, K, M=1):
    """s^2 of a null is a mean of M exponentials (M = noncoherent slices): Gamma(M, mean/M) tail."""
    from scipy.stats import gamma
    m = np.mean(null_sc ** 2)
    return math.sqrt(gamma.isf(P_FA / K, M, scale=m / M))


VARIANTS = {}


def variant(name):
    def deco(f):
        VARIANTS[name] = f
        return f
    return deco


# each variant: (xseg_masked, xseg_raw, template_real_masked_list [real, nulls...], sr, nlags, use_ppm)
# -> list of (env, sc) per template, decimation factor, lag offset (samples at sr) of the slice
def _tmpl_analytic(ts):
    return [analytic(t) for t in ts]


@variant("V0 full 1s float (baseline repro)")
def v0(xm, xr, ts, sr, nl):
    return [scores(xm, a, nl) for a in _tmpl_analytic(ts)], 1, 0


for Lms in (250, 100, 50, 25):
    def _mk(Lms):
        def f(xm, xr, ts, sr, nl):
            s0 = int(SKIP_S * sr); Ls = int(Lms * sr / 1000)
            return [scores(xm[s0:], analytic(t)[s0:s0 + Ls], nl) for t in ts], 1, 0
        return f
    VARIANTS[f"short {Lms} ms slice, float"] = _mk(Lms)

for M in (4, 10):
    def _mk(M):
        def f(xm, xr, ts, sr, nl):
            return [seg_nc(xm, a, nl, M) for a in _tmpl_analytic(ts)], 1, 0, M
        return f
    VARIANTS[f"1s noncoherent {M} slices"] = _mk(M)


@variant("1-bit template only (x float)")
def v_bt(xm, xr, ts, sr, nl):
    return [scores(xm, q1(a), nl) for a in _tmpl_analytic(ts)], 1, 0


@variant("1-bit masked x, 1-bit template")
def v_b11(xm, xr, ts, sr, nl):
    return [scores(q1(xm), q1(a), nl) for a in _tmpl_analytic(ts)], 1, 0


@variant("1-bit RAW x (no band mask), 1-bit template")
def v_braw(xm, xr, ts, sr, nl):
    return [scores(q1(xr), q1(a), nl) for a in _tmpl_analytic(ts)], 1, 0


@variant("1-bit diff(RAW x), 1-bit template")
def v_bdiff(xm, xr, ts, sr, nl):
    d = np.concatenate([[0], np.diff(xr)])
    return [scores(q1(d), q1(a), nl) for a in _tmpl_analytic(ts)], 1, 0


@variant("3-bit masked x, 3-bit template")
def v_b3(xm, xr, ts, sr, nl):
    return [scores(qb(xm, 3), qb(a, 3), nl) for a in _tmpl_analytic(ts)], 1, 0


for (f1, f2, D) in ((2000, 18000, 3), (4000, 12000, 6), (6000, 10000, 12)):
    def _mk(f1, f2, D, bits):
        def f(xm, xr, ts, sr, nl):
            xb = baseband(xr, sr, f1, f2, D)
            out = []
            for t in ts:
                tb = baseband(t, sr, f1, f2, D)
                if bits == 1:
                    out.append(scores(q1(xb), q1(tb), nl // D))
                else:
                    out.append(scores(xb, tb, nl // D))
            return out, D, 0
        return f
    for bits in (0, 1):
        VARIANTS[f"baseband {f1//1000}-{f2//1000} kHz /{D}" + (" 1-bit" if bits else " float")] = _mk(f1, f2, D, bits)


@variant("V0 full 1s float, ppm0 (no bank)")
def v0p(xm, xr, ts, sr, nl):
    return [scores(xm, a, nl) for a in _tmpl_analytic(ts)], 1, 0


for Lms in (250, 100):
    def _mk(Lms):
        def f(xm, xr, ts, sr, nl):
            s0 = int(SKIP_S * sr); Ls = int(Lms * sr / 1000)
            return [scores(xm[s0:], analytic(t)[s0:s0 + Ls], nl) for t in ts], 1, 0
        return f
    VARIANTS[f"short {Lms} ms slice, float, ppm0"] = _mk(Lms)

for (f1, f2, D, Lms) in ((2000, 18000, 3, 250), (4000, 12000, 6, 250), (2000, 18000, 3, 100)):
    def _mk(f1, f2, D, Lms):
        def f(xm, xr, ts, sr, nl):
            s0 = int(SKIP_S * sr); Ls = int(Lms * sr / 1000)
            xb = baseband(xr[s0:], sr, f1, f2, D)
            return [scores(q1(xb), q1(baseband(t[s0:s0 + Ls], sr, f1, f2, D)), nl // D) for t in ts], D, 0
        return f
    VARIANTS[f"STACK baseband {f1//1000}-{f2//1000} /{D} 1-bit {Lms} ms, ppm0"] = _mk(f1, f2, D, Lms)


def main(nmax):
    sessions = sorted(p for p in (FIELD / "data" / "sessions").iterdir() if (p / "result.json").exists())[:nmax]
    stats = {v: {"loss_db": [], "margin_db": [], "dt_ms": [], "miss": 0, "n": 0, "Tratio": []} for v in VARIANTS}
    flights = {v: [] for v in VARIANTS}   # (session, k, label, base_flight, var_flight)
    late = {d: [] for d in D_LIST_MS}
    early_ms = []
    t0 = time.time()
    for sd in sessions:
        sess = json.loads((sd / "session.json").read_text())
        res = json.loads((sd / "result.json").read_text())
        seed = sess["seed_hex"]; lab = sess["labels"]["label_cm"]
        rec = {L: _read_wav(sd / f"recording_{L}.wav") for L in "AB"}
        nulls = {}
        for rd in res["probes"][PROBE]["rounds"]:
            k = rd["k"]
            tv = {v: {} for v in VARIANTS}
            for key, a in rd["arrivals"].items():
                if not a:
                    continue
                E, L = key.split("_at_")
                x, sr = rec[L]
                lo = int(round(a["window"][0] * sr)); hi = int(round(a["window"][1] * sr))
                nl = hi - lo
                Lt = int(sr * 1.0) + 200
                seg = x[lo: hi + Lt]
                if len(seg) < nl + Lt:
                    seg = np.concatenate([seg, np.zeros(nl + Lt - len(seg))])
                xm = masked(seg, sr)
                ppm = a.get("ppm", 0) or 0
                if (E, sr) not in nulls:
                    nulls[(E, sr)] = [fp.null_template(seed, PROBE, E, sr, i) for i in range(N_NULL)]
                ts = [fp.template(seed, PROBE, E, sr)] + nulls[(E, sr)]
                ts0 = [masked(t, sr) for t in ts]
                ts = [masked(_stretch(t, ppm), sr) for t in ts]
                ref_i = int(round(a["t"] * sr)) - lo
                for v, f in VARIANTS.items():
                    r = f(xm, seg, ts0 if "ppm0" in v else ts, sr, nl)
                    out, D, off = r[:3]
                    M = r[3] if len(r) > 3 else 1
                    env, sc = out[0]
                    nsc = np.concatenate([o[1] for o in out[1:]])
                    T = ray_T(nsc, len(sc), M)
                    i, _ = _first_arrival(env, sc, T, max(2, int(round(0.005 * sr / D))))
                    st = stats[v]; st["n"] += 1
                    ref_d = min(len(sc) - 1, int(round(ref_i / D)))
                    st["loss_db"].append(20 * math.log10(max(sc[max(0, ref_d - 1):ref_d + 2].max(), 1e-9) / (a["right_pct"] / 100)))
                    if v.startswith("V0"):
                        st["Tratio"].append(T * 100 / a["T"])
                        # relaxed first-peak: latest T-passing local max with no score >= T in [t'-D, t')
                        if E == L:
                            lm = np.nonzero((sc[1:-1] >= sc[:-2]) & (sc[1:-1] > sc[2:]) & (sc[1:-1] >= T))[0] + 1
                            above = sc >= T
                            cabove = np.concatenate([[0], np.cumsum(above)])
                            for dms in D_LIST_MS:
                                Dn = max(1, int(round(dms * sr / 1000)))
                                ok = [j for j in lm if j > ref_i and cabove[j] - cabove[max(0, j - Dn)] == 0]
                                late[dms].append(1000 * (max(ok) - ref_i) / sr if ok else 0.0)
                        else:
                            ab = np.nonzero(sc >= T)[0]
                            early_ms.append(1000 * (ref_i - ab[0]) / sr if len(ab) else 0.0)
                    if i is None:
                        st["miss"] += 1
                        continue
                    st["margin_db"].append(20 * math.log10(sc[i] / T))
                    fi = float(i)
                    if D > 1 and 0 < i < len(env) - 1:
                        a0, a1, a2 = env[i - 1], env[i], env[i + 1]
                        den = a0 - 2 * a1 + a2
                        if den < 0:
                            fi = i + 0.5 * (a0 - a2) / den
                    dt = (fi * D + off - ref_i) / sr
                    st["dt_ms"].append(1000 * dt)
                    tv[v][key] = a["t"] + dt
            for v in VARIANTS:
                t = tv[v]
                if len(t) == 4 and rd.get("flight_cm") is not None:
                    fl = C / 2 * ((t["B_at_A"] - t["A_at_A"]) - (t["B_at_B"] - t["A_at_B"])) - (rd.get("drift_cm") or 0)
                    flights[v].append((sd.name[:8], k, lab, rd["flight_cm"], fl))
                elif rd.get("flight_cm") is not None:
                    flights[v].append((sd.name[:8], k, lab, rd["flight_cm"], None))
        print(f"  {sd.name[:8]} done {time.time() - t0:.0f}s", file=sys.stderr)

    print(f"\n{PROBE}, {len(sessions)} sessions, baseline arrivals re-scored per variant\n")
    print("| variant | n | miss | score vs base dB (med) | margin dB min / med | abs dt ms p95 / max | flight err cm med / max | decision flips |")
    print("|---|---|---|---|---|---|---|---|")
    for v, st in stats.items():
        fe = [abs(b - f) for (_, _, _, b, f) in flights[v] if f is not None]
        nmiss = sum(1 for r in flights[v] if r[4] is None)
        flips = 0
        # decision per session from median of usable rounds
        bys = {}
        for s, k, lab, b, f in flights[v]:
            bys.setdefault((s, lab), ([], []))
            bys[(s, lab)][0].append(b)
            if f is not None: bys[(s, lab)][1].append(f)
        def dec(fl):
            if len(fl) < 2: return "UND"
            if max(fl) - min(fl) > 40: return "UND"
            m = float(np.median(fl)); return "NEAR" if m < 45 else "FAR" if m > 80 else "UND"
        flips = sum(1 for (s, lab), (b, f) in bys.items() if dec(b) != dec(f))
        adt = np.abs(st["dt_ms"]) if st["dt_ms"] else np.array([np.nan])
        print(f"| {v} | {st['n']} | {st['miss']} | {np.median(st['loss_db']):+.1f} | "
              f"{(min(st['margin_db']) if st['margin_db'] else float('nan')):.1f} / {np.median(st['margin_db']) if st['margin_db'] else float('nan'):.1f} | "
              f"{np.percentile(adt, 95):.2f} / {np.max(adt):.2f} | "
              f"{(np.median(fe) if fe else float('nan')):.1f} / {(max(fe) if fe else float('nan')):.1f} | {flips} (rounds lost {nmiss}) |")
    print(f"\nV0 Rayleigh-T / Gumbel-T (result.json): median {np.median(stats[list(VARIANTS)[0]]['Tratio']):.3f} "
          f"range {min(stats[list(VARIANTS)[0]]['Tratio']):.3f}..{max(stats[list(VARIANTS)[0]]['Tratio']):.3f}")
    print("\nself arrival, relaxed first-peak (check only D lags before the claimed lag): late-claim gain ms")
    for d, g in late.items():
        g = np.array(g)
        print(f"  D = {d:5} ms: median {np.median(g):6.2f}  p90 {np.percentile(g, 90):6.2f}  max {g.max():7.2f}  "
              f"(= {C / 2 * g.max() / 1000:.0f} cm one arrival)  zero-gain {np.mean(g == 0) * 100:.0f}%")
    e = np.array(early_ms)
    print(f"\ncross arrival, earliest score >= T before the chosen lag: median {np.median(e):.3f} ms, max {e.max():.3f} ms")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 99)
