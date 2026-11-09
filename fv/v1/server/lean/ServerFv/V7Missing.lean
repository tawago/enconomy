import ServerFv.V7Bridge

/-!
# V7, row 5: a record with a transcript missing fails replay with a reject

Gap 5, V7, last row of the spec table (rejected, final fail, final timeout). When the stored
record has no transcript for A or for B, and both device rows are in it (so `toRR` gives a replay
input, `toRR_eq_none_iff`), `verify_record` (`verdict.py:168-189`) raises a `reject`, never
`zero_division` and never a verdict. With a device row missing, Python raises `KeyError`
(`verdict.py:177`); nothing here covers that.

**What this pins.**
* `check_commit_error_reject`, `check_transcript_error_reject`: every error these two raise is a
  `reject`.
* `V7_missing_any`: for any `ResultRecord` with a transcript entry missing, `verify_record` is
  `.error (.reject _)`. It needs no session at all.
* `V7_missing`: the same for the replay of a stored `Record` through `toRR`, when the record lacks
  A's or B's transcript. Stated on a reachable doc to match the spec row; the proof does not use
  reachability.
* `V7_missing_submitted`: on a reachable doc whose result is set while not both roles submitted,
  some transcript is missing, so the replay rejects. This ties the row to the session states that
  write such a record.

**What it does not pin.** Which reason the reject carries (A's commit can fail first with
`signature_invalid`, for example). That rejected, final fail and final timeout really leave a
transcript missing is only shown here through `all2 s.submitted = false`; that those finalizing
paths have not both submitted is a separate fact (V7-4a).
-/

namespace ServerFv
namespace Machine

variable {B D : Type} [DecidableEq B] [DecidableEq D]

/-- `y` can only fail with a `reject`. -/
def OnlyRejects {α : Type} (y : Except Raised α) : Prop := ∀ x, y = .error x → ∃ rsn, x = .reject rsn

theorem OnlyRejects.ok {α : Type} (t : α) : OnlyRejects (Except.ok t : Except Raised α) := by
  intro x h; cases h

theorem OnlyRejects.rej {α : Type} (r : Reason) : OnlyRejects (Except.error (.reject r) : Except Raised α) := by
  intro x h; cases h; exact ⟨r, rfl⟩

theorem OnlyRejects.ite {α : Type} {c : Prop} [Decidable c] {r : Reason} {y : Except Raised α}
    (hy : OnlyRejects y) : OnlyRejects (if c then Except.error (.reject r) else y) := by
  split
  · exact OnlyRejects.rej r
  · exact hy

/-- Every error `check_commit` raises is a `reject`. -/
theorem check_commit_error_reject (p : Prims B) (raw sig : B) (r : Role) (pk n : B) (k : ℕ)
    (x : Raised) (h : check_commit p raw sig r pk n k = .error x) : ∃ rsn, x = .reject rsn := by
  revert x h
  show OnlyRejects _
  unfold check_commit
  split
  · exact OnlyRejects.rej _
  · repeat (first | exact OnlyRejects.ok _ | exact OnlyRejects.rej _ | apply OnlyRejects.ite)

/-- Every error `check_transcript` raises is a `reject`. -/
theorem check_transcript_error_reject (p : Prims B) (raw sig : B) (r : Role) (pk pk' n : B)
    (k : ℕ) (ch rc : Option B) (sr : Option ℕ) (ver : ℕ) (cc : Option B) (x : Raised)
    (h : check_transcript p raw sig r pk pk' n k ch rc sr ver cc = .error x) :
    ∃ rsn, x = .reject rsn := by
  revert x h
  show OnlyRejects _
  unfold check_transcript
  split
  · exact OnlyRejects.rej _
  · repeat (first | exact OnlyRejects.ok _ | exact OnlyRejects.rej _ | apply OnlyRejects.ite)
    split
    · repeat (first | exact OnlyRejects.ok _ | exact OnlyRejects.rej _ | apply OnlyRejects.ite)
    · exact OnlyRejects.ok _

/-- Every error `verify_one` raises is a `reject`. -/
theorem verify_one_error_reject (p : Prims B) (rr : ResultRecord B) (r o : Role) (x : Raised)
    (h : verify_one p rr r o = .error x) : ∃ rsn, x = .reject rsn := by
  unfold verify_one at h
  split at h
  · split at h
    · cases h; exact check_commit_error_reject _ _ _ _ _ _ _ _ (by assumption)
    · exact check_transcript_error_reject _ _ _ _ _ _ _ _ _ _ _ _ _ _ h
  · cases h; exact ⟨_, rfl⟩

/-- `verify_one` on a role with no transcript entry rejects with `transcript_mismatch`. -/
theorem verify_one_missing (p : Prims B) (rr : ResultRecord B) (r o : Role)
    (h : rr.transcripts r = none) : verify_one p rr r o = .error (.reject .transcript_mismatch) := by
  unfold verify_one; rw [h]

/-- Row 5 for any record: with A's or B's transcript missing, `verify_record` raises a `reject`.
It never returns a verdict and never raises `zero_division`. The reason is not pinned. -/
theorem V7_missing_any (p : Prims B) (rr : ResultRecord B)
    (hm : rr.transcripts .A = none ∨ rr.transcripts .B = none) :
    ∃ rsn, verify_record p rr = .error (.reject rsn) := by
  unfold verify_record
  rcases hA : verify_one p rr .A .B with x | ta
  · obtain ⟨rsn, rfl⟩ := verify_one_error_reject p rr .A .B x hA
    exact ⟨rsn, rfl⟩
  · rcases hm with hm | hm
    · rw [verify_one_missing p rr .A .B hm] at hA; cases hA
    · simp only
      rw [verify_one_missing p rr .B .A hm]
      exact ⟨_, rfl⟩

omit [DecidableEq B] [DecidableEq D] in
/-- A missing stored transcript stays missing after `toRR`. -/
theorem toRR_transcripts_none {e : Env B D} {rc : Record B D} {rr : ResultRecord B} {r : Role}
    (hr : toRR e rc = some rr) (h : rc.transcripts r = none) : rr.transcripts r = none := by
  rcases hA : rc.devices .A with _ | dA <;> rcases hB : rc.devices .B with _ | dB <;>
    simp [toRR, hA, hB] at hr
  subst hr; simp [h]

/-- Row 5 on a stored record: if the record lacks A's or B's transcript, every replay of it
(`toRR` succeeds) rejects. `h` matches the spec row; the proof does not need it. -/
theorem V7_missing {e : Env B D} {c : ℕ} {s : Doc B D} {rc : Record B D}
    (_h : Reachable e c s) (_hr : s.result = some rc)
    (hm : rc.transcripts .A = none ∨ rc.transcripts .B = none) :
    ∀ rr, toRR e rc = some rr → ∃ rsn, verify_record e.p rr = .error (.reject rsn) := by
  intro rr hrr
  exact V7_missing_any e.p rr (hm.imp (toRR_transcripts_none hrr) (toRR_transcripts_none hrr))

/-- On a reachable doc, a result written while not both roles submitted has a transcript missing,
so its replay rejects. Uses `Inv.rec_eq` (the stored record is `_record` of the doc) and
`Inv.sub_iff` (submitted exactly when a transcript is stored). -/
theorem V7_missing_submitted {e : Env B D} {c : ℕ} {s : Doc B D} {rc : Record B D}
    (h : Reachable e c s) (hr : s.result = some rc) (hn : all2 s.submitted = false) :
    (rc.transcripts .A = none ∨ rc.transcripts .B = none) ∧
    ∀ rr, toRR e rc = some rr → ∃ rsn, verify_record e.p rr = .error (.reject rsn) := by
  have hi := M9 h
  have hm : rc.transcripts .A = none ∨ rc.transcripts .B = none := by
    rw [hi.rec_eq rc hr]
    have hsA := hi.sub_iff .A
    have hsB := hi.sub_iff .B
    simp only [all2, Bool.and_eq_false_iff] at hn
    rcases hn with hn | hn
    · left; rw [hn] at hsA; simp [_record]
      cases ht : (s.per_role .A).tx <;> simp_all
    · right; rw [hn] at hsB; simp [_record]
      cases ht : (s.per_role .B).tx <;> simp_all
  exact ⟨hm, V7_missing h hr hm⟩

end Machine
end ServerFv

#print axioms ServerFv.Machine.check_commit_error_reject
#print axioms ServerFv.Machine.check_transcript_error_reject
#print axioms ServerFv.Machine.V7_missing_any
#print axioms ServerFv.Machine.V7_missing
#print axioms ServerFv.Machine.V7_missing_submitted
