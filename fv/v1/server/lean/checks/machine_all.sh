#!/bin/bash
# Every check for ServerFv/Machine.lean, from fv/v1/server/lean.
# These results show the server follows its rules on signed numbers. They do not show a phone told the truth about the air (CN1).
set -u
echo "== lake build"; lake build 2>&1 | grep -v "Popfv\|Copyright\|linter\|^$\|Verdict.lean\|depends on axioms\|does not depend\|deprecated\|Hint\|if_\|ite_" | tail -6
build_rc=${PIPESTATUS[0]}
echo "build rc=$build_rc"
if [ "$build_rc" -ne 0 ]; then echo "== end of machine_all"; exit "$build_rc"; fi   # a broken build would make every mutant look broken
echo "== fresh lake env lean ServerFv/Machine.lean"
lake env lean ServerFv/Machine.lean > /tmp/machfix_fresh.txt 2>&1; echo "fresh rc=$?"
echo "print-axioms lines: $(grep -c "axioms\|does not depend" /tmp/machfix_fresh.txt)"
echo "print-axioms requests: $(grep -c '^#print axioms' ServerFv/Machine.lean)"
echo "lines with sorryAx, ofReduceBool, trustCompiler: $(grep -c 'sorryAx\|ofReduceBool\|trustCompiler' /tmp/machfix_fresh.txt)"
echo "axiom sets seen:"; grep -o "depends on axioms: .*\|does not depend on any axioms" /tmp/machfix_fresh.txt | sort | uniq -c
echo "errors: $(grep -c ': error' /tmp/machfix_fresh.txt)"
echo "every axiom line:"; grep "axioms\|does not depend" /tmp/machfix_fresh.txt
rm -f /tmp/machfix_fresh.txt
echo "== word scan of source"; grep -nE '\bsorry\b|\badmit\b|native_decide|^axiom|^unsafe|^partial|ex''ploit' ServerFv/Machine.lean; echo "scan done"
echo "== traces"; lake env lean checks/machine_traces.lean 2>&1 | sed -e 's/^info: //' ; echo "traces rc=${PIPESTATUS[0]}"
echo "== mutants"; python3 checks/machine_mutants.py; mut_rc=$?; echo "mutants rc=$mut_rc"
echo "== end of machine_all"
exit "$mut_rc"
