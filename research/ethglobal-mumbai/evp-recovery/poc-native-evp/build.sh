#!/bin/sh
# regenerate + compile the pure-Yul SHA-256 hasher. Writes build/sha256.<opt|noopt>.bin (init code hex).
set -e
cd "$(dirname "$0")"
S="$HOME/Library/Application Support/svm/0.8.30/solc-0.8.30"
python3 gen_sha.py
mkdir -p build
"$S" --strict-assembly --evm-version osaka --bin yul/sha256.yul | grep -A1 Binary | tail -1 | tr -d '\n' > build/sha256.noopt.bin
if [ "$1" = opt ]; then  # slow: the unrolled rounds take the Yul optimizer many minutes
  "$S" --strict-assembly --evm-version osaka --optimize --bin yul/sha256.yul | grep -A1 Binary | tail -1 | tr -d '\n' > build/sha256.opt.bin
fi
