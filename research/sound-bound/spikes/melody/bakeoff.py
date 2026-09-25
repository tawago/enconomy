"""Melody-vs-noise probe bake-off (offline, deterministic apart from timings).

  /Users/takahiro_ogawa/dev/enconomy/research/proximity-echo/.venv/bin/python3 bakeoff.py [--quick]

Writes wav/ and results.json next to this file and prints markdown tables.

Two receivers are scored for every candidate:
  plain  exactly analysis.py: matched filter on the raw code, Hilbert envelope,
         first local max >= half the window max (analysis._find_arrival).
  white  same rule, but code and recording are both equalised by 1/|C(f)|
         (smoothed; inside the code's band; floored WHITE_FLOOR_DB below its median).
         Every frequency the code occupies then counts once, whatever its
         loudness -- so a quiet secret layer weighs as much as the loud tune.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import time

import numpy as np
import soundfile as sf
from scipy.fft import next_fast_len
from scipy.signal import butter, fftconvolve, hilbert, resample, sosfilt
from scipy.stats import gumbel_r

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))
import analysis  # noqa: E402  read-only: _find_arrival, _window, _flat_runs
import melody_probes as mp  # noqa: E402

QUICK = "--quick" in sys.argv
SR = 48000
C_CM = 34300.0
HALF_C = C_CM / 2.0               # flight cm per second of arrival error
CANDS = mp.VARIANTS
KINDS = ("plain", "white")
RXS = ("plain/mad", "plain/null", "white/null")
COLOR_DB = 6.0                    # unknown speaker/mic EQ ripple per phone
SELF_M = 0.12
NOISE_DB = -40.0                  # noise RMS re self-path direct RMS
LEAD = 0.3
LAT = (0.05, 0.15)                # per-phone stack latency, s
RESID = 0.005                     # residual clock error, s
PPM = 50.0                        # each phone's sample clock +-PPM
DISTS = (0.05, 0.30, 1.00, 2.00)
TRIALS = 3 if QUICK else 8
N_NULL = 60 if QUICK else 300
N_NOISE_NULL = 30 if QUICK else 150
ROOMS = {
    # synth_check.py's room: RT60 0.4 s, fixed tail level 0.05
    "normal": {"rt60": 0.4, "tail": 0.05, "early": (0.01, 0.03)},
    # small reverberant room, tail level calibrated so the N30 plain score at
    # 1-2 m lands in the 20-26 % seen on real data (see calibrate())
    "harsh": {"rt60": 0.6, "tail": 1.2, "early": (0.05, 0.12)},
}
WHITE_BAND_DB = -40.0             # whiten only inside the code's own band (500 Hz-smoothed
                                  # spectrum within 40 dB of its max): out-of-band room
                                  # noise is never boosted
WHITE_FLOOR_DB = -20.0            # and never boost a bin more than 20 dB above the code's
                                  # in-band MEDIAN level (a floor relative to the peak let a
                                  # few band-edge bins dominate the N1s null: one 8 % outlier)
WHITE_SMOOTH_HZ = 10.0
WHITE_FIR_S = 0.1
HOLE_N = 960                      # 20 ms at 48 kHz, as seen on Android


def b_off(cand):
    return {"N30": 0.5, "N250": 0.6}.get(cand, mp.DUR_S + 0.35)


def seed_of(*parts) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()


# ---------------------------------------------------------------- receivers
def whiten_fir(code, sr):
    lw = int(WHITE_FIR_S * sr) | 1
    nfft = 1 << int(np.ceil(np.log2(2 * max(len(code), lw))))
    p = np.abs(np.fft.rfft(code, nfft)) ** 2
    sm = max(1, int(round(WHITE_SMOOTH_HZ * nfft / sr)))
    if sm > 1:
        p = np.convolve(p, np.ones(sm) / sm, mode="same")
    cs = np.sqrt(p)
    wide = max(1, int(round(500.0 * nfft / sr)))
    pw = np.convolve(p, np.ones(wide) / wide, mode="same")
    band = pw >= pw.max() * 10 ** (WHITE_BAND_DB / 10)
    floor = np.median(cs[band]) * 10 ** (WHITE_FLOOR_DB / 20)
    w_f = np.where(cs >= floor, 1.0 / np.maximum(cs, 1e-30), cs / floor**2) * band
    w = np.fft.fftshift(np.fft.irfft(w_f, nfft))
    h = lw // 2
    w = w[nfft // 2 - h : nfft // 2 + h + 1] * np.hanning(lw)
    return w / np.sqrt(np.sum(w * w))


class Rx:
    def __init__(self, code, kind):
        self.code = np.asarray(code, dtype=np.float64)
        self.kind = kind
        if kind == "plain":
            self.w = None
            self.tmpl = self.code
        else:
            self.w = whiten_fir(self.code, SR)
            self.tmpl = fftconvolve(self.code, self.w, mode="same")
        self.L = len(self.tmpl)
        self.tnorm = float(np.sqrt(np.sum(self.tmpl**2)))

    def pre(self, x):
        return x if self.w is None else fftconvolve(x, self.w, mode="same")

    def env_score(self, x):
        """(envelope, normalized score) indexed by code onset sample."""
        xw = self.pre(np.asarray(x, dtype=np.float64))
        corr = fftconvolve(xw, self.tmpl[::-1], mode="full")[self.L - 1 :]
        nf = next_fast_len(len(corr))
        env = np.abs(hilbert(corr, N=nf)[: len(corr)])
        cs = np.concatenate([[0.0], np.cumsum(xw * xw)])
        n = np.arange(len(corr))
        end = np.minimum(n + self.L, len(xw))
        nx = np.sqrt(np.maximum(cs[end] - cs[n], 0.0))
        return env, env / (nx * self.tnorm + 1e-30)


# ---------------------------------------------------------------- room sim
def add_delayed(buf, sig, t_s, sr=SR):
    """Add sig into buf at fractional time t_s via an FFT phase ramp."""
    n0 = int(np.floor(t_s * sr))
    frac = t_s * sr - n0
    m = next_fast_len(len(sig) + 64)
    spec = np.fft.rfft(sig, m)
    k = np.arange(len(spec))
    spec *= np.exp(-2j * np.pi * k * frac / m)
    y = np.fft.irfft(spec, m)
    a, b = n0, min(len(buf), n0 + m)
    if a >= 0 and b > a:
        buf[a:b] += y[: b - a]


def warp(x, eps):
    """Time-stretch by (1+eps), band-limited (FFT resample of a long zero-padded copy)."""
    if eps == 0:
        return x
    big = 1 << 19
    m = int(round(eps * big))
    if m == 0:
        return x
    pad = np.zeros(big)
    pad[: len(x)] = x
    y = resample(pad, big + m)
    return y[: len(x) + max(m, 0) + 64]


def rir(rng, room, amp):
    """Direct tap, four early reflections, then a diffuse tail that builds up
    over ~10 ms and decays 60 dB per RT60.  Tail energy is fixed per room
    (independent of distance), as in synth_check.py."""
    rt60 = room["rt60"]
    n = int(1.5 * rt60 * SR)
    h = np.zeros(n)
    h[0] = amp
    for _ in range(4):  # table, walls, ceiling
        d = rng.uniform(0.0007, 0.008)
        h[int(round(d * SR))] += rng.uniform(*room["early"]) * rng.choice([-1, 1])
    t = np.arange(n) / SR
    tt = np.clip(t - 0.003, 0, None)
    tail = rng.normal(0, 1, n) * 10 ** (-3.0 * t / rt60) * (1 - np.exp(-tt / 0.010))
    tail *= room["tail"] / np.sqrt(np.sum(tail**2))
    return h + tail


def color_fir(rng):
    """Unknown device response: smooth random EQ +-COLOR_DB, linear phase,
    fixed length (so its delay is the same on every path and cancels)."""
    nfft = 512
    f = np.fft.rfftfreq(nfft, 1 / SR)
    knots = np.geomspace(200, 20000, 12)
    db = np.interp(np.log(np.maximum(f, 1)), np.log(knots), rng.uniform(-COLOR_DB, COLOR_DB, 12))
    h = np.fft.fftshift(np.fft.irfft(10 ** (db / 20), nfft))[1:] * np.hanning(nfft - 1)
    return h / np.sum(h)


def scenario(room_name, d, k):
    """Everything physical about one round, independent of the candidate, so
    every candidate meets the same rooms, latencies, drifts and devices."""
    rng = np.random.default_rng(int(seed_of("scene", room_name, d, k)[:12], 16))
    room = ROOMS[room_name]
    sc = {"room": room_name, "d": d, "k": k,
          "lat": {r: rng.uniform(*LAT) for r in "AB"},
          "resid": {r: rng.uniform(-RESID, RESID) for r in "AB"},
          "ppm": {r: rng.uniform(-PPM, PPM) * 1e-6 for r in "AB"},
          "spk": {r: color_fir(rng) for r in "AB"},
          "mic": {r: color_fir(rng) for r in "AB"},
          "noise_seed": int(rng.integers(1 << 31))}
    sc["rir"] = {f"{em}_at_{lis}": rir(rng, room, 1.0 if em == lis else SELF_M / max(d, 0.01))
                 for lis in "AB" for em in "AB"}
    return sc


def build_round(cand, sc, seed):
    d = sc["d"]
    codes = {r: mp.generate(seed, r, SR, cand).astype(np.float64) for r in "AB"}
    emitted = {r: mp.speaker(codes[r], SR) for r in "AB"}
    lat, resid, ppm = sc["lat"], sc["resid"], sc["ppm"]
    sched = {"A": 0.0, "B": b_off(cand)}
    L = len(codes["A"])
    n = int((LEAD + b_off(cand) + L / SR + 1.0) * SR)
    cap = {r: -LEAD + lat[r] + resid[r] for r in "AB"}
    sigma = mp.TARGET_RMS * 10 ** (NOISE_DB / 20)
    nrng = np.random.default_rng(sc["noise_seed"])
    recs, truth, expected = {}, {}, {}
    for lis in "AB":
        buf = nrng.normal(0, sigma, n)
        for em in "AB":
            key = f"{em}_at_{lis}"
            same = em == lis
            dist = SELF_M if same else d
            sig = emitted[em] if same else warp(emitted[em], ppm[lis] - ppm[em])
            path = fftconvolve(sc["rir"][key], np.convolve(sc["spk"][em], sc["mic"][lis]))
            y = fftconvolve(sig, path)
            t = sched[em] + lat[em] + dist / (C_CM / 100) - cap[lis]
            add_delayed(buf, y, t)
            truth[key] = t
            expected[key] = sched[em] + LEAD
        recs[lis] = buf
    return {"codes": codes, "recs": recs, "truth": truth, "expected": expected,
            "d": d, "cand": cand}


def find_arrival_null(env, score, exp, thr):
    """Long-code rule: first local max >= half the window max AND whose
    normalized score clears the null threshold (replaces the MAD floor)."""
    lo, hi = analysis._window(exp, SR)
    lo, hi = max(lo, 0), min(hi, len(env))
    w = env[lo:hi]
    s = score[lo:hi]
    wmax = float(np.max(w))
    inner = w[1:-1]
    ok = ((inner >= w[:-2]) & (inner > w[2:])
          & (inner >= analysis.QUALIFY_FRAC_OF_MAX * analysis.QUALIFY_FRAC_TOL * wmax)
          & (s[1:-1] >= thr))
    idx = np.nonzero(ok)[0]
    return None if idx.size == 0 else (lo + int(idx[0]) + 1) / SR


def evaluate(rd, rxname, recs=None, thr=None):
    """rxname: 'plain/mad' (analysis.py verbatim), 'plain/null', 'white/null'."""
    kind, rule = rxname.split("/")
    recs = recs or rd["recs"]
    rx = {r: Rx(rd["codes"][r], kind) for r in "AB"}
    out = {"arr": {}, "score": {}, "xfire": {}}
    for lis in "AB":
        es = {em: rx[em].env_score(recs[lis]) for em in "AB"}
        for em in "AB":
            key = f"{em}_at_{lis}"
            env, sc = es[em]
            wenv, _ = es["B" if em == "A" else "A"]
            exp = rd["expected"][key]
            if rule == "mad":
                a = analysis._find_arrival(env, SR, exp)
                out["arr"][key] = a["t_s"] if a else None
            else:
                out["arr"][key] = find_arrival_null(env, sc, exp, thr[kind])
            lo, hi = analysis._window(exp, SR)
            lo, hi = max(lo, 0), min(hi, len(env))
            out["score"][key] = float(np.max(sc[lo:hi]))
            out["xfire"][key] = 20 * np.log10(np.max(env[lo:hi]) / np.max(wenv[lo:hi]))
    a = out["arr"]
    if None in a.values():
        out["flight_cm"] = None
    else:
        delta = (a["B_at_A"] - a["A_at_A"]) - (a["B_at_B"] - a["A_at_B"])
        out["flight_cm"] = HALF_C * delta
    out["truth_cm"] = 100.0 * (rd["d"] - SELF_M)
    return out


# ---------------------------------------------------------------- metric 1
def autocorr_metrics(cand, kind, seed):
    c = mp.generate(seed, "A", SR, cand).astype(np.float64)
    pad = int(0.3 * SR)
    r = np.concatenate([np.zeros(pad), mp.speaker(c, SR), np.zeros(pad + len(c))])
    env, _ = Rx(c, kind).env_score(r)
    p = int(np.argmax(env))
    e = env / env[p]
    lag = (np.arange(len(e)) - p) / SR
    # FWHM
    i = p
    while i > 0 and e[i] >= 0.5:
        i -= 1
    j = p
    while j < len(e) - 1 and e[j] >= 0.5:
        j += 1
    fwhm_s = (j - i) / SR
    # mainlobe = down to first local minimum on each side
    lo = p
    while lo > 0 and e[lo - 1] < e[lo]:
        lo -= 1
    hi = p
    while hi < len(e) - 1 and e[hi + 1] < e[hi]:
        hi += 1
    side = e.copy()
    side[lo : hi + 1] = 0.0
    m15 = np.abs(lag) <= 0.015
    k15 = int(np.argmax(np.where(m15, side, 0)))
    # before the true peak inside the search window: this is what the
    # first-peak >= half-max rule would jump to
    mpre = (lag < 0) & (lag >= -analysis.SEARCH_PRE_S)
    kpre = int(np.argmax(np.where(mpre, side, 0)))
    pitch = 0.0
    for t0 in mp.pitch_periods_s("A"):
        for s in (-1, 1):
            m = np.abs(lag - s * t0) <= 0.00005
            pitch = max(pitch, float(np.max(side[m])))
    return {"fwhm_cm": fwhm_s * HALF_C, "sl15": float(side[k15]),
            "sl15_cm": float(lag[k15] * HALF_C), "pre": float(side[kpre]),
            "pre_cm": float(lag[kpre] * HALF_C),
            "pitch": pitch if cand.startswith("M") else None}


# ---------------------------------------------------------------- metric 2
def noise_code(i, n):
    rng = np.random.default_rng(10_000 + i)
    x = sosfilt(butter(4, (2000, 18000), "bandpass", fs=SR, output="sos"),
                rng.normal(0, 1, n + 2000))[2000:]
    x = mp._fade(x, SR)
    return x * mp.TARGET_RMS / np.sqrt(np.mean(x * x))


def window_max(code, kind, x, exp):
    rx = Rx(code, kind)
    lo, hi = analysis._window(exp, SR)
    lo = max(lo, 0)
    margin = len(rx.w) if rx.w is not None else 0
    a = max(0, lo - margin)
    b = min(len(x), hi + rx.L + margin)
    _, sc = rx.env_score(x[a:b])
    return float(np.max(sc[lo - a : hi - a]))


def null_stats(samples):
    s = np.asarray(samples)
    loc, scale = gumbel_r.fit(s)
    return {"n": len(s), "median": float(np.median(s)), "max": float(s.max()),
            "T1e-4": float(gumbel_r.isf(1e-4, loc, scale)),
            "T1e-6": float(gumbel_r.isf(1e-6, loc, scale))}


# ---------------------------------------------------------------- metric 4
def split_arrivals(rx, x, t_arr):
    """Arrival of the code's first and second half, each by its own matched filter."""
    h = rx.L // 2
    xw = rx.pre(x)
    out = []
    for part, off in ((rx.tmpl[:h], 0), (rx.tmpl[h:], h)):
        corr = fftconvolve(xw, part[::-1], mode="full")[len(part) - 1 :]
        env = np.abs(hilbert(corr, N=next_fast_len(len(corr)))[: len(corr)])
        c0 = int(round(t_arr * SR)) + off
        lo, hi = max(0, c0 - int(0.04 * SR)), min(len(env), c0 + int(0.04 * SR))
        out.append((lo + int(np.argmax(env[lo:hi])) - off) / SR)
    return out


def hole_test(rxname, rd, base, thr):
    """20 ms hole inside A's code as heard by B (A_at_B), at 5 positions.
    insert = Android-style: 960 zeros, everything after slips 20 ms late.
    replace = 960 samples zeroed in place, no slip."""
    x0 = rd["recs"]["B"]
    t_true = base["arr"]["A_at_B"]    # observed onset (device filters add ~10 ms)
    L = len(rd["codes"]["A"])
    rows = []
    for mode in ("insert", "replace"):
        for frac in (0.1, 0.3, 0.5, 0.7, 0.9):
            i = int(round(t_true * SR + frac * L - HOLE_N / 2))
            if mode == "replace":
                x = x0.copy()
                x[i : i + HOLE_N] = 0.0
            else:
                x = np.concatenate([x0[:i], np.zeros(HOLE_N), x0[i:]])[: len(x0)]
            ev = evaluate(rd, rxname, {"A": rd["recs"]["A"], "B": x}, thr)
            t = ev["arr"]["A_at_B"]
            err_ms = None if t is None else (t - base["arr"]["A_at_B"]) * 1000
            s1, s2 = split_arrivals(Rx(rd["codes"]["A"], rxname.split("/")[0]), x,
                                    t if t is not None else t_true)
            rows.append({"mode": mode, "frac": frac, "err_ms": err_ms,
                         "flat_flag": bool(analysis._flat_runs(x, SR)),
                         "split_flag": bool(abs(s2 - s1) > 0.001),
                         "split_ms": (s2 - s1) * 1000})
    return rows


# ---------------------------------------------------------------- main
def write_wavs():
    wd = HERE / "wav"
    wd.mkdir(exist_ok=True)
    seed = "5b" * 32
    gap = np.zeros(int(0.2 * SR))
    for cand in CANDS:
        a = mp.generate(seed, "A", SR, cand)
        b = mp.generate(seed, "B", SR, cand)
        sf.write(str(wd / f"{cand}_A.wav"), a, SR, subtype="PCM_16")
        sf.write(str(wd / f"{cand}_B.wav"), b, SR, subtype="PCM_16")
        sf.write(str(wd / f"{cand}_AB.wav"), np.concatenate([a, gap, b]), SR,
                 subtype="PCM_16")


def calibrate():
    """N30 plain score at 1-2 m in the harsh room (target: 20-26 %)."""
    s = []
    for d in (1.0, 2.0):
        for k in range(4):
            rd = build_round("N30", scenario("harsh", d, 900 + k), seed_of("cal", d, k))
            ev = evaluate(rd, "plain/mad")
            s += [ev["score"]["A_at_B"], ev["score"]["B_at_A"]]
    return float(np.median(s))


def timing():
    rng = np.random.default_rng(5)
    x = rng.normal(0, 0.01, 3 * SR)
    out = {}
    for cand in ("N30", "N1s"):
        c = mp.generate("00" * 32, "A", SR, cand).astype(np.float64)
        for label, seg in (("3s", x), ("win", x[: int(0.4 * SR) + len(c)])):
            ts = []
            for _ in range(7):
                t0 = time.perf_counter()
                corr = fftconvolve(seg, c[::-1], mode="full")[len(c) - 1 :]
                np.abs(hilbert(corr, N=next_fast_len(len(corr))))
                ts.append(time.perf_counter() - t0)
            out[f"{cand}_{label}_ms"] = 1000 * float(np.median(ts))
    ts = []
    for _ in range(3):
        t0 = time.perf_counter()
        mp.generate("00" * 32, "A", SR, "M-air")
        ts.append(time.perf_counter() - t0)
    out["gen_M-air_ms"] = 1000 * float(np.median(ts))
    return out


def fmt_walk(cand, room, d, rxname, r):
    return (f"walk {cand:7s} {room:6s} d={d:4.2f} {rxname:10s} ok={r['n_ok']}/{r['n']} "
            f"err_med={r['err_med']} absmax={r['err_absmax']} bad={r['n_bad20']} "
            f"score={r['score_med']:.3f} xfire_min={r['xfire_min']:.1f}")


def main():
    t_start = time.time()
    write_wavs()
    res = {"config": {"quick": QUICK, "trials": TRIALS, "n_null": N_NULL,
                      "rooms": ROOMS, "white_floor_db": WHITE_FLOOR_DB,
                      "air_rel_db": mp.AIR_REL_DB, "knot_s": mp.KNOT_S,
                      "color_db": COLOR_DB, "ppm": PPM, "noise_db": NOISE_DB}}
    res["crest_db"] = {}
    for cand in CANDS:
        x = mp.generate("5b" * 32, "A", SR, cand).astype(np.float64)
        res["crest_db"][cand] = float(20 * np.log10(np.max(np.abs(x)) / np.sqrt(np.mean(x * x))))
    res["calib_N30_harsh_far_score"] = calibrate()
    print(f"calibration: N30 plain score harsh 1-2 m median = "
          f"{100*res['calib_N30_harsh_far_score']:.1f} %", flush=True)

    # metric 1 -- autocorrelation through the speaker model
    res["autocorr"] = {}
    for cand in CANDS:
        for kind in KINDS:
            ms = [autocorr_metrics(cand, kind, seed_of("ac", s)) for s in range(3)]
            # mean mainlobe width; worst sidelobe over seeds, with that seed's lag
            agg = {"fwhm_cm": float(np.mean([m["fwhm_cm"] for m in ms]))}
            for k in ("sl15", "pre", "pitch"):
                agg[k] = None if ms[0][k] is None else float(np.max([m[k] for m in ms]))
            w = int(np.argmax([m["sl15"] for m in ms]))
            agg["sl15_cm"] = ms[w]["sl15_cm"]
            w = int(np.argmax([m["pre"] for m in ms]))
            agg["pre_cm"] = ms[w]["pre_cm"]
            res["autocorr"][f"{cand}/{kind}"] = agg
            print(f"autocorr {cand:7s} {kind:5s} {agg}", flush=True)

    # metric 2 -- null: same tune (attacker knows it), other seeds; and plain
    # noise codes.  Scored over the real search window of a harsh-room far
    # recording that carries the true code.
    null_scenes = [scenario("harsh", d, 100 + k) for d in (1.0, 2.0) for k in range(3)]
    res["null"] = {}
    thr = {}
    for cand in CANDS:
        recs = []
        for j, sc in enumerate(null_scenes):
            rd = build_round(cand, sc, seed_of("nullrec", j))
            recs.append((rd["recs"]["B"], rd["expected"]["A_at_B"]))
        L = len(mp.generate("00" * 32, "A", SR, cand))
        thr[cand] = {}
        for kind in KINDS:
            s_tune = [window_max(mp.generate(seed_of("null", i), "A", SR, cand).astype(np.float64),
                                 kind, *recs[i % len(recs)]) for i in range(N_NULL)]
            s_noise = [window_max(noise_code(i, L), kind, *recs[i % len(recs)])
                       for i in range(N_NOISE_NULL)]
            st = {"same_tune": null_stats(s_tune), "noise": null_stats(s_noise)}
            res["null"][f"{cand}/{kind}"] = st
            thr[cand][kind] = st["same_tune"]["T1e-6"]
            print(f"null {cand:7s} {kind:5s} tune: med {st['same_tune']['median']:.4f} "
                  f"max {st['same_tune']['max']:.4f} T1e-4 {st['same_tune']['T1e-4']:.4f} "
                  f"T1e-6 {st['same_tune']['T1e-6']:.4f} | noise T1e-6 {st['noise']['T1e-6']:.4f}",
                  flush=True)
    res["thr"] = thr

    # metric 3 -- the walk
    res["walk"] = {}
    for cand in CANDS:
        for room in ROOMS:
            for d in DISTS:
                cell = {rxn: [] for rxn in RXS}
                for k in range(TRIALS):
                    rd = build_round(cand, scenario(room, d, k), seed_of("walk", room, d, k))
                    for rxn in RXS:
                        cell[rxn].append(evaluate(rd, rxn, thr=thr[cand]))
                for rxn in RXS:
                    evs = cell[rxn]
                    errs = [e["flight_cm"] - e["truth_cm"] for e in evs if e["flight_cm"] is not None]
                    sc = [v for e in evs for kk, v in e["score"].items() if kk[0] != kk[-1]]
                    xf = [v for e in evs for v in e["xfire"].values()]
                    r = {"n": len(evs), "n_ok": len(errs),
                         "err_med": float(np.median(errs)) if errs else None,
                         "err_absmax": float(np.max(np.abs(errs))) if errs else None,
                         "spread": float(np.ptp(errs)) if errs else None,
                         "n_bad20": int(sum(abs(e) > 20 for e in errs)) + len(evs) - len(errs),
                         "score_med": float(np.median(sc)), "score_p10": float(np.percentile(sc, 10)),
                         "xfire_min": float(np.min(xf))}
                    res["walk"][f"{cand}/{room}/{d}/{rxn}"] = r
                    print(fmt_walk(cand, room, d, rxn, r), flush=True)

    # metric 4 -- 20 ms hole inside the sound; normal room, 1 m, two rounds
    res["hole"] = {}
    for cand in CANDS:
        for rxn in RXS:
            rows = []
            for k in range(2):
                rd = build_round(cand, scenario("normal", 1.0, 7000 + k), seed_of("hole", k))
                base = evaluate(rd, rxn, thr=thr[cand])
                if base["arr"]["A_at_B"] is None:
                    continue
                rows += hole_test(rxn, rd, base, thr[cand])
            res["hole"][f"{cand}/{rxn}"] = rows
            bad = [(r["mode"], r["frac"], None if r["err_ms"] is None else round(r["err_ms"], 2))
                   for r in rows if r["err_ms"] is None or abs(r["err_ms"]) > 0.2]
            print(f"hole {cand:7s} {rxn:10s} n={len(rows)} wrong={bad} "
                  f"flat_all={all(r['flat_flag'] for r in rows)} "
                  f"split_insert={sum(r['split_flag'] for r in rows if r['mode']=='insert')}/"
                  f"{sum(1 for r in rows if r['mode']=='insert')}", flush=True)

    res["timing"] = timing()
    print("timing", res["timing"])
    res["wall_s"] = time.time() - t_start
    name = "results_quick.json" if QUICK else "results.json"
    (HERE / name).write_text(json.dumps(res, indent=1, default=float))
    print(f"done in {res['wall_s']:.0f} s -> {name}")


def table(res):
    """Markdown comparison table from a results dict."""
    def walk(cand, room, rxn, ds):
        rs = [res["walk"][f"{cand}/{room}/{d}/{rxn}"] for d in ds]
        bad = sum(r["n_bad20"] for r in rs)
        n = sum(r["n"] for r in rs)
        errs = [abs(r["err_med"]) for r in rs if r["err_med"] is not None]
        return bad, n, (max(errs) if errs else None)

    hdr = ("| cand | crest dB | mainlobe cm (plain/white) | worst early sidelobe (plain/white) "
           "| pitch-period peak (plain/white) | null same-tune T1e-6 (plain/white) "
           "| right% harsh 1-2 m median/p10 (white) | margin p10 vs T1e-6 dB (plain/white) "
           "| walk normal: bad/n (best rx) | walk harsh <=1 m: bad/n (best rx) | walk harsh 2 m bad/n "
           "| insert hole: wrong/n |")
    lines = [hdr, "|" + "---|" * (hdr.count("|") - 1)]
    for cand in CANDS:
        ac = {k: res["autocorr"][f"{cand}/{k}"] for k in KINDS}
        nl = {k: res["null"][f"{cand}/{k}"]["same_tune"]["T1e-6"] for k in KINDS}
        far = {k: [res["walk"][f"{cand}/harsh/{d}/{k}/null"] for d in (1.0, 2.0)] for k in KINDS}
        med = {k: np.mean([r["score_med"] for r in far[k]]) for k in KINDS}
        p10 = {k: min(r["score_p10"] for r in far[k]) for k in KINDS}
        mg = {k: 20 * np.log10(p10[k] / nl[k]) for k in KINDS}
        best = "white/null" if cand != "N30" else "plain/mad"
        wn = walk(cand, "normal", best, DISTS)
        wh = walk(cand, "harsh", best, (0.05, 0.3, 1.0))
        w2 = walk(cand, "harsh", best, (2.0,))
        holes = res["hole"].get(f"{cand}/{best}", [])
        ins = [h for h in holes if h["mode"] == "insert"]
        wrong = sum(1 for h in ins if h["err_ms"] is None or abs(h["err_ms"]) > 0.2)
        pitch = ("-" if ac["plain"]["pitch"] is None else
                 f"{ac['plain']['pitch']:.2f} / {ac['white']['pitch']:.2f}")
        lines.append(
            f"| {cand} | {res['crest_db'][cand]:.1f} "
            f"| {ac['plain']['fwhm_cm']:.1f} / {ac['white']['fwhm_cm']:.1f} "
            f"| {ac['plain']['pre']:.2f}@{ac['plain']['pre_cm']:.0f}cm / {ac['white']['pre']:.2f}@{ac['white']['pre_cm']:.0f}cm "
            f"| {pitch} | {min(nl['plain'], 9.99):.3f} / {nl['white']:.3f} "
            f"| {100*med['white']:.1f} / {100*p10['white']:.1f} "
            f"| {mg['plain']:+.1f} / {mg['white']:+.1f} "
            f"| {wn[0]}/{wn[1]} | {wh[0]}/{wh[1]} | {w2[0]}/{w2[1]} | {wrong}/{len(ins)} |")
    return "\n".join(lines)


if __name__ == "__main__":
    if "--table" in sys.argv:
        print(table(json.loads((HERE / "results.json").read_text())))
    else:
        main()
