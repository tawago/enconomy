import ProtoFv.Steps

/-!
# The retry after both `GAP_VALUE`s, in every reachable state

Spec F10, FP3 and FP5 (b). `fp3_next_attempt` and `fp5_retry_fail` speak about one step. Here the
same rule holds in every reachable state, for every attempt `j`, not only the current one.

* `fp3_next_attempt_reach`: if the device has moved past attempt `j` and signed `GAP_VALUE` for
  `j`, it holds both transcripts for `j` and `combine` gives `impossible` or `selfTs`.
* `fp5_retry_fail_reach`: if the device signed both `GAP_VALUE` and a retry `FAIL` for `j`, the
  same holds.

The step proof needs one fact: a lookup in `sent ++ got` keeps its value as the logs grow
(`get?_step`). `sent` grows in the middle of `sent ++ got`, so this uses `Reach.roles`: own slots
are only in `sent`, partner slots only in `got`.
-/

namespace ProtoFv

set_option linter.unusedSectionVars false

variable {D : Type} [DecidableEq D]

/-- `pairRetry` for any attempt `j`: both transcripts for `j` are in `l` and `combine` asks for a
retry. -/
def pairAt (l : List (Signed D)) (j : Nat) : Bool :=
  match txOf l .A j, txOf l .B j with
  | some ta, some tb =>
      match combine ta tb with
      | .impossible => true
      | .selfTs _ => true
      | _ => false
  | _, _ => false

theorem pairRetry_eq (st : St D) : pairRetry st = pairAt (st.sent ++ st.got) st.k := rfl

/-- `pairAt`, spelled out. -/
theorem pairAt_iff {l : List (Signed D)} {j : Nat} :
    pairAt l j = true ↔ ∃ ta tb, txOf l .A j = some ta ∧ txOf l .B j = some tb ∧
      (combine ta tb = .impossible ∨ ∃ r, combine ta tb = .selfTs r) := by
  unfold pairAt
  cases txOf l .A j <;> cases txOf l .B j <;> simp
  split <;> simp_all

/-- `pairAt` reads two lookups, so it stays true when every lookup that found something keeps it. -/
theorem pairAt_mono {l l' : List (Signed D)} {j : Nat}
    (hm : ∀ x b, get? l x = some b → get? l' x = some b) (h : pairAt l j = true) :
    pairAt l' j = true := by
  unfold pairAt txOf at *
  cases ha : get? l (.A, j, .gapVal) with
  | none => simp [ha] at h
  | some ba =>
    cases hb : get? l (.B, j, .gapVal) with
    | none => simp [ha, hb] at h
    | some bb => rw [hm _ _ ha, hm _ _ hb]; simpa [ha, hb] using h

/-- Looking up a slot no element of `m` holds skips `m`. -/
theorem get?_append_none {l m : List (Signed D)} {x} (h : ∀ s ∈ m, s.slot ≠ x) :
    get? (l ++ m) x = get? l x := by
  have : List.find? (fun s => s.slot == x) m = none :=
    List.find?_eq_none.2 (fun s hs => by simpa using h s hs)
  simp [get?, List.find?_append, this]

/-- In `sent ++ got`, an own slot is looked up in `sent`, a partner slot in `got`. -/
theorem get?_split {C : Crypto D} {c : Cfg} {st : St D} (R : Roles C c st) (x : Role × Nat × Tag) :
    get? (st.sent ++ st.got) x = if x.1 = c.me then get? st.sent x else get? st.got x := by
  split
  · rename_i h
    exact get?_append_none (fun s hs he => by
      have := (R.2 s hs).1
      rw [← he] at h; simp [Signed.slot, this, Cfg.p] at h)
  · rename_i h
    exact get?_append_skip (fun s hs he => by
      have := (R.1 s hs).1
      rw [← he] at h; simp [Signed.slot, this] at h)

/-- A lookup in `sent ++ got` keeps its value after a step. -/
theorem get?_step {C : Crypto D} {c : Cfg} {st : St D} (hr : Reach C c st) (i : Input D)
    (x : Role × Nat × Tag) (b : Body D) (h : get? (st.sent ++ st.got) x = some b) :
    get? ((step C c st i).sent ++ (step C c st i).got) x = some b := by
  rw [get?_split (Reach.roles hr)] at h
  rw [get?_split (Reach.roles (Reach.step i hr))]
  split at h <;> simp only [*, ite_true, ite_false]
  · rcases step_sent C c st i with he | ⟨y, he, -⟩ <;> rw [he]
    · exact h
    · exact get?_append h
  · rcases step_got C c st i with he | ⟨y, he, -⟩ <;> rw [he]
    · exact h
    · exact get?_append h

theorem pairAt_step {C : Crypto D} {c : Cfg} {st : St D} (hr : Reach C c st) (i : Input D)
    {j : Nat} (h : pairAt (st.sent ++ st.got) j = true) :
    pairAt ((step C c st i).sent ++ (step C c st i).got) j = true :=
  pairAt_mono (get?_step hr i) h

/-- A step that signs nothing new in slot `x` leaves `has sent x` as it was. -/
theorem has_sent_back {C : Crypto D} {c : Cfg} {st : St D} {i : Input D} {y : Signed D} {x}
    (he : (step C c st i).sent = st.sent ++ [y]) (hy : y.slot ≠ x)
    (h : has (step C c st i).sent x = true) : has st.sent x = true := by
  rw [he, has_append_one] at h
  simpa [hy] using h

/-! ## FP3: past an attempt with an own `GAP_VALUE` only on a retry verdict -/

def InvNext (c : Cfg) (st : St D) : Prop :=
  ∀ j, j < st.k → has st.sent (c.me, j, .gapVal) = true → pairAt (st.sent ++ st.got) j = true

theorem invNext {C : Crypto D} {c : Cfg} {st : St D} (h : Reach C c st) : InvNext c st := by
  induction h with
  | init => intro j hj; simp [St.init] at hj
  | @step st i hr ih =>
    intro j hj hg
    by_cases hk : (step C c st i).k = st.k
    · -- same attempt: anything new in `sent` is for `st.k`, not `j`
      rw [hk] at hj
      have hold : has st.sent (c.me, j, .gapVal) = true := by
        rcases step_sent C c st i with he | ⟨y, he, hy⟩
        · rwa [he] at hg
        · refine has_sent_back he (fun e => ?_) hg
          simp [Signed.slot, hy.2.1] at e; omega
      exact pairAt_step hr i (ih j hj hold)
    · -- the attempt moved: nothing was signed, and the guard of `adv` held
      have hs : (step C c st i).sent = st.sent :=
        Classical.byContradiction (fun ne => hk (step_k_of_sent C c st i ne))
      rcases step_k C c st i with e | ⟨e, hm, -⟩
      · exact absurd e hk
      · rw [e] at hj
        rw [hs] at hg
        rcases Nat.lt_succ_iff_lt_or_eq.1 hj with hj | rfl
        · exact pairAt_step hr i (ih j hj hg)
        · rcases hm with hm | hm
          · simp [mine] at hm; rw [hm] at hg; cases hg
          · exact pairAt_step hr i hm

/-- **FP3**, in every reachable state: once the device is past attempt `j`, and it signed
`GAP_VALUE` for `j`, it holds both transcripts for `j` and the verdict asks for a retry. -/
theorem fp3_next_attempt_reach {C : Crypto D} {c : Cfg} {st : St D} (h : Reach C c st) {j : Nat}
    (hj : j < st.k) (hg : has st.sent (c.me, j, .gapVal) = true) :
    ∃ ta tb, txOf (st.sent ++ st.got) .A j = some ta ∧ txOf (st.sent ++ st.got) .B j = some tb ∧
      (combine ta tb = .impossible ∨ ∃ r, combine ta tb = .selfTs r) :=
  pairAt_iff.1 (invNext h j hj hg)

/-! ## FP5 (b): an own `GAP_VALUE` and a retry `FAIL` only on a retry verdict -/

def InvFail (c : Cfg) (st : St D) : Prop :=
  ∀ x ∈ st.sent, ∀ w, x.msg.body = .fail true w →
    has st.sent (c.me, x.msg.attempt, .gapVal) = true →
    pairAt (st.sent ++ st.got) x.msg.attempt = true

theorem invFail {C : Crypto D} {c : Cfg} {st : St D} (h : Reach C c st) : InvFail c st := by
  induction h with
  | init => intro x hx; simp [St.init] at hx
  | @step st i hr ih =>
    have R := Reach.roles hr
    intro x hx w hb hg
    rcases step_sent C c st i with he | ⟨y, he, hy⟩
    · rw [he] at hx hg
      exact pairAt_step hr i (ih x hx w hb hg)
    · obtain ⟨hrole, hk, -, -, hf, -, hA⟩ := hy
      rw [he] at hx; simp at hx
      rcases hx with hx | rfl
      · -- an old `FAIL`; the new message `y` is not a `GAP_VALUE` for its attempt
        have hxr := (R.1 x hx).1
        have hold : has st.sent (c.me, x.msg.attempt, .gapVal) = true := by
          refine has_sent_back he (fun e => ?_) hg
          simp [Signed.slot] at e
          obtain ⟨-, ha, ht⟩ := e
          -- `y` would be a `GAP_VALUE` for `st.k` while a `FAIL` for `st.k` was already signed
          have : mine c st .fail = true :=
            has_iff.2 ⟨x, hx, by simp [Signed.slot, hxr, hb, Body.tag, ← ha, hk]⟩
          rw [hf] at this; cases this
        exact pairAt_step hr i (ih x hx w hb hold)
      · -- the new message is this retry `FAIL`, for `st.k`
        rw [hb] at hA
        have hold : has st.sent (c.me, st.k, .gapVal) = true := by
          rw [← hk]; exact has_sent_back he (by simp [Signed.slot, hb, Body.tag]) hg
        rcases hA rfl with hm | hm
        · simp [mine] at hm; rw [hm] at hold; cases hold
        · rw [hk]; exact pairAt_step hr i hm

/-- **FP5 (b)**, in every reachable state: if the device signed both `GAP_VALUE` and a retry
`FAIL` for attempt `j`, it holds both transcripts for `j` and the verdict asks for a retry. -/
theorem fp5_retry_fail_reach {C : Crypto D} {c : Cfg} {st : St D} (h : Reach C c st)
    {x : Signed D} (hx : x ∈ st.sent) {w : Nat} (hb : x.msg.body = .fail true w)
    (hg : has st.sent (c.me, x.msg.attempt, .gapVal) = true) :
    ∃ ta tb, txOf (st.sent ++ st.got) .A x.msg.attempt = some ta ∧
      txOf (st.sent ++ st.got) .B x.msg.attempt = some tb ∧
      (combine ta tb = .impossible ∨ ∃ r, combine ta tb = .selfTs r) :=
  pairAt_iff.1 (invFail h x hx w hb hg)

end ProtoFv
