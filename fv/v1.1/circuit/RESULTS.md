# pair_named: gas and size

Measured 2026-11-07. Throwaway inputs, valid NEAR opening, no signature needed.

## Circuit

`pair_named` is the frozen `noir/pair` with `pub` added to `xa` and `xb`. Nothing else changed in the code.
`pair_ref` is a byte copy of the frozen pair, built only as the baseline.

```
15,16c15,16
<     xa: [Field; 2],
<     xb: [Field; 2],
---
>     xa: pub [Field; 2],
>     xb: pub [Field; 2],
```

Public inputs, from the ABI and from `out/public_inputs` (352 B = 11 x 32):
nonce_hi, nonce_lo, attempt, commit_a, commit_b, sr_a, sr_b, xa[0], xa[1], xb[0], xb[1].
This matches `EvpNoirPresenceVerifier.sol` lines 13-14.

The generated verifier says `NUMBER_OF_PUBLIC_INPUTS = 19`. That is 11 + 8 pairing fields inside the proof. `verify()` takes 11.

## Versions

nargo 1.0.0-beta.22 (same `noir_version` as the frozen build), bb 5.0.0-nightly.20260522, forge 1.9.0, solc 0.8.30, Osaka, optimizer runs 1, no via-ir.

`pair_ref` is the same build as deployed: its compile hash is 5097533778046084836, same as `fv/v1`'s frozen `pair.json`, and its VK_HASH equals `contracts/zk/src/PairVerifier.sol`.

## Numbers, all measured today

| | pair (frozen) | pair_named | change |
| --- | ---: | ---: | ---: |
| ACIR opcodes | 57 | 57 | 0 |
| Gates, `bb gates` circuit_size | 3,459 | 3,463 | +4 |
| Circuit size after padding | 2^12 | 2^12 | 0 |
| Proof | 7,232 B | 7,232 B | 0 |
| `verify` gas, gas report | 3,313,313 | 3,318,955 | +5,642 |
| `verify` gas, gasleft delta with call | 3,319,044 | 3,325,048 | +6,004 |
| Verifier runtime | 16,901 B | 16,901 B | 0 |
| RelationsLib / ZKTranscriptLib runtime | 7,964 / 6,108 B | 7,964 / 6,108 B | 0 |
| Verifier initcode | 17,228 B | 17,228 B | 0 |

Forge version drift: none seen here. The frozen pair's 3,313,313 today is the exact Nov 2 gas report figure under forge 1.4.3.

Tamper: flipping the low bit of each of the 11 public inputs in turn reverts with `0x9fc3a218`. All 11 rejected.

## Frame 1 budget against 12,000,000, throwaway pair

| Part | Gas | When |
| --- | ---: | --- |
| Phone A + phone B (about 4.07M x2), gasleft delta | 4,083,276 + 4,069,887 | Nov 2, forge 1.4.3, old circuit, `research/ethglobal-mumbai/poc-verifier-gas/README.md` |
| pair_named, gasleft delta | 3,325,048 | today |
| Adapter and account with mock proofs | 82,905 | `research/ethglobal-mumbai/evp-recovery/REPORT.md`, older, forge 1.4.3 |
| Entry 3,000 + 4 cold accounts at 400 (helper, adapter, two verifiers) | 4,600 | same REPORT, modeled |
| **Plain sum** | **11,565,716** | 434,284 left |

The plain sum flatters us. EIP-150 holds back 1/64 at each call. REPORT's forwarded test, with burn mocks at the 12M limit, fits a pair of up to 3,524,568. Against that, real margin is **3,524,568 - 3,325,048 = 199,520**.

So it fits on the Nov 2 phone numbers. The real proof through the adapter is the next section. The rest of this section stays as measured earlier today, with throwaway pair inputs.

## Real bundle through the adapter

Measured 2026-11-07, later the same day. Three real proofs through the real `verifyPresence`, no mocks, in forge and on chain 1337. Fixture 180ca04b_48k, in `forge/fixtures/field_180ca04b`.

Inputs:
- Phones: the existing A and B proofs, byte copies, not re-proved. `PhoneVerifier.sol` is a byte copy of `contracts/zk/src/PhoneVerifier.sol`.
- Pair: re-proved on `pair_named` with the field witness, `prove_field.sh`. The witness commits equal A and B word 11. VK equals `pair_named/vk`.
- POPCC1: signed today with the dev issuer key, `sign_popcc1.py`, low-S as the server does. Only the signatures are in the fixture. Both verified with openssl first.
- `popNonce` is A's words 0, 1. `deviceA`, `deviceB` are `xa`, `xb`. Issuer is A's words 5..8. `notBefore` 1789999400, `deadline` 1790000600, `maxAge` 1200, around `valid_at` 1790000000.

Build: solc 0.8.30, Osaka, runs 1, forge 1.9.0. Verifiers no via-ir, as before. The adapter is via-ir: without it, solc stops with stack too deep. Its own `foundry.toml` is via-ir at runs 1,000,000, and that setting was not measured.

Results:
- Forge: selector returned. Wrong `deviceB` reverts `BadPublicInputs(8)`.
- Chain 1337: `eth_call` returned `0x7dd7b02c`. Wrong `deviceB` reverts `0x58df4847...08`, which is `BadPublicInputs(8)`. Plain tx through `PresenceLog`, status 1, block 8461: `0xc68df63826b98383deb7dca97baa2547f1c4f69e0fbe660a8047979670c59a99`.

Addresses and every tx hash are in `forge/fixtures/field_180ca04b/chain1337.json`. A chain reset wipes them.

| Gas, per call | forge | chain 1337 |
| --- | ---: | ---: |
| Phone A, trace | 4,072,116 | 4,072,916 |
| Phone B, trace | 4,067,116 | 4,067,116 |
| pair_named, trace | 3,318,955 | 3,319,755 |
| Three verifiers | 11,458,187 | 11,459,787 |
| Adapter's own work, decode and 2 x P-256 included | 49,783 | 50,583 |
| **`verifyPresence` total, trace** | **11,507,970** | **11,510,370** |
| gasleft delta around the call | 11,532,190, test's own memory included | 11,520,986, `PresenceLog` event |

Chain minus forge is +400 per cold account, every time: 6 in the adapter's frame, phone and pair verifiers plus 4 libraries. Phone A minus phone B is 5,000, the 2 libraries going warm.

### Is the margin real?

Frame 1 limit 12,000,000, with the 1/64 hold-back at each call.

Measured, chain 1337:
- Smallest gas after intrinsic through `PresenceLog`, found with `eth_call`: 11,752,576. That is **247,424** under 12M. This path holds back at wrapper to adapter, adapter to verifier, and inside the real verifiers.
- A mined plain tx with exactly 12,000,000 left after intrinsic: accepted. The pair was offered 3,560,853 and used 3,319,755.
- `PresenceLog` is not the account. It is a thin stand-in, one level of call depth like the account.

Smallest gas handed to the adapter: 11,561,678 in forge, all accounts cold. A direct `eth_call` at the adapter gave 11,558,090, which is 3,588 lower and goes the wrong way, by about 6,000, given the +400s. Not explained. Back-computing from the wrapper run gives about 11,564,090, which matches forge + 400s. Only the wrapper figure is used below.

Modeled, with the real account:

| Part | Gas | From |
| --- | ---: | --- |
| Adapter, smallest gas, with hold-back at the verifiers | 11,564,090 | today, back-computed from the wrapper run |
| The same, through the account's 63/64 | 11,747,647 | arithmetic |
| Account's own work | 32,322 | older mock frame 82,905, minus today's adapter work 50,583. Mixed builds |
| Entry 3,000 + helper cold 400 | 3,400 | REPORT, modeled |
| **Total** | **11,783,369** | |
| **Margin** | **about 216,600** | |

So the 199,520 from earlier today holds, a little better. Most of the gain is today's phones at about 13,000 less than the Nov 2 numbers, which were gasleft deltas, so not quite the same measure. Whether it stays there depends on the account, which did not run: its share is an old number with mock proofs.

### Calldata

| | Bytes | Calldata gas |
| --- | ---: | ---: |
| Encoded bundle, `presence` | 29,632 | |
| `verifyPresence` calldata | 29,924 | 449,096 (2,474 zero bytes) |
| Plain tx through `PresenceLog`, mined | 30,052 | 449,932 |
| Design's frame 1 data | 30,052 | 462,832, DESIGN's figure |
| Most frame data ever sent | 28,000 | 446,300 |

The bundle is the real one, so the design's size assumption holds. The plain tx being 30,052 B is a coincidence of the wrapper's encoding. It is not frame data: frame data is still 28,000 B at most. DESIGN's 462,832 is not 30,052 x 16 = 480,832. Not chased.

### Deploy cost on 1337

Code is far dearer than on Osaka, about 1,570 per runtime byte all in. Likely EIP-8037 state gas, not traced. `PhoneVerifier` 27,016,685, `PairNamedVerifier` 26,342,456, libraries 12,523,529 and 9,653,543 per verifier, adapter 5,987,119, wrapper 1,200,731. Total 104,901,135. Block limit is 60,000,000. A 9,000,000 limit on the first library ran out of gas, status 0, nothing lost but devnet gas.

### What this does NOT show

- **No `ctx`.** Nothing computed `popNonce` from a context. It is a fixed old nonce read off the proofs.
- **Account layer not exercised.** No `evpVerify`, no frame tx, no sidecar, no VERIFY frame. All plain calls.
- **The deadline is an argument.** 1790000600 is long past on chain. `verifyPresence` has no clock so it passes. A real frame 0 expiry check would refuse it, so this bundle cannot go through the account as is.
- **Old audio.** From an old field walk, not a fresh session.
- **Role A is a Mac enclave key,** not a laptop chirping. `deviceA` is that key's X.
- **POPCC1 signed after the fact,** today, with the dev key. No server issued it for this session.
- **Deployed phone verifier.** Not rebuilt from today's phone source.
- **One input set.** Verifier gas on other inputs was not measured.

### Commands

From `fv/v1.1/circuit`, then `forge`:

```
bash prove_field.sh                                # field witness, pair_named. Leaves Prover.toml, out, vk alone
python3 -I sign_popcc1.py <issuer pem>             # local only
cd forge && bash run_field.sh                      # needs the adapter's contracts in the repo tree
python3 -I chain1337.py out <funded 1337 key file> # plain txs only. Printed JSON is chain1337.json
```

## Commands

From `fv/v1.1/circuit`. `oalib` comes from `research/worldid/prototypes/optA-noir/noir/oalib`.

`target/` is not kept here, nargo writes absolute paths into it. `prove.sh` makes it again.

```
bash prove.sh             # compile, bb gates, execute, write_vk, prove, verify, write_solidity_verifier
                          # bb flags: -t evm, as in contracts/zk/README.md. poc-verifier-gas ran no bb itself,
                          # it reused those verifiers.
cd forge && bash run.sh   # forge build --sizes, forge test -vv, forge test --gas-report
```
