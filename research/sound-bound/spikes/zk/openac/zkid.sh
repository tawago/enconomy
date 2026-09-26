#!/bin/bash
# Run the vendored zkID ecdsa-spartan2 CLI from its crate dir with witnesscalc dylibs on the loader path.
Z=$(cd "$(dirname "$0")/.." && pwd)
lib=$(ls -d $Z/vendor/target/release/build/ecdsa-spartan2-*/out/witnesscalc/package/lib | head -1)
cd $Z/vendor/zkID/wallet-unit-poc/ecdsa-spartan2
DYLD_LIBRARY_PATH=$lib exec $Z/vendor/target/release/ecdsa-spartan2 "$@"
