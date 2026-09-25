# Two left-only repetitions

> Historical record. Automated tests and regression gates were removed at the user's request on 2026-09-22. Old test commands below no longer apply; follow [the current workflow](../AGENTS.md).

Both new recordings contain all expected probes, with no overload, missing browser frames, or repeat of the earlier long silent span. Their response shapes are consistent within each run. Left-only playback did not reliably eliminate competing arrival peaks, so neither recording establishes a distance.

| Trial | Playback | Detected arrivals | Ambiguous arrivals | Distance |
|---|---|---:|---:|---|
| `6ba25fd9` | Left / Left | 32 / 32 | 24 | Withheld |
| `428ab971` | Left / Left | 32 / 32 | 21 | Withheld |

The user supplied these as two fixed-placement repetitions. Both have session label `exp-3-sep-22`, reference body gap 5 cm, and pose `face to face`. Readiness, upload, and report metadata agree on Left-only playback. Participant identities, unchanged input settings and output layout, and increasing context times support one armed session across the pair. Reference gap labels are not estimator inputs.

## Capture and arrival observations

All four WAVs contain 410,016 mono samples at 48 kHz. No samples exceed the existing 0.999 overload threshold. Laptop peak amplitudes are 0.5023 and 0.5910; phone peaks are 0.1038 and 0.0839. The phone contains isolated 1.00–1.21 ms zero or constant spans in quiet audio, with no corresponding large timing jump. These differ from the previous 60 ms zero span with an independently observed timing step.

Every laptop-to-phone arrival is locally usable in both recordings. Every phone-to-laptop and phone self-arrival remains ambiguous. The laptop self path is ambiguous on eight probes in the first recording and five in the second. No probes are missing or rejected for clipping. The original first-arrival clock estimator receives zero and three usable paired observations. Its unavailable fit follows from the arrival gate; it does not by itself establish clock instability.

Amplitudes differ from the earlier Left-only capture, so its reduction to four ambiguous arrivals cannot be treated as an established routing effect under identical conditions. OS volume and complete geometry were not recorded. This does not establish that either changed between the two new repetitions.

## Independent whole-response timing

The offline inspector uses each exact emitted waveform to estimate a complete response for each path. It aligns repeated response shapes without declaring a physical first arrival. It retains original excerpt origins and fits a common relative clock rate with separate fixed offsets for the two emitters.

| Trial | Relative rate | Clock-trend RMS | Rate in low / high band |
|---|---:|---:|---:|
| `6ba25fd9` | 21.750 ppm | 0.378 µs | 21.639 / 21.695 ppm |
| `428ab971` | 22.034 ppm | 0.256 µs | 22.266 / 22.259 ppm |

These residuals describe agreement with the clock model, not absolute timing accuracy or distance error. Fixed path-dependent timing bias remains unknown. Low and high bands are 4.25–6.25 and 6.25–8.75 kHz.

Within-run median complex response coherence across paths is 0.9933–0.9994. Held-out response predictions explain 99.54–99.93% of regularized in-band waveform energy after delay and gain fitting. Phone self-probe normalized matches are at least 0.823 and 0.802 in the two runs.

Between the pair, mean responses explain 96.17–98.51% of each other's complex response energy after delay and gain alignment. Small differences and competing lobes remain. The first laptop self response has lobes 0.2292 ms apart with amplitude ratio 0.963. The second phone-to-laptop response has lobes 0.3125 ms apart with ratio 0.976. Stable competing lobes still do not identify the direct path.

## Software follow-through

Optional offline reanalysis now attaches a whole-response clock and per-path consistency diagnostic:

```bash
.venv/bin/python analysis/reanalyze_ranging.py data/ranging/<trial_id> --include-responses
```

It creates a new report and preserves the original arrival classifications, clock result, distance summary, and INCONCLUSIVE verdict. Recording-quality failures prevent supplemental inspection. Missing probes or invalid diagnostic output leave the optional section unavailable. The saved-result view labels clock-model residuals separately from physical accuracy and exposes band, emitter, and possible-step diagnostics. A step candidate is not a correction or proof of a dropout.

The inspector verifies exact template identity and schedule order, chronological nonoverlapping detected probes, finite mono audio, and complete extraction windows. Tests cover stable two-tap responses with known drift, an inserted timing step, missing probes, silence, invalid identities, and extraction boundaries. No new distance threshold or physically validated status was added.

No more user recordings are needed for this processing stage. These repetitions can test clock alignment and alternative arrival estimators. Physical arrival bias must still be identified or bounded before a distance sweep can validate a 0–10 cm decision. Two clean recordings do not prove that earlier intermittent capture defects are fixed.

## Saved views and validation

- [First repetition with response diagnostics](https://192.168.0.34:5002/ranging?trial=6ba25fd9b43946a0b327e0a63ad5ef0d&report=reanalysis_a62d0b62dd774f73999ab6b3ceaeef24.json)
- [Second repetition with response diagnostics](https://192.168.0.34:5002/ranging?trial=428ab971ce3d49948158fc7351a397f0&report=reanalysis_80a8b9769dea4278b13087b2a898d5f0.json)

Expand **Inspect independent response alignment**. The original arrival clock and distance fields remain withheld. Primary status, arrivals, recording diagnostics, clock result, aggregate, and summary match the original reports exactly. The original INCONCLUSIVE decision is preserved.

All 70 Python and 22 Node tests passed. Browser checks covered both saved diagnostics, unchanged withheld timing fields, older reports without the optional section, and a 393-pixel mobile layout. Saved views opened no recording socket or microphone. Hashes confirmed all 132 original capture artifacts across the eleven trials remain unchanged, as do the legacy log and golden data.
