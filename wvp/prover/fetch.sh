#!/bin/bash
# Gets what the prover and the demo need into $WVP_THIRD_PARTY. Usage: prover/fetch.sh source | keys
#   source: zkID at the pinned commit, plus a patched copy of its SDK, built.
#   keys:   the 4 published 1k keys, about 560 MB. Digests are checked.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
: "${WVP_THIRD_PARTY:?Set WVP_THIRD_PARTY to an empty folder. See prover/README.md.}"
T=$WVP_THIRD_PARTY
mkdir -p "$T"
T=$(cd "$T" && pwd)
PIN=b395e09c225ff45b003f0087c28e2e208e22f944
KEY_BASE=https://pub-d941fd6fc0c84bd892810e681a55edcd.r2.dev/openac-5.0.0   # The SDK's default, DEFAULT_KEYS_BASE_URL in src/index.ts.

source_step() {
  if [ ! -d "$T/zkID/.git" ]; then
    git init -q "$T/zkID"
    git -C "$T/zkID" remote add origin https://github.com/privacy-ethereum/zkID.git
  fi
  git -C "$T/zkID" fetch --depth 1 origin "$PIN"
  git -C "$T/zkID" checkout -q FETCH_HEAD
  [ "$(git -C "$T/zkID" rev-parse HEAD)" = "$PIN" ]
  ln -sfn "$T/zkID" "$HERE/zkID"
  rm -rf "$T/sdk-q1"
  cp -R "$T/zkID/wallet-unit-poc/openac-sdk" "$T/sdk-q1"
  rm -rf "$T/sdk-q1/wasm"   # Upstream's wasm-bindgen glue. We use prover/fast. Without this the dist bundles it and differs from what ran.
  patch -s -p1 -d "$T/sdk-q1" < "$HERE/sdk-q1.patch"
  (cd "$T/sdk-q1" && npm ci --ignore-scripts && npx tsup --no-dts)
}

keys_step() {
  mkdir -p "$T/keys"
  cd "$T/keys"
  while read -r sha file; do
    [ -f "$file" ] || curl -fL -o "$file" "$KEY_BASE/$file"
    echo "$sha  $file" | shasum -a 256 -c -
  done <<'K'
095f9c253274a831eb5d8225b6d7b855ab8471621968e773c041c83f32c46e8a 1k_prepare_proving.key
f1fcc1d5036ef6ca9efb538b3510a5a492518018beb217c50ee2c014d7351add 1k_prepare_verifying.key
809f24ca6ee003b684e2282b77f5a47279528edee7654a3801770a2ffca67831 1k_show_proving.key
f0c447a9757d182e8aa23083bc3dba5a9a22f3e0fcbb344724568cc3c83352d8 1k_show_verifying.key
K
}

case "$1" in
  source) source_step ;;
  keys) keys_step ;;
  *) echo "Usage: prover/fetch.sh source | keys"; exit 2 ;;
esac
