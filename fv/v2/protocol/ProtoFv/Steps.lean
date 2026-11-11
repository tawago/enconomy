import ProtoFv.Device

/-!
# What one step can do

The property files reason through these few facts, not through `step` itself:

* `step_sent`: a step signs nothing, or one message, for the current attempt, from `me`, and only
  if `Allowed` holds in the state before the step.
* `step_got`: a step accepts nothing, or one message that passed the envelope checks and the body
  checks.
* `step_mono`: the logs only grow, the clock only moves forward, `t0` is written once.
* `step_k`: the attempt only moves on through `adv`, under its guard: no own `GAP_VALUE` for the
  attempt, or a pair that asks for a retry (`pairRetry`).
* `Reach.roles`: every signed message is from `me` for this `sid`; every accepted one is from the
  partner, for this `sid`, with a valid signature.
-/

namespace ProtoFv

set_option linter.unusedSectionVars false

variable {D : Type} [DecidableEq D]

/-! ## Lists -/

theorem has_iff {l : List (Signed D)} {x} : has l x = true ↔ ∃ s ∈ l, s.slot = x := by
  simp [has, List.any_eq_true]

theorem has_append {l m : List (Signed D)} {x} (h : has l x = true) : has (l ++ m) x = true := by
  simp [has, List.any_append] at *; simp [h]

theorem has_append_one {l : List (Signed D)} {x y} :
    has (l ++ [y]) x = (has l x || y.slot == x) := by
  simp [has, List.any_append]

theorem get?_append {l m : List (Signed D)} {x b} (h : get? l x = some b) :
    get? (l ++ m) x = some b := by
  simp only [get?, List.find?_append, Option.map] at *
  split at h <;> simp_all

/-- Looking up a slot no element of `l` holds skips `l`. -/
theorem get?_append_skip {l m : List (Signed D)} {x} (h : ∀ s ∈ l, s.slot ≠ x) :
    get? (l ++ m) x = get? m x := by
  have : List.find? (fun s => s.slot == x) l = none :=
    List.find?_eq_none.2 (fun s hs => by simpa using h s hs)
  simp [get?, List.find?_append, this]

theorem get?_some_of_has {l : List (Signed D)} {x} (h : has l x = true) :
    ∃ b, get? l x = some b ∧ b.tag = x.2.2 := by
  cases hf : List.find? (fun s => s.slot == x) l with
  | none =>
    rw [has_iff] at h; obtain ⟨s, hs, he⟩ := h
    exact absurd (List.find?_eq_none.1 hf s hs) (by simp [he])
  | some s =>
    have := List.find?_some hf
    refine ⟨s.msg.body, by simp [get?, hf], ?_⟩
    simp [Signed.slot] at this; rw [← this]

/-- Each lookup (`hsOf`, `cOf`, ...) keeps its value when the list grows. -/
theorem pick_append {α : Type} {l m : List (Signed D)} {x} {f : Body D → Option α} {v : α}
    (h : (get? l x).bind f = some v) : (get? (l ++ m) x).bind f = some v := by
  cases hg : get? l x with
  | none => simp [hg] at h
  | some b => rw [get?_append hg]; simpa [hg] using h

/-! ## The step facts -/

/-- The guard under which `step` signs body `b` in state `st`. -/
def Allowed (c : Cfg) (st : St D) (b : Body D) : Prop :=
  st.done = false ∧ mine c st .fail = false ∧ mine c st b.tag = false ∧
  match b with
  | .salt _ => theirs c st .seedHash = true
  | .time _ => c.me = .A ∧ theirs c st .salt = true
  | .recHash _ => theirs c st .salt = true ∧ ∃ t0, st.t0 st.k = some t0 ∧ t0 + 2000 ≤ st.now
  | .seedVal _ => theirs c st .recHash = true ∧ mine c st .recHash = true
  | .gapHash _ => theirs c st .seedVal = true ∧ mine c st .seedVal = true
  | .gapVal .. => theirs c st .gapHash = true ∧ mine c st .gapHash = true
  | .fail r _ => r = true → (mine c st .gapVal = false ∨ pairRetry st = true)
  | _ => True

/-- A message `step` may add to `sent`. -/
def NewSent (C : Crypto D) (c : Cfg) (st : St D) (x : Signed D) : Prop :=
  x.msg.role = c.me ∧ x.msg.attempt = st.k ∧ x.msg.sid = c.sid C ∧ Allowed c st x.msg.body

/-- A message `step` may add to `got`. -/
def NewGot (C : Crypto D) (c : Cfg) (st : St D) (s : Signed D) : Prop :=
  envOk C c st s = true ∧
  match s.msg.body with
  | .time _ => True
  | .fail .. => True
  | _ => bodyOk C c.pk (c.sid C) (st.sent ++ st.got) s.msg = true

theorem step_sent (C : Crypto D) (c : Cfg) (st : St D) (i : Input D) :
    (step C c st i).sent = st.sent ∨
      ∃ x, (step C c st i).sent = st.sent ++ [x] ∧ NewSent C c st x := by
  cases i <;> simp only [step, act, recv, adv, emit, setT0] <;> (repeat' split) <;>
    simp_all [NewSent, Allowed, Body.tag, gate, envOk, mine, theirs]

theorem step_got (C : Crypto D) (c : Cfg) (st : St D) (i : Input D) :
    (step C c st i).got = st.got ∨
      ∃ s, (step C c st i).got = st.got ++ [s] ∧ NewGot C c st s := by
  cases i <;> simp only [step, act, recv, adv, emit, setT0] <;> (repeat' split) <;>
    simp_all [NewGot]

theorem step_mono (C : Crypto D) (c : Cfg) (st : St D) (i : Input D) :
    st.now ≤ (step C c st i).now ∧ st.k ≤ (step C c st i).k ∧
      (st.done = true → (step C c st i).done = true) ∧
      ∀ j v, st.t0 j = some v → (step C c st i).t0 j = some v := by
  cases i <;> simp only [step, act, recv, adv, emit, setT0] <;> (repeat' split) <;>
    simp_all

theorem step_k (C : Crypto D) (c : Cfg) (st : St D) (i : Input D) :
    (step C c st i).k = st.k ∨
      ((step C c st i).k = st.k + 1 ∧ (mine c st .gapVal = false ∨ pairRetry st = true) ∧
        retried st.got c.p st.k = true) := by
  cases i <;> simp only [step, act, recv, adv, emit, setT0] <;> (repeat' split) <;>
    simp_all

/-- `envOk`, unpacked. -/
structure EnvFacts (C : Crypto D) (c : Cfg) (st : St D) (s : Signed D) : Prop where
  conf : st.confirmed = true
  live : st.done = false
  sig : C.verify (c.pk c.p) s.msg s.sig = true
  sid : s.msg.sid = c.sid C
  role : s.msg.role = c.p
  att : s.msg.attempt = st.k
  fresh : has st.got s.slot = false
  exp : expects c st s.msg = true
  peer : peerOk C st.sent s.msg = true

theorem envOk_eq {C : Crypto D} {c : Cfg} {st : St D} {s : Signed D} :
    envOk C c st s = true ↔ EnvFacts C c st s := by
  constructor
  · intro h; simp [envOk] at h
    obtain ⟨⟨⟨⟨⟨⟨⟨⟨a, b⟩, d⟩, e⟩, f⟩, g⟩, i⟩, j⟩, k⟩ := h
    exact ⟨a, b, d, e, f, g, i, j, k⟩
  · intro h; simp [envOk, h.conf, h.live, h.sig, h.sid, h.role, h.att, h.fresh, h.exp, h.peer]

/-- Every signed message is from `me` for this `sid`. Every accepted one is from the partner,
for this `sid`, for an attempt not past the current one, with a valid signature. -/
def Roles (C : Crypto D) (c : Cfg) (st : St D) : Prop :=
  (∀ x ∈ st.sent, x.msg.role = c.me ∧ x.msg.sid = c.sid C ∧ x.msg.attempt ≤ st.k) ∧
  (∀ x ∈ st.got, x.msg.role = c.p ∧ x.msg.sid = c.sid C ∧ x.msg.attempt ≤ st.k ∧
     C.verify (c.pk c.p) x.msg x.sig = true)

theorem Reach.roles {C : Crypto D} {c : Cfg} {st : St D} (h : Reach C c st) : Roles C c st := by
  induction h with
  | init => simp [Roles, St.init]
  | @step st i _ ih =>
    obtain ⟨h1, h2⟩ := ih
    have hk := (step_mono C c st i).2.1
    refine ⟨fun x hx => ?_, fun x hx => ?_⟩
    · rcases step_sent C c st i with he | ⟨y, he, hy⟩ <;> rw [he] at hx
      · have := h1 x hx; exact ⟨this.1, this.2.1, Nat.le_trans this.2.2 hk⟩
      · simp at hx
        rcases hx with hx | rfl
        · have := h1 x hx; exact ⟨this.1, this.2.1, Nat.le_trans this.2.2 hk⟩
        · exact ⟨hy.1, hy.2.2.1, hy.2.1 ▸ hk⟩
    · rcases step_got C c st i with he | ⟨y, he, hy⟩ <;> rw [he] at hx
      · have := h2 x hx; exact ⟨this.1, this.2.1, Nat.le_trans this.2.2.1 hk, this.2.2.2⟩
      · simp at hx
        rcases hx with hx | rfl
        · have := h2 x hx; exact ⟨this.1, this.2.1, Nat.le_trans this.2.2.1 hk, this.2.2.2⟩
        · have := (envOk_eq.1 hy.1)
          exact ⟨this.role, this.sid, by have := this.att; omega, this.sig⟩

/-- In `sent ++ got`, a lookup for a partner slot only sees `got`. -/
theorem get?_partner {C : Crypto D} {c : Cfg} {st : St D} (h : Roles C c st) (k : Nat) (t : Tag) :
    get? (st.sent ++ st.got) (c.p, k, t) = get? st.got (c.p, k, t) :=
  get?_append_skip (fun s hs he => by
    have := (h.1 s hs).1
    simp [Signed.slot, Cfg.p] at he
    rw [this] at he; exact Role.other_ne c.me he.1.symm)

/-! ## Facts that survive a step -/

theorem step_has_got (C : Crypto D) (c : Cfg) (st : St D) (i : Input D) {x}
    (h : has st.got x = true) : has (step C c st i).got x = true := by
  rcases step_got C c st i with he | ⟨y, he, -⟩ <;> rw [he]
  · exact h
  · exact has_append h

theorem step_has_sent (C : Crypto D) (c : Cfg) (st : St D) (i : Input D) {x}
    (h : has st.sent x = true) : has (step C c st i).sent x = true := by
  rcases step_sent C c st i with he | ⟨y, he, -⟩ <;> rw [he]
  · exact h
  · exact has_append h

/-- A lookup that found something still finds it after the list grows. -/
theorem lookup_append {α : Type} (F : Option (Body D) → Option α) (hF : F none = none)
    {l m : List (Signed D)} {x} {v : α} (h : F (get? l x) = some v) :
    F (get? (l ++ m) x) = some v := by
  cases hg : get? l x with
  | none => rw [hg, hF] at h; cases h
  | some b => rw [get?_append hg, ← hg]; exact h

theorem lookup_step_got {α : Type} (F : Option (Body D) → Option α) (hF : F none = none)
    (C : Crypto D) (c : Cfg) (st : St D) (i : Input D) {x} {v : α}
    (h : F (get? st.got x) = some v) : F (get? (step C c st i).got x) = some v := by
  rcases step_got C c st i with he | ⟨y, he, -⟩ <;> rw [he]
  · exact h
  · exact lookup_append F hF h

/-- A step that signs something keeps the attempt. -/
theorem step_k_of_sent (C : Crypto D) (c : Cfg) (st : St D) (i : Input D)
    (h : (step C c st i).sent ≠ st.sent) : (step C c st i).k = st.k := by
  cases i <;> simp only [step, act, recv, adv, emit, setT0] at h ⊢ <;> (repeat' split) <;>
    simp_all

/-- A `GAP_VALUE` that passes `txOk` matches the `GAP_HASH` in its slot. -/
theorem txOk_matches {C : Crypto D} {pk : Role → Nat} {sid : D} {l : List (Signed D)} {r : Role}
    {k blind sigt : Nat} {t : Tx D} (h : txOk C pk sid l r k blind t sigt = true) :
    cOf l r k = some (C.H (.tx blind t sigt)) := by
  unfold txOk at h
  split at h
  · rename_i c sr root cc hc _ _ _
    simp at h
    rw [hc, h.1.1.1.1.1.1.1.1.1.1]
  · cases h

end ProtoFv
