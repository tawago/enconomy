import ProtoFv.Steps

/-!
# FP1, order

Spec section 6, FP1, in two pieces.

* `fp1_order`, an invariant over every reachable state: if the honest device signed `SEED_VALUE` for
  attempt `k`, it had accepted the partner's `REC_HASH` and `SALT` for `k` and signed its own `REC_HASH`
  for `k`. `t0` for `k` is set (and written once).
* `fp1_rec_hash_clock`, at the moment of signing: a step that signs `REC_HASH` does it with `t0` set and
  the clock already past `t0 + 2.0 s`. "Past it now" alone would not say this, so it is its own
  theorem.

Assumes nothing about crypto. Does not give: that `REC_HASH` is the hash of real audio (CN1, CN2).
-/

namespace ProtoFv

variable {D : Type} [DecidableEq D]

def Inv1 (c : Cfg) (st : St D) : Prop :=
  (∀ x ∈ st.sent, x.msg.body.tag = .recHash →
    has st.got (c.p, x.msg.attempt, .salt) = true ∧
    ∃ t0, st.t0 x.msg.attempt = some t0 ∧ t0 + 2000 ≤ st.now) ∧
  (∀ x ∈ st.sent, x.msg.body.tag = .seedVal →
    has st.got (c.p, x.msg.attempt, .recHash) = true ∧ has st.sent (c.me, x.msg.attempt, .recHash) = true)

theorem inv1 {C : Crypto D} {c : Cfg} {st : St D} (h : Reach C c st) : Inv1 c st := by
  induction h with
  | init => simp [Inv1, St.init]
  | @step st i _ ih =>
    obtain ⟨h1, h2⟩ := ih
    obtain ⟨hnow, -, -, ht0⟩ := step_mono C c st i
    -- every fact about the old logs survives the step
    have gotG : ∀ x, has st.got x = true → has (step C c st i).got x = true := by
      intro x hx
      rcases step_got C c st i with he | ⟨y, he, -⟩ <;> rw [he]
      · exact hx
      · exact has_append hx
    have sentG : ∀ x, has st.sent x = true → has (step C c st i).sent x = true := by
      intro x hx
      rcases step_sent C c st i with he | ⟨y, he, -⟩ <;> rw [he]
      · exact hx
      · exact has_append hx
    have old1 : ∀ x ∈ st.sent, x.msg.body.tag = .recHash →
        has (step C c st i).got (c.p, x.msg.attempt, .salt) = true ∧
        ∃ t0, (step C c st i).t0 x.msg.attempt = some t0 ∧ t0 + 2000 ≤ (step C c st i).now := by
      intro x hx ht
      obtain ⟨a, t0, e, le⟩ := h1 x hx ht
      exact ⟨gotG _ a, t0, ht0 _ _ e, Nat.le_trans le hnow⟩
    have old2 : ∀ x ∈ st.sent, x.msg.body.tag = .seedVal →
        has (step C c st i).got (c.p, x.msg.attempt, .recHash) = true ∧
        has (step C c st i).sent (c.me, x.msg.attempt, .recHash) = true := by
      intro x hx ht
      obtain ⟨a, b⟩ := h2 x hx ht
      exact ⟨gotG _ a, sentG _ b⟩
    rcases step_sent C c st i with he | ⟨y, he, hy⟩
    · exact ⟨fun x hx ht => old1 x (he ▸ hx) ht, fun x hx ht => old2 x (he ▸ hx) ht⟩
    · obtain ⟨-, hk, -, hA⟩ := hy
      obtain ⟨-, -, -, hb⟩ := hA
      unfold Inv1
      constructor
      · intro x hx ht
        rw [he] at hx; simp at hx
        rcases hx with hx | rfl
        · exact old1 x hx ht
        · revert hb ht; cases x.msg.body <;> simp [Body.tag]
          intro hs t0 e le
          rw [hk]
          exact ⟨gotG _ hs, t0, ht0 _ _ e, Nat.le_trans le hnow⟩
      · intro x hx ht
        rw [he] at hx; simp at hx
        rcases hx with hx | rfl
        · exact old2 x hx ht
        · revert hb ht; cases x.msg.body <;> simp [Body.tag]
          intro hr hm
          rw [hk]
          exact ⟨gotG _ hr, sentG _ hm⟩

/-- **FP1.** A signed `SEED_VALUE` for `k` comes after the partner's `REC_HASH` and `SALT` for `k` and the
device's own `REC_HASH` for `k`, signed when its clock was past `t0 + 2.0 s`. -/
theorem fp1_order {C : Crypto D} {c : Cfg} {st : St D} (h : Reach C c st)
    {x : Signed D} (hx : x ∈ st.sent) (ht : x.msg.body.tag = .seedVal) :
    has st.got (c.p, x.msg.attempt, .recHash) = true ∧
    has st.got (c.p, x.msg.attempt, .salt) = true ∧
    ∃ r ∈ st.sent, r.slot = (c.me, x.msg.attempt, .recHash) ∧
      ∃ t0, st.t0 x.msg.attempt = some t0 ∧ t0 + 2000 ≤ st.now := by
  obtain ⟨h1, h2⟩ := inv1 h
  obtain ⟨hr, hm⟩ := h2 x hx ht
  obtain ⟨r, hr', hs⟩ := has_iff.1 hm
  simp [Signed.slot] at hs
  obtain ⟨-, ha, htag⟩ := hs
  obtain ⟨hsalt, rest⟩ := h1 r hr' htag
  rw [ha] at hsalt rest
  exact ⟨hr, hsalt, r, hr', by simp [Signed.slot, (Reach.roles h).1 r hr' |>.1, ha, htag], rest⟩

/-- **FP1**, at the moment of signing: the step that signs `REC_HASH` runs in a state whose clock is
past `t0 + 2.0 s` for the current attempt. -/
theorem fp1_rec_hash_clock (C : Crypto D) (c : Cfg) (st : St D) (i : Input D) {x : Signed D}
    (he : (step C c st i).sent = st.sent ++ [x]) (ht : x.msg.body.tag = .recHash) :
    x.msg.attempt = st.k ∧ ∃ t0, st.t0 st.k = some t0 ∧ t0 + 2000 ≤ st.now := by
  rcases step_sent C c st i with he' | ⟨y, he', hy⟩
  · rw [he'] at he
    have := congrArg List.length he; simp at this
  · rw [he'] at he
    have hxy : y = x := by simpa using he
    subst hxy
    obtain ⟨-, hk, -, -, -, -, hb⟩ := hy
    refine ⟨hk, ?_⟩
    revert hb ht; cases y.msg.body <;> simp [Body.tag]

end ProtoFv
