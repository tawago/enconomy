#!/bin/bash
# Builds the extension. Usage: extension/build.sh [output dir]
# Default output: extension/build/extension. For the patched browser: out/<dir>/wvp_extension.
# Needs WVP_THIRD_PARTY (prover/README.md) and npm ci in wvp/. esbuild is the one the SDK's lockfile pins (0.27.3).
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
: "${WVP_THIRD_PARTY:?Set WVP_THIRD_PARTY. See prover/README.md.}"
T=$WVP_THIRD_PARTY
ESBUILD=${ESBUILD:-$T/sdk-q1/node_modules/.bin/esbuild}
OUT=${1:-$HERE/build/extension}
rm -rf "$OUT"; mkdir -p "$OUT/wasm" "$HERE/build"
cd "$HERE"
B="--bundle --format=esm --platform=browser --target=es2022 --log-level=warning --alias:openac-sdk=$T/sdk-q1"
for f in sw coordinator offscreen popup pool-worker; do "$ESBUILD" "src/$f.mjs" $B --outfile="$OUT/$f.js"; done
cp src/static/* "$OUT/"
cp src/page-api.js src/bridge.js src/login.js "$OUT/"
cp "$T/p2-threads/openac_plain2.wasm" "$T/sdk-q1/assets/jwt_1k.wasm" "$T/sdk-q1/assets/show.wasm" "$OUT/wasm/"
echo '{"issuerOrigin":"http://issuer.test:8801","approveOrigin":"http://enroll.test:8806","assetBase":"http://keys.test:8804","threads":4}' > "$OUT/config.json"
# The fake wallet is for the demo only. It never goes in the extension.
"$ESBUILD" ../demo/fake-wallet.mjs --bundle --format=iife --platform=browser --target=es2022 --log-level=warning --outfile=build/fake-wallet.js
du -sh "$OUT"
