# fv/v1/docs: the write-ups

Goal: a machine-checked proof that the Noir circuits accept only what we say they accept. They run after the verdict. Live NEAR doesn't depend on them.

| File | What's in it |
|---|---|
| [01-primer.md](01-primer.md) | What FV is, in five steps, worked through on the arrival rule |
| [02-scope.md](02-scope.md) | Which code is in scope, block by block, and what we trust without proof |
| [03-bar.md](03-bar.md) | Why BAR = 4474747, and what FV can and can't say about it |
| [04-plan.md](04-plan.md) | The hackathon plan, the fix bundle, open questions |
| [05-spike-results.md](05-spike-results.md) | Results: review verdicts, what got proved, findings, what's left |
| [06-app-invariants.md](06-app-invariants.md) | What the phone code must get right |
| [../server/README.md](../server/README.md) | The server's verdict and session rules |

## Code under study

- **Circuits** live in `research/worldid/prototypes/optA-noir/noir/`. `oalib/src/lib.nr` is the shared logic, 819 lines, about 275 of them the `_opt` variant. `phone/src/main.nr` is the per-phone statement. `pair/src/main.nr` is the distance check.
- **On-chain verifiers** are `contracts/zk/src/{PhoneVerifier,PairVerifier}.sol` (UltraHonk). They're deployed on Sepolia, but the live Safe guard doesn't use them.
- **The same rule off-circuit** is in `app/.../dsp/Popt2Rule.kt` and `server/pop/popt2.py`.
- **The old circom version** was deleted in #17, and is in git at `53604e3^`. Out of scope.

## Short version

- The live verdict comes from two signed numbers, with no circuit. The circuits are for the proof that may follow a NEAR.
- The app finds the beep, and the circuit only checks the answer. So we prove a list of checks, not a search. That's what makes FV doable.
- `phone` says "this arrival is the first loud-enough lag in my signed recording". `pair` says "these two half gaps mean -20 to 60 cm". Loud enough doesn't mean a beep was heard. Silence passes.
- FV can show the code matches the spec. It can't show how the room behaves. The most useful output is the list of assumptions, because each one is something to measure.
