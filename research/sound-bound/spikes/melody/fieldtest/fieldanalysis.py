"""fieldtest session analysis.  CONTRACT.md section 4-6.

  python fieldanalysis.py <session_dir>     # prints a per-probe summary, exit 0 ok / 1 failed

Per (probe, listener) one segment of the recording is masked once in the
frequency domain; every template (real, partner, N_NULL live-null codes, each
at every ppm-bank entry) is one complex FFT correlation over that segment,
then every window is sliced out of it.  The "right code" bar T is fitted per
window from the live null (Gumbel on window maxima, exceed prob NULL_P).

Choices not pinned by the contract:
  - The segment gets the 0.1 s margin on both sides.
  - Onsets are integer samples (as analysis.py); no sub-sample interpolation.
  - "local maximum" = env[n] >= env[n-1] and env[n] > env[n+1] (analysis.py rule).
  - Review fixes (deviate from CONTRACT section 5 on purpose):
    * half-max reference is max env over [peak, peak + HALF_LOOKAHEAD_S], not the
      whole window; `half_rejected` counts earlier T-passing peaks it still rejected.
    * T = gumbel isf(NULL_P / NULL_P_SAFETY) (conservative for the 64-maxima fit).
    * N1s/JB flight is drift-corrected from the bank ppm; flight_raw_cm keeps the raw value.
  - null_T_median / null_median_median in summary are over every window of the
    probe (found or missed); right_pct_median over found arrivals.
  - v2 (probes N250/N500/N1s/JBQ/JBL/JBL250):
    * Two arrival pickers per window from the same correlation: the primary rule
      (FIELD_ARRIVAL_RULE, default "first") fills the classic fields (arrivals, flight_cm,
      summary, decision); every other rule in RULES ("ownwalk") goes to
      round[<rule>] = {arrivals, flight_cm, ..., usable, reasons} and
      probe["summary_<rule>"], probe["decision_<rule>"].
    * ppm bank on cross arrivals of every probe but N30.  N250's chosen ppm is recorded
      (arrival ppm, round drift_ppm/drift_cm) but its flight is NOT drift-corrected
      (DRIFT_CORRECT_PROBES): a 0.25 s code barely resolves 25 ppm.
    * Self-arrival code-gap guard: a flat run inside [t, t + code length] of a found self
      arrival adds "code_gap" to that arrival's flags and `self_code_gap_at_<L>` to the
      round reasons (the straddle rule already makes such rounds unusable).
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
import traceback
from pathlib import Path

import numpy as np
import scipy.fft as sfft
from scipy.stats import gumbel_r

HERE = Path(__file__).resolve().parent
SB_ROOT = HERE.parents[2]
for _p in (str(HERE), str(SB_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import fieldprobes as fp  # noqa: E402
import analysis as sb_analysis  # noqa: E402  read-only: _flat_runs, _quality

SPEED_OF_SOUND_CM_S = 34300.0   # dry air ~20 C
N_NULL = 64                     # live-null codes per window; Gumbel fit needs dozens, budget allows 64
NULL_P = 1e-4                   # per-window false-accept probability that sets T
HALF_FRAC = 0.5                 # arrival peak >= half the local max: direct path beats a later louder reflection
HALF_LOOKAHEAD_S = 0.005        # "local max" = env max over [peak, peak + 5 ms]; a diffuse-tail peak 19 ms
                                # later must not veto the direct (review: JB 200 cm locked 10.8 ms late)
NULL_P_SAFETY = 3.0             # T = isf(NULL_P / 3): Gumbel extrapolated from 64 maxima under-states the
                                # tail; held-out nulls showed 1.5-2x the nominal rate at isf(NULL_P)
DRIFT_CORRECT = True            # subtract c/2 * b_offset * drift_ppm (bank probes); N1s/JB gap 1.7 s
PPM_BANK = (0, 25, -25, 50, -50, 75, -75)  # phone clocks differ up to ~100 ppm; 1 s codes lose score beyond ~25 ppm
FLAT_RUN_MIN_S = 0.008          # an 8 ms constant run is a dropped block, not audio
NEAR_CM = 45.0                  # below: NEAR (target separates <=30 cm)
FAR_CM = 80.0                   # above: FAR (target >=100 cm)
MIN_USABLE = 2                  # rounds needed before any decision
SPREAD_MAX_CM = 40.0            # rounds disagreeing by more -> UNDECIDED
IMPOSSIBLE_CM = -20.0           # flight below this is physically impossible (self path ~12 cm)
SEGMENT_MARGIN_S = 0.1          # extra audio each side of the segment
BANK_PROBES = ("N250", "N500", "N1s", "JB", "JBQ", "JBL", "JBL250")   # ppm bank on cross arrivals
DRIFT_CORRECT_PROBES = ("N500", "N1s", "JB", "JBQ", "JBL")  # N250/JBL250: bank ppm recorded, not applied
FFT_WORKERS = -1                # scipy.fft threads: all cores
ARRIVAL_RULE = os.environ.get("FIELD_ARRIVAL_RULE", "first")
                                # "first": earliest T-passing local max that is >= HALF_FRAC x the
                                #   next HALF_LOOKAHEAD_S of env (CONTRACT section 5 + review fix).
                                # "walkback": strongest match, walk back while score >= T, earliest local
                                #   max of that connected region; only T sets a level.
                                # "ownwalk": walkback for self arrivals (E hears itself, speaker a few
                                #   cm from mic), first for cross arrivals.
assert ARRIVAL_RULE in ("first", "walkback", "ownwalk"), ARRIVAL_RULE
RULES = ("first", "ownwalk")    # every session is analysed under both; primary = ARRIVAL_RULE
ALT_RULES = tuple(r for r in RULES if r != ARRIVAL_RULE)
BATCH = 24                      # templates per batched FFT (memory ~ BATCH x nfft x 16 B)

assert abs(FLAT_RUN_MIN_S - sb_analysis.ZERO_RUN_MIN_S) < 1e-12


def _constants() -> dict:
    return {
        "version": fp.VERSION,
        "speed_of_sound_cm_s": SPEED_OF_SOUND_CM_S, "n_null": N_NULL, "null_p": NULL_P,
        "arrival_rule": ARRIVAL_RULE, "half_frac": HALF_FRAC, "half_lookahead_s": HALF_LOOKAHEAD_S,
        "null_p_safety": NULL_P_SAFETY, "drift_correct": DRIFT_CORRECT, "ppm_bank": list(PPM_BANK), "bank_probes": list(BANK_PROBES),
        "drift_correct_probes": list(DRIFT_CORRECT_PROBES), "alt_rules": list(ALT_RULES),
        "jb_family": {k: list(v) for k, v in fp.JB_FAMILY.items()},
        "jbl_partial_max_hz": fp.JBL_PARTIAL_MAX_HZ,
        "flat_run_min_s": FLAT_RUN_MIN_S, "near_cm": NEAR_CM, "far_cm": FAR_CM,
        "min_usable": MIN_USABLE, "spread_max_cm": SPREAD_MAX_CM, "impossible_cm": IMPOSSIBLE_CM,
        "segment_margin_s": SEGMENT_MARGIN_S, "target_rms": fp.TARGET_RMS,
        "band_hz": list(fp.BAND_HZ), "jb_bed_rel_db": fp.JB_BED_REL_DB, "jb_notch_hz": fp.JB_NOTCH_HZ,
        "clip_level": sb_analysis.CLIP_LEVEL,
    }


def _clean(v):
    """JSON-safe: numpy -> python, NaN/inf -> None."""
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        f = float(v)
        return f if math.isfinite(f) else None
    if isinstance(v, np.ndarray):
        return _clean(v.tolist())
    return v


def _read_wav(path: Path):
    import soundfile as sf
    x, sr = sf.read(str(path), dtype="float32", always_2d=True)
    return np.ascontiguousarray(x[:, 0].astype(np.float64)), int(sr)


def _stretch(c: np.ndarray, ppm: int) -> np.ndarray:
    """Band-limited resample of template c to round(len(c)*(1+ppm*1e-6)) samples."""
    if ppm == 0:
        return c
    n0 = len(c)
    n = int(round(n0 * (1 + ppm * 1e-6)))
    if n == n0:
        return c
    S = np.fft.rfft(c)
    m = n // 2 + 1
    S2 = np.zeros(m, dtype=S.dtype)
    k = min(m, len(S))
    S2[:k] = S[:k]
    return np.fft.irfft(S2, n) * (n / n0)


class _Seg:
    """One masked recording segment of listener L for probe p."""

    def __init__(self, x, a, b, probe, sr, nfft, mask):
        self.a = a
        self.n = b - a
        self.nfft = nfft
        X = sfft.rfft(x[a:b], nfft, workers=FFT_WORKERS) * mask
        xm = sfft.irfft(X, nfft, workers=FFT_WORKERS)[: self.n]
        self.X2 = (2.0 * X).astype(np.complex64)   # one-sided (analytic) factor folded in
        self.cs = np.concatenate([[0.0], np.cumsum(xm * xm)])
        self._nx = {}

    def nx(self, w0, w1, L):
        """||masked x[n:n+L]|| for onsets n in [w0, w1) (segment-relative)."""
        key = (w0, w1, L)
        if key not in self._nx:
            n = np.arange(w0, w1)
            end = np.minimum(n + L, self.n)
            self._nx[key] = np.sqrt(np.maximum(self.cs[end] - self.cs[n], 0.0))
        return self._nx[key]


def _gumbel_T(maxima):
    s = np.asarray(maxima, dtype=np.float64)
    try:
        loc, scale = gumbel_r.fit(s)
        T = float(gumbel_r.isf(NULL_P / NULL_P_SAFETY, loc, scale))
        if not math.isfinite(T):
            raise ValueError("non-finite T")
        return max(T, float(s.max())), "gumbel"
    except Exception:
        return float(s.max()), "max_fallback"


def _first_arrival(env, sc, T, look):
    """Earliest local max with score >= T and env >= HALF_FRAC x max(env[i : i + look]).

    Returns (index or None, number of earlier T-passing peaks rejected by the half-max rule).
    The reference is local (look samples ahead), not the whole 400 ms window, so a
    louder diffuse-tail peak 10-20 ms later cannot veto the direct sound.
    """
    w = env
    if len(w) < 3:
        return None, 0
    inner = w[1:-1]
    cand = np.nonzero((inner >= w[:-2]) & (inner > w[2:]) & (sc[1:-1] >= T))[0] + 1
    rejected = 0
    for i in cand:
        ref = float(np.max(w[i : i + look + 1]))
        if w[i] >= HALF_FRAC * ref:
            return int(i), rejected
        rejected += 1
    return None, rejected


def _local_max(env):
    """Indices n (1 <= n < len-1) with env[n] >= env[n-1] and env[n] > env[n+1]."""
    inner = env[1:-1]
    return np.nonzero((inner >= env[:-2]) & (inner > env[2:]))[0] + 1


def _above_regions_before(sc, T, i):
    """Number of separate runs of score >= T that end before index i (i.e. not connected to i)."""
    a = sc[:i] >= T
    if not a.any():
        return 0
    # a run ends at n where a[n] and (n == i-1 -> connected, skip) or not a[n+1]
    starts = np.count_nonzero(a[1:] & ~a[:-1]) + int(a[0])
    return int(starts) - int(a[-1] and sc[i] >= T)


def _walkback_arrival(env, sc, T):
    """Walk back from the strongest match.

    s = argmax score (the real sound or its strongest echo).  Walk back from s while
    score stays >= T; the run [r, s] is the region connected to the strongest match.
    Arrival = earliest local max of env inside [r, s] (a direct path weaker than the
    strongest echo stays, as long as the score never drops below T in between).
    Earlier above-T runs are cut off from the peak by a stretch below T: ignored.
    Returns (index or None, strongest index or None).
    """
    if len(sc) < 3:
        return None, None
    s = int(np.argmax(sc))
    if sc[s] < T:
        return None, s
    below = np.nonzero(sc[: s + 1] < T)[0]
    r = int(below[-1]) + 1 if len(below) else 0
    lm = _local_max(env)
    lm = lm[(lm >= r) & (lm <= s)]
    return (int(lm[0]) if len(lm) else s), s


def _probe_all(p, rec, seed, windows):
    """Every arrival of probe p in both recordings.

    windows: {(E, L, k): (lo, hi, expected_s) sample span in L's recording, or None}
    returns {(E, L, k): record dict or None}

    Listeners with the same sample rate share one nfft, so each template's
    masked spectrum is computed once and used for both recordings.  Templates
    go through the FFTs in batches (threads parallelize over the batch).
    """
    out = {key: None for key, w in windows.items() if w is None}
    groups = {}
    for L in fp.ROLES:
        groups.setdefault(rec[L]["sr"], []).append(L)
    for sr, Ls in groups.items():
        tl = {E: fp.template(seed, p, E, sr) for E in fp.ROLES}
        lmax = int(math.ceil(max(len(t) for t in tl.values()) * (1 + max(PPM_BANK) * 1e-6))) + 2
        m = int(round(SEGMENT_MARGIN_S * sr))
        span = {}
        for L in Ls:
            valid = [w for (E, LL, k), w in windows.items() if LL == L and w is not None]
            if valid:
                x = rec[L]["x"]
                span[L] = (max(0, min(w[0] for w in valid) - m),
                           min(len(x), max(w[1] for w in valid) + lmax + m))
        if not span:
            continue
        nfft = sfft.next_fast_len(max(b - a for a, b in span.values()) + lmax, real=False)
        mask = fp.rx_mask(p, nfft, sr)
        maskf = mask.astype(np.float32)
        segs = {L: _Seg(rec[L]["x"], a, b, p, sr, nfft, mask) for L, (a, b) in span.items()}
        half = nfft // 2 + 1

        for E in fp.ROLES:
            # per listener: windows of E (segment-relative) and its bank
            lw = {}
            for L in segs:
                keys = [(E, L, k) for (EE, LL, k), w in windows.items()
                        if EE == E and LL == L and w is not None]
                if keys:
                    a = segs[L].a
                    lw[L] = {"keys": keys,
                             "wins": [(windows[kk][0] - a, windows[kk][1] - a) for kk in keys],
                             "bank": PPM_BANK if (E != L and p in BANK_PROBES) else (0,)}
            if not lw:
                continue
            need_e = sorted({e for d in lw.values() for e in d["bank"]}, key=PPM_BANK.index)
            other = "B" if E == "A" else "A"
            # code list: ("real", c), ("partner", c), ("null", i)
            codes = [("real", 0), ("partner", 0)] + [("null", i) for i in range(N_NULL)]
            # rows: (code_idx, e); partner only at e = 0
            rows = [(ci, e) for ci, (kind, _) in enumerate(codes)
                    for e in (need_e if kind != "partner" else (0,))]
            # results
            real_env = {L: {} for L in lw}   # L -> e -> list over windows of (env, score)
            wmax = {L: np.zeros((len(codes), len(PPM_BANK), len(lw[L]["wins"]))) - 1.0 for L in lw}
            cache_c = {}

            def code_wave(ci):
                if ci not in cache_c:
                    kind, i = codes[ci]
                    cache_c.clear()
                    cache_c[ci] = (tl[E] if kind == "real" else tl[other] if kind == "partner"
                                   else fp.null_template(seed, p, E, sr, i))
                return cache_c[ci]

            B = BATCH
            for r0 in range(0, len(rows), B):
                chunk = rows[r0 : r0 + B]
                buf = np.zeros((len(chunk), nfft), dtype=np.float32)
                lens = []
                for j, (ci, e) in enumerate(chunk):
                    c = _stretch(code_wave(ci), e)
                    buf[j, : len(c)] = c
                    lens.append(len(c))
                C = sfft.rfft(buf, axis=-1, workers=FFT_WORKERS)
                del buf
                C *= maskf
                p2 = np.abs(C) ** 2
                cn = np.sqrt((p2[:, 0] + 2 * p2[:, 1:].sum(axis=1)
                              - (p2[:, -1] if nfft % 2 == 0 else 0.0)) / nfft)
                del p2
                np.conjugate(C, out=C)
                for L, d in lw.items():
                    sel = [j for j, (ci, e) in enumerate(chunk) if e in d["bank"]]
                    if not sel:
                        continue
                    Z = np.zeros((len(sel), nfft), dtype=np.complex64)
                    Z[:, :half] = C[sel] * segs[L].X2
                    corr = sfft.ifft(Z, axis=-1, workers=FFT_WORKERS, overwrite_x=True)
                    for zj, j in enumerate(sel):
                        ci, e = chunk[j]
                        ei = PPM_BANK.index(e)
                        for wi, (w0, w1) in enumerate(d["wins"]):
                            env = np.abs(corr[zj, w0:w1]).astype(np.float64)
                            sc = env / (segs[L].nx(w0, w1, lens[j]) * cn[j] + 1e-30)
                            wmax[L][ci, ei, wi] = float(np.max(sc))
                            if codes[ci][0] == "real":
                                real_env[L].setdefault(e, [None] * len(d["wins"]))[wi] = (env, sc)
                    del Z, corr

            for L, d in lw.items():
                a = segs[L].a
                bank_idx = [PPM_BANK.index(e) for e in d["bank"]]
                for wi, key in enumerate(d["keys"]):
                    rm = wmax[L][0, bank_idx, wi]
                    e = d["bank"][int(np.argmax(rm))]
                    env, sc = real_env[L][e][wi]
                    mx = float(np.max(rm))
                    nmax = wmax[L][2:, :, wi][:, bank_idx].max(axis=1)
                    pmx = float(wmax[L][1, PPM_BANK.index(0), wi])
                    T, tmode = _gumbel_T(nmax)
                    w0, w1 = d["wins"][wi]
                    base = {
                        "expected": windows[key][2],
                        "right_max_pct": 100 * mx, "T": 100 * T,
                        "null_median": 100 * float(np.median(nmax)),
                        "null_max": 100 * float(np.max(nmax)), "T_fit": tmode,
                        "window": [(w0 + a) / sr, (w1 + a) / sr], "ppm": int(e),
                        "partner_pct": 100 * pmx,
                        "window_max_margin_db": 20 * math.log10(max(mx, 1e-12) / T),
                    }
                    s_i = int(np.argmax(sc))
                    base["strongest_t"] = (w0 + a + s_i) / sr
                    base["strongest_pct"] = 100 * float(sc[s_i])
                    picks = {}
                    for rule_name in (ARRIVAL_RULE,) + ALT_RULES:
                        rule = rule_name
                        if rule == "ownwalk":
                            rule = "walkback" if key[0] == key[1] else "first"
                        if rule == "walkback":
                            i, _ = _walkback_arrival(env, sc, T)
                            nrej = None
                        else:
                            i, nrej = _first_arrival(env, sc, T, int(round(HALF_LOOKAHEAD_S * sr)))
                        pk = {"half_rejected": nrej, "arrival_rule": rule}
                        if i is None:
                            why = f"below_null_{E}_at_{L}" if mx < T else f"no_arrival_{E}_at_{L}"
                            pk.update({"found": False, "why": why})
                        else:
                            r = float(sc[i])
                            pk.update({"found": True, "t": (w0 + a + i) / sr, "right_pct": 100 * r,
                                       "margin_db": 20 * math.log10(max(r, 1e-12) / T),
                                       "gap_to_strongest_ms": 1000 * (s_i - i) / sr,
                                       "blips_before": _above_regions_before(sc, T, i)})
                        picks[rule_name] = pk
                    out[key] = {"base": base, "picks": picks}
    return out


def _fail(reasons, session=None, t0=None):
    session = session or {}
    return {"status": "failed", "version": fp.VERSION, "session_id": session.get("session_id"),
            "labels": session.get("labels"), "reasons": list(reasons), "quality": {},
            "probes": {}, "constants": _constants(),
            "runtime_s": (time.time() - t0) if t0 else None}


def _write(session_dir: Path, res: dict) -> dict:
    res = _clean(res)
    try:
        tmp = session_dir / "result.json.tmp"
        tmp.write_text(json.dumps(res, indent=1))
        tmp.replace(session_dir / "result.json")
    except Exception as exc:  # pragma: no cover
        res.setdefault("reasons", []).append(f"could_not_write_result: {exc}")
    return res


def analyze_session(session_dir) -> dict:
    session_dir = Path(session_dir)
    t0 = time.time()
    try:
        res = _analyze(session_dir, t0)
    except Exception as exc:
        res = _fail([f"exception: {type(exc).__name__}: {exc}", traceback.format_exc(limit=4)], t0=t0)
    res["runtime_s"] = time.time() - t0
    return _write(session_dir, res)


def _decide(fl):
    if len(fl) < MIN_USABLE:
        return "UNDECIDED", f"{len(fl)} usable rounds < {MIN_USABLE}"
    med = float(np.median(fl))
    spread = float(np.max(fl) - np.min(fl))
    if spread > SPREAD_MAX_CM:
        return "UNDECIDED", f"round spread {spread:.0f} cm > {SPREAD_MAX_CM:.0f} cm"
    if med < NEAR_CM:
        return "NEAR", f"flight median {med:.1f} cm < {NEAR_CM:.0f}"
    if med > FAR_CM:
        return "FAR", f"flight median {med:.1f} cm > {FAR_CM:.0f}"
    return "UNDECIDED", f"flight median {med:.1f} cm between {NEAR_CM:.0f} and {FAR_CM:.0f}"


def _build_round(k, rule, ctx, compact):
    """Round k of ctx["p"] with arrivals picked by `rule` (primary: full records, alt: compact)."""
    p, arr, wins_s, rec, sched = ctx["p"], ctx["arr"], ctx["wins_s"], ctx["rec"], ctx["sched"]
    rr = {"k": k, "flight_cm": None, "flight_raw_cm": None, "drift_ppm": None, "drift_cm": None,
          "delta_ms": None, "usable": True, "reasons": [], "arrivals": {}, "misses": {}}
    t, ppm = {}, {}
    for E in fp.ROLES:
        for L in fp.ROLES:
            key = f"{E}_at_{L}"
            v = arr[(E, L, k)]
            if v is None:
                rr["arrivals"][key] = None
                lo_s, hi_s, exp = wins_s[(E, L, k)]
                rr["misses"][key] = ({"why": "window_outside_recording"} if compact else
                                     {"window": [lo_s, hi_s], "expected": exp, "why": "window_outside_recording"})
                rr["reasons"].append(f"window_outside_recording_{key}")
                continue
            base, pk = v["base"], v["picks"][rule]
            ppm[key] = base["ppm"]
            if not pk["found"]:
                rr["arrivals"][key] = None
                rr["misses"][key] = ({"why": pk["why"], "arrival_rule": pk["arrival_rule"]} if compact else
                                     {**base, **{kk: vv for kk, vv in pk.items() if kk != "found"}})
                rr["reasons"].append(pk["why"])
                continue
            rec_a = ({kk: pk.get(kk) for kk in ("t", "right_pct", "margin_db", "arrival_rule",
                                                 "gap_to_strongest_ms", "half_rejected")}
                     if compact else {**base, **{kk: vv for kk, vv in pk.items() if kk != "found"}})
            if E == L:   # self-arrival code-gap guard
                sr = rec[L]["sr"]
                c0, c1 = pk["t"], pk["t"] + ctx["clen"][(E, L)]
                if any(s0 / sr < c1 and c0 < s1 / sr for s0, s1 in rec[L]["quality"]["flat_run_spans"]):
                    rec_a["flags"] = ["code_gap"]
                    rr["reasons"].append(f"self_code_gap_at_{L}")
            rr["arrivals"][key] = rec_a
            t[key] = pk["t"]
    if len(t) == 4:
        delta = (t["B_at_A"] - t["A_at_A"]) - (t["B_at_B"] - t["A_at_B"])
        rr["delta_ms"] = 1000 * delta
        rr["flight_raw_cm"] = rr["flight_cm"] = SPEED_OF_SOUND_CM_S * delta / 2
        if p in BANK_PROBES:
            # bank ppm of B_at_A ~ ppm_A - ppm_B, of A_at_B ~ ppm_B - ppm_A.  The A->B gap
            # b_offset_s is timed by A's clock in one term and B's in the other, so the
            # flight carries c/2 * b_offset * (ppm_A - ppm_B).
            d_ppm = (ppm["B_at_A"] - ppm["A_at_B"]) / 2
            rr["drift_ppm"] = d_ppm
            rr["drift_cm"] = (SPEED_OF_SOUND_CM_S / 2 * float(sched["probes"][p]["b_offset_s"])
                              * d_ppm * 1e-6)
            if DRIFT_CORRECT and p in DRIFT_CORRECT_PROBES:
                rr["flight_cm"] -= rr["drift_cm"]
    for L in fp.ROLES:
        sr = rec[L]["sr"]
        spans = rec[L]["quality"]["flat_run_spans"]
        lo = min(wins_s[(E, L, k)][0] for E in fp.ROLES)
        hi = max(wins_s[(E, L, k)][1] for E in fp.ROLES) + ctx["tlen"][L]
        if any(s0 / sr < hi and lo < s1 / sr for s0, s1 in spans):
            rr["reasons"].append(f"timeline_gap_at_{L}")
    if rr["flight_cm"] is not None and rr["flight_cm"] < IMPOSSIBLE_CM:
        rr["reasons"].append("impossible_flight")
    rr["usable"] = rr["flight_cm"] is not None and not rr["reasons"]
    return rr


def _summarize(rounds_list, total):
    """(summary dict, decision label, rule text) over a list of round dicts of one rule."""
    good = [r for r in rounds_list if r["usable"]]
    fl = [r["flight_cm"] for r in good]
    allw = [a for r in rounds_list for a in list(r["arrivals"].values()) + list(r["misses"].values())
            if a and a.get("T") is not None]
    margins = [a["margin_db"] for r in good for a in r["arrivals"].values()]
    rights = [a["right_pct"] for r in rounds_list for a in r["arrivals"].values() if a]
    label, rule = _decide(fl)
    summary = {
        "flight_median": float(np.median(fl)) if fl else None,
        "spread": float(np.max(fl) - np.min(fl)) if fl else None,
        "usable_rounds": len(good), "total_rounds": total,
        "min_margin_db": float(min(margins)) if margins else None,
        "right_pct_median": float(np.median(rights)) if rights else None,
    }
    if allw:   # full records only (primary rule); T is rule-independent anyway
        summary["null_T_median"] = float(np.median([a["T"] for a in allw]))
        summary["null_median_median"] = float(np.median([a["null_median"] for a in allw]))
    else:
        summary["null_T_median"] = summary["null_median_median"] = None
    return summary, label, rule


def _analyze(session_dir: Path, t0: float) -> dict:
    try:
        session = json.loads((session_dir / "session.json").read_text())
    except Exception as exc:
        return _fail([f"session.json unreadable: {exc}"], t0=t0)
    seed = session.get("seed_hex")
    sched = session.get("schedule") or {}
    if not seed or "probes" not in sched:
        return _fail(["session.json missing seed_hex or schedule"], session, t0)
    pre = float(sched.get("search_pre_s", fp.SCHEDULE["search_pre_s"]))
    post = float(sched.get("search_post_s", fp.SCHEDULE["search_post_s"]))
    reasons = []

    rec = {}
    for L in fp.ROLES:
        try:
            meta = json.loads((session_dir / f"meta_{L}.json").read_text())
            x, sr = _read_wav(session_dir / f"recording_{L}.wav")
        except Exception as exc:
            return _fail([f"{L}: meta/recording unreadable: {exc}"], session, t0)
        if not fp.SR_MIN <= sr <= fp.SR_MAX:
            return _fail([f"{L}: sample rate {sr} unsupported"], session, t0)
        if int(meta.get("sample_rate") or sr) != sr:
            reasons.append(f"{L}: meta sample_rate {meta.get('sample_rate')} != wav {sr}; using wav")
        q = sb_analysis._quality(x, sr, meta)
        rec[L] = {"x": x, "sr": sr, "meta": meta, "quality": q}

    probes_out = {}
    order = [q for q in (sched.get("order") or list(sched["probes"])) if q in sched["probes"]]
    for p in order:
        if p not in fp.PROBES:
            reasons.append(f"unknown probe {p} in schedule; skipped")
            continue
        rounds = int(sched["probes"][p]["rounds"])
        windows = {}      # (E, L, k) -> (lo, hi, expected) clipped samples, or None
        wins_s = {}       # (E, L, k) -> (lo_s, hi_s, expected) unclipped, seconds
        for L in fp.ROLES:
            meta, sr, x = rec[L]["meta"], rec[L]["sr"], rec[L]["x"]
            cap = float(meta["capture_start_ctx_s"])
            start = float(meta["start_ctx_s"])
            own = {(d.get("probe"), int(d.get("k"))): float(d["ctx_s"]) for d in meta.get("plays") or []}
            for E in fp.ROLES:
                for k in range(rounds):
                    if E == L:
                        ctx = own.get((p, k))
                        if ctx is None:
                            reasons.append(f"{L}: no play record for {p} k={k}; using schedule")
                            ctx = start + fp.offset_s(sched, p, E, k)
                        exp = ctx - cap
                    else:
                        exp = start + fp.offset_s(sched, p, E, k) - cap
                    lo = int(round((exp - pre) * sr))
                    hi = int(round((exp + post) * sr))
                    wins_s[(E, L, k)] = (exp - pre, exp + post, exp)
                    clo, chi = max(lo, 0), min(hi, len(x))
                    windows[(E, L, k)] = (clo, chi, exp) if chi - clo >= 3 else None
        arr = _probe_all(p, rec, seed, windows)

        tlen = {L: max(len(fp.template(seed, p, E, rec[L]["sr"])) for E in fp.ROLES) / rec[L]["sr"]
                for L in fp.ROLES}
        clen = {(E, L): len(fp.template(seed, p, E, rec[L]["sr"])) / rec[L]["sr"]
                for E in fp.ROLES for L in fp.ROLES}
        ctx = {"p": p, "arr": arr, "wins_s": wins_s, "rec": rec, "sched": sched,
               "tlen": tlen, "clen": clen}
        out_rounds = []
        for k in range(rounds):
            rr = _build_round(k, ARRIVAL_RULE, ctx, compact=False)
            for rule in ALT_RULES:
                alt = _build_round(k, rule, ctx, compact=True)
                alt.pop("k", None)
                rr[rule] = alt
            out_rounds.append(rr)

        summary, label, rule_txt = _summarize(out_rounds, rounds)
        probes_out[p] = {"rounds": out_rounds, "summary": summary,
                         "decision": {"label": label, "rule": rule_txt, "provisional": True,
                                      "arrival_rule": ARRIVAL_RULE}}
        for rule in ALT_RULES:
            s_alt, l_alt, r_alt = _summarize([r[rule] for r in out_rounds], rounds)
            probes_out[p][f"summary_{rule}"] = s_alt
            probes_out[p][f"decision_{rule}"] = {"label": l_alt, "rule": r_alt, "provisional": True,
                                                 "arrival_rule": rule}

    quality = {L: {k: v for k, v in rec[L]["quality"].items() if k != "flat_run_spans"} for L in fp.ROLES}
    return {"status": "ok", "version": fp.VERSION, "session_id": session.get("session_id"),
            "labels": session.get("labels"), "reasons": reasons, "quality": quality,
            "probes": probes_out, "constants": _constants()}


def _f(v, spec=".1f"):
    return "-" if v is None else format(v, spec)


def print_result(res: dict) -> None:
    print(f"status {res['status']}  session {res.get('session_id')}  labels {res.get('labels')}  "
          f"runtime {_f(res.get('runtime_s'))} s")
    for r in res.get("reasons") or []:
        print("  reason:", r.splitlines()[0] if isinstance(r, str) else r)
    for p, d in (res.get("probes") or {}).items():
        s, dec = d["summary"], d["decision"]
        print(f"{p:4s} {dec['label']:9s} flight {_f(s['flight_median'])} cm spread {_f(s['spread'])} "
              f"usable {s['usable_rounds']}/{s['total_rounds']} right {_f(s['right_pct_median'])}% "
              f"T {_f(s['null_T_median'])}% null {_f(s['null_median_median'])}% "
              f"min margin {_f(s['min_margin_db'])} dB  ({dec['rule']})")
        for rule in ALT_RULES:
            da, sa = d.get(f"decision_{rule}"), d.get(f"summary_{rule}")
            if da:
                print(f"     {rule:8s} {da['label']:9s} flight {_f(sa['flight_median'])} spread {_f(sa['spread'])} "
                      f"usable {sa['usable_rounds']}/{sa['total_rounds']} min margin {_f(sa['min_margin_db'])} dB")
        for r in d["rounds"]:
            parts = []
            for key in ("A_at_A", "B_at_A", "B_at_B", "A_at_B"):
                a = r["arrivals"].get(key) or r["misses"].get(key) or {}
                parts.append(f"{key} {_f(a.get('right_pct', a.get('right_max_pct')))}/{_f(a.get('T'))}"
                             + ("" if r["arrivals"].get(key) else "!"))
            alt = "".join(f" {rl}:{_f((r.get(rl) or {}).get('flight_cm'))}" for rl in ALT_RULES)
            print(f"   k={r['k']} flight {_f(r['flight_cm']):>6}{alt} ppm {r.get('drift_ppm')} usable {str(r['usable']):5s} "
                  + "  ".join(parts) + ("  " + ",".join(r["reasons"]) if r["reasons"] else ""))
    for L, q in (res.get("quality") or {}).items():
        print(f"  {L}: {q.get('sample_rate')} Hz flat_runs {len(q.get('flat_runs') or [])} "
              f"clipped {q.get('clipped_samples')} flags {q.get('flags')}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python fieldanalysis.py <session_dir>")
        sys.exit(2)
    out = analyze_session(sys.argv[1])
    print_result(out)
    sys.exit(0 if out["status"] == "ok" else 1)
