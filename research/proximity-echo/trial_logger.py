"""Structured JSONL logging for proximity-echo trials."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parent
LOG_DIR = ROOT / "data" / "logs"
TRIALS_FILE = LOG_DIR / "trials.jsonl"

# Schema history:
#   1 (implicit, no field) — original paper_repro records.
#   2 — Phase-0 alias fix: per_beep_summary rows gain chirp_start (samples) and
#       canonical_sample_rate; device summaries gain self/partner train assignment,
#       cross_status, self-structure mask fields; pair gains alias_overlaps and
#       sum_residual_ms.
#   3 — Phase-1 B5 enforcement: each record gains `regression_coverage`
#       (historical automated-suite snapshot: status/reason/git_rev/mode) so an
#       uncovered live trial — server started with a stale/red/missing regression stamp —
#       is visible in the log. Additive only; older readers ignore the extra key.
#   4 — Phase-2 A3 timing prior: each record gains top-level `alignment_mode`
#       (prior_bounded | masked_full_sweep), and each device summary gains `alignment_mode`
#       + `cross_offset_prior` (center_ms/half_window_ms/search bounds/record_start_skew_ms,
#       or null when the full sweep ran). `alignment_mode` is the per-trial golden-pin key for
#       the dual-mode contract (A3.3). Additive only; older readers ignore the extra keys.
#   5 — Phase-3 C3 version stamping: each record gains a consolidated `provenance` block
#       (pipeline_version + constants snapshot hash/values + feature/classifier/validity
#       versions + log_schema_version + alignment_mode + regression_coverage). The pre-existing
#       top-level feature_version/alignment_mode/regression_coverage keys are KEPT so old-schema
#       readers still work; `provenance` is the new superset. Additive only.
#   6 — Phase-4 Workstream E (tier ladder + link-test gate): each record gains
#       `hardware_tier` (T1|T2|T3|T4|null), `hardware_notes` (free text|null),
#       `condition_distance` (touch|30cm|1m|other|null — the structured condition; the free-text
#       `condition_label` is kept as the grouping key), `link_test` (the session's most recent
#       reciprocal-audibility gate snapshot: present/passed/min_ratio/per-direction ratios +
#       pass flags/tier/band, or {"present": false} when none has run), and `is_link_test`
#       (true on the short probe records the gate itself produced, so analysis excludes them
#       from condition statistics). Additive only; older readers ignore the extra keys.
#   7 — Phase-4 link-test tier/band integrity: the stamped `link_test` block may gain
#       `stale` (bool) + `stale_reason` (str) when the session's most recent gate was measured
#       under a DIFFERENT hardware_tier/beep band than the trial it is stamped onto (server
#       compares tier AND band before stamping). experiment_power.gate_state maps such a record
#       to the 'stale' gate state (not 'passed'), so campaign go/no-go never silently admits a
#       trial gated for a different tier/band. Absent on matching stamps. Additive only; older
#       readers that ignore the two keys still read the block as before.
#   8 — Period selection records include failure reason, echo noise median and threshold.
#   9 — Experimental workflow removes automated-suite coverage fields from new records.
#       Old records retain their original provenance; signal-quality checks remain active.
LOG_SCHEMA_VERSION = 9


def ensure_log_dir() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def log_trial(record: dict) -> None:
    ensure_log_dir()
    with TRIALS_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
