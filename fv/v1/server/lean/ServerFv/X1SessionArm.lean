import ServerFv.X1SessionDefs

/-!
# X1 as a session result (Known gap 4): the two arms

Two step lemmas for the plan of `X1SessionDefs.lean`: the host's arm at `T+10` takes `d3` to `d4`,
and the guest's arm at `T+11` takes `d4` to `d5`.

**What this file pins.** For any setting `e` and any plan `P`, `step` on the stored document, with the
request `X1Plan.reqArmA` (attempt 0, the host's own rate, rtt 0, the host's own version) at clock
`T+10`, stores exactly `d4`: the host's arm row holds its rate, `T+10`, its version and the stored
calibration `cal dA`; only the host is armed; the state stays `confirmed`; `seq` is 5. The same for the
guest at `T+11`, which stores exactly `d5`: both armed, state `started`, `t0 = T+11+3000 = T+3011`,
`seq` 6. On the way it pins that `load` changes nothing at these clocks, that the sender's role is
found, and that the rate, rtt and version checks all pass.

**What it does not pin.** It says nothing about the response (`_arm_material`). The rtt is fixed at 0;
any value in 0..300 would pass too, but that is not proven here. It does not show that `d3` or `d4`
are reached; the other step lemmas and `run_reachable` do that. Nothing here is about sound.
-/

namespace ServerFv
namespace Machine
namespace X1Plan

variable {B D : Type} [DecidableEq B] [DecidableEq D]

set_option linter.unusedSectionVars false
variable {e : Env B D} {nonce sid : B} (P : X1Plan e nonce sid)

/-- A rate in 36000..96000, sent as an integer, passes `srArg` unchanged. -/
theorem srArg_int {sr : ℕ} (h1 : 36000 ≤ sr) (h2 : sr ≤ 96000) :
    srArg (.int (sr : ℤ)) = some sr := by
  simp only [srArg]
  split
  · simp
  · rename_i hc
    exact absurd ⟨by simp only [K.SR_MIN]; omega, by simp only [K.SR_MAX]; omega⟩ hc

/-- A version 1 or 2, sent as an integer, passes `poptArg` unchanged. -/
theorem poptArg_int {v : ℕ} (h : v = 1 ∨ v = 2) : poptArg (.int (v : ℤ)) = some v := by
  rcases h with h | h <;> subst h <;> rfl

/-- An rtt of 0 passes. -/
theorem rttOk_zero : rttOk (some 0) = true := by
  simp [rttOk]

/-- The fields of `d3` that the arm reads. -/
theorem d3_facts :
    P.d3.state = .confirmed ∧ P.d3.attempt = 0 ∧ P.d3.created_ms = P.T ∧
    P.d3.host_device_id = P.dA ∧ P.d3.guest_device_id = some P.dB ∧ P.d3.armed = _flags ∧
    P.d3.seq = 4 := by
  simp [d3, d2, d1, d0, create, _save, W]

/-- `load` at `T + n` changes nothing on a document in `confirmed` created at `T`, for `n ≤ 600000`. -/
theorem load_confirmed {s : Doc B D} (n : ℕ) (hs : s.state = .confirmed) (hc : s.created_ms = P.T)
    (hn : n ≤ 600000) : load e (P.W n) s = s := by
  simp only [load, _expire, hs, W, hc, live, K.SESSION_MAX_AGE_S]
  simp
  omega

/-- **The host's arm.** At `T+10`, on `d3`, the arm request of `reqArmA` stores exactly `d4`. -/
theorem step_armA : (step e (P.W 10) P.reqArmA P.d3).1 = P.d4 := by
  obtain ⟨hst, hat, hcr, hho, hgu, harm, hseq⟩ := P.d3_facts
  have hload := P.load_confirmed 10 hst hcr (by omega)
  have hrole : role_of P.d3 P.dA = some .A := by simp [role_of, hho]
  have hsr := srArg_int P.hrA1 P.hrA2
  have hpv := poptArg_int P.hvA
  simp only [step, reqArmA, opReq, hload, hrole, handle, arm, hst, hat, hsr, hpv, rttOk_zero, harm,
    devId, hho]
  simp [upd, _flags, all2, _save, d4, hseq, W, hst, hat, hho]

/-- The fields of `d4` that the arm reads. -/
theorem d4_facts :
    P.d4.state = .confirmed ∧ P.d4.attempt = 0 ∧ P.d4.created_ms = P.T ∧
    P.d4.host_device_id = P.dA ∧ P.d4.guest_device_id = some P.dB ∧
    P.d4.armed = upd _flags .A true ∧ P.d4.seq = 5 := by
  simp [d4, d3, d2, d1, d0, create, _save, W]

/-- **The guest's arm.** At `T+11`, on `d4`, the arm request of `reqArmB` stores exactly `d5`: both
armed, `started`, `t0 = T + 3011`. -/
theorem step_armB : (step e (P.W 11) P.reqArmB P.d4).1 = P.d5 := by
  obtain ⟨hst, hat, hcr, hho, hgu, harm, hseq⟩ := P.d4_facts
  have hload := P.load_confirmed 11 hst hcr (by omega)
  have hrole : role_of P.d4 P.dB = some .B := by
    simp [role_of, hho, hgu, P.hdev.symm]
  have hsr := srArg_int P.hrB1 P.hrB2
  have hpv := poptArg_int P.hvB
  have hnA : (upd (_flags : Role → Bool) .A true) .B = false := by simp [upd, _flags]
  simp only [step, reqArmB, opReq, hload, hrole, handle, arm, hst, hat, hsr, hpv, rttOk_zero, harm,
    devId, hgu, hnA]
  simp [upd, all2, _save, d5, hseq, W, T0_DELAY_MS, hat, hgu]

end X1Plan

#print axioms X1Plan.step_armA
#print axioms X1Plan.step_armB

end Machine
end ServerFv
