import Popfv.Field

/-!
# Popfv.PartnerGlue — blocks E (`partner_side`) and F (`phone_core` glue)

Source: `research/worldid/prototypes/optA-noir/noir/oalib/src/lib.nr` (deployed variant `phone_core`,
not `*_opt`). Line numbers below refer to that file.

Modelling conventions
* Byte arrays (`[u8; T]`) and sample arrays (`[u16; NT]`) are functions `Nat → Nat`; the type range
  of the entries we read is an explicit hypothesis.
* `w(e)` (line 14) is a hint plus `assert(v == e)`, so it is the identity.
* Loops are modelled as recursions over the loop counter, one constraint per step in source order.

What this file does NOT prove (all disclosed, see also `phone_core_glue`):
* `fits 8 leaf_s` / `fits 8 leaf_p` are hypotheses standing in for `idx.to_le_bits()` into `[bool; 8]` at
  line 109, reached with `i = 0` from `open_leaves` (line 127). `merkle_root` is not modelled here. The
  circuit is stronger (`leaf + i` for every `i < 13`), and we use only `i = 0`. That Noir's `to_le_bits`
  behaves as documented is trusted.
* That `xs`, `xp` really are the recording under `rec_root` is block B (Poseidon2 binding), not here.
* The arrival loop of `self_side` is `Arrival.lean`; here we use only its usum lines (361, 369).
* The half commitment (lines 528-534) is `hash_n`, an opaque hash. We model the call and its argument list
  (`halfCommit`). Binding is an explicit hypothesis, never proved (`half_commit_binds`).
* What the partner check means as a physical score is `Bar.lean` (`bar_iff_score`, `T0eff_48k`).
-/

set_option linter.style.whitespace false
set_option linter.style.longLine false
set_option linter.style.header false

namespace Popfv
namespace PartnerGlue

/-! ## Transcript helpers `be_f`, `signed32` (lib.nr 171-182) -/

/-- `be_f(t, off, n)`, lib.nr 171-177: `v = 0; for i in 0..n { v = v * 256 + t[off + i] }` in `Field`. -/
def beF (t : Nat → Nat) (off : Nat) : Nat → F
  | 0 => 0
  | n + 1 => beF t off n * 256 + (t (off + n) : F)

/-- The same loop over the natural numbers (no wraparound): the big-endian value of the bytes. -/
def beNat (t : Nat → Nat) (off : Nat) : Nat → Nat
  | 0 => 0
  | n + 1 => beNat t off n * 256 + t (off + n)

theorem beF_eq (t : Nat → Nat) (off n : Nat) : beF t off n = (beNat t off n : F) := by
  induction n with
  | zero => simp [beF, beNat]
  | succ n ih => simp [beF, beNat, ih]

theorem beNat_lt (t : Nat → Nat) (off n : Nat) (ht : ∀ i, i < off + n → t i < 256) :
    beNat t off n < 256 ^ n := by
  induction n with
  | zero => simp [beNat]
  | succ n ih =>
    have h1 := ih (fun i hi => ht i (by omega))
    have h2 := ht (off + n) (by omega)
    simp only [beNat, pow_succ]
    generalize 256 ^ n = X at h1 ⊢
    omega

/-- `be_f` of 4 bytes is the big-endian natural number, `< 2^32`. -/
theorem beF4 (t : Nat → Nat) (off : Nat) (ht : ∀ i, i < off + 4 → t i < 256) :
    beF t off 4 = (beNat t off 4 : F) ∧ beNat t off 4 < 2 ^ 32 := by
  refine ⟨beF_eq t off 4, ?_⟩
  have := beNat_lt t off 4 ht
  norm_num at this ⊢; exact this

/-- For `n ≤ 31` bytes no wraparound: the field element's canonical value is the big-endian number.
(Used for the 16-byte nonce / key limbs.) For `n = 32` this fails, see `beF32_wraps`. -/
theorem beF_val_of_le31 (t : Nat → Nat) (off n : Nat) (hn : n ≤ 31)
    (ht : ∀ i, i < off + n → t i < 256) : (beF t off n).val = beNat t off n := by
  rw [beF_eq]
  apply val_natCast_of_lt
  have h1 := beNat_lt t off n ht
  have h2 : (256:Nat) ^ n ≤ 256 ^ 31 := Nat.pow_le_pow_right (by norm_num) hn
  have h3 : (256:Nat) ^ 31 < p := by unfold p; norm_num
  omega

/-- `signed32(t, off)`, lib.nr 179-182: `msb = (t[off] >> 7) as Field; be_f(t, off, 4) - msb * 2^32`. -/
def signed32 (t : Nat → Nat) (off : Nat) : F :=
  let msb : F := ((t off >>> 7 : Nat) : F)
  beF t off 4 - msb * 4294967296

/-- Two's-complement reading of 4 big-endian bytes, as a true integer. -/
def signedInt (t : Nat → Nat) (off : Nat) : Int :=
  if t off < 128 then (beNat t off 4 : Int) else (beNat t off 4 : Int) - 2 ^ 32

theorem beNat4_expand (t : Nat → Nat) (off : Nat) :
    beNat t off 4 = ((t off * 256 + t (off + 1)) * 256 + t (off + 2)) * 256 + t (off + 3) := by
  simp [beNat]

/-- `signed32` is the cast of the two's-complement integer, which lies in `[-2^31, 2^31)`. -/
theorem signed32_eq (t : Nat → Nat) (off : Nat) (ht : ∀ i, i < off + 4 → t i < 256) :
    signed32 t off = (signedInt t off : F) ∧ -2 ^ 31 ≤ signedInt t off ∧ signedInt t off < 2 ^ 31 := by
  have e := beNat4_expand t off
  have h0 := ht off (by omega)
  have h1 := ht (off + 1) (by omega)
  have h2 := ht (off + 2) (by omega)
  have h3 := ht (off + 3) (by omega)
  have hs : t off >>> 7 = t off / 128 := by rw [Nat.shiftRight_eq_div_pow]
  unfold signed32 signedInt
  rw [beF_eq, hs]
  by_cases hc : t off < 128
  · have hm : t off / 128 = 0 := by omega
    simp only [hc, ite_true, hm]
    refine ⟨by simp, by omega, by omega⟩
  · have hm : t off / 128 = 1 := by omega
    simp only [hc, ite_false, hm]
    refine ⟨by push_cast; ring, by omega, by omega⟩

/-! ## `check_signed` field derivations (lib.nr 284-297) -/

/-- `role_b as Field`. -/
def boolF (b : Bool) : F := if b then 1 else 0

/-- line 284 -/ def aSelfF (t : Nat → Nat) : F := beF t 269 4
/-- line 285 -/ def pPartnerF (t : Nat → Nat) : F := beF t 273 4
/-- line 286 -/ def halfF (t : Nat → Nat) : F := signed32 t 173
/-- line 287 -/ def sodF (t : Nat → Nat) : F := signed32 t 233
/-- line 288: `sg = 1 - 2 * (role_b as Field)` -/ def sgF (role_b : Bool) : F := 1 - 2 * boolF role_b
/-- line 292 -/ def pSelfF (t : Nat → Nat) : F := aSelfF t - sodF t
/-- line 293 -/ def aPartnerF (t : Nat → Nat) (role_b : Bool) : F := aSelfF t + sgF role_b * halfF t

/-! True integer values. -/

def aSelf (t : Nat → Nat) : Int := beNat t 269 4
def pPartner (t : Nat → Nat) : Int := beNat t 273 4
def half (t : Nat → Nat) : Int := signedInt t 173
def sod (t : Nat → Nat) : Int := signedInt t 233
def sg (role_b : Bool) : Int := if role_b then -1 else 1
def pSelf (t : Nat → Nat) : Int := aSelf t - sod t
def aPartner (t : Nat → Nat) (role_b : Bool) : Int := aSelf t + sg role_b * half t

/-- Every transcript byte (`t : [u8; 311]`) is a byte. -/
def bytesOK (t : Nat → Nat) : Prop := ∀ i, i < 311 → t i < 256

theorem signed_casts (t : Nat → Nat) (role_b : Bool) (ht : bytesOK t) :
    aSelfF t = (aSelf t : F) ∧ pPartnerF t = (pPartner t : F) ∧ halfF t = (half t : F) ∧
    sodF t = (sod t : F) ∧ pSelfF t = (pSelf t : F) ∧ aPartnerF t role_b = (aPartner t role_b : F) := by
  have ha := (beF4 t 269 (fun i hi => ht i (by omega))).1
  have hp := (beF4 t 273 (fun i hi => ht i (by omega))).1
  have hh := (signed32_eq t 173 (fun i hi => ht i (by omega))).1
  have hs := (signed32_eq t 233 (fun i hi => ht i (by omega))).1
  have hsg : sgF role_b = (sg role_b : F) := by
    cases role_b <;> simp [sgF, sg, boolF]; norm_num
  refine ⟨?_, ?_, ?_, ?_, ?_, ?_⟩
  · simp [aSelfF, aSelf, ha]
  · simp [pPartnerF, pPartner, hp]
  · simp [halfF, half, hh]
  · simp [sodF, sod, hs]
  · simp [pSelfF, pSelf, aSelfF, aSelf, sodF, sod, ha, hs]
  · simp [aPartnerF, aPartner, aSelfF, aSelf, halfF, half, ha, hh, hsg]

/-- Integer ranges of the signed fields: `a_self, p_partner` are u32, `half, sod` are int32. -/
theorem signed_ranges (t : Nat → Nat) (role_b : Bool) (ht : bytesOK t) :
    0 ≤ aSelf t ∧ aSelf t < 2 ^ 32 ∧ 0 ≤ pPartner t ∧ pPartner t < 2 ^ 32 ∧
    -2 ^ 31 ≤ half t ∧ half t < 2 ^ 31 ∧ -2 ^ 31 ≤ sod t ∧ sod t < 2 ^ 31 ∧
    -2 ^ 31 ≤ aPartner t role_b - aSelf t ∧ aPartner t role_b - aSelf t ≤ 2 ^ 31 := by
  have ha := (beF4 t 269 (fun i hi => ht i (by omega))).2
  have hp := (beF4 t 273 (fun i hi => ht i (by omega))).2
  have hh := (signed32_eq t 173 (fun i hi => ht i (by omega))).2
  have hs := (signed32_eq t 233 (fun i hi => ht i (by omega))).2
  unfold aPartner sg aSelf pPartner half sod
  have ha' : ((beNat t 269 4 : Nat) : Int) < 2 ^ 32 := by exact_mod_cast ha
  have hp' : ((beNat t 273 4 : Nat) : Int) < 2 ^ 32 := by exact_mod_cast hp
  cases role_b <;> simp only [ite_true, ite_false, Bool.false_eq_true] <;> omega

/-! ## (iv) `half` is the signed gap between own and partner arrival -/

/-- **(iv) What `half` means.** The circuit's partner arrival `a_partner` (line 293) is the true integer
`a_self + sg * half`, with no wraparound: it is `a_self + half` for role A and `a_self - half` for role B.
So `half` is exactly "partner arrival minus own arrival" for A and "own arrival minus partner arrival"
for B, in samples.

Honest size of this result: the two integer clauses are true by definition of `aPartner`. The only real
content is the first clause, the cast with no wraparound. "Arrival" here means the numbers in the signed
transcript. It says nothing about any physical gap until combined with D (`a_self` is the first peak) and
E + F (`a_partner` sits at a lag that passes the ratio test, see `phone_core_glue`). -/
theorem half_is_gap (t : Nat → Nat) (role_b : Bool) (ht : bytesOK t) :
    aPartnerF t role_b = (aPartner t role_b : F) ∧
    (role_b = false → half t = aPartner t role_b - aSelf t) ∧
    (role_b = true → half t = aSelf t - aPartner t role_b) := by
  refine ⟨(signed_casts t role_b ht).2.2.2.2.2, ?_, ?_⟩
  · intro h; subst h; simp [aPartner, sg]
  · intro h; subst h; simp [aPartner, sg]

/-! ## (i) self window offset (lib.nr 503-505) -/

/-- line 503: `os = p_self - DELTA - HM - 1024 * leaf_s` -/
def osF (t : Nat → Nat) (leaf_s : F) : F := pSelfF t - 96 - 31 - 1024 * leaf_s

theorem osF_cast (t : Nat → Nat) (ls : Nat) (ht : bytesOK t) :
    osF t (ls : F) = ((pSelf t - 127 - 1024 * ls : Int) : F) := by
  simp only [osF, (signed_casts t false ht).2.2.2.2.1]; push_cast; ring

/-- **(i) Self window offset.** If the transcript bytes are bytes, `leaf_s` passed the 8-bit
decomposition inside `merkle_root` (line 109, reached with `idx = leaf_s + 0` from `open_leaves`
line 127, i = 0), and `os` passed `assert_max_bit_size::<10>` (line 504), then `leaf_s` is a real
leaf index `ls < 256` and `os` is the true integer `p_self - 127 - 1024 * ls`, in `[0, 1024)`.
So `os as u32` (line 513) is that integer, and the self window starts at sample `p_self - 96 - 31`
(of the recording only given block B; here it is an offset into the opened leaves). -/
theorem os_window (t : Nat → Nat) (leaf_s : F) (ht : bytesOK t)
    (hleaf : fits 8 leaf_s) (hos : fits 10 (osF t leaf_s)) :
    ∃ ls : Nat, ls < 256 ∧ leaf_s = (ls : F) ∧
      osF t leaf_s = ((pSelf t - 127 - 1024 * ls : Int) : F) ∧
      ((osF t leaf_s).val : Int) = pSelf t - 127 - 1024 * ls ∧
      0 ≤ pSelf t - 127 - 1024 * ls ∧ pSelf t - 127 - 1024 * ls < 1024 := by
  obtain ⟨ls, hls, rfl⟩ := fits_exists_nat hleaf
  have hr := signed_ranges t false ht
  have hlsI : (ls : Int) < 256 := by exact_mod_cast hls
  have heq := osF_cast t ls ht
  have habs : |pSelf t - 127 - 1024 * (ls : Int)| < 2 ^ 34 := by
    unfold pSelf; rw [abs_lt]; constructor <;> omega
  rw [heq] at hos
  have hb := nonneg_of_fits_intCast (by norm_num) (by norm_num) habs hos
  refine ⟨ls, hls, rfl, heq, ?_, hb.1, by norm_num at hb; exact hb.2⟩
  rw [heq, val_intCast, Int.emod_eq_of_lt hb.1]
  have := two_pow_lt_p (k := 10) (by norm_num)
  omega

/-! ## partner window offset (lib.nr 506-508), same shape -/

/-- line 506: `op = a_partner - HM - 1024 * leaf_p` -/
def opF (t : Nat → Nat) (role_b : Bool) (leaf_p : F) : F := aPartnerF t role_b - 31 - 1024 * leaf_p

theorem opF_cast (t : Nat → Nat) (role_b : Bool) (lp : Nat) (ht : bytesOK t) :
    opF t role_b (lp : F) = ((aPartner t role_b - 31 - 1024 * lp : Int) : F) := by
  simp only [opF, (signed_casts t role_b ht).2.2.2.2.2]; push_cast; ring

/-- **Partner window offset.** Same as (i) for the partner window: `op` is the true integer
`a_partner - 31 - 1024 * lp` in `[0, 1024)`, and its canonical value `.val` is that integer, so `op as u32`
(line 524) is exact. The partner window starts at sample `a_partner - 31`
(and in particular the true `a_partner ≥ 31`). -/
theorem op_window (t : Nat → Nat) (role_b : Bool) (leaf_p : F) (ht : bytesOK t)
    (hleaf : fits 8 leaf_p) (hop : fits 10 (opF t role_b leaf_p)) :
    ∃ lp : Nat, lp < 256 ∧ leaf_p = (lp : F) ∧
      opF t role_b leaf_p = ((aPartner t role_b - 31 - 1024 * lp : Int) : F) ∧
      ((opF t role_b leaf_p).val : Int) = aPartner t role_b - 31 - 1024 * lp ∧
      0 ≤ aPartner t role_b - 31 - 1024 * lp ∧ aPartner t role_b - 31 - 1024 * lp < 1024 := by
  obtain ⟨lp, hlp, rfl⟩ := fits_exists_nat hleaf
  have hr := signed_ranges t role_b ht
  have hlpI : (lp : Int) < 256 := by exact_mod_cast hlp
  have heq := opF_cast t role_b lp ht
  have habs : |aPartner t role_b - 31 - 1024 * (lp : Int)| < 2 ^ 34 := by
    rw [abs_lt]; constructor <;> omega
  rw [heq] at hop
  have hb := nonneg_of_fits_intCast (by norm_num) (by norm_num) habs hop
  refine ⟨lp, hlp, rfl, heq, ?_, hb.1, by norm_num at hb; exact hb.2⟩
  rw [heq, val_intCast, Int.emod_eq_of_lt hb.1]
  have := two_pow_lt_p (k := 10) (by norm_num)
  omega

/-! ## (ii) WPRE / WPOST window (lib.nr 525-526) -/

/-- **(ii) Partner arrival window.** If both 33-bit checks pass (lines 525-526,
`a_partner - p_partner + WPRE` and `p_partner + WPOST - a_partner`, WPRE = 7200, WPOST = 12000),
then over the true integers the partner arrival is at most 7200 samples before and at most
12000 samples after its predicted time: `-7200 ≤ a_partner - p_partner ≤ 12000`. -/
theorem partner_window (t : Nat → Nat) (role_b : Bool) (ht : bytesOK t)
    (h1 : fits 33 (aPartnerF t role_b - pPartnerF t + 7200))
    (h2 : fits 33 (pPartnerF t + 12000 - aPartnerF t role_b)) :
    -7200 ≤ aPartner t role_b - pPartner t ∧ aPartner t role_b - pPartner t ≤ 12000 := by
  have hc := signed_casts t role_b ht
  have hr := signed_ranges t role_b ht
  rw [hc.2.2.2.2.2, hc.2.1] at h1 h2
  have e1 : ((aPartner t role_b : Int) : F) - (pPartner t : F) + 7200
      = ((aPartner t role_b - pPartner t + 7200 : Int) : F) := by push_cast; ring
  have e2 : ((pPartner t : Int) : F) + 12000 - (aPartner t role_b : F)
      = ((pPartner t + 12000 - aPartner t role_b : Int) : F) := by push_cast; ring
  rw [e1] at h1; rw [e2] at h2
  have b1 := nonneg_of_fits_intCast (k := 33) (m := 35) (by norm_num) (by norm_num)
    (by rw [abs_lt]; constructor <;> omega) h1
  have b2 := nonneg_of_fits_intCast (k := 33) (m := 35) (by norm_num) (by norm_num)
    (by rw [abs_lt]; constructor <;> omega) h2
  omega

/-! ## (iii) the arrival target `usum_target` (lib.nr 360-369, 521) -/

/-- lines 362-368: `usum = 0; for j in 0..K { usum += u[j] as Field }` (monotonicity asserts omitted:
they are not needed for this bound). -/
def usumLoop (u : Nat → Bool) : Nat → F
  | 0 => 0
  | j + 1 => usumLoop u j + boolF (u j)

def usumNat (u : Nat → Bool) : Nat → Nat
  | 0 => 0
  | j + 1 => usumNat u j + (if u j then 1 else 0)

theorem usumLoop_eq (u : Nat → Bool) (n : Nat) : usumLoop u n = (usumNat u n : F) := by
  induction n with
  | zero => simp [usumLoop, usumNat]
  | succ n ih => cases h : u n <;> simp [usumLoop, usumNat, ih, boolF, h]

theorem usumNat_le (u : Nat → Bool) (n : Nat) : usumNat u n ≤ n := by
  induction n with
  | zero => simp [usumNat]
  | succ n ih => simp only [usumNat]; split <;> omega

/-- line 521: the `usum_target` argument `a_self - p_self + DELTA`. -/
def usumTarget (t : Nat → Nat) : F := aSelfF t - pSelfF t + 96

/-- **(iii) Self offset `sod` is small.** `self_side` is called with target `a_self - p_self + 96`
(line 521), which is just `sod + 96`. The arrival selector sums `K = 193` flags with the last one forced
to 0 (line 361), so the sum is a whole number `a ≤ 192`. The equality check (line 369) then forces,
over the true integers, `a = sod + 96`, hence `-96 ≤ sod ≤ 96`, i.e. the signed predicted own arrival
`p_self = a_self - sod` is within 96 samples of the claimed arrival `a_self`. -/
theorem sod_small (t : Nat → Nat) (u : Nat → Bool) (ht : bytesOK t)
    (hlast : u 192 = false) (heq : usumLoop u 193 = usumTarget t) :
    (usumNat u 193 : Int) = sod t + 96 ∧ -96 ≤ sod t ∧ sod t ≤ 96 := by
  have hc := signed_casts t false ht
  have hr := signed_ranges t false ht
  have hle : usumNat u 193 ≤ 192 := by
    have := usumNat_le u 192
    have e : usumNat u 193 = usumNat u 192 + (if u 192 then 1 else 0) := rfl
    rw [e, hlast]; simp; omega
  have hT : usumTarget t = ((sod t + 96 : Int) : F) := by
    simp only [usumTarget, pSelfF, hc.2.2.2.1]; push_cast; ring
  rw [usumLoop_eq, hT, ← intCast_natCast] at heq
  have hleI : ((usumNat u 193 : Nat) : Int) ≤ 192 := by exact_mod_cast hle
  have hinj := intCast_inj_of_small (a := (usumNat u 193 : Int)) (b := sod t + 96)
    (by rw [abs_lt]; constructor <;> omega) (by rw [abs_lt]; constructor <;> omega) heq
  omega

/-! ## Note: 32-byte `be_f` wraps (rec_root, line 279) -/

/-- The 32 big-endian bytes of `p` itself. -/
def pBytes (i : Nat) : Nat := (p / 256 ^ (208 - i)) % 256

/-- **32-byte `be_f` is not injective.** The bytes of `p` and 32 zero bytes give the same field element
(0). This is why line 279-283 re-serialises `rec_root` and compares bytes. Whether that closes the alias
is NOT proved here: it rests on Noir's `to_be_bytes` returning the canonical (`< p`) encoding, which is
trusted. `be_f` with 16 or 4 bytes cannot wrap (`beF_val_of_le31`), this is proved. -/
theorem beF32_wraps : beF pBytes 177 32 = beF (fun _ => 0) 177 32 ∧ pBytes 177 ≠ 0 := by
  have h : beNat pBytes 177 32 = p := by unfold pBytes p; decide
  have h0 : beNat (fun _ => 0) 177 32 = 0 := by simp [beNat]
  refine ⟨by rw [beF_eq, beF_eq, h, h0]; simp, by unfold pBytes p; decide⟩

/-! ## Block E: `partner_side` (lib.nr 436-473) -/

/-- lib.nr 35-36: offsets of the 31 non-zero FIR taps. -/
def NZT : List Nat :=
  [9, 11, 12, 14, 15, 17, 18, 20, 21, 23, 24, 26, 27, 29, 30, 31, 32, 33, 35, 36, 38, 39, 41, 42, 44, 45, 47, 48, 50, 51, 53]
/-- lib.nr 37-39: the 31 non-zero FIR taps (as integers; the circuit's `-1` is the field element `p - 1`). -/
def NZH : List Int :=
  [1, 1, 2, 2, 2, 4, -1, 2, -7, -5, -13, -19, -13, -45, 27, 127, 27, -45, -13, -19, -13, -5, -7, 2, -1, 4, 2, 2, 2, 1, 1]
def nzt (t : Nat) : Nat := NZT.getD t 0
def nzh (t : Nat) : Int := NZH.getD t 0

theorem nzt_bounds : ∀ t, t < 31 → 9 ≤ nzt t ∧ nzt t ≤ 53 := by decide
theorem sum_abs_nzh : (∑ t ∈ Finset.range 31, |nzh t|) = 415 := by decide

/-- `BAR` (line 33). -/
def BAR : Int := 4474747

/-- `ToF for u8` (lines 136-139): `self as Field - 128`. -/
def tf (x : Nat) : F := (x : F) - 128

/-- lines 441-446: `cnp = 0; for n in 0..L { v = c_i[n].tf(); cnp = w(cnp + v * v) }`. -/
def cnpLoop (c : Nat → Nat) : Nat → F
  | 0 => 0
  | n + 1 => let v := tf (c n); cnpLoop c n + v * v

/-- line 452: `wi = xp[o + i] as Field - 32768`. -/
def wiF (xp : Nat → Nat) (o i : Nat) : F := (xp (o + i) : F) - 32768

/-- lines 456-459: `y = 0; for t in 0..NZ { y += NZH[t] * ring[(m + NZT[t]) % 64] }`. -/
def yLoop (ring : Nat → F) (m : Nat) : Nat → F
  | 0 => 0
  | t + 1 => yLoop ring m t + (nzh t : F) * ring ((m + nzt t) % 64)

/-- Loop state of lines 447-450: the 64-slot ring and the three running sums. -/
structure PSt where
  ring : Nat → F
  ep : F
  ii : F
  qq : F

/-- One iteration `i` of the loop at lines 451-469. -/
def pstep (xp : Nat → Nat) (o : Nat) (ci cq : Nat → Nat) (s : PSt) (i : Nat) : PSt :=
  let ring := Function.update s.ring (i % 64) (wiF xp o i)          -- 452-453
  if 62 ≤ i then                                                    -- 454
    let m := i - 62                                                 -- 455
    let y := yLoop ring m 31                                        -- 456-460
    let wc := ring ((m + 31) % 64)                                  -- 463
    { ring := ring,
      ep := s.ep + y * y,                                           -- 461-462
      ii := s.ii + tf (ci m) * wc,                                  -- 464-465
      qq := s.qq + tf (cq m) * wc }                                 -- 466-467
  else { s with ring := ring }

/-- State after the first `i` iterations (initial values lines 447-450). -/
def prun (xp : Nat → Nat) (o : Nat) (ci cq : Nat → Nat) : Nat → PSt
  | 0 => ⟨fun _ => 0, 0, 0, 0⟩
  | i + 1 => pstep xp o ci cq (prun xp o ci cq i) i

/-- lines 470-471: `v = BAR * (ii*ii + qq*qq) - ep * cnp`, after `NP = 12062` iterations, `L = 12000`. -/
def partnerV (xp : Nat → Nat) (o : Nat) (ci cq : Nat → Nat) : F :=
  let s := prun xp o ci cq 12062
  let penv2 := s.ii * s.ii + s.qq * s.qq
  (BAR : F) * penv2 - s.ep * cnpLoop ci 12000

/-- `partner_side` accepts: line 472, `v.assert_max_bit_size::<96>()`. -/
def partnerAccepts (xp : Nat → Nat) (o : Nat) (ci cq : Nat → Nat) : Prop :=
  fits 96 (partnerV xp o ci cq)

/-! True integer quantities. Window sample `i` is `x[a_partner - 31 + i]` (from `op`, see `op_window`). -/

def tfI (x : Nat) : Int := (x : Int) - 128
def wI (xp : Nat → Nat) (o j : Nat) : Int := (xp (o + j) : Int) - 32768
/-- FIR output `y_m`. -/
def yI (xp : Nat → Nat) (o m : Nat) : Int := ∑ t ∈ Finset.range 31, nzh t * wI xp o (m + nzt t)
/-- Filtered energy of the partner window, `E`. -/
def EI (xp : Nat → Nat) (o : Nat) : Int := ∑ m ∈ Finset.range 12000, yI xp o m ^ 2
/-- In-phase correlation of the partner template with the window at lag `a_partner`. -/
def II (xp : Nat → Nat) (o : Nat) (ci : Nat → Nat) : Int := ∑ m ∈ Finset.range 12000, tfI (ci m) * wI xp o (m + 31)
/-- Template energy `cn2`. -/
def CI (ci : Nat → Nat) : Int := ∑ n ∈ Finset.range 12000, tfI (ci n) ^ 2

theorem cnpLoop_eq (c : Nat → Nat) (n : Nat) :
    cnpLoop c n = ((∑ k ∈ Finset.range n, tfI (c k) ^ 2 : Int) : F) := by
  induction n with
  | zero => simp [cnpLoop]
  | succ n ih => simp only [cnpLoop, ih, Finset.sum_range_succ, tf, tfI]; push_cast; ring

theorem wiF_eq (xp : Nat → Nat) (o j : Nat) : wiF xp o j = (wI xp o j : F) := by
  simp [wiF, wI]

/-- Loop invariant of lines 451-469: the ring holds the last 64 window samples, and the three sums
are the true integer sums over the outputs so far. -/
theorem prun_inv (xp : Nat → Nat) (o : Nat) (ci cq : Nat → Nat) (i : Nat) :
    (∀ j, j < i → i ≤ j + 64 → (prun xp o ci cq i).ring (j % 64) = wiF xp o j) ∧
    (prun xp o ci cq i).ep = ((∑ m ∈ Finset.range (i - 62), yI xp o m ^ 2 : Int) : F) ∧
    (prun xp o ci cq i).ii = ((∑ m ∈ Finset.range (i - 62), tfI (ci m) * wI xp o (m + 31) : Int) : F) ∧
    (prun xp o ci cq i).qq = ((∑ m ∈ Finset.range (i - 62), tfI (cq m) * wI xp o (m + 31) : Int) : F) := by
  induction i with
  | zero => simp [prun]
  | succ i ih =>
    obtain ⟨hr, he, hi, hq⟩ := ih
    set s := prun xp o ci cq i with hs
    set ring' := Function.update s.ring (i % 64) (wiF xp o i) with hring'
    have hR : ∀ j, j < i + 1 → i + 1 ≤ j + 64 → ring' (j % 64) = wiF xp o j := by
      intro j hj1 hj2
      by_cases hji : j = i
      · subst hji; simp [hring']
      · have hne : j % 64 ≠ i % 64 := by omega
        rw [hring', Function.update_of_ne hne]
        exact hr j (by omega) (by omega)
    have hstep : prun xp o ci cq (i + 1) = pstep xp o ci cq s i := rfl
    by_cases h62 : 62 ≤ i
    · have hy : ∀ T, T ≤ 31 → yLoop ring' (i - 62) T
          = ((∑ t ∈ Finset.range T, nzh t * wI xp o (i - 62 + nzt t) : Int) : F) := by
        intro T hT
        induction T with
        | zero => simp [yLoop]
        | succ T ihT =>
          have hb := nzt_bounds T (by omega)
          rw [yLoop, ihT (by omega), hR _ (by omega) (by omega), wiF_eq, Finset.sum_range_succ]
          push_cast; ring
      have hwc : ring' ((i - 62 + 31) % 64) = (wI xp o (i - 62 + 31) : F) := by
        rw [hR _ (by omega) (by omega), wiF_eq]
      have hy' : yLoop ring' (i - 62) 31 = (yI xp o (i - 62) : F) := by
        unfold yI; exact hy 31 le_rfl
      have hidx : i + 1 - 62 = (i - 62) + 1 := by omega
      rw [hstep]
      simp only [pstep, h62, ite_true]
      rw [← hring']
      refine ⟨hR, ?_, ?_, ?_⟩
      · rw [hy', he, hidx, Finset.sum_range_succ]; push_cast; ring
      · rw [hwc, hi, hidx, Finset.sum_range_succ]; simp only [tf, tfI]; push_cast; ring
      · rw [hwc, hq, hidx, Finset.sum_range_succ]; simp only [tf, tfI]; push_cast; ring
    · have hidx : i + 1 - 62 = i - 62 := by omega
      rw [hstep]
      simp only [pstep, h62, ite_false]
      exact ⟨hR, by rw [hidx]; exact he, by rw [hidx]; exact hi, by rw [hidx]; exact hq⟩

theorem partnerV_eq (xp : Nat → Nat) (o : Nat) (ci cq : Nat → Nat) :
    partnerV xp o ci cq = ((BAR * (II xp o ci ^ 2 + II xp o cq ^ 2) - EI xp o * CI ci : Int) : F) := by
  obtain ⟨_, he, hi, hq⟩ := prun_inv xp o ci cq 12062
  have h : (12062 - 62 : Nat) = 12000 := by norm_num
  rw [h] at he hi hq
  simp only [partnerV, he, hi, hq, cnpLoop_eq, EI, II, CI]
  push_cast; ring

/-! Integer bounds (no wraparound). -/

theorem abs_wI (xp : Nat → Nat) (o j : Nat) (h : xp (o + j) < 2 ^ 16) : |wI xp o j| ≤ 32768 := by
  unfold wI; rw [abs_le]
  have : ((xp (o + j) : Nat) : Int) < 65536 := by exact_mod_cast h
  constructor <;> omega

theorem abs_tfI (x : Nat) (h : x < 256) : |tfI x| ≤ 128 := by
  unfold tfI; rw [abs_le]
  have : (x : Int) < 256 := by exact_mod_cast h
  constructor <;> omega

theorem abs_yI (xp : Nat → Nat) (o m : Nat) (hm : m < 12000)
    (hx : ∀ i, i < 12062 → xp (o + i) < 2 ^ 16) : |yI xp o m| ≤ 415 * 32768 := by
  unfold yI
  calc |∑ t ∈ Finset.range 31, nzh t * wI xp o (m + nzt t)|
      ≤ ∑ t ∈ Finset.range 31, |nzh t * wI xp o (m + nzt t)| := Finset.abs_sum_le_sum_abs _ _
    _ ≤ ∑ t ∈ Finset.range 31, |nzh t| * 32768 := by
        apply Finset.sum_le_sum
        intro t ht
        rw [Finset.mem_range] at ht
        have hb := nzt_bounds t ht
        rw [abs_mul]
        exact mul_le_mul_of_nonneg_left (abs_wI xp o _ (hx _ (by omega))) (abs_nonneg _)
    _ = 415 * 32768 := by rw [← Finset.sum_mul, sum_abs_nzh]

theorem abs_II (xp : Nat → Nat) (o : Nat) (c : Nat → Nat)
    (hx : ∀ i, i < 12062 → xp (o + i) < 2 ^ 16) (hc : ∀ n, n < 12000 → c n < 256) :
    |II xp o c| ≤ 12000 * (128 * 32768) := by
  unfold II
  calc |∑ m ∈ Finset.range 12000, tfI (c m) * wI xp o (m + 31)|
      ≤ ∑ m ∈ Finset.range 12000, |tfI (c m) * wI xp o (m + 31)| := Finset.abs_sum_le_sum_abs _ _
    _ ≤ ∑ m ∈ Finset.range 12000, (128 * 32768 : Int) := by
        apply Finset.sum_le_sum
        intro m hm
        rw [Finset.mem_range] at hm
        rw [abs_mul]
        exact mul_le_mul (abs_tfI _ (hc m hm)) (abs_wI xp o _ (hx _ (by omega))) (abs_nonneg _) (by norm_num)
    _ = 12000 * (128 * 32768) := by simp

theorem EI_bounds (xp : Nat → Nat) (o : Nat) (hx : ∀ i, i < 12062 → xp (o + i) < 2 ^ 16) :
    0 ≤ EI xp o ∧ EI xp o ≤ 12000 * (415 * 32768) ^ 2 := by
  unfold EI
  refine ⟨Finset.sum_nonneg (fun m _ => sq_nonneg _), ?_⟩
  calc ∑ m ∈ Finset.range 12000, yI xp o m ^ 2 ≤ ∑ m ∈ Finset.range 12000, ((415 * 32768) ^ 2 : Int) := by
        apply Finset.sum_le_sum
        intro m hm
        rw [Finset.mem_range] at hm
        have := abs_le.mp (abs_yI xp o m hm hx)
        nlinarith
    _ = 12000 * (415 * 32768) ^ 2 := by simp

theorem CI_bounds (c : Nat → Nat) (hc : ∀ n, n < 12000 → c n < 256) :
    0 ≤ CI c ∧ CI c ≤ 12000 * 128 ^ 2 := by
  unfold CI
  refine ⟨Finset.sum_nonneg (fun m _ => sq_nonneg _), ?_⟩
  calc ∑ n ∈ Finset.range 12000, tfI (c n) ^ 2 ≤ ∑ n ∈ Finset.range 12000, ((128) ^ 2 : Int) := by
        apply Finset.sum_le_sum
        intro n hn
        rw [Finset.mem_range] at hn
        have := abs_le.mp (abs_tfI _ (hc n hn))
        nlinarith
    _ = 12000 * 128 ^ 2 := by simp

/-- **Block E: the partner's code passes the ratio test at one lag.**
Inputs: the opened recording samples `xp` are u16 (stored as `x + 32768`), the partner templates
`c_ip, c_qp` are u8 (so `tf` gives integers in `[-128, 127]`). Over the 12000-sample template, `I` and `Q`
are the true correlations of the partner template with the recording starting at lag `a_partner`,
`E` is the filtered (31-tap FIR, sum |h| = 415) recording energy and `cn2` the template energy.
Then the circuit's single 96-bit check (line 472) passes **exactly when**
`BAR * (I^2 + Q^2) ≥ E * cn2`, with no wraparound either way.

That inequality is the claim. Read as a score, when `E * cn2 > 0`, it is
`g * sqrt((I^2+Q^2)/(E*cn2)) ≥ g / sqrt BAR`, where `g` is the normalising gain. `g / sqrt BAR` is 0.09 up to
BAR's rounding (about 1e-8) when `BAR = round(g^2 / 0.09^2)`; see `bar_iff_score` and `T0eff_48k` in `Bar.lean`.
Without `g`, `1 / sqrt BAR` alone is about 0.00047.

It is a RATIO test, not a loudness test. When `E * cn2 = 0` the score is 0/0 and the check passes anyway:
a silent window (`partner_silence_accepts`) or an all-128 I template (`zero_template_accepts`). Also `cn2`
comes only from `c_i` (line 443) while the top uses `I^2 + Q^2`, so a weak I template with a strong Q template
inflates the score. Safety against bad templates rests on `code_commit` being attested by the server.

Note: this checks a threshold at one lag, NOT "first". Unlike the self side, nothing says earlier lags were
below the bar; `a_partner` can be any qualifying lag in the WPRE/WPOST window (`partner_window`). -/
theorem partner_loud (xp : Nat → Nat) (o : Nat) (ci cq : Nat → Nat)
    (hx : ∀ i, i < 12062 → xp (o + i) < 2 ^ 16)
    (hci : ∀ n, n < 12000 → ci n < 256) (hcq : ∀ n, n < 12000 → cq n < 256) :
    partnerAccepts xp o ci cq ↔ EI xp o * CI ci ≤ BAR * (II xp o ci ^ 2 + II xp o cq ^ 2) := by
  unfold partnerAccepts
  rw [partnerV_eq]
  have hI := abs_le.mp (abs_II xp o ci hx hci)
  have hQ := abs_le.mp (abs_II xp o cq hx hcq)
  have hE := EI_bounds xp o hx
  have hC := CI_bounds ci hci
  have hI2 : II xp o ci ^ 2 ≤ (12000 * (128 * 32768)) ^ 2 := by nlinarith
  have hQ2 : II xp o cq ^ 2 ≤ (12000 * (128 * 32768)) ^ 2 := by nlinarith
  have hEC : EI xp o * CI ci ≤ (12000 * (415 * 32768) ^ 2) * (12000 * 128 ^ 2) :=
    mul_le_mul hE.2 hC.2 hC.1 (by norm_num)
  have hEC0 : 0 ≤ EI xp o * CI ci := mul_nonneg hE.1 hC.1
  have hP0 : 0 ≤ II xp o ci ^ 2 + II xp o cq ^ 2 := by positivity
  unfold BAR at *
  have hlo : -(2:Int) ^ 96 < 4474747 * (II xp o ci ^ 2 + II xp o cq ^ 2) - EI xp o * CI ci := by
    norm_num at hEC ⊢; nlinarith
  have hhi : 4474747 * (II xp o ci ^ 2 + II xp o cq ^ 2) - EI xp o * CI ci < (2:Int) ^ 96 := by
    norm_num at hI2 hQ2 ⊢; nlinarith
  rw [fits_intCast_iff_of_abs (k := 96) (m := 96) (by norm_num) (by norm_num) (abs_lt.mpr ⟨hlo, hhi⟩)]
  constructor
  · intro h; linarith [h.1]
  · intro h; exact ⟨by linarith, hhi⟩

/-! ## Block E: both sides are reachable, and the degenerate accepts -/

theorem wI_silent (xp : Nat → Nat) (o : Nat) (hs : ∀ i, i < 12062 → xp (o + i) = 32768)
    (j : Nat) (hj : j < 12062) : wI xp o j = 0 := by
  simp [wI, hs j hj]

/-- **Silence passes block E.** If every sample of the opened partner window is digital silence
(stored 32768, meaning 0), the check passes for ANY in-range templates, though no code was heard.
Using this needs a device-signed recording with a silent window. (Same hole as `Bar.lean` section 6, here on
the full loop model rather than the final line.) -/
theorem partner_silence_accepts (xp : Nat → Nat) (o : Nat) (ci cq : Nat → Nat)
    (hs : ∀ i, i < 12062 → xp (o + i) = 32768)
    (hci : ∀ n, n < 12000 → ci n < 256) (hcq : ∀ n, n < 12000 → cq n < 256) :
    partnerAccepts xp o ci cq := by
  have hx : ∀ i, i < 12062 → xp (o + i) < 2 ^ 16 := by
    intro i hi; rw [hs i hi]; norm_num
  have hy : ∀ m ∈ Finset.range 12000, yI xp o m ^ 2 = 0 := by
    intro m hm
    rw [Finset.mem_range] at hm
    have : yI xp o m = 0 := by
      unfold yI
      apply Finset.sum_eq_zero
      intro k hk
      rw [Finset.mem_range] at hk
      have hb := nzt_bounds k hk
      rw [wI_silent xp o hs _ (by omega), mul_zero]
    rw [this]; norm_num
  have hE : EI xp o = 0 := Finset.sum_eq_zero hy
  have hI : ∀ c : Nat → Nat, II xp o c = 0 := by
    intro c
    unfold II
    apply Finset.sum_eq_zero
    intro m hm
    rw [Finset.mem_range] at hm
    rw [wI_silent xp o hs _ (by omega), mul_zero]
  rw [partner_loud xp o ci cq hx hci hcq, hE, hI, hI]
  simp

/-- **An all-128 I template passes block E on any recording.** `c_ip` all 128 gives `tf = 0`, so `cn2 = 0`, and
the check becomes `BAR * Q^2 ≥ 0`, always true, for any Q template. Templates are bound by `code_commit`, a
public input the server attests (`phone/src/main.nr`), so this is safe only if the server refuses such codes.
-/
theorem zero_template_accepts (xp : Nat → Nat) (o : Nat) (cq : Nat → Nat)
    (hx : ∀ i, i < 12062 → xp (o + i) < 2 ^ 16) (hcq : ∀ n, n < 12000 → cq n < 256) :
    partnerAccepts xp o (fun _ => 128) cq := by
  rw [partner_loud xp o _ cq hx (fun _ _ => by norm_num) hcq]
  have hC : CI (fun _ => 128) = 0 := by
    unfold CI
    exact Finset.sum_eq_zero (fun n _ => by simp [tfI])
  rw [hC, mul_zero]
  unfold BAR
  positivity

/-- **Block E also accepts a recording that is not silent, with a template that is not zero.** Every sample is
1 (stored 32769), `c_i` is all 129 (`tf = 1`), `c_q` is all 128 (`tf = 0`). Then `E = 108000`, `cn2 = 12000`,
`I = 12000`, `Q = 0`, so `E * cn2 > 0` and the check passes on the real ratio, not on 0/0.
This is a constant (DC) recording with a toy template; it shows the check is reachable, not that it is a hole.
The offset `o` is free, so `phone_glue_nonvacuous` can use it at any window.
(`hw` uses `norm_num`: `simp [wI]` here gives a proof the kernel rejects with "deep recursion".) -/
theorem partner_accepts_nonsilent (o : Nat) :
    partnerAccepts (fun _ => 32769) o (fun _ => 129) (fun _ => 128) ∧
      0 < EI (fun _ => 32769) o * CI (fun _ => 129) := by
  have hw : ∀ j, wI (fun _ => 32769) o j = 1 := by
    intro j; unfold wI; norm_num
  have hsum : (∑ t ∈ Finset.range 31, nzh t) = 3 := by decide
  have hy : ∀ m, yI (fun _ => 32769) o m = 3 := by
    intro m; simp [yI, hw, hsum]
  have hE : EI (fun _ => 32769) o = 108000 := by
    simp [EI, hy]
  have hC : CI (fun _ => 129) = 12000 := by
    simp [CI, tfI]
  have hI : II (fun _ => 32769) o (fun _ => 129) = 12000 := by
    simp [II, tfI, hw]
  have hQ : II (fun _ => 32769) o (fun _ => 128) = 0 := by
    simp [II, tfI]
  refine ⟨?_, by rw [hE, hC]; norm_num⟩
  rw [partner_loud _ o _ _ (fun _ _ => by norm_num) (fun _ _ => by norm_num) (fun _ _ => by norm_num),
    hE, hC, hI, hQ]
  norm_num [BAR]

/-- A one-sample click at index 32, with an I template that ignores it. -/
def xpR (j : Nat) : Nat := if j = 32 then 32769 else 32768
def ciR (m : Nat) : Nat := if m = 0 then 129 else 128

theorem yI_R : yI xpR 0 0 = 27 := by decide

/-- **Block E really can reject.** The click gives `E > 0`, the template has `cn2 > 0`, and `I = Q = 0`, so the
ratio test fails. This shows `partner_loud` is not vacuous and the check is not always true. -/
theorem partner_rejects : ¬ partnerAccepts xpR 0 ciR (fun _ => 128) := by
  have hx : ∀ i, i < 12062 → xpR (0 + i) < 2 ^ 16 := by
    intro i _; unfold xpR; split_ifs <;> norm_num
  have hci : ∀ n, n < 12000 → ciR n < 256 := by
    intro n _; unfold ciR; split_ifs <;> norm_num
  rw [partner_loud xpR 0 ciR _ hx hci (fun _ _ => by norm_num)]
  have hI : II xpR 0 ciR = 0 := by
    unfold II
    apply Finset.sum_eq_zero
    intro m _
    by_cases hm : m = 0
    · subst hm; simp [wI, xpR]
    · simp [tfI, ciR, hm]
  have hQ : II xpR 0 (fun _ => 128) = 0 := by
    unfold II
    exact Finset.sum_eq_zero (fun m _ => by simp [tfI])
  have hE : yI xpR 0 0 ^ 2 ≤ EI xpR 0 := by
    unfold EI
    exact Finset.single_le_sum (f := fun m => yI xpR 0 m ^ 2) (fun m _ => sq_nonneg _)
      (Finset.mem_range.mpr (by norm_num))
  have hC : tfI (ciR 0) ^ 2 ≤ CI ciR := by
    unfold CI
    exact Finset.single_le_sum (f := fun n => tfI (ciR n) ^ 2) (fun m _ => sq_nonneg _)
      (Finset.mem_range.mpr (by norm_num))
  rw [yI_R] at hE
  have hC1 : (1 : Int) ≤ CI ciR := by
    have : tfI (ciR 0) = 1 := by simp [tfI, ciR]
    rw [this] at hC; linarith
  rw [hI, hQ]
  simp only [BAR]
  nlinarith

/-! ## Block F: the whole `phone_core` glue in one statement -/

/-- `x as u32` on a `Field`: the low 32 bits of the canonical value (lines 513, 524). -/
def asU32 (x : F) : Nat := x.val % 2 ^ 32

theorem asU32_of_fits {x : F} (h : fits 10 x) : asU32 x = x.val := by
  unfold asU32 fits at *
  exact Nat.mod_eq_of_lt (by omega)

/-- Every constraint of `phone_core` this file models, in source order. `self_side`'s arrival loop is
`Arrival.lean`, `merkle_root`'s hashing is block B. -/
structure PhoneGlue (t : Nat → Nat) (role_b : Bool) (leaf_s leaf_p : F) (u : Nat → Bool)
    (xp : Nat → Nat) (c_ip c_qp : Nat → Nat) : Prop where
  os_ok : fits 10 (osF t leaf_s)                                          -- 504
  leaf_s_ok : fits 8 leaf_s                                               -- 505 → 127 → 109 (i = 0)
  op_ok : fits 10 (opF t role_b leaf_p)                                   -- 507
  leaf_p_ok : fits 8 leaf_p                                               -- 508 → 127 → 109 (i = 0)
  u_last : u 192 = false                                                  -- 521 → 361
  usum_ok : usumLoop u 193 = usumTarget t                                 -- 521 → 369
  partner_ok : partnerAccepts xp (asU32 (opF t role_b leaf_p)) c_ip c_qp  -- 524 → 472
  wpre_ok : fits 33 (aPartnerF t role_b - pPartnerF t + 7200)             -- 525
  wpost_ok : fits 33 (pPartnerF t + 12000 - aPartnerF t role_b)           -- 526

/-- **Block F, all together.** If `phone_core`'s constraints hold and the inputs have their types, then, over
true integers: `leaf_s`, `leaf_p` are small whole numbers; both offsets `os`, `op` are exact, in `[0, 1024)`, so
the self window starts at sample `p_self - 127` and the partner window at `a_partner - 31` of the recording; the
partner window fits inside the 13 opened leaves; `sod` is in `[-96, 96]`; `a_partner` is within
`-7200..+12000` of its prediction; and the ratio test holds at THAT window, the one given by `op`.

This ties `op` to the correlated window, which `partner_loud` alone did not. "Sample ... of the recording" holds
only with block B, for BOTH windows: nothing here ties `xs` or `xp` to the signed recording, and `xs` is not even
an argument of this theorem. Here `os` and `op` are only offsets into arrays the prover supplies. -/
theorem phone_core_glue (t : Nat → Nat) (role_b : Bool) (leaf_s leaf_p : F) (u : Nat → Bool)
    (xp c_ip c_qp : Nat → Nat) (ht : bytesOK t)
    (hxp : ∀ j, j < 13312 → xp j < 2 ^ 16)
    (hci : ∀ n, n < 12000 → c_ip n < 256) (hcq : ∀ n, n < 12000 → c_qp n < 256)
    (G : PhoneGlue t role_b leaf_s leaf_p u xp c_ip c_qp) :
    ∃ ls lp : Nat, ls < 256 ∧ lp < 256 ∧ leaf_s = (ls : F) ∧ leaf_p = (lp : F) ∧
      (asU32 (osF t leaf_s) : Int) = pSelf t - 127 - 1024 * ls ∧
      asU32 (osF t leaf_s) < 1024 ∧
      (asU32 (opF t role_b leaf_p) : Int) = aPartner t role_b - 31 - 1024 * lp ∧
      asU32 (opF t role_b leaf_p) < 1024 ∧
      asU32 (opF t role_b leaf_p) + 12062 ≤ 13312 ∧
      -96 ≤ sod t ∧ sod t ≤ 96 ∧
      -7200 ≤ aPartner t role_b - pPartner t ∧ aPartner t role_b - pPartner t ≤ 12000 ∧
      EI xp (asU32 (opF t role_b leaf_p)) * CI c_ip ≤
        BAR * (II xp (asU32 (opF t role_b leaf_p)) c_ip ^ 2 +
               II xp (asU32 (opF t role_b leaf_p)) c_qp ^ 2) := by
  obtain ⟨ls, hls, hs, _, hsv, hs0, hs1⟩ := os_window t leaf_s ht G.leaf_s_ok G.os_ok
  obtain ⟨lp, hlp, hp, _, hpv, hp0, hp1⟩ := op_window t role_b leaf_p ht G.leaf_p_ok G.op_ok
  have es := asU32_of_fits G.os_ok
  have ep := asU32_of_fits G.op_ok
  have hop : asU32 (opF t role_b leaf_p) < 1024 := by
    have h := G.op_ok; unfold fits at h; rw [ep]; norm_num at h; exact h
  have hos : asU32 (osF t leaf_s) < 1024 := by
    have h := G.os_ok; unfold fits at h; rw [es]; norm_num at h; exact h
  have hx : ∀ i, i < 12062 → xp (asU32 (opF t role_b leaf_p) + i) < 2 ^ 16 :=
    fun i hi => hxp _ (by omega)
  have hsod := sod_small t u ht G.u_last G.usum_ok
  have hwin := partner_window t role_b ht G.wpre_ok G.wpost_ok
  refine ⟨ls, lp, hls, hlp, hs, hp, ?_, hos, ?_, hop, by omega, hsod.2.1, hsod.2.2, hwin.1, hwin.2,
    (partner_loud xp _ c_ip c_qp hx hci hcq).mp G.partner_ok⟩
  · rw [es]; exact hsv
  · rw [ep]; exact hpv

/-! ### The glue can all hold at once -/

/-- `a_self = 1000` (bytes 269-272), `p_partner = 1200` (273-276), `half = 200` (173-176), `sod = 0`. -/
def tW (i : Nat) : Nat :=
  if i = 271 then 3 else if i = 272 then 232 else if i = 275 then 4 else if i = 276 then 176
  else if i = 176 then 200 else 0

theorem usumNat_prefix (k n : Nat) : usumNat (fun j => decide (j < k)) n = min n k := by
  induction n with
  | zero => simp [usumNat]
  | succ n ih =>
    simp only [usumNat, ih, decide_eq_true_eq]
    split <;> omega

/-- **The glue constraints are not contradictory, and not only on 0/0.** A concrete assignment meets every input
range `phone_core_glue` asks for and all of `PhoneGlue` at once (`a_self = 1000`, `sod = 0`, `half = 200`,
`p_partner = 1200`, role A, `leaf_s = 0`, `leaf_p = 1`, first 96 flags set, so `os = 873`, `op = 145`), with
`E * cn2 > 0` at the partner window. So `phone_core_glue` is not vacuous. The recording is the toy constant one
of `partner_accepts_nonsilent`. It shows reachability, not a realistic signal. -/
theorem phone_glue_nonvacuous :
    bytesOK tW ∧ (∀ j, j < 13312 → (fun _ => 32769 : Nat → Nat) j < 2 ^ 16) ∧
    (∀ n, n < 12000 → (fun _ => 129 : Nat → Nat) n < 256) ∧
    (∀ n, n < 12000 → (fun _ => 128 : Nat → Nat) n < 256) ∧
    PhoneGlue tW false 0 ((1 : Nat) : F) (fun j => decide (j < 96)) (fun _ => 32769)
      (fun _ => 129) (fun _ => 128) ∧
    0 < EI (fun _ => 32769) (asU32 (opF tW false ((1 : Nat) : F))) * CI (fun _ => 129) := by
  have ht : bytesOK tW := by
    intro i _; unfold tW; split_ifs <;> norm_num
  refine ⟨ht, fun _ _ => by norm_num, fun _ _ => by norm_num, fun _ _ => by norm_num, ?_,
    (partner_accepts_nonsilent _).2⟩
  have hA : aSelf tW = 1000 := by decide
  have hP : pPartner tW = 1200 := by decide
  have hH : half tW = 200 := by decide
  have hS : sod tW = 0 := by decide
  have hPS : pSelf tW = 1000 := by simp [pSelf, hA, hS]
  have hAP : aPartner tW false = 1200 := by simp [aPartner, sg, hA, hH]
  have hc := signed_casts tW false ht
  have fit : ∀ {k : Nat} (z : Int), k ≤ 252 → |z| < 2 ^ 252 → 0 ≤ z → z < 2 ^ k → fits k (z : F) := by
    intro k z hk hz h0 h1
    exact (fits_intCast_iff_of_abs hk (by norm_num) hz).mpr ⟨h0, h1⟩
  have hop : opF tW false ((1 : Nat) : F) = ((145 : Int) : F) := by
    rw [opF_cast tW false 1 ht, hAP]; norm_num
  have hos : osF tW 0 = ((873 : Int) : F) := by
    have := osF_cast tW 0 ht
    simp only [Nat.cast_zero] at this
    rw [this, hPS]; norm_num
  refine ⟨?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_⟩
  · rw [hos]; exact fit _ (by norm_num) (by norm_num) (by norm_num) (by norm_num)
  · simp [fits]
  · rw [hop]; exact fit _ (by norm_num) (by norm_num) (by norm_num) (by norm_num)
  · exact fits_natCast (by norm_num) (by norm_num)
  · decide
  · have hT : usumTarget tW = ((96 : Nat) : F) := by
      simp only [usumTarget, pSelfF, hc.2.2.2.1, hS]; push_cast; ring
    rw [usumLoop_eq, usumNat_prefix, hT]; norm_num
  · exact (partner_accepts_nonsilent _).1
  · have e : aPartnerF tW false - pPartnerF tW + 7200 = ((7200 : Int) : F) := by
      rw [hc.2.2.2.2.2, hc.2.1, hAP, hP]; push_cast; ring
    rw [e]; exact fit _ (by norm_num) (by norm_num) (by norm_num) (by norm_num)
  · have e : pPartnerF tW + 12000 - aPartnerF tW false = ((12000 : Int) : F) := by
      rw [hc.2.2.2.2.2, hc.2.1, hAP, hP]; push_cast; ring
    rw [e]; exact fit _ (by norm_num) (by norm_num) (by norm_num) (by norm_num)

/-! ## The half commitment (lib.nr 528-534): modelled call, opaque hash -/

/-- The eleven `hash_n` arguments of lines 531-532, by name. -/
structure HalfOpening where
  nonce_hi : F
  nonce_lo : F
  attempt : F
  role_b : F
  sr : F
  half : F
  salt : F
  x_own0 : F
  x_own1 : F
  x_partner0 : F
  x_partner1 : F

/-- The arguments in source order. -/
def HalfOpening.toList (o : HalfOpening) : List F :=
  [o.nonce_hi, o.nonce_lo, o.attempt, o.role_b, o.sr, o.half, o.salt, o.x_own0, o.x_own1, o.x_partner0, o.x_partner1]

/-- lines 528-534: `hash_n(TAG_HALF, [...])`, `TAG_HALF = 8` (line 44), with `hash_n` an arbitrary function. -/
def halfCommit (H : F → List F → F) (o : HalfOpening) : F := H 8 o.toList

/-- **What the half commitment binds, IF the hash does.** Given a collision hypothesis for exactly these two
openings, equal commitments mean equal nonce, attempt, role, sr, half, salt and both keys. Binding is ASSUMED,
not proved. The only thing checked is that all eleven fields go into the hash. Hiding is not addressed. -/
theorem half_commit_binds (H : F → List F → F) (a b : HalfOpening)
    (hcr : H 8 a.toList = H 8 b.toList → a.toList = b.toList)
    (h : halfCommit H a = halfCommit H b) : a = b := by
  have := hcr h
  cases a; cases b
  simp only [HalfOpening.toList, List.cons.injEq, and_true] at this
  obtain ⟨h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11⟩ := this
  subst h1 h2 h3 h4 h5 h6 h7 h8 h9 h10 h11
  rfl

end PartnerGlue
end Popfv

#print axioms Popfv.PartnerGlue.signed32_eq
#print axioms Popfv.PartnerGlue.half_is_gap
#print axioms Popfv.PartnerGlue.os_window
#print axioms Popfv.PartnerGlue.op_window
#print axioms Popfv.PartnerGlue.partner_window
#print axioms Popfv.PartnerGlue.sod_small
#print axioms Popfv.PartnerGlue.beF32_wraps
#print axioms Popfv.PartnerGlue.prun_inv
#print axioms Popfv.PartnerGlue.partner_loud
#print axioms Popfv.PartnerGlue.partner_silence_accepts
#print axioms Popfv.PartnerGlue.zero_template_accepts
#print axioms Popfv.PartnerGlue.partner_accepts_nonsilent
#print axioms Popfv.PartnerGlue.partner_rejects
#print axioms Popfv.PartnerGlue.phone_core_glue
#print axioms Popfv.PartnerGlue.phone_glue_nonvacuous
#print axioms Popfv.PartnerGlue.half_commit_binds
