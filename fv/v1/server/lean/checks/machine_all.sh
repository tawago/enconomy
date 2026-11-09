#!/bin/bash
# Every check for ServerFv/Machine.lean and the files that prove things about it, from fv/v1/server/lean.
# Checked files: Machine.lean plus every ServerFv/*.lean except Verdict.lean (lean-verdict checks) and Replay.lean (replay_all.sh).
# These results show the server follows its rules on signed numbers. They do not show a phone told the truth about the air (CN1).
# Leftover scratch files in ServerFv/ (mutant copies) are checked too and will fail: clean them first.
# Exit code: 0 only if every step passed. Any failed step sets it to 1. The last line says "overall rc=N".
set -u
fail=0
bad() { echo "FAIL: $*"; fail=1; }
tmp=$(mktemp -d "${TMPDIR:-/tmp}/machine_all.XXXXXX")
trap 'rm -rf "$tmp"' EXIT

# With arguments, only those files are checked (a quick run; the full run takes no arguments).
# An empty, spaced or missing file name fails the run: it would otherwise skip the per-file checks.
for a in "$@"; do
  case "$a" in ""|*[[:space:]]*) echo "FAIL: empty argument or a name with spaces: '$a'"; echo "overall rc=1"; exit 1;; esac
  [ -f "$a" ] && [ -r "$a" ] || { echo "FAIL: no readable file '$a'"; echo "overall rc=1"; exit 1; }
done
# Kept in an array and always expanded quoted, so no name is globbed or split.
files=("ServerFv/Machine.lean")
if [ $# -gt 0 ]; then files=("$@"); else
  for f in ServerFv/*.lean; do
    case "$(basename "$f")" in Machine.lean|Verdict.lean|Replay.lean) continue;; esac
    files+=("$f")
  done
fi
mods=(); for f in "${files[@]}"; do mods+=("ServerFv.$(basename "$f" .lean)"); done
echo "== files: ${files[*]}"

# grep -c that returns 2 on a read error (grep rc 2+) instead of a count.
count() { local n r; n=$(grep -c "$@"); r=$?; [ "$r" -gt 1 ] && return 2; echo "$n"; }
# grep -q that fails the run on a read error: returns 0 found, 1 not found, 2+ error.
has() { local r; grep -q "$@"; r=$?; [ "$r" -gt 1 ] && bad "grep read error rc=$r on: $*"; return $r; }

echo "== lake build"
lake build "${mods[@]}" 2>&1 | grep -v "Popfv\|Copyright\|linter\|^$\|Verdict.lean\|depends on axioms\|does not depend\|deprecated\|Hint\|if_\|ite_" | tail -6
build_rc=${PIPESTATUS[0]}
echo "build rc=$build_rc"
if [ "$build_rc" -ne 0 ]; then echo "== end of machine_all"; echo "overall rc=1"; exit 1; fi   # a broken build would make every mutant look broken

for f in "${files[@]}"; do
  echo "== fresh lake env lean $f"
  out="$tmp/$(basename "$f").txt"
  lake env lean "$f" > "$out" 2>&1; rc=$?
  echo "fresh rc=$rc"; [ "$rc" -ne 0 ] && bad "$f fresh rc=$rc"
  nreq=$(count '^#print axioms' "$f") || { bad "$f: could not read the source"; continue; }
  nlines=$(count "depends on axioms\|does not depend" "$out") || { bad "$f: could not read the lean output"; continue; }
  echo "print-axioms requests: $nreq, lines: $nlines"
  [ "$nreq" -eq 0 ] && bad "$f has no #print axioms"
  [ "$nreq" -ne "$nlines" ] && bad "$f asked for $nreq axiom lines, got $nlines"
  nerr=$(count ': error' "$out") || { bad "$f: could not read the lean output"; continue; }
  echo "errors: $nerr"; [ "$nerr" -gt 0 ] && { grep ': error' "$out" | head -5; bad "$f errors=$nerr"; }
  # Lean wraps a long axiom list over several lines: join the output before reading the lists.
  # Every pipeline stage is checked: a failed stage would leave an empty list that passes the allow-list.
  tr '\n' ' ' < "$out" | grep -o "depends on axioms: \[[^]]*\]\|does not depend on any axioms" | tr -s ' ' > "$tmp/sets.txt"
  ps=("${PIPESTATUS[@]}")
  if [ "${ps[0]}" -ne 0 ] || [ "${ps[1]}" -gt 1 ] || [ "${ps[2]}" -ne 0 ]; then bad "$f axiom list scan failed, stage rc ${ps[*]}"; continue; fi
  echo "axiom sets seen:"; sort "$tmp/sets.txt" | uniq -c
  nsets=$(count 'depend' "$tmp/sets.txt") || { bad "$f: could not read the axiom lists"; continue; }
  [ "$nsets" -ne "$nreq" ] && bad "$f asked for $nreq axiom lists, parsed $nsets"
  ndep=$(count 'depends on axioms:' "$tmp/sets.txt") || { bad "$f: could not read the axiom lists"; continue; }
  # only propext, Classical.choice, Quot.sound are allowed
  grep -o "depends on axioms: \[[^]]*\]" "$tmp/sets.txt" | sed -e 's/depends on axioms: \[//' -e 's/\]$//' | tr ',' '\n' | sed 's/^ *//; s/ *$//' \
    | grep -v '^$' > "$tmp/ax_names.txt"
  ps=("${PIPESTATUS[@]}")
  if [ "${ps[0]}" -gt 1 ] || [ "${ps[1]}" -ne 0 ] || [ "${ps[2]}" -ne 0 ] || [ "${ps[3]}" -ne 0 ] || [ "${ps[4]}" -gt 1 ]; then
    bad "$f axiom name extraction failed, stage rc ${ps[*]}"; continue; fi
  nnames=$(count '' "$tmp/ax_names.txt") || { bad "$f: could not read the axiom names"; continue; }
  echo "axiom lists with names: $ndep, names read: $nnames"
  [ "$nnames" -lt "$ndep" ] && { bad "$f printed $ndep axiom lists but $nnames names were read"; continue; }
  # Whole-line fixed strings, so a name like ClassicalXchoice is not allowed. grep -v: 0 = other names, 1 = none, 2+ = error.
  grep -vxF -e propext -e Classical.choice -e Quot.sound "$tmp/ax_names.txt" > "$tmp/ax_odd.txt"; ax_rc=$?
  case "$ax_rc" in 0) bad "$f other axioms: $(sort -u "$tmp/ax_odd.txt" | tr '\n' ' ')";; 1) ;; *) bad "$f axiom allow-list grep rc=$ax_rc";; esac
  # belt and braces: these names must not show up anywhere in the output, wrapped or not
  grep -nE 'sorryAx|ofReduceBool|trustCompiler' "$out"; bb_rc=$?
  case "$bb_rc" in 0) bad "$f output names sorryAx/ofReduceBool/trustCompiler";; 1) ;; *) bad "$f output scan rc=$bb_rc";; esac
done

echo "== word scan of source"
grep -nE '\bsorry\b|\badmit\b|native_decide|^[[:space:]]*(axiom|unsafe|partial)\b|ex''ploit' "${files[@]}"; scan_rc=$?
echo "scan done rc=$scan_rc"   # grep: 0 = found, 1 = clean, anything else = could not read
case "$scan_rc" in 0) bad "word scan found something";; 1) ;; *) bad "word scan rc=$scan_rc (read error)";; esac

echo "== traces"
lake env lean checks/machine_traces.lean > "$tmp/traces.txt" 2>&1; traces_rc=$?
sed -e 's/^info: //' "$tmp/traces.txt"; echo "traces rc=$traces_rc"
[ "$traces_rc" -ne 0 ] && bad "traces rc=$traces_rc"
[ -r "$tmp/traces.txt" ] || bad "traces output missing"
has ': error' "$tmp/traces.txt" && bad "traces have errors"
has '^done$\|^info: done$\|: done$' "$tmp/traces.txt" || bad "traces did not reach done"
has 't=594301: accepted ServerFv.Machine.St.started' "$tmp/traces.txt" || bad "E2 beats E3 trace: no transcript accepted at 594301"
has 't=620000: view st=[A-Za-z.]*aborted .*err=some (*[A-Za-z.]*timeout' "$tmp/traces.txt" || bad "E2 beats E3 trace: not aborted at 620000"

echo "== mutants"; python3 checks/machine_mutants.py; mut_rc=$?; echo "mutants rc=$mut_rc"
[ "$mut_rc" -ne 0 ] && bad "mutants rc=$mut_rc"
echo "== end of machine_all"
echo "overall rc=$fail"
exit "$fail"
