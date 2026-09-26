#!/bin/bash
# Run the sbzk prover with the witnesscalc dylibs on the loader path (cargo run does this implicitly).
Z=$(cd "$(dirname "$0")/.." && pwd)
lib=$(ls -d $Z/vendor/target/release/build/sbzk-*/out/witnesscalc/package/lib | head -1)
DYLD_LIBRARY_PATH=$lib exec $Z/vendor/target/release/sbzk "$@"
