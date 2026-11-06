import Popfv.PartnerGlue

/-!
# Popfv.Commit — blocks H (`code_commitment`) and B (`open_leaves`, `merkle_root`, `leaf_hash`)

Source: `research/worldid/prototypes/optA-noir/noir/oalib/src/lib.nr`. Line numbers below refer to that file.

Modelling conventions (same as `PartnerGlue.lean`)
* Arrays `[u8; T]`, `[u16; T]` are functions `Nat → Nat`; the type range is an explicit hypothesis.
* Loops are recursions over the counter. An `assert` is a `Prop` collected along the way.
* `poseidon2_permutation` is an arbitrary function `perm`, nothing is known about it. `Sp` (lines 49-73) and
  `hash_n` (75-81) are modelled literally on top of it.
* `idx.to_le_bits()` into `[bool; 8]` (line 109) is modelled by what Noir documents: `idx` fits in 8 bits, and
  bit `n` is `idx.val / 2^n % 2`. That Noir does this is trusted, as in `PartnerGlue.lean`.

How collision resistance is stated
A hash from many field elements to one always has collisions, so "this hash has no collisions at all" is simply
false (`node_hash_not_injective`), and a theorem assuming it would say nothing. So every hypothesis here is about
the specific inputs at hand: `NodeBinds`, `LeafBinds`, `CodeBinds` say "these two inputs, if they hash the same,
are the same". If such a hypothesis fails, the witness itself is a Poseidon2 collision
(`opening_mismatch_gives_collision`). `BindsToRecording`, the hypothesis of the window theorems, is not contradictory:
an honest prover meets it for every `perm` (`honest_binds`), the circuit accepts that prover (`open_leaves_complete`),
and `phone_core_windows_nonvacuous` gives a concrete transcript where every premise of the window theorem holds.
`honest_binds` does not cover `CodeBinds` or `OpeningsBind`: this file gives no separate witness for those two.

The sponge has no length padding: a shorter input and the same input with trailing zeros can collide
(`sponge_zero_tail_collision`). This is harmless because each tag is used with one fixed length, so all the
hypotheses compare inputs of equal length.

What this file does NOT prove
* Poseidon2 itself. Nothing about `perm` is used.
* That `rec_root` and `code_commit` come from honest parties. `recRoot` is what an honest tree builder computes
  (`server/pop/poseidon2.py`, `OaHash.kt`), and using it is a hypothesis.
* That a recording is what the mic heard. The tree commits 256 leaves with no length, so samples past the real
  capture are filler (`past_capture_window_passes`).
-/

set_option linter.style.whitespace false
set_option linter.style.longLine false
set_option linter.style.header false

namespace Popfv
namespace Commit

open PartnerGlue (bytesOK osF opF pSelf aPartner os_window op_window asU32 asU32_of_fits partnerAccepts
  partner_silence_accepts)

/-! ## The sponge (lib.nr 49-81), over an opaque permutation -/

/-- The sponge state, `s: [Field; 4]`. -/
abbrev State := Fin 4 → F

/-- The type of `poseidon2_permutation`. Every theorem takes it as a parameter. -/
abbrev Perm := State → State

/-- lines 49-52 -/
structure Sp where
  s : State
  pos : Nat

/-- line 56: `Sp { s: [0, 0, 0, tag], pos: 0 }` -/
def Sp.new (tag : F) : Sp := ⟨![0, 0, 0, tag], 0⟩

/-- lines 58-65 -/
def Sp.absorb (perm : Perm) (sp : Sp) (x : F) : Sp :=
  let s' := Function.update sp.s (Fin.ofNat 4 sp.pos) (sp.s (Fin.ofNat 4 sp.pos) + x)  -- 59
  if sp.pos + 1 = 3 then ⟨perm s', 0⟩ else ⟨s', sp.pos + 1⟩                             -- 60-64

/-- lines 66-72 -/
def Sp.finish (perm : Perm) (sp : Sp) : F × F :=
  let s' := if sp.pos ≠ 0 then perm sp.s else sp.s
  (s' 0, s' 1)

/-- A run of `sp.absorb(x)` calls, in order. -/
def absorbAll (perm : Perm) (sp : Sp) (l : List F) : Sp := l.foldl (Sp.absorb perm) sp

/-- lines 75-81, with `sp.finish().0` -/
def hash_n (perm : Perm) (tag : F) (l : List F) : F := ((absorbAll perm (Sp.new tag) l).finish perm).1

/-- line 42 -/ def TAG_LEAF : F := 262145
/-- line 43 -/ def TAG_NODE : F := 2
/-- line 46 -/ def TAG_CODE : F := 10

theorem absorb_zero_full (perm : Perm) (sp : Sp) (h : sp.pos = 2) :
    Sp.absorb perm sp 0 = ⟨perm sp.s, 0⟩ := by
  unfold Sp.absorb
  rw [h]
  simp

/-- **The sponge has no length padding.** Hashing `[a, b]` and `[a, b, 0]` under one tag gives the same answer,
for every permutation. So "no collisions" can only ever be claimed for inputs of one fixed length. Each tag in
the circuit is used at one fixed length, so this does not hurt the circuit, but it is why the hypotheses in this
file are about inputs of equal length. -/
theorem sponge_zero_tail_collision (perm : Perm) (tag a b : F) :
    hash_n perm tag [a, b] = hash_n perm tag [a, b, 0] := by
  have hpos : (absorbAll perm (Sp.new tag) [a, b]).pos = 2 := rfl
  have e : absorbAll perm (Sp.new tag) [a, b, 0]
      = Sp.absorb perm (absorbAll perm (Sp.new tag) [a, b]) 0 := rfl
  unfold hash_n
  rw [e, absorb_zero_full perm _ hpos]
  simp [Sp.finish, hpos]

/-! ## Small arithmetic helpers -/

theorem natCast_inj_of_lt {a b : Nat} (ha : a < p) (hb : b < p) (h : (a : F) = (b : F)) : a = b := by
  have := congrArg ZMod.val h
  rwa [val_natCast_of_lt ha, val_natCast_of_lt hb] at this

theorem add_mul_inj {a b x y M : Nat} (ha : a < M) (hb : b < M) (h : a + x * M = b + y * M) :
    a = b ∧ x = y := by
  have h1 : a = b := by
    have := congrArg (· % M) h
    simpa [Nat.add_mul_mod_self_right, Nat.mod_eq_of_lt ha, Nat.mod_eq_of_lt hb] using this
  subst h1
  have hM : 0 < M := by omega
  have h2 : x * M = y * M := by omega
  exact ⟨rfl, Nat.eq_of_mul_eq_mul_right hM h2⟩

/-! ## Block H: `absorb_bytes`, `code_commitment` (lib.nr 148-168) -/

/-- line 23 -/
abbrev L : Nat := 12000

/-- lines 150-156, the inner loop: `acc = 0; for j in 0..n { idx = 31 * k + j; if idx < L { acc = acc * 256 + a[idx] } }`. -/
def chunkGo (a : Nat → Nat) (k : Nat) : Nat → F
  | 0 => 0
  | j + 1 => if 31 * k + j < L then chunkGo a k j * 256 + (a (31 * k + j) : F) else chunkGo a k j

/-- The element absorbed at line 157, for chunk `k`. -/
def chunk (a : Nat → Nat) (k : Nat) : F := chunkGo a k 31

/-- The sequence of elements absorbed for one template: line 149, `for k in 0..(L + 30) / 31`. -/
def chunks (a : Nat → Nat) : List F := (List.range ((L + 30) / 31)).map (chunk a)

/-- lines 148-159 -/
def absorb_bytes (perm : Perm) (sp : Sp) (a : Nat → Nat) : Sp := absorbAll perm sp (chunks a)

/-- lines 161-168 -/
def code_commitment (perm : Perm) (a b c d : Nat → Nat) : F :=
  let sp := Sp.new TAG_CODE
  let sp := absorb_bytes perm sp a
  let sp := absorb_bytes perm sp b
  let sp := absorb_bytes perm sp c
  let sp := absorb_bytes perm sp d
  (sp.finish perm).1

theorem chunks_length (a : Nat → Nat) : (chunks a).length = 388 := by
  simp [chunks, L]

/-- The stream of `code_commitment` is one sequence: the four templates' chunks, one after the other. -/
theorem code_commitment_eq (perm : Perm) (a b c d : Nat → Nat) :
    code_commitment perm a b c d = hash_n perm TAG_CODE (chunks a ++ chunks b ++ chunks c ++ chunks d) := by
  simp only [code_commitment, absorb_bytes, absorbAll, hash_n, List.foldl_append]

/-- `chunkGo` as a true natural number, no field involved. -/
def chunkNat (a : Nat → Nat) (k : Nat) : Nat → Nat
  | 0 => 0
  | j + 1 => if 31 * k + j < L then chunkNat a k j * 256 + a (31 * k + j) else chunkNat a k j

theorem chunkGo_eq (a : Nat → Nat) (k j : Nat) : chunkGo a k j = (chunkNat a k j : F) := by
  induction j with
  | zero => simp [chunkGo, chunkNat]
  | succ j ih =>
    simp only [chunkGo, chunkNat, ih]
    split <;> push_cast <;> rfl

theorem chunkNat_lt (a : Nat → Nat) (k : Nat) (ha : ∀ i, i < L → a i < 256) (j : Nat) :
    chunkNat a k j < 256 ^ j := by
  induction j with
  | zero => simp [chunkNat]
  | succ j ih =>
    simp only [chunkNat]
    rw [pow_succ]
    split
    · rename_i h
      have := ha _ h
      omega
    · omega

/-- **A chunk fits with room to spare.** Each element absorbed at line 157 is below `2^248`, which is below `p`,
for the short last chunk too. So nothing wraps around the field. -/
theorem chunk_lt_two_pow_248 (a : Nat → Nat) (k : Nat) (ha : ∀ i, i < L → a i < 256) :
    (chunk a k).val < 2 ^ 248 ∧ (2 : Int) ^ 248 < (p : Int) := by
  have hb : chunkNat a k 31 < 2 ^ 248 := by
    have := chunkNat_lt a k ha 31
    norm_num at this ⊢
    exact this
  refine ⟨?_, two_pow_lt_p (by norm_num)⟩
  rw [chunk, chunkGo_eq, val_natCast_of_lt (natCast_lt_p_of_lt_two_pow (by norm_num) hb)]
  exact hb

/-- **The short last chunk, spelled out.** `L = 12000 = 31 * 387 + 3`, so chunk 387 holds only three bytes, with
no padding. It is still big-endian. -/
theorem chunk_last_short (a : Nat → Nat) :
    chunk a 387 = ((a 11997 : F) * 256 + (a 11998 : F)) * 256 + (a 11999 : F) := by
  simp [chunk, chunkGo, L]

theorem chunkNat_inj (a b : Nat → Nat) (k : Nat) (ha : ∀ i, i < L → a i < 256) (hb : ∀ i, i < L → b i < 256)
    (j : Nat) (h : chunkNat a k j = chunkNat b k j) :
    ∀ j', j' < j → 31 * k + j' < L → a (31 * k + j') = b (31 * k + j') := by
  induction j with
  | zero => intro j' hj'; omega
  | succ j ih =>
    intro j' hj' hL'
    by_cases hi : 31 * k + j < L
    · simp only [chunkNat, if_pos hi] at h
      have h1 := ha _ hi
      have h2 := hb _ hi
      have hA : chunkNat a k j = chunkNat b k j := by omega
      have hX : a (31 * k + j) = b (31 * k + j) := by omega
      by_cases hj : j' = j
      · subst hj; exact hX
      · exact ih hA j' (by omega) hL'
    · simp only [chunkNat, if_neg hi] at h
      by_cases hj : j' = j
      · subst hj; exact absurd hL' hi
      · exact ih h j' (by omega) hL'

theorem chunkGo_congr (a b : Nat → Nat) (k : Nat) (h : ∀ i, i < L → a i = b i) (j : Nat) :
    chunkGo a k j = chunkGo b k j := by
  induction j with
  | zero => rfl
  | succ j ih =>
    simp only [chunkGo, ih]
    split
    · rename_i hi; rw [h _ hi]
    · rfl

/-- **The byte packing loses nothing.** Two templates of `u8` values give the same absorbed sequence exactly when
they agree on all 12000 bytes. The 31-byte big-endian chunks stay below `2^248 < p`, so a chunk is a true whole
number, and its base-256 digits are the bytes. -/
theorem packing_injective (a b : Nat → Nat) (ha : ∀ i, i < L → a i < 256) (hb : ∀ i, i < L → b i < 256) :
    chunks a = chunks b ↔ ∀ i, i < L → a i = b i := by
  constructor
  · intro h i hi
    have hm := (List.map_inj_left.1 h) (i / 31) (List.mem_range.2 (by
      have hi' : i < 12000 := hi
      show i / 31 < (12000 + 30) / 31
      omega))
    have hAlt : chunkNat a (i / 31) 31 < 2 ^ 248 := by
      have := chunkNat_lt a (i / 31) ha 31
      norm_num at this ⊢
      exact this
    have hBlt : chunkNat b (i / 31) 31 < 2 ^ 248 := by
      have := chunkNat_lt b (i / 31) hb 31
      norm_num at this ⊢
      exact this
    have hn : chunkNat a (i / 31) 31 = chunkNat b (i / 31) 31 := by
      apply natCast_inj_of_lt (natCast_lt_p_of_lt_two_pow (by norm_num) hAlt)
        (natCast_lt_p_of_lt_two_pow (by norm_num) hBlt)
      rw [← chunkGo_eq, ← chunkGo_eq]
      exact hm
    have hdec : 31 * (i / 31) + i % 31 = i := Nat.div_add_mod i 31
    have := chunkNat_inj a b (i / 31) ha hb 31 hn (i % 31) (Nat.mod_lt _ (by norm_num)) (by rw [hdec]; exact hi)
    rwa [hdec] at this
  · intro h
    exact List.map_congr_left (fun k _ => chunkGo_congr a b k h 31)

/-- **The absorbed sequence determines the four templates.** The four chunk lists have fixed length 388 each, so
the concatenation splits in only one way. No hash is involved. -/
theorem absorbed_determines_templates (a b c d a' b' c' d' : Nat → Nat)
    (ha : ∀ i, i < L → a i < 256) (hb : ∀ i, i < L → b i < 256)
    (hc : ∀ i, i < L → c i < 256) (hd : ∀ i, i < L → d i < 256)
    (ha' : ∀ i, i < L → a' i < 256) (hb' : ∀ i, i < L → b' i < 256)
    (hc' : ∀ i, i < L → c' i < 256) (hd' : ∀ i, i < L → d' i < 256)
    (h : chunks a ++ chunks b ++ chunks c ++ chunks d = chunks a' ++ chunks b' ++ chunks c' ++ chunks d') :
    (∀ i, i < L → a i = a' i) ∧ (∀ i, i < L → b i = b' i) ∧
    (∀ i, i < L → c i = c' i) ∧ (∀ i, i < L → d i = d' i) := by
  obtain ⟨h, h4⟩ := List.append_inj h (by simp [chunks_length])
  obtain ⟨h, h3⟩ := List.append_inj h (by simp [chunks_length])
  obtain ⟨h1, h2⟩ := List.append_inj h (by simp [chunks_length])
  exact ⟨(packing_injective a a' ha ha').1 h1, (packing_injective b b' hb hb').1 h2,
    (packing_injective c c' hc hc').1 h3, (packing_injective d d' hd hd').1 h4⟩

/-- Collision hypothesis for `code_commitment`, at exactly these two inputs. -/
def CodeBinds (perm : Perm) (A A' : List F) : Prop :=
  hash_n perm TAG_CODE A = hash_n perm TAG_CODE A' → A = A'

/-- **Equal commitments mean equal templates, IF the hash has no collision here.** Suppose two sets of four
`u8` templates give the same `code_commitment`. If Poseidon2 has no collision at these two inputs (`CodeBinds`,
assumed, not proved), the templates are the same on all 12000 bytes. What is proved is only that the packing and
the stream lose no information. -/
theorem code_commitment_binds (perm : Perm) (a b c d a' b' c' d' : Nat → Nat)
    (ha : ∀ i, i < L → a i < 256) (hb : ∀ i, i < L → b i < 256)
    (hc : ∀ i, i < L → c i < 256) (hd : ∀ i, i < L → d i < 256)
    (ha' : ∀ i, i < L → a' i < 256) (hb' : ∀ i, i < L → b' i < 256)
    (hc' : ∀ i, i < L → c' i < 256) (hd' : ∀ i, i < L → d' i < 256)
    (hcr : CodeBinds perm (chunks a ++ chunks b ++ chunks c ++ chunks d)
      (chunks a' ++ chunks b' ++ chunks c' ++ chunks d'))
    (h : code_commitment perm a b c d = code_commitment perm a' b' c' d') :
    (∀ i, i < L → a i = a' i) ∧ (∀ i, i < L → b i = b' i) ∧
    (∀ i, i < L → c i = c' i) ∧ (∀ i, i < L → d i = d' i) := by
  rw [code_commitment_eq, code_commitment_eq] at h
  exact absorbed_determines_templates a b c d a' b' c' d' ha hb hc hd ha' hb' hc' hd' (hcr h)

/-- **Same templates, same commitment.** The other direction, with no hypothesis: the commitment depends only on
the 12000 bytes of each template. -/
theorem code_commitment_congr (perm : Perm) (a b c d a' b' c' d' : Nat → Nat)
    (h1 : ∀ i, i < L → a i = a' i) (h2 : ∀ i, i < L → b i = b' i)
    (h3 : ∀ i, i < L → c i = c' i) (h4 : ∀ i, i < L → d i = d' i) :
    code_commitment perm a b c d = code_commitment perm a' b' c' d' := by
  have e : ∀ x y : Nat → Nat, (∀ i, i < L → x i = y i) → chunks x = chunks y :=
    fun x y h => List.map_congr_left (fun k _ => chunkGo_congr x y k h 31)
  rw [code_commitment_eq, code_commitment_eq, e a a' h1, e b b' h2, e c c' h3, e d d' h4]

/-! ## Block B: `leaf_hash` (lib.nr 85-100) -/

/-- lines 88-96, the inner loop, state `(acc, mul)`. `mul` moves only when a sample is added. -/
def leafGo (x : Nat → Nat) (base k : Nat) : Nat → F × F
  | 0 => (0, 1)
  | j + 1 =>
    if k * 15 + j < 1024 then
      ((leafGo x base k j).1 + (x (base + (k * 15 + j)) : F) * (leafGo x base k j).2, (leafGo x base k j).2 * 65536)
    else leafGo x base k j

/-- The element absorbed at line 97, for element `k`. -/
def leafAcc (x : Nat → Nat) (base k : Nat) : F := (leafGo x base k 15).1

/-- line 87: `for k in 0..69`. -/
def leafElems (x : Nat → Nat) (base : Nat) : List F := (List.range 69).map (leafAcc x base)

/-- lines 85-100 -/
def leaf_hash (perm : Perm) (x : Nat → Nat) (base : Nat) : F := hash_n perm TAG_LEAF (leafElems x base)

/-- How many samples element `k` has taken after `j` steps. -/
def leafCount (k : Nat) : Nat → Nat
  | 0 => 0
  | j + 1 => if k * 15 + j < 1024 then leafCount k j + 1 else leafCount k j

/-- `acc` as a true natural number. -/
def leafNat (x : Nat → Nat) (base k : Nat) : Nat → Nat
  | 0 => 0
  | j + 1 =>
    if k * 15 + j < 1024 then leafNat x base k j + x (base + (k * 15 + j)) * 65536 ^ leafCount k j
    else leafNat x base k j

theorem leafGo_eq (x : Nat → Nat) (base k j : Nat) :
    leafGo x base k j = ((leafNat x base k j : F), (65536 : F) ^ leafCount k j) := by
  induction j with
  | zero => simp [leafGo, leafNat, leafCount]
  | succ j ih =>
    by_cases h : k * 15 + j < 1024
    · simp only [leafGo, leafNat, leafCount, if_pos h, ih]
      refine Prod.ext ?_ ?_ <;> simp [pow_succ]
    · simp only [leafGo, leafNat, leafCount, if_neg h, ih]

theorem leafCount_le (k j : Nat) : leafCount k j ≤ j := by
  induction j with
  | zero => simp [leafCount]
  | succ j ih =>
    simp only [leafCount]
    split <;> omega

theorem leafNat_lt (x : Nat → Nat) (base k : Nat) (hx : ∀ idx, idx < 1024 → x (base + idx) < 65536) (j : Nat) :
    leafNat x base k j < 65536 ^ leafCount k j := by
  induction j with
  | zero => simp [leafNat, leafCount]
  | succ j ih =>
    by_cases h : k * 15 + j < 1024
    · simp only [leafNat, leafCount, if_pos h]
      rw [pow_succ]
      have h1 := hx _ h
      have h2 : x (base + (k * 15 + j)) * 65536 ^ leafCount k j ≤ 65535 * 65536 ^ leafCount k j :=
        Nat.mul_le_mul_right _ (by omega)
      omega
    · simp only [leafNat, leafCount, if_neg h]
      exact ih

/-- **A leaf element fits.** Each of the 69 elements holds at most 15 samples of 16 bits, so it is below
`2^240 < p`, and nothing wraps around the field. -/
theorem leafNat_lt_two_pow_240 (x : Nat → Nat) (base k : Nat) (hx : ∀ idx, idx < 1024 → x (base + idx) < 65536) :
    leafNat x base k 15 < 2 ^ 240 := by
  have h1 := leafNat_lt x base k hx 15
  have h2 : (65536 : Nat) ^ leafCount k 15 ≤ 65536 ^ 15 :=
    pow_le_pow_right₀ (by norm_num) (leafCount_le k 15)
  have h3 : (65536 : Nat) ^ 15 = 2 ^ 240 := by norm_num
  omega

theorem leafNat_inj (x y : Nat → Nat) (b b' k : Nat)
    (hx : ∀ idx, idx < 1024 → x (b + idx) < 65536) (hy : ∀ idx, idx < 1024 → y (b' + idx) < 65536)
    (j : Nat) (h : leafNat x b k j = leafNat y b' k j) :
    ∀ j', j' < j → k * 15 + j' < 1024 → x (b + (k * 15 + j')) = y (b' + (k * 15 + j')) := by
  induction j with
  | zero => intro j' hj'; omega
  | succ j ih =>
    intro j' hj' hL'
    by_cases hi : k * 15 + j < 1024
    · simp only [leafNat, if_pos hi] at h
      obtain ⟨hA, hX⟩ := add_mul_inj (leafNat_lt x b k hx j) (leafNat_lt y b' k hy j) h
      by_cases hj : j' = j
      · subst hj; exact hX
      · exact ih hA j' (by omega) hL'
    · simp only [leafNat, if_neg hi] at h
      by_cases hj : j' = j
      · subst hj; exact absurd hL' hi
      · exact ih h j' (by omega) hL'

theorem leafGo_congr (x y : Nat → Nat) (b b' k : Nat) (h : ∀ idx, idx < 1024 → x (b + idx) = y (b' + idx))
    (j : Nat) : leafGo x b k j = leafGo y b' k j := by
  induction j with
  | zero => rfl
  | succ j ih =>
    simp only [leafGo, ih]
    split
    · rename_i hi; rw [h _ hi]
    · rfl

theorem leafElems_congr (x y : Nat → Nat) (b b' : Nat) (h : ∀ idx, idx < 1024 → x (b + idx) = y (b' + idx)) :
    leafElems x b = leafElems y b' :=
  List.map_congr_left (fun k _ => congrArg Prod.fst (leafGo_congr x y b b' k h 15))

/-- **The sample packing loses nothing.** For 1024 `u16` samples, the 69 elements of 15 x 16 bits are equal
exactly when the samples are equal. The bases may differ: the two sides can be two arrays read at two offsets.
This is the 15 x 16-bit packing of lines 87-98, little-end within an element. -/
theorem leaf_packing_injective (x y : Nat → Nat) (b b' : Nat)
    (hx : ∀ idx, idx < 1024 → x (b + idx) < 65536) (hy : ∀ idx, idx < 1024 → y (b' + idx) < 65536) :
    leafElems x b = leafElems y b' ↔ ∀ idx, idx < 1024 → x (b + idx) = y (b' + idx) := by
  constructor
  · intro h idx hidx
    have hm := (List.map_inj_left.1 h) (idx / 15) (List.mem_range.2 (by omega))
    have hF : ((leafNat x b (idx / 15) 15 : Nat) : F) = (leafNat y b' (idx / 15) 15 : Nat) := by
      have := hm
      simp only [leafAcc, leafGo_eq] at this
      exact this
    have hn := natCast_inj_of_lt
      (natCast_lt_p_of_lt_two_pow (by norm_num) (leafNat_lt_two_pow_240 x b _ hx))
      (natCast_lt_p_of_lt_two_pow (by norm_num) (leafNat_lt_two_pow_240 y b' _ hy)) hF
    have hdec : idx / 15 * 15 + idx % 15 = idx := Nat.div_add_mod' idx 15
    have := leafNat_inj x y b b' (idx / 15) hx hy 15 hn (idx % 15) (Nat.mod_lt _ (by norm_num))
      (by rw [hdec]; exact hidx)
    rwa [hdec] at this
  · exact leafElems_congr x y b b'

/-! ## Block B: `node_hash`, `merkle_root` (lib.nr 103-121) -/

/-- lines 103-105 -/
def node_hash (perm : Perm) (c : Fin 4 → F) : F := hash_n perm TAG_NODE [c 0, c 1, c 2, c 3]

/-- **"No collisions at all" is false, whatever the permutation is.** `node_hash` maps four field elements to one,
so by counting it has collisions. This is why this file never assumes a global collision-resistance statement:
such a hypothesis could never hold, and any theorem resting on it would be empty. -/
theorem node_hash_not_injective (perm : Perm) : ¬ Function.Injective (node_hash perm) := by
  intro h
  have h1 := Fintype.card_le_of_injective _ h
  have h2 : Fintype.card (Fin 4 → F) = p ^ 4 := by simp [ZMod.card]
  have h3 : Fintype.card F = p := ZMod.card p
  rw [h2, h3] at h1
  norm_num [p] at h1

/-- Line 112-113: `bits[n] as Field`, from `idx.to_le_bits()` at line 109. -/
def bit (idx : F) (n : Nat) : F := ((idx.val / 2 ^ n % 2 : Nat) : F)

/-- line 116 -/
def sel (c : Fin 4 → F) (b0 b1 : F) : F :=
  c 0 + b0 * (c 1 - c 0) + b1 * (c 2 - c 0) + b0 * b1 * (c 3 - c 2 - c 1 + c 0)

/-- line 116 at level `l`, with lines 112-115. -/
def selAt (idx : F) (c : Fin 4 → F) (l : Nat) : F := sel c (bit idx (2 * l)) (bit idx (2 * l + 1))

/-- State of the loop at lines 110-119: `cur`, and the conjunction of the asserts so far. -/
structure MSt where
  cur : F
  ok : Prop

/-- lines 109-119. The start carries the 8-bit check of line 109. -/
def merkleGo (perm : Perm) (leaf idx : F) (ch : Nat → Fin 4 → F) : Nat → MSt
  | 0 => ⟨leaf, fits 8 idx⟩
  | l + 1 =>
    ⟨node_hash perm (ch l),                                                       -- 118
     (merkleGo perm leaf idx ch l).ok ∧ (merkleGo perm leaf idx ch l).cur = selAt idx (ch l) l⟩  -- 117

/-- line 120: the returned value. -/
def merkle_root (perm : Perm) (leaf idx : F) (ch : Nat → Fin 4 → F) : F := (merkleGo perm leaf idx ch 4).cur

/-- All asserts inside `merkle_root` hold. -/
def merkle_ok (perm : Perm) (leaf idx : F) (ch : Nat → Fin 4 → F) : Prop := (merkleGo perm leaf idx ch 4).ok

theorem merkle_ok_iff (perm : Perm) (leaf idx : F) (ch : Nat → Fin 4 → F) :
    merkle_ok perm leaf idx ch ↔ fits 8 idx ∧ leaf = selAt idx (ch 0) 0 ∧
      node_hash perm (ch 0) = selAt idx (ch 1) 1 ∧ node_hash perm (ch 1) = selAt idx (ch 2) 2 ∧
      node_hash perm (ch 2) = selAt idx (ch 3) 3 := by
  simp only [merkle_ok, merkleGo, and_assoc]

theorem merkle_root_eq (perm : Perm) (leaf idx : F) (ch : Nat → Fin 4 → F) :
    merkle_root perm leaf idx ch = node_hash perm (ch 3) := rfl

theorem sel_cases (c : Fin 4 → F) (y : Nat) :
    sel c ((y % 2 : Nat) : F) ((y / 2 % 2 : Nat) : F) = c (Fin.ofNat 4 (y % 4)) := by
  have e0 : Fin.ofNat 4 0 = (0 : Fin 4) := rfl
  have e1 : Fin.ofNat 4 1 = (1 : Fin 4) := rfl
  have e2 : Fin.ofNat 4 2 = (2 : Fin 4) := rfl
  have e3 : Fin.ofNat 4 3 = (3 : Fin 4) := rfl
  have h : y % 4 = 0 ∨ y % 4 = 1 ∨ y % 4 = 2 ∨ y % 4 = 3 := by omega
  rcases h with h | h | h | h
  · have a : y % 2 = 0 := by omega
    have b : y / 2 % 2 = 0 := by omega
    rw [a, b, h, e0]; simp only [sel, Nat.cast_zero]; ring
  · have a : y % 2 = 1 := by omega
    have b : y / 2 % 2 = 0 := by omega
    rw [a, b, h, e1]; simp only [sel, Nat.cast_zero, Nat.cast_one]; ring
  · have a : y % 2 = 0 := by omega
    have b : y / 2 % 2 = 1 := by omega
    rw [a, b, h, e2]; simp only [sel, Nat.cast_zero, Nat.cast_one]; ring
  · have a : y % 2 = 1 := by omega
    have b : y / 2 % 2 = 1 := by omega
    rw [a, b, h, e3]; simp only [sel, Nat.cast_one]; ring

theorem childIx_eq (n l : Nat) : (n >>> (2 * l)) &&& 3 = n / 4 ^ l % 4 := by
  have h3 : (3 : Nat) = 2 ^ 2 - 1 := by norm_num
  rw [h3, Nat.and_two_pow_sub_one_eq_mod, Nat.shiftRight_eq_div_pow, pow_mul]
  norm_num

theorem bits_of_level (n l : Nat) :
    n / 2 ^ (2 * l) = n / 4 ^ l ∧ n / 2 ^ (2 * l + 1) = n / 4 ^ l / 2 := by
  have h : (2 : Nat) ^ (2 * l) = 4 ^ l := by rw [pow_mul]; norm_num
  refine ⟨by rw [h], ?_⟩
  rw [pow_succ, h, Nat.div_div_eq_div_mul]

/-- **The selector picks the right child.** At level `l`, the polynomial on line 116 equals child number
`(idx >> 2l) & 3`. So the path goes through the child the leaf index says, and the prover has no choice. -/
theorem selector_picks (idx : F) (c : Fin 4 → F) (l : Nat) :
    selAt idx c l = c (Fin.ofNat 4 ((idx.val >>> (2 * l)) &&& 3)) := by
  obtain ⟨h1, h2⟩ := bits_of_level idx.val l
  rw [childIx_eq]
  unfold selAt bit
  rw [h1, h2]
  exact sel_cases c _

/-- Collision hypothesis for `node_hash`, at exactly these two inputs. -/
def NodeBinds (perm : Perm) (c c' : Fin 4 → F) : Prop :=
  node_hash perm c = node_hash perm c' → c = c'

/-- Collision hypothesis for `leaf_hash`, at exactly these two inputs. Both are 69 elements long. -/
def LeafBinds (perm : Perm) (x : Nat → Nat) (b : Nat) (y : Nat → Nat) (b' : Nat) : Prop :=
  leaf_hash perm x b = leaf_hash perm y b' → leafElems x b = leafElems y b'

theorem merkle_two_openings (perm : Perm) (leaf leaf' idx : F) (ch ch' : Nat → Fin 4 → F)
    (hok : merkle_ok perm leaf idx ch) (hok' : merkle_ok perm leaf' idx ch')
    (hroot : merkle_root perm leaf idx ch = merkle_root perm leaf' idx ch')
    (hb : ∀ l, l < 4 → NodeBinds perm (ch l) (ch' l)) : leaf = leaf' := by
  obtain ⟨_, a0, a1, a2, a3⟩ := (merkle_ok_iff perm leaf idx ch).1 hok
  obtain ⟨_, b0, b1, b2, b3⟩ := (merkle_ok_iff perm leaf' idx ch').1 hok'
  have h3 : ch 3 = ch' 3 := hb 3 (by norm_num) hroot
  have h2 : ch 2 = ch' 2 := hb 2 (by norm_num) (by rw [a3, b3, h3])
  have h1 : ch 1 = ch' 1 := hb 1 (by norm_num) (by rw [a2, b2, h2])
  have h0 : ch 0 = ch' 0 := hb 0 (by norm_num) (by rw [a1, b1, h1])
  rw [a0, b0, h0]

/-- **Two openings of one leaf index under one root agree, IF the hash has no collision there.** Suppose two
witnesses open the same leaf index under the same root, reading 1024 `u16` samples each. If Poseidon2 has no
collision at the nodes and leaves along these two paths, the samples are the same. So the root fixes the samples,
at most one way per leaf. The two sides may be different arrays at different offsets. -/
theorem two_openings_agree (perm : Perm) (x y : Nat → Nat) (b b' : Nat) (idx : F) (ch ch' : Nat → Fin 4 → F)
    (hx : ∀ k, k < 1024 → x (b + k) < 65536) (hy : ∀ k, k < 1024 → y (b' + k) < 65536)
    (hok : merkle_ok perm (leaf_hash perm x b) idx ch) (hok' : merkle_ok perm (leaf_hash perm y b') idx ch')
    (hroot : merkle_root perm (leaf_hash perm x b) idx ch = merkle_root perm (leaf_hash perm y b') idx ch')
    (hn : ∀ l, l < 4 → NodeBinds perm (ch l) (ch' l)) (hl : LeafBinds perm x b y b') :
    ∀ k, k < 1024 → x (b + k) = y (b' + k) :=
  (leaf_packing_injective x y b b' hx hy).1 (hl (merkle_two_openings perm _ _ idx ch ch' hok hok' hroot hn))

/-- **If two openings disagree, the witness holds a Poseidon2 collision.** This is `two_openings_agree` with no
hypothesis at all: two accepted openings of one leaf under one root that differ in some sample hand you two
different inputs with the same hash, either at a node on the path or at the leaf. -/
theorem opening_mismatch_gives_collision (perm : Perm) (x y : Nat → Nat) (b b' : Nat) (idx : F)
    (ch ch' : Nat → Fin 4 → F)
    (hx : ∀ k, k < 1024 → x (b + k) < 65536) (hy : ∀ k, k < 1024 → y (b' + k) < 65536)
    (hok : merkle_ok perm (leaf_hash perm x b) idx ch) (hok' : merkle_ok perm (leaf_hash perm y b') idx ch')
    (hroot : merkle_root perm (leaf_hash perm x b) idx ch = merkle_root perm (leaf_hash perm y b') idx ch')
    (hdiff : ∃ k, k < 1024 ∧ x (b + k) ≠ y (b' + k)) :
    (∃ l, l < 4 ∧ ch l ≠ ch' l ∧ node_hash perm (ch l) = node_hash perm (ch' l)) ∨
    (leafElems x b ≠ leafElems y b' ∧ leaf_hash perm x b = leaf_hash perm y b') := by
  by_contra hno
  obtain ⟨k, hk, hne⟩ := hdiff
  apply hne
  refine two_openings_agree perm x y b b' idx ch ch' hx hy hok hok' hroot ?_ ?_ k hk
  · intro l hl heq
    by_contra hc
    exact hno (Or.inl ⟨l, hl, hc, heq⟩)
  · intro heq
    by_contra hc
    exact hno (Or.inr ⟨hc, heq⟩)

/-! ## The recording, as a function, and its honest tree -/

/-- What an honest builder computes (`server/pop/poseidon2.py` `rec_levels`, `OaHash.kt`): level 0 is
`leaf_hash` of samples `1024 j ..`, and node `j` of level `l + 1` hashes nodes `4j .. 4j+3` of level `l`.
`rcd` gives the stored `u = sample + 32768` at each index. Every leaf is hashed, samples past the capture are 32768. -/
def nodeAt (perm : Perm) (rcd : Nat → Nat) : Nat → Nat → F
  | 0, j => leaf_hash perm rcd (1024 * j)
  | l + 1, j => node_hash perm (fun c : Fin 4 => nodeAt perm rcd l (4 * j + c.val))

/-- The four children of node `j` of level `l + 1`. -/
def children (perm : Perm) (rcd : Nat → Nat) (l j : Nat) : Fin 4 → F :=
  fun c => nodeAt perm rcd l (4 * j + c.val)

/-- The root of the depth-4, 256-leaf tree over `rcd`. -/
def recRoot (perm : Perm) (rcd : Nat → Nat) : F := nodeAt perm rcd 4 0

theorem selAt_children (perm : Perm) (rcd : Nat → Nat) (idx : F) (n l : Nat) (hv : idx.val = n) :
    selAt idx (children perm rcd l (n / 4 ^ (l + 1))) l = nodeAt perm rcd l (n / 4 ^ l) := by
  rw [selector_picks, hv, childIx_eq]
  have h1 : n / 4 ^ (l + 1) = n / 4 ^ l / 4 := by rw [pow_succ, Nat.div_div_eq_div_mul]
  have hv2 : (Fin.ofNat 4 (n / 4 ^ l % 4)).val = n / 4 ^ l % 4 := by simp [Fin.ofNat]
  unfold children
  rw [hv2, h1]
  congr 1
  omega

theorem tie_step (perm : Perm) (rcd : Nat → Nat) (idx : F) (n l : Nat) (hv : idx.val = n) (c : Fin 4 → F)
    (hb : NodeBinds perm c (children perm rcd l (n / 4 ^ (l + 1))))
    (h : node_hash perm c = nodeAt perm rcd (l + 1) (n / 4 ^ (l + 1))) :
    selAt idx c l = nodeAt perm rcd l (n / 4 ^ l) := by
  rw [hb h]
  exact selAt_children perm rcd idx n l hv

/-- **The path leads from the root of the recording down to its leaf.** If an accepted path ends at the root of
the tree over `rcd`, and Poseidon2 has no collision against the true nodes along the way, the `leaf` at the
bottom is the true leaf number `idx` of `rcd`. -/
theorem merkle_tie (perm : Perm) (rcd : Nat → Nat) (leaf idx : F) (ch : Nat → Fin 4 → F)
    (hok : merkle_ok perm leaf idx ch) (hroot : merkle_root perm leaf idx ch = recRoot perm rcd)
    (hb : ∀ l, l < 4 → NodeBinds perm (ch l) (children perm rcd l (idx.val / 4 ^ (l + 1)))) :
    leaf = nodeAt perm rcd 0 idx.val := by
  obtain ⟨hf, a0, a1, a2, a3⟩ := (merkle_ok_iff perm leaf idx ch).1 hok
  have hn : idx.val < 256 := lt_of_lt_of_eq hf (by norm_num)
  have htop : node_hash perm (ch 3) = nodeAt perm rcd 4 (idx.val / 4 ^ 4) := by
    have h0 : idx.val / 4 ^ 4 = 0 := Nat.div_eq_of_lt (by norm_num; omega)
    rw [h0]
    exact hroot
  have s3 := tie_step perm rcd idx idx.val 3 rfl (ch 3) (hb 3 (by norm_num)) htop
  have s2 := tie_step perm rcd idx idx.val 2 rfl (ch 2) (hb 2 (by norm_num)) (a3.trans s3)
  have s1 := tie_step perm rcd idx idx.val 1 rfl (ch 1) (hb 1 (by norm_num)) (a2.trans s2)
  have s0 := tie_step perm rcd idx idx.val 0 rfl (ch 0) (hb 0 (by norm_num)) (a1.trans s1)
  have := a0.trans s0
  simpa using this

/-! ## Block B: `open_leaves` (lib.nr 124-130) -/

/-- line 29 -/
abbrev NL : Nat := 13

/-- lines 124-130: for each `i < NL`, `h = leaf_hash(x, i * 1024)`, `r = merkle_root(h, first + i, ch[i])`,
`assert(r == root)`. -/
def open_leaves (perm : Perm) (x : Nat → Nat) (first : F) (ch : Nat → Nat → Fin 4 → F) (root : F) : Prop :=
  ∀ i, i < NL →
    merkle_ok perm (leaf_hash perm x (i * 1024)) (first + (i : F)) (ch i) ∧
    merkle_root perm (leaf_hash perm x (i * 1024)) (first + (i : F)) (ch i) = root

theorem val_add_of_lt (f i : Nat) (h : f + i < 2 ^ 9) : (((f : F) + (i : F)) : F).val = f + i := by
  rw [← Nat.cast_add]
  exact val_natCast_of_lt (natCast_lt_p_of_lt_two_pow (by norm_num) h)

/-- **The leaf range comes from the circuit, it is not assumed.** If `open_leaves` accepts, `first` is a true whole
number `f` with `f + 12 < 256`, because each of the 13 indices must pass the 8-bit check, and `first` cannot wrap
around the field to dodge it. So the 13 leaves are 13 contiguous real leaves. -/
theorem open_leaves_first (perm : Perm) (x : Nat → Nat) (first : F) (ch : Nat → Nat → Fin 4 → F) (root : F)
    (h : open_leaves perm x first ch root) : ∃ f : Nat, first = (f : F) ∧ f + 12 < 256 := by
  have h0 := ((merkle_ok_iff _ _ _ _).1 (h 0 (by norm_num)).1).1
  have h12 := ((merkle_ok_iff _ _ _ _).1 (h 12 (by norm_num)).1).1
  rw [Nat.cast_zero, add_zero] at h0
  obtain ⟨f, hf, rfl⟩ := fits_exists_nat h0
  refine ⟨f, rfl, ?_⟩
  have hf' : f < 256 := lt_of_lt_of_eq hf (by norm_num)
  have hv := val_add_of_lt f 12 (by omega)
  have : ((f : F) + ((12 : Nat) : F)).val < 2 ^ 8 := h12
  rw [hv] at this
  omega

/-- Collision hypothesis for one opening against the tree over `rcd`: at exactly the nodes and leaves on each of
the 13 paths. -/
def BindsToRecording (perm : Perm) (rcd x : Nat → Nat) (first : F) (ch : Nat → Nat → Fin 4 → F) : Prop :=
  ∀ i, i < 13 →
    (∀ l, l < 4 → NodeBinds perm (ch i l) (children perm rcd l ((first + (i : F)).val / 4 ^ (l + 1)))) ∧
    LeafBinds perm x (i * 1024) rcd (1024 * (first + (i : F)).val)

/-- **The opened array is the committed recording, leaf by leaf.** If `open_leaves` accepts under the root of the
tree over the recording `rcd`, and Poseidon2 has no collision along these paths (`BindsToRecording`, assumed), then
sample `1024 i + k` of the array is sample `1024 (first + i) + k` of the recording, for all 13 leaves and all 1024
samples of each, with `first + 12 < 256`. -/
theorem open_leaves_ties (perm : Perm) (rcd x : Nat → Nat) (first : F) (ch : Nat → Nat → Fin 4 → F)
    (hx : ∀ j, j < 13312 → x j < 2 ^ 16) (hrcd : ∀ n, rcd n < 2 ^ 16)
    (hopen : open_leaves perm x first ch (recRoot perm rcd))
    (hb : BindsToRecording perm rcd x first ch) :
    ∃ f : Nat, first = (f : F) ∧ f + 12 < 256 ∧
      ∀ i, i < 13 → ∀ k, k < 1024 → x (1024 * i + k) = rcd (1024 * (f + i) + k) := by
  obtain ⟨f, rfl, hf⟩ := open_leaves_first perm x first ch _ hopen
  refine ⟨f, rfl, hf, ?_⟩
  intro i hi k hk
  obtain ⟨hok, hroot⟩ := hopen i hi
  obtain ⟨hn, hl⟩ := hb i hi
  have hv := val_add_of_lt f i (by omega)
  have ht := merkle_tie perm rcd _ _ (ch i) hok hroot hn
  have hsam := (leaf_packing_injective x rcd (i * 1024) (1024 * ((f : F) + (i : F)).val)
    (fun idx hidx => by have := hx (i * 1024 + idx) (by omega); omega)
    (fun idx _ => by have := hrcd (1024 * ((f : F) + (i : F)).val + idx); omega)).1 (hl ht) k hk
  rw [hv] at hsam
  rw [Nat.mul_comm 1024 i]
  exact hsam

/-! ## Honest prover: the circuit accepts, and the hypotheses hold -/

/-- The array an honest prover supplies: the recording from leaf `f` on. -/
def honestXs (rcd : Nat → Nat) (f : Nat) : Nat → Nat := fun n => rcd (1024 * f + n)

/-- The paths an honest prover supplies (`rec_path` in `server/pop/poseidon2.py`). -/
def honestCh (perm : Perm) (rcd : Nat → Nat) (f i l : Nat) : Fin 4 → F :=
  children perm rcd l ((f + i) / 4 ^ (l + 1))

theorem honest_leaf_elems (rcd : Nat → Nat) (f i : Nat) :
    leafElems (honestXs rcd f) (i * 1024) = leafElems rcd (1024 * (f + i)) :=
  leafElems_congr _ _ _ _ (fun idx _ => by
    unfold honestXs
    congr 1
    ring)

/-- **An honest prover is accepted.** For any recording and any `f` with `f + 12 < 256`, the true samples and
true paths pass `open_leaves` under the true root. This needs no hash assumption. So `open_leaves_ties` does not
rest on an impossible situation. -/
theorem open_leaves_complete (perm : Perm) (rcd : Nat → Nat) (f : Nat) (hf : f + 12 < 256) :
    open_leaves perm (honestXs rcd f) (f : F) (honestCh perm rcd f) (recRoot perm rcd) := by
  intro i hi
  have hi' : i < 13 := hi
  have hv : ((f : F) + (i : F)).val = f + i := val_add_of_lt f i (by omega)
  have sel_n := fun l => selAt_children perm rcd ((f : F) + (i : F)) (f + i) l hv
  have hleaf : leaf_hash perm (honestXs rcd f) (i * 1024) = nodeAt perm rcd 0 (f + i) := by
    show hash_n perm TAG_LEAF _ = hash_n perm TAG_LEAF _
    rw [honest_leaf_elems]
  have s0 := sel_n 0
  rw [pow_zero, Nat.div_one] at s0
  constructor
  · refine (merkle_ok_iff _ _ _ _).2 ⟨?_, hleaf.trans s0.symm, (sel_n 1).symm, (sel_n 2).symm, (sel_n 3).symm⟩
    show ((f : F) + (i : F)).val < 2 ^ 8
    rw [hv]
    omega
  · rw [merkle_root_eq]
    show node_hash perm (children perm rcd 3 ((f + i) / 4 ^ (3 + 1))) = nodeAt perm rcd 4 0
    have h0 : (f + i) / 4 ^ (3 + 1) = 0 := Nat.div_eq_of_lt (by norm_num; omega)
    rw [h0]
    rfl

/-- **The collision hypothesis is not empty.** For an honest prover, `BindsToRecording` holds for EVERY permutation,
since the two sides are literally the same input. So the hypothesis of `open_leaves_ties` can be met. It only rules
out a witness that actually holds a collision. -/
theorem honest_binds (perm : Perm) (rcd : Nat → Nat) (f : Nat) (hf : f + 12 < 256) :
    BindsToRecording perm rcd (honestXs rcd f) (f : F) (honestCh perm rcd f) := by
  intro i hi
  have hv : ((f : F) + (i : F)).val = f + i := val_add_of_lt f i (by omega)
  rw [hv]
  refine ⟨fun l _ _ => rfl, fun _ => honest_leaf_elems rcd f i⟩

/-! ## Tie to the windows of `phone_core` (lib.nr 503-508) -/

theorem window_of_ties (x rcd : Nat → Nat) (f : Nat)
    (ties : ∀ i, i < 13 → ∀ k, k < 1024 → x (1024 * i + k) = rcd (1024 * (f + i) + k))
    (j : Nat) (hj : j < 13312) : x j = rcd (1024 * f + j) := by
  have := ties (j / 1024) (by omega) (j % 1024) (by omega)
  rwa [show 1024 * (j / 1024) + j % 1024 = j by omega,
    show 1024 * (f + j / 1024) + j % 1024 = 1024 * f + j by omega] at this

theorem self_window_of_ties (t : Nat → Nat) (ht : bytesOK t) (leaf_s : F) (f : Nat) (hfe : leaf_s = (f : F))
    (hf : f < 256) (hos : fits 10 (osF t leaf_s)) (xs rcd : Nat → Nat)
    (ties : ∀ i, i < 13 → ∀ k, k < 1024 → xs (1024 * i + k) = rcd (1024 * (f + i) + k)) :
    0 ≤ pSelf t - 96 - 31 ∧ ∀ i, i < 12254 →
      asU32 (osF t leaf_s) + i < 13312 ∧
      ∃ idx : Nat, (idx : Int) = pSelf t - 96 - 31 + i ∧ xs (asU32 (osF t leaf_s) + i) = rcd idx := by
  have hleaf : fits 8 leaf_s := by
    rw [hfe]
    exact fits_natCast (by norm_num) (lt_of_lt_of_eq hf (by norm_num))
  obtain ⟨ls, _, hs, _, hsv, h0, h1⟩ := os_window t leaf_s ht hleaf hos
  have hlsf : ls = f := natCast_inj_of_lt
    (natCast_lt_p_of_lt_two_pow (k := 8) (by norm_num) (by rename_i h; omega))
    (natCast_lt_p_of_lt_two_pow (k := 8) (by norm_num) (by omega)) (hs.symm.trans hfe)
  subst hlsf
  rw [asU32_of_fits hos]
  have hnn : (0 : Int) ≤ (ls : Int) := by omega
  refine ⟨by omega, fun i hi => ?_⟩
  have hj : (osF t leaf_s).val + i < 13312 := by omega
  refine ⟨hj, 1024 * ls + ((osF t leaf_s).val + i), by push_cast; omega, ?_⟩
  exact window_of_ties xs rcd ls ties _ hj

theorem partner_window_of_ties (t : Nat → Nat) (role_b : Bool) (ht : bytesOK t) (leaf_p : F) (f : Nat)
    (hfe : leaf_p = (f : F)) (hf : f < 256) (hop : fits 10 (opF t role_b leaf_p)) (xp rcd : Nat → Nat)
    (ties : ∀ i, i < 13 → ∀ k, k < 1024 → xp (1024 * i + k) = rcd (1024 * (f + i) + k)) :
    0 ≤ aPartner t role_b - 31 ∧ ∀ i, i < 12062 →
      asU32 (opF t role_b leaf_p) + i < 13312 ∧
      ∃ idx : Nat, (idx : Int) = aPartner t role_b - 31 + i ∧ xp (asU32 (opF t role_b leaf_p) + i) = rcd idx := by
  have hleaf : fits 8 leaf_p := by
    rw [hfe]
    exact fits_natCast (by norm_num) (lt_of_lt_of_eq hf (by norm_num))
  obtain ⟨ls, _, hs, _, hsv, h0, h1⟩ := op_window t role_b leaf_p ht hleaf hop
  have hlsf : ls = f := natCast_inj_of_lt
    (natCast_lt_p_of_lt_two_pow (k := 8) (by norm_num) (by rename_i h; omega))
    (natCast_lt_p_of_lt_two_pow (k := 8) (by norm_num) (by omega)) (hs.symm.trans hfe)
  subst hlsf
  rw [asU32_of_fits hop]
  have hnn : (0 : Int) ≤ (ls : Int) := by omega
  refine ⟨by omega, fun i hi => ?_⟩
  have hj : (opF t role_b leaf_p).val + i < 13312 := by omega
  refine ⟨hj, 1024 * ls + ((opF t role_b leaf_p).val + i), by push_cast; omega, ?_⟩
  exact window_of_ties xp rcd ls ties _ hj

/-- **Both windows of `phone_core` are the recording, at the right place.** Take a recording `rcd`, and ASSUME the
`rec_root` the openings use is the honest tree's root over it (`recRoot perm rcd`). This theorem does not tie that root
to the transcript bytes `t[177..209]` (`lib.nr` 279), or to any signature. If `phone_core` accepts the offsets `os`, `op` and both `open_leaves` calls, and Poseidon2 has no
collision along these paths (assumed):
* `xs[os + i]` is recording sample `p_self - 96 - 31 + i`, for every `i` of the self window (`NS = 12254`);
* `xp[op + i]` is recording sample `a_partner - 31 + i`, for every `i` of the partner window (`NP = 12062`);
* both index ranges stay inside the arrays, and the sample numbers are true non-negative whole numbers.

This is what block F's offsets were waiting for. It says which samples the arrival rule and the partner test read.
It says nothing about whether those samples came from a mic, or lie within the real capture. -/
theorem phone_core_windows_are_recording (perm : Perm) (t : Nat → Nat) (role_b : Bool) (leaf_s leaf_p : F)
    (xs xp rcd : Nat → Nat) (chs chp : Nat → Nat → Fin 4 → F) (ht : bytesOK t)
    (hxs : ∀ j, j < 13312 → xs j < 2 ^ 16) (hxp : ∀ j, j < 13312 → xp j < 2 ^ 16) (hrcd : ∀ n, rcd n < 2 ^ 16)
    (hos : fits 10 (osF t leaf_s)) (hop : fits 10 (opF t role_b leaf_p))
    (hs : open_leaves perm xs leaf_s chs (recRoot perm rcd))
    (hp : open_leaves perm xp leaf_p chp (recRoot perm rcd))
    (bs : BindsToRecording perm rcd xs leaf_s chs) (bp : BindsToRecording perm rcd xp leaf_p chp) :
    (0 ≤ pSelf t - 96 - 31 ∧ ∀ i, i < 12254 →
      asU32 (osF t leaf_s) + i < 13312 ∧
      ∃ idx : Nat, (idx : Int) = pSelf t - 96 - 31 + i ∧ xs (asU32 (osF t leaf_s) + i) = rcd idx) ∧
    (0 ≤ aPartner t role_b - 31 ∧ ∀ i, i < 12062 →
      asU32 (opF t role_b leaf_p) + i < 13312 ∧
      ∃ idx : Nat, (idx : Int) = aPartner t role_b - 31 + i ∧ xp (asU32 (opF t role_b leaf_p) + i) = rcd idx) := by
  obtain ⟨f, hfe, hf, ties⟩ := open_leaves_ties perm rcd xs leaf_s chs hxs hrcd hs bs
  obtain ⟨g, hge, hg, tiep⟩ := open_leaves_ties perm rcd xp leaf_p chp hxp hrcd hp bp
  exact ⟨self_window_of_ties t ht leaf_s f hfe (by omega) hos xs rcd ties,
    partner_window_of_ties t role_b ht leaf_p g hge (by omega) hop xp rcd tiep⟩

/-- A transcript for `phone_core_windows_nonvacuous`: bytes `t[271] = 4`, `t[272] = 200`, the rest 0. So
`a_self = 1224`, and `half = sod = 0`. -/
def tWin (i : Nat) : Nat := if i = 271 then 4 else if i = 272 then 200 else 0

/-- **`phone_core_windows_are_recording` is not empty.** Here is one concrete case where all its premises hold at once,
for every permutation and every recording of `u16` samples. Transcript `tWin`, so `a_self = p_self = a_partner = 1224`,
role A, both openings start at leaf 1, and the arrays are the honest ones. Then `os = 73`, `op = 169`, and the windows
read recording samples `1097 + i` and `1193 + i`, which are `p_self - 96 - 31 + i` and `a_partner - 31 + i`. It shows
the premises can be met. It is a toy transcript, not a realistic signal. -/
theorem phone_core_windows_nonvacuous (perm : Perm) (rcd : Nat → Nat) (hrcd : ∀ n, rcd n < 2 ^ 16) :
    bytesOK tWin ∧
    (∀ j, j < 13312 → honestXs rcd 1 j < 2 ^ 16) ∧
    fits 10 (osF tWin ((1 : Nat) : F)) ∧ fits 10 (opF tWin false ((1 : Nat) : F)) ∧
    open_leaves perm (honestXs rcd 1) ((1 : Nat) : F) (honestCh perm rcd 1) (recRoot perm rcd) ∧
    BindsToRecording perm rcd (honestXs rcd 1) ((1 : Nat) : F) (honestCh perm rcd 1) ∧
    pSelf tWin - 96 - 31 = 1097 ∧ aPartner tWin false - 31 = 1193 ∧
    asU32 (osF tWin ((1 : Nat) : F)) = 73 ∧ asU32 (opF tWin false ((1 : Nat) : F)) = 169 ∧
    (∀ i, honestXs rcd 1 (asU32 (osF tWin ((1 : Nat) : F)) + i) = rcd (1097 + i)) ∧
    (∀ i, honestXs rcd 1 (asU32 (opF tWin false ((1 : Nat) : F)) + i) = rcd (1193 + i)) := by
  have ht : bytesOK tWin := by
    intro i _; unfold tWin; split_ifs <;> norm_num
  have hA : PartnerGlue.aSelf tWin = 1224 := by decide
  have hH : PartnerGlue.half tWin = 0 := by decide
  have hS : PartnerGlue.sod tWin = 0 := by decide
  have hPS : pSelf tWin = 1224 := by simp [pSelf, hA, hS]
  have hAP : aPartner tWin false = 1224 := by simp [aPartner, PartnerGlue.sg, hA, hH]
  have eos : osF tWin ((1 : Nat) : F) = ((73 : Nat) : F) := by
    rw [PartnerGlue.osF_cast tWin 1 ht, hPS]; norm_num
  have eop : opF tWin false ((1 : Nat) : F) = ((169 : Nat) : F) := by
    rw [PartnerGlue.opF_cast tWin false 1 ht, hAP]; norm_num
  have fos : fits 10 (osF tWin ((1 : Nat) : F)) := by
    rw [eos]; exact fits_natCast (by norm_num) (by norm_num)
  have fop : fits 10 (opF tWin false ((1 : Nat) : F)) := by
    rw [eop]; exact fits_natCast (by norm_num) (by norm_num)
  have vos : asU32 (osF tWin ((1 : Nat) : F)) = 73 := by
    rw [asU32_of_fits fos, eos]
    exact val_natCast_of_lt (natCast_lt_p_of_lt_two_pow (k := 10) (by norm_num) (by norm_num))
  have vop : asU32 (opF tWin false ((1 : Nat) : F)) = 169 := by
    rw [asU32_of_fits fop, eop]
    exact val_natCast_of_lt (natCast_lt_p_of_lt_two_pow (k := 10) (by norm_num) (by norm_num))
  refine ⟨ht, fun j _ => hrcd _, fos, fop, open_leaves_complete perm rcd 1 (by norm_num),
    honest_binds perm rcd 1 (by norm_num), by rw [hPS]; norm_num, by rw [hAP]; norm_num, vos, vop,
    fun i => ?_, fun i => ?_⟩
  · rw [vos]
    show rcd (1024 * 1 + (73 + i)) = rcd (1097 + i)
    congr 1
    omega
  · rw [vop]
    show rcd (1024 * 1 + (169 + i)) = rcd (1193 + i)
    congr 1
    omega

/-- Collision hypothesis between two `open_leaves` calls under one root: at the paths of any leaf they share. -/
def OpeningsBind (perm : Perm) (x : Nat → Nat) (first : F) (ch : Nat → Nat → Fin 4 → F)
    (y : Nat → Nat) (first' : F) (ch' : Nat → Nat → Fin 4 → F) : Prop :=
  ∀ i : Nat, i < 13 → ∀ i' : Nat, i' < 13 → first + (i : F) = first' + (i' : F) →
    (∀ l, l < 4 → NodeBinds perm (ch i l) (ch' i' l)) ∧ LeafBinds perm x (i * 1024) y (i' * 1024)

/-- The recording that two openings define: take the self opening where it covers, then the partner opening, and
filler elsewhere. -/
def glued (xs : Nat → Nat) (fs : Nat) (xp : Nat → Nat) (fp : Nat) (n : Nat) : Nat :=
  if fs ≤ n / 1024 ∧ n / 1024 < fs + 13 then xs (1024 * (n / 1024 - fs) + n % 1024)
  else if fp ≤ n / 1024 ∧ n / 1024 < fp + 13 then xp (1024 * (n / 1024 - fp) + n % 1024)
  else 32768

/-- **One root, one recording, whatever the root is.** `phone_core` opens `xs` and `xp` under the same
`rec_root`, and nothing says that root came from an honest tree. Even so: if Poseidon2 has no collision at the
nodes and the leaves on the paths the two openings share (`OpeningsBind`, assumed), there is ONE recording of `u16` samples that both windows read. `xs[os + i]`
is its sample `p_self - 96 - 31 + i` and `xp[op + i]` is its sample `a_partner - 31 + i`. So the prover cannot show
one version of a leaf to the self check and another to the partner check. This does not show that `rec_root` is the
root of a tree over that recording: where neither opening covers a leaf the recording is just filler. -/
theorem phone_core_one_recording (perm : Perm) (t : Nat → Nat) (role_b : Bool) (leaf_s leaf_p rec_root : F)
    (xs xp : Nat → Nat) (chs chp : Nat → Nat → Fin 4 → F) (ht : bytesOK t)
    (hxs : ∀ j, j < 13312 → xs j < 2 ^ 16) (hxp : ∀ j, j < 13312 → xp j < 2 ^ 16)
    (hos : fits 10 (osF t leaf_s)) (hop : fits 10 (opF t role_b leaf_p))
    (hs : open_leaves perm xs leaf_s chs rec_root) (hp : open_leaves perm xp leaf_p chp rec_root)
    (hb : OpeningsBind perm xs leaf_s chs xp leaf_p chp) :
    ∃ rcd : Nat → Nat, (∀ n, rcd n < 2 ^ 16) ∧
    (0 ≤ pSelf t - 96 - 31 ∧ ∀ i, i < 12254 →
      asU32 (osF t leaf_s) + i < 13312 ∧
      ∃ idx : Nat, (idx : Int) = pSelf t - 96 - 31 + i ∧ xs (asU32 (osF t leaf_s) + i) = rcd idx) ∧
    (0 ≤ aPartner t role_b - 31 ∧ ∀ i, i < 12062 →
      asU32 (opF t role_b leaf_p) + i < 13312 ∧
      ∃ idx : Nat, (idx : Int) = aPartner t role_b - 31 + i ∧ xp (asU32 (opF t role_b leaf_p) + i) = rcd idx) := by
  obtain ⟨fs, hfs, hfs'⟩ := open_leaves_first perm xs leaf_s chs _ hs
  obtain ⟨fp, hfp, hfp'⟩ := open_leaves_first perm xp leaf_p chp _ hp
  have hu : ∀ n, glued xs fs xp fp n < 2 ^ 16 := by
    intro n
    unfold glued
    split
    · exact hxs _ (by omega)
    · split
      · exact hxp _ (by omega)
      · norm_num
  have ties : ∀ i, i < 13 → ∀ k, k < 1024 →
      xs (1024 * i + k) = glued xs fs xp fp (1024 * (fs + i) + k) := by
    intro i hi k hk
    have hq : (1024 * (fs + i) + k) / 1024 = fs + i := by omega
    have hr : (1024 * (fs + i) + k) % 1024 = k := by omega
    unfold glued
    rw [hq, hr, if_pos ⟨by omega, by omega⟩, Nat.add_sub_cancel_left]
  have tiep : ∀ i, i < 13 → ∀ k, k < 1024 →
      xp (1024 * i + k) = glued xs fs xp fp (1024 * (fp + i) + k) := by
    intro i hi k hk
    have hq : (1024 * (fp + i) + k) / 1024 = fp + i := by omega
    have hr : (1024 * (fp + i) + k) % 1024 = k := by omega
    unfold glued
    rw [hq, hr]
    by_cases c : fs ≤ fp + i ∧ fp + i < fs + 13
    · rw [if_pos c]
      have hi2 : fp + i - fs < 13 := by omega
      have hidx : leaf_s + ((fp + i - fs : Nat) : F) = leaf_p + (i : F) := by
        rw [hfs, hfp, ← Nat.cast_add, ← Nat.cast_add]
        congr 1
        omega
      obtain ⟨hn, hl⟩ := hb _ hi2 i hi hidx
      obtain ⟨ok1, rt1⟩ := hs _ hi2
      obtain ⟨ok2, rt2⟩ := hp i hi
      rw [hidx] at ok1 rt1
      have := two_openings_agree perm xs xp ((fp + i - fs) * 1024) (i * 1024) _ _ _
        (fun k hk => by have := hxs ((fp + i - fs) * 1024 + k) (by omega); omega)
        (fun k hk => by have := hxp (i * 1024 + k) (by omega); omega)
        ok1 ok2 (rt1.trans rt2.symm) hn hl k hk
      rw [Nat.mul_comm 1024 (fp + i - fs), Nat.mul_comm 1024 i]
      exact this.symm
    · rw [if_neg c, if_pos ⟨by omega, by omega⟩, Nat.add_sub_cancel_left]
  exact ⟨glued xs fs xp fp, hu,
    self_window_of_ties t ht leaf_s fs hfs (by omega) hos xs _ ties,
    partner_window_of_ties t role_b ht leaf_p fp hfp (by omega) hop xp _ tiep⟩

/-! ## Hole: the tree has no length, so a window can sit past the capture -/

/-- **A real recording can pass the partner test past its own end.** The tree always has 256 leaves, and the
builder pads with 32768 (silence) past the capture (`OaHash.kt`, `server/pop/poseidon2.py`). Nothing in the transcript
or the circuit gives the capture length. So take ANY recording whose samples from `n` on are padding, and any leaf
`f` past `n` with `f + 12 < 256`. The honest opening at `f` is accepted under the honest root, for any permutation,
and `partner_side` accepts at any offset the circuit allows (`o < 1024`), for any in-range templates. The theorem has
no bound on `o` because the model has no array bounds; real Noir fails on `xp[o + i]` once `o + 12061 >= 13312`, and
every `o < 1024` is inside that.

This is the silence gap (`partner_silence_accepts`) reached without a silent capture: only the padding past the end is
silent. The app's flat-run check (`PopDsp.flatRuns`) looks at the capture, not the padding, so it would not see this
when the capture has no flat runs (see `past_capture_witness`). A signer still has to sign the `a_partner` that
lands there, so it needs a dishonest signer, same as the silence gap. Not run through `nargo`. -/
theorem past_capture_window_passes (perm : Perm) (rcd ci cq : Nat → Nat) (n f o : Nat)
    (hpad : ∀ j, n ≤ j → rcd j = 32768) (hpast : n ≤ 1024 * f) (hf : f + 12 < 256)
    (hci : ∀ m, m < 12000 → ci m < 256) (hcq : ∀ m, m < 12000 → cq m < 256) :
    open_leaves perm (honestXs rcd f) (f : F) (honestCh perm rcd f) (recRoot perm rcd) ∧
    partnerAccepts (honestXs rcd f) o ci cq :=
  ⟨open_leaves_complete perm rcd f hf,
    partner_silence_accepts _ o ci cq (fun i _ => hpad _ (by omega)) hci hcq⟩

/-- A 2.5 s capture at 48 kHz that wiggles one step around silence on every sample: `u = 32769, 32767, 32769, ...`.
It is very quiet, not loud. What matters is that no sample is silent and no two neighbours are equal. -/
def wigglyCapture (j : Nat) : Nat := if j < 120000 then (if j % 2 = 0 then 32769 else 32767) else 32768

/-- **Concrete witness for `past_capture_window_passes`.** A capture 120000 samples long, with no silent sample and no
two equal neighbours, so `PopDsp.flatRuns`, which flags runs of equal samples of any value, finds nothing in it. Leaf
118 starts at sample 120832, past the end. Opening there is accepted, and `partner_side` passes at offset 0, for any
in-range templates. -/
theorem past_capture_witness (perm : Perm) (ci cq : Nat → Nat)
    (hci : ∀ m, m < 12000 → ci m < 256) (hcq : ∀ m, m < 12000 → cq m < 256) :
    (∀ j, j < 120000 → wigglyCapture j ≠ 32768) ∧
    (∀ j, j + 1 < 120000 → wigglyCapture j ≠ wigglyCapture (j + 1)) ∧
    open_leaves perm (honestXs wigglyCapture 118) ((118 : Nat) : F) (honestCh perm wigglyCapture 118) (recRoot perm wigglyCapture) ∧
    partnerAccepts (honestXs wigglyCapture 118) 0 ci cq := by
  refine ⟨fun j hj => ?_, fun j hj => ?_,
    past_capture_window_passes perm wigglyCapture ci cq 120000 118 0 ?_ (by norm_num) (by norm_num) hci hcq⟩
  · unfold wigglyCapture
    rw [if_pos hj]
    split <;> norm_num
  · unfold wigglyCapture
    rw [if_pos (by omega), if_pos hj]
    split <;> split <;> omega
  · intro j hj
    simp [wigglyCapture, Nat.not_lt.2 hj]

end Commit
end Popfv

#print axioms Popfv.Commit.sponge_zero_tail_collision
#print axioms Popfv.Commit.chunk_lt_two_pow_248
#print axioms Popfv.Commit.chunk_last_short
#print axioms Popfv.Commit.packing_injective
#print axioms Popfv.Commit.absorbed_determines_templates
#print axioms Popfv.Commit.code_commitment_binds
#print axioms Popfv.Commit.code_commitment_congr
#print axioms Popfv.Commit.leaf_packing_injective
#print axioms Popfv.Commit.node_hash_not_injective
#print axioms Popfv.Commit.selector_picks
#print axioms Popfv.Commit.two_openings_agree
#print axioms Popfv.Commit.opening_mismatch_gives_collision
#print axioms Popfv.Commit.merkle_tie
#print axioms Popfv.Commit.open_leaves_first
#print axioms Popfv.Commit.open_leaves_ties
#print axioms Popfv.Commit.open_leaves_complete
#print axioms Popfv.Commit.honest_binds
#print axioms Popfv.Commit.phone_core_windows_are_recording
#print axioms Popfv.Commit.phone_core_windows_nonvacuous
#print axioms Popfv.Commit.phone_core_one_recording
#print axioms Popfv.Commit.past_capture_window_passes
#print axioms Popfv.Commit.past_capture_witness
