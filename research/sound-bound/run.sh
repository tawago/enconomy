#!/usr/bin/env bash
# sound-bound launcher.
#
#   ./run.sh check   # parse first-party Python + JavaScript, then this script
#   ./run.sh serve   # check, then start the HTTPS server on :5003
#   ./run.sh         # same as serve
#
# These are syntax checks only. They say nothing about whether the acoustics work.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$SCRIPT_DIR/../proximity-echo/.venv/bin/python"

check_python() {
  if [ ! -x "$PYTHON" ]; then
    echo "Missing venv python at $PYTHON" >&2
    return 1
  fi
  echo ">> Parsing first-party Python files..."
  find "$SCRIPT_DIR" -path "$SCRIPT_DIR/data" -prune -o -type f -name '*.py' -print0 |
    "$PYTHON" -c '
import sys
from pathlib import Path

paths = [Path(p.decode()) for p in sys.stdin.buffer.read().split(b"\0") if p]
for path in paths:
    compile(path.read_bytes(), str(path), "exec")
print(f"Python syntax OK ({len(paths)} files)")
'
}

check_javascript() {
  if ! command -v node >/dev/null 2>&1; then
    echo "Node.js is required to parse the browser scripts." >&2
    return 1
  fi
  echo ">> Parsing first-party JavaScript files..."
  find "$SCRIPT_DIR/static" -type f -name '*.js' ! -name 'socket.io.min.js' -print0 |
    while IFS= read -r -d '' file; do
      node --check "$file"
    done
  echo "JavaScript syntax OK"
}

check() {
  check_python
  check_javascript
  bash -n "$SCRIPT_DIR/run.sh"
  echo "Shell syntax OK"
}

serve() {
  check
  echo ">> Starting server on https://0.0.0.0:5003 ..."
  exec "$PYTHON" "$SCRIPT_DIR/server.py"
}

case "${1:-serve}" in
  serve|"") serve ;;
  check) check ;;
  *) echo "Usage: ./run.sh [serve|check]" >&2; exit 1 ;;
esac
