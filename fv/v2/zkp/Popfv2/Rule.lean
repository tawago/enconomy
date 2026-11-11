import Mathlib

/-!
# Popfv2.Rule — the v2 detection rule, as a pure definition   (fv/v2/spec.md, section 5)

The v2 rule is fixes 1, 2 and 3 of `fv/v1/next-version-fixes.md` together:
1. the match `I`, `Q` is taken on the filtered signal `y`, the same `y` as the energy `E`;
2. a loudness floor `E · cn2 ≥ FLOOR`;
3. `cq` is in the template energy: `cn2 = Σ ci² + Σ cq²`.

No v2 circuit exists yet. This is the proposed rule, not code that runs. `BAR`, the taps `h`,
`FLOOR` and the bit widths are not fixed (roadmap stage 3), so they are parameters everywhere.

Signals are integer sequences `ℕ → ℤ` read on `range n`, not `List ℤ`. Same thing, and it is the
shape of v1's `yI` (`fv/v1/zkp/popfv/Popfv/PartnerGlue.lean`, `yI`, `EI`, `II`, `CI`).
All values are exact integers: no field, no overflow. Bit widths are a circuit question.

This file models one lag. `passAt`, `FirstPass` and `PartnerPass` lift it to a window of lags.
-/

set_option linter.style.whitespace false
set_option linter.style.longLine false
set_option linter.style.header false

namespace Popfv2

open Finset

/-- A template byte, centered. Copied from v1 `PartnerGlue.tfI` (`c - 128`). -/
def tf (c : ℕ) : ℤ := (c : ℤ) - 128

/-- The FIR filter with `T` taps `h`: `y[m] = Σ_t h[t] · w[m + t]`. Same form as v1 `PartnerGlue.yI`
(there 31 nonzero taps of 63, here any taps). -/
def filt (h : ℕ → ℤ) (T : ℕ) (w : ℕ → ℤ) (m : ℕ) : ℤ := ∑ t ∈ range T, h t * w (m + t)

/-- Correlation of a template `c` with a signal `y`. `I = corr ci y`, `Q = corr cq y`. -/
def corr (n : ℕ) (c y : ℕ → ℤ) : ℤ := ∑ m ∈ range n, c m * y m

/-- Energy `Σ y²`. Used for the loudness `E` and for each template. -/
def energy (n : ℕ) (y : ℕ → ℤ) : ℤ := ∑ m ∈ range n, y m ^ 2

/-- Template energy of the v2 rule, with `cq` (fix 3). -/
def cn2 (n : ℕ) (ci cq : ℕ → ℤ) : ℤ := energy n ci + energy n cq

/-- Match energy `M = I² + Q²`, both on the same signal `y`. -/
def M (n : ℕ) (ci cq y : ℕ → ℤ) : ℤ := corr n ci y ^ 2 + corr n cq y ^ 2

/-- The floor part (fix 2): `E · cn2 ≥ FLOOR`. Not scale-free, on purpose. -/
def Floor (FLOOR : ℤ) (n : ℕ) (ci cq y : ℕ → ℤ) : Prop := FLOOR ≤ energy n y * cn2 n ci cq

/-- The ratio part: `BAR · M ≥ E · cn2`, with `M` and `E` over the same `y` (fix 1). -/
def Ratio (BAR : ℤ) (n : ℕ) (ci cq y : ℕ → ℤ) : Prop := energy n y * cn2 n ci cq ≤ BAR * M n ci cq y

/-- The v2 rule at one lag, on the filtered signal `y`. `BAR` and `FLOOR` are not checked here: the spec's
`FLOOR ≥ 1` is a hypothesis on each theorem that needs it (`PassY 1 0` accepts silence). -/
def PassY (BAR FLOOR : ℤ) (n : ℕ) (ci cq y : ℕ → ℤ) : Prop :=
  Floor FLOOR n ci cq y ∧ Ratio BAR n ci cq y

/-- The v2 rule at one lag, on the centered recording `w` (`x - 32768`), read from the window start.
The filter reads `T - 1` samples past the window. -/
def Pass (h : ℕ → ℤ) (T n : ℕ) (BAR FLOOR : ℤ) (ci cq w : ℕ → ℤ) : Prop :=
  PassY BAR FLOOR n ci cq (filt h T w)

/-- The v2 rule at lag `j` of a recording `w`. -/
def passAt (h : ℕ → ℤ) (T n : ℕ) (BAR FLOOR : ℤ) (ci cq w : ℕ → ℤ) (j : ℕ) : Prop :=
  Pass h T n BAR FLOOR ci cq (fun i => w (j + i))

/-- Self side: `a` is the first of `K` lags where the v2 rule passes. A lag that fails either part is
"not yet". -/
def FirstPass (h : ℕ → ℤ) (T n : ℕ) (BAR FLOOR : ℤ) (ci cq w : ℕ → ℤ) (K a : ℕ) : Prop :=
  a < K ∧ passAt h T n BAR FLOOR ci cq w a ∧ ∀ j < a, ¬ passAt h T n BAR FLOOR ci cq w j

/-- Partner side: the lag `a` the transcript names is one of the `K` lags of the partner window,
and the v2 rule passes there ("any passing lag", as in v1). -/
def PartnerPass (h : ℕ → ℤ) (T n : ℕ) (BAR FLOOR : ℤ) (ci cq w : ℕ → ℤ) (K a : ℕ) : Prop :=
  a < K ∧ passAt h T n BAR FLOOR ci cq w a

/-! ## Mutants: the v2 rule with one fix taken out, plus the full v1 rule as a baseline. Used only to show each fix matters. -/

/-- Fix 3 taken out: template energy from `ci` only (v1's `cna`, `cnp`). -/
def cn2CiOnly (n : ℕ) (ci : ℕ → ℤ) : ℤ := energy n ci

/-- Fix 1 taken out: the match is on a raw signal `x` (v1: the window at the center tap), the
energy on the filtered `y`. -/
def RatioRaw (BAR : ℤ) (n : ℕ) (ci cq y x : ℕ → ℤ) : Prop :=
  energy n y * cn2 n ci cq ≤ BAR * M n ci cq x

/-- Fix 1 taken out, fixes 2 and 3 kept. -/
def PassRaw (BAR FLOOR : ℤ) (n : ℕ) (ci cq y x : ℕ → ℤ) : Prop :=
  Floor FLOOR n ci cq y ∧ RatioRaw BAR n ci cq y x

/-- The v1 rule, all three fixes out: raw match, ci-only template energy, no floor.
The integer test `B·m ≥ L` of v1 `Bar.lean` (section 1) with `m` from v1 `PartnerGlue.II`
(raw window) and `L = EI · CI` (filtered energy, ci only). -/
def PassV1 (BAR : ℤ) (n : ℕ) (ci cq y x : ℕ → ℤ) : Prop :=
  energy n y * cn2CiOnly n ci ≤ BAR * M n ci cq x

end Popfv2
