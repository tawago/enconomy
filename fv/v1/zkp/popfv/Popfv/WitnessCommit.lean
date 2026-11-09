import Popfv.Commit

/-! Non-vacuity witness for `Popfv.Commit`: every hypothesis of the main theorems, at one concrete world. -/

set_option linter.style.whitespace false
set_option linter.style.longLine false
set_option linter.style.header false

namespace Popfv
namespace Commit
namespace RecheckHB

open PartnerGlue (bytesOK osF opF pSelf aPartner)

/-- `a_self = 2100`, `half = sod = 0`, so the self opening starts at leaf 1 and the partner opening at leaf 2. Each window spans more than
one leaf: the self window starts at offset 949 in the opened array and runs 12254 samples, to index 13202 of 13312, so 13 leaves of 1024. -/
def tNV (i : Nat) : Nat := if i = 271 then 8 else if i = 272 then 52 else 0

/-- A non-constant recording of `u16` samples. -/
def rcdNV (n : Nat) : Nat := n % 65536

/-- Two templates that differ as functions, only past byte 12000, which the circuit never reads. -/
def tmplA (i : Nat) : Nat := i % 256
def tmplB (i : Nat) : Nat := if i < L then i % 256 else 0

theorem rcdNV_lt (n : Nat) : rcdNV n < 2 ^ 16 := by
  have := Nat.mod_lt n (show 65536 > 0 by norm_num)
  unfold rcdNV
  omega

theorem rcdNV_lt' (n : Nat) : rcdNV n < 65536 := Nat.mod_lt n (by norm_num)

theorem tNV_ok : bytesOK tNV := by
  intro i _; unfold tNV; split_ifs <;> norm_num

theorem tmplA_lt (i : Nat) (_ : i < L) : tmplA i < 256 := Nat.mod_lt i (by norm_num)

theorem tmplB_lt (i : Nat) (hi : i < L) : tmplB i < 256 := by
  unfold tmplB; rw [if_pos hi]; exact Nat.mod_lt i (by norm_num)

theorem hPS : pSelf tNV = 2100 := by
  have hA : PartnerGlue.aSelf tNV = 2100 := by decide
  have hS : PartnerGlue.sod tNV = 0 := by decide
  simp [pSelf, hA, hS]

theorem hAP : aPartner tNV false = 2100 := by
  have hA : PartnerGlue.aSelf tNV = 2100 := by decide
  have hH : PartnerGlue.half tNV = 0 := by decide
  simp [aPartner, PartnerGlue.sg, hA, hH]

theorem fos : fits 10 (osF tNV ((1 : Nat) : F)) := by
  have e : osF tNV ((1 : Nat) : F) = ((949 : Nat) : F) := by
    rw [PartnerGlue.osF_cast tNV 1 tNV_ok, hPS]; norm_num
  rw [e]; exact fits_natCast (by norm_num) (by norm_num)

theorem fop : fits 10 (opF tNV false ((2 : Nat) : F)) := by
  have e : opF tNV false ((2 : Nat) : F) = ((21 : Nat) : F) := by
    rw [PartnerGlue.opF_cast tNV false 2 tNV_ok, hAP]; norm_num
  rw [e]; exact fits_natCast (by norm_num) (by norm_num)

/-- The self opening (leaves 1..13) and the partner opening (leaves 2..14) share 12 leaves, read at different
offsets of two different arrays. `OpeningsBind` holds on all of them, for every permutation. -/
theorem openings_bind (perm : Perm) :
    OpeningsBind perm (honestXs rcdNV 1) ((1 : Nat) : F) (honestCh perm rcdNV 1)
      (honestXs rcdNV 2) ((2 : Nat) : F) (honestCh perm rcdNV 2) := by
  intro i hi i' hi' h
  rw [← Nat.cast_add, ← Nat.cast_add] at h
  have e : 1 + i = 2 + i' := natCast_inj_of_lt
    (natCast_lt_p_of_lt_two_pow (k := 8) (by norm_num) (by omega))
    (natCast_lt_p_of_lt_two_pow (k := 8) (by norm_num) (by omega)) h
  refine ⟨fun l _ _ => ?_, fun _ => ?_⟩
  · show children perm rcdNV l ((1 + i) / 4 ^ (l + 1)) = children perm rcdNV l ((2 + i') / 4 ^ (l + 1))
    rw [e]
  · rw [honest_leaf_elems, honest_leaf_elems, e]

theorem tmpl_eq (i : Nat) (hi : i < L) : tmplA i = tmplB i := by
  unfold tmplA tmplB; rw [if_pos hi]

theorem chunks_tmpl : chunks tmplA = chunks tmplB :=
  (packing_injective tmplA tmplB tmplA_lt tmplB_lt).2 tmpl_eq

/-- **All the hypotheses of the main theorems hold at once**, in one world: one permutation, one recording, one
transcript, one set of openings and templates. -/
theorem hypotheses_hold_together (perm : Perm) :
    bytesOK tNV ∧
    (∀ j, j < 13312 → honestXs rcdNV 1 j < 2 ^ 16) ∧ (∀ j, j < 13312 → honestXs rcdNV 2 j < 2 ^ 16) ∧
    (∀ n, rcdNV n < 2 ^ 16) ∧
    fits 10 (osF tNV ((1 : Nat) : F)) ∧ fits 10 (opF tNV false ((2 : Nat) : F)) ∧
    open_leaves perm (honestXs rcdNV 1) ((1 : Nat) : F) (honestCh perm rcdNV 1) (recRoot perm rcdNV) ∧
    open_leaves perm (honestXs rcdNV 2) ((2 : Nat) : F) (honestCh perm rcdNV 2) (recRoot perm rcdNV) ∧
    BindsToRecording perm rcdNV (honestXs rcdNV 1) ((1 : Nat) : F) (honestCh perm rcdNV 1) ∧
    BindsToRecording perm rcdNV (honestXs rcdNV 2) ((2 : Nat) : F) (honestCh perm rcdNV 2) ∧
    OpeningsBind perm (honestXs rcdNV 1) ((1 : Nat) : F) (honestCh perm rcdNV 1)
      (honestXs rcdNV 2) ((2 : Nat) : F) (honestCh perm rcdNV 2) ∧
    CodeBinds perm (chunks tmplA ++ chunks tmplA ++ chunks tmplA ++ chunks tmplA)
      (chunks tmplB ++ chunks tmplB ++ chunks tmplB ++ chunks tmplB) ∧
    code_commitment perm tmplA tmplA tmplA tmplA = code_commitment perm tmplB tmplB tmplB tmplB :=
  ⟨tNV_ok, fun _ _ => rcdNV_lt _, fun _ _ => rcdNV_lt _, rcdNV_lt, fos, fop,
    open_leaves_complete perm rcdNV 1 (by norm_num), open_leaves_complete perm rcdNV 2 (by norm_num),
    honest_binds perm rcdNV 1 (by norm_num), honest_binds perm rcdNV 2 (by norm_num),
    openings_bind perm,
    fun _ => by rw [chunks_tmpl],
    code_commitment_congr perm _ _ _ _ _ _ _ _ tmpl_eq tmpl_eq tmpl_eq tmpl_eq⟩

/-- The same, at a concrete permutation (the identity), so the world exists with nothing left quantified. -/
def hypotheses_hold_concrete := hypotheses_hold_together (fun s => s)

/-! Each main theorem, actually fired on that world. -/

def fire_windows (perm : Perm) :=
  phone_core_windows_are_recording perm tNV false ((1 : Nat) : F) ((2 : Nat) : F) (honestXs rcdNV 1) (honestXs rcdNV 2) rcdNV
    (honestCh perm rcdNV 1) (honestCh perm rcdNV 2) tNV_ok
    (fun _ _ => rcdNV_lt _) (fun _ _ => rcdNV_lt _) rcdNV_lt fos fop
    (open_leaves_complete perm rcdNV 1 (by norm_num)) (open_leaves_complete perm rcdNV 2 (by norm_num))
    (honest_binds perm rcdNV 1 (by norm_num)) (honest_binds perm rcdNV 2 (by norm_num))

def fire_one_recording (perm : Perm) :=
  phone_core_one_recording perm tNV false ((1 : Nat) : F) ((2 : Nat) : F) (recRoot perm rcdNV) (honestXs rcdNV 1) (honestXs rcdNV 2)
    (honestCh perm rcdNV 1) (honestCh perm rcdNV 2) tNV_ok
    (fun _ _ => rcdNV_lt _) (fun _ _ => rcdNV_lt _) fos fop
    (open_leaves_complete perm rcdNV 1 (by norm_num)) (open_leaves_complete perm rcdNV 2 (by norm_num))
    (openings_bind perm)

def fire_code_binds (perm : Perm) :=
  code_commitment_binds perm tmplA tmplA tmplA tmplA tmplB tmplB tmplB tmplB
    tmplA_lt tmplA_lt tmplA_lt tmplA_lt tmplB_lt tmplB_lt tmplB_lt tmplB_lt
    (fun _ => by rw [chunks_tmpl])
    (code_commitment_congr perm _ _ _ _ _ _ _ _ tmpl_eq tmpl_eq tmpl_eq tmpl_eq)

/-- Leaf number 2 opened two ways: index 1 of the self array, index 0 of the partner array. -/
theorem fire_two_openings (perm : Perm) :
    ∀ k, k < 1024 → honestXs rcdNV 1 (1 * 1024 + k) = honestXs rcdNV 2 (0 * 1024 + k) := by
  have hidx : ((1 : Nat) : F) + ((1 : Nat) : F) = ((2 : Nat) : F) + ((0 : Nat) : F) := by norm_num
  obtain ⟨ok1, rt1⟩ := open_leaves_complete perm rcdNV 1 (by norm_num) 1 (by norm_num)
  obtain ⟨ok2, rt2⟩ := open_leaves_complete perm rcdNV 2 (by norm_num) 0 (by norm_num)
  rw [hidx] at ok1 rt1
  obtain ⟨hn, hl⟩ := openings_bind perm 1 (by norm_num) 0 (by norm_num) hidx
  exact two_openings_agree perm (honestXs rcdNV 1) (honestXs rcdNV 2) (1 * 1024) (0 * 1024) _ _ _
    (fun _ _ => rcdNV_lt' _) (fun _ _ => rcdNV_lt' _) ok1 ok2 (rt1.trans rt2.symm) hn hl

end RecheckHB
end Commit
end Popfv

#print axioms Popfv.Commit.RecheckHB.hypotheses_hold_together
#print axioms Popfv.Commit.RecheckHB.hypotheses_hold_concrete
#print axioms Popfv.Commit.RecheckHB.fire_windows
#print axioms Popfv.Commit.RecheckHB.fire_one_recording
#print axioms Popfv.Commit.RecheckHB.fire_code_binds
#print axioms Popfv.Commit.RecheckHB.fire_two_openings
