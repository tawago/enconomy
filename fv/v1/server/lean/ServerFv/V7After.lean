import ServerFv.V7Facts

/-!
# V7, rows 2 to 4, part b: `afterStore` is the one place a both-in record is born

Gap 5 of `README.md`, property V7 of `spec.md`. Part a (`V7Facts.lean`) defined `ResultFacts` and
showed every other way to finish a session leaves a role not submitted. This file takes the last
branch of `/transcript` (`sessions.py:451-465`, `afterStore` in `Machine.lean`): once the second
transcript is in, the doc either keeps `ResultFacts` or goes back to the loaded doc `s0`, which is
what the induction (part c) already knows about.

It needs only `s.attempt ≤ 1` (`Core.attempt_le`). It reads only the model in `Machine.lean` and
`Verdict.lean`, and says nothing about the air (CN1).
-/

namespace ServerFv
namespace Machine

set_option linter.unusedSectionVars false

variable {B D : Type} [DecidableEq B] [DecidableEq D]

/-- `combine` gives no verdict only with a retry reason: the two self-check branches say
`self_timestamp_mismatch` and `decide`'s no-verdict branch says `impossible_flight`, both in
`RETRY_REASONS`. It pins the reason class only, not which of the two. -/
theorem combine_none_retry {ta tb : Transcript B} {cal : Option (Role → Option ℤ)}
    {out : CombineOut} (h : combine ta tb cal = .ok out) (hv : out.verdict = none) :
    isRetry out.reason = true := by
  unfold combine at h
  split_ifs at h <;> simp only [Except.ok.injEq] at h <;> subst h <;>
    simp only at hv ⊢
  all_goals first
    | (simp [isRetry, RETRY_REASONS]; done)
    | (revert hv; generalize flight_exact _ _ _ _ = f; rw [ServerFv.decide]
       split_ifs <;> simp [isRetry, RETRY_REASONS])

/-- `_finalize` leaves the stored transcripts alone: it does not touch `per_role`. -/
theorem stored_finalize {e : Env B D} {w : World D} {s : Doc B D} {v : Verdict}
    {rs : Option Reason} {fl : Option ℚ} {o : Outcome} {by_ : Option Role} (r : Role) :
    stored e (_finalize e w s v rs fl o by_) r = stored e s r := rfl

/-- `_finalize` leaves the calibration map alone. -/
theorem calMap_finalize {e : Env B D} {w : World D} {s : Doc B D} {v : Verdict}
    {rs : Option Reason} {fl : Option ℚ} {o : Outcome} {by_ : Option Role} :
    calMap (_finalize e w s v rs fl o by_) = calMap s := rfl

/-- The record `_finalize` writes carries exactly the verdict, reason and flight it was given. -/
theorem finalize_result {e : Env B D} {w : World D} {s : Doc B D} {v : Verdict}
    {rs : Option Reason} {fl : Option ℚ} {o : Outcome} {by_ : Option Role} {rc : Record B D}
    (h : (_finalize e w s v rs fl o by_).result = some rc) :
    rc.verdict = v ∧ rc.reason = rs ∧ rc.flight_cm = fl := by
  simp only [_finalize, _save, Option.some.injEq] at h
  subst h; exact ⟨rfl, rfl, rfl⟩

/-- The last attempts row `_finalize` appends names the `by_` it was given. -/
theorem finalize_last_by {e : Env B D} {w : World D} {s : Doc B D} {v : Verdict}
    {rs : Option Reason} {fl : Option ℚ} {o : Outcome} {by_ : Option Role} :
    ((_finalize e w s v rs fl o by_).attempts.getLast?).map (·.by_) = some by_ := by
  simp [_finalize, _save]

/-- **afterStore_ResultFacts.** On a doc with `attempt ≤ 1`, `afterStore` either returns a doc
with `ResultFacts` or returns the loaded doc `s0` unchanged (the two uncaught 500s: a stored
transcript that does not decode, and `combine`'s zero division).

The branches: not all in gives `_save s` (some role not submitted); `combine` rejecting gives the
NOT_NEAR reject record; `combine` with a verdict gives a record with that verdict, reason and
flight; `combine` with no verdict gives `_failed`, which at attempt 0 retries (all flags cleared)
and at attempt 1 writes NOT_NEAR with `combine`'s reason, no flight and a last row naming
`combine`'s `by_`. Every finalize keeps `per_role`, so the stored transcripts and calibration it
compares are the ones `combine` saw.

It pins verdict, reason and flight against `combine` on the stored data. It does not say the
stored data are the phones' (that is `Inv`), nor anything about `s0` (part c brings that). -/
theorem afterStore_ResultFacts {e : Env B D} {w : World D} {s0 s : Doc B D}
    (hle : s.attempt ≤ 1) :
    ResultFacts e (afterStore e w s0 s).1 ∨ (afterStore e w s0 s).1 = s0 := by
  unfold afterStore
  split
  · rename_i hn
    exact Or.inl (ResultFacts_of_not_all (by simpa [_save] using hn))
  · split
    · rename_i ta tb hA hB
      split
      · rename_i rsn hc
        refine Or.inl fun rc hr _ => ⟨ta, tb, ?_, ?_, ?_⟩
        · rw [stored_finalize]; exact hA
        · rw [stored_finalize]; exact hB
        · obtain ⟨hv, hrs, _⟩ := finalize_result hr
          exact Or.inr ⟨rsn, by rw [calMap_finalize]; exact hc, hv, hrs⟩
      · exact Or.inr rfl
      · rename_i out hc
        left
        cases hv : out.verdict with
        | some v =>
          dsimp only
          intro rc hr _
          obtain ⟨hv', hrs, hfl⟩ := finalize_result hr
          refine ⟨ta, tb, by rw [stored_finalize]; exact hA, by rw [stored_finalize]; exact hB,
            Or.inl ⟨out, by rw [calMap_finalize]; exact hc, Or.inl ⟨v, hv, hv', hrs, hfl⟩⟩⟩
        | none =>
          dsimp only
          have hret := combine_none_retry hc hv
          unfold _failed
          rw [hret, Bool.true_and]
          split
          · rename_i hb
            have h0 : (next_attempt s out.reason out.by_).submitted = _flags := rfl
            exact ResultFacts_of_not_all (by rw [h0]; rfl)
          · rename_i hb
            have h1 : s.attempt = 1 := by
              cases ha : s.attempt with
              | zero => simp [ha] at hb
              | succ n => omega
            intro rc hr _
            obtain ⟨hv', hrs, hfl⟩ := finalize_result hr
            refine ⟨ta, tb, by rw [stored_finalize]; exact hA, by rw [stored_finalize]; exact hB,
              Or.inl ⟨out, by rw [calMap_finalize]; exact hc,
                Or.inr ⟨hv, hv', hrs, hfl, h1, finalize_last_by⟩⟩⟩
    · exact Or.inr rfl

/-- The form part c uses: if the loaded doc `s0` has `ResultFacts`, so does whatever `afterStore`
returns. Same hypothesis, same limits as `afterStore_ResultFacts`. -/
theorem ResultFacts_afterStore {e : Env B D} {w : World D} {s0 s : Doc B D}
    (hle : s.attempt ≤ 1) (h0 : ResultFacts e s0) : ResultFacts e (afterStore e w s0 s).1 := by
  rcases afterStore_ResultFacts (w := w) (s0 := s0) hle with h | h
  · exact h
  · rw [h]; exact h0

end Machine
end ServerFv

#print axioms ServerFv.Machine.combine_none_retry
#print axioms ServerFv.Machine.afterStore_ResultFacts
#print axioms ServerFv.Machine.ResultFacts_afterStore
