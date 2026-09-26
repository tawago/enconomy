#!/usr/bin/env bash
# CI gate. Proves: committed circom == zkey circuit, zkey from PSE ppot, vkey == zkey, wasm+zkey make proofs
# the committed TransferVerifier.sol accepts, and bad inputs are UNSAT.
set -euo pipefail
cd "$(dirname "$0")"
Z=../zk/presence_transfer; B=build; SJ="node node_modules/snarkjs/cli.js"; mkdir -p $B
if [ "${1:-}" = "--write-fixture" ]; then (cd $Z && shasum -a 256 presenceTransfer.zkey presenceTransfer.wasm vkey.json beacon.txt ../../contracts/src/TransferVerifier.sol ../../circuits/src/*.circom > MANIFEST.sha256); fi
(cd $Z && shasum -a 256 -c MANIFEST.sha256)
circom src/presenceTransfer.circom --r1cs --O2 -l node_modules -o $B >/dev/null
$SJ zkey verify $B/presenceTransfer.r1cs $B/ppot_0080_14.ptau $Z/presenceTransfer.zkey | grep -q "ZKey Ok" || { echo "FAIL zkey/circuit/ptau"; exit 1; }
$SJ zkey export verificationkey $Z/presenceTransfer.zkey $B/vk.json >/dev/null
cmp -s $B/vk.json $Z/vkey.json || { echo "FAIL vkey != zkey"; exit 1; }
node -e '
const {wtns}=require("snarkjs");(async()=>{for(const f of ["tin_over","tin_wrongpayee"]){try{await wtns.calculate(require("./fixtures/"+f+".json"),process.argv[1],{type:"mem"});console.log("FAIL",f,"SAT");process.exit(1)}catch(e){console.log("ok",f,"UNSAT")}}process.exit(0)})()' $Z/presenceTransfer.wasm
$SJ wtns calculate $Z/presenceTransfer.wasm fixtures/tin.json $B/tin.wtns
$SJ groth16 prove $Z/presenceTransfer.zkey $B/tin.wtns $B/proof.json $B/public.json
$SJ groth16 verify $Z/vkey.json $B/public.json $B/proof.json | grep -q OK || { echo "FAIL proof"; exit 1; }
node -e '
const p=require("./build/proof.json"),s=require("./build/public.json"),h=x=>"0x"+BigInt(x).toString(16).padStart(64,"0");
require("fs").writeFileSync("../contracts/test/fixture.json",JSON.stringify({a:[h(p.pi_a[0]),h(p.pi_a[1])],b:[[h(p.pi_b[0][1]),h(p.pi_b[0][0])],[h(p.pi_b[1][1]),h(p.pi_b[1][0])]],c:[h(p.pi_c[0]),h(p.pi_c[1])],pub:s.map(h),ic0x:h(require(process.argv[1]).IC[0][0]),ic0y:h(require(process.argv[1]).IC[0][1])}))' $PWD/$Z/vkey.json
(cd ../contracts && forge test -q --match-contract TransferVerifierPin)
echo "ALL CHECKS PASSED"
