# ADR 0002: plain names in the v2 Lean models

Date: 2026-11-12. Status: proposed. Nothing is renamed yet. The renames land in a later change.

This record changes two rules of [ADR 0001](0001-direct-webrtc-link-and-plain-words.md), Decision 2, "Rules for the swap":

- "Ids stay: FP1 to FP6, K1 to K16, ..."
- "The Lean rule model changes in comments only."

## Context

The Lean names are short and hard to read. `ci`, `cq`, `cn2`, `tf`, `PassY`, `St`, `got` and `toyC` say little about what they are. The theorem names are ids: `fp1_order`, `fp5_pair`, `fp6_value`. A reader has to look each id up in `spec.md` to know what was proved.

One name is wrong, not just short. `cn2` in the app is the sum of `cI²` alone (`app/.../dsp/Popt2Rule.kt:49`). `cn2` in the v2 rule is the sum of `cI²` and `cQ²` (`zkp/Popfv2/Rule.lean:43`). One name means two different sums. Moving the v2 rule into the app with this name would mix them up.

## Decision

1. **The Lean rule model gets new names**, not only new comments. This replaces "the Lean rule model changes in comments only."
2. **Lean theorem names say what the theorem says.** The spec id (FP1, RS, ...) moves into the theorem's docstring.
3. **Ids stay in the spec as link targets.** Every mention leads with the plain phrase. The id appears once, in brackets, where the item is defined. This changes "Ids stay" without breaking links from the README, ROADMAP, QUESTIONS and the v1 documents.
4. **Short math letters stay inside formulas:** `I`, `Q`, `E`, `M`, `y`, `h`, `w`, `n`, `T`, `BAR`, `FLOOR`. They match the spec's formulas (`spec.md:165-172`).
5. **Wire and code names still stay**, as in ADR 0001: the POPT field `half`, `code_commit`, `commit_hash`, `rec_root`, `verify_record`, POPC, POPT. Nothing here renames the circuit, the app or `popt2.py`.

## Rule model (`zkp/Popfv2`)

| Now | New | Why |
|---|---|---|
| `cn2` | `templateSumSquares` | the app's `cn2` is a different sum, see Context |
| `ci`, `cq` | `cI`, `cQ` | the spelling in `popt2.py` and the app |
| `tf` | `centered` | it subtracts 128 |
| `corr` | `sumProducts` | says what it sums |
| `energy` | `sumSquares` | same |
| `Floor` | `LoudEnough` | `Floor` and `FLOOR` differ only by case |
| `Ratio` | `MatchHighEnough` | says what it checks |
| `PassY` | `PassesFiltered` | a one-letter suffix said "on `y`" |
| `Pass` | `PassesRecording` | it runs on the recording `w` |
| `passAt` | `PassesAtLag` | same family, same case |
| `FirstPass` | `SelfArrivalAt` | the circuit calls this the self side |
| `PartnerPass` | `PartnerHeardAt` | the circuit's partner side |
| `ceiling` | `score_at_most_one` | the theorem's content |
| `pass_silence` | `silent_recording_rejected` | it proves a reject, not a pass |
| `ratio_scale` | `match_test_ignores_volume` | the theorem's content |
| `gain_route` | `filter_gain_cancels` | "route" was a picture |
| `Tone.lean` | `GainCancels.lean` | no tone result is inside |
| `Code.lean` | `ZeroTemplate.lean` | it is about the all-128 template |

## Protocol model (`protocol/ProtoFv`)

| Now | New | Why |
|---|---|---|
| `St` | `DeviceState` | |
| `Cfg` | `DeviceConfig` | |
| `Tx` | `Transcript` | `Tx` reads as "transaction" |
| `pkPeer` | `pkPartner` | the POPT field is `pk_partner` |
| `selfOs` | `selfOffset` | |
| `sent`, `got` | `signed`, `accepted` | the docstrings' own words |
| `mine`, `theirs` | `hasSigned`, `hasAccepted` | same |
| `act`, `emit`, `adv`, `gate` | `trySign`, `signAndLog`, `nextAttempt`, `maySign` | say what each step does |
| `envOk`, `txOk` | `commonChecksOk`, `transcriptOk` | the spec never says "envelope" |
| `hsOf`, `cOf`, `ccOf`, `txOf` | `seedHashOf`, `gapHashOf`, `codeCommitOf`, `transcriptOf` | |
| `Res` | `Verdict` | it holds a verdict |
| `flight` | `verdictOfGaps` | |
| `pairRetry`, `retried`, `why` | `pairAsksRetry`, `hasRetryFail`, `reason` | the spec says `reason` |
| `Reach`, `Inv1` to `Inv5` | `Reachable`, one name per invariant by its content | |
| `fp1_order` | `seed_value_after_rec_hashes` | Decision 2 |
| `fp5_pair` | `outcome_is_combine_of_pair` | Decision 2 |
| `fp6_value` | `verify_accepts_iff_checks_pass` | Decision 2 |
| other `fpN_*` theorems | by content, the same way | Decision 2 |
| `toyC` | `constHashCrypto` | every hash is 7 |
| `freeC` | `injectiveHashCrypto` | |
| `txBfar` | `txBImpossible` | gap 1100 gives "impossible", not "too far" |

## Spec labels

| Now | New |
|---|---|
| FP1 to FP6, RC, RS, RT | the property's plain name, id once in brackets |
| F1a to F11 | the message name (`F2` is `SEED_HASH`) |
| K1 to K16 | a short phrase plus a link to the hole |
| C6 to C23, CN, FN, V | words, with the v1 id once in brackets |
| HASH, SIG, HIDE, RAND, OOB | "no collisions", "no forgery", "hash hides", "fresh randoms", "QR unchanged" |

## Consequences

- The Lean names stop matching the v1 models in `fv/v1`. v1 keeps its names, because it describes the system as built.
- `Axioms.lean` and every README that lists theorem names change with the renames.
- The `zkp` model depends on Mathlib, so the rename rebuilds it. Run that build with `tools/cloud/cloud.sh run`.
- When the v2 rule moves into the app, the app's `cn2` gets renamed too, or it stays clearly `cI`-only.

## Options not taken

- **Keep the ids as theorem names.** Short, but a reader can't tell what was proved without the spec open.
- **Drop the ids everywhere.** Breaks every cross-reference in the README, ROADMAP, QUESTIONS and the v1 documents.
- **Rename the wire and code names too.** They are shared with the app, the circuit and the server. That is a separate change.
