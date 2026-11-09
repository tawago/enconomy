#!/bin/bash
# Every check of fv/v1/server, against the server/ in this same checkout. Nothing is pinned to an old commit.
#
#   fv/v1/server/run_all.sh [python|lean|all]      default: all
#
# python  spec rechecks, the walk (1000 sessions, fixed seed), four traces (3 seeds x 2000 sessions + the directed cases)
# lean    lake build, a fresh check of Verdict.lean, the layout vectors, machine_all.sh (with its mutants)
# all     both, then the replay of the Lean table on the traces and replay_checks.py (tampers + rule mutants)
#
# Env: PY (python with the server's deps, default python3), OUT (default fv/v1/server/logs, git-ignored),
#      WALK_SESSIONS (1000), TRACE_SESSIONS (2000). Traces are seeded, so they are made fresh each run and never stored.
# Output: one file per step in $OUT, and a summary table at the end. Exit 0 only if every step passed.
# These checks show the server follows its rules on signed numbers. They do not show a phone told the truth about the air (CN1).
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../.." && pwd)
PY=${PY:-python3}
OUT=${OUT:-$HERE/logs}
mkdir -p "$OUT"; OUT=$(cd "$OUT" && pwd)   # absolute: steps cd into other folders
WALK_SESSIONS=${WALK_SESSIONS:-1000}
TRACE_SESSIONS=${TRACE_SESSIONS:-2000}
what=${1:-all}
case "$what" in python|lean|all) ;; *) echo "usage: run_all.sh [python|lean|all]"; exit 2;; esac
mkdir -p "$OUT" "$OUT/traces"
T=$OUT/traces
export PYTHONPATH="$REPO/server"
command -v sha256sum >/dev/null || sha256sum() { shasum -a 256 "$@"; }
export -f sha256sum 2>/dev/null || true

declare -a NAMES RCS
step() {   # step NAME DIR CMD... : run, log to $OUT/NAME.txt, remember the rc
  local name=$1 dir=$2; shift 2
  echo "== $name"
  local t0=$SECONDS
  (cd "$dir" && "$@") > "$OUT/$name.txt" 2>&1
  local rc=$?
  echo "   rc=$rc, $((SECONDS - t0)) s, $(tail -1 "$OUT/$name.txt" | cut -c1-120)"
  NAMES+=("$name"); RCS+=("$rc")
}

{ if git -C "$REPO" rev-parse HEAD >/dev/null 2>&1; then
    echo "commit $(git -C "$REPO" rev-parse HEAD)$(git -C "$REPO" diff --quiet HEAD -- server fv/v1 || echo ' + local changes')"
  else echo "commit unknown, not a git checkout"; fi
  echo "python $($PY --version 2>&1)"; date -u +%FT%TZ; } > "$OUT/run.txt"
cat "$OUT/run.txt"

if [ "$what" != lean ]; then
  step recheck "$HERE" "$PY" spec-checks/recheck.py
  step recheck-m6-fail "$HERE/tests" "$PY" recheck_m6_fail.py
  step walk "$HERE/tests" "$PY" -m pytest -q -p no:cacheprovider test_walk.py --walk-sessions "$WALK_SESSIONS"
  # The four traces are independent: run them side by side.
  echo "== traces (4 in parallel)"
  t0=$SECONDS
  (cd "$HERE/tests"
   "$PY" -m pytest -q -p no:cacheprovider test_walk.py::test_walk --walk-seed 20261106 --walk-sessions "$TRACE_SESSIONS" --trace-out "$T/walk-20261106.jsonl" > "$OUT/trace-20261106.txt" 2>&1 & p1=$!
   "$PY" -m pytest -q -p no:cacheprovider test_walk.py::test_walk --walk-seed 7001 --walk-sessions "$TRACE_SESSIONS" --trace-out "$T/walk-7001.jsonl" > "$OUT/trace-7001.txt" 2>&1 & p2=$!
   "$PY" -m pytest -q -p no:cacheprovider test_walk.py::test_walk --walk-seed 7002 --walk-sessions "$TRACE_SESSIONS" --trace-out "$T/walk-7002.jsonl" > "$OUT/trace-7002.txt" 2>&1 & p3=$!
   "$PY" -m pytest -q -p no:cacheprovider test_walk.py::test_directed_cases --directed-trace-out "$T/directed.jsonl" > "$OUT/trace-directed.txt" 2>&1 & p4=$!
   rc=0; for p in $p1 $p2 $p3 $p4; do wait $p || rc=1; done; exit $rc)
  rc=$?; echo "   rc=$rc, $((SECONDS - t0)) s"; NAMES+=(traces); RCS+=("$rc")
fi

if [ "$what" != python ]; then
  L=$HERE/lean
  step lake-build "$L" bash -c 'lake exe cache get >/dev/null 2>&1; lake build 2>&1 | tail -3; exit ${PIPESTATUS[0]}'
  step lean-verdict "$L" lake env lean ServerFv/Verdict.lean
  step layout-vectors "$HERE" "$PY" spec-checks/layout_vectors.py "$OUT/lean-verdict.txt"
  step machine-all "$L" bash checks/machine_all.sh
fi

if [ "$what" = all ]; then
  traces=("$T/walk-20261106.jsonl" "$T/walk-7001.jsonl" "$T/walk-7002.jsonl" "$T/directed.jsonl")
  step replay "$HERE/lean" bash checks/replay_all.sh "${traces[@]}"
  step replay-checks "$HERE/lean" python3 checks/replay_checks.py "$T/walk-20261106.jsonl" 0 "$T/directed.jsonl"
fi

echo
echo "| step | rc |"
echo "| --- | --- |"
fail=0
for i in "${!NAMES[@]}"; do echo "| ${NAMES[$i]} | ${RCS[$i]} |"; [ "${RCS[$i]}" -eq 0 ] || fail=1; done
echo "overall rc=$fail"
exit $fail
