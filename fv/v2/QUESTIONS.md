# v2 questions for the owner

Each question has the decision or the default taken in [`spec.md`](spec.md), and what changes if the owner picks otherwise. Q1 to Q4 are the roadmap's decisions ([`../ROADMAP.md`](../ROADMAP.md), "Decisions"). The rest came up while writing the spec.

[ADR 0001](adr/0001-direct-webrtc-link-and-plain-words.md) decides Q4, Q5, Q9 and Q13. The owner decided Q1, Q2, Q3, Q8 and Q19. Q7 and Q16 wait for stage 3. The rest keep their default.

**`BAR` waits on stage 3.** The rule's `BAR`, filter taps, loudness floor and bit widths come from real recordings (roadmap stage 3), which hasn't run. Until then every rule theorem is stated for any `BAR`, any taps, any floor of 1 or more.

## From the roadmap

**Q1. Deadline.** What date is the submission?
- *Decided:* no deadline. Work follows the roadmap order, and the cut list is not in force.
- *If a date comes:* the cut list in the roadmap applies. FP2 to FP4 are the first proofs to drop.

**Q2. Do proofs count?**
- *Decided:* proofs are optional. v2 is a core library, so it never requires a proof. The implementer who builds on it chooses whether a NEAR needs one. A NEAR without a proof means two keys signed two numbers. The log carries proofs if there are any.
- *If an implementer requires proofs:* the protocol needs a step where each device checks the partner's proof before the outcome counts, and the circuit needs a capture length, pinned public inputs, and `pair` tied to the phone proofs (roadmap stage 4, last row). Phone proving cost (25 s, 1.74 GB in one bench) becomes part of every run. Web can't take part (Q4).

**Q3. Who vouches for devices?**
- *Decided:* vouching is optional. The core has none: every key is just a key, and attestation is outside the model. An implementer can add it.
- *Owner's idea, not designed:* make the proof's inputs and outputs extendable, with an optional input for app or device attestation. The cheapest shape is one extension value that the transcript signature and the proof both bind and that the core does not read. An implementer puts the hash of an attestation there, and the reader checks the attestation itself outside the circuit. Checking an Apple or Google attestation inside the circuit is a separate and larger job. The extension value has to go into the stage 4 circuit bundle, because any later circuit change needs a new verifier key. A browser has no attestation to attach.
- *If readers check attestation:* `JOIN` and a message from A carry an attestation each, with a challenge from the partner. Untested for Apple App Attest between peers. Android needs Google's root pinned (CN6). FP6 then also says "the keys were attested", under one more assumption.
- *If a small attestation service:* that service is a trusted party again, only for keys, not verdicts. It needs its own spec.

**Q4. Web.**
- *Decided:* a browser can take part, paired with a phone. The target runs are phone with phone and phone with browser. Browser with browser is not a target for now.
- *What it costs:* the browser has no prover, so in a phone with browser run only the phone can attach a proof. The laptop needs a camera to scan the phone's QR code. EVP needs the laptop as role A.

## New

**Q5. Transport.**
- *Decided:* a direct WebRTC data channel, set up by a QR code in each direction. No STUN or TURN server, so both devices must be on the same local network. Every message is still signed.
- *If a forwarding server or a STUN server is added later:* the protocol is the same. Only completeness changes.

**Q6. Tool.**
- *Default:* Lean, plain core for the protocol, one property per file. Tamarin isn't installed.
- *If Tamarin:* FP1 to FP4 move there and gain a real Dolev-Yao attacker. FP5, FP6 and the rule stay in Lean.

**Q7. Rule parameters.** `BAR`, taps, `FLOOR`, widths.
- *Default:* parametric until stage 3.
- *When stage 3 lands:* plug the numbers in, add the bit-width proofs, and rerun `circuit-cases`.

**Q8. Retry after a gap is sent.**
- *Decided:* retry as in v1 (C22). `impossible_flight` and a self timing mismatch retry once, also after both gaps are sent. v2 does not expect modified apps, so a written warning is enough.
- *The warning:* a dishonest device can send a gap that gives `impossible_flight`, see the honest gap, and use it in attempt 1. New codes on the retry do not help, because the gap comes from the distance and the audio delays of the two devices, not from the code. Spec hole K3.
- *Not taken:* never retry once a gap is sent. That closes K3 and costs an honest pair a session whenever the pair gives `impossible_flight` or a self timing mismatch.

**Q9. Pairing channel.**
- *Decided:* two-way. B scans A's QR code, then A scans B's. Each device takes the other's key from a QR code, so an outsider can't swap keys between two honest devices (K6).
- *Not taken:* one QR code from A to B, where A relies on its person's confirm tap against a swapped key.

**Q10. Chain each message to the one it answers (`peer`).**
- *Default:* yes. Without it, a dishonest device can swap its own messages after seeing the honest ones and still show a valid log (K1).
- *If no:* FP6 only says "nobody but the signer changed it", which is much weaker.

**Q11. Random blind in the gap hash.**
- *Default:* yes, 32 random bytes hashed inside `GAP_HASH`, sent in `GAP_VALUE`.
- *If no:* hiding the gap rests on the signature being unpredictable (K2).

**Q12. Failure messages.**
- *Default:* a signed `FAIL(reason)`. The next attempt needs both sides' retry `FAIL` for the last one. A `FAIL` in the log makes that attempt NOT_NEAR.
- *If failures are silent (just stop):* the log can't say why, and the two devices may disagree on whether to retry.

**Q13. Encrypt payloads.**
- *Decided:* the spec adds no encryption of its own. WebRTC encrypts the link, and the two QR codes carry the certificate fingerprints. Not modeled.

**Q14. Start time.**
- *Default:* A picks `t0 = now + 5 s` on its wall clock. B accepts if `t0` is 1 s to 30 s ahead on its own clock, else a retry `FAIL(time)`.
- *If ping-based offset estimation (draft F4):* more messages. Neither choice touches safety: no property reads `t0`.

**Q15. Gates on the recording hash and the seed.**
- *Default:* `REC_HASH` after the own capture ends (`t0 + 2.0 s`). `SEED_VALUE` after holding the partner's `REC_HASH` and sending its own. Today's server gate was `t0 + 1.2 s`, "sounds over".
- *If the earlier gate:* about 0.8 s faster. FP1's clock part weakens to "sounds over".

**Q16. Loudness floor.**
- *Default:* `FLOOR >= 1`, any value, as fix 2 says.
- *If higher:* very quiet noise and a small DC offset can fail too, whenever `E · cn2` stays under the floor (K11). Needs honest scores from stage 3.

**Q17. Partner side: any passing lag, or the first?**
- *Default:* any passing lag at the named lag, as v1 (gap 6).
- *If first:* the partner side gets the self side's sweep, more constraints, and the gap's meaning gets stricter.

**Q18. Codes.**
- *Default:* `key_X = H("bed" ‖ sid ‖ role_X ‖ k ‖ seed_X ‖ salt_Y)`, rendered by a new bit-exact integer generator (K9).
- *If codes stay on the numpy FFT path:* devices and readers can't rederive them, so `code_commit` isn't rechecked and FP6 loses that check.

**Q19. How many attempts per session.**
- *Decided:* two, as today (C22). A dishonest device can fail attempt 0 on purpose and pick the better of two codes (spec hole K16).
- *If one:* no second draw, and no retry logic at all. An honest pair loses a session on every glitch and has to start over, with a new confirm tap.

## From the Lean model (`protocol/`)

**Q20. Small spec gaps the model had to fill.** Details in `protocol/README.md`, "Model choices".
- *Default taken in the model:* `GAP_HASH` waits for the device's own `SEED_VALUE` (the partner's `GAP_VALUE` check needs both seeds). Nothing incoming is accepted before the confirm tap. A partner retry `FAIL` is answered at once. A final check failure after the device's one `FAIL` ends the session with no second `FAIL`. `verify` rejects attempts above 1.
- *If the owner wants otherwise:* change `Device.lean` or `Log.lean` and rerun the build. None of these changes an FP statement. The spec text should get the same lines either way.
