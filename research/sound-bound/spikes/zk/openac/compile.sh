#!/bin/bash
# Compile one sound-bound circuit with circom 2.2.3 over secq256r1.
# Usage: ./compile.sh sb_pair_v1   (outputs build/<name>/{.r1cs,_cpp,_js})
set -e
cd "$(dirname "$0")"
ZK=$(cd .. && pwd)
POC=$ZK/vendor/zkID/wallet-unit-poc/circom
name=$1
mkdir -p build/$name build/cpp
$ZK/vendor/bin/circom circuits/main/$name.circom --prime secq256r1 --r1cs --c --wasm --O2 \
  -l $POC/circuits -l $POC/node_modules -o build/$name
cp build/$name/${name}_cpp/$name.cpp build/$name/${name}_cpp/$name.dat build/cpp/
