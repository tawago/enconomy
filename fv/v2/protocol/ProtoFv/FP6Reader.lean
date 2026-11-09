import ProtoFv.FP5Agree

/-!
# FP6, third-party check

Spec section 6, FP6, about the reader's pure `verify` (`Record.lean`). For keys the reader pinned:

* `fp6_value`: `verify` returns the record's `sid` and `outcome`, and does so exactly when every
  check passes.
* `fp6_signed`, `fp6_tamper` (SIG): every message under the honest role in a record that verifies
  is one the honest device signed. A changed field gives a message it never signed, so `verify`
  rejects the record.
* `fp6_pinned` (HASH): a message the honest side named in `seen` is the only message in its slot.
  So once the honest device answered, D can't swap that message for another.
* `fp6_txo_fixed` (HASH): D's `TXO` content (`blind`, `t`, `sig_t`) is fixed by D's `TXC`.

Does not give: anything about the air, or who holds a key (decision 3). D's `FAIL`s are fixed by
nothing: D can add one and make its own record NOT_NEAR (X2, K12). A NEAR record does not mean
the honest device saw NEAR (K10).
-/

namespace ProtoFv

variable {D : Type} [DecidableEq D]

/-- What a passing `verify` checked, unpacked. -/
structure Checked (C : Crypto D) (pkA pkB : Nat) (rec : Record D) : Prop where
  keyA : rec.pkA = pkA
  keyB : rec.pkB = pkB
  keysDiffer : pkA ≠ pkB
  slots : SlotsDistinct rec.msgs
  each : ∀ x ∈ rec.msgs, msgOk C (pkOf pkA pkB) (C.H (.sid rec.pkA rec.pkB rec.rA rec.rB rec.ctx))
    rec.msgs x = true

/-- **FP6.** `verify` gives the `sid` and the outcome of the record, exactly when all checks pass. -/
theorem fp6_value (C : Crypto D) (pkA pkB : Nat) (rec : Record D) :
    (∃ r, verify C pkA pkB rec = some r) ↔ Checked C pkA pkB rec := by
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

theorem fp6_result {C : Crypto D} {pkA pkB : Nat} {rec : Record D} {r : D × Outcome}
    (h : verify C pkA pkB rec = some r) :
    r = (C.H (.sid rec.pkA rec.pkB rec.rA rec.rB rec.ctx), outcome rec.msgs) := by
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

theorem checked_of {C : Crypto D} {pkA pkB : Nat} {rec : Record D} {r}
    (h : verify C pkA pkB rec = some r) : Checked C pkA pkB rec :=
  (fp6_value C pkA pkB rec).1 ⟨r, h⟩

/-- **FP6**, under SIG for the honest role `hr`: every message under `hr` in a verifying record
was signed by the honest device. `S` is the set of messages it signed. -/
theorem fp6_signed {C : Crypto D} {pkA pkB : Nat} {hr : Role} {S : Msg D → Prop}
    (hSig : C.Unforgeable (pkOf pkA pkB hr) S) {rec : Record D} {r}
    (h : verify C pkA pkB rec = some r) {x : Signed D} (hx : x ∈ rec.msgs)
    (hrole : x.msg.role = hr) : S x.msg := by
  have := msgOk_parts ((checked_of h).each x hx)
  rw [hrole] at this
  exact hSig _ _ this.1

/-- **FP6**, under SIG: a record holding, under the honest role, a message the honest device
never signed (for example a signed message with one field changed) is rejected. -/
theorem fp6_tamper {C : Crypto D} {pkA pkB : Nat} {hr : Role} {S : Msg D → Prop}
    (hSig : C.Unforgeable (pkOf pkA pkB hr) S) {rec : Record D} {x : Signed D}
    (hx : x ∈ rec.msgs) (hrole : x.msg.role = hr) (hn : ¬ S x.msg) :
    verify C pkA pkB rec = none := by
  cases h : verify C pkA pkB rec with
  | none => rfl
  | some r => exact absurd (fp6_signed hSig h hx hrole) hn

/-- **FP6**, under HASH: if a message `hm` in a verifying record names `d` in `seen`, then every
message of the record in `d`'s slot is `d`. -/
theorem fp6_pinned {C : Crypto D} (hH : C.HashInj) {pkA pkB : Nat} {rec : Record D} {r}
    (h : verify C pkA pkB rec = some r) {hm : Signed D} (hhm : hm ∈ rec.msgs) {d : Msg D}
    (hd : C.H (.msg d) ∈ hm.msg.seen) {y : Signed D} (hy : y ∈ rec.msgs)
    (hs : y.slot = (d.role, d.attempt, d.body.tag)) : y.msg = d := by
  have ck := checked_of h
  have := (msgOk_parts (ck.each hm hhm)).2.2.1
  simp [peerOk] at this
  obtain ⟨z, hz', hzh⟩ := this.1 _ hd
  have hzd : z.msg = d := by have := hH _ _ hzh.2; cases this; rfl
  have : y = z := slot_unique ck.slots hy hz' (by rw [hs]; simp [Signed.slot, hzd])
  rw [this, hzd]

/-- In a verifying record, every `TXO` opens the `TXC` in its slot. -/
theorem fp6_txo_opens {C : Crypto D} {pkA pkB : Nat} {rec : Record D} {r}
    (h : verify C pkA pkB rec = some r) {x : Signed D} (hx : x ∈ rec.msgs)
    {blind sigt : Nat} {t : Tx D} (hb : x.msg.body = .txo blind t sigt) :
    cOf rec.msgs x.msg.role x.msg.attempt = some (C.H (.tx blind t sigt)) := by
  have hbody := (msgOk_parts ((checked_of h).each x hx)).2.2.2.1
  simp only [bodyOk, hb] at hbody
  exact txOk_opens hbody

/-- **FP6**, under HASH: two verifying records with the same `TXC` in one slot have the same
`TXO` content in that slot. D can't open its commit two ways. -/
theorem fp6_txo_fixed {C : Crypto D} (hH : C.HashInj) {pkA pkB : Nat} {rec1 rec2 : Record D}
    {r1 r2} (h1 : verify C pkA pkB rec1 = some r1) (h2 : verify C pkA pkB rec2 = some r2)
    {x1 x2 : Signed D} (hx1 : x1 ∈ rec1.msgs) (hx2 : x2 ∈ rec2.msgs)
    (hc : cOf rec1.msgs x1.msg.role x1.msg.attempt = cOf rec2.msgs x2.msg.role x2.msg.attempt)
    {b1 b2 s1 s2 : Nat} {t1 t2 : Tx D}
    (e1 : x1.msg.body = .txo b1 t1 s1) (e2 : x2.msg.body = .txo b2 t2 s2) :
    b1 = b2 ∧ t1 = t2 ∧ s1 = s2 := by
  have o1 := fp6_txo_opens h1 hx1 e1
  have o2 := fp6_txo_opens h2 hx2 e2
  rw [o1, o2] at hc
  have := hH _ _ (Option.some.inj hc)
  cases this
  exact ⟨rfl, rfl, rfl⟩

end ProtoFv
