#!/bin/bash
# Compile pair_named with nargo 1.0.0-beta.22 and put the json where server/pop/zk.py looks for it.
# Source paths are stripped, so the sha256 pin in zk.py holds on any machine.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
DEST=$HOME/.enconomy/zk/optA/noir/pair_named/target
cd "$ROOT/fv/v1.1/circuit/pair_named"
"${NARGO:-nargo}" compile
mkdir -p "$DEST"
python3 -I -c '
import json, sys
d = json.load(open("target/pair_named.json"))
d["file_map"] = {}   # absolute paths live here, zkprove only needs the key
json.dump(d, open(sys.argv[1], "w"), sort_keys=True, separators=(",", ":"))
' "$DEST/pair_named.json"
wc -c "$DEST/pair_named.json"
shasum -a 256 "$DEST/pair_named.json"
