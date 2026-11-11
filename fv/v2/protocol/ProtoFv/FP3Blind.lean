import ProtoFv.Steps

/-!
# FP3, blind gap

Spec section 6, FP3, in two pieces.

* `fp3_after_gap_hash`, in every reachable state: a signed `GAP_VALUE` for `k` comes after an
  accepted partner `GAP_HASH` for `k`.
* `fp3_next_attempt`, at the moment the attempt moves on: the device has not signed `GAP_VALUE`
  for `k`, or it holds both transcripts for `k` and the verdict asks for a retry
  (`impossible_flight` or a self timing mismatch, `pairRetry`). This is the v1 retry rule, kept by
  the owner on 2026-11-11 (spec F10, Q8).

Assumes HIDE (stated, not modeled) for "the `GAP_HASH` tells D nothing about the gap". Does not give:
that the gap is true (CN1), nor anything about later sessions (K4). The last device to send its `GAP_VALUE` still holds
the full log (FN1). On a retry after both `GAP_VALUE`s the partner already knows the honest gap of
the first attempt, and D can force that retry (K3).
-/

namespace ProtoFv

variable {D : Type} [DecidableEq D]

def Inv3 (c : Cfg) (st : St D) : Prop :=
  ∀ x ∈ st.sent, x.msg.body.tag = .gapVal → has st.got (c.p, x.msg.attempt, .gapHash) = true

theorem inv3 {C : Crypto D} {c : Cfg} {st : St D} (h : Reach C c st) : Inv3 c st := by
  induction h with
  | init => simp [Inv3, St.init]
  | @step st i _ ih =>
    intro x hx ht
    rcases step_sent C c st i with he | ⟨y, he, hy⟩
    · rw [he] at hx
      exact step_has_got C c st i (ih x hx ht)
    · rw [he] at hx; simp at hx
      rcases hx with hx | rfl
      · exact step_has_got C c st i (ih x hx ht)
      · obtain ⟨-, hk, -, -, -, -, hb⟩ := hy
        revert hb ht; cases x.msg.body <;> simp [Body.tag]
        intro hs _; rw [hk]; exact step_has_got C c st i hs

/-- **FP3.** `GAP_VALUE` for `k` only after the partner's `GAP_HASH` for `k`. -/
theorem fp3_after_gap_hash {C : Crypto D} {c : Cfg} {st : St D} (h : Reach C c st)
    {x : Signed D} (hx : x ∈ st.sent) (ht : x.msg.body.tag = .gapVal) :
    has st.got (c.p, x.msg.attempt, .gapHash) = true :=
  inv3 h x hx ht

/-- **FP3**, at the moment the attempt moves on: a step that leaves attempt `k` goes to `k + 1`.
It runs in a state where the device has not signed `GAP_VALUE` for `k`, or holds both transcripts
for `k` with a verdict that asks for a retry. -/
theorem fp3_next_attempt (C : Crypto D) (c : Cfg) (st : St D) (i : Input D)
    (h : (step C c st i).k ≠ st.k) :
    (step C c st i).k = st.k + 1 ∧ (mine c st .gapVal = false ∨ pairRetry st = true) := by
  rcases step_k C c st i with e | ⟨e, hm, -⟩
  · exact absurd e h
  · exact ⟨e, hm⟩

end ProtoFv
