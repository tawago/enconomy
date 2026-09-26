#!/bin/bash
# aarch64-linux-android -> dist/android/arm64-v8a/libpop_prover.so (JNI + C ABI; libc++ linked statically).
# Heavy (GMP + two 2 MB circuit .cpp): run through research/sound-bound/spikes/zk/tools/heavy.sh.
set -e
P=$(cd "$(dirname "$0")/.." && pwd)
export ANDROID_NDK=${ANDROID_NDK:-$HOME/Library/Android/sdk/ndk/28.2.13676358}
export ANDROID_NDK_HOME=$ANDROID_NDK
API=${POP_ANDROID_API:-24}
cd "$P"
[ -f cpp/oa2t_s48.cpp ] || scripts/sync_circuits.sh
cargo ndk -t arm64-v8a -P "$API" rustc --release --lib --crate-type cdylib
mkdir -p dist/android/arm64-v8a
cp target/aarch64-linux-android/release/libpop_prover.so dist/android/arm64-v8a/
"$ANDROID_NDK"/toolchains/llvm/prebuilt/darwin-x86_64/bin/llvm-readelf -d dist/android/arm64-v8a/libpop_prover.so | grep NEEDED
ls -l dist/android/arm64-v8a/libpop_prover.so
