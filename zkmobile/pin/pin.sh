#!/bin/bash
# Reproduce the pinned laptop run: fetch bb v5.0.0-nightly.20260522 (AztecProtocol/barretenberg),
# write vk, prove+verify fixtures A/B (evm target), emit PhoneVerifier.sol. Artifacts -> ~/.enconomy/zk/pinned/
set -e
TAG=v5.0.0-nightly.20260522
O=~/.enconomy/zk/pinned; P=~/.enconomy/zk/optA/noir/phone
mkdir -p $O/rel50 $O/bin && cd $O
[ -x bin/bb ] || { gh release download $TAG -R AztecProtocol/barretenberg -D rel50 --clobber \
  -p barretenberg-arm64-darwin.tar.gz -p barretenberg-arm64-linux.tar.gz \
  -p barretenberg-static-arm64-android.tar.gz -p barretenberg-static-arm64-ios.tar.gz -p barretenberg-static-arm64-ios-sim.tar.gz
  tar -xzf rel50/barretenberg-arm64-darwin.tar.gz -C bin; }
bin/bb --version
bin/bb write_vk -b $P/target/phone.json -o vk -t evm
for r in A B; do w=$P/target/phone.gz; [ $r = B ] && w=$P/target/phoneB.gz; mkdir -p $r
  /usr/bin/time -l bin/bb prove -b $P/target/phone.json -w $w -k vk/vk -o $r -t evm 2>&1 | egrep "real|maximum resident"
  bin/bb verify -k vk/vk -p $r/proof -i $r/public_inputs -t evm; done
bin/bb write_solidity_verifier -k vk/vk -o PhoneVerifier.sol -t evm
sed -i '' 's/^contract HonkVerifier is/contract PhoneVerifier is/' PhoneVerifier.sol
