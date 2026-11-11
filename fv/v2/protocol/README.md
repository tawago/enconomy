# v2 protocol model (Lean)

Models [`../spec.md`](../spec.md) sections 2, 4 and 6 (FP1 to FP6). Plain Lean 4 core, no Mathlib, no dependencies. Toolchain `leanprover/lean4:v4.36.0-rc2`, as in `fv/v1`.

Nothing of v2 is built yet. This checks the spec, not code. The detection rule (RC, RS, RT) is not in here.

Names follow [ADR 0001](../adr/0001-direct-webrtc-link-and-plain-words.md).

## Status

| Builds | Main theorems | Review | Mutants |
|---|---|---|---|
| yes, 32 jobs, no `sorry`, only `propext`, `Classical.choice`, `Quot.sound` | FP1 to FP6 as in the table below | Codex, Fable 5.2 | M1 to M18 as in the table below. None for `fp5_final_fail`, the self timing mismatch retry runs, or the run with a hidden `GAP_VALUE` (spec K3) |

## Files

| File | What it proves or holds |
|---|---|
| `Basic.lean` | Messages, the log, slots, lookups. `H`, `Sign`, `Verify` as fields of `Crypto`. HASH is `Crypto.HashInj`, SIG is `Crypto.Unforgeable`. The `GAP_VALUE`, body and `peer` checks that the device and the reader share. |
| `Verdict.lean` | The v1 verdict math from `server/pop/verdict.py` (`self_os_ok`, `combine`, `decide`), in integers, cal = 0. Line cites in the file. Check order, absolute value, sign and ties match `verdict.py` for positive rates. |
| `Device.lean` | One honest device as a state machine. Inputs are any message, the app's send requests, the confirm tap, clock ticks, next attempt. `Reach` is every state some input list reaches. |
| `Log.lean` | `outcome` of a log and the reader's `verify`. |
| `Steps.lean` | What one step can do: sign one message under its guard (`step_sent`), accept one message that passed the checks (`step_got`), logs only grow, clock only forward. `Reach.roles`: signed messages are own, accepted ones are the partner's, same `sid`. |
| `FP1Order.lean` | `fp1_order`: a signed `SEED_VALUE` for `k` comes after the partner's `REC_HASH` and `SALT` for `k` and the device's own `REC_HASH`. `fp1_rec_hash_clock`: the step that signs `REC_HASH` runs with the clock already past `t0 + 2.0 s`. |
| `FP2Code.lean` | `fp2_matches`: an accepted partner seed matches the accepted seed hash. `fp2_salt_after`: own `SALT` only after that hash. `fp2_one_seed` (HASH): any two runs that accepted the same seed hash for `k` accepted the same seed. |
| `FP3Blind.lean` | `fp3_after_gap_hash`: own `GAP_VALUE` only after the partner's `GAP_HASH`. `fp3_next_attempt`: a step that moves to the next attempt has no own `GAP_VALUE` for the old one, or holds both transcripts with a verdict that asks for a retry. |
| `FP4Fresh.lean` | `fp4_sid`: every accepted message carries the device's `sid`. `fp4_fresh` (HASH): nothing from a session with another own random is accepted. |
| `FP5Agree.lean` | `fp5_perm`: the outcome doesn't depend on message order. `fp5_pair`: with no `FAIL`, it is `combine (t_A, t_B)`. `fp5_device`: one message per slot, sent and accepted; an accepted partner `GAP_VALUE` matches the accepted `GAP_HASH`. `fp5_retry_fail`: a step that signs a retry `FAIL` has no own `GAP_VALUE` for the attempt, or holds both transcripts with a verdict that asks for a retry. `fp5_final_fail`: a step that signs a final `FAIL` is the receipt of a message that passed the envelope checks and failed its body check. |
| `FP6Reader.lean` | `fp6_value`: `verify` returns `sid` and `outcome` exactly when every check `verify` runs passes. That is the model's list: no `commit_hash`, no `TIME` bounds, no check that the log is complete. `fp6_signed`, `fp6_tamper` (SIG): a log with an honest-role message the honest device never signed is rejected. `fp6_pinned` (HASH): a message named in `seen` is the only one in its slot. `fp6_gap_fixed` (HASH): D's `GAP_HASH` fixes its `GAP_VALUE` content. |
| `Retry.lean` | The retry rule in every reachable state, for every attempt `j`. `fp3_next_attempt_reach`: a device past attempt `j` that signed `GAP_VALUE` for `j` holds both transcripts for `j`, and `combine` gives `impossible` or `selfTs`. `fp5_retry_fail_reach`: the same for a device that signed both `GAP_VALUE` and a retry `FAIL` for `j`. The step lemma `get?_step`: a lookup in `sent ++ got` keeps its value as the logs grow. |
| `Examples.lean` | Non-vacuity: one concrete honest-A run reaches the state each FP talks about, and `verify` says NEAR on its log. The crypto there is a toy, so HASH and SIG are shown satisfiable only on their own (see Model choices). Runs for the retry after both `GAP_VALUE`s: A's own retry `FAIL`, A's answer to B's retry `FAIL`, and the move to attempt 1, each with an `impossible_flight` pair; the same with a self timing mismatch, B's offset (own `FAIL` and answer path) and A's; no retry with a NEAR pair. A log D hands over without A's `GAP_VALUE(0)` that still verifies with an attempt-1 NEAR (spec K3). Verdict values checked against `verdict.py`. |
| `Axioms.lean` | `#print axioms` of every main theorem. |

## Assumptions

- **HASH**, `Crypto.HashInj`: `H` is injective. A hypothesis of `fp2_one_seed`, `fp4_fresh`, `fp6_pinned`, `fp6_gap_fixed` only.
- **SIG**, `Crypto.Unforgeable pk S`: anything that verifies under `pk` is in `S`, the set its holder signed. A hypothesis of `fp6_signed` and `fp6_tamper` only.
- No `axiom` declarations. Every main theorem depends only on `propext`, `Classical.choice`, `Quot.sound` (the build prints them).
- The adversary picks every input to the honest device, in any order. The clock only adds, so it moves forward without a hypothesis.
- HIDE and RAND are not modeled. They are needed to read FP2 as "D can't steer its code" and FP3 as "the gap hash tells D nothing". Stated in the spec, not here.

## What it does not give

- Nothing about the air. A device signs whatever recording and gap it likes (CN1).
- No two-device theorem. FP5's "never NEAR on one honest device and NOT_NEAR on the other" is on paper from `fp5_perm`, `fp5_pair`, `fp5_device` and `fp5_retry_fail` (spec FP5). The two outcomes can still differ: if the link closes mid-exchange, one side can hold NEAR and the other be incomplete, or one hold `.pair .impossible` and the other `.fail .B`.
- Liveness. The model says what an honest device never does, not that a run finishes.
- `fp5_pair`, `fp6_value` and `fp6_result` are close to definitions. They say what the functions compute, not that the functions follow the spec.
- K3. The model does not show that a forced retry hands D the honest gap, since HIDE is not modeled. `Examples.lean` only shows that a log D hands over can hide the forced retry.
- `fp6_pinned` says a message named in `seen` is pinned. That the honest device's `seen` holds every message it accepted is how `emit` builds it, not a separate theorem.
- K16 (two code draws per session), K4, K9, K10 and K12 stay as in the spec. The spec closes K6 with the second QR code. That is outside this model, which has no `INVITE` or `JOIN`.

## Model choices

These differ from the spec text, or fill a gap in it.

- **`INVITE` and `JOIN` are not modeled.** The config holds the five inputs of `sid`. FP4 assumes A's `JOIN` check pinned `r_A`. The link is not modeled either: the adversary picks every input, so a reliable, ordered link is one case of that.
- **`peer` is the list `seen`, not `H(seen)`.** The same under HASH, one hash layer less.
- **`GAP_HASH` waits for the device's own `SEED_VALUE`.** The spec's "sends when" for `GAP_HASH` says only "F7 gave a gap". But the partner's `GAP_VALUE` check rederives `code_commit` from both seeds, so without the own `SEED_VALUE` the partner would fail it. Worth adding to the spec.
- **A final body-check failure after the device already signed its one `FAIL` for the attempt** ends the session without a second `FAIL`. The spec allows one `FAIL` per attempt but doesn't say what happens here.
- **A partner `FAIL` with a final reason ends the session.** A retry one is held for the attempt switch, and answered at once with the device's own retry `FAIL` if it has not signed one and has not sent its `GAP_VALUE`. After its own `GAP_VALUE` it answers only when the pair asks for a retry.
- **The retry after both `GAP_VALUE`s is one Bool, `pairRetry`.** It is true when the device holds both transcripts for the current attempt and `combine` gives `impossible` or `selfTs`. It guards the retry `FAIL`, the answer to a partner's retry `FAIL`, and the move to the next attempt. This is the v1 rule C22, kept by the owner (spec F10, Q8). One `FAIL` per attempt is enforced in `gate`.
- **Before the confirm tap, every incoming message is dropped.** So nothing, not even a `FAIL`, is signed before the person confirmed (spec 2.2). The partner resends.
- **`verify` also checks `attempt < 2`** on every message. Without it a signed message for attempt 2 rode along unseen, since `outcome` reads only 0 and 1.
- **The reader checks two F10 and F4 rules a device enforces by its state.** A `TIME` must be from A (`bodyOk`). A message for attempt 1 needs a retry `FAIL` from both sides for attempt 0 in the log (`msgOk`, `retryBoth`). The spec's `verify` list (section 4) has both, and says that the `FAIL` body carries the `retry` bit the reader reads.
- **A `FAIL` names no partner message** (`answerOf .fail = none`). Its `seen` holds every accepted partner message, as for any message. The spec's F10 row says "none".
- **`outcome` alone is not a check.** It reads the log as given. `verify` runs the F8 checks first.
- **All final reasons are one code, and retry reasons are free.** The device signs `FAIL(final, 2)` for any failed body check. A retry `FAIL` from `act` carries whatever reason the app gives. The reader doesn't check reasons, and no FP reads them. So "no timeout after the own `GAP_VALUE`" is held by the `pairRetry` guard, not by a reason code: after its `GAP_VALUE` the device signs a retry `FAIL` only when the pair asks for one, whatever reason it names. A final `FAIL` comes only from a failed body check (`fp5_final_fail`).
- **A bad `TIME` and a later good one.** In `recv`, the `!mine c st .gapVal` test on a `TIME` out of bounds can never be false: a device holds its own `GAP_VALUE` only after its `REC_HASH`, which needs an accepted `TIME`, and then the `TIME` slot is full. A `TIME` out of bounds is not accepted, so the slot stays free, and a later `TIME` in bounds is accepted after the device signed `FAIL(time)`. It sets `t0`, but the device signs nothing more for the attempt (`gate`). Harmless, and left as is.
- **The config is not checked.** `Cfg` may have `pkA = pkB` or an own `sr` outside 36000..96000, which the spec rules out at `INVITE`/`JOIN` and F2. With equal keys `combine` gives `mismatch`, which is final. A partner rejects an own rate out of range in its F2 body check. `verify` checks `pkA ≠ pkB`.
- **Not modeled:** resends (same bytes, dropped as duplicates), encryption, timeouts and the 600 s end as clock rules (a timeout is just a `send .fail` the adversary may trigger), the local measurement F7, the `TIME` bounds at the reader (a reader has no clock), `commit_hash` in the transcript. `delta` is checked.
- **The toy crypto in `Examples.lean` is degenerate** (every hash 7, every signature valid). It shows the runs are reachable. It can't satisfy HASH or SIG. `freeC` shows HASH can hold, with a free hash type. Reachability and HASH together in one instance is not shown: the run needs a computable hash.

## Build

```
cd fv/v2/protocol
lake build
```

A clean build takes a few seconds. It must end with `Build completed successfully (32 jobs)`, no `sorry` warning, and only `propext`, `Classical.choice`, `Quot.sound` in the `Axioms.lean` output.

## Hand mutants

Each mutant was applied, built, and the files restored. Guards are first checked by `step_sent` (the guard list `Allowed`) or `step_got`. So a guard is removed twice: from `Device.lean` alone (the "a" row, `Steps` must break), and also from `Allowed` (the "b" row, the property itself must break). For device mutants, a concrete run on the mutated device shows the property really fails; the same run on the real device doesn't.

| Id | Change | Breaks | Concrete run on the mutant |
|---|---|---|---|
| M1a | `SEED_VALUE` without the partner's `REC_HASH` | `step_sent` | `SEED_VALUE` signed, no partner `REC_HASH` held |
| M1b | same, also in `Allowed` | `inv1` (FP1) | |
| M2a | `REC_HASH` without the clock gate | `step_sent` | `REC_HASH` signed at clock 0, with `t0 = 5000` |
| M2b | same, also in `Allowed` | `inv1` (FP1) | |
| M3b | `SALT` without the partner's `SEED_HASH`, also in `Allowed` | `inv2` (FP2) | `SALT` signed, no partner `SEED_HASH` held |
| M4 | receiver skips the check of the seed against its hash | `inv2` (FP2) | |
| M5b | `GAP_VALUE` without the partner's `GAP_HASH`, also in `Allowed` | `inv3` (FP3) | `GAP_VALUE` signed, no partner `GAP_HASH` held |
| M6a | next attempt without its retry guard (`!mine gapVal \|\| pairRetry`) | `step_k` | no counterexample |
| M6b | same, also in `step_k` | `fp3_next_attempt`, `invNext` (FP3) | |
| M7b | receiver skips the `sid` check, also in `EnvFacts` | `Reach.roles` (FP4) | |
| M8a | retry `FAIL` from `act` without its guard (`!mine gapVal \|\| pairRetry`) | `step_sent` | NEAR pair: the mutant signs a retry `FAIL` next to its own `GAP_VALUE`, the real device signs nothing |
| M8b | same, also in `Allowed` | `fp5_retry_fail`, `invFail` (FP5 b) | |
| M9b | receiver skips the one-per-slot check, also in `EnvFacts` | `inv5` (FP5 b) | |
| M10a | reader skips the signature check | `msgOk_parts` | |
| M10b | same, also in `msgOk_parts` | `fp6_signed` (FP6) | |
| M11b | reader skips one-per-slot, also in `Checked` | `fp6_pinned` (FP6) | |
| M12 | receiver drops the confirm guard (`envOk`) | `Steps` | an otherwise valid `SEED_HASH` with rate 1 before the tap: the mutant signs a final `FAIL`, the real device signs nothing |
| M13 | reader takes a `TIME` from B (`bodyOk`) | `Examples` | `logA` plus a B-signed `TIME` verifies on the mutant, is rejected on the real reader |
| M14 | reader drops the attempt-1 check (`msgOk`) | `msgOk_parts`, then `Examples` | `logA` plus A's final `FAIL(0)` plus a B `SEED_HASH(1)` verifies as incomplete on the mutant, is rejected on the real reader |
| M15 | `act`: `pairRetry` replaced by `false` (the old rule) | `Examples`: A's own retry `FAIL` on an `impossible_flight` pair, and the non-vacuity example for the `Retry.lean` theorems | on that pair the mutant signs no retry `FAIL` of its own; it still answers B's |
| M16 | `recv`: `pairRetry` replaced by `false` in the answer to a partner's retry `FAIL` | `Examples`: the answer run (`inputsAnswer`) | on that pair the mutant leaves B's retry `FAIL` unanswered and stays on attempt 0 |
| M17 | `adv`: `pairRetry` replaced by `false` | `Examples`: all three retry runs | on that pair the mutant stays on attempt 0 |
| M18a | `recv`: answer to a partner's retry `FAIL` without its guard | `step_sent` | NEAR pair: the mutant answers B's retry `FAIL` next to its own `GAP_VALUE`, the real device doesn't |
| M18b | same, also in `Allowed` | `fp5_retry_fail`, `invFail` (FP5 b) | |

M6 and M8 remove the whole guard, `pairRetry` branch included. M15 to M17 replace `pairRetry` by `false` in one of the three places that use it, so the device never retries after its own `GAP_VALUE`. They break only examples: a stronger guard keeps every safety proof true, so only a run can show the retry went missing.

**M6 is still a redundant guard.** Without it the proof breaks, but FP3 still holds. The move to the next attempt needs an own retry `FAIL`, and after its own `GAP_VALUE` the device signs one only under `pairRetry` (the guards of M8 and M18). The concrete run tried both orders on a NEAR pair and stayed on attempt 0. Keep the guard: it says the rule in one place.

**M8a and M18a sign a retry `FAIL` on a NEAR pair, but don't move on.** The `adv` guard still holds them on attempt 0. That breaks FP5 (b), not FP3.

M1 to M5, M7 and M9 to M14 were run before the retry rule after both `GAP_VALUE`s and the ADR 0001 renames, and were not rerun after them. M7b, M9b and M11b break where the proof reads the removed check, so they show the proof needs it, not that the property is false. M1, M2, M3, M5 and M8 have a concrete run.

## Open

- `commit_hash` (F8) is not modeled or checked. Adding it needs the partner's `REC_HASH` message, not just its root, in `txOk`.
- A late `SEED_HASH(0)` from D, with empty `seen`, can sit in a log whose attempt 0 had none. Harmless to the outcome.
- FP6 is not one theorem from a reachable honest device to the reader. That every accepted message lands in `seen` is how `emit` builds it, not proved.
- The mutant patches and concrete runs are not kept in the repo. The table is the only account of them.
- Retry reasons are not modeled (see Model choices). That a retry `FAIL` after the own `GAP_VALUE` names `impossible_flight` or `self_timestamp_mismatch` is not checked.
