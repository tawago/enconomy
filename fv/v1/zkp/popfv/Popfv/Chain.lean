import Popfv.Pair
import Popfv.Arrival
import Popfv.PartnerGlue
import Popfv.Bar
import Popfv.Commit
import Popfv.Freivalds
import Popfv.Signed

/-!
# Popfv.Chain — the whole statement: `phone`, twice, then `pair`

Sources, all under `research/worldid/prototypes/optA-noir/noir/`: `phone/src/main.nr`, `pair/src/main.nr`,
`oalib/src/lib.nr` (deployed `phone_core`, `self_side`, `partner_side`, not `*_opt`). Bare line numbers are `lib.nr`.

The other files prove one block each. This file writes `phone_circuit` as ONE statement over ONE set of variables, using the
block models unchanged, so nothing here is proved about a different circuit. It is hand-written, like the block models.
No tool extracted it from Noir.

## Read this before quoting anything

`phone_sound` and `presence_sound` say what the checks enforce, under named assumptions. They do NOT say a beep was heard,
and they say NOTHING about where the phones really were.

* "Loud enough" means the literal integer test `BAR * match >= loudness`. That includes `0 >= 0`.
* `silence_satisfies_phone_sound` and `silence_satisfies_presence_sound` are the known silence case, machine-checked: two
  all-silent recordings, with no sound in them at all, meet every hypothesis of these theorems and every conclusion, and `pair` reads
  flight 0 cm. Same shape as `circuit-cases` e1.
* Silence is not the only exception. Loudness above zero doesn't mean a beep either: a clean 500 Hz tone, written to a file before any code exists, solved the real
  `phone` circuit on 6 of 6 fresh sessions (`circuit-cases` d). That's a run in `nargo`, not a theorem here, and a file, not a room.
* Any signer can sign any recording, so "signed" says who signed, not that what they signed is true.
* Live NEAR doesn't run these circuits (`server/pop/verdict.py:165`).

## What is assumed

| Name | What | Where |
|---|---|---|
| `Assumptions.issuer_sig`, `device_sig` | no forged signature, on these exact digests | `Signed.Unforgeable` |
| `Assumptions.issuer_hash`, `device_hash` | no SHA-256 collision with what the key signed | `Signed.NoCollisionWith` |
| `Assumptions.root_is_recording` | the signed `rec_root` is the root of a tree over `rcd` | not enforced by the circuit, dropped in `phone_sound_no_tree` |
| `Assumptions.self_paths`, `partner_paths` | no Poseidon2 collision along the opened paths | `Commit.BindsToRecording` |
| `hspot` | the challenge `(r, rho)` isn't one of the few bad pairs | `Freivalds.Fooled`, see below |
| `HalfBinds` | no Poseidon2 collision between each phone's output and `pair`'s opening | here |

These are the main hypotheses, not all of them. The theorem statements also take: input types (`PhoneTypes`, `hat`, `hsa`, `hsb`), `rcd_u16` (the recording holds `u16` samples), and `hb` in `phone_sound_no_tree`. Read the statements for the full list. Some trust is built into the model itself and appears in no theorem statement: Noir's `to_be_bytes` is canonical (`Signed.IsBE`), `to_le_bits` gives 8 bits (`fits 8`), Noir really enforces the input types, the hand model equals the Noir, and the compiler, prover and Solidity verifier are faithful. The verifier must also pin `issuer` and `code_commit`: an all-128 `c_i` gives loudness 0 and passes on any audio (`WitnessChain.all128_self`).

About `hspot`. Given that the check passed, "not fooled" is the same thing as "the claimed curve is true"
(`Freivalds.claim_true_of_not_fooled`). So on its own it would be the old assumption with a new name. What makes it worth having
is `phone_bad_challenges`: for a fixed witness at most `193 p` of the `p²` pairs can accept with the conclusion false.

Getting from that count to "the real challenge avoids those pairs" takes two more things, and neither is proved:

* The random-oracle assumption: the hash output acts like a fresh uniform pair. `Freivalds.rom_union_bound` is the labelled form. It covers a fixed list
  of tries, not an attacker who picks each try after seeing the last answer.
* Poseidon2 binding, so the witness really is fixed before the challenge. `fs_challenges` absorbs `cc` and `rec_root`, not the templates or the samples.
  The count only applies if those two hashes pin them down. `Commit.CodeBinds` would say that for the templates, and it is NOT in `Assumptions`.
  With a collision in `code_commitment`, a prover could swap `c_is` after seeing `(r, rho)`, and the hash input would not change.

None of this touches `phone_sound` itself, because `hspot` is stated on the final witness. It limits what `phone_bad_challenges` can be quoted for.

## The word "keys" means X coordinates

Whenever this file says keys are in the output, or crossed, or different, it means X coordinates only: bytes 40-71 (own) and 105-136 (partner). The output hashes no Y, and `pair` sees no Y.
Partner Y (bytes 137-168) is never read by the circuit (table in `Signed.lean`). So nothing here says A's partner Y is B's own Y. A can sign any partner Y: `check_signed` accepts and gives the same output (`Signed.junk_accepted`), and `pair` never sees Y, so by reading it should accept too. No theorem states that last step.
Meanwhile the server compares whole public keys (`server/pop/verdict.py:159`). Own Y is covered only by the two signatures: `PhoneConclusion.issuer_signed` and `device_signed` name it.

`[Fact (Nat.Prime p)]` is a hypothesis only of `phone_bad_challenges` and `phone_bad_odds`.

## Where the block models had to be lined up

* `Arrival` and `Freivalds` index the window (`x i` is `xs[o + i]`), and `PartnerGlue` and `Commit` index the array. `selfWindow` is the
  one shift, with `o = os as u32`.
* `Pair` and `PartnerGlue` take an opaque `H`, and `Commit` builds the sponge. Here `H := Commit.hash_n perm` everywhere, and
  `fsHash` is the same sponge under `TAG_FS`. One `perm`, for the whole statement.
* `Pair`'s role is the literal `0` or `1`, and `phone_core`'s is `role_b as Field`. They only meet through `HalfBinds`, so the role, nonce,
  attempt and rate of each phone come from `HalfBinds` in `presence_sound`. Once both circuits accept, `HalfBinds` says exactly that the two lists are equal, so this is the collision assumption doing the work, not a free result.
* `Arrival` and `PartnerGlue` each carry their own FIR table and `BAR`. `tables_agree` checks they are the same numbers.
* `Assumptions` and the conclusions talk about the recording `rcd`, not the prover's arrays (`arrival_window_congr`,
  `partner_window_congr`).
-/

set_option linter.style.whitespace false
set_option linter.style.longLine false
set_option linter.style.header false

namespace Popfv
namespace Chain

open PartnerGlue (beF beNat bytesOK osF opF pSelf aPartner aSelf pPartner half sod asU32 usumTarget partnerAccepts
  aSelfF pPartnerF pSelfF aPartnerF halfF boolF HalfOpening halfCommit)
open Commit (hash_n Perm open_leaves code_commitment recRoot BindsToRecording)

/-! ## All the inputs of `phone/src/main.nr`, by name -/

/-- The arguments of `main` in `phone/src/main.nr` (lines 5-31), and the outputs of the `to_be_bytes` calls, which are the only values
the circuit computes that aren't functions of the arguments in this model. -/
structure Witness where
  /-- main.nr 5-12, public -/
  nonce_hi : F
  nonce_lo : F
  attempt : Nat
  role_b : Bool
  code_commit : F
  issuer : Nat → F
  sr : Nat
  valid_at : Nat
  /-- main.nr 13-18 -/
  t : Nat → Nat
  sig : Nat → Nat
  exp : Nat → Nat
  hold : Nat → Nat
  csig : Nat → Nat
  salt : F
  /-- main.nr 19-22 -/
  c_is : Nat → Nat
  c_qs : Nat → Nat
  c_ip : Nat → Nat
  c_qp : Nat → Nat
  /-- main.nr 23-28 -/
  xs : Nat → Nat
  chs : Nat → Nat → Fin 4 → F
  leaf_s : F
  xp : Nat → Nat
  chp : Nat → Nat → Fin 4 → F
  leaf_p : F
  /-- main.nr 29-31 -/
  ci : Nat → F
  cq : Nat → F
  u : Nat → Bool
  /-- main.nr 35: `cb = cc.to_be_bytes()` -/
  cb : Nat → Nat
  /-- lib.nr 187-190: the issuer limbs' `to_be_bytes` -/
  a : Nat → Nat
  b : Nat → Nat
  c : Nat → Nat
  d : Nat → Nat
  /-- lib.nr 280: `back = rr.to_be_bytes()` -/
  back : Nat → Nat

/-- The Noir types of those inputs (main.nr 5-31). Noir enforces them on input. -/
structure PhoneTypes (w : Witness) : Prop where
  attempt_ok : isU8 w.attempt                    -- main.nr 7
  sr_ok : isU32 w.sr                             -- main.nr 11
  valid_at_ok : isU64 w.valid_at                 -- main.nr 12
  t_ok : bytesOK w.t                             -- main.nr 13
  exp_ok : ∀ i, i < 8 → w.exp i < 256            -- main.nr 15
  hold_ok : ∀ i, i < 32 → w.hold i < 256         -- main.nr 16
  c_is_ok : ∀ n, n < 12000 → w.c_is n < 256      -- main.nr 19
  c_qs_ok : ∀ n, n < 12000 → w.c_qs n < 256      -- main.nr 20
  c_ip_ok : ∀ n, n < 12000 → w.c_ip n < 256      -- main.nr 21
  c_qp_ok : ∀ n, n < 12000 → w.c_qp n < 256      -- main.nr 22
  xs_ok : ∀ j, j < 13312 → w.xs j < 2 ^ 16       -- main.nr 23
  xp_ok : ∀ j, j < 13312 → w.xp j < 2 ^ 16       -- main.nr 26

/-- The same inputs, as `check_signed` receives them (main.nr 36). `code` is `cb`. -/
def Witness.signedInputs (w : Witness) : Signed.Inputs where
  t := w.t
  sig := w.sig
  exp := w.exp
  hold := w.hold
  csig := w.csig
  nonce_hi := w.nonce_hi
  nonce_lo := w.nonce_lo
  attempt := w.attempt
  role_b := w.role_b
  issuer := w.issuer
  sr := w.sr
  valid_at := w.valid_at
  code := w.cb
  a := w.a
  b := w.b
  c := w.c
  d := w.d
  back := w.back

/-- `cc` of main.nr 33: `code_commitment(c_is, c_qs, c_ip, c_qp)`. -/
def cc (perm : Perm) (w : Witness) : F := code_commitment perm w.c_is w.c_qs w.c_ip w.c_qp

/-- `xs[os as u32 + i]`, the sample `self_side` reads at step `i` (line 382, with `o` from line 513). `Arrival` and `Freivalds` call this `x i`. -/
def selfWindow (w : Witness) : Nat → Nat := fun i => w.xs (asU32 (osF w.t w.leaf_s) + i)

/-- What `self_side` hands the spot check. -/
def wit (w : Witness) : Freivalds.Wit := ⟨selfWindow w, w.c_is, w.c_qs, w.ci, w.cq⟩

/-- lines 312, 331: the Poseidon2 sponge under `TAG_FS` (line 45), run on the absorbed list. Same `perm` as every other hash. -/
def fsHash (perm : Perm) : List F → F × F := fun l => (Commit.absorbAll perm (Commit.Sp.new 101897) l).finish perm

/-- line 510: `(r, rho) = fs_challenges(...)`, with `code = [cc, 0]` (main.nr 38). -/
def challenges (perm : Perm) (w : Witness) : F × F :=
  Freivalds.fs_challenges (fsHash perm) w.nonce_hi w.nonce_lo w.attempt w.role_b
    (beF w.t 177 32) (pSelfF w.t) (pPartnerF w.t) (aSelfF w.t) (aPartnerF w.t w.role_b) (cc perm w) 0 w.ci w.cq

/-- lines 530-533: the eleven values `phone_core` hashes into its output. -/
def opening (w : Witness) : HalfOpening :=
  ⟨w.nonce_hi, w.nonce_lo, (w.attempt : F), boolF w.role_b, (w.sr : F), halfF w.t, w.salt,
    beF w.t 40 16, beF w.t 56 16, beF w.t 105 16, beF w.t 121 16⟩

/-! ## The circuit -/

/-- **`phone_circuit`, with the challenge left open.** Every constraint of `phone/src/main.nr` and `phone_core`, in source order, over one
witness. Each field is the block model, unchanged. `phone_circuit` below fixes `(r, rho)` to the hash output (line 510). Leaving it open here is
what lets `phone_bad_challenges` count over all pairs.

Lines 228-299 are inside `signed`. Lines 361-369 and 405 are inside `arrival`, and lines 371 and 433 inside `spot`. `open_s` and `open_p` hold the Merkle
asserts (lines 109, 117, 128). `beF t 177 32` is `sg.rec_root` (line 279), `osF` and `opF` are lines 503 and 506, written with `sg.p_self` and `sg.a_partner`
as `check_signed` returns them (lines 292-293). -/
structure phone_circuit_at (C : Signed.Crypto) (perm : Perm) (w : Witness) (out r rho : F) : Prop where
  /-- main.nr 33-34 -/
  code_eq : cc perm w = w.code_commit
  /-- main.nr 35 -/
  code_be : Signed.IsBE 32 (cc perm w) w.cb
  /-- main.nr 36, all of `check_signed` -/
  signed : Signed.CheckSigned C w.signedInputs
  /-- line 504 -/
  os_ok : fits 10 (osF w.t w.leaf_s)
  /-- line 505 -/
  open_s : open_leaves perm w.xs w.leaf_s w.chs (beF w.t 177 32)
  /-- line 507 -/
  op_ok : fits 10 (opF w.t w.role_b w.leaf_p)
  /-- line 508 -/
  open_p : open_leaves perm w.xp w.leaf_p w.chp (beF w.t 177 32)
  /-- lines 511-522 → 361, 365, 369, 405. The target is `a_self - p_self + DELTA` (line 521). -/
  arrival : Arrival.ArrivalOK w.u (Arrival.dF (selfWindow w) w.c_is w.ci w.cq) (usumTarget w.t)
  /-- lines 511-522 → 371, 433 -/
  spot : Freivalds.freivaldsOK (wit w) r rho
  /-- line 524 → 472 -/
  partner : partnerAccepts w.xp (asU32 (opF w.t w.role_b w.leaf_p)) w.c_ip w.c_qp
  /-- line 525 -/
  wpre : fits 33 (aPartnerF w.t w.role_b - pPartnerF w.t + 7200)
  /-- line 526 -/
  wpost : fits 33 (pPartnerF w.t + 12000 - aPartnerF w.t w.role_b)
  /-- lines 528-534: the circuit's public output -/
  output : out = halfCommit (hash_n perm) (opening w)

/-- **`phone_circuit`.** `phone/src/main.nr` accepts `w` and outputs `out`. The challenge is the hash output, as at line 510. -/
def phone_circuit (C : Signed.Crypto) (perm : Perm) (w : Witness) (out : F) : Prop :=
  phone_circuit_at C perm w out (challenges perm w).1 (challenges perm w).2

/-! ## The assumptions -/

/-- The named hypotheses of `phone_sound`, other than the spot check. Each is about the exact values this witness uses. A universal version of any of
them would be false (`Commit.node_hash_not_injective`, the note in `Signed.lean`). `silence_satisfies_phone_sound` shows they can all hold at once. -/
structure SigAssumptions (C : Signed.Crypto) (Msgs : Signed.SignedSet) (w : Witness) : Prop where
  /-- ECDSA: the credential signature isn't a forgery -/
  issuer_sig : Signed.Unforgeable C Msgs (Signed.issuerX w.signedInputs) (Signed.issuerY w.signedInputs)
    (Signed.slice w.csig 0 64) (C.sha256 (Signed.credList w.signedInputs))
  /-- SHA-256: no collision with this credential among what the issuer signed -/
  issuer_hash : Signed.NoCollisionWith C Msgs (Signed.issuerX w.signedInputs) (Signed.issuerY w.signedInputs)
    (Signed.credList w.signedInputs)
  /-- ECDSA: if the issuer credentialed this key, the transcript signature isn't a forgery -/
  device_sig : Msgs (Signed.issuerX w.signedInputs) (Signed.issuerY w.signedInputs) (Signed.credList w.signedInputs) →
    Signed.Unforgeable C Msgs (Signed.ownX w.signedInputs) (Signed.ownY w.signedInputs)
      (Signed.slice w.sig 0 64) (C.sha256 (Signed.slice w.t 0 311))
  /-- SHA-256: no collision with this transcript among what that key signed -/
  device_hash : Signed.NoCollisionWith C Msgs (Signed.ownX w.signedInputs) (Signed.ownY w.signedInputs) (Signed.slice w.t 0 311)

/-- `SigAssumptions`, plus what ties the opened samples to a recording `rcd`. -/
structure Assumptions (C : Signed.Crypto) (Msgs : Signed.SignedSet) (perm : Perm) (w : Witness) (rcd : Nat → Nat) : Prop
    extends SigAssumptions C Msgs w where
  /-- `rcd` holds `u16` samples -/
  rcd_u16 : ∀ n, rcd n < 2 ^ 16
  /-- The signed `rec_root` is the root of a tree over `rcd`. NOT enforced by the circuit: this is what "the committed recording" means here. -/
  root_is_recording : beF w.t 177 32 = recRoot perm rcd
  /-- Poseidon2: no collision along the self opening's paths -/
  self_paths : BindsToRecording perm rcd w.xs w.leaf_s w.chs
  /-- Poseidon2: no collision along the partner opening's paths -/
  partner_paths : BindsToRecording perm rcd w.xp w.leaf_p w.chp

/-! ## The conclusion -/

/-- `rcd` from sample `base` on. -/
def recWindow (rcd : Nat → Nat) (base : Int) : Nat → Nat := fun i => rcd (base.toNat + i)

/-- **The literal arrival test.** `a` is the first of the 193 lags with `BAR * match >= loudness`, on window `X` and templates `c_i`, `c_q`. Before `a` the test
fails, at `a` it holds. Lags after `a` are not constrained, and neither are lags before the window. `0 >= 0` passes, so this does not mean a sound is there. -/
def FirstLoudEnough (X c_i c_q : Nat → Nat) (a : Nat) : Prop :=
  a < 193 ∧
  (∀ j, j < a → Arrival.BAR * Arrival.env2 X c_i c_q j < Arrival.bigC X c_i j) ∧
  Arrival.bigC X c_i a ≤ Arrival.BAR * Arrival.env2 X c_i c_q a

/-- **The literal partner test.** `BAR * match >= loudness`, on window `Y` and templates `c_i`, `c_q`. One lag, not "first". `0 >= 0` passes. -/
def PartnerLoudEnough (Y c_i c_q : Nat → Nat) : Prop :=
  PartnerGlue.EI Y 0 * PartnerGlue.CI c_i ≤
    PartnerGlue.BAR * (PartnerGlue.II Y 0 c_i ^ 2 + PartnerGlue.II Y 0 c_q ^ 2)

/-- The window of `rcd` that the arrival rule reads. -/
def selfRec (w : Witness) (rcd : Nat → Nat) : Nat → Nat := recWindow rcd (pSelf w.t - 96 - 31)
/-- The window of `rcd` that the partner test reads. -/
def partnerRec (w : Witness) (rcd : Nat → Nat) : Nat → Nat := recWindow rcd (aPartner w.t w.role_b - 31)

/-- What `phone_sound` concludes, field by field. -/
structure PhoneConclusion (C : Signed.Crypto) (Msgs : Signed.SignedSet) (perm : Perm) (w : Witness) (out : F) (rcd : Nat → Nat) : Prop where
  /-- The issuer signed a credential on this key. -/
  issuer_signed : Msgs (Signed.issuerX w.signedInputs) (Signed.issuerY w.signedInputs) (Signed.credList w.signedInputs)
  /-- The holder of that same key signed this exact 311-byte transcript. -/
  device_signed : Msgs (Signed.ownX w.signedInputs) (Signed.ownY w.signedInputs) (Signed.slice w.t 0 311)
  /-- Block A in true bytes: magic, role, attempt, nonce, rate 48000, delta 96, canonical root, expiry, own X differs from partner X. -/
  bytes : Signed.BlockA C w.signedInputs
  /-- The private templates hash to the public `code_commit`, and the signed code bytes are that value. -/
  code_opened : cc perm w = w.code_commit ∧ beNat w.t 279 32 = w.code_commit.val
  /-- The self samples opened are the committed recording's, from `p_self - 96 - 31` on. -/
  self_samples : 0 ≤ pSelf w.t - 96 - 31 ∧ ∀ i, i < 12254 → selfWindow w i = selfRec w rcd i
  /-- The partner samples opened are the committed recording's, from `a_partner - 31` on. -/
  partner_samples : 0 ≤ aPartner w.t w.role_b - 31 ∧
    ∀ i, i < 12062 → w.xp (asU32 (opF w.t w.role_b w.leaf_p) + i) = partnerRec w rcd i
  /-- The signed `a_self` is sample `p_self - 96 + a`, where `a` is the first lag passing the literal test, on the true correlation of the recording. -/
  arrival : ∃ a : Nat, FirstLoudEnough (selfRec w rcd) w.c_is w.c_qs a ∧ aSelf w.t = pSelf w.t - 96 + a
  /-- The signed partner lag is inside the window around the signed prediction. -/
  partner_in_window : -7200 ≤ aPartner w.t w.role_b - pPartner w.t ∧ aPartner w.t w.role_b - pPartner w.t ≤ 12000
  /-- The partner lag meets the literal test, on the recording. -/
  partner_loud : PartnerLoudEnough (partnerRec w rcd) w.c_ip w.c_qp
  /-- `half` is a true signed 32-bit integer, read from the signed bytes. -/
  half_cast : halfF w.t = (half w.t : F) ∧ -2 ^ 31 ≤ half w.t ∧ half w.t < 2 ^ 31
  /-- Role A: `half` is partner arrival minus own arrival. -/
  half_gap_A : w.role_b = false → half w.t = aPartner w.t w.role_b - aSelf w.t
  /-- Role B: `half` is own arrival minus partner arrival. -/
  half_gap_B : w.role_b = true → half w.t = aSelf w.t - aPartner w.t w.role_b
  /-- The output is the hash of nonce, attempt, role, sr, half, salt and both keys' X coordinates. It hashes no Y. -/
  out_is_hash : out = hash_n perm 8 (opening w).toList
  /-- Any other opening of the output is this one, unless it is a Poseidon2 collision. -/
  out_binds : ∀ o : HalfOpening, (hash_n perm 8 o.toList = hash_n perm 8 (opening w).toList → o.toList = (opening w).toList) →
    hash_n perm 8 o.toList = out → o = opening w

/-! ## Lining the blocks up -/

/-- `Arrival` and `PartnerGlue` keep separate copies of the constants. They are the same numbers. -/
theorem tables_agree :
    Arrival.BAR = PartnerGlue.BAR ∧
    (∀ t : Fin 31, PartnerGlue.nzt t.val = Arrival.NZT t) ∧ (∀ t : Fin 31, PartnerGlue.nzh t.val = Arrival.NZH t) := by
  refine ⟨rfl, ?_, ?_⟩ <;> decide +kernel

/-- `Arrival`'s numbers depend only on the window. -/
theorem arrival_window_congr {x x' : Nat → Nat} (h : ∀ i, i < Arrival.NS → x i = x' i) (c_i c_q : Nat → Nat) {j : Nat}
    (hj : j < Arrival.K) :
    Arrival.bigC x c_i j = Arrival.bigC x' c_i j ∧ Arrival.env2 x c_i c_q j = Arrival.env2 x' c_i c_q j := by
  have hK : Arrival.K = 193 := rfl
  have hL : Arrival.L = 12000 := rfl
  have hNS : Arrival.NS = 12254 := rfl
  have hy : ∀ m, m + 53 < Arrival.NS → Arrival.yI x m = Arrival.yI x' m := fun m hm =>
    Finset.sum_congr rfl (fun t _ => by
      have := Arrival.NZT_le t
      unfold Arrival.wI
      rw [h (m + Arrival.NZT t) (by omega)])
  have hE : Arrival.EI x j = Arrival.EI x' j :=
    Finset.sum_congr rfl (fun m hm => by
      have hm' := Finset.mem_Ico.1 hm
      rw [hy m (by omega)])
  have hc : ∀ c, Arrival.corr c x j = Arrival.corr c x' j := fun c =>
    Finset.sum_congr rfl (fun n hn => by
      unfold Arrival.wI
      rw [h (n + j + Arrival.HM) (Freivalds.window_reads n j (Finset.mem_range.1 hn) hj)])
  refine ⟨by unfold Arrival.bigC; rw [hE], by unfold Arrival.env2; rw [hc, hc]⟩

/-- `PartnerGlue`'s numbers depend only on the window. -/
theorem partner_window_congr {xp xp' : Nat → Nat} {o o' : Nat} (h : ∀ j, j < 12062 → xp (o + j) = xp' (o' + j)) :
    PartnerGlue.EI xp o = PartnerGlue.EI xp' o' ∧ ∀ c, PartnerGlue.II xp o c = PartnerGlue.II xp' o' c := by
  have hy : ∀ m, m < 12000 → PartnerGlue.yI xp o m = PartnerGlue.yI xp' o' m := fun m hm =>
    Finset.sum_congr rfl (fun t ht => by
      have := PartnerGlue.nzt_bounds t (Finset.mem_range.1 ht)
      unfold PartnerGlue.wI
      rw [h (m + PartnerGlue.nzt t) (by omega)])
  refine ⟨Finset.sum_congr rfl (fun m hm => by rw [hy m (Finset.mem_range.1 hm)]), fun c =>
    Finset.sum_congr rfl (fun m hm => ?_)⟩
  have := Finset.mem_range.1 hm
  unfold PartnerGlue.wI
  rw [h (m + 31) (by omega)]

theorem idx_eq {base : Int} (h0 : 0 ≤ base) {i idx : Nat} (h : (idx : Int) = base + i) : idx = base.toNat + i := by
  have := Int.toNat_of_nonneg h0
  omega

theorem u8_of {c : Nat → Nat} (h : ∀ n, n < 12000 → c n < 256) : ∀ n, n < Arrival.L → isU8 (c n) := fun n hn => by
  have := h n hn
  show c n < 2 ^ 8
  omega

/-! ## `phone_sound` -/

/-- The proof of `phone_sound`, from the two statements Block B gives: the opened windows are samples of `rcd`. -/
theorem phone_sound_core {C : Signed.Crypto} {Msgs : Signed.SignedSet} {perm : Perm} {w : Witness} {out r rho : F} {rcd : Nat → Nat}
    (ty : PhoneTypes w) (A : SigAssumptions C Msgs w)
    (h : phone_circuit_at C perm w out r rho) (hnf : ¬ Freivalds.Fooled (wit w) r rho)
    (wS : 0 ≤ pSelf w.t - 96 - 31 ∧ ∀ i, i < 12254 →
      asU32 (osF w.t w.leaf_s) + i < 13312 ∧
      ∃ idx : Nat, (idx : Int) = pSelf w.t - 96 - 31 + i ∧ w.xs (asU32 (osF w.t w.leaf_s) + i) = rcd idx)
    (wP : 0 ≤ aPartner w.t w.role_b - 31 ∧ ∀ i, i < 12062 →
      asU32 (opF w.t w.role_b w.leaf_p) + i < 13312 ∧
      ∃ idx : Nat, (idx : Int) = aPartner w.t w.role_b - 31 + i ∧ w.xp (asU32 (opF w.t w.role_b w.leaf_p) + i) = rcd idx) :
    PhoneConclusion C Msgs perm w out rcd := by
  have ht := ty.t_ok
  have hT : Signed.Types w.signedInputs := ⟨ty.t_ok, ty.exp_ok, ty.hold_ok, ty.sr_ok, ty.valid_at_ok⟩
  -- block A
  obtain ⟨c1, c2⟩ := Signed.chain_of_trust C w.signedInputs Msgs h.signed A.issuer_sig A.issuer_hash A.device_sig A.device_hash
  -- block H
  have hcode := (Signed.code_commit_signed w.signedInputs h.signed.bytes (cc perm w) h.code_be).1
  rw [h.code_eq] at hcode
  -- block B
  have hwS : ∀ i, i < 12254 → selfWindow w i = selfRec w rcd i := fun i hi => by
    obtain ⟨_, idx, hidx, he⟩ := wS.2 i hi
    show w.xs (asU32 (osF w.t w.leaf_s) + i) = rcd ((pSelf w.t - 96 - 31).toNat + i)
    rw [he, idx_eq wS.1 hidx]
  have hwP : ∀ i, i < 12062 → w.xp (asU32 (opF w.t w.role_b w.leaf_p) + i) = partnerRec w rcd i := fun i hi => by
    obtain ⟨_, idx, hidx, he⟩ := wP.2 i hi
    show w.xp (asU32 (opF w.t w.role_b w.leaf_p) + i) = rcd ((aPartner w.t w.role_b - 31).toNat + i)
    rw [he, idx_eq wP.1 hidx]
  -- block C, then block D
  obtain ⟨hI, hQ⟩ := Freivalds.claim_true_of_not_fooled h.spot hnf
  have hx : ∀ i, i < Arrival.NS → isU16 (selfWindow w i) := fun i hi => ty.xs_ok _ (wS.2 i hi).1
  obtain ⟨a, haK, hut, _, hbelow, hat⟩ := Arrival.self_side_arrival_sound hx (u8_of ty.c_is_ok) (u8_of ty.c_qs_ok) hI hQ h.arrival
  have hcast := PartnerGlue.signed_casts w.t false ht
  have hr := PartnerGlue.signed_ranges w.t false ht
  have ha193 : a < 193 := haK
  have hTg : usumTarget w.t = ((sod w.t + 96 : Int) : F) := by
    simp only [usumTarget, pSelfF, hcast.2.2.2.1]; push_cast; ring
  rw [hTg, ← intCast_natCast] at hut
  have hinj := intCast_inj_of_small (a := (a : Int)) (b := sod w.t + 96)
    (by rw [abs_lt]; constructor <;> omega) (by rw [abs_lt]; constructor <;> omega) hut
  have harr : aSelf w.t = pSelf w.t - 96 + a := by
    unfold PartnerGlue.pSelf
    omega
  have hcg : ∀ j, j < Arrival.K → _ := fun j hj =>
    arrival_window_congr (x := selfWindow w) (x' := selfRec w rcd) hwS w.c_is w.c_qs (j := j) hj
  have hfirst : FirstLoudEnough (selfRec w rcd) w.c_is w.c_qs a := by
    refine ⟨ha193, fun j hj => ?_, ?_⟩
    · obtain ⟨e1, e2⟩ := hcg j (lt_trans hj haK)
      rw [← e1, ← e2]
      exact hbelow j hj
    · obtain ⟨e1, e2⟩ := hcg a haK
      rw [← e1, ← e2]
      exact hat
  -- block E
  have hxp : ∀ i, i < 12062 → w.xp (asU32 (opF w.t w.role_b w.leaf_p) + i) < 2 ^ 16 := fun i hi => ty.xp_ok _ (wP.2 i hi).1
  have hloud := (PartnerGlue.partner_loud w.xp _ w.c_ip w.c_qp hxp ty.c_ip_ok ty.c_qp_ok).1 h.partner
  obtain ⟨eE, eI⟩ := partner_window_congr (xp := w.xp) (o := asU32 (opF w.t w.role_b w.leaf_p)) (xp' := partnerRec w rcd) (o' := 0)
    (fun j hj => by rw [hwP j hj, Nat.zero_add])
  rw [eE, eI, eI] at hloud
  -- block F
  have hgap := PartnerGlue.half_is_gap w.t w.role_b ht
  have hrb := PartnerGlue.signed_ranges w.t w.role_b ht
  exact
    { issuer_signed := c1
      device_signed := c2
      bytes := Signed.check_signed_sound C w.signedInputs h.signed hT
      code_opened := ⟨h.code_eq, hcode⟩
      self_samples := ⟨wS.1, hwS⟩
      partner_samples := ⟨wP.1, hwP⟩
      arrival := ⟨a, hfirst, harr⟩
      partner_in_window := PartnerGlue.partner_window w.t w.role_b ht h.wpre h.wpost
      partner_loud := hloud
      half_cast := ⟨(PartnerGlue.signed_casts w.t w.role_b ht).2.2.1, hrb.2.2.2.2.1, hrb.2.2.2.2.2.1⟩
      half_gap_A := hgap.2.1
      half_gap_B := hgap.2.2
      out_is_hash := h.output
      out_binds := fun o hcr ho => PartnerGlue.half_commit_binds (hash_n perm) o (opening w) hcr
        (ho.trans h.output) }

/-- `phone_sound`, for any challenge. The hypothesis on the challenge is `hnf`. -/
theorem phone_sound_at {C : Signed.Crypto} {Msgs : Signed.SignedSet} {perm : Perm} {w : Witness} {out r rho : F} {rcd : Nat → Nat}
    (ty : PhoneTypes w) (A : Assumptions C Msgs perm w rcd)
    (h : phone_circuit_at C perm w out r rho) (hnf : ¬ Freivalds.Fooled (wit w) r rho) :
    PhoneConclusion C Msgs perm w out rcd := by
  have hs := h.open_s
  have hp := h.open_p
  rw [A.root_is_recording] at hs hp
  obtain ⟨wS, wP⟩ := Commit.phone_core_windows_are_recording perm w.t w.role_b w.leaf_s w.leaf_p w.xs w.xp rcd w.chs w.chp ty.t_ok
    ty.xs_ok ty.xp_ok A.rcd_u16 h.os_ok h.op_ok hs hp A.self_paths A.partner_paths
  exact phone_sound_core ty A.toSigAssumptions h hnf wS wP

/-- **What one accepted `phone` proof means.** Suppose `phone/src/main.nr` accepts this witness, with its output `out`, and these assumptions hold:

* no forged signature and no SHA-256 collision, on the two signatures this witness uses;
* the signed `rec_root` is the root of a tree over a recording `rcd`, and no Poseidon2 collision along the opened paths;
* the hash's challenge is not one of the few pairs that fool the spot check (`hspot`, see the top of this file, and `phone_bad_challenges` for how few).

Then, in true integers and true bytes:

1. a key the issuer signed a credential for signed this exact transcript. Nonce, attempt, role, sr, `rec_root`, `a_self`, `p_self`, `a_partner`, `p_partner`, `half` and both X coordinates are read from those signed bytes.
   `salt` is not: it is a free private input (main.nr line 18), so changing it keeps the signature and changes `out`;
2. the samples opened are the recording's, at the offset computed from the signed numbers. That place may be past the end of the real capture, where the tree holds silence padding (`Commit.past_capture_witness`, shown for the partner window);
3. the signed `a_self` is the first of 193 lags where `BAR * match >= loudness` on that recording, using the true correlation, not the prover's claim;
4. the partner lag meets `BAR * match >= loudness`, within -7200..+12000 samples of the signed prediction;
5. `half` is the signed gap between those two lags;
6. `out` hashes nonce, attempt, role, sr, half, salt and both keys' X coordinates, and can't be opened any other way short of a Poseidon2 collision. It hashes no Y.

**What this does NOT say.** "Loud enough" is the literal integer test, and it includes `0 >= 0`. So this does NOT say a beep was heard. A silent recording meets all six
(`silence_satisfies_phone_sound`), and sound above zero loudness isn't a beep either: a clean 500 Hz tone in a file solved the real circuit (`circuit-cases` d, 6/6, not a theorem here). It says nothing about where the phone was, or that the recording came from a mic. A device key can sign anything, and on its own
"signed" says who signed, not that it's true. The issuer and `code_commit` are whatever the public inputs name, so a verifier has to pin both: with an all-128 `c_i`, loudness is 0 and the test passes on any audio. `p_self` is a number the signer chose, so "first of 193 lags" in 3 is
first inside a window the signer places. `circuit-cases` c puts the arrival at lag 50 with a one-sample click. `p_partner` is also the signer's number, so the window in 4
narrows nothing against a dishonest signer. And 4 isn't "first": any passing lag in the window will do. The partner key's Y isn't read, see the top of this file. -/
theorem phone_sound {C : Signed.Crypto} {Msgs : Signed.SignedSet} {perm : Perm} {w : Witness} {out : F} {rcd : Nat → Nat}
    (ty : PhoneTypes w) (A : Assumptions C Msgs perm w rcd)
    (h : phone_circuit C perm w out)
    (hspot : ¬ Freivalds.Fooled (wit w) (challenges perm w).1 (challenges perm w).2) :
    PhoneConclusion C Msgs perm w out rcd :=
  phone_sound_at ty A h hspot

/-- **`phone_sound` without assuming an honest tree.** `Assumptions.root_is_recording` isn't enforced by the circuit. Drop it. If Poseidon2 has no collision on the paths the two openings share (`Commit.OpeningsBind`), there is still ONE recording of `u16` samples that
both windows read, and all of `phone_sound`'s conclusion holds of it. The price: that recording is only defined where the windows look, and filler elsewhere. It need not be what any tree under `rec_root` holds, and it need not be anything the phone captured.
The warning on `phone_sound` applies in full. -/
theorem phone_sound_no_tree {C : Signed.Crypto} {Msgs : Signed.SignedSet} {perm : Perm} {w : Witness} {out : F}
    (ty : PhoneTypes w) (A : SigAssumptions C Msgs w)
    (h : phone_circuit C perm w out)
    (hspot : ¬ Freivalds.Fooled (wit w) (challenges perm w).1 (challenges perm w).2)
    (hb : Commit.OpeningsBind perm w.xs w.leaf_s w.chs w.xp w.leaf_p w.chp) :
    ∃ rcd : Nat → Nat, (∀ n, rcd n < 2 ^ 16) ∧ PhoneConclusion C Msgs perm w out rcd := by
  obtain ⟨rcd, hu, wS, wP⟩ := Commit.phone_core_one_recording perm w.t w.role_b w.leaf_s w.leaf_p (beF w.t 177 32) w.xs w.xp w.chs w.chp ty.t_ok
    ty.xs_ok ty.xp_ok h.os_ok h.op_ok h.open_s h.open_p hb
  exact ⟨rcd, hu, phone_sound_core ty A h hspot wS wP⟩

/-- **The values are the signed bytes.** Two transcripts with the same signed 311 bytes have the same `a_self`, `p_self`, `p_partner`, `half`, `a_partner`, and the same root and key X coordinates.
So "these values" in `phone_sound` really are what the signature covers. -/
theorem values_are_signed_bytes (t t' : Nat → Nat) (role_b : Bool) (h : Signed.slice t 0 311 = Signed.slice t' 0 311) :
    aSelf t = aSelf t' ∧ pSelf t = pSelf t' ∧ pPartner t = pPartner t' ∧ half t = half t' ∧
    aPartner t role_b = aPartner t' role_b ∧
    beF t 177 32 = beF t' 177 32 ∧ beF t 40 16 = beF t' 40 16 ∧ beF t 56 16 = beF t' 56 16 ∧
    beF t 105 16 = beF t' 105 16 ∧ beF t 121 16 = beF t' 121 16 := by
  have hb : ∀ i, i < 311 → t i = t' i := fun i hi => by
    have := List.map_inj_left.1 h i (List.mem_range.2 hi)
    simpa using this
  have nat : ∀ off n, off + n ≤ 311 → beNat t off n = beNat t' off n := fun off n hn =>
    Signed.beNat_congr _ _ _ _ _ (fun i hi => hb _ (by omega))
  have fld : ∀ off n, off + n ≤ 311 → beF t off n = beF t' off n := fun off n hn =>
    Signed.beF_congr _ _ _ _ (fun i hi => hb _ (by omega))
  have sgn : ∀ off, off + 4 ≤ 311 → PartnerGlue.signedInt t off = PartnerGlue.signedInt t' off := fun off hoff => by
    unfold PartnerGlue.signedInt
    rw [hb off (by omega), nat off 4 hoff]
  have e1 : aSelf t = aSelf t' := by unfold PartnerGlue.aSelf; rw [nat 269 4 (by norm_num)]
  have e2 : sod t = sod t' := sgn 233 (by norm_num)
  have e3 : half t = half t' := sgn 173 (by norm_num)
  refine ⟨e1, by unfold PartnerGlue.pSelf; rw [e1, e2], by unfold PartnerGlue.pPartner; rw [nat 273 4 (by norm_num)], e3,
    by unfold PartnerGlue.aPartner; rw [e1, e3], fld _ _ (by norm_num), fld _ _ (by norm_num), fld _ _ (by norm_num),
    fld _ _ (by norm_num), fld _ _ (by norm_num)⟩

/-! ## Block C as a count, not an assumption -/

section Count

set_option linter.concreteInstances false

-- Keep Lean from computing with the 254-bit literal when it compares instances on `ZMod p`, as `Freivalds.lean` does.
attribute [local irreducible] Popfv.p

open scoped Classical in
/-- **How few challenges can go wrong.** Fix the witness, and everything else about it. Of all `p²` possible pairs `(r, rho)`, at most `193 p` make the circuit accept while the conclusion
of `phone_sound` is false. So this count drops the hypothesis "the curve is the true one", and puts "the challenge missed these pairs" in its place. The types and every entry of `Assumptions` (signatures, SHA-256, tree, paths) are still hypotheses.

This is a plain count over a witness fixed in advance. That the real challenge misses the pairs isn't proved, and takes two assumptions. One, the random-oracle assumption, because `r, rho` come out of Poseidon2. `Freivalds.rom_union_bound` covers a fixed list of tries,
not an adaptive attacker. Two, the witness has to be fixed before the challenge. The hash absorbs `cc` and `rec_root`, not the templates or samples, so that needs Poseidon2 binding of `code_commitment` and the tree. `Commit.CodeBinds` is not among these hypotheses: with a
code collision, `c_is` can change after `(r, rho)` is known, with the hash input unchanged. `phone_sound` is unaffected, because `hspot` is stated on the final witness.

The primality of `p` is a hypothesis here, never proved in this repo. And the conclusion is still only the literal test: see the warning on `phone_sound`. -/
theorem phone_bad_challenges [Fact (Nat.Prime p)] {C : Signed.Crypto} {Msgs : Signed.SignedSet} {perm : Perm} {w : Witness} {out : F} {rcd : Nat → Nat}
    (ty : PhoneTypes w) (A : Assumptions C Msgs perm w rcd) :
    (Finset.univ.filter fun z : F × F =>
      phone_circuit_at C perm w out z.1 z.2 ∧ ¬ PhoneConclusion C Msgs perm w out rcd).card ≤ 193 * p := by
  refine le_trans (Freivalds.card_filter_mono (Q := fun z : F × F => Freivalds.Fooled (wit w) z.1 z.2) (fun z hz => ?_))
    (Freivalds.fooled_count (wit w))
  by_contra hnf
  exact hz.2 (phone_sound_at ty A hz.1 hnf)

open scoped Classical in
/-- **The same count, as odds.** Over a uniformly chosen pair, accepting with a false conclusion has odds at most `193 / p`, below `2^-246` (`Freivalds.odds_numeric`). "Uniformly" is the
random-oracle assumption, and the witness must be fixed before the challenge. See `phone_bad_challenges` for both limits. -/
theorem phone_bad_odds [Fact (Nat.Prime p)] {C : Signed.Crypto} {Msgs : Signed.SignedSet} {perm : Perm} {w : Witness} {out : F} {rcd : Nat → Nat}
    (ty : PhoneTypes w) (A : Assumptions C Msgs perm w rcd) :
    ((Finset.univ.filter fun z : F × F =>
      phone_circuit_at C perm w out z.1 z.2 ∧ ¬ PhoneConclusion C Msgs perm w out rcd).card : ℚ) /
      (Fintype.card (F × F) : ℚ) ≤ 193 / (p : ℚ) :=
  Freivalds.odds_zmod _ (phone_bad_challenges ty A)

end Count

/-! ## `presence_sound` -/

/-- lines 21, 23 of `pair/src/main.nr`, A's opening. The role is the literal `0`. -/
def pairListA (nonce_hi nonce_lo : F) (attempt sr_a : Nat) (half_a salt_a xa0 xa1 xb0 xb1 : F) : List F :=
  [nonce_hi, nonce_lo, (attempt : F), 0, (sr_a : F), half_a, salt_a, xa0, xa1, xb0, xb1]

/-- B's opening. The role is the literal `1`, and the X coordinates are the other way round. -/
def pairListB (nonce_hi nonce_lo : F) (attempt sr_b : Nat) (half_b salt_b xa0 xa1 xb0 xb1 : F) : List F :=
  [nonce_hi, nonce_lo, (attempt : F), 1, (sr_b : F), half_b, salt_b, xb0, xb1, xa0, xa1]

/-- Named hypothesis: Poseidon2 has no collision between exactly these two inputs. Each tag has one fixed length, so this compares like with like.
Given that both circuits accepted, the hashes are equal, so this is the same as saying the two lists are equal. As with `hspot`, its worth is in being a named collision claim, not a result. -/
def HalfBinds (perm : Perm) (l l' : List F) : Prop := hash_n perm 8 l = hash_n perm 8 l' → l = l'

/-- The flight number `pair` tests, in cm, as a plain rational: `c/2 * (hA/srA - hB/srB)`, with `c = 34300`. -/
def flight (hA hB : Int) (sr_a sr_b : Nat) : ℚ := (34300 / 2) * ((hA : ℚ) / sr_a - (hB : ℚ) / sr_b)

/-- What `presence_sound` concludes. -/
structure PresenceConclusion (C : Signed.Crypto) (Msgs : Signed.SignedSet) (perm : Perm) (wA wB : Witness) (commit_a commit_b : F)
    (rcdA rcdB : Nat → Nat) (nonce_hi nonce_lo : F) (attempt sr_a sr_b : Nat) (half_a salt_a half_b salt_b xa0 xa1 xb0 xb1 : F) : Prop where
  /-- Everything `phone_sound` says, for each phone. -/
  phone_A : PhoneConclusion C Msgs perm wA commit_a rcdA
  phone_B : PhoneConclusion C Msgs perm wB commit_b rcdB
  /-- `commit_a` came from a role A phone, `commit_b` from a role B phone. -/
  role_A : wA.role_b = false
  role_B : wB.role_b = true
  /-- Both phones and `pair` are in one session. -/
  nonce_A : nonce_hi = wA.nonce_hi ∧ nonce_lo = wA.nonce_lo ∧ attempt = wA.attempt
  nonce_B : nonce_hi = wB.nonce_hi ∧ nonce_lo = wB.nonce_lo ∧ attempt = wB.attempt
  /-- The halves `pair` opens are the ones each device signed. -/
  half_A : half_a = (half wA.t : F)
  half_B : half_b = (half wB.t : F)
  salt_A : salt_a = wA.salt
  salt_B : salt_b = wB.salt
  /-- The rates `pair` uses are the signed ones, and `phone` forces 48000. -/
  rate_A : sr_a = wA.sr ∧ sr_a = 48000
  rate_B : sr_b = wB.sr ∧ sr_b = 48000
  /-- X coordinates only. `xa` is A's own X, and B names it as partner X. `xb` is B's own X, and A names it as partner X. The two X values differ.
  Nothing here relates any Y: a phone's partner Y (bytes 137-168) is never read, so it need not be the other phone's own Y. -/
  own_A : xa0 = beF wA.t 40 16 ∧ xa1 = beF wA.t 56 16
  partner_A : xb0 = beF wA.t 105 16 ∧ xb1 = beF wA.t 121 16
  own_B : xb0 = beF wB.t 40 16 ∧ xb1 = beF wB.t 56 16
  partner_B : xa0 = beF wB.t 105 16 ∧ xa1 = beF wB.t 121 16
  keys_differ : (xa0, xa1) ≠ (xb0, xb1)
  /-- `-20 < flight < 60`, in plain arithmetic, with no wraparound, on the signed halves. Both ends strict. -/
  flight_lo : (-20 : ℚ) < flight (half wA.t) (half wB.t) sr_a sr_b
  flight_hi : flight (half wA.t) (half wB.t) sr_a sr_b < 60
  /-- With both rates forced, that number is `17150 * (hA - hB) / 48000`. -/
  flight_plain : flight (half wA.t) (half wB.t) sr_a sr_b = 17150 * (((half wA.t : Int) : ℚ) - ((half wB.t : Int) : ℚ)) / 48000

theorem boolF_true : boolF true = 1 := by simp [boolF]
theorem boolF_false : boolF false = 0 := by simp [boolF]

/-- **What two `phone` proofs and one `pair` proof mean together.** Suppose `phone` accepts for two witnesses with outputs `commit_a`, `commit_b`, and `pair` accepts those two commitments. Add the assumptions of `phone_sound`
for each phone, and that Poseidon2 has no collision between each phone's output and `pair`'s opening of it (`HalfBinds`). Then both halves are the ones each device signed, the keys' X coordinates are crossed (each phone names the other's X as partner X, and Y isn't crossed), both are in one session
with the right roles, and `-20 < flight < 60` in plain arithmetic, where flight is `c/2 * (hA/srA - hB/srB)` on the signed integers. The role, nonce, attempt and rate of each phone follow from `HalfBinds`, which, once both circuits accept, says exactly that the two lists are equal. So they rest on that collision assumption.

A verifier has to do its part: it must check that `commit_a`, `commit_b` are those two phones' public outputs (here, the same variables), and it must pin each phone's `issuer` and `code_commit`. Nothing here ties the two phones' issuers or code commits to each other.

**What this does NOT say.** "-20 < flight < 60" is arithmetic on two numbers the devices signed. It says nothing about where the phones really were. "Loud enough" includes `0 >= 0`, so this does NOT say a beep was heard: two silent recordings with chosen halves
satisfy every hypothesis and every conclusion, at flight 0 cm (`silence_satisfies_presence_sound`, and `circuit-cases` e1 runs that shape through the real compiled circuit). On such a recording a dishonest signer picks `half`, limited only by the range checks on the offsets and leaves. A phone's partner key is only a name it signed. Its own proof checks no
credential for it. The crossing of X holds because each phone's own proof also covers the other's X as its own. A's partner Y is never read, so it can differ from B's own Y, and by reading `pair` still accepts, since it never sees Y (`Signed.junk_accepted` has junk partner Y with a willing signer, and no theorem states the `pair` step), while the server compares whole
public keys (`server/pop/verdict.py:159`). -/
theorem presence_sound {C : Signed.Crypto} {Msgs : Signed.SignedSet} {perm : Perm} {wA wB : Witness} {commit_a commit_b : F} {rcdA rcdB : Nat → Nat}
    {nonce_hi nonce_lo : F} {attempt sr_a sr_b : Nat} {half_a salt_a half_b salt_b xa0 xa1 xb0 xb1 : F}
    (tyA : PhoneTypes wA) (tyB : PhoneTypes wB)
    (hat : isU8 attempt) (hsa : isU32 sr_a) (hsb : isU32 sr_b)
    (AA : Assumptions C Msgs perm wA rcdA) (AB : Assumptions C Msgs perm wB rcdB)
    (hA : phone_circuit C perm wA commit_a) (hB : phone_circuit C perm wB commit_b)
    (spotA : ¬ Freivalds.Fooled (wit wA) (challenges perm wA).1 (challenges perm wA).2)
    (spotB : ¬ Freivalds.Fooled (wit wB) (challenges perm wB).1 (challenges perm wB).2)
    (hP : pairCircuit (hash_n perm) nonce_hi nonce_lo attempt commit_a commit_b sr_a sr_b half_a salt_a half_b salt_b xa0 xa1 xb0 xb1)
    (bindA : HalfBinds perm (opening wA).toList (pairListA nonce_hi nonce_lo attempt sr_a half_a salt_a xa0 xa1 xb0 xb1))
    (bindB : HalfBinds perm (opening wB).toList (pairListB nonce_hi nonce_lo attempt sr_b half_b salt_b xa0 xa1 xb0 xb1)) :
    PresenceConclusion C Msgs perm wA wB commit_a commit_b rcdA rcdB nonce_hi nonce_lo attempt sr_a sr_b half_a salt_a half_b salt_b xa0 xa1 xb0 xb1 := by
  have pA := phone_sound tyA AA hA spotA
  have pB := phone_sound tyB AB hB spotB
  obtain ⟨hA', hB', ⟨a1, a2⟩, ⟨b1, b2⟩, ea, eb, _, _, hx, lo, hi⟩ := pair_sound (hash_n perm) nonce_hi nonce_lo attempt commit_a commit_b sr_a sr_b
    half_a salt_a half_b salt_b xa0 xa1 xb0 xb1 hat hsa hsb hP
  obtain ⟨hca, hcb, _⟩ := hP
  have hca' : hash_n perm 8 (pairListA nonce_hi nonce_lo attempt sr_a half_a salt_a xa0 xa1 xb0 xb1) = commit_a := hca
  have hcb' : hash_n perm 8 (pairListB nonce_hi nonce_lo attempt sr_b half_b salt_b xa0 xa1 xb0 xb1) = commit_b := hcb
  have eA := bindA (pA.out_is_hash.symm.trans hca'.symm)
  have eB := bindB (pB.out_is_hash.symm.trans hcb'.symm)
  simp only [opening, HalfOpening.toList, pairListA, List.cons.injEq, and_true] at eA
  simp only [opening, HalfOpening.toList, pairListB, List.cons.injEq, and_true] at eB
  obtain ⟨n1, n2, at1, r1, s1, h1, sl1, k1, k2, k3, k4⟩ := eA
  obtain ⟨n1', n2', at2, r2, s2, h2, sl2, k1', k2', k3', k4'⟩ := eB
  have rA : wA.role_b = false := by
    cases hr : wA.role_b with
    | false => rfl
    | true =>
      rw [hr, boolF_true] at r1
      exact absurd r1.symm Freivalds.F_zero_ne_one
  have rB : wB.role_b = true := by
    cases hr : wB.role_b with
    | true => rfl
    | false =>
      rw [hr, boolF_false] at r2
      exact absurd r2 Freivalds.F_zero_ne_one
  have atA : attempt = wA.attempt := (Commit.natCast_inj_of_lt (isU8_lt_p tyA.attempt_ok) (isU8_lt_p hat) at1).symm
  have atB : attempt = wB.attempt := (Commit.natCast_inj_of_lt (isU8_lt_p tyB.attempt_ok) (isU8_lt_p hat) at2).symm
  have srA : sr_a = wA.sr := (Commit.natCast_inj_of_lt (isU32_lt_p tyA.sr_ok) (isU32_lt_p hsa) s1).symm
  have srB : sr_b = wB.sr := (Commit.natCast_inj_of_lt (isU32_lt_p tyB.sr_ok) (isU32_lt_p hsb) s2).symm
  have sA48 : sr_a = 48000 := srA.trans pA.bytes.sr.1
  have sB48 : sr_b = 48000 := srB.trans pB.bytes.sr.1
  obtain ⟨cA, rA1, rA2⟩ := pA.half_cast
  obtain ⟨cB, rB1, rB2⟩ := pB.half_cast
  have iA : half wA.t = hA' := intCast_inj_of_small (by rw [abs_lt]; constructor <;> omega) (by rw [abs_lt]; constructor <;> omega)
    (cA.symm.trans (h1.trans ea))
  have iB : half wB.t = hB' := intCast_inj_of_small (by rw [abs_lt]; constructor <;> omega) (by rw [abs_lt]; constructor <;> omega)
    (cB.symm.trans (h2.trans eb))
  subst iA iB
  exact
    { phone_A := pA
      phone_B := pB
      role_A := rA
      role_B := rB
      nonce_A := ⟨n1.symm, n2.symm, atA⟩
      nonce_B := ⟨n1'.symm, n2'.symm, atB⟩
      half_A := ea
      half_B := eb
      salt_A := sl1.symm
      salt_B := sl2.symm
      rate_A := ⟨srA, sA48⟩
      rate_B := ⟨srB, sB48⟩
      own_A := ⟨k1.symm, k2.symm⟩
      partner_A := ⟨k3.symm, k4.symm⟩
      own_B := ⟨k1'.symm, k2'.symm⟩
      partner_B := ⟨k3'.symm, k4'.symm⟩
      keys_differ := hx
      flight_lo := lo
      flight_hi := hi
      flight_plain := by
        unfold flight
        rw [sA48, sB48]
        push_cast
        ring }

/-! ## So the theorems can't be misread: silence

Everything from here on is about the known silence gap (`fv/v1/docs/05-spike-results.md` finding 1, `circuit-cases` b and e1).

`silent_recording_passes_the_tests` needs no toy: any silent window meets the literal tests, for any templates. `silence_satisfies_phone_sound` and
`silence_satisfies_presence_sound` go further. Their proofs build the whole witness and use it for the hypotheses of `phone_sound` and `presence_sound`, so those hypotheses aren't contradictory. `silence_satisfies_phone_sound` lists them all in its statement. `silence_satisfies_presence_sound` lists only part: see its docstring. Limit: every chain-level witness here uses silent audio, so nothing at this level shows the model accepts real audio, or exercises an arrival lag above 0.

The witness has the shape of `circuit-cases` e1, in `cases.py` `silent_phone`: all samples silent, `p_self = 24000`, `a_self = p_self - 96`, `a_partner = a_self ± half`, `p_partner = a_partner - 100`, one chosen `half` on both phones.
Two things are toys, because Poseidon2, SHA-256 and ECDSA are opaque here. The permutation always answers 1, and a signature verifies exactly when the toy signing history holds that message. So this shows the hypotheses are consistent.
It says nothing about real Poseidon2 or real ECDSA, and nobody here holds a real issuer's credential. `circuit-cases` b and e1 run this shape through the real compiled circuit, with real hashes and throwaway keys, and no proof made. -/

/-- **A silent window passes both literal tests, with no assumption.** For any templates, at any place in a silent recording: lag 0 is the "first loud enough lag", with loudness 0 and match 0, and the partner test holds
with loudness 0 and match 0. This is `0 >= 0`. So `FirstLoudEnough` and `PartnerLoudEnough`, and with them `phone_sound`'s audio clauses, do NOT mean a sound is there. -/
theorem silent_recording_passes_the_tests (base base' : Int) (c_i c_q c_i' c_q' : Nat → Nat) :
    FirstLoudEnough (recWindow Arrival.silent base) c_i c_q 0 ∧
    Arrival.bigC (recWindow Arrival.silent base) c_i 0 = 0 ∧ Arrival.env2 (recWindow Arrival.silent base) c_i c_q 0 = 0 ∧
    PartnerLoudEnough (recWindow Arrival.silent base') c_i' c_q' ∧
    PartnerGlue.EI (recWindow Arrival.silent base') 0 = 0 ∧
    PartnerGlue.II (recWindow Arrival.silent base') 0 c_i' = 0 ∧ PartnerGlue.II (recWindow Arrival.silent base') 0 c_q' = 0 := by
  have hX : recWindow Arrival.silent base = Arrival.silent := rfl
  have hcorr : ∀ c, Arrival.corr c Arrival.silent 0 = 0 := fun c =>
    Finset.sum_eq_zero (fun n _ => by rw [Arrival.wI_silent, mul_zero])
  have hy : ∀ m, Arrival.yI Arrival.silent m = 0 := fun m =>
    Finset.sum_eq_zero (fun t _ => by rw [Arrival.wI_silent, mul_zero])
  have hE : Arrival.EI Arrival.silent 0 = 0 := Finset.sum_eq_zero (fun m _ => by rw [hy]; norm_num)
  have hb : Arrival.bigC Arrival.silent c_i 0 = 0 := by simp [Arrival.bigC, hE]
  have he : Arrival.env2 Arrival.silent c_i c_q 0 = 0 := by simp [Arrival.env2, hcorr]
  have hw : ∀ j, PartnerGlue.wI (recWindow Arrival.silent base') 0 j = 0 := fun j => by
    simp [PartnerGlue.wI, recWindow, Arrival.silent]
  have hpy : ∀ m, PartnerGlue.yI (recWindow Arrival.silent base') 0 m = 0 := fun m =>
    Finset.sum_eq_zero (fun t _ => by rw [hw, mul_zero])
  have hpE : PartnerGlue.EI (recWindow Arrival.silent base') 0 = 0 := Finset.sum_eq_zero (fun m _ => by rw [hpy]; norm_num)
  have hpI : ∀ c, PartnerGlue.II (recWindow Arrival.silent base') 0 c = 0 := fun c =>
    Finset.sum_eq_zero (fun m _ => by rw [hw, mul_zero])
  rw [hX]
  refine ⟨⟨by norm_num, fun j hj => absurd hj (Nat.not_lt_zero j), by rw [hb, he]; norm_num⟩, hb, he, ?_, hpE, hpI _, hpI _⟩
  unfold PartnerLoudEnough
  rw [hpE, hpI, hpI]
  norm_num

/-- **The rule still has teeth on silence.** "First" is enforced: on a silent window the only first lag is 0. So a silent phone can't place its own arrival by flags. It has to pick `p_self`, which the circuit doesn't check, as `a_self + 96`. `half` isn't tied this way at all. -/
theorem silence_forces_lag_zero (base : Int) (c_i c_q : Nat → Nat) (a : Nat)
    (h : FirstLoudEnough (recWindow Arrival.silent base) c_i c_q a) : a = 0 := by
  by_contra hne
  have h0 := h.2.1 0 (by omega)
  obtain ⟨_, hb, he, _⟩ := silent_recording_passes_the_tests base base c_i c_q c_i c_q
  rw [hb, he] at h0
  norm_num at h0

/-- **The test as a score, for any positive `g`, and what happens at loudness 0.** When loudness is above zero, the literal test is exactly `score >= g / sqrt BAR`, for ANY `g > 0`. The theorem doesn't fix `g`. At `g = 1` the bar is about 0.00047.
The bar is 0.09, up to rounding, only for a `g` with `round(g^2 / 0.09^2) = 4474747`, roughly 190 (`Bar.T0eff_48k`). This theorem doesn't assume that.
And `g` is just a number we pick. It isn't the gain the audio really gets through the filter, which depends on the sound: about 0.14 at 500 Hz. So passing does not mean the code is present.
Silence isn't the only exception, then. Loudness above zero doesn't mean a beep: a clean 500 Hz tone solved the real circuit (`circuit-cases` d, 6/6, in a file, no room test), and this theorem says nothing about that case.
At loudness 0 the score is `0/0`, which Lean's convention makes 0, so the score does not reach the bar for any positive `g`, and yet the circuit's test passes. So a score bar is NOT what `phone_sound` proves at a silent lag. -/
theorem loud_enough_vs_score (g : ℝ) (hg : 0 < g) (X c_i c_q : Nat → Nat) (j : Nat) (hL : 0 < Arrival.bigC X c_i j) :
    (Arrival.bigC X c_i j ≤ Arrival.BAR * Arrival.env2 X c_i c_q j ↔
      T0eff (4474747 : ℤ) g ≤ g * Real.sqrt ((Arrival.env2 X c_i c_q j : ℝ) / (Arrival.bigC X c_i j : ℝ))) ∧
    ((0 : ℤ) ≤ Arrival.BAR * 0 ∧ ¬ (T0eff (4474747 : ℤ) g ≤ g * Real.sqrt ((0 : ℝ) / 0))) := by
  refine ⟨bar_iff_score _ _ 4474747 g hg (by unfold Arrival.env2; positivity) hL (by norm_num), by norm_num [Arrival.BAR], ?_⟩
  have hpos : 0 < T0eff (4474747 : ℤ) g := by
    unfold T0eff
    have : (0 : ℝ) < ((4474747 : ℤ) : ℝ) := by norm_num
    positivity
  simp only [div_zero, Real.sqrt_zero, mul_zero]
  linarith

namespace Silence

/-! ### A toy permutation -/

/-- The toy permutation. It always answers 1, so `r = rho = 1`, which has an inverse, as line 371 needs. -/
def permOne : Perm := fun _ _ => 1

theorem absorb_inv (sp : Commit.Sp) (x : F) :
    (Commit.Sp.absorb permOne sp x).pos = 0 → (Commit.Sp.absorb permOne sp x).s = fun _ => 1 := by
  unfold Commit.Sp.absorb
  dsimp only
  split
  · intro _; rfl
  · intro h; exact absurd h (Nat.succ_ne_zero _)

theorem absorbAll_inv : ∀ (l : List F) (sp : Commit.Sp), l ≠ [] →
    (Commit.absorbAll permOne sp l).pos = 0 → (Commit.absorbAll permOne sp l).s = fun _ => 1
  | [], _, h => absurd rfl h
  | [x], sp, _ => absorb_inv sp x
  | x :: y :: r, sp, _ => absorbAll_inv (y :: r) (Commit.Sp.absorb permOne sp x) (by simp)

theorem finish_one (sp : Commit.Sp) (h : sp.pos = 0 → sp.s = fun _ => 1) : sp.finish permOne = (1, 1) := by
  simp only [Commit.Sp.finish]
  split_ifs with hp
  · rfl
  · rw [h (not_not.1 hp)]

theorem fsHash_one {l : List F} (h : l ≠ []) : fsHash permOne l = (1, 1) := finish_one _ (absorbAll_inv l _ h)

theorem hash_one {tag : F} {l : List F} (h : l ≠ []) : hash_n permOne tag l = 1 := by
  unfold hash_n
  rw [finish_one _ (absorbAll_inv l _ h)]

theorem root_one (rcd : Nat → Nat) : recRoot permOne rcd = 1 := hash_one (by simp)

theorem cc_one (a b c d : Nat → Nat) : code_commitment permOne a b c d = 1 := by
  rw [Commit.code_commitment_eq]
  refine hash_one (fun hn => ?_)
  have := congrArg List.length hn
  simp [Commit.chunks_length] at this

/-! ### The transcript -/

/-- The nonzero bytes of the transcript, role A or B, with the layout in `Signed.lean`: `a_self = 23904`, `sod = -96`, so `p_self = 24000`, and `half = 10000`, so `a_partner` is 33904 for A and 13904 for B, and `p_partner` is 100 less.
Own X and partner X are crossed. The root and the code commit are 1, what `permOne` gives. Nonce and attempt are 0. Same shape as `silent_phone` in `circuit-cases/cases.py`. -/
def tbl (b : Bool) : List (Nat × Nat) :=
  [(0, 0x50), (1, 0x4f), (2, 0x50), (3, 0x54), (4, 2), (5, if b then 0x42 else 0x41), (39, 4), (40, if b then 2 else 1), (104, 4),
    (105, if b then 1 else 2), (171, 0xBB), (172, 0x80), (175, 0x27), (176, 0x10), (208, 1), (233, 0xFF), (234, 0xFF), (235, 0xFF),
    (236, 0xA0), (271, 0x5D), (272, 0x60), (275, if b then 0x35 else 0x84), (276, if b then 0xEC else 0x0C), (278, 96), (310, 1)]

/-- The transcript. -/
def silT (b : Bool) (i : Nat) : Nat := ((tbl b).lookup i).getD 0

/-- First partner leaf: `a_partner - 31 = 1024 * lp + op`. -/
def lpOf (b : Bool) : Nat := if b then 13 else 33

theorem silT_bytes (b : Bool) : bytesOK (silT b) := by
  cases b <;> (unfold PartnerGlue.bytesOK; decide +kernel)

theorem silT_values : ∀ b : Bool, aSelf (silT b) = 23904 ∧ half (silT b) = 10000 ∧ sod (silT b) = -96 ∧
    pPartner (silT b) = (if b then 13804 else 33804) ∧ beNat (silT b) 177 32 = 1 ∧ beNat (silT b) 279 32 = 1 := by
  decide +kernel

theorem silT_pSelf (b : Bool) : pSelf (silT b) = 24000 := by
  obtain ⟨h1, _, h3, _⟩ := silT_values b
  unfold PartnerGlue.pSelf
  omega

theorem silT_aPartner (b : Bool) : aPartner (silT b) b = if b then 13904 else 33904 := by
  obtain ⟨h1, h2, _⟩ := silT_values b
  unfold PartnerGlue.aPartner PartnerGlue.sg
  cases b <;> simp [h1, h2]

theorem silT_root (b : Bool) : beF (silT b) 177 32 = recRoot permOne Arrival.silent := by
  rw [root_one, PartnerGlue.beF_eq, (silT_values b).2.2.2.2.1]
  exact Nat.cast_one

theorem silT_halfF (b : Bool) : halfF (silT b) = ((10000 : Int) : F) := by
  rw [(PartnerGlue.signed_casts (silT b) b (silT_bytes b)).2.2.1, (silT_values b).2.1]

theorem keys_cross_0 : beF (silT false) 105 16 = beF (silT true) 40 16 := by
  rw [PartnerGlue.beF_eq, PartnerGlue.beF_eq, show beNat (silT false) 105 16 = beNat (silT true) 40 16 by decide +kernel]
theorem keys_cross_1 : beF (silT false) 121 16 = beF (silT true) 56 16 := by
  rw [PartnerGlue.beF_eq, PartnerGlue.beF_eq, show beNat (silT false) 121 16 = beNat (silT true) 56 16 by decide +kernel]
theorem keys_cross_2 : beF (silT true) 105 16 = beF (silT false) 40 16 := by
  rw [PartnerGlue.beF_eq, PartnerGlue.beF_eq, show beNat (silT true) 105 16 = beNat (silT false) 40 16 by decide +kernel]
theorem keys_cross_3 : beF (silT true) 121 16 = beF (silT false) 56 16 := by
  rw [PartnerGlue.beF_eq, PartnerGlue.beF_eq, show beNat (silT true) 121 16 = beNat (silT false) 56 16 by decide +kernel]

/-- Inputs of `check_signed` on this transcript. Issuer limbs and expiry are 0. Toy values: a real verifier pins the issuer. -/
def silSW (b : Bool) : Signed.Inputs where
  t := silT b
  sig := Signed.zeros
  exp := Signed.zeros
  hold := Signed.zeros
  csig := Signed.zeros
  nonce_hi := ((0 : Nat) : F)
  nonce_lo := ((0 : Nat) : F)
  attempt := 0
  role_b := b
  issuer := fun _ => ((0 : Nat) : F)
  sr := 48000
  valid_at := 0
  code := fun i => silT b (279 + i)
  a := Signed.limbBytes 0
  b := Signed.limbBytes 0
  c := Signed.limbBytes 0
  d := Signed.limbBytes 0
  back := fun i => silT b (177 + i)

theorem silSW_byteChecks (b : Bool) : Signed.ByteChecks (silSW b) := by
  cases b <;> exact
    { magic0 := by decide +kernel
      magic1 := by decide +kernel
      magic2 := by decide +kernel
      magic3 := by decide +kernel
      version := by decide +kernel
      role := by decide +kernel
      attempt := by decide +kernel
      nonce_hi := Signed.beF_of_beNat (by decide +kernel)
      nonce_lo := Signed.beF_of_beNat (by decide +kernel)
      prefix_own := by decide +kernel
      prefix_partner := by decide +kernel
      sr_eq := Signed.beF_of_beNat (by decide +kernel)
      sr_const := rfl
      delta := Signed.beF_of_beNat (by decide +kernel)
      code := fun _ _ => rfl
      limb_a := Signed.isBE_limb _ (by decide +kernel) (by decide +kernel) (by decide +kernel)
      limb_b := Signed.isBE_limb _ (by decide +kernel) (by decide +kernel) (by decide +kernel)
      limb_c := Signed.isBE_limb _ (by decide +kernel) (by decide +kernel) (by decide +kernel)
      limb_d := Signed.isBE_limb _ (by decide +kernel) (by decide +kernel) (by decide +kernel)
      expiry := Nat.zero_le _
      x_ne := (Signed.x_differ_iff _ (silT_bytes _)).mpr ⟨0, by norm_num, by decide +kernel⟩
      rr_be := by
        refine ⟨by decide +kernel, ?_⟩
        rw [PartnerGlue.beF_eq, val_natCast_of_lt (by decide +kernel)]
        exact Signed.beNat_congr _ _ 0 177 32 (fun i _ => by rw [Nat.zero_add]; rfl)
      rr_eq := fun _ _ => rfl }

/-! ### The toy signatures -/

/-- The toy signing history: the issuer credentialed both keys, each key signed its own transcript, and nothing else was signed by anyone. -/
def silMsgs : Signed.SignedSet := fun qx qy m =>
  ∃ b, (qx = Signed.issuerX (silSW b) ∧ qy = Signed.issuerY (silSW b) ∧ m = Signed.credList (silSW b)) ∨
    (qx = Signed.ownX (silSW b) ∧ qy = Signed.ownY (silSW b) ∧ m = Signed.slice (silT b) 0 311)

/-- The toy `Crypto`: the hash is the identity, and a signature verifies exactly on what the history holds. -/
def silC : Signed.Crypto := ⟨id, fun qx qy _ d => silMsgs qx qy d⟩

theorem silSW_checkSigned (b : Bool) : Signed.CheckSigned silC (silSW b) :=
  { bytes := silSW_byteChecks b
    dev_sig := by
      show silMsgs (Signed.slice (Signed.pxOf (silT b)) 0 32) (Signed.slice (Signed.pyOf (silT b)) 0 32) (id (Signed.slice (silT b) 0 311))
      rw [Signed.px_slice, Signed.py_slice]
      exact ⟨b, Or.inr ⟨rfl, rfl, rfl⟩⟩
    cred_sig := by
      show silMsgs (Signed.issuerX (silSW b)) (Signed.issuerY (silSW b)) (id (Signed.slice (Signed.credOf (silT b) Signed.zeros Signed.zeros) 0 111))
      rw [id, Signed.cred_list]
      exact ⟨b, Or.inl ⟨rfl, rfl, rfl⟩⟩ }

/-- The toy history isn't "everything": the empty message was never signed. -/
theorem silMsgs_not_everything (qx qy : List Nat) : ¬ silMsgs qx qy [] := by
  rintro ⟨b, ⟨_, _, h⟩ | ⟨_, _, h⟩⟩ <;> cases b <;> exact absurd h (by decide +kernel)

/-! ### The whole witness -/

/-- The whole witness, for any templates. Silent samples and honest Merkle paths under the leaves the offsets ask for: `p_self - 127 = 1024 * 23 + 321`. The curve is the true one, and it is all zero. The flags are all off, so the arrival is lag 0. -/
def silW (b : Bool) (c1 c2 c3 c4 : Nat → Nat) : Witness where
  nonce_hi := ((0 : Nat) : F)
  nonce_lo := ((0 : Nat) : F)
  attempt := 0
  role_b := b
  code_commit := 1
  issuer := fun _ => ((0 : Nat) : F)
  sr := 48000
  valid_at := 0
  t := silT b
  sig := Signed.zeros
  exp := Signed.zeros
  hold := Signed.zeros
  csig := Signed.zeros
  salt := 0
  c_is := c1
  c_qs := c2
  c_ip := c3
  c_qp := c4
  xs := Commit.honestXs Arrival.silent 23
  chs := Commit.honestCh permOne Arrival.silent 23
  leaf_s := ((23 : Nat) : F)
  xp := Commit.honestXs Arrival.silent (lpOf b)
  chp := Commit.honestCh permOne Arrival.silent (lpOf b)
  leaf_p := ((lpOf b : Nat) : F)
  ci := fun j => ((Arrival.corr c1 Arrival.silent j : ℤ) : F)
  cq := fun j => ((Arrival.corr c2 Arrival.silent j : ℤ) : F)
  u := fun j => decide (j < 0)
  cb := fun i => silT b (279 + i)
  a := Signed.limbBytes 0
  b := Signed.limbBytes 0
  c := Signed.limbBytes 0
  d := Signed.limbBytes 0
  back := fun i => silT b (177 + i)

theorem silT_cb (b : Bool) : (∀ i, i < 32 → silT b (279 + i) < 256) ∧ beNat (fun i => silT b (279 + i)) 0 32 = 1 := by
  cases b <;> decide +kernel

theorem fit {k : Nat} (z : Int) (hk : k ≤ 252) (hz : |z| < 2 ^ 252) (h0 : 0 ≤ z) (h1 : z < 2 ^ k) : fits k (z : F) :=
  (fits_intCast_iff_of_abs hk (by norm_num) hz).mpr ⟨h0, h1⟩

section
variable (b : Bool) (c1 c2 c3 c4 : Nat → Nat)

theorem silW_types (h1 : ∀ n, n < 12000 → c1 n < 256) (h2 : ∀ n, n < 12000 → c2 n < 256)
    (h3 : ∀ n, n < 12000 → c3 n < 256) (h4 : ∀ n, n < 12000 → c4 n < 256) : PhoneTypes (silW b c1 c2 c3 c4) :=
  { attempt_ok := by show (0 : Nat) < 2 ^ 8; norm_num
    sr_ok := by show (48000 : Nat) < 2 ^ 32; norm_num
    valid_at_ok := by show (0 : Nat) < 2 ^ 64; norm_num
    t_ok := silT_bytes b
    exp_ok := fun _ _ => by show (0 : Nat) < 256; norm_num
    hold_ok := fun _ _ => by show (0 : Nat) < 256; norm_num
    c_is_ok := h1
    c_qs_ok := h2
    c_ip_ok := h3
    c_qp_ok := h4
    xs_ok := fun _ _ => by show (32768 : Nat) < 2 ^ 16; norm_num
    xp_ok := fun _ _ => by show (32768 : Nat) < 2 ^ 16; norm_num }

theorem silW_assumptions : Assumptions silC silMsgs permOne (silW b c1 c2 c3 c4) Arrival.silent :=
  { toSigAssumptions :=
      { issuer_sig := fun hv => ⟨_, hv, rfl⟩
        issuer_hash := fun _ _ he => he
        device_sig := fun _ hv => ⟨_, hv, rfl⟩
        device_hash := fun _ _ he => he }
    rcd_u16 := fun _ => Arrival.silent_u16 _
    root_is_recording := silT_root b
    self_paths := Commit.honest_binds permOne Arrival.silent 23 (by norm_num)
    partner_paths := Commit.honest_binds permOne Arrival.silent (lpOf b) (by cases b <;> simp [lpOf]) }

theorem silW_challenges : challenges permOne (silW b c1 c2 c3 c4) = (1, 1) :=
  fsHash_one (by simp [Freivalds.fsInput])

theorem silW_spot_not_fooled :
    ¬ Freivalds.Fooled (wit (silW b c1 c2 c3 c4)) (challenges permOne (silW b c1 c2 c3 c4)).1 (challenges permOne (silW b c1 c2 c3 c4)).2 := by
  rintro ⟨⟨j, _, h⟩, _⟩
  rcases h with h | h <;> exact h rfl

theorem silW_accepts (h1 : ∀ n, n < 12000 → c1 n < 256) (h2 : ∀ n, n < 12000 → c2 n < 256)
    (h3 : ∀ n, n < 12000 → c3 n < 256) (h4 : ∀ n, n < 12000 → c4 n < 256) :
    phone_circuit silC permOne (silW b c1 c2 c3 c4) 1 := by
  have ht := silT_bytes b
  have hc := PartnerGlue.signed_casts (silT b) b ht
  have hPS := silT_pSelf b
  have hAP := silT_aPartner b
  obtain ⟨_, _, hS, hPP, _, _⟩ := silT_values b
  have hos : fits 10 (osF (silT b) ((23 : Nat) : F)) := by
    rw [PartnerGlue.osF_cast (silT b) 23 ht, hPS]
    exact fit _ (by norm_num) (by norm_num) (by norm_num) (by norm_num)
  have hop : fits 10 (opF (silT b) b ((lpOf b : Nat) : F)) := by
    rw [PartnerGlue.opF_cast (silT b) b _ ht, hAP]
    cases b <;> exact fit _ (by norm_num) (by norm_num [lpOf]) (by norm_num [lpOf]) (by norm_num [lpOf])
  have hTg : usumTarget (silT b) = ((0 : Nat) : F) := by
    have hcast := (PartnerGlue.signed_casts (silT b) false ht).2.2.2.1
    simp only [usumTarget, pSelfF, hcast, hS]
    push_cast
    ring
  have hpre : fits 33 (aPartnerF (silT b) b - pPartnerF (silT b) + 7200) := by
    have e : aPartnerF (silT b) b - pPartnerF (silT b) + 7200 = ((aPartner (silT b) b - pPartner (silT b) + 7200 : Int) : F) := by
      rw [hc.2.2.2.2.2, hc.2.1]; push_cast; ring
    rw [e, hAP, hPP]
    cases b <;> exact fit _ (by norm_num) (by norm_num) (by norm_num) (by norm_num)
  have hpost : fits 33 (pPartnerF (silT b) + 12000 - aPartnerF (silT b) b) := by
    have e : pPartnerF (silT b) + 12000 - aPartnerF (silT b) b = ((pPartner (silT b) + 12000 - aPartner (silT b) b : Int) : F) := by
      rw [hc.2.2.2.2.2, hc.2.1]; push_cast; ring
    rw [e, hAP, hPP]
    cases b <;> exact fit _ (by norm_num) (by norm_num) (by norm_num) (by norm_num)
  have hcc : cc permOne (silW b c1 c2 c3 c4) = 1 := cc_one _ _ _ _
  unfold phone_circuit
  rw [silW_challenges]
  exact
    { code_eq := hcc
      code_be := by
        rw [hcc]
        refine ⟨(silT_cb b).1, ?_⟩
        rw [show (1 : F) = ((1 : Nat) : F) from Nat.cast_one.symm, val_natCast_of_lt (by decide +kernel)]
        exact (silT_cb b).2
      signed := silSW_checkSigned b
      os_ok := hos
      open_s := by
        show open_leaves permOne _ _ _ (beF (silT b) 177 32)
        rw [silT_root]
        exact Commit.open_leaves_complete permOne Arrival.silent 23 (by norm_num)
      op_ok := hop
      open_p := by
        show open_leaves permOne _ _ _ (beF (silT b) 177 32)
        rw [silT_root]
        exact Commit.open_leaves_complete permOne Arrival.silent (lpOf b) (by cases b <;> simp [lpOf])
      arrival := by
        show Arrival.ArrivalOK _ _ (usumTarget (silT b))
        rw [hTg]
        exact (Arrival.silence_passes (u8_of h1) (u8_of h2)).1
      spot := ⟨1, mul_one 1, Freivalds.freivalds_complete _ 1 (mul_one 1) (fun _ _ => rfl) (fun _ _ => rfl)⟩
      partner := PartnerGlue.partner_silence_accepts _ _ c3 c4 (fun _ _ => rfl) h3 h4
      wpre := hpre
      wpost := hpost
      output := (hash_one (by simp [HalfOpening.toList])).symm }

end

end Silence

open Silence in
/-- **The known silence case meets `phone_sound`, all of it.** For either role and ANY `u8` templates, a recording of nothing but digital silence meets every input type, every assumption, the spot check and the circuit, and `phone_sound`'s whole conclusion then holds.
At the arrival lag, loudness and match are both 0. At the partner lag, too. So "the arrival is the first lag meeting the test" and "the partner lag meets the test" are true of a recording with no sound in it.

This is the point of the theorem: `phone_sound` does NOT say a beep was heard. It also shows the hypotheses of `phone_sound` aren't contradictory, in a toy model of the hashes and signatures. See the section header for what the toy leaves open. The real compiled circuit accepts this shape too (`circuit-cases` b). -/
theorem silence_satisfies_phone_sound (b : Bool) (c1 c2 c3 c4 : Nat → Nat)
    (h1 : ∀ n, n < 12000 → c1 n < 256) (h2 : ∀ n, n < 12000 → c2 n < 256)
    (h3 : ∀ n, n < 12000 → c3 n < 256) (h4 : ∀ n, n < 12000 → c4 n < 256) :
    PhoneTypes (silW b c1 c2 c3 c4) ∧
    Assumptions silC silMsgs permOne (silW b c1 c2 c3 c4) Arrival.silent ∧
    phone_circuit silC permOne (silW b c1 c2 c3 c4) 1 ∧
    ¬ Freivalds.Fooled (wit (silW b c1 c2 c3 c4)) (challenges permOne (silW b c1 c2 c3 c4)).1 (challenges permOne (silW b c1 c2 c3 c4)).2 ∧
    PhoneConclusion silC silMsgs permOne (silW b c1 c2 c3 c4) 1 Arrival.silent ∧
    (∀ n, Arrival.silent n = 32768) ∧
    (∃ base base' : Int,
      FirstLoudEnough (recWindow Arrival.silent base) c1 c2 0 ∧
      Arrival.bigC (recWindow Arrival.silent base) c1 0 = 0 ∧ Arrival.env2 (recWindow Arrival.silent base) c1 c2 0 = 0 ∧
      PartnerLoudEnough (recWindow Arrival.silent base') c3 c4 ∧
      PartnerGlue.EI (recWindow Arrival.silent base') 0 = 0 ∧
      PartnerGlue.II (recWindow Arrival.silent base') 0 c3 = 0 ∧ PartnerGlue.II (recWindow Arrival.silent base') 0 c4 = 0) ∧
    (∀ qx qy, ¬ silMsgs qx qy []) :=
  ⟨silW_types b c1 c2 c3 c4 h1 h2 h3 h4, silW_assumptions b c1 c2 c3 c4, silW_accepts b c1 c2 c3 c4 h1 h2 h3 h4,
    silW_spot_not_fooled b c1 c2 c3 c4,
    phone_sound (silW_types b c1 c2 c3 c4 h1 h2 h3 h4) (silW_assumptions b c1 c2 c3 c4) (silW_accepts b c1 c2 c3 c4 h1 h2 h3 h4)
      (silW_spot_not_fooled b c1 c2 c3 c4),
    fun _ => rfl,
    ⟨_, _, silent_recording_passes_the_tests 0 0 c1 c2 c3 c4⟩,
    silMsgs_not_everything⟩

open Silence in
/-- **The known silence case meets `presence_sound`, all of it.** Two phones, with ANY `u8` templates, record digital silence and sign one chosen `half`, here 10000 on both. `pair` accepts at flight exactly 0 cm, `HalfBinds` holds and the conclusion holds. This statement lists only those. The proof builds the other hypotheses of `presence_sound` for the same witness, but doesn't export them.
There is no sound anywhere in either recording. Nothing in this witness says where either phone was: there is no position in it at all, and the same witness works if they were on different continents.

So "`-20 < flight < 60`" is arithmetic on signed numbers. It is NOT proof that two phones were near each other, and NOT proof that anything was heard. Same shape as `circuit-cases` e1, which the real compiled circuit accepts with throwaway keys. One silent cheater is enough in the real circuit too: `circuit-cases` e2, handed the other phone's half, reads 33.9 cm. That's a `nargo` run, not a theorem here. It needs a device willing to sign a silent recording and a credential from the issuer:
this witness uses toys for both. -/
theorem silence_satisfies_presence_sound (c1 c2 c3 c4 c5 c6 c7 c8 : Nat → Nat)
    (h1 : ∀ n, n < 12000 → c1 n < 256) (h2 : ∀ n, n < 12000 → c2 n < 256)
    (h3 : ∀ n, n < 12000 → c3 n < 256) (h4 : ∀ n, n < 12000 → c4 n < 256)
    (h5 : ∀ n, n < 12000 → c5 n < 256) (h6 : ∀ n, n < 12000 → c6 n < 256)
    (h7 : ∀ n, n < 12000 → c7 n < 256) (h8 : ∀ n, n < 12000 → c8 n < 256) :
    let wA := silW false c1 c2 c3 c4
    let wB := silW true c5 c6 c7 c8
    let n0 : F := ((0 : Nat) : F)
    let hh : F := ((10000 : Int) : F)
    let xa0 := beF (silT false) 40 16
    let xa1 := beF (silT false) 56 16
    let xb0 := beF (silT true) 40 16
    let xb1 := beF (silT true) 56 16
    pairCircuit (hash_n permOne) n0 n0 0 1 1 48000 48000 hh 0 hh 0 xa0 xa1 xb0 xb1 ∧
    HalfBinds permOne (opening wA).toList (pairListA n0 n0 0 48000 hh 0 xa0 xa1 xb0 xb1) ∧
    HalfBinds permOne (opening wB).toList (pairListB n0 n0 0 48000 hh 0 xa0 xa1 xb0 xb1) ∧
    PresenceConclusion silC silMsgs permOne wA wB 1 1 Arrival.silent Arrival.silent n0 n0 0 48000 48000 hh 0 hh 0 xa0 xa1 xb0 xb1 ∧
    flight (half wA.t) (half wB.t) 48000 48000 = 0 ∧
    (∀ n, Arrival.silent n = 32768) := by
  intro wA wB n0 hh xa0 xa1 xb0 xb1
  have hne : (xa0, xa1) ≠ (xb0, xb1) := by
    have hx := (silSW_byteChecks false).x_ne
    have hx' : beF (silT false) 40 16 ≠ beF (silT false) 105 16 ∨ beF (silT false) 56 16 ≠ beF (silT false) 121 16 := hx
    rw [keys_cross_0, keys_cross_1] at hx'
    exact (keys_differ_iff _ _ _ _).1 hx'
  have hP : pairCircuit (hash_n permOne) n0 n0 0 1 1 48000 48000 hh 0 hh 0 xa0 xa1 xb0 xb1 := by
    obtain ⟨_, _, rest⟩ := pair_complete (hash_n permOne) n0 n0 0 48000 48000 10000 10000 0 0 xa0 xa1 xb0 xb1
      (by norm_num) (by norm_num) (by norm_num) (by norm_num) (by norm_num) (by norm_num) (by norm_num) (by norm_num) hne
      (by norm_num) (by norm_num)
    exact ⟨hash_one (by simp), hash_one (by simp), rest⟩
  have listA : (opening wA).toList = pairListA n0 n0 0 48000 hh 0 xa0 xa1 xb0 xb1 := by
    show ([n0, n0, ((0 : Nat) : F), boolF false, ((48000 : Nat) : F), halfF (silT false), 0, xa0, xa1,
      beF (silT false) 105 16, beF (silT false) 121 16] : List F) = [n0, n0, ((0 : Nat) : F), 0, ((48000 : Nat) : F), hh, 0, xa0, xa1, xb0, xb1]
    rw [boolF_false, silT_halfF, keys_cross_0, keys_cross_1]
  have listB : (opening wB).toList = pairListB n0 n0 0 48000 hh 0 xa0 xa1 xb0 xb1 := by
    show ([n0, n0, ((0 : Nat) : F), boolF true, ((48000 : Nat) : F), halfF (silT true), 0, xb0, xb1,
      beF (silT true) 105 16, beF (silT true) 121 16] : List F) = [n0, n0, ((0 : Nat) : F), 1, ((48000 : Nat) : F), hh, 0, xb0, xb1, xa0, xa1]
    rw [boolF_true, silT_halfF, keys_cross_2, keys_cross_3]
  have bA : HalfBinds permOne (opening wA).toList (pairListA n0 n0 0 48000 hh 0 xa0 xa1 xb0 xb1) := fun _ => listA
  have bB : HalfBinds permOne (opening wB).toList (pairListB n0 n0 0 48000 hh 0 xa0 xa1 xb0 xb1) := fun _ => listB
  have hf : flight (half wA.t) (half wB.t) 48000 48000 = 0 := by
    show flight (half (silT false)) (half (silT true)) 48000 48000 = 0
    rw [(silT_values false).2.1, (silT_values true).2.1]
    unfold flight
    norm_num
  exact ⟨hP, bA, bB,
    presence_sound (silW_types false c1 c2 c3 c4 h1 h2 h3 h4) (silW_types true c5 c6 c7 c8 h5 h6 h7 h8)
      (by show (0 : Nat) < 2 ^ 8; norm_num) (by show (48000 : Nat) < 2 ^ 32; norm_num) (by show (48000 : Nat) < 2 ^ 32; norm_num)
      (silW_assumptions false c1 c2 c3 c4) (silW_assumptions true c5 c6 c7 c8)
      (silW_accepts false c1 c2 c3 c4 h1 h2 h3 h4) (silW_accepts true c5 c6 c7 c8 h5 h6 h7 h8)
      (silW_spot_not_fooled false c1 c2 c3 c4) (silW_spot_not_fooled true c5 c6 c7 c8) hP bA bB,
    hf, fun _ => rfl⟩

end Chain
end Popfv

#print axioms Popfv.Chain.tables_agree
#print axioms Popfv.Chain.arrival_window_congr
#print axioms Popfv.Chain.partner_window_congr
#print axioms Popfv.Chain.phone_sound_core
#print axioms Popfv.Chain.phone_sound_at
#print axioms Popfv.Chain.phone_sound
#print axioms Popfv.Chain.phone_sound_no_tree
#print axioms Popfv.Chain.values_are_signed_bytes
#print axioms Popfv.Chain.phone_bad_challenges
#print axioms Popfv.Chain.phone_bad_odds
#print axioms Popfv.Chain.presence_sound
#print axioms Popfv.Chain.silent_recording_passes_the_tests
#print axioms Popfv.Chain.silence_forces_lag_zero
#print axioms Popfv.Chain.loud_enough_vs_score
#print axioms Popfv.Chain.Silence.silW_accepts
#print axioms Popfv.Chain.silence_satisfies_phone_sound
#print axioms Popfv.Chain.silence_satisfies_presence_sound
