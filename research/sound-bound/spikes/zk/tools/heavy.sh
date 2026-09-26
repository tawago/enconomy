#!/bin/bash
# Serialize heavy jobs (big builds, proving runs) on this 8 GB machine.
# Usage: tools/heavy.sh <label> <command...>
# Waits for the global lock, runs the command, prints wall time, releases the lock.
LOCK=/tmp/zk-heavy.lock
label=$1; shift
until mkdir "$LOCK" 2>/dev/null; do
  if [ -f "$LOCK/pid" ] && ! kill -0 "$(cat "$LOCK/pid")" 2>/dev/null; then rm -rf "$LOCK"; continue; fi
  sleep 3
done
echo $$ > "$LOCK/pid"; echo "$label" > "$LOCK/label"
trap 'rm -rf "$LOCK"' EXIT
start=$(python3 -c 'import time;print(time.time())')
"$@"; rc=$?
python3 -c "import time;print('[heavy] $label: %.1fs rc=$rc' % (time.time()-$start))" >&2
exit $rc
