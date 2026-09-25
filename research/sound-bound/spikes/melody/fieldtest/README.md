# fieldtest: probe length and jingle mix in real rooms

Two phones, one run, five probes back to back (**N250 -> N500 -> N1s -> JBL -> JBL250**, v2),
one continuous 27 s recording per phone (~30 s with the start delay). Answers: how short
a code can be, and whether a louder/lower public jingle hurts the secret bed, at 30 vs
100 cm and with what margin over a live null. Spec: `CONTRACT.md` (+ "v2 addendum" at its end).

## Probes (v2)

| probe | sound | receiver |
|---|---|---|
| N250 / N500 / N1s | random-phase multisine 2-18 kHz, 0.25 / 0.5 / 1 s | whole code |
| JBQ (old sessions) | JB's public bell jingle + secret 2-18 kHz bed, bed **+6 dB** re jingle | bed only, jingle partials notched +-15 Hz |
| JBL | soft low tune (C4-C5 pentatonic, 4 harmonics max, every partial < 1.8 kHz) + secret bed at -6 dB | bed only, 2-18 kHz, no notches |
| JBL250 | 0.25 s two-note soft mallet "ding-dong" (A E4->A4 rising, B C5->G4 falling, 3 harmonics, every partial < 1.8 kHz) + secret 0.25 s bed (grid 4 Hz) at -6 dB | bed only, 2-18 kHz, no notches |

All equal digital RMS (0.15). The sequence is `fieldprobes.SEQUENCE`; each probe plays
A, B, A, B with 0.7 s silence after every sound. N30, JB and JBQ still generate and analyse
(old sessions reanalyse unchanged) but are not played by default.

Every session is analysed under two arrival rules from one correlation pass:
**first** (primary: `decision`, `summary`, round `flight_cm`) and **ownwalk**
(`decision_ownwalk`, `summary_ownwalk`, round `ownwalk.{flight_cm, arrivals, reasons}`).
ownwalk = walk back from the strongest match for self arrivals, first for cross.

## Run

```
cd research/sound-bound/spikes/melody/fieldtest
./run.sh check                      # syntax: python, js, shell
./run.sh serve                      # https://0.0.0.0:5004  (self-signed cert from research/fuzzy-commitment)
FIELD_GAIN_DB="N250:0,N1s:-3,JBL:0" ./run.sh serve   # per-probe gain in dB; default equal RMS
./run.sh synth                      # simulated walk (data/synth), prints the compare table
./run.sh e2e                        # own server on :5005 (E2E_PORT) -> data/e2e, fake phones 30 + 200 cm
```

`./run.sh e2e` uses its own port (default 5005, `E2E_PORT`), so a live `serve` on 5004 keeps
running; it refuses if that port is busy. `FIELD_PORT` moves `server.py` off 5004.
Its sessions go to `data/e2e/`, never to `data/sessions/`.

Phones: both on the Mac's Wi-Fi, open `https://<mac-ip>:5004/` (accept the cert
warning). `ipconfig getifaddr en0` gives the IP. Past runs: `/sessions`.
Listen to the probes: buttons on the page, or `/preview/<probe>.wav` for N250, N500,
N1s, JBL, JBL250 (also N30, JB, JBQ) (`?role=B` for B's tune).

## One run

1. Phone 1: tap distance (touch / 30 / 60 / 100 / 200 / other), pick room, pose,
   noise. Tap **Join**. These labels are what gets recorded.
2. Phone 2: tap **Join** (its labels are ignored; the recorded ones show on both).
3. Both: media volume up, tap **Arm**, grant the mic. Put phones down. Quiet.
4. Run starts 2.5 s after the second arm. 30 s. Progress names the sound playing
   (e.g. `N500 · B round 2`).
   Preview buttons are disabled while recording.
5. Result card: one row per probe: decision (first), decision (ownwalk), flight, spread,
   min margin (first / ownwalk). Tap a row for per-round detail.
6. **Next run** keeps labels.

When it goes wrong:
- Upload failed: the phone says why and shows **Retry upload** (the recording is kept).
- Stuck (a phone closed its tab, locked, lost Wi-Fi): tap **Abort / reset pair** on
  either phone. If nobody does, the server resets itself ~67 s after the start.
- "ECHO CANCELLATION IS ON": note it; that phone's self arrivals are suspect.

## Field protocol

- Phones flat on a table (pose=table), screens up, speakers/mics unobstructed.
  Distance = mic to mic, roughly (tape measure, ±2 cm is fine).
- Grid: room {small, big} x distance {touch(0), 30, 100, 200 cm} x **3 runs** = 24 runs.
  60 cm optional (no expected answer; shows where the edge sits).
- Order: do one room completely, then the other. Within a room go 0 -> 30 -> 100 -> 200,
  then repeat the sweep twice (3 passes), so drift in the room shows up.
- Swap which phone is A for one of the three passes (role select A/B).
- Noise: quiet for the grid. If time allows, 3 extra runs at 30 and at 100 cm with
  music, then talk.
- Nobody moves or talks during a run. Check the result card before the next run;
  if a probe shows `timeline_gap` or 0 usable rounds, redo that run.

## Reading results

Per probe, per run (`result.json`, result card, `/sessions`):

| field | meaning |
|---|---|
| decision | NEAR if flight median < 45 cm, FAR if > 80 cm, else UNDECIDED. Also UNDECIDED if < 2 usable rounds or rounds spread > 40 cm. |
| flight | acoustic flight in cm = true distance **minus ~12 cm** (own speaker-to-mic path). 30 cm reads ~18, 100 reads ~88, touch reads ~-10. |
| spread | max - min flight over usable rounds. Small = repeatable. |
| usable | rounds with all 4 arrivals found and no gap / impossible flight. |
| right % / T % | match score of the true code vs the live-null bar T for that window. Found only if right >= T. |
| min margin dB | worst 20 log10(right / T) over usable arrivals. The security headroom: near 0 dB = barely above what random codes reach. |

Per round (tap a probe): four cells `A→A, B→A, B→B, A→B` as right % / T %, red when
missed, plus reasons (`below_null_B_at_A`, `timeline_gap_at_A`, `impossible_flight`).
`result.json` also has `ppm`, `drift_ppm` / `drift_cm` (clock drift estimate; applied to
N500/N1s/JB/JBQ/JBL; N250 and JBL250 record it but are not corrected), `flight_raw_cm` (before correction),
`half_rejected` (earlier peaks above T that the direct-path rule skipped) and, per self
arrival, `flags: ["code_gap"]` + round reason `self_code_gap_at_<L>` when a dropped block
lies inside its own code.

Across runs:

```
PY=/Users/takahiro_ogawa/dev/enconomy/research/proximity-echo/.venv/bin/python3
$PY compare.py                        # field runs, data/sessions (e2e-labelled runs skipped)
$PY compare.py --by probe,room        # pooled over distances
$PY compare.py --by probe,label_cm,noise
$PY compare.py --csv > runs.csv
$PY compare.py --dir data/synth       # simulated runs
$PY fieldanalysis.py data/sessions/<id>   # one run, per-round detail
```

Columns (unprefixed = first rule, `ow ...` = ownwalk): `NEAR/FAR/UND` counts, `correct` (label <= 30 expects NEAR, >= 100 FAR),
median flight, worst spread, usable rounds, median right %, median T, min margin dB,
timeline gaps. The probe that wins: most `correct`, fewest UND, tight spread, and the
largest min margin at 100 and 200 cm (margin is what an attacker's guess must beat).

The simulator (`synth`, `e2e`) is a wiring stress test, not a probe ranking: its
room tail puts the critical distance at ~10 cm, so 200 cm there is far harsher than
a real room (see `synth_field.py` docstring).

## Web side notes

- Browser does no DSP. It fetches float32 probes (`/api/probe/...f32?sr=<ctx rate>`)
  at Arm, schedules 8 own plays with `AudioBufferSourceNode.start(when)`, records via
  an AudioWorklet, trims to `[t0 - lead_s, t0 - lead_s + record_total_s)`, uploads
  a float32 WAV plus meta.
- `fieldprobes` / `fieldanalysis` are imported lazily. Missing -> probe route 503,
  result.json `failed` with `server_missing_signal_code`.
- Arm is disabled until the partner has joined (the session directory and seed only
  exist once the pair is complete, so probes cannot be fetched earlier).
- `FIELD_SESSIONS_DIR` moves the session store (e2e uses it); `/api/info` reports it.
- Last label choices are kept in localStorage (best effort).

## Review fixes (deviations from CONTRACT.md)

- Arrival rule: half-max reference is the env max within 5 ms after a peak
  (`HALF_LOOKAHEAD_S`), not the whole 400 ms window; a louder diffuse-tail peak can
  no longer push the lock 10 ms late.
- Null bar: `T = gumbel isf(NULL_P / 3)`; the 64-maxima fit under-states the tail.
- N1s/JB flight is corrected for clock drift over the 1.7 s A->B gap.
- Server: stuck-run watchdog, `abort` wired to a button, `FIELD_SESSIONS_DIR`.
