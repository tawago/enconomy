#!/usr/bin/env bash
# Run our alt mempool node against public chain 1337, with our own rules:
#   - verify gas cap raised to 16M (the public sidecar uses 100k)
#   - precompiles allowed in VERIFY (the public sidecar bans them)
#
# First run clones and builds. Needs devnet/.run/heavy.key, which
# `node poc/clients/heavy-verify.cjs setup` creates.
#
#   devnet/sidecar.sh
#   SIDECAR_ADDRESS=0.0.0.0 devnet/sidecar.sh   # let phones reach it
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/.vendor/sidecar"
RUN="$HERE/.run"
KEY_FILE="$RUN/heavy.key"
HEAVY="$HERE/../../sound-bound/spikes/zk/tools/heavy.sh"

PIN=2e22ff0a2898e69ea4bf5275bce1be8581a8582a
REPO=https://github.com/forshtat/mempool-workshop-sidecar
NODE=https://altmempool.forshtat.com
CAP_FILE=packages/executor/src/services/UserOpValidation/utils/validationPrefix.ts
CAP_NEW='MAX_VERIFY_GAS = BigInt(16_000_000)'

[ -r "$KEY_FILE" ] || {
  echo "no $KEY_FILE: run heavy-verify.cjs setup first" >&2
  exit 1
}

if [ ! -d "$SRC" ]; then
  git clone --filter=blob:none "$REPO" "$SRC"
  git -C "$SRC" checkout -q "$PIN"
fi
cd "$SRC"

needs_build=no
[ -d packages/executor/lib ] || needs_build=yes
# Matches any earlier cap, so an already-patched clone gets updated too.
if ! grep -qF "$CAP_NEW" "$CAP_FILE"; then
  sed -i '' -E "s/MAX_VERIFY_GAS = BigInt\([0-9_]+\)/$CAP_NEW/" "$CAP_FILE"
  grep -qF "$CAP_NEW" "$CAP_FILE" || {
    echo "cap patch did not apply to $CAP_FILE" >&2
    exit 1
  }
  needs_build=yes
fi
if [ "$needs_build" = yes ]; then
  "$HEAVY" sidecar sh -c 'bun install --frozen-lockfile && bun run build'
fi

# 0x01-0x11 are the standard precompiles, 0x100 is P256VERIFY.
# The sidecar compares full lowercase 20-byte addresses.
precompiles() {
  for n in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 256; do
    printf '0x%040x\n' "$n"
  done | jq -R . | jq -s .
}

(umask 077
  jq --arg key "$(tr -d '[:space:]' < "$KEY_FILE")" \
     --arg node "$NODE" \
     --argjson precompiles "$(precompiles)" \
     '.relayers = [$key]
      | .rpcEndpoint = $node
      | .rpcEndpointSubmit = $node
      | .precompiles = $precompiles' \
     config.json.default > config.json)

exec ./skandha standalone --redirectRpc \
  --api.address "${SIDECAR_ADDRESS:-127.0.0.1}" \
  --dataDir "$RUN/sidecar-db"
