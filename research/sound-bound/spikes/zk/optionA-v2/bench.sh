#!/bin/bash
# setup + prove (fresh process, /usr/bin/time -l) + verify (fresh) + in-process bench, for one circuit.
# Usage: ./bench.sh <circuit> <input-stem>   (inputs/<stem>.input.json / .public.json)
cd "$(dirname "$0")"
H=../tools/heavy.sh
c=$1; s=$2
$H setup-$c /usr/bin/time -l ./oa2zk.sh setup $c 2>&1 | grep -E "RESULT|maximum resident|heavy"
$H prove-$c /usr/bin/time -l ./oa2zk.sh prove $c inputs/$s.input.json out/$s.proof 2>&1 | grep -E "RESULT|maximum resident|peak memory|heavy"
$H verify-$c /usr/bin/time -l ./oa2zk.sh verify $c out/$s.proof inputs/$s.public.json 2>&1 | grep -E "RESULT|maximum resident|heavy"
$H bench-$c ./oa2zk.sh bench $c inputs/$s.input.json inputs/$s.public.json 3 2>&1 | grep -E "RESULT|heavy"
ls -la out/$s.proof | awk '{print "proof_file_bytes", $5}'
