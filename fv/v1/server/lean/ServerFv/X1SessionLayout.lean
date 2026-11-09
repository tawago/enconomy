import ServerFv.X1Session

/-!
# The session hypotheses can hold (Known gap 4)

`X1_session` takes a long list of hypotheses. This file meets all of them at once, on the Lean copy of
the wire layout (`Layout.prims`, the setting `layoutEnv`), so the theorem is not empty:

* `X1_session_on_layout`: halves 100 and 0, rates 48000, versions 1 or 2 on each side (mixed too),
  flight 1715/48 cm. Its conclusion is `X1Reached`, so it pins the all-zero recording values and
  self deltas in the stored commits and transcripts too.
* `X1_session_on_layout_edges`: both rate ends at once, A at 36000 and B at 96000, halves 0, flight 0.

The stand-in signatures and hash have no security, as in `Powers_satisfiable`. The base64 decoder is
the identity. Device ids are their own keys. Nothing here reads sound (CN1).
-/

set_option linter.style.whitespace false
set_option linter.style.longLine false
set_option linter.style.header false
set_option linter.unusedVariables false

namespace ServerFv
namespace Machine

/-- The setting on the Lean layout: prims `Layout.prims`, base64 decoding is the identity, a device id
is its own enrolled key, and the server's `code_commit` is 32 zero bytes whatever the codes. None of
it is `codec.py`, `base64` or `popt2.py`; it only shows the hypotheses can be met. -/
def layoutEnv : Env Layout.Bytes Layout.Bytes :=
  { p := Layout.prims, b64d := some, pk := id, code_commit := fun _ _ _ => Layout.fill 32 0 }

/-- The token used below is already lower case. Checked by kernel reduction (`decide +kernel`, no
extra axiom); plain `decide` and `rfl` get stuck on `String.map`. -/
theorem layout_token_lower : "t".toLower = "t" := by decide +kernel

/-- All-zero 32 bytes pass the field-size check. -/
theorem layout_root_zero : Layout.prims.rec_root_ok (Layout.fill 32 0) = true := by
  simp only [Layout.prims, Layout.rootOk, Layout.fill, Layout.unbe_fill_zero]
  simp [Layout.R]

/-- The two device ids differ, so do their keys. -/
theorem layout_fill_ne : Layout.fill 65 1 ≠ Layout.fill 65 2 := by
  intro h; have := congrArg List.head? h; simp [Layout.fill] at this

/-- **`X1_session` is not empty.** The proof feeds `X1_session` this pick on `layoutEnv`: devices
`fill 65 1` (host) and `fill 65 2` (guest), token "t", halves 100 and 0, rates 48000, calibration 0,
all-zero recordings and nonce, self deltas 0, and any versions 1 or 2 on each side. Every hypothesis
of `X1_session` holds for it, for all four version pairs.

**What the statement pins.** `X1Reached` for this pick: the nine requests from the `create` at `T`
with this `sid`, all-zero nonce, `seed` and token "t" end at `T + 4411` on a `done` document that
keeps them, whose result is NEAR, no reason, attempt 0, flight `flight_exact 100 48000 0 48000`,
which is 1715/48 cm, the two device rows, and whose stored commits and transcripts carry the all-zero
recording values, halves 100 and 0, and self deltas 0 for both roles.

**What it does not pin.** Nothing about `codec.py`, base64 or the real hash and signatures: the
layout prims are stand-ins with no security. Nothing about sound (CN1). The flight is exact; Python
would store `round(float(f), 2)`, 35.73. -/
theorem X1_session_on_layout (verA verB : ℕ) (hvA : verA = 1 ∨ verA = 2) (hvB : verB = 1 ∨ verB = 2)
    (sid : Layout.Bytes) (seed : String) (T : ℕ) :
    X1Reached layoutEnv (Layout.fill 65 1) (Layout.fill 65 2) sid (Layout.fill 32 0)
      (Layout.fill 32 0) (Layout.fill 32 0) seed "t" T (fun _ => 0) verA verB 100 0 0 0 48000 48000 ∧
    flight_exact 100 48000 0 48000 = 1715 / 48 := by
  have hflight := toy_flight
  have hself : ∀ v : ℕ, self_os_ok 0 48000 (if v = 2 then 0 else (fun _ : Layout.Bytes => (0 : ℤ)) (Layout.fill 65 1)) = true := by
    intro v; norm_num [self_os_ok]
  have hself' : ∀ v : ℕ, self_os_ok 0 48000 (if v = 2 then 0 else (fun _ : Layout.Bytes => (0 : ℤ)) (Layout.fill 65 2)) = true := by
    intro v; norm_num [self_os_ok]
  have hw32 : Layout.prims.width (Layout.fill 32 0) = 32 := by simp [Layout.prims, Layout.fill]
  refine ⟨?_, hflight⟩
  exact X1_session layoutEnv (Layout.fill 65 1) (Layout.fill 65 2) sid (Layout.fill 32 0)
    (Layout.fill 32 0) (Layout.fill 32 0) seed "t" T (fun _ => 0) verA verB 100 0 0 0 48000 48000
    (Powers_satisfiable _ _) (fun x => ⟨x, rfl⟩) Layout.prims_sha_width
    layout_fill_ne layout_fill_ne layout_token_lower
    (by simp [layoutEnv, Layout.prims, Layout.fill]) (by simp [layoutEnv, Layout.prims, Layout.fill])
    (by simp [layoutEnv, Layout.prims, Layout.fill]) (by simp [layoutEnv, Layout.prims, Layout.fill])
    (by simp [layoutEnv, Layout.prims, Layout.fill]) hvA hvB
    (fun _ => ⟨layout_root_zero, hw32⟩) (fun _ => ⟨layout_root_zero, hw32⟩)
    (by norm_num) (by norm_num) (by norm_num) (by norm_num)
    (by norm_num) (by norm_num) (by norm_num) (by norm_num)
    (by norm_num) (by norm_num) (by norm_num) (by norm_num)
    (hself verA) (hself' verB)
    (by rw [hflight]; norm_num) (by rw [hflight]; norm_num)

/-- The flight at the rate ends with both halves 0 is 0. -/
theorem layout_edge_flight : flight_exact 0 36000 0 96000 = 0 := by
  norm_num [flight_exact]

/-- **Both rate ends at once.** As `X1_session_on_layout`, but A runs at 36000 and B at 96000, the
two ends of the allowed range, with both halves 0, so the flight is 0 cm. The session model still
reaches a `done` NEAR result with both device rows.

**What it pins.** The rate bounds in `X1_session` can be met at their ends together, with any
versions 1 or 2 on each side. The conclusion is `X1Reached` for this pick, so it names the run from
the `create` at `T`, the rows at 36000 and 96000 with halves 0, the all-zero recording values and
self deltas 0 in the stored commits and transcripts, and flight `flight_exact 0 36000 0 96000` = 0.

**What it does not pin.** As above: stand-in prims, no `codec.py`, nothing about sound (CN1). -/
theorem X1_session_on_layout_edges (verA verB : ℕ) (hvA : verA = 1 ∨ verA = 2)
    (hvB : verB = 1 ∨ verB = 2) (sid : Layout.Bytes) (seed : String) (T : ℕ) :
    X1Reached layoutEnv (Layout.fill 65 1) (Layout.fill 65 2) sid (Layout.fill 32 0)
      (Layout.fill 32 0) (Layout.fill 32 0) seed "t" T (fun _ => 0) verA verB 0 0 0 0 36000 96000 ∧
    flight_exact 0 36000 0 96000 = 0 := by
  have hflight := layout_edge_flight
  have hselfA : ∀ v : ℕ, self_os_ok 0 36000 (if v = 2 then 0 else (fun _ : Layout.Bytes => (0 : ℤ)) (Layout.fill 65 1)) = true := by
    intro v; norm_num [self_os_ok]
  have hselfB : ∀ v : ℕ, self_os_ok 0 96000 (if v = 2 then 0 else (fun _ : Layout.Bytes => (0 : ℤ)) (Layout.fill 65 2)) = true := by
    intro v; norm_num [self_os_ok]
  have hw32 : Layout.prims.width (Layout.fill 32 0) = 32 := by simp [Layout.prims, Layout.fill]
  refine ⟨?_, hflight⟩
  exact X1_session layoutEnv (Layout.fill 65 1) (Layout.fill 65 2) sid (Layout.fill 32 0)
    (Layout.fill 32 0) (Layout.fill 32 0) seed "t" T (fun _ => 0) verA verB 0 0 0 0 36000 96000
    (Powers_satisfiable _ _) (fun x => ⟨x, rfl⟩) Layout.prims_sha_width
    layout_fill_ne layout_fill_ne layout_token_lower
    (by simp [layoutEnv, Layout.prims, Layout.fill]) (by simp [layoutEnv, Layout.prims, Layout.fill])
    (by simp [layoutEnv, Layout.prims, Layout.fill]) (by simp [layoutEnv, Layout.prims, Layout.fill])
    (by simp [layoutEnv, Layout.prims, Layout.fill]) hvA hvB
    (fun _ => ⟨layout_root_zero, hw32⟩) (fun _ => ⟨layout_root_zero, hw32⟩)
    (by norm_num) (by norm_num) (by norm_num) (by norm_num)
    (by norm_num) (by norm_num) (by norm_num) (by norm_num)
    (by norm_num) (by norm_num) (by norm_num) (by norm_num)
    (hselfA verA) (hselfB verB)
    (by rw [hflight]; norm_num) (by rw [hflight]; norm_num)

end Machine
end ServerFv

/-! ## Axioms -/

#print axioms ServerFv.Machine.layout_token_lower
#print axioms ServerFv.Machine.X1_session_on_layout
#print axioms ServerFv.Machine.X1_session_on_layout_edges
