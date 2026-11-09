import ServerFv.M14Handlers
import ServerFv.M14Transcript

/-!
# M14: a failed request leaves no trace (README gap 5)

`spec.md` M14, for `step` as a whole. "Unchanged" here means one of two documents: the stored one
`s`, when the request stops before the load (bad JSON, no auth, bad shape), or `load e w s`, the
stored one after `_expire`, when the request gets as far as the load. The load's own change is what
the clock already dictates (M12); this file does not repeat that.

The one exception is on purpose: the transcript route ends a session as NOT_NEAR on a bad transcript
or a pair `combine` rejects, and then answers 400 with the reason. Then the document is a
`_finalize` to NOT_NEAR, outcome `rejected`, no flight, of one of exactly two documents
(`TxReject`): the loaded one blaming the sender (bad transcript), or the loaded one with this
request's transcript stored blaming no role (combine reject).

**What this does not say.** Which reason `combine` gives. Nothing about success answers. Nothing about the `noauth_load`
route's own work (it answers `.other`, never an error, so it is out of M14's reach). It is about the
Lean model; that a raise in `main.py` throws away unsaved edits is A8.
-/

set_option linter.style.whitespace false
set_option linter.style.longLine false
set_option linter.style.header false
set_option linter.unusedVariables false
set_option linter.unusedSimpArgs false
set_option linter.unusedSectionVars false

namespace ServerFv.Machine

variable {B D : Type} [DecidableEq B] [DecidableEq D]

/-- **M14, an authed request that passed the shape check.** If it answers an error, the stored
document is `load e w s` (the load's change only, no handler write, no `seq` bump), unless it is a
transcript from a member `role`, the answer is 400 with a reject reason `rsn`, and the document is
`TxReject` on `load e w s`: that document finalized blaming `role`, or that document with this
transcript stored finalized blaming no role. Covers join, non-member, and every member handler. -/
theorem M14 {e : Env B D} {w : World D} {s : Doc B D} {dev : D} {b : Body B} {st : ℕ} {c : Err}
    (h : (step e w (.api false (some dev) false b) s).2 = .error st c) :
    (step e w (.api false (some dev) false b) s).1 = load e w s ∨
      ∃ tb sb rsn role, b = .op (.transcript tb sb) ∧ role_of (load e w s) dev = some role ∧
        st = 400 ∧ c = .reason rsn ∧
        TxReject e w (load e w s) role dev tb sb rsn (step e w (.api false (some dev) false b) s).1 := by
  cases b with
  | join tok =>
    simp only [step, Bool.false_eq_true, ↓reduceIte] at h ⊢
    exact Or.inl (viewOr_err_doc h)
  | op o =>
    simp only [step, Bool.false_eq_true, ↓reduceIte] at h ⊢
    revert h
    split
    · intro _; exact Or.inl rfl
    · rename_i role hrole
      cases o with
      | view => intro h; simp [handle] at h
      | result => intro h; exact Or.inl (result_err_doc h)
      | confirm => intro h; exact Or.inl (viewOr_err_doc h)
      | abort => intro h; exact Or.inl (viewOr_err_doc h)
      | arm a sr rtt p => intro h; exact Or.inl (arm_err_doc (e := e) h)
      | commit cb sb => intro h; exact Or.inl (commit_err_doc h)
      | fail_ a rsn => intro h; exact Or.inl (viewOr_err_doc h)
      | transcript tb sb =>
        intro h
        rcases transcript_err_doc h with h1 | ⟨rsn, hst, hc, h1⟩
        · exact Or.inl h1
        · exact Or.inr ⟨tb, sb, rsn, role, rfl, hrole, hst, hc, h1⟩

/-- **M14, any request.** If `step` answers an error, the stored document is the old one `s` (bad
JSON, no auth, bad shape: stopped before the load), or `load e w s`, or the transcript exception:
an authed transcript request from member `role`, answer 400 with reason `rsn`, document one of the
two `TxReject` finalizes of `load e w s`. -/
theorem M14_any {e : Env B D} {w : World D} {s : Doc B D} (req : Req B D) {st : ℕ} {c : Err}
    (h : (step e w req s).2 = .error st c) :
    (step e w req s).1 = s ∨ (step e w req s).1 = load e w s ∨
      ∃ dev tb sb rsn role, req = .api false (some dev) false (.op (.transcript tb sb)) ∧
        role_of (load e w s) dev = some role ∧ st = 400 ∧ c = .reason rsn ∧
        TxReject e w (load e w s) role dev tb sb rsn (step e w req s).1 := by
  cases req with
  | noauth_load => simp [step] at h
  | api j x sh b =>
    cases j with
    | true => exact Or.inl (M12_bad_json e w s x sh b)
    | false =>
      cases x with
      | none => exact Or.inl (M12_no_auth e w s false sh b)
      | some dev =>
        cases sh with
        | true => exact Or.inl (M12_bad_shape e w s false (some dev) b)
        | false =>
          rcases M14 h with h1 | ⟨tb, sb, rsn, role, hb, hrole, hst, hc, h1⟩
          · exact Or.inr (Or.inl h1)
          · subst hb
            exact Or.inr (Or.inr ⟨dev, tb, sb, rsn, role, rfl, hrole, hst, hc, h1⟩)

end ServerFv.Machine

#print axioms ServerFv.Machine.M14
#print axioms ServerFv.Machine.M14_any
