# v2 protocol model (Lean)

Written 2026-11-10. Models [`../spec.md`](../spec.md) sections 2, 4 and 6 (FP1 to FP6). Plain Lean 4 core, no Mathlib, no dependencies. Toolchain `leanprover/lean4:v4.36.0-rc2`, as in `fv/v1`.

Nothing of v2 is built yet. This checks the spec, not code. The rule R2 (RC, RS, RT) is not in here.

## Files

| File | What it proves or holds |
|---|---|
| `Basic.lean` | Messages, the record, slots, lookups. `H`, `Sign`, `Verify` as fields of `Crypto`. HASH is `Crypto.HashInj`, SIG is `Crypto.Unforgeable`. The `TXO`, body and `peer` checks that the device and the reader share. |
| `Verdict.lean` | The v1 verdict math from `server/pop/verdict.py` (`self_os_ok`, `combine`, `decide`), in integers, cal = 0. Line cites in the file. |
| `Device.lean` | One honest device as a state machine. Inputs are any message, the app's send requests, the confirm tap, clock ticks, next attempt. `Reach` is every state some input list reaches. |
| `Record.lean` | `outcome` of a record and the reader's `verify`. |
| `Steps.lean` | What one step can do: sign one message under its guard (`step_sent`), accept one message that passed the checks (`step_got`), logs only grow, clock only forward. `Reach.roles`: signed messages are own, accepted ones are the partner's, same `sid`. |
| `FP1Order.lean` | `fp1_order`: a signed `REVEAL` for `k` comes after the partner's `RECC` and `SALT` for `k` and the device's own `RECC`. `fp1_recc_clock`: the step that signs `RECC` runs with the clock already past `t0 + 2.0 s`. |
| `FP2Code.lean` | `fp2_opens`: an accepted partner seed opens the accepted seed commit. `fp2_salt_after`: own `SALT` only after that commit. `fp2_one_seed` (HASH): any two runs that accepted the same seed commit for `k` accepted the same seed. |
| `FP3Blind.lean` | `fp3_after_txc`: own `TXO` only after the partner's `TXC`. `fp3_no_later`: after own `TXO` for `k`, nothing is signed for a later attempt. |
| `FP4Fresh.lean` | `fp4_sid`: every accepted message carries the device's `sid`. `fp4_fresh` (HASH): nothing from a session with another own random is accepted. |
| `FP5Agree.lean` | `fp5_perm`: the outcome doesn't depend on message order. `fp5_pair`: with no `FAIL`, it is `combine (t_A, t_B)`. `fp5_device`: one message per slot, sent and accepted; an accepted partner `TXO` opens the accepted `TXC`; never a retry `FAIL` next to its own `TXO`. |
| `FP6Reader.lean` | `fp6_value`: `verify` returns `sid` and `outcome` exactly when every check passes. `fp6_signed`, `fp6_tamper` (SIG): a record with an honest-role message the honest device never signed is rejected. `fp6_pinned` (HASH): a message named in `seen` is the only one in its slot. `fp6_txo_fixed` (HASH): D's `TXC` fixes its `TXO` content. |
| `Examples.lean` | Non-vacuity: one concrete honest-A run reaches the state each FP talks about, and `verify` says NEAR on its record. The crypto there is a toy, so HASH and SIG are shown satisfiable only on their own (see Model choices). Verdict values checked against `verdict.py`. |
| `Axioms.lean` | `#print axioms` of every main theorem. |

## Assumptions

- **HASH**, `Crypto.HashInj`: `H` is injective. A hypothesis of `fp2_one_seed`, `fp4_fresh`, `fp6_pinned`, `fp6_txo_fixed` only.
- **SIG**, `Crypto.Unforgeable pk S`: anything that verifies under `pk` is in `S`, the set its holder signed. A hypothesis of `fp6_signed` and `fp6_tamper` only.
- No `axiom` declarations. Every main theorem depends only on `propext`, `Classical.choice`, `Quot.sound` (the build prints them).
- The adversary picks every input to the honest device, in any order. The clock only adds, so it moves forward without a hypothesis.
- HIDE and RAND are not modeled. They are needed to read FP2 as "D can't steer its code" and FP3 as "the commit tells D nothing". Stated in the spec, not here.

## What it does not give

- Nothing about the air. A device signs whatever recording and half it likes (CN1).
- No two-device theorem. FP5's "both honest devices get the same outcome" is on paper from `fp5_perm`, `fp5_pair` and `fp5_device` (spec FP5).
- Liveness. The model says what an honest device never does, not that a run finishes.
- `fp6_pinned` says a message named in `seen` is pinned. That the honest device's `seen` holds every message it accepted is how `emit` builds it, not a separate theorem.
- K16 (two code draws per session), K4, K6, K9, K10 and K12 stay as in the spec.

## Model choices

These differ from the spec text, or fill a gap in it.

- **`INVITE` and `JOIN` are not modeled.** The config holds the five inputs of `sid`. FP4 assumes A's `JOIN` check pinned `r_A`.
- **`peer` is the list `seen`, not `H(seen)`.** The same under HASH, one hash layer less.
- **`TXC` waits for the device's own `REVEAL`.** The spec's "sends when" for `TXC` says only "F7 gave a half". But the partner's `TXO` check rederives `code_commit` from both seeds, so without the own `REVEAL` the partner would fail it. Worth adding to the spec.
- **A final body-check failure after the device already signed its one `FAIL` for the attempt** ends the session without a second `FAIL`. The spec allows one `FAIL` per attempt but doesn't say what happens here.
- **A partner `FAIL` with a final reason ends the session.** A retry one is held for the attempt switch, and answered at once with the device's own retry `FAIL` if it has not signed one and has not opened.
- **Before the confirm tap, every incoming message is dropped.** So nothing, not even a `FAIL`, is signed before the person confirmed (spec 2.2). The partner resends.
- **`verify` also checks `attempt < 2`** on every message. Without it a signed message for attempt 2 rode along unseen, since `outcome` reads only 0 and 1.
- **The reader checks two F10 and F4 rules a device enforces by its state.** A `TIME` must be from A (`bodyOk`). A message for attempt 1 needs a retry `FAIL` from both sides for attempt 0 in the record (`msgOk`, `retryBoth`).
- **`outcome` alone is not a check.** It reads the record as given. `verify` runs the F8 checks first.
- **All final reasons are one code.** The device signs `FAIL(final, 2)` for any failed body check. The reader doesn't check reasons, and no FP reads them.
- **Not modeled:** resends (same bytes, dropped as duplicates), encryption, timeouts and the 600 s end as clock rules (a timeout is just a `send .fail` the adversary may trigger), the local measurement F7, the `TIME` bounds at the reader (a reader has no clock), `commit_hash` in the transcript. `delta` is checked.
- **The toy crypto in `Examples.lean` is degenerate** (every hash 7, every signature valid). It shows the runs are reachable. It can't satisfy HASH or SIG. `freeC` shows HASH can hold, with a free hash type. Reachability and HASH together in one instance is not shown: the run needs a computable hash.

## Build

```
cd fv/v2/protocol
lake build
```

A clean build takes a few seconds. It must end with `Build completed successfully`, no `sorry` warning, and only `propext`, `Classical.choice`, `Quot.sound` in the `Axioms.lean` output.

## Hand mutants

Run 2026-11-10. Each mutant was applied to a copy, built, and the files restored. Guards are first checked by `step_sent` (the guard list `Allowed`) or `step_got`. So a guard is removed twice: from `Device.lean` alone (the "a" row, `Steps` must break), and also from `Allowed` (the "b" row, the property itself must break). For device mutants, a concrete run on the mutated device shows the property really fails; the same run on the real device doesn't.

| Id | Change | Breaks | Concrete run on the mutant |
|---|---|---|---|
| M1a | `REVEAL` without the partner's `RECC` | `step_sent` | `REVEAL` signed, no partner `RECC` held |
| M1b | same, also in `Allowed` | `inv1` (FP1) | |
| M2a | `RECC` without the clock gate | `step_sent` | `RECC` signed at clock 0, with `t0 = 5000` |
| M2b | same, also in `Allowed` | `inv1` (FP1) | |
| M3b | `SALT` without the partner's `SEEDC`, also in `Allowed` | `inv2` (FP2) | `SALT` signed, no partner `SEEDC` held |
| M4 | receiver skips the seed opening check | `inv2` (FP2) | |
| M5b | `TXO` without the partner's `TXC`, also in `Allowed` | `inv3` (FP3) | `TXO` signed, no partner `TXC` held |
| M6a | next attempt without the "no own `TXO`" guard | `step_k` | no counterexample |
| M6b | same, also in `step_k` | `inv3` (FP3) | |
| M7b | receiver skips the `sid` check, also in `EnvFacts` | `Reach.roles` (FP4) | |
| M8b | retry `FAIL` after own `TXO`, also in `Allowed` | `inv5` (FP5 b) | retry `FAIL` signed next to own `TXO` |
| M9b | receiver skips the one-per-slot check, also in `EnvFacts` | `inv5` (FP5 b) | |
| M10a | reader skips the signature check | `msgOk_parts` | |
| M10b | same, also in `msgOk_parts` | `fp6_signed` (FP6) | |
| M11b | reader skips one-per-slot, also in `Checked` | `fp6_pinned` (FP6) | |
| M12 | receiver drops the confirm guard (`envOk`) | `Steps` | an otherwise valid `SEEDC` with rate 1 before the tap: the mutant signs a final `FAIL`, the real device signs nothing |
| M13 | reader takes a `TIME` from B (`bodyOk`) | `Examples` | `recA` plus a B-signed `TIME` verifies on the mutant, is rejected on the real reader |
| M14 | reader drops the attempt-1 check (`msgOk`) | `msgOk_parts`, then `Examples` | `recA` plus A's final `FAIL(0)` plus a B `SEEDC(1)` verifies as incomplete on the mutant, is rejected on the real reader |

**M6 is a redundant guard.** Without it the proof breaks, but FP3 still holds. The one-`FAIL`-per-attempt rule already keeps a retry `FAIL` and an own `TXO` apart, and the next attempt needs an own retry `FAIL`. The concrete run tried exactly that and stayed on attempt 0. Keep the guard: it says the rule in one place.

M12 to M14 were run 2026-11-10 in the second review. M7b, M9b and M11b break where the proof reads the removed check, so they show the proof needs it, not that the property is false. M1, M2, M3, M5 and M8 have a concrete run.

## Review log

**2026-11-10, first pass, Codex** (gpt-6-astra, high, read-only) read the model, the spec and `verdict.py`. Nine findings. Each was checked against the files and fixed or answered, then rebuilt and the mutants rerun.

- **Confirmed, fixed.** (1) The F8 `delta` check was missing: `Tx` has `delta` now and `txOk` checks it. (2) A partner retry `FAIL` wasn't answered, so the device could still open after it: now it answers with its own retry `FAIL`. (3) `verify` took attempts above 1 and ignored them: now `attempt < 2`. (5) A body-check `FAIL` could be signed before the confirm tap: now nothing is accepted before it. (7) FP1's "past it now means past it when signed" was wrong: `fp1_recc_clock` states the moment of signing. (8) `fp2_one_seed` was already given by one-per-slot: it now compares two runs, which is where HASH matters. (9) The README said the run reaches every FP's hypotheses: it doesn't reach HASH or SIG, now said plainly.
- **Answered in the docs, not changed.** (4) `outcome` alone gives NEAR without checks: by design, `verify` checks first; said in `Record.lean` and here. (6) Final reasons are one code: no FP or reader reads them; listed under Model choices.
- **Passed.** The verdict math: check order, absolute value, sign and ties match `verdict.py` for positive rates.

These fixes had no second Codex pass.

**2026-11-10, second pass, Codex** (gpt-6-astra, high, read-only) reviewed the model after the first fixes, then rechecked the fixes below. Each claim was checked against the files and by building.

- **Confirmed, fixed.** (1) The reader took a `TIME` signed by B: `bodyOk` passed every `TIME` and the `peer` check didn't look at the sender. So D could add one to a record that holds the honest A's `TXO`, a message A never accepted. Now `bodyOk` needs role A (M13). (3) The pre-confirm example didn't test the confirm guard: its message had `seen = [7]` with nothing sent, so the `peer` check dropped it anyway. It now sends an otherwise valid message; on the mutant without the guard, A signs a final `FAIL` (M12). (5, from the recheck) The reader took attempt-1 messages after a final `FAIL`: `peer` only asks that a `FAIL` for 0 is named, not that both are retry ones. D could append its `SEEDC(1)` to a record with A's final `FAIL(0)` and turn NOT_NEAR into incomplete. Now `msgOk` needs both retry `FAIL`s for 0 (M14). No false NEAR came from (1) or (5).
- **Confirmed, not changed.** (2) F8's `t.commit_hash = H(partner RECC)` is not in `Tx` and not checked. Already listed under Model choices. Moved to Open.
- **Confirmed, out of scope.** (4, from the recheck) If both sides failed attempt 0 before any `SEEDC`, D can append a `SEEDC(0)` with empty `seen` later. The reader takes it. The outcome reads attempt 1 and doesn't change, and FP6 speaks only of messages for the attempt that holds the honest `TXO`. In Open.
- **Agreed with, no change.** `fp5_pair`, `fp6_value` and `fp6_result` are close to definitions: they say what the functions compute, not that the functions follow the spec. FP6 is a set of lemmas, not one device-to-reader theorem; `fp6_pinned` assumes the `seen` membership. Both already said above.
- **Passed.** The first-pass fixes (`delta`, retry `FAIL` answer, `attempt < 2`, confirm guard, `fp1_recc_clock`, two-run `fp2_one_seed`), the verdict math, and the mutant claims for M1 to M11.

## Open

- `commit_hash` (F8) is not modeled or checked. Adding it needs the partner's `RECC` message, not just its root, in `txOk`.
- A late `SEEDC(0)` from D, with empty `seen`, can sit in a record whose attempt 0 had none. Harmless to the outcome.
- FP6 is not one theorem from a reachable honest device to the reader. That every accepted message lands in `seen` is how `emit` builds it, not proved.
- The mutant patches and concrete runs are not kept in the repo. The table is the record of them.

