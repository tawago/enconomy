import Popfv.Pair

/-!
# The verdict rules of the server (`server/pop/verdict.py`)

A literal Lean copy of `verdict.py`. Same names, same order of checks.
Line numbers in the comments are for that file, unless another file is named.
Property ids (V1 .. V6, X1) are from `fv/v1/server/spec.md`.

**What this file shows, and what it does not.** These results show the server follows its rules
on signed numbers. They do not show a phone told the truth about the air (CN1). A NEAR means two
keys signed two numbers that fit a range. It does not mean two phones were close. Theorem `X1`
says exactly this, and it sits next to the others so nobody reads them as more than they are.

**Scope.** Only the basic proximity check. Sessions are taken with `context=None` and
`early_nonce=False`. Contexts, zk routes, the presence signature, recording upload and audio
processing are not modeled, and nothing is claimed about them. The session steps themselves
(`sessions.py`) are not in this file either. So `X1` here stops at `check_commit`,
`check_transcript`, `combine` and `verify_record`. The session walk to `result.verdict = NEAR`
is not proved here. `sessions.py` never calls `check_commit`. It has its own copy of those checks
(`sessions.py:279-290`), with an armed version check, and a `too_early` gate after it (`:296`).

**Assumptions, by name.**
* A1, honest server: the code runs as written. All of this is about that code.
* A4, signatures can't be forged: only used where a theorem says `Unforgeable` in its hypotheses.
  Exactly one theorem here does, `V5_record_swapped_mixed_versions`.
* A5, no hash collisions: not used in this file. Hashes are opaque functions, and equal
  hashes are never turned into equal messages here.
* `Powers`, named: any value in the wire ranges and widths can be written as bytes, and each key's
  holder can sign. Only `X1` uses it. It is a hypothesis about the codec, not a fact proved about
  `codec.py`. That the Python gives it is by reading and by runs. `Powers_satisfiable` shows it can
  hold on a Lean copy of the byte layout (`Layout`). What that decoder returns always has the wire
  widths, and it refuses a wrong total length. It says nothing more about the Python than that. `X1_core`, `X1_witness_v1` and `X1_witness_v2` don't use it.
* SHA-256 gives 32 bytes: a named hypothesis of `X1` (`hsha`). It is about the hash's width only.
* One uvicorn worker and no await between load and save (A2, A3): not used here. This file has no
  stored state.

**How the Lean copy differs from the Python.** These are the differences we know of.
* Byte strings are a type parameter `B` with equality. A later run on traces can pick any concrete
  type. `verify_raw`, `sha256`, `decode_commit` and `decode_transcript` are opaque, passed in
  `Prims`. Nothing is assumed about them unless a theorem says so.
* `hmac.compare_digest` is plain equality. Timing is out of scope.
* `Reject`'s detail text is dropped. Only the reason is kept.
* `Fraction` with denominator 0 raises `ZeroDivisionError`, while Lean's `x / 0` is 0. So `combine`
  has an explicit `zero_division` outcome at line 165. Only a direct call can reach it (V1).
* `flight_cm` in the result is the exact rational. The Python stores `round(float(f), 2)` for
  display. The verdict comes from the exact value in both. Display is V8, not here.
* `by` is a Lean keyword, so the result field is `by_`.
* `decode_*` failing is `none`. The `ValueError` text is dropped.
* One field `rec_` stands for (`rec` alone clashes with a Lean built-in) `rec_sha256` (v1) or `rec_root` (v2). `REC_KEY` only picks the name.
  A v1 transcript has `delta = none` and `code_commit = none`, as the Python dict has no such key.
* In `verify_record`, the record's base64 and hex are taken as already decoded. Bad base64 in a
  record is not modeled, and neither is a record missing a key other than the ones line 181 reads.
* `REC_KEY[version]` raises `KeyError` at lines 136 and 185-188 if the version isn't 1 or 2. The Lean
  has no such outcome and goes on. Only a decoder that returns such a version could get there, and
  `codec.py:59`, `:89` refuse them. So theorems about an opaque decoder also cover versions the Python
  can't reach, and say nothing true of the Python for those. In the same way, a v2 transcript with no
  `delta` is a `KeyError` at line 140 and a plain reject here. Again the real decoder can't give one.
* Rates are `ℕ`. A direct Python call to `self_os_ok` or `flight_exact` could pass a negative int. The
  real decoder can't, as the field is `u32` (`codec.py:29`).
* `role` is one of two values. A direct Python call could pass another string.
* `decide` takes a rational. A direct Python call could pass a float, which is compared as given (line 82).
* Not modeled at all: the derived v2 fields `p_self` and `a_partner` (`codec.py:100-101`), and
  `flight_cm`, `FINAL_REASONS` and `USER_TEXT` (`verdict.py:76-77`, `:42`, `:44-57`). No check in
  `verdict.py` reads `p_self` or `a_partner`.
* `Prims.width` stands for Python's `len`. No check in `verdict.py` reads it. Only `wire_ok` does.
-/

set_option linter.style.whitespace false
set_option linter.style.longLine false
set_option linter.style.header false
set_option linter.unusedVariables false
set_option linter.unusedSimpArgs false

namespace ServerFv

/-! ## Constants (`constants.py`) -/

namespace K
/-- `constants.py:4` -/
abbrev SR_MIN : ℕ := 36000
/-- `constants.py:4` -/
abbrev SR_MAX : ℕ := 96000
/-- `constants.py:22` -/
abbrev IMPOSSIBLE_CM : ℤ := -20
/-- `constants.py:23` -/
abbrev NEAR_CM : ℤ := 60
/-- `constants.py:24` -/
abbrev SPEED_OF_SOUND_CM_S : ℕ := 34300
/-- `constants.py:27` -/
abbrev SELF_OS_TOL_MS : ℕ := 50
/-- `constants.py:40` -/
abbrev DELTA_MS : ℕ := 2
end K

/-! ## Data -/

/-- The two roles. The decoders accept only these (`codec.py:61`, `:91`). -/
inductive Role | A | B
  deriving DecidableEq, Repr

/-- Reasons, same words as `verdict.py:37-42`. -/
inductive Reason
  | capture_failed | glitch | self_not_heard | self_timestamp_mismatch | partner_not_heard
  | impossible_flight | timeout | too_far | signature_invalid | transcript_mismatch
  | partner_mismatch | aborted
  deriving DecidableEq, Repr

/-- `RETRY_REASONS`, `verdict.py:37-38`. -/
def RETRY_REASONS : List Reason :=
  [.capture_failed, .glitch, .self_not_heard, .self_timestamp_mismatch, .partner_not_heard,
   .impossible_flight, .timeout]

/-- `PHONE_REASONS`, `verdict.py:40-41`. -/
def PHONE_REASONS : List Reason :=
  [.capture_failed, .glitch, .self_not_heard, .self_timestamp_mismatch, .partner_not_heard,
   .partner_mismatch]

/-- The two verdict strings. -/
inductive Verdict | NEAR | NOT_NEAR
  deriving DecidableEq, Repr

/-- What the Python can raise here. `reject` is `class Reject` (`verdict.py:60`).
`zero_division` is the `ZeroDivisionError` from `Fraction` with rate 0. -/
inductive Raised
  | reject (reason : Reason)
  | zero_division
  deriving DecidableEq, Repr

/-- A decoded commitment (`codec.py:55-67`). `version` 1 stands for a dict with no `version` key. -/
structure Commit (B : Type) where
  role : Role
  attempt : ℕ
  nonce : B
  rec_ : B
  version : ℕ
  deriving DecidableEq, Repr

/-- A decoded transcript (`codec.py:30-34`, `:84-102`). Signed fields are `ℤ`, unsigned are `ℕ`.
`rec_` is `rec_sha256` (v1) or `rec_root` (v2). The last four are v2 only. -/
structure Transcript (B : Type) where
  role : Role
  attempt : ℕ
  nonce : B
  pk_self : B
  pk_partner : B
  sample_rate : ℕ
  half : ℤ
  rec_ : B
  play_frame_position : ℕ
  play_nano_time : ℕ
  rec_frame0_nano_time : ℕ
  self_os_delta : ℤ
  commit_hash : B
  version : ℕ
  a_self : Option ℕ
  p_partner : Option ℕ
  delta : Option ℕ
  code_commit : Option B
  deriving DecidableEq, Repr

/-- `version_of`, `codec.py:39-40`. -/
def version_of {B : Type} (t : Transcript B) : ℕ := t.version

/-- The opaque parts. Nothing is assumed about them unless a theorem says so.
`rec_root_ok` is the check `rec_root < r` (`codec.py:43-45`), and `width` is `len`, the number of
bytes. Both are used only to say which values can be encoded. -/
structure Prims (B : Type) where
  width : B → ℕ
  verify_raw : B → B → B → Bool
  sha256 : B → B
  rec_root_ok : B → Bool
  decode_commit : B → Option (Commit B)
  decode_transcript : B → Option (Transcript B)

variable {B : Type} [DecidableEq B]

/-- **A4, by name.** A signature check passes only if the key's holder really signed that message.
`signed pk m` means "the holder of `pk` signed `m`". It is about messages, not signature bytes, so
a second valid signature on a signed message is not a forgery (`crypto.py:32`). -/
def Unforgeable (p : Prims B) (signed : B → B → Prop) : Prop :=
  ∀ pk m s, p.verify_raw pk m s = true → signed pk m

/-! ## The functions, in file order -/

/-- `self_os_ok`, `verdict.py:66-69`. -/
def self_os_ok (delta_frames : ℤ) (sr : ℕ) (cal_us : ℤ := 0) : Bool :=
  |delta_frames * 1000000 - cal_us * (sr : ℤ)| ≤ ((K.SELF_OS_TOL_MS * 1000 * sr : ℕ) : ℤ)

/-- `flight_exact`, `verdict.py:72-73`. -/
def flight_exact (half_a : ℤ) (sr_a : ℕ) (half_b : ℤ) (sr_b : ℕ) : ℚ :=
  ((K.SPEED_OF_SOUND_CM_S : ℚ) / 2) * ((half_a : ℚ) / (sr_a : ℚ) - (half_b : ℚ) / (sr_b : ℚ))

/-- `decide`, `verdict.py:80-87`, on a rational, which is all `combine` ever passes. -/
def decide (flight : ℚ) : Option Verdict × Option Reason :=
  if flight ≤ (K.IMPOSSIBLE_CM : ℚ) then (none, some .impossible_flight)  -- line 83
  else if flight ≥ (K.NEAR_CM : ℚ) then (some .NOT_NEAR, some .too_far)   -- line 85
  else (some .NEAR, none)                                                  -- line 87

/-- `check_commit`, `verdict.py:90-99`. -/
def check_commit (p : Prims B) (commit_raw sig : B) (role : Role) (pk nonce : B) (attempt : ℕ) :
    Except Raised (Commit B) :=
  match p.decode_commit commit_raw with
  | none => .error (.reject .transcript_mismatch)                            -- lines 93-94
  | some c =>
    if p.verify_raw pk commit_raw sig = false then
      .error (.reject .signature_invalid)                                    -- lines 95-96
    else if c.role ≠ role ∨ c.attempt ≠ attempt ∨ c.nonce ≠ nonce then
      .error (.reject .transcript_mismatch)                                  -- lines 97-98
    else .ok c

/-- `popt2.delta`, `popt2.py:40-41`. -/
def popt2_delta (sr : ℕ) : ℕ := K.DELTA_MS * sr / 1000

/-- Pins `K.DELTA_MS` and `popt2_delta` to one number: 2 ms at rate 48000 is 96 frames. Without this,
changing the constant would still build.

It says nothing about the air, and it does not show a phone told the truth about it (CN1). -/
theorem popt2_delta_48000 : popt2_delta 48000 = 96 := by
  norm_num [popt2_delta]

/-- `check_transcript`, `verdict.py:102-144`. Same order of checks. -/
def check_transcript (p : Prims B) (raw sig : B) (role : Role) (pk_self pk_partner nonce : B)
    (attempt : ℕ) (commit_sha256 rec : Option B) (sample_rate : Option ℕ := none)
    (version : ℕ := 1) (code_commit : Option B := none) : Except Raised (Transcript B) :=
  match p.decode_transcript raw with
  | none => .error (.reject .transcript_mismatch)                            -- lines 114-115
  | some t =>
    if p.verify_raw pk_self raw sig = false then .error (.reject .signature_invalid)  -- 116-117
    else if version_of t ≠ version then .error (.reject .transcript_mismatch)         -- 118-119
    else if t.pk_self ≠ pk_self then .error (.reject .signature_invalid)              -- 120-121
    else if t.role ≠ role then .error (.reject .transcript_mismatch)                  -- 122-123
    else if t.nonce ≠ nonce then .error (.reject .transcript_mismatch)                -- 124-125
    else if t.attempt ≠ attempt then .error (.reject .transcript_mismatch)            -- 126-127
    else if t.pk_partner ≠ pk_partner then .error (.reject .transcript_mismatch)      -- 128-129
    else if sample_rate ≠ none ∧ some t.sample_rate ≠ sample_rate then
      .error (.reject .transcript_mismatch)                                           -- 130-131
    else if ¬ (K.SR_MIN ≤ t.sample_rate ∧ t.sample_rate ≤ K.SR_MAX) then
      .error (.reject .transcript_mismatch)                                           -- 132-133
    else if commit_sha256 = none ∨ some t.commit_hash ≠ commit_sha256 then
      .error (.reject .transcript_mismatch)                                           -- 134-135
    else if rec = none ∨ some t.rec_ ≠ rec then
      .error (.reject .transcript_mismatch)                                           -- 136-138
    else if version = 2 then                                                          -- 139
      if t.delta ≠ some (popt2_delta t.sample_rate) then
        .error (.reject .transcript_mismatch)                                         -- 140-141
      else if code_commit ≠ none ∧ t.code_commit ≠ code_commit then
        .error (.reject .transcript_mismatch)                                         -- 142-143
      else .ok t
    else .ok t

/-- The dict `combine` returns. `flight_cm` here is exact, see the top of this file. -/
structure CombineOut where
  flight_cm : Option ℚ
  verdict : Option Verdict
  reason : Option Reason
  by_ : Option Role
  deriving DecidableEq, Repr

/-- `verdict.py:162`: the calibration a transcript's self check uses. v2: 0. v1: the role's entry
in `cal_us`, or 0 if `cal_us` or the entry is missing. -/
def cal_for (t : Transcript B) (cal_us : Option (Role → Option ℤ)) : ℤ :=
  if version_of t = 2 then 0 else (cal_us.bind (fun m => m t.role)).getD 0

/-- The self check of one transcript inside `combine`, `verdict.py:163`. -/
def self_check (t : Transcript B) (cal_us : Option (Role → Option ℤ)) : Bool :=
  self_os_ok t.self_os_delta t.sample_rate (cal_for t cal_us)

/-- `combine`, `verdict.py:147-167`. -/
def combine (ta tb : Transcript B) (cal_us : Option (Role → Option ℤ) := none) :
    Except Raised CombineOut :=
  if ta.role ≠ .A ∨ tb.role ≠ .B then .error (.reject .transcript_mismatch)         -- 155-156
  else if ta.nonce ≠ tb.nonce ∨ ta.attempt ≠ tb.attempt then
    .error (.reject .transcript_mismatch)                                           -- 157-158
  else if ta.pk_partner ≠ tb.pk_self ∨ tb.pk_partner ≠ ta.pk_self ∨ ta.pk_self = tb.pk_self then
    .error (.reject .transcript_mismatch)                                           -- 159-160
  else if self_check ta cal_us = false then                                         -- 161-164, A first
    .ok ⟨none, none, some .self_timestamp_mismatch, some ta.role⟩
  else if self_check tb cal_us = false then
    .ok ⟨none, none, some .self_timestamp_mismatch, some tb.role⟩
  else if ta.sample_rate = 0 ∨ tb.sample_rate = 0 then .error .zero_division         -- 165, Fraction
  else
    let f := flight_exact ta.half ta.sample_rate tb.half tb.sample_rate             -- 165
    let r := decide f                                                               -- 166
    .ok ⟨some f, r.1, r.2, none⟩                                                    -- 167

/-- A signed record as `verify_record` reads it: raw bytes and signature. -/
structure SignedEntry (B : Type) where
  raw : B
  sig : B
  deriving DecidableEq, Repr

/-- One entry of `rec["devices"]`, the two keys `verify_record` reads. -/
structure DeviceEntry (B : Type) where
  pubkey : B
  cal_us : Option ℤ

/-- A §8.4 record, only the parts `verify_record` reads (`verdict.py:176-189`). -/
structure ResultRecord (B : Type) where
  session_nonce : B
  attempt : ℕ
  devices : Role → DeviceEntry B
  transcripts : Role → Option (SignedEntry B)
  commits : Option (Role → Option (SignedEntry B))

/-- One round of the loop in `verify_record`, `verdict.py:180-188`. -/
def verify_one (p : Prims B) (rec : ResultRecord B) (r other : Role) :
    Except Raised (Transcript B) :=
  match rec.transcripts r, rec.commits.bind (fun m => m r) with
  | some tr, some cm =>
    match check_commit p cm.raw cm.sig r (rec.devices r).pubkey rec.session_nonce rec.attempt with
    | .error e => .error e
    | .ok c =>
      check_transcript p tr.raw tr.sig r (rec.devices r).pubkey (rec.devices other).pubkey
        rec.session_nonce rec.attempt (some (p.sha256 cm.raw)) (some c.rec_) none c.version none
  | _, _ => .error (.reject .transcript_mismatch)                                   -- 181-182

/-- `verify_record`, `verdict.py:170-189`. A first, then B, then `combine`. -/
def verify_record (p : Prims B) (rec : ResultRecord B) : Except Raised CombineOut :=
  match verify_one p rec .A .B with
  | .error e => .error e
  | .ok ta =>
    match verify_one p rec .B .A with
    | .error e => .error e
    | .ok tb => combine ta tb (some (fun r => some ((rec.devices r).cal_us.getD 0)))

/-! ## Small tools -/

omit [DecidableEq B] in
private theorem ite_err_ok {α : Type} {c : Prop} [Decidable c] {e : Raised} {x : Except Raised α} {t : α} :
    (if c then Except.error e else x) = Except.ok t ↔ ¬ c ∧ x = Except.ok t := by
  split <;> simp_all

/-- Exactly what it takes for `check_transcript` to return `t`. Each conjunct is one line of the
Python. V6 is the left-to-right half. `X1` uses the right-to-left half. -/
theorem check_transcript_ok_iff (p : Prims B) (raw sig : B) (role : Role) (pk_self pk_partner nonce : B)
    (attempt : ℕ) (commit_sha256 rec : Option B) (sample_rate : Option ℕ) (version : ℕ)
    (code_commit : Option B) (t : Transcript B) :
    check_transcript p raw sig role pk_self pk_partner nonce attempt commit_sha256 rec sample_rate
        version code_commit = .ok t ↔
      p.decode_transcript raw = some t ∧ p.verify_raw pk_self raw sig = true ∧
      t.version = version ∧ t.pk_self = pk_self ∧ t.role = role ∧ t.nonce = nonce ∧
      t.attempt = attempt ∧ t.pk_partner = pk_partner ∧
      (sample_rate ≠ none → some t.sample_rate = sample_rate) ∧
      36000 ≤ t.sample_rate ∧ t.sample_rate ≤ 96000 ∧
      commit_sha256 = some t.commit_hash ∧ rec = some t.rec_ ∧
      (version = 2 → t.delta = some (popt2_delta t.sample_rate) ∧
        (code_commit ≠ none → t.code_commit = code_commit)) := by
  rcases hd : p.decode_transcript raw with _ | t0
  · simp [check_transcript, hd]
  · simp only [check_transcript, hd, ite_err_ok, version_of, Option.some.injEq, K.SR_MIN, K.SR_MAX]
    have last : (if version = 2 then
          (if t0.delta ≠ some (popt2_delta t0.sample_rate) then
            (Except.error (Raised.reject .transcript_mismatch) : Except Raised (Transcript B))
          else if code_commit ≠ none ∧ t0.code_commit ≠ code_commit then
            Except.error (Raised.reject .transcript_mismatch)
          else Except.ok t0)
        else Except.ok t0) = Except.ok t ↔
        t0 = t ∧ (version = 2 → t0.delta = some (popt2_delta t0.sample_rate) ∧
          (code_commit ≠ none → t0.code_commit = code_commit)) := by
      by_cases hv : version = 2
      · by_cases h1 : t0.delta = some (popt2_delta t0.sample_rate)
        · by_cases h2 : code_commit ≠ none ∧ t0.code_commit ≠ code_commit
          · simp only [hv, ite_true, h1, ne_eq, not_true_eq_false, ite_false]
            simp [h2.1, h2.2]
          · have h2' : code_commit ≠ none → t0.code_commit = code_commit := by
              intro h; by_contra h3; exact h2 ⟨h, h3⟩
            simp [hv, h1, h2]
            intro _ h
            exact h2' h
        · simp [hv, h1]
      · simp [hv]
    rw [last]
    constructor
    · rintro ⟨h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, rfl, h12⟩
      simp only [Bool.not_eq_false, ne_eq, not_not] at h1 h2 h3 h4 h5 h6 h7 h8 h9 h10 h11
      refine ⟨rfl, h1, h2, h3, h4, h5, h6, h7, ?_, h9.1, h9.2, ?_, ?_, h12⟩
      · intro h; by_contra h'; exact h8 ⟨h, h'⟩
      · rcases commit_sha256 with _ | c <;> simp_all
      · rcases rec with _ | c <;> simp_all
    · rintro ⟨rfl, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, rfl, rfl, h12⟩
      simp only [Bool.not_eq_false, ne_eq, not_not]
      refine ⟨h1, h2, h3, h4, h5, h6, h7, ?_, ⟨h9, h10⟩, by simp, by simp, trivial, h12⟩
      rintro ⟨h, h'⟩; exact h' (h8 h)

/-- Exactly what it takes for `check_commit` to return `c`. -/
theorem check_commit_ok_iff (p : Prims B) (commit_raw sig : B) (role : Role) (pk nonce : B)
    (attempt : ℕ) (c : Commit B) :
    check_commit p commit_raw sig role pk nonce attempt = .ok c ↔
      p.decode_commit commit_raw = some c ∧ p.verify_raw pk commit_raw sig = true ∧
      c.role = role ∧ c.attempt = attempt ∧ c.nonce = nonce := by
  rcases hd : p.decode_commit commit_raw with _ | c0
  · simp [check_commit, hd]
  · simp only [check_commit, hd, ite_err_ok, Option.some.injEq]
    by_cases ht : c0 = c
    · subst ht
      simp only [Bool.not_eq_false, not_or, ne_eq, not_not, true_and, and_true, iff_true]
    · constructor
      · intro h
        exact absurd (by simpa using h.2.2) ht
      · rintro ⟨h, -⟩; exact absurd h ht

/-! ## V2: `decide` -/

/-- **V2 (rule C21).** For every rational flight, `decide` gives exactly one of three answers.
At or below -20: no verdict, `impossible_flight`. At or above 60: `NOT_NEAR`, `too_far`.
Strictly between: `NEAR`, no reason. Both edges are out of NEAR. `NaN` is not a rational, so it is
not covered. No caller passes a float (spec.md, V2).

This is about the number the server computes. It does not show a phone told the truth about the
air (CN1). -/
theorem V2 (f : ℚ) :
    (decide f = (none, some .impossible_flight) ↔ f ≤ -20) ∧
    (decide f = (some .NOT_NEAR, some .too_far) ↔ 60 ≤ f) ∧
    (decide f = (some .NEAR, none) ↔ (-20 < f ∧ f < 60)) ∧
    (decide f = (none, some .impossible_flight) ∨ decide f = (some .NOT_NEAR, some .too_far) ∨
      decide f = (some .NEAR, none)) := by
  have c1 : ((K.IMPOSSIBLE_CM : ℤ) : ℚ) = -20 := by norm_num
  have c2 : ((K.NEAR_CM : ℤ) : ℚ) = 60 := by norm_num
  unfold decide
  rw [c1, c2]
  by_cases h1 : f ≤ -20
  · have h2 : ¬ (f ≥ 60) := by intro h; linarith
    have h3 : ¬ (60 ≤ f) := h2
    have h4 : ¬ (-20 < f) := by linarith
    simp [h1, h3, h4]
  · have h1' : -20 < f := not_le.mp h1
    by_cases h2 : f ≥ 60
    · have h3 : 60 ≤ f := h2
      have h4 : ¬ (f < 60) := not_lt.mpr h3
      simp [h1, h2, h3, h4]
    · have h3 : ¬ (60 ≤ f) := h2
      have h4 : f < 60 := not_le.mp h3
      simp [h1, h2, h3, h1', h4]

/-! ## V3: the integer form, and the bridge to the circuit -/

/-- `flight_exact` as one fraction, for positive rates. -/
private theorem flight_as_fraction (hA hB : ℤ) (a b : ℕ) (ha : 0 < a) (hb : 0 < b) :
    flight_exact hA a hB b =
      (34300 * ((hA * b - hB * a : ℤ) : ℚ)) / (2 * (((a : ℤ) * (b : ℤ) : ℤ) : ℚ)) := by
  have aq : (a : ℚ) ≠ 0 := by exact_mod_cast ha.ne'
  have bq : (b : ℚ) ≠ 0 := by exact_mod_cast hb.ne'
  unfold flight_exact
  push_cast
  field_simp

/-- The tie rule of `verdict.py:10-11`. With `N = hA·srB - hB·srA` and `S = srA·srB`:
flight at or below -20 is `c·N ≤ -40·S`, and flight at or above 60 is `c·N ≥ 120·S`. Exact integers,
no rounding.

It does not show a phone told the truth about the air (CN1). -/
theorem V3_ties (hA hB : ℤ) (a b : ℕ) (ha : 0 < a) (hb : 0 < b) :
    (flight_exact hA a hB b ≤ -20 ↔
      34300 * (hA * b - hB * a) ≤ -40 * ((a : ℤ) * b)) ∧
    (60 ≤ flight_exact hA a hB b ↔
      120 * ((a : ℤ) * b) ≤ 34300 * (hA * b - hB * a)) := by
  rw [flight_as_fraction hA hB a b ha hb]
  set n : ℤ := hA * b - hB * a
  set s : ℤ := (a : ℤ) * b with hs
  have sq : (0 : ℚ) < (s : ℚ) := by
    have : 0 < s := by rw [hs]; positivity
    exact_mod_cast this
  rw [div_le_iff₀ (by positivity), le_div_iff₀ (by positivity)]
  constructor
  · constructor
    · intro h
      have : ((34300 * n : ℤ) : ℚ) ≤ ((-40 * s : ℤ) : ℚ) := by push_cast; linarith
      exact_mod_cast this
    · intro h
      have : ((34300 * n : ℤ) : ℚ) ≤ ((-40 * s : ℤ) : ℚ) := by exact_mod_cast h
      push_cast at this; linarith
  · constructor
    · intro h
      have : ((120 * s : ℤ) : ℚ) ≤ ((34300 * n : ℤ) : ℚ) := by push_cast; linarith
      exact_mod_cast this
    · intro h
      have : ((120 * s : ℤ) : ℚ) ≤ ((34300 * n : ℤ) : ℚ) := by exact_mod_cast h
      push_cast at this; linarith

/-- **V3, integer form.** On the wire ranges, flight is strictly between -20 and 60 exactly when
`-40·S < 34300·N < 120·S`, with `N = hA·srB - hB·srA` and `S = srA·srB`. Whole numbers only.
The proof only needs the rates to be positive. The other ranges are here to match the spec.

This is arithmetic on numbers the phones chose. It does not show a phone told the truth about the
air (CN1). -/
theorem V3 (hA hB : ℤ) (a b : ℕ)
    (_hA1 : -2^31 ≤ hA) (_hA2 : hA < 2^31) (_hB1 : -2^31 ≤ hB) (_hB2 : hB < 2^31)
    (ha1 : 36000 ≤ a) (_ha2 : a ≤ 96000) (hb1 : 36000 ≤ b) (_hb2 : b ≤ 96000) :
    (-20 < flight_exact hA a hB b ∧ flight_exact hA a hB b < 60) ↔
      (-40 * ((a : ℤ) * b) < 34300 * (hA * b - hB * a) ∧
       34300 * (hA * b - hB * a) < 120 * ((a : ℤ) * b)) := by
  obtain ⟨t1, t2⟩ := V3_ties hA hB a b (by omega) (by omega)
  have e1 : -20 < flight_exact hA a hB b ↔ -40 * ((a : ℤ) * b) < 34300 * (hA * b - hB * a) := by
    rw [← not_le, t1, not_le]
  have e2 : flight_exact hA a hB b < 60 ↔ 34300 * (hA * b - hB * a) < 120 * ((a : ℤ) * b) := by
    rw [← not_le, t2, not_le]
  rw [e1, e2]

/-- **V3, bridge to the circuit.** On the same ranges, the server's flight range is the same test
as the last two lines of the `pair` circuit. This cites the real `Popfv.distance_iff` from
`fv/v1/zkp/popfv/Popfv/Pair.lean`, not a copy.

It says the server and the circuit agree on the range. It does not show a phone told the truth
about the air (CN1). -/
theorem V3_circuit (hA hB : ℤ) (a b : ℕ)
    (hA1 : -2^31 ≤ hA) (hA2 : hA < 2^31) (hB1 : -2^31 ≤ hB) (hB2 : hB < 2^31)
    (ha1 : 36000 ≤ a) (ha2 : a ≤ 96000) (hb1 : 36000 ≤ b) (hb2 : b ≤ 96000) :
    (-20 < flight_exact hA a hB b ∧ flight_exact hA a hB b < 60) ↔
      (Popfv.fits 70 (34300 * ((hA : Popfv.F) * (b : Popfv.F) - (hB : Popfv.F) * (a : Popfv.F)) +
          40 * ((a : Popfv.F) * (b : Popfv.F)) - 1) ∧
       Popfv.fits 70 (120 * ((a : Popfv.F) * (b : Popfv.F)) -
          34300 * ((hA : Popfv.F) * (b : Popfv.F) - (hB : Popfv.F) * (a : Popfv.F)) - 1)) := by
  rw [Popfv.distance_iff hA1 hA2 hB1 hB2 ha1 ha2 hb1 hb2]
  have e : flight_exact hA a hB b = (34300 / 2) * ((hA : ℚ) / a - (hB : ℚ) / b) := by
    simp [flight_exact]
  rw [e]

/-! ## V4: `self_os_ok` -/

/-- **V4 (rule C20), the rule.** `self_os_ok` holds exactly when
`|d·10^6 - cal·sr| ≤ 50·1000·sr`, in whole numbers, both edges included.

It checks a number the phone signed. It does not show a phone told the truth about the air
(CN1). -/
theorem V4 (d : ℤ) (sr : ℕ) (cal : ℤ) :
    self_os_ok d sr cal = true ↔ |d * 1000000 - cal * (sr : ℤ)| ≤ 50 * 1000 * (sr : ℤ) := by
  simp [self_os_ok]

omit [DecidableEq B] in
/-- **V4, which calibration.** In `combine`, each transcript picks its own: 0 for v2, and the role's
snapshot or 0 for v1. So a pair may mix versions.

It does not show a phone told the truth about the air (CN1). -/
theorem V4_cal (t : Transcript B) (cal_us : Option (Role → Option ℤ)) :
    (t.version = 2 → cal_for t cal_us = 0) ∧
    (t.version ≠ 2 → cal_for t cal_us = (cal_us.bind (fun m => m t.role)).getD 0) := by
  constructor <;> intro h <;> simp [cal_for, version_of, h]

/-- **V4, the edges from the spec.** At 48000 with no calibration, ±2400 pass and ±2401 fail.
With calibration 10000 µs, 480 ± 2400 pass and one more fails.

It does not show a phone told the truth about the air (CN1). -/
theorem V4_edges :
    self_os_ok 2400 48000 0 = true ∧ self_os_ok (-2400) 48000 0 = true ∧
    self_os_ok 2401 48000 0 = false ∧ self_os_ok (-2401) 48000 0 = false ∧
    self_os_ok (480 + 2400) 48000 10000 = true ∧ self_os_ok (480 - 2400) 48000 10000 = true ∧
    self_os_ok (480 + 2401) 48000 10000 = false ∧ self_os_ok (480 - 2401) 48000 10000 = false := by
  norm_num [self_os_ok, abs_of_nonneg, abs_of_neg]

/-- A phone can always pick a number that passes the self check, whatever the calibration in the
allowed range: 0..`CAL_MAX_US_WEB` = 150000, the larger of the two enrolment limits (`calibration.max_us`;
phones get 0..50000). No audio is needed to do so. Used to read `X1` plainly.

It does not show a phone told the truth about the air (CN1). -/
theorem self_os_can_pass (sr : ℕ) (cal : ℤ) (hsr : 36000 ≤ sr) (hsr2 : sr ≤ 96000)
    (hc0 : 0 ≤ cal) (hc1 : cal ≤ 150000) :
    self_os_ok (cal * sr / 1000000) sr cal = true ∧
      -2^31 ≤ cal * sr / 1000000 ∧ cal * sr / 1000000 < 2^31 := by
  have hm : 0 ≤ cal * (sr : ℤ) := by positivity
  have hle : cal * (sr : ℤ) ≤ 150000 * 96000 :=
    mul_le_mul hc1 (by exact_mod_cast hsr2) (by positivity) (by norm_num)
  set x : ℤ := cal * (sr : ℤ) with hx
  have h1 : x / 1000000 * 1000000 ≤ x := Int.ediv_mul_le x (by norm_num)
  have h2 : x < x / 1000000 * 1000000 + 1000000 := by
    have := Int.lt_ediv_add_one_mul_self x (b := 1000000) (by norm_num)
    linarith
  refine ⟨?_, by omega, by omega⟩
  rw [V4, abs_le]
  have hsr' : (36000 : ℤ) ≤ sr := by exact_mod_cast hsr
  constructor <;> omega

/-! ## V1: `combine` -/

/-- The pair checks of `combine`, `verdict.py:155-160`, as one statement. -/
def pair (ta tb : Transcript B) : Prop :=
  ta.role = .A ∧ tb.role = .B ∧ ta.nonce = tb.nonce ∧ ta.attempt = tb.attempt ∧
    ta.pk_partner = tb.pk_self ∧ tb.pk_partner = ta.pk_self ∧ ta.pk_self ≠ tb.pk_self

/-- "This transcript passed `check_transcript`" for some arguments. -/
def passed (p : Prims B) (t : Transcript B) : Prop :=
  ∃ raw sig role pk_self pk_partner nonce attempt commit_sha256 rec sample_rate version code_commit,
    check_transcript p raw sig role pk_self pk_partner nonce attempt commit_sha256 rec sample_rate
      version code_commit = .ok t

private theorem combine_pair_steps {ta tb : Transcript B} (cal : Option (Role → Option ℤ))
    (hp : pair ta tb) :
    combine ta tb cal =
      if self_check ta cal = false then .ok ⟨none, none, some .self_timestamp_mismatch, some ta.role⟩
      else if self_check tb cal = false then
        .ok ⟨none, none, some .self_timestamp_mismatch, some tb.role⟩
      else if ta.sample_rate = 0 ∨ tb.sample_rate = 0 then .error .zero_division
      else
        let f := flight_exact ta.half ta.sample_rate tb.half tb.sample_rate
        let r := decide f
        .ok ⟨some f, r.1, r.2, none⟩ := by
  obtain ⟨h1, h2, h3, h4, h5, h6, h7⟩ := hp
  unfold combine
  simp [h1, h2, h3, h4, h5, h6, h7]

/-- `combine` raises `transcript_mismatch` exactly when the pair checks fail. No rate needed. -/
theorem combine_rejects_iff (ta tb : Transcript B) (cal : Option (Role → Option ℤ)) :
    combine ta tb cal = .error (.reject .transcript_mismatch) ↔ ¬ pair ta tb := by
  by_cases hp : pair ta tb
  · rw [combine_pair_steps cal hp]
    simp only [hp, not_true_eq_false, iff_false]
    split_ifs <;> simp
  · simp only [hp, not_false_eq_true, iff_true]
    unfold combine
    unfold pair at hp
    split_ifs <;> first | rfl | (exfalso; apply hp; grind)

/-- With both self checks passed and rates not zero, the result is the exact flight and what
`decide` says about it. -/
theorem combine_measured {ta tb : Transcript B} {cal : Option (Role → Option ℤ)}
    (hp : pair ta tb) (hA : self_check ta cal = true) (hB : self_check tb cal = true)
    (ha : ta.sample_rate ≠ 0) (hb : tb.sample_rate ≠ 0) :
    combine ta tb cal = .ok
      ⟨some (flight_exact ta.half ta.sample_rate tb.half tb.sample_rate),
       (decide (flight_exact ta.half ta.sample_rate tb.half tb.sample_rate)).1,
       (decide (flight_exact ta.half ta.sample_rate tb.half tb.sample_rate)).2, none⟩ := by
  rw [combine_pair_steps cal hp]
  simp [hA, hB, ha, hb]

/-- **V1 (rules C19, C20, C21).** Take two transcripts that each passed `check_transcript`.
1. `combine` refuses with `transcript_mismatch` exactly when they are not a proper pair: one A, one B,
   same nonce, same attempt, each names the other's key, and the keys differ.
2. The verdict is NEAR exactly when they are a pair, both self checks pass, and the exact flight is
   strictly between -20 and 60.
3. If they are a pair and a self check fails, there is no verdict, the reason is
   `self_timestamp_mismatch`, and `by` is the first failing role. A is checked first.

The pair of hypotheses on `check_transcript` is needed: that is where the rates get their range.
`combine` has no rate check of its own, so a direct call with rate 0 raises (`combine_rate_zero`).

A NEAR here means two keys signed two numbers in a range. It does not show a phone told the truth
about the air (CN1). See `X1`. -/
theorem V1 {p : Prims B} {ta tb : Transcript B} (hta : passed p ta) (htb : passed p tb)
    (cal : Option (Role → Option ℤ)) :
    (combine ta tb cal = .error (.reject .transcript_mismatch) ↔ ¬ pair ta tb) ∧
    ((∃ o, combine ta tb cal = .ok o ∧ o.verdict = some .NEAR) ↔
      pair ta tb ∧ self_check ta cal = true ∧ self_check tb cal = true ∧
      -20 < flight_exact ta.half ta.sample_rate tb.half tb.sample_rate ∧
      flight_exact ta.half ta.sample_rate tb.half tb.sample_rate < 60) ∧
    (pair ta tb → self_check ta cal = false →
      combine ta tb cal = .ok ⟨none, none, some .self_timestamp_mismatch, some .A⟩) ∧
    (pair ta tb → self_check ta cal = true → self_check tb cal = false →
      combine ta tb cal = .ok ⟨none, none, some .self_timestamp_mismatch, some .B⟩) := by
  have rate_of : ∀ t, passed p t → t.sample_rate ≠ 0 := by
    rintro t ⟨_, _, _, _, _, _, _, _, _, _, _, _, h⟩
    have := (check_transcript_ok_iff _ _ _ _ _ _ _ _ _ _ _ _ _ _).1 h
    omega
  have ra := rate_of ta hta
  have rb := rate_of tb htb
  refine ⟨combine_rejects_iff ta tb cal, ?_, ?_, ?_⟩
  · constructor
    · rintro ⟨o, ho, hv⟩
      by_cases hp : pair ta tb
      · by_cases hA : self_check ta cal = true
        · by_cases hB : self_check tb cal = true
          · rw [combine_measured hp hA hB ra rb] at ho
            cases ho
            refine ⟨hp, hA, hB, ?_⟩
            exact ((V2 _).2.2.1).1 (Prod.ext hv (by
              rcases (V2 (flight_exact ta.half ta.sample_rate tb.half tb.sample_rate)).2.2.2 with h | h | h <;>
                simp_all))
          · rw [combine_pair_steps cal hp] at ho
            have hA' : self_check ta cal ≠ false := by simpa using hA
            have hB' : self_check tb cal = false := by simpa using hB
            simp only [hA', hB', ite_false, ite_true] at ho
            cases ho
            simp at hv
        · rw [combine_pair_steps cal hp] at ho
          have hA' : self_check ta cal = false := by simpa using hA
          simp only [hA', ite_true] at ho
          cases ho
          simp at hv
      · have := (combine_rejects_iff ta tb cal).2 hp
        rw [this] at ho
        cases ho
    · rintro ⟨hp, hA, hB, h1, h2⟩
      refine ⟨_, combine_measured hp hA hB ra rb, ?_⟩
      have := ((V2 (flight_exact ta.half ta.sample_rate tb.half tb.sample_rate)).2.2.1).2 ⟨h1, h2⟩
      simp [this]
  · intro hp hA
    rw [combine_pair_steps cal hp]
    simp [hA, hp.1]
  · intro hp hA hB
    rw [combine_pair_steps cal hp]
    simp [hA, hB, hp.2.1]

/-- Why V1 needs the hypothesis on rates: a direct call with rate 0 and passing self checks raises
`ZeroDivisionError`, as `Fraction` does. The live flow can't reach this. -/
theorem combine_rate_zero {ta tb : Transcript B} {cal : Option (Role → Option ℤ)}
    (hp : pair ta tb) (hA : self_check ta cal = true) (hB : self_check tb cal = true)
    (h0 : ta.sample_rate = 0 ∨ tb.sample_rate = 0) :
    combine ta tb cal = .error .zero_division := by
  rw [combine_pair_steps cal hp]
  simp [hA, hB, h0]

/-- A server NEAR on wire-range numbers implies the circuit's range test. The rates come from
`check_transcript` having passed. The circuit has no self check, so the reverse is false, see
`V3_range_does_not_give_near`.

This links two checks on the same numbers. It does not show a phone told the truth about the air
(CN1). -/
theorem V3_near_gives_range {p : Prims B} {ta tb : Transcript B} (hta : passed p ta) (htb : passed p tb)
    (cal : Option (Role → Option ℤ))
    (hA1 : -2^31 ≤ ta.half) (hA2 : ta.half < 2^31) (hB1 : -2^31 ≤ tb.half) (hB2 : tb.half < 2^31)
    (hnear : ∃ o, combine ta tb cal = .ok o ∧ o.verdict = some .NEAR) :
    Popfv.fits 70 (34300 * ((ta.half : Popfv.F) * (tb.sample_rate : Popfv.F) -
        (tb.half : Popfv.F) * (ta.sample_rate : Popfv.F)) +
        40 * ((ta.sample_rate : Popfv.F) * (tb.sample_rate : Popfv.F)) - 1) ∧
    Popfv.fits 70 (120 * ((ta.sample_rate : Popfv.F) * (tb.sample_rate : Popfv.F)) -
        34300 * ((ta.half : Popfv.F) * (tb.sample_rate : Popfv.F) -
          (tb.half : Popfv.F) * (ta.sample_rate : Popfv.F)) - 1) := by
  have rates : ∀ t, passed p t → 36000 ≤ t.sample_rate ∧ t.sample_rate ≤ 96000 := by
    rintro t ⟨_, _, _, _, _, _, _, _, _, _, _, _, h⟩
    have := (check_transcript_ok_iff _ _ _ _ _ _ _ _ _ _ _ _ _ _).1 h
    omega
  obtain ⟨a1, a2⟩ := rates ta hta
  obtain ⟨b1, b2⟩ := rates tb htb
  obtain ⟨_, _, _, h1, h2⟩ := (V1 hta htb cal).2.1.1 hnear
  exact (V3_circuit _ _ _ _ hA1 hA2 hB1 hB2 a1 a2 b1 b2).1 ⟨h1, h2⟩

/-! ## V5: swapped pairs -/

/-- **V5, row 1.** `combine` with the two halves in the wrong order refuses with
`transcript_mismatch` (`verdict.py:155`). This is what stops 100 cm from turning into -100 cm.

It stops a mix-up of signed numbers. It does not show a phone told the truth about the air (CN1). -/
theorem V5_combine_swapped (ta tb : Transcript B) (cal : Option (Role → Option ℤ))
    (hA : ta.role = .A) (hB : tb.role = .B) :
    combine tb ta cal = .error (.reject .transcript_mismatch) := by
  simp [combine, hA, hB]

/-- **V5, row 2.** `verify_record` with the two transcripts swapped and the keys in place. A's slot
holds B's transcript. A's commit is fine, and the transcript version is the one A's commit says.
The result is `signature_invalid` (`verdict.py:116` or `:120`). No assumption on signatures is
needed: if the signature check somehow passes, line 120 fires instead, since B's transcript names
B's key.

It is about signed records. It does not show a phone told the truth about the air (CN1). -/
theorem V5_record_swapped (p : Prims B) (rec : ResultRecord B) (tr cm : SignedEntry B)
    (c : Commit B) (tB : Transcript B)
    (hT : rec.transcripts .A = some tr)
    (hC : rec.commits.bind (fun m => m .A) = some cm)
    (hc : check_commit p cm.raw cm.sig .A (rec.devices .A).pubkey rec.session_nonce rec.attempt = .ok c)
    (hd : p.decode_transcript tr.raw = some tB)
    (hk : tB.pk_self ≠ (rec.devices .A).pubkey)
    (hv : tB.version = c.version) :
    verify_record p rec = .error (.reject .signature_invalid) := by
  have : verify_one p rec .A .B = .error (.reject .signature_invalid) := by
    simp only [verify_one, hT, hC, hc, check_transcript, hd, version_of]
    by_cases hs : p.verify_raw (rec.devices .A).pubkey tr.raw tr.sig = false
    · simp [hs]
    · simp [hs, hv, hk]
  simp [verify_record, this]

/-- **V5, row 2 with mixed versions.** If the swapped transcript has another version than A's commit,
then the signature decides which reject comes first. Here, and only here, A4 is used by name: if
`Unforgeable` holds and A's key never signed these bytes, the result is `signature_invalid`.
Without A4 it could be `transcript_mismatch` (`verdict.py:118`). Refused either way.

It is about signed records. It does not show a phone told the truth about the air (CN1). -/
theorem V5_record_swapped_mixed_versions (p : Prims B) (signed : B → B → Prop)
    (A4 : Unforgeable p signed) (rec : ResultRecord B) (tr cm : SignedEntry B) (c : Commit B)
    (tB : Transcript B)
    (hT : rec.transcripts .A = some tr)
    (hC : rec.commits.bind (fun m => m .A) = some cm)
    (hc : check_commit p cm.raw cm.sig .A (rec.devices .A).pubkey rec.session_nonce rec.attempt = .ok c)
    (hd : p.decode_transcript tr.raw = some tB)
    (hns : ¬ signed (rec.devices .A).pubkey tr.raw) :
    verify_record p rec = .error (.reject .signature_invalid) := by
  have hs : p.verify_raw (rec.devices .A).pubkey tr.raw tr.sig = false := by
    by_contra h
    exact hns (A4 _ _ _ (by simpa using h))
  have : verify_one p rec .A .B = .error (.reject .signature_invalid) := by
    simp [verify_one, hT, hC, hc, check_transcript, hd, hs]
  simp [verify_record, this]

/-- **V5, row 3.** `verify_record` with transcripts, commits and keys all swapped. Every signature
checks, but A's slot holds a commit that says role B. The result is `transcript_mismatch`, from
`check_commit` (`verdict.py:97`).

It is about signed records. It does not show a phone told the truth about the air (CN1). -/
theorem V5_record_all_swapped (p : Prims B) (rec : ResultRecord B) (tr cm : SignedEntry B)
    (c : Commit B)
    (hT : rec.transcripts .A = some tr)
    (hC : rec.commits.bind (fun m => m .A) = some cm)
    (hd : p.decode_commit cm.raw = some c)
    (hs : p.verify_raw (rec.devices .A).pubkey cm.raw cm.sig = true)
    (hr : c.role = .B) :
    verify_record p rec = .error (.reject .transcript_mismatch) := by
  have : verify_one p rec .A .B = .error (.reject .transcript_mismatch) := by
    simp [verify_one, hT, hC, check_commit, hd, hs, hr]
  simp [verify_record, this]

/-- **V5, row 4.** Live: a phone signs a transcript that names the other role. All earlier checks
pass, and `check_transcript` gives `transcript_mismatch` (`verdict.py:122`). That this ends the session is
`sessions.py:441-443`, which is not in this file.

It is about signed records. It does not show a phone told the truth about the air (CN1). -/
theorem V5_live_other_role (p : Prims B) (raw sig : B) (role : Role) (pk_self pk_partner nonce : B)
    (attempt : ℕ) (commit_sha256 rec : Option B) (sample_rate : Option ℕ) (version : ℕ)
    (code_commit : Option B) (t : Transcript B)
    (hd : p.decode_transcript raw = some t)
    (hs : p.verify_raw pk_self raw sig = true)
    (hv : t.version = version) (hk : t.pk_self = pk_self) (hr : t.role ≠ role) :
    check_transcript p raw sig role pk_self pk_partner nonce attempt commit_sha256 rec sample_rate
      version code_commit = .error (.reject .transcript_mismatch) := by
  simp [check_transcript, hd, hs, version_of, hv, hk, hr]

/-! ## V6: what `check_transcript` pins -/

/-- **V6 (rule C17).** If `check_transcript` returns `t`, then: the bytes decode to `t`, the signature
checks under the sender's key, and the version, sender key, role, nonce, attempt and partner key are
the expected ones. The rate is in 36000..96000, and equals the armed rate if one was given. The commit
hash and rec were given and match. In version 2, `delta` is right, and `code_commit` matches if given.

Note what is **not** in this list: `half` and `self_os_delta`. The sender picks those freely
(`V6_free`). So this does not show a phone told the truth about the air (CN1). -/
theorem V6 {p : Prims B} {raw sig : B} {role : Role} {pk_self pk_partner nonce : B}
    {attempt : ℕ} {commit_sha256 rec : Option B} {sample_rate : Option ℕ} {version : ℕ}
    {code_commit : Option B} {t : Transcript B}
    (h : check_transcript p raw sig role pk_self pk_partner nonce attempt commit_sha256 rec sample_rate
      version code_commit = .ok t) :
    p.decode_transcript raw = some t ∧
    p.verify_raw pk_self raw sig = true ∧
    version_of t = version ∧
    t.pk_self = pk_self ∧ t.role = role ∧ t.nonce = nonce ∧ t.attempt = attempt ∧
    t.pk_partner = pk_partner ∧
    36000 ≤ t.sample_rate ∧ t.sample_rate ≤ 96000 ∧
    (∀ s, sample_rate = some s → t.sample_rate = s) ∧
    commit_sha256 = some t.commit_hash ∧
    rec = some t.rec_ ∧
    (version = 2 → t.delta = some (popt2_delta t.sample_rate)) ∧
    (version = 2 → ∀ cc, code_commit = some cc → t.code_commit = some cc) := by
  obtain ⟨h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14⟩ :=
    (check_transcript_ok_iff _ _ _ _ _ _ _ _ _ _ _ _ _ _).1 h
  refine ⟨h1, h2, h3, h4, h5, h6, h7, h8, h10, h11, ?_, h12, h13, ?_, ?_⟩
  · rintro s rfl
    simpa using h9 (by simp)
  · exact fun v => (h14 v).1
  · rintro v cc rfl
    exact (h14 v).2 (by simp)

/-- **V6, the free fields.** If a transcript passes, any other transcript that differs only in `half`,
`self_os_delta`, the three clock fields, `a_self` or `p_partner` passes too, when its bytes decode
and its signature checks. So nothing here reads those numbers against anything. On purpose for `half`
and `self_os_delta`, and it is what CN1 is about. It does not show a phone told the truth about the air (CN1). -/
theorem V6_free {p p' : Prims B} {raw raw' sig sig' : B} {role : Role} {pk_self pk_partner nonce : B}
    {attempt : ℕ} {commit_sha256 rec : Option B} {sample_rate : Option ℕ} {version : ℕ}
    {code_commit : Option B} {t : Transcript B}
    (h : check_transcript p raw sig role pk_self pk_partner nonce attempt commit_sha256 rec sample_rate
      version code_commit = .ok t)
    (half' delta' : ℤ) (f1 f2 f3 : ℕ) (a' q' : Option ℕ)
    (hd : p'.decode_transcript raw' = some { t with
        half := half', self_os_delta := delta', play_frame_position := f1, play_nano_time := f2,
        rec_frame0_nano_time := f3, a_self := a', p_partner := q' })
    (hs : p'.verify_raw pk_self raw' sig' = true) :
    check_transcript p' raw' sig' role pk_self pk_partner nonce attempt commit_sha256 rec sample_rate
      version code_commit = .ok { t with
        half := half', self_os_delta := delta', play_frame_position := f1, play_nano_time := f2,
        rec_frame0_nano_time := f3, a_self := a', p_partner := q' } := by
  obtain ⟨_, _, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14⟩ :=
    (check_transcript_ok_iff _ _ _ _ _ _ _ _ _ _ _ _ _ _).1 h
  exact (check_transcript_ok_iff _ _ _ _ _ _ _ _ _ _ _ _ _ _).2
    ⟨hd, hs, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14⟩

/-! ## X1: the hole (rule CN1) -/

/-- What one signer picks. Nothing here is audio. `rec_` is any value at all, and the bytes and
signatures are whatever the signer writes. `code_commit` is copied from the server's reply in v2. -/
structure Side (B : Type) where
  pk_self : B
  pk_partner : B
  sample_rate : ℕ
  half : ℤ
  self_os_delta : ℤ
  rec_ : B
  version : ℕ
  code_commit : Option B
  commit_raw : B
  commit_sig : B
  raw : B
  sig : B

/-- The commit this signer writes. -/
def Side.commit (s : Side B) (role : Role) (attempt : ℕ) (nonce : B) : Commit B :=
  { role, attempt, nonce, rec_ := s.rec_, version := s.version }

/-- The transcript this signer writes. All the clock fields are 0, which no check reads. -/
def Side.transcript (sha256 : B → B) (s : Side B) (role : Role) (attempt : ℕ) (nonce : B) :
    Transcript B :=
  { role, attempt, nonce, pk_self := s.pk_self, pk_partner := s.pk_partner,
    sample_rate := s.sample_rate, half := s.half, rec_ := s.rec_,
    play_frame_position := 0, play_nano_time := 0, rec_frame0_nano_time := 0,
    self_os_delta := s.self_os_delta, commit_hash := sha256 s.commit_raw, version := s.version,
    a_self := if s.version = 2 then some 0 else none,
    p_partner := if s.version = 2 then some 0 else none,
    delta := if s.version = 2 then some (popt2_delta s.sample_rate) else none,
    code_commit := if s.version = 2 then s.code_commit else none }

/-- A signer is ready when its bytes decode to what it picked and its signatures check. This is all
that "holding the enrolled key" and "the codec works" are used for. -/
def Side.Ready (p : Prims B) (s : Side B) (role : Role) (attempt : ℕ) (nonce : B) : Prop :=
  p.decode_commit s.commit_raw = some (s.commit role attempt nonce) ∧
  p.verify_raw s.pk_self s.commit_raw s.commit_sig = true ∧
  p.decode_transcript s.raw = some (s.transcript p.sha256 role attempt nonce) ∧
  p.verify_raw s.pk_self s.raw s.sig = true

/-- The record two signers would get from such a run. -/
def x1Record (sA sB : Side B) (nonce : B) (attempt : ℕ) (calA calB : ℤ) : ResultRecord B :=
  { session_nonce := nonce, attempt,
    devices := fun r => match r with
      | .A => ⟨sA.pk_self, some calA⟩
      | .B => ⟨sB.pk_self, some calB⟩,
    transcripts := fun r => match r with
      | .A => some ⟨sA.raw, sA.sig⟩
      | .B => some ⟨sB.raw, sB.sig⟩,
    commits := some fun r => match r with
      | .A => some ⟨sA.commit_raw, sA.commit_sig⟩
      | .B => some ⟨sB.commit_raw, sB.commit_sig⟩ }

/-- The checks of `verdict.py` all come out in favour, and the verdict is NEAR at the chosen flight.
The live path doesn't call `check_commit`, see `X1`. -/
def X1Outcome (p : Prims B) (sA sB : Side B) (nonce : B) (attempt : ℕ) (calA calB : ℤ) : Prop :=
  check_commit p sA.commit_raw sA.commit_sig .A sA.pk_self nonce attempt
      = .ok (sA.commit .A attempt nonce) ∧
  check_commit p sB.commit_raw sB.commit_sig .B sB.pk_self nonce attempt
      = .ok (sB.commit .B attempt nonce) ∧
  check_transcript p sA.raw sA.sig .A sA.pk_self sB.pk_self nonce attempt
      (some (p.sha256 sA.commit_raw)) (some sA.rec_) (some sA.sample_rate) sA.version sA.code_commit
      = .ok (sA.transcript p.sha256 .A attempt nonce) ∧
  check_transcript p sB.raw sB.sig .B sB.pk_self sA.pk_self nonce attempt
      (some (p.sha256 sB.commit_raw)) (some sB.rec_) (some sB.sample_rate) sB.version sB.code_commit
      = .ok (sB.transcript p.sha256 .B attempt nonce) ∧
  combine (sA.transcript p.sha256 .A attempt nonce) (sB.transcript p.sha256 .B attempt nonce)
      (some fun r => match r with | .A => some calA | .B => some calB)
      = .ok ⟨some (flight_exact sA.half sA.sample_rate sB.half sB.sample_rate), some .NEAR, none, none⟩ ∧
  verify_record p (x1Record sA sB nonce attempt calA calB)
      = .ok ⟨some (flight_exact sA.half sA.sample_rate sB.half sB.sample_rate), some .NEAR, none, none⟩

omit [DecidableEq B] in
private theorem delta_ok (s : Side B) (sha : B → B) (r : Role) (k : ℕ) (n : B) (h : s.version = 2) :
    (s.transcript sha r k n).delta = some (popt2_delta s.sample_rate) := by
  simp [Side.transcript, h]

/-- **X1 with the bytes in hand (rule CN1).** Take two sides that are `Ready` (bytes decode to their
fields, signatures check), with crossed partner keys, distinct keys, rates in 36000..96000, self
deltas that pass `self_os_ok`, and an exact flight strictly between -20 and 60. Then every check
passes and the verdict is NEAR. Nothing in the hypotheses or in the functions is about sound. See `X1`
for the plain reading.

It does not show a phone told the truth about the air (CN1). It shows the verdict can't know. -/
theorem X1_core (p : Prims B) (sA sB : Side B) (nonce : B) (attempt : ℕ) (calA calB : ℤ)
    (hRA : sA.Ready p .A attempt nonce) (hRB : sB.Ready p .B attempt nonce)
    (hpA : sA.pk_partner = sB.pk_self) (hpB : sB.pk_partner = sA.pk_self)
    (hne : sA.pk_self ≠ sB.pk_self)
    (ha1 : 36000 ≤ sA.sample_rate) (ha2 : sA.sample_rate ≤ 96000)
    (hb1 : 36000 ≤ sB.sample_rate) (hb2 : sB.sample_rate ≤ 96000)
    (hdA : self_os_ok sA.self_os_delta sA.sample_rate (if sA.version = 2 then 0 else calA) = true)
    (hdB : self_os_ok sB.self_os_delta sB.sample_rate (if sB.version = 2 then 0 else calB) = true)
    (hf1 : -20 < flight_exact sA.half sA.sample_rate sB.half sB.sample_rate)
    (hf2 : flight_exact sA.half sA.sample_rate sB.half sB.sample_rate < 60) :
    X1Outcome p sA sB nonce attempt calA calB := by
  obtain ⟨dcA, scA, dtA, stA⟩ := hRA
  obtain ⟨dcB, scB, dtB, stB⟩ := hRB
  set ta := sA.transcript p.sha256 .A attempt nonce with hta
  set tb := sB.transcript p.sha256 .B attempt nonce with htb
  have ccA : check_commit p sA.commit_raw sA.commit_sig .A sA.pk_self nonce attempt
      = .ok (sA.commit .A attempt nonce) :=
    (check_commit_ok_iff _ _ _ _ _ _ _ _).2 ⟨dcA, scA, rfl, rfl, rfl⟩
  have ccB : check_commit p sB.commit_raw sB.commit_sig .B sB.pk_self nonce attempt
      = .ok (sB.commit .B attempt nonce) :=
    (check_commit_ok_iff _ _ _ _ _ _ _ _).2 ⟨dcB, scB, rfl, rfl, rfl⟩
  have ctA : ∀ sr cc, (sr = some sA.sample_rate ∨ sr = none) → (cc = sA.code_commit ∨ cc = none) →
      check_transcript p sA.raw sA.sig .A sA.pk_self sB.pk_self nonce attempt
        (some (p.sha256 sA.commit_raw)) (some sA.rec_) sr sA.version cc = .ok ta := by
    intro sr cc hsr hcc
    refine (check_transcript_ok_iff _ _ _ _ _ _ _ _ _ _ _ _ _ _).2
      ⟨dtA, stA, rfl, rfl, rfl, rfl, rfl, hpA, ?_, ha1, ha2, rfl, rfl, ?_⟩
    · rcases hsr with rfl | rfl <;> simp [hta, Side.transcript]
    · intro hv
      refine ⟨delta_ok _ _ _ _ _ hv, ?_⟩
      rcases hcc with rfl | rfl <;> simp [hta, Side.transcript, hv]
  have ctB : ∀ sr cc, (sr = some sB.sample_rate ∨ sr = none) → (cc = sB.code_commit ∨ cc = none) →
      check_transcript p sB.raw sB.sig .B sB.pk_self sA.pk_self nonce attempt
        (some (p.sha256 sB.commit_raw)) (some sB.rec_) sr sB.version cc = .ok tb := by
    intro sr cc hsr hcc
    refine (check_transcript_ok_iff _ _ _ _ _ _ _ _ _ _ _ _ _ _).2
      ⟨dtB, stB, rfl, rfl, rfl, rfl, rfl, hpB, ?_, hb1, hb2, rfl, rfl, ?_⟩
    · rcases hsr with rfl | rfl <;> simp [htb, Side.transcript]
    · intro hv
      refine ⟨delta_ok _ _ _ _ _ hv, ?_⟩
      rcases hcc with rfl | rfl <;> simp [htb, Side.transcript, hv]
  have hpair : pair ta tb := ⟨rfl, rfl, rfl, rfl, hpA, hpB, hne⟩
  have hnear := ((V2 (flight_exact sA.half sA.sample_rate sB.half sB.sample_rate)).2.2.1).2 ⟨hf1, hf2⟩
  have result : ∀ cal : Option (Role → Option ℤ),
      self_check ta cal = true → self_check tb cal = true →
      combine ta tb cal
        = .ok ⟨some (flight_exact sA.half sA.sample_rate sB.half sB.sample_rate), some .NEAR, none, none⟩ := by
    intro cal h1 h2
    rw [combine_measured hpair h1 h2 (by simp [hta, Side.transcript]; omega)
      (by simp [htb, Side.transcript]; omega)]
    simp [hta, htb, Side.transcript, hnear]
  refine ⟨ccA, ccB, ctA _ _ (Or.inl rfl) (Or.inl rfl), ctB _ _ (Or.inl rfl) (Or.inl rfl), ?_, ?_⟩
  · apply result
    · simpa [self_check, cal_for, version_of, hta, Side.transcript] using hdA
    · simpa [self_check, cal_for, version_of, htb, Side.transcript] using hdB
  · have oneA : verify_one p (x1Record sA sB nonce attempt calA calB) .A .B = .ok ta := by
      simp only [verify_one, x1Record, Option.bind_some, ccA]
      exact ctA _ _ (Or.inr rfl) (Or.inr rfl)
    have oneB : verify_one p (x1Record sA sB nonce attempt calA calB) .B .A = .ok tb := by
      simp only [verify_one, x1Record, Option.bind_some, ccB]
      exact ctB _ _ (Or.inr rfl) (Or.inr rfl)
    simp only [verify_record, oneA, oneB]
    apply result
    · simpa [self_check, cal_for, version_of, hta, Side.transcript, x1Record] using hdA
    · simpa [self_check, cal_for, version_of, htb, Side.transcript, x1Record] using hdB

/-- The wire ranges and widths of a commit: `codec.py:26` and the v2 root check. -/
def Commit.wire_ok (p : Prims B) (c : Commit B) : Prop :=
  (c.version = 1 ∨ c.version = 2) ∧ c.attempt < 2^8 ∧ p.width c.nonce = 32 ∧ p.width c.rec_ = 32 ∧
  (c.version = 2 → p.rec_root_ok c.rec_ = true)

/-- The wire ranges and widths of a transcript: `codec.py:29`, `:30`, and the v2 root check. -/
def Transcript.wire_ok (p : Prims B) (t : Transcript B) : Prop :=
  (t.version = 1 ∨ t.version = 2) ∧ t.attempt < 2^8 ∧ p.width t.nonce = 32 ∧
  p.width t.pk_self = 65 ∧ p.width t.pk_partner = 65 ∧ p.width t.rec_ = 32 ∧
  p.width t.commit_hash = 32 ∧ t.sample_rate < 2^32 ∧
  -2^31 ≤ t.half ∧ t.half < 2^31 ∧ -2^31 ≤ t.self_os_delta ∧ t.self_os_delta < 2^31 ∧
  t.play_frame_position < 2^64 ∧ t.play_nano_time < 2^64 ∧ t.rec_frame0_nano_time < 2^64 ∧
  (t.version = 1 → t.a_self = none ∧ t.p_partner = none ∧ t.delta = none ∧ t.code_commit = none) ∧
  (t.version = 2 → p.rec_root_ok t.rec_ = true ∧ (∃ x, t.a_self = some x ∧ x < 2^32) ∧
    (∃ x, t.p_partner = some x ∧ x < 2^32) ∧ (∃ x, t.delta = some x ∧ x < 2^16) ∧
    (∃ x, t.code_commit = some x ∧ p.width x = 32))

/-- What two signers can do, named. Any value in the wire ranges and widths can be written as bytes,
and the holder of each key can sign any bytes. A hypothesis. It is not proved of `codec.py`, since
byte parsing is out of scope. By reading, `codec.py` round trips these values, and `spec-recheck.txt`
has the X1 run on the real code. `Powers_satisfiable` shows it holds on a Lean copy of the layout. -/
structure Powers (p : Prims B) (pkA pkB : B) : Prop where
  write_commit : ∀ c : Commit B, c.wire_ok p → ∃ raw, p.decode_commit raw = some c
  write_transcript : ∀ t : Transcript B, t.wire_ok p → ∃ raw, p.decode_transcript raw = some t
  sign : ∀ pk, (pk = pkA ∨ pk = pkB) → ∀ m, ∃ s, p.verify_raw pk m s = true

/-- **X1 (rule CN1). The hole.** Pick any two halves in the signed 32-bit range and any two rates in
36000..96000 whose exact flight lies strictly between -20 and 60. Pick any 32-byte recording values,
with no recording behind them (for v2 they must be below the field size, `hrA`, `hrB`). Pick self
deltas that pass. A phone can always find one when its calibration is in 0..150000
(`self_os_can_pass`). This theorem takes the deltas as given and works for any calibration, as long as
they pass. Two signers holding their enrolled keys can then write transcripts that pass every check, and the verdict is NEAR. No part of this reads
sound.

**What the statement pins.** Its conclusion names the halves, rates, recording values and versions. It does not name the keys, self deltas or `code_commit`, so read the sentence above as what the proof builds, not what the statement says.

**So the verdict can't tell distance by itself.** It shows that a NEAR is about signed numbers. It
does not show a phone told the truth about the air, and no check in this file reads the air.

**What this covers, exactly.** `X1Outcome` calls `verify_record` as written. It calls `check_transcript`
and `combine` with arguments of the shape the live path passes (`sessions.py:436-440`, `:454-456`).
`X1Outcome` passes each side's own `code_commit`. `X1`'s conclusion does not tie that to `ccA`,
`ccB`: the proof builds the sides with them, but the statement forces neither the live v1 value
(`None`) nor the server's v2 value (`sessions.py:440`). `X1_keys` pins `code_commit = ccA`, `ccB`.
It also calls
`check_commit`, which `sessions.py` never calls. The live path has its own copy of those checks
(`sessions.py:279-290`), with an armed version check and a `too_early` gate. The session walk to
`result.verdict = NEAR` is not proved here.

Hypotheses by name: `Powers` is what the signers can do. `hsha` says the hash gives 32 bytes, kept out
of `Powers` so that `Powers` stays about the codec and the signers. The widths of the keys, nonce and
recording values are `hwA` .. `hwrB`. `X1_on_layout` runs all of these at once. Not assumed: anything
about signatures being forgeable or not. -/
theorem X1 (p : Prims B) (pkA pkB nonce recA recB : B) (ccA ccB : Option B) (verA verB attempt : ℕ)
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
      X1Outcome p sA sB nonce attempt calA calB := by
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
  have wire : ∀ (s : Side B) (r : Role), (s.version = 1 ∨ s.version = 2) →
      (s.version = 2 → p.rec_root_ok s.rec_ = true ∧ ∃ x, s.code_commit = some x ∧ p.width x = 32) →
      p.width s.pk_self = 65 → p.width s.pk_partner = 65 → p.width s.rec_ = 32 →
      s.sample_rate ≤ 96000 → -2^31 ≤ s.half → s.half < 2^31 → -2^31 ≤ s.self_os_delta →
      s.self_os_delta < 2^31 → (s.transcript p.sha256 r attempt nonce).wire_ok p := by
    intro s r hv hroot wps wpp wr hsr h1 h2 h3 h4
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
      refine ⟨r1, ⟨0, rfl, by norm_num⟩, ⟨0, rfl, by norm_num⟩, ⟨_, rfl, hd⟩, r2⟩
  let sA0 : Side B := ⟨pkA, pkB, srA, hA, dA, recA, verA, ccA, craA, csA, craA, csA⟩
  let sB0 : Side B := ⟨pkB, pkA, srB, hB, dB, recB, verB, ccB, craB, csB, craB, csB⟩
  obtain ⟨tA, htA⟩ := hpow.write_transcript _
    (wire sA0 .A hvA hrA hwA hwB hwrA ha2 hA1 hA2 hdA1 hdA2)
  obtain ⟨tB, htB⟩ := hpow.write_transcript _
    (wire sB0 .B hvB hrB hwB hwA hwrB hb2 hB1 hB2 hdB1 hdB2)
  obtain ⟨sgA, hsgA⟩ := hpow.sign pkA (Or.inl rfl) tA
  obtain ⟨sgB, hsgB⟩ := hpow.sign pkB (Or.inr rfl) tB
  let sA : Side B := ⟨pkA, pkB, srA, hA, dA, recA, verA, ccA, craA, csA, tA, sgA⟩
  let sB : Side B := ⟨pkB, pkA, srB, hB, dB, recB, verB, ccB, craB, csB, tB, sgB⟩
  refine ⟨sA, sB, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, ?_⟩
  exact X1_core p sA sB nonce attempt calA calB
    ⟨hcraA, hcsA, htA, hsgA⟩ ⟨hcraB, hcsB, htB, hsgB⟩ rfl rfl hne
    ha1 ha2 hb1 hb2 hdA hdB hf1 hf2

/-! ### X1, a concrete witness

Plain numbers stand for byte strings. The decoders are a small table. The two signers each sign two
messages and nothing else, and the toy signature check accepts only those. So this run has no
forgery in it (`toy_unforgeable`). All the hypotheses of `X1_core` hold, and the result runs. -/

/-- Toy sides: A's half is 100 at rate 48000, B's is 0 at rate 48000. `spec-recheck.txt` has this run
on the real code, flight 35.73 cm (lines `X1`). `ver` is the transcript version. -/
def toyA (ver : ℕ) : Side ℕ :=
  ⟨1, 2, 48000, 100, 0, 77, ver, if ver = 2 then some 55 else none, 10, 100, 11, 101⟩

/-- Toy side B, see `toyA`. Its recording hash is a value with no recording behind it. -/
def toyB (ver : ℕ) : Side ℕ :=
  ⟨2, 1, 48000, 0, 0, 88, ver, if ver = 2 then some 55 else none, 20, 200, 21, 201⟩

/-- Toy hash. -/
def toySha (m : ℕ) : ℕ := m + 1000

/-- The toy nonce. -/
def toyNonce : ℕ := 9

/-- The toy prims. Accepts the four signed messages and nothing else. The toy numbers have no width,
and the witnesses here go through `X1_core`, which never reads one, so `width` is a dummy. -/
def toyPrims (ver : ℕ) : Prims ℕ where
  width _ := 0
  verify_raw pk m s := [(1, 10, 100), (1, 11, 101), (2, 20, 200), (2, 21, 201)].contains (pk, m, s)
  sha256 := toySha
  rec_root_ok _ := true
  decode_commit raw :=
    if raw = 10 then some ((toyA ver).commit .A 0 toyNonce)
    else if raw = 20 then some ((toyB ver).commit .B 0 toyNonce)
    else none
  decode_transcript raw :=
    if raw = 11 then some ((toyA ver).transcript toySha .A 0 toyNonce)
    else if raw = 21 then some ((toyB ver).transcript toySha .B 0 toyNonce)
    else none

/-- The flight in the toy run: 1715/48, about 35.73 cm. -/
theorem toy_flight : flight_exact 100 48000 0 48000 = 1715 / 48 := by
  norm_num [flight_exact]

/-- The toy check accepts only what the two keys signed, so `Unforgeable` holds in the toy run. -/
theorem toy_unforgeable (ver : ℕ) :
    Unforgeable (toyPrims ver)
      (fun pk m => (pk, m) = (1, 10) ∨ (pk, m) = (1, 11) ∨ (pk, m) = (2, 20) ∨ (pk, m) = (2, 21)) := by
  intro pk m s h
  simp only [toyPrims, List.contains_eq_mem, List.mem_cons, List.not_mem_nil, or_false,
    decide_eq_true_eq, Prod.mk.injEq] at h
  simp only [Prod.mk.injEq]
  omega

/-- Only versions 1 and 2 are stated, as the Python can't go past `REC_KEY[version]` with others. -/
private theorem toy_run (ver : ℕ) (hv : ver = 1 ∨ ver = 2) :
    X1Outcome (toyPrims ver) (toyA ver) (toyB ver) toyNonce 0 0 0 := by
  have hself : self_os_ok 0 48000 0 = true := by norm_num [self_os_ok]
  have hflight : flight_exact (toyA ver).half (toyA ver).sample_rate (toyB ver).half (toyB ver).sample_rate
      = 1715 / 48 := toy_flight
  apply X1_core
  · exact ⟨by simp [toyPrims, toyA], by simp [toyPrims, toyA], by simp [toyPrims, toyA],
      by simp [toyPrims, toyA]⟩
  · exact ⟨by simp [toyPrims, toyB], by simp [toyPrims, toyB], by simp [toyPrims, toyB],
      by simp [toyPrims, toyB]⟩
  · rfl
  · rfl
  · simp [toyA, toyB]
  · simp [toyA]
  · simp [toyA]
  · simp [toyB]
  · simp [toyB]
  · show self_os_ok 0 48000 (if ver = 2 then 0 else 0) = true
    split_ifs <;> exact hself
  · show self_os_ok 0 48000 (if ver = 2 then 0 else 0) = true
    split_ifs <;> exact hself
  · rw [hflight]; norm_num
  · rw [hflight]; norm_num

/-- **X1, concrete witness, v1.** Numbers picked by hand, no audio anywhere, no forged signature.
Every check passes and the verdict is NEAR, at flight 1715/48, about 35.73 cm.

It does not show a phone told the truth about the air (CN1). It shows the verdict can't know. -/
theorem X1_witness_v1 : X1Outcome (toyPrims 1) (toyA 1) (toyB 1) toyNonce 0 0 0 :=
  toy_run 1 (Or.inl rfl)

/-- **X1, concrete witness, v2.** The same, with version 2 transcripts. `delta` and `code_commit` are
copied as the server would give them.

It does not show a phone told the truth about the air (CN1). It shows the verdict can't know. -/
theorem X1_witness_v2 : X1Outcome (toyPrims 2) (toyA 2) (toyB 2) toyNonce 0 0 0 :=
  toy_run 2 (Or.inr rfl)

/-! ### `Powers` can hold, on a decoder that holds widths fixed

This is a small Lean copy of the byte layout in `codec.py:26`, `:29`, `:30`. Same field order, same
widths, same big-endian numbers, same checks as `decode_commit` and `decode_transcript`. It exists
for one job: to show `Powers` can be true of a decoder that really holds field widths fixed.
The encoders match `codec.py` only on values that pass `wire_ok`, and `Powers` only needs them there.
On other values they differ, at least in these ways:
* A byte field is appended as given. Python's `struct` cuts or pads it to its width.
* An int that doesn't fit is silently cut by `be`. Attempt 300 gives byte 0x2c. Python raises
  `struct.error`.
* A bad version is encoded. Python raises `ValueError`.
* A v2 transcript with a missing tail field gets an empty tail, 269 bytes. Python raises `KeyError`.
* A v1 transcript that carries all the tail fields gets the tail too. Python leaves them out.

It is not `codec.py`. Nothing here is proved about the Python. A run compares the bytes on four
samples only (`spec-checks/layout_vectors.py`, run by `run_all.sh`). The signature check and the hash here are stand-ins with no
security at all. -/

namespace Layout

/-- One byte. -/
abbrev Byte := Fin 256

/-- A byte string. Its width is its length, as Python's `len`. -/
abbrev Bytes := List Byte

/-- A number as `k` big-endian bytes, as `struct` packs an unsigned field. -/
def be : ℕ → ℕ → Bytes
  | 0, _ => []
  | k + 1, n => be k (n / 256) ++ [⟨n % 256, Nat.mod_lt _ (by norm_num)⟩]

/-- Big-endian bytes back to a number. -/
def unbe (l : Bytes) : ℕ := l.foldl (fun a b => a * 256 + b.val) 0

theorem be_length (k n : ℕ) : (be k n).length = k := by
  induction k generalizing n with
  | zero => rfl
  | succ k ih => simp [be, ih]

theorem unbe_snoc (l : Bytes) (b : Byte) : unbe (l ++ [b]) = unbe l * 256 + b.val := by
  simp [unbe, List.foldl_append]

theorem unbe_be (k n : ℕ) (h : n < 256 ^ k) : unbe (be k n) = n := by
  induction k generalizing n with
  | zero => simp at h; subst h; rfl
  | succ k ih =>
    have hk : n / 256 < 256 ^ k := by
      apply Nat.div_lt_of_lt_mul
      rw [pow_succ] at h
      omega
    rw [be, unbe_snoc, ih _ hk]
    simp only
    omega

theorem unbe_lt (l : Bytes) : unbe l < 256 ^ l.length := by
  induction l using List.reverseRecOn with
  | nil => simp [unbe]
  | append_singleton l b ih =>
    rw [unbe_snoc, List.length_append, List.length_singleton, pow_succ]
    have := b.isLt
    omega

/-- A signed 32-bit number as its unsigned form (two's complement), as `struct` packs `i`. -/
def i32Enc (x : ℤ) : ℕ := (if x < 0 then x + 4294967296 else x).toNat

/-- The unsigned form back to a signed 32-bit number. -/
def i32Dec (u : ℕ) : ℤ := if u < 2147483648 then (u : ℤ) else (u : ℤ) - 4294967296

theorem i32_round {x : ℤ} (h1 : -2^31 ≤ x) (h2 : x < 2^31) :
    i32Dec (i32Enc x) = x ∧ i32Enc x < 256 ^ 4 := by
  norm_num at h1 h2 ⊢
  unfold i32Dec i32Enc
  split_ifs <;> omega

theorem i32Dec_range {u : ℕ} (h : u < 256 ^ 4) : -2^31 ≤ i32Dec u ∧ i32Dec u < 2^31 := by
  norm_num at h ⊢
  unfold i32Dec
  split_ifs <;> omega

/-- Take `n` bytes off the front. `none` if there are too few. -/
def peel (n : ℕ) (s : Bytes) : Option (Bytes × Bytes) :=
  if n ≤ s.length then some (s.take n, s.drop n) else none

theorem peel_append {a : Bytes} {n : ℕ} (h : a.length = n) (b : Bytes) :
    peel n (a ++ b) = some (a, b) := by
  subst h; simp [peel]

theorem peel_len {n : ℕ} {s : Bytes} {p : Bytes × Bytes} (h : peel n s = some p) :
    p.1.length = n := by
  unfold peel at h
  split_ifs at h with hn
  simp only [Option.some.injEq] at h
  subst h
  simp [hn]

/-- `POPC`, `codec.py:23`. -/
def magicC : Bytes := [80, 79, 80, 67]

/-- `POPT`, `codec.py:27`. -/
def magicT : Bytes := [80, 79, 80, 84]

/-- The role byte. -/
def roleCell : Role → Bytes
  | .A => [65]
  | .B => [66]

/-- `codec.py:61`, `:91`: only the bytes `A` and `B` are roles. -/
def roleOf (c : Bytes) : Option Role :=
  if c = [65] then some .A else if c = [66] then some .B else none

theorem roleOf_cell (r : Role) : roleOf (roleCell r) = some r := by
  cases r <;> simp [roleOf, roleCell]

theorem roleCell_length (r : Role) : (roleCell r).length = 1 := by
  cases r <;> rfl

/-- BN254 `r`, `poseidon2.py:10`. -/
def R : ℕ := 21888242871839275222246405745257275088548364400416034343698204186575808495617

/-- `_root_ok`, `codec.py:43-45`. -/
def rootOk (r : Bytes) : Bool := Decidable.decide (unbe r < R)

/-- The cells of a commit, widths from `codec.py:26`. -/
structure CommitCells where
  magic : Bytes
  ver : Bytes
  role : Bytes
  attempt : Bytes
  nonce : Bytes
  rec_ : Bytes

/-- Cut a commit into its cells. Fails if the bytes run out or some are left over. -/
def parseCommit (raw : Bytes) : Option CommitCells :=
  (peel 4 raw).bind fun p1 => (peel 1 p1.2).bind fun p2 => (peel 1 p2.2).bind fun p3 =>
  (peel 1 p3.2).bind fun p4 => (peel 32 p4.2).bind fun p5 => (peel 32 p5.2).bind fun p6 =>
    if p6.2 = [] then some ⟨p1.1, p2.1, p3.1, p4.1, p5.1, p6.1⟩ else none

/-- `decode_commit`, `codec.py:54-67`. -/
def decodeCommit (raw : Bytes) : Option (Commit Bytes) :=
  if raw.length ≠ 71 then none else
  (parseCommit raw).bind fun f =>
    if f.magic ≠ magicC then none else
    if unbe f.ver ≠ 1 ∧ unbe f.ver ≠ 2 then none else
    (roleOf f.role).bind fun ro =>
      if unbe f.ver = 2 ∧ rootOk f.rec_ = false then none else
      some { role := ro, attempt := unbe f.attempt, nonce := f.nonce, rec_ := f.rec_,
             version := unbe f.ver }

/-- `encode_commit`, `codec.py:48-51`. -/
def encodeCommit (c : Commit Bytes) : Bytes :=
  magicC ++ (be 1 c.version ++ (roleCell c.role ++ (be 1 c.attempt ++ (c.nonce ++ (c.rec_ ++ [])))))

/-- The cells of the part of a transcript that v1 and v2 share, widths from `codec.py:29`. -/
structure TxCells where
  magic : Bytes
  ver : Bytes
  role : Bytes
  attempt : Bytes
  nonce : Bytes
  pk_self : Bytes
  pk_partner : Bytes
  sample_rate : Bytes
  half : Bytes
  rec_ : Bytes
  play_frame_position : Bytes
  play_nano_time : Bytes
  rec_frame0_nano_time : Bytes
  self_os_delta : Bytes
  commit_hash : Bytes

/-- The 269 byte head of a transcript, and whatever comes after it. -/
def parseTx (raw : Bytes) : Option (TxCells × Bytes) :=
  (peel 4 raw).bind fun p1 => (peel 1 p1.2).bind fun p2 => (peel 1 p2.2).bind fun p3 =>
  (peel 1 p3.2).bind fun p4 => (peel 32 p4.2).bind fun p5 => (peel 65 p5.2).bind fun p6 =>
  (peel 65 p6.2).bind fun p7 => (peel 4 p7.2).bind fun p8 => (peel 4 p8.2).bind fun p9 =>
  (peel 32 p9.2).bind fun p10 => (peel 8 p10.2).bind fun p11 => (peel 8 p11.2).bind fun p12 =>
  (peel 8 p12.2).bind fun p13 => (peel 4 p13.2).bind fun p14 => (peel 32 p14.2).bind fun p15 =>
    some (⟨p1.1, p2.1, p3.1, p4.1, p5.1, p6.1, p7.1, p8.1, p9.1, p10.1, p11.1, p12.1, p13.1,
      p14.1, p15.1⟩, p15.2)

/-- The v2 tail, `codec.py:30`. Fails if the bytes run out or some are left over. -/
def parseTail (r : Bytes) : Option (Bytes × Bytes × Bytes × Bytes) :=
  (peel 4 r).bind fun p1 => (peel 4 p1.2).bind fun p2 => (peel 2 p2.2).bind fun p3 =>
  (peel 32 p3.2).bind fun p4 =>
    if p4.2 = [] then some (p1.1, p2.1, p3.1, p4.1) else none

/-- A transcript from its cells. `tail` is the v2 part, `none` for v1. -/
def txOf (f : TxCells) (ro : Role) (tail : Option (Bytes × Bytes × Bytes × Bytes)) : Transcript Bytes :=
  { role := ro, attempt := unbe f.attempt, nonce := f.nonce, pk_self := f.pk_self,
    pk_partner := f.pk_partner, sample_rate := unbe f.sample_rate, half := i32Dec (unbe f.half),
    rec_ := f.rec_, play_frame_position := unbe f.play_frame_position,
    play_nano_time := unbe f.play_nano_time, rec_frame0_nano_time := unbe f.rec_frame0_nano_time,
    self_os_delta := i32Dec (unbe f.self_os_delta), commit_hash := f.commit_hash,
    version := unbe f.ver,
    a_self := tail.map fun x => unbe x.1,
    p_partner := tail.map fun x => unbe x.2.1,
    delta := tail.map fun x => unbe x.2.2.1,
    code_commit := tail.map fun x => x.2.2.2 }

/-- `decode_transcript`, `codec.py:84-102`. -/
def decodeTranscript (raw : Bytes) : Option (Transcript Bytes) :=
  if raw.length ≠ 269 ∧ raw.length ≠ 311 then none else
  (parseTx raw).bind fun q =>
    let f := q.1
    if f.magic ≠ magicT then none else
    (roleOf f.role).bind fun ro =>
      if unbe f.ver = 1 ∧ raw.length = 269 ∧ q.2 = [] then some (txOf f ro none)
      else if unbe f.ver = 2 ∧ raw.length = 311 then
        (parseTail q.2).bind fun tl =>
          if rootOk f.rec_ = false then none else some (txOf f ro (some tl))
      else none

/-- The v2 tail as bytes. Empty for a v1 transcript. -/
def encodeTail (t : Transcript Bytes) : Bytes :=
  match t.a_self, t.p_partner, t.delta, t.code_commit with
  | some a, some b, some d, some c => be 4 a ++ (be 4 b ++ (be 2 d ++ (c ++ [])))
  | _, _, _, _ => []

/-- `encode_transcript`, `codec.py:70-81`. -/
def encodeTranscript (t : Transcript Bytes) : Bytes :=
  magicT ++ (be 1 t.version ++ (roleCell t.role ++ (be 1 t.attempt ++ (t.nonce ++ (t.pk_self ++
    (t.pk_partner ++ (be 4 t.sample_rate ++ (be 4 (i32Enc t.half) ++ (t.rec_ ++
    (be 8 t.play_frame_position ++ (be 8 t.play_nano_time ++ (be 8 t.rec_frame0_nano_time ++
    (be 4 (i32Enc t.self_os_delta) ++ (t.commit_hash ++ encodeTail t))))))))))))))

/-- The prims on this layout. The signature check accepts only `pk ++ m`, and the hash is a stand-in
of the right width. Neither is secure. They are here so `Powers` has something to hold on. -/
def prims : Prims Bytes where
  width := List.length
  verify_raw pk m s := s == pk ++ m
  sha256 m := be 32 (unbe m)
  rec_root_ok := rootOk
  decode_commit := decodeCommit
  decode_transcript := decodeTranscript

theorem parseCommit_widths {raw : Bytes} {f : CommitCells} (h : parseCommit raw = some f) :
    f.magic.length = 4 ∧ f.ver.length = 1 ∧ f.role.length = 1 ∧ f.attempt.length = 1 ∧
      f.nonce.length = 32 ∧ f.rec_.length = 32 := by
  simp only [parseCommit, Option.bind_eq_some_iff] at h
  obtain ⟨p1, h1, p2, h2, p3, h3, p4, h4, p5, h5, p6, h6, h7⟩ := h
  split_ifs at h7
  simp only [Option.some.injEq] at h7
  subst h7
  exact ⟨peel_len h1, peel_len h2, peel_len h3, peel_len h4, peel_len h5, peel_len h6⟩

theorem parseTx_widths {raw : Bytes} {q : TxCells × Bytes} (h : parseTx raw = some q) :
    q.1.magic.length = 4 ∧ q.1.ver.length = 1 ∧ q.1.role.length = 1 ∧ q.1.attempt.length = 1 ∧
      q.1.nonce.length = 32 ∧ q.1.pk_self.length = 65 ∧ q.1.pk_partner.length = 65 ∧
      q.1.sample_rate.length = 4 ∧ q.1.half.length = 4 ∧ q.1.rec_.length = 32 ∧
      q.1.play_frame_position.length = 8 ∧ q.1.play_nano_time.length = 8 ∧
      q.1.rec_frame0_nano_time.length = 8 ∧ q.1.self_os_delta.length = 4 ∧
      q.1.commit_hash.length = 32 := by
  rw [parseTx] at h
  rw [Option.bind_eq_some_iff] at h
  obtain ⟨p1, h1, h⟩ := h
  rw [Option.bind_eq_some_iff] at h
  obtain ⟨p2, h2, h⟩ := h
  rw [Option.bind_eq_some_iff] at h
  obtain ⟨p3, h3, h⟩ := h
  rw [Option.bind_eq_some_iff] at h
  obtain ⟨p4, h4, h⟩ := h
  rw [Option.bind_eq_some_iff] at h
  obtain ⟨p5, h5, h⟩ := h
  rw [Option.bind_eq_some_iff] at h
  obtain ⟨p6, h6, h⟩ := h
  rw [Option.bind_eq_some_iff] at h
  obtain ⟨p7, h7, h⟩ := h
  rw [Option.bind_eq_some_iff] at h
  obtain ⟨p8, h8, h⟩ := h
  rw [Option.bind_eq_some_iff] at h
  obtain ⟨p9, h9, h⟩ := h
  rw [Option.bind_eq_some_iff] at h
  obtain ⟨p10, h10, h⟩ := h
  rw [Option.bind_eq_some_iff] at h
  obtain ⟨p11, h11, h⟩ := h
  rw [Option.bind_eq_some_iff] at h
  obtain ⟨p12, h12, h⟩ := h
  rw [Option.bind_eq_some_iff] at h
  obtain ⟨p13, h13, h⟩ := h
  rw [Option.bind_eq_some_iff] at h
  obtain ⟨p14, h14, h⟩ := h
  rw [Option.bind_eq_some_iff] at h
  obtain ⟨p15, h15, h⟩ := h
  rw [Option.some.injEq] at h
  subst h
  exact ⟨peel_len h1, peel_len h2, peel_len h3, peel_len h4, peel_len h5, peel_len h6, peel_len h7,
    peel_len h8, peel_len h9, peel_len h10, peel_len h11, peel_len h12, peel_len h13, peel_len h14,
    peel_len h15⟩

theorem parseTail_widths {r : Bytes} {x : Bytes × Bytes × Bytes × Bytes} (h : parseTail r = some x) :
    x.1.length = 4 ∧ x.2.1.length = 4 ∧ x.2.2.1.length = 2 ∧ x.2.2.2.length = 32 := by
  simp only [parseTail, Option.bind_eq_some_iff] at h
  obtain ⟨p1, h1, p2, h2, p3, h3, p4, h4, h5⟩ := h
  split_ifs at h5
  simp only [Option.some.injEq] at h5
  subst h5
  have w1 := peel_len h1
  have w2 := peel_len h2
  have w3 := peel_len h3
  have w4 := peel_len h4
  exact ⟨w1, w2, w3, w4⟩

/-- A wrong total length is rejected, `codec.py:56`. -/
theorem decodeCommit_wrong_length {raw : Bytes} (h : raw.length ≠ 71) : decodeCommit raw = none := by
  rw [decodeCommit, ite_eq_left_of_eq_true _ _ (eq_true h)]

/-- A wrong total length is rejected, `codec.py:86`. -/
theorem decodeTranscript_wrong_length {raw : Bytes} (h : raw.length ≠ 269) (h' : raw.length ≠ 311) :
    decodeTranscript raw = none := by
  rw [decodeTranscript, ite_eq_left_of_eq_true _ _ (eq_true ⟨h, h'⟩)]

omit [DecidableEq B] in
private theorem ite_none {α : Type} {c : Prop} [Decidable c] {x : Option α} {y : α} :
    (if c then none else x) = some y ↔ ¬ c ∧ x = some y := by
  split <;> simp_all

private theorem unbe_lt' {l : Bytes} {k m : ℕ} (h : l.length = k) (hm : 256 ^ k = m) : unbe l < m := by
  have := unbe_lt l
  rw [h, hm] at this
  exact this

/-- **The decoder holds widths fixed.** Whatever it returns has the wire widths and ranges, so no
33-byte nonce can come out of it. -/
theorem decodeCommit_wire_ok {raw : Bytes} {c : Commit Bytes} (h : decodeCommit raw = some c) :
    c.wire_ok prims := by
  simp only [decodeCommit, ite_none, Option.bind_eq_some_iff, Option.some.injEq] at h
  obtain ⟨_, f, hf, _, h2, ro, _, h3, rfl⟩ := h
  obtain ⟨_, wv, _, wa, wn, wr⟩ := parseCommit_widths hf
  have ha : unbe f.attempt < 2^8 := unbe_lt' wa (by norm_num)
  refine ⟨?_, ha, wn, wr, ?_⟩
  · show unbe f.ver = 1 ∨ unbe f.ver = 2
    omega
  · intro hv
    have hv' : unbe f.ver = 2 := hv
    show rootOk f.rec_ = true
    by_contra hc
    exact h3 ⟨hv', by simpa using hc⟩

/-- **The decoder holds widths fixed.** The same for transcripts. -/
theorem decodeTranscript_wire_ok {raw : Bytes} {t : Transcript Bytes}
    (h : decodeTranscript raw = some t) : t.wire_ok prims := by
  rw [decodeTranscript, ite_none, Option.bind_eq_some_iff] at h
  obtain ⟨_, q, hq, h⟩ := h
  simp only [ite_none, Option.bind_eq_some_iff] at h
  obtain ⟨_, ro, _, h⟩ := h
  obtain ⟨_, _, _, wa, wn, wps, wpp, wsr, wh, wr, wpos, wpl, wf0, wd, wch⟩ := parseTx_widths hq
  have ha : unbe q.1.attempt < 2^8 := unbe_lt' wa (by norm_num)
  have hsr : unbe q.1.sample_rate < 2^32 := unbe_lt' wsr (by norm_num)
  have hpos : unbe q.1.play_frame_position < 2^64 := unbe_lt' wpos (by norm_num)
  have hpl : unbe q.1.play_nano_time < 2^64 := unbe_lt' wpl (by norm_num)
  have hf0 : unbe q.1.rec_frame0_nano_time < 2^64 := unbe_lt' wf0 (by norm_num)
  obtain ⟨hh1, hh2⟩ := i32Dec_range (unbe_lt' wh rfl)
  obtain ⟨hd1, hd2⟩ := i32Dec_range (unbe_lt' wd rfl)
  by_cases hv1 : unbe q.1.ver = 1 ∧ raw.length = 269 ∧ q.2 = []
  · rw [ite_eq_left_of_eq_true _ _ (eq_true hv1), Option.some.injEq] at h
    subst h
    refine ⟨Or.inl hv1.1, ha, wn, wps, wpp, wr, wch, hsr, hh1, hh2, hd1, hd2, hpos, hpl, hf0, ?_, ?_⟩
    · intro _; simp [txOf]
    · intro hv
      have hv' : unbe q.1.ver = 2 := hv
      have := hv1.1
      omega
  · rw [ite_eq_right_of_eq_false _ _ (eq_false hv1)] at h
    by_cases hv2 : unbe q.1.ver = 2 ∧ raw.length = 311
    · rw [ite_eq_left_of_eq_true _ _ (eq_true hv2), Option.bind_eq_some_iff] at h
      obtain ⟨tl, htl, h⟩ := h
      rw [ite_none, Option.some.injEq] at h
      obtain ⟨hroot, h⟩ := h
      subst h
      obtain ⟨w1, w2, w3, w4⟩ := parseTail_widths htl
      have ta : unbe tl.1 < 2^32 := unbe_lt' w1 (by norm_num)
      have tb : unbe tl.2.1 < 2^32 := unbe_lt' w2 (by norm_num)
      have tc : unbe tl.2.2.1 < 2^16 := unbe_lt' w3 (by norm_num)
      refine ⟨Or.inr hv2.1, ha, wn, wps, wpp, wr, wch, hsr, hh1, hh2, hd1, hd2, hpos, hpl, hf0, ?_, ?_⟩
      · intro hv
        have hv' : unbe q.1.ver = 1 := hv
        have := hv2.1
        omega
      · intro _
        refine ⟨?_, ⟨_, rfl, ta⟩, ⟨_, rfl, tb⟩, ⟨_, rfl, tc⟩, ⟨_, rfl, w4⟩⟩
        show rootOk q.1.rec_ = true
        simpa using hroot
    · rw [ite_eq_right_of_eq_false _ _ (eq_false hv2)] at h
      cases h

theorem decode_encodeCommit {c : Commit Bytes} (hw : c.wire_ok prims) :
    decodeCommit (encodeCommit c) = some c := by
  obtain ⟨hv, ha, hn, hr, hroot⟩ := hw
  have hn' : c.nonce.length = 32 := hn
  have hr' : c.rec_.length = 32 := hr
  have hroot' : c.version = 2 → rootOk c.rec_ = true := hroot
  have hvb : unbe (be 1 c.version) = c.version := unbe_be _ _ (by norm_num; omega)
  have hab : unbe (be 1 c.attempt) = c.attempt := unbe_be _ _ (by norm_num at ha ⊢; exact ha)
  have hl : (encodeCommit c).length = 71 := by
    simp [encodeCommit, magicC, be_length, roleCell_length, hn', hr']
  have hp : parseCommit (encodeCommit c) =
      some ⟨magicC, be 1 c.version, roleCell c.role, be 1 c.attempt, c.nonce, c.rec_⟩ := by
    simp only [encodeCommit, parseCommit,
      peel_append (a := magicC) (n := 4) rfl, Option.bind_some,
      peel_append (a := be 1 c.version) (n := 1) (be_length _ _),
      peel_append (a := roleCell c.role) (n := 1) (roleCell_length _),
      peel_append (a := be 1 c.attempt) (n := 1) (be_length _ _),
      peel_append hn', peel_append hr', ite_true]
  simp only [decodeCommit, hl, hp, Option.bind_some, hvb, hab, roleOf_cell]
  have h1 : ¬ (c.version ≠ 1 ∧ c.version ≠ 2) := by omega
  have h2 : ¬ (c.version = 2 ∧ rootOk c.rec_ = false) := by
    rintro ⟨a, b⟩; simp [hroot' a] at b
  simp [h1, h2]

theorem parseTail_encode {a b d : ℕ} {c : Bytes} (hc : c.length = 32) :
    parseTail (be 4 a ++ (be 4 b ++ (be 2 d ++ (c ++ [])))) = some (be 4 a, be 4 b, be 2 d, c) := by
  simp only [parseTail, peel_append (a := be 4 a) (n := 4) (be_length _ _), Option.bind_some,
    peel_append (a := be 4 b) (n := 4) (be_length _ _),
    peel_append (a := be 2 d) (n := 2) (be_length _ _), peel_append hc, ite_true]

/-- The cells `encodeTranscript` writes. -/
def cellsOf (t : Transcript Bytes) : TxCells :=
  ⟨magicT, be 1 t.version, roleCell t.role, be 1 t.attempt, t.nonce, t.pk_self, t.pk_partner,
    be 4 t.sample_rate, be 4 (i32Enc t.half), t.rec_, be 8 t.play_frame_position,
    be 8 t.play_nano_time, be 8 t.rec_frame0_nano_time, be 4 (i32Enc t.self_os_delta),
    t.commit_hash⟩

private theorem bind_peel {α : Type} {a : Bytes} {n : ℕ} (h : a.length = n) (b : Bytes)
    (f : Bytes × Bytes → Option α) : (peel n (a ++ b)).bind f = f (a, b) := by
  rw [peel_append h]; rfl

private theorem parseTx_encode {t : Transcript Bytes} (hn : t.nonce.length = 32)
    (hps : t.pk_self.length = 65) (hpp : t.pk_partner.length = 65) (hr : t.rec_.length = 32)
    (hch : t.commit_hash.length = 32) :
    parseTx (encodeTranscript t) = some (cellsOf t, encodeTail t) := by
  rw [encodeTranscript, parseTx, bind_peel (a := magicT) (n := 4) rfl,
    bind_peel (a := be 1 t.version) (n := 1) (be_length _ _),
    bind_peel (a := roleCell t.role) (n := 1) (roleCell_length _),
    bind_peel (a := be 1 t.attempt) (n := 1) (be_length _ _),
    bind_peel hn, bind_peel hps, bind_peel hpp,
    bind_peel (a := be 4 t.sample_rate) (n := 4) (be_length _ _),
    bind_peel (a := be 4 (i32Enc t.half)) (n := 4) (be_length _ _),
    bind_peel hr,
    bind_peel (a := be 8 t.play_frame_position) (n := 8) (be_length _ _),
    bind_peel (a := be 8 t.play_nano_time) (n := 8) (be_length _ _),
    bind_peel (a := be 8 t.rec_frame0_nano_time) (n := 8) (be_length _ _),
    bind_peel (a := be 4 (i32Enc t.self_os_delta)) (n := 4) (be_length _ _),
    bind_peel hch]
  rfl

private theorem tx_eta (t : Transcript Bytes) {a b d : Option ℕ} {c : Option Bytes}
    (h1 : t.a_self = a) (h2 : t.p_partner = b) (h3 : t.delta = d) (h4 : t.code_commit = c) :
    ({ role := t.role, attempt := t.attempt, nonce := t.nonce, pk_self := t.pk_self,
       pk_partner := t.pk_partner, sample_rate := t.sample_rate, half := t.half, rec_ := t.rec_,
       play_frame_position := t.play_frame_position, play_nano_time := t.play_nano_time,
       rec_frame0_nano_time := t.rec_frame0_nano_time, self_os_delta := t.self_os_delta,
       commit_hash := t.commit_hash, version := t.version, a_self := a, p_partner := b, delta := d,
       code_commit := c } : Transcript Bytes) = t := by
  subst h1 h2 h3 h4
  rfl

theorem decode_encodeTranscript {t : Transcript Bytes} (hw : t.wire_ok prims) :
    decodeTranscript (encodeTranscript t) = some t := by
  obtain ⟨hv, ha, hn, hps, hpp, hr, hch, hsr, hh1, hh2, hd1, hd2, hpos, hpl, hf0, hv1, hv2⟩ := hw
  have hn' : t.nonce.length = 32 := hn
  have hps' : t.pk_self.length = 65 := hps
  have hpp' : t.pk_partner.length = 65 := hpp
  have hr' : t.rec_.length = 32 := hr
  have hch' : t.commit_hash.length = 32 := hch
  obtain ⟨ih, ihl⟩ := i32_round hh1 hh2
  obtain ⟨id, idl⟩ := i32_round hd1 hd2
  have hp := parseTx_encode hn' hps' hpp' hr' hch'
  have hvb : unbe (be 1 t.version) = t.version := unbe_be _ _ (by norm_num; omega)
  have hab : unbe (be 1 t.attempt) = t.attempt := unbe_be _ _ (by norm_num at ha ⊢; exact ha)
  have hsb : unbe (be 4 t.sample_rate) = t.sample_rate := unbe_be _ _ (by norm_num at hsr ⊢; exact hsr)
  have hhb : unbe (be 4 (i32Enc t.half)) = i32Enc t.half := unbe_be _ _ ihl
  have hdb : unbe (be 4 (i32Enc t.self_os_delta)) = i32Enc t.self_os_delta := unbe_be _ _ idl
  have hposb : unbe (be 8 t.play_frame_position) = t.play_frame_position :=
    unbe_be _ _ (by norm_num at hpos ⊢; exact hpos)
  have hplb : unbe (be 8 t.play_nano_time) = t.play_nano_time :=
    unbe_be _ _ (by norm_num at hpl ⊢; exact hpl)
  have hf0b : unbe (be 8 t.rec_frame0_nano_time) = t.rec_frame0_nano_time :=
    unbe_be _ _ (by norm_num at hf0 ⊢; exact hf0)
  have hm : (cellsOf t).magic = magicT := rfl
  have hro : (cellsOf t).role = roleCell t.role := rfl
  have hve : unbe (cellsOf t).ver = t.version := hvb
  rcases hv with hv | hv
  · obtain ⟨e1, e2, e3, e4⟩ := hv1 hv
    have htail : encodeTail t = [] := by simp [encodeTail, e1]
    have hl : (encodeTranscript t).length = 269 := by
      simp [encodeTranscript, magicT, be_length, roleCell_length, hn', hps', hpp', hr', hch', htail]
    have ht : txOf (cellsOf t) t.role none = t := by
      simp only [txOf, cellsOf, hab, hsb, hhb, hdb, ih, id, hposb, hplb, hf0b, hvb, Option.map_none]
      exact tx_eta t e1 e2 e3 e4
    rw [decodeTranscript, ite_eq_right_of_eq_false _ _ (eq_false (by rw [hl]; norm_num)), hp, Option.bind_some]
    simp only [hm, hro, roleOf_cell, Option.bind_some, hve, hv, hl, htail, ne_eq, not_true_eq_false,
      ite_false, and_self, ite_true, ht]
  · obtain ⟨root, ⟨x, ex, hx⟩, ⟨y, ey, hy⟩, ⟨z, ez, hz⟩, ⟨c, ec, hc⟩⟩ := hv2 hv
    have hc' : c.length = 32 := hc
    have htail : encodeTail t = be 4 x ++ (be 4 y ++ (be 2 z ++ (c ++ []))) := by
      simp only [encodeTail, ex, ey, ez, ec]
    have hl : (encodeTranscript t).length = 311 := by
      rw [encodeTranscript, htail]
      simp [magicT, be_length, roleCell_length, hn', hps', hpp', hr', hch', hc']
    have root' : rootOk (cellsOf t).rec_ = true := root
    have hxb : unbe (be 4 x) = x := unbe_be _ _ (by norm_num at hx ⊢; exact hx)
    have hyb : unbe (be 4 y) = y := unbe_be _ _ (by norm_num at hy ⊢; exact hy)
    have hzb : unbe (be 2 z) = z := unbe_be _ _ (by norm_num at hz ⊢; exact hz)
    have ht : txOf (cellsOf t) t.role (some (be 4 x, be 4 y, be 2 z, c)) = t := by
      simp only [txOf, cellsOf, hab, hsb, hhb, hdb, ih, id, hposb, hplb, hf0b, hvb, Option.map_some, hxb,
        hyb, hzb]
      exact tx_eta t ex ey ez ec
    rw [decodeTranscript, ite_eq_right_of_eq_false _ _ (eq_false (by rw [hl]; norm_num)), hp, Option.bind_some]
    simp only [hm, hro, roleOf_cell, Option.bind_some, hve, hv, hl, htail, parseTail_encode hc', root',
      ne_eq, not_true_eq_false, ite_false, and_self, ite_true, ht]
    simp [ht]

/-- The stand-in hash has the width of SHA-256. -/
theorem prims_sha_width (m : Bytes) : prims.width (prims.sha256 m) = 32 := by
  have h1 : ∀ x : Bytes, prims.width x = x.length := fun _ => rfl
  have h2 : prims.sha256 m = be 32 (unbe m) := rfl
  rw [h1, h2, be_length]

theorem unbe_fill_zero (n : ℕ) : unbe (List.replicate n 0) = 0 := by
  induction n with
  | zero => rfl
  | succ n ih =>
    have h : List.replicate (n + 1) (0 : Byte) = List.replicate n 0 ++ [0] := by
      simp [List.replicate_succ']
    rw [h, unbe_snoc, ih]
    rfl

/-- Hex, for the runs that compare against `codec.py`. -/
def hex (l : Bytes) : String :=
  String.join (l.map fun b =>
    String.singleton (Nat.digitChar (b.val / 16)) ++ String.singleton (Nat.digitChar (b.val % 16)))

/-- A run of `n` equal bytes. -/
def fill (n : ℕ) (b : Byte) : Bytes := List.replicate n b

/-- A commit, compared with `codec.py` by a run. -/
def sampleCommit (v : ℕ) : Commit Bytes :=
  { role := .B, attempt := 3, nonce := fill 32 7, rec_ := fill 32 9, version := v }

/-- A transcript, compared with `codec.py` by a run. Holds a negative half and a negative delta. -/
def sampleTx (v : ℕ) : Transcript Bytes :=
  { role := .A, attempt := 1, nonce := fill 32 7, pk_self := fill 65 1, pk_partner := fill 65 2,
    sample_rate := 48000, half := -5, rec_ := fill 32 9, play_frame_position := 1000,
    play_nano_time := 2000000000, rec_frame0_nano_time := 3000000000, self_os_delta := -77,
    commit_hash := fill 32 4, version := v,
    a_self := if v = 2 then some 70000 else none, p_partner := if v = 2 then some 80000 else none,
    delta := if v = 2 then some 96 else none, code_commit := if v = 2 then some (fill 32 6) else none }

end Layout

/-- **`Powers` can hold on a decoder that holds widths fixed.** The decoder is `Layout.decodeCommit`
and `Layout.decodeTranscript`. `Layout.decodeCommit_wire_ok` and `Layout.decodeTranscript_wire_ok`
show that whatever they return has the wire widths, and the theorems named `wrong_length` show a
wrong total length is refused. A decoder like this can't spot one field of the wrong size: bytes of
the right total length are simply cut at the wire widths.

This is a Lean copy of the layout, not `codec.py`. That the Python gives `Powers` is by reading and by
runs, not by proof. Signatures and hash here are stand-ins.

It does not show a phone told the truth about the air (CN1). -/
theorem Powers_satisfiable (pkA pkB : Layout.Bytes) : Powers Layout.prims pkA pkB where
  write_commit c hc := ⟨_, Layout.decode_encodeCommit hc⟩
  write_transcript t ht := ⟨_, Layout.decode_encodeTranscript ht⟩
  sign pk _ m := ⟨pk ++ m, by simp [Layout.prims]⟩

/-- **X1 run through its own hypotheses, on the fixed-width decoder.** Every hypothesis of `X1` is met
at once, for version 1 and for version 2. The proof feeds `X1` 65-byte keys, all-zero recording values
with no recording behind them, self deltas 0 and calibration 0.

**What the statement pins.** Halves 100 and 0, rates 48000, version `ver` on both sides, and
`X1Outcome` (every check passes, verdict NEAR) with an all-zero nonce, attempt 0 and calibration 0.
So `X1` is not empty. Keys, recording values, self deltas and `code_commit` are what the proof
builds, not what the statement says; `X1_on_layout_keys` pins them.

It does not show a phone told the truth about the air (CN1). It shows the verdict can't know. -/
theorem X1_on_layout (ver : ℕ) (hv : ver = 1 ∨ ver = 2) :
    ∃ sA sB : Side Layout.Bytes,
      sA.half = 100 ∧ sB.half = 0 ∧ sA.sample_rate = 48000 ∧ sB.sample_rate = 48000 ∧
      sA.version = ver ∧ sB.version = ver ∧
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
  obtain ⟨sA, sB, h1, h2, h3, h4, _, _, h7, h8, hx⟩ :=
    X1 Layout.prims (Layout.fill 65 1) (Layout.fill 65 2) (Layout.fill 32 0)
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
  exact ⟨sA, sB, h1, h2, h3, h4, h7, h8, hx⟩

/-- **The reverse of "NEAR implies range" is false.** The circuit's range test has no self check. Here
the flight is in range, the two transcripts are a proper pair, and the server gives no verdict, as
A's self delta is one frame past the edge.

It does not show a phone told the truth about the air (CN1). -/
theorem V3_range_does_not_give_near :
    let ta := { (toyA 1).transcript toySha .A 0 toyNonce with self_os_delta := 2401 }
    let tb := (toyB 1).transcript toySha .B 0 toyNonce
    (-20 < flight_exact ta.half ta.sample_rate tb.half tb.sample_rate ∧
      flight_exact ta.half ta.sample_rate tb.half tb.sample_rate < 60) ∧
    combine ta tb none = .ok ⟨none, none, some .self_timestamp_mismatch, some .A⟩ := by
  have hf : flight_exact 100 48000 0 48000 = 1715 / 48 := toy_flight
  have hs : self_os_ok 2401 48000 0 = false := by norm_num [self_os_ok, abs_of_pos]
  intro ta tb
  have hpair : pair ta tb := by
    refine ⟨rfl, rfl, rfl, rfl, rfl, rfl, ?_⟩
    simp [ta, tb, Side.transcript, toyA, toyB]
  have hA : self_check ta none = false := by
    simpa [self_check, cal_for, ta, Side.transcript, toyA, version_of] using hs
  refine ⟨?_, ?_⟩
  · change -20 < flight_exact 100 48000 0 48000 ∧ flight_exact 100 48000 0 48000 < 60
    rw [hf]; norm_num
  · rw [combine_pair_steps none hpair, hA]
    simp [ta, Side.transcript]

end ServerFv

/-! ## Axioms -/

#print axioms ServerFv.V1
#print axioms ServerFv.V2
#print axioms ServerFv.V3
#print axioms ServerFv.V3_ties
#print axioms ServerFv.V3_circuit
#print axioms ServerFv.V3_near_gives_range
#print axioms ServerFv.V3_range_does_not_give_near
#print axioms ServerFv.V4
#print axioms ServerFv.V4_cal
#print axioms ServerFv.V4_edges
#print axioms ServerFv.V5_combine_swapped
#print axioms ServerFv.V5_record_swapped
#print axioms ServerFv.V5_record_swapped_mixed_versions
#print axioms ServerFv.V5_record_all_swapped
#print axioms ServerFv.V5_live_other_role
#print axioms ServerFv.V6
#print axioms ServerFv.V6_free
#print axioms ServerFv.popt2_delta_48000
#print axioms ServerFv.self_os_can_pass
#print axioms ServerFv.X1_core
#print axioms ServerFv.X1
#print axioms ServerFv.X1_witness_v1
#print axioms ServerFv.X1_witness_v2
#print axioms ServerFv.Powers_satisfiable
#print axioms ServerFv.X1_on_layout
#print axioms ServerFv.Layout.decodeCommit_wire_ok
#print axioms ServerFv.Layout.decodeTranscript_wire_ok
#print axioms ServerFv.Layout.decodeCommit_wrong_length
#print axioms ServerFv.Layout.decodeTranscript_wrong_length

/-! ## The definitions run -/

open ServerFv in
#eval decide (-20)
open ServerFv in
#eval flight_exact 100 48000 0 48000
open ServerFv in
#eval self_os_ok 2400 48000 0
open ServerFv in
#eval combine ((toyA 1).transcript toySha .A 0 toyNonce) ((toyB 1).transcript toySha .B 0 toyNonce) none
open ServerFv in
#eval verify_record (toyPrims 1) (x1Record (toyA 1) (toyB 1) toyNonce 0 0 0)

/-! ## The byte layout, compared with `codec.py` by a run -/

open ServerFv.Layout in
#eval "LAYOUT commit1 " ++ hex (encodeCommit (sampleCommit 1))
open ServerFv.Layout in
#eval "LAYOUT commit2 " ++ hex (encodeCommit (sampleCommit 2))
open ServerFv.Layout in
#eval "LAYOUT tx1 " ++ hex (encodeTranscript (sampleTx 1))
open ServerFv.Layout in
#eval "LAYOUT tx2 " ++ hex (encodeTranscript (sampleTx 2))
open ServerFv.Layout in
#eval decodeCommit (encodeCommit (sampleCommit 1)) == some (sampleCommit 1)
open ServerFv.Layout in
#eval decodeTranscript (encodeTranscript (sampleTx 2)) == some (sampleTx 2)
open ServerFv.Layout in
#eval (decodeCommit (encodeCommit { sampleCommit 1 with nonce := fill 33 7 })).isNone
