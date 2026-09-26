#!/bin/bash
# witnesscalc (zkmopro fork) builds GMP 6.2.1 for the host. On Apple Silicon its arm64 assembly
# uses register x18, which Darwin reserves -> random segfaults in __gmpn_* (seen here in
# mpz_gcdext during Fr_inv, ~25% of witness runs). GMP 6.3.0 fixed this. Swap in Homebrew's
# GMP 6.3.0 static lib + header, then force the witnesscalc libs to relink.
set -e
Z=$(cd "$(dirname "$0")/.." && pwd)
for w in $Z/vendor/target/release/build/*/out/witnesscalc; do
  pkg=$w/depends/gmp/package
  [ -d "$pkg" ] || continue
  cp /opt/homebrew/lib/libgmp.a $pkg/lib/libgmp.a
  cp /opt/homebrew/include/gmp.h $pkg/include/gmp.h
  rm -rf $w/build_witnesscalc $w/package
  echo "patched $pkg -> $(grep -o 'VERSION_MINOR *[0-9]*' $pkg/include/gmp.h)"
done
touch $Z/openac/build/cpp $Z/vendor/zkID/wallet-unit-poc/circom/build/cpp
