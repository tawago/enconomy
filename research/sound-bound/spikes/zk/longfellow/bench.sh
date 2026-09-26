#!/bin/bash
# Timing runs (single process at a time). Run under tools/heavy.sh:
#   ../tools/heavy.sh lf-bench ./bench.sh
cd "$(dirname "$0")"
PY=${PY:-../../../../proximity-echo/.venv/bin/python3}
B=../vendor/longfellow-zk/clang-build-release
C=out/sbzk1.circuit; d=out/bench; $PY prep.py ../fixtures/180ca04b.json $d >/dev/null
echo "load: $(sysctl -n vm.loadavg)"
for i in 1 2 3 4 5; do /usr/bin/time -l ./build/sbzk prove $C $d/witness.txt $d/proof.bin 2>&1 | grep -E "^prove|maximum resident"; done
for i in 1 2 3 4 5; do /usr/bin/time -l ./build/sbzk verify $C $d/public.txt $d/proof.bin 2>&1 | grep -E "^verify|maximum resident"; done
echo "load: $(sysctl -n vm.loadavg)"
echo "--- vendor, same session"
/usr/bin/time -l $B/circuits/tests/anoncred/small_test --benchmark_filter=BM_AnonCred --benchmark_min_time=5x 2>&1 | grep -E "^BM_|maximum resident|Compiled|depth"
$B/circuits/ecdsa/verify_test --benchmark_filter='BM_ECDSAZK(Prover|Verifier)/1' --benchmark_min_time=5x 2>&1 | grep -E "^BM_"
$B/circuits/ecdsa/verify_test --gtest_filter='ECDSA.Size' 2>&1 | grep -E "depth|Compiled"
echo "load: $(sysctl -n vm.loadavg)"
