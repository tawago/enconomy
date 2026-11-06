import Popfv.Signed

/-!
# Evpfv.Limbs: Noir limbs against `PopCtx.split`

The contract splits a device key `X` as
`hi = X >> 128`, `lo = uint128(X)` (PopCtx.sol lines 40-43), so `X / 2^128` and `X % 2^128`.
The phone reads its own key as `be_f(t, 40, 16)`, `be_f(t, 56, 16)` (lib.nr line 275), and it signs
bytes `t[40..72]` as that key (lib.nr lines 250, 261).

`limbs_pin_key` says the two agree: when the limbs match the split, those 32 bytes read big-endian
are exactly `X`.

`beF` and `beNat` are v1's (`PartnerGlue`, lib.nr 171-177). `beNat t off n` is the big-endian
value of `n` bytes from `off`: the first byte is the most significant.
-/

set_option linter.style.whitespace false
set_option linter.style.longLine false
set_option linter.style.header false

namespace Evpfv

open Popfv Popfv.PartnerGlue

/-- The high limb is the cast of its big-endian value. -/
theorem own_hi_cast (t : Nat → Nat) : beF t 40 16 = (beNat t 40 16 : F) := beF_eq t 40 16

/-- The low limb is the cast of its big-endian value. -/
theorem own_lo_cast (t : Nat → Nat) : beF t 56 16 = (beNat t 56 16 : F) := beF_eq t 56 16

theorem limb_lt_p {a : Nat} (h : a < 2 ^ 128) : a < p :=
  natCast_lt_p_of_lt_two_pow (by norm_num) h

/-- Limbs under `2^128` do not collide in `F`. -/
theorem limb_cast_inj {a b : Nat} (ha : a < 2 ^ 128) (hb : b < 2 ^ 128) (e : (a : F) = (b : F)) :
    a = b := by
  have := congrArg ZMod.val e
  rwa [val_natCast_of_lt (limb_lt_p ha), val_natCast_of_lt (limb_lt_p hb)] at this

/-- The 32 key bytes are the high limb, then the low limb. -/
theorem own_key_split (t : Nat → Nat) :
    beNat t 40 32 = beNat t 40 16 * 2 ^ 128 + beNat t 56 16 := by
  have h := Signed.beNat_split t 40 16 16
  norm_num at h ⊢
  exact h

/-- The 32 bytes the phone signed as its own key are exactly `X`, in the order the contract uses. -/
theorem limbs_pin_key (t : Nat → Nat) (X : Nat) (ht : bytesOK t) (hX : X < 2 ^ 256)
    (hhi : beF t 40 16 = ((X / 2 ^ 128 : Nat) : F))
    (hlo : beF t 56 16 = ((X % 2 ^ 128 : Nat) : F)) :
    beNat t 40 32 = X := by
  have hiLt : X / 2 ^ 128 < 2 ^ 128 := Nat.div_lt_of_lt_mul (by simpa using hX)
  have loLt : X % 2 ^ 128 < 2 ^ 128 := Nat.mod_lt _ (by norm_num)
  have hi : beNat t 40 16 = X / 2 ^ 128 :=
    limb_cast_inj (Signed.beNat16_lt t 40 fun i _ => ht _ (by omega)) hiLt ((own_hi_cast t).symm.trans hhi)
  have lo : beNat t 56 16 = X % 2 ^ 128 :=
    limb_cast_inj (Signed.beNat16_lt t 56 fun i _ => ht _ (by omega)) loLt ((own_lo_cast t).symm.trans hlo)
  rw [own_key_split, hi, lo, Nat.div_add_mod' X]

/-- The public inputs of the recovery `pair` circuit, in circuit order: `main.nr` lines 4-10, then
`xa` and `xb` made public. The private `half_a salt_a half_b salt_b` add no entries. -/
def pairPublicInputs (nonce_hi nonce_lo : F) (attempt : Nat) (commit_a commit_b : F)
    (sr_a sr_b : Nat) (xa0 xa1 xb0 xb1 : F) : List F :=
  [nonce_hi, nonce_lo, (attempt : F), commit_a, commit_b, (sr_a : F), (sr_b : F), xa0, xa1, xb0, xb1]

theorem pairPublicInputs_length (nonce_hi nonce_lo : F) (attempt : Nat) (commit_a commit_b : F)
    (sr_a sr_b : Nat) (xa0 xa1 xb0 xb1 : F) :
    (pairPublicInputs nonce_hi nonce_lo attempt commit_a commit_b sr_a sr_b xa0 xa1 xb0 xb1).length = 11 :=
  rfl

/-- Positions 7..10, the `p[7..10]` of `verifyPresence`, are `xa0 xa1 xb0 xb1`. -/
theorem pairPublicInputs_keys (nonce_hi nonce_lo : F) (attempt : Nat) (commit_a commit_b : F)
    (sr_a sr_b : Nat) (xa0 xa1 xb0 xb1 : F) :
    let l := pairPublicInputs nonce_hi nonce_lo attempt commit_a commit_b sr_a sr_b xa0 xa1 xb0 xb1
    l[7]? = some xa0 ∧ l[8]? = some xa1 ∧ l[9]? = some xb0 ∧ l[10]? = some xb1 :=
  ⟨rfl, rfl, rfl, rfl⟩

end Evpfv

#print axioms Evpfv.limb_cast_inj
#print axioms Evpfv.own_key_split
#print axioms Evpfv.limbs_pin_key
#print axioms Evpfv.pairPublicInputs_keys
