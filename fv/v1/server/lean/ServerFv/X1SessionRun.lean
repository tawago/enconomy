import ServerFv.X1SessionOpen
import ServerFv.X1SessionArm
import ServerFv.X1SessionCommit
import ServerFv.X1SessionTx
import ServerFv.X1SessionVerdict

/-!
# X1 as a session run: the plan reaches NEAR (Known gap 4)

The step lemmas in `X1SessionOpen`, `X1SessionArm`, `X1SessionCommit`, `X1SessionTx` and
`X1SessionVerdict` each show one request takes `d_k` to `d_{k+1}`. This file chains them: the nine
requests of `X1Plan.reqs`, run from `d0`, end on `d9`, and `d9` is a `Reachable` document at
`T + 4411` whose stored record is a NEAR verdict with the exact flight and both devices' rows.

**What it pins.** For any `X1Plan` (any setting `e`, any signers' picks meeting the plan's
hypotheses), the model of `sessions.py` at 9db1490 can reach a finished session whose record says
NEAR, attempt 0, no reason, `flight_cm = flight_exact ..`, and device rows holding the enrolled ids,
their keys, the armed rates, the transcript halves, the armed versions and the stored calibration.

**What it does not pin.** That such a plan exists (a separate result), anything about other
schedules, or anything about sound: the verdict is a function of signed numbers, not of distance
(CN1).
-/

namespace ServerFv
namespace Machine
namespace X1Plan

variable {B D : Type} [DecidableEq B] [DecidableEq D]
variable {e : Env B D} {nonce sid : B} (P : X1Plan e nonce sid)

/-- **The nine requests of the plan, run from `d0`, end on `d9`.** Pure chaining of the nine step
lemmas; it pins the end document, not the responses. -/
theorem run_d9 : runL e P.d0 P.reqs = P.d9 := by
  simp only [reqs, runL_cons, runL_nil, reqJoin, reqConfA, reqConfB, opReq]
  rw [P.step_join, P.step_confA, P.step_confB, P.step_armA, P.step_armB, P.step_commitA,
    P.step_commitB, P.step_txA, P.step_txB]

/-- **The plan reaches a NEAR record.** `d9` is `Reachable` at clock `T + 4411` from a `create` at
`T`, its state is `done`, and its stored record says NEAR, no reason, attempt 0, the exact flight of
the two halves, and device rows `⟨id, enrolled key, armed rate, transcript half, version, cal⟩` for
host `dA` and guest `dB`. It does not say any other run gives NEAR, nor that the flight is a
distance. -/
theorem reaches_near :
    Reachable e (P.T + 4411) P.d9 ∧ P.d9.state = .done ∧
    ∃ rc, P.d9.result = some rc ∧ rc.verdict = .NEAR ∧ rc.reason = none ∧ rc.attempt = 0 ∧
      rc.flight_cm = some (flight_exact P.sA.half P.sA.sample_rate P.sB.half P.sB.sample_rate) ∧
      rc.devices .A = some ⟨P.dA, e.pk P.dA, some P.sA.sample_rate, some P.sA.half,
        P.sA.version, P.cal P.dA⟩ ∧
      rc.devices .B = some ⟨P.dB, e.pk P.dB, some P.sB.sample_rate, some P.sB.half,
        P.sB.version, P.cal P.dB⟩ := by
  refine ⟨?_, rfl, _, rfl, rfl, rfl, rfl, rfl, rfl, rfl⟩
  have h := P.run_reachable
  rwa [P.run_d9] at h

end X1Plan

#print axioms X1Plan.run_d9
#print axioms X1Plan.reaches_near

end Machine
end ServerFv
