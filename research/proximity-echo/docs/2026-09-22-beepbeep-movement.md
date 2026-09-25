# First 5 cm, 25 cm, 5 cm comparison

The three recordings contain a promising change-and-return pattern in an exploratory timing calculation. All three live reports remain invalid. No calibrated distance or proximity decision follows from this experiment.

The run labels correctly record 5 cm, 25 cm, and 5 cm in `exp-5-sep-22`, a small room with the pose labeled `90 degree`. This is a new setup relative to the previous successful run, which was labeled a large room and face-to-face. The comparison below uses only this new sequence.

| Trial | Reference gap | Live usable arrivals | Live result | Exploratory timing difference | Uncorrected timing equivalent |
| --- | ---: | ---: | --- | ---: | ---: |
| [effee55b](../data/ranging/effee55b8cc34113a00babb14bcff234/report.json) | 5 cm | 29/32 | Invalid | 1.080653 ms | 18.5332 cm |
| [37fa17db](../data/ranging/37fa17dbb5f74ea3811b76601582603d/report.json) | 25 cm | 31/32 | Invalid | 1.746955 ms | 29.9603 cm |
| [8335587e](../data/ranging/8335587ecb2643b0a58d52f5894e8f93/report.json) | 5 cm | 32/32 | Invalid | 1.039208 ms | 17.8224 cm |

The timing equivalent increases by 11.4271 cm, then returns to 0.7108 cm below the initial value. These values are not device-body distances. They depend on unknown self paths, device response, and selected correlation peaks. A 20 cm movement of the bodies need not change the mean cross-transducer paths by exactly 20 cm, but the geometry was not measured here, so the size of this response is not an accuracy result.

## Why the live reports were withheld

The first 5 cm capture triggered the added extra-event audit on three laptop slots. Those late matches sit about 202.04 ms after the main phone chirp, with only about 0.34% of its correlation amplitude. A similar tail occurs after every phone chirp, but only three cross the normalized-correlation threshold. The first phone self-arrival also makes the maximum clock residual 0.1516 ms, just above the fixed 0.15 ms limit.

The 25 cm capture has one such flagged slot. Its late match is about 163 ms after the main chirp. Its maximum clock residual is otherwise 0.0394 ms. Independent direct dot-product calculations agree with the stored correlations, so this is not a numerical normalization error. The recurring source-locked tails support investigating room or device response. Identical chirps cannot distinguish a reflection from a replay, and the audit should not imply that it has observed an independently played extra chirp.

The return capture contains 960 exact-zero phone samples from 1.217333 to 1.237333 seconds, between the first and second emissions. The following laptop chirps shift by about 20 ms in the phone timeline. The global clock model spreads the first-arrival discrepancy across the fit, producing a 14.621 ms maximum residual. The zero interval and timing jump together support a recording-timeline discontinuity. They do not identify the component responsible or prove whether samples were inserted or lost. Some paths also switch between correlation peaks about 0.25 to 0.27 ms apart.

All six WAVs contain the expected finite samples and pass the current amplitude checks. No hidden-page, microphone interruption, context suspension, route-change, or missing-worklet-block event was recorded. The return-run content anomaly therefore occurs despite continuous AudioWorklet counters. Further volume adjustment is not supported by this batch.

## What the exploratory calculation does

This calculation leaves every live report and gate unchanged. It retains the published detector's selected sample for every slot, including samples whose attribution was withheld. Within each source, it computes all pairwise slopes between receiver B and receiver A arrival times, takes the median slope across both sources, computes all eight four-arrival differences, and takes their median. Reference distances are used only to label the resulting rows. No emission or peak is manually substituted or excluded.

The estimated relative rates are 17.3614, 17.3611, and 18.2292 ppm. The return run still contains a first-pair equivalent near minus 320.5 cm and two remaining peak families around 17.8 and 22.5 cm. A robust median reduces their effect; it does not repair the recording or prove which arrival is direct. This estimator was selected after examining these failures and has not been independently validated. Its output is exploratory evidence for further development, not a replacement valid report.

The calculation uses the same four-arrival equation as the live analyzer:

`delta = (t_BA - t_AA) - (t_BB - t_AB) / rate_B_over_A`

`uncorrected_equivalent = 343 * delta / 2`

The full eight values and original artifact hashes are in the [machine-readable audit](benchmarks/2026-09-22-beepbeep-movement.json).

## Next engineering step

Use these existing recordings to develop and test two bounded changes before asking for more physical data:

1. Separate late matching tails from ambiguity in the arrival being timed. Preserve their evidence and the absence of acoustic source authentication. Test the behavior against both reflections and genuinely competing emissions, without tuning for the ruler label.
2. Detect recording-time discontinuities from signal content as well as block counters. Evaluate complete exchanges within stable timing intervals, with declared minimum evidence and peak-consistency checks. Do not silently stitch a time jump or discard data to obtain the desired distance.

Peak-family switching remains a separate bias to evaluate; selecting the strongest peak everywhere is not an established solution. Benchmark the proposed behavior on all saved captures and synthetic failure cases before changing live acceptance. No more captures are needed to diagnose the failure patterns in this sequence.

## Verification

Two Astra Max subagents independently inspected original PCM, capture metadata, and timing selections. All 36 original artifacts were hash verified and remain unchanged. No live code, threshold, report, or running server was changed during this audit.
