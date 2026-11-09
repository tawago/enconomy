import Popfv.PartnerGlue

/-!
# Popfv.Signed — block A: `check_signed` and `unpack_issuer`

Source: `research/worldid/prototypes/optA-noir/noir/oalib/src/lib.nr`, lines 184-198 and 213-299. Called from
`phone/src/main.nr` line 36. Line numbers below refer to `lib.nr` unless a file is named.

## Layouts, read from the source, not typed from memory

Transcript, 311 bytes. Sizes come from the struct strings in `server/pop/codec.py` line 29 (`_TX`,
`>4sBcB32s65s65sIi32sQQQi32s`) and line 30 (`_TX2X`, `>IIH32s`). They agree with the table in
`docs/pop-transcript-v2.md` section 1. `Layout.*` below recomputes every offset by adding up those sizes, and
`Layout.offsets` pins each one to the number the circuit uses. A one-off Python run put the fixture
`phone/Prover_A.toml` from the built circuits through the same struct string and got the same offsets.

Credential `SBcred3`, 111 bytes: `lib.nr` 254-268, `server/pop/issuer.py` line 3.

## What the circuit checks, and what it doesn't

"Hash only" means the bytes reach the proof only through `sha256(t)`, so the device key vouches for them and no
constraint reads them. `digest_only_free` proves this for all 88 such bytes at once. `only_read_bytes_matter`
proves that, the signatures aside, the 200 transcript bytes outside the 111 that the asserts read can be anything,
as long as own X and partner X still differ. Read doesn't mean fixed. Of those 111, the 32 `rec_root` bytes are tied to
no value: they only have to be below `p` and re-serialise. The rest of the 111 are fixed only as the rows below say.

| Thing | Transcript bytes | lib.nr lines | Status in this block |
|---|---|---|---|
| magic, version | 0-4 | 228-232 | fixed to `POPT`, 2 |
| role, attempt | 5-6 | 233-234 | fixed to the public inputs |
| session nonce | 7-38 | 235-236 | fixed to the public `nonce_hi`, `nonce_lo` |
| `04` prefix of both keys | 39, 104 | 237-238 | fixed, says nothing else about the keys |
| sample rate | 169-172 | 239-240 | fixed to 48000 |
| delta | 277-278 | 241 | fixed to 96 |
| `code_commit` bytes | 279-310 | 242-244 | fixed to `code`, which `phone/main.nr` 33-36 ties to the public `code_commit` |
| `rec_root` | 177-208 | 279-283 | below `p`, read canonically. No check here ties it to any value |
| own key X, Y | 40-103 | 249-253, 260-262, 275, 277, 296 | inside `verify_signature` and the credential. The X limbs are also compared to partner X and exported as `Signed.x_own`. Y goes nowhere else |
| partner X | 105-136 | 276-277 | prefix and "differs from own X", then exported |
| expiry | not in `t` | 272-273 | `valid_at <= expiry`, exact u64 |
| issuer key | not in `t` | 184-198, 270-271 | whatever the public `issuer` limbs say; the verifier must pin them |
| **`commit_hash`** | 237-268 | never read | **hash only.** Nothing compares it to a POPC commitment or to `rec_root` |
| **play and capture times** | 209-232 | never read | **hash only** |
| **partner Y** | 137-168 | never read | **hash only.** Only the X limbs are compared and exported |
| **partner key validity and ownership** | 104-168 | - | **not checked.** No credential, no signature, no curve check |
| **`half`, `self_os_delta`, `a_self`, `p_partner`** | 173-176, 233-236, 269-276 | 284-287 | **read, not constrained here.** `phone_core` constrains them afterwards |
| **`hold`, holder commit** | not in `t` | 266-268 | **only hashed into the credential, never opened** (also `server/pop/issuer.py` line 6) |
| **own key on the curve** | 39-103 | - | **no constraint of its own.** Whatever the ECDSA blackbox does, which is opaque here |
| **own Y vs partner Y, device key vs issuer key** | - | - | **no comparison** |
| **`sig`, `csig` low-S or uniqueness** | not in `t` | - | **not checked here.** Opaque |
| **`valid_at` is fresh, credential was issued before it** | not in `t` | - | **not checked.** Public input, upper bound only |
| **issuer is the real issuer** | not in `t` | - | **not checked.** Public input; the server's check pins it (`server/pop/zk.py` line 13) |

## Modelling

* Byte arrays are functions `Nat → Nat`, as in `PartnerGlue.lean`. Their type ranges are hypotheses (`Types`).
* Loops that write arrays are `fill`, one `Function.update` per iteration, written literally.
* `sha256::digest` and `verify_signature` are arbitrary fields of `Crypto`, taking `List Nat`, so a message's length
  is part of the message. Nothing about them is assumed in the model.
* Unforgeability and collision resistance appear ONLY as the named hypotheses `Unforgeable` and `NoCollisionWith`,
  and only for the one key, signature and digest involved. A universal version of either would be false: every digest
  has some verifying signature as a mathematical object under a valid ECDSA key, and two lists of bytes do collide
  under SHA-256 by counting. `chain_hypotheses_consistent` shows the scoped hypotheses all hold at once with the circuit
  accepting, in a toy where every digest has a verifying signature and the universal version fails.
* `to_be_bytes::<N>` is `IsBE`: bytes, and the big-endian value is exactly `x.val`. For `N = 32` that is an unproved
  modelling assumption about Noir. It is the only thing closing the `rec_root` alias (`alias_without_canonical`). It was
  read from source: the built `phone/target/phone.json` says `noir_version` is
  `1.0.0-beta.22+c57152f91260ecdb9faad4efc20abb14b6d2ece7`, and that revision's `noir_stdlib/src/field/mod.nr` lines
  131-156 does a byte-by-byte check against the modulus in constrained code. The `lib.nr` embedded in that `phone.json` is
  the first 535 lines of today's `lib.nr`, byte for byte; today's file only adds the `_opt` section after them. For
  `N ≤ 31`, `IsBE` follows from "they are bytes and they recompose to x" (`isBE_of_recompose`).
* `phone/main.nr`'s block H hash and `phone_core` are not here.

## Spec drift, for the record

`docs/pop-transcript-v2.md` is an older proposal. Its offsets match. Its hashes do not: it says `code_commit` is
`sha256(...)` and `rec_root` is Poseidon7 over the P-256 field. The circuit and `server/pop/popt2.py`,
`server/pop/codec.py` use Poseidon2 over BN254, and the doc's `rec_root < p` means the BN254 `p` in the code.
-/

set_option linter.style.whitespace false
set_option linter.style.longLine false
set_option linter.style.header false

namespace Popfv
namespace Signed

open PartnerGlue

/-! ## The layout, computed from the sizes in `server/pop/codec.py` lines 29, 30 -/

namespace Layout
def off_magic : Nat := 0
def off_version : Nat := off_magic + 4         -- 4s
def off_role : Nat := off_version + 1          -- B
def off_attempt : Nat := off_role + 1          -- c
def off_nonce : Nat := off_attempt + 1         -- B
def off_pk_self : Nat := off_nonce + 32        -- 32s
def off_pk_partner : Nat := off_pk_self + 65   -- 65s
def off_sample_rate : Nat := off_pk_partner + 65 -- 65s
def off_half : Nat := off_sample_rate + 4      -- I
def off_rec_root : Nat := off_half + 4         -- i
def off_play_frame : Nat := off_rec_root + 32  -- 32s
def off_play_nano : Nat := off_play_frame + 8  -- Q
def off_rec_frame0 : Nat := off_play_nano + 8  -- Q
def off_self_os_delta : Nat := off_rec_frame0 + 8 -- Q
def off_commit_hash : Nat := off_self_os_delta + 4 -- i
def off_a_self : Nat := off_commit_hash + 32   -- 32s; end of _TX, start of _TX2X
def off_p_partner : Nat := off_a_self + 4      -- I
def off_delta : Nat := off_p_partner + 4       -- I
def off_code_commit : Nat := off_delta + 2     -- H
def off_end : Nat := off_code_commit + 32      -- 32s

/-- Credential, `lib.nr` 257-268 and `server/pop/issuer.py` line 3. -/
def cred_tag : Nat := 0
def cred_xy : Nat := cred_tag + 7
def cred_expiry : Nat := cred_xy + 64
def cred_holder : Nat := cred_expiry + 8
def cred_end : Nat := cred_holder + 32

/-- Every offset the circuit uses, against the offset the layout computes. -/
theorem offsets :
    off_version = 4 ∧ off_role = 5 ∧ off_attempt = 6 ∧ off_nonce = 7 ∧ off_pk_self = 39 ∧
    off_pk_partner = 104 ∧ off_sample_rate = 169 ∧ off_half = 173 ∧ off_rec_root = 177 ∧
    off_play_frame = 209 ∧ off_play_nano = 217 ∧ off_rec_frame0 = 225 ∧ off_self_os_delta = 233 ∧
    off_commit_hash = 237 ∧ off_a_self = 269 ∧ off_p_partner = 273 ∧ off_delta = 277 ∧
    off_code_commit = 279 ∧ off_end = 311 ∧
    cred_xy = 7 ∧ cred_expiry = 71 ∧ cred_holder = 79 ∧ cred_end = 111 := by
  decide
end Layout

/-! ## Lists of bytes -/

/-- The `n` entries of `f` starting at `off`. -/
def slice (f : Nat → Nat) (off n : Nat) : List Nat := (List.range n).map (fun i => f (off + i))

theorem slice_congr {f g : Nat → Nat} {off off' n : Nat} (h : ∀ i, i < n → f (off + i) = g (off' + i)) :
    slice f off n = slice g off' n := by
  unfold slice
  apply List.map_congr_left
  intro i hi
  exact h i (List.mem_range.mp hi)

theorem slice_split (f : Nat → Nat) (off m n off' : Nat) (h : off' = off + m) :
    slice f off (m + n) = slice f off m ++ slice f off' n := by
  subst h
  unfold slice
  rw [List.range_add, List.map_append, List.map_map]
  congr 1
  apply List.map_congr_left
  intro i _
  simp [Nat.add_assoc]

/-! ## Big-endian numbers over a window -/

theorem beNat_congr (t t' : Nat → Nat) (off off' n : Nat) (h : ∀ i, i < n → t (off + i) = t' (off' + i)) :
    beNat t off n = beNat t' off' n := by
  induction n with
  | zero => rfl
  | succ n ih =>
    simp only [beNat]
    rw [ih (fun i hi => h i (by omega)), h n (by omega)]

theorem beF_congr (t t' : Nat → Nat) (off n : Nat) (h : ∀ i, i < n → t (off + i) = t' (off + i)) :
    beF t off n = beF t' off n := by
  rw [beF_eq, beF_eq, beNat_congr t t' off off n h]

theorem signed32_congr (t t' : Nat → Nat) (off : Nat) (h : ∀ i, i < 4 → t (off + i) = t' (off + i)) :
    signed32 t off = signed32 t' off := by
  have h0 : t off = t' off := by simpa using h 0 (by norm_num)
  have hb := beF_congr t t' off 4 h
  simp only [signed32, h0, hb]

theorem beNat_lt_win (t : Nat → Nat) (off n : Nat) (h : ∀ i, i < n → t (off + i) < 256) :
    beNat t off n < 256 ^ n := by
  induction n with
  | zero => simp [beNat]
  | succ n ih =>
    have h1 := ih (fun i hi => h i (by omega))
    have h2 := h n (by omega)
    simp only [beNat, pow_succ]
    generalize 256 ^ n = X at h1 ⊢
    omega

theorem beNat16_lt (t : Nat → Nat) (off : Nat) (h : ∀ i, i < 16 → t (off + i) < 256) :
    beNat t off 16 < 2 ^ 128 := by
  have := beNat_lt_win t off 16 h
  norm_num at this ⊢; exact this

/-- Up to 31 bytes the field element's value is the big-endian number, with no wraparound. -/
theorem beF_val_win (t : Nat → Nat) (off n : Nat) (hn : n ≤ 31) (h : ∀ i, i < n → t (off + i) < 256) :
    (beF t off n).val = beNat t off n := by
  rw [beF_eq]
  apply val_natCast_of_lt
  have h1 := beNat_lt_win t off n h
  have h2 : (256:Nat) ^ n ≤ 256 ^ 31 := Nat.pow_le_pow_right (by norm_num) hn
  have h3 : (256:Nat) ^ 31 < p := by unfold p; norm_num
  omega

theorem beF_of_beNat {t : Nat → Nat} {off n v : Nat} (h : beNat t off n = v) : beF t off n = (v : F) := by
  rw [beF_eq, h]

theorem beNat_of_beF {t : Nat → Nat} {off n v : Nat} (hn : n ≤ 31) (hb : ∀ i, i < n → t (off + i) < 256)
    (hv : v < p) (e : beF t off n = (v : F)) : beNat t off n = v := by
  have := congrArg ZMod.val e
  rwa [beF_val_win t off n hn hb, val_natCast_of_lt hv] at this

/-- Equal big-endian numbers over byte windows of the same length mean equal bytes. -/
theorem beNat_inj (t t' : Nat → Nat) (off off' n : Nat)
    (h1 : ∀ i, i < n → t (off + i) < 256) (h2 : ∀ i, i < n → t' (off' + i) < 256)
    (e : beNat t off n = beNat t' off' n) : ∀ i, i < n → t (off + i) = t' (off' + i) := by
  induction n with
  | zero => intro i hi; omega
  | succ n ih =>
    have b1 := h1 n (by omega)
    have b2 := h2 n (by omega)
    simp only [beNat] at e
    have e1 : beNat t off n = beNat t' off' n := by omega
    have e2 : t (off + n) = t' (off' + n) := by omega
    intro i hi
    by_cases hin : i = n
    · subst hin; exact e2
    · exact ih (fun j hj => h1 j (by omega)) (fun j hj => h2 j (by omega)) e1 i (by omega)

theorem beNat_split (t : Nat → Nat) (off m n : Nat) :
    beNat t off (m + n) = beNat t off m * 256 ^ n + beNat t (off + m) n := by
  induction n with
  | zero => simp [beNat]
  | succ n ih =>
    rw [← Nat.add_assoc m n 1]
    simp only [beNat]
    rw [ih, pow_succ, Nat.add_assoc off m n]
    ring

/-! ## `to_be_bytes` -/

/-- `let b: [u8; N] = x.to_be_bytes();`: `b` holds bytes and its big-endian value is exactly `x.val`.
Trusted Noir behaviour for `N = 32` (see the file header). -/
def IsBE (N : Nat) (x : F) (b : Nat → Nat) : Prop :=
  (∀ i, i < N → b i < 256) ∧ beNat b 0 N = x.val

theorem isBE_bytes {N : Nat} {x : F} {b : Nat → Nat} (h : IsBE N x b) : ∀ i, i < N → b (0 + i) < 256 := by
  intro i hi; rw [Nat.zero_add]; exact h.1 i hi

/-- `to_be_bytes` has one answer. -/
theorem isBE_unique {N : Nat} {x : F} {b b' : Nat → Nat} (h : IsBE N x b) (h' : IsBE N x b') :
    ∀ i, i < N → b i = b' i := by
  intro i hi
  have := beNat_inj b b' 0 0 N (isBE_bytes h) (isBE_bytes h') (h.2.trans h'.2.symm) i hi
  simpa using this

/-- Below 32 bytes, `IsBE` needs no trust in canonicality: "they are bytes and they recompose to `x`" is enough. -/
theorem isBE_of_recompose {N : Nat} {x : F} {b : Nat → Nat} (hN : N ≤ 31) (hb : ∀ i, i < N → b i < 256)
    (e : beF b 0 N = x) : IsBE N x b := by
  have hb' : ∀ i, i < N → b (0 + i) < 256 := by
    intro i hi; rw [Nat.zero_add]; exact hb i hi
  exact ⟨hb, by rw [← e, beF_val_win b 0 N hN hb']⟩

/-- Noir `x as u64` (line 272): the low 64 bits of the canonical value. -/
def asU64 (x : F) : Nat := x.val % 2 ^ 64

/-! ## Array-filling loops -/

/-- `for i in 0..n { c[base + i] = src(i); }` -/
def fill (c src : Nat → Nat) (base : Nat) : Nat → Nat → Nat
  | 0 => c
  | n + 1 => Function.update (fill c src base n) (base + n) (src n)

theorem fill_at (c src : Nat → Nat) (base n j : Nat) (hj : j < n) : fill c src base n (base + j) = src j := by
  induction n with
  | zero => omega
  | succ n ih =>
    by_cases hjn : j = n
    · subst hjn; simp [fill]
    · have hne : base + j ≠ base + n := by omega
      simp only [fill]
      rw [Function.update_of_ne hne]
      exact ih (by omega)

theorem fill_out (c src : Nat → Nat) (base n x : Nat) (hx : x < base ∨ base + n ≤ x) :
    fill c src base n x = c x := by
  induction n with
  | zero => rfl
  | succ n ih =>
    have hne : x ≠ base + n := by omega
    simp only [fill]
    rw [Function.update_of_ne hne]
    exact ih (by omega)

/-- `[0u8; N]` -/
def zeros : Nat → Nat := fun _ => 0

/-- lines 247, 249-252: `px[i] = t[40 + i]`. -/
def pxOf (t : Nat → Nat) : Nat → Nat := fill zeros (fun i => t (40 + i)) 0 32
/-- lines 248, 249-252: `py[i] = t[72 + i]`. -/
def pyOf (t : Nat → Nat) : Nat → Nat := fill zeros (fun i => t (72 + i)) 0 32

/-- lines 185, 191-196: `x[i] = a[i]; x[16 + i] = b[i]`. Same for `y` with `c`, `d` (lines 186, 194-195). -/
def unpackXY (a b : Nat → Nat) : Nat → Nat := fill (fill zeros a 0 16) b 16 16

/-- line 256 -/
def credTag : List Nat := [0x53, 0x42, 0x63, 0x72, 0x65, 0x64, 0x33]
def tagAt (i : Nat) : Nat := credTag.getD i 0

/-- lines 255-268: `c`, four loops in source order. -/
def credOf (t e h : Nat → Nat) : Nat → Nat :=
  fill (fill (fill (fill zeros tagAt 0 7) (fun i => t (40 + i)) 7 64) e 71 8) h 79 32

theorem credTag_is_SBcred3 : credTag = "SBcred3".toList.map Char.toNat := by decide

theorem cred_tag (t e h : Nat → Nat) (i : Nat) (hi : i < 7) : credOf t e h (0 + i) = tagAt i := by
  unfold credOf
  rw [fill_out _ _ 79 32 _ (Or.inl (by omega)), fill_out _ _ 71 8 _ (Or.inl (by omega)),
    fill_out _ _ 7 64 _ (Or.inl (by omega))]
  exact fill_at _ _ 0 7 i hi

theorem cred_key (t e h : Nat → Nat) (i : Nat) (hi : i < 64) : credOf t e h (7 + i) = t (40 + i) := by
  unfold credOf
  rw [fill_out _ _ 79 32 _ (Or.inl (by omega)), fill_out _ _ 71 8 _ (Or.inl (by omega))]
  exact fill_at _ (fun i => t (40 + i)) 7 64 i hi

theorem cred_exp (t e h : Nat → Nat) (i : Nat) (hi : i < 8) : credOf t e h (71 + i) = e i := by
  unfold credOf
  rw [fill_out _ _ 79 32 _ (Or.inl (by omega))]
  exact fill_at _ _ 71 8 i hi

theorem cred_hold (t e h : Nat → Nat) (i : Nat) (hi : i < 32) : credOf t e h (79 + i) = h i := by
  unfold credOf
  exact fill_at _ _ 79 32 i hi

/-- `"SBcred3" | X | Y | expiry | holder_commit`. -/
def credMsg (X Y e h : List Nat) : List Nat := credTag ++ X ++ Y ++ e ++ h

/-- The four loops write exactly the documented message, all 111 bytes, in order. -/
theorem cred_list (t e h : Nat → Nat) :
    slice (credOf t e h) 0 111 = credMsg (slice t 40 32) (slice t 72 32) (slice e 0 8) (slice h 0 32) := by
  have s1 : slice (credOf t e h) 0 111 = slice (credOf t e h) 0 79 ++ slice (credOf t e h) 79 32 :=
    slice_split _ 0 79 32 79 rfl
  have s2 : slice (credOf t e h) 0 79 = slice (credOf t e h) 0 71 ++ slice (credOf t e h) 71 8 :=
    slice_split _ 0 71 8 71 rfl
  have s3 : slice (credOf t e h) 0 71 = slice (credOf t e h) 0 39 ++ slice (credOf t e h) 39 32 :=
    slice_split _ 0 39 32 39 rfl
  have s4 : slice (credOf t e h) 0 39 = slice (credOf t e h) 0 7 ++ slice (credOf t e h) 7 32 :=
    slice_split _ 0 7 32 7 rfl
  have p0 : slice (credOf t e h) 0 7 = credTag := by
    have : slice (credOf t e h) 0 7 = slice tagAt 0 7 :=
      slice_congr (fun i hi => by rw [cred_tag t e h i hi, Nat.zero_add])
    rw [this]; decide
  have p1 : slice (credOf t e h) 7 32 = slice t 40 32 :=
    slice_congr (fun i hi => cred_key t e h i (by omega))
  have p2 : slice (credOf t e h) 39 32 = slice t 72 32 :=
    slice_congr (fun i hi => by
      have := cred_key t e h (32 + i) (by omega)
      have e1 : 7 + (32 + i) = 39 + i := by omega
      have e2 : 40 + (32 + i) = 72 + i := by omega
      rwa [e1, e2] at this)
  have p3 : slice (credOf t e h) 71 8 = slice e 0 8 :=
    slice_congr (fun i hi => by rw [cred_exp t e h i hi, Nat.zero_add])
  have p4 : slice (credOf t e h) 79 32 = slice h 0 32 :=
    slice_congr (fun i hi => by rw [cred_hold t e h i hi, Nat.zero_add])
  rw [s1, s2, s3, s4, p0, p1, p2, p3, p4]
  simp only [credMsg]

theorem px_slice (t : Nat → Nat) : slice (pxOf t) 0 32 = slice t 40 32 :=
  slice_congr (fun i hi => fill_at _ (fun i => t (40 + i)) 0 32 i hi)

theorem py_slice (t : Nat → Nat) : slice (pyOf t) 0 32 = slice t 72 32 :=
  slice_congr (fun i hi => fill_at _ (fun i => t (72 + i)) 0 32 i hi)

theorem unpack_lo (a b : Nat → Nat) (i : Nat) (hi : i < 16) : unpackXY a b (0 + i) = a (0 + i) := by
  unfold unpackXY
  rw [fill_out _ _ 16 16 _ (Or.inl (by omega)), fill_at _ _ 0 16 i hi, Nat.zero_add]

theorem unpack_hi (a b : Nat → Nat) (i : Nat) (hi : i < 16) : unpackXY a b (16 + i) = b (0 + i) := by
  unfold unpackXY
  rw [fill_at _ _ 16 16 i hi, Nat.zero_add]

theorem unpack_slice (a b : Nat → Nat) :
    slice (unpackXY a b) 0 32 = slice a 0 16 ++ slice b 0 16 := by
  have s : slice (unpackXY a b) 0 32 = slice (unpackXY a b) 0 16 ++ slice (unpackXY a b) 16 16 :=
    slice_split _ 0 16 16 16 rfl
  rw [s, slice_congr (fun i hi => unpack_lo a b i hi), slice_congr (fun i hi => unpack_hi a b i hi)]

/-- A 32-byte coordinate is the two 16-byte limbs, high limb first. -/
theorem unpack_value (a b : Nat → Nat) :
    beNat (unpackXY a b) 0 32 = beNat a 0 16 * 2 ^ 128 + beNat b 0 16 := by
  have s := beNat_split (unpackXY a b) 0 16 16
  have e1 : beNat (unpackXY a b) 0 16 = beNat a 0 16 :=
    beNat_congr _ _ 0 0 16 (fun i hi => unpack_lo a b i hi)
  have e2 : beNat (unpackXY a b) (0 + 16) 16 = beNat b 0 16 :=
    beNat_congr _ _ (0 + 16) 0 16 (fun i hi => by
      rw [Nat.zero_add 16]; exact unpack_hi a b i hi)
  rw [e1, e2] at s
  have e3 : (256:Nat) ^ 16 = 2 ^ 128 := by norm_num
  rw [e3] at s
  exact s

/-! ## The opaque primitives -/

/-- `sha256::digest` (lines 246, 269) and `std::ecdsa_secp256r1::verify_signature` (lines 253, 271). Arbitrary: a
theorem over `Crypto` holds whatever these are. -/
structure Crypto where
  sha256 : List Nat → List Nat
  /-- `verify_signature(pub_x, pub_y, sig, digest)` -/
  verify : List Nat → List Nat → List Nat → List Nat → Prop

/-- line 22 -/ def SR : Nat := 48000
/-- line 25 -/ def DELTA : Nat := 96

/-! ## `check_signed`: arguments, constraints, output -/

/-- The arguments of `check_signed` (lines 214-226) and the outputs of its `to_be_bytes` calls, which are the only
values it computes that aren't functions of the arguments in this model. -/
structure Inputs where
  t : Nat → Nat
  sig : Nat → Nat
  exp : Nat → Nat
  hold : Nat → Nat
  csig : Nat → Nat
  nonce_hi : F
  nonce_lo : F
  attempt : Nat
  role_b : Bool
  issuer : Nat → F
  sr : Nat
  valid_at : Nat
  code : Nat → Nat
  /-- lines 187-190 -/
  a : Nat → Nat
  b : Nat → Nat
  c : Nat → Nat
  d : Nat → Nat
  /-- line 280 -/
  back : Nat → Nat

/-- The type ranges Noir gives the arguments (lines 214-226). -/
structure Types (w : Inputs) : Prop where
  t_ok : bytesOK w.t                         -- t: [u8; 311]
  exp_ok : ∀ i, i < 8 → w.exp i < 256        -- exp: [u8; 8]
  hold_ok : ∀ i, i < 32 → w.hold i < 256     -- hold: [u8; 32]
  sr_ok : isU32 w.sr                         -- sr: u32
  valid_at_ok : isU64 w.valid_at             -- valid_at: u64

/-- Every constraint of `check_signed` except the two signature checks, in source order. -/
structure ByteChecks (w : Inputs) : Prop where
  magic0 : w.t 0 = 0x50                                     -- 228
  magic1 : w.t 1 = 0x4f                                     -- 229
  magic2 : w.t 2 = 0x50                                     -- 230
  magic3 : w.t 3 = 0x54                                     -- 231
  version : w.t 4 = 2                                       -- 232
  role : w.t 5 = 0x41 + (if w.role_b then 1 else 0)         -- 233
  attempt : w.t 6 = w.attempt                               -- 234
  nonce_hi : beF w.t 7 16 = w.nonce_hi                      -- 235
  nonce_lo : beF w.t 23 16 = w.nonce_lo                     -- 236
  prefix_own : w.t 39 = 4                                   -- 237
  prefix_partner : w.t 104 = 4                              -- 238
  sr_eq : beF w.t 169 4 = ((w.sr : Nat) : F)                -- 239
  sr_const : w.sr = SR                                      -- 240
  delta : beF w.t 277 2 = ((DELTA : Nat) : F)               -- 241
  code : ∀ i, i < 32 → w.t (279 + i) = w.code i             -- 242-244
  limb_a : IsBE 16 (w.issuer 0) w.a                         -- 270 → 187
  limb_b : IsBE 16 (w.issuer 1) w.b                         -- 270 → 188
  limb_c : IsBE 16 (w.issuer 2) w.c                         -- 270 → 189
  limb_d : IsBE 16 (w.issuer 3) w.d                         -- 270 → 190
  expiry : w.valid_at ≤ asU64 (beF w.exp 0 8)               -- 272-273
  x_ne : beF w.t 40 16 ≠ beF w.t 105 16 ∨ beF w.t 56 16 ≠ beF w.t 121 16 -- 275-277
  rr_be : IsBE 32 (beF w.t 177 32) w.back                   -- 279-280
  rr_eq : ∀ i, i < 32 → w.back i = w.t (177 + i)            -- 281-283

/-- `(ix, iy) = unpack_issuer(issuer)`, line 270, as the byte lists passed to line 271. -/
def issuerX (w : Inputs) : List Nat := slice (unpackXY w.a w.b) 0 32
def issuerY (w : Inputs) : List Nat := slice (unpackXY w.c w.d) 0 32

/-- All of `check_signed`. -/
structure CheckSigned (C : Crypto) (w : Inputs) : Prop where
  bytes : ByteChecks w
  /-- line 253, with `digest` from line 246 and `px`, `py` from lines 247-252 -/
  dev_sig : C.verify (slice (pxOf w.t) 0 32) (slice (pyOf w.t) 0 32) (slice w.sig 0 64) (C.sha256 (slice w.t 0 311))
  /-- line 271, with `cd` from line 269 and `c` from lines 255-268 -/
  cred_sig : C.verify (issuerX w) (issuerY w) (slice w.csig 0 64) (C.sha256 (slice (credOf w.t w.exp w.hold) 0 111))

/-- `struct Signed`, lines 200-209. -/
structure Signed where
  rec_root : F
  a_self : F
  p_self : F
  a_partner : F
  p_partner : F
  half : F
  x_own : F × F
  x_partner : F × F
  deriving DecidableEq

/-- What `check_signed` returns, lines 275-276 and 279-298. -/
def checkSignedOut (t : Nat → Nat) (role_b : Bool) : Signed where
  rec_root := beF t 177 32
  a_self := beF t 269 4
  p_self := beF t 269 4 - signed32 t 233
  a_partner := beF t 269 4 + (1 - 2 * boolF role_b) * signed32 t 173
  p_partner := beF t 273 4
  half := signed32 t 173
  x_own := (beF t 40 16, beF t 56 16)
  x_partner := (beF t 105 16, beF t 121 16)

/-! ## Theorems: the asserted bytes -/

theorem beNat2_expand (t : Nat → Nat) (off : Nat) : beNat t off 2 = t off * 256 + t (off + 1) := by
  simp [beNat]

/-- **The fixed bytes are fixed.** If the checks pass, the transcript starts with `POPT`, version 2, the role byte is
`'A'` or `'B'` matching the public `role_b`, the attempt byte is the public attempt, both keys start with the `04`
prefix, the sample rate bytes are 48000, delta is 96 and the 32 code bytes are the `code` argument. These are facts
about the actual bytes, not field elements. -/
theorem asserted_bytes (w : Inputs) (h : ByteChecks w) (ty : Types w) :
    w.t 0 = 0x50 ∧ w.t 1 = 0x4f ∧ w.t 2 = 0x50 ∧ w.t 3 = 0x54 ∧ w.t 4 = 2 ∧
    w.t 5 = (if w.role_b then 0x42 else 0x41) ∧ w.t 6 = w.attempt ∧ w.t 39 = 4 ∧ w.t 104 = 4 ∧
    w.sr = 48000 ∧ beNat w.t 169 4 = 48000 ∧
    w.t 169 = 0 ∧ w.t 170 = 0 ∧ w.t 171 = 0xbb ∧ w.t 172 = 0x80 ∧
    beNat w.t 277 2 = 96 ∧ w.t 277 = 0 ∧ w.t 278 = 96 ∧
    (∀ i, i < 32 → w.t (279 + i) = w.code i) := by
  have ht := ty.t_ok
  have hsr : w.sr = 48000 := h.sr_const
  have e1 : beF w.t 169 4 = ((48000 : Nat) : F) := by rw [h.sr_eq, hsr]
  have hs : beNat w.t 169 4 = 48000 :=
    beNat_of_beF (by norm_num) (fun i hi => ht _ (by omega)) (by unfold p; norm_num) e1
  have hd : beNat w.t 277 2 = 96 :=
    beNat_of_beF (by norm_num) (fun i hi => ht _ (by omega)) (by unfold p; norm_num) h.delta
  have ex := beNat4_expand w.t 169
  have ex2 := beNat2_expand w.t 277
  have b0 := ht 169 (by norm_num)
  have b1 := ht 170 (by norm_num)
  have b2 := ht 171 (by norm_num)
  have b3 := ht 172 (by norm_num)
  have b4 := ht 277 (by norm_num)
  have b5 := ht 278 (by norm_num)
  norm_num only at ex ex2
  have hrole : w.t 5 = (if w.role_b then 0x42 else 0x41) := by
    rw [h.role]; cases w.role_b <;> simp
  refine ⟨h.magic0, h.magic1, h.magic2, h.magic3, h.version, hrole, h.attempt, h.prefix_own, h.prefix_partner,
    hsr, hs, by omega, by omega, by omega, by omega, hd, by omega, by omega, h.code⟩

/-- Role byte and `role_b` determine each other, so a transcript signed for one role can't be used for the other. -/
theorem role_iff (w : Inputs) (h : ByteChecks w) : w.role_b = true ↔ w.t 5 = 0x42 := by
  have := h.role
  cases hb : w.role_b <;> simp_all

/-! ## Theorems: nonce, key limbs, no wraparound -/

/-- **The nonce limbs don't wrap.** The two public nonce limbs are the two halves of the 32 signed nonce bytes, as true
numbers below `2^128`. A public limb at `2^128` or above can't satisfy the circuit. -/
theorem nonce_limbs (w : Inputs) (h : ByteChecks w) (ty : Types w) :
    w.nonce_hi.val = beNat w.t 7 16 ∧ w.nonce_hi.val < 2 ^ 128 ∧
    w.nonce_lo.val = beNat w.t 23 16 ∧ w.nonce_lo.val < 2 ^ 128 ∧
    beNat w.t 7 32 = w.nonce_hi.val * 2 ^ 128 + w.nonce_lo.val := by
  have ht := ty.t_ok
  have bh : ∀ i, i < 16 → w.t (7 + i) < 256 := fun i hi => ht _ (by omega)
  have bl : ∀ i, i < 16 → w.t (23 + i) < 256 := fun i hi => ht _ (by omega)
  have e1 : w.nonce_hi.val = beNat w.t 7 16 := by
    rw [← h.nonce_hi]; exact beF_val_win _ _ _ (by norm_num) bh
  have e2 : w.nonce_lo.val = beNat w.t 23 16 := by
    rw [← h.nonce_lo]; exact beF_val_win _ _ _ (by norm_num) bl
  have s := beNat_split w.t 7 16 16
  have e3 : (256:Nat) ^ 16 = 2 ^ 128 := by norm_num
  rw [e3] at s
  refine ⟨e1, by rw [e1]; exact beNat16_lt _ _ bh, e2, by rw [e2]; exact beNat16_lt _ _ bl, ?_⟩
  rw [e1, e2]; exact s

/-- **Same public nonce, same nonce bytes.** Two accepted transcripts with equal `nonce_hi` and `nonce_lo` carry the same
32 nonce bytes. -/
theorem nonce_determines_bytes (w w' : Inputs) (h : ByteChecks w) (h' : ByteChecks w') (ty : Types w) (ty' : Types w')
    (e1 : w.nonce_hi = w'.nonce_hi) (e2 : w.nonce_lo = w'.nonce_lo) :
    ∀ i, i < 32 → w.t (7 + i) = w'.t (7 + i) := by
  have ht := ty.t_ok
  have ht' := ty'.t_ok
  have n := nonce_limbs w h ty
  have n' := nonce_limbs w' h' ty'
  have inj1 := beNat_inj w.t w'.t 7 7 16 (fun i hi => ht _ (by omega)) (fun i hi => ht' _ (by omega))
    (by rw [← n.1, ← n'.1, e1])
  have inj2 := beNat_inj w.t w'.t 23 23 16 (fun i hi => ht _ (by omega)) (fun i hi => ht' _ (by omega))
    (by rw [← n.2.2.1, ← n'.2.2.1, e2])
  intro i hi
  by_cases hi16 : i < 16
  · exact inj1 i hi16
  · have := inj2 (i - 16) (by omega)
    have e : 23 + (i - 16) = 7 + i := by omega
    rwa [e] at this

/-- **The key limbs don't wrap.** Each 16-byte limb of own X and partner X is a true number below `2^128`, and own X as a
256-bit number is `x_own[0] * 2^128 + x_own[1]`; the same for partner X. -/
theorem x_limbs (t : Nat → Nat) (ht : bytesOK t) :
    (beF t 40 16).val = beNat t 40 16 ∧ beNat t 40 16 < 2 ^ 128 ∧
    (beF t 56 16).val = beNat t 56 16 ∧ beNat t 56 16 < 2 ^ 128 ∧
    (beF t 105 16).val = beNat t 105 16 ∧ beNat t 105 16 < 2 ^ 128 ∧
    (beF t 121 16).val = beNat t 121 16 ∧ beNat t 121 16 < 2 ^ 128 ∧
    beNat t 40 32 = (beF t 40 16).val * 2 ^ 128 + (beF t 56 16).val ∧
    beNat t 105 32 = (beF t 105 16).val * 2 ^ 128 + (beF t 121 16).val := by
  have b : ∀ off, off + 16 ≤ 311 → ∀ i, i < 16 → t (off + i) < 256 := fun off ho i hi => ht _ (by omega)
  have v : ∀ off, off + 16 ≤ 311 → (beF t off 16).val = beNat t off 16 :=
    fun off ho => beF_val_win _ _ _ (by norm_num) (b off ho)
  have e3 : (256:Nat) ^ 16 = 2 ^ 128 := by norm_num
  have s1 := beNat_split t 40 16 16
  have s2 := beNat_split t 105 16 16
  rw [e3] at s1 s2
  refine ⟨v 40 (by norm_num), beNat16_lt _ _ (b 40 (by norm_num)), v 56 (by norm_num),
    beNat16_lt _ _ (b 56 (by norm_num)), v 105 (by norm_num), beNat16_lt _ _ (b 105 (by norm_num)),
    v 121 (by norm_num), beNat16_lt _ _ (b 121 (by norm_num)), ?_, ?_⟩
  · rw [v 40 (by norm_num), v 56 (by norm_num)]; exact s1
  · rw [v 105 (by norm_num), v 121 (by norm_num)]; exact s2

/-- **Own X differs from partner X, exactly.** The limb check (line 277) passes exactly when the 32 bytes of own X and
partner X differ somewhere. It says nothing about Y. -/
theorem x_differ_iff (t : Nat → Nat) (ht : bytesOK t) :
    (beF t 40 16 ≠ beF t 105 16 ∨ beF t 56 16 ≠ beF t 121 16) ↔ ∃ i, i < 32 ∧ t (40 + i) ≠ t (105 + i) := by
  constructor
  · intro h
    by_contra hc
    push_neg at hc
    rcases h with h | h
    · refine h ?_
      rw [beF_eq, beF_eq, beNat_congr t t 40 105 16 (fun i hi => hc i (by omega))]
    · refine h ?_
      rw [beF_eq, beF_eq, beNat_congr t t 56 121 16 (fun i hi => by
        have := hc (16 + i) (by omega)
        have e1 : 40 + (16 + i) = 56 + i := by omega
        have e2 : 105 + (16 + i) = 121 + i := by omega
        rwa [e1, e2] at this)]
  · rintro ⟨i, hi, hne⟩
    by_contra hc
    push_neg at hc
    obtain ⟨h1, h2⟩ := hc
    have b : ∀ off, off + 16 ≤ 311 → ∀ i, i < 16 → t (off + i) < 256 := fun off ho i hi => ht _ (by omega)
    have v : ∀ off, off + 16 ≤ 311 → (beF t off 16).val = beNat t off 16 :=
      fun off ho => beF_val_win _ _ _ (by norm_num) (b off ho)
    have n1 : beNat t 40 16 = beNat t 105 16 := by
      rw [← v 40 (by norm_num), ← v 105 (by norm_num), h1]
    have n2 : beNat t 56 16 = beNat t 121 16 := by
      rw [← v 56 (by norm_num), ← v 121 (by norm_num), h2]
    have i1 := beNat_inj t t 40 105 16 (b 40 (by norm_num)) (b 105 (by norm_num)) n1
    have i2 := beNat_inj t t 56 121 16 (b 56 (by norm_num)) (b 121 (by norm_num)) n2
    apply hne
    by_cases h16 : i < 16
    · exact i1 i h16
    · have := i2 (i - 16) (by omega)
      have e1 : 56 + (i - 16) = 40 + i := by omega
      have e2 : 121 + (i - 16) = 105 + i := by omega
      rwa [e1, e2] at this

/-! ## Theorems: `rec_root` -/

/-- **`rec_root` is canonical, if `to_be_bytes` is.** The 32 signed bytes, read as a true number, are the canonical value
of the field element the circuit carries forward, so that number is below `p`. Rests on `IsBE 32`, which is trusted. -/
theorem rec_root_canonical (w : Inputs) (h : ByteChecks w) :
    beNat w.t 177 32 = (beF w.t 177 32).val ∧ beNat w.t 177 32 < p := by
  have e : beNat w.t 177 32 = beNat w.back 0 32 :=
    beNat_congr _ _ 177 0 32 (fun i hi => by rw [Nat.zero_add, h.rr_eq i hi])
  have e2 : beNat w.t 177 32 = (beF w.t 177 32).val := e.trans h.rr_be.2
  exact ⟨e2, by rw [e2]; exact ZMod.val_lt _⟩

/-- **One `rec_root`, one byte string.** Two accepted transcripts with the same `rec_root` field element carry the same 32
root bytes. -/
theorem rec_root_injective (w w' : Inputs) (h : ByteChecks w) (h' : ByteChecks w') (ty : Types w) (ty' : Types w')
    (e : beF w.t 177 32 = beF w'.t 177 32) : ∀ i, i < 32 → w.t (177 + i) = w'.t (177 + i) := by
  have ht := ty.t_ok
  have ht' := ty'.t_ok
  refine beNat_inj _ _ 177 177 32 (fun i hi => ht _ (by omega)) (fun i hi => ht' _ (by omega)) ?_
  rw [(rec_root_canonical w h).1, (rec_root_canonical w' h').1, e]

/-- `beF32_wraps`'s witness, as a number: the 32 bytes of `pBytes` are `p`. -/
theorem beNat_pBytes : beNat pBytes 177 32 = p := by
  unfold pBytes p; decide

/-- **The wrapped root is rejected.** The bytes of `p` read as the field element 0 (`beF32_wraps`), the same as 32 zero
bytes. With a canonical `to_be_bytes`, no output can match them. -/
theorem wrapped_root_rejected (back : Nat → Nat) :
    ¬ (IsBE 32 (beF pBytes 177 32) back ∧ ∀ i, i < 32 → back i = pBytes (177 + i)) := by
  rintro ⟨h1, h2⟩
  have e : beNat pBytes 177 32 = beNat back 0 32 :=
    beNat_congr _ _ 177 0 32 (fun i hi => by rw [Nat.zero_add, h2 i hi])
  have e2 := e.trans h1.2
  rw [beNat_pBytes] at e2
  have := ZMod.val_lt (beF pBytes 177 32)
  omega

/-- **Canonicality is what closes the alias.** If `to_be_bytes` only promised "bytes that recompose to the value", the
wrapped bytes of `p` would pass lines 280-283, with the circuit carrying 0 and the transcript saying `p`. So the rejection
above rests entirely on Noir's `to_be_bytes::<32>` checking against the modulus. -/
theorem alias_without_canonical :
    let back : Nat → Nat := fun i => pBytes (177 + i)
    (∀ i, i < 32 → back i < 256) ∧ beF back 0 32 = beF pBytes 177 32 ∧ (∀ i, i < 32 → back i = pBytes (177 + i)) ∧
      beF pBytes 177 32 = 0 ∧ pBytes 177 ≠ 0 := by
  intro back
  have h0 : beF pBytes 177 32 = 0 := by rw [beF_eq, beNat_pBytes]; simp
  have hb : beF back 0 32 = beF pBytes 177 32 := by
    rw [beF_eq, beF_eq, beNat_congr back pBytes 0 177 32 (fun i _ => by simp [back])]
  exact ⟨fun i _ => Nat.mod_lt _ (by norm_num), hb, fun _ _ => rfl, h0, beF32_wraps.2⟩

/-- `phone/main.nr` 33-36: the `code` argument is `code_commit.to_be_bytes()`. Then the transcript's 32 code bytes are the
big-endian encoding of the public `code_commit`. What `code_commit` commits to is block H. -/
theorem code_commit_signed (w : Inputs) (h : ByteChecks w) (cc : F) (hcc : IsBE 32 cc w.code) :
    beNat w.t 279 32 = cc.val ∧ beF w.t 279 32 = cc := by
  have e : beNat w.t 279 32 = beNat w.code 0 32 :=
    beNat_congr _ _ 279 0 32 (fun i hi => by rw [Nat.zero_add]; exact h.code i hi)
  have e2 := e.trans hcc.2
  refine ⟨e2, ?_⟩
  rw [beF_eq, e2]
  exact ZMod.natCast_zmod_val cc

/-! ## Theorems: expiry -/

theorem expiry_exact (e : Nat → Nat) (he : ∀ i, i < 8 → e i < 256) :
    asU64 (beF e 0 8) = beNat e 0 8 := by
  have hb : ∀ i, i < 8 → e (0 + i) < 256 := fun i hi => by rw [Nat.zero_add]; exact he i hi
  have hl := beNat_lt_win e 0 8 hb
  unfold asU64
  rw [beF_val_win e 0 8 (by norm_num) hb]
  apply Nat.mod_eq_of_lt
  norm_num at hl ⊢; exact hl

/-- **Expiry is a true 64-bit comparison.** `be_f(exp, 0, 8) as u64` loses nothing, so lines 272-273 say exactly
"`valid_at` is at or before the 8 signed expiry bytes, read as a whole number". -/
theorem expiry_iff (e : Nat → Nat) (he : ∀ i, i < 8 → e i < 256) (valid_at : Nat) :
    valid_at ≤ asU64 (beF e 0 8) ↔ valid_at ≤ beNat e 0 8 := by
  rw [expiry_exact e he]

/-! ## Theorems: `unpack_issuer` -/

/-- **The issuer key is the public limbs.** Each limb is below `2^128`, or the circuit has no solution. Issuer X and Y as
32-byte values are `issuer[0] * 2^128 + issuer[1]` and `issuer[2] * 2^128 + issuer[3]`. For limbs in range this rests
only on "bytes that recompose" (`isBE_of_recompose`), not on any canonicality. -/
theorem unpack_issuer_spec (w : Inputs) (h : ByteChecks w) :
    (w.issuer 0).val < 2 ^ 128 ∧ (w.issuer 1).val < 2 ^ 128 ∧ (w.issuer 2).val < 2 ^ 128 ∧ (w.issuer 3).val < 2 ^ 128 ∧
    issuerX w = slice w.a 0 16 ++ slice w.b 0 16 ∧ issuerY w = slice w.c 0 16 ++ slice w.d 0 16 ∧
    beNat (unpackXY w.a w.b) 0 32 = (w.issuer 0).val * 2 ^ 128 + (w.issuer 1).val ∧
    beNat (unpackXY w.c w.d) 0 32 = (w.issuer 2).val * 2 ^ 128 + (w.issuer 3).val := by
  have l : ∀ (x : F) (b : Nat → Nat), IsBE 16 x b → x.val < 2 ^ 128 := by
    intro x b hb
    rw [← hb.2]
    exact beNat16_lt _ _ (isBE_bytes hb)
  refine ⟨l _ _ h.limb_a, l _ _ h.limb_b, l _ _ h.limb_c, l _ _ h.limb_d, unpack_slice _ _, unpack_slice _ _, ?_, ?_⟩
  · rw [unpack_value, h.limb_a.2, h.limb_b.2]
  · rw [unpack_value, h.limb_c.2, h.limb_d.2]

/-- The limbs fix the issuer key bytes: no two different keys pass for one public `issuer`. -/
theorem issuer_key_unique (w w' : Inputs) (h : ByteChecks w) (h' : ByteChecks w')
    (e : ∀ i, w.issuer i = w'.issuer i) : issuerX w = issuerX w' ∧ issuerY w = issuerY w' := by
  have u : ∀ {x : F} {b b' : Nat → Nat}, IsBE 16 x b → IsBE 16 x b' → slice b 0 16 = slice b' 0 16 := by
    intro x b b' hb hb'
    exact slice_congr (fun i hi => by rw [Nat.zero_add]; exact isBE_unique hb hb' i hi)
  have ea := u h.limb_a (e 0 ▸ h'.limb_a)
  have eb := u h.limb_b (e 1 ▸ h'.limb_b)
  have ec := u h.limb_c (e 2 ▸ h'.limb_c)
  have ed := u h.limb_d (e 3 ▸ h'.limb_d)
  simp only [issuerX, issuerY, unpack_slice, ea, eb, ec, ed, and_self]

/-! ## Theorems: `Signed` and the spec offsets -/

/-- **Every `Signed` field is the bytes at the spec offset.** Each field of the output is the read the spec names, at the
offset the layout computes, and equals what `PartnerGlue.lean` calls it, so `phone_core_glue` is about these same numbers.
The integer lines say each field element is the cast of an exact integer. The sizes of those integers aren't stated here:
`PartnerGlue.signed_ranges` bounds `a_self` and `p_partner` to u32, `half` and `self_os_delta` to int32, and
`a_partner - a_self` to within `2^31`. -/
theorem signed_fields (t : Nat → Nat) (role_b : Bool) (ht : bytesOK t) :
    let s := checkSignedOut t role_b
    s.rec_root = beF t Layout.off_rec_root 32 ∧
    s.a_self = beF t Layout.off_a_self 4 ∧
    s.p_partner = beF t Layout.off_p_partner 4 ∧
    s.half = signed32 t Layout.off_half ∧
    s.p_self = beF t Layout.off_a_self 4 - signed32 t Layout.off_self_os_delta ∧
    s.x_own = (beF t (Layout.off_pk_self + 1) 16, beF t (Layout.off_pk_self + 17) 16) ∧
    s.x_partner = (beF t (Layout.off_pk_partner + 1) 16, beF t (Layout.off_pk_partner + 17) 16) ∧
    s.a_self = aSelfF t ∧ s.p_self = pSelfF t ∧ s.a_partner = aPartnerF t role_b ∧
    s.p_partner = pPartnerF t ∧ s.half = halfF t ∧
    s.a_self = (aSelf t : F) ∧ s.p_partner = (pPartner t : F) ∧ s.half = (half t : F) ∧
    s.p_self = (pSelf t : F) ∧ s.a_partner = (aPartner t role_b : F) := by
  have hc := signed_casts t role_b ht
  exact ⟨rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, hc.1, hc.2.1, hc.2.2.1, hc.2.2.2.2.1,
    hc.2.2.2.2.2⟩

/-! ## Theorems: the signatures -/

/-- Own key X and Y, as the transcript carries them. -/
def ownX (w : Inputs) : List Nat := slice w.t 40 32
def ownY (w : Inputs) : List Nat := slice w.t 72 32

/-- The credential message the circuit builds. -/
def credList (w : Inputs) : List Nat := credMsg (ownX w) (ownY w) (slice w.exp 0 8) (slice w.hold 0 32)

/-- **One key.** The key the device signature is checked against (line 253) and the key inside the credential the issuer's
signature is checked over (line 271) are the same 64 transcript bytes. No crypto assumption: this is only about which
bytes go where. -/
theorem one_key (C : Crypto) (w : Inputs) (h : CheckSigned C w) :
    C.verify (ownX w) (ownY w) (slice w.sig 0 64) (C.sha256 (slice w.t 0 311)) ∧
    C.verify (issuerX w) (issuerY w) (slice w.csig 0 64) (C.sha256 (credList w)) := by
  have d := h.dev_sig
  have c := h.cred_sig
  rw [px_slice, py_slice] at d
  rw [cred_list] at c
  exact ⟨d, c⟩

/-- `Msgs qx qy m`: the holder of key `(qx, qy)` really signed `m`. Abstract: it is whatever history you are reasoning
about. -/
abbrev SignedSet := List Nat → List Nat → List Nat → Prop

/-- **Named hypothesis: ECDSA unforgeability, for one signature on one digest.** If THIS signature verifies on THIS digest
under this key, the digest is the hash of a message the key's holder signed. In other words, this witness isn't a forgery.

It is deliberately not "for every signature and digest". Under a valid ECDSA key every digest has some verifying signature
as a mathematical object; forging means finding one. So the "for every" version needs `Msgs` to hold one preimage of each
digest that has a verifying signature, which under such a key is every digest. No real signing history is that big, so that
version is false for any `Msgs` that means one. -/
def Unforgeable (C : Crypto) (Msgs : SignedSet) (qx qy s d : List Nat) : Prop :=
  C.verify qx qy s d → ∃ m, Msgs qx qy m ∧ C.sha256 m = d

/-- **Named hypothesis: SHA-256 has no collision between `m` and what this key signed.** Deliberately this narrow: a
statement about every pair of lists would be false of real SHA-256. -/
def NoCollisionWith (C : Crypto) (Msgs : SignedSet) (qx qy m : List Nat) : Prop :=
  ∀ m', Msgs qx qy m' → C.sha256 m' = C.sha256 m → m' = m

theorem signed_of_verify (C : Crypto) (Msgs : SignedSet) (qx qy m s : List Nat)
    (hu : Unforgeable C Msgs qx qy s (C.sha256 m)) (hc : NoCollisionWith C Msgs qx qy m)
    (hv : C.verify qx qy s (C.sha256 m)) : Msgs qx qy m := by
  obtain ⟨m', hm', hd⟩ := hu hv
  rwa [hc m' hm' hd] at hm'

/-- **The chain of trust, under named assumptions.** Suppose the circuit accepts, and:

1. the witness's credential signature isn't a forgery (`hI`), and SHA-256 has no collision with this credential among what
   the issuer signed (`hIc`);
2. if the issuer really credentialed this key, the witness's transcript signature isn't a forgery (`hD`), and no collision
   with this transcript among what that key signed (`hDc`).

Then the issuer really signed "SBcred3, this X and Y, this expiry, this holder commit", and the holder of that same key
really signed this exact 311-byte transcript.

The issuer here is whatever the public `issuer` limbs name, so the verifier has to pin it. What the issuer's signature
means about the device is outside the circuit. `hD` is where "the issuer only credentials keys held in real hardware"
would live. A signing device can sign anything, so this says who signed, not that what they signed is true.

Honest size of this result: the cryptography isn't derived here, it's assumed. Once the circuit accepts, `hI` says the same
thing as "some message the issuer signed hashes to this digest", and adding `hIc` turns that into the first half of the
conclusion. `hD` and `hDc` do the same for the second half (`chain_of_trust_size`). The real content is which message and which
key those are: the 111 bytes the loops wrote, and the same 64 transcript bytes in both signatures (`one_key`). -/
theorem chain_of_trust(C : Crypto) (w : Inputs) (Msgs : SignedSet) (h : CheckSigned C w)
    (hI : Unforgeable C Msgs (issuerX w) (issuerY w) (slice w.csig 0 64) (C.sha256 (credList w)))
    (hIc : NoCollisionWith C Msgs (issuerX w) (issuerY w) (credList w))
    (hD : Msgs (issuerX w) (issuerY w) (credList w) →
      Unforgeable C Msgs (ownX w) (ownY w) (slice w.sig 0 64) (C.sha256 (slice w.t 0 311)))
    (hDc : NoCollisionWith C Msgs (ownX w) (ownY w) (slice w.t 0 311)) :
    Msgs (issuerX w) (issuerY w) (credList w) ∧ Msgs (ownX w) (ownY w) (slice w.t 0 311) := by
  obtain ⟨d, c⟩ := one_key C w h
  have hc := signed_of_verify C Msgs _ _ _ _ hI hIc c
  exact ⟨hc, signed_of_verify C Msgs _ _ _ _ (hD hc) hDc d⟩

/-- **How much `chain_of_trust` assumes.** When the signature verifies, `Unforgeable` is the same statement as "some message
this key signed hashes to this digest", and with `NoCollisionWith` that gives "this key signed this message". This holds for
both signatures, so the two hypotheses of each pair nearly restate that half of the conclusion. -/
theorem chain_of_trust_size (C : Crypto) (w : Inputs) (Msgs : SignedSet) (h : CheckSigned C w) :
    (Unforgeable C Msgs (issuerX w) (issuerY w) (slice w.csig 0 64) (C.sha256 (credList w)) ↔
      ∃ m, Msgs (issuerX w) (issuerY w) m ∧ C.sha256 m = C.sha256 (credList w)) ∧
    (NoCollisionWith C Msgs (issuerX w) (issuerY w) (credList w) →
      (∃ m, Msgs (issuerX w) (issuerY w) m ∧ C.sha256 m = C.sha256 (credList w)) →
      Msgs (issuerX w) (issuerY w) (credList w)) ∧
    (Unforgeable C Msgs (ownX w) (ownY w) (slice w.sig 0 64) (C.sha256 (slice w.t 0 311)) ↔
      ∃ m, Msgs (ownX w) (ownY w) m ∧ C.sha256 m = C.sha256 (slice w.t 0 311)) ∧
    (NoCollisionWith C Msgs (ownX w) (ownY w) (slice w.t 0 311) →
      (∃ m, Msgs (ownX w) (ownY w) m ∧ C.sha256 m = C.sha256 (slice w.t 0 311)) →
      Msgs (ownX w) (ownY w) (slice w.t 0 311)) := by
  obtain ⟨d, c⟩ := one_key C w h
  refine ⟨⟨fun hu => hu c, fun he _ => he⟩, ?_, ⟨fun hu => hu d, fun he _ => he⟩, ?_⟩
  · rintro hc ⟨m, hm, he⟩
    rwa [hc m hm he] at hm
  · rintro hc ⟨m, hm, he⟩
    rwa [hc m hm he] at hm

/-! ## Theorems: what is NOT checked -/

/-- Bytes that reach the proof only through `sha256(t)`: partner Y, the three time fields, `commit_hash`. -/
def digestOnly (i : Nat) : Prop :=
  (137 ≤ i ∧ i < 169) ∨ (209 ≤ i ∧ i < 233) ∨ (237 ≤ i ∧ i < 269)

/-- The `digestOnly` ranges are exactly the fields the layout names. -/
theorem digestOnly_is_fields :
    Layout.off_pk_partner + 33 = 137 ∧ Layout.off_pk_partner + 65 = 169 ∧
    Layout.off_play_frame = 209 ∧ Layout.off_self_os_delta = 233 ∧
    Layout.off_commit_hash = 237 ∧ Layout.off_a_self = 269 := by
  decide

/-- **88 transcript bytes are unconstrained, apart from the device's signature.** Take an accepted witness. Change any of
partner Y (137-168), the play and capture times (209-232), and `commit_hash` (237-268) to any other bytes. If the device key
signs the new transcript, the circuit still accepts, and `check_signed` returns exactly the same `Signed`. (`t'` being bytes
is Noir's type rule, `Types.t_ok`. This theorem doesn't use it.)

So the circuit doesn't tie `commit_hash` to a commitment, doesn't check any timestamp and doesn't look at partner Y. Those
are true only as far as the signer is honest. -/
theorem digest_only_free (C : Crypto) (w : Inputs) (t' sig' : Nat → Nat) (h : CheckSigned C w)
    (hagree : ∀ i, i < 311 → ¬ digestOnly i → t' i = w.t i)
    (hsig : C.verify (slice t' 40 32) (slice t' 72 32) (slice sig' 0 64) (C.sha256 (slice t' 0 311))) :
    CheckSigned C { w with t := t', sig := sig' } ∧ checkSignedOut t' w.role_b = checkSignedOut w.t w.role_b := by
  have a : ∀ off n, (∀ i, i < n → off + i < 311 ∧ ¬ digestOnly (off + i)) → ∀ i, i < n → t' (off + i) = w.t (off + i) :=
    fun off n hw i hi => hagree _ (hw i hi).1 (hw i hi).2
  have rr : beF t' 177 32 = beF w.t 177 32 := beF_congr _ _ _ _ (a _ _ (fun i hi => by unfold digestOnly; omega))
  have as : beF t' 269 4 = beF w.t 269 4 := beF_congr _ _ _ _ (a _ _ (fun i hi => by unfold digestOnly; omega))
  have pp : beF t' 273 4 = beF w.t 273 4 := beF_congr _ _ _ _ (a _ _ (fun i hi => by unfold digestOnly; omega))
  have x0 : beF t' 40 16 = beF w.t 40 16 := beF_congr _ _ _ _ (a _ _ (fun i hi => by unfold digestOnly; omega))
  have x1 : beF t' 56 16 = beF w.t 56 16 := beF_congr _ _ _ _ (a _ _ (fun i hi => by unfold digestOnly; omega))
  have y0 : beF t' 105 16 = beF w.t 105 16 := beF_congr _ _ _ _ (a _ _ (fun i hi => by unfold digestOnly; omega))
  have y1 : beF t' 121 16 = beF w.t 121 16 := beF_congr _ _ _ _ (a _ _ (fun i hi => by unfold digestOnly; omega))
  have hf : signed32 t' 173 = signed32 w.t 173 := signed32_congr _ _ _ (a _ _ (fun i hi => by unfold digestOnly; omega))
  have sd : signed32 t' 233 = signed32 w.t 233 := signed32_congr _ _ _ (a _ _ (fun i hi => by unfold digestOnly; omega))
  have hn : beF t' 7 16 = beF w.t 7 16 := beF_congr _ _ _ _ (a _ _ (fun i hi => by unfold digestOnly; omega))
  have hl : beF t' 23 16 = beF w.t 23 16 := beF_congr _ _ _ _ (a _ _ (fun i hi => by unfold digestOnly; omega))
  have hs : beF t' 169 4 = beF w.t 169 4 := beF_congr _ _ _ _ (a _ _ (fun i hi => by unfold digestOnly; omega))
  have hd : beF t' 277 2 = beF w.t 277 2 := beF_congr _ _ _ _ (a _ _ (fun i hi => by unfold digestOnly; omega))
  have one : ∀ i, i < 311 → ¬ digestOnly i → t' i = w.t i := hagree
  have h1 := h.bytes
  have hb : ByteChecks { w with t := t', sig := sig' } :=
    { magic0 := (one 0 (by norm_num) (by unfold digestOnly; omega)).trans h1.magic0
      magic1 := (one 1 (by norm_num) (by unfold digestOnly; omega)).trans h1.magic1
      magic2 := (one 2 (by norm_num) (by unfold digestOnly; omega)).trans h1.magic2
      magic3 := (one 3 (by norm_num) (by unfold digestOnly; omega)).trans h1.magic3
      version := (one 4 (by norm_num) (by unfold digestOnly; omega)).trans h1.version
      role := (one 5 (by norm_num) (by unfold digestOnly; omega)).trans h1.role
      attempt := (one 6 (by norm_num) (by unfold digestOnly; omega)).trans h1.attempt
      nonce_hi := hn.trans h1.nonce_hi
      nonce_lo := hl.trans h1.nonce_lo
      prefix_own := (one 39 (by norm_num) (by unfold digestOnly; omega)).trans h1.prefix_own
      prefix_partner := (one 104 (by norm_num) (by unfold digestOnly; omega)).trans h1.prefix_partner
      sr_eq := hs.trans h1.sr_eq
      sr_const := h1.sr_const
      delta := hd.trans h1.delta
      code := fun i hi => (one _ (by omega) (by unfold digestOnly; omega)).trans (h1.code i hi)
      limb_a := h1.limb_a
      limb_b := h1.limb_b
      limb_c := h1.limb_c
      limb_d := h1.limb_d
      expiry := h1.expiry
      x_ne := by
        show beF t' 40 16 ≠ beF t' 105 16 ∨ beF t' 56 16 ≠ beF t' 121 16
        rw [x0, x1, y0, y1]; exact h1.x_ne
      rr_be := by
        show IsBE 32 (beF t' 177 32) w.back
        rw [rr]; exact h1.rr_be
      rr_eq := fun i hi => (h1.rr_eq i hi).trans (one _ (by omega) (by unfold digestOnly; omega)).symm }
  have hcred : slice (credOf t' w.exp w.hold) 0 111 = slice (credOf w.t w.exp w.hold) 0 111 := by
    rw [cred_list, cred_list,
      slice_congr (f := t') (g := w.t) (off := 40) (off' := 40) (n := 32) (a _ _ (fun i hi => by unfold digestOnly; omega)),
      slice_congr (f := t') (g := w.t) (off := 72) (off' := 72) (n := 32) (a _ _ (fun i hi => by unfold digestOnly; omega))]
  refine ⟨⟨hb, ?_, ?_⟩, ?_⟩
  · show C.verify (slice (pxOf t') 0 32) (slice (pyOf t') 0 32) (slice sig' 0 64) (C.sha256 (slice t' 0 311))
    rw [px_slice, py_slice]; exact hsig
  · show C.verify (issuerX w) (issuerY w) (slice w.csig 0 64) (C.sha256 (slice (credOf t' w.exp w.hold) 0 111))
    rw [hcred]; exact h.cred_sig
  · simp only [checkSignedOut, rr, as, pp, x0, x1, y0, y1, hf, sd]

/-- The only transcript bytes the non-signature asserts read at all, other than comparing the X limbs: 0-39, 104, 169-172,
177-208, 277-310. That is 111 bytes. Being read doesn't fix a byte: the 32 at 177-208 only have to be below `p`. -/
def readByChecks (i : Nat) : Prop :=
  i < 40 ∨ i = 104 ∨ (169 ≤ i ∧ i < 173) ∨ (177 ≤ i ∧ i < 209) ∨ (277 ≤ i ∧ i < 311)

/-- **Apart from the signatures, only 111 transcript bytes are read, plus "X differs".** Take a witness passing every
non-signature check. Rewrite the other 200 bytes to any other bytes, as long as own X and partner X still differ. All
non-signature checks still pass. This shows the other 200 are free. It doesn't show the 111 are fixed: `asserted_bytes` and
`nonce_limbs` say what's fixed, and `rec_root`'s 32 are only constrained to be below `p`.

So in this block there's no constraint at all on `half`, `a_self`, `p_partner`, `self_os_delta` (`phone_core` constrains
those later), and none on own Y or partner X and Y other than X differing. In particular, no check says either key is a
curve point: for the own key that's left to the ECDSA blackbox, and for the partner key to nothing. -/
theorem only_read_bytes_matter (w : Inputs) (t' : Nat → Nat) (h : ByteChecks w) (ht' : bytesOK t')
    (hagree : ∀ i, readByChecks i → t' i = w.t i) (hx : ∃ i, i < 32 ∧ t' (40 + i) ≠ t' (105 + i)) :
    ByteChecks { w with t := t' } := by
  have a : ∀ off n, (∀ i, i < n → readByChecks (off + i)) → ∀ i, i < n → t' (off + i) = w.t (off + i) :=
    fun off n hw i hi => hagree _ (hw i hi)
  have rr : beF t' 177 32 = beF w.t 177 32 := beF_congr _ _ _ _ (a _ _ (fun i hi => by unfold readByChecks; omega))
  have hn : beF t' 7 16 = beF w.t 7 16 := beF_congr _ _ _ _ (a _ _ (fun i hi => by unfold readByChecks; omega))
  have hl : beF t' 23 16 = beF w.t 23 16 := beF_congr _ _ _ _ (a _ _ (fun i hi => by unfold readByChecks; omega))
  have hs : beF t' 169 4 = beF w.t 169 4 := beF_congr _ _ _ _ (a _ _ (fun i hi => by unfold readByChecks; omega))
  have hd : beF t' 277 2 = beF w.t 277 2 := beF_congr _ _ _ _ (a _ _ (fun i hi => by unfold readByChecks; omega))
  have one : ∀ i, readByChecks i → t' i = w.t i := hagree
  exact
    { magic0 := (one 0 (by unfold readByChecks; omega)).trans h.magic0
      magic1 := (one 1 (by unfold readByChecks; omega)).trans h.magic1
      magic2 := (one 2 (by unfold readByChecks; omega)).trans h.magic2
      magic3 := (one 3 (by unfold readByChecks; omega)).trans h.magic3
      version := (one 4 (by unfold readByChecks; omega)).trans h.version
      role := (one 5 (by unfold readByChecks; omega)).trans h.role
      attempt := (one 6 (by unfold readByChecks; omega)).trans h.attempt
      nonce_hi := hn.trans h.nonce_hi
      nonce_lo := hl.trans h.nonce_lo
      prefix_own := (one 39 (by unfold readByChecks; omega)).trans h.prefix_own
      prefix_partner := (one 104 (by unfold readByChecks; omega)).trans h.prefix_partner
      sr_eq := hs.trans h.sr_eq
      sr_const := h.sr_const
      delta := hd.trans h.delta
      code := fun i hi => (one _ (by unfold readByChecks; omega)).trans (h.code i hi)
      limb_a := h.limb_a
      limb_b := h.limb_b
      limb_c := h.limb_c
      limb_d := h.limb_d
      expiry := h.expiry
      x_ne := (x_differ_iff t' ht').mpr hx
      rr_be := by
        show IsBE 32 (beF t' 177 32) w.back
        rw [rr]; exact h.rr_be
      rr_eq := fun i hi => (h.rr_eq i hi).trans (one _ (by unfold readByChecks; omega)).symm }

/-- **The holder commit is never opened.** If the issuer signed a credential with a different `hold`, the proof goes through
with that one. Only the credential signature touches it. -/
theorem holder_commit_free (C : Crypto) (w : Inputs) (hold' csig' : Nat → Nat) (h : CheckSigned C w)
    (hsig : C.verify (issuerX w) (issuerY w) (slice csig' 0 64)
      (C.sha256 (slice (credOf w.t w.exp hold') 0 111))) :
    CheckSigned C { w with hold := hold', csig := csig' } :=
  { bytes :=
      { magic0 := h.bytes.magic0, magic1 := h.bytes.magic1, magic2 := h.bytes.magic2, magic3 := h.bytes.magic3,
        version := h.bytes.version, role := h.bytes.role, attempt := h.bytes.attempt,
        nonce_hi := h.bytes.nonce_hi, nonce_lo := h.bytes.nonce_lo, prefix_own := h.bytes.prefix_own,
        prefix_partner := h.bytes.prefix_partner, sr_eq := h.bytes.sr_eq, sr_const := h.bytes.sr_const,
        delta := h.bytes.delta, code := h.bytes.code, limb_a := h.bytes.limb_a, limb_b := h.bytes.limb_b,
        limb_c := h.bytes.limb_c, limb_d := h.bytes.limb_d, expiry := h.bytes.expiry, x_ne := h.bytes.x_ne,
        rr_be := h.bytes.rr_be, rr_eq := h.bytes.rr_eq }
    dev_sig := h.dev_sig
    cred_sig := hsig }

/-! ## The whole block in one statement -/

/-- What block A establishes, in true numbers and actual bytes. -/
structure BlockA (C : Crypto) (w : Inputs) : Prop where
  magic : w.t 0 = 0x50 ∧ w.t 1 = 0x4f ∧ w.t 2 = 0x50 ∧ w.t 3 = 0x54
  version : w.t 4 = 2
  role : w.t 5 = if w.role_b then 0x42 else 0x41
  attempt : w.t 6 = w.attempt
  sec1 : w.t 39 = 4 ∧ w.t 104 = 4
  sr : w.sr = 48000 ∧ beNat w.t 169 4 = 48000
  delta : beNat w.t 277 2 = 96
  code : ∀ i, i < 32 → w.t (279 + i) = w.code i
  nonce : w.nonce_hi.val = beNat w.t 7 16 ∧ w.nonce_hi.val < 2 ^ 128 ∧
    w.nonce_lo.val = beNat w.t 23 16 ∧ w.nonce_lo.val < 2 ^ 128
  rec_root : beNat w.t 177 32 = (beF w.t 177 32).val ∧ beNat w.t 177 32 < p
  expiry : w.valid_at ≤ beNat w.exp 0 8
  key_limbs : (beF w.t 40 16).val = beNat w.t 40 16 ∧ beNat w.t 40 16 < 2 ^ 128 ∧
    (beF w.t 56 16).val = beNat w.t 56 16 ∧ beNat w.t 56 16 < 2 ^ 128 ∧
    (beF w.t 105 16).val = beNat w.t 105 16 ∧ beNat w.t 105 16 < 2 ^ 128 ∧
    (beF w.t 121 16).val = beNat w.t 121 16 ∧ beNat w.t 121 16 < 2 ^ 128 ∧
    beNat w.t 40 32 = (beF w.t 40 16).val * 2 ^ 128 + (beF w.t 56 16).val ∧
    beNat w.t 105 32 = (beF w.t 105 16).val * 2 ^ 128 + (beF w.t 121 16).val
  x_differ : ∃ i, i < 32 ∧ w.t (40 + i) ≠ w.t (105 + i)
  issuer_limbs : (w.issuer 0).val < 2 ^ 128 ∧ (w.issuer 1).val < 2 ^ 128 ∧
    (w.issuer 2).val < 2 ^ 128 ∧ (w.issuer 3).val < 2 ^ 128
  issuer : beNat (unpackXY w.a w.b) 0 32 = (w.issuer 0).val * 2 ^ 128 + (w.issuer 1).val ∧
    beNat (unpackXY w.c w.d) 0 32 = (w.issuer 2).val * 2 ^ 128 + (w.issuer 3).val
  device_sig : C.verify (ownX w) (ownY w) (slice w.sig 0 64) (C.sha256 (slice w.t 0 311))
  credential_sig : C.verify (issuerX w) (issuerY w) (slice w.csig 0 64) (C.sha256 (credList w))

/-- **Block A, all together.** If `check_signed` accepts on inputs of the right Noir types, then every field of `BlockA` holds
of the actual bytes, with no wraparound: the fixed bytes are fixed, the nonce, own X, partner X and issuer limbs are true
128-bit numbers, `rec_root` is below `p` (given canonical `to_be_bytes`), the expiry comparison is true 64-bit, own X differs
from partner X, and one key both verified the transcript's signature and sits inside the credential the issuer's key
verified. The `Signed` output's integer ranges are separate: see `signed_fields`.

"Verified" means the opaque `verify` predicate holds. To get "really signed", add the named assumptions of
`chain_of_trust`. What this does not check is in the table at the top of this file. -/
theorem check_signed_sound (C : Crypto) (w : Inputs) (h : CheckSigned C w) (ty : Types w) : BlockA C w := by
  have a := asserted_bytes w h.bytes ty
  obtain ⟨m0, m1, m2, m3, ver, ro, at', s1, s2, sr1, sr2, _, _, _, _, dl, _, _, cd⟩ := a
  have n := nonce_limbs w h.bytes ty
  have o := one_key C w h
  have u := unpack_issuer_spec w h.bytes
  exact
    { magic := ⟨m0, m1, m2, m3⟩
      version := ver
      role := ro
      attempt := at'
      sec1 := ⟨s1, s2⟩
      sr := ⟨sr1, sr2⟩
      delta := dl
      code := cd
      nonce := ⟨n.1, n.2.1, n.2.2.1, n.2.2.2.1⟩
      rec_root := rec_root_canonical w h.bytes
      expiry := (expiry_iff w.exp ty.exp_ok w.valid_at).mp h.bytes.expiry
      key_limbs := x_limbs w.t ty.t_ok
      x_differ := (x_differ_iff w.t ty.t_ok).mp h.bytes.x_ne
      issuer_limbs := ⟨u.1, u.2.1, u.2.2.1, u.2.2.2.1⟩
      issuer := u.2.2.2.2.2.2
      device_sig := o.1
      credential_sig := o.2 }

/-! ## A real witness: the model on `Prover_A.toml`

The transcript, expiry, holder commit and public inputs below were generated by script from
`phone/Prover_A.toml` in the built circuits, a fixture that solves the real compiled circuit on 2026-11-06
(`fv/v1/zkp/logs/nargo-control.txt` (removed from the repo, in git at 5863e9c)). If the model read a wrong offset or got a check backwards, this would fail. -/

def fxTList : List Nat := [80, 79, 80, 84, 2, 65, 0, 239, 165, 54, 136, 219, 65, 189, 192, 239, 32, 110, 20, 207, 66, 197, 222, 135, 68, 67, 213, 182, 212, 76, 110, 95, 193, 176, 52, 87, 56, 219, 133, 4, 163, 173, 216, 15, 11, 48, 139, 135, 249, 25, 144, 170, 210, 11, 27, 160, 158, 172, 35, 41, 204, 76, 168, 9, 64, 162, 156, 91, 39, 190, 205, 12, 92, 112, 202, 108, 177, 40, 5, 221, 224, 33, 249, 93, 171, 62, 42, 2, 146, 200, 100, 45, 152, 205, 236, 223, 101, 247, 251, 109, 57, 105, 15, 67, 4, 245, 103, 252, 218, 162, 203, 0, 45, 123, 145, 118, 59, 83, 20, 0, 135, 22, 50, 143, 184, 217, 67, 192, 166, 245, 146, 186, 220, 234, 226, 91, 89, 1, 199, 210, 54, 247, 133, 177, 9, 42, 100, 13, 134, 229, 190, 160, 233, 111, 185, 54, 107, 163, 7, 129, 53, 31, 220, 123, 15, 32, 11, 28, 28, 0, 0, 187, 128, 0, 0, 175, 242, 35, 190, 146, 124, 163, 158, 6, 100, 123, 46, 196, 225, 56, 57, 217, 91, 29, 8, 213, 46, 179, 249, 69, 139, 147, 89, 175, 95, 234, 122, 126, 38, 0, 0, 0, 0, 0, 0, 103, 32, 0, 0, 51, 142, 19, 112, 202, 45, 0, 0, 51, 141, 225, 58, 54, 177, 0, 0, 0, 33, 105, 26, 81, 90, 202, 247, 142, 109, 134, 41, 3, 193, 164, 72, 253, 47, 210, 252, 59, 59, 223, 219, 47, 138, 7, 129, 181, 105, 29, 135, 90, 248, 0, 0, 111, 54, 0, 1, 15, 224, 0, 96, 29, 246, 243, 19, 129, 140, 213, 69, 85, 145, 127, 171, 90, 180, 146, 107, 213, 10, 163, 178, 189, 61, 38, 185, 84, 168, 75, 88, 192, 170, 179, 103]
def fxExpList : List Nat := [0, 0, 0, 0, 106, 222, 52, 225]
def fxHoldList : List Nat := [243, 112, 180, 57, 9, 94, 171, 240, 135, 84, 19, 191, 177, 109, 239, 62, 62, 109, 91, 41, 59, 50, 187, 179, 129, 2, 61, 75, 191, 23, 72, 36]
def fxT (i : Nat) : Nat := fxTList.getD i 0
def fxExp (i : Nat) : Nat := fxExpList.getD i 0
def fxHold (i : Nat) : Nat := fxHoldList.getD i 0
def fxNonceHi : Nat := 318543326067258532728290763847107790302
def fxNonceLo : Nat := 179800231470968996318113978715922291589
def fxValidAt : Nat := 1790000000
def fxCodeCommit : Nat := 13553394637094685588538090720355072531776183114434122398368012337076564046695
def fxLimb (i : Nat) : Nat := [193361542834748534988432975479966784079, 173636210078147415339230545169441724854, 100303539518225465188202088575728389411, 69862963338395041927192204904878343651].getD i 0

/-- `to_be_bytes::<16>` on a concrete limb. -/
def limbBytes (k i : Nat) : Nat := k / 256 ^ (15 - i) % 256

def fxW : Inputs where
  t := fxT
  sig := zeros
  exp := fxExp
  hold := fxHold
  csig := zeros
  nonce_hi := ((fxNonceHi : Nat) : F)
  nonce_lo := ((fxNonceLo : Nat) : F)
  attempt := 0
  role_b := false
  issuer := fun i => ((fxLimb i : Nat) : F)
  sr := 48000
  valid_at := fxValidAt
  code := fun i => fxT (279 + i)
  a := limbBytes (fxLimb 0)
  b := limbBytes (fxLimb 1)
  c := limbBytes (fxLimb 2)
  d := limbBytes (fxLimb 3)
  back := fun i => fxT (177 + i)

theorem fxT_ok : bytesOK fxT := by unfold bytesOK; decide +kernel

theorem isBE_limb (k : Nat) (h1 : ∀ i, i < 16 → limbBytes k i < 256) (h2 : beNat (limbBytes k) 0 16 = k) (h3 : k < p) :
    IsBE 16 ((k : Nat) : F) (limbBytes k) :=
  ⟨h1, by rw [val_natCast_of_lt h3]; exact h2⟩

/-- **A real circuit witness passes every non-signature check of this model.** -/
theorem fx_byteChecks : ByteChecks fxW :=
  { magic0 := by decide +kernel
    magic1 := by decide +kernel
    magic2 := by decide +kernel
    magic3 := by decide +kernel
    version := by decide +kernel
    role := by decide +kernel
    attempt := by decide +kernel
    nonce_hi := beF_of_beNat (t := fxT) (by decide +kernel)
    nonce_lo := beF_of_beNat (t := fxT) (by decide +kernel)
    prefix_own := by decide +kernel
    prefix_partner := by decide +kernel
    sr_eq := beF_of_beNat (t := fxT) (by decide +kernel)
    sr_const := rfl
    delta := beF_of_beNat (t := fxT) (by decide +kernel)
    code := fun _ _ => rfl
    limb_a := isBE_limb _ (by decide +kernel) (by decide +kernel) (by decide +kernel)
    limb_b := isBE_limb _ (by decide +kernel) (by decide +kernel) (by decide +kernel)
    limb_c := isBE_limb _ (by decide +kernel) (by decide +kernel) (by decide +kernel)
    limb_d := isBE_limb _ (by decide +kernel) (by decide +kernel) (by decide +kernel)
    expiry := by
      show fxValidAt ≤ asU64 (beF fxExp 0 8)
      rw [expiry_exact fxExp (by decide +kernel)]
      decide +kernel
    x_ne := (x_differ_iff fxT fxT_ok).mpr ⟨0, by norm_num, by decide +kernel⟩
    rr_be := by
      show IsBE 32 (beF fxT 177 32) (fun i => fxT (177 + i))
      refine ⟨by decide +kernel, ?_⟩
      rw [beF_eq, val_natCast_of_lt (by decide +kernel)]
      exact beNat_congr _ _ 0 177 32 (fun i _ => by rw [Nat.zero_add])
    rr_eq := fun _ _ => rfl }

/-- **The model's output on the real witness.** The values match `server/pop/codec.py decode_transcript` on the same bytes
(one-off Python run): `a_self`, `half`, `self_os_delta`, `p_partner`, `p_self`, `a_partner`. Its `code_commit` public input is
the transcript's code bytes. -/
theorem fx_values :
    aSelf fxT = 28470 ∧ half fxT = 45042 ∧ sod fxT = 33 ∧ pPartner fxT = 69600 ∧
    pSelf fxT = 28437 ∧ aPartner fxT false = 73512 ∧ beNat fxT 279 32 = fxCodeCommit := by
  decide +kernel

/-- The toy's signing history: the issuer key signed this credential, the own key signed this transcript, and nothing else
was signed by anyone. -/
def fxCred : List Nat := credList fxW
def fxMsgs : SignedSet := fun qx qy m =>
  (qx = issuerX fxW ∧ qy = issuerY fxW ∧ m = fxCred) ∨ (qx = ownX fxW ∧ qy = ownY fxW ∧ m = slice fxT 0 311)

/-- The signature on what was really signed, which is the one the witness carries. -/
def fxSigSigned : List Nat := slice zeros 0 64
/-- The signature that verifies on everything else. It exists but the witness doesn't use it, like a forgery nobody found. -/
def fxSigOther : List Nat := [1]

/-- A toy `Crypto` shaped like real ECDSA in the way that matters here: under any key, every digest has a verifying signature.
The hash is the identity. -/
def fxC : Crypto :=
  ⟨id, fun qx qy s d => (fxMsgs qx qy d ∧ s = fxSigSigned) ∨ (¬ fxMsgs qx qy d ∧ s = fxSigOther)⟩

theorem fxC_verify_signed {qx qy d : List Nat} (h : fxMsgs qx qy d) : fxC.verify qx qy fxSigSigned d := by
  show (fxMsgs qx qy d ∧ fxSigSigned = fxSigSigned) ∨ _
  exact Or.inl ⟨h, rfl⟩

theorem fxC_verify_other {qx qy d : List Nat} (h : ¬ fxMsgs qx qy d) : fxC.verify qx qy fxSigOther d := by
  show _ ∨ (¬ fxMsgs qx qy d ∧ fxSigOther = fxSigOther)
  exact Or.inr ⟨h, rfl⟩

theorem fx_checkSigned : CheckSigned fxC fxW :=
  { bytes := fx_byteChecks
    dev_sig := by
      show fxC.verify (slice (pxOf fxT) 0 32) (slice (pyOf fxT) 0 32) fxSigSigned (slice fxT 0 311)
      rw [px_slice, py_slice]
      exact fxC_verify_signed (Or.inr ⟨rfl, rfl, rfl⟩)
    cred_sig := by
      show fxC.verify (issuerX fxW) (issuerY fxW) fxSigSigned (slice (credOf fxT fxExp fxHold) 0 111)
      rw [cred_list]
      exact fxC_verify_signed (Or.inl ⟨rfl, rfl, rfl⟩) }

theorem fx_unforgeable (qx qy d : List Nat) : Unforgeable fxC fxMsgs qx qy fxSigSigned d := by
  intro hv
  rcases hv with ⟨hm, _⟩ | ⟨_, hs⟩
  · exact ⟨d, hm, rfl⟩
  · exact absurd hs (by decide +kernel)

theorem fx_noCollision (qx qy m : List Nat) : NoCollisionWith fxC fxMsgs qx qy m := fun _ _ he => he

/-- The empty message isn't in the toy's history, so the history isn't "everything". -/
theorem fx_empty_unsigned (qx qy : List Nat) : ¬ fxMsgs qx qy [] := by
  rintro (⟨_, _, h⟩ | ⟨_, _, h⟩)
  · exact absurd h (by decide +kernel)
  · exact absurd h (by decide +kernel)

/-- **`chain_of_trust` isn't vacuous, and its scoped hypothesis survives the objection to the universal one.** In one toy model,
all at once: the circuit accepts the real witness; every digest has a verifying signature under every key, as in real ECDSA;
the universal "any signature on any digest" claim is false; and all the scoped hypotheses hold, with a signing history that
isn't "everything", so the conclusion means something.

Consistency only. The toy hash is the identity and its signatures are made up, so this says nothing about whether real
ECDSA or SHA-256 has these properties on a real witness. That's what the named hypotheses are for. -/
theorem chain_hypotheses_consistent :
    CheckSigned fxC fxW ∧
    (∀ qx qy d, ∃ s, fxC.verify qx qy s d) ∧
    (¬ ∀ s d, fxC.verify (ownX fxW) (ownY fxW) s d →
      ∃ m, fxMsgs (ownX fxW) (ownY fxW) m ∧ fxC.sha256 m = d) ∧
    Unforgeable fxC fxMsgs (issuerX fxW) (issuerY fxW) (slice fxW.csig 0 64) (fxC.sha256 (credList fxW)) ∧
    NoCollisionWith fxC fxMsgs (issuerX fxW) (issuerY fxW) (credList fxW) ∧
    (fxMsgs (issuerX fxW) (issuerY fxW) (credList fxW) →
      Unforgeable fxC fxMsgs (ownX fxW) (ownY fxW) (slice fxW.sig 0 64) (fxC.sha256 (slice fxW.t 0 311))) ∧
    NoCollisionWith fxC fxMsgs (ownX fxW) (ownY fxW) (slice fxW.t 0 311) ∧
    fxMsgs (issuerX fxW) (issuerY fxW) (credList fxW) ∧ fxMsgs (ownX fxW) (ownY fxW) (slice fxW.t 0 311) ∧
    ¬ fxMsgs (ownX fxW) (ownY fxW) [] := by
  have hall : ∀ qx qy d, ∃ s, fxC.verify qx qy s d := by
    intro qx qy d
    by_cases h : fxMsgs qx qy d
    · exact ⟨_, fxC_verify_signed h⟩
    · exact ⟨_, fxC_verify_other h⟩
  have huniv : ¬ ∀ s d, fxC.verify (ownX fxW) (ownY fxW) s d →
      ∃ m, fxMsgs (ownX fxW) (ownY fxW) m ∧ fxC.sha256 m = d := by
    intro hu
    obtain ⟨m, hm, he⟩ := hu _ _ (fxC_verify_other (fx_empty_unsigned _ _))
    have hmn : m = [] := he
    rw [hmn] at hm
    exact fx_empty_unsigned _ _ hm
  have hI : Unforgeable fxC fxMsgs (issuerX fxW) (issuerY fxW) (slice fxW.csig 0 64) (fxC.sha256 (credList fxW)) :=
    fx_unforgeable _ _ _
  have hD : Unforgeable fxC fxMsgs (ownX fxW) (ownY fxW) (slice fxW.sig 0 64) (fxC.sha256 (slice fxW.t 0 311)) :=
    fx_unforgeable _ _ _
  have hc := chain_of_trust fxC fxW fxMsgs fx_checkSigned hI (fx_noCollision _ _ _) (fun _ => hD) (fx_noCollision _ _ _)
  exact ⟨fx_checkSigned, hall, huniv, hI, fx_noCollision _ _ _, fun _ => hD, fx_noCollision _ _ _, hc.1, hc.2,
    fx_empty_unsigned _ _⟩

/-- All of Noir's type ranges hold on the real witness. -/
theorem fx_types : Types fxW :=
  { t_ok := fxT_ok
    exp_ok := by show ∀ i, i < 8 → fxExp i < 256; decide +kernel
    hold_ok := by show ∀ i, i < 32 → fxHold i < 256; decide +kernel
    sr_ok := by show (48000 : Nat) < 2 ^ 32; norm_num
    valid_at_ok := by show fxValidAt < 2 ^ 64; decide +kernel }

/-- **`check_signed_sound`'s two hypotheses can hold together.** The real witness has the right Noir types, and it is accepted in
the toy `Crypto`, so the theorem isn't about an empty set of inputs. Same limit as `chain_hypotheses_consistent`: the signatures
here are made up. -/
theorem fx_sound : BlockA fxC fxW := check_signed_sound fxC fxW fx_checkSigned fx_types

/-- **The model does reject things: wrong public role.** Same witness, but the public input says role B. -/
theorem fx_rejects_role : ¬ ByteChecks { fxW with role_b := true } := by
  intro h
  have := h.role
  revert this
  decide +kernel

/-- **The model does reject things: expired.** Same witness, with `valid_at` past the signed expiry. -/
theorem fx_rejects_expiry : ¬ ByteChecks { fxW with valid_at := 2 ^ 40 } := by
  intro h
  have e := (expiry_iff fxExp (by decide +kernel) (2 ^ 40)).mp h.expiry
  revert e
  decide +kernel

/-- The real witness, with partner X overwritten by own X. -/
def fxSameX (i : Nat) : Nat := if 105 ≤ i ∧ i < 137 then fxT (i - 65) else fxT i

/-- **The model does reject things: own X equals partner X.** -/
theorem fx_rejects_same_x : ¬ ByteChecks { fxW with t := fxSameX } := by
  intro h
  have ht : bytesOK fxSameX := by unfold bytesOK; decide +kernel
  obtain ⟨i, hi, hne⟩ := (x_differ_iff fxSameX ht).mp h.x_ne
  have heq : ∀ i, i < 32 → fxSameX (40 + i) = fxSameX (105 + i) := by decide +kernel
  exact hne (heq i hi)

/-- A `Crypto` that accepts everything, standing for "a device key willing to sign this". -/
def anyC : Crypto := ⟨id, fun _ _ _ _ => True⟩

/-- The real witness with 0xFF in all 88 hash-only bytes. -/
def fxJunk (i : Nat) : Nat :=
  if (137 ≤ i ∧ i < 169) ∨ (209 ≤ i ∧ i < 233) ∨ (237 ≤ i ∧ i < 269) then 0xff else fxT i

/-- **Concrete witness: junk `commit_hash`, times and partner Y.** With those 88 bytes all 0xFF and a device willing to sign,
the circuit accepts and returns the same `Signed` as the real fixture. -/
theorem junk_accepted :
    CheckSigned anyC { fxW with t := fxJunk, sig := zeros } ∧
      checkSignedOut fxJunk false = checkSignedOut fxT false ∧
      fxJunk 237 ≠ fxT 237 ∧ fxJunk 137 ≠ fxT 137 ∧ fxJunk 209 ≠ fxT 209 := by
  have hc : CheckSigned anyC fxW := ⟨fx_byteChecks, trivial, trivial⟩
  have := digest_only_free anyC fxW fxJunk zeros hc
    (fun i _ hi => by
      unfold digestOnly at hi
      unfold fxJunk
      rw [if_neg hi]
      rfl)
    trivial
  exact ⟨this.1, this.2, by decide +kernel, by decide +kernel, by decide +kernel⟩

/-- The real witness with an all-zero own key, and a partner key of X = 1, Y = 0. Neither is a point on P-256 as far as this
model knows or cares; `(0, 0)` isn't one in fact, since the curve's constant term is nonzero. -/
def fxBadKeys (i : Nat) : Nat :=
  if 40 ≤ i ∧ i < 104 then 0
  else if i = 136 then 1
  else if 105 ≤ i ∧ i < 169 then 0
  else fxT i

/-- **Concrete witness: nonsense keys pass every check but the signatures.** Only `verify_signature` can reject the all-zero
own key. Nothing at all rejects the partner key. -/
theorem bad_keys_pass_byteChecks : ByteChecks { fxW with t := fxBadKeys } := by
  refine only_read_bytes_matter fxW fxBadKeys fx_byteChecks (by unfold bytesOK; decide +kernel) ?_
    ⟨31, by norm_num, by decide +kernel⟩
  intro i hi
  unfold readByChecks at hi
  unfold fxBadKeys
  rw [if_neg (by omega), if_neg (by omega), if_neg (by omega)]
  rfl

end Signed
end Popfv

#print axioms Popfv.Signed.Layout.offsets
#print axioms Popfv.Signed.credTag_is_SBcred3
#print axioms Popfv.Signed.cred_list
#print axioms Popfv.Signed.asserted_bytes
#print axioms Popfv.Signed.role_iff
#print axioms Popfv.Signed.nonce_limbs
#print axioms Popfv.Signed.nonce_determines_bytes
#print axioms Popfv.Signed.x_limbs
#print axioms Popfv.Signed.x_differ_iff
#print axioms Popfv.Signed.rec_root_canonical
#print axioms Popfv.Signed.rec_root_injective
#print axioms Popfv.Signed.wrapped_root_rejected
#print axioms Popfv.Signed.alias_without_canonical
#print axioms Popfv.Signed.code_commit_signed
#print axioms Popfv.Signed.expiry_iff
#print axioms Popfv.Signed.unpack_issuer_spec
#print axioms Popfv.Signed.issuer_key_unique
#print axioms Popfv.Signed.signed_fields
#print axioms Popfv.Signed.one_key
#print axioms Popfv.Signed.chain_of_trust
#print axioms Popfv.Signed.digest_only_free
#print axioms Popfv.Signed.only_read_bytes_matter
#print axioms Popfv.Signed.holder_commit_free
#print axioms Popfv.Signed.check_signed_sound
#print axioms Popfv.Signed.fx_byteChecks
#print axioms Popfv.Signed.fx_values
#print axioms Popfv.Signed.chain_hypotheses_consistent
#print axioms Popfv.Signed.chain_of_trust_size
#print axioms Popfv.Signed.fx_types
#print axioms Popfv.Signed.fx_sound
#print axioms Popfv.Signed.fx_rejects_role
#print axioms Popfv.Signed.fx_rejects_expiry
#print axioms Popfv.Signed.fx_rejects_same_x
#print axioms Popfv.Signed.junk_accepted
#print axioms Popfv.Signed.bad_keys_pass_byteChecks
