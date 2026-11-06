#!/bin/bash
# Run from fv/v1.1/circuit/forge. Needs research/ethglobal-mumbai/evp-recovery/contracts beside it in the repo.
set -euo pipefail
forge --version
forge build --sizes
forge test --match-contract FieldPresence -vv
PRESENCE_NO_SEARCH=true forge test --match-test test_field_bundle_accepted -vvvv
