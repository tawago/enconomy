"""Capture-validity checks for proximity-echo trials.

This module answers a different question than scoring:
is the acoustic measurement usable enough to trust a proximity verdict at all?
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import median

from pipeline_constants import (
    A3_PRIOR_DISAGREEMENT_MARGIN_MS,
    ALIAS_OVERLAP_MAX_COUNT,
    ALIAS_OVERLAP_TOLERANCE_MS,
    ALIAS_PARTNER_MATCH_TOLERANCE_MS,
    CROSS_OFFSET_SCORE_NOISE_FLOOR_MULTIPLE,
    CROSS_OFFSET_SCORE_SELF_FRACTION,
    CROSS_SELF_ENERGY_WARN_HIGH,
    CROSS_SELF_ENERGY_WARN_LOW,
    CROSS_SELF_SIMILARITY_MAX,
    GRID_COHERENCE_CLEAR_SELF_FRACTION,
    GRID_COHERENCE_TOLERANCE_MS,
    MAX_ROUND_TRIP_MS,
    MIN_SELECTION_OK_RATIO,
    MIN_SIGNATURE_FREQ_POINTS,
    POSSIBLE_AEC_ECHO_FRACTION,
    ROUND_TRIP_NOISE_FLOOR_MS,
    SCHEDULE_PERIOD_MS,
    SWEEP_STEP_MS,
    WEAK_DIRECT_PATH_NOISE_FLOOR_MULTIPLE,
)

VALIDITY_VERSION = "capture_validity_v3"
INTERLEAVE_MS = SCHEDULE_PERIOD_MS / 2.0


@dataclass(frozen=True)
class ChannelValidity:
    name: str
    total_beeps: int
    ok_beeps: int
    ok_ratio: float
    median_chirp_peak: float
    median_echo_peak: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CaptureValidity:
    validity_version: str
    capture_valid: bool
    failure_reasons: list[str]
    warnings: list[str]
    # Per-device breakdown of the (device-prefixed) reasons/warnings so the browser UI
    # (C2) can render them beside each device rather than as one flat pair-level list.
    device_reasons: dict[str, list[str]]
    device_warnings: dict[str, list[str]]
    channels: dict[str, dict]
    alias_overlaps: dict[str, int]
    grid_coherence_lag_ms: dict[str, float | None]
    cross_self_similarity: dict[str, float | None]
    sum_residual_ms: float | None
    signature_freq_points: int
    raw_score: float
    raw_verdict: bool
    proximity_score: float | None
    proximity_verdict: bool | None

    def to_dict(self) -> dict:
        return asdict(self)


def _truthy(value) -> bool:
    return bool(value is True or value == 1)


def _circ_signed_ms(value_ms: float, period_ms: float = SCHEDULE_PERIOD_MS) -> float:
    residual = float(value_ms) % period_ms
    if residual > period_ms / 2.0:
        residual -= period_ms
    return float(residual)


def _aec_gate_reasons(metadata: dict, device_label: str) -> list[str]:
    """A2.7 hard guard: browser/OS echo cancellation or voice isolation destroys the echo
    period at the source (the paper's core signal), so a capture with either granted is
    unusable — reject. `voiceIsolation` was present in every logged granted_track_settings
    but never read before this."""
    granted = (metadata or {}).get("granted_track_settings") or {}
    reasons = []
    if _truthy(granted.get("echoCancellation")):
        reasons.append(f"{device_label}_echo_cancellation_enabled")
    if _truthy(granted.get("voiceIsolation")):
        reasons.append(f"{device_label}_voice_isolation_enabled")
    return reasons


def _dsp_warnings(metadata: dict, device_label: str) -> list[str]:
    """A2.7 warn-only DSP flags, plus an explicit warning when the capture settings were
    never reported (OS-level processing is then invisible to getSettings())."""
    granted = (metadata or {}).get("granted_track_settings")
    warnings = []
    if not granted:
        warnings.append(f"{device_label}_capture_settings_unreported")
        return warnings
    if _truthy(granted.get("noiseSuppression")):
        warnings.append(f"{device_label}_noise_suppression_enabled")
    if _truthy(granted.get("autoGainControl")):
        warnings.append(f"{device_label}_auto_gain_control_enabled")
    # Fields that were absent from the report (vs explicitly false) leave OS processing
    # unaccounted for; note it but do not gate.
    for field in ("echoCancellation", "voiceIsolation"):
        if field not in granted:
            warnings.append(f"{device_label}_{_snake(field)}_unreported")
    return warnings


def _snake(name: str) -> str:
    out = []
    for ch in name:
        if ch.isupper():
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def _self_reference_amp(device: dict) -> float | None:
    """Self-loop matched-filter amplitude — the per-recording reference for 'what an
    audible chirp looks like' (D3.2 self-normalization). None when self was not locked."""
    train = device.get("self_train") or {}
    amp = train.get("median_amplitude")
    return float(amp) if amp else None


def _grid_coherence_lag_ms(device: dict) -> float | None:
    """A2.2: signed circular distance of (cross_offset - self_offset) to the DANGER point
    ±INTERLEAVE (mod the full period). Near 0 => the partner-prediction grid coincides with
    the device's own emission grid.

    The cross schedule is interleaved by INTERLEAVE_MS from the self schedule, so a predicted
    partner arrival at self_sched + INTERLEAVE + cross_offset lands on a self beep
    (self_sched + self_offset) exactly when (cross_offset - self_offset) ≡ ±INTERLEAVE
    (mod period) — the self-latch alias (replica-findings §4.1.6). The harmless branch
    (cross_offset - self_offset ≡ 0 mod period) puts predictions a full INTERLEAVE (500 ms,
    maximally far) from every self beep. Folding mod INTERLEAVE would collapse both branches
    to ~0 and falsely flag the harmless one, so we fold (value - INTERLEAVE) mod period and
    measure the signed distance to 0 = distance to the ±INTERLEAVE danger point."""
    cross = device.get("cross_offset_ms")
    self_off = device.get("self_offset_ms")
    if cross is None or self_off is None:
        return None
    return _circ_signed_ms(float(cross) - float(self_off) - INTERLEAVE_MS, SCHEDULE_PERIOD_MS)


def _noise_floor_env(device: dict) -> float:
    """The device's per-recording matched-filter noise floor (median of the masked envelope),
    the self-referenced denominator for the D3.2 weak-direct-path gate."""
    return float((device.get("sweep") or {}).get("noise_floor_env") or 0.0)


def _echo_chirp_fraction(channel: ChannelValidity) -> float | None:
    """A2.7 acoustic fingerprint: self echo-period energy relative to the self chirp peak."""
    if channel.median_chirp_peak <= 0.0:
        return None
    return channel.median_echo_peak / channel.median_chirp_peak


def _channel_metrics(per_beep_summary: list[dict], emitter_role: str, name: str) -> ChannelValidity:
    rows = [entry for entry in per_beep_summary if entry.get("emitter_role") == emitter_role]
    ok_rows = [entry for entry in rows if entry.get("selection_ok")]
    chirp_peaks = [float(entry.get("chirp_peak_value") or 0.0) for entry in rows]
    echo_peaks = [float(entry.get("echo_peak_value") or 0.0) for entry in rows]
    total = len(rows)
    ok = len(ok_rows)
    return ChannelValidity(
        name=name,
        total_beeps=total,
        ok_beeps=ok,
        ok_ratio=(ok / total) if total else 0.0,
        median_chirp_peak=float(median(chirp_peaks)) if chirp_peaks else 0.0,
        median_echo_peak=float(median(echo_peaks)) if echo_peaks else 0.0,
    )


def _alias_overlap_count(device: dict) -> int:
    """A2.1 guard input: number of cross-beep chirp starts landing within
    ±ALIAS_OVERLAP_TOLERANCE_MS of any masked self-structure position.

    Close-gap exemption: when the cross offset is train-assigned (joint assignment
    vetted the partner), a selection matching its PREDICTED partner arrival within
    ±ALIAS_PARTNER_MATCH_TOLERANCE_MS is the partner, not an alias — otherwise every
    legitimate trial with |gap| below the overlap tolerance is falsely rejected
    (nothing prevents gap ~0, replica-findings §3)."""
    positions_ms = device.get("self_structure_positions_ms") or []
    role = device.get("role")
    if not positions_ms or role is None:
        return 0
    cross_offset_ms = device.get("cross_offset_ms")
    partner_assigned = (
        device.get("cross_offset_source") == "partner_train" and cross_offset_ms is not None
    )
    count = 0
    for row in device.get("per_beep_summary") or []:
        if row.get("emitter_role") == role or not row.get("selection_ok"):
            continue
        chirp_start = row.get("chirp_start")
        rate = row.get("canonical_sample_rate")
        if chirp_start is None or not rate:
            continue
        chirp_ms = float(chirp_start) / float(rate) * 1000.0
        if partner_assigned and row.get("offset_ms") is not None:
            predicted_ms = float(row["offset_ms"]) + float(cross_offset_ms)
            if abs(chirp_ms - predicted_ms) <= ALIAS_PARTNER_MATCH_TOLERANCE_MS:
                continue
        if any(abs(chirp_ms - float(tau)) <= ALIAS_OVERLAP_TOLERANCE_MS for tau in positions_ms):
            count += 1
    return count


def _cross_offset_reasons(device: dict, label: str) -> list[str]:
    """Deaf-vs-ambiguous split (fix-plan A2.6): unresolved cross offsets are labelled
    by WHY they are unresolved — hardware failure vs algorithm failure."""
    if device.get("cross_offset_ms") is not None:
        return []
    status = device.get("cross_status")
    if status == "partner_inaudible":
        return [f"{label}_partner_inaudible"]
    if status == "cross_offset_ambiguous":
        return [f"{label}_cross_offset_ambiguous"]
    return [f"{label}_cross_offset_unresolved"]


def _cross_offset_prior_warning(device: dict, label: str) -> list[str]:
    """A3.4: when an A3 timing prior was applied, WARN (never gate — the A2 guards decide
    rejection) if the finally-measured cross offset disagrees with the prior center by more
    than the prior half-window plus the sweep-quantization margin. A disagreement means the
    predicted clock skew / partner latency and the measured alignment are inconsistent — a
    forensic flag, not a verdict."""
    prior = device.get("cross_offset_prior")
    if not prior:
        return []
    measured = device.get("cross_offset_ms")
    if measured is None:
        # A prior was applied but the (narrowed) sweep resolved no partner offset. The
        # deaf-vs-ambiguous classification (A2.6) then rests entirely on a window the prior
        # chose: a wrong clock reading silently narrows the sweep off the true partner and
        # gets reported as partner_inaudible/cross_offset_ambiguous with no forensic trail.
        # Surface it here so a bad clock reading is VISIBLE, not silently decisive (A3.4).
        return [f"{label}_sweep_unresolved_under_prior"]
    center = prior.get("center_ms")
    half = prior.get("half_window_ms")
    if center is None or half is None:
        return []
    if abs(_circ_signed_ms(float(measured) - float(center))) > float(half) + A3_PRIOR_DISAGREEMENT_MARGIN_MS:
        return [f"{label}_cross_offset_outside_prior"]
    return []


def _sum_residual_ms(device_a: dict, device_b: dict) -> float | None:
    """A2.5 sum-consistency: Δ_A + Δ_B must equal lat_A + lat_B − period (mod period).
    With correctly measured latencies this catches single-sided self-latch aliases
    (replica-findings §4.1.6). None when any input is missing."""
    values = [
        device_a.get("cross_offset_ms"),
        device_b.get("cross_offset_ms"),
        device_a.get("self_offset_ms"),
        device_b.get("self_offset_ms"),
    ]
    if any(v is None for v in values):
        return None
    delta_a, delta_b, lat_a, lat_b = (float(v) for v in values)
    return _circ_signed_ms(delta_a + delta_b - (lat_a + lat_b - SCHEDULE_PERIOD_MS))


def _sum_tolerance_ms(device_a: dict, device_b: dict) -> float:
    """A2.5 tolerance: the residual is the round-trip air time (bounded by
    MAX_ROUND_TRIP_MS), plus up to SWEEP_STEP_MS/2 quantization error for EACH cross
    offset that came from the 10 ms sweep grid rather than a sub-ms partner train —
    the two devices' grid errors do not cancel."""
    tolerance = MAX_ROUND_TRIP_MS
    for device in (device_a, device_b):
        if device.get("cross_offset_source") == "masked_sweep":
            tolerance += SWEEP_STEP_MS / 2.0
    return tolerance


def _cross_grid_guards(
    device: dict,
    label: str,
    channels: dict[str, ChannelValidity],
    self_similarity: float | None,
    grid_lag_ms: float | None,
) -> list[str]:
    """A2.2 (self-grid coherence) + A2.3 (spectral self-similarity), both keyed on the
    grid-coherence flag. A grid-coherent cross offset is a self-latch alias unless it is
    both LOUD (clears a high self-referenced score bar, A2.2) and spectrally UNLIKE the
    device's own self echo (A2.3). Only fires when a cross offset was chosen."""
    reasons: list[str] = []
    if grid_lag_ms is None or abs(grid_lag_ms) > GRID_COHERENCE_TOLERANCE_MS:
        return reasons
    self_ref = _self_reference_amp(device)
    score = device.get("cross_offset_score")
    # A2.2: reject unless the offset independently clears a high bar vs the self loop.
    clears = (
        self_ref is not None
        and score is not None
        and float(score) >= GRID_COHERENCE_CLEAR_SELF_FRACTION * self_ref
    )
    if not clears:
        reasons.append(f"{label}_cross_grid_coherent")
    # A2.3: high spectral self-similarity + grid coherence => re-measuring self, reject
    # even when the offset is loud (a loud self-latch is still a self-latch).
    if self_similarity is not None and self_similarity >= CROSS_SELF_SIMILARITY_MAX:
        reasons.append(f"{label}_cross_self_similar")
    return reasons


def _cross_offset_below_floor(device: dict, label: str) -> list[str]:
    """A2.8: a masked-sweep-sourced cross offset (NOT vetted by the joint train assignment)
    must clear a floor to be trusted. Floor = max(noise-floor multiple, self-loop fraction);
    the self-loop term is the robust backstop because the masked noise floor is ~0 on these
    mostly-silent envelopes. Train-assigned offsets are exempt."""
    if device.get("cross_offset_source") != "masked_sweep":
        return []
    score = device.get("cross_offset_score")
    if score is None:
        return []
    noise_floor = float((device.get("sweep") or {}).get("noise_floor_env") or 0.0)
    self_ref = _self_reference_amp(device) or 0.0
    floor = max(
        CROSS_OFFSET_SCORE_NOISE_FLOOR_MULTIPLE * noise_floor,
        CROSS_OFFSET_SCORE_SELF_FRACTION * self_ref,
    )
    if float(score) < floor:
        return [f"{label}_cross_offset_below_floor"]
    return []


def _clipping_reasons(device: dict, label: str) -> tuple[list[str], list[str]]:
    """D3.7: whole-recording saturation is fatal; sparse/short clipping (localized to a few
    beep windows, which are excluded from scoring upstream) is downgraded to a warning."""
    clipping = device.get("clipping") or {}
    if clipping.get("saturated"):
        return [f"{label}_clipped"], []
    if clipping.get("severity") == "minor" or clipping.get("clipped"):
        n_excluded = int((device.get("clipping_exclusion") or {}).get("n_excluded") or 0)
        return [], [f"{label}_clipping_localized_{n_excluded}_beeps"]
    return [], []


def _cross_self_energy_warning(device_channel: ChannelValidity, self_channel: ChannelValidity, label: str) -> list[str]:
    """A2.4 cross/self energy plausibility — WARN-ONLY (never gates: it both misses quiet
    aliases and false-positives the paper's beside-each-other scenario)."""
    self_peak = self_channel.median_chirp_peak
    cross_peak = device_channel.median_chirp_peak
    if self_peak <= 0.0 or cross_peak <= 0.0:
        return []
    ratio = cross_peak / self_peak
    if ratio < CROSS_SELF_ENERGY_WARN_LOW or ratio > CROSS_SELF_ENERGY_WARN_HIGH:
        return [f"{label}_cross_self_energy_implausible"]
    return []


def _group_by_device(items: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {"device_a": [], "device_b": [], "pair": []}
    for item in items:
        if item.startswith("device_a_"):
            grouped["device_a"].append(item[len("device_a_"):])
        elif item.startswith("device_b_"):
            grouped["device_b"].append(item[len("device_b_"):])
        else:
            grouped["pair"].append(item)
    return {k: sorted(set(v)) for k, v in grouped.items()}


def assess_capture_validity(
    device_a: dict,
    device_b: dict,
    signature_freq_points: int,
    raw_score: float,
    raw_verdict: bool,
    cross_self_similarity: dict | None = None,
    compensation_dropped_beeps: int = 0,
) -> CaptureValidity:
    failure_reasons: list[str] = []
    warnings: list[str] = []
    similarity = cross_self_similarity or {}
    # D3.6: surface (never gate on) beeps dropped from the compensation stack on rfft grid-size
    # mismatch — otherwise the compensation silently averages over a subset of the beeps.
    if compensation_dropped_beeps > 0:
        warnings.append(f"compensation_grid_mismatch_dropped_{compensation_dropped_beeps}_beeps")

    channels = {
        "AA": _channel_metrics(device_a.get("per_beep_summary") or [], "initiator", "AA"),
        "BA": _channel_metrics(device_a.get("per_beep_summary") or [], "observer", "BA"),
        "AB": _channel_metrics(device_b.get("per_beep_summary") or [], "initiator", "AB"),
        "BB": _channel_metrics(device_b.get("per_beep_summary") or [], "observer", "BB"),
    }
    # Self channel per device: AA is A's own emissions, BB is B's own.
    self_channel = {"device_a": channels["AA"], "device_b": channels["BB"]}
    cross_channel = {"device_a": channels["BA"], "device_b": channels["AB"]}

    # D3.7 clipping: fatal only on whole-recording saturation.
    for label, device in (("device_a", device_a), ("device_b", device_b)):
        clip_fatal, clip_warn = _clipping_reasons(device, label)
        failure_reasons.extend(clip_fatal)
        warnings.extend(clip_warn)

    # A2.7 AEC/voice-isolation hard guard.
    failure_reasons.extend(_aec_gate_reasons(device_a.get("metadata") or {}, "device_a"))
    failure_reasons.extend(_aec_gate_reasons(device_b.get("metadata") or {}, "device_b"))

    # A2.6 deaf-vs-ambiguous split (cross_status set by the self-referenced sweep floor).
    failure_reasons.extend(_cross_offset_reasons(device_a, "device_a"))
    failure_reasons.extend(_cross_offset_reasons(device_b, "device_b"))

    # A2.1 self-structure overlap guard (decisive).
    alias_overlaps = {
        "device_a": _alias_overlap_count(device_a),
        "device_b": _alias_overlap_count(device_b),
    }
    if any(count > ALIAS_OVERLAP_MAX_COUNT for count in alias_overlaps.values()):
        failure_reasons.append("cross_selection_self_aliased")

    # A2.2 self-grid coherence + A2.3 spectral self-similarity.
    grid_coherence_lag_ms = {
        "device_a": _grid_coherence_lag_ms(device_a),
        "device_b": _grid_coherence_lag_ms(device_b),
    }
    similarity_values = {
        "device_a": similarity.get("device_a"),
        "device_b": similarity.get("device_b"),
    }
    for label, device in (("device_a", device_a), ("device_b", device_b)):
        failure_reasons.extend(
            _cross_grid_guards(device, label, channels, similarity_values[label], grid_coherence_lag_ms[label])
        )
        # A2.8 masked-sweep cross-offset floor.
        failure_reasons.extend(_cross_offset_below_floor(device, label))

    # A2.5 sum-consistency check.
    sum_residual_ms = _sum_residual_ms(device_a, device_b)
    if sum_residual_ms is not None and abs(sum_residual_ms) > _sum_tolerance_ms(device_a, device_b):
        failure_reasons.append("cross_offset_sum_inconsistent")

    # A2.5b physically-impossible geometry. The joint round trip is the sum-identity residual
    # of the four train lags and is POSITIVE by geometry (ROUND_TRIP_NOISE_FLOOR_MS note: it
    # equals the round-trip air time, measured +0.13..+3.19 ms at touch..30 cm). A joint
    # assignment whose round trip is negative beyond the noise floor is a swapped/replica
    # mislabeling; the _assign_trains sign tie-break only DEMOTES such quadruples, so when no
    # non-negative quadruple is feasible the impossible one still wins as "joint". The A2.5
    # check above uses abs(residual) and passes it (|residual| < tolerance), and a joint
    # assignment makes BOTH devices train_assigned — exempting them from the A2.6/A2.8
    # self-referenced cross floors. Without this decisive gate the impossible alignment scores
    # as a trusted pair (and the failure is invisible in the report). round_trip is a joint
    # quantity, identical on both device dicts.
    assignment = device_a.get("train_assignment") or {}
    if assignment.get("status") == "joint":
        round_trip_ms = assignment.get("round_trip_ms")
        if round_trip_ms is not None and float(round_trip_ms) < -ROUND_TRIP_NOISE_FLOOR_MS:
            failure_reasons.append("negative_round_trip")

    # Partial-assignment self ambiguity (decisive).
    for label, device in (("device_a", device_a), ("device_b", device_b)):
        if "self_train_ambiguous" in (device.get("alignment_warnings") or []):
            failure_reasons.append(f"{label}_self_train_ambiguous")

    # D3.2: the direct-path weakness gate is normalized against each LISTENING device's own
    # per-recording matched-filter noise floor (sweep.noise_floor_env) instead of the old
    # absolute 0.02 envelope units. Channels AA/BA are heard by device_a, AB/BB by device_b.
    channel_noise_floor = {
        "AA": _noise_floor_env(device_a), "BA": _noise_floor_env(device_a),
        "AB": _noise_floor_env(device_b), "BB": _noise_floor_env(device_b),
    }
    for channel_name, metrics in channels.items():
        if metrics.total_beeps == 0:
            failure_reasons.append(f"{channel_name}_missing_beeps")
            continue
        if metrics.ok_ratio < MIN_SELECTION_OK_RATIO:
            failure_reasons.append(f"{channel_name}_low_period_recovery")
        weak_floor = WEAK_DIRECT_PATH_NOISE_FLOOR_MULTIPLE * channel_noise_floor[channel_name]
        # `<=`, not `<`: the degenerate silent-capture case (muted mic / permission failure
        # delivering digital zeros) has a masked-envelope median of exactly 0.0 AND a missing
        # noise floor, so weak_floor is also 0.0. A strict `<` would let a dead 0.0 channel PASS
        # this gate (0.0 is not < 0.0), misclassifying a dead-mic capture — which the C1 banner
        # and golden reason sets key on weak_direct_path — as a mere period-recovery problem. A
        # healthy channel has median > 3*noise, so `<=` differs from `<` only at exact equality
        # (the silent 0.0==0.0 case); it stays self-referenced (no absolute envelope threshold).
        if metrics.median_chirp_peak <= weak_floor:
            failure_reasons.append(f"{channel_name}_weak_direct_path")

    if signature_freq_points < MIN_SIGNATURE_FREQ_POINTS:
        failure_reasons.append("insufficient_signature_frequency_points")

    # A2.4 cross/self energy plausibility (warn-only) + A2.7 fingerprint (warn-only).
    for label in ("device_a", "device_b"):
        warnings.extend(_cross_self_energy_warning(cross_channel[label], self_channel[label], label))
        echo_frac = _echo_chirp_fraction(self_channel[label])
        if echo_frac is not None and echo_frac < POSSIBLE_AEC_ECHO_FRACTION:
            warnings.append(f"{label}_possible_aec_suppression")

    # A3.4 prior-vs-measured disagreement (warn-only; present only for prior-bounded trials).
    warnings.extend(_cross_offset_prior_warning(device_a, "device_a"))
    warnings.extend(_cross_offset_prior_warning(device_b, "device_b"))

    warnings.extend(_dsp_warnings(device_a.get("metadata") or {}, "device_a"))
    warnings.extend(_dsp_warnings(device_b.get("metadata") or {}, "device_b"))
    for label, device in (("device_a", device_a), ("device_b", device_b)):
        for warning in device.get("alignment_warnings") or []:
            warnings.append(f"{label}_{warning}")

    capture_valid = not failure_reasons
    return CaptureValidity(
        validity_version=VALIDITY_VERSION,
        capture_valid=capture_valid,
        failure_reasons=sorted(set(failure_reasons)),
        warnings=sorted(set(warnings)),
        device_reasons=_group_by_device(sorted(set(failure_reasons))),
        device_warnings=_group_by_device(sorted(set(warnings))),
        channels={name: metrics.to_dict() for name, metrics in channels.items()},
        alias_overlaps=alias_overlaps,
        grid_coherence_lag_ms={
            k: (float(round(v, 3)) if v is not None else None) for k, v in grid_coherence_lag_ms.items()
        },
        cross_self_similarity={
            k: (float(round(v, 5)) if v is not None else None) for k, v in similarity_values.items()
        },
        sum_residual_ms=(float(round(sum_residual_ms, 3)) if sum_residual_ms is not None else None),
        signature_freq_points=int(signature_freq_points),
        raw_score=float(raw_score),
        raw_verdict=bool(raw_verdict),
        proximity_score=float(raw_score) if capture_valid else None,
        proximity_verdict=bool(raw_verdict) if capture_valid else None,
    )
