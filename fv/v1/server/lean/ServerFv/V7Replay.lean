import ServerFv.V7Bridge

/-!
# V7 core: replaying a stored record gives the live `combine`

Gap 5, V7, the core equation. Take a reachable document with a final record `rc` that holds both
transcripts. Feed `toRR e rc` (the record as `verify_record` reads it, `verdict.py:168-189`) to
`verify_record`. The result is exactly `combine` on the two transcripts the server stored, with the
`cal_us` snapshots the server used (`sessions.py:451-456`).

The proof goes through `Core.com_ok` and `Core.tx_ok` directly. `side_facts` and `M3` drop
`c.version = _popt s r`, and `verify_one` passes `c.version` as the version, so they are not enough.

**What it pins.** The equation is between `Except` values, so it covers every outcome: the same
verdict, reason, `by_` and flight, the same reject, the same `zero_division`.

**What it does not pin.** Record fields `verify_record` never reads (`verdict`, `reason`,
`flight_cm`, `half`, `sample_rate`, `popt`, `attempts`, times) are not compared here. How the stored
`verdict` and `reason` relate to `combine`'s output is a separate fact (V7 rows). Hex decoding of the
nonce and keys is not modeled (see `V7Bridge`). A record missing a transcript is out of scope here.
-/

namespace ServerFv
namespace Machine

variable {B D : Type} [DecidableEq B] [DecidableEq D]

omit [DecidableEq B] [DecidableEq D] in
/-- What `toRR` makes of a record built by `_record`, field by field, once both device ids are set.
It pins the nonce, the attempt, each role's key and `cal_us`, and each transcript and commit entry.
It says nothing about fields `toRR` drops. -/
theorem toRR_record (e : Env B D) (s : Doc B D) (v : Verdict) (rs : Option Reason) (f : Option ℚ)
    {dA dB : D} (hA : devId s .A = some dA) (hB : devId s .B = some dB) :
    ∃ rr, toRR e (_record e s v rs f) = some rr ∧ rr.session_nonce = s.nonce_hex ∧
      rr.attempt = s.attempt ∧
      (∀ r d, devId s r = some d → (rr.devices r).pubkey = e.pk d) ∧
      (∀ r, (rr.devices r).cal_us = some (((s.per_role r).arm.map (·.cal_us)).getD 0)) ∧
      (∀ r, rr.transcripts r =
        (s.per_role r).tx.bind fun t => txEntry e ⟨t.transcript_b64, t.sig_b64, t.transcript_sha256⟩) ∧
      rr.commits = some fun r =>
        (s.per_role r).commit.bind fun c => commitEntry e ⟨c.commit_b64, c.commit_sig_b64⟩ := by
  have hA' : (_record e s v rs f).devices .A = some ⟨dA, e.pk dA, (s.per_role .A).arm.map (·.sample_rate),
      (s.per_role .A).tx.map (·.half), _popt s .A, ((s.per_role .A).arm.map (·.cal_us)).getD 0⟩ := by
    simp [_record, hA]
  have hB' : (_record e s v rs f).devices .B = some ⟨dB, e.pk dB, (s.per_role .B).arm.map (·.sample_rate),
      (s.per_role .B).tx.map (·.half), _popt s .B, ((s.per_role .B).arm.map (·.cal_us)).getD 0⟩ := by
    simp [_record, hB]
  refine ⟨_, toRR_eq e _ hA' hB', rfl, rfl, ?_, ?_, ?_, ?_⟩
  · intro r d hd
    cases r
    · rw [hA] at hd; cases hd; rfl
    · rw [hB] at hd; cases hd; rfl
  · intro r; cases r <;> rfl
  · intro r
    show ((_record e s v rs f).transcripts r).bind (txEntry e) = _
    simp only [_record]
    rcases (s.per_role r).tx with _ | t <;> rfl
  · show some (fun r => ((_record e s v rs f).commits r).bind (commitEntry e)) = _
    simp only [_record]
    congr 1; funext r
    rcases (s.per_role r).commit with _ | c <;> rfl

/-- **One role replays.** In a document that satisfies `Core`, take a role `r` whose transcript is
stored. Let `rr` be any record whose nonce, attempt, keys, transcript entries and commit entries are
the ones the document holds (the shape `toRR_record` gives). Then `verify_one` on `rr` for `r`
accepts, and returns the same transcript the server re-decodes at `sessions.py:454` (`stored`).

The key facts: the commit check passes by `CommitOk`; the transcript check passes by `TxOk`, with
`sample_rate` and `code_commit` dropped (`check_transcript_offline`), and with the version
`verify_one` reads from the commit equal to `_popt s r` (`CommitOk` keeps that). -/
theorem verify_one_core {e : Env B D} {c : ℕ} {s : Doc B D} {r : Role} {td : TxData B}
    {rr : ResultRecord B} (hc : Core e c s) (htx : (s.per_role r).tx = some td)
    (hn : rr.session_nonce = s.nonce_hex) (ha : rr.attempt = s.attempt)
    (hdev : ∀ r d, devId s r = some d → (rr.devices r).pubkey = e.pk d)
    (htr : ∀ r, rr.transcripts r =
      (s.per_role r).tx.bind fun t => txEntry e ⟨t.transcript_b64, t.sig_b64, t.transcript_sha256⟩)
    (hcm : rr.commits = some fun r =>
      (s.per_role r).commit.bind fun c => commitEntry e ⟨c.commit_b64, c.commit_sig_b64⟩) :
    ∃ t, verify_one e.p rr r (OTHER r) = .ok t ∧ stored e s r = some t := by
  have hsub : s.submitted r = true := (hc.sub_iff r).2 (by simp [htx])
  have hcom := (hc.com_iff r).1 (hc.sub_com r hsub)
  rcases hcd : (s.per_role r).commit with _ | cd
  · simp [hcd] at hcom
  obtain ⟨pk, rawc, sigc, cm, hpk, hrawc, hsigc, hchk, hver, hrec, hsha⟩ :=
    check_commit_of_CommitOk (hc.com_ok r cd hcd)
  obtain ⟨pk1, pk', raw, sig, t, hpk1, hpk', hraw, hsig, hct, -, -, -⟩ := hc.tx_ok r td htx
  rw [hpk] at hpk1
  cases hpk1
  have hct' := check_transcript_offline hct
  rw [hcd] at hct'
  simp only [Option.map_some] at hct'
  rw [hsha, ← hrec, ← hver] at hct'
  have hdec := ((check_transcript_ok_iff _ _ _ _ _ _ _ _ _ _ _ _ _ _).1 hct').1
  -- keys of both roles, through `devId`
  have hkey : ∀ r' k, _pk e s r' = some k → (rr.devices r').pubkey = k := by
    intro r' k hk
    simp only [_pk, Option.map_eq_some_iff] at hk
    obtain ⟨d, hd, rfl⟩ := hk
    exact hdev r' d hd
  have k1 := hkey r pk hpk
  have k2 := hkey (OTHER r) pk' hpk'
  refine ⟨t, ?_, stored_eq htx hraw hdec⟩
  have etr : rr.transcripts r = some ⟨raw, sig⟩ := by
    rw [htr r, htx]
    simp [txEntry, hraw, hsig]
  have ecm : rr.commits.bind (fun m => m r) = some ⟨rawc, sigc⟩ := by
    rw [hcm]
    simp [hcd, commitEntry, hrawc, hsigc]
  unfold verify_one
  rw [etr, ecm]
  simp only
  rw [k1, hn, ha, hchk]
  simp only
  rw [k2]
  exact hct'

/-- **V7, the replay equation.** Take a reachable document `s` whose final record `rc` holds both
transcripts. Then `toRR e rc` exists, the server's stored transcripts `ta` and `tb` both decode, and
`verify_record` on the record returns exactly what `combine ta tb (calMap s)` returns: the same value
on success, the same error on failure.

So an offline verifier that re-runs `verify_record` on a published record sees the server's own
`combine` call at `sessions.py:456`, on the same inputs. It does not say what `rc.verdict` or
`rc.reason` hold; that link is the V7 rows. It assumes nothing about `e` (no key injectivity). -/
theorem V7_replay_eq {e : Env B D} {c : ℕ} {s : Doc B D} {rc : Record B D} (h : Reachable e c s)
    (hr : s.result = some rc) (hA : rc.transcripts .A ≠ none) (hB : rc.transcripts .B ≠ none) :
    ∃ rr ta tb, toRR e rc = some rr ∧ stored e s .A = some ta ∧ stored e s .B = some tb ∧
      verify_record e.p rr = combine ta tb (calMap s) := by
  have hc : Core e c s := (M9 h).toCore
  have hrc := hc.rec_eq rc hr
  rw [hrc] at hA hB ⊢
  rcases htA : (s.per_role .A).tx with _ | tdA
  · simp [_record, htA] at hA
  rcases htB : (s.per_role .B).tx with _ | tdB
  · simp [_record, htB] at hB
  -- both device ids are set: each role's `TxOk` names its key
  have hdev : ∀ r td, (s.per_role r).tx = some td → ∃ d, devId s r = some d := by
    intro r td ht
    obtain ⟨pk, -, -, -, -, hpk, -⟩ := hc.tx_ok r td ht
    simp only [_pk, Option.map_eq_some_iff] at hpk
    obtain ⟨d, hd, -⟩ := hpk
    exact ⟨d, hd⟩
  obtain ⟨dA, hdA⟩ := hdev .A tdA htA
  obtain ⟨dB, hdB⟩ := hdev .B tdB htB
  obtain ⟨rr, hrr, hn, ha, hk, hcal, htr, hcm⟩ :=
    toRR_record e s rc.verdict rc.reason rc.flight_cm hdA hdB
  obtain ⟨ta, hvA, hsA⟩ := verify_one_core (r := .A) hc htA hn ha hk htr hcm
  obtain ⟨tb, hvB, hsB⟩ := verify_one_core (r := .B) hc htB hn ha hk htr hcm
  refine ⟨rr, ta, tb, hrr, hsA, hsB, ?_⟩
  unfold verify_record
  rw [show OTHER .A = .B from rfl] at hvA
  rw [show OTHER .B = .A from rfl] at hvB
  rw [hvA]
  simp only
  rw [hvB]
  simp only
  congr 1
  simp only [calMap, hcal, Option.getD_some]

end Machine
end ServerFv

#print axioms ServerFv.Machine.toRR_record
#print axioms ServerFv.Machine.verify_one_core
#print axioms ServerFv.Machine.V7_replay_eq
