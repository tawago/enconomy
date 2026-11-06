#!/bin/bash
# Builds the extension. Usage: extension/build.sh [output dir]
# Default output: extension/build/extension. For the patched browser: out/<dir>/wvp_extension.
# Needs WVP_THIRD_PARTY (prover/README.md) and npm ci in wvp/. esbuild is the one the SDK's lockfile pins (0.27.3).
# Other hosts, https too. With none of these set you get the *.test demo build.
#   WVP_APPROVE_ORIGIN  the approval page's origin. Setting this one rewrites the manifest's matches.
#   WVP_LOGIN_MATCHES   comma list of match patterns where the login script runs. Required with WVP_APPROVE_ORIGIN.
#   WVP_HOST_PERMISSIONS  comma list of match patterns for the issuer and key host. Default none, which is fine with no issuer.
#   WVP_ISSUER_ORIGIN, WVP_ASSET_BASE  default to the *.test ones. Sites check names with neither.
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
echo "{\"issuerOrigin\":\"${WVP_ISSUER_ORIGIN:-http://issuer.test:8801}\",\"approveOrigin\":\"${WVP_APPROVE_ORIGIN:-http://enroll.test:8806}\",\"assetBase\":\"${WVP_ASSET_BASE:-http://keys.test:8804}\",\"threads\":4}" > "$OUT/config.json"
if [ -n "${WVP_APPROVE_ORIGIN:-}" ]; then
  : "${WVP_LOGIN_MATCHES:?WVP_APPROVE_ORIGIN needs WVP_LOGIN_MATCHES.}"
  # Only the matches and host permissions change. The key stays, so the extension ID does too.
  node -e '
    const fs = require("fs"), f = process.argv[1], m = JSON.parse(fs.readFileSync(f, "utf8")), e = process.env;
    const list = (s) => (s ?? "").split(",").map((x) => x.trim()).filter(Boolean);
    m.host_permissions = list(e.WVP_HOST_PERMISSIONS);
    const [page, bridge, login] = m.content_scripts;
    page.matches = bridge.matches = [`${e.WVP_APPROVE_ORIGIN}/*`];
    login.matches = list(e.WVP_LOGIN_MATCHES);
    fs.writeFileSync(f, JSON.stringify(m, null, 2) + "\n");
  ' "$OUT/manifest.json"
fi
# The fake wallet is for the demo only. It never goes in the extension.
"$ESBUILD" ../demo/fake-wallet.mjs --bundle --format=iife --platform=browser --target=es2022 --log-level=warning --outfile=build/fake-wallet.js
du -sh "$OUT"
