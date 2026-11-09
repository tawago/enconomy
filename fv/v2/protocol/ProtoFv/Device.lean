import ProtoFv.Basic

/-!
# One honest device as a state machine

Spec sections 2.2 to 2.3 and F10, from the view of one honest device after `JOIN`.

* The adversary picks every input: any message (`recv`), when the app tries to send (`send`),
  the person's tap, clock ticks and when to try the next attempt. So the guards below are all
  that stand between it and a bad send.
* Clock ticks add, so the clock only moves forward. No hypothesis is needed for that.
* `send t loc`: the app asks to sign a message of tag `t`. `loc` is what its own audio gave
  (recording root, self offset, half, a failure reason). The device signs only if the guard holds.
* The state keeps every signed and every accepted message. That list is the record (F11).

Not modeled: `INVITE`/`JOIN` (the config holds `sid`'s inputs), resends (same bytes, dropped as
duplicates), encryption, timeouts and the 600 s end as clock rules (a timeout is just a
`send .fail`), the local measurement (F7).
-/

namespace ProtoFv

variable {D : Type} [DecidableEq D]

structure Cfg where
  me : Role
  sk : Nat
  pkA : Nat
  pkB : Nat
  rA : Nat
  rB : Nat
  ctx : Nat
  /-- Fresh per attempt (RAND). -/
  seed : Nat → Nat
  salt : Nat → Nat
  blind : Nat → Nat
  sr : Nat

def Cfg.sid (C : Crypto D) (c : Cfg) : D := C.H (.sid c.pkA c.pkB c.rA c.rB c.ctx)
def Cfg.pk (c : Cfg) : Role → Nat := pkOf c.pkA c.pkB
def Cfg.p (c : Cfg) : Role := c.me.other

structure Local where
  root : Nat
  selfOs : Int
  half : Int
  why : Nat

structure St (D : Type) where
  now : Nat
  confirmed : Bool
  k : Nat
  done : Bool
  /-- `t0` per attempt, written once. -/
  t0 : Nat → Option Nat
  /-- Own transcript for the current attempt, fixed when `TXC` is signed. -/
  tx : Option (Tx D)
  sent : List (Signed D)
  got : List (Signed D)

def St.init : St D :=
  { now := 0, confirmed := false, k := 0, done := false, t0 := fun _ => none, tx := none,
    sent := [], got := [] }

inductive Input (D : Type)
  | tick (d : Nat)
  | confirm
  | recv (s : Signed D)
  | send (t : Tag) (loc : Local)
  | advance

/-- Own message in slot `(me, k, t)` already signed. -/
def mine (c : Cfg) (st : St D) (t : Tag) : Bool := has st.sent (c.me, st.k, t)
/-- Partner message in slot `(p, k, t)` already accepted. -/
def theirs (c : Cfg) (st : St D) (t : Tag) : Bool := has st.got (c.p, st.k, t)

def setT0 (st : St D) (v : Nat) : St D :=
  { st with t0 := fun j => match st.t0 j with
      | some x => some x
      | none => if j = st.k then some v else none }

/-- Sign body `b` for the current attempt and log it. -/
def emit (C : Crypto D) (c : Cfg) (st : St D) (b : Body D) : St D :=
  let m : Msg D := { sid := c.sid C, role := c.me, attempt := st.k,
                     seen := st.got.map (fun s => C.H (.msg s.msg)), body := b }
  { st with sent := st.sent ++ [⟨m, C.sign c.sk m⟩] }

/-- Common gate: confirmed, session live, slot free, no `FAIL` signed for this attempt. -/
def gate (c : Cfg) (st : St D) (t : Tag) : Bool :=
  st.confirmed && !st.done && !mine c st t && !mine c st .fail

/-- The "honest sender sends when" column. -/
def act (C : Crypto D) (c : Cfg) (st : St D) (t : Tag) (loc : Local) : St D :=
  if !gate c st t then st else
  match t with
  | .seedc => emit C c st (.seedc (C.H (.seed (c.sid C) c.me st.k (c.seed st.k))) c.sr)
  | .salt => if theirs c st .seedc then emit C c st (.salt (c.salt st.k)) else st
  | .time =>
      if c.me = .A && theirs c st .salt then emit C c (setT0 st (st.now + 5000)) (.time (st.now + 5000))
      else st
  | .recc =>
      match st.t0 st.k with
      | some t0 => if theirs c st .salt && decide (t0 + 2000 ≤ st.now) then emit C c st (.recc loc.root)
                   else st
      | none => st
  | .reveal => if theirs c st .recc && mine c st .recc then emit C c st (.reveal (c.seed st.k)) else st
  | .txc =>
      if theirs c st .reveal && mine c st .reveal then
        match rootOf st.sent c.me st.k, ccOf C (c.sid C) (st.sent ++ st.got) st.k c.sr with
        | some root, some cc =>
            let t : Tx D := { role := c.me, sid := c.sid C, attempt := st.k, pkSelf := c.pk c.me,
                              pkPeer := c.pk c.p, sr := c.sr, delta := deltaOf c.sr, recRoot := root, codeCommit := cc,
                              selfOs := loc.selfOs, half := loc.half }
            emit C c { st with tx := some t } (.txc (C.H (.tx (c.blind st.k) t (C.signTx c.sk t))))
        | _, _ => st
      else st
  | .txo =>
      match st.tx with
      | some t => if theirs c st .txc && mine c st .txc then
                    emit C c st (.txo (c.blind st.k) t (C.signTx c.sk t)) else st
      | none => st
  | .fail => if !mine c st .txo then emit C c st (.fail true loc.why) else st

/-- What a receiver expects now, beyond a free slot (spec 2.3). -/
def expects (c : Cfg) (st : St D) (m : Msg D) : Bool :=
  match m.body with
  | .reveal _ => theirs c st .seedc
  | .txo .. => theirs c st .txc
  | .time _ => c.me == .B && theirs c st .salt
  | _ => true

/-- The envelope checks of spec 2.1. A message failing these is dropped. Before the person's
confirm tap every message is dropped too (spec 2.2): it comes again by resend. -/
def envOk (C : Crypto D) (c : Cfg) (st : St D) (s : Signed D) : Bool :=
  st.confirmed && !st.done && C.verify (c.pk c.p) s.msg s.sig && s.msg.sid == c.sid C && s.msg.role == c.p &&
  s.msg.attempt == st.k && !has st.got s.slot && expects c st s.msg && peerOk C st.sent s.msg

def WHY_TIME : Nat := 1
def WHY_BAD : Nat := 2
def WHY_PARTNER : Nat := 3

def recv (C : Crypto D) (c : Cfg) (st : St D) (s : Signed D) : St D :=
  if !envOk C c st s then st else
  let st1 := { st with got := st.got ++ [s] }
  match s.msg.body with
  | .time t0 =>
      if decide (st.now + 1000 ≤ t0 ∧ t0 ≤ st.now + 30000) then setT0 st1 t0
      else if !mine c st .fail && !mine c st .txo then emit C c st (.fail true WHY_TIME) else st
  | .fail r _ =>
      -- a partner retry `FAIL` is answered with `FAIL(partner_failed)`, unless already opened (F10)
      if r then (if !mine c st .fail && !mine c st .txo then emit C c st1 (.fail true WHY_PARTNER) else st1)
      else { st1 with done := true }
  | _ =>
      if bodyOk C c.pk (c.sid C) (st.sent ++ st.got) s.msg then st1
      else if mine c st .fail then { st with done := true }
      else { emit C c st (.fail false WHY_BAD) with done := true }

def retried (l : List (Signed D)) (r : Role) (k : Nat) : Bool :=
  match failOf l r k with | some (true, _) => true | _ => false

/-- Move to the next attempt (F10): both retry `FAIL`s held, nothing opened, `k + 1 < 2`. -/
def adv (c : Cfg) (st : St D) : St D :=
  if !st.done && decide (st.k + 1 < 2) && retried st.sent c.me st.k && retried st.got c.p st.k &&
     !mine c st .txo
  then { st with k := st.k + 1, tx := none } else st

def step (C : Crypto D) (c : Cfg) (st : St D) : Input D → St D
  | .tick d => { st with now := st.now + d }
  | .confirm => { st with confirmed := true }
  | .recv s => recv C c st s
  | .send t loc => act C c st t loc
  | .advance => adv c st

inductive Reach (C : Crypto D) (c : Cfg) : St D → Prop
  | init : Reach C c St.init
  | step {st : St D} (i : Input D) : Reach C c st → Reach C c (step C c st i)

def run (C : Crypto D) (c : Cfg) (st : St D) (is : List (Input D)) : St D :=
  is.foldl (step C c) st

theorem reach_run (C : Crypto D) (c : Cfg) {st : St D} (h : Reach C c st) (is : List (Input D)) :
    Reach C c (run C c st is) := by
  induction is generalizing st with
  | nil => exact h
  | cons i is ih => exact ih (Reach.step i h)

end ProtoFv
