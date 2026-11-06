import Popfv.Field

/-!
# Block D: the arrival rule inside `self_side`

Source: `research/worldid/prototypes/optA-noir/noir/oalib/src/lib.nr`, `self_side`, lines 338-434
(deployed variant; the `_opt` functions are not modeled).

Three layers.

1. **Abstract arrival rule** (lines 360-369 and 398-405). The per-lag value `d j` is an opaque field
   element. We prove: the flags `u` are a block of 1s then 0s, the number of 1s `a` is the arrival lag,
   and, when `d j` is the cast of an integer that does not wrap around, the 96-bit checks say exactly
   "`d j ≥ 1` for `j < a`" and "`d a ≤ 0`". Plus the converse (an honest prover passes).
2. **Sign checks**: `v_j` is `(d - 1)`, `-d`, or `0`, depending on the flags.
3. **Signal chain** (lines 353-359, 371-405). Samples, ring buffer, FIR, energy, template energy,
   correlations. Proves that `d j` really is the cast of the integer
   `D j = bigC j - BAR * env2 j`, and that `|D j|` is far below the wraparound point, using only the
   input types (u16 samples, u8 templates) plus the Block C hypothesis that the claimed `ci, cq` equal
   the true correlations.

Modeling choices (also listed in the report):
* arrays of length `K` are modeled as `ℕ → _` with every constraint quantified over `j < K`;
* the sample window `xs[o + i]` is modeled as `x i` (Block B / F fix the offset);
* the loop is unrolled by hand into recurrences (`ringSt`, `EY`, `CNA`), one per mutable variable;
* `w(e)` (line 14) is the identity.

Read this before quoting the main theorem: "loud enough" means the literal integer test
`BAR · match ≥ loudness`. That test is true at `0 ≥ 0`, so a lag with no sound at all counts as loud
enough. Layer 4 machine-checks what this allows: a recording with no beep in it passes, and it picks
the arrival lag. So the theorems say what the circuit enforces. They do NOT say a beep was heard.
-/

set_option linter.style.whitespace false
set_option linter.style.longLine false
set_option linter.style.header false

namespace Popfv
namespace Arrival

open Finset

/-! ## Constants (lib.nr lines 23-39) -/

/-- line 24 -/
def K : ℕ := 193
/-- line 23 -/
def L : ℕ := 12000
/-- line 26 -/
def HM : ℕ := 31
/-- line 27 -/
def NS : ℕ := 12254
/-- line 33 -/
def BAR : ℤ := 4474747

/-- line 36: positions of the 31 nonzero FIR taps. -/
def NZT : Fin 31 → ℕ :=
  ![9, 11, 12, 14, 15, 17, 18, 20, 21, 23, 24, 26, 27, 29, 30, 31, 32, 33, 35, 36, 38, 39, 41, 42, 44,
    45, 47, 48, 50, 51, 53]

/-- lines 37-39: the 31 nonzero FIR taps (Field constants; negative ones are `p - |h|`, i.e. the
cast of a negative integer). -/
def NZH : Fin 31 → ℤ :=
  ![1, 1, 2, 2, 2, 4, -1, 2, -7, -5, -13, -19, -13, -45, 27, 127, 27, -45, -13, -19, -13, -5, -7, 2,
    -1, 4, 2, 2, 2, 1, 1]

/-- The task statement's "sum of |h| = 415": checked. -/
theorem NZH_abs_sum : (∑ t : Fin 31, |NZH t|) = 415 := by
  simp only [Fin.sum_univ_succ, Fin.sum_univ_zero, NZH, Matrix.cons_val_zero, Matrix.cons_val_succ]
  norm_num

theorem NZT_le (t : Fin 31) : NZT t ≤ 53 := by
  fin_cases t <;> simp [NZT]

/-! ## Layer 1: the abstract arrival rule -/

/-- Noir `b as Field` for a `bool`. -/
def bf (b : Bool) : F := if b then 1 else 0

/-- line 403: `e = (if j == 0 { 1 } else { u[j - 1] as Field }) - uj`. -/
def eSel (u : ℕ → Bool) (j : ℕ) : F := (if j = 0 then 1 else bf (u (j - 1))) - bf (u j)

/-- line 404: `v = uj * (d - 1) - e * d`. -/
def vSel (u : ℕ → Bool) (d : F) (j : ℕ) : F := bf (u j) * (d - 1) - eSel u j * d

/-- Every arrival-rule constraint of `self_side`, in source order. `d j` is the field value of
line 401 at lag `j`. -/
structure ArrivalOK (u : ℕ → Bool) (d : ℕ → F) (usum_target : F) : Prop where
  /-- line 361: `assert(!u[K - 1])` -/
  last : (!u (K - 1)) = true
  /-- lines 363-366: `if j > 0 { assert(!u[j] | u[j - 1]) }` -/
  mono : ∀ j, j < K → 0 < j → (!u j || u (j - 1)) = true
  /-- lines 362-369: `usum = Σ u[j] as Field; assert(usum == usum_target)` -/
  usum : (∑ j ∈ range K, bf (u j)) = usum_target
  /-- lines 397-405: for each lag `j < K` (one loop step each), `v.assert_max_bit_size::<96>()` -/
  bits : ∀ j, j < K → fits 96 (vSel u (d j) j)

/-- Number of `true` flags among `u 0, …, u (n-1)`. -/
def cnt (u : ℕ → Bool) (n : ℕ) : ℕ := ∑ j ∈ range n, if u j then 1 else 0

theorem cnt_succ (u : ℕ → Bool) (n : ℕ) : cnt u (n + 1) = cnt u n + if u n then 1 else 0 := by
  unfold cnt; rw [sum_range_succ]

theorem cnt_le (u : ℕ → Bool) (n : ℕ) : cnt u n ≤ n := by
  induction n with
  | zero => simp [cnt]
  | succ n ih => rw [cnt_succ]; split <;> omega

/-- **Induction lemma (1).** If the flags never have a 1 right after a 0 inside the first `n`
positions, then flag `j` is on exactly when `j` is smaller than the number of flags that are on.
In words: the flags are a block of 1s followed by a block of 0s, and the count of 1s marks the
boundary. -/
theorem prefix_iff (u : ℕ → Bool) :
    ∀ n, (∀ j, j < n → 0 < j → u j = true → u (j - 1) = true) →
      ∀ j, j < n → (u j = true ↔ j < cnt u n) := by
  intro n
  induction n with
  | zero => intro _ j hj; omega
  | succ n ih =>
    intro hmono
    have ih' := ih (fun j hj h0 hu => hmono j (by omega) h0 hu)
    rw [cnt_succ]
    cases hun : u n with
    | false =>
      intro j hj
      simp only [Bool.false_eq_true, ↓reduceIte, add_zero]
      rcases Nat.lt_or_ge j n with hjn | hjn
      · exact ih' j hjn
      · have : j = n := by omega
        subst this
        have := cnt_le u j
        simp only [hun, Bool.false_eq_true, false_iff]; omega
    | true =>
      -- all flags up to n are on, so cnt u n = n
      have hcn : cnt u n = n := by
        rcases Nat.eq_zero_or_pos n with h0 | hpos
        · subst h0; simp [cnt]
        · have hprev := hmono n (by omega) hpos hun
          have := (ih' (n - 1) (by omega)).mp hprev
          have := cnt_le u n
          omega
      intro j hj
      simp only [↓reduceIte, hcn]
      rcases Nat.lt_or_ge j n with hjn | hjn
      · have := ih' j hjn; rw [hcn] at this; simp only [this]; omega
      · have : j = n := by omega
        subst this; simp [hun]

theorem cnt_cast (u : ℕ → Bool) (n : ℕ) : ((cnt u n : ℕ) : F) = ∑ j ∈ range n, bf (u j) := by
  simp only [cnt, Nat.cast_sum]
  refine sum_congr rfl (fun j _ => ?_)
  cases u j <;> simp [bf]

/-- The flags define one arrival lag `a < K`, it equals `usum_target`, and the flags are on exactly
before it. -/
theorem arrival_index {u : ℕ → Bool} {d : ℕ → F} {ut : F} (h : ArrivalOK u d ut) :
    ∃ a, a < K ∧ (a : F) = ut ∧ ∀ j, j < K → (u j = true ↔ j < a) := by
  have hm : ∀ j, j < K → 0 < j → u j = true → u (j - 1) = true := by
    intro j hj h0 hu
    have := h.mono j hj h0
    simpa [hu] using this
  have hp := prefix_iff u K hm
  refine ⟨cnt u K, ?_, ?_, hp⟩
  · have hle := cnt_le u K
    have hlast : u (K - 1) = false := by simpa using h.last
    by_contra hc
    have hK : cnt u K = K := by omega
    have := (hp (K - 1) (by decide)).mpr (by rw [hK]; decide)
    rw [hlast] at this; exact Bool.false_ne_true this
  · rw [cnt_cast]; exact h.usum

/-! ## Layer 2: what each 96-bit check says -/

/-- Before the arrival (`u j = 1`, previous flag 1 or `j = 0`): `v = d - 1`. -/
theorem vSel_before (u : ℕ → Bool) (D : ℤ) (j : ℕ) (hu : u j = true)
    (hprev : j = 0 ∨ u (j - 1) = true) : vSel u (D : F) j = ((D - 1 : ℤ) : F) := by
  unfold vSel eSel
  rcases hprev with h0 | hp
  · subst h0; simp [bf, hu]
  · by_cases h0 : j = 0
    · subst h0; simp [bf, hu]
    · simp [bf, hu, hp, h0]

/-- At the arrival (`u j = 0`, previous flag 1 or `j = 0`): `v = -d`. -/
theorem vSel_at (u : ℕ → Bool) (D : ℤ) (j : ℕ) (hu : u j = false)
    (hprev : j = 0 ∨ u (j - 1) = true) : vSel u (D : F) j = ((-D : ℤ) : F) := by
  unfold vSel eSel
  rcases hprev with h0 | hp
  · subst h0; simp [bf, hu]
  · by_cases h0 : j = 0
    · subst h0; simp [bf, hu]
    · simp [bf, hu, hp, h0]

/-- After the arrival (`u j = 0`, previous flag 0): `v = 0`, no check. -/
theorem vSel_after (u : ℕ → Bool) (d : F) (j : ℕ) (hu : u j = false) (h0 : j ≠ 0)
    (hp : u (j - 1) = false) : vSel u d j = 0 := by
  unfold vSel eSel
  simp [bf, hu, hp, h0]

theorem abs_sub_one_lt {D : ℤ} (h : |D| < 2^251) : |D - 1| < 2^252 := by
  have := abs_sub D 1
  have h2 : (2:ℤ)^252 = 2 * 2^251 := by norm_num
  have h3 : (1:ℤ) ≤ 2^251 := by norm_num
  simp at this; linarith

theorem abs_neg_lt {D : ℤ} (h : |D| < 2^251) : |-D| < 2^252 := by
  rw [abs_neg]; have : (2:ℤ)^251 < 2^252 := by norm_num
  linarith

/-- **Arrival rule, soundness (2).** If every arrival constraint of the circuit holds, and each
per-lag value `d j` is the field image of a true integer `D j` that is not astronomically large
(`|D j| < 2^251`, far below the wraparound point), then there is one lag `a < K`, equal to the
public `usum_target`, such that `D j ≥ 1` (score below the bar) at every lag before `a`, and
`D a ≤ 0` at `a`. So `a` is the first lag passing the literal test `D ≤ 0`. Careful: `D a = 0` also
covers the empty case of no sound and no match (`0 ≥ 0`), so this does not say a beep is there. See
Layer 4. -/
theorem arrival_correct {u : ℕ → Bool} {d : ℕ → F} {ut : F} (D : ℕ → ℤ)
    (hd : ∀ j, j < K → d j = (D j : F)) (hD : ∀ j, j < K → |D j| < 2^251)
    (h : ArrivalOK u d ut) :
    ∃ a, a < K ∧ (a : F) = ut ∧ (∀ j, j < K → (u j = true ↔ j < a)) ∧
      (∀ j, j < a → 1 ≤ D j) ∧ D a ≤ 0 := by
  obtain ⟨a, haK, hut, hiff⟩ := arrival_index h
  refine ⟨a, haK, hut, hiff, ?_, ?_⟩
  · intro j hja
    have hjK : j < K := by omega
    have hb := h.bits j hjK
    have hu : u j = true := (hiff j hjK).mpr hja
    have hprev : j = 0 ∨ u (j - 1) = true := by
      rcases Nat.eq_zero_or_pos j with h0 | hpos
      · exact Or.inl h0
      · exact Or.inr ((hiff (j - 1) (by omega)).mpr (by omega))
    rw [hd j hjK, vSel_before u (D j) j hu hprev] at hb
    have := nonneg_of_fits_intCast (k := 96) (m := 252) (by norm_num) (by norm_num)
      (abs_sub_one_lt (hD j hjK)) hb
    omega
  · have hb := h.bits a haK
    have hu : u a = false := by
      cases hh : u a with
      | false => rfl
      | true => have := (hiff a haK).mp hh; omega
    have hprev : a = 0 ∨ u (a - 1) = true := by
      rcases Nat.eq_zero_or_pos a with h0 | hpos
      · exact Or.inl h0
      · exact Or.inr ((hiff (a - 1) (by omega)).mpr (by omega))
    rw [hd a haK, vSel_at u (D a) a hu hprev] at hb
    have := nonneg_of_fits_intCast (k := 96) (m := 252) (by norm_num) (by norm_num)
      (abs_neg_lt (hD a haK)) hb
    omega

theorem cnt_lt (a n : ℕ) : cnt (fun j => decide (j < a)) n = min n a := by
  induction n with
  | zero => simp [cnt]
  | succ n ih =>
    rw [cnt_succ, ih]
    by_cases h : n < a <;> simp [h] <;> omega

theorem fits_zero (k : ℕ) : fits k (0 : F) := by
  simp [fits, ZMod.val_zero]

/-- **Arrival rule, completeness.** An honest prover passes: if `a < K`, `D j ≥ 1` before `a`,
`D a ≤ 0`, and every `D j` lies in `(-2^96, 2^96]`, then setting the flags to "1 before `a`, 0
from `a` on" and `usum_target = a` satisfies every arrival constraint. -/
theorem arrival_complete {d : ℕ → F} (D : ℕ → ℤ) (hd : ∀ j, j < K → d j = (D j : F))
    (hD : ∀ j, j < K → -2^96 < D j ∧ D j ≤ 2^96) (a : ℕ) (ha : a < K)
    (hbefore : ∀ j, j < a → 1 ≤ D j) (hat : D a ≤ 0) :
    ArrivalOK (fun j => decide (j < a)) d (a : F) where
  last := by
    have : ¬ (K - 1 < a) := by simp only [K] at ha ⊢; omega
    simpa using this
  mono := by intro j _ _; simp; omega
  usum := by
    rw [← cnt_cast, cnt_lt]; congr 1; simp [K] at ha ⊢; omega
  bits := by
    intro j hj
    rw [hd j hj]
    obtain ⟨hlo, hhi⟩ := hD j hj
    rcases lt_trichotomy j a with hja | hja | hja
    · rw [vSel_before _ (D j) j (by simpa using hja)
        (by rcases Nat.eq_zero_or_pos j with h0 | _ ; exact Or.inl h0; right; simp; omega)]
      have h1 := hbefore j hja
      rw [fits_intCast_iff_of_abs (m := 252) (by norm_num) (by norm_num)]
      · constructor <;> linarith
      · rw [abs_lt]; constructor <;> norm_num <;> linarith
    · subst hja
      rw [vSel_at _ (D j) j (by simp)
        (by rcases Nat.eq_zero_or_pos j with h0 | _ ; exact Or.inl h0; right; simp; omega)]
      rw [fits_intCast_iff_of_abs (m := 252) (by norm_num) (by norm_num)]
      · constructor <;> linarith
      · rw [abs_lt]; constructor <;> norm_num <;> linarith
    · rw [vSel_after _ _ j (by simp; omega) (by omega) (by simp; omega)]
      exact fits_zero 96

/-! ## Layer 3a: the signal chain, field side (literal model of lines 353-405) -/

/-- line 382: `wi = xs[o + i] as Field - 32768`. Here `x i` stands for `xs[o + i]`. -/
def wF (x : ℕ → ℕ) (i : ℕ) : F := (x i : F) - 32768

/-- lines 372, 383: the 64-slot `ring` right after the write `ring[i % 64] = wi` of loop step `i`. -/
def ringSt (x : ℕ → ℕ) : ℕ → ℕ → F
  | 0 => Function.update (fun _ => 0) (0 % 64) (wF x 0)
  | i + 1 => Function.update (ringSt x i) ((i + 1) % 64) (wF x (i + 1))

/-- The ring buffer holds the last 64 samples: slot `q % 64` at step `i` is sample `q` whenever
`i - 63 ≤ q ≤ i`. -/
theorem ring_read (x : ℕ → ℕ) : ∀ i q, q ≤ i → i < q + 64 → ringSt x i (q % 64) = wF x q := by
  intro i
  induction i with
  | zero =>
    intro q hq _
    have : q = 0 := by omega
    subst this; simp [ringSt]
  | succ i ih =>
    intro q hq hlt
    by_cases hqi : q = i + 1
    · subst hqi; simp [ringSt]
    · simp only [ringSt]
      rw [Function.update_of_ne (by omega)]
      exact ih q (by omega) (by omega)

/-- lines 384-391, at loop step `i = m + 62`: `y = Σ_t NZH[t] * ring[(m + NZT[t]) % 64]`. -/
def yF (x : ℕ → ℕ) (m : ℕ) : F :=
  ∑ t : Fin 31, ((NZH t : ℤ) : F) * ringSt x (m + 62) ((m + NZT t) % 64)

/-- lines 375, 392-396: `ey` after `m` FIR outputs (`EY[m]`). Line 393 stores `eyf[m] = EY x m`
for `m < K`; after line 396 at step `m`, `ey = EY x (m + 1)`. -/
def EY (x : ℕ → ℕ) : ℕ → F
  | 0 => 0
  | m + 1 => EY x m + yF x m * yF x m

/-- line 138 (`impl ToF for u8`): `tf(c) = c as Field - 128`. -/
def tf (c : ℕ) : F := (c : F) - 128

/-- lines 353-359: `cna` after `n` template samples. -/
def CNA (c : ℕ → ℕ) : ℕ → F
  | 0 => 0
  | n + 1 => CNA c n + tf (c n) * tf (c n)

/-- line 399 at loop step `m = j + L - 1`: `big_c = (ey - eyf[j]) * cna` with `ey = EY[j + L]`. -/
def bigCF (x c_i : ℕ → ℕ) (j : ℕ) : F := (EY x (j + L) - EY x j) * CNA c_i L

/-- line 400: `env2 = ci[j] * ci[j] + cq[j] * cq[j]`. -/
def env2F (ci cq : ℕ → F) (j : ℕ) : F := ci j * ci j + cq j * cq j

/-- line 401: `d = big_c - BAR * env2`. -/
def dF (x c_i : ℕ → ℕ) (ci cq : ℕ → F) (j : ℕ) : F :=
  bigCF x c_i j - ((BAR : ℤ) : F) * env2F ci cq j

/-- Loop coverage (lines 381, 384-385, 397-398): every lag `j < K` is checked, at the loop step
`m = j + L - 1`, which lies inside `i = m + 62 < NS`. -/
theorem loop_covers_lag (j : ℕ) (hj : j < K) :
    (j + L - 1) + 62 < NS ∧ L ≤ (j + L - 1) + 1 ∧ (j + L - 1) + 1 - L = j := by
  simp only [K, L, NS] at *; omega

/-- ... and every checking step lands on a lag `j < K` (so `eyf[j]`, `ci[j]`, `u[j]` are in range). -/
theorem loop_lag_in_range (m : ℕ) (hm : m + 62 < NS) (hL : L ≤ m + 1) : m + 1 - L < K := by
  simp only [K, L, NS] at *; omega

/-! ## Layer 3b: the same quantities over the integers (no wraparound) -/

/-- sample minus 32768, as a true integer -/
def wI (x : ℕ → ℕ) (i : ℕ) : ℤ := (x i : ℤ) - 32768
/-- FIR output `y_m` as a true integer -/
def yI (x : ℕ → ℕ) (m : ℕ) : ℤ := ∑ t : Fin 31, NZH t * wI x (m + NZT t)
/-- recording energy at lag `j`: sum of `y^2` over the `L` outputs `j, …, j + L - 1` -/
def EI (x : ℕ → ℕ) (j : ℕ) : ℤ := ∑ m ∈ Ico j (j + L), yI x m ^ 2
/-- template value in `[-128, 127]` -/
def tfI (c : ℕ) : ℤ := (c : ℤ) - 128
/-- template energy `cn2` -/
def cnaI (c : ℕ → ℕ) : ℤ := ∑ n ∈ range L, tfI (c n) ^ 2
/-- The TRUE correlation of template `c` against the samples at lag `j`. Block C (Freivalds)
is what ties the circuit's claimed `ci[j]`, `cq[j]` to these. -/
def corr (c x : ℕ → ℕ) (j : ℕ) : ℤ := ∑ n ∈ range L, tfI (c n) * wI x (n + j + HM)
/-- loudness: recording energy times template energy -/
def bigC (x c_i : ℕ → ℕ) (j : ℕ) : ℤ := EI x j * cnaI c_i
/-- match: `I^2 + Q^2` -/
def env2 (x c_i c_q : ℕ → ℕ) (j : ℕ) : ℤ := corr c_i x j ^ 2 + corr c_q x j ^ 2
/-- the true integer behind `d` -/
def DI (x c_i c_q : ℕ → ℕ) (j : ℕ) : ℤ := bigC x c_i j - BAR * env2 x c_i c_q j

theorem yF_eq (x : ℕ → ℕ) (m : ℕ) : yF x m = (yI x m : F) := by
  unfold yF yI
  push_cast
  refine sum_congr rfl (fun t _ => ?_)
  rw [ring_read x (m + 62) (m + NZT t) (by have := NZT_le t; omega) (by omega)]
  simp [wF, wI]

theorem EY_eq (x : ℕ → ℕ) : ∀ m, EY x m = ((∑ k ∈ range m, yI x k ^ 2 : ℤ) : F) := by
  intro m
  induction m with
  | zero => simp [EY]
  | succ m ih => rw [EY, ih, yF_eq, sum_range_succ]; push_cast; ring

theorem CNA_eq (c : ℕ → ℕ) : ∀ n, CNA c n = ((∑ k ∈ range n, tfI (c k) ^ 2 : ℤ) : F) := by
  intro n
  induction n with
  | zero => simp [CNA]
  | succ n ih => rw [CNA, ih, sum_range_succ]; simp only [tf, tfI]; push_cast; ring

theorem bigCF_eq (x c_i : ℕ → ℕ) (j : ℕ) : bigCF x c_i j = (bigC x c_i j : F) := by
  unfold bigCF bigC EI cnaI
  rw [EY_eq, EY_eq, CNA_eq, sum_Ico_eq_sub _ (by omega : j ≤ j + L)]
  push_cast; ring

/-- The field value `d` the circuit computes at lag `j` is the image of the true integer `DI j`,
provided the claimed `ci[j]`, `cq[j]` are the true correlations (Block C). -/
theorem dF_eq (x c_i c_q : ℕ → ℕ) (ci cq : ℕ → F) (j : ℕ)
    (hI : ci j = (corr c_i x j : F)) (hQ : cq j = (corr c_q x j : F)) :
    dF x c_i ci cq j = (DI x c_i c_q j : F) := by
  unfold dF env2F DI env2
  rw [bigCF_eq, hI, hQ]
  push_cast; ring

/-! ## Layer 3c: numeric bounds from the input types -/

theorem sq_le_of_abs_le {a b : ℤ} (h : |a| ≤ b) : a ^ 2 ≤ b ^ 2 := by
  have := abs_le.mp h; exact sq_le_sq' this.1 this.2

theorem wI_abs {x : ℕ → ℕ} {i : ℕ} (h : isU16 (x i)) : |wI x i| ≤ 32768 := by
  unfold isU16 at h; norm_num at h; unfold wI
  rw [abs_le]; constructor <;> omega

theorem tfI_abs {c : ℕ} (h : isU8 c) : |tfI c| ≤ 128 := by
  unfold isU8 at h; norm_num at h; unfold tfI
  rw [abs_le]; constructor <;> omega

theorem yI_abs {x : ℕ → ℕ} (hx : ∀ i, i < NS → isU16 (x i)) {m : ℕ} (hm : m + 53 < NS) :
    |yI x m| ≤ 415 * 32768 := by
  unfold yI
  calc |∑ t, NZH t * wI x (m + NZT t)| ≤ ∑ t, |NZH t * wI x (m + NZT t)| := abs_sum_le_sum_abs _ _
    _ ≤ ∑ t : Fin 31, |NZH t| * 32768 := by
        refine sum_le_sum (fun t _ => ?_)
        rw [abs_mul]
        exact mul_le_mul_of_nonneg_left (wI_abs (hx _ (by have := NZT_le t; omega))) (abs_nonneg _)
    _ = 415 * 32768 := by rw [← sum_mul, NZH_abs_sum]

theorem L_int : (L : ℤ) = 12000 := by simp [L]

theorem EI_bounds {x : ℕ → ℕ} (hx : ∀ i, i < NS → isU16 (x i)) {j : ℕ} (hj : j < K) :
    0 ≤ EI x j ∧ EI x j ≤ 12000 * (415 * 32768) ^ 2 := by
  unfold EI
  constructor
  · exact sum_nonneg (fun m _ => sq_nonneg _)
  · calc ∑ m ∈ Ico j (j + L), yI x m ^ 2 ≤ ∑ m ∈ Ico j (j + L), ((415 * 32768 : ℤ)) ^ 2 := by
          refine sum_le_sum (fun m hm => ?_)
          rw [mem_Ico] at hm
          exact sq_le_of_abs_le (yI_abs hx (by simp only [K, L, NS] at hm hj ⊢; omega))
      _ = 12000 * (415 * 32768) ^ 2 := by simp [sum_const, Nat.card_Ico, L]

theorem cnaI_bounds {c : ℕ → ℕ} (hc : ∀ n, n < L → isU8 (c n)) :
    0 ≤ cnaI c ∧ cnaI c ≤ 12000 * 128 ^ 2 := by
  unfold cnaI
  constructor
  · exact sum_nonneg (fun _ _ => sq_nonneg _)
  · calc ∑ n ∈ range L, tfI (c n) ^ 2 ≤ ∑ n ∈ range L, (128 : ℤ) ^ 2 :=
          sum_le_sum (fun n hn => sq_le_of_abs_le (tfI_abs (hc n (mem_range.mp hn))))
      _ = 12000 * 128 ^ 2 := by simp [L]

theorem corr_abs {c x : ℕ → ℕ} (hc : ∀ n, n < L → isU8 (c n)) (hx : ∀ i, i < NS → isU16 (x i))
    {j : ℕ} (hj : j < K) : |corr c x j| ≤ 12000 * (128 * 32768) := by
  unfold corr
  calc |∑ n ∈ range L, tfI (c n) * wI x (n + j + HM)|
        ≤ ∑ n ∈ range L, |tfI (c n) * wI x (n + j + HM)| := abs_sum_le_sum_abs _ _
    _ ≤ ∑ n ∈ range L, (128 * 32768 : ℤ) := by
        refine sum_le_sum (fun n hn => ?_)
        rw [mem_range] at hn
        rw [abs_mul]
        exact mul_le_mul (tfI_abs (hc n hn))
          (wI_abs (hx _ (by simp only [K, L, NS, HM] at hn hj ⊢; omega))) (abs_nonneg _) (by norm_num)
    _ = 12000 * (128 * 32768) := by simp [L]

/-- worst-case loudness: `L · (415 · 32768)^2 · L · 128^2` -/
def BCMAX : ℤ := 12000 * (415 * 32768) ^ 2 * (12000 * 128 ^ 2)
/-- worst-case match: `2 · (L · 128 · 32768)^2` -/
def ENVMAX : ℤ := 2 * (12000 * (128 * 32768)) ^ 2

/-- The numbers: worst-case loudness is below `2^89`, worst-case `BAR · match` below `2^95`.
Both fit under the 96-bit check, with about 1.8 bits of headroom on the `BAR` side. -/
theorem BCMAX_lt : BCMAX < 2 ^ 89 := by norm_num [BCMAX]
theorem BAR_ENVMAX_lt : BAR * ENVMAX < 2 ^ 95 := by norm_num [BAR, ENVMAX]

theorem bigC_bounds {x c_i : ℕ → ℕ} (hx : ∀ i, i < NS → isU16 (x i))
    (hc : ∀ n, n < L → isU8 (c_i n)) {j : ℕ} (hj : j < K) :
    0 ≤ bigC x c_i j ∧ bigC x c_i j ≤ BCMAX := by
  obtain ⟨h1, h2⟩ := EI_bounds hx hj
  obtain ⟨h3, h4⟩ := cnaI_bounds hc
  unfold bigC BCMAX
  exact ⟨mul_nonneg h1 h3, mul_le_mul h2 h4 h3 (by norm_num)⟩

theorem env2_bounds {x c_i c_q : ℕ → ℕ} (hx : ∀ i, i < NS → isU16 (x i))
    (hci : ∀ n, n < L → isU8 (c_i n)) (hcq : ∀ n, n < L → isU8 (c_q n)) {j : ℕ} (hj : j < K) :
    0 ≤ env2 x c_i c_q j ∧ env2 x c_i c_q j ≤ ENVMAX := by
  have h1 := sq_le_of_abs_le (corr_abs hci hx hj)
  have h2 := sq_le_of_abs_le (corr_abs hcq hx hj)
  unfold env2 ENVMAX
  constructor
  · positivity
  · linarith

theorem DI_bounds {x c_i c_q : ℕ → ℕ} (hx : ∀ i, i < NS → isU16 (x i))
    (hci : ∀ n, n < L → isU8 (c_i n)) (hcq : ∀ n, n < L → isU8 (c_q n)) {j : ℕ} (hj : j < K) :
    -(BAR * ENVMAX) ≤ DI x c_i c_q j ∧ DI x c_i c_q j ≤ BCMAX := by
  obtain ⟨h1, h2⟩ := bigC_bounds hx hci hj
  obtain ⟨h3, h4⟩ := env2_bounds hx hci hcq hj
  have hB : (0 : ℤ) ≤ BAR := by norm_num [BAR]
  have h5 : BAR * env2 x c_i c_q j ≤ BAR * ENVMAX := mul_le_mul_of_nonneg_left h4 hB
  have h6 : 0 ≤ BAR * env2 x c_i c_q j := mul_nonneg hB h3
  unfold DI
  constructor <;> linarith

/-- **No wraparound (3).** From the input types alone (samples are u16, templates are u8) and the
Block C fact that `ci, cq` are the true correlations, the true integer `d` at every lag lies in
`(-2^95, 2^89)`: far from the wraparound point, and inside the 96-bit window on both sides. -/
theorem DI_range {x c_i c_q : ℕ → ℕ} (hx : ∀ i, i < NS → isU16 (x i))
    (hci : ∀ n, n < L → isU8 (c_i n)) (hcq : ∀ n, n < L → isU8 (c_q n)) {j : ℕ} (hj : j < K) :
    -2 ^ 95 < DI x c_i c_q j ∧ DI x c_i c_q j < 2 ^ 89 := by
  obtain ⟨h1, h2⟩ := DI_bounds hx hci hcq hj
  have := BCMAX_lt; have := BAR_ENVMAX_lt
  constructor <;> linarith

theorem DI_wrap {x c_i c_q : ℕ → ℕ} (hx : ∀ i, i < NS → isU16 (x i))
    (hci : ∀ n, n < L → isU8 (c_i n)) (hcq : ∀ n, n < L → isU8 (c_q n)) {j : ℕ} (hj : j < K) :
    |DI x c_i c_q j| < 2 ^ 251 := by
  obtain ⟨h1, h2⟩ := DI_range hx hci hcq hj
  rw [abs_lt]; constructor <;> norm_num <;> linarith

theorem DI_96 {x c_i c_q : ℕ → ℕ} (hx : ∀ i, i < NS → isU16 (x i))
    (hci : ∀ n, n < L → isU8 (c_i n)) (hcq : ∀ n, n < L → isU8 (c_q n)) {j : ℕ} (hj : j < K) :
    -2 ^ 96 < DI x c_i c_q j ∧ DI x c_i c_q j ≤ 2 ^ 96 := by
  obtain ⟨h1, h2⟩ := DI_range hx hci hcq hj
  constructor <;> norm_num <;> linarith

/-- **The 96-bit check is exactly an integer comparison.** At every lag, under the input types:
"`d - 1` fits in 96 bits" holds exactly when `BAR · match < loudness` (not loud enough), and
"`-d` fits in 96 bits" holds exactly when `BAR · match ≥ loudness` (loud enough). -/
theorem bit96_is_sign_check {x c_i c_q : ℕ → ℕ} (hx : ∀ i, i < NS → isU16 (x i))
    (hci : ∀ n, n < L → isU8 (c_i n)) (hcq : ∀ n, n < L → isU8 (c_q n)) {j : ℕ} (hj : j < K) :
    (fits 96 ((DI x c_i c_q j - 1 : ℤ) : F) ↔ BAR * env2 x c_i c_q j < bigC x c_i j) ∧
    (fits 96 ((-DI x c_i c_q j : ℤ) : F) ↔ bigC x c_i j ≤ BAR * env2 x c_i c_q j) := by
  obtain ⟨h1, h2⟩ := DI_range hx hci hcq hj
  have hw := DI_wrap hx hci hcq hj
  rw [fits_intCast_iff_of_abs (m := 252) (by norm_num) (by norm_num) (abs_sub_one_lt hw),
    fits_intCast_iff_of_abs (m := 252) (by norm_num) (by norm_num) (abs_neg_lt hw)]
  unfold DI at h1 h2 ⊢
  constructor
  · constructor
    · intro h; linarith [h.1]
    · intro h; constructor <;> norm_num <;> linarith
  · constructor
    · intro h; linarith [h.1]
    · intro h; constructor <;> norm_num <;> linarith

/-! ## Main theorems: the arrival rule over the real signal -/

/-- **`self_side` arrival rule, soundness, end to end.** Assume: samples are u16, both templates
are u8, the claimed correlations `ci, cq` are the true ones (this is what Block C / Freivalds
gives, and it is an explicit hypothesis here), and every arrival constraint of `self_side` holds
(lines 361, 365, 369, 405). Then there is a lag `a < 193`, equal to the public `usum_target`
(`= a_self - p_self + 96` in `phone_core`), such that the score is below the bar at every lag
before `a` (`BAR · match < loudness`) and `BAR · match ≥ loudness` at `a`.
So `a` is the first lag passing that literal integer test. This is NOT "the first lag where a beep
is heard": `0 ≥ 0` passes, so a lag with zero energy and zero match qualifies, and
`click_picks_any_lag` shows a beep-free recording can use this to land on any lag. -/
theorem self_side_arrival_sound {x c_i c_q : ℕ → ℕ} {ci cq : ℕ → F} {u : ℕ → Bool} {ut : F}
    (hx : ∀ i, i < NS → isU16 (x i))
    (hci_t : ∀ n, n < L → isU8 (c_i n)) (hcq_t : ∀ n, n < L → isU8 (c_q n))
    (hI : ∀ j, j < K → ci j = (corr c_i x j : F)) (hQ : ∀ j, j < K → cq j = (corr c_q x j : F))
    (h : ArrivalOK u (dF x c_i ci cq) ut) :
    ∃ a, a < K ∧ (a : F) = ut ∧ (∀ j, j < K → (u j = true ↔ j < a)) ∧
      (∀ j, j < a → BAR * env2 x c_i c_q j < bigC x c_i j) ∧
      bigC x c_i a ≤ BAR * env2 x c_i c_q a := by
  obtain ⟨a, haK, hut, hiff, hb, hat⟩ := arrival_correct (DI x c_i c_q)
    (fun j hj => dF_eq x c_i c_q ci cq j (hI j hj) (hQ j hj))
    (fun j hj => DI_wrap hx hci_t hcq_t hj) h
  refine ⟨a, haK, hut, hiff, fun j hj => ?_, ?_⟩
  · have := hb j hj; unfold DI at this; linarith
  · unfold DI at hat; linarith

/-- **`self_side` arrival rule, completeness, end to end.** An honest phone gets through: under
the same input types and true correlations, if `a < 193` is the first lag where
`BAR · match ≥ loudness`, then the flags "1 before `a`, 0 from `a` on" with `usum_target = a`
satisfy every arrival constraint. -/
theorem self_side_arrival_complete {x c_i c_q : ℕ → ℕ} {ci cq : ℕ → F}
    (hx : ∀ i, i < NS → isU16 (x i))
    (hci_t : ∀ n, n < L → isU8 (c_i n)) (hcq_t : ∀ n, n < L → isU8 (c_q n))
    (hI : ∀ j, j < K → ci j = (corr c_i x j : F)) (hQ : ∀ j, j < K → cq j = (corr c_q x j : F))
    (a : ℕ) (ha : a < K) (hbefore : ∀ j, j < a → BAR * env2 x c_i c_q j < bigC x c_i j)
    (hat : bigC x c_i a ≤ BAR * env2 x c_i c_q a) :
    ArrivalOK (fun j => decide (j < a)) (dF x c_i ci cq) (a : F) :=
  arrival_complete (DI x c_i c_q) (fun j hj => dF_eq x c_i c_q ci cq j (hI j hj) (hQ j hj))
    (fun j hj => DI_96 hx hci_t hcq_t hj) a ha
    (fun j hj => by have := hbefore j hj; unfold DI; linarith)
    (by unfold DI; linarith)

/-! ## Layer 4: what "loud enough" really covers (machine-checked witnesses)

These also show the main hypotheses can all be met together, so the main theorems are not vacuous.

* `silence_passes`: silence, any templates, arrival 0.
* `click_picks_any_lag`: one sample off by one, arrival wherever the click puts it.
* `flat_template_any_recording`: a silent template passes any recording at lag 0.
* `dc_strict_pass`: strict pass with real energy and real match, which the proposed floor does not stop.

Each is a witness for the arrival rule (Block D) with true correlations. The rest of the circuit
(signature, Merkle, Freivalds) was not run on them. -/

/-- digital silence: every sample is int16 0, stored as 32768 -/
def silent : ℕ → ℕ := fun _ => 32768
/-- silence except for sample `q`, which is one step above zero -/
def clickAt (q : ℕ) : ℕ → ℕ := fun i => if i = q then 32769 else 32768
/-- constant int16 1 -/
def dcOne : ℕ → ℕ := fun _ => 32769

theorem wI_silent (i : ℕ) : wI silent i = 0 := by simp [wI, silent]
theorem wI_dc (i : ℕ) : wI dcOne i = 1 := by unfold wI dcOne; norm_num
theorem wI_click (q i : ℕ) : wI (clickAt q) i = if i = q then 1 else 0 := by
  unfold wI clickAt; split <;> simp

theorem silent_u16 (i : ℕ) : isU16 (silent i) := by unfold isU16 silent; norm_num
theorem dc_u16 (i : ℕ) : isU16 (dcOne i) := by unfold isU16 dcOne; norm_num
theorem click_u16 (q i : ℕ) : isU16 (clickAt q i) := by
  unfold isU16 clickAt; split <;> norm_num

theorem NZT_ge (t : Fin 31) : 9 ≤ NZT t := by
  fin_cases t <;> simp [NZT]

theorem yI_click_zero {q m : ℕ} (h : q < m + 9) : yI (clickAt q) m = 0 := by
  unfold yI
  refine sum_eq_zero (fun t _ => ?_)
  have := NZT_ge t
  rw [wI_click, if_neg (by omega), mul_zero]

theorem yI_click_tap (m s : ℕ) :
    yI (clickAt (m + s)) m = ∑ t : Fin 31, NZH t * (if NZT t = s then 1 else 0) := by
  unfold yI
  refine sum_congr rfl (fun t _ => ?_)
  rw [wI_click]; simp

theorem tap9 : (∑ t : Fin 31, NZH t * (if NZT t = 9 then 1 else 0)) = (1 : ℤ) := by
  simp only [Fin.sum_univ_succ, Fin.sum_univ_zero, NZH, NZT, Matrix.cons_val_zero, Matrix.cons_val_succ]
  norm_num

theorem tap31 : (∑ t : Fin 31, NZH t * (if NZT t = 31 then 1 else 0)) = (127 : ℤ) := by
  simp only [Fin.sum_univ_succ, Fin.sum_univ_zero, NZH, NZT, Matrix.cons_val_zero, Matrix.cons_val_succ]
  norm_num

theorem EI_ge_sq (x : ℕ → ℕ) {j m : ℕ} (h1 : j ≤ m) (h2 : m < j + L) : yI x m ^ 2 ≤ EI x j := by
  unfold EI
  exact single_le_sum (f := fun m => yI x m ^ 2) (fun _ _ => sq_nonneg _) (mem_Ico.2 ⟨h1, h2⟩)

theorem corr_click_zero (c : ℕ → ℕ) {q j : ℕ} (h : q < j + HM) : corr c (clickAt q) j = 0 := by
  unfold corr
  refine sum_eq_zero (fun n _ => ?_)
  rw [wI_click, if_neg (by omega), mul_zero]

theorem corr_click_abs {c : ℕ → ℕ} (hc : ∀ n, n < L → isU8 (c n)) {q : ℕ} (hq : q < L) (j : ℕ) :
    |corr c (clickAt q) j| ≤ 128 := by
  by_cases hlt : q < j + HM
  · rw [corr_click_zero c hlt]; norm_num
  · have hn0 : q - j - HM < L := by omega
    have : corr c (clickAt q) j = tfI (c (q - j - HM)) := by
      unfold corr
      rw [sum_eq_single (q - j - HM)]
      · rw [wI_click, if_pos (by omega), mul_one]
      · intro n _ hne
        rw [wI_click, if_neg (by omega), mul_zero]
      · intro hmem; exact absurd (mem_range.2 hn0) hmem
    rw [this]
    exact tfI_abs (hc _ hn0)

/-- **Witness: silence passes.** Digital silence, ANY u8 templates, true correlations (all zero),
all flags off, `usum_target = 0`. Every arrival constraint holds, with energy 0 and match 0 at the
arrival lag. So the arrival check can be `0 ≥ 0`: nothing was heard. -/
theorem silence_passes {c_i c_q : ℕ → ℕ}
    (hci : ∀ n, n < L → isU8 (c_i n)) (hcq : ∀ n, n < L → isU8 (c_q n)) :
    ArrivalOK (fun j => decide (j < 0))
      (dF silent c_i (fun j => (corr c_i silent j : F)) (fun j => (corr c_q silent j : F))) ((0 : ℕ) : F) ∧
    bigC silent c_i 0 = 0 ∧ env2 silent c_i c_q 0 = 0 := by
  have hc0 : ∀ c j, corr c silent j = 0 := fun c j =>
    sum_eq_zero (fun n _ => by rw [wI_silent, mul_zero])
  have hy0 : ∀ m, yI silent m = 0 := fun m =>
    sum_eq_zero (fun t _ => by rw [wI_silent, mul_zero])
  have hE0 : EI silent 0 = 0 := sum_eq_zero (fun m _ => by rw [hy0]; norm_num)
  have hb : bigC silent c_i 0 = 0 := by simp [bigC, hE0]
  have he : env2 silent c_i c_q 0 = 0 := by simp [env2, hc0]
  refine ⟨self_side_arrival_complete (fun i _ => silent_u16 i) hci hcq (fun _ _ => rfl) (fun _ _ => rfl)
    0 (by decide) (fun j hj => absurd hj (Nat.not_lt_zero j)) (by rw [hb, he]; norm_num), hb, he⟩

/-- **Witness: a beep-free recording picks the arrival lag.** Take any u8 templates whose `cI` energy
is at least 9100000 (real server codes have about 10 million, see
`scripts/arrival_real_template.py`). Take any lag `a` from 1 to 192. Record silence with one sample
one step above zero, at position `a + 8`. Then every arrival constraint holds with `usum_target = a`,
and the "loud enough" lag `a` has energy 0 and match 0. No beep is in this recording, and the click
position alone sets `a`. Producing it still takes a device willing to sign such a recording. -/
theorem click_picks_any_lag {c_i c_q : ℕ → ℕ}
    (hci : ∀ n, n < L → isU8 (c_i n)) (hcq : ∀ n, n < L → isU8 (c_q n))
    (hcna : 9100000 ≤ cnaI c_i) (a : ℕ) (ha1 : 1 ≤ a) (haK : a < K) :
    ArrivalOK (fun j => decide (j < a))
      (dF (clickAt (a + 8)) c_i (fun j => (corr c_i (clickAt (a + 8)) j : F))
        (fun j => (corr c_q (clickAt (a + 8)) j : F))) (a : F) ∧
    bigC (clickAt (a + 8)) c_i a = 0 ∧ env2 (clickAt (a + 8)) c_i c_q a = 0 := by
  have hK : a < 193 := haK
  have hE0 : EI (clickAt (a + 8)) a = 0 :=
    sum_eq_zero (fun m hm => by
      rw [mem_Ico] at hm
      rw [yI_click_zero (by omega)]; norm_num)
  have hc0 : ∀ c, corr c (clickAt (a + 8)) a = 0 := fun c =>
    corr_click_zero c (by simp only [HM]; omega)
  have hb : bigC (clickAt (a + 8)) c_i a = 0 := by simp [bigC, hE0]
  have he : env2 (clickAt (a + 8)) c_i c_q a = 0 := by simp [env2, hc0]
  have hq : a + 8 < L := by simp only [L]; omega
  refine ⟨self_side_arrival_complete (fun i _ => click_u16 _ i) hci hcq (fun _ _ => rfl) (fun _ _ => rfl)
    a haK (fun j hj => ?_) (by rw [hb, he]; norm_num), hb, he⟩
  unfold bigC
  by_cases hjq : j + 23 ≤ a
  · -- the click is inside the correlation window, and tap 127 is inside the energy window
    have hy : yI (clickAt (a + 8)) (a - 23) = 127 := by
      have : a + 8 = (a - 23) + 31 := by omega
      rw [this, yI_click_tap, tap31]
    have hE : (127 : ℤ) ^ 2 ≤ EI (clickAt (a + 8)) j := by
      have := EI_ge_sq (clickAt (a + 8)) (j := j) (m := a - 23) (by omega)
        (by simp only [L]; omega)
      rwa [hy] at this
    have h1 := sq_le_of_abs_le (corr_click_abs hci hq j)
    have h2 := sq_le_of_abs_le (corr_click_abs hcq hq j)
    have hbar : BAR * env2 (clickAt (a + 8)) c_i c_q j ≤ BAR * (2 * 128 ^ 2) :=
      mul_le_mul_of_nonneg_left (by unfold env2; linarith) (by norm_num [BAR])
    have hprod : (127 : ℤ) ^ 2 * 9100000 ≤ EI (clickAt (a + 8)) j * cnaI c_i :=
      mul_le_mul hE hcna (by norm_num) (by linarith [sq_nonneg (127 : ℤ)])
    have hnum : BAR * (2 * 128 ^ 2) < (127 : ℤ) ^ 2 * 9100000 := by norm_num [BAR]
    linarith
  · -- too early for the template to see the click: match is 0, and tap 1 keeps the energy positive
    have hy : yI (clickAt (a + 8)) (a - 1) = 1 := by
      have : a + 8 = (a - 1) + 9 := by omega
      rw [this, yI_click_tap, tap9]
    have hE : (1 : ℤ) ≤ EI (clickAt (a + 8)) j := by
      have := EI_ge_sq (clickAt (a + 8)) (j := j) (m := a - 1) (by omega)
        (by simp only [L]; omega)
      rw [hy] at this; simpa using this
    have hz : env2 (clickAt (a + 8)) c_i c_q j = 0 := by
      have h1 := corr_click_zero c_i (q := a + 8) (j := j) (by simp only [HM]; omega)
      have h2 := corr_click_zero c_q (q := a + 8) (j := j) (by simp only [HM]; omega)
      simp [env2, h1, h2]
    rw [hz, mul_zero]
    exact mul_pos (by linarith) (by linarith)

/-- A concrete template meeting the energy condition of `click_picks_any_lag`: `cI` alternates
+127, -127. So that theorem's hypotheses can be met. -/
theorem click_instance :
    9100000 ≤ cnaI (fun n => if n % 2 = 0 then 255 else 1) := by
  have : ∀ n ∈ range L, tfI ((fun n => if n % 2 = 0 then 255 else 1) n) ^ 2 = (16129 : ℤ) := by
    intro n _
    by_cases h : n % 2 = 0 <;> simp [tfI, h]
  unfold cnaI
  rw [sum_congr rfl this]
  simp [L]

/-- **Witness: a silent `cI` template passes any recording.** If every `cI` byte is 128 (value 0), then
`cna = 0`, so `big_c = 0` and lag 0 passes whatever was recorded. `phone/main.nr` relies on the server
to attest the codes, so the server has to refuse such a template; the circuit does not. -/
theorem flat_template_any_recording {x c_q : ℕ → ℕ} (hx : ∀ i, i < NS → isU16 (x i))
    (hcq : ∀ n, n < L → isU8 (c_q n)) :
    ArrivalOK (fun j => decide (j < 0))
      (dF x (fun _ => 128) (fun j => (corr (fun _ => 128) x j : F)) (fun j => (corr c_q x j : F)))
      ((0 : ℕ) : F) := by
  have h8 : ∀ n, n < L → isU8 ((fun _ => 128) n) := fun _ _ => by unfold isU8; norm_num
  have hcna : cnaI (fun _ => 128) = 0 := by simp [cnaI, tfI]
  refine self_side_arrival_complete hx h8 hcq (fun _ _ => rfl) (fun _ _ => rfl) 0 (by decide)
    (fun j hj => absurd hj (Nat.not_lt_zero j)) ?_
  have h := (env2_bounds hx h8 hcq (j := 0) (by decide)).1
  have hB : (0 : ℤ) ≤ BAR := by norm_num [BAR]
  simp only [bigC, hcna, mul_zero]
  exact mul_nonneg hB h

theorem yI_dc (m : ℕ) : yI dcOne m = 3 := by
  unfold yI
  simp only [wI_dc, mul_one]
  simp only [Fin.sum_univ_succ, Fin.sum_univ_zero, NZH, Matrix.cons_val_zero, Matrix.cons_val_succ]
  norm_num

/-- **Witness: a strict pass with real energy.** Recording constant 1, `cI` constant 1, `cQ` constant 0.
Energy is positive and `BAR · match` is strictly above loudness, so the arrival branch is reached
for a real reason too. It also shows the mismatch behind the out-of-band finding: energy goes through
the FIR, which nearly kills this signal (taps sum to 3, in-band gain about 190), while the correlation
uses the raw samples. -/
theorem dc_strict_pass :
    ArrivalOK (fun j => decide (j < 0))
      (dF dcOne (fun _ => 129) (fun j => (corr (fun _ => 129) dcOne j : F))
        (fun j => (corr (fun _ => 128) dcOne j : F))) ((0 : ℕ) : F) ∧
    bigC dcOne (fun _ => 129) 0 = 1296000000 ∧
    env2 dcOne (fun _ => 129) (fun _ => 128) 0 = 144000000 ∧
    bigC dcOne (fun _ => 129) 0 < BAR * env2 dcOne (fun _ => 129) (fun _ => 128) 0 := by
  have hE : EI dcOne 0 = 108000 := by simp [EI, yI_dc, L]
  have hcna : cnaI (fun _ => 129) = 12000 := by simp [cnaI, tfI, L]
  have hI : corr (fun _ => 129) dcOne 0 = 12000 := by simp [corr, tfI, wI_dc, L]
  have hQ : corr (fun _ => 128) dcOne 0 = 0 := by simp [corr, tfI]
  have hb : bigC dcOne (fun _ => 129) 0 = 1296000000 := by rw [bigC, hE, hcna]; norm_num
  have he : env2 dcOne (fun _ => 129) (fun _ => 128) 0 = 144000000 := by rw [env2, hI, hQ]; norm_num
  refine ⟨self_side_arrival_complete (fun i _ => dc_u16 i) (fun _ _ => by unfold isU8; norm_num)
    (fun _ _ => by unfold isU8; norm_num) (fun _ _ => rfl) (fun _ _ => rfl) 0 (by decide)
    (fun j hj => absurd hj (Nat.not_lt_zero j)) (by rw [hb, he]; norm_num [BAR]), hb, he,
    by rw [hb, he]; norm_num [BAR]⟩

/-! ## Layer 5: the energy floor (a PROPOSED circuit change, not in `lib.nr` today)

Add at line 405: `(e * (big_c - 1)).assert_max_bit_size::<96>()`. That asks for `big_c ≥ 1` at the
arrival lag only (`e = 1` there, `e = 0` elsewhere). -/

/-- the proposed extra check at lag `j` -/
def floorV (u : ℕ → Bool) (bc : F) (j : ℕ) : F := eSel u j * (bc - 1)

theorem eSel_at (u : ℕ → Bool) (j : ℕ) (hu : u j = false) (hprev : j = 0 ∨ u (j - 1) = true) :
    eSel u j = 1 := by
  unfold eSel
  rcases hprev with h0 | hp
  · subst h0; simp [bf, hu]
  · by_cases h0 : j = 0
    · subst h0; simp [bf, hu]
    · simp [bf, hu, hp, h0]

theorem floor_cast (x c_i : ℕ → ℕ) (j : ℕ) :
    bigCF x c_i j - 1 = ((bigC x c_i j - 1 : ℤ) : F) := by
  rw [bigCF_eq]; push_cast; ring

/-- **With the floor, the arrival lag has real energy and real match.** Everything from
`self_side_arrival_sound`, and also `loudness ≥ 1` and `match > 0` at the arrival lag. So `0 ≥ 0` can no
longer pass. This does not make the arrival a beep: see `dc_passes_floor`. -/
theorem floor_sound {x c_i c_q : ℕ → ℕ} {ci cq : ℕ → F} {u : ℕ → Bool} {ut : F}
    (hx : ∀ i, i < NS → isU16 (x i))
    (hci_t : ∀ n, n < L → isU8 (c_i n)) (hcq_t : ∀ n, n < L → isU8 (c_q n))
    (hI : ∀ j, j < K → ci j = (corr c_i x j : F)) (hQ : ∀ j, j < K → cq j = (corr c_q x j : F))
    (h : ArrivalOK u (dF x c_i ci cq) ut)
    (hf : ∀ j, j < K → fits 96 (floorV u (bigCF x c_i j) j)) :
    ∃ a, a < K ∧ (a : F) = ut ∧ (∀ j, j < K → (u j = true ↔ j < a)) ∧
      (∀ j, j < a → BAR * env2 x c_i c_q j < bigC x c_i j) ∧
      bigC x c_i a ≤ BAR * env2 x c_i c_q a ∧ 1 ≤ bigC x c_i a ∧ 0 < env2 x c_i c_q a := by
  obtain ⟨a, haK, hut, hiff, hb, hat⟩ := self_side_arrival_sound hx hci_t hcq_t hI hQ h
  have hu : u a = false := by
    cases hh : u a with
    | false => rfl
    | true => have := (hiff a haK).mp hh; omega
  have hprev : a = 0 ∨ u (a - 1) = true := by
    rcases Nat.eq_zero_or_pos a with h0 | hpos
    · exact Or.inl h0
    · exact Or.inr ((hiff (a - 1) (by omega)).mpr (by omega))
  have hfa := hf a haK
  rw [floorV, eSel_at u a hu hprev, one_mul, floor_cast] at hfa
  obtain ⟨h0, h1⟩ := bigC_bounds hx hci_t haK
  have hsmall : |bigC x c_i a - 1| < 2 ^ 252 := by
    have := BCMAX_lt
    rw [abs_lt]; constructor <;> norm_num <;> linarith
  have hge := (nonneg_of_fits_intCast (k := 96) (m := 252) (by norm_num) (by norm_num) hsmall hfa).1
  have hbc : 1 ≤ bigC x c_i a := by linarith
  refine ⟨a, haK, hut, hiff, hb, hat, hbc, ?_⟩
  by_contra hne
  have hle : env2 x c_i c_q a ≤ 0 := not_lt.mp hne
  have : BAR * env2 x c_i c_q a ≤ 0 := mul_nonpos_of_nonneg_of_nonpos (by norm_num [BAR]) hle
  linarith

/-- **The floor closes silence.** With the floor added, no flags and no target make digital silence
pass, whatever the templates. -/
theorem floor_blocks_silence {c_i c_q : ℕ → ℕ} {ci cq : ℕ → F} {u : ℕ → Bool} {ut : F}
    (hci_t : ∀ n, n < L → isU8 (c_i n)) (hcq_t : ∀ n, n < L → isU8 (c_q n))
    (hI : ∀ j, j < K → ci j = (corr c_i silent j : F)) (hQ : ∀ j, j < K → cq j = (corr c_q silent j : F))
    (h : ArrivalOK u (dF silent c_i ci cq) ut)
    (hf : ∀ j, j < K → fits 96 (floorV u (bigCF silent c_i j) j)) : False := by
  obtain ⟨a, _, _, _, _, _, hbc, _⟩ :=
    floor_sound (fun i _ => silent_u16 i) hci_t hcq_t hI hQ h hf
  have hy0 : ∀ m, yI silent m = 0 := fun m =>
    sum_eq_zero (fun t _ => by rw [wI_silent, mul_zero])
  have hE0 : EI silent a = 0 := sum_eq_zero (fun m _ => by rw [hy0]; norm_num)
  simp [bigC, hE0] at hbc

theorem fits_natCast_or_small : fits 96 (((1296000000 - 1 : ℤ)) : F) :=
  (fits_intCast_iff_of_abs (k := 96) (m := 96) (by norm_num) (by norm_num) (by norm_num)).2
    (by norm_num)

/-- **The floor is not enough on its own.** `dc_strict_pass` still passes with the floor added:
a signal the FIR rejects carries real energy and real match, so it clears the floor without a beep.
The template here is a toy. Real codes with a tone at a FIR null are measured in
`scripts/arrival_real_template.py`, not proved here. -/
theorem dc_passes_floor :
    ∀ j, j < K → fits 96 (floorV (fun j => decide (j < 0)) (bigCF dcOne (fun _ => 129) j) j) := by
  intro j _
  rcases Nat.eq_zero_or_pos j with h0 | hpos
  · subst h0
    rw [floorV, eSel_at _ 0 (by simp) (Or.inl rfl), one_mul, floor_cast, dc_strict_pass.2.1]
    exact fits_natCast_or_small
  · have : eSel (fun j => decide (j < 0)) j = 0 := by
      unfold eSel
      simp [bf, Nat.pos_iff_ne_zero.mp hpos]
    rw [floorV, this, zero_mul]
    exact fits_zero 96

end Arrival
end Popfv

#print axioms Popfv.Arrival.prefix_iff
#print axioms Popfv.Arrival.arrival_correct
#print axioms Popfv.Arrival.arrival_complete
#print axioms Popfv.Arrival.ring_read
#print axioms Popfv.Arrival.dF_eq
#print axioms Popfv.Arrival.DI_range
#print axioms Popfv.Arrival.bit96_is_sign_check
#print axioms Popfv.Arrival.self_side_arrival_sound
#print axioms Popfv.Arrival.self_side_arrival_complete
#print axioms Popfv.Arrival.silence_passes
#print axioms Popfv.Arrival.click_picks_any_lag
#print axioms Popfv.Arrival.click_instance
#print axioms Popfv.Arrival.flat_template_any_recording
#print axioms Popfv.Arrival.dc_strict_pass
#print axioms Popfv.Arrival.floor_sound
#print axioms Popfv.Arrival.floor_blocks_silence
#print axioms Popfv.Arrival.dc_passes_floor
