#!/bin/bash
# Build zkprove (CLI + libzkprove.so/.a) for arm64-v8a. Artifacts stay under ~/.enconomy/zk/android.
#   1. fetch libbb-external.a (github.com/AztecProtocol/barretenberg release v5.0.0-nightly.20260522)
#   2. build zig 0.15's libc++/libc++abi for aarch64-linux-android (the bb archive is zig-built, std::__1 ABI)
#   3. cargo ndk build (API 31)
# usage: build_android.sh [extra cargo args, e.g. --features witness]
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
A=$HOME/.enconomy/zk/android; TAG=v5.0.0-nightly.20260522
export ANDROID_NDK_HOME=${ANDROID_NDK_HOME:-$HOME/Library/Android/sdk/ndk/28.2.13676358}
SYS=$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/darwin-x86_64/sysroot

L=$A/rel50/android; mkdir -p $L
[ -f $L/libbb-external.a ] || (cd $L && gh release download $TAG -R AztecProtocol/barretenberg -p barretenberg-static-arm64-android.tar.gz --clobber && tar xzf barretenberg-static-arm64-android.tar.gz)

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

cd $HERE/zkprove
ZIG_CXX_DIR=$Zc CARGO_TARGET_DIR=$A/target BB_LIB_DIR=$L cargo ndk -t arm64-v8a -P 31 build --release "$@"
ls -la $A/target/aarch64-linux-android/release/zkprove $A/target/aarch64-linux-android/release/libzkprove.*
