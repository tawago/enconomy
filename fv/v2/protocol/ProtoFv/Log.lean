import ProtoFv.Verdict

/-!
# The log, `Outcome` and the reader's `verify`

Spec section 4 and F11. Both are pure functions of the log.

* `outcome l`: the last attempt in `l` (0 or 1). A `FAIL` for it gives NOT_NEAR, A's first.
  Else both `GAP_VALUE`s give `combine (t_A, t_B)`, A first. Else incomplete.
* `verify pkA pkB log`: the keys must be the pinned ones; one message per slot; every signature,
  `sid`, `peer` and body check passes; then `outcome`. Returns the `sid` too. The log holds
  no stated verdict here, so there is nothing to compare: the reader computes it.
-/

namespace ProtoFv

variable {D : Type} [DecidableEq D]

inductive Outcome
  | fail (by_ : Role) (why : Nat)
  | pair (r : Res)
  | incomplete
  deriving DecidableEq, Repr

def lastK (l : List (Signed D)) : Nat := if l.any (fun s => s.msg.attempt == 1) then 1 else 0

/-- Spec section 4. This reads the log as given. The F8 checks on the two `GAP_VALUE`s are run
by `verify` before it calls `outcome`, not here: `outcome` alone is not a check. -/
def outcomeAt (l : List (Signed D)) (k : Nat) : Outcome :=
  match failOf l .A k, failOf l .B k with
  | some (_, w), _ => .fail .A w
  | none, some (_, w) => .fail .B w
  | none, none =>
      match txOf l .A k, txOf l .B k with
      | some ta, some tb => .pair (combine ta tb)
      | _, _ => .incomplete

def outcome (l : List (Signed D)) : Outcome := outcomeAt l (lastK l)

structure Log (D : Type) where
  pkA : Nat
  pkB : Nat
  rA : Nat
  rB : Nat
  ctx : Nat
  msgs : List (Signed D)

/-- One message per slot. -/
abbrev SlotsDistinct (l : List (Signed D)) : Prop := l.Pairwise (fun a b => a.slot ≠ b.slot)

/-- Both sides hold a retry `FAIL` for attempt 0: the only way into attempt 1 (F10). -/
def retryBoth (l : List (Signed D)) : Bool :=
  match failOf l .A 0, failOf l .B 0 with
  | some (true, _), some (true, _) => true
  | _, _ => false

/-- Every per-message check `verify` runs. A message for attempt 1 needs both retry `FAIL`s for
attempt 0 in the log, so D can't append attempt-1 messages after a final `FAIL`. -/
def msgOk (C : Crypto D) (pk : Role → Nat) (sid : D) (l : List (Signed D)) (s : Signed D) : Bool :=
  C.verify (pk s.msg.role) s.msg s.sig && s.msg.sid == sid &&
  peerOk C (l.filter (fun x => x.msg.role == s.msg.role.other)) s.msg && bodyOk C pk sid l s.msg &&
  decide (s.msg.attempt < 2) && (s.msg.attempt == 0 || retryBoth l)

def verify (C : Crypto D) (pkA pkB : Nat) (log : Log D) : Option (D × Outcome) :=
  let sid := C.H (.sid log.pkA log.pkB log.rA log.rB log.ctx)
  if log.pkA = pkA ∧ log.pkB = pkB ∧ pkA ≠ pkB ∧ SlotsDistinct log.msgs ∧
     log.msgs.all (msgOk C (pkOf pkA pkB) sid log.msgs) = true
  then some (sid, outcome log.msgs) else none

end ProtoFv
