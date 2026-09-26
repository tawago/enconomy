#!/bin/bash
# aarch64-apple-ios + aarch64-apple-ios-sim static libs -> dist/ios/PopProver.xcframework (+ header, modulemap).
# Link the app with libc++ (-lc++). Heavy: run through research/sound-bound/spikes/zk/tools/heavy.sh.
set -e
P=$(cd "$(dirname "$0")/.." && pwd)
cd "$P"
[ -f cpp/oa2t_s48.cpp ] || scripts/sync_circuits.sh
# build.rs keeps this away from GMP's configure (it would retarget the host clang used for build tools).
export IPHONEOS_DEPLOYMENT_TARGET=${IPHONEOS_DEPLOYMENT_TARGET:-16.0}
for t in aarch64-apple-ios aarch64-apple-ios-sim; do
  cargo rustc --release --lib --crate-type staticlib --target $t
done
rm -rf dist/ios && mkdir -p dist/ios/headers
cp include/pop_prover.h include/module.modulemap dist/ios/headers/
xcodebuild -create-xcframework \
  -library target/aarch64-apple-ios/release/libpop_prover.a -headers dist/ios/headers \
  -library target/aarch64-apple-ios-sim/release/libpop_prover.a -headers dist/ios/headers \
  -output dist/ios/PopProver.xcframework
ls -l target/aarch64-apple-ios/release/libpop_prover.a target/aarch64-apple-ios-sim/release/libpop_prover.a
du -sh dist/ios/PopProver.xcframework
