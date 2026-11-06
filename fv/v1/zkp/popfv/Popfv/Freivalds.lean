import Popfv.Arrival

/-!
# Block C: the Freivalds spot check inside `self_side`

Source: `research/worldid/prototypes/optA-noir/noir/oalib/src/lib.nr`, `self_side` lines 338-434 (deployed
variant) and `fs_challenges` lines 302-332. Line numbers below refer to that file.

The arrival proof (`Arrival.self_side_arrival_sound`) assumes that the claimed curve `ci`, `cq` is the true
correlation. The circuit never computes the 193 correlations directly, since that would cost 193 x 12000
multiplications. It checks one random linear combination of them instead. This file says what that check gives.

What is proved, with no probability and no hash assumption:
* `run` is a literal model of the loop, and `run_identity` gives the two closed forms at the end of it:
  `lhs = Σ_j r^j (ci_j + ρ cq_j)` and `acc = Σ_j r^j (I_j + ρ Q_j)`, `I, Q` being `Arrival.corr`.
* `honest_passes`: true values always pass, for every `r ≠ 0` and every `ρ`.
* `fooled_count`: if the claim is wrong, at most `193 p` of the `p²` pairs `(r, ρ)` pass. That is odds of `193/p`,
  below `2^-246` (`fooled_odds`, `odds_numeric`). All the Freivalds content is in this count.
* `arrival_bad_pairs_count`, `arrival_bad_pairs_count_any_flags`, `arrival_bad_odds`: the count joined to the arrival
  theorem. For a fixed window, templates and curve, at most `193 p` pairs pass the spot check while the arrival
  conclusion is false. This is the statement that replaces the Block C hypothesis.
* `claim_true_of_not_fooled`, `self_side_sound_unless_fooled` are bookkeeping only. `Fooled` is defined as "wrong and
  passes", so given a pass, "not fooled" MEANS the curve is right. Both hold by definition, and neither says anything
  about how likely that is.
* `wrong_curve_moves_arrival`: the bad pairs are real. A concrete wrong curve passes at `r = 1` and moves the arrival.

`[Fact (Nat.Prime p)]` is a hypothesis of `honest_passes` (for the inverse of `r`), and of `fooled_count`, `fooled_odds`,
`arrival_bad_pairs_count`, `arrival_bad_pairs_count_any_flags`, `arrival_bad_odds`, `rom_union_bound` (for root counting).
It is never proved in this repo. The loop model, `run_identity`, `check_iff`, `freivalds_complete` and
`wrong_curve_moves_arrival` don't use it.

What is NOT proved, in plain words. `r` and `ρ` come out of a hash (`fs_challenges`, Poseidon2 sponge). The count
above is over all pairs. To turn it into "the odds of cheating are tiny" you have to treat the hash output as a fresh
uniform pair, independent of everything that went in. That is the random-oracle assumption. Lean knows nothing about
Poseidon2 here: `fs_challenges` takes the hash `H` as an arbitrary function. `rom_union_bound` is a LABELLED statement
about an idealized `H`, not about Poseidon2. It covers a fixed list of tries, not an attacker who picks each try after
seeing the last answer. The textbook bound for that case is the same, but it is not machine-checked here.

Modeling choices.
* `x i` stands for `xs[o + i]`, as in `Arrival.lean`. `window_in_array` shows the read stays inside the array, and
  `window_offset_unique` shows `o` is pinned by `p_self`. That the array is the signed recording is Block B.
* `w(e)` (line 14) is the identity.
* `let rinv = 1 / r` (line 371) is modeled as a witness with the constraint `r * rinv = 1`, which is how Noir compiles
  a field division. So the model needs no primality for the identity. `r_zero_rejected` is the consequence.
* The FIR and arrival lines inside the same loop (386-406) write none of `s, pr, pinv, acc, lhs, sring`, so they are
  left out of `stepAt`. `Arrival.lean` models them. Both read the same `ringSt`.
* Only `T = u8` templates are modeled, as in `Arrival.lean`. That is the `phone` circuit, the deployed one
  (`fv/v1/docs/02-scope.md`). `phone_pub/src/main.nr` calls `phone_core` with `Field` templates and `[code_hi, code_lo]`,
  and neither the model nor the audit below covers it.
-/

set_option linter.style.whitespace false
set_option linter.style.longLine false
set_option linter.style.header false

namespace Popfv
namespace Freivalds

open Finset Arrival

-- Keep Lean from computing with the 254-bit literal when it compares instances on `ZMod p`.
attribute [local irreducible] Popfv.p

/-! ## The loop, literally (lib.nr 371-433) -/

/-- The prover's inputs that the loop reads. `x i` is `xs[o + i]` (u16), `c_i`, `c_q` are the u8 self templates,
`ci`, `cq` are the claimed curve (free field values, lines 341-342). -/
structure Wit where
  x : ℕ → ℕ
  c_i : ℕ → ℕ
  c_q : ℕ → ℕ
  ci : ℕ → F
  cq : ℕ → F

/-- The mutable variables of lines 372-380 that the spot check uses. `ring_` is `ring` (a Mathlib tactic name). -/
structure St where
  ring_ : ℕ → F
  sring : ℕ → F
  s : F
  pr : F
  pinv : F
  acc : F
  lhs : F

/-- lines 372-380: `ring = [0; 64]`, `sring = [0; K]`, `s = 0`, `pr = 1`, `pinv = 1`, `acc = 0`, `lhs = 0`. -/
def init : St := ⟨fun _ => 0, fun _ => 0, 0, 1, 1, 0, 0⟩

/-- lines 407-430, the body of `if i >= 62`, at `m = i - 62`. `rg` is `ring` after the write of line 383. -/
def firStep (w : Wit) (r rho rinv : F) (st : St) (rg : ℕ → F) (m : ℕ) : St :=
  let wc := rg ((m + HM) % 64)                                                        -- 408
  let lhs := if m < K then st.lhs + st.pr * (w.ci m + rho * w.cq m) else st.lhs       -- 409-413
  let s2 := st.s + st.pr * wc                                                         -- 414
  let n := m + 1 - K                                                                  -- 416
  let act := K ≤ m + 1 ∧ n < L                                                        -- 415, 417
  let sn := st.sring (n % K)                                                          -- 418
  let cp := tf (w.c_i n) + rho * tf (w.c_q n)                                         -- 419
  let g := cp * st.pinv                                                               -- 420
  let acc := if act then st.acc + g * (s2 - sn) else st.acc                           -- 421-422
  let pinv := if act then st.pinv * rinv else st.pinv                                 -- 423-424
  { ring_ := rg
    sring := Function.update st.sring ((m + 1) % K) s2                                -- 427
    s := s2                                                                           -- 428
    pr := st.pr * r                                                                   -- 429-430
    pinv := pinv, acc := acc, lhs := lhs }

/-- lines 382-384: one loop step `i`. -/
def stepAt (w : Wit) (r rho rinv : F) (st : St) (i : ℕ) : St :=
  let rg := Function.update st.ring_ (i % 64) (wF w.x i)
  if 62 ≤ i then firStep w r rho rinv st rg (i - 62) else { st with ring_ := rg }

/-- line 381: the state after the first `i` loop steps. `run … NS` is the state at line 433. -/
def run (w : Wit) (r rho rinv : F) : ℕ → St
  | 0 => init
  | i + 1 => stepAt w r rho rinv (run w r rho rinv i) i

theorem run_succ (w : Wit) (r rho rinv : F) (i : ℕ) :
    run w r rho rinv (i + 1) = stepAt w r rho rinv (run w r rho rinv i) i := rfl

/-- The spot check as the circuit runs it: `1 / r` exists (line 371) and `assert(lhs == acc)` (line 433). -/
def freivaldsOK (w : Wit) (r rho : F) : Prop :=
  ∃ rinv, r * rinv = 1 ∧ (run w r rho rinv NS).lhs = (run w r rho rinv NS).acc

/-! ## The ring buffer is the one `Arrival.lean` uses -/

theorem stepAt_ring (w : Wit) (r rho rinv : F) (st : St) (i : ℕ) :
    (stepAt w r rho rinv st i).ring_ = Function.update st.ring_ (i % 64) (wF w.x i) := by
  simp only [stepAt]
  split <;> rfl

theorem run_ring (w : Wit) (r rho rinv : F) (i : ℕ) :
    (run w r rho rinv (i + 1)).ring_ = ringSt w.x i := by
  induction i with
  | zero => rw [run_succ, stepAt_ring]; rfl
  | succ i ih => rw [run_succ, stepAt_ring, ih]; rfl

/-! ## Invariants -/

/-- The prefix sum of line 336: `S_m = Σ_{k < m} r^k x[lo + k]`, where `x[lo + k]` is window sample `k + HM`. -/
def S (x : ℕ → ℕ) (r : F) (m : ℕ) : F := ∑ k ∈ range m, r ^ k * wF x (k + HM)

theorem S_succ (x : ℕ → ℕ) (r : F) (m : ℕ) : S x r (m + 1) = S x r m + r ^ m * wF x (m + HM) :=
  sum_range_succ _ _

/-- One term of the running sum `acc`: `(cI_n + ρ cQ_n) r^-n (S_{n+K} - S_n)`. -/
def term (w : Wit) (r rho rinv : F) (n : ℕ) : F :=
  (tf (w.c_i n) + rho * tf (w.c_q n)) * rinv ^ n * (S w.x r (n + K) - S w.x r n)

/-- What holds before loop step `m` of the FIR part (loop index `i = m + 62`). -/
structure Inv (w : Wit) (r rho rinv : F) (m : ℕ) (st : St) : Prop where
  s : st.s = S w.x r m
  pr : st.pr = r ^ m
  lhs : st.lhs = ∑ j ∈ range (min m K), r ^ j * (w.ci j + rho * w.cq j)
  acc : st.acc = ∑ n ∈ range (m + 1 - K), term w r rho rinv n
  pinv : st.pinv = rinv ^ (m + 1 - K)
  /-- the slot `n % K` still holds `S_n` for the last `K` values of `n` -/
  sring : ∀ n, n ≤ m → m < n + K → st.sring (n % K) = S w.x r n

theorem run_early (w : Wit) (r rho rinv : F) (i : ℕ) (hi : i ≤ 62) :
    (run w r rho rinv i).sring = (fun _ => 0) ∧ (run w r rho rinv i).s = 0 ∧ (run w r rho rinv i).pr = 1 ∧
    (run w r rho rinv i).pinv = 1 ∧ (run w r rho rinv i).acc = 0 ∧ (run w r rho rinv i).lhs = 0 := by
  induction i with
  | zero => exact ⟨rfl, rfl, rfl, rfl, rfl, rfl⟩
  | succ i ih =>
    obtain ⟨h1, h2, h3, h4, h5, h6⟩ := ih (by omega)
    have hn : ¬ 62 ≤ i := by omega
    have e : run w r rho rinv (i + 1) =
        { run w r rho rinv i with ring_ := Function.update (run w r rho rinv i).ring_ (i % 64) (wF w.x i) } := by
      rw [run_succ]
      simp only [stepAt]
      exact if_neg hn
    rw [e]
    exact ⟨h1, h2, h3, h4, h5, h6⟩

theorem inv_base_at (w : Wit) (r rho rinv : F) (n : ℕ) (hn : n = 62) : Inv w r rho rinv 0 (run w r rho rinv n) := by
  obtain ⟨h1, h2, h3, h4, h5, h6⟩ := run_early w r rho rinv n (by omega)
  have hK : 0 + 1 - K = 0 := by simp [K]
  refine ⟨?_, ?_, ?_, ?_, ?_, ?_⟩
  · simpa [S] using h2
  · simpa using h3
  · simpa using h6
  · rw [hK]; simpa using h5
  · rw [hK]; simpa using h4
  · intro n hn _
    have : n = 0 := by omega
    subst this
    rw [h1]; simp [S]

/-- One FIR step keeps every invariant. This is the induction step of the whole file. It holds for
`m < K + L - 1`, the last step of the loop, so the guard `n < L` of line 417 is always true when it is reached. -/
theorem inv_fir (w : Wit) (r rho rinv : F) {m : ℕ} {st : St} {rg : ℕ → F}
    (h : Inv w r rho rinv m st) (hm : m < K + L - 1)
    (hrg : rg ((m + HM) % 64) = wF w.x (m + HM)) :
    Inv w r rho rinv (m + 1) (firStep w r rho rinv st rg m) := by
  have hKpos : 0 < K := by decide
  have hs2 : st.s + st.pr * rg ((m + HM) % 64) = S w.x r (m + 1) := by
    rw [h.s, h.pr, hrg, S_succ]
  refine ⟨?_, ?_, ?_, ?_, ?_, ?_⟩
  · exact hs2
  · show st.pr * r = r ^ (m + 1)
    rw [h.pr, pow_succ]
  · show (if m < K then st.lhs + st.pr * (w.ci m + rho * w.cq m) else st.lhs) = _
    by_cases hK : m < K
    · rw [if_pos hK, h.lhs, h.pr, min_eq_left (by omega), min_eq_left (by omega), sum_range_succ]
    · rw [if_neg hK, h.lhs, min_eq_right (by omega), min_eq_right (by omega)]
  · show (if K ≤ m + 1 ∧ m + 1 - K < L then
        st.acc + (tf (w.c_i (m + 1 - K)) + rho * tf (w.c_q (m + 1 - K))) * st.pinv *
          (st.s + st.pr * rg ((m + HM) % 64) - st.sring ((m + 1 - K) % K)) else st.acc) = _
    by_cases hK : K ≤ m + 1
    · rw [if_pos ⟨hK, by omega⟩, show m + 1 + 1 - K = (m + 1 - K) + 1 by omega, sum_range_succ, ← h.acc, hs2,
        h.sring (m + 1 - K) (by omega) (by omega), h.pinv]
      unfold term
      rw [show m + 1 - K + K = m + 1 by omega]
    · rw [if_neg (fun hc => hK hc.1), h.acc, show m + 1 - K = 0 by omega, show m + 1 + 1 - K = 0 by omega]
  · show (if K ≤ m + 1 ∧ m + 1 - K < L then st.pinv * rinv else st.pinv) = _
    by_cases hK : K ≤ m + 1
    · rw [if_pos ⟨hK, by omega⟩, h.pinv, show m + 1 + 1 - K = (m + 1 - K) + 1 by omega, pow_succ]
    · rw [if_neg (fun hc => hK hc.1), h.pinv, show m + 1 - K = 0 by omega, show m + 1 + 1 - K = 0 by omega]
  · intro n hn hlt
    show Function.update st.sring ((m + 1) % K) (st.s + st.pr * rg ((m + HM) % 64)) (n % K) = _
    by_cases hnm : n = m + 1
    · subst hnm
      rw [Function.update_self, hs2]
    · rw [Function.update_of_ne (by simp only [K] at hlt ⊢; omega)]
      exact h.sring n (by omega) (by omega)

/-- Every FIR step. -/
theorem inv_all (w : Wit) (r rho rinv : F) (m : ℕ) (hm : m ≤ K + L - 1) :
    Inv w r rho rinv m (run w r rho rinv (m + 62)) := by
  induction m with
  | zero => exact inv_base_at w r rho rinv (0 + 62) (by norm_num)
  | succ m ih =>
    have hprev := ih (by omega)
    have e1 : m + 1 + 62 = (m + 62) + 1 := by omega
    rw [e1, run_succ]
    have hrgEq : Function.update (run w r rho rinv (m + 62)).ring_ ((m + 62) % 64) (wF w.x (m + 62)) =
        ringSt w.x (m + 62) := by
      have hthis := run_ring w r rho rinv (m + 62)
      rw [run_succ, stepAt_ring] at hthis
      exact hthis
    have e2 : stepAt w r rho rinv (run w r rho rinv (m + 62)) (m + 62) =
        firStep w r rho rinv (run w r rho rinv (m + 62)) (ringSt w.x (m + 62)) m := by
      simp only [stepAt]
      rw [if_pos (by omega), hrgEq, Nat.add_sub_cancel]
    rw [e2]
    refine inv_fir w r rho rinv hprev (by omega) ?_
    exact ring_read w.x (m + 62) (m + HM) (by simp only [HM]; omega) (by simp only [HM]; omega)

theorem NS_eq : NS = (K + L - 1) + 62 := by norm_num [NS, K, L]
theorem min_final : min (K + L - 1) K = K := by norm_num [K, L]
theorem L_final : K + L - 1 + 1 - K = L := by norm_num [K, L]

/-- The state at line 433, in closed form, from the invariants alone. -/
theorem lhs_at (w : Wit) (r rho rinv : F) (n : ℕ) (hn : n = (K + L - 1) + 62) :
    (run w r rho rinv n).lhs = ∑ j ∈ range K, r ^ j * (w.ci j + rho * w.cq j) := by
  subst hn
  rw [(inv_all w r rho rinv _ (le_refl _)).lhs, min_final]

theorem lhs_final (w : Wit) (r rho rinv : F) :
    (run w r rho rinv NS).lhs = ∑ j ∈ range K, r ^ j * (w.ci j + rho * w.cq j) :=
  lhs_at w r rho rinv NS NS_eq

theorem acc_at (w : Wit) (r rho rinv : F) (n : ℕ) (hn : n = (K + L - 1) + 62) :
    (run w r rho rinv n).acc = ∑ i ∈ range L, term w r rho rinv i := by
  subst hn
  rw [(inv_all w r rho rinv _ (le_refl _)).acc, L_final]

theorem acc_final (w : Wit) (r rho rinv : F) :
    (run w r rho rinv NS).acc = ∑ n ∈ range L, term w r rho rinv n :=
  acc_at w r rho rinv NS NS_eq

/-- Every read stays inside the window: the correlation at lag `j` reads samples below `NS`. Together with `o < 1024`
(10-bit check, line 504) this means `xs[o + i]` is inside the `NT` array (`window_in_array`). -/
theorem window_reads (n j : ℕ) (hn : n < L) (hj : j < K) : n + j + HM < NS := by
  simp only [L, K, HM, NS] at *; omega

/-- line 382 reads `xs[o + i]`, `i < NS`, and line 504 gives `o < 2^10`, so the index is below `NT = 13312`. -/
theorem window_in_array (o i : ℕ) (ho : o < 2 ^ 10) (hi : i < NS) : o + i < 13312 := by
  simp only [NS] at hi; omega

/-! ## The identity -/

/-- `corr` written in the field. -/
def corrF (c x : ℕ → ℕ) (j : ℕ) : F := ∑ n ∈ range L, tf (c n) * wF x (n + j + HM)

theorem corr_cast (c x : ℕ → ℕ) (j : ℕ) : ((corr c x j : ℤ) : F) = corrF c x j := by
  unfold corr corrF
  push_cast
  refine sum_congr rfl (fun n _ => ?_)
  simp [tfI, wI, tf, wF]

theorem S_window (x : ℕ → ℕ) (r : F) (n k : ℕ) :
    S x r (n + k) - S x r n = ∑ j ∈ range k, r ^ (n + j) * wF x (n + j + HM) := by
  induction k with
  | zero => simp
  | succ k ih =>
    rw [← add_assoc, S_succ, sum_range_succ, ← ih]
    ring

theorem unwind (x : ℕ → ℕ) {r rinv : F} (hr : r * rinv = 1) (n : ℕ) :
    rinv ^ n * (S x r (n + K) - S x r n) = ∑ j ∈ range K, r ^ j * wF x (n + j + HM) := by
  have h1 : rinv ^ n * r ^ n = 1 := by rw [← mul_pow, mul_comm, hr, one_pow]
  rw [S_window, mul_sum]
  refine sum_congr rfl (fun j _ => ?_)
  rw [pow_add]
  linear_combination (r ^ j * wF x (n + j + HM)) * h1

/-- The swap of the two sums: `acc`'s sum over the template equals the sum over lags. -/
theorem acc_closed (w : Wit) {r rinv : F} (rho : F) (hr : r * rinv = 1) :
    ∑ n ∈ range L, term w r rho rinv n =
      ∑ j ∈ range K, r ^ j * (corrF w.c_i w.x j + rho * corrF w.c_q w.x j) := by
  calc ∑ n ∈ range L, term w r rho rinv n
      = ∑ n ∈ range L, ∑ j ∈ range K,
          (tf (w.c_i n) + rho * tf (w.c_q n)) * (r ^ j * wF w.x (n + j + HM)) := by
        refine sum_congr rfl (fun n _ => ?_)
        unfold term
        rw [mul_assoc, unwind w.x hr, mul_sum]
    _ = ∑ j ∈ range K, ∑ n ∈ range L,
          (tf (w.c_i n) + rho * tf (w.c_q n)) * (r ^ j * wF w.x (n + j + HM)) := sum_comm
    _ = ∑ j ∈ range K, r ^ j * (corrF w.c_i w.x j + rho * corrF w.c_q w.x j) := by
        refine sum_congr rfl (fun j _ => ?_)
        unfold corrF
        rw [mul_sum (range L) _ rho, ← sum_add_distrib, mul_sum]
        refine sum_congr rfl (fun n _ => ?_)
        ring

/-- **What the loop computes.** Whatever the prover supplies, at the end of the loop `lhs` is the random combination of
the claimed curve and `acc` is the same combination of the true correlations:
`lhs = Σ_j r^j (ci_j + ρ cq_j)` and `acc = Σ_j r^j (I_j + ρ Q_j)`. The only requirement is that `1 / r` exists, which the
circuit enforces. `I_j`, `Q_j` here are `Arrival.corr`, the very values the arrival proof assumes. No primality, no hash
assumption, no range on the samples. -/
theorem run_identity (w : Wit) {r rinv : F} (rho : F) (hr : r * rinv = 1) :
    (run w r rho rinv NS).lhs = ∑ j ∈ range K, r ^ j * (w.ci j + rho * w.cq j) ∧
    (run w r rho rinv NS).acc =
      ∑ j ∈ range K, r ^ j * (((corr w.c_i w.x j : ℤ) : F) + rho * ((corr w.c_q w.x j : ℤ) : F)) := by
  refine ⟨lhs_final w r rho rinv, ?_⟩
  rw [acc_final, acc_closed w rho hr]
  simp only [corr_cast]

/-- Distance between the claim and the truth at lag `j`: I side. -/
def dI (w : Wit) (j : ℕ) : F := w.ci j - ((corr w.c_i w.x j : ℤ) : F)
/-- Distance between the claim and the truth at lag `j`: Q side. -/
def dQ (w : Wit) (j : ℕ) : F := w.cq j - ((corr w.c_q w.x j : ℤ) : F)

/-- `lhs - acc` is a polynomial in `r` whose coefficients are the errors of the claim. -/
theorem check_iff (w : Wit) {r rinv : F} (rho : F) (hr : r * rinv = 1) :
    (run w r rho rinv NS).lhs = (run w r rho rinv NS).acc ↔
      ∑ j ∈ range K, r ^ j * (dI w j + rho * dQ w j) = 0 := by
  obtain ⟨h1, h2⟩ := run_identity w rho hr
  rw [h1, h2, ← sub_eq_zero, ← sum_sub_distrib]
  have : ∀ j ∈ range K, r ^ j * (w.ci j + rho * w.cq j) -
      r ^ j * (((corr w.c_i w.x j : ℤ) : F) + rho * ((corr w.c_q w.x j : ℤ) : F)) =
      r ^ j * (dI w j + rho * dQ w j) := by
    intro j _
    unfold dI dQ
    ring
  rw [sum_congr rfl this]

/-! ## `1 / r`, and completeness -/

theorem F_zero_ne_one : (0 : F) ≠ 1 := by
  haveI : Fact (1 < p) := ⟨by unfold p; norm_num⟩
  exact zero_ne_one

/-- **`r = 0` is rejected.** `let rinv = 1 / r` (line 371) has no solution at `r = 0`. So the check can't be dodged with
a zero challenge, where every power of `r` but the first would vanish. It also means an honest phone fails if the hash
ever outputs `r = 0`. That is 1 chance in `p` under the random-oracle assumption: a completeness footnote. -/
theorem r_zero_rejected (w : Wit) (rho : F) : ¬ freivaldsOK w 0 rho := by
  rintro ⟨rinv, h, _⟩
  rw [zero_mul] at h
  exact F_zero_ne_one h

theorem r_ne_zero_of_inv {r rinv : F} (hr : r * rinv = 1) : r ≠ 0 := by
  rintro rfl
  rw [zero_mul] at hr
  exact F_zero_ne_one hr

/-- **Completeness.** If the claimed curve is the true correlation, `lhs == acc` holds for every `ρ` and every `r` that
has an inverse. An honest prover can't be caught out by an unlucky challenge, apart from `r = 0`. -/
theorem freivalds_complete (w : Wit) {r rinv : F} (rho : F) (hr : r * rinv = 1)
    (hI : ∀ j, j < K → w.ci j = ((corr w.c_i w.x j : ℤ) : F))
    (hQ : ∀ j, j < K → w.cq j = ((corr w.c_q w.x j : ℤ) : F)) :
    (run w r rho rinv NS).lhs = (run w r rho rinv NS).acc := by
  rw [check_iff w rho hr]
  refine sum_eq_zero (fun j hj => ?_)
  have hj' := mem_range.1 hj
  simp [dI, dQ, hI j hj', hQ j hj']

/-- **Completeness, as the circuit runs it.** True values pass for every nonzero `r` and every `ρ`. This uses that `p` is
prime only to get the inverse of `r`. -/
theorem honest_passes [Fact (Nat.Prime p)] (w : Wit) {r : F} (rho : F) (hr0 : r ≠ 0)
    (hI : ∀ j, j < K → w.ci j = ((corr w.c_i w.x j : ℤ) : F))
    (hQ : ∀ j, j < K → w.cq j = ((corr w.c_q w.x j : ℤ) : F)) :
    freivaldsOK w r rho :=
  ⟨r⁻¹, mul_inv_cancel₀ hr0, freivalds_complete w rho (mul_inv_cancel₀ hr0) hI hQ⟩

/-! ## Root counting (Schwartz-Zippel, by hand), over any finite integral domain -/

section RootCount

open Polynomial

-- A commutative ring with no zero divisors, not `Field`: on `F` this keeps the ring operations literally the
-- ones `check_iff` uses.
variable {𝔽 : Type*} [CommRing 𝔽] [IsDomain 𝔽] [Fintype 𝔽]

/-- `Σ_{j < n} a_j X^j` -/
noncomputable def polyOf (n : ℕ) (a : ℕ → 𝔽) : 𝔽[X] := ∑ j ∈ range n, C (a j) * X ^ j

theorem eval_polyOf (n : ℕ) (a : ℕ → 𝔽) (r : 𝔽) :
    (polyOf n a).eval r = ∑ j ∈ range n, r ^ j * a j := by
  unfold polyOf
  rw [eval_finsetSum]
  refine sum_congr rfl (fun j _ => ?_)
  rw [eval_mul, eval_C, eval_pow, eval_X, mul_comm]

theorem coeff_polyOf {n j : ℕ} (a : ℕ → 𝔽) (hj : j < n) : (polyOf n a).coeff j = a j := by
  unfold polyOf
  rw [finsetSum_coeff]
  simp only [coeff_C_mul_X_pow]
  rw [sum_ite_eq]
  simp [hj]

theorem natDegree_polyOf_le {n : ℕ} (a : ℕ → 𝔽) : (polyOf n a).natDegree ≤ n - 1 := by
  unfold polyOf
  refine natDegree_sum_le_of_forall_le _ _ (fun j hj => ?_)
  have := mem_range.1 hj
  exact (natDegree_C_mul_X_pow_le _ _).trans (by omega)

open scoped Classical in
theorem card_roots_le {P : 𝔽[X]} {d : ℕ} (hP : P ≠ 0) (hd : P.natDegree ≤ d) :
    (univ.filter fun r : 𝔽 => P.eval r = 0).card ≤ d := by
  have hsub : (univ.filter fun r : 𝔽 => P.eval r = 0) ⊆ P.roots.toFinset := by
    intro r hr
    rw [mem_filter] at hr
    rw [Multiset.mem_toFinset, mem_roots hP]
    exact hr.2
  exact (card_le_card hsub).trans (Multiset.toFinset_card_le _ |>.trans ((card_roots' P).trans hd))

open scoped Classical in
/-- **The counting core.** Take any `a_j`, `b_j` for `j < n`, not all zero. Among all pairs `(r, ρ)` of field elements, at most
`n · q` satisfy `Σ_j r^j (a_j + ρ b_j) = 0`, where `q` is the size of the field.

Why: `A(r) = Σ a_j r^j`, `B(r) = Σ b_j r^j` are polynomials of degree below `n`, and one of them is not zero. So at most
`n - 1` values of `r` make both vanish, and each of those can go with any `ρ`: at most `(n - 1) q` pairs. Any other `r` allows
at most one `ρ`: at most `q` pairs more. -/
theorem sz_count (n : ℕ) (a b : ℕ → 𝔽) (hne : ∃ j, j < n ∧ (a j ≠ 0 ∨ b j ≠ 0)) :
    (univ.filter fun z : 𝔽 × 𝔽 => ∑ j ∈ range n, z.1 ^ j * (a j + z.2 * b j) = 0).card
      ≤ n * Fintype.card 𝔽 := by
  obtain ⟨j0, hj0, hj⟩ := hne
  set q := Fintype.card 𝔽 with hq
  have hsplit : ∀ r rho : 𝔽, ∑ j ∈ range n, r ^ j * (a j + rho * b j) =
      (polyOf n a).eval r + rho * (polyOf n b).eval r := by
    intro r rho
    rw [eval_polyOf, eval_polyOf, mul_sum, ← sum_add_distrib]
    refine sum_congr rfl (fun j _ => ?_)
    ring
  -- the `r` where both polynomials vanish
  set Z : Finset 𝔽 := univ.filter fun r => (polyOf n a).eval r = 0 ∧ (polyOf n b).eval r = 0 with hZ
  have hZcard : Z.card ≤ n - 1 := by
    rcases hj with ha | hb
    · have hP : polyOf n a ≠ 0 := fun h0 => ha (by rw [← coeff_polyOf a hj0, h0, coeff_zero])
      refine (card_le_card ?_).trans (card_roots_le hP (natDegree_polyOf_le a))
      intro r hr
      rw [hZ, mem_filter] at hr
      exact mem_filter.2 ⟨mem_univ _, hr.2.1⟩
    · have hP : polyOf n b ≠ 0 := fun h0 => hb (by rw [← coeff_polyOf b hj0, h0, coeff_zero])
      refine (card_le_card ?_).trans (card_roots_le hP (natDegree_polyOf_le b))
      intro r hr
      rw [hZ, mem_filter] at hr
      exact mem_filter.2 ⟨mem_univ _, hr.2.2⟩
  -- everything else allows at most one `ρ`
  set W : Finset (𝔽 × 𝔽) := univ.filter fun z =>
    z.1 ∉ Z ∧ (polyOf n a).eval z.1 + z.2 * (polyOf n b).eval z.1 = 0 with hW
  have hWcard : W.card ≤ q := by
    refine card_le_card_of_injOn Prod.fst (fun _ _ => mem_coe.2 (mem_univ _)) ?_
    rintro ⟨r, rho⟩ h1 ⟨r', rho'⟩ h2 hfst
    simp only at hfst
    subst hfst
    have h1' := (mem_filter.1 (mem_coe.1 h1)).2
    have h2' := (mem_filter.1 (mem_coe.1 h2)).2
    simp only at h1' h2'
    by_cases hb0 : (polyOf n b).eval r = 0
    · exfalso
      apply h1'.1
      have ha0 := h1'.2
      rw [hb0, mul_zero, add_zero] at ha0
      exact mem_filter.2 ⟨mem_univ _, ha0, hb0⟩
    · have : rho * (polyOf n b).eval r = rho' * (polyOf n b).eval r := by
        linear_combination h1'.2 - h2'.2
      rw [mul_right_cancel₀ hb0 this]
  have hsub : (univ.filter fun z : 𝔽 × 𝔽 => ∑ j ∈ range n, z.1 ^ j * (a j + z.2 * b j) = 0) ⊆
      (Z ×ˢ (univ : Finset 𝔽)) ∪ W := by
    rintro ⟨r, rho⟩ hz
    have hz' := (mem_filter.1 hz).2
    simp only at hz'
    rw [hsplit] at hz'
    by_cases hrZ : r ∈ Z
    · exact mem_union_left _ (mem_product.2 ⟨hrZ, mem_univ _⟩)
    · exact mem_union_right _ (mem_filter.2 ⟨mem_univ _, hrZ, hz'⟩)
  have hprod : ((Z ×ˢ (univ : Finset 𝔽))).card = Z.card * q := by
    rw [card_product, card_univ]
  have hn1 : 1 ≤ n := by omega
  calc _ ≤ ((Z ×ˢ (univ : Finset 𝔽)) ∪ W).card := card_le_card hsub
    _ ≤ (Z ×ˢ (univ : Finset 𝔽)).card + W.card := card_union_le _ _
    _ ≤ (n - 1) * q + q := by
        rw [hprod]
        exact add_le_add (Nat.mul_le_mul_right _ hZcard) hWcard
    _ = n * q := by
        obtain ⟨n', rfl⟩ : ∃ n', n = n' + 1 := ⟨n - 1, by omega⟩
        simp only [Nat.add_sub_cancel]
        ring

end RootCount

/-! ## Soundness -/

/-- The claimed curve differs from the true correlation somewhere. -/
def Wrong (w : Wit) : Prop :=
  ∃ j, j < K ∧ (w.ci j ≠ ((corr w.c_i w.x j : ℤ) : F) ∨ w.cq j ≠ ((corr w.c_q w.x j : ℤ) : F))

/-- The challenge `(r, ρ)` fools the check: the claim is wrong, and the circuit accepts it. -/
def Fooled (w : Wit) (r rho : F) : Prop := Wrong w ∧ freivaldsOK w r rho

theorem wrong_coeff {w : Wit} {j : ℕ}
    (hne : w.ci j ≠ ((corr w.c_i w.x j : ℤ) : F) ∨ w.cq j ≠ ((corr w.c_q w.x j : ℤ) : F)) :
    dI w j ≠ 0 ∨ dQ w j ≠ 0 := by
  rcases hne with h | h
  · exact Or.inl (sub_ne_zero.2 h)
  · exact Or.inr (sub_ne_zero.2 h)

/-- A filter that implies another has no more elements, whichever way each filter is decided. -/
theorem card_filter_mono {α : Type*} [Fintype α] {P Q : α → Prop} [DecidablePred P] [DecidablePred Q]
    (h : ∀ z, P z → Q z) : (univ.filter P).card ≤ (univ.filter Q).card :=
  card_le_card (fun z hz => mem_filter.2 ⟨mem_univ _, h z (mem_filter.1 hz).2⟩)

open scoped Classical in
/-- `sz_count` on `ZMod m`, for a VARIABLE modulus. Proved here and only then applied at `p`: with the 254-bit literal in
sight the kernel tries to compute through `ZMod p`, and this proof did not finish. -/
theorem sz_count_zmod {m : ℕ} [NeZero m] [IsDomain (ZMod m)] (n : ℕ) (a b : ℕ → ZMod m)
    (hne : ∃ j, j < n ∧ (a j ≠ 0 ∨ b j ≠ 0)) :
    (univ.filter fun z : ZMod m × ZMod m => ∑ j ∈ range n, z.1 ^ j * (a j + z.2 * b j) = 0).card ≤ n * m := by
  have hcount := sz_count (𝔽 := ZMod m) n a b hne
  rw [ZMod.card] at hcount
  -- `sz_count` decides its filter classically, while here the filter uses `ZMod`'s real decidable equality.
  -- `card_filter_mono` works across the two instances, so they are never compared.
  exact le_trans (@card_filter_mono _ _ _ _ _ (fun _ => Classical.propDecidable _) (fun _ h => h)) hcount

open scoped Classical in
theorem sum_count_F [IsDomain F] (w : Wit) (hw : Wrong w) :
    (univ.filter fun z : F × F => ∑ j ∈ range K, z.1 ^ j * (dI w j + z.2 * dQ w j) = 0).card ≤ K * p := by
  obtain ⟨j, hj, hne⟩ := hw
  exact sz_count_zmod (m := p) K (dI w) (dQ w) ⟨j, hj, wrong_coeff hne⟩

theorem fooled_sum (w : Wit) (z : F × F) (h : Fooled w z.1 z.2) :
    ∑ j ∈ range K, z.1 ^ j * (dI w j + z.2 * dQ w j) = 0 := by
  obtain ⟨_, rinv, hr, heq⟩ := h
  exact (check_iff w z.2 hr).1 heq

open scoped Classical in
/-- `fooled_count`, from "`F` has no zero divisors". No `Fact` is in scope here, so `CommRing F` stays `ZMod.commRing p`. -/
theorem fooled_count_dom [IsDomain F] (w : Wit) :
    (univ.filter fun z : F × F => Fooled w z.1 z.2).card ≤ 193 * p := by
  by_cases hw : Wrong w
  · refine (card_le_card ?_).trans ((sum_count_F w hw).trans (le_of_eq (congrArg (· * p) (rfl : K = 193))))
    intro z hz
    exact mem_filter.2 ⟨mem_univ _, fooled_sum w z (mem_filter.1 hz).2⟩
  · have : (univ.filter fun z : F × F => Fooled w z.1 z.2) = ∅ := by
      refine filter_eq_empty_iff.2 (fun z _ hz => hw hz.1)
    rw [this]
    exact Nat.zero_le _

open scoped Classical in
/-- **Soundness, the count.** Fix the recording window, the templates and the claimed curve. If the claim is wrong
anywhere, at most `193 · p` of the `p²` pairs `(r, ρ)` make the check pass. If the claim is right, no pair fools it.

This is a plain count. It does not say the pair is hard to steer, because it says nothing about where the pair comes
from: `r, ρ` must be fixed AFTER everything else, and see `known_r_fools` for what happens otherwise. The primality of `p`
is a hypothesis here, never proved in this repo. -/
theorem fooled_count [Fact (Nat.Prime p)] (w : Wit) :
    (univ.filter fun z : F × F => Fooled w z.1 z.2).card ≤ 193 * p :=
  fooled_count_dom w

/-- Plain arithmetic, for variable numbers. -/
theorem odds_of_count (c m : ℕ) (hm : 0 < m) (h : c ≤ 193 * m) :
    (c : ℚ) / ((m * m : ℕ) : ℚ) ≤ 193 / (m : ℚ) := by
  have hp : (0 : ℚ) < (m : ℚ) := by exact_mod_cast hm
  have hc : (c : ℚ) ≤ 193 * (m : ℚ) := by exact_mod_cast h
  rw [div_le_div_iff₀ (by push_cast; exact mul_pos hp hp) hp]
  push_cast
  calc _ ≤ 193 * (m : ℚ) * (m : ℚ) := mul_le_mul_of_nonneg_right hc hp.le
    _ = _ := by ring

/-- Plain arithmetic, for variable numbers. -/
theorem frac_of_count (c N i m : ℕ) (hN : 0 < N) (hm : 0 < m) (h : c * m ≤ i * 193 * N) :
    (c : ℚ) / (N : ℚ) ≤ (i : ℚ) * 193 / (m : ℚ) := by
  have hN' : (0 : ℚ) < (N : ℚ) := by exact_mod_cast hN
  have hm' : (0 : ℚ) < (m : ℚ) := by exact_mod_cast hm
  rw [div_le_div_iff₀ hN' hm']
  exact_mod_cast h

/-- Plain arithmetic, for variable numbers: cancel one factor of `m`. -/
theorem cancel_count (c N i m : ℕ) (hm : 0 < m) (h : c * (m * m) ≤ i * (193 * m) * N) :
    c * m ≤ i * 193 * N := by
  refine Nat.le_of_mul_le_mul_right ?_ hm
  calc c * m * m = c * (m * m) := by ring
    _ ≤ i * (193 * m) * N := h
    _ = i * 193 * N * m := by ring

/-- The number of pairs, for a variable modulus. -/
theorem card_pairs (m : ℕ) [NeZero m] : Fintype.card (ZMod m × ZMod m) = m * m := by
  rw [Fintype.card_prod, ZMod.card]

/-- The odds as a fraction of all pairs, for a variable modulus. -/
theorem odds_zmod {m : ℕ} [NeZero m] (T : Finset (ZMod m × ZMod m)) (h : T.card ≤ 193 * m) :
    (T.card : ℚ) / (Fintype.card (ZMod m × ZMod m) : ℚ) ≤ 193 / (m : ℚ) := by
  rw [card_pairs]
  exact odds_of_count _ m (Nat.pos_of_ne_zero (NeZero.ne m)) h

open scoped Classical in
/-- **The odds.** Over a uniformly chosen pair `(r, ρ)`, the chance of fooling the check is at most `193 / p`. The word
"uniformly" is the assumption: this is a statement about counting pairs, and `fs_challenges` is what must behave like a
uniform choice. See `rom_union_bound`. -/
theorem fooled_odds [Fact (Nat.Prime p)] (w : Wit) :
    ((univ.filter fun z : F × F => Fooled w z.1 z.2).card : ℚ) / (Fintype.card (F × F) : ℚ) ≤ 193 / (p : ℚ) := by
  exact odds_zmod _ (fooled_count w)

/-- `193 / p` is below `2^-246`. -/
theorem odds_numeric : (193 : ℚ) / (p : ℚ) < 1 / 2 ^ 246 := by
  have h : 193 * 2 ^ 246 < p := by unfold p; norm_num
  have hq : (193 : ℚ) * 2 ^ 246 < (p : ℚ) := by exact_mod_cast h
  have hp : (0 : ℚ) < (p : ℚ) := lt_trans (by positivity) hq
  rw [div_lt_div_iff₀ hp (by positivity)]
  linarith

/-- **Bookkeeping, true by definition.** `Fooled` means "wrong and passes". So once the check has passed, "not fooled" is just
another way to write "`ci`, `cq` are the true correlations", and this theorem only unpacks that. It never looks at the loop.
The hypothesis of the arrival proof is not discharged here: that takes the count, see `arrival_bad_pairs_count`. -/
theorem claim_true_of_not_fooled {w : Wit} {r rho : F} (hok : freivaldsOK w r rho) (hnf : ¬ Fooled w r rho) :
    (∀ j, j < K → w.ci j = ((corr w.c_i w.x j : ℤ) : F)) ∧
    (∀ j, j < K → w.cq j = ((corr w.c_q w.x j : ℤ) : F)) := by
  have hw : ¬ Wrong w := fun hw => hnf ⟨hw, hok⟩
  constructor
  · intro j hj
    by_contra hne
    exact hw ⟨j, hj, Or.inl hne⟩
  · intro j hj
    by_contra hne
    exact hw ⟨j, hj, Or.inr hne⟩

/-- **The arrival theorem, restated, true by definition.** With `hok`, the hypothesis `hnf` says exactly that `ci`, `cq` are the
true correlations, so this is `self_side_arrival_sound` with its hypothesis renamed. It proves nothing about the spot check.
It is the step `arrival_bad_pairs_count` uses to turn "fooled" into "arrival false". The Freivalds content is in `fooled_count`.
As in `Arrival.lean`, `0 ≥ 0` passes, so this does not say a beep was heard. -/
theorem self_side_sound_unless_fooled {w : Wit} {r rho : F} {u : ℕ → Bool} {ut : F}
    (hx : ∀ i, i < NS → isU16 (w.x i))
    (hci_t : ∀ n, n < L → isU8 (w.c_i n)) (hcq_t : ∀ n, n < L → isU8 (w.c_q n))
    (hok : freivaldsOK w r rho) (hnf : ¬ Fooled w r rho)
    (h : ArrivalOK u (dF w.x w.c_i w.ci w.cq) ut) :
    ∃ a, a < K ∧ (a : F) = ut ∧ (∀ j, j < K → (u j = true ↔ j < a)) ∧
      (∀ j, j < a → BAR * env2 w.x w.c_i w.c_q j < bigC w.x w.c_i j) ∧
      bigC w.x w.c_i a ≤ BAR * env2 w.x w.c_i w.c_q a := by
  obtain ⟨hI, hQ⟩ := claim_true_of_not_fooled hok hnf
  exact self_side_arrival_sound hx hci_t hcq_t hI hQ h

/-- The conclusion of the arrival theorem, for a witness, as a name: there is a lag `a < 193`, equal to the public
`usum_target`, marked by the flags `u`, such that `BAR · match < loudness` at every lag before `a`, and
`BAR · match ≥ loudness` at `a`. All of it is about the TRUE correlations of the window. -/
def ArrivalHolds (w : Wit) (u : ℕ → Bool) (ut : F) : Prop :=
  ∃ a, a < K ∧ (a : F) = ut ∧ (∀ j, j < K → (u j = true ↔ j < a)) ∧
    (∀ j, j < a → BAR * env2 w.x w.c_i w.c_q j < bigC w.x w.c_i j) ∧
    bigC w.x w.c_i a ≤ BAR * env2 w.x w.c_i w.c_q a

open scoped Classical in
/-- **The arrival theorem, with Block C replaced by a count of bad challenges.** Fix the recording window (u16), the templates
(u8), the claimed curve, the flags `u` and `usum_target`, with every arrival constraint holding at the claimed curve. Of the
`p²` pairs `(r, ρ)`, at most `193 p` pass the spot check while the arrival conclusion is false.

So the hypothesis "the curve is the true one" of `self_side_arrival_sound` is gone. What's left is "`(r, ρ)` is not one of these
few pairs". This is still a plain count: that the real pair avoids them is the random-oracle assumption, not proved here. -/
theorem arrival_bad_pairs_count [Fact (Nat.Prime p)] {w : Wit} {u : ℕ → Bool} {ut : F}
    (hx : ∀ i, i < NS → isU16 (w.x i))
    (hci_t : ∀ n, n < L → isU8 (w.c_i n)) (hcq_t : ∀ n, n < L → isU8 (w.c_q n))
    (h : ArrivalOK u (dF w.x w.c_i w.ci w.cq) ut) :
    (univ.filter fun z : F × F => freivaldsOK w z.1 z.2 ∧ ¬ ArrivalHolds w u ut).card ≤ 193 * p := by
  refine le_trans (card_filter_mono (Q := fun z : F × F => Fooled w z.1 z.2) (fun z hz => ?_)) (fooled_count w)
  by_contra hnf
  exact hz.2 (self_side_sound_unless_fooled hx hci_t hcq_t hz.1 hnf h)

open scoped Classical in
/-- **The same count, when the flags are picked after the challenge.** `u` is not absorbed in `fs_challenges`, so a prover may
choose it after seeing `(r, ρ)`. That gains nothing: the bad pairs are counted with the flags and `usum_target` free. At most
`193 p` pairs pass while SOME flags satisfy the arrival constraints and the arrival conclusion is false for them. -/
theorem arrival_bad_pairs_count_any_flags [Fact (Nat.Prime p)] {w : Wit}
    (hx : ∀ i, i < NS → isU16 (w.x i))
    (hci_t : ∀ n, n < L → isU8 (w.c_i n)) (hcq_t : ∀ n, n < L → isU8 (w.c_q n)) :
    (univ.filter fun z : F × F => freivaldsOK w z.1 z.2 ∧
      ∃ u ut, ArrivalOK u (dF w.x w.c_i w.ci w.cq) ut ∧ ¬ ArrivalHolds w u ut).card ≤ 193 * p := by
  refine le_trans (card_filter_mono (Q := fun z : F × F => Fooled w z.1 z.2) (fun z hz => ?_)) (fooled_count w)
  obtain ⟨hok, u, ut, h, hna⟩ := hz
  by_contra hnf
  exact hna (self_side_sound_unless_fooled hx hci_t hcq_t hok hnf h)

open scoped Classical in
/-- **The odds of `arrival_bad_pairs_count`.** Over a uniformly chosen pair, passing the check with a false arrival conclusion has
odds at most `193 / p`, which `odds_numeric` puts below `2^-246`. The word "uniformly" is the random-oracle assumption. -/
theorem arrival_bad_odds [Fact (Nat.Prime p)] {w : Wit} {u : ℕ → Bool} {ut : F}
    (hx : ∀ i, i < NS → isU16 (w.x i))
    (hci_t : ∀ n, n < L → isU8 (w.c_i n)) (hcq_t : ∀ n, n < L → isU8 (w.c_q n))
    (h : ArrivalOK u (dF w.x w.c_i w.ci w.cq) ut) :
    ((univ.filter fun z : F × F => freivaldsOK w z.1 z.2 ∧ ¬ ArrivalHolds w u ut).card : ℚ) /
      (Fintype.card (F × F) : ℚ) ≤ 193 / (p : ℚ) :=
  odds_zmod _ (arrival_bad_pairs_count hx hci_t hcq_t h)

/-! ## Why the order of events matters -/

/-- **If `r` were known before the claim was fixed, the check would be worthless.** Take a true curve and any `r` with an
inverse. Add `r` to `ci[0]` and subtract 1 from `ci[1]`. The curve is now wrong, and it passes for every `ρ`, because
the two errors cancel: `r^0 · r + r^1 · (-1) = 0`.

So the whole value of this check rests on `r` being fixed after `ci`, `cq`, the samples and the templates. That is why
the absorption order is audited below, and why no count over pairs can stand in for the random-oracle assumption. -/
theorem known_r_fools (w : Wit)
    (hI : ∀ j, j < K → w.ci j = ((corr w.c_i w.x j : ℤ) : F))
    (hQ : ∀ j, j < K → w.cq j = ((corr w.c_q w.x j : ℤ) : F))
    {r rinv : F} (hr : r * rinv = 1) (rho : F) :
    Fooled { w with ci := fun j => w.ci j + (if j = 0 then r else if j = 1 then -1 else 0) } r rho := by
  set w' : Wit := { w with ci := fun j => w.ci j + (if j = 0 then r else if j = 1 then -1 else 0) } with hw'
  have hx : w'.x = w.x := rfl
  have hc : w'.c_i = w.c_i := rfl
  have hcq : w'.c_q = w.c_q := rfl
  have h0K : 0 < K := by decide
  have h1K : 1 < K := by decide
  refine ⟨⟨0, h0K, Or.inl ?_⟩, rinv, hr, ?_⟩
  · intro h
    have e : w'.ci 0 = w.ci 0 + r := by simp [hw']
    rw [e, hx, hc, ← hI 0 h0K] at h
    exact r_ne_zero_of_inv hr (add_eq_left.1 h)
  · rw [check_iff w' rho hr]
    have hterm : ∀ j ∈ range K, r ^ j * (dI w' j + rho * dQ w' j) =
        r ^ j * (if j = 0 then r else if j = 1 then -1 else 0) := by
      intro j hj
      have hj' := mem_range.1 hj
      have e1 : dI w' j = (if j = 0 then r else if j = 1 then -1 else 0) := by
        unfold dI
        rw [hx, hc]
        show w.ci j + _ - _ = _
        rw [hI j hj']
        ring
      have e2 : dQ w' j = 0 := by
        unfold dQ
        rw [hx, hcq]
        show w.cq j - _ = 0
        rw [hQ j hj', sub_self]
      rw [e1, e2]
      ring
    rw [sum_congr rfl hterm, sum_eq_add_of_mem 0 1 (mem_range.2 h0K) (mem_range.2 h1K) (by norm_num)]
    · simp
    · intro c _ hc'
      rw [if_neg hc'.1, if_neg hc'.2, mul_zero]

/-- The recording is digital silence, the templates are flat (`tf = 0`), so every true correlation and all the energy are zero.
The claimed curve is wrong at two lags: `t` at lag 0 and `-t` at lag 1. -/
def moveWit (t : F) : Wit :=
  ⟨silent, fun _ => 128, fun _ => 128, fun j => if j = 0 then t else if j = 1 then -t else 0, fun _ => 0⟩

theorem CNA_flat (n : ℕ) : CNA (fun _ => 128) n = 0 := by
  induction n with
  | zero => rfl
  | succ n ih => simp [CNA, ih, tf]

/-- `T` solves `BAR · T² = -5` in the field when `BAR · T² + 5` is a multiple of `p`. Variable `T`, so no 254-bit literal here. -/
theorem sq_of_multiple (T Q : ℕ) (h : 4474747 * T * T + 5 = p * Q) : ((BAR : ℤ) : F) * ((T : F) * (T : F)) = -5 := by
  have hc := congrArg (Nat.cast : ℕ → F) h
  rw [Nat.cast_mul p Q, ZMod.natCast_self, zero_mul] at hc
  push_cast at hc
  have hB : ((BAR : ℤ) : F) = 4474747 := by simp [BAR]
  rw [hB]
  linear_combination hc

/-- The general form of `wrong_curve_moves_arrival`, for any `t` with `BAR · t² = -5`. -/
theorem moveWit_all (t : F) (ht : ((BAR : ℤ) : F) * (t * t) = -5) (rho : F) :
    freivaldsOK (moveWit t) 1 rho ∧
    ArrivalOK (fun j => decide (j < 2)) (dF silent (fun _ => 128) (moveWit t).ci (moveWit t).cq) ((2 : ℕ) : F) ∧
    ¬ ArrivalHolds (moveWit t) (fun j => decide (j < 2)) ((2 : ℕ) : F) := by
  have hc0 : ∀ c j, corr c silent j = 0 := fun c j =>
    sum_eq_zero (fun n _ => by rw [wI_silent, mul_zero])
  have h0K : 0 < K := by decide
  have h1K : 1 < K := by decide
  refine ⟨⟨1, mul_one 1, (check_iff (moveWit t) rho (mul_one 1)).2 ?_⟩, ?_, ?_⟩
  · have hterm : ∀ j ∈ range K, (1 : F) ^ j * (dI (moveWit t) j + rho * dQ (moveWit t) j) =
        (if j = 0 then t else if j = 1 then -t else 0) := by
      intro j _
      have e1 : dI (moveWit t) j = (if j = 0 then t else if j = 1 then -t else 0) := by
        show (if j = 0 then t else if j = 1 then -t else 0) - ((corr (fun _ => 128) silent j : ℤ) : F) = _
        rw [hc0]; simp
      have e2 : dQ (moveWit t) j = 0 := by
        show (0 : F) - ((corr (fun _ => 128) silent j : ℤ) : F) = 0
        rw [hc0]; simp
      rw [e1, e2, one_pow, one_mul, mul_zero, add_zero]
    rw [sum_congr rfl hterm, sum_eq_add_of_mem 0 1 (mem_range.2 h0K) (mem_range.2 h1K) (by norm_num)]
    · simp
    · intro c _ hc'
      rw [if_neg hc'.1, if_neg hc'.2]
  · refine arrival_complete (fun j => if j < 2 then 5 else 0) (fun j _ => ?_) (fun j _ => ?_) 2 (by decide)
      (fun j hj => ?_) (by norm_num)
    · have hC : bigCF silent (fun _ => 128) j = 0 := by
        unfold bigCF
        rw [CNA_flat, mul_zero]
      unfold dF env2F
      rw [hC]
      show (0 : F) - ((BAR : ℤ) : F) * ((if j = 0 then t else if j = 1 then -t else 0) *
        (if j = 0 then t else if j = 1 then -t else 0) + 0 * 0) = _
      by_cases hj0 : j = 0
      · subst hj0
        simp only [if_true, Nat.zero_lt_two]
        push_cast
        linear_combination -ht
      · by_cases hj1 : j = 1
        · subst hj1
          simp only [one_ne_zero, if_false, if_true, Nat.one_lt_two]
          push_cast
          linear_combination -ht
        · have hj2 : ¬ j < 2 := by omega
          simp [hj0, hj1, hj2]
    · split_ifs <;> norm_num
    · simp [hj]
  · rintro ⟨a, _, _, hiff, hb, _⟩
    have ha : 0 < a := (hiff 0 h0K).1 (by simp)
    have hlt := hb 0 ha
    have hy0 : ∀ m, yI silent m = 0 := fun m =>
      sum_eq_zero (fun t _ => by rw [wI_silent, mul_zero])
    have hE0 : EI silent 0 = 0 := sum_eq_zero (fun m _ => by rw [hy0]; norm_num)
    have hb0 : bigC silent (fun _ => 128) 0 = 0 := by simp [bigC, hE0]
    have he0 : env2 silent (fun _ => 128) (fun _ => 128) 0 = 0 := by simp [env2, hc0]
    have hlt' : BAR * env2 silent (fun _ => 128) (fun _ => 128) 0 < bigC silent (fun _ => 128) 0 := hlt
    rw [hb0, he0] at hlt'
    simp at hlt'

/-- **The bad pairs are real: a wrong curve can pass and move the arrival.** Digital silence and flat templates, so every true
correlation is zero and the true first lag passing the test is 0. Claim the curve `t, -t, 0, 0, …` with `t` chosen so that
`BAR · t² = -5`. At `r = 1`, for every `ρ`, the two errors cancel and the spot check passes. All the arrival constraints hold at the
claimed curve with `usum_target = 2`. Yet the arrival conclusion is false. So the check really can be fooled at a pair, and the count
in `arrival_bad_pairs_count` can't be replaced by zero.

This is no attack on the circuit: `r = 1` was picked after the fact, and `(1, ρ)` is one of the bad pairs for this input. In the real
circuit the prover would have to get `r = 1` out of the hash. No primality is used. -/
theorem wrong_curve_moves_arrival :
    ∃ (w : Wit) (u : ℕ → Bool) (ut : F),
      (∀ i, i < NS → isU16 (w.x i)) ∧ (∀ n, n < L → isU8 (w.c_i n)) ∧ (∀ n, n < L → isU8 (w.c_q n)) ∧
      ArrivalOK u (dF w.x w.c_i w.ci w.cq) ut ∧ ¬ ArrivalHolds w u ut ∧ ∀ rho, freivaldsOK w 1 rho := by
  have ht := sq_of_multiple 133000484291441286342549414662442663973303751116631445006103920758912720298
    3616296501790571749874907549335611017921390399085897296464192878512003277514129
    (by unfold p; norm_num)
  refine ⟨moveWit _, _, _, fun i _ => silent_u16 i, fun _ _ => ?_, fun _ _ => ?_,
    (moveWit_all _ ht 0).2.1, (moveWit_all _ ht 0).2.2, fun rho => (moveWit_all _ ht rho).1⟩ <;>
  · show (128 : ℕ) < 2 ^ 8
    norm_num

/-! ## What goes into the hash (lib.nr 302-332)

The check is only as good as the list below. The audit is:

| What the identity reads | How it is fixed before the challenge |
|---|---|
| `ci[j]`, `cq[j]`, all 193 lags | absorbed directly (lines 325-330) |
| templates `c_i`, `c_q` | absorbed through `code[0] = cc` (`phone/main.nr` 33-34, 38), needs `code_commitment` to bind |
| samples `xs[o + i]` | absorbed through `rec_root` (line 317), needs the Merkle tree to bind |
| offset `o`, `leaf_s` | not absorbed, but pinned by `p_self` (line 318) and the range checks, `window_offset_unique` |
| `r`, `ρ` themselves | output of the hash, `Sp.finish` (line 331), cells 0 and 1 of the same permutation output |

`u`, `salt`, the partner window `xp`, `chs`, `chp`, `sig`, `csig`, `hold`, `exp`, `issuer`, `sr`, `valid_at` are not absorbed.
The identity reads none of them, and `arrival_bad_pairs_count_any_flags` shows that picking `u` late gains nothing.
`code[1]` is always 0 in `phone/main.nr` (line 38), so it carries nothing. The table is for `phone/main.nr` only. `phone_pub` passes
`[code_hi, code_lo]` with `Field` templates, and it is not covered. -/

/-- line 45: `TAG_FS = 9 + (398 << 8)`. The sponge has no length padding, so the tag is what fixes the length. -/
theorem TAG_FS_records_length : (101897 : ℕ) = 9 + 398 * 256 := by norm_num

/-- lines 313-330: the list of absorbed values, in order. `bf role_b` is `role_b as Field`. `(96 : F)` is `DELTA` (line 320). -/
def fsInput (nonce_hi nonce_lo : F) (attempt : ℕ) (role_b : Bool)
    (rec_root p_self p_partner a_self a_partner : F) (code0 code1 : F) (ci cq : ℕ → F) : List F :=
  [nonce_hi, nonce_lo, (attempt : F), bf role_b, rec_root, p_self, p_partner, (96 : F), a_self, a_partner, code0, code1]
    ++ (List.range K).map ci ++ (List.range K).map cq

/-- The list has 398 entries, which is the length `TAG_FS` declares. -/
theorem fsInput_length (nonce_hi nonce_lo : F) (attempt : ℕ) (role_b : Bool)
    (rec_root p_self p_partner a_self a_partner code0 code1 : F) (ci cq : ℕ → F) :
    (fsInput nonce_hi nonce_lo attempt role_b rec_root p_self p_partner a_self a_partner code0 code1 ci cq).length
      = 398 := by
  simp [fsInput, K]

/-- lines 302-332 over an arbitrary hash `H`. `H` stands for the sponge (`Sp`, tag `TAG_FS`), and nothing is known about it. -/
def fs_challenges (H : List F → F × F) (nonce_hi nonce_lo : F) (attempt : ℕ) (role_b : Bool)
    (rec_root p_self p_partner a_self a_partner code0 code1 : F) (ci cq : ℕ → F) : F × F :=
  H (fsInput nonce_hi nonce_lo attempt role_b rec_root p_self p_partner a_self a_partner code0 code1 ci cq)

/-- **The absorbed list determines what it should.** Two equal lists have the same `rec_root`, `p_self`, `code[0]` and the same
curve at all 193 lags. So a prover can't change the claimed curve without changing the hash input. -/
theorem fsInput_determines {nonce_hi nonce_lo nonce_hi' nonce_lo' : F} {attempt attempt' : ℕ} {role_b role_b' : Bool}
    {rec_root p_self p_partner a_self a_partner code0 code1 : F}
    {rec_root' p_self' p_partner' a_self' a_partner' code0' code1' : F} {ci cq ci' cq' : ℕ → F}
    (h : fsInput nonce_hi nonce_lo attempt role_b rec_root p_self p_partner a_self a_partner code0 code1 ci cq =
      fsInput nonce_hi' nonce_lo' attempt' role_b' rec_root' p_self' p_partner' a_self' a_partner' code0' code1' ci' cq') :
    rec_root = rec_root' ∧ p_self = p_self' ∧ code0 = code0' ∧
      (∀ j, j < K → ci j = ci' j) ∧ (∀ j, j < K → cq j = cq' j) := by
  unfold fsInput at h
  obtain ⟨h1, h2⟩ := List.append_inj h (by simp)
  obtain ⟨h3, h4⟩ := List.append_inj h1 (by simp)
  simp only [List.cons.injEq, List.nil_eq, and_true] at h3
  obtain ⟨_, _, _, _, hroot, hps, _, _, _, _, hc0, _⟩ := h3
  exact ⟨hroot, hps, hc0, fun j hj => List.map_inj_left.1 h4 j (List.mem_range.2 hj),
    fun j hj => List.map_inj_left.1 h2 j (List.mem_range.2 hj)⟩

/-- **`p_self` pins the window offset and the first leaf, so they don't have to be absorbed.** Line 503 computes
`os = p_self - DELTA - HM - 1024 * leaf_s`. Line 504 forces `os < 1024`, and line 109 forces `leaf_s < 256`. So `os` and
`leaf_s` are the remainder and the quotient of `p_self - 127` by 1024: two witnesses with the same `p_self` have the same `os` and
the same `leaf_s`. Nothing can wrap, because `os + 1024 * leaf_s` is far below `p`. -/
theorem window_offset_unique {p_self os os' leaf leaf' : F}
    (h : os = p_self - 96 - 31 - 1024 * leaf) (h' : os' = p_self - 96 - 31 - 1024 * leaf')
    (ho : fits 10 os) (ho' : fits 10 os') (hl : fits 8 leaf) (hl' : fits 8 leaf') :
    os = os' ∧ leaf = leaf' := by
  obtain ⟨a, ha, rfl⟩ := fits_exists_nat ho
  obtain ⟨a', ha', rfl⟩ := fits_exists_nat ho'
  obtain ⟨f, hf, rfl⟩ := fits_exists_nat hl
  obtain ⟨f', hf', rfl⟩ := fits_exists_nat hl'
  norm_num at ha ha' hf hf'
  have hcast : ((a + 1024 * f : ℕ) : F) = ((a' + 1024 * f' : ℕ) : F) := by
    push_cast
    linear_combination h - h'
  have hv := congrArg ZMod.val hcast
  rw [val_natCast_of_lt (natCast_lt_p_of_lt_two_pow (k := 19) (by norm_num) (by norm_num; omega)),
    val_natCast_of_lt (natCast_lt_p_of_lt_two_pow (k := 19) (by norm_num) (by norm_num; omega))] at hv
  have e1 : a = a' := by omega
  have e2 : f = f' := by omega
  exact ⟨by rw [e1], by rw [e2]⟩

/-- Named hypothesis, block B: same root and same first leaf means same samples in the opened array. `Commit.two_openings_agree`
proves this leaf by leaf under Poseidon2 no-collision hypotheses. It is not imported here, so this stays an assumption. -/
def RecRootBinds (rec_root rec_root' leaf leaf' : F) (xs xs' : ℕ → ℕ) : Prop :=
  rec_root = rec_root' → leaf = leaf' → ∀ k, k < 13312 → xs k = xs' k

/-- Named hypothesis, block H: same `code_commit` means same templates. `Commit.code_commitment_binds` proves this under
a Poseidon2 no-collision hypothesis. It is not imported here, so this stays an assumption. -/
def CodeCommitBinds (cc cc' : F) (c_i c_q c_i' c_q' : ℕ → ℕ) : Prop :=
  cc = cc' → (∀ n, n < L → c_i n = c_i' n) ∧ (∀ n, n < L → c_q n = c_q' n)

/-- **Nothing the identity reads escapes the hash input, given two binding assumptions.** Take any two witnesses whose absorbed lists are
equal, so they get the same challenge from any hash. Their claimed curves agree, as this file proves. Given the offset equation and the
range checks for both witnesses (`hos`, `ho`, `hl`, which the circuit enforces), their offsets agree, as this file proves.

The sample windows and templates agree only because `hB` and `hH` are assumed for these two witnesses. `RecRootBinds` and
`CodeCommitBinds` are hypotheses about this one pair. They are not derived here from "Poseidon2 has no collisions", and this file doesn't
connect them to `Commit.lean`. The theorem takes no "the check passed" hypothesis, and it doesn't need one. So, IF those two hypotheses hold,
a prover can't look at `(r, ρ)` and then change anything the check reads. -/
theorem absorbed_pins_identity {nonce_hi nonce_lo nonce_hi' nonce_lo' : F} {attempt attempt' : ℕ} {role_b role_b' : Bool}
    {rec_root p_self p_partner a_self a_partner code0 code1 : F}
    {rec_root' p_self' p_partner' a_self' a_partner' code0' code1' : F} {ci cq ci' cq' : ℕ → F}
    {os os' leaf leaf' : F} {xs xs' c_i c_q c_i' c_q' : ℕ → ℕ}
    (h : fsInput nonce_hi nonce_lo attempt role_b rec_root p_self p_partner a_self a_partner code0 code1 ci cq =
      fsInput nonce_hi' nonce_lo' attempt' role_b' rec_root' p_self' p_partner' a_self' a_partner' code0' code1' ci' cq')
    (hos : os = p_self - 96 - 31 - 1024 * leaf) (hos' : os' = p_self' - 96 - 31 - 1024 * leaf')
    (ho : fits 10 os) (ho' : fits 10 os') (hl : fits 8 leaf) (hl' : fits 8 leaf')
    (hB : RecRootBinds rec_root rec_root' leaf leaf' xs xs') (hH : CodeCommitBinds code0 code0' c_i c_q c_i' c_q') :
    (∀ j, j < K → ci j = ci' j) ∧ (∀ j, j < K → cq j = cq' j) ∧
    (∀ i, i < NS → xs (os.val + i) = xs' (os'.val + i)) ∧
    (∀ n, n < L → c_i n = c_i' n) ∧ (∀ n, n < L → c_q n = c_q' n) := by
  obtain ⟨hroot, hps, hc0, hI, hQ⟩ := fsInput_determines h
  subst hps
  obtain ⟨hoo, hll⟩ := window_offset_unique hos hos' ho ho' hl hl'
  obtain ⟨ht1, ht2⟩ := hH hc0
  refine ⟨hI, hQ, fun i hi => ?_, ht1, ht2⟩
  rw [← hoo]
  exact hB hroot hll _ (window_in_array _ _ ho hi)

/-! ## The random-oracle statement (LABELLED: an idealization, not a fact about Poseidon2) -/

theorem card_fun_hit {ι α : Type*} [Fintype ι] [DecidableEq ι] [Fintype α] (t : ι) (T : Finset α)
    [DecidablePred fun H : ι → α => H t ∈ T] :
    (univ.filter fun H : ι → α => H t ∈ T).card * Fintype.card α = T.card * Fintype.card (ι → α) := by
  have hset : (univ.filter fun H : ι → α => H t ∈ T) =
      Fintype.piFinset (fun i => if i = t then T else univ) := by
    ext H
    simp only [mem_filter, mem_univ, true_and, Fintype.mem_piFinset]
    constructor
    · intro h i
      by_cases hi : i = t
      · subst hi; simpa using h
      · simp [hi]
    · intro h
      simpa using h t
  have h1 : ∏ i, (if i = t then T else (univ : Finset α)).card =
      T.card * ∏ i ∈ univ.erase t, Fintype.card α := by
    rw [← mul_prod_erase univ _ (mem_univ t)]
    simp only [if_true]
    congr 1
    refine prod_congr rfl (fun i hi => ?_)
    rw [if_neg (ne_of_mem_erase hi), card_univ]
  have h2 : Fintype.card (ι → α) = Fintype.card α * ∏ i ∈ univ.erase t, Fintype.card α := by
    have : Fintype.card (ι → α) = ∏ _i : ι, Fintype.card α := by simp
    rw [this, ← mul_prod_erase univ _ (mem_univ t)]
  rw [hset, Fintype.card_piFinset, h1, h2]
  ring

open scoped Classical in
/-- **LABELLED: the random-oracle statement. This is NOT a theorem about Poseidon2.**

Suppose the hash were a truly random function: every input gets a fresh uniform pair `(r, ρ)`, with all the inputs independent of each
other. A cheater tries a fixed list `ι` of hash inputs, each with its own witness `D t`. Then, over the choice of that random function,
the chance that any try fools the check is at most `|ι| · 193 / p`. So at `2^64` tries the odds are below `2^-182`.

What this assumes, in the open:
* `H` is uniform. Poseidon2 is a fixed function, so this is a model of it. It is not derived from anything.
* Each input `t` has just one witness `D t`. That's where binding comes in: `absorbed_pins_identity` is what justifies a function `D`
  here, and it needs its two named hypotheses.
* The list `ι` is fixed in advance. A real attacker can pick its next try after seeing the last answer. The standard argument gives the
  same bound for that case, but it is not machine-checked here.
* The real sponge has one capacity cell (lib.nr 49-73), so generic collision security tops out around `2^127` work. That sits outside
  this model. -/
theorem rom_union_bound [Fact (Nat.Prime p)] {ι : Type*} [Fintype ι] [DecidableEq ι] (D : ι → Wit) :
    ((univ.filter fun H : ι → F × F => ∃ t, Fooled (D t) (H t).1 (H t).2).card : ℚ) /
      (Fintype.card (ι → F × F) : ℚ) ≤ (Fintype.card ι : ℚ) * 193 / (p : ℚ) := by
  set N := Fintype.card (ι → F × F) with hN
  set bad : ι → Finset (F × F) := fun t => univ.filter fun z : F × F => Fooled (D t) z.1 z.2 with hbad
  have hpn : 0 < p := Nat.pos_of_ne_zero (NeZero.ne p)
  have hNpos : 0 < N := Fintype.card_pos
  have hsub : (univ.filter fun H : ι → F × F => ∃ t, Fooled (D t) (H t).1 (H t).2) ⊆
      univ.biUnion (fun t => univ.filter fun H : ι → F × F => H t ∈ bad t) := by
    intro H hH
    obtain ⟨t, ht⟩ := (mem_filter.1 hH).2
    exact mem_biUnion.2 ⟨t, mem_univ _, mem_filter.2 ⟨mem_univ _, mem_filter.2 ⟨mem_univ _, ht⟩⟩⟩
  have hcard : (univ.filter fun H : ι → F × F => ∃ t, Fooled (D t) (H t).1 (H t).2).card * (p * p)
      ≤ Fintype.card ι * (193 * p) * N := by
    have hq : Fintype.card (F × F) = p * p := card_pairs p
    calc _ ≤ (univ.biUnion (fun t => univ.filter fun H : ι → F × F => H t ∈ bad t)).card * (p * p) :=
          Nat.mul_le_mul_right _ (card_le_card hsub)
      _ ≤ (∑ t : ι, (univ.filter fun H : ι → F × F => H t ∈ bad t).card) * (p * p) :=
          Nat.mul_le_mul_right _ card_biUnion_le
      _ = ∑ t : ι, (univ.filter fun H : ι → F × F => H t ∈ bad t).card * (p * p) := by rw [sum_mul]
      _ = ∑ t : ι, (bad t).card * N := by
          refine sum_congr rfl (fun t _ => ?_)
          rw [← hq, card_fun_hit]
      _ ≤ ∑ _t : ι, (193 * p) * N :=
          sum_le_sum (fun t _ => Nat.mul_le_mul_right _ (fooled_count (D t)))
      _ = Fintype.card ι * (193 * p) * N := by
          rw [sum_const, card_univ, smul_eq_mul]
          ring
  exact frac_of_count _ N _ p hNpos hpn (cancel_count _ N _ p hpn hcard)

/-- The arithmetic in the docstring above: `2^64` tries give odds below `2^-182`. -/
theorem odds_2_64_tries : (2 : ℚ) ^ 64 * 193 / (p : ℚ) < 1 / 2 ^ 182 := by
  have h := odds_numeric
  have e : (2 : ℚ) ^ 64 * 193 / (p : ℚ) = 2 ^ 64 * (193 / (p : ℚ)) := by ring
  rw [e]
  calc (2 : ℚ) ^ 64 * (193 / (p : ℚ)) < 2 ^ 64 * (1 / 2 ^ 246) :=
        mul_lt_mul_of_pos_left h (by positivity)
    _ = 1 / 2 ^ 182 := by norm_num

end Freivalds
end Popfv

#print axioms Popfv.Freivalds.run_ring
#print axioms Popfv.Freivalds.inv_all
#print axioms Popfv.Freivalds.run_identity
#print axioms Popfv.Freivalds.check_iff
#print axioms Popfv.Freivalds.r_zero_rejected
#print axioms Popfv.Freivalds.freivalds_complete
#print axioms Popfv.Freivalds.honest_passes
#print axioms Popfv.Freivalds.sz_count
#print axioms Popfv.Freivalds.sz_count_zmod
#print axioms Popfv.Freivalds.fooled_count_dom
#print axioms Popfv.Freivalds.fooled_count
#print axioms Popfv.Freivalds.fooled_odds
#print axioms Popfv.Freivalds.odds_numeric
#print axioms Popfv.Freivalds.claim_true_of_not_fooled
#print axioms Popfv.Freivalds.self_side_sound_unless_fooled
#print axioms Popfv.Freivalds.arrival_bad_pairs_count
#print axioms Popfv.Freivalds.arrival_bad_pairs_count_any_flags
#print axioms Popfv.Freivalds.arrival_bad_odds
#print axioms Popfv.Freivalds.known_r_fools
#print axioms Popfv.Freivalds.wrong_curve_moves_arrival
#print axioms Popfv.Freivalds.fsInput_length
#print axioms Popfv.Freivalds.fsInput_determines
#print axioms Popfv.Freivalds.window_offset_unique
#print axioms Popfv.Freivalds.absorbed_pins_identity
#print axioms Popfv.Freivalds.card_fun_hit
#print axioms Popfv.Freivalds.rom_union_bound
#print axioms Popfv.Freivalds.odds_2_64_tries
