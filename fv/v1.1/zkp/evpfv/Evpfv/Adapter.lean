/-!
# Evpfv.Adapter — hand model of `verifyPresence`

Source: `examples/evp-recovery/contracts/src/pop/EvpNoirPresenceVerifier.sol`, lines 75-98,
plus the helpers `_ccOk` (107-121), `_issuerOk` (123-126) and `PopCtx.split` (`PopCtx.sol` 40-43).
This is a hand model, not a compiled one: nothing ties it to the Solidity but reading the two side by side.

What the model leaves out or widens. Each choice can only let the model accept more, so `adapter_pins` still
holds for the real contract:
- `bytes32` and `uint256` are `Nat` with no upper bound.
- Solidity reverts when `deadline + CLOCK_SKEW` or `validAt + maxAge` overflows (line 96). `Nat` never overflows.
- A read past the end of an array reverts. `W` gives 0, but the lengths are checked first, so it never happens.

What stays abstract: the P-256 signature check in `_ccOk` (with its 64-byte length check and the signature bytes;
the key `(qx, qy)` is an argument), and the three proof verifier calls on lines 100-102. Lines 100-102 run right
after the window, so they are the last checks here too. Only the `attempt <= 255` part of `_ccOk` is modeled for real.
-/

namespace Evpfv.Adapter

/-- `N_PHONE`, line 41. -/
def nPhone : Nat := 12
/-- `N_PAIR`, line 42. -/
def nPair : Nat := 11
/-- `CLOCK_SKEW`, line 43. -/
def clockSkew : Nat := 300

/-- `PopCtx.split`: high 128 bits, low 128 bits. -/
def split (x : Nat) : Nat × Nat := (x / 2 ^ 128, x % 2 ^ 128)

/-- The limbs put back together give the word. -/
theorem split_join (x : Nat) : (split x).1 * 2 ^ 128 + (split x).2 = x :=
  Nat.div_add_mod' x (2 ^ 128)

/-- Word `i` of a public input array. -/
def W (v : List Nat) (i : Nat) : Nat := v.getD i 0

/-- The role byte passed to `_ccOk` on lines 92-93. -/
inductive Role
  | A
  | B

/-- What the model does not look inside. `Nat` stands for opaque proof bytes. -/
structure Env where
  /-- `phoneVerifier.verify(proof, pub)`, lines 100-101. -/
  phoneVerify : Nat → List Nat → Prop
  /-- `pairVerifier.verify(proof, pub)`, line 102. -/
  pairVerify : Nat → List Nat → Prop
  /-- The signature part of `_ccOk`, line 120. Arguments: `qx`, `qy`, nonce, attempt, role, code_commit. The POPCC1
  message over the last four carries a good signature from key `(qx, qy)`. P-256 itself stays abstract. -/
  ccSig : Nat → Nat → Nat → Nat → Role → Nat → Prop

/-- The arguments of `verifyPresence`, the arrays and proofs from the bundle, and the immutable `maxAge`. -/
structure Input where
  popNonce : Nat
  deviceA : Nat
  deviceB : Nat
  qx : Nat
  qy : Nat
  notBefore : Nat
  deadline : Nat
  maxAge : Nat
  a : List Nat
  bb : List Nat
  p : List Nat
  proofA : Nat
  proofB : Nat
  proofPair : Nat

/-- `_ccOk`, lines 107-121: the `v[2] <= 255` check on line 112, then the abstract signature. -/
def ccOk (env : Env) (qx qy nonce : Nat) (v : List Nat) (role : Role) : Prop :=
  W v 2 ≤ 255 ∧ env.ccSig qx qy nonce (W v 2) role (W v 4)

/-- `_issuerOk`, lines 123-126. `q >> 128` and `uint128(q)` are the two parts of `split q`. -/
def issuerOk (v : List Nat) (qx qy : Nat) : Prop :=
  W v 5 = (split qx).1 ∧ W v 6 = (split qx).2 ∧ W v 7 = (split qy).1 ∧ W v 8 = (split qy).2

/-- Every check of `verifyPresence`, in source order. Each conjunct is the negation of one `revert` condition. -/
def AdapterAccepts (env : Env) (i : Input) : Prop :=
  -- line 75
  (i.a.length = nPhone ∧ i.bb.length = nPhone ∧ i.p.length = nPair) ∧
  -- lines 77-80
  (W i.a 0 = (split i.popNonce).1 ∧ W i.a 1 = (split i.popNonce).2 ∧
    W i.bb 0 = (split i.popNonce).1 ∧ W i.bb 1 = (split i.popNonce).2 ∧
    W i.p 0 = (split i.popNonce).1 ∧ W i.p 1 = (split i.popNonce).2) ∧
  -- line 81
  (W i.a 2 = W i.p 2 ∧ W i.bb 2 = W i.p 2) ∧
  -- line 82
  (W i.a 3 = 0 ∧ W i.bb 3 = 1) ∧
  -- line 83
  (issuerOk i.a i.qx i.qy ∧ issuerOk i.bb i.qx i.qy) ∧
  -- line 84
  (W i.a 9 = W i.p 5 ∧ W i.bb 9 = W i.p 6) ∧
  -- line 85
  (W i.a 11 = W i.p 3 ∧ W i.bb 11 = W i.p 4) ∧
  -- lines 87-88
  (W i.p 7 = (split i.deviceA).1 ∧ W i.p 8 = (split i.deviceA).2) ∧
  -- lines 89-90
  (W i.p 9 = (split i.deviceB).1 ∧ W i.p 10 = (split i.deviceB).2) ∧
  -- line 92
  ccOk env i.qx i.qy i.popNonce i.a Role.A ∧
  -- line 93
  ccOk env i.qx i.qy i.popNonce i.bb Role.B ∧
  -- lines 95-96
  (W i.bb 10 = W i.a 10 ∧ i.notBefore ≤ W i.a 10 ∧ W i.a 10 ≤ i.deadline + clockSkew ∧
    i.deadline ≤ W i.a 10 + i.maxAge) ∧
  -- line 100
  env.phoneVerify i.proofA i.a ∧
  -- line 101
  env.phoneVerify i.proofB i.bb ∧
  -- line 102
  env.pairVerify i.proofPair i.p

/-- What an accepted call pins, named for the next layer. The session attempt is `W i.p 2`. -/
structure Pins (env : Env) (i : Input) : Prop where
  len_a : i.a.length = 12
  len_bb : i.bb.length = 12
  len_p : i.p.length = 11
  /-- All three proofs carry the nonce's two limbs. -/
  nonce_a : W i.a 0 = i.popNonce / 2 ^ 128 ∧ W i.a 1 = i.popNonce % 2 ^ 128
  nonce_bb : W i.bb 0 = i.popNonce / 2 ^ 128 ∧ W i.bb 1 = i.popNonce % 2 ^ 128
  nonce_p : W i.p 0 = i.popNonce / 2 ^ 128 ∧ W i.p 1 = i.popNonce % 2 ^ 128
  /-- One attempt across all three, and it fits a byte. -/
  attempt_a : W i.a 2 = W i.p 2
  attempt_bb : W i.bb 2 = W i.p 2
  attempt_le : W i.p 2 ≤ 255
  role_a : W i.a 3 = 0
  role_bb : W i.bb 3 = 1
  /-- Both phones name the pinned issuer. Words 5..8 are X hi, X lo, Y hi, Y lo. -/
  issuer_a : W i.a 5 = i.qx / 2 ^ 128 ∧ W i.a 6 = i.qx % 2 ^ 128 ∧
    W i.a 7 = i.qy / 2 ^ 128 ∧ W i.a 8 = i.qy % 2 ^ 128
  issuer_bb : W i.bb 5 = i.qx / 2 ^ 128 ∧ W i.bb 6 = i.qx % 2 ^ 128 ∧
    W i.bb 7 = i.qy / 2 ^ 128 ∧ W i.bb 8 = i.qy % 2 ^ 128
  /-- Rates: the phones' `sr` are the pair's `sr_a`, `sr_b`. -/
  sr_a : W i.a 9 = W i.p 5
  sr_b : W i.bb 9 = W i.p 6
  /-- The phones' `halfCommit` are the pair's `commit_a`, `commit_b`. -/
  commit_a : W i.a 11 = W i.p 3
  commit_b : W i.bb 11 = W i.p 4
  /-- The pair's `xa`, `xb` limbs put back together are the two device keys. -/
  xa_limbs : W i.p 7 = i.deviceA / 2 ^ 128 ∧ W i.p 8 = i.deviceA % 2 ^ 128
  xb_limbs : W i.p 9 = i.deviceB / 2 ^ 128 ∧ W i.p 10 = i.deviceB % 2 ^ 128
  xa_join : W i.p 7 * 2 ^ 128 + W i.p 8 = i.deviceA
  xb_join : W i.p 9 * 2 ^ 128 + W i.p 10 = i.deviceB
  /-- Key `(qx, qy)` signed each phone's `code_commit` (word 4), for this nonce, attempt and role. -/
  cc_a : env.ccSig i.qx i.qy i.popNonce (W i.p 2) Role.A (W i.a 4)
  cc_bb : env.ccSig i.qx i.qy i.popNonce (W i.p 2) Role.B (W i.bb 4)
  /-- One `valid_at` (word 10), inside the window. -/
  valid_eq : W i.bb 10 = W i.a 10
  valid_lo : i.notBefore ≤ W i.a 10
  valid_hi : W i.a 10 ≤ i.deadline + 300
  deadline_le : i.deadline ≤ W i.a 10 + i.maxAge
  proof_a : env.phoneVerify i.proofA i.a
  proof_bb : env.phoneVerify i.proofB i.bb
  proof_p : env.pairVerify i.proofPair i.p

/-- An accepted call pins everything `Pins` lists. -/
theorem adapter_pins (env : Env) (i : Input) (h : AdapterAccepts env i) : Pins env i := by
  obtain ⟨⟨l1, l2, l3⟩, ⟨n1, n2, n3, n4, n5, n6⟩, ⟨t1, t2⟩, ⟨r1, r2⟩,
    ⟨⟨ia1, ia2, ia3, ia4⟩, ⟨ib1, ib2, ib3, ib4⟩⟩, ⟨s1, s2⟩, ⟨c1, c2⟩, ⟨xa1, xa2⟩, ⟨xb1, xb2⟩,
    ⟨cl, ca⟩, ⟨_, cb⟩, ⟨v1, v2, v3, v4⟩, pa, pb, pp⟩ := h
  have ja := split_join i.deviceA
  have jb := split_join i.deviceB
  rw [← xa1, ← xa2] at ja
  rw [← xb1, ← xb2] at jb
  rw [t1] at cl ca
  rw [t2] at cb
  exact ⟨l1, l2, l3, ⟨n1, n2⟩, ⟨n3, n4⟩, ⟨n5, n6⟩, t1, t2, cl, r1, r2, ⟨ia1, ia2, ia3, ia4⟩,
    ⟨ib1, ib2, ib3, ib4⟩, s1, s2, c1, c2, ⟨xa1, xa2⟩, ⟨xb1, xb2⟩, ja, jb, ca, cb, v1, v2, v3, v4,
    pa, pb, pp⟩

/-- Accepts every proof and signature. Only for the example below. -/
def openEnv : Env where
  phoneVerify _ _ := True
  pairVerify _ _ := True
  ccSig _ _ _ _ _ _ := True

/-- Nonce limbs 5, 7. Attempt 0. Issuer limbs 8, 9, 10, 11. Device limbs 1, 2 and 3, 4. Rate 48000. -/
def exampleInput : Input where
  popNonce := 5 * 2 ^ 128 + 7
  deviceA := 1 * 2 ^ 128 + 2
  deviceB := 3 * 2 ^ 128 + 4
  qx := 8 * 2 ^ 128 + 9
  qy := 10 * 2 ^ 128 + 11
  notBefore := 900
  deadline := 1100
  maxAge := 1200
  a := [5, 7, 0, 0, 300, 8, 9, 10, 11, 48000, 1000, 100]
  bb := [5, 7, 0, 1, 301, 8, 9, 10, 11, 48000, 1000, 200]
  p := [5, 7, 0, 100, 200, 48000, 48000, 1, 2, 3, 4]
  proofA := 0
  proofB := 0
  proofPair := 0

/-- The checks can all pass at once, so `AdapterAccepts` is not empty. -/
theorem adapter_accepts_example : AdapterAccepts openEnv exampleInput := by
  simp [AdapterAccepts, openEnv, exampleInput, ccOk, issuerOk, split, W, nPhone, nPair, clockSkew]

end Evpfv.Adapter

#print axioms Evpfv.Adapter.split_join
#print axioms Evpfv.Adapter.adapter_pins
#print axioms Evpfv.Adapter.adapter_accepts_example
