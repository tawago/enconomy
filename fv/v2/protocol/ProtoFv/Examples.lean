import ProtoFv.FP1Order
import ProtoFv.FP2Code
import ProtoFv.FP3Blind
import ProtoFv.FP4Fresh
import ProtoFv.FP5Agree
import ProtoFv.FP6Reader

/-!
# The theorems are not vacuous

One concrete run of an honest A. B's messages are written by hand (B could be D: the device takes
any message). The run reaches a state where A has signed every message of attempt 0 and accepted
all of B's. Each FP gets an example that its hypotheses hold in that state, and the reader's
`verify` accepts the record with NEAR.

The toy crypto is as weak as it gets: every hash is 7, every signature checks. That is fine for
reachability: the device has no secret way past its guards. It can't satisfy HASH or SIG, so the
end of the file shows HASH holds for a free hash (`freeC`), where `H` is a constructor.
-/

namespace ProtoFv

def toyC : Crypto Nat where
  H _ := 7
  sign _ _ := 0
  verify _ _ _ := true
  signTx _ _ := 0
  verifyTx _ _ _ := true
  codes _ _ _ := 7

def cfgA : Cfg :=
  { me := .A, sk := 11, pkA := 1, pkB := 2, rA := 3, rB := 4, ctx := 0,
    seed := fun _ => 21, salt := fun _ => 22, blind := fun _ => 23, sr := 48000 }

/-- A message from B for attempt 0. `seen = [7]` names A's messages under the toy hash. -/
def fromB (b : Body Nat) : Signed Nat :=
  ⟨{ sid := 7, role := .B, attempt := 0, seen := [7], body := b }, 0⟩

def txB : Tx Nat :=
  { role := .B, sid := 7, attempt := 0, pkSelf := 2, pkPeer := 1, sr := 48000, delta := 96, recRoot := 5,
    codeCommit := 7, selfOs := 0, half := 1000 }

def locA : Local := { root := 6, selfOs := 0, half := 1000, why := 0 }

def inputsA : List (Input Nat) :=
  [ .confirm,
    .send .seedc locA, .recv (fromB (.seedc 7 48000)),
    .send .salt locA, .recv (fromB (.salt 31)),
    .send .time locA, .tick 7000,
    .send .recc locA, .recv (fromB (.recc 5)),
    .send .reveal locA, .recv (fromB (.reveal 32)),
    .send .txc locA, .recv (fromB (.txc 7)),
    .send .txo locA, .recv (fromB (.txo 33 txB 0)) ]

def runA : St Nat := run toyC cfgA St.init inputsA

theorem runA_reach : Reach toyC cfgA runA := reach_run toyC cfgA .init inputsA

/-- A signed its 7 messages of attempt 0 and accepted all 6 of B's (B sends no `TIME`). -/
example : runA.sent.length = 7 ∧ runA.got.length = 6 ∧ runA.done = false := by decide

theorem slot_of {l : List (Signed Nat)} {x} (h : has l x = true) :
    ∃ s ∈ l, s.slot = x := has_iff.1 h

/-- FP1: a reachable state with a signed `REVEAL`. -/
example : ∃ st : St Nat, Reach toyC cfgA st ∧ ∃ x ∈ st.sent, x.msg.body.tag = .reveal := by
  obtain ⟨x, hx, he⟩ := slot_of (show has runA.sent (.A, 0, .reveal) = true by decide)
  exact ⟨runA, runA_reach, x, hx, by simp [Signed.slot] at he; exact he.2.2⟩

/-- FP2: a reachable state with an accepted partner `REVEAL` and a signed `SALT`. -/
example : ∃ st : St Nat, Reach toyC cfgA st ∧ (∃ x ∈ st.got, x.msg.body = .reveal 32) ∧
    ∃ x ∈ st.sent, x.msg.body.tag = .salt := by
  obtain ⟨y, hy, hye⟩ := slot_of (show has runA.sent (.A, 0, .salt) = true by decide)
  refine ⟨runA, runA_reach, ⟨fromB (.reveal 32), by decide, rfl⟩, y, hy, ?_⟩
  simp [Signed.slot] at hye; exact hye.2.2

/-- FP3: a reachable state with a signed `TXO`. -/
example : ∃ st : St Nat, Reach toyC cfgA st ∧ ∃ x ∈ st.sent, x.msg.body.tag = .txo := by
  obtain ⟨x, hx, he⟩ := slot_of (show has runA.sent (.A, 0, .txo) = true by decide)
  exact ⟨runA, runA_reach, x, hx, by simp [Signed.slot] at he; exact he.2.2⟩

/-- FP4: a reachable state with accepted messages. -/
example : ∃ st : St Nat, Reach toyC cfgA st ∧ st.got ≠ [] :=
  ⟨runA, runA_reach, by decide⟩

/-- FP5 (b): a reachable state with an accepted partner `TXO`. (a): the outcome is the pair's. -/
example : ∃ st : St Nat, Reach toyC cfgA st ∧ ∃ x ∈ st.got, x.msg.body = .txo 33 txB 0 :=
  ⟨runA, runA_reach, fromB (.txo 33 txB 0), by decide, rfl⟩

example : outcome (runA.sent ++ runA.got) = .pair .near := by decide

/-- FP6: the reader accepts A's record, pinned to keys 1 and 2, with NEAR. -/
def recA : Record Nat := { pkA := 1, pkB := 2, rA := 3, rB := 4, ctx := 0, msgs := runA.sent ++ runA.got }

example : verify toyC 1 2 recA = some (7, .pair .near) := by decide

/-- And rejects it pinned to other keys. -/
example : verify toyC 1 3 recA = none := by decide

/-- And rejects it with a message for attempt 2 added (only attempts 0 and 1 exist). -/
example : verify toyC 1 2 { recA with msgs := recA.msgs ++
    [⟨{ sid := 7, role := .B, attempt := 2, seen := [], body := .fail true 0 }, 0⟩] } = none := by
  decide

/-- A final `FAIL` from A for attempt 0 makes the record NOT_NEAR. D can't then append its own
attempt-1 `SEEDC` naming that `FAIL` to turn it into incomplete: attempt 1 needs two retry `FAIL`s. -/
def finalA : Signed Nat := ⟨{ sid := 7, role := .A, attempt := 0, seen := [7], body := .fail false 2 }, 0⟩

example : verify toyC 1 2 { recA with msgs := recA.msgs ++ [finalA] } = some (7, .fail .A 2) := by
  decide

example : verify toyC 1 2 { recA with msgs := recA.msgs ++ [finalA,
    ⟨{ sid := 7, role := .B, attempt := 1, seen := [7], body := .seedc 7 48000 }, 0⟩] } = none := by
  decide

/-- A partner retry `FAIL` before opening is answered with the device's own retry `FAIL`. -/
example : has (run toyC cfgA St.init [.confirm, .send .seedc locA, .recv (fromB (.fail true 0))]).sent
    (.A, 0, .fail) = true := by decide

/-- Before the confirm tap, a partner message is dropped and nothing is signed. The message
passes every other envelope check (`seen = []`, no answer needed) and fails its body check (rate
1), so without the confirm guard A would sign a final `FAIL` here. -/
example : (run toyC cfgA St.init
    [.recv ⟨{ sid := 7, role := .B, attempt := 0, seen := [], body := .seedc 7 1 }, 0⟩]).sent = [] := by
  decide

/-- The reader rejects a `TIME` signed by B: only A sends one (F4). -/
example : verify toyC 1 2 { recA with msgs := recA.msgs ++
    [⟨{ sid := 7, role := .B, attempt := 0, seen := [7], body := .time 0 }, 0⟩] } = none := by
  decide

/-! ## The verdict math against `verdict.py`

The same inputs through `server/pop/verdict.py` (`decide (flight_exact ...)`) gave: 168 too far,
167 NEAR, -55 NEAR, -56 impossible at 48 kHz; mixed rates 44100/48000 NEAR at 1000/1000 and too
far at 2000/1000. -/

example : flight 1168 48000 1000 48000 = .tooFar := by decide
example : flight 1167 48000 1000 48000 = .near := by decide
example : flight 945 48000 1000 48000 = .near := by decide
example : flight 944 48000 1000 48000 = .impossible := by decide
example : flight 1000 44100 1000 48000 = .near := by decide
example : flight 2000 44100 1000 48000 = .tooFar := by decide

/-! ## HASH can hold: a free hash -/

inductive Dg where
  | mk (p : Pre Dg)

noncomputable instance : DecidableEq Dg := fun a b => Classical.propDecidable (a = b)

noncomputable def freeC : Crypto Dg where
  H := Dg.mk
  sign _ _ := 0
  verify _ _ _ := true
  signTx _ _ := 0
  verifyTx _ _ _ := true
  codes a _ _ := a

theorem freeC_hash : freeC.HashInj := fun _ _ h => Dg.mk.inj h

/-- SIG can hold too: with a `verify` that accepts nothing, every key is unforgeable for any set. -/
example (pk : Nat) (S : Msg Nat → Prop) : ({ toyC with verify := fun _ _ _ => false } : Crypto Nat).Unforgeable pk S :=
  fun _ _ h => by cases h

end ProtoFv
