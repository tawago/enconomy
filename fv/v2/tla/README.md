# v2 pairing with two honest devices (TLA+)

Models [`../spec.md`](../spec.md) as of commit `45e4da9`, plus the two F10 sentences added with this model (a device signs nothing else for an attempt after its own `FAIL`; a local failure comes before the own `GAP_HASH`): section 2.1 (drop rules, resend, link close), the section 2.3 table ("sends when" and the receiver rules), F10 (failures, retry, timeouts, the 600 s end) and `Outcome` from section 4. The Lean model in [`../protocol`](../protocol/README.md) follows the same version. Why TLA+ next to Lean, and the drift rule: [ADR 0003](../adr/0003-tla-for-two-devices.md).

Both devices are honest. There is no attacker and no crypto. FP1 to FP6 stay in Lean and are not restated here.

Nothing of v2 is built. This checks the spec, not code.

## Status

| Checks | Result | Review | Mutants |
|---|---|---|---|
| `Agreement`, `NearStays`, `AcceptOrder`, `AnswersHeld`, `Liveness`, `StuckExplained`, `EndsWithPair`, four reach checks, three runs that must fail `Liveness` | all as expected, TLA+ tools v1.7.4 | Codex, Fable 5.2 | seven, each fails a property, table below |

Results of `./run.sh all`. "Distinct states" is the full state space when the run passes. When an invariant or `NearStays` fails, it is the states seen before the violation; these runs use one worker, so the count and the run TLC prints are the same every time. When `Liveness` fails, it is the states TLC had when its periodic check of the temporal property found the violation. That check runs on a timer, so the count, the time and the run TLC prints change from run to run, with machine speed and load; those counts are rounded. Times are rounded.

| Config | What it checks | Expected | Result | Distinct states | Depth | Time |
|---|---|---|---|---|---|---|
| `Safety` | `Agreement`, `AcceptOrder`, `AnswersHeld`, `NearStays`, every fault on | pass | pass | 3,491,224 | 74 | 45 s |
| `Live` | `Liveness`, `Agreement`; only local failures before the own `GAP_HASH` and `TIME` failures | pass | pass | 262,055 | 71 | 20 s |
| `Stuck` | `StuckExplained`, `Agreement`; timeouts and late local failures on, link and session stay | pass | pass | 436,403 | 71 | 10 s |
| `NoFault` | `Liveness`, `Agreement`, `EndsWithPair`; every fault off | pass | pass | 1,737 | 71 | 5 s |
| `MutantAnswerAfterGapValueAgreement` | M1 keeps `Agreement`, every fault on | pass | pass | 3,594,296 | 74 | 25 s |
| `MutantNextAttemptWithoutPartnerFailAgreement` | M4 keeps `Agreement`, every fault on | pass | pass | 13,879,920 | 74 | 90 s |
| `LiveWithTimeouts` | `Liveness` with timeouts on | fail `Liveness` | fail | about 110,000 | | about 65 s |
| `LiveWithClose` | `Liveness` with link close on | fail `Liveness` | fail | about 8,000 | | about 5 s |
| `LiveWithLateLocalFail` | `Liveness` with a local failure allowed after the own `GAP_HASH` | fail `Liveness` | fail | about 110,000 | | about 65 s |
| `KnownStuckRun` | the F10 stuck run is reachable on attempt 0 | fail | fail | 37,610 | 33 | 10 s |
| `KnownStuckRunOnRetry` | the F10 stuck run is reachable on attempt 1 | fail | fail | 92,223 | 38 | 15 s |
| `NearAfterRetry` | both devices can reach NEAR on attempt 1 | fail | fail | 80,090 | 38 | 10 s |
| `NearBesideIncomplete` | after the link closes, NEAR on one side and incomplete on the other is reachable | fail | fail | 246,788 | 33 | 15 s |
| `MutantAnswerAfterGapValue` | M1 | fail `StuckExplained` | fail | 43,628 | 34 | 10 s |
| `MutantTimeoutAfterGapValue` | M2 | fail `Agreement` | fail | 247,259 | 33 | 15 s |
| `MutantTimeoutAfterGapValueNearStays` | M2 | fail `NearStays` | fail | 247,257 | 33 | 20 s |
| `MutantNextAttemptWithoutFails` | M3 | fail `Liveness` | fail | about 260,000 | | about 125 s |
| `MutantNextAttemptWithoutPartnerFail` | M4 | fail `StuckExplained` | fail | 157,610 | 33 | 25 s |
| `MutantNextAttemptWithoutPartnerFailAnswers` | M4, no timeout | fail `AnswersHeld` | fail | 30 | 5 | 1 s |
| `MutantBCombinesOwnFirst` | M5 | fail `Agreement` | fail | 36,373 | 33 | 5 s |
| `MutantSignAfterFail` | M6 | fail `Agreement` | fail | 247,355 | 33 | 20 s |
| `MutantGapValueWithoutPartnerGapHash` | M7 | fail `AcceptOrder` | fail | 116,575 | 27 | 10 s |

A liveness run that fails prints no depth. All configs use `Vals = {0, 1, 2}`.

## Files

| File | What it holds |
|---|---|
| `Pairing.tla` | The model: the two devices, the link, the faults, the properties, the mutants (one `CONSTANT` switch). |
| `Safety.cfg`, `Live.cfg`, `Stuck.cfg`, `NoFault.cfg` | The checks that must pass. |
| `LiveWithTimeouts.cfg`, `LiveWithClose.cfg`, `LiveWithLateLocalFail.cfg` | `Liveness` with one fault on that the protocol can't recover from without the 600 s end. Must fail. |
| `KnownStuckRun.cfg`, `KnownStuckRunOnRetry.cfg`, `NearAfterRetry.cfg`, `NearBesideIncomplete.cfg` | Reach checks: each states that something never happens, and must fail, to show TLC reaches it. |
| `Mutant*.cfg` | The mutants. Each must fail on the property named in the table, except the two `...Agreement` configs, which show that M1 and M4 keep `Agreement` and must pass. |
| `run.sh` | Runs TLC on one config, or on all of them with the expected result of each. |

## What it checks

- **`Agreement`** (invariant, every fault on: timeouts, link close, the 600 s end, local measurement failure at any point before the own `GAP_VALUE`, `TIME` failure). Never NEAR on one device and NOT_NEAR on the other. This is the two-device half of FP5 that the spec argues on paper. It needs the rule that a device signs nothing for an attempt after its own `FAIL` (M6).
- **`NearStays`** (action property, same config). Once a device's outcome is NEAR, it stays NEAR.
- **`AcceptOrder`** (invariant, same config). A device accepts a partner `GAP_VALUE` only once it holds what the `GAP_VALUE` check reads: the partner's `SEED_HASH`, `SALT`, `REC_HASH` and `SEED_VALUE`, and its own `SALT` and `SEED_VALUE`. It follows from both devices' send rules, not from a receive guard alone: M7 drops the partner `GAP_HASH` guard on sending `GAP_VALUE` and breaks it. (A partner `SEED_VALUE` only after the partner's `SEED_HASH` is itself a receive guard here, so it is not checked as an invariant.)
- **`AnswersHeld`** (invariant, same config). When a device signs a message, it has accepted the partner message that message answers (spec 2.3, "answers" column; the `SEED_HASH` for attempt 1 answers the partner's `FAIL` for 0). This is the sender side of the `peer` check: between honest devices the check would pass. Receivers in this model don't run it (Model choices).
- **`Liveness`** (temporal, under fairness, with only the faults the protocol recovers from: a local failure before the own `GAP_HASH`, and a `TIME` failure). Every run ends with no protocol step left, both outcomes final and equal, and neither device waiting for a partner `FAIL`. Final means NEAR, or NOT_NEAR with no attempt 1 to wait for. So with the link up and no timeout, both devices finish without the 600 s end, a failure on attempt 0 always leads to attempt 1, and both agree. It assumes both people tap confirm (the tap is a protocol step under fairness).
- **`StuckExplained`** (invariant, timeouts and late local failures on, link and session stay). Every state where neither device can take a protocol step, and one of them is not final or still waits for the partner's `FAIL`, has the shape of the run in spec F10, "Two honest devices can lose a session this way": one device signed a retry `FAIL` after its `GAP_HASH` and before its `GAP_VALUE`, the other sent its `GAP_VALUE`, holds no pair, signed no `FAIL`, and both outcomes are NOT_NEAR. `KnownStuckRun` is a state, not an order: the other device's `GAP_VALUE` may come before or after the `FAIL`. Both orders are spec runs with the same harm. A terminal state needs both confirm taps, since the tap is a protocol step, so this says nothing about a person who never taps. It holds for this model, with its link and its atomic steps. On attempt 0 the stuck run costs the retry. On attempt 1 there is no retry to lose. The device that signed the `FAIL` still waits for the partner's `FAIL`, which never comes, until the 600 s end.
- **`EndsWithPair`** (invariant, `NoFault`: every fault switch off). A run that stops ends with both devices holding both `GAP_VALUE`s for the last attempt in their log, so the outcome is the verdict of a pair, never a pair of `FAIL`s. `NoFault` also checks `Liveness` and `Agreement`.
- **Reach checks.** The stuck run on attempt 0 (`KnownStuckRun`) and on attempt 1 (`KnownStuckRunOnRetry`). NEAR on both devices on attempt 1 after a retry. NEAR on one device and incomplete on the other after the link closes, as the spec allows (FP5).

`Liveness` fails in three expected cases. The runs below are examples from one run of each. TLC prints a different run from time to time (see Status): the roles, the attempt and the order of steps can differ.

- `LiveWithTimeouts`: B signs its `GAP_HASH`, then times out. A then signs its `GAP_HASH` and `GAP_VALUE`, and holds no pair. The F10 run, with the roles swapped. In other runs the `GAP_VALUE` comes before the timeout.
- `LiveWithClose`: the link closes at once. Each device signs `SEED_HASH`, then a local-failure `FAIL` for 0. Neither `FAIL` arrives. Both are NOT_NEAR and wait for attempt 1. Nobody is incomplete.
- `LiveWithLateLocalFail`: as with timeouts, but the `FAIL` after the own `GAP_HASH` is a local failure (in the run printed, A's on attempt 1, after a retry). So the F10 run needs no timeout once a local failure can come after the own `GAP_HASH`. Spec F10 now says it can't.

In each, the 600 s end is what ends the session. That it does is not checked: no config has a fair 600 s end. It holds trivially, since after the end no protocol step is possible.

## Mutants

Each is one `Mutant` value in `Pairing.tla`. Ids here are only for this table. The mutant configs that must fail use only the faults the spec allows (no local failure after the own `GAP_HASH`), except M7's. M7 and the two `...Agreement` configs use `Safety`'s faults. The runs are what TLC prints with one worker; for M3, a `Liveness` failure, the run printed can change from run to run.

| Id | `Mutant` | Change | Fails | The run TLC finds |
|---|---|---|---|---|
| M1 | `answerAfterGapValue` | answer a partner's retry `FAIL` after the own `GAP_VALUE` always, not only when the pair asks for a retry | `StuckExplained` | A sends its `GAP_VALUE`. B times out before its own. A answers, but can't move on (own `GAP_VALUE`, no pair). B moves to attempt 1 alone. Both stuck, not the F10 shape |
| M2 | `timeoutAfterGapValue` | allow a timeout `FAIL` after the own `GAP_VALUE` | `Agreement`, `NearStays` | both `GAP_VALUE`s sent, A holds the pair, gets NEAR. B times out before A's `GAP_VALUE` arrives, gets NOT_NEAR |
| M3 | `nextAttemptWithoutFails` | move to attempt 1 with no `FAIL` held | `Liveness` | B signs its `GAP_HASH` for 0 and moves to attempt 1 at once. A then sends its `GAP_VALUE` for 0, and with no pair can never follow |
| M4 | `nextAttemptWithoutPartnerFail` | move to attempt 1 with only the own `FAIL` | `StuckExplained`, `AnswersHeld` | `StuckExplained`: A sends its `GAP_VALUE`. B times out, and A doesn't answer. B moves to attempt 1 alone. `AnswersHeld`, with no timeout: A signs a local-failure `FAIL`, moves to attempt 1, and signs its `SEED_HASH` for 1, which answers no partner `FAIL` for 0 |
| M5 | `bCombinesOwnFirst` | B passes its own transcript first to the verdict | `Agreement` | A's transcript 0, B's 1. A gets NEAR from (0, 1). B computes (1, 0), impossible, NOT_NEAR |
| M6 | `signAfterFail` | sign `GAP_HASH` and `GAP_VALUE` after the own `FAIL` | `Agreement` | B times out after its `GAP_HASH`, then signs its `GAP_VALUE` anyway. A holds the pair, gets NEAR. B is NOT_NEAR by its own `FAIL` |
| M7 | `gapValueWithoutPartnerGapHash` | sign `GAP_VALUE` without the partner's `GAP_HASH` | `AcceptOrder` | A signs its `GAP_HASH` and at once its `GAP_VALUE`. B accepts both before it accepted A's `SEED_VALUE` |

M1 and M4 keep `Agreement` with every fault on (the two `...Agreement` configs). M2 also breaks `NearStays`: both `GAP_VALUE`s are sent, A holds the pair and NEAR, then A's own timeout `FAIL` turns it NOT_NEAR. M1 alone gives no retry: A, with its own `GAP_VALUE` sent and no pair, still can't move on, so the answer only lets B start attempt 1 alone, and the run is stuck in a new way. Answering and moving on as well is what would hand a cheater the K3 retry (spec F10); the model has no cheater. In this model M4 breaks `StuckExplained` only with a timeout, or a local failure after the own `GAP_HASH`. In the spec it breaks with neither: the `SEED_HASH` for 1 must answer the partner's `FAIL` for 0, so the partner drops it at the `peer` check. The model's receivers don't run that check, so `AnswersHeld` stands in for it.

## What it does not give

- **Nothing about content.** No hashes, seeds, signatures, `sid` or `peer`. That a `GAP_VALUE` a device accepts is the one the partner signed is the Lean model plus HASH (`fp5_device`). That every receiver check passes between honest devices is assumed here and proved in neither model. The spec says it on paper (FP5, "An honest partner never fails a final check"). The order part of it is checked here (`AcceptOrder`), and the sender side of the `peer` check (`AnswersHeld`).
- **No attacker.** A dishonest device is the Lean model's job (FP1 to FP6).
- **The verdict is a stand-in.** `Combine` over `Vals = {0, 1, 2}` gives near when B's value is A's or one more (except (2, 2)), too far for (0, 2), impossible when A's value is larger, and self timing mismatch for (2, 2), with A's transcript first. It is not the v1 math, but like it, NEAR is not symmetric in the order, so a device that swaps the roles breaks `Agreement` (M5). The checks need only that both devices compute the same function of the same pair, and that each result can happen.
- **Small instance.** Three values per measurement, two attempts.
- **Time is not modeled.** A timeout may fire at any point before the device's own `GAP_VALUE`. The spec's clock rule (`t0 + 20 s`, or 60 s with no new message) picks some of these points. So the safety checks cover the spec's timeouts. The F10 run needs a timeout at one exact point, and its rarity is not shown.
- **Final failures are not modeled.** Between honest devices no body check fails, so every `FAIL` is a retry `FAIL`.
- **Liveness only without timeouts, link close, local failures after the own `GAP_HASH` and the 600 s end.** With any of the first three, a run can stop short of a final outcome (the three `LiveWith` configs), and only the 600 s end closes the session. That the 600 s end does so is not checked.
- **`Live` covers less than the Lean model allows.** The Lean model lets a device sign a retry `FAIL` for any reason up to its own `GAP_VALUE`. `Live` has local failures only before the own `GAP_HASH`, as the spec now says. `Safety` and `Stuck` allow them up to the own `GAP_VALUE`.
- **Both people tap confirm.** `Liveness` assumes it (the tap is a protocol step under fairness). A person who never taps leaves the other device to the 600 s end. Not checked.
- **The atomic steps and the link are model choices.** `StuckExplained` classifies the end states of this model. A second kind of stuck state in the spec could hide behind them, and if TLC finds one later, it may come from the spec or from a model choice.
- **K9 breaks the assumption that body checks pass.** If `render` is not bit-exact on both devices, an honest receiver can fail the partner's `code_commit` and sign a final `FAIL` while the partner already holds NEAR. That split is outside this model, which has no final `FAIL`.
- `INVITE`, `JOIN`, the QR codes and the WebRTC setup are not modeled. The run starts with the link open.

## Model choices

These differ from the spec text, fill a gap in it, or simplify it.

- **The link.** Every signed message is on the link while it is open. A device accepts any partner message it has not accepted yet, for its current attempt, when the receiver rule allows it. The message stays on the link. This covers the spec's resend (same bytes until answered), the duplicate drop, the drop of a message not expected yet (it comes again), and messages in any order. Any order is more than the spec's ordered link, which is fine for safety. For `Liveness` it means a message is available until accepted. The spec stops resending once the partner's answer arrives, and an answer comes only after the partner accepted the message, so nothing is lost. The same holds for a `FAIL` for attempt 0, resent until a partner message for attempt 1 arrives: the partner moved on only after accepting it.
- **Link close is one step.** After it, nothing arrives. Signing goes on, and the messages stay on the device.
- **Before the confirm tap every incoming message is dropped**, as in the Lean model. After the 600 s end a device does nothing, not even the confirm tap. The Lean model's confirm input doesn't check the end; nothing follows from it either way.
- **One `FAIL` per attempt.** After its own `FAIL` a device signs nothing more for the attempt. It still accepts partner messages, as in the Lean model, so a partner `FAIL` completes the pair of `FAIL`s. `Agreement` depends on this rule (M6). The spec text before this model said only "at most one `FAIL`" and "waits"; F10 now says it.
- **The answer to a partner's retry `FAIL` is signed in the same step as the accept**, as in the Lean model: only if the device has signed no `FAIL` and either has not sent its `GAP_VALUE` or holds the pair and the verdict asks for a retry.
- **`GAP_HASH` waits for the device's own `SEED_VALUE`** (Lean model choice). The spec's row says only "F7 gave a gap".
- **`GAP_VALUE` waits for the device's own `GAP_HASH`**, as in the Lean model. The spec's row says only "holds partner `GAP_HASH` for k". The own `GAP_HASH` also stands for "F7 gave a gap", since the value comes from the measurement. A `GAP_VALUE` sent before its `GAP_HASH` would be dropped by the partner until the hash arrives, so this likely changes no result.
- **What a receiver expects now.** Spec 2.3 states an "expects now" rule only for `TIME` (B waits for A's `SALT`) and for filled slots. The model, as the Lean model, also drops a partner `SEED_VALUE` before the partner's `SEED_HASH`, and a partner `GAP_VALUE` before the partner's `GAP_HASH`; the message comes again. On the spec's ordered link these can't arrive early. On this any-order link the rule turns an early message into a drop instead of a final body check failure.
- **The `peer` check is not run by receivers.** Between honest devices it is assumed to pass, like every other envelope check. `AnswersHeld` checks the sender side: every signed message comes after the partner message it answers.
- **Capture and measurement stop after the device's own `FAIL`.** They change nothing the outcome reads.
- **B's `TIME` check.** A failure is a fault switch: B signs a retry `FAIL`, the `TIME` is not accepted, stays on the link, and may be accepted later, as in the Lean model. It sets `t0`, but B signs nothing more for the attempt.
- **Local failures come before the device's own `GAP_HASH`.** The measurement (F7) gives a gap or a failure. Any other local failure, such as a failed capture, is a fault at any point before the own `GAP_HASH`. A device that sent its `GAP_HASH` has a gap and reports no local failure. The spec text before this model read as allowing a local-failure `FAIL` up to the own `GAP_VALUE`; F10 now says a device that sent its `GAP_HASH` has none left to report. The switch `AllowLateLocalFail` allows one up to the own `GAP_VALUE`. It behaves like a timeout: `LiveWithLateLocalFail` shows the F10 stuck run with no timeout, and `Stuck` shows it adds no other stuck state.
- **Each step is atomic on one device.** A guard check and the signing it allows are one step, and a device's timer, receive and sign never interleave inside a step. A device must do them one at a time. M2 shows what the race costs.
- **Old messages stay on the link.** A sender stops resending its attempt-0 messages once it moves to attempt 1, but here they stay receivable. Harmless: a receiver still on attempt 0 at that point has signed its `FAIL` for 0 and needs only the partner's `FAIL`.
- **Every `FAIL` is a retry `FAIL`.** No final `FAIL` happens between honest devices, so the reason codes are not modeled.
- **`Outcome` reads the last attempt in the device's log**, as the spec and the Lean `outcome` do. Right after the move to attempt 1, before any attempt-1 message, that is still attempt 0. The verdict impossible or self timing mismatch reads as NOT_NEAR. "Final" adds: not waiting for attempt 1, that is, not on attempt 0 with an own retry `FAIL` or a pair that asks for one.
- **Fairness.** Weak fairness on every protocol step of each device: confirm, each kind of signing, capture over, measure, receive, the move to attempt 1. None on a fault: timeout, `TIME` failure, link close, the 600 s end. The result of a measurement is free, so a measurement may fail every time; the retry is capped at attempt 1.

## Run

TLC needs Java 11 or newer and `tla2tools.jar` v1.7.4 (sha256 `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`), at `$TLA2TOOLS` or `~/tla/tla2tools.jar`. `TLC_HEAP` sets the Java heap, default `4g`, enough for every config. `Safety`, the largest of the three main checks, also passes with `1g`.

```
cd fv/v2/tla
./run.sh Safety     # one config, TLC's own output
./run.sh all        # every config, one line each, exit 0 when all end as expected
```

`./run.sh all` took about 10 minutes, most of it the configs that must fail, which run on one worker. Output goes to `logs/`, TLC's state files to `states/`. Both are ignored by git.
