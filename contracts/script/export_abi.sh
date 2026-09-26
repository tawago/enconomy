#!/usr/bin/env bash
# Build and export ABIs to contracts/out-abi/ (consumed by web/ and server/).
set -euo pipefail
cd "$(dirname "$0")/.."
forge build --silent
mkdir -p out-abi
jq '.abi' out/MeetResolver.sol/MeetResolver.json > out-abi/MeetResolver.json
echo "wrote out-abi/MeetResolver.json"
