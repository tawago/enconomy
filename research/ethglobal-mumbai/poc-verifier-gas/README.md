# poc-verifier-gas: how much gas does proof verification cost?

Date: 2026-11-02. Fork rules: Osaka unless noted. Tool: forge 1.4.3, solc 0.8.30.

## Bottom line

- Nothing pairing-based fits the 100k public-mempool verify budget. The BN254 pairing precompile alone costs 113k for 2 pairs and 181k for the 4 pairs Groth16 needs.
- Groth16 fits 250k up to about 8 public inputs.
- Our UltraHonk verifiers cost 3.3M to 4.1M gas each on Osaka. That is 13x to 16x over 250k and 3x to 4x over 1M. The 3-proof bundle costs 11.5M.
- About half of the UltraHonk cost is MODEXP field inversions. Osaka's EIP-7883 tripled their price. On Prague rules the same verifies cost 2.2M to 2.7M.
- P-256 (EIP-7951) costs 6,900 gas. It is the only primitive here that fits easily inside 100k.

## Table

"Verify gas" means execution gas inside the verifier call. It excludes the 21k tx base cost and calldata. The fit columns compare against that number only.

| Proof system | Verify gas | Fits 100k | Fits 250k | Fits 1M | Source |
| --- | ---: | :---: | :---: | :---: | --- |
| P-256 ECDSA, P256VERIFY precompile (EIP-7951) | 6,900 (precompile). 7,355 measured with call overhead | yes | yes | yes | measured, `test_p256_precompile` |
| P-256 inside EIP-8141 `signature_gas` | 6,700 | yes | yes | yes | EIP-8141 spec |
| Groth16 BN254, 1 public input | 188,905 | no | yes | yes | measured, `Groth16N1` |
| Groth16 BN254, 2 inputs | 195,582 | no | yes | yes | measured |
| Groth16 BN254, 4 inputs | 208,893 | no | yes | yes | measured |
| Groth16 BN254, 8 inputs | 235,350 | no | yes | yes | measured |
| Groth16 BN254, 16 inputs | 288,430 | no | no | yes | measured |
| Groth16 BN254, 32 inputs | 394,590 | no | no | yes | measured |
| Semaphore v4 `validateProof` (Groth16 with 4 inputs plus nullifier write; whole tx) | 285,577 to 290,087 | no | no | yes | Semaphore docs gas report |
| Semaphore v4 verifier only (4 public inputs) | about 209k (our Groth16 n=4 result, used as a proxy) | no | yes | yes | UNREACHABLE: their docs give no verifier-only number. 209k is our own n=4 measurement |
| UltraHonk (bb 5.0.0-nightly), pair circuit, 2^12 gates, 15 PI | 3,313,313 | no | no | no | measured, enconomy `PairVerifier` |
| UltraHonk, phone circuit, 2^20 gates, 20 PI | 4,072,116 | no | no | no | measured, enconomy `PhoneVerifier` |
| UltraHonk, 3-proof bundle (A + B + pair) | 11,473,237 | no | no | no | measured, `test_real_verifiers_each` |
| Same UltraHonk verifiers, Prague rules (before EIP-7883) | 2.23M / 2.72M / 2.73M | no | no | no | measured with `--evm-version prague` |

Thresholds: the 100k comes from EIP-8141 `MAX_VERIFY_GAS`. 250k and 1M are the reference points the task asked for. Alt-mempool limits are covered in the recap and are not checked here.

## What was run

### 1. enconomy contracts (existing tests, unchanged)

The repo's `contracts/lib` submodules are empty. To avoid touching anything outside this folder, I copied `contracts/` to the session scratchpad. Then I cloned forge-std v1.11.0 (8e40513d) and safe-smart-account v1.5.0 (dc437e8f), the same revisions `foundry.lock` pins. Then I ran:

```
forge test --offline -vv --gas-report       # 38 passed, 1 skipped (fork test)
forge test --offline --evm-version prague --match-test test_real_verifiers_each -vv
```

Those library repos were only compiled and executed inside the forge EVM. I ran none of their scripts.

Results from `test/NoirRealGas.t.sol`, Osaka:

- PhoneVerifier A: 4,083,276 gas. PhoneVerifier B: 4,069,887 gas. PairVerifier: 3,320,074 gas. Sum: 11,473,237 gas. These are gasleft deltas, which include call overhead. The gas report gives `verify` at 4,072,116 (phone) and 3,313,313 (pair).
- Whole Safe spend through the guard with 3 real proofs: 11,947,942 execution gas, and an estimated 12,419,370 tx gas including calldata. That fits the EIP-7825 per-tx cap of 16,777,216.
- Proof sizes: 10,304 B (phone), 7,232 B (pair). Signatures blob: 29,898 B.
- Runtime bytecode: 17,337 B (phone), 16,901 B (pair).

The same test on Prague rules: 2,730,777 / 2,717,388 / 2,226,679 gas, sum 7,674,844.

Where the gas goes, from precompile calls traced with `-vvvv` across all 3 verifies (`results/ultrahonk-precompile-breakdown.txt`):

| Precompile | Calls | Osaka gas | Prague gas |
| --- | ---: | ---: | ---: |
| modexp (0x05) | 1,410 | 5,697,036 | 1,898,643 |
| ecMul (0x07) | 178 | 1,068,000 | 1,068,000 |
| ecPairing (0x08) | 3 | 339,000 | 339,000 |
| ecAdd (0x06) | 178 | 26,700 | 26,700 |

The modexp difference is 3,798,393 gas. The total difference is 11,473,237 minus 7,674,844, which is 3,798,393. They match exactly. So EIP-7883 explains the whole Osaka increase. The bb verifier makes about 470 single-element modexp inversions per proof, at about 4,040 gas each on Osaka.

Idea, not tested: a verifier that batch-inverts with Montgomery's trick (one modexp plus 3 mulmods per element) would remove most of the 5.7M. It would still need about 1.5M or more for ecMul and pairing across the 3 proofs, so it would still be far over 1M.

Note: the existing `test_noir_gas_budget_mock` burns 2x2.73M plus 2.23M. Those are Prague-era numbers. The real Osaka cost is about 3.8M higher.

Also: the pair circuit has 2^12 gates and the phone circuit has 2^20, yet the verify costs differ by only 0.76M. UltraHonk verify cost depends only weakly on circuit size.

### 2. Groth16 BN254 (this folder)

- `gen/gen_groth16.py` writes `src/Groth16N{1,2,4,8,16,32}.sol`. Each one follows the shape of the snarkjs verifier template, with the VK in constants, plus `test/Groth16Fixtures.sol`.
- No circuit is used. The VK and proof are a synthetic but valid instance of the Groth16 equation. B, beta, gamma and delta are the G2 generator. Every G1 point is a known multiple of G1, with A = (alpha + vk_x + c)·G1. Precompile prices depend only on input length and pair count, so the gas matches a real proof with the same number of public inputs. That is the assumption; the identical pairing cost of 181,579 in `test_bn254_pairing_raw` (k=4) supports it.
- Every proof verifies (`require(ok)`). A wrong-but-valid C point returns false.
- Run: `cd poc-verifier-gas && forge test --offline -vv --gas-report`. Results are in `results/poc-gas-report-osaka.txt`.
- Formula fit: about 182k + 6.6k per public input. That is a 4-pair pairing (45,000 + 4 x 34,000 = 181,000) plus ecMul (6,000) and ecAdd (150) per input, plus memory and calldata handling.
- Raw pairing call costs: k=2: 113,494; k=3: 147,534; k=4: 181,579.

Pitfall worth knowing for a VERIFY frame: if a proof point is off the curve, the pairing precompile fails and consumes all the gas forwarded to it (`staticcall(gas(), 8, ...)`). With a 1M cap, an off-curve C used 987,549 gas (`test_groth16_offcurve_burns_forwarded_gas`, `-vv` run). A raw off-curve pairing call or ecMul call eats its whole 500k cap on both Osaka and Prague (`test/Fail.t.sol`). Forward a bounded gas amount, or check the points are on the curve first. Odd detail: in the `--gas-report` run the same test logged only 2,716 gas. I did not chase this; trust the plain `-vv` number.

### 3. P-256

- Measured 7,355 gas for a staticcall to 0x100 with a valid public test vector, copied from `contracts/test/PopCtx.t.sol`. The precompile itself is 6,900 gas.
- On Prague rules the same call fails, because there is no precompile at 0x100 before Osaka (`results/poc-tests-prague.txt`).

## Claims checked against sources

- VERIFIED: P256VERIFY is at 0x100 and costs 6,900 gas. Status Final. https://eips.ethereum.org/EIPS/eip-7951 ("a gas cost of `6900` gas"). The spec also notes RIP-7212 used 3,450 gas.
- VERIFIED: EIP-8141 sets the public-mempool `MAX_VERIFY_GAS = 100_000` and `MAX_VERIFY_STATE_GAS = 500_000`. It prices P256 at 6,700 gas in `signature_gas`. https://eips.ethereum.org/EIPS/eip-8141 . I read only the first 100k characters of the page.
- VERIFIED: BN254 costs are ECADD 150, ECMUL 6,000, and pairing 34,000·k + 45,000. https://eips.ethereum.org/EIPS/eip-1108 . The measured k=4 cost of 181,579 is consistent.
- VERIFIED: EIP-7883 raises the MODEXP minimum from 200 to 500 and "triples the general cost by removing the division by 3". Status Final. https://eips.ethereum.org/EIPS/eip-7883 . The EIP page does not name a fork. What I observed: forge's `osaka` ruleset applies the new formula, and measured modexp gas went up 3.0x versus `prague` (1,898,643 to 5,697,036).
- VERIFIED: Semaphore v4 `validateProof` costs 285,577 min, 290,087 max, 288,798 average. Source: the gas-report image on https://docs.semaphore.pse.dev/benchmarks (`/assets/images/semaphore-v4-contracts-benchmarks-6cdd95e0eff3900dbf026165b28d50cb.png`). The report is from hardhat-gas-reporter, so the numbers are tx gas including the 21k base and the nullifier SSTORE. A HashCloak report gives 285,622 (10 members) and 285,598 (30 members): https://hashcloak.github.io/semaphore-noir-final-report/benchmarks.html . The same report puts SemaphoreNoir (UltraHonk) `validateProof` at about 2.0M to 2.1M. UNREACHABLE: I did not open it to confirm, or to check whether it was measured before Osaka.
- VERIFIED: EIP-7904 (Glamsterdam general repricing, Last Call) changes no precompile prices: "No opcode or precompile gas cost is modified." Its measurements suggest P256VERIFY (6,900 vs 3,814 measured) and pairing are overpriced, so a future repricing could lower them. https://eips.ethereum.org/EIPS/eip-7904
- UNREACHABLE (not checked): the alt-mempool (ERC-8421) verification gas cap. Whether it is about 1M, 3M or 16M decides whether the existing UltraHonk bundle can be used at all, or needs a Groth16 wrap.
- UNREACHABLE: whether calldata cost counts toward the 100k verify budget in EIP-8141. I did not find it in the part of the spec I read. A 10 KB UltraHonk proof costs roughly 165k to 412k in calldata alone, depending on whether the EIP-7623 floor applies.

## What this means for Mumbai (alt-mempool prize)

- "Verification budget above 100k" holds for every ZK option. Even the cheapest Groth16 needs about 189k. So any ZK-gated VERIFY frame belongs in the alt mempool by construction, which is what the prize asks for.
- If the alt mempool's budget is a few hundred k, use Groth16 with 8 or fewer public inputs (or Semaphore v4). Our current UltraHonk bundle (11.5M) will not pass any realistic mempool verify cap.
- A cheap public-mempool path: P-256 signatures from the phones (6.9k each) in the VERIFY frame, with the ZK proof checked later in an execution frame or off-chain. That splits "admission" from "proof".
- To keep Noir: pay 3M+ per proof on Osaka, or use a different backend or wrapper that produces a Groth16-sized final proof. That route is not measured here.

## Files

- `gen/gen_groth16.py`: generator (Python standard library only, run with `python3 -I`)
- `src/Groth16N*.sol`: generated verifiers
- `test/Gas.t.sol`, `test/Fail.t.sol`, `test/Groth16Fixtures.sol`: tests, no forge-std
- `results/`: raw logs (enconomy tests on Osaka, UltraHonk on Prague, PoC gas report, precompile breakdown)
