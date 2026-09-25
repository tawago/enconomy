"""Physics-based acoustic capture for the Proximity-Echo reproduction.

This module renders the two WAV recordings that two devices *would* have captured in
a given 3D scene, then feeds them into the EXISTING paper-faithful analysis pipeline
(alignment -> feature_extraction -> compensation -> scoring). Nothing downstream of the
WAV bytes is reimplemented; the simulation only replaces the physical microphone capture.

Two ways to obtain the four direction impulse responses (AA / AB / BA / BB):

  * `compute_shared_room_rirs` — one pyroomacoustics ShoeBox containing both devices.
    This is the physically rigorous path: all four responses share the room's image-source
    reflections, frequency-dependent wall absorption, and air absorption. Used for the
    positive cases (touch / 10 cm / 30 cm / 1 m, same room).

  * `compute_split_rirs` — device A and device B each solved in their OWN room for the
    self paths (AA, BB); the cross paths (AB, BA) are a parametric through-wall model
    (delay + attenuation + low-pass + an INDEPENDENT diffuse tail). This is an
    approximation, used for the negative cases (different room, remote / co-located
    attacker) where pyroomacoustics' single ShoeBox cannot represent inter-room
    transmission. It is intentionally pessimistic about shared echo structure, which is
    exactly the property the protocol's security rests on.

Naming follows the paper (see compensation.py):
    AA = initiator speaker -> initiator mic      (A hears itself)
    AB = initiator speaker -> observer  mic      (A's chirp heard by B)
    BA = observer  speaker -> initiator mic      (B's chirp heard by A)
    BB = observer  speaker -> observer  mic      (B hears itself)
Device A's recording = AA (self emissions) + BA (cross). Device B's = BB + AB.

Phase-1 (fix-plan §B1-B3, amended by docs/replica-findings.md §4.3): the renderer now
drives the production JOINT alignment entry point `extract_pair_recording_spectra`
(exactly as server.py does), wires `assess_capture_validity`, and — using its knowledge
of where every emission truly lands (a triple render: full / self-only / partner-only) —
classifies every pipeline selection as SELF / PARTNER / NOISE, so the sim can assert
ZERO aliased and ZERO swapped selections rather than merely counting `selection_ok`.
"""

from __future__ import annotations

import io
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyroomacoustics as pra
import soundfile as sf
from pyroomacoustics.directivities import CardioidFamily, DirectionVector
from scipy import signal as sps

sys.path.insert(0, str(Path(__file__).parent.parent))

from alignment import (  # noqa: E402
    bandpass_edges_hz,
    bandpass_filter,
    canonicalize_audio,
    matched_filter_envelope,
)
from challenge_generator import BeepSpec, make_beep_spec, synthesize_beep  # noqa: E402
from clipping import apply_clipping_exclusion, detect_clipping  # noqa: E402
from compensation import compute_compensated_signatures  # noqa: E402
from feature_extraction import (  # noqa: E402
    extract_pair_recording_spectra,
    platform_hint_from_user_agent,
)
from scoring import DEFAULT_VERDICT_THRESHOLD, cross_self_similarity, score_proximity  # noqa: E402
from server import build_device_summary, build_schedule  # noqa: E402
from validity import assess_capture_validity  # noqa: E402

SPEED_OF_SOUND = 343.0  # m/s, ~20 C
FS = 48_000

# --------------------------------------------------------------------------------------
# Simulation-local tunables (units + rationale). New knobs introduced by fix-plan §B1-B3;
# they belong to the SIM, not the production pipeline, so they live here rather than in
# pipeline_constants.py. Empirical numbers cite docs/replica-findings.md (§3 archive
# survey, 24 trials x 2 devices).
# --------------------------------------------------------------------------------------
# CardioidFamily shape parameter for device MICROPHONES (dimensionless, [0, 1]).
# p=0.5 is an ideal cardioid with a PERFECT rear null — unphysical: a real beamformed
# laptop mic still hears its own speaker (live self matched-filter peaks exceed 150) and
# still hears a phone behind it, just attenuated. The polar response is
# gain*(p + (1-p)cos theta), so the rear/front magnitude ratio is |2p-1|. p=0.34 gives
# |2*0.34-1| = 0.32, i.e. ~10 dB front-to-back — a finite lobe that reproduces the
# archive's partner/self peak ratios (§3: 0.1-11, median 0.6-1.0) instead of nulling
# either the self loop or the partner. (fix-plan B1.2)
MIC_CARDIOID_P = 0.34
# CardioidFamily shape for SPEAKERS: kept at an ideal cardioid. Speakers are genuinely
# directional and, unlike the mic, their pattern was never the deaf-to-self bug.
# KNOWN LIMITATION (deferred): p=0.5 is a PERFECT rear null, and the laptop preset places
# its mic exactly on the speaker's rear axis when facing_az=180 (same_room negatives /
# adverse_alias), so the direct self loop is nulled and the self train is carried by a room
# reflection ~27 ms late (self latency reads ~117 ms vs the 90 ms preset). Lowering p to
# ~0.4 restores the direct loop but shifts every scene's RIRs enough to collapse the tuned
# score separation and flip adverse_alias's rejection class — i.e. it needs a full B3
# scenario re-calibration, not a one-line constant bump, so it is left for that pass.
SPEAKER_CARDIOID_P = 0.5
# Full-scale peak each rendered recording is normalized to before int16 encoding. Models
# a device input-gain stage set so the loudest expected sound uses the dynamic range
# without clipping; well under 0.99 so detect_clipping() never trips on a valid capture.
# Per-recording scaling is Pearson-invariant, so it does not move any c_a/c_b (a uniform
# gain cancels in both the correlation and the compensation ratio).
NORMALIZE_TARGET_PEAK = 0.9
# WebAudio render-quantum in samples at 48 kHz (128 samples = 2.67 ms). Optional Android
# playout-start quantization knob (§3: 14-15 kHz android lags quantize in 2.67 ms steps).
RENDER_QUANTUM_SAMPLES = 128
# Fixed salt so per-beep playout jitter is IDENTICAL across the full and the muted
# (ground-truth) renders of one trial: jitter is drawn per schedule slot from an RNG
# seeded by (trial seed ^ salt), independent of which sources a given render places.
JITTER_RNG_SALT = 0x9E3779B9
# ms. A pipeline selection whose chirp start lands within this of a ground-truth arrival
# instant is attributed to that source. Matched-filter peaks are sub-ms and the smallest
# real self/partner gap observed is 17.1 ms (§3), so 12 ms attributes cleanly without
# cross-labeling a neighbouring source.
GT_MATCH_TOLERANCE_MS = 12.0
# AGC soft-knee drive (dimensionless). The agc knob models a device auto-gain stage; it MUST
# be a nonlinearity, because the per-recording peak normalization below is a uniform scalar
# that would exactly cancel any uniform AGC gain (leaving agc=True byte-identical to
# agc=False — the flag would silently do nothing). A tanh soft-knee compresses loud material
# toward the reference level while leaving quiet material ~linear, so the shape change
# survives the later normalization. Higher = harder compression; 1.5 is a gentle knee that
# only bends the top ~third of the range.
AGC_SOFT_KNEE_DRIVE = 1.5
# AEC model (fix-plan B4.1 / A2.7). Browser/OS echo cancellation adaptively suppresses the
# device's OWN known playback reference in its capture: the sharp chirp onset partially
# leaks (residual direct path), but the predictable room echo tail of the reference is
# cancelled — collapsing the SELF echo-period energy relative to the self chirp peak, which
# is exactly the A2.7 acoustic fingerprint. Modeled by attenuating the self RIR's tail
# (everything after the direct peak + a short leak window) before convolution; the partner
# path is untouched (AEC only knows the self reference).
# ms. Direct-path leak window kept at full amplitude after the RIR's direct peak.
AEC_DIRECT_WINDOW_MS = 1.0
# fraction. Residual gain applied to the self RIR tail after the leak window (a converged
# adaptive canceller leaves a small residual). 0.03 collapses the echo period ~30 dB.
AEC_TAIL_SUPPRESSION = 0.03

# The paper interleave: initiator at 1000, 2000, ...; observer 500 ms later. A partner
# whose (record-start skew + playout latency) is a multiple of this lands its beeps on the
# recorder's OWN grid — the degenerate schedule collision (fix-plan B1.1 / colliding_clocks).
INTERLEAVE_MS = 500.0

# Relay (man-in-the-middle) attacker model (Workstream E attack scenes, fix-plan §7 phase-4
# "attack scenarios (sim first: AEC + relay scenes)"). A relay attacker places a microphone
# in each victim's OWN room and a loudspeaker beside the OTHER victim, then forwards the
# captured audio ELECTRONICALLY — there is no speed-of-sound coupling between the two rooms,
# only the attacker's chosen relay latency. The cross path therefore becomes a COMPOSITE RIR:
#     victim_speaker -> attacker_mic          (in the victim's OWN room)   [capture leg]
#         (*) relay kernel: pure electronic delay + attacker-hardware coloration
#     attacker_speaker -> other_victim_mic    (in the OTHER room)          [replay leg]
# The self paths (AA, BB) are each solved in the device's own room, exactly like
# compute_split_rirs. This is the physically faithful realization of the paper's §V-D relay
# threat: unlike compute_split_rirs' single through-wall approximation, it models both the
# attacker's in-victim-room capture (which INHERITS that victim's speaker+room spectral
# signature — the property that makes a transparent relay partially defeat the echo binding)
# and a configurable electronic latency the round-trip identity must contend with.
# ms. The composite cross RIR is trimmed to this length before rendering. Capture and replay
# RIRs are each ~130 ms; their convolution plus the relay delay is longer, but the analysis
# only consumes the first ~100 ms echo period, so trimming bounds the fftconvolve without
# altering the modeled echo structure the scoring sees.
RELAY_RIR_TRIM_MS = 380.0


# --------------------------------------------------------------------------------------
# Device model
# --------------------------------------------------------------------------------------
@dataclass
class Device:
    """One physical device (speaker + microphone), plus its emission/clock behaviour.

    speaker_pos / mic_pos are 3D points in metres. They must differ (a real device's
    speaker and mic are centimetres apart); a zero gap produces a singular near-field RIR.

    Directivity is given as (azimuth_deg, colatitude_deg) pointing directions plus a
    pattern. `None` orientation means omnidirectional. colatitude is measured from +z
    (90 deg = horizontal). The asymmetry between a laptop mic beamformed at the user and
    a phone speaker firing elsewhere is the dominant real-world failure mode, so it is a
    first-class parameter here.
    """

    role: str  # "initiator" (laptop/A) or "observer" (phone/B)
    speaker_pos: tuple[float, float, float]
    mic_pos: tuple[float, float, float]
    speaker_dir: tuple[float, float] | None = None  # (az_deg, colat_deg) or None=omni
    mic_dir: tuple[float, float] | None = None
    speaker_gain: float = 1.0
    mic_gain: float = 1.0
    # Speaker frequency response. Two parts:
    #   * a band-pass models loudspeaker roll-off (a phone that cannot radiate 14 kHz
    #     across an air gap is a low highcut);
    #   * `speaker_resonances` are peaking-EQ bumps/dips (freq_hz, gain_db, Q) that give the
    #     speaker a characteristic NON-FLAT in-band envelope. This matters: the proximity
    #     decision is a Pearson correlation of *smoothed* echo spectra, so it keys on the
    #     shared smooth spectral envelope a device's speaker imprints on every chirp it
    #     emits (present in both its AA and AB paths). Perfectly flat speakers leave nothing
    #     to correlate at 6-12 kHz, where the wavelength (3-6 cm) is smaller than the mic
    #     spacing and fine room structure decorrelates. Real micro-speakers are peaky here.
    speaker_lowcut_hz: float = 150.0
    speaker_highcut_hz: float = 18_000.0
    speaker_resonances: tuple[tuple[float, float, float], ...] = ()
    # Clock / latency. self emissions ride the recorder's own clock (no relative drift);
    # cross emissions arrive shifted by the inter-device clock offset + output latency.
    output_latency_ms: float = 0.0
    clock_offset_ms: float = 0.0   # recording-start instant vs the reference device
    clock_drift_ppm: float = 0.0   # ADC rate error of this device's recorder clock
    # Per-beep playout-latency jitter (sigma, ms). Real playout starts wobble a fraction of
    # a ms slot-to-slot (§3: sigma 0.1-0.5 ms), stressing the median self_offset and the
    # tight per-beep windows. Seeded per trial, identical across the triple render.
    playout_jitter_ms: float = 0.0
    # Quantize this device's playout starts to WebAudio render quanta (2.67 ms). Off by
    # default; the android §3 14-15 kHz quantization knob.
    quantize_render_quantum: bool = False
    # Browser/OS echo cancellation active on THIS device's capture (fix-plan B4.1). When
    # True, the device's own self RIR tail is suppressed before rendering, collapsing the
    # self echo period (the A2.7 acoustic fingerprint). Off by default.
    aec: bool = False

    def speaker_directivity(self):
        return _make_directivity(self.speaker_dir, SPEAKER_CARDIOID_P)

    def mic_directivity(self):
        return _make_directivity(self.mic_dir, MIC_CARDIOID_P)


def _make_directivity(spec: tuple[float, float] | None, p: float):
    """Build a pyroomacoustics directivity with a FINITE front-to-back ratio.

    `p` is the CardioidFamily shape parameter (0=omni, 0.5=ideal cardioid, 1=figure-8).
    Mics use MIC_CARDIOID_P < 0.5 so the rear lobe is attenuated but not nulled (real
    beamformed mics still capture their own speaker and a device behind them).
    """
    if spec is None:
        return None  # omnidirectional
    az, colat = spec
    return CardioidFamily(orientation=DirectionVector(az, colat, degrees=True), p=p)


# --------------------------------------------------------------------------------------
# Device presets that reproduce the observed laptop/phone asymmetry
# --------------------------------------------------------------------------------------
def laptop(center: tuple[float, float, float], facing_az_deg: float = 0.0) -> Device:
    """MacBook-like device. Mic is a finite-front/back cardioid pointed at the user
    (facing_az); pointing it AWAY from a phone beside it attenuates (does not null) the
    cross path — the documented reason c_b weakens. Speaker and mic ~6 cm apart.

    Latency/clock: mac output latency ~90 ms sits in the measured 77-123 ms range
    (replica-findings §3) and inside the 60-150 ms mac self-latency prior; a small
    NEGATIVE ADC drift (opposite sign to the phone's) exercises the joint assignment's
    opposite-sign drift evidence."""
    cx, cy, cz = center
    return Device(
        role="initiator",
        speaker_pos=(cx, cy, cz),
        mic_pos=(cx + 0.06, cy, cz),
        speaker_dir=(facing_az_deg, 90.0),       # speaker fires toward user
        mic_dir=(facing_az_deg, 90.0),           # mic beamformed toward user
        speaker_gain=0.5,
        mic_gain=1.0,
        speaker_lowcut_hz=150.0,
        speaker_highcut_hz=16_000.0,
        # Distinctive laptop-speaker envelope in 6-12 kHz (small drivers are peaky).
        speaker_resonances=((6_500.0, 8.0, 2.5), (7_600.0, -7.0, 3.0),
                            (8_700.0, 9.0, 2.5), (9_900.0, -6.0, 3.0),
                            (11_000.0, 7.0, 2.0), (13_000.0, -8.0, 1.5)),
        output_latency_ms=90.0,                   # measured mac 77-123 ms (§3)
        clock_offset_ms=0.0,                      # reference clock
        clock_drift_ppm=-12.0,                    # independent ADC drift, opposite the phone
        playout_jitter_ms=0.3,                    # §3: per-beep sigma 0.1-0.5 ms
    )


def phone(center: tuple[float, float, float], speaker_az_deg: float = 90.0,
          clock_offset_ms: float = 60.0, clock_drift_ppm: float = 18.0,
          output_latency_ms: float = 185.0) -> Device:
    """Android-phone-like device. Bottom-edge speaker fires sideways/up (speaker_az),
    rolls off above ~10 kHz (why 14 kHz failed across the gap). Mic near the speaker.

    Latency/clock (fix-plan B1.1 repair): the OLD default `clock_offset 320 + output
    latency 180 = 500 ms` collided the interleaved schedules by construction (the partner
    landed on the recorder's own grid). The repaired default draws a representative
    android playout latency (185 ms; measured 95-310 ms, §3) with a modest record-start
    skew (60 ms); their sum 245 ms is NOT a multiple of the 500 ms interleave, so the
    partner train sits well clear of the self grid on both folds (>100 ms separation).
    The degenerate case is preserved on purpose as scenarios.colliding_clocks()."""
    cx, cy, cz = center
    return Device(
        role="observer",
        speaker_pos=(cx, cy, cz),
        mic_pos=(cx, cy + 0.12, cz),
        speaker_dir=(speaker_az_deg, 90.0),
        mic_dir=None,                             # phone mic roughly omni
        speaker_gain=0.55,
        mic_gain=1.2,
        speaker_lowcut_hz=250.0,
        speaker_highcut_hz=10_500.0,              # poor HF radiation
        # Distinctive phone-speaker envelope; peakier and rolls off earlier than the laptop.
        speaker_resonances=((6_400.0, 7.0, 2.5), (7_300.0, 9.0, 2.0),
                            (8_200.0, -7.0, 2.5), (9_000.0, 8.0, 2.5),
                            (9_900.0, -6.0, 3.0)),
        output_latency_ms=output_latency_ms,
        clock_offset_ms=clock_offset_ms,
        clock_drift_ppm=clock_drift_ppm,
        playout_jitter_ms=0.3,                    # §3: per-beep sigma 0.1-0.5 ms
    )


# --------------------------------------------------------------------------------------
# Impulse responses
# --------------------------------------------------------------------------------------
@dataclass
class RIRBundle:
    AA: np.ndarray
    AB: np.ndarray
    BA: np.ndarray
    BB: np.ndarray
    fs: int = FS

    def scaled(self, *, AA: float = 1.0, AB: float = 1.0, BA: float = 1.0, BB: float = 1.0) -> "RIRBundle":
        """Return a copy with per-channel amplitude scales. Used by B3 scenarios to make
        one direction deaf (e.g. BA x0.01 = laptop barely hears the phone) without
        re-solving the room."""
        return RIRBundle(AA=self.AA * AA, AB=self.AB * AB, BA=self.BA * BA, BB=self.BB * BB, fs=self.fs)


@dataclass
class Room:
    dims: tuple[float, float, float]
    absorption: float = 0.25     # average Sabine absorption coefficient of the walls
    max_order: int = 12          # image-source reflection order
    air_absorption: bool = True


def compute_shared_room_rirs(room: Room, dev_a: Device, dev_b: Device) -> RIRBundle:
    """Both devices in ONE ShoeBox -> all four RIRs share the same image-source room."""
    box = pra.ShoeBox(
        list(room.dims), fs=FS, materials=pra.Material(room.absorption),
        max_order=room.max_order, air_absorption=room.air_absorption,
    )
    box.add_source(list(dev_a.speaker_pos), directivity=dev_a.speaker_directivity())  # src0 = A
    box.add_source(list(dev_b.speaker_pos), directivity=dev_b.speaker_directivity())  # src1 = B
    box.add_microphone(list(dev_a.mic_pos), directivity=dev_a.mic_directivity())      # mic0 = A
    box.add_microphone(list(dev_b.mic_pos), directivity=dev_b.mic_directivity())      # mic1 = B
    box.compute_rir()
    return RIRBundle(
        AA=np.asarray(box.rir[0][0], dtype=np.float64),
        BA=np.asarray(box.rir[0][1], dtype=np.float64),
        AB=np.asarray(box.rir[1][0], dtype=np.float64),
        BB=np.asarray(box.rir[1][1], dtype=np.float64),
    )


def _wall_cross_rir(spk_pos, mic_pos, seed: int, attenuation_db: float,
                    lowpass_hz: float, tail_taps: int = 16) -> np.ndarray:
    """Parametric through-wall cross path: delayed+attenuated direct arrival, low-passed,
    plus a short INDEPENDENT diffuse tail (the recorder room's reverberation of the
    through-wall sound). The tail uses its own RNG seed so it does NOT share echo
    structure with the recorder's self path — this is what makes a different-room pair
    decorrelate, matching the protocol's security assumption. The low-pass models the
    strong high-frequency loss of transmission through a wall/door, so very little of the
    6-12 kHz analysis band survives — exactly why a remote attacker can't pass."""
    dist = float(np.linalg.norm(np.asarray(spk_pos) - np.asarray(mic_pos)))
    dist = max(dist, 0.5)
    rir = np.zeros(int(0.13 * FS), dtype=np.float64)
    direct_gain = (10.0 ** (-attenuation_db / 20.0)) / dist
    direct_delay = int(dist / SPEED_OF_SOUND * FS)
    if direct_delay < len(rir):
        rir[direct_delay] = direct_gain
    rng = np.random.default_rng(seed)
    for _ in range(tail_taps):
        t_ms = rng.uniform(3.0, 110.0)
        idx = direct_delay + int(t_ms / 1000.0 * FS)
        if idx < len(rir):
            rir[idx] += direct_gain * rng.uniform(0.1, 0.6) * np.exp(-t_ms / 45.0) * rng.choice([-1.0, 1.0])
    # 8th-order low-pass: a wall is a steep acoustic low-pass; the upper analysis band
    # is suppressed to the noise floor.
    sos = sps.butter(8, min(lowpass_hz, 0.49 * FS) / (0.5 * FS), btype="low", output="sos")
    return sps.sosfilt(sos, rir)


def compute_split_rirs(room_a: Room, dev_a: Device, room_b: Room, dev_b: Device,
                       attenuation_db: float = 55.0, lowpass_hz: float = 4_000.0,
                       seed: int = 0) -> RIRBundle:
    """Self paths from each device's own room; cross paths parametric through a wall.
    Use for different-room and attacker scenarios."""
    box_a = pra.ShoeBox(list(room_a.dims), fs=FS, materials=pra.Material(room_a.absorption),
                        max_order=room_a.max_order, air_absorption=room_a.air_absorption)
    box_a.add_source(list(dev_a.speaker_pos), directivity=dev_a.speaker_directivity())
    box_a.add_microphone(list(dev_a.mic_pos), directivity=dev_a.mic_directivity())
    box_a.compute_rir()
    aa = np.asarray(box_a.rir[0][0], dtype=np.float64)

    box_b = pra.ShoeBox(list(room_b.dims), fs=FS, materials=pra.Material(room_b.absorption),
                        max_order=room_b.max_order, air_absorption=room_b.air_absorption)
    box_b.add_source(list(dev_b.speaker_pos), directivity=dev_b.speaker_directivity())
    box_b.add_microphone(list(dev_b.mic_pos), directivity=dev_b.mic_directivity())
    box_b.compute_rir()
    bb = np.asarray(box_b.rir[0][0], dtype=np.float64)

    ab = _wall_cross_rir(dev_a.speaker_pos, dev_b.mic_pos, seed + 1, attenuation_db, lowpass_hz)
    ba = _wall_cross_rir(dev_b.speaker_pos, dev_a.mic_pos, seed + 2, attenuation_db, lowpass_hz)
    return RIRBundle(AA=aa, AB=ab, BA=ba, BB=bb)


# ms. Coloration tail after the relay's delay impulse — room for the causal pass-band /
# resonance impulse response so the attacker-hardware colouration actually shapes the relayed
# signal (without a tail the impulse sits at the array end and the ringing is truncated away,
# collapsing the kernel to a bare scaled delay). 40 ms comfortably covers a 4th-order
# band-pass + peaking-EQ settling at 48 kHz.
RELAY_KERNEL_TAIL_MS = 40.0


def _relay_kernel(latency_ms: float, lowcut_hz: float, highcut_hz: float,
                  resonances: tuple[tuple[float, float, float], ...], fs: int = FS) -> np.ndarray:
    """Electronic relay transfer function: a pure delay of `latency_ms` (the attacker's
    forwarding latency — NOT speed-of-sound) followed by the attacker hardware's colouration
    (a pass-band and optional peaking-EQ resonances). Convolved between the capture-leg and
    replay-leg RIRs to form the composite cross path. A wide, flat pass-band models a
    high-fidelity relay (the strong-attacker assumption); a narrow band + resonances models
    cheap/codec-limited relay gear. The delay impulse is placed with a trailing tail so the
    causal colouration impulse response is retained rather than truncated."""
    delay = int(round(latency_ms / 1000.0 * fs))
    tail = int(round(RELAY_KERNEL_TAIL_MS / 1000.0 * fs))
    kernel = np.zeros(delay + tail + 1, dtype=np.float64)
    kernel[delay] = 1.0  # unit impulse delayed by latency_ms; ringing extends into the tail
    nyq = 0.5 * fs
    low = max(20.0, lowcut_hz) / nyq
    high = min(highcut_hz, nyq * 0.999) / nyq
    if high > low:
        sos = sps.butter(4, [low, high], btype="bandpass", output="sos")
        kernel = sps.sosfilt(sos, kernel)  # causal: the delay must not be smeared backwards
    for f0, gain_db, q in resonances:
        if 0.0 < f0 < nyq:
            b, a = _peaking_eq(f0, gain_db, q)
            kernel = sps.lfilter(b, a, kernel)  # causal, same reason
    return kernel


def compute_relay_rirs(room_a: Room, dev_a: Device, room_b: Room, dev_b: Device, *,
                       attacker_mic_a_pos: tuple[float, float, float],
                       attacker_spk_a_pos: tuple[float, float, float],
                       attacker_mic_b_pos: tuple[float, float, float],
                       attacker_spk_b_pos: tuple[float, float, float],
                       latency_ms: float = 20.0, relay_gain_db: float = 0.0,
                       lowcut_hz: float = 150.0, highcut_hz: float = 16_000.0,
                       resonances: tuple[tuple[float, float, float], ...] = (),
                       seed: int = 0) -> RIRBundle:
    """Physically faithful relay (MiM) cross paths (see the RELAY_RIR_TRIM_MS note).

    Solves each device in its OWN room together with the attacker's local transducers:
      * box A holds dev_a's speaker+mic, plus the attacker's mic (near dev_a, capturing A)
        and the attacker's speaker (near dev_a, replaying B into A's room);
      * box B holds dev_b's speaker+mic, plus the attacker's mic (near dev_b, capturing B)
        and the attacker's speaker (near dev_b, replaying A into B's room).
    Self paths AA/BB come from each own room. Cross paths are the composite
        capture_leg (victim room) (*) relay_kernel (*) replay_leg (other room),
    scaled by the attacker's relay gain. The attacker transducers are omnidirectional and
    broadband (a capable attacker) unless `resonances`/`lowcut`/`highcut` narrow them."""
    box_a = pra.ShoeBox(list(room_a.dims), fs=FS, materials=pra.Material(room_a.absorption),
                        max_order=room_a.max_order, air_absorption=room_a.air_absorption)
    box_a.add_source(list(dev_a.speaker_pos), directivity=dev_a.speaker_directivity())  # src0 = A speaker
    box_a.add_source(list(attacker_spk_a_pos))                                           # src1 = attacker speaker in A's room
    box_a.add_microphone(list(dev_a.mic_pos), directivity=dev_a.mic_directivity())       # mic0 = A mic
    box_a.add_microphone(list(attacker_mic_a_pos))                                        # mic1 = attacker mic in A's room
    box_a.compute_rir()
    aa = np.asarray(box_a.rir[0][0], dtype=np.float64)          # A speaker -> A mic (self)
    replay_a = np.asarray(box_a.rir[0][1], dtype=np.float64)    # attacker speaker -> A mic (replay leg of BA)
    capture_a = np.asarray(box_a.rir[1][0], dtype=np.float64)   # A speaker -> attacker mic (capture leg of AB)

    box_b = pra.ShoeBox(list(room_b.dims), fs=FS, materials=pra.Material(room_b.absorption),
                        max_order=room_b.max_order, air_absorption=room_b.air_absorption)
    box_b.add_source(list(dev_b.speaker_pos), directivity=dev_b.speaker_directivity())  # src0 = B speaker
    box_b.add_source(list(attacker_spk_b_pos))                                           # src1 = attacker speaker in B's room
    box_b.add_microphone(list(dev_b.mic_pos), directivity=dev_b.mic_directivity())       # mic0 = B mic
    box_b.add_microphone(list(attacker_mic_b_pos))                                        # mic1 = attacker mic in B's room
    box_b.compute_rir()
    bb = np.asarray(box_b.rir[0][0], dtype=np.float64)          # B speaker -> B mic (self)
    replay_b = np.asarray(box_b.rir[0][1], dtype=np.float64)    # attacker speaker -> B mic (replay leg of AB)
    capture_b = np.asarray(box_b.rir[1][0], dtype=np.float64)   # B speaker -> attacker mic (capture leg of BA)

    kernel = _relay_kernel(latency_ms, lowcut_hz, highcut_hz, resonances)
    gain = 10.0 ** (relay_gain_db / 20.0)
    trim = int(RELAY_RIR_TRIM_MS / 1000.0 * FS)

    def _compose(capture: np.ndarray, replay: np.ndarray) -> np.ndarray:
        composite = sps.fftconvolve(sps.fftconvolve(capture, kernel), replay) * gain
        return composite[:trim] if composite.size > trim else composite

    # AB = A heard by B: capture A in room A, relay, replay into room B toward B's mic.
    ab = _compose(capture_a, replay_b)
    # BA = B heard by A: capture B in room B, relay, replay into room A toward A's mic.
    ba = _compose(capture_b, replay_a)
    return RIRBundle(AA=aa, AB=ab, BA=ba, BB=bb)


# --------------------------------------------------------------------------------------
# Rendering recordings
# --------------------------------------------------------------------------------------
def _peaking_eq(f0: float, gain_db: float, q: float, fs: int = FS) -> tuple[np.ndarray, np.ndarray]:
    """Audio-EQ-cookbook peaking biquad. gain_db>0 is a bump, <0 a dip, centred at f0."""
    A = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * np.pi * f0 / fs
    alpha = np.sin(w0) / (2.0 * q)
    cw = np.cos(w0)
    b = np.array([1 + alpha * A, -2 * cw, 1 - alpha * A], dtype=np.float64)
    a = np.array([1 + alpha / A, -2 * cw, 1 - alpha / A], dtype=np.float64)
    return b / a[0], a / a[0]


def _speaker_filter(beep: np.ndarray, dev: Device) -> np.ndarray:
    """Colour the emitted beep by the device speaker's pass-band roll-off and its
    characteristic in-band resonances."""
    nyq = 0.5 * FS
    out = beep.astype(np.float64)
    low = max(20.0, dev.speaker_lowcut_hz) / nyq
    high = min(dev.speaker_highcut_hz, nyq * 0.999) / nyq
    if high > low:
        sos = sps.butter(4, [low, high], btype="bandpass", output="sos")
        out = sps.sosfiltfilt(sos, out)
    for f0, gain_db, q in dev.speaker_resonances:
        if 0.0 < f0 < nyq:
            b, a = _peaking_eq(f0, gain_db, q)
            out = sps.filtfilt(b, a, out)
    return out


def _place(buf: np.ndarray, wave: np.ndarray, start_sample: int) -> None:
    if start_sample < 0:
        wave = wave[-start_sample:]
        start_sample = 0
    end = start_sample + len(wave)
    if start_sample >= len(buf) or len(wave) == 0:
        return
    end = min(end, len(buf))
    buf[start_sample:end] += wave[: end - start_sample]


def _aec_suppress_rir(rir: np.ndarray, fs: int) -> np.ndarray:
    """AEC model (fix-plan B4.1): keep the direct arrival (+ a short leak window) and
    attenuate the RIR tail, so the self chirp onset survives but the self echo period
    collapses — the A2.7 fingerprint. Only ever applied to a device's OWN self RIR."""
    if rir.size == 0:
        return rir
    out = rir.astype(np.float64).copy()
    peak = int(np.argmax(np.abs(out)))
    leak_end = peak + int(round(AEC_DIRECT_WINDOW_MS / 1000.0 * fs))
    if leak_end < out.size:
        out[leak_end:] *= AEC_TAIL_SUPPRESSION
    return out


def _arrival_sample(arrival_ms: float, quantize: bool, fs: int) -> int:
    idx = int(round(arrival_ms / 1000.0 * fs))
    if quantize:
        idx = int(round(idx / RENDER_QUANTUM_SAMPLES) * RENDER_QUANTUM_SAMPLES)
    return idx


def _expected_arrival_ms(recorder: Device, partner: Device, offset_ms: float,
                         emitter_is_self: bool) -> float:
    """Deterministic (jitter-free) instant, in ms on the recorder's timeline, where the
    beep scheduled at `offset_ms` lands — the SAME formula _render_samples uses, minus the
    per-beep jitter (sub-ms, negligible for windowing). Ground-truth slot windows are
    centered here, not on the bare schedule offset: a partner whose (clock_offset+latency)
    pushes its arrival past +/-half a period from its slot offset (e.g. adverse_alias, where
    345+155 lands the partner ~1000 ms = ~0 mod-period, straddling the slot boundary) would
    otherwise fall in a blind hole of an offset-anchored window and be mis-measured as the
    previous beep's echo tail."""
    if emitter_is_self:
        return offset_ms + recorder.output_latency_ms
    wall_ms = partner.clock_offset_ms + offset_ms + partner.output_latency_ms
    return (wall_ms - recorder.clock_offset_ms) * (1.0 + recorder.clock_drift_ppm * 1e-6)


def _render_samples(recorder: Device, partner: Device, rirs: RIRBundle,
                    schedule: list[dict], beep_spec: BeepSpec, *,
                    emit: str = "both", snr_db: float = 40.0, add_noise: bool = True,
                    agc: bool = False, seed: int = 0) -> np.ndarray:
    """Render one device's full recording as a float buffer (pre int16 encoding).

    emit: "both" (self+partner, the real recording), "self" (self emissions only) or
    "partner" (partner emissions only) — the last two are the ground-truth renders that
    reveal exactly where each source lands. Per-beep playout jitter is drawn from a seed-
    keyed RNG in schedule order, so a slot's jitter is identical across all three emit
    modes and the ground truth matches the full render sample-for-sample.
    """
    fs = beep_spec.sample_rate
    assert fs == rirs.fs == FS
    is_a = recorder.role == "initiator"
    self_rir = rirs.AA if is_a else rirs.BB
    cross_rir = rirs.BA if is_a else rirs.AB  # partner -> recorder
    if recorder.aec:
        # AEC cancels the device's own playback reference only; the partner path is intact.
        self_rir = _aec_suppress_rir(self_rir, FS)

    tail_ms = 1000
    total_ms = schedule[-1]["offset_ms"] + tail_ms
    n = int(total_ms / 1000.0 * fs) + max(len(self_rir), len(cross_rir)) + fs
    buf = np.zeros(n, dtype=np.float64)
    beep = synthesize_beep(beep_spec).astype(np.float64)

    self_emit = sps.fftconvolve(_speaker_filter(beep, recorder) * recorder.speaker_gain, self_rir)
    cross_emit = sps.fftconvolve(_speaker_filter(beep, partner) * partner.speaker_gain, cross_rir)

    jitter_rng = np.random.default_rng((seed ^ JITTER_RNG_SALT) & 0xFFFFFFFF)
    jitter_norm = jitter_rng.standard_normal(len(schedule))

    for i, entry in enumerate(schedule):
        emitter_is_self = entry["emitter_role"] == recorder.role
        emitter = recorder if emitter_is_self else partner
        jitter_ms = float(jitter_norm[i]) * emitter.playout_jitter_ms
        if emitter_is_self:
            if emit not in ("both", "self"):
                continue
            # Self emission rides the recorder's own clock: schedule offset + output latency.
            arrival_ms = entry["offset_ms"] + recorder.output_latency_ms + jitter_ms
            _place(buf, self_emit, _arrival_sample(arrival_ms, recorder.quantize_render_quantum, fs))
        else:
            if emit not in ("both", "partner"):
                continue
            # Cross emission: partner fires on its clock; map wall time into the recorder's
            # timeline via the inter-device clock offset and the recorder's rate drift.
            wall_ms = partner.clock_offset_ms + entry["offset_ms"] + partner.output_latency_ms + jitter_ms
            arrival_ms = (wall_ms - recorder.clock_offset_ms) * (1.0 + recorder.clock_drift_ppm * 1e-6)
            _place(buf, cross_emit, _arrival_sample(arrival_ms, partner.quantize_render_quantum, fs))

    buf *= recorder.mic_gain

    if add_noise:
        rng = np.random.default_rng(seed + (1 if is_a else 2))
        sig_rms = float(np.sqrt(np.mean(buf ** 2))) + 1e-12
        noise_rms = sig_rms / (10.0 ** (snr_db / 20.0))
        buf += noise_rms * rng.standard_normal(len(buf))

    if agc:
        # Nonlinear soft-knee AGC. A plain gain scalar here would be undone by the uniform
        # peak-normalization below (making agc=True == agc=False); a tanh soft-knee keyed to
        # the 99.5th-percentile level is a genuine nonlinearity that compresses the loud tail
        # toward the reference while leaving quiet material near-linear, so it survives.
        level = float(np.percentile(np.abs(buf), 99.5)) + 1e-9
        buf = np.tanh((buf / level) * AGC_SOFT_KNEE_DRIVE) * (level / AGC_SOFT_KNEE_DRIVE)

    # Device input-gain normalization: bring the peak to NORMALIZE_TARGET_PEAK so a valid
    # capture never clips (detect_clipping trips on a single >=0.99 sample). Uniform per-
    # recording scaling is Pearson-invariant, so this does not move any score.
    peak = float(np.max(np.abs(buf)))
    if peak > 0.0:
        buf *= NORMALIZE_TARGET_PEAK / peak
    return buf


def render_recording(recorder: Device, partner: Device, rirs: RIRBundle,
                     schedule: list[dict], beep_spec: BeepSpec,
                     snr_db: float = 40.0, agc: bool = False, seed: int = 0,
                     drive: float = 1.0) -> bytes:
    """Synthesize one device's full WAV recording for the whole session.

    `drive` > 1 pushes the normalized signal past full scale so it clips on int16 encode —
    used to reproduce touch-distance saturation deliberately (default 1.0 = no clipping).
    """
    buf = _render_samples(recorder, partner, rirs, schedule, beep_spec,
                          emit="both", snr_db=snr_db, add_noise=True, agc=agc, seed=seed)
    clipped = np.clip(buf * drive, -1.0, 1.0).astype(np.float32)
    out = io.BytesIO()
    sf.write(out, clipped, beep_spec.sample_rate, format="WAV", subtype="PCM_16")
    return out.getvalue()


# --------------------------------------------------------------------------------------
# Ground truth (fix-plan B2): triple render reveals where every source truly lands
# --------------------------------------------------------------------------------------
def _slot_arrivals(recorder: Device, partner: Device, rirs: RIRBundle, schedule: list[dict],
                   beep_spec: BeepSpec, *, emit: str, seed: int) -> dict[int, float]:
    """Render ONLY `emit` sources (no noise) and return, per matching schedule slot, the
    matched-filter envelope-peak instant in ms — the same index convention pass-3 uses for
    chirp_start, so classification is apples-to-apples."""
    role = recorder.role
    want_self = emit == "self"
    buf = _render_samples(recorder, partner, rirs, schedule, beep_spec,
                          emit=emit, add_noise=False, agc=False, seed=seed)
    # Band-parametric (D3.5): filter the ground-truth render on the SAME band the production
    # pipeline derives from beep_spec, not the module-level 6-12 kHz constants — otherwise a
    # non-default-band scenario (e.g. a future 14-15 kHz sim) would classify slot arrivals from
    # a near-zero, wrong-band buffer and assert against false ground truth.
    low_hz, high_hz = bandpass_edges_hz(beep_spec.start_freq_hz, beep_spec.end_freq_hz)
    filtered = bandpass_filter(buf.astype(np.float32), beep_spec.sample_rate,
                               low_hz=low_hz, high_hz=high_hz)
    envelope = matched_filter_envelope(filtered, synthesize_beep(beep_spec))
    fs = beep_spec.sample_rate
    # +/- ~half a period around the EXPECTED arrival (not the bare slot offset). Same-source
    # arrivals are one full period (1000 ms) apart, so a +/-480 ms window centered on the true
    # expected instant is unambiguous (one emission per window) AND has no blind hole for
    # partners whose latency+skew pushes them across the slot boundary (finding: adverse_alias).
    half = int(round(0.480 * fs))
    arrivals: dict[int, float] = {}
    for entry in schedule:
        emitter_is_self = entry["emitter_role"] == role
        if emitter_is_self != want_self:
            continue
        exp_ms = _expected_arrival_ms(recorder, partner, float(entry["offset_ms"]), emitter_is_self)
        center = int(round(exp_ms / 1000.0 * fs))
        lo = max(0, center - half)
        hi = min(len(envelope), center + half)
        if hi - lo < 3:
            continue
        peak = lo + int(np.argmax(envelope[lo:hi]))
        arrivals[int(entry["beep_index"])] = peak / fs * 1000.0
    return arrivals


def _classify_device(per_beep: list[dict], role: str, rate: int,
                     self_gt: dict[int, float], partner_gt: dict[int, float],
                     period_ms: float) -> dict:
    """Ground-truth verdict for one recording: label every OK selection SELF/PARTNER/NOISE
    by nearest true arrival, and count aliases (cross selection grabbing self) and swaps
    (self selection grabbing partner)."""
    self_arr = list(self_gt.values())
    partner_arr = list(partner_gt.values())
    alias = swap = noise = 0
    self_timing_err: list[float] = []
    partner_timing_err: list[float] = []
    for entry in per_beep:
        sel = entry["selection"]
        if not sel.get("selection_ok"):
            continue
        chirp_ms = float(sel["chirp_start"]) / float(rate) * 1000.0
        d_self = min((abs(chirp_ms - g) for g in self_arr), default=float("inf"))
        d_partner = min((abs(chirp_ms - g) for g in partner_arr), default=float("inf"))
        if min(d_self, d_partner) > GT_MATCH_TOLERANCE_MS:
            label = "NOISE"
        elif d_self <= d_partner:
            label = "SELF"
        else:
            label = "PARTNER"
        is_self_beep = entry["emitter_role"] == role
        if label == "NOISE":
            noise += 1
        elif is_self_beep:
            if label == "PARTNER":
                swap += 1
            else:
                self_timing_err.append(d_self)
        else:  # cross beep
            if label == "SELF":
                alias += 1
            else:
                partner_timing_err.append(d_partner)

    # True cross offset: partner arrival relative to its own schedule slot, median over
    # cross slots (the quantity the pipeline's cross_offset_ms estimates).
    true_cross = None
    residuals = []
    for entry in per_beep:
        if entry["emitter_role"] == role:
            continue
        gt = partner_gt.get(int(entry["beep_index"]))
        if gt is None:
            continue
        residuals.append(_circ_signed(gt - float(entry["offset_ms"]), period_ms))
    if residuals:
        true_cross = float(np.median(residuals))
    # True self latency: self arrival relative to its schedule slot.
    self_lat = None
    self_res = [self_gt[e["beep_index"]] - float(e["offset_ms"])
                for e in per_beep if e["emitter_role"] == role and e["beep_index"] in self_gt]
    if self_res:
        self_lat = float(np.median(self_res))
    return {
        "alias_count": alias,
        "swap_count": swap,
        "noise_count": noise,
        "self_selection_timing_err_ms": round(float(np.mean(self_timing_err)), 3) if self_timing_err else None,
        "partner_selection_timing_err_ms": round(float(np.mean(partner_timing_err)), 3) if partner_timing_err else None,
        "true_cross_offset_ms": round(true_cross, 3) if true_cross is not None else None,
        "true_self_latency_ms": round(self_lat, 3) if self_lat is not None else None,
    }


def _circ_signed(value_ms: float, period_ms: float) -> float:
    residual = float(value_ms) % period_ms
    if residual > period_ms / 2.0:
        residual -= period_ms
    return float(residual)


def _compensation_check(signatures, dev_a: Device, dev_b: Device) -> dict:
    """B2 compensation ground truth. In this sim the microphones are frequency-flat
    (a gain + a directivity scalar per path), so the paper's comp(f) ~ M_B/M_A should be
    FLAT across frequency near proximity (the path terms cancel). We therefore check the
    SHAPE (spread) of the recovered compensation rather than its absolute value, which is
    confounded by the per-recording normalization scale (that scale is Pearson-invariant
    and cancels downstream, so it never touches c_a/c_b). Reports the nominal mic-gain
    ratio for reference.

    SCOPE: `spread` measures ratio spikes on the coincident single-band chirp grid (where
    both devices' sources land on the same frequency points), NOT the chirp->echo remap
    extrapolation D3.6 targets. D3.6's hazard is the compensation being extrapolated from
    the chirp grid onto echo-grid frequencies the chirp grid never covered; this metric
    only sees the chirp grid where the sources coincide, so it cannot catch that
    extrapolation — treat it as a coincident-grid conditioning check, not a D3.6 guard."""
    comp = np.asarray(signatures.compensation_at_chirp_grid, dtype=np.float64)
    comp = comp[np.isfinite(comp) & (comp > 0.0)]
    if comp.size == 0:
        return {"n": 0, "geomean": None, "spread": None, "nominal_mic_ratio": None}
    geomean = float(np.exp(np.mean(np.log(comp))))
    spread = float(comp.max() / comp.min())
    return {
        "n": int(comp.size),
        "geomean": round(geomean, 4),
        "spread": round(spread, 3),
        "nominal_mic_ratio": round(dev_b.mic_gain / dev_a.mic_gain, 4),
    }


# --------------------------------------------------------------------------------------
# End-to-end: scene -> recordings -> existing scorer
# --------------------------------------------------------------------------------------
def score_recordings(wav_a: bytes, wav_b: bytes, schedule: list[dict], beep_spec: BeepSpec, *,
                     platform_hint_a: str | None = "mac", platform_hint_b: str | None = "android",
                     granted_settings_a: dict | None = None, granted_settings_b: dict | None = None,
                     verdict_threshold: float = DEFAULT_VERDICT_THRESHOLD,
                     score_mode: str = "mean") -> dict:
    """Run the unmodified paper pipeline (joint alignment -> compensation -> scoring ->
    validity) on an already-rendered pair of WAV recordings, exactly as server.py does.

    Factored out of run_trial so both the physics scenes AND the WAV-level replay
    demonstration (scenarios.replay_exposure) score through the IDENTICAL code path — the
    replay scorer therefore cannot drift from what a live trial measures. Returns the raw
    pipeline objects (spectra, summaries, compensated signatures, score, validity) without
    the sim-only ground-truth triple render (which needs the scene, not just the WAVs)."""
    spectra_a, spectra_b = extract_pair_recording_spectra(
        wav_a, wav_b, schedule, beep_spec,
        platform_hint_a=platform_hint_a, platform_hint_b=platform_hint_b,
    )
    audio_a, _, _ = canonicalize_audio(wav_a, beep_spec.sample_rate)
    audio_b, _, _ = canonicalize_audio(wav_b, beep_spec.sample_rate)
    clipping_a = detect_clipping(audio_a)
    clipping_b = detect_clipping(audio_b)
    exclusion_a = apply_clipping_exclusion(audio_a, spectra_a)
    exclusion_b = apply_clipping_exclusion(audio_b, spectra_b)

    meta_a = {"granted_track_settings": granted_settings_a} if granted_settings_a else {}
    meta_b = {"granted_track_settings": granted_settings_b} if granted_settings_b else {}
    summary_a = build_device_summary("initiator", spectra_a, clipping_a, meta_a, exclusion_a)
    summary_b = build_device_summary("observer", spectra_b, clipping_b, meta_b, exclusion_b)

    signatures = compute_compensated_signatures(
        spectra_a["per_beep"], spectra_b["per_beep"],
        low_hz=beep_spec.start_freq_hz, high_hz=beep_spec.end_freq_hz,
    )
    score = score_proximity(signatures.to_dict(), verdict_threshold=verdict_threshold, score_mode=score_mode)
    validity = assess_capture_validity(
        summary_a, summary_b,
        signature_freq_points=len(signatures.freqs_hz),
        raw_score=score.score, raw_verdict=score.verdict,
        cross_self_similarity=cross_self_similarity(signatures.to_dict()),
        compensation_dropped_beeps=signatures.n_grid_mismatch_dropped,
    )
    return {
        "spectra_a": spectra_a, "spectra_b": spectra_b,
        "summary_a": summary_a, "summary_b": summary_b,
        "signatures": signatures, "score": score, "validity": validity,
    }


@dataclass
class Trial:
    dev_a: Device
    dev_b: Device
    rirs: RIRBundle
    label: str = ""
    snr_db: float = 40.0
    agc: bool = False
    seed: int = 0
    drive: float = 1.0
    beep_overrides: dict = field(default_factory=dict)
    platform_hint_a: str | None = "mac"
    platform_hint_b: str | None = "android"
    # Granted getUserMedia track settings injected into each device's summary metadata,
    # exactly as the browser uploads them (fix-plan A2.7). Lets a scenario exercise the
    # hard AEC/voice-isolation guard (e.g. {"echoCancellation": True}); None => the guard
    # sees no granted settings (an unreported-capture warning, never a gate).
    granted_settings_a: dict | None = None
    granted_settings_b: dict | None = None


def run_trial(trial: Trial, beeps_per_device: int = 20, score_mode: str = "mean",
              verdict_threshold: float = DEFAULT_VERDICT_THRESHOLD,
              save_wav_dir: str | None = None) -> dict:
    """Render both recordings and run the unmodified paper pipeline through its JOINT
    entry point (exactly as server.py does), then wire validity and attach ground-truth
    verdicts (alias/swap counts, timing errors, true-vs-estimated Δ) from the triple
    render. Returns the score, the capture-validity verdict + reasons, and diagnostics."""
    schedule = [b.to_dict() for b in build_schedule(beeps_per_device=beeps_per_device)]
    beep_spec = make_beep_spec(seed=trial.seed, **trial.beep_overrides)

    wav_a = render_recording(trial.dev_a, trial.dev_b, trial.rirs, schedule, beep_spec,
                             snr_db=trial.snr_db, agc=trial.agc, seed=trial.seed, drive=trial.drive)
    wav_b = render_recording(trial.dev_b, trial.dev_a, trial.rirs, schedule, beep_spec,
                             snr_db=trial.snr_db, agc=trial.agc, seed=trial.seed, drive=trial.drive)

    if save_wav_dir:
        d = Path(save_wav_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{trial.label or 'trial'}_initiator.wav").write_bytes(wav_a)
        (d / f"{trial.label or 'trial'}_observer.wav").write_bytes(wav_b)

    # Production joint alignment + compensation + scoring + validity (shared with the replay
    # demonstration via score_recordings, so the two cannot drift). Self/partner assignment
    # needs BOTH recordings.
    scored = score_recordings(
        wav_a, wav_b, schedule, beep_spec,
        platform_hint_a=trial.platform_hint_a, platform_hint_b=trial.platform_hint_b,
        granted_settings_a=trial.granted_settings_a, granted_settings_b=trial.granted_settings_b,
        verdict_threshold=verdict_threshold, score_mode=score_mode,
    )
    spectra_a, spectra_b = scored["spectra_a"], scored["spectra_b"]
    signatures, score, validity = scored["signatures"], scored["score"], scored["validity"]

    # Ground truth via the triple render (self-only / partner-only), classify selections.
    rate_a = spectra_a["canonical_sample_rate"]
    rate_b = spectra_b["canonical_sample_rate"]
    period_ms = 2.0 * INTERLEAVE_MS
    gt_self_a = _slot_arrivals(trial.dev_a, trial.dev_b, trial.rirs, schedule, beep_spec, emit="self", seed=trial.seed)
    gt_part_a = _slot_arrivals(trial.dev_a, trial.dev_b, trial.rirs, schedule, beep_spec, emit="partner", seed=trial.seed)
    gt_self_b = _slot_arrivals(trial.dev_b, trial.dev_a, trial.rirs, schedule, beep_spec, emit="self", seed=trial.seed)
    gt_part_b = _slot_arrivals(trial.dev_b, trial.dev_a, trial.rirs, schedule, beep_spec, emit="partner", seed=trial.seed)
    gt_a = _classify_device(spectra_a["per_beep"], "initiator", rate_a, gt_self_a, gt_part_a, period_ms)
    gt_b = _classify_device(spectra_b["per_beep"], "observer", rate_b, gt_self_b, gt_part_b, period_ms)

    def _cross_err(spectra, gt) -> float | None:
        est, true = spectra.get("cross_offset_ms"), gt["true_cross_offset_ms"]
        if est is None or true is None:
            return None
        return round(abs(_circ_signed(est - true, period_ms)), 3)
    gt_a["cross_offset_err_ms"] = _cross_err(spectra_a, gt_a)
    gt_b["cross_offset_err_ms"] = _cross_err(spectra_b, gt_b)
    gt_a["est_cross_offset_ms"] = spectra_a.get("cross_offset_ms")
    gt_b["est_cross_offset_ms"] = spectra_b.get("cross_offset_ms")

    assignment = spectra_a.get("train_assignment") or {}

    ok_a = sum(1 for e in spectra_a["per_beep"]
               if e["emitter_role"] == "initiator" and e["selection"]["selection_ok"])
    ok_b = sum(1 for e in spectra_b["per_beep"]
               if e["emitter_role"] == "observer" and e["selection"]["selection_ok"])
    cross_a = sum(1 for e in spectra_a["per_beep"]
                  if e["emitter_role"] == "observer" and e["selection"]["selection_ok"])
    cross_b = sum(1 for e in spectra_b["per_beep"]
                  if e["emitter_role"] == "initiator" and e["selection"]["selection_ok"])

    return {
        "label": trial.label,
        "c_a": score.c_a,
        "c_b": score.c_b,
        "score": score.score,
        "verdict": score.verdict,                       # raw score >= threshold
        "proximity_verdict": validity.proximity_verdict,  # None when withheld
        "capture_valid": validity.capture_valid,
        "failure_reasons": validity.failure_reasons,
        "warnings": validity.warnings,
        "threshold": score.threshold,
        "score_mode": score.score_mode,
        "period_ok": {"AA": ok_a, "BB": ok_b, "BA_at_A": cross_a, "AB_at_B": cross_b},
        "cross_offset_ms": {"A": spectra_a["cross_offset_ms"], "B": spectra_b["cross_offset_ms"]},
        "cross_offset_source": {"A": spectra_a["cross_offset_source"], "B": spectra_b["cross_offset_source"]},
        "self_offset_ms": {"A": spectra_a["self_offset_ms"], "B": spectra_b["self_offset_ms"]},
        "assignment": {
            "status": assignment.get("status"),
            "round_trip_ms": assignment.get("round_trip_ms"),
            "drift_support": assignment.get("drift_support"),
        },
        "ground_truth": {"device_a": gt_a, "device_b": gt_b},
        "compensation": _compensation_check(signatures, trial.dev_a, trial.dev_b),
        "alias_count": gt_a["alias_count"] + gt_b["alias_count"],
        "swap_count": gt_a["swap_count"] + gt_b["swap_count"],
        "beeps_per_device": beeps_per_device,
    }
