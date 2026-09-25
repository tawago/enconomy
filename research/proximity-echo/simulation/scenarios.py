"""Pre-built scenes for the Proximity-Echo simulation.

Positive cases (should stay capture-valid and score high): a laptop and a phone in one
room at varying separation. Negative cases (should reject / withhold): different rooms, a
remote attacker relaying beeps, and a co-located attacker sitting next to one legit device.

B3 alias-regression scenes (fix-plan §B3, re-scoped by replica-findings §4.3 — there is NO
self-replica, so `replica_alias()` is replaced by the real degeneracy failure modes):

  * `adverse_alias()`         — adverse orientation + BA x0.01 + danger-zone offsets.
  * `partner_latch()`         — partner inside the pass-1 self window AND louder than self.
  * `late_android()`          — android self latency > 230 ms (old window edge).
  * `partner_in_self_tail()`  — partner-to-self gap < 20 ms (mask-trim territory).
  * `deaf_laptop()`           — one-sided deafness (laptop cannot hear the phone).
  * `colliding_clocks()`      — the degenerate 500 ms collision, deliberately.
  * `aec_on()`                — browser/OS echo cancellation active (A2.7 guard + fingerprint).

Workstream E attack scenes (fix-plan §7 phase-4, "sim first: AEC + relay scenes"):

  * `relay_attacker()`   — general relay (MiM): mic in each victim room, speaker by the other,
                           electronic forwarding latency + coloration. Latency/gain sweepable.
  * `relay_transparent()`— strongest (flat, 5 ms) relay. FINDING: rejected only by the sub-0.78
                           score (~0.69) while staying capture_valid — no anti-relay guard fires.
  * `relay_loud()`       — a transparent relay driven hard; withheld via cross_offset_sum_inconsistent.
  * `relay_t3()`         — strongest relay vs a T3 external OMNI mic (bypasses beamforming). FINDING:
                           no T3 param reaches ACCEPT (swept max ~0.44); the omni mic collapses the
                           laptop self-loop, so a T3 relay is WITHHELD (capture-invalid), not verified.
  * `replay_exposure()`  — protocol-level demo (returns facts, not a Trial): the fixed-template
                           challenge has no freshness, so a stale recording verifies in a later
                           session identically. Documents the §4.4 replay gap.

Each `*_attacker`/B3 builder returns a `Trial` ready for `scene.run_trial`; `replay_exposure`
returns a facts dict.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the project-root pipeline modules importable regardless of the caller's cwd (mirrors
# scene.py's bootstrap). scenarios now imports challenge_generator/server directly, so we
# cannot rely on `from scene import ...` having run scene.py's own sys.path insertion first.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from challenge_generator import make_beep_spec, synthesize_beep  # noqa: E402
from scene import (  # noqa: E402
    Room,
    Trial,
    compute_relay_rirs,
    compute_shared_room_rirs,
    compute_split_rirs,
    laptop,
    phone,
    render_recording,
    score_recordings,
)
from server import build_schedule  # noqa: E402

# A typical small office/room.
DEFAULT_ROOM = Room(dims=(4.5, 3.5, 2.7), absorption=0.22, max_order=12)


# --------------------------------------------------------------------------------------
# Positive / negative baseline scenes
# --------------------------------------------------------------------------------------
def same_room(distance_m: float, *, room: Room = DEFAULT_ROOM, snr_db: float = 40.0,
              phone_speaker_az_deg: float = 90.0, laptop_facing_az_deg: float = 180.0,
              agc: bool = True, seed: int = 0, beep_overrides: dict | None = None) -> Trial:
    """Laptop and phone in one room, `distance_m` apart on a desk (z=0.75 m).
    `laptop_facing_az_deg`=0 aims the laptop mic at the phone (favorable); =180 aims it at
    the user (adverse — the documented directivity blocker)."""
    cx, cy, cz = room.dims[0] / 2, room.dims[1] / 2, 0.75
    lap = laptop((cx - distance_m / 2, cy, cz), facing_az_deg=laptop_facing_az_deg)
    ph = phone((cx + distance_m / 2, cy, cz), speaker_az_deg=phone_speaker_az_deg)
    rirs = compute_shared_room_rirs(room, lap, ph)
    return Trial(dev_a=lap, dev_b=ph, rirs=rirs, label=f"same_room_{distance_m*100:.0f}cm",
                 snr_db=snr_db, agc=agc, seed=seed, beep_overrides=beep_overrides or {})


def different_rooms(*, snr_db: float = 40.0, agc: bool = True, seed: int = 0,
                    beep_overrides: dict | None = None) -> Trial:
    """Legit-looking devices that are actually in two separate rooms — the basic negative
    case. Self echoes come from each room; the cross path is a through-wall approximation
    with no shared echo structure."""
    room_a = Room(dims=(4.5, 3.5, 2.7), absorption=0.22, max_order=12)
    room_b = Room(dims=(3.2, 2.8, 2.5), absorption=0.30, max_order=12)
    lap = laptop((2.0, 1.7, 0.75), facing_az_deg=180.0)
    ph = phone((1.6, 1.4, 0.75), speaker_az_deg=90.0)
    rirs = compute_split_rirs(room_a, lap, room_b, ph, attenuation_db=62.0,
                              lowpass_hz=2_500.0, seed=seed)
    return Trial(dev_a=lap, dev_b=ph, rirs=rirs, label="different_rooms",
                 snr_db=snr_db, agc=agc, seed=seed, beep_overrides=beep_overrides or {})


def remote_attacker(*, snr_db: float = 40.0, agc: bool = True, seed: int = 0,
                    relay_attenuation_db: float = 58.0, beep_overrides: dict | None = None) -> Trial:
    """Paper section V-D style. The attacker is far from the victim and relays the audio
    over a network/loudspeaker. Even a clean relay cannot reproduce the victim room's
    echo, so the cross path carries no matching reflections. Modeled as different rooms
    with a stronger (cleaner relay) but still echo-mismatched cross path."""
    room_a = Room(dims=(4.5, 3.5, 2.7), absorption=0.22, max_order=12)
    room_b = Room(dims=(5.0, 4.0, 3.0), absorption=0.18, max_order=12)
    lap = laptop((2.0, 1.7, 0.75), facing_az_deg=180.0)
    ph = phone((2.5, 2.0, 0.75), speaker_az_deg=90.0)
    rirs = compute_split_rirs(room_a, lap, room_b, ph, attenuation_db=relay_attenuation_db,
                              lowpass_hz=3_000.0, seed=seed + 100)
    return Trial(dev_a=lap, dev_b=ph, rirs=rirs, label="remote_attacker",
                 snr_db=snr_db, agc=agc, seed=seed, beep_overrides=beep_overrides or {})


def colocated_attacker(*, snr_db: float = 40.0, agc: bool = True, seed: int = 0,
                       beep_overrides: dict | None = None) -> Trial:
    """Paper section V-E style. An attacker device sits right next to the victim's laptop
    (so it shares the laptop's room and can hear those echoes) but the genuine partner
    phone is in a different room. The pair under test is (laptop, far phone); the shared
    laptop-side echoes don't help because the phone side is decorrelated."""
    room_a = Room(dims=(4.5, 3.5, 2.7), absorption=0.22, max_order=12)
    room_b = Room(dims=(3.0, 2.6, 2.4), absorption=0.28, max_order=12)
    lap = laptop((2.0, 1.7, 0.75), facing_az_deg=180.0)
    ph = phone((1.5, 1.3, 0.75), speaker_az_deg=90.0)
    rirs = compute_split_rirs(room_a, lap, room_b, ph, attenuation_db=52.0,
                              lowpass_hz=3_000.0, seed=seed + 200)
    return Trial(dev_a=lap, dev_b=ph, rirs=rirs, label="colocated_attacker",
                 snr_db=snr_db, agc=agc, seed=seed, beep_overrides=beep_overrides or {})


# --------------------------------------------------------------------------------------
# B3 alias-regression scenes (the bug, pinned forever)
# --------------------------------------------------------------------------------------
def adverse_alias(*, room: Room = DEFAULT_ROOM, snr_db: float = 45.0, seed: int = 0) -> Trial:
    """Adverse orientation (both devices point away from each other) with the laptop's
    cross path BA attenuated x0.01 and a record-start skew that pushes the partner toward
    the self grid — the exact conditions that produced the live self-alias. The fixed
    pipeline must EITHER align correctly (Δ error < 50 ms) OR reject with
    `cross_selection_self_aliased`; it must never ACCEPT via aliased selections."""
    cx, cy, cz = room.dims[0] / 2, room.dims[1] / 2, 0.75
    d = 0.30
    lap = laptop((cx - d / 2, cy, cz), facing_az_deg=180.0)     # mic aimed at the user
    ph = phone((cx + d / 2, cy, cz), speaker_az_deg=90.0,       # speaker fires away
               clock_offset_ms=345.0, output_latency_ms=155.0)  # skew+lat near the 500 collision
    rirs = compute_shared_room_rirs(room, lap, ph).scaled(BA=0.01)  # laptop barely hears phone
    return Trial(dev_a=lap, dev_b=ph, rirs=rirs, label="adverse_alias",
                 snr_db=snr_db, agc=False, seed=seed)


def partner_latch(*, room: Room = DEFAULT_ROOM, snr_db: float = 48.0, seed: int = 0) -> Trial:
    """The partner arrival lands INSIDE the pass-1 self window and is LOUDER than the
    device's own self loop (amp ratio up to 11x in the archive, §3). Amplitude cannot
    separate self from partner; only the joint sum identity can. Assert pass-1 still
    locks the TRUE self train (self_offset_ms ~ the true self latency, not the partner's).

    Realized by making device A (laptop) hear the phone strongly (favorable mic + BA
    boosted) while its own self loop AA is attenuated, so on A the partner is the louder
    in-window train."""
    cx, cy, cz = room.dims[0] / 2, room.dims[1] / 2, 0.75
    d = 0.30
    lap = laptop((cx - d / 2, cy, cz), facing_az_deg=0.0)   # mic aimed AT the phone
    # clock_offset places the phone's beep ~250 ms into device A's pass-1 self window
    # (co + output_latency ~ 850, verified in the diagnostic runner), where — with AA
    # attenuated and BA boosted — it is the LOUDER in-window train.
    ph = phone((cx + d / 2, cy, cz), speaker_az_deg=180.0,
               clock_offset_ms=665.0, output_latency_ms=185.0)
    rirs = compute_shared_room_rirs(room, lap, ph).scaled(AA=0.25, BA=4.0)  # partner >> self on A
    return Trial(dev_a=lap, dev_b=ph, rirs=rirs, label="partner_latch",
                 snr_db=snr_db, agc=False, seed=seed)


def late_android(*, room: Room = DEFAULT_ROOM, snr_db: float = 48.0, seed: int = 0) -> Trial:
    """Android playout latency 260 ms (> 230 ms, the OLD pass-1 window edge that caused
    the `ca3013a2` android mis-lock). Assert the widened −20/+400 ms window + train policy
    finds the true self train (self_offset_ms > 230) and still aligns."""
    cx, cy, cz = room.dims[0] / 2, room.dims[1] / 2, 0.75
    d = 0.30
    lap = laptop((cx - d / 2, cy, cz), facing_az_deg=0.0)
    ph = phone((cx + d / 2, cy, cz), speaker_az_deg=180.0,
               clock_offset_ms=40.0, output_latency_ms=260.0)  # late android
    rirs = compute_shared_room_rirs(room, lap, ph)
    return Trial(dev_a=lap, dev_b=ph, rirs=rirs, label="late_android",
                 snr_db=snr_db, agc=False, seed=seed)


def partner_in_self_tail(*, room: Room = DEFAULT_ROOM, snr_db: float = 48.0, seed: int = 0) -> Trial:
    """Record-start skew tuned so the partner arrives < 20 ms after the self peak on one
    device (min observed gap 17.1 ms, §3; nothing prevents ~0). Assert the small-gap mask
    trim fires (`cross_partner_in_self_tail` or `unassigned_train_in_self_tail`) and no
    aliased ACCEPT results."""
    cx, cy, cz = room.dims[0] / 2, room.dims[1] / 2, 0.75
    d = 0.30
    lap = laptop((cx - d / 2, cy, cz), facing_az_deg=0.0)
    # clock_offset chosen (verified in the diagnostic runner) so the phone's beep lands
    # ~10 ms after the laptop's own beep on device A's fold.
    ph = phone((cx + d / 2, cy, cz), speaker_az_deg=180.0,
               clock_offset_ms=514.0, output_latency_ms=90.0)
    rirs = compute_shared_room_rirs(room, lap, ph)
    return Trial(dev_a=lap, dev_b=ph, rirs=rirs, label="partner_in_self_tail",
                 snr_db=snr_db, agc=False, seed=seed)


def deaf_laptop(*, room: Room = DEFAULT_ROOM, snr_db: float = 48.0, seed: int = 0) -> Trial:
    """One-sided deafness: the laptop cannot hear the phone at all (BA x0.001), the real
    MacBook-beamforming failure the alias used to hide. Assert a DEAF-CLASS rejection
    (partner_inaudible / cross_offset_sum_inconsistent / cross_offset_ambiguous /
    self_train_ambiguous — the literal `partner_inaudible` reason rarely fires because
    leakage keeps the masked sweep above floor, per phase0-rescore), never `...aliased`,
    never a crash."""
    cx, cy, cz = room.dims[0] / 2, room.dims[1] / 2, 0.75
    d = 0.30
    lap = laptop((cx - d / 2, cy, cz), facing_az_deg=0.0)   # clean self loop, but deaf to phone
    ph = phone((cx + d / 2, cy, cz), speaker_az_deg=180.0)
    rirs = compute_shared_room_rirs(room, lap, ph).scaled(BA=0.001)
    return Trial(dev_a=lap, dev_b=ph, rirs=rirs, label="deaf_laptop",
                 snr_db=snr_db, agc=False, seed=seed)


def aec_on(*, room: Room = DEFAULT_ROOM, snr_db: float = 48.0, seed: int = 0) -> Trial:
    """Browser/OS echo cancellation active on BOTH devices (fix-plan B4.1 / A2.7). Two
    prongs, both asserted by the smoke test:
      * acoustic fingerprint — the AEC model collapses each device's self echo period, so
        `possible_aec_suppression` must warn (this is what catches OS-level AEC that
        getSettings() cannot see);
      * hard guard — with `echoCancellation:true` injected into the granted track settings
        (what the browser uploads when AEC is on), capture must be REJECTED with
        `echo_cancellation_enabled`.
    A favorable same-room geometry is used so the ONLY reason to reject is the AEC — if the
    guard were removed the pair would otherwise be a clean capture."""
    cx, cy, cz = room.dims[0] / 2, room.dims[1] / 2, 0.75
    d = 0.30
    lap = laptop((cx - d / 2, cy, cz), facing_az_deg=0.0)
    ph = phone((cx + d / 2, cy, cz), speaker_az_deg=180.0)
    lap.aec = True
    ph.aec = True
    rirs = compute_shared_room_rirs(room, lap, ph)
    return Trial(dev_a=lap, dev_b=ph, rirs=rirs, label="aec_on",
                 snr_db=snr_db, agc=False, seed=seed,
                 granted_settings_a={"echoCancellation": True, "noiseSuppression": False,
                                     "autoGainControl": False, "voiceIsolation": False},
                 granted_settings_b={"echoCancellation": True, "noiseSuppression": False,
                                     "autoGainControl": False, "voiceIsolation": False})


def colliding_clocks(*, room: Room = DEFAULT_ROOM, snr_db: float = 48.0, seed: int = 0) -> Trial:
    """The degenerate collision that contaminated the sim before B1.1: the phone's
    record-start skew + playout latency put its beeps ON the laptop's own beep grid
    (gap ≈ 0), so self and partner are indistinguishable up to phase. (The historical
    default was clock_offset 320 + output_latency 180 = 500 ms against the old 30 ms
    laptop latency.) With the repaired 90 ms laptop latency an on-peak collision needs the
    partner's self-grid gap `(500 + skew + lat_B - lat_A) mod 1000` to vanish, i.e.
    skew + lat_B ≈ lat_A - 500 ≡ 590 ms (mod 1000); clock_offset 410 + output_latency 180
    = 590 lands the phone's beep directly on the laptop's own peak (measured gap ~0.5 ms,
    versus the +11 ms the earlier 601 ms draw actually produced). Kept on PURPOSE as the
    extreme. Assert no aliased ACCEPT survives; the trial is withheld with a sensible
    reason."""
    cx, cy, cz = room.dims[0] / 2, room.dims[1] / 2, 0.75
    d = 0.30
    lap = laptop((cx - d / 2, cy, cz), facing_az_deg=0.0)
    ph = phone((cx + d / 2, cy, cz), speaker_az_deg=180.0,
               clock_offset_ms=410.0, output_latency_ms=180.0)  # partner lands on the self grid (gap ~ 0)
    rirs = compute_shared_room_rirs(room, lap, ph)
    return Trial(dev_a=lap, dev_b=ph, rirs=rirs, label="colliding_clocks",
                 snr_db=snr_db, agc=False, seed=seed)


# --------------------------------------------------------------------------------------
# Workstream E attack scenes: relay (man-in-the-middle) + replay (fix-plan §7 phase-4)
# --------------------------------------------------------------------------------------
# The relay attacker (paper §V-D) puts a microphone in each victim's OWN room and a speaker
# beside the OTHER victim, forwarding audio electronically. The two devices are genuinely in
# separate rooms; the ONLY coupling is the attacker's relay. scene.compute_relay_rirs builds
# the composite cross path (capture-in-victim-room -> electronic delay+coloration -> replay-
# into-other-room). The paper's security claim is that echo signatures bind to the shared
# acoustic environment, so a relayed trial must not verify. See the module docstring and the
# per-scene findings below for where that claim holds and where the current pipeline leaks.
#
# Relay attacker room + transducer geometry (shared by every relay preset). Two separate
# rooms; the attacker's mic sits ~0.25 m from each victim (capturing its emissions with that
# victim's own room signature) and the attacker's speaker ~0.25 m on the other side (replaying
# the forwarded audio into that room).
_RELAY_ROOM_A = Room(dims=(4.5, 3.5, 2.7), absorption=0.22, max_order=12)
_RELAY_ROOM_B = Room(dims=(5.0, 4.0, 3.0), absorption=0.18, max_order=12)
_RELAY_LAP_POS = (2.0, 1.7, 0.75)
_RELAY_PH_POS = (2.5, 2.0, 0.75)
# Attacker transducers, per room (mic captures the local victim; speaker replays into it).
_RELAY_ATT_MIC_A = (2.25, 1.7, 0.75)
_RELAY_ATT_SPK_A = (1.75, 1.7, 0.75)
_RELAY_ATT_MIC_B = (2.75, 2.0, 0.75)
_RELAY_ATT_SPK_B = (2.25, 2.0, 0.75)
# A high-fidelity relay's mild passband coloration (the attacker's gear is otherwise flat and
# broadband across the 6-12 kHz analysis band — the strong-attacker assumption).
_RELAY_HIFI_RESONANCES = ((7_000.0, 5.0, 2.0), (9_500.0, -4.0, 2.0))


def relay_attacker(*, latency_ms: float = 20.0, relay_gain_db: float = 0.0,
                   lowcut_hz: float = 150.0, highcut_hz: float = 16_000.0,
                   resonances: tuple[tuple[float, float, float], ...] = _RELAY_HIFI_RESONANCES,
                   external_mic: bool = False, snr_db: float = 48.0, seed: int = 0) -> Trial:
    """General relay (MiM) scene. `latency_ms` is the attacker's ELECTRONIC forwarding delay
    (5-50 ms is the modeled sweep); `relay_gain_db` is how hard the attacker drives the
    replayed audio; a narrow `lowcut/highcut` + `resonances` models cheap/codec-limited relay
    gear. The two victims are in separate rooms (_RELAY_ROOM_A/B); only the attacker couples
    them. Used directly by the latency/gain sweep and by the pinned presets below.

    `external_mic` models the T3 hardware tier: a USB microphone on the laptop that BYPASSES the
    MacBook's beamforming — omnidirectional (mic_dir=None, reusing _make_directivity's omni path).
    This is the tier the campaign steers toward to win a GO, so relay robustness AT T3 is the open
    question relay_t3() answers. The relay_transparent docstring hypothesized 'a stronger laptop
    side / tier T3 could lift the pair over 0.78'; the swept T3 result REFUTES that in this model
    (see relay_t3): the omni capsule hears the loud relayed cross content symmetrically, which
    collapses the laptop's own self-loop period recovery rather than lifting c_a, so a T3 relay is
    withheld (capture-invalid) instead of verifying. (A mic_gain change would be inert here: uniform
    per-recording scaling is Pearson-invariant AND does not move period recovery — verified — so
    only the DIRECTIVITY is changed, keeping the model honest about what T3 does.)"""
    lap = laptop(_RELAY_LAP_POS, facing_az_deg=0.0)
    if external_mic:
        lap.mic_dir = None      # omni external USB mic — bypasses beamforming (T3)
    ph = phone(_RELAY_PH_POS, speaker_az_deg=180.0)
    rirs = compute_relay_rirs(
        _RELAY_ROOM_A, lap, _RELAY_ROOM_B, ph,
        attacker_mic_a_pos=_RELAY_ATT_MIC_A, attacker_spk_a_pos=_RELAY_ATT_SPK_A,
        attacker_mic_b_pos=_RELAY_ATT_MIC_B, attacker_spk_b_pos=_RELAY_ATT_SPK_B,
        latency_ms=latency_ms, relay_gain_db=relay_gain_db,
        lowcut_hz=lowcut_hz, highcut_hz=highcut_hz, resonances=resonances, seed=seed)
    return Trial(dev_a=lap, dev_b=ph, rirs=rirs, label=f"relay_{latency_ms:.0f}ms_{relay_gain_db:.0f}dB",
                 snr_db=snr_db, agc=False, seed=seed)


def relay_transparent(*, snr_db: float = 48.0, seed: int = 0) -> Trial:
    """The STRONGEST relay: a perfectly transparent (flat, broadband, no coloration), low-
    latency (5 ms) forwarder at natural gain — the closest an attacker gets. Across the full
    latency/gain/coloration sweep NO relay achieves a proximity ACCEPT, but this configuration
    is the closest call and it exposes the real gap: it stays CAPTURE_VALID (no anti-relay /
    freshness guard fires on a clean relay — the attacker's mic sits in each victim's own room,
    so the forwarded audio inherits that victim's speaker+room spectral envelope and c_b stays
    ~0.8) and is stopped ONLY by the sub-threshold proximity SCORE (~0.69 < 0.78). That margin
    is thin and rests on the laptop's beamforming weakness pulling c_a down (~0.58); a stronger
    laptop side (external mic / tier T3) could lift the pair over 0.78. The contract asserts
    the security property (no ACCEPT) and DOCUMENTS the capture_valid gap + sub-threshold score
    (contract_relay_transparent) — see docs/replica-findings.md and the sweep in the report."""
    return relay_attacker(latency_ms=5.0, relay_gain_db=0.0, resonances=(), snr_db=snr_db, seed=seed)


def relay_loud(*, snr_db: float = 48.0, seed: int = 0) -> Trial:
    """A transparent relay at ~20 ms driven hard (+20 dB). Driving the replayed partner far
    above the victim's own self loop, combined with the 20 ms electronic round trip, breaks the
    joint train assignment (the cross offset falls back to the masked sweep) and the round trip
    fails the sum identity: this scene is withheld with `cross_offset_sum_inconsistent`.
    Characterizes the timing/round-trip consistency guard — the one that bites a relay whose
    latency it can measure — and pins it so a regression that loosens it is caught
    (contract_relay_loud)."""
    return relay_attacker(latency_ms=20.0, relay_gain_db=20.0, resonances=(), snr_db=snr_db, seed=seed)


def relay_t3(*, snr_db: float = 48.0, seed: int = 0) -> Trial:
    """T3-tier relay: the STRONGEST relay (transparent, flat, 5 ms, natural gain) against a laptop
    fitted with an external omnidirectional USB mic that BYPASSES the MacBook's beamforming — the
    tier the campaign steers toward to win a GO. OPEN-SCIENCE FINDING (documents current behavior):
    across the full latency x gain x coloration sweep NO T3 parameterization reaches a proximity
    ACCEPT (observed max score ~0.437 at hifi/5 ms/+20 dB, margin ~-0.34 to the 0.78 threshold; this
    transparent preset scores ~0.392). The relay_transparent hypothesis that 'a stronger laptop side
    / T3 could lift the pair over 0.78' is REFUTED in this model: the omni mic hears the loud relayed
    cross content symmetrically, which COLLAPSES the laptop's self-loop period recovery
    (AA_low_period_recovery, c_a -> 0). So a T3 relay is WITHHELD as capture-invalid — a STRONGER kill
    than the baseline beamformed relay_transparent, which stays capture_valid and is stopped only by
    the sub-0.78 score. relay does NOT defeat verification at T3 with these params. contract_relay_t3
    pins this (no ACCEPT, score below threshold, withheld); a regression that lets a T3 relay verify —
    or that hardens the self loop so it becomes capture_valid — flips the contract and forces a re-pin
    plus a threat-model update. Reported in the paper-reproduction conclusions either way."""
    return relay_attacker(latency_ms=5.0, relay_gain_db=0.0, resonances=(), external_mic=True,
                          snr_db=snr_db, seed=seed)


def replay_exposure(*, beeps_per_device: int = 12, genuine_distance_m: float = 0.30,
                    snr_db: float = 48.0, seed_session_1: int = 1001,
                    seed_session_2: int = 2002) -> dict:
    """REPLAY attack demonstration (paper threat model; docs/replica-findings.md §4.4).

    This is NOT a physics Trial — it is a protocol-level demonstration, because the replay
    exposure is a property of the challenge, not of any room geometry. Per the Map agent's
    freshness finding and the challenge_generator docstring, the emitted chirp is a FIXED
    template: make_beep_spec's per-trial random seed is retained only as a log-side id, and
    synthesize_beep ignores it, so every session emits a BYTE-IDENTICAL challenge on a fixed
    schedule. There is therefore no freshness a verifier could check.

    We demonstrate the consequence end-to-end: render a genuine co-located session under
    session 1's challenge, then have the verifier score those exact recordings under a LATER
    session 2's challenge (a different seed). Because the two challenges are byte-identical,
    the stale recording is accepted and scored IDENTICALLY — a recording captured in one
    session verifies in another. Returns a dict of facts for contract_replay_exposure, which
    DOCUMENTS this gap rather than asserting a rejection the protocol cannot deliver."""
    schedule = [b.to_dict() for b in build_schedule(beeps_per_device=beeps_per_device)]
    schedule_again = [b.to_dict() for b in build_schedule(beeps_per_device=beeps_per_device)]
    spec_1 = make_beep_spec(seed=seed_session_1)
    spec_2 = make_beep_spec(seed=seed_session_2)
    chirp_identical = synthesize_beep(spec_1).tobytes() == synthesize_beep(spec_2).tobytes()
    schedule_identical = schedule == schedule_again

    # Genuine co-located session, captured under session 1's challenge.
    room = DEFAULT_ROOM
    cx, cy, cz = room.dims[0] / 2, room.dims[1] / 2, 0.75
    d = genuine_distance_m
    lap = laptop((cx - d / 2, cy, cz), facing_az_deg=0.0)
    ph = phone((cx + d / 2, cy, cz), speaker_az_deg=180.0)
    rirs = compute_shared_room_rirs(room, lap, ph)
    wav_a = render_recording(lap, ph, rirs, schedule, spec_1, snr_db=snr_db, agc=False, seed=seed_session_1)
    wav_b = render_recording(ph, lap, rirs, schedule, spec_1, snr_db=snr_db, agc=False, seed=seed_session_1)

    genuine = score_recordings(wav_a, wav_b, schedule, spec_1)
    # The attacker replays the SAME recordings into a later session; the verifier scores them
    # under session 2's (fresh-seed) challenge. No re-render — the bytes are the stale capture.
    replay = score_recordings(wav_a, wav_b, schedule, spec_2)

    def _facts(scored: dict) -> dict:
        return {"score": scored["score"].score, "verdict": scored["score"].verdict,
                "capture_valid": scored["validity"].capture_valid,
                "failure_reasons": scored["validity"].failure_reasons}

    g, r = _facts(genuine), _facts(replay)
    return {
        "chirp_identical_across_seeds": chirp_identical,
        "schedule_seed_independent": schedule_identical,
        "seed_session_1": seed_session_1,
        "seed_session_2": seed_session_2,
        "genuine": g,
        "replay": r,
        "replay_matches_genuine": (abs(g["score"] - r["score"]) < 1e-9
                                   and g["verdict"] == r["verdict"]
                                   and g["capture_valid"] == r["capture_valid"]),
    }
