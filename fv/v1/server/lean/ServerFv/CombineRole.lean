import ServerFv.Verdict

/-!
# Gap 15: the role guard at the top of `combine`

`combine` (`verdict.py:155-156`) first checks that the first transcript says role A and the second
says role B, and refuses with `transcript_mismatch` otherwise. The replay never hits this branch:
through `Machine.step` the server always passes its stored A half first and its stored B half second,
and `combine_guard_unreachable` (Machine.lean) shows the guard can't fire on that path. So no trace
checks this line against Python.

This file pins what the guard does in the Lean model of `combine`, nothing more. It says nothing
about the Python itself beyond what the model already transcribes, and it adds no new trace coverage.
-/

namespace ServerFv

variable {B : Type} [DecidableEq B]

/-- **Gap 15, the guard fires.** If the first transcript is not role A, or the second is not role B,
`combine` refuses with `transcript_mismatch`, whatever the nonces, keys, calibration or rates are.
It pins the model's line 155-156 only. The guard is unreachable through `Machine.step`
(`combine_guard_unreachable`), so this is the model's behavior, not something the replay checked
against Python. -/
theorem combine_role_guard (ta tb : Transcript B) (cal : Option (Role → Option ℤ))
    (h : ta.role ≠ .A ∨ tb.role ≠ .B) :
    combine ta tb cal = .error (.reject .transcript_mismatch) := by
  unfold combine
  simp [h]

/-- **Gap 15, the converse side.** Any `.ok` out of `combine` came from an A transcript first and a
B transcript second. It says nothing about which `.ok` (verdict or self check reason) comes out, and
nothing about `.error` results, which can also come from the later checks. -/
theorem combine_ok_roles {ta tb : Transcript B} {cal : Option (Role → Option ℤ)} {out : CombineOut}
    (h : combine ta tb cal = .ok out) : ta.role = .A ∧ tb.role = .B := by
  by_contra hn
  have hg : ta.role ≠ .A ∨ tb.role ≠ .B := by
    by_cases ha : ta.role = .A
    · exact .inr (fun hb => hn ⟨ha, hb⟩)
    · exact .inl ha
  rw [combine_role_guard ta tb cal hg] at h
  cases h

end ServerFv

#print axioms ServerFv.combine_role_guard
#print axioms ServerFv.combine_ok_roles
