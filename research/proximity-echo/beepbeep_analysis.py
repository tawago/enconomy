"""Live, schedule-separated BeepBeep detector and four-arrival diagnostics.

The published detector remains in analysis.beepbeep_reference. Added presence
and slot audits are reported separately. No schedule timestamp enters the
sample-count formula, and no body-gap label or earlier report is an input.
"""
from __future__ import annotations

from dataclasses import asdict
import math

import numpy as np
from scipy import signal

from beepbeep_protocol import PROFILE, validate_protocol

ANALYSIS_VERSION = "beepbeep-four-arrival-diagnostic-v1"
EVENT_NOISE_SD = 8.
EVENT_NORMALIZED_CORRELATION = .20
EVENT_SEPARATION_S = .060
MAX_EVENTS = 64
METADATA_TOLERANCE_S = .020

# Secondary-event classification. A secondary event is any qualified event that
# shares a slot with a stronger one. These constants are engineering thresholds,
# not published detector parameters, and they never move a selected arrival.
LATE_TAIL_MAX_AMPLITUDE_RATIO = .05  # raw-correlation ratio; the paper's sharpness rule already demands a selected peak dominate competitors by ~2x, so an extra sound below 5% of the primary is two decades from an equal-strength emission and is only ever a weak echo of it.
COMPETING_MIN_AMPLITUDE_RATIO = .20  # raw-correlation ratio; at or above a fifth of the primary an extra sound is strong enough to be an independent emission and must stay ambiguous.
LATE_TAIL_RECURRENCE_TOLERANCE_S = .010  # s; half-width of the search window around the same delay after another primary. It is about a chirp-envelope width, so the search does not resolve a fixed delay: it asks whether a qualified peak recurs anywhere inside the reverberant tail at roughly that lag. Observed matched offsets span several milliseconds.
LATE_TAIL_RECURRENCE_DIAGNOSTIC_TOLERANCE_S = .002  # s; report-only second window. The recurrence fraction recomputed at this tighter lag exposes how much the matched peer delays jitter; it changes no classification.
LATE_TAIL_RECURRENCE_RATIO_FACTOR = 3.  # dimensionless; the recurring peak must sit within a factor of three of the observed amplitude ratio.
LATE_TAIL_MIN_RECURRENCE_FRACTION = .5  # fraction of same-emitter slots that must show the recurrence for the "recurrent" late-tail class to hold.
LATE_TAIL_POLICIES = ("withhold", "separate")

LIMITATIONS = [
    "The published sharpness heuristic selects a candidate; it does not establish the acoustic first path.",
    "Identical sounds have no acoustic session freshness or authenticated source identity. A same-waveform replacement inside a slot cannot be distinguished from the intended emission.",
    "Attribution assumes each chirp lies within its declared coarse timing window. Metadata consistency cannot establish synchronized device wall clocks or bound hidden DAC/ADC latency.",
    "The extra-event audit groups correlation peaks within 60 ms. An overlapping replay and a reflection can be observationally identical; weak extra sounds can remain undetected.",
    "An arrival can be reflected, structure-borne, or biased by device filtering, polarity and browser processing.",
    "The 10 ms shadow window, sample neighborhoods and signal phase are explicit implementation conventions where the paper leaves details unspecified.",
    "The eight repeated exchanges and fitted relative recording rate extend the paper's paired sample-count equation. Stable paths and source-specific detector biases are assumed; motion can resemble clock drift.",
    "WAV sample rates are nominal. Browser continuity metadata covers delivered blocks, not hidden ADC/OS resampling or processing.",
    "Integer sample precision and repeatability are diagnostics, not a calibrated physical error bound.",
    "Independent speaker-to-microphone lengths provide a geometric self-path correction only. Acoustic detector bias and the relation to device-body gap remain uncalibrated.",
    "Synthetic checks do not validate physical accuracy. No NEAR/FAR proximity verdict is produced.",
    "Chirps carry no source authentication. The late-tail recurrence test asks only whether a qualified positive correlation peak reappears within a chirp-envelope width (10 ms) of the same delay after that emitter's other primaries; it therefore discriminates \"inside the reverberant tail\" from \"outside\" rather than establishing a fixed-delay device or room response, and the matched offsets are reported so the jitter is visible. A recurring weak tail is equally consistent with a reflection or device/browser response and with a co-located replay locked to that device's schedule. The late_tail_recurrent classification records the recurrence as evidence; it does not attribute the sound to a source.",
]


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _metadata_audit(metadata, protocol, role, rate):
    """Validate recording origin and local playback identity, never infer TOF."""
    reasons = []
    for field, expected in (("profile", PROFILE), ("protocol_version", protocol["version"]),
            ("protocol_id", protocol["protocol_id"]), ("session_id", protocol["session_id"]),
            ("emitter", role), ("role", "initiator" if role == "A" else "observer")):
        if metadata.get(field) != expected:
            reasons.append(f"attribution_metadata_{field}_mismatch_or_missing")
    start_frame, start_time = metadata.get("capture_start_context_frame"), metadata.get("capture_start_context_time")
    origin_valid = (isinstance(start_frame, int) and not isinstance(start_frame, bool)
        and start_frame >= 0 and _finite(start_time)
        and abs(start_frame / rate - start_time) <= 1 / rate)
    if not origin_valid:
        reasons.append("attribution_capture_origin_missing_or_inconsistent")
    blocks = metadata.get("blocks")
    if not isinstance(blocks, list) or not blocks or not isinstance(blocks[0], dict) or blocks[0].get("context_frame") != start_frame:
        reasons.append("attribution_first_pcm_frame_does_not_match_capture_origin")
    playback = metadata.get("playback")
    rows = playback.get("emissions") if isinstance(playback, dict) else None
    expected = [e for e in protocol["emissions"] if e["emitter"] == role]
    if not isinstance(rows, list) or len(rows) != len(expected):
        reasons.append("attribution_local_playback_manifest_missing_or_incomplete")
        rows = []
    for row, emission in zip(rows, expected):
        if not isinstance(row, dict) or any(row.get(key) != emission[key] for key in ("id", "pair_index", "sha256")):
            reasons.append("attribution_local_playback_identity_mismatch")
            continue
        scheduled = row.get("scheduled_context_time")
        if row.get("source_sample_rate") != protocol["sample_rate"]:
            reasons.append("attribution_local_playback_rate_mismatch")
        if not origin_valid or not _finite(scheduled) or abs(scheduled - start_time - emission["offset_s"]) > 2 / rate:
            reasons.append("attribution_local_playback_schedule_mismatch")
    schedule = metadata.get("schedule")
    schedule = schedule if isinstance(schedule, dict) else {}
    target = schedule.get("coordination_target_unix_ms")
    delay = schedule.get("start_after_ms")
    if not _finite(target) or not _finite(delay):
        reasons.append("attribution_coordination_metadata_missing")
    elif not 50 <= delay <= 10_000:
        reasons.append("attribution_coordination_metadata_inconsistent")
    return {"valid": not reasons, "reasons": list(dict.fromkeys(reasons)),
        "capture_start_context_frame": start_frame if isinstance(start_frame, int) else None,
        "declared_coordination_target_unix_ms": target if _finite(target) else None,
        "scope": "manifest_and_local_capture_origin_consistency_only_not_clock_synchronization"}


def _event_audit(audio, reference, rate, protocol):
    """Find strong template events solely to reject missing/extra attribution.

    These explicit engineering thresholds are not part of the paper's detector.
    The audit never adjusts the slot windows or chooses a distance-consistent lag.
    """
    if len(audio) < len(reference):
        return {"events": [], "reasons": ["recording_too_short_for_reference"],
            "noise_sd": 0., "correlation_threshold": 0.}, np.empty(0), np.empty(0)
    correlation = signal.correlate(audio, reference, mode="valid", method="fft")
    energy = np.r_[0., np.cumsum(audio * audio)]
    window_energy = np.maximum(energy[len(reference):] - energy[:-len(reference)], 0)
    denominator = np.sqrt(window_energy * float(reference @ reference))
    normalized = np.divide(correlation, denominator, out=np.zeros_like(correlation), where=denominator > 1e-15)
    normalized = np.clip(normalized, -1, 1)
    sigma = float(np.median(np.abs(correlation - np.median(correlation))) / .6744897501960817)
    threshold = max(EVENT_NOISE_SD * sigma, float(np.max(np.abs(correlation), initial=0)) * 1e-9, 1e-14)
    eligible = (correlation > threshold) & (normalized >= EVENT_NORMALIZED_CORRELATION)
    remaining = np.where(eligible, correlation, 0.)
    exclusion = math.ceil(EVENT_SEPARATION_S * rate)
    events = []
    for _ in range(MAX_EVENTS):
        frame = int(np.argmax(remaining))
        if remaining[frame] <= 0:
            break
        time = frame / rate
        slots = [e["id"] for e in protocol["emissions"] if e["search_window_s"][0] <= time <= e["search_window_s"][1]]
        events.append({"strongest_frame": frame, "strongest_ms": time * 1000,
            "signed_correlation": float(correlation[frame]),
            "normalized_correlation": float(normalized[frame]),
            "slot_emission_id": slots[0] if len(slots) == 1 else None})
        remaining[max(0, frame - exclusion):min(len(remaining), frame + exclusion + 1)] = 0
    events.sort(key=lambda event: event["strongest_frame"])
    reasons = []
    if np.max(remaining, initial=0) > 0:
        reasons.append("attribution_event_limit_exceeded")
    if any(event["slot_emission_id"] is None for event in events):
        reasons.append("attribution_signal_outside_declared_slots")
    return {"events": events, "reasons": reasons, "noise_sd": sigma,
        "correlation_threshold": threshold, "minimum_noise_sd": EVENT_NOISE_SD,
        "minimum_normalized_correlation": EVENT_NORMALIZED_CORRELATION,
        "event_separation_s": EVENT_SEPARATION_S,
        "semantics": "additional_engineering_probe_presence_audit_not_published_detector_thresholds"}, correlation, normalized


def _secondary_audit(audit, correlation, rate, protocol):
    """Classify every non-primary event in a slot; never change slot windows or arrivals.

    The primary of a slot is the event with the largest signed correlation among
    that slot's qualified events (the detector-selected arrival is not available
    here, and the audit must not depend on it). Recurrence is measured on the
    same full correlation array used by the audit: for the same emitter role, the
    array is inspected at the same relative delay after every other slot primary.
    A peer peak counts only if it clears the same correlation floor the audit
    applies to events, and the offset of every matched peak inside the window is
    reported so the reader can see how far the "same delay" actually moves.
    """
    by_slot, primaries = {}, {}
    for event in audit["events"]:
        if event["slot_emission_id"] is not None:
            by_slot.setdefault(event["slot_emission_id"], []).append(event)
    for slot, events in by_slot.items():
        primaries[slot] = max(events, key=lambda event: event["signed_correlation"])
    emitters = {emission["id"]: emission["emitter"] for emission in protocol["emissions"]}
    tolerance = math.ceil(LATE_TAIL_RECURRENCE_TOLERANCE_S * rate)
    result = {}
    for slot, events in by_slot.items():
        primary = primaries[slot]
        rows = []
        for event in events:
            if event is primary:
                continue
            delay = event["strongest_frame"] - primary["strongest_frame"]
            ratio = (event["signed_correlation"] / primary["signed_correlation"]
                if primary["signed_correlation"] > 0 else None)
            matching, considered, ratios, peers, offsets = 0, 0, [], [], []
            for other, other_primary in sorted(primaries.items()):
                if other == slot or emitters.get(other) != emitters.get(slot) or other_primary["signed_correlation"] <= 0:
                    continue
                center = other_primary["strongest_frame"] + delay
                low, high = max(0, center - tolerance), min(len(correlation), center + tolerance + 1)
                if high - low < 3:
                    continue
                considered += 1
                window = correlation[low:high]
                index = int(np.argmax(window))
                peak = float(window[index])
                offset_ms = (low + index - center) / rate * 1000
                # A peer peak is evidence only if it clears the same 8-sigma floor
                # the audit demands of an event; a raw argmax inside the window is
                # otherwise satisfied by noise.
                qualified = bool(peak > 0 and index not in (0, len(window) - 1)
                                 and peak >= audit["correlation_threshold"])
                peer = peak / other_primary["signed_correlation"]
                slot_row = {"slot_emission_id": other, "peer_peak_correlation": peak,
                    "peer_peak_sigma": peak / audit["noise_sd"] if audit["noise_sd"] > 0 else None,
                    "peer_qualified": qualified, "peer_amplitude_ratio": peer,
                    "peer_delay_offset_ms": offset_ms, "matched": False}
                peers.append(slot_row)
                if not qualified:
                    continue
                ratios.append(peer)
                if ratio is not None and ratio > 0 and ratio / LATE_TAIL_RECURRENCE_RATIO_FACTOR <= peer <= ratio * LATE_TAIL_RECURRENCE_RATIO_FACTOR:
                    matching += 1
                    slot_row["matched"] = True
                    offsets.append(offset_ms)
            fraction = matching / considered if considered else 0.
            tight = LATE_TAIL_RECURRENCE_DIAGNOSTIC_TOLERANCE_S * 1000
            tight_matching = sum(1 for value in offsets if abs(value) <= tight)
            recurrent = considered > 0 and fraction > LATE_TAIL_MIN_RECURRENCE_FRACTION
            if ratio is None:
                classification = "unclassified_secondary"
            elif delay < 0 or ratio >= COMPETING_MIN_AMPLITUDE_RATIO or not recurrent:
                classification = "competing_emission_candidate"
            elif ratio < LATE_TAIL_MAX_AMPLITUDE_RATIO:
                classification = "late_tail_recurrent"
            else:
                classification = "unclassified_secondary"
            rows.append({"strongest_frame": event["strongest_frame"],
                "strongest_ms": event["strongest_ms"],
                "delay_after_primary_s": delay / rate,
                "amplitude_ratio": ratio,
                "normalized": event["normalized_correlation"],
                "classification": classification,
                "recurrence": {"emitter": emitters.get(slot),
                    "same_emitter_slots_considered": considered,
                    "slots_with_matching_peak": matching,
                    "fraction": fraction,
                    "median_amplitude_ratio": float(np.median(ratios)) if ratios else None,
                    "delay_tolerance_s": tolerance / rate,
                    "ratio_factor": LATE_TAIL_RECURRENCE_RATIO_FACTOR,
                    "peer_threshold": audit["correlation_threshold"],
                    "peer_threshold_noise_sd_multiple": EVENT_NOISE_SD,
                    "peer_slots": peers,
                    "peer_qualified_count": sum(1 for item in peers if item["peer_qualified"]),
                    "peer_delay_offsets_ms": offsets,
                    "peer_delay_jitter_ms": max((abs(value) for value in offsets), default=None),
                    "peer_delay_median_offset_ms": float(np.median(offsets)) if offsets else None,
                    "diagnostic_tolerance_s": LATE_TAIL_RECURRENCE_DIAGNOSTIC_TOLERANCE_S,
                    "slots_with_matching_peak_at_2ms": tight_matching,
                    "recurrence_fraction_at_2ms": tight_matching / considered if considered else 0.,
                    "semantics": ("a positive local maximum >= the audit threshold within +/-10 ms of the "
                        "same delay after other same-emitter primaries; this indicates a recurring late tail, "
                        "consistent with room/device response OR a schedule-locked replay; it does not "
                        "identify a fixed-delay path")}})
        if rows:
            result[slot] = {"primary_frame": primary["strongest_frame"],
                "primary_rule": "largest_signed_correlation_event_in_slot",
                "secondary_events": rows}
    return result


def _arrival(audio, reference, rate, emission, protocol, detector_settings, audit, correlation, normalized,
        secondary=None, late_tail_policy="withhold"):
    from analysis.beepbeep_reference import detect_arrival
    from ranging_analysis import _compact_profile
    low, high = emission["search_window_s"]
    precontext = protocol["attribution"]["precontext_s"]
    guard = protocol["attribution"]["boundary_guard_s"]
    first = max(0, math.floor((low - precontext) * rate))
    end = min(len(audio), math.ceil(high * rate) + len(reference) + math.ceil(.003 * rate))
    row = {"emission_id": emission["id"], "pair_index": emission["pair_index"],
        "emitter": emission["emitter"], "onset_ms": None, "onset_frame": None,
        "uncertainty_ms": None, "quality": "missing", "reasons": [], "candidates": [],
        "search_scope": "declared_nonoverlapping_slot_with_background_precontext",
        "selection_rule": "published_earliest_sharp_positive_peak_in_assumed_shadow_window",
        "uncertainty_semantics": "one_sample_resolution_only_not_a_physical_error_bound",
        "attribution": {"search_window_s": [low, high], "precontext_s": precontext,
            "boundary_guard_s": guard, "identity": "schedule_consistent_only"}}
    if end - first < len(reference):
        row["reasons"].append("complete_slot_reference_unavailable")
        row["detector"] = {"detected": False, "reason": "recording_too_short"}
        row["delay_profile"] = {"bin_frames": 1, "sample_rate_hz": rate, "envelope_max": []}
        return row
    detected = detect_arrival(audio[first:end], reference, rate, detector_settings)
    detected["recording_origin_frame"] = first
    row["detector"] = detected
    profile = np.maximum(correlation[first:min(len(correlation), end - len(reference) + 1)], 0)
    row["delay_profile"] = _compact_profile(profile, rate, 256)
    row["delay_profile"].update({"origin_frame": first,
        "semantics": "positive_signed_correlation_max_per_bin_for_display_only"})
    for candidate in detected["candidates"]:
        frame = first + candidate["frame"]
        row["candidates"].append({**candidate, "onset_frame": frame,
            "onset_ms": frame / rate * 1000, "uncertainty_ms": 1000 / rate,
            "normalized_correlation": float(normalized[frame]),
            "credible": candidate["meets_published_sharpness"], "reasons": []})
    events = [event for event in audit["events"] if event["slot_emission_id"] == emission["id"]]
    row["attribution"]["event_count"] = len(events)
    row["attribution"]["events"] = events
    entry = (secondary or {}).get(emission["id"])
    rows = entry["secondary_events"] if entry else []
    row["attribution"]["secondary_events"] = rows
    if entry:
        row["attribution"]["primary_frame"] = entry["primary_frame"]
        row["attribution"]["primary_rule"] = entry["primary_rule"]
    late_tail_only = bool(rows) and all(item["classification"] == "late_tail_recurrent" for item in rows)
    if not detected["detected"]:
        row["reasons"].append(detected["reason"] or "published_detector_failed")
    if not events:
        row["reasons"].append("attribution_no_qualified_chirp_event_in_slot")
    if len(events) > 1:
        if late_tail_policy == "separate" and late_tail_only:
            for item in rows:
                item["note"] = "late_tail_observed"
            row["attribution"]["notes"] = ["late_tail_observed"]
        else:
            row["reasons"].append("attribution_multiple_chirp_events_in_slot")
            row["quality"] = "ambiguous"
    if detected["detected"]:
        selected = first + detected["selected_frame"]
        strongest = first + detected["strongest_positive_frame"]
        row["detector"]["selected_recording_frame"] = selected
        row["detector"]["strongest_recording_frame"] = strongest
        if any(not low + guard < frame / rate < high - guard for frame in (selected, strongest)):
            row["reasons"].append("attribution_peak_outside_or_near_slot_boundary")
            row["quality"] = "ambiguous"
        reference_frame = (events[0]["strongest_frame"] if len(events) == 1
            else entry["primary_frame"] if entry and late_tail_policy == "separate" and late_tail_only else None)
        if reference_frame is not None and abs(reference_frame - strongest) > 1:
            row["reasons"].append("attribution_published_peak_not_qualified_event")
            row["quality"] = "ambiguous"
        if not row["reasons"]:
            row.update({"quality": "usable", "onset_frame": selected,
                "onset_ms": selected / rate * 1000, "uncertainty_ms": 1000 / rate})
    return row


def analyze_beepbeep(recordings: dict, protocol: dict, config: dict | None = None) -> dict:
    """Return the common live schema. All physical proximity decisions abstain."""
    from analysis.beepbeep_reference import DetectorSettings, PAPER_URL
    from ranging_analysis import (_at_rate, _mark_exchanges_unusable, _read_recording,
        _settings, _unique, timeline_evaluation)
    from ranging_timeline import timeline_settings
    if set(recordings) != {"A", "B"}:
        raise ValueError("Both A and B recordings are required")
    templates = validate_protocol(protocol)
    config = config or {}
    settings = _settings({key: config[key] for key in (
        "speed_of_sound_m_s", "clock_residual_limit_ms", "minimum_emissions_per_direction",
        "self_path_m") if key in config})
    shadow = config.get("shadow_window_ms", 10.)
    if not _finite(shadow) or not 0 < shadow <= 50:
        raise ValueError("shadow_window_ms must be finite and in (0, 50]")
    detector_settings = DetectorSettings(shadow_window_ms=float(shadow))
    settings["timeline"] = timeline_settings(config)
    late_tail_policy = config.get("late_tail_policy", "withhold")
    if late_tail_policy not in LATE_TAIL_POLICIES:
        raise ValueError(f"late_tail_policy must be one of {LATE_TAIL_POLICIES}")
    emissions = protocol["emissions"]
    reference = templates[emissions[0]["id"]][protocol["reference_offset_frames"]:]
    arrivals, recording_reports, audits, attribution_reasons = [], {}, {}, []
    late_tail_slots = []
    for role in ("A", "B"):
        audio, rate, report = _read_recording(recordings[role], role, settings["timeline"])
        recording_reports[role] = report
        metadata = recordings[role].get("metadata") or {}
        report["attribution_metadata"] = _metadata_audit(metadata, protocol, role, rate)
        derived_reference = _at_rate(reference, protocol["sample_rate"], rate)
        audit, correlation, normalized = _event_audit(audio, derived_reference, rate, protocol)
        audits[role] = audit
        secondary = _secondary_audit(audit, correlation, rate, protocol)
        audit["secondary_events"] = secondary
        local_reasons = report["attribution_metadata"]["reasons"] + audit["reasons"]
        for emission in emissions:
            row = _arrival(audio, derived_reference, rate, emission, protocol,
                detector_settings, audit, correlation, normalized, secondary, late_tail_policy)
            row["receiver"] = role
            if row["attribution"].get("notes"):
                late_tail_slots.append({"receiver": role, "emission_id": emission["id"],
                    "emitter": emission["emitter"],
                    "secondary_count": len(row["attribution"]["secondary_events"]),
                    "delays_s": [item["delay_after_primary_s"] for item in row["attribution"]["secondary_events"]],
                    "amplitude_ratios": [item["amplitude_ratio"] for item in row["attribution"]["secondary_events"]]})
            row["template_conversion"] = {"source_rate_hz": protocol["sample_rate"],
                "reference_rate_hz": rate, "method": "none" if rate == protocol["sample_rate"] else "polyphase_reference_resampling",
                "recording_resampled": False}
            arrivals.append(row)
            if row["quality"] != "usable":
                local_reasons += [f"{emission['id']}:{reason}" for reason in row["reasons"]]
        attribution_reasons += [f"{role}:{reason}" for reason in local_reasons]
    targets = [recording_reports[role]["attribution_metadata"]["declared_coordination_target_unix_ms"] for role in ("A", "B")]
    if all(value is not None for value in targets) and abs(targets[0] - targets[1]) > METADATA_TOLERANCE_S * 1000:
        attribution_reasons.append("attribution_interdevice_coordination_targets_disagree")
    capture_reasons = [f"{role}:{reason}" for role, report in recording_reports.items() for reason in report["quality_reasons"]]
    clock, exchanges, timeline, timeline_reasons = timeline_evaluation(
        arrivals, emissions, settings, recording_reports)
    if capture_reasons:
        clock["valid"] = False
        clock["reasons"].append("recording_quality_or_continuity_failed")
    if attribution_reasons:
        clock["valid"] = False
        clock["reasons"].append("schedule_attribution_not_established")
    if capture_reasons or attribution_reasons:
        exchanges = _mark_exchanges_unusable(exchanges)
    usable = [item for item in exchanges if item["usable"]]
    valid = len(usable) == len(exchanges) == 8 and clock["valid"] and not capture_reasons and not attribution_reasons
    values = np.array([item["timing_difference_s"] for item in usable])
    center = float(np.median(values)) if valid else None
    mad = float(np.median(abs(values - center))) if valid else None
    speed = settings["speed_of_sound_m_s"]
    correction = sum(settings["self_path_m"].values()) / 2 if settings["self_path_m"] is not None else None
    equivalent = speed * center / 2 if center is not None else None
    acoustic = equivalent + correction if equivalent is not None and correction is not None else None
    spread = speed * 1.4826 * mad / 2 if mad is not None else None
    reasons = capture_reasons + attribution_reasons + clock["reasons"] + timeline_reasons
    if len(usable) < 8:
        reasons.append("insufficient_usable_exchanges")
    if correction is None:
        reasons.append("self_path_correction_not_provided")
    reasons += ["source_detector_bias_calibration_missing", "physical_error_calibration_missing", "device_body_gap_mapping_missing"]
    if acoustic is not None and acoustic < 0:
        reasons.append("negative_acoustic_path_check_self_paths_or_arrival_bias")
    return {"analysis_version": ANALYSIS_VERSION, "protocol_version": protocol["version"],
        "profile": PROFILE, "protocol_profile": PROFILE, "mode": PROFILE,
        "protocol_id": protocol["protocol_id"], "session_id": protocol["session_id"],
        "status": "diagnostic" if valid else "invalid",
        "decision": {"label": "INCONCLUSIVE", "reasons": ["No calibrated physical error bound or device-body-gap mapping. The selected arrival need not be the direct acoustic path."]},
        "summary": {"timing_difference_ms": center * 1000 if center is not None else None,
            "uncorrected_equivalent_cm": equivalent * 100 if equivalent is not None else None,
            "acoustic_path_cm": acoustic * 100 if acoustic is not None else None,
            "repeatability_cm": spread * 100 if spread is not None else None,
            "repeatability_definition": "1.4826 * median absolute deviation across paired timing equivalents; not physical confidence",
            "self_path_correction_cm": correction * 100 if correction is not None else None,
            "usable_emissions": clock["used_emissions"], "total_emissions": 16,
            "usable_exchanges": len(usable), "total_exchanges": 8,
            "detected_arrivals": sum(row["detector"]["detected"] for row in arrivals),
            "total_arrivals": 32, "ambiguous_arrivals": sum(row["quality"] == "ambiguous" for row in arrivals),
            "device_body_gap_cm": None},
        "reasons": _unique(reasons), "quality_reasons": _unique(reasons),
        "quality_warnings": [f"{role}:{warning}" for role, report in recording_reports.items() for warning in report["quality_warnings"]],
        "recordings": recording_reports, "arrivals": arrivals, "clock_fit": clock,
        "exchanges": exchanges, "timeline": timeline, "aggregate": {"timing_difference_s": center,
            "uncorrected_equivalent_m": equivalent, "acoustic_cross_path_m": acoustic,
            "self_path_correction_m": correction, "repeatability_m": spread,
            "timing_min_s": float(np.min(values)) if valid else None,
            "timing_max_s": float(np.max(values)) if valid else None,
            "device_body_gap_m": None, "calibrated_confidence_interval": None,
            "formula": "D_cross = [c * (delta_A - delta_B / rate_B_over_A) + d_AA + d_BB] / 2",
            "speed_of_sound_m_s": speed, "self_path_m": settings["self_path_m"],
            "ground_truth_used_in_calculation": False, "schedule_used_in_timing_calculation": False},
        "attribution": {"valid": not attribution_reasons, "identity": "schedule_consistent_only_not_acoustically_verified",
            "acoustic_freshness": False, "reasons": _unique(attribution_reasons),
            "settings": protocol["attribution"], "event_audits": audits,
            "late_tail_slots": late_tail_slots,
            "policy": {"late_tail_policy": late_tail_policy,
                "late_tail_max_amplitude_ratio": LATE_TAIL_MAX_AMPLITUDE_RATIO,
                "competing_min_amplitude_ratio": COMPETING_MIN_AMPLITUDE_RATIO,
                "recurrence_tolerance_s": LATE_TAIL_RECURRENCE_TOLERANCE_S,
                "recurrence_ratio_factor": LATE_TAIL_RECURRENCE_RATIO_FACTOR,
                "recurrence_min_fraction": LATE_TAIL_MIN_RECURRENCE_FRACTION,
                "recurrence_diagnostic_tolerance_s": LATE_TAIL_RECURRENCE_DIAGNOSTIC_TOLERANCE_S,
                "semantics": "withhold_keeps_every_multi_event_slot_ambiguous_separate_excuses_only_all_late_tail_slots_source_is_never_authenticated"}},
        "detector": {"paper_url": PAPER_URL, "paper_sections": ["3", "5.1", "5.2"],
            "settings": asdict(detector_settings), "reference_offset_frames": protocol["reference_offset_frames"],
            "reference_frames": protocol["reference_frames"],
            "timing_origin": "chirp_onset_in_original_recording_samples",
            "published_detector": "signed_correlation_signal_noise_norm_and_relative_peak_sharpness",
            "additional_checks": "manifest, recording continuity, disjoint slot attribution, normalized probe presence, extra-event and clock-stability audits"},
        "limitations": LIMITATIONS}
