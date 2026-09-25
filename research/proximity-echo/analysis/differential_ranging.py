"""Offline change in the four-path acoustic channel delay, never absolute range.

R = Y_AB Y_BA / (Y_AA Y_BB), Q = R_current / R_baseline. The first
index is the emitter. Exact templates cancel inside each R, including when the
two emissions or two sessions use different templates. Fourier transforms use
one frequency scale, and every excerpt's original frame origin is restored.
Stable transducer responses and stable dispersive propagation factors cancel
in Q. Under the additional whole-channel translation model its phase slope is
the CHANGE in tau_AB + tau_BA - tau_AA - tau_BB. Moving only a direct path while
reflections stay fixed generally violates this model. No direct lobe is chosen.

Both sessions must be stationary during their probes. Relative clock tracking
cannot distinguish systematic within-session motion from sample-clock drift.
The common absolute clock rate, physical propagation model, and relation to a
body gap are unvalidated. Even a passing result is an exploratory channel delay.
All gates below are declared in code, not fitted to distance labels. A failed
gate makes the public numeric result null; exploratory fit evidence is retained.

Run: .venv/bin/python analysis/differential_ranging.py BASELINE CURRENT --output /tmp/differential.json
Only original protocol, WAV and capture-continuity metadata are inputs.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from scipy import optimize, signal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis import inspect_ranging_channels as inspector
from ranging_analysis import _read_recording

RATE = inspector.RATE
FREQUENCIES = np.arange(4250.0, 8750.0 + 1, 31.25)
BANDS = ((4250., 8750.), (4250., 6250.), (6250., 8750.))
DELAY_GRID = np.linspace(-.002, .002, 2001)
SEARCH_PHASE = np.exp(2j * np.pi * DELAY_GRID[:, None] * FREQUENCIES)


@dataclass(frozen=True)
class Gates:
    """Prototype rejection limits; these are not calibrated confidence limits."""
    clock_abs_ppm: float = 500.
    clock_rms_us: float = 10.
    clock_emitter_disagreement_ppm: float = 2.
    clock_band_disagreement_ppm: float = 2.
    minimum_channel_coherence: float = .98
    minimum_phase_fit_coherence: float = .99
    maximum_band_delay_difference_us: float = 10.
    maximum_pair_delay_spread_us: float = 10.
    maximum_leave_one_out_difference_us: float = 3.
    maximum_alternative_peak_ratio: float = .90
    minimum_bin_fraction: float = .60
    minimum_repeat_phase_concentration: float = .98


GATES = Gates()


def phase_fit(phasor, weights, band=BANDS[0]):
    """Fit a delay and free constant phase, retaining other delay optima."""
    phasor, weights = np.asarray(phasor), np.asarray(weights, float)
    use = (FREQUENCIES >= band[0]) & (FREQUENCIES <= band[1]) & (weights > 0)
    if np.count_nonzero(use) < 12:
        raise ValueError("Insufficient supported frequency bins")
    w = np.where(use, weights, 0.)
    product = w * phasor
    norm = float(w.sum())
    scores = abs(SEARCH_PHASE @ product) / norm
    index = int(np.argmax(scores))
    if index in (0, len(DELAY_GRID) - 1):
        raise ValueError("Delay optimum touches the search boundary")

    def score(delay):
        return abs(np.sum(product * np.exp(2j * np.pi * FREQUENCIES * delay))) / norm

    refined = optimize.minimize_scalar(lambda d: -score(d),
        bounds=(DELAY_GRID[index - 1], DELAY_GRID[index + 1]),
        method="bounded", options={"xatol": 1e-12})
    delay = float(refined.x)
    coherence = float(score(delay))
    adjusted = phasor * np.exp(2j * np.pi * FREQUENCIES * delay)
    intercept = float(np.angle(np.sum(w * adjusted)))
    residual = np.angle(adjusted * np.exp(-1j * intercept))
    peaks, _ = signal.find_peaks(scores)
    # find_peaks excludes array endpoints. A strong edge competitor can be an
    # alias or a higher optimum just outside the search range and must count.
    peaks = np.r_[peaks, 0, len(scores) - 1]
    # Inspect every distinct local optimum, including those closer than the
    # nominal main-lobe width when frequency support is irregular.
    separation = 2 * (DELAY_GRID[1] - DELAY_GRID[0])
    others = [int(i) for i in peaks if abs(DELAY_GRID[i] - delay) >= separation]
    others.sort(key=lambda i: scores[i], reverse=True)
    alternatives = [{"delay_us": float(DELAY_GRID[i] * 1e6),
                     "score_relative_to_best": float(scores[i] / coherence)} for i in others[:4]]
    return {"delay_us": delay * 1e6, "phase_intercept_rad": intercept,
            "phase_fit_coherence": coherence,
            "phase_residual_rms_rad": float(np.sqrt(np.sum(w * residual**2) / norm)),
            "supported_bins": int(np.count_nonzero(use)),
            "alternative_delay_peaks": alternatives,
            "largest_alternative_peak_ratio": alternatives[0]["score_relative_to_best"] if alternatives else 0.}


def origin_restored_spectrum(excerpt, origin_frame, relative_rate):
    """Correct both frequency and epoch to A's nominal sample-clock scale."""
    actual_rate = RATE * relative_rate
    local = signal.zoom_fft(excerpt, [FREQUENCIES[0], FREQUENCIES[-1]],
                            m=len(FREQUENCIES), fs=actual_rate, endpoint=True)
    epoch = origin_frame / actual_rate
    return local * np.exp(-2j * np.pi * FREQUENCIES * epoch)


def four_path_ratio(spectra, weights):
    """Unit phasor avoids dividing by near-zero spectra; weights mask them."""
    unit = {key: value / np.maximum(abs(value), 1e-300) for key, value in spectra.items()}
    ratio = unit["AB"] * unit["BA"] * unit["AA"].conj() * unit["BB"].conj()
    weight = np.min(np.array([weights[key] for key in ("AA", "AB", "BA", "BB")]), axis=0)
    return ratio, weight


def _mean_phase(rows, weights):
    total = np.sum(weights, axis=0)
    average = np.divide(np.sum(rows * weights, axis=0), total,
                        out=np.zeros(rows.shape[1], complex), where=total > 0)
    concentration = abs(average)
    unit = np.divide(average, concentration, out=np.zeros_like(average), where=concentration > 0)
    return unit, np.mean(weights, axis=0), concentration


def _load_capture(directory):
    directory = Path(directory)
    protocol_path = directory / "protocol.json"
    protocol = json.loads(protocol_path.read_text())
    templates = inspector.validate_protocol(protocol)
    inputs, audio, quality = [protocol_path], {}, {}
    for receiver in "AB":
        wav, upload = directory / f"recording_{receiver}.wav", directory / f"upload_{receiver}.json"
        metadata = json.loads(upload.read_text())["metadata"]
        pcm, rate, q = _read_recording({"wav_path": wav, "metadata": metadata}, receiver)
        if rate != RATE or not q["usable"]:
            raise ValueError(f"Capture {receiver} failed original quality checks: {q['quality_reasons']}")
        audio[receiver], quality[receiver] = pcm, {"frames": len(pcm), "continuity": q["continuity"]}
        inputs.extend([wav, upload])
    rows = {key: [] for key in ("AA", "AB", "BA", "BB")}
    previous = {"A": None, "B": None}
    for emission in protocol["emissions"]:
        template = templates[emission["id"]]
        X = np.fft.rfft(template, n=inspector.NFFT)
        power = abs(X)**2
        regularizer = 1e-3 * np.median(power[inspector.mask_for(inspector.BANDS[0])])
        for receiver in "AB":
            pcm = audio[receiver]
            center = inspector.locate_probe(pcm, template)
            inspector.validate_probe_location(center, len(pcm), previous[receiver])
            previous[receiver] = center
            origin = center - inspector.PRE
            excerpt = pcm[origin:origin + inspector.EXCERPT].copy()
            excerpt[-480:] *= np.cos(np.linspace(0, np.pi / 2, 480))**2
            Y = np.fft.rfft(excerpt, n=inspector.NFFT) * np.exp(1j * inspector.OMEGA * inspector.PRE)
            H = Y * X.conj() / (power + regularizer)
            rows[emission["emitter"] + receiver].append({"id": emission["id"], "center": center,
                "origin": origin, "excerpt": excerpt, "H": H})
    clocks, shapes, within = [], {}, {}
    for band in inspector.BANDS:
        times = {}
        for key, group in rows.items():
            delays, aligned = inspector.align_group(np.array([row["H"] for row in group]), band)
            for row, delay in zip(group, delays):
                times[(row["id"], key[1])] = row["center"] + delay
            if band == inspector.BANDS[0]:
                m = inspector.mask_for(band)
                mean = aligned.mean(axis=0)
                coherence = abs(aligned[:, m] @ mean[m].conj()) / (np.linalg.norm(aligned[:, m], axis=1) * np.linalg.norm(mean[m]))
                within[key] = float(np.min(coherence))
                shapes[key] = mean
        clocks.append(inspector.fit_clock(times, protocol["emissions"]))
    reasons = []
    for clock in clocks:
        if abs(clock["relative_rate_ppm"]) > GATES.clock_abs_ppm:
            reasons.append("clock_rate_outside_model")
        if clock["rms_ms"] * 1000 > GATES.clock_rms_us:
            reasons.append("clock_step_or_nonstationary_capture")
        if abs(clock["by_emitter_ppm"]["A"] - clock["by_emitter_ppm"]["B"]) > GATES.clock_emitter_disagreement_ppm:
            reasons.append("clock_emitter_disagreement")
    if np.ptp([c["relative_rate_ppm"] for c in clocks]) > GATES.clock_band_disagreement_ppm:
        reasons.append("clock_band_disagreement")
    if min(within.values()) < GATES.minimum_channel_coherence:
        reasons.append("channel_changed_within_capture")
    rate = 1 + clocks[0]["relative_rate_ppm"] * 1e-6
    ratios, weights = [], []
    for index in range(8):
        spectra, supports = {}, {}
        for key, group in rows.items():
            row = group[index]
            spectrum = origin_restored_spectrum(row["excerpt"], row["origin"], rate if key[1] == "B" else 1.)
            magnitude = abs(spectrum)
            floor = max(.05 * np.median(magnitude), 1e-15)
            # PRE is a coarse pre-roll, not a claimed direct onset. The first
            # half is background and may conservatively mask early weak energy.
            noise = np.std(row["excerpt"][:inspector.PRE // 2]) * np.sqrt(len(row["excerpt"]))
            supported = (magnitude >= max(floor, 8 * noise))
            supports[key] = np.where(supported, np.minimum(magnitude / max(np.median(magnitude), 1e-15), 1.), 0.)
            spectra[key] = spectrum
        ratio, weight = four_path_ratio(spectra, supports)
        ratios.append(ratio)
        weights.append(weight)
    return {"trial_id": directory.name, "ratios": np.array(ratios), "weights": np.array(weights), "shapes": shapes,
            "diagnostics": {"trial_id": directory.name, "capture_quality": quality,
                "input_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
                "clock_by_band": clocks, "relative_receiver_rate": rate,
                "minimum_within_capture_channel_coherence": within,
                "window_origins_frames": {key: [row["origin"] for row in group] for key, group in rows.items()},
                "reasons": list(dict.fromkeys(reasons))}}


def compare_captures(baseline, current):
    """Compare prepared captures without any geometry or distance labels."""
    source_paths = [Path(__file__), Path(inspector.__file__), Path(__file__).resolve().parents[1] / "ranging_analysis.py"]
    report = {"version": "differential-four-path-v1", "status": "unavailable",
        "combined_path_delay_change_us": None,
        "quantity": "change in tau_AB + tau_BA - tau_AA - tau_BB",
        "absolute_distance_m": None, "body_gap_m": None, "physical_timing_validated": False,
        "gates": asdict(GATES), "reasons": [], "baseline": baseline["diagnostics"], "current": current["diagnostics"],
        "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}}
    reasons = report["reasons"]
    for capture in (baseline, current):
        reasons.extend(f"{capture['trial_id']}: {reason}" for reason in capture["diagnostics"]["reasons"])
    # Failed acquisition or clock models must not produce a fitted channel change.
    if reasons:
        return report
    phase0, weights0, conc0 = _mean_phase(baseline["ratios"], baseline["weights"])
    phase1, weights1, conc1 = _mean_phase(current["ratios"], current["weights"])
    weight = np.minimum(weights0, weights1)
    supported = (conc0 >= GATES.minimum_repeat_phase_concentration) & (conc1 >= GATES.minimum_repeat_phase_concentration)
    weight = np.where(supported, weight, 0.)
    if np.count_nonzero(weight) / len(weight) < GATES.minimum_bin_fraction:
        reasons.append("insufficient_repeatable_frequency_support")
        return report
    fit = phase_fit(phase1 * phase0.conj(), weight)
    bands = [phase_fit(phase1 * phase0.conj(), weight, band) for band in BANDS[1:]]
    if fit["phase_fit_coherence"] < GATES.minimum_phase_fit_coherence:
        reasons.append("changed_channel_not_a_pure_delay")
    if fit["largest_alternative_peak_ratio"] >= GATES.maximum_alternative_peak_ratio:
        reasons.append("alternative_delay_ambiguity")
    if np.ptp([fit["delay_us"], *[b["delay_us"] for b in bands]]) > GATES.maximum_band_delay_difference_us:
        reasons.append("frequency_band_disagreement")
    # Every baseline/current exchange combination contributes a diagnostic
    # comparison. These 64 correlated fits are not 64 new samples.
    pairs = []
    for i in range(8):
        for j in range(8):
            w = np.minimum(baseline["weights"][i], current["weights"][j]) * (weight > 0)
            pairs.append(phase_fit(current["ratios"][j] * baseline["ratios"][i].conj(), w)["delay_us"])
    if np.ptp(pairs) > GATES.maximum_pair_delay_spread_us:
        reasons.append("exchange_pair_disagreement")
    left_out = []
    for side in (0, 1):
        for omit in range(8):
            capture = (baseline, current)[side]
            keep = np.arange(8) != omit
            p, w, _ = _mean_phase(capture["ratios"][keep], capture["weights"][keep])
            q = phase1 * p.conj() if side == 0 else p * phase0.conj()
            other_w = weights1 if side == 0 else weights0
            left_out.append(phase_fit(q, np.minimum(w, other_w) * (weight > 0))["delay_us"])
    if max(abs(np.array(left_out) - fit["delay_us"])) > GATES.maximum_leave_one_out_difference_us:
        reasons.append("held_out_exchange_disagreement")
    change_coherence = {}
    m = inspector.mask_for(inspector.BANDS[0])
    for key in ("AA", "AB", "BA", "BB"):
        h0, h1 = baseline["shapes"][key], current["shapes"][key]
        shift = inspector.response_delay(h1, h0, inspector.BANDS[0])
        h1 = h1 * np.exp(1j * inspector.OMEGA * shift)
        change_coherence[key] = float(abs(np.vdot(h0[m], h1[m])) / (np.linalg.norm(h0[m]) * np.linalg.norm(h1[m])))
    if min(change_coherence.values()) < GATES.minimum_channel_coherence:
        reasons.append("channel_shape_changed_between_captures")
    report["exploratory_fit"] = {**fit, "subbands": [{"band_hz": list(b), **f} for b, f in zip(BANDS[1:], bands)],
        "all_64_exchange_comparison_delay_us": pairs,
        "leave_one_exchange_out_delay_us": left_out,
        "between_capture_channel_coherence_after_delay_and_gain": change_coherence,
        "repeat_phase_concentration_minimum": float(min(conc0[weight > 0].min(), conc1[weight > 0].min()))}
    report["status"] = "rejected" if reasons else "exploratory_channel_change"
    if not reasons:
        report["combined_path_delay_change_us"] = fit["delay_us"]
    return report


def analyze_differential(baseline_directory, current_directory):
    """Fail closed on capture, probe, clock, or numerical failures."""
    try:
        result = compare_captures(_load_capture(baseline_directory), _load_capture(current_directory))
        json.dumps(result, allow_nan=False)
        return result
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        return {"version": "differential-four-path-v1", "status": "unavailable",
            "combined_path_delay_change_us": None, "absolute_distance_m": None, "body_gap_m": None,
            "physical_timing_validated": False, "gates": asdict(GATES), "reasons": [str(exc)]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("current", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    archive = Path(__file__).resolve().parents[1] / "data/ranging"
    if any(root.resolve() == output or root.resolve() in output.parents for root in (archive, args.baseline, args.current)):
        parser.error("Output must be outside all original capture directories")
    result = analyze_differential(args.baseline, args.current)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({key: result[key] for key in ("status", "combined_path_delay_change_us", "reasons")}, indent=2))
    print(output)


if __name__ == "__main__":
    main()
