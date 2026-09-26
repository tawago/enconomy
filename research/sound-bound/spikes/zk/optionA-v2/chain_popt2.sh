#!/bin/bash
# prover build + setup for the POPT v2 circuits (run after the compiles). Every heavy step via ../tools/heavy.sh.
cd "$(dirname "$0")"
H=$(cd .. && pwd)/tools/heavy.sh
(cd prover && CARGO_TARGET_DIR=../../vendor/target $H oa2zk-build-popt2 cargo build --release) > logs/prover_build_popt2.log 2>&1
./fix_gmp.sh >> logs/prover_build_popt2.log 2>&1
(cd prover && CARGO_TARGET_DIR=../../vendor/target $H oa2zk-build-popt2b cargo build --release) >> logs/prover_build_popt2.log 2>&1
for c in oa2t_pair oa2t_s48 oa2t_s44; do
  $H setup-$c /usr/bin/time -l ./oa2zk.sh setup $c > logs/setup_$c.log 2>&1
done
echo done > logs/chain_popt2.done
