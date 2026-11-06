import Evpfv.Adapter
import Evpfv.Limbs
import Popfv.Chain

/-!
# Evpfv.Glue: the contract's checks, plus v1's `presence_sound`

`verifyPresence` accepts three proofs and compares their public words. `presence_sound` talks about witnesses.
This file joins the two. Its main theorem is `evp_presence_sound`; read its docstring before quoting it.

The two proof system hypotheses are `PhoneVerifierSound` and `PairVerifierSound`. They are assumed, not proved.
-/

set_option linter.style.whitespace false
set_option linter.style.longLine false
set_option linter.style.header false

namespace Evpfv

open Popfv Popfv.Chain Popfv.PartnerGlue Evpfv.Adapter
open Popfv.Commit (Perm hash_n)

/-! ## What a verifier's yes means -/

/-- The public values of `phone/src/main.nr`, in circuit order: lines 5-12 (`issuer` is four fields), then the return value.
That the return value comes last is read off the contract, which takes `a[11]` as `halfCommit`. -/
def phonePublicInputs (w : Witness) (out : F) : List F :=
  [w.nonce_hi, w.nonce_lo, (w.attempt : F), boolF w.role_b, w.code_commit, w.issuer 0, w.issuer 1, w.issuer 2, w.issuer 3,
    (w.sr : F), (w.valid_at : F), out]

/-- Contract words, read as field elements. The relations below use this and not "word = value", so they stay true
for a verifier that reduces words mod `p`. Nothing here needs a verifier that refuses a word `>= p`. -/
def asField (v : List Nat) : List F := v.map fun n => (n : F)

/-- `v` are the public words of an accepted `phone` run on witness `w`, with output `out`. `types` is here because Noir enforces input types. -/
structure PhoneRelation (C : Signed.Crypto) (perm : Perm) (v : List Nat) (w : Witness) (out : F) : Prop where
  types : PhoneTypes w
  circuit : phone_circuit C perm w out
  pub : asField v = phonePublicInputs w out

/-- All the values of one `pair` run. -/
structure PairWitness where
  nonce_hi : F
  nonce_lo : F
  attempt : Nat
  commit_a : F
  commit_b : F
  sr_a : Nat
  sr_b : Nat
  half_a : F
  salt_a : F
  half_b : F
  salt_b : F
  xa0 : F
  xa1 : F
  xb0 : F
  xb1 : F

/-- `v` are the public words of an accepted v1.1 `pair` run: the frozen constraints (`pairCircuit`), with `xa`, `xb` public at positions 7..10.
`pair_named` is compiled and its ABI order is in `circuit/RESULTS.md`, but this is still a hand copy of it. No check links the two. -/
structure PairRelation (perm : Perm) (v : List Nat) (q : PairWitness) : Prop where
  attempt_ok : isU8 q.attempt
  sr_a_ok : isU32 q.sr_a
  sr_b_ok : isU32 q.sr_b
  circuit : pairCircuit (hash_n perm) q.nonce_hi q.nonce_lo q.attempt q.commit_a q.commit_b q.sr_a q.sr_b
    q.half_a q.salt_a q.half_b q.salt_b q.xa0 q.xa1 q.xb0 q.xb1
  pub : asField v = pairPublicInputs q.nonce_hi q.nonce_lo q.attempt q.commit_a q.commit_b q.sr_a q.sr_b q.xa0 q.xa1 q.xb0 q.xb1

/-- **Named hypothesis: the phone verifier is sound.** A yes on `v` means a witness exists with those public values. Not proved here. -/
def PhoneVerifierSound (C : Signed.Crypto) (perm : Perm) (env : Env) : Prop :=
  ∀ proof v, env.phoneVerify proof v → ∃ w out, PhoneRelation C perm v w out

/-- **Named hypothesis: the pair verifier is sound.** Same, for `pair`. Not proved here. -/
def PairVerifierSound (perm : Perm) (env : Env) : Prop :=
  ∀ proof v, env.pairVerify proof v → ∃ q, PairRelation perm v q

/-- What the Solidity types give and the `Nat` model drops. `deadline_ok` follows from the `be64` deadline in `EvpRecoveryAccount.sol` lines 208 and 229.
It is what makes `valid_at` a true number: a word `>= p` can't pass the window. -/
structure Widths (i : Input) : Prop where
  deviceA : i.deviceA < 2 ^ 256
  deviceB : i.deviceB < 2 ^ 256
  qx : i.qx < 2 ^ 256
  qy : i.qy < 2 ^ 256
  deadline_ok : i.deadline + 300 < p

/-- What `presence_sound` needs on these witnesses, unchanged. -/
structure Trust (C : Signed.Crypto) (Msgs : Signed.SignedSet) (perm : Perm) (wA wB : Witness) (rcdA rcdB : Nat → Nat) (q : PairWitness) : Prop where
  AA : Assumptions C Msgs perm wA rcdA
  AB : Assumptions C Msgs perm wB rcdB
  spotA : ¬ Freivalds.Fooled (wit wA) (challenges perm wA).1 (challenges perm wA).2
  spotB : ¬ Freivalds.Fooled (wit wB) (challenges perm wB).1 (challenges perm wB).2
  bindA : HalfBinds perm (opening wA).toList (pairListA q.nonce_hi q.nonce_lo q.attempt q.sr_a q.half_a q.salt_a q.xa0 q.xa1 q.xb0 q.xb1)
  bindB : HalfBinds perm (opening wB).toList (pairListB q.nonce_hi q.nonce_lo q.attempt q.sr_b q.half_b q.salt_b q.xa0 q.xa1 q.xb0 q.xb1)

/-! ## What comes out -/

/-- What `evp_presence_sound` concludes. -/
structure EvpConclusion (C : Signed.Crypto) (Msgs : Signed.SignedSet) (perm : Perm) (env : Env) (i : Input) (wA wB : Witness) (outA outB : F)
    (rcdA rcdB : Nat → Nat) (q : PairWitness) : Prop where
  /-- All of `presence_sound`. -/
  presence : PresenceConclusion C Msgs perm wA wB q.commit_a q.commit_b rcdA rcdB q.nonce_hi q.nonce_lo q.attempt q.sr_a q.sr_b
    q.half_a q.salt_a q.half_b q.salt_b q.xa0 q.xa1 q.xb0 q.xb1
  /-- The commitments `pair` opens are the phones' outputs. -/
  commit_A : outA = q.commit_a
  commit_B : outB = q.commit_b
  /-- The X each phone signed as its own is the device key the caller named. -/
  device_A : beNat wA.t 40 32 = i.deviceA
  device_B : beNat wB.t 40 32 = i.deviceB
  /-- Both witnesses carry the two limbs of `popNonce`. -/
  nonce_A : wA.nonce_hi = ((i.popNonce / 2 ^ 128 : Nat) : F) ∧ wA.nonce_lo = ((i.popNonce % 2 ^ 128 : Nat) : F)
  nonce_B : wB.nonce_hi = ((i.popNonce / 2 ^ 128 : Nat) : F) ∧ wB.nonce_lo = ((i.popNonce % 2 ^ 128 : Nat) : F)
  /-- One attempt, as a true number. -/
  attempt_A : wA.attempt = W i.p 2
  attempt_B : wB.attempt = W i.p 2
  /-- The issuer key whose signature `phone_A.issuer_signed` names is the pinned `(qx, qy)`, as bytes. -/
  issuer_A : beNat (Signed.unpackXY wA.a wA.b) 0 32 = i.qx ∧ beNat (Signed.unpackXY wA.c wA.d) 0 32 = i.qy
  issuer_B : beNat (Signed.unpackXY wB.a wB.b) 0 32 = i.qx ∧ beNat (Signed.unpackXY wB.c wB.d) 0 32 = i.qy
  /-- `_ccOk` passed under the pinned `(qx, qy)`, on the word that is the witness's `code_commit`. -/
  cc_A : ccOk env i.qx i.qy i.popNonce i.a Role.A ∧ wA.code_commit = ((W i.a 4 : Nat) : F)
  cc_B : ccOk env i.qx i.qy i.popNonce i.bb Role.B ∧ wB.code_commit = ((W i.bb 4 : Nat) : F)
  /-- One `valid_at` in both witnesses, inside the window. -/
  valid_B : wB.valid_at = wA.valid_at
  valid_lo : i.notBefore ≤ wA.valid_at
  valid_hi : wA.valid_at ≤ i.deadline + 300
  deadline_le : i.deadline ≤ wA.valid_at + i.maxAge

/-! ## Helpers -/

/-- Word `j` of `v`, as a field element, is entry `j` of the public values. -/
theorem pub_at {v : List Nat} {l : List F} (h : asField v = l) {j : Nat} {x : F} (hl : l[j]? = some x) :
    ((W v j : Nat) : F) = x := by
  subst h
  induction v generalizing j with
  | nil => simp [asField] at hl
  | cons n v ih =>
    cases j with
    | zero => simpa [asField, W] using hl
    | succ j => simpa [W] using ih (by simpa [asField] using hl)

/-- The words of a `phone` run that the glue reads. -/
theorem phone_words {C : Signed.Crypto} {perm : Perm} {v : List Nat} {w : Witness} {out : F} (r : PhoneRelation C perm v w out) :
    ((W v 0 : Nat) : F) = w.nonce_hi ∧ ((W v 1 : Nat) : F) = w.nonce_lo ∧ ((W v 2 : Nat) : F) = (w.attempt : F) ∧
    ((W v 4 : Nat) : F) = w.code_commit ∧ ((W v 5 : Nat) : F) = w.issuer 0 ∧ ((W v 6 : Nat) : F) = w.issuer 1 ∧
    ((W v 7 : Nat) : F) = w.issuer 2 ∧ ((W v 8 : Nat) : F) = w.issuer 3 ∧ ((W v 10 : Nat) : F) = (w.valid_at : F) ∧
    ((W v 11 : Nat) : F) = out :=
  ⟨pub_at r.pub rfl, pub_at r.pub rfl, pub_at r.pub rfl, pub_at r.pub rfl, pub_at r.pub rfl, pub_at r.pub rfl,
    pub_at r.pub rfl, pub_at r.pub rfl, pub_at r.pub rfl, pub_at r.pub rfl⟩

/-- Limbs equal to the split of `x` put `x` back together as true numbers. -/
theorem limbs_val {x : Nat} (hx : x < 2 ^ 256) {h l : F} (eh : h = ((x / 2 ^ 128 : Nat) : F)) (el : l = ((x % 2 ^ 128 : Nat) : F)) :
    h.val * 2 ^ 128 + l.val = x := by
  have hiLt : x / 2 ^ 128 < 2 ^ 128 := Nat.div_lt_of_lt_mul (by simpa using hx)
  have loLt : x % 2 ^ 128 < 2 ^ 128 := Nat.mod_lt _ (by norm_num)
  subst eh el
  rw [val_natCast_of_lt (limb_lt_p hiLt), val_natCast_of_lt (limb_lt_p loLt), Nat.div_add_mod']

/-! ## The theorem -/

/-- `evp_presence_sound`, for witnesses already in hand. -/
theorem evp_presence_sound_at {C : Signed.Crypto} {Msgs : Signed.SignedSet} {perm : Perm} {env : Env} {i : Input}
    {wA wB : Witness} {outA outB : F} {rcdA rcdB : Nat → Nat} {q : PairWitness}
    (hacc : AdapterAccepts env i) (Wd : Widths i)
    (rA : PhoneRelation C perm i.a wA outA) (rB : PhoneRelation C perm i.bb wB outB) (rP : PairRelation perm i.p q)
    (T : Trust C Msgs perm wA wB rcdA rcdB q) :
    EvpConclusion C Msgs perm env i wA wB outA outB rcdA rcdB q := by
  have P := adapter_pins env i hacc
  obtain ⟨a0, a1, a2, a4, a5, a6, a7, a8, a10, a11⟩ := phone_words rA
  obtain ⟨b0, b1, b2, b4, b5, b6, b7, b8, b10, b11⟩ := phone_words rB
  have p3 : ((W i.p 3 : Nat) : F) = q.commit_a := pub_at rP.pub rfl
  have p4 : ((W i.p 4 : Nat) : F) = q.commit_b := pub_at rP.pub rfl
  have p7 : ((W i.p 7 : Nat) : F) = q.xa0 := pub_at rP.pub rfl
  have p8 : ((W i.p 8 : Nat) : F) = q.xa1 := pub_at rP.pub rfl
  have p9 : ((W i.p 9 : Nat) : F) = q.xb0 := pub_at rP.pub rfl
  have p10 : ((W i.p 10 : Nat) : F) = q.xb1 := pub_at rP.pub rfl
  -- line 85: what `presence_sound` leaves to the verifier
  have cA : outA = q.commit_a := by rw [← a11, ← p3, P.commit_a]
  have cB : outB = q.commit_b := by rw [← b11, ← p4, P.commit_b]
  have hA := rA.circuit
  have hB := rB.circuit
  rw [cA] at hA
  rw [cB] at hB
  have pres := presence_sound rA.types rB.types rP.attempt_ok rP.sr_a_ok rP.sr_b_ok T.AA T.AB hA hB T.spotA T.spotB rP.circuit T.bindA T.bindB
  -- the attempt word fits a byte, so it is the witness's number
  have u8 : isU8 (W i.p 2) := by
    have := P.attempt_le
    change W i.p 2 < 2 ^ 8
    omega
  rw [P.attempt_a] at a2
  rw [P.attempt_bb] at b2
  -- the window bounds the `valid_at` word below `p`, so it is the witness's number
  have vlt : W i.a 10 < p := lt_of_le_of_lt P.valid_hi Wd.deadline_ok
  have vA : W i.a 10 = wA.valid_at := Commit.natCast_inj_of_lt vlt (isU64_lt_p rA.types.valid_at_ok) a10
  rw [P.valid_eq] at b10
  have vB : W i.a 10 = wB.valid_at := Commit.natCast_inj_of_lt vlt (isU64_lt_p rB.types.valid_at_ok) b10
  have PA := pres.phone_A.bytes.issuer
  have PB := pres.phone_B.bytes.issuer
  exact
    { presence := pres
      commit_A := cA
      commit_B := cB
      device_A := limbs_pin_key wA.t _ rA.types.t_ok Wd.deviceA
        (by rw [← pres.own_A.1, ← p7, P.xa_limbs.1]) (by rw [← pres.own_A.2, ← p8, P.xa_limbs.2])
      device_B := limbs_pin_key wB.t _ rB.types.t_ok Wd.deviceB
        (by rw [← pres.own_B.1, ← p9, P.xb_limbs.1]) (by rw [← pres.own_B.2, ← p10, P.xb_limbs.2])
      nonce_A := ⟨by rw [← a0, P.nonce_a.1], by rw [← a1, P.nonce_a.2]⟩
      nonce_B := ⟨by rw [← b0, P.nonce_bb.1], by rw [← b1, P.nonce_bb.2]⟩
      attempt_A := (Commit.natCast_inj_of_lt (isU8_lt_p u8) (isU8_lt_p rA.types.attempt_ok) a2).symm
      attempt_B := (Commit.natCast_inj_of_lt (isU8_lt_p u8) (isU8_lt_p rB.types.attempt_ok) b2).symm
      issuer_A :=
        ⟨PA.1.trans (limbs_val (h := wA.issuer 0) (l := wA.issuer 1) Wd.qx (by rw [← a5, P.issuer_a.1]) (by rw [← a6, P.issuer_a.2.1])),
          PA.2.trans (limbs_val (h := wA.issuer 2) (l := wA.issuer 3) Wd.qy (by rw [← a7, P.issuer_a.2.2.1]) (by rw [← a8, P.issuer_a.2.2.2]))⟩
      issuer_B :=
        ⟨PB.1.trans (limbs_val (h := wB.issuer 0) (l := wB.issuer 1) Wd.qx (by rw [← b5, P.issuer_bb.1]) (by rw [← b6, P.issuer_bb.2.1])),
          PB.2.trans (limbs_val (h := wB.issuer 2) (l := wB.issuer 3) Wd.qy (by rw [← b7, P.issuer_bb.2.2.1]) (by rw [← b8, P.issuer_bb.2.2.2]))⟩
      cc_A := ⟨⟨by rw [P.attempt_a]; exact P.attempt_le, by rw [P.attempt_a]; exact P.cc_a⟩, a4.symm⟩
      cc_B := ⟨⟨by rw [P.attempt_bb]; exact P.attempt_le, by rw [P.attempt_bb]; exact P.cc_bb⟩, b4.symm⟩
      valid_B := vB.symm.trans vA
      valid_lo := vA ▸ P.valid_lo
      valid_hi := vA ▸ P.valid_hi
      deadline_le := vA ▸ P.deadline_le }

/-- **What an accepted `verifyPresence` means.** Suppose the contract's checks all pass (`AdapterAccepts`), both proof verifiers are sound, and the inputs have their Solidity widths.
Then three witnesses exist whose public values are the contract's words read as field elements. For those witnesses, under the same assumptions `presence_sound` takes (`Trust`):

1. all of `PresenceConclusion`;
2. the X each phone signed as its own is `deviceA`, `deviceB`, the keys the caller named. The account passes `laptopDeviceX` and the new phone's `qx` there, which is not modeled;
3. both witnesses carry the limbs of `popNonce`;
4. both witnesses' issuer key is the pinned `(qx, qy)`;
5. `_ccOk` holds under the pinned `(qx, qy)` on both witnesses' `code_commit`;
6. `valid_at` is one number in both, inside the window.

What `presence_sound` leaves to "the verifier" is proved here from the adapter: that `commit_a`, `commit_b` are the phones' outputs, and the issuer pin. Items 3, 5, 6 and the commitments do not use `Trust` in their proof. Item 2 does, through `HalfBinds`. Item 4 reads its bytes from `phone_sound` here.
Contract lines 82 (role) and 84 (rate) carry no weight here: `role_A`, `role_B` and the rates come through `HalfBinds` in `Trust`, and the proof never reads words 3 and 9.

**What this does NOT say.** Every limit of `presence_sound` stays. Silence and a clean tone still pass, so this does not say a beep was heard. Flight is arithmetic on signed numbers, and it says nothing about where the phones were.
Keys are X only: no Y is compared, so "device" here means the X coordinate.

Not modeled: the account layer. Nothing here looks at `ctx`, what `popNonce` is the hash of, or the `newKey` keccak. `popNonce` is just a number that all three proofs share. There is no clock either: the window in 6 is relative to `deadline`, and only frame 0's expiry check ties `deadline` to real time.
Also `Env.ccSig` takes `(qx, qy)` as an argument, but P-256 itself stays abstract: nothing here says `ccSig` is the real signature check. So 5 says "the `Env`'s check passed on that key", no more.

Assumed and not proved: the two verifier hypotheses; that `AdapterAccepts` is the Solidity (a hand reading); that `PairRelation` matches the compiled `pair_named` (a hand copy, no check links them); and everything in `Trust`, `Widths`.
The relations compare words as field elements, so this needs no claim that the verifier refuses a word `>= p`. Bounds come from the contract's own checks and `Widths`. `Assumptions` is stated on the witnesses the verifiers give, which is why they come first in the statement. -/
theorem evp_presence_sound {C : Signed.Crypto} {Msgs : Signed.SignedSet} {perm : Perm} {env : Env} {i : Input}
    (hacc : AdapterAccepts env i) (Wd : Widths i)
    (hPhone : PhoneVerifierSound C perm env) (hPair : PairVerifierSound perm env) :
    ∃ (wA wB : Witness) (outA outB : F) (q : PairWitness),
      PhoneRelation C perm i.a wA outA ∧ PhoneRelation C perm i.bb wB outB ∧ PairRelation perm i.p q ∧
      ∀ rcdA rcdB : Nat → Nat, Trust C Msgs perm wA wB rcdA rcdB q →
        EvpConclusion C Msgs perm env i wA wB outA outB rcdA rcdB q := by
  have P := adapter_pins env i hacc
  obtain ⟨wA, outA, rA⟩ := hPhone _ _ P.proof_a
  obtain ⟨wB, outB, rB⟩ := hPhone _ _ P.proof_bb
  obtain ⟨q, rP⟩ := hPair _ _ P.proof_p
  exact ⟨wA, wB, outA, outB, q, rA, rB, rP, fun _ _ T => evp_presence_sound_at hacc Wd rA rB rP T⟩

end Evpfv

#print axioms Evpfv.evp_presence_sound_at
#print axioms Evpfv.evp_presence_sound
