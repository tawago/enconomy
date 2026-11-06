# fv/v1.1: the EVP recovery variant

v1.1 = the v1 circuits, the same server and issuer, plus one copy of the `pair` circuit with `xa` and `xb` public. Nothing else changes.

The one circuit change is two words: `xa: pub [Field; 2]`, `xb: pub [Field; 2]`.

The Lean here adds one thing to v1: if `verifyPresence` (`EvpNoirPresenceVerifier.sol` lines 61-104) accepts, then v1's `presence_sound` applies to the witnesses behind the three proofs, and those witnesses are tied to the keys, nonce and issuer the contract was given.

**This sits on v1 as merged at `ce2b920` (#30).** If v1's `Chain.lean` or `Pair.lean` change, rebuild, and read the theorem again. Built against these sha256 prefixes, which match that commit: `Chain` 6b600140d55b25e4, `Pair` b440179eed287c0c, `Signed` a966e3c7eca46fe9.

## Layout

- `zkp/evpfv/Evpfv/Adapter.lean`: hand model of the contract's checks. Imports nothing.
- `zkp/evpfv/Evpfv/Limbs.lean`: Noir limbs against `PopCtx.split`, and the pair's public input order.
- `zkp/evpfv/Evpfv/Glue.lean`: the main theorem. Reuses `Popfv.Chain.presence_sound` by path require, re-proves none of it.
- `zkp/logs/build.txt`: the final build output, runner lines removed.
- `circuit/pair_named`: the v1.1 pair. `circuit/pair_ref`: byte copy of the frozen pair, baseline only. `circuit/commit_helper`: makes the throwaway inputs.
- `circuit/forge`, `circuit/RESULTS.md`: gas and size runs.
- `circuit/forge/fixtures/field_180ca04b`: the real bundle. A and B proofs, re-proved pair with its witness, POPCC1 signatures, chain 1337 results.
- `circuit/frame_tx`, `circuit/forge/fixtures/frame_180ca04b`: the frame tx through `evpVerify`. Scripts, fresh proofs, chain 1337 results.

## Theorems

Final `lake build Evpfv`: exit code 0, 18205 jobs. No `sorry`, `native_decide` or new axiom. Every `#print axioms` line in the log, v1's too, stays inside propext, Classical.choice, Quot.sound.

| Theorem | File | Status | Review | Mutation |
| --- | --- | --- | --- | --- |
| `adapter_pins`, `split_join`, `adapter_accepts_example` | Adapter | proved | Codex + Opus: no missing or wrong check, 1 defect (`ccSig` did not see the key), fixed. The fix was not reviewed again | 5 of 5 stopped proving `adapter_pins`: drop `p[7]`,`p[8]` pin; drop `bb` issuer check; read `p[8]` for `p[9]`; swap hi and lo in the `deviceA` pin; after the fix, swap `qx`, `qy` in `cc_a`. The first four ran before the fix |
| `limbs_pin_key`, `limb_cast_inj`, `own_key_split`, `pairPublicInputs_keys` | Limbs | proved | Codex + Opus: no defects | 3 of 3 stopped proving: swap hi and lo; offset 57 for 56 in the hypothesis; offset 57 everywhere. The swapped and offset 57 statements were also proved false by explicit counterexamples, not kept in the tree |
| `evp_presence_sound_at`, `evp_presence_sound` | Glue | proved, under the assumptions below | Codex + Opus: no proof defect, 4 doc defects, all fixed | see below |

Glue mutants, each with the field dropped from the Adapter so the failure lands in Glue. Drop `p[9]`, `p[10]` pin: stopped proving. Drop `a[11] = p[3]`: stopped proving. Drop `a[3]`, `bb[3]` role check: **still proved.** Explained: Glue never reads word 3, role comes through `HalfBinds`. The docstring now says so.

Glue mutants ran before the `ccSig` fix and were not rerun. Stopped proving means the proof needed that field. Apart from the Limbs ones above, no counterexample was built. Review was Codex plus Opus. No Fable review ran. The doc fixes were rebuilt, not reviewed again.

## Named assumptions

`evp_presence_sound` says: three witnesses exist whose public values are the contract's words read as field elements, and under `Trust` the conclusion holds for them.
- `AdapterAccepts`: the contract's checks. A hand reading of the Solidity, nothing links them. Same for P-256 in `_ccOk`: `Env.ccSig` is abstract.
- `PhoneVerifierSound`, `PairVerifierSound`: a verifier's yes means a witness exists. Not proved.
- `PhoneRelation`, `PairRelation`: hand copies of the public input order, read against `phone/src/main.nr` and `circuit/RESULTS.md`. No check links them.
- `Widths`: Solidity widths the `Nat` model drops. `deadline_ok` is `deadline + 300 < p`. The account's `be64` deadline gives it; a direct call to the adapter may not.
- `Trust`: all of what `presence_sound` takes, unchanged: `Assumptions` and not-`Fooled` for each phone, `HalfBinds` for each half. That the whole set can hold at once is not shown in v1.1.

## Gas and size

### Frame tx through the real account, 2026-11-07, latest

A real 4-frame tx on chain 1337, sent through our own sidecar. Frame 1 ran `evpVerify` on a fresh `EvpRecoveryAccount` with three real proofs bound to a fresh `ctx`. No mocks. VERIFY passed, the tx mined in block 8720, the body reverted on a junk token, nothing rotated. Tx `0x341aaba06e088193ed20e9c7d59294cef581174fdac41bf58724a09a1b43ec5c`. Detail in `circuit/RESULTS.md`.

| Gas | Limit | Used |
| --- | ---: | ---: |
| Frame 0, expiry | 4,000 | 3,051 |
| **Frame 1, `evpVerify`** | **12,000,000** | **11,545,764** |
| of which `verifyPresence` | | 11,510,370 |
| of which the account's share, entry included | | 35,394 |
| Frame 2, L pays | 8,000 | 3,000 |
| Frame 3, body, reverts | 110,000 + 100,000 state | 2,709 |
| Whole tx | | 12,037,188 |

- **Frame 1 margin: 217,627.** Smallest limit that passes is 11,782,373, by search with `ethrex_simulateFrameTransaction`. Plain 12M minus used is 454,236, but that ignores the 1/64 hold-back.
- 35,394 replaces the old 32,322 + 3,400 from mock proofs.
- Frame 1 data 30,052 B, new largest sent. No limit hit in the sidecar or ethrex.

Real: the three proofs, `ctx`, the frames, both enclave signatures, the audio. Not real: the audio is from an old walk, role A is a Mac enclave key and not a laptop chirp, POPCC1 and credentials are signed locally and not by the server, the email token is junk.

### Plain tx, no account, earlier the same day

Three real proofs through the real `verifyPresence`, no mocks, 2026-11-07. nargo 1.0.0-beta.22, bb 5.0.0-nightly.20260522, forge 1.9.0, solc 0.8.30, Osaka, runs 1, adapter via-ir (it does not compile without). Detail, addresses and tx hashes in `circuit/RESULTS.md` and `circuit/forge/fixtures/field_180ca04b/chain1337.json`.

| Gas, per call | forge | chain 1337 |
| --- | ---: | ---: |
| Phone A | 4,072,116 | 4,072,916 |
| Phone B | 4,067,116 | 4,067,116 |
| pair_named | 3,318,955 | 3,319,755 |
| Adapter's own work | 49,783 | 50,583 |
| **`verifyPresence` total** | **11,507,970** | **11,510,370** |

Chain 1337: `eth_call` returned the selector. Plain tx through a thin wrapper, status 1, `0xc68df63826b98383deb7dca97baa2547f1c4f69e0fbe660a8047979670c59a99`. Wrong `deviceB` reverts `BadPublicInputs(8)` in forge and in `eth_call`.

Frame 1 against 12,000,000, with the 1/64 hold-back:
- **Measured on chain, wrapper in place of the account: smallest gas 11,752,576, so 247,424 left.** A mined tx with exactly 12M after intrinsic passed.
- **Modeled with the real account: about 216,600 left.** Uses the older account share, 32,322 from the mock frame, plus 3,400 entry and helper. The account did not run.

Calldata: bundle 29,632 B, `verifyPresence` 29,924 B. Plain tx mined at 30,052 B.

Not shown by this run, the frame tx above covers the first three: no `ctx`, a fixed old nonce, the account layer not exercised. Also audio from an old walk, role A is a Mac enclave key and not a laptop chirp, and the `deadline` is long past.

Older numbers, from before this run, throwaway pair inputs:

| | frozen pair | pair_named | change |
| --- | ---: | ---: | ---: |
| ACIR opcodes | 57 | 57 | 0 |
| Gates | 3,459 | 3,463 | +4 |
| After padding | 2^12 | 2^12 | 0 |
| Proof | 7,232 B | 7,232 B | 0 |
| `verify` gas, gas report | 3,313,313 | 3,318,955 | +5,642 |
| `verify` gas, gasleft delta | 3,319,044 | 3,325,048 | +6,004 |
| Verifier runtime | 16,901 B | 16,901 B | 0 |

Each of the 11 public inputs flipped in turn: all rejected.

The earlier budget used phones 4,083,276 + 4,069,887 (Nov 2, old circuit), adapter with mocks 82,905 and entry plus cold 4,600 (`evp-recovery/REPORT.md`). It gave a plain-sum 434,284 and a margin after hold-back of 199,520. Today's numbers replace it.

## What it does NOT say

- **Silence and tone, from v1.** Silence and a clean tone still pass. This does not say a beep was heard.
- **Signed numbers, not location.** Flight is arithmetic on what the phones signed.
- **X only.** No Y is compared. A phone's partner Y is never read. "Device" means an X coordinate.
- **Account layer not modeled.** Nothing looks at `ctx`, what `popNonce` is the hash of, or the `newKey` keccak. `popNonce` is just a number the three proofs share. That `deviceA`, `deviceB` are the laptop and the new phone is the account's job, also not modeled.
- **No clock.** The window is relative to `deadline`. Only frame 0's expiry check ties it to real time.
- **P-256 is abstract.** `Env.ccSig` takes `(qx, qy)` as an argument, but nothing says it is the real signature check. `_ccOk` means the `Env`'s check passed on that key, no more.
- **Limits from the EVP threat model and progress report section 6, all still there.** One cheating side can fake NEAR. A copied laptop key gets a real NEAR on the attacker's own laptop beside their own phone. An unattested laptop can edit its half. A stolen unlocked laptop still wins, and a stolen phone is not covered.

## Open

- No real token has reached the body. Frame 3 carried junk, so the rotation has not run on chain, and the body's gas is still the forge number.
- Frame 3's revert data is not exposed by the node. `BadHint(5)` is read from the code and fits the trace, it was not seen.
- The account path did not run in forge. It only ran on chain 1337, so no forge number exists to compare.
- The session is scripted on one Mac. No server issued it, no laptop chirped, no phone signed.
- The deployed phone verifier matches the phone circuit as it stands now: same VK hash after a rebuild.
- A direct `eth_call` at the adapter needs 3,588 less gas than forge, not the slightly more the cold-account pricing predicts. The wrapper path matches. Not explained.
- Nothing links `AdapterAccepts` or the public input orders to the compiled code but reading them.
- Contract lines 82 (role) and 84 (rate) carry no weight in this theorem. Reading word 3 directly, so role needs no `Trust`, was not tried.
- The Adapter and Limbs reviews are recorded only in the table above, no review files are in the tree. The `ccSig` fix was rebuilt and got one mutant, no second review.
- `Glue.lean` is 259 lines, a little over the 250 aim.

## Reproduce

Lean, from `zkp/evpfv` (Lean 4.36.0-rc2, Mathlib v4.36.0-rc2, needs `fv/v1/zkp/popfv` beside it by the path in `lakefile.toml`):

```
lake exe cache get
lake build Evpfv
```

Circuit, from `circuit`. `oalib` comes from `research/worldid/prototypes/optA-noir/noir/oalib`:

```
bash prove.sh             # compile, gates, execute, write_vk, prove, verify, write_solidity_verifier
cd forge && bash run.sh   # forge build --sizes, forge test -vv, forge test --gas-report
```

Real bundle: see Commands under "Real bundle through the adapter" in `circuit/RESULTS.md`.
