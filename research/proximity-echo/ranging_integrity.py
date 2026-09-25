"""Content diagnostics for complete, original-rate mono PCM recordings.

Exact-zero and constant-nonzero spans are observations, not proof of dropped
capture time. Quiet recordings, digital silence between synthetic probes and
edge padding can contain the same values. Callers must assess probe overlap and
independent timing evidence separately, without changing the recording or
attributing a hardware, driver, operating-system or browser cause.
"""

from __future__ import annotations

import math

import numpy as np


def _positive_number(value, name):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return number


def _context(samples, start, end):
    window = samples[start:end]
    finite = window[np.isfinite(window)]
    peak = float(np.max(np.abs(finite), initial=0.0))
    # Scaling also keeps diagnostics JSON-safe for malformed, very large PCM.
    rms = float(peak * np.sqrt(np.mean((finite / peak) ** 2))) if peak else 0.0
    return {
        "start_frame": int(start),
        "end_frame_exclusive": int(end),
        "frame_count": int(len(window)),
        "finite_frame_count": int(len(finite)),
        "exact_zero_frame_count": int(np.count_nonzero(finite == 0)),
        "rms": rms,
        "peak_abs": peak,
        "varies": bool(len(finite) > 1 and np.any(finite[1:] != finite[0])),
    }


def scan_pcm_integrity(samples, sample_rate, *, minimum_span_ms=1.0,
                       context_ms=5.0, max_spans=64):
    """Return bounded JSON-safe diagnostics without an acceptance decision.

    Pass decoded mono PCM before replacement of nonfinite values, filtering or
    resampling. Equality is exact. No amplitude threshold turns quiet nonzero
    noise into silence. Nonfinite samples break runs and are counted separately.
    Run lengths use at least two samples and ceil(rate * minimum_span_ms / 1000),
    so all reported runs meet the nominal duration threshold.

    The full recording is scanned even when ``max_spans`` limits the detail.
    Retention favors internal spans, then longer spans, with frame order as the
    tie breaker. Returned details are in frame order. Counts and total durations
    include omitted spans; callers must not assume a truncated list is complete.

    Context variation identifies an observed change in the PCM around a span,
    not its cause. Neither this evidence nor exact silence alone establishes a
    dropout. This function intentionally has no ``usable`` or rejection fields.
    """
    rate = _positive_number(sample_rate, "sample_rate")
    minimum_ms = _positive_number(minimum_span_ms, "minimum_span_ms")
    context_duration_ms = _positive_number(context_ms, "context_ms")
    if isinstance(max_spans, (bool, np.bool_)) or not isinstance(max_spans, (int, np.integer)) or max_spans < 1:
        raise ValueError("max_spans must be a positive integer")
    values = np.asarray(samples)
    if values.ndim != 1 or np.iscomplexobj(values):
        raise ValueError("samples must be a one-dimensional real mono PCM array")
    values = np.asarray(values, dtype=np.float64)
    minimum_frames = max(2, math.ceil(rate * minimum_ms / 1000.0))
    context_frames = max(1, math.ceil(rate * context_duration_ms / 1000.0))
    frames = len(values)
    finite_mask = np.isfinite(values)
    exact_zero_frames = int(np.count_nonzero(values == 0))

    # Nonfinite samples never join a finite run. Repeated infinities can form a
    # provisional run here but are excluded before counting or reporting it.
    boundaries = np.r_[0, np.flatnonzero(values[1:] != values[:-1]) + 1, frames]
    starts, ends = boundaries[:-1], boundaries[1:]
    lengths = ends - starts
    if frames:
        run_values = values[starts]
        finite_runs = np.isfinite(run_values)
        zero_runs = finite_runs & (run_values == 0)
        nonzero_runs = finite_runs & (run_values != 0)
        longest_zero = int(np.max(lengths[zero_runs], initial=0))
        longest_nonzero = int(np.max(lengths[nonzero_runs], initial=0))
        sustained = np.flatnonzero(finite_runs & (lengths >= minimum_frames))
    else:
        run_values = np.empty(0)
        longest_zero = longest_nonzero = 0
        sustained = np.empty(0, dtype=np.int64)

    span_counts = {"exact_zero": 0, "constant_nonzero": 0}
    internal_counts = dict(span_counts)
    frame_counts = dict(span_counts)
    for index in sustained:
        kind = "exact_zero" if run_values[index] == 0 else "constant_nonzero"
        span_counts[kind] += 1
        internal_counts[kind] += int(starts[index] > 0 and ends[index] < frames)
        frame_counts[kind] += int(lengths[index])

    # Sorting qualifying runs, rather than retaining the first ones encountered,
    # allows a late internal anomaly to survive abundant early edge padding.
    retained = sorted(sustained, key=lambda index: (
        not (starts[index] > 0 and ends[index] < frames),
        -int(lengths[index]), int(starts[index]),
    ))[:max_spans]
    spans = []
    for index in sorted(retained, key=lambda index: int(starts[index])):
        start, end = int(starts[index]), int(ends[index])
        if start == 0 and end == frames:
            position = "whole_recording"
        elif start == 0:
            position = "leading"
        elif end == frames:
            position = "trailing"
        else:
            position = "internal"
        before = _context(values, max(0, start - context_frames), start)
        after = _context(values, end, min(frames, end + context_frames))
        spans.append({
            "kind": "exact_zero" if run_values[index] == 0 else "constant_nonzero",
            "start_frame": start,
            "end_frame_exclusive": end,
            "frame_count": end - start,
            "start_s": start / rate,
            "end_s": end / rate,
            "duration_ms": (end - start) * 1000.0 / rate,
            "value": float(run_values[index]),
            "position": position,
            "context_before": before,
            "context_after": after,
            "flanked_by_varying_pcm": bool(
                position == "internal" and before["varies"] and after["varies"]
                and before["finite_frame_count"] == before["frame_count"]
                and after["finite_frame_count"] == after["frame_count"]
            ),
        })

    total_sustained_frames = sum(frame_counts.values())
    return {
        "scope": "original_pcm_entire_recording",
        "assessment": "diagnostic_only",
        "sample_rate_hz": rate,
        "frames_scanned": frames,
        "minimum_span_ms": minimum_ms,
        "minimum_span_frames": minimum_frames,
        "context_ms": context_duration_ms,
        "nonfinite_sample_count": int(frames - np.count_nonzero(finite_mask)),
        "exact_zero_sample_count": exact_zero_frames,
        "all_exact_zero": bool(frames and exact_zero_frames == frames),
        "longest_exact_zero_run_frames": longest_zero,
        "longest_constant_nonzero_run_frames": longest_nonzero,
        "span_count": int(len(sustained)),
        "span_counts": span_counts,
        "internal_span_counts": internal_counts,
        "sustained_frame_counts": frame_counts,
        "sustained_frames": total_sustained_frames,
        "sustained_duration_ms": total_sustained_frames * 1000.0 / rate,
        "max_reported_spans": int(max_spans),
        "omitted_span_count": int(len(sustained) - len(spans)),
        "spans_truncated": bool(len(sustained) > len(spans)),
        "span_retention": "internal_first_then_longest_returned_in_frame_order",
        "spans": spans,
        "interpretation": (
            "Exact-zero or constant PCM alone does not establish missing capture time. "
            "Assess probe overlap and independent timing evidence separately. "
            "These samples do not identify the component responsible."
        ),
    }
