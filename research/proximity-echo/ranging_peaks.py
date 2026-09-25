"""Local matched-filter evidence that candidate suppression must not erase.

This is a shape diagnostic, not a multipath decomposition or a direct-path
estimator. It compares observed envelope maxima with the autocorrelation of the
exact digital template. A channel can merge paths into a single biased maximum,
so the absence of a competing maximum is not evidence of physical accuracy.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import signal


def _fractional_peak(values, index):
    if index <= 0 or index >= len(values) - 1:
        return float(index)
    left, center, right = values[index - 1:index + 2]
    curvature = left - 2 * center + right
    offset = 0.5 * (left - right) / curvature if curvature < 0 else 0.0
    return float(index + np.clip(offset, -0.5, 0.5))


def close_peak_diagnostics(envelope, normalized, noise_scale, template, rate,
                           candidates, settings):
    """Retain every local maximum inside each candidate's suppression radius.

    Peak extraction has no minimum separation. The previous detector's score
    and noise gates still apply when declaring an alternative unresolved. The
    reference envelope is sampled at each candidate's fractional delay, with a
    one-sample allowance and an explicit amplitude tolerance. These allowances
    distinguish ordinary digital sidelobes; neither is a physical error bound.
    """
    radius = max(1, round(settings["candidate_separation_ms"] * rate / 1000))
    profile_radius = max(radius + 1, math.ceil(settings["close_peak_profile_radius_ms"] * rate / 1000))
    result = {
        "unresolved": False,
        "ambiguity_span_ms": None,
        "alternatives": [],
        "local_profiles": [],
        "method": "unseparated_original_envelope_maxima_compared_with_exact_template_autocorrelation",
        "suppression_radius_ms": radius / rate * 1000,
        "reference_amplitude_tolerance": settings["close_peak_reference_tolerance"],
        "reference_lag_allowance_frames": 1,
        "limits": [
            "A competing envelope lobe is unresolved timing structure, not an identified physical path.",
            "The ambiguity span is the observed lobe separation, not a calibrated error bound.",
            "Merged paths and channel bias without distinct envelope maxima can remain undetected.",
        ],
    }
    if not candidates or not len(envelope):
        return result

    autocorrelation = signal.correlate(template, template, mode="full", method="fft")
    # Zero padding approximates the isolated reference in a long recording and
    # prevents the short reference's periodic Hilbert boundary from dominating.
    padding = len(autocorrelation)
    reference = np.abs(signal.hilbert(np.pad(autocorrelation, (padding, padding))))[padding:-padding]
    origin = len(template) - 1
    reference /= max(float(reference[origin]), np.finfo(float).tiny)
    reference_lags = np.arange(len(reference)) - origin

    def reference_at(offsets):
        return np.interp(offsets, reference_lags, reference, left=0, right=0)

    # Candidates are disjoint after pursuit suppression. Their evidence windows
    # can overlap; anchor identifiers make repeated observations explicit.
    spans = []
    for candidate_index, candidate in enumerate(candidates):
        anchor = candidate["onset_frame"]
        index = round(anchor)
        start = max(0, index - profile_radius)
        stop = min(len(envelope), index + profile_radius + 1)
        frames = np.arange(start, stop)
        anchor_amplitude = max(float(envelope[index]), np.finfo(float).tiny)
        relative = envelope[start:stop] / anchor_amplitude
        offsets = frames - anchor
        expected = reference_at(offsets)
        noise_allowance = 3 * noise_scale / anchor_amplitude
        amplitude_allowance = max(settings["close_peak_reference_tolerance"], noise_allowance)
        peaks, _ = signal.find_peaks(envelope[start:stop])
        peaks += start
        near = [int(peak) for peak in peaks if abs(peak - index) <= radius]
        # A pursuit peak may move a sample after stronger copies are subtracted.
        # Only the nearest original maximum within two samples is its own lobe.
        own_peak = min(near, key=lambda peak: abs(peak - anchor)) if near else None
        if own_peak is not None and abs(own_peak - anchor) > 2:
            own_peak = None
        competing_frames = []
        alternatives = []
        for peak in near:
            if peak == own_peak:
                continue
            fractional = _fractional_peak(envelope, peak)
            offset = fractional - anchor
            observed = float(envelope[peak] / anchor_amplitude)
            reference_amplitude = float(reference_at(np.array([peak - anchor]))[0])
            reference_upper = float(np.max(reference_at(np.array([peak - anchor - 1, peak - anchor, peak - anchor + 1]))))
            noise_ratio = float(envelope[peak] / noise_scale)
            passes_detection = bool(
                normalized[peak] >= settings["min_normalized_correlation"]
                and noise_ratio >= settings["min_noise_ratio"]
            )
            altered = observed > reference_upper + amplitude_allowance
            unresolved = altered and passes_detection
            if unresolved:
                classification = "competing_close_peak"
                competing_frames.append(fractional)
            elif not altered:
                classification = "template_autocorrelation_sidelobe"
            else:
                classification = "weak_channel_altered_peak"
            alternative = {
                "anchor_candidate_index": candidate_index,
                "anchor_onset_frame": anchor,
                "onset_frame": fractional,
                "onset_ms": fractional / rate * 1000,
                "offset_ms": offset / rate * 1000,
                "relative_amplitude": observed,
                "normalized_correlation": float(normalized[peak]),
                "noise_ratio": noise_ratio,
                "reference_relative_amplitude": reference_amplitude,
                "reference_relative_amplitude_upper": reference_upper,
                "reference_amplitude_allowance": amplitude_allowance,
                "passes_detection_thresholds": passes_detection,
                "classification": classification,
                "unresolved": unresolved,
            }
            alternatives.append(alternative)
            result["alternatives"].append(alternative)
        span = (max(competing_frames + [anchor]) - min(competing_frames + [anchor])) / rate * 1000 if competing_frames else None
        if span is not None:
            spans.append(span)
        result["local_profiles"].append({
            "anchor_candidate_index": candidate_index,
            "anchor_onset_frame": anchor,
            "anchor_onset_ms": anchor / rate * 1000,
            "sample_rate_hz": rate,
            "start_frame": start,
            "offset_ms": (offsets / rate * 1000).tolist(),
            "relative_amplitude": relative.tolist(),
            "reference_relative_amplitude": expected.tolist(),
            "normalized_correlation": normalized[start:stop].tolist(),
            "absolute_anchor_amplitude": anchor_amplitude,
            "noise_scale": noise_scale,
            "alternatives": alternatives,
            "unresolved": bool(competing_frames),
            "ambiguity_span_ms": span,
            "semantics": "one_value_per_original_profile_sample; reference_is_digital_template_autocorrelation",
        })
    result["unresolved"] = bool(spans)
    result["ambiguity_span_ms"] = max(spans) if spans else None
    return result
