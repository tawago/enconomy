import ServerFv.Machine

/-!
# V7 bridge: from a stored record to what `verify_record` reads

Gap 5, V7, the first piece. `verify_record` (`verdict.py:168-189`) re-checks a §8.4 record offline.
The machine stores that record as `Machine.Record` (`sessions.py:361-384`). This file turns one into
the other (`toRR`) and proves two small transfer lemmas that the V7 replay proof needs.

**What `toRR` copies.** `session_nonce`, `attempt`, each role's `pubkey` and `cal_us`, and the
base64 strings of each transcript and commit, decoded with `Env.b64d`. Nothing else: `verdict`,
`reason`, `flight_cm`, `half` and the rest are never read by `verify_record`.

**Where `toRR` differs from Python.**
* A record with no device row for A or B gives `none`. Python raises `KeyError` at `verdict.py:175`.
* A base64 string that does not decode makes that transcript or commit entry missing, so
  `verify_record` rejects with `transcript_mismatch`. Python raises `binascii.Error` instead. On a
  reachable record every stored string decodes (`CommitOk`, `TxOk`), so this never happens there.
* Hex decoding of `session_nonce` and `pubkey` (`verdict.py:174-175`) is not modeled: the machine
  already keeps them as bytes `B`.
* Python's `rec["devices"][r].get("cal_us") or 0` is `some cal_us` here, and `verify_record` reads it
  with `getD 0`. The machine always writes an integer there (`_record`), so the two agree.
-/

namespace ServerFv
namespace Machine

variable {B D : Type} [DecidableEq B] [DecidableEq D]

/-- Decode a stored transcript entry's two base64 strings. `none` if either fails. -/
def txEntry (e : Env B D) (t : TxEntry B) : Option (SignedEntry B) := do
  let raw ← e.b64d t.transcript_b64
  let sig ← e.b64d t.sig_b64
  pure ⟨raw, sig⟩

/-- Decode a stored commit entry's two base64 strings. `none` if either fails. -/
def commitEntry (e : Env B D) (c : CommitEntry B) : Option (SignedEntry B) := do
  let raw ← e.b64d c.commit_b64
  let sig ← e.b64d c.sig_b64
  pure ⟨raw, sig⟩

/-- The record `verify_record` would read, built from the machine's stored `Record`.
`none` exactly when a device row is missing (Python: `KeyError` at `verdict.py:175`).
A transcript or commit whose base64 fails to decode becomes a missing entry. -/
def toRR (e : Env B D) (rc : Record B D) : Option (ResultRecord B) := do
  let dA ← rc.devices .A
  let dB ← rc.devices .B
  pure
    { session_nonce := rc.session_nonce
      attempt := rc.attempt
      devices := fun r => match r with
        | .A => ⟨dA.pubkey, some dA.cal_us⟩
        | .B => ⟨dB.pubkey, some dB.cal_us⟩
      transcripts := fun r => (rc.transcripts r).bind (txEntry e)
      commits := some fun r => (rc.commits r).bind (commitEntry e) }

omit [DecidableEq B] [DecidableEq D] in
/-- Unfolds `toRR` when both device rows are present. It pins every field of the result. -/
theorem toRR_eq (e : Env B D) (rc : Record B D) {dA dB : DeviceRow B D}
    (hA : rc.devices .A = some dA) (hB : rc.devices .B = some dB) :
    toRR e rc = some
      { session_nonce := rc.session_nonce
        attempt := rc.attempt
        devices := fun r => match r with
          | .A => ⟨dA.pubkey, some dA.cal_us⟩
          | .B => ⟨dB.pubkey, some dB.cal_us⟩
        transcripts := fun r => (rc.transcripts r).bind (txEntry e)
        commits := some fun r => (rc.commits r).bind (commitEntry e) } := by
  simp [toRR, hA, hB]

omit [DecidableEq B] [DecidableEq D] in
/-- `toRR` is `none` exactly when a device row is missing. -/
theorem toRR_none_iff (e : Env B D) (rc : Record B D) :
    toRR e rc = none ↔ rc.devices .A = none ∨ rc.devices .B = none := by
  rcases hA : rc.devices .A with _ | dA <;> rcases hB : rc.devices .B with _ | dB <;>
    simp [toRR, hA, hB]

omit [DecidableEq B] [DecidableEq D] in
/-- A stored transcript entry decodes exactly when both its strings decode. -/
theorem txEntry_eq_some (e : Env B D) (t : TxEntry B) (se : SignedEntry B) :
    txEntry e t = some se ↔ e.b64d t.transcript_b64 = some se.raw ∧ e.b64d t.sig_b64 = some se.sig := by
  rcases se with ⟨raw, sig⟩
  rcases h1 : e.b64d t.transcript_b64 with _ | r1 <;> rcases h2 : e.b64d t.sig_b64 with _ | s1 <;>
    simp [txEntry, h1, h2, and_comm]

omit [DecidableEq B] [DecidableEq D] in
/-- A stored commit entry decodes exactly when both its strings decode. -/
theorem commitEntry_eq_some (e : Env B D) (c : CommitEntry B) (se : SignedEntry B) :
    commitEntry e c = some se ↔ e.b64d c.commit_b64 = some se.raw ∧ e.b64d c.sig_b64 = some se.sig := by
  rcases se with ⟨raw, sig⟩
  rcases h1 : e.b64d c.commit_b64 with _ | r1 <;> rcases h2 : e.b64d c.sig_b64 with _ | s1 <;>
    simp [commitEntry, h1, h2, and_comm]

omit [DecidableEq D] in
/-- **Live acceptance implies replay acceptance**, for one transcript. If `check_transcript` passes
with some `sample_rate` and `code_commit`, it passes with both `none` and the same other arguments,
and returns the same transcript. This is what `verify_record` does: it passes no sample rate and no
code commit (`verdict.py:185-187`), since neither can be re-derived offline.

It says nothing about the other arguments: the key, nonce, attempt, commit hash, `rec` and version
must be the same on both sides. The converse is false (offline skips two checks). -/
theorem check_transcript_offline {p : Prims B} {raw sig : B} {role : Role} {pk pk' n : B} {k : ℕ}
    {ch rc : Option B} {sr : Option ℕ} {ver : ℕ} {cc : Option B} {t : Transcript B}
    (h : check_transcript p raw sig role pk pk' n k ch rc sr ver cc = .ok t) :
    check_transcript p raw sig role pk pk' n k ch rc none ver none = .ok t := by
  rw [check_transcript_ok_iff] at h ⊢
  obtain ⟨h1, h2, h3, h4, h5, h6, h7, h8, -, h10, h11, h12, h13, h14⟩ := h
  refine ⟨h1, h2, h3, h4, h5, h6, h7, h8, fun hn => absurd rfl hn, h10, h11, h12, h13, ?_⟩
  intro hv
  exact ⟨(h14 hv).1, fun hn => absurd rfl hn⟩

omit [DecidableEq D] in
/-- **A stored commit passes the offline commit check.** From `CommitOk` (what an accepted commit
leaves in the document): the role's key, the two decoded strings, and that `check_commit` with the
document's nonce and attempt returns a commit `c` whose `version` is the role's `popt`, whose `rec_`
is the stored `rec_`, and whose SHA-256 is the stored `commit_sha256`.

It pins the check against the document's current `nonce_hex` and `attempt`. It does not say the
record's `session_nonce` and `attempt` are those; the replay proof gets that from `_record`. -/
theorem check_commit_of_CommitOk {e : Env B D} {s : Doc B D} {r : Role} {cd : CommitData B}
    (h : CommitOk e s r cd) :
    ∃ pk raw sig c, _pk e s r = some pk ∧ e.b64d cd.commit_b64 = some raw ∧
      e.b64d cd.commit_sig_b64 = some sig ∧
      check_commit e.p raw sig r pk s.nonce_hex s.attempt = .ok c ∧
      c.version = _popt s r ∧ c.rec_ = cd.rec_ ∧ cd.commit_sha256 = e.p.sha256 raw := by
  obtain ⟨pk, raw, sig, c, hpk, hraw, hsig, hdec, hver, hrole, hatt, hn, hv, hsha, hrec, -⟩ := h
  exact ⟨pk, raw, sig, c, hpk, hraw, hsig,
    (check_commit_ok_iff _ _ _ _ _ _ _ _).2 ⟨hdec, hver, hrole, hatt, hn⟩, hv, hrec.symm, hsha⟩

end Machine
end ServerFv

#print axioms ServerFv.Machine.toRR_eq
#print axioms ServerFv.Machine.toRR_none_iff
#print axioms ServerFv.Machine.txEntry_eq_some
#print axioms ServerFv.Machine.commitEntry_eq_some
#print axioms ServerFv.Machine.check_transcript_offline
#print axioms ServerFv.Machine.check_commit_of_CommitOk
