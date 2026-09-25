"""Period selection (Section IV-B of Ren et al., INFOCOM'21).

For each beep emission, locate the chirp period (direct speaker→mic path) and the echo
period (first reflected sound after the direct path) inside a recorded analysis window.
The output is sample indices and segment slices; this module does NOT decide accept/reject
on its own — that is the job of feature_extraction + scoring.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from io import BytesIO

import numpy as np
import soundfile as sf
from scipy import signal

from challenge_generator import (
    BEEP_END_FREQ_HZ,
    BEEP_START_FREQ_HZ,
    CANONICAL_SAMPLE_RATE,
    BeepSpec,
    synthesize_beep,
)
from pipeline_constants import (
    CHIRP_PEAK_THRESHOLD_RATIO,
    CHIRP_PERIOD_MS,
    CHIRP_GUARD_MS,
    PERIOD_SEARCH_FALSE_ALARM_BUDGET,
    ENVELOPE_RELATIVE_PRECISION_FLOOR,
    ECHO_PERIOD_MS,
    ECHO_SEARCH_RANGE_MS,
    ENVELOPE_FLOOR_EPS,
    LOCAL_MAX_WINDOW_MS,
    SELECT_SEARCH_PAD_AFTER_MS,
    SELECT_SEARCH_PAD_BEFORE_MS,
    bandpass_edges_hz,
)

# Samples derived from the ms-denominated constants at the canonical rate (D3.1: the tunables
# live in pipeline_constants in ms/Hz; sample counts are computed, not hand-tuned).
LOCAL_MAX_WINDOW_SAMPLES = int(LOCAL_MAX_WINDOW_MS * CANONICAL_SAMPLE_RATE / 1000)
# Module-default bandpass edges for the 6-12 kHz protocol band. Per-trial callers derive the
# band from beep_spec via bandpass_edges_hz (D3.5); these remain the single-arg default.
BANDPASS_LOW_HZ, BANDPASS_HIGH_HZ = bandpass_edges_hz(BEEP_START_FREQ_HZ, BEEP_END_FREQ_HZ)


@dataclass(frozen=True)
class PeriodSelection:
    chirp_start: int
    chirp_end: int
    echo_start: int
    echo_end: int
    chirp_peak_value: float
    echo_peak_value: float
    selection_ok: bool
    failure_reason: str | None = None
    echo_noise_median: float = 0.0
    echo_threshold: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def load_audio_bytes(audio_bytes: bytes) -> tuple[np.ndarray, int]:
    audio, sample_rate = sf.read(BytesIO(audio_bytes), dtype="float32")
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)
    return audio.astype(np.float32), int(sample_rate)


def resample_audio(audio: np.ndarray, original_rate: int, target_rate: int = CANONICAL_SAMPLE_RATE) -> np.ndarray:
    if original_rate == target_rate:
        return audio.astype(np.float32)
    gcd = np.gcd(original_rate, target_rate)
    up = target_rate // gcd
    down = original_rate // gcd
    return signal.resample_poly(audio, up, down).astype(np.float32)


def canonicalize_audio(audio_bytes: bytes, target_rate: int = CANONICAL_SAMPLE_RATE) -> tuple[np.ndarray, int, int]:
    audio, original_rate = load_audio_bytes(audio_bytes)
    audio = resample_audio(audio, original_rate, target_rate)
    return audio.astype(np.float32), original_rate, target_rate


def bandpass_filter(audio: np.ndarray, sample_rate: int, low_hz: float = BANDPASS_LOW_HZ, high_hz: float = BANDPASS_HIGH_HZ) -> np.ndarray:
    nyquist = 0.5 * sample_rate
    sos = signal.butter(4, [low_hz / nyquist, high_hz / nyquist], btype="bandpass", output="sos")
    return signal.sosfiltfilt(sos, audio).astype(np.float32)


def matched_filter_envelope(audio: np.ndarray, beep: np.ndarray) -> np.ndarray:
    """Return one value per possible chirp ONSET in the input recording.

    Full convolution places zero correlation lag at len(beep)-1. A central
    ``same`` slice instead moves a 20 ms chirp's peak 10 ms past its onset,
    causing the raw chirp/echo slices to omit their first half-chirp.
    Form the analytic envelope before slicing to retain the negative-lag
    context at the beginning of a recording.
    """
    if audio.size == 0 or beep.size == 0:
        return np.zeros(audio.size, dtype=np.float64)
    template = beep[::-1].astype(np.float64)
    correlation = signal.fftconvolve(audio.astype(np.float64), template, mode="full")
    analytic = signal.hilbert(correlation)
    first = beep.size - 1
    return np.abs(analytic[first:first + audio.size]).astype(np.float64)


def find_local_maxima_with_removal(envelope: np.ndarray, threshold: float, window_samples: int = LOCAL_MAX_WINDOW_SAMPLES, search_start: int = 0, search_end: int | None = None, eligible_mask: np.ndarray | None = None) -> list[int]:
    """Thin eligible natural peaks within each Algorithm-1 sliding window.

    Compare original envelope neighbors before restricting candidates. This
    includes peaks exactly on search boundaries without manufacturing peaks
    where an exclusion mask cuts through a rising or falling envelope.
    """
    if envelope.size == 0:
        return []
    search_start = max(0, search_start)
    search_end = min(len(envelope), len(envelope) if search_end is None else search_end)
    if search_end <= search_start:
        return []
    left = np.concatenate(([-np.inf], envelope[:-1]))
    right = np.concatenate((envelope[1:], [-np.inf]))
    candidate_mask = (envelope > left) & (envelope >= right) & (envelope > threshold)
    if eligible_mask is not None:
        candidate_mask &= eligible_mask
    candidates = np.flatnonzero(candidate_mask[search_start:search_end]) + search_start
    keep = set(candidates.tolist())
    step = max(1, window_samples // 4)
    for start in range(search_start, max(search_start + 1, search_end - window_samples + 1), step):
        nearby = candidates[(candidates >= start) & (candidates < start + window_samples)]
        if nearby.size:
            peak = float(envelope[nearby].max())
            keep.difference_update(nearby[envelope[nearby] < peak].tolist())
    return sorted(keep)


def _noise_peak_threshold(values: np.ndarray) -> float:
    """Nominal per-search noise gate for a Rayleigh analytic envelope.

    For a known Rayleigh scale, a union bound over N samples gives the factor
    below. The median estimates that scale here, so this is a model-based
    engineering gate, not a guarantee for arbitrary acoustic interference.
    """
    if values.size == 0:
        return float("inf")
    median = float(np.median(values))
    factor = np.sqrt(np.log(max(1, values.size) / PERIOD_SEARCH_FALSE_ALARM_BUDGET) / np.log(2.0))
    return max(ENVELOPE_FLOOR_EPS, median * factor)


def _complete_unmasked_starts(mask: np.ndarray, length: int) -> np.ndarray:
    """An eligible onset must leave a full, uncontaminated output slice."""
    eligible = np.zeros(mask.size, dtype=bool)
    if mask.size >= length:
        prefix = np.concatenate(([0], np.cumsum(mask, dtype=np.int64)))
        eligible[:mask.size - length + 1] = prefix[length:] == prefix[:-length]
    return eligible


def select_periods(audio: np.ndarray, sample_rate: int, beep: np.ndarray, search_start_sample: int, search_end_sample: int, already_filtered: bool = False, chirp_search_end_sample: int | None = None, exclusion_mask: np.ndarray | None = None, tau1_policy: str = "first") -> PeriodSelection:
    """Find direct and reflected chirp onsets and return complete raw periods.

    The exclusion mask covers unrelated emissions. Masked or incomplete output
    slices cannot be returned. Thin natural peaks before rejecting incomplete
    slices, so truncation cannot promote a true echo's earlier sidelobes.
    ``first`` chooses the earliest direct candidate; ``strongest`` is used when
    aligning the partner's emission within a wider search window.
    """
    if tau1_policy not in ("first", "strongest"):
        raise ValueError(f"tau1_policy must be 'first' or 'strongest', got {tau1_policy!r}")
    search_start_sample = max(0, search_start_sample)
    search_end_sample = min(len(audio), search_end_sample)
    segment = audio[search_start_sample:search_end_sample]
    # Legacy/custom templates can exceed 20 ms. Their remaining direct sound
    # must never be selected as an echo after the standard 25 ms period.
    chirp_len = max(int(sample_rate * CHIRP_PERIOD_MS / 1000),
                    len(beep) + int(sample_rate * CHIRP_GUARD_MS / 1000))
    echo_len = int(sample_rate * ECHO_PERIOD_MS / 1000)
    empty = dict(chirp_start=0, chirp_end=0, echo_start=0, echo_end=0,
                 chirp_peak_value=0.0, echo_peak_value=0.0, selection_ok=False)
    if segment.size < max(len(beep), chirp_len) + echo_len:
        return PeriodSelection(**empty, failure_reason="recording_too_short")
    seg_mask = (np.asarray(exclusion_mask[search_start_sample:search_end_sample], dtype=bool)
                if exclusion_mask is not None else np.zeros(segment.size, dtype=bool))
    filtered = segment if already_filtered else bandpass_filter(segment, sample_rate)
    envelope = matched_filter_envelope(filtered, beep)
    chirp_eligible = _complete_unmasked_starts(seg_mask, chirp_len)
    chirp_search_end_local = max(0, min(len(envelope), chirp_search_end_sample - search_start_sample)) if chirp_search_end_sample is not None else len(envelope)
    chirp_eligible[chirp_search_end_local:] = False
    chirp_values = envelope[chirp_eligible]
    if chirp_values.size == 0:
        return PeriodSelection(**empty, failure_reason="no_unmasked_chirp_window")
    onset_values = envelope[:chirp_search_end_local][~seg_mask[:chirp_search_end_local]]
    local_max = float(onset_values.max()) if onset_values.size else 0.0
    # A relative peak gate alone always picks a peak in pure noise. Estimate
    # the background over the analysis segment as an additional direct gate.
    chirp_threshold = max(CHIRP_PEAK_THRESHOLD_RATIO * local_max,
                          _noise_peak_threshold(envelope[~seg_mask]))
    window_samples = max(1, int(LOCAL_MAX_WINDOW_MS * sample_rate / 1000))
    chirp_candidates = find_local_maxima_with_removal(envelope, chirp_threshold,
                                                     eligible_mask=~seg_mask,
                                                     window_samples=window_samples,
                                                     search_end=chirp_search_end_local)
    had_chirp_peak = bool(chirp_candidates)
    chirp_candidates = [idx for idx in chirp_candidates if chirp_eligible[idx]]
    if not chirp_candidates:
        reason = "chirp_window_incomplete_or_masked" if had_chirp_peak else "chirp_below_noise_threshold"
        return PeriodSelection(**empty, failure_reason=reason)
    tau_1 = max(chirp_candidates, key=lambda idx: float(envelope[idx])) if tau1_policy == "strongest" else chirp_candidates[0]
    result = dict(empty, chirp_start=search_start_sample + tau_1,
                  chirp_end=search_start_sample + tau_1 + chirp_len,
                  chirp_peak_value=float(envelope[tau_1]))

    post_start = tau_1 + chirp_len
    post_end = min(len(envelope), tau_1 + int(ECHO_SEARCH_RANGE_MS * sample_rate / 1000))
    echo_eligible = _complete_unmasked_starts(seg_mask, echo_len)
    echo_eligible[:post_start] = False
    echo_eligible[post_end:] = False
    if not np.any(echo_eligible):
        return PeriodSelection(**result, failure_reason="no_complete_unmasked_echo_window")
    post_values = envelope[post_start:post_end][~seg_mask[post_start:post_end]]
    noise_median = float(np.median(post_values))
    # This relative floor covers float32 precision and ideal bandpass ringing;
    # it is not an acoustic echo/direct amplitude requirement.
    echo_threshold = max(_noise_peak_threshold(post_values),
                         ENVELOPE_RELATIVE_PRECISION_FLOOR * float(envelope[tau_1]))
    result.update(echo_noise_median=noise_median, echo_threshold=echo_threshold)
    echo_candidates = find_local_maxima_with_removal(envelope, echo_threshold,
                                                    eligible_mask=~seg_mask,
                                                    window_samples=window_samples,
                                                    search_start=post_start, search_end=post_end)
    had_echo_peak = bool(echo_candidates)
    echo_candidates = [idx for idx in echo_candidates if echo_eligible[idx]]
    if not echo_candidates:
        reason = "echo_window_incomplete_or_masked" if had_echo_peak else "echo_below_noise_threshold"
        return PeriodSelection(**result, failure_reason=reason)
    tau_k = echo_candidates[0]
    result.update(echo_start=search_start_sample + tau_k,
                  echo_end=search_start_sample + tau_k + echo_len,
                  echo_peak_value=float(envelope[tau_k]), selection_ok=True)
    return PeriodSelection(**result)


def select_periods_for_beep(audio: np.ndarray, sample_rate: int, spec: BeepSpec, expected_offset_ms: float, search_pad_before_ms: float = SELECT_SEARCH_PAD_BEFORE_MS, search_pad_after_ms: float = SELECT_SEARCH_PAD_AFTER_MS, already_filtered: bool = False, exclusion_mask: np.ndarray | None = None, tau1_policy: str = "first") -> PeriodSelection:
    """Search for τ1 in a window around `expected_offset_ms`. The default lopsided window
    (100 ms before, 350 ms after) accommodates audio-output latency on Android/Chrome
    which routinely buffers 150–300 ms before the speaker actually fires.

    Correlation indices are raw chirp onsets. The segment includes the entire echo
    search span plus a complete echo period beyond the latest possible onset.
    """
    beep = synthesize_beep(spec)
    expected_sample = int(expected_offset_ms * sample_rate / 1000)
    pad_before = int(search_pad_before_ms * sample_rate / 1000)
    pad_after = int(search_pad_after_ms * sample_rate / 1000)
    search_start = expected_sample - pad_before
    chirp_search_end = expected_sample + pad_after + 1
    echo_period_samples = int(ECHO_PERIOD_MS * sample_rate / 1000)
    echo_search_samples = int(ECHO_SEARCH_RANGE_MS * sample_rate / 1000)
    search_end = chirp_search_end + echo_search_samples + max(echo_period_samples, len(beep))
    if audio.size < len(beep) + echo_period_samples:
        return PeriodSelection(0, 0, 0, 0, 0.0, 0.0, False, failure_reason="recording_too_short")
    if not already_filtered:
        low_hz, high_hz = bandpass_edges_hz(spec.start_freq_hz, spec.end_freq_hz)
        audio = bandpass_filter(audio, sample_rate, low_hz, high_hz)
    return select_periods(audio, sample_rate, beep, search_start, search_end, already_filtered=True, chirp_search_end_sample=chirp_search_end, exclusion_mask=exclusion_mask, tau1_policy=tau1_policy)
