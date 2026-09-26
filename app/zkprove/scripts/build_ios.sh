#!/bin/bash
# zkprove static lib for iOS (device + simulator), linked against the pinned bb v5.0.0-nightly.20260522
# libbb-external.a -> dist/ios/ZkProve.xcframework. The app links it with -lc++ (cinterop zkprove.def).
set -e
P=$(cd "$(dirname "$0")/.." && pwd)
R=$HOME/.enconomy/zk/pinned/rel50; D=$HOME/.enconomy/zk/ios/pinned
export IPHONEOS_DEPLOYMENT_TARGET=${IPHONEOS_DEPLOYMENT_TARGET:-16.0}
cd $P
rm -rf dist/ios && mkdir -p dist/ios/headers
cp include/zkprove.h include/module.modulemap dist/ios/headers/
args=()
for s in ios ios-sim; do
  L=$D/$s; mkdir -p $L
  [ -f $L/libbb-external.a ] || tar xzf $R/barretenberg-static-arm64-$s.tar.gz -C $L
  [ -f $L/libbb-external.a ] || L=$(dirname "$(find $D/$s -name libbb-external.a | head -1)")
  t=aarch64-apple-$s
  BB_LIB_DIR=$L cargo rustc --release --lib --crate-type staticlib --target $t --features witness
  args+=(-library target/$t/release/libzkprove.a -headers dist/ios/headers)
done
xcodebuild -create-xcframework "${args[@]}" -output dist/ios/ZkProve.xcframework
ls -l target/aarch64-apple-ios/release/libzkprove.a target/aarch64-apple-ios-sim/release/libzkprove.a
