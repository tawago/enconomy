# Live capture diagnosis, 2026-09-21

> Historical record. Automated tests and regression gates were removed at the user's request on 2026-09-22. Old test commands below no longer apply; follow [the current workflow](../AGENTS.md).

The browser connection, sound exchange, recording, and screen wake lock work on the current laptop/Android pair. The original v2 trials failed echo recovery. The v3 changes below recover usable echo periods from those saved recordings, but both awake-screen touch trials still reject proximity. There is no successful live touch demonstration yet.

## Evidence

Both devices report an active screen wake lock and `page_hidden=false` in these full touch trials. Both report echo cancellation, noise suppression, automatic gain control, and voice isolation disabled.

| Recording path | T1 `d7428fad`, 6–12 kHz | T2 `d1708b45`, 4–9 kHz |
|---|---:|---:|
| Laptop to laptop, AA | 20/20 usable echo periods | 20/20 |
| Laptop to phone, AB | 1/20 | 0/20 |
| Phone to laptop, BA | 1/20 | 1/20 |
| Phone to phone, BB | 0/20 | 0/20 |

The T2 link test `40d8ad66` passed in both directions. The following full trial has strong direct chirps, no clipping on either device, and jointly assigned self/partner trains. Its failure reasons are exactly `AB_low_period_recovery`, `BA_low_period_recovery`, and `BB_low_period_recovery`.

The warning `possible_aec_suppression` is a heuristic based on missing selected self echoes. It does not establish that Android enabled echo cancellation. The T2 result also shows that screen sleep and clipping are not necessary for this failure to occur.

## What the offline experiments establish

The original v2 `alignment.select_periods` required an echo peak above the larger of three times the post-chirp median envelope and 2% of the search-window envelope maximum. Removing only the 2% floor in an isolated Python process changes both captures from WITHHELD to capture-valid REJECT. This identifies the floor as a cause of the low-recovery outcome. It does not establish that the extra selected peaks are reliable room echoes.

| Offline configuration | T1 score/verdict | T2 score/verdict |
|---|---|---|
| Original v2 production selection | -0.21793 / WITHHELD | 0 / WITHHELD |
| Remove only the 2% floor | 0.55241 / REJECT | 0.24637 / REJECT |
| Correct correlation indexing only | -0.03766 / WITHHELD | 0 / WITHHELD |
| Correct indexing and remove the floor | 0.04560 / REJECT | 0.11949 / REJECT |

The verdict threshold remained 0.78 in every experiment. The archived weak-link control `b933225d` remained WITHHELD in all four configurations. One control is insufficient to validate a new selector or its false-positive rate. The production server, thresholds, golden expectations, and original trial records were not changed by these experiments. Full diagnostic output is in `data/reports/2026-09-21-echo-ablation.json` locally.

## Separate indexing defect

The original matched filter used `fftconvolve(audio, reversed_template, mode="same")`. For an isolated 20 ms chirp whose known onset is 250 ms, its envelope peak and the reported raw `chirp_start` are both 260 ms. The code treats the middle of the chirp as its beginning and consequently drops its first 10 ms from the chirp spectrum. This is reproducible with a synthetic signal and does not depend on a distance label.

The original [Proximity-Echo paper, section IV-B](https://www.winlab.rutgers.edu/~yychen/papers/%28INFOCOM%2721%29%20Proximity-Echo%20Secure%20Two%20Factor%20Authentication%20Using%20Active%20Sound%20Sensing.pdf) describes selecting raw periods from the beginning of received chirps and echoes. Mapping correlation indices to those raw-sample onsets therefore needs an explicit convention. A full-convolution slice beginning at `len(template)-1` was tested offline as that correction. It did not resolve the failed captures by itself.

## Work identified before v3

1. Correct and test correlation-to-audio indexing with known chirp onsets and delayed copies. Account for the effects on narrow self-search windows, masks, compensation spectra, and pipeline provenance.
2. Replace or justify the 2% echo floor using measured noise and isolated-chirp controls. Test whether the newly admitted peaks are reproducible reflections rather than filter artifacts or noise. Do not select a cutoff merely because these touch trials pass capture validity.
3. Validate the candidate extraction on the saved touch recordings, archive controls, and simulated noise/alias cases before requesting another phone experiment. Existing goldens pin current behavior, so a changed algorithm needs reviewed, versioned expectations.

There are still no current-generation full distance trials with which to establish near/far separation. Passing the link test is evidence of audibility only.

Reproduce the unchanged live summaries with:

```bash
.venv/bin/python analysis/inspect_trial.py d7428fad
.venv/bin/python analysis/inspect_trial.py d1708b45
```


## V3 implementation and verification, 2026-09-22

The new extraction uses full correlation with index zero mapped to a raw chirp onset. It preserves the complete direct chirp and the 100 ms echo slice. A 20 ms chirp keeps the 25 ms direct period; archived 40 ms chirps now require 45 ms, so their remaining direct sound cannot become a false echo.

The old 2% direct-amplitude floor is replaced by a noise-model gate. For N eligible onset samples and median envelope m, the threshold is `m * sqrt(log(N / 0.001) / log(2))`, bounded below by float32 precision relative to the direct peak and a numerical epsilon. This uses a Rayleigh model for stationary Gaussian noise. The median estimates its scale, so 0.001 is a nominal per-search budget, not a general false-positive guarantee. Direct chirps also need to clear a noise gate.

Candidates must be natural envelope peaks, and their entire returned slice must avoid unrelated-emission masks. Masked peaks cannot suppress eligible neighbors during thinning. Searches include exact boundaries and enough trailing audio for a complete echo. Schema 8 logs each selection's failure reason, noise median and threshold; the feature and pipeline versions are v3. The original WAVs and trial records remain unchanged.

| Saved recording | AA | AB | BA | BB | v3 score | v3 verdict |
|---|---:|---:|---:|---:|---:|---|
| T1 awake `d7428fad` | 20/20 | 19/20 | 20/20 | 20/20 | 0.04559 | Valid REJECT |
| T2 awake `d1708b45` | 20/20 | 19/20 | 19/20 | 20/20 | 0.11948 | Valid REJECT |
| Earlier sleep-affected `d04313d2` | 20/20 | 12/20 | 19/20 | 13/20 | 0.35870 | Valid REJECT |

The acceptance threshold remains 0.78. These are offline re-scores, not new physical trials. Recovered periods can contain room response or repeatable hardware response; recovery alone does not establish proximity.

Known-onset tests cover three bands, weak delayed copies, direct-only recordings, silence, Gaussian noise, complete masks, truncated selector input, exact search boundaries, and 40 ms templates. They run in the quick startup regression. Independent review also checked 2,400 stationary white/correlated Gaussian noise cases, with and without a direct chirp, with no false echo selections in those cases. Transient noise bursts can still be selected as echo candidates. That limitation is outside the stationary-noise model, and a candidate alone is not a whole-trial ACCEPT.

Full simulation exposed a security failure. A transparent 5 ms audio relay scores 0.86918 and is accepted, with no aliased or swapped selections. Its weak self-echo was below the old 2% floor; recovering it exposes the relay's strong correlation. The relay security assertion remains unchanged and fails. Do not retune the cutoff to hide this result. The T3 relay also becomes capture-valid, but rejects at 0.71574. The overlapping-emission scene still withholds, now before its old spectral-similarity guard can operate. Those two older guard-specific assertions remain red as well. A green quick regression is therefore not a green security suite.

Next, refresh both device pages and run one full touch trial and one full 1 m trial with the same settings. Check echo recovery and both directional scores. If touch remains below threshold, the next problem is signature separation or capture hardware, not network access or the audio-link check. App packaging remains premature until repeated near/far trials work. Anti-relay protection is a separate unresolved requirement for any secure co-presence claim.

Reproduce the v3 re-score:

```bash
.venv/bin/python analysis/rescore_archive.py d7428fad d1708b45 d04313d2
.venv/bin/python -m unittest discover -s tests -p test_echo_selection.py
./run.sh regression --quick
./run.sh regression --full
```


## First live v3 distance pair, 2026-09-22

Both new recordings pass capture validity. They used the same actual 6–12 kHz, 20 ms, amplitude 0.35 configuration, despite both carrying the T2 hardware-tier label. The user intended T2. At the time of capture, the separate Hardware tier selector only changed that label; only Band preset or the sliders changed the emitted band. Preserve these original records and analyze them as 6–12 kHz data, not as a 4–9 kHz T2 test.

| Condition | Trial | AA / AB / BA / BB recovery | c_a | c_b | Mean score | Verdict |
|---|---|---|---:|---:|---:|---|
| Touch | `24aa9105` | 20 / 19 / 19 / 20 of 20 | 0.37333 | -0.12302 | 0.12515 | Valid REJECT |
| 1 m | `e7dbf584` | 20 / 19 / 19 / 19 of 20 | 0.35072 | 0.26315 | 0.30693 | Valid REJECT |

Offline replay matches both logged scores exactly. Both devices stayed visible with active wake locks and reported echo cancellation, noise suppression, automatic gain control and voice isolation disabled. Neither recording clipped. Both contain a phone weak-self-echo warning; the 1 m recording also has an unresolved independent sweep on the laptop. These warnings do not invalidate the capture. Neither trial has a fresh audio-link check attached.

Touch minus 1 m is -0.18178 for this pair. The farther trial scored higher, and both are below the unchanged 0.78 acceptance threshold. This confirms live extraction is functioning but does not demonstrate near/far discrimination. One trial per condition cannot estimate repeatability or accuracy, and a lower acceptance threshold would not fix this reversed ordering.

The next comparison should use the actual 4–9 kHz preset at both distances. The UI fix makes selecting hardware tier T2 apply that band, while still allowing later intentional custom-band edits. Confirm the displayed 4.0 and 9.0 kHz values before recording. Check the audio link, then run a full proximity trial at each distance with the same volume and orientation.


## Correct T2 pair and repeatability, 2026-09-22

Both latest full trials used the intended 4–9 kHz band with 20 ms chirps at amplitude 0.35. Both pass capture validity, recover 19–20 of 20 periods per channel, have no clipping, and keep both screens visible with active wake locks. Reported browser echo cancellation, noise suppression, automatic gain control and voice isolation are false. A matching passed link check is attached to both trials; the 1 m trial carries the preceding touch link check, not a newly measured 1 m link.

| Condition | Trial | c_a | c_b | Mean score | Verdict |
|---|---|---:|---:|---:|---|
| Touch | `68a5f87b` | 0.72466 | 0.73651 | 0.73058 | Valid REJECT |
| 1 m | `45cdc7cd` | 0.72517 | 0.53088 | 0.62803 | Valid REJECT |

Offline replay matches these logged scores. The 1 m rejection is expected; touch rejects because its score is below the unchanged 0.78 cutoff. The mean gap is +0.10255 in favor of touch, almost entirely from c_b. This is one observation per condition, not a validated classifier. The repository's runbook already requires per-setup separation before threshold tuning.

Splitting each full recording into its first and last ten emission pairs gives touch scores 0.73194 and 0.72459, versus 1 m scores 0.61926 and 0.60556. These are correlated subsets of the same recordings, not independent repeat trials or a confidence interval. They suggest the latest pair's ordering is not caused solely by one half of a capture.

Earlier genuine T2 touch recording `d1708b45` re-scores 0.11948. Its first and last ten-pair subsets score 0.15620 and 0.06374. These captures therefore cannot all be correctly classified by one threshold: accepting the low-scoring touch would also accept the latest 1 m sample. The earlier recording is a different session, so this does not isolate an unchanged-setup repeatability failure by itself.

However, two consecutive same-session touch link checks changed substantially. Failed check `3be5419e` has A-hears-B ratio 0.4365 and B-hears-A 1.3073; passed check `08f148e7` has 1.5337 and 0.8973. The user explicitly reports changing neither volume nor device position/orientation between them. The passing check clips 69 isolated laptop samples, whereas the failed check does not clip. Both later full trials are unclipped. Reported DSP flags and emitted chirp parameters are unchanged. These facts establish unexplained measurement variation; they do not establish OS echo cancellation or user error.

The next engineering step is to isolate changes in the saved waveforms, alignment, echo selection and microphone compensation. Keep the classifier threshold unchanged during that diagnosis. These inspected captures are development data. Any later calibration must be evaluated on separate reserved trials after the pipeline and threshold are frozen.


### Saved-waveform check of the consecutive link tests

Independent inspection confirms that the level change is already present in the recorded audio. Laptop phone-arrival matched peaks rise from a median 14.5251 to 72.0505, while laptop self peaks rise from 33.2770 to 46.9792. Raw PCM RMS across the eight physical arrivals independently rises from 0.07779 to 0.34007 for phone-to-laptop, a factor of 4.37; laptop self RMS rises from 0.18792 to 0.25002, a factor of 1.33. Every logged nonzero direct onset agrees exactly with the strongest full-recording correlation peak in its local -5 to +25 ms search, so a different sidelobe selection does not explain this link flip.

Granted capture settings and reported base/output latencies are identical. The passing link's phone WAV also shows a 20 ms timing step in late arrivals from both emitters, which slightly changes train support but does not explain the laptop amplitude change. The source of these recording changes remains unknown. OS processing, browser buffering, acoustic-path changes and warm-up are hypotheses, not established causes. A level change alone also does not establish why the scale-normalized proximity correlation changes between sessions.

These findings make recording repeatability the next issue to isolate before calibrating a decision threshold. No new distance sweep is needed to establish that the current recordings vary.
