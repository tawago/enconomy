# fv/v1: Lean proofs of the proximity circuits, and of the server

Two parts:

- `zkp/` has the Noir circuits for the optional proof that may follow a NEAR. No live consumer requires it.
- `server/` has the live verdict: two signed numbers, no circuit. See [server/README.md](server/README.md).

The proofs work end to end: `lake build` passes on all 13 circuit files with no `sorry` and no new axioms. They also found real holes in the circuit. Read [Findings](#findings) before quoting anything.

**Which code.** The circuit side was written against 9db1490. Since then the circuits, `verdict.py`, `codec.py`, `auth.py`, `popt2.py`, `jbl250.py` and the app's DSP haven't changed, so the proofs still describe today's code. One exception: `zk.py` gained an opt-in mode, `POP_PAIR_CIRCUIT=named`, the v1.1 pair circuit. Citations of `chainatt.py`, `contracts/` and `bridge/` point at the old commit. The server side cites 5863e9c and runs on the current code.

Longer write-ups are in `docs/`, starting with [docs/05-spike-results.md](docs/05-spike-results.md).

## Build

```bash
brew install elan-init uv
cd fv/v1/zkp/popfv
lake exe cache get                         # prebuilt Mathlib
LEAN_NUM_THREADS=2 lake build              # all files; `lake build Popfv.Pair` for one
```

`lake build -j2` doesn't work, so use `LEAN_NUM_THREADS`. Mathlib is heavy. On a small machine, build one file at a time and never run two Lean jobs at once. To check a file without saving the result, use `lake env lean Popfv/Pair.lean`. If reviewers run side by side, give each mutant its own name, like `_mut_<reviewer>_<name>.lean`.

The from-zero steps last ran when the project was set up, not since.

**Expected.** `Build completed successfully (18206 jobs).` and 201 axiom lines, all within `propext`, `Classical.choice`, `Quot.sound`. Any `sorryAx` means a broken proof. Warnings about modules, copyright and `if_pos` are harmless.

**Cost.** `.lake` takes 7.3 GB. One file takes 2-3 minutes, all of them about 15 minutes one at a time, and a rebuild with nothing changed about 2.5 minutes.

## Scripts

From `popfv/`:

```bash
uv run --with z3-solver python scripts/pair_z3.py                           # z3 on block G, ends ALL OK, ~25 s
uv run --with mpmath --with numpy --with scipy python scripts/bar_check.py  # recomputes BAR's g, ends ALL OK
uv run --with numpy python scripts/arrival_real_template.py                 # arrival rule on real codes
python3 scripts/rates_parity.py                                             # taps and constants: circuit vs app vs server
```

`arrival_real_template.py` prints no pass/fail. Its "pass" lines are bad news: a recording that knows nothing about the code got through. Look for `silence -> (0, 0, 0)`, the 500 Hz tone at 57/60, and noise at rms 20 passing 57/60. Its role A and role B lines are the same, because it reuses one key. So read them as 3 codes, not 6.

## Results

| Block | File | Main theorem | Status | Last review | Mutant |
|---|---|---|---|---|---|
| Shared | `Field.lean` | `fits_intCast_iff` | proved | no separate audit | none |
| G pair | `Pair.lean` | `pair_sound`, `pair_complete`, `distance_iff` | proved, z3 agrees | Fable: pass | caught |
| BAR | `Bar.lean` | `bar_iff_score`, `T0eff_48k` | proved | Fable: pass | caught |
| D arrival | `Arrival.lean` | `self_side_arrival_sound` | proved, if the curve is true | Fable: pass | caught |
| E partner, F glue | `PartnerGlue.lean` | `partner_loud`, `half_commit_binds` | proved | Fable: pass | caught |
| App vs circuit | `AppPasses.lean`, `AppParity.lean` | `passes_correct_real`, `transcript_parity` | proved | Fable: pass | caught |
| B samples, H code | `Commit.lean` | `code_commitment_binds` | proved, under hash hypotheses | Opus: unfinished, no defect. A recheck passed. | caught |
| C spot check | `Freivalds.lean` | `fooled_count` | proved, needs p prime | Opus: pass | caught |
| A signatures | `Signed.lean` | `check_signed_sound`, `chain_of_trust` | proved, under signature hypotheses | Opus: pass | caught |
| Join | `Chain.lean` | `phone_sound`, `presence_sound` | builds | Opus: no proof defect. Failed on wording, fixed, not re-reviewed. | 6 caught |

"Mutant caught" means a reviewer broke one constraint on purpose and the proof stopped working.

**What `presence_sound` says.** Under all its hypotheses: a credentialed key signed the transcript, the opened samples come from the recording, `a_self` is the first lag that passes the loudness test, the partner lag passes it close to the prediction, and the two halves give -20 < flight < 60 cm.

**What it doesn't say.** That a beep was heard. Silence meets every hypothesis, at flight 0, and a tone solved the real circuit. It doesn't say where the phones were, or that a mic made the recording. The halves are whatever the signer chose. Every chain-level witness is silent, with toy crypto.

So a pass means "the circuit enforces this". Never quote it as "a beep was heard".

## Evidence, by kind

- **Lean.** The table above, plus witnesses like `silence_passes` and `silence_satisfies_presence_sound`.
- **Scripts.** The four above. Reproducible, but not proofs.
- **nargo.** Control, silence, click, tone in a file, and a fake near ran through the real compiled circuit, with throwaway keys and no proof made. See `zkp/circuit-cases/RESULTS.md`.
- **One-off Python, not in the repo.** The block E tone runs, and the code survey.
- **By hand.** Witnesses through all blocks, the order of events, the `half` argument.
- **Real mic.** One quiet recording, Pixel 6: 0/800 passed, too quiet to settle anything. Simulation says the tone needs about 93 dB at the phone and under 0.3% speaker distortion. Never shown in a real room.

## Findings

| # | Finding | Status | Severity |
|---|---|---|---|
| 1 | Silence passes D and E (0 ≥ 0) | confirmed | medium, proof path only |
| 2 | A blind 500 Hz tone passes. Energy goes through the filter, but correlation doesn't. | confirmed in the circuit, not through a real mic | medium. Could reach live NEAR via the stock app, but needs a loud clean tone in a quiet room. |
| 3 | One click picks the arrival | confirmed, self side only | low |
| 4 | A toy template passes with no beep | true on the toy only | none on real codes |
| 5 | A flat template accepts anything | true, but the server pins `code_commit` | none |
| 6 | Block E checks "loud enough", not "first" | true, needs a decision | not rated |
| 7 | `half` is free for a dishonest signer | follows from 1 and 2. On the plaintext path it's free anyway. | low |
| 8 | 44.1 kHz can't prove | confirmed | none, completeness only |
| 9 | A and B share codes | refuted, `bed_key` carries role and attempt | none |
| 10 | The Noir verifier returns `(0, 0)`, so it doesn't bind phones to owners | confirmed, not deployed | high only if a Noir guard ships |

**Why these ratings.** A phone gets its own code before capture, and the partner's only after it commits. Proofs only come after a plaintext NEAR. So a lone far-away cheater can't reach NEAR either way, and with an accomplice speaker NEAR is reachable with or without these holes. On the plaintext path a dishonest signer just signs a number. It still has to land its half in a window about 5 ms wide.

**Why the tone matters.** The stock v2 app has no live loudness bar (`PopRound2.kt:18`), so it signs a tone recording as is. No patched app is needed. If the tone survives a real mic, an outsider could make two honest phones far apart read NEAR. That needs a very quiet room and two speakers timed to about 2 ms. Untested.

Block E on a 500 Hz tone gave different rates in two one-off runs: 200/200 then 154/200 clean, 0/200 then 2/200 with noise. The rate depends on the code and phase.

**More circuit concerns (2026-11-06), report only.**
- A window past the end of the capture passes `partner_side`, because the tree is padded and the transcript carries no capture length. Not run in nargo.
- The partner's Y, `commit_hash` and the play times reach the proof only through `sha256(t)`.
- The partner key has no credential, signature or curve check.
- `rec_root` ties to nothing beyond the opened leaves.
- `pair` doesn't tie issuer or `code_commit` across phones. The verifier has to.

## Lampe

Not usable. It pins Noir beta.19, and ours is beta.22. Its only update path, PR #311, uses `native_decide`, which breaks the axiom rule here. So the model stays hand-written.

## Not done

- `bb prove` on the crafted cases. Only `nargo execute` ran.
- A non-silent run of the joined model. A loud recording accepted by the Lean model.
- The random-oracle step, and linking `Freivalds`' binding hypotheses to `Commit.lean`.
- BAR layer 3, which stays false until findings 1 and 2 are fixed.
- The `earliest()` FFT screen, and the Kotlin side of `OaHash.kt` and `CodeCommit.kt`.
- Any circuit fix. Next steps are in `docs/04-plan.md`.

## Trusted, not proved

- **The model equals the Noir code.** It's hand-written and cites line numbers. A reviewer read it against the source and broke it on purpose, but no tool extracted it. This is the weakest link.
- **The Kotlin models equal the Kotlin code,** by the same method. Nothing ran on a JVM.
- **Only `phone`, `pair` and the shared logic are modeled,** with `u8` templates only. `phone_opt` isn't deployed.
- **Poseidon2, SHA-256 and ECDSA are opaque.** Each use is a named hypothesis. `pair_sound` needs none of them. `presence_sound` needs `HalfBinds`.
- **`rec_root` is a tree over the recording.** That's assumed, and the circuit doesn't enforce it.
- **Noir and Barretenberg are correct,** Noir enforces input types, `to_le_bits` gives 8 bits, `to_be_bytes` is canonical, and the Solidity verifier matches the circuit.
- **Physics** (rooms, echoes, speaker delay) is out of reach for any proof.

## Files

- `zkp/popfv/Popfv/*.lean`: the proofs.
- `zkp/popfv/scripts/`: the four scripts.
- `zkp/tone/tone_test.py`: makes a tone WAV and scores a real recording, arithmetic only.
- `zkp/circuit-cases/`: crafted inputs through the real circuit.
- `docs/`: the write-ups. `05` has the results, `04` the plan, `06` the app invariants.
