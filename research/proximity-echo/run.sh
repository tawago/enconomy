#!/usr/bin/env bash
# Proximity-Echo launcher.
#
# Usage:
#   ./run.sh check   # parse first-party Python and JavaScript, then check this script
#   ./run.sh serve   # run the same checks, then start the HTTPS server
#   ./run.sh         # same as ./run.sh serve
#
# These checks catch syntax errors only. They do not validate acoustic ranging,
# scoring, or protocol behavior.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$SCRIPT_DIR/.venv/bin/python"

check_python() {
  echo ">> Parsing first-party Python files..."
  find "$SCRIPT_DIR" \
    \( -path "$SCRIPT_DIR/.venv" -o -path "$SCRIPT_DIR/tests" \) -prune -o \
    -type f -name '*.py' -print0 |
    "$PYTHON" -c '
import sys
from pathlib import Path

paths = [Path(item.decode()) for item in sys.stdin.buffer.read().split(b"\0") if item]
for path in paths:
    compile(path.read_bytes(), str(path), "exec")
print(f"Python syntax OK ({len(paths)} files)")
'
}

check_javascript() {
  if ! command -v node >/dev/null 2>&1; then
    echo "Node.js is required to parse the first-party browser scripts." >&2
    return 1
  fi

  echo ">> Parsing first-party JavaScript files..."
  find "$SCRIPT_DIR/static" -type f \
    \( -name '*.js' -o -name '*.cjs' -o -name '*.mjs' \) \
    ! -name 'socket.io.min.js' -print0 |
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
  echo ">> Starting server..."
  exec "$PYTHON" "$SCRIPT_DIR/server.py"
}

case "${1:-serve}" in
  serve|"")
    serve
    ;;
  check)
    check
    ;;
  *)
    echo "Usage: ./run.sh [serve|check]" >&2
    exit 1
    ;;
esac
