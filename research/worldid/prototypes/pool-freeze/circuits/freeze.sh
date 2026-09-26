#!/usr/bin/env bash
# ONE-SHOT. Creates the canonical PresenceTransfer Groth16 keys. Refuses to run if zk/ already holds a zkey.
set -euo pipefail
cd "$(dirname "$0")"
Z=../zk/presence_transfer; B=build; SJ="node node_modules/snarkjs/cli.js"
PTAU_URL=https://pse-trusted-setup-ppot.s3.eu-central-1.amazonaws.com/pot28_0080/ppot_0080_14.ptau
PTAU_SHA=3ca1149e9349b22b0ee0649399cfb787677129b7b1189d1899fc0d615d9583db
[ -e $Z/presenceTransfer.zkey ] && { echo "refusing: $Z/presenceTransfer.zkey exists (it is canonical)"; exit 1; }
[ "$(circom --version)" = "circom compiler 2.1.8" ] || { echo "need circom 2.1.8"; exit 1; }
mkdir -p $B $Z
[ -f $B/ppot_0080_14.ptau ] || curl -L -o $B/ppot_0080_14.ptau $PTAU_URL
echo "$PTAU_SHA  $B/ppot_0080_14.ptau" | shasum -a 256 -c
circom src/presenceTransfer.circom --r1cs --wasm --O2 -l node_modules -o $B
$SJ groth16 setup $B/presenceTransfer.r1cs $B/ppot_0080_14.ptau $B/t0.zkey
$SJ zkey contribute $B/t0.zkey $B/t1.zkey -n="enconomy-1" -e="$(head -c 64 /dev/urandom | xxd -p -c 256)"
BEACON=${BEACON:?set BEACON to a public 32-byte hex, e.g. a World Chain block hash, no 0x}
$SJ zkey beacon $B/t1.zkey $Z/presenceTransfer.zkey "$BEACON" 10 -n="beacon"
rm -f $B/t0.zkey $B/t1.zkey    # toxic-waste-adjacent intermediates; the entropy itself was never written
cp $B/presenceTransfer_js/presenceTransfer.wasm $Z/
$SJ zkey export verificationkey $Z/presenceTransfer.zkey $Z/vkey.json
$SJ zkey export solidityverifier $Z/presenceTransfer.zkey ../contracts/src/TransferVerifier.sol
sed -i.bak -e 's/contract Groth16Verifier/contract TransferVerifier/' -e 's/pragma solidity >=0.7.0 <0.9.0;/pragma solidity 0.8.28;/' ../contracts/src/TransferVerifier.sol && rm ../contracts/src/TransferVerifier.sol.bak
echo "$BEACON" > $Z/beacon.txt
./check.sh --write-fixture
