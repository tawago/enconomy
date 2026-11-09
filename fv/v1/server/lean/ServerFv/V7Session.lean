import ServerFv.V7After
import ServerFv.V7Rows
import ServerFv.V7Missing

/-!
# V7 on a reachable final record: rows 2 to 4, and the whole table

Gap 5 of `README.md`, property V7 of `spec.md`, part c. Parts a and b (`V7Facts.lean`,
`V7After.lean`) showed every request either keeps `ResultFacts` or makes a doc that has it. This
file runs the induction over `Reachable`, so every reachable doc has `ResultFacts`, and then reads
the V7 rows off it, through the replay equation of `V7Replay.lean`.

What comes out, for a reachable doc `s` with final record `rc`:

* both transcripts in: `verify_record` on `toRR e rc` returns `out`, or rejects. When `out` has a
  verdict (rows 1 and 2), it is the record's verdict, with the record's reason and flight. When
  `out` has no verdict (rows 3 and 4), only the reason matches: the record says NOT_NEAR where
  replay says no verdict, the record's flight is `none`, the doc is at attempt 1, and replay's `by_`
  is the one in the doc's last attempts row. Replay's flight there is a number for
  `impossible_flight` and `none` for `self_timestamp_mismatch` (`V7_failed_row_flight`). Or
  `combine` rejected and the record names that same reason;
* with key injectivity (`Function.Injective e.pk`, as in `combine_guard_unreachable`), the reject
  case can't happen;
* a transcript missing: every replay rejects (`V7Missing.lean`), as long as `toRR` exists. It
  exists exactly when both device rows are in the record (`toRR_eq_none_iff`). With a device row
  missing Python's `verify_record` raises `KeyError` at `verdict.py:177`, not `Reject`; nothing
  here covers that case;
* rows 3 and 4 can occur: concrete runs end with an `impossible_flight` and a
  `self_timestamp_mismatch` record at attempt 1 (`reaches_impossible_final`,
  `reaches_self_mismatch_final`), and `V7_failed_row` applies to them.

It reads only the model in `Machine.lean` and `Verdict.lean`. It says nothing about the air (CN1),
nor about record fields `verify_record` never reads (`half`, `sample_rate`, `popt`, times).
-/

namespace ServerFv
namespace Machine

set_option linter.unusedSectionVars false

variable {B D : Type} [DecidableEq B] [DecidableEq D]

/-! ## The induction -/

/-- A handler result `s'` on the loaded doc `s1`: the record field is unchanged, and on a done doc
nothing changed at all. Bookkeeping for the step proof. -/
def KeepRes (s1 s' : Doc B D) : Prop :=
  s'.result = s1.result ∧ (s1.state = .done → s' = s1)

theorem KeepRes.rf {e : Env B D} {c : ℕ} {s1 s' : Doc B D} (hc : Core e c s1)
    (h1 : ResultFacts e s1) (hk : KeepRes s1 s') : ResultFacts e s' := by
  by_cases hd : s1.state = .done
  · rw [hk.2 hd]; exact h1
  · exact ResultFacts_of_no_result (by rw [hk.1]; exact hc.result_none hd)

theorem join_keep {w : World D} {s s' : Doc B D} {d : D} {tok : String}
    (hj : join w s d tok = .ok s') : KeepRes s s' := by
  unfold join at hj
  split_ifs at hj with h1 h2 h3 h4
  simp only [Except.ok.injEq] at hj
  subst hj
  refine ⟨rfl, fun hd => ?_⟩
  exact absurd (Or.inl (by rw [hd]; simp)) h4

theorem confirm_keep {s s' : Doc B D} {role : Role} (hj : confirm s role = .ok s') :
    KeepRes s s' := by
  refine ⟨?_, fun hd => ?_⟩
  · unfold confirm at hj
    split_ifs at hj <;> simp only [Except.ok.injEq] at hj <;> subst hj
    · rfl
    · dsimp only [_save]; split <;> rfl
  · simp [confirm, hd] at hj

theorem abort_keep {w : World D} {s : Doc B D} {role : Role} : KeepRes s (abort w s role) := by
  refine ⟨?_, fun hd => by simp [abort, hd]⟩
  unfold abort
  split_ifs <;> rfl

theorem arm_keep {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {a sr : Arg}
    {rtt : Option ℚ} {p : Arg} : KeepRes s (arm e w s role a sr rtt p).1 := by
  refine ⟨?_, fun hd => by simp [arm, hd]⟩
  unfold arm
  repeat' split
  all_goals first | rfl | (dsimp only [_save]; split <;> rfl)

theorem commit_keep {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {dev : D}
    {cb sb : B} : KeepRes s (commit e w s role dev cb sb).1 := by
  refine ⟨?_, fun hd => by simp [commit, hd]⟩
  unfold commit
  repeat' split
  all_goals rfl

theorem viewOr_rf {e : Env B D} {w : World D} {s : Doc B D} {role : Role}
    {x : Except (ℕ × Err) (Doc B D)} (h0 : ResultFacts e s)
    (hx : ∀ s', x = .ok s' → ResultFacts e s') : ResultFacts e (viewOr e w s role x).1 := by
  unfold viewOr
  split
  · exact hx _ rfl
  · exact h0

/-- `/transcript` keeps `ResultFacts`: it returns the doc, the reject finalize of part a (5), or
`afterStore` (part b), which needs `attempt ≤ 1` from `Core`. -/
theorem ResultFacts_transcript {e : Env B D} {c : ℕ} {w : World D} {s : Doc B D} {role : Role}
    {dev : D} {tb sb : B} (hc : Core e c s) (h1 : ResultFacts e s) :
    ResultFacts e (transcript e w s role dev tb sb).1 := by
  rcases transcript_cases e w s role dev tb sb with hx | ⟨rsn, hns, hx⟩ | ⟨td, _, _, hx⟩
  · rw [hx]; exact h1
  · rw [hx]; exact ResultFacts_transcript_reject hns
  · rw [hx]; exact ResultFacts_afterStore hc.attempt_le h1

/-- One request keeps `ResultFacts`, on a doc that has `Inv`. The proof follows `step_inv`: a
finished doc does not move (`M1_terminal`); otherwise the load has it (part a, (3)), join, confirm,
abort, arm and commit either return the loaded doc or keep its record field on a doc that has no
record yet, `/fail` leaves its role not submitted (part a, (4)), and `/transcript` is part a, (5),
or part b. -/
theorem ResultFacts_step {e : Env B D} {c : ℕ} {s : Doc B D} {w : World D} (req : Req B D)
    (h : Inv e c s) (hcw : c ≤ w.now) (hf : ResultFacts e s) :
    ResultFacts e (step e w req s).1 := by
  by_cases hst : s.state = .done ∨ s.state = .aborted
  · exact ResultFacts_terminal req hst hf
  have hres : s.result = none := h.toCore.result_none (fun hd => hst (Or.inl hd))
  have hl := expire_inv (w := w) h hcw
  have h1 : ResultFacts e (_expire e w s) := ResultFacts_expire h hres
  have hk : ∀ s', KeepRes (_expire e w s) s' → ResultFacts e s' :=
    fun s' hk => KeepRes.rf hl.toCore h1 hk
  unfold step
  split
  · exact h1
  split
  · exact hf
  split
  · exact hf
  split
  · exact hf
  dsimp only [load]
  split
  · exact viewOr_rf h1 (fun s' hs' => hk s' (join_keep hs'))
  · split
    · exact h1
    · unfold handle
      split
      · exact h1
      · unfold result; split <;> exact h1
      · exact viewOr_rf h1 (fun s' hs' => hk s' (confirm_keep hs'))
      · exact viewOr_rf h1 (fun s' hs' => by
          simp only [Except.ok.injEq] at hs'
          subst hs'
          exact hk _ abort_keep)
      · exact hk _ arm_keep
      · exact hk _ commit_keep
      · exact ResultFacts_transcript hl.toCore h1
      · exact viewOr_rf h1 (fun s' hs' => ResultFacts_fail hs')

/-- **resultFacts.** Every reachable doc has `ResultFacts`: if it holds a record and both roles
submitted, both stored transcripts decode, and `combine` on them and the stored calibration does
one of three things. It returns a verdict, and the record has that verdict, reason and flight. Or it
returns no verdict, and the record has the same reason only: it says NOT_NEAR with flight `none`,
the doc is at attempt 1, and the last attempts row has `combine`'s `by_`; `combine`'s flight is not
pinned there. Or it rejects, and the record says NOT_NEAR with that reason. It needs no key
injectivity. -/
theorem resultFacts {e : Env B D} {c : ℕ} {s : Doc B D} (h : Reachable e c s) :
    ResultFacts e s := by
  induction h with
  | create w host sid nonce seed token => exact ResultFacts_create e w host sid nonce seed token
  | step w req hr hcw ih => exact ResultFacts_step req (M9 hr) hcw ih

/-! ## Facts about `combine` used by the rows -/

omit [DecidableEq D] in
/-- `combine` rejects only with `transcript_mismatch` (its three pairing guards). -/
theorem combine_reject_mismatch {ta tb : Transcript B} {cal : Option (Role → Option ℤ)}
    {rsn : Reason} (h : combine ta tb cal = .error (.reject rsn)) : rsn = .transcript_mismatch := by
  unfold combine at h
  split_ifs at h <;> cases h <;> rfl

omit [DecidableEq D] in
/-- A `combine` result with a verdict comes from `decide`'s two verdict branches: no `by_`, and
either NEAR with no reason or NOT_NEAR with `too_far`. -/
theorem combine_some_shape {ta tb : Transcript B} {cal : Option (Role → Option ℤ)}
    {out : CombineOut} {v : Verdict} (h : combine ta tb cal = .ok out) (hv : out.verdict = some v) :
    out.by_ = none ∧ ((out.verdict = some .NEAR ∧ out.reason = none) ∨
      (out.verdict = some .NOT_NEAR ∧ out.reason = some .too_far)) := by
  unfold combine at h
  split_ifs at h <;> cases h
  all_goals try (exfalso; simp at hv; done)
  generalize flight_exact ta.half ta.sample_rate tb.half tb.sample_rate = f at hv ⊢
  simp only [ServerFv.decide] at hv ⊢
  split_ifs at hv ⊢ <;> simp_all

omit [DecidableEq D] in
/-- A `verify_record` that returns a value got it from `combine` on some transcripts and
calibration. -/
theorem verify_record_ok_combine {p : Prims B} {rr : ResultRecord B} {out : CombineOut}
    (h : verify_record p rr = .ok out) :
    ∃ (ta tb : Transcript B) (cal : Option (Role → Option ℤ)), combine ta tb cal = .ok out := by
  unfold verify_record at h
  split at h
  · cases h
  split at h
  · cases h
  exact ⟨_, _, _, h⟩

/-! ## The rows -/

/-- How a `verify_record` result `out` matches the record `rc` of doc `s`: a verdict from replay is
the record's, with the same reason and flight; or replay gives no verdict, the record says NOT_NEAR
with the same reason and no flight, the doc is at attempt 1, and the last attempts row names
replay's `by_`. In that second case replay's flight is left free and only the reason matches.
Same shape as inside `ResultFacts`. -/
def RowMatch (s : Doc B D) (rc : Record B D) (out : CombineOut) : Prop :=
  (∃ v, out.verdict = some v ∧ rc.verdict = v ∧ rc.reason = out.reason ∧
      rc.flight_cm = out.flight_cm) ∨
  (out.verdict = none ∧ rc.verdict = .NOT_NEAR ∧ rc.reason = out.reason ∧
      rc.flight_cm = none ∧ s.attempt = 1 ∧ (s.attempts.getLast?).map (·.by_) = some out.by_)

/-- On a reachable doc, a record with both transcripts present means both roles submitted. -/
theorem submitted_of_present {e : Env B D} {c : ℕ} {s : Doc B D} {rc : Record B D}
    (h : Reachable e c s) (hr : s.result = some rc) (hA : rc.transcripts .A ≠ none)
    (hB : rc.transcripts .B ≠ none) : all2 s.submitted = true := by
  have hc : Core e c s := (M9 h).toCore
  have hs : ∀ r, rc.transcripts r ≠ none → s.submitted r = true := by
    intro r hn
    apply (hc.sub_iff r).2
    rw [hc.rec_eq rc hr] at hn
    rcases ht : (s.per_role r).tx with _ | td
    · simp [_record, ht] at hn
    · simp
  simp [all2, hs .A hA, hs .B hB]

/-- **V7, both transcripts in.** Take a reachable doc `s` whose final record `rc` has both
transcripts. Then `toRR e rc` exists, and `verify_record` on it either returns `out` matching the
record (`RowMatch`), or rejects with `transcript_mismatch` and the record says NOT_NEAR with that
same reason.

No key injectivity is assumed; `V7_both_inj` drops the reject case under it. With a replay verdict
it pins verdict, reason and flight; with no replay verdict only the reason, plus `by_` through the
doc's last attempts row. -/
theorem V7_both {e : Env B D} {c : ℕ} {s : Doc B D} {rc : Record B D} (h : Reachable e c s)
    (hr : s.result = some rc) (hA : rc.transcripts .A ≠ none) (hB : rc.transcripts .B ≠ none) :
    ∃ rr, toRR e rc = some rr ∧
      ((∃ out, verify_record e.p rr = .ok out ∧ RowMatch s rc out) ∨
       (verify_record e.p rr = .error (.reject .transcript_mismatch) ∧ rc.verdict = .NOT_NEAR ∧
          rc.reason = some .transcript_mismatch)) := by
  have hall := submitted_of_present h hr hA hB
  obtain ⟨ta, tb, hsA, hsB, hx⟩ := resultFacts h rc hr hall
  obtain ⟨rr, ta', tb', hrr, hsA', hsB', heq⟩ := V7_replay_eq h hr hA hB
  rw [hsA] at hsA'; cases hsA'
  rw [hsB] at hsB'; cases hsB'
  refine ⟨rr, hrr, ?_⟩
  rw [heq]
  rcases hx with hx | ⟨rsn, hc, hv, hrs⟩
  · exact Or.inl hx
  · have := combine_reject_mismatch hc
    subst this
    exact Or.inr ⟨hc, hv, hrs⟩

/-- **V7, both transcripts in, with distinct keys.** Same as `V7_both`, assuming
`Function.Injective e.pk` (the "A != B" of M12, as in `combine_guard_unreachable`). Then the replay
never rejects: it returns `out` and `RowMatch` holds. -/
theorem V7_both_inj {e : Env B D} {c : ℕ} {s : Doc B D} {rc : Record B D}
    (hinj : Function.Injective e.pk) (h : Reachable e c s) (hr : s.result = some rc)
    (hA : rc.transcripts .A ≠ none) (hB : rc.transcripts .B ≠ none) :
    ∃ rr out, toRR e rc = some rr ∧ verify_record e.p rr = .ok out ∧ RowMatch s rc out := by
  obtain ⟨rr, hrr, hx⟩ := V7_both h hr hA hB
  rcases hx with ⟨out, ho, hm⟩ | ⟨hrej, -, -⟩
  · exact ⟨rr, out, hrr, ho, hm⟩
  · exfalso
    have hall := submitted_of_present h hr hA hB
    obtain ⟨ta, tb, out, hsA, hsB, hc⟩ := combine_guard_unreachable hinj (M9 h).toCore hall
    obtain ⟨rr', ta', tb', hrr', hsA', hsB', heq⟩ := V7_replay_eq h hr hA hB
    rw [hrr] at hrr'; cases hrr'
    rw [hsA] at hsA'; cases hsA'
    rw [hsB] at hsB'; cases hsB'
    rw [hrej, hc] at heq
    cases heq

/-- **V7 row 2, too_far.** A reachable final record with both transcripts and reason `too_far`
says NOT_NEAR, and its replay returns exactly `⟨rc.flight_cm, some NOT_NEAR, some too_far, none⟩`:
the record's own flight, verdict NOT_NEAR, reason `too_far`, no `by`. No key injectivity needed. -/
theorem V7_verdict_row {e : Env B D} {c : ℕ} {s : Doc B D} {rc : Record B D}
    (h : Reachable e c s) (hr : s.result = some rc) (hA : rc.transcripts .A ≠ none)
    (hB : rc.transcripts .B ≠ none) (hreason : rc.reason = some .too_far) :
    rc.verdict = .NOT_NEAR ∧ ∃ rr, toRR e rc = some rr ∧
      verify_record e.p rr = .ok ⟨rc.flight_cm, some .NOT_NEAR, some .too_far, none⟩ := by
  obtain ⟨rr, hrr, hx⟩ := V7_both h hr hA hB
  rcases hx with ⟨out, ho, ⟨v, hv, hrv, hrs, hfl⟩ | ⟨hv, -, hrs, -⟩⟩ | ⟨-, -, hrs⟩
  · obtain ⟨ta, tb, cal, hc⟩ := verify_record_ok_combine ho
    obtain ⟨hby, hsh⟩ := combine_some_shape hc hv
    have hor : out.reason = some .too_far := by rw [← hrs, hreason]
    rcases hsh with ⟨-, hn⟩ | ⟨hvn, -⟩
    · rw [hn] at hor; cases hor
    rw [hv] at hvn; cases hvn
    refine ⟨hrv, rr, hrr, ?_⟩
    rw [ho]
    obtain ⟨fl, vd, rs, b⟩ := out
    simp only at hv hor hby hfl
    subst hv hor hby hfl
    rfl
  · exfalso
    obtain ⟨ta, tb, cal, hc⟩ := verify_record_ok_combine ho
    have hret := combine_none_retry hc hv
    rw [← hrs, hreason] at hret
    simp [isRetry, RETRY_REASONS] at hret
  · rw [hreason] at hrs; cases hrs

/-- **V7 rows 3 and 4, impossible_flight and self_timestamp_mismatch.** A reachable final record with
both transcripts and one of those two reasons came from a final no-verdict attempt: its replay
returns `out` with no verdict and the record's reason, the record says NOT_NEAR with no flight, the
doc and record are at attempt 1, and the doc's last attempts row names replay's `by_`. Spec row 3:
replay gives no verdict where the record says NOT_NEAR, and this states exactly that. No key
injectivity needed. -/
theorem V7_failed_row {e : Env B D} {c : ℕ} {s : Doc B D} {rc : Record B D}
    (h : Reachable e c s) (hr : s.result = some rc) (hA : rc.transcripts .A ≠ none)
    (hB : rc.transcripts .B ≠ none)
    (hrsn : rc.reason = some .impossible_flight ∨ rc.reason = some .self_timestamp_mismatch) :
    ∃ rr out, toRR e rc = some rr ∧ verify_record e.p rr = .ok out ∧ out.verdict = none ∧
      out.reason = rc.reason ∧ rc.verdict = .NOT_NEAR ∧ rc.flight_cm = none ∧ s.attempt = 1 ∧
      rc.attempt = 1 ∧ (s.attempts.getLast?).map (·.by_) = some out.by_ := by
  have hatt : rc.attempt = s.attempt := by
    have := congrArg Record.attempt ((M9 h).rec_eq rc hr)
    simpa [_record] using this
  obtain ⟨rr, hrr, hx⟩ := V7_both h hr hA hB
  rcases hx with ⟨out, ho, ⟨v, hv, -, hrs, -⟩ | ⟨hv, hvn, hrs, hfl, h1, hby⟩⟩ | ⟨-, -, hrs⟩
  · exfalso
    obtain ⟨ta, tb, cal, hc⟩ := verify_record_ok_combine ho
    obtain ⟨-, hsh⟩ := combine_some_shape hc hv
    rw [← hrs] at hsh
    rcases hrsn with hq | hq <;> rw [hq] at hsh <;> simp at hsh
  · exact ⟨rr, out, hrr, ho, hv, hrs.symm, hvn, hfl, h1, by rw [hatt, h1], hby⟩
  · rcases hrsn with hq | hq <;> rw [hq] at hrs <;> cases hrs

/-- **V7, the reject row with both transcripts in.** A reachable final record with both transcripts
whose reason is neither a retry reason nor `too_far` replays to a reject with that same reason. By
`V7_both` such a reason can only be `transcript_mismatch`, and by `V7_both_inj` such a record does
not exist when keys are distinct; this row is for an `e` without that assumption. -/
theorem V7_rejected_both {e : Env B D} {c : ℕ} {s : Doc B D} {rc : Record B D} {rsn : Reason}
    (h : Reachable e c s) (hr : s.result = some rc) (hA : rc.transcripts .A ≠ none)
    (hB : rc.transcripts .B ≠ none) (hrs : rc.reason = some rsn)
    (hnr : isRetry (some rsn) = false) (hnt : rsn ≠ .too_far) :
    ∃ rr, toRR e rc = some rr ∧ verify_record e.p rr = .error (.reject rsn) := by
  obtain ⟨rr, hrr, hx⟩ := V7_both h hr hA hB
  refine ⟨rr, hrr, ?_⟩
  rcases hx with ⟨out, ho, ⟨v, hv, -, hrs', -⟩ | ⟨hv, -, hrs', -⟩⟩ | ⟨hrej, -, hrs'⟩
  · exfalso
    obtain ⟨ta, tb, cal, hc⟩ := verify_record_ok_combine ho
    obtain ⟨-, hsh⟩ := combine_some_shape hc hv
    rw [← hrs', hrs] at hsh
    rcases hsh with ⟨-, hq⟩ | ⟨-, hq⟩
    · cases hq
    · cases hq; exact hnt rfl
  · exfalso
    obtain ⟨ta, tb, cal, hc⟩ := verify_record_ok_combine ho
    have hret := combine_none_retry hc hv
    rw [← hrs', hrs, hnr] at hret
    cases hret
  · rw [hrs] at hrs'; cases hrs'; exact hrej

/-- **V7, the whole table on a reachable final record.** Either a transcript is missing and every
replay of the record rejects (row 5), or both are in and `V7_both` holds (rows 1 to 4, and the
reject case). In rows 1 and 2 verdict, reason and flight match `verify_record`; in rows 3 and 4
only the reason does (see `RowMatch`). Row 5 says nothing when `toRR e rc = none`, that is when a
device row is missing (`toRR_eq_none_iff`); Python raises `KeyError` there. Nothing about the air
(CN1) or fields `verify_record` never reads. -/
theorem V7_session {e : Env B D} {c : ℕ} {s : Doc B D} {rc : Record B D} (h : Reachable e c s)
    (hr : s.result = some rc) :
    ((rc.transcripts .A = none ∨ rc.transcripts .B = none) ∧
      ∀ rr, toRR e rc = some rr → ∃ rsn, verify_record e.p rr = .error (.reject rsn)) ∨
    (∃ rr, toRR e rc = some rr ∧
      ((∃ out, verify_record e.p rr = .ok out ∧ RowMatch s rc out) ∨
       (verify_record e.p rr = .error (.reject .transcript_mismatch) ∧ rc.verdict = .NOT_NEAR ∧
          rc.reason = some .transcript_mismatch))) := by
  by_cases hm : rc.transcripts .A = none ∨ rc.transcripts .B = none
  · exact Or.inl ⟨hm, V7_missing h hr hm⟩
  · rw [not_or] at hm
    exact Or.inr (V7_both h hr hm.1 hm.2)

/-! ## What the rows leave open, made precise -/

omit [DecidableEq B] [DecidableEq D] in
/-- `toRR` is missing exactly when a device row is missing from the record. In that case
`V7_missing` and the row-5 part of `V7_session` say nothing; Python's `verify_record` would raise
`KeyError` at `verdict.py:177`, which this model does not have. -/
theorem toRR_eq_none_iff (e : Env B D) (rc : Record B D) :
    toRR e rc = none ↔ rc.devices .A = none ∨ rc.devices .B = none := by
  rcases hA : rc.devices .A with _ | dA <;> rcases hB : rc.devices .B with _ | dB <;>
    simp [toRR, hA, hB]

omit [DecidableEq D] in
/-- A `combine` result with no verdict is one of two shapes: `self_timestamp_mismatch` with no
flight, or `impossible_flight` with a flight number. -/
theorem combine_none_shape {ta tb : Transcript B} {cal : Option (Role → Option ℤ)}
    {out : CombineOut} (h : combine ta tb cal = .ok out) (hv : out.verdict = none) :
    (out.reason = some .self_timestamp_mismatch ∧ out.flight_cm = none) ∨
      (out.reason = some .impossible_flight ∧ ∃ f, out.flight_cm = some f) := by
  unfold combine at h
  split_ifs at h <;> cases h
  all_goals try (left; exact ⟨rfl, rfl⟩)
  generalize flight_exact ta.half ta.sample_rate tb.half tb.sample_rate = f at hv ⊢
  simp only [ServerFv.decide] at hv ⊢
  split_ifs at hv ⊢; simp_all

/-- **V7 rows 3 and 4, replay's flight.** In the setting of `V7_failed_row`, replay's flight is a
number for `impossible_flight` (spec row 3) and `none` for `self_timestamp_mismatch` (row 4). It
does not say which number; the record's own flight is `none` in both rows. -/
theorem V7_failed_row_flight {e : Env B D} {c : ℕ} {s : Doc B D} {rc : Record B D}
    (h : Reachable e c s) (hr : s.result = some rc) (hA : rc.transcripts .A ≠ none)
    (hB : rc.transcripts .B ≠ none)
    (hrsn : rc.reason = some .impossible_flight ∨ rc.reason = some .self_timestamp_mismatch) :
    ∃ rr out, toRR e rc = some rr ∧ verify_record e.p rr = .ok out ∧ out.verdict = none ∧
      out.reason = rc.reason ∧
      (rc.reason = some .impossible_flight → ∃ f, out.flight_cm = some f) ∧
      (rc.reason = some .self_timestamp_mismatch → out.flight_cm = none) := by
  obtain ⟨rr, out, hrr, ho, hv, hrs, -⟩ := V7_failed_row h hr hA hB hrsn
  refine ⟨rr, out, hrr, ho, hv, hrs, ?_, ?_⟩
  · intro hq
    obtain ⟨ta, tb, cal, hc⟩ := verify_record_ok_combine ho
    rcases combine_none_shape hc hv with ⟨hq', -⟩ | ⟨-, hf⟩
    · rw [hrs, hq] at hq'; cases hq'
    · exact hf
  · intro hq
    obtain ⟨ta, tb, cal, hc⟩ := verify_record_ok_combine ho
    rcases combine_none_shape hc hv with ⟨-, hf⟩ | ⟨hq', -⟩
    · exact hf
    · rw [hrs, hq] at hq'; cases hq'

/-! ## Rows 3 and 4 can occur

Two concrete runs on the toy setting of `Machine.lean`'s `Witness` section. Each fails twice and
finalizes at attempt 1 with a no-verdict reason. No audio exists anywhere (CN1). -/

namespace V7Witness

open Witness

/-- Halves that give an impossible flight (about -357 cm) at every attempt. -/
def Himp : ℕ → Role → ℤ := fun _ r => match r with | .A => -1000 | .B => 0

/-- Both attempts of `Witness.retry1Trace`, with `Himp`. -/
def impDoc := run (env Himp) start retry1Trace

/-- **Row 3 can occur.** A run ends done at attempt 1 with a record that says NOT_NEAR, reason
`impossible_flight`, flight `none`, and both transcripts in. -/
theorem reaches_impossible_final : Reachable (env Himp) (lastTime 0 retry1Trace) impDoc ∧
    impDoc.state = .done ∧ impDoc.attempt = 1 ∧
    impDoc.result.map (·.verdict) = some .NOT_NEAR ∧
    impDoc.result.map (·.reason) = some (some .impossible_flight) ∧
    impDoc.result.map (·.flight_cm) = some none ∧
    impDoc.result.map (fun rc => (rc.transcripts .A).isSome && (rc.transcripts .B).isSome) =
      some true := by
  refine ⟨run_reachable (Reachable.create (W 0) 1 5 9 "seed" "t") _ (by decide), ?_, ?_, ?_, ?_,
    ?_, ?_⟩ <;> decide +kernel

/-- `Witness.tx` with a self check offset of 1000 s for A, so A's self check fails. -/
def txS (role : Role) (k raw : ℕ) : Transcript ℕ :=
  { tx Hnear role k raw with self_os_delta := match role with | .A => 48000000 | .B => 0 }

/-- `Witness.env Hnear` with `txS` as the transcript decoder. -/
def envS : Env ℕ ℕ :=
  { env Hnear with
    p := { (env Hnear).p with
      decode_transcript := fun raw =>
        if raw = 11 then some (txS .A 0 raw) else if raw = 21 then some (txS .B 0 raw)
        else if raw = 31 then some (txS .A 1 raw) else if raw = 41 then some (txS .B 1 raw)
        else none } }

/-- Both attempts of `Witness.retry1Trace`, in `envS`. -/
def selfDoc := run envS start retry1Trace

/-- **Row 4 can occur.** A run ends done at attempt 1 with a record that says NOT_NEAR, reason
`self_timestamp_mismatch`, flight `none`, and both transcripts in. -/
theorem reaches_self_mismatch_final : Reachable envS (lastTime 0 retry1Trace) selfDoc ∧
    selfDoc.state = .done ∧ selfDoc.attempt = 1 ∧
    selfDoc.result.map (·.verdict) = some .NOT_NEAR ∧
    selfDoc.result.map (·.reason) = some (some .self_timestamp_mismatch) ∧
    selfDoc.result.map (·.flight_cm) = some none ∧
    selfDoc.result.map (fun rc => (rc.transcripts .A).isSome && (rc.transcripts .B).isSome) =
      some true := by
  refine ⟨run_reachable (Reachable.create (W 0) 1 5 9 "seed" "t") _ (by decide), ?_, ?_, ?_, ?_,
    ?_, ?_⟩ <;> decide +kernel

/-- The hypotheses of `V7_failed_row` hold together on a reachable doc: from a reachable doc whose
record has both transcripts and a row-3 or row-4 reason, its conclusion follows. Applied to
`impDoc` and `selfDoc`. -/
theorem failed_row_instances :
    (∃ rc, impDoc.result = some rc ∧ rc.transcripts .A ≠ none ∧ rc.transcripts .B ≠ none ∧
      rc.reason = some .impossible_flight ∧
      ∃ rr out, toRR (env Himp) rc = some rr ∧ verify_record (env Himp).p rr = .ok out ∧
        out.verdict = none ∧ out.reason = rc.reason) ∧
    (∃ rc, selfDoc.result = some rc ∧ rc.transcripts .A ≠ none ∧ rc.transcripts .B ≠ none ∧
      rc.reason = some .self_timestamp_mismatch ∧
      ∃ rr out, toRR envS rc = some rr ∧ verify_record envS.p rr = .ok out ∧
        out.verdict = none ∧ out.reason = rc.reason) := by
  obtain ⟨hR1, -, -, -, hrs1, -, htx1⟩ := reaches_impossible_final
  obtain ⟨hR2, -, -, -, hrs2, -, htx2⟩ := reaches_self_mismatch_final
  constructor
  · rcases hres : impDoc.result with _ | rc
    · rw [hres] at hrs1; cases hrs1
    rw [hres] at hrs1 htx1
    simp only [Option.map_some, Option.some.injEq, Bool.and_eq_true, Option.isSome_iff_ne_none]
      at hrs1 htx1
    obtain ⟨rr, out, hrr, ho, hv, hrs, -⟩ := V7_failed_row hR1 hres htx1.1 htx1.2 (Or.inl hrs1)
    exact ⟨rc, rfl, htx1.1, htx1.2, hrs1, rr, out, hrr, ho, hv, hrs⟩
  · rcases hres : selfDoc.result with _ | rc
    · rw [hres] at hrs2; cases hrs2
    rw [hres] at hrs2 htx2
    simp only [Option.map_some, Option.some.injEq, Bool.and_eq_true, Option.isSome_iff_ne_none]
      at hrs2 htx2
    obtain ⟨rr, out, hrr, ho, hv, hrs, -⟩ := V7_failed_row hR2 hres htx2.1 htx2.2 (Or.inr hrs2)
    exact ⟨rc, rfl, htx2.1, htx2.2, hrs2, rr, out, hrr, ho, hv, hrs⟩

end V7Witness

end Machine
end ServerFv

#print axioms ServerFv.Machine.ResultFacts_step
#print axioms ServerFv.Machine.resultFacts
#print axioms ServerFv.Machine.combine_reject_mismatch
#print axioms ServerFv.Machine.combine_some_shape
#print axioms ServerFv.Machine.V7_both
#print axioms ServerFv.Machine.V7_both_inj
#print axioms ServerFv.Machine.V7_verdict_row
#print axioms ServerFv.Machine.V7_failed_row
#print axioms ServerFv.Machine.V7_rejected_both
#print axioms ServerFv.Machine.V7_session
#print axioms ServerFv.Machine.toRR_eq_none_iff
#print axioms ServerFv.Machine.combine_none_shape
#print axioms ServerFv.Machine.V7_failed_row_flight
#print axioms ServerFv.Machine.V7Witness.reaches_impossible_final
#print axioms ServerFv.Machine.V7Witness.reaches_self_mismatch_final
#print axioms ServerFv.Machine.V7Witness.failed_row_instances
