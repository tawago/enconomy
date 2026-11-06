import Popfv.Chain

set_option linter.style.whitespace false
set_option linter.style.longLine false
set_option linter.style.header false

namespace Popfv
namespace Chain
namespace WitnessChain

open Silence

/-- All hypotheses of `phone_sound` at once, with a template that has real energy. -/
theorem phone_hyps_hold : ∃ (C : Signed.Crypto) (Msgs : Signed.SignedSet) (perm : Commit.Perm) (w : Witness) (out : F) (rcd : Nat → Nat),
    PhoneTypes w ∧ Assumptions C Msgs perm w rcd ∧ phone_circuit C perm w out ∧
    ¬ Freivalds.Fooled (wit w) (challenges perm w).1 (challenges perm w).2 ∧
    0 < Arrival.cnaI w.c_is := by
  have hc : ∀ n, n < 12000 → (fun _ : Nat => 129) n < 256 := fun _ _ => by norm_num
  refine ⟨silC, silMsgs, permOne, silW false (fun _ => 129) (fun _ => 129) (fun _ => 129) (fun _ => 129), 1, Arrival.silent,
    silW_types _ _ _ _ _ hc hc hc hc, silW_assumptions _ _ _ _ _, silW_accepts _ _ _ _ _ hc hc hc hc, silW_spot_not_fooled _ _ _ _ _, ?_⟩
  show 0 < Arrival.cnaI (fun _ => 129)
  simp [Arrival.cnaI, Arrival.tfI, Arrival.L]

/-- The docstring claim on `phone_sound`: an all-128 `c_i` makes loudness 0, and the arrival test passes on ANY audio. -/
theorem all128_self (X c_q : Nat → Nat) (j : Nat) :
    Arrival.bigC X (fun _ => 128) j = 0 ∧ Arrival.bigC X (fun _ => 128) j ≤ Arrival.BAR * Arrival.env2 X (fun _ => 128) c_q j := by
  have h0 : Arrival.bigC X (fun _ => 128) j = 0 := by
    simp [Arrival.bigC, Arrival.cnaI, Arrival.tfI]
  refine ⟨h0, ?_⟩
  rw [h0]
  unfold Arrival.env2 Arrival.BAR
  positivity

theorem all128_first (X c_q : Nat → Nat) : FirstLoudEnough X (fun _ => 128) c_q 0 :=
  ⟨by norm_num, fun _ hj => absurd hj (Nat.not_lt_zero _), (all128_self X c_q 0).2⟩

theorem all128_partner (Y c_q : Nat → Nat) : PartnerLoudEnough Y (fun _ => 128) c_q := by
  unfold PartnerLoudEnough
  have h0 : PartnerGlue.CI (fun _ => 128) = 0 := by
    simp [PartnerGlue.CI, PartnerGlue.tfI]
  rw [h0, mul_zero]
  unfold PartnerGlue.BAR
  positivity

/-- `Commit.OpeningsBind`, the hypothesis of `phone_sound_no_tree`, is satisfiable on the silence witness. -/
theorem openings_bind_holds (b : Bool) (c1 c2 c3 c4 : Nat → Nat) :
    Commit.OpeningsBind permOne (silW b c1 c2 c3 c4).xs (silW b c1 c2 c3 c4).leaf_s (silW b c1 c2 c3 c4).chs
      (silW b c1 c2 c3 c4).xp (silW b c1 c2 c3 c4).leaf_p (silW b c1 c2 c3 c4).chp := by
  intro i hi i' hi' he
  have he' : (((23 + i : Nat)) : F) = ((lpOf b + i' : Nat) : F) := by
    push_cast
    exact he
  have hlp : lpOf b ≤ 33 := by cases b <;> simp [lpOf]
  have hn : 23 + i = lpOf b + i' :=
    Commit.natCast_inj_of_lt (natCast_lt_p_of_lt_two_pow (k := 16) (by norm_num) (by omega))
      (natCast_lt_p_of_lt_two_pow (k := 16) (by norm_num) (by omega)) he'
  refine ⟨fun l _ _ => ?_, fun _ => ?_⟩
  · show Commit.honestCh permOne Arrival.silent 23 i l = Commit.honestCh permOne Arrival.silent (lpOf b) i' l
    unfold Commit.honestCh
    rw [hn]
  · show Commit.leafElems (Commit.honestXs Arrival.silent 23) (i * 1024) = Commit.leafElems (Commit.honestXs Arrival.silent (lpOf b)) (i' * 1024)
    rw [Commit.honest_leaf_elems, Commit.honest_leaf_elems, hn]

/-- So `phone_sound_no_tree` is not vacuous. -/
theorem no_tree_nonvacuous (b : Bool) (c1 c2 c3 c4 : Nat → Nat)
    (h1 : ∀ n, n < 12000 → c1 n < 256) (h2 : ∀ n, n < 12000 → c2 n < 256)
    (h3 : ∀ n, n < 12000 → c3 n < 256) (h4 : ∀ n, n < 12000 → c4 n < 256) :
    ∃ rcd : Nat → Nat, (∀ n, rcd n < 2 ^ 16) ∧ PhoneConclusion silC silMsgs permOne (silW b c1 c2 c3 c4) 1 rcd :=
  phone_sound_no_tree (silW_types b c1 c2 c3 c4 h1 h2 h3 h4) (silW_assumptions b c1 c2 c3 c4).toSigAssumptions
    (silW_accepts b c1 c2 c3 c4 h1 h2 h3 h4) (silW_spot_not_fooled b c1 c2 c3 c4) (openings_bind_holds b c1 c2 c3 c4)

end WitnessChain
end Chain
end Popfv

#print axioms Popfv.Chain.WitnessChain.phone_hyps_hold
#print axioms Popfv.Chain.WitnessChain.all128_first
#print axioms Popfv.Chain.WitnessChain.all128_partner
#print axioms Popfv.Chain.WitnessChain.no_tree_nonvacuous
