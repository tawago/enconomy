# v2 questions for the owner

Written 2026-11-10, while the owner was away. Each question has the default taken in [`spec.md`](spec.md) and what changes if the owner picks otherwise. Q1 to Q4 are the roadmap's decisions ([`../ROADMAP.md`](../ROADMAP.md), "Decisions"). The rest came up while writing the spec.

**`BAR` waits on stage 3.** The rule's `BAR`, filter taps, loudness floor and bit widths come from real recordings (roadmap stage 3), which hasn't run. Until then every rule theorem is stated for any `BAR`, any taps, any floor of 1 or more.

## From the roadmap

**Q1. Deadline.** What date is the submission?
- *Default:* unknown. Work follows the roadmap's "Must" row first.
- *If a date comes:* the cut list in the roadmap applies. FP2 to FP4 are the first proofs to drop.

**Q2. Do proofs count?**
- *Default:* the protocol doesn't force them. Each reader decides. A NEAR without a proof means two keys signed two numbers. The record carries proofs if there are any.
- *If proofs are required:* the protocol needs a step where each device checks the partner's proof before the outcome counts, and the circuit needs a capture length, pinned public inputs, and `pair` tied to the phone proofs (roadmap stage 4, last row). Phone proving cost (25 s, 1.74 GB in one bench) becomes part of every run. Web can't take part (Q4).

**Q3. Who vouches for devices?**
- *Default:* nobody. Every key is just a key. Attestation is outside the model.
- *If readers check attestation:* `JOIN` and a message from A carry an attestation each, with a challenge from the partner. Untested for Apple App Attest between peers. Android needs Google's root pinned (CN6). FP6 then also says "the keys were attested", under one more assumption.
- *If a small attestation service:* that service is a trusted party again, only for keys, not verdicts. It needs its own spec.

**Q4. Web.**
- *Default:* not in the first v2 run. Android first, as the roadmap says.
- *If web is in:* the laptop has no prover and no way to advertise a link. With the mailbox it can still run the protocol, so only proofs are missing for it. EVP needs the laptop as role A.

## New

**Q5. Transport.**
- *Default:* an untrusted mailbox. It can drop, delay, reorder, replay. Every message is signed.
- *If a direct link:* the protocol is the same. Only completeness changes.

**Q6. Tool.**
- *Default:* Lean, plain core for the protocol, one property per file. Tamarin isn't installed.
- *If Tamarin:* FP1 to FP4 move there and gain a real Dolev-Yao attacker. FP5, FP6 and the rule stay in Lean.

**Q7. Rule parameters.** `BAR`, taps, `FLOOR`, widths.
- *Default:* parametric until stage 3.
- *When stage 3 lands:* plug the numbers in, add the bit-width proofs, and rerun `circuit-cases`.

**Q8. No retry after a half is open.**
- *Default:* once a device sent its transcript (`TXO`) for an attempt, it never retries it. `impossible_flight` and a partner's bad self timing become final. Spec hole K3.
- *If retries stay as in C22:* the partner learns the honest half and can use it in attempt 1. FP3 then holds only for attempt 0.

**Q9. Pairing channel.**
- *Default:* one-way QR from A to B. B checks A's key. A relies on its person's confirm tap.
- *If two-way (NFC tap, or B shows a QR back):* A checks B's key too, and an active outsider on the mailbox can't swap keys between two honest devices (K6). Adds a field to the invite flow, no property gets weaker.

**Q10. Chain each message to the one it answers (`peer`).**
- *Default:* yes. Without it, a dishonest device can swap its own messages after seeing the honest ones and still show a valid record (K1).
- *If no:* FP6 only says "nobody but the signer changed it", which is much weaker.

**Q11. Random blind in the transcript commit.**
- *Default:* yes, 32 random bytes hashed inside `TXC`, sent in `TXO`.
- *If no:* hiding the half rests on the signature being unpredictable (K2).

**Q12. Failure messages.**
- *Default:* a signed `FAIL(reason)`. The next attempt needs both sides' retry `FAIL` for the last one. A `FAIL` in the record makes that attempt NOT_NEAR.
- *If failures are silent (just stop):* the record can't say why, and the two devices may disagree on whether to retry.

**Q13. Encrypt mailbox payloads.**
- *Default:* yes, after `JOIN`, with a key from `ECDH(sk_self, pk_partner)` and `sid`. `JOIN` itself is in the clear. Not modeled.
- *If no:* the mailbox reads halves and seeds too, not just the keys and randoms from `JOIN`. Roadmap stage 5 says the mailbox should store nothing it can read.

**Q14. Start time.**
- *Default:* A picks `t0 = now + 5 s` on its wall clock. B accepts if `t0` is 1 s to 30 s ahead on its own clock, else a retry `FAIL(time)`.
- *If ping-based offset estimation (draft F4):* more messages. Neither choice touches safety: no property reads `t0`.

**Q15. Gates on the commit and reveal.**
- *Default:* `RECC` after the own capture ends (`t0 + 2.0 s`). `REVEAL` after holding the partner's `RECC` and sending its own. Today's server gate was `t0 + 1.2 s`, "sounds over".
- *If the earlier gate:* about 0.8 s faster. FP1's clock part weakens to "sounds over".

**Q16. Loudness floor.**
- *Default:* `FLOOR >= 1`, any value, as fix 2 says.
- *If higher:* very quiet noise and a small DC offset can fail too, whenever `E · cn2` stays under the floor (K11). Needs honest scores from stage 3.

**Q17. Partner side: any passing lag, or the first?**
- *Default:* any passing lag at the named lag, as v1 (gap 6).
- *If first:* the partner side gets the self side's sweep, more constraints, and the half's meaning gets stricter.

**Q18. Codes.**
- *Default:* `key_X = H("bed" ‖ sid ‖ role_X ‖ k ‖ seed_X ‖ salt_Y)`, rendered by a new bit-exact integer generator (K9).
- *If codes stay on the numpy FFT path:* devices and readers can't rederive them, so `code_commit` isn't rechecked and FP6 loses that check.

**Q19. How many attempts per session.**
- *Default:* two, as today (C22). A dishonest device can fail attempt 0 on purpose and pick the better of two codes (spec hole K16).
- *If one:* no second draw, and no retry logic at all. An honest pair loses a session on every glitch and has to start over, with a new confirm tap.

## From the Lean model (`protocol/`)

**Q20. Small spec gaps the model had to fill.** Details in `protocol/README.md`, "Model choices".
- *Default taken in the model:* `TXC` waits for the device's own `REVEAL` (the partner's `TXO` check needs both seeds). Nothing incoming is accepted before the confirm tap. A partner retry `FAIL` is answered at once. A final check failure after the device's one `FAIL` ends the session with no second `FAIL`. `verify` rejects attempts above 1.
- *If the owner wants otherwise:* change `Device.lean` or `Record.lean` and rerun the build. None of these changes an FP statement. The spec text should get the same lines either way.
