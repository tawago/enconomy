#!/usr/bin/env bash
# Laptop loop: every 1 s, relay each finished safe-tx session of the last 15 min exactly once.
# out/<sid>.json (sent) or out/<sid>.skip (refused) marks a session handled; relay.mjs is idempotent anyway.
# env: POP_DB (default ../server/data/pop.sqlite) + everything relay.mjs needs (RELAYER_PK, RPC, POP_SERVER_URL).
set -uo pipefail
cd "$(dirname "$0")"
DB=${POP_DB:-../server/data/pop.sqlite}; OUT=${OUT_DIR:-./out}; mkdir -p "$OUT"
while sleep 1; do
  since=$(( ($(date +%s) - 900) * 1000 ))
  sqlite3 "$DB" "select session_id from sessions
     where json_extract(doc,'\$.context.kind') = 'safe-tx' and json_extract(doc,'\$.state') = 'done'
       and json_extract(doc,'\$.finished_ms') > $since" |
  while read -r sid; do
    [ -e "$OUT/$sid.json" ] || [ -e "$OUT/$sid.skip" ] || node relay.mjs "$sid" | tee -a "$OUT/log.jsonl"
  done
done
