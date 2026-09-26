#!/bin/bash
# prove (fresh process, /usr/bin/time -l) + verify (fresh) + in-process bench, keys already set up.
# Usage: ./bench_popt2.sh <circuit> <input-stem>
cd "$(dirname "$0")"
H=$(cd .. && pwd)/tools/heavy.sh
c=$1; s=$2
mkdir -p out/popt2
$H prove-$c /usr/bin/time -l ./oa2zk.sh prove $c inputs/$s.input.json out/popt2/bench_$s.proof 2>&1 | grep -E "RESULT|maximum resident|peak memory|heavy"
$H verify-$c /usr/bin/time -l ./oa2zk.sh verify $c out/popt2/bench_$s.proof inputs/$s.public.json 2>&1 | grep -E "RESULT|maximum resident|heavy"
$H bench-$c ./oa2zk.sh bench $c inputs/$s.input.json inputs/$s.public.json 3 2>&1 | grep -E "RESULT|heavy"
ls -la out/popt2/bench_$s.proof | awk '{print "proof_file_bytes", $5}'
