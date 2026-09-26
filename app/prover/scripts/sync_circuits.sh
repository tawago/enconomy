#!/bin/bash
# Copy the compiled circom C++ witness generators (oa2t_s48, oa2t_s44) from the spike into ./cpp.
# The spike is the source of truth; cpp/ is gitignored (~25 MB). Re-run after a circuit recompile,
# together with a new trusted setup (pk/vk must come from the same r1cs).
set -e
P=$(cd "$(dirname "$0")/.." && pwd)
SRC=${POP_CIRCUITS_CPP:-$P/../../research/sound-bound/spikes/zk/optionA-v2/build/cpp}
mkdir -p "$P/cpp"
for c in oa2t_s48 oa2t_s44; do
  for e in cpp dat; do
    [ -f "$SRC/$c.$e" ] || { echo "missing $SRC/$c.$e" >&2; exit 1; }
    cmp -s "$SRC/$c.$e" "$P/cpp/$c.$e" || cp "$SRC/$c.$e" "$P/cpp/$c.$e"
  done
done
shasum -a 256 "$P"/cpp/*
