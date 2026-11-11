import ProtoFv.FP5Agree

/-!
# FP6, third-party check

Spec section 6, FP6, about the reader's pure `verify` (`Log.lean`). For keys the reader pinned:

* `fp6_value`: `verify` returns the log's `sid` and `outcome`, and does so exactly when every
  check `verify` runs passes. That is the model's list of checks: `commit_hash` (F8) is not in it,
  and a reader has no clock for the `TIME` bounds. `verify` doesn't check that a log is complete.
* `fp6_signed`, `fp6_tamper` (SIG): every message under the honest role in a log that verifies
  is one the honest device signed. A changed field gives a message it never signed, so `verify`
  rejects the log.
* `fp6_pinned` (HASH): a message the honest side named in `seen` is the only message in its slot.
  So once the honest device answered, D can't swap that message for another.
* `fp6_gap_fixed` (HASH): D's `GAP_VALUE` content (`blind`, `t`, `sig_t`) is fixed by D's `GAP_HASH`.

Does not give: anything about the air, or who holds a key (decision 3). D's `FAIL`s are fixed by
nothing: D can add one and make its own log NOT_NEAR (X2, K12). A NEAR log does not mean
the honest device saw NEAR (K10).
-/

namespace ProtoFv

variable {D : Type} [DecidableEq D]

/-- What a passing `verify` checked, unpacked. -/
structure Checked (C : Crypto D) (pkA pkB : Nat) (log : Log D) : Prop where
  keyA : log.pkA = pkA
  keyB : log.pkB = pkB
  keysDiffer : pkA ≠ pkB
  slots : SlotsDistinct log.msgs
  each : ∀ x ∈ log.msgs, msgOk C (pkOf pkA pkB) (C.H (.sid log.pkA log.pkB log.rA log.rB log.ctx))
    log.msgs x = true

/-- **FP6.** `verify` gives the `sid` and the outcome of the log, exactly when all its checks pass
(`Checked`, the model's list). -/
theorem fp6_value (C : Crypto D) (pkA pkB : Nat) (log : Log D) :
    (∃ r, verify C pkA pkB log = some r) ↔ Checked C pkA pkB log := by
  dsimp only [verify]
  constructor
  · intro ⟨r, h⟩
    split at h
    · rename_i hc
      obtain ⟨a, b, d, e, f⟩ := hc
      exact ⟨a, b, d, e, List.all_eq_true.1 f⟩
    · cases h
  · intro h
    split
    · exact ⟨_, rfl⟩
    · rename_i hn
      exact absurd ⟨h.keyA, h.keyB, h.keysDiffer, h.slots, List.all_eq_true.2 h.each⟩ hn

theorem fp6_result {C : Crypto D} {pkA pkB : Nat} {log : Log D} {r : D × Outcome}
    (h : verify C pkA pkB log = some r) :
    r = (C.H (.sid log.pkA log.pkB log.rA log.rB log.ctx), outcome log.msgs) := by
  dsimp only [verify] at h
  split at h
  · exact (Option.some.inj h).symm
  · cases h

theorem msgOk_parts {C : Crypto D} {pk : Role → Nat} {sid : D} {l : List (Signed D)}
    {s : Signed D} (h : msgOk C pk sid l s = true) :
    C.verify (pk s.msg.role) s.msg s.sig = true ∧ s.msg.sid = sid ∧
    peerOk C (l.filter (fun x => x.msg.role == s.msg.role.other)) s.msg = true ∧
    bodyOk C pk sid l s.msg = true ∧ s.msg.attempt < 2 := by
  simp only [msgOk, Bool.and_eq_true, decide_eq_true_eq, beq_iff_eq] at h
  obtain ⟨⟨⟨⟨⟨a, b⟩, c⟩, d⟩, e⟩, -⟩ := h
  exact ⟨a, b, c, d, e⟩

theorem checked_of {C : Crypto D} {pkA pkB : Nat} {log : Log D} {r}
    (h : verify C pkA pkB log = some r) : Checked C pkA pkB log :=
  (fp6_value C pkA pkB log).1 ⟨r, h⟩

/-- **FP6**, under SIG for the honest role `hr`: every message under `hr` in a verifying log
was signed by the honest device. `S` is the set of messages it signed. -/
theorem fp6_signed {C : Crypto D} {pkA pkB : Nat} {hr : Role} {S : Msg D → Prop}
    (hSig : C.Unforgeable (pkOf pkA pkB hr) S) {log : Log D} {r}
    (h : verify C pkA pkB log = some r) {x : Signed D} (hx : x ∈ log.msgs)
    (hrole : x.msg.role = hr) : S x.msg := by
  have := msgOk_parts ((checked_of h).each x hx)
  rw [hrole] at this
  exact hSig _ _ this.1

/-- **FP6**, under SIG: a log holding, under the honest role, a message the honest device
never signed (for example a signed message with one field changed) is rejected. -/
theorem fp6_tamper {C : Crypto D} {pkA pkB : Nat} {hr : Role} {S : Msg D → Prop}
    (hSig : C.Unforgeable (pkOf pkA pkB hr) S) {log : Log D} {x : Signed D}
    (hx : x ∈ log.msgs) (hrole : x.msg.role = hr) (hn : ¬ S x.msg) :
    verify C pkA pkB log = none := by
  cases h : verify C pkA pkB log with
  | none => rfl
  | some r => exact absurd (fp6_signed hSig h hx hrole) hn

/-- **FP6**, under HASH: if a message `hm` in a verifying log names `d` in `seen`, then every
message of the log in `d`'s slot is `d`. -/
theorem fp6_pinned {C : Crypto D} (hH : C.HashInj) {pkA pkB : Nat} {log : Log D} {r}
    (h : verify C pkA pkB log = some r) {hm : Signed D} (hhm : hm ∈ log.msgs) {d : Msg D}
    (hd : C.H (.msg d) ∈ hm.msg.seen) {y : Signed D} (hy : y ∈ log.msgs)
    (hs : y.slot = (d.role, d.attempt, d.body.tag)) : y.msg = d := by
  have ck := checked_of h
  have := (msgOk_parts (ck.each hm hhm)).2.2.1
  simp [peerOk] at this
  obtain ⟨z, hz', hzh⟩ := this.1 _ hd
  have hzd : z.msg = d := by have := hH _ _ hzh.2; cases this; rfl
  have : y = z := slot_unique ck.slots hy hz' (by rw [hs]; simp [Signed.slot, hzd])
  rw [this, hzd]

/-- In a verifying log, every `GAP_VALUE` matches the `GAP_HASH` in its slot. -/
theorem fp6_gap_matches {C : Crypto D} {pkA pkB : Nat} {log : Log D} {r}
    (h : verify C pkA pkB log = some r) {x : Signed D} (hx : x ∈ log.msgs)
    {blind sigt : Nat} {t : Tx D} (hb : x.msg.body = .gapVal blind t sigt) :
    cOf log.msgs x.msg.role x.msg.attempt = some (C.H (.tx blind t sigt)) := by
  have hbody := (msgOk_parts ((checked_of h).each x hx)).2.2.2.1
  simp only [bodyOk, hb] at hbody
  exact txOk_matches hbody

/-- **FP6**, under HASH: two verifying logs with the same `GAP_HASH` in one slot have the same
`GAP_VALUE` content in that slot. D can not send two values for one hash. -/
theorem fp6_gap_fixed {C : Crypto D} (hH : C.HashInj) {pkA pkB : Nat} {log1 log2 : Log D}
    {r1 r2} (h1 : verify C pkA pkB log1 = some r1) (h2 : verify C pkA pkB log2 = some r2)
    {x1 x2 : Signed D} (hx1 : x1 ∈ log1.msgs) (hx2 : x2 ∈ log2.msgs)
    (hc : cOf log1.msgs x1.msg.role x1.msg.attempt = cOf log2.msgs x2.msg.role x2.msg.attempt)
    {b1 b2 s1 s2 : Nat} {t1 t2 : Tx D}
    (e1 : x1.msg.body = .gapVal b1 t1 s1) (e2 : x2.msg.body = .gapVal b2 t2 s2) :
    b1 = b2 ∧ t1 = t2 ∧ s1 = s2 := by
  have o1 := fp6_gap_matches h1 hx1 e1
  have o2 := fp6_gap_matches h2 hx2 e2
  rw [o1, o2] at hc
  have := hH _ _ (Option.some.inj hc)
  cases this
  exact ⟨rfl, rfl, rfl⟩

end ProtoFv
