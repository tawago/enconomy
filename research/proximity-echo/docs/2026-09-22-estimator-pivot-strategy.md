# Estimator pivot decision

The bounded differential-ranging attempt failed its offline gate on the two untouched recordings, and independent numerical review confirmed the rejection. That result applies to this whole-channel translation model. The earlier recommendation to stop browser acoustic development and require external reference capture went beyond the evidence. The project remains acoustic-only, with a BeepBeep reference implementation next. See the [paper reproduction review](2026-09-22-paper-reproduction-reset.md).

The new implementation is an offline benchmark. It changes no live estimator, threshold, or original artifact. Its [reviewed output](benchmarks/2026-09-22-differential-left-repeats.json) retains the rejected fits and input/source hashes.

The [two untouched repetitions](2026-09-22-left-repeat-results.md) establish clean, repeatable responses within each run. They still contain 24 and 21 ambiguous arrivals. The [four-path analysis](2026-09-22-channel-cancellation.md) shows that stable responses can have incompatible delays in different frequency bands. All eleven captures have the same 5 cm body-gap label, with placement changes among earlier captures. They provide no measurement of distance sensitivity.

## Why a more elaborate absolute fit is insufficient

Write the observable four-path ratio at placement g as

\[
R_g(f)=F_g(f)e^{-\mathrm{i}2\pi fT_g}.
\]

Here T is the proposed combination of acoustic travel times and F contains everything that the model has not identified, including multipath and direction-dependent or structure-borne response. For any proposed delay change delta, the transformation

\[
T'_g=T_g+\delta,\qquad F'_g(f)=F_g(f)e^{+\mathrm{i}2\pi f\delta}
\]

leaves R unchanged. This is an algebraic ambiguity in this unconstrained model. More repeated probes reduce noise without removing it.

A joint fit of clocks, channels, and distance becomes informative only after it imposes independently justified constraints on F. A selected sparse path count, a smoothness penalty, or an earliest fitted component can choose one answer without establishing its physical identity. Such a model is worth revisiting after calibrated geometry and movement data constrain it. It is not the next implementation.

This does not prove that acoustic ranging is impossible. BeepBeep demonstrated acoustic ranging and explicitly addressed transducer distortion and competing arrival peaks. Its results also show why success depends on the devices and propagation conditions. They do not validate this hardware at a 10 cm body-gap boundary. [Peng, Shen, and Zhang, sections 5 and 6](https://www.cs.purdue.edu/homes/chunyi/pubs/peng-tecs12.pdf)

## What the differential estimator changes

For a fixed reference placement g0, form

\[
Q_g(f)=\frac{R_g(f)}{R_{g0}(f)}
=\frac{F_g(f)}{F_{g0}(f)}e^{-\mathrm{i}2\pi f(T_g-T_{g0})}.
\]

If the residual channel factor is unchanged except for gain and a constant phase, its unknown fixed delay cancels. Fit one delay and a phase intercept to Q, using a frozen band and label-independent weights. Treat this as a change in the average cross-transducer path length,

\[
\Delta D=\frac{c}{2}\Delta T,
\]

provided both self paths remain unchanged. A 1 cm change in D corresponds to about 58.3 microseconds in T at 343 m/s.

The method reuses exact probes, continuous PCM, integrity rejection, whole-response clock tracking, restored excerpt origins, and all four recorded paths. It replaces the absolute onset decision with comparison to an explicitly identified reference recording. Each capture must first use its own estimated relative clock rate and a common frequency grid referenced to A's nominal clock. Changes in A's absolute sample rate between runs remain a nuisance to bound. Independently aligning away the four between-run delays would erase the wanted displacement.

Fixed orientation alone does not make F constant. A wall reflection and a direct path can change length by different amounts when a device moves. Contact can change a self path. An unchanged four-path ratio at one placement is therefore only a necessary test. It does not establish that the ratio is sensitive to distance.

A known baseline gap plus a validated, monotonic geometry function could later convert relative acoustic length into gap. For example, measured transducer coordinates define D(g) as the average of the two cross-path lengths. Inverting D(g) is justified only where the movement experiment supports that mapping. Adding delta D directly to a body-gap label assumes geometry that these recordings have not established. A baseline that needs the devices already placed at a known gap is also a product constraint.

A simple geometric example shows the issue. With a fixed 15 cm lateral offset and cross-path length D(g) equal to the square root of 15 squared plus g squared, moving the body gap from 0 to 10 cm changes the acoustic length by only 3.03 cm. Even an exact touch baseline does not make acoustic displacement equal body-gap displacement.

## Alternatives and their decision points

| Approach | Decision now | What must change |
|---|---|---|
| Absolute joint channel and distance fit | Do not pursue next | Obtain independent geometry or transfer-response constraints that remove the delay ambiguity. |
| Differential four-path ratio | Offline benchmark failed; do not run the physical block | Independent physical information must justify reopening this model. |
| Wider usable audio band with native capture | Do not start a general app rewrite | First demonstrate usable extra acoustic bandwidth or a reproducible browser capture defect that native capture fixes. Preserve the same benchmark so improvement is measurable. |
| Independent reference microphones | Optional diagnostic, not a demonstrated prerequisite | A calibrated fixture could separate propagation from device processing if the paper-based baseline needs that investigation. |

Wider acoustic bandwidth can separate some overlapping responses. Raising the sample rate or moving the same 4–9 kHz signal into a native app does not add that bandwidth. Native access can expose audio-source controls, but Android documents that unprocessed input is device-dependent and can fall back to default behavior. [Android audio documentation](https://developer.android.com/media/platform/mediarecorder)

## Freeze these go/no-go criteria

The numerical limits below were proposed engineering requirements for a 1 cm measurement budget. They are not the implementation's thresholds and are not confidence intervals inferred from two recordings. They describe what would have been required before a movement experiment. Do not loosen requirements to accept this data.

1. The offline implementation must recover known injected differential delays, including negative delays, within 1 microsecond through fixed multipath responses and independent clock rates. It must preserve the answer when extraction origins change. A changed-multipath example that violates the pure-delay model must fail the fit checks. Synthetic delay injection validates the implementation, not physical distance.
2. Use the two untouched runs as the only existing zero-motion test. The full-band result must be within 5 mm of zero equivalent acoustic displacement. Low- and high-band estimates, and disjoint exchange subsets, must agree within 5 mm. Apply the same limits to valid window-margin variants. Preserve every failing comparison.
3. Require weighted phase RMS at most 0.2 radians for the differential pure-delay fit. Reject a competing local delay optimum separated by at least 1 cm equivalent displacement if its fit coherence is at least 95% of the best optimum. Retain a sufficiently broad delay search to reveal alternatives; do not constrain it using the 5 cm label. These checks bound model disagreement, not systematic error.
4. Integrity failures, an unavailable clock fit, or insufficient usable frequency support make the result inconclusive. Freeze noise masks, frequency coverage requirements, bands, windows, and aggregation in the benchmark before a movement test. A required comparison that cannot be evaluated does not pass.

These gates define a bounded experiment for this differential model. They are not necessary conditions for every acoustic estimator, and their relationship to physical distance error is uncalibrated. Preserve the failed result rather than loosening its gates. Paper-based arrival detectors and echo comparison remain separate experiments.

## Reviewed differential result and implemented gates

The separate [offline implementation](../analysis/differential_ranging.py) declares its own gates before evaluating the untouched pair. These include fit coherence at least 0.99, full/subband delay disagreement at most 10 microseconds, exchange-pair spread at most 10 microseconds, leave-one-out deviation at most 3 microseconds, channel coherence at least 0.98, and alternative-peak ratio below 0.90. Its integrity and frequency-support requirements also apply. These are engineering checks, not physically calibrated confidence levels.

The reviewed output for baseline `6ba25fd9` and current `428ab971` rejects the comparison. Its public delay, absolute distance, and body gap are null. The exploratory full-band fit is +31.191 microseconds, but low and high bands give -2.699 and -15.392 microseconds. Full-band phase RMS is 0.3615 radians and fit coherence is 0.9364. The 64 exchange comparisons have only 7.673 microseconds of spread, showing why repeated consistency alone does not rescue the model. These comparisons reuse eight exchanges from each recording and are not 64 independent recordings. The result fails the implementation's coherence and frequency-agreement gates, and also the proposed 0.2-radian requirement above.

Independent review verified clock scaling, phase signs, template cancellation, and restoration of window origins. Review also fixed a search-edge ambiguity bug: the delay search now retains strong competitors at its endpoints. The test preserves a frequency comb with aliases at those endpoints. This correction did not change the real-data rejection or loosen any gate. The proposed five-placement block below fails its prerequisite and should not be scheduled. This is failure of the tested pure-delay differential model on the pair, not proof that all acoustic approaches are impossible.

| Independent check | Result |
|---|---|
| Continuous synthetic signals with competing echoes, different receiver clocks and independently shifted window origins | Expected 80 microseconds; recovered 79.99999848 microseconds. |
| Change excerpt preroll from 10 ms to 5 and 15 ms | Both reject the same two model checks; raw fits are +31.952 and +31.886 microseconds. |
| Perturb current capture's relative clock correction by -5 and +5 ppm | Both reject the same two checks; raw fits are +28.629 and +33.953 microseconds. |
| Reverse the real baseline/current order | Raw fit becomes -31.190549 microseconds with the same rejection. |
| Compare each real recording with itself | Both return numerical zero with no model-check failures. This is an algebra check, not an independent physical repetition. |

The new eight-test module also checks full-waveform clock dilation, dispersive filters, a stronger reflected path, a known 114-microsecond combined delay change, independent emission epochs, zero motion, missing probes, capture steps, changed response shapes, nonfinite samples, and ambiguity rejection. A pure-delay nuisance test explicitly demonstrates that a passing channel-change fit cannot distinguish a physical movement from an identical device-delay change. The returned physical-validation flag always remains false.

`LC_ALL=C ./run.sh ranging-test` passed all 78 Python and 22 Node tests. Hash checks confirmed that all 132 original capture artifacts, the legacy trial log, and golden data remain unchanged. The existing live server and distance verdicts were not modified. Software tests do not resolve the separate known legacy relay failure.

## Conditional physical block, currently not reached

Use one named device pair, a marked translation axis, fixed orientation, fixed audio settings, and independently measured speaker/microphone positions. Keep hands off during capture. Take five recordings at body gaps 5, 0, 10, 15, and 5 cm, in that order. The opening 5 cm recording is the new session's sole reference. The closing 5 cm recording tests return to baseline. Keep these labels outside the estimator and do not refit a slope or offset using the four test recordings.

Before capture, calculate the predicted change in D from geometry and a stated sound-speed assumption. Pass only if all four test recordings meet the frozen quality and differential-fit checks, every measured change is within 1 cm of its prediction, the order follows the predicted geometry, and the closing reference is within 5 mm of zero. Include geometry and sound-speed uncertainty in that budget. An inconclusive required placement fails this small feasibility block. Do not replace failed recordings by repeating placements until they succeed.

This five-recording block tests displacement sensitivity and reversibility on one setup. It cannot establish a 0–10 cm classifier, arbitrary placement, generalization across rooms or devices, or a low false-accept rate. Those require subsequent held-out placements, especially around the boundary. A preselected mapping that cannot distinguish 10 cm from nearby larger gaps must narrow the product claim or be rejected.

If this conditional block fails, stop this differential model's experiment. That would not stop acoustic work using separately justified waveform, arrival-detection, calibration, or echo-classification methods.

## Optional reference-capture diagnostic

Reference instrumentation could help if a paper-based baseline needs independent timing evidence. Two reference microphones recorded by one shared-clock stereo recorder or audio interface would need relative phase/delay calibration and documented positions beside the selected transducers. Retaining device PCM simultaneously could help separate device input behavior from propagation. A shared clock alone does not remove microphone, channel, or geometric bias. These saved results do not establish that this equipment is required.

If reference capture becomes useful, its offline importer should retain reference PCM, calibration, transducer coordinates, and frame origins. A controlled displacement block could then compare the device estimator with independently measured arrival changes. Native capture is another implementation choice to evaluate through a targeted comparison, rather than assuming it solves the failure of this phase model.

The intended 0–10 cm result still needs a justified mapping to device gap and held-out room changes. A per-placement differential baseline is insufficient. The next test of commodity-device feasibility is the paper-based baseline described in the reproduction review.

Acoustic ranging accuracy and resistance to an active relay remain separate claims. Bind any later measurement to the fresh session and test the stated adversary separately.
