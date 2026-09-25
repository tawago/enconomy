# Melody probe spike: results

Question: can a short, pleasant melody replace the 30 ms noise probe, and does it detect better?

Short answer: no, not as the secret carrier.
A melody works for timing only with a whitened receiver.
Even then it holds 5 to 7 dB less security margin than a 1 s noise code of the same loudness.
The winner is a longer noise code: N1s, or N250 as a compromise.
If the product needs a tune, play it as a public jingle and put the secret in a noise layer under it.

## Reproduce

    cd /Users/takahiro_ogawa/dev/enconomy/research/sound-bound/spikes/melody
    /Users/takahiro_ogawa/dev/enconomy/research/proximity-echo/.venv/bin/python3 bakeoff.py          # ~6.5 min, writes results.json + wav/
    /Users/takahiro_ogawa/dev/enconomy/research/proximity-echo/.venv/bin/python3 bakeoff.py --table  # the table below, from results.json

Everything except the timings is seeded and deterministic. `--quick` gives a smaller run.

## Candidates

All candidates play at the same digital RMS (0.15). Each file has A, B and A+B versions under `wav/`.

- **N30**: `probes.generate`, the current 30 ms probe with 480 random-phase tones from 2 to 18 kHz.
- **N250**: the same design at 250 ms on a 4 Hz grid. This one is extra: reverb caps what extra length buys, so a mid length is worth checking.
- **N1s**: the same design at 1 s on a 1 Hz grid.
- **M-harm**: five notes, E major pentatonic. A asks (E5 G#5 B5 C#6 B5, rising) and B answers (C#6 B5 G#5 F#5 E5).
  - Onsets are 170 ms apart and the notes ring over each other.
  - Attack is 8 ms. Decay is exponential, and higher partials die faster.
  - Partial amplitude goes as k^-0.9, up to 16 kHz.
  - Every partial gets a secret phase. Its phase also wanders as a smooth random walk with a knot every 5 ms.
  - Wander depth is 0 below 1.5 kHz and full above 4 kHz, so the low, pitch-carrying partials stay clean.
- **M-bell**: M-harm with stretched partials, f_k = f0·k^1.07.
- **M-air**: M-bell plus a secret noise layer from 6 to 16 kHz, **at −12 dB relative to the melody**. It is shaped as a shaker hit on each note over a steady bed.

## Model

- **Speaker:** 2nd-order highpass at 400 Hz and 2nd-order lowpass at 16 kHz.
- **Device colouring:** each phone's speaker and mic gets an unknown ±6 dB smooth EQ. It is linear-phase, so its delay is the same on every path.
- **Clocks:** each phone's sample clock is off by ±50 ppm. Cross paths are time-stretched by the band-limited difference.
- **Noise:** −40 dB relative to the self-path level.
- **Paths:** self path 12 cm. Direct amplitude falls as 1/r. Four early reflections arrive 0.7 to 8 ms after the direct sound.
- **Rooms:**
  - normal: RT60 0.4 s, tail level 0.05. This matches synth_check.py.
  - harsh: RT60 0.6 s, tail level 1.2, stronger early reflections. The tail was calibrated so the N30 score at 1 to 2 m is 26.4%, against the real 20 to 26%.
- **Schedule:** call and response. B starts 1.35 s after A for the 1 s codes, 0.6 s for N250, 0.5 s for N30. Every candidate meets identical rooms, latencies, drifts and devices.

Receivers and arrival rules:

- **plain/mad**: analysis.py as written. Matched filter, Hilbert envelope, and the first local max at least half the window max and at least 10× the MAD floor.
- **white/null**: whitens code and recording by 1/|C(f)|, only inside the code's band and floored 20 dB below the in-band median.
  - Every occupied bin then counts once, however quiet it is.
  - The MAD floor is replaced by "normalized score ≥ the same-tune null T(1e-6)".
- For the long codes the MAD rule had to go. With a 1 s template the MAD is taken over a recording that is mostly the other code's crosstalk, so it lands at 0.4 to 2× the window max. It rejects true arrivals: plain/mad lost 3/8 rounds for N1s at 1 m harsh, and every round for all the melodies.

## Comparison

Units and rules for the table:

- Distances are in flight-cm (c/2 × time).
- The "best rx" is plain/mad for N30 and white/null for everything else. "Bad" means a round that is missing or off by more than 20 cm.
- "Worst early sidelobe" is the highest non-mainlobe envelope peak before the true peak inside the search window. The first-peak rule would jump to it if it reached 0.5.
- "Margin" is the p10 right score at 1 to 2 m in the harsh room, over the Gumbel T(1e-6) of 300 same-tune, wrong-seed codes. The null is scored over the real −150/+250 ms window of recordings that carry the true code.

| cand | crest dB | mainlobe cm (plain/white) | worst early sidelobe (plain/white) | pitch-period peak (plain/white) | null same-tune T1e-6 (plain/white) | right% harsh 1-2 m median/p10 (white) | margin p10 vs T1e-6 dB (plain/white) | walk normal: bad/n (best rx) | walk harsh <=1 m: bad/n (best rx) | walk harsh 2 m bad/n | insert hole: wrong/n |
|---|---|---|---|---|---|---|---|---|---|---|---|
| N30 | 12.0 | 1.8 / 1.8 | 0.10@-3cm / 0.15@-1cm | - | 0.233 / 0.207 | 23.6 / 16.8 | -2.2 / -1.8 | 0/32 | 0/24 | 5/8 | 7/10 |
| N250 | 12.9 | 1.8 / 1.8 | 0.15@-2cm / 0.09@-3cm | - | 0.084 / 0.083 | 9.9 / 8.5 | +0.2 / +0.2 | 0/32 | 0/24 | 8/8 | 4/10 |
| N1s | 12.9 | 1.8 / 1.8 | 0.09@-3cm / 0.09@-3cm | - | 0.042 / 0.042 | 8.2 / 6.0 | **+3.1 / +3.0** | 0/32 | 0/24 | 4/8 | 4/10 |
| M-harm | 12.9 | 23.7 / 1.4 | 0.68@-103cm / 0.14@-2cm | 0.56 / 0.04 | ≥1 (none) / 0.162 | 9.2 / 7.3 | -12.8 / -6.9 | 0/32 | 9/24 | 8/8 | 2/10 |
| M-bell | 14.2 | 26.3 / 1.8 | 0.64@-302cm / 0.12@-2cm | 0.62 / 0.06 | ≥1 (none) / 0.138 | 9.1 / 7.9 | -12.9 / -4.8 | 0/32 | 9/24 | 8/8 | 2/10 |
| M-air | 13.2 | 21.1 / 1.8 | 0.61@-302cm / 0.15@-2cm | 0.58 / 0.04 | ≥1 (none) / 0.145 | 8.8 / 7.8 | -13.0 / -5.4 | 0/32 | 9/24 | 8/8 | 2/10 |

Extra numbers:

- **Normal-room margin** (p10 score at 1 to 2 m over T1e-6), same receivers as above: N30 9.4, **N250 16.7, N1s 16.4**, M-harm 4.8, M-bell 5.4, M-air 7.9 dB.
- **Same-tune null medians:**
  - noise codes: 13.6% for N30, 4.9% for N250, 2.5% for N1s.
  - whitened melodies: 5.2% for M-harm, 5.4% for M-bell, 4.2% for M-air.
  - plain melodies: 47 to 51%.
- **Walk timing:** in every cell where the arrival is found, the median flight error is 0.03 to 0.22 cm. All errors come from picking the wrong peak, never from imprecision.
- **Harsh 2 m:** every candidate fails, N30 included (5/8). Early reflections there beat the direct sound by more than 2×, so this cell is a limit of the room, not of the code.
- **Hole, 20 ms of zeros inserted with Android-style slip, 1 m normal room:**
  - Replacing the audio in place (no slip) never moves the arrival.
  - With slip, the arrival jumps +20 ms whenever less than about 1/3 of the code's matched energy lies before the hole. For the 1 s codes that means holes in the first 10 to 30% of the sound. For N30 it is almost any hole.
  - The flat-run detector (`analysis._flat_runs`) flagged 100% of cases.
  - A half-vs-half split matched filter flagged 40 to 60% of the slips. It is useful as a backup if the zeros ever get dithered.
- **Compute:** a full 3 s × 1 s matched filter plus Hilbert takes 10.5 ms on the Mac (N30: 8.7 ms, dominated by the 3 s FFT). The windowed version (1.4 s segment) takes 5.1 ms. Generating M-air takes 65 ms. None of this matters.

## What it means

1. **Phase secrecy is nearly worthless to the current receiver.**
   - The Hilbert-envelope matched filter ignores the phase of a single steady partial.
   - A melody's energy sits in a handful of low partials.
   - So an attacker who plays the tune with *random* phases scores about 50% against the real code, which is more than the right code gets at 1 m in a reverberant room.
   - The plain arrival rule also sees pitch-period peaks at 0.56 to 0.62 and early lobes ±1 to 3 m away.
   - Stretching the partials (M-bell) did not help the plain receiver, because the loud low partials are still nearly harmonic.
2. **Whitening rescues timing, not margin.**
   - With 1/|C| equalisation the melodies get a 1.4 to 1.8 cm mainlobe, pitch peaks of 0.04 to 0.06, and a flawless normal-room walk.
   - But the secret degrees of freedom are what the tune occupies in time and frequency: narrow lines, decaying notes.
   - That leaves a null median of about 5% against 2.5% for N1s, and 5 to 7 dB less margin.
   - The air layer helps a little (median 5.4 → 4.2%). Under whitening its level barely matters: sweeps at −12, −6 and 0 dB came out the same. The limit is occupancy, not level.
3. **Reverb caps what length buys.**
   - In a 1 s window the whole reverberant tail sits under the code. The right score falls from 24% (N30) to about 8 to 10%, and it does so for every long code.
   - The null keeps falling as 1/√length, so the margin still grows, but only +5 dB from 30 ms to 1 s in the harsh room, not the ideal +15.
   - N250 gets most of the gain in the normal room (16.7 dB) and less in the harsh one (+0.2 dB).
4. **Risks.**
   - The harsh room reaches the real 20 to 26% score through reverb alone. If the real low score comes from device mismatch instead, the long codes will do better than shown here. The normal room brackets that case.
   - Gumbel fits from 300 samples are only rough out at 1e-6.
   - Long sounds widen the window a hole can land in, so more rounds get discarded (each is caught, but it costs liveness).
   - ±50 ppm drift cost little over 1 s (tested with and without).

## What a real phone test should check

- Real same-tune null on device recordings. Rescore existing recordings with N1s-style and M-air codes, and play a random-phase "same tune" as the attacker.
- Where the right score of a 250 ms or 1 s code saturates in the real small room. Does it fall to ~9% like the model, or stay near N30's?
- Whether phone speakers keep 6 to 16 kHz noise clean at a comfortable level. Also whether Android's 20 ms holes cluster early in a playback.
- Listening: whether M-air's shimmer and the wander on the upper partials sound "pleasant" or "broken" on a phone speaker (files in `wav/`).
