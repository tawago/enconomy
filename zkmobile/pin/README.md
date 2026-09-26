# zk pin: one bb version for everything

**Pinned: bb `v5.0.0-nightly.20260522` from `AztecProtocol/barretenberg`** (not aztec-packages). See `~/.enconomy/zk/pinned/VERSION`.

- Darwin CLI sha256 `ab4ff1ab…a7330d`, byte-identical to the ZK team's `~/.enconomy/zk/bin/bb`. Same build as the team's vk, proofs, and PhoneVerifier.sol.
- The same release ships mobile libs: `barretenberg-static-arm64-{android,ios,ios-sim}.tar.gz`, in `~/.enconomy/zk/pinned/rel50/` (hashes in SHA256SUMS).
- Do not use aztec-packages `v4.4.0-nightly.20260522`. Its bb can't read nargo 1.0.0-beta.22 ACIR. On a tiny x*x==y test circuit it fails with `error converting into field Circuit::current_witness_index`, and on phone.json it dumps the whole circuit, which runs away.

## Artifacts (`~/.enconomy/zk/pinned/`)
- `bin/bb` — pinned CLI
- `vk/vk`, `vk/vk_hash` — phone circuit vk (`-t evm`), identical to the team's `optA/noir/phone/vk/vk`
- `A/`, `B/` — `proof` (10304 B) + `public_inputs` (384 B) for fixture 180ca04b_48k roles A and B
- `PhoneVerifier.sol` — `write_solidity_verifier -t evm`, with the contract renamed to PhoneVerifier. Identical to the team's forge/src copy.

## Commands
Run `./pin.sh` to redo everything. In short:
```
bb write_vk -b phone.json -o vk -t evm
bb prove    -b phone.json -w phone.gz -k vk/vk -o A -t evm
bb verify   -k vk/vk -p A/proof -i A/public_inputs -t evm
bb write_solidity_verifier -k vk/vk -o PhoneVerifier.sol -t evm
```
Inputs: `~/.enconomy/zk/optA/noir/phone/target/{phone.json,phone.gz,phoneB.gz}`.

## Laptop numbers (M-series Mac, 8 threads, load avg ~12 from other builds)
| fixture | prove wall | peak RSS | verify | EVM verify tx gas |
|---|---|---|---|---|
| A | 19.3 s | 1.13 GB | ok | 2,905,625 |
| B | 21.9 s | 1.33 GB | ok | 2,905,637 |

The team measured 8.9 s on an idle machine. The difference is load. Gas was measured on anvil with the team's `gas.sh`. A tampered public input reverts (0x9fc3a218).
