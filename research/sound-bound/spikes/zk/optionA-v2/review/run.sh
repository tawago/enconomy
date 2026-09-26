#!/bin/bash
# Reviewer runs. Call as: ../tools/heavy.sh review-oa2 review/run.sh   (from optionA-v2/)
cd "$(dirname "$0")/.."
B=./oa2zk.sh; I=review/inputs; O=review/out
PY=../../../../proximity-echo/.venv/bin/python3
echo "== honest per-phone d2 sig, fresh processes"
for n in honest_180ca04b_d2_A_sig 180ca04b_d2_B_sig; do
  /usr/bin/time -l $B prove oa2_d2_sig $I/$n.input.json $O/$n.proof 2>&1 | grep -E "RESULT|maximum resident|peak memory"
  /usr/bin/time -l $B verify oa2_d2_sig $O/$n.proof $I/$n.public.json 2>&1 | grep -E "RESULT|maximum resident"
done
echo "== honest pair"
$B prove oa2_pair $I/honest_pair_180ca04b.input.json $O/honest_pair_180ca04b.proof | grep RESULT
$B verify oa2_pair $O/honest_pair_180ca04b.proof $I/honest_pair_180ca04b.public.json | grep RESULT
echo "== per-phone attacks: check, then forced prove + verify"
for n in X1_path_other_position X1b_children_reordered X2_leaf_minus1_offset_plus1024 X6_templates_partner_order X7_curve_shifted_one_lag; do
  echo "-- $n"
  $B check oa2_d2_sig $I/$n.input.json 2>&1 | grep -E "RESULT|Failed assert" | head -3
  $B prove oa2_d2_sig $I/$n.input.json $O/$n.proof 2>&1 | grep -E "RESULT|Failed assert" | head -3
  $B verify oa2_d2_sig $O/$n.proof $I/$n.public.json 2>&1 | grep RESULT | cut -c1-160
done
echo "== pair attacks"
for n in X3_cross_session_splice X4_fabricated_pair_9afb91c6 X5_role_doubling X8_half_wrap_2p32; do
  echo "-- $n"
  $B check oa2_pair $I/$n.input.json 2>&1 | grep -E "RESULT|Failed assert" | head -3
  $B prove oa2_pair $I/$n.input.json $O/$n.proof 2>&1 | grep -E "RESULT|Failed assert" | head -3
  $B verify oa2_pair $O/$n.proof $I/$n.public.json 2>&1 | grep RESULT | cut -c1-160
done
echo "== end-to-end verifier sketch"
echo "-- 180ca04b honest (A, B, pair)"
$PY review/verify_session.py 180ca04b $O/honest_180ca04b_d2_A_sig.proof $O/180ca04b_d2_B_sig.proof $O/honest_pair_180ca04b.proof
echo "-- 9afb91c6 (200 cm): builder's honest per-phone proofs + X4 fabricated pair proof"
$PY review/verify_session.py 9afb91c6 out/9afb91c6_d2_A_sig.proof out/9afb91c6_d2_B_sig.proof $O/X4_fabricated_pair_9afb91c6.proof
echo "-- 9afb91c6 per-phone A + 180ca04b per-phone B + 180ca04b pair (cross-session)"
$PY review/verify_session.py 9afb91c6 out/9afb91c6_d2_A_sig.proof $O/180ca04b_d2_B_sig.proof $O/honest_pair_180ca04b.proof
echo "-- 180ca04b A used in both roles"
$PY review/verify_session.py 180ca04b $O/honest_180ca04b_d2_A_sig.proof $O/honest_180ca04b_d2_A_sig.proof $O/honest_pair_180ca04b.proof
