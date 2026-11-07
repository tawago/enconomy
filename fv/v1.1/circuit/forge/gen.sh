#!/bin/bash
# Verifiers and throwaway fixtures for forge, from the output of ../prove.sh. Run from fv/v1.1/circuit/forge.
set -euo pipefail
sed 's/^contract HonkVerifier /contract PairNamedVerifier /' ../pair_named/Verifier.sol > src/PairNamedVerifier.sol
sed 's/^contract HonkVerifier /contract PairRefVerifier /' ../pair_ref/Verifier.sol > src/PairRefVerifier.sol
cp ../../../../contracts/zk/src/PhoneVerifier.sol src/PhoneVerifier.sol
mkdir -p fixtures/named fixtures/ref
cp ../pair_named/out/proof ../pair_named/out/public_inputs fixtures/named/
cp ../pair_ref/out/proof ../pair_ref/out/public_inputs fixtures/ref/
