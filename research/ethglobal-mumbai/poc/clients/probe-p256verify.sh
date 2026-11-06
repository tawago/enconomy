#!/bin/sh
# Read-only: eth_call the EIP-7951 P256VERIFY precompile (0x100) with a valid vector
# (first "expected 1" case in go-ethereum core/vm/testdata/precompiles/p256Verify.json).
# Prints ...01 when the precompile exists and the signature verifies.
V=$(cat "$(dirname "$0")/p256verify-vector.hex")
for u in "$@"; do
  printf '{"jsonrpc":"2.0","id":1,"method":"eth_call","params":[{"to":"0x0000000000000000000000000000000000000100","data":"0x%s"},"latest"]}' "$V" |
    curl -s -m 25 -X POST -H 'content-type: application/json' --data @- "$u"; echo "  <- $u"
done
