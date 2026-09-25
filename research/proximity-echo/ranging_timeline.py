"""Timeline-discontinuity candidates and segmented timing evaluation.

A recording whose driver delivered zero-filled or near-silent buffers keeps
perfectly contiguous worklet block counters: ``currentFrame`` advances whether or
not the buffer carried captured sound. The PCM is therefore the only first-party
evidence of a timeline discontinuity, and it is still only *evidence*: exact
silence, a muted source and digital padding produce identical samples.

Nothing here repairs, stitches or shifts a recording. Candidates are observations
with declared thresholds; segmentation only refuses to fit one clock model across
a suspected break, and every arrival that falls outside a stable interval is
reported rather than dropped.

Limits, stated plainly: true *sample loss* (frames removed rather than zeroed)
leaves no silent span and produces no candidate here. Only the existing clock
step check can notice that, and it cannot localize it in the PCM.
"""

from __future__ import annotations

import math

import numpy as np

from ranging_integrity import _context


# Worklet capture quantum is 128 frames (2.67 ms at 48 kHz). Benign exact-zero
# spans around 1 ms are documented in docs/2026-09-22-playback-routing-captures.md
# and a single dropped quantum is not separable from ordinary digital silence.
# Three quanta (8 ms at 48 kHz) sits above both, and far below the 20 ms and
# 60 ms spans that accompany the observed timeline jumps.
TIMELINE_GAP_MIN_MS = 8.0

# A dropout that is not bit-exact zero (dither, DC offset, a decaying tail) is
# still a dropout if the level collapses far below the recording's own noise.
# Five percent of the MAD noise floor is ~26 dB below background: no ordinary
# quiet passage in these captures reaches it, while a synthetic 1e-4 floor does.
TIMELINE_NEAR_SILENT_FRACTION = 0.05

# The clock step check locates a break at the midpoint between two consecutive
# emission arrivals, so it cannot resolve position better than the ~1 s emission
# spacing. Corroboration therefore requires only that the candidate lie in the
# same inter-emission interval as the fitted boundary (checked on that
# recording's own time axis), not at a particular sample.
TIMELINE_STEP_BOUNDARY_TOLERANCE_S = 1.0

# Fitted step magnitude versus candidate duration. Detector precision is one
# sample plus multipath bias, and the step is an average over several emissions,
# so a quarter-relative band with a 1 ms floor is the declared agreement window.
TIMELINE_STEP_MAGNITUDE_TOLERANCE = 0.25
TIMELINE_STEP_MAGNITUDE_FLOOR_MS = 1.0

TIMELINE_POLICIES = ("global", "segmented")

TIMELINE_DEFAULTS = {
    "timeline_policy": "global",
    "timeline_gap_min_ms": TIMELINE_GAP_MIN_MS,
    "timeline_near_silent_fraction": TIMELINE_NEAR_SILENT_FRACTION,
    "timeline_step_boundary_tolerance_s": TIMELINE_STEP_BOUNDARY_TOLERANCE_S,
    "timeline_step_magnitude_tolerance": TIMELINE_STEP_MAGNITUDE_TOLERANCE,
}

CANDIDATE_SEMANTICS = (
    "Observed signal-content discontinuity candidate. Silent or near-silent PCM "
    "flanked by varying sound is consistent with buffers delivered without "
    "captured audio, but does not establish missing capture time, and does not "
    "identify the responsible component. Worklet block counters cannot confirm or "
    "refute it: they advance regardless."
)


def _finite_positive(value, name):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return number


def timeline_settings(config):
    """Validate the timeline keys of a config without touching other settings."""
    supplied = config or {}
    settings = dict(TIMELINE_DEFAULTS)
    policy = supplied.get("timeline_policy", settings["timeline_policy"])
    if policy not in TIMELINE_POLICIES:
        raise ValueError(f"timeline_policy must be one of {TIMELINE_POLICIES}")
    settings["timeline_policy"] = policy
    for key in ("timeline_gap_min_ms", "timeline_near_silent_fraction",
                "timeline_step_boundary_tolerance_s", "timeline_step_magnitude_tolerance"):
        if key in supplied:
            settings[key] = _finite_positive(supplied[key], key)
    if not 0 < settings["timeline_near_silent_fraction"] < 1:
        raise ValueError("timeline_near_silent_fraction must lie strictly between zero and one")
    return settings


def _runs(mask, minimum_frames):
    edges = np.flatnonzero(np.diff(np.r_[False, mask.astype(bool), False]))
    starts, ends = edges[::2], edges[1::2]
    keep = (ends - starts) >= minimum_frames
    return list(zip(starts[keep].tolist(), ends[keep].tolist()))


def _candidate(values, start, end, rate, kind, context_frames, confidence, extra=None):
    frames = len(values)
    before = _context(values, max(0, start - context_frames), start)
    after = _context(values, end, min(frames, end + context_frames))
    flanked = bool(
        start > 0 and end < frames and before["varies"] and after["varies"]
        and before["finite_frame_count"] == before["frame_count"]
        and after["finite_frame_count"] == after["frame_count"]
    )
    row = {
        "kind": kind,
        "confidence": confidence,
        "start_frame": int(start),
        "end_frame_exclusive": int(end),
        "frame_count": int(end - start),
        "start_s": start / rate,
        "end_s": end / rate,
        "duration_s": (end - start) / rate,
        "duration_ms": (end - start) * 1000.0 / rate,
        "position": "internal" if (start > 0 and end < frames) else "edge",
        "flanked_by_varying_pcm": flanked,
        "context_before": before,
        "context_after": after,
        "semantics": CANDIDATE_SEMANTICS,
    }
    row.update(extra or {})
    return row


def timeline_candidates(samples, sample_rate, *, minimum_gap_ms=TIMELINE_GAP_MIN_MS,
                        near_silent_fraction=TIMELINE_NEAR_SILENT_FRACTION,
                        context_ms=5.0, max_candidates=32):
    """Return internal silent / near-silent spans long enough to matter.

    ``exact_zero`` and ``constant_nonzero`` candidates repeat the bit-exact runs
    that :func:`ranging_integrity.scan_pcm_integrity` already observes, filtered
    to internal spans that are at least ``minimum_gap_ms`` long and flanked by
    varying PCM. ``near_silent_span`` candidates additionally catch collapses to
    a small fraction of the recording's own MAD noise floor; they carry lower
    confidence because a genuine quiet passage can look the same.
    """
    rate = _finite_positive(sample_rate, "sample_rate")
    minimum_ms = _finite_positive(minimum_gap_ms, "minimum_gap_ms")
    values = np.asarray(samples, dtype=np.float64)
    if values.ndim != 1:
        raise ValueError("samples must be a one-dimensional real mono PCM array")
    minimum_frames = max(2, math.ceil(rate * minimum_ms / 1000.0))
    context_frames = max(1, math.ceil(rate * context_ms / 1000.0))
    finite = values[np.isfinite(values)]
    median = float(np.median(finite)) if len(finite) else 0.0
    noise_floor = float(1.4826 * np.median(np.abs(finite - median))) if len(finite) else 0.0
    quiet_threshold = noise_floor * float(near_silent_fraction)

    candidates = []
    # Bit-exact constant runs, including exact zero.
    boundaries = np.r_[0, np.flatnonzero(values[1:] != values[:-1]) + 1, len(values)]
    for start, end in zip(boundaries[:-1].tolist(), boundaries[1:].tolist()):
        if end - start < minimum_frames or not np.isfinite(values[start]):
            continue
        kind = "exact_zero" if values[start] == 0 else "constant_nonzero"
        candidates.append(_candidate(values, start, end, rate, kind, context_frames,
                                     "observed_bit_exact_constant_pcm",
                                     {"value": float(values[start])}))
    covered = [(row["start_frame"], row["end_frame_exclusive"]) for row in candidates]
    if quiet_threshold > 0:
        quiet = np.isfinite(values) & (np.abs(values) < quiet_threshold)
        for start, end in _runs(quiet, minimum_frames):
            if any(start < right and left < end for left, right in covered):
                continue
            candidates.append(_candidate(values, start, end, rate, "near_silent_span",
                                         context_frames, "amplitude_threshold_relative_to_noise_floor",
                                         {"threshold_abs": quiet_threshold,
                                          "max_abs_in_span": float(np.max(np.abs(values[start:end]), initial=0.0))}))
    candidates = [row for row in candidates if row["position"] == "internal" and row["flanked_by_varying_pcm"]]
    candidates.sort(key=lambda row: row["start_frame"])
    truncated = len(candidates) > max_candidates
    if truncated:
        keep = sorted(sorted(candidates, key=lambda row: -row["frame_count"])[:max_candidates],
                      key=lambda row: row["start_frame"])
    else:
        keep = candidates
    return {
        "assessment": "diagnostic_only",
        "sample_rate_hz": rate,
        "frames_scanned": int(len(values)),
        "minimum_gap_ms": minimum_ms,
        "minimum_gap_frames": minimum_frames,
        "noise_floor_mad": noise_floor,
        "near_silent_fraction": float(near_silent_fraction),
        "near_silent_threshold_abs": quiet_threshold,
        "candidate_count": len(candidates),
        "candidates_truncated": truncated,
        "candidates": keep,
        "semantics": CANDIDATE_SEMANTICS,
    }


def corroborate(step_check, rows, candidates_by_role, settings=None):
    """Check whether the fitted clock step coincides with a PCM candidate.

    ``rows`` are the clock-fit rows (``a_s``/``b_s`` in each recording's own time
    axis). The step boundary is expressed on the A axis; it is mapped onto the B
    axis through the pair of rows it separates, so no rate or intercept model is
    needed and no sample time is altered.
    """
    settings = settings or dict(TIMELINE_DEFAULTS)
    result = {"corroborated": False, "step_check": step_check, "matches": [],
              "reasons": [],
              "semantics": ("Agreement between an independent PCM observation and the "
                            "timing step model. Neither piece of evidence alone establishes "
                            "lost capture time, and agreement does not identify a cause.")}
    if not step_check:
        result["reasons"].append("no_clock_step_candidate")
        return result
    if not rows:
        result["reasons"].append("no_clock_fit_rows")
        return result
    boundary = float(step_check["after_a_s"])
    step_ms = abs(float(step_check["step_ms"]))
    ordered = sorted(rows, key=lambda row: row["a_s"])
    before = [row for row in ordered if row["a_s"] <= boundary]
    after = [row for row in ordered if row["a_s"] > boundary]
    if not before or not after:
        result["reasons"].append("clock_step_boundary_outside_row_range")
        return result
    axis_bounds = {"A": (before[-1]["a_s"], after[0]["a_s"]),
                   "B": (before[-1]["b_s"], after[0]["b_s"])}
    tolerance = settings["timeline_step_boundary_tolerance_s"]
    magnitude_tolerance = settings["timeline_step_magnitude_tolerance"]
    for role, block in candidates_by_role.items():
        low, high = axis_bounds[role]
        for candidate in block.get("candidates", []):
            mid = (candidate["start_s"] + candidate["end_s"]) / 2
            in_interval = bool(low - tolerance <= mid <= high + tolerance)
            duration_ms = candidate["duration_ms"]
            allowed = max(magnitude_tolerance * max(duration_ms, step_ms),
                          TIMELINE_STEP_MAGNITUDE_FLOOR_MS)
            magnitude_agrees = bool(abs(step_ms - duration_ms) <= allowed)
            match = {
                "recording": role, "kind": candidate["kind"],
                "start_s": candidate["start_s"], "end_s": candidate["end_s"],
                "duration_ms": duration_ms,
                "step_ms": float(step_check["step_ms"]),
                "step_boundary_a_s": boundary,
                "enclosing_arrival_interval_s": [float(low), float(high)],
                "boundary_tolerance_s": tolerance,
                "magnitude_difference_ms": abs(step_ms - duration_ms),
                "magnitude_allowance_ms": allowed,
                "boundary_agrees": in_interval,
                "magnitude_agrees": magnitude_agrees,
                "corroborated": bool(in_interval and magnitude_agrees),
                "sse_reduction_fraction": step_check.get("sse_reduction_fraction"),
            }
            result["matches"].append(match)
    result["corroborated"] = any(match["corroborated"] for match in result["matches"])
    if not result["matches"]:
        result["reasons"].append("no_pcm_candidate_to_compare")
    elif not result["corroborated"]:
        result["reasons"].append("clock_step_not_corroborated_by_pcm_candidate")
    return result


def _cuts(candidates_by_role):
    """Flatten candidates from both recordings into ordered cut descriptors."""
    cuts = []
    for role, block in sorted(candidates_by_role.items()):
        for candidate in block.get("candidates", []):
            cuts.append({"recording": role, "kind": candidate["kind"],
                         "start_s": candidate["start_s"], "end_s": candidate["end_s"],
                         "duration_ms": candidate["duration_ms"]})
    cuts.sort(key=lambda cut: (cut["start_s"], cut["recording"]))
    return cuts


def _row_axis(row, role):
    return row["a_s"] if role == "A" else row["b_s"]


def _project_cut(cut, ordered):
    """Map one cut onto the A-ordered row sequence, without any rate model.

    Returns ``(boundary_index, inside_positions, detail)``. ``boundary_index`` is
    a position ``k`` in ``0..len(ordered)``: rows before ``k`` precede the cut and
    rows from ``k`` follow it. The cut is read on its own recording's axis, and it
    is bracketed exactly as :func:`corroborate` maps a boundary between axes: a
    B-axis cut at ``t_B`` lies "between row i and row i+1" when ``b_s[i]`` is at or
    before the span and ``b_s[i+1]`` at or after it. Rows whose own-axis arrival
    falls inside the span are excluded from bracketing and reported separately.
    A cut before the first row or after the last one splits at that end (a no-op).
    ``boundary_index`` is ``None`` when the bracket is not unique, which happens
    only when the cut's axis is not monotonic across the row sequence; the caller
    refuses segmentation rather than guessing which pair the cut belongs between.
    """
    role, start, end = cut["recording"], cut["start_s"], cut["end_s"]
    values = [_row_axis(row, role) for row in ordered]
    inside = [index for index, value in enumerate(values) if start < value < end]
    kept = [(index, value) for index, value in enumerate(values) if index not in set(inside)]
    candidates = set()
    for (_, before), (position, after) in zip(kept, kept[1:]):
        if before <= start and after >= end:
            candidates.add(position)
    if not kept:
        candidates.add(0)
    else:
        if all(value >= end for _, value in kept):
            candidates.add(0)
        if all(value <= start for _, value in kept):
            candidates.add(len(values))
    boundary = candidates.pop() if len(candidates) == 1 else None
    detail = {"recording": role, "kind": cut["kind"], "start_s": start, "end_s": end,
              "axis_projected_onto": "A_row_sequence",
              "boundary_row_index": boundary,
              "candidate_boundary_indices": sorted(candidates) if boundary is None else [boundary],
              "rows_inside_span": [ordered[index]["emission_id"] for index in inside],
              "unique_bracket": boundary is not None}
    return boundary, inside, detail


def assign_segments(rows, cuts):
    """Assign each clock-fit row to a stable interval between cuts.

    A cut in either recording splits both, because the two axes describe the same
    physical exchange sequence. Every cut is therefore projected onto one axis --
    the rows ordered by ``a_s`` -- through the pair of emissions that brackets it
    on its own axis, so cuts from the two recordings are ordered by the emissions
    they separate rather than by raw seconds on two unrelated clocks. A row whose
    arrival lies inside a cut span is not assigned to any segment; it is reported,
    never silently dropped.

    Returns ``(assignments, projections, reasons)``. ``reasons`` is non-empty only
    when a cut cannot be placed between a unique pair of emissions; segmentation
    is then refused outright instead of guessing a grouping.
    """
    ordered = sorted(rows, key=lambda row: row["a_s"])
    boundaries, projections, reasons = [], [], []
    inside_by_position = {}
    for cut in cuts:
        boundary, inside, detail = _project_cut(cut, ordered)
        projections.append(detail)
        for index in inside:
            inside_by_position.setdefault(index, cut)
        if boundary is None:
            reason = ("timeline_cuts_interleave_across_axes"
                      if len({item["recording"] for item in cuts}) > 1
                      else "timeline_cut_projection_ambiguous")
            reasons.append(f"{reason}:{cut['recording']}:{cut['start_s']:.6f}s")
            continue
        if 0 < boundary < len(ordered):
            boundaries.append(boundary)
    reasons = list(dict.fromkeys(reasons))
    if reasons:
        return [], projections, reasons
    boundaries = sorted(set(boundaries))
    assignments = []
    for position, row in enumerate(ordered):
        inside = inside_by_position.get(position)
        index = sum(1 for boundary in boundaries if boundary <= position)
        assignments.append({"emission_id": row["emission_id"],
                            "segment_index": None if inside else index,
                            "inside_candidate": inside})
    return assignments, projections, reasons


def evaluate_timeline(arrivals, emissions, settings, recording_reports, fit_clock, build_exchanges,
                      *, timeline=None):
    """Compute candidates, corroboration, segments and (optionally) segmented results.

    ``fit_clock``/``build_exchanges`` are ``ranging_analysis._fit_clock`` and
    ``._exchanges``; the fitting mathematics is reused unchanged on subsets of the
    emission list. Returns ``(clock, exchanges, timeline_block, extra_reasons)``.
    Under the ``global`` policy the returned clock and exchanges are exactly the
    unsegmented ones and the timeline block is reported but not used.
    """
    options = dict(TIMELINE_DEFAULTS)
    options.update(timeline or {})
    candidates_by_role = {
        role: report.get("timeline_candidates") or {"candidates": []}
        for role, report in recording_reports.items()
    }
    global_clock = fit_clock(arrivals, emissions, settings)
    global_exchanges = build_exchanges(arrivals, emissions, global_clock, settings)
    corroboration = corroborate(global_clock.get("step_check"), global_clock.get("rows", []),
                                candidates_by_role, options)
    cuts = _cuts(candidates_by_role)
    assignments, projections, segmentation_reasons = assign_segments(global_clock.get("rows", []), cuts)
    by_index = {}
    outside = []
    for item in assignments:
        if item["segment_index"] is None:
            outside.append({"emission_id": item["emission_id"],
                            "reason": "outside_stable_timing_interval",
                            "inside_candidate": item["inside_candidate"]})
        else:
            by_index.setdefault(item["segment_index"], []).append(item["emission_id"])
    if segmentation_reasons:
        outside = [{"emission_id": row["emission_id"],
                    "reason": "timeline_segmentation_refused",
                    "inside_candidate": None} for row in global_clock.get("rows", [])]

    emission_by_id = {emission["id"]: emission for emission in emissions}
    segments = []
    for index in sorted(by_index):
        ids = by_index[index]
        subset = [emission_by_id[identifier] for identifier in ids]
        clock = fit_clock(arrivals, subset, settings)
        pairs = {}
        for emission in subset:
            pairs.setdefault(emission["pair_index"], set()).add(emission["emitter"])
        complete = sorted(key for key, roles in pairs.items() if roles == {"A", "B"})
        pair_emissions = [emission for emission in subset if emission["pair_index"] in complete]
        exchanges = build_exchanges(arrivals, pair_emissions, clock, settings) if pair_emissions else []
        usable = [item for item in exchanges if item["usable"]]
        segments.append({
            "segment_index": index,
            "emission_ids": ids,
            "usable_emissions": clock["used_emissions"],
            "valid": clock["valid"],
            "reasons": clock["reasons"],
            "max_abs_residual_ms": clock["max_abs_residual_ms"],
            "residual_ms": clock["residual_ms"],
            "relative_rate_ppm": clock["relative_rate_ppm"],
            "clock_fit": clock,
            "exchanges": exchanges,
            "usable_exchanges": len(usable),
            "excluded_pair_indices": sorted(set(pairs) - set(complete)),
            "peak_consistency": peak_consistency(arrivals, ids),
            "evidence": ("sufficient_segment_evidence" if clock["used_emissions"]
                         and "insufficient_independent_emissions_for_clock_fit" not in clock["reasons"]
                         and "insufficient_time_span_for_clock_fit" not in clock["reasons"]
                         else "insufficient_segment_evidence"),
        })
    for segment in segments:
        if segment["evidence"] == "insufficient_segment_evidence":
            segment["reasons"] = list(dict.fromkeys(segment["reasons"] + ["insufficient_segment_evidence"]))

    detected = bool(cuts)
    block = {
        "policy": options["timeline_policy"],
        "settings": {key: options[key] for key in TIMELINE_DEFAULTS},
        "candidates": {role: candidates_by_role[role] for role in sorted(candidates_by_role)},
        "candidate_count": len(cuts),
        "cuts": cuts,
        "cut_projections": projections,
        "segmentation_refused": bool(segmentation_reasons),
        "segmentation_refusal_reasons": segmentation_reasons,
        "corroboration": corroboration,
        "discontinuity_detected": detected,
        "segments": segments,
        "segment_count": len(segments),
        "arrivals_outside_segments": outside,
        "global_clock_fit": {key: global_clock[key] for key in
                             ("valid", "used_emissions", "max_abs_residual_ms", "relative_rate_ppm", "reasons")},
        "semantics": ("Segmentation refuses one clock model across a suspected break. It does not "
                      "stitch, shift or repair samples, and a segment result is still diagnostic. "
                      "True sample loss without a silent span produces no candidate here."),
    }

    extra_reasons = list(segmentation_reasons)
    for cut in cuts:
        extra_reasons.append(
            f"timeline_discontinuity_detected:{cut['recording']}:{cut['start_s']:.6f}s:"
            f"{cut['duration_ms']:.3f}ms:{cut['kind']}")
    if options["timeline_policy"] == "global":
        return global_clock, global_exchanges, block, []

    if not segments:
        clock = dict(global_clock)
        clock["valid"] = False
        clock["reasons"] = list(dict.fromkeys(clock["reasons"] + ["no_stable_timing_interval_available"]))
        clock["segments"] = []
        return clock, build_exchanges(arrivals, emissions, clock, settings), block, extra_reasons

    usable_counts = [segment["usable_exchanges"] for segment in segments]
    best = max(range(len(segments)), key=lambda i: (segments[i]["valid"], usable_counts[i],
                                                    segments[i]["usable_emissions"]))
    chosen = segments[best]
    clock = dict(chosen["clock_fit"])
    clock["segments"] = [{key: segment[key] for key in
                          ("segment_index", "emission_ids", "usable_emissions", "valid", "reasons",
                           "max_abs_residual_ms", "residual_ms", "relative_rate_ppm",
                           "usable_exchanges", "evidence", "excluded_pair_indices", "peak_consistency")}
                         for segment in segments]
    clock["segmented"] = True
    clock["selected_segment_index"] = chosen["segment_index"]
    clock["segment_selection_rule"] = "largest_valid_stable_interval_by_usable_exchanges"
    clock["reasons"] = list(dict.fromkeys(clock["reasons"] + extra_reasons))
    clock["valid"] = bool(chosen["valid"])

    by_pair = {item["pair_index"]: item for item in chosen["exchanges"]}
    exchanges = []
    for item in global_exchanges:
        index = item["pair_index"]
        if index in by_pair:
            exchanges.append({**by_pair[index], "segment_index": chosen["segment_index"]})
            continue
        replacement = {**item, "usable": False, "segment_index": None,
                       "delta_a_s": None, "delta_b_s": None, "delta_b_in_a_seconds": None,
                       "timing_difference_s": None, "uncorrected_equivalent_m": None,
                       "acoustic_cross_path_m": None}
        replacement["reasons"] = list(dict.fromkeys(list(item["reasons"]) + ["pair_outside_selected_stable_interval"]))
        exchanges.append(replacement)
    return clock, exchanges, block, extra_reasons


def peak_consistency(arrivals, emission_ids=None):
    """Report-only peak-family audit: selected-versus-strongest detector lags.

    Uses ``arrivals[i]["detector"]["selected_relative_to_strongest_samples"]``
    when the published BeepBeep detector produced it. No selection is changed.
    """
    selected = set(emission_ids) if emission_ids is not None else None
    paths = {}
    for arrival in arrivals:
        if selected is not None and arrival.get("emission_id") not in selected:
            continue
        detector = arrival.get("detector")
        if not isinstance(detector, dict):
            continue
        lag = detector.get("selected_relative_to_strongest_samples")
        if lag is None:
            continue
        path = f"{arrival.get('emitter')}{arrival.get('receiver')}"
        entry = paths.setdefault(path, {"lags": [], "emission_ids": []})
        entry["lags"].append(int(lag))
        entry["emission_ids"].append(arrival.get("emission_id"))
    result = {}
    for path, entry in sorted(paths.items()):
        lags = entry["lags"]
        histogram = {}
        for lag in lags:
            histogram[str(lag)] = histogram.get(str(lag), 0) + 1
        switches = sum(1 for left, right in zip(lags, lags[1:]) if left != right)
        result[path] = {
            "count": len(lags),
            "peak_family_switches": switches,
            "distinct_lags": len(histogram),
            "lag_histogram_samples": histogram,
            "non_strongest_selections": sum(1 for lag in lags if lag != 0),
            "emission_ids": entry["emission_ids"],
            "lags": lags,
        }
    return {
        "paths": result,
        "semantics": ("Selected-minus-strongest correlation peak offsets, in samples, per "
                      "emitter-receiver path. Report only: a switch means the published "
                      "sharpness rule changed which lobe it accepted, not that either lobe "
                      "is the direct acoustic path."),
    }
