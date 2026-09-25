"""Table over many fieldtest sessions.  CONTRACT.md section 10.

  python compare.py [--dir data/sessions] [--csv] [--by probe,room,label_cm]

`correct`: label <= 30 expects NEAR, >= 100 expects FAR, other labels blank.
Per-rule columns: the primary arrival rule ("first" unless FIELD_ARRIVAL_RULE was set at
analysis time) without prefix, "ow" = ownwalk (blank for sessions analysed before v2).
Sessions without a result.json (or a failed one) are counted in `failed` at the end.
In the default dir (data/sessions), sessions labelled note "e2e" (fake phones) are
skipped and counted; e2e runs normally land in data/e2e (`--dir data/e2e`).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
PROBE_ORDER = ("N30", "N250", "N500", "N1s", "JB", "JBQ", "JBL", "JBL250")
RULE_COLS = ["NEAR/FAR/UND", "correct", "flight_median", "worst spread", "usable rounds", "min margin dB"]
ALT = "ow"   # column prefix for the ownwalk rule
COLS = (["probe", "room", "label_cm", "n"] + RULE_COLS + ["right% median", "T median", "gaps"]
        + [f"{ALT} {c}" for c in RULE_COLS])


def load(dirs, skip_e2e=False):
    rows, failed = [], []
    load.skipped_e2e = 0
    for d in dirs:
        d = Path(d)
        try:
            s = json.loads((d / "session.json").read_text())
            r = json.loads((d / "result.json").read_text())
        except Exception:
            failed.append(d.name)
            continue
        if skip_e2e and (s.get("labels") or {}).get("note") == "e2e":
            load.skipped_e2e += 1
            continue
        if r.get("status") != "ok":
            failed.append(d.name)
            continue
        lab = s.get("labels") or {}
        for p, pr in (r.get("probes") or {}).items():
            gaps = sum(1 for rd in pr["rounds"] for x in rd["reasons"] if x.startswith("timeline_gap"))
            alt_s = pr.get("summary_ownwalk")
            alt_d = (pr.get("decision_ownwalk") or {}).get("label")
            if alt_s is None and (pr.get("decision") or {}).get("arrival_rule") == "ownwalk":
                alt_s, alt_d = pr["summary"], pr["decision"]["label"]
            rows.append({"session": d.name, "probe": p, "room": lab.get("room"),
                         "label_cm": lab.get("label_cm"), "pose": lab.get("pose"),
                         "noise": lab.get("noise"), "decision": pr["decision"]["label"],
                         "gaps": gaps, **pr["summary"],
                         "alt": ({"decision": alt_d, **alt_s} if alt_s else None)})
    return rows, failed


def _expect(label):
    if label is None:
        return None
    return "NEAR" if label <= 30 else ("FAR" if label >= 100 else None)


def _med(v):
    v = [x for x in v if x is not None]
    return float(np.median(v)) if v else None


def _f(v, spec=".1f"):
    return "" if v is None else format(v, spec)


def _rule_cols(ss, rs, prefix):
    """Decision/flight columns over summaries ss (same order as session rows rs)."""
    dec = [x["decision"] for x in ss]
    exp = [_expect(r["label_cm"]) for r in rs]
    corr = [d == e for d, e in zip(dec, exp) if e is not None]
    vals = {
        "NEAR/FAR/UND": f"{dec.count('NEAR')}/{dec.count('FAR')}/{dec.count('UNDECIDED')}",
        "correct": f"{sum(corr)}/{len(corr)}" if corr else "",
        "flight_median": _med([x["flight_median"] for x in ss]),
        "worst spread": max([x["spread"] for x in ss if x["spread"] is not None], default=None),
        "usable rounds": f"{sum(x['usable_rounds'] for x in ss)}/{sum(x['total_rounds'] for x in ss)}",
        "min margin dB": min([x["min_margin_db"] for x in ss if x["min_margin_db"] is not None], default=None),
    }
    return {prefix + k: v for k, v in vals.items()}


def group(rows, by):
    g = {}
    for r in rows:
        g.setdefault(tuple(r.get(b) for b in by), []).append(r)
    order = lambda k: tuple(
        (PROBE_ORDER.index(v) if b == "probe" and v in PROBE_ORDER else
         (v if isinstance(v, (int, float)) else (1e9 if v is None else 0)), str(v))
        for b, v in zip(by, k))
    out = []
    for key in sorted(g, key=order):
        rs = g[key]
        row = dict(zip(by, key))
        row["n"] = len(rs)
        row.update(_rule_cols(rs, rs, ""))
        alts = [(r["alt"], r) for r in rs if r.get("alt")]
        if alts:
            row.update(_rule_cols([a for a, _ in alts], [r for _, r in alts], f"{ALT} "))
        row.update({
            "right% median": _med([r["right_pct_median"] for r in rs]),
            "T median": _med([r["null_T_median"] for r in rs]),
            "gaps": sum(r["gaps"] for r in rs),
        })
        for extra in ("pose", "noise"):
            if extra not in by:
                vals = sorted({str(r.get(extra)) for r in rs})
                row[extra] = ",".join(vals)
        out.append(row)
    return out


def table(loaded, by=("probe", "room", "label_cm"), as_csv=False):
    rows, failed = loaded
    by = list(by)
    grp = group(rows, by)
    extras = [e for e in ("pose", "noise") if e not in by and len({r.get(e) for r in rows}) > 1]
    cols = by + COLS[3:] + extras
    fmt = lambda v: _f(v) if isinstance(v, float) else ("" if v is None else str(v))
    if as_csv:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(cols)
        for r in grp:
            w.writerow([fmt(r.get(c)) for c in cols])
        return buf.getvalue()
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(fmt(r.get(c)) for c in cols) + " |" for r in grp]
    if getattr(load, "skipped_e2e", 0):
        lines.append(f"\nskipped e2e test sessions: {load.skipped_e2e}")
    if failed:
        lines.append(f"\nfailed or missing result: {len(failed)} ({', '.join(failed[:10])})")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    default_dir = HERE / "data" / "sessions"
    ap.add_argument("--dir", default=str(default_dir))
    ap.add_argument("--csv", action="store_true")
    ap.add_argument("--by", default="probe,room,label_cm")
    a = ap.parse_args(argv)
    dirs = sorted(p.parent for p in Path(a.dir).glob("*/session.json"))
    skip = Path(a.dir).resolve() == default_dir.resolve()
    print(table(load(dirs, skip_e2e=skip), [b.strip() for b in a.by.split(",") if b.strip()], a.csv))
    return 0


if __name__ == "__main__":
    sys.exit(main())
