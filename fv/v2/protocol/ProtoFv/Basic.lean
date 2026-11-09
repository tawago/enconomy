/-!
# Messages, the record, and what we assume of hash and signature

Follows `fv/v2/spec.md` section 2. Plain Lean core, no Mathlib.

* `D` is the digest type: what `H` returns. Keys, signatures and random values are `Nat`.
* `H`, `Sign` and `Verify` are fields of `Crypto`. Nothing about them is an axiom.
  HASH and SIG are the `Prop`s `Crypto.HashInj` and `Crypto.Unforgeable` below. A theorem
  that needs one names it as a hypothesis.
* The tag of a message is a function of its body, so a body can't carry the wrong tag.
* `seen` is the list of `H` of every partner message the sender had accepted. The spec sends
  `H(seen)`. Sending the list itself is the same thing once HASH holds, and it keeps the model
  free of a second hash layer.
-/

namespace ProtoFv

inductive Role | A | B
  deriving DecidableEq, Repr

def Role.other : Role → Role
  | .A => .B
  | .B => .A

@[simp] theorem Role.other_ne (r : Role) : r.other ≠ r := by cases r <;> decide

inductive Tag | seedc | salt | time | recc | reveal | txc | txo | fail
  deriving DecidableEq, Repr

/-- The POPT v2 fields the checks and the verdict read (spec F8). Everything else in a
transcript is left out. -/
structure Tx (D : Type) where
  role : Role
  sid : D
  attempt : Nat
  pkSelf : Nat
  pkPeer : Nat
  sr : Nat
  delta : Nat
  recRoot : Nat
  codeCommit : D
  selfOs : Int
  half : Int
  deriving DecidableEq

/-- Message bodies, spec 2.3. `fail retry why`: `retry` says if the reason is a retry reason. -/
inductive Body (D : Type) where
  | seedc (hs : D) (sr : Nat)
  | salt (salt : Nat)
  | time (t0 : Nat)
  | recc (root : Nat)
  | reveal (seed : Nat)
  | txc (c : D)
  | txo (blind : Nat) (t : Tx D) (sigt : Nat)
  | fail (retry : Bool) (why : Nat)
  deriving DecidableEq

def Body.tag {D : Type} : Body D → Tag
  | .seedc .. => .seedc
  | .salt .. => .salt
  | .time .. => .time
  | .recc .. => .recc
  | .reveal .. => .reveal
  | .txc .. => .txc
  | .txo .. => .txo
  | .fail .. => .fail

/-- `m = tag ‖ sid ‖ role ‖ attempt ‖ peer ‖ body`, spec 2.1. -/
structure Msg (D : Type) where
  sid : D
  role : Role
  attempt : Nat
  seen : List D
  body : Body D
  deriving DecidableEq

structure Signed (D : Type) where
  msg : Msg D
  sig : Nat
  deriving DecidableEq

/-- What `H` is applied to. One constructor per use, so uses can't collide (domain separation). -/
inductive Pre (D : Type) where
  | sid (pkA pkB rA rB ctx : Nat)
  | seed (sid : D) (role : Role) (k seed : Nat)
  | bed (sid : D) (role : Role) (k seed salt : Nat)
  | tx (blind : Nat) (t : Tx D) (sigt : Nat)
  | msg (m : Msg D)

structure Crypto (D : Type) where
  H : Pre D → D
  /-- `sign sk m`, the message signature. -/
  sign : Nat → Msg D → Nat
  /-- `verify pk m sig`. -/
  verify : Nat → Msg D → Nat → Bool
  /-- The POPT transcript signature `sig_t`. -/
  signTx : Nat → Tx D → Nat
  verifyTx : Nat → Tx D → Nat → Bool
  /-- `code_commit` of the two code keys `(key_A, key_B)` rendered at rate `sr`. -/
  codes : D → D → Nat → D

variable {D : Type}

/-- HASH: no collisions. -/
def Crypto.HashInj (C : Crypto D) : Prop := ∀ a b, C.H a = C.H b → a = b

/-- SIG for one key: every message that verifies under `pk` is one its holder signed. -/
def Crypto.Unforgeable (C : Crypto D) (pk : Nat) (signed : Msg D → Prop) : Prop :=
  ∀ m s, C.verify pk m s = true → signed m

/-! ## Slots and lookups -/

/-- `(role, attempt, tag)`. The spec allows one message per slot. -/
def Signed.slot (s : Signed D) : Role × Nat × Tag := (s.msg.role, s.msg.attempt, s.msg.body.tag)

def has (l : List (Signed D)) (x : Role × Nat × Tag) : Bool := l.any (fun s => s.slot == x)

/-- The body in slot `x`, the first one if there are several. -/
def get? (l : List (Signed D)) (x : Role × Nat × Tag) : Option (Body D) :=
  (l.find? (fun s => s.slot == x)).map (·.msg.body)

def hsOf (l : List (Signed D)) (r : Role) (k : Nat) : Option D :=
  match get? l (r, k, .seedc) with | some (.seedc hs _) => some hs | _ => none
def srOf (l : List (Signed D)) (r : Role) (k : Nat) : Option Nat :=
  match get? l (r, k, .seedc) with | some (.seedc _ sr) => some sr | _ => none
def saltOf (l : List (Signed D)) (r : Role) (k : Nat) : Option Nat :=
  match get? l (r, k, .salt) with | some (.salt s) => some s | _ => none
def rootOf (l : List (Signed D)) (r : Role) (k : Nat) : Option Nat :=
  match get? l (r, k, .recc) with | some (.recc x) => some x | _ => none
def seedOf (l : List (Signed D)) (r : Role) (k : Nat) : Option Nat :=
  match get? l (r, k, .reveal) with | some (.reveal s) => some s | _ => none
def cOf (l : List (Signed D)) (r : Role) (k : Nat) : Option D :=
  match get? l (r, k, .txc) with | some (.txc c) => some c | _ => none
def txOf (l : List (Signed D)) (r : Role) (k : Nat) : Option (Tx D) :=
  match get? l (r, k, .txo) with | some (.txo _ t _) => some t | _ => none
def failOf (l : List (Signed D)) (r : Role) (k : Nat) : Option (Bool × Nat) :=
  match get? l (r, k, .fail) with | some (.fail b w) => some (b, w) | _ => none

/-! ## Checks shared by the device and the reader -/

variable [DecidableEq D]

def pkOf (pkA pkB : Nat) : Role → Nat
  | .A => pkA
  | .B => pkB

def SR_MIN : Nat := 36000
def SR_MAX : Nat := 96000

/-- `delta(sr) = DELTA_MS * sr // 1000`, `DELTA_MS = 2` (`popt2.py`, `constants.py:40`). -/
def deltaOf (sr : Nat) : Nat := 2 * sr / 1000

/-- `code_commit` for attempt `k`, rederived from the seeds and salts in `l`, at rate `sr`.
`key_X = H("bed" ‖ sid ‖ X ‖ k ‖ seed_X ‖ salt_Y)`, spec F3. -/
def ccOf (C : Crypto D) (sid : D) (l : List (Signed D)) (k sr : Nat) : Option D :=
  match seedOf l .A k, seedOf l .B k, saltOf l .A k, saltOf l .B k with
  | some sA, some sB, some aA, some aB =>
      some (C.codes (C.H (.bed sid .A k sA aB)) (C.H (.bed sid .B k sB aA)) sr)
  | _, _, _, _ => none

/-- The F8 checks on a `TXO` from role `r` for attempt `k`, against the messages in `l`. -/
def txOk (C : Crypto D) (pk : Role → Nat) (sid : D) (l : List (Signed D)) (r : Role) (k : Nat)
    (blind : Nat) (t : Tx D) (sigt : Nat) : Bool :=
  match cOf l r k, srOf l r k, rootOf l r k, ccOf C sid l k t.sr with
  | some c, some sr, some root, some cc =>
      C.H (.tx blind t sigt) == c && C.verifyTx (pk r) t sigt && t.pkSelf == pk r &&
      t.pkPeer == pk r.other && t.role == r && t.sid == sid && t.attempt == k &&
      t.sr == sr && t.delta == deltaOf t.sr && t.recRoot == root && t.codeCommit == cc
  | _, _, _, _ => false

/-- Body checks a receiver and a reader both run (spec 2.3, last column). Only A sends `TIME`
(F4); its bounds are checked against the local clock, so they are not here. A `FAIL`'s reason is
not checked. -/
def bodyOk (C : Crypto D) (pk : Role → Nat) (sid : D) (l : List (Signed D)) (m : Msg D) : Bool :=
  match m.body with
  | .seedc _ sr => decide (SR_MIN ≤ sr ∧ sr ≤ SR_MAX)
  | .time _ => m.role == .A
  | .reveal seed => hsOf l m.role m.attempt == some (C.H (.seed sid m.role m.attempt seed))
  | .txo blind t sigt => txOk C pk sid l m.role m.attempt blind t sigt
  | _ => true

/-- The receiver's message that a message of tag `t` from `sender` for attempt `k` must name in
`seen` ("answers" column, spec 2.2 and 2.3), as `(attempt, tag)`. -/
def answerOf (sender : Role) (k : Nat) : Tag → Option (Nat × Tag)
  | .salt => some (k, .seedc)
  | .time => some (k, .salt)
  | .recc => if sender = .A then some (k, .salt) else some (k, .time)
  | .reveal => some (k, .recc)
  | .txc => some (k, .reveal)
  | .txo => some (k, .txc)
  | .seedc => if k = 0 then none else some (k - 1, .fail)
  | .fail => none

/-- The `peer` check, spec 2.1. `mine` is the receiver's own messages. Every entry of `seen` is
the hash of one of them, and the answered one is there. -/
def peerOk (C : Crypto D) (mine : List (Signed D)) (m : Msg D) : Bool :=
  m.seen.all (fun h => mine.any (fun s => C.H (.msg s.msg) == h)) &&
  match answerOf m.role m.attempt m.body.tag with
  | none => true
  | some (j, t) => mine.any (fun s => s.msg.attempt == j && s.msg.body.tag == t &&
      m.seen.contains (C.H (.msg s.msg)))

end ProtoFv
