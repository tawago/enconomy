#!/bin/bash
# Web build of the PoP app (Kotlin/Wasm, app/composeApp wasmJs target) and copy to where it is served.
#
#   app/scripts/build_web.sh              -> server/web-app/   (server: POP_WEB_DIR=web-app; the app talks to the origin
#                                                              that serves /app/: tunnel, LAN or localhost:8000)
#   app/scripts/build_web.sh --workers    -> web/app/          (ens.enconomy.dev/app/ via wrangler; server: POP_CORS_ORIGINS=https://ens.enconomy.dev)
#
# POP_SERVER_URL overrides the baked-in server (default https://pop.enconomy.dev; used as-is by --workers, and as the
# fallback when the page is not served over http(s)). Nothing is deployed here.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"     # app/
repo="$(cd "$here/.." && pwd)"
url="${POP_SERVER_URL:-https://pop.enconomy.dev}"
dest="$repo/server/web-app"
same=true
[ "${1:-}" = "--workers" ] && { dest="$repo/web/app"; same=false; }

heavy="$repo/research/sound-bound/spikes/zk/tools/heavy.sh"
run=(./gradlew :composeApp:wasmJsBrowserDistribution "-Ppop.serverUrl=$url" "-Ppop.webSameOrigin=$same")
cd "$here"
if [ -x "$heavy" ]; then "$heavy" pop-web "${run[@]}"; else "${run[@]}"; fi

out="$here/composeApp/build/dist/wasmJs/productionExecutable"
mkdir -p "$dest"
rsync -a --delete --exclude '*.map' "$out/" "$dest/"
if $same; then echo "web app (same origin as /app/) -> $dest"; else echo "web app ($url) -> $dest"; fi
