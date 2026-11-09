import ServerFv.X1SessionDefs

/-!
# X1 as a session result (Known gap 4): the two commits

Two step lemmas for the plan of `X1SessionDefs.lean`: the host's commit at `T+4310` takes `d5` to
`d6`, and the guest's commit at `T+4311` takes `d6` to `d7`.

**What this file pins.** For any setting `e` and any plan `P`, `step` on `d5` with the request
`X1Plan.reqComA` (the host's base64 commit and signature) at clock `T+4310` stores exactly `d6`: the
host's commit row is `cdA` (its strings, the hash of its commit bytes, its `rec_`, `T+4310`, and the
server's `code_commit` for the host's arm when it is v2), the host is marked committed, `seq` is 7.
The same for the guest at `T+4311`, from `d6` to exactly `d7`. On the way it pins that `load` changes
nothing at these clocks, that the sender's role is found, that the base64 strings decode, that the
commit decodes to the signer's own commit and its signature checks against the enrolled key, that the
role, attempt, nonce and version match, that neither side had committed yet, and that the clock is
past the gate `t0 + 1200 = T+4211`.

**What it does not pin.** It says nothing about the response (`_partner_bed`). It does not show that
`d5` or `d6` are reached; the other step lemmas and `run_reachable` do that. The commit times are one
fixed pick. Nothing here is about sound (CN1).
-/

namespace ServerFv
namespace Machine
namespace X1Plan

variable {B D : Type} [DecidableEq B] [DecidableEq D]
variable {e : Env B D} {nonce sid : B} (P : X1Plan e nonce sid)

omit [DecidableEq B] [DecidableEq D] in
/-- `load` at `T + n` changes nothing on a `started` document created at `T` with `t0 = T + 3011`,
for `n ≤ 23011` (the transcript deadline `t0 + 20000`, and under the 600 s age cap). -/
theorem load_started {s : Doc B D} (n : ℕ) (hs : s.state = .started) (hc : s.created_ms = P.T)
    (ht : s.t0_ms = some (P.T + 3011)) (hn : n ≤ 23011) : load e (P.W n) s = s := by
  simp only [load, _expire, hs, W, hc, ht, live]
  simp only [reduceCtorEq, false_and, ite_false, true_and, Nat.add_sub_cancel_left]
  rw [if_neg (by simp only [K.SESSION_MAX_AGE_S]; omega),
    if_neg (by simp only [K.TRANSCRIPT_DEADLINE_S, Option.getD_some]; omega)]

omit [DecidableEq B] [DecidableEq D] in
/-- The fields of `d5` that the host's commit reads. -/
theorem d5_facts :
    P.d5.state = .started ∧ P.d5.attempt = 0 ∧ P.d5.created_ms = P.T ∧
    P.d5.host_device_id = P.dA ∧ P.d5.guest_device_id = some P.dB ∧
    P.d5.t0_ms = some (P.T + 3011) ∧ P.d5.nonce_hex = nonce ∧ P.d5.committed = _flags ∧
    _popt P.d5 .A = P.sA.version ∧ P.d5.seq = 6 := by
  exact ⟨rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl⟩

/-- **The host's commit.** At `T+4310`, on `d5`, the commit request of `reqComA` stores exactly `d6`. -/
theorem step_commitA : (step e (P.W 4310) P.reqComA P.d5).1 = P.d6 := by
  obtain ⟨hst, hat, hcr, hho, hgu, ht0, hno, hcom, hpo, hseq⟩ := P.d5_facts
  obtain ⟨hdec, hver, -, -⟩ := P.hRA
  obtain ⟨hpkA, -, -, -⟩ := P.hpk
  have hload := P.load_started 4310 hst hcr ht0 (by omega)
  have hrole : role_of P.d5 P.dA = some .A := by simp [role_of, hho]
  have hsig : e.p.verify_raw (e.pk P.dA) P.sA.commit_raw P.sA.commit_sig = true := hpkA ▸ hver
  have hgate : ¬ (P.W 4310).now < P.d5.t0_ms.getD 0 + K.COMMIT_GATE_MS := by
    simp [W, ht0, K.COMMIT_GATE_MS]
  simp only [step, reqComA, opReq, hload, hrole, handle, commit, hst, P.hcbA, P.hsbA, hdec, hsig,
    Side.commit, hat, hno, hpo, hcom, hgate, _flags, ne_eq, not_true_eq_false, or_self,
    ite_false, Bool.false_eq_true]
  rfl

omit [DecidableEq B] [DecidableEq D] in
/-- The fields of `d6` that the guest's commit reads. -/
theorem d6_facts :
    P.d6.state = .started ∧ P.d6.attempt = 0 ∧ P.d6.created_ms = P.T ∧
    P.d6.host_device_id = P.dA ∧ P.d6.guest_device_id = some P.dB ∧
    P.d6.t0_ms = some (P.T + 3011) ∧ P.d6.nonce_hex = nonce ∧ P.d6.committed .B = false ∧
    _popt P.d6 .B = P.sB.version ∧ P.d6.seq = 7 := by
  exact ⟨rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl⟩

/-- **The guest's commit.** At `T+4311`, on `d6`, the commit request of `reqComB` stores exactly `d7`. -/
theorem step_commitB : (step e (P.W 4311) P.reqComB P.d6).1 = P.d7 := by
  obtain ⟨hst, hat, hcr, hho, hgu, ht0, hno, hcom, hpo, hseq⟩ := P.d6_facts
  obtain ⟨hdec, hver, -, -⟩ := P.hRB
  obtain ⟨-, -, hpkB, -⟩ := P.hpk
  have hload := P.load_started 4311 hst hcr ht0 (by omega)
  have hrole : role_of P.d6 P.dB = some .B := by
    simp [role_of, hho, hgu, P.hdev.symm]
  have hsig : e.p.verify_raw (e.pk P.dB) P.sB.commit_raw P.sB.commit_sig = true := hpkB ▸ hver
  have hgate : ¬ (P.W 4311).now < P.d6.t0_ms.getD 0 + K.COMMIT_GATE_MS := by
    simp [W, ht0, K.COMMIT_GATE_MS]
  simp only [step, reqComB, opReq, hload, hrole, handle, commit, hst, P.hcbB, P.hsbB, hdec, hsig,
    Side.commit, hat, hno, hpo, hcom, hgate, ne_eq, not_true_eq_false, or_self,
    ite_false, Bool.false_eq_true]
  rfl

end X1Plan

#print axioms X1Plan.step_commitA
#print axioms X1Plan.step_commitB

end Machine
end ServerFv
