import Popfv2.Rule

/-!
# Popfv2.Tone — RT, the filter's gain cancels   (fv/v2/spec.md, section 6, "Rule")

The v1 tone route (`fv/v1/next-version-fixes.md` fix 1, `circuit-cases` gap 2): the match was on
raw samples and the energy on the filtered ones. A 500 Hz tone went through gain 1 on one side
and about 0.14 on the other, and its score was inflated about 1,400 times.

What is proved here:
1. `ratio_scale`: the v2 rule's ratio test does not change when the filtered signal is scaled by any
   integer `g ≠ 0`.
2. `gain_route`: on a signal that the filter scales by `p / q` (`q · y = p · x` on the window),
   The v2 rule's ratio test on `y` is the same test on the raw `x`, with the same `BAR`. The gain is gone.
3. `gain_route_raw` (mutant, fix 1 out): the raw-match test is the raw test with `BAR` multiplied
   by `q² / p²`. A filter gain of `1/7` makes the bar 49 times easier. This is the v1 route.
4. `raw_route_witness`: for every `BAR ≥ 1` a recording the filter sends to a zero match passes
   the raw-match rule and fails the v2 rule. The recording is a DC offset plus a dip, and the taps
   `[1, -1]` have gain 0 at DC.

What this does NOT say: that a 500 Hz tone is rejected. Under the v2 rule a tone is judged by its plain
correlation with the code, which is at most 1 (`Ceiling.ceiling`) and depends on the code and the
phase. Whether it passes depends on `BAR` (stage 3) and is checked by rerunning `circuit-cases`
and real recordings, not here. So the honest statement is "the gain mismatch is gone", not
"the tone is rejected".

Model limit: gain is an exact integer ratio on the window. A real filter also shifts the phase
of a tone and has edge effects at the window ends. Neither is modeled.

The floor part is not scale-free, on purpose: `floor_not_scale_free`.
-/

set_option linter.style.whitespace false
set_option linter.style.longLine false
set_option linter.style.header false

namespace Popfv2

open Finset

/-- A signal scaled by an integer `g`. -/
def scale (g : ℤ) (y : ℕ → ℤ) : ℕ → ℤ := fun m => g * y m

theorem corr_scale (n : ℕ) (c y : ℕ → ℤ) (g : ℤ) : corr n c (scale g y) = g * corr n c y := by
  unfold corr scale
  rw [Finset.mul_sum]
  exact Finset.sum_congr rfl fun _ _ => by ring

theorem energy_scale (n : ℕ) (y : ℕ → ℤ) (g : ℤ) : energy n (scale g y) = g ^ 2 * energy n y := by
  unfold energy scale
  rw [Finset.mul_sum]
  exact Finset.sum_congr rfl fun _ _ => by ring

theorem M_scale (n : ℕ) (ci cq y : ℕ → ℤ) (g : ℤ) : M n ci cq (scale g y) = g ^ 2 * M n ci cq y := by
  unfold M
  rw [corr_scale, corr_scale]
  ring

theorem corr_congr (n : ℕ) (c y y' : ℕ → ℤ) (h : ∀ m < n, y m = y' m) : corr n c y = corr n c y' :=
  Finset.sum_congr rfl fun m hm => by rw [h m (Finset.mem_range.mp hm)]

theorem energy_congr (n : ℕ) (y y' : ℕ → ℤ) (h : ∀ m < n, y m = y' m) : energy n y = energy n y' :=
  Finset.sum_congr rfl fun m hm => by rw [h m (Finset.mem_range.mp hm)]

theorem ratio_congr (BAR : ℤ) (n : ℕ) (ci cq y y' : ℕ → ℤ) (h : ∀ m < n, y m = y' m) :
    Ratio BAR n ci cq y ↔ Ratio BAR n ci cq y' := by
  unfold Ratio M
  rw [energy_congr n y y' h, corr_congr n ci y y' h, corr_congr n cq y y' h]

theorem sq_pos_of_ne {g : ℤ} (hg : g ≠ 0) : 0 < g ^ 2 :=
  lt_of_le_of_ne (sq_nonneg g) (Ne.symm (pow_ne_zero 2 hg))

/-- **RT.** The ratio test is the same for `y` and `g · y`, for any integer `g ≠ 0`. -/
theorem ratio_scale (BAR : ℤ) (n : ℕ) (ci cq y : ℕ → ℤ) (g : ℤ) (hg : g ≠ 0) :
    Ratio BAR n ci cq (scale g y) ↔ Ratio BAR n ci cq y := by
  unfold Ratio
  rw [energy_scale, M_scale,
    show g ^ 2 * energy n y * cn2 n ci cq = g ^ 2 * (energy n y * cn2 n ci cq) by ring,
    show BAR * (g ^ 2 * M n ci cq y) = g ^ 2 * (BAR * M n ci cq y) by ring]
  exact mul_le_mul_iff_of_pos_left (sq_pos_of_ne hg)

/-- **RT, gain route closed.** If the filter scales this signal by `p / q`, the v2 rule's ratio test on
the filtered `y` is the ratio test on the raw `x`, same `BAR`. -/
theorem gain_route (BAR : ℤ) (n : ℕ) (ci cq y x : ℕ → ℤ) (p q : ℤ) (hp : p ≠ 0) (hq : q ≠ 0)
    (hyx : ∀ m < n, q * y m = p * x m) :
    Ratio BAR n ci cq y ↔ Ratio BAR n ci cq x := by
  rw [← ratio_scale BAR n ci cq y q hq, ← ratio_scale BAR n ci cq x p hp]
  exact ratio_congr BAR n ci cq _ _ hyx

/-! ## Mutants: fix 1 out -/

/-- Fix 1 out. On the same signal, the raw-match test is the raw test with `BAR · q² / p²`:
the filter gain `p / q` changes the bar. -/
theorem gain_route_raw (BAR : ℤ) (n : ℕ) (ci cq y x : ℕ → ℤ) (p q : ℤ) (hq : q ≠ 0)
    (hyx : ∀ m < n, q * y m = p * x m) :
    RatioRaw BAR n ci cq y x ↔
      p ^ 2 * energy n x * cn2 n ci cq ≤ BAR * q ^ 2 * M n ci cq x := by
  have hE : q ^ 2 * energy n y = p ^ 2 * energy n x := by
    rw [← energy_scale, ← energy_scale]
    exact energy_congr n _ _ hyx
  unfold RatioRaw
  rw [← mul_le_mul_iff_of_pos_left (sq_pos_of_ne hq),
    show q ^ 2 * (energy n y * cn2 n ci cq) = p ^ 2 * energy n x * cn2 n ci cq by rw [← mul_assoc, hE],
    show q ^ 2 * (BAR * M n ci cq x) = BAR * q ^ 2 * M n ci cq x by ring]

/-- Fix 1 out: for every `BAR ≥ 1` and `FLOOR ≤ 4`, a recording passes the raw-match rule and
fails the v2 rule. Taps `[1, -1]`, recording `[2, 1, 2]`, `ci = [1, 1]`, `cq = 0`. The filtered window is
`[1, -1]`, which has zero match with `ci`. The raw window keeps the DC offset, match 9. -/
theorem raw_route_witness (BAR FLOOR : ℤ) (hB : 1 ≤ BAR) (hF : FLOOR ≤ 4) :
    PassRaw BAR FLOOR 2 (fun _ => 1) (fun _ => 0)
        (filt (fun t => if t = 0 then 1 else -1) 2 (fun m => if m = 1 then 1 else 2))
        (fun m => if m = 1 then 1 else 2) ∧
      ¬ Pass (fun t => if t = 0 then 1 else -1) 2 2 BAR FLOOR (fun _ => 1) (fun _ => 0)
        (fun m => if m = 1 then 1 else 2) := by
  refine ⟨⟨?_, ?_⟩, ?_⟩
  · norm_num [Floor, energy, cn2, filt, Finset.sum_range_succ]; omega
  · norm_num [RatioRaw, M, corr, energy, cn2, filt, Finset.sum_range_succ]; omega
  · norm_num [Pass, PassY, Floor, Ratio, M, corr, energy, cn2, filt, Finset.sum_range_succ]

/-! ## Not vacuous -/

/-- `gain_route` and `gain_route_raw` have instances: gain `1/7` on `[1, 1]`, `ci = [1, 0]`,
`BAR = 1`. The raw-match test passes (2 ≤ 49), the v2 rule fails (2 ≤ 1 is false). -/
example : (∀ m < 2, (7 : ℤ) * (fun _ => (1 : ℤ)) m = 1 * (fun _ => (7 : ℤ)) m) ∧
    RatioRaw 1 2 (fun m => if m = 0 then 1 else 0) (fun _ => 0) (fun _ => 1) (fun _ => 7) ∧
    ¬ Ratio 1 2 (fun m => if m = 0 then 1 else 0) (fun _ => 0) (fun _ => 1) := by
  refine ⟨fun _ _ => by norm_num, ?_, ?_⟩
  · norm_num [RatioRaw, M, corr, energy, cn2, Finset.sum_range_succ]
  · norm_num [Ratio, M, corr, energy, cn2, Finset.sum_range_succ]

/-- The floor is not scale-free: with `FLOOR = 2`, `[1]` fails it and `2 · [1]` passes it. -/
theorem floor_not_scale_free :
    ¬ Floor 2 1 (fun _ => 1) (fun _ => 0) (fun _ => 1) ∧
      Floor 2 1 (fun _ => 1) (fun _ => 0) (scale 2 (fun _ => 1)) := by
  constructor <;> norm_num [Floor, energy, cn2, scale]

end Popfv2

#print axioms Popfv2.corr_scale
#print axioms Popfv2.energy_scale
#print axioms Popfv2.M_scale
#print axioms Popfv2.ratio_congr
#print axioms Popfv2.ratio_scale
#print axioms Popfv2.gain_route
#print axioms Popfv2.gain_route_raw
#print axioms Popfv2.raw_route_witness
#print axioms Popfv2.floor_not_scale_free
