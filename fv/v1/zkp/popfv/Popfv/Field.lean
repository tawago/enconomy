import Mathlib

/-!
# Popfv.Field — shared field model for the Noir circuits

Noir works over the BN254 scalar field. Every other file imports this one.

* `p`, `F`             : the prime modulus and the field `ZMod p`.
* `fits k x`           : Noir `x.assert_max_bit_size::<k>()`, i.e. `x.val < 2^k`.
                         This is how the circuit says "x ≥ 0 (and small)".
* `fits_intCast_iff`   : for a true integer `z` that is not huge, `fits k (z : F) ↔ 0 ≤ z < 2^k`.
* `isU8/isU16/isU32/isU64` : input type ranges.
* `intCast_inj_of_abs_lt`  : an equation in `F` between casts of integers that are
                         closer than `p` is a real integer equation.

Primality of `p` is NOT assumed anywhere here.
-/

set_option linter.style.whitespace false
set_option linter.style.longLine false
set_option linter.style.header false

namespace Popfv

/-- BN254 scalar field modulus `r`. -/
def p : Nat :=
  21888242871839275222246405745257275088548364400416034343698204186575808495617

/-- The Noir `Field` type. -/
abbrev F := ZMod p

instance : NeZero p := ⟨by unfold p; decide⟩

/-- `2^253 < p`, so every bit size we use (≤ 252) leaves room for wraparound detection. -/
theorem two_pow_253_lt_p : (2:Int)^253 < (p:Int) := by unfold p; norm_num

theorem two_pow_lt_p {k : Nat} (hk : k ≤ 252) : (2:Int)^k < (p:Int) := by
  have h1 : (2:Int)^k ≤ 2^252 := pow_le_pow_right₀ (by norm_num) hk
  have := two_pow_253_lt_p
  have h2 : (2:Int)^252 < 2^253 := by norm_num
  omega

/-- Noir `x.assert_max_bit_size::<k>()`: the canonical representative of `x` is `< 2^k`. -/
def fits (k : Nat) (x : F) : Prop := x.val < 2^k

/-! ## Input type ranges (`uN` values are naturals in `[0, 2^N)`). -/

def isU8  (x : Nat) : Prop := x < 2^8
def isU16 (x : Nat) : Prop := x < 2^16
def isU32 (x : Nat) : Prop := x < 2^32
def isU64 (x : Nat) : Prop := x < 2^64

/-! ## Natural-number casts (`v as Field`). -/

/-- Casting a natural below `p` into `F` and reading `.val` gives it back. -/
theorem val_natCast_of_lt {n : Nat} (h : n < p) : (n : F).val = n :=
  ZMod.val_cast_of_lt h

theorem natCast_lt_p_of_lt_two_pow {n k : Nat} (hk : k ≤ 252) (h : n < 2^k) : n < p := by
  have := two_pow_lt_p hk
  have : (n:Int) < 2^k := by exact_mod_cast h
  omega

/-- For `n < p`, the bit check on `(n : F)` is just `n < 2^k`. -/
theorem fits_natCast_iff {k n : Nat} (h : n < p) : fits k (n : F) ↔ n < 2^k := by
  unfold fits; rw [val_natCast_of_lt h]

/-- Any `n < 2^k` (k ≤ 252) passes `assert_max_bit_size::<k>`. -/
theorem fits_natCast {k n : Nat} (hk : k ≤ 252) (h : n < 2^k) : fits k (n : F) :=
  (fits_natCast_iff (natCast_lt_p_of_lt_two_pow hk h)).2 h

theorem isU8_lt_p  {x : Nat} (h : isU8 x)  : x < p := natCast_lt_p_of_lt_two_pow (by norm_num) h
theorem isU16_lt_p {x : Nat} (h : isU16 x) : x < p := natCast_lt_p_of_lt_two_pow (by norm_num) h
theorem isU32_lt_p {x : Nat} (h : isU32 x) : x < p := natCast_lt_p_of_lt_two_pow (by norm_num) h
theorem isU64_lt_p {x : Nat} (h : isU64 x) : x < p := natCast_lt_p_of_lt_two_pow (by norm_num) h

/-- A field element that passes the bit check is the cast of a small natural. -/
theorem fits_exists_nat {k : Nat} {x : F} (h : fits k x) : ∃ n : Nat, n < 2^k ∧ x = (n : F) :=
  ⟨x.val, h, (ZMod.natCast_zmod_val x).symm⟩

/-! ## Integer casts (`Int → F` is a ring hom: `Int.cast_add`, `Int.cast_sub`, `Int.cast_mul`
are `simp`/`push_cast` lemmas, so field equations built from casts are integer equations mod p). -/

theorem intCast_natCast (n : Nat) : (((n : Int)) : F) = (n : F) := Int.cast_natCast n

/-- `.val` of an integer cast, as an integer: it is `z mod p`. -/
theorem val_intCast (z : Int) : (((z : F).val : Nat) : Int) = z % (p : Int) :=
  ZMod.val_intCast z

/-- **Key lemma.** As long as the true integer `z` lies in `(-(p - 2^k), p)`, the circuit's bit
check on `z` (as a field element) means exactly `0 ≤ z < 2^k`. A negative `z` wraps to `p + z`,
which is at least `2^k`, so the check rejects it. -/
theorem fits_intCast_iff {k : Nat} (hk : k ≤ 252) {z : Int}
    (hlo : -((p : Int) - 2^k) < z) (hhi : z < (p : Int)) :
    fits k (z : F) ↔ 0 ≤ z ∧ z < 2^k := by
  have hp := two_pow_lt_p hk
  have hpos : (0:Int) < 2^k := by positivity
  have hv := val_intCast z
  have hfits : fits k (z : F) ↔ (((z : F).val : Nat) : Int) < 2^k := by
    unfold fits; constructor <;> intro h <;> exact_mod_cast h
  rw [hfits, hv]
  rcases le_or_gt 0 z with h0 | h0
  · rw [Int.emod_eq_of_lt h0 hhi]; constructor
    · intro h; exact ⟨h0, h⟩
    · intro h; exact h.2
  · have : z % (p : Int) = z + p := by
      have e : (z + p) % (p : Int) = z % p := by simp
      rw [← e]
      exact Int.emod_eq_of_lt (by omega) (by omega)
    rw [this]; constructor
    · intro h; omega
    · intro h; omega

/-- Symmetric-bound version: if `|z| < 2^m` with `m ≤ 252`, the bit check on `z` means
`0 ≤ z < 2^k`. -/
theorem fits_intCast_iff_of_abs {k m : Nat} (hk : k ≤ 252) (hm : m ≤ 252) {z : Int}
    (hz : |z| < 2^m) : fits k (z : F) ↔ 0 ≤ z ∧ z < 2^k := by
  have hp := two_pow_253_lt_p
  have h1 : (2:Int)^k ≤ 2^252 := pow_le_pow_right₀ (by norm_num) hk
  have h2 : (2:Int)^m ≤ 2^252 := pow_le_pow_right₀ (by norm_num) hm
  have h3 : (2:Int)^253 = 2^252 + 2^252 := by norm_num
  have ⟨ha, hb⟩ := abs_lt.mp hz
  exact fits_intCast_iff hk (by omega) (by omega)

/-- Only the "passes ⇒ nonnegative and small" direction, the one soundness proofs use. -/
theorem nonneg_of_fits_intCast {k m : Nat} (hk : k ≤ 252) (hm : m ≤ 252) {z : Int}
    (hz : |z| < 2^m) (h : fits k (z : F)) : 0 ≤ z ∧ z < 2^k :=
  (fits_intCast_iff_of_abs hk hm hz).1 h

/-- An equation in `F` between two integers that differ by less than `p` is a true integer
equation (no wraparound possible). -/
theorem intCast_inj_of_abs_lt {a b : Int} (hab : |a - b| < (p : Int))
    (h : (a : F) = (b : F)) : a = b := by
  have h0 : (((a - b : Int)) : F) = 0 := by rw [Int.cast_sub, h, sub_self]
  have hd : (p : Int) ∣ a - b := (ZMod.intCast_zmod_eq_zero_iff_dvd _ _).1 h0
  have := Int.eq_zero_of_abs_lt_dvd hd hab
  omega

/-- Same, with the convenient bound `|a|, |b| < 2^252`. -/
theorem intCast_inj_of_small {a b : Int} (ha : |a| < 2^252) (hb : |b| < 2^252)
    (h : (a : F) = (b : F)) : a = b := by
  have hp := two_pow_253_lt_p
  have h3 : (2:Int)^253 = 2^252 + 2^252 := by norm_num
  have ⟨a1, a2⟩ := abs_lt.mp ha
  have ⟨b1, b2⟩ := abs_lt.mp hb
  exact intCast_inj_of_abs_lt (abs_lt.mpr ⟨by omega, by omega⟩) h

end Popfv

#print axioms Popfv.fits_intCast_iff
#print axioms Popfv.fits_intCast_iff_of_abs
#print axioms Popfv.intCast_inj_of_abs_lt
#print axioms Popfv.intCast_inj_of_small
#print axioms Popfv.fits_natCast
