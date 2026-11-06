# Informal spec: the protocol today, and a draft without the server

Written 2026-11-06, for the formal verification work. This is step 1 of the primer in `fv/v1/docs/01-primer.md`, one level up: the whole protocol, not one circuit block.

- **Part 1** describes `main` at 53604e3, from reading `server/pop/` and `app/composeApp/`. It says what the code does, including where that falls short of what we'd want.
- **Part 2** is a design draft. No code exists for it and nobody has reviewed it.
- **Part 3** maps both onto the FV blocks, rows and gaps in `fv/v1/docs/`.
- **Part 4** lists places where the FV notes disagreed with the code: what was fixed, and what is still open.

**Links:** `fv/v1/docs/` travels with a clone. `docs/generated/` is still in the gitignored `/docs` at the repo root, so links there will be dead in a fresh clone.

Rule ids (C1, F1, ...) are stable, so proofs can cite them. Each rule names who enforces it: **server**, **app**, **circuit** or **contract**. An app rule only binds an honest device.

## Words

- **A, B**: the two devices. A is the host, B the guest.
- **Code**: a device's secret 0.25 s sound (the "bed"). The public two-note tune played with it is not secret.
- **half**: one device's gap between two arrivals in its own recording, in frames. A: `t_BA - t_AA`. B: `t_BB - t_AB`. `t_XY` is the arrival of X's sound in Y's recording.
- **flight**: `c/2 x (half_A/sr_A - half_B/sr_B)`, with c = 34300 cm/s.
- **Commit**: a signed record holding a hash of the recording. It does not hold the half.
- **Transcript**: the signed record holding the half and the timing values.
- **Attempt**: one play-and-record round. A session has at most 2.

## Part 1: today

### Who is trusted

The server is trusted for all of these:

- It holds the seed, derives every code and picks the session nonce.
- It enforces message order and decides the verdict.
- It signs the credential, the code attestation and the chain attestation.

A cheating server can report any verdict and sign a chain attestation for any two enrolled keys. It can't forge signatures for a given device key. But `verify_record` takes the public keys from the record itself (`verdict.py:177`), and the server writes the record, so it can list keys it made and sign with those. A reader must already know the two device keys for the check to mean anything. The Safe guard still needs both owners' signatures.

### Enrolment

- **C1 (server).** `device_id = sha256(pubkey)[:16]`. The enrol nonce is single use.
- **C2 (server).** Android: at least 2 certs, the chain links up, the leaf key equals the enrolled key, the leaf has the attestation extension, and its challenge equals the nonce. The root is not pinned, so a self-made chain passes and gets `attested: true` (`attestation.py:5`). The chain needs no secret of the leaf key, so it can name someone else's key.
- **C3 (server).** iOS: App Attest is checked against Apple's root, and `clientDataHash` ties it to the signing key. It does not show the signing key is in hardware; the key kind is only reported (`main.py:462`). The default app build does not send it (`POP_PAID=0`), so the server refuses that enrol unless `POP_ALLOW_UNATTESTED` is on.
- **C4 (server).** With `POP_ALLOW_UNATTESTED` (any platform) or `POP_ALLOW_WEB` (web only), a device enrols with no attestation. Enrol asks for no signature from the key itself, unless the device also sends a calibration. Any enrol replaces the existing row for that `device_id` (`store.py:85`), so a re-enrol can change a key's `attested` flag and credential without proof of the key.
- **C5 (server).** The credential (SBcred3) is issued whenever the device sends a holder commit, attested or not (`main.py:441`).

### Pairing

- **C6 (server).** The join token lasts 120 s and works once. A device can't join its own session. A session lasts at most 600 s.
- **C7 (app, guest only).** The guest checks `sha256(partner pubkey)[:8]` against the invite. The host has no such check.
- **C8 (server).** Both devices must confirm before arming. With a World ID policy, both humans must also be verified, with different nullifiers.

### One attempt

- **C9 (server).** The normal state order is `created -> joined -> confirmed -> started -> done`, and any live state can go to `aborted`. A `/fail` from `confirmed` can also retry or finish the session, with no measurement. A retry goes back to `confirmed` with `attempt + 1` and fresh codes.
- **C10 (server).** Arm needs the current attempt, a sample rate of 36000 to 96000, and a device-reported RTT of at most 300 ms. Once both are armed, `t0 = now + 3 s`.
- **C11 (server).** `bed_key = sha256("pop-v1|seed|JBL250|role|attempt|bed")`. A device gets its own code at arm. The seed is never sent.
- **C12 (app).** A plays at `t0`, B at `t0 + 0.95 s`. Each captures 2.5 s, starting at `t0 - 0.5 s`.
- **C13 (app, v2, on by default when the phone's rate has v2 constants).** A device finds its own arrival with `Popt2Rule.earliest` around its expected position plus its calibration. Failure reports `capture_failed`, `glitch`, `self_not_heard` or `self_timestamp_mismatch`. If v2 is off or the rate has no entry, the v1 rule in `PopRound` runs instead.
- **C14 (server).** A commit is accepted only from `t0 + 1.2 s` on, must be signed, and must carry the right role, attempt, nonce and version. A bad commit changes nothing. A different second commit is refused.
- **C15 (server).** The partner's code is released only in the response to a device's own accepted commit.
- **C16 (app).** A device finds the partner's arrival, computes its half, then signs the transcript.
- **C17 (server).** A transcript needs that device's commit first, and is checked in this order: layout, signature, version, `pk_self`, role, nonce, attempt, `pk_partner`, sample rate, `commit_hash`, recording hash. v2 adds `delta` and `code_commit`. A failure in this list is final NOT_NEAR. These change nothing and return 409: a validly signed transcript for an older attempt, a transcript before the commit, and a second different transcript.
- **C18 (server).** Neither device can read the partner's half while its own transcript could still count. `view()` exposes the result only once it exists. If the session ends after one transcript is in (the partner's bad transcript, a final `/fail` or a final timeout), the result shows that one half to the partner. That half can't help, because the session is over.

### Verdict

`verdict.py:147` is a pure function of the two transcripts and, for v1, each device's calibration `cal_us`, using exact fractions:

- **C19.** Roles are A and B, nonce and attempt match, the keys are crossed and different.
- **C20.** `self_os_delta` is at most 50 ms, around the device's calibration in v1 and around 0 in v2. A failure here retries. It's a number the device reports, and nothing recomputes it.
- **C21.** `flight <= -20` retries as `impossible_flight`. `flight >= 60` is final NOT_NEAR. Otherwise NEAR.
- **C22.** Measurement failures retry once, and the second one is final. `too_far` never retries. The transcript deadline is `t0 + 20 s`.

### After the verdict

- **C23 (circuit, optional).** The server takes proofs only after NEAR, for the final attempt, on POPT v2 at 48 kHz, from a device with an SBcred3. A failed proof leaves NEAR standing. `phone` checks, on opened windows of the committed recording, that the self arrival is the first passing lag, and that the partner's code passes at one signed lag. Passing means `BAR x match >= loudness`, and silence passes. `pair` checks the distance range on committed halves.
- **C24 (server).** Chain attestation requires NEAR, a valid context, two verified humans and attested devices, unless flags say otherwise. It does not look at ZK.
- **C25 (contract).** A presence spend through the live Safe guard needs an attestation signed by the key pinned on that Safe, plus signatures from the two different owners mapped to the attested devices. The server signs with `data/attest.pem` by default; the demo Safe pins a dev key, so the server must run with that key (`contracts/README.md:102`). With no presence, the guard allows only an announced recovery call after its delay. `PhoneVerifier` and `PairVerifier` are on Sepolia, but no guard uses them: the `NoirPresenceVerifier` wrapper is not deployed.

### Properties that hold today

Each assumes an honest server.

- **CP1, order.** The server gives no device the partner's code before it holds that device's signed commit for this attempt. (C14, C15) The commit fixes a hash, and nothing checks at that point that a real recording is behind it. This protects something only if passing needs the partner's code. Silence passes the partner check without it, a tone may too, and without proofs the half isn't tied to audio (CN1). A colluding partner can also hand over its own code at arm.
- **CP2, blind half.** A device can't read the partner's half from the server while its own transcript could still count. A retry shows only the reason, for example `impossible_flight`, not the number. This doesn't stop devices sharing halves outside the server. (C18)
- **CP3, binding.** A NEAR verdict comes from two transcripts signed by the two session keys, for one nonce and attempt. NOT_NEAR needs no such pair: one bad transcript, a `/fail` or a timeout can end the session. (C17, C19)
- **CP4, honest accuracy.** If both devices are honest, the speaker lag and clock offset `u` cancel. In seconds: `half_A/sr_A = u + tau - d_A` and `half_B/sr_B = u - tau + d_B`, where `d` is the trip from a device's speaker to its own mic. So the difference is `2 tau - d_A - d_B`, and flight reads a little under the true distance. This is physics plus arrival accuracy. It is measured, not provable.
- **CP5, bounded retries.** At most 2 attempts per session, and each measurement needs both devices to arm again. A `/fail` from one device can use up an attempt with no measurement.

### Properties that do not hold

These are the ones a reader may assume. Attack names match `docs/generated/attack-case-*.png`, except that the case 2 image shows only the no-mic version (CN3). None of these attacks has been built.

- **CN1.** The verdict does not depend on any audio. The half is a signed number. Without a proof, nothing ties it to the recording.
- **CN2.** Nothing shows a recording came from a mic.
- **CN3.** Nothing limits an emission to one device's speaker. In case 2, a planted speaker plays L's code near P. L must then pick a half in a band about 5 ms wide. A speaker alone must guess that. A timing mic that hears P's public tune gives the timing and can likely produce a passing half on the plaintext path. On the proof path, silence or a tone may also remove the relay mic, the one that gets P's code into the recording, but L still needs the timing. The case 2 image shows only the no-mic version and says it fails.
- **CN4.** Cases 3 and 4 work by reporting a false half. Case 5 needs no false number, because a helper runs an honest measurement and L signs. No timing check can see it.
- **CN5.** NEAR is not "this person was here". At best it says that this key took part in a measurement.
- **CN6.** `attested: true` is not a claim about hardware on Android today. (C2)
- **CN7.** The recording does not stay on the device. Upload is on by default, and delegated proving sends audio windows.

## Part 2: draft without the server

### Goals

Keep CP1, CP2, CP3 and CP5, as worded in Part 1. CP3 covers NEAR only. Remove the party who can forge a verdict or collect recordings. Run the same over a direct link or a dumb mailbox: every message is signed, so the transport is not trusted.

Not a goal: stopping cases 3, 4 and 5. They survive this change. L still reports its own half.

### Protocol

- **F1, pairing.** Each device sends its full public key and 32 random bytes (`r_A`, `r_B`). `sid = sha256("pop-p2p-v1" | pk_A | pk_B | r_A | r_B | context)`. Both devices check the other's key, closing the one-sided C7. Both people confirm.
- **F2, code commit.** For each attempt, each device picks a random `seed` and sends a signed `sha256(seed)`. It must hold the partner's before going on.
- **F3, salt.** After F2, each device sends fresh random `salt`. `code = derive(seed, sid, partner's salt, role, attempt)`.
- **F4, time.** The devices agree `t0` over the link and estimate their clock offset by pinging each other. Play and capture follow C12.
- **F5, recording commit.** Same as C14: a signed hash of the recording, sent after the schedule ends.
- **F6, reveal.** A device sends its seed only after it holds the partner's valid commit from F5. Each device checks the seed against F2. A mismatch is final.
- **F7, measure.** Same as C16.
- **F8, blind half.** Each device sends a signed `sha256(transcript | sig)`, and only after holding the partner's does it send the transcript and signature.
- **F9, verdict.** Each device runs C19 to C21 unchanged, if both transcripts are v2. If v1 stays, F11's record must carry each device's signed `cal_us`, because C20 needs it. The result is exact, so honest devices agree.
- **F10, retry.** Same reasons and limit as C22, with new seeds. Each honest device counts for itself.
- **F11, record.** The result is the pair of keys, `r_A`, `r_B`, the seed commits, salts, seeds, commits, transcripts and signatures. Anyone can rerun it, including deriving the codes, which `verify_record` can't do today (`verdict.py:174`).

### Why each step exists

- **F2 before the recording:** without it, a device could choose its sound after the fact. Today the server fixes it.
- **F3 and a derived code:** a device can't pick its own code or search seeds for a weak one. This keeps gap 5 closed. It does not help gap 3: the click works on most ordinary codes, and the loudness floor closes it on most codes. Today gap 5 is closed by the server pinning `code_commit`.
- **F6 after F5:** this is CP1. It protects the code only if passing needs the partner's code.
- **F8:** this is CP2. Without it, the second sender sees the first half and writes the exact number it needs. Today C18 gives this for free.

### Properties to prove

Two-party, against one dishonest device, with no trusted server:

- **FP1, order.** An honest device reveals its seed only after holding the partner's recording commit. This proves order, not that the half came from audio.
- **FP2, fixed code.** After F3, a device's code has one value, or the honest partner aborts.
- **FP3, blind half.** An honest device's half is hidden until the partner has committed to its transcript.
- **FP4, freshness.** A record from an old session does not verify for a new `sid`, since each honest device added fresh randomness.
- **FP5, agreement.** Two honest devices that both finish compute the same verdict.
- **FP6, third-party check.** A verifier given only the record gets the same verdict as C19 to C21 (given `cal_us` in the record, if v1 stays), and rejects any changed field.

### What gets worse

- **FN1, no fair finish.** The last sender in F8 ends up holding a full record while the other holds nothing, then can walk away. P may never learn that L has a record. Another round only moves the problem.
- **FN2, no one vouches for devices.** Each reader must check attestation itself. Nothing replaces C2, C3 and the device check in C24 yet.
- **FN3, less replay help on chain.** For a Safe, the Safe nonce inside `safeTxHash` stops replay today, and that stays. What goes away is the server's expiry on the attestation. Any other consumer must mark `sid` as used.
- **FN4, World ID is unassigned.** Only the server calls the Portal today. Not studied.
- **FN5, web proving has no home.** Delegated proving goes away, or moves to a helper who sees the audio.
- **FN6, one more real unknown.** F4's clock estimate and F1's link have not been tried on iPhone to Android, or from a browser.

### Open choices

1. Direct link or mailbox. Same protocol, so this can wait.
2. Whether attestation goes in F1 at every session, or a device carries it once.
3. What replaces `issuer` in the `phone` circuit: a list of allowed keys, the keys as public inputs, or nothing.
4. How `code_commit` is bound without POPCC1. One option is a per-side code hash in each transcript, with `pair` checking that the two sides match when crossed.
5. Whether a NEAR that matters must carry proofs. Without them, CN1 still holds.

## Part 3: what this means for the FV work

| Item in `fv/v1/docs/` | Today | Without the server |
| --- | --- | --- |
| Block A (signature, credential). `Signed.lean`, review passed, Opus only | Issuer signs the credential | Changes: open choice 3 |
| Blocks B, C, D, E, F. Lean theorems exist for all five. B and C are Opus only | Same | Unchanged, if samples and the arrival rule stay |
| Block G (`pair`) | Same | Math unchanged. Who proves it moves to a device, which then needs both halves, both salts and both keys. F8 gives the halves, so the salts need a step too |
| Block H (`code_commit`). `Commit.lean`, Opus only | Four templates, one hash, signed by the issuer | Changes: open choice 4 |
| `phone_sound`, `presence_sound` (`Chain.lean`, Opus only, closing review found no proof defect). These restate C23 under named hypotheses | What the checks enforce, on signed numbers. Silence meets them all. Says nothing about CN1 to CN5 | Redo with any change to Block A, H or `pair` |
| Row 10 (order) | Rests on trusting the server | Becomes FP1, a two-party model |
| Row 11 (freshness) | Rests on trusting the server | Becomes FP4 |
| Row 14 (attestation) | See Part 4 | Moves to each verifier |
| Gaps 1, 2, 3, 6 | Open | Unchanged. They are circuit gaps. Gap 2 also needs the app rule changed (`Popt2Rule.kt:99,171`) |
| Gap 5 | Refuted because the server pins the code | Reopens unless codes are derived as in F3 |
| Gap 7 | Open. The low rating is about gain. It closes with gaps 1 and 2 only on the proof path; on the plaintext path the half is free anyway | Unchanged |
| Gap 10 | Open on the Noir path only. Not live: the live attestation path binds devices, on the server's word | Needed: the Noir path is the only one left, and the keys are the only identity left |

Rows 10 and 11 already call for a protocol tool such as Tamarin. Part 2 is a better target than Part 1: Part 1's properties all assume the honest server, so a model of it mostly restates that assumption.

No protocol proof reaches CN2 to CN5. FV can show the steps are right. It can't show the device told the truth about the air.

## Part 4: where the FV notes disagree with the code

Items marked resolved were fixed in `fv/v1/docs/` on 2026-11-06. The text keeps what the note used to say. Items marked open are not fixed.

1. **Resolved. Row 14 of `06-app-invariants.md`** said the issuer signs SBcred3 only for an attested key. `main.py:441` issues for any device that enrols with a holder commit, and C2 and C4 make enrolment weak. With flags off, an unattested device can't reach line 441, but a self-made Android chain can. The opening of that file leaned on this too.
2. **Resolved. Gap 7** was rated "low, follows from 1 and 2". That fits the proof path. On the plaintext path the half is free regardless of those gaps (CN1), because no circuit runs before NEAR. Fixing gaps 1 and 2 doesn't change this unless proofs become required. "Low" still rates the gain. The wrong part was that fixes to gaps 1 and 2 close it.
3. **Resolved. Scope.** The Lean work covers circuits that run only after the verdict, on a path no live consumer requires (C23 to C25). Any claim about where phones were has to say so. The ENS bridge uses proofs for an optional mark, but doesn't need them (`bridge/bridge.py:404-410`). `AppPasses.lean` is the exception, and gap 2 could still reach live NEAR through the stock app, if the tone survives a real mic, because the app runs the same test before the verdict (`Popt2Rule.kt:171`).
4. **Resolved. Gap 10** was rated high without saying the live guard doesn't use the Noir verifier (`contracts/deployments/11155111.json`). Now: high only if a Noir guard is deployed. Not live.
5. **Resolved. Stale evidence in `05`, `04` and the spike README.** "Nothing ran in `nargo`" was too strong: Sept fixtures and the Sepolia proofs ran the real circuit. The crafted spike cases ran later: `circuit-cases/RESULTS.md`. `tone/tone_test.py` now exists, run on synthetic audio only (`logs/tone-synthetic.txt`).
6. **Resolved. "App bugs cost only completeness" in `06`.** On the plaintext path a bad half goes straight into the verdict (`verdict.py:165`).
7. **Open. Case 2 image.** `docs/generated/attack-case-2-planted-speaker.png` shows no mic and says "Fails today". CN3 and `research/2026-11-05-layers-and-removing-the-server.md:45` say a mic likely wins. The image is out of step.
8. **Open. `contracts/README.md:138`** says the server needs both owner sigs to attest. `refusal()` doesn't check them (`chainatt.py:29-60`).
9. **Open. `contracts/DEPLOYMENTS.md:29`** says the server doesn't sign `pop-safe-v2` yet. `chainatt.py` does.
10. **Resolved. `nargo` control run.** `Prover_A` solves and `Prover_sample` fails at Merkle: `logs/nargo-control.txt`. The crafted cases have now run too, with throwaway keys: `circuit-cases/RESULTS.md`.
11. **Resolved. Gap 2's severity.** Medium, from one quiet real recording plus simulation (`logs/tone-room-2.txt`, `logs/tone-distortion-sim.txt`). Not demonstrated in a real room.
12. **Resolved. Where these notes live.** The FV notes moved to `fv/v1/docs/`. The images in `docs/generated/` stay in the gitignored folder.
13. **Open. New gaps between server and circuit.** C17 and C19 read whole keys and `commit_hash`. The circuit never reads partner Y or `commit_hash` (`Signed.junk_accepted`). So on the proof path those two rest on the server having checked them. A window past the end of the capture also passes C23's partner test (`Commit.past_capture_witness`), because the transcript has no capture length. Not in `next-version-fixes.md` yet.

## Not checked

- The app and server rules were read in code. Nothing here ran on a device for this note.
- C25 was read in code, line by line, on 2026-11-06. Nothing ran.
- C23's circuit rules now have Lean theorems on a hand-written model (Part 3). Nothing in Lean ran the app, the server or a device.
- No chain read: "live" and "deployed" mean the deployment records in `contracts/deployments/`. The link between the demo Safe's key and `server/data/attest-demo.pem` comes from `contracts/README.md:102` only. Nobody derived the public key from that file.
- Part 2 has had no review, no model and no code. Expect changes.
