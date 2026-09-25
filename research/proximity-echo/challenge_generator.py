"""Beep template generation for the Proximity-Echo (Ren et al., INFOCOM'21) reproduction.

The paper uses a fixed 14-15 kHz linear chirp, 20 ms long, sampled at 48 kHz, played L=20
times per device per session at 0.5 s intervals. There is no per-beep frequency
randomization — matched filtering benefits from a stable template. The session seed is
retained only as a log-side identifier, not as a chirp parameter.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

# Protocol/template constants are homed in pipeline_constants.py (fix-plan D3.1) and
# re-exported here so `from challenge_generator import BEEP_START_FREQ_HZ` (and the empirical
# 6-12 kHz rationale) stay put for existing callers. pipeline_constants imports nothing from
# the pipeline, so this introduces no import cycle.
from pipeline_constants import (  # noqa: F401  (re-exported)
    BEEP_AMPLITUDE,
    BEEP_DURATION_MS,
    BEEP_END_FREQ_HZ,
    BEEP_FADE_MS,
    BEEP_START_FREQ_HZ,
    CANONICAL_SAMPLE_RATE,
)


@dataclass(frozen=True)
class BeepSpec:
    seed: int
    sample_rate: int = CANONICAL_SAMPLE_RATE
    duration_ms: int = BEEP_DURATION_MS
    start_freq_hz: float = BEEP_START_FREQ_HZ
    end_freq_hz: float = BEEP_END_FREQ_HZ
    amplitude: float = BEEP_AMPLITUDE
    sweep: str = "linear"
    fade_ms: int = BEEP_FADE_MS

    def to_dict(self) -> dict:
        return asdict(self)


def make_beep_spec(
    seed: int,
    start_freq_hz: float | None = None,
    end_freq_hz: float | None = None,
    amplitude: float | None = None,
    duration_ms: int | None = None,
) -> BeepSpec:
    start = float(start_freq_hz if start_freq_hz is not None else BEEP_START_FREQ_HZ)
    end = float(end_freq_hz if end_freq_hz is not None else BEEP_END_FREQ_HZ)
    if start <= 0 or end <= 0 or end <= start:
        raise ValueError(f"Invalid beep band: start={start}, end={end}")

    return BeepSpec(
        seed=seed,
        start_freq_hz=start,
        end_freq_hz=end,
        amplitude=float(amplitude if amplitude is not None else BEEP_AMPLITUDE),
        duration_ms=int(duration_ms if duration_ms is not None else BEEP_DURATION_MS),
    )


def synthesize_beep(spec: BeepSpec) -> np.ndarray:
    sample_count = int(spec.sample_rate * spec.duration_ms / 1000)
    if sample_count <= 1:
        raise ValueError("Beep duration is too short")

    t = np.arange(sample_count, dtype=np.float64) / float(spec.sample_rate)
    duration_s = spec.duration_ms / 1000.0
    slope = (spec.end_freq_hz - spec.start_freq_hz) / duration_s
    phase = 2.0 * np.pi * (spec.start_freq_hz * t + 0.5 * slope * (t ** 2))
    beep = spec.amplitude * np.sin(phase)

    fade_samples = min(int(spec.fade_ms * spec.sample_rate / 1000), sample_count // 2)
    if fade_samples > 1:
        ramp = 0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, fade_samples))
        beep[:fade_samples] *= ramp
        beep[-fade_samples:] *= ramp[::-1]

    return beep.astype(np.float32)
