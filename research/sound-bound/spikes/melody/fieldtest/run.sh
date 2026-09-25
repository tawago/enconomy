#!/usr/bin/env bash
# fieldtest launcher.
#
#   ./run.sh check   # compile() every fieldtest .py (no .pyc written), node --check static/*.js, bash -n run.sh
#   ./run.sh serve   # check, then python server.py  (https://0.0.0.0:5004)
#   ./run.sh synth   # python synth_field.py --walk  (writes data/synth/, prints the table)
#   ./run.sh e2e     # own server on :$E2E_PORT (default 5005) -> data/e2e, fake phones 30 + 200 cm, server stopped after
#
# FIELD_GAIN_DB="N250:0,N500:0,N1s:0,JBL:0,JBL250:0" passes through to the server (dB per probe).

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="/Users/takahiro_ogawa/dev/enconomy/research/proximity-echo/.venv/bin/python3"

check() {
  [ -x "$PYTHON" ] || { echo "missing python at $PYTHON" >&2; return 1; }
  echo ">> python"
  local n=0
  for f in "$HERE"/*.py; do
    [ -e "$f" ] || continue
    "$PYTHON" -c 'import sys; compile(open(sys.argv[1],"rb").read(), sys.argv[1], "exec")' "$f"
    n=$((n + 1))
  done
  echo "python OK ($n files)"
  echo ">> javascript"
  command -v node >/dev/null 2>&1 || { echo "node is required" >&2; return 1; }
  for f in "$HERE"/static/*.js; do
    [ "$(basename "$f")" = "socket.io.min.js" ] && continue
    node --check "$f"
  done
  echo "javascript OK"
  bash -n "$HERE/run.sh"
  echo "shell OK"
}

case "${1:-serve}" in
  check) check ;;
  serve)
    check
    echo ">> https://0.0.0.0:5004  FIELD_GAIN_DB=${FIELD_GAIN_DB:-}"
    cd "$HERE"
    exec "$PYTHON" "$HERE/server.py" ;;
  synth)
    cd "$HERE"
    exec "$PYTHON" "$HERE/synth_field.py" --walk ;;
  e2e)
    # Starts its own server on :E2E_PORT (default 5005, so a live :5004 keeps running) with
    # sessions in data/e2e (never data/sessions), runs two fake phones at 30 cm and 200 cm
    # (A at 44.1 kHz for the second), then stops that server.
    cd "$HERE"
    PORT_E2E="${E2E_PORT:-5005}"
    URL="https://127.0.0.1:$PORT_E2E"
    if curl -sk --max-time 2 "$URL/api/time" >/dev/null 2>&1; then
      echo "port $PORT_E2E busy (a server is running); stop it or set E2E_PORT" >&2; exit 1
    fi
    check
    mkdir -p "$HERE/data/e2e"
    FIELD_PORT="$PORT_E2E" FIELD_SESSIONS_DIR="$HERE/data/e2e" "$PYTHON" "$HERE/server.py" >"$HERE/data/e2e/server.log" 2>&1 &
    SRV=$!
    trap 'kill $SRV 2>/dev/null || true' EXIT
    for _ in $(seq 1 40); do
      curl -sk --max-time 1 "$URL/api/time" >/dev/null 2>&1 && break
      sleep 0.25
    done
    rc=0
    "$PYTHON" "$HERE/e2e.py" --url "$URL" --dist-cm 30 || rc=1
    "$PYTHON" "$HERE/e2e.py" --url "$URL" --dist-cm 200 --sr-a 44100 || rc=1
    "$PYTHON" "$HERE/compare.py" --dir "$HERE/data/e2e"
    exit $rc ;;
  *) echo "usage: ./run.sh [check|serve|synth|e2e]" >&2; exit 1 ;;
esac
