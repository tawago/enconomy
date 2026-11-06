#!/bin/bash
# Compile both pairs, make a throwaway witness, prove, write verifiers. Run from fv/v1.1/circuit.
set -euo pipefail
nargo --version; bb --version
(cd commit_helper && nargo execute | tee out.log)
CS=($(grep -o '0x[0-9a-f]*' commit_helper/out.log)); CA=${CS[0]}; CB=${CS[1]}
[ -n "$CA" ] && [ -n "$CB" ]
for p in pair_ref:pair pair_named:pair_named; do
  d=${p%%:*}; n=${p##*:}
  cat > $d/Prover.toml <<T
nonce_hi = "0x1111"
nonce_lo = "0x2222"
attempt = "1"
commit_a = "$CA"
commit_b = "$CB"
sr_a = "48000"
sr_b = "48000"
half_a = "110"
salt_a = "0x7777"
half_b = "10"
salt_b = "0x9999"
xa = ["0x0123456789abcdef0123456789abcdef", "0x89abcdef0123456789abcdef01234567"]
xb = ["0xfedcba9876543210fedcba9876543210", "0x76543210fedcba9876543210fedcba98"]
T
  ( cd $d
    nargo compile
    bb gates -b target/$n.json
    nargo execute $n
    bb write_vk -b target/$n.json -o vk -t evm
    bb prove -b target/$n.json -w target/$n.gz -k vk/vk -o out -t evm
    bb verify -k vk/vk -p out/proof -i out/public_inputs -t evm
    bb write_solidity_verifier -k vk/vk -o Verifier.sol -t evm
    wc -c out/proof out/public_inputs
    grep -E 'NUMBER_OF_PUBLIC_INPUTS =|^uint256 constant (N|LOG_N) ' Verifier.sol )
done
