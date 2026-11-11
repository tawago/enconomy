import ProtoFv.Steps

/-!
# FP2, fixed code

Spec section 6, FP2. In every reachable state:

* an accepted partner `SEED_VALUE(seed)` for `k` matches the `hs` of the partner `SEED_HASH` accepted for `k`:
  `H("seed" ‖ sid ‖ partner role ‖ k ‖ seed) = hs`;
* the device signed its own `SALT` for `k` only once it held that `SEED_HASH`;
* under HASH, `fp2_one_seed`: any two runs (any two continuations, whatever D sends) that
  accepted the same seed hash for `k` accepted the same seed. So once the device holds `hs`, and
  before its salt goes out, the partner's seed for `k` has one possible value. (Inside one run
  this is already given by one message per slot. The point is across runs.)

Assumes HASH for the last point only. "D couldn't steer its code within the attempt" needs RAND
and HIDE too: that is reasoning, not a theorem here. Over a session D gets two draws (K16).
-/

namespace ProtoFv

variable {D : Type} [DecidableEq D]

def Inv2 (C : Crypto D) (c : Cfg) (st : St D) : Prop :=
  (∀ x ∈ st.got, ∀ seed, x.msg.body = .seedVal seed →
    hsOf st.got c.p x.msg.attempt = some (C.H (.seed (c.sid C) c.p x.msg.attempt seed))) ∧
  (∀ x ∈ st.sent, x.msg.body.tag = .salt → has st.got (c.p, x.msg.attempt, .seedHash) = true)

theorem hsOf_step {C : Crypto D} {c : Cfg} {st : St D} (i : Input D) {r k v}
    (h : hsOf st.got r k = some v) : hsOf (step C c st i).got r k = some v :=
  lookup_step_got (fun o => match o with | some (.seedHash hs _) => some hs | _ => none) rfl C c st i h

theorem inv2 {C : Crypto D} {c : Cfg} {st : St D} (h : Reach C c st) : Inv2 C c st := by
  induction h with
  | init => simp [Inv2, St.init]
  | @step st i hr ih =>
    obtain ⟨h1, h2⟩ := ih
    have R := Reach.roles hr
    refine ⟨fun x hx seed hb => ?_, fun x hx ht => ?_⟩
    · rcases step_got C c st i with he | ⟨y, he, hy⟩
      · rw [he] at hx; exact hsOf_step i (h1 x hx seed hb)
      · rw [he] at hx; simp at hx
        rcases hx with hx | rfl
        · exact hsOf_step i (h1 x hx seed hb)
        · obtain ⟨henv, hbody⟩ := hy
          have E := envOk_eq.1 henv
          rw [hb] at hbody
          simp [bodyOk, hb] at hbody
          rw [E.role] at hbody
          have : hsOf st.got c.p x.msg.attempt = some (C.H (.seed (c.sid C) c.p x.msg.attempt seed)) := by
            have e := get?_partner R x.msg.attempt .seedHash
            unfold hsOf at hbody ⊢; rw [e] at hbody; exact hbody
          exact hsOf_step i this
    · rcases step_sent C c st i with he | ⟨y, he, hy⟩
      · rw [he] at hx; exact step_has_got C c st i (h2 x hx ht)
      · rw [he] at hx; simp at hx
        rcases hx with hx | rfl
        · exact step_has_got C c st i (h2 x hx ht)
        · obtain ⟨-, hk, -, -, -, -, hb⟩ := hy
          revert hb ht; cases x.msg.body <;> simp [Body.tag]
          intro hs; rw [hk]; exact step_has_got C c st i hs

/-- **FP2.** An accepted partner seed matches the accepted seed hash. -/
theorem fp2_matches {C : Crypto D} {c : Cfg} {st : St D} (h : Reach C c st)
    {x : Signed D} (hx : x ∈ st.got) {seed : Nat} (hb : x.msg.body = .seedVal seed) :
    hsOf st.got c.p x.msg.attempt = some (C.H (.seed (c.sid C) c.p x.msg.attempt seed)) :=
  (inv2 h).1 x hx seed hb

/-- **FP2.** Own `SALT` for `k` only after holding the partner's seed hash for `k`. -/
theorem fp2_salt_after {C : Crypto D} {c : Cfg} {st : St D} (h : Reach C c st)
    {x : Signed D} (hx : x ∈ st.sent) (ht : x.msg.body.tag = .salt) :
    has st.got (c.p, x.msg.attempt, .seedHash) = true :=
  (inv2 h).2 x hx ht

/-- **FP2**, under HASH: two runs that accepted the same seed hash for `k` accepted the same
seed for `k`. -/
theorem fp2_one_seed {C : Crypto D} (hH : C.HashInj) {c : Cfg} {st1 st2 : St D}
    (r1 : Reach C c st1) (r2 : Reach C c st2)
    {x y : Signed D} (hx : x ∈ st1.got) (hy : y ∈ st2.got) (hk : x.msg.attempt = y.msg.attempt)
    (hhs : hsOf st1.got c.p x.msg.attempt = hsOf st2.got c.p y.msg.attempt)
    {s1 s2 : Nat} (h1 : x.msg.body = .seedVal s1) (h2 : y.msg.body = .seedVal s2) : s1 = s2 := by
  have e1 := fp2_matches r1 hx h1
  have e2 := fp2_matches r2 hy h2
  rw [hhs, e2, hk] at e1
  have := hH _ _ (Option.some.inj e1)
  cases this; rfl

end ProtoFv
