# zk verifiers on Sepolia

UltraHonk (ZK, `-t evm`) Solidity verifiers from the pinned bb `v5.0.0-nightly.20260522`.
Addresses in `../deployments/zk-sepolia.json`.

- `src/PhoneVerifier.sol` — `~/.enconomy/zk/pinned/PhoneVerifier.sol`, same bytes as the team's forge copy. 20 public inputs, N=2^20.
- `src/PairVerifier.sol` — `bb write_solidity_verifier -k vk/vk -t evm` on `~/.enconomy/zk/optA/noir/pair`, contract renamed. Same bytes as the team's. 15 public inputs, N=2^12.
- `src/VerifyLog.sol` — calls `verify()` inside a tx and emits `Verified(verifier, keccak(proof), keccak(publicInputs), ok, gasUsed)`.
- `fixtures/{A,B,pair}` — fixture 180ca04b_48k. A/B are the pinned phone proofs; pair was re-proved with the pinned bb (public inputs and vk match the team's).

Build settings match the team's forge: solc 0.8.x, optimizer runs=1, no via-ir, evm cancun. Runtime sizes: verifiers ~17.3 KB, RelationsLib 8.0 KB, ZKTranscriptLib 6.1 KB (all under EIP-170).

## Commands
```
forge build --sizes
./deploy.sh                                   # libs + verifiers + VerifyLog
./verify.sh <verifier> <verifyLog> fixtures/A # eth_call, VerifyLog tx, tampered eth_call
```
Pair proof:
```
bb write_vk -b pair.json -o vk -t evm
bb prove -b pair.json -w pair.gz -k vk/vk -o out -t evm
bb write_solidity_verifier -k vk/vk -o Verifier.sol -t evm
```

## Gas on Sepolia
| proof | verify() execution | VerifyLog tx |
|---|---|---|
| phone A | 4,077,544 | 4,270,503 |
| phone B | 4,077,544 | 4,270,515 |
| pair | 3,318,020 | 3,456,918 |

Flipping the last public input makes `verify` revert with `0x9fc3a218`.

On a pre-Osaka anvil the phone verify tx was 2.9M. Sepolia runs Osaka now, and EIP-7883 raises MODEXP cost, which the verifier uses for field inversions. That's likely where the extra ~1.2M comes from.
Deploying everything and the 3 verify txs cost ~0.028 Sepolia ETH at ~1.1 gwei.
