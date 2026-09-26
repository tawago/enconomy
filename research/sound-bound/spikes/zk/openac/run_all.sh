#!/bin/bash
# End-to-end: inputs -> compile -> build -> setup -> tests -> bench. Heavy steps go through tools/heavy.sh.
# Prereqs (once): vendor/zkID cloned at b395e09c, `yarn install` in vendor/zkID/wallet-unit-poc/circom,
# circom 2.2.3 at vendor/bin/circom, Homebrew gmp 6.3 (see fix_gmp.sh).
set -e
cd "$(dirname "$0")"
H=../tools/heavy.sh
PY=../enclave/.venv/bin/python
for f in ../fixtures/*.json; do $PY prep_inputs.py $(basename $f .json) > /dev/null; done
for t in half swap nonce badsig issuer expired holder; do $PY prep_inputs.py 180ca04b --tamper $t > /dev/null; done
$PY prep_inputs.py 180ca04b --variant pair_v2 > /dev/null
$PY prep_inputs.py 180ca04b --variant pair_v2 --tamper holder > /dev/null
for v in half_v1 half_v2; do for r in A B; do $PY prep_inputs.py 180ca04b --variant $v --role $r > /dev/null; done; done
$PY prep_inputs.py 180ca04b --variant half_v2 --tamper holder > /dev/null
for c in sb_pair_v1 sb_pair_v2 sb_half_v1 sb_half_v2; do
  [ -f build/$c/$c.r1cs ] || $H compile-$c ./compile.sh $c
done
(cd prover && CARGO_TARGET_DIR=../../vendor/target $H sbzk-build cargo build --release)
./fix_gmp.sh   # first build pulls GMP 6.2.1 (x18 bug on Apple Silicon); swap and relink
(cd prover && CARGO_TARGET_DIR=../../vendor/target $H sbzk-build cargo build --release)
for c in sb_pair_v1 sb_pair_v2 sb_half_v1 sb_half_v2; do
  [ -f keys/$c.vk ] || $H setup-$c ./sbzk.sh setup $c
done
$H sbzk-check python3 run_tests.py check
$H sbzk-proofs python3 run_tests.py proofs
for c in pair_v1 pair_v2 half_v1_A half_v2_A; do n=sb_${c%_A}
  $H bench-$n /usr/bin/time -l ./sbzk.sh bench $n inputs/180ca04b_$c.input.json inputs/180ca04b_$c.public.json 5 2>&1 | grep -E "RESULT|maximum resident"
done
