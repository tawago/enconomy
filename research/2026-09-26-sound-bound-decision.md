# sound-bound decision: one short low jingle per phone, 2026-09-26

We build the proximity check around **JBL250**: each phone plays a 250 ms soft two-note sound. Distance comes from four arrival times. The verdict is NEAR (under 45 cm), FAR (over 80 cm) or UNDECIDED.

This note records what we will implement, why the logic looks the way it does, what it means for the ZK circuit, and how two phones find each other and run a session. It builds on `2026-09-25-cheating-participant-and-trust.md` (who can cheat, where the defense lives) and `2026-09-26-zk-gap-research.md` (proof systems). Evidence comes from `sound-bound/spikes/melody/fieldtest/` and its recorded sessions. The note was checked by two adversarial reviews (data claims; protocol and ZK), and their corrections are folded in.

Two choices are still open (section 6): **one play or two per phone**, and **option C or option A for the proof**. The second one decides whether JBL250 can be the sound at all.

## 1. What we implement

| Part | Decision |
| --- | --- |
| Sound | JBL250: a public two-note "ding-dong" (A rises, B falls), every tone below 1.6 kHz, plus a secret noise layer 2–18 kHz at −6 dB. 250 ms. |
| Plays | A plays, then B 0.95 s later. One or two rounds: open, see section 6. |
| Receiver | Correlate with the secret noise layer only (2–18 kHz). The tune is ignored. |
| Bar | Live random-code bar: the same recording scored against 64 made-up codes; the bar is the level they exceed with probability 1e-4/3 per window. A fixed public floor sits under it. |
| Arrival rule | "First": the earliest local peak above the bar that is at least half as tall as the biggest peak in the next 5 ms. No walk-back. |
| Checks | Drop a round if a 20 ms silent block (Android recording glitch) lies anywhere between its first and last search window, or if the distance is below −20 cm. Both checks run on the phone before it signs anything. |
| Retry | UNDECIDED means "play again" with fresh codes, automatically, once. Never after FAR. |

## 2. How the processing works, and why

### Distance from four times

Each phone records both sounds. Per round there are four times: A hears A, A hears B, B hears B, B hears A.

    flight = c/2 × ((t_BA − t_AA) − (t_BB − t_AB))
                    A's file only    B's file only

Each phone's speaker delay and clock offset appear in both terms of its own file and cancel. What's left is the flight time minus half of each phone's own speaker-to-mic path, which is why touching phones read about 8 cm, not 0. Clock sync only has to be good enough to put each sound inside its search window (section 4).

### Finding an arrival

The phone knows the secret sound exactly. It slides it along the recording and computes a match score at every position, 0% to 100%. The whole curve comes out of one Fourier transform: multiply the two spectra, transform back. The real arrival shows up as a jump (17–62% for JBL250 on the walk). Everywhere else there are small chance matches, mostly well under the bar of about 4%.

The rule takes the earliest peak above the random-code bar, provided it is at least half the size of the biggest peak in the next 5 ms. That bar is measured on the same recording, so a noisy room raises it along with everything else.

### Why a secret noise layer under a public tune

- A tune can't carry the secret. Anyone can record a tune and replay it. Shuffling the phases of a held note only shifts it in time, and the detector can't see that. Tested: five instrument styles, all lost (`spikes/melody/RESULTS.md`).
- Detection strength comes from bandwidth × duration of the secret part. The noise layer covers 2–18 kHz.
- The tune is there for people. Measurement ignores it.

### Why the tune sits below 2 kHz

The first jingle (bell tones up to 16 kHz, inside the noise band) put an early false match above the bar in 9 of 36 rounds, across 6 of 18 sessions. Each time it was a phone hearing its own sound: about 4.2% against a 4.0% bar, 7–11 ms before the real arrival. In two of those runs we measured that false-match level against what the code's own math predicts, and it came out 2.3–2.6× higher (session scratch script, not in the repo).

The same bell jingle played 12 dB quieter (JBQ) failed 6 of 8 rounds with the same signature. So loudness is not the cause; what matters is that the jingle's tones sit inside the secret noise's band. Moving the tune below 1.6 kHz removed it. On the walk, JB-low and JBL250 showed no early false matches, and an alternative rule (walk-back on a phone's own sound) agreed with "first" within 4 cm on every session. That is 12 sessions in one room.

### Why 250 ms

Same 12-session walk (big room, handheld, quiet, Mac + Android):

| Sound | Weakest margin over the bar | Notes |
| --- | --- | --- |
| 30 ms noise | 0–4 dB | too thin |
| 250 ms noise | 7.0 dB | |
| JBL250 | 6.6 dB | 24 of 24 rounds usable, each on the right side of the 45/80 cm lines |
| 1 s noise | 14.3 dB | across all sessions, including the small room: 7.3 dB |

JBL250 readings (label → reading): touch → 8, 30 → 26–35, 60 → 60–76, 100 → 95–110, 200 → 211–225. Two rounds in the same run agree within 3.2 cm.

Clock drift barely matters at 250 ms: phone audio clocks differ by up to about 100 ppm, which stretches a 250 ms sound by at most about one sample, less than 2 cm of distance. No drift correction.

### The Android recording glitch

The Android browser sometimes drops one audio buffer. The recording then holds exactly 20 ms of zeros, and everything after it is 20 ms late.

**Direction matters.** If the block lands in B's file between A's arrival and B's own sound, the pair reads about 3.4 m **closer**, a fake NEAR. In A's file the same thing reads farther. That's why the flat-block check has to run on the phone before signing, and why the self-arrival cross-check against the OS output timestamp (trust note) needs a tolerance well under 20 ms.

Measured: 13 blocks in 816 s of Android recording, none on the Mac. 8 of 13 fell in the first 4 s of a run's capture. **The mic had already been open for at least 9 s each time**, so this is not a mic warm-up effect. The blocks cluster near the start of a run, around the first sounds. JBL250 played last (after 22 s) and was never hit.

What this means: a one-sound run falls exactly into the risky early part. The cause is unknown. Candidates are the first playback starting while recording, or the page doing work at run start. Two things to try: play a short silent or inaudible buffer before the real sound to start the output path early, and measure the glitch rate in a native AAudio recorder. We may also cut the 20 ms block out and keep the round, since the shift after it is exact. Not tested.

## 3. What this means for the ZK circuit

The trust note settles the main point: the prover supplies the recording, so no circuit can tell a real recording from an edited one. The defense against a cheating phone is the attested app with a hardware key. The proof's job is binding and privacy.

### Option C, analysis outside (recommended)

Each attested app computes its own half from its own file (A: t_BA − t_AA; B: t_BB − t_AB).

**What each phone signs, all of it:** session nonce, attempt number, its role (A or B), its own session key and the partner's, sample rate, its half (in samples), recording hash, and the OS output timestamps of its playback.

Without role and both keys in the signature, anyone combining the halves can swap them. Swapping flips the sign: 100 cm becomes −100 cm, which passes "flight < 45 cm".

**The circuit checks:**
- both signatures over the same nonce and the same pair of keys
- one role A and one role B
- −20 cm < flight < 45 cm
- the nullifier

**Which key signs.** The enclave key is P-256. The current `circuits/copresence.circom` verifies EdDSA on BabyJubjub over BN254, and checking P-256 there costs about 2M constraints. Two ways out, per the zk-gap note:
- prove P-256 directly with OpenAC or longfellow-zk (about 0.1–0.9 s on a phone), or
- have the enclave certify a software key at enrollment and sign with that.

The old "20–30k constraints" figure only holds for the software-key path, and SHA-256 over the transcript adds about 30k per block on top.

**Nullifier.** H(holder software secret, nonce) using SHA-256 or α=7 Poseidon, with the nonce kept private. Not Poseidon(hash, pkA, pkB) as today: that lets the issuer link people (zk-gap note, section 3).

Nothing chosen in section 1 changes the circuit size under option C.

### Option A, analysis inside

It is only worth it if the analysis runner can't be trusted. **It likely rules out JBL250.** The zk-gap note found 250 ms codes left 0.0–0.4 dB of margin under its circuit-friendly receiver (1-bit samples, fixed bar, narrow windows). JBL250's secret layer is the same 250 ms at −6 dB, so expect the same or worse. With option A, the sound becomes the 1 s chip code from that note.

If option A is chosen anyway:
- **Hint, then verify.** The phone passes the arrival positions it found; the circuit checks "above the bar here, below it in the stretch before" without searching.
- **Fixed bar, no floor-only rule.** A prover-chosen bar must be bounded from above too: a high bar hides the true self peak and lets a later echo pass as the first sound, which makes the pair look closer. Use a fixed public bar, or both a floor and a ceiling. Recomputing the live bar in-circuit (65× the cost) is out.
- **Windows.** Self arrival: ±2 ms around the signed OS output timestamp. Cross arrival: ±10 ms, checked densely.
- The run's lead-in adds nothing. The circuit only sees the stretch around each arrival.

## 4. How two phones run a session

### Discovery and pairing

1. Both users open the "meet" screen and keep the app in the foreground. iOS hides a backgrounded app's Bluetooth advertisement from Android.
2. Each phone advertises a short-lived random ID as a 128-bit Bluetooth LE service UUID and lists nearby IDs. Android 12+ needs the Bluetooth scan, advertise and connect permissions at runtime.
3. The users confirm each other: name or avatar from the server, looked up by the ephemeral ID. Until they confirm, pairing is unauthenticated; someone else in the room could show up in the list.
4. The phones swap session public keys over a Bluetooth GATT connection. The server creates the session.

QR code is the required fallback when Bluetooth is off or denied. NFC tap stays optional. Android can emulate a card; iPhone card emulation needs an entitlement and depends on region.

### Setup from the server

- Session nonce and attempt number.
- **Codes, commit then reveal.** Each phone first gets only its own secret code. It needs the partner's code to find the partner's arrival in its own recording. The server releases the partner's code to a phone only after that phone has sent its enclave-signed recording hash, the same hash that later goes into the signed transcript. So no one can pre-play the partner's sound or edit a recording after seeing it.
- Codes derived from (session, role, attempt). A retry gets new codes.
- The prototype falls short here in two ways: the rendered code of either role can be fetched from `/api/probe/<session>/<role>` without authentication, and the code derivation (`fieldprobes._sub`) has no round or attempt index.
- **Start time.** T0 is set a few seconds ahead, from a clock sync of 10 pings to the server. The budget: the partner's sound must land inside the −150/+250 ms search window. That window has to absorb the sync error between the two phones (half the round-trip asymmetry, tens of ms on cellular), the emitter's output latency (20–200 ms) and the listener's input latency. On the Android browser the observed arrivals already sat 74–138 ms late. Tighten the windows once native OS timestamps are available. Any miss shows up as UNDECIDED and triggers a retry.

### The run

| Time | Phone A | Phone B |
| --- | --- | --- |
| T0 − lead | mic on (no echo cancellation, noise suppression or auto gain); optional silent buffer to start the output path | same |
| T0 | plays JBL250 | records |
| T0 + 0.95 s | records | plays JBL250 |
| T0 + about 2 s | mic off | mic off |

With two rounds, the second pair of plays follows 1.9 s later.

Platform details:
- **iOS:** `.playAndRecord` with `.measurement` mode and `.defaultToSpeaker`, otherwise sound goes to the earpiece. A phone call interrupting the audio session aborts the run.
- **Android 14+:** the mic needs a foreground service if the app might leave the foreground mid-run.
- **Pre-flight:** check media volume above a set level and speaker output (not Bluetooth headphones).

### After the run

1. Each phone checks its own recording: no 20 ms silent block in the used windows, and its self-arrival agrees with the OS output timestamp. Target tolerance about 1 ms (trust note).
2. Each phone computes its half and signs the full transcript (section 3).
3. Halves meet, at the server or directly over Bluetooth. flight → NEAR / FAR / UNDECIDED.
4. UNDECIDED: one automatic retry with fresh codes. The retry counts against the same false-accept budget.
5. Failure messages name the cause: "partner not heard, check volume", "recording glitch, trying again", "too far". Not a generic "try again, closer".
6. NEAR: build and submit the proof.

**Privacy.** The server sees the pair before any proof exists: ephemeral-ID lookup, IP addresses, timing, the halves and the verdict. ZK hides the meeting only from third parties. Having the halves meet over Bluetooth instead of at the server reduces that. The proof has to be built on a phone, because the holder secret can't be on the server.

## 5. What is not proven yet

- Every JBL250 number comes from 12 sessions in one afternoon: one large quiet room, one Mac + Android pair, phones handheld, mid volume. The earlier small, echoey room wasn't walked with JBL250. There, 1 s noise dropped to 7.3 dB of margin, and the bell jingle read 145 cm for a true 200.
- iPhone is untested. In Safari, echo cancellation may be forced on; a native app with measurement mode avoids that.
- The cause of the Android glitch, native-app glitch rates and OS output-timestamp accuracy are all unmeasured.
- Clipping: the Mac clipped about 16k samples in the touch run and still read 8 cm. There's no clipping tolerance on record yet.
- A noisy venue: the bar adapts, but there's no noisy walk with JBL250.
- Each recording shows a few worklet discontinuities with zero missing frames. Probably a counting artifact; not explained yet.
- A handheld 60 cm run read 80–90 cm on the noise sounds and 75–78 on the low jingles. Hands move; the UI should say "phones side by side".

## 6. Open decisions

**One play or two per phone.**
- One play is shorter, and each round was individually correct on the walk.
- It drops the only cross-check between rounds (at least 2 usable rounds, spread under 40 cm). A single early false match in a cross window then decides directly, and the retry gives a second draw.
- Two plays cost about 1.9 s more.
- If we go with one play, require a NEAR margin above a set level on all four arrivals, and count the retry against the same false-accept budget.

**Option C or option A.**
- Option C keeps JBL250 and adds nothing to the circuit's audio side, but needs the P-256 key path.
- Option A needs the 1 s chip code, not JBL250. It adds no security against a cheating participant.

## 7. Next steps

1. Test app in the production shape: JBL250, per-attempt codes, commit-then-reveal code release, role-bound signed transcript, optional silent output primer.
2. Walk: small room and big room, 0 / 30 / 100 / 200 cm, 5 runs each. Plus one noisy walk.
3. iPhone + Android walk.
4. Native Android recorder with AAudio timestamps: glitch rate, glitch cause, timestamp accuracy.
5. Pick the key path for option C (OpenAC or longfellow vs an enclave-certified software key) and prototype the transcript circuit.
