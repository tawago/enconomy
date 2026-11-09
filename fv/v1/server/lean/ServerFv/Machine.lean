import ServerFv.Verdict

/-!
# The session machine of the server (`server/pop/sessions.py`)

A literal Lean copy of the session steps in `sessions.py`, from the table in
`fv/v1/server/spec.md` section 3.5. Same names, same order of guards. Line numbers in comments are
for `sessions.py` at 5863e9c, unless another file is named; they are pointers only, the replay runs
against the checkout's own `server/`. Property ids (M1 .. M13) are from `spec.md`.

**What this file shows, and what it does not.** These results show the server follows its rules on
signed numbers. They do not show a phone told the truth about the air (CN1). A NEAR means two keys
signed two numbers that fit a range. It does not mean two phones were close. See `X1` in
`Verdict.lean`. The witness at the end of this file reaches NEAR with numbers picked by hand, and no
audio exists anywhere in this model.

**Scope.** Only the basic proximity flow. Every session here has `context=None` and
`early_nonce=False`. Contexts, zk routes, the presence signature, recording upload, enrolment
and audio processing are not modeled, and nothing is claimed about them.

**Assumptions, by name.** Ids are from `spec.md` section 2.
* A1, honest server: the code runs as written.
* A2 and A3, one worker process and no await between load and save: each `step` here is one
  uninterrupted request on the latest stored document. That is built into the shape of `Reachable`.
* A4, signatures can't be forged: the check is the opaque `Prims.verify_raw`. Only `M3_signed` turns
  a passed check into "the key's holder signed", and it says `Unforgeable` in its hypotheses.
* A5, one device id means one key: `Env.pk` is a plain function from id to key. So a re-enrol can't
  change the key behind an id. Three theorems also need ids and keys to match one to one:
  `combine_guard_unreachable`, `afterStore_accepted` and `combine_guard_on_request`. Each says so in
  its hypotheses (`Function.Injective e.pk`). `M8_keys` needs SHA-256 to have no collision among the
  four messages of one seed, and says so too. It asks nothing about any other input.
* A7, the clock doesn't go back: `Reachable` only takes a step whose clock read is not before the
  last one. Every theorem built on `step_inv` or `frame_step` takes this as a hypothesis (`c ≤ w.now`).
  M11 leans on it most, in two places: for "t0 is at least arm time + 3000", and for `created_ms` being at most
  the clock read of the finalizing load (`created_le`).
* A8, the store returns what was last saved: an error returns the document as the load left it.
* A9, out-of-scope routes don't move the core fields of this kind of session: they are not steps
  here, apart from `Req.noauth_load`, which stands for what they do by running `load`.
* A10, every save works: there is no failed save here. `spec.md` E500-meta shows the real code can
  break this. That loses progress, not safety, since a failed save stores nothing.

**How the Lean copy differs from the Python.** These are the differences we know of.
* One clock read per step, `World.now`. The real code reads the clock several times in a handler.
  So `join`'s second expiry check (line 184) can't fire here, and `finished_ms` is the load's read.
* `per_role[r]` is split into groups written together: `arm` (line 251), `commit` (line 298),
  `tx` (line 447), `fail_` (line 479). A key being present is the group being `some`.
* Dropped, as in `spec.md` section 3.3: display fields, `updated_ms`, `meta`, `rtt_min_ms` (kept as a
  guard), `zk`, `presence`, `context`, `early_nonce`, `not_before`, `last_flight_cm`, `code_attest`,
  `submitted_ms`, `result.json`, `user_text`, `proto`. Kept against that list, since M5 and M11 need them:
  `armed_ms` and `committed_ms`. Python's `created_at` and `finished_at` are `created_ms` and `finished_ms` here.
* Error details are dropped. An error is a status and a code.
* Codes are one opaque value `Code` (seed, role, attempt). Real ones are PCM from `jbl250`. A response
  field of type `Code` stands for the `play`, `own_bed`, `own_code`, `partner_bed`, `partner_code`
  fields. The seed sits inside that value only, and A6 in `spec.md` says it can't be got back.
* Base64 is an opaque partial function `Env.b64d`. Wire strings are `B`, like raw bytes.
* A request's JSON body is already sorted into `Arg`. `Arg.other` is anything that isn't null or an
  int, a bool included.
* Uncaught Python exceptions are the response `error 500 internal`, with the document as loaded:
  line 454 or a rate of 0 in `combine`. `M9` shows the paths that need a missing key can't happen, so
  a `None` where Python would raise a `TypeError` or `KeyError` (`t0_ms`, `_pk`, `mine[...]`) takes
  a harmless default here. These are the spots marked "unreachable".
* Three known 500s are plain refusals here, with the same stored document: a `reason` that is a list
  (`spec.md` E500-fail) is `reason = none`, a 400, a non-ASCII token (E500-join) is a 403, and an
  `X-Pop-Ts` that `int` can't read (E500-ts, section 3.4) is `sender = none`, a 401.
* `token.lower()` is `String.toLower`. It differs from Python only on non-ASCII, see the line above.
* One session document at a time. An unknown session id is a 404 with nothing stored, so not a step.
  A refused `create` stores nothing either, so it isn't a step. That covers its 500 (`spec.md` E500-create).
* The long poll of `GET /session` (`main.py:474-478`) is one load and one view. Each extra round of it is one
  more load, and it saves nothing else (A3). `Req.noauth_load` covers what such a load can do.
* `json_bad` can be set on any `Req.api`, even for a route with no body, where the Python has no such path. It only
  refuses, so it adds nothing a real request could not do.
* In this model the seed is in responses, inside `Code` values (`M5_codes`). Real responses hold PCM there.
  Only A6 says PCM doesn't give the seed away, and A6 is an assumption, not a result here.
* This table is compared with the real Python on sampled runs by `ServerFv/Replay.lean`; `fv/v1/server/run_all.sh` runs it on fresh traces.
  That is testing, not a proof that the two are equal. Nothing in this file depends on it.
-/

set_option linter.style.whitespace false
set_option linter.style.longLine false
set_option linter.style.header false
set_option linter.unusedVariables false
set_option linter.unusedSimpArgs false
set_option linter.style.setOption false
set_option linter.flexible false
set_option linter.style.multiGoal false
set_option linter.style.cases false
set_option linter.unusedSectionVars false
set_option linter.unusedTactic false
set_option linter.unreachableTactic false

namespace ServerFv

namespace K
/-- `constants.py:52` -/
abbrev JOIN_TOKEN_TTL_S : ℕ := 120
/-- `constants.py:53` -/
abbrev SESSION_MAX_AGE_S : ℕ := 600
/-- `constants.py:35` -/
abbrev TRANSCRIPT_DEADLINE_S : ℕ := 20
/-- `constants.py:36` -/
abbrev MAX_ATTEMPTS : ℕ := 2
/-- `sessions.py:296`, `int((K.B_PLAY_S + K.CODE_S) * 1000)`: 0.95 s + 0.25 s. The walk saw the gate at
exactly this number (`spec.md` M5, gate at 1199 and 1200). -/
abbrev COMMIT_GATE_MS : ℕ := 1200
end K

namespace Machine

/-- `T0_DELAY_MS`, `sessions.py:80`. -/
abbrev T0_DELAY_MS : ℕ := 3000
/-- `MAX_RTT_MS`, `sessions.py:79`. -/
abbrev MAX_RTT_MS : ℕ := 300

/-! ## Data -/

/-- The value of `s["state"]`. -/
inductive St | created | joined | confirmed | started | done | aborted
  deriving DecidableEq, Repr

/-- `LIVE`, `sessions.py:81`. -/
def live (st : St) : Bool :=
  st = .created || st = .joined || st = .confirmed || st = .started

/-- `OTHER`, `sessions.py:78`. -/
def OTHER : Role → Role
  | .A => .B
  | .B => .A

/-- The opaque `Code(seed, role, attempt)` of `spec.md` section 3.2. -/
structure Code where
  seed : String
  role : Role
  attempt : ℕ
  deriving DecidableEq, Repr

/-- `per_role[r]` written by arm, `sessions.py:251-252`. `rtt_min_ms` is only a guard. -/
structure ArmData where
  sample_rate : ℕ
  armed_ms : ℕ
  popt : ℕ
  cal_us : ℤ

/-- `per_role[r]` written by commit, `sessions.py:298-303`. `rec_` stands for `REC_KEY[ver]`. -/
structure CommitData (B : Type) where
  commit_b64 : B
  commit_sig_b64 : B
  commit_sha256 : B
  rec_ : B
  committed_ms : ℕ
  code_commit : Option B

/-- `per_role[r]` written by transcript, `sessions.py:447-449`. -/
structure TxData (B : Type) where
  transcript_b64 : B
  sig_b64 : B
  transcript_sha256 : B
  half : ℤ
  self_os_delta : ℤ

/-- `per_role[r]`. Empty is `{}`, line 166 and line 320. -/
structure PerRole (B : Type) where
  arm : Option ArmData := none
  commit : Option (CommitData B) := none
  tx : Option (TxData B) := none
  fail_ : Option (Reason × ℕ) := none

/-- The `outcome` of an attempts row. -/
inductive Outcome | failed | aborted | rejected | verdict
  deriving DecidableEq, Repr

/-- One row of `s["attempts"]`, lines 204, 314-315, 344-345. -/
structure AttemptRow (B : Type) where
  attempt : ℕ
  outcome : Outcome
  reason : Option Reason
  by_ : Option Role
  verdict : Option Verdict := none
  flight_cm : Option ℚ := none
  per_role : Option (Role → PerRole B) := none
  t0_ms : Option ℕ := none

/-- One row of `result["attempts"]`, lines 381-383. -/
structure SummaryRow where
  attempt : ℕ
  outcome : Outcome
  reason : Option Reason
  by_ : Option Role
  verdict : Option Verdict
  flight_cm : Option ℚ

/-- `s["last_failure"]`, line 316. `text` is a fixed string for the reason, so it is left out. -/
structure LastFailure where
  attempt : ℕ
  reason : Option Reason
  by_ : Option Role

/-- `result["devices"][r]`, lines 363-366. -/
structure DeviceRow (B D : Type) where
  device_id : D
  pubkey : B
  sample_rate : Option ℕ
  half : Option ℤ
  popt : ℕ
  cal_us : ℤ

/-- `result["transcripts"][r]`, lines 368-369. -/
structure TxEntry (B : Type) where
  transcript_b64 : B
  sig_b64 : B
  sha256 : B

/-- `result["commits"][r]`, line 371. -/
structure CommitEntry (B : Type) where
  commit_b64 : B
  sig_b64 : B

/-- `s["result"]`, the record from `_record`, lines 372-384, the fields in scope. -/
structure Record (B D : Type) where
  session_id : B
  session_nonce : B
  attempt : ℕ
  verdict : Verdict
  reason : Option Reason
  flight_cm : Option ℚ
  t0_ms : Option ℕ
  created_ms : ℕ
  finished_ms : Option ℕ
  devices : Role → Option (DeviceRow B D)
  transcripts : Role → Option (TxEntry B)
  commits : Role → Option (CommitEntry B)
  attempts : List SummaryRow

/-- The session document, `sessions.py:153-167`, fields of `spec.md` section 3.1. -/
structure Doc (B D : Type) where
  session_id : B
  seed_hex : String
  nonce_hex : B
  join_token : String
  token_expires_ms : ℕ
  state : St
  attempt : ℕ
  seq : ℕ
  created_ms : ℕ
  finished_ms : Option ℕ
  host_device_id : D
  guest_device_id : Option D
  confirmed : Role → Bool
  armed : Role → Bool
  committed : Role → Bool
  submitted : Role → Bool
  t0_ms : Option ℕ
  result : Option (Record B D)
  error : Option Reason
  attempts : List (AttemptRow B)
  last_failure : Option LastFailure
  per_role : Role → PerRole B

/-- The opaque parts and fixed facts of the setting. Nothing is assumed about them unless a theorem
says so. `pk` is the enrolled key behind a device id (A5). `code_commit` is `popt2.code_commit` on
codes at a rate. -/
structure Env (B D : Type) where
  p : Prims B
  b64d : B → Option B
  pk : D → B
  code_commit : ℕ → Code → Code → B

/-- What one request reads from the outside: one clock read (A7), and the `cal_us` of each device row
at that moment (`sessions.py:328-330`). How a row gets its `cal_us` is out of scope, so any value can
turn up. -/
structure World (D : Type) where
  now : ℕ
  cal : D → ℤ

/-- A JSON value in an `Any` field of a request body (`main.py:202-205`, `:220-221`). -/
inductive Arg
  | null
  | int (n : ℤ)
  | other
  deriving DecidableEq, Repr

/-- The session handlers that come after the `member` check. -/
inductive Op (B : Type)
  | view | result | confirm | abort
  | arm (attempt sample_rate : Arg) (rtt_min_ms : Option ℚ) (popt : Arg)
  | commit (commit_b64 sig_b64 : B)
  | transcript (transcript_b64 sig_b64 : B)
  | fail_ (attempt : Arg) (reason : Option Reason)

/-- The body of a route: join has no member step (`main.py:465-468`). -/
inductive Body (B : Type)
  | join (token : String)
  | op (o : Op B)

/-- A request on this session. `noauth_load` is any route that runs `load` with no auth or no member
check, for example `/zk/bundle` (`main.py:593`). Its own work is out of scope.

For the rest, in the order of `spec.md` section 3.4: `json_bad` is a body that fails the JSON parse,
`sender` is `none` when auth fails, `shape_bad` is a wrong body shape or a bad query. All three stop
before the load. `sender` is the device id, after `auth.py` accepted the request. -/
inductive Req (B D : Type)
  | noauth_load
  | api (json_bad : Bool) (sender : Option D) (shape_bad : Bool) (body : Body B)

/-- The error codes of the handlers. `reason` holds a `Reject` reason, or a `PopError` with the same
word (lines 283, 285, 287, 290). -/
inductive Err
  | auth_failed | bad_request | not_member | self_join | already_joined | bad_token | token_expired
  | bad_state | bad_attempt | bad_sample_rate | already_committed | too_early | stale_attempt
  | already_submitted | bad_reason | no_result | internal
  | reason (r : Reason)
  deriving DecidableEq, Repr

/-- The `self` and `partner` blocks of `view`, lines 669-674, fields in scope. -/
structure ViewDevice (B D : Type) where
  device_id : D
  pubkey : B
  cal_us : ℤ

/-- The dict `view` returns, lines 664-684, fields in scope. -/
structure ViewBody (B D : Type) where
  session_id : B
  seq : ℕ
  state : St
  attempt : ℕ
  role : Role
  nonce : Option B
  self_ : Option (ViewDevice B D)
  partner : Option (ViewDevice B D)
  confirmed : Role → Bool
  armed : Role → Bool
  committed : Role → Bool
  submitted : Role → Bool
  popt : Role → Option ℕ
  t0_ms : Option ℕ
  result : Option (Record B D)
  error : Option Reason
  last_failure : Option LastFailure

/-- What a request gets back. M5 and M6 are statements about this.

* `created`: line 171. Its invite fields carry the same token.
* `view`: the view.
* `armMaterial`: `_arm_material`, lines 216-229. `play` and `own_bed` always, `own_code` and `delta` in v2.
* `partnerBed`: `_partner_bed`, lines 260-269.
* `accepted`: lines 428, 465.
* `record`: `result`, line 485.
* `other`: what a `noauth_load` route answers. Out of scope, nothing is claimed about it.
* `error`: a `PopError`. -/
inductive Resp (B D : Type)
  | created (session_id nonce : B) (join_token : String) (expires_at_ms : ℕ)
  | view (v : ViewBody B D)
  | armMaterial (attempt : ℕ) (sample_rate : Option ℕ) (play own_bed : Code) (own_code : Option Code)
      (delta : Option ℕ)
  | partnerBed (partner_bed : Code) (partner_code : Option Code) (code_commit : Option B)
  | accepted (state : St) (attempt : ℕ)
  | record (r : Record B D)
  | other
  | error (status : ℕ) (code : Err)

variable {B D : Type} [DecidableEq B] [DecidableEq D]

/-! ## Small tools -/

/-- `d[r] = v` on a per-role map. -/
def upd {α : Type} (f : Role → α) (r : Role) (v : α) : Role → α :=
  fun x => if x = r then v else f x

/-- `_flags()`, lines 84-85. -/
def _flags : Role → Bool := fun _ => false

/-- `all(d.values())` on a per-role flag map. -/
def all2 (f : Role → Bool) : Bool := f .A && f .B

/-- `_int`, lines 92-93. -/
def _int : Arg → Option ℤ
  | .int n => some n
  | _ => none

/-- Device id of a role: lines 325, 333, 359. -/
def devId (s : Doc B D) : Role → Option D
  | .A => some s.host_device_id
  | .B => s.guest_device_id

/-- `_pk`, lines 332-334. `none` where Python would raise, which `M9` shows is unreachable. -/
def _pk (e : Env B D) (s : Doc B D) (r : Role) : Option B :=
  (devId s r).map e.pk

/-- `_popt`, lines 212-214. -/
def _popt (s : Doc B D) (r : Role) : ℕ :=
  ((s.per_role r).arm.map (·.popt)).getD 1

/-- `Code(seed, role, attempt)`, the current attempt: `_key`, lines 209-210. -/
def _code (s : Doc B D) (r : Role) : Code := ⟨s.seed_hex, r, s.attempt⟩

/-- `_code_commit`, lines 271-274. -/
def _code_commit (e : Env B D) (s : Doc B D) (r : Role) : B :=
  e.code_commit (((s.per_role r).arm.map (·.sample_rate)).getD 0) (_code s r) (_code s (OTHER r))

/-- `role_of`, lines 132-137. -/
def role_of (s : Doc B D) (d : D) : Option Role :=
  if d = s.host_device_id then some .A
  else if some d = s.guest_device_id then some .B
  else none

/-- `_save`, lines 106-110. `updated_ms` is dropped. Every save works (A10). -/
def _save (s : Doc B D) : Doc B D := { s with seq := s.seq + 1 }

/-- `reason in V.RETRY_REASONS`, with `None` not in it. -/
def isRetry (reason : Option Reason) : Bool :=
  match reason with
  | some r => RETRY_REASONS.contains r
  | none => false

/-! ## The steps, in file order -/

/-- `_record`, lines 355-384. It reads the document it is given, like the Python. -/
def _record (e : Env B D) (s : Doc B D) (verdict : Verdict) (reason : Option Reason)
    (flight : Option ℚ) : Record B D where
  session_id := s.session_id
  session_nonce := s.nonce_hex
  attempt := s.attempt
  verdict := verdict
  reason := reason
  flight_cm := flight
  t0_ms := s.t0_ms
  created_ms := s.created_ms
  finished_ms := s.finished_ms
  devices r := (devId s r).map fun d =>
    ⟨d, e.pk d, (s.per_role r).arm.map (·.sample_rate), (s.per_role r).tx.map (·.half),
      _popt s r, ((s.per_role r).arm.map (·.cal_us)).getD 0⟩
  transcripts r := (s.per_role r).tx.map fun t => ⟨t.transcript_b64, t.sig_b64, t.transcript_sha256⟩
  commits r := (s.per_role r).commit.map fun c => ⟨c.commit_b64, c.commit_sig_b64⟩
  attempts := s.attempts.map fun a =>
    ⟨a.attempt, a.outcome, a.reason, a.by_,
      if a.outcome = .verdict then a.verdict else none,
      if a.outcome = .verdict then a.flight_cm else none⟩

/-- `next_attempt`, lines 311-321. The guard at line 312 can't fire, since `_failed` is its only
caller and checks the same thing at line 338. So it isn't copied. `confirmed` stays. -/
def next_attempt (s : Doc B D) (reason : Option Reason) (by_ : Option Role) : Doc B D :=
  _save { s with
    attempts := s.attempts ++
      [{ attempt := s.attempt, outcome := .failed, reason := reason, by_ := by_,
         per_role := some s.per_role, t0_ms := s.t0_ms }]
    last_failure := some ⟨s.attempt, reason, by_⟩
    attempt := s.attempt + 1
    state := .confirmed
    t0_ms := none
    armed := _flags
    committed := _flags
    submitted := _flags
    per_role := fun _ => {} }

/-- `_finalize`, lines 342-353. `result.json` is not modeled. -/
def _finalize (e : Env B D) (w : World D) (s : Doc B D) (verdict : Verdict) (reason : Option Reason)
    (flight : Option ℚ) (outcome : Outcome) (by_ : Option Role) : Doc B D :=
  let s1 : Doc B D := { s with
    attempts := s.attempts ++
      [{ attempt := s.attempt, outcome := outcome, reason := reason, by_ := by_,
         verdict := some verdict, flight_cm := flight, per_role := some s.per_role, t0_ms := s.t0_ms }]
    state := .done
    error := reason
    finished_ms := some w.now }
  _save { s1 with result := some (_record e s1 verdict reason flight) }

/-- `_failed`, lines 336-340. Python's `reason` can be `None` only as a type, so `Option` is kept. -/
def _failed (e : Env B D) (w : World D) (s : Doc B D) (reason : Option Reason) (by_ : Option Role) :
    Doc B D :=
  if isRetry reason && Nat.blt (s.attempt + 1) K.MAX_ATTEMPTS then next_attempt s reason by_
  else _finalize e w s .NOT_NEAR reason none .failed by_

/-- The silent role of line 121-122: the only one not submitted, else none. -/
def silent (s : Doc B D) : Option Role :=
  match s.submitted .A, s.submitted .B with
  | false, true => some .A
  | true, false => some .B
  | _, _ => none

/-- `_expire`, lines 112-123: rows E1, E2, E3 of the table. On line 120 `t0_ms = None` would raise in
Python, and `M9` shows a started session has one. -/
def _expire (e : Env B D) (w : World D) (s : Doc B D) : Doc B D :=
  if s.state = .created ∧ w.now > s.token_expires_ms then
    _save { s with state := .aborted, error := some .timeout }
  else if live s.state = true ∧ w.now - s.created_ms > K.SESSION_MAX_AGE_S * 1000 then
    _save { s with state := .aborted, error := some .timeout }
  else if s.state = .started ∧ w.now > s.t0_ms.getD 0 + K.TRANSCRIPT_DEADLINE_S * 1000 then
    _failed e w s (some .timeout) (silent s)
  else s

/-- `load`, lines 125-129, for a known session. -/
def load (e : Env B D) (w : World D) (s : Doc B D) : Doc B D := _expire e w s

/-- `create`, lines 146-174, with `context=None`, `early_nonce=False`. `sid`, `seed`, `nonce` and `token` are
the fresh random values of lines 149-158. -/
def create (w : World D) (host : D) (sid nonce : B) (seed token : String) : Doc B D × Resp B D :=
  let s : Doc B D := _save
    { session_id := sid, seed_hex := seed, nonce_hex := nonce, join_token := token
      token_expires_ms := w.now + K.JOIN_TOKEN_TTL_S * 1000
      state := .created, attempt := 0, seq := 0
      created_ms := w.now, finished_ms := none
      host_device_id := host, guest_device_id := none
      confirmed := _flags, armed := _flags, committed := _flags, submitted := _flags
      t0_ms := none, result := none, error := none
      attempts := [], last_failure := none
      per_role := fun _ => {} }
  (s, .created s.session_id s.nonce_hex s.join_token s.token_expires_ms)

/-- `join`, lines 176-188, after the load inside it (line 177). -/
def join (w : World D) (s : Doc B D) (guest : D) (token : String) : Except (ℕ × Err) (Doc B D) :=
  if guest = s.host_device_id then .error (400, .self_join)                  -- 177-178
  else if s.guest_device_id ≠ none then .error (409, .already_joined)        -- 179-180
  else if token.toLower ≠ s.join_token then .error (403, .bad_token)         -- 181-182
  else if s.state ≠ .created ∨ w.now > s.token_expires_ms then
    .error (410, .token_expired)                                             -- 183-184
  else .ok (_save { s with guest_device_id := some guest, state := .joined }) -- 185-187

/-- `confirm`, lines 190-198. -/
def confirm (s : Doc B D) (role : Role) : Except (ℕ × Err) (Doc B D) :=
  if s.state = .confirmed ∨ (s.state = .joined ∧ s.confirmed role = true) then .ok s  -- 190-191
  else if s.state ≠ .joined then .error (409, .bad_state)                             -- 192-193
  else
    let c := upd s.confirmed role true                                                -- 194
    let s1 : Doc B D := { s with confirmed := c }
    .ok (_save (if all2 c = true then { s1 with state := .confirmed } else s1))       -- 195-197

/-- `abort`, lines 200-206. -/
def abort (w : World D) (s : Doc B D) (role : Role) : Doc B D :=
  if s.state = .done ∨ s.state = .aborted then s
  else _save { s with
    state := .aborted, error := some .aborted
    attempts := s.attempts ++
      [{ attempt := s.attempt, outcome := .aborted, reason := some .aborted, by_ := some role }]
    finished_ms := some w.now }

/-- `_arm_material`, lines 216-229. Only the sender's own code. -/
def _arm_material (s : Doc B D) (role : Role) : Resp B D :=
  let sr := (s.per_role role).arm.map (·.sample_rate)
  .armMaterial s.attempt sr (_code s role) (_code s role)
    (if _popt s role = 2 then some (_code s role) else none)
    (if _popt s role = 2 then sr.map popt2_delta else none)

/-- `sample_rate` as `int` in range, line 236. Bools are `Arg.other`. -/
def srArg : Arg → Option ℕ
  | .int n => if (K.SR_MIN : ℤ) ≤ n ∧ n ≤ (K.SR_MAX : ℤ) then some n.toNat else none
  | _ => none

/-- `popt`, lines 240-242: null means 1. Any other value but the integers 1 and 2 is refused. -/
def poptArg : Arg → Option ℕ
  | .null => some 1
  | .int 1 => some 1
  | .int 2 => some 2
  | _ => none

/-- `rtt_min_ms` in range, line 238. A non-number is `none`. -/
def rttOk (rtt : Option ℚ) : Bool :=
  match rtt with
  | some x => Decidable.decide (0 ≤ x ∧ x ≤ (MAX_RTT_MS : ℚ))
  | none => false

/-- `arm`, lines 231-257. -/
def arm (e : Env B D) (w : World D) (s : Doc B D) (role : Role) (attempt sample_rate : Arg)
    (rtt : Option ℚ) (popt : Arg) : Doc B D × Resp B D :=
  if ¬ (s.state = .confirmed ∨ s.state = .started) then (s, .error 409 .bad_state)    -- 231-232
  else if attempt ≠ .int s.attempt then (s, .error 400 .bad_attempt)                  -- 235-236
  else match srArg sample_rate with
  | none => (s, .error 400 .bad_sample_rate)                                          -- 237-238
  | some sr =>
    if rttOk rtt = false then (s, .error 400 .bad_request)                            -- 239-240
    else match poptArg popt with
    | none => (s, .error 400 .bad_request)                                            -- 241-243
    | some v =>
      if s.armed role = true then                                                     -- 244
        if (s.per_role role).arm.map (·.sample_rate) ≠ some sr then
          (s, .error 409 .bad_state)                                                  -- 245-246
        else if _popt s role ≠ v then (s, .error 409 .bad_state)                      -- 247-248
        else (s, _arm_material s role)                                                -- 249
      else if s.state ≠ .confirmed then (s, .error 409 .bad_state)                    -- 250-251
      else
        let cal := ((devId s role).map w.cal).getD 0                                  -- 253, _cal_us
        let a := upd s.armed role true                                                -- 254
        let s1 : Doc B D := { s with
          per_role := upd s.per_role role { arm := some ⟨sr, w.now, v, cal⟩ }         -- 252-253
          armed := a }
        let s2 := _save (if all2 a = true then                                        -- 255-257
          { s1 with state := .started, t0_ms := some (w.now + T0_DELAY_MS) } else s1)
        (s2, _arm_material s2 role)                                                   -- 258

/-- `_partner_bed`, lines 260-269. -/
def _partner_bed (s : Doc B D) (role : Role) : Resp B D :=
  .partnerBed (_code s (OTHER role))
    (if _popt s role = 2 then some (_code s (OTHER role)) else none)
    (if _popt s role = 2 then ((s.per_role role).commit.bind (·.code_commit)) else none)

/-- Lines 299-308: what an accepted commit stores. -/
def commitStore (s : Doc B D) (role : Role) (cd : CommitData B) : Doc B D :=
  _save { s with
    per_role := upd s.per_role role { s.per_role role with commit := some cd }
    committed := upd s.committed role true }

/-- `commit`, lines 276-308. -/
def commit (e : Env B D) (w : World D) (s : Doc B D) (role : Role) (dev : D) (commit_b64 sig_b64 : B) :
    Doc B D × Resp B D :=
  if s.state ≠ .started then (s, .error 409 .bad_state)                               -- 278-279
  else match e.b64d commit_b64, e.b64d sig_b64 with
  | some raw, some sig =>
    match e.p.decode_commit raw with
    | none => (s, .error 400 (.reason .transcript_mismatch))                          -- 283-284
    | some c =>
      if e.p.verify_raw (e.pk dev) raw sig = false then
        (s, .error 400 (.reason .signature_invalid))                                  -- 285-286
      else if c.role ≠ role ∨ c.attempt ≠ s.attempt ∨ c.nonce ≠ s.nonce_hex then
        (s, .error 400 (.reason .transcript_mismatch))                                -- 287-288
      else if c.version ≠ _popt s role then
        (s, .error 400 (.reason .transcript_mismatch))                                -- 289-291
      else if s.committed role = true then                                            -- 293
        if (s.per_role role).commit.map (·.commit_b64) ≠ some commit_b64 then
          (s, .error 409 .already_committed)                                          -- 294-295
        else (s, _partner_bed s role)                                                 -- 296
      else if w.now < s.t0_ms.getD 0 + K.COMMIT_GATE_MS then
        (s, .error 409 .too_early)                                                    -- 297-298
      else
        let cd : CommitData B :=
          { commit_b64 := commit_b64, commit_sig_b64 := sig_b64
            commit_sha256 := e.p.sha256 raw, rec_ := c.rec_, committed_ms := w.now
            code_commit := if c.version = 2 then some (_code_commit e s role) else none } -- 299-304
        let s1 := commitStore s role cd
        (s1, _partner_bed s1 role)                                                    -- 309
  | _, _ => (s, .error 400 (.reason .transcript_mismatch))                            -- 283-284

/-- `_stale`, lines 407-409, for an attempt that is an int. -/
def _stale (s : Doc B D) (attempt : ℤ) : Bool :=
  (s.state = .confirmed || s.state = .started) && Decidable.decide (attempt < (s.attempt : ℤ))

/-- Lines 409-419: is this a signed transcript of an older attempt? -/
def staleTranscript (e : Env B D) (s : Doc B D) (role : Role) (transcript_b64 sig_b64 : B) : Bool :=
  match e.b64d transcript_b64, e.b64d sig_b64 with
  | some raw, some sig =>
    match e.p.decode_transcript raw with
    | some t =>
      Nat.blt t.attempt s.attempt && ((_pk e s role).any fun pk => e.p.verify_raw pk raw sig)
        && _stale s t.attempt
    | none => false
  | _, _ => false

/-- The re-decode at line 454 of a stored transcript. -/
def stored (e : Env B D) (s : Doc B D) (r : Role) : Option (Transcript B) :=
  match (s.per_role r).tx with
  | some td => (e.b64d td.transcript_b64).bind e.p.decode_transcript
  | none => none

/-- The `cal_us` map of line 456: the snapshots. -/
def calMap (s : Doc B D) : Option (Role → Option ℤ) :=
  some fun r => some (((s.per_role r).arm.map (·.cal_us)).getD 0)

/-- Lines 448-462, once the transcript of this request is in `s`. `s0` is the document from the load,
which is what stays if an uncaught error comes up. -/
def afterStore (e : Env B D) (w : World D) (s0 s : Doc B D) : Doc B D × Resp B D :=
  if all2 s.submitted = false then
    let s1 := _save s
    (s1, .accepted s1.state s1.attempt)                                               -- 448-449, 462
  else match stored e s .A, stored e s .B with
  | some ta, some tb =>
    match combine ta tb (calMap s) with
    | .error (.reject rsn) =>
      (_finalize e w s .NOT_NEAR (some rsn) none .rejected none,
        .error 400 (.reason rsn))                                                     -- 454-456
    | .error .zero_division => (s0, .error 500 .internal)                             -- uncaught
    | .ok out =>
      let s1 := match out.verdict with
        | none => _failed e w s out.reason out.by_                                    -- 458-459
        | some v => _finalize e w s v out.reason out.flight_cm .verdict none          -- 460-461
      (s1, .accepted s1.state s1.attempt)                                             -- 462
  | _, _ => (s0, .error 500 .internal)                                                -- 451, uncaught

/-- Lines 430-437: the check of a new transcript. `none` for the raw bytes means bad base64. -/
def checkNew (e : Env B D) (s : Doc B D) (role : Role) (dev : D) (transcript_b64 sig_b64 : B) (pk' : B) :
    Except Raised (B × Transcript B) :=
  match e.b64d transcript_b64, e.b64d sig_b64 with
  | some raw, some sig =>
    let mine := s.per_role role
    let ver := _popt s role
    match check_transcript e.p raw sig role (e.pk dev) pk' s.nonce_hex s.attempt
        (mine.commit.map (·.commit_sha256)) (mine.commit.map (·.rec_))
        (mine.arm.map (·.sample_rate)) ver
        (if ver = 2 then some (_code_commit e s role) else none) with
    | .ok t => .ok (raw, t)
    | .error x => .error x
  | _, _ => .error (.reject .transcript_mismatch)                                     -- 431-432

/-- Lines 444-447: what a checked transcript stores, in memory. -/
def txStore (s : Doc B D) (role : Role) (td : TxData B) : Doc B D :=
  { s with
    per_role := upd s.per_role role { s.per_role role with tx := some td }
    submitted := upd s.submitted role true }

/-- `transcript`, lines 411-465. `meta` is dropped (`spec.md` section 3.3). -/
def transcript (e : Env B D) (w : World D) (s : Doc B D) (role : Role) (dev : D)
    (transcript_b64 sig_b64 : B) : Doc B D × Resp B D :=
  if staleTranscript e s role transcript_b64 sig_b64 = true then
    (s, .error 409 .stale_attempt)                                                    -- 409-419
  else if s.state ≠ .started then (s, .error 409 .bad_state)                          -- 420-421
  else if s.submitted role = true then                                                -- 423
    match (s.per_role role).tx with
    | some td =>
      if td.transcript_b64 = transcript_b64 ∧ td.sig_b64 = sig_b64 then
        (s, .accepted s.state s.attempt)                                              -- 424-425
      else (s, .error 409 .already_submitted)                                         -- 426
    | none => (s, .error 409 .already_submitted)                                      -- unreachable
  else if s.committed role = false then (s, .error 409 .bad_state)                    -- 427-428
  else match _pk e s (OTHER role) with
  | none => (s, .error 500 .internal)                                                 -- unreachable
  | some pk' =>
    match checkNew e s role dev transcript_b64 sig_b64 pk' with
    | .error (.reject rsn) =>
      (_finalize e w s .NOT_NEAR (some rsn) none .rejected (some role),
        .error 400 (.reason rsn))                                                     -- 438-440
    | .error .zero_division => (s, .error 500 .internal)                              -- can't come from the check
    | .ok (raw, t) =>
      let td : TxData B :=
        { transcript_b64 := transcript_b64, sig_b64 := sig_b64
          transcript_sha256 := e.p.sha256 raw, half := t.half
          self_os_delta := t.self_os_delta }                                          -- 444-446
      afterStore e w s (txStore s role td)                                            -- 447

/-- Line 476. -/
def failStore (s : Doc B D) (role : Role) (f : Reason × ℕ) : Doc B D :=
  { s with per_role := upd s.per_role role { s.per_role role with fail_ := some f } }

/-- `fail`, lines 467-480. -/
def fail_ (e : Env B D) (w : World D) (s : Doc B D) (role : Role) (attempt : Arg) (reason : Option Reason) :
    Except (ℕ × Err) (Doc B D) :=
  match reason with
  | none => .error (400, .bad_reason)                                                 -- 465-466
  | some rsn =>
    if rsn ∉ PHONE_REASONS then .error (400, .bad_reason)                             -- 465-466
    else match _int attempt with
    | none => .error (400, .bad_attempt)                                              -- 467-468
    | some n =>
      if _stale s n = true then .error (409, .stale_attempt)                          -- 469
      else if ¬ (s.state = .confirmed ∨ s.state = .started) then
        .error (409, .bad_state)                                                      -- 470-471
      else if n ≠ (s.attempt : ℤ) then .error (400, .bad_attempt)                     -- 472-473
      else if s.submitted role = true then .error (409, .already_submitted)           -- 474-475
      else
        .ok (_failed e w (failStore s role (rsn, w.now)) (some rsn) (some role))                                                     -- 476-477

/-- `view`, lines 656-684, fields in scope. -/
def view (e : Env B D) (w : World D) (s : Doc B D) (role : Role) : ViewBody B D where
  session_id := s.session_id
  seq := s.seq
  state := s.state
  attempt := s.attempt
  role := role
  nonce := if all2 s.confirmed = true then some s.nonce_hex else none
  self_ := (devId s role).map fun d => ⟨d, e.pk d, w.cal d⟩
  partner := (devId s (OTHER role)).map fun d => ⟨d, e.pk d, w.cal d⟩
  confirmed := s.confirmed
  armed := s.armed
  committed := s.committed
  submitted := s.submitted
  popt r := (s.per_role r).arm.map (·.popt)
  t0_ms := s.t0_ms
  result := s.result
  error := s.error
  last_failure := s.last_failure

/-- A handler that returns a document or raises, then a view: `main.py:483-484`, `:509-510`, `:710-711`. -/
def viewOr (e : Env B D) (w : World D) (s : Doc B D) (role : Role) (x : Except (ℕ × Err) (Doc B D)) :
    Doc B D × Resp B D :=
  match x with
  | .ok s' => (s', .view (view e w s' role))
  | .error (st, c) => (s, .error st c)

/-- `result`, lines 482-485. -/
def result (s : Doc B D) : Doc B D × Resp B D :=
  match s.result with
  | none => (s, .error 404 .no_result)
  | some r => (s, .record r)

/-- One member route, after the load and the `member` check (`main.py:471-510`, `:707-711`). -/
def handle (e : Env B D) (w : World D) (s : Doc B D) (role : Role) (dev : D) : Op B → Doc B D × Resp B D
  | .view => (s, .view (view e w s role))
  | .result => result s
  | .confirm => viewOr e w s role (confirm s role)
  | .abort => viewOr e w s role (.ok (abort w s role))
  | .arm a sr rtt p => arm e w s role a sr rtt p
  | .commit c sg => commit e w s role dev c sg
  | .transcript t sg => transcript e w s role dev t sg
  | .fail_ a rsn => viewOr e w s role (fail_ e w s role a rsn)

/-- One request on the stored document `s`: the order of `spec.md` section 3.4. Returns the new stored
document and the response. -/
def step (e : Env B D) (w : World D) (req : Req B D) (s : Doc B D) : Doc B D × Resp B D :=
  match req with
  | .noauth_load => (load e w s, .other)
  | .api json_bad sender shape_bad body =>
    if json_bad = true then (s, .error 400 .bad_request)
    else match sender with
    | none => (s, .error 401 .auth_failed)
    | some dev =>
      if shape_bad = true then (s, .error 400 .bad_request)
      else
        let s1 := load e w s
        match body with
        | .join token => viewOr e w s1 .B (join w s1 dev token)
        | .op o =>
          match role_of s1 dev with
          | none => (s1, .error 403 .not_member)
          | some role => handle e w s1 role dev o

/-- `Reachable e clock s`: the document `s` can be stored after a run from `create`, with `clock` the
last clock read. A step's clock read is never before the last one (A7). -/
inductive Reachable (e : Env B D) : ℕ → Doc B D → Prop
  | create (w : World D) (host : D) (sid nonce : B) (seed token : String) :
      Reachable e w.now (create w host sid nonce seed token).1
  | step {clock : ℕ} {s : Doc B D} (w : World D) (req : Req B D) :
      Reachable e clock s → clock ≤ w.now → Reachable e w.now (step e w req s).1

/-! ## The invariant (M9, and what the other properties need) -/

/-- What an accepted arm leaves behind. -/
def ArmOk (clock : ℕ) (s : Doc B D) (a : ArmData) : Prop :=
  K.SR_MIN ≤ a.sample_rate ∧ a.sample_rate ≤ K.SR_MAX ∧ (a.popt = 1 ∨ a.popt = 2) ∧
    a.armed_ms ≤ clock ∧ ∀ t, s.t0_ms = some t → a.armed_ms + T0_DELAY_MS ≤ t

/-- What an accepted commit leaves behind: its stored strings still decode to a commit that passed. -/
def CommitOk (e : Env B D) (s : Doc B D) (r : Role) (cd : CommitData B) : Prop :=
  ∃ pk raw sig c, _pk e s r = some pk ∧ e.b64d cd.commit_b64 = some raw ∧
    e.b64d cd.commit_sig_b64 = some sig ∧ e.p.decode_commit raw = some c ∧
    e.p.verify_raw pk raw sig = true ∧ c.role = r ∧ c.attempt = s.attempt ∧
    c.nonce = s.nonce_hex ∧ c.version = _popt s r ∧
    cd.commit_sha256 = e.p.sha256 raw ∧ cd.rec_ = c.rec_ ∧
    ∃ t, s.t0_ms = some t ∧ t + K.COMMIT_GATE_MS ≤ cd.committed_ms

/-- What an accepted transcript leaves behind: `check_transcript` passed on its stored strings. -/
def TxOk (e : Env B D) (s : Doc B D) (r : Role) (td : TxData B) : Prop :=
  ∃ pk pk' raw sig t, _pk e s r = some pk ∧ _pk e s (OTHER r) = some pk' ∧
    e.b64d td.transcript_b64 = some raw ∧ e.b64d td.sig_b64 = some sig ∧
    check_transcript e.p raw sig r pk pk' s.nonce_hex s.attempt
      ((s.per_role r).commit.map (·.commit_sha256)) ((s.per_role r).commit.map (·.rec_))
      ((s.per_role r).arm.map (·.sample_rate)) (_popt s r)
      (if _popt s r = 2 then some (_code_commit e s r) else none) = .ok t ∧
    td.half = t.half ∧ td.self_os_delta = t.self_os_delta ∧
    td.transcript_sha256 = e.p.sha256 raw

/-- What a NEAR record stands on. -/
structure NearFacts (e : Env B D) (s : Doc B D) (rc : Record B D) : Prop where
  both : all2 s.submitted = true
  cmb : ∃ ta tb out, stored e s .A = some ta ∧ stored e s .B = some tb ∧
    combine ta tb (calMap s) = .ok out ∧ out.verdict = some .NEAR ∧ rc.flight_cm = out.flight_cm
  time : ∃ t n, s.t0_ms = some t ∧ s.finished_ms = some n ∧ s.created_ms ≤ n ∧
    n ≤ t + K.TRANSCRIPT_DEADLINE_S * 1000 ∧ n - s.created_ms ≤ K.SESSION_MAX_AGE_S * 1000

/-- Everything but one row of the M9 table. `Inv` adds "never all submitted and still started". The
split is there because a transcript briefly has both in, in memory, before it leaves `started`. -/
structure Core (e : Env B D) (clock : ℕ) (s : Doc B D) : Prop where
  attempt_le : s.attempt ≤ 1
  guest_ne : s.guest_device_id ≠ some s.host_device_id
  expires : s.token_expires_ms = s.created_ms + K.JOIN_TOKEN_TTL_S * 1000
  created_le : s.created_ms ≤ clock
  sub_com : ∀ r, s.submitted r = true → s.committed r = true
  com_arm : ∀ r, s.committed r = true → s.armed r = true
  rows : s.attempts.map (·.attempt) = List.range s.attempts.length
  result_iff : s.result.isSome = true ↔ s.state = .done
  arm_iff : ∀ r, s.armed r = true ↔ (s.per_role r).arm.isSome = true
  com_iff : ∀ r, s.committed r = true ↔ (s.per_role r).commit.isSome = true
  sub_iff : ∀ r, s.submitted r = true ↔ (s.per_role r).tx.isSome = true
  live_row : live s.state = true →
    s.attempts.length = s.attempt ∧ s.finished_ms = none ∧ s.error = none
  row_created : s.state = .created →
    s.guest_device_id = none ∧ (∀ r, s.confirmed r = false ∧ s.armed r = false ∧
      s.committed r = false ∧ s.submitted r = false) ∧ s.t0_ms = none ∧ s.attempt = 0
  row_joined : s.state = .joined →
    s.guest_device_id ≠ none ∧ all2 s.confirmed = false ∧ (∀ r, s.armed r = false ∧
      s.committed r = false ∧ s.submitted r = false) ∧ s.t0_ms = none ∧ s.attempt = 0
  row_confirmed : s.state = .confirmed →
    s.guest_device_id ≠ none ∧ all2 s.confirmed = true ∧ all2 s.armed = false ∧
      (∀ r, s.committed r = false ∧ s.submitted r = false) ∧ s.t0_ms = none
  row_started : s.state = .started →
    s.guest_device_id ≠ none ∧ all2 s.confirmed = true ∧ all2 s.armed = true ∧ s.t0_ms ≠ none
  row_done : s.state = .done →
    s.finished_ms ≠ none ∧ s.attempts.length = s.attempt + 1 ∧
      ∃ rc, s.result = some rc ∧ s.error = rc.reason
  row_aborted : s.state = .aborted →
    (s.error = some .aborted ∧ s.finished_ms ≠ none ∧ s.attempts.length = s.attempt + 1) ∨
    (s.error = some .timeout ∧ s.finished_ms = none ∧ s.attempts.length = s.attempt)
  arm_ok : ∀ r a, (s.per_role r).arm = some a → ArmOk clock s a
  com_ok : ∀ r cd, (s.per_role r).commit = some cd → CommitOk e s r cd
  tx_ok : ∀ r td, (s.per_role r).tx = some td → TxOk e s r td
  rec_eq : ∀ rc, s.result = some rc → rc = _record e s rc.verdict rc.reason rc.flight_cm
  near : ∀ rc, s.result = some rc → rc.verdict = .NEAR → NearFacts e s rc
  verdict_row : ∀ row, s.attempts.getLast? = some row → row.outcome = .verdict →
    all2 s.submitted = true

/-- **M9, the full invariant.** See `Core`. -/
structure Inv (e : Env B D) (clock : ℕ) (s : Doc B D) : Prop extends Core e clock s where
  started_not_all : s.state = .started → all2 s.submitted = false

/-! ### Frame lemmas -/

theorem Core.mono {e : Env B D} {c c' : ℕ} {s : Doc B D} (h : Core e c s) (hc : c ≤ c') : Core e c' s :=
  { h with
    created_le := le_trans h.created_le hc
    arm_ok := fun r a ha => by
      obtain ⟨h1, h2, h3, h4, h5⟩ := h.arm_ok r a ha
      exact ⟨h1, h2, h3, le_trans h4 hc, h5⟩ }

theorem Inv.mono {e : Env B D} {c c' : ℕ} {s : Doc B D} (h : Inv e c s) (hc : c ≤ c') : Inv e c' s :=
  { toCore := h.toCore.mono hc, started_not_all := h.started_not_all }

theorem Core.save {e : Env B D} {c : ℕ} {s : Doc B D} (h : Core e c s) : Core e c (_save s) :=
  { attempt_le := h.attempt_le, guest_ne := h.guest_ne, expires := h.expires, created_le := h.created_le
    sub_com := h.sub_com, com_arm := h.com_arm, rows := h.rows, result_iff := h.result_iff
    arm_iff := h.arm_iff, com_iff := h.com_iff, sub_iff := h.sub_iff, live_row := h.live_row
    row_created := h.row_created, row_joined := h.row_joined, row_confirmed := h.row_confirmed
    row_started := h.row_started, row_done := h.row_done, row_aborted := h.row_aborted
    arm_ok := h.arm_ok, com_ok := h.com_ok, tx_ok := h.tx_ok, rec_eq := h.rec_eq
    near := fun rc hr hv => let f := h.near rc hr hv; ⟨f.both, f.cmb, f.time⟩
    verdict_row := h.verdict_row }

theorem Inv.save {e : Env B D} {c : ℕ} {s : Doc B D} (h : Inv e c s) : Inv e c (_save s) :=
  { toCore := h.toCore.save, started_not_all := h.started_not_all }

@[simp] theorem upd_same {α : Type} (f : Role → α) (r : Role) (v : α) : upd f r v r = v := by simp [upd]

@[simp] theorem upd_other {α : Type} (f : Role → α) {r x : Role} (v : α) (h : x ≠ r) : upd f r v x = f x := by
  simp [upd, h]

theorem live_confirmed : live .confirmed = true := rfl
theorem live_started : live .started = true := rfl

/-- A retry leaves a clean `confirmed`. -/
theorem next_attempt_inv {e : Env B D} {c : ℕ} {s : Doc B D} (reason : Option Reason) (by_ : Option Role)
    (h : Core e c s) (hst : s.state = .confirmed ∨ s.state = .started) (ha : s.attempt + 1 < K.MAX_ATTEMPTS) :
    Inv e c (next_attempt s reason by_) := by
  have hl : live s.state = true := by rcases hst with h' | h' <;> simp [h', live]
  obtain ⟨hlen, hfin, herr⟩ := h.live_row hl
  have hres : s.result = none := by
    have := h.result_iff
    rcases hr : s.result with _ | rc
    · rfl
    · have : s.state = .done := this.1 (by simp [hr])
      rcases hst with h' | h' <;> simp [h'] at this
  have hconf : s.guest_device_id ≠ none ∧ all2 s.confirmed = true := by
    rcases hst with h' | h'
    · exact ⟨(h.row_confirmed h').1, (h.row_confirmed h').2.1⟩
    · exact ⟨(h.row_started h').1, (h.row_started h').2.1⟩
  have hrows := h.rows
  refine ⟨⟨?_, h.guest_ne, h.expires, h.created_le, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_⟩, ?_⟩
  all_goals simp [next_attempt, _save, _flags, all2, hres, hfin, herr, hlen, live]
  · simp [K.MAX_ATTEMPTS] at ha; omega
  · rw [hrows, hlen, List.range_succ]
  · exact ⟨hconf.1, by simpa [all2] using hconf.2⟩

/-- A live document has no result. -/
theorem Core.result_none {e : Env B D} {c : ℕ} {s : Doc B D} (h : Core e c s) (hl : s.state ≠ .done) :
    s.result = none := by
  rcases hr : s.result with _ | rc
  · rfl
  · exact absurd (h.result_iff.1 (by simp [hr])) hl

/-- `_finalize` leaves a `done` document that keeps the invariant. `hv` and `hn` are what its callers
must bring: an outcome `verdict` needs both transcripts in, and NEAR needs the `combine` result and
fresh timing. -/
theorem finalize_inv {e : Env B D} {c : ℕ} {s : Doc B D} {w : World D} {verdict : Verdict}
    {reason : Option Reason} {flight : Option ℚ} {outcome : Outcome} {by_ : Option Role}
    (h : Core e c s) (hst : s.state = .confirmed ∨ s.state = .started) (hcw : c ≤ w.now)
    (hv : outcome = .verdict → all2 s.submitted = true)
    (hn : verdict = .NEAR → all2 s.submitted = true ∧
      (∃ ta tb out, stored e s .A = some ta ∧ stored e s .B = some tb ∧
        combine ta tb (calMap s) = .ok out ∧ out.verdict = some .NEAR ∧ flight = out.flight_cm) ∧
      ∃ t, s.t0_ms = some t ∧ w.now ≤ t + K.TRANSCRIPT_DEADLINE_S * 1000 ∧
        w.now - s.created_ms ≤ K.SESSION_MAX_AGE_S * 1000) :
    Inv e w.now (_finalize e w s verdict reason flight outcome by_) := by
  have hl : live s.state = true := by rcases hst with h' | h' <;> simp [h', live]
  obtain ⟨hlen, hfin, herr⟩ := h.live_row hl
  have hm := h.mono hcw
  refine ⟨{ attempt_le := h.attempt_le, guest_ne := h.guest_ne, expires := h.expires
            created_le := hm.created_le, sub_com := h.sub_com, com_arm := h.com_arm
            rows := ?_, result_iff := ?_, arm_iff := h.arm_iff, com_iff := h.com_iff, sub_iff := h.sub_iff
            live_row := ?_, row_created := ?_, row_joined := ?_, row_confirmed := ?_, row_started := ?_
            row_done := ?_, row_aborted := ?_, arm_ok := hm.arm_ok, com_ok := h.com_ok, tx_ok := h.tx_ok
            rec_eq := ?_, near := ?_, verdict_row := ?_ }, ?_⟩
  · simp [_finalize, _save, h.rows, List.range_succ, hlen]
  · simp [_finalize, _save]
  · simp [_finalize, _save, live]
  · simp [_finalize, _save]
  · simp [_finalize, _save]
  · simp [_finalize, _save]
  · simp [_finalize, _save]
  · simp [_finalize, _save, hlen, _record]
  · simp [_finalize, _save]
  · intro rc hrc
    simp only [_finalize, _save, Option.some.injEq] at hrc
    subst hrc
    rfl
  · intro rc hrc hvv
    simp only [_finalize, _save, Option.some.injEq] at hrc
    subst hrc
    obtain ⟨h1, ⟨ta, tb, out, h2, h3, h4, h5, h6⟩, t, h7, h8, h9⟩ := hn hvv
    exact ⟨h1, ⟨ta, tb, out, h2, h3, h4, h5, h6⟩, ⟨t, w.now, h7, rfl, hm.created_le, h8, h9⟩⟩
  · intro row hrow hout
    simp [_finalize, _save, List.getLast?_append] at hrow
    subst hrow
    exact hv hout
  · simp [_finalize, _save]

/-- `_failed` keeps the invariant, from a live state that may have all transcripts in. -/
theorem failed_inv {e : Env B D} {c : ℕ} {s : Doc B D} {w : World D} {reason : Option Reason} {by_ : Option Role}
    (h : Core e c s) (hst : s.state = .confirmed ∨ s.state = .started) (hcw : c ≤ w.now) :
    Inv e w.now (_failed e w s reason by_) := by
  unfold _failed
  split
  · rename_i hc
    simp only [Bool.and_eq_true, Nat.blt_eq] at hc
    exact next_attempt_inv reason by_ (h.mono hcw) hst hc.2
  · exact finalize_inv h hst hcw (by simp) (by simp)

/-- A timeout from `_expire`, rows E1 and E2. -/
theorem timeout_inv {e : Env B D} {c : ℕ} {s : Doc B D} (h : Core e c s) (hl : live s.state = true) :
    Inv e c (_save { s with state := .aborted, error := some .timeout }) := by
  obtain ⟨hlen, hfin, herr⟩ := h.live_row hl
  have hres : s.result = none := h.result_none (by
    intro h'; simp [h', live] at hl)
  refine ⟨{ attempt_le := h.attempt_le, guest_ne := h.guest_ne, expires := h.expires
            created_le := h.created_le, sub_com := h.sub_com, com_arm := h.com_arm
            rows := h.rows, result_iff := ?_, arm_iff := h.arm_iff, com_iff := h.com_iff, sub_iff := h.sub_iff
            live_row := ?_, row_created := ?_, row_joined := ?_, row_confirmed := ?_, row_started := ?_
            row_done := ?_, row_aborted := ?_, arm_ok := h.arm_ok, com_ok := h.com_ok, tx_ok := h.tx_ok
            rec_eq := ?_, near := ?_, verdict_row := h.verdict_row }, ?_⟩
  all_goals simp [_save, live, hres, hfin, hlen]

/-- `_expire` keeps the invariant, and moves the clock. -/
theorem expire_inv {e : Env B D} {c : ℕ} {s : Doc B D} {w : World D} (h : Inv e c s) (hcw : c ≤ w.now) :
    Inv e w.now (_expire e w s) := by
  have hm := h.mono hcw
  unfold _expire
  split
  · rename_i hc
    exact timeout_inv hm.toCore (by simp [hc.1, live])
  · split
    · rename_i hc
      exact timeout_inv hm.toCore hc.1
    · split
      · rename_i hc
        exact failed_inv h.toCore (Or.inr hc.1) hcw
      · exact hm

/-- After the load, a session still `started` is on time: the deadlines of lines 117 and 120 are strict,
so both edges pass. This is the first half of M11. -/
theorem expire_fresh {e : Env B D} {c : ℕ} {s : Doc B D} {w : World D} (h : Inv e c s)
    (hst : (_expire e w s).state = .started) :
    ∃ t, (_expire e w s).t0_ms = some t ∧ w.now ≤ t + K.TRANSCRIPT_DEADLINE_S * 1000 ∧
      w.now - (_expire e w s).created_ms ≤ K.SESSION_MAX_AGE_S * 1000 := by
  unfold _expire at hst ⊢
  split at hst
  · simp [_save] at hst
  · split at hst
    · simp [_save] at hst
    · split at hst
      · rename_i h1 h2 h3
        exfalso
        unfold _failed at hst
        split at hst
        · simp [next_attempt, _save] at hst
        · simp [_finalize, _save] at hst
      · rename_i h1 h2 h3
        rw [ite_eq_right h1, ite_eq_right h2, ite_eq_right h3]
        obtain ⟨_, _, _, ht⟩ := h.row_started hst
        rcases ht' : s.t0_ms with _ | t
        · exact absurd ht' ht
        · refine ⟨t, rfl, ?_, ?_⟩
          · by_contra hh
            apply h3
            refine ⟨hst, ?_⟩
            simp [ht'] at hh ⊢
            omega
          · by_contra hh
            apply h2
            exact ⟨by simp [hst, live], by omega⟩

/-! ### `CommitOk` and `TxOk` read only a few fields -/

theorem CommitOk_same {e : Env B D} {s s' : Doc B D} {r : Role} {cd : CommitData B}
    (hn : s'.nonce_hex = s.nonce_hex) (ha : s'.attempt = s.attempt) (hh : s'.host_device_id = s.host_device_id)
    (hg : s'.guest_device_id = s.guest_device_id) (ht : s'.t0_ms = s.t0_ms)
    (harm : (s'.per_role r).arm = (s.per_role r).arm) (h : CommitOk e s r cd) : CommitOk e s' r cd := by
  have hp : ∀ r, _pk e s' r = _pk e s r := by intro r; cases r <;> simp [_pk, devId, hh, hg]
  have hq : _popt s' r = _popt s r := by simp [_popt, harm]
  simpa only [CommitOk, hp, hq, hn, ha, ht] using h

theorem TxOk_same {e : Env B D} {s s' : Doc B D} {r : Role} {td : TxData B}
    (hn : s'.nonce_hex = s.nonce_hex) (ha : s'.attempt = s.attempt) (hh : s'.host_device_id = s.host_device_id)
    (hg : s'.guest_device_id = s.guest_device_id) (hsd : s'.seed_hex = s.seed_hex)
    (harm : (s'.per_role r).arm = (s.per_role r).arm) (hcm : (s'.per_role r).commit = (s.per_role r).commit)
    (h : TxOk e s r td) : TxOk e s' r td := by
  have hp : ∀ r, _pk e s' r = _pk e s r := by intro r; cases r <;> simp [_pk, devId, hh, hg]
  have hq : _popt s' r = _popt s r := by simp [_popt, harm]
  have hc : _code_commit e s' r = _code_commit e s r := by simp [_code_commit, _code, harm, hsd, ha]
  simpa only [TxOk, hp, hq, hc, hn, ha, harm, hcm] using h

theorem role_of_pk {e : Env B D} {s : Doc B D} {d : D} {r : Role} (h : role_of s d = some r) :
    _pk e s r = some (e.pk d) := by
  unfold role_of at h
  split at h
  · simp at h; subst h; simp [_pk, devId, *]
  · split at h
    · simp at h; subst h; simp [_pk, devId, ← ‹some d = _›]
    · simp at h

theorem other_ne (r : Role) : OTHER r ≠ r := by cases r <;> simp [OTHER]

theorem eq_or_other (r x : Role) : x = r ∨ x = OTHER r := by cases r <;> cases x <;> simp [OTHER]

theorem Core.arm_none {e : Env B D} {c : ℕ} {s : Doc B D} {r : Role} (h : Core e c s) (hf : s.armed r = false) :
    (s.per_role r).arm = none := by
  have := h.arm_iff r
  rcases hx : (s.per_role r).arm with _ | a
  · rfl
  · simp [hx, hf] at this

theorem Core.com_none {e : Env B D} {c : ℕ} {s : Doc B D} {r : Role} (h : Core e c s) (hf : s.committed r = false) :
    (s.per_role r).commit = none := by
  have := h.com_iff r
  rcases hx : (s.per_role r).commit with _ | a
  · rfl
  · simp [hx, hf] at this

theorem Core.tx_none {e : Env B D} {c : ℕ} {s : Doc B D} {r : Role} (h : Core e c s) (hf : s.submitted r = false) :
    (s.per_role r).tx = none := by
  have := h.sub_iff r
  rcases hx : (s.per_role r).tx with _ | a
  · rfl
  · simp [hx, hf] at this

/-- **Row `join`.** -/
theorem join_inv {e : Env B D} {c : ℕ} {s s' : Doc B D} {w : World D} {d : D} {tok : String}
    (h : Inv e c s) (hj : join w s d tok = .ok s') : Inv e c s' := by
  unfold join at hj
  split at hj
  · simp at hj
  rename_i h1
  split at hj
  · simp at hj
  rename_i h2
  split at hj
  · simp at hj
  split at hj
  · simp at hj
  rename_i h4
  simp only [Except.ok.injEq] at hj
  subst hj
  have hs : s.state = .created := by
    by_contra hh; exact h4 (Or.inl hh)
  obtain ⟨hg, hf, ht, ha⟩ := h.row_created hs
  have hres : s.result = none := h.result_none (by simp [hs])
  obtain ⟨hlen, hfin, herr⟩ := h.live_row (by simp [hs, live])
  refine ⟨{ attempt_le := h.attempt_le, guest_ne := ?_, expires := h.expires
            created_le := h.created_le, sub_com := h.sub_com, com_arm := h.com_arm
            rows := h.rows, result_iff := ?_, arm_iff := h.arm_iff, com_iff := h.com_iff, sub_iff := h.sub_iff
            live_row := ?_, row_created := ?_, row_joined := ?_, row_confirmed := ?_, row_started := ?_
            row_done := ?_, row_aborted := ?_, arm_ok := ?_, com_ok := ?_, tx_ok := ?_
            rec_eq := ?_, near := ?_, verdict_row := ?_ }, ?_⟩
  · simpa [_save] using h1
  · simp [_save, hres]
  · simp [_save, hlen, hfin, herr, ha]
  · simp [_save]
  · intro _
    simp [_save, all2, hf, ht, ha]
  · simp [_save]
  · simp [_save]
  · simp [_save]
  · simp [_save]
  · intro r a ha'
    have : (s.per_role r).arm = none := h.arm_none (hf r).2.1
    simp [_save, this] at ha'
  · intro r a ha'
    have : (s.per_role r).commit = none := h.com_none (hf r).2.2.1
    simp [_save, this] at ha'
  · intro r a ha'
    have : (s.per_role r).tx = none := h.tx_none (hf r).2.2.2
    simp [_save, this] at ha'
  · simp [_save, hres]
  · simp [_save, hres]
  · intro row hrow hout
    have : s.attempts = [] := by
      apply List.length_eq_zero_iff.1; rw [hlen, ha]
    simp [_save, this] at hrow
  · simp [_save]

/-- **Row `confirm`.** -/
theorem confirm_inv {e : Env B D} {c : ℕ} {s s' : Doc B D} {role : Role}
    (h : Inv e c s) (hj : confirm s role = .ok s') : Inv e c s' := by
  unfold confirm at hj
  split at hj
  · simp only [Except.ok.injEq] at hj; subst hj; exact h
  split at hj
  · simp at hj
  rename_i h2
  have hs : s.state = .joined := by simpa using h2
  simp only [Except.ok.injEq] at hj
  subst hj
  obtain ⟨hg, hc, hf, ht, ha⟩ := h.row_joined hs
  have hres : s.result = none := h.result_none (by simp [hs])
  obtain ⟨hlen, hfin, herr⟩ := h.live_row (by simp [hs, live])
  have hnone : s.attempts = [] := by
    apply List.length_eq_zero_iff.1; rw [hlen, ha]
  by_cases hall : all2 (upd s.confirmed role true) = true
  · simp only [hall, ite_true]
    refine ⟨{ attempt_le := h.attempt_le, guest_ne := h.guest_ne, expires := h.expires
              created_le := h.created_le, sub_com := h.sub_com, com_arm := h.com_arm
              rows := h.rows, result_iff := ?_, arm_iff := h.arm_iff, com_iff := h.com_iff, sub_iff := h.sub_iff
              live_row := ?_, row_created := ?_, row_joined := ?_, row_confirmed := ?_, row_started := ?_
              row_done := ?_, row_aborted := ?_, arm_ok := fun r a ha' => ?_, com_ok := fun r a ha' => ?_, tx_ok := fun r a ha' => ?_
              rec_eq := ?_, near := ?_, verdict_row := ?_ }, ?_⟩
    · simp [_save, hres]
    · simp [_save, hlen, hfin, herr]
    · simp [_save]
    · simp [_save]
    · intro _
      exact ⟨hg, hall, by show all2 s.armed = false; simp [all2, (hf .A).1], fun r => ⟨(hf r).2.1, (hf r).2.2⟩, ht⟩
    · simp [_save]
    · simp [_save]
    · simp [_save]
    · have : (s.per_role r).arm = none := h.arm_none (hf r).1
      simp [_save, this] at ha'
    · have : (s.per_role r).commit = none := h.com_none (hf r).2.1
      simp [_save, this] at ha'
    · have : (s.per_role r).tx = none := h.tx_none (hf r).2.2
      simp [_save, this] at ha'
    · simp [_save, hres]
    · simp [_save, hres]
    · simp [_save, hnone]
    · simp [_save]
  · simp only [Bool.not_eq_true] at hall
    simp only [hall, Bool.false_eq_true, ite_false]
    refine ⟨{ attempt_le := h.attempt_le, guest_ne := h.guest_ne, expires := h.expires
              created_le := h.created_le, sub_com := h.sub_com, com_arm := h.com_arm
              rows := h.rows, result_iff := ?_, arm_iff := h.arm_iff, com_iff := h.com_iff, sub_iff := h.sub_iff
              live_row := ?_, row_created := ?_, row_joined := ?_, row_confirmed := ?_, row_started := ?_
              row_done := ?_, row_aborted := ?_, arm_ok := fun r a ha' => ?_, com_ok := fun r a ha' => ?_, tx_ok := fun r a ha' => ?_
              rec_eq := ?_, near := ?_, verdict_row := ?_ }, ?_⟩
    · simp [_save, hres, hs]
    · simp [_save, hlen, hfin, herr, hs, live]
    · simp [_save, hs]
    · intro _
      simp only [_save]
      exact ⟨hg, hall, hf, ht, ha⟩
    · simp [_save, hs]
    · simp [_save, hs]
    · simp [_save, hs]
    · simp [_save, hs]
    · have : (s.per_role r).arm = none := h.arm_none (hf r).1
      simp [_save, this] at ha'
    · have : (s.per_role r).commit = none := h.com_none (hf r).2.1
      simp [_save, this] at ha'
    · have : (s.per_role r).tx = none := h.tx_none (hf r).2.2
      simp [_save, this] at ha'
    · simp [_save, hres]
    · simp [_save, hres]
    · simp [_save, hnone]
    · simp [_save, hs]

/-- **Row `abort`.** -/
theorem abort_inv {e : Env B D} {c : ℕ} {s : Doc B D} {w : World D} {role : Role}
    (h : Inv e c s) (hcw : c ≤ w.now) : Inv e w.now (abort w s role) := by
  have hm := h.mono hcw
  unfold abort
  split
  · exact hm
  rename_i h1
  have hl : live s.state = true := by
    simp only [not_or] at h1
    rcases hst : s.state <;> simp [hst, live] at h1 ⊢
  have hnd : s.state ≠ .done := fun h' => h1 (Or.inl h')
  have hres : s.result = none := h.result_none hnd
  obtain ⟨hlen, hfin, herr⟩ := h.live_row hl
  refine ⟨{ attempt_le := h.attempt_le, guest_ne := h.guest_ne, expires := h.expires
            created_le := hm.created_le, sub_com := h.sub_com, com_arm := h.com_arm
            rows := ?_, result_iff := ?_, arm_iff := h.arm_iff, com_iff := h.com_iff, sub_iff := h.sub_iff
            live_row := ?_, row_created := ?_, row_joined := ?_, row_confirmed := ?_, row_started := ?_
            row_done := ?_, row_aborted := ?_, arm_ok := hm.arm_ok, com_ok := h.com_ok, tx_ok := h.tx_ok
            rec_eq := ?_, near := ?_, verdict_row := ?_ }, ?_⟩
  · simp [_save, h.rows, List.range_succ, hlen]
  all_goals simp [_save, hres, hlen, live, List.getLast?_append]

theorem srArg_range {a : Arg} {sr : ℕ} (h : srArg a = some sr) : K.SR_MIN ≤ sr ∧ sr ≤ K.SR_MAX := by
  unfold srArg at h
  split at h
  · split at h
    · rename_i n hc
      simp only [Option.some.injEq] at h
      subst h
      omega
    · simp at h
  · simp at h

theorem poptArg_vals {a : Arg} {v : ℕ} (h : poptArg a = some v) : v = 1 ∨ v = 2 := by
  unfold poptArg at h
  split at h <;> simp at h <;> omega

/-- **Row `arm`.** Only the path that stores anything needs work. The others return the document. -/
theorem arm_inv {e : Env B D} {c : ℕ} {s : Doc B D} {w : World D} {role : Role} {a sr' : Arg}
    {rtt : Option ℚ} {pv : Arg} (h : Inv e c s) (hcw : c ≤ w.now) :
    Inv e w.now (arm e w s role a sr' rtt pv).1 := by
  have hm := h.mono hcw
  unfold arm
  split
  · exact hm
  split
  · exact hm
  split
  · exact hm
  rename_i sr hsr
  split
  · exact hm
  split
  · exact hm
  rename_i v hv
  split
  · split
    · exact hm
    · split
      · exact hm
      · exact hm
  split
  · exact hm
  rename_i h5 h6
  have hs : s.state = .confirmed := by simpa using h6
  obtain ⟨hg, hc, hna, hf, ht⟩ := h.row_confirmed hs
  have hres : s.result = none := h.result_none (by simp [hs])
  obtain ⟨hlen, hfin, herr⟩ := h.live_row (by simp [hs, live])
  obtain ⟨hr1, hr2⟩ := srArg_range hsr
  have hvv := poptArg_vals hv
  have hnotarmed : s.armed role = false := by simpa using h5
  have hcomn : ∀ x, (s.per_role x).commit = none := fun x => h.com_none (hf x).1
  have htxn : ∀ x, (s.per_role x).tx = none := fun x => h.tx_none (hf x).2
  dsimp only
  have hflags : ∀ x, x ≠ role → (upd s.armed role true) x = s.armed x := fun x hx => upd_other _ _ hx
  by_cases hall : all2 (upd s.armed role true) = true
  · simp only [hall, ite_true]
    refine ⟨{ attempt_le := h.attempt_le, guest_ne := h.guest_ne, expires := h.expires
              created_le := hm.created_le, sub_com := h.sub_com, com_arm := ?_
              rows := h.rows, result_iff := ?_, arm_iff := ?_, com_iff := ?_, sub_iff := ?_
              live_row := ?_, row_created := ?_, row_joined := ?_, row_confirmed := ?_, row_started := ?_
              row_done := ?_, row_aborted := ?_, arm_ok := ?_, com_ok := ?_, tx_ok := ?_
              rec_eq := ?_, near := ?_, verdict_row := ?_ }, ?_⟩
    · intro r hr
      simp [_save, (hf r).1] at hr
    · simp [_save, hres]
    · intro r
      by_cases hx : r = role
      · subst hx; simp [_save]
      · simpa [_save, hx, upd] using h.arm_iff r
    · intro r
      by_cases hx : r = role
      · subst hx; simp [_save, (hf r).1]
      · simpa [_save, hx, upd] using h.com_iff r
    · intro r
      by_cases hx : r = role
      · subst hx; simp [_save, (hf r).2]
      · simpa [_save, hx, upd] using h.sub_iff r
    · simp [_save, hlen, hfin, herr, live]
    · simp [_save]
    · simp [_save]
    · simp [_save]
    · intro _
      simp only [_save]
      exact ⟨hg, hc, hall, by simp⟩
    · simp [_save]
    · simp [_save]
    · intro r a' ha'
      by_cases hx : r = role
      · subst hx
        simp [_save] at ha'
        subst ha'
        refine ⟨hr1, hr2, hvv, le_refl _, ?_⟩
        intro t ht'
        simp [_save] at ht'
        show w.now + T0_DELAY_MS ≤ t
        omega
      · simp [_save, hx, upd] at ha'
        obtain ⟨a1, a2, a3, a4, a5⟩ := h.arm_ok r a' ha'
        refine ⟨a1, a2, a3, le_trans a4 hcw, ?_⟩
        intro t ht'
        simp [_save] at ht'
        have := le_trans a4 hcw
        omega
    · intro r cd hcd
      by_cases hx : r = role
      · subst hx; simp [_save] at hcd
      · simp [_save, hx, upd, hcomn] at hcd
    · intro r td htd
      by_cases hx : r = role
      · subst hx; simp [_save] at htd
      · simp [_save, hx, upd, htxn] at htd
    · simp [_save, hres]
    · simp [_save, hres]
    · exact fun row hrow hout => absurd (h.verdict_row row hrow hout) (by
        simp [all2, (hf .A).2])
    · intro _
      simp [_save, all2, (hf .A).2]
  · simp only [Bool.not_eq_true] at hall
    simp only [hall, Bool.false_eq_true, ite_false]
    refine ⟨{ attempt_le := h.attempt_le, guest_ne := h.guest_ne, expires := h.expires
              created_le := hm.created_le, sub_com := h.sub_com, com_arm := ?_
              rows := h.rows, result_iff := ?_, arm_iff := ?_, com_iff := ?_, sub_iff := ?_
              live_row := ?_, row_created := ?_, row_joined := ?_, row_confirmed := ?_, row_started := ?_
              row_done := ?_, row_aborted := ?_, arm_ok := ?_, com_ok := ?_, tx_ok := ?_
              rec_eq := ?_, near := ?_, verdict_row := ?_ }, ?_⟩
    · intro r hr
      simp [_save, (hf r).1] at hr
    · simp [_save, hres, hs]
    · intro r
      by_cases hx : r = role
      · subst hx; simp [_save]
      · simpa [_save, hx, upd] using h.arm_iff r
    · intro r
      by_cases hx : r = role
      · subst hx; simp [_save, (hf r).1]
      · simpa [_save, hx, upd] using h.com_iff r
    · intro r
      by_cases hx : r = role
      · subst hx; simp [_save, (hf r).2]
      · simpa [_save, hx, upd] using h.sub_iff r
    · simp [_save, hlen, hfin, herr, live, hs]
    · simp [_save, hs]
    · simp [_save, hs]
    · intro _
      simp only [_save]
      exact ⟨hg, hc, hall, hf, ht⟩
    · simp [_save, hs]
    · simp [_save, hs]
    · simp [_save, hs]
    · intro r a' ha'
      by_cases hx : r = role
      · subst hx
        simp [_save] at ha'
        subst ha'
        refine ⟨hr1, hr2, hvv, le_refl _, ?_⟩
        intro t ht'
        simp [_save, ht] at ht'
      · simp [_save, hx, upd] at ha'
        obtain ⟨a1, a2, a3, a4, a5⟩ := h.arm_ok r a' ha'
        refine ⟨a1, a2, a3, le_trans a4 hcw, ?_⟩
        intro t ht'
        simp [_save, ht] at ht'
    · intro r cd hcd
      by_cases hx : r = role
      · subst hx; simp [_save] at hcd
      · simp [_save, hx, upd, hcomn] at hcd
    · intro r td htd
      by_cases hx : r = role
      · subst hx; simp [_save] at htd
      · simp [_save, hx, upd, htxn] at htd
    · simp [_save, hres]
    · simp [_save, hres]
    · exact fun row hrow hout => absurd (h.verdict_row row hrow hout) (by
        simp [all2, (hf .A).2])
    · simp [_save, hs]

/-- **Row `commit`**, the path that stores. -/
theorem commitStore_inv {e : Env B D} {c : ℕ} {s : Doc B D} {role : Role} {cd : CommitData B}
    (h : Inv e c s) (hs : s.state = .started) (hna : s.committed role = false) (hok : CommitOk e s role cd) :
    Inv e c (commitStore s role cd) := by
  obtain ⟨hg, hc, ha, ht⟩ := h.row_started hs
  have hres : s.result = none := h.result_none (by simp [hs])
  obtain ⟨hlen, hfin, herr⟩ := h.live_row (by simp [hs, live])
  have harm : ∀ x, ((commitStore s role cd).per_role x).arm = (s.per_role x).arm := by
    intro x; by_cases hx : x = role
    · subst hx; simp [commitStore, _save]
    · simp [commitStore, _save, upd, hx]
  have htx : ∀ x, ((commitStore s role cd).per_role x).tx = (s.per_role x).tx := by
    intro x; by_cases hx : x = role
    · subst hx; simp [commitStore, _save]
    · simp [commitStore, _save, upd, hx]
  have hnsub : s.submitted role = false := by
    rcases hx : s.submitted role with _ | _
    · rfl
    · have := h.sub_com role hx; simp [this] at hna
  have harmed : ∀ r, s.armed r = true := by
    intro r; simp [all2] at ha; cases r
    · exact ha.1
    · exact ha.2
  refine ⟨{ attempt_le := h.attempt_le, guest_ne := h.guest_ne, expires := h.expires
            created_le := h.created_le, sub_com := ?_, com_arm := ?_
            rows := h.rows, result_iff := ?_, arm_iff := ?_, com_iff := ?_, sub_iff := ?_
            live_row := ?_, row_created := ?_, row_joined := ?_, row_confirmed := ?_, row_started := ?_
            row_done := ?_, row_aborted := ?_, arm_ok := ?_, com_ok := ?_, tx_ok := ?_
            rec_eq := ?_, near := ?_, verdict_row := ?_ }, ?_⟩
  · intro r hr
    have hr' : s.submitted r = true := hr
    by_cases hx : r = role
    · subst hx; simp [hnsub] at hr'
    · simpa [commitStore, _save, upd, hx] using h.sub_com r hr'
  · intro r _
    exact harmed r
  · simp [commitStore, _save, hres, hs]
  · intro r; rw [harm]; exact h.arm_iff r
  · intro r
    by_cases hx : r = role
    · subst hx; simp [commitStore, _save]
    · simpa [commitStore, _save, upd, hx] using h.com_iff r
  · intro r; rw [htx]; exact h.sub_iff r
  · simp [commitStore, _save, hs, hlen, hfin, herr, live]
  · simp [commitStore, _save, hs]
  · simp [commitStore, _save, hs]
  · simp [commitStore, _save, hs]
  · intro _
    exact ⟨hg, hc, ha, ht⟩
  · simp [commitStore, _save, hs]
  · simp [commitStore, _save, hs]
  · intro r a ha'
    rw [harm] at ha'
    exact h.arm_ok r a ha'
  · intro r cd' hcd
    by_cases hx : r = role
    · subst hx
      simp [commitStore, _save] at hcd
      subst hcd
      exact CommitOk_same (s := s) rfl rfl rfl rfl rfl (harm r) hok
    · have : (s.per_role r).commit = some cd' := by simpa [commitStore, _save, upd, hx] using hcd
      exact CommitOk_same (s := s) rfl rfl rfl rfl rfl (harm r) (h.com_ok r cd' this)
  · intro r td htd
    by_cases hx : r = role
    · subst hx
      rw [htx, h.tx_none hnsub] at htd
      simp at htd
    · have : (s.per_role r).tx = some td := by rw [htx] at htd; exact htd
      have hcm : ((commitStore s role cd).per_role r).commit = (s.per_role r).commit := by
        simp [commitStore, _save, upd, hx]
      exact TxOk_same (s := s) rfl rfl rfl rfl rfl (harm r) hcm (h.tx_ok r td this)
  · simp [commitStore, _save, hres]
  · simp [commitStore, _save, hres]
  · exact h.verdict_row
  · intro _; exact h.started_not_all hs

/-- **Row `commit`.** -/
theorem commit_inv {e : Env B D} {c : ℕ} {s : Doc B D} {w : World D} {role : Role} {dev : D} {cb sb : B}
    (h : Inv e c s) (hcw : c ≤ w.now) (hr : role_of s dev = some role) :
    Inv e w.now (commit e w s role dev cb sb).1 := by
  have hm := h.mono hcw
  unfold commit
  split
  · exact hm
  rename_i h0
  have hs : s.state = .started := by simpa using h0
  split
  · rename_i raw sig hb1 hb2
    split
    · exact hm
    rename_i cm hdec
    split
    · exact hm
    rename_i h3
    split
    · exact hm
    rename_i h4
    split
    · exact hm
    rename_i h5
    split
    · split
      · exact hm
      · exact hm
    rename_i h6
    split
    · exact hm
    rename_i h7
    apply commitStore_inv hm hs (by simpa using h6)
    obtain ⟨_, _, _, ht⟩ := h.row_started hs
    rcases ht' : s.t0_ms with _ | t
    · exact absurd ht' ht
    simp only [not_or, not_not, ne_eq] at h4 h5
    refine ⟨e.pk dev, raw, sig, cm, role_of_pk hr, hb1, hb2, hdec, by simpa using h3, h4.1, h4.2.1, h4.2.2, h5, rfl, rfl, t, ht', ?_⟩
    simp only [ht', Option.getD_some, not_lt] at h7
    exact h7
  · exact hm

/-- `txStore` keeps everything but "not all submitted". -/
theorem txStore_core {e : Env B D} {c : ℕ} {s : Doc B D} {role : Role} {td : TxData B}
    (h : Inv e c s) (hs : s.state = .started) (hnsub : s.submitted role = false)
    (hcom : s.committed role = true) (hok : TxOk e s role td) :
    Core e c (txStore s role td) := by
  obtain ⟨hg, hc, ha, ht⟩ := h.row_started hs
  have hres : s.result = none := h.result_none (by simp [hs])
  obtain ⟨hlen, hfin, herr⟩ := h.live_row (by simp [hs, live])
  have hna := h.started_not_all hs
  have harm : ∀ x, ((txStore s role td).per_role x).arm = (s.per_role x).arm := by
    intro x; by_cases hx : x = role
    · subst hx; simp [txStore]
    · simp [txStore, upd, hx]
  have hcm : ∀ x, ((txStore s role td).per_role x).commit = (s.per_role x).commit := by
    intro x; by_cases hx : x = role
    · subst hx; simp [txStore]
    · simp [txStore, upd, hx]
  exact { attempt_le := h.attempt_le, guest_ne := h.guest_ne, expires := h.expires
          created_le := h.created_le
          sub_com := by
            intro r hr
            by_cases hx : r = role
            · subst hx; exact hcom
            · exact h.sub_com r (by simpa [txStore, upd, hx] using hr)
          com_arm := h.com_arm
          rows := h.rows
          result_iff := h.result_iff
          arm_iff := by intro r; rw [harm]; exact h.arm_iff r
          com_iff := by intro r; rw [hcm]; exact h.com_iff r
          sub_iff := by
            intro r
            by_cases hx : r = role
            · subst hx; simp [txStore]
            · simpa [txStore, upd, hx] using h.sub_iff r
          live_row := h.live_row
          row_created := by
            intro h'; simp [txStore, hs] at h'
          row_joined := by
            intro h'; simp [txStore, hs] at h'
          row_confirmed := by
            intro h'; simp [txStore, hs] at h'
          row_started := fun h' => ⟨hg, hc, ha, ht⟩
          row_done := h.row_done, row_aborted := h.row_aborted
          arm_ok := by
            intro r a ha'
            rw [harm] at ha'
            exact h.arm_ok r a ha'
          com_ok := by
            intro r cd hcd
            rw [hcm] at hcd
            exact CommitOk_same (s := s) rfl rfl rfl rfl rfl (harm r) (h.com_ok r cd hcd)
          tx_ok := by
            intro r td' htd
            by_cases hx : r = role
            · subst hx
              simp [txStore] at htd
              subst htd
              exact TxOk_same (s := s) rfl rfl rfl rfl rfl (harm r) (hcm r) hok
            · have : (s.per_role r).tx = some td' := by simpa [txStore, upd, hx] using htd
              exact TxOk_same (s := s) rfl rfl rfl rfl rfl (harm r) (hcm r) (h.tx_ok r td' this)
          rec_eq := by simp [txStore, hres]
          near := by simp [txStore, hres]
          verdict_row := by
            intro row hrow hout
            have := h.verdict_row row hrow hout
            simp [this] at hna }

/-- Lines 448-462 keep the invariant. This is where NEAR is made: `hfresh` is the timing from the
load, and the `combine` result is at hand. -/
theorem afterStore_inv {e : Env B D} {s0 s : Doc B D} {w : World D}
    (h0 : Inv e w.now s0) (h : Core e w.now s) (hs : s.state = .started)
    (hfresh : ∃ t, s.t0_ms = some t ∧ w.now ≤ t + K.TRANSCRIPT_DEADLINE_S * 1000 ∧
      w.now - s.created_ms ≤ K.SESSION_MAX_AGE_S * 1000) :
    Inv e w.now (afterStore e w s0 s).1 := by
  unfold afterStore
  split
  · rename_i hall
    exact { toCore := h.save, started_not_all := fun _ => hall }
  rename_i hall
  have hall' : all2 s.submitted = true := by simpa using hall
  split
  · rename_i ta tb h1 h2
    split
    · rename_i rsn hc
      exact finalize_inv h (Or.inr hs) (le_refl _) (by simp) (by simp)
    · exact h0
    · rename_i out hc
      split
      · exact failed_inv h (Or.inr hs) (le_refl _)
      · rename_i v hv
        apply finalize_inv h (Or.inr hs) (le_refl _) (fun _ => hall')
        intro hvn
        subst hvn
        exact ⟨hall', ⟨ta, tb, out, h1, h2, hc, hv, rfl⟩, hfresh⟩
  · exact h0

theorem checkNew_ok {e : Env B D} {s : Doc B D} {role : Role} {dev : D} {tb sb pk' raw : B} {t : Transcript B}
    (hc : checkNew e s role dev tb sb pk' = .ok (raw, t)) (hr : role_of s dev = some role)
    (hp : _pk e s (OTHER role) = some pk') :
    TxOk e s role ⟨tb, sb, e.p.sha256 raw, t.half, t.self_os_delta⟩ := by
  unfold checkNew at hc
  split at hc
  · rename_i raw' sig hb1 hb2
    dsimp only at hc
    split at hc
    · rename_i t' hck
      simp only [Except.ok.injEq, Prod.mk.injEq] at hc
      obtain ⟨rfl, rfl⟩ := hc
      exact ⟨e.pk dev, pk', raw', sig, t', role_of_pk hr, hp, hb1, hb2, hck, rfl, rfl, rfl⟩
    · simp at hc
  · simp at hc

/-- **Row `transcript`.** `hfresh` comes from the load, see `expire_fresh`. -/
theorem transcript_inv {e : Env B D} {s : Doc B D} {w : World D} {role : Role} {dev : D} {tb sb : B}
    (h : Inv e w.now s) (hr : role_of s dev = some role)
    (hfresh : s.state = .started → ∃ t, s.t0_ms = some t ∧ w.now ≤ t + K.TRANSCRIPT_DEADLINE_S * 1000 ∧
      w.now - s.created_ms ≤ K.SESSION_MAX_AGE_S * 1000) :
    Inv e w.now (transcript e w s role dev tb sb).1 := by
  unfold transcript
  split
  · exact h
  split
  · exact h
  rename_i h0
  have hs : s.state = .started := by simpa using h0
  split
  · split
    · split
      · exact h
      · exact h
    · exact h
  rename_i h1
  have hnsub : s.submitted role = false := by simpa using h1
  split
  · exact h
  rename_i h2
  have hcom : s.committed role = true := by simpa using h2
  split
  · exact h
  rename_i pk' hp
  split
  · rename_i rsn hc
    exact finalize_inv h.toCore (Or.inr hs) (le_refl _) (by simp) (by simp)
  · exact h
  · rename_i raw t hc
    have hok := checkNew_ok hc hr hp
    obtain ⟨t0, h1', h2', h3'⟩ := hfresh hs
    exact afterStore_inv h (txStore_core h hs hnsub hcom hok) hs ⟨t0, h1', h2', h3'⟩

/-- **Row `fail`.** -/
theorem fail_inv {e : Env B D} {c : ℕ} {s s' : Doc B D} {w : World D} {role : Role} {a : Arg} {rsn : Option Reason}
    (h : Inv e c s) (hcw : c ≤ w.now) (hj : fail_ e w s role a rsn = .ok s') : Inv e w.now s' := by
  unfold fail_ at hj
  split at hj
  · simp at hj
  split at hj
  · simp at hj
  split at hj
  · simp at hj
  split at hj
  · simp at hj
  split at hj
  · simp at hj
  rename_i h1
  split at hj
  · simp at hj
  split at hj
  · simp at hj
  simp only [Except.ok.injEq] at hj
  subst hj
  rename_i rr _ _ n _ _ _ _ _
  have hst : s.state = .confirmed ∨ s.state = .started := Classical.not_not.1 h1
  have hres : s.result = none := h.result_none (by rcases hst with h' | h' <;> simp [h'])
  have harm : ∀ x f, ((failStore s role f).per_role x).arm = (s.per_role x).arm := by
    intro x f; by_cases hx : x = role
    · subst hx; simp [failStore]
    · simp [failStore, upd, hx]
  have hcm : ∀ x f, ((failStore s role f).per_role x).commit = (s.per_role x).commit := by
    intro x f; by_cases hx : x = role
    · subst hx; simp [failStore]
    · simp [failStore, upd, hx]
  have htx : ∀ x f, ((failStore s role f).per_role x).tx = (s.per_role x).tx := by
    intro x f; by_cases hx : x = role
    · subst hx; simp [failStore]
    · simp [failStore, upd, hx]
  apply failed_inv _ (by simpa [failStore] using hst) hcw
  exact { attempt_le := h.attempt_le, guest_ne := h.guest_ne, expires := h.expires
          created_le := h.created_le, sub_com := h.sub_com, com_arm := h.com_arm
          rows := h.rows, result_iff := h.result_iff
          arm_iff := by intro r; rw [harm]; exact h.arm_iff r
          com_iff := by intro r; rw [hcm]; exact h.com_iff r
          sub_iff := by intro r; rw [htx]; exact h.sub_iff r
          live_row := h.live_row
          row_created := h.row_created, row_joined := h.row_joined, row_confirmed := h.row_confirmed
          row_started := h.row_started, row_done := h.row_done, row_aborted := h.row_aborted
          arm_ok := by
            intro r a' ha'
            rw [harm] at ha'
            exact h.arm_ok r a' ha'
          com_ok := by
            intro r cd hcd
            rw [hcm] at hcd
            exact CommitOk_same (s := s) rfl rfl rfl rfl rfl (harm r _) (h.com_ok r cd hcd)
          tx_ok := by
            intro r td htd
            rw [htx] at htd
            exact TxOk_same (s := s) rfl rfl rfl rfl rfl (harm r _) (hcm r _) (h.tx_ok r td htd)
          rec_eq := by simp [failStore, hres]
          near := by simp [failStore, hres]
          verdict_row := h.verdict_row }

/-- `viewOr` either stores the handler's document or keeps the loaded one. -/
theorem viewOr_inv {e : Env B D} {c : ℕ} {s : Doc B D} {w : World D} {role : Role} {x : Except (ℕ × Err) (Doc B D)}
    (h : Inv e c s) (hok : ∀ s', x = .ok s' → Inv e c s') : Inv e c (viewOr e w s role x).1 := by
  unfold viewOr
  split
  · exact hok _ rfl
  · exact h

/-- A created document fits the invariant. -/
theorem create_inv {e : Env B D} (w : World D) (host : D) (sid nonce : B) (seed token : String) :
    Inv e w.now (create w host sid nonce seed token).1 := by
  refine ⟨⟨?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_⟩, ?_⟩
  all_goals simp [create, _save, _flags, live]

/-- One step keeps the invariant. -/
theorem step_inv {e : Env B D} {c : ℕ} {s : Doc B D} {w : World D} (req : Req B D)
    (h : Inv e c s) (hcw : c ≤ w.now) : Inv e w.now (step e w req s).1 := by
  have hm := h.mono hcw
  have hl := expire_inv (w := w) h hcw
  have hf : (_expire e w s).state = .started → _ := expire_fresh (e := e) (w := w) h
  unfold step
  split
  · exact hl
  split
  · exact hm
  split
  · exact hm
  split
  · exact hm
  dsimp only [load]
  rename_i dev _ _
  split
  · exact viewOr_inv hl (fun s' hs' => join_inv hl hs')
  · split
    · exact hl
    · rename_i role hr
      unfold handle
      split
      · exact hl
      · unfold result; split <;> exact hl
      · exact viewOr_inv hl (fun s' hs' => confirm_inv hl hs')
      · exact viewOr_inv hl (fun s' hs' => by
          simp only [Except.ok.injEq] at hs'
          subst hs'
          exact abort_inv hl (le_refl _))
      · exact arm_inv hl (le_refl _)
      · exact commit_inv hl (le_refl _) hr
      · exact transcript_inv hl hr hf
      · exact viewOr_inv hl (fun s' hs' => fail_inv hl (le_refl _) hs')

/-- **M9.** Every reachable document fits the table in `spec.md` M9, and carries what the other
properties lean on. It says the server keeps its books straight on signed numbers. It does not show a
phone told the truth about the air (CN1). -/
theorem M9 {e : Env B D} {c : ℕ} {s : Doc B D} (h : Reachable e c s) : Inv e c s := by
  induction h with
  | create w host sid nonce seed token => exact create_inv w host sid nonce seed token
  | step w req _ hcw ih => exact step_inv req ih hcw

/-! ## A frame: what no step can do

`Frame s s'` collects what holds between the stored document before and after any request. M1, M2,
M7, M10 and M12 read off it. -/

/-- The state moves a request can make, the load included. `spec.md` section 3.5 in one table. A load can
move a state and then a handler can too, so one request can go, for example, `started` to `done`. -/
def Edge : St → St → Bool
  | .created, .created | .created, .joined | .created, .aborted => true
  | .joined, .joined | .joined, .confirmed | .joined, .aborted => true
  | .confirmed, .confirmed | .confirmed, .started | .confirmed, .done | .confirmed, .aborted => true
  | .started, .started | .started, .confirmed | .started, .done | .started, .aborted => true
  | .done, .done | .aborted, .aborted => true
  | _, _ => false

theorem Edge.refl (a : St) : Edge a a = true := by cases a <;> rfl

/-- See above. -/
structure Frame (s s' : Doc B D) : Prop where
  session_id : s'.session_id = s.session_id
  seed : s'.seed_hex = s.seed_hex
  nonce : s'.nonce_hex = s.nonce_hex
  token : s'.join_token = s.join_token
  created : s'.created_ms = s.created_ms
  expires : s'.token_expires_ms = s.token_expires_ms
  host : s'.host_device_id = s.host_device_id
  guest : ∀ g, s.guest_device_id = some g → s'.guest_device_id = some g
  edge : Edge s.state s'.state = true
  attempt : s'.attempt = s.attempt ∨ (s.attempt = 0 ∧ s'.attempt = 1)
  confirmed : ∀ r, s.confirmed r = true → s'.confirmed r = true
  keep_commit : ∀ r cd, (s.per_role r).commit = some cd → s'.attempt = s.attempt →
    (s'.per_role r).commit = some cd
  keep_tx : ∀ r td, (s.per_role r).tx = some td → s'.attempt = s.attempt →
    (s'.per_role r).tx = some td
  result : ∀ rc, s.result = some rc → s'.result = some rc

theorem Frame.refl (s : Doc B D) : Frame s s :=
  ⟨rfl, rfl, rfl, rfl, rfl, rfl, rfl, fun _ h => h, Edge.refl _, Or.inl rfl, fun _ h => h,
    fun _ _ h _ => h, fun _ _ h _ => h, fun _ h => h⟩

theorem Frame.trans {s s1 s2 : Doc B D} (a : Frame s s1) (b : Frame s1 s2) (hle : s.attempt ≤ 1)
    (hlink : ∀ c, Edge s1.state c = true → Edge s.state c = true) : Frame s s2 := by
  have hat : s2.attempt = s.attempt → s1.attempt = s.attempt := by
    intro h
    rcases a.attempt with h1 | h1
    · exact h1
    · rcases b.attempt with h2 | h2 <;> omega
  refine ⟨?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, hlink _ b.edge, ?_, ?_, ?_, ?_, ?_⟩
  · rw [b.session_id, a.session_id]
  · rw [b.seed, a.seed]
  · rw [b.nonce, a.nonce]
  · rw [b.token, a.token]
  · rw [b.created, a.created]
  · rw [b.expires, a.expires]
  · rw [b.host, a.host]
  · exact fun g h => b.guest g (a.guest g h)
  · rcases a.attempt with h1 | h1 <;> rcases b.attempt with h2 | h2
    · left; omega
    · right; omega
    · right; omega
    · omega
  · exact fun r h => b.confirmed r (a.confirmed r h)
  · intro r cd h hh
    have h1 := hat hh
    exact b.keep_commit r cd (a.keep_commit r cd h h1) (by omega)
  · intro r td h hh
    have h1 := hat hh
    exact b.keep_tx r td (a.keep_tx r td h h1) (by omega)
  · exact fun rc h => b.result rc (a.result rc h)

theorem frame_finalize {e : Env B D} {w : World D} {s : Doc B D} {v : Verdict} {rs : Option Reason}
    {f : Option ℚ} {o : Outcome} {by_ : Option Role} (hst : s.state = .confirmed ∨ s.state = .started)
    (hres : s.result = none) : Frame s (_finalize e w s v rs f o by_) := by
  refine ⟨rfl, rfl, rfl, rfl, rfl, rfl, rfl, fun _ h => h, ?_, Or.inl rfl, fun _ h => h,
    fun _ _ h _ => h, fun _ _ h _ => h, ?_⟩
  · rcases hst with h | h <;> simp [_finalize, _save, h, Edge]
  · simp [hres]

theorem frame_failed {e : Env B D} {w : World D} {s : Doc B D} {rs : Option Reason} {by_ : Option Role}
    (hst : s.state = .confirmed ∨ s.state = .started) (hres : s.result = none) (hle : s.attempt ≤ 1) :
    Frame s (_failed e w s rs by_) := by
  unfold _failed
  split
  · rename_i hc
    simp only [Bool.and_eq_true, Nat.blt_eq] at hc
    have ha : s.attempt = 0 := by simp [K.MAX_ATTEMPTS] at hc; omega
    refine ⟨rfl, rfl, rfl, rfl, rfl, rfl, rfl, fun _ h => h, ?_, Or.inr ⟨ha, by simp [next_attempt, _save, ha]⟩,
      fun _ h => h, ?_, ?_, ?_⟩
    · rcases hst with h | h <;> simp [next_attempt, _save, h, Edge]
    · intro r cd _ hh; simp [next_attempt, _save] at hh
    · intro r cd _ hh; simp [next_attempt, _save] at hh
    · simp [hres]
  · exact frame_finalize hst hres

theorem frame_timeout {s : Doc B D} (hl : live s.state = true) (hres : s.result = none) :
    Frame s (_save { s with state := .aborted, error := some .timeout }) := by
  refine ⟨rfl, rfl, rfl, rfl, rfl, rfl, rfl, fun _ h => h, ?_, Or.inl rfl, fun _ h => h,
    fun _ _ h _ => h, fun _ _ h _ => h, ?_⟩
  · rcases hst : s.state <;> simp [hst, live] at hl <;> simp [_save, hst, Edge]
  · simp [hres]

theorem Core.result_none' {e : Env B D} {c : ℕ} {s : Doc B D} (h : Core e c s) (hl : live s.state = true) :
    s.result = none :=
  h.result_none (by intro h'; simp [h', live] at hl)

theorem frame_expire {e : Env B D} {c : ℕ} {w : World D} {s : Doc B D} (h : Inv e c s) :
    Frame s (_expire e w s) := by
  unfold _expire
  split
  · rename_i hc
    have hl : live s.state = true := by simp [hc.1, live]
    exact frame_timeout hl (h.toCore.result_none' hl)
  · split
    · rename_i hc
      exact frame_timeout hc.1 (h.toCore.result_none' hc.1)
    · split
      · rename_i hc
        exact frame_failed (Or.inr hc.1) (h.toCore.result_none (by simp [hc.1])) h.attempt_le
      · exact Frame.refl s

theorem frame_join {e : Env B D} {c : ℕ} {s s' : Doc B D} {w : World D} {d : D} {tok : String}
    (h : Inv e c s) (hj : join w s d tok = .ok s') : Frame s s' := by
  unfold join at hj
  split at hj
  · simp at hj
  split at hj
  · simp at hj
  rename_i h2
  split at hj
  · simp at hj
  split at hj
  · simp at hj
  rename_i h4
  simp only [Except.ok.injEq] at hj
  subst hj
  have hs : s.state = .created := by
    by_contra hh; exact h4 (Or.inl hh)
  have hg : s.guest_device_id = none := by simpa using h2
  refine ⟨rfl, rfl, rfl, rfl, rfl, rfl, rfl, ?_, ?_, Or.inl rfl, fun _ h => h, fun _ _ h _ => h, fun _ _ h _ => h, fun _ h => h⟩
  · simp [hg]
  · simp [_save, hs, Edge]

theorem frame_confirm {s s' : Doc B D} {role : Role} (hj : confirm s role = .ok s') : Frame s s' := by
  unfold confirm at hj
  split at hj
  · simp only [Except.ok.injEq] at hj; subst hj; exact Frame.refl s
  split at hj
  · simp at hj
  rename_i h2
  have hs : s.state = .joined := by simpa using h2
  simp only [Except.ok.injEq] at hj
  subst hj
  have hc : ∀ r, s.confirmed r = true → (upd s.confirmed role true) r = true := by
    intro r hr; by_cases hx : r = role
    · subst hx; simp
    · simpa [upd, hx] using hr
  by_cases hall : all2 (upd s.confirmed role true) = true
  · simp only [hall, ite_true]
    exact ⟨rfl, rfl, rfl, rfl, rfl, rfl, rfl, fun _ h => h, by simp [_save, hs, Edge], Or.inl rfl, hc, fun _ _ h _ => h, fun _ _ h _ => h, fun _ h => h⟩
  · simp only [hall, ite_false]
    exact ⟨rfl, rfl, rfl, rfl, rfl, rfl, rfl, fun _ h => h, by simp [_save, hs, Edge], Or.inl rfl, hc, fun _ _ h _ => h, fun _ _ h _ => h, fun _ h => h⟩

theorem frame_abort {e : Env B D} {c : ℕ} {s : Doc B D} {w : World D} {role : Role} (h : Inv e c s) :
    Frame s (abort w s role) := by
  unfold abort
  split
  · exact Frame.refl s
  rename_i h1
  have hl : live s.state = true := by
    simp only [not_or] at h1
    rcases hst : s.state <;> simp [hst, live] at h1 ⊢
  refine ⟨rfl, rfl, rfl, rfl, rfl, rfl, rfl, fun _ h => h, ?_, Or.inl rfl, fun _ h => h,
    fun _ _ h _ => h, fun _ _ h _ => h, ?_⟩
  · rcases hst : s.state <;> simp [hst, live] at hl <;> simp [_save, hst, Edge]
  · simp [h.toCore.result_none' hl]

theorem frame_arm {e : Env B D} {c : ℕ} {s : Doc B D} {w : World D} {role : Role} {a sr' : Arg}
    {rtt : Option ℚ} {pv : Arg} (h : Inv e c s) :
    Frame s (arm e w s role a sr' rtt pv).1 := by
  have hm := Frame.refl s
  unfold arm
  split
  · exact hm
  split
  · exact hm
  split
  · exact hm
  rename_i sr hsr
  split
  · exact hm
  split
  · exact hm
  rename_i v hv
  split
  · split
    · exact hm
    · split
      · exact hm
      · exact hm
  split
  · exact hm
  rename_i h5 h6
  have hs : s.state = .confirmed := by simpa using h6
  obtain ⟨hg, hc, hna, hf, ht⟩ := h.row_confirmed hs
  have hcomn : ∀ x, (s.per_role x).commit = none := fun x => h.toCore.com_none (hf x).1
  have htxn : ∀ x, (s.per_role x).tx = none := fun x => h.toCore.tx_none (hf x).2
  dsimp only
  by_cases hall : all2 (upd s.armed role true) = true
  · simp only [hall, ite_true]
    exact ⟨rfl, rfl, rfl, rfl, rfl, rfl, rfl, fun _ h => h, by simp [_save, hs, Edge], Or.inl rfl, fun _ h => h,
      fun r cd hx => by simp [hcomn] at hx, fun r cd hx => by simp [htxn] at hx, fun _ h => h⟩
  · simp only [hall, ite_false]
    exact ⟨rfl, rfl, rfl, rfl, rfl, rfl, rfl, fun _ h => h, by simp [_save, hs, Edge], Or.inl rfl, fun _ h => h,
      fun r cd hx => by simp [hcomn] at hx, fun r cd hx => by simp [htxn] at hx, fun _ h => h⟩

theorem frame_commitStore {e : Env B D} {c : ℕ} {s : Doc B D} {role : Role} {cd : CommitData B}
    (h : Inv e c s) (hna : s.committed role = false) : Frame s (commitStore s role cd) := by
  refine ⟨rfl, rfl, rfl, rfl, rfl, rfl, rfl, fun _ h => h, Edge.refl _, Or.inl rfl, fun _ h => h, ?_, ?_, fun _ h => h⟩
  · intro r cd' hx _
    by_cases hr : r = role
    · subst hr; rw [h.toCore.com_none hna] at hx; simp at hx
    · simpa [commitStore, _save, upd, hr] using hx
  · intro r td hx _
    by_cases hr : r = role
    · subst hr; simpa [commitStore, _save] using hx
    · simpa [commitStore, _save, upd, hr] using hx

theorem frame_commit {e : Env B D} {c : ℕ} {s : Doc B D} {w : World D} {role : Role} {dev : D} {cb sb : B}
    (h : Inv e c s) : Frame s (commit e w s role dev cb sb).1 := by
  have hm := Frame.refl s
  unfold commit
  split
  · exact hm
  split
  · split
    · exact hm
    split
    · exact hm
    split
    · exact hm
    split
    · exact hm
    split
    · split
      · exact hm
      · exact hm
    rename_i h6
    split
    · exact hm
    exact frame_commitStore h (by simpa using h6)
  · exact hm

theorem frame_txStore {s : Doc B D} {role : Role} {td : TxData B} (hns : s.submitted role = false) (hnt : (s.per_role role).tx = none) :
    Frame s (txStore s role td) := by
  refine ⟨rfl, rfl, rfl, rfl, rfl, rfl, rfl, fun _ h => h, Edge.refl _, Or.inl rfl, fun _ h => h, ?_, ?_, fun _ h => h⟩
  · intro r cd' hx _
    by_cases hr : r = role
    · subst hr; simpa [txStore] using hx
    · simpa [txStore, upd, hr] using hx
  · intro r td' hx _
    by_cases hr : r = role
    · subst hr; rw [hnt] at hx; simp at hx
    · simpa [txStore, upd, hr] using hx

theorem frame_afterStore {e : Env B D} {w : World D} {s0 s : Doc B D} (hf : Frame s0 s) (hst : s.state = .started)
    (hst0 : s0.state = .started) (hres : s.result = none) (hle : s0.attempt ≤ 1) :
    Frame s0 (afterStore e w s0 s).1 := by
  have hle' : s.attempt ≤ 1 := by rcases hf.attempt with h | h <;> omega
  have hk : ∀ c, Edge s.state c = true → Edge s0.state c = true := by
    intro c hc; rw [hst0]; rw [hst] at hc; exact hc
  unfold afterStore
  split
  · exact hf.trans ⟨rfl, rfl, rfl, rfl, rfl, rfl, rfl, fun _ h => h, Edge.refl _, Or.inl rfl, fun _ h => h, fun _ _ h _ => h, fun _ _ h _ => h, fun _ h => h⟩ hle hk
  split
  · split
    · exact hf.trans (frame_finalize (Or.inr hst) hres) hle hk
    · exact Frame.refl s0
    · split
      · exact hf.trans (frame_failed (Or.inr hst) hres hle') hle hk
      · exact hf.trans (frame_finalize (Or.inr hst) hres) hle hk
  · exact Frame.refl s0

theorem frame_transcript {e : Env B D} {c : ℕ} {s : Doc B D} {w : World D} {role : Role} {dev : D} {tb sb : B}
    (h : Inv e c s) : Frame s (transcript e w s role dev tb sb).1 := by
  have hm := Frame.refl s
  unfold transcript
  split
  · exact hm
  split
  · exact hm
  rename_i h0
  have hs : s.state = .started := by simpa using h0
  have hres : s.result = none := h.toCore.result_none (by simp [hs])
  split
  · split
    · split
      · exact hm
      · exact hm
    · exact hm
  rename_i h1
  have hnsub : s.submitted role = false := by simpa using h1
  split
  · exact hm
  split
  · exact hm
  split
  · exact frame_finalize (Or.inr hs) hres
  · exact hm
  · exact frame_afterStore (frame_txStore hnsub (h.toCore.tx_none hnsub)) hs hs hres h.attempt_le

theorem frame_fail {e : Env B D} {c : ℕ} {s s' : Doc B D} {w : World D} {role : Role} {a : Arg} {rsn : Option Reason}
    (h : Inv e c s) (hj : fail_ e w s role a rsn = .ok s') : Frame s s' := by
  unfold fail_ at hj
  split at hj
  · simp at hj
  split at hj
  · simp at hj
  split at hj
  · simp at hj
  split at hj
  · simp at hj
  split at hj
  · simp at hj
  rename_i h1
  split at hj
  · simp at hj
  split at hj
  · simp at hj
  simp only [Except.ok.injEq] at hj
  subst hj
  have hst : s.state = .confirmed ∨ s.state = .started := Classical.not_not.1 h1
  have hres : s.result = none := h.toCore.result_none (by rcases hst with h' | h' <;> simp [h'])
  have hfs : ∀ f, Frame s (failStore s role f) := by
    intro f
    refine ⟨rfl, rfl, rfl, rfl, rfl, rfl, rfl, fun _ h => h, Edge.refl _, Or.inl rfl, fun _ h => h, ?_, ?_, fun _ h => h⟩
    · intro r cd' hx _
      by_cases hr : r = role
      · subst hr; simpa [failStore] using hx
      · simpa [failStore, upd, hr] using hx
    · intro r td' hx _
      by_cases hr : r = role
      · subst hr; simpa [failStore] using hx
      · simpa [failStore, upd, hr] using hx
  exact (hfs _).trans (frame_failed hst hres h.attempt_le) h.attempt_le (fun c hc => hc)

theorem frame_viewOr {e : Env B D} {s : Doc B D} {w : World D} {role : Role} {x : Except (ℕ × Err) (Doc B D)}
    (hok : ∀ s', x = .ok s' → Frame s s') : Frame s (viewOr e w s role x).1 := by
  unfold viewOr
  split
  · exact hok _ rfl
  · exact Frame.refl s

/-- A load moves a state only in ways a handler's move can follow. -/
theorem expire_link {e : Env B D} {w : World D} {s : Doc B D} (c : St) (hc : Edge (_expire e w s).state c = true) :
    Edge s.state c = true := by
  unfold _expire at hc
  split at hc
  · rename_i h1
    have : c = .aborted := by cases c <;> simp_all [Edge, _save]
    subst this
    simp [h1.1, Edge]
  · split at hc
    · rename_i h1 h2
      have : c = .aborted := by cases c <;> simp_all [Edge, _save]
      subst this
      have hl := h2.1
      rcases hst : s.state <;> simp [hst, live] at hl <;> simp [Edge]
    · split at hc
      · rename_i h1 h2 h3
        rw [h3.1]
        unfold _failed at hc
        split at hc
        · simp [next_attempt, _save] at hc
          cases c <;> simp_all [Edge]
        · simp [_finalize, _save] at hc
          cases c <;> simp_all [Edge]
      · exact hc

/-- Every request obeys the frame. -/
theorem frame_step {e : Env B D} {c : ℕ} {s : Doc B D} {w : World D} (req : Req B D)
    (h : Inv e c s) (hcw : c ≤ w.now) : Frame s (step e w req s).1 := by
  have hl := expire_inv (w := w) h hcw
  have hfe : Frame s (_expire e w s) := frame_expire h
  have hle := h.attempt_le
  have hk : ∀ c, Edge (_expire e w s).state c = true → Edge s.state c = true := fun c hc => expire_link c hc
  unfold step
  split
  · exact hfe
  split
  · exact Frame.refl s
  split
  · exact Frame.refl s
  split
  · exact Frame.refl s
  dsimp only [load]
  split
  · exact hfe.trans (frame_viewOr (fun s' hs' => frame_join hl hs')) hle hk
  · split
    · exact hfe
    · unfold handle
      split
      · exact hfe
      · unfold result; split <;> exact hfe
      · exact hfe.trans (frame_viewOr (fun s' hs' => frame_confirm hs')) hle hk
      · exact hfe.trans (frame_viewOr (fun s' hs' => by
          simp only [Except.ok.injEq] at hs'
          subst hs'
          exact frame_abort hl)) hle hk
      · exact hfe.trans (frame_arm hl) hle hk
      · exact hfe.trans (frame_commit hl) hle hk
      · exact hfe.trans (frame_transcript hl) hle hk
      · exact hfe.trans (frame_viewOr (fun s' hs' => frame_fail hl hs')) hle hk

/-! ## M1, M2: finished sessions don't move -/

/-- `_expire` leaves a finished session alone. -/
theorem expire_terminal {e : Env B D} {w : World D} {s : Doc B D} (hst : s.state = .done ∨ s.state = .aborted) :
    _expire e w s = s := by
  unfold _expire
  rcases hst with h | h <;> simp [h, live]

/-- **M1, part one.** From done or aborted no request changes the stored document. Any request, any
sender. It needs no invariant. `zk` and `seq` from out-of-scope routes aren't in this model (A9).

It says nothing about the air (CN1). -/
theorem M1_terminal {e : Env B D} {w : World D} {s : Doc B D} (req : Req B D)
    (hst : s.state = .done ∨ s.state = .aborted) : (step e w req s).1 = s := by
  have hl : load e w s = s := expire_terminal hst
  have hne : s.state ≠ .created := by rcases hst with h | h <;> simp [h]
  have hnj : s.state ≠ .joined := by rcases hst with h | h <;> simp [h]
  have hnc : s.state ≠ .confirmed := by rcases hst with h | h <;> simp [h]
  have hns : s.state ≠ .started := by rcases hst with h | h <;> simp [h]
  unfold step
  split
  · exact hl
  split
  · rfl
  split
  · rfl
  split
  · rfl
  dsimp only
  rw [hl]
  split
  · unfold viewOr
    split
    · rename_i s' hj
      unfold join at hj
      simp only [hne, ne_eq, not_false_eq_true, true_or, ite_true] at hj
      split at hj
      · simp at hj
      split at hj
      · simp at hj
      split at hj
      · simp at hj
      · simp at hj
    · rfl
  · split
    · rfl
    · unfold handle
      split
      · rfl
      · unfold result; split <;> rfl
      · unfold viewOr
        split
        · rename_i s' hj
          simp [confirm, hnc, hnj] at hj
        · rfl
      · unfold viewOr
        simp only
        unfold abort
        simp [hst]
      · unfold arm
        simp [hnc, hns]
      · unfold commit
        simp [hns]
      · unfold transcript
        simp [hns]
        split <;> rfl
      · unfold viewOr
        split
        · rename_i s' hj
          unfold fail_ at hj
          split at hj
          · simp at hj
          split at hj
          · simp at hj
          split at hj
          · simp at hj
          split at hj
          · simp at hj
          simp [hnc, hns] at hj
        · rfl

/-- **M1, part two.** Every request moves the state along `Edge` only. So the states of the table can't be
skipped: nothing goes from `created` to `started`, and nothing leaves `done` or `aborted`. This
is the state column of the table in `spec.md` section 3.5 and nothing else. `Edge` knows only states. That other fields change only
as the table says rests on `step` being a literal copy, which is checked by reading, plus what `Frame` and `Inv` prove.

It says nothing about the air (CN1). -/
theorem M1_edges {e : Env B D} {c : ℕ} {s : Doc B D} {w : World D} (req : Req B D)
    (h : Reachable e c s) (hcw : c ≤ w.now) : Edge s.state (step e w req s).1.state = true :=
  (frame_step req (M9 h) hcw).edge

/-- **M2.** Once `result` is set, it stays, with `state` and `error`. The whole record is one value here, so
that covers `verdict`, `reason`, `flight_cm`, `attempt`, `devices`, `transcripts`, `commits` and
`attempts`. `result["zk"]` isn't modeled (A9).

It says nothing about the air (CN1). -/
theorem M2 {e : Env B D} {c : ℕ} {s : Doc B D} {w : World D} {rc : Record B D} (req : Req B D)
    (h : Reachable e c s) (hr : s.result = some rc) :
    (step e w req s).1.result = some rc ∧ (step e w req s).1.state = s.state ∧
      (step e w req s).1.error = s.error := by
  have hd := (M9 h).result_iff.1 (by simp [hr])
  rw [M1_terminal req (Or.inl hd)]
  exact ⟨hr, rfl, rfl⟩

/-! ## M3: what a NEAR stands on -/

theorem stored_eq {e : Env B D} {s : Doc B D} {r : Role} {td : TxData B} {raw : B} {t : Transcript B}
    (h1 : (s.per_role r).tx = some td) (h2 : e.b64d td.transcript_b64 = some raw)
    (h3 : e.p.decode_transcript raw = some t) : stored e s r = some t := by
  simp [stored, h1, h2, h3]

/-- One role's side of M3, for a document that passed everything so far. -/
theorem side_facts {e : Env B D} {c : ℕ} {s : Doc B D} {r : Role} (h : Core e c s) (hsub : s.submitted r = true) :
    ∃ pk pk' cd td rawc sigc rawt sigt cm t,
      (s.per_role r).commit = some cd ∧ (s.per_role r).tx = some td ∧
      _pk e s r = some pk ∧ _pk e s (OTHER r) = some pk' ∧
      e.b64d cd.commit_b64 = some rawc ∧ e.b64d cd.commit_sig_b64 = some sigc ∧
      e.b64d td.transcript_b64 = some rawt ∧ e.b64d td.sig_b64 = some sigt ∧
      e.p.decode_commit rawc = some cm ∧ e.p.verify_raw pk rawc sigc = true ∧
      cm.role = r ∧ cm.attempt = s.attempt ∧ cm.nonce = s.nonce_hex ∧
      e.p.decode_transcript rawt = some t ∧ e.p.verify_raw pk rawt sigt = true ∧
      t.pk_self = pk ∧ t.pk_partner = pk' ∧ t.role = r ∧ t.attempt = s.attempt ∧ t.nonce = s.nonce_hex ∧
      t.commit_hash = e.p.sha256 rawc ∧ t.rec_ = cm.rec_ ∧
      36000 ≤ t.sample_rate ∧ t.sample_rate ≤ 96000 := by
  have hcom := h.sub_com r hsub
  rcases hcd : (s.per_role r).commit with _ | cd
  · have := (h.com_iff r).1 hcom; simp [hcd] at this
  rcases htd : (s.per_role r).tx with _ | td
  · have := (h.sub_iff r).1 hsub; simp [htd] at this
  obtain ⟨pk, rawc, sigc, cm, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, _⟩ := h.com_ok r cd hcd
  obtain ⟨pk1, pk', rawt, sigt, t, h1', hp', h2', h3', hck, _, _, _⟩ := h.tx_ok r td htd
  rw [h1] at h1'
  simp only [Option.some.injEq] at h1'
  subst h1'
  rw [check_transcript_ok_iff] at hck
  obtain ⟨k1, k2, k3, k4, k5, k6, k7, k8, k9, k10, k11, k12, k13, k14⟩ := hck
  rw [hcd] at k12 k13
  simp only [Option.map_some, Option.some.injEq] at k12 k13
  refine ⟨pk, pk', cd, td, rawc, sigc, rawt, sigt, cm, t, rfl, rfl, h1, hp', h2, h3, h2', h3', h4, h5, h6, h7, h8, k1, k2, k4, k8, k5, k7, k6, ?_, ?_, k10, k11⟩
  · rw [← k12, h10]
  · rw [← k13, h11]

/-- **M3.** Say the record has verdict NEAR, and k is `result.attempt`. Then k is the document's attempt,
and for each role r:
* r's commit and transcript were accepted (flags set), and the record holds them;
* the commit decodes, passes `verify_raw` under the enrolled key of r's device, with role r, attempt k and
  this nonce;
* the transcript decodes, passes `verify_raw` under the same key, with `pk_self` that key, `pk_partner` the
  partner's key, role r, attempt k, this nonce, `commit_hash` the hash of that commit, rec that commit's rec.

And `combine` on the two decoded transcripts, with the `cal_us` snapshots, returned NEAR, with the
record's flight.

This is about signed numbers. It does not show a phone told the truth about the air (CN1): see `X1`. It
says nothing about NOT_NEAR. A passed `verify_raw` becomes "the holder signed" only in `M3_signed`. -/
theorem M3 {e : Env B D} {c : ℕ} {s : Doc B D} {rc : Record B D} (h : Reachable e c s)
    (hr : s.result = some rc) (hv : rc.verdict = .NEAR) :
    rc.attempt = s.attempt ∧ ∃ T : Role → Transcript B,
      (∀ r, s.committed r = true ∧ s.submitted r = true ∧
        ∃ pk pk' cm tr rawc sigc rawt sigt cmt,
          _pk e s r = some pk ∧ _pk e s (OTHER r) = some pk' ∧
          rc.commits r = some cm ∧ rc.transcripts r = some tr ∧
          e.b64d cm.commit_b64 = some rawc ∧ e.b64d cm.sig_b64 = some sigc ∧
          e.b64d tr.transcript_b64 = some rawt ∧ e.b64d tr.sig_b64 = some sigt ∧
          e.p.decode_commit rawc = some cmt ∧ e.p.verify_raw pk rawc sigc = true ∧
          cmt.role = r ∧ cmt.attempt = rc.attempt ∧ cmt.nonce = s.nonce_hex ∧
          e.p.decode_transcript rawt = some (T r) ∧ e.p.verify_raw pk rawt sigt = true ∧
          (T r).pk_self = pk ∧ (T r).pk_partner = pk' ∧ (T r).role = r ∧
          (T r).attempt = rc.attempt ∧ (T r).nonce = s.nonce_hex ∧
          (T r).commit_hash = e.p.sha256 rawc ∧ (T r).rec_ = cmt.rec_) ∧
      ∃ out, combine (T .A) (T .B) (calMap s) = .ok out ∧ out.verdict = some .NEAR ∧
        rc.flight_cm = out.flight_cm := by
  have hi := M9 h
  have nf := hi.near rc hr hv
  have hrec := hi.rec_eq rc hr
  have hatt : rc.attempt = s.attempt := by rw [hrec]; rfl
  obtain ⟨ta, tb, out, hta, htb, hcomb, hout, hfl⟩ := nf.cmb
  have hsub : ∀ r, s.submitted r = true := by
    have := nf.both
    simp only [all2, Bool.and_eq_true] at this
    intro r; cases r
    · exact this.1
    · exact this.2
  let T : Role → Transcript B := fun r => match r with | .A => ta | .B => tb
  have hst : ∀ r, stored e s r = some (T r) := by intro r; cases r <;> simp [T, hta, htb]
  refine ⟨hatt, T, ?_, out, hcomb, hout, hfl⟩
  intro r
  obtain ⟨pk, pk', cd, td, rawc, sigc, rawt, sigt, cm, t, h1, h2, h3, h3', h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, _, _⟩ :=
    side_facts hi.toCore (hsub r)
  have htT : t = T r := by
    have := stored_eq h2 h6 h13
    rw [hst r] at this
    simpa using this.symm
  subst htT
  refine ⟨hi.sub_com r (hsub r), hsub r, pk, pk', ⟨cd.commit_b64, cd.commit_sig_b64⟩,
    ⟨td.transcript_b64, td.sig_b64, td.transcript_sha256⟩, rawc, sigc, rawt, sigt, cm, h3, h3', ?_, ?_,
    h4, h5, h6, h7, h8, h9, h10, by rw [h11, hatt], h12, h13, h14, h15, h16, h17, by rw [h18, hatt], h19, h20, h21⟩
  · rw [hrec]; simp [_record, h1]
  · rw [hrec]; simp [_record, h2]

/-- **M3 with A4.** If signature checks can't be forged, then in a NEAR record the holder of each role's
enrolled key really signed that role's commit and transcript. It uses `Unforgeable` and nothing here shows
that it holds for P-256 (A4). It does not show a phone told the truth about the air (CN1): the holder may
have signed any numbers. -/
theorem M3_signed {e : Env B D} {c : ℕ} {s : Doc B D} {rc : Record B D} {signed : B → B → Prop}
    (hu : Unforgeable e.p signed) (h : Reachable e c s) (hr : s.result = some rc) (hv : rc.verdict = .NEAR)
    (r : Role) :
    ∃ pk rawc rawt cm tr, _pk e s r = some pk ∧ rc.commits r = some cm ∧ rc.transcripts r = some tr ∧
      e.b64d cm.commit_b64 = some rawc ∧ e.b64d tr.transcript_b64 = some rawt ∧
      signed pk rawc ∧ signed pk rawt := by
  obtain ⟨_, T, hs, _⟩ := M3 h hr hv
  obtain ⟨_, _, pk, pk', cm, tr, rawc, sigc, rawt, sigt, cmt, h1, _, h2, h3, h4, _, h5, _, _, h6, _, _, _, _, h7, _⟩ := hs r
  exact ⟨pk, rawc, rawt, cm, tr, h1, h2, h3, h4, h5, hu _ _ _ h6, hu _ _ _ h7⟩

/-- **The guard at lines 457-459, and the raise at line 454, can't fire.** On a document with both
transcripts in, and ids that map to different keys, the stored transcripts decode and `combine` returns.
This one is about any such document. `combine_guard_on_request` below ties it to a real request.
`spec.md` section 3.5: the Python keeps this as a guard. The hypothesis is the "A != B" of M12. The device id is a
function of the key, so different ids have different keys. Here the map runs from id to key, so that fact is
named as `Function.Injective e.pk`. -/
theorem combine_guard_unreachable {e : Env B D} {c : ℕ} {s : Doc B D} (hinj : Function.Injective e.pk)
    (h : Core e c s) (hall : all2 s.submitted = true) :
    ∃ ta tb out, stored e s .A = some ta ∧ stored e s .B = some tb ∧ combine ta tb (calMap s) = .ok out := by
  simp only [all2, Bool.and_eq_true] at hall
  obtain ⟨pkA, pkB, cdA, tdA, _, _, rawA, _, _, ta, _, h2A, h3A, h3A', _, _, h6A, _, _, _, _, _, _, h13A, _, h15A, h16A, h17A, h18A, h19A, _, _, h22A, h23A⟩ :=
    side_facts h hall.1
  obtain ⟨pkB', pkA', cdB, tdB, _, _, rawB, _, _, tb, _, h2B, h3B, h3B', _, _, h6B, _, _, _, _, _, _, h13B, _, h15B, h16B, h17B, h18B, h19B, _, _, h22B, h23B⟩ :=
    side_facts h hall.2
  simp only [OTHER] at h3A' h3B'
  have e1 : pkB' = pkB := by rw [h3B] at h3A'; simpa using h3A'
  have e2 : pkA' = pkA := by rw [h3A] at h3B'; simpa using h3B'.symm
  subst e1 e2
  have hne : pkA' ≠ pkB' := by
    intro heq
    rcases hg : s.guest_device_id with _ | g
    · simp [_pk, devId, hg] at h3B
    · simp only [_pk, devId, Option.map_some, Option.some.injEq, hg] at h3A h3B
      rw [← h3A, ← h3B] at heq
      have := hinj heq
      exact h.guest_ne (by rw [hg, this])
  have hc : ∃ out, combine ta tb (calMap s) = .ok out := by
    unfold combine
    rw [ite_eq_right (by simp [h17A, h17B]), ite_eq_right (by simp [h19A, h19B, h18A, h18B]),
      ite_eq_right (by simp [h16A, h16B, h15A, h15B, hne])]
    split
    · exact ⟨_, rfl⟩
    split
    · exact ⟨_, rfl⟩
    rw [ite_eq_right (by simp; omega)]
    exact ⟨_, rfl⟩
  obtain ⟨out, hout⟩ := hc
  exact ⟨ta, tb, out, stored_eq h2A h6A h13A, stored_eq h2B h6B h13B, hout⟩

/-- When both transcripts are in, on a document that keeps the rows, `afterStore` answers `accepted`. So none of its error answers
can come out. It says nothing about the air (CN1). -/
theorem afterStore_accepted {e : Env B D} {c : ℕ} {s s0 : Doc B D} {w : World D} (hinj : Function.Injective e.pk)
    (h : Core e c s) : ∃ st a, (afterStore e w s0 s).2 = .accepted st a := by
  unfold afterStore
  split
  · exact ⟨_, _, rfl⟩
  rename_i hall
  obtain ⟨ta, tb, out, h1, h2, hc⟩ := combine_guard_unreachable hinj h (by simpa using hall)
  simp only [h1, h2, hc]
  exact ⟨_, _, rfl⟩

/-- **The same guard, on a real `/transcript` request.** This is about the handler `transcript`, on the document after the load. Take a
request from a member whose new transcript passes the check of lines 433-440 and that isn't caught as stale. Then the answer is `accepted`. So the guard at lines 457-459 and the raise at line 454 can't
fire on such a request. The hypotheses are the guards of `transcript`, in its order. It says nothing about the air (CN1). -/
theorem combine_guard_on_request {e : Env B D} {c : ℕ} {s : Doc B D} {w : World D} {role : Role} {dev : D} {tb sb pk' raw : B}
    {t : Transcript B} (hinj : Function.Injective e.pk) (h : Inv e c s) (hr : role_of s dev = some role)
    (hstale : staleTranscript e s role tb sb = false) (hs : s.state = .started) (hnsub : s.submitted role = false)
    (hcom : s.committed role = true) (hp : _pk e s (OTHER role) = some pk')
    (hc : checkNew e s role dev tb sb pk' = .ok (raw, t)) :
    ∃ st a, (transcript e w s role dev tb sb).2 = .accepted st a := by
  have hk := txStore_core h hs hnsub hcom (checkNew_ok hc hr hp)
  obtain ⟨st, a, hx⟩ := afterStore_accepted (s0 := s) (w := w) hinj hk
  refine ⟨st, a, ?_⟩
  unfold transcript
  simp only [hstale, hs, hnsub, hcom, hp, hc]
  simpa using hx

/-! ## M4: NEAR has one source -/

theorem failed_not_near {e : Env B D} {w : World D} {s : Doc B D} {rs : Option Reason} {by_ : Option Role} {rc : Record B D}
    (hres : s.result = none) (h : (_failed e w s rs by_).result = some rc) : rc.verdict = .NOT_NEAR := by
  unfold _failed at h
  split at h
  · simp [next_attempt, _save, hres] at h
  · simp only [_finalize, _save, Option.some.injEq] at h
    rw [← h]; rfl

theorem expire_not_near {e : Env B D} {w : World D} {s : Doc B D} {rc : Record B D}
    (hres : s.result = none) (h : (_expire e w s).result = some rc) : rc.verdict = .NOT_NEAR := by
  unfold _expire at h
  split at h
  · simp [_save, hres] at h
  split at h
  · simp [_save, hres] at h
  split at h
  · exact failed_not_near hres h
  · simp [hres] at h

/-- **M4.** NEAR has one source. A request that writes a NEAR record is a `/transcript` request with good auth,
from a member. `_finalize` is the only writer of `result` (line 348), and `M3` shows the verdict it
wrote came from `combine`. The other three call sites (lines 340, 442, 458) pass `NOT_NEAR`: `failed_not_near`
for the first, and the `transcript` definition for the others.

It says nothing about the air (CN1). -/
theorem M4 {e : Env B D} {c : ℕ} {s : Doc B D} {w : World D} {rc : Record B D} (req : Req B D)
    (hreach : Reachable e c s) (hcw : c ≤ w.now) (hn : s.result = none)
    (hr : (step e w req s).1.result = some rc) (hv : rc.verdict = .NEAR) :
    ∃ dev role tb sb, req = .api false (some dev) false (.op (.transcript tb sb)) ∧
      role_of (load e w s) dev = some role := by
  have h := M9 hreach
  have hl := expire_inv (w := w) h hcw
  have hne : ∀ s' : Doc B D, s'.result = (_expire e w s).result → s'.result = some rc → False := by
    intro s' hs' hx
    rw [hs'] at hx
    have := expire_not_near hn hx
    rw [hv] at this
    simp at this
  unfold step at hr
  split at hr
  · exact (hne _ rfl hr).elim
  split at hr
  · simp [hn] at hr
  rename_i j _ sender sh body h1
  split at hr
  · simp [hn] at hr
  rename_i dev
  split at hr
  · simp [hn] at hr
  rename_i h3
  dsimp only [load] at hr
  split at hr
  · unfold viewOr at hr
    split at hr
    · rename_i s' hj
      unfold join at hj
      split at hj
      · simp at hj
      split at hj
      · simp at hj
      split at hj
      · simp at hj
      split at hj
      · simp at hj
      simp only [Except.ok.injEq] at hj
      subst hj
      exact (hne _ rfl hr).elim
    · exact (hne _ rfl hr).elim
  · split at hr
    · exact (hne _ rfl hr).elim
    · rename_i o _ role hrole
      unfold handle at hr
      split at hr
      · exact (hne _ rfl hr).elim
      · unfold result at hr
        split at hr <;> exact (hne _ rfl hr).elim
      · unfold viewOr at hr
        split at hr
        · rename_i s' hj
          have hf := frame_confirm hj
          unfold confirm at hj
          split at hj
          · simp only [Except.ok.injEq] at hj; subst hj; exact (hne _ rfl hr).elim
          split at hj
          · simp at hj
          simp only [Except.ok.injEq] at hj
          subst hj
          split at hr <;> exact (hne _ rfl hr).elim
        · exact (hne _ rfl hr).elim
      · unfold viewOr at hr
        simp only at hr
        unfold abort at hr
        split at hr
        · exact (hne _ rfl hr).elim
        · exact (hne _ rfl hr).elim
      · exfalso
        unfold arm at hr
        repeat' (first | exact hne _ rfl hr | split at hr)
        all_goals dsimp only at hr
        all_goals (first | exact hne _ rfl hr | (split at hr <;> exact hne _ rfl hr))
      · exfalso
        unfold commit at hr
        repeat' (first | exact hne _ rfl hr | split at hr)
      · simp only [Bool.not_eq_true] at h1 h3
        subst h1 h3
        exact ⟨dev, role, _, _, rfl, hrole⟩
      · exfalso
        unfold viewOr at hr
        split at hr
        · rename_i s' hj
          unfold fail_ at hj
          split at hj
          · simp at hj
          split at hj
          · simp at hj
          split at hj
          · simp at hj
          split at hj
          · simp at hj
          split at hj
          · simp at hj
          split at hj
          · simp at hj
          split at hj
          · simp at hj
          simp only [Except.ok.injEq] at hj
          subst hj
          rename_i hfresh
          by_cases hnr : (_expire e w s).result = none
          · have := failed_not_near (s := failStore (_expire e w s) _ _) hnr hr
            rw [hv] at this; simp at this
          · rename_i hss _
            exact absurd (hl.toCore.result_none (by
              intro hd
              rw [hd] at hss
              simp at hss)) hnr
        · exact hne _ rfl hr

/-! ## What a response contains (for M5 and M6) -/

/-- Every code in a response. These are the `Code` fields of `Resp`. -/
def Resp.codes : Resp B D → List Code
  | .armMaterial _ _ p o oc _ => [p, o] ++ oc.toList
  | .partnerBed pb pc _ => [pb] ++ pc.toList
  | _ => []

/-- Every `String` of a response outside a `Code`. The only one in the type is the token in `created`. -/
def Resp.strings : Resp B D → List String
  | .created _ _ tk _ => [tk]
  | _ => []

/-- Every result record in a response. A half and a transcript can only be in here: reading `Resp`,
`ViewBody` and `LastFailure` shows no other field holds one. A `self_os_delta` is only in the transcript
bytes of a record. -/
def Resp.records : Resp B D → List (Record B D)
  | .view v => v.result.toList
  | .record r => [r]
  | _ => []

/-- Every half in a response: those of the records. -/
def Resp.halves (x : Resp B D) : List ℤ :=
  x.records.flatMap fun rc =>
    [(rc.devices .A).bind (·.half), (rc.devices .B).bind (·.half)].filterMap id

/-- Every transcript entry in a response: those of the records. -/
def Resp.transcripts (x : Resp B D) : List (TxEntry B) :=
  x.records.flatMap fun rc => [rc.transcripts .A, rc.transcripts .B].filterMap id

/-- The three possible shapes of a `commit` result. -/
theorem commit_shape (e : Env B D) (w : World D) (s : Doc B D) (role : Role) (dev : D) (cb sb : B) :
    (∃ st c, commit e w s role dev cb sb = (s, .error st c)) ∨
    (s.state = .started ∧ s.committed role = true ∧
      commit e w s role dev cb sb = (s, _partner_bed s role)) ∨
    (s.state = .started ∧ ∃ cd, s.committed role = false ∧ commit e w s role dev cb sb =
      (commitStore s role cd, _partner_bed (commitStore s role cd) role)) := by
  unfold commit
  split
  · exact Or.inl ⟨_, _, rfl⟩
  rename_i h0
  have hs : s.state = .started := by simpa using h0
  split
  · split
    · exact Or.inl ⟨_, _, rfl⟩
    split
    · exact Or.inl ⟨_, _, rfl⟩
    split
    · exact Or.inl ⟨_, _, rfl⟩
    split
    · exact Or.inl ⟨_, _, rfl⟩
    split
    · rename_i h6
      split
      · exact Or.inl ⟨_, _, rfl⟩
      · exact Or.inr (Or.inl ⟨hs, h6, rfl⟩)
    rename_i h6
    split
    · exact Or.inl ⟨_, _, rfl⟩
    exact Or.inr (Or.inr ⟨hs, _, by simpa using h6, rfl⟩)
  · exact Or.inl ⟨_, _, rfl⟩

/-- A response with no codes, no records and no strings. -/
def Quiet (x : Resp B D) : Prop := x.codes = [] ∧ x.records = [] ∧ x.strings = []

theorem afterStore_quiet (e : Env B D) (w : World D) (s0 s : Doc B D) : Quiet (afterStore e w s0 s).2 := by
  unfold afterStore
  split
  · exact ⟨rfl, rfl, rfl⟩
  split
  · split
    · exact ⟨rfl, rfl, rfl⟩
    · exact ⟨rfl, rfl, rfl⟩
    · exact ⟨rfl, rfl, rfl⟩
  · exact ⟨rfl, rfl, rfl⟩

theorem transcript_quiet (e : Env B D) (w : World D) (s : Doc B D) (role : Role) (dev : D) (tb sb : B) :
    Quiet (transcript e w s role dev tb sb).2 := by
  unfold transcript
  split
  · exact ⟨rfl, rfl, rfl⟩
  split
  · exact ⟨rfl, rfl, rfl⟩
  split
  · split
    · split
      · exact ⟨rfl, rfl, rfl⟩
      · exact ⟨rfl, rfl, rfl⟩
    · exact ⟨rfl, rfl, rfl⟩
  split
  · exact ⟨rfl, rfl, rfl⟩
  split
  · exact ⟨rfl, rfl, rfl⟩
  split
  · exact ⟨rfl, rfl, rfl⟩
  · exact ⟨rfl, rfl, rfl⟩
  · exact afterStore_quiet ..

theorem viewOr_codes (e : Env B D) (w : World D) (s : Doc B D) (role : Role) (x : Except (ℕ × Err) (Doc B D)) :
    (viewOr e w s role x).2.codes = [] := by
  unfold viewOr
  split <;> rfl

theorem viewOr_records {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {x : Except (ℕ × Err) (Doc B D)}
    {rc : Record B D} (h : rc ∈ (viewOr e w s role x).2.records) : (viewOr e w s role x).1.result = some rc := by
  unfold viewOr at h ⊢
  split at h
  · simpa [Resp.records, view] using h
  · simp [Resp.records] at h

theorem arm_material_codes {s : Doc B D} {role : Role} {x : Code} (h : x ∈ (_arm_material s role).codes) :
    x = _code s role := by
  simp only [_arm_material, Resp.codes] at h
  split at h <;> simp_all

theorem partner_bed_codes {s : Doc B D} {role : Role} {x : Code} (h : x ∈ (_partner_bed s role).codes) :
    x = _code s (OTHER role) := by
  simp only [_partner_bed, Resp.codes] at h
  split at h <;> simp_all

theorem arm_records (e : Env B D) (w : World D) (s : Doc B D) (role : Role) (a sr : Arg) (rtt : Option ℚ) (pv : Arg) :
    (arm e w s role a sr rtt pv).2.records = [] := by
  unfold arm
  repeat' (first | rfl | (dsimp only; rfl) | split)

theorem commit_records (e : Env B D) (w : World D) (s : Doc B D) (role : Role) (dev : D) (cb sb : B) :
    (commit e w s role dev cb sb).2.records = [] := by
  rcases commit_shape e w s role dev cb sb with ⟨st, c, h⟩ | ⟨_, _, h⟩ | ⟨_, cd, _, h⟩ <;> rw [h] <;> rfl

/-- `arm` hands out only the sender's own code, at the current attempt. -/
theorem arm_codes {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {a sr : Arg} {rtt : Option ℚ} {pv : Arg} {x : Code}
    (h : x ∈ (arm e w s role a sr rtt pv).2.codes) :
    x.role = role ∧ x.attempt = s.attempt ∧ x.seed = s.seed_hex := by
  unfold arm at h
  split at h
  · simp [Resp.codes] at h
  split at h
  · simp [Resp.codes] at h
  split at h
  · simp [Resp.codes] at h
  split at h
  · simp [Resp.codes] at h
  split at h
  · simp [Resp.codes] at h
  split at h
  · split at h
    · simp [Resp.codes] at h
    split at h
    · simp [Resp.codes] at h
    have := arm_material_codes h
    subst this
    exact ⟨rfl, rfl, rfl⟩
  split at h
  · simp [Resp.codes] at h
  dsimp only at h
  have := arm_material_codes h
  subst this
  split <;> exact ⟨rfl, rfl, rfl⟩

/-! ## M5: the partner's code only after your own commit -/

/-- **M5, the codes.** Any code in any response to any request has this session's seed, and comes in one of two
ways. Both need good auth and a member.
* From `arm`: it is the sender's own code, for the current attempt.
* From `commit`: it is the partner's code, for the current attempt. After the request the session is started
  at that attempt, the sender's commit is stored, and it was accepted at a clock read of t0 + 1200 or later.

The partner's commit isn't needed: a device can get the partner's code before the partner has committed.
This is only what the server sends. The partner's code is also played out loud, and a colluding partner can
hand it over at arm (CP1). A `noauth_load` answers `Resp.other`, which holds no code by how it's built, so this is no
claim about what those out-of-scope routes send. It says nothing about the air (CN1). -/
theorem M5_codes {e : Env B D} {c : ℕ} {s : Doc B D} {w : World D} {x : Code} (req : Req B D)
    (h : Reachable e c s) (hcw : c ≤ w.now) (hx : x ∈ (step e w req s).2.codes) :
    x.seed = s.seed_hex ∧ ∃ dev role o, req = .api false (some dev) false (.op o) ∧
      role_of (load e w s) dev = some role ∧
      (((∃ a sr rtt pv, o = .arm a sr rtt pv) ∧ x.role = role ∧ x.attempt = (load e w s).attempt) ∨
       ((∃ cb sb, o = .commit cb sb) ∧ x.role = OTHER role ∧
         (step e w req s).1.state = .started ∧ (step e w req s).1.attempt = x.attempt ∧
         (step e w req s).1.committed role = true ∧
         ∃ t cd, (step e w req s).1.t0_ms = some t ∧ ((step e w req s).1.per_role role).commit = some cd ∧
           t + K.COMMIT_GATE_MS ≤ cd.committed_ms)) := by
  have hi := M9 h
  have hl := expire_inv (w := w) hi hcw
  have hseed : (load e w s).seed_hex = s.seed_hex := (frame_expire hi).seed
  have hs' := step_inv (w := w) req hi hcw
  unfold step at hx hs' ⊢
  split at hx
  · simp [Resp.codes] at hx
  split at hx
  · simp [Resp.codes] at hx
  rename_i j _ sender sh body h1
  simp only [h1, ite_false, Bool.false_eq_true] at hs' ⊢
  split at hx
  · simp [Resp.codes] at hx
  rename_i dev
  simp only at hs' ⊢
  split at hx
  · simp [Resp.codes] at hx
  rename_i h3
  simp only [h3, ite_false, Bool.false_eq_true] at hs' ⊢
  simp only [Bool.not_eq_true] at h1 h3
  subst h1 h3
  dsimp only at hx hs' ⊢
  split at hx
  · rw [viewOr_codes] at hx; simp at hx
  rename_i o
  simp only at hs' ⊢
  split at hx
  · simp [Resp.codes] at hx
  rename_i role hrole
  simp only [hrole] at hs' ⊢
  refine ?_
  unfold handle at hx hs' ⊢
  split at hx
  · simp [Resp.codes] at hx
  · unfold result at hx
    split at hx <;> simp [Resp.codes] at hx
  · rw [viewOr_codes] at hx; simp at hx
  · rw [viewOr_codes] at hx; simp at hx
  · rename_i a sr rtt pv
    obtain ⟨h1, h2, h3⟩ := arm_codes hx
    exact ⟨h3.trans hseed, dev, role, _, rfl, hrole, Or.inl ⟨⟨_, _, _, _, rfl⟩, h1, h2⟩⟩
  · rename_i cb sb
    have hcore := hs'.toCore
    rcases commit_shape e w (load e w s) role dev cb sb with ⟨st, cc, hc⟩ | ⟨hst, hcom, hc⟩ | ⟨hst, cd, hna, hc⟩
    · dsimp only [load] at hc hx hcore ⊢
      rw [hc] at hx
      simp [Resp.codes] at hx
    · dsimp only [load] at hc hx hcore hst hcom ⊢
      rw [hc] at hx hcore ⊢
      have hxe := partner_bed_codes hx
      subst hxe
      have hc1 := (hcore.com_iff role).1 hcom
      rcases hcd : ((_expire e w s).per_role role).commit with _ | cd
      · simp [hcd] at hc1
      obtain ⟨_, _, _, _, _, _, _, _, _, _, _, _, _, _, _, t, ht, hg⟩ := hcore.com_ok role cd hcd
      exact ⟨hseed, dev, role, _, rfl, hrole, Or.inr ⟨⟨_, _, rfl⟩, rfl, hst, rfl, hcom, t, cd, ht, hcd, hg⟩⟩
    · dsimp only [load] at hc hx hcore hst hna ⊢
      rw [hc] at hx hcore ⊢
      have hxe := partner_bed_codes hx
      subst hxe
      have hcomm : (commitStore (_expire e w s) role cd).committed role = true := by simp [commitStore, _save]
      have hc1 := (hcore.com_iff role).1 hcomm
      rcases hcd : ((commitStore (_expire e w s) role cd).per_role role).commit with _ | cd'
      · simp [hcd] at hc1
      obtain ⟨_, _, _, _, _, _, _, _, _, _, _, _, _, _, _, t, ht, hg⟩ := hcore.com_ok role cd' hcd
      exact ⟨hseed, dev, role, _, rfl, hrole, Or.inr ⟨⟨_, _, rfl⟩, rfl, hst, rfl, hcomm, t, cd', ht, hcd, hg⟩⟩
  · rw [(transcript_quiet e w _ role dev _ _).1] at hx; simp at hx
  · rw [viewOr_codes] at hx; simp at hx

/-- **M5, the partner's code, as the spec words it.** A code of the sender's partner, for attempt k, comes only
from `commit`. At that point the session is started at attempt k, the sender's commit is stored, and it was accepted
at a clock read of t0 + 1200 or later. `arm` can't hand one out. It says nothing about the air (CN1). -/
theorem M5_partner_code {e : Env B D} {c : ℕ} {s : Doc B D} {w : World D} {x : Code} {dev : D} {role : Role} (req : Req B D)
    (h : Reachable e c s) (hcw : c ≤ w.now) (hx : x ∈ (step e w req s).2.codes)
    (hsender : ∃ o, req = .api false (some dev) false (.op o)) (hr : role_of (load e w s) dev = some role)
    (hpartner : x.role = OTHER role) :
    (∃ cb sb, req = .api false (some dev) false (.op (.commit cb sb))) ∧
      (step e w req s).1.state = .started ∧ (step e w req s).1.attempt = x.attempt ∧
      (step e w req s).1.committed role = true ∧
      ∃ t cd, (step e w req s).1.t0_ms = some t ∧ ((step e w req s).1.per_role role).commit = some cd ∧
        t + K.COMMIT_GATE_MS ≤ cd.committed_ms := by
  obtain ⟨_, dev', role', o, hreq, hr', hcase⟩ := M5_codes req h hcw hx
  obtain ⟨o', ho'⟩ := hsender
  rw [ho'] at hreq
  simp only [Req.api.injEq, Option.some.injEq, Body.op.injEq, true_and, and_true] at hreq
  obtain ⟨rfl, rfl⟩ := hreq
  have : role' = role := by rw [hr] at hr'; simpa using hr'.symm
  subst this
  rcases hcase with ⟨_, h1, _⟩ | ⟨⟨cb, sb, ho⟩, _, h2, h3, h4, h5⟩
  · rw [hpartner] at h1
    exact absurd h1 (other_ne _)
  · subst ho
    exact ⟨⟨cb, sb, ho'⟩, h2, h3, h4, h5⟩

theorem commit_strings (e : Env B D) (w : World D) (s : Doc B D) (role : Role) (dev : D) (cb sb : B) :
    (commit e w s role dev cb sb).2.strings = [] := by
  rcases commit_shape e w s role dev cb sb with ⟨st, c, h⟩ | ⟨_, _, h⟩ | ⟨_, cd, _, h⟩ <;> rw [h] <;> rfl

/-- **M5, the seed and the token.** No response from `step` holds a plain `String`. So the join token is in no response
from `step`: `Created` is the only response that holds it, and only `create` makes it, for the host. The seed is different.
In this model it does sit in responses, inside `Code` values (`M5_codes` shows `x.seed = s.seed_hex`). Real responses hold
PCM in that spot. Only A6 in `spec.md` says PCM doesn't give the seed away, and this theorem doesn't show that. It says
nothing about the air (CN1). -/
theorem M5_no_strings {e : Env B D} {w : World D} {s : Doc B D} (req : Req B D) : (step e w req s).2.strings = [] := by
  unfold step
  split
  · rfl
  split
  · rfl
  split
  · rfl
  split
  · rfl
  dsimp only
  split
  · unfold viewOr; split <;> rfl
  · split
    · rfl
    · unfold handle
      split
      · rfl
      · unfold result; split <;> rfl
      · unfold viewOr; split <;> rfl
      · rfl
      · unfold arm
        repeat' (first | rfl | (dsimp only; rfl) | split)
      · exact commit_strings ..
      · exact (transcript_quiet ..).2.2
      · unfold viewOr; split <;> rfl

/-- `create` is where the token goes out. The response's strings are the token and nothing else. A response has no addressee in
this model. That it goes to the host, and only the host, comes from reading `create`: its caller is the host. It says nothing
about the air (CN1). -/
theorem M5_create_token (w : World D) (host : D) (sid nonce : B) (seed token : String) :
    (create w host sid nonce seed token).2.strings = [token] := rfl

/-! ## M6: no partner number while live -/

/-- Every record in a response is the stored result, after the request. -/
theorem step_records {e : Env B D} {w : World D} {s : Doc B D} {rc : Record B D} (req : Req B D)
    (hx : rc ∈ (step e w req s).2.records) : (step e w req s).1.result = some rc := by
  unfold step at hx ⊢
  split at hx
  · simp [Resp.records] at hx
  split at hx
  · simp [Resp.records] at hx
  rename_i h1
  simp only [h1, ite_false, Bool.false_eq_true]
  split at hx
  · simp [Resp.records] at hx
  try simp only
  split at hx
  · simp [Resp.records] at hx
  rename_i h3
  simp only [h3, ite_false, Bool.false_eq_true]
  dsimp only at hx ⊢
  split at hx
  · exact viewOr_records hx
  try simp only
  split at hx
  · simp [Resp.records] at hx
  rename_i role hrole
  try simp only [hrole]
  unfold handle at hx ⊢
  split at hx
  · simpa [Resp.records, view] using hx
  · unfold result at hx ⊢
    split at hx
    · simp [Resp.records] at hx
    · rename_i hres
      simp [Resp.records] at hx
      subst hx
      exact hres
  · exact viewOr_records hx
  · exact viewOr_records hx
  · rw [arm_records] at hx; simp at hx
  · rw [commit_records] at hx; simp at hx
  · rw [(transcript_quiet e w _ role _ _ _).2.1] at hx; simp at hx
  · exact viewOr_records hx

/-- **M6.** If the session is live after a request, the response holds no result record, so no half and no
transcript of anyone. A delta is only in a record's transcript bytes. Reading the response type shows no
other field holds one.

What does leak while live, as `spec.md` M6 says: the flags, `seq`, and `last_failure`, which is a reason and a role. A report
from `combine` tells more than its own words. The witness `retry_shows_reason` has one. A `noauth_load` answers `Resp.other`, which is
empty by how it's built, so this is no claim about what those out-of-scope routes send. It says nothing about the air (CN1). -/
theorem M6 {e : Env B D} {c : ℕ} {s : Doc B D} {w : World D} (req : Req B D)
    (h : Reachable e c s) (hcw : c ≤ w.now) (hl : live (step e w req s).1.state = true) :
    (step e w req s).2.records = [] ∧ (step e w req s).2.halves = [] ∧ (step e w req s).2.transcripts = [] := by
  have hi := step_inv (w := w) req (M9 h) hcw
  have hres := hi.toCore.result_none' hl
  have hnil : (step e w req s).2.records = [] := by
    rcases hr : (step e w req s).2.records with _ | ⟨rc, tl⟩
    · rfl
    · have := step_records (e := e) (w := w) (s := s) (rc := rc) req (by simp [hr])
      rw [hres] at this
      simp at this
  simp [Resp.halves, Resp.transcripts, hnil]

/-- **M6, by another route.** A view doesn't read any transcript field of anyone. Change those fields of any role, the half and
delta included, and the view is the same. It says nothing about the air (CN1). -/
theorem M6_view_ignores (e : Env B D) (w : World D) (s : Doc B D) (viewer r : Role) (x : Option (TxData B)) :
    view e w { s with per_role := upd s.per_role r { s.per_role r with tx := x } } viewer = view e w s viewer := by
  have : (fun y => ((upd s.per_role r { s.per_role r with tx := x }) y).arm.map (·.popt)) =
      fun y => (s.per_role y).arm.map (·.popt) := by
    funext y
    by_cases hy : y = r
    · subst hy; simp
    · simp [upd, hy]
  simp only [view, devId]
  rw [this]

/-! ## M7, M8: at most two attempts, nothing carries over -/

/-- **M7.** `attempt` is 0 or 1, and at most two rows are ever in `attempts`. It only goes up, from 0 to 1. It says
nothing about the air (CN1). -/
theorem M7 {e : Env B D} {c : ℕ} {s : Doc B D} {w : World D} (req : Req B D) (h : Reachable e c s) (hcw : c ≤ w.now) :
    s.attempt ≤ 1 ∧ s.attempts.length ≤ 2 ∧
      ((step e w req s).1.attempt = s.attempt ∨ (s.attempt = 0 ∧ (step e w req s).1.attempt = 1)) := by
  have hi := M9 h
  refine ⟨hi.attempt_le, ?_, (frame_step req hi hcw).attempt⟩
  have hle := hi.attempt_le
  rcases hst : s.state
  · have := (hi.live_row (by simp [hst, live])).1; omega
  · have := (hi.live_row (by simp [hst, live])).1; omega
  · have := (hi.live_row (by simp [hst, live])).1; omega
  · have := (hi.live_row (by simp [hst, live])).1; omega
  · have := (hi.row_done hst).2.1; omega
  · rcases hi.row_aborted hst with ⟨_, _, h3⟩ | ⟨_, _, h3⟩ <;> omega

/-- **M7, M8, the retry.** `next_attempt` is what moves `attempt` (line 317). It clears `armed`, `committed`, `submitted` and
`t0_ms`, and wipes `per_role`. `confirmed` stays. So a measured attempt 1 needs both phones to arm again, as `started` needs
both armed (`M9`). It says nothing about the air (CN1). -/
theorem M8_retry_wipes (s : Doc B D) (rs : Option Reason) (by_ : Option Role) (r : Role) :
    let s' := next_attempt s rs by_
    s'.attempt = s.attempt + 1 ∧ s'.state = .confirmed ∧ s'.t0_ms = none ∧ s'.armed r = false ∧
      s'.committed r = false ∧ s'.submitted r = false ∧ (s'.per_role r).arm = none ∧
      (s'.per_role r).commit = none ∧ (s'.per_role r).tx = none ∧ s'.confirmed r = s.confirmed r :=
  ⟨rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl, rfl⟩

/-- **M8, what's stored is pinned.** A stored commit and a stored transcript decode to the current attempt. So nothing
from attempt k sits in the `per_role` of attempt k + 1. It says nothing about the air (CN1). -/
theorem M8_pins {e : Env B D} {c : ℕ} {s : Doc B D} (h : Reachable e c s) (r : Role) :
    (∀ cd, (s.per_role r).commit = some cd → ∃ raw cm, e.b64d cd.commit_b64 = some raw ∧
      e.p.decode_commit raw = some cm ∧ cm.attempt = s.attempt) ∧
    (∀ td, (s.per_role r).tx = some td → ∃ raw t, e.b64d td.transcript_b64 = some raw ∧
      e.p.decode_transcript raw = some t ∧ t.attempt = s.attempt) := by
  have hi := M9 h
  constructor
  · intro cd hcd
    obtain ⟨_, raw, _, cm, _, h2, _, h4, _, _, h7, _⟩ := hi.com_ok r cd hcd
    exact ⟨raw, cm, h2, h4, h7⟩
  · intro td htd
    obtain ⟨_, _, raw, _, t, _, _, h3, _, hck, _⟩ := hi.tx_ok r td htd
    rw [check_transcript_ok_iff] at hck
    exact ⟨raw, t, h3, hck.1, hck.2.2.2.2.2.2.1⟩

/-- **M8, an old signed transcript.** It gets 409 `stale_attempt`, and nothing changes. It says nothing about the air (CN1). -/
theorem M8_stale_transcript {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {dev : D} {tb sb raw sig pk : B}
    {t : Transcript B} (hst : s.state = .confirmed ∨ s.state = .started) (h1 : e.b64d tb = some raw) (h2 : e.b64d sb = some sig)
    (h3 : e.p.decode_transcript raw = some t) (hlt : t.attempt < s.attempt) (hp : _pk e s role = some pk)
    (hv : e.p.verify_raw pk raw sig = true) :
    transcript e w s role dev tb sb = (s, .error 409 .stale_attempt) := by
  have : staleTranscript e s role tb sb = true := by
    simp only [staleTranscript, h1, h2, h3, hp]
    simp [hlt, hv, _stale, Nat.blt_eq]
    rcases hst with h | h <;> simp [h]
  simp [transcript, this]

/-- **M8, an old fail.** It gets 409 `stale_attempt`, and nothing changes. It says nothing about the air (CN1). -/
theorem M8_stale_fail {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {n : ℤ} {rsn : Reason}
    (hst : s.state = .confirmed ∨ s.state = .started) (hr : rsn ∈ PHONE_REASONS) (hlt : n < (s.attempt : ℤ)) :
    fail_ e w s role (.int n) (some rsn) = .error (409, .stale_attempt) := by
  have : _stale s n = true := by
    simp only [_stale, hlt, decide_true, Bool.and_true]
    rcases hst with h | h <;> simp [h]
  simp [fail_, hr, _int, this]

/-- **M8, an old commit while started.** A commit signed by the sender for another attempt gets 400 `transcript_mismatch`.
Nothing changes. It says nothing about the air (CN1). -/
theorem M8_old_commit_started {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {dev : D} {cb sb raw sig : B} {cm : Commit B}
    (hs : s.state = .started) (h1 : e.b64d cb = some raw) (h2 : e.b64d sb = some sig) (h3 : e.p.decode_commit raw = some cm)
    (hv : e.p.verify_raw (e.pk dev) raw sig = true) (ha : cm.attempt ≠ s.attempt) :
    commit e w s role dev cb sb = (s, .error 400 (.reason .transcript_mismatch)) := by
  simp [commit, hs, h1, h2, h3, hv, ha]

/-- **M8, a commit when not started.** Any commit, from an old attempt or not, gets 409 `bad_state`. The state is checked
first, so nothing in the commit is read. Nothing changes. It says nothing about the air (CN1). -/
theorem M8_old_commit_not_started {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {dev : D} {cb sb : B}
    (hs : s.state ≠ .started) : commit e w s role dev cb sb = (s, .error 409 .bad_state) := by
  simp [commit, hs]

/-- The bytes hashed by `bed_key`, `jbl250.py:47`: `pop-v1|seed|JBL250|role|attempt|bed`. `seed` stands for `seed_hex.strip().lower()`.
The digit is for an attempt below 10, and `jbl250.py:45-46` refuses anything else but 0 and 1. -/
def bed_msg (seed : String) (r : Role) (k : ℕ) : List Char :=
  "pop-v1|".toList ++ seed.toList ++ "|JBL250|".toList ++
    [(match r with | .A => 'A' | .B => 'B'), '|', Nat.digitChar k] ++ "|bed".toList

/-- `jbl250.bed_key`, with `sha` for SHA-256. -/
def bed_key (sha : List Char → B) (seed : String) (r : Role) (k : ℕ) : B := sha (bed_msg seed r k)

/-- **M8, the messages.** Two roles and two attempts give four different messages to hash, for one seed. This needs no
assumption about any hash. It says nothing about the air (CN1). -/
theorem bed_msg_eq_iff (seed : String) (r r' : Role) (k k' : ℕ) (hk : k < K.MAX_ATTEMPTS) (hk' : k' < K.MAX_ATTEMPTS) :
    bed_msg seed r k = bed_msg seed r' k' ↔ r = r' ∧ k = k' := by
  constructor
  · intro h1
    simp only [bed_msg, List.append_assoc, List.append_cancel_left_eq, List.append_cancel_right_eq,
      List.cons_append, List.nil_append, List.cons.injEq, true_and] at h1
    have : k = 0 ∨ k = 1 := by simp [K.MAX_ATTEMPTS] at hk; omega
    have : k' = 0 ∨ k' = 1 := by simp [K.MAX_ATTEMPTS] at hk'; omega
    rcases ‹k = 0 ∨ k = 1› with rfl | rfl <;> rcases ‹k' = 0 ∨ k' = 1› with rfl | rfl <;> cases r <;> cases r' <;>
      simp_all [Nat.digitChar]
  · rintro ⟨rfl, rfl⟩; rfl

/-- **M8, the keys.** Take any function `sha` with no collision among the four messages of one seed (`hsha`). Then the two
roles and two attempts give four different keys for that seed. `hsha` is about those four strings only, so real SHA-256 can
meet it. A5 is what says it does. That isn't checked here, and SHA-256 itself isn't in this model, since `sha` is any function
with that property. That different keys give different sound isn't shown here: `Code` hides that, and audio is out of scope.
In the model two `Code` values with another role or attempt differ just by being a different structure. So this theorem is the
only one about how the keys are derived. It says nothing about the air (CN1). -/
theorem M8_keys {sha : List Char → B} (seed : String)
    (hsha : ∀ r r' k k', k < K.MAX_ATTEMPTS → k' < K.MAX_ATTEMPTS →
      sha (bed_msg seed r k) = sha (bed_msg seed r' k') → bed_msg seed r k = bed_msg seed r' k')
    (r r' : Role) (k k' : ℕ) (hk : k < K.MAX_ATTEMPTS) (hk' : k' < K.MAX_ATTEMPTS) :
    bed_key sha seed r k = bed_key sha seed r' k' ↔ r = r' ∧ k = k' := by
  constructor
  · intro h
    exact (bed_msg_eq_iff seed r r' k k' hk hk').1 (hsha r r' k k' hk hk' h)
  · rintro ⟨rfl, rfl⟩; rfl

/-! ## M10: the first one stays -/

/-- **M10, the first stays.** While the attempt doesn't change, a stored commit and a stored transcript never change. It says
nothing about the air (CN1). -/
theorem M10_stays {e : Env B D} {c : ℕ} {s : Doc B D} {w : World D} (req : Req B D) (h : Reachable e c s) (hcw : c ≤ w.now)
    (r : Role) (hsame : (step e w req s).1.attempt = s.attempt) :
    (∀ cd, (s.per_role r).commit = some cd → ((step e w req s).1.per_role r).commit = some cd) ∧
    (∀ td, (s.per_role r).tx = some td → ((step e w req s).1.per_role r).tx = some td) := by
  have hf := frame_step req (M9 h) hcw
  exact ⟨fun cd hc => hf.keep_commit r cd hc hsame, fun td ht => hf.keep_tx r td ht hsame⟩

/-- **M10, a repeated commit changes nothing.** Any commit from a role already committed leaves the document as it is. This
holds with a fresh signature too (`spec.md` M10 note). This one is only about the document. `M10_commit_repeat_answer` is about
the answer. It says nothing about the air (CN1). -/
theorem M10_commit_repeat {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {dev : D} {cb sb : B}
    (hc : s.committed role = true) : (commit e w s role dev cb sb).1 = s := by
  rcases commit_shape e w s role dev cb sb with ⟨st, c, h⟩ | ⟨_, _, h⟩ | ⟨_, cd, hna, h⟩
  · rw [h]
  · rw [h]
  · rw [hc] at hna; simp at hna

/-- **M10, the answer to a repeated commit.** While started, a commit with the stored `commit_b64` that passes the checks gets
the partner's bed again, and nothing changes. The signature isn't compared, so a fresh valid one gets this too (`spec.md`
M10 note). It says nothing about the air (CN1). -/
theorem M10_commit_repeat_answer {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {dev : D} {cb sb raw sig : B}
    {cm : Commit B} (hs : s.state = .started) (hc : s.committed role = true)
    (h1 : e.b64d cb = some raw) (h2 : e.b64d sb = some sig) (h3 : e.p.decode_commit raw = some cm)
    (hv : e.p.verify_raw (e.pk dev) raw sig = true) (hr : cm.role = role) (ha : cm.attempt = s.attempt)
    (hn : cm.nonce = s.nonce_hex) (hver : cm.version = _popt s role)
    (hd : (s.per_role role).commit.map (·.commit_b64) = some cb) :
    commit e w s role dev cb sb = (s, _partner_bed s role) := by
  simp [commit, hs, h1, h2, h3, hv, hr, ha, hn, hver, hc, hd]

/-- **M10, resending the stored commit.** On a reachable started document, the sender's own stored strings pass every check
again, so the answer is the partner's bed and nothing changes. `hk` says `dev` holds the key of that role. It says nothing
about the air (CN1). -/
theorem M10_commit_resend {e : Env B D} {c : ℕ} {w : World D} {s : Doc B D} {role : Role} {dev : D} {cd : CommitData B}
    (h : Reachable e c s) (hs : s.state = .started) (hcd : (s.per_role role).commit = some cd)
    (hk : _pk e s role = some (e.pk dev)) :
    commit e w s role dev cd.commit_b64 cd.commit_sig_b64 = (s, _partner_bed s role) := by
  have hi := M9 h
  obtain ⟨pk, raw, sig, cm, hp, h1, h2, h3, hv, hr, ha, hn, hver, _⟩ := hi.com_ok role cd hcd
  rw [hk] at hp
  simp only [Option.some.injEq] at hp
  subst hp
  exact M10_commit_repeat_answer hs ((hi.com_iff role).2 (by simp [hcd])) h1 h2 h3 hv hr ha hn hver (by simp [hcd])

/-- **M10, a different commit.** One that passes the checks before it gets 409 `already_committed`. It says nothing about the air (CN1). -/
theorem M10_commit_different {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {dev : D} {cb sb raw sig : B}
    {cm : Commit B} (hs : s.state = .started) (hc : s.committed role = true)
    (h1 : e.b64d cb = some raw) (h2 : e.b64d sb = some sig) (h3 : e.p.decode_commit raw = some cm)
    (hv : e.p.verify_raw (e.pk dev) raw sig = true) (hr : cm.role = role) (ha : cm.attempt = s.attempt)
    (hn : cm.nonce = s.nonce_hex) (hver : cm.version = _popt s role)
    (hd : (s.per_role role).commit.map (·.commit_b64) ≠ some cb) :
    commit e w s role dev cb sb = (s, .error 409 .already_committed) := by
  simp [commit, hs, h1, h2, h3, hv, hr, ha, hn, hver, hc]
  intro x hx hy
  exact (hd (by simp [hx, hy])).elim

/-- **M10, a repeated transcript changes nothing.** Any transcript from a role that has submitted leaves the document as
it is. This one is only about the document. `M10_tx_repeat_answer` is about the answer. It says nothing about the air (CN1). -/
theorem M10_tx_repeat {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {dev : D} {tb sb : B}
    (hc : s.submitted role = true) : (transcript e w s role dev tb sb).1 = s := by
  unfold transcript
  split
  · rfl
  split
  · rfl
  try simp only [hc, ite_true]
  split
  · split <;> rfl
  · rfl

/-- **M10, the answer to a repeated transcript.** On a reachable started document, the same two strings again get
`accepted`, with the state and attempt as stored, and nothing changes. `Reachable` is needed: M9 says the stored transcript
is for this attempt, so it can't count as an old one. It says nothing about the air (CN1). -/
theorem M10_tx_repeat_answer {e : Env B D} {c : ℕ} {w : World D} {s : Doc B D} {role : Role} {dev : D} {td : TxData B}
    (h : Reachable e c s) (hs : s.state = .started) (htd : (s.per_role role).tx = some td) :
    transcript e w s role dev td.transcript_b64 td.sig_b64 = (s, .accepted s.state s.attempt) := by
  have hsub : s.submitted role = true := ((M9 h).sub_iff role).2 (by simp [htd])
  have hns : staleTranscript e s role td.transcript_b64 td.sig_b64 = false := by
    obtain ⟨raw, t, h1, h3, ha⟩ := (M8_pins h role).2 td htd
    cases hsg : e.b64d td.sig_b64 <;> simp [staleTranscript, h1, hsg, h3, ha, _stale]
  simp [transcript, hns, hs, hsub, htd]

/-- **M10, a different transcript.** While started, one that isn't an old signed one gets 409 `already_submitted`, with no signature
check. A fresh signature on the same bytes counts as different. It says nothing about the air (CN1). -/
theorem M10_tx_different {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {dev : D} {tb sb : B} {td : TxData B}
    (hs : s.state = .started) (hc : s.submitted role = true) (hns : staleTranscript e s role tb sb = false)
    (htd : (s.per_role role).tx = some td) (hd : ¬ (td.transcript_b64 = tb ∧ td.sig_b64 = sb)) :
    transcript e w s role dev tb sb = (s, .error 409 .already_submitted) := by
  simp [transcript, hs, hc, hns, htd]
  exact fun a b => hd ⟨a, b⟩

/-- **M10, once the session moved on: the document.** When the state isn't started, a transcript or a commit leaves the document
as it is. This one is only about the document. The answers are in the next theorems. It says nothing about the air (CN1). -/
theorem M10_not_started {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {dev : D} {a b : B} (hs : s.state ≠ .started) :
    (transcript e w s role dev a b).1 = s ∧ (commit e w s role dev a b).1 = s := by
  constructor
  · unfold transcript
    split
    · rfl
    · simp [hs]
  · simp [commit, hs]

/-- **M10, the answer to a commit when not started.** 409 `bad_state`, and nothing changes. It says nothing about the air (CN1). -/
theorem M10_not_started_commit {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {dev : D} {a b : B}
    (hs : s.state ≠ .started) : commit e w s role dev a b = (s, .error 409 .bad_state) :=
  M8_old_commit_not_started hs

/-- **M10, the answer to a transcript when not started.** A signed old one gets 409 `stale_attempt`. Anything else gets 409
`bad_state`. Nothing changes either way. It says nothing about the air (CN1). -/
theorem M10_not_started_transcript {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {dev : D} {a b : B}
    (hs : s.state ≠ .started) :
    (staleTranscript e s role a b = true → transcript e w s role dev a b = (s, .error 409 .stale_attempt)) ∧
    (staleTranscript e s role a b = false → transcript e w s role dev a b = (s, .error 409 .bad_state)) := by
  constructor
  · intro h; simp [transcript, h]
  · intro h; simp [transcript, h, hs]

/-- **M10, a transcript once the session is over.** When done or aborted, every transcript gets 409 `bad_state`, a signed old
one too (`spec.md` M10, first bullet). Nothing changes. It says nothing about the air (CN1). -/
theorem M10_over_transcript {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {dev : D} {a b : B}
    (hs : s.state = .done ∨ s.state = .aborted) :
    transcript e w s role dev a b = (s, .error 409 .bad_state) := by
  have hst : s.state ≠ .started := by rcases hs with h | h <;> simp [h]
  have hc : s.state ≠ .confirmed := by rcases hs with h | h <;> simp [h]
  have hns : staleTranscript e s role a b = false := by
    unfold staleTranscript
    split
    · split
      · simp [_stale, hst, hc]
      · rfl
    · rfl
  exact (M10_not_started_transcript hst).2 hns

/-! ## M11: timing of a NEAR -/

/-- **M11.** Say the record has verdict NEAR. With one clock read per step, `finished_ms` is the clock read n of the load
at the top of the finalizing request. Then n is at most t0 + 20000, and at most `created_ms` + 600000. Both edges pass, since the
tests in `_expire` are strict. Both commits were accepted at t0 + 1200 or later. Both arms were at t0 - 3000 or earlier. That last
one uses A7. The real code has several clock reads in a handler, so a real `finished_ms` can be a bit later (`spec.md` M11).

This is the schedule on the server's clock. It does not show when any sound was played, and it does not show a phone told the
truth about the air (CN1). -/
theorem M11 {e : Env B D} {c : ℕ} {s : Doc B D} {rc : Record B D} (h : Reachable e c s)
    (hr : s.result = some rc) (hv : rc.verdict = .NEAR) :
    ∃ t n, s.t0_ms = some t ∧ s.finished_ms = some n ∧ s.created_ms ≤ n ∧ n ≤ t + 20000 ∧ n ≤ s.created_ms + 600000 ∧
      ∀ r, ∃ a cd, (s.per_role r).arm = some a ∧ (s.per_role r).commit = some cd ∧
        t + 1200 ≤ cd.committed_ms ∧ a.armed_ms + 3000 ≤ t := by
  have hi := M9 h
  have nf := hi.near rc hr hv
  obtain ⟨t, n, ht, hn, hc, h1, h2⟩ := nf.time
  have h1' : n ≤ t + 20000 := h1
  have h2' : n - s.created_ms ≤ 600000 := h2
  refine ⟨t, n, ht, hn, hc, h1', by omega, ?_⟩
  intro r
  have hsub : s.submitted r = true := by
    have := nf.both
    simp only [all2, Bool.and_eq_true] at this
    cases r
    · exact this.1
    · exact this.2
  have hcom := hi.sub_com r hsub
  have harm := hi.com_arm r hcom
  rcases hcd : (s.per_role r).commit with _ | cd
  · have := (hi.com_iff r).1 hcom; simp [hcd] at this
  rcases ha : (s.per_role r).arm with _ | a
  · have := (hi.arm_iff r).1 harm; simp [ha] at this
  refine ⟨a, cd, rfl, rfl, ?_, ?_⟩
  · obtain ⟨_, _, _, _, _, _, _, _, _, _, _, _, _, _, _, t', ht', hg⟩ := hi.com_ok r cd hcd
    rw [ht] at ht'
    simp only [Option.some.injEq] at ht'
    subst ht'
    exact hg
  · exact (hi.arm_ok r a ha).2.2.2.2 t ht

/-! ## M12: who can move what -/

/-- **M12, no auth.** A request that fails auth stops before the load. So do bad JSON and a bad body shape. Nothing changes.
It says nothing about the air (CN1). -/
theorem M12_no_auth (e : Env B D) (w : World D) (s : Doc B D) (j sh : Bool) (b : Body B) :
    (step e w (.api j none sh b) s).1 = s := by
  simp only [step]
  split <;> rfl

theorem M12_bad_json (e : Env B D) (w : World D) (s : Doc B D) (x : Option D) (sh : Bool) (b : Body B) :
    (step e w (.api true x sh b) s).1 = s := rfl

theorem M12_bad_shape (e : Env B D) (w : World D) (s : Doc B D) (j : Bool) (x : Option D) (b : Body B) :
    (step e w (.api j x true b) s).1 = s := by
  simp only [step]
  split
  · rfl
  · split <;> rfl

/-- **M12, `_expire` is the exception.** It runs in `load`, before the member check. So anyone who knows the session id fires it: a
non-member, or a route with no auth at all. The change is only what the clock already dictates. A non-member's request
does that and nothing else. It says nothing about the air (CN1). -/
theorem M12_non_member (e : Env B D) (w : World D) (s : Doc B D) (dev : D) (o : Op B) (hn : role_of (load e w s) dev = none) :
    (step e w (.api false (some dev) false (.op o)) s).1 = load e w s := by
  simp [step, hn]

/-- **M12, a member starts the same way.** A member's request also runs on `load e w s`, so it fires the same `_expire`. This is
the reason a non-member's request adds nothing the clock and a member wouldn't do. It says nothing about the air (CN1). -/
theorem M12_member_load (e : Env B D) (w : World D) (s : Doc B D) (dev : D) (r : Role) (o : Op B)
    (hr : role_of (load e w s) dev = some r) :
    step e w (.api false (some dev) false (.op o)) s = handle e w (load e w s) r dev o := by
  simp [step, hr]

theorem M12_noauth_load (e : Env B D) (w : World D) (s : Doc B D) :
    (step e w (.noauth_load) s).1 = load e w s := rfl

/-- **M12, roles are fixed.** The host never changes. A guest, once set, never changes. Host and guest are never the same. It
says nothing about the air (CN1). -/
theorem M12_roles {e : Env B D} {c : ℕ} {s : Doc B D} {w : World D} (req : Req B D) (h : Reachable e c s) (hcw : c ≤ w.now) :
    (step e w req s).1.host_device_id = s.host_device_id ∧
    (∀ g, s.guest_device_id = some g → (step e w req s).1.guest_device_id = some g) ∧
    s.guest_device_id ≠ some s.host_device_id := by
  have hf := frame_step req (M9 h) hcw
  exact ⟨hf.host, hf.guest, (M9 h).guest_ne⟩

theorem join_ok {w : World D} {s s' : Doc B D} {d : D} {tok : String} (hj : join w s d tok = .ok s') :
    d ≠ s.host_device_id ∧ s.guest_device_id = none ∧ tok.toLower = s.join_token ∧ s.state = .created := by
  unfold join at hj
  split at hj
  · simp at hj
  rename_i h1
  split at hj
  · simp at hj
  rename_i h2
  split at hj
  · simp at hj
  rename_i h3
  split at hj
  · simp at hj
  rename_i h4
  exact ⟨h1, by simpa using h2, by simpa using h3, by by_contra hh; exact h4 (Or.inl hh)⟩

/-- **M12, every handler change is from a member, or a `join` with the token.** If a request leaves a stored document that
is neither the old one nor what the load alone would leave, then the sender passed auth. It is a member, or this is a
`join`. And a `join` that goes through had the right token, a sender who isn't the host, no guest yet, and a session in
`created`. So roles come only from `create` and `join`. It says nothing about the air (CN1). -/
theorem M12_member {e : Env B D} {s : Doc B D} {w : World D} (req : Req B D)
    (hne : (step e w req s).1 ≠ s) (hnl : (step e w req s).1 ≠ load e w s) :
    ∃ dev, (∃ o role, req = .api false (some dev) false (.op o) ∧ role_of (load e w s) dev = some role) ∨
      (∃ tok, req = .api false (some dev) false (.join tok) ∧ dev ≠ (load e w s).host_device_id ∧
        tok.toLower = (load e w s).join_token ∧ (load e w s).guest_device_id = none ∧ (load e w s).state = .created) := by
  cases req with
  | noauth_load => exact absurd rfl hnl
  | api j x sh b =>
    cases j with
    | true => exact absurd (M12_bad_json e w s x sh b) hne
    | false =>
      cases x with
      | none => exact absurd (M12_no_auth e w s false sh b) hne
      | some dev =>
        cases sh with
        | true => exact absurd (M12_bad_shape e w s false (some dev) b) hne
        | false =>
          cases b with
          | join tok =>
            have hs : (step e w (.api false (some dev) false (.join tok)) s).1 =
                (viewOr e w (load e w s) .B (join w (load e w s) dev tok)).1 := by simp [step]
            rcases hj : join w (load e w s) dev tok with x | s'
            · rw [hs, hj] at hnl
              exact absurd rfl hnl
            · obtain ⟨h1, h2, h3, h4⟩ := join_ok hj
              exact ⟨dev, Or.inr ⟨tok, rfl, h1, h3, h2, h4⟩⟩
          | op o =>
            rcases hr : role_of (load e w s) dev with _ | role
            · exact absurd (M12_non_member e w s dev o hr) hnl
            · exact ⟨dev, Or.inl ⟨o, role, rfl, hr⟩⟩

/-- **M13.** The fields fixed at create stay. It says nothing about the air (CN1). -/
theorem M13 {e : Env B D} {c : ℕ} {s : Doc B D} {w : World D} (req : Req B D) (h : Reachable e c s) (hcw : c ≤ w.now) :
    let s' := (step e w req s).1
    s'.session_id = s.session_id ∧ s'.seed_hex = s.seed_hex ∧ s'.nonce_hex = s.nonce_hex ∧ s'.join_token = s.join_token ∧
      s'.created_ms = s.created_ms ∧ s'.token_expires_ms = s.token_expires_ms ∧ s'.host_device_id = s.host_device_id := by
  have hf := frame_step req (M9 h) hcw
  exact ⟨hf.session_id, hf.seed, hf.nonce, hf.token, hf.created, hf.expires, hf.host⟩

/-! ### M13, `t0_ms` -/

/-- `t0_ms` stays, as long as the attempt number stays. Used only for `M13_t0`. -/
def T0Keep (s s' : Doc B D) : Prop :=
  ∀ t, s.t0_ms = some t → s'.attempt = s.attempt → s'.t0_ms = some t

theorem T0Keep.trans {s s1 s2 : Doc B D} (a : T0Keep s s1) (b : T0Keep s1 s2)
    (ha : s1.attempt = s.attempt ∨ (s.attempt = 0 ∧ s1.attempt = 1))
    (hb : s2.attempt = s1.attempt ∨ (s1.attempt = 0 ∧ s2.attempt = 1)) : T0Keep s s2 := by
  intro t ht h2
  have h1 : s1.attempt = s.attempt := by omega
  exact b t (a t ht h1) (by omega)

theorem t0_failed {e : Env B D} {w : World D} {s : Doc B D} {r : Option Reason} {b : Option Role} :
    T0Keep s (_failed e w s r b) := by
  intro t ht ha
  unfold _failed at ha ⊢
  split at ha
  · simp [next_attempt, _save] at ha
  · rw [ite_eq_right (by assumption)]; exact ht

theorem t0_expire {e : Env B D} {w : World D} {s : Doc B D} : T0Keep s (_expire e w s) := by
  intro t ht ha
  unfold _expire at ha ⊢
  split
  · exact ht
  rename_i h1
  rw [ite_eq_right h1] at ha
  split
  · exact ht
  rename_i h2
  rw [ite_eq_right h2] at ha
  split
  · rename_i h3
    rw [ite_eq_left h3] at ha
    exact t0_failed t ht ha
  · exact ht

theorem t0_join {w : World D} {s s' : Doc B D} {g : D} {tok : String} (hj : join w s g tok = .ok s') :
    T0Keep s s' := by
  intro t ht _
  unfold join at hj
  repeat' split at hj
  all_goals first | (simp at hj; done) | (simp only [Except.ok.injEq] at hj; subst hj; exact ht)

theorem t0_confirm {s s' : Doc B D} {r : Role} (hj : confirm s r = .ok s') : T0Keep s s' := by
  intro t ht _
  unfold confirm at hj
  split at hj
  · simp only [Except.ok.injEq] at hj; subst hj; exact ht
  split at hj
  · simp at hj
  simp only [Except.ok.injEq] at hj
  subst hj
  split <;> exact ht

theorem t0_abort {w : World D} {s : Doc B D} {r : Role} : T0Keep s (abort w s r) := by
  intro t ht _
  unfold abort
  split <;> exact ht

theorem t0_arm {e : Env B D} {c : ℕ} {w : World D} {s : Doc B D} {role : Role} {a sr : Arg} {rtt : Option ℚ} {p : Arg}
    (h : Inv e c s) : T0Keep s (arm e w s role a sr rtt p).1 := by
  intro t ht _
  have hnc : s.state ≠ .confirmed := fun hc => by
    have := (h.toCore.row_confirmed hc).2.2.2.2
    simp [this] at ht
  unfold arm
  repeat' split
  all_goals first | exact ht | (exfalso; simp_all; done)

theorem t0_commit {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {dev : D} {cb sb : B} :
    T0Keep s (commit e w s role dev cb sb).1 := by
  intro t ht _
  unfold commit
  repeat' split
  all_goals exact ht

theorem t0_afterStore {e : Env B D} {w : World D} {s0 s : Doc B D} (ht0 : s.t0_ms = s0.t0_ms) (hat : s.attempt = s0.attempt) :
    T0Keep s0 (afterStore e w s0 s).1 := by
  have hm : T0Keep s0 s0 := fun _ h _ => h
  unfold afterStore
  split
  · exact fun t ht _ => ht0.trans ht
  split
  · split
    · exact fun t ht _ => ht0.trans ht
    · exact hm
    · split
      · intro t ht ha
        exact t0_failed t (ht0.trans ht) (ha.trans hat.symm)
      · exact fun t ht _ => ht0.trans ht
  · exact hm

theorem t0_transcript {e : Env B D} {w : World D} {s : Doc B D} {role : Role} {dev : D} {tb sb : B} :
    T0Keep s (transcript e w s role dev tb sb).1 := by
  have hm : T0Keep s s := fun _ h _ => h
  unfold transcript
  split
  · exact hm
  split
  · exact hm
  split
  · split
    · split
      · exact hm
      · exact hm
    · exact hm
  split
  · exact hm
  split
  · exact hm
  split
  · exact fun t ht _ => ht
  · exact hm
  · exact t0_afterStore rfl rfl

theorem t0_fail {e : Env B D} {w : World D} {s s' : Doc B D} {role : Role} {a : Arg} {rsn : Option Reason}
    (hj : fail_ e w s role a rsn = .ok s') : T0Keep s s' := by
  intro t ht ha
  unfold fail_ at hj
  repeat' split at hj
  all_goals first
    | (simp at hj; done)
    | (simp only [Except.ok.injEq] at hj; subst hj; exact t0_failed t ht ha)

theorem t0_viewOr {e : Env B D} {s : Doc B D} {w : World D} {role : Role} {x : Except (ℕ × Err) (Doc B D)}
    (hok : ∀ s', x = .ok s' → T0Keep s s') : T0Keep s (viewOr e w s role x).1 := by
  unfold viewOr
  split
  · exact hok _ rfl
  · exact fun _ h _ => h

/-- Every request keeps `t0_ms` inside one attempt. -/
theorem t0_step {e : Env B D} {c : ℕ} {s : Doc B D} {w : World D} (req : Req B D)
    (h : Inv e c s) (hcw : c ≤ w.now) : T0Keep s (step e w req s).1 := by
  have hl := expire_inv (w := w) h hcw
  have hfe : Frame s (_expire e w s) := frame_expire h
  have hm : T0Keep s s := fun _ h _ => h
  unfold step
  split
  · exact t0_expire
  split
  · exact hm
  split
  · exact hm
  split
  · exact hm
  dsimp only [load]
  split
  · exact t0_expire.trans (t0_viewOr (fun s' hs' => t0_join hs')) hfe.attempt
      (frame_viewOr (fun s' hs' => frame_join hl hs')).attempt
  · split
    · exact t0_expire
    · unfold handle
      split
      · exact t0_expire
      · unfold result; split <;> exact t0_expire
      · exact t0_expire.trans (t0_viewOr (fun s' hs' => t0_confirm hs')) hfe.attempt
          (frame_viewOr (fun s' hs' => frame_confirm hs')).attempt
      · exact t0_expire.trans (t0_viewOr (fun s' hs' => by
          simp only [Except.ok.injEq] at hs'
          subst hs'
          exact t0_abort)) hfe.attempt
          (frame_viewOr (fun s' hs' => by
          simp only [Except.ok.injEq] at hs'
          subst hs'
          exact frame_abort hl)).attempt
      · exact t0_expire.trans (t0_arm hl) hfe.attempt (frame_arm hl).attempt
      · exact t0_expire.trans t0_commit hfe.attempt (frame_commit hl).attempt
      · exact t0_expire.trans t0_transcript hfe.attempt (frame_transcript hl).attempt
      · exact t0_expire.trans (t0_viewOr (fun s' hs' => t0_fail hs')) hfe.attempt
          (frame_viewOr (fun s' hs' => frame_fail hl hs')).attempt

/-- **M13, `t0_ms`.** Inside one attempt, `t0_ms` is written once. Once it's set, no request changes it, unless that request moves
to the next attempt. `M8_retry_wipes` shows the move clears it. `row_confirmed` and `row_started` of `Inv` show it's none before the
second arm and set after it. It says nothing about the air (CN1). -/
theorem M13_t0 {e : Env B D} {c : ℕ} {s : Doc B D} {w : World D} (req : Req B D) (h : Reachable e c s) (hcw : c ≤ w.now)
    {t : ℕ} (ht : s.t0_ms = some t) (ha : (step e w req s).1.attempt = s.attempt) : (step e w req s).1.t0_ms = some t :=
  t0_step req (M9 h) hcw t ht ha

/-- **M9, as a table.** The "all" rows of `spec.md` M9 read off `Inv`. The rows per state are the fields `row_created` to `row_aborted` of `Core`, and `verdict_row` is "if verdict: both submitted". It says
nothing about the air (CN1). -/
theorem M9_table {e : Env B D} {c : ℕ} {s : Doc B D} (h : Reachable e c s) (r : Role) :
    s.attempt ≤ 1 ∧ s.guest_device_id ≠ some s.host_device_id ∧
    (s.submitted r = true → s.committed r = true) ∧ (s.committed r = true → s.armed r = true) ∧
    (∀ i (hi : i < s.attempts.length), s.attempts[i].attempt = i) ∧
    (s.result.isSome = true ↔ s.state = .done) ∧
    (s.committed r = true ↔ (s.per_role r).commit.isSome = true) ∧
    (s.submitted r = true ↔ (s.per_role r).tx.isSome = true) ∧
    (s.armed r = true ↔ (s.per_role r).arm.isSome = true) ∧
    (s.state = .started → all2 s.submitted = false) := by
  have hi := M9 h
  refine ⟨hi.attempt_le, hi.guest_ne, hi.sub_com r, hi.com_arm r, ?_, hi.result_iff, hi.com_iff r, hi.sub_iff r,
    hi.arm_iff r, hi.started_not_all⟩
  intro i hx
  have hr := hi.rows
  have h1 : (s.attempts.map (·.attempt))[i]'(by simpa using hx) = (List.range s.attempts.length)[i]'(by simpa using hx) := by
    simp only [hr]
  simpa using h1

/-- `confirmed` flags only go from false to true. Row "all" of `spec.md` M9, about two documents. It says nothing about the air (CN1). -/
theorem M9_confirmed {e : Env B D} {c : ℕ} {s : Doc B D} {w : World D} (req : Req B D) (h : Reachable e c s) (hcw : c ≤ w.now)
    (r : Role) (hc : s.confirmed r = true) : (step e w req s).1.confirmed r = true :=
  (frame_step req (M9 h) hcw).confirmed r hc

/-! ## Concrete runs: the theorems above are not empty

Plain numbers stand for byte strings, as in `Verdict.lean`. The two signers pick their numbers by hand. No audio exists
anywhere. One run reaches NEAR, one reaches `too_far`, one retries and then reaches NEAR. So a NEAR here is not evidence of any
distance: see `X1` and CN1. -/

namespace Witness

/-- The toy transcript of a raw number. Rate 48000, self check 0. Commit raw numbers: 10 and 20 at attempt 0, 30 and
40 at attempt 1. A transcript's raw number is its commit's plus 1. -/
def tx (H : ℕ → Role → ℤ) (role : Role) (k raw : ℕ) : Transcript ℕ :=
  { role := role, attempt := k, nonce := 9
    pk_self := (match role with | .A => 1 | .B => 2)
    pk_partner := (match role with | .A => 2 | .B => 1)
    sample_rate := 48000, half := H k role, rec_ := 77, play_frame_position := 0, play_nano_time := 0
    rec_frame0_nano_time := 0, self_os_delta := 0, commit_hash := raw - 1 + 1000, version := 1
    a_self := none, p_partner := none, delta := none, code_commit := none }

/-- The toy signature check accepts only the eight messages each key signs. The signature of m is m + 100. -/
def okSig (pk m : ℕ) : Bool :=
  (pk == 1 && (m == 10 || m == 11 || m == 30 || m == 31)) ||
  (pk == 2 && (m == 20 || m == 21 || m == 40 || m == 41))

/-- The toy setting. `H k r` is the half role r signs at attempt k. Device 1 has key 1, device 2 has key 2. -/
def env (H : ℕ → Role → ℤ) : Env ℕ ℕ where
  p :=
    { width := fun _ => 0
      verify_raw := fun pk m s => okSig pk m && s == m + 100
      sha256 := fun m => m + 1000
      rec_root_ok := fun _ => true
      decode_commit := fun raw =>
        if raw = 10 then some ⟨.A, 0, 9, 77, 1⟩ else if raw = 20 then some ⟨.B, 0, 9, 77, 1⟩
        else if raw = 30 then some ⟨.A, 1, 9, 77, 1⟩ else if raw = 40 then some ⟨.B, 1, 9, 77, 1⟩ else none
      decode_transcript := fun raw =>
        if raw = 11 then some (tx H .A 0 raw) else if raw = 21 then some (tx H .B 0 raw)
        else if raw = 31 then some (tx H .A 1 raw) else if raw = 41 then some (tx H .B 1 raw) else none }
  b64d := some
  pk := id
  code_commit := fun _ _ _ => 55

/-- A clock read, with no calibration on any device. -/
def W (n : ℕ) : World ℕ := ⟨n, fun _ => 0⟩

/-- A request with good auth and a good shape. -/
def R (dev : ℕ) (o : Op ℕ) : Req ℕ ℕ := .api false (some dev) false (.op o)

/-- The opening: create at 0, join, both confirm. The token is lower case. -/
def opening : List (ℕ × Req ℕ ℕ) :=
  [(1, .api false (some 2) false (.join "t")), (2, R 1 .confirm), (3, R 2 .confirm)]

/-- One measured attempt, from time `n`. Arm, wait for the gate, commit, send transcripts. `a` is the raw commit number of A,
`b` of B. -/
def attemptRun (n k a b : ℕ) : List (ℕ × Req ℕ ℕ) :=
  [(n, R 1 (.arm (.int k) (.int 48000) (some 10) .null)),
   (n + 1, R 2 (.arm (.int k) (.int 48000) (some 10) .null)),
   (n + 4300, R 1 (.commit a (a + 100))),
   (n + 4301, R 2 (.commit b (b + 100))),
   (n + 4400, R 1 (.transcript (a + 1) (a + 101))),
   (n + 4401, R 2 (.transcript (b + 1) (b + 101)))]

/-- A created document. -/
def start : Doc ℕ ℕ := (create (W 0) 1 5 9 "seed" "t").1

/-- Run a list of timed requests. -/
def run (e : Env ℕ ℕ) (s : Doc ℕ ℕ) (l : List (ℕ × Req ℕ ℕ)) : Doc ℕ ℕ :=
  l.foldl (fun x p => (step e (W p.1) p.2 x).1) s

/-- Is each time at or after the one before? -/
def inOrder : ℕ → List (ℕ × Req ℕ ℕ) → Bool
  | _, [] => true
  | c, p :: l => Nat.ble c p.1 && inOrder p.1 l

/-- The last time in a list. -/
def lastTime : ℕ → List (ℕ × Req ℕ ℕ) → ℕ
  | c, [] => c
  | _, p :: l => lastTime p.1 l

/-- A run with times in order is a `Reachable` one. -/
theorem run_reachable {e : Env ℕ ℕ} {c : ℕ} {s : Doc ℕ ℕ} (h : Reachable e c s) (l : List (ℕ × Req ℕ ℕ))
    (ho : inOrder c l = true) : Reachable e (lastTime c l) (run e s l) := by
  induction l generalizing c s with
  | nil => exact h
  | cons p l ih =>
    simp only [inOrder, Bool.and_eq_true, Nat.ble_eq] at ho
    exact ih (Reachable.step (W p.1) p.2 h ho.1) ho.2

/-- The halves of the NEAR run: flight 1715/48, about 35.73 cm, as in `Verdict.lean`. Numbers picked by hand. -/
def Hnear : ℕ → Role → ℤ := fun _ r => match r with | .A => 100 | .B => 0

/-- The halves of the `too_far` run: flight about 357 cm. -/
def Hfar : ℕ → Role → ℤ := fun _ r => match r with | .A => 1000 | .B => 0

/-- The halves of the retry run: at attempt 0 flight about -357 cm, impossible. At attempt 1 as `Hnear`. -/
def Hretry : ℕ → Role → ℤ := fun k r => match k, r with | 0, .A => -1000 | _, .A => 100 | _, .B => 0

/-- The requests of the NEAR run. -/
def nearTrace := opening ++ attemptRun 10 0 10 20
/-- The requests of the `too_far` run. The same requests, other signed numbers. -/
def farTrace := opening ++ attemptRun 10 0 10 20
/-- The requests of the retry run, up to the first measurement. -/
def retry0Trace := opening ++ attemptRun 10 0 10 20
/-- The requests of the retry run, with the second measurement. -/
def retry1Trace := retry0Trace ++ attemptRun 5000 1 30 40

/-- The document after the NEAR run. -/
def nearDoc := run (env Hnear) start nearTrace
/-- The document after the `too_far` run. -/
def farDoc := run (env Hfar) start farTrace
/-- The document after the first measurement of the retry run. -/
def retry0Doc := run (env Hretry) start retry0Trace
/-- The document after the second measurement of the retry run. -/
def retry1Doc := run (env Hretry) start retry1Trace

/-- **A run reaches NEAR**, with no audio anywhere and numbers picked by hand. So M3 and M11 aren't empty, and a NEAR doesn't show
a phone told the truth about the air (CN1). -/
theorem reaches_near : Reachable (env Hnear) (lastTime 0 nearTrace) nearDoc ∧ nearDoc.state = .done ∧
    nearDoc.attempt = 0 ∧ nearDoc.result.map (·.verdict) = some .NEAR := by
  refine ⟨run_reachable (Reachable.create (W 0) 1 5 9 "seed" "t") _ (by decide), ?_, ?_, ?_⟩ <;> decide +kernel

/-- **A run reaches `too_far`.** Verdict NOT_NEAR, reason `too_far`, from `combine`. It says nothing about the air (CN1). -/
theorem reaches_too_far : Reachable (env Hfar) (lastTime 0 farTrace) farDoc ∧ farDoc.state = .done ∧
    farDoc.result.map (·.verdict) = some .NOT_NEAR ∧ farDoc.error = some .too_far := by
  refine ⟨run_reachable (Reachable.create (W 0) 1 5 9 "seed" "t") _ (by decide), ?_, ?_, ?_⟩ <;> decide +kernel

/-- **A run retries.** After an impossible flight at attempt 0 the session goes back to `confirmed` at attempt 1, with no
result, with flags cleared. It says nothing about the air (CN1). -/
theorem retries : Reachable (env Hretry) (lastTime 0 retry0Trace) retry0Doc ∧ retry0Doc.state = .confirmed ∧
    retry0Doc.attempt = 1 ∧ retry0Doc.result.isNone = true ∧ retry0Doc.armed .A = false ∧ retry0Doc.attempts.length = 1 := by
  refine ⟨run_reachable (Reachable.create (W 0) 1 5 9 "seed" "t") _ (by decide), ?_, ?_, ?_, ?_, ?_⟩ <;> decide +kernel

/-- **The leak in M6, in that run.** While live, a member's view of the retry shows the reason. No number is in it. It says nothing
about the air (CN1). -/
theorem retry_shows_reason : (view (env Hretry) (W 5000) retry0Doc .B).last_failure.map (·.reason) = some (some .impossible_flight) ∧
    (view (env Hretry) (W 5000) retry0Doc .B).result.isNone = true := by
  constructor <;> decide +kernel

/-- **After the retry the same session can reach NEAR at attempt 1.** Both phones armed again. It says nothing about the air (CN1). -/
theorem retry_then_near : Reachable (env Hretry) (lastTime 0 retry1Trace) retry1Doc ∧ retry1Doc.state = .done ∧
    retry1Doc.attempt = 1 ∧ retry1Doc.result.map (·.verdict) = some .NEAR ∧ retry1Doc.attempts.length = 2 := by
  refine ⟨run_reachable (Reachable.create (W 0) 1 5 9 "seed" "t") _ (by decide), ?_, ?_, ?_, ?_⟩ <;> decide +kernel

/-- The toy signature check has no forgery in it: it passes only what a key's holder signs. So `M3_signed`'s hypothesis can hold. -/
theorem toy_unforgeable (H : ℕ → Role → ℤ) : Unforgeable (env H).p (fun pk m => okSig pk m = true) := by
  intro pk m s h
  simp only [env, Bool.and_eq_true] at h
  exact h.1

end Witness

end Machine
end ServerFv

/-! ## Axioms -/

#print axioms ServerFv.Machine.M9
#print axioms ServerFv.Machine.M9_table
#print axioms ServerFv.Machine.M9_confirmed
#print axioms ServerFv.Machine.M1_terminal
#print axioms ServerFv.Machine.M1_edges
#print axioms ServerFv.Machine.M2
#print axioms ServerFv.Machine.M3
#print axioms ServerFv.Machine.M3_signed
#print axioms ServerFv.Machine.combine_guard_unreachable
#print axioms ServerFv.Machine.afterStore_accepted
#print axioms ServerFv.Machine.combine_guard_on_request
#print axioms ServerFv.Machine.M4
#print axioms ServerFv.Machine.M5_codes
#print axioms ServerFv.Machine.M5_partner_code
#print axioms ServerFv.Machine.M5_no_strings
#print axioms ServerFv.Machine.M5_create_token
#print axioms ServerFv.Machine.M6
#print axioms ServerFv.Machine.M6_view_ignores
#print axioms ServerFv.Machine.M7
#print axioms ServerFv.Machine.M8_retry_wipes
#print axioms ServerFv.Machine.M8_pins
#print axioms ServerFv.Machine.M8_stale_transcript
#print axioms ServerFv.Machine.M8_stale_fail
#print axioms ServerFv.Machine.M8_old_commit_started
#print axioms ServerFv.Machine.M8_old_commit_not_started
#print axioms ServerFv.Machine.bed_msg_eq_iff
#print axioms ServerFv.Machine.M8_keys
#print axioms ServerFv.Machine.M10_stays
#print axioms ServerFv.Machine.M10_commit_repeat
#print axioms ServerFv.Machine.M10_commit_repeat_answer
#print axioms ServerFv.Machine.M10_commit_resend
#print axioms ServerFv.Machine.M10_commit_different
#print axioms ServerFv.Machine.M10_tx_repeat
#print axioms ServerFv.Machine.M10_tx_repeat_answer
#print axioms ServerFv.Machine.M10_tx_different
#print axioms ServerFv.Machine.M10_not_started
#print axioms ServerFv.Machine.M10_not_started_commit
#print axioms ServerFv.Machine.M10_not_started_transcript
#print axioms ServerFv.Machine.M10_over_transcript
#print axioms ServerFv.Machine.M11
#print axioms ServerFv.Machine.M12_no_auth
#print axioms ServerFv.Machine.M12_bad_json
#print axioms ServerFv.Machine.M12_bad_shape
#print axioms ServerFv.Machine.M12_non_member
#print axioms ServerFv.Machine.M12_member_load
#print axioms ServerFv.Machine.M12_noauth_load
#print axioms ServerFv.Machine.M12_roles
#print axioms ServerFv.Machine.M12_member
#print axioms ServerFv.Machine.M13
#print axioms ServerFv.Machine.M13_t0
#print axioms ServerFv.Machine.Witness.reaches_near
#print axioms ServerFv.Machine.Witness.reaches_too_far
#print axioms ServerFv.Machine.Witness.retries
#print axioms ServerFv.Machine.Witness.retry_shows_reason
#print axioms ServerFv.Machine.Witness.retry_then_near
#print axioms ServerFv.Machine.Witness.toy_unforgeable
