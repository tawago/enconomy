# FV spike: Lean proofs of the Noir proximity circuits

**Which code this describes.** Written against `main` at 9db1490 (`informal-spec.md` Part 1 says 53604e3 where it differs). The decoupling that followed moved Safe, ENS, World ID and attestation out to `examples/` and changed `server/pop/sessions.py` and `main.py`. So citations of `chainatt.py`, `contracts/`, `bridge/`, and line numbers in those two server files point at the older commit. `server/` here is the exception: since issue #43 its citations are for 5863e9c and its checks run on the current code. The circuits, `verdict.py`, `codec.py`, `auth.py`, `popt2.py`, `jbl250.py`, `zk.py` and the app's DSP folder are unchanged since then, so the circuit proofs still describe the current code.

Does the pipeline work end to end? Yes. `lake build` passes on all 13 files (11 proofs, 2 witness files), with no `sorry` and no new axioms. Every block has theorems, and `Chain.lean` joins them. Reviews are in Results.

The proofs also found real gaps in the circuit. Read the results and findings below before quoting anything. The gap cases ran through the real compiled circuit (`nargo`), with throwaway keys and no proof made: `circuit-cases/RESULTS.md`. These circuits run only after a NEAR, and no live consumer requires them. The longer version is [fv/v1/docs/05-spike-results.md](../../fv/v1/docs/05-spike-results.md).

**Notes:** the longer write-ups are in `docs/` next to this file, and they travel with a clone. `zkp/` holds the circuit proofs and test cases.

**Server side, added 2026-11-07.** The live verdict comes from the server, with no circuit. `server/` now holds a spec, Lean proofs of the verdict and the session table (`Verdict.lean`, `Machine.lean` and 26 newer files), a walk on the real routes (62 tests with 45 mutations, final run 1000 sessions), and a replay comparing the two (6032 sessions, 0 mismatches on the compared fields; 67 of 67 tampers caught, 104 rule changes with 103 caught and 1 unreachable one allowed). This shows the server follows its rules on signed numbers. A phone can still sign a false half (CN1, X1). The last `spec.md` and `Machine.lean` re-reviews and the last critic passed. The `Verdict.lean` and `test_walk.py` re-reviews failed; their defects are fixed and not re-reviewed. On 2026-11-09 Codex (gpt-6-astra) reviewed the work again; its findings (M14, `X1_session`, the checkers, the replay, the docs) were fixed and the code fixes passed re-review, with low items left open. M14 now pins, through `TxReject`, the two docs a rejected transcript may finalize. Since issue #43 it checks the `server/` of the same checkout, not a pinned copy: all of it reran green on 5863e9c plus the #43 edits, and CI reruns it on every server change. Details and how to reproduce: [server/README.md](server/README.md).

## Reproduce from zero on a Mac

```bash
brew install elan-init uv        # elan installs the Lean version named in popfv/lean-toolchain
cd fv/v1/zkp/popfv
lake exe cache get               # downloads prebuilt Mathlib, 9081 files
lake build
```

Then the scripts, from `popfv/`:

```bash
uv run --with z3-solver python scripts/pair_z3.py
uv run --with mpmath --with numpy --with scipy python scripts/bar_check.py
uv run --with numpy python scripts/arrival_real_template.py
python3 scripts/rates_parity.py
```

The from-zero steps ran once, when the project was set up. They have not been rerun on a clean machine since then.

### Building

`lake build -j2` is rejected (`unknown short option '-j'`), so set `LEAN_NUM_THREADS` instead.

```bash
cd fv/v1/zkp/popfv
LEAN_NUM_THREADS=2 lake build Popfv.Pair   # one file
LEAN_NUM_THREADS=2 lake build              # all of them
```

Mathlib is heavy. On a small machine, build one file at a time first, and don't run Lean jobs side by side.

To check one file without saving a build result: `lake env lean Popfv/Pair.lean`.

Running reviewers side by side? Give each one its own mutant name, like `_mut_<reviewer>_<name>.lean`.

## Expected output

`lake build` ends with:

```
Build completed successfully (18206 jobs).
```

It prints 201 axiom lines: 173 with `[propext, Classical.choice, Quot.sound]`, 23 with `[propext, Quot.sound]`, 4 with `[propext]`, 1 with none. These three are Lean's standard built-in axioms. Anything else, above all `sorryAx`, means a proof is broken.

Last run 2026-11-06, one module at a time, then the full build. Files whose source hadn't changed were replayed from saved results. The job count can differ on another machine.

| File | Axiom lines |
|---|---|
| Field | 5 |
| Pair | 4 |
| Bar | 22 |
| Arrival | 17 |
| PartnerGlue | 16 |
| AppPasses | 14 |
| AppParity | 12 |
| Commit | 22 |
| Freivalds | 27 |
| Signed | 35 |
| Chain | 17 |
| WitnessCommit | 6 |
| WitnessChain | 4 |


Warnings are harmless: `consider adding module`, `Copyright too short`, `if_pos` / `if_neg` deprecated.

`pair_z3.py` ends with this. The model numbers can differ between runs, since z3 picks its own.

```
SOUND      z3: unsat  (expected unsat)  OK
COMPLETE   z3: unsat  (expected unsat)  OK
EDGE-20    z3: sat  (expected sat)  OK
EDGE60     z3: sat  (expected sat)  OK
SAT        z3: sat  (expected sat)  OK
ALL OK
```

`bar_check.py` ends with:

```
  round        = 3792174   RATES B = 3792174   OK
  margin to rounding edge = 0.09168959577 (of 0.5)
  ...
lib.nr hard-codes only the 48 kHz BAR; no 44.1 kHz Noir circuit carries 3792174.
ALL OK
```

`arrival_real_template.py` has no pass/fail line. It prints what passes on real server codes. These lines are the ones to look for:

```
  silence -> (0, 0, 0)
    500 Hz  FIR gain     0.1   57/60  lags [0, 1, 2, 3, 4, 5, 7, 8]
    800 Hz  FIR gain     0.2   42/60  lags [0, 3, 4, 5, 6, 7, 9, 10]
  noise rms  20: 57/60 pass
  noise rms  50: 33/60 pass
```

Here "pass" is bad news: a recording that knows nothing about the code got through the arrival rule.

The script's "role A" and "role B" lines print the same numbers, because it reuses one key and `popt2.code`'s role argument does nothing for the bed. The real server uses a different key per role (`jbl250.bed_key`). So treat those lines as 3 codes, not 6.

All three scripts were rerun with `uv run --offline`. `pair_z3.py` and `bar_check.py` end in `ALL OK`. The arrival numbers above came out the same.

## Time and disk

Rough numbers. They vary with the machine.

| Step | Cost |
|---|---|
| Disk, `popfv/.lake` | 7.3 GB, plus the Lean toolchain that `elan` installs |
| Toolchain and Mathlib download | a few minutes (from file times, not timed) |
| One proof file, nothing else running | 2-3 min, mostly loading Mathlib |
| All files, one at a time | about 15 min |
| `lake build` when all files are already built | about 2.5 min |
| `pair_z3.py` | 23 s, up to 40 s seen |
| `bar_check.py` | 4 s |
| `arrival_real_template.py` | 12 s |

## Results

**Reviews.** The original seven files got an independent Fable audit, after Opus reviews. `Commit`, `Freivalds`, `Signed` and `Chain`, and the role mutant, are **Opus only**. A mutation test breaks one constraint on purpose and checks that the proof stops working. "Fix rounds" counts every time a review sent the file back.

| Block | File | Main theorem | Status | Last verdict | Mutation test | Fix rounds |
|---|---|---|---|---|---|---|
| Shared model | `Field.lean` | `fits_intCast_iff` | proved | no separate audit | none | 0 |
| G `pair` | `Pair.lean` | `pair_sound`, `pair_complete`, `distance_iff` | proved, z3 agrees | Fable: pass | dropped `half_b` range check: stopped proving | 0 |
| BAR layer 1 | `Bar.lean` | `bar_iff_score`, `T0eff_48k`, `round_eq_iff_g2` | proved | Fable: pass | 48 kHz constant +1 and 44.1 kHz bound set to the outer value: both stopped proving, control proved | 1 |
| BAR layer 2 | `scripts/bar_check.py` | none, 60-digit numeric check | ALL OK, not a Lean proof | Fable: recompute matched | n/a | 0 |
| D arrival | `Arrival.lean` | `self_side_arrival_sound`, `self_side_arrival_complete` | proved, assuming the curve is true | Fable: pass | dropped `u[K-1] = 0`: stopped proving | 1 |
| E partner, F glue | `PartnerGlue.lean` | `partner_loud`, `phone_core_glue`, `half_commit_binds` | proved | Fable: pass | dropped `u[K-1] = 0`: `sod_small` stopped proving | 2 |
| App vs circuit | `AppPasses.lean` | `passes_correct_real`, `passes_iff_partner_fits` | proved | Fable: pass, second review. The first failed only because its build never got to run. | dropped carry, and `≥` to `>`: both stopped proving | 1 |
| App vs circuit | `AppParity.lean` | `transcript_parity`, `encoder_to_circuit` | proved | Fable: pass. Role mutant by Opus, 2026-11-06. | weakened role tie: stopped proving, and `role_mutant_refuted` shows it false | 0 |
| B samples, H code | `Commit.lean` | `phone_core_windows_are_recording`, `open_leaves_ties`, `code_commitment_binds` | proved, under named hash hypotheses | Opus only: **last review failed as unfinished, no defect found.** A separate recheck finished its checks and passed them. | removed the 8-bit check: `sorryAx` on the window theorems (log: `zkp/logs/chain-mutants.txt` (removed from the repo, in git at 5863e9c)) | 2 |
| C spot check | `Freivalds.lean` | `fooled_count`, `arrival_bad_pairs_count` | proved, needs p prime. Random-oracle step is an assumption. | Opus only: pass | `r * rinv = 1` to `True`: `sorryAx` on the counts | 1 |
| A signatures | `Signed.lean` | `check_signed_sound`, `chain_of_trust` | proved, under named signature hypotheses | Opus only: pass | removed the expiry check: `sorryAx` on `check_signed_sound` | 2 |
| Join | `Chain.lean` | `phone_sound`, `presence_sound`, `phone_bad_challenges` | builds, under all hypotheses | Opus only: closing review found no proof or model defect. It failed on wording only. Two re-reviews read those fixes and failed on wording again. Those fixes are in and not re-reviewed. | `op_ok` removed, `cb = commit_b` to `True`, the upper bound to `True` (both readings), the partner test, the root tie, `fits 33` to `fits 34`: all stopped proving (log: `zkp/logs/chain-mutants.txt` (removed from the repo, in git at 5863e9c)) | 2 |

**What `phone_sound` and `presence_sound` say.** Under every hypothesis: a credentialed key signed this transcript, the opened samples are the recording's, `a_self` is the first of 193 lags passing `BAR × match ≥ loudness`, the partner lag passes it within -7200..+12000 of the signed prediction, `half` is the gap between them, and two phones plus `pair` give -20 < flight < 60 on the signed numbers.

**What they don't say.** That a beep was heard: silence meets every hypothesis and conclusion, at flight 0 cm, and a tone solved the real circuit. Where the phones were. That the recording came from a mic. `p_self` and `p_partner` are the signer's numbers. "Keys" means X coordinates. The chain-level witnesses are silent with toy crypto, and no loud recording with a real template is machine-checked by the chain-level model. Block-level witnesses accept any recording, but only with a flat template. Details: `fv/v1/docs/05-spike-results.md`.

A pass means a proof of what the circuit enforces. Don't quote it as "a beep was heard" or as "no hole in Block D".

## What kind of evidence is what

- **Machine-proven (Lean)**: everything in the table marked "proved", under its stated hypotheses, on the hand-written model. Also the witnesses `silence_passes`, `partner_silence_accepts`, `click_picks_any_lag`, `dc_strict_pass`, `flat_template_any_recording`, `floor_blocks_silence`, `docstring_bound_hole`, `hole_pSelf_overflow`, `beF32_wraps`, `past_capture_witness`, `junk_accepted`, `bad_keys_pass_byteChecks`, `silence_satisfies_presence_sound`.
- **Script replay**: `pair_z3.py` (z3 on block G), `bar_check.py` (the value of g), `arrival_real_template.py` (silence, click, tone on real codes, arrival rule only), `rates_parity.py` (taps and constants across circuit, app and server: 42 comparisons, 0 differences, text only). Not proofs, but reproducible.
- **One-off Python, no script in the repo**: the block E tone runs, and the code survey (`cna`, code A vs B).
- **Ran in `nargo`**: control, silence, click, tone in a file, fake near, with throwaway keys and no proof made. See `circuit-cases/RESULTS.md`. Older Sept fixtures too: `logs/nargo-control.txt` (removed from the repo, in git at 5863e9c).
- **Hand-traced**: witnesses through all blocks, the order of events, who gains what, the `half` argument. Nothing checked these.
- **Real speaker or mic**: one quiet run only. One real recording, Pixel 6, normal source, 16-bit: 0/800 at amplitude about 835, too quiet to settle it. In simulation on that room's noise it needs amplitude 5000 or more (roughly 93 dB at the phone, not measured) and under about 0.3% speaker distortion. Not demonstrated in a real room. Logs: `logs/tone-room-2.txt` (removed from the repo, in git at 5863e9c), `logs/tone-distortion-sim.txt` (removed from the repo, in git at 5863e9c).

## Findings

Each has a status from an independent adjudication that reread the code. Severity is about what a real attacker gains.

| # | Finding | Status | Severity | Evidence |
|---|---|---|---|---|
| 1 | Silence passes D and E (0 ≥ 0) | confirmed | medium, proof path only. No effect on live NEAR. | Lean, script, one-off |
| 2 | Blind 500 Hz tone passes, because energy is filtered and correlation isn't | confirmed at circuit level, not demonstrated through a real mic | medium. Could reach live NEAR through the stock app, but needs a very loud, clean tone in a quiet room. | script (arrival rule 57/60), one-off (block E, see below) |
| 3 | One click picks the arrival | confirmed, self side only | low | Lean, script. The theorem needs `cna ≥ 9.1M`, and some real keys fall below that (one-off). |
| 4 | Strict pass with no beep on a toy template | true on the toy, no separate verdict | none on real codes | Lean, script |
| 5 | Flat template accepts anything | theorem true, attack refuted: the server pins `code_commit` | none | Lean, read in code |
| 6 | Block E checks "loud enough", not "first" | true, written decision owed | no separate rating | Lean, by hand |
| 7 | `half` is a free choice for a dishonest signer | proof path: confirmed, follows from 1 and 2. Plaintext path: free regardless. | low (gain only) | by hand |
| 8 | 44.1 kHz can't prove | confirmed | none, completeness only | by hand, read in code |
| 9 | A and B share codes | refuted: `bed_key` carries role and attempt | none | one-off |
| 10 | Noir verifier returns `(0, 0)`, so proving phones aren't bound to owners. The live attestation verifier does bind them, through the server's signature. | confirmed, not deployed, outside FV scope | high only if a Noir guard is deployed; not live | read in code |

Block E on a 500 Hz tone gave different numbers in two one-off runs with different setups. The adjudicator's run, 200 lags, exact setup not recorded: 200/200 at amplitude 10000, 0/200 with noise rms 30, 132/200 at amplitude 30000 with noise rms 30. A second run with 80 codes, random phase and offset: 154/200, 2/200, 74/200. So the rate moves with the code and phase.

**Why these severities.** By hand, from `sessions.py`, `verdict.py`, `RunFlow.kt`: a phone gets its own code before capture, and the partner's code only after committing `rec_root`. Proofs come only after a plaintext NEAR. So the self side binds nothing against a dishonest app, and a lone far cheater can't reach NEAR either way. With an accomplice speaker NEAR is reachable with or without the gaps. On the proof path, silence and a tone only remove the relay mic, not the need for timing. On the plaintext path, a dishonest signer needs neither a beep nor a relay, because it signs a number. It still has to land its half in a band about 5 ms wide, by guessing or with a timing mic.

**The tone matters because of who it helps.** The stock v2 app has no live bar (`PopRound2.kt:18`; `earliest` uses only `passes(.., rate.B)` at `Popt2Rule.kt:171`). `PopDsp.kt:102` is v1 code. So the stock app signs a tone recording, and no patched app is needed. If the tone survives a real mic, an outsider could make two honest far-apart phones read NEAR. It needs a very quiet room and a tone timed to about 2 ms across two speakers. Untested.

## New circuit concerns (2026-11-06)

Frozen circuit, report only. Not in `next-version-fixes.md` yet. Table with evidence in `fv/v1/docs/05-spike-results.md`.

- A window past the end of the capture passes `partner_side`, because the tree is padded and the transcript has no capture length (`past_capture_witness`). Not run in `nargo`, and not shown reachable through a whole statement.
- Partner Y, `commit_hash`, and play and capture times reach the proof only through `sha256(t)`. The server compares whole keys.
- The partner key has no credential, signature or curve check. The holder commit is never opened.
- `rec_root` ties to no value beyond the opened leaves.
- Issuer and `code_commit` are whatever the public inputs say, and `pair` doesn't tie them across phones or link its commitments to a phone proof. The verifier has to.

## Lampe

Not usable today. From reading source only: nothing built or extracted, because the one build try was denied as external code. It pins Noir beta.19, ours is beta.22, and two `oalib` calls shouldn't typecheck. Open PR #311 (beta.25) is the only path. It's on Lean 4.29.1 and uses `native_decide` in its crypto layer, which would break the axiom rule here. So the hand model stays.

## What is not done

- **`bb prove` on the crafted cases.** `nargo execute` found valid witnesses, and no proof was made. The inputs use throwaway keys, so a real run would still need the real issuer and a willing device.
- **A non-silent run of the joined model.** Every chain-level witness uses silent audio, so nothing at that level shows the model accepts real audio or an arrival lag above 0. `nargo` covers real audio on the circuit, not the Lean model.
- **The random-oracle step**, and connecting `Freivalds.RecRootBinds` and `CodeCommitBinds` to `Commit.lean`.
- **A loud recording accepted by the Lean model.** Only silent witnesses with toy crypto.
- **BAR layer 3.** False until findings 1 and 2 are fixed or scoped.
- **The `earliest()` FFT screen.**
- **The Kotlin side of rows 3, 4, 9** (`OaHash.kt`, `CodeCommit.kt`).
- **Any circuit fix.** Next steps are in `fv/v1/docs/04-plan.md`.

## What is trusted, not proved

**The model**
- The Lean model equals the Noir code. It is hand-written and cites line numbers. A reviewer read it against the source and broke it on purpose. No tool extracted it from Noir, so this is the weakest link.
- Kotlin models equal the Kotlin code, by the same method. Nothing ran on a real JVM. The test vectors of `Popt2RuleTest.kt` hold on the Lean model, as the theorem `popt2RuleTest_vectors`.
- `w(e)` is the identity (`lib.nr` line 14).
- Only `T = u8` templates are modeled. The Field template at `lib.nr` line 141 has no range check, and these bounds don't cover it.
- Only `phone`, `pair` and shared logic are modeled. `phone_opt` is out of scope, since it isn't deployed.

**Hashes and signatures**
- Poseidon2, SHA-256 and ECDSA are opaque. Every use is a named hypothesis on these exact inputs: `Unforgeable`, `NoCollisionWith`, `BindsToRecording`, `OpeningsBind`, `CodeBinds`, `HalfBinds`, `RecRootBinds`, `CodeCommitBinds`.
- `pair_sound` alone uses no hash binding. `presence_sound` does: `HalfBinds`.
- `rec_root` is a tree over the recording: `Assumptions.root_is_recording`. The circuit doesn't enforce it.
- `hspot`: the challenge isn't one of the bad pairs. Given acceptance, that's "the curve is true" renamed. `phone_bad_challenges` counts them, for a witness fixed in advance. That the real hash misses them is the random-oracle assumption, and fixing the witness first needs `CodeBinds`, which isn't in `Assumptions`.

**Noir behavior**
- `to_le_bits` forces an 8-bit leaf index. `PartnerGlue` takes `fits 8 leaf` as a hypothesis.
- `to_be_bytes` is canonical (`Signed.IsBE`). It is the only guard for the 32-byte read of `rec_root`, which can wrap (`beF32_wraps`).
- Noir enforces input types.
- The Noir compiler and Barretenberg (the proving system) work correctly, and the Solidity verifier matches the circuit.

**Not relied on**
- Primality of p, outside the odds theorems. `[Fact (Nat.Prime p)]` is a hypothesis of those, in `Freivalds.lean` and `Chain.lean`. It's never proved in this repo.
- Physics: rooms, echoes, speaker delay. Formal proofs can't reach these.

## Files

- `popfv/Popfv/*.lean`: the proofs. `popfv/Popfv.lean` imports all of them.
- `popfv/scripts/pair_z3.py`: independent z3 check of block G.
- `popfv/scripts/bar_check.py`: recomputes the filter gain from integer taps.
- `popfv/scripts/arrival_real_template.py`: replays the arrival rule on real server codes.
- `popfv/scripts/rates_parity.py`: compares taps and constants across `lib.nr`, `Popt2Rule.kt` and `popt2.py`.
- `tone/tone_test.py`: makes a tone WAV and scores a real recording with the partner test on fresh codes. Arithmetic only: no signature, Merkle or proof.
- `fv/v1/docs/05-spike-results.md`: results in plain English.
- `fv/v1/docs/04-plan.md`: what to do first at the hackathon.
- `fv/v1/docs/06-app-invariants.md`: what the app must get right.
