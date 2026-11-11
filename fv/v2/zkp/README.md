# fv/v2/zkp: Lean proofs of the v2 detection rule

The v2 rule is the fixed rule in [`../spec.md`](../spec.md), section 5: the match on the filtered audio, a loudness floor, and `cq` in the template energy. It is fixes 1, 2 and 3 of [`../../v1/next-version-fixes.md`](../../v1/next-version-fixes.md) together.

No v2 circuit exists yet. So this models the proposed rule, not code that runs. `BAR`, the filter taps, the floor and the bit widths aren't fixed (roadmap stage 3, real recordings, hasn't run). The rule theorems hold for any `BAR`, any taps, any `FLOOR >= 1`. Witnesses and mutants use small concrete values, and say so.

`lake build` passes on all 5 proof files with no `sorry`. Every theorem uses only `propext`, `Classical.choice`, `Quot.sound`.

Comments follow the words of [ADR 0001](../adr/0001-direct-webrtc-link-and-plain-words.md).

## Build

```bash
cd fv/v2/zkp
lake exe cache get              # prebuilt Mathlib
lake build                      # all files, or `lake build Popfv2.Ceiling` for one
```

Same toolchain and Mathlib as `fv/v1/zkp/popfv`. Mathlib is heavy: on a small machine build one file at a time and never run two Lean jobs at once.

**Expected.** `Build completed successfully (18190 jobs).` and 28 axiom lines. Warnings about modules and copyright are harmless.

## The model

`Popfv2/Rule.lean` defines the v2 rule as a pure function at one lag. Signals are integer sequences read on a window of length `n` (a function plus a length, not a `List`). The filter is `y[m] = Σ h[t] · w[m + t]`, any `T` taps, the same form as v1's `yI`. All values are exact integers: no field, no overflow.

```
I = Σ ci·y    Q = Σ cq·y    E = Σ y²    cn2 = Σ ci² + Σ cq²    M = I² + Q²
Pass  :=  E·cn2 >= FLOOR  and  BAR·M >= E·cn2
```

`passAt`, `FirstPass` (self side, first passing lag) and `PartnerPass` (partner side, the named lag, inside the window) lift it to a window. The file doesn't import v1. It copies `tfI` (centered template byte) and the shape of `yI`, `EI`, `II`, `CI` from `fv/v1/zkp/popfv/Popfv/PartnerGlue.lean`.

Each proof file also has mutants: the v2 rule with one fix taken out, plus the full v1 rule as a baseline. They live in `Rule.lean` too: `cn2CiOnly` (fix 3 out), `RatioRaw` and `PassRaw` (fix 1 out), `PassV1` (all three out, so `Code.v1_all128_passes` does not isolate one fix).

`PassY`, `Pass` and the rest take `BAR` and `FLOOR` as plain integers and don't check them. The spec's `FLOOR >= 1` is a hypothesis on each theorem that needs it. `PassY 1 0` accepts silence. `BAR >= 1` needs no check: with `FLOOR >= 1` a pass already gives it (`pass_needs_bar_ge_one`).

## Results

| File | Spec | Main theorem | Not vacuous | Mutant |
|---|---|---|---|---|
| `Ceiling.lean` | RC | `ceiling`: `M <= E·cn2`, for every recording. `pass_needs_bar_ge_one`: with a floor, nothing passes unless `BAR >= 1`. `pass_score_bounds`: a pass has `0 < E·cn2`, `E·cn2 <= BAR·M <= BAR·E·cn2`. | the bound is reached; a pass at `BAR = 1` | `ciOnly_unbounded`: without `cq` in `cn2`, the score has no ceiling. `raw_breaks_ceiling`: raw match, `M = 9 > 4`. |
| `Silence.lean` | RS | `silent_rejected`, `pass_silence`: a zero filtered window, or a recording zero over the filter span, fails. `no_arrival_in_silence`, `no_partner_pass_in_silence`. `zero_template_rejected`: `cn2 = 0` fails for every recording. | a real recording passes | `silence_passes_without_floor`: drop the floor and silence passes for every `BAR`. |
| `Tone.lean` | RT | `ratio_scale`: the ratio test is the same for `y` and `g·y`, any integer `g != 0`. `gain_route`: if the filter scales a signal by `p/q` (`p, q != 0`), the v2 rule's ratio test on the filtered signal is the ratio test on the raw one, same `BAR`. The floor part is not invariant. | gain `1/7`: raw match passes, the v2 rule fails | `gain_route_raw`: raw match turns `BAR` into `BAR·q²/p²` (stated cross-multiplied, so `p = 0` is allowed). `raw_route_witness`: for every `BAR >= 1`, a recording passes raw match and fails the v2 rule. |
| `Code.lean` | gap 5, fix 3 | `all128_both_rejected`: both templates all-128 gives `cn2 = 0`, rejected. `ci_zero_pass_iff`: only `ci` all-128, the v2 rule is a plain correlation test on `cq`. | `cq = [1]` passes | `v1_all128_passes`: the v1 rule passes every recording with an all-128 `ci`. |

### Read before quoting

- **The tone is not proved rejected.** What is proved: the filter gain cancels (RT), and no score is above 1 (RC). So v1's route, match through gain 1 and loudness through gain 0.14, is gone. Under the v2 rule a 500 Hz tone is judged by its plain correlation with the code, which depends on the code, the phase and `BAR`. That is a `circuit-cases` rerun and a stage 3 question, not a Lean one.
- **Gain is modeled as an exact integer ratio on the window.** A real filter also shifts a tone's phase and has edge effects at the window ends. Neither is modeled. `raw_route_witness` is not a gain example: its recording is a DC offset plus a dip, and no single ratio maps the raw window `[2, 1]` to the filtered `[1, -1]`. It only shows raw match and filtered energy disagreeing. The gain example is the `1/7` one in `Tone.lean`.
- **The floor, not fix 3, closes gap 5.** `floor_alone_rejects_all128`: the floor with v1's ci-only energy already rejects an all-128 `ci`. Fix 3's real job is the ceiling: without `cq` in `cn2`, one nonzero `ci` and a large `cq` give any score (`ciOnly_unbounded`).
- **`BAR >= 1` or nothing passes.** By RC the score is at most 1, so the ratio test needs `BAR >= 1`. With `cq` in `cn2` an honest score drops, so `BAR` must be set from real recordings with `cn2` computed the new way (spec section 5).
- **The floor only catches exact silence, at `FLOOR = 1`.** The real taps don't sum to 0, so with a nonzero template a DC offset of one step passes the floor and is judged by the ratio alone (spec K11). A higher floor could reject it; stage 3 picks it. The floor isn't scale-free on purpose (`floor_not_scale_free`).
- **One lag, exact integers.** No bit widths, no field wraparound, no circuit, no app. Whether the circuit, the app and `popt2.py` compute this rule bit for bit is a later step.

## v1 theorems, v2 status

| v1 theorem (`fv/v1/zkp/popfv/Popfv/`) | v2 status |
|---|---|
| `Bar.partner_silence_accepts`, `Bar.self_silence_accepts` | **flipped**: `Silence.silent_rejected`, `no_partner_pass_in_silence`, `no_arrival_in_silence` |
| `Bar.silence_score_below_bar` | **moot**: silence no longer passes, so there is nothing to compare |
| `WitnessChain.all128_self`, `all128_first`, `all128_partner` | **flipped in part**: the free pass is gone. Both templates all-128: rejected (`Code.all128_both_rejected`). Only `ci` all-128: the v2 rule is a plain correlation test on `cq` (`Code.ci_zero_pass_iff`), which a recording can still pass. `floor_alone_rejects_all128` is about the floor with ci-only energy, not the v2 rule. `Code.v1_all128_passes` restates the v1 hole |
| tone witness (`circuit-cases`, gap 2) | not a v1 theorem. The algebra is redone: `Tone.gain_route_raw` is the v1 route, `Tone.gain_route` shows it closed. The tone run itself flips in `nargo`, not here |
| `Bar.bar_iff_ratio`, `bar_iff_sqrt`, `below_bar_iff_sqrt`, `bar_iff_score` | unchanged in form (the test is still `B·m >= L`), not redone. On a passing lag their `0 < L` assumption now holds, since the floor gives it. On a "not yet" lag it still doesn't |
| `Bar.T0eff_*`, `g_range_*`, `inv_sqrt_*`, `round_eq_iff_g2` | not redone: they derive v1's bar from the gain `g` (`round(g²/T0²)`), generic in `T0eff_close`, `round_eq_iff_g2`, `inv_sqrt_bounds`, and checked at 4474747 (48 kHz) and 3792174 (44.1 kHz). The v2 rule's `BAR` has no `g`; stage 3 sets it |
| `Bar.partner_bar_of_fits`, `self_before_arrival`, `self_at_arrival` | not redone: field encoding, needs the v2 circuit |
| `Arrival.*`, `PartnerGlue.*`, `Freivalds.*`, `Commit.*`, `Signed.*`, `Chain.*`, `Pair.*` | not redone: needs the v2 circuit |
| `AppPasses.*`, `AppParity.*` | not redone: needs the v2 app rule |
