# First physical ranging captures

> Historical record. Automated tests and regression gates were removed at the user's request on 2026-09-22. Old test commands below no longer apply; follow [the current workflow](../AGENTS.md).

Four trials recorded on 2026-09-22 at 05:41–05:43 UTC. Labels describe a MacBook Air and Pixel 6, a 5 cm body gap, face-to-face placement, and a large room with a high ceiling. The user confirmed changing position, orientation, or grip across the attempts. These are therefore not repetitions of one unchanged setup.

## Results

| Trial | Timing status | Finding |
|---|---|---|
| `28487e02` | Invalid | Maximum clock-fit residual 0.211 ms exceeds the 0.150 ms limit. Some MacBook self-arrival estimates shift by roughly 0.25–0.30 ms. |
| `5b79b0d2` | Diagnostic | All 8 exchanges usable under current checks. Timing difference −0.158044 ms; clock-fit RMS residual 0.005547 ms. |
| `550fb0db` | Diagnostic | All 8 exchanges usable under current checks. Timing difference +0.076858 ms; clock-fit RMS residual 0.003313 ms. |
| `efb2b564` | Invalid | Approximately 20 ms relative timing step. Raw Pixel recording contains exactly 960 consecutive zero samples at 48 kHz. |

All four trials contain both complete uploaded recordings and detections for all 16 emissions on both receivers. Each WAV has 410,016 samples at 48 kHz. There are no reported clipping samples, missing worklet input frames, block discontinuities, hidden-page events, or audio-context interruptions. Requested and reported echo cancellation, noise suppression, and automatic gain control are false. These browser reports do not establish what happened below the browser's input interface.

The two diagnostic timing differences differ by 0.234902 ms, equivalent to 4.03 cm in the uncorrected timing expression. This is not an observed change in body gap or a fixed-placement repeatability failure. Placement changed, self-path lengths are unknown, and arrival bias is uncalibrated. All four body-gap decisions remain inconclusive.

## Concrete failure in the last recording

In `efb2b564cf1c4f54b7260e4e45431e2e/recording_B.wav`, frames 192,384 through 193,343 are exactly zero. This is the interval [4.008, 4.028) seconds, exactly 20 ms. The fitted relative timing step is 19.971 ms. It occurs between observations of emissions e06 and e07; the report's 3.64085-second change-point coordinate is a midpoint between probes, not a measured dropout onset.

After this interval, both emitter groups appear about 20 ms later in B's recording relative to A. B's own arrivals also shift by 20 ms relative to its playback schedule, while A hearing those same B emissions preserves their spacing. This supports a change in B's capture timing, accompanied by silent padding or a dropout. It does not identify the browser, driver, or operating system component responsible.

The delivered AudioWorklet blocks remain consecutive. Block continuity alone therefore missed a defect present in the audio content. The independent clock-consistency check correctly withheld the result. Its invalid 4,055 ppm slope estimate should not be interpreted as a measured hardware clock rate.

## Limits of the apparently usable results

The current detector enforces 0.60 ms separation between candidate peaks. Nearby peaks can therefore be grouped into one candidate even when their timing differences matter at centimeter scale.

Inspection of the full-resolution template-match profiles found:

- In the failed `28487e02` trial, A's self-arrivals e02 and e10 select later peaks despite earlier peaks about 0.274 ms and 0.249 ms away. The earlier peaks have normalized correlations about 0.558 and 0.579, both above the 0.40 cutoff. Suppression of these alternatives hides the local ambiguity behind the two largest clock-fit residuals.
- In `5b79b0d2`, B hearing its own e01 probe has a peak 0.3125 ms earlier than the selected peak, with 87.2% of its amplitude.
- In `550fb0db`, A hearing B's e01 probe has a peak 0.2708 ms earlier than the selected peak, with 96.9% of its amplitude. Nearby competing lobes are present across the other B-to-A probes too.

These may be a combination of the channel response, the matched-filter shape, and multipath. The recordings alone do not prove that a particular lobe is a separate reflection or the direct air path. Choosing the earlier lobe to obtain an expected 5 cm result would be invalid. A single reported candidate and a small within-trial spread do not establish physical accuracy.

## Next engineering work

Use the existing WAVs before collecting a larger campaign. Expose internal silent spans alongside block continuity, retain and display closely spaced peak structure, and make arrival ambiguity and uncertainty account for that structure. Preserve the original reports and timing rejection limits. Any revised detector needs synthetic cases for close overlapping paths and channel filtering, followed by reanalysis of all four captures without using their distance labels to choose arrivals.

After those diagnostics are reviewable, collect several runs at one unchanged placement, with both devices resting still and volume fixed. That will test repeatability. A subsequent distance sweep and held-out placements are still needed to test distance sensitivity and a body-gap decision.

This review changed no analyzer code, acceptance thresholds, original reports, or recordings.


## Implemented v2 diagnostics and reanalysis

Version `four-arrival-diagnostic-v2` now preserves close local maxima, compares their shape with exact-template autocorrelation, and withholds ambiguous onset times. A separate scan reports exact-zero and constant spans throughout the original PCM. Silence alone is a diagnostic observation, not a cause-specific rejection. The existing detection and clock-fit thresholds remain unchanged.

All four saved recordings were reanalyzed into new files. All 48 original trial artifacts passed a byte-for-byte SHA-256 preservation check.

| Trial | v1 status | v2 status | Ambiguous arrival windows | Saved v2 view |
|---|---|---|---:|---|
| `28487e02` | Invalid | Invalid | 24 / 32 | [Open saved analysis](https://192.168.0.34:5002/ranging?trial=28487e02f60944aaa2b2556d53e31e22&report=reanalysis_7d8b09137757420d893aa98e6585bd29.json) |
| `5b79b0d2` | Diagnostic | Invalid | 18 / 32 | [Open saved analysis](https://192.168.0.34:5002/ranging?trial=5b79b0d2afda4e03ab21afae93842e8f&report=reanalysis_1d2262a3d974456f9cbeab4c8e465dbe.json) |
| `550fb0db` | Diagnostic | Invalid | 16 / 32 | [Open saved analysis](https://192.168.0.34:5002/ranging?trial=550fb0db67734444a47630c18e57fd26&report=reanalysis_a3ecdc5e2c45403686995f138eb61f75.json) |
| `efb2b564` | Invalid | Invalid | 24 / 32 | [Open saved analysis](https://192.168.0.34:5002/ranging?trial=efb2b564cf1c4f54b7260e4e45431e2e&report=reanalysis_7d8bd2965ff74817a5ddd25f3560c9d5.json) |

All four retain 32 detected arrival windows. Too few unambiguous arrivals in both emitter directions remain for a valid clock fit. The two previous diagnostic results no longer expose numeric timing summaries. This is a correction to the confidence of the diagnostic, not evidence that the devices were far apart.

The last recording independently exposes its exact 20 ms internal zero span even though arrival ambiguity now prevents fitting a clock step. The original v1 report remains available as evidence of the earlier 19.971 ms fitted step. The new analysis neither removes those samples nor chooses a competing peak to recover that fit.

The next distance-estimation work remains separating or modelling the channel response well enough to justify an arrival time. A clean result under these heuristic checks still does not validate physical accuracy. The close-peak comparison uses an explicit 0.08 amplitude tolerance and one-sample reference allowance; it can miss merged paths without distinct peaks.

Validation passed 61 Python tests, 15 JavaScript tests, and the existing quick echo regression. Browser checks covered all four new saved views, an original v1 view, malformed links, mobile layout, and a two-browser capture using a silent simulated microphone. Saved views made no recording-session connections. No new physical measurement was performed for this update.
