#!/bin/bash
# Web build of this example's app (Kotlin/Wasm, composeApp wasmJs target), copied to web/app/ for ens.enconomy.dev/app/
# (wrangler serves web/, nothing is deployed here). It talks to the core at POP_SERVER_URL, which then needs
# POP_CORS_ORIGINS=https://ens.enconomy.dev. The web app has no ENS screen and never calls the ENS backend.
#
# Never run yet, like the rest of this copy. On a small machine put the gradle run under the repo's tools/heavy.sh.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"     # app/
url="${POP_SERVER_URL:-https://pop.enconomy.dev}"
dest="$here/../web/app"

cd "$here"
./gradlew :composeApp:wasmJsBrowserDistribution "-Ppop.serverUrl=$url" "-Ppop.webSameOrigin=false"

out="$here/composeApp/build/dist/wasmJs/productionExecutable"
mkdir -p "$dest"
rsync -a --delete --exclude '*.map' "$out/" "$dest/"
echo "web app ($url) -> $dest"
