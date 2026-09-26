#!/bin/bash
# Same fix as ../openac/fix_gmp.sh (GMP 6.2.1 uses x18 on Apple arm64 -> random segfaults), for this crate.
set -e
Z=$(cd "$(dirname "$0")" && pwd)
for w in $Z/../vendor/target/release/build/oa2zk-*/out/witnesscalc; do
  pkg=$w/depends/gmp/package
  [ -d "$pkg" ] || continue
  cp /opt/homebrew/lib/libgmp.a $pkg/lib/libgmp.a
  cp /opt/homebrew/include/gmp.h $pkg/include/gmp.h
  rm -rf $w/build_witnesscalc $w/package
  echo "patched $pkg"
done
touch $Z/build/cpp
