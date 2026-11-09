# fv/v1.1: the EVP recovery variant

v1.1 is the v1 circuits, server and issuer, plus one copy of `pair` with `xa` and `xb` made public. That's the only circuit change: `xa: pub [Field; 2]`, `xb: pub [Field; 2]`.

The Lean adds one result. If `verifyPresence` (`EvpNoirPresenceVerifier.sol` lines 61-104) accepts, then v1's `presence_sound` holds for the witnesses behind the three proofs, and those witnesses are tied to the keys, nonce and issuer the contract was given.

It sits on v1 as merged at `ce2b920` (#30). If v1's `Chain.lean` or `Pair.lean` changes, rebuild and reread the theorem. Built against `Chain` 6b600140d55b25e4, `Pair` b440179eed287c0c, `Signed` a966e3c7eca46fe9 (sha256 prefixes).

## Files

- `zkp/evpfv/Evpfv/Adapter.lean`: a hand model of the contract's checks.
- `zkp/evpfv/Evpfv/Limbs.lean`: Noir limbs against `PopCtx.split`, and the pair's public input order.
- `zkp/evpfv/Evpfv/Glue.lean`: the main theorem. It reuses `presence_sound` and re-proves none of it.
- `circuit/pair_named`: the v1.1 pair. `circuit/pair_ref` is a byte copy of the frozen pair, kept as a baseline.
- `circuit/forge`, `circuit/RESULTS.md`: gas and size runs. `circuit/frame_tx`: the frame tx through `evpVerify`.
- `circuit/forge/fixtures/`: the real bundle and the frame tx results on chain 1337.

## Theorems

`lake build Evpfv` passes, 18205 jobs. No `sorry`, no `native_decide`, standard axioms only.

| Theorem | File | Review | Mutants |
| --- | --- | --- | --- |
| `adapter_pins`, `split_join` | Adapter | Codex + Opus: one defect (`ccSig` didn't see the key), fixed. The fix wasn't reviewed again. | 5 of 5 stopped proving |
| `limbs_pin_key`, `pairPublicInputs_keys` | Limbs | Codex + Opus: no defects | 3 of 3 stopped proving |
| `evp_presence_sound` | Glue | Codex + Opus: no proof defect, 4 doc defects fixed | 2 of 3 stopped proving, see below |

The Glue mutant that survived drops the role check on word 3. That's expected, because Glue never reads word 3 and the role comes through `HalfBinds`. The docstring says so. Glue mutants ran before the `ccSig` fix and weren't rerun. No Fable review ran.

## Assumptions

- **`AdapterAccepts`** is a hand reading of the Solidity. Nothing links them. P-256 (`Env.ccSig`) is abstract.
- **`PhoneVerifierSound`, `PairVerifierSound`:** a verifier's yes means a witness exists. Not proved.
- **`PhoneRelation`, `PairRelation`** are hand copies of the public input order.
- **`Widths`** covers Solidity widths the model drops. `deadline_ok` is `deadline + 300 < p`. The account guarantees it, but a direct call to the adapter may not.
- **`Trust`** is everything `presence_sound` already needs. Nobody has shown the whole set can hold at once.

## Gas

**The frame tx through the real account, 2026-11-07.** A real 4-frame tx on chain 1337, with three real proofs bound to a fresh `ctx` and no mocks. VERIFY passed and the tx mined, then the body reverted on a junk token, so nothing rotated. Tx `0x341aaba06e088193ed20e9c7d59294cef581174fdac41bf58724a09a1b43ec5c`.

| Frame | Limit | Used |
| --- | ---: | ---: |
| 0, expiry | 4,000 | 3,051 |
| **1, `evpVerify`** | **12,000,000** | **11,545,764** |
| of which `verifyPresence` | | 11,510,370 |
| 2, L pays | 8,000 | 3,000 |
| 3, body, reverts | 110,000 + 100,000 state | 2,709 |
| Whole tx | | 12,037,188 |

Frame 1 has 217,627 gas to spare once the 1/64 hold-back is counted. Its data is 30,052 bytes.

What's real: the proofs, `ctx`, the frames, both enclave signatures, the audio. What's not: the audio comes from an old walk, role A is a Mac enclave key rather than a laptop chirp, POPCC1 and the credentials were signed locally, and the email token is junk.

**Per proof**, earlier the same day:

| | forge | chain 1337 |
| --- | ---: | ---: |
| Phone A | 4,072,116 | 4,072,916 |
| Phone B | 4,067,116 | 4,067,116 |
| pair_named | 3,318,955 | 3,319,755 |
| Adapter | 49,783 | 50,583 |
| **`verifyPresence`** | **11,507,970** | **11,510,370** |

pair_named costs +4 gates and +5,642 gas against the frozen pair. Proof size and verifier size don't change. Flipping any of the 11 public inputs gets rejected. Versions, addresses and hashes are in `circuit/RESULTS.md`.

## What it doesn't say

- Silence and a clean tone still pass, same as v1. Nobody heard a beep.
- Flight is arithmetic on signed numbers. It's not a location.
- Only X coordinates are compared. Y is never read.
- The account layer isn't modeled: `ctx`, what `popNonce` hashes, `newKey`, which device is which.
- There's no clock. Only frame 0's expiry ties the window to real time.
- The EVP threat model limits still apply. One cheating side can fake NEAR. A copied laptop key works next to the attacker's own phone. A stolen unlocked laptop wins.

## Open

- No real token has reached the body yet, so rotation hasn't run on chain.
- The node doesn't expose frame 3's revert data. `BadHint(5)` comes from reading the code.
- The account path ran only on chain 1337, not in forge.
- The session was scripted on one Mac. No server issued it, no laptop chirped, no phone signed.
- A direct `eth_call` on the adapter uses 3,588 less gas than forge. Unexplained.
- Only reading links `AdapterAccepts` and the input orders to the compiled code.
- The Adapter and Limbs reviews are recorded only in the table above.

## Reproduce

Lean, from `zkp/evpfv`. It needs `fv/v1/zkp/popfv` beside it.

```
lake exe cache get
lake build Evpfv
```

Circuit, from `circuit`. `oalib` comes from `research/worldid/prototypes/optA-noir/noir/oalib`.

```
bash prove.sh
cd forge && bash run.sh
```

For the real bundle, see "Real bundle through the adapter" in `circuit/RESULTS.md`.
