"""Clipping detection for proximity-echo recordings (fix-plan D3.7).

A clipped recording (peak == 1.0 in float32 PCM) produces a saturated waveform that
corrupts the matched-filter and makes the echo-period analysis unreliable — but ONLY
where the saturation actually lands. The old detector tripped a trial-fatal flag on a
single clipped sample, which withheld archive trials whose clipping was a handful of
isolated samples (fractions 8e-5..2e-2, longest contiguous run < 0.7 ms) — cosmetic
saturation that never touched the analysis windows.

D3.7 replaces that with:
  * severity classification (fraction + contiguous-duration thresholds): only genuine
    WHOLE-recording saturation is fatal; sparse/short clipping is "minor";
  * per-beep localization (`clipped_beep_windows`): which beep windows a clipped run
    actually corrupts, so validity can exclude those windows and downgrade to a warning
    rather than invalidating the entire capture (clipping confined to self direct-path
    chirps must not kill the cross echo periods). A "window" is identified by its
    (emitter_role, beep_index) pair, NOT by beep_index alone: the per-beep table holds
    BOTH roles (initiator self-chirp windows and observer cross-echo windows) with
    overlapping index ranges, so keying exclusion on the index would discard a clean
    cross-echo window merely because the co-indexed self-chirp window clipped.

Clipping thresholds are in PCM full-scale units on purpose: clipping is DEFINED at the
+/-1.0 rails, a hardware-independent physical fact — not a matched-filter envelope
threshold, so D3.2's "normalize against the noise floor" rule does not apply here.
"""

from __future__ import annotations

import numpy as np

from pipeline_constants import (
    CANONICAL_SAMPLE_RATE,
    CLIP_BEEP_EXCLUDE_RUN_MS,
    CLIP_DETECT_THRESHOLD,
    CLIP_FATAL_FRACTION,
    CLIP_FATAL_RUN_MS,
    CLIP_LOCALIZE_PAD_MS,
)


def _run_lengths(mask: np.ndarray) -> np.ndarray:
    """Lengths (in samples) of each maximal contiguous run of True in `mask`."""
    if mask.size == 0 or not mask.any():
        return np.zeros(0, dtype=np.int64)
    idx = np.flatnonzero(np.diff(mask.astype(np.int8)))
    # Boundaries between runs; prepend/append the array ends.
    bounds = np.concatenate(([0], idx + 1, [mask.size]))
    lengths = np.diff(bounds)
    values = mask[bounds[:-1]]
    return lengths[values]


def detect_clipping(
    audio: np.ndarray,
    threshold: float = CLIP_DETECT_THRESHOLD,
    sample_rate: int = CANONICAL_SAMPLE_RATE,
) -> dict:
    """Detect and classify clipping in a recording (fix-plan D3.7).

    Args:
        audio: 1-D float32 audio array with samples in [-1.0, 1.0].
        threshold: Absolute sample value at or above which a sample is considered clipped.
        sample_rate: Canonical sample rate, used to express the longest run in ms.

    Returns:
        A dict with:
            clipped (bool): True if any sample meets or exceeds *threshold* (unchanged
                meaning; retained for backward compatibility and diagnostics).
            saturated (bool): True only for WHOLE-recording saturation — clipped_fraction
                >= CLIP_FATAL_FRACTION OR longest_run_ms >= CLIP_FATAL_RUN_MS. This is the
                fatal condition validity gates on; sparse/short clipping is not saturated.
            severity (str): "none" | "minor" | "saturated".
            peak (float): Maximum absolute sample value.
            clipped_sample_count (int): Number of samples at or above threshold.
            clipped_fraction (float): Fraction of total samples that clipped.
            longest_run_samples (int) / longest_run_ms (float): the longest contiguous run.
            n_runs (int): number of contiguous clipped runs.
    """
    abs_audio = np.abs(audio)
    peak = float(abs_audio.max()) if audio.size > 0 else 0.0
    clipped_mask = abs_audio >= threshold
    clipped_sample_count = int(clipped_mask.sum())
    total_samples = audio.size if audio.size > 0 else 1
    clipped_fraction = clipped_sample_count / total_samples

    runs = _run_lengths(clipped_mask)
    longest_run_samples = int(runs.max()) if runs.size else 0
    longest_run_ms = float(longest_run_samples) / float(sample_rate) * 1000.0

    saturated = (
        clipped_fraction >= CLIP_FATAL_FRACTION or longest_run_ms >= CLIP_FATAL_RUN_MS
    )
    if saturated:
        severity = "saturated"
    elif clipped_sample_count > 0:
        severity = "minor"
    else:
        severity = "none"

    return {
        "clipped": clipped_sample_count > 0,
        "saturated": bool(saturated),
        "severity": severity,
        "peak": peak,
        "clipped_sample_count": clipped_sample_count,
        "clipped_fraction": float(clipped_fraction),
        "longest_run_samples": longest_run_samples,
        "longest_run_ms": float(round(longest_run_ms, 3)),
        "n_runs": int(runs.size),
    }


def clipped_beep_windows(
    audio: np.ndarray,
    per_beep: list[dict],
    sample_rate: int,
    threshold: float = CLIP_DETECT_THRESHOLD,
    pad_ms: float = CLIP_LOCALIZE_PAD_MS,
) -> set[tuple[str, int]]:
    """Per-beep clipping localization (fix-plan D3.7).

    Returns the set of `(emitter_role, beep_index)` WINDOW IDENTITIES whose own chirp/echo
    analysis window (padded by `pad_ms`) contains a SUSTAINED clipped run
    (>= CLIP_BEEP_EXCLUDE_RUN_MS) — genuine saturation that corrupts that beep's spectrum.

    Keying by (role, index) rather than index alone is load-bearing: the per-beep table
    contains BOTH roles at each index (an initiator self-chirp window AND an observer
    cross-echo window), and a clipped run that lands only in one role's window must not
    evict the co-indexed clean window of the other role. Isolated single-sample clips are
    cosmetic and do NOT exclude a window. Excluded windows are dropped from the
    compensation/scoring stack; every un-clipped window — including the cross echo periods
    a self-chirp clip does not touch — is preserved.
    """
    if audio.size == 0:
        return set()
    clipped_mask = np.abs(audio) >= threshold
    if not clipped_mask.any():
        return set()
    pad = int(round(pad_ms / 1000.0 * sample_rate))
    min_run = max(1, int(round(CLIP_BEEP_EXCLUDE_RUN_MS / 1000.0 * sample_rate)))
    affected: set[tuple[str, int]] = set()
    n = clipped_mask.size
    for entry in per_beep:
        sel = entry.get("selection") or {}
        chirp_start = sel.get("chirp_start")
        if chirp_start is None:
            continue
        # The CHIRP-period spectrum is stacked into the compensation ratio regardless of
        # selection_ok (compensation._stack_spectra gates only the ECHO segment on it), so a
        # clipped chirp corrupts comp(f) even on an echo-selection failure. Scan the chirp
        # window unconditionally; extend through the echo window only when the echo was
        # validly selected (and hence also feeds compensation).
        if sel.get("selection_ok") and sel.get("echo_end") is not None:
            hi_raw = int(sel["echo_end"])
        elif sel.get("chirp_end") is not None:
            hi_raw = int(sel["chirp_end"])
        else:
            hi_raw = int(chirp_start)
        lo = max(0, int(chirp_start) - pad)
        hi = min(n, hi_raw + pad)
        if hi <= lo:
            continue
        runs = _run_lengths(clipped_mask[lo:hi])
        if runs.size and int(runs.max()) >= min_run:
            affected.add((str(entry["emitter_role"]), int(entry["beep_index"])))
    return affected


def apply_clipping_exclusion(audio: np.ndarray, spectra: dict, threshold: float = CLIP_DETECT_THRESHOLD) -> dict:
    """Exclude clipping-corrupted beep WINDOWS from a device's spectra IN PLACE (fix-plan
    D3.7).

    Clears the chirp/echo energy arrays of every (role, beep_index) WINDOW whose own window
    contains a sustained clipped run (so `compensation._stack_spectra` skips them: it drops
    entries with empty energy) and tags each such window with `clipped=True`. Only the
    windows that actually clipped are evicted — a clipped initiator self-chirp window no
    longer takes the clean observer cross-echo window at the same index down with it.
    selection_ok is deliberately left untouched so the per-channel ok-ratio recovery guard
    is not penalized for a cosmetic clip. Returns a small summary
    {excluded_windows, n_excluded, excluded_by_role} for the device summary / validity;
    `n_excluded` is the true number of excluded windows (not the number of unique indices).
    """
    rate = int(spectra.get("canonical_sample_rate") or CANONICAL_SAMPLE_RATE)
    per_beep = spectra.get("per_beep") or []
    affected = clipped_beep_windows(audio, per_beep, rate, threshold=threshold)
    excluded_by_role: dict[str, int] = {}
    for entry in per_beep:
        key = (str(entry["emitter_role"]), int(entry["beep_index"]))
        if key in affected:
            entry["clipped"] = True
            sp = entry.get("spectra") or {}
            for k in ("chirp_energy", "chirp_freqs_hz", "echo_energy", "echo_freqs_hz"):
                if k in sp:
                    sp[k] = []
            role = entry.get("emitter_role")
            excluded_by_role[role] = excluded_by_role.get(role, 0) + 1
        else:
            entry.setdefault("clipped", False)
    return {
        # Forensic detail: which windows were dropped, role-qualified. Sorted for a
        # deterministic (byte-identical re-score) summary.
        "excluded_windows": [
            {"emitter_role": role, "beep_index": index}
            for role, index in sorted(affected)
        ],
        "n_excluded": len(affected),
        "excluded_by_role": excluded_by_role,
    }
