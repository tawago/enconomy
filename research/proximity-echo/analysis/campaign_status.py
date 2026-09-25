"""Phase-4 campaign dashboard: the turnkey "where are we / collect K more" view (fix-plan §6 E2).

This is the human-facing companion to `experiment_power.py` (the statistics engine). It reads the
trial log, keeps VALID trials only, groups them by hardware tier and band, and for each
tier x band x scoring-rule reports:

  * N valid so far per condition (touch / distance) and the rejected trials itemized by failure
    reason (fix-plan E2: rejects are data about the tier, not noise);
  * the touch-minus-distance separation, its bootstrap CI, and the go/no-go call (CI excludes
    zero => GO), for BOTH the mean and the conservative min(c_a,c_b) scoring;
  * "collect K more valid trials per group" — the sequential-collection target from the power
    projection at the observed effect size.

It also prints the BAND DECISION view (bands ranked by separation + CI, not absolute score —
fix-plan E3) and a THRESHOLD-SWEEP view over the pooled valid scores (reusing sweep_thresholds).

Kept as its OWN tool rather than folded into summarize_trials.py: summarize_trials answers "what is
in the log" (descriptive counts, one pass, no statistics); campaign_status answers "what do we do
next" (bootstrap CIs, power projection, go/no-go). They have different runtimes and different
audiences, and coupling the descriptive summary to the (slower, seeded, bootstrap-heavy) decision
engine would make the quick summary slow and the decision logic hard to test in isolation.

usage:
  python analysis/campaign_status.py data/logs/trials.jsonl
  python analysis/campaign_status.py data/logs/trials.jsonl --positive touch --negative 30cm 1m
  python analysis/campaign_status.py data/logs/trials.jsonl --tier T2 --json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ANALYSIS_DIR = Path(__file__).resolve().parent
ROOT = ANALYSIS_DIR.parent
for p in (str(ANALYSIS_DIR), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import experiment_power as ep


def _verdict(sep: dict) -> str:
    if sep["status"] != "ok":
        return "PENDING"          # not enough data yet
    return "GO" if sep["excludes_zero"] else "NO-GO"


def build_dashboard(records: list[dict], *, positive: set[str], negative: set[str],
                    alpha: float, target_power: float, n_boot: int, seed: int,
                    project: bool) -> dict:
    # tier -> band -> [records]
    by_tier: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for r in records:
        by_tier[ep.tier_of(r)][ep.band_label(r)].append(r)

    # The go/no-go is computed on link-test-GATE-PASSED trials only (fix-plan §E1: the gate admits
    # the tier). Failed/absent-gate valid trials are itemized separately, not silently counted.
    admitted_records = [r for r in records if ep.gate_state(r) == "passed"]

    tiers: dict = {}
    for tier, bands in sorted(by_tier.items()):
        tier_records = [r for band_recs in bands.values() for r in band_recs]
        # Collection ledger: valid trials that PASSED the gate, per condition (this is what the
        # decision counts). Gate-excluded valid trials are tallied alongside for visibility so a
        # tier collected under a failing gate cannot silently look "collected".
        counts: dict[str, int] = defaultdict(int)
        gate_excluded: dict[str, dict[str, int]] = {
            "failed": defaultdict(int), "stale": defaultdict(int), "absent": defaultdict(int)}
        for r in tier_records:
            if not ep.is_valid_record(r):
                continue
            key = ep.condition_key(r) or "unlabeled"
            st = ep.gate_state(r)
            if st == "passed":
                counts[key] += 1
            else:
                gate_excluded[st][key] += 1
        band_reports: dict = {}
        for band, band_recs in sorted(bands.items()):
            band_admitted = [r for r in band_recs if ep.gate_state(r) == "passed"]
            band_reports[band] = ep.condition_pair_report(
                band_admitted, positive=positive, negative=negative, alpha=alpha,
                target_power=target_power, n_boot=n_boot, seed=seed, project=project)
        tiers[tier] = {
            "valid_counts": dict(sorted(counts.items())),
            "gate_excluded": {st: dict(sorted(d.items())) for st, d in gate_excluded.items() if d},
            "rejected_trials": ep.failure_breakdown(tier_records),
            "bands": band_reports,
        }

    dashboard = {
        "positive": sorted(positive),
        "negative": sorted(negative),
        "alpha": alpha,
        "target_power": target_power,
        "gate_note": "go/no-go computed on link-test-gate-passed trials only; failed/stale/absent-gate "
                     "valid trials are itemized per tier (gate_excluded) but do not count "
                     "(stale = link test measured under a different hardware tier/beep band than the trial)",
        "tiers": tiers,
        # Band decision pools ALL tiers (fix-plan E3 compares bands; tier is the orthogonal ladder).
        # Gate-passed trials only, same as the per-tier go/no-go.
        "band_decision": ep.band_separation_table(
            admitted_records, positive=positive, negative=negative, alpha=alpha, n_boot=n_boot, seed=seed),
        "threshold_sweep": threshold_sweep_view(admitted_records, positive=positive, negative=negative),
        "cautions": _statistical_cautions(tiers),
    }
    return dashboard


# ----------------------------------------------------------------------------------------
# Statistical honesty: the go/no-go is one look at a bootstrap CI. Three ways it can mislead an
# operator following the runbook, surfaced in every dashboard so they are impossible to miss.
# ----------------------------------------------------------------------------------------
def _statistical_cautions(tiers: dict) -> list[str]:
    cautions = [
        "OPTIONAL STOPPING: re-running this dashboard after each batch and stopping the moment a "
        "cell reads GO inflates the false-GO rate well above the nominal 5% (measured ~3x, ~15% "
        "cumulative over 5 looks under a true null). Pre-register a target N (the 'collect K more' "
        "number is a projection, not a stop rule) and read the verdict once at that N, or confirm a "
        "GO with a fresh fixed-N batch before reporting it.",
        "MULTIPLE COMPARISONS: this dashboard tests every tier x band x scoring at once. 'Report the "
        "lowest tier that reaches GO' harvests the best of that family, so an isolated GO (GO on min "
        "but NO-GO on mean, or GO at only one band) is exactly what a no-true-effect campaign throws "
        "off by chance — confirm it with a fresh replication batch before reporting.",
    ]
    # Only warn about small-N anticonservatism if some cell is actually in that regime and GO.
    small_n_go = any(
        entry["scorings"][sc]["separation"].get("small_sample")
        and entry["scorings"][sc]["separation"].get("excludes_zero")
        for tinfo in tiers.values()
        for entry in tinfo["bands"].values()
        for sc in ep.SCORINGS
    )
    if small_n_go:
        cautions.append(
            f"SMALL-N CI: a GO below {ep.SMALL_SAMPLE_MIN_N} valid trials/group is flagged "
            "small-N because the bootstrap CI (BCa or percentile) is anticonservative there "
            "(measured false-GO ≈8-9% at n=4-8 vs nominal 5%) — treat it as "
            "provisional until confirmed at the larger N.")
    return cautions


def threshold_sweep_view(records: list[dict], *, positive: set[str], negative: set[str],
                         steps: int = 21) -> dict:
    """A verdict-threshold sweep over the pooled VALID scores (fix-plan E3), reusing the
    sweep_thresholds metrics. Positives = the proximity condition(s); negatives = the distance
    condition(s). ONLY records whose condition is in positive ∪ negative enter the sweep — an
    'other'-labeled record (e.g. the runbook §1 deliberate-misconfiguration trials, or a
    different-room control) must NEVER be treated as a distance negative, or an AEC-suppressed
    or otherwise-anomalous score would shift the re-derived equal-error threshold. Reported for
    both scorings; the equal-error threshold is the tunable the paper fixed at 0.78 on their
    hardware — here it is re-derived from the user's own valid distribution."""
    from sweep_thresholds import metrics as sweep_metrics  # rewritten machinery (fix-plan D2)

    labeled = positive | negative
    out: dict = {}
    valid = [r for r in records if ep.is_valid_record(r) and ep.condition_key(r) in labeled]
    for scoring in ep.SCORINGS:
        rows: list[tuple[float, bool]] = []
        for r in valid:
            s = ep.record_score(r, scoring)
            if s is None:
                continue
            rows.append((s, ep.condition_key(r) in positive))
        n_pos = sum(1 for _, lab in rows if lab)
        n_neg = len(rows) - n_pos
        if n_pos == 0 or n_neg == 0:
            out[scoring] = {"status": "insufficient_data", "n_positive": n_pos, "n_negative": n_neg}
            continue
        # min/max scores can be negative (Pearson); sweep the observed range.
        lo = min(s for s, _ in rows)
        hi = max(s for s, _ in rows)
        grid = [lo + (hi - lo) * i / (steps - 1) for i in range(steps)] if hi > lo else [lo]
        results = [sweep_metrics(rows, t) for t in grid]
        eer_cands = [row for row in results if row["far"] is not None and row["frr"] is not None]
        eer = (min(eer_cands, key=lambda row: abs(row["far"] - row["frr"])) if eer_cands else None)
        out[scoring] = {
            "status": "ok", "n_positive": n_pos, "n_negative": n_neg,
            "score_range": [round(lo, 5), round(hi, 5)],
            "equal_error": ({"threshold": eer["threshold"], "far": eer["far"], "frr": eer["frr"]}
                            if eer else None),
            "sweep": results,
        }
    return out


# ----------------------------------------------------------------------------------------
# Text renderer (the dashboard operators actually read)
# ----------------------------------------------------------------------------------------
def _fmt_ci(sep: dict) -> str:
    if sep["status"] != "ok":
        return f"[{sep['status']} n_pos={sep['n_pos']} n_neg={sep['n_neg']}]"
    return (f"sep={sep['observed_separation']:+.3f}  CI[{sep['ci_low']:+.3f},{sep['ci_high']:+.3f}]"
            f" ({sep['ci_method']})")


def _fmt_collect(proj: dict | None) -> str:
    if proj is None:
        return ""
    st = proj["status"]
    if st == "ok":
        return f"collect {proj['collect_more_per_group']} more/group -> N={proj['projected_n_per_group']}"
    if st == "already_significant":
        return "target power already reached"
    if st == "unreached":
        return f"effect too small: N>{ep.DEFAULT_MAX_N}/group needed"
    return "insufficient data to project"


def render_text(dash: dict) -> str:
    L: list[str] = []
    L.append("=" * 92)
    L.append(f"PROXIMITY-ECHO CAMPAIGN STATUS   positive={dash['positive']}  negative={dash['negative']}")
    L.append(f"go/no-go = bootstrap CI on touch-minus-distance separation excludes zero "
             f"(alpha={dash['alpha']}, target power={dash['target_power']})")
    L.append("=" * 92)
    if not dash["tiers"]:
        L.append("\nNo trials for the selected generation. Nothing to report yet.")
    for tier, tinfo in dash["tiers"].items():
        L.append(f"\n### TIER {tier}")
        counts = tinfo["valid_counts"] or {}
        L.append("  valid trials/condition (gate PASSED, counted): " +
                 (", ".join(f"{k}={v}" for k, v in counts.items()) or "(none)"))
        ge = tinfo.get("gate_excluded") or {}
        if ge:
            parts = []
            for st in ("failed", "stale", "absent"):
                if ge.get(st):
                    parts.append(f"{st}: " + ", ".join(f"{k}={v}" for k, v in ge[st].items()))
            L.append("  gate-excluded (NOT counted): " + "; ".join(parts))
        rej = tinfo["rejected_trials"]
        L.append("  rejected (by reason):   " +
                 (", ".join(f"{k}={v}" for k, v in rej.items()) or "(none)"))
        for band, report in tinfo["bands"].items():
            L.append(f"  -- band {band} --")
            for scoring in ep.SCORINGS:
                entry = report["scorings"][scoring]
                sep = entry["separation"]
                proj = entry.get("projection")
                flag = "  [small-N: CI anticonservative]" if (sep.get("small_sample")
                                                              and sep["status"] == "ok") else ""
                L.append(f"     {scoring:<4}  {_verdict(sep):<7} {_fmt_ci(sep)}   {_fmt_collect(proj)}{flag}")

    L.append("\n### BAND DECISION (by separation + CI, not absolute score)")
    for band, entry in dash["band_decision"].items():
        L.append(f"  band {band}:")
        for scoring in ep.SCORINGS:
            sep = entry[scoring]
            L.append(f"     {scoring:<4}  {_verdict(sep):<7} {_fmt_ci(sep)}")

    L.append("\n### THRESHOLD SWEEP (verdict threshold re-derived on the user's valid scores)")
    for scoring in ep.SCORINGS:
        ts = dash["threshold_sweep"][scoring]
        if ts["status"] != "ok":
            L.append(f"  {scoring:<4}  [{ts['status']} n_pos={ts['n_positive']} n_neg={ts['n_negative']}]")
            continue
        eer = ts["equal_error"]
        eer_txt = (f"EER threshold={eer['threshold']:.3f} far={eer['far']} frr={eer['frr']}"
                   if eer else "EER undefined (single class)")
        L.append(f"  {scoring:<4}  n_pos={ts['n_positive']} n_neg={ts['n_negative']}  "
                 f"range={ts['score_range']}  {eer_txt}")

    cautions = dash.get("cautions") or []
    if cautions:
        L.append("\n### READ BEFORE TRUSTING A GO (statistical cautions)")
        import textwrap
        for c in cautions:
            wrapped = textwrap.fill(c, width=88, initial_indent="  - ", subsequent_indent="    ")
            L.append(wrapped)
    L.append("=" * 92)
    return "\n".join(L)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("trials", type=Path)
    p.add_argument("--positive", nargs="+", default=["touch"])
    p.add_argument("--negative", nargs="+", default=["30cm", "1m"])
    p.add_argument("--tier", action="append", dest="tiers", help="restrict to hardware tier(s)")
    p.add_argument("--feature-version", action="append", dest="feature_versions",
                   help=f"generation(s). Default: current ({ep.current_feature_version()}).")
    p.add_argument("--alpha", type=float, default=ep.DEFAULT_ALPHA)
    p.add_argument("--target-power", type=float, default=ep.DEFAULT_TARGET_POWER)
    p.add_argument("--n-boot", type=int, default=ep.DEFAULT_N_BOOT)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--no-project", action="store_true", help="skip the (slower) power projection")
    p.add_argument("--json", action="store_true", help="emit the full dashboard as JSON")
    args = p.parse_args()

    if not args.trials.exists():
        raise SystemExit(f"missing trial log: {args.trials}")
    records = ep.load_trials(args.trials)
    versions = set(args.feature_versions) if args.feature_versions else {ep.current_feature_version()}
    records = [r for r in records if r.get("feature_version") in versions]
    if args.tiers:
        wanted = set(args.tiers)
        records = [r for r in records if ep.tier_of(r) in wanted]

    dash = build_dashboard(
        records, positive=set(args.positive), negative=set(args.negative), alpha=args.alpha,
        target_power=args.target_power, n_boot=args.n_boot, seed=args.seed,
        project=not args.no_project)
    dash["feature_versions"] = sorted(versions)

    if args.json:
        print(json.dumps(dash, indent=2))
    else:
        print(render_text(dash))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
