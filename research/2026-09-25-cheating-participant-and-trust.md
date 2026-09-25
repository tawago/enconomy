# Cheating participant: where the defense lives, 2026-09-25

Question: can one of the two phones cheat the sound-bound ranging, and does the audio analysis or a ZK circuit have to stop it?

Answer: yes, it can cheat. Neither the analysis nor the circuit can stop it, because the cheater writes its own input. The defense is the app: a hardware-backed key plus platform attestation that the app is genuine. The analysis keeps one small job, a timestamp cross-check, described below.

This makes concrete the "trusted-client assumption" from `sound-bound/docs/2026-09-23-handoff.md`.

Diagrams: https://claude.ai/artifact/3da3hjLeNFmfPnQh8vYtYW

## The formula splits by file

`sound-bound/analysis.py:351`:

    delta = (t_BA - t_AA) - (t_BB - t_AB)
             A's file only    B's file only

Let u be (moment B's speaker fired) - (moment A's speaker fired), and τ the one-way flight time.

    A's file:  t_BA - t_AA = u + τ
    B's file:  t_BB - t_AB = u - τ
    delta                  = 2τ   (u cancels)

u is unknown because it holds the clock offset and each phone's speaker lag, 20 to 200 ms. The subtraction exists only to cancel it. It cancels only if both files report the same u, and nothing checks that.

Playing both codes at the same moment changes nothing. Scheduled u is 0, but real u still holds the offset and the lag. Separating overlapping codes is easy (CDMA-style, 1 s code gives about 47 dB of matched-filter gain), but it is not a security feature.

## The attack

A is far away. A cheap phone sits near B on a call and relays both sounds, adding R (for example 80 ms) each way. τ really grows by R. Honest files would read FAR.

A cuts its own code out of its recording and pastes it back 2R later. A's file now claims A fired 2R late, so A's u is 2R smaller than B's u:

    (u_A + τ) - (u_B - τ) = (u_A - u_B) + 2τ = -2R + 2R = 0   → NEAR

B cannot object. B's file looks exactly like A sitting next to B with a speaker that lagged R. The only witness of when A's speaker fired is A's own mic.

| Attacker | Controls | Result |
| --- | --- | --- |
| Outside relayer | the air path, can only add delay | looks far, fails |
| One cheater | air path + own file = one half of the formula | looks near, wins |
| Two colluders | both files | anything, no sound needed |

A secret per-role seed does not help: the edit moves A's own code, which A always knows.

## Why the audio layer can't fix it

- **Room echo / reciprocity / shared noise checks.** They show that some speaker and mic were in B's room. The relay phone was, so its echoes are genuine. They catch lazy fakes (synthetic files, a different room), not this.
- **Deeper problem.** With a device in B's room, A can skip the edit and just give that device the code. Then an honest 30 cm ranging happens. Acoustics can bind a measurement to a device, never to an identity.
- In distance-bounding terms: the edit is distance fraud, the outside relayer is mafia fraud (already beaten by ranging), and the accomplice device is terrorist fraud (the hard one).

## Why ZK can't fix it

A proof shows a computation over an input is correct. The prover supplies the recording, so a forged file goes in as the input. A full matched filter in-circuit is also 10^8 to 10^9 constraints, which is not provable on a phone. The circuit's job is binding and privacy only (see below).

## Where the defense lives: the app

- **iOS:** Secure Enclave key (not exportable) + App Attest.
- **Android:** Keystore / StrongBox key + Key Attestation + Play Integrity.

What they prove: this genuine, unmodified app on a real, non-rooted device signed these bytes. What they do not prove: that the bytes are what the mic heard. No phone signs audio in hardware.

That is enough for the main attacks:

| Attack | Status |
| --- | --- |
| Edit own file | blocked: the genuine app does not edit |
| Accomplice device signs as A | blocked: A's key cannot leave A's phone |
| Physical self-path spoof (tape the mic, feed own sound back delayed) | mostly blocked by the timestamp check below |
| Rooted phone that still passes attestation | rare, arms race |
| Lending the whole phone | unsolvable, out of scope |

## What each layer still owes

**App**
- Hold the signing key in the enclave or StrongBox.
- Attach the attestation.
- Sign: session nonce, hash of the recording, OS output timestamps for each played buffer, device model.

**Audio analysis** (the one remaining audio-level job)
- Take A's firing time from the signed OS output timestamp (AAudio timestamps on Android, output latency values on iOS), not only from the self-hear.
- Reject the round if the self-hear disagrees with the OS time by more than that model's known latency tolerance.
- Reject the round if the self-path does not look like that model's speaker-to-mic path (level, frequency response).
- The tolerance is the cheat budget: every 1 ms buys about 17 cm of fake closeness. Target about 1 ms.

**ZK circuit** (option C, the small one)
- Extends `circuits/copresence.circom`.
- Public: nullifier, session root or nonce, thresholds (max flight_cm, min DRR, min score), root of accepted measurer or app keys.
- Private: seed, both identity keys and signatures, flight_cm, drr, score, the measurer's signature, the exact timestamp.
- Proves: seed commitment, signatures, values within thresholds, nullifier. About 20 to 30k constraints. circom + Groth16 is fine; switch to Noir if the circuit ever grows.

## Open

- How accurate are the OS output timestamps on real devices? This decides whether a ~1 ms tolerance is realistic. Test on the Mac + Android pair from the walk.
- A browser build cannot attest. The attack holds there until the native app exists (`androidApp/`, `iosApp/`).
- The product has to choose what is proven present: a device, a key, or a person. This note assumes "a key that can't be copied".
