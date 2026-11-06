# Formal verification of the proximity proof (prep notes)

Goal: prove, with a machine-checked proof, that the Noir circuits of the optional proof path accept only
what we say they accept. These run after the verdict. Live NEAR doesn't depend on them.

## Files

| File | What |
|---|---|
| [01-primer.md](01-primer.md) | What FV is, in five steps, worked on the arrival rule |
| [02-scope.md](02-scope.md) | What code is in scope, block by block, and what we trust without proof |
| [03-bar.md](03-bar.md) | Why BAR = 4474747: what FV can and can't say about the threshold |
| [04-plan.md](04-plan.md) | Hackathon plan: what to do first given the spike, fix bundle, open questions |
| [05-spike-results.md](05-spike-results.md) | Spike results in plain English: audit verdicts, what got proven, findings with severity, what's left |
| [06-app-invariants.md](06-app-invariants.md) | What the phone code must get right: table of invariants, what's proven |
| [../server/README.md](../server/README.md) | The server's verdict and session rules: results, gaps, how to reproduce |

## Code under study

- Circuits: `research/worldid/prototypes/optA-noir/noir/` (same bytes as the built copies)
  - `oalib/src/lib.nr`: the shared logic (819 lines; ~275 of them are the `_opt` variant)
  - `phone/src/main.nr` (and `phone_opt`): per-phone statement
  - `pair/src/main.nr`: the distance check
- Onchain verifiers, deployed on Sepolia but not used by the live Safe guard:
  `contracts/zk/src/{PhoneVerifier,PairVerifier}.sol` (UltraHonk, bb v5.0.0-nightly.20260522).
  The ENS bridge calls `PhoneVerifier` for its optional check.
- Off-circuit reference of the same rule: `app/.../dsp/Popt2Rule.kt`, `server/pop/popt2.py`
- The old circom/Spartan2 version (`oa2t_s48`) was deleted in #17; it's still in git at `53604e3^`.
  Out of scope here.

## The short version

- The live verdict comes from two signed numbers, with no circuit. Everything below describes the proof that may
  follow a NEAR.
- The circuit doesn't find the beep. The app finds it; the circuit checks the answer. That's what makes
  FV doable: we prove a list of checks, not a search.
- Two circuits: `phone` (detection: "this arrival is the first loud-enough lag in my signed recording")
  and `pair` (ranging: "these two half-gaps mean −20..60 cm"). "Loud enough" doesn't mean a beep was heard:
  silence passes. See [05-spike-results.md](05-spike-results.md).
- FV can prove the code matches the spec. It can't prove the room behaves. The output we care about most is
  the list of assumptions, each one a thing to measure.
