"""Summarize scored proximity-echo trials, grouped by hardware tier + condition WITHIN a generation.

A threshold or score summary that pools across feature generations is meaningless (a retune
moves every score), so this groups first by `feature_version`, then by `hardware_tier` (the
Workstream-E tier ladder; pre-tier records group under `untiered`), then by `condition_label`
within that tier. Reads the current record schema directly (no legacy compat shims):

  * score    = record["score"]["score"]
  * validity = record["pair"]["capture_valid"]        (absent => pre-validity record)
  * verdict  = record["pair"]["proximity_verdict"]    (falls back to record["score"]["verdict"])

Pre-validity records (the early paper_repro trials with no `pair`) cannot have their capture
confirmed, so they are counted under `unvalidated_count` rather than folded into the valid set.

usage: python analysis/summarize_trials.py data/logs/trials.jsonl
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def load_trials(path: Path) -> list[dict]:
    """Load the trial log, de-duplicated by trial_id (last wins). A repeated trial_id can only be a
    double-logged record (each start_trial mints a fresh id), so counting it twice would inflate the
    descriptive counts; the readers collapse duplicates defensively."""
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    seen: dict[str, int] = {}
    out: list[dict] = []
    for r in records:
        tid = r.get("trial_id")
        if tid is None:
            out.append(r)
        elif tid in seen:
            out[seen[tid]] = r
        else:
            seen[tid] = len(out)
            out.append(r)
    return out


def mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 5) if values else None


def capture_valid(record: dict) -> bool | None:
    """True/False from the validity block; None for pre-validity records (no `pair`)."""
    pair = record.get("pair")
    if not pair:
        return None
    return bool(pair.get("capture_valid"))


def proximity_score(record: dict) -> float | None:
    return (record.get("score") or {}).get("score")


def min_score(record: dict) -> float | None:
    """The conservative min(c_a,c_b) both-directions score (fix-plan E3), for the band decision.
    None when the per-direction correlations are absent (very old records)."""
    score = record.get("score") or {}
    c_a, c_b = score.get("c_a"), score.get("c_b")
    if c_a is None or c_b is None:
        return None
    return min(float(c_a), float(c_b))


def band_label(record: dict) -> str:
    bs = record.get("beep_spec") or {}
    lo, hi = bs.get("start_freq_hz"), bs.get("end_freq_hz")
    if lo is None or hi is None:
        return "unknown_band"
    return f"{round(lo / 1000)}-{round(hi / 1000)}kHz"


def proximity_verdict(record: dict) -> bool | None:
    pair = record.get("pair") or {}
    if "proximity_verdict" in pair:
        return pair.get("proximity_verdict")
    return (record.get("score") or {}).get("verdict")


def _summarize_condition(records: list[dict]) -> dict:
    validated = [r for r in records if capture_valid(r) is not None]
    unvalidated = [r for r in records if capture_valid(r) is None]
    valid_records = [r for r in validated if capture_valid(r)]
    scores = [proximity_score(r) for r in valid_records if proximity_score(r) is not None]
    min_scores = [min_score(r) for r in valid_records if min_score(r) is not None]
    verdicts = [proximity_verdict(r) for r in valid_records if proximity_verdict(r) is not None]
    band_counts: dict[str, int] = {}
    for r in valid_records:
        band_counts[band_label(r)] = band_counts.get(band_label(r), 0) + 1
    failure_reasons = sorted({
        reason
        for r in records
        for reason in ((r.get("pair") or {}).get("failure_reasons") or [])
    })
    return {
        "trial_count": len(records),
        "unvalidated_count": len(unvalidated),
        "valid_capture_count": len(valid_records),
        "valid_capture_rate": round(len(valid_records) / len(validated), 5) if validated else None,
        "score_mean": mean(scores),
        "score_min": round(min(scores), 5) if scores else None,
        "score_max": round(max(scores), 5) if scores else None,
        "min_score_mean": mean(min_scores),  # mean of the per-trial min(c_a,c_b) (both-directions rule)
        "verdict_accept_rate": round(sum(1 for v in verdicts if v) / len(verdicts), 5) if verdicts else None,
        "bands": dict(sorted(band_counts.items())),  # valid trials by band (for the E3 band decision)
        "failure_reasons": failure_reasons,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("trials", type=Path)
    args = parser.parse_args()

    if not args.trials.exists():
        raise SystemExit(f"missing trial log: {args.trials}")

    # generation -> tier -> condition -> [records]. Link-test probe records (is_link_test) are
    # excluded: they are the gate's own short trials, not condition data.
    by_generation: dict[str, dict[str, dict[str, list[dict]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    for record in load_trials(args.trials):
        if record.get("is_link_test"):
            continue
        generation = record.get("feature_version") or "unknown_generation"
        tier = record.get("hardware_tier") or "untiered"
        condition = record.get("condition_label") or "unlabeled"
        by_generation[generation][tier][condition].append(record)

    summary: dict[str, dict] = {}
    for generation, tiers in sorted(by_generation.items()):
        summary[generation] = {
            tier: {
                condition: _summarize_condition(records)
                for condition, records in sorted(conditions.items())
            }
            for tier, conditions in sorted(tiers.items())
        }

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
