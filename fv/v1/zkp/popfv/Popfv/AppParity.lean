import Popfv.Field

/-!
# APP item: transcript integer decode parity (Kotlin app vs Noir circuit)

Kotlin side: `app/composeApp/src/commonMain/kotlin/com/enconomy/pop/Transcript.kt`
* line 51-52  `pSelf = aSelf - selfOsDelta`, `aPartner = if (role == 'A') aSelf + half else aSelf - half`
* line 106-122 `transcript2` (encoder), line 148 `W.be(v, n)`
* line 124-139 `decodeTranscript2`, local `be(off, n)` at line 129

Circuit side: `research/worldid/prototypes/optA-noir/noir/oalib/src/lib.nr`
* line 171-177 `be_f`, line 179-182 `signed32`, line 284-296 (`a_self`, `p_partner`, `half`,
  `sod`, `sg`, `p_self`, `a_partner`), role tie line 233 `assert(t[5] == 0x41 + (role_b as u8))`.

JVM model (literal):
* `Long` is an `Int` in `[-2^63, 2^63)`; every Long op is done exactly and then reduced with
  `toLong` (two's complement wrap mod 2^64).  `Int` (32-bit) ops are reduced with `toInt32`.
* A Kotlin `Byte` is an `Int` in `[-128, 128)`; `ByteArray` is `Nat → Int`.
* `shl`, `or`, `and`, `ushr` act on the 64-bit pattern `bits64 z = z mod 2^64`.
* Noir `u8` array `t` is `Nat → Nat` with every entry `< 256`; `x as Field` is the Nat cast.
-/

set_option linter.style.whitespace false
set_option linter.style.longLine false
set_option linter.style.header false

namespace Popfv
namespace AppParity

/-! ## JVM integer semantics -/

/-- Two's complement reinterpretation to a 64-bit `Long`. -/
def toLong (z : Int) : Int := if z % 2^64 < 2^63 then z % 2^64 else z % 2^64 - 2^64

/-- `Long.toInt()`: keep the low 32 bits, two's complement. Also models `Int` `+`/`-` wraparound. -/
def toInt32 (z : Int) : Int := if z % 2^32 < 2^31 then z % 2^32 else z % 2^32 - 2^32

/-- `Long.toByte()`: keep the low 8 bits, two's complement. -/
def toByte (z : Int) : Int := if z % 256 < 128 then z % 256 else z % 256 - 256

/-- The 64-bit pattern of a Long, as a natural number. -/
def bits64 (z : Int) : Nat := (z % 2^64).toNat

/-- `v shl k` on Long. -/
def shl (v : Int) (k : Nat) : Int := toLong (v * 2^k)

/-- `a or b` on Long. -/
def lor (a b : Int) : Int := toLong ((bits64 a ||| bits64 b : Nat) : Int)

/-- `a and b` on Long. -/
def land (a b : Int) : Int := toLong ((bits64 a &&& bits64 b : Nat) : Int)

/-- `v ushr k` on Long (logical shift). -/
def ushr (v : Int) (k : Nat) : Int := toLong ((bits64 v / 2^k : Nat) : Int)

/-- Kotlin `b[j].toLong() and 0xff` (`Byte.toLong()` sign-extends, i.e. is the identity on values). -/
def uByte (kb : Nat → Int) (j : Nat) : Int := land (kb j) 0xff

/-- Kotlin decoder `be` (Transcript.kt line 129):
`var v = 0L; for (i in 0 until n) v = (v shl 8) or (b[off + i].toLong() and 0xff)`. -/
def ktBe (kb : Nat → Int) (off n : Nat) : Int :=
  (List.range n).foldl (fun v i => lor (shl v 8) (uByte kb (off + i))) 0

/-- Kotlin encoder `W.be(v, n)` (Transcript.kt line 148):
`for (k in n - 1 downTo 0) b[i++] = (v ushr (8 * k)).toByte()`.
Byte number `j` (`0 ≤ j < n`) of the written block is the one with `k = n - 1 - j`. -/
def wBe (v : Int) (n j : Nat) : Int := toByte (ushr v (8 * (n - 1 - j)))

/-- A value is a Kotlin `Byte`. -/
def isByte (z : Int) : Prop := -128 ≤ z ∧ z < 128

/-! ## Circuit model -/

/-- lib.nr line 171-177 `be_f`: `v = v * 256 + t[off + i] as Field` for `i in 0..n`. -/
def be_f (t : Nat → Nat) (off n : Nat) : F :=
  (List.range n).foldl (fun v i => v * 256 + ((t (off + i) : Nat) : F)) 0

/-- lib.nr line 179-182 `signed32`: `msb = (t[off] >> 7) as Field; be_f(t, off, 4) - msb * 4294967296`. -/
def signed32 (t : Nat → Nat) (off : Nat) : F :=
  be_f t off 4 - ((t off / 2^7 : Nat) : F) * 4294967296

/-- The same big-endian fold, in natural numbers (the mathematical spec). -/
def beN (t : Nat → Nat) (off n : Nat) : Nat :=
  (List.range n).foldl (fun v i => v * 256 + t (off + i)) 0

/-- The mathematical value of `signed32`, in integers. -/
def sgn32 (t : Nat → Nat) (off : Nat) : Int := (beN t off 4 : Int) - ((t off / 128 : Nat) : Int) * 2^32

/-! ## Basic lemmas -/

/-- One more step of a fold over `range`, for any step function `f`. -/
theorem foldl_range_succ {α : Type} (f : α → Nat → α) (a : α) (n : Nat) :
    (List.range (n + 1)).foldl f a = f ((List.range n).foldl f a) n := by
  simp [List.range_succ, List.foldl_append]

theorem beN_succ (t : Nat → Nat) (off n : Nat) :
    beN t off (n + 1) = beN t off n * 256 + t (off + n) := by
  simp [beN, List.range_succ, List.foldl_append]

theorem be_f_succ (t : Nat → Nat) (off n : Nat) :
    be_f t off (n + 1) = be_f t off n * 256 + ((t (off + n) : Nat) : F) := by
  simp [be_f, List.range_succ, List.foldl_append]

theorem ktBe_succ (kb : Nat → Int) (off n : Nat) :
    ktBe kb off (n + 1) = lor (shl (ktBe kb off n) 8) (uByte kb (off + n)) := by
  unfold ktBe; exact foldl_range_succ _ _ n

/-- `be_f` (lib.nr 171-177) is the natural number `beN` cast into the field. -/
theorem be_eq_be_f (t : Nat → Nat) (off n : Nat) : be_f t off n = ((beN t off n : Nat) : F) := by
  induction n with
  | zero => simp [be_f, beN]
  | succ n ih => rw [be_f_succ, beN_succ, ih]; push_cast; ring

/-- `beN` of `n` bytes is below `256^n = 2^(8n)`. -/
theorem beN_lt (t : Nat → Nat) (ht : ∀ i, t i < 256) (off n : Nat) : beN t off n < 2^(8*n) := by
  induction n with
  | zero => simp [beN]
  | succ n ih =>
    rw [beN_succ, show 8 * (n+1) = 8 * n + 8 by ring, pow_add]
    have := ht (off + n)
    nlinarith

theorem beN_four (t : Nat → Nat) (off : Nat) :
    beN t off 4 = t off * 2^24 + t (off+1) * 2^16 + t (off+2) * 2^8 + t (off+3) := by
  simp only [beN_succ]; simp [beN]; ring

theorem toLong_of_small {z : Int} (h0 : 0 ≤ z) (h1 : z < 2^63) : toLong z = z := by
  unfold toLong
  have : z % 2^64 = z := Int.emod_eq_of_lt h0 (by omega)
  rw [this]; exact if_pos h1

theorem bits64_of_small {z : Int} (h0 : 0 ≤ z) (h1 : z < 2^64) : (bits64 z : Int) = z := by
  unfold bits64
  rw [Int.emod_eq_of_lt h0 h1]; exact Int.toNat_of_nonneg h0

theorem toLong_emod256 (z : Int) : toLong z % 256 = z % 256 := by
  unfold toLong; split_ifs <;> omega

theorem toByte_emod256 (z : Int) : toByte z % 256 = z % 256 := by
  unfold toByte; split_ifs <;> omega

/-- `b.toLong() and 0xff` is the unsigned byte `b mod 256`. -/
theorem uByte_eq (kb : Nat → Int) (j : Nat) : uByte kb j = kb j % 256 := by
  unfold uByte land
  have h255 : bits64 (0xff : Int) = 2^8 - 1 := by unfold bits64; norm_num
  rw [h255, Nat.and_two_pow_sub_one_eq_mod]
  have hb : ((bits64 (kb j) : Nat) : Int) = kb j % 2^64 := by
    unfold bits64; exact Int.toNat_of_nonneg (Int.emod_nonneg _ (by norm_num))
  have : (((bits64 (kb j) % 2^8 : Nat)) : Int) = kb j % 256 := by
    push_cast; rw [hb]; omega
  rw [this]; exact toLong_of_small (Int.emod_nonneg _ (by norm_num)) (by omega)

/-- One decoder step without overflow: `(v shl 8) or u = v*256 + u` for small `v ≥ 0`, `u < 256`. -/
theorem step_eq {v u : Int} (hv0 : 0 ≤ v) (hv1 : v < 2^55) (hu0 : 0 ≤ u) (hu1 : u < 256) :
    lor (shl v 8) u = v * 256 + u := by
  unfold lor
  rw [show shl v 8 = v * 256 by unfold shl; exact toLong_of_small (by omega) (by omega)]
  obtain ⟨a, rfl⟩ := Int.eq_ofNat_of_zero_le hv0
  obtain ⟨b, rfl⟩ := Int.eq_ofNat_of_zero_le hu0
  have ha : bits64 ((a : Int) * 256) = a <<< 8 := by
    rw [Nat.shiftLeft_eq]; unfold bits64
    rw [Int.emod_eq_of_lt (by omega) (by omega)]; omega
  have hb : bits64 (b : Int) = b := by
    unfold bits64; rw [Int.emod_eq_of_lt (by omega) (by omega)]; simp
  rw [ha, hb, ← Nat.shiftLeft_add_eq_or_of_lt (by omega : b < 2^8), Nat.shiftLeft_eq]
  push_cast
  exact toLong_of_small (by omega) (by omega)

/-- **Decoder parity.** For `n ≤ 7` bytes the Kotlin `be` (a `Long` loop with `shl`/`or`) never
overflows and returns exactly the big-endian number that the circuit's `be_f` computes, where the
circuit's byte `t[i]` is the Kotlin byte read as unsigned (`b mod 256`). -/
theorem ktBe_eq_beN (kb : Nat → Int) (t : Nat → Nat) (ht : ∀ i, (t i : Int) = kb i % 256)
    (off n : Nat) (hn : n ≤ 7) : ktBe kb off n = (beN t off n : Int) := by
  have htl : ∀ i, t i < 256 := fun i => by have := ht i; omega
  induction n with
  | zero => simp [ktBe, beN]
  | succ n ih =>
    rw [ktBe_succ, ih (by omega), beN_succ, uByte_eq, ← ht]
    have hb := beN_lt t htl off n
    have : (2:Nat)^(8*n) ≤ 2^48 := Nat.pow_le_pow_right (by norm_num) (by omega)
    push_cast
    exact step_eq (by omega) (by omega) (by omega) (by have := htl (off+n); omega)

/-! ## signed32 parity -/

/-- **signed32 parity.** Kotlin `be(off, 4).toInt()` (two's complement) equals the integer the
circuit's `signed32` (lib.nr 179-182) means: the unsigned value minus `2^32` when the top bit of
the first byte is set. -/
theorem signed_parity (t : Nat → Nat) (ht : ∀ i, t i < 256) (off : Nat) :
    toInt32 (beN t off 4 : Int) = sgn32 t off := by
  unfold toInt32 sgn32
  rw [beN_four]
  have h0 := ht off; have h1 := ht (off+1); have h2 := ht (off+2); have h3 := ht (off+3)
  push_cast
  split_ifs <;> omega

/-- The circuit's `signed32` field element is the cast of the integer `sgn32`. -/
theorem signed32_eq (t : Nat → Nat) (off : Nat) : signed32 t off = ((sgn32 t off : Int) : F) := by
  have h : t off / 2^7 = t off / 128 := by norm_num
  unfold signed32 sgn32
  rw [be_eq_be_f, h]
  simp only [Int.cast_sub, Int.cast_mul, Int.cast_natCast, Int.cast_pow, Int.cast_ofNat]
  ring

theorem sgn32_bounds (t : Nat → Nat) (ht : ∀ i, t i < 256) (off : Nat) :
    -2^31 ≤ sgn32 t off ∧ sgn32 t off < 2^31 := by
  unfold sgn32; rw [beN_four]
  have h0 := ht off; have h1 := ht (off+1); have h2 := ht (off+2); have h3 := ht (off+3)
  push_cast; omega

/-- For a first byte below 128 (top bit clear) `signed32` is just the unsigned value. -/
theorem sgn32_of_msb0 (t : Nat → Nat) (off : Nat) (h : t off < 128) : sgn32 t off = beN t off 4 := by
  unfold sgn32; rw [Nat.div_eq_of_lt h]; simp

/-! ## Encoder round trip -/

/-- Unsigned reading of a byte written by `W.be(v, n)`: digit `n-1-j` of `v mod 2^64`. -/
theorem wBe_emod (v : Int) (n j : Nat) :
    wBe v n j % 256 = (v % 2^64) / 2^(8 * (n - 1 - j)) % 256 := by
  unfold wBe ushr
  rw [toByte_emod256, toLong_emod256]
  unfold bits64
  rw [Int.natCast_div, Int.toNat_of_nonneg (Int.emod_nonneg _ (by norm_num))]
  push_cast; rfl

theorem dig1 (u : Int) : u = u/256*256 + u%256 := by omega
theorem dig2 (u : Int) : u/256 = u/65536*256 + u/256%256 := by omega
theorem dig3 (u : Int) : u/65536 = u/16777216*256 + u/65536%256 := by omega
theorem dig4 (u : Int) : u/16777216 = u/16777216/256*256 + u/16777216%256 := by omega

theorem byte_bd (x : Int) : 0 ≤ x%256 ∧ x%256 < 256 := by omega

/-- A Long `v` in Int range, as a 64-bit pattern. -/
theorem mod_cases (v : Int) (hlo : -2147483648 ≤ v) (hhi : v < 2147483648) :
    (0 ≤ v → v % 18446744073709551616 = v) ∧
    (v < 0 → v % 18446744073709551616 = v + 18446744073709551616) := by
  constructor <;> intro h <;> omega

theorem bytes_bd (t0 t1 t2 t3 : Int) (b0 : 0 ≤ t0 ∧ t0 < 256) (b1 : 0 ≤ t1 ∧ t1 < 256)
    (b2 : 0 ≤ t2 ∧ t2 < 256) (b3 : 0 ≤ t3 ∧ t3 < 256) :
    0 ≤ t0*16777216 + t1*65536 + t2*256 + t3 ∧ t0*16777216 + t1*65536 + t2*256 + t3 < 4294967296 := by
  omega

theorem msb_low (t0 t1 t2 t3 : Int) (b0 : 0 ≤ t0 ∧ t0 < 256) (b1 : 0 ≤ t1 ∧ t1 < 256)
    (b2 : 0 ≤ t2 ∧ t2 < 256) (b3 : 0 ≤ t3 ∧ t3 < 256)
    (h : t0*16777216 + t1*65536 + t2*256 + t3 < 2147483648) : t0/128 = 0 := by
  omega

theorem msb_high (t0 t1 t2 t3 : Int) (b0 : 0 ≤ t0 ∧ t0 < 256) (b1 : 0 ≤ t1 ∧ t1 < 256)
    (b2 : 0 ≤ t2 ∧ t2 < 256) (b3 : 0 ≤ t3 ∧ t3 < 256)
    (h : 2147483648 ≤ t0*16777216 + t1*65536 + t2*256 + t3) : t0/128 = 1 := by
  omega

theorem finish_nonneg (v y R : Int) (h : v = y*4294967296 + R) (h0 : 0 ≤ R) (h1 : R < 4294967296)
    (hv0 : 0 ≤ v) (hv1 : v < 2147483648) : R = v := by omega

theorem finish_neg (v y R : Int) (h : v + 18446744073709551616 = y*4294967296 + R)
    (h0 : 0 ≤ R) (h1 : R < 4294967296) (hv0 : -2147483648 ≤ v) (hv1 : v < 0) :
    R = v + 4294967296 := by omega

/-- The arithmetic core: the four base-256 digits of the 64-bit pattern of `v` rebuild `v`. -/
theorem digits_value (v u t0 t1 t2 t3 : Int)
    (hlo : -2147483648 ≤ v) (hhi : v < 2147483648) (hu : u = v % 18446744073709551616)
    (d0 : t0 = u/16777216 % 256) (d1 : t1 = u/65536 % 256) (d2 : t2 = u/256 % 256) (d3 : t3 = u % 256) :
    t0*16777216 + t1*65536 + t2*256 + t3 - (t0/128)*4294967296 = v ∧
    (0 ≤ v → t0*16777216 + t1*65536 + t2*256 + t3 = v) := by
  have b0 : 0 ≤ t0 ∧ t0 < 256 := by rw [d0]; exact byte_bd _
  have b1 : 0 ≤ t1 ∧ t1 < 256 := by rw [d1]; exact byte_bd _
  have b2 : 0 ≤ t2 ∧ t2 < 256 := by rw [d2]; exact byte_bd _
  have b3 : 0 ≤ t3 ∧ t3 < 256 := by rw [d3]; exact byte_bd _
  have e1 := dig1 u
  have e2 := dig2 u
  have e3 := dig3 u
  have e4 := dig4 u
  rw [← d3] at e1
  rw [← d2] at e2
  rw [← d1] at e3
  rw [← d0] at e4
  clear d0 d1 d2 d3
  generalize u/16777216/256 = y4 at e4
  generalize u/16777216 = y3 at e3 e4
  generalize u/65536 = y2 at e2 e3
  generalize u/256 = y1 at e1 e2
  have hR : u = y4*4294967296 + (t0*16777216 + t1*65536 + t2*256 + t3) := by
    rw [e1, e2, e3, e4]; ring
  have hb := bytes_bd t0 t1 t2 t3 b0 b1 b2 b3
  have hc := mod_cases v hlo hhi
  have hlow := msb_low t0 t1 t2 t3 b0 b1 b2 b3
  have hhigh := msb_high t0 t1 t2 t3 b0 b1 b2 b3
  by_cases hv : 0 ≤ v
  · have huv : u = v := hu.trans (hc.1 hv)
    have hRv := finish_nonneg v y4 _ (huv.symm.trans hR) hb.1 hb.2 hv hhi
    have hq := hlow (by rw [hRv]; exact hhi)
    rw [hq, hRv]
    exact ⟨by ring, fun _ => rfl⟩
  · have hv' : v < 0 := not_le.mp hv
    have huv : u = v + 18446744073709551616 := hu.trans (hc.2 hv')
    have hRv := finish_neg v y4 _ (huv.symm.trans hR) hb.1 hb.2 hlo hv'
    have hq := hhigh (by rw [hRv]; linarith)
    rw [hq, hRv]
    exact ⟨by ring, fun h => absurd h hv⟩

/-- **Encoder round trip.** For any `Int` `v` (that is, `-2^31 ≤ v < 2^31`), the 4 bytes written
by `W.be(v.toLong(), 4)` decode back to `v`, both through the Kotlin decoder `be(off,4).toInt()`
and through the circuit's `signed32`. If also `v ≥ 0`, the circuit's unsigned `be_f` gives `v`
too. -/
theorem encode_roundtrip (v : Int) (hlo : -2^31 ≤ v) (hhi : v < 2^31)
    (kb : Nat → Int) (t : Nat → Nat) (ht : ∀ i, (t i : Int) = kb i % 256)
    (off : Nat) (hw : ∀ j, j < 4 → kb (off + j) = wBe v 4 j) :
    toInt32 (ktBe kb off 4) = v ∧ sgn32 t off = v ∧ signed32 t off = ((v : Int) : F) ∧
    (0 ≤ v → (beN t off 4 : Int) = v ∧ be_f t off 4 = ((v : Int) : F)) := by
  have htl : ∀ i, t i < 256 := fun i => by have := ht i; omega
  have hM : (2:Int)^64 = 18446744073709551616 := by norm_num
  have hlo' : -2147483648 ≤ v := by omega
  have hhi' : v < 2147483648 := by omega
  have d : ∀ j K, j < 4 → (2:Int)^(8 * (4 - 1 - j)) = K →
      (t (off + j) : Int) = (v % 18446744073709551616) / K % 256 := by
    intro j K hj hK
    rw [ht, hw j hj, wBe_emod, hK, hM]
  have d0 := d 0 16777216 (by norm_num) (by norm_num)
  have d1 := d 1 65536 (by norm_num) (by norm_num)
  have d2 := d 2 256 (by norm_num) (by norm_num)
  have d3 := d 3 1 (by norm_num) (by norm_num)
  rw [Nat.add_zero] at d0
  rw [Int.ediv_one] at d3
  obtain ⟨hA, hB⟩ := digits_value v _ _ _ _ _ hlo' hhi' rfl d0 d1 d2 d3
  have hs : sgn32 t off = v := by
    unfold sgn32; rw [beN_four]; push_cast
    exact hA
  have hk : toInt32 (ktBe kb off 4) = v := by
    rw [ktBe_eq_beN kb t ht off 4 (by norm_num), signed_parity t htl, hs]
  refine ⟨hk, hs, by rw [signed32_eq, hs], fun hv => ?_⟩
  have hu : (beN t off 4 : Int) = v := by
    rw [beN_four]; push_cast
    exact hB hv
  exact ⟨hu, by rw [be_eq_be_f, ← hu, Int.cast_natCast]⟩

/-! ## Main: `pSelf` / `aPartner` parity -/

/-- Kotlin `Transcript2` integer fields as `decodeTranscript2` (Transcript.kt 124-139) builds them,
one function per field, and the two derived getters (line 51-52). `Int` `+`/`-` wrap mod 2^32
(`toInt32`). `role = b[5].toInt().toChar()`, so `role == 'A'` is `kb 5 = 65`. -/
def ktHalf (kb : Nat → Int) : Int := toInt32 (ktBe kb 173 4)          -- line 133
def ktSelfOsDelta (kb : Nat → Int) : Int := toInt32 (ktBe kb 233 4)   -- line 135
def ktASelf (kb : Nat → Int) : Int := toInt32 (ktBe kb 269 4)         -- line 136
def ktPPartner (kb : Nat → Int) : Int := toInt32 (ktBe kb 273 4)      -- line 136

/-- `val pSelf: Int get() = aSelf - selfOsDelta` (line 51), with Int wraparound. -/
def ktPSelf (kb : Nat → Int) : Int := toInt32 (ktASelf kb - ktSelfOsDelta kb)

/-- `val aPartner: Int get() = if (role == 'A') aSelf + half else aSelf - half` (line 52). -/
def ktAPartner (kb : Nat → Int) : Int :=
  if kb 5 = 65 then toInt32 (ktASelf kb + ktHalf kb) else toInt32 (ktASelf kb - ktHalf kb)

/-- Circuit values, lib.nr line 284-293. -/
def c_a_self (t : Nat → Nat) : F := be_f t 269 4                       -- line 284
def c_half (t : Nat → Nat) : F := signed32 t 173                       -- line 286
def c_sod (t : Nat → Nat) : F := signed32 t 233                        -- line 287
def c_sg (role_b : Bool) : F := 1 - 2 * ((if role_b then 1 else 0 : Nat) : F)  -- line 288
def c_p_self (t : Nat → Nat) : F := c_a_self t - c_sod t               -- line 292
def c_a_partner (t : Nat → Nat) (role_b : Bool) : F := c_a_self t + c_sg role_b * c_half t  -- line 293

/-- The exact integers the circuit means. -/
def P_self (t : Nat → Nat) : Int := (beN t 269 4 : Int) - sgn32 t 233
def A_partner (t : Nat → Nat) (role_b : Bool) : Int :=
  (beN t 269 4 : Int) + (if role_b then -1 else 1) * sgn32 t 173

theorem toInt32_of_range {z : Int} (h0 : -2^31 ≤ z) (h1 : z < 2^31) : toInt32 z = z := by
  unfold toInt32; split_ifs <;> omega

/-- **Main parity theorem.** Take the 311 transcript bytes as the Kotlin app holds them (`kb`) and
as the circuit sees them (`t`, the same bytes read unsigned), with the circuit's role check
`t[5] = 0x41 + role_b` and with `a_self < 2^31` (first byte of `a_self` below 128, which the
encoder guarantees by `require(aSelf >= 0)`). Then:
1. the circuit's `p_self` and `a_partner` are the casts of the true integers
   `P = a_self - sod` and `A = a_self ± half` (sign `+` for role A), and `|P|, |A| < 2^33`, far
   below `p`, so the field values never wrap;
2. the Kotlin decoder reads `aSelf`, `selfOsDelta`, `half` as exactly the circuit's `a_self`,
   `sod`, `half` (as integers);
3. Kotlin's `pSelf` / `aPartner` equal `P` / `A` reduced into 32-bit `Int` range, so whenever
   `P` (resp. `A`) is in `[-2^31, 2^31)` the app and the circuit agree exactly.
(Outside that range Kotlin's 32-bit arithmetic wraps; see `hole_pSelf_overflow`.) -/
theorem transcript_parity (kb : Nat → Int) (t : Nat → Nat) (role_b : Bool)
    (ht : ∀ i, (t i : Int) = kb i % 256)
    (hrole : t 5 = 0x41 + (if role_b then 1 else 0))
    (hrole_kt : kb 5 = 65 ∨ kb 5 = 66)
    (ha : t 269 < 128) :
    -- 1. circuit values are faithful integers
    c_p_self t = ((P_self t : Int) : F) ∧ c_a_partner t role_b = ((A_partner t role_b : Int) : F) ∧
    |P_self t| < 2^33 ∧ |A_partner t role_b| < 2^33 ∧
    -- 2. Kotlin decodes the same integers
    ktASelf kb = beN t 269 4 ∧ ktSelfOsDelta kb = sgn32 t 233 ∧
    ktHalf kb = sgn32 t 173 ∧ (kb 5 = 65 ↔ role_b = false) ∧
    -- 3. Kotlin derived getters = circuit integers, mod 2^32
    ktPSelf kb = toInt32 (P_self t) ∧ ktAPartner kb = toInt32 (A_partner t role_b) ∧
    (-2^31 ≤ P_self t → P_self t < 2^31 →
       ktPSelf kb = P_self t ∧ ((ktPSelf kb : Int) : F) = c_p_self t) ∧
    (-2^31 ≤ A_partner t role_b → A_partner t role_b < 2^31 →
       ktAPartner kb = A_partner t role_b ∧
       ((ktAPartner kb : Int) : F) = c_a_partner t role_b) := by
  have htl : ∀ i, t i < 256 := fun i => by have := ht i; omega
  have hdec : ∀ off, toInt32 (ktBe kb off 4) = sgn32 t off := fun off => by
    rw [ktBe_eq_beN kb t ht off 4 (by norm_num), signed_parity t htl]
  have hA : ktASelf kb = beN t 269 4 := by
    unfold ktASelf; rw [hdec, sgn32_of_msb0 t 269 ha]
  have hS : ktSelfOsDelta kb = sgn32 t 233 := by unfold ktSelfOsDelta; exact hdec 233
  have hH : ktHalf kb = sgn32 t 173 := by unfold ktHalf; exact hdec 173
  have hR : kb 5 = 65 ↔ role_b = false := by
    have h5 := ht 5
    cases role_b <;> simp at hrole <;> rw [hrole] at h5 <;> simp <;> omega
  have hb := beN_lt t htl 269 4
  have bS := sgn32_bounds t htl 233
  have bH := sgn32_bounds t htl 173
  have hcP : c_p_self t = ((P_self t : Int) : F) := by
    unfold c_p_self c_a_self c_sod P_self; rw [be_eq_be_f, signed32_eq]; push_cast; ring
  have hcA : c_a_partner t role_b = ((A_partner t role_b : Int) : F) := by
    unfold c_a_partner c_a_self c_sg c_half A_partner; rw [be_eq_be_f, signed32_eq]
    cases role_b <;> simp only [Bool.false_eq_true, ↓reduceIte] <;> push_cast <;> ring
  have hkP : ktPSelf kb = toInt32 (P_self t) := by
    unfold ktPSelf P_self; rw [hA, hS]
  have hkA : ktAPartner kb = toInt32 (A_partner t role_b) := by
    unfold ktAPartner A_partner
    cases role_b
    · have h65 : kb 5 = 65 := hR.mpr rfl
      rw [if_pos h65, hA, hH]; simp
    · have h65 : ¬ kb 5 = 65 := fun h => by simpa using hR.mp h
      rw [if_neg h65, hA, hH]; simp; ring_nf
  refine ⟨hcP, hcA, ?_, ?_, hA, hS, hH, hR, hkP, hkA, ?_, ?_⟩
  · unfold P_self; rw [abs_lt]; constructor <;> norm_num at hb ⊢ <;> omega
  · unfold A_partner; rw [abs_lt]; cases role_b <;> simp <;> norm_num at hb ⊢ <;> omega
  · intro h0 h1; rw [hkP, toInt32_of_range h0 h1]; exact ⟨rfl, hcP.symm⟩
  · intro h0 h1; rw [hkA, toInt32_of_range h0 h1]; exact ⟨rfl, hcA.symm⟩

/-- The hypothesis `a_self < 2^31` is the same as "first byte below 128". -/
theorem lt_two_pow_31_iff (t : Nat → Nat) (ht : ∀ i, t i < 256) (off : Nat) :
    beN t off 4 < 2^31 ↔ t off < 128 := by
  rw [beN_four]
  have h0 := ht off; have h1 := ht (off+1); have h2 := ht (off+2); have h3 := ht (off+3)
  omega

/-- The sign in the circuit's form: `sg = 1 - 2 * role_b` (lib.nr line 288, 293). -/
theorem A_partner_eq (t : Nat → Nat) (role_b : Bool) :
    A_partner t role_b = (beN t 269 4 : Int) + (1 - 2 * (if role_b then 1 else 0 : Int)) * sgn32 t 173 := by
  cases role_b <;> simp [A_partner]

/-- `p_partner` (lib.nr line 285, unsigned) and Kotlin `pPartner` (`.toInt()`, signed) agree when
the first byte is below 128, which the encoder guarantees by `require(pPartner >= 0)`. -/
theorem p_partner_parity (kb : Nat → Int) (t : Nat → Nat) (ht : ∀ i, (t i : Int) = kb i % 256)
    (h : t 273 < 128) :
    ktPPartner kb = beN t 273 4 ∧ be_f t 273 4 = ((beN t 273 4 : Nat) : F) := by
  have htl : ∀ i, t i < 256 := fun i => by have := ht i; omega
  refine ⟨?_, be_eq_be_f t 273 4⟩
  unfold ktPPartner
  rw [ktBe_eq_beN kb t ht 273 4 (by norm_num), signed_parity t htl, sgn32_of_msb0 t 273 h]

/-- **App to circuit, end to end.** Start from the numbers the app holds: `aSelf ≥ 0`, `half` and
`selfOsDelta`, each a 32-bit `Int`. Write them with `W.be(v.toLong(), 4)` at the transcript offsets.
Then the circuit's `p_self` is exactly `aSelf - selfOsDelta` and its `a_partner` is exactly
`aSelf ± half` (plus for role A), as true integers placed in the field. -/
theorem encoder_to_circuit (aSelf half sod : Int)
    (ha0 : 0 ≤ aSelf) (ha1 : aSelf < 2^31)
    (hh0 : -2^31 ≤ half) (hh1 : half < 2^31)
    (hs0 : -2^31 ≤ sod) (hs1 : sod < 2^31)
    (kb : Nat → Int) (t : Nat → Nat) (ht : ∀ i, (t i : Int) = kb i % 256) (role_b : Bool)
    (wh : ∀ j, j < 4 → kb (173 + j) = wBe half 4 j)
    (ws : ∀ j, j < 4 → kb (233 + j) = wBe sod 4 j)
    (wa : ∀ j, j < 4 → kb (269 + j) = wBe aSelf 4 j) :
    c_p_self t = ((aSelf - sod : Int) : F) ∧
    c_a_partner t role_b = ((aSelf + (if role_b then -1 else 1) * half : Int) : F) := by
  have ra := ((encode_roundtrip aSelf (by omega) ha1 kb t ht 269 wa).2.2.2 ha0).2
  have rs := (encode_roundtrip sod hs0 hs1 kb t ht 233 ws).2.2.1
  have rh := (encode_roundtrip half hh0 hh1 kb t ht 173 wh).2.2.1
  constructor
  · unfold c_p_self c_a_self c_sod; rw [ra, rs]; push_cast; ring
  · unfold c_a_partner c_a_self c_sg c_half; rw [ra, rh]
    cases role_b <;> simp only [Bool.false_eq_true, ↓reduceIte] <;> push_cast <;> ring

/-! ## Parity gap: Kotlin 32-bit overflow -/

/-- Witness bytes: `a_self = 0x7fffffff` (allowed by the encoder: `aSelf ≥ 0`), `selfOsDelta =
-2^31` (`0x80000000`, any Int is allowed), everything else 0, role 'A'. -/
def holeKb (i : Nat) : Int :=
  if i = 5 then 65
  else if i = 269 then 127 else if i = 270 ∨ i = 271 ∨ i = 272 then -1
  else if i = 233 then -128 else 0

def holeT (i : Nat) : Nat := (holeKb i % 256).toNat

/-- **Parity gap (app-side, not a circuit bug).** With `a_self = 2^31 - 1` and `selfOsDelta = -2^31`
(both accepted by the encoder), the circuit's `p_self` is the true integer `2^32 - 1`, but the
Kotlin getter `pSelf = aSelf - selfOsDelta` overflows 32-bit `Int` and returns `-1`. -/
theorem hole_pSelf_overflow :
    P_self holeT = 2^32 - 1 ∧ ktPSelf holeKb = -1 ∧
    c_p_self holeT = (((2^32 - 1 : Int)) : F) := by
  have ht : ∀ i, (holeT i : Int) = holeKb i % 256 := fun i => by
    unfold holeT; exact Int.toNat_of_nonneg (Int.emod_nonneg _ (by norm_num))
  have h5 : holeT 5 = 65 := by norm_num [holeT, holeKb]
  have h269 : holeT 269 = 127 := by norm_num [holeT, holeKb]
  have h270 : holeT 270 = 255 := by norm_num [holeT, holeKb]
  have h271 : holeT 271 = 255 := by norm_num [holeT, holeKb]
  have h272 : holeT 272 = 255 := by norm_num [holeT, holeKb]
  have h233 : holeT 233 = 128 := by norm_num [holeT, holeKb]
  have h234 : holeT 234 = 0 := by norm_num [holeT, holeKb]
  have h235 : holeT 235 = 0 := by norm_num [holeT, holeKb]
  have h236 : holeT 236 = 0 := by norm_num [holeT, holeKb]
  have hP : P_self holeT = 2^32 - 1 := by
    unfold P_self sgn32
    rw [beN_four holeT 269, beN_four holeT 233]
    norm_num [h269, h270, h271, h272, h233, h234, h235, h236]
  obtain ⟨hc, _, _, _, _, _, _, _, hk, _⟩ := transcript_parity holeKb holeT false ht
    (by norm_num [h5]) (Or.inl (by norm_num [holeKb])) (by norm_num [h269])
  refine ⟨hP, ?_, ?_⟩
  · rw [hk, hP]; unfold toInt32; norm_num
  · rw [hc, hP]

end AppParity
end Popfv

#print axioms Popfv.AppParity.be_eq_be_f
#print axioms Popfv.AppParity.beN_lt
#print axioms Popfv.AppParity.ktBe_eq_beN
#print axioms Popfv.AppParity.signed_parity
#print axioms Popfv.AppParity.encode_roundtrip
#print axioms Popfv.AppParity.transcript_parity
#print axioms Popfv.AppParity.hole_pSelf_overflow
#print axioms Popfv.AppParity.lt_two_pow_31_iff
#print axioms Popfv.AppParity.A_partner_eq
#print axioms Popfv.AppParity.p_partner_parity
#print axioms Popfv.AppParity.encoder_to_circuit
#print axioms Popfv.AppParity.digits_value
