# First live BeepBeep device check

> Historical record. Automated tests and regression gates were removed at the user's request on 2026-09-22. Old test commands below no longer apply; follow [the current workflow](../AGENTS.md).

The reference waveform and detector now run through the two-device browser recorder. This check asks whether timing responds to a measured movement and returns when the device returns. It does not yet validate a 10 cm acceptance boundary.

## Prepare once

1. Start `./run.sh serve` if the server is not already running. Refresh `/ranging` on both devices. Open the laptop page first so it is device A.
2. Enable both microphones. Select **BeepBeep reference** on A and **Left only** on both devices. Stop and report an unsupported-output message if either browser cannot use Left only.
3. Keep a comfortable volume, the laptop lid angle, supports, cases, orientation, and room unchanged. Rest the phone screen up with its USB-C edge facing the laptop's front edge. Mark the phone's placement so it can be restored. Do not hold either device during capture.
4. Use one collection-session label, for example `beepbeep-first-movement`. Leave both optional speaker-to-microphone lengths blank unless the active transducers and their separation are independently known. The ruler-measured body gap is a reference label, not an estimator input.

## Record

1. Place the device bodies **5 cm apart**, enter `5` as the measured gap, withdraw your hands, and start one measurement on A. Keep both pages visible and the devices still for about **18 seconds**.
2. Inspect the result. Continue when the report has **32 usable arrivals and 8 usable exchanges** and a numeric signed timing difference. The proximity verdict remains **INCONCLUSIVE**. If timing is invalid, stop here and share the trial ID and reasons; do not change volume or placement to make it pass.
3. Move the phone straight back to a **25 cm body gap**, preserving its angle and height. Enter `25` and record once.
4. Return it to the marked **5 cm** placement, enter `5`, and record once. Share all three trial IDs, including failures.

Each capture contains eight exchanges, which measure spread within a run. The return capture checks whether the original timing returns. An extra unmoved 5 cm repetition is optional if between-run repeatability needs investigation.

## Read the result

Compare the **signed uncorrected timing equivalent** and the underlying timing difference. Unknown fixed self-path lengths cancel when comparing placements. This value can be negative at close range; it is not the body gap. Moving the bodies by 20 cm need not change the mean speaker-to-microphone paths by exactly 20 cm because the transducers have different positions. We will inspect those paths before assigning a distance-error claim.

Detector candidates and usable arrivals are different. The paper's detector may nominate a peak even in a slot containing a click. Separate probe-presence and slot checks can reject it. Recordings retain both the candidate and the reason for withholding timing.

A small spread does not establish accuracy. A stable reflection or device response can produce a stable timing bias. The profile uses identical chirps and coarse slots, so it also does not establish acoustic freshness or resistance to replay. Independent device calibration, repeated poses, held-out distances, and multiple environments remain necessary before a live proximity verdict.

## What the software preserves

Each attempt saves the exact waveform and schedule, both original float32 recordings, capture/playback metadata, source hashes, detector output, attribution checks, relative-clock fit, and paired timing results. Saved views and reanalysis work after restart. Prior coded-probe recordings and reports remain available; they cannot substitute for recordings of this reference waveform.

## Integration validation

The live integration passed 104 Python and 32 Node tests. Independent synthesis covered 44.1/48 kHz recording, clock skew, signed close-range timing, missing chirps, clicks, extra events, stronger reflections, and unrelated browser wall clocks. A two-page browser test uploaded synthetic WAVs through the real server and recovered a 35.00 cm mean path as 35.01 cm; a mismatched coordination target withheld timing. These are software checks, not physical device results.

New and old saved reports also loaded after restarting the isolated QA server without opening a microphone, audio context, or socket. The 393-pixel phone layout had no page overflow. Reanalysis of the new saved synthetic recording retained its result; the coded-probe response inspector correctly marked itself unavailable for this waveform. All 132 original capture artifacts, the legacy log, and golden fixture were unchanged.
