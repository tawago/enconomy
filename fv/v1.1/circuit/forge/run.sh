#!/bin/bash
# Run from fv/v1.1/circuit/forge. Needs network once, forge fetches solc 0.8.30.
set -euo pipefail
forge --version
forge build --sizes
forge test -vv
forge test --gas-report --match-test 'real_proof'
python3 -I - <<'P'
import json,glob
for f in sorted(glob.glob('out/Pair*Verifier.sol/*.json')):
    d=json.load(open(f))
    n=len(d['deployedBytecode']['object'].removeprefix('0x'))//2
    if n: print(f, n)
P
