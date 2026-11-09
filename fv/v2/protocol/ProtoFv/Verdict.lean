import ProtoFv.Basic

/-!
# The verdict math (`server/pop/verdict.py`), in integers

v2 keeps the v1 math (spec section 4). Only v2 transcripts exist, so the calibration is 0.
Copied from `verdict.py`, line numbers cite that file:

* `self_os_ok`, `:66-69`, with `cal_us = 0`: `|delta * 1000000| <= 50 * 1000 * sr`.
* `combine`, `:147-167`, same order of checks: roles, nonce and attempt, keys crossed and
  different, self check A then B, flight.
* `decide`, `:80-87`, on the exact flight. The flight is `34300/2 * N / S` with
  `N = hA*srB - hB*srA` and `S = srA*srB` (`:7`). Cross-multiplied as in the docstring, `:10-11`:
  impossible iff `34300*N <= -40*S`, too far iff `34300*N >= 120*S`. This holds when `S > 0`.
  A zero rate raises in Python (`Fraction`, `:165`). Here it is `mismatch`; in v2 a signed rate
  is always in 36000..96000.
* A `Reject` from `combine` is `mismatch`.
-/

namespace ProtoFv

inductive Res
  | near
  | tooFar
  | impossible
  | selfTs (by_ : Role)
  | mismatch
  deriving DecidableEq, Repr

/-- `constants.py:22-24, 27`. -/
def SPEED : Int := 34300
def TOL_MS : Nat := 50

/-- `self_os_ok`, `verdict.py:69`, `cal_us = 0`. -/
def selfOsOk (d : Int) (sr : Nat) : Bool := (d * 1000000).natAbs ≤ TOL_MS * 1000 * sr

/-- `decide (flight_exact ...)`, `verdict.py:72-73, 80-87`, cross-multiplied (`:10-11`). -/
def flight (hA : Int) (srA : Nat) (hB : Int) (srB : Nat) : Res :=
  let N := hA * srB - hB * srA
  let S : Int := srA * srB
  if SPEED * N ≤ -40 * S then .impossible
  else if SPEED * N ≥ 120 * S then .tooFar
  else .near

variable {D : Type} [DecidableEq D]

/-- `combine`, `verdict.py:147-167`. -/
def combine (ta tb : Tx D) : Res :=
  if ta.role ≠ .A ∨ tb.role ≠ .B then .mismatch                                   -- :155-156
  else if ta.sid ≠ tb.sid ∨ ta.attempt ≠ tb.attempt then .mismatch                -- :157-158
  else if ta.pkPeer ≠ tb.pkSelf ∨ tb.pkPeer ≠ ta.pkSelf ∨ ta.pkSelf = tb.pkSelf then
    .mismatch                                                                     -- :159-160
  else if !selfOsOk ta.selfOs ta.sr then .selfTs .A                               -- :161-164
  else if !selfOsOk tb.selfOs tb.sr then .selfTs .B
  else if ta.sr = 0 ∨ tb.sr = 0 then .mismatch                                    -- :165
  else flight ta.half ta.sr tb.half tb.sr                                         -- :165-167

end ProtoFv
