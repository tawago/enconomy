#!/bin/bash
# Web build of this example's app (Kotlin/Wasm, composeApp wasmJs target), copied to web-dist/. Never run so far.
#
# The app talks to the origin that serves it for the core, so the core serves it: POP_WEB_DIR=<this web-dist>.
# POP_SERVER_URL is the fallback when the page isn't served over http(s), POP_WORLD_ID_URL is this example's backend.
# The backend must accept that origin, it has no CORS setting yet (see ../README.md). Nothing is deployed here.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"     # examples/world-id/app/
repo="$(cd "$here/../../.." && pwd)"
url="${POP_SERVER_URL:-https://pop.enconomy.dev}"
dest="$here/web-dist"

heavy="$repo/research/sound-bound/spikes/zk/tools/heavy.sh"
run=(./gradlew :composeApp:wasmJsBrowserDistribution "-Ppop.serverUrl=$url" "-Ppop.webSameOrigin=true")
cd "$here"
if [ -x "$heavy" ]; then "$heavy" pop-web "${run[@]}"; else "${run[@]}"; fi

out="$here/composeApp/build/dist/wasmJs/productionExecutable"
mkdir -p "$dest"
rsync -a --delete --exclude '*.map' "$out/" "$dest/"
echo "web app (same origin as /app/) -> $dest"
