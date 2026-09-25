# A0 findings: the "+128 ms self-replica" is the partner's beep

Date: 2026-07-07. Deliverable for [fix-plan.md](fix-plan.md) §A0. Adjudicated from three
independent hypothesis investigations (acoustic/OS event; capture artifact; pass-1
mis-identification), a full-archive survey (24 trials × 2 devices), and an independent
verification run by the adjudicator (script:
`scratchpad/adjudicate/verify.py` under the session scratchpad; all numbers below
reproduced from the archived WAVs + `data/logs/trials.jsonl`).

## 1. Mechanism (decided)

**There is no self-replica.** The discrete event ~128 ms after each detected self beep in
`ca3013a2` is the **partner device's beep**, arriving through the air. It is phase-locked
to the self grid because the two schedules are **degenerate**: both devices emit with the
same 1000 ms period at a 500 ms interleave, so the partner's emissions land at a
per-trial-constant lag on the *self* grid (mod 1000 ms). The apparent lag is

```
gap = (±500 + record_start_skew + lat_partner − lat_self + air_transit) mod 1000
```

— a per-trial constant (record-start skew is re-established every trial), which is why
the "replica lag" is rock-stable within a trial (per-beep σ 0.1–1.7 ms) yet varies
17–177 ms across trials of the *same* device pair.

Concretely, on `ca3013a2`:

| recording | event 1 | event 2 | assignment |
|---|---|---|---|
| Mac (387d0a91) | 82.0 ms, drift −7.6 µs/beep, amp 8.3 | 211.5 ms, drift −22.4 µs/beep, amp 19.9 | e1 = **Mac's own playout**; e2 = **phone's beep** |
| Android (a1cfc16c) | 114.7 ms, drift +5.8 µs/beep, amp 26.8 | 243.7 ms, drift −3.0 µs/beep, amp 43.1 | e1 = **Mac's beep**; e2 = **phone's own playout** |

So on the Mac, pass-1 found the true self peak and the "+129.5 ms replica" is the phone.
On the Android, pass-1's detected "self" event (114.7 ms — the number the fix-plan cites
as "phone self_offset ≈ 115 ms") **is actually the Mac's beep**; the phone's true playout
latency is **243.7 ms**, right at the edge of the −20/+230 ms pass-1 window. The phone's
"self latency" in the fix-plan §0/§1.2 arithmetic was wrong; the alias arithmetic still
works out because the events themselves are where they are.

Two compatible sub-conclusions survive from the refuted hypotheses: the event **is** a
real acoustic arrival (full 6–12 kHz chirp structure: STFT ridge slope 280–301 Hz/ms vs
300 expected, up-vs-down-chirp matched-filter discrimination 3.5–9.7, acoustically
colored spectrum — not a filter artifact or digital copy), and for the Android in
`ca3013a2` it is also that device's **true main playout** (the pass-1-mis-identification
framing was right about *which* event is the phone's playout, wrong that a "replica"
exists at all).

## 2. Discriminating evidence

Ranked by decisiveness; all sample-level, all reproducible offline.

1. **Sum rule (clock-free, mod-1000 identity).** If both devices' second events were
   self-replicas, the cross-device equality of the gap (below) is a miracle; if both were
   partner beeps, `gap_A + gap_B ≡ 0 (mod 1000)`. Observed sums: 258.60, 233.05, 201.28,
   131.98, 34.44 ms (ca3013a2, bbcb9f47, 0b8127ea, b1f00218, 1703c871) — refuted. The
   **mixed** assignment (each device: one train self, one train partner) predicts
   `gap_A ≡ gap_B (mod 1000)` up to air transit; residuals 0.12–0.48 ms, i.e. 2–3 orders
   of magnitude better. Independently re-verified by the adjudicator on 4 trials.
2. **The gap difference is round-trip air time.** `gap_A − gap_B = T_AB + T_BA` (two air
   transits) under the mixed assignment: measured +0.13…+0.48 ms for touch/baseline
   trials, +1.98/+3.19 ms for 30 cm trials, positive in 16/17 clean pairs. A software or
   device-local event cannot depend on device placement (this also independently refuted
   the capture-artifact hypothesis). The survey's reading of this asymmetry as "a single
   re-emitting source at the android" is superseded: the sign is positive by geometry
   regardless of platform.
3. **Clock-domain signature.** A self playout is generated and captured by the same
   audio clock ⇒ ~zero drift vs its own schedule; a partner arrival drifts at the
   inter-device clock rate, with **opposite signs in the two recordings**. Measured
   (e45a9b51): Mac's drifting train −18.4 µs/beep, Android's drifting train
   +18.1 µs/beep (≈18 ppm, equal magnitude, opposite sign). On `ca3013a2` the Android's
   *243.7 ms* event is the drift-locked one (−3 µs/beep; the earlier investigation
   measured its absolute grid lock at σ = 33 µs) while the 114.7 ms event drifts — the
   "replica" is the phone's own clock-locked playout.
4. **Cross-offset identity.** `Δ_A + Δ_B = lat_A + lat_B − 1000 (mod 1000)` holds to
   0.3–0.5 ms once events are assigned this way (ca3013a2: −288.5 + −385.3 = −673.8 vs
   82.0 + 243.7 − 1000 = −674.3). Corollary: **the Mac's logged −290 ms offset in
   `ca3013a2` was the TRUE cross offset**, not an alias (the phone's beeps really sit at
   −288.5 ms relative to their schedule in the Mac recording). Only the phone's +740 was
   an alias — onto the phone's own true playout (+500 + 243.7 ≈ 740 at 10 ms sweep
   quantization). The Mac's 20/20 self-identical pass-3 selections happened *despite a
   correct offset*, because the ±200 ms pass-3 window around −290 contains the Mac's own
   beep earlier in time than the phone's, and the first-above-threshold τ1 policy picked
   it. Fix-plan §1.2's "two alias flavors" needs this re-interpretation: the "replica
   flavor" is a **self-main-peak latch where the true latency was mis-measured**, and
   `ca3013a2` was a *single-sided* alias, not double.
5. **Different loudspeakers.** Within-recording log-spectrum correlation between the two
   trains (0.685–0.987) is systematically below same-event split-half baselines
   (0.98–0.998); raw-waveform NCC between the trains is −0.66…+0.50 (sign-flipping,
   acoustic phase) — two different physical sources, never a copy.
6. **Refuted: capture-graph artifact** (high confidence). All 48 WAV headers and all
   granted track settings are 48000 Hz; file lengths are exact multiples of the 4096
   ScriptProcessor chunk; zero duplicated int16 blocks at 1/2/3-chunk gaps in 16 files
   scanned; lag never matches 4096/6144/8192 samples (misses 6144 by 51–84 samples,
   5–8× the per-beep jitter); `app.js` copies each capture buffer
   (`chunks.push(new Float32Array(input))`). The fix-plan's 44.1 kHz header-mismatch
   hypothesis is dead for this archive: no time-stretch on any self grid
   (a 44.1-as-48 error would give +88 ms/beep; observed < 0.05 ms/beep). Note the
   canonicalize-path risk remains a valid *general* concern for future captures.
7. **Refuted: OS/driver second playout ("real self-replica")** (the H1 verdict). Every
   observation H1 made is real, but the attribution fails: identical lag on two
   physically different devices per session (its own flagged open question) is exactly
   the degeneracy; the "different clock domains of the same pipeline" it measured are
   the two devices' clocks; `app.js` schedules each beep exactly once. The absence of a
   second-order replica at +2·lag (< 0.1% of the event, everywhere — also confirmed
   archive-wide, < 0.005 of main) additionally kills the survey's mic→speaker
   re-emission conjecture: a feedback path with observed gain up to 11× would ring.

## 3. Parameters (survey, 24 trials × 2 devices, reinterpreted)

All "replica" numbers below are now **partner-arrival** parameters.

- **Presence:** discrete partner train (amp ≥ 0.2 of the detected self peak, SNR ≥ 50 in
  the self-anchored fold) in 39/48 recordings, 21/24 trials. Absent = **partner
  inaudible**: `b933225d` (both sides), `d6415a40` (android side), plus the Mac side of
  4/5 14–15 kHz trials (probe ratio ≤ 0.0025) — consistent with fix-plan §A2.6/§E's
  expected deafness class, and these are the clean control trials for any fix.
- **Apparent lag (gap on the self grid):** per-trial constant, range **15–177 ms**
  observed (17.1, 22.5, 36.7, 66.0, 72.2, 100.5–100.7, 106.3, 111.5, 116.6, 129.3,
  130.7, 139–141.5, 146.3–146.7, 157.1, 169.7–177 across trials). "~128 ms" is merely
  `ca3013a2`'s draw. Same session pair produced 17/100/129/137/165 ms in five trials.
  Nothing prevents the gap from being ~0 (partner on top of the self peak) in a future
  trial — the observed range is luck, not a bound.
- **Within-trial stability:** per-beep lag σ 0.10–0.25 ms (android-side recordings),
  0.25–1.7 ms (mac-side), 2.4–4.2 ms in 14–15 kHz trials; drift ≤ 0.3 ms/beep
  (inter-device clock, ≈5–25 ppm). Android 14–15 kHz lags quantize in ~128-sample
  (2.67 ms) steps — WebAudio render-quantum scheduling jitter on the phone's playout.
- **Amplitude ratio (partner/self-loop):** 0.1–11 across recordings; median 0.62
  (mac recordings) / 0.97 (android recordings); partner ≥ self in 18/43. The partner is
  often *louder* than the device's own near-field loop (why — see §6.1); consequence:
  **no amplitude threshold can separate self from partner**, in either direction.
- **True playout latencies** (after correct assignment): Mac 77–123 ms (per-beep σ down
  to 0–0.22 ms); Android **95–306 ms**, varying 142–292 ms across sessions on the same
  phone. At least 10 android recordings exceed the current +230 ms pass-1 pad; the
  survey's per-recording "self_off" column is pass-1-style and hence **unreliable for
  androids** (e.g. `ca3013a2` android "self_off 114.67" is the Mac's beep).
- **Pass-1 partner-capture cases** (detected "self" is actually the partner, or the
  argmax lands on it): confirmed on `ca3013a2` (android; and 5/20 android beeps had τ1 on
  the partner event), and mac-side argmax cases `ffeb620f` (223.5 = 92.7+130.8),
  `bbcb9f47` (209.8), `0b8127ea` (192.9), `b1f00218` (157.1).
- **Genuine self acoustic structure** (this *is* maskable self footprint): room/chassis
  echo tail after every emission at +4.6–6.3 ms (0.15–0.5 of peak), +9–13 ms (0.03–0.3),
  +21–23 ms (≤ 0.26), decaying below 0.01 by +60 ms; and small ~30–37 ms mac chassis
  reflections in 14–15 kHz trials (ratio 0.05–0.3, no chirp discrimination). The
  borderline `d4624efe` ~22 ms secondary (ratio 0.18 both devices) may be echo rather
  than partner — unresolved (§6).
- **Band dependence:** 6–12 kHz — bidirectional audibility in 15/16 non-control trials.
  14–15 kHz — phone's beep audible on the mac (appears at negative self-grid lag,
  −149…−170 ms, ratio up to 0.96), mac's beep reaches the phone in ~3/5 trials; mac-side
  partner train otherwise absent. No sample-rate dependence (all true 48 kHz).

## 4. Decisions

### 4.1 A1 mask design (revises fix-plan §A1.2–A1.4)

**The central design assumption of A1.2 as written — "find all envelope peaks
phase-coherent with the self grid and mask them" — is unsafe and must change.** Because
of the schedule degeneracy, the partner's beeps are *also* perfectly self-grid-coherent;
a coherence-keyed mask erases the only signal the pipeline needs. Masking must cover
**self-attributed events only**, and self-attribution requires the joint two-recording
assignment:

1. **Detect trains, not peaks:** per recording, fold the matched-filter envelope mod
   1000 ms anchored on the device's own schedule (window −20…+420 ms per slot, or the
   full fold); every coherent peak train with per-beep lag σ < 2 ms is an event train.
   Expect 1–2 chirp trains + echo-tail bumps.
2. **Assign self vs partner jointly across both recordings** (this replaces/absorbs
   fix-plan A1.5's joint selection): choose the labeling that satisfies
   (i) the sum identity `Δ_A + Δ_B ≡ lat_A + lat_B − 1000 (mod 1000)` within ~5 ms
   (measured residuals ≤ 0.5 ms; use 5 ms to absorb sweep/fold quantization — far
   tighter than the ±100 ms in fix-plan A1.5, which should be tightened accordingly);
   (ii) drift: the self train has ~zero slope vs its own schedule, partner trains have
   opposite-sign slopes across the two recordings (discriminates at ≥ 10 ppm; treat as
   supporting evidence below that);
   (iii) latency priors: mac 60–150 ms, android 80–350 ms (warn outside, don't hard-gate).
   Degenerate single-train recordings (partner inaudible) assign trivially.
3. **Mask geometry:** for each self-train per-beep position τ, mask
   `[τ − 10 ms, τ + beep_len + 40 ms]` (echo tail < 5% by +36 ms, < 1% by +60 ms; the
   +40 ms pad is the default constant, homed in `pipeline_constants.py` per fix-plan
   D3.1). Add the measured 14–15 kHz mac chassis reflection (~30–37 ms) — the default pad
   already covers it. **No 128 ms notch. No fixed-lag replica component. Never mask the
   partner train.**
4. **Small-gap guard:** the partner can sit inside the self mask (observed minimum gap
   17.1 ms, `1703c871`; nothing prevents ~0). If the assigned partner train falls within
   a self mask window, trim the mask to `gap − 5 ms` after the self peak and flag the
   trial `cross_partner_in_self_tail` (warn; A2 spectral guards then carry the load).
5. **Pass-3 must use the same assignment:** the `ca3013a2` laptop failure was pass-3
   re-latching the *self* beep inside a ±200 ms window around a **correct** offset.
   Masked per-beep selection + "strongest unmasked candidate" (fix-plan A1.4) stands,
   with the mask defined as above.
6. **A2 guard re-interpretation:** A2.1 (self-overlap) still fires on `ca3013a2` laptop
   20/20 — keep it. A2.2's "danger lag set" = {0} plus nothing: there are no replica
   lags; the dangerous offsets are exactly `±500 + self_lat` (mod 1000) for the
   *correctly assigned* self latency. A2.5's sum check is stronger than fix-plan §1.2
   believed — with correctly measured latencies it catches *single*-sided self-latch
   aliases (ca3013a2 phone: observed sum 451.5 vs expected 325.7 mod 1000 → 126 ms
   violation), and the "double replica alias ⇒ +2×128 ms" category does not exist.
   Acceptance criterion §8 bullet 1 should expect: laptop channel fixed by pass-3
   masking (its Δ was true), phone channel rejected/corrected via the sum identity.

### 4.2 Pass-1 first-candidate policy and self window (must change)

- **Window: −20/+230 ms → −20/+400 ms.** True android playout latency reached 243.7 ms
  (at the current edge — the direct cause of the `ca3013a2` android mis-lock) and 306 ms
  elsewhere; +400 ms covers the observed range with margin. Cost: the window now
  virtually always contains the partner's arrival too — which it already did; the point
  is to stop *excluding the true self peak* while the policy below handles the ambiguity.
- **Policy: neither "first above 0.30×local-max" (current, alignment.py ~148) nor
  "strongest" is correct** — the partner arrival can be both earlier *and* stronger
  (amp ratio up to 11×). Replace per-beep picking with **train-level selection**:
  cluster candidates across the ~20 beeps by lag mod 1000, then pick the *self* train by
  the §4.1.2 joint assignment; per-beep τ1 anchors to its train (median lag ± small
  per-beep refinement within ±3 ms). Per-beep coherence with the train (σ < 1.5 ms)
  replaces the `chirp_peak_value ≥ 1.0` absolute gate as the lock criterion (also
  serves fix-plan D3.2's de-absolutization).
- `self_offset_ms` then becomes the true playout latency and feeds A2.5/A3.1 correctly;
  today it silently reports the partner's arrival on affected android recordings, which
  would poison A3's prior if built on the current pass-1.

### 4.3 Simulation knob (fix-plan B4.2) — re-specified

**Do not implement a self-replica injection knob; the mechanism doesn't exist.** The
sim's existing two-device machinery already produces the phenomenon *structurally* —
which is why the phone preset with `clock_offset + output_latency = 500` collided
schedules (fix-plan B1.1): that *is* this bug at gap = 0. B4.2 becomes "cover the
measured phenomenology of the schedule degeneracy":

- **Playout latency** per device per trial: mac ~U(77, 123) ms; android ~U(95, 310) ms,
  re-drawn every trial (same physical phone measured 142–292 ms across sessions).
- **Record-start skew** per trial such that the partner's apparent self-grid gap
  `(500 + skew + lat_B − lat_A + air) mod 1000` sweeps 0–1000 ms uniformly — including
  the < 20 ms and ≈ 0 collision cases never observed but possible.
- **Clocks:** relative rate 5–25 ppm (opposite-sign drift in the two renders); per-beep
  playout jitter σ 0.1–0.5 ms; android option: quantize playout starts to 128-sample
  render quanta (2.67 ms — reproduces the 14–15 kHz jitter).
- **Cross amplitude:** partner/self-loop ratio log-uniform over [0.1, 11] (must allow
  > 1); per-side inaudibility probability ~20%; 14–15 kHz mode: mac-side partner train
  absent, phone-side present in ~60%.
- **Echo tails** attached to *every* emission (+5–6 ms @ 0.15–0.5, +10–13 ms @ 0.03–0.3,
  +21–23 ms @ ≤ 0.26, < 0.01 by +60 ms); no 2×-lag repeats anywhere.
- **B3 `replica_alias()` scenario → rename/re-scope** to the real failure modes:
  (i) `partner_latch()`: partner arrival inside the pass-1 window and louder than self
  (assert pass-1 still finds the true self train); (ii) `late_android()`: self latency
  > 230 ms (assert window/policy fix); (iii) `partner_in_self_tail()`: gap < 20 ms
  (assert the trim + flag); (iv) keep `colliding_clocks()` (gap ≈ 0) as the extreme.

### 4.4 Root-cause note beyond A0 (recommendation, not required for Phase 0)

The degeneracy is a **protocol** property: with equal 1000 ms periods, self and partner
grids are indistinguishable up to phase, and every grid-keyed technique (masking,
folding, sweep scoring) inherits the ambiguity. The joint assignment (§4.1.2) resolves
it *post hoc* on existing recordings; a client-side fix — per-beep pseudorandom offset
jitter (±tens of ms, known to both ends via the seed) or coprime per-device periods —
removes it *structurally* and would make self/partner separation trivial. Worth
scheduling alongside A3's client changes (fix-plan §2/A3); it also invalidates the
replay value of the fixed grid, which the paper's threat model cares about.

## 5. What this changes in the fix-plan, at a glance

- §0/§1.2: "self-replica" terminology and the "±500 + self_latency + 128" arithmetic —
  the +128 term is the partner; `ca3013a2` phone "self_offset 115" is the Mac's beep and
  the true phone latency is 243.7 ms; laptop −290 was the true offset; §1.2's
  "double replica alias" category is empty; the antisymmetry check is *stronger* than
  stated (catches the actually-observed single-sided flavor).
- A1.2: coherence-keyed self-structure mask replaced by assignment-keyed self mask
  (§4.1); A1.5's sum tolerance tightens from ±100 ms to ~±5 ms.
- A2.2: danger-lag set is {0} at the corrected self latency; no replica lags exist.
- §8 acceptance bullet 4 ("sim reproduces the replica via a knob") → sim covers the
  degeneracy phenomenology per §4.3; the mechanism is already structural in the sim.
- Good news for §E (hardware reality): partner audibility at 6–12 kHz is far better than
  the "10–1000× weaker" estimate in §1.1 — partner arrivals are *comparable to or louder
  than* the self loop in ~40% of recordings. The deafness narrative mainly holds for
  14–15 kHz mac-side and specific sessions (`b933225d`, `d6415a40`).

## 6. Open uncertainties (do not overclaim)

1. **Why the partner arrival often exceeds the device's own near-field loop** (up to
   11×). Granted track settings show `echoCancellation/noiseSuppression/autoGainControl/
   voiceIsolation = false` in all 144 device-trial records, so browser-level AEC is not
   the (reported) cause; OS-level own-speaker suppression (macOS voice processing,
   beamforming nulls toward own speakers) is the leading suspect but unverified — the
   fix-plan A2.7 acoustic fingerprint remains worthwhile.
2. **14–15 kHz trials are only partially assigned.** The mac-side negative-lag trains
   (−149…−170 ms) are consistent with the phone's playout position on the fold, and the
   phone-side 146–177 ms trains with high jitter + 128-sample quantization are presumed
   the phone's own playout — but the sum rule was not directly verified in this band
   (weak/one-sided audibility makes both trains hard to measure on one device).
3. **Direct sum-rule verification covers 6 trials** (5 from the investigation + 4 by the
   adjudicator, overlapping). The other replica-positive 6–12 kHz trials rest on gap
   equality + the positive two-transit residual (16/17 pairs) — strong but indirect.
   The archive re-score with the §4.1 assignment (fix-plan A1.6) will close this.
4. **Ambiguous recordings:** `d4624efe` (~22 ms secondary at ratio 0.18 on both devices
   — partner vs strong room echo undecided), `d6415a40` mac (twin-peak at 10–17 ms),
   `2e7904fa` (gap_A − gap_B = 9.1 ms, an order larger than every other pair; possibly a
   mis-paired train). Exclude these from golden pins until re-scored with assignment.
5. **Common-mode schedule drift** (`bbcb9f47` android: both trains drift ~−170 µs/beep
   vs the schedule; residuals 750 µs) — playout-vs-capture clock divergence within one
   device. Harmless to the mechanism conclusion (the sum rule is clock-free) but it
   belongs in A3's error budget and weakens per-recording drift-sign tests (use them as
   supporting, not primary, evidence — as specified in §4.1.2).
6. **No low-amplitude true replica hides anywhere we can see** (no 2×-lag repeats above
   0.005 of main; no unexplained third trains), but "absent in this archive" is not
   "impossible" — the A1 train detector will naturally surface one if future hardware
   produces it, since it detects *all* coherent trains before assignment.
