import Popfv2.Rule

/-!
# Popfv2.Ceiling — RC, the score has a fixed ceiling   (fv/v2/spec.md, section 6, "Rule")

For every recording, `M ≤ E · cn2`. So the score `M / (E · cn2)` is at most 1 whenever
`E · cn2 > 0`. Proof: Cauchy–Schwarz on `I` and on `Q`, added.

It needs two of the fixes:
* fix 1, `I`, `Q`, `E` over the same `y`. Mutant: `raw_breaks_ceiling`.
* fix 3, `cq` inside `cn2`. Mutant: `ciOnly_unbounded`, the score has no ceiling at all.

What it does not give: that noise fails. That depends on `BAR` and the codes (stage 3).
-/

set_option linter.style.whitespace false
set_option linter.style.longLine false
set_option linter.style.header false

namespace Popfv2

open Finset

/-- Cauchy–Schwarz for one template. -/
theorem corr_sq_le (n : ℕ) (c y : ℕ → ℤ) : corr n c y ^ 2 ≤ energy n c * energy n y := by
  unfold corr energy
  exact Finset.sum_mul_sq_le_sq_mul_sq _ _ _

/-- **RC.** For any `y`, `ci`, `cq`: `M ≤ E · cn2`. -/
theorem ceiling (n : ℕ) (ci cq y : ℕ → ℤ) : M n ci cq y ≤ energy n y * cn2 n ci cq := by
  unfold M cn2
  nlinarith [corr_sq_le n ci y, corr_sq_le n cq y]

/-- What the ceiling means for `BAR`. With a floor of 1 or more, the v2 rule passes nothing unless
`BAR ≥ 1`. -/
theorem pass_needs_bar_ge_one (BAR FLOOR : ℤ) (n : ℕ) (ci cq y : ℕ → ℤ) (hF : 1 ≤ FLOOR)
    (h : PassY BAR FLOOR n ci cq y) : 1 ≤ BAR := by
  obtain ⟨hfl, hr⟩ := h
  unfold Floor at hfl
  unfold Ratio at hr
  have hc := ceiling n ci cq y
  have hM : 0 ≤ M n ci cq y := by unfold M; positivity
  by_contra hB
  have : BAR * M n ci cq y ≤ 0 := by nlinarith
  linarith

/-- A pass, in cross-multiplied form: `0 < E·cn2` and `E·cn2 ≤ BAR·M` and `M ≤ E·cn2`.
Read as reals, the score `M / (E·cn2)` is at least `1 / BAR` and at most 1. -/
theorem pass_score_bounds (BAR FLOOR : ℤ) (n : ℕ) (ci cq y : ℕ → ℤ) (hF : 1 ≤ FLOOR)
    (h : PassY BAR FLOOR n ci cq y) :
    0 < energy n y * cn2 n ci cq ∧ energy n y * cn2 n ci cq ≤ BAR * M n ci cq y ∧
      M n ci cq y ≤ energy n y * cn2 n ci cq :=
  ⟨lt_of_lt_of_le (by omega) h.1, h.2, ceiling n ci cq y⟩

/-! ## Not vacuous -/

/-- The ceiling is reached: `y = 3 · ci` gives `M = E · cn2`. -/
example : M 1 (fun _ => 1) (fun _ => 0) (fun _ => 3) = energy 1 (fun _ => 3) * cn2 1 (fun _ => 1) (fun _ => 0) := by
  norm_num [M, corr, energy, cn2]

/-- Something passes the v2 rule: `BAR = FLOOR = 1`, one sample. -/
example : PassY 1 1 1 (fun _ => 1) (fun _ => 0) (fun _ => 3) := by
  norm_num [PassY, Floor, Ratio, M, corr, energy, cn2]

/-! ## Mutants -/

/-- Fix 3 out: with `cn2 = Σ ci²` the score has no ceiling. For any `K` there is a recording
with `M > K · E · cn2`: `ci = [1, 0]`, `cq = [0, 2K]`, `y = [1, 1]`. -/
theorem ciOnly_unbounded (K : ℤ) :
    K * (energy 2 (fun _ => 1) * cn2CiOnly 2 (fun m => if m = 0 then 1 else 0)) <
      M 2 (fun m => if m = 0 then 1 else 0) (fun m => if m = 0 then 0 else 2 * K) (fun _ => 1) := by
  norm_num [M, corr, energy, cn2CiOnly, Finset.sum_range_succ]
  nlinarith [sq_nonneg (2 * K - 1)]

/-- Fix 1 out: match on the raw signal, energy on the filtered one. Taps `[1, -1]`, recording
`[2, 1, 2]`, `ci = [1, 1]`: filtered `y = [1, -1]`, `E · cn2 = 4`, raw match `M = 9 > 4`. -/
theorem raw_breaks_ceiling :
    energy 2 (filt (fun t => if t = 0 then 1 else -1) 2 (fun m => if m = 1 then 1 else 2)) *
        cn2 2 (fun _ => 1) (fun _ => 0) <
      M 2 (fun _ => 1) (fun _ => 0) (fun m => if m = 1 then 1 else 2) := by
  norm_num [M, corr, energy, cn2, filt, Finset.sum_range_succ]

end Popfv2

#print axioms Popfv2.corr_sq_le
#print axioms Popfv2.ceiling
#print axioms Popfv2.pass_needs_bar_ge_one
#print axioms Popfv2.pass_score_bounds
#print axioms Popfv2.ciOnly_unbounded
#print axioms Popfv2.raw_breaks_ceiling
