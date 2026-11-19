# fv/v2: the serverless protocol and the fixed rule

v2 has two changes. The server goes away: the two devices run the protocol between them over a direct WebRTC link, and anyone with the log and the two keys can recheck it. No server takes part in a run. And the detection rule gets fixed (match on filtered audio, a loudness floor, `cq` in the template energy). See [`../ROADMAP.md`](../ROADMAP.md).

The link and the words follow [ADR 0001](adr/0001-direct-webrtc-link-and-plain-words.md).

**Nothing of v2 is built.** No v2 circuit, no device protocol code. So the proofs here are about a model of a draft spec, not about code that runs.

## Files

- [`spec.md`](spec.md): the protocol spec (roadmap stage 2). Messages, what each device checks, the verdict, the detection rule, the properties FP1 to FP6 and the rule properties, known holes K1 to K19.
- [`QUESTIONS.md`](QUESTIONS.md): the design choices, the owner's decisions, and what changes if one is picked otherwise. Q7 and Q16 wait for stage 3.
- [`adr/`](adr/0001-direct-webrtc-link-and-plain-words.md): ADR 0001, the direct WebRTC link and the words.
- [`adr/0002`](adr/0002-plain-names-in-the-lean-models.md): ADR 0002, plain names in the Lean models (proposed).
- [`protocol/`](protocol/README.md): one honest device as a state machine, the reader's `verify`, and FP1 to FP6. Plain Lean, no Mathlib.
- [`zkp/`](zkp/README.md): the v2 rule as a pure function at one lag. Score ceiling, silence rejected, gain route closed. Lean with Mathlib.
- [`tla/`](tla/README.md): two honest devices together, in TLA+, checked with TLC. Agreement, the link closing, finishing, the timeout and retry rules. No crypto. See [ADR 0003](adr/0003-tla-for-two-devices.md).

## Status

| Part | Main theorems | Builds | Review | Mutants |
|---|---|---|---|---|
| `spec.md` | none, it's the spec | n/a | yes, except the link and words change from ADR 0001 | n/a |
| `protocol/` | `fp1_order`, `fp1_rec_hash_clock`, `fp2_matches`, `fp2_one_seed`, `fp3_after_gap_hash`, `fp3_next_attempt`, `fp3_next_attempt_reach`, `fp4_sid`, `fp4_fresh`, `fp5_perm`, `fp5_pair`, `fp5_device`, `fp5_retry_fail`, `fp5_final_fail`, `fp5_retry_fail_reach`, `fp6_value`, `fp6_signed`, `fp6_tamper`, `fp6_pinned`, `fp6_gap_fixed` | yes, 32 jobs, no `sorry`, only `propext`, `Classical.choice`, `Quot.sound` | yes | M1 to M18, each breaks a proof or an example, except M6, a redundant guard: it breaks a proof but the property still holds |
| `tla/` | `Agreement`, `NearStays`, `AcceptOrder`, `Liveness`, `StuckExplained` (TLC, no proofs) | TLC passes, see `tla/README.md` | yes | seven, each fails a property, see `tla/README.md` |
| `zkp/` | `ceiling`, `pass_needs_bar_ge_one`, `silent_rejected`, `no_partner_pass_in_silence`, `ratio_scale`, `gain_route`, `all128_both_rejected` | yes, 18190 jobs, no `sorry`, 28 axiom lines, all within `propext`, `Classical.choice`, `Quot.sound` | yes | one per fix, plus the full v1 rule |

Assumptions (hash injective, signatures unforgeable) are hypotheses or structure fields, never `axiom` declarations.

## What it does not show

- **No code is checked.** There is no v2 circuit and no device code. The models follow a draft spec that has been reviewed but never built.
- **The air is not modeled.** A device still signs whatever recording and gap it likes (CN1). A NEAR without a proof means two keys signed two numbers.
- **CN1 to CN5 stay.** A helper next to the partner still wins (CN4, CN5).
- **A forced retry leaks the gap (K3).** A device that sends a wrong gap or a wrong self timing on purpose forces a retry and then knows the honest gap. The owner keeps the v1 retry and accepts this with a warning (Q8).
- **FN1 stays.** The last sender ends up holding the full log and can walk away.
- **The tone is not proved rejected.** Only the gain trick is closed. The tone run is a `circuit-cases` and real-recording question.
- **`BAR`, filter taps, floor and bit widths are unknown** (stage 3 hasn't run). The rule theorems hold for any of them.
- **No two-device theorem in Lean.** The Lean protocol model says what one honest device never does. Two honest devices together, the link closing and finishing are checked in TLA+ (`tla/`), for a model without crypto and over three transcript values, not proved.
- HIDE and RAND (spec section 1) are stated, not modeled.
- **No restart, no expiry, nothing tied to the recorder finishing.** Neither model has a device that forgets what it signed (K18). The Lean clock may jump forward, and FP1 still holds, but nothing ties the gate to the real end of the capture (K19). The TLA+ step `CaptureOver` is an abstract capture-over step, tied to no clock and no recorder. A NEAR log has no expiry or stated purpose (K17).

## Next, in roadmap order

1. Stage 3: run the v2 rule offline on real recordings. Set `BAR`, taps, floor, widths. Then plug them into `zkp/` and add bit-width proofs.
2. Stage 4: the circuit bundle. Then redo `Bar`, `Arrival`, `PartnerGlue`, `Chain` against it (see the table in `zkp/README.md`).
3. Stage 5: device protocol code. It starts with a test of the WebRTC link (ADR 0001, "Not tested"). Then check the Kotlin against `protocol/`, and close its Open list (`commit_hash`).
4. Stage 6: two-phone run, `circuit-cases` rerun.

## Build

```
cd fv/v2/protocol && lake build   # plain Lean, seconds
cd fv/v2/zkp && lake exe cache get && lake build   # Mathlib, heavy
```

Never run two Lean jobs at once on a small machine.
