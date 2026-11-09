import ServerFv.Verdict

/-!
# X1 with the keys pinned (README gap 1)

`X1`'s conclusion names the halves, rates, recording values and versions, but not the keys, the self
deltas or `code_commit`. `X1_keys` is the same statement with those pinned too: for each side,
`pk_self`, `pk_partner`, `self_os_delta` and `code_commit` equal the values given in the binders.
`X1_on_layout_keys` runs it on the fixed-width decoder.

`X1` itself is not edited here. `X1_of_keys` shows `X1_keys` gives `X1`'s conclusion.

Still hypotheses, not facts about `codec.py`: `Powers` and `hsha`. Nothing here reads sound (CN1).
-/

set_option linter.style.whitespace false
set_option linter.style.longLine false
set_option linter.style.header false
set_option linter.unusedVariables false
set_option linter.unusedSimpArgs false

namespace ServerFv

variable {B : Type} [DecidableEq B]

omit [DecidableEq B] in
/-- **A side's transcript is in the wire ranges.** If the side's own fields are in range (version,
widths of keys and recording value, rate, half, self delta, and for v2 the root check and a 32-byte
`code_commit`), and the hash gives 32 bytes, then the transcript `Side.transcript` builds meets
`Transcript.wire_ok`. This is the local `wire` step of `X1`, lifted out. It says nothing about the
signatures or the decoder. -/
theorem Side.transcript_wire_ok (p : Prims B) (s : Side B) (r : Role) (attempt : ℕ) (nonce : B)
    (hk : attempt < 2^8) (hwn : p.width nonce = 32) (hsha : ∀ m, p.width (p.sha256 m) = 32)
    (hv : s.version = 1 ∨ s.version = 2)
    (hroot : s.version = 2 → p.rec_root_ok s.rec_ = true ∧ ∃ x, s.code_commit = some x ∧ p.width x = 32)
    (wps : p.width s.pk_self = 65) (wpp : p.width s.pk_partner = 65) (wr : p.width s.rec_ = 32)
    (hsr : s.sample_rate ≤ 96000) (h1 : -2^31 ≤ s.half) (h2 : s.half < 2^31)
    (h3 : -2^31 ≤ s.self_os_delta) (h4 : s.self_os_delta < 2^31) :
    (s.transcript p.sha256 r attempt nonce).wire_ok p := by
  have hd : popt2_delta s.sample_rate < 2^16 := by
    unfold popt2_delta K.DELTA_MS
    omega
  refine ⟨hv, hk, hwn, wps, wpp, wr, hsha _, by simp only [Side.transcript]; omega, h1, h2, h3, h4,
    by simp [Side.transcript], by simp [Side.transcript], by simp [Side.transcript], ?_, ?_⟩
  · intro hv1
    have : s.version ≠ 2 := by simp only [Side.transcript] at hv1; omega
    simp [Side.transcript, this]
  · intro hv2
    have hv2' : s.version = 2 := hv2
    obtain ⟨r1, r2⟩ := hroot hv2'
    simp only [Side.transcript, hv2', ite_true]
    exact ⟨r1, ⟨0, rfl, by norm_num⟩, ⟨0, rfl, by norm_num⟩, ⟨_, rfl, hd⟩, r2⟩

omit [DecidableEq B] in
/-- **Two ready signers with the picked fields.** Under `X1`'s wire and width hypotheses (no self
check and no flight bound needed), there are two sides that are `Side.Ready` (bytes decode to what
they picked, signatures check) whose keys, partner keys, rates, halves, self deltas, recording values,
versions and `code_commit` are exactly the given ones. A's partner is B's key and the other way round.

It pins every picked field. It does not pin the raw bytes or signatures, which `Powers` supplies.
Nothing here reads sound. -/
theorem X1_ready (p : Prims B) (pkA pkB nonce recA recB : B) (ccA ccB : Option B) (verA verB attempt : ℕ)
    (dA dB hA hB : ℤ) (srA srB : ℕ) (hpow : Powers p pkA pkB)
    (hsha : ∀ m, p.width (p.sha256 m) = 32)
    (hwA : p.width pkA = 65) (hwB : p.width pkB = 65) (hwn : p.width nonce = 32)
    (hwrA : p.width recA = 32) (hwrB : p.width recB = 32)
    (hvA : verA = 1 ∨ verA = 2) (hvB : verB = 1 ∨ verB = 2) (hk : attempt < 2^8)
    (hrA : verA = 2 → p.rec_root_ok recA = true ∧ ∃ x, ccA = some x ∧ p.width x = 32)
    (hrB : verB = 2 → p.rec_root_ok recB = true ∧ ∃ x, ccB = some x ∧ p.width x = 32)
    (hA1 : -2^31 ≤ hA) (hA2 : hA < 2^31) (hB1 : -2^31 ≤ hB) (hB2 : hB < 2^31)
    (ha2 : srA ≤ 96000) (hb2 : srB ≤ 96000)
    (hdA1 : -2^31 ≤ dA) (hdA2 : dA < 2^31) (hdB1 : -2^31 ≤ dB) (hdB2 : dB < 2^31) :
    ∃ sA sB : Side B,
      sA.pk_self = pkA ∧ sA.pk_partner = pkB ∧ sB.pk_self = pkB ∧ sB.pk_partner = pkA ∧
      sA.sample_rate = srA ∧ sB.sample_rate = srB ∧ sA.half = hA ∧ sB.half = hB ∧
      sA.self_os_delta = dA ∧ sB.self_os_delta = dB ∧ sA.rec_ = recA ∧ sB.rec_ = recB ∧
      sA.version = verA ∧ sB.version = verB ∧ sA.code_commit = ccA ∧ sB.code_commit = ccB ∧
      sA.Ready p .A attempt nonce ∧ sB.Ready p .B attempt nonce := by
  have writeC : ∀ (r : Role) (rc : B) (v : ℕ), (v = 1 ∨ v = 2) → p.width rc = 32 →
      (v = 2 → p.rec_root_ok rc = true) →
      ∃ raw, p.decode_commit raw =
        some ({ role := r, attempt, nonce, rec_ := rc, version := v } : Commit B) := by
    intro r rc v h1 hw h2
    exact hpow.write_commit _ ⟨h1, hk, hwn, hw, h2⟩
  obtain ⟨craA, hcraA⟩ := writeC .A recA verA hvA hwrA (fun h => (hrA h).1)
  obtain ⟨craB, hcraB⟩ := writeC .B recB verB hvB hwrB (fun h => (hrB h).1)
  obtain ⟨csA, hcsA⟩ := hpow.sign pkA (Or.inl rfl) craA
  obtain ⟨csB, hcsB⟩ := hpow.sign pkB (Or.inr rfl) craB
  let sA0 : Side B := ⟨pkA, pkB, srA, hA, dA, recA, verA, ccA, craA, csA, craA, csA⟩
  let sB0 : Side B := ⟨pkB, pkA, srB, hB, dB, recB, verB, ccB, craB, csB, craB, csB⟩
  obtain ⟨tA, htA⟩ := hpow.write_transcript _
    (Side.transcript_wire_ok p sA0 .A attempt nonce hk hwn hsha hvA hrA hwA hwB hwrA ha2
      hA1 hA2 hdA1 hdA2)
  obtain ⟨tB, htB⟩ := hpow.write_transcript _
    (Side.transcript_wire_ok p sB0 .B attempt nonce hk hwn hsha hvB hrB hwB hwA hwrB hb2
      hB1 hB2 hdB1 hdB2)
  obtain ⟨sgA, hsgA⟩ := hpow.sign pkA (Or.inl rfl) tA
  obtain ⟨sgB, hsgB⟩ := hpow.sign pkB (Or.inr rfl) tB
  let sA : Side B := ⟨pkA, pkB, srA, hA, dA, recA, verA, ccA, craA, csA, tA, sgA⟩
  let sB : Side B := ⟨pkB, pkA, srB, hB, dB, recB, verB, ccB, craB, csB, tB, sgB⟩
  exact ⟨sA, sB, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl,
    ⟨hcraA, hcsA, htA, hsgA⟩, ⟨hcraB, hcsB, htB, hsgB⟩⟩

/-- **X1 with the keys pinned (rule CN1).** Same binders and hypotheses as `X1`. The conclusion adds,
for both sides, that `pk_self`, `pk_partner`, `self_os_delta` and `code_commit` are the given ones:
A signs as `pkA` with partner `pkB`, B signs as `pkB` with partner `pkA`. So "two signers holding
their enrolled keys" is now what the statement says, not just what the proof builds. Every check
passes and the verdict is NEAR (`X1Outcome`).

It does not pin the raw bytes or signatures. `Powers` and `hsha` are still hypotheses, not facts about
`codec.py`. It does not show a phone told the truth about the air (CN1). -/
theorem X1_keys (p : Prims B) (pkA pkB nonce recA recB : B) (ccA ccB : Option B) (verA verB attempt : ℕ)
    (calA calB dA dB hA hB : ℤ) (srA srB : ℕ) (hpow : Powers p pkA pkB)
    (hsha : ∀ m, p.width (p.sha256 m) = 32) (hne : pkA ≠ pkB)
    (hwA : p.width pkA = 65) (hwB : p.width pkB = 65) (hwn : p.width nonce = 32)
    (hwrA : p.width recA = 32) (hwrB : p.width recB = 32)
    (hvA : verA = 1 ∨ verA = 2) (hvB : verB = 1 ∨ verB = 2) (hk : attempt < 2^8)
    (hrA : verA = 2 → p.rec_root_ok recA = true ∧ ∃ x, ccA = some x ∧ p.width x = 32)
    (hrB : verB = 2 → p.rec_root_ok recB = true ∧ ∃ x, ccB = some x ∧ p.width x = 32)
    (hA1 : -2^31 ≤ hA) (hA2 : hA < 2^31) (hB1 : -2^31 ≤ hB) (hB2 : hB < 2^31)
    (ha1 : 36000 ≤ srA) (ha2 : srA ≤ 96000) (hb1 : 36000 ≤ srB) (hb2 : srB ≤ 96000)
    (hdA1 : -2^31 ≤ dA) (hdA2 : dA < 2^31) (hdB1 : -2^31 ≤ dB) (hdB2 : dB < 2^31)
    (hdA : self_os_ok dA srA (if verA = 2 then 0 else calA) = true)
    (hdB : self_os_ok dB srB (if verB = 2 then 0 else calB) = true)
    (hf1 : -20 < flight_exact hA srA hB srB) (hf2 : flight_exact hA srA hB srB < 60) :
    ∃ sA sB : Side B,
      sA.half = hA ∧ sB.half = hB ∧ sA.sample_rate = srA ∧ sB.sample_rate = srB ∧
      sA.rec_ = recA ∧ sB.rec_ = recB ∧ sA.version = verA ∧ sB.version = verB ∧
      sA.pk_self = pkA ∧ sB.pk_self = pkB ∧ sA.pk_partner = pkB ∧ sB.pk_partner = pkA ∧
      sA.self_os_delta = dA ∧ sB.self_os_delta = dB ∧
      sA.code_commit = ccA ∧ sB.code_commit = ccB ∧
      X1Outcome p sA sB nonce attempt calA calB := by
  obtain ⟨sA, sB, kA, pA, kB, pB, rA, rB, eA, eB, oA, oB, cA, cB, vA, vB, mA, mB, hRA, hRB⟩ :=
    X1_ready p pkA pkB nonce recA recB ccA ccB verA verB attempt dA dB hA hB srA srB hpow hsha
      hwA hwB hwn hwrA hwrB hvA hvB hk hrA hrB hA1 hA2 hB1 hB2 ha2 hb2 hdA1 hdA2 hdB1 hdB2
  subst kA kB rA rB eA eB oA oB cA cB vA vB mA mB
  refine ⟨sA, sB, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, pA, pB, rfl, rfl, rfl, rfl, ?_⟩
  exact X1_core p sA sB nonce attempt calA calB hRA hRB pA pB hne
    ha1 ha2 hb1 hb2 hdA hdB hf1 hf2

/-- **`X1_keys` gives `X1`'s conclusion.** A sanity check that the new statement is at least as
strong: drop the key, delta and `code_commit` equalities and what's left is exactly `X1`'s
conclusion. -/
theorem X1_of_keys (p : Prims B) (pkA pkB nonce recA recB : B) (ccA ccB : Option B) (verA verB attempt : ℕ)
    (calA calB dA dB hA hB : ℤ) (srA srB : ℕ)
    (h : ∃ sA sB : Side B,
      sA.half = hA ∧ sB.half = hB ∧ sA.sample_rate = srA ∧ sB.sample_rate = srB ∧
      sA.rec_ = recA ∧ sB.rec_ = recB ∧ sA.version = verA ∧ sB.version = verB ∧
      sA.pk_self = pkA ∧ sB.pk_self = pkB ∧ sA.pk_partner = pkB ∧ sB.pk_partner = pkA ∧
      sA.self_os_delta = dA ∧ sB.self_os_delta = dB ∧
      sA.code_commit = ccA ∧ sB.code_commit = ccB ∧
      X1Outcome p sA sB nonce attempt calA calB) :
    ∃ sA sB : Side B,
      sA.half = hA ∧ sB.half = hB ∧ sA.sample_rate = srA ∧ sB.sample_rate = srB ∧
      sA.rec_ = recA ∧ sB.rec_ = recB ∧ sA.version = verA ∧ sB.version = verB ∧
      X1Outcome p sA sB nonce attempt calA calB := by
  obtain ⟨sA, sB, h1, h2, h3, h4, h5, h6, h7, h8, -, -, -, -, -, -, -, -, hx⟩ := h
  exact ⟨sA, sB, h1, h2, h3, h4, h5, h6, h7, h8, hx⟩

/-- **`X1_keys` run through its own hypotheses, on the fixed-width decoder.** Every hypothesis is met
at once, for version 1 and for version 2.

**What the statement pins.** Halves 100 and 0, rates 48000, versions `ver`, recording values all-zero
32 bytes on both sides, A's key 65 bytes of 1 and B's 65 bytes of 2 with crossed partners, self deltas
0, `code_commit` all-zero 32 bytes in v2 and `none` in v1, and `X1Outcome` (every check passes, verdict
NEAR) with an all-zero nonce, attempt 0 and calibration 0. So `X1_keys` is not empty.

One concrete instance. It shows the hypotheses can hold, not a session run, and not that a phone told
the truth about the air (CN1). -/
theorem X1_on_layout_keys (ver : ℕ) (hv : ver = 1 ∨ ver = 2) :
    ∃ sA sB : Side Layout.Bytes,
      sA.half = 100 ∧ sB.half = 0 ∧ sA.sample_rate = 48000 ∧ sB.sample_rate = 48000 ∧
      sA.rec_ = Layout.fill 32 0 ∧ sB.rec_ = Layout.fill 32 0 ∧
      sA.version = ver ∧ sB.version = ver ∧
      sA.pk_self = Layout.fill 65 1 ∧ sB.pk_self = Layout.fill 65 2 ∧
      sA.pk_partner = Layout.fill 65 2 ∧ sB.pk_partner = Layout.fill 65 1 ∧
      sA.self_os_delta = 0 ∧ sB.self_os_delta = 0 ∧
      sA.code_commit = (if ver = 2 then some (Layout.fill 32 0) else none) ∧
      sB.code_commit = (if ver = 2 then some (Layout.fill 32 0) else none) ∧
      X1Outcome Layout.prims sA sB (Layout.fill 32 0) 0 0 0 := by
  have hflight := toy_flight
  have hself : self_os_ok 0 48000 (if ver = 2 then 0 else 0) = true := by
    norm_num [self_os_ok]
  have hroot : Layout.prims.rec_root_ok (Layout.fill 32 0) = true := by
    simp only [Layout.prims, Layout.rootOk, Layout.fill, Layout.unbe_fill_zero]
    simp [Layout.R]
  have hcc : ver = 2 → Layout.prims.rec_root_ok (Layout.fill 32 0) = true ∧
      ∃ x, (if ver = 2 then some (Layout.fill 32 0) else none) = some x ∧ Layout.prims.width x = 32 := by
    intro h
    exact ⟨hroot, Layout.fill 32 0, by simp [h], by simp [Layout.prims, Layout.fill]⟩
  obtain ⟨sA, sB, h1, h2, h3, h4, h5, h6, h7, h8, k1, k2, k3, k4, d1, d2, c1, c2, hx⟩ :=
    X1_keys Layout.prims (Layout.fill 65 1) (Layout.fill 65 2) (Layout.fill 32 0)
      (Layout.fill 32 0) (Layout.fill 32 0)
      (if ver = 2 then some (Layout.fill 32 0) else none)
      (if ver = 2 then some (Layout.fill 32 0) else none) ver ver 0 0 0 0 0 100 0 48000 48000
      (Powers_satisfiable _ _) Layout.prims_sha_width
      (by intro h; have := congrArg List.head? h; simp [Layout.fill] at this)
      (by simp [Layout.prims, Layout.fill]) (by simp [Layout.prims, Layout.fill])
      (by simp [Layout.prims, Layout.fill]) (by simp [Layout.prims, Layout.fill])
      (by simp [Layout.prims, Layout.fill]) hv hv (by norm_num) hcc hcc
      (by norm_num) (by norm_num) (by norm_num) (by norm_num)
      (by norm_num) (by norm_num) (by norm_num) (by norm_num)
      (by norm_num) (by norm_num) (by norm_num) (by norm_num) hself hself
      (by rw [hflight]; norm_num) (by rw [hflight]; norm_num)
  exact ⟨sA, sB, h1, h2, h3, h4, h5, h6, h7, h8, k1, k2, k3, k4, d1, d2, c1, c2, hx⟩

end ServerFv

/-! ## Axioms -/

#print axioms ServerFv.Side.transcript_wire_ok
#print axioms ServerFv.X1_ready
#print axioms ServerFv.X1_keys
#print axioms ServerFv.X1_of_keys
#print axioms ServerFv.X1_on_layout_keys
