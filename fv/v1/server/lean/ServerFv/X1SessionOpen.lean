import ServerFv.X1SessionDefs

/-!
# X1 as a session result, opening steps (Known gap 4, chunk S1)

The first three requests of `X1Plan.reqs`: the guest joins at `T+1`, the host confirms at `T+2`, the
guest confirms at `T+3`. Each lemma says that `step` stores exactly the hand-written document of
`X1SessionDefs.lean`: `d0 → d1 → d2 → d3`.

**What this file pins.** For any `X1Plan`, the stored document after each of the three steps equals
`d1`, `d2`, `d3` field for field. On the way it shows `load` changes nothing at these clocks: no token
expiry (E1, the clock is far below `T + 120000`), no age expiry (E2, age is at most 3 ms), no
transcript deadline (E3, the state is not `started`).

**What it does not pin.** Nothing about the responses (they are views; only the stored document is
compared). Nothing about other timings, other devices, or later steps (arms, commits, transcripts are
other chunks). Nothing about sound.
-/

namespace ServerFv
namespace Machine
namespace X1Plan

variable {B D : Type} [DecidableEq B] [DecidableEq D]
variable {e : Env B D} {nonce sid : B} (P : X1Plan e nonce sid)

omit [DecidableEq B] [DecidableEq D] in
/-- `load` leaves an open document alone in the first two minutes: if the document was created at
`T`, its token runs to `T + 120000`, it is not `started`, and the clock is `T + n` with
`n ≤ 120000`, then none of E1, E2, E3 fires. It pins only these field values; any other field can be
anything. -/
theorem load_open (s : Doc B D) (n : ℕ) (hc : s.created_ms = P.T)
    (ht : s.token_expires_ms = P.T + 120000) (hs : s.state ≠ .started) (hn : n ≤ 120000) :
    load e (P.W n) s = s := by
  unfold load _expire
  have h1 : ¬ (s.state = .created ∧ (P.W n).now > s.token_expires_ms) := by
    rintro ⟨-, h⟩; simp [W, ht] at h; omega
  have h2 : ¬ (live s.state = true ∧ (P.W n).now - s.created_ms > K.SESSION_MAX_AGE_S * 1000) := by
    rintro ⟨-, h⟩; simp [W, hc, K.SESSION_MAX_AGE_S] at h; omega
  have h3 : ¬ (s.state = .started ∧
      (P.W n).now > s.t0_ms.getD 0 + K.TRANSCRIPT_DEADLINE_S * 1000) := by
    rintro ⟨h, -⟩; exact hs h
  rw [ite_eq_right h1, ite_eq_right h2, ite_eq_right h3]

omit [DecidableEq B] [DecidableEq D] in
/-- `d0` was created at `T`. -/
theorem d0_created : P.d0.created_ms = P.T := rfl
omit [DecidableEq B] [DecidableEq D] in
/-- `d0`'s token runs to `T + 120000`. -/
theorem d0_token : P.d0.token_expires_ms = P.T + 120000 := rfl

/-- **The join step.** The guest `dB` joins with the plan's token at `T+1`; the stored document is
`d1` (guest set, state `joined`, `seq` 2). Uses that the devices differ (`hdev`) and the token is
lower case (`htok`). -/
theorem step_join :
    (step e (P.W 1) (.api false (some P.dB) false (.join P.token)) P.d0).1 = P.d1 := by
  have hl : load e (P.W 1) P.d0 = P.d0 :=
    P.load_open _ 1 rfl rfl (by simp [d0, create, _save]) (by norm_num)
  have hj : join (P.W 1) P.d0 P.dB P.token = .ok P.d1 := by
    have hh : P.d0.host_device_id = P.dA := rfl
    have hg : P.d0.guest_device_id = none := rfl
    have hk : P.d0.join_token = P.token := rfl
    have hst : P.d0.state = .created := rfl
    have hnow : ¬ (P.W 1).now > P.d0.token_expires_ms := by
      simp [W, P.d0_token]
    unfold join
    rw [ite_eq_right (by rw [hh]; exact P.hdev.symm), ite_eq_right (by simp [hg]),
      ite_eq_right (by simp [hk, P.htok]), ite_eq_right (by simp [hst, hnow])]
    rfl
  simp only [step, Bool.false_eq_true, ↓reduceIte, hl, hj, viewOr]

/-- **The host confirms.** At `T+2` the host `dA` confirms on `d1`; the stored document is `d2`
(host's confirm flag set, still `joined`, `seq` 3). -/
theorem step_confA :
    (step e (P.W 2) (.api false (some P.dA) false (.op .confirm)) P.d1).1 = P.d2 := by
  have hl : load e (P.W 2) P.d1 = P.d1 :=
    P.load_open _ 2 rfl rfl (by simp [d1]) (by norm_num)
  have hr : role_of P.d1 P.dA = some .A := by
    simp [role_of, d1, d0, create, _save]
  have hc : confirm P.d1 .A = .ok P.d2 := by
    have hst : P.d1.state = .joined := rfl
    have hcf : P.d1.confirmed = _flags := rfl
    unfold confirm
    rw [ite_eq_right (by simp [hst, hcf, _flags]), ite_eq_right (by simp [hst])]
    simp only [hcf]
    rw [ite_eq_right (by simp [all2, upd, _flags])]
    rfl
  simp only [step, Bool.false_eq_true, ↓reduceIte, hl, hr, handle, hc, viewOr]

/-- **The guest confirms.** At `T+3` the guest `dB` confirms on `d2`; both flags are set, the
stored document is `d3` (state `confirmed`, `seq` 4). Uses that the devices differ (`hdev`) to find
the guest's role. -/
theorem step_confB :
    (step e (P.W 3) (.api false (some P.dB) false (.op .confirm)) P.d2).1 = P.d3 := by
  have hl : load e (P.W 3) P.d2 = P.d2 :=
    P.load_open _ 3 rfl rfl (by simp [d2, d1]) (by norm_num)
  have hr : role_of P.d2 P.dB = some .B := by
    have hh : P.d2.host_device_id = P.dA := rfl
    have hg : P.d2.guest_device_id = some P.dB := rfl
    unfold role_of
    rw [ite_eq_right (by rw [hh]; exact P.hdev.symm), ite_eq_left (by rw [hg])]
  have hc : confirm P.d2 .B = .ok P.d3 := by
    have hst : P.d2.state = .joined := rfl
    have hcf : P.d2.confirmed = upd _flags .A true := rfl
    unfold confirm
    rw [ite_eq_right (by simp [hst, hcf, upd, _flags]), ite_eq_right (by simp [hst])]
    simp only [hcf]
    rw [ite_eq_left (by simp [all2, upd])]
    rfl
  simp only [step, Bool.false_eq_true, ↓reduceIte, hl, hr, handle, hc, viewOr]

/-- The first three requests of the plan run `d0` to `d3`. Pins only the stored document. -/
theorem run_open :
    runL e P.d0 [(P.W 1, P.reqJoin), (P.W 2, P.reqConfA), (P.W 3, P.reqConfB)] = P.d3 := by
  simp only [runL_cons, runL_nil, reqJoin, reqConfA, reqConfB, opReq]
  rw [P.step_join, P.step_confA, P.step_confB]

end X1Plan
end Machine
end ServerFv

#print axioms ServerFv.Machine.X1Plan.load_open
#print axioms ServerFv.Machine.X1Plan.step_join
#print axioms ServerFv.Machine.X1Plan.step_confA
#print axioms ServerFv.Machine.X1Plan.step_confB
#print axioms ServerFv.Machine.X1Plan.run_open
