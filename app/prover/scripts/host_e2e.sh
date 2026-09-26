#!/bin/bash
# Host end-to-end on real fixtures: prove + verify (s48, s44), spike verifier cross-check, and refusal of
# tampered / corrupted witnesses. Needs the spike keys (research/.../optionA-v2/keys, gitignored there).
# Heavy (~2 GB, ~1 min): run as research/sound-bound/spikes/zk/tools/heavy.sh prover-e2e scripts/host_e2e.sh
set -e
P=$(cd "$(dirname "$0")/.." && pwd)
ZK=${POP_ZK_SPIKE:-$P/../../research/sound-bound/spikes/zk/optionA-v2}
K=${POP_KEYS:-$ZK/keys}
IN=$ZK/inputs
OUT=${TMPDIR:-/tmp}/pop-prover-e2e; mkdir -p "$OUT"
cd "$P"; cargo build --release -q
B=target/release/popprover
fail=0
expect() { # expect ACCEPT|REJECT <cmd...>
  want=$1; shift
  r=$("$@" 2>&1 | grep RESULT | tail -1); echo "$r"
  case "$r" in *" $want"*) ;; *) echo "  ^ expected $want"; fail=1;; esac
}
/usr/bin/time -l $B e2e $K/oa2t_s48.pk $K/oa2t_s48.vk $IN/popt2_180ca04b_48k_A.input.json $IN/popt2_180ca04b_48k_A.public.json $OUT/s48_A.proof 2>&1 | grep -E "RESULT|real|peak memory"
expect ACCEPT $B verify $K/oa2t_s48.vk $OUT/s48_A.proof $IN/popt2_180ca04b_48k_A.public.json
/usr/bin/time -l $B e2e $K/oa2t_s44.pk $K/oa2t_s44.vk $IN/popt2_180ca04b_mix_B.input.json $IN/popt2_180ca04b_mix_B.public.json $OUT/s44_B.proof 2>&1 | grep -E "RESULT|real|peak memory"
expect ACCEPT $B verify $K/oa2t_s44.vk $OUT/s44_B.proof $IN/popt2_180ca04b_mix_B.public.json
[ -x $ZK/oa2zk.sh ] && expect ACCEPT $ZK/oa2zk.sh verify oa2t_s48 $OUT/s48_A.proof $IN/popt2_180ca04b_48k_A.public.json
expect REJECT $B verify $K/oa2t_s48.vk $OUT/s48_A.proof $IN/popt2_180ca04b_48k_B.public.json
for t in t-half t-nonce t-resign_early t-resign_late; do
  expect REJECT $B check $K/oa2t_s48.pk $IN/popt2_180ca04b_48k_A_$t.input.json
done
expect REJECT $B prove $K/oa2t_s48.pk $IN/popt2_180ca04b_48k_A_t-half.input.json $OUT/bad.proof
expect REJECT $B check $K/oa2t_s48.pk $IN/popt2_180ca04b_48k_sodwide_B.input.json
expect ACCEPT $B corrupt $K/oa2t_s48.pk $IN/popt2_180ca04b_48k_A.input.json 700000
[ $fail = 0 ] && echo "host_e2e: all ok" || { echo "host_e2e: FAILED"; exit 1; }
