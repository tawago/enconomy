#!/bin/bash
# Web build of the Safe example's app (Kotlin/Wasm, composeApp wasmJs target), never run so far.
#
#   scripts/build_web.sh  -> app/build/web/   Serve it yourself, same origin as the core (POP_WEB_DIR) or set POP_CORS_ORIGINS on the core.
#
# POP_SERVER_URL overrides the baked-in core (default https://pop.enconomy.dev; the fallback
# when the page is not served over http(s)). Nothing is deployed here.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"     # examples/safe/app/
url="${POP_SERVER_URL:-https://pop.enconomy.dev}"
dest="$here/build/web"

cd "$here"
./gradlew :composeApp:wasmJsBrowserDistribution "-Ppop.serverUrl=$url" "-Ppop.webSameOrigin=true"

out="$here/composeApp/build/dist/wasmJs/productionExecutable"
mkdir -p "$dest"
rsync -a --delete --exclude '*.map' "$out/" "$dest/"
echo "web app (same origin as /app/) -> $dest"
