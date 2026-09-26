#!/bin/bash
# zkprove (ACVM witness + Barretenberg UltraHonk, bb v5.0.0-nightly.20260522) -> dist/android/arm64-v8a/libzkprove.so
#   1. libbb-external.a from the pinned release (~/.enconomy/zk/pinned/rel50, else gh release download)
#   2. zig 0.15's libc++/libc++abi for aarch64-linux-android (the bb archive is zig-built, std::__1 ABI)
#   3. cargo ndk build (API 31), feature "witness"
# Same recipe as zkmobile/android/build_android.sh (spike: Pixel 6, 25 s, 1.6 GB).
set -e
P=$(cd "$(dirname "$0")/.." && pwd)
A=$HOME/.enconomy/zk/android; TAG=v5.0.0-nightly.20260522
export ANDROID_NDK_HOME=${ANDROID_NDK_HOME:-$HOME/Library/Android/sdk/ndk/28.2.13676358}
SYS=$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/darwin-x86_64/sysroot

L=$A/rel50/android; mkdir -p $L
if [ ! -f $L/libbb-external.a ]; then
  T=$HOME/.enconomy/zk/pinned/rel50/barretenberg-static-arm64-android.tar.gz
  if [ -f $T ]; then tar xzf $T -C $L
  else (cd $L && gh release download $TAG -R AztecProtocol/barretenberg -p barretenberg-static-arm64-android.tar.gz --clobber && tar xzf barretenberg-static-arm64-android.tar.gz); fi
fi

Zc=$A/zigcxx; mkdir -p $Zc
if [ ! -f $Zc/libzigc++.a ]; then
  cd $Zc
  printf 'include_dir=%s\nsys_include_dir=%s\ncrt_dir=%s\nmsvc_lib_dir=\nkernel32_lib_dir=\ngcc_dir=\n' \
    $SYS/usr/include $SYS/usr/include/aarch64-linux-android $SYS/usr/lib/aarch64-linux-android/29 > libc.txt
  printf '#include <iostream>\n#include <sstream>\nint f(){std::ostringstream s; s<<1.5; std::cerr<<s.str(); return 0;}\n' > d.cpp
  ZIG_LIBC=$Zc/libc.txt ZIG_GLOBAL_CACHE_DIR=$Zc/cache ZIG_LOCAL_CACHE_DIR=$Zc/cache zig c++ -target aarch64-linux-android.29 -shared d.cpp -o d.so
  cp "$(find cache -name 'libc++.a' | head -1)" libzigc++.a
  cp "$(find cache -name 'libc++abi.a' | head -1)" libzigc++abi.a
fi

cd $P
export CARGO_TARGET_DIR=${CARGO_TARGET_DIR:-$A/target}   # shared with the spike build (deps already compiled)
ZIG_CXX_DIR=$Zc BB_LIB_DIR=$L cargo ndk -t arm64-v8a -P 31 build --release --lib --features witness
mkdir -p dist/android/arm64-v8a
cp $CARGO_TARGET_DIR/aarch64-linux-android/release/libzkprove.so dist/android/arm64-v8a/
ls -l dist/android/arm64-v8a/libzkprove.so
