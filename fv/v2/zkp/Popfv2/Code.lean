import Popfv2.Silence

/-!
# Popfv2.Code — the all-128 template   (fix 3, gap 5, fv/v2/spec.md, section 6, "Rule")

Gap 5: a template whose `ci` bytes are all 128 has `ci = 0` once centered. In v1 the template
energy was `Σ ci²` only, so it was 0, and the test `BAR·M ≥ E·0` passed every recording (v1
`WitnessChain.all128_self`, `all128_partner`). `v1_all128_passes` restates that here.

What R2 gives:
* `all128_both_rejected`: if `ci` and `cq` are both all-128, `cn2 = 0` and the floor rejects
  every recording (RS).
* `ci_zero_pass_iff`: if only `ci` is all-128, R2 is a plain correlation test on `cq`. Nothing
  passes for free.

Plainly: the floor (fix 2), not fix 3, is what closes gap 5. `floor_alone_rejects_all128` shows
the floor with v1's ci-only energy already rejects an all-128 `ci`. Fix 3's real job is the
ceiling: without `cq` in `cn2` the score has no upper bound (`Ceiling.ciOnly_unbounded`).
-/

set_option linter.style.whitespace false
set_option linter.style.longLine false
set_option linter.style.header false

namespace Popfv2

open Finset

/-- The all-128 template, centered, is all zero. -/
theorem tf_128 : tf 128 = 0 := by norm_num [tf]

/-- Both templates all-128: `cn2 = 0`, so R2 rejects every recording. -/
theorem all128_both_rejected (BAR FLOOR : ℤ) (n : ℕ) (y : ℕ → ℤ) (hF : 1 ≤ FLOOR) :
    ¬ PassY BAR FLOOR n (fun _ => tf 128) (fun _ => tf 128) y := by
  apply zero_template_rejected BAR FLOOR n _ _ y hF
  unfold cn2
  rw [energy_eq_zero n _ (fun _ _ => tf_128), add_zero]

/-- Only `ci` all-128 (zero on the window): R2 is the correlation test on `cq` alone. -/
theorem ci_zero_pass_iff (BAR FLOOR : ℤ) (n : ℕ) (ci cq y : ℕ → ℤ) (hci : ∀ m < n, ci m = 0) :
    PassY BAR FLOOR n ci cq y ↔
      FLOOR ≤ energy n y * energy n cq ∧ energy n y * energy n cq ≤ BAR * corr n cq y ^ 2 := by
  have hE : energy n ci = 0 := energy_eq_zero n ci hci
  have hI : corr n ci y = 0 :=
    Finset.sum_eq_zero fun m hm => by rw [hci m (Finset.mem_range.mp hm), zero_mul]
  simp [PassY, Floor, Ratio, cn2, M, hE, hI]

/-- Fix 2 alone (floor, v1's ci-only energy) already rejects an all-128 `ci`. -/
theorem floor_alone_rejects_all128 (FLOOR : ℤ) (n : ℕ) (y : ℕ → ℤ) (hF : 1 ≤ FLOOR) :
    ¬ FLOOR ≤ energy n y * cn2CiOnly n (fun _ => tf 128) := by
  unfold cn2CiOnly
  rw [energy_eq_zero n _ (fun _ _ => tf_128), mul_zero]
  omega

/-! ## Not vacuous -/

/-- `ci_zero_pass_iff` has a passing instance: `ci` all-128, `cq = [1]`, `y = [3]`. -/
example : PassY 1 1 1 (fun _ => tf 128) (fun _ => 1) (fun _ => 3) := by
  rw [ci_zero_pass_iff 1 1 1 _ _ _ (fun _ _ => tf_128)]
  norm_num [energy, corr]

/-! ## Mutant -/

/-- The v1 rule (no floor, ci-only energy, any match): an all-128 `ci` passes every recording for
every `BAR ≥ 0`. v1 `WitnessChain.all128_self` in this model. -/
theorem v1_all128_passes (BAR : ℤ) (hB : 0 ≤ BAR) (n : ℕ) (cq y x : ℕ → ℤ) :
    PassV1 BAR n (fun _ => tf 128) cq y x := by
  unfold PassV1 cn2CiOnly
  rw [energy_eq_zero n _ (fun _ _ => tf_128), mul_zero]
  unfold M
  positivity

end Popfv2

#print axioms Popfv2.tf_128
#print axioms Popfv2.all128_both_rejected
#print axioms Popfv2.ci_zero_pass_iff
#print axioms Popfv2.floor_alone_rejects_all128
#print axioms Popfv2.v1_all128_passes
