# Hackathon plan (continuity track, from 2026-11-06)

Status 2026-11-06: eleven proof files and two witness files build, and all the blocks have theorems. The new four are Opus-reviewed only. `Chain.lean`'s closing review found no proof defect, and failed only on wording, since fixed. The gaps do hold in the real circuit (`nargo`). See [05-spike-results.md](05-spike-results.md).

## What to do first

The current circuit stays frozen while this list finishes. Circuit fixes wait for the next version: `fv/v1/next-version-fixes.md`.

| # | Work | Why this order | Rough size |
|---|---|---|---|
| 0 | Rerun the build from a clean clone, one file at a time | `partner_accepts_nonsilent` and `wI_dc` hit a kernel "deep recursion" error before a one-line fix. It could come back if it depends on stack size. | 15 min |
| 1 | **Done: `nargo` cases.** Control, silence, click, tone, fake near, all with throwaway keys. See `fv/v1/zkp/circuit-cases/RESULTS.md`. | The gaps hold in the real circuit, so the fix decision below is now the next step. Optional: run `bb prove` on one case. | done |
| 2 | **Circuit fix: deferred to the next version.** See `fv/v1/next-version-fixes.md`. | A new verifier key is expensive. Pay for it once. | done for now |
| 3 | **Done: `AppParity` role mutant.** `transcript_parity` stopped proving, and the weakened statement is false. | | done |
| 4 | **Written, not decided: gap 6.** The section in `05` is marked "Owner to confirm". | Owner's call. | owner |
| 5 | **Done: row 5 by script, rows 12 and 8 by reading.** No Lean for these. | See [06-app-invariants.md](06-app-invariants.md). | done |
| 6 | **Done: H, B** (`Commit.lean`). Last review failed as unfinished, no defect found. A recheck finished its checks. Opus only. | | done |
| 7 | **Lampe checked by reading: not usable today.** Pins Noir beta.19, we're on beta.22. Nothing built or extracted. | Owner decides whether to allow the build for a PR #311 try. | owner |
| 8 | **Done: C** (`Freivalds.lean`). Review passed, Opus only. The random-oracle step stays an assumption. | | done |
| 9 | **Done: A** (`Signed.lean`). Review passed, Opus only. BAR layer 3 not started: it's false until gaps 1 and 2 are fixed. | | done for A |
| 10 | **Join: `Chain.lean`** (`phone_sound`, `presence_sound`). Builds, and three mutants in a finished review stopped proving. Wording fixes are in, the last three by hand and not re-reviewed. Every chain-level witness is silent audio. | Done. | done |
| 11 | **Server side: built, last reviews failed.** Spec, Lean, walk and replay in [`../server/README.md`](../server/README.md). This shows the server follows its rules on signed numbers. A phone can still sign a false half (CN1, X1). Open items are listed there. | Owner decides which to close before a commit. | owner |

Demo minimum: `lake build`, one theorem in plain English, and one gap. A proof that found a hole in its own subject is a better story than a green check.

## The `nargo` run

Done 2026-11-06 with a new harness, `fv/v1/zkp/circuit-cases/cases.py`. It signs with throwaway keys and uses `server/pop/poseidon2.py`, which matched the circuit on every run. It doesn't need the Secure Enclave. Results: `fv/v1/zkp/circuit-cases/RESULTS.md`.

## Fix bundle

Changing the circuit means a new verifier key and a redeploy of those verifiers. The live guard doesn't use them, so this affects the Noir path and the ENS bridge's check, not today's Safe. So decide these together:

| Fix | Closes | Status |
|---|---|---|
| Require loudness > 0 on both sides | gap 1, and gap 3 on most codes | `floor_blocks_silence` proves only the silence case. One of 80 codes surveyed fell below the click bound. |
| Measure energy and correlation on the same signal | gap 2 | Not tested. Bar and arrival proofs need redoing. The app rule must change too: the stock app runs this test before the verdict, so a circuit-only fix leaves live NEAR open. |
| Expose device hashes as `pair` public inputs and bind them in the guard | gap 10, Noir path only | Needed before any Noir guard goes live. Not a fix to today's path, which already binds devices through the server's signature. Not in FV scope. Bundle it only if the Noir switch is planned. |
| Sum `c_q²` into template energy, or assert `cna > 0` | gap 5, hygiene only | Optional. |

On the proof path, gap 7 (`half` is free) closes with the first two. On the plaintext path it stays open unless a consumer requires proofs. Gap 2's fix can wait until the circuit next changes, but it should go in then. The floor still stands for the proof path. Device binding matters only if the Noir guard is switched on.

## Deliverables

- Lean project: exists at `fv/v1/zkp/popfv` (Lean 4 + Mathlib, field = `ZMod p`, p = BN254 scalar field)
- One theorem per block: done for A to H, under named hypotheses. Two theorems join them.
- List of assumptions: "Everything assumed" in [05-spike-results.md](05-spike-results.md), and "What is trusted, not proved" in `fv/v1/README.md`. "How we'd test it in the field" isn't written yet.
- A short "what this does / doesn't prove" for judges: [05-spike-results.md](05-spike-results.md). Tell judges plainly that the proofs cover an optional path that runs after the verdict.

This folder lives at `fv/v1/docs/`, so it travels with a clone.

## Tools

| Tool | Use | Note |
|---|---|---|
| Lean 4 + Mathlib | main proofs, hand-written model of each function | steepest, most flexible |
| Lampe (Reilabs) | auto-extract Noir to Lean, so the model can't drift from the code | **Not usable today, from reading source.** No version matches beta.22, and it's on another Lean. See `05`. |
| z3 / cvc5 | fast automatic check of small pieces (G) | won't scale to D |

Hand model risk: the Lean model can differ from the Noir code. Mitigation: names and line order are kept identical. `Signed.fx_sound` runs block A on the real `Prover_A` bytes, with toy crypto. Running the whole Lean model on the `180ca04b_48k` fixture as a differential test is still not done.

## Open questions (resolve day 1)

- ~~Which phone variant is deployed~~: `phone` (VK_HASH match). `phone_opt` is out of scope.
- ~~Is `half` a free choice~~: on the plaintext path, yes, with no conditions. On the proof path, yes for a dishonest signer, given a passing partner lag. By code reading. See gap 7.
- ~~Does the stock app apply a stricter live bar~~: no, not on v2. See [05-spike-results.md](05-spike-results.md).
- ~~Lampe: does it handle this Noir version~~: no. `assert_max_bit_size` and unconstrained hints look fine, but it pins beta.19, and hashes are concrete there, not opaque. See `05`.
- E "loud enough, not first": intended? Gap 6 in `05` has the facts. Owner's call.
- Continuity track rules and judging criteria: fill in.
