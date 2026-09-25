"""Rescore the 18 fieldtest sessions under receiver simplifications that shrink the ZK circuit.

    PY=../../../../proximity-echo/.venv/bin/python3
    $PY rescore.py                       # all single variants + lean stacks, JB and N1s, all sessions
    $PY rescore.py --variants base,rq1pre --sessions 3 --procs 4
    $PY rescore.py --list                # variant names

Reuses fieldanalysis / fieldprobes (imported, never edited).  Nothing is written
into the session folders; results go to shrink/out/.

Receiver model (same as fieldanalysis unless a variant changes it):
  segment of listener L -> [optional pre-mask quantize] -> band(+notch) mask
  -> [optional post-mask quantize] -> per window: analytic matched filter vs
  masked template (real + 64 nulls, x 7 ppm for cross arrivals), score =
  |corr| / (||x_win|| ||c||), T = Gumbel(null maxima) per window, first-peak rule.
Implementation detail that differs from fieldanalysis: correlations are done per
window on a window-sized FFT grid instead of one segment-sized grid (speed); the
recording mask is still applied on the segment grid.  `base` checks the effect.

Variant knobs (cfg keys):
  rq=(bits, 'pre'|'post')  recording quantizer.  scale: 8 bit = segment peak -> +-127;
                           4/2 bit = uniform midrise, step 0.335 / 0.996 x segment RMS
                           (Gaussian-optimal uniform steps), clipped; 1 bit = sign.
                           pre = on the raw recording before the band mask (what a
                           device would commit to); post = on the masked signal.
  tq1                      template -> sign(masked template) and sign(its Hilbert pair),
                           time-limited to the template support; I/Q correlated separately.
  tlen                     keep only the first tlen seconds of every template (real + nulls).
  win_ms, win_center       search window +-win_ms.  'oracle': centred on the baseline arrival
                           plus a deterministic jitter uniform in +-win_ms/2 (emulates an
                           OS-timestamp prior good to +-win_ms/2).  'expected': centred on
                           fieldanalysis' expected time (today's Web Audio prior).
  fixT                     one T per probe for every window: Gumbel isf(NULL_P/3) fitted on the
                           pooled null maxima of the OTHER 17 sessions (leave-one-session-out),
                           same config.  Nulls are then calibration only, not in the circuit.
  ppm0                     no ppm bank (e = 0 only), so no drift correction.
  realonly                 env = |I| (no Hilbert pair): halves the multiplies.
  norm='committed'         normalise by the energy of the committed (quantized, unmasked)
                           recording instead of the masked one; with 1-bit pre it is sqrt(L),
                           a constant.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pickle
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import scipy.fft as sfft
from scipy.stats import gumbel_r

HERE = Path(__file__).resolve().parent
FIELD = HERE.parents[1] / "melody" / "fieldtest"
SESS_DIR = FIELD / "data" / "sessions"
OUT = HERE / "out"
sys.path.insert(0, str(FIELD))
import fieldanalysis as fa  # noqa: E402  read-only
import fieldprobes as fp  # noqa: E402  read-only

PROBES = ("JB", "N1s")
SR = 48000
KEYS4 = ("A_at_A", "B_at_A", "B_at_B", "A_at_B")
WORKERS = int(os.environ.get("RESCORE_FFT_WORKERS", "2"))
BATCH = 16

# ---------------------------------------------------------------- variants
BASE = dict(rq=None, tq1=False, tlen=None, win_ms=None, win_center="oracle", fixT=False,
            ppm0=False, realonly=False, norm="masked")


def V(**kw):
    c = dict(BASE)
    c.update(kw)
    return c


VARIANTS = {
    "base": V(),
    "rq8pre": V(rq=(8, "pre")), "rq4pre": V(rq=(4, "pre")), "rq2pre": V(rq=(2, "pre")), "rq1pre": V(rq=(1, "pre")),
    "rq8post": V(rq=(8, "post")), "rq4post": V(rq=(4, "post")), "rq2post": V(rq=(2, "post")), "rq1post": V(rq=(1, "post")),
    "tq1": V(tq1=True),
    "tl250": V(tlen=0.25), "tl100": V(tlen=0.10),
    "win5": V(win_ms=5.0), "win2": V(win_ms=2.0),
    "win5exp": V(win_ms=5.0, win_center="expected"),
    "fixT": V(fixT=True),
    "ppm0": V(ppm0=True),
    "realonly": V(realonly=True),
    # lean stacks: filled in after the single-knob pass (see README in the reply)
    "lean_a": V(rq=(1, "pre"), tq1=True, tlen=0.25, win_ms=5.0, fixT=True, ppm0=True, norm="committed"),
    "lean_b": V(rq=(1, "pre"), tq1=True, tlen=0.10, win_ms=2.0, fixT=True, ppm0=True, norm="committed"),
    "lean_c": V(rq=(1, "pre"), tq1=True, tlen=0.10, win_ms=2.0, fixT=True, ppm0=True, realonly=True,
                norm="committed"),
    "lean_d": V(rq=(2, "pre"), tq1=True, tlen=0.25, win_ms=2.0, fixT=True, ppm0=True),
    # second pass: in R1CS the recording's bit width only moves range checks, so keep it
    "lean_e": V(tlen=0.25, win_ms=2.0, fixT=True, ppm0=True),
    "lean_f": V(tlen=0.10, win_ms=2.0, fixT=True, ppm0=True),
    "lean_g": V(tlen=0.25, win_ms=2.0, fixT=True, ppm0=True, tq1=True),
    "lean_h": V(tlen=0.25, win_ms=2.0, fixT=True, ppm0=True, tq1=True, rq=(1, "post")),
    "lean_i": V(tlen=0.10, win_ms=2.0, fixT=True, ppm0=True, tq1=True),
    "lean_j": V(tlen=0.25, win_ms=5.0, fixT=True, ppm0=True, tq1=True),
    # same stacks, JB window prior from N1s (see correlate_probe)
    "win2n": V(win_ms=2.0, win_center="n1sprior"),
    "lean_en": V(tlen=0.25, win_ms=2.0, win_center="n1sprior", fixT=True, ppm0=True),
    "lean_fn": V(tlen=0.10, win_ms=2.0, win_center="n1sprior", fixT=True, ppm0=True),
    "lean_gn": V(tlen=0.25, win_ms=2.0, win_center="n1sprior", fixT=True, ppm0=True, tq1=True),
    "lean_hn": V(tlen=0.25, win_ms=2.0, win_center="n1sprior", fixT=True, ppm0=True, tq1=True, rq=(1, "post")),
    "lean_in": V(tlen=0.10, win_ms=2.0, win_center="n1sprior", fixT=True, ppm0=True, tq1=True),
    "win2r": V(win_ms=2.0, win_center="ref"),
    "win5r": V(win_ms=5.0, win_center="ref"),
    "lean_er": V(tlen=0.25, win_ms=2.0, win_center="ref", fixT=True, ppm0=True),
    "lean_fr": V(tlen=0.10, win_ms=2.0, win_center="ref", fixT=True, ppm0=True),
    "lean_gr": V(tlen=0.25, win_ms=2.0, win_center="ref", fixT=True, ppm0=True, tq1=True),
    "lean_hr": V(tlen=0.25, win_ms=2.0, win_center="ref", fixT=True, ppm0=True, tq1=True, rq=(1, "post")),
    "lean_ir": V(tlen=0.10, win_ms=2.0, win_center="ref", fixT=True, ppm0=True, tq1=True),
    "lean_kr": V(tlen=0.10, win_ms=2.0, win_center="ref", fixT=True, ppm0=True, tq1=True, rq=(1, "post")),
    "lean_kn": V(tlen=0.10, win_ms=2.0, win_center="n1sprior", fixT=True, ppm0=True, tq1=True, rq=(1, "post")),
}


# ---------------------------------------------------------------- helpers
def quantize(v: np.ndarray, bits: int) -> np.ndarray:
    if bits == 1:
        return np.where(v >= 0, 1.0, -1.0)
    if bits == 8:
        pk = float(np.max(np.abs(v))) or 1.0
        return np.clip(np.round(v / pk * 127), -127, 127)
    step = {4: 0.335, 2: 0.996}[bits] * (float(np.sqrt(np.mean(v * v))) or 1.0)
    lv = 2 ** (bits - 1)
    return np.clip(np.floor(v / step), -lv, lv - 1) + 0.5


def jitter(sid, p, key, k) -> float:
    h = hashlib.sha256(f"jit|{sid}|{p}|{key}|{k}".encode()).digest()
    return int.from_bytes(h[:8], "big") / 2 ** 64 - 0.5      # uniform in [-0.5, 0.5)


def load_session(sdir: Path):
    session = json.loads((sdir / "session.json").read_text())
    base = json.loads((sdir / "result.json").read_text())
    rec = {}
    for L in fp.ROLES:
        meta = json.loads((sdir / f"meta_{L}.json").read_text())
        x, sr = fa._read_wav(sdir / f"recording_{L}.wav")
        assert sr == SR, (sdir.name, L, sr)
        spans = fa.sb_analysis._flat_runs(x, sr)
        rec[L] = {"x": x, "meta": meta, "spans": spans}
    return session, base, rec


def base_windows(session, rec, p):
    """(E, L, k) -> (lo_s, hi_s, expected_s) exactly as fieldanalysis._analyze."""
    sched = session["schedule"]
    pre = float(sched.get("search_pre_s", fp.SCHEDULE["search_pre_s"]))
    post = float(sched.get("search_post_s", fp.SCHEDULE["search_post_s"]))
    out = {}
    for L in fp.ROLES:
        meta = rec[L]["meta"]
        cap, start = float(meta["capture_start_ctx_s"]), float(meta["start_ctx_s"])
        own = {(d.get("probe"), int(d.get("k"))): float(d["ctx_s"]) for d in meta.get("plays") or []}
        for E in fp.ROLES:
            for k in range(int(sched["probes"][p]["rounds"])):
                if E == L and (p, k) in own:
                    exp = own[(p, k)] - cap
                else:
                    exp = start + fp.offset_s(sched, p, E, k) - cap
                out[(E, L, k)] = (exp - pre, exp + post, exp)
    return out


def base_arrival(base, p, E, L, k):
    r = base["probes"][p]["rounds"][k]
    return r["arrivals"].get(f"{E}_at_{L}")


# ---------------------------------------------------------------- core
class TemplateBank:
    """Raw (stretched, truncated) code waveforms per (probe, E, code, ppm), cached per session."""

    def __init__(self, seed):
        self.seed = seed
        self.raw = {}
        self.st = {}

    def wave(self, p, E, ci, e, tlen):
        key = (p, E, ci, e)
        if key not in self.st:
            if (p, E, ci) not in self.raw:
                self.raw[(p, E, ci)] = (fp.template(self.seed, p, E, SR) if ci == 0
                                        else fp.null_template(self.seed, p, E, SR, ci - 1)).astype(np.float64)
            self.st[key] = fa._stretch(self.raw[(p, E, ci)], e).astype(np.float32)
        c = self.st[key]
        if tlen:
            c = c[: int(round(tlen * SR * (1 + e * 1e-6)))]
        return c

    def drop(self, p):
        self.raw = {k: v for k, v in self.raw.items() if k[0] != p}
        self.st = {k: v for k, v in self.st.items() if k[0] != p}


def correlate_probe(cfg, p, session, base, rec, tb):
    """Per window: best-ppm real env/score, null maxima.  Returns {(E,L,k): dict or None}."""
    sid = session["session_id"]
    wins_s = base_windows(session, rec, p)
    wins = {}
    for key, (lo_s, hi_s, exp) in wins_s.items():
        if cfg["win_ms"]:
            w = cfg["win_ms"] / 1000.0
            if cfg["win_center"] == "expected":
                c = exp
            else:
                # 'n1sprior': JB windows centred on the N1s baseline arrival's latency (same devices,
                # same round), i.e. a prior from a clean probe, not from JB's own (late-locking) result
                pp = "N1s" if (cfg["win_center"] == "n1sprior" and p == "JB") else p
                if cfg["win_center"] == "ref":
                    ref = json.loads((OUT / "ref_arrivals.json").read_text())
                    ba = ref.get(f"{sid}|{p}|{key[0]}_at_{key[1]}|{key[2]}")
                else:
                    ba = base_arrival(base, pp, *key)
                if ba is None:
                    wins[key] = None
                    continue
                c = exp + (ba["t"] - ba["expected"]) + jitter(sid, p, f"{key[0]}_at_{key[1]}", key[2]) * w
            lo_s, hi_s = c - w, c + w
        x = rec[key[1]]["x"]
        lo, hi = int(round(lo_s * SR)), int(round(hi_s * SR))
        clo, chi = max(lo, 0), min(hi, len(x))
        wins[key] = (clo, chi, exp) if chi - clo >= 3 else None

    bank_all = (0,) if cfg["ppm0"] else fa.PPM_BANK
    tlen_n = int(round(cfg["tlen"] * SR)) if cfg["tlen"] else SR
    lmax = int(math.ceil(tlen_n * (1 + max(fa.PPM_BANK) * 1e-6))) + 2
    m = int(round(fa.SEGMENT_MARGIN_S * SR))
    wlen = max(w[1] - w[0] for w in wins.values() if w)
    N = sfft.next_fast_len(wlen + lmax + 2, real=True)
    maskN = fp.rx_mask(p, N, SR).astype(np.float32)
    half = N // 2 + 1

    segs = {}
    for L in fp.ROLES:
        valid = [w for (E, LL, k), w in wins.items() if LL == L and w]
        if not valid:
            continue
        x = rec[L]["x"]
        a = max(0, min(w[0] for w in valid) - m)
        b = min(len(x), max(w[1] for w in valid) + lmax + m)
        xs = x[a:b]
        if cfg["rq"] and cfg["rq"][1] == "pre":
            xs = quantize(xs, cfg["rq"][0])
        committed = xs
        nseg = sfft.next_fast_len(b - a + lmax, real=True)
        xm = sfft.irfft(sfft.rfft(xs, nseg, workers=WORKERS) * fp.rx_mask(p, nseg, SR),
                        nseg, workers=WORKERS)[: b - a]
        if cfg["rq"] and cfg["rq"][1] == "post":
            xm = quantize(xm, cfg["rq"][0])
            committed = xm
        y = committed if cfg["norm"] == "committed" else xm
        cs = np.concatenate([[0.0], np.cumsum(y * y)])
        # the correlation input: masked (the template spectra are masked too, so this is
        # the same as correlating the committed signal with the masked template)
        segs[L] = {"a": a, "n": b - a, "xm": np.concatenate([xm, np.zeros(N)]), "cs": cs}

    out = {key: None for key, w in wins.items() if w is None}
    for E in fp.ROLES:
        lw = {}
        for L in segs:
            keys = [kk for kk, w in wins.items() if kk[0] == E and kk[1] == L and w]
            if keys:
                a = segs[L]["a"]
                spec = []
                for kk in keys:
                    w0, w1 = wins[kk][0] - a, wins[kk][1] - a
                    spec.append(sfft.rfft(segs[L]["xm"][w0 : w0 + N], N, workers=WORKERS).astype(np.complex64))
                lw[L] = {"keys": keys, "spec": spec,
                         "wins": [(wins[kk][0] - a, wins[kk][1] - a) for kk in keys],
                         "bank": bank_all if (E != L and p in fa.BANK_PROBES) else (0,)}
        if not lw:
            continue
        need_e = sorted({e for d in lw.values() for e in d["bank"]}, key=fa.PPM_BANK.index)
        rows = [(ci, e) for ci in range(1 + fa.N_NULL) for e in need_e]
        real = {L: {} for L in lw}   # L -> wi -> e -> (env, sc)
        nmax = {L: np.full((fa.N_NULL, len(need_e), len(lw[L]["wins"])), -1.0) for L in lw}
        for r0 in range(0, len(rows), BATCH):
            chunk = rows[r0 : r0 + BATCH]
            lens = []
            buf = np.zeros((len(chunk), N), dtype=np.float32)
            for j, (ci, e) in enumerate(chunk):
                c = tb.wave(p, E, ci, e, cfg["tlen"])
                buf[j, : len(c)] = c
                lens.append(len(c))
            C = sfft.rfft(buf, axis=-1, workers=WORKERS)
            C *= maskN
            if cfg["tq1"] or cfg["realonly"]:
                # time-domain I (and Q) templates, limited to the template support
                mc = sfft.irfft(C, N, axis=-1, workers=WORKERS)
                hq = np.zeros_like(mc)
                if not cfg["realonly"]:
                    Za = np.zeros((len(chunk), N), dtype=np.complex64)
                    Za[:, :half] = 2 * C
                    hq = sfft.ifft(Za, axis=-1, workers=WORKERS).imag
                    del Za
                tI = np.zeros_like(mc)
                tQ = np.zeros_like(mc)
                for j, n in enumerate(lens):
                    if cfg["tq1"]:
                        tI[j, :n] = np.where(mc[j, :n] >= 0, 1.0, -1.0)
                        tQ[j, :n] = np.where(hq[j, :n] >= 0, 1.0, -1.0)
                    else:
                        tI[j, :n] = mc[j, :n]
                        tQ[j, :n] = hq[j, :n]
                cn = np.sqrt(np.sum(tI * tI, axis=1))
                CI = np.conjugate(sfft.rfft(tI, axis=-1, workers=WORKERS) * maskN)
                CQ = None if cfg["realonly"] else np.conjugate(sfft.rfft(tQ, axis=-1, workers=WORKERS) * maskN)
                del mc, hq, tI, tQ
            else:
                p2 = np.abs(C) ** 2
                cn = np.sqrt((p2[:, 0] + 2 * p2[:, 1:].sum(axis=1) - (p2[:, -1] if N % 2 == 0 else 0.0)) / N)
                del p2
                CI = np.conjugate(C)
            del buf, C
            for L, d in lw.items():
                sel = [j for j, (ci, e) in enumerate(chunk) if e in d["bank"]]
                if not sel:
                    continue
                for wi, (w0, w1) in enumerate(d["wins"]):
                    X = d["spec"][wi]
                    W = w1 - w0
                    if cfg["tq1"] or cfg["realonly"]:
                        rI = sfft.irfft(CI[sel] * X, N, axis=-1, workers=WORKERS)[:, :W]
                        if CQ is None:
                            env_all = np.abs(rI)
                        else:
                            rQ = sfft.irfft(CQ[sel] * X, N, axis=-1, workers=WORKERS)[:, :W]
                            env_all = np.hypot(rI, rQ)
                    else:
                        Z = np.zeros((len(sel), N), dtype=np.complex64)
                        Z[:, :half] = 2 * CI[sel] * X
                        env_all = np.abs(sfft.ifft(Z, axis=-1, workers=WORKERS, overwrite_x=True)[:, :W])
                        del Z
                    for zj, j in enumerate(sel):
                        ci, e = chunk[j]
                        n0 = np.arange(w0, w1)
                        end = np.minimum(n0 + lens[j], segs[L]["n"])
                        nx = np.sqrt(np.maximum(segs[L]["cs"][end] - segs[L]["cs"][n0], 0.0))
                        env = env_all[zj].astype(np.float64)
                        sc = env / (nx * cn[j] + 1e-30)
                        if ci == 0:
                            real[L].setdefault(wi, {})[e] = (env, sc)
                        else:
                            nmax[L][ci - 1, need_e.index(e), wi] = float(np.max(sc))
        for L, d in lw.items():
            bidx = [need_e.index(e) for e in d["bank"]]
            for wi, key in enumerate(d["keys"]):
                best = max(d["bank"], key=lambda e: float(np.max(real[L][wi][e][1])))
                env, sc = real[L][wi][best]
                out[key] = {"env": env.astype(np.float32), "sc": sc.astype(np.float32),
                            "nmax": nmax[L][:, bidx, wi].max(axis=1), "ppm": int(best),
                            "w0abs": wins[key][0], "W": d["wins"][wi][1] - d["wins"][wi][0],
                            "expected": wins[key][2]}
    return out, wins_s


def arrivals(corr, Tfix=None):
    """Apply T (per-window Gumbel or fixed) and the first-peak rule."""
    look = int(round(fa.HALF_LOOKAHEAD_S * SR))
    res = {}
    for key, v in corr.items():
        if v is None:
            res[key] = {"found": False, "why": "window_outside"}
            continue
        T = Tfix if Tfix is not None else fa._gumbel_T(v["nmax"])[0]
        env, sc = v["env"].astype(np.float64), v["sc"].astype(np.float64)
        i, _ = fa._first_arrival(env, sc, T, look)
        mx = float(np.max(sc))
        if i is None:
            res[key] = {"found": False, "why": "below_T" if mx < T else "no_arrival", "T": T,
                        "max_margin_db": 20 * math.log10(max(mx, 1e-12) / T)}
        else:
            r = float(sc[i])
            res[key] = {"found": True, "t": (v["w0abs"] + i) / SR, "ppm": v["ppm"], "T": T,
                        "right": r, "margin_db": 20 * math.log10(max(r, 1e-12) / T)}
    return res


def rounds_and_decision(p, session, rec, arr, wins_s, tlen_s):
    sched = session["schedule"]
    out = []
    for k in range(int(sched["probes"][p]["rounds"])):
        t, reasons = {}, []
        for E in fp.ROLES:
            for L in fp.ROLES:
                a = arr[(E, L, k)]
                if a["found"]:
                    t[f"{E}_at_{L}"] = a
                else:
                    reasons.append(a["why"])
        fl = None
        if len(t) == 4:
            delta = (t["B_at_A"]["t"] - t["A_at_A"]["t"]) - (t["B_at_B"]["t"] - t["A_at_B"]["t"])
            fl = fa.SPEED_OF_SOUND_CM_S * delta / 2
            if p in fa.BANK_PROBES and fa.DRIFT_CORRECT:
                d_ppm = (t["B_at_A"]["ppm"] - t["A_at_B"]["ppm"]) / 2
                fl -= fa.SPEED_OF_SOUND_CM_S / 2 * float(sched["probes"][p]["b_offset_s"]) * d_ppm * 1e-6
        for L in fp.ROLES:
            lo = min(wins_s[(E, L, k)][0] for E in fp.ROLES)
            hi = max(wins_s[(E, L, k)][1] for E in fp.ROLES) + 1.0
            if any(s0 / SR < hi and lo < s1 / SR for s0, s1 in rec[L]["spans"]):
                reasons.append(f"timeline_gap_at_{L}")
        if fl is not None and fl < fa.IMPOSSIBLE_CM:
            reasons.append("impossible_flight")
        out.append({"k": k, "flight_cm": fl, "usable": fl is not None and not reasons, "reasons": reasons,
                    "arr": {kk: arr[(kk[0], kk[-1], k)] for kk in KEYS4}})
    label, rule = fa._decide([r["flight_cm"] for r in out if r["usable"]])
    return out, label, rule


def strip(corr, keep_arrays):
    s = {}
    for key, v in corr.items():
        if v is None:
            s[key] = None
            continue
        d = {kk: vv for kk, vv in v.items() if kk not in ("env", "sc")}
        if keep_arrays:
            d["env"], d["sc"] = v["env"], v["sc"]
        s[key] = d
    return s


def work(args):
    sdir, vnames = args
    t0 = time.time()
    session, base, rec = load_session(Path(sdir))
    tb = TemplateBank(session["seed_hex"])
    res = {"sid": session["session_id"], "label_cm": session["labels"]["label_cm"], "v": {}}
    for p in PROBES:
        for vn in vnames:
            cfg = VARIANTS[vn]
            corr, wins_s = correlate_probe(cfg, p, session, base, rec, tb)
            res["v"].setdefault(vn, {})[p] = {"corr": corr, "wins_s": wins_s}
        tb.drop(p)
    # the per-window-T pass happens here; fixT variants keep arrays for the pooled pass
    slim = {"sid": res["sid"], "label_cm": res["label_cm"], "v": {}, "runtime_s": 0.0}
    for vn, pp in res["v"].items():
        for p, d in pp.items():
            cfg = VARIANTS[vn]
            entry = {"corr": strip(d["corr"], cfg["fixT"]), "wins_s": d["wins_s"]}
            if not cfg["fixT"]:
                arr = arrivals(d["corr"])
                rounds, label, rule = rounds_and_decision(p, session, rec, arr, d["wins_s"], cfg["tlen"])
                entry.update(rounds=rounds, label=label, rule=rule, corr=None)
            slim["v"].setdefault(vn, {})[p] = entry
    slim["runtime_s"] = time.time() - t0
    slim["spans"] = {L: rec[L]["spans"] for L in fp.ROLES}
    slim["session"] = session
    return slim


# ---------------------------------------------------------------- constraint model (zk README)
def poseidon_cost(nsamp, bits):
    per = 15 * max(1, 240 // bits)          # README: 15 x int16 per element, 15 elements per Poseidon(16)
    return 610 * nsamp / per


def constraints(cfg, n_null_in_circuit=None):
    """R1CS estimate per ranging round (4 arrivals), README cost model with the variant's L, K, bits.

    Returns dict: core (1 template/arrival, like README's 7.4e9), full (with the nulls and ppm bank the
    variant still evaluates in-circuit), and core_const_tmpl (1-bit template as circuit constant:
    taps become additions, 0 constraints)."""
    L = int(round((cfg["tlen"] or 1.0) * SR))
    K = int(round(2 * (cfg["win_ms"] / 1000.0) * SR)) if cfg["win_ms"] else int(round(0.4 * SR))
    b = cfg["rq"][0] if cfg["rq"] else 16
    bt = 1 if cfg["tq1"] else 16
    iq = 1 if cfg["realonly"] else 2
    R = L + K - 1
    nn = 0 if cfg["fixT"] else fa.N_NULL
    bank = 1 if cfg["ppm0"] else len(fa.PPM_BANK)

    def arrival(ntempl, const_tmpl=False):
        c = b * R + poseidon_cost(R, b)                           # commit + range-check recording
        c += ntempl * (iq * L * bt + poseidon_cost(iq * L, bt))   # templates committed
        c += 0 if const_tmpl else ntempl * iq * L * K             # taps
        c += 0 if b == 1 and cfg["norm"] == "committed" else R    # window energy squares
        c += ntempl * iq * K                                      # env^2
        c += 4 * 70 * K                                           # first-peak: ~4 comparisons of ~64-bit values per lag
        return c

    core = 4 * arrival(1)
    full = 2 * arrival(1 + nn) + 2 * arrival((1 + nn) * bank)
    return {"L": L, "K": K, "core": core, "full": full,
            "core_const_tmpl": 4 * arrival(1, const_tmpl=True), "taps_core": 4 * iq * L * K}


# ---------------------------------------------------------------- pooled / metrics
def fixed_T(results, vn, p, exclude_sid):
    pool = []
    for r in results:
        if r["sid"] == exclude_sid:
            continue
        for v in r["v"][vn][p]["corr"].values():
            if v is not None:
                pool.extend(np.asarray(v["nmax"]).tolist())
    pool = np.asarray(pool)
    loc, scale = gumbel_r.fit(pool)
    T = float(gumbel_r.isf(fa.NULL_P / fa.NULL_P_SAFETY, loc, scale))
    return max(T, float(pool.max())), pool


def finish_fixT(results, vn):
    Ts = {}
    for p in PROBES:
        Ts[p] = [fixed_T(results, vn, p, r["sid"])[0] for r in results]
        for r, T in zip(results, Ts[p]):
            corr = {k: (None if v is None else v) for k, v in r["v"][vn][p]["corr"].items()}
            arr = arrivals(corr, Tfix=T)
            rounds, label, rule = rounds_and_decision(p, r["session"], {L: {"spans": r["spans"][L]} for L in fp.ROLES},
                                                      arr, r["v"][vn][p]["wins_s"], VARIANTS[vn]["tlen"])
            r["v"][vn][p].update(rounds=rounds, label=label, rule=rule, Tfix=T)
    for r in results:
        for p in PROBES:
            ce = {}
            for (E, L, k), v in r["v"][vn][p]["corr"].items():
                ce.setdefault(f"{E}_at_{L}", {})[k] = r["v"][vn][p]["wins_s"][(E, L, k)][2]
            r["v"][vn][p]["corr_exp"] = ce
            r["v"][vn][p]["corr"] = None
    return {p: (float(np.min(v)), float(np.median(v)), float(np.max(v))) for p, v in Ts.items()}


def truth(label_cm):
    return "NEAR" if label_cm <= 30 else "FAR" if label_cm >= 100 else "MID"


def metrics(results, vn, p, sessions_meta):
    agree = n = 0
    errs, dmarg, lost, gained, nbase = [], [], 0, 0, 0
    correct = wrong = und = 0
    margins, near_fl, far_fl, eref = [], [], [], []
    rf = OUT / "ref_flights.json"
    refl = json.loads(rf.read_text()) if rf.exists() else {}
    for r in results:
        b = sessions_meta[r["sid"]]["base"]["probes"][p]
        d = r["v"][vn][p]
        n += 1
        agree += d["label"] == b["decision"]["label"]
        tr = truth(r["label_cm"])
        fl = [rr["flight_cm"] for rr in d["rounds"] if rr["usable"]]
        if fl and d["label"] != "UNDECIDED":
            (near_fl if tr == "NEAR" else far_fl if tr == "FAR" else []).append(float(np.median(fl)))
        margins += [a["margin_db"] for rr in d["rounds"] if rr["usable"] for a in rr["arr"].values()]
        if tr != "MID":
            if d["label"] == tr:
                correct += 1
            elif d["label"] == "UNDECIDED":
                und += 1
            else:
                wrong += 1
        for rv, rb in zip(d["rounds"], b["rounds"]):
            if rv["usable"] and rb["usable"]:
                errs.append(abs(rv["flight_cm"] - rb["flight_cm"]))
            fr = refl.get(f"{r['sid']}|{p}|{rv['k']}")
            if rv["usable"] and fr is not None:
                eref.append(abs(rv["flight_cm"] - fr))
            for key in KEYS4:
                ab = rb["arrivals"].get(key)
                av = rv["arr"][key]
                if ab:
                    nbase += 1
                    if not av["found"]:
                        lost += 1
                    else:
                        dmarg.append(av["margin_db"] - ab["margin_db"])
                elif av["found"]:
                    gained += 1
    return {"agree": agree, "n": n, "correct": correct, "wrong": wrong, "undecided_on_labeled": und,
            "err_med": float(np.median(errs)) if errs else None, "err_max": float(np.max(errs)) if errs else None,
            "n_err_rounds": len(errs),
            "eref_med": float(np.median(eref)) if eref else None, "eref_max": float(np.max(eref)) if eref else None, "lost": lost, "gained": gained, "nbase": nbase,
            "dmargin_med": float(np.median(dmarg)) if dmarg else None,
            "dmargin_p10": float(np.percentile(dmarg, 10)) if dmarg else None,
            "margin_med": float(np.median(margins)) if margins else None,
            "margin_min": float(np.min(margins)) if margins else None,
            "near_max_fl": max(near_fl) if near_fl else None, "far_min_fl": min(far_fl) if far_fl else None}


def expected_outside(sessions_meta, win_ms):
    """How many baseline arrivals lie outside +-win_ms of fieldanalysis' expected time."""
    tot = out = 0
    offs = []
    for sid, sm in sessions_meta.items():
        for p in PROBES:
            for r in sm["base"]["probes"][p]["rounds"]:
                for key, a in r["arrivals"].items():
                    if a:
                        tot += 1
                        off = 1000 * (a["t"] - a["expected"])
                        offs.append(off)
                        out += abs(off) > win_ms
    return out, tot, (float(np.min(offs)), float(np.median(offs)), float(np.max(offs)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", default=",".join(VARIANTS))
    ap.add_argument("--sessions", type=int, default=0, help="0 = all")
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--reuse", action="store_true", help="reuse out/raw_<tag>.pkl (post-processing only)")
    a = ap.parse_args()
    if a.list:
        for k, v in VARIANTS.items():
            print(k, {kk: vv for kk, vv in v.items() if BASE[kk] != vv})
        return
    vnames = [v for v in a.variants.split(",") if v]
    sdirs = sorted(p for p in SESS_DIR.iterdir() if (p / "result.json").exists())
    if a.sessions:
        sdirs = sdirs[: a.sessions]
    sessions_meta = {d.name: {"base": json.loads((d / "result.json").read_text())} for d in sdirs}
    t0 = time.time()
    OUT.mkdir(exist_ok=True)
    tag = os.environ.get("RESCORE_TAG", "run")
    cache = OUT / f"raw_{tag}.pkl"
    if a.reuse and cache.exists():
        results = pickle.loads(cache.read_bytes())
    else:
        with ProcessPoolExecutor(a.procs) as ex:
            results = list(ex.map(work, [(str(d), vnames) for d in sdirs]))
        cache.write_bytes(pickle.dumps(results))
    print(f"# {len(sdirs)} sessions, {len(vnames)} variants, {time.time() - t0:.0f} s wall")
    Tinfo = {vn: finish_fixT(results, vn) for vn in vnames if VARIANTS[vn]["fixT"]}
    OUT.mkdir(exist_ok=True)
    table = []
    hdr = (f"{'variant':9s} {'probe':4s} {'agree':>6s} {'lab ok/wrong/und':>16s} {'|dfl| med/max cm':>17s} "
           f"{'vsRef med/max':>13s} {'lost/base':>9s} {'gain':>4s} {'dMarg med/p10 dB':>17s} {'marg med/min':>12s} {'NEARmax/FARmin':>14s} {'core R1CS':>9s} {'full R1CS':>9s}")
    print(hdr)
    for vn in vnames:
        cst = constraints(VARIANTS[vn])
        for p in PROBES:
            m = metrics(results, vn, p, sessions_meta)
            row = {"variant": vn, "probe": p, **m, **cst, "cfg": {k: v for k, v in VARIANTS[vn].items()},
                   "Tfix": Tinfo.get(vn, {}).get(p),
                   "labels": {r["sid"][:8]: r["v"][vn][p]["label"] for r in results},
                   "flights": {r["sid"][:8]: [rr["flight_cm"] if rr["usable"] else None
                                              for rr in r["v"][vn][p]["rounds"]] for r in results}}
            table.append(row)
            f = lambda v, s=".1f": "-" if v is None else format(v, s)  # noqa: E731
            print(f"{vn:9s} {p:4s} {m['agree']:>3d}/{m['n']:<2d} {m['correct']:>6d}/{m['wrong']}/{m['undecided_on_labeled']:<6d} "
                  f"{f(m['err_med'], '.2f'):>8s}/{f(m['err_max']):<8s} {f(m['eref_med'], '.2f'):>6s}/{f(m['eref_max']):<6s} {m['lost']:>4d}/{m['nbase']:<4d} {m['gained']:>4d} "
                  f"{f(m['dmargin_med'], '+.2f'):>8s}/{f(m['dmargin_p10'], '+.2f'):<8s} {f(m['margin_med']):>5s}/{f(m['margin_min']):<6s} "
                  f"{f(m['near_max_fl']):>6s}/{f(m['far_min_fl']):<7s} {cst['core']:9.2e} {cst['full']:9.2e}")
    for vn, t in Tinfo.items():
        print(f"fixed T {vn}: " + ", ".join(f"{p} min/med/max {v[0]*100:.2f}/{v[1]*100:.2f}/{v[2]*100:.2f} %"
                                            for p, v in t.items()))
    for w in (5.0, 2.0):
        o, tot, offs = expected_outside(sessions_meta, w)
        print(f"expected-centred +-{w:.0f} ms: {o}/{tot} baseline arrivals outside; "
              f"arrival - expected min/med/max {offs[0]:.1f}/{offs[1]:.1f}/{offs[2]:.1f} ms")
    for vn in vnames:
        for p in PROBES:
            print(f"labels {vn:9s} {p:4s} " + " ".join(
                f"{r['sid'][:4]}:{int(r['label_cm'])}{r['v'][vn][p]['label'][0]}" for r in results))
    if "fixT" in vnames:
        # reference arrivals for win_center='ref': the full-window fixed-T receiver (labels 15/0/0 on both probes)
        ref = {f"{r['sid']}|{p}|{kk}|{rr['k']}": {"t": a["t"], "expected": r["v"]["fixT"][p]["corr_exp"][kk][rr["k"]]}
               for r in results for p in PROBES for rr in r["v"]["fixT"][p]["rounds"]
               for kk, a in rr["arr"].items() if a["found"]}
        (OUT / "ref_arrivals.json").write_text(json.dumps(ref))
        (OUT / "ref_flights.json").write_text(json.dumps(
            {f"{r['sid']}|{p}|{rr['k']}": rr["flight_cm"] for r in results for p in PROBES
             for rr in r["v"]["fixT"][p]["rounds"] if rr["usable"]}))
    (OUT / f"rescore_{tag}.json").write_text(json.dumps(fa._clean(table), indent=1))
    print("runtime per session (s):", [round(r["runtime_s"]) for r in results])


if __name__ == "__main__":
    main()
