"""Exact, session-bound probes for the independent travel-time diagnostic.

The stored float32 samples are the reference. Browsers must decode these bytes,
not regenerate a waveform from the seed. A correlation lag denotes the first
sample of this full, tapered template; it is not an envelope threshold crossing.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets

import numpy as np
from scipy.signal import correlate, correlation_lags, hilbert

PROTOCOL_VERSION = "ranging-v1"
SAMPLE_RATE = 48_000
PROBE_FRAMES = 1_536
PEAK_AMPLITUDE = 0.16
BAND_HZ = (4_000, 9_000)
PAIR_GAPS_S = (0.26, 0.40, 0.55, 0.70, 0.30, 0.65, 0.45, 0.80)
PAIR_GUARD_S = 0.40
PRE_ROLL_S = 0.80
POST_ROLL_S = 0.80
MAIN_LOBE_EXCLUSION_SAMPLES = 12


def _probe(seed_material: bytes) -> np.ndarray:
    """Use independent random phases with a flat interior band and 4 ms fades."""
    rng = np.random.Generator(np.random.PCG64(int.from_bytes(seed_material, "big")))
    frequencies = np.fft.rfftfreq(PROBE_FRAMES, 1 / SAMPLE_RATE)
    inside = (frequencies >= BAND_HZ[0]) & (frequencies <= BAND_HZ[1])
    spectrum = np.zeros(frequencies.size, dtype=np.complex128)
    # A 250 Hz spectral edge taper limits out-of-band energy after time tapering.
    band_frequencies = frequencies[inside]
    edge = np.minimum(band_frequencies - BAND_HZ[0], BAND_HZ[1] - band_frequencies)
    weights = np.sin(np.pi / 2 * np.clip(edge / 250, 0, 1)) ** 2
    spectrum[inside] = weights * np.exp(2j * np.pi * rng.random(inside.sum()))
    samples = np.fft.irfft(spectrum, n=PROBE_FRAMES)
    fade_frames = round(0.004 * SAMPLE_RATE)
    fade = np.sin(np.linspace(0, np.pi / 2, fade_frames)) ** 2
    samples[:fade_frames] *= fade
    samples[-fade_frames:] *= fade[::-1]
    samples *= PEAK_AMPLITUDE / np.max(np.abs(samples))
    return samples.astype("<f4")


def template_metrics(templates: dict[str, np.ndarray]) -> dict:
    """Report full-energy normalized correlations, including all linear lags.

    Main-lobe exclusion is explicit because a bandpass signal has nearby carrier
    peaks. These measurements describe digital templates, not phone acoustics.
    """
    metrics = {}
    cross_max = 0.0
    worst_pair = None
    for name, values in templates.items():
        x = values.astype(np.float64)
        energy = float(np.dot(x, x))
        auto = correlate(x, x, mode="full", method="fft") / energy
        lags = correlation_lags(x.size, x.size, mode="full")
        outside = np.abs(lags) > MAIN_LOBE_EXCLUSION_SAMPLES
        envelope = np.abs(hilbert(auto))
        spectrum_energy = np.abs(np.fft.rfft(x, n=16_384)) ** 2
        frequencies = np.fft.rfftfreq(16_384, 1 / SAMPLE_RATE)
        in_band = (frequencies >= BAND_HZ[0]) & (frequencies <= BAND_HZ[1])
        metrics[name] = {
            "rms": float(np.sqrt(np.mean(x * x))),
            "peak": float(np.max(np.abs(x))),
            "autocorrelation_abs_sidelobe": float(np.max(np.abs(auto[outside]))),
            "autocorrelation_envelope_sidelobe": float(np.max(envelope[outside])),
            "in_band_energy_fraction": float(spectrum_energy[in_band].sum() / spectrum_energy.sum()),
        }
    names = list(templates)
    for index, left in enumerate(names):
        x = templates[left].astype(np.float64)
        for right in names[index + 1:]:
            y = templates[right].astype(np.float64)
            cross = correlate(x, y, mode="full", method="fft")
            peak = float(np.max(np.abs(cross)) / np.sqrt(np.dot(x, x) * np.dot(y, y)))
            if peak > cross_max:
                cross_max = peak
                worst_pair = [left, right]
    return {
        "normalization": "correlation / sqrt(full_template_energy_x * full_template_energy_y)",
        "lag_domain": "all linear correlation lags",
        "main_lobe_exclusion_samples": MAIN_LOBE_EXCLUSION_SAMPLES,
        "main_lobe_exclusion_ms": 1_000 * MAIN_LOBE_EXCLUSION_SAMPLES / SAMPLE_RATE,
        "max_abs_cross_correlation": cross_max,
        "worst_cross_correlation_pair": worst_pair,
        "per_emission": metrics,
        "scope": "Digital templates only; speaker, microphone, room and processing effects are unmeasured.",
    }


def build_protocol(seed: int | str | None = None, session_id: str | None = None,
                   *, profile: str = "coded-probes") -> dict:
    """Build a selected profile with eight alternating A/B exchanges.

    For coded probes, seed and session_id reproduce the samples; a fresh session
    changes every probe. BeepBeep uses the same reference waveform in every slot
    and session. Neither profile establishes relay resistance.
    """
    if profile == "beepbeep-reference":
        from beepbeep_protocol import build_protocol as build_beepbeep_protocol
        return build_beepbeep_protocol(seed=seed, session_id=session_id)
    if profile != "coded-probes":
        raise ValueError("Unsupported ranging profile")
    if seed is None:
        seed = secrets.token_hex(16)
    if not isinstance(seed, (int, str)) or isinstance(seed, bool):
        raise ValueError("seed must be an integer or string")
    if session_id is None:
        session_id = secrets.token_hex(12)
    if not isinstance(session_id, str) or not session_id or len(session_id) > 256:
        raise ValueError("session_id must be a nonempty string of at most 256 characters")
    seed_text = str(seed)
    if len(seed_text) > 256:
        raise ValueError("seed is too long")
    emissions = []
    templates = {}
    next_frame = round(PRE_ROLL_S * SAMPLE_RATE)
    for pair_index, gap_s in enumerate(PAIR_GAPS_S):
        for emitter, role in (("A", "initiator"), ("B", "observer")):
            index = len(emissions)
            emission_id = f"e{index:02d}"
            material = json.dumps([PROTOCOL_VERSION, session_id, seed_text, emission_id],
                                  separators=(",", ":")).encode()
            samples = _probe(hashlib.sha256(material).digest())
            raw = samples.tobytes()
            templates[emission_id] = samples
            emissions.append({
                "id": emission_id,
                "index": index,
                "pair_index": pair_index,
                "emitter": emitter,
                "role": role,
                "offset_samples": next_frame,
                "offset_s": next_frame / SAMPLE_RATE,
                "samples_b64": base64.b64encode(raw).decode("ascii"),
                "sha256": hashlib.sha256(raw).hexdigest(),
            })
            next_frame += round((gap_s if emitter == "A" else PAIR_GUARD_S) * SAMPLE_RATE)
    duration_frames = emissions[-1]["offset_samples"] + PROBE_FRAMES + round(POST_ROLL_S * SAMPLE_RATE)
    identity = json.dumps({"session_id": session_id, "seed": seed_text,
                           "emissions": [(e["sha256"], e["offset_samples"]) for e in emissions]},
                          sort_keys=True, separators=(",", ":")).encode()
    return {
        "version": PROTOCOL_VERSION,
        "protocol_id": hashlib.sha256(identity).hexdigest(),
        "session_id": session_id,
        "seed": seed_text,
        "sample_rate": SAMPLE_RATE,
        "sample_format": "float32-le",
        "band_hz": list(BAND_HZ),
        "probe_frames": PROBE_FRAMES,
        "peak_amplitude": PEAK_AMPLITUDE,
        "pre_roll_s": PRE_ROLL_S,
        "post_roll_s": POST_ROLL_S,
        "duration_s": duration_frames / SAMPLE_RATE,
        "duration_frames": duration_frames,
        "pair_gaps_s": list(PAIR_GAPS_S),
        "emissions": emissions,
        "template_metrics": template_metrics(templates),
        "timing_semantics": {
            "template_origin": "First sample of the stored full 32 ms tapered template.",
            "matched_filter_lag": "For correlate(recording, template, 'full'), subtract len(template)-1 from the peak index.",
            "arrival_estimation": "Select the earliest credible template-delay candidate, preserve alternatives and uncertainty; the largest peak may be a reflection.",
            "schedule": "Offsets coordinate playback only. They are not acoustic arrival measurements or synchronized device clocks.",
            "sample_rate_conversion": "Preserve original capture samples and rate. Any template resampling used for analysis must be explicit.",
        },
        "playback_note": "Digital peak is 0.16. Physical loudness depends on device volume and route; use a comfortable volume.",
    }


def decode_template(protocol: dict, emission_id: str) -> np.ndarray:
    """Decode and verify exactly the samples supplied to the browser."""
    if protocol.get("version") == "beepbeep-v1":
        from beepbeep_protocol import decode_template as decode_beepbeep_template
        return decode_beepbeep_template(protocol, emission_id)
    if protocol.get("version") != PROTOCOL_VERSION or protocol.get("sample_format") != "float32-le":
        raise ValueError("Unsupported ranging protocol or sample format")
    matches = [emission for emission in protocol["emissions"] if emission["id"] == emission_id]
    if len(matches) != 1:
        raise ValueError(f"Expected one emission named {emission_id!r}")
    emission = matches[0]
    raw = base64.b64decode(emission["samples_b64"], validate=True)
    if len(raw) != int(protocol["probe_frames"]) * 4:
        raise ValueError("Template sample count does not match the protocol")
    if hashlib.sha256(raw).hexdigest() != emission["sha256"]:
        raise ValueError("Template checksum mismatch")
    samples = np.frombuffer(raw, dtype="<f4").copy()
    if not np.isfinite(samples).all() or np.max(np.abs(samples)) > 0.2:
        raise ValueError("Template contains invalid or excessive samples")
    return samples


def reference_templates(protocol: dict) -> dict[str, np.ndarray]:
    return {emission["id"]: decode_template(protocol, emission["id"])
            for emission in protocol["emissions"]}
