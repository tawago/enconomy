"""Pearson-correlation proximity score on smoothed echo-period signatures.

Implements Section IV-D-2 of Ren et al., INFOCOM'21:
  c_A = corr( smooth(R̄'_AA),  smooth(R̄''_AB) )
  c_B = corr( smooth(R̄'_BB),  smooth(R̄''_BA) )
  final = (c_A + c_B) / 2          (score_mode="mean", default)
  accept if final ≥ c_th (paper: 0.78)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from pipeline_constants import DEFAULT_VERDICT_THRESHOLD, SMOOTH_WINDOW_HZ

CLASSIFIER_VERSION = "paper_pearson_v2"


def _window_bins(freqs_hz: np.ndarray) -> int:
    """D3.4: convert the Hz-denominated smoothing bandwidth to a boxcar width in FFT bins,
    using the ACTUAL echo-grid resolution (median bin spacing). Historically the window was a
    fixed 20 bins, whose Hz bandwidth silently changed with the echo-segment duration; keying
    it to SMOOTH_WINDOW_HZ makes the smoothing band/duration invariant. The 100 ms echo grid at
    48 kHz has a 10 Hz bin, so SMOOTH_WINDOW_HZ=200 -> 20 bins, reproducing the historical value
    on the 6-12 kHz archive. Falls back to 1 bin (no smoothing) when the grid is too small to
    measure a spacing."""
    freqs = np.asarray(freqs_hz, dtype=np.float64)
    if freqs.size < 2:
        return 1
    bin_hz = float(np.median(np.diff(freqs)))
    if bin_hz <= 0.0:
        return 1
    return max(1, int(round(SMOOTH_WINDOW_HZ / bin_hz)))


@dataclass(frozen=True)
class ProximityScore:
    classifier_version: str
    threshold: float
    c_a: float
    c_b: float
    score: float
    verdict: bool
    score_mode: str
    smoothed_AA: list[float]
    smoothed_AB: list[float]
    smoothed_BB: list[float]
    smoothed_BA: list[float]
    freqs_hz: list[float]

    def to_dict(self) -> dict:
        return asdict(self)


def _smooth(values: np.ndarray, window: int) -> np.ndarray:
    if values.size == 0:
        return values
    window = max(1, min(window, values.size))
    kernel = np.ones(window, dtype=np.float64) / window
    return np.convolve(values, kernel, mode="same")


def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    if a.size == 0 or b.size == 0 or a.size != b.size:
        return 0.0
    a_centered = a - np.mean(a)
    b_centered = b - np.mean(b)
    denom = float(np.linalg.norm(a_centered) * np.linalg.norm(b_centered))
    if denom < 1e-12:
        return 0.0
    return float(np.dot(a_centered, b_centered) / denom)


def cross_self_similarity(signatures: dict) -> dict:
    """A2.3 raw material: per device, the Pearson correlation between the device's OWN
    self-channel echo signature and its (uncompensated) cross-channel echo signature —
    both measured by the same microphone on the same echo grid.

      device_a: corr( smooth(sig_AA), smooth(sig_BA_raw) )   (A's self vs A's cross)
      device_b: corr( smooth(sig_BB), smooth(sig_AB_raw) )   (B's self vs B's cross)

    An ALIASED cross channel silently re-measures the device's own self echo, so this
    correlation is near 1 regardless of amplitude — the signature amplitude checks (A2.4)
    provably miss. High similarity is NOT sufficient to reject on its own (a legitimate
    beside-each-other pair genuinely has cross ≈ self); it becomes decisive only combined
    with a grid-coherence flag (A2.2), which is how validity consumes it."""
    window = _window_bins(np.array(signatures.get("freqs_hz") or [], dtype=np.float64))

    def _corr(self_key: str, cross_key: str) -> float | None:
        self_sig = np.array(signatures.get(self_key) or [], dtype=np.float64)
        cross_sig = np.array(signatures.get(cross_key) or [], dtype=np.float64)
        if self_sig.size == 0 or cross_sig.size == 0 or self_sig.size != cross_sig.size:
            return None
        return _pearson(_smooth(self_sig, window), _smooth(cross_sig, window))

    return {
        "device_a": _corr("sig_AA", "sig_BA_raw"),
        "device_b": _corr("sig_BB", "sig_AB_raw"),
    }


def score_proximity(
    signatures: dict,
    verdict_threshold: float = DEFAULT_VERDICT_THRESHOLD,
    score_mode: str = "mean",
) -> ProximityScore:
    """Compute proximity score from echo-period signatures.

    Parameters
    ----------
    signatures:
        Dict containing freqs_hz, sig_AA, sig_AB_compensated, sig_BB,
        sig_BA_compensated arrays.
    verdict_threshold:
        Acceptance threshold (default 0.78, per paper).
    score_mode:
        "mean" (default) — score = (c_a + c_b) / 2, matching the paper.
    """
    if score_mode != "mean":
        raise ValueError(f"score_mode must be 'mean', got {score_mode!r}")

    freqs = np.array(signatures["freqs_hz"], dtype=np.float64)
    sig_AA = np.array(signatures["sig_AA"], dtype=np.float64)
    sig_AB = np.array(signatures["sig_AB_compensated"], dtype=np.float64)
    sig_BB = np.array(signatures["sig_BB"], dtype=np.float64)
    sig_BA = np.array(signatures["sig_BA_compensated"], dtype=np.float64)

    window = _window_bins(freqs)
    smoothed_AA = _smooth(sig_AA, window)
    smoothed_AB = _smooth(sig_AB, window)
    smoothed_BB = _smooth(sig_BB, window)
    smoothed_BA = _smooth(sig_BA, window)

    c_a = _pearson(smoothed_AA, smoothed_AB)
    c_b = _pearson(smoothed_BB, smoothed_BA)

    score = float((c_a + c_b) / 2.0)

    verdict = bool(score >= verdict_threshold)

    return ProximityScore(
        classifier_version=CLASSIFIER_VERSION,
        threshold=float(verdict_threshold),
        c_a=float(round(c_a, 5)),
        c_b=float(round(c_b, 5)),
        score=float(round(score, 5)),
        verdict=verdict,
        score_mode=score_mode,
        smoothed_AA=smoothed_AA.tolist(),
        smoothed_AB=smoothed_AB.tolist(),
        smoothed_BB=smoothed_BB.tolist(),
        smoothed_BA=smoothed_BA.tolist(),
        freqs_hz=freqs.tolist(),
    )
