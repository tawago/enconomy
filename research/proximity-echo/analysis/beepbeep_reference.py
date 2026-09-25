"""Offline BeepBeep waveform and signed-correlation detector reference.

Primary source: Peng, Shen and Zhang, ACM TECS 2012, sections 5.1 and 5.2,
https://www.cs.purdue.edu/homes/chunyi/pubs/peng-tecs12.pdf

The paper specifies a 50 ms 2-6 kHz linear chirp preceded by a 5 ms 2 kHz
cosine, and correlation signal/noise norm and peak-sharpness ratios. It does
not completely specify the shadow-window extent, neighborhood endpoints,
waveform amplitude/phase, or whether the warmup enters the reference. These
conventions are explicit below. This is a method reference, not original code.

Saved ranging-v1 recordings contain different 32 ms 4-9 kHz random-phase
templates. Applying this detector to those exact templates is a detector-only
ablation, never a faithful waveform reproduction or a physical distance test.
No distance label, prior report, differential-fit gate, or live verdict is read.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from scipy import signal
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.inspect_ranging_channels import validate_protocol
from ranging_analysis import _read_recording

PAPER_URL = "https://www.cs.purdue.edu/homes/chunyi/pubs/peng-tecs12.pdf"


@dataclass(frozen=True)
class DetectorSettings:
    shadow_window_ms: float = 10.0  # Explicit implementation assumption.
    signal_noise_norm_ratio: float = 2.0
    relative_peak_sharpness: float = .85
    paper_window_samples: int = 100
    paper_sample_rate_hz: int = 44100


def _frames(seconds, sample_rate):
    """Round half up, avoiding the implicit half-even choice for 220.5 frames."""
    return int(np.floor(seconds * sample_rate + .5))


def reference_waveform(sample_rate=44100, amplitude=.16):
    """Return playback and chirp-only reference with explicit sample origins."""
    if sample_rate < 12000 or not 0 < amplitude <= 1:
        raise ValueError("Require sample rate >= 12 kHz and amplitude in (0, 1]")
    warmup_frames, chirp_frames = _frames(.005, sample_rate), _frames(.050, sample_rate)
    warmup_time = np.arange(warmup_frames) / sample_rate
    chirp_time = np.arange(chirp_frames) / sample_rate
    warmup = amplitude * np.cos(2 * np.pi * 2000 * warmup_time)
    phase = 2 * np.pi * 2000 * warmup_frames / sample_rate
    chirp = amplitude * np.cos(phase + 2 * np.pi * (2000 * chirp_time + .5 * (4000 / .050) * chirp_time**2))
    return {"playback": np.r_[warmup, chirp], "reference": chirp,
        "metadata": {"sample_rate_hz": sample_rate, "warmup_frames": warmup_frames,
            "chirp_frames": chirp_frames, "template_origin_in_playback_frames": warmup_frames,
            "arrival_semantics": "Correlation lag locates chirp start; subtract warmup_frames for playback start.",
            "conventions": ["Chirp-only reference; paper gives N=2205 for 50 ms at 44.1 kHz.",
                "Cosine phase is continuous at the rounded warmup boundary.",
                "Durations round half up; no amplitude taper; digital amplitude is an implementation choice."]}}


def _window(values, center, width):
    start = center - width // 2
    end = start + width
    if start < 0 or end > len(values):
        raise ValueError("Complete correlation neighborhood is unavailable")
    return values[start:end], [int(start), int(end)]


def detect_arrival(recording, reference, sample_rate, settings=DetectorSettings()):
    """Strongest positive match, then earliest comparable sharp positive peak.

    The signed linear time-domain correlation is computed with FFT acceleration.
    No Hilbert envelope, whitening, phase ratio, or fractional interpolation is
    used. A selected peak is a detector candidate, not an identified direct path.
    """
    recording, reference = np.asarray(recording, float), np.asarray(reference, float)
    if recording.ndim != 1 or reference.ndim != 1 or len(reference) < 2 or len(recording) < len(reference):
        raise ValueError("Require mono recording and complete nonempty reference")
    if not np.isfinite(recording).all() or not np.isfinite(reference).all() or not np.any(reference):
        raise ValueError("Require finite samples and a nonzero reference")
    if not np.isfinite(sample_rate) or sample_rate <= 0 or not np.isfinite(settings.shadow_window_ms) or settings.shadow_window_ms <= 0:
        raise ValueError("Sample rate and shadow-window duration must be positive")
    width = _frames(settings.paper_window_samples / settings.paper_sample_rate_hz, sample_rate)
    correlation = signal.correlate(recording, reference, mode="valid", method="fft")
    strongest = int(np.argmax(correlation))
    result = {"detected": False, "selected_frame": None, "strongest_positive_frame": strongest,
        "strongest_positive_correlation": float(correlation[strongest]),
        "window_samples": width, "shadow_window_ms": settings.shadow_window_ms,
        "signal_noise_norm_ratio": None, "candidates": [], "reason": None}
    if correlation[strongest] <= 0:
        result["reason"] = "no_positive_correlation"
        return result
    try:
        signal_window, signal_bounds = _window(correlation, strongest, width)
        noise_end = strongest - len(reference)
        noise_start = noise_end - width
        if noise_start < 0:
            raise ValueError("Noise window at least one reference length before the peak is unavailable")
        noise_window = correlation[noise_start:noise_end]
        signal_norm, noise_norm = float(np.linalg.norm(signal_window)), float(np.linalg.norm(noise_window))
        # Exact silent background is represented without infinity in JSON.
        ratio = signal_norm / noise_norm if noise_norm > 0 else None
        detected = signal_norm > 0 and (noise_norm == 0 or ratio > settings.signal_noise_norm_ratio)
        result.update({"signal_noise_norm_ratio": ratio, "signal_l2_norm": signal_norm,
            "noise_l2_norm": noise_norm, "noise_is_exact_zero": noise_norm == 0,
            "signal_window_lags": signal_bounds, "noise_window_lags": [int(noise_start), int(noise_end)]})
        if not detected:
            result["reason"] = "published_signal_noise_ratio_not_met"
            return result
        strongest_mean_abs = float(np.mean(abs(signal_window)))
        strongest_sharpness = float(correlation[strongest] / strongest_mean_abs)
        first = max(width // 2, strongest - _frames(settings.shadow_window_ms / 1000, sample_rate))
        peaks, _ = signal.find_peaks(correlation[first:strongest + 2])
        peaks = list(first + peaks)
        if strongest not in peaks:
            peaks.append(strongest)
        # Include a local peak on the left search boundary; find_peaks omits it.
        if first > 0 and correlation[first] > correlation[first - 1] and correlation[first] > correlation[first + 1]:
            peaks.append(first)
        candidates = []
        for peak in sorted(set(peaks)):
            if peak > strongest or correlation[peak] <= 0:
                continue
            vicinity, _ = _window(correlation, int(peak), width)
            mean_abs = float(np.mean(abs(vicinity)))
            sharpness = float(correlation[peak] / mean_abs) if mean_abs else 0.
            candidates.append({"frame": int(peak), "correlation": float(correlation[peak]),
                "sharpness": sharpness, "sharpness_relative_to_strongest": sharpness / strongest_sharpness,
                "meets_published_sharpness": sharpness > settings.relative_peak_sharpness * strongest_sharpness})
        selected = next(p["frame"] for p in candidates if p["meets_published_sharpness"])
        result.update({"detected": True, "selected_frame": selected,
            "selected_relative_to_strongest_samples": selected - strongest,
            "strongest_peak_sharpness": strongest_sharpness,
            "shadow_window_lags": [int(first), strongest], "candidates": candidates})
    except ValueError as exc:
        result["reason"] = str(exc)
    return result


def inspect_saved_trial(directory, settings=DetectorSettings()):
    """Apply only the detector to original exact templates, reporting 32 rows."""
    directory = Path(directory)
    protocol_path = directory / "protocol.json"
    protocol = json.loads(protocol_path.read_text())
    templates = validate_protocol(protocol)
    audio, quality, inputs = {}, {}, [protocol_path]
    for receiver in "AB":
        upload, wav = directory / f"upload_{receiver}.json", directory / f"recording_{receiver}.wav"
        metadata = json.loads(upload.read_text())["metadata"]
        pcm, rate, quality[receiver] = _read_recording({"wav_path": wav, "metadata": metadata}, receiver)
        if rate != protocol["sample_rate"] or not quality[receiver]["usable"]:
            raise ValueError(f"Original capture {receiver} failed quality checks: {quality[receiver]['quality_reasons']}")
        audio[receiver] = pcm
        inputs.extend([upload, wav])
    arrivals, by_id = [], {}
    for emission in protocol["emissions"]:
        for receiver in "AB":
            detection = detect_arrival(audio[receiver], templates[emission["id"]], protocol["sample_rate"], settings)
            row = {"emission": emission["id"], "pair_index": emission["pair_index"],
                   "path": emission["emitter"] + receiver, **detection}
            arrivals.append(row)
            by_id[(emission["id"], receiver)] = detection
    identity_conflicts = []
    for receiver in "AB":
        ordered = [row for row in arrivals if row["path"][1] == receiver]
        for previous, current in zip(ordered, ordered[1:]):
            left, right = previous["selected_frame"], current["selected_frame"]
            if left is not None and right is not None and right - left < protocol["probe_frames"]:
                identity_conflicts.append({"receiver": receiver, "earlier_emission": previous["emission"],
                    "later_emission": current["emission"], "reason": "selected_identity_windows_reversed_or_overlapping"})
    identity_order_verified = not identity_conflicts and all(row["detected"] for row in arrivals)
    pairs = []
    fs = protocol["sample_rate"]
    for index in range(8):
        a, b = f"e{2 * index:02d}", f"e{2 * index + 1:02d}"
        aa, ab, ba, bb = [by_id[key]["selected_frame"] for key in ((a, "A"), (a, "B"), (b, "A"), (b, "B"))]
        value = None if any(t is None for t in (aa, ab, ba, bb)) else (ab + ba - aa - bb) / fs * 1e6
        pairs.append({"pair_index": index, "nominal_cross_minus_self_timing_us": value if identity_order_verified else None,
            "unverified_selected_lag_combination_us": value})
    return {"trial_id": directory.name, "scope": "detector_only_ablation_on_existing_random_phase_templates",
        "physical_arrival_validated": False, "physical_distance_m": None, "arrivals": arrivals,
        "detected_count": sum(row["detected"] for row in arrivals),
        "detected_count_semantics": "Number passing the correlation energy ratio; this does not verify emission identity or first arrival.",
        "identity_order_verified": identity_order_verified, "identity_conflicts": identity_conflicts,
        "nominal_timing_pairs": pairs,
        "identity_caveat": "Global signed matching across independent random templates can select a different emission. Invalid chronological identities withhold combined timing. This is an adaptation failure, not a test of schedule-separated BeepBeep chirps.",
        "timing_caveat": "Nominal sample rates only; no clock-skew, channel-delay or self-path calibration. Values are detector outputs, not physical distance.",
        "input_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}}


def report(trial_directories, settings=DetectorSettings()):
    here = Path(__file__)
    return {"version": "beepbeep-reference-v1", "paper": {"url": PAPER_URL, "sections": ["5.1", "5.2"]},
        "settings": asdict(settings), "source_sha256": {here.name: hashlib.sha256(here.read_bytes()).hexdigest()},
        "method_deviations_and_assumptions": [
            "The numeric shadow-window extent is absent from the paper; the supplied duration is an explicit assumption.",
            "Each vicinity has 100 total samples at 44.1 kHz, starts at peak-floor(width/2), and excludes its right endpoint; other sample rates preserve its duration by rounding half up.",
            "The assumed-background window ends one full reference length before the strongest peak; every lag is at least N samples earlier, but earlier-path signal contamination is possible.",
            "Reference waveform uses a chirp-only matching template with an explicit warmup-origin offset; waveform amplitude, boundary phase and rounding are conventions.",
            "Saved captures use their exact 32 ms 4-9 kHz random-phase templates and global identity matching, not the paper's chirp or schedule-separated detection.",
            "Timing uses integer selected samples and nominal rates; no physical distance or live verdict is produced."],
        "trials": [inspect_saved_trial(path, settings) for path in trial_directories]}


def _temporary_output(path):
    path = Path(path).resolve()
    if Path("/private/tmp") not in path.parents and Path("/tmp") not in path.parents:
        raise ValueError("Derived outputs must be under /tmp")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trials", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--shadow-window-ms", type=float, default=10.)
    parser.add_argument("--reference-wav", type=Path)
    args = parser.parse_args()
    outputs = [args.output] + ([args.reference_wav] if args.reference_wav else [])
    for candidate in outputs:
        resolved = _temporary_output(candidate)
        if any(path.resolve() == resolved or path.resolve() in resolved.parents for path in args.trials):
            parser.error("Derived outputs must be outside every original capture directory")
    if args.reference_wav and args.output.resolve() == args.reference_wav.resolve():
        parser.error("Report and reference WAV must use different paths")
    settings = DetectorSettings(shadow_window_ms=args.shadow_window_ms)
    result = report(args.trials, settings)
    output = _temporary_output(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    if args.reference_wav:
        waveform = reference_waveform()
        sf.write(_temporary_output(args.reference_wav), waveform["playback"], 44100, subtype="FLOAT")
    print(json.dumps({"output": str(output), "trials": [{"trial_id": t["trial_id"], "detected": t["detected_count"],
        "timing_us": [p["nominal_cross_minus_self_timing_us"] for p in t["nominal_timing_pairs"]]} for t in result["trials"]]}, indent=2))


if __name__ == "__main__":
    main()
