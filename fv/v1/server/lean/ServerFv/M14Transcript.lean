import ServerFv.Machine

/-!
# M14 for the transcript route (`spec.md` M14, gap 5)

`spec.md` M14: a failed request leaves no trace. The transcript route is the one place where an
error answer comes with a changed document on purpose: a transcript that fails its check, or a
pair that `combine` rejects, ends the session as NOT_NEAR and answers 400 with the reason.

This file pins that, for `afterStore` and `transcript` of `Machine.lean`: when either answers an
error, the document it hands back is either the one it was given (unchanged, not even a `seq` bump),
or a `_finalize` to NOT_NEAR with outcome `rejected` of exactly that document (blaming the sender)
or of that document with this transcript stored (blaming no role), and then the answer is exactly
400 with that same reason.

**What this does not say.** It is about the handler, run on the document after the load. It says
nothing about the load itself (`_expire` may save before the handler runs); that wrap is the job of
the general M14 theorem. It pins which document `_finalize` is applied to (`TxReject`): the loaded
one, or the loaded one with this request's transcript stored. It says nothing about which reason
`combine` gives, nor about success answers.
-/

namespace ServerFv.Machine

variable {B D : Type} [DecidableEq B]

/-- `afterStore` answers an error only in two ways. Either the document is `s0`, the one from the
load (the uncaught 500s, lines 451 and the zero-division path), or the answer is 400 with a reject
reason `rsn` and the document is `s` (the one with the transcript stored) finalized as NOT_NEAR,
`rejected`, with no flight and no blamed role (lines 454-456). The accepted paths never answer an
error. -/
theorem afterStore_err_doc {e : Env B D} {w : World D} {s0 s : Doc B D} {st : ℕ} {c : Err}
    (h : (afterStore e w s0 s).2 = .error st c) :
    (afterStore e w s0 s).1 = s0 ∨
      ∃ rsn, st = 400 ∧ c = .reason rsn ∧
        (afterStore e w s0 s).1 = _finalize e w s .NOT_NEAR (some rsn) none .rejected none := by
  revert h
  unfold afterStore
  split
  · intro h; exact absurd h (by simp)
  · split
    · split
      · intro h
        obtain ⟨h1, h2⟩ := Resp.error.inj h
        exact Or.inr ⟨_, h1.symm, h2.symm, rfl⟩
      · intro _; exact Or.inl rfl
      · intro h; exact absurd h (by simp)
    · intro _; exact Or.inl rfl

/-- The two documents a rejected transcript may leave, exactly as in `transcript` (lines 438-440 and
454-456). Bad transcript: the check rejects with `rsn`, and the loaded document `s` itself is
finalized, blaming the sender `role`. Combine reject: the check passed with `(raw, t)`, and `s` with
this request's transcript stored (`txStore`, the same `td` as lines 444-446) is finalized, blaming no
role. Nothing else: not `s` with another nonce, other participants, or a `seq` bump. -/
def TxReject (e : Env B D) (w : World D) (s : Doc B D) (role : Role) (dev : D) (tb sb : B)
    (rsn : Reason) (d : Doc B D) : Prop :=
  (∃ pk', _pk e s (OTHER role) = some pk' ∧ checkNew e s role dev tb sb pk' = .error (.reject rsn) ∧
      d = _finalize e w s .NOT_NEAR (some rsn) none .rejected (some role)) ∨
  (∃ pk' raw t, _pk e s (OTHER role) = some pk' ∧ checkNew e s role dev tb sb pk' = .ok (raw, t) ∧
      d = _finalize e w
        (txStore s role
          { transcript_b64 := tb, sig_b64 := sb, transcript_sha256 := e.p.sha256 raw,
            half := t.half, self_os_delta := t.self_os_delta })
        .NOT_NEAR (some rsn) none .rejected none)

/-- `transcript` answers an error only in two ways. Either the document is `s`, exactly the one it
was given (stale attempt, bad state, already submitted, not committed, the 500s), or the answer is
400 with a reject reason `rsn` and the document is one of the two in `TxReject`: `s` finalized
blaming the sender (bad transcript), or `s` after this request's `txStore` finalized blaming no role
(combine reject). -/
theorem transcript_err_doc {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {dev : D}
    {tb sb : B} {st : ℕ} {c : Err} (h : (transcript e w s role dev tb sb).2 = .error st c) :
    (transcript e w s role dev tb sb).1 = s ∨
      ∃ rsn, st = 400 ∧ c = .reason rsn ∧
        TxReject e w s role dev tb sb rsn (transcript e w s role dev tb sb).1 := by
  revert h
  unfold transcript
  split
  · intro _; exact Or.inl rfl
  split
  · intro _; exact Or.inl rfl
  split
  · split
    · split <;> intro _ <;> exact Or.inl rfl
    · intro _; exact Or.inl rfl
  split
  · intro _; exact Or.inl rfl
  cases hpk : _pk e s (OTHER role) with
  | none => intro _; exact Or.inl rfl
  | some pk' =>
    dsimp only
    cases hck : checkNew e s role dev tb sb pk' with
    | error r =>
      cases r with
      | reject rsn =>
        intro h
        obtain ⟨h1, h2⟩ := Resp.error.inj h
        exact Or.inr ⟨rsn, h1.symm, h2.symm, Or.inl ⟨pk', hpk, hck, rfl⟩⟩
      | zero_division => intro _; exact Or.inl rfl
    | ok p =>
      obtain ⟨raw, t⟩ := p
      intro h
      rcases afterStore_err_doc h with h5 | ⟨rsn, hst, hc', h5⟩
      · exact Or.inl h5
      · exact Or.inr ⟨rsn, hst, hc', Or.inr ⟨pk', raw, t, hpk, hck, h5⟩⟩

#print axioms afterStore_err_doc
#print axioms transcript_err_doc

end ServerFv.Machine
