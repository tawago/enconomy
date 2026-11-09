import ServerFv.X1SessionDefs

/-!
# X1 as a session result (Known gap 4): the guest's transcript and the verdict

One step lemma for the plan of `X1SessionDefs.lean`: the guest's transcript at `T+4411` takes `d8`
to `d9`, which is `_finalize` with verdict NEAR, no reason, and flight `flight_exact` of the two
halves and rates.

**What this file pins.** For any setting `e` and any plan `P`, `step` on `d8` with the request
`X1Plan.reqTxB` (the guest's base64 transcript and signature) at clock `T+4411` stores exactly `d9`.
On the way it pins:
* `load` changes nothing at `T+4411` (before the deadline `t0 + 20000 = T+23011`, under the 600 s cap);
* the sender `dB` is role B;
* the transcript is not a stale one (its attempt is 0, the session's is 0);
* the guest had not submitted, and had committed;
* `checkNew` accepts the guest's bytes against the enrolled keys, its commit row and its arm row, and
  returns the guest's own transcript (`txB_checkNew`);
* both stored transcripts decode back to the two signers' transcripts (`txB_stored`);
* `combine` on them, with the `cal_us` snapshots of the two arm rows (`cal dA` and `cal dB`), gives
  exactly `⟨some f, some NEAR, none, none⟩` with `f = flight_exact ..` (`txB_combine`).

**What it does not pin.** It says nothing about the response. It does not show that `d8` is reached;
the other step lemmas and `run_reachable` do that. It is one fixed clock. Nothing here is about sound
(CN1): the NEAR comes from numbers two signers picked.
-/

namespace ServerFv
namespace Machine
namespace X1Plan

variable {B D : Type} [DecidableEq B] [DecidableEq D]
variable {e : Env B D} {nonce sid : B} (P : X1Plan e nonce sid)

set_option linter.unusedSectionVars false

/-- The host's transcript as the signer wrote it. -/
abbrev tA : Transcript B := P.sA.transcript e.p.sha256 .A 0 nonce

/-- The guest's transcript as the signer wrote it. -/
abbrev tB : Transcript B := P.sB.transcript e.p.sha256 .B 0 nonce

/-- The document right after the guest's transcript is stored, before `afterStore`. -/
abbrev s9 : Doc B D := txStore P.d8 .B P.tdB

omit [DecidableEq B] [DecidableEq D] in
/-- The fields of `d8` that the guest's transcript reads. Each one unfolds by definition. -/
theorem txB_d8_facts :
    P.d8.state = .started ∧ P.d8.attempt = 0 ∧ P.d8.created_ms = P.T ∧
    P.d8.host_device_id = P.dA ∧ P.d8.guest_device_id = some P.dB ∧
    P.d8.t0_ms = some (P.T + 3011) ∧ P.d8.nonce_hex = nonce ∧ P.d8.seed_hex = P.seed ∧
    P.d8.submitted .A = true ∧ P.d8.submitted .B = false ∧ P.d8.committed .B = true ∧
    (P.d8.per_role .A).tx = some P.tdA ∧
    (P.d8.per_role .A).arm = some ⟨P.sA.sample_rate, P.T + 10, P.sA.version, P.cal P.dA⟩ ∧
    (P.d8.per_role .B).arm = some ⟨P.sB.sample_rate, P.T + 11, P.sB.version, P.cal P.dB⟩ ∧
    (P.d8.per_role .B).commit = some P.cdB :=
  ⟨rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl⟩

/-- `load` at `T+4411` leaves `d8` alone. -/
theorem txB_load : load e (P.W 4411) P.d8 = P.d8 := by
  obtain ⟨hst, -, hcr, -, -, ht0, -⟩ := P.txB_d8_facts
  simp only [load, _expire, hst, W, hcr, ht0, live]
  simp only [reduceCtorEq, false_and, ite_false, true_and, gt_iff_lt, add_tsub_cancel_left, Option.getD_some]
  rw [ite_eq_right (by norm_num [K.SESSION_MAX_AGE_S]), ite_eq_right (by simp only [K.TRANSCRIPT_DEADLINE_S]; omega)]

/-- The guest's transcript is not a stale one: its attempt 0 is not below the session's 0. -/
theorem txB_not_stale : staleTranscript e P.d8 .B P.tbB P.tsB = false := by
  obtain ⟨-, hat, -⟩ := P.txB_d8_facts
  obtain ⟨-, -, hdec, -⟩ := P.hRB
  simp [staleTranscript, P.htbB, P.htsB, hdec, hat, Side.transcript]

/-- **The guest's bytes pass `checkNew`.** Against the enrolled keys (`e.pk dB` for the sender, `e.pk dA`
for the partner), its commit row (the hash of its commit bytes, its `rec_`), its arm row (its rate,
its version) and, in v2, the server's `code_commit` for its codes, `checkNew` gives back the raw bytes
and the guest's own transcript. -/
theorem txB_checkNew :
    checkNew e P.d8 .B P.dB P.tbB P.tsB (e.pk P.dA) = .ok (P.sB.raw, P.tB) := by
  obtain ⟨-, hat, -, -, -, -, hno, hseed, -, -, -, -, -, harmB, hcomB⟩ := P.txB_d8_facts
  obtain ⟨-, -, hdec, hsig⟩ := P.hRB
  obtain ⟨-, -, hpkB, hpkB'⟩ := P.hpk
  have hpo : _popt P.d8 .B = P.sB.version := by simp [_popt, harmB]
  have hcc : _code_commit e P.d8 .B =
      e.code_commit P.sB.sample_rate ⟨P.seed, .B, 0⟩ ⟨P.seed, .A, 0⟩ := by
    simp [_code_commit, harmB, _code, hseed, hat, OTHER]
  unfold checkNew
  simp only [P.htbB, P.htsB, hpo, hcomB, harmB, hno, hat, Option.map_some]
  rw [(check_transcript_ok_iff _ _ _ _ _ _ _ _ _ _ _ _ _ _).2]
  refine ⟨hdec, hpkB ▸ hsig, rfl, hpkB, rfl, rfl, rfl, hpkB', ?_, P.hrB1, P.hrB2, rfl, rfl, ?_⟩
  · intro _; rfl
  · intro hv
    refine ⟨by simp [Side.transcript, hv], ?_⟩
    intro _
    simp [Side.transcript, hv, hcc, P.hccB hv]

/-- The two stored transcripts decode back to the two signers' transcripts. -/
theorem txB_stored : stored e P.s9 .A = some P.tA ∧ stored e P.s9 .B = some P.tB := by
  obtain ⟨-, -, -, -, -, -, -, -, -, -, -, htxA, -⟩ := P.txB_d8_facts
  obtain ⟨-, -, hdA, -⟩ := P.hRA
  obtain ⟨-, -, hdB, -⟩ := P.hRB
  constructor
  · exact stored_eq (td := P.tdA) (by simp [s9, txStore, upd, htxA]) P.htbA hdA
  · exact stored_eq (td := P.tdB) (by simp [s9, txStore, upd]) P.htbB hdB

/-- The `cal_us` map after the store: the snapshots `cal dA` and `cal dB` of the two arm rows. -/
theorem txB_calMap :
    calMap P.s9 = some (fun r : Role => match r with | .A => some (P.cal P.dA) | .B => some (P.cal P.dB)) := by
  obtain ⟨-, -, -, -, -, -, -, -, -, -, -, -, harmA, harmB, -⟩ := P.txB_d8_facts
  simp only [calMap, s9, txStore, Option.some.injEq]
  funext r
  cases r <;> simp [upd, harmA, harmB]

/-- **`combine` gives NEAR at the exact flight.** On the two signers' transcripts, with the snapshots
of the arm rows, `combine` returns the exact flight, NEAR, no reason, no `by`. It uses the pair checks
(roles, nonce, attempt, each names the other's enrolled key, the keys differ by `hkey`), the two self
checks (`hdA`, `hdB`), rates not zero, and `V2` on `-20 < f < 60`. -/
theorem txB_combine :
    combine P.tA P.tB (calMap P.s9) =
      .ok ⟨some (flight_exact P.sA.half P.sA.sample_rate P.sB.half P.sB.sample_rate),
        some .NEAR, none, none⟩ := by
  obtain ⟨hpkA, hpkA', hpkB, hpkB'⟩ := P.hpk
  have hpair : pair P.tA P.tB :=
    ⟨rfl, rfl, rfl, rfl, by simp [Side.transcript, hpkA', hpkB], by simp [Side.transcript, hpkB', hpkA],
      by simpa [Side.transcript, hpkA, hpkB] using P.hkey⟩
  have hsA : self_check P.tA (calMap P.s9) = true := by
    rw [P.txB_calMap]
    simpa [self_check, cal_for, version_of, Side.transcript] using P.hdA
  have hsB : self_check P.tB (calMap P.s9) = true := by
    rw [P.txB_calMap]
    simpa [self_check, cal_for, version_of, Side.transcript] using P.hdB
  have hnear := ((V2 (flight_exact P.sA.half P.sA.sample_rate P.sB.half P.sB.sample_rate)).2.2.1).2
    ⟨P.hf1, P.hf2⟩
  rw [combine_measured hpair hsA hsB (by simp [Side.transcript]; have := P.hrA1; omega)
    (by simp [Side.transcript]; have := P.hrB1; omega)]
  simp [Side.transcript, hnear]

/-- `afterStore` on the stored pair finalizes as NEAR at the exact flight: exactly `d9`. -/
theorem txB_afterStore : (afterStore e (P.W 4411) P.d8 P.s9).1 = P.d9 := by
  obtain ⟨-, -, -, -, -, -, -, -, hsubA, -⟩ := P.txB_d8_facts
  obtain ⟨hA, hB⟩ := P.txB_stored
  have hall : all2 P.s9.submitted = true := by simp [all2, s9, txStore, upd, hsubA]
  simp only [afterStore, hall, hA, hB, P.txB_combine]
  rfl

/-- **The guest's transcript.** At `T+4411`, on `d8`, the transcript request of `reqTxB` stores exactly
`d9`: both transcripts in, state `done`, the record says NEAR, no reason, flight
`flight_exact sA.half sA.sample_rate sB.half sB.sample_rate`. -/
theorem step_txB : (step e (P.W 4411) P.reqTxB P.d8).1 = P.d9 := by
  obtain ⟨hst, -, -, hho, hgu, -, -, -, -, hsubB, hcomB, -⟩ := P.txB_d8_facts
  have hrole : role_of P.d8 P.dB = some .B := by
    simp [role_of, hho, hgu, P.hdev.symm]
  have hpkA : _pk e P.d8 (OTHER .B) = some (e.pk P.dA) := by
    simp [_pk, OTHER, devId, hho]
  have htd : (⟨P.tbB, P.tsB, e.p.sha256 P.sB.raw, P.tB.half, P.tB.self_os_delta⟩ : TxData B) = P.tdB := by
    simp [tdB, Side.transcript]
  simp only [step, reqTxB, opReq, P.txB_load, hrole, handle, transcript, P.txB_not_stale, hst,
    hsubB, hcomB, hpkA, P.txB_checkNew, htd, Bool.false_eq_true, ↓reduceIte, ne_eq,
    not_true_eq_false]
  exact P.txB_afterStore

end X1Plan

#check @X1Plan.txB_checkNew
#check @X1Plan.txB_stored
#check @X1Plan.txB_calMap
#check @X1Plan.txB_combine
#check @X1Plan.txB_afterStore
#check @X1Plan.step_txB

#print axioms X1Plan.txB_checkNew
#print axioms X1Plan.txB_combine
#print axioms X1Plan.txB_afterStore
#print axioms X1Plan.step_txB

end Machine
end ServerFv
