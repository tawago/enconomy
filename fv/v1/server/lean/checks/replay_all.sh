#!/bin/bash
# The replay of Machine.step on traces from the real server, from fv/v1/server/lean.
# Usage: checks/replay_all.sh TRACE.jsonl [TRACE2.jsonl ...]
# Exit code: the build's if it fails, else the combined replay's (1 mismatch, 2 unreadable, 3 too few sessions or a target missed),
# else 1 if a one-trace run found a mismatch or couldn't read its trace. A single trace can be short on targets, so rc=3 there is only a note.
# Testing on sampled runs, not a proof the Lean table equals the Python. These results show the server follows its rules on
# signed numbers. They do not show a phone told the truth about the air (CN1).
set -u
echo "== lake build (the Machine proofs too, so the Replay reads what was checked)"
lake build ServerFv 2>&1 | tail -1
build_rc=${PIPESTATUS[0]}
echo "build rc=$build_rc"
if [ "$build_rc" -ne 0 ]; then echo "== end of replay_all, rc=$build_rc"; exit "$build_rc"; fi
echo "== traces"
for f in "$@"; do echo "$(basename "$f") lines=$(wc -l < "$f") sha256=$(sha256sum "$f" | cut -d' ' -f1) header=$(head -1 "$f")"; done
echo "== replay, all traces together"
lake env lean --run ServerFv/Replay.lean "$@"
all_rc=$?
echo "replay rc=$all_rc"
echo "== replay, one trace at a time"
one_bad=0
one=$(mktemp)
for f in "$@"; do
  lake env lean --run ServerFv/Replay.lean "$f" > "$one" 2>&1; rc=$?
  echo "$(basename "$f") rc=$rc $(grep -E '^(sessions|RESULT)' "$one" | tr '\n' ' ')"
  if [ "$rc" -ne 0 ] && [ "$rc" -ne 3 ]; then one_bad=1; fi
done
rm -f "$one"
final=$all_rc
if [ "$final" -eq 0 ]; then final=$one_bad; fi
echo "== end of replay_all, rc=$final"
exit "$final"
