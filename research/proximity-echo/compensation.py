"""Energy-loss compensation between heterogeneous device microphones.

Implements equations (6)–(10) and (11)–(16) from Ren et al., INFOCOM'21. For each beep
direction we average the per-beep chirp-period and echo-period spectra across L beeps,
then compute the per-frequency compensation factor

    comp(f) = sqrt( R̄_BB(f) / R̄_BA(f) · R̄_AB(f) / R̄_AA(f) )   ≈ M_B(f) / M_A(f)

and apply it to the echo spectra so that all four signatures end up multiplied by the
same microphone energy-loss factor (R̄'_AA and R̄''_AB are both in M_A units; R̄'_BB and
R̄''_BA are both in M_B units). Both pairs are then directly comparable via Pearson
correlation downstream.

The compensation factor is computed on the chirp-period frequency grid and interpolated
up to the echo-period frequency grid, since the two segments have different durations
(25 ms vs 100 ms → different rfft bin spacing).

D3.6: the interpolation is shape-preserving PCHIP with extrapolation FORBIDDEN. Every target
grid is first restricted to the OVERLAP of all contributing source grids, so no spline is ever
evaluated beyond a source's support. The previous CubicSpline(extrapolate=True) manufactured
large, oscillatory values at the band edges (where the coarse 25 ms chirp grid does not cover
the finer/wider 100 ms echo grid), which distorted the compensated cross signatures and is the
suspected cause of the documented c_a/c_b asymmetry (progress-report blocker #3).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from scipy import interpolate

from challenge_generator import BEEP_END_FREQ_HZ, BEEP_START_FREQ_HZ
from pipeline_constants import COMPENSATION_EPS as EPS


@dataclass(frozen=True)
class CompensatedSignatures:
    freqs_hz: list[float]
    sig_AA: list[float]
    sig_AB_compensated: list[float]
    sig_BB: list[float]
    sig_BA_compensated: list[float]
    # UNcompensated cross-channel echo signatures on the same echo grid (fix-plan A2.3).
    # sig_BA_raw is device A's cross channel (B's emission heard by A) in A's own mic
    # units — directly comparable to sig_AA (A's self channel). sig_AB_raw is device B's
    # cross channel comparable to sig_BB. The A2.3 spectral self-similarity guard needs the
    # RAW (pre-compensation) cross signature: an aliased cross channel re-measures the SAME
    # physical self echo, so raw sig_BA_raw ≈ sig_AA regardless of amplitude; compensation
    # (derived from the same aliased data) would partly mask that identity.
    sig_BA_raw: list[float]
    sig_AB_raw: list[float]
    compensation_at_chirp_grid: list[float]
    chirp_freqs_hz: list[float]
    n_beeps_a: int
    n_beeps_b: int
    # D3.6: count of per-beep spectra dropped by _stack_spectra because their rfft grid size
    # differed from the reference (segment truncation near the recording end, or a future
    # resample-from-44.1k path). Surfaced so validity can warn instead of silently averaging
    # over a subset.
    n_grid_mismatch_dropped: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def _stack_spectra(per_beep_entries: list[dict], emitter_role: str, segment: str) -> tuple[np.ndarray, np.ndarray, int]:
    freqs = None
    energies = []
    dropped = 0
    for entry in per_beep_entries:
        if entry["emitter_role"] != emitter_role:
            continue
        spec_freqs = np.array(entry["spectra"][f"{segment}_freqs_hz"], dtype=np.float64)
        spec_energy = np.array(entry["spectra"][f"{segment}_energy"], dtype=np.float64)
        if spec_freqs.size == 0 or spec_energy.size == 0:
            continue
        if segment == "echo" and not entry["selection"]["selection_ok"]:
            continue
        if freqs is None:
            freqs = spec_freqs
            energies.append(spec_energy)
            continue
        if spec_freqs.size != freqs.size:
            dropped += 1  # grid-size mismatch (D3.6): record instead of silently skipping
            continue
        energies.append(spec_energy)
    if freqs is None or not energies:
        return np.zeros(0), np.zeros(0), dropped
    return freqs, np.mean(np.stack(energies, axis=0), axis=0), dropped


def _overlap_bounds(source_grids: list[np.ndarray]) -> tuple[float, float] | None:
    """Tightest [max source-min, min source-max] over the non-empty source grids. Any target
    point inside this range lies within EVERY contributing source's support, so PCHIP never
    extrapolates. Returns None when no source has >=2 points (nothing to interpolate from)."""
    usable = [g for g in source_grids if g.size >= 2]
    if not usable:
        return None
    lo = max(float(g.min()) for g in usable)
    hi = min(float(g.max()) for g in usable)
    if hi <= lo:
        return None
    return lo, hi


def _interpolate_to_grid(values: np.ndarray, source_freqs: np.ndarray, target_freqs: np.ndarray) -> np.ndarray:
    if source_freqs.size < 4 or target_freqs.size == 0:
        return np.full_like(target_freqs, np.mean(values) if values.size else 0.0, dtype=np.float64)
    # Shape-preserving, no extrapolation (D3.6). Callers restrict target_freqs to the source
    # overlap, so evaluation stays within support; the clamp is a numerical-edge backstop.
    interp = interpolate.PchipInterpolator(source_freqs, values, extrapolate=False)
    clamped = np.clip(target_freqs, float(source_freqs.min()), float(source_freqs.max()))
    return interp(clamped)


def compute_compensated_signatures(per_beep_a: list[dict], per_beep_b: list[dict], low_hz: float = BEEP_START_FREQ_HZ, high_hz: float = BEEP_END_FREQ_HZ) -> CompensatedSignatures:
    """`per_beep_a` and `per_beep_b` are the per_beep arrays from extract_recording_spectra
    for device A and device B respectively. Both contain spectra for ALL beeps regardless
    of emitter; we filter by `emitter_role` here.
    """
    chirp_freqs_a_aa, chirp_AA, d1 = _stack_spectra(per_beep_a, "initiator", "chirp")
    chirp_freqs_a_ba, chirp_BA, d2 = _stack_spectra(per_beep_a, "observer", "chirp")
    chirp_freqs_b_ab, chirp_AB, d3 = _stack_spectra(per_beep_b, "initiator", "chirp")
    chirp_freqs_b_bb, chirp_BB, d4 = _stack_spectra(per_beep_b, "observer", "chirp")

    echo_freqs_a_aa, echo_AA, d5 = _stack_spectra(per_beep_a, "initiator", "echo")
    echo_freqs_b_ab, echo_AB, d6 = _stack_spectra(per_beep_b, "initiator", "echo")
    echo_freqs_b_bb, echo_BB, d7 = _stack_spectra(per_beep_b, "observer", "echo")
    echo_freqs_a_ba, echo_BA, d8 = _stack_spectra(per_beep_a, "observer", "echo")
    n_dropped = d1 + d2 + d3 + d4 + d5 + d6 + d7 + d8

    n_beeps_a = sum(1 for e in per_beep_a if e["emitter_role"] == "initiator")
    n_beeps_b = sum(1 for e in per_beep_b if e["emitter_role"] == "observer")

    chirp_grid_candidates = [g for g in (chirp_freqs_a_aa, chirp_freqs_a_ba, chirp_freqs_b_ab, chirp_freqs_b_bb) if g.size > 0]
    if not chirp_grid_candidates:
        empty = []
        return CompensatedSignatures(empty, empty, empty, empty, empty, empty, empty, empty, empty, n_beeps_a, n_beeps_b, n_dropped)
    chirp_grid = chirp_grid_candidates[0]
    band_mask = (chirp_grid >= low_hz) & (chirp_grid <= high_hz)
    chirp_grid = chirp_grid[band_mask]
    # D3.6: restrict the chirp grid to the OVERLAP of every source it will be resampled from,
    # so PCHIP never extrapolates. For a single band all four grids coincide, so this is a
    # no-op; it only bites when a direction's native segment spans a narrower range.
    chirp_overlap = _overlap_bounds([chirp_freqs_a_aa, chirp_freqs_b_ab, chirp_freqs_a_ba, chirp_freqs_b_bb])
    if chirp_overlap is not None:
        chirp_grid = chirp_grid[(chirp_grid >= chirp_overlap[0]) & (chirp_grid <= chirp_overlap[1])]

    def _resampled(values: np.ndarray, freqs: np.ndarray) -> np.ndarray:
        if values.size == 0 or freqs.size == 0:
            return np.zeros_like(chirp_grid)
        return _interpolate_to_grid(values, freqs, chirp_grid)

    R_AA = _resampled(chirp_AA, chirp_freqs_a_aa)
    R_AB = _resampled(chirp_AB, chirp_freqs_b_ab)
    R_BA = _resampled(chirp_BA, chirp_freqs_a_ba)
    R_BB = _resampled(chirp_BB, chirp_freqs_b_bb)

    ratio = (R_BB / np.maximum(R_BA, EPS)) * (R_AB / np.maximum(R_AA, EPS))
    ratio = np.clip(ratio, EPS, None)
    compensation = np.sqrt(ratio)  # ≈ M_B/M_A on chirp-period grid

    echo_grid_candidates = [g for g in (echo_freqs_a_aa, echo_freqs_a_ba, echo_freqs_b_ab, echo_freqs_b_bb) if g.size > 0]
    if not echo_grid_candidates:
        empty = []
        return CompensatedSignatures(empty, empty, empty, empty, empty, empty, empty, empty, empty, n_beeps_a, n_beeps_b, n_dropped)
    echo_grid = echo_grid_candidates[0]
    band_mask = (echo_grid >= low_hz) & (echo_grid <= high_hz)
    echo_grid = echo_grid[band_mask]
    # D3.6: the echo grid receives both the per-direction echo spectra AND the compensation
    # remapped from the chirp grid, so restrict it to the overlap of the non-empty echo sources
    # AND the chirp grid's range — no extrapolation on any of those interpolations.
    echo_overlap = _overlap_bounds([echo_freqs_a_aa, echo_freqs_a_ba, echo_freqs_b_ab, echo_freqs_b_bb, chirp_grid])
    if echo_overlap is not None:
        echo_grid = echo_grid[(echo_grid >= echo_overlap[0]) & (echo_grid <= echo_overlap[1])]

    def _on_echo_grid(values: np.ndarray, freqs: np.ndarray) -> np.ndarray:
        if values.size == 0 or freqs.size == 0:
            return np.zeros_like(echo_grid)
        return _interpolate_to_grid(values, freqs, echo_grid)

    R_prime_AA = _on_echo_grid(echo_AA, echo_freqs_a_aa)
    R_prime_AB = _on_echo_grid(echo_AB, echo_freqs_b_ab)
    R_prime_BB = _on_echo_grid(echo_BB, echo_freqs_b_bb)
    R_prime_BA = _on_echo_grid(echo_BA, echo_freqs_a_ba)

    compensation_on_echo = _interpolate_to_grid(compensation, chirp_grid, echo_grid)
    compensation_on_echo = np.clip(compensation_on_echo, EPS, None)

    R_dprime_AB = R_prime_AB / compensation_on_echo  # → M_A units, comparable to R'_AA
    R_dprime_BA = R_prime_BA * compensation_on_echo  # → M_B units, comparable to R'_BB

    return CompensatedSignatures(
        freqs_hz=echo_grid.tolist(),
        sig_AA=R_prime_AA.tolist(),
        sig_AB_compensated=R_dprime_AB.tolist(),
        sig_BB=R_prime_BB.tolist(),
        sig_BA_compensated=R_dprime_BA.tolist(),
        sig_BA_raw=R_prime_BA.tolist(),
        sig_AB_raw=R_prime_AB.tolist(),
        compensation_at_chirp_grid=compensation.tolist(),
        chirp_freqs_hz=chirp_grid.tolist(),
        n_beeps_a=n_beeps_a,
        n_beeps_b=n_beeps_b,
        n_grid_mismatch_dropped=n_dropped,
    )
