import ServerFv.Machine

/-!
# V7, rows 2 to 4, part a: `ResultFacts` and the paths that can't feed it

Gap 5 of `README.md`, property V7 of `spec.md`. A final record whose two transcripts are both in
should agree with what `combine` says on them. When `combine` gives a verdict (rows 1 and 2), the
record has that verdict, reason and flight. When it gives no verdict (rows 3 and 4), only the
reason matches: the record says NOT_NEAR with no flight, so it does not replay to the verdict it
shows. When `combine` rejects, the record names the same reason. `Inv` does not carry this fact for
NOT_NEAR records, and adding it there would mean a `Machine.lean` edit. So this file states it as a
separate predicate, `ResultFacts`, to be proved later by its own induction over `Reachable`.

This file only defines the predicate and proves the cheap cases: every way a session can end with a
record except the both-transcripts-in branch of `afterStore` leaves at least one role not submitted,
so `ResultFacts` holds there for nothing (vacuously). The real source, `afterStore`, and the
induction are later chunks.

It says nothing about the air (CN1). It reads only the model in `Machine.lean`.
-/

namespace ServerFv
namespace Machine

set_option linter.unusedSectionVars false

variable {B D : Type} [DecidableEq B] [DecidableEq D]

/-- **ResultFacts.** If `s` holds a record and both roles have submitted, then both stored
transcripts decode, and either

* `combine` on them and the stored calibration returns `out`, and the record matches it: a verdict
  `v` from `combine` is the record's verdict, with the same reason and flight; or `combine` gave no
  verdict, the record says NOT_NEAR with `combine`'s reason and no flight, this was the last attempt
  (attempt 1), and the last attempts row names the same `by_` as `combine`; or
* `combine` rejects with reason `rsn`, and the record says NOT_NEAR with reason `rsn`.

It pins verdict, reason and flight only. It says nothing about the other record fields, nor about
records where a transcript is missing (those are V7's last row). -/
def ResultFacts (e : Env B D) (s : Doc B D) : Prop :=
  ∀ rc, s.result = some rc → all2 s.submitted = true →
    ∃ ta tb, stored e s .A = some ta ∧ stored e s .B = some tb ∧
      ((∃ out, combine ta tb (calMap s) = .ok out ∧
        ((∃ v, out.verdict = some v ∧ rc.verdict = v ∧ rc.reason = out.reason ∧
            rc.flight_cm = out.flight_cm) ∨
         (out.verdict = none ∧ rc.verdict = .NOT_NEAR ∧ rc.reason = out.reason ∧
            rc.flight_cm = none ∧ s.attempt = 1 ∧
            (s.attempts.getLast?).map (·.by_) = some out.by_))) ∨
       (∃ rsn, combine ta tb (calMap s) = .error (.reject rsn) ∧ rc.verdict = .NOT_NEAR ∧
          rc.reason = some rsn))

/-- A doc with no record has `ResultFacts`, for nothing. -/
theorem ResultFacts_of_no_result {e : Env B D} {s : Doc B D} (h : s.result = none) :
    ResultFacts e s := by
  intro rc hr; simp [h] at hr

/-- A doc where some role has not submitted has `ResultFacts`, for nothing. -/
theorem ResultFacts_of_not_all {e : Env B D} {s : Doc B D} (h : all2 s.submitted = false) :
    ResultFacts e s := by
  intro rc _ hall; simp [h] at hall

/-- **(1)** A freshly created doc has `ResultFacts`: it has no record. -/
theorem ResultFacts_create (e : Env B D) (w : World D) (host : D) (sid nonce : B)
    (seed token : String) : ResultFacts e (create w host sid nonce seed token).1 :=
  ResultFacts_of_no_result rfl

/-- **(2)** From done or aborted, no request changes the doc (`M1_terminal`), so `ResultFacts`
carries over unchanged. -/
theorem ResultFacts_terminal {e : Env B D} {w : World D} {s : Doc B D} (req : Req B D)
    (hst : s.state = .done ∨ s.state = .aborted) (h : ResultFacts e s) :
    ResultFacts e (step e w req s).1 := by
  rw [M1_terminal req hst]; exact h

/-- `_finalize` keeps the submitted flags. -/
theorem finalize_submitted {e : Env B D} {w : World D} {s : Doc B D} {v : Verdict}
    {rs : Option Reason} {fl : Option ℚ} {o : Outcome} {by_ : Option Role} :
    (_finalize e w s v rs fl o by_).submitted = s.submitted := rfl

/-- `_failed` never turns a role to submitted: if some role is not submitted before, some role is
not submitted after. The retry branch clears all flags, the final branch keeps them. -/
theorem failed_not_all {e : Env B D} {w : World D} {s : Doc B D} {rs : Option Reason}
    {by_ : Option Role} (h : all2 s.submitted = false) :
    all2 (_failed e w s rs by_).submitted = false := by
  unfold _failed
  split
  · simp [next_attempt, _save, all2, _flags]
  · rw [finalize_submitted]; exact h

/-- **(3)** A load that writes a record onto a doc with none leaves some role not submitted. Only
the E3 timeout can write a record there, it needs `started`, and `Inv.started_not_all` says a
started doc never has both in. The two abort rows keep `result = none`. -/
theorem expire_done_not_all {e : Env B D} {c : ℕ} {w : World D} {s : Doc B D} {rc : Record B D}
    (h : Inv e c s) (hres : s.result = none) (hr : (_expire e w s).result = some rc) :
    all2 (_expire e w s).submitted = false := by
  unfold _expire at hr ⊢
  split_ifs at hr ⊢ with h1 h2 h3
  · simp [_save, hres] at hr
  · simp [_save, hres] at hr
  · exact failed_not_all (h.started_not_all h3.1)
  · simp [hres] at hr

/-- Same as (3), as `ResultFacts` of the loaded doc. -/
theorem ResultFacts_expire {e : Env B D} {c : ℕ} {w : World D} {s : Doc B D}
    (h : Inv e c s) (hres : s.result = none) : ResultFacts e (_expire e w s) := by
  intro rc hr
  rw [expire_done_not_all h hres hr]; simp

/-- **(4)** An accepted `/fail` leaves the failing role not submitted: line 474 refuses a role that
has submitted, `failStore` writes only `fail_`, and `_failed` either clears all flags or keeps them.
This holds whether or not a record was written. -/
theorem fail_not_submitted {e : Env B D} {w : World D} {s s' : Doc B D} {role : Role} {a : Arg}
    {rsn : Option Reason} (hf : fail_ e w s role a rsn = .ok s') : s'.submitted role = false := by
  unfold fail_ at hf
  split at hf
  · simp at hf
  split at hf
  · simp at hf
  split at hf
  · simp at hf
  split at hf
  · simp at hf
  split at hf
  · simp at hf
  split at hf
  · simp at hf
  split at hf
  · simp at hf
  rename_i hsub
  simp only [Except.ok.injEq] at hf
  subst hf
  unfold _failed
  split
  · simp [next_attempt, _save, _flags]
  · simpa [finalize_submitted, failStore] using hsub

/-- (4) in the plan's form: a `/fail` that writes a record leaves the failing role not submitted. -/
theorem fail_done_not_all {e : Env B D} {w : World D} {s s' : Doc B D} {role : Role} {a : Arg}
    {rsn : Option Reason} {rc : Record B D} (hf : fail_ e w s role a rsn = .ok s')
    (_hr : s'.result = some rc) : all2 s'.submitted = false := by
  have h := fail_not_submitted hf
  cases role <;> simp [all2, h]

/-- (4) as `ResultFacts`. -/
theorem ResultFacts_fail {e : Env B D} {w : World D} {s s' : Doc B D} {role : Role} {a : Arg}
    {rsn : Option Reason} (hf : fail_ e w s role a rsn = .ok s') : ResultFacts e s' := by
  intro rc hr
  rw [fail_done_not_all hf hr]; simp

/-- **(5)** The transcript reject at lines 438-440 finalizes the doc from before `txStore`, so the
sending role, not yet submitted there (line 423), stays not submitted. -/
theorem transcript_reject_not_all {e : Env B D} {w : World D} {s : Doc B D} {role : Role}
    {rsn : Reason} (hns : s.submitted role = false) :
    all2 (_finalize e w s .NOT_NEAR (some rsn) none .rejected (some role)).submitted = false := by
  rw [finalize_submitted]; cases role <;> simp [all2, hns]

/-- What `/transcript` stores, in three shapes: nothing changed; the reject finalize of (5) on a
doc where the sender had not submitted; or `afterStore` after storing the sender's transcript, on a
started doc where the sender had not submitted. Part b takes the last shape. It pins which doc
each branch starts from, not what the response says. -/
theorem transcript_cases (e : Env B D) (w : World D) (s : Doc B D) (role : Role) (dev : D)
    (tb sb : B) :
    (transcript e w s role dev tb sb).1 = s ∨
    (∃ rsn, s.submitted role = false ∧
      (transcript e w s role dev tb sb).1 =
        _finalize e w s .NOT_NEAR (some rsn) none .rejected (some role)) ∨
    (∃ td, s.state = .started ∧ s.submitted role = false ∧
      (transcript e w s role dev tb sb).1 = (afterStore e w s (txStore s role td)).1) := by
  unfold transcript
  split_ifs with h1 h2 h3 h4
  · exact Or.inl rfl
  · exact Or.inl rfl
  · split
    · split_ifs <;> exact Or.inl rfl
    · exact Or.inl rfl
  · exact Or.inl rfl
  · have hns : s.submitted role = false := by simpa using h3
    have hst : s.state = .started := by simpa using h2
    split
    · exact Or.inl rfl
    · split
      · exact Or.inr (Or.inl ⟨_, hns, rfl⟩)
      · exact Or.inl rfl
      · exact Or.inr (Or.inr ⟨_, hst, hns, rfl⟩)

/-- (5) as `ResultFacts`: a `/transcript` reject leaves a doc with `ResultFacts`. -/
theorem ResultFacts_transcript_reject {e : Env B D} {w : World D} {s : Doc B D} {role : Role}
    {rsn : Reason} (hns : s.submitted role = false) :
    ResultFacts e (_finalize e w s .NOT_NEAR (some rsn) none .rejected (some role)) :=
  ResultFacts_of_not_all (transcript_reject_not_all hns)

end Machine
end ServerFv

#print axioms ServerFv.Machine.ResultFacts_create
#print axioms ServerFv.Machine.ResultFacts_terminal
#print axioms ServerFv.Machine.expire_done_not_all
#print axioms ServerFv.Machine.ResultFacts_expire
#print axioms ServerFv.Machine.fail_done_not_all
#print axioms ServerFv.Machine.ResultFacts_fail
#print axioms ServerFv.Machine.transcript_reject_not_all
#print axioms ServerFv.Machine.transcript_cases
#print axioms ServerFv.Machine.ResultFacts_transcript_reject
