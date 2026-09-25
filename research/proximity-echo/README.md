# Proximity-Echo validation MVP

This browser-to-phone experiment explores whether active sound sensing can distinguish close co-presence from distance on a specific laptop and phone pair. It follows the echo-signature approach in Ren et al., *Proximity-Echo: Secure Two Factor Authentication Using Active Sound Sensing* (IEEE INFOCOM 2021), but it is a prototype. Its accuracy is not validated for authentication or any production decision.

The paper uses 20 ms, 14–15 kHz chirps. The current harness uses 20 ms, 6–12 kHz chirps by default because that band has better commodity phone-speaker reach. The browser can also select the 4–9 kHz T2 band-drop preset. Changing the band changes the experiment and is recorded with the trial.

**Status, 2026-09-22:** the corrected T2 run uses 4–9 kHz and passes capture validity. Touch scores 0.731 and 1 m scores 0.628; both reject against the uncalibrated 0.78 cutoff. Earlier same-band touch data re-scores 0.119, and two audio-link checks vary despite no reported volume or positioning change. Repeatability remains unresolved, so threshold tuning alone is not enough. Earlier simulation found that an audio relay can pass; relay resistance remains unresolved. See the [live diagnosis and results](docs/2026-09-21-live-diagnosis.md).

**Latest timing result:** the first controlled 5 cm, 25 cm, 5 cm sequence shows an exploratory timing change and return, but all three live reports were withheld. Weak late matching tails trigger the extra-event audit; the return capture also has a 20 ms phone PCM/timing discontinuity. The next work is to handle those specific cases using the saved recordings before further collection. See the [movement audit](docs/2026-09-22-beepbeep-movement.md). The prior batch produced one clean timing capture, `20e97c08`, as documented in the [first batch audit](docs/2026-09-22-beepbeep-first-runs.md). Acoustic distance and 0–10 cm proximity remain unvalidated.

## New timing diagnostic

`/ranging` provides a separate two-device recorder and travel-time analysis. **BeepBeep reference** is the default: sixteen identical 50 ms, 2–6 kHz chirps, each preceded by a 5 ms warmup, alternate between devices one second apart. Capture lasts 17.055 seconds. The original **Coded probes** profile remains available with its sixteen unique 32 ms, 4–9 kHz probes. Both store exact server-generated waveforms and continuous AudioWorklet PCM with block metadata. The analyzer estimates relative recording clock rate and combines four arrivals per exchange. It does not use the echo pipeline's similarity threshold.

The recorder is operational, but the current device pair has not produced a validated distance. Numeric timing and repeated-exchange spread are diagnostics; the spread is not a confidence bound. A mean cross-transducer path estimate is available when both independently measured speaker-to-microphone lengths are supplied and the arrival checks pass. Neither that estimate nor the reference body-gap label establishes a calibrated body-gap measurement. The displayed proximity decision remains inconclusive. The first [BeepBeep device check](docs/2026-09-22-beepbeep-device-check.md) is complete. Read the [movement audit](docs/2026-09-22-beepbeep-movement.md) before repeating it; the current next step is software work on the saved data.

1. Run `./run.sh serve`. Node.js 18 or newer is needed for the capture checks, in addition to the Python environment below.
2. Open `https://<laptop-LAN-IP>:5002/ranging` on both devices. The first page is device A. Use HTTPS and a browser that supports AudioWorklet; there is no fallback to the old recorder.
3. Tap **Enable microphone** on each device, choose **Left only** on both, and keep **BeepBeep reference** selected on A. Enabling does not play sound. Use a comfortable device volume; do not increase it to force a passing result.
4. On A, enter the ruler-measured body gap, room, and placement. Leave speaker-to-microphone lengths blank unless the active transducers and their separation are known. The body gap is a saved reference label and never enters the estimator.
5. Start one timing measurement and keep both devices still for about 18 seconds. Inspect usable arrivals and exchanges, signed timing difference, and downloadable JSON/WAVs. **INCONCLUSIVE** remains the proximity verdict even when timing succeeds. A detector-candidate count alone does not establish usable arrivals.

Each attempt has a new `data/ranging/<trial_id>/` directory containing the exact protocol, experiment metadata, original float32 WAVs, capture block records, source provenance, and final report. Failures and partial captures are retained. These files are separate from `data/logs/trials.jsonl` and the legacy WAV archive. Existing artifact files are not overwritten. Download URLs remain available after restart.

To rerun the analysis after an algorithm change, use `.venv/bin/python analysis/reanalyze_ranging.py data/ranging/<trial_id>`. This writes a new `reanalysis_<id>.json` and preserves the original report and recordings.

Version `four-arrival-diagnostic-v2` scans the entire original PCM for exact-zero and constant spans, independently of browser block continuity. A silent span is evidence to inspect, not proof of its cause. The detector also retains closely spaced match peaks and compares them with the exact probe's expected autocorrelation. Unresolved competing peaks withhold the arrival time; the analyzer does not pick a peak to match the reference distance or repair the clock fit. Single merged peaks and physical timing bias remain limitations.

Results include zero-span tables and full-resolution local match profiles. Use **Open saved view** to revisit a result without joining the recording session. For an offline reanalysis, open `/ranging?trial=<trial_id>&report=reanalysis_<id>.json`. The saved view uses the existing WAVs and never starts microphone capture.

Use `./run.sh check` for lightweight Python, JavaScript, and shell syntax checks. Automated test suites, regression runners, test fixtures, and commit/startup test gates have been removed for the experimental phase. Do not reintroduce them unless requested. Saved-recording analysis and physical experiments remain available, and runtime measurement-validity checks remain active. Syntax checks do not establish physical accuracy. See [AGENTS.md](AGENTS.md) for the current workflow. The original echo experiment remains at `/`.

### Playback-channel investigation

The first four captures do not yet establish a distance measurement. Two have stable received response shapes, but close competing peaks survive deconvolution and phase-only filtering. The four-channel phase response also disagrees across frequency bands. Playing the mono probe through multiple physical speakers is one possible cause. See the [channel investigation](docs/2026-09-22-channel-cancellation.md).

The [next five recordings](docs/2026-09-22-playback-routing-captures.md) completed the routing comparison below plus two louder Default mono retries. Left-only reduced ambiguous arrivals from 21 to 4, but its phone recording had a 60 ms silent span and timing jump. Both louder retries triggered laptop overload checks. None yielded a valid distance.

The [two subsequent Left-only repetitions](docs/2026-09-22-left-repeat-results.md) captured all probes without overload or another large timing gap. Their responses are consistent within each run, and whole-response alignment estimates approximately 22 ppm relative clock drift. But 24 and 21 arrival windows remain ambiguous. A new differential method has now compared these captures without selecting an arrival peak and also failed its consistency checks. The reference waveform/detector mode is now available for the next physical check; do not repeat this old routing campaign. The three-mode procedure below documents the completed initial routing comparison.

Refresh `/ranging` on both devices to load the **Playback on this device** control. Rest the devices at a measured 5 cm gap, with the phone screen up and its USB-C edge facing the laptop's front edge. Keep the laptop lid, orientation, supports, cases, and comfortable volume fixed. Enable both microphones once. Use the same collection-session label and leave the optional self-path lengths blank.

Run exactly three measurements, choosing the setting on **both** devices before each run:

1. **Default mono** on A and B.
2. **Left only** on A and B.
3. **Right only** on A and B.

Do not move or hold either device between runs. Withdraw your hands after selecting a setting, wait briefly, then start on A. Keep the pages open and the microphones enabled. Save all three results even if they say inconclusive. Stop and report an unsupported-output message instead of substituting another setting. This compares routing at one pose; it is not a repeatability or distance validation.

The selected channel retains the exact original probe amplitude. The unused stereo channel is zero. Default mono preserves the previous playback behavior, which normally feeds both stereo channels. The browser refuses left/right mode without a stereo destination. Source/destination channel metadata is saved in readiness and upload artifacts and displayed in new reports. These settings do not prove which physical speaker the OS activates. An observable output-layout or sink change aborts the capture and preserves partial audio. The recorder selects the first delivered microphone channel with discrete channel handling if the browser ignores the mono request.

Offline response inspection is available with `.venv/bin/python analysis/inspect_ranging_channels.py data/ranging/<trial_id> --output /tmp/channels.json`. It reads original WAVs and exact templates without using reference distance labels. Its response shapes, relative clock rates, and phase slopes remain exploratory, not proximity decisions.

To show response consistency alongside an existing result, run `.venv/bin/python analysis/reanalyze_ranging.py data/ranging/<trial_id> --include-responses` and open the new saved report. Its optional whole-response section shows relative clock trends and path consistency separately from physical first-arrival selection. Recording-quality failures or missing probes leave that section unavailable. Neither fit residuals nor consistency metrics establish distance accuracy; existing ranging decisions remain unchanged.

The [first-principles plan](docs/2026-09-22-first-principles-plan.md) explains the four-arrival calculation and the proposed physical validation campaign.

### Offline differential estimator

`analysis/differential_ranging.py` compares the complete four-path response of a current capture with a baseline. It corrects relative clock frequency and original excerpt times before taking the phase ratio. Stable channel effects can cancel without identifying the first arrival. A passing result would describe a change in combined acoustic path delay, not an absolute distance or body gap. Reference distance labels are not inputs.

```bash
.venv/bin/python analysis/differential_ranging.py \
  data/ranging/6ba25fd9b43946a0b327e0a63ad5ef0d \
  data/ranging/428ab971ce3d49948158fc7351a397f0 \
  --output /tmp/differential-left-repeat.json
```

This pair returns `rejected`, with its public delay and distance fields null. The full-band phase fit has coherence 0.9364 against the declared 0.99 minimum, and full/subband estimates disagree by 46.583 microseconds against the 10-microsecond limit. Synthetic tests and independent clock/window checks support the calculation. The [reviewed report](docs/benchmarks/2026-09-22-differential-left-repeats.json) preserves the rejected exploratory fits and input/source hashes. No live verdict or original recording is changed. These are custom engineering gates, not tests of paper reproducibility or calibrated physical-error limits. The [reproduction review](docs/2026-09-22-paper-reproduction-reset.md) sets the next acoustic step.

### BeepBeep reference mode

`analysis/beepbeep_reference.py` provides the waveform generator and signed correlation/sharpness detector. `beepbeep_protocol.py` stores the live schedule and exact waveform bytes; `beepbeep_analysis.py` applies the detector to declared, nonoverlapping slots. Its added capture, probe-presence, extra-event, attribution, and clock checks are recorded separately from the published detector thresholds. Identical chirps carry no acoustic session identity or relay defense. A schedule-consistent candidate is not proof of a direct path. See the [device check](docs/2026-09-22-beepbeep-device-check.md) for current collection instructions.

The offline comparison against the older coded recordings remains available:

```bash
.venv/bin/python analysis/beepbeep_reference.py \
  data/ranging/6ba25fd9b43946a0b327e0a63ad5ef0d \
  data/ranging/428ab971ce3d49948158fc7351a397f0 \
  --output /tmp/beepbeep-reference-comparison.json
```

The saved data uses different probes, so this is a detector comparison. Global matching produces source-order conflicts in both trials and the report withholds combined timing. It does not assess physical BeepBeep accuracy. The new live mode records the reference waveform in separate device time slots. Device calibration and physical validation remain outstanding. See the [reproduction review](docs/2026-09-22-paper-reproduction-reset.md).

## Start a session

For first-time setup, create the local Python environment and install its dependencies:

```bash
cd research/proximity-echo
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

From this directory, start the server with the project launcher:

```bash
./run.sh serve
```

Keep the server running and the laptop awake while either device is connected. `serve` checks code syntax and starts the HTTPS server without running tests. Look for `Running on https://<laptop-LAN-IP>:5002`. The server listens on port 5002 and expects `cert.pem` and `key.pem` in `research/fuzzy-commitment/`.

Open exactly two browser tabs or devices on the same LAN:

- Laptop: `https://localhost:5002`
- Phone: `https://<laptop-LAN-IP>:5002`

The first browser to join is the initiator. Its band preset, hardware tier, and distance condition apply to the trial. Only the initiator can check the audio link or start the proximity trial. Open the laptop page first for the normal laptop-and-phone setup.

## Run a trial

1. Grant microphone permission on both browsers.
2. Tap **Tap to Arm Audio** on both browsers. Mobile browsers require a gesture before they allow scheduled audio.
3. On the initiator, set the **Band preset**, **Hardware tier**, and **Condition (distance)**. Selecting hardware tier **T2** automatically applies the **4–9 kHz** preset; adjust the sliders afterward for an intentional custom band. The standard distance labels are `touch`, `30 cm`, and `1 m`; use `other` for a named control.
4. Click **Check audio link**. It checks whether both devices can hear each other's chirps. **Audio link ready** confirms reciprocal audibility only. If the result is **Audio link weak or unresolved**, reposition the devices or move to the next hardware tier.
5. Click **Start proximity trial** on the initiator to run the echo-based proximity measurement. A ready audio link does not establish proximity.

During a proximity trial, audio link check, or self-echo recording, the page requests a screen wake lock. Check that **Screen awake** reads **Keeping screen awake** on both devices. Keep both pages visible. If the browser denies the request, increase the phone's screen timeout for the test and keep it unlocked. The lock releases after the recording and upload. Full trial logs include `metadata.screen_awake` on each device so a hidden page or released lock can be diagnosed later.

Each device emits 20 chirps, alternating every 0.5 seconds, while both record about 22 seconds of audio. The server aligns the recordings, selects echo periods, compensates for microphone response, and compares their spectra. The live score is the mean of the two directional correlations, with an acceptance threshold of 0.78. This threshold still needs validation on real devices with the current frequency bands.

The proximity trial reports **Accept**, **Reject**, or **Withheld**. A withheld result has failed capture-validity checks, so do not treat its score as a proximity result. A weak or unchecked audio link does not stop a trial, but the server records that state; collect the distance sweep only after the audio link is ready.

The hardware tier ladder is T1 fixed phone-to-laptop orientation, T2 4–9 kHz band drop, T3 external USB microphone, and T4 alternate phone. The current [Phase 4 campaign runbook](docs/phase4-runbook.md) has the complete setup, gate, collection, diagnosis, and analysis procedure.

## Phone cannot reach the server

`0.0.0.0` is the server bind address. It means the server accepts connections on all local interfaces; it is not an address to enter in a browser. On the phone, use the laptop's current LAN IP, never `localhost`, which points back to the phone itself.

If the phone times out or cannot connect, confirm that the `./run.sh serve` terminal is still running, both devices are on the same LAN, and the laptop IP has not changed after a Wi-Fi, VPN, sleep, or network change. Reopen the phone URL with the current IP. A certificate warning means the phone reached an HTTPS server whose certificate it does not trust. A timeout or connection refusal points to the address, network path, firewall rule, or stopped server instead.

Sharing a Wi-Fi network name does not guarantee that devices can reach each other. Guest networks and access-point client isolation can block traffic between them. VPNs can also affect access to local addresses. Check the phone's Wi-Fi IP and exact browser error before changing network settings.

Renewing a self-signed certificate does not make the phone trust it. Microphone capture requires a secure context, and a temporary certificate exception may be insufficient. If microphone permission remains unavailable after the exception, use a certificate the phone trusts for the laptop LAN name or address, then retry the page and permission prompt. Certificate changes do not fix a timeout.

## Inspect results

The server saves WAV files in `data/audio/` and trial records in `data/logs/trials.jsonl`.

```bash
.venv/bin/python analysis/inspect_trial.py <trial_id>
.venv/bin/python analysis/inspect_trial.py <trial_id> --plot
.venv/bin/python analysis/campaign_status.py data/logs/trials.jsonl
```

Recompute a saved trial with the current extraction code without changing its original log:

```bash
.venv/bin/python analysis/rescore_archive.py d7428fad d1708b45
```

Earlier simulations exposed a transparent audio relay that was accepted. Removing the test infrastructure does not change that finding. Historical documents retain prior results; their old test commands no longer apply.

For the legacy echo experiment, compare full touch and 1 m trials with the same band, volume, orientation, and microphone settings. Record both scores and recovery counts. An audio-link result cannot show whether measurements separate distance. Current acoustic work uses the live BeepBeep reference mode for the next physical experiment. The failed differential model remains a separate benchmark.
