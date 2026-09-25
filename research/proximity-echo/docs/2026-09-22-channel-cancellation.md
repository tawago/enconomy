# Four-channel cancellation on the first captures

> Historical record. Automated tests and regression gates were removed at the user's request on 2026-09-22. Old test commands below no longer apply; follow [the current workflow](../AGENTS.md).

The four-channel complex ratio can remove shared speaker and microphone filters. The existing recordings do not support treating its phase as one acoustic travel time. Two trials have stable phase responses across their eight exchanges, but different frequency bands imply incompatible delays. No distance label was used to choose a band, peak, window, or clock rate. This work changes no production estimator, thresholds, or original artifacts.

## What cancels

Let the first channel index denote the emitter and the second the receiver. After expressing both recordings on A's nominal sample-clock scale and restoring the origins of all extraction windows, write

\[
G_{ij}(f)=S_i(f)M_j(f)P_{ij}(f)
 e^{-\mathrm{i}2\pi f(E_i+B_j)}.
\]

Here, \(E_i\) is the unknown emission epoch, \(B_j\) is a fixed capture offset, and \(S_i\), \(M_j\), and \(P_{ij}\) are the speaker, microphone, and propagation responses. This assumes separable transducer responses and stable receiver processing between the two emissions. Then

\[
R(f)=\frac{G_{AB}(f)G_{BA}(f)}{G_{AA}(f)G_{BB}(f)}
 =\frac{P_{AB}(f)P_{BA}(f)}{P_{AA}(f)P_{BB}(f)}.
\]

The unknown epochs, fixed capture offsets, and separable transducer filters cancel, including their all-pass components. The two emissions can use different exact templates. Each template occurs once in the numerator and once in the denominator, so the same ratio can be formed from their recorded spectra without dividing by the template spectrum. Exact session templates remain necessary to identify the emissions and locate their extraction windows.

For pure paths \(P_{ij}=a_{ij}e^{-\mathrm{i}2\pi f\tau_{ij}}\), with frequency-independent phase in \(a_{ij}\),

\[
-\frac{1}{2\pi}\frac{d\arg R}{df}
=\tau_{AB}+\tau_{BA}-\tau_{AA}-\tau_{BB}.
\]

For general paths this is a combination of group delays, not a direct-path arrival time. Group delay is the negative derivative of unwrapped phase. [SciPy documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.group_delay.html)

Multipath, directional phase response, and structure-borne self coupling remain inside \(P\). A residual linear-phase factor is indistinguishable from additional travel time. Even a straight phase curve cannot prove an unbiased distance without an independent physical check. Neither magnitude-only equalization nor an assumed minimum-phase response resolves an unknown residual all-pass delay.

If all four delays are validated air-path times, then

\[
\frac{c\,\Delta\tau+d_{AA}+d_{BB}}{2}
=\frac{d_{AB}+d_{BA}}{2}.
\]

This is the average of two speaker-to-microphone cross-path lengths. It is not the minimum device-body gap. The self-path correction and the locations of active transducers are unknown in these captures. BeepBeep's experiments used one selected speaker and calibrated the self speaker-to-microphone distance. [Peng, Shen, and Zhang, 2012](https://www.cs.purdue.edu/homes/chunyi/pubs/peng-tecs12.pdf)

## Clock and window handling

Use \(r_A=1\) and \(r_B\) equal to the relative recording rate B/A. A sample at frame \(n\) on receiver \(j\) has time \(n/(f_s r_j)\) on A's nominal clock scale, apart from an unknown constant offset. Both the spectral frequency grid and window origins must use this rate. Correcting only the long interval between probes leaves their spectra on different frequency scales.

If a local Fourier transform begins at frame \(w_{ij}\), define \(u_{ij}=w_{ij}/(f_s r_j)\). Its four-way ratio needs the correction

\[
R=R_{\mathrm{window}}\exp\{-\mathrm{i}2\pi f
[u_{AB}+u_{BA}-u_{AA}-u_{BB}]\}.
\]

Centering four windows on independently selected lobes without this correction inserts those selected delays into the result. With the correction, a coarse detection is only a window locator. It is not an accepted onset measurement. The window must contain the relevant full received probe and its response tail.

Repeated observations also allow clock tracking without choosing an arrival lobe. For each emitter, form the receiver ratio \(D_k=Y_{B,k}/Y_{A,k}\), with origins restored. Compare \(D_k\) with an earlier same-emitter ratio. A stationary channel gives a delay trend caused by relative sample-clock drift. Fit the two emitter groups with a shared rate and separate intercepts; check each group's rate independently and reject steps or changing channel shape. A changing path can still resemble clock drift. Playback schedule times do not establish physical clock alignment.

## Exploration and results

The temporary scripts are `/private/tmp/channel-cancel-explore.py` and `/private/tmp/channel-cancel-clock.py`. Run from the project directory:

```bash
cd /Users/takahiro_ogawa/dev/enconomy/research/proximity-echo
.venv/bin/python /private/tmp/channel-cancel-explore.py
.venv/bin/python /private/tmp/channel-cancel-clock.py
```

These scripts are exploratory and have not received production validation. They use original v1 detections as coarse window locations. They do not restore the v1 onset decisions or bypass v2 rejection. The first script uses the old v1 relative clock rates for the first three trials. For the known discontinuous last trial it uses an explicitly assumed 20 ppm rate only to inspect the failure, not to produce a valid result.

The first script evaluates local recorded spectra at a common frequency grid using `scipy.signal.zoom_fft`. It uses 4.25–8.75 kHz at 31.25 Hz spacing, initially 5 ms before the coarse location and 25 ms after the 32 ms probe. It combines phases by multiplication and conjugation, avoiding division by small denominators. It gates bins against a background-noise spectrum, caps their weights, restores origins, and searches a ±2 ms delay range while allowing an arbitrary constant phase. This is a diagnostic model fit, not a calibrated uncertainty calculation.

| Trial | Full-band best-fit delay across 8 pairs | Phase RMS after delay fit | Subband delay medians |
|---|---|---|---|
| `5b79b0d2` | −146 to −145 µs | 0.769–0.776 rad | +87, −282, +125 µs |
| `550fb0db` | +296 to +298 µs | 0.647–0.668 rad | −0.5, +519.5, +169.5 µs |

The subbands are 4.25–5.5, 5.5–7.25, and 7.25–8.75 kHz. The full-band phase-fit coherences are approximately 0.729 and 0.805. These quantify agreement with the fitted phase line, not magnitude-squared coherence or measurement confidence. Alternative delay peaks remain, near +182 µs for `5b79b0d2` and −29 µs for `550fb0db`.

Changing the leading margin to 2, 5, or 10 ms and the tail margin to 5, 10, 25, 50, or 80 ms changes the median full-band fits by only about 1–2 µs. The large subband disagreements remain. This argues against the extraction boundary being their principal cause. Stable estimates from one chosen band do not establish physical accuracy.

The second script independently compares same-emitter receiver ratios at nominal equal sample rates. It estimates their relative delay changes, then fits those changes against elapsed capture time. Its 0.5 µs search grid and residuals describe this numerical comparison, not absolute timing accuracy.

| Trial | Rate from A emissions | Rate from B emissions | Delay-trend RMS, A / B |
|---|---|---|---|
| `5b79b0d2` | 19.602 ppm | 19.487 ppm | 0.25 / 0.22 µs |
| `550fb0db` | 19.787 ppm | 19.548 ppm | 0.51 / 0.21 µs |
| `28487e02` | 10.570 ppm | 12.440 ppm | 16.35 / 22.27 µs |

The two stable trials have phase-shape comparison coherence around 0.993–0.999. The first trial falls to 0.634–0.875 and has changing channel shape, so its fitted rate needs caution. For `efb2b564`, both emitter groups independently show an approximately 20 ms step between observations of e06 and e07, consistent with the known silent span. A single drift fit is invalid there. Do not repair that capture by subtracting a fitted step.

## Reusable response inspection

`analysis/inspect_ranging_channels.py` provides an independent, retained implementation. It reads only exact protocols and original WAVs, not previous reports, clock fits, or distance labels. It aligns full regularized channel responses within each path and fits a common relative clock rate with separate emitter offsets. Its phase-ratio origins are arbitrary, so only shape and band disagreement are interpretable, not absolute delay. This differs from the origin-restored temporary experiment above.

```bash
.venv/bin/python analysis/inspect_ranging_channels.py --self-check
.venv/bin/python analysis/inspect_ranging_channels.py --output /tmp/ranging-channels.json
```

| Trial | Relative rate | Trend RMS | Rate in low / high band |
|---|---:|---:|---:|
| `28487e02` | 14.70 ppm | 20.42 µs | 24.11 / 5.85 ppm |
| `5b79b0d2` | 19.65 ppm | 0.24 µs | 19.75 / 19.58 ppm |
| `550fb0db` | 19.73 ppm | 0.62 µs | 19.70 / 19.52 ppm |
| `efb2b564` | Invalid global fit | 4.93 ms | A step model finds 19.9997 ms at e07 |

The low and high bands are 4.25–6.25 and 6.25–8.75 kHz. Across the four paths in each of the two stable trials, median complex response coherence is 0.9824–0.9990. Training on seven probes predicts 99.40–99.91% of the eighth probe's regularized in-band waveform energy after fitting a delay and complex gain. This tests response-shape consistency, not independent arrival accuracy. The comparison excludes out-of-band raw energy and does not identify a direct path.

For `550fb0db` B-to-A, deconvolution retains lobes 0.2708 ms apart at amplitude ratio 0.926. Phase-only filtering also retains alternatives and introduces stronger alternatives on A-to-A. No route, lobe, or band was selected to obtain a desired distance.

The synthetic self-check recovers fractional shifts through a two-tap response within 1.43e-6 samples and an injected 23 ppm rate within 1e-9 ppm. These are numerical checks only. Output JSON includes protocol/WAV hashes and records that physical timing is unvalidated.

## Multiple active speakers

The playback code used for the first four captures constructs a one-channel buffer and connects it directly to the destination in `static/ranging-audio.js`. This is still the default mode. Web Audio's normal mono-to-stereo speaker mixing copies the input to both output channels. This establishes the software mixing rule, not which physical transducers the operating system activates. [Web Audio specification, channel mixing](https://www.w3.org/TR/webaudio-1.0/#channel-up-mixing)

With multiple active speakers, the channel instead contains

\[
G_{ij}\propto M_j\sum_{\ell}S_{i\ell}P_{i\ell,j}.
\]

The weighted sum depends on receiver position. It generally cannot be factored into one receiver-independent speaker response and one pure propagation delay. Microphone arrays, beamforming, and direction-dependent processing pose a similar problem. Two speakers playing the same mono probe cannot be separated from their aggregate recordings alone.

The observed 0.25–0.31 ms lobe separations correspond to approximately 8.6–10.6 cm of acoustic path difference at 343 m/s. Multiple speakers are one plausible explanation, alongside reflections and filtering. These recordings do not identify the cause.

Before a distance sweep, request three captures at one unchanged placement and volume: both output channels, left only, and right only. Use an explicit two-channel buffer with zeros in the unused channel, record the selected route and destination channel configuration, and inspect whether the received response actually changes as expected. Keep both devices supported and motionless. Physical speaker isolation remains an empirical check because output routing can remap channels.

The browser now provides **Default mono**, **Left only**, and **Right only** on each device. The selected setting is frozen before readiness, preserved in uploads and reports, and displayed in saved views. Single-channel modes require a stereo destination. Observable output-layout or sink changes abort while retaining partial PCM. The microphone node uses discrete channel selection so extra delivered channels cannot silently mix into the declared first input channel. The exact three-run instructions are in the README.

Validation covered 61 Python and 19 Node contracts, a two-browser synthetic silent capture with different modes on A and B, saved-report routing labels, and a 393-pixel mobile layout. Offline browser rendering verified that default mono reaches both output channels, single-channel modes leave the other channel at zero, and a stereo microphone input preserves channel 0. These checks used no physical microphones or audible playback.

## Minimal next estimator and failure gates

1. Keep the current recording-integrity checks. Decode and verify the exact session templates, identify each emission, and retain coarse windows plus their original frame origins.
2. Track repeated complex receiver ratios to estimate a common relative clock rate. Reject discontinuities, disagreement between the emitter groups, and changing response shapes before computing a timing result.
3. Evaluate all four channels on one frequency grid referenced to A's nominal clock. The common absolute clock scale remains uncalibrated. Preserve origin phase, mask weak or near-null bins, and retain the complex ratio and its per-pair variation.
4. Fit a delay with a free phase intercept. Report the full-band residual, alternative optima, subband agreement, sensitivity to extraction windows, and held-out-probe consistency. Do not infer coherence from a single Fourier product.
5. Withhold a travel-time interpretation when a pure-delay fit fails. Even a successful fit remains a channel-delay diagnostic until controlled distance changes and known transducer geometry test its physical slope and offset.

The existing data can test numerical cancellation, clock stability, window dependence, probe-to-probe consistency, and pure-delay fit failure. They cannot validate the separable-transducer assumption, identify the direct air path, or establish a body-gap decision. After the output-channel intervention, controlled distance changes at fixed orientation can test whether the delay changes by the predicted cross-path difference divided by sound speed. Absolute distance and a body-gap threshold require further geometric calibration and held-out placements.
