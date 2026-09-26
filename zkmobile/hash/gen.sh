#!/usr/bin/env bash
# Reference vectors from the Noir oalib (nargo 1.0.0-beta.22). Workspace + outputs under ~/.enconomy/zk/hash/.
#   OALIB=path/to/optA-noir/noir/oalib (default: the ZK team build copy)   NARGO=... (default ~/.enconomy/zk/bin/nargo)
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
NARGO=${NARGO:-$HOME/.enconomy/zk/bin/nargo}
OALIB=${OALIB:-$HOME/.enconomy/zk/optA/noir/oalib}
ws=$HOME/.enconomy/zk/hash/noirws
mkdir -p "$ws"
rm -rf "$ws/vec" "$ws/oalib"
cp -r "$OALIB" "$ws/oalib"
cp -r "$here/vec" "$ws/vec"
(cd "$ws/vec" && "$NARGO" execute) > "$ws/vec_out.txt"
python3 "$here/gen_vectors.py" "$ws/vec_out.txt" "$here/vectors.json"
# real fixture: the team's helper over its Prover.toml (a 180ca04b_48k capture)
if [ -f "$ws/helper/Prover.toml" ]; then
  [ -f "$ws/helper_out.txt" ] || (cd "$ws/helper" && "$NARGO" execute) > "$ws/helper_out.txt"
  python3 "$here/check_fixture.py" "$ws/helper/Prover.toml" "$ws/helper_out.txt" \
    "$HOME/.enconomy/zk/optA/noir/prep_180ca04b_48k_A.json" --dump "$here/fixture_vectors.json"
fi
