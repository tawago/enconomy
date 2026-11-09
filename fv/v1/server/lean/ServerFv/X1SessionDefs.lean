import ServerFv.Machine

/-!
# Definitions for X1 as a session result (Known gap 4)

`Witness.run_reachable` in `Machine.lean` only works for `Env ℕ ℕ` and the fixed clock `Witness.W`.
This file gives the same runner for any `Env B D` and any `World D`, plus `X1Plan`: everything two
signers pick for one session run, with the hypotheses the walk needs, and the ten documents
`d0 .. d9` that the walk is expected to pass through.

**What this file proves.** Only the runner facts (`runL_reachable` and small unfolding lemmas), that
`d0` is `Reachable`, and that the nine requests of the plan are in time order and end at `T + 4411`.

**What it does not prove.** It does not prove that `step` takes `d_k` to `d_{k+1}`. Those are
separate lemmas in other files. The documents here are written by hand from `sessions.py` at 9db1490
and could be wrong until those lemmas check them. The schedule is one fixed timing (join at `T+1`,
confirms at `T+2`, `T+3`, arms at `T+10`, `T+11`, commits at `T+4310`, `T+4311`, transcripts at
`T+4410`, `T+4411`). Nothing here is about sound (CN1).
-/

namespace ServerFv
namespace Machine

section Runner

variable {B D : Type}

/-- Is each request's clock at or after the one before, starting from clock `c`? -/
def inOrderL : ℕ → List (World D × Req B D) → Bool
  | _, [] => true
  | c, p :: l => Nat.ble c p.1.now && inOrderL p.1.now l

/-- The clock of the last request in a list, or `c` for an empty list. -/
def lastTimeL : ℕ → List (World D × Req B D) → ℕ
  | c, [] => c
  | _, p :: l => lastTimeL p.1.now l

variable [DecidableEq B] [DecidableEq D]

/-- Run a list of requests, each with its own world (clock and calibration), and keep the stored
document. The responses are dropped. -/
def runL (e : Env B D) (s : Doc B D) (l : List (World D × Req B D)) : Doc B D :=
  l.foldl (fun x p => (step e p.1 p.2 x).1) s

@[simp] theorem runL_nil (e : Env B D) (s : Doc B D) : runL e s [] = s := rfl

@[simp] theorem runL_cons (e : Env B D) (s : Doc B D) (p : World D × Req B D) (l : List (World D × Req B D)) :
    runL e s (p :: l) = runL e (step e p.1 p.2 s).1 l := rfl

theorem runL_append (e : Env B D) (s : Doc B D) (l l' : List (World D × Req B D)) :
    runL e s (l ++ l') = runL e (runL e s l) l' := by
  simp [runL, List.foldl_append]

/-- **A run with clocks in order is a `Reachable` one.** The same as `Witness.run_reachable`, for any
`Env B D` and any worlds. It pins only that the result document is reachable at the last clock; it
says nothing about what the document holds. -/
theorem runL_reachable {e : Env B D} {c : ℕ} {s : Doc B D} (h : Reachable e c s)
    (l : List (World D × Req B D)) (ho : inOrderL c l = true) :
    Reachable e (lastTimeL c l) (runL e s l) := by
  induction l generalizing c s with
  | nil => exact h
  | cons p l ih =>
    simp only [inOrderL, Bool.and_eq_true, Nat.ble_eq] at ho
    exact ih (Reachable.step p.1 p.2 h ho.1) ho.2

end Runner

section Plan

variable {B D : Type} [DecidableEq B] [DecidableEq D]

/-- A request with good auth and a good shape, from device `dev`, after the member check. -/
def opReq (dev : D) (o : Op B) : Req B D := .api false (some dev) false (.op o)

/-- **What two signers pick for one session, and what the walk needs of it.** `e` is any setting,
`nonce` and `sid` are the fresh values of `create`. Host is `dA` (role A), guest is `dB` (role B).
`T` is the clock at `create`. `cal` is the `cal_us` the server reads for each device. `sA`, `sB` are
the two signers' picks (`Side` from `Verdict.lean`): any halves, rates, recording values, versions,
self deltas, `code_commit`. The eight `B` strings are what the phones send as base64.

The hypotheses: the two devices and keys differ, the token is lower case, each base64 string decodes
to the bytes of its side, the keys in the transcripts are the enrolled ones, both sides are `Ready`
at attempt 0 with this nonce, rates are in 36000..96000, versions are 1 or 2, a v2 side copies the
server's `code_commit` for these codes at its own rate, the self deltas pass with the stored
calibration (0 in v2), and the exact flight is strictly between -20 and 60.

Nothing here is about sound. It does not say such a plan exists; that is a separate result. -/
structure X1Plan (e : Env B D) (nonce sid : B) where
  dA : D
  dB : D
  seed : String
  token : String
  T : ℕ
  cal : D → ℤ
  sA : Side B
  sB : Side B
  cbA : B
  sbA : B
  tbA : B
  tsA : B
  cbB : B
  sbB : B
  tbB : B
  tsB : B
  hdev : dA ≠ dB
  hkey : e.pk dA ≠ e.pk dB
  htok : token.toLower = token
  hcbA : e.b64d cbA = some sA.commit_raw
  hsbA : e.b64d sbA = some sA.commit_sig
  htbA : e.b64d tbA = some sA.raw
  htsA : e.b64d tsA = some sA.sig
  hcbB : e.b64d cbB = some sB.commit_raw
  hsbB : e.b64d sbB = some sB.commit_sig
  htbB : e.b64d tbB = some sB.raw
  htsB : e.b64d tsB = some sB.sig
  hpk : sA.pk_self = e.pk dA ∧ sA.pk_partner = e.pk dB ∧ sB.pk_self = e.pk dB ∧ sB.pk_partner = e.pk dA
  hRA : sA.Ready e.p .A 0 nonce
  hRB : sB.Ready e.p .B 0 nonce
  hrA1 : 36000 ≤ sA.sample_rate
  hrA2 : sA.sample_rate ≤ 96000
  hrB1 : 36000 ≤ sB.sample_rate
  hrB2 : sB.sample_rate ≤ 96000
  hvA : sA.version = 1 ∨ sA.version = 2
  hvB : sB.version = 1 ∨ sB.version = 2
  hccA : sA.version = 2 → sA.code_commit = some (e.code_commit sA.sample_rate ⟨seed, .A, 0⟩ ⟨seed, .B, 0⟩)
  hccB : sB.version = 2 → sB.code_commit = some (e.code_commit sB.sample_rate ⟨seed, .B, 0⟩ ⟨seed, .A, 0⟩)
  hdA : self_os_ok sA.self_os_delta sA.sample_rate (if sA.version = 2 then 0 else cal dA) = true
  hdB : self_os_ok sB.self_os_delta sB.sample_rate (if sB.version = 2 then 0 else cal dB) = true
  hf1 : -20 < flight_exact sA.half sA.sample_rate sB.half sB.sample_rate
  hf2 : flight_exact sA.half sA.sample_rate sB.half sB.sample_rate < 60

namespace X1Plan

variable {e : Env B D} {nonce sid : B} (P : X1Plan e nonce sid)

/-- The world `n` ms after `create`: clock `T + n`, calibration `cal`. -/
def W (n : ℕ) : World D := ⟨P.T + n, P.cal⟩

/-! ### The nine requests -/

/-- Guest joins with the token. -/
def reqJoin : Req B D := .api false (some P.dB) false (.join P.token)
/-- Host confirms. -/
def reqConfA : Req B D := opReq P.dA .confirm
/-- Guest confirms. -/
def reqConfB : Req B D := opReq P.dB .confirm
/-- Host arms at attempt 0, its own rate, rtt 0, its own version. -/
def reqArmA : Req B D := opReq P.dA (.arm (.int 0) (.int P.sA.sample_rate) (some 0) (.int P.sA.version))
/-- Guest arms at attempt 0, its own rate, rtt 0, its own version. -/
def reqArmB : Req B D := opReq P.dB (.arm (.int 0) (.int P.sB.sample_rate) (some 0) (.int P.sB.version))
/-- Host commits. -/
def reqComA : Req B D := opReq P.dA (.commit P.cbA P.sbA)
/-- Guest commits. -/
def reqComB : Req B D := opReq P.dB (.commit P.cbB P.sbB)
/-- Host sends its transcript. -/
def reqTxA : Req B D := opReq P.dA (.transcript P.tbA P.tsA)
/-- Guest sends its transcript. -/
def reqTxB : Req B D := opReq P.dB (.transcript P.tbB P.tsB)

/-- The nine timed requests after `create`. Commits at `T+4310` are past the gate
`t0 + 1200 = T+4211`; transcripts at `T+4411` are well before the deadline `t0 + 20000`. -/
def reqs : List (World D × Req B D) :=
  [(P.W 1, P.reqJoin), (P.W 2, P.reqConfA), (P.W 3, P.reqConfB),
   (P.W 10, P.reqArmA), (P.W 11, P.reqArmB),
   (P.W 4310, P.reqComA), (P.W 4311, P.reqComB),
   (P.W 4410, P.reqTxA), (P.W 4411, P.reqTxB)]

/-! ### The documents the walk should pass through, written by hand -/

/-- After `create` at `T`, host `dA`. -/
def d0 : Doc B D := (create (P.W 0) P.dA sid nonce P.seed P.token).1

/-- After the join. -/
def d1 : Doc B D := { P.d0 with guest_device_id := some P.dB, state := .joined, seq := 2 }

/-- After the host confirms. -/
def d2 : Doc B D := { P.d1 with confirmed := upd _flags .A true, seq := 3 }

/-- After the guest confirms. -/
def d3 : Doc B D :=
  { P.d2 with confirmed := upd (upd _flags .A true) .B true, state := .confirmed, seq := 4 }

/-- After the host arms at `T+10`. -/
def d4 : Doc B D :=
  { P.d3 with
    per_role := upd P.d3.per_role .A
      ({ arm := some ⟨P.sA.sample_rate, P.T + 10, P.sA.version, P.cal P.dA⟩ } : PerRole B)
    armed := upd _flags .A true
    seq := 5 }

/-- After the guest arms at `T+11`: started, `t0 = T + 3011`. -/
def d5 : Doc B D :=
  { P.d4 with
    per_role := upd P.d4.per_role .B
      ({ arm := some ⟨P.sB.sample_rate, P.T + 11, P.sB.version, P.cal P.dB⟩ } : PerRole B)
    armed := upd (upd _flags .A true) .B true
    state := .started
    t0_ms := some (P.T + 3011)
    seq := 6 }

/-- What the host's commit stores at `T+4310`. -/
def cdA : CommitData B :=
  ⟨P.cbA, P.sbA, e.p.sha256 P.sA.commit_raw, P.sA.rec_, P.T + 4310,
    if P.sA.version = 2 then some (_code_commit e P.d5 .A) else none⟩

/-- After the host commits. -/
def d6 : Doc B D := commitStore P.d5 .A P.cdA

/-- What the guest's commit stores at `T+4311`. `_code_commit` reads `d6`, the document it runs on. -/
def cdB : CommitData B :=
  ⟨P.cbB, P.sbB, e.p.sha256 P.sB.commit_raw, P.sB.rec_, P.T + 4311,
    if P.sB.version = 2 then some (_code_commit e P.d6 .B) else none⟩

/-- After the guest commits. -/
def d7 : Doc B D := commitStore P.d6 .B P.cdB

/-- What the host's transcript stores. -/
def tdA : TxData B := ⟨P.tbA, P.tsA, e.p.sha256 P.sA.raw, P.sA.half, P.sA.self_os_delta⟩

/-- What the guest's transcript stores. -/
def tdB : TxData B := ⟨P.tbB, P.tsB, e.p.sha256 P.sB.raw, P.sB.half, P.sB.self_os_delta⟩

/-- After the host's transcript at `T+4410`: stored, one side in, saved. -/
def d8 : Doc B D := _save (txStore P.d7 .A P.tdA)

/-- After the guest's transcript at `T+4411`: both in, finalized as NEAR at the exact flight. -/
def d9 : Doc B D :=
  _finalize e (P.W 4411) (txStore P.d8 .B P.tdB) .NEAR none
    (some (flight_exact P.sA.half P.sA.sample_rate P.sB.half P.sB.sample_rate)) .verdict none

/-! ### Small facts -/

/-- `d0` is reachable at clock `T`. -/
theorem d0_reachable : Reachable e P.T P.d0 :=
  Reachable.create (P.W 0) P.dA sid nonce P.seed P.token

omit [DecidableEq B] [DecidableEq D] in
/-- The nine requests are in clock order from `T`. -/
theorem reqs_inOrder : inOrderL P.T P.reqs = true := by
  simp [reqs, inOrderL, W]

omit [DecidableEq B] [DecidableEq D] in
/-- The last clock of the nine requests is `T + 4411`. -/
theorem reqs_last : lastTimeL P.T P.reqs = P.T + 4411 := rfl

/-- The whole run from `d0` is reachable at `T + 4411`. It says nothing about the document it ends on;
the step lemmas pin that it is `d9`. -/
theorem run_reachable : Reachable e (P.T + 4411) (runL e P.d0 P.reqs) := by
  have h := runL_reachable P.d0_reachable P.reqs P.reqs_inOrder
  rwa [P.reqs_last] at h

end X1Plan

end Plan

#check @inOrderL
#check @lastTimeL
#check @runL
#check @runL_cons
#check @runL_append
#check @runL_reachable
#check @opReq
#check @X1Plan
#check @X1Plan.W
#check @X1Plan.reqs
#check @X1Plan.d0
#check @X1Plan.d5
#check @X1Plan.cdA
#check @X1Plan.cdB
#check @X1Plan.tdA
#check @X1Plan.d9
#check @X1Plan.run_reachable

#print axioms runL_reachable
#print axioms runL_append
#print axioms X1Plan.d0_reachable
#print axioms X1Plan.reqs_inOrder
#print axioms X1Plan.run_reachable

end Machine
end ServerFv
