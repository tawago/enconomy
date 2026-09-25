"""Threshold sweep for scored proximity-echo trials (current record schema).

Sweeps the accept/reject threshold over the proximity score and reports FAR/FRR/precision/
recall at each step plus the equal-error estimate. Reads the CURRENT log schema:

  * score      = record["score"]["score"]         (the Pearson proximity score)
  * validity   = record["pair"]["capture_valid"]  (the A2 capture-validity verdict)
  * label      = record["ground_truth_label"] or record["condition_label"]
  * generation = record["feature_version"]

Generation filter (fix-plan D1/D2): a threshold tuned on one feature generation must not be
contaminated by scores from another (retunes move scores; that is why the log became
uninterpretable). `--feature-version` selects which generation(s) to sweep and DEFAULTS to the
current pipeline generation (feature_extraction.FEATURE_VERSION). Pass it explicitly to sweep an
older generation (e.g. the archived `paper_repro_v1` trials). The tool prints every generation
present in the log so the right filter is obvious.

Pre-validity records policy (the 14 early paper_repro records): records that predate validity
wiring carry NO `pair` block, so their capture cannot be confirmed usable. A threshold sweep
must not count an unvalidated capture, so these are SKIPPED and reported under
`skipped.no_validity_assessment` rather than silently dropped. (`--include-unvalidated` overrides
this for exploratory use, treating a missing `pair` as capture_valid=True — use with care.)

usage:
  python analysis/sweep_thresholds.py data/logs/trials.jsonl --positive-label touch [...]
  python analysis/sweep_thresholds.py data/logs/trials.jsonl --positive-label touch \
      --feature-version paper_repro_v1
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from feature_extraction import FEATURE_VERSION  # noqa: E402  (the current pipeline generation)


def load_trials(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def is_positive(label: str | None, positive_labels: set[str]) -> bool:
    return bool(label and label in positive_labels)


def _score(record: dict, mode: str = "mean") -> float | None:
    """Per-trial scalar score. mode='mean' (default) is the pipeline's (c_a+c_b)/2; mode='min' is
    the conservative min(c_a,c_b) both-directions-must-agree rule (fix-plan E3). Both are derived
    from the per-direction correlations so the same records feed either rule; falls back to the
    stored mean score only when c_a/c_b are absent (old records)."""
    score = record.get("score") or {}
    c_a, c_b = score.get("c_a"), score.get("c_b")
    if c_a is not None and c_b is not None:
        return min(float(c_a), float(c_b)) if mode == "min" else 0.5 * (float(c_a) + float(c_b))
    value = score.get("score")
    return float(value) if (value is not None and mode == "mean") else None


def _band_label(record: dict) -> str:
    bs = record.get("beep_spec") or {}
    lo, hi = bs.get("start_freq_hz"), bs.get("end_freq_hz")
    if lo is None or hi is None:
        return "unknown_band"
    return f"{round(lo / 1000)}-{round(hi / 1000)}kHz"


def _label(record: dict) -> str | None:
    return record.get("ground_truth_label") or record.get("condition_label")


def _capture_valid(record: dict, include_unvalidated: bool) -> bool | None:
    """True/False from the validity block, or None when the record predates validity wiring
    (no `pair`). include_unvalidated collapses the None case to True."""
    pair = record.get("pair")
    if not pair:
        return True if include_unvalidated else None
    return bool(pair.get("capture_valid"))


def metrics(rows: list[tuple[float, bool]], threshold: float) -> dict:
    tp = fp = tn = fn = 0
    for score, label in rows:
        predicted = score >= threshold
        if predicted and label:
            tp += 1
        elif predicted and not label:
            fp += 1
        elif not predicted and label:
            fn += 1
        else:
            tn += 1
    far = fp / (fp + tn) if (fp + tn) else None
    frr = fn / (fn + tp) if (fn + tp) else None
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    return {
        "threshold": round(threshold, 5),
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "far": round(far, 5) if far is not None else None,
        "frr": round(frr, 5) if frr is not None else None,
        "precision": round(precision, 5) if precision is not None else None,
        "recall": round(recall, 5) if recall is not None else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("trials", type=Path)
    parser.add_argument("--positive-label", action="append", dest="positive_labels", required=True,
                        help="condition label(s) counted as a proximity positive (repeatable)")
    parser.add_argument("--negative-label", action="append", dest="negative_labels",
                        help="condition label(s) counted as the distance NEGATIVE (repeatable). When "
                             "given, ONLY positive+negative labels enter the sweep; every other "
                             "labeled valid trial is skipped so a stray condition cannot pollute the "
                             "FAR. Default: everything-not-positive is a negative (minus 'other').")
    parser.add_argument("--include-other", action="store_true",
                        help="include condition_distance=='other' records (the custom-label / "
                             "deliberate-misconfiguration class the runbook §1 logs). Excluded by "
                             "default so misconfig trials never enter the equal-error derivation.")
    parser.add_argument("--feature-version", action="append", dest="feature_versions",
                        help=f"generation(s) to sweep (repeatable). Default: {FEATURE_VERSION} (current).")
    parser.add_argument("--tier", action="append", dest="tiers",
                        help="hardware tier(s) to include (repeatable), e.g. T1 T2. "
                             "Default: all tiers. Use 'untiered' for pre-tier records.")
    parser.add_argument("--band", action="append", dest="bands",
                        help="band(s) to include (repeatable), e.g. 6-12kHz 4-9kHz. A threshold "
                             "pools scores, and band moves scores, so restrict to one band for a "
                             "clean sweep. Default: all bands.")
    parser.add_argument("--score-mode", choices=("mean", "min"), default="mean",
                        help="mean=(c_a+c_b)/2 (default); min=min(c_a,c_b), the conservative rule.")
    parser.add_argument("--include-unvalidated", action="store_true",
                        help="treat pre-validity records (no `pair`) as capture_valid=True")
    parser.add_argument("--steps", type=int, default=41)
    args = parser.parse_args()

    if not args.trials.exists():
        raise SystemExit(f"missing trial log: {args.trials}")

    records = load_trials(args.trials)
    available = Counter(r.get("feature_version") for r in records)
    wanted_versions = set(args.feature_versions) if args.feature_versions else {FEATURE_VERSION}

    rows: list[tuple[float, bool]] = []
    positives = set(args.positive_labels)
    negatives = set(args.negative_labels) if args.negative_labels else None
    wanted_tiers = set(args.tiers) if args.tiers else None
    wanted_bands = set(args.bands) if args.bands else None
    skipped = Counter()
    for record in records:
        # Link-test probe records are the gate's own short trials, never proximity data.
        if record.get("is_link_test"):
            skipped["link_test_probe"] += 1
            continue
        if record.get("feature_version") not in wanted_versions:
            skipped["other_feature_version"] += 1
            continue
        if wanted_tiers is not None and (record.get("hardware_tier") or "untiered") not in wanted_tiers:
            skipped["other_tier"] += 1
            continue
        if wanted_bands is not None and _band_label(record) not in wanted_bands:
            skipped["other_band"] += 1
            continue
        valid = _capture_valid(record, args.include_unvalidated)
        if valid is None:
            skipped["no_validity_assessment"] += 1
            continue
        if not valid:
            skipped["capture_invalid"] += 1
            continue
        # The 'other' distance is the UI's custom-label bucket (deliberate-misconfiguration and
        # non-sweep controls, runbook §1); those scores must never be treated as distance negatives
        # in the equal-error derivation. Excluded by default.
        if not args.include_other and record.get("condition_distance") == "other":
            skipped["other_condition"] += 1
            continue
        score = _score(record, args.score_mode)
        label = _label(record)
        if score is None:
            skipped["no_score"] += 1
            continue
        if label is None:
            skipped["no_label"] += 1
            continue
        positive = is_positive(label, positives)
        # With an explicit negative set, keep only positive+negative labels so a stray condition
        # cannot silently become a negative and shift the FAR / equal-error threshold.
        if negatives is not None and not positive and label not in negatives:
            skipped["other_condition"] += 1
            continue
        rows.append((score, positive))

    if not rows:
        raise SystemExit(json.dumps({
            "error": "no labeled valid scored trials for the selected generation(s)",
            "requested_feature_versions": sorted(wanted_versions),
            "available_feature_versions": dict(available),
            "skipped": dict(skipped),
        }, indent=2))

    thresholds = [index / max(1, args.steps - 1) for index in range(args.steps)]
    results = [metrics(rows, threshold) for threshold in thresholds]
    # An equal-error estimate needs BOTH a positive and a negative class to be defined; with a
    # single-class sample (e.g. only positives among the valid trials) far or frr is undefined
    # at every threshold, so report it as null instead of crashing on an empty min().
    eer_candidates = [row for row in results if row["far"] is not None and row["frr"] is not None]
    if eer_candidates:
        eer_row = min(eer_candidates, key=lambda row: abs(row["far"] - row["frr"]))
        eer = {"threshold": eer_row["threshold"], "far": eer_row["far"], "frr": eer_row["frr"]}
    else:
        n_pos = sum(1 for _, label in rows if label)
        eer = {"error": "undefined: sample has a single class",
               "n_positive": n_pos, "n_negative": len(rows) - n_pos}

    print(json.dumps({
        "requested_feature_versions": sorted(wanted_versions),
        "available_feature_versions": dict(available),
        "positive_labels": sorted(positives),
        "score_mode": args.score_mode,
        "bands_filter": sorted(wanted_bands) if wanted_bands else "all",
        "sample_count": len(rows),
        "skipped": dict(skipped),
        "equal_error_estimate": eer,
        "thresholds": results,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
