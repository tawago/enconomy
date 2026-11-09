import ServerFv.X1SessionDefs

/-!
# X1 as a session result (Known gap 4): the host's transcript

One step lemma for the plan of `X1SessionDefs.lean`: the host's transcript at `T+4410` takes `d7` to
`d8`.

**What this file pins.** For any setting `e` and any plan `P`, `step` on `d7` with the request
`X1Plan.reqTxA` (the host's base64 transcript and signature) at clock `T+4410` stores exactly `d8`:
the host's `tx` row holds the two strings, the hash of the decoded bytes, the host's `half` and
`self_os_delta`; only the host is marked submitted; the state stays `started`; `seq` goes up by one.
On the way it pins that `load` changes nothing at that clock, that the request is not taken as a stale
one (`Nat.blt 0 0 = false`), that the partner key read is the guest's enrolled key, and that
`checkNew` passes and returns the host's own bytes and transcript (`Side.transcript` at attempt 0 with
this nonce). For a v2 host this uses `hccA`: the `code_commit` in the transcript equals the server's
`_code_commit` for the stored rate and the codes of this seed. `check_txA_partner` shows the check
pins the partner key: any `pk'` it passes with is the guest's enrolled key.

**What it does not pin.** It says nothing about the response (`accepted`). It does not show `d7` is
reached; the other step lemmas and `run_reachable` do that. It does not cover a guest that sends first,
or a second send. It does not show an `X1Plan` exists; without one every statement here is about no
plan at all. Nothing here is about sound (CN1).
-/

namespace ServerFv
namespace Machine
namespace X1Plan

variable {B D : Type} [DecidableEq B] [DecidableEq D]
variable {e : Env B D} {nonce sid : B} (P : X1Plan e nonce sid)

omit [DecidableEq B] [DecidableEq D] in
/-- The fields of `d7` that the transcript route reads. Each one holds by unfolding alone. -/
theorem d7_facts :
    P.d7.state = .started ∧ P.d7.attempt = 0 ∧ P.d7.created_ms = P.T ∧
    P.d7.t0_ms = some (P.T + 3011) ∧ P.d7.host_device_id = P.dA ∧
    P.d7.guest_device_id = some P.dB ∧ P.d7.nonce_hex = nonce ∧ P.d7.seed_hex = P.seed ∧
    P.d7.submitted = _flags ∧ P.d7.committed .A = true ∧
    P.d7.per_role .A =
      ({ arm := some ⟨P.sA.sample_rate, P.T + 10, P.sA.version, P.cal P.dA⟩,
         commit := some P.cdA } : PerRole B) :=
  ⟨rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl⟩

omit [DecidableEq B] [DecidableEq D] in
/-- `load` at `T + n` changes nothing on a `started` document created at `T` with `t0 = T + 3011`,
for `n ≤ 23011` (the transcript deadline `t0 + 20000`, and under the 600 s age cap). The same fact
as `load_started` of `X1SessionCommit.lean`, under its own name so the two files stay apart. -/
theorem load_startedTx {s : Doc B D} (n : ℕ) (hs : s.state = .started) (hc : s.created_ms = P.T)
    (ht : s.t0_ms = some (P.T + 3011)) (hn : n ≤ 23011) : load e (P.W n) s = s := by
  simp only [load, _expire, hs, W, hc, ht, live]
  simp only [reduceCtorEq, false_and, ite_false, true_and, Nat.add_sub_cancel_left]
  rw [if_neg (by simp only [K.SESSION_MAX_AGE_S]; omega),
    if_neg (by simp only [K.TRANSCRIPT_DEADLINE_S, Option.getD_some]; omega)]

omit [DecidableEq B] [DecidableEq D] in
/-- The host's transcript is not taken as a stale one: it is for attempt 0, and so is `d7`. -/
theorem stale_txA : staleTranscript e P.d7 .A P.tbA P.tsA = false := by
  simp only [staleTranscript, P.htbA, P.htsA, P.hRA.2.2.1]
  rfl

omit [DecidableEq B] [DecidableEq D] in
/-- The partner key read for the host is the guest's enrolled key. -/
theorem pk_B : _pk e P.d7 .B = some (e.pk P.dB) := rfl

omit [DecidableEq D] in
/-- `check_transcript` with the values `d7` holds for the host, written out. -/
theorem check_txA_raw :
    check_transcript e.p P.sA.raw P.sA.sig .A (e.pk P.dA) (e.pk P.dB) nonce 0
      (some (e.p.sha256 P.sA.commit_raw)) (some P.sA.rec_) (some P.sA.sample_rate) P.sA.version
      (if P.sA.version = 2 then
        some (e.code_commit P.sA.sample_rate ⟨P.seed, .A, 0⟩ ⟨P.seed, .B, 0⟩) else none) =
      .ok (P.sA.transcript e.p.sha256 .A 0 nonce) := by
  obtain ⟨hps, hpp, -, -⟩ := P.hpk
  obtain ⟨-, -, hdt, hst⟩ := P.hRA
  have hsig : e.p.verify_raw (e.pk P.dA) P.sA.raw P.sA.sig = true := hps ▸ hst
  refine (check_transcript_ok_iff _ _ _ _ _ _ _ _ _ _ _ _ _ _).2
    ⟨hdt, hsig, rfl, hps, rfl, rfl, rfl, hpp, fun _ => rfl, P.hrA1, P.hrA2, rfl, rfl, ?_⟩
  intro hv
  refine ⟨?_, fun _ => ?_⟩
  · show (if P.sA.version = 2 then some (popt2_delta P.sA.sample_rate) else none) =
      some (popt2_delta P.sA.sample_rate)
    rw [if_pos hv]
  · show (if P.sA.version = 2 then P.sA.code_commit else none) =
      (if P.sA.version = 2 then
        some (e.code_commit P.sA.sample_rate ⟨P.seed, .A, 0⟩ ⟨P.seed, .B, 0⟩) else none)
    rw [if_pos hv, if_pos hv, P.hccA hv]

omit [DecidableEq D] in
/-- **The check of the host's transcript passes** and returns the host's bytes and the transcript of
`Side.transcript` at attempt 0 with this nonce. -/
theorem check_txA :
    checkNew e P.d7 .A P.dA P.tbA P.tsA (e.pk P.dB) =
      .ok (P.sA.raw, P.sA.transcript e.p.sha256 .A 0 nonce) := by
  have hct : check_transcript e.p P.sA.raw P.sA.sig .A (e.pk P.dA) (e.pk P.dB) P.d7.nonce_hex
      P.d7.attempt ((P.d7.per_role .A).commit.map (·.commit_sha256))
      ((P.d7.per_role .A).commit.map (·.rec_)) ((P.d7.per_role .A).arm.map (·.sample_rate))
      (_popt P.d7 .A) (if _popt P.d7 .A = 2 then some (_code_commit e P.d7 .A) else none) =
      .ok (P.sA.transcript e.p.sha256 .A 0 nonce) := P.check_txA_raw
  simp only [checkNew, P.htbA, P.htsA, hct]

omit [DecidableEq D] in
/-- **The check pins the partner key.** If `checkNew` on `d7` passes for the host's two strings with a
partner key `pk'`, then `pk'` is the guest's enrolled key: the key in the host's signed transcript is
compared with it. It does not say which other inputs the check reads. -/
theorem check_txA_partner {pk' : B} {r : B × Transcript B}
    (h : checkNew e P.d7 .A P.dA P.tbA P.tsA pk' = .ok r) : pk' = e.pk P.dB := by
  obtain ⟨-, hpp, -, -⟩ := P.hpk
  obtain ⟨-, -, hdt, -⟩ := P.hRA
  simp only [checkNew, P.htbA, P.htsA] at h
  split at h
  · rename_i t ht
    obtain ⟨hd, -, -, -, -, -, -, hpt, -⟩ := (check_transcript_ok_iff _ _ _ _ _ _ _ _ _ _ _ _ _ _).1 ht
    rw [hdt, Option.some.injEq] at hd
    rw [← hpt, ← hd]
    exact hpp
  · exact absurd h (by simp)

/-- **The host's transcript.** At `T+4410`, on `d7`, the transcript request of `reqTxA` stores exactly
`d8`: the host's `tx` row is `tdA`, only the host is submitted, and the document is saved once. -/
theorem step_txA : (step e (P.W 4410) P.reqTxA P.d7).1 = P.d8 := by
  obtain ⟨hst, -, hcr, ht0, -, -, -, -, -, hcom, -⟩ := P.d7_facts
  have hload := P.load_startedTx 4410 hst hcr ht0 (by omega)
  have hrole : role_of P.d7 P.dA = some .A := if_pos rfl
  have hsub : P.d7.submitted .A = false := rfl
  simp only [step, reqTxA, opReq, Bool.false_eq_true, ite_false, hload, hrole, handle, transcript,
    P.stale_txA, hst, ne_eq, not_true_eq_false, hsub, hcom, Bool.true_eq_false, OTHER, P.pk_B,
    P.check_txA]
  rfl

end X1Plan

#check @X1Plan.check_txA_partner
#check @X1Plan.step_txA

#print axioms X1Plan.stale_txA
#print axioms X1Plan.check_txA
#print axioms X1Plan.check_txA_partner
#print axioms X1Plan.step_txA

end Machine
end ServerFv
