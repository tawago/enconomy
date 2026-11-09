import ServerFv.Machine

/-!
# Three guards on `arm` and `view` (README "Known gaps" 13)

Before this file, three guards survived one-place Lean mutants: `arm`'s `rtt_min_ms` range
(`sessions.py:238-239`), `arm`'s refusal to re-arm at another `sample_rate` or `popt`
(`sessions.py:243-247`), and `view`'s nonce gate (`sessions.py:663`, `:667`). Each theorem below
breaks when its guard is taken out of `Machine.lean`.

**Level.** Each statement is about one handler (`arm` or `view`) on one document. They say nothing
about the load before it, the HTTP layer, or what a phone does with the answer.

**What is left out.** The model has no `early_nonce`, so `view` here is the plain-session rule
(`early_nonce` false). A session created with `early_nonce` shows the nonce from create on (`sessions.py:663`); that
branch is not modelled and nothing here is claimed about it. The `rtt_min_ms` value is only a guard:
it is checked, never used in a verdict, so `arm_ok_rtt` says only that an accepted arm carried a
number in `0..300`, not that the number was true.
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

/-! ## `arm` -/

/-- **`arm`'s rtt range.** If `arm` answers anything but an error, the `rtt_min_ms` it got passed
`rttOk`: a number in `0..MAX_RTT_MS`. This holds on both the first arm and the idempotent re-arm.
It does not say the number was measured honestly. -/
theorem arm_ok_rtt {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {a sr : Arg}
    {rtt : Option ℚ} {p : Arg}
    (h : ∀ st c, (arm e w s role a sr rtt p).2 ≠ .error st c) : rttOk rtt = true := by
  revert h
  simp only [arm]
  repeat' split
  all_goals simp_all

/-- The same, unfolded: an accepted arm carried some `x` with `0 ≤ x ≤ 300`. -/
theorem arm_ok_rtt_range {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {a sr : Arg}
    {rtt : Option ℚ} {p : Arg}
    (h : ∀ st c, (arm e w s role a sr rtt p).2 ≠ .error st c) :
    ∃ x, rtt = some x ∧ 0 ≤ x ∧ x ≤ (MAX_RTT_MS : ℚ) := by
  have hr := arm_ok_rtt h
  cases rtt with
  | none => simp [rttOk] at hr
  | some x => exact ⟨x, rfl, by simpa [rttOk] using hr⟩

/-- **No re-arm at another rate or `popt`.** If `arm` answers anything but an error, then after it
the role's stored arm row has exactly the `sample_rate` this call sent (as `srArg` reads it), and
the stored `popt` is the one this call sent (null read as 1). On a first arm that is what was just
written; on a re-arm it means the earlier row matched, so a second arm at another rate or `popt`
can't succeed. It says nothing about `armed_ms` or `cal_us`, and nothing about the other role. -/
theorem arm_rate_matches {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {a sr : Arg}
    {rtt : Option ℚ} {p : Arg}
    (h : ∀ st c, (arm e w s role a sr rtt p).2 ≠ .error st c) :
    ((arm e w s role a sr rtt p).1.per_role role).arm.map (·.sample_rate) = srArg sr ∧
      poptArg p = some (_popt (arm e w s role a sr rtt p).1 role) := by
  revert h
  simp only [arm]
  repeat' split
  all_goals simp_all [_save, upd, _popt]

/-- The re-arm form, as `sessions.py:12` states it: once a role is armed at rate `r0`, an `arm`
with a rate that reads as anything else is an error. -/
theorem arm_other_rate_error {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {a sr : Arg}
    {rtt : Option ℚ} {p : Arg} {r0 : ℕ}
    (harm : s.armed role = true) (hr0 : (s.per_role role).arm.map (·.sample_rate) = some r0)
    (hne : srArg sr ≠ some r0) :
    ∃ st c, (arm e w s role a sr rtt p).2 = .error st c := by
  by_contra hc
  push Not at hc
  have h := (arm_rate_matches (e := e) (w := w) (a := a) (rtt := rtt) (p := p) hc).1
  have hs : (arm e w s role a sr rtt p).1 = s := by
    revert hc
    simp only [arm]
    repeat' split
    all_goals simp_all
  rw [hs, hr0] at h
  exact hne h.symm

/-! ## `view` -/

/-- **`view`'s nonce gate.** The view shows a nonce only when both roles have confirmed. Plain
sessions only (see the module note). It does not say which nonce is shown. -/
theorem view_nonce_gate (e : Env B D) (w : World D) (s : Doc B D) (r : Role)
    (h : (view e w s r).nonce.isSome = true) : all2 s.confirmed = true := by
  simp only [view] at h
  split at h
  · assumption
  · simp at h

/-- On a reachable document still in `created` or `joined`, no member's view carries the nonce.
Uses the M9 rows for those states. -/
theorem view_nonce_hidden {e : Env B D} {c : ℕ} {s : Doc B D} (w : World D) (r : Role)
    (h : Reachable e c s) (hst : s.state = .created ∨ s.state = .joined) :
    (view e w s r).nonce = none := by
  have hi := M9 h
  have hc : all2 s.confirmed = false := by
    rcases hst with hs | hs
    · obtain ⟨_, hr, _⟩ := hi.row_created hs
      simp [all2, (hr .A).1, (hr .B).1]
    · exact (hi.row_joined hs).2.1
  simp [view, hc]

#print axioms arm_ok_rtt
#print axioms arm_ok_rtt_range
#print axioms arm_rate_matches
#print axioms arm_other_rate_error
#print axioms view_nonce_gate
#print axioms view_nonce_hidden

end Machine
end ServerFv
