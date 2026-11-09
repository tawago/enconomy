import ServerFv.Machine

/-!
# X2, the abort row: one member ends a session alone, with no measurement

`spec.md` X2, first row of its table: `/abort` needs nobody else, in any live state, even right after
create. This file proves that row on the Lean copy of `sessions.py` at 9db1490 (`Machine.lean`).

**What is pinned.** A member's `/abort` request, on any reachable document whose state after `load`
is still live, stores a document that is `aborted`, has no result record and has `error = aborted`.
The response is a view, not an error. Right after `create`, the host alone gets the same, within the
join token's 120 s, and the guest slot is still empty: no second device took part.

**What is not pinned.** "No measurement" here means `result = none`: no result record is stored, so
no verdict or record `flight_cm`. A flight from an earlier retried attempt (`last_flight_cm`,
`attempts[].per_role`) may still be stored and is not covered; `Machine.lean` drops `last_flight_cm`.
Right after `create` nothing has been measured yet. Nothing is said about the request-level auth (R1 is not modeled),
about the other rows of X2 (`/fail`, a bad transcript; see `X2Fail.lean`), or about the air (CN1).
A session already done or aborted after `load` is not covered: `abort` leaves it as it is.
-/

set_option linter.style.longLine false
set_option linter.style.header false
set_option linter.unusedVariables false

namespace ServerFv
namespace Machine

variable {B D : Type} [DecidableEq B] [DecidableEq D]

/-- On a reachable document, if the state after `load` is live, `load` left no result. `load` either
keeps the document, ends it (state no longer live), or starts a retry from `started` (result kept,
and a started document has none). -/
theorem X2_load_result_none {e : Env B D} {c : ℕ} {s : Doc B D} {w : World D}
    (h : Reachable e c s) (hl : live (load e w s).state = true) : (load e w s).result = none := by
  have hi := (M9 h).toCore
  simp only [load, _expire] at hl ⊢
  by_cases h1 : s.state = .created ∧ w.now > s.token_expires_ms
  · rw [ite_eq_left_of_eq_true _ _ (eq_true h1)] at hl; simp [_save, live] at hl
  rw [ite_eq_right_of_eq_false _ _ (eq_false h1)] at hl ⊢
  by_cases h2 : live s.state = true ∧ w.now - s.created_ms > K.SESSION_MAX_AGE_S * 1000
  · rw [ite_eq_left_of_eq_true _ _ (eq_true h2)] at hl; simp [_save, live] at hl
  rw [ite_eq_right_of_eq_false _ _ (eq_false h2)] at hl ⊢
  by_cases h3 : s.state = .started ∧ w.now > s.t0_ms.getD 0 + K.TRANSCRIPT_DEADLINE_S * 1000
  · rw [ite_eq_left_of_eq_true _ _ (eq_true h3)] at hl ⊢
    have hs : s.result = none := hi.result_none' (by simp [h3.1, live])
    unfold _failed at hl ⊢
    by_cases hr : (isRetry (some Reason.timeout) && Nat.blt (s.attempt + 1) K.MAX_ATTEMPTS) = true
    · rw [ite_eq_left_of_eq_true _ _ (eq_true hr)]; simp [next_attempt, _save, hs]
    · rw [ite_eq_right_of_eq_false _ _ (eq_false hr)] at hl; simp [_finalize, _save, live] at hl
  · rw [ite_eq_right_of_eq_false _ _ (eq_false h3)] at hl ⊢
    exact hi.result_none' hl

/-- **X2, abort.** A member (`role_of` after `load` gives a role) sends `/abort` while the state after
`load` is live. The stored document is `aborted`, with no result record (so no verdict or record
`flight_cm`) and `error = aborted`, and the response is a view (200). A flight from an earlier retried
attempt (`last_flight_cm`, `attempts[].per_role`) may still be stored and is not covered. Nothing about
the partner is assumed. It says nothing about the air (CN1). -/
theorem X2_abort {e : Env B D} {c : ℕ} {s : Doc B D} {w : World D} {dev : D} {role : Role}
    (h : Reachable e c s) (hm : role_of (load e w s) dev = some role)
    (hl : live (load e w s).state = true) :
    let r := step e w (.api false (some dev) false (.op .abort)) s
    r.1.state = .aborted ∧ r.1.result = none ∧ r.1.error = some .aborted ∧ ∃ v, r.2 = .view v := by
  have hres := X2_load_result_none h hl
  have hnt : ¬((load e w s).state = .done ∨ (load e w s).state = .aborted) := by
    rintro (h' | h') <;> simp [h', live] at hl
  simp only [step, hm, handle, viewOr, abort, ite_eq_right_of_eq_false _ _ (eq_false hnt)]
  exact ⟨rfl, by simp [_save, hres], rfl, _, rfl⟩

/-- **X2, abort right after create.** The host creates a session at `w`, and sends `/abort` at `w'`,
no later than the join token's expiry (`w.now + 120000`). The stored document is `aborted`, with no
result, `error = aborted`, a view response, and still no guest. So abort needs nobody else. `w'` may
even read an earlier clock than `w`: nothing here needs A7. It says nothing about the air (CN1). -/
theorem X2_abort_after_create (e : Env B D) (w w' : World D) (host : D) (sid nonce : B) (seed tok : String)
    (hw : w'.now ≤ w.now + 120000) :
    let r := step e w' (.api false (some host) false (.op .abort)) (create w host sid nonce seed tok).1
    r.1.state = .aborted ∧ r.1.result = none ∧ r.1.error = some .aborted ∧ (∃ v, r.2 = .view v) ∧
      r.1.guest_device_id = none := by
  have hload : load e w' (create w host sid nonce seed tok).1 = (create w host sid nonce seed tok).1 := by
    unfold load _expire
    split_ifs with h1 h2 h3
    · simp [create, _save, K.JOIN_TOKEN_TTL_S] at h1; omega
    · simp [create, _save, K.SESSION_MAX_AGE_S] at h2; omega
    · simp [create, _save] at h3
    · rfl
  have hm : role_of (load e w' (create w host sid nonce seed tok).1) host = some .A := by
    rw [hload]; simp [role_of, create, _save]
  have hl : live (load e w' (create w host sid nonce seed tok).1).state = true := by
    rw [hload]; simp [create, _save, live]
  obtain ⟨h1, h2, h3, h4⟩ := X2_abort (Reachable.create (e := e) w host sid nonce seed tok) hm hl
  refine ⟨h1, h2, h3, h4, ?_⟩
  rw [M12_member_load e w' _ host .A .abort hm, hload]
  simp [handle, viewOr, abort, create, _save]

#print axioms X2_load_result_none
#print axioms X2_abort
#print axioms X2_abort_after_create

end Machine
end ServerFv
