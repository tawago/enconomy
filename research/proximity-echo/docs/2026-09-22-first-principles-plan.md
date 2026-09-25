# First-principles plan for 0–10 cm proximity

Date: 2026-09-22. Proposed measurement and validation plan, informed by three independent Astra reviews of physics, signal processing, and experimental design. No processing change or new physical experiment was performed for this review.

Implementation update, 2026-09-22: the separate `/ranging` diagnostic now records exact session-bound probes and continuous PCM with block metadata, detects arrival candidates, fits relative audio clock rate, and computes four-arrival timing. Synthetic math tests, capture and lifecycle tests, and a silent two-browser capture check pass. Physical accuracy and the body-gap decision remain unvalidated. See the [README](../README.md#new-timing-diagnostic) for collection and reanalysis steps. The assessment below describes the original echo pipeline at the time of the review.

The next milestone is a repeatable acoustic measurement that distinguishes the intended near range across specified environments. The current saved trials do not establish that milestone. An installable app can follow once the measurement passes a frozen validation test.

## Define what is being measured

Use the nearest gap between device bodies as the user-facing distance, measured with a ruler or spacer. Zero means the bodies touch. Record the locations of active speakers and microphones separately. Phone contact does not mean zero acoustic path length.

Start with named device pairs and an explicit placement gesture. Test environmental variation independently from support for arbitrary devices and orientations. A guided pose that works in several rooms is a useful scoped result. It does not establish arbitrary-pose support.

Positive examples must cover 0–10 cm, including the upper end. Negative examples must include distances just above 10 cm, not only 1 m. Measurement uncertainty makes a perfectly sharp boundary unrealistic. Return NEAR, FAR, or INCONCLUSIVE; characterize behavior around the boundary. Introducing a transition band would narrow the product claim and must be stated explicitly.

## What information does sound carry?

A recording depends on the emitted waveform, speaker response, propagation paths, microphone response, device processing, and noise. Distance is only one cause of change. Loudness alone cannot distinguish a nearby quiet source from a farther loud source. Echo similarity can also vary with room, orientation, obstruction, and device response.

A useful mathematical counterexample is a delayed, scaled copy: `H2(f) = a * exp(-i*2*pi*f*tau) * H1(f)`. Its normalized magnitude spectrum is unchanged even though its delay changes. This does not disprove the paper's empirical results; it shows why spectral similarity alone cannot uniquely determine distance. Its relation to the desired gap must be established with data.

Keep two analyses separate until their performance is measured:

- Reproduce the paper's echo comparison as a benchmark. It estimates proximity from compensated echo spectra. The published method compensates individual beep spectra before averaging; our current code averages first. Its evaluation uses 14–15 kHz, whereas the latest local captures use 4–9 kHz. Fixing calculation order alone does not make these recordings a replication of the original experiment. [Proximity-Echo, sections IV–V](https://www.winlab.rutgers.edu/~yychen/papers/%28INFOCOM%2721%29%20Proximity-Echo%20Secure%20Two%20Factor%20Authentication%20Using%20Active%20Sound%20Sensing.pdf)
- Add an independently derived travel-time diagnostic. Two-way sound exchange and self-recording can remove unknown emission scheduling times and recording start offsets. This principle was demonstrated by [BeepBeep](https://www.microsoft.com/en-us/research/publication/beepbeep-a-high-accuracy-acoustic-ranging-system-using-cots-mobile-devices/). It still needs validation on our hardware.

The second analysis provides a physically interpretable reference. Do not automatically combine its output with the echo score, or use one to relabel the other's failures.

## Minimum data contract

Each trial needs two continuous recordings. Each recording must contain both devices' probes, yielding four observable paths: A heard by A, A heard by B, B heard by A, and B heard by B.

| Save | Why it is needed |
|---|---|
| Original uncompressed PCM from both devices, including quiet intervals and complete probe tails | Re-run detection, inspect noise and clipping, and avoid committing to one feature representation |
| Exact probe samples, emitter identity, emission index, session identifier, and protocol version | Associate every arrival with its source and exchange |
| Capture sample rate, channel/route, per-block sample positions or audio timestamps, discontinuities and dropped-frame information | Establish continuity and diagnose clock-rate differences; callback wall time is not the acoustic arrival time |
| Playback configuration, output level, device/OS/browser versions, requested and reported audio processing settings | Track hardware and capture changes without assuming a requested setting proves the physical signal is unprocessed |
| Ground-truth body gap, speaker/mic geometry, orientation, grip, case, surface, room, noise condition, session and placement ID | Separate distance effects from nuisance variables and prevent train/test leakage |
| All candidate arrival times, confidence measures, selected windows, per-beep features, final decision and failure reasons | Explain outcomes and retain failed attempts |

Capture from before the first emission until after the last usable tail. Treat sample-rate conversion as an explicit derived operation and retain the originals. More chirps improve a measurement within a trial; they do not create independent physical trials.

## Sound and processing logic

1. Choose a comfortable probe with adequate usable bandwidth on both devices. Use short, tapered, known signals. A pleasant cue is compatible with sensing if it retains useful timing structure and frequency coverage. A single steady tone has timing ambiguity. Choose the band using measured response and background noise, then freeze it for evaluation.
2. Make the two emitters distinguishable by their signal templates, not inferred closeness. Validate template cross-correlation through the real speakers and microphones. A fresh session-bound sequence can distinguish exchanges and detect stale recordings, but does not by itself stop live relays.
3. Record both devices continuously during alternating emissions. Leave enough separation to distinguish the probes and relevant tails. Use the same identified pair of emissions when comparing the two recordings.
4. Check recording quality before estimating proximity: missing samples, clipping, weak partner signal, wrong source, overlapping events and unstable timing. An unusable capture is INCONCLUSIVE. It is not evidence that the devices are far apart.
5. Matched-filter each recording against the correct templates. Preserve the delay profile. For ranging, estimate the earliest credible direct arrival with a noise-aware uncertainty estimate; the strongest peak can be a reflection. Ambiguous or obstructed paths must remain unresolved unless a tested method handles them.
6. Compute four-arrival timing per exchange, estimate relative clock-rate error, and account for self-path and detector bias. Aggregate repeat exchanges robustly and expose their spread. Never choose event assignments because they produce the desired short distance.
7. In a separate echo branch, pair the corresponding per-beep spectra, apply microphone compensation before averaging, and report unusable spectral regions. Compare this branch with the existing average-first calculation on the same saved captures. This is an ablation, not a reason to select whichever accepts touch.
8. Apply a frozen decision rule with a measured uncertainty policy. A narrow interval only supports a close decision after the mapping from acoustic paths to the user-facing gap is validated. Do not issue a close verdict when uncertainty crosses the boundary.

## Four-arrival timing derivation

Let `t_AA` be the arrival of A's probe at A, and similarly define `t_AB`, `t_BA`, and `t_BB`, with emitter first. These are local recording times; clocks need not have the same origin. Define the elapsed intervals within each recording:

```text
Delta_A = t_BA - t_AA
Delta_B = t_BB - t_AB
```

For stable clock rates, the same two emissions, and correctly identified direct air paths, cancellation of the unknown emission times gives:

```text
c * (Delta_A - Delta_B) = d_AB + d_BA - d_AA - d_BB
D_acoustic = (d_AB + d_BA) / 2
           = [c * (Delta_A - Delta_B) + d_AA + d_BB] / 2
```

This is a derivation for the average cross-transducer path length, not automatically the nearest body gap. The self paths cannot be ignored at centimeter distances. Structure-borne self sound, filter delay, and source-dependent arrival estimation can require measured bias calibration instead of a geometric correction. Arbitrary orientation leaves the body-gap mapping underdetermined with this observable alone.

All four arrival estimates matter. A delayed cross arrival increases the range estimate, but a delayed self arrival is subtracted and can decrease it. Reflections therefore cannot be assumed to produce only conservative overestimation. Inspect mechanically isolated placement as well as shared-table contact, and compare rotations at the same body gap.

Using 343 m/s as an illustrative sound speed, 10 cm is about 0.292 ms of one-way air travel, roughly 14 samples at 48 kHz. Sample spacing is not measurement accuracy. Bandwidth, signal-to-noise ratio, multipath, geometry and systematic delay matter. Relative clock error also survives the cancellation: a 100 ppm mismatch over a 0.5 s emission gap introduces about 8.6 mm of apparent range error. Shorter paired gaps or independently estimated rate correction must fit the timing error budget.

## What can be reused, and what is missing?

The repository already retains paired WAVs and waveform parameters. These are useful development data. The latest archive also contains unexplained changes in recorded level, which warrant capture diagnostics but do not by themselves explain a Pearson-score change.

- `challenge_generator.py` uses identical fixed probes; its seed is a log identifier. Source identification therefore depends on inference from timing and train structure.
- `static/app.js` saves continuous sample chunks but lacks a per-block continuity record. Its first callback timestamp does not establish sub-millisecond acoustic timing.
- `feature_extraction.py` ranks candidate assignments partly by absolute round-trip residual and uses the strongest selected peaks. Its `round_trip_ms` and `chirp_start` outputs cannot simply be relabeled as independently measured distance.
- `compensation.py` averages spectra before the nonlinear compensation calculation.
- Existing labels mainly describe touch, 30 cm, and 1 m. They lack the geometry and close-negative coverage needed for a 10 cm boundary.

The current campaign's mean-score separation criterion is insufficient for this new milestone. Two heavily overlapping distributions can have different means. The existing dashboard warns about optional stopping, but neither those cautions nor statistical significance establish usable classification.

## A bounded data collection plan

Do not start a large campaign until recording continuity and source attribution are reviewable.

First, use saved WAVs to compare compensation order and inspect four-arrival timing without accepting the current assignment as ground truth. Synthetic known-delay signals can check indexing and bias, but do not validate the physical devices.

Before moving devices for a sweep, check repeated independent captures at one unchanged placement. A restart must not produce unexplained shifts that exceed the measurement error budget. This recorder checkout is development work.

Then run a diagnostic pilot with one pair, one defined pose, and a measured setup. A proposed fixed budget is 32 attempts: four randomized placement blocks at 0, 5, 10, 11, 15, 20, 30, and 100 cm. Reset placement between attempts and restart capture in more than one session. Keep every failure. This pilot diagnoses signal quality, timing-versus-distance behavior, and feature overlap; it is calibration data, not the final demonstration result.

After the pilot, freeze waveform, calibration, detector, threshold, retry policy and code version. A proposed bounded validation campaign is 120 attempts over two named device pairs and three environments, 20 attempts per pair-environment combination. Use a furnished room, a more reverberant space, and a noisier/open space, with the precise environments recorded. Reserve environments and sessions not used for threshold selection. If only one pair is available, report environmental results for that pair and make no cross-device claim.

Each combination contains 10 near and 10 farther attempts. Collect two attempts at each near distance of 0, 2, 5, 8 and 10 cm, and two at each farther distance of 11, 15, 20, 30 and 100 cm. Preassign any supported pose/grip variations and randomize order. Room-specific threshold tuning is prohibited during validation. A phone-to-phone product needs phone-to-phone evidence; laptop-to-phone results alone do not establish it.

Measure ground-truth uncertainty as well as the nominal gap. If the measured interval straddles 10 cm, retain the observation as boundary data and report that ambiguity separately. Do not choose its label after observing the output or count it as a resolved pass in the gate below. A remaining unresolved boundary prevents a strict 10 cm claim. At the current roughly 22-second capture duration, 120 attempts alone contain about 44 minutes of audio, before setup and repositioning; stationary results also do not establish reliability during motion.

One proposed stringent demo gate is at least 59 of 60 near attempts accepted, zero of 60 farther attempts accepted, and no more than one INCONCLUSIVE result per 20-attempt combination. These are engineering targets, not achieved results or universal guarantees. Publish counts at each distance and for each pair/environment, not only pooled success.

Count every scheduled attempt in the appropriate denominator. Publish near acceptance, false-near decisions, correct far decisions, inconclusive results and latency. Any automatic retry policy belongs inside the evaluated user attempt. Do not replace failed trials until the sample looks favorable.

Under independent binomial assumptions, zero false accepts in 60 trials gives a one-sided 95% upper bound of about 4.87%; 59 near accepts out of 60 gives a lower bound of about 92.34%. Even zero errors in a 10-trial subgroup leaves an upper error bound of about 25.89%. Shared rooms, devices and sessions limit those assumptions and generalization. Use these as uncertainty illustrations, not assurances about every environment. [NIST guidance on proportion confidence intervals](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm)

If close-boundary errors or environmental failures remain, narrow the supported conditions transparently or change the measurement method. Do not declare success from touch-versus-1 m separation alone.

## Immediate next engineering deliverable

A diagnostic recorder/report that shows the two raw recordings, the four independently attributed arrivals, continuity and clock diagnostics, geometry-corrected timing uncertainty, and both echo calculations for the same trial. Build this before asking for another long distance campaign.

This milestone concerns cooperative device proximity. Resistance to malicious clients and real-time relays is a separate test. Neither an accurate range nor a cryptographic wrapper alone establishes that two distinct people held the devices.
