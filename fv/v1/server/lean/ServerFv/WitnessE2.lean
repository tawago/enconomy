import ServerFv.Machine

/-!
# E2 beats E3 with one transcript in (README "Known gaps" item 14)

`_expire` checks the session age (E2, `sessions.py` max age) before the transcript deadline (E3).
When both have passed, E2 wins: the session is `aborted` with `timeout`, no result. This file runs
one toy session (the `Witness` setting of `Machine.lean`) where both have passed and A has already
sent its transcript, and shows E2's outcome.

Timing: created at 0, both arm at 590000/590001, so t0 = 593001 and the commit gate is at 594201.
A commits at 594300 and sends its transcript at 594301 (`started`, A submitted, B not). At 620000
the age (620 s > 600 s) and the deadline (t0 + 20 s = 613001) have both passed.

**What this pins.** Only this run, with these numbers. If `_expire` checked E3 first, the view at
620000 would see `_failed` with `timeout` instead, and the last theorem would break.

**What this does not say.** Nothing about other runs or other orders of requests, and nothing
about the air (CN1).
-/

set_option linter.style.whitespace false
set_option linter.style.longLine false
set_option linter.style.header false

namespace ServerFv.Machine.Witness

/-- The requests up to A's transcript: opening, both arm at 590000, A commits after the gate and
sends its transcript. -/
def e2Pre : List (ℕ × Req ℕ ℕ) :=
  opening ++
    [(590000, R 1 (.arm (.int 0) (.int 48000) (some 10) .null)),
     (590001, R 2 (.arm (.int 0) (.int 48000) (some 10) .null)),
     (594300, R 1 (.commit 10 110)),
     (594301, R 1 (.transcript 11 111))]

/-- `e2Pre`, then a view by A at 620000, after both E2 and E3 have passed. -/
def e2Full : List (ℕ × Req ℕ ℕ) := e2Pre ++ [(620000, R 1 .view)]

/-- The run's last clock is 620000. -/
theorem e2_clock : lastTime 0 e2Full = 620000 := by decide

/-- **One transcript is in.** After `e2Pre` the session is `started`, A has submitted, B has not.
So the run below really has a transcript on file when E2 and E3 both fire. -/
theorem e2_one_tx_in : (run (env Hnear) start e2Pre).state = .started ∧
    (run (env Hnear) start e2Pre).submitted .A = true ∧
    (run (env Hnear) start e2Pre).submitted .B = false := by
  refine ⟨?_, ?_, ?_⟩ <;> decide +kernel

/-- **E2 beats E3 with one transcript in.** The run is reachable, and at 620000 the session is
`aborted` with error `timeout` and no result (E2), not finished as NOT_NEAR by the transcript
deadline (E3). Only this run; nothing about the air (CN1). -/
theorem E2_beats_E3_one_tx : Reachable (env Hnear) (lastTime 0 e2Full) (run (env Hnear) start e2Full) ∧
    (run (env Hnear) start e2Full).state = .aborted ∧
    (run (env Hnear) start e2Full).error = some .timeout ∧
    (run (env Hnear) start e2Full).result = none := by
  refine ⟨run_reachable (Reachable.create (W 0) 1 5 9 "seed" "t") _ (by decide), ?_, ?_, ?_⟩ <;> decide +kernel

end ServerFv.Machine.Witness

#print axioms ServerFv.Machine.Witness.e2_clock
#print axioms ServerFv.Machine.Witness.e2_one_tx_in
#print axioms ServerFv.Machine.Witness.E2_beats_E3_one_tx
