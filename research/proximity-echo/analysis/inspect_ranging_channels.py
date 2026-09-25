"""Offline, uncalibrated channel-shape inspection of saved ranging captures.

Usage: .venv/bin/python analysis/inspect_ranging_channels.py --output /tmp/channels.json

Reads only protocol.json and original WAVs. No labels, reports, distance targets,
clock-fit targets, or live analyzer are inputs. A global exact-template envelope
maximum at a local peak with normalized correlation >= 0.40 and non-silent
window energy locates a probe excerpt; it is not declared the
direct-path arrival. All 16 exact probe identities and their chronological,
non-overlapping template windows must be present in both finite mono captures.
Relative delay aligns the *whole channel response* across
independent probes in the same emitter/receiver path. Its unknown fixed offset
cancels for clock-rate estimation but not for ranging.

Regularized deconvolution uses Y X* / (|X|^2 + 1e-3 median_inband |X|^2).
The excerpt spans 10 ms before the global peak and 75.3 ms after it. Its final
10 ms fades to zero. Aligned complex responses are averaged across eight probes.
Leave-one-out prediction uses seven other probes' responses, then fits one delay
and one complex gain to the held-out response. This evaluates channel repeat-
ability, not independent arrival accuracy. The held-out waveform metric compares
H_i X_i with H_train X_i after template regularization, not total raw waveform
energy. Bandlimited inverse transforms have
acausal ringing; their maxima and energy widths do not identify physical paths.

The phase-only profile is regularized PHAT. The four-path product cancels common
scalar linear source/receiver filters only under separability and stable geometry.
Multiple speakers, microphone arrays, directional transfer, reflections and
capture defects can violate that model. All timing results remain exploratory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import optimize, signal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ranging_protocol import PROBE_FRAMES, decode_template

RATE = 48000
NFFT = 8192
EXCERPT = 4096
PRE = 480
BANDS = [(4250, 8750), (4250, 6250), (6250, 8750)]
FREQ = np.fft.rfftfreq(NFFT, 1 / RATE)
OMEGA = 2 * np.pi * FREQ / RATE


def stats(values):
    a = np.asarray(values, float)
    return {"min": float(a.min()), "median": float(np.median(a)),
            "max": float(a.max()), "std": float(np.std(a))}


def mask_for(band):
    return (FREQ >= band[0]) & (FREQ <= band[1])


def peak_fraction(values, index):
    if index == 0 or index == len(values) - 1:
        return float(index)
    a, b, c = values[index - 1:index + 2]
    d = a - 2 * b + c
    return index + float(np.clip(.5 * (a - c) / d, -.5, .5)) if d < 0 else float(index)


def response_delay(left, right, band):
    """Positive means left response arrives later than right, in samples."""
    m = mask_for(band)
    cross = np.where(m, left * right.conj(), 0)
    profile = np.abs(signal.hilbert(np.fft.irfft(cross, n=NFFT)))
    lags = np.arange(-96, 97)
    lag = lags[np.argmax(profile[lags % NFFT])]
    # Full-band envelope avoids choosing an arbitrary carrier-cycle maximum.
    def objective(d):
        return -abs(np.sum(cross[m] * np.exp(1j * OMEGA[m] * d)))
    fit = optimize.minimize_scalar(objective, bounds=(lag - 1.0, lag + 1.0), method="bounded")
    return float(fit.x)


def align_group(responses, band):
    reference = responses[0]
    delays = np.array([response_delay(h, reference, band) for h in responses])
    aligned = np.array([h * np.exp(1j * OMEGA * d) for h, d in zip(responses, delays)])
    # Refine against the average with no recording-time or clock model prior.
    reference = aligned.mean(axis=0)
    updates = np.array([response_delay(h, reference, band) for h in aligned])
    delays += updates
    aligned = np.array([h * np.exp(1j * OMEGA * d) for h, d in zip(responses, delays)])
    return delays, aligned


def profile_peaks(spectrum, radius=48):
    env = np.abs(signal.hilbert(np.fft.irfft(spectrum, n=NFFT)))
    lags = np.arange(-radius, radius + 1)
    local = env[lags % NFFT]
    peaks, _ = signal.find_peaks(local)
    peaks = sorted(peaks, key=lambda j: local[j], reverse=True)
    if not peaks:
        return []
    maximum = float(local[peaks[0]])
    return [{"relative_ms": float(lags[j] / RATE * 1000), "relative_amplitude": float(local[j] / maximum)}
            for j in peaks[:6] if local[j] / maximum >= .20]


def fit_clock(times, emissions):
    # Fixed arbitrary offsets for the two emitter groups absorb unknown channel
    # delay. This is relative capture-rate consistency, never physical distance.
    a = np.array([times[(e["id"], "A")] / RATE for e in emissions])
    b = np.array([times[(e["id"], "B")] / RATE for e in emissions])
    emit_a = np.array([e["emitter"] == "A" for e in emissions])
    design = np.column_stack((a - a.mean(), emit_a.astype(float), (~emit_a).astype(float)))
    coeff = np.linalg.lstsq(design, b - a, rcond=None)[0]
    residual = b - a - design @ coeff
    per = {}
    for role, use in [("A", emit_a), ("B", ~emit_a)]:
        per[role] = float(np.polyfit(a[use] - a[use].mean(), (b - a)[use], 1)[0] * 1e6)
    # A step is inspected, never removed from the recordings or accepted fit.
    steps = []
    for index in range(3, len(a) - 3):
        after = np.arange(len(a)) >= index
        if min(np.count_nonzero(after & emit_a), np.count_nonzero(after & ~emit_a),
               np.count_nonzero(~after & emit_a), np.count_nonzero(~after & ~emit_a)) < 2:
            continue
        d = np.column_stack((design, after.astype(float)))
        c = np.linalg.lstsq(d, b - a, rcond=None)[0]
        res = b - a - d @ c
        steps.append({"first_after_emission": emissions[index]["id"], "step_ms": float(c[-1] * 1000),
                      "residual_rms_ms": float(np.sqrt(np.mean(res**2)) * 1000), "relative_rate_ppm": float(c[0] * 1e6)})
    return {"relative_rate_ppm": float(coeff[0] * 1e6), "by_emitter_ppm": per,
            "rms_ms": float(np.sqrt(np.mean(residual**2)) * 1000),
            "max_abs_ms": float(np.max(np.abs(residual)) * 1000),
            "best_step_diagnostic": min(steps, key=lambda x: x["residual_rms_ms"]),
            "per_emission_residual_ms": (residual * 1000).tolist()}


def locate_probe(recording, template):
    """Locate a strong code match without normalizing silent-window roundoff.

    This uses the live analyzer's existing relative energy floor and 0.40 NCC
    locator cutoff, but does not reuse its arrival acceptance or physical timing.
    Hilbert-envelope tails can extend into zero-energy windows; these are not
    evidence of a probe. Select only local envelope maxima above the energy floor.
    """
    match = signal.correlate(recording, template, mode="valid", method="fft")
    envelope = np.abs(signal.hilbert(match))
    energy = np.r_[0.0, np.cumsum(recording**2)]
    local_energy = np.maximum(energy[len(template):] - energy[:-len(template)], 0)
    minimum_energy = max(float(local_energy.max(initial=0)) * 1e-12, 1e-24)
    denominator = np.sqrt(local_energy * np.sum(template**2))
    normalized = np.divide(envelope, denominator, out=np.zeros_like(envelope),
                           where=local_energy > minimum_energy)
    normalized = np.minimum(normalized, 1)
    peaks, _ = signal.find_peaks(envelope)
    eligible = peaks[normalized[peaks] >= .40]
    if not len(eligible):
        raise ValueError(f"No credible full-recording probe locator; best NCC={normalized.max(initial=0):.6f}")
    return int(eligible[np.argmax(envelope[eligible])])


def validate_protocol(protocol):
    """Verify stored samples and the exact identity/order of all 16 probes."""
    if not isinstance(protocol, dict):
        raise ValueError("Protocol must be an object")
    if (protocol.get("version") != "ranging-v1" or protocol.get("sample_format") != "float32-le"
            or protocol.get("sample_rate") != RATE or protocol.get("probe_frames") != PROBE_FRAMES
            or protocol.get("band_hz") != [4000, 9000]):
        raise ValueError("Expected the original ranging-v1 48 kHz, 1536-frame, 4–9 kHz protocol")
    emissions = protocol.get("emissions")
    if not isinstance(emissions, list) or len(emissions) != 16:
        raise ValueError("Exactly 16 original emissions are required")
    if not all(isinstance(protocol.get(key), str) and protocol[key] for key in ("session_id", "seed")):
        raise ValueError("Protocol session and seed identity must be nonempty strings")
    templates, hashes, offsets = {}, set(), []
    for index, emission in enumerate(emissions):
        expected_id = f"e{index:02d}"
        if (not isinstance(emission, dict) or emission.get("id") != expected_id
                or emission.get("index") != index or emission.get("pair_index") != index // 2
                or emission.get("emitter") != "AB"[index % 2]
                or emission.get("role") != ("initiator" if index % 2 == 0 else "observer")):
            raise ValueError(f"Emission identity/order mismatch at {expected_id}")
        offset = emission.get("offset_samples")
        if (type(offset) is not int or offset < 0 or (offsets and offset <= offsets[-1])
                or emission.get("offset_s") != offset / RATE):
            raise ValueError(f"Emission schedule identity/order mismatch at {expected_id}")
        offsets.append(offset)
        try:
            samples = decode_template(protocol, expected_id).astype(float)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid exact template {expected_id}: {exc}") from exc
        digest = emission["sha256"]
        if digest in hashes or not np.any(samples):
            raise ValueError("All 16 exact probe sample sequences must be distinct and nonzero")
        hashes.add(digest)
        templates[expected_id] = samples
    identity = json.dumps({"session_id": protocol["session_id"], "seed": protocol["seed"],
                           "emissions": [(e["sha256"], e["offset_samples"]) for e in emissions]},
                          sort_keys=True, separators=(",", ":")).encode()
    if hashlib.sha256(identity).hexdigest() != protocol.get("protocol_id"):
        raise ValueError("Protocol identity checksum mismatch")
    return templates


def validate_probe_location(center, frame_count, previous=None):
    """Reject clipped excerpts and reused or out-of-order probe identities."""
    if type(center) is not int or center - PRE < 0 or center - PRE + EXCERPT > frame_count:
        raise ValueError("Probe analysis window is outside the original recording")
    if previous is not None:
        if center <= previous:
            raise ValueError("Probe identities are not in chronological recording order")
        if center - previous < PROBE_FRAMES:
            raise ValueError("Probe identity windows collide in the recording")


def inspect_trial(directory):
    directory = Path(directory)
    protocol_path = directory / "protocol.json"
    protocol = json.loads(protocol_path.read_text())
    templates = validate_protocol(protocol)
    inputs = [protocol_path]
    audio = {}
    for receiver in "AB":
        path = directory / f"recording_{receiver}.wav"
        audio[receiver], rate = sf.read(path)
        if rate != RATE or audio[receiver].ndim != 1 or len(audio[receiver]) < EXCERPT:
            raise ValueError("This experiment requires complete mono original 48 kHz WAVs")
        if not np.isfinite(audio[receiver]).all():
            raise ValueError(f"Recording {receiver} contains nonfinite samples")
        inputs.append(path)
    groups = {a + b: [] for a in "AB" for b in "AB"}
    previous_centers = {receiver: None for receiver in "AB"}
    for emission in protocol["emissions"]:
        x = templates[emission["id"]]
        X = np.fft.rfft(x, n=NFFT)
        power = abs(X)**2
        regularizer = 1e-3 * np.median(power[mask_for(BANDS[0])])
        for receiver in "AB":
            recording = audio[receiver]
            try:
                center = locate_probe(recording, x)
                validate_probe_location(center, len(recording), previous_centers[receiver])
            except ValueError as exc:
                raise ValueError(f"{directory.name} {emission['emitter']}{receiver} {emission['id']}: {exc}") from exc
            previous_centers[receiver] = center
            excerpt = recording[center - PRE:center - PRE + EXCERPT].copy()
            excerpt[-480:] *= np.cos(np.linspace(0, np.pi / 2, 480))**2
            Y = np.fft.rfft(excerpt, n=NFFT) * np.exp(1j * OMEGA * PRE)
            H = Y * X.conj() / (power + regularizer)
            groups[emission["emitter"] + receiver].append({"id": emission["id"], "center": center,
                         "H": H, "X": X, "Y": Y, "regularizer": regularizer})
    report = {"trial_id": directory.name, "input_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
              "channels": {}, "clock_by_band": {}, "physical_timing_validated": False}
    aligned_by_band = {}
    times_by_band = {}
    for band in BANDS:
        band_key = f"{band[0]}-{band[1]}"
        m = mask_for(band)
        times = {}
        for key, rows in groups.items():
            hs = np.array([r["H"] for r in rows])
            delays, aligned = align_group(hs, band)
            aligned_by_band[(band_key, key)] = aligned
            for r, delay in zip(rows, delays):
                times[(r["id"], key[1])] = r["center"] + delay
            if band != BANDS[0]:
                continue
            # Remove a fitted complex gain per probe before shape statistics.
            mean = aligned.mean(axis=0)
            gains = np.sum(aligned[:, m] * mean[m].conj(), axis=1) / np.sum(abs(mean[m])**2)
            normalized = aligned / gains[:, None]
            mean = normalized.mean(axis=0)
            coherence = abs(normalized[:, m].sum(axis=0))**2 / (len(rows) * np.sum(abs(normalized[:, m])**2, axis=0))
            magnitudes_db = 20 * np.log10(np.maximum(abs(normalized[:, m]), 1e-12))
            loo = []
            held_out = []
            for j in range(len(rows)):
                # Train and align without this probe, then fit only its shift
                # and gain. Target response cannot alter the training shape.
                _, training = align_group(np.delete(hs, j, axis=0), band)
                train = training.mean(axis=0)
                held_delay = response_delay(hs[j], train, band)
                observed = hs[j] * np.exp(1j * OMEGA * held_delay)
                held_out.append((observed, train))
                X = rows[j]["X"]
                prediction = train[m] * X[m]
                truth = observed[m] * X[m]
                gain = np.vdot(prediction, truth) / np.vdot(prediction, prediction)
                loo.append(1 - float(np.sum(abs(truth - gain * prediction)**2) / np.sum(abs(truth)**2)))
            band_powers = []
            for lo, hi in [(4250, 5250), (5250, 6250), (6250, 7250), (7250, 8750)]:
                use = mask_for((lo, hi))
                band_powers.append({"band_hz": [lo, hi], "median_gain_db": float(20 * np.log10(np.median(abs(mean[use]))))})
            whiten_floor = .03 * np.median(abs(mean[m]))
            phaseonly = np.where(m, mean / np.maximum(abs(mean), whiten_floor), 0)
            regularized = np.where(m, mean, 0)
            impulse = np.fft.irfft(regularized, n=NFFT)
            lags = np.arange(NFFT); lags = np.where(lags > NFFT // 2, lags - NFFT, lags)
            energy = impulse**2
            # Center the displayed energy window at the largest IR envelope peak.
            h_env = np.abs(signal.hilbert(impulse))
            peak_lag = int(lags[np.argmax(h_env)])
            widths = {str(ms): float(energy[abs(lags - peak_lag) <= ms * RATE / 1000].sum() / energy.sum())
                      for ms in [.25, .5, 1, 2, 5, 10]}
            # Compare observed matched-filter local profiles to held-out channel
            # predictions, retaining template-specific spectrum and phase.
            shape_scores = []
            for j, (observed, train) in enumerate(held_out):
                pwr = abs(rows[j]["X"])**2
                lag_window = np.arange(-48, 49) % NFFT
                actual = abs(signal.hilbert(np.fft.irfft(observed * pwr, n=NFFT)))[lag_window]
                pred = abs(signal.hilbert(np.fft.irfft(train * pwr, n=NFFT)))[lag_window]
                shape_scores.append(float(np.corrcoef(actual, pred)[0, 1]))
            report["channels"][key] = {"emissions": [r["id"] for r in rows],
                "waveform_alignment_shift_ms": (delays / RATE * 1000).tolist(),
                "complex_coherence_across_probes": stats(coherence),
                "normalized_magnitude_std_db_across_probes": stats(np.std(magnitudes_db, axis=0)),
                "held_out_band_waveform_explained_energy": stats(loo),
                "held_out_match_envelope_shape_correlation": stats(shape_scores),
                "magnitude_band_levels": band_powers,
                "deconvolved_profile_peaks": profile_peaks(regularized),
                "phase_only_profile_peaks": profile_peaks(phaseonly),
                "impulse_energy_fraction_within_radius_ms": widths,
                "global_match_frames": [r["center"] for r in rows]}
        times_by_band[band_key] = times
        report["clock_by_band"][band_key] = fit_clock(times, protocol["emissions"])
    # A phase ratio of the four averaged channel responses. Aligned response
    # centers are arbitrary per path, so slope sensitivity across bands is the
    # output; no absolute travel-time or range follows from this ratio.
    main_key = f"{BANDS[0][0]}-{BANDS[0][1]}"
    means = {key: aligned_by_band[(main_key, key)].mean(axis=0) for key in groups}
    numerator = means["AB"] * means["BA"]
    denominator = means["AA"] * means["BB"]
    ratio = numerator * denominator.conj()
    phase_result = []
    for band in BANDS:
        m = mask_for(band)
        phase = np.unwrap(np.angle(ratio[m]))
        f = FREQ[m]
        coeff = np.polyfit(f - f.mean(), phase, 1)
        residual = phase - np.polyval(coeff, f - f.mean())
        phase_result.append({"band_hz": list(band), "arbitrary_origin_group_delay_ms": float(-coeff[0] / (2*np.pi) * 1000),
                             "phase_line_residual_rms_rad": float(np.sqrt(np.mean(residual**2)))})
    report["four_path_phase_ratio"] = phase_result
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trial_directories", nargs="*", type=Path)
    parser.add_argument("--output", type=Path, help="JSON destination outside the immutable capture directories")
    args = parser.parse_args()
    if args.output is None:
        parser.error("--output is required")
    root = Path(__file__).resolve().parents[1]
    directories = args.trial_directories or sorted((root / "data/ranging").glob("*"))
    if (root / 'data/ranging').resolve() in args.output.resolve().parents or any(path.resolve() in args.output.resolve().parents for path in directories):
        parser.error("Output must be outside capture directories")
    result = {"version": "exploratory-channel-shapes-v2", "method": __doc__,
              "channel_key": "emitter then receiver", "frequency_bands_hz": BANDS,
              "trials": [inspect_trial(path) for path in directories if (path / "protocol.json").exists()]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    for trial in result["trials"]:
        print(trial["trial_id"][:8])
        for key, c in trial["channels"].items():
            print(key, "coherence", round(c["complex_coherence_across_probes"]["median"], 4),
                  "LOO energy", round(c["held_out_band_waveform_explained_energy"]["median"], 4),
                  "shape", round(c["held_out_match_envelope_shape_correlation"]["median"], 4),
                  "peaks", c["deconvolved_profile_peaks"][:3])
        for band, c in trial["clock_by_band"].items():
            print(band, "ppm", round(c["relative_rate_ppm"], 2), "rms ms", round(c["rms_ms"], 5),
                  "by emitter", {k: round(v, 2) for k, v in c["by_emitter_ppm"].items()})
        print("phase ratio", trial["four_path_phase_ratio"])
    print(args.output)


if __name__ == "__main__":
    main()
