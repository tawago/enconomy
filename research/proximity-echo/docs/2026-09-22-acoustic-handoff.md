# Acoustic project handoff

Goal: reliable 0–10 cm proximity on ordinary devices, eventually a downloadable hackathon demo. Stay acoustic-only. No NFC. Use Astra Max subagents.

BeepBeep measures acoustic travel time. Both devices record their own and the partner's chirps. Four arrival times cancel unknown start and response delays. Relative clock drift, speaker-to-microphone geometry, and detector bias still matter. Its earlier-sharp-peak rule does not guarantee the direct path.

Proximity-Echo compares compensated echo spectra. It classifies proximity rather than measuring distance. Our implementation still differs from the paper: different frequency bands, and averaging before compensation instead of compensating each beep first. Its score threshold is not an arbitrary centimeter cutoff.

We built a live BeepBeep reference mode at `/ranging`. One earlier physical capture passed timing checks. The latest 5 cm, 25 cm, 5 cm sequence showed an exploratory timing pattern of 1.081, 1.747, 1.039 ms, but all three live reports remain invalid. Distance accuracy is unproven.

Our immediate blockers are weak delayed responses triggering our added extra-chirp audit, 20 ms phone recording-time discontinuities despite clean worklet counters, and unstable peak selection. These failures do not establish that either paper is irreproducible. Small repeat spread does not prove accuracy. Identical chirps do not authenticate their source or prevent replay.

Next: use saved recordings to investigate better late-response attribution, signal-based discontinuity detection, and peak consistency. Preserve failures and original data. Validate replacements before changing live gates or collecting more recordings. Keep timing reproduction separate from the Proximity-Echo compensation-order experiment.

Current workflow: the user removed automated tests and regression gates to speed experimentation. Use `./run.sh check` for syntax and `./run.sh serve` to start. Do not restore test suites unless requested. Runtime recording-quality checks and original data remain. See [AGENTS.md](../AGENTS.md).

Read the [movement evidence and exact trial IDs](2026-09-22-beepbeep-movement.md), [paper comparison and sources](2026-09-22-paper-reproduction-reset.md), and [first batch audit](2026-09-22-beepbeep-first-runs.md). Latest evidence supersedes earlier next-step instructions.

The first two of those blockers now have offline work behind them: see [late-tail attribution and timeline segmentation](2026-09-23-late-tail-and-timeline.md). Both added policies, `late_tail_policy` and `timeline_policy`, are opt-in and default-off, and the live server passes neither, so every live report and gate is unchanged. Only one saved trial (37fa17db, 25 cm) changes headline status, and only under the late-tail policy. The open items are peak-family selection, which still holds 8335587e above the residual gate on its own, and deciding whether the 10 ms recurrence window is acceptable given the 6.396 ms peer-delay jitter on 37fa17db's only tail.
