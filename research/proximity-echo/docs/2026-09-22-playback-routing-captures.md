# Five playback-routing captures

The left-only condition reduced local arrival ambiguity, but none of these five captures establishes a valid distance. Its phone recording contains a 60 ms silent span and a matching timing jump. Higher volume triggered overload checks without resolving the competing arrivals.

The user reports that the first three recordings followed the fixed-placement instructions and that the last two were increased-volume retries. All five carry the same `exp-2-sep-22` collection label, 5 cm reference gap, room, and `face to face` pose. The recorded playback choices confirm the requested sequence. Both louder retries used Default mono on both devices.

| Order | Trial | A / B output | Locally usable arrivals | Ambiguous | Rejected / missing | Whole-trial result |
|---|---|---|---:|---:|---:|---|
| 1 | `32533e19` | Default / Default | 11 / 32 | 21 | 0 / 0 | Invalid |
| 2 | `6b9e788b` | Left / Left | 26 / 32 | 4 | 1 / 1 | Invalid, capture timing defect |
| 3 | `2544d907` | Right / Right | 15 / 32 | 16 | 0 / 1 | Invalid |
| 4 | `830242a7` | Default / Default, louder | 6 / 32 | 26 | 0 / 0 | Invalid, overload check |
| 5 | `f6d98ecb` | Default / Default, louder | 8 / 32 | 17 | 7 / 0 | Invalid, overload check |

These are local detector classifications. A locally usable arrival is not a validated physical direct path. Every trial still reports INCONCLUSIVE and has no accepted timing or distance summary.

## Capture integrity

All ten WAVs contain 410,016 mono samples at 48 kHz. Browser block counters report continuous delivery. Both devices stayed visible, reported running audio contexts, and recorded no track or route changes. Capture settings report echo cancellation, noise suppression, and automatic gain control disabled. These browser reports do not establish what lower layers of the audio system did.

The left-only phone WAV contains exactly 2,880 consecutive zero samples at frames `[228160, 231040)`, or 4.753333–4.813333 seconds. Matched observations of the laptop's emissions have B-minus-A offsets near 29.17–29.23 ms before the span and 89.25–89.28 ms afterward. Phone-emitted observations show the same approximately 60 ms change. This supports a discontinuity in recorded timing, rather than ordinary clock drift. It does not identify whether Chrome, Android, a driver, or another component caused it. No samples were removed and no timing step was subtracted to accept the trial.

Other runs contain occasional approximately 1 ms zero or constant spans in quiet phone audio. Those short spans alone do not prove missing time. The 60 ms span has separate timing evidence. The rejected phone self-arrival e09 overlaps the affected region; e15 has no credible self-arrival under the existing detector checks.

The laptop's peak absolute samples across the five trials are 0.1249, 0.0515, 0.1082, 1.0344, and 2.3605. The two louder trials contain 1 and 648 samples at or above the existing 0.999 overload threshold. Float WAVs preserve these values, including values greater than 1. They do not identify the physical stage that overloaded or prove every overrange sample was hard-clipped. The last run rejects seven phone-to-laptop arrival windows under its clipping checks.

## What the routing comparison says

With Default mono, every arrival on the phone is ambiguous. Left-only makes seven of eight laptop-to-phone arrivals locally usable and all eight phone-to-laptop arrivals locally usable. The phone's self path remains the weakest part, with four usable, two ambiguous, one rejected, and one missing observation. Right-only leaves every phone arrival ambiguous and misses one phone-to-laptop probe.

This supports testing left-only again. It does not establish which physical speakers were active or prove that two speakers caused the original lobes. Channel routing changes signal level and transducer response as well as possible source geometry. Different session probes also require comparison through their exact templates. No route or peak was chosen because its estimate matched 5 cm.

An exploratory comparison of the first four exchanges in each initial routing trial uses the original detector candidates only as excerpt locations. For Left-only, median complex response coherence is 0.9986, 0.9970, and 0.9972 for laptop self, laptop-to-phone, and phone-to-laptop paths. The phone self path is weaker at 0.9447, with median normalized match 0.555. Its competing deconvolved lobe falls from amplitude ratio 0.978 under Default to 0.613 under Left, but remains present. These subset diagnostics exclude the later timing defect for shape comparison; they do not turn the full Left trial into an accepted measurement. Temporary output is `/private/tmp/ranging-route-first-four-pairs.json`.

For the first four left-only exchanges before the silent span, an exploratory four-path phase fit gives nearly constant full-band fitted delays of −562 to −563 µs under an assumed 20 ppm relative clock rate. But three subbands give approximately −611.5, −509, and −836.5 µs. Phase residuals remain 0.601–0.642 radians. The disagreement persists with zero assumed drift and different extraction margins. Thus fewer detector ambiguities have not established a single physical propagation delay. This temporary exploration lives at `/private/tmp/routing-left-phase.py`; it does not replace the original analysis.

## Next bounded check

Collect exactly two Left-only / Left-only recordings at one untouched 5 cm placement, using one fixed comfortable volume below the louder retry settings. Restore the first-three settings if known. Otherwise note the new settings and treat the pair as a new volume condition. OS volume was not captured, so browser gain 1 does not document the physical volume.

Keep both microphones enabled between the two runs. Do not hold, rotate, or move either device. Stop after those two, even if the results are inconclusive. Their purpose is to determine whether the simpler left-only response can be recorded intact and repeated. A recurring silent span with a timing jump warrants investigating the capture path before collecting distance sweeps. A clean pair with unresolved arrivals warrants further processing work, not endless retries or threshold changes.

Original trials, WAVs, metadata, and reports remain unchanged. All conclusions above distinguish original live results from exploratory processing. The separate analysis artifact does not authorize a proximity verdict.

## Offline inspector correction

The new captures exposed a bug in `analysis/inspect_ranging_channels.py`, separate from the live analyzer. Normalizing an analytic correlation-envelope tail by near-zero window energy could invent a probe location inside silence. The Left trial's missing phone self-probe e15 triggered this error. Version `exploratory-channel-shapes-v2` applies the existing live analyzer's minimum-energy rule and requires a local envelope peak before accepting an excerpt location. The 0.40 normalized-match cutoff is unchanged.

Its self-check now reproduces and rejects that false match while still locating a real exact template surrounded by silence. Independent checks retain Left B/e15 and Right A/e09 as missing, at best normalized correlations 0.366511 and 0.379222. All 128 probe locations across the earlier four captures remain locatable. Preliminary whole-trial inspector output for Left was discarded. Original live reports already rejected these probes and did not need correction.
