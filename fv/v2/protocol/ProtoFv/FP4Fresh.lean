import ProtoFv.Steps

/-!
# FP4, freshness

Spec section 6, FP4. Every message the honest device accepts carries its own `sid`, and
`sid = H("pop-p2p-v2" ‖ pk_A ‖ pk_B ‖ r_A ‖ r_B ‖ ctx)` holds the device's own fresh random.
So under HASH, a message from any session whose random for this device's role differs (an old
record, another session) is never accepted.

`JOIN` is not modeled: the config already holds the five `sid` inputs. A's `JOIN` check, which
pins its own `r_A` (spec F1b), is assumed. Assumes HASH and RAND (the random differs). Does not
give replay protection at a reader: a consumer has to mark `sid` as used (FN3).
-/

namespace ProtoFv

variable {D : Type} [DecidableEq D]

/-- The random a role puts into `sid`. -/
def ownR (r : Role) (rA rB : Nat) : Nat :=
  match r with
  | .A => rA
  | .B => rB

/-- **FP4.** Every accepted message carries the device's `sid`. -/
theorem fp4_sid {C : Crypto D} {c : Cfg} {st : St D} (h : Reach C c st)
    {x : Signed D} (hx : x ∈ st.got) : x.msg.sid = c.sid C :=
  ((Reach.roles h).2 x hx).2.1

/-- **FP4**, under HASH: no message for a session with another own random is accepted. -/
theorem fp4_fresh {C : Crypto D} (hH : C.HashInj) {c : Cfg} {st : St D} (h : Reach C c st)
    {pkA pkB rA rB ctx : Nat} (hr : ownR c.me rA rB ≠ ownR c.me c.rA c.rB)
    {x : Signed D} (hx : x ∈ st.got) : x.msg.sid ≠ C.H (.sid pkA pkB rA rB ctx) := by
  intro e
  rw [fp4_sid h hx] at e
  have := hH _ _ e
  cases this
  exact hr rfl

end ProtoFv
