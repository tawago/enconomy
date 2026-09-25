"""Stored BeepBeep reference waveforms with coarse, disjoint emission slots.

Session identity binds the playback manifest. The identical sounds contain no
session identity, source identity, freshness, authentication, or relay defense.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
from functools import lru_cache

import numpy as np

PROTOCOL_VERSION = "beepbeep-v1"
PROFILE = "beepbeep-reference"
SAMPLE_RATE = 48_000
PROBE_FRAMES = 2_640
REFERENCE_OFFSET_FRAMES = 240
REFERENCE_FRAMES = 2_400
PEAK_AMPLITUDE = .16
BAND_HZ = (2_000, 6_000)
PRE_ROLL_S = POST_ROLL_S = 1.
SLOT_INTERVAL_S = 1.
SEARCH_EARLY_S = .20
SEARCH_LATE_S = .45


@lru_cache(maxsize=1)
def _waveform_bytes():
    # Lazy import avoids a dependency cycle through the offline reference CLI.
    from analysis.beepbeep_reference import reference_waveform
    return reference_waveform(SAMPLE_RATE, PEAK_AMPLITUDE)["playback"].astype("<f4").tobytes()


def build_protocol(seed: int | str | None = None, session_id: str | None = None) -> dict:
    """Build eight alternating exchanges, each using the same 55 ms playback."""
    if seed is None:
        seed = secrets.token_hex(16)
    if not isinstance(seed, (int, str)) or isinstance(seed, bool) or len(str(seed)) > 256:
        raise ValueError("seed must be an integer or string of at most 256 characters")
    if session_id is None:
        session_id = secrets.token_hex(12)
    if not isinstance(session_id, str) or not session_id or len(session_id) > 256:
        raise ValueError("session_id must be a nonempty string of at most 256 characters")
    raw = _waveform_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    encoded = base64.b64encode(raw).decode("ascii")
    emissions = []
    for index in range(16):
        offset = (index + 1) * SAMPLE_RATE
        offset_s = offset / SAMPLE_RATE
        emissions.append({"id": f"e{index:02d}", "index": index,
            "pair_index": index // 2, "emitter": "AB"[index % 2],
            "role": "initiator" if index % 2 == 0 else "observer",
            "offset_samples": offset, "offset_s": offset_s,
            "search_window_s": [offset_s - SEARCH_EARLY_S, offset_s + SEARCH_LATE_S],
            "samples_b64": encoded, "sha256": digest})
    duration_frames = emissions[-1]["offset_samples"] + PROBE_FRAMES + SAMPLE_RATE
    identity = {"version": PROTOCOL_VERSION, "profile": PROFILE,
        "session_id": session_id, "seed": str(seed), "sample_rate": SAMPLE_RATE,
        "reference_offset_frames": REFERENCE_OFFSET_FRAMES,
        "reference_frames": REFERENCE_FRAMES,
        "emissions": [(e["id"], e["emitter"], e["sha256"], e["offset_samples"],
                       e["search_window_s"]) for e in emissions]}
    return {"version": PROTOCOL_VERSION, "profile": PROFILE,
        "protocol_id": hashlib.sha256(json.dumps(identity, sort_keys=True,
            separators=(",", ":")).encode()).hexdigest(),
        "session_id": session_id, "seed": str(seed), "sample_rate": SAMPLE_RATE,
        "sample_format": "float32-le", "probe_frames": PROBE_FRAMES,
        "reference_offset_frames": REFERENCE_OFFSET_FRAMES,
        "reference_frames": REFERENCE_FRAMES, "band_hz": list(BAND_HZ),
        "peak_amplitude": PEAK_AMPLITUDE, "pre_roll_s": PRE_ROLL_S,
        "post_roll_s": POST_ROLL_S, "slot_interval_s": SLOT_INTERVAL_S,
        "pair_gaps_s": [1.] * 8, "duration_frames": duration_frames,
        "duration_s": duration_frames / SAMPLE_RATE, "emissions": emissions,
        "attribution": {"window_origin": "first_sample_of_each_original_recording",
            "window_target": "chirp_onset", "precontext_s": .060,
            "boundary_guard_s": .010, "early_bound_s": SEARCH_EARLY_S,
            "late_bound_s": SEARCH_LATE_S,
            "identity": "schedule_consistent_only_not_acoustically_verified",
            "acoustic_freshness": False,
            "assumption": "Actual chirp onsets must remain within their declared slots despite capture offsets, output latency and coordination skew. Missing, extra or boundary events withhold timing; slots are never shifted to recover a favorable result."},
        "timing_semantics": {
            "template_origin": "Chirp start, 240 frames after the stored playback begins.",
            "matched_filter_lag": "Signed valid correlation with the 2400-frame chirp suffix; integer sample lag.",
            "arrival_estimation": "Published signal/noise norm >2 and earliest sharp peak >85% of strongest peak sharpness within the assumed 10 ms shadow window.",
            "schedule": "Coarse attribution only. Playback offsets and wall-clock timestamps never enter the four-arrival timing difference.",
            "sample_rate_conversion": "Resample only the reference if needed; original recording samples remain unchanged."},
        "identity_note": "The manifest is session-bound, but every emission and every session uses the identical sound. There is no acoustic freshness or authenticated source identity.",
        "playback_note": "Digital peak is 0.16. Physical loudness depends on device volume and route; use a comfortable volume."}


def decode_template(protocol: dict, emission_id: str) -> np.ndarray:
    """Verify and decode the full playback, including its 5 ms warmup."""
    if protocol.get("version") != PROTOCOL_VERSION or protocol.get("sample_format") != "float32-le":
        raise ValueError("Unsupported BeepBeep protocol or sample format")
    matches = [e for e in protocol.get("emissions", []) if e.get("id") == emission_id]
    if len(matches) != 1:
        raise ValueError(f"Expected one emission named {emission_id!r}")
    emission = matches[0]
    raw = base64.b64decode(emission["samples_b64"], validate=True)
    if len(raw) != PROBE_FRAMES * 4 or protocol.get("probe_frames") != PROBE_FRAMES:
        raise ValueError("BeepBeep playback must contain exactly 2640 float32 frames")
    if hashlib.sha256(raw).hexdigest() != emission.get("sha256"):
        raise ValueError("Template checksum mismatch")
    if raw != _waveform_bytes():
        raise ValueError("Playback differs from the declared BeepBeep reference waveform")
    return np.frombuffer(raw, dtype="<f4").copy()


def validate_protocol(protocol: dict) -> dict[str, np.ndarray]:
    """Reject changed identities, waveforms, durations or attribution windows."""
    expected = build_protocol(seed=protocol.get("seed"), session_id=protocol.get("session_id"))
    fields = ("version", "profile", "protocol_id", "session_id", "seed", "sample_rate",
        "sample_format", "probe_frames", "reference_offset_frames", "reference_frames",
        "band_hz", "peak_amplitude", "pre_roll_s", "post_roll_s", "slot_interval_s",
        "duration_frames", "duration_s", "pair_gaps_s", "attribution")
    for field in fields:
        if protocol.get(field) != expected[field]:
            raise ValueError(f"Invalid BeepBeep protocol field: {field}")
    emissions = protocol.get("emissions")
    if not isinstance(emissions, list) or len(emissions) != 16:
        raise ValueError("BeepBeep requires exactly 16 alternating emissions")
    result = {}
    for emission, declared in zip(emissions, expected["emissions"]):
        if not isinstance(emission, dict):
            raise ValueError("Invalid BeepBeep emission")
        # Check bytes and checksum separately for a useful integrity error.
        samples = decode_template(protocol, emission.get("id"))
        for field, value in declared.items():
            if emission.get(field) != value:
                raise ValueError(f"Invalid BeepBeep emission field: {field}")
        result[emission["id"]] = samples
    return result
