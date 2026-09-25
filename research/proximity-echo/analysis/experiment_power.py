"""Powered experiment tooling for the proximity-echo distance sweep (fix-plan §6 / Workstream E2-E3).

This module is the STATISTICS ENGINE behind the Phase-4 campaign. It answers three questions the
go/no-go decision needs, on VALID trials only, per hardware tier and per band:

  1. SEPARATION + CONFIDENCE. Does the touch (proximity) score distribution sit above the
     distance (non-proximity) distribution by more than noise? The decision statistic is
     "the bootstrap CI on the touch-minus-distance separation excludes zero" (fix-plan E2:
     "N chosen so a bootstrap CI on the touch-vs-1m score separation excludes zero — not a
     point-EER from 5 samples"). Reported for BOTH scoring rules the pipeline exposes:
       * mean  scoring: score = (c_a + c_b) / 2        (the pipeline's default)
       * min   scoring: score = min(c_a, c_b)          (the both-directions-must-agree rule;
                                                         the sim's chosen discriminator)
     Both are computed per trial from the logged per-direction correlations c_a, c_b, so the
     same valid trials feed both rules and the two can be compared directly.

  2. POWER / SEQUENTIAL COLLECTION. Given the data collected so far, how many MORE valid trials
     per group are needed before the CI excludes zero at the observed effect size? A
     resampling-based projection (documented assumptions below) yields a power curve over N and
     the smallest N reaching a target power — i.e. the "collect K more" number the campaign
     dashboard prints.

  3. BAND DECISION SUPPORT. The paper's 0.78 threshold was tuned on THEIR hardware, so bands are
     compared by SEPARATION, not absolute score (fix-plan E3). `band_separation_table` scores the
     same analysis per band (6-12 vs 4-9 vs 14-15 kHz) so the campaign can pick a band by which
     one separates touch from distance most reliably on the user's hardware.

CI method — BCa vs percentile (justification, honest about what we measured). The default is BCa
(bias-corrected and accelerated). Proximity scores are Pearson correlations bounded in [-1, 1]; a
touch distribution piles up near the ceiling, so the bootstrap distribution of the separation is
skewed and biased, and BCa is the theoretically-preferred correction — it applies a bias
correction z0 (median-bias of the bootstrap distribution) and an acceleration a (skewness, via a
multi-sample jackknife over every observation). But do NOT overstate the empirical win: in this
project's OWN null-calibration measurements BCa and the plain percentile interval come out close
(coverage within Monte-Carlo noise at n≈20; the shipped case prints both), and the dominant
problem at campaign sample sizes is small-N under-coverage that afflicts BOTH methods — measured
one-sided coverage is anticonservative below n≈10 per group (see SMALL_SAMPLE_MIN_N and the
small-N calibration report). So: BCa is a reasonable, theory-backed default rather than a fix for
under-coverage; neither method reaches nominal coverage at the N a live campaign collects, which
is why small groups carry an explicit anticonservative-CI warning. We compute and report the
percentile interval alongside BCa for transparency. When the bootstrap distribution is degenerate (all replicates equal, e.g. n too
small) BCa is undefined and the code falls back to the percentile interval with a recorded note.

Import it as a library (campaign_status.py does) or run it directly:

  # one condition-pair, full separation + power report (JSON)
  python analysis/experiment_power.py data/logs/trials.jsonl \
      --positive touch --negative 30cm 1m --tier T2 --json

"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.stats import norm

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ----------------------------------------------------------------------------------------
# Defaults (documented; overridable from the CLI / callers). Kept here rather than in
# pipeline_constants.py because these are ANALYSIS knobs (how we read the data), not pipeline
# tunables that change a score — mixing the two is what made the old log uninterpretable.
# ----------------------------------------------------------------------------------------
DEFAULT_ALPHA = 0.10            # two-sided; a 90% CI. Excludes-zero == the 95% one-sided lower bound
                                # > 0, matching a one-sided "touch > distance" go decision at 5%.
DEFAULT_N_BOOT = 4000           # bootstrap replicates for a reported CI.
DEFAULT_TARGET_POWER = 0.80     # projection target: P(CI excludes zero) at the projected N.
DEFAULT_PROJECTION_NBOOT = 800  # inner bootstrap size during the (nested) power projection.
DEFAULT_PROJECTION_SIMS = 300   # synthetic datasets per candidate N in the projection.
DEFAULT_MAX_N = 120             # projection search ceiling per group.
MIN_GROUP_FOR_CI = 3            # below this a bootstrap CI is meaningless; report insufficient_data.
SMALL_SAMPLE_MIN_N = 10         # per group. At/above this the BCa CI is ~nominal in the shipped null
                                # calibration; BELOW it the one-sided lower bound is measurably
                                # ANTICONSERVATIVE (measured P(ci_low>0 | true null) ≈0.08-0.09
                                # across n=4-8 — seeded null draw n=4:0.077, n=6:0.090, n=8:0.080 —
                                # vs the nominal 0.05, both BCa and
                                # percentile). A GO from fewer than this many valid trials/group is
                                # flagged small_sample so an early verdict is not read as calibrated.
                                # NOT a hard floor (MIN_GROUP_FOR_CI stays the floor) so a tight,
                                # unambiguous effect can still be seen early — but it must be
                                # confirmed at N>=this before it is reported as a decision.

SCORINGS = ("mean", "min")


# ========================================================================================
# Scoring rules
# ========================================================================================
def trial_scores(c_a: float, c_b: float) -> dict[str, float]:
    """The two per-trial scalar scores from the per-direction correlations."""
    return {"mean": 0.5 * (c_a + c_b), "min": min(c_a, c_b)}


def separation(pos: np.ndarray, neg: np.ndarray) -> float:
    """The go/no-go effect: how far the proximity group sits above the distance group."""
    return float(np.mean(pos) - np.mean(neg))


# ========================================================================================
# Bootstrap intervals
# ========================================================================================
def _bootstrap_separation_replicates(pos: np.ndarray, neg: np.ndarray, n_boot: int,
                                     rng: np.random.Generator) -> np.ndarray:
    """n_boot resampled separations. Groups are resampled INDEPENDENTLY with replacement
    (each is its own population), which is the correct scheme for a two-sample statistic."""
    n_p, n_n = pos.size, neg.size
    pos_bs = pos[rng.integers(0, n_p, size=(n_boot, n_p))].mean(axis=1)
    neg_bs = neg[rng.integers(0, n_n, size=(n_boot, n_n))].mean(axis=1)
    return pos_bs - neg_bs


def _percentile_ci(replicates: np.ndarray, alpha: float) -> tuple[float, float]:
    lo = float(np.percentile(replicates, 100 * (alpha / 2)))
    hi = float(np.percentile(replicates, 100 * (1 - alpha / 2)))
    return lo, hi


def _jackknife_separations(pos: np.ndarray, neg: np.ndarray) -> np.ndarray:
    """Leave-one-out separations over EVERY observation (multi-sample jackknife): each point is
    removed from whichever group it belongs to and the separation recomputed. Used for the BCa
    acceleration (skewness). Closed-form via group sums so it stays O(n)."""
    n_p, n_n = pos.size, neg.size
    sp, sn = pos.sum(), neg.sum()
    # drop one positive: pos-mean uses (n_p-1) points, neg unchanged
    pos_loo = (sp - pos) / (n_p - 1) - sn / n_n
    # drop one negative: neg-mean uses (n_n-1) points, pos unchanged
    neg_loo = sp / n_p - (sn - neg) / (n_n - 1)
    return np.concatenate([pos_loo, neg_loo])


def _bca_ci(pos: np.ndarray, neg: np.ndarray, replicates: np.ndarray, observed: float,
            alpha: float) -> tuple[tuple[float, float], str]:
    """Bias-corrected and accelerated interval. Returns ((lo, hi), method) where method is
    'bca' or 'percentile' when BCa degenerates (constant bootstrap dist or a==inf)."""
    n_boot = replicates.size
    prop_less = float(np.mean(replicates < observed))
    # Degenerate bootstrap (all replicates equal, e.g. every group value identical): no interval
    # to correct — fall back to percentile.
    if prop_less <= 0.0 or prop_less >= 1.0:
        return _percentile_ci(replicates, alpha), "percentile"
    z0 = norm.ppf(prop_less)

    jack = _jackknife_separations(pos, neg)
    jack_mean = jack.mean()
    diffs = jack_mean - jack
    denom = 6.0 * (np.sum(diffs ** 2) ** 1.5)
    if denom == 0.0:
        return _percentile_ci(replicates, alpha), "percentile"
    accel = float(np.sum(diffs ** 3) / denom)

    def _endpoint(z: float) -> float:
        adj = z0 + (z0 + z) / (1 - accel * (z0 + z))
        return float(norm.cdf(adj))

    a1 = _endpoint(norm.ppf(alpha / 2))
    a2 = _endpoint(norm.ppf(1 - alpha / 2))
    if not (np.isfinite(a1) and np.isfinite(a2)) or a1 >= a2:
        return _percentile_ci(replicates, alpha), "percentile"
    lo = float(np.percentile(replicates, 100 * a1))
    hi = float(np.percentile(replicates, 100 * a2))
    return (lo, hi), "bca"


# ========================================================================================
# Public results
# ========================================================================================
@dataclass
class SeparationResult:
    scoring: str
    status: str                         # "ok" | "insufficient_data"
    n_pos: int
    n_neg: int
    pos_mean: float | None = None
    neg_mean: float | None = None
    observed_separation: float | None = None
    ci_method: str | None = None
    alpha: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    ci_width: float | None = None
    excludes_zero: bool | None = None
    small_sample: bool | None = None           # True when min(n_pos,n_neg) < SMALL_SAMPLE_MIN_N:
                                               # the CI (BCa or percentile) is anticonservative here,
                                               # so a GO must be confirmed at a larger N before it counts.
    percentile_ci: list[float] | None = None   # [lo, hi], for comparison against BCa
    n_boot: int | None = None
    note: str | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class ProjectionResult:
    scoring: str
    status: str                         # "ok" | "already_significant" | "insufficient_data" | "unreached"
    current_n_per_group: int
    target_power: float
    projected_n_per_group: int | None = None
    collect_more_per_group: int | None = None
    power_curve: list[list[float]] = field(default_factory=list)   # [[N, power], ...]
    analytic_n_per_group: int | None = None    # normal-approx cross-check
    method: str = ""
    assumptions: str = ""
    note: str | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def analyze_separation(pos: np.ndarray, neg: np.ndarray, *, scoring: str,
                       alpha: float = DEFAULT_ALPHA, n_boot: int = DEFAULT_N_BOOT,
                       ci_method: str = "bca",
                       rng: np.random.Generator | None = None) -> SeparationResult:
    """Bootstrap CI on the touch-minus-distance separation for one scoring rule."""
    pos = np.asarray(pos, dtype=float)
    neg = np.asarray(neg, dtype=float)
    if pos.size < MIN_GROUP_FOR_CI or neg.size < MIN_GROUP_FOR_CI:
        return SeparationResult(
            scoring=scoring, status="insufficient_data", n_pos=int(pos.size), n_neg=int(neg.size),
            note=f"need >= {MIN_GROUP_FOR_CI} valid trials per group for a bootstrap CI",
        )
    rng = rng or np.random.default_rng(0)
    observed = separation(pos, neg)
    reps = _bootstrap_separation_replicates(pos, neg, n_boot, rng)
    pct = _percentile_ci(reps, alpha)
    if ci_method == "percentile":
        (lo, hi), method = pct, "percentile"
    else:
        (lo, hi), method = _bca_ci(pos, neg, reps, observed, alpha)
    return SeparationResult(
        scoring=scoring, status="ok", n_pos=int(pos.size), n_neg=int(neg.size),
        pos_mean=round(float(np.mean(pos)), 5), neg_mean=round(float(np.mean(neg)), 5),
        observed_separation=round(observed, 5), ci_method=method, alpha=alpha,
        ci_low=round(lo, 5), ci_high=round(hi, 5), ci_width=round(hi - lo, 5),
        excludes_zero=bool(lo > 0.0),
        small_sample=bool(min(pos.size, neg.size) < SMALL_SAMPLE_MIN_N),
        percentile_ci=[round(pct[0], 5), round(pct[1], 5)],
        n_boot=n_boot,
    )


def _analytic_n_per_group(pos: np.ndarray, neg: np.ndarray, alpha: float,
                          target_power: float) -> int | None:
    """Normal-approximation N-per-group so the one-sided lower CI clears zero at `target_power`.
    N = (z_{1-alpha/2} + z_power)^2 * (var_pos + var_neg) / delta^2. Cross-check only."""
    delta = separation(pos, neg)
    if delta <= 0:
        return None
    var = np.var(pos, ddof=1) + np.var(neg, ddof=1)
    if var == 0:
        return 1
    z = norm.ppf(1 - alpha / 2) + norm.ppf(target_power)
    return int(np.ceil(z * z * var / (delta * delta)))


def project_sample_size(pos: np.ndarray, neg: np.ndarray, *, scoring: str,
                        alpha: float = DEFAULT_ALPHA, target_power: float = DEFAULT_TARGET_POWER,
                        n_boot: int = DEFAULT_PROJECTION_NBOOT, n_sims: int = DEFAULT_PROJECTION_SIMS,
                        max_n: int = DEFAULT_MAX_N, ci_method: str = "bca",
                        rng: np.random.Generator | None = None) -> ProjectionResult:
    """Resampling-based projection of the per-group N needed to exclude zero.

    ASSUMPTIONS (documented, honest): (1) the observed valid samples are treated as the population
    for each group (plug-in bootstrap) — the true effect equals the observed effect, so this is a
    projection AT the observed effect size, not a hedge against a smaller true effect; (2) balanced
    collection (equal N per group); (3) the same bootstrap CI machinery used to report the decision
    is used to score each synthetic dataset, so the projected N is calibrated to the actual test,
    not an idealized one. Because the plug-in population is itself noisy at tiny N, read the number
    as an order-of-magnitude target that tightens as data accrues, and re-run after each batch
    (sequential collection) rather than trusting a single early estimate.
    """
    pos = np.asarray(pos, dtype=float)
    neg = np.asarray(neg, dtype=float)
    current_n = int(min(pos.size, neg.size))
    base = ProjectionResult(
        scoring=scoring, status="insufficient_data", current_n_per_group=current_n,
        target_power=target_power, method="nested-bootstrap plug-in Monte Carlo",
        assumptions="observed sample = population; balanced N; same CI test as the reported decision",
    )
    if pos.size < MIN_GROUP_FOR_CI or neg.size < MIN_GROUP_FOR_CI:
        base.note = f"need >= {MIN_GROUP_FOR_CI} valid trials per group to estimate an effect"
        return base
    if separation(pos, neg) <= 0:
        base.status = "insufficient_data"
        base.note = "observed separation <= 0 (distance scores >= touch): no positive effect to power for"
        return base

    rng = rng or np.random.default_rng(0)
    base.analytic_n_per_group = _analytic_n_per_group(pos, neg, alpha, target_power)

    # Already there? Check power at the current N first.
    def _power_at(n: int) -> float:
        hits = 0
        for _ in range(n_sims):
            sp = pos[rng.integers(0, pos.size, size=n)]
            sn = neg[rng.integers(0, neg.size, size=n)]
            reps = _bootstrap_separation_replicates(sp, sn, n_boot, rng)
            if ci_method == "percentile":
                lo, _ = _percentile_ci(reps, alpha)
            else:
                (lo, _), _ = _bca_ci(sp, sn, reps, separation(sp, sn), alpha)
            if lo > 0.0:
                hits += 1
        return hits / n_sims

    # Search a coarse grid upward, record the curve, stop at the first N meeting target.
    grid = sorted(set([current_n] + list(range(max(MIN_GROUP_FOR_CI, 4), max_n + 1, 4)) + [max_n]))
    grid = [n for n in grid if n >= MIN_GROUP_FOR_CI]
    curve: list[list[float]] = []
    projected: int | None = None
    for n in grid:
        p = round(_power_at(n), 4)
        curve.append([n, p])
        if projected is None and p >= target_power:
            projected = n
            # one more grid point above for context, then stop
            if n != grid[-1]:
                nxt = grid[grid.index(n) + 1]
                curve.append([nxt, round(_power_at(nxt), 4)])
            break
    base.power_curve = curve

    current_power = next((p for (n, p) in curve if n == current_n), None)
    if current_power is not None and current_power >= target_power:
        base.status = "already_significant"
        base.projected_n_per_group = current_n
        base.collect_more_per_group = 0
        base.note = f"current N={current_n} already reaches power {current_power:.2f} >= {target_power}"
        return base
    if projected is None:
        base.status = "unreached"
        base.note = f"target power {target_power} not reached by N={max_n} per group at the observed effect"
        return base
    base.status = "ok"
    base.projected_n_per_group = projected
    base.collect_more_per_group = max(0, projected - current_n)
    return base


# ========================================================================================
# Record helpers (reading the trial log the way summarize/sweep do)
# ========================================================================================
def load_trials(path: Path) -> list[dict]:
    """Load the trial log, de-duplicated by trial_id (last record wins).

    Each start_trial mints a fresh trial_id, so a repeated trial_id can only be a DOUBLE-LOGGED
    record (historically produced by the pre-lock upload-completion race in server.py). Counting
    such a record twice would inflate N and tighten the go/no-go CI toward a false GO, so the
    readers collapse duplicates defensively even though the server no longer creates them.
    Records without a trial_id are kept as-is (nothing to key on)."""
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    deduped: dict[str, dict] = {}
    out: list[dict] = []
    for r in records:
        tid = r.get("trial_id")
        if tid is None:
            out.append(r)
            continue
        if tid in deduped:
            out[deduped[tid]] = r  # replace the earlier copy in place (last wins, order preserved)
        else:
            deduped[tid] = len(out)
            out.append(r)
    return out


def current_feature_version() -> str:
    """The current pipeline generation (lazy import so the stats stay usable without the pipeline)."""
    try:
        from feature_extraction import FEATURE_VERSION
        return FEATURE_VERSION
    except Exception:
        return "unknown_generation"


def band_label(record: dict) -> str:
    bs = record.get("beep_spec") or {}
    lo, hi = bs.get("start_freq_hz"), bs.get("end_freq_hz")
    if lo is None or hi is None:
        return "unknown_band"
    return f"{round(lo / 1000)}-{round(hi / 1000)}kHz"


def condition_key(record: dict) -> str | None:
    """The condition a record belongs to, matching summarize_trials' grouping.

    A structured distance (touch|30cm|1m) is the key directly. The catch-all 'other' is NOT a
    condition — it is the UI's "type a custom label" option — so an 'other' record keys on its
    free-text condition_label (e.g. '2m-quiet', 'misconfig-aec'); this is what summarize_trials
    groups by, and it keeps two distinct 'other' campaigns from pooling into one bucket and lets
    `--negative 2m-quiet` actually match. 'other' with no label falls back to 'other'."""
    dist = record.get("condition_distance")
    if dist and dist != "other":
        return dist
    return record.get("condition_label") or dist


def gate_state(record: dict) -> str:
    """The link-test gate state stamped on a trial record (fix-plan §E1): 'passed' | 'failed' |
    'stale' | 'absent'. The gate admits a hardware tier; the campaign go/no-go is computed on
    gate-'passed' trials only (a trial collected under a failed, stale, or missing reciprocal-
    audibility gate is not tier-admitted data — the runbook §4/§5 says do not collect a sweep
    through a failing gate). The stamp is additive and never blocks collection, so non-passed
    trials still exist in the log and are itemized separately rather than silently counted.

    'stale' means the stamp is present and its own pass flag is true, but it was measured under a
    DIFFERENT hardware_tier/beep band than this trial (server marks `stale: true` when the session
    link test no longer matches the trial's tier/band). Such a stamp never gated THIS trial, so it
    is treated as not-passed rather than silently admitting the trial as gate-PASSED."""
    lt = record.get("link_test")
    if not lt or not lt.get("present"):
        return "absent"
    if lt.get("stale"):
        return "stale"
    return "passed" if lt.get("passed") else "failed"


def tier_of(record: dict) -> str:
    return record.get("hardware_tier") or "untiered"


def is_valid_record(record: dict) -> bool:
    if record.get("is_link_test"):
        return False
    if record.get("failure_reason"):
        return False
    pair = record.get("pair")
    if not pair or not pair.get("capture_valid"):
        return False
    score = record.get("score") or {}
    return score.get("c_a") is not None and score.get("c_b") is not None


def record_score(record: dict, scoring: str) -> float | None:
    score = record.get("score") or {}
    c_a, c_b = score.get("c_a"), score.get("c_b")
    if c_a is None or c_b is None:
        return None
    return trial_scores(float(c_a), float(c_b))[scoring]


def failure_breakdown(records: list[dict]) -> dict[str, int]:
    """Itemize REJECTED trials by failure reason (fix-plan E2: rejects are data about the tier).
    Counts every capture-invalid or logged-failed non-link-test record in `records`."""
    from collections import Counter
    counts: Counter = Counter()
    for r in records:
        if r.get("is_link_test"):
            continue
        if r.get("failure_reason"):
            counts["logged_failed"] += 1
            continue
        pair = r.get("pair")
        if not pair:
            counts["no_validity_assessment"] += 1
            continue
        if not pair.get("capture_valid"):
            for reason in (pair.get("failure_reasons") or ["capture_invalid_unspecified"]):
                counts[reason] += 1
    return dict(sorted(counts.items()))


def valid_scores(records: list[dict], condition_keys: set[str], scoring: str) -> np.ndarray:
    vals = [record_score(r, scoring) for r in records
            if is_valid_record(r) and condition_key(r) in condition_keys]
    return np.asarray([v for v in vals if v is not None], dtype=float)


# ========================================================================================
# One condition-pair report (both scorings) + band table
# ========================================================================================
def condition_pair_report(records: list[dict], *, positive: set[str], negative: set[str],
                          alpha: float = DEFAULT_ALPHA, target_power: float = DEFAULT_TARGET_POWER,
                          n_boot: int = DEFAULT_N_BOOT, seed: int = 0,
                          project: bool = True) -> dict:
    out: dict = {"positive": sorted(positive), "negative": sorted(negative), "scorings": {}}
    for scoring in SCORINGS:
        pos = valid_scores(records, positive, scoring)
        neg = valid_scores(records, negative, scoring)
        sep = analyze_separation(pos, neg, scoring=scoring, alpha=alpha, n_boot=n_boot,
                                 rng=np.random.default_rng(seed))
        entry = {"separation": sep.to_dict()}
        if project:
            proj = project_sample_size(pos, neg, scoring=scoring, alpha=alpha,
                                       target_power=target_power, rng=np.random.default_rng(seed + 1))
            entry["projection"] = proj.to_dict()
        out["scorings"][scoring] = entry
    return out


def band_separation_table(records: list[dict], *, positive: set[str], negative: set[str],
                          alpha: float = DEFAULT_ALPHA, n_boot: int = DEFAULT_N_BOOT,
                          seed: int = 0) -> dict:
    """Per-band separation (both scorings). The band decision (fix-plan E3) is by separation +
    CI, never absolute score. Bands with too few valid trials report insufficient_data."""
    from collections import defaultdict
    by_band: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_band[band_label(r)].append(r)
    table: dict = {}
    for band, recs in sorted(by_band.items()):
        band_entry = {}
        for scoring in SCORINGS:
            pos = valid_scores(recs, positive, scoring)
            neg = valid_scores(recs, negative, scoring)
            band_entry[scoring] = analyze_separation(
                pos, neg, scoring=scoring, alpha=alpha, n_boot=n_boot,
                rng=np.random.default_rng(seed)).to_dict()
        table[band] = band_entry
    return table


# ========================================================================================
# CLI
# ========================================================================================
def _cmd_report(args) -> int:
    if not args.trials or not args.trials.exists():
        raise SystemExit(f"missing trial log: {args.trials}")
    records = load_trials(args.trials)
    versions = set(args.feature_versions) if args.feature_versions else {current_feature_version()}
    records = [r for r in records if r.get("feature_version") in versions]
    if args.tiers:
        wanted = set(args.tiers)
        records = [r for r in records if tier_of(r) in wanted]

    # Go/no-go is on link-test-gate-PASSED trials only (fix-plan §E1), matching campaign_status. A
    # failed/absent-gate trial is not tier-admitted data. --include-ungated opts out for diagnostics.
    gate_counts = {"passed": 0, "failed": 0, "stale": 0, "absent": 0}
    for r in records:
        if is_valid_record(r):
            gate_counts[gate_state(r)] += 1
    if not args.include_ungated:
        records = [r for r in records if gate_state(r) == "passed"]

    report = condition_pair_report(
        records, positive=set(args.positive), negative=set(args.negative),
        alpha=args.alpha, target_power=args.target_power, n_boot=args.n_boot, seed=args.seed,
    )
    report["bands"] = band_separation_table(
        records, positive=set(args.positive), negative=set(args.negative),
        alpha=args.alpha, n_boot=args.n_boot, seed=args.seed)
    report["rejected_trials"] = failure_breakdown(records)
    report["feature_versions"] = sorted(versions)
    report["tiers"] = sorted(args.tiers) if args.tiers else "all"
    report["gate"] = {
        "counted": "all_valid" if args.include_ungated else "gate_passed_only",
        "valid_by_gate_state": gate_counts,
    }
    print(json.dumps(report, indent=2))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("trials", type=Path, help="trial log")
    p.add_argument("--positive", nargs="+", default=["touch"], help="condition key(s) = proximity positive")
    p.add_argument("--negative", nargs="+", default=["30cm", "1m"], help="condition key(s) = distance negative")
    p.add_argument("--tier", action="append", dest="tiers", help="hardware tier(s) to include (repeatable)")
    p.add_argument("--feature-version", action="append", dest="feature_versions",
                   help=f"generation(s) (repeatable). Default: current ({current_feature_version()}).")
    p.add_argument("--alpha", type=float, default=DEFAULT_ALPHA)
    p.add_argument("--n-boot", type=int, default=DEFAULT_N_BOOT)
    p.add_argument("--target-power", type=float, default=DEFAULT_TARGET_POWER)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--json", action="store_true", help="(default output is already JSON)")
    p.add_argument("--include-ungated", action="store_true",
                   help="also count trials collected under a failed/absent link-test gate "
                        "(default: gate-passed only, matching campaign_status)")
    args = p.parse_args()

    return _cmd_report(args)


if __name__ == "__main__":
    raise SystemExit(main())
