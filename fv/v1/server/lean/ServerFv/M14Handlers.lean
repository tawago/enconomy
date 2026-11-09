import ServerFv.Machine

/-!
# M14 for the small handlers (README gap 5)

M14 says a failed request leaves no trace. This file proves it for four pieces of `Machine.lean`:
`viewOr`, `result`, `arm` and `commit`. Each theorem says: if the handler answers `.error st c`, the document
it returns is exactly the one it was given.

What this pins: no error branch of these four writes anything, not even `_save`'s `seq` bump.
What it doesn't: the transcript route (`M14Transcript`), the load before a handler, and `step` as a whole
(`M14`). It is about the Lean model only; that a raise in `main.py` throws away unsaved edits is A8.
-/

set_option linter.style.whitespace false
set_option linter.style.longLine false
set_option linter.style.header false
set_option linter.unusedVariables false
set_option linter.unusedSimpArgs false
set_option linter.unusedSectionVars false

namespace ServerFv.Machine

variable {B D : Type} [DecidableEq B] [DecidableEq D]

/-- `viewOr` on an error gives back the document it was handed. The `.ok` branch answers a view, never an
error, so the hypothesis rules it out. Says nothing about which document `.ok` returns. -/
theorem viewOr_err_doc {e : Env B D} {w : World D} {s : Doc B D} {role : Role}
    {x : Except (ℕ × Err) (Doc B D)} {st : ℕ} {c : Err}
    (h : (viewOr e w s role x).2 = .error st c) : (viewOr e w s role x).1 = s := by
  revert h
  unfold viewOr
  split
  · intro h; cases h
  · intro _; rfl

/-- `result` never changes the document, error or not. Stated with the error hypothesis to match the others. -/
theorem result_err_doc {s : Doc B D} {st : ℕ} {c : Err}
    (h : (result s).2 = .error st c) : (result s).1 = s := by
  unfold result
  split <;> rfl

/-- `arm` on any error gives back the document it was handed: none of the error branches (lines 232-250)
stores the arm or bumps `seq`. The two success branches answer `armMaterial`, which the hypothesis rules out. -/
theorem arm_err_doc {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {a sr : Arg}
    {rtt : Option ℚ} {p : Arg} {st : ℕ} {c : Err}
    (h : (arm e w s role a sr rtt p).2 = .error st c) : (arm e w s role a sr rtt p).1 = s := by
  revert h
  unfold arm
  repeat' split
  all_goals first
    | (intro _; rfl)
    | (intro h; simp [_arm_material] at h)

/-- `commit` on any error gives back the document it was handed: bad state, bad base64, bad decode, bad
signature, wrong role/attempt/nonce/version, a different second commit, and too early all return `s`.
The replayed commit and the stored commit answer `partnerBed`, which the hypothesis rules out. -/
theorem commit_err_doc {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {dev : D} {cb sb : B}
    {st : ℕ} {c : Err}
    (h : (commit e w s role dev cb sb).2 = .error st c) : (commit e w s role dev cb sb).1 = s := by
  rcases commit_shape e w s role dev cb sb with ⟨st', c', h'⟩ | ⟨_, _, h'⟩ | ⟨_, cd, _, h'⟩
  · rw [h']
  · rw [h']
  · rw [h'] at h; simp [_partner_bed] at h

end ServerFv.Machine

#print axioms ServerFv.Machine.viewOr_err_doc
#print axioms ServerFv.Machine.result_err_doc
#print axioms ServerFv.Machine.arm_err_doc
#print axioms ServerFv.Machine.commit_err_doc
