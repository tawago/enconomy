"""Integer twin of the optionA-v2 receiver: earliest lag with score >= 9 %, exact circuit math.

  $PY twin2.py all            # 12 JBL250 sessions x 2 rounds x 4 arrivals: twin vs float reference
                               # (fieldanalysis correlation, same rule, 0 ppm) vs result.json ("first")
                               # -> build/twin2_all.json, printed summary
Library: curve(), earliest(), arrivals(sess8, round) used by build_fixtures2.py and prep.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from common2 import HM, L, SR, T0, WPOST, WPRE, flight_cm, verdict
import twin as tw1                      # optionA-jbl250/twin.py: load, windows, templates, fir, q16, bconst

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
KEYS = ("A_at_A", "B_at_A", "B_at_B", "A_at_B")
H, G = tw1.fir()
B = tw1.bconst(G, T0)


def curve(xw, cI, cQ, K):
    """xw: int16 samples x[lo-HM : lo+K+L-1+HM]. Returns (I, Q, E) as Python-int lists, K lags."""
    xw = np.asarray(xw, dtype=np.int64)
    assert len(xw) == K + L - 1 + 2 * HM
    I = tw1.corr_exact(xw[HM:], np.asarray(cI, dtype=np.int64), K)
    Q = tw1.corr_exact(xw[HM:], np.asarray(cQ, dtype=np.int64), K)
    y = np.convolve(xw, H[::-1], mode="valid")          # y[m] = sum_t h[t] xw[m+t]
    assert len(y) == K + L - 1
    y2 = [int(v) * int(v) for v in y]
    cs = [0]
    for v in y2:
        cs.append(cs[-1] + v)
    E = [cs[k + L] - cs[k] for k in range(K)]
    return [int(v) for v in I], [int(v) for v in Q], E


def passes(I, Q, E, cn2):
    return [(i * i + q * q) * B >= e * cn2 for i, q, e in zip(I, Q, E)]


def score(I, Q, E, cn2):
    return [float(np.sqrt((i * i + q * q) * G * G / (e * cn2))) if e else 0.0 for i, q, e in zip(I, Q, E)]


def earliest(ok):
    for j, v in enumerate(ok):
        if v:
            return j
    return None


_cache = {}


def session_dir(sess8):
    return next(tw1.SESS.glob(sess8 + "*"))


def load(sess8):
    if sess8 not in _cache:
        d = session_dir(sess8)
        session, res, rec = tw1.load(d)
        x = {r: tw1.q16(rec[r]["x"]) for r in "AB"}
        tpl = {E: tw1.templates(session["seed_hex"], E) for E in "AB"}
        _cache[sess8] = (d, session, res, rec, x, tpl)
    return _cache[sess8]


def arrivals(sess8, k=0, keep_curve=False):
    """Twin arrivals (absolute sample index in the listener's file) for round k, web windows."""
    d, session, res, rec, x, tpl = load(sess8)
    wins = tw1.windows(session, rec, k)
    out = {}
    for key in KEYS:
        E_, Lr = key.split("_at_")
        lo, hi = wins[(E_, Lr)]
        K = hi - lo
        cI, cQ = tpl[E_]
        cn2 = int(np.dot(cI, cI))
        I, Q, En = curve(x[Lr][lo - HM: lo + K + L - 1 + HM], cI, cQ, K)
        ok = passes(I, Q, En, cn2)
        j = earliest(ok)
        sc = score(I, Q, En, cn2)
        rec_ = {"lo": lo, "hi": hi, "K": K, "j": j, "n": None if j is None else lo + j,
                "score": None if j is None else sc[j],
                "max_before_1ms": None if j is None or j < 48 else max(sc[: j - 48]),
                "n_pass": sum(ok), "cn2": cn2}
        if keep_curve:
            rec_.update({"I": I, "Q": Q, "E": En, "ok": ok, "sc": sc})
        out[key] = rec_
    return out


def float_reference(sess8, k):
    """fieldanalysis' own float correlation and normalization, rule replaced by 'earliest score >= T0',
    ppm bank off. Returns {key: absolute sample index}."""
    import fieldanalysis as fa
    import fieldprobes as fp
    d, session, res, rec, x, tpl = load(sess8)
    fa.PPM_BANK = (0,)
    fa.N_NULL = 2
    fa._first_arrival = lambda env, sc, T, look: (
        (int(np.argmax(sc >= T0)), 0) if np.any(sc >= T0) else (None, 0))
    sched = session["schedule"]
    pre, post = float(sched["search_pre_s"]), float(sched["search_post_s"])
    windows = {}
    recf = {}
    for Lr in "AB":
        meta = rec[Lr]["meta"]
        recf[Lr] = {"x": rec[Lr]["x"], "sr": SR, "meta": meta}
        cap, start = float(meta["capture_start_ctx_s"]), float(meta["start_ctx_s"])
        own = {(q.get("probe"), int(q.get("k"))): float(q["ctx_s"]) for q in meta.get("plays") or []}
        for E_ in "AB":
            if E_ == Lr:
                exp = own.get(("JBL250", k), start + fp.offset_s(sched, "JBL250", E_, k)) - cap
            else:
                exp = start + fp.offset_s(sched, "JBL250", E_, k) - cap
            windows[(E_, Lr, k)] = (int(round((exp - pre) * SR)), int(round((exp + post) * SR)), exp)
    arr = fa._probe_all("JBL250", recf, session["seed_hex"], windows)
    out = {}
    for (E_, Lr, kk), v in arr.items():
        pk = v["picks"]["first"] if v else None
        out[f"{E_}_at_{Lr}"] = int(round(pk["t"] * SR)) if pk and pk.get("found") else None
    return out


def run_all():
    rows = []
    sess = [dd.name[:8] for dd in tw1.sessions()]
    for s in sess:
        d, session, res, rec, x, tpl = load(s)
        for k in (0, 1):
            tw = arrivals(s, k)
            fr = float_reference(s, k)
            rj = res["probes"]["JBL250"]["rounds"][k]
            row = {"session": s, "label": session["labels"].get("label_cm"), "round": k}
            for key in KEYS:
                ref_first = rj["arrivals"][key]
                row[key] = {"twin": tw[key]["n"], "float_earliest": fr[key],
                            "result_first": int(round(ref_first["t"] * SR)) if ref_first.get("found", True) and ref_first.get("t") is not None else None,
                            "twin_score": tw[key]["score"], "max_before_1ms": tw[key]["max_before_1ms"],
                            "lo": tw[key]["lo"], "K": tw[key]["K"]}
            n = {key: row[key]["twin"] for key in KEYS}
            if all(v is not None for v in n.values()):
                hA, hB = n["B_at_A"] - n["A_at_A"], n["B_at_B"] - n["A_at_B"]
                row["twin_half"] = {"A": hA, "B": hB}
                row["twin_flight"] = flight_cm(hA, hB)
            f = {key: row[key]["float_earliest"] for key in KEYS}
            if all(v is not None for v in f.values()):
                row["float_flight"] = flight_cm(f["B_at_A"] - f["A_at_A"], f["B_at_B"] - f["A_at_B"])
            row["result_flight"] = rj.get("flight_cm")
            rows.append(row)
            print(json.dumps({kk: vv for kk, vv in row.items() if kk not in KEYS}), flush=True)
    BUILD.mkdir(exist_ok=True)
    (BUILD / "twin2_all.json").write_text(json.dumps(rows, indent=1))
    summarize(rows)


def summarize(rows):
    diffs_f, diffs_r = [], []
    for r in rows:
        for key in KEYS:
            a = r[key]
            if a["twin"] is not None and a["float_earliest"] is not None:
                diffs_f.append(a["twin"] - a["float_earliest"])
            if a["twin"] is not None and a["result_first"] is not None:
                diffs_r.append(a["twin"] - a["result_first"])
    n = len(rows) * 4
    print(f"\narrivals: {n}; twin found {sum(r[k]['twin'] is not None for r in rows for k in KEYS)}")
    print(f"twin - float(earliest>=9%): identical {sum(d == 0 for d in diffs_f)}/{len(diffs_f)}, "
          f"|diff|<=1: {sum(abs(d) <= 1 for d in diffs_f)}, max |diff| {max(map(abs, diffs_f))}")
    print(f"twin - result.json('first'): min {min(diffs_r)} max {max(diffs_r)} samples "
          f"({min(diffs_r)/SR*1e3:.2f} .. {max(diffs_r)/SR*1e3:.2f} ms)")
    sc = [r[k]["twin_score"] for r in rows for k in KEYS if r[k]["twin_score"] is not None]
    mb = [r[k]["max_before_1ms"] for r in rows for k in KEYS if r[k]["max_before_1ms"] is not None]
    print(f"arrival score min {100*min(sc):.1f}%, highest score >1 ms before an arrival {100*max(mb):.1f}%")
    for r in rows:
        if "twin_flight" in r:
            tv, rv = verdict(r["twin_flight"]), verdict(r["result_flight"])
            print(f"{r['session']} r{r['round']} label {r['label']:5.0f}  twin {r['twin_flight']:7.1f}  "
                  f"float {r.get('float_flight', float('nan')):7.1f}  result(first) {r['result_flight']:7.1f}  "
                  f"{tv} {'==' if tv == rv else '!='} {rv}  d={r['twin_flight']-r['result_flight']:+.1f} cm")


if __name__ == "__main__":
    if sys.argv[1:2] == ["all"]:
        run_all()
    elif sys.argv[1:2] == ["summary"]:
        summarize(json.loads((BUILD / "twin2_all.json").read_text()))
