"""Independent four-arrival acoustic timing diagnostics.

This module never imports the echo alignment/score pipeline. It matches the exact
session templates over each complete recording, before looking at exchange pairs.
WAV rates are *nominal* sample rates. Relative rate is estimated from arrivals;
the common absolute clock scale and physical detector biases remain uncalibrated.

``analyze_ranging({"A": {"wav_path": ..., "metadata": ...}, "B": ...}, protocol)``
returns a JSON-safe report. Ground-truth labels are intentionally not inputs to
the estimator. Optional ``config["self_path_m"]`` contains independent measured
self paths, not a body-gap label. No proximity verdict is implemented here.
"""

from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from scipy import signal

from ranging_peaks import close_peak_diagnostics
from ranging_protocol import decode_template
from ranging_integrity import scan_pcm_integrity
from ranging_timeline import TIMELINE_DEFAULTS, evaluate_timeline, timeline_candidates, timeline_settings


ANALYSIS_VERSION = "four-arrival-diagnostic-v2"
DEFAULTS = {
    "speed_of_sound_m_s": 343.0,
    "min_normalized_correlation": 0.40,
    "min_noise_ratio": 8.0,
    "candidate_separation_ms": 0.60,
    "close_peak_profile_radius_ms": 1.0,
    "close_peak_reference_tolerance": 0.08,
    "max_echo_span_ms": 120.0,
    "max_candidates": 12,
    "clock_residual_limit_ms": 0.15,
    "minimum_emissions_per_direction": 3,
    "profile_bins": 1024,
}

LIMITATIONS = [
    "Synthetic checks do not validate physical range accuracy.",
    "Reported sample rates are nominal; only the relative recording clock rate is estimated.",
    "The clock fit assumes stable propagation paths during the capture; systematic motion can resemble clock drift.",
    "Detector uncertainty and exchange spread are diagnostics, not a calibrated physical confidence interval.",
    "A matched arrival may be reflected, structure-borne, or biased by device filtering and processing.",
    "Close-peak checks retain competing envelope lobes, but cannot rule out unresolved paths merged into one maximum or calibrate channel bias.",
    "Browser continuity metadata covers delivered audio blocks, not hidden ADC/OS resampling or processing.",
    "Average cross-transducer acoustic path is not the nearest device-body gap.",
    "No calibrated detector-bias or acoustic-path-to-body-gap model is implemented; NEAR/FAR is withheld.",
]


def _unique(items):
    return list(dict.fromkeys(items))


def _number(value, name, *, positive=False):
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError(f"{name} must be a finite {'positive ' if positive else ''}number")
    return result


def _settings(config):
    # Explicit whitelist: labels or legacy alignment fields cannot enter timing.
    settings = dict(DEFAULTS)
    supplied = config or {}
    for key in DEFAULTS:
        if key in supplied:
            settings[key] = _number(supplied[key], key, positive=True)
    for key in ("max_candidates", "minimum_emissions_per_direction", "profile_bins"):
        settings[key] = int(settings[key])
    if not 0 < settings["min_normalized_correlation"] < 1:
        raise ValueError("min_normalized_correlation must lie strictly between zero and one")
    if not 0 < settings["close_peak_reference_tolerance"] < 1:
        raise ValueError("close_peak_reference_tolerance must lie strictly between zero and one")
    if settings["minimum_emissions_per_direction"] < 3:
        raise ValueError("At least three emissions in each direction are required for clock diagnostics")
    self_paths = supplied.get("self_path_m")
    if self_paths is not None:
        if not isinstance(self_paths, dict) or set(self_paths) != {"A", "B"}:
            raise ValueError("self_path_m requires independently measured A and B paths")
        self_paths = {role: _number(value, f"self_path_m.{role}") for role, value in self_paths.items()}
        if any(value < 0 for value in self_paths.values()):
            raise ValueError("Self path lengths cannot be negative")
    settings["self_path_m"] = self_paths
    # Timeline keys are validated separately: one is a string policy, and the
    # defaults reproduce today's behavior exactly, so a caller that supplies
    # none (the live server) is unaffected.
    settings["timeline"] = timeline_settings(supplied)
    return settings


def _longest_run(mask):
    indices = np.flatnonzero(np.diff(np.r_[False, mask, False]))
    return int(np.max(indices[1::2] - indices[::2], initial=0))


def _continuity(metadata, frames, sample_rate):
    reasons = []
    warnings = []
    if metadata.get("recording_complete") is not True:
        reasons.append("recording_incomplete")
    if metadata.get("frame_count") != frames:
        reasons.append("recording_frame_count_mismatch")
    if metadata.get("sample_rate") != sample_rate:
        reasons.append("recording_sample_rate_metadata_mismatch")
    if metadata.get("channel_count") != 1:
        reasons.append("recording_channel_metadata_missing_or_not_mono")
    blocks = metadata.get("blocks")
    coverage = 0
    previous_context_end = None
    context_missing = False
    if not isinstance(blocks, list) or not blocks:
        reasons.append("continuity_metadata_missing")
        blocks = []
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            reasons.append("continuity_block_invalid")
            continue
        start, count = block.get("start_frame"), block.get("frame_count")
        if not isinstance(start, int) or not isinstance(count, int) or count <= 0:
            reasons.append("continuity_block_invalid")
            continue
        if start != coverage or block.get("index") != index:
            reasons.append("continuity_block_gap_or_overlap")
        coverage = start + count
        context_frame = block.get("context_frame")
        if not isinstance(context_frame, int):
            context_missing = True
        elif previous_context_end is not None and context_frame != previous_context_end:
            reasons.append("audio_context_frame_discontinuity")
        if isinstance(context_frame, int):
            previous_context_end = context_frame + count
        if block.get("input_channels", 1) < 1:
            reasons.append("capture_block_without_input")
    if blocks and coverage != frames:
        reasons.append("continuity_blocks_do_not_cover_wav")
    if context_missing:
        reasons.append("audio_context_frame_metadata_missing")
    if metadata.get("discontinuities"):
        reasons.append("reported_capture_discontinuity")
    if metadata.get("missing_frames", 0):
        reasons.append("reported_missing_frames")
    for event in metadata.get("context_events", []):
        if isinstance(event, dict) and event.get("state") in {"suspended", "interrupted", "closed"}:
            reasons.append("audio_context_interrupted")
    for event in metadata.get("track_events", []):
        if isinstance(event, dict) and event.get("type") in {"mute", "ended", "error"}:
            reasons.append("audio_track_interrupted")
    if metadata.get("visibility_events"):
        warnings.append("visibility_events_recorded")
    return {
        "verified": not reasons,
        "block_count": len(blocks),
        "covered_frames": coverage,
        "scope": "delivered_audio_context_blocks_only",
        "reasons": _unique(reasons),
        "warnings": warnings,
    }


def _read_recording(source, role, timeline=None):
    options = dict(TIMELINE_DEFAULTS)
    options.update(timeline or {})
    path = Path(source["wav_path"])
    audio, rate = sf.read(path, dtype="float64", always_2d=True)
    info = sf.info(path)
    reasons = []
    if audio.shape[1] != 1:
        reasons.append("recording_not_mono")
    # Do not average channels. Averaging can cancel a direct path and alter timing.
    mono = audio[:, 0].copy()
    pcm_integrity = scan_pcm_integrity(mono, rate)
    # Signal-content discontinuity candidates. Diagnostic only; they do not join
    # quality_reasons or quality_warnings and cannot change an existing verdict.
    candidates = timeline_candidates(
        mono, rate,
        minimum_gap_ms=options["timeline_gap_min_ms"],
        near_silent_fraction=options["timeline_near_silent_fraction"],
    )
    if not np.all(np.isfinite(mono)):
        reasons.append("nonfinite_audio_samples")
        mono[~np.isfinite(mono)] = 0.0
    clipped = np.abs(mono) >= 0.999
    clipped_count = int(np.count_nonzero(clipped))
    clipped_run = _longest_run(clipped)
    if clipped_run >= 3 or clipped_count >= max(8, len(mono) * 0.0001):
        reasons.append("recording_clipped")
    metadata = source.get("metadata") or {}
    continuity = _continuity(metadata, len(mono), rate)
    reasons += continuity["reasons"]
    if metadata.get("clipping", {}).get("clipped_samples", 0):
        reasons.append("reported_capture_clipping")
    report = {
        "receiver": role,
        "sample_rate_hz": int(rate),
        "sample_rate_semantics": "wav_header_nominal_not_measured_hardware_rate",
        "frames": len(mono),
        "channels": audio.shape[1],
        "wav_subtype": info.subtype,
        "duration_nominal_s": len(mono) / rate,
        "peak": float(np.max(np.abs(mono), initial=0)),
        "rms": float(np.sqrt(np.mean(mono * mono))) if len(mono) else 0.0,
        "clipped_samples": clipped_count,
        "longest_clipped_run_frames": clipped_run,
        "continuity": continuity,
        # Requested browser routing is context for comparing channel responses,
        # never evidence that a particular physical transducer was selected.
        "playback": metadata.get("playback") if isinstance(metadata.get("playback"), dict) else {},
        "pcm_integrity": pcm_integrity,
        "timeline_candidates": candidates,
        "quality_warnings": _unique([
            f"internal_{kind}_span_observed"
            for kind, count in pcm_integrity["internal_span_counts"].items() if count
        ]),
        "quality_reasons": _unique(reasons),
        "usable": not reasons,
    }
    return mono, rate, report


def _at_rate(template, template_rate, recording_rate):
    if template_rate == recording_rate:
        return np.asarray(template, dtype=np.float64)
    divisor = math.gcd(int(template_rate), int(recording_rate))
    # Derived reference only. The recording and its original rate are unchanged.
    return signal.resample_poly(template, recording_rate // divisor, template_rate // divisor).astype(np.float64)


def _profile(audio, template):
    count = len(template)
    if len(audio) < count or count == 0:
        return np.empty(0), np.empty(0), np.empty(0), 0.0
    correlation = signal.correlate(audio, template, mode="valid", method="fft")
    envelope = np.abs(signal.hilbert(correlation))
    energy = np.r_[0.0, np.cumsum(audio * audio)]
    window_energy = np.maximum(energy[count:] - energy[:-count], 0)
    denominator = np.sqrt(window_energy * float(template @ template))
    # Roundoff in long quiet stretches must not turn zero energy into a match.
    minimum_energy = max(float(np.max(window_energy, initial=0)) * 1e-12, 1e-24)
    normalized = np.divide(envelope, denominator, out=np.zeros_like(envelope), where=window_energy > minimum_energy)
    normalized = np.minimum(normalized, 1.0)
    median = float(np.median(envelope))
    noise_scale = max(
        1.4826 * float(np.median(np.abs(envelope - median))),
        median / 1.1774,
        float(np.max(envelope, initial=0)) * 1e-9,
        1e-14,
    )
    return correlation, envelope, normalized, noise_scale


def _compact_profile(envelope, sample_rate, bins):
    if not len(envelope):
        return {"bin_frames": 1, "sample_rate_hz": sample_rate, "envelope_max": []}
    stride = max(1, math.ceil(len(envelope) / bins))
    padding = (-len(envelope)) % stride
    maxima = np.pad(envelope, (0, padding)).reshape(-1, stride).max(axis=1)
    peak = float(np.max(maxima, initial=0))
    return {
        "bin_frames": stride,
        "sample_rate_hz": sample_rate,
        "envelope_max": np.round(maxima / peak, 6).tolist() if peak else maxima.tolist(),
        "absolute_peak": peak,
        "semantics": "max_envelope_per_bin_for_display_only; full-resolution matching precedes binning",
    }


def _fractional_peak(envelope, index):
    if index <= 0 or index >= len(envelope) - 1:
        return float(index)
    left, center, right = envelope[index - 1:index + 2]
    curvature = left - 2 * center + right
    offset = 0.5 * (left - right) / curvature if curvature < 0 else 0.0
    return float(index + np.clip(offset, -0.5, 0.5))


def _candidate_uncertainty(envelope, index, rate, noise_ratio):
    # Local interpolation precision only. It excludes multipath, filter bias and
    # unknown absolute clock scale; it is not a physical accuracy claim.
    half = envelope[index] * 0.5
    left = right = index
    while left > 0 and envelope[left] > half:
        left -= 1
    while right + 1 < len(envelope) and envelope[right] > half:
        right += 1
    width = (right - left) / rate
    return max(1.0 / rate, width / (2.0 * math.sqrt(max(noise_ratio, 1)))), width


def _detect(audio, template, rate, settings):
    """Full-recording matching, with matching pursuit for weaker overlapping paths.

    A strong path is subtracted using the exact waveform before searching again.
    This is a diagnostic linear-copy model, not a claim to identify direct sound
    under arbitrary channel filtering. The original profile is retained.
    """
    correlation, envelope, normalized, noise_scale = _profile(audio, template)
    original_noise_scale = noise_scale
    result = {
        "onset_ms": None,
        "onset_frame": None,
        "uncertainty_ms": None,
        "quality": "missing",
        "reasons": [],
        "candidates": [],
        "delay_profile": _compact_profile(envelope, rate, settings["profile_bins"]),
        "search_scope": "entire_recording_without_schedule_or_distance_prior",
        "uncertainty_semantics": "local_template_peak_precision_only_not_physical_error_bound",
        "close_peak_diagnostics": close_peak_diagnostics(envelope, normalized, noise_scale, template, rate, [], settings),
    }
    if not len(envelope):
        result["reasons"].append("recording_shorter_than_template")
        return result, normalized
    residual = audio.copy()
    mask = np.ones(len(envelope), dtype=bool)
    separation = max(1, round(settings["candidate_separation_ms"] * rate / 1000))
    original_envelope = envelope.copy()
    original_normalized = normalized.copy()
    template_energy = float(template @ template)
    for iteration in range(settings["max_candidates"]):
        if iteration:
            correlation, envelope, normalized, noise_scale = _profile(residual, template)
        eligible = (
            mask
            & (normalized >= settings["min_normalized_correlation"])
            & (envelope >= settings["min_noise_ratio"] * noise_scale)
        )
        # Peak locations, rather than the leading threshold crossing, preserve
        # the exact template-origin timing including the template's fade.
        peaks, _ = signal.find_peaks(envelope, distance=separation)
        peaks = peaks[eligible[peaks]]
        if not len(peaks):
            break
        index = int(peaks[np.argmax(envelope[peaks])])
        fractional = _fractional_peak(envelope, index)
        ratio = float(envelope[index] / noise_scale)
        uncertainty, width = _candidate_uncertainty(envelope, index, rate, ratio)
        amplitude = float(correlation[index] / template_energy)
        local = audio[index:index + len(template)]
        local_zero_run = _longest_run(np.abs(local[len(template) // 8:7 * len(template) // 8]) <= 1e-12)
        reasons = []
        if _longest_run(np.abs(local) >= 0.999) >= 3:
            reasons.append("arrival_window_clipped")
        if local_zero_run >= max(8, math.ceil(rate * 0.001)):
            reasons.append("arrival_window_zero_dropout")
        result["candidates"].append({
            "onset_frame": fractional,
            "onset_ms": fractional / rate * 1000,
            "normalized_correlation": float(original_normalized[index]),
            "residual_normalized_correlation": float(normalized[index]),
            "noise_ratio": ratio,
            "signed_template_gain": amplitude,
            "uncertainty_ms": uncertainty * 1000,
            "half_height_width_ms": width * 1000,
            "pursuit_pass": iteration,
            "credible": not reasons,
            "reasons": reasons,
        })
        mask[max(0, index - separation):min(len(mask), index + separation + 1)] = False
        residual[index:index + len(template)] -= amplitude * template
    result["candidates"].sort(key=lambda candidate: candidate["onset_frame"])
    result["close_peak_diagnostics"] = close_peak_diagnostics(
        original_envelope, original_normalized, original_noise_scale,
        template, rate, result["candidates"], settings,
    )
    result["candidate_limit_reached"] = len(result["candidates"]) == settings["max_candidates"]
    if result["candidate_limit_reached"]:
        result["reasons"].append("candidate_limit_reached")
    if not result["candidates"]:
        result["reasons"].append("missing_or_weak_template")
        result["best_normalized_correlation"] = float(np.max(original_normalized, initial=0))
        result["best_noise_ratio"] = float(np.max(original_envelope, initial=0) / noise_scale)
    return result, original_normalized


def _select_arrival(arrival, profiles, rate, settings):
    """Compare code evidence locally, without using any desired distance."""
    arrival.update({"onset_ms": None, "onset_frame": None, "uncertainty_ms": None})
    guard = max(1, round(rate * settings["candidate_separation_ms"] / 1000))
    for candidate in arrival["candidates"]:
        index = round(candidate["onset_frame"])
        competitor_score, competitor_id = 0.0, None
        for emission_id, profile in profiles.items():
            if emission_id == arrival["emission_id"]:
                continue
            region = profile[max(0, index - guard):min(len(profile), index + guard + 1)]
            score = float(np.max(region, initial=0))
            if score > competitor_score:
                competitor_score, competitor_id = score, emission_id
        candidate["competing_emission_id"] = competitor_id
        candidate["competing_normalized_correlation"] = competitor_score
        own_score = candidate["normalized_correlation"]
        if competitor_score >= max(settings["min_normalized_correlation"], own_score * 0.90):
            candidate["credible"] = False
            candidate["reasons"].append("cross_code_confusion")
    credible = [candidate for candidate in arrival["candidates"] if candidate["credible"]]
    rejected_reasons = [reason for candidate in arrival["candidates"] for reason in candidate["reasons"]]
    if not credible:
        arrival["quality"] = "rejected" if arrival["candidates"] else "missing"
        arrival["reasons"] = _unique(arrival["reasons"] + rejected_reasons)
        return
    if arrival["close_peak_diagnostics"]["unresolved"]:
        arrival["quality"] = "ambiguous"
        arrival["reasons"] = _unique(arrival["reasons"] + ["unresolved_close_peaks"])
        arrival["selection_rule"] = "withheld_unresolved_close_peak_structure"
        return
    span = credible[-1]["onset_ms"] - credible[0]["onset_ms"]
    if span > settings["max_echo_span_ms"] or arrival["candidate_limit_reached"]:
        arrival["quality"] = "ambiguous"
        arrival["reasons"].append("multiple_separated_template_events" if span > settings["max_echo_span_ms"] else "unresolved_candidate_count")
        return
    selected = credible[0]
    # A suspect earlier path cannot be silently discarded to accept a later one.
    earlier_rejected = [candidate for candidate in arrival["candidates"] if candidate["onset_frame"] < selected["onset_frame"] and not candidate["credible"]]
    if earlier_rejected:
        arrival["quality"] = "ambiguous"
        arrival["reasons"] = _unique(arrival["reasons"] + ["earlier_candidate_unresolved"] + rejected_reasons)
        return
    arrival.update({key: selected[key] for key in ("onset_ms", "onset_frame", "uncertainty_ms")})
    arrival["quality"] = "usable"
    arrival["selection_rule"] = "earliest_credible_candidate_without_cross_device_timing_prior"
    if len(credible) > 1:
        arrival["reasons"].append("multiple_paths_detected_directness_unverified")


def _fit_clock(arrivals, emissions, settings):
    by_key = {(item["emission_id"], item["receiver"]): item for item in arrivals}
    rows = []
    for emission in emissions:
        a, b = (by_key[(emission["id"], role)] for role in ("A", "B"))
        if a["quality"] == b["quality"] == "usable":
            rows.append({
                "emission_id": emission["id"], "emitter": emission["emitter"],
                "a_s": a["onset_ms"] / 1000, "b_s": b["onset_ms"] / 1000,
                "uncertainty_s": math.hypot(a["uncertainty_ms"], b["uncertainty_ms"]) / 1000,
            })
    result = {
        "valid": False, "relative_rate_ppm": None, "relative_rate_b_over_a": None,
        "residual_ms": None, "max_abs_residual_ms": None, "intercepts_s": None,
        "used_emissions": len(rows), "rows": rows, "reasons": [],
        "model": "t_B = relative_rate * t_A + intercept[emitter]",
        "clock_scale": "A nominal recording seconds; no measured absolute hardware rate",
        "assumptions": "Stable source/receiver paths and source-specific detector bias throughout the recording; systematic path changes can be confounded with rate.",
        "step_check": None,
    }
    counts = {emitter: sum(row["emitter"] == emitter for row in rows) for emitter in ("A", "B")}
    if min(counts.values()) < settings["minimum_emissions_per_direction"]:
        result["reasons"].append("insufficient_independent_emissions_for_clock_fit")
        return result
    a = np.array([row["a_s"] for row in rows])
    b = np.array([row["b_s"] for row in rows])
    is_a = np.array([row["emitter"] == "A" for row in rows])
    centered_a = a.copy()
    centered_b = b.copy()
    for selector in (is_a, ~is_a):
        centered_a[selector] -= np.mean(a[selector])
        centered_b[selector] -= np.mean(b[selector])
        if np.ptp(a[selector]) < 0.5:
            result["reasons"].append("insufficient_time_span_for_clock_fit")
    variance = float(centered_a @ centered_a)
    if variance <= 0 or result["reasons"]:
        return result
    rate = float(centered_a @ centered_b / variance)
    if rate <= 0:
        result["reasons"].append("nonpositive_relative_clock_rate")
        return result
    intercepts = {emitter: float(np.mean(b[selector] - rate * a[selector])) for emitter, selector in (("A", is_a), ("B", ~is_a))}
    residuals = b - rate * a - np.where(is_a, intercepts["A"], intercepts["B"])
    rms = float(np.sqrt(np.mean(residuals * residuals)))
    maximum = float(np.max(np.abs(residuals)))
    result.update({
        "relative_rate_ppm": (rate - 1) * 1e6,
        "relative_rate_b_over_a": rate,
        "intercepts_s": intercepts,
        "residual_ms": rms * 1000,
        "max_abs_residual_ms": maximum * 1000,
        "within_direction_span_s": {"A": float(np.ptp(a[is_a])), "B": float(np.ptp(a[~is_a]))},
    })
    for row, residual in zip(rows, residuals):
        row["residual_ms"] = float(residual * 1000)
    # A single fitted slope can conceal a clock jump. Compare a shared-step model
    # at every eligible boundary, requiring both emitters on each side. Never use
    # that model to repair the capture or silently remove its bad emissions.
    design = np.column_stack((a - np.mean(a), is_a.astype(float), (~is_a).astype(float)))
    baseline_sse = float(residuals @ residuals)
    best_step = None
    for left, right in zip(np.sort(a)[:-1], np.sort(a)[1:]):
        boundary = (left + right) / 2
        after = a > boundary
        if min(np.count_nonzero(after & is_a), np.count_nonzero(after & ~is_a), np.count_nonzero(~after & is_a), np.count_nonzero(~after & ~is_a)) < 2:
            continue
        step_design = np.column_stack((design, after.astype(float)))
        fit = np.linalg.lstsq(step_design, b, rcond=None)[0]
        error = b - step_design @ fit
        sse = float(error @ error)
        improvement = 1 - sse / baseline_sse if baseline_sse > 1e-20 else 0.0
        candidate = {"after_a_s": float(boundary), "step_ms": float(fit[-1] * 1000), "sse_reduction_fraction": improvement, "residual_ms_with_step": float(math.sqrt(sse / len(a)) * 1000)}
        if best_step is None or candidate["sse_reduction_fraction"] > best_step["sse_reduction_fraction"]:
            best_step = candidate
    result["step_check"] = best_step
    local_precision_ms = float(np.median([row["uncertainty_s"] for row in rows]) * 1000)
    if best_step and abs(best_step["step_ms"]) > max(settings["clock_residual_limit_ms"], 4 * local_precision_ms) and best_step["sse_reduction_fraction"] > 0.65:
        result["reasons"].append("discontinuous_clock_step_suspected")
    if maximum * 1000 > settings["clock_residual_limit_ms"]:
        result["reasons"].append("clock_fit_residual_too_large")
    if abs(rate - 1) > 0.01:
        result["reasons"].append("relative_clock_rate_outside_diagnostic_limit")
    result["valid"] = not result["reasons"]
    return result


def _exchanges(arrivals, emissions, clock, settings):
    lookup = {(item["emission_id"], item["receiver"]): item for item in arrivals}
    pairs = defaultdict(dict)
    for emission in emissions:
        pair = pairs[emission["pair_index"]]
        if emission["emitter"] in pair:
            raise ValueError("Each pair must contain exactly one emission from each emitter")
        pair[emission["emitter"]] = emission["id"]
    result = []
    rate = clock["relative_rate_b_over_a"]
    correction = sum(settings["self_path_m"].values()) / 2 if settings["self_path_m"] is not None else None
    for pair_index, pair in sorted(pairs.items()):
        item = {"pair_index": pair_index, "usable": False, "arrivals": {}, "reasons": [], "delta_a_s": None, "delta_b_s": None, "delta_b_in_a_seconds": None, "timing_difference_s": None, "uncorrected_equivalent_m": None, "acoustic_cross_path_m": None}
        if set(pair) != {"A", "B"}:
            item["reasons"].append("incomplete_emission_pair")
            result.append(item)
            continue
        observed = {}
        for path, emission_id, receiver in (("AA", pair["A"], "A"), ("AB", pair["A"], "B"), ("BA", pair["B"], "A"), ("BB", pair["B"], "B")):
            observed[path] = lookup[(emission_id, receiver)]
            item["arrivals"][path] = {key: observed[path][key] for key in ("emission_id", "receiver", "onset_ms", "onset_frame", "quality", "uncertainty_ms")}
        if any(arrival["quality"] != "usable" for arrival in observed.values()):
            item["reasons"].append("four_usable_arrivals_required")
        if rate is None or not clock["valid"]:
            item["reasons"].append("stable_relative_clock_fit_required")
        if item["reasons"]:
            result.append(item)
            continue
        delta_a = (observed["BA"]["onset_ms"] - observed["AA"]["onset_ms"]) / 1000
        delta_b = (observed["BB"]["onset_ms"] - observed["AB"]["onset_ms"]) / 1000
        difference = delta_a - delta_b / rate
        equivalent = settings["speed_of_sound_m_s"] * difference / 2
        precision = math.sqrt(sum((arrival["uncertainty_ms"] / 1000 / (rate if path[1] == "B" else 1)) ** 2 for path, arrival in observed.items()))
        item.update({
            "usable": True, "delta_a_s": delta_a, "delta_b_s": delta_b,
            "delta_b_in_a_seconds": delta_b / rate,
            "timing_difference_s": difference,
            "local_detector_precision_s": precision,
            "uncorrected_equivalent_m": equivalent,
            "acoustic_cross_path_m": equivalent + correction if correction is not None else None,
        })
        result.append(item)
    return result


def _mark_exchanges_unusable(exchanges):
    """Re-mark already-built exchange rows unusable without rebuilding them.

    A capture or attribution failure invalidates the clock fit after the
    exchanges were built. Rebuilding them globally would discard the segment
    membership that :func:`timeline_evaluation` attached under the segmented
    policy while the clock fit itself stays the selected segment's. Re-marking
    produces exactly the rows ``_exchanges`` would return for an invalid clock
    (same keys, same reason, same nulls) and keeps ``segment_index``.
    """
    result = []
    for item in exchanges:
        row = {"pair_index": item["pair_index"], "usable": False,
               "arrivals": item["arrivals"], "reasons": list(item["reasons"]),
               "delta_a_s": None, "delta_b_s": None, "delta_b_in_a_seconds": None,
               "timing_difference_s": None, "uncorrected_equivalent_m": None,
               "acoustic_cross_path_m": None}
        if "incomplete_emission_pair" not in row["reasons"]:
            row["reasons"] = _unique(row["reasons"] + ["stable_relative_clock_fit_required"])
        if "segment_index" in item:
            row["segment_index"] = item["segment_index"]
        result.append(row)
    return result


def timeline_evaluation(arrivals, emissions, settings, recording_reports):
    """Public wiring point: clock fit and exchanges under the timeline policy.

    Returns ``(clock_fit, exchanges, timeline_block, extra_reasons)``. Under the
    default ``global`` policy the clock fit and exchanges are byte-identical to
    ``_fit_clock``/``_exchanges`` and the timeline block is reported but unused.
    ``settings["timeline"]`` is the single source of the timeline options; every
    caller builds it with :func:`ranging_timeline.timeline_settings` from its own
    config before calling, so the config is never re-read here.
    """
    options = settings["timeline"]
    return evaluate_timeline(arrivals, emissions, settings, recording_reports,
                             _fit_clock, _exchanges, timeline=options)


def analyze_ranging(recordings: dict, protocol: dict, config: dict | None = None) -> dict[str, Any]:
    """Analyze two original mono WAVs with the exact server-owned protocol.

    Expected recording values are ``{"wav_path": path, "metadata": dict}``.
    Metadata needs complete ordered block coverage and audio-context frame indices.
    Results never contain NEAR or FAR, even if an unknown calibration or label is
    supplied. Valid physical calibration requires a separate validated estimator.
    """
    if protocol.get("version") == "beepbeep-v1":
        from beepbeep_analysis import analyze_beepbeep
        return analyze_beepbeep(recordings=recordings, protocol=protocol, config=config)
    settings = _settings(config)
    if set(recordings) != {"A", "B"}:
        raise ValueError("Both A and B recordings are required")
    emissions = protocol.get("emissions")
    if not isinstance(emissions, list) or not emissions:
        raise ValueError("Protocol has no exact emissions")
    identifiers = [emission["id"] for emission in emissions]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Emission identifiers must be unique")
    if any(emission["emitter"] not in {"A", "B"} for emission in emissions):
        raise ValueError("Emission identities must be A or B")
    template_rate = int(_number(protocol["sample_rate"], "template sample_rate", positive=True))
    templates = {emission["id"]: np.asarray(decode_template(protocol, emission["id"]), dtype=np.float64) for emission in emissions}
    if len({template.tobytes() for template in templates.values()}) != len(templates):
        raise ValueError("Every emission must have a distinct exact template")
    if any(len(template) < 8 or not np.all(np.isfinite(template)) or float(template @ template) <= 0 for template in templates.values()):
        raise ValueError("Templates must contain finite nonzero waveforms")
    arrivals = []
    recording_reports = {}
    for role in ("A", "B"):
        audio, rate, report = _read_recording(recordings[role], role, settings["timeline"])
        recording_reports[role] = report
        profiles = {}
        local_arrivals = []
        for emission in emissions:
            reference = _at_rate(templates[emission["id"]], template_rate, rate)
            arrival, profile = _detect(audio, reference, rate, settings)
            arrival.update({"emission_id": emission["id"], "pair_index": emission["pair_index"], "emitter": emission["emitter"], "receiver": role})
            arrival["template_conversion"] = {"source_rate_hz": template_rate, "reference_rate_hz": rate, "method": "none" if template_rate == rate else "polyphase_reference_resampling", "recording_resampled": False}
            profiles[emission["id"]] = profile
            local_arrivals.append(arrival)
        for arrival in local_arrivals:
            _select_arrival(arrival, profiles, rate, settings)
        arrivals.extend(local_arrivals)
    clock, exchanges, timeline, timeline_reasons = timeline_evaluation(
        arrivals, emissions, settings, recording_reports)
    capture_reasons = [f"{role}:{reason}" for role, report in recording_reports.items() for reason in report["quality_reasons"]]
    capture_warnings = [f"{role}:{warning}" for role, report in recording_reports.items() for warning in report["quality_warnings"]]
    if capture_reasons:
        clock["valid"] = False
        clock["reasons"].append("recording_quality_or_continuity_failed")
        exchanges = _mark_exchanges_unusable(exchanges)
    usable = [item for item in exchanges if item["usable"]]
    reasons = capture_reasons + clock["reasons"] + timeline_reasons
    if len(usable) < settings["minimum_emissions_per_direction"]:
        reasons.append("insufficient_usable_exchanges")
    for arrival in arrivals:
        if arrival["quality"] != "usable":
            reasons.append(f"{arrival['receiver']}:{arrival['emission_id']}:{arrival['quality']}")
    if settings["self_path_m"] is None:
        reasons.append("self_path_correction_not_provided")
    reasons += ["physical_error_calibration_missing", "device_body_gap_mapping_missing"]
    # A partial set can be inspected, but all expected arrivals are required for
    # the trial summary. This keeps failed attempts visible instead of selecting
    # only convenient exchanges from the capture.
    valid = bool(usable) and len(usable) == len(exchanges) and not capture_reasons and clock["valid"]
    values = np.array([item["timing_difference_s"] for item in usable])
    center = float(np.median(values)) if valid else None
    mad = float(np.median(np.abs(values - np.median(values)))) if valid else None
    speed = settings["speed_of_sound_m_s"]
    correction = sum(settings["self_path_m"].values()) / 2 if settings["self_path_m"] is not None else None
    equivalent = speed * center / 2 if center is not None else None
    acoustic = equivalent + correction if equivalent is not None and correction is not None else None
    if acoustic is not None and acoustic < 0:
        reasons.append("negative_acoustic_path_check_self_paths_or_arrival_bias")
    spread = speed * 1.4826 * mad / 2 if mad is not None else None
    summary = {
        "timing_difference_ms": center * 1000 if center is not None else None,
        "uncorrected_equivalent_cm": equivalent * 100 if equivalent is not None else None,
        "acoustic_path_cm": acoustic * 100 if acoustic is not None else None,
        "repeatability_cm": spread * 100 if spread is not None else None,
        "repeatability_definition": "1.4826 * median absolute deviation across paired timing equivalents; not physical confidence",
        "self_path_correction_cm": correction * 100 if correction is not None else None,
        "usable_emissions": clock["used_emissions"], "total_emissions": len(emissions),
        "usable_exchanges": len(usable), "total_exchanges": len(exchanges),
        "detected_arrivals": sum(bool(arrival.get("candidates")) for arrival in arrivals),
        "total_arrivals": len(arrivals),
        "ambiguous_arrivals": sum(arrival["quality"] == "ambiguous" for arrival in arrivals),
        "device_body_gap_cm": None,
    }
    return {
        "analysis_version": ANALYSIS_VERSION,
        "protocol_version": protocol.get("version"),
        "session_id": protocol.get("session_id"),
        "status": "diagnostic" if valid else "invalid",
        "decision": {"label": "INCONCLUSIVE", "reasons": ["No calibrated physical error bound and body-gap mapping; diagnostic timing does not authorize a proximity verdict."]},
        "summary": summary,
        "reasons": _unique(reasons), "quality_reasons": _unique(reasons),
        "quality_warnings": capture_warnings,
        "recordings": recording_reports, "arrivals": arrivals,
        "clock_fit": clock, "exchanges": exchanges, "timeline": timeline,
        "aggregate": {
            "timing_difference_s": center,
            "uncorrected_equivalent_m": equivalent,
            "acoustic_cross_path_m": acoustic,
            "self_path_correction_m": correction,
            "repeatability_m": spread,
            "timing_min_s": float(np.min(values)) if valid else None,
            "timing_max_s": float(np.max(values)) if valid else None,
            "device_body_gap_m": None,
            "calibrated_confidence_interval": None,
            "formula": "D_cross = [c * (delta_A - delta_B / rate_B_over_A) + d_AA + d_BB] / 2",
            "speed_of_sound_m_s": speed,
            "self_path_m": settings["self_path_m"],
            "ground_truth_used_in_calculation": False,
        },
        "limitations": LIMITATIONS,
    }
