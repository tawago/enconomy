import ServerFv.Machine

/-!
# The guards of `/fail` (README "Known gaps" item 13)

`fail_` in `Machine.lean` copies `sessions.py:464-477` at 9db1490. Before this file, three of its
guards survived a one-place mutant: the `already_submitted` check, the `attempt != s["attempt"]`
check and the `reason not in PHONE_REASONS` check. Each theorem below breaks under one of them.

**Level.** `fail_submitted_refused`, `fail_ok_attempt`, `fail_ok_reason`, `fail_ok_iff` are about the
handler run on a given document. `M10_no_fail_after_tx` is about one full `step` on the stored
document, load included: it says the stored document after the request is the loaded one, so the
`/fail` adds nothing beyond what the load (expiry) already does.

**What this does not say.** Nothing here is about the air (CN1). Nothing says which error code a
refused `/fail` gets, except where a statement names it.
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

/-- **What an accepted `/fail` needed.** `fail_` returns a document exactly when the reason is
present and in `PHONE_REASONS`, the attempt is an int equal to the document's attempt, the state is
confirmed or started, and this role has not sent a transcript. The document it returns is then
`_failed` on the document with the sender's fail row. It pins the handler only, on the document it
is given; it says nothing about the load before it. -/
theorem fail_ok_iff {e : Env B D} {w : World D} {s s' : Doc B D} {role : Role} {a : Arg}
    {rsn : Option Reason} :
    fail_ e w s role a rsn = .ok s' ↔
      ∃ r, rsn = some r ∧ r ∈ PHONE_REASONS ∧ _int a = some (s.attempt : ℤ) ∧
        (s.state = .confirmed ∨ s.state = .started) ∧ s.submitted role = false ∧
        s' = _failed e w (failStore s role (r, w.now)) (some r) (some role) := by
  constructor
  · intro h
    cases rsn with
    | none => simp [fail_] at h
    | some r =>
      by_cases hr : r ∈ PHONE_REASONS
      · cases hi : _int a with
        | none => simp [fail_, hr, hi] at h
        | some n =>
          by_cases hs : _stale s n = true
          · simp [fail_, hr, hi, hs] at h
          · by_cases hst : s.state = .confirmed ∨ s.state = .started
            · by_cases hn : n = (s.attempt : ℤ)
              · subst hn
                cases hsub : s.submitted role
                · simp [fail_, hr, hi, hs, hst, hsub] at h
                  exact ⟨r, rfl, hr, rfl, hst, rfl, h.symm⟩
                · simp [fail_, hr, hi, hs, hst, hsub] at h
              · simp [fail_, hr, hi, hs, hst, hn] at h
            · simp [fail_, hr, hi, hs, hst] at h
      · simp [fail_, hr] at h
  · rintro ⟨r, rfl, hr, hi, hst, hsub, rfl⟩
    have hs : _stale s (s.attempt : ℤ) = false := by simp [_stale]
    have hst' : ¬ ¬ (s.state = .confirmed ∨ s.state = .started) := fun h => h hst
    simp [fail_, hr, hi, hs, hsub, hst']

/-- **Gap 13, `already_submitted`.** Once this role's transcript is stored (`submitted role = true`),
`/fail` from that role never returns a document, whatever the attempt and reason. It does not say
which error comes back: an earlier guard (reason, attempt, stale, state) may fire first. -/
theorem fail_submitted_refused {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {a : Arg}
    {rsn : Option Reason} (h : s.submitted role = true) (s' : Doc B D) :
    fail_ e w s role a rsn ≠ .ok s' := by
  intro hok
  obtain ⟨_, _, _, _, _, hsub, _⟩ := fail_ok_iff.mp hok
  simp [h] at hsub

/-- **Gap 13, `already_submitted`, on the full request (M10 for `/fail`).** On a stored document whose
loaded form has the sender as a member with a transcript already stored, a well-formed `/fail`
request leaves the stored document equal to the loaded one, and the response is an error. So the
`/fail` writes nothing: no fail row, no `_failed`, no retry. It does not say the load itself is the
identity (expiry can still move the document), and it does not pin the error code. -/
theorem M10_no_fail_after_tx {e : Env B D} {w : World D} {s : Doc B D} {dev : D} {role : Role}
    {a : Arg} {rsn : Option Reason} (hr : role_of (load e w s) dev = some role)
    (hsub : (load e w s).submitted role = true) :
    (step e w (.api false (some dev) false (.op (.fail_ a rsn))) s).1 = load e w s ∧
      ∃ st c, (step e w (.api false (some dev) false (.op (.fail_ a rsn))) s).2 = .error st c := by
  cases hf : fail_ e w (load e w s) role a rsn with
  | ok s' => exact absurd hf (fail_submitted_refused hsub s')
  | error x =>
    obtain ⟨st, c⟩ := x
    simp [step, hr, handle, viewOr, hf]

/-- **Gap 13, the attempt check.** An accepted `/fail` carried an int attempt equal to the document's
current attempt: not a later one, not an older one, not a non-int. -/
theorem fail_ok_attempt {e : Env B D} {w : World D} {s s' : Doc B D} {role : Role} {a : Arg}
    {rsn : Option Reason} (h : fail_ e w s role a rsn = .ok s') : _int a = some (s.attempt : ℤ) := by
  obtain ⟨_, _, _, hi, _⟩ := fail_ok_iff.mp h
  exact hi

/-- **Gap 13, `PHONE_REASONS`.** An accepted `/fail` carried a reason, and that reason is one of the
six phone reasons. So a phone cannot end a session by `/fail` with a server-side reason such as
`too_far`, `aborted`, `timeout` or `impossible_flight`. -/
theorem fail_ok_reason {e : Env B D} {w : World D} {s s' : Doc B D} {role : Role} {a : Arg}
    {rsn : Option Reason} (h : fail_ e w s role a rsn = .ok s') : ∃ r, rsn = some r ∧ r ∈ PHONE_REASONS := by
  obtain ⟨r, hr, hp, _⟩ := fail_ok_iff.mp h
  exact ⟨r, hr, hp⟩

end Machine
end ServerFv

#print axioms ServerFv.Machine.fail_ok_iff
#print axioms ServerFv.Machine.fail_submitted_refused
#print axioms ServerFv.Machine.M10_no_fail_after_tx
#print axioms ServerFv.Machine.fail_ok_attempt
#print axioms ServerFv.Machine.fail_ok_reason
