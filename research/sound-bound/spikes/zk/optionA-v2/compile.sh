#!/bin/bash
# Compile one optionA-v2 circuit with circom 2.2.3 over secq256r1 (outputs build/<name>/{.r1cs,_cpp,_js}).
# Usage: ./compile.sh <name> [--no-c]    (source: circuits/main/<name>.circom)
set -e
cd "$(dirname "$0")"
ZK=$(cd .. && pwd)
POC=$ZK/vendor/zkID/wallet-unit-poc/circom
name=$1
flags="--r1cs --wasm --c"
[ "$2" == "--no-c" ] && flags="--r1cs --wasm"
mkdir -p build/$name build/cpp
$ZK/vendor/bin/circom circuits/main/$name.circom --prime secq256r1 $flags --O2 \
  -l circuits -l $ZK/openac/circuits -l $POC/circuits -l $POC/node_modules -o build/$name
if [ -d build/$name/${name}_cpp ]; then
  cp build/$name/${name}_cpp/$name.cpp build/$name/${name}_cpp/$name.dat build/cpp/
fi
