import ServerFv.Machine

/-!
# X2, the `/fail` and bad-transcript ways (`spec.md` section 4, X2 rows 2 and 3)

`spec.md` X2: one member can end a session as NOT_NEAR with no measurement. This file proves the
`/fail` row and the bad-transcript row of that table, on the handlers of `Machine.lean`. The
`/abort` row is in `X2.lean`.

**Level.** Every statement here is about a handler (`fail_`, `transcript`, `handle`) run on the
document after the load. None of them says the load is the identity on that document. That wrap
(now within `created + 600000`, and not started past its deadline) is not done here. So "the
second `/fail`" below means the second handler call on the document the first one stored, with no
expiry in between.

**What NOT_NEAR means here.** Each final record below has `flight_cm = none`: no flight was
computed. So NOT_NEAR from these ways is no finding about distance. Nothing here is about the air
(CN1).
-/

set_option linter.style.whitespace false
set_option linter.style.longLine false
set_option linter.style.header false
set_option linter.unusedVariables false
set_option linter.unusedSimpArgs false
set_option linter.style.setOption false
set_option linter.flexible false
set_option linter.style.multiGoal false
set_option linter.style.cases false
set_option linter.unusedSectionVars false
set_option linter.unusedTactic false
set_option linter.unreachableTactic false

namespace ServerFv
namespace Machine

variable {B D : Type} [DecidableEq B] [DecidableEq D]

/-! ## `/fail` -/

/-- A `/fail` that passes its guards stores `_failed` on the document with the sender's fail row. -/
theorem X2_fail_ok {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {rsn : Reason}
    (hst : s.state = .confirmed ∨ s.state = .started) (hns : s.submitted role = false)
    (hp : rsn ∈ PHONE_REASONS) :
    fail_ e w s role (.int s.attempt) (some rsn) =
      .ok (_failed e w (failStore s role (rsn, w.now)) (some rsn) (some role)) := by
  have hst' : ¬ ¬ (s.state = .confirmed ∨ s.state = .started) := fun h => h hst
  simp [fail_, hp, _int, _stale, hns, hst']

/-- **X2, `/fail` that ends the session.** On a confirmed or started document, a member who has not
sent a transcript posts `/fail` with the current attempt and a phone reason. If that reason is not a
retry reason, or this is already attempt 1 or later, the stored document is `done` with a NOT_NEAR
record whose reason is the sender's word and whose `flight_cm` is `none`. It pins the handler only:
the load before it is not covered, and it says nothing about what the other member did or can do. -/
theorem X2_fail_final {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {rsn : Reason}
    (hst : s.state = .confirmed ∨ s.state = .started) (hns : s.submitted role = false)
    (hp : rsn ∈ PHONE_REASONS) (hfin : rsn ∉ RETRY_REASONS ∨ 1 ≤ s.attempt) :
    ∃ s' rc, fail_ e w s role (.int s.attempt) (some rsn) = .ok s' ∧ s'.state = .done ∧
      s'.result = some rc ∧ rc.verdict = .NOT_NEAR ∧ rc.reason = some rsn ∧ rc.flight_cm = none := by
  have hd : _failed e w (failStore s role (rsn, w.now)) (some rsn) (some role) =
      _finalize e w (failStore s role (rsn, w.now)) .NOT_NEAR (some rsn) none .failed (some role) := by
    unfold _failed
    split
    · rename_i hc
      rcases hfin with h | h
      · simp [isRetry, h] at hc
      · simp [failStore, Nat.blt] at hc; omega
    · rfl
  exact ⟨_, _, (X2_fail_ok hst hns hp).trans (by rw [hd]), rfl, rfl, rfl, rfl, rfl⟩

/-- **X2, `partner_mismatch` once.** The same as `X2_fail_final` with no condition on the attempt:
`partner_mismatch` is a phone reason and not a retry reason, so one `/fail` with it ends the session
as NOT_NEAR with no flight. -/
theorem X2_fail_partner_mismatch {e : Env B D} {w : World D} {s : Doc B D} {role : Role}
    (hst : s.state = .confirmed ∨ s.state = .started) (hns : s.submitted role = false) :
    ∃ s' rc, fail_ e w s role (.int s.attempt) (some .partner_mismatch) = .ok s' ∧ s'.state = .done ∧
      s'.result = some rc ∧ rc.verdict = .NOT_NEAR ∧ rc.reason = some .partner_mismatch ∧
      rc.flight_cm = none :=
  X2_fail_final hst hns (by decide) (Or.inl (by decide))

/-- **X2, the first of two `/fail`s.** At attempt 0, a `/fail` with a reason that is both a phone
reason and a retry reason moves the document to `confirmed`, attempt 1, no result, nobody submitted.
`hres` (no result yet) is needed because `next_attempt` keeps `result` as it was. -/
theorem X2_fail_retry {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {rsn : Reason}
    (hst : s.state = .confirmed ∨ s.state = .started) (hns : s.submitted role = false)
    (hp : rsn ∈ PHONE_REASONS) (hr : rsn ∈ RETRY_REASONS) (h0 : s.attempt = 0)
    (hres : s.result = none) :
    ∃ s', fail_ e w s role (.int s.attempt) (some rsn) = .ok s' ∧ s'.state = .confirmed ∧
      s'.attempt = 1 ∧ s'.result = none ∧ (∀ r, s'.submitted r = false) := by
  have hd : _failed e w (failStore s role (rsn, w.now)) (some rsn) (some role) =
      next_attempt (failStore s role (rsn, w.now)) (some rsn) (some role) := by
    unfold _failed
    split
    · rfl
    · rename_i hc
      simp [isRetry, hr, failStore, h0, Nat.blt] at hc
  refine ⟨_, (X2_fail_ok hst hns hp).trans (by rw [hd]), rfl, ?_, ?_, fun _ => rfl⟩
  · simp [next_attempt, _save, failStore, h0]
  · simp [next_attempt, _save, failStore, hres]

/-- **X2, `/fail` twice, at handler level.** Start from a confirmed or started document at attempt 0
with no result, where `role1` has not submitted. `role1` posts `/fail` with a reason that is a phone
reason and a retry reason. On the document that stores, any member `role2` (the same one or the other)
posts `/fail` with attempt 1 and any phone reason. The second stored document is `done` with a NOT_NEAR
record, that reason, and no flight. The two calls are `handle` on the stored documents: no load runs
between them, so expiry in between is not covered. -/
theorem X2_fail_twice {e : Env B D} {w w' : World D} {s : Doc B D} {role1 role2 : Role} {dev1 dev2 : D}
    {r1 r2 : Reason}
    (hst : s.state = .confirmed ∨ s.state = .started) (hns : s.submitted role1 = false)
    (h0 : s.attempt = 0) (hres : s.result = none)
    (hp1 : r1 ∈ PHONE_REASONS) (hr1 : r1 ∈ RETRY_REASONS) (hp2 : r2 ∈ PHONE_REASONS) :
    let s1 := (handle e w s role1 dev1 (.fail_ (.int 0) (some r1))).1
    let s2 := (handle e w' s1 role2 dev2 (.fail_ (.int 1) (some r2))).1
    s2.state = .done ∧ ∃ rc, s2.result = some rc ∧ rc.verdict = .NOT_NEAR ∧ rc.reason = some r2 ∧
      rc.flight_cm = none := by
  obtain ⟨s1, h1, hs1, ha1, _, hsub1⟩ := X2_fail_retry (e := e) (w := w) hst hns hp1 hr1 h0 hres
  rw [h0] at h1
  obtain ⟨s2, rc, h2, hs2, hrc, hv, hrs, hfl⟩ :=
    X2_fail_final (e := e) (w := w') (role := role2) (Or.inl hs1) (hsub1 role2) hp2 (Or.inr (by omega))
  rw [ha1] at h2
  simp only [handle, viewOr]
  simp only [Nat.cast_zero, Nat.cast_one] at h1 h2
  rw [h1]
  simp only
  rw [h2]
  exact ⟨hs2, rc, hrc, hv, hrs, hfl⟩

/-- **X2, `/fail` needs confirmed or started.** On any other state, every `/fail` is refused, for any
attempt value and any reason. A refusal stores nothing: `viewOr` keeps the loaded document. -/
theorem X2_fail_needs {e : Env B D} {w : World D} {s : Doc B D} {role : Role}
    (hst : ¬ (s.state = .confirmed ∨ s.state = .started)) :
    ∀ a r, ∃ x, fail_ e w s role a r = .error x := by
  intro a r
  unfold fail_
  split
  · exact ⟨_, rfl⟩
  split
  · exact ⟨_, rfl⟩
  split
  · exact ⟨_, rfl⟩
  split
  · exact ⟨_, rfl⟩
  exact ⟨_, rfl⟩

/-! ## One bad transcript -/

/-- **X2, one bad transcript.** The guards of `transcript` in its order, as in
`combine_guard_on_request`: not caught as stale, state `started`, sender not submitted, sender
committed, partner key present. If the check of lines 430-437 rejects with `rsn`, the stored document
is `done` with a NOT_NEAR record, reason `rsn`, no flight, and the answer is a 400 with that reason.
It needs no injectivity of keys and no invariant. It says nothing about what makes the check reject;
`X2_bad_base64` gives one way that needs no measurement. -/
theorem X2_bad_transcript {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {dev : D}
    {tb sb pk' : B} {rsn : Reason}
    (hstale : staleTranscript e s role tb sb = false) (hs : s.state = .started)
    (hnsub : s.submitted role = false) (hcom : s.committed role = true)
    (hp : _pk e s (OTHER role) = some pk')
    (hc : checkNew e s role dev tb sb pk' = .error (.reject rsn)) :
    (transcript e w s role dev tb sb).1.state = .done ∧
    (∃ rc, (transcript e w s role dev tb sb).1.result = some rc ∧ rc.verdict = .NOT_NEAR ∧
      rc.reason = some rsn ∧ rc.flight_cm = none) ∧
    (transcript e w s role dev tb sb).2 = .error 400 (.reason rsn) := by
  unfold transcript
  simp only [hstale, hs, hnsub, hcom, hp, hc]
  exact ⟨rfl, ⟨_, rfl, rfl, rfl, rfl⟩, rfl⟩

/-- A transcript string that is not base64 is rejected by the check with `transcript_mismatch`.
So a member can send a bad transcript with no audio and no numbers at all. -/
theorem X2_bad_base64 {e : Env B D} {s : Doc B D} {role : Role} {dev : D} {tb sb pk' : B}
    (hb : e.b64d tb = none) :
    checkNew e s role dev tb sb pk' = .error (.reject .transcript_mismatch) := by
  simp [checkNew, hb]

/-- On a started document from a run, the partner's key is there: the guest is set (M9). -/
theorem X2_pk_started {e : Env B D} {c : ℕ} {s : Doc B D} (h : Core e c s) (hs : s.state = .started)
    (r : Role) : ∃ pk', _pk e s r = some pk' := by
  cases r
  · exact ⟨_, rfl⟩
  · obtain ⟨hg, _⟩ := h.row_started hs
    obtain ⟨g, hg'⟩ := Option.ne_none_iff_exists'.mp hg
    exact ⟨e.pk g, by simp [_pk, devId, hg']⟩

/-- **X2, a bad transcript needs started and the sender's commit.** If the state is not `started`, or
the sender has not committed, `transcript` stores nothing: the document is unchanged. With the sender
not yet submitted, the answer is also an error. On a run, `started` means both armed (M9
`row_started`), and a commit is only stored at `t0 + 1200` or later (M9 `com_ok`). This covers
refusals only. -/
theorem X2_tx_needs {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {dev : D} {tb sb : B}
    (hst : s.state ≠ .started ∨ s.committed role = false) :
    (transcript e w s role dev tb sb).1 = s := by
  unfold transcript
  split
  · rfl
  split
  · rfl
  split
  · split
    · split <;> rfl
    · rfl
  rcases hst with h | h
  · exact absurd ‹¬ s.state ≠ .started› (by simpa using h)
  · simp [h]

/-- The answer in the case of `X2_tx_needs`, when the sender has not submitted: an error. -/
theorem X2_tx_needs_error {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {dev : D} {tb sb : B}
    (hst : s.state ≠ .started ∨ s.committed role = false) (hnsub : s.submitted role = false) :
    ∃ st x, (transcript e w s role dev tb sb).2 = .error st x := by
  unfold transcript
  split
  · exact ⟨_, _, rfl⟩
  split
  · exact ⟨_, _, rfl⟩
  split
  · simp [hnsub] at *
  rcases hst with h | h
  · exact absurd ‹¬ s.state ≠ .started› (by simpa using h)
  · simp [h]

end Machine
end ServerFv

#print axioms ServerFv.Machine.X2_fail_ok
#print axioms ServerFv.Machine.X2_fail_final
#print axioms ServerFv.Machine.X2_fail_partner_mismatch
#print axioms ServerFv.Machine.X2_fail_retry
#print axioms ServerFv.Machine.X2_fail_twice
#print axioms ServerFv.Machine.X2_fail_needs
#print axioms ServerFv.Machine.X2_bad_transcript
#print axioms ServerFv.Machine.X2_bad_base64
#print axioms ServerFv.Machine.X2_pk_started
#print axioms ServerFv.Machine.X2_tx_needs
#print axioms ServerFv.Machine.X2_tx_needs_error
