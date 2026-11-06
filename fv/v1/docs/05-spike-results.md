# Spike results (2026-11-05-2026-11-06)

## The short version

The pipeline works. Lean checks eleven proof files, plus two witness files, against a hand-written model of the circuits and the app, with one theorem per block and two that join them (`phone_sound`, `presence_sound`). Not every review closed: see [the verdict table](#review-verdict-per-file). `Chain.lean`, the file that joins the blocks, had no proof defect in its closing review. That review failed only on wording, since fixed. z3, an automatic solver, agrees on the distance check.

The most useful result isn't a proof. It's a gap the proofs exposed: **the circuit's "loud enough" test doesn't mean a beep was heard.** Silence passes it. A plain 500 Hz tone often passes it too, on real codes, without knowing the code.

**The gaps now hold in the real compiled circuit.** Silence, a click and a clean tone in a file all solve the phone circuit, and two phones with no beep at all solve `pair` as NEAR (`fv/v1/zkp/circuit-cases/RESULTS.md`). This used throwaway keys, including the issuer, and made no proof. So it isn't a demonstrated end-to-end attack: a real one still needs a credential from the real issuer and a device willing to sign such a recording.

Don't say "the circuit is proven secure". Say this: "we proved exactly what the checks enforce, and that showed us what they miss."

**Scope.** These circuits run only after the server has said NEAR, and no live consumer requires them. So don't quote any of this as showing where two phones were. The live verdict comes from two signed numbers (`server/pop/verdict.py:165`, `server/pop/sessions.py:604-605`, `server/pop/chainatt.py:29-60`). The ENS bridge adds an optional zk mark when proofs exist, but records on NEAR alone (`bridge/bridge.py:404-410`). One exception: `AppPasses.lean` covers the app's pass test, which an honest phone runs before the verdict (`Popt2Rule.kt:171`).

## Words used here

- **Circuit**: the list of math checks a zero-knowledge proof must satisfy.
- **Field**: the circuit's number system. Numbers wrap around at a huge prime p, like a clock.
- **Wraparound**: a negative number in the field looks like a huge positive one. Most proofs here show this can't fool a check.
- **Witness**: the private values a prover feeds the circuit. A concrete set of them is also how we show a check can be fooled.
- **Soundness**: a cheater can't pass. **Completeness**: an honest phone does pass.
- **Axiom**: something accepted without proof. Our proofs add none beyond Lean's three standard ones.
- **Mutation test**: break one check on purpose and confirm the proof stops working. It shows the proof actually depends on that check.
- **Freivalds check**: a random spot check that the claimed correlation numbers are the real ones. It's block C.
- **Correlation**: how well a recording matches the secret code.
- **FIR filter**: cuts sound outside the beep band. Its gain differs by frequency.

## How strong is each kind of evidence

| Level | What it means | What's at this level |
|---|---|---|
| **Lean** | A machine checked the theorem. It holds for the hand-written model, under the stated hypotheses. | All theorems named below. |
| **Script** | Python rerun on real server codes, in exact integers. Not a proof. Reproducible with the scripts in `fv/v1/zkp/popfv/scripts/`. | `pair_z3.py` (z3), `bar_check.py`, `arrival_real_template.py`, `rates_parity.py` (compares source text). |
| **One-off** | Python run once by a reviewer. No script is in the repo. | Block E tone runs, 40-seed code survey. |
| **nargo** | The real compiled circuit ran on the witness. | Sept fixtures only. The honest ones have proofs on Sepolia. The tampered runs from September are inferred from the `Prover_*.toml` files and `tamper.py`, with no log. On 2026-11-06 `Prover_A` solved and `Prover_sample` failed at Merkle (`fv/v1/zkp/logs/nargo-control.txt`). The fixtures live with the built circuits, outside a clone. **Spike cases, 2026-11-06:** control, silence, click, tone and fake near, with throwaway keys (`fv/v1/zkp/circuit-cases/RESULTS.md`). |
| **By hand** | A person or agent read the code and reasoned. Nothing checked it. | Attack order, what a cheater gains, witnesses traced through all blocks. |

No test touched a real speaker or mic.

## What the two top-level theorems say

Both are in `Chain.lean`, a hand-written model of `phone/main.nr` and `pair/main.nr` as one statement.

**`phone_sound`.** If `phone` accepts, and the assumptions below hold, then in true integers and bytes:

1. A key the issuer credentialed signed this exact 311-byte transcript. The session values, `a_self`, `p_self`, `a_partner`, `p_partner`, `half`, `rec_root` and both X coordinates are those signed bytes. `salt` isn't.
2. The opened samples are the recording's, at the right place.
3. `a_self` is the first of 193 lags where `BAR × match ≥ loudness`, on the true correlation.
4. The partner lag meets that same test, within -7200..+12000 samples of the signed `p_partner`.
5. `half` is the signed gap between those two lags.
6. The output hashes nonce, attempt, role, rate, `half`, `salt` and both X coordinates, and can't be opened another way short of a Poseidon2 collision.

**`presence_sound`.** If two `phone` runs and `pair` accept, under those assumptions for each phone, and `HalfBinds`, then: both halves are the ones each device signed, roles and session match, both rates are 48000, each phone names the other's X as partner X, and -20 < flight < 60 in plain arithmetic.

**What they don't say.**

- **No beep.** `0 ≥ 0` passes. `silence_satisfies_phone_sound` and `silence_satisfies_presence_sound` are all-silent witnesses that meet every hypothesis and conclusion, at flight 0 cm. Above-zero loudness isn't a beep either: a clean 500 Hz tone in a file solved the real circuit (case d, 6/6, in `nargo`, not a theorem).
- **No location.** The flight range is arithmetic on two numbers the devices signed.
- **No mic.** "Signed" says who signed, not that it's true. Nothing shows a recording came from a mic, or that the tree under `rec_root` is what the phone captured.
- **"First" is relative.** `p_self` and `p_partner` are the signer's numbers, so the window sits where the signer puts it. The partner test isn't "first" at all (gap 6).
- **Keys means X only.** The output hashes no Y. Partner Y is never read, while the server compares whole keys (`verdict.py:159`).
- **Nothing here touches live NEAR.** It comes from two signed numbers (`verdict.py:165`), with no circuit.

Limit of the witnesses: they use toy crypto (constant permutation, a verify that ignores signatures) and silent audio. They show the hypotheses can all hold. No loud recording is machine-checked as accepted by this model. Only `nargo` covers that (case a).

## Everything assumed

Named hypotheses. None is an axiom, and each is scoped to one witness.

| Name | What it says | Enforced by the circuit? |
|---|---|---|
| `Assumptions.issuer_sig`, `device_sig` (`Signed.Unforgeable`) | No forged signature on these exact digests | ECDSA is opaque. On its own this nearly assumes the conclusion, and `chain_of_trust_size` says so. Its content is which bytes and which key. |
| `Assumptions.issuer_hash`, `device_hash` (`Signed.NoCollisionWith`) | No SHA-256 collision with what the key signed | Opaque |
| `Assumptions.root_is_recording` | `rec_root` is the root of a tree over `rcd` | **No.** `phone_sound_no_tree` drops it, and gets a recording that is filler outside the opened windows |
| `Assumptions.self_paths`, `partner_paths` (`Commit.BindsToRecording`) | No Poseidon2 collision on the opened paths | Opaque |
| `Commit.OpeningsBind` | Same, between the two openings. Only for `phone_sound_no_tree` | Opaque |
| `Commit.CodeBinds` | No Poseidon2 collision on the templates. Only for `code_commitment_binds`, **not** in `Assumptions` | Opaque |
| `hspot` (`¬ Freivalds.Fooled`) | The challenge isn't a bad pair | Given acceptance, this is "the curve is true" renamed. See below. |
| `HalfBinds` | No Poseidon2 collision between each phone's output and `pair`'s opening | Opaque |
| `Freivalds.RecRootBinds`, `CodeCommitBinds` | Binding, for the absorption audit only | Opaque, and not connected to `Commit.lean` |
| `[Fact (Nat.Prime p)]` | p is prime, on the odds theorems only | Never proved in this repo |

About `hspot`. The real content is the count: `phone_bad_challenges` says at most 193p of the p² pairs accept with a false conclusion, for a witness fixed in advance. Getting from there to "the real challenge misses them" takes two unproved steps. One, the random-oracle assumption (`rom_union_bound` is labelled as an idealization and covers a fixed list of tries, not an adaptive attacker). Two, the witness has to be fixed before the challenge, which needs `CodeBinds` and tree binding. By hand, not checked: the sponge has one capacity cell, so real security is likely near 2^127 work, not the 2^-246 and 2^-182 figures.

Trusted, built into the model rather than named:

- The Lean models equal the Noir and Kotlin code. Hand-written, read by reviewers. No tool extracted them (see Lampe below).
- Noir's `to_be_bytes` is canonical (`Signed.IsBE`) and `to_le_bits` gives 8 bits. Noir enforces input types. `w(e)` is the identity.
- The compiler, Barretenberg, and the Solidity verifier matching the circuit.
- Only `u8` templates are modeled. `phone_pub` and `phone_opt` aren't.
- A verifier does its part: treats the commitments as those phones' public outputs, pins `issuer` and `code_commit`. With an all-128 `c_i`, loudness is 0 and the test passes on any audio.

## Review verdict per file

**Who reviewed what.** The original seven files got an independent Fable audit, after Opus reviews. The four new files, and the role-mutant recheck, are **Opus only**: all 27 agents in the 2026-11-06 workflow ran on Opus. Each reviewer reran the file, read the model against the source and broke one check on purpose, unless the table says otherwise.

| File | Block | Reviewer | Verdict | Mutation test | Notes |
|---|---|---|---|---|---|
| `Field.lean` | shared | none | no separate audit | none | Every other file builds on it. |
| `Pair.lean` | G | Fable | pass | Dropped the `half_b` range check. `pair_sound` and `pair_complete` stopped proving. | |
| `Bar.lean` | BAR 1 | Fable | pass | 48 kHz constant +1, and 44.1 kHz bound widened to the outer value. Both stopped proving. The unchanged control proved. | `g_range_*_sufficient` are now mutation-tested. |
| `Arrival.lean` | D | Fable | pass | Dropped `u[K-1] = 0`. `self_side_arrival_sound` stopped proving. | Assumes block C. |
| `PartnerGlue.lean` | E, F | Fable | pass | Dropped `u[K-1] = 0`. `sod_small` and `phone_core_glue` stopped proving. | |
| `AppPasses.lean` | app row 1 | Fable | pass, after one fix round | Dropped the carry. Changed `≥` to `>` in the tie. Both stopped proving. | The first review returned fail only because its build was stuck behind the machine lock. No defect was found. |
| `AppParity.lean` | app row 2 | Fable, mutant by Opus | pass | Weakened the role tie (`lib.nr` 233). `transcript_parity` stopped proving, `sorryAx` in its axioms. Ran 2026-11-06, not in the Fable audit. | The error is a tactic failing. `role_mutant_refuted` compiled clean: the weakened statement is false, role byte `'A'`, circuit told role B. |
| `Commit.lean` | B, H | **Opus only** | **Last review: fail, unfinished. No defect found.** A separate recheck agent then finished its open checks and passed them. | Removed the 8-bit check (`lib.nr` 109). `phone_core_windows_are_recording`, `phone_core_one_recording` and `open_leaves_ties` picked up `sorryAx`. | Non-vacuity: the recheck's witness holds every hypothesis at once, `CodeBinds` and `OpeningsBind` included. It lives in a temporary scratch file, not the repo. It uses honest openings, so it shows consistency, not collision resistance. |
| `Freivalds.lean` | C | **Opus only** | pass, on the second review | Replaced `r * rinv = 1` with `True` (`lib.nr` 371). `fooled_count` and the `arrival_bad_*` theorems picked up `sorryAx`. A failed proof, not a proved refutation. | Non-vacuity witnesses are degenerate: silence, flat templates. The absorption audit is partly a source reading. |
| `Signed.lean` | A | **Opus only** | pass, on the third review | Removed the expiry check (`lib.nr` 273). `check_signed_sound` picked up `sorryAx`. | The fixture's real signatures verify in a Python P-256 check using the model's layout. `IsBE` is disclosed as an assumption. |
| `Chain.lean` | joins all | **Opus only** | **No proof or model defect. Failed on wording only, fixed.** The last three wording notes were fixed by hand and not re-reviewed. | Earlier text, reviews 0 and 1: weakening the root tie, and `fits 33` to `fits 34` at `lib.nr` 526, both stopped proving. On today's text, run by the finish step, not a reviewer: the partner test (`lib.nr` 524) replaced with `True`. `phone_sound_core` failed, and `sorryAx` reached `phone_sound` and `presence_sound`. A failed proof, not a proved refutation. Closing review: `op_ok` deleted, `cb = commit_b` to `True`, the upper bound to `True`. All three made `phone_sound` or `presence_sound` show `sorryAx` with rc=1. The deletion partly reflects a missing field name. | Reviews 0 to 2 were cut off or asked for fixes. The closing review ran to the end, read the model against the source, and found no dropped or strengthened constraint. It didn't read the proof bodies of the block files, AppParity, AppPasses or Bar. Its limit: every chain-level witness uses silent audio, so nothing at that level shows the model accepts real audio or a lag above 0. |

Build, 2026-11-06: `Build completed successfully (18206 jobs).` 201 axiom lines across 13 files: 173 with `[propext, Classical.choice, Quot.sound]`, 23 with `[propext, Quot.sound]`, 4 with `[propext]`, 1 with none. No `sorryAx`. No `sorry`, `admit`, `native_decide` or `axiom` in the source. Per file: Field 5, Pair 4, Bar 22, Arrival 17, PartnerGlue 16, AppPasses 14, AppParity 12, Commit 22, Freivalds 27, Signed 35, Chain 17, WitnessCommit 6, WitnessChain 4. Module by module first, then the full build. Files whose source hadn't changed since their last check were replayed, not rechecked.

## What got proven (Lean)

Each line says: if the circuit accepts, this is true in ordinary numbers, no wraparound.

### Block G, the distance check (`Pair.lean`): the cleanest result

- `pair_sound`: if `pair` accepts, then -20 < 17150 × (hA/srA − hB/srB) < 60. Both ends are strict. Both halves are real signed 32-bit integers. Both sample rates are in 36000..96000. The two keys differ, meaning their field limbs differ.
- `pair_complete`: honest inputs pass.
- `distance_iff`: for real integers in range (signed 32-bit halves, rates 36000..96000), the two 70-bit checks are exactly that inequality.
- **Script**: z3 agrees. Edge cases at exactly -20 cm and 60 cm are rejected.

### BAR (`Bar.lean`, `bar_check.py`): 4474747 is the right number for 0.09 (Lean + script)

The Lean half: any g in a narrow range rounds to 4474747. The script half: g falls in that range. The value of g is not in Lean.

- `bar_iff_score`: the whole-number test `B × match ≥ loudness` is the real-number test `score ≥ g/√B`, when loudness is above zero.
- `T0eff_48k`: if g²/0.09² rounds to 4474747, the threshold really enforced is within about 1e-8 of 0.09.
- `bar_check.py` recomputes the filter gain to 60 digits: g = 190.38238 at 48 kHz, which rounds to 4474747. The margin is 0.47 of 0.5.
- 44.1 kHz gives 3792174, with a thin margin: 0.092 away from rounding differently. No circuit uses it.

### Block D, the arrival rule (`Arrival.lean`): the heart

- `self_side_arrival_sound`: **given block C**, and samples and templates of the right type, passing means `a` is the first lag where `BAR × match ≥ loudness`.
- `self_side_arrival_complete`: an honest recording passes the arrival checks, if `a` is the first loud-enough lag in the window and the signed target equals `a`.
- `bit96_is_sign_check`: the 96-bit check is exactly an integer sign check. It really fits: largest value 2^94.2, with 1.8 bits of room.
- These theorems assume the curve is true. `Freivalds.lean` and `phone_sound` carry that assumption, see below.
- Lags after the arrival are unconstrained. The rule is "first lag over the bar" only.

### Block E, the partner check (`PartnerGlue.lean`)

- `partner_loud`: the check passes exactly when `BAR × match ≥ loudness` at one lag. That lag need not be the first. Block E sums match and loudness inside the circuit, so it does not rest on block C.

### Block F, the glue (`PartnerGlue.lean`)

- `phone_core_glue`: window offsets are exact, `-7200 ≤ a_partner − p_partner ≤ 12000`, and `|sod| ≤ 96`.
- `half_commit_binds`: if the hash has no collision at these two openings, equal commitments mean equal fields. `Chain.out_is_hash` links it to the circuit's real output.

### Block A, signatures and bytes (`Signed.lean`)

- `check_signed_sound`: if `check_signed` accepts, the fields are the bytes at the spec offsets, the rate is 48000, delta is 96, and the expiry and X-differ checks hold.
- `chain_of_trust`: under `Unforgeable` and `NoCollisionWith`, the issuer signed a credential on this key, and that key signed this transcript. `chain_of_trust_size` says how little that adds alone.
- `fx_sound`: the real fixture `Prover_A.toml` satisfies the model, with toy crypto.
- `junk_accepted`, `bad_keys_pass_byteChecks`, `holder_commit_free`: what isn't checked. See new concerns below.

### Block B, the samples (`Commit.lean`)

- `open_leaves_first`, `open_leaves_ties`: the opened leaves are 13 in a row, with `first + 12 < 256`.
- `phone_core_windows_are_recording`: given the root is an honest tree over `rcd` and no collision on the paths, `xs[os+i]` is sample `p_self-96-31+i`, and `xp[op+i]` is sample `a_partner-31+i`.
- `phone_core_one_recording`: without that root assumption, both windows read one `u16` recording. Outside the opened leaves it is filler.
- `sponge_zero_tail_collision`, `node_hash_not_injective`: there is no length padding, so a blanket "no collisions" hypothesis would be false. That's why the hypotheses are per input.

### Block H, the code commitment (`Commit.lean`)

- `packing_injective`, `absorbed_determines_templates`: the 31-byte packing loses nothing, the short last chunk included.
- `code_commitment_binds`: under `CodeBinds`, one commitment means one set of templates.

### Block C, the spot check (`Freivalds.lean`)

- `check_iff`, `freivalds_complete`: the check is "an error polynomial is zero at (r, rho)". True values pass for all `r ≠ 0`.
- `fooled_count`, `fooled_odds`: for a fixed witness, at most 193p of the p² pairs pass with a false curve. Odds 193/p, below 2^-246.
- `arrival_bad_pairs_count`: the same count, for the arrival conclusion false.
- `known_r_fools`: if r is known before the curve is fixed, the check is worthless. So everything rests on the hash.
- `rom_union_bound`: labelled idealization, not a fact about Poseidon2.
- `absorbed_pins_identity`: under binding hypotheses, the absorbed values fix what the identity reads. The list itself is partly a source reading.

### App vs circuit (`AppPasses.lean`, `AppParity.lean`)

- `passes_correct_real`: the app's 128-bit math answers exactly `(I²+Q²)·B ≥ E·cn2`, at real input sizes.
- `passes_iff_partner_fits`: given the same integers on both sides, the app's yes agrees with the circuit's last 96-bit partner check. It doesn't show that the two compute those integers the same way. The float FFT screen in `earliest()` is outside the proof.
- `popt2RuleTest_vectors`: the asserts of `Popt2RuleTest.kt` hold on the Lean model. Nothing ran on a real JVM.
- `transcript_parity`, `encoder_to_circuit`: the app and the circuit read the same numbers from the signed bytes. The app's getters match when the value fits in 32 bits. This needs `a_self` and `p_partner` below 2^31. The app's encoder enforces that. The circuit doesn't.

## What a cheater can do, in order of events

Severity depends on this order. Read from `sessions.py`, `verdict.py` and `RunFlow.kt`. By hand.

1. The server sends a phone its own code at arm, before capture.
2. The phone commits `rec_root` after all sounds.
3. Only then does the server release the partner's code.
4. The server decides NEAR from both plaintext transcripts. An honest far partner fails with `partner_not_heard`.
5. Proofs are taken only after NEAR.

So:

- **The self side binds nothing against a dishonest app.** It knows its own code before capture, so it can synthesize its own beep anywhere.
- **The partner side is the only place the commitment has teeth.** And that check is the one silence passes.
- **A lone far cheater can't reach NEAR**, gaps or not.
- **With an accomplice speaker near the honest partner, NEAR is reachable either way.** On the plaintext path the cheater signs a number, so nothing has to be in its recording. It only needs a half close to the partner's, in a band about 5 ms wide. It can't see the partner's half, so it guesses or uses a timing mic that hears the partner's public tune. On the proof path, without these gaps, it also needs the partner's beep relayed into its recording before commit. That takes a relay mic and a network. Silence or a tone removes the relay mic, not the need for timing. For a dishonest signer, that is the whole gain.

**The stock v2 app has no live bar.** `PopRound2.kt:18` says the v1 null-bar rule is not run. `Popt2Rule.earliest` uses only `passes(.., rate.B)`. `PopDsp.kt:102` is v1 code. Only two checks stand between the app and a strange recording: the 8 ms flat-run glitch check, and the self-timestamp tolerance. So a tone doesn't need a patched app. Silence does, because of the flat-run check.

## Findings

| # | Finding | Status | Severity | Best evidence |
|---|---|---|---|---|
| 1 | Silence passes D and E | confirmed | medium, proof path only. No effect on live NEAR. | Lean, script |
| 2 | Blind tone passes D and E | confirmed at circuit level, not demonstrated through a real mic | medium. Could reach live NEAR through the stock app, but needs a very loud, clean tone in a quiet room. | script, one-off |
| 3 | One click picks the arrival | confirmed | low | Lean, script |
| 4 | Strict pass with no beep, toy template | true on the toy, no separate verdict | none on real codes | Lean, script |
| 5 | Flat template accepts anything | theorem true, attack refuted | none | Lean, by hand |
| 6 | Block E checks "loud enough", not "first" | true, owner to confirm | no separate rating | Lean, by hand, old notes |
| 7 | `half` is a free choice | proof path: confirmed, follows from 1 and 2. Plaintext path: free regardless, see section 7. | low (gain only) | by hand |
| 8 | 44.1 kHz can't prove | confirmed | none, completeness only | by hand, read in code |
| 9 | A and B share codes | refuted | none | one-off |
| 10 | Noir verifier doesn't bind devices | confirmed, not deployed, outside FV scope | high only if a Noir guard is deployed; not live | read in code |

### 1. Silence passes. Confirmed, medium.

**Real circuit:** an all-zero recording solves `phone` on both roles (case b).

The test is `BAR × match ≥ loudness`. With silence that's 0 ≥ 0, which is true. Nothing asserts loudness above zero (`lib.nr` 404-405, 471-472).

- **Lean**: digital silence passes the arrival rule at lag 0 (`silence_passes`).
- **Lean**: a silent partner window passes block E with any template (`partner_silence_accepts`).
- **Lean**: `silence_score_below_bar`. The score there is 0/0, which is undefined. Lean's convention makes it 0. So "score ≥ 0.09" doesn't apply to silence, yet the test passes.
- **Script**: silence gives (0, 0, 0) on 3 real codes. The script's "both roles" lines reuse one key, so they add nothing.
- **One-off**: block E on a silent window gives `v = 0`, `ep = 0`, `env2 = 0`.
- **By hand**: all-silent windows go through `self_side`, `partner_side` and `phone_core`, Freivalds included (0 = 0).

Needs a device willing to sign a silent recording. The stock app won't, because of the flat-run check. So: a patched app on an attested phone, or an unattested or web enrol where those are allowed.

Gain: on the proof path, drops the relay mic from the known accomplice attack. The timing need stays. It can also earn a false ENS zk mark after a NEAR. Modest.

Fix: require loudness above zero on both sides. `floor_blocks_silence` proves this works for silence. It means a new verifier key. It doesn't close gap 2.

### 2. A blind tone passes. Confirmed at circuit level, medium.

**Real circuit:** a clean 500 Hz tone written to the file before any code exists solved `phone` on 6 of 6 fresh sessions, A side (case d). That's a file, not a room.

Energy goes through the filter. Correlation uses raw samples. The filter's gain at 500 Hz is 0.14, and about 190 in the beep band. So a 500 Hz tone looks quiet to the energy side, yet still correlates a little with the code.

Arrival rule, **script**, 20 keys, 3 phases each, no knowledge of the code:

- Amplitude 10000: 500 Hz **57/60 pass**, 800 Hz **42/60 pass**. Every other frequency tried, 50 Hz to 8 kHz: 0/60.
- 500 Hz at amplitude 30000 with white noise: rms up to 20, 57/60. Rms 50, 33/60.
- White noise alone (±1000) found no arrival. Constant 1000 found none either.

Block E, **one-off**, exact integers. Two runs, and they differ:

| 500 Hz tone | Adjudicator (200 lags, exact setup not recorded) | Second run (80 codes, random phase and offset) |
|---|---|---|
| amplitude 10000, no noise | 200/200 | 154/200 |
| amplitude 10000, noise rms 30 | 0/200 | 2/200 |
| amplitude 30000, no noise | not run | 144/200 |
| amplitude 30000, noise rms 30 | 132/200 | 74/200 |

These are two different setups, not one experiment repeated. The second run shows the rate moves with the code and the phase. Read these as "often passes", not as a fixed number. Noise hurts it badly. Neither run is in Lean or `nargo`. No script in the repo replays these runs. `fv/v1/zkp/tone/tone_test.py` now has the exact partner test, but it scores new recordings on its own codes. It doesn't reproduce these numbers.

Needs, for an outsider with no key and no code:

- two speakers, one near each honest phone
- a tone timed to about 2 ms across both, inside the partner windows
- a room and mic with in-band noise far below the tone, about 1/1000 of its amplitude

Gain: this is the only gap that helps a new kind of attacker. The stock app signs what the circuit accepts. So if a tone got through a real mic, an outsider could make two honest, far-apart phones read NEAR, through the server and on to chain attestation, if both humans are verified and both devices attested, among other checks (`chainatt.py:29-60`). Owner signatures are needed only for a Safe spend (`PopSafeGuard.sol:270`). This needs no proof, because the stock app runs the same test before the verdict. Any proof made afterwards would likely pass too. For a dishonest signer it adds nothing beyond silence, until a floor is added.

Caveats, by hand: the app takes the earliest passing lag, and that depends on the noise before the tone. A tone covering the whole window pins the arrival to the window's start, which gives an impossible flight time. The timing must hit a band about 5 ms wide.

**Real-mic check, 2026-11-06.** One real recording, Pixel 6, normal source, 16-bit: 0/800 at amplitude about 835, too quiet to settle it. In simulation on that room's noise it needs amplitude 5000 or more (roughly 93 dB at the phone, not measured) and under about 0.3% speaker distortion. Not demonstrated in a real room. Logs: `fv/v1/zkp/logs/tone-room-2.txt`, `tone-distortion-sim.txt`. This is one room and one phone, so it lowers the rating but doesn't rule the attack out.

Fix: measure energy and correlation on the same signal, in the circuit and in the app rule (`Popt2Rule.kt:99`). Correlate on filtered samples, or add an in-band energy term. Bar and arrival proofs need redoing. 

### 3. One click picks the arrival. Confirmed, low.

**Real circuit:** silence plus one +1 sample solved `phone`, with the arrival on the chosen lag 50 (case c).

- **Lean**: one sample at +1, at position a+8, gives arrival `a`, for any `a` in 1..192 (`click_picks_any_lag`). It needs template energy `cna ≥ 9100000`.
- **Script**: three real codes, `cna` 9794687, 10162845, 11208062. Lags 1, 50 and 192 landed as asked.
- **One-off**: some real keys fall below 9.1M, so the theorem doesn't cover every key. One survey of 40 keys gave a minimum of 8903015. A second of 80 codes gave a minimum of 5622936, with 7 below 9.1M. Whether the click works on those wasn't tested.

Energy is 0 and match is 0 at that lag: same 0 ≥ 0 root as gap 1. Self side only.

Gain: none. A dishonest signer can already make its own beep at any lag.

Fix: the loudness floor from gap 1. A single-sample click with real energy can't pass when `BAR × 2 × 128² < 23253 × cna`, which means `cna` above about 6.3M. That covered 79 of the 80 codes surveyed. So it covers most codes. It isn't proved for all, and the one below 6.3M only falls outside this bound. It wasn't shown to pass.

### 4. A strict pass needs no beep, on a toy template. No separate verdict.

- **Lean**: constant signal 1 on a toy template gives a strict pass, with real energy and real match (`dc_strict_pass`). It also passes the proposed floor (`dc_passes_floor`).
- **Script**: constant 1000 on real codes fails.

So the toy shows the floor alone isn't enough. It isn't an attack on real codes. Gap 2 is the real-code version.

### 5. A flat template accepts anything. Theorem true, attack refuted.

- **Lean**: an all-128 I template has zero energy, so any recording passes (`flat_template_any_recording`, `zero_template_accepts`).
- **Read in code**: templates aren't chosen by the attacker. The server pins `code_commit` (`verdict.py:142`). It also signs it for the chain (POPCC1), but only the Noir verifier reads that signature, and it isn't deployed. Only a malicious server reaches this, and a malicious server can forge everything anyway.
- **One-off**: on real codes the Q and I template energies are equal to within 0.1%. No byte was -128.

Optional hygiene: sum `c_q²` into the template energy too, or assert `cna > 0`.

### 6. Block E checks "loud enough", not "first". Owner to confirm.

**What it accepts today.** `partner_side` tests one lag: `BAR × match ≥ loudness` at `a_partner` (`lib.nr:436-473`, Lean `partner_loud`). `phone_core` adds `-7200 ≤ a_partner − p_partner ≤ 12000` (`lib.nr:525-526`, Lean `phone_core_glue`). So any passing lag in that range is accepted, not just the first. An honest app does take the first (`PopRound2.kt:78`). Its pre-proof check tests only the one lag, like the circuit (`WitnessInput.kt:119`).

**What a cheater can do.** By hand.

- Sign a later lag, if the recording has one over the bar: an echo, or a beep played twice. Old fixtures had echoes over the bar 6-15 samples late, score 38-48% (old README, line 301). Each frame later on either phone adds 0.36 cm of flight, because `flight = 17150 × (half_A − half_B) / 48000`.
- That only pushes the reading up. Sept far fixtures reached 402-707 cm this way (old README, line 325). A near phone could make its pair read NOT_NEAR, but it could also just fail the run.

**What it can't do, with this alone.** By hand.

- Pull a far pair near. That needs an earlier lag over the bar, and a genuine recording has none before its first. The Sept tamper `resign_early` signed a lag 100 frames earlier and hit the partner bar (`optA-noir.md`, section 6. Inferred, no log, see the evidence table).
- An injected early peak isn't this gap. That peak would be the first passing lag, so "first" accepts it too.

**"First" alone wouldn't narrow it for a dishonest signer.** By hand. `p_partner` is a number the signer picks. The circuit checks nothing else about it (`lib.nr:285`), and on the server it shows up only in the decoder's field list (`codec.py:34`). Set `p_partner = a_partner + 7200` and `a_partner` is the window's first lag, so every earlier lag falls outside. The later-lag freedom can't be separated from this one, or from the free `half` in gap 7.

**Why it's like this.** It was known in September. The old README lists it under "Remaining gaps" as a limit bounded by a chance budget, and doesn't call it intended. It's at `research/sound-bound/spikes/zk/optionA-v2/README.md`, added in `0691db1` (2026-09-26), removed in `53604e3`. Read it with `git show '53604e3^:research/sound-bound/spikes/zk/optionA-v2/README.md'`.

- Line 348: "The partner arrival is one-sided. The proof alone admits any lag ≥ bar in the window."
- Line 329: "The proof accepts any lag ≥ 9% in the window. A cheater gains only from an earlier one, which has to be a chance match."
- Lines 331-341: 64 wrong codes per window on 24 windows, highest score 7.10%. Chance of clearing 9% anywhere in 19,200 lags: median 6.7e-7, worst window 1.2e-5, 2.4e-5 with one retry.
- Line 343, why the window is this wide: "On the web data only w400 is complete: cross arrivals sat 74–138 ms late." `b555c3f` (2026-11-06) has the same problem. A Pixel 6 fired 200 ms late, so web now moves `p_partner` by the self offset (`RunFlow.kt:283-284`).
- The Noir port kept the statement (`optA-noir.md:61`, "same"; comment at `lib.nr:436`). `lib.nr` has one commit in git (`5acd098`), so it holds no line history.
- Not found: any source tying this choice to echoes, as earlier versions of this doc and `02-scope.md` guessed. The only echo note is the fixture on line 301, a test of the self rule. Also not found: cost given as a reason. Rough estimate, not measured and not from the history: a "first" check over 19,201 lags needs 32 leaves, not 13, and about 975k gates for the Fiat-Shamir sponge alone (scaled from 10,108 gates per 398 values), against 75.7k gates of headroom. Not measured.

**What has moved since then.** "Has to be a chance match" came from wrong codes on real audio. Silence and a tone (gaps 1, 2) pass without being chance, so the budget doesn't cover them. Line 325's "the self arrival is forced" doesn't hold for a dishonest signer either. The same folder's `REVIEW.md` said so in September (F3, line 116).

**Owner to confirm.** Not decided here.

1. Is "any passing lag" the intended statement for this circuit? The September note accepts it as a bounded gap. Nobody has signed off on it since gaps 1 and 2 turned up.
2. If yes, does the chance budget still stand as the written reason, with gaps 1 and 2 tracked apart?

Today's proofs don't depend on the answer. `partner_loud` proves the statement as it is.

### 7. `half` is a free choice. Confirmed, low.

**Real circuit:** two silent phones with chosen halves solved `pair` at 0 cm (case e1). A silent phone also fit a genuine partner at 33.9 cm (case e2), but that run handed it the partner's half, which a real cheater would have to guess to about 5 ms or learn with a mic.

Settled by reading the code. No `nargo` was needed for this reasoning.

- `p_partner` is an app prediction that nothing verifies (`lib.nr` 285). The window checks at 525-526 are relative to it.
- `a_self` is free, because the signer knows its own code.
- The leaf offsets can be met for any position in the 2.5 s capture.

On the proof path, a dishonest signer picks `half` freely, given any passing partner lag at the position it wants. Silence gives that today, and a tone might. Without such a lag, `half` is tied to "the partner's code is present there". So on this path it closes with the fixes for gaps 1 and 2.

On the plaintext path `half` is free regardless, because no circuit runs before NEAR (`verdict.py:165`, `sessions.py:604-605`). Fixing the circuit doesn't change that unless proofs become required.

"Low" rates the gain. A lone far cheater still needs the honest partner to pass (`PopRound2.kt:80`, `RunFlow.kt:324`). The half is blind, so it must land in a band about 224 frames wide at 48 kHz around the partner's. Two colluding signers need no audio at all.

### 8. 44.1 kHz can't prove. Confirmed, completeness only.

`zk.CIRCUITS` holds only 48000. `lib.nr:240` forces the rate. `sessions.zk_expected` rejects other rates with 409. But `server/pop/sessions.py:43` still says "44.1 / 48 kHz", and `constants.py` has `ZK_RATES = (44100, 48000)`. Compile a 44.1 kHz circuit, or drop it from those two places.

### 9. A and B share codes. Refuted.

`jbl250.bed_key` includes the role and the attempt. Codes differed on 40 of 40 seeds. One footgun, not a finding: `popt2.code`'s role argument does nothing for the bed. Separation rests entirely on `bed_key`.

### 10. The Noir verifier doesn't bind devices. Confirmed, not live, outside FV scope.

`NoirPresenceVerifier.verifyPresence` returns `(0, 0)` (line 72). The guard then needs two signing owners who have a registered device, but not that the proving phones are theirs (`PopSafeGuard.sol:260-263`). So the owners can sign from anywhere while two other credentialed phones get NEAR in a session made for that transaction. High only if a Noir guard is deployed.

The live guard uses the attestation verifier (`verifierKind` in `contracts/deployments/11155111.json`). It returns the server-signed device hashes, and the guard requires those devices' owners to sign (`PopSafeGuard.sol:265-270`). That binding rests on the server.

Fix, before any Noir switch: expose device hashes or key limbs as public inputs of `pair`, and bind them in the guard.

## Smaller findings

These aren't soundness holes.

| Finding | Evidence |
|---|---|
| Phone forces sample rate = 48000; `pair` allows 36000..96000. Harmless, but the wide range is unreachable. | by hand |
| Merkle index limit caps arrivals at about 5.2 s at 48 kHz. Later arrivals can't be proved. | by hand |
| `pair` compares key limbs and doesn't range-check them. "Real keys differ" needs the phone proofs and hash binding. | by hand |
| 32-byte reads can wrap. `rec_root` relies on Noir's `to_be_bytes` being canonical. | Lean, `beF32_wraps` |
| Comment in `Popt2Rule.kt:98` is wrong twice. `passes(2^61, 0, 1, 1, 2^31)` returns false, but the true answer is yes. Its `cn2 < 2^32` is also broken by its own test, which uses 9164281855. Live inputs can't reach the first case. | Lean, `docstring_bound_hole`; read in code |
| Kotlin `pSelf` can wrap where the circuit doesn't: `aSelf = 2^31-1`, `selfOsDelta = -2^31` gives -1 vs 2^32-1. | Lean, `hole_pSelf_overflow` |
| The same case looks unreachable, and the circuit would reject the wrong value. `WitnessInput.kt:103` refuses first. | by hand |
| The `a_self` and `p_partner` reads have no range check in the circuit. At 2^31 or above, Kotlin sees a negative number. | read in code |

## Checked and fine

- No overflow in the 96-bit checks. Largest value 2^94.2.
- The distance check is exact: strict at both ends. The 70-bit width has spare room (real values under 2^64).
- BAR is right at 48 kHz, 0.47 from a rounding edge (Lean + script).
- Filter taps, `BAR`, `L`, delta, wpre and wpost match across `lib.nr`, `Popt2Rule.kt` and `popt2.py` at 48 kHz, and across app and server at 44.1 kHz. Script, comparing source text: `rates_parity.py`, 42 comparisons, 0 differences.
- `lib.nr`, `phone/main.nr` and `pair/main.nr` have the same bytes as the built copies.
- The deployed `PairVerifier` VK hash matches the built copy.

## New circuit concerns (2026-11-06)

Frozen circuit, so report only. None is rated. **None of these is in `fv/v1/next-version-fixes.md` yet.**

| Concern | Evidence |
|---|---|
| **Past-capture window.** The tree always has 256 leaves padded with 32768, and the transcript has no capture length. A window past the capture reads padding and passes `partner_side`. Needs a dishonest signer. Not run in `nargo`, and not shown reachable through a whole statement. | Lean, `Commit.past_capture_witness`: a 120000-sample capture with no silent sample, opening at leaf 118 |
| **Partner Y is unread.** Bytes 137-168 reach the proof only through `sha256(t)`. The server compares whole keys. | Lean, `Signed.junk_accepted`; `verdict.py:159` read in code |
| **Partner key has no check.** No credential, signature or curve check. Only "X differs from own X". | Lean, `Signed.bad_keys_pass_byteChecks`: partner X = 1, Y = 0 |
| **`commit_hash`, play and capture times are hash-only.** Nothing compares `commit_hash` to a POPC commitment or to `rec_root`. | Lean, `Signed.junk_accepted`, `digest_only_free` |
| **Holder commit is never opened.** | Lean, `Signed.holder_commit_free` |
| **`rec_root` ties to no value in the circuit**, beyond the opened leaves. Other subtrees can be anything. | Lean, `phone_sound_no_tree` needs filler; by hand for the rest |
| **Own key has no curve check of its own.** It rests on the opaque ECDSA blackbox. No low-S check, no device key vs issuer key check. | Read in the model |
| **Issuer and `code_commit` are whatever the public inputs say.** `pair` ties nothing about them across the two phones. `valid_at` is an upper bound only, with no freshness. | Read in the model. By hand: all-128 `c_i` makes loudness 0 |
| **`pair` doesn't link its commitments to a phone proof.** That's the verifier's job. | Read in the model |

## Lampe: not usable today

Verdict from reading source only. **Nothing built, nothing extracted, no Lean came out.** The one attempted extractor build was denied as external code, and that wasn't routed around.

- Lampe main (`3d7668f`, 2026-10-21) pins Noir beta.19. Ours is beta.22. Two `oalib` calls shouldn't typecheck there: `poseidon2_permutation(self.s)` (`lib.nr` 62, 68) and `bits: [bool; 8]` (`lib.nr` 109). Inferred from signatures, not observed.
- Open PR #311 moves to beta.25, which should accept those two calls. It is unmerged, and no Lampe matches beta.22 exactly.
- Lampe is on Lean 4.29.1, and we're on 4.36.0-rc2, so its output can't import into `Popfv`.
- Its crypto layer uses `native_decide`, which would break our axiom rule if p is fixed or `phone`'s ECDSA is touched. Poseidon2 and ECDSA are concrete there, where ours are opaque with named hypotheses.
- PR #310, unmerged: `for i in a..=b` extracts without its last iteration. `oalib` has no such loop. The `sha256` dependency does.

Rough guess, from the reviewer: a day or two for `pair`, weeks for all blocks. So the hand model stays, and it is still the weakest link. The owner decides whether to allow the build for a #311 try.

## What was NOT done

- **No proof made from the crafted cases.** `nargo execute` ran them all (`fv/v1/zkp/circuit-cases/RESULTS.md`), but `bb prove` didn't. The keys were throwaway, so none of this ran against the real issuer, a real device, a server or a chain.
- **Real speaker and mic: one quiet run only.** One real recording, Pixel 6, normal source, 16-bit: 0/800 at amplitude about 835, too quiet to settle it. In simulation on that room's noise it needs amplitude 5000 or more (roughly 93 dB at the phone, not measured) and under about 0.3% speaker distortion. Not demonstrated in a real room.
- **No non-silent run of the joined model.** See the verdict table.
- **Hashes and signatures are not proved secure.** Blocks A, B, C and H rest on the named hypotheses above. The random-oracle step for block C is unproved, and `Freivalds.RecRootBinds` and `CodeCommitBinds` aren't connected to `Commit.lean`.
- **No loud recording in Lean.** The end-to-end witnesses are silent, with toy crypto.
- **BAR layer 3 not started.** The chance that random sound clears 0.09 (see [03-bar.md](03-bar.md)). Gaps 1 and 2 must be fixed or scoped first, or that theorem is false.
- **The `earliest()` FFT screen is unproved.** Nothing shows it never skips a lag the exact rule passes. A miss costs completeness only.
- **Model drift.** The Lean models are hand-written. Lampe is not usable today, see above. The block-level fixture test `Signed.fx_sound` covers block A's bytes. The `180ca04b_48k` differential test in [04-plan.md](04-plan.md) hasn't been run.
- **Kotlin side of rows 3, 4, 9.** `Commit.lean` models the circuit's leaf packing, Merkle path and code commitment. `OaHash.kt` and `CodeCommit.kt` aren't modeled.
- **Block E tone runs and the code survey have no script in the repo.** Their numbers can't be replayed exactly. `tone_test.py` has the exact partner test, but it scores new recordings on its own codes.
- **Protocol attacks.** Relay, collusion, replay: other tools (Tamarin).

## Next steps

See [04-plan.md](04-plan.md).
