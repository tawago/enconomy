import Popfv2.Rule

/-!
# Popfv2.Silence — RS, silence is rejected   (fv/v2/spec.md, section 6, "Rule")

With `FLOOR ≥ 1`:
* if the filtered window is all zero, the v2 rule fails (`silent_rejected`);
* digital silence (the recording is zero over the filter's whole span) gives a zero filtered
  window, so it fails too (`pass_silence`), at every lag: no self arrival, no partner pass;
* a zero template energy (`cn2 = 0`, e.g. all-128 templates) fails for every recording.

This flips v1's `Bar.partner_silence_accepts` and `Bar.self_silence_accepts`.
The mutant `silence_passes_without_floor` is the v1 hole again, once the floor is dropped.

What it does not give: that quiet sound fails. With `FLOOR = 1`, a nonzero template and taps that
don't sum to 0 (the real ones sum to 3 or 1), a constant offset of one step passes the floor and is
judged by the ratio test alone (spec K11). A higher floor could reject it.
-/

set_option linter.style.whitespace false
set_option linter.style.longLine false
set_option linter.style.header false

namespace Popfv2

open Finset

theorem energy_eq_zero (n : ℕ) (y : ℕ → ℤ) (hy : ∀ m < n, y m = 0) : energy n y = 0 := by
  unfold energy
  exact Finset.sum_eq_zero fun m hm => by rw [hy m (Finset.mem_range.mp hm)]; ring

/-- A recording that is zero over the filter's span gives a zero filtered window. -/
theorem filt_eq_zero (h : ℕ → ℤ) (T n : ℕ) (w : ℕ → ℤ) (hw : ∀ i < n + T - 1, w i = 0) :
    ∀ m < n, filt h T w m = 0 := by
  intro m hm
  unfold filt
  exact Finset.sum_eq_zero fun t ht => by
    have := Finset.mem_range.mp ht
    rw [hw (m + t) (by omega)]; ring

/-- **RS.** A zero filtered window fails the v2 rule. -/
theorem silent_rejected (BAR FLOOR : ℤ) (n : ℕ) (ci cq y : ℕ → ℤ) (hF : 1 ≤ FLOOR)
    (hy : ∀ m < n, y m = 0) : ¬ PassY BAR FLOOR n ci cq y := by
  rintro ⟨hfl, -⟩
  unfold Floor at hfl
  rw [energy_eq_zero n y hy, zero_mul] at hfl
  omega

/-- **RS.** A zero template energy fails the v2 rule, for every recording. -/
theorem zero_template_rejected (BAR FLOOR : ℤ) (n : ℕ) (ci cq y : ℕ → ℤ) (hF : 1 ≤ FLOOR)
    (hc : cn2 n ci cq = 0) : ¬ PassY BAR FLOOR n ci cq y := by
  rintro ⟨hfl, -⟩
  unfold Floor at hfl
  rw [hc, mul_zero] at hfl
  omega

/-- **RS** on the recording: digital silence over the filter's span fails the v2 rule. -/
theorem pass_silence (h : ℕ → ℤ) (T n : ℕ) (BAR FLOOR : ℤ) (ci cq w : ℕ → ℤ) (hF : 1 ≤ FLOOR)
    (hw : ∀ i < n + T - 1, w i = 0) : ¬ Pass h T n BAR FLOOR ci cq w :=
  silent_rejected BAR FLOOR n ci cq _ hF (filt_eq_zero h T n w hw)

/-- Self side: an all-silent recording has no arrival. -/
theorem no_arrival_in_silence (h : ℕ → ℤ) (T n : ℕ) (BAR FLOOR : ℤ) (ci cq : ℕ → ℤ) (K a : ℕ)
    (hF : 1 ≤ FLOOR) : ¬ FirstPass h T n BAR FLOOR ci cq (fun _ => 0) K a := by
  rintro ⟨-, hp, -⟩
  exact pass_silence h T n BAR FLOOR ci cq _ hF (fun _ _ => rfl) hp

/-- Partner side: no lag of an all-silent recording passes. -/
theorem no_partner_pass_in_silence (h : ℕ → ℤ) (T n : ℕ) (BAR FLOOR : ℤ) (ci cq : ℕ → ℤ) (K a : ℕ)
    (hF : 1 ≤ FLOOR) : ¬ PartnerPass h T n BAR FLOOR ci cq (fun _ => 0) K a := by
  rintro ⟨-, hp⟩
  exact pass_silence h T n BAR FLOOR ci cq _ hF (fun _ _ => rfl) hp

/-! ## Not vacuous -/

/-- A real recording passes: one tap of gain 1, one sample `3`, `ci = [1]`, `BAR = FLOOR = 1`. -/
example : Pass (fun _ => 1) 1 1 1 1 (fun _ => 1) (fun _ => 0) (fun _ => 3) := by
  norm_num [Pass, PassY, Floor, Ratio, M, corr, energy, cn2, filt]

/-! ## Mutant -/

/-- Floor dropped: silence passes the ratio test for every `BAR` (v1's
`Bar.partner_silence_accepts`, in this model). -/
theorem silence_passes_without_floor (BAR : ℤ) (n : ℕ) (ci cq : ℕ → ℤ) :
    Ratio BAR n ci cq (fun _ => 0) := by
  unfold Ratio
  rw [energy_eq_zero n _ (fun _ _ => rfl)]
  simp [M, corr]

end Popfv2

#print axioms Popfv2.energy_eq_zero
#print axioms Popfv2.filt_eq_zero
#print axioms Popfv2.silent_rejected
#print axioms Popfv2.zero_template_rejected
#print axioms Popfv2.pass_silence
#print axioms Popfv2.no_arrival_in_silence
#print axioms Popfv2.no_partner_pass_in_silence
#print axioms Popfv2.silence_passes_without_floor
