# First live BeepBeep recordings

One of nine recordings passed all timing checks. The final capture, `20e97c08`, has 32 usable arrivals and eight usable exchanges. Seven earlier attempts were invalid; one failed recording continuity. This establishes one usable acoustic timing capture on the current pair. It does not validate the 5 cm body gap or repeatability across placements.

The user confirmed that every placement was around 5 cm, with small phone movements between runs to locate its microphone. The phone rested untouched during each recording. These are different placements rather than an unchanged-pose repeatability series. No 25 cm comparison is present.

| Trial, in order | Timing status | Usable arrivals | Main finding |
| --- | --- | ---: | --- |
| [2793667c](../data/ranging/2793667c360a4f69b6983f987acc41ab/report.json) | invalid | 32/32 | Timing fit failed, mainly the first phone self-arrival |
| [6c526b85](../data/ranging/6c526b853cf848bfa5fd2e13112cf5b6/report.json) | invalid | 29/32 | Laptop amplitude limit; multiple events in three slots; timing fit failed |
| [954275df](../data/ranging/954275dfec30447994b1573548513189/report.json) | invalid | 32/32 | Laptop amplitude limit; 20 ms phone PCM gap and timing step |
| [0617ca3b](../data/ranging/0617ca3bdaef434ab2361584f65f0e07/report.json) | invalid | 32/32 | Laptop amplitude limit; arrival timing otherwise fits |
| [9830dc42](../data/ranging/9830dc421f384b31af9ec003beff59f1/report.json) | invalid | 32/32 | Laptop amplitude limit; arrival timing otherwise fits |
| [45e6b9f1](../data/ranging/45e6b9f1f6f04f3b821e83a8b5201a35/report.json) | invalid | 29/32 | Multiple events in three slots; timing fit failed |
| [f60fa320](../data/ranging/f60fa320428c40a99845607c588db174/report.json) | failed | Not analyzed | Capture context-frame discontinuity; laptop amplitude also exceeds limit |
| [71f0a6a1](../data/ranging/71f0a6a15650426c81dfe66fb4114d6a/report.json) | invalid | 32/32 | Inconsistent selected peaks; timing fit failed |
| [20e97c08](../data/ranging/20e97c0891f941de8f97a3168c518d7c/report.json) | Passed | 32/32 | All timing and recording checks passed |

## The final capture

The signed four-arrival difference is 1.080615 ms, or 18.53255 cm before self-path correction. Both self-path lengths are unknown, so corrected mean acoustic path and body gap remain unset. This number is not an estimate of the ruler-measured gap. Relative recording rate is 17.671 ppm; the maximum clock-fit residual is 0.012463 ms against the declared 0.15 ms limit.

The displayed near-zero spread is not submillimeter accuracy. Seven exchanges occupy the same integer-sample difference, while one differs by one sample, about 0.3573 cm in the timing equivalent. Median absolute deviation rounds almost to zero in this pattern. Full exchange range is 18.53251–18.88981 cm. Neither that range nor the small clock residual bounds stable reflection or device-response bias.

## Capture and timing failures

All 18 WAVs contain the expected 818,640 frames at 48 kHz, including the failed attempt. File hashes, headers, peak amplitudes, and over-threshold sample counts match upload metadata. Full file length does not establish continuity: failed `f60fa320` contains a negative 128-frame then positive 128-frame context discontinuity.

Five laptop recordings exceed the current 0.999 amplitude limit, including the failed capture. Four analyzed reports are withheld for this reason. Their float PCM peaks range from 1.243 to 8.830. This establishes threshold exceedance, not the location or mechanism of analog hard clipping. The phone never exceeds that limit. OS volume is not recorded.

In `954275df`, the phone contains 960 exact-zero samples from 10.076 to 10.096 seconds. Arrival times on both emission directions then show a roughly 19.997 ms step. This supports a recording-time discontinuity; the analysis correctly withheld timing. Smaller timing failures have path-specific peak changes rather than the same shared-step evidence.

No run logs page hiding, audio-context suspension, microphone mute/end, or wake-lock release. All request Left only on both devices with the same capture settings. These software observations do not verify which physical speaker or microphone the OS used. There is no basis here to blame movement during recording.

## Next recording

Keep the final successful arrangement and comfortable volume. Mark the 5 cm position, translate the phone straight back to 25 cm without rotating it, update the distance label, and record. Return to the marked 5 cm position and record again. Keep each pose untouched for the complete capture. If the final successful setup has already changed, first take a fresh 5 cm baseline.

The exact microphone location is not needed for this first relative-change test. Leave optional self-path lengths blank. The comparison should show whether timing changes with position and returns; it will still require independent calibration and more placements before a proximity verdict. Retain failures rather than adjusting detector gates to force a result.

## Verification

Two Astra Max subagents independently audited capture data and timing. Re-running the unchanged live analyzer on the final original WAVs exactly reproduced status, summary, arrivals, attribution, clock fit, exchanges, and reasons. Every trial source hash matches the current implementation. No original recording, report, threshold, live code, or running server was changed. [Machine-readable evidence](benchmarks/2026-09-22-beepbeep-first-runs.json).
