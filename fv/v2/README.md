# fv/v2: the serverless protocol and the fixed rule

v2 has two changes. The server goes away: the two devices run the protocol between them over a mailbox, and anyone with the record and the two keys can recheck it. And the detection rule gets fixed (R2: match on filtered audio, a loudness floor, `cq` in the template energy). See [`../ROADMAP.md`](../ROADMAP.md).

**Nothing of v2 is built.** No v2 circuit, no device protocol code. So the proofs here are about a model of a draft spec, not about code that runs.

## What was done, 2026-11-10

- [`spec.md`](spec.md): the protocol spec (roadmap stage 2). Messages, what each device checks, the verdict, the rule R2, the properties FP1 to FP6 and the rule properties, known holes K1 to K16. Two Codex passes, all findings checked and fixed.
- [`QUESTIONS.md`](QUESTIONS.md): open choices, the default taken for each, and what flips if the owner picks otherwise.
- [`protocol/`](protocol/README.md): one honest device as a state machine, the reader's `verify`, and FP1 to FP6. Plain Lean, no Mathlib.
- [`zkp/`](zkp/README.md): the rule R2 as a pure function at one lag. Score ceiling, silence rejected, gain route closed. Lean with Mathlib.

## Status

| Part | Main theorems | Builds | Last review | Mutants |
|---|---|---|---|---|
| `spec.md` | none, it's the spec | n/a | Codex, two passes, 2026-11-10. The last three fixes had no third pass | n/a |
| `protocol/` | `fp1_order`, `fp1_recc_clock`, `fp2_opens`, `fp2_one_seed`, `fp3_after_txc`, `fp3_no_later`, `fp4_sid`, `fp4_fresh`, `fp5_perm`, `fp5_pair`, `fp5_device`, `fp6_value`, `fp6_signed`, `fp6_tamper`, `fp6_pinned`, `fp6_txo_fixed` | yes, clean rebuild, no `sorry`, only `propext`, `Classical.choice`, `Quot.sound` | Codex, two passes, 2026-11-10 | M1 to M14, each breaks a proof or an example. M6 is a redundant guard |
| `zkp/` | `ceiling`, `pass_needs_bar_ge_one`, `silent_rejected`, `no_partner_pass_in_silence`, `ratio_scale`, `gain_route`, `all128_both_rejected` | yes, 18190 jobs, no `sorry`, same three axioms | Codex, one pass plus a recheck, 2026-11-10 | one per fix, plus the full v1 rule |

Assumptions (hash injective, signatures unforgeable) are hypotheses or structure fields, never `axiom` declarations.

## What it does not show

- **No code is checked.** There is no v2 circuit and no device code. The models follow a draft spec that nobody but Codex has reviewed.
- **The air is not modeled.** A device still signs whatever recording and half it likes (CN1). A NEAR without a proof means two keys signed two numbers.
- **CN1 to CN5 stay.** A helper next to the partner still wins (CN4, CN5).
- **FN1 stays.** The last sender ends up holding the full record and can walk away.
- **The tone is not proved rejected.** Only the gain trick is closed. The tone run is a `circuit-cases` and real-recording question.
- **`BAR`, filter taps, floor and bit widths are unknown** (stage 3 hasn't run). The rule theorems hold for any of them.
- **No two-device theorem, no liveness.** The protocol model says what one honest device never does.
- HIDE and RAND (spec section 1) are stated, not modeled.

## Next, in roadmap order

1. Owner answers `QUESTIONS.md`, at least Q2, Q3, Q8, Q19.
2. Stage 3: run R2 offline on real recordings. Set `BAR`, taps, floor, widths. Then plug them into `zkp/` and add bit-width proofs.
3. Stage 4: the circuit bundle. Then redo `Bar`, `Arrival`, `PartnerGlue`, `Chain` against it (see the table in `zkp/README.md`).
4. Stage 5: device protocol code. Then check the Kotlin against `protocol/`, and close its Open list (`commit_hash`).
5. Stage 6: two-phone run, `circuit-cases` rerun.

## Build

```
cd fv/v2/protocol && lake build   # plain Lean, seconds
cd fv/v2/zkp && lake exe cache get && lake build   # Mathlib, heavy
```

Never run two Lean jobs at once on a small machine.
