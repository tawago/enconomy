# sound-bound decision: one short low jingle per phone, 2026-09-26

We build the proximity check around **JBL250**: each phone plays a 250 ms soft two-note sound. Distance comes from four arrival times. The verdict is a yes/no: NEAR if the distance is under 60 cm, otherwise not near.

This note records what we will implement, why the logic looks the way it does, what each phone must sign, and how two phones find each other and run a session. The ZK proof design is out of scope here and handled separately. It builds on `2026-09-25-cheating-participant-and-trust.md` (who can cheat, where the defense lives). Evidence comes from `sound-bound/spikes/melody/fieldtest/` and its recorded sessions. The note was checked by two adversarial reviews (data claims; protocol), and their corrections are folded in.

Decided: **one play per phone**. Section 6 lists what that gives up and how we cover it.

## 1. What we implement

| Part | Decision |
| --- | --- |
| Sound | JBL250: a public two-note "ding-dong" (A rises, B falls), every tone below 1.6 kHz, plus a secret noise layer 2–18 kHz at −6 dB. 250 ms. |
| Plays | One per phone: A plays, then B 0.95 s later. See section 6. |
| Receiver | Correlate with the secret noise layer only (2–18 kHz). The tune is ignored. |
| Bar | Live random-code bar: the same recording scored against 64 made-up codes; the bar is the level they exceed with probability 1e-4/3 per window. A fixed public floor sits under it. |
| Arrival rule | "First": the earliest local peak above the bar that is at least half as tall as the biggest peak in the next 5 ms. No walk-back. |
| Checks | Drop a round if a 20 ms silent block (Android recording glitch) lies anywhere between its first and last search window, or if the distance is below −20 cm. Both checks run on the phone before it signs anything. |
| Verdict | NEAR if flight < 60 cm, otherwise not near. No gray zone. |
| Failed measurement | Glitch in the used windows, partner's sound not found, or flight below −20 cm: retry once automatically with fresh codes. A second failure counts as not near. Never retry after a valid "not near". |

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
| JBL250 | 6.6 dB | 24 of 24 rounds usable, each on the right side of a 60 cm line |
| 1 s noise | 14.3 dB | across all sessions, including the small room: 7.3 dB |

JBL250 readings (label → reading): touch → 8, 30 → 26–35, 60 → 60–76, 100 → 95–110, 200 → 211–225. Two rounds in the same run agree within 3.2 cm.

Clock drift barely matters at 250 ms: phone audio clocks differ by up to about 100 ppm, which stretches a 250 ms sound by at most about one sample, less than 2 cm of distance. No drift correction.

### The Android recording glitch

The Android browser sometimes drops one audio buffer. The recording then holds exactly 20 ms of zeros, and everything after it is 20 ms late.

**Direction matters.** If the block lands in B's file between A's arrival and B's own sound, the pair reads about 3.4 m **closer**, a fake NEAR. In A's file the same thing reads farther. That's why the flat-block check has to run on the phone before signing, and why the self-arrival cross-check against the OS output timestamp (trust note) needs a tolerance well under 20 ms.

Measured: 13 blocks in 816 s of Android recording, none on the Mac. 8 of 13 fell in the first 4 s of a run's capture. **The mic had already been open for at least 9 s each time**, so this is not a mic warm-up effect. The blocks cluster near the start of a run, around the first sounds. JBL250 played last (after 22 s) and was never hit.

What this means: a one-sound run falls exactly into the risky early part. The cause is unknown. Candidates are the first playback starting while recording, or the page doing work at run start. Two things to try: play a short silent or inaudible buffer before the real sound to start the output path early, and measure the glitch rate in a native AAudio recorder. We may also cut the 20 ms block out and keep the round, since the shift after it is exact. Not tested.

## 3. What each phone signs

The trust note settles the main point: a phone supplies its own recording, so nothing downstream can tell a real recording from an edited one. The defense against a cheating phone is the attested app with a hardware key. Each app computes its own half from its own file (A: t_BA − t_AA; B: t_BB − t_AB) and its hardware key signs the result.

**Signed, all of it:** session nonce, attempt number, its role (A or B), its own session key and the partner's, sample rate, its half (in samples), recording hash, and the OS output timestamps of its playback.

Without role and both keys in the signature, anyone combining the halves can swap them. Swapping flips the sign: 100 cm becomes −100 cm, which passes "flight < 60 cm". Whoever combines the halves must check: both signatures cover the same nonce and the same pair of keys, one role A and one role B, and −20 cm < flight < 60 cm.

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
- **Start time.** T0 is set a few seconds ahead, from a clock sync of 10 pings to the server. The budget: the partner's sound must land inside the −150/+250 ms search window. That window has to absorb the sync error between the two phones (half the round-trip asymmetry, tens of ms on cellular), the emitter's output latency (20–200 ms) and the listener's input latency. On the Android browser the observed arrivals already sat 74–138 ms late. Tighten the windows once native OS timestamps are available. Any miss is a failed measurement and triggers the retry.

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
3. Halves meet, at the server or directly over Bluetooth. flight < 60 cm → NEAR, otherwise not near.
4. Failed measurement: one automatic retry with fresh codes, then not near. The retry counts against the same false-accept budget.
5. Failure messages name the cause: "partner not heard, check volume", "recording glitch, trying again", "too far". Not a generic "try again, closer".
6. NEAR: hand the signed halves to the proof step (separate design).

**Privacy.** The server sees the pair: ephemeral-ID lookup, IP addresses, timing, the halves and the verdict. Having the halves meet over Bluetooth instead of at the server reduces that.

## 5. What is not proven yet

- Every JBL250 number comes from 12 sessions in one afternoon: one large quiet room, one Mac + Android pair, phones handheld, mid volume. The earlier small, echoey room wasn't walked with JBL250. There, 1 s noise dropped to 7.3 dB of margin, and the bell jingle read 145 cm for a true 200.
- iPhone is untested. In Safari, echo cancellation may be forced on; a native app with measurement mode avoids that.
- The cause of the Android glitch, native-app glitch rates and OS output-timestamp accuracy are all unmeasured.
- Clipping: the Mac clipped about 16k samples in the touch run and still read 8 cm. There's no clipping tolerance on record yet.
- A noisy venue: the bar adapts, but there's no noisy walk with JBL250.
- Each recording shows a few worklet discontinuities with zero missing frames. Probably a counting artifact; not explained yet.
- The 60 cm line: 30 cm read at most 35 and 100 cm at least 95, so both sit about 25 cm from the line. Handheld 60 cm runs read 60–90, so phones actually near 60 cm will flip between answers run to run. The UI should ask for "phones side by side", well inside the line.

## 6. One play per phone: what it gives up

On the walk every single JBL250 round was right on its own (24 of 24), so one play works when nothing goes wrong. What we lose is a second opinion: with two rounds, the rule required both to be usable and to agree within 40 cm. That was the only check that catches a bad round the other checks miss. With one play, one bad arrival decides the verdict.

What can make one arrival bad, and which way it pushes:

| Failure | Direction | Covered by |
| --- | --- | --- |
| Early false match on a phone's own sound | depends on the phone | the low tune (none seen on the walk); self-arrival vs OS output timestamp (native app) |
| Early false match on the partner's sound | toward NEAR | the bar (random chance about 1 in 30,000 per window); none seen, but only 48 cross arrivals measured |
| Android 20 ms glitch between the two sounds in B's file | toward NEAR (3.4 m) | flat-block check on the phone before signing (caught every one so far); OS timestamp check |
| Partner's sound late or missing | no measurement | retry once, then not near |
| Retry | a second draw at every failure above | count both attempts against one false-accept budget |

Cover for the lost second opinion:

1. **OS timestamp check** on a phone's own sound, once the native app exists (trust note, about 1 ms tolerance).
2. **Retry only after a failed measurement**, never after a valid "not near", and at most once.
3. **Watch the data.** The next walks should count early false matches on the partner's sound specifically; that is the failure that can fake NEAR and we have seen none so far in 48.

Tested and dropped: a **split check** (score each half of the 250 ms secret separately, require both halves to agree). On the 96 JBL250 arrivals it raised 4 false alarms (about 4%), and it missed the one real failure we have seen, the bell jingle's early false matches, because both halves skipped them together. Scripts: session scratchpad `splitcheck/`.

## 7. Next steps

1. Test app in the production shape: JBL250 once per phone, per-attempt codes, commit-then-reveal code release, role-bound signed transcript, optional silent output primer.
2. Walk: small room and big room, 0 / 30 / 100 / 200 cm, 5 runs each. Plus one noisy walk.
3. iPhone + Android walk.
4. Native Android recorder with AAudio timestamps: glitch rate, glitch cause, timestamp accuracy.
