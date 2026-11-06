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

## Frame 1 budget against 12,000,000

| Part | Gas | When |
| --- | ---: | --- |
| Phone A + phone B (about 4.07M x2), gasleft delta | 4,083,276 + 4,069,887 | Nov 2, forge 1.4.3, old circuit, `research/ethglobal-mumbai/poc-verifier-gas/README.md` |
| pair_named, gasleft delta | 3,325,048 | today |
| Adapter and account with mock proofs | 82,905 | `research/ethglobal-mumbai/evp-recovery/REPORT.md`, older, forge 1.4.3 |
| Entry 3,000 + 4 cold accounts at 400 (helper, adapter, two verifiers) | 4,600 | same REPORT, modeled |
| **Plain sum** | **11,565,716** | 434,284 left |

The plain sum flatters us. EIP-150 holds back 1/64 at each call. REPORT's forwarded test, with burn mocks at the 12M limit, fits a pair of up to 3,524,568. Against that, real margin is **3,524,568 - 3,325,048 = 199,520**.

So it fits on the Nov 2 phone numbers. Not checked: the phone circuit as it stands now, and the real proof through the adapter (later step).

## Commands

From `fv/v1.1/circuit`. `oalib` comes from `research/worldid/prototypes/optA-noir/noir/oalib`.

`target/` is not kept here, nargo writes absolute paths into it. `prove.sh` makes it again.

```
bash prove.sh             # compile, bb gates, execute, write_vk, prove, verify, write_solidity_verifier
                          # bb flags: -t evm, as in contracts/zk/README.md. poc-verifier-gas ran no bb itself,
                          # it reused those verifiers.
cd forge && bash run.sh   # forge build --sizes, forge test -vv, forge test --gas-report
```
