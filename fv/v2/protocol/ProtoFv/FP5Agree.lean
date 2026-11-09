import ProtoFv.Steps
import ProtoFv.Record

/-!
# FP5, agreement

Spec section 6, FP5. Two pieces, neither a two-device run.

(a) `outcome` is a function of the record's content, not of its order: two slot-distinct records
that are permutations of each other give the same outcome (`fp5_perm`). With no `FAIL`, it reads
only the pair `(t_A, t_B)`, A first (`fp5_pair`).

(b) One honest device, in every reachable state (`fp5_device`): it signs at most one message per
slot, so one `TXO` per attempt; it accepts at most one per slot; each accepted partner `TXO`
opens the one partner `TXC` it accepted; and it never holds both its own `TXO` and its own retry
`FAIL` for one attempt.

On paper, from (a), (b) and HASH: if both devices are honest, each holds the other's only `TXO`,
so both hold the same pair and get the same outcome. Not proved here as a two-device theorem.
Does not give: that the honest device learns the outcome when D walks away (FN1).
-/

namespace ProtoFv

set_option linter.unusedSectionVars false

variable {D : Type} [DecidableEq D]

/-! ## (a) The outcome is a function of the record -/

theorem slot_unique {l : List (Signed D)} (hd : SlotsDistinct l) {a b : Signed D}
    (ha : a ∈ l) (hb : b ∈ l) (he : a.slot = b.slot) : a = b := by
  induction l with
  | nil => cases ha
  | cons y l ih =>
    rw [SlotsDistinct, List.pairwise_cons] at hd
    simp at ha hb
    rcases ha with rfl | ha <;> rcases hb with rfl | hb
    · rfl
    · exact absurd he (hd.1 _ hb)
    · exact absurd he.symm (hd.1 _ ha)
    · exact ih hd.2 ha hb

theorem get?_perm {l1 l2 : List (Signed D)} (hp : l1.Perm l2) (hd : SlotsDistinct l1) (x) :
    get? l1 x = get? l2 x := by
  unfold get?
  cases h1 : List.find? (fun s => s.slot == x) l1 with
  | none =>
    have : List.find? (fun s => s.slot == x) l2 = none :=
      List.find?_eq_none.2 (fun y hy => List.find?_eq_none.1 h1 y (hp.mem_iff.2 hy))
    rw [this]
  | some a =>
    cases h2 : List.find? (fun s => s.slot == x) l2 with
    | none =>
      exact absurd (List.find?_some h1)
        (List.find?_eq_none.1 h2 a (hp.mem_iff.1 (List.mem_of_find?_eq_some h1)))
    | some b =>
      have pa := List.find?_some h1
      have pb := List.find?_some h2
      simp at pa pb
      have := slot_unique hd (List.mem_of_find?_eq_some h1)
        (hp.mem_iff.2 (List.mem_of_find?_eq_some h2)) (pa.trans pb.symm)
      rw [this]

/-- **FP5 (a).** Order doesn't matter. -/
theorem fp5_perm {l1 l2 : List (Signed D)} (hp : l1.Perm l2) (hd : SlotsDistinct l1) :
    outcome l1 = outcome l2 := by
  unfold outcome outcomeAt lastK failOf txOf
  simp only [get?_perm hp hd, hp.any_eq]

/-- **FP5 (a).** With no `FAIL` for `k`, the outcome is `combine (t_A, t_B)`, A first. -/
theorem fp5_pair {l : List (Signed D)} {k : Nat} {ta tb : Tx D}
    (fA : failOf l .A k = none) (fB : failOf l .B k = none)
    (hA : txOf l .A k = some ta) (hB : txOf l .B k = some tb) :
    outcomeAt l k = .pair (combine ta tb) := by
  simp [outcomeAt, fA, fB, hA, hB]

/-! ## (b) One honest device -/

def Inv5 (C : Crypto D) (c : Cfg) (st : St D) : Prop :=
  SlotsDistinct st.sent ∧ SlotsDistinct st.got ∧
  (∀ x ∈ st.got, ∀ blind t sigt, x.msg.body = .txo blind t sigt →
    cOf st.got c.p x.msg.attempt = some (C.H (.tx blind t sigt))) ∧
  (∀ f ∈ st.sent, ∀ w, f.msg.body = .fail true w → has st.sent (c.me, f.msg.attempt, .txo) = false)

theorem cOf_step {C : Crypto D} {c : Cfg} {st : St D} (i : Input D) {r k v}
    (h : cOf st.got r k = some v) : cOf (step C c st i).got r k = some v :=
  lookup_step_got (fun o => match o with | some (.txc c) => some c | _ => none) rfl C c st i h

theorem inv5 {C : Crypto D} {c : Cfg} {st : St D} (h : Reach C c st) : Inv5 C c st := by
  induction h with
  | init => simp [Inv5, St.init, SlotsDistinct]
  | @step st i hr ih =>
    have R := Reach.roles hr
    obtain ⟨d1, d2, h3, h4⟩ := ih
    -- the `got` parts
    have G : SlotsDistinct (step C c st i).got ∧
        (∀ x ∈ (step C c st i).got, ∀ blind t sigt, x.msg.body = .txo blind t sigt →
          cOf (step C c st i).got c.p x.msg.attempt = some (C.H (.tx blind t sigt))) := by
      rcases step_got C c st i with he | ⟨y, he, hy⟩
      · rw [he]; exact ⟨d2, fun x hx b t s hb => by rw [← he]; exact cOf_step i (h3 x hx b t s hb)⟩
      · obtain ⟨henv, hbody⟩ := hy
        have E := envOk_eq.1 henv
        refine ⟨?_, fun x hx b t s hb => ?_⟩
        · rw [he, SlotsDistinct, List.pairwise_append]
          refine ⟨d2, by simp, fun a ha z hz => ?_⟩
          simp at hz; subst hz
          intro e
          have : has st.got z.slot = true := has_iff.2 ⟨a, ha, e⟩
          rw [E.fresh] at this; cases this
        · have hx' := hx
          rw [he] at hx'; simp at hx'
          rcases hx' with hx' | rfl
          · exact cOf_step i (h3 x hx' b t s hb)
          · rw [hb] at hbody
            simp only [bodyOk, hb] at hbody
            have o := txOk_opens hbody
            rw [E.role] at o
            have e := get?_partner R x.msg.attempt .txc
            have : cOf st.got c.p x.msg.attempt = some (C.H (.tx b t s)) := by
              unfold cOf at o ⊢; rw [e] at o; exact o
            exact cOf_step i this
    refine ⟨?_, G.1, G.2, ?_⟩
    · rcases step_sent C c st i with he | ⟨y, he, hy⟩
      · rw [he]; exact d1
      · rw [he, SlotsDistinct, List.pairwise_append]
        obtain ⟨hrole, hk, -, -, -, hm, -⟩ := hy
        refine ⟨d1, by simp, fun a ha z hz => ?_⟩
        simp at hz; subst hz
        intro e
        have : mine c st z.msg.body.tag = true :=
          has_iff.2 ⟨a, ha, by rw [e]; simp [Signed.slot, hrole, hk]⟩
        rw [hm] at this; cases this
    · rcases step_sent C c st i with he | ⟨y, he, hy⟩
      · rw [he]; exact h4
      · obtain ⟨hrole, hk, -, -, hfail, hm, hb⟩ := hy
        rw [he]
        intro f hf w hfb
        simp at hf
        rw [has_append_one]
        rcases hf with hf | rfl
        · have old := h4 f hf w hfb
          rw [old]; simp
          intro e
          -- the new message sits in the `TXO` slot of `f`'s attempt
          simp [Signed.slot] at e
          obtain ⟨-, ha, ht⟩ := e
          have : mine c st .fail = true := has_iff.2 ⟨f, hf, by
            simp [Signed.slot, (R.1 f hf).1, ← ha, hk, hfb, Body.tag]⟩
          rw [hfail] at this; cases this
        · rw [hfb] at hb
          simp at hb
          have hm' : has st.sent (c.me, st.k, .txo) = false := hb
          rw [hk, hm']; simp [Signed.slot, hfb, Body.tag]

/-- **FP5 (b).** What one honest device keeps, in every reachable state. -/
theorem fp5_device {C : Crypto D} {c : Cfg} {st : St D} (h : Reach C c st) :
    -- at most one own message per slot, so one `TXO` per attempt
    SlotsDistinct st.sent ∧
    -- at most one partner message per slot
    SlotsDistinct st.got ∧
    -- an accepted partner `TXO` opens the one accepted partner `TXC`
    (∀ x ∈ st.got, ∀ blind t sigt, x.msg.body = .txo blind t sigt →
      cOf st.got c.p x.msg.attempt = some (C.H (.tx blind t sigt))) ∧
    -- no retry `FAIL` next to its own `TXO` for one attempt
    (∀ f ∈ st.sent, ∀ w, f.msg.body = .fail true w →
      has st.sent (c.me, f.msg.attempt, .txo) = false) :=
  inv5 h

end ProtoFv
