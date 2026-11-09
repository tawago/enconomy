import ProtoFv.Examples

/-! Prints the axioms of every main theorem. Allowed: `propext`, `Classical.choice`,
`Quot.sound`. The build log must show no `sorryAx` and no `Lean.ofReduceBool`. -/

namespace ProtoFv
#print axioms fp1_order
#print axioms fp1_recc_clock
#print axioms fp2_opens
#print axioms fp2_salt_after
#print axioms fp2_one_seed
#print axioms fp3_after_txc
#print axioms fp3_no_later
#print axioms fp4_sid
#print axioms fp4_fresh
#print axioms fp5_perm
#print axioms fp5_pair
#print axioms fp5_device
#print axioms fp6_value
#print axioms fp6_result
#print axioms fp6_signed
#print axioms fp6_tamper
#print axioms fp6_pinned
#print axioms fp6_txo_fixed
#print axioms runA_reach
#print axioms freeC_hash
end ProtoFv
