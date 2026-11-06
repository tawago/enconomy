import Popfv.Field

/-!
# Popfv.Bar — BAR = 4474747 is the integer form of "score ≥ 0.09"   (fv/v1/docs/03-bar.md, layer 1)

Circuit side (`oalib/src/lib.nr`):
* line 33:      `pub global BAR: Field = 4474747; // B = round(g^2 / 0.09^2)`
* line 353-358: `cna = Σ c_i[n]^2`                                    (template energy cn2)
* line 400-401: self side   `env2 = ci^2 + cq^2`, `d = big_c - BAR * env2`, `big_c = E * cn2`
* line 470-472: partner side `penv2 = ii^2 + qq^2`, `v = BAR * penv2 - ep * cnp`, `v.assert_max_bit_size::<96>()`

So every bar test in the circuit is the integer comparison `B * m ≥ L` with
`m = I² + Q²` (match energy) and `L = E · cn2` (loudness × template energy).
Design side (`server/pop/popt2.py:26`): `score = g · sqrt(m / L)`, `B = round(g² / T0²)`, `T0 = 0.09`.

What is proved here:
1. `bar_iff_ratio`, `bar_iff_sqrt`: `B·m ≥ L  ↔  m/L ≥ 1/B  ↔  sqrt(m/L) ≥ 1/sqrt B` (exact, no rounding).
2. `bar_iff_score`: with `T0eff = g / sqrt B`, `B·m ≥ L ↔ g·sqrt(m/L) ≥ T0eff`.
3. `T0eff_close`: if `B = round(g²/T0²)` then `|T0eff − T0| ≤ T0 / (2B)` (≈ 1e-8 at B = 4474747).
4. Numbers: rigorous intervals for `1/sqrt 4474747`, `1/sqrt 3792174`. The exact `g` condition for
   rounding to B is `round_eq_iff_g2` (stated on `g²`). In decimals, for each B: `g_range_*` is a
   necessary outer interval (round = B implies g inside), `g_range_*_sufficient` is a sufficient
   inner interval (g inside implies round = B). The two differ by 1e-8 at each end.
   Layer 2 (`scripts/bar_check.py`) computes g itself and lands inside the inner interval.
5. `partner_bar_of_fits` / `fits_of_partner_bar`: the field check `fits 96 (B·m − L)` (lib.nr 471-472)
   gives `B·m ≥ L` over ℤ, and conversely. `self_before_arrival` / `self_at_arrival`: same for the
   self side `v = uj·(d−1) − e·d` (lib.nr 400-405).
6. HOLE (section 6): `0 < L` is ASSUMED in 1-5, the circuit does NOT enforce it. With a silent
   recording (L = 0, m = 0) both the partner check and the self arrival check pass, while the
   score is 0/0 (not ≥ 0.09). `partner_silence_accepts`, `self_silence_accepts`, `silence_score_below_bar`.

Width hypotheses `|B·m − L| < 2^250` (or 2^249) are ASSUMED here; to be discharged by the D/E width
proofs (by hand: |B·m − L| ≤ 4474747·2·(12000·128·32768)² < 2^95).
On the self side the D/E widths are not enough. `ci[j]`, `cq[j]` are free Field witnesses, so the
hand bound on `m = ci² + cq²` holds only once block C (Freivalds) says they are the true
correlations. `Arrival.lean` takes that as an explicit assumption. Nothing here proves it.
-/

set_option linter.style.whitespace false
set_option linter.style.longLine false
set_option linter.style.header false

namespace Popfv

open Real

/-! ## 1. The integer test is exactly a ratio / square-root test -/

/-- The circuit's integer bar `B·m ≥ L` says exactly "match / loudness ≥ 1/B" as real numbers.
No rounding, no approximation. `0 < L` is ASSUMED, NOT enforced by the circuit (see section 6). -/
theorem bar_iff_ratio (m L B : ℤ) (hL : 0 < L) (hB : 0 < B) :
    L ≤ B * m ↔ (1 : ℝ) / B ≤ (m : ℝ) / L := by
  have hL' : (0 : ℝ) < L := by exact_mod_cast hL
  have hB' : (0 : ℝ) < B := by exact_mod_cast hB
  rw [div_le_div_iff₀ hB' hL', one_mul]
  constructor
  · intro h; have : ((L : ℤ) : ℝ) ≤ ((B * m : ℤ) : ℝ) := by exact_mod_cast h
    push_cast at this; linarith
  · intro h; have : ((L : ℤ) : ℝ) ≤ ((B * m : ℤ) : ℝ) := by push_cast; linarith
    exact_mod_cast this

/-- Same test with square roots: `B·m ≥ L` iff `sqrt(m/L) ≥ 1/sqrt B`.
So the circuit accepts exactly when the normalised score `sqrt((I²+Q²)/(E·cn2))` reaches `1/sqrt B`.
`0 < L` is ASSUMED, NOT enforced by the circuit (see section 6). -/
theorem bar_iff_sqrt (m L B : ℤ) (hm : 0 ≤ m) (hL : 0 < L) (hB : 0 < B) :
    L ≤ B * m ↔ 1 / Real.sqrt B ≤ Real.sqrt ((m : ℝ) / L) := by
  have hB' : (0 : ℝ) < B := by exact_mod_cast hB
  have hm' : (0 : ℝ) ≤ m := by exact_mod_cast hm
  have hL' : (0 : ℝ) < L := by exact_mod_cast hL
  have e : (1 : ℝ) / Real.sqrt B = Real.sqrt (1 / B) := by rw [one_div, one_div, Real.sqrt_inv]
  rw [bar_iff_ratio m L B hL hB, e]
  exact (Real.sqrt_le_sqrt_iff (div_nonneg hm' hL'.le)).symm

/-- The negation, used on the self side before the arrival (lib.nr 400-405, `u = 1`):
`B·m < L` iff `sqrt(m/L) < 1/sqrt B` ("still below the bar"). `0 < L` ASSUMED, not enforced. -/
theorem below_bar_iff_sqrt (m L B : ℤ) (hm : 0 ≤ m) (hL : 0 < L) (hB : 0 < B) :
    B * m < L ↔ Real.sqrt ((m : ℝ) / L) < 1 / Real.sqrt B := by
  rw [← not_le, ← not_le]
  exact not_congr (bar_iff_sqrt m L B hm hL hB)

/-! ## 2. Effective threshold `T0eff = g / sqrt B` -/

/-- The threshold the circuit really enforces, in score units. -/
noncomputable def T0eff (B g : ℝ) : ℝ := g / Real.sqrt B

/-- With the physical score `g·sqrt(m/L)` (g = filter gain), the circuit accepts iff
score ≥ `T0eff B g = g / sqrt B`. `0 < L` ASSUMED, not enforced by the circuit. -/
theorem bar_iff_score (m L B : ℤ) (g : ℝ) (hg : 0 < g) (hm : 0 ≤ m) (hL : 0 < L) (hB : 0 < B) :
    L ≤ B * m ↔ T0eff B g ≤ g * Real.sqrt ((m : ℝ) / L) := by
  rw [bar_iff_sqrt m L B hm hL hB, T0eff, div_eq_mul_one_div g]
  exact (mul_le_mul_iff_of_pos_left hg).symm

/-- Rounding costs almost nothing: if `B` is `g²/T0²` rounded to the nearest whole number, the
enforced threshold `g / sqrt B` is within `T0 / (2B)` of the intended `T0`. -/
theorem T0eff_close (B g T0 : ℝ) (hB : 0 < B) (hg : 0 < g) (hT : 0 < T0)
    (hround : |B - g ^ 2 / T0 ^ 2| ≤ 1 / 2) :
    |T0eff B g - T0| ≤ T0 / (2 * B) := by
  set s := Real.sqrt B with hs
  set t := g / T0 with ht
  have hs0 : 0 < s := Real.sqrt_pos.mpr hB
  have hss : s * s = B := Real.mul_self_sqrt hB.le
  have ht0 : 0 < t := div_pos hg hT
  have htt : t ^ 2 = g ^ 2 / T0 ^ 2 := by rw [ht, div_pow]
  -- |t - s| ≤ 1 / (2 (t + s)) ≤ 1 / (2 s)
  have key : |t - s| * (t + s) ≤ 1 / 2 := by
    have e1 : |t - s| * (t + s) = |t ^ 2 - s * s| := by
      rw [show t ^ 2 - s * s = (t - s) * (t + s) by ring, abs_mul,
        abs_of_pos (by linarith : (0:ℝ) < t + s)]
    have e2 : |B - g ^ 2 / T0 ^ 2| = |t ^ 2 - s * s| := by rw [← htt, ← hss, abs_sub_comm]
    linarith
  have h1 : |t - s| * s ≤ 1 / 2 := le_trans (mul_le_mul_of_nonneg_left (by linarith) (abs_nonneg _)) key
  have hT0eff : T0eff B g - T0 = T0 * (t - s) / s := by
    rw [T0eff, ← hs, ht]; field_simp
  rw [hT0eff, abs_div, abs_mul, abs_of_pos hT, abs_of_pos hs0, div_le_div_iff₀ hs0 (by positivity), ← hss]
  have := mul_le_mul_of_nonneg_left h1 (le_of_lt (mul_pos hT hs0))
  nlinarith [abs_nonneg (t - s)]

/-- `round` form of the hypothesis of `T0eff_close`. -/
theorem T0eff_close_round (B : ℤ) (g T0 : ℝ) (hB : 0 < B) (hg : 0 < g) (hT : 0 < T0)
    (hround : B = round (g ^ 2 / T0 ^ 2)) :
    |T0eff B g - T0| ≤ T0 / (2 * B) := by
  apply T0eff_close _ g T0 (by exact_mod_cast hB) hg hT
  rw [hround, abs_sub_comm]; exact abs_sub_round _

/-! ## 3. g range that rounds to a given B (T0 = 0.09) -/

/-- `round(g²/0.09²) = B` exactly when `0.0081·(B − ½) ≤ g² < 0.0081·(B + ½)`. -/
theorem round_eq_iff_g2 (B : ℤ) (g : ℝ) :
    round (g ^ 2 / (9 / 100 : ℝ) ^ 2) = B ↔
      (81 / 10000 : ℝ) * (B - 1 / 2) ≤ g ^ 2 ∧ g ^ 2 < (81 / 10000 : ℝ) * (B + 1 / 2) := by
  rw [round_eq, Int.floor_eq_iff, show g ^ 2 / (9 / 100 : ℝ) ^ 2 = g ^ 2 * (10000 / 81) by ring]
  constructor <;> rintro ⟨h1, h2⟩ <;> constructor <;> linarith

/-- 48 kHz, NECESSARY direction only: if `round(g²/0.09²) = 4474747` and `g > 0`, then
`36245.44665 ≤ g² < 36245.45475` and g lies in the outer interval `(190.38236958, 190.38239087)`.
Not every g in that interval rounds to B: the exact statement is `round_eq_iff_g2`, and the
converse in decimals is `g_range_48k_sufficient`. -/
theorem g_range_48k (g : ℝ) (hg : 0 < g) (h : round (g ^ 2 / (9 / 100 : ℝ) ^ 2) = 4474747) :
    (3624544665 / 100000 : ℝ) ≤ g ^ 2 ∧ g ^ 2 < 3624545475 / 100000 ∧
      (19038236958 / 100000000 : ℝ) < g ∧ g < 19038239087 / 100000000 := by
  obtain ⟨h1, h2⟩ := (round_eq_iff_g2 4474747 g).mp h
  push_cast at h1 h2
  refine ⟨by linarith, by linarith, ?_, ?_⟩ <;> nlinarith

/-- 48 kHz, SUFFICIENT direction: any g in `[190.38236959, 190.38239086]` rounds to 4474747.
Layer 2 computes g = 190.3823795841…, which is inside, so this is the theorem that makes
"g rounds to BAR" follow from the number. -/
theorem g_range_48k_sufficient (g : ℝ) (h1 : (19038236959 / 100000000 : ℝ) ≤ g)
    (h2 : g ≤ 19038239086 / 100000000) :
    round (g ^ 2 / (9 / 100 : ℝ) ^ 2) = 4474747 := by
  refine (round_eq_iff_g2 4474747 g).mpr ?_
  push_cast
  constructor <;> nlinarith

/-- 44.1 kHz, NECESSARY direction only: if `round(g²/0.09²) = 3792174` and `g > 0`, then
`30716.60535 ≤ g² < 30716.61345` and g lies in the outer interval `(175.26153414, 175.26155726)`.
Not every g in that interval rounds to B: the exact statement is `round_eq_iff_g2`, and the
converse in decimals is `g_range_44k_sufficient`. -/
theorem g_range_44k (g : ℝ) (hg : 0 < g) (h : round (g ^ 2 / (9 / 100 : ℝ) ^ 2) = 3792174) :
    (3071660535 / 100000 : ℝ) ≤ g ^ 2 ∧ g ^ 2 < 3071661345 / 100000 ∧
      (17526153414 / 100000000 : ℝ) < g ∧ g < 17526155726 / 100000000 := by
  obtain ⟨h1, h2⟩ := (round_eq_iff_g2 3792174 g).mp h
  push_cast at h1 h2
  refine ⟨by linarith, by linarith, ?_, ?_⟩ <;> nlinarith

/-- 44.1 kHz, SUFFICIENT direction: any g in `[175.26153415, 175.26155725]` rounds to 3792174.
Layer 2 computes g = 175.2615551320…, which is inside (close to the top edge: margin 0.092 of 0.5).
3792174 is a design value only: lib.nr 240 asserts `sr == SR` (48000), no 44.1 kHz circuit exists. -/
theorem g_range_44k_sufficient (g : ℝ) (h1 : (17526153415 / 100000000 : ℝ) ≤ g)
    (h2 : g ≤ 17526155725 / 100000000) :
    round (g ^ 2 / (9 / 100 : ℝ) ^ 2) = 3792174 := by
  refine (round_eq_iff_g2 3792174 g).mpr ?_
  push_cast
  constructor <;> nlinarith

/-! ## 4. Rigorous intervals for 1/sqrt B -/

lemma inv_sqrt_bounds (B lo hi : ℝ) (hlo : 0 < lo) (hhi : 0 < hi) (h1 : lo ^ 2 < B) (h2 : B < hi ^ 2) :
    1 / hi < 1 / Real.sqrt B ∧ 1 / Real.sqrt B < 1 / lo := by
  have hs1 : lo < Real.sqrt B := (Real.lt_sqrt hlo.le).mpr h1
  have hs2 : Real.sqrt B < hi := (Real.sqrt_lt' hhi).mpr h2
  have hs0 : 0 < Real.sqrt B := by linarith
  exact ⟨one_div_lt_one_div_of_lt hs0 hs2, one_div_lt_one_div_of_lt hlo hs1⟩

/-- 48 kHz bar in score units: `0.000472732822721 < 1/sqrt 4474747 < 0.000472732822722`
(sqrt 4474747 = 2115.3597802737…). -/
theorem inv_sqrt_4474747 :
    (472732822721 / 10 ^ 15 : ℝ) < 1 / Real.sqrt 4474747 ∧
      1 / Real.sqrt 4474747 < (472732822722 / 10 ^ 15 : ℝ) := by
  obtain ⟨a, b⟩ := inv_sqrt_bounds 4474747 (21153597802737 / 10 ^ 10) (21153597802738 / 10 ^ 10)
    (by norm_num) (by norm_num) (by norm_num) (by norm_num)
  constructor
  · refine lt_trans ?_ a; norm_num
  · refine lt_trans b ?_; norm_num

/-- 44.1 kHz: `0.000513518237227 < 1/sqrt 3792174 < 0.000513518237228`
(sqrt 3792174 = 1947.3505077412…). -/
theorem inv_sqrt_3792174 :
    (513518237227 / 10 ^ 15 : ℝ) < 1 / Real.sqrt 3792174 ∧
      1 / Real.sqrt 3792174 < (513518237228 / 10 ^ 15 : ℝ) := by
  obtain ⟨a, b⟩ := inv_sqrt_bounds 3792174 (19473505077412 / 10 ^ 10) (19473505077413 / 10 ^ 10)
    (by norm_num) (by norm_num) (by norm_num) (by norm_num)
  constructor
  · refine lt_trans ?_ a; norm_num
  · refine lt_trans b ?_; norm_num

/-- 48 kHz, end to end: for any gain g that rounds to BAR = 4474747, the enforced threshold
`g / sqrt 4474747` is within about 1e-8 of 0.09 (relative error ≤ 1/(2·4474747) ≈ 1.1e-7). -/
theorem T0eff_48k (g : ℝ) (hg : 0 < g) (h : round (g ^ 2 / (9 / 100 : ℝ) ^ 2) = 4474747) :
    |T0eff 4474747 g - 9 / 100| ≤ (9 / 100) / (2 * 4474747) := by
  have := T0eff_close_round 4474747 g (9 / 100) (by norm_num) hg (by norm_num) h.symm
  push_cast at this; exact this

/-- 44.1 kHz version: within `0.09 / (2·3792174)` ≈ 1.2e-8 of 0.09. -/
theorem T0eff_44k (g : ℝ) (hg : 0 < g) (h : round (g ^ 2 / (9 / 100 : ℝ) ^ 2) = 3792174) :
    |T0eff 3792174 g - 9 / 100| ≤ (9 / 100) / (2 * 3792174) := by
  have := T0eff_close_round 3792174 g (9 / 100) (by norm_num) hg (by norm_num) h.symm
  push_cast at this; exact this

/-! ## 5. Bridge from the field check (lib.nr 470-472) -/

/-- Partner side, lib.nr 471-472: `v = BAR * penv2 - ep * cnp; v.assert_max_bit_size::<96>()`,
with `m = penv2 = ii² + qq²` and `L = ep · cnp`.
If the check passes, the score reaches the bar (one direction; the converse is
`fits_of_partner_bar`). Two hypotheses are ASSUMED, not proved from the circuit:
* `0 < L` — the circuit does NOT enforce it (section 6: silence passes);
* `|B·m − L| < 2^250` — assumed here; to be discharged by the D/E width proofs
  (partner `ii`, `qq`, `ep` are computed in the circuit, so no Freivalds step is needed). -/
theorem partner_bar_of_fits (m L B : ℤ) (hm : 0 ≤ m) (hL : 0 < L) (hB : 0 < B)
    (hsmall : |B * m - L| < 2 ^ 250)
    (hfits : fits 96 (((B : F) * (m : F)) - (L : F))) :
    1 / Real.sqrt B ≤ Real.sqrt ((m : ℝ) / L) := by
  have hcast : ((B : F) * (m : F)) - (L : F) = ((B * m - L : ℤ) : F) := by push_cast; ring
  rw [hcast] at hfits
  have := (nonneg_of_fits_intCast (k := 96) (m := 250) (by norm_num) (by norm_num) hsmall hfits).1
  exact (bar_iff_sqrt m L B hm hL hB).mp (by linarith)

/-- Converse of the partner check (no false reject): if `B·m ≥ L` over the integers and
`B·m − L < 2^96`, the field check `fits 96 (B·m − L)` passes. (By hand `B·m < 2^95` in the
circuit, so the 96-bit cap never rejects an honest pass; that bound is for blocks D/E.) -/
theorem fits_of_partner_bar (m L B : ℤ) (hge : L ≤ B * m) (hlt : B * m - L < 2 ^ 96) :
    fits 96 (((B : F) * (m : F)) - (L : F)) := by
  have hcast : ((B : F) * (m : F)) - (L : F) = ((B * m - L : ℤ) : F) := by push_cast; ring
  rw [hcast]
  have h0 : 0 ≤ B * m - L := by linarith
  have habs : |B * m - L| < 2 ^ 96 := by rw [abs_of_nonneg h0]; exact hlt
  exact (fits_intCast_iff_of_abs (k := 96) (m := 96) (by norm_num) (by norm_num) habs).2 ⟨h0, hlt⟩

/-- Self side before the arrival, lib.nr 400-405 with `u[j-1] = 1, u[j] = 1` (so `e = 1 − 1`):
`d = big_c − BAR·env2 = L − B·m`, `v = uj·(d−1) − e·d`. If `v` fits 96 bits then `B·m < L`
("still below the bar"; with `0 < L` this is `below_bar_iff_sqrt`).
`|L − B·m| < 2^249` is ASSUMED; to be discharged by the D/E width proofs plus block C (Freivalds),
since `ci`, `cq` inside `m` are free Field witnesses. -/
theorem self_before_arrival (m L B : ℤ) (hsmall : |L - B * m| < 2 ^ 249)
    (hfits : fits 96 ((1 : F) * ((((L : F)) - (B : F) * (m : F)) - 1)
      - ((1 : F) - 1) * (((L : F)) - (B : F) * (m : F)))) :
    B * m < L := by
  have hcast : (1 : F) * ((((L : F)) - (B : F) * (m : F)) - 1) - ((1 : F) - 1) * (((L : F)) - (B : F) * (m : F))
      = ((L - B * m - 1 : ℤ) : F) := by push_cast; ring
  rw [hcast] at hfits
  have hb : |L - B * m - 1| < 2 ^ 250 := by
    have := abs_sub (L - B * m) 1
    simp at this; linarith
  have := (nonneg_of_fits_intCast (k := 96) (m := 250) (by norm_num) (by norm_num) hb hfits).1
  linarith

/-- Self side at the arrival lag, lib.nr 400-405 with `u[j-1] = 1, u[j] = 0` (or `j = 0, u[0] = 0`),
so `uj = 0, e = 1`, `v = −d = B·m − L`. If `v` fits 96 bits then `B·m ≥ L` (score reaches the bar
when `0 < L`, by `bar_iff_sqrt`). `|L − B·m| < 2^250` ASSUMED (blocks D/E, plus block C for the
free witnesses `ci`, `cq` inside `m`). -/
theorem self_at_arrival (m L B : ℤ) (hsmall : |L - B * m| < 2 ^ 250)
    (hfits : fits 96 ((0 : F) * ((((L : F)) - (B : F) * (m : F)) - 1)
      - ((1 : F) - 0) * (((L : F)) - (B : F) * (m : F)))) :
    L ≤ B * m := by
  have hcast : (0 : F) * ((((L : F)) - (B : F) * (m : F)) - 1) - ((1 : F) - 0) * (((L : F)) - (B : F) * (m : F))
      = ((B * m - L : ℤ) : F) := by push_cast; ring
  rw [hcast] at hfits
  have hb : |B * m - L| < 2 ^ 250 := by rw [abs_sub_comm]; exact hsmall
  have := (nonneg_of_fits_intCast (k := 96) (m := 250) (by norm_num) (by norm_num) hb hfits).1
  linarith

/-! ## 6. HOLE: silence passes both bars (`0 < L` is not enforced)

Witness: `xs = xp = [32768; NT]` (digital silence: int16 0 + 32768), `ci = cq = 0`,
`u = [false; K]`, `a_self = p_self − DELTA` (so `usum_target = 0`), any template.
Then every `wi = 0`, so `y = 0`, `ep = ey = 0`, `ii = qq = 0`; Freivalds forces `ci = cq = 0`.
Partner: `v = BAR·(0·0 + 0·0) − 0·cnp = 0` fits. Self: `big_c = 0`, `env2 = 0`, `d = 0`;
at `j = 0`, `uj = 0`, `e = 1`, `v = 0 − 1·0 = 0` fits; elsewhere `uj = e = 0`, `v = 0`.
The score `sqrt(0/0)` is undefined (0 in Lean), NOT ≥ 0.09. Fix idea: assert `ep·cnp ≥ 1`
(an energy floor) in `partner_side`, and `(ey − eyf[j])·cna ≥ 1` at the arrival lag. -/

/-- HOLE, partner side (lib.nr 470-472): when the opened window is silent (`ii = qq = ep = 0`),
the check `BAR·(ii² + qq²) − ep·cnp` fits 96 bits for ANY template energy `cnp`. -/
theorem partner_silence_accepts (cnp : F) :
    fits 96 ((4474747 : F) * ((0 : F) * 0 + (0 : F) * 0) - (0 : F) * cnp) := by
  simp [fits]

/-- HOLE, self side (lib.nr 400-405) at the arrival lag `j = 0` with `u[0] = 0` (`uj = 0, e = 1`)
and silence (`big_c = L = 0`, `env2 = m = 0`): `v = 0` fits 96 bits. -/
theorem self_silence_accepts :
    fits 96 ((0 : F) * ((((0 : ℤ) : F) - (4474747 : F) * ((0 : ℤ) : F)) - 1)
      - ((1 : F) - 0) * (((0 : ℤ) : F) - (4474747 : F) * ((0 : ℤ) : F))) := by
  simp [fits]

/-- …while the silent recording does NOT reach the bar in score units: `sqrt(0/0) = 0 < 1/sqrt B`.
So the circuit accepts something the informal claim "score ≥ 0.09" rejects. -/
theorem silence_score_below_bar (B : ℝ) (hB : 0 < B) :
    ¬ (1 / Real.sqrt B ≤ Real.sqrt ((0 : ℝ) / 0)) := by
  have : 0 < 1 / Real.sqrt B := by positivity
  simp only [div_zero, Real.sqrt_zero]; linarith

end Popfv

#print axioms Popfv.bar_iff_ratio
#print axioms Popfv.bar_iff_sqrt
#print axioms Popfv.below_bar_iff_sqrt
#print axioms Popfv.bar_iff_score
#print axioms Popfv.T0eff_close
#print axioms Popfv.T0eff_close_round
#print axioms Popfv.round_eq_iff_g2
#print axioms Popfv.g_range_48k
#print axioms Popfv.g_range_44k
#print axioms Popfv.g_range_48k_sufficient
#print axioms Popfv.g_range_44k_sufficient
#print axioms Popfv.inv_sqrt_4474747
#print axioms Popfv.inv_sqrt_3792174
#print axioms Popfv.T0eff_48k
#print axioms Popfv.T0eff_44k
#print axioms Popfv.partner_bar_of_fits
#print axioms Popfv.fits_of_partner_bar
#print axioms Popfv.self_before_arrival
#print axioms Popfv.self_at_arrival
#print axioms Popfv.partner_silence_accepts
#print axioms Popfv.self_silence_accepts
#print axioms Popfv.silence_score_below_bar
