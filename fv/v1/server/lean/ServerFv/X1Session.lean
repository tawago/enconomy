import ServerFv.X1Keys
import ServerFv.X1SessionRun

/-!
# X1 as a session result (Known gap 4)

`X1` and `X1_keys` stop at `verify_record`: every check passes and the verdict function says NEAR.
They do not run `sessions.py`. `X1_session` does: for any setting `e`, any two enrolled devices with
different keys, any halves in the signed 32-bit range, any rates in 36000..96000, versions 1 or 2 on
each side, any 32-byte recording values (v2: under the field size), and self deltas that pass, as long
as the exact flight is strictly between -20 and 60, the model of `sessions.py` at 9db1490 reaches a
finished session whose stored result is NEAR at that flight, with both devices' rows, reached as the
run from the given `create` at `T`, and whose stored commits and transcripts carry the picked
recording values, halves and self deltas (`X1Reached`). The stored flight is exact, Python's is
`round(float(f), 2)`.

It builds the two signers with `X1_ready`, picks base64 strings for their bytes with `hb64`, fills an
`X1Plan`, and runs it with `X1Plan.reaches_near`.

Still hypotheses, not facts about `codec.py` or base64: `Powers`, `hsha`, `hb64`. Nothing here reads
sound (CN1): the NEAR is about signed numbers, not distance.
-/

set_option linter.style.whitespace false
set_option linter.style.longLine false
set_option linter.style.header false
set_option linter.unusedVariables false

namespace ServerFv
namespace Machine

variable {B D : Type} [DecidableEq B] [DecidableEq D]

/-- **What `X1_session` reaches.** The document `s` is the one the model gets by running, from the
`create` at clock `T` (host `dA`, these `sid`, `nonce`, `seed`, `token`), the nine requests below,
each with calibration `cal`: guest `dB` joins with `token` at `T+1`, confirms at `T+2` (A) and `T+3`
(B), arms at `T+10` (A, rate `srA`, version `verA`) and `T+11` (B), commits at `T+4310` (A) and
`T+4311` (B), sends transcripts at `T+4410` (A) and `T+4411` (B). The eight base64 strings are
named. Then:

* `s` is `Reachable` at `T + 4411`, keeps `sid`, `nonce`, `seed`, `token`, host `dA`, guest `dB`,
  attempt 0, and is `done` with a stored record `rc`;
* `rc` has `sid`, `nonce`, NEAR, no reason, attempt 0, `flight_cm` = the exact flight, the two device
  rows, and as its commits and transcripts the very base64 strings sent;
* for each role, the commit string decodes to bytes whose commit is that role, attempt 0, `nonce`,
  its recording value (`recA` or `recB`) and its version; the transcript string decodes to a
  transcript with that recording value, half, self delta and the enrolled key;
* the document's own `per_role` rows store the commit (that string, that recording value) and the
  transcript (that string, that half, that self delta).

The flight is the exact rational `flight_exact`. Python stores `round(float(f), 2)`
(`verdict.py:167` at 9db1490), so the two stored values can differ past two decimals; this is not
modelled. -/
def X1Reached {B D : Type} [DecidableEq B] [DecidableEq D] (e : Env B D) (dA dB : D)
    (sid nonce recA recB : B) (seed token : String) (T : ℕ) (cal : D → ℤ) (verA verB : ℕ)
    (hA hB dlA dlB : ℤ) (srA srB : ℕ) : Prop :=
  ∃ (cbA sbA tbA tsA cbB sbB tbB tsB : B) (s : Doc B D) (rc : Record B D),
    s = runL e (create ⟨T, cal⟩ dA sid nonce seed token).1
      [(⟨T + 1, cal⟩, .api false (some dB) false (.join token)),
       (⟨T + 2, cal⟩, opReq dA .confirm), (⟨T + 3, cal⟩, opReq dB .confirm),
       (⟨T + 10, cal⟩, opReq dA (.arm (.int 0) (.int srA) (some 0) (.int verA))),
       (⟨T + 11, cal⟩, opReq dB (.arm (.int 0) (.int srB) (some 0) (.int verB))),
       (⟨T + 4310, cal⟩, opReq dA (.commit cbA sbA)), (⟨T + 4311, cal⟩, opReq dB (.commit cbB sbB)),
       (⟨T + 4410, cal⟩, opReq dA (.transcript tbA tsA)),
       (⟨T + 4411, cal⟩, opReq dB (.transcript tbB tsB))] ∧
    Reachable e (T + 4411) s ∧
    s.session_id = sid ∧ s.nonce_hex = nonce ∧ s.seed_hex = seed ∧ s.join_token = token ∧
    s.host_device_id = dA ∧ s.guest_device_id = some dB ∧ s.attempt = 0 ∧
    s.state = .done ∧ s.result = some rc ∧
    rc.session_id = sid ∧ rc.session_nonce = nonce ∧
    rc.verdict = .NEAR ∧ rc.reason = none ∧ rc.attempt = 0 ∧
    rc.flight_cm = some (flight_exact hA srA hB srB) ∧
    rc.devices .A = some ⟨dA, e.pk dA, some srA, some hA, verA, cal dA⟩ ∧
    rc.devices .B = some ⟨dB, e.pk dB, some srB, some hB, verB, cal dB⟩ ∧
    (rc.commits .A).map (·.commit_b64) = some cbA ∧ (rc.commits .B).map (·.commit_b64) = some cbB ∧
    (rc.transcripts .A).map (·.transcript_b64) = some tbA ∧
    (rc.transcripts .B).map (·.transcript_b64) = some tbB ∧
    (∃ raw, e.b64d cbA = some raw ∧
      e.p.decode_commit raw = some ⟨.A, 0, nonce, recA, verA⟩) ∧
    (∃ raw, e.b64d cbB = some raw ∧
      e.p.decode_commit raw = some ⟨.B, 0, nonce, recB, verB⟩) ∧
    (∃ raw t, e.b64d tbA = some raw ∧ e.p.decode_transcript raw = some t ∧
      t.rec_ = recA ∧ t.half = hA ∧ t.self_os_delta = dlA ∧ t.pk_self = e.pk dA) ∧
    (∃ raw t, e.b64d tbB = some raw ∧ e.p.decode_transcript raw = some t ∧
      t.rec_ = recB ∧ t.half = hB ∧ t.self_os_delta = dlB ∧ t.pk_self = e.pk dB) ∧
    (∃ c, (s.per_role .A).commit = some c ∧ c.commit_b64 = cbA ∧ c.rec_ = recA) ∧
    (∃ c, (s.per_role .B).commit = some c ∧ c.commit_b64 = cbB ∧ c.rec_ = recB) ∧
    (∃ t, (s.per_role .A).tx = some t ∧ t.transcript_b64 = tbA ∧ t.half = hA ∧
      t.self_os_delta = dlA) ∧
    (∃ t, (s.per_role .B).tx = some t ∧ t.transcript_b64 = tbB ∧ t.half = hB ∧
      t.self_os_delta = dlB)

/-- **X1 as a session result (rule CN1).** Pick a setting `e`, two devices `dA` (host) and `dB`
(guest) with different enrolled keys, a fresh `sid` and `nonce`, a seed and a lower-case token, a
clock `T` and the `cal_us` each device row holds. Pick, for each side, a half in the signed 32-bit
range, a rate in 36000..96000, a version 1 or 2, a 32-byte recording value (v2: passes the root
check, and the server's `code_commit` for these codes at that rate is 32 bytes), and a self delta in
range that passes with the stored calibration (0 in v2). If the exact flight lies strictly between
-20 and 60, then `X1Reached` holds: the nine requests listed there, run from the `create` at `T`
with these `sid`, `nonce`, `seed`, `token`, end on a `done` document at `T + 4411` that keeps those
values, whose stored record says NEAR, no reason, attempt 0, `flight_cm` = that exact flight, with
device rows `⟨id, enrolled key, picked rate, picked half, picked version, cal⟩` for A and B, and
whose stored commits and transcripts carry `recA`/`recB`, the halves and `dlA`/`dlB` for both roles.

**What it pins.** That this outcome is `Reachable` in the model, as the run from this `create`, for
every allowed pick, both versions, mixed versions included. The rows carry the enrolled keys.

**What it does not pin.** Any other schedule (it is one fixed timing), the raw bytes or signatures
(`Powers` supplies them; only their decoded fields are named), that base64 or the codec really behave
like `hb64` and `Powers`, or anything about sound. The verdict is a function of signed numbers, not
of distance (CN1).

**Gap to Python.** `flight_cm` here is the exact rational `flight_exact ..`. Python stores
`round(float(f), 2)` (`verdict.py:167` at 9db1490). Same verdict, but the stored number can differ
past two decimals and by float rounding. -/
theorem X1_session (e : Env B D) (dA dB : D) (sid nonce recA recB : B) (seed token : String)
    (T : ℕ) (cal : D → ℤ) (verA verB : ℕ) (hA hB dlA dlB : ℤ) (srA srB : ℕ)
    (hpow : Powers e.p (e.pk dA) (e.pk dB))
    (hb64 : ∀ x, ∃ y, e.b64d y = some x)
    (hsha : ∀ m, e.p.width (e.p.sha256 m) = 32)
    (hdev : dA ≠ dB) (hkey : e.pk dA ≠ e.pk dB) (htok : token.toLower = token)
    (hwA : e.p.width (e.pk dA) = 65) (hwB : e.p.width (e.pk dB) = 65) (hwn : e.p.width nonce = 32)
    (hwrA : e.p.width recA = 32) (hwrB : e.p.width recB = 32)
    (hvA : verA = 1 ∨ verA = 2) (hvB : verB = 1 ∨ verB = 2)
    (hrA : verA = 2 → e.p.rec_root_ok recA = true ∧
      e.p.width (e.code_commit srA ⟨seed, .A, 0⟩ ⟨seed, .B, 0⟩) = 32)
    (hrB : verB = 2 → e.p.rec_root_ok recB = true ∧
      e.p.width (e.code_commit srB ⟨seed, .B, 0⟩ ⟨seed, .A, 0⟩) = 32)
    (hA1 : -2^31 ≤ hA) (hA2 : hA < 2^31) (hB1 : -2^31 ≤ hB) (hB2 : hB < 2^31)
    (hdA1 : -2^31 ≤ dlA) (hdA2 : dlA < 2^31) (hdB1 : -2^31 ≤ dlB) (hdB2 : dlB < 2^31)
    (ha1 : 36000 ≤ srA) (ha2 : srA ≤ 96000) (hb1 : 36000 ≤ srB) (hb2 : srB ≤ 96000)
    (hdA : self_os_ok dlA srA (if verA = 2 then 0 else cal dA) = true)
    (hdB : self_os_ok dlB srB (if verB = 2 then 0 else cal dB) = true)
    (hf1 : -20 < flight_exact hA srA hB srB) (hf2 : flight_exact hA srA hB srB < 60) :
    X1Reached e dA dB sid nonce recA recB seed token T cal verA verB hA hB dlA dlB srA srB := by
  -- The two signers, with `code_commit` set to the server's value in v2 and `none` in v1.
  let ccA : Option B := if verA = 2 then some (e.code_commit srA ⟨seed, .A, 0⟩ ⟨seed, .B, 0⟩) else none
  let ccB : Option B := if verB = 2 then some (e.code_commit srB ⟨seed, .B, 0⟩ ⟨seed, .A, 0⟩) else none
  have hrA' : verA = 2 → e.p.rec_root_ok recA = true ∧ ∃ x, ccA = some x ∧ e.p.width x = 32 := by
    intro h
    exact ⟨(hrA h).1, _, by simp [ccA, h], (hrA h).2⟩
  have hrB' : verB = 2 → e.p.rec_root_ok recB = true ∧ ∃ x, ccB = some x ∧ e.p.width x = 32 := by
    intro h
    exact ⟨(hrB h).1, _, by simp [ccB, h], (hrB h).2⟩
  obtain ⟨sA, sB, kA, pA, kB, pB, rA, rB, eA, eB, oA, oB, cA, cB, vA, vB, mA, mB, hRA, hRB⟩ :=
    X1_ready e.p (e.pk dA) (e.pk dB) nonce recA recB ccA ccB verA verB 0 dlA dlB hA hB srA srB
      hpow hsha hwA hwB hwn hwrA hwrB hvA hvB (by norm_num) hrA' hrB' hA1 hA2 hB1 hB2 ha2 hb2
      hdA1 hdA2 hdB1 hdB2
  -- Base64 strings for the eight byte strings the phones send.
  obtain ⟨cbA, hcbA⟩ := hb64 sA.commit_raw
  obtain ⟨sbA, hsbA⟩ := hb64 sA.commit_sig
  obtain ⟨tbA, htbA⟩ := hb64 sA.raw
  obtain ⟨tsA, htsA⟩ := hb64 sA.sig
  obtain ⟨cbB, hcbB⟩ := hb64 sB.commit_raw
  obtain ⟨sbB, hsbB⟩ := hb64 sB.commit_sig
  obtain ⟨tbB, htbB⟩ := hb64 sB.raw
  obtain ⟨tsB, htsB⟩ := hb64 sB.sig
  subst rA rB eA eB oA oB vA vB cA cB
  have hccA : sA.version = 2 →
      sA.code_commit = some (e.code_commit sA.sample_rate ⟨seed, .A, 0⟩ ⟨seed, .B, 0⟩) := by
    intro h; rw [mA]; simp [ccA, h]
  have hccB : sB.version = 2 →
      sB.code_commit = some (e.code_commit sB.sample_rate ⟨seed, .B, 0⟩ ⟨seed, .A, 0⟩) := by
    intro h; rw [mB]; simp [ccB, h]
  let P : X1Plan e nonce sid :=
    { dA, dB, seed, token, T, cal, sA, sB, cbA, sbA, tbA, tsA, cbB, sbB, tbB, tsB,
      hdev, hkey, htok, hcbA, hsbA, htbA, htsA, hcbB, hsbB, htbB, htsB,
      hpk := ⟨kA, pA, kB, pB⟩, hRA, hRB,
      hrA1 := ha1, hrA2 := ha2, hrB1 := hb1, hrB2 := hb2, hvA, hvB, hccA, hccB,
      hdA, hdB, hf1, hf2 }
  have hreach := P.reaches_near.1
  refine ⟨cbA, sbA, tbA, tsA, cbB, sbB, tbB, tsB, P.d9, _, P.run_d9.symm, hreach,
    rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl,
    rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl,
    rfl, rfl, rfl, rfl,
    ⟨_, hcbA, hRA.1⟩, ⟨_, hcbB, hRB.1⟩,
    ⟨_, _, htbA, hRA.2.2.1, rfl, rfl, rfl, kA⟩, ⟨_, _, htbB, hRB.2.2.1, rfl, rfl, rfl, kB⟩,
    ⟨_, rfl, rfl, rfl⟩, ⟨_, rfl, rfl, rfl⟩,
    ⟨_, rfl, rfl, rfl, rfl⟩, ⟨_, rfl, rfl, rfl, rfl⟩⟩

/-- **The plan's weaker shape.** `X1Reached` gives what the chunk plan asked for: some reachable
`done` document with a NEAR result at the exact flight, whose device rows carry the enrolled keys.
Only a projection of `X1_session`'s conclusion; it adds nothing. -/
theorem X1_session_keys {e : Env B D} {dA dB : D} {sid nonce recA recB : B} {seed token : String}
    {T : ℕ} {cal : D → ℤ} {verA verB : ℕ} {hA hB dlA dlB : ℤ} {srA srB : ℕ}
    (h : X1Reached e dA dB sid nonce recA recB seed token T cal verA verB hA hB dlA dlB srA srB) :
    ∃ c s rc, Reachable e c s ∧ s.state = .done ∧ s.result = some rc ∧
      rc.verdict = .NEAR ∧ rc.flight_cm = some (flight_exact hA srA hB srB) ∧
      (rc.devices .A).map (·.pubkey) = some (e.pk dA) ∧
      (rc.devices .B).map (·.pubkey) = some (e.pk dB) := by
  obtain ⟨-, -, -, -, -, -, -, -, s, rc, -, h1, -, -, -, -, -, -, -, h2, h3, -, -, h4, -, -, h7, h8,
    h9, -⟩ := h
  exact ⟨_, s, rc, h1, h2, h3, h4, h7, by rw [h8]; rfl, by rw [h9]; rfl⟩

end Machine
end ServerFv

/-! ## Axioms -/

#print axioms ServerFv.Machine.X1_session
#print axioms ServerFv.Machine.X1_session_keys
