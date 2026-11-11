import ProtoFv.Steps
import ProtoFv.Log

/-!
# FP5, agreement

Spec section 6, FP5. Two pieces, neither a two-device run.

(a) `outcome` is a function of the log's content, not of its order: two slot-distinct logs
that are permutations of each other give the same outcome (`fp5_perm`). With no `FAIL`, it reads
only the pair `(t_A, t_B)`, A first (`fp5_pair`).

(b) One honest device, in every reachable state (`fp5_device`): it signs at most one message per
slot, so one `GAP_VALUE` per attempt; it accepts at most one per slot; and each accepted partner
`GAP_VALUE` matches the one partner `GAP_HASH` it accepted. At the moment of signing
(`fp5_retry_fail`): a step that signs a retry `FAIL` runs in a state where the device has not
signed `GAP_VALUE` for the attempt, or holds both transcripts with a verdict that asks for a retry
(`pairRetry`, the v1 rule kept on 2026-11-11, spec F10).

A step that signs a final `FAIL` is the receipt of a message that failed its body check
(`fp5_final_fail`).

On paper, from (a), (b) and HASH: if both devices are honest, any `GAP_VALUE` one accepts is the
other's only one, so when both hold a pair it is the same pair. A retry `FAIL` after its own
`GAP_VALUE` is signed only on a verdict of that same pair that is not NEAR, so one honest device
never holds NEAR while the other holds NOT_NEAR. The outcomes can still differ: if the link closes
mid-exchange, one side can hold NEAR and the other be incomplete, or one hold `.pair .impossible`
and the other `.fail .B`. Not proved here as a two-device theorem.
Does not give: that the honest device learns the outcome when D walks away (FN1).
-/

namespace ProtoFv

set_option linter.unusedSectionVars false

variable {D : Type} [DecidableEq D]

/-! ## (a) The outcome is a function of the log -/

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
  (∀ x ∈ st.got, ∀ blind t sigt, x.msg.body = .gapVal blind t sigt →
    cOf st.got c.p x.msg.attempt = some (C.H (.tx blind t sigt)))

theorem cOf_step {C : Crypto D} {c : Cfg} {st : St D} (i : Input D) {r k v}
    (h : cOf st.got r k = some v) : cOf (step C c st i).got r k = some v :=
  lookup_step_got (fun o => match o with | some (.gapHash c) => some c | _ => none) rfl C c st i h

theorem inv5 {C : Crypto D} {c : Cfg} {st : St D} (h : Reach C c st) : Inv5 C c st := by
  induction h with
  | init => simp [Inv5, St.init, SlotsDistinct]
  | @step st i hr ih =>
    have R := Reach.roles hr
    obtain ⟨d1, d2, h3⟩ := ih
    -- the `got` parts
    have G : SlotsDistinct (step C c st i).got ∧
        (∀ x ∈ (step C c st i).got, ∀ blind t sigt, x.msg.body = .gapVal blind t sigt →
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
            have o := txOk_matches hbody
            rw [E.role] at o
            have e := get?_partner R x.msg.attempt .gapHash
            have : cOf st.got c.p x.msg.attempt = some (C.H (.tx b t s)) := by
              unfold cOf at o ⊢; rw [e] at o; exact o
            exact cOf_step i this
    refine ⟨?_, G.1, G.2⟩
    rcases step_sent C c st i with he | ⟨y, he, hy⟩
    · rw [he]; exact d1
    · rw [he, SlotsDistinct, List.pairwise_append]
      obtain ⟨hrole, hk, -, -, -, hm, -⟩ := hy
      refine ⟨d1, by simp, fun a ha z hz => ?_⟩
      simp at hz; subst hz
      intro e
      have : mine c st z.msg.body.tag = true :=
        has_iff.2 ⟨a, ha, by rw [e]; simp [Signed.slot, hrole, hk]⟩
      rw [hm] at this; cases this

/-- **FP5 (b).** What one honest device keeps, in every reachable state. -/
theorem fp5_device {C : Crypto D} {c : Cfg} {st : St D} (h : Reach C c st) :
    -- at most one own message per slot, so one `GAP_VALUE` per attempt
    SlotsDistinct st.sent ∧
    -- at most one partner message per slot
    SlotsDistinct st.got ∧
    -- an accepted partner `GAP_VALUE` matches the one accepted partner `GAP_HASH`
    (∀ x ∈ st.got, ∀ blind t sigt, x.msg.body = .gapVal blind t sigt →
      cOf st.got c.p x.msg.attempt = some (C.H (.tx blind t sigt))) :=
  inv5 h

/-- **FP5 (b)**, at the moment of signing: a step that signs a retry `FAIL` runs in a state where
the device has not signed `GAP_VALUE` for the current attempt, or holds both transcripts with a
verdict that asks for a retry (`pairRetry`). So after its own `GAP_VALUE` it signs a retry `FAIL`
only when the pair asks for one. Reasons are not modeled: once `pairRetry` holds, that `FAIL` may
name any reason the app gives, a timeout included. -/
theorem fp5_retry_fail (C : Crypto D) (c : Cfg) (st : St D) (i : Input D) {x : Signed D} {w : Nat}
    (he : (step C c st i).sent = st.sent ++ [x]) (hb : x.msg.body = .fail true w) :
    x.msg.attempt = st.k ∧ (mine c st .gapVal = false ∨ pairRetry st = true) := by
  rcases step_sent C c st i with he' | ⟨y, he', hy⟩
  · rw [he'] at he
    have := congrArg List.length he; simp at this
  · rw [he'] at he
    have hxy : y = x := by simpa using he
    subst hxy
    obtain ⟨-, hk, -, -, -, -, hm⟩ := hy
    refine ⟨hk, ?_⟩
    rw [hb] at hm
    exact hm rfl

/-- **FP5 (b)**, the final `FAIL`: a step that signs a final `FAIL` is the receipt of a partner
message that passed the envelope checks and failed its body check. Nothing else signs one. -/
theorem fp5_final_fail (C : Crypto D) (c : Cfg) (st : St D) (i : Input D) {x : Signed D} {w : Nat}
    (he : (step C c st i).sent = st.sent ++ [x]) (hb : x.msg.body = .fail false w) :
    ∃ s, i = .recv s ∧ envOk C c st s = true ∧
      bodyOk C c.pk (c.sid C) (st.sent ++ st.got) s.msg = false := by
  cases i with
  | tick d => simp [step] at he
  | confirm => simp [step] at he
  | advance => simp only [step, adv] at he; split at he <;> simp at he
  | send t loc =>
    exfalso; simp only [step, act] at he
    split at he
    · simp at he
    · cases t <;> (repeat' split at he) <;>
        (try simp only [emit, setT0, List.append_cancel_left_eq, List.cons.injEq, and_true] at he) <;>
        (try subst he) <;> (try simp at hb) <;> (try simp at he)
  | recv s =>
    refine ⟨s, rfl, ?_⟩
    simp only [step, recv] at he
    split at he
    · simp at he
    · rename_i hok
      simp only [Bool.not_eq_true', Bool.not_eq_false] at hok
      refine ⟨hok, ?_⟩
      split at he <;> (repeat' split at he) <;>
        (try simp only [emit, setT0, List.append_cancel_left_eq, List.cons.injEq, and_true] at he) <;>
        (try subst he) <;> (try simp at hb) <;> (try simp at he) <;>
        (try (rename_i hn _; simpa using hn))

end ProtoFv
