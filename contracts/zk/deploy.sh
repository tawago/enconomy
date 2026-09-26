#!/bin/bash
# Deploy RelationsLib + ZKTranscriptLib (per verifier), PhoneVerifier, PairVerifier, VerifyLog to Sepolia.
# usage: RPC=... KEY_FILE=~/.enconomy/ens-sepolia.key ./deploy.sh   -> prints NAME=address lines
set -e
cd "$(dirname "$0")"
RPC=${RPC:-https://ethereum-sepolia-rpc.publicnode.com}; KEY_FILE=${KEY_FILE:-$HOME/.enconomy/ens-sepolia.key}
dep(){ for i in 1 2 3 4; do
  out=$(forge create --broadcast --rpc-url $RPC --private-key "$(cat $KEY_FILE)" "$@" 2>&1) && { echo "$out" | awk '/Deployed to/{a=$3}/Transaction hash/{t=$3}END{print a, t}'; return; }
  echo "retry: $(echo "$out" | tail -1)" >&2; sleep 4; done; exit 1; }
for V in PhoneVerifier PairVerifier; do
  L=""
  for lib in RelationsLib ZKTranscriptLib; do
    read a t < <(dep src/$V.sol:$lib); echo "${V}_$lib=$a tx=$t"; L="$L --libraries src/$V.sol:$lib:$a"
  done
  read a t < <(dep $L src/$V.sol:$V); echo "$V=$a tx=$t"
done
read a t < <(dep src/VerifyLog.sol:VerifyLog); echo "VerifyLog=$a tx=$t"
