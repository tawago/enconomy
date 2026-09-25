"""sound-bound session analysis.

Reads a session directory, finds the four arrivals per round (each device
hearing itself and hearing its partner), turns them into a flight-time
distance, and reports DRR, code cross-fire and capture quality alongside a
PROVISIONAL near/far call.

Never raises on bad input: returns {"status": "failed", "reasons": [...]}.
"""

from __future__ import annotations

import json
import math
import pathlib
import sys
import traceback

import numpy as np

import probes

VERSION = "sound-bound-v1"

# ---------------------------------------------------------------------------
# Constants.  Every threshold the analysis uses lives here, with its reason.
# ---------------------------------------------------------------------------
SPEED_OF_SOUND_CM_S = 34300.0   # cm/s, dry air ~20 C; the only physics constant
SEARCH_PRE_S = 0.150            # s; before expected. A cross path arrives early when
                                # the emitter's stack latency is below the listener's
SEARCH_POST_S = 0.250           # s; after expected. Real runs land 74-138 ms late,
                                # plus a 20 ms Android timeline slip, plus headroom
QUALIFY_FRAC_OF_MAX = 0.5       # peak must be >= half the window max, so a direct
                                # path is kept over a louder late reflection
QUALIFY_FRAC_TOL = 0.999        # tiny slack so an exactly-half peak still qualifies
QUALIFY_MAD_MULT = 10.0         # peak must be >= 10x robust noise level (MAD based)
MAD_TO_SIGMA = 1.4826           # MAD -> Gaussian sigma, so the 10x is in sigmas
DRR_DIRECT_PRE_S = 0.0001       # s; 0.1 ms before the arrival, catches envelope rise
DRR_DIRECT_POST_S = 0.0010      # s; 1.0 ms after -- direct path plus probe mainlobe
DRR_REVERB_START_S = 0.0020     # s; 2 ms after arrival, past the direct lobe
DRR_REVERB_END_S = 0.1000       # s; 100 ms of tail, ~RT60 of a small room
ZERO_RUN_MIN_S = 0.008          # s; an 8 ms flat run is a dropped block, not audio
CONST_RUN_EPS = 1e-9            # amplitude tolerance for "constant" sample runs
CLIP_LEVEL = 0.99               # |x| above this is treated as clipped
CROSSFIRE_MIN_DB = 6.0          # dB; correct code must beat wrong code by this much
                                # in its own window, else the arrival is not trusted
NEAR_CM = 45.0                  # cm; below this we call NEAR (target: separate <=30 cm)
FAR_CM = 80.0                   # cm; above this we call FAR (target: >=1 m)
MIN_USABLE_ROUNDS = 2           # rounds needed before any decision is made
SPREAD_MAX_CM = 40.0            # cm; if rounds disagree by more than this, UNDECIDED


def _mad_threshold(env: np.ndarray) -> float:
    med = float(np.median(env))
    mad = float(np.median(np.abs(env - med)))
    return med + QUALIFY_MAD_MULT * MAD_TO_SIGMA * mad


def _matched_envelope(x: np.ndarray, probe: np.ndarray) -> np.ndarray:
    """Envelope of the matched-filter output, indexed by probe ONSET sample."""
    from scipy.signal import fftconvolve, hilbert

    corr = fftconvolve(x, probe[::-1], mode="full")
    # full-mode lag 0 (probe starting at sample 0) sits at index len(probe)-1
    corr = corr[len(probe) - 1 :]
    return np.abs(hilbert(corr))


def _window(expected_s: float, sr: int):
    """Unclipped sample span [lo, hi) searched around expected_s."""
    return (int(round((expected_s - SEARCH_PRE_S) * sr)),
            int(round((expected_s + SEARCH_POST_S) * sr)))


def _find_arrival(env: np.ndarray, sr: int, expected_s: float):
    """FIRST QUALIFIED PEAK inside [-SEARCH_PRE_S, +SEARCH_POST_S] of expected_s."""
    lo, hi = _window(expected_s, sr)
    lo = max(lo, 0)
    hi = min(hi, len(env))
    if hi - lo < 8:
        return None
    w = env[lo:hi]
    wmax = float(np.max(w))
    if not np.isfinite(wmax) or wmax <= 0:
        return None
    thresh = max(QUALIFY_FRAC_OF_MAX * QUALIFY_FRAC_TOL * wmax, _mad_threshold(env))
    # local maxima inside the window
    inner = w[1:-1]
    is_peak = (inner >= w[:-2]) & (inner > w[2:]) & (inner >= thresh)
    idx = np.nonzero(is_peak)[0]
    if idx.size == 0:
        return None
    first = int(idx[0]) + 1
    strongest = int(np.argmax(w))
    return {
        "t_s": (lo + first) / sr,
        "amp": float(w[first]),
        "t_strongest_s": (lo + strongest) / sr,
        "amp_strongest": wmax,
        "gap_ms": (strongest - first) * 1000.0 / sr,
        "index": lo + first,
        "window": (lo, hi),
        "window_max": wmax,
    }


def _drr_db(env: np.ndarray, sr: int, t_s: float):
    e2 = env.astype(np.float64) ** 2
    i = int(round(t_s * sr))
    d0 = max(0, i - int(round(DRR_DIRECT_PRE_S * sr)))
    d1 = min(len(e2), i + int(round(DRR_DIRECT_POST_S * sr)) + 1)
    r0 = min(len(e2), i + int(round(DRR_REVERB_START_S * sr)))
    r1 = min(len(e2), i + int(round(DRR_REVERB_END_S * sr)))
    if d1 <= d0 or r1 <= r0:
        return None
    direct = float(np.sum(e2[d0:d1]))
    reverb = float(np.sum(e2[r0:r1]))
    if direct <= 0 or reverb <= 0:
        return None
    return 10.0 * math.log10(direct / reverb)


def _flat_runs(x: np.ndarray, sr: int):
    """Spans (start, end) of exact-zero or constant runs >= ZERO_RUN_MIN_S."""
    min_n = int(round(ZERO_RUN_MIN_S * sr))
    if len(x) < min_n or min_n < 2:
        return []
    same = np.abs(np.diff(x)) <= CONST_RUN_EPS
    runs = []
    i = 0
    n = len(same)
    while i < n:
        if not same[i]:
            i += 1
            continue
        j = i
        while j < n and same[j]:
            j += 1
        if (j - i + 1) >= min_n:
            runs.append((i, j + 1))
        i = j
    return runs


def _quality(x: np.ndarray, sr: int, meta: dict) -> dict:
    runs = _flat_runs(x, sr)
    ts = (meta or {}).get("track_settings") or {}
    blocks = (meta or {}).get("blocks") or {}
    flags = []
    if runs:
        flags.append("timeline_gap")
    if ts.get("echoCancellation"):
        flags.append("self_arrival_may_be_suppressed")
    if ts.get("autoGainControl"):
        flags.append("agc_on")
    if ts.get("noiseSuppression"):
        flags.append("noise_suppression_on")
    if (blocks.get("discontinuities") or 0) > 0:
        flags.append("worklet_discontinuities")
    if (blocks.get("missing_frames") or 0) > 0:
        flags.append("worklet_missing_frames")
    clip = int(np.count_nonzero(np.abs(x) > CLIP_LEVEL))
    if clip > 0:
        flags.append("clipping")
    return {
        "sample_rate": sr,
        "duration_s": len(x) / sr,
        "flat_runs": [
            {"start_s": a / sr, "end_s": b / sr, "ms": (b - a) * 1000.0 / sr}
            for a, b in runs
        ],
        "flat_run_spans": runs,
        "clipped_samples": clip,
        "worklet_discontinuities": blocks.get("discontinuities"),
        "worklet_missing_frames": blocks.get("missing_frames"),
        "track_settings": ts,
        "flags": flags,
    }


def _fail(reasons):
    return {"status": "failed", "reasons": list(reasons), "version": VERSION,
            "rounds": [], "summary": {}, "quality": {}, "decision": {
                "label": "UNDECIDED", "provisional": True, "rule": "analysis failed"},
            "constants": _constants()}


def _constants() -> dict:
    return {
        "speed_of_sound_cm_per_s": SPEED_OF_SOUND_CM_S,
        "search_window_s": [-SEARCH_PRE_S, SEARCH_POST_S],
        "qualify_frac_of_window_max": QUALIFY_FRAC_OF_MAX,
        "qualify_mad_multiple": QUALIFY_MAD_MULT,
        "drr_direct_window_s": [-DRR_DIRECT_PRE_S, DRR_DIRECT_POST_S],
        "drr_reverb_window_s": [DRR_REVERB_START_S, DRR_REVERB_END_S],
        "flat_run_min_s": ZERO_RUN_MIN_S,
        "clip_level": CLIP_LEVEL,
        "crossfire_min_db": CROSSFIRE_MIN_DB,
        "near_cm": NEAR_CM,
        "far_cm": FAR_CM,
        "min_usable_rounds": MIN_USABLE_ROUNDS,
        "spread_max_cm": SPREAD_MAX_CM,
        "probe_duration_s": probes.PROBE_DURATION_S,
        "probe_band_hz": list(probes.BAND_HZ),
    }


def _read_wav(path: pathlib.Path):
    import soundfile as sf

    x, sr = sf.read(str(path), dtype="float32", always_2d=True)
    return np.ascontiguousarray(x[:, 0].astype(np.float64)), int(sr)


def analyze_session(session_dir) -> dict:
    session_dir = pathlib.Path(session_dir)
    try:
        return _analyze(session_dir)
    except Exception as exc:  # never raise
        return _fail([f"exception: {type(exc).__name__}: {exc}",
                      traceback.format_exc(limit=3)])


def _analyze(session_dir: pathlib.Path) -> dict:
    reasons = []
    try:
        session = json.loads((session_dir / "session.json").read_text())
    except Exception as exc:
        return _fail([f"session.json unreadable: {exc}"])

    seed = session.get("seed_hex")
    sched = session.get("schedule") or {}
    period = float(sched.get("period_s", 1.0))
    b_offset = float(sched.get("b_offset_s", 0.5))
    rounds = int(sched.get("rounds", 4))
    if not seed or rounds <= 0:
        return _fail(["session.json missing seed_hex or rounds"])

    rec = {}
    for role in ("A", "B"):
        try:
            meta = json.loads((session_dir / f"meta_{role}.json").read_text())
        except Exception as exc:
            return _fail([f"meta_{role}.json unreadable: {exc}"])
        try:
            x, sr = _read_wav(session_dir / f"recording_{role}.wav")
        except Exception as exc:
            return _fail([f"recording_{role}.wav unreadable: {exc}"])
        if len(x) < sr * 0.2:
            return _fail([f"recording_{role}.wav too short ({len(x)} samples)"])
        meta_sr = int(meta.get("sample_rate") or sr)
        if meta_sr != sr:
            reasons.append(f"{role}: meta sample_rate {meta_sr} != wav {sr}; using wav")
        try:
            pa = probes.generate(seed, "A", sr).astype(np.float64)
            pb = probes.generate(seed, "B", sr).astype(np.float64)
        except Exception as exc:
            return _fail([f"probe generation failed at {sr} Hz: {exc}"])
        rec[role] = {
            "x": x, "sr": sr, "meta": meta,
            "env": {"A": _matched_envelope(x, pa), "B": _matched_envelope(x, pb)},
            "quality": _quality(x, sr, meta),
        }

    # expected slot times, in each recording's own timeline
    expected = {}
    for role in ("A", "B"):
        meta = rec[role]["meta"]
        try:
            cap = float(meta["capture_start_ctx_s"])
            start_ctx = float(meta["start_ctx_s"])
            own_plays = [float(v) for v in meta["scheduled_plays_ctx_s"]]
        except Exception as exc:
            return _fail([f"meta_{role}.json missing timing fields: {exc}"])
        if len(own_plays) < rounds:
            return _fail([f"meta_{role}.json has {len(own_plays)} plays, need {rounds}"])
        partner = "B" if role == "A" else "A"
        p_off = b_offset if partner == "B" else 0.0
        expected[role] = {
            role: [own_plays[k] - cap for k in range(rounds)],
            partner: [start_ctx + k * period + p_off - cap for k in range(rounds)],
        }

    out_rounds = []
    for k in range(rounds):
        r = {"k": k, "reasons": [], "usable": True, "detail": {}}
        arrivals = {}
        crossfire = {}
        for listener in ("A", "B"):
            sr = rec[listener]["sr"]
            for emitter in ("A", "B"):
                key = f"{emitter}_at_{listener}"
                t_exp = expected[listener][emitter][k]
                env_ok = rec[listener]["env"][emitter]
                env_wrong = rec[listener]["env"]["B" if emitter == "A" else "A"]
                a = _find_arrival(env_ok, sr, t_exp)
                arrivals[key] = a
                w = _find_arrival(env_wrong, sr, t_exp)
                lo, hi = _window(t_exp, sr)
                lo, hi = max(0, lo), min(len(env_wrong), hi)
                wrong_peak = float(np.max(env_wrong[lo:hi])) if hi > lo else 0.0
                right_peak = a["amp_strongest"] if a else (
                    float(np.max(env_ok[lo:hi])) if hi > lo else 0.0)
                if wrong_peak > 0 and right_peak > 0:
                    crossfire[key] = 20.0 * math.log10(right_peak / wrong_peak)
                else:
                    crossfire[key] = None
                if a is None:
                    r["usable"] = False
                    r["reasons"].append(f"no_arrival_{key}")
                else:
                    r["detail"][key] = {
                        "t_s": a["t_s"], "expected_s": t_exp,
                        "t_strongest_s": a["t_strongest_s"], "gap_ms": a["gap_ms"],
                    }
                if crossfire[key] is not None and crossfire[key] < CROSSFIRE_MIN_DB:
                    r["usable"] = False
                    r["reasons"].append(f"crossfire_low_{key}")

        r["crossfire_db"] = crossfire
        r["t_AA_s"] = arrivals["A_at_A"]["t_s"] if arrivals["A_at_A"] else None
        r["t_BA_s"] = arrivals["B_at_A"]["t_s"] if arrivals["B_at_A"] else None
        r["t_BB_s"] = arrivals["B_at_B"]["t_s"] if arrivals["B_at_B"] else None
        r["t_AB_s"] = arrivals["A_at_B"]["t_s"] if arrivals["A_at_B"] else None

        # quality: a flat run anywhere from this recording's first window start
        # to its last window end breaks the round. A slip inside a window moves
        # one arrival; a slip BETWEEN the two windows shifts one arrival against
        # the other and the four-arrival difference no longer cancels it.
        for listener in ("A", "B"):
            sr = rec[listener]["sr"]
            spans = rec[listener]["quality"]["flat_run_spans"]
            if not spans:
                continue
            wins = [_window(expected[listener][e][k], sr) for e in ("A", "B")]
            lo = min(w[0] for w in wins)
            hi = max(w[1] for w in wins)
            if any(a < hi and lo < b for a, b in spans):
                r["usable"] = False
                r["reasons"].append(f"timeline_gap_at_{listener}")

        r["drr_AB_db"] = None
        r["drr_BA_db"] = None
        if arrivals["A_at_B"]:
            r["drr_AB_db"] = _drr_db(rec["B"]["env"]["A"], rec["B"]["sr"],
                                     arrivals["A_at_B"]["t_s"])
        if arrivals["B_at_A"]:
            r["drr_BA_db"] = _drr_db(rec["A"]["env"]["B"], rec["A"]["sr"],
                                     arrivals["B_at_A"]["t_s"])

        if all(r[k2] is not None for k2 in ("t_AA_s", "t_BA_s", "t_BB_s", "t_AB_s")):
            delta = (r["t_BA_s"] - r["t_AA_s"]) - (r["t_BB_s"] - r["t_AB_s"])
            r["delta_ms"] = delta * 1000.0
            r["flight_cm"] = SPEED_OF_SOUND_CM_S * delta / 2.0
        else:
            r["delta_ms"] = None
            r["flight_cm"] = None
            r["usable"] = False
        out_rounds.append(r)

    good = [r for r in out_rounds if r["usable"] and r["flight_cm"] is not None]
    fl = [r["flight_cm"] for r in good]
    drrs = [v for r in good for v in (r["drr_AB_db"], r["drr_BA_db"]) if v is not None]
    cfs = [v for r in good for v in r["crossfire_db"].values() if v is not None]
    summary = {
        "usable_rounds": len(good),
        "total_rounds": rounds,
        "flight_cm_median": float(np.median(fl)) if fl else None,
        "flight_cm_spread": (float(np.max(fl) - np.min(fl)) if len(fl) > 1
                             else (0.0 if fl else None)),
        "drr_db_median": float(np.median(drrs)) if drrs else None,
        "crossfire_db_min": float(np.min(cfs)) if cfs else None,
    }

    med = summary["flight_cm_median"]
    spread = summary["flight_cm_spread"]
    if len(good) < MIN_USABLE_ROUNDS or med is None:
        decision = ("UNDECIDED", f"fewer than {MIN_USABLE_ROUNDS} usable rounds")
    elif spread is not None and spread > SPREAD_MAX_CM:
        decision = ("UNDECIDED", f"round spread {spread:.0f} cm > {SPREAD_MAX_CM:.0f} cm")
    elif med < NEAR_CM:
        decision = ("NEAR", f"flight_cm_median {med:.1f} < {NEAR_CM}")
    elif med > FAR_CM:
        decision = ("FAR", f"flight_cm_median {med:.1f} > {FAR_CM}")
    else:
        decision = ("UNDECIDED", f"flight_cm_median {med:.1f} between {NEAR_CM} and {FAR_CM}")

    result = {
        "status": "ok",
        "reasons": reasons,
        "version": VERSION,
        "session_id": session.get("session_id"),
        "label_cm": session.get("label_cm"),
        "rounds": out_rounds,
        "summary": summary,
        "quality": {r: {k2: v for k2, v in rec[r]["quality"].items()
                        if k2 != "flat_run_spans"} for r in ("A", "B")},
        "decision": {"label": decision[0], "provisional": True, "rule": decision[1]},
        "constants": _constants(),
    }
    try:
        (session_dir / "result.json").write_text(json.dumps(result, indent=2, default=float))
    except Exception as exc:
        result["reasons"].append(f"could not write result.json: {exc}")
    return result


def _fmt(v, spec=".1f"):
    return "   -  " if v is None else format(v, spec)


def print_result(res: dict) -> None:
    print(f"status: {res['status']}  {' '.join(res.get('reasons') or [])}")
    if res["status"] != "ok":
        return
    print(f"{'k':>2} {'flight_cm':>10} {'delta_ms':>9} {'drr_AB':>7} {'drr_BA':>7} "
          f"{'xfire_min':>9} {'usable':>6}  reasons")
    for r in res["rounds"]:
        cf = [v for v in r["crossfire_db"].values() if v is not None]
        print(f"{r['k']:>2} {_fmt(r['flight_cm']):>10} {_fmt(r['delta_ms'], '.3f'):>9} "
              f"{_fmt(r['drr_AB_db']):>7} {_fmt(r['drr_BA_db']):>7} "
              f"{_fmt(min(cf) if cf else None):>9} {str(r['usable']):>6}  "
              f"{','.join(r['reasons'])}")
    s = res["summary"]
    print(f"usable {s['usable_rounds']}/{s['total_rounds']}  "
          f"flight_cm median {_fmt(s['flight_cm_median'])} spread {_fmt(s['flight_cm_spread'])}  "
          f"DRR median {_fmt(s['drr_db_median'])} dB  crossfire min {_fmt(s['crossfire_db_min'])} dB")
    for role in ("A", "B"):
        q = res["quality"].get(role, {})
        print(f"  {role}: {q.get('sample_rate')} Hz, {q.get('clipped_samples')} clipped, "
              f"{len(q.get('flat_runs') or [])} flat runs, flags={q.get('flags')}")
    d = res["decision"]
    print(f"decision: {d['label']} (provisional) -- {d['rule']}")


def main(argv):
    if len(argv) != 2:
        print("usage: python analysis.py data/sessions/<session_id>")
        return 2
    res = analyze_session(pathlib.Path(argv[1]))
    print_result(res)
    return 0 if res["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
