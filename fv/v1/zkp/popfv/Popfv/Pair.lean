import Popfv.Field

/-!
# Block G: the `pair` circuit (`noir/pair/src/main.nr`, 37 lines)

Literal model of `main` in `pair/src/main.nr`. Line numbers below refer to that file
unless marked `lib.nr`.

* `hash_n` (lib.nr line 75, Poseidon2 sponge) is an opaque function `H : F → List F → F`.
  Commitment binding is out of scope: the two commitment checks stay in the model but the
  distance theorems never use them.
* `u8` / `u32` inputs are naturals with a range hypothesis; `x as Field` is the natural cast.
* `assert_max_bit_size::<k>()` is `fits k`.
-/

set_option linter.style.whitespace false
set_option linter.style.longLine false
set_option linter.style.header false

namespace Popfv

/-- `pub global TAG_HALF: Field = 8;` (lib.nr line 44). -/
def TAG_HALF : F := 8

/-- Every constraint of `pair/src/main.nr`, in source order.
`xa`, `xb` are the `[Field; 2]` arrays, written as two components each. -/
def pairCircuit (H : F → List F → F)
    (nonce_hi nonce_lo : F) (attempt : Nat) (commit_a commit_b : F) (sr_a sr_b : Nat)
    (half_a salt_a half_b salt_b : F) (xa0 xa1 xb0 xb1 : F) : Prop :=
  let at_ : F := (attempt : F)                                                   -- line 18
  let sa : F := (sr_a : F)                                                       -- line 19
  let sb : F := (sr_b : F)                                                       -- line 20
  let ca := H TAG_HALF [nonce_hi, nonce_lo, at_, 0, sa, half_a, salt_a, xa0, xa1, xb0, xb1]  -- line 21
  let cb := H TAG_HALF [nonce_hi, nonce_lo, at_, 1, sb, half_b, salt_b, xb0, xb1, xa0, xa1]  -- line 23
  let n := half_a * sb - half_b * sa                                             -- line 33
  let s := sa * sb                                                               -- line 34
  ca = commit_a ∧                                                                -- line 22
  cb = commit_b ∧                                                                -- line 24
  (xa0 ≠ xb0 ∨ xa1 ≠ xb1) ∧                                                      -- line 25
  fits 32 (half_a + 2147483648) ∧                                                -- line 26
  fits 32 (half_b + 2147483648) ∧                                                -- line 27
  fits 17 (sa - 36000) ∧                                                         -- line 28
  fits 17 (96000 - sa) ∧                                                         -- line 29
  fits 17 (sb - 36000) ∧                                                         -- line 30
  fits 17 (96000 - sb) ∧                                                         -- line 31
  fits 70 (34300 * n + 40 * s - 1) ∧                                             -- line 35
  fits 70 (120 * s - 34300 * n - 1)                                              -- line 36

/-! ## Building blocks -/

/-- Lines 26/27: the check on `half + 2^31` means `half` is a signed 32-bit integer. -/
theorem half_of_fits {x : F} (h : fits 32 (x + 2147483648)) :
    ∃ hA : Int, -2^31 ≤ hA ∧ hA < 2^31 ∧ x = (hA : F) := by
  obtain ⟨m, hm, he⟩ := fits_exists_nat h
  refine ⟨(m : Int) - 2^31, ?_, ?_, ?_⟩
  · omega
  · have : (m : Int) < 2^32 := by exact_mod_cast hm
    omega
  · have : x = (m : F) - 2147483648 := eq_sub_of_add_eq he
    rw [this]; push_cast; norm_num

/-- Converse of `half_of_fits`. -/
theorem fits_half {hA : Int} (h1 : -2^31 ≤ hA) (h2 : hA < 2^31) :
    fits 32 ((hA : F) + 2147483648) := by
  have e : (hA : F) + 2147483648 = ((hA + 2^31 : Int) : F) := by push_cast; norm_num
  rw [e, fits_intCast_iff_of_abs (m := 33) (by norm_num) (by norm_num) (abs_lt.mpr ⟨by omega, by omega⟩)]
  omega

/-- Lines 28-31 for one rate: the two checks on a `u32` rate mean `36000 ≤ sr ≤ 96000`. -/
theorem rate_of_fits {r : Nat} (hr : isU32 r) (h1 : fits 17 ((r : F) - 36000))
    (h2 : fits 17 (96000 - (r : F))) : 36000 ≤ r ∧ r ≤ 96000 := by
  have hr' : (r : Int) < 2^32 := by unfold isU32 at hr; exact_mod_cast hr
  have e1 : (r : F) - 36000 = (((r : Int) - 36000 : Int) : F) := by push_cast; ring
  have e2 : 96000 - (r : F) = ((96000 - (r : Int) : Int) : F) := by push_cast; ring
  rw [e1] at h1; rw [e2] at h2
  have a1 := nonneg_of_fits_intCast (m := 33) (by norm_num) (by norm_num)
    (abs_lt.mpr ⟨by omega, by omega⟩) h1
  have a2 := nonneg_of_fits_intCast (m := 33) (by norm_num) (by norm_num)
    (abs_lt.mpr ⟨by omega, by omega⟩) h2
  omega

/-- Converse of `rate_of_fits`. -/
theorem fits_rate {r : Nat} (h1 : 36000 ≤ r) (h2 : r ≤ 96000) :
    fits 17 ((r : F) - 36000) ∧ fits 17 (96000 - (r : F)) := by
  have e1 : (r : F) - 36000 = (((r : Int) - 36000 : Int) : F) := by push_cast; ring
  have e2 : 96000 - (r : F) = ((96000 - (r : Int) : Int) : F) := by push_cast; ring
  rw [e1, e2, fits_intCast_iff_of_abs (m := 33) (by norm_num) (by norm_num) (abs_lt.mpr ⟨by omega, by omega⟩),
    fits_intCast_iff_of_abs (m := 33) (by norm_num) (by norm_num) (abs_lt.mpr ⟨by omega, by omega⟩)]
  omega

/-- The integer numerator `n = hA·srB − hB·srA` is small: `|n| < 2^49`. -/
theorem n_bound {hA hB : Int} {a b : Nat} (hA1 : -2^31 ≤ hA) (hA2 : hA < 2^31)
    (hB1 : -2^31 ≤ hB) (hB2 : hB < 2^31) (ha : a ≤ 96000) (hb : b ≤ 96000) :
    |hA * b - hB * a| ≤ 2^31 * 96000 * 2 := by
  have k1 : |hA * (b : Int)| ≤ 2^31 * 96000 := by
    rw [abs_mul]
    exact mul_le_mul (abs_le.mpr ⟨by omega, by omega⟩) (by rw [Nat.abs_cast]; exact_mod_cast hb)
      (abs_nonneg _) (by norm_num)
  have k2 : |hB * (a : Int)| ≤ 2^31 * 96000 := by
    rw [abs_mul]
    exact mul_le_mul (abs_le.mpr ⟨by omega, by omega⟩) (by rw [Nat.abs_cast]; exact_mod_cast ha)
      (abs_nonneg _) (by norm_num)
  calc |hA * b - hB * a| ≤ |hA * (b : Int)| + |hB * (a : Int)| := abs_sub _ _
    _ ≤ _ := by linarith

/-- The exact arithmetic content of lines 35-36, for genuine integers in range:
both 70-bit checks pass iff `-20 < (34300/2)(hA/srA − hB/srB) < 60` over the rationals.
Both edges are **strict** (the `- 1` turns `≥ 1` into `> 0`), and the `< 2^70` halves
of the checks never bind in this range. -/
theorem distance_iff {hA hB : Int} {a b : Nat} (hA1 : -2^31 ≤ hA) (hA2 : hA < 2^31)
    (hB1 : -2^31 ≤ hB) (hB2 : hB < 2^31) (ha1 : 36000 ≤ a) (ha2 : a ≤ 96000)
    (hb1 : 36000 ≤ b) (hb2 : b ≤ 96000) :
    (fits 70 (34300 * ((hA : F) * (b : F) - (hB : F) * (a : F)) + 40 * ((a : F) * (b : F)) - 1) ∧
     fits 70 (120 * ((a : F) * (b : F)) - 34300 * ((hA : F) * (b : F) - (hB : F) * (a : F)) - 1))
    ↔ ((-20 : ℚ) < (34300 / 2) * ((hA : ℚ) / a - (hB : ℚ) / b) ∧
       (34300 / 2) * ((hA : ℚ) / a - (hB : ℚ) / b) < 60) := by
  set n : Int := hA * b - hB * a with hn
  set s : Int := (a : Int) * b with hs
  have nb := n_bound hA1 hA2 hB1 hB2 ha2 hb2
  have ⟨nb1, nb2⟩ := abs_le.mp nb
  have s0 : 36000 * 36000 ≤ s := by
    have : (36000 : Int) * 36000 ≤ (a : Int) * b :=
      mul_le_mul (by exact_mod_cast ha1) (by exact_mod_cast hb1) (by norm_num) (by positivity)
    simpa [hs] using this
  have s1 : s ≤ 96000 * 96000 := by
    have : (a : Int) * b ≤ 96000 * 96000 :=
      mul_le_mul (by exact_mod_cast ha2) (by exact_mod_cast hb2) (by positivity) (by norm_num)
    simpa [hs] using this
  have e1 : 34300 * ((hA : F) * (b : F) - (hB : F) * (a : F)) + 40 * ((a : F) * (b : F)) - 1
      = ((34300 * n + 40 * s - 1 : Int) : F) := by rw [hn, hs]; push_cast; ring
  have e2 : 120 * ((a : F) * (b : F)) - 34300 * ((hA : F) * (b : F) - (hB : F) * (a : F)) - 1
      = ((120 * s - 34300 * n - 1 : Int) : F) := by rw [hn, hs]; push_cast; ring
  rw [e1, e2,
    fits_intCast_iff_of_abs (m := 80) (by norm_num) (by norm_num) (abs_lt.mpr ⟨by omega, by omega⟩),
    fits_intCast_iff_of_abs (m := 80) (by norm_num) (by norm_num) (abs_lt.mpr ⟨by omega, by omega⟩)]
  -- rational side
  have aq : (0 : ℚ) < a := by have : (0 : Nat) < a := by omega
                              exact_mod_cast this
  have bq : (0 : ℚ) < b := by have : (0 : Nat) < b := by omega
                              exact_mod_cast this
  have sq : (0 : ℚ) < (s : ℚ) := by have : (0 : Int) < s := by omega
                                    exact_mod_cast this
  have hX : (34300 / 2) * ((hA : ℚ) / a - (hB : ℚ) / b) = (34300 * (n : ℚ)) / (2 * (s : ℚ)) := by
    rw [hn, hs]; push_cast; field_simp
  rw [hX, lt_div_iff₀ (by positivity), div_lt_iff₀ (by positivity)]
  constructor
  · rintro ⟨⟨h1, _⟩, ⟨h2, _⟩⟩
    have q1 : ((0 : Int) : ℚ) < ((34300 * n + 40 * s : Int) : ℚ) := by exact_mod_cast (by omega : (0:Int) < 34300 * n + 40 * s)
    have q2 : ((0 : Int) : ℚ) < ((120 * s - 34300 * n : Int) : ℚ) := by exact_mod_cast (by omega : (0:Int) < 120 * s - 34300 * n)
    push_cast at q1 q2
    constructor <;> linarith
  · rintro ⟨h1, h2⟩
    have q1 : ((0 : Int) : ℚ) < ((34300 * n + 40 * s : Int) : ℚ) := by push_cast; linarith
    have q2 : ((0 : Int) : ℚ) < ((120 * s - 34300 * n : Int) : ℚ) := by push_cast; linarith
    have r1 : (0 : Int) < 34300 * n + 40 * s := by exact_mod_cast q1
    have r2 : (0 : Int) < 120 * s - 34300 * n := by exact_mod_cast q2
    refine ⟨⟨by omega, ?_⟩, ⟨by omega, ?_⟩⟩
    · have : (34300 : Int) * n + 40 * s - 1 < 2^70 := by omega
      exact this
    · have : (120 : Int) * s - 34300 * n - 1 < 2^70 := by omega
      exact this

/-! ## Main theorems -/

/-- **Keys-differ constraint (line 25).** The Noir check `(xa[0] != xb[0]) | (xa[1] != xb[1])`
says exactly that the two key pairs are different. -/
theorem keys_differ_iff (xa0 xa1 xb0 xb1 : F) :
    (xa0 ≠ xb0 ∨ xa1 ≠ xb1) ↔ (xa0, xa1) ≠ (xb0, xb1) := by
  simp only [ne_eq, Prod.mk.injEq]
  tauto


/-- **Pair soundness (block G).** If every constraint of the `pair` circuit holds, and the
public `u32`/`u8` inputs are in their type ranges, then:
* the two hidden half-distances are genuine signed 32-bit integers `hA`, `hB`;
* both sample rates are between 36000 and 96000;
* the two key pairs differ;
* and, in real-number arithmetic with no wraparound,
  `-20 < (34300/2)·(hA/srA − hB/srB) < 60`, with **both** ends strict.
The commitment checks are kept but not used (hash binding is out of scope). -/
theorem pair_sound (H : F → List F → F)
    (nonce_hi nonce_lo : F) (attempt : Nat) (commit_a commit_b : F) (sr_a sr_b : Nat)
    (half_a salt_a half_b salt_b : F) (xa0 xa1 xb0 xb1 : F)
    (_hat : isU8 attempt) (hsa : isU32 sr_a) (hsb : isU32 sr_b)
    (hc : pairCircuit H nonce_hi nonce_lo attempt commit_a commit_b sr_a sr_b
            half_a salt_a half_b salt_b xa0 xa1 xb0 xb1) :
    ∃ hA hB : Int,
      (-2^31 ≤ hA ∧ hA < 2^31) ∧ (-2^31 ≤ hB ∧ hB < 2^31) ∧
      half_a = (hA : F) ∧ half_b = (hB : F) ∧
      (36000 ≤ sr_a ∧ sr_a ≤ 96000) ∧ (36000 ≤ sr_b ∧ sr_b ≤ 96000) ∧
      (xa0, xa1) ≠ (xb0, xb1) ∧
      (-20 : ℚ) < (34300 / 2) * ((hA : ℚ) / sr_a - (hB : ℚ) / sr_b) ∧
      (34300 / 2) * ((hA : ℚ) / sr_a - (hB : ℚ) / sr_b) < 60 := by
  obtain ⟨_, _, hx, h26, h27, h28, h29, h30, h31, h35, h36⟩ := hc
  obtain ⟨hA, hA1, hA2, rfl⟩ := half_of_fits h26
  obtain ⟨hB, hB1, hB2, rfl⟩ := half_of_fits h27
  obtain ⟨a1, a2⟩ := rate_of_fits hsa h28 h29
  obtain ⟨b1, b2⟩ := rate_of_fits hsb h30 h31
  have hd := (distance_iff hA1 hA2 hB1 hB2 a1 a2 b1 b2).1 ⟨h35, h36⟩
  exact ⟨hA, hB, ⟨hA1, hA2⟩, ⟨hB1, hB2⟩, rfl, rfl, ⟨a1, a2⟩, ⟨b1, b2⟩,
    (keys_differ_iff xa0 xa1 xb0 xb1).1 hx, hd.1, hd.2⟩

/-- **Pair completeness (block G).** Conversely, honest inputs pass: take signed 32-bit
half-distances `hA`, `hB`, rates in [36000, 96000], different key pairs, and the strict
inequality `-20 < (34300/2)·(hA/srA − hB/srB) < 60`; if the public commitments are the
hashes of the openings, every constraint of the circuit holds. -/
theorem pair_complete (H : F → List F → F)
    (nonce_hi nonce_lo : F) (attempt : Nat) (sr_a sr_b : Nat)
    (hA hB : Int) (salt_a salt_b : F) (xa0 xa1 xb0 xb1 : F)
    (hA1 : -2^31 ≤ hA) (hA2 : hA < 2^31) (hB1 : -2^31 ≤ hB) (hB2 : hB < 2^31)
    (a1 : 36000 ≤ sr_a) (a2 : sr_a ≤ 96000) (b1 : 36000 ≤ sr_b) (b2 : sr_b ≤ 96000)
    (hx : (xa0, xa1) ≠ (xb0, xb1))
    (d1 : (-20 : ℚ) < (34300 / 2) * ((hA : ℚ) / sr_a - (hB : ℚ) / sr_b))
    (d2 : (34300 / 2) * ((hA : ℚ) / sr_a - (hB : ℚ) / sr_b) < 60) :
    pairCircuit H nonce_hi nonce_lo attempt
      (H TAG_HALF [nonce_hi, nonce_lo, (attempt : F), 0, (sr_a : F), (hA : F), salt_a, xa0, xa1, xb0, xb1])
      (H TAG_HALF [nonce_hi, nonce_lo, (attempt : F), 1, (sr_b : F), (hB : F), salt_b, xb0, xb1, xa0, xa1])
      sr_a sr_b (hA : F) salt_a (hB : F) salt_b xa0 xa1 xb0 xb1 := by
  have hd := (distance_iff hA1 hA2 hB1 hB2 a1 a2 b1 b2).2 ⟨d1, d2⟩
  obtain ⟨r1, r2⟩ := fits_rate a1 a2
  obtain ⟨r3, r4⟩ := fits_rate b1 b2
  have hx' := (keys_differ_iff xa0 xa1 xb0 xb1).2 hx
  exact ⟨rfl, rfl, hx', fits_half hA1 hA2, fits_half hB1 hB2, r1, r2, r3, r4, hd.1, hd.2⟩

end Popfv

#print axioms Popfv.pair_sound
#print axioms Popfv.pair_complete
#print axioms Popfv.distance_iff
#print axioms Popfv.keys_differ_iff
