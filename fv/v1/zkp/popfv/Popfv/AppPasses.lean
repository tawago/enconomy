import Popfv.Field

/-!
# Popfv.AppPasses — the app's 128-bit `Popt2Rule.passes` is exact

Kotlin source: `app/composeApp/src/commonMain/kotlin/com/enconomy/pop/dsp/Popt2Rule.kt`
lines 98-110 (`passes`) and 210-240 (`U128`).

Model of Kotlin numbers:
* `ULong` = `Nat`; every `+`, `*`, `shl` is followed by `% 2^64` (JVM wraparound).
  `and`, `shr`, `or` are the Nat bit ops `&&&`, `>>>`, `|||` (logical, no wrap possible).
* `Long` = `Int` with hypothesis `-2^63 ≤ x < 2^63`.
  `Long.toULong()` = `(x mod 2^64).toNat` (two's complement reinterpretation).
  Long negation wraps: `wrapLong (-v)`, so `-Long.MIN_VALUE = Long.MIN_VALUE`.
* ULong comparisons are plain Nat comparisons (unsigned).

Result: `passes i q e cn2 b = true ↔ e*cn2 ≤ (i²+q²)*b` (over Int) whenever
`(i²+q²)*b < 2^128`. The code comment's bounds (`|I|,|Q| < 2^62`, `B < 2^32`) are NOT
enough: see `docstring_bound_hole`. The real operating bounds (`|I|,|Q| ≤ 2^36`, `B < 2^32`)
are fine: see `passes_correct_real`.

Scope: this file proves `passes` only, one call on given numbers. Outside it:
* `earliest()` (Popt2Rule.kt:127-174). It skips lags with a float FFT screen first
  (:147-153, slack :207). Nothing here proves the screen never skips a lag the exact rule
  would pass.
* How the circuit gets its numbers from samples. The parity theorems take the app's and the
  circuit's `i, q, e, cn2, b` to be the same integers.

The vectors of `Popt2RuleTest.kt:28-44` run against this model in `popt2RuleTest_vectors`.
-/

set_option linter.style.whitespace false
set_option linter.style.longLine false
set_option linter.style.header false

namespace Popfv
namespace AppPasses

/-- Kotlin `Long.toULong()`: two's complement reinterpretation, `x mod 2^64`. -/
def toULong (x : Int) : Nat := (x % (2^64 : Int)).toNat

/-- A Kotlin `Long` arithmetic result, wrapped back into `[-2^63, 2^63)`. -/
def wrapLong (x : Int) : Int := (x + 2^63) % (2^64 : Int) - 2^63

/-- Popt2Rule.kt:211-213, the unsigned 128-bit scratch `hi·2^64 + lo`. -/
structure U128 where
  hi : Nat
  lo : Nat

/-- Popt2Rule.kt:216-227 `U128.mul` (this = a·b), literal: every ULong `*`, `+`, `shl` wraps. -/
def U128.mul (a b : Nat) : U128 :=
  let m : Nat := 0xFFFFFFFF                                   -- :217
  let a0 := a &&& m                                           -- :218
  let a1 := a >>> 32
  let b0 := b &&& m                                           -- :219
  let b1 := b >>> 32
  let p00 := a0 * b0 % 2^64                                   -- :220
  let p01 := a0 * b1 % 2^64                                   -- :221
  let p10 := a1 * b0 % 2^64                                   -- :222
  let p11 := a1 * b1 % 2^64                                   -- :223
  let mid := ((p00 >>> 32) + (p01 &&& m) + (p10 &&& m)) % 2^64 -- :224
  let lo := (p00 &&& m) ||| ((mid <<< 32) % 2^64)              -- :225
  let hi := (p11 + (p01 >>> 32) + (p10 >>> 32) + (mid >>> 32)) % 2^64 -- :226
  ⟨hi, lo⟩

/-- Popt2Rule.kt:229-232 `U128.sq`: `a = (if (v < 0) -v else v).toULong(); mul(a, a)`. -/
def U128.sq (v : Int) : U128 :=
  let a := toULong (if v < 0 then wrapLong (-v) else v)
  U128.mul a a

/-- Popt2Rule.kt:235-239 `U128.timesSmall`: `h = hi*s; mul(lo, s); hi += h`. -/
def U128.timesSmall (u : U128) (s : Nat) : U128 :=
  let h := u.hi * s % 2^64
  let r := U128.mul u.lo s
  ⟨(r.hi + h) % 2^64, r.lo⟩

/-- Popt2Rule.kt:103-105: `lo = iL + u.lo; hi = iH + u.hi + (if (lo < iL) 1 else 0)`. -/
def addCarry (iH iL qH qL : Nat) : U128 :=
  let lo := (iL + qL) % 2^64
  let hi := (iH + qH + (if lo < iL then 1 else 0)) % 2^64
  ⟨hi, lo⟩

/-- Popt2Rule.kt:109: `if (lHi != u.hi) lHi > u.hi else lLo >= u.lo` (unsigned). -/
def cmp (l r : U128) : Bool :=
  if l.hi ≠ r.hi then decide (l.hi > r.hi) else decide (l.lo ≥ r.lo)

/-- Popt2Rule.kt:99-110 `passes(i, q, e, cn2, b)`. -/
def passes (i q e cn2 b : Int) : Bool :=
  let u1 := U128.sq i                                   -- :101  iH, iL
  let u2 := U128.sq q                                   -- :102
  let s := addCarry u1.hi u1.lo u2.hi u2.lo             -- :103-105
  let l := U128.timesSmall s (toULong b)                -- :106-107
  let r := U128.mul (toULong e) (toULong cn2)           -- :108
  cmp l r                                               -- :109

/-! ## Bit-op helpers -/

theorem and_m (x : Nat) : x &&& 0xFFFFFFFF = x % 2^32 := by
  exact Nat.and_two_pow_sub_one_eq_mod x 32

theorem shr32 (x : Nat) : x >>> 32 = x / 2^32 := Nat.shiftRight_eq_div_pow x 32

theorem shl32 (x : Nat) : x <<< 32 = x * 2^32 := Nat.shiftLeft_eq x 32

theorem or_lo (x y : Nat) (hx : x < 2^32) : x ||| (y * 2^32 % 2^64) = x + y % 2^32 * 2^32 := by
  have h1 : y * 2^32 % 2^64 = (y % 2^32) <<< 32 := by rw [Nat.shiftLeft_eq]; omega
  rw [h1, Nat.or_comm, ← Nat.shiftLeft_add_eq_or_of_lt hx, Nat.shiftLeft_eq]; omega

/-- Limb split: the low half of `x·2^32 + y` is `y`. -/
theorem split_mod (x y : Nat) (hy : y < 2^32) : (x * 2^32 + y) % 2^32 = y := by omega

/-- Limb split: the high half of `x·2^32 + y` is `x`. -/
theorem split_div (x y : Nat) (hy : y < 2^32) : (x * 2^32 + y) / 2^32 = x := by omega

/-! ## The 64×64 → 128 multiply -/

/-- `U128.mul a b` really computes the 128-bit product `a·b` (for 64-bit `a`, `b`):
`hi·2^64 + lo = a·b`, and both halves are genuine 64-bit words. -/
theorem U128.mul_spec (a b : Nat) (ha : a < 2^64) (hb : b < 2^64) :
    (U128.mul a b).hi * 2^64 + (U128.mul a b).lo = a * b ∧
      (U128.mul a b).hi < 2^64 ∧ (U128.mul a b).lo < 2^64 := by
  obtain ⟨a0, a1, rfl, ha0, ha1⟩ : ∃ a0 a1, a = a1 * 2^32 + a0 ∧ a0 < 2^32 ∧ a1 < 2^32 :=
    ⟨a % 2^32, a / 2^32, by omega, by omega, by omega⟩
  obtain ⟨b0, b1, rfl, hb0, hb1⟩ : ∃ b0 b1, b = b1 * 2^32 + b0 ∧ b0 < 2^32 ∧ b1 < 2^32 :=
    ⟨b % 2^32, b / 2^32, by omega, by omega, by omega⟩
  have e0 := split_mod a1 a0 ha0
  have e1 := split_div a1 a0 ha0
  have f0 := split_mod b1 b0 hb0
  have f1 := split_div b1 b0 hb0
  have hP : (a1 * 2^32 + a0) * (b1 * 2^32 + b0)
      = 2^64 * (a1 * b1) + 2^32 * (a0 * b1) + 2^32 * (a1 * b0) + a0 * b0 := by ring
  have hlt : (a1 * 2^32 + a0) * (b1 * 2^32 + b0) < 2^128 := by
    calc _ < 2^64 * 2^64 := Nat.mul_lt_mul'' ha hb
      _ = 2^128 := by norm_num
  have h32 : (2:Nat)^32 * 2^32 = 2^64 := by norm_num
  have q00 : a0 * b0 < 2^64 := h32 ▸ Nat.mul_lt_mul'' ha0 hb0
  have q01 : a0 * b1 < 2^64 := h32 ▸ Nat.mul_lt_mul'' ha0 hb1
  have q10 : a1 * b0 < 2^64 := h32 ▸ Nat.mul_lt_mul'' ha1 hb0
  have q11 : a1 * b1 < 2^64 := h32 ▸ Nat.mul_lt_mul'' ha1 hb1
  simp only [U128.mul, and_m, shr32, shl32, e0, e1, f0, f1, Nat.mod_eq_of_lt q00,
    Nat.mod_eq_of_lt q01, Nat.mod_eq_of_lt q10, Nat.mod_eq_of_lt q11]
  rw [or_lo _ _ (Nat.mod_lt _ (by norm_num))]
  refine ⟨?_, ?_, ?_⟩ <;> omega

/-! ## Squaring a Long, including Long.MIN_VALUE -/

theorem toULong_abs (v : Int) (h1 : -2^63 ≤ v) (h2 : v < 2^63) :
    toULong (if v < 0 then wrapLong (-v) else v) = v.natAbs := by
  unfold toULong wrapLong
  split_ifs <;> omega

/-- `U128.sq v` computes `|v|²` exactly as a 128-bit number, for every Kotlin `Long` `v`,
including `Long.MIN_VALUE = -2^63` (whose negation wraps, but reinterprets as `2^63`). -/
theorem U128.sq_spec (v : Int) (h1 : -2^63 ≤ v) (h2 : v < 2^63) :
    (U128.sq v).hi * 2^64 + (U128.sq v).lo = v.natAbs ^ 2 ∧
      (U128.sq v).hi < 2^64 ∧ (U128.sq v).lo < 2^64 := by
  have hlt : v.natAbs < 2^64 := by omega
  simp only [U128.sq, toULong_abs v h1 h2, pow_two]
  exact U128.mul_spec _ _ hlt hlt

/-! ## Add with carry, timesSmall, compare -/

/-- Lines 103-105: adding two 128-bit numbers with a carry bit is exact when the sum fits. -/
theorem addCarry_spec (iH iL qH qL I2 Q2 : Nat) (hI : iH * 2^64 + iL = I2)
    (hQ : qH * 2^64 + qL = Q2) (hiL : iL < 2^64) (hqL : qL < 2^64) (hS : I2 + Q2 < 2^128) :
    (addCarry iH iL qH qL).hi * 2^64 + (addCarry iH iL qH qL).lo = I2 + Q2 ∧
      (addCarry iH iL qH qL).hi < 2^64 ∧ (addCarry iH iL qH qL).lo < 2^64 := by
  simp only [addCarry]
  split_ifs <;> omega

/-- The carry arithmetic of `timesSmall`, on plain numbers: `H = hi·s`, `L = lo·s`, and
`mul(lo, s)` returned `rh·2^64 + rl = L`. -/
theorem timesSmall_arith (H L rh rl : Nat) (m1 : rh * 2^64 + rl = L) (m3 : rl < 2^64)
    (hX : H * 2^64 + L < 2^128) :
    ((rh + H % 2^64) % 2^64) * 2^64 + rl = H * 2^64 + L ∧ (rh + H % 2^64) % 2^64 < 2^64 := by
  omega

/-- `timesSmall` multiplies a 128-bit number by a 64-bit `s` exactly, provided the true
product is below `2^128` (the code comment's own precondition). -/
theorem U128.timesSmall_spec (u : U128) (s : Nat) (hlo : u.lo < 2^64) (hs : s < 2^64)
    (hX : (u.hi * 2^64 + u.lo) * s < 2^128) :
    (U128.timesSmall u s).hi * 2^64 + (U128.timesSmall u s).lo = (u.hi * 2^64 + u.lo) * s ∧
      (U128.timesSmall u s).hi < 2^64 ∧ (U128.timesSmall u s).lo < 2^64 := by
  obtain ⟨m1, m2, m3⟩ := U128.mul_spec u.lo s hlo hs
  have hexp : (u.hi * 2^64 + u.lo) * s = u.hi * s * 2^64 + u.lo * s := by ring
  simp only [U128.timesSmall]
  rw [hexp] at hX ⊢
  have ha := timesSmall_arith (u.hi * s) (u.lo * s) _ _ m1 m3 hX
  exact ⟨ha.1, ha.2, m3⟩

/-- Line 109: the hi-then-lo unsigned compare is the numeric `≥` of the two 128-bit values. -/
theorem cmp_spec (l r : U128) (hl : l.lo < 2^64) (hr : r.lo < 2^64) :
    cmp l r = true ↔ r.hi * 2^64 + r.lo ≤ l.hi * 2^64 + l.lo := by
  unfold cmp
  split_ifs <;> first | omega | (simp only [decide_eq_true_eq]; omega)

/-! ## Main theorems -/

theorem toULong_nonneg (x : Int) (h1 : 0 ≤ x) (h2 : x < 2^63) : toULong x = x.toNat := by
  unfold toULong; omega

/-- Nat form of the main theorem (used to prove `passes_correct`). -/
theorem passes_nat (i q e cn2 b : Int)
    (hi1 : -2^63 ≤ i) (hi2 : i < 2^63) (hq1 : -2^63 ≤ q) (hq2 : q < 2^63)
    (he1 : 0 ≤ e) (he2 : e < 2^63) (hc1 : 0 ≤ cn2) (hc2 : cn2 < 2^63)
    (hb1 : 0 ≤ b) (hb2 : b < 2^63)
    (hbig : (i.natAbs ^ 2 + q.natAbs ^ 2) * b.toNat < 2^128) :
    passes i q e cn2 b = true ↔ e.toNat * cn2.toNat ≤ (i.natAbs ^ 2 + q.natAbs ^ 2) * b.toNat := by
  obtain ⟨si1, -, si3⟩ := U128.sq_spec i hi1 hi2
  obtain ⟨sq1, -, sq3⟩ := U128.sq_spec q hq1 hq2
  have hI : i.natAbs ^ 2 ≤ 2^126 := by
    calc i.natAbs ^ 2 ≤ (2^63) ^ 2 := Nat.pow_le_pow_left (by omega) 2
      _ = 2^126 := by norm_num
  have hQ : q.natAbs ^ 2 ≤ 2^126 := by
    calc q.natAbs ^ 2 ≤ (2^63) ^ 2 := Nat.pow_le_pow_left (by omega) 2
      _ = 2^126 := by norm_num
  have hS := addCarry_spec _ _ _ _ _ _ si1 sq1 si3 sq3 (by omega)
  have tb := toULong_nonneg b hb1 hb2
  have te := toULong_nonneg e he1 he2
  have tc := toULong_nonneg cn2 hc1 hc2
  have hbU : toULong b < 2^64 := by rw [tb]; omega
  have heU : toULong e < 2^64 := by rw [te]; omega
  have hcU : toULong cn2 < 2^64 := by rw [tc]; omega
  have hl := U128.timesSmall_spec
    (addCarry (U128.sq i).hi (U128.sq i).lo (U128.sq q).hi (U128.sq q).lo) (toULong b)
    hS.2.2 hbU (by rw [hS.1, tb]; exact hbig)
  have hr := U128.mul_spec (toULong e) (toULong cn2) heU hcU
  simp only [passes]
  rw [cmp_spec _ _ hl.2.2 hr.2.2, hl.1, hr.1, hS.1, tb, te, tc]

theorem cast_lhs (e cn2 : Int) (he : 0 ≤ e) (hc : 0 ≤ cn2) :
    ((e.toNat * cn2.toNat : Nat) : Int) = e * cn2 := by
  rw [Nat.cast_mul, Int.toNat_of_nonneg he, Int.toNat_of_nonneg hc]

theorem cast_rhs (i q b : Int) (hb : 0 ≤ b) :
    (((i.natAbs ^ 2 + q.natAbs ^ 2) * b.toNat : Nat) : Int) = (i ^ 2 + q ^ 2) * b := by
  rw [Nat.cast_mul, Nat.cast_add, Nat.cast_pow, Nat.cast_pow, Int.natAbs_pow_two,
    Int.natAbs_pow_two, Int.toNat_of_nonneg hb]

/-- **Main theorem.** For any Kotlin `Long` inputs with `e, cn2, b ≥ 0`, the app's
128-bit-integer routine `passes` answers exactly the real-number question
"is (I² + Q²)·B ≥ E·cn2 ?", as long as the left side is below 2^128 (no overflow). -/
theorem passes_correct (i q e cn2 b : Int)
    (hi1 : -2^63 ≤ i) (hi2 : i < 2^63) (hq1 : -2^63 ≤ q) (hq2 : q < 2^63)
    (he1 : 0 ≤ e) (he2 : e < 2^63) (hc1 : 0 ≤ cn2) (hc2 : cn2 < 2^63)
    (hb1 : 0 ≤ b) (hb2 : b < 2^63)
    (hbig : (i ^ 2 + q ^ 2) * b < 2^128) :
    passes i q e cn2 b = true ↔ e * cn2 ≤ (i ^ 2 + q ^ 2) * b := by
  have hbig' : (i.natAbs ^ 2 + q.natAbs ^ 2) * b.toNat < 2^128 := by
    have h := hbig
    rw [← cast_rhs i q b hb1] at h
    exact_mod_cast h
  rw [passes_nat i q e cn2 b hi1 hi2 hq1 hq2 he1 he2 hc1 hc2 hb1 hb2 hbig',
    ← cast_lhs e cn2 he1 hc1, ← cast_rhs i q b hb1]
  exact Nat.cast_le.symm

/-- **Main theorem, real operating bounds.** With |I|, |Q| ≤ 2^36 (real: < 2^35.6),
0 ≤ E < 2^63, 0 ≤ cn2 < 2^63 and 0 ≤ B < 2^32, `passes` is exactly `(I²+Q²)·B ≥ E·cn2`. -/
theorem passes_correct_real (i q e cn2 b : Int)
    (hi : |i| ≤ 2^36) (hq : |q| ≤ 2^36)
    (he1 : 0 ≤ e) (he2 : e < 2^63) (hc1 : 0 ≤ cn2) (hc2 : cn2 < 2^63)
    (hb1 : 0 ≤ b) (hb2 : b < 2^32) :
    passes i q e cn2 b = true ↔ e * cn2 ≤ (i ^ 2 + q ^ 2) * b := by
  obtain ⟨hi1, hi2⟩ := abs_le.mp hi
  obtain ⟨hq1, hq2⟩ := abs_le.mp hq
  have hI : i ^ 2 ≤ (2^36) ^ 2 := sq_le_sq' hi1 hi2
  have hQ : q ^ 2 ≤ (2^36) ^ 2 := sq_le_sq' hq1 hq2
  have hS : i ^ 2 + q ^ 2 ≤ 2^73 := by norm_num at hI hQ ⊢; linarith
  have hSb : (i ^ 2 + q ^ 2) * b ≤ 2^73 * b := mul_le_mul_of_nonneg_right hS hb1
  have hbig : (i ^ 2 + q ^ 2) * b < 2^128 := by norm_num at hSb hb2 ⊢; linarith
  exact passes_correct i q e cn2 b (by linarith) (by linarith) (by linarith) (by linarith)
    he1 he2 hc1 hc2 hb1 (by linarith) hbig

/-- **App/circuit parity.** With the circuit's `d = E·cn2 − BAR·env2` (lib.nr:401, BAR = B,
env2 = I²+Q²), the app's `passes` holds exactly when `d ≤ 0`, i.e. the circuit's partner
value `v = BAR·penv2 − ep·cnp = −d` is `≥ 0` (lib.nr:470-472). -/
theorem passes_iff_d_nonpos (i q e cn2 b : Int)
    (hi : |i| ≤ 2^36) (hq : |q| ≤ 2^36)
    (he1 : 0 ≤ e) (he2 : e < 2^63) (hc1 : 0 ≤ cn2) (hc2 : cn2 < 2^63)
    (hb1 : 0 ≤ b) (hb2 : b < 2^32) :
    passes i q e cn2 b = true ↔ e * cn2 - b * (i ^ 2 + q ^ 2) ≤ 0 := by
  rw [passes_correct_real i q e cn2 b hi hq he1 he2 hc1 hc2 hb1 hb2, mul_comm b, sub_nonpos]

/-- **App/circuit parity in the field.** Under the real bounds (|I|,|Q| < 2^36, B < 2^23,
cn2 < 2^28, E < 2^63) the app's `passes` is true exactly when the circuit's partner
constraint `v.assert_max_bit_size::<96>()` with `v = BAR·penv2 − ep·cnp` (lib.nr:470-472)
is satisfied, the circuit's ii, qq, ep, cnp, BAR being the same integers as the app's.
Here the bounds assume nothing an attacker controls: the partner side computes all of these from
`u16` samples and `u8` templates, which forces them. The theorem is about that last assert only,
not how the circuit computes its inputs, and not `earliest()`'s FFT screen. -/
theorem passes_iff_partner_fits (i q e cn2 b : Int)
    (hi : |i| < 2^36) (hq : |q| < 2^36)
    (he1 : 0 ≤ e) (he2 : e < 2^63) (hc1 : 0 ≤ cn2) (hc2 : cn2 < 2^28)
    (hb1 : 0 ≤ b) (hb2 : b < 2^23) :
    passes i q e cn2 b = true ↔ fits 96 (((b * (i ^ 2 + q ^ 2) - e * cn2 : Int)) : F) := by
  obtain ⟨hi1, hi2⟩ := abs_lt.mp hi
  obtain ⟨hq1, hq2⟩ := abs_lt.mp hq
  have hI : i ^ 2 < (2^36) ^ 2 := sq_lt_sq' hi1 hi2
  have hQ : q ^ 2 < (2^36) ^ 2 := sq_lt_sq' hq1 hq2
  have hS : i ^ 2 + q ^ 2 < 2^73 := by norm_num at hI hQ ⊢; linarith
  have hS0 : 0 ≤ i ^ 2 + q ^ 2 := by positivity
  have hbS : b * (i ^ 2 + q ^ 2) ≤ b * 2^73 := mul_le_mul_of_nonneg_left hS.le hb1
  have hbS' : b * (i ^ 2 + q ^ 2) < 2^96 := by norm_num at hbS hb2 ⊢; linarith
  have hbS0 : 0 ≤ b * (i ^ 2 + q ^ 2) := mul_nonneg hb1 hS0
  have hec : e * cn2 ≤ e * 2^28 := mul_le_mul_of_nonneg_left hc2.le he1
  have hec' : e * cn2 < 2^91 := by norm_num at hec he2 ⊢; linarith
  have hec0 : 0 ≤ e * cn2 := mul_nonneg he1 hc1
  have habs : |b * (i ^ 2 + q ^ 2) - e * cn2| < 2^97 := by
    rw [abs_lt]; constructor <;> norm_num at hbS' hec' ⊢ <;> linarith
  have hcomm : b * (i ^ 2 + q ^ 2) = (i ^ 2 + q ^ 2) * b := mul_comm _ _
  rw [fits_intCast_iff_of_abs (k := 96) (m := 97) (by norm_num) (by norm_num) habs,
    passes_correct_real i q e cn2 b (by linarith [abs_nonneg i]) (by linarith [abs_nonneg q])
      he1 he2 hc1 (by linarith) hb1 (by linarith)]
  constructor
  · intro h; exact ⟨by linarith, by linarith⟩
  · rintro ⟨h, -⟩; linarith

/-- lib.nr:401-404, the circuit's self-side value `v = uj*(d-1) - (prev-uj)*d`, where
`prev` is the flag `u[j-1]` (1 at `j = 0`) and `d = E*cn2 - BAR*env2`. After the arrival both
flags are 0, so `v = 0` and the rule asks nothing of that lag. -/
def selfV (uj prev d : Int) : Int := uj * (d - 1) - (prev - uj) * d

/-- **App/circuit parity at the arrival sample.** The flags flip here (`u[j-1] = 1`, `u[j] = 0`),
so the circuit's check at lib.nr:405 is `-d ≥ 0`. It holds exactly when the app's `passes` says yes.
**Assumes block C.** `ci`, `cq` are unconstrained `Field` witnesses in `self_side` (lib.nr:341-342).
`|i|, |q| < 2^36` holds only if block C (Freivalds, unproved) makes them the true correlations. -/
theorem passes_iff_self_arrival (i q e cn2 b : Int)
    (hi : |i| < 2^36) (hq : |q| < 2^36)
    (he1 : 0 ≤ e) (he2 : e < 2^63) (hc1 : 0 ≤ cn2) (hc2 : cn2 < 2^28)
    (hb1 : 0 ≤ b) (hb2 : b < 2^23) :
    passes i q e cn2 b = true ↔
      fits 96 ((selfV 0 1 (e * cn2 - b * (i ^ 2 + q ^ 2)) : Int) : F) := by
  have h : selfV 0 1 (e * cn2 - b * (i ^ 2 + q ^ 2)) = b * (i ^ 2 + q ^ 2) - e * cn2 := by
    unfold selfV; ring
  rw [h]
  exact passes_iff_partner_fits i q e cn2 b hi hq he1 he2 hc1 hc2 hb1 hb2

/-- **App/circuit parity before the arrival.** The flags stay 1 (`u[j-1] = u[j] = 1`), so the
circuit's check at lib.nr:405 is `d - 1 ≥ 0`, meaning "strictly under the bar". It holds exactly
when the app's `passes` says no.
**Assumes block C.** `ci`, `cq` are unconstrained `Field` witnesses in `self_side` (lib.nr:341-342).
`|i|, |q| < 2^36` holds only if block C (Freivalds, unproved) makes them the true correlations. -/
theorem not_passes_iff_self_before (i q e cn2 b : Int)
    (hi : |i| < 2^36) (hq : |q| < 2^36)
    (he1 : 0 ≤ e) (he2 : e < 2^63) (hc1 : 0 ≤ cn2) (hc2 : cn2 < 2^28)
    (hb1 : 0 ≤ b) (hb2 : b < 2^23) :
    passes i q e cn2 b = false ↔
      fits 96 ((selfV 1 1 (e * cn2 - b * (i ^ 2 + q ^ 2)) : Int) : F) := by
  obtain ⟨hi1, hi2⟩ := abs_lt.mp hi
  obtain ⟨hq1, hq2⟩ := abs_lt.mp hq
  have hI : i ^ 2 < (2^36) ^ 2 := sq_lt_sq' hi1 hi2
  have hQ : q ^ 2 < (2^36) ^ 2 := sq_lt_sq' hq1 hq2
  have hS : i ^ 2 + q ^ 2 < 2^73 := by norm_num at hI hQ ⊢; linarith
  have hS0 : 0 ≤ i ^ 2 + q ^ 2 := by positivity
  have hbS : b * (i ^ 2 + q ^ 2) ≤ b * 2^73 := mul_le_mul_of_nonneg_left hS.le hb1
  have hbS' : b * (i ^ 2 + q ^ 2) < 2^96 := by norm_num at hbS hb2 ⊢; linarith
  have hbS0 : 0 ≤ b * (i ^ 2 + q ^ 2) := mul_nonneg hb1 hS0
  have hec : e * cn2 ≤ e * 2^28 := mul_le_mul_of_nonneg_left hc2.le he1
  have hec' : e * cn2 < 2^91 := by norm_num at hec he2 ⊢; linarith
  have hec0 : 0 ≤ e * cn2 := mul_nonneg he1 hc1
  have h : selfV 1 1 (e * cn2 - b * (i ^ 2 + q ^ 2)) = e * cn2 - b * (i ^ 2 + q ^ 2) - 1 := by
    unfold selfV; ring
  have habs : |e * cn2 - b * (i ^ 2 + q ^ 2) - 1| < 2^97 := by
    rw [abs_lt]; constructor <;> norm_num at hbS' hec' ⊢ <;> linarith
  have hcomm : b * (i ^ 2 + q ^ 2) = (i ^ 2 + q ^ 2) * b := mul_comm _ _
  have hp := passes_correct_real i q e cn2 b (by linarith [abs_nonneg i]) (by linarith [abs_nonneg q])
    he1 he2 hc1 (by linarith) hb1 (by linarith)
  rw [h, fits_intCast_iff_of_abs (k := 96) (m := 97) (by norm_num) (by norm_num) habs,
    ← Bool.not_eq_true, hp]
  constructor
  · intro hn
    have hn' : (i ^ 2 + q ^ 2) * b < e * cn2 := not_le.mp hn
    constructor
    · have : (i ^ 2 + q ^ 2) * b + 1 ≤ e * cn2 := hn'
      linarith
    · norm_num at hec' hbS0 ⊢; linarith
  · rintro ⟨h0, -⟩
    exact not_le.mpr (by linarith)

/-- **Hole in the code comment.** The comment on `passes` (Popt2Rule.kt:98) promises
exactness for |I|,|Q| < 2^62 and B < 2^32. That is false: with I = 2^61, Q = 0, E = cn2 = 1,
B = 2^31 (all inside those ranges), the true left side is 2^153 ≥ 1, but the 128-bit
product overflows to 0 and `passes` returns false. The missing condition is
(I²+Q²)·B < 2^128; the app's real inputs (|I| < 2^35.6, B < 2^22.1) satisfy it easily. -/
theorem docstring_bound_hole :
    passes 2305843009213693952 0 1 1 2147483648 = false ∧
      (1 : Int) * 1 ≤ ((2305843009213693952 : Int) ^ 2 + 0 ^ 2) * 2147483648 := by
  exact ⟨by decide, by norm_num⟩

/-- `Popt2RuleTest.kt:28-44` `passesIsExact`, every assert, run on this model.
`cn2 = 9164281855` is what `:39-40` computes in IEEE doubles, hard-coded here, so the fifth and
sixth lines are its `cn2 - 1` and `cn2 + 1`. The last conjunct checks those two against the
true integers too. -/
theorem popt2RuleTest_vectors :
    passes 3 4 10 10 4 = true ∧                                               -- :30
    passes 3 (-4) 11 10 4 = false ∧                                           -- :31
    passes (-1099511627776) 0 4611686018427387904 262144 1 = true ∧           -- :34
    passes 1099511627776 0 4611686018427387905 262144 1 = false ∧             -- :35
    passes 68719476735 68719476735 4611686018427387903 9164281854 4474747 = true ∧  -- :41
    passes 68719476735 68719476735 4611686018427387903 9164281856 4474747 = false ∧ -- :42
    passes 0 0 0 12345 1 = true ∧                                             -- :43
    ((4611686018427387903 : Int) * 9164281854 ≤ (68719476735 ^ 2 + 68719476735 ^ 2) * 4474747 ∧
      ((68719476735 : Int) ^ 2 + 68719476735 ^ 2) * 4474747 < 4611686018427387903 * 9164281856) := by
  refine ⟨by decide, by decide, by decide, by decide, by decide, by decide, by decide, ?_, ?_⟩ <;>
    norm_num

/-- Cases the Kotlin test lacks. First pair: a real carry out of the low word at :104, with
legal `Long` inputs (`2·I² = 2^64 + 290948384`, an exact tie, then one over). Drop the carry and
the first line turns false. Third line: `Long.MIN_VALUE`, whose negation wraps. -/
theorem extra_vectors :
    passes 3037000500 3037000500 3037000500 6074001000 1 = true ∧
    passes 3037000500 3037000500 3037000500 6074001001 1 = false ∧
    passes (-9223372036854775808) 0 9223372036854775807 1 1 = true := by
  refine ⟨by decide, by decide, by decide⟩

/-- Not vacuous: a test vector meets every hypothesis of the partner parity theorem, and the
app's yes there gives the circuit's check. -/
theorem partner_fits_witness :
    fits 96 (((4 * ((3 : Int) ^ 2 + 4 ^ 2) - 10 * 10 : Int)) : F) :=
  (passes_iff_partner_fits 3 4 10 10 4 (by norm_num) (by norm_num) (by norm_num) (by norm_num)
    (by norm_num) (by norm_num) (by norm_num) (by norm_num)).mp (by decide)

end AppPasses
end Popfv

#print axioms Popfv.AppPasses.U128.mul_spec
#print axioms Popfv.AppPasses.U128.sq_spec
#print axioms Popfv.AppPasses.addCarry_spec
#print axioms Popfv.AppPasses.U128.timesSmall_spec
#print axioms Popfv.AppPasses.passes_correct
#print axioms Popfv.AppPasses.passes_correct_real
#print axioms Popfv.AppPasses.passes_iff_d_nonpos
#print axioms Popfv.AppPasses.passes_iff_partner_fits
#print axioms Popfv.AppPasses.passes_iff_self_arrival
#print axioms Popfv.AppPasses.not_passes_iff_self_before
#print axioms Popfv.AppPasses.docstring_bound_hole
#print axioms Popfv.AppPasses.popt2RuleTest_vectors
#print axioms Popfv.AppPasses.extra_vectors
#print axioms Popfv.AppPasses.partner_fits_witness
