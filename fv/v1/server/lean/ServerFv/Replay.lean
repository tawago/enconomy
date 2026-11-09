import ServerFv.Machine
import Lean.Data.Json
import Std.Data.HashMap

/-!
# Replay: does the Lean table agree with the real Python, on sampled runs?

`Machine.step` is a copy of `server/pop/sessions.py` written by hand, and the proofs are about that copy.
This file reads traces from the real server (`fv/v1/server/tests/test_walk.py --trace-out`), runs
`Machine.step` on each request, and compares the result with what the real server did, after every step:
the status and error code, the abstract document, and a digest of the response. It reports the first mismatch and the totals.
A session keeps its own Lean document from the create on. It is never reset to what the trace says.
Real time in the traces starts at `created_ms`. Here it starts at `baseMs`, far from zero, so a rule that used a fixed time shows up.

Run from `fv/v1/server/lean`:
  lake build ServerFv.Machine
  lake env lean --run ServerFv/Replay.lean TRACE.jsonl [TRACE2.jsonl ...]
Flags, before the files: `--stop-first` stops at the first mismatch. `--min-sessions=N` changes the session floor, 1000 by default.
Exit code 0: no mismatch, at least that many sessions, and every target in `wantCoverage` reached. Those targets are a short list
chosen by hand, so this does not mean full coverage. `replay.txt` prints the list.
1: a mismatch. 2: the trace can't be read. 3: too few sessions, or a target missed.

**What this shows.** On these runs, the Lean table and the Python gave the same status and code, the same abstract document
and the same response digest. Those are only the fields listed under "What is compared". It is testing on sampled runs. It is
not a proof that the two are equal.

**What this does not show.** These results show the server follows its rules on signed numbers. They do not
show a phone told the truth about the air (CN1). A NEAR here means two keys signed two numbers that fit a range.
No sound is played or heard anywhere in this file. None of this is a proof of proximity.

**Scope.** Only sessions with `context=None` and `early_nonce=False`. No context, zk route, presence signature,
recording upload, enrolment or audio processing.

**Assumptions, named.** Honest server code as written. One worker process. No await between load and save.
Signatures can't be forged. SHA-256 and the truncated device id have no collisions. The walk's test client sends
one request at a time and reads one fake clock value per step, so the second and third are not tested here.
The traces come from the `server/` in the same checkout. `run_all.sh` makes them fresh each run, so the two can't drift apart silently.

**Facts taken from the trace, not worked out here.** The Lean model has these as opaque functions, so a replay
has to fill them in. They were all recorded from the real code, on the strings really sent. See `real_block` in
`test_walk.py`.
* Did `b64d` accept this string. Recorded bit.
* Did `verify_raw` pass under this phone's key. Recorded bit.
* What the real decoder returned for these bytes, or that it refused them. All decoded fields are read, the times too.
* The starting calibration of each phone, on the create line. It is an input, like the clock.
The same string must keep the same facts. If a later line says otherwise, that is a mismatch, and no earlier fact is kept silently.
The trace is never edited to fit. A wire string is its label, and hash, key and nonce bytes are labels too.
That is sound as long as the assumption about collisions holds. The trace gives a hash the same label as its wire string, so
labels are read by kind: a wire field shows only a wire label, a signature field only a signature label, a hash field only a hash
label (`wireLbl`, `sigLbl`, `hashLbl`). A hash field holding the wire string shows "?", and is a mismatch. "?" is never equal
to anything in `cmp`, "?" in the trace included, so a value neither side can name fails closed. A rec is compared as
[length, value], so a stored rec of another length with the same number is a mismatch.

**What is compared.**
* Document: state, attempt, seq, guest, the four flag maps, t0, token expiry, finished, error, last failure's attempt, reason and by,
  and each attempts row with its outcome, reason, by, verdict, flight and t0.
* For each role and row: rate, popt, calibration, armed time, the commit and its signature, hash and rec, committed time, code commit,
  transcript and its signature and hash, half, self delta, fail reason and fail time.
* Session id, seed, nonce and join token, each only as "same as at create". Host and created time.
* Record, in the document and in the answers: all of the above that it holds, record nonce, session id, device ids and keys, created and finished.
* Answers: the same record, and what `respV` writes. Sounds are compared by name: the trace names one by running the real generator on the
  session's real seed, and Lean names it by role and attempt once its seed equals the seed the create was given. The Lean `Code` has no rate,
  so the rate of a sound is checked only on the Python side.

**What is not compared.** The Lean table doesn't hold these, so a wrong value in one can't show up here.
`test_walk.py` checks many of them against its own model. This replay doesn't.
* Document: `updated_ms`, `last_flight_cm`, `last_failure.text`, `not_before`, `context`, `early_nonce`.
* Per role: `rtt_min_ms`, `submitted_ms`, `meta`, `code_attest`.
* Record: `proto`, `user_text`, `context`, `not_before`, `zk`, `presence` (the walk checks its body and signature), and display fields of a device: name, model,
  attested, security level.
* Answers: the create's invite, `not_before` and `context`. A view's constants, display fields, calibration block, `zk_valid_at`, `context`
  and `not_before`. An arm's `popt` and `tune_db`. A commit's `code_attest`. The detail text of an error. All bytes of a sound.
* The real value of an id, secret or key. Only "same as at create" or a label reaches the trace.
* Keys the trace never writes. The trace is a projection: `abstract`, `abstract_result`, `full_record`, `trace_extra` and `resp_digest` in
  `test_walk.py` build new dicts from fixed key lists, so a key the Python adds outside those lists is dropped before this replay's
  strict compare. The compare here rejects an extra key only among the keys the trace writes. "The whole record" in a log means
  the compared part. The walk itself rejects unknown keys in the stored document and the record (`check_record_shape` and `check_fixed`,
  in `test_walk.py`), and checks the whole view against `want_view`. That is the walk's check, not this replay's.

**What a trace can't cover.**
* It is a sample. A rule the walk never hits with the right inputs is not tested, however many runs pass.
  `replay.txt` lists the error codes and reasons seen, and the ones never seen.
* Fixed inputs. The host is the create's actor, read from the trace, but every create in the saved traces is by phone A, so another
  host isn't tested (the counter "first good create by a phone other than A" says how many were seen). Every create's time is the session's own zero.
  Each decoded transcript holds the same five values the walk sends: 1, 2, 3, 70000 and 71000. No rule in `Machine.step` or `combine` reads them.
* `Verdict.check_commit` isn't called by `Machine.step`, which has those checks inline, so it isn't tested here.
* `Req.noauth_load`: no such request is sent, so routes like `/zk/bundle` that run a bare load are not tested.
* Races. One request at a time, so A2 and A3 are not tested.
* Several clock reads in one handler. The fake clock holds still during a step. This is how `join`'s second expiry
  check and `finished_ms` could differ, and this replay can't see it.
* Byte parsing and real crypto are not modeled in Lean. A bug in the real decoder would be recorded here as
  a fact and both sides would agree on it.
* The three known 500s (`spec.md` section 6) are not generated. `Err.internal` is never reached.
* Bad creates and unknown session ids never reach `Machine.step`. Those only get a light check here, and are
  counted under `not a step`. `set_cal` is not a route, it only changes the calibration input.
* `flight` is rounded in Python (`round(float(f), 2)`) and exact in Lean. It is compared to within 0.005 plus 1e-9.
  Nothing decides on the rounded number, so that gap can't move a verdict.
* Auth is not modeled: `auth.py` is out of `Machine.step`, whose `sender` is `none` when auth fails. Here the trace's `auth`
  label picks `sender`. All four 401 codes are the one Lean code `auth_failed`. The real code is checked against the label
  with `authCodes`, a copy of `m_auth` in `test_walk.py`. A `replay` label allows `auth_stale` or `auth_replay`, since which one
  depends on a time the trace doesn't keep.

**Sessions.** One good create per session: a second good create in the same session is a mismatch. Lines of one session
come together, and a session id that already ended in the same trace file can't come back: that is a mismatch too. A new id
starts a new session. Ids are counted per file, since each trace numbers its sessions from 0.
-/

set_option linter.style.whitespace false
set_option linter.style.longLine false
set_option linter.style.header false
set_option linter.unusedVariables false
set_option linter.style.setOption false
set_option linter.flexible false

open Lean (Json JsonNumber)

namespace ServerFv
namespace Replay
open Machine

/-- The bytes of the model. A label stands for a string the walk saw. -/
inductive RB
  /-- A wire string of a commit or transcript, by its label. -/
  | wire (l : String)
  /-- The bytes that wire string decodes to. -/
  | raw (l : String)
  /-- A signature string, by its label. -/
  | sigw (l : String)
  /-- The bytes that signature string decodes to. -/
  | sig (l : String)
  /-- SHA-256 of `raw l`. -/
  | hash (l : String)
  /-- A rec field, as the number it holds. -/
  | num (n : Nat)
  /-- Any other bytes, as hex with an `x:` in front. -/
  | str (s : String)
  /-- The key of a phone. -/
  | pk (phone : String)
  /-- This session's nonce. -/
  | nonce
  /-- A code commit: the rate and the two codes, with their seeds. -/
  | cc (sr : Nat) (a b : Code)
  deriving DecidableEq, Repr

/-! ## What every create is given. Fixed labels for the real random values. -/

/-- The session id the create is given. -/
def sidL : RB := .str "sid"
/-- The seed the create is given. -/
def seedL : String := "seed"
/-- The join token the create is given. -/
def tokenL : String := "abc123"
/-- The session's zero, in Lean. The trace's times count from `created_ms`. -/
def baseMs : ℕ := 1700000000000

/-! ## Words, written out here so they are checked against the trace and not against `repr` -/

def roleW : Role → String
  | .A => "A"
  | .B => "B"

def roleOf? : String → Option Role
  | "A" => some .A
  | "B" => some .B
  | _ => none

def stW : St → String
  | .created => "created"
  | .joined => "joined"
  | .confirmed => "confirmed"
  | .started => "started"
  | .done => "done"
  | .aborted => "aborted"

def reasonW : Reason → String
  | .capture_failed => "capture_failed"
  | .glitch => "glitch"
  | .self_not_heard => "self_not_heard"
  | .self_timestamp_mismatch => "self_timestamp_mismatch"
  | .partner_not_heard => "partner_not_heard"
  | .impossible_flight => "impossible_flight"
  | .timeout => "timeout"
  | .too_far => "too_far"
  | .signature_invalid => "signature_invalid"
  | .transcript_mismatch => "transcript_mismatch"
  | .partner_mismatch => "partner_mismatch"
  | .aborted => "aborted"

def allReasons : List Reason :=
  [.capture_failed, .glitch, .self_not_heard, .self_timestamp_mismatch, .partner_not_heard, .impossible_flight,
   .timeout, .too_far, .signature_invalid, .transcript_mismatch, .partner_mismatch, .aborted]

def reasonOf? (s : String) : Option Reason := allReasons.find? (fun r => reasonW r == s)

def outcomeW : Outcome → String
  | .failed => "failed"
  | .aborted => "aborted"
  | .rejected => "rejected"
  | .verdict => "verdict"

def verdictW : Verdict → String
  | .NEAR => "NEAR"
  | .NOT_NEAR => "NOT_NEAR"

def errW : Err → String
  | .auth_failed => "auth_failed"
  | .bad_request => "bad_request"
  | .not_member => "not_member"
  | .self_join => "self_join"
  | .already_joined => "already_joined"
  | .bad_token => "bad_token"
  | .token_expired => "token_expired"
  | .bad_state => "bad_state"
  | .bad_attempt => "bad_attempt"
  | .bad_sample_rate => "bad_sample_rate"
  | .already_committed => "already_committed"
  | .too_early => "too_early"
  | .stale_attempt => "stale_attempt"
  | .already_submitted => "already_submitted"
  | .bad_reason => "bad_reason"
  | .no_result => "no_result"
  | .internal => "internal"
  | .reason r => reasonW r

/-! ## The abstract document, in the shape `abstract` in `test_walk.py` writes -/

/-- A small value tree. `flight` is exact, and the only leaf compared loosely. -/
inductive V
  | null
  | bool (b : Bool)
  | str (s : String)
  | int (z : ℤ)
  | flight (q : ℚ)
  | arr (l : List V)
  | obj (l : List (String × V))

def optV {α : Type} (f : α → V) : Option α → V
  | some a => f a
  | none => .null

def natV (n : ℕ) : V := .int n
/-- A time, as ms since the session's zero, like the trace. -/
def tV (t : ℕ) : V := .int ((t : ℤ) - (baseMs : ℤ))
/-- "ok" when the value is the one the create was given, else "?". -/
def okV (b : Bool) : V := .str (if b then "ok" else "?")
def strO (o : Option String) : V := optV .str o
def reasonO (o : Option Reason) : V := optV (fun r => .str (reasonW r)) o
def roleO (o : Option Role) : V := optV (fun r => .str (roleW r)) o
def flagsV (f : Role → Bool) : V := .obj [("A", .bool (f .A)), ("B", .bool (f .B))]
def flightO (o : Option ℚ) : V := optV .flight o

/-- The label of a wire string, in a field that must hold a wire string. Any other kind of bytes gives "?".
The trace writes a hash under the same label as its wire string (`cm_hash`, `tx_hash` in `test_walk.py`), so one shared
label function would let a hash field holding the wire string pass. Each field kind gets its own function for that reason. -/
def wireLbl : RB → V
  | .wire l => .str l
  | _ => .str "?"

/-- The label of a signature string. Any other kind of bytes gives "?". -/
def sigLbl : RB → V
  | .sigw l => .str l
  | _ => .str "?"

/-- The label of SHA-256 of decoded bytes. A wire or signature string in a hash field gives "?". -/
def hashLbl : RB → V
  | .hash l => .str l
  | _ => .str "?"

/-- True when the value is the string `s`. `V` has no equality, so the checks below go through this. -/
def V.isStr (s : String) : V → Bool
  | .str t => t == s
  | _ => false

-- A field of one kind never shows the label of another kind.
#guard (hashLbl (.wire "t1")).isStr "?"
#guard (hashLbl (.sigw "s1")).isStr "?"
#guard (wireLbl (.hash "t1")).isStr "?"
#guard (wireLbl (.sigw "s1")).isStr "?"
#guard (sigLbl (.wire "t1")).isStr "?"
#guard (sigLbl (.hash "t1")).isStr "?"
#guard (hashLbl (.hash "t1")).isStr "t1"
#guard (wireLbl (.wire "t1")).isStr "t1"
#guard (sigLbl (.sigw "s1")).isStr "s1"

/-- A rec field as [length in bytes, value], like `stored_rec` in `test_walk.py`. The codec's rec is always 32 bytes (`32s` in
`_COMMIT` and `_TX` of `codec.py`), so a stored 33-byte value with a leading 00 is a mismatch even though its number is the same. -/
def recV : RB → V
  | .num n => .arr [.int 32, .int n]
  | _ => .str "?"

/-- `pr` in `abstract`: only the keys set so far. -/
def prV (attempt : ℕ) (r : Role) (p : PerRole RB) : V :=
  let arm := match p.arm with
    | some a => [("sr", natV a.sample_rate), ("popt", natV a.popt), ("cal", V.int a.cal_us)]
    | none => []
  let sr := (p.arm.map (·.sample_rate)).getD 0
  let cm := match p.commit with
    | some c =>
      [("cm", wireLbl c.commit_b64), ("cms", sigLbl c.commit_sig_b64), ("cmh", hashLbl c.commit_sha256), ("rec", recV c.rec_)] ++
        (match c.code_commit with
         | some x => [("cc", if x = RB.cc sr ⟨seedL, r, attempt⟩ ⟨seedL, OTHER r, attempt⟩ then V.bool true else V.str "?")]
         | none => [])
    | none => []
  let tx := match p.tx with
    | some t =>
      [("tx", wireLbl t.transcript_b64), ("txs", sigLbl t.sig_b64), ("txh", hashLbl t.transcript_sha256),
       ("half", V.int t.half), ("delta", V.int t.self_os_delta)]
    | none => []
  let fl := match p.fail_ with
    | some f => [("fail", V.str (reasonW f.1))]
    | none => []
  .obj (arm ++ cm ++ tx ++ fl)

def rolesV (f : Role → V) : V := .obj [("A", f .A), ("B", f .B)]

/-- Keep only the roles that have an entry, like a dict that holds only what was set. -/
def someRoles (f : Role → Option V) : V :=
  .obj (([Role.A, Role.B].filterMap fun r => (f r).map fun v => (roleW r, v)))

def rowV (a : AttemptRow RB) : V :=
  let base := [("attempt", natV a.attempt), ("outcome", V.str (outcomeW a.outcome)), ("reason", reasonO a.reason), ("by", roleO a.by_)]
  let pr := match a.per_role with
    | some f => [("per_role", rolesV fun r => prV a.attempt r (f r)), ("t0", optV tV a.t0_ms)]
    | none => []
  let vd := match a.verdict with
    | some v => [("verdict", V.str (verdictW v)), ("flight", flightO a.flight_cm)]
    | none => []
  .obj (base ++ pr ++ vd)

def summaryV (a : SummaryRow) : V :=
  .obj ([("attempt", natV a.attempt), ("outcome", V.str (outcomeW a.outcome)), ("reason", reasonO a.reason), ("by", roleO a.by_)] ++
    if a.outcome = .verdict then
      [("verdict", optV (fun v => V.str (verdictW v)) a.verdict), ("flight", flightO a.flight_cm)]
    else [])

/-- `RESULT` in the trace format. `full` adds what `RECORD` has on top: ids, keys and times. -/
def recordFields (full : Bool) (x : Record RB String) : List (String × V) :=
  [("verdict", .str (verdictW x.verdict)), ("reason", reasonO x.reason), ("flight", flightO x.flight_cm),
   ("attempt", natV x.attempt), ("t0", optV tV x.t0_ms),
   ("devices", someRoles fun r => (x.devices r).map fun d =>
     .obj ([("half", optV V.int d.half), ("sr", optV natV d.sample_rate), ("popt", natV d.popt), ("cal", V.int d.cal_us)] ++
       if full then [("dev", V.str d.device_id), ("pk", V.str (match d.pubkey with | .pk p => p | _ => "?"))] else [])),
   ("tx", someRoles fun r => (x.transcripts r).map fun t => wireLbl t.transcript_b64),
   ("txs", someRoles fun r => (x.transcripts r).map fun t => sigLbl t.sig_b64),
   ("txh", someRoles fun r => (x.transcripts r).map fun t => hashLbl t.sha256),
   ("cm", someRoles fun r => (x.commits r).map fun c => wireLbl c.commit_b64),
   ("cms", someRoles fun r => (x.commits r).map fun c => sigLbl c.sig_b64),
   ("rows", .arr (x.attempts.map summaryV))] ++
  if full then
    [("sid", okV (x.session_id = sidL)), ("nonce", okV (x.session_nonce = RB.nonce)),
     ("created", tV x.created_ms), ("finished", optV tV x.finished_ms)]
  else []

def recordV (x : Record RB String) : V := .obj (recordFields false x)
def recordFullV (x : Record RB String) : V := .obj (recordFields true x)

def lastFailureV (l : Option LastFailure) : V :=
  optV (fun f => .obj [("attempt", natV f.attempt), ("reason", reasonO f.reason), ("by", roleO f.by_)]) l

/-- The whole abstract document. -/
def docV (s : Doc RB String) : V :=
  .obj [("state", .str (stW s.state)), ("attempt", natV s.attempt), ("seq", natV s.seq),
        ("guest", strO s.guest_device_id), ("confirmed", flagsV s.confirmed), ("armed", flagsV s.armed),
        ("committed", flagsV s.committed), ("submitted", flagsV s.submitted), ("t0", optV tV s.t0_ms),
        ("token_exp", tV s.token_expires_ms), ("finished", optV tV s.finished_ms), ("error", reasonO s.error),
        ("last_failure", lastFailureV s.last_failure),
        ("per_role", rolesV fun r => prV s.attempt r (s.per_role r)),
        ("attempts", .arr (s.attempts.map rowV)),
        ("result", optV recordV s.result)]

/-- The times of one role: what `TIMES` holds in `trace_extra`. -/
def timesV (p : PerRole RB) : V :=
  .obj ((match p.arm with | some a => [("armed", tV a.armed_ms)] | none => []) ++
        (match p.commit with | some c => [("committed", tV c.committed_ms)] | none => []) ++
        (match p.fail_ with | some f => [("fail_ms", tV f.2)] | none => []))

/-- `EXTRA` in the trace format, `trace_extra` in `test_walk.py`. -/
def docExtraV (s : Doc RB String) : V :=
  .obj [("sid", okV (s.session_id = sidL)), ("seed", okV (s.seed_hex = seedL)), ("nonce", okV (s.nonce_hex = RB.nonce)),
        ("token", okV (s.join_token = tokenL)), ("host", .str s.host_device_id), ("created", tV s.created_ms),
        ("per_role", rolesV fun r => timesV (s.per_role r)),
        ("rows", .arr (s.attempts.map fun a =>
          match a.per_role with
          | some f => .obj [("per_role", rolesV fun r => timesV (f r))]
          | none => .obj [])),
        ("result", optV recordFullV s.result)]

/-! ## The response, in the shape `resp_digest` writes -/

/-- The name of a sound. Only a sound of the seed this session was given gets a name, as in `sound_id`. -/
def codeW (c : Code) : String :=
  if c.seed = seedL then roleW c.role ++ toString c.attempt else "?"

def pkW : RB → String
  | .pk p => p
  | _ => "?"

def viewDevV (d : Option (ViewDevice RB String)) : V :=
  optV (fun x => .obj [("dev", .str x.device_id), ("pk", .str (pkW x.pubkey)), ("cal", .int x.cal_us)]) d

def ccV : RB → V
  | .cc sr a b =>
    if a.seed = seedL ∧ b = ⟨seedL, OTHER a.role, a.attempt⟩ then
      .obj [("sr", natV sr), ("role", .str (roleW a.role)), ("attempt", natV a.attempt)]
    else .str "?"
  | .str s => .str s
  | _ => .str "?"

def respV : Resp RB String → V
  | .created sid n tok exp =>
    .obj [("kind", .str "created"), ("token_exp", tV exp), ("sid", okV (sid = sidL)), ("token", okV (tok = tokenL)), ("nonce", okV (n = RB.nonce))]
  | .view v =>
    .obj [("kind", .str "view"), ("sid", okV (v.session_id = sidL)), ("state", .str (stW v.state)), ("attempt", natV v.attempt), ("seq", natV v.seq),
          ("role", .str (roleW v.role)), ("nonce", optV (fun n => .str (if n = RB.nonce then "ok" else "?")) v.nonce),
          ("self", viewDevV v.self_), ("partner", viewDevV v.partner), ("confirmed", flagsV v.confirmed),
          ("armed", flagsV v.armed), ("committed", flagsV v.committed), ("submitted", flagsV v.submitted),
          ("popt", rolesV fun r => optV natV (v.popt r)), ("t0", optV tV v.t0_ms), ("error", reasonO v.error),
          ("last_failure", lastFailureV v.last_failure),
          ("result", optV recordFullV v.result)]
  | .armMaterial a sr play bed code delta =>
    .obj [("kind", .str "arm"), ("attempt", natV a), ("sr", optV natV sr), ("play", .str (codeW play)),
          ("own_bed", .str (codeW bed)), ("own_code", optV (fun c => .str (codeW c)) code), ("delta", optV natV delta)]
  | .partnerBed bed code cc =>
    .obj [("kind", .str "commit"), ("partner_bed", .str (codeW bed)), ("partner_code", optV (fun c => .str (codeW c)) code),
          ("cc", optV ccV cc)]
  | .accepted st a => .obj [("kind", .str "accepted"), ("accepted", .bool true), ("state", .str (stW st)), ("attempt", natV a)]
  | .record x => .obj (("kind", .str "record") :: recordFields true x)
  | .other | .error _ _ => .null

/-! ## Comparing -/

partial def V.show : V → String
  | .null => "null"
  | .bool b => toString b
  | .str s => "\"" ++ s ++ "\""
  | .int z => toString z
  | .flight q => s!"exact {q.num}/{q.den}"
  | .arr l => "[" ++ ", ".intercalate (l.map V.show) ++ "]"
  | .obj l => "{" ++ ", ".intercalate (l.map fun kv => kv.1 ++ ": " ++ V.show kv.2) ++ "}"

def numQ (n : JsonNumber) : ℚ := (n.mantissa : ℚ) / ((10 ^ n.exponent : ℕ) : ℚ)

/-- `round(float(f), 2)` in Python against the exact value: within half a cent, and a little for the float. -/
def flightClose (q r : ℚ) : Bool :=
  let t : ℚ := 1 / 200 + 1 / 1000000000
  Decidable.decide (q - r ≤ t) && Decidable.decide (r - q ≤ t)

def jsonKeys (j : Json) : List String :=
  match j.getObj? with
  | .ok kvs => kvs.foldl (fun acc k _ => k :: acc) []
  | .error _ => []

structure Diff where
  path : String
  lean : String
  trace : String

/-- The first place where the Lean value and the trace differ, or none. -/
partial def cmp (path : String) (v : V) (j : Json) : Option Diff :=
  let no : Option Diff := some ⟨path, v.show, j.compress⟩
  match v, j with
  | .null, .null => none
  | .bool a, .bool b => if a == b then none else no
  | .str a, .str b => if a == b && a != "?" then none else no   -- "?" is a value one side can't name: never equal
  | .int z, .num n => if n.exponent == 0 && n.mantissa == z then none else no
  | .flight q, .num n => if flightClose q (numQ n) then none else no
  | .arr l, .arr m =>
    if l.length != m.size then some ⟨path ++ ".length", toString l.length, toString m.size⟩
    else
      let rec goArr (i : Nat) : List V → Option Diff
        | [] => none
        | x :: xs =>
          match cmp s!"{path}[{i}]" x (m.getD i .null) with
          | some d => some d
          | none => goArr (i + 1) xs
      goArr 0 l
  | .obj kv, .obj _ =>
    let extra := (jsonKeys j).filter fun k => !(kv.any fun p => p.1 == k)
    match extra with
    | k :: _ => some ⟨path ++ "." ++ k, "(no such key)", (j.getObjValD k).compress⟩
    | [] =>
      let rec goObj : List (String × V) → Option Diff
        | [] => none
        | (k, x) :: xs =>
          match j.getObjVal? k with
          | .error _ => some ⟨path ++ "." ++ k, x.show, "(no such key)"⟩
          | .ok y =>
            match cmp (path ++ "." ++ k) x y with
            | some d => some d
            | none => goObj xs
      goObj kv
  | _, _ => no

-- Fail closed: "?" on both sides is a mismatch, not a match. A rec keeps its length.
#guard (cmp "p" (.str "?") (.str "?")).isSome
#guard (cmp "p" (.str "ok") (.str "ok")).isNone
#guard (cmp "p" (recV (.num 5)) (Lean.toJson ([33, 5] : List Nat))).isSome
#guard (cmp "p" (recV (.num 5)) (Lean.toJson ([32, 5] : List Nat))).isNone
#guard (cmp "p" (recV (.str "x:00")) (.str "?")).isSome

/-! ## Reading a trace line -/

abbrev R := Except String

def jStr (j : Json) (k : String) : R String := do
  let v ← j.getObjVal? k
  v.getStr?

def jNat (j : Json) (k : String) : R ℕ := do
  let v ← j.getObjVal? k
  v.getNat?

def jInt (j : Json) (k : String) : R ℤ := do
  let v ← j.getObjVal? k
  v.getInt?

def jBool (j : Json) (k : String) : R Bool := do
  let v ← j.getObjVal? k
  v.getBool?

/-- A key that may be missing, as a string, or `dflt`. -/
def jStrD (j : Json) (k dflt : String) : String :=
  match j.getObjVal? k with
  | .ok (.str s) => s
  | _ => dflt

def jRole (j : Json) (k : String) : R Role := do
  match roleOf? (← jStr j k) with
  | some r => pure r
  | none => throw s!"bad role in {k}"

/-- Bytes as the walk named them. `x:...` is bytes the test never made. -/
def bytesOf (named : String → RB) (s : String) : RB :=
  if s.startsWith "x:" then .str s else named s

def nonceB (s : String) : RB := bytesOf (fun _ => .nonce) s

def decCommit (j : Json) : R (Option (Commit RB)) := do
  if j.isNull then return none
  return some {
    role := ← jRole j "role"
    attempt := ← jNat j "attempt"
    nonce := nonceB (← jStr j "nonce")
    rec_ := .num (← jNat j "rec")
    version := ← jNat j "version" }

def ccOf (j : Json) : R (Option RB) := do
  match j with
  | .null => pure none
  | .str s => pure (some (.str s))
  | _ =>
    let r ← jRole j "role"
    let k ← jNat j "attempt"
    pure (some (.cc (← jNat j "sr") ⟨seedL, r, k⟩ ⟨seedL, OTHER r, k⟩))

def decTx (j : Json) : R (Option (Transcript RB)) := do
  if j.isNull then return none
  let d := j.getObjValD "v2_delta"
  let delta ← if d.isNull then pure none else some <$> d.getNat?
  let optNat (k : String) : R (Option ℕ) := do
    let x := j.getObjValD k
    if x.isNull then pure none else some <$> x.getNat?
  return some {
    role := ← jRole j "role"
    attempt := ← jNat j "attempt"
    nonce := nonceB (← jStr j "nonce")
    pk_self := bytesOf .pk (← jStr j "pk_self")
    pk_partner := bytesOf .pk (← jStr j "pk_partner")
    sample_rate := ← jNat j "sr"
    half := ← jInt j "half"
    rec_ := .num (← jNat j "rec")
    play_frame_position := ← jNat j "play_frame_position"
    play_nano_time := ← jNat j "play_nano_time"
    rec_frame0_nano_time := ← jNat j "rec_frame0_nano_time"
    self_os_delta := ← jInt j "delta"
    commit_hash := bytesOf .hash (← jStr j "commit_hash")
    version := ← jNat j "version"
    a_self := ← optNat "a_self"
    p_partner := ← optNat "p_partner"
    delta := delta
    code_commit := ← ccOf (j.getObjValD "cc") }

/-! ## The recorded facts, as the opaque parts of `Env` -/

/-- The facts seen so far. `none` in `commits` or `txs` means the real decoder refused those bytes. -/
structure Reg where
  wireOk : Std.HashMap String Bool := {}
  sigOk : Std.HashMap String Bool := {}
  commits : Std.HashMap String (Option (Commit RB)) := {}
  txs : Std.HashMap String (Option (Transcript RB)) := {}
  verify : Std.HashMap String (List (String × Bool)) := {}

def Reg.env (r : Reg) : Env RB String where
  p :=
    { width := fun _ => 0
      verify_raw := fun pk m sg =>
        match pk, m, sg with
        | .pk ph, .raw l, .sig s => (((r.verify[l ++ "|" ++ s]?).bind (·.lookup ph)).getD false)
        | _, _, _ => false
      sha256 := fun x =>
        match x with
        | .raw l => .hash l
        | _ => .str "x:sha-of-nonraw"
      rec_root_ok := fun _ => true
      decode_commit := fun x =>
        match x with
        | .raw l => (r.commits[l]?).join
        | _ => none
      decode_transcript := fun x =>
        match x with
        | .raw l => (r.txs[l]?).join
        | _ => none }
  b64d := fun x =>
    match x with
    | .wire l => if r.wireOk[l]?.getD false then some (.raw l) else none
    | .sigw l => if r.sigOk[l]?.getD false then some (.sig l) else none
    | _ => none
  pk := .pk
  code_commit := fun sr a b => .cc sr a b

/-- A fact about one string or pair of strings. It must not change between lines. -/
def learn {α : Type} [BEq α] (m : Std.HashMap String α) (k : String) (v : α) : Std.HashMap String α × Bool :=
  match m[k]? with
  | some old => (m, old != v)
  | none => (m.insert k v, false)

/-- Take in the facts of one commit or transcript request. A fact that changes, or doesn't fit the others, comes back as a problem.
When only one string parses, the real code never reached the decoder, so a null there says nothing about those bytes. -/
def Reg.add (r : Reg) (isCommit : Bool) (eff : Json) : R (Reg × Option Diff) := do
  let l ← jStr eff "label"
  let sl ← jStr eff "sigl"
  let real ← eff.getObjVal? "real"
  let wire ← jBool real "wire_b64"
  let sg ← jBool real "sig_b64"
  let dec := real.getObjValD "dec"
  let ver := real.getObjValD "verify"
  let no (what : String) : Option Diff := some ⟨s!"facts.{what}", s!"the facts seen for {l} and {sl}", real.compress⟩
  let (wm, c1) := learn r.wireOk l wire
  let (sm, c2) := learn r.sigOk sl sg
  let r := { r with wireOk := wm, sigOk := sm }
  if c1 || c2 then return (r, no "base64 changed")
  if !(wire && sg) then
    if !dec.isNull || !ver.isNull then return (r, no "a decode with no parsed strings")
    return (r, none)
  if ver.isNull then return (r, no "parsed strings with no verify")
  let bits ← ["A", "B", "C"].mapM fun ph => do pure (ph, ← jBool ver ph)
  let (vm, c3) := learn r.verify (l ++ "|" ++ sl) bits
  let r := { r with verify := vm }
  if c3 then return (r, no "verify changed")
  if isCommit then
    let (m, c4) := learn r.commits l (← decCommit dec)
    return ({ r with commits := m }, if c4 then no "decode changed" else none)
  else
    let (m, c4) := learn r.txs l (← decTx dec)
    return ({ r with txs := m }, if c4 then no "decode changed" else none)

def argOf : Json → Arg
  | .null => .null
  | .num n => if n.exponent == 0 then .int n.mantissa else .other
  | _ => .other

def rttOf : Json → Option ℚ
  | .num n => some (numQ n)
  | _ => none

def reasonArg : Json → Option Reason
  | .str s => reasonOf? s
  | _ => none

def bodyOf (kind : String) (op : Json) : R (Body RB) := do
  match kind with
  | "join" =>
    match ← jStr op "token" with
    | "ok" => pure (.join tokenL)
    | "upper" => pure (.join tokenL.toUpper)
    | "wrong" => pure (.join "00000000000000000000000000000000")
    | t => throw s!"bad token {t}"
  | "view" => pure (.op .view)
  | "result" => pure (.op .result)
  | "confirm" => pure (.op .confirm)
  | "abort" => pure (.op .abort)
  | "arm" =>
    pure (.op (.arm (argOf (op.getObjValD "attempt")) (argOf (op.getObjValD "sample_rate")) (rttOf (op.getObjValD "rtt_min_ms")) (argOf (op.getObjValD "popt"))))
  | "commit" =>
    let eff ← op.getObjVal? "eff"
    pure (.op (.commit (.wire (← jStr eff "label")) (.sigw (← jStr eff "sigl"))))
  | "transcript" =>
    let eff ← op.getObjVal? "eff"
    pure (.op (.transcript (.wire (← jStr eff "label")) (.sigw (← jStr eff "sigl"))))
  | "fail" => pure (.op (.fail_ (argOf (op.getObjValD "attempt")) (reasonArg (op.getObjValD "reason"))))
  | k => throw s!"unknown op {k}"

/-- The routes with a JSON body, `BODY_OPS` in the walk. -/
def hasBody (kind : String) : Bool := ["join", "arm", "commit", "transcript", "fail"].contains kind

def authOk (a : String) : Bool := ["ok", "edge_old", "edge_new"].contains a

/-- The real 401 codes an `auth` label can give: `m_auth` in `test_walk.py`, written out again. Empty for a label that passes.
`replay` gives either, by a time the trace doesn't keep. -/
def authCodes : String → List String
  | "missing" | "bad_sig_b64_missing" | "bad_sig_b64" | "wrong_key" | "tamper" => ["auth_bad_signature"]
  | "unknown_device" => ["auth_unknown_device"]
  | "stale_old" | "stale_new" => ["auth_stale"]
  | "replay" => ["auth_stale", "auth_replay"]
  | _ => []

#guard authCodes "stale_old" == ["auth_stale"]
#guard authCodes "ok" == []
#guard (authCodes "replay").contains "auth_replay"

/-! ## The run -/

structure Sess where
  id : Nat
  doc : Option (Doc RB String) := none
  cal : Std.HashMap String ℤ := {}
  reg : Reg := {}
  lastNow : Nat := 0
  broke : Bool := false

/-- The world of one request. `now` is the trace's time, from the session's zero. -/
def Sess.world (s : Sess) (now : ℕ) : World String := ⟨baseMs + now, fun d => (s.cal[d]?).getD 0⟩

def calOf (j : Json) : ℤ :=
  match j.getInt? with
  | .ok z => z
  | .error _ => 0

structure Tot where
  counts : Std.HashMap String Nat := {}
  mismatches : Nat := 0
  sessionsBroken : Nat := 0
  first : Option String := none

def Tot.inc (t : Tot) (k : String) (n : Nat := 1) : Tot :=
  { t with counts := t.counts.insert k ((t.counts[k]?).getD 0 + n) }

/-- What the Lean step answered, as status and code. `auth_failed` stands for four real codes. -/
def outcomeOf : Resp RB String → Nat × Option String
  | .error st c => (st, some (errW c))
  | _ => (200, none)

def sameCode (auth : String) (lean : Option String) (trace : Json) : Bool :=
  match lean, trace with
  | none, .null => true
  | some "auth_failed", .str c => (authCodes auth).contains c
  | some a, .str c => a == c
  | _, _ => false

/-- One line. Returns the new session, or a problem as a `Diff`. -/
def compareStep (line : Json) (s' : Doc RB String) (r : Resp RB String) : R (Option Diff) := do
  let (st, code) := outcomeOf r
  let tst ← jNat line "status"
  let tcode := line.getObjValD "code"
  let auth := jStrD ((line.getObjValD "op")) "auth" "ok"
  if st != tst || !sameCode auth code tcode then
    return some ⟨"status", s!"{st} {code}", s!"{tst} {tcode.compress}"⟩
  match cmp "after" (docV s') (line.getObjValD "after") with
  | some d => return some d
  | none => pure ()
  match cmp "x" (docExtraV s') (line.getObjValD "x") with
  | some d => return some d
  | none => pure ()
  return cmp "resp" (respV r) (line.getObjValD "resp")

/-- Which expiry row fired in the load of this step, if any. -/
def expired (e : Env RB String) (w : World String) (s : Doc RB String) : Option String :=
  if (load e w s).seq == s.seq then none
  else if s.state = .created ∧ w.now > s.token_expires_ms then some "E1"
  else if s.state = .started ∧ ¬ (w.now - s.created_ms > K.SESSION_MAX_AGE_S * 1000) then some "E3"
  else some "E2"

def tally (t : Tot) (before : Option (Doc RB String)) (s' : Doc RB String) : Tot := Id.run do
  let mut t := t.inc s!"state after a step: {stW s'.state}"
  let wasSet := match before with
    | some b => b.result.isSome
    | none => false
  if !wasSet then
    if let some x := s'.result then
      t := t.inc s!"result: {verdictW x.verdict} reason={(x.reason.map reasonW).getD "none"}"
      t := t.inc s!"verdict: {verdictW x.verdict}"
      if x.flight_cm.isSome then t := t.inc "flight values compared, within 0.005"
  let oldRows := match before with
    | some b => b.attempts.length
    | none => 0
  for a in s'.attempts.drop oldRows do
    t := t.inc s!"row: {outcomeW a.outcome} reason={(a.reason.map reasonW).getD "none"} by={(a.by_.map roleW).getD "none"}"
  return t

structure Out where
  sess : Sess
  tot : Tot
  diff : Option Diff

def runLine (ss : Sess) (t : Tot) (line : Json) : R Out := do
  let op ← line.getObjVal? "op"
  let kind ← jStr op "op"
  let now ← jNat line "now"
  let t := t.inc s!"op: {kind}"
  if now < ss.lastNow then
    return ⟨ss, t, some ⟨"now", s!"at least {ss.lastNow}, by A7", toString now⟩⟩
  let ss := { ss with lastNow := now }
  match kind with
  | "create" =>
    let body ← jStr op "create_body"
    let auth := jStrD op "auth" "ok"
    let good := ["empty", "object", "early_false"].contains body && auth == "ok"
    let calJ ← op.getObjVal? "cal"
    let cal := ["A", "B", "C"].foldl (fun (m : Std.HashMap String ℤ) ph => m.insert ph (calOf (calJ.getObjValD ph))) {}
    let ss := { ss with cal := cal }
    if good then
      if ss.doc.isSome then
        return ⟨ss, t, some ⟨"create", "one good create per session", "a second good create"⟩⟩
      -- The host is the create's actor, read from the trace. Fixed inputs, not read from the trace: this session's zero as the time,
      -- and the labels for id, nonce, seed and token. The walk's every create is by phone A at its zero (`do_create` in `test_walk.py`).
      let host ← jStr op "actor"
      let (s', r) := Machine.create (B := RB) (D := String) (ss.world now) host sidL .nonce seedL tokenL
      let d ← compareStep line s' r
      let t := if host != "A" then t.inc "first good create by a phone other than A" else t
      return ⟨{ ss with doc := some s' }, (tally t none s').inc s!"step code: create 200", d⟩
    else
      let tst ← jNat line "status"
      let tcode := line.getObjValD "code"
      let wantCode := if auth != "ok" then authCodes auth else ["bad_request"]
      let d : Option Diff :=
        if !(line.getObjValD "after").isNull then some ⟨"after", "nothing stored", (line.getObjValD "after").compress⟩
        else if auth != "ok" && tst != 401 then some ⟨"status", "401", toString tst⟩
        else if auth == "ok" && tst != 400 then some ⟨"status", "400", toString tst⟩
        else if !(wantCode.any fun c => tcode == Json.str c) then some ⟨"code", toString wantCode, tcode.compress⟩
        else none
      return ⟨ss, t.inc "not a step: refused create", d⟩
  | "set_cal" =>
    let ph ← jStr op "actor"
    let ss := { ss with cal := ss.cal.insert ph (calOf (op.getObjValD "cal_us")) }
    let d := match ss.doc with
      | some s => cmp "after" (docV s) (line.getObjValD "after")
      | none => none
    return ⟨ss, t.inc "not a step: set_cal", d⟩
  | _ =>
    let some s := ss.doc | throw "a step before any good create"
    let actor ← jStr op "actor"
    if let some d := cmp "before" (docV s) (line.getObjValD "before") then
      return ⟨ss, t, some d⟩
    let mut reg := ss.reg
    if kind == "commit" || kind == "transcript" then
      let (reg', bad) ← reg.add (kind == "commit") (← op.getObjVal? "eff")
      if let some d := bad then
        return ⟨ss, t, some d⟩
      reg := reg'
    let ss := { ss with reg := reg }
    let e := reg.env
    let w := ss.world now
    let bodyTag := jStrD op "body" "ok"
    let json_bad := hasBody kind && bodyTag == "bad_json"
    let sender : Option String := if authOk (jStrD op "auth" "ok") then some actor else none
    let shape_bad := (hasBody kind && bodyTag == "bad_shape") || (kind == "view" && jStrD op "query" "" == "after=x")
    if jStrD op "sid" "ok" == "unknown" && !json_bad && sender.isSome && !shape_bad then
      let tst ← jNat line "status"
      let d : Option Diff :=
        if tst != 404 || !sameCode "ok" (some "not_found") (line.getObjValD "code") then some ⟨"status", "404 not_found", toString tst⟩
        else (cmp "after" (docV s) (line.getObjValD "after")).orElse fun _ => cmp "x" (docExtraV s) (line.getObjValD "x")
      return ⟨ss, t.inc "not a step: unknown session id", d⟩
    let b ← bodyOf kind op
    let (s', r) := Machine.step e w (.api json_bad sender shape_bad b) s
    let d ← compareStep line s' r
    let (st, code) := outcomeOf r
    let t := t.inc s!"step code: {kind} {st} {code.getD ""}"
    let t := match code with
      | some c => t.inc s!"err seen: {c}"
      | none => t
    let t := if !json_bad && sender.isSome && !shape_bad then
        match expired e w s with
        | some x => t.inc s!"expiry fired: {x}"
        | none => t
      else t
    let t := if st == 200 then
        match r with
        | .view _ => t.inc "resp compared: view"
        | .armMaterial .. => t.inc "resp compared: arm"
        | .partnerBed .. => t.inc "resp compared: commit"
        | .accepted .. => t.inc "resp compared: accepted"
        | .record _ => t.inc "resp compared: record"
        | _ => t
      else t
    let t := t.inc "steps run through Machine.step"
    let t := if kind == "transcript" && st == 200 && s'.seq == (load e w s).seq then t.inc "same transcript again, answered 200" else t
    let t := if kind == "transcript" && st == 200 && s'.seq == (load e w s).seq &&
        (match (op.getObjValD "eff").getObjValD "label" with
         | .str l => match ((reg.txs[l]?).join) with
           | some td => td.half != 0
           | none => false
         | _ => false) then t.inc "repeat transcript with a nonzero half" else t
    let t := if kind == "arm" && st == 200 && (s'.armed .A || s'.armed .B) then
        if _popt s' .A == 2 || _popt s' .B == 2 then t.inc "arm answered, a role on popt 2" else t.inc "arm answered, both on popt 1"
      else t
    return ⟨{ ss with doc := some s' }, tally t (some s) s', d⟩

/-- The error codes the Lean table can answer, to say which were never hit. `reason` errors are only these two. -/
def allErrs : List String :=
  ["auth_failed", "bad_request", "not_member", "self_join", "already_joined", "bad_token", "token_expired", "bad_state",
   "bad_attempt", "bad_sample_rate", "already_committed", "too_early", "stale_attempt", "already_submitted", "bad_reason",
   "no_result", "internal", "signature_invalid", "transcript_mismatch"]

/-- Targets chosen by hand: every state and verdict, the expiry rows, a live repeat transcript, each kind of answer, and each
error code but `internal`, which the walk doesn't generate. Reaching them all is not full coverage. -/
def wantCoverage : List String :=
  (["created", "joined", "confirmed", "started", "done", "aborted"].map fun x => s!"state after a step: {x}") ++
  ["verdict: NEAR", "verdict: NOT_NEAR", "expiry fired: E1", "expiry fired: E2", "expiry fired: E3", "same transcript again, answered 200",
   "resp compared: view", "resp compared: arm", "resp compared: commit", "resp compared: accepted", "resp compared: record"] ++
  ((allErrs.filter (· != "internal")).map fun c => s!"err seen: {c}")

def header : List String :=
  ["Replay of Machine.step against traces from the real server (test_walk.py --trace-out).",
   "This is testing on sampled runs. It is not a proof that the Lean table and the Python are equal.",
   "These results show the server follows its rules on signed numbers. They do not show a phone told the truth about the air (CN1). Not a proof of proximity.",
   "Scope: context=None, early_nonce=False. Assumptions named in ServerFv/Replay.lean: honest code, one worker, no await between load and save, unforgeable signature, no collisions.",
   "Signature bits, base64 bits, decoded fields and starting calibration are recorded facts from the real code, read from the trace.",
   "Compared: status and code, the abstract document and the response digest. Fields outside those are listed in ServerFv/Replay.lean and are not checked here.",
   "Not compared, among others: record context, zk, presence; view context; document context, early_nonce, not_before.",
   "The trace is a projection built from fixed key lists in test_walk.py, so keys outside those lists are dropped before the strict compare. 'The whole record' means the compared part.",
   "Labels are read by kind: a hash field shows only a hash label, a wire field only a wire label, a signature field only a signature label.",
   "Sessions: one good create per session, and an id can't come back within a trace file; either is a mismatch. The host is the create's actor. A 401 code must be one the auth label gives (authCodes, from m_auth)."]

def main (args : List String) : IO UInt32 := do
  let stopFirst := args.contains "--stop-first"
  let minFlag := "--min-sessions="
  let minSessions : Nat := ((args.find? (·.startsWith minFlag)).bind fun a => (a.drop minFlag.length).toString.toNat?).getD 1000
  let files := args.filter fun a => a != "--stop-first" && !a.startsWith minFlag
  if files.isEmpty then
    IO.eprintln "usage: lean --run ServerFv/Replay.lean [--stop-first] [--min-sessions=N] TRACE.jsonl ..."
    return 2
  for l in header do IO.println l
  let mut t : Tot := {}
  let mut sessions : Nat := 0
  let mut lines : Nat := 0
  let mut skipped : Nat := 0
  for f in files do
    let h ← IO.FS.Handle.mk f .read
    let first ← h.getLine
    match Json.parse first with
    | .error e => IO.eprintln s!"{f}: bad header: {e}"; return 2
    | .ok hd =>
      if jStrD hd "format" "" != "pop-walk-trace-5" then
        IO.eprintln s!"{f}: wrong format {first}"
        return 2
      IO.println s!"trace {f}: {hd.compress}"
    let mut ss : Sess := { id := 0 }
    let mut seen : Std.HashSet Nat := {}
    let mut started := false
    let mut stopped := false
    while !stopped do
      let l ← h.getLine
      if l.isEmpty then break
      lines := lines + 1
      let j ← match Json.parse l with
        | .ok j => pure j
        | .error e => IO.eprintln s!"{f}: line {lines}: {e}"; return 2
      let id ← match (j.getObjValD "session").getNat? with
        | .ok n => pure n
        | .error e => IO.eprintln s!"{f}: line {lines}: {e}"; return 2
      if !started || id != ss.id then
        let back := seen.contains id
        seen := seen.insert id
        ss := { id := id }
        started := true
        sessions := sessions + 1
        if back then
          -- One session's lines come together, so an id that already ended can't start again.
          let msg := s!"MISMATCH {f} session {id} step {(j.getObjValD "step").compress} now {(j.getObjValD "now").compress} op {((j.getObjValD "op").getObjValD "op").compress} tag {((j.getObjValD "op").getObjValD "tag").compress}: at session: lean an id not seen before in this file, trace id {id} comes back"
          if t.first.isNone then
            IO.println msg
            t := { t with first := some msg }
          t := { t with mismatches := t.mismatches + 1, sessionsBroken := t.sessionsBroken + 1 }
          ss := { ss with broke := true }
          if stopFirst then stopped := true
      if ss.broke then
        skipped := skipped + 1
        continue
      match runLine ss t j with
      | .error e =>
        IO.eprintln s!"{f}: line {lines}: can't read: {e}"
        return 2
      | .ok o =>
        ss := o.sess
        t := o.tot
        if let some d := o.diff then
          let msg := s!"MISMATCH {f} session {id} step {(j.getObjValD "step").compress} now {(j.getObjValD "now").compress} op {((j.getObjValD "op").getObjValD "op").compress} tag {((j.getObjValD "op").getObjValD "tag").compress}: at {d.path}: lean {d.lean}, trace {d.trace}"
          if t.first.isNone then
            IO.println msg
            IO.println s!"  that op: {(j.getObjValD "op").compress}"
            IO.println s!"  status {(j.getObjValD "status").compress} code {(j.getObjValD "code").compress}"
            t := { t with first := some msg }
          t := { t with mismatches := t.mismatches + 1, sessionsBroken := t.sessionsBroken + 1 }
          ss := { ss with broke := true }
          if stopFirst then stopped := true
    if stopped then break
  IO.println s!"sessions {sessions}"
  IO.println s!"trace lines {lines}"
  IO.println s!"lines skipped, after a mismatch in the same session: {skipped}"
  IO.println s!"sessions with a mismatch: {t.sessionsBroken}"
  let keys := (t.counts.toList.map (·.1)).toArray.qsort (· < ·)
  for k in keys do
    IO.println s!"  {k}: {(t.counts[k]?).getD 0}"
  let neverErr := allErrs.filter fun c => !(t.counts.contains s!"err seen: {c}")
  IO.println s!"Lean error codes never hit: {neverErr}"
  let neverRow := (allReasons.map reasonW).filter fun c => !(t.counts.toList.any fun kv => kv.1.startsWith "row: " && (kv.1.splitOn s!"reason={c} ").length > 1)
  IO.println s!"reasons never seen in an attempts row: {neverRow}"
  let short := wantCoverage.filter fun c => !(t.counts.contains c)
  IO.println s!"chosen coverage targets: {wantCoverage.length}, missed: {short}"
  IO.println s!"session floor: {minSessions}"
  if t.mismatches > 0 then
    IO.println s!"RESULT mismatch. First: {t.first.getD ""}"
    return 1
  if sessions < minSessions then
    IO.println s!"RESULT no mismatch, but only {sessions} sessions, under the floor of {minSessions}"
    return 3
  if !short.isEmpty then
    IO.println "RESULT no mismatch, but a chosen coverage target was missed"
    return 3
  IO.println s!"RESULT no mismatch in any compared step, on these sampled runs, with {sessions} sessions and all {wantCoverage.length} chosen targets reached. That is not full coverage. Not a proof of equivalence, and not a proof of proximity."
  return 0

end Replay
end ServerFv

def main (args : List String) : IO UInt32 := ServerFv.Replay.main args
