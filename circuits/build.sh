#!/bin/bash
# Build script for copresence circuit

set -e

CIRCUIT_NAME="copresence"
BUILD_DIR="build"
PTAU_FILE="powersOfTau28_hez_final_14.ptau"

# Create build directory
mkdir -p $BUILD_DIR

echo "=== Compiling circuit ==="
circom $CIRCUIT_NAME.circom --r1cs --wasm --sym -o $BUILD_DIR

echo "=== Downloading powers of tau (if not exists) ==="
if [ ! -f "$BUILD_DIR/$PTAU_FILE" ]; then
    curl -L https://hermez.s3-eu-west-1.amazonaws.com/$PTAU_FILE -o $BUILD_DIR/$PTAU_FILE
fi

echo "=== Generating proving key ==="
snarkjs groth16 setup $BUILD_DIR/$CIRCUIT_NAME.r1cs $BUILD_DIR/$PTAU_FILE $BUILD_DIR/${CIRCUIT_NAME}_0000.zkey

echo "=== Contributing to ceremony (skip for dev) ==="
snarkjs zkey contribute $BUILD_DIR/${CIRCUIT_NAME}_0000.zkey $BUILD_DIR/${CIRCUIT_NAME}_final.zkey --name="Dev contribution" -v -e="random entropy"

echo "=== Exporting verification key ==="
snarkjs zkey export verificationkey $BUILD_DIR/${CIRCUIT_NAME}_final.zkey $BUILD_DIR/verification_key.json

echo "=== Build complete ==="
echo "Circuit artifacts in: $BUILD_DIR/"
