import ProtoFv.FP1Order
import ProtoFv.FP2Code
import ProtoFv.FP3Blind
import ProtoFv.FP4Fresh
import ProtoFv.FP5Agree
import ProtoFv.FP6Reader
import ProtoFv.Retry

/-!
# The theorems are not vacuous

One concrete run of an honest A. B's messages are written by hand (B could be D: the device takes
any message). The run reaches a state where A has signed every message of attempt 0 and accepted
all of B's. Each FP gets an example that its hypotheses hold in that state, and the reader's
`verify` accepts the log with NEAR.

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
    codeCommit := 7, selfOs := 0, gap := 1000 }

def locA : Local := { root := 6, selfOs := 0, gap := 1000, why := 0 }

def inputsA : List (Input Nat) :=
  [ .confirm,
    .send .seedHash locA, .recv (fromB (.seedHash 7 48000)),
    .send .salt locA, .recv (fromB (.salt 31)),
    .send .time locA, .tick 7000,
    .send .recHash locA, .recv (fromB (.recHash 5)),
    .send .seedVal locA, .recv (fromB (.seedVal 32)),
    .send .gapHash locA, .recv (fromB (.gapHash 7)),
    .send .gapVal locA, .recv (fromB (.gapVal 33 txB 0)) ]

def runA : St Nat := run toyC cfgA St.init inputsA

theorem runA_reach : Reach toyC cfgA runA := reach_run toyC cfgA .init inputsA

/-- A signed its 7 messages of attempt 0 and accepted all 6 of B's (B sends no `TIME`). -/
example : runA.sent.length = 7 ∧ runA.got.length = 6 ∧ runA.done = false := by decide

theorem slot_of {l : List (Signed Nat)} {x} (h : has l x = true) :
    ∃ s ∈ l, s.slot = x := has_iff.1 h

/-- FP1: a reachable state with a signed `SEED_VALUE`. -/
example : ∃ st : St Nat, Reach toyC cfgA st ∧ ∃ x ∈ st.sent, x.msg.body.tag = .seedVal := by
  obtain ⟨x, hx, he⟩ := slot_of (show has runA.sent (.A, 0, .seedVal) = true by decide)
  exact ⟨runA, runA_reach, x, hx, by simp [Signed.slot] at he; exact he.2.2⟩

/-- FP2: a reachable state with an accepted partner `SEED_VALUE` and a signed `SALT`. -/
example : ∃ st : St Nat, Reach toyC cfgA st ∧ (∃ x ∈ st.got, x.msg.body = .seedVal 32) ∧
    ∃ x ∈ st.sent, x.msg.body.tag = .salt := by
  obtain ⟨y, hy, hye⟩ := slot_of (show has runA.sent (.A, 0, .salt) = true by decide)
  refine ⟨runA, runA_reach, ⟨fromB (.seedVal 32), by decide, rfl⟩, y, hy, ?_⟩
  simp [Signed.slot] at hye; exact hye.2.2

/-- FP3: a reachable state with a signed `GAP_VALUE`. -/
example : ∃ st : St Nat, Reach toyC cfgA st ∧ ∃ x ∈ st.sent, x.msg.body.tag = .gapVal := by
  obtain ⟨x, hx, he⟩ := slot_of (show has runA.sent (.A, 0, .gapVal) = true by decide)
  exact ⟨runA, runA_reach, x, hx, by simp [Signed.slot] at he; exact he.2.2⟩

/-- FP4: a reachable state with accepted messages. -/
example : ∃ st : St Nat, Reach toyC cfgA st ∧ st.got ≠ [] :=
  ⟨runA, runA_reach, by decide⟩

/-- FP5 (b): a reachable state with an accepted partner `GAP_VALUE`. (a): the outcome is the pair's. -/
example : ∃ st : St Nat, Reach toyC cfgA st ∧ ∃ x ∈ st.got, x.msg.body = .gapVal 33 txB 0 :=
  ⟨runA, runA_reach, fromB (.gapVal 33 txB 0), by decide, rfl⟩

example : outcome (runA.sent ++ runA.got) = .pair .near := by decide

/-- FP6: the reader accepts A's log, pinned to keys 1 and 2, with NEAR. -/
def logA : Log Nat := { pkA := 1, pkB := 2, rA := 3, rB := 4, ctx := 0, msgs := runA.sent ++ runA.got }

example : verify toyC 1 2 logA = some (7, .pair .near) := by decide

/-- And rejects it pinned to other keys. -/
example : verify toyC 1 3 logA = none := by decide

/-- And rejects it with a message for attempt 2 added (only attempts 0 and 1 exist). -/
example : verify toyC 1 2 { logA with msgs := logA.msgs ++
    [⟨{ sid := 7, role := .B, attempt := 2, seen := [], body := .fail true 0 }, 0⟩] } = none := by
  decide

/-- A final `FAIL` from A for attempt 0 makes the log NOT_NEAR. D can't then append its own
attempt-1 `SEED_HASH` naming that `FAIL` to turn it into incomplete: attempt 1 needs two retry `FAIL`s. -/
def finalA : Signed Nat := ⟨{ sid := 7, role := .A, attempt := 0, seen := [7], body := .fail false 2 }, 0⟩

example : verify toyC 1 2 { logA with msgs := logA.msgs ++ [finalA] } = some (7, .fail .A 2) := by
  decide

example : verify toyC 1 2 { logA with msgs := logA.msgs ++ [finalA,
    ⟨{ sid := 7, role := .B, attempt := 1, seen := [7], body := .seedHash 7 48000 }, 0⟩] } = none := by
  decide

/-- A partner retry `FAIL` before the device sent its `GAP_VALUE` is answered with the device's own retry `FAIL`. -/
example : has (run toyC cfgA St.init [.confirm, .send .seedHash locA, .recv (fromB (.fail true 0))]).sent
    (.A, 0, .fail) = true := by decide

/-! ## The retry after both `GAP_VALUE`s (spec F10, the v1 rule kept on 2026-11-11) -/

/-- B's transcript with a gap that makes the pair `impossible_flight`: A has 1000, B has 1100. -/
def txBfar : Tx Nat := { txB with gap := 1100 }

/-- The same run as `inputsA`, but B's `GAP_VALUE` holds `txBfar`. Then A signs a retry `FAIL`,
accepts B's retry `FAIL`, and moves on. -/
def inputsRetry : List (Input Nat) :=
  inputsA.dropLast ++
    [ .recv (fromB (.gapVal 33 txBfar 0)), .send .fail locA, .recv (fromB (.fail true 0)), .advance ]

/-- With an `impossible_flight` pair, A reaches attempt 1 although it signed `GAP_VALUE` for 0. -/
example : (run toyC cfgA St.init inputsRetry).k = 1 ∧
    has (run toyC cfgA St.init inputsRetry).sent (.A, 0, .gapVal) = true ∧
    has (run toyC cfgA St.init inputsRetry).sent (.A, 0, .fail) = true := by decide

/-- The same pair, before any partner `FAIL`: A signs its own retry `FAIL` (the `act` path). -/
example : has (run toyC cfgA St.init
    (inputsA.dropLast ++ [.recv (fromB (.gapVal 33 txBfar 0)), .send .fail locA])).sent
    (.A, 0, .fail) = true := by decide

/-- With a NEAR pair, A signs no retry `FAIL` after its own `GAP_VALUE`. -/
example : (run toyC cfgA runA [.send .fail locA]).sent.length = 7 := by decide

/-- With a NEAR pair, a partner retry `FAIL` is accepted but not answered, and the attempt stays. -/
example : (run toyC cfgA runA [.recv (fromB (.fail true 0)), .advance]).sent.length = 7 ∧
    (run toyC cfgA runA [.recv (fromB (.fail true 0)), .advance]).k = 0 := by decide

/-- The answer path: B's `GAP_VALUE` makes the pair `impossible_flight`, then B's retry `FAIL`
comes first. A answers it with its own retry `FAIL` and moves on. -/
def inputsAnswer : List (Input Nat) :=
  inputsA.dropLast ++ [ .recv (fromB (.gapVal 33 txBfar 0)), .recv (fromB (.fail true 0)), .advance ]

example : (run toyC cfgA St.init inputsAnswer).k = 1 ∧
    has (run toyC cfgA St.init inputsAnswer).sent (.A, 0, .fail) = true := by decide

/-- A self timing mismatch also retries after both `GAP_VALUE`s. Both gaps are 1000, but B's
`self_os_delta` is 2401 samples at 48 kHz, just over 50 ms. So `combine` gives `selfTs .B`. -/
def txBts : Tx Nat := { txB with selfOs := 2401 }

example : runA.tx.map (combine · txBts) = some (.selfTs .B) := by decide

/-- On that pair A reaches attempt 1 by its own retry `FAIL`, and by answering B's. -/
example : (run toyC cfgA St.init (inputsA.dropLast ++
      [.recv (fromB (.gapVal 33 txBts 0)), .send .fail locA, .recv (fromB (.fail true 0)), .advance])).k = 1 ∧
    (run toyC cfgA St.init (inputsA.dropLast ++
      [.recv (fromB (.gapVal 33 txBts 0)), .recv (fromB (.fail true 0)), .advance])).k = 1 := by decide

/-- A's own offset out of range (`selfTs .A`): A signs its transcript with `self_os_delta` 2401,
B's is fine. A reaches attempt 1 too. -/
def locAts : Local := { locA with selfOs := 2401 }

example : (run toyC cfgA St.init
    ((inputsA.dropLast.map (fun i => match i with | .send t _ => .send t locAts | j => j)) ++
      [.recv (fromB (.gapVal 33 txB 0)), .send .fail locA, .recv (fromB (.fail true 0)), .advance])).k = 1 := by
  decide

/-! ## A log D hands over can hide the forced retry (spec K3)

D runs the forced retry of `inputsRetry`, then a NEAR attempt 1. In the log it shows a reader, it
leaves out A's `GAP_VALUE` for attempt 0. `verify` doesn't ask that a log is complete, so the log
still verifies with NEAR. Attempt 0 then looks like a run where A failed before it sent its gap.
With real crypto this needs only that no message of D names A's `GAP_VALUE(0)` in `seen`, and D
picks what its own messages name. -/

def fromB1 (b : Body Nat) : Signed Nat :=
  ⟨{ sid := 7, role := .B, attempt := 1, seen := [7], body := b }, 0⟩

def inputs1 : List (Input Nat) :=
  [ .send .seedHash locA, .recv (fromB1 (.seedHash 7 48000)),
    .send .salt locA, .recv (fromB1 (.salt 31)),
    .send .time locA, .tick 7000,
    .send .recHash locA, .recv (fromB1 (.recHash 5)),
    .send .seedVal locA, .recv (fromB1 (.seedVal 32)),
    .send .gapHash locA, .recv (fromB1 (.gapHash 7)),
    .send .gapVal locA, .recv (fromB1 (.gapVal 33 { txB with attempt := 1 } 0)) ]

def runHidden : St Nat := run toyC cfgA St.init (inputsRetry ++ inputs1)

def logHidden : Log Nat :=
  { logA with msgs := runHidden.sent.filter (fun s => !(s.slot == ((.A, 0, .gapVal) : Role × Nat × Tag)))
                      ++ runHidden.got }

set_option maxRecDepth 4000 in
example : has logHidden.msgs (.A, 0, .gapVal) = false := by decide

set_option maxRecDepth 4000 in
example : verify toyC 1 2 logHidden = some (7, .pair .near) := by decide

/-- `fp3_next_attempt_reach` and `fp5_retry_fail_reach` are not vacuous: a reachable state past
attempt 0 with an own `GAP_VALUE` and an own retry `FAIL` for 0. -/
example : ∃ st : St Nat, Reach toyC cfgA st ∧ 0 < st.k ∧ has st.sent (.A, 0, .gapVal) = true ∧
    ∃ x ∈ st.sent, x.msg.body = .fail true 0 ∧ x.msg.attempt = 0 :=
  ⟨_, reach_run toyC cfgA .init inputsRetry, by decide, by decide, by decide⟩

/-- Before the confirm tap, a partner message is dropped and nothing is signed. The message
passes every other envelope check (`seen = []`, no answer needed) and fails its body check (rate
1), so without the confirm guard A would sign a final `FAIL` here. -/
example : (run toyC cfgA St.init
    [.recv ⟨{ sid := 7, role := .B, attempt := 0, seen := [], body := .seedHash 7 1 }, 0⟩]).sent = [] := by
  decide

/-- The reader rejects a `TIME` signed by B: only A sends one (F4). -/
example : verify toyC 1 2 { logA with msgs := logA.msgs ++
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
