# Late-tail attribution and timeline segmentation

Two opt-in analyzer policies were added for the two blockers named in the [movement evidence](2026-09-22-beepbeep-movement.md): weak recurring tails withholding otherwise complete arrivals, and 20 ms recording-time discontinuities. Both default off. Neither is passed by the live server, so every live report is unchanged. One saved trial changes headline status under one of them. No distance is validated by this work.

## Summary

Under the default configuration, re-analysis reproduces the stored `report.json` for the 18 trials stored at the current analysis version (`reasons`, per-arrival quality, clock fit and exchanges all identical). The four ranging-v1 trials stored at `four-arrival-diagnostic-v1` (28487e02, 550fb0db, 5b79b0d2, efb2b564) and the failed stub f60fa320 differ, for the pre-existing version reasons, not because of these policies.

Under the opt-in policies, exactly one trial flips: 37fa17db (25 cm) becomes `diagnostic` with `late_tail_policy=separate`. Segmentation alone changes no trial's headline status; it changes usable exchanges only on 6b9e788b (0 to 3).

## What changed

`late_tail_policy` (`withhold` | `separate`, default `withhold`). Every non-primary qualified event in a slot is classified by `_secondary_audit` in `beepbeep_analysis.py`. Thresholds, with their stated rationale: amplitude ratio below `0.05` of the slot primary is a candidate tail, at or above `COMPETING_MIN_AMPLITUDE_RATIO = 0.20` the extra sound is strong enough to be an independent emission and stays ambiguous; the band between the two is `unclassified_secondary` and remains fatal. Recurrence is searched within `±10 ms` of the same delay after the same emitter's other primaries; a peer peak counts only if it clears the same 8σ correlation floor the audit demands of an event; a majority (`fraction > 0.5`) is required for `late_tail_recurrent`. A negative delay, or a non-recurrent tail, is `competing_emission_candidate`. Under `separate`, only slots whose every secondary is `late_tail_recurrent` keep their arrival usable.

`timeline_policy` (`global` | `segmented`, default `global`), in `ranging_timeline.py`, wired through `ranging_analysis.timeline_evaluation`. A PCM candidate is an exact-zero or constant run, or a near-silent run below 5% of the recording's own MAD noise floor, lasting at least `TIMELINE_GAP_MIN_MS = 8.0` (three 128-frame worklet quanta) and flanked by varying PCM. Under `segmented` the analyzer refuses to fit one clock model across a candidate; arrivals outside a stable interval are reported, never dropped or stitched.

Report fields added: `attribution.secondary_events` per arrival (classification, amplitude ratio, delay, and the full recurrence record including matched peer offsets), `attribution.late_tail_slots`, a `timeline` block with candidates, corroboration and segments, and a `policy` block echoing every constant above. `LIMITATIONS` gained an explicit entry stating what the recurrence test does and does not establish.

## Benchmark, all 23 captures

Status letters: `i` invalid, `d` diagnostic, `f` failed. Configs in order D = default, L = `late_tail_policy:separate`, T = `timeline_policy:segmented`, B = both. Segment residuals in ms.

| trial | gap | room / pose | live | status D/L/T/B | usable exch D/L/T/B | tails | timeline candidate | corrob | segments (B) | top reason (B) |
| --- | --- | --- | --- | --- | --- | ---: | --- | --- | --- | --- |
| 0617ca3b | - | big / face to face | i | iiii | 0/0/0/0 | 0 | - | no | s0:16em/8ex/0.0109 | A:recording_clipped |
| 20e97c08 | - | big / face to face | d | dddd | 8/8/8/8 | 0 | - | no | s0:16em/8ex/0.0125 | - |
| 2544d907 | - | big / face to face | i | iiii | 0/0/0/0 | 0 | - | no | - | insufficient_independent_emissions_for_clock_fit |
| 2793667c | - | big / face to face | i | iiii | 0/0/0/0 | 0 | - | no | s0:16em/0ex/0.1597 | clock_fit_residual_too_large |
| 28487e02 | - | big / face to face | i | iiii | 0/0/0/0 | 0 | - | no | - | insufficient_independent_emissions_for_clock_fit |
| 32533e19 | - | big / face to face | i | iiii | 0/0/0/0 | 0 | - | no | - | insufficient_independent_emissions_for_clock_fit |
| 37fa17db | 25 cm | small / 90 deg | i | idid | 0/8/0/8 | 1 | - | no | s0:16em/8ex/0.0369 | - |
| 428ab971 | - | big / face to face | i | iiii | 0/0/0/0 | 0 | - | no | s0:3em/0ex/- | insufficient_independent_emissions_for_clock_fit |
| 45e6b9f1 | - | big / face to face | i | iiii | 0/0/0/0 | 3 | - | no | s0:16em/0ex/0.2561 | clock_fit_residual_too_large |
| 550fb0db | - | big / face to face | d | iiii | 0/0/0/0 | 0 | - | no | s0:8em/0ex/- | insufficient_independent_emissions_for_clock_fit |
| 5b79b0d2 | - | big / face to face | d | iiii | 0/0/0/0 | 0 | - | no | s0:6em/0ex/- | insufficient_independent_emissions_for_clock_fit |
| 6b9e788b | - | big / face to face | i | iiii | 0/0/3/3 | 0 | B@4.753s/60.0ms | no | s0:8em/3ex/0.0017; s1:2em/0ex/- | timeline_discontinuity_detected:B:4.753333s:60.000ms:exact_zero |
| 6ba25fd9 | - | big / face to face | i | iiii | 0/0/0/0 | 0 | - | no | - | insufficient_independent_emissions_for_clock_fit |
| 6c526b85 | - | big / face to face | i | iiii | 0/0/0/0 | 3 | B@0.713s/20.0ms | no | s0:16em/0ex/0.3702 | A:recording_clipped |
| 71f0a6a1 | - | big / face to face | i | iiii | 0/0/0/0 | 0 | B@0.800s/20.0ms | no | s0:16em/0ex/0.3065 | clock_fit_residual_too_large |
| 830242a7 | - | big / face to face | i | iiii | 0/0/0/0 | 0 | - | no | - | A:reported_capture_clipping |
| 8335587e | 5 cm | small / 90 deg | i | iiii | 0/0/0/0 | 0 | B@1.217s/20.0ms | no | s0:1em/0ex/-; s1:15em/0ex/0.1833 | clock_fit_residual_too_large |
| 954275df | - | big / face to face | i | iiii | 0/0/0/0 | 0 | B@10.076s/20.0ms | yes | s0:9em/4ex/0.0083; s1:7em/3ex/0.0089 | A:recording_clipped |
| 9830dc42 | - | big / face to face | i | iiii | 0/0/0/0 | 0 | - | no | s0:16em/8ex/0.0095 | A:recording_clipped |
| efb2b564 | - | big / face to face | i | iiii | 0/0/0/0 | 0 | B@4.008s/20.0ms | no | - | insufficient_independent_emissions_for_clock_fit |
| effee55b | 5 cm | small / 90 deg | i | iiii | 0/0/0/0 | 3 | - | no | s0:16em/0ex/0.1758 | clock_fit_residual_too_large |
| f60fa320 | - | big / face to face | f | iiii | 0/0/0/0 | 0 | B@10.215s/20.0ms | yes | s0:10em/0ex/2.4292; s1:6em/0ex/0.2222 | A:recording_clipped |
| f6d98ecb | - | big / face to face | i | iiii | 0/0/0/0 | 0 | - | no | - | A:recording_clipped |

## Late tails in the saved data

Across all 23 captures there are 10 secondary events. All 10 are on receiver A, all 10 classify as `late_tail_recurrent`, and there are zero `competing_emission_candidate` and zero `unclassified_secondary` events. They occur in four trials: 45e6b9f1 (3), 6c526b85 (3), effee55b (3), 37fa17db (1). Nine of the ten are tight: peer delay jitter between 0.000 and 0.042 ms, recurrence 7/7 at both the ±10 ms classification window and the ±2 ms report-only window. Their amplitude ratios run 0.0006 to 0.0140 at delays of 90.10, 114.25–114.27, 186.75 and 202.02–202.04 ms.

The tenth is the one that matters. 37fa17db slot e13 (emitter B) has ratio 0.0190 at 163.00 ms, recurrence 7/7 at ±10 ms but only 3/7 at ±2 ms, with matched peer offsets spanning 0.83 to −6.40 ms — peer delay jitter 6.396 ms. Its classification therefore rests on the 10 ms window being the right width. The window is about a chirp-envelope width, so it asks whether a qualified peak reappears anywhere inside the reverberant tail at roughly that lag; it does not establish a fixed-delay path.

Under `separate`, 37fa17db regains its 32nd arrival and becomes `diagnostic` with 8/8 usable exchanges, maximum clock residual 0.0369 ms and median timing difference 1.746256 ms, which is 29.948 cm uncorrected. That number is not a device-body distance: it carries unknown self paths, detector bias and device response, exactly as in the earlier movement write-up. effee55b regains 32/32 arrivals under `separate` but still fails the 0.15 ms residual gate at 0.1758 ms, so it stays invalid. 45e6b9f1 and 6c526b85 likewise regain arrivals and stay invalid for their pre-existing reasons.

Chirps carry no source authentication. A recurrent weak tail is equally consistent with room or device response and with a co-located replay locked to that device's emission schedule. The `separate` policy records the recurrence as evidence; it does not attribute the sound to a source.

## Synthetic checks

In-memory only, injected into a copy of 20e97c08's audio; nothing was saved and no capture directory was touched. Tails at 1% and 3% of the primary classify as recurrent and, under `separate`, restore 32 arrivals and 8 exchanges. A 10% tail falls in the 0.05–0.20 unclassified band and stays fatal under both policies. Competing injections at 30% and 100%, and an earlier competing chirp at −80 ms, all stay `competing_emission_candidate` and remain fatal. A non-recurrent single-slot tail at 1% classifies as competing and remains fatal. A 0.3% tail never clears the event threshold at all, so no event is produced. Synthetic checks do not validate physical accuracy.

## Timeline candidates and segmentation

PCM candidates appear in 7 captures: 6b9e788b, 6c526b85, 71f0a6a1, 8335587e, 954275df, efb2b564, f60fa320. All 7 are on recording B, all are exact-zero, all are 20 ms except 6b9e788b at 60 ms.

Corroboration against the existing clock-step check succeeds for only two: 954275df (candidate 20 ms, fitted step 19.997 ms) and f60fa320. It structurally cannot corroborate 8335587e, because that break follows emission 1 and the step model needs at least two emissions per emitter on each side of the boundary. Absence of corroboration is therefore not evidence against a candidate.

954275df splits into two valid segments — 9 emissions / 4 exchanges, residual 0.0083 ms, median 0.2467 ms, and 7 emissions / 3 exchanges, residual 0.0089 ms, median 0.2479 ms — agreeing to within 0.0013 ms across the break. The trial nonetheless stays invalid: `A:recording_clipped` is independent of the timeline. 6b9e788b (ranging-v1) recovers an 8-emission segment with 3 exchanges at 0.0017 ms residual; the second segment has only 2 emissions and stays unfit.

8335587e is the 5 cm return run. Segmentation drops its largest residual from 14.62 ms to 0.1833 ms on segment 1 (15 emissions), still above the 0.15 ms gate. The five largest remaining residuals are all B-emitted rows, and the BA path alternates its selected-minus-strongest lag between 0 and −13 samples (about 0.271 ms at 48 kHz). That residual is consistent with peak-family switching, not with a remaining timing error. Peak-family selection is unchanged by this work and remains open.

## Limitations

- True sample deletion — frames removed rather than zeroed — leaves no silent span and produces no PCM candidate. Only the existing clock-step check and the worklet counters can notice it, and neither localizes it in the PCM. Synthetic case (c) covers this.
- Exact silence, a muted source and digital padding produce identical samples. A candidate is an observation with declared thresholds, not an identified cause.
- The 10 ms recurrence window does not resolve a fixed delay; the matched offsets are reported so the jitter is visible.
- No policy here changes a selected arrival, repairs a recording, or produces a NEAR/FAR verdict. No calibrated distance follows from any number in this document.

## Review findings and fixes

Six issues were found and fixed during review: cross-axis segment projection (a latent grouping bug, where a cut on one recording's axis was compared against the other recording's times); the peer significance floor (a raw window argmax was otherwise satisfied by noise, so peers must now clear the same 8σ threshold as events); the class rename `late_tail_source_locked` to `late_tail_recurrent`, because the evidence is recurrence and not a source; the ±2 ms report-only recurrence diagnostic, which is what exposed the 37fa17db jitter; `--set` unknown-key rejection in `analysis/reanalyze_ranging.py`, so a misspelled key is refused instead of silently discarded; and failure-path exchange consistency via `_mark_exchanges_unusable`, which preserves segment membership when a capture failure invalidates a clock fit after exchanges were built.

## Recommended next step

Do not enable either policy live yet. For `late_tail_policy=separate`, the evidence that would justify it is a capture pair recorded with a deliberate, independent co-located emitter playing the same chirp on a schedule locked to a device, showing that such a replay is classified `competing_emission_candidate` and not `late_tail_recurrent` — and a decision on whether a 10 ms window is acceptable given the 6.396 ms jitter on 37fa17db's only tail. For `timeline_policy=segmented`, it is a capture where a segmented result and an independent ground-truth gap agree, since today segmentation recovers exchanges on two trials and validates none. Peak-family selection should be settled first: 8335587e shows it can hold a trial above the residual gate on its own.

## How to reproduce

From the repository root, per trial directory. Nothing is written into `data/ranging/`.

```
python3 analysis/reanalyze_ranging.py data/ranging/<trial_id> --output-dir <out>/default
python3 analysis/reanalyze_ranging.py data/ranging/<trial_id> --set late_tail_policy=separate --output-dir <out>/late_separate
python3 analysis/reanalyze_ranging.py data/ranging/<trial_id> --set timeline_policy=segmented --output-dir <out>/timeline_segmented
python3 analysis/reanalyze_ranging.py data/ranging/<trial_id> --set late_tail_policy=separate --set timeline_policy=segmented --output-dir <out>/both
```

Per-trial rows, the full secondary-event records, and sha256 of the four source files and of all 23 stored `report.json` files are in the [machine-readable benchmark](benchmarks/2026-09-23-late-tail-and-timeline.json).
