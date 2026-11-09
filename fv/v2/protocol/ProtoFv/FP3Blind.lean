import ProtoFv.Steps

/-!
# FP3, blind half

Spec section 6, FP3. In every reachable state:

* a signed `TXO` for `k` comes after an accepted partner `TXC` for `k`;
* once the device signed `TXO` for `k`, it never moves past `k`, so it signs nothing for `k + 1`.

Assumes HIDE (stated, not modeled) for "the `TXC` tells D nothing about the half". Does not give:
that the half is true (CN1), nor anything about later sessions (K4). The last opener still holds
the full record (FN1).
-/

namespace ProtoFv

variable {D : Type} [DecidableEq D]

def Inv3 (c : Cfg) (st : St D) : Prop :=
  ∀ x ∈ st.sent, x.msg.body.tag = .txo →
    has st.got (c.p, x.msg.attempt, .txc) = true ∧ x.msg.attempt = st.k

theorem inv3 {C : Crypto D} {c : Cfg} {st : St D} (h : Reach C c st) : Inv3 c st := by
  induction h with
  | init => simp [Inv3, St.init]
  | @step st i hr ih =>
    have R := Reach.roles hr
    -- an old `TXO` keeps the attempt where it is
    have keep : ∀ x ∈ st.sent, x.msg.body.tag = .txo → (step C c st i).k = st.k := by
      intro x hx ht
      rcases step_k C c st i with e | ⟨-, hm, -⟩
      · exact e
      · have : mine c st .txo = true := has_iff.2 ⟨x, hx, by
          simp [Signed.slot, (R.1 x hx).1, (ih x hx ht).2, ht]⟩
        rw [this] at hm; cases hm
    intro x hx ht
    rcases step_sent C c st i with he | ⟨y, he, hy⟩
    · rw [he] at hx
      exact ⟨step_has_got C c st i (ih x hx ht).1, (ih x hx ht).2.trans (keep x hx ht).symm⟩
    · have hk' := step_k_of_sent C c st i (by rw [he]; simp)
      rw [he] at hx; simp at hx
      rcases hx with hx | rfl
      · exact ⟨step_has_got C c st i (ih x hx ht).1, (ih x hx ht).2.trans hk'.symm⟩
      · obtain ⟨-, hk, -, -, -, -, hb⟩ := hy
        refine ⟨?_, hk.trans hk'.symm⟩
        revert hb ht; cases x.msg.body <;> simp [Body.tag]
        intro hs _; rw [hk]; exact step_has_got C c st i hs

/-- **FP3.** `TXO` for `k` only after the partner's `TXC` for `k`. -/
theorem fp3_after_txc {C : Crypto D} {c : Cfg} {st : St D} (h : Reach C c st)
    {x : Signed D} (hx : x ∈ st.sent) (ht : x.msg.body.tag = .txo) :
    has st.got (c.p, x.msg.attempt, .txc) = true :=
  (inv3 h x hx ht).1

/-- **FP3.** After `TXO` for `k`, every signed message is for `k` or earlier. -/
theorem fp3_no_later {C : Crypto D} {c : Cfg} {st : St D} (h : Reach C c st)
    {x : Signed D} (hx : x ∈ st.sent) (ht : x.msg.body.tag = .txo) :
    ∀ y ∈ st.sent, y.msg.attempt ≤ x.msg.attempt := by
  intro y hy
  rw [(inv3 h x hx ht).2]
  exact ((Reach.roles h).1 y hy).2.2

end ProtoFv
