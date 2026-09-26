#!/usr/bin/env bash
# Poseidon BN254 parity: JS (poseidon-lite, circomlibjs x3, maci-crypto) = circom witness = poseidon-solidity = Python = Kotlin(BigNat)
set -euo pipefail; cd "$(dirname "$0")"
node gen.mjs | tail -1; node tree.mjs >/dev/null; node circ.cjs | tail -1; node maci.cjs
python3 poseidon_bn254.py
(cd forge && forge test -q 2>&1 | tail -1)
java -jar kt.jar
