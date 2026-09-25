"""Per-beep chirp/echo energy-spectrum extraction (Section IV of Ren et al., INFOCOM'21).

For each emission `l` we extract:
  - the chirp-period segment (direct path) → energy spectrum R_l(f)
  - the echo-period segment (reflections) → energy spectrum R'_l(f)

Both are restricted to the band defined by the beep template. compensation.py combines
per-beep spectra across the four directions (AA, AB, BA, BB).

Alignment strategy (post fix-plan Phase 0, see docs/replica-findings.md): the two
interleaved schedules share the same period, so self and partner emission grids are
degenerate up to phase — no per-recording rule (amplitude, order, coherence) can tell
them apart. We therefore:
  1. detect coherent event TRAINS per recording (envelope peaks repeating each period
     with per-beep lag σ below TRAIN_COHERENCE_MAX_SIGMA_MS);
  2. assign self vs partner JOINTLY across both recordings via the clock-free sum
     identity Δ_A + Δ_B ≡ lat_A + lat_B − period (mod period);
  3. mask ONLY the assigned self train (main peak + echo tail pad) — never the partner;
  4. estimate the cross offset from the assigned partner train (sub-ms), with the
     masked sweep as fallback and consistency check;
  5. re-select cross beeps with the mask threaded through period selection
     (strongest UNMASKED candidate).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
from scipy import signal as sps

from alignment import (
    PeriodSelection,
    bandpass_filter,
    canonicalize_audio,
    matched_filter_envelope,
    select_periods_for_beep,
)
from challenge_generator import (
    BEEP_END_FREQ_HZ,
    BEEP_START_FREQ_HZ,
    BeepSpec,
    synthesize_beep,
)
from pipeline_constants import (
    A3_PRIOR_ANCHOR_HALF_WINDOW_MS,
    A3_PRIOR_BASE_HALF_WINDOW_MS,
    A3_PRIOR_MAX_HALF_WINDOW_MS,
    A3_PRIOR_RTT_HALF_WINDOW_FRACTION,
    BEEP_REFINE_HALF_WINDOW_MS,
    CROSS_BEEP_SEARCH_PAD_MS,
    DRIFT_SUPPORT_MIN_ABS_US_PER_BEEP,
    ENVELOPE_FLOOR_EPS,
    SWEEP_PEAKINESS_MEDIAN_MULTIPLE,
    SWEEP_PEAKINESS_P25_MULTIPLE,
    SWEEP_PREDICTION_TOL_MS,
    SWEEP_SEARCH_HALF_RANGE_MS,
    bandpass_edges_hz,
    beep_refine_half_window_ms,
    self_lock_sigma_ms,
    train_coherence_sigma_ms,
    ECHO_TAIL_SPAN_MS,
    MASK_PAD_AFTER_BEEP_MS,
    MASK_PAD_BEFORE_MS,
    MAX_ROUND_TRIP_MS,
    PARTNER_GAP_GUARD_MS,
    PARTNER_INAUDIBLE_FLOOR_MULTIPLE,
    PARTNER_INAUDIBLE_SELF_FRACTION,
    ROUND_TRIP_NOISE_FLOOR_MS,
    SCHEDULE_PERIOD_MS,
    SELF_LATENCY_PRIOR_MS,
    SELF_LOCK_MAX_SIGMA_MS,
    SELF_SEARCH_PAD_AFTER_MS,
    SELF_SEARCH_PAD_BEFORE_MS,
    SWEEP_MIN_UNMASKED_PREDICTIONS,
    SWEEP_STEP_MS,
    SWEEP_TRAIN_DISAGREEMENT_WARN_MS,
    TRAIN_CANDIDATE_MIN_SNR,
    TRAIN_CANDIDATES_PER_SLOT,
    TRAIN_CLUSTER_TOLERANCE_MS,
    TRAIN_COHERENCE_MAX_SIGMA_MS,
    TRAIN_MIN_STAT_SLOTS,
    TRAIN_MIN_SUPPORT_FRACTION,
)

FEATURE_VERSION = "paper_repro_v3"


def circ_signed_ms(value_ms: float, period_ms: float = SCHEDULE_PERIOD_MS) -> float:
    """Map a duration onto (-period/2, period/2] (signed circular residual)."""
    residual = float(value_ms) % period_ms
    if residual > period_ms / 2.0:
        residual -= period_ms
    return float(residual)


def platform_hint_from_user_agent(user_agent: str | None) -> str | None:
    """Best-effort platform label for the warn-only latency priors."""
    if not user_agent:
        return None
    ua = user_agent.lower()
    if "android" in ua:
        return "android"
    if "macintosh" in ua or "mac os x" in ua:
        return "mac"
    return None


@dataclass(frozen=True)
class BeepSpectra:
    chirp_freqs_hz: list[float]
    chirp_energy: list[float]
    echo_freqs_hz: list[float]
    echo_energy: list[float]
    chirp_total_energy: float
    echo_total_energy: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class EventTrain:
    """A period-coherent envelope peak train on the device's own schedule fold.

    lag_ms is the circular median lag on the self-anchored fold, in [0, period);
    mapped_lag_ms is the same folded into (-period/2, period/2] (a self train sits in
    the pass-1 window [-20, +400] after mapping). per_slot_lag_ms holds the refined
    absolute lag per self slot (NaN where the slot window was unusable or too weak).
    """

    lag_ms: float
    mapped_lag_ms: float
    sigma_ms: float
    support: int
    n_slots: int
    drift_us_per_beep: float
    median_amplitude: float
    per_slot_lag_ms: tuple
    per_slot_amplitude: tuple

    def summary(self) -> dict:
        return {
            "lag_ms": round(self.lag_ms, 3),
            "mapped_lag_ms": round(self.mapped_lag_ms, 3),
            "sigma_ms": round(self.sigma_ms, 4),
            "support": self.support,
            "n_slots": self.n_slots,
            "drift_us_per_beep": round(self.drift_us_per_beep, 2),
            "median_amplitude": round(self.median_amplitude, 4),
        }


def _energy_spectrum(segment: np.ndarray, sample_rate: int, low_hz: float, high_hz: float) -> tuple[np.ndarray, np.ndarray]:
    if len(segment) == 0:
        return np.zeros(0), np.zeros(0)
    spectrum = np.fft.rfft(segment.astype(np.float64))
    freqs = np.fft.rfftfreq(len(segment), d=1.0 / sample_rate)
    mask = (freqs >= low_hz) & (freqs <= high_hz)
    band_freqs = freqs[mask]
    band_energy = (np.abs(spectrum[mask]) ** 2).astype(np.float64)
    return band_freqs, band_energy


def extract_beep_spectra(audio: np.ndarray, sample_rate: int, selection: PeriodSelection, low_hz: float = BEEP_START_FREQ_HZ, high_hz: float = BEEP_END_FREQ_HZ) -> BeepSpectra:
    chirp_segment = audio[selection.chirp_start:selection.chirp_end]
    echo_segment = audio[selection.echo_start:selection.echo_end] if selection.echo_end > selection.echo_start else np.zeros(0, dtype=np.float32)

    chirp_freqs, chirp_energy = _energy_spectrum(chirp_segment, sample_rate, low_hz, high_hz)
    echo_freqs, echo_energy = _energy_spectrum(echo_segment, sample_rate, low_hz, high_hz)

    return BeepSpectra(
        chirp_freqs_hz=chirp_freqs.tolist(),
        chirp_energy=chirp_energy.tolist(),
        echo_freqs_hz=echo_freqs.tolist(),
        echo_energy=echo_energy.tolist(),
        chirp_total_energy=float(np.sum(chirp_energy)),
        echo_total_energy=float(np.sum(echo_energy)),
    )


# ---------------------------------------------------------------------------
# Event-train detection (replica-findings §4.1.1)
# ---------------------------------------------------------------------------

def _refine_train(envelope: np.ndarray, sample_rate: int, self_sched_ms: list[float], rough_lag_ms: float, refine_half_window_ms: float = BEEP_REFINE_HALF_WINDOW_MS) -> tuple[list[float], list[float]]:
    """Per-slot argmax refinement within ±refine_half_window_ms of sched+rough_lag.

    Returns (per_slot_lag_ms, per_slot_amplitude); NaN lag / 0 amplitude where the slot
    window is unusable. refine_half_window_ms is band-aware (D3.5): the 6-12 kHz default
    reproduces the historical ±3 ms; the render-quantized high band widens it.
    """
    half = refine_half_window_ms
    lags: list[float] = []
    amps: list[float] = []
    for sched in self_sched_ms:
        center_ms = sched + rough_lag_ms
        lo = int((center_ms - half) * sample_rate / 1000.0)
        hi = int((center_ms + half) * sample_rate / 1000.0) + 1
        lo = max(0, lo)
        hi = min(len(envelope), hi)
        if hi - lo < 3:
            lags.append(float("nan"))
            amps.append(0.0)
            continue
        window = envelope[lo:hi]
        peak = int(np.argmax(window))
        lags.append((lo + peak) / sample_rate * 1000.0 - sched)
        amps.append(float(window[peak]))
    return lags, amps


def _train_from_rough_lag(envelope: np.ndarray, sample_rate: int, self_sched_ms: list[float], rough_lag_ms: float, period_ms: float, support: int, n_slots: int, env_floor: float, coherence_sigma_ms: float = TRAIN_COHERENCE_MAX_SIGMA_MS, refine_half_window_ms: float = BEEP_REFINE_HALF_WINDOW_MS) -> EventTrain | None:
    per_slot_lag, per_slot_amp = _refine_train(envelope, sample_rate, self_sched_ms, rough_lag_ms, refine_half_window_ms)
    stat = [
        (idx, lag, amp)
        for idx, (lag, amp) in enumerate(zip(per_slot_lag, per_slot_amp))
        if not math.isnan(lag) and amp >= TRAIN_CANDIDATE_MIN_SNR * env_floor
    ]
    if len(stat) < max(TRAIN_MIN_STAT_SLOTS, int(math.ceil(TRAIN_MIN_SUPPORT_FRACTION * n_slots))):
        return None
    indices = np.array([s[0] for s in stat], dtype=np.float64)
    lags = np.array([s[1] for s in stat], dtype=np.float64)
    amps = np.array([s[2] for s in stat], dtype=np.float64)
    slope, intercept = np.polyfit(indices, lags, 1)
    residuals = lags - (slope * indices + intercept)
    sigma_ms = float(np.std(residuals))
    if sigma_ms >= coherence_sigma_ms:
        return None
    median_lag = float(np.median(lags))
    folded = median_lag % period_ms
    return EventTrain(
        lag_ms=folded,
        mapped_lag_ms=circ_signed_ms(median_lag, period_ms),
        sigma_ms=sigma_ms,
        support=len(stat),
        n_slots=n_slots,
        drift_us_per_beep=float(slope * 1000.0),
        median_amplitude=float(np.median(amps)),
        per_slot_lag_ms=tuple(per_slot_lag),
        per_slot_amplitude=tuple(per_slot_amp),
    )


def _detect_event_trains(envelope: np.ndarray, sample_rate: int, self_sched_ms: list[float], period_ms: float, coherence_sigma_ms: float = TRAIN_COHERENCE_MAX_SIGMA_MS, refine_half_window_ms: float = BEEP_REFINE_HALF_WINDOW_MS) -> list[EventTrain]:
    """Fold the matched-filter envelope mod the schedule period, anchored on the device's
    own slots, and return every coherent event train (self playout, partner arrival,
    strong echo-tail bumps). Assignment of self vs partner happens later and jointly.

    coherence_sigma_ms / refine_half_window_ms are band-aware (D3.5): the 6-12 kHz defaults
    reproduce the historical σ<2 ms gate and ±3 ms refinement; the render-quantized high band
    loosens both by one render quantum so 14-15 kHz trains (jitter 2.4-4.2 ms) are detectable."""
    if envelope.size == 0 or not self_sched_ms:
        return []
    period_samples = int(round(period_ms * sample_rate / 1000.0))
    distance_samples = max(1, int(TRAIN_CLUSTER_TOLERANCE_MS * sample_rate / 1000.0))
    env_floor = float(np.median(envelope)) + ENVELOPE_FLOOR_EPS

    candidates: list[tuple[float, float, int]] = []  # (lag_ms in [0, period), amplitude, slot_idx)
    n_slots = 0
    for slot_idx, sched in enumerate(self_sched_ms):
        start = int(round(sched * sample_rate / 1000.0))
        stop = min(len(envelope), start + period_samples)
        if start < 0 or stop - start < period_samples // 2:
            continue
        n_slots += 1
        window = envelope[start:stop]
        slot_floor = float(np.median(window)) + ENVELOPE_FLOOR_EPS
        peaks, props = sps.find_peaks(window, height=TRAIN_CANDIDATE_MIN_SNR * slot_floor, distance=distance_samples)
        if peaks.size == 0:
            continue
        strongest = np.argsort(props["peak_heights"])[::-1][:TRAIN_CANDIDATES_PER_SLOT]
        for p in peaks[strongest]:
            candidates.append((float(p) / sample_rate * 1000.0, float(window[p]), slot_idx))
    if not candidates or n_slots == 0:
        return []

    # Circular clustering: sort by lag, split at gaps wider than the cluster tolerance,
    # then merge the boundary clusters if the wrap-around gap is tight too.
    candidates.sort(key=lambda c: c[0])
    clusters: list[list[tuple[float, float, int]]] = [[candidates[0]]]
    for cand in candidates[1:]:
        if cand[0] - clusters[-1][-1][0] <= TRAIN_CLUSTER_TOLERANCE_MS:
            clusters[-1].append(cand)
        else:
            clusters.append([cand])
    if len(clusters) > 1:
        wrap_gap = candidates[0][0] + period_ms - candidates[-1][0]
        if wrap_gap <= TRAIN_CLUSTER_TOLERANCE_MS:
            first = clusters.pop(0)
            clusters[-1].extend([(lag + period_ms, amp, slot) for lag, amp, slot in first])

    trains: list[EventTrain] = []
    min_support = int(math.ceil(TRAIN_MIN_SUPPORT_FRACTION * n_slots))
    for cluster in clusters:
        strongest_per_slot: dict[int, tuple[float, float, int]] = {}
        for cand in cluster:
            slot = cand[2]
            if slot not in strongest_per_slot or cand[1] > strongest_per_slot[slot][1]:
                strongest_per_slot[slot] = cand
        if len(strongest_per_slot) < min_support:
            continue
        rough_lag = float(np.median([c[0] for c in strongest_per_slot.values()]))
        train = _train_from_rough_lag(envelope, sample_rate, self_sched_ms, rough_lag, period_ms, len(strongest_per_slot), n_slots, env_floor, coherence_sigma_ms, refine_half_window_ms)
        if train is None:
            continue
        duplicate = any(
            abs(circ_signed_ms(train.lag_ms - existing.lag_ms, period_ms)) <= TRAIN_CLUSTER_TOLERANCE_MS
            for existing in trains
        )
        if not duplicate:
            trains.append(train)
    trains.sort(key=lambda t: -t.median_amplitude)
    return trains


# ---------------------------------------------------------------------------
# Joint self/partner train assignment (replica-findings §4.1.2)
# ---------------------------------------------------------------------------

def _self_candidates(trains: list[EventTrain]) -> list[EventTrain]:
    return [
        t for t in trains
        if -SELF_SEARCH_PAD_BEFORE_MS <= t.mapped_lag_ms <= SELF_SEARCH_PAD_AFTER_MS
    ]


def _drift_support(self_a: EventTrain, self_b: EventTrain, partner_a: EventTrain, partner_b: EventTrain) -> int:
    """Supporting (never decisive) drift evidence: self trains lock to their own clock,
    partner trains drift at the inter-device rate with opposite signs across recordings."""
    threshold = DRIFT_SUPPORT_MIN_ABS_US_PER_BEEP
    score = 0
    if abs(self_a.drift_us_per_beep) < threshold:
        score += 1
    if abs(self_b.drift_us_per_beep) < threshold:
        score += 1
    if (
        abs(partner_a.drift_us_per_beep) >= threshold
        and abs(partner_b.drift_us_per_beep) >= threshold
        and partner_a.drift_us_per_beep * partner_b.drift_us_per_beep < 0
    ):
        score += 2
    return score


def _assign_single(trains: list[EventTrain], period_ms: float) -> tuple[EventTrain | None, list[str]]:
    """Fallback self-train choice when the joint sum identity cannot be applied.
    Trivial for single-train recordings; otherwise warned as ambiguous because no
    per-recording rule separates self from partner (replica-findings §4.1) — unless
    every alternative is merely an echo-tail satellite of the chosen train."""
    warnings: list[str] = []
    candidates = _self_candidates(trains)
    if not candidates:
        if trains:
            warnings.append("no_self_train_in_window")
        else:
            warnings.append("no_self_train")
        return None, warnings
    if len(candidates) == 1:
        return candidates[0], warnings
    low_drift = [t for t in candidates if abs(t.drift_us_per_beep) < DRIFT_SUPPORT_MIN_ABS_US_PER_BEEP]
    pool = low_drift or candidates
    chosen = max(pool, key=lambda t: t.median_amplitude)
    span_ms = ECHO_TAIL_SPAN_MS
    if any(not _is_satellite(t, chosen, period_ms, span_ms) for t in candidates if t is not chosen):
        warnings.append("self_train_ambiguous")
    return chosen, warnings


def _is_satellite(candidate: EventTrain, anchor: EventTrain, period_ms: float, span_ms: float) -> bool:
    """True when `candidate` is the same physical event family as `anchor`: identical,
    or a (weaker) echo-tail bump within the mask span after it. A room reflection at a
    common lag shifts self AND partner trains of one recording equally, so bump combos
    satisfy the sum identity too — they are not distinct hypotheses."""
    if candidate is anchor:
        return True
    gap = (candidate.lag_ms - anchor.lag_ms) % period_ms
    return 0.0 < gap <= span_ms and candidate.median_amplitude <= anchor.median_amplitude


def _assign_trains(trains_a: list[EventTrain], trains_b: list[EventTrain], period_ms: float) -> dict:
    """Choose (self, partner) per recording jointly across BOTH devices.

    Primary criterion: the clock-free sum identity — with lags on each device's own
    fold, L_partner_A + L_partner_B ≡ L_self_A + L_self_B (mod period), whose signed
    residual is the round-trip air time (small and positive). The identity is symmetric
    under swapping self↔partner on both sides, which negates the residual — requiring a
    (near-)positive round trip breaks the tie. Echo-bump quadruples (which satisfy the
    identity at a common lag shift) rank below quadruples built from event-family heads
    via the satellite count; drift signs are supporting evidence.
    """
    satellite_span_ms = ECHO_TAIL_SPAN_MS

    def _satellite_count(chosen: tuple, trains: list[EventTrain]) -> int:
        # How many of a device's chosen trains are echo-tail satellites of some other
        # detected train in the SAME recording. A common room-echo lag on two devices
        # produces shifted feasible quadruples (self_x + s with partner_y + s); the
        # main peaks are family heads (satellites of nothing), so quadruples built
        # from heads are preferred structurally — neither amplitude nor earliness can
        # arbitrate this on their own.
        count = 0
        for train in chosen:
            if any(
                other is not train and _is_satellite(train, other, period_ms, satellite_span_ms)
                for other in trains
            ):
                count += 1
        return count

    def _same_family(x: EventTrain, y: EventTrain) -> bool:
        # Within ONE device, self and partner must be distinct event families: a main
        # peak paired with its own echo bump satisfies the sum identity whenever both
        # devices have bumps at similar lags (the residual becomes the bump-lag
        # difference), silently re-labeling self energy as "partner" — the alias again.
        # Cost: a genuinely weaker partner inside the self echo tail (< beep+40 ms gap)
        # is declined here and degrades to the masked-sweep / partner_inaudible path.
        return _is_satellite(x, y, period_ms, satellite_span_ms) or _is_satellite(y, x, period_ms, satellite_span_ms)

    feasible = []
    for self_a in _self_candidates(trains_a):
        for self_b in _self_candidates(trains_b):
            for partner_a in trains_a:
                if partner_a is self_a or _same_family(partner_a, self_a):
                    continue
                for partner_b in trains_b:
                    if partner_b is self_b or _same_family(partner_b, self_b):
                        continue
                    round_trip = circ_signed_ms(
                        partner_a.lag_ms + partner_b.lag_ms - self_a.lag_ms - self_b.lag_ms,
                        period_ms,
                    )
                    if abs(round_trip) > MAX_ROUND_TRIP_MS:
                        continue
                    drift = _drift_support(self_a, self_b, partner_a, partner_b)
                    satellites = (
                        _satellite_count((self_a, partner_a), trains_a)
                        + _satellite_count((self_b, partner_b), trains_b)
                    )
                    key = (
                        round_trip < -ROUND_TRIP_NOISE_FLOOR_MS,  # swapped labelings go last
                        satellites,
                        -drift,
                        abs(round_trip),
                        -round_trip,
                    )
                    feasible.append({
                        "key": key,
                        "self_a": self_a,
                        "self_b": self_b,
                        "partner_a": partner_a,
                        "partner_b": partner_b,
                        "round_trip_ms": round_trip,
                        "drift_support": drift,
                    })

    warnings: list[str] = []
    if feasible:
        feasible.sort(key=lambda f: f["key"])
        best = feasible[0]
        runner_up = next(
            (
                f for f in feasible[1:]
                if not all(
                    _is_satellite(f[slot], best[slot], period_ms, satellite_span_ms)
                    for slot in ("self_a", "self_b", "partner_a", "partner_b")
                )
            ),
            None,
        )
        if (
            runner_up is not None
            and runner_up["key"][:3] == best["key"][:3]
            # Residual tie: with train-derived (sub-ms) lags, an alternative labeling is
            # only genuinely ambiguous when its round trip is within measurement noise
            # of the best one — a runner-up worse by more than the noise floor is
            # decisively outranked by |round_trip| and must not warn (the wide
            # MAX_ROUND_TRIP_MS window admits far-separation quadruples that are
            # feasible but clearly inferior).
            and abs(runner_up["round_trip_ms"]) - abs(best["round_trip_ms"]) <= ROUND_TRIP_NOISE_FLOOR_MS
        ):
            warnings.append("train_assignment_ambiguous")
        return {
            "status": "joint",
            "self_a": best["self_a"],
            "partner_a": best["partner_a"],
            "self_b": best["self_b"],
            "partner_b": best["partner_b"],
            "round_trip_ms": best["round_trip_ms"],
            "drift_support": best["drift_support"],
            "warnings": warnings,
            "warnings_a": [],
            "warnings_b": [],
        }

    # No joint solution (partner inaudible on at least one side, or trains missing):
    # assign self per recording, leave partners unassigned — the masked sweep and the
    # validity guards carry the cross channel from here.
    self_a, warnings_a = _assign_single(trains_a, period_ms)
    self_b, warnings_b = _assign_single(trains_b, period_ms)
    status = "partial" if (self_a is not None or self_b is not None) else "none"
    return {
        "status": status,
        "self_a": self_a,
        "partner_a": None,
        "self_b": self_b,
        "partner_b": None,
        "round_trip_ms": None,
        "drift_support": None,
        "warnings": warnings,
        "warnings_a": warnings_a,
        "warnings_b": warnings_b,
    }


# ---------------------------------------------------------------------------
# Self-structure mask (replica-findings §4.1.3-4)
# ---------------------------------------------------------------------------

def _build_self_mask(
    n_samples: int,
    sample_rate: int,
    self_train: EventTrain,
    self_sched_ms: list[float],
    beep_len_ms: float,
    protect_trains: list[EventTrain],
    period_ms: float,
) -> tuple[np.ndarray, list[float], list[list[float]], bool]:
    """Mask [τ − MASK_PAD_BEFORE_MS, τ + beep_len + MASK_PAD_AFTER_BEEP_MS] around each
    self-train beep position τ. NEVER masks a protected train (the assigned partner, or
    — in partial assignment — any detected non-family train that could BE the partner):
    if a protected train falls inside the self window, the mask is trimmed to
    gap − PARTNER_GAP_GUARD_MS (small-gap guard; caller warns).

    Returns (mask, positions_ms, intervals_ms, trimmed).
    """
    mask = np.zeros(n_samples, dtype=bool)
    pad_before_ms = MASK_PAD_BEFORE_MS
    span_after_ms = beep_len_ms + MASK_PAD_AFTER_BEEP_MS
    trimmed = False
    for other in protect_trains:
        gap_after = (other.lag_ms - self_train.lag_ms) % period_ms
        if gap_after < span_after_ms:
            span_after_ms = max(0.0, gap_after - PARTNER_GAP_GUARD_MS)
            trimmed = True
        gap_before = (self_train.lag_ms - other.lag_ms) % period_ms
        if gap_before < pad_before_ms:
            pad_before_ms = max(0.0, gap_before - PARTNER_GAP_GUARD_MS)
            trimmed = True

    # Lag-domain choice: a train inside the pass-1 self window keeps its mapped
    # (possibly slightly negative) lag, anchoring arrivals to THIS slot. Any other train
    # (e.g. a partner arriving late in the slot, folded lag > period/2) keeps its folded
    # [0, period) lag — mapping it would shift every mask position one slot early,
    # masking a nonexistent "slot −1" arrival and leaving the LAST real arrival unmasked.
    if -SELF_SEARCH_PAD_BEFORE_MS <= self_train.mapped_lag_ms <= SELF_SEARCH_PAD_AFTER_MS:
        base_lag_ms = self_train.mapped_lag_ms
    else:
        base_lag_ms = self_train.lag_ms
    positions_ms: list[float] = []
    intervals_ms: list[list[float]] = []
    for slot_idx, sched in enumerate(self_sched_ms):
        lag = self_train.per_slot_lag_ms[slot_idx] if slot_idx < len(self_train.per_slot_lag_ms) else float("nan")
        amp = self_train.per_slot_amplitude[slot_idx] if slot_idx < len(self_train.per_slot_amplitude) else 0.0
        if math.isnan(lag) or amp <= 0.0:
            lag = base_lag_ms  # emission happens every slot; mask the predicted spot
        else:
            # Per-slot lags are refined near the folded [0, period) lag; normalize them
            # into the same domain as the base lag.
            lag = base_lag_ms + circ_signed_ms(lag - base_lag_ms, period_ms)
        tau_ms = sched + lag
        positions_ms.append(float(tau_ms))
        lo_ms = tau_ms - pad_before_ms
        hi_ms = tau_ms + span_after_ms
        lo = max(0, int(lo_ms * sample_rate / 1000.0))
        hi = min(n_samples, int(hi_ms * sample_rate / 1000.0) + 1)
        if hi > lo:
            mask[lo:hi] = True
            intervals_ms.append([round(lo_ms, 2), round(hi_ms, 2)])
    return mask, positions_ms, intervals_ms, trimmed


# ---------------------------------------------------------------------------
# Masked cross-offset sweep (fix-plan A1.3 / A2.6)
# ---------------------------------------------------------------------------

def _score_offset(envelope: np.ndarray, mask: np.ndarray | None, sample_rate: int, cross_sched_ms: list[float], offset_ms: float, tol_samples: int) -> tuple[float, int]:
    """Average envelope over ±tol windows at the predicted cross positions, skipping
    windows that touch the self-structure mask (never averaging zeros for them)."""
    env_len = envelope.size
    total = 0.0
    count = 0
    for s_ms in cross_sched_ms:
        idx = int((s_ms + offset_ms) * sample_rate / 1000.0)
        lo = max(0, idx - tol_samples)
        hi = min(env_len, idx + tol_samples)
        if hi <= lo:
            continue
        if mask is not None and mask[lo:hi].any():
            continue
        total += float(envelope[lo:hi].mean())
        count += 1
    return (total / count if count else 0.0), count


def _estimate_cross_device_offset_ms(
    envelope: np.ndarray,
    schedule: list[dict],
    device_role: str,
    sample_rate: int,
    search_min_ms: float = -SWEEP_SEARCH_HALF_RANGE_MS,
    search_max_ms: float = SWEEP_SEARCH_HALF_RANGE_MS,
    step_ms: float = SWEEP_STEP_MS,
    mask: np.ndarray | None = None,
    self_reference_amp: float | None = None,
) -> dict:
    # Search range capped at ±900 ms to avoid the far aliasing trap: cross peaks are 1 s
    # apart, so offset and offset±1000 ms both score high (alignment one slot off).
    """Sweep candidate cross offsets, scoring each by the average matched-filter envelope
    at the predicted cross-emission positions ON THE MASKED ENVELOPE (self-locked windows
    are skipped, not zeroed; offsets with fewer than SWEEP_MIN_UNMASKED_PREDICTIONS
    unmasked predictions are ineligible).

    Returns a dict with offset_ms (None unless status == "ok"), score, status
    ("ok" | "partner_inaudible" | "cross_offset_ambiguous"), and noise_floor_env.
    """
    cross_sched_ms = [float(entry["offset_ms"]) for entry in schedule if entry["emitter_role"] != device_role]
    unmasked = envelope[~mask] if mask is not None else envelope
    noise_floor_env = float(np.median(unmasked)) if unmasked.size else 0.0
    result = {
        "offset_ms": None,
        "score": 0.0,
        "status": "cross_offset_ambiguous",
        "noise_floor_env": noise_floor_env,
        "n_eligible_offsets": 0,
    }
    if not cross_sched_ms or envelope.size == 0:
        return result

    tol_samples = int(SWEEP_PREDICTION_TOL_MS / 1000.0 * sample_rate)  # ±5 ms prediction tolerance
    n_offsets = int((search_max_ms - search_min_ms) / step_ms) + 1
    offsets_ms = np.linspace(search_min_ms, search_max_ms, n_offsets)

    scores = np.full(n_offsets, np.nan)
    for i, off in enumerate(offsets_ms):
        score, count = _score_offset(envelope, mask, sample_rate, cross_sched_ms, float(off), tol_samples)
        if count >= SWEEP_MIN_UNMASKED_PREDICTIONS:
            scores[i] = score
    eligible = ~np.isnan(scores)
    result["n_eligible_offsets"] = int(eligible.sum())
    if not eligible.any():
        return result

    best_idx = int(np.nanargmax(scores))
    best_score = float(scores[best_idx])
    result["score"] = best_score

    # A2.6 deaf-vs-ambiguous split. The masked noise floor is the median of a mostly-silent
    # envelope (~0), so a bare noise-floor multiple is a trivially-cleared bar that faint
    # leakage passed on deaf channels (phase0-rescore anomaly) — the literal partner_inaudible
    # reason never fired. The robust reference is the device's OWN self-loop matched-filter
    # amplitude: a best score below PARTNER_INAUDIBLE_SELF_FRACTION of the self loop means no
    # partner is audible. Falls back to the noise-floor multiple when no self reference is
    # available (single-recording callers with no locked self train).
    inaudible_floor = PARTNER_INAUDIBLE_FLOOR_MULTIPLE * noise_floor_env
    if self_reference_amp:
        inaudible_floor = max(inaudible_floor, PARTNER_INAUDIBLE_SELF_FRACTION * float(self_reference_amp))
    if best_score < inaudible_floor:
        result["status"] = "partner_inaudible"
        return result

    # Peakiness gate (pre-existing multipliers) — on masked scores it is meaningful
    # rather than trivially satisfied by the device's own beeps.
    noise_floor = float(np.nanpercentile(scores, 25))
    median_score = float(np.nanmedian(scores))
    if best_score < max(noise_floor * SWEEP_PEAKINESS_P25_MULTIPLE, median_score * SWEEP_PEAKINESS_MEDIAN_MULTIPLE):
        result["status"] = "cross_offset_ambiguous"
        return result

    result["status"] = "ok"
    result["offset_ms"] = float(offsets_ms[best_idx])
    return result


# ---------------------------------------------------------------------------
# Per-recording preparation and finalization
# ---------------------------------------------------------------------------

def _prepare_recording(audio_bytes: bytes | np.ndarray, schedule: list[dict], beep_spec: BeepSpec, device_role: str | None) -> dict:
    if isinstance(audio_bytes, np.ndarray):
        # Already-decoded canonical-rate audio (test/simulation convenience).
        audio = audio_bytes.astype(np.float32)
        original_rate = canonical_rate = beep_spec.sample_rate
    else:
        audio, original_rate, canonical_rate = canonicalize_audio(audio_bytes, beep_spec.sample_rate)
    # D3.5: bandpass edges from the trial's beep band, not the 6-12 kHz module constants. For
    # the 6-12 kHz protocol band this yields (5500, 12500) — identical to BANDPASS_LOW/HIGH_HZ.
    band_low_hz, band_high_hz = bandpass_edges_hz(beep_spec.start_freq_hz, beep_spec.end_freq_hz)
    filtered = bandpass_filter(audio, canonical_rate, low_hz=band_low_hz, high_hz=band_high_hz)
    beep = synthesize_beep(beep_spec)
    envelope = matched_filter_envelope(filtered, beep)

    self_sched_ms = [float(e["offset_ms"]) for e in schedule if device_role is not None and e["emitter_role"] == device_role]
    if len(self_sched_ms) >= 2:
        period_ms = float(np.median(np.diff(self_sched_ms)))
    else:
        period_ms = SCHEDULE_PERIOD_MS
    cross_sched_ms = [float(e["offset_ms"]) for e in schedule if e["emitter_role"] != device_role]
    if self_sched_ms and cross_sched_ms:
        cross_phase_ms = (cross_sched_ms[0] - self_sched_ms[0]) % period_ms
    else:
        cross_phase_ms = period_ms / 2.0

    trains = (
        _detect_event_trains(
            envelope, canonical_rate, self_sched_ms, period_ms,
            coherence_sigma_ms=train_coherence_sigma_ms(beep_spec.start_freq_hz),
            refine_half_window_ms=beep_refine_half_window_ms(beep_spec.start_freq_hz),
        )
        if device_role is not None
        else []
    )
    return {
        "audio": audio,
        "filtered": filtered,
        "envelope": envelope,
        "original_rate": original_rate,
        "canonical_rate": canonical_rate,
        "role": device_role,
        "self_sched_ms": self_sched_ms,
        "period_ms": period_ms,
        "cross_phase_ms": cross_phase_ms,
        "trains": trains,
    }


def _finalize_recording(
    prep: dict,
    schedule: list[dict],
    beep_spec: BeepSpec,
    self_train: EventTrain | None,
    partner_train: EventTrain | None,
    assignment_info: dict,
    warnings: list[str],
    platform_hint: str | None = None,
    sweep_prior: dict | None = None,
) -> dict:
    filtered = prep["filtered"]
    envelope = prep["envelope"]
    canonical_rate = prep["canonical_rate"]
    role = prep["role"]
    period_ms = prep["period_ms"]
    self_sched_ms = prep["self_sched_ms"]
    warnings = list(warnings)
    # D3.5 band-aware timing gates + spectrum band (no-op for the 6-12 kHz protocol band).
    self_lock_sigma = self_lock_sigma_ms(beep_spec.start_freq_hz)
    refine_half_window = beep_refine_half_window_ms(beep_spec.start_freq_hz)
    spectrum_low_hz = float(beep_spec.start_freq_hz)
    spectrum_high_hz = float(beep_spec.end_freq_hz)

    self_offset_ms = None
    self_locked = False
    mask = None
    positions_ms: list[float] = []
    intervals_ms: list[list[float]] = []
    if self_train is not None:
        self_offset_ms = self_train.mapped_lag_ms
        self_locked = self_train.sigma_ms < self_lock_sigma
        if not self_locked:
            warnings.append("self_lock_failed")
        prior = SELF_LATENCY_PRIOR_MS.get(platform_hint or "")
        if prior is not None and not (prior[0] <= self_train.mapped_lag_ms <= prior[1]):
            warnings.append("self_latency_outside_prior")
        if partner_train is not None:
            protect_trains = [partner_train]
        else:
            # Partial assignment: no train is CONFIRMED as the partner, but any detected
            # non-family train (not the self train, not one of its echo-tail satellites)
            # could be — "never mask the partner" must hold for those too, or the masked
            # sweep skips the true offset and re-aliases onto residual structure
            # (observed on 1703c871 device_a: partner at 17.4 ms gap, stronger than self).
            protect_trains = [
                t for t in prep["trains"]
                if t is not self_train
                and not _is_satellite(t, self_train, period_ms, ECHO_TAIL_SPAN_MS)
                and not _is_satellite(self_train, t, period_ms, ECHO_TAIL_SPAN_MS)
            ]
        mask, positions_ms, intervals_ms, trimmed = _build_self_mask(
            envelope.size, canonical_rate, self_train, self_sched_ms,
            float(beep_spec.duration_ms), protect_trains, period_ms,
        )
        if trimmed:
            warnings.append(
                "cross_partner_in_self_tail" if partner_train is not None
                else "unassigned_train_in_self_tail"
            )
    else:
        warnings.append("no_self_structure_mask")

    # Mirror mask for SELF-beep selection: the partner's arrivals land inside the self
    # echo-search range (schedule degeneracy), so the self echo period must never latch
    # onto partner structure. Built with roles swapped; the same small-gap guard then
    # protects the self peak from being masked.
    partner_mask = None
    if partner_train is not None:
        partner_mask, _, _, _ = _build_self_mask(
            envelope.size, canonical_rate, partner_train, self_sched_ms,
            float(beep_spec.duration_ms), [self_train] if self_train is not None else [], period_ms,
        )

    self_reference_amp = self_train.median_amplitude if self_train is not None else None
    # A3.3 dual-mode: prior-bounded sweep IFF a valid timing prior was supplied for this
    # device; otherwise the Phase-0 full masked sweep (default +/-900 ms bounds). Passing the
    # prior's bounds only narrows the search grid — with no prior the defaults are unchanged,
    # so pre-A3 recordings (archive/goldens) score byte-identically.
    if sweep_prior is not None:
        sweep_bounds = {
            "search_min_ms": float(sweep_prior["search_min_ms"]),
            "search_max_ms": float(sweep_prior["search_max_ms"]),
        }
        alignment_mode = "prior_bounded"
    else:
        sweep_bounds = {}
        alignment_mode = "masked_full_sweep"
    sweep = (
        _estimate_cross_device_offset_ms(
            envelope, schedule, role, canonical_rate, mask=mask,
            self_reference_amp=self_reference_amp, **sweep_bounds,
        )
        if role is not None
        else {"offset_ms": None, "score": 0.0, "status": "cross_offset_ambiguous", "noise_floor_env": 0.0, "n_eligible_offsets": 0}
    )

    cross_sched_ms = [float(e["offset_ms"]) for e in schedule if e["emitter_role"] != role]
    tol_samples = int(SWEEP_PREDICTION_TOL_MS / 1000.0 * canonical_rate)
    if partner_train is not None:
        cross_offset_ms = circ_signed_ms(partner_train.lag_ms - prep["cross_phase_ms"], period_ms)
        cross_offset_source = "partner_train"
        cross_status = "train_assigned"
        cross_offset_score, _ = _score_offset(envelope, mask, canonical_rate, cross_sched_ms, cross_offset_ms, tol_samples)
        if sweep["offset_ms"] is not None:
            if abs(circ_signed_ms(sweep["offset_ms"] - cross_offset_ms, period_ms)) > SWEEP_TRAIN_DISAGREEMENT_WARN_MS:
                warnings.append("sweep_train_disagreement")
        else:
            # The joint assignment vetted a partner train, but the independent masked sweep
            # abstained (partner_inaudible / cross_offset_ambiguous) — typically because the
            # sweep's alias peak is fainter than the A2.6 self-referenced floor. The
            # sweep_train_disagreement check above cannot fire when the sweep offset is None,
            # so surface the contradiction explicitly (warn-only; the train assignment stands).
            warnings.append("sweep_unresolved_train_assigned")
    elif sweep["status"] == "ok":
        cross_offset_ms = sweep["offset_ms"]
        cross_offset_source = "masked_sweep"
        cross_status = "sweep_only"
        cross_offset_score = sweep["score"]
    else:
        cross_offset_ms = None
        cross_offset_source = None
        cross_status = sweep["status"]  # partner_inaudible | cross_offset_ambiguous
        cross_offset_score = sweep["score"]

    # Pass 3: per-beep period selection. Self beeps anchor to their train (per-slot
    # refined τ, ±BEEP_REFINE_HALF_WINDOW_MS); cross beeps search ±200 ms around
    # schedule + cross_offset with the self mask threaded through and the strongest
    # UNMASKED candidate as τ1 (fix-plan A1.4).
    not_found = PeriodSelection(
        chirp_start=0,
        chirp_end=0,
        echo_start=0,
        echo_end=0,
        chirp_peak_value=0.0,
        echo_peak_value=0.0,
        selection_ok=False,
    )
    per_beep = []
    self_slot_idx = 0
    for entry in schedule:
        offset_ms = float(entry["offset_ms"])
        is_self = role is not None and entry["emitter_role"] == role
        if is_self:
            if self_train is not None and self_slot_idx < len(positions_ms):
                selection = select_periods_for_beep(
                    filtered, canonical_rate, beep_spec,
                    expected_offset_ms=positions_ms[self_slot_idx],
                    search_pad_before_ms=refine_half_window,
                    search_pad_after_ms=refine_half_window,
                    already_filtered=True,
                    exclusion_mask=partner_mask,
                    tau1_policy="strongest",
                )
            else:
                selection = not_found
            self_slot_idx += 1
        else:
            if cross_offset_ms is None:
                # Can't trust alignment; mark cross-device beep as not found (A1.1: this
                # rejection path used to crash on nonexistent PeriodSelection kwargs).
                selection = not_found
            else:
                selection = select_periods_for_beep(
                    filtered, canonical_rate, beep_spec,
                    expected_offset_ms=offset_ms + cross_offset_ms,
                    search_pad_before_ms=CROSS_BEEP_SEARCH_PAD_MS,
                    search_pad_after_ms=CROSS_BEEP_SEARCH_PAD_MS,
                    already_filtered=True,
                    exclusion_mask=mask,
                    tau1_policy="strongest",
                )
        spectra = extract_beep_spectra(filtered, canonical_rate, selection, low_hz=spectrum_low_hz, high_hz=spectrum_high_hz)
        per_beep.append({
            "beep_index": int(entry["beep_index"]),
            "emitter_role": entry["emitter_role"],
            "offset_ms": offset_ms,
            "selection": selection.to_dict(),
            "spectra": spectra.to_dict(),
        })

    return {
        "feature_version": FEATURE_VERSION,
        "original_sample_rate": prep["original_rate"],
        "canonical_sample_rate": canonical_rate,
        "sample_count": int(len(prep["audio"])),
        "duration_ms": float(round(len(prep["audio"]) / canonical_rate * 1000.0, 2)),
        "self_offset_ms": float(self_offset_ms) if self_offset_ms is not None else None,
        "self_locked": bool(self_locked),
        "self_train": self_train.summary() if self_train is not None else None,
        "partner_train": partner_train.summary() if partner_train is not None else None,
        "detected_trains": [t.summary() for t in prep["trains"]],
        "train_assignment": assignment_info,
        "cross_offset_ms": float(cross_offset_ms) if cross_offset_ms is not None else None,
        "cross_offset_source": cross_offset_source,
        "cross_offset_score": float(cross_offset_score),
        "cross_status": cross_status,
        "sweep": {
            "offset_ms": sweep["offset_ms"],
            "score": float(sweep["score"]),
            "status": sweep["status"],
            "noise_floor_env": float(sweep["noise_floor_env"]),
            "n_eligible_offsets": int(sweep["n_eligible_offsets"]),
        },
        "self_structure_positions_ms": [float(round(p, 3)) for p in positions_ms],
        "self_mask_intervals_ms": intervals_ms,
        "alignment_mode": alignment_mode,
        "cross_offset_prior": sweep_prior,
        "alignment_warnings": sorted(set(warnings)),
        "per_beep": per_beep,
    }


def _timing_prior_fields(timing_meta: dict | None) -> tuple[float, float, float] | None:
    """Extract the (offset_vs_server_ms, min_rtt_ms, anchor_date_now_ms) triple needed for
    the A3 cross-offset prior, or None if any field is missing/non-finite. A3 metadata is
    optional (dual-mode): a caller with no probes/anchor yields None and falls back to the
    full sweep."""
    if not timing_meta:
        return None
    offset = timing_meta.get("offset_vs_server_ms")
    rtt = timing_meta.get("min_rtt_ms")
    anchor = timing_meta.get("capture_anchor") or {}
    date_now = anchor.get("date_now_ms")
    vals = (offset, rtt, date_now)
    if any(v is None for v in vals):
        return None
    try:
        offset, rtt, date_now = (float(v) for v in vals)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (offset, rtt, date_now)) or rtt < 0:
        return None
    return offset, rtt, date_now


def _compute_cross_offset_priors(
    timing_meta_a: dict | None,
    timing_meta_b: dict | None,
    self_lat_a: float | None,
    self_lat_b: float | None,
    period_ms: float,
) -> tuple[dict | None, dict | None]:
    """A3.2/A3.3: from the two devices' websocket-time-probe offsets, min-RTTs, and
    first-onaudioprocess (Date.now) anchors, plus each device's pass-1 measured self playout
    latency, predict each cross offset and a MEASURED-uncertainty search window around it.

    The cross offset in device A's recording clock is Delta_A = lat_B + Delta_rs, where the
    record-start skew Delta_rs = (anchorB.date_now + offset_B) - (anchorA.date_now + offset_A)
    is the two WAV sample-0 wall times expressed in a common (server) clock; symmetrically
    Delta_B = lat_A - Delta_rs (their sum = lat_A + lat_B, the findings §2.4 identity mod
    period). The half-window scales with the measured per-trial uncertainty (RTT clock-offset
    error + sample-0 anchoring), NOT a fixed +/-150 ms, and is capped so a noisy network can
    never widen it back onto the +/-500 ms alias. Returns (prior_a, prior_b); a device's prior
    is None when its metadata is incomplete or the PARTNER's self latency is unavailable (a
    deaf partner means no lat to predict against — fall back to the full sweep on that side)."""
    fields_a = _timing_prior_fields(timing_meta_a)
    fields_b = _timing_prior_fields(timing_meta_b)
    if fields_a is None or fields_b is None:
        return None, None
    offset_a, rtt_a, date_now_a = fields_a
    offset_b, rtt_b, date_now_b = fields_b
    record_start_skew_ms = (date_now_b + offset_b) - (date_now_a + offset_a)

    half_window_ms = min(
        A3_PRIOR_MAX_HALF_WINDOW_MS,
        A3_PRIOR_BASE_HALF_WINDOW_MS
        + A3_PRIOR_RTT_HALF_WINDOW_FRACTION * (rtt_a + rtt_b)
        + A3_PRIOR_ANCHOR_HALF_WINDOW_MS,
    )

    def _prior(center_ms: float | None) -> dict | None:
        if center_ms is None:
            return None
        center = circ_signed_ms(center_ms, period_ms)
        return {
            "center_ms": float(round(center, 3)),
            "half_window_ms": float(round(half_window_ms, 3)),
            "search_min_ms": float(round(center - half_window_ms, 3)),
            "search_max_ms": float(round(center + half_window_ms, 3)),
            "record_start_skew_ms": float(round(record_start_skew_ms, 3)),
        }

    prior_a = _prior(self_lat_b + record_start_skew_ms) if self_lat_b is not None else None
    prior_b = _prior(self_lat_a - record_start_skew_ms) if self_lat_a is not None else None
    return prior_a, prior_b


def extract_pair_recording_spectra(
    audio_bytes_a: bytes | np.ndarray,
    audio_bytes_b: bytes | np.ndarray,
    schedule: list[dict],
    beep_spec: BeepSpec,
    role_a: str = "initiator",
    role_b: str = "observer",
    platform_hint_a: str | None = None,
    platform_hint_b: str | None = None,
    timing_meta_a: dict | None = None,
    timing_meta_b: dict | None = None,
) -> tuple[dict, dict]:
    """Joint-alignment entry point: align BOTH devices together (replica-findings
    §4.1.2), then extract per-beep spectra per recording. This is the path server.py
    and the archive re-scorer use; extract_recording_spectra remains for single-
    recording callers and degrades to per-recording (partial) assignment.

    timing_meta_a/b carry the optional A3 client timing metadata (websocket-probe
    offset_vs_server_ms + min_rtt_ms, and the first-onaudioprocess capture_anchor). When
    both are present and sufficient the cross-offset sweep is prior-bounded (A3.3); when
    absent (the archive, the goldens) the full Phase-0 masked sweep runs unchanged."""
    prep_a = _prepare_recording(audio_bytes_a, schedule, beep_spec, role_a)
    prep_b = _prepare_recording(audio_bytes_b, schedule, beep_spec, role_b)
    assignment = _assign_trains(prep_a["trains"], prep_b["trains"], prep_a["period_ms"])
    assignment_info = {
        "status": assignment["status"],
        "round_trip_ms": (
            float(round(assignment["round_trip_ms"], 3)) if assignment["round_trip_ms"] is not None else None
        ),
        "drift_support": assignment["drift_support"],
        "warnings": assignment["warnings"],
    }
    # A3 prior needs each device's pass-1 measured self playout latency (the partner's latency
    # is what the other device's cross offset is predicted against). Available now the joint
    # assignment has run, before per-recording finalize/sweep.
    self_lat_a = assignment["self_a"].mapped_lag_ms if assignment["self_a"] is not None else None
    self_lat_b = assignment["self_b"].mapped_lag_ms if assignment["self_b"] is not None else None
    prior_a, prior_b = _compute_cross_offset_priors(
        timing_meta_a, timing_meta_b, self_lat_a, self_lat_b, prep_a["period_ms"]
    )
    out_a = _finalize_recording(
        prep_a, schedule, beep_spec,
        assignment["self_a"], assignment["partner_a"], assignment_info,
        assignment["warnings"] + assignment["warnings_a"],
        platform_hint=platform_hint_a,
        sweep_prior=prior_a,
    )
    out_b = _finalize_recording(
        prep_b, schedule, beep_spec,
        assignment["self_b"], assignment["partner_b"], assignment_info,
        assignment["warnings"] + assignment["warnings_b"],
        platform_hint=platform_hint_b,
        sweep_prior=prior_b,
    )
    return out_a, out_b


def extract_recording_spectra(audio_bytes: bytes | np.ndarray, schedule: list[dict], beep_spec: BeepSpec, device_role: str | None = None, platform_hint: str | None = None) -> dict:
    """Single-recording extraction (kept for the simulation and ad-hoc callers).

    Without the partner recording the sum identity cannot run, so self/partner train
    assignment is per-recording ("partial"): trivial when only one coherent train
    exists, warned as ambiguous otherwise. The cross offset comes from the masked
    sweep. Prefer extract_pair_recording_spectra whenever both WAVs are available.
    """
    prep = _prepare_recording(audio_bytes, schedule, beep_spec, device_role)
    self_train, single_warnings = (
        _assign_single(prep["trains"], prep["period_ms"])
        if device_role is not None
        else (None, [])
    )
    assignment_info = {
        "status": "partial" if self_train is not None else "none",
        "round_trip_ms": None,
        "drift_support": None,
        "warnings": single_warnings,
    }
    return _finalize_recording(
        prep, schedule, beep_spec, self_train, None, assignment_info, single_warnings,
        platform_hint=platform_hint,
    )
