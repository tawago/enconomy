# Acoustic reproduction remains the objective

> Historical record. Automated tests and regression gates were removed at the user's request on 2026-09-22. Old test commands below no longer apply; follow [the current workflow](../AGENTS.md).

The project remains acoustic-only. The failed differential phase model does not establish that BeepBeep or Proximity-Echo is irreproducible. The earlier recommendation to stop browser acoustic development or require external reference microphones was too broad. Reference equipment remains an optional diagnostic, not a demonstrated prerequisite.

The two saved Left-only captures fail the declared consistency checks of our new whole-channel translation model. Preserve that result. Those engineering checks have not been calibrated against physical distance error, and neither paper uses that model as its acceptance test. Software tests establish the implementation's behavior, not that its assumptions are necessary for acoustic ranging.

## What still needs reproduction

BeepBeep uses a 50 ms linear chirp at 2–6 kHz with a 5 ms warmup, correlation-based detection, and an earlier-peak sharpness rule to handle reflections. Its distance calculation includes device speaker-to-microphone calibration. Our 32 ms random-phase probes and ambiguity rejection differ. The reference detector should therefore be implemented before judging this method on our hardware. [Journal paper, sections 3 and 5](https://www.cs.purdue.edu/homes/chunyi/pubs/peng-tecs12.pdf)

The original BeepBeep demonstration includes a 10 cm phone-pair example and a software calibration procedure. This supports attempting a commodity-device reproduction. It is not an independent replication on our devices. [Demonstration paper, page 2](https://www.microsoft.com/en-us/research/wp-content/uploads/2007/11/demo_sensys07_beepbeep.pdf)

Proximity-Echo compares compensated echo-energy signatures. It compensates individual beeps before averaging; `compensation.py` currently averages first. Its evaluated 20 ms, 14–15 kHz chirps also differ from our current signals. The reported acceptance-versus-distance curve does not establish a sharp, adjustable 10 cm boundary. [Paper, sections IV-D and V-E](https://www.winlab.rutgers.edu/~yychen/papers/%28INFOCOM%2721%29%20Proximity-Echo%20Secure%20Two%20Factor%20Authentication%20Using%20Active%20Sound%20Sensing.pdf)

## Next engineering step

The separate [BeepBeep reference implementation](../analysis/beepbeep_reference.py) now generates the waveform and implements the detector. It documents underspecified choices, including shadow-window size, exact sample neighborhoods, and which samples enter the matching reference. Eight tests cover known simulated arrivals, weaker early paths, stronger reflections whose amplitude changes, background-noise rejection, and waveform origins. Applying it to existing unique probes is a detector comparison only; those recordings cannot retroactively become recordings of the published waveform.

The saved-pair comparison exposes another protocol mismatch: global signed-correlation search across different probes can select another emission. Both saved trials contain eight identity-order conflicts, so the report withholds combined timing. Passing the signal-energy check does not validate a source identity. The reference capture mode must assign separate time slots to the devices before interpreting the detector's candidate arrivals. This adaptation result is not a physical reproduction test.

The reference waveform is now a live recorder mode at `/ranging`. Next, validate a named device pair at measured placements using the [device check](2026-09-22-beepbeep-device-check.md). Keep the source assignment, original PCM, clock diagnostics, and failed attempts. Estimate device calibration independently of the validation distances. Judge the detector by measured timing and distance errors, rather than by whether it reproduces the rejection rate of our custom phase model.

Run the paper's per-beep compensation order as a separate Proximity-Echo comparison. Keep timing accuracy and echo classification as separate outcomes. A score increase alone is not a validated proximity result.

The first physical milestone remains a repeatable 0–10 cm measurement on the selected pair in a declared pose, followed by testing across environments. This review does not establish that milestone, and it does not justify abandoning it.

## Software validation

`LC_ALL=C ./run.sh ranging-test` passed 86 Python and 22 Node tests. The final reference module's eight tests also passed after its output-protection and attribution-report changes. Those counts describe the earlier offline baseline. The subsequent live integration adds waveform validation, schedule attribution, and browser/server coverage. Original captures remain unchanged; no physical measurement has yet validated the new mode.
