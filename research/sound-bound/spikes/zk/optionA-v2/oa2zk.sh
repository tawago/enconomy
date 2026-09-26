#!/bin/bash
# Run the oa2zk prover with the witnesscalc dylibs on the loader path.
Z=$(cd "$(dirname "$0")" && pwd)
lib=$(ls -d $Z/../vendor/target/release/build/oa2zk-*/out/witnesscalc/package/lib | head -1)
DYLD_LIBRARY_PATH=$lib exec $Z/../vendor/target/release/oa2zk "$@"
