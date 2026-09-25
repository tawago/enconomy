# Proximity-Echo Reproduction — Progress Report

Snapshot of state as of the end of the working session that pivoted from a custom direct-path scorer to a faithful reproduction of Ren et al., *Proximity-Echo* (INFOCOM '21).

> **⚠ CORRECTION (2026-07-07).** Several results below were later invalidated by a
> confirmed cross-device alignment bug (self-aliasing — see
> [fix-plan.md](fix-plan.md)):
>
> - The headline "paper-grade scores (0.74–0.89) on five of ten trials" and the
>   May-12 touch ACCEPT at 0.86 (`ca3013a2`) are artifacts: in `ca3013a2` **all**
>   "partner" beep selections on both devices were the device's *own* beeps, so the
>   score correlated self-echo with self-echo, not proximity.
> - The results table's scores came from re-analysis under later code revisions and
>   disagree with the logged values for the same trials (e.g. `fedbaf73`: 0.862 in the
>   table vs 0.464 in `trials.jsonl`) — scores were not stable across the ~20
>   hand-tuned constants being retuned between sessions.
> - The conclusion "the analysis pipeline is no longer the bottleneck" is therefore
>   unsupported; the alignment layer of the pipeline *was* a (silent) bottleneck, in
>   addition to the real hardware asymmetry, which remains true.
>
> The hardware observations (directional MacBook mic, phone speaker roll-off,
> touch-distance clipping) and the architecture decisions are unaffected.

## TL;DR

We rebuilt the pipeline to match the paper's protocol (alternating L=20 short beeps, 4-direction energy-loss compensation, Pearson correlation on smoothed echo-period spectra, threshold 0.78). The analysis works end-to-end and gives **paper-grade scores (0.74-0.89) on five of ten collected trials** — including the most recent touch trial at 14-15 kHz which scored **0.86**. The remaining bottleneck is a hardware/setup issue: at this user's MacBook + Android phone combination, **the laptop microphone often cannot pick up the phone's beep emissions** through air, even at 6-12 kHz, even at touch distance. When that asymmetry is bad, c_a or c_b drops below the threshold and the trial is rejected. The analysis pipeline is no longer the bottleneck; cross-device acoustic propagation is.

## What was built

### Pipeline (paper-faithful)

| File | Role |
|---|---|
| `challenge_generator.py` | 6-12 kHz, 40 ms linear chirp at 48 kHz. Originally 14-15 kHz / 20 ms per paper §IV-A but dropped to a wider lower band because phone speakers don't radiate 14 kHz audibly across an air gap on the user's hardware. |
| `server.py` | Schedules L=20 alternating beeps per device at 0.5 s intervals (lead-in 1 s, total ~21.5 s recording). HTTPS + WebSocket harness. |
| `static/app.js` | Audio-clock scheduling (`BufferSource.start(when)`) for jitter-free playback; "Tap to Arm Audio" gesture to unlock AudioContext on each device; speaker test buttons; live cross-device link meter. |
| `alignment.py` | Period selection per paper §IV-B: bandpass → matched-filter envelope → two-phase τ1 / τ_k search with sliding-window local-max removal. |
| `feature_extraction.py` | Per-beep chirp/echo energy spectra, plus cross-device clock-drift compensation (described below). |
| `compensation.py` | Energy-loss compensation per paper Eq. (10): `comp(f) = √((R̄_BB/R̄_BA)·(R̄_AB/R̄_AA))`, cubic-spline interpolated to the echo-period frequency grid. |
| `scoring.py` | 20-frequency-point smoothed Pearson `c_A = corr(R̄'_AA, R̄''_AB)` and `c_B = corr(R̄'_BB, R̄''_BA)`; final score = mean; threshold 0.78. |
| `analysis/smoke_test.py` | Synthetic same-room vs different-rooms test. Currently 0.993 vs 0.475 — clean separation. |
| `analysis/inspect_trial.py` | Compact summary view per trial. |

### Browser UX additions

- **Tap to Arm Audio** button on each device (mandatory user gesture for AudioContext.resume + silent-buffer trick to unlock output on Android Chrome / iOS Safari).
- **Speaker test** buttons (1 kHz / 8 kHz / 6-12 kHz chirp / 5-beep schedule).
- **Cross-device link test**: continuous 8 kHz tone toggle + live mic level meter (in-band 6-12 kHz). Lets the user verify each device hears the other before running a full trial.
- Granted MediaTrackSettings logged so AEC/NS/AGC behavior is visible per trial.

### Cross-device clock-drift compensation

This was the biggest non-obvious bug. Each device's `audioContext.currentTime` is a separate clock; recording-start instants on the two devices differ by ±100-700 ms in wall-clock. Schedule offsets are interpreted in each device's *own* clock, so the partner's emission lands at `schedule_offset + (partner_latency + clock_drift)` in our recording — anywhere in a ±1500 ms window relative to schedule.

Solution implemented:
1. **Tight self-search** (-20 ms / +230 ms) so partner's emission can't sneak in.
2. **Brute-force cross-offset search** in `feature_extraction.py::_estimate_cross_device_offset_ms`: sweep candidate offsets in [-900 ms, +900 ms] at 10 ms steps; for each, score by the average matched-filter envelope value at the predicted cross-emission positions; pick the maximizing offset that clearly stands out from the median.
3. **Tight cross-search** around `schedule + cross_offset` for the actual period selection.

Cap of ±900 ms specifically to avoid an aliasing trap (cross peaks are 1 s apart, so the score at any offset ±1000 ms also looks high; a wider search picks the wrong one).

## Empirical results

Re-analyzing all 10 paper-repro trials with the final pipeline:

| trial | cond | band | c_a | c_b | score | verdict@0.78 | notes |
|---|---|---|---|---|---|---|---|
| fedbaf73 | touch | 14-15 kHz / 20 ms | 0.852 | 0.872 | 0.862 | **ACCEPT** | paper-grade |
| 361d4526 | – | 14-15 kHz / 20 ms | 0.975 | 0.803 | 0.889 | **ACCEPT** | best result |
| fadae387 | – | 14-15 kHz / 20 ms | 0.884 | 0.590 | 0.737 | reject | borderline |
| 0b8127ea | – | 6-12 kHz / 40 ms | 0.817 | 0.501 | 0.659 | reject | c_b weak |
| c175938d | – | 14-15 kHz / 20 ms | 0.894 | 0.000 | 0.447 | reject | c_b dead (laptop didn't hear phone) |
| d4624efe | – | 6-12 kHz / 40 ms | -0.180 | 0.471 | 0.145 | reject | c_a noise |
| bbcb9f47 | – | 6-12 kHz / 40 ms | -0.079 | 0.242 | 0.081 | reject | phone face-down → mic blocked |
| b1f00218 | touch | 6-12 kHz / 40 ms | 0.048 | -0.076 | -0.014 | reject | clipping (laptop wav peak=1.0) |
| 8e25f1d4 | 30 cm | 6-12 kHz / 40 ms | -0.326 | -0.050 | -0.188 | reject | laptop can't hear phone |
| 976bfc01 | – | 14-15 kHz / 20 ms | -0.350 | -0.162 | -0.256 | reject | early-band, weak |

Smoke test (synthetic): same-room 0.993, different-rooms 0.475.

## Architecture decisions made along the way

- **14-15 kHz → 6-12 kHz**: the paper's band fails on commodity phone speakers — they radiate 14 kHz to their own near-field mic at env~150 but the laptop mic 30 cm away gets env~0.02 (pure noise floor, verified directly from wav spectrograms). 6-12 kHz lets both devices' speakers radiate enough to be picked up.
- **No hand-tuned scorer**: the original implementation used a 7-component weighted score. Replaced entirely with the paper's Pearson approach. The hand-tuned scorer is gone.
- **Audio-clock scheduling, not setTimeout**: `setTimeout`-based playback callbacks suspended the AudioContext mid-trial on Android Chrome. Switched to pre-scheduling all 20 beeps via `BufferSource.start(audioCtx.currentTime + offset)` in one synchronous loop. Fixed phone emission reliability completely.
- **Arm gesture on both devices**: Android Chrome / iOS Safari refuse to play scheduled audio without a per-device user gesture. The "Start Trial" button on the laptop wasn't a gesture for the phone, so the phone played nothing for the first several trials. Adding "Tap to Arm Audio" on both devices fixed it.
- **Tight self-search window**: when the partner's emission lands ~100 ms after a self-emission (cross_offset around -300 ms is common with our trial setup), a wide self-search would lock onto the (often louder) cross emission instead of self. Window is now -20 / +230 ms — tight enough to exclude the partner.

## Current blockers (in priority order)

### 1. Asymmetric cross-device acoustic propagation (HARDWARE)
The MacBook microphone is heavily directional/beamformed and physically positioned to face the user's mouth. A phone sitting beside the laptop with its speaker pointing in a different direction does not get heard. We've verified this directly:
- In multiple trials the **laptop's wav shows env=0.02 at every phone emission time** (pure noise floor) while the **phone's wav shows the laptop emissions at env~0.6** (faint but consistent).
- Flipping the phone face-down reverses the asymmetry: c_b jumps to 0.73 but c_a goes to noise (phone mic now blocked by desk).
- Only orientations that worked for both directions: phone screen-up with the bottom-edge speaker offset over the desk edge (and aimed at the laptop's mic location). Even that is fragile.

The paper used a ThinkPad X280 + four Android phones; their mic placements are different.

**Mitigations to try next session:**
- Have the user document one specific physical setup (orientation, distance, surface) that gives both directions ≥ 0.5 in the live link-test meter, then run the full distance sweep in that orientation.
- Consider lowering the band further to 4-9 kHz (more omnidirectional speaker output).
- Consider using an external USB mic on the laptop or AirPods/headphones speaker to bypass the directional MacBook mic.
- Ask the user to test with a different phone if available — Android speakers vary widely.

### 2. ADC clipping at touch distance (HARDWARE / UX)
Trial b1f00218 (6-12 kHz, touch) had `peak=1.0000` in the laptop's WAV — the recording clipped because the phone speaker is too loud at touch range, the matched filter shape is destroyed, and analysis fails completely. We currently emit at amplitude 0.6.

**Mitigations to try:**
- Reduce `BEEP_AMPLITUDE` in `challenge_generator.py` to 0.3-0.4.
- Or detect clipping in canonicalization and either reject the trial or apply a soft de-clipping pre-filter.
- Or document that "touch" should mean ~5 cm separation, not literally touching.

### 3. Score asymmetry on borderline trials
Even when both directions reach each other, c_a often outperforms c_b by 0.2-0.3. Trial fadae387 has c_a=0.88 / c_b=0.59 — score 0.74, just below the 0.78 threshold. Possible causes:
- Imperfect energy-loss compensation when the chirp-period spectra used for it are themselves noisy.
- Cross-device output latency on Android being so large that some echo-period samples leak into the next emission window (echo period is 100 ms, schedule spacing is 500 ms — should be safe but worth verifying).

**Mitigation to try next session:**
- Try lowering the verdict threshold from 0.78 to ~0.65 once we have a real distance sweep — paper's 0.78 was tuned for their hardware, ours likely runs at lower absolute correlations.
- Or use `max(c_a, c_b)` instead of mean — accept proximity if either direction confidently agrees. (Deviates from paper but practical.)

### 4. Smoke test passes don't predict real trials
Synthetic same-room scores 0.993 in the smoke test, but the best real same-room score is 0.89. The smoke test uses random-impulse room responses convolved cleanly; real microphones add noise, AGC artifacts, and the directional/asymmetry effects above. The smoke test is useful for catching pipeline-wiring regressions but not for tuning thresholds.

## Files of interest for next session

- `data/audio/` — 10 trial WAVs (4 paper-repro pairs at 14-15 kHz, 5 at 6-12 kHz)
- `data/logs/trials.jsonl` — full structured logs for every trial
- `analysis/inspect_trial.py <trial_id>` — quick view
- `progress-report-proximity.md` — this document

## What to do first next session

1. Decide on the band: 6-12 kHz works in principle but produces lower absolute correlations than 14-15 kHz. Consider trying both with the new alignment fixes and picking whichever gives larger touch-vs-1m separation, not which gives higher absolute touch scores.
2. Have the user collect a labeled distance sweep — 5 trials each at touch / 10 cm / 30 cm / 1 m / different-room — in **one fixed physical orientation** that produces ≥ 0.5 on both directions of the link-test meter. Then we can do real ROC analysis instead of debugging individual trials.
3. Sweep the verdict threshold against this dataset; the paper's 0.78 is a hardware-specific number, not a fundamental constant.
4. If the sweep shows separation, consider mild scoring changes (e.g., max(c_a, c_b) instead of mean, or weighting by signal quality) that recover the asymmetric-propagation cases without re-introducing hand-tuning.
5. If the sweep shows no separation, investigate either external-mic setups (USB mic, headphones) or accept that this commodity-browser MVP has shown its limit and start scoping native implementation.

## Out of scope so far

- Replay attack and co-located attack tests (paper §V-D, §V-E). The paper's whole security claim rests on these; we haven't run them yet because basic touch-vs-distance separation needs to land first.
- Multi-device pairs (paper tested 4 phones × 1 laptop). We've only tested one phone.
- Validation against any published threshold (paper's 0.78 may be unreachable on our setup).
