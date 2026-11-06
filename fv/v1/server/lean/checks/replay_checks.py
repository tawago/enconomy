"""Does the replay in ServerFv/Replay.lean catch anything? A checker that can't fail shows nothing.

Run from fv/v1/server/lean: python3 checks/replay_checks.py TRACE.jsonl [lines] [MORE_TRACES...]
MORE_TRACES are added to the honest runs of part 2, and aren't tampered with.
It only uses a copy of the first lines of TRACE. The trace and the repo files aren't changed.
Two parts:
  1. TAMPER. Change one fact in a copy of the trace. The replay must report a mismatch.
  2. MUTANTS. Change one rule in a copy of the definitions of Verdict.lean and Machine.lean, proofs cut out. The replay must
     report a mismatch on the honest trace. A mutant that passes is printed as SURVIVED. That has two possible meanings: the sampled
     runs don't reach that rule, or they do and the rule only moves something the compare can't see. Read the rule to tell which.
A control comes first: the same copy with no change must pass.
Exit code 0 only if every control passes, every tamper is caught, and every mutant builds and is caught. Else 1.
These results show the server follows its rules on signed numbers. They do not show a phone told the truth about the air (CN1).
"""
import copy, json, os, random, re, shutil, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor

trace = sys.argv[1]
keep = int(sys.argv[2]) if len(sys.argv) > 2 else 12000
more = " ".join(sys.argv[3:])
work = tempfile.mkdtemp(prefix="replay_checks_")
small = f"{work}/small.jsonl"
with open(trace) as f, open(small, "w") as g:
    lines = []
    for i, l in enumerate(f):
        if i > keep:
            break
        lines.append(l)
    g.writelines(lines)


def replay(file, leanpath=None):
    env = None
    cmd = ["lake", "env", "lean", "--run", "ServerFv/Replay.lean", file]
    if leanpath:
        cmd = ["lake", "env", "bash", "-c", f'LEAN_PATH={leanpath}:$LEAN_PATH lean --run ServerFv/Replay.lean {file}']
    p = subprocess.run(cmd, capture_output=True, text=True, env=env)
    first = next((x for x in p.stdout.splitlines() if x.startswith("MISMATCH")), "")
    m = re.search(r" at (\S+): ", first)
    return p.returncode, (m.group(1) if m else ""), p.stderr[:300], first


# ------------------------------------------------------------ tamper

parsed = [json.loads(l) for l in lines]


def find(name, pred):
    rng = random.Random(name)   # the same trace gives the same line, run after run
    idx = [i for i, x in enumerate(parsed) if i and pred(x)]
    return rng.choice(idx)


def has_near(x):
    return (x.get("after") or {}).get("result") and x["after"]["result"]["verdict"] == "NEAR" and not (x.get("before") or {}).get("result")


def is_op(k, status=200):
    return lambda x: x["op"]["op"] == k and x["status"] == status


def dec(k):
    def p(x):
        return x["op"]["op"] == k and x["status"] == 200 and x["op"]["eff"]["real"]["dec"] is not None
    return p


SEEN = {}
REPEAT = set()   # lines that send a string the same session already sent, and both strings parse
for i, x in enumerate(parsed):
    if not i or x["op"]["op"] not in ("commit", "transcript"):
        continue
    e = x["op"]["eff"]
    k = (x["session"], x["op"]["op"], e["label"])
    if e["real"]["wire_b64"] and e["real"]["sig_b64"] and e["real"]["dec"] is not None:
        if k in SEEN:
            REPEAT.add(i)
        SEEN[k] = i


REPEAT_IDS = {id(parsed[i]) for i in REPEAT}
PAIRS = set()
PAIR_IDS = set()   # lines that send the same two strings again, so every recorded bit about them must repeat too
for x in parsed[1:]:
    if x["op"]["op"] in ("commit", "transcript") and x["op"]["eff"]["real"]["verify"] is not None:
        k = (x["session"], x["op"]["op"], x["op"]["eff"]["label"], x["op"]["eff"]["sigl"])
        if k in PAIRS:
            PAIR_IDS.add(id(x))
        PAIRS.add(k)


def repeat_any(x):
    return id(x) in REPEAT_IDS


def repeat_tx(x):
    return id(x) in REPEAT_IDS and x["op"]["op"] == "transcript"


def is_created(x):
    return x["op"]["op"] == "create" and x["after"] is not None


def has_record(x):
    return x["op"]["op"] == "result" and x["status"] == 200


def has_result(x):
    return x.get("x") and x["x"]["result"]


def setp(path, v):
    def f(x):
        o = x
        for k in path[:-1]:
            o = o[k]
        o[path[-1]] = v(o[path[-1]]) if callable(v) else v
    return f


TAMPER = [
    ("status", lambda x: x["status"] == 200 and x["op"]["op"] == "view", setp(["status"], 409)),
    ("code", lambda x: x["code"] == "bad_state", setp(["code"], "bad_attempt")),
    ("after.state", lambda x: x["after"] and x["op"]["op"] == "confirm", setp(["after", "state"], "aborted")),
    ("after.seq", lambda x: x["after"] and x["op"]["op"] == "view", setp(["after", "seq"], lambda n: n + 1)),
    ("after.attempt", lambda x: x["after"] and x["op"]["op"] == "view", setp(["after", "attempt"], lambda n: n + 1)),
    ("after.guest", lambda x: x["after"] and x["after"]["guest"] and x["op"]["op"] == "view", setp(["after", "guest"], "C")),
    ("after.armed", lambda x: x["after"] and x["op"]["op"] == "arm" and x["status"] == 200, setp(["after", "armed", "A"], lambda b: not b)),
    ("after.t0", lambda x: x["after"] and x["after"]["t0"] is not None, setp(["after", "t0"], lambda n: n + 1)),
    ("after.token_exp", lambda x: x["after"] is not None, setp(["after", "token_exp"], lambda n: n + 1)),
    ("after.finished", lambda x: x["after"] and x["after"]["finished"] is not None, setp(["after", "finished"], lambda n: n + 1)),
    ("after.error", lambda x: x["after"] and x["after"]["error"], setp(["after", "error"], "glitch")),
    ("after.last_failure", lambda x: x["after"] and x["after"]["last_failure"], setp(["after", "last_failure", "by"], "Z")),
    ("per_role.cal", lambda x: x["after"] and x["after"]["per_role"]["A"].get("cal") is not None, setp(["after", "per_role", "A", "cal"], lambda n: n + 1)),
    ("per_role.cm", lambda x: x["after"] and x["after"]["per_role"]["A"].get("cm"), setp(["after", "per_role", "A", "cm"], "c999")),
    ("per_role.half", lambda x: x["after"] and "half" in x["after"]["per_role"]["A"], setp(["after", "per_role", "A", "half"], lambda n: n + 1)),
    ("per_role extra key", lambda x: x["after"] and x["op"]["op"] == "view", setp(["after", "per_role", "A", "zzz"], 1)),
    ("rows.length", lambda x: x["after"] and x["after"]["attempts"], setp(["after", "attempts"], lambda r: r[:-1])),
    ("result.verdict", has_near, setp(["after", "result", "verdict"], "NOT_NEAR")),
    ("result.flight", has_near, setp(["after", "result", "flight"], lambda q: q + 0.02)),
    ("result.devices.half", has_near, setp(["after", "result", "devices", "A", "half"], lambda n: n + 1)),
    ("resp.view.seq", is_op("view"), setp(["resp", "seq"], lambda n: n + 1)),
    ("resp.view.role", is_op("view"), setp(["resp", "role"], "Z")),
    ("resp.arm.play is the partner's", is_op("arm"), setp(["resp", "play"], "Z0")),
    ("resp.commit.partner_bed", is_op("commit"), setp(["resp", "partner_bed"], "Z0")),
    ("resp.accepted.state", is_op("transcript"), setp(["resp", "state"], "aborted")),
    ("resp.null on a 200", is_op("view"), setp(["resp"], None)),
    ("sig bit", dec("commit"), lambda x: x["op"]["eff"]["real"]["verify"].update({x["op"]["actor"]: False})),
    ("b64 bit", dec("commit"), setp(["op", "eff", "real", "wire_b64"], False)),
    ("decoded role", dec("commit"), setp(["op", "eff", "real", "dec", "role"], lambda r: "A" if r == "B" else "B")),
    ("decoded half", lambda x: dec("transcript")(x) and x["after"]["per_role"]["A"].get("half") is not None, setp(["op", "eff", "real", "dec", "half"], lambda n: n + 1)),
    ("calibration input", lambda x: x["op"]["op"] == "arm" and x["status"] == 200, None),
    ("clock back", lambda x: x["now"] > 5000 and x["op"]["op"] == "view", setp(["now"], 1)),
    ("before", lambda x: x["before"] and x["op"]["op"] == "view", setp(["before", "seq"], lambda n: n + 1)),
    ("x.sid", lambda x: x.get("x") and x["op"]["op"] == "view", setp(["x", "sid"], "?")),
    ("x.seed", lambda x: x.get("x") and x["op"]["op"] == "view", setp(["x", "seed"], "?")),
    ("x.nonce", lambda x: x.get("x") and x["op"]["op"] == "view", setp(["x", "nonce"], "?")),
    ("x.token", lambda x: x.get("x") and x["op"]["op"] == "view", setp(["x", "token"], "?")),
    ("x.host", lambda x: x.get("x") and x["op"]["op"] == "view", setp(["x", "host"], "B")),
    ("x.created", lambda x: x.get("x") and x["op"]["op"] == "view", setp(["x", "created"], 1)),
    ("x.armed", lambda x: x.get("x") and "armed" in x["x"]["per_role"]["A"], setp(["x", "per_role", "A", "armed"], lambda n: n + 1)),
    ("x.committed", lambda x: x.get("x") and "committed" in x["x"]["per_role"]["A"], setp(["x", "per_role", "A", "committed"], lambda n: n + 1)),
    ("x.fail_ms", lambda x: x.get("x") and any("per_role" in r and "fail_ms" in r["per_role"]["A"] for r in x["x"]["rows"]),
     lambda x: next(r for r in x["x"]["rows"] if "per_role" in r and "fail_ms" in r["per_role"]["A"])["per_role"]["A"].update(fail_ms=-5)),
    ("x.result.nonce", has_result, setp(["x", "result", "nonce"], "?")),
    ("x.result.sid", has_result, setp(["x", "result", "sid"], "?")),
    ("x.result.finished", has_result, setp(["x", "result", "finished"], None)),
    ("x.result.created", has_result, setp(["x", "result", "created"], 1)),
    ("x.result.pk", has_result, setp(["x", "result", "devices", "A", "pk"], "B")),
    ("x.result.dev", has_result, setp(["x", "result", "devices", "A", "dev"], "B")),
    ("resp.created.nonce", is_created, setp(["resp", "nonce"], "?")),
    ("resp.created.token", is_created, setp(["resp", "token"], "?")),
    ("resp.created.sid", is_created, setp(["resp", "sid"], "?")),
    ("resp.view.sid", is_op("view"), setp(["resp", "sid"], "?")),
    ("resp.arm.own_bed of another seed", is_op("arm"), setp(["resp", "own_bed"], "?")),
    ("resp.accepted false", is_op("transcript"), setp(["resp", "accepted"], False)),
    ("resp.record.nonce", has_record, setp(["resp", "nonce"], "?")),
    ("resp.record.tx dropped", lambda x: has_record(x) and x["resp"]["tx"], setp(["resp", "tx"], {})),
    ("resp.record.finished", has_record, setp(["resp", "finished"], None)),
    ("null decode on a repeat", repeat_any, setp(["op", "eff", "real", "dec"], None)),
    ("decoded time changed on a repeat", repeat_tx, setp(["op", "eff", "real", "dec", "play_nano_time"], 99)),
    ("verify changed on a repeat", lambda x: id(x) in PAIR_IDS,
     lambda x: x["op"]["eff"]["real"]["verify"].update(C=not x["op"]["eff"]["real"]["verify"]["C"])),
]


def tamper(ix):
    name, pred, change = TAMPER[ix]
    i = find(name, pred)
    x = copy.deepcopy(parsed[i])
    out = list(lines)
    if change is None:   # move a phone's starting calibration on the create line of that session, up front
        role = x["op"]["actor"]
        j = next(k for k in range(i, -1, -1) if parsed[k].get("session") == x["session"] and parsed[k].get("op", {}).get("op") == "create"
                 and parsed[k]["status"] == 200)
        y = copy.deepcopy(parsed[j])
        y["op"]["cal"][role] = (y["op"]["cal"][role] or 0) + 7
        out[j] = json.dumps(y) + "\n"
    else:
        change(x)
        out[i] = json.dumps(x) + "\n"
    f = f"{work}/t{ix}.jsonl"
    open(f, "w").writelines(out)
    rc, path, err, first = replay(f)
    os.remove(f)
    return f"TAMPER {name}: {'caught' if rc == 1 and first else 'MISSED'} rc={rc} at {path} {err}"


# ------------------------------------------------------------ mutants

m_src = open("ServerFv/Machine.lean").read()
cut = m_src.index("/-- `Reachable e clock s`")
m_defs = m_src[:cut] + "\nend Machine\nend ServerFv\n"
v_src = open("ServerFv/Verdict.lean").read()
cut = v_src.index("/-- A signed record as `verify_record` reads it")
v_defs = v_src[:cut] + "\nend ServerFv\n"

g = {}
txt = open("checks/machine_mutants.py").read()
exec(txt[txt.index("M = ["):txt.index("def run(ix)")], g)
MUT = [("M", *x) for x in g["M"]] + [
    ("M", "t0 delay 3001", "abbrev T0_DELAY_MS : ℕ := 3000", "abbrev T0_DELAY_MS : ℕ := 3001"),
    ("M", "gate 1201", "abbrev COMMIT_GATE_MS : ℕ := 1200", "abbrev COMMIT_GATE_MS : ℕ := 1201"),
    ("M", "token ttl 121", "abbrev JOIN_TOKEN_TTL_S : ℕ := 120", "abbrev JOIN_TOKEN_TTL_S : ℕ := 121"),
    ("M", "age 601", "abbrev SESSION_MAX_AGE_S : ℕ := 600", "abbrev SESSION_MAX_AGE_S : ℕ := 601"),
    ("M", "deadline 21", "abbrev TRANSCRIPT_DEADLINE_S : ℕ := 20", "abbrev TRANSCRIPT_DEADLINE_S : ℕ := 21"),
    ("M", "rtt 299", "abbrev MAX_RTT_MS : ℕ := 300", "abbrev MAX_RTT_MS : ℕ := 299"),
    ("M", "abort writes no row", "      [{ attempt := s.attempt, outcome := .aborted, reason := some .aborted, by_ := some role }]", "      []"),
    ("M", "abort keeps finished none", "    attempts := s.attempts ++\n      [{ attempt := s.attempt, outcome := .aborted, reason := some .aborted, by_ := some role }]\n    finished_ms := some w.now }", "    attempts := s.attempts ++\n      [{ attempt := s.attempt, outcome := .aborted, reason := some .aborted, by_ := some role }] }"),
    ("M", "nonce always shown", "nonce := if all2 s.confirmed = true then some s.nonce_hex else none", "nonce := some s.nonce_hex"),
    ("M", "silent role swapped", "  | false, true => some .A\n  | true, false => some .B", "  | false, true => some .B\n  | true, false => some .A"),
    ("M", "cal read live at arm is 0", "let cal := ((devId s role).map w.cal).getD 0", "let cal : ℤ := 0"),
    ("M", "calMap ignores snapshots", "some fun r => some (((s.per_role r).arm.map (·.cal_us)).getD 0)", "none"),
    ("M", "own_code on v1", "(if _popt s role = 2 then some (_code s role) else none)", "(some (_code s role))"),
    ("M", "partner_code on v1", "(if _popt s role = 2 then some (_code s (OTHER role)) else none)", "(some (_code s (OTHER role)))"),
    ("M", "stale needs no signature", "Nat.blt t.attempt s.attempt && ((_pk e s role).any fun pk => e.p.verify_raw pk raw sig)", "Nat.blt t.attempt s.attempt"),
    ("M", "fail skips submitted guard", "else if s.submitted role = true then .error (409, .already_submitted)", "else if False then .error (409, .already_submitted)"),
    ("M", "fail stores nothing", ".ok (_failed e w (failStore s role (rsn, w.now)) (some rsn) (some role))", ".ok (_failed e w s (some rsn) (some role))"),
    ("M", "failed row has no by", "[{ attempt := s.attempt, outcome := .failed, reason := reason, by_ := by_,", "[{ attempt := s.attempt, outcome := .failed, reason := reason, by_ := none,"),
    ("M", "rejected row has no by", "(_finalize e w s .NOT_NEAR (some rsn) none .rejected (some role),", "(_finalize e w s .NOT_NEAR (some rsn) none .rejected none,"),
    ("M", "repeat arm ignores rate", "if (s.per_role role).arm.map (·.sample_rate) ≠ some sr then", "if False then"),
    ("M", "repeat arm ignores popt", "else if _popt s role ≠ v then (s, .error 409 .bad_state)", "else if False then (s, .error 409 .bad_state)"),
    ("M", "null popt refused", "  | .null => some 1\n  | .int 1 => some 1", "  | .null => none\n  | .int 1 => some 1"),
    ("M", "repeat transcript ignores sig", "if td.transcript_b64 = transcript_b64 ∧ td.sig_b64 = sig_b64 then", "if td.transcript_b64 = transcript_b64 then"),
    ("M", "code commit at the partner's rate", "e.code_commit (((s.per_role r).arm.map (·.sample_rate)).getD 0) (_code s r)", "e.code_commit (((s.per_role (OTHER r)).arm.map (·.sample_rate)).getD 0) (_code s r)"),
    ("M", "commit version not checked", "else if c.version ≠ _popt s role then", "else if False then"),
    ("V", "near at 60 too", "else if flight ≥ (K.NEAR_CM : ℚ) then (some .NOT_NEAR, some .too_far)", "else if flight > (K.NEAR_CM : ℚ) then (some .NOT_NEAR, some .too_far)"),
    ("V", "impossible edge", "if flight ≤ (K.IMPOSSIBLE_CM : ℚ) then (none, some .impossible_flight)", "if flight < (K.IMPOSSIBLE_CM : ℚ) then (none, some .impossible_flight)"),
    ("V", "near limit 61", "abbrev NEAR_CM : ℤ := 60", "abbrev NEAR_CM : ℤ := 61"),
    ("V", "self tolerance strict", "|delta_frames * 1000000 - cal_us * (sr : ℤ)| ≤ ((K.SELF_OS_TOL_MS * 1000 * sr : ℕ) : ℤ)", "|delta_frames * 1000000 - cal_us * (sr : ℤ)| < ((K.SELF_OS_TOL_MS * 1000 * sr : ℕ) : ℤ)"),
    ("V", "flight sign swapped", "((K.SPEED_OF_SOUND_CM_S : ℚ) / 2) * ((half_a : ℚ) / (sr_a : ℚ) - (half_b : ℚ) / (sr_b : ℚ))", "((K.SPEED_OF_SOUND_CM_S : ℚ) / 2) * ((half_b : ℚ) / (sr_b : ℚ) - (half_a : ℚ) / (sr_a : ℚ))"),
    ("V", "flight drops one rate", "((half_a : ℚ) / (sr_a : ℚ) - (half_b : ℚ) / (sr_b : ℚ))", "((half_a : ℚ) / (sr_a : ℚ) - (half_b : ℚ) / (sr_a : ℚ))"),
    ("V", "v2 uses calibration", "if version_of t = 2 then 0 else (cal_us.bind (fun m => m t.role)).getD 0", "(cal_us.bind (fun m => m t.role)).getD 0"),
    ("V", "self check B before A", "else if self_check ta cal_us = false then                                         -- 161-164, A first\n    .ok ⟨none, none, some .self_timestamp_mismatch, some ta.role⟩\n  else if self_check tb cal_us = false then\n    .ok ⟨none, none, some .self_timestamp_mismatch, some tb.role⟩",
     "else if self_check tb cal_us = false then\n    .ok ⟨none, none, some .self_timestamp_mismatch, some tb.role⟩\n  else if self_check ta cal_us = false then\n    .ok ⟨none, none, some .self_timestamp_mismatch, some ta.role⟩"),
    ("V", "transcript signature not checked", "if p.verify_raw pk_self raw sig = false then .error (.reject .signature_invalid)  -- 116-117", "if False then .error (.reject .signature_invalid)"),
    ("V", "transcript version not checked", "else if version_of t ≠ version then .error (.reject .transcript_mismatch)         -- 118-119", "else if False then .error (.reject .transcript_mismatch)"),
    ("V", "pk_self gives the other reason", "else if t.pk_self ≠ pk_self then .error (.reject .signature_invalid)              -- 120-121", "else if t.pk_self ≠ pk_self then .error (.reject .transcript_mismatch)"),
    ("V", "partner key not checked", "else if t.pk_partner ≠ pk_partner then .error (.reject .transcript_mismatch)      -- 128-129", "else if False then .error (.reject .transcript_mismatch)"),
    ("V", "commit hash not checked", "else if commit_sha256 = none ∨ some t.commit_hash ≠ commit_sha256 then", "else if False then"),
    ("V", "rec not checked", "else if rec = none ∨ some t.rec_ ≠ rec then", "else if False then"),
    ("V", "v2 delta not checked", "if t.delta ≠ some (popt2_delta t.sample_rate) then", "if False then"),
    ("V", "v2 code commit not checked", "else if code_commit ≠ none ∧ t.code_commit ≠ code_commit then", "else if False then"),
    ("V", "retry reasons lose glitch", "def RETRY_REASONS : List Reason :=\n  [.capture_failed, .glitch,", "def RETRY_REASONS : List Reason :=\n  [.capture_failed,"),
    ("V", "partner_mismatch retries", "def RETRY_REASONS : List Reason :=\n  [.capture_failed,", "def RETRY_REASONS : List Reason :=\n  [.partner_mismatch, .capture_failed,"),
    ("V", "phone can send too_far", "def PHONE_REASONS : List Reason :=\n  [.capture_failed,", "def PHONE_REASONS : List Reason :=\n  [.too_far, .capture_failed,"),
    ("M", "wrong sound seed", "def _code (s : Doc B D) (r : Role) : Code := ⟨s.seed_hex, r, s.attempt⟩", "def _code (s : Doc B D) (r : Role) : Code := ⟨\"other\", r, s.attempt⟩"),
    ("M", "record nonce is session id", "  session_nonce := s.nonce_hex\n", "  session_nonce := s.session_id\n"),
    ("M", "record id is the nonce", "  session_id := s.session_id\n  session_nonce", "  session_id := s.nonce_hex\n  session_nonce"),
    ("M", "record keys all host", "⟨d, e.pk d, (s.per_role r).arm.map (·.sample_rate),", "⟨d, e.pk s.host_device_id, (s.per_role r).arm.map (·.sample_rate),"),
    ("M", "record devices all host", "⟨d, e.pk d, (s.per_role r).arm.map (·.sample_rate),", "⟨s.host_device_id, e.pk d, (s.per_role r).arm.map (·.sample_rate),"),
    ("M", "record finish absent", "  finished_ms := s.finished_ms\n  devices r", "  finished_ms := none\n  devices r"),
    ("M", "record created zero", "  created_ms := s.created_ms\n  finished_ms := s.finished_ms\n  devices r", "  created_ms := 0\n  finished_ms := s.finished_ms\n  devices r"),
    ("M", "arm time shifted", "{ arm := some ⟨sr, w.now, v, cal⟩ }", "{ arm := some ⟨sr, w.now + 1, v, cal⟩ }"),
    ("M", "commit time shifted", "rec_ := c.rec_, committed_ms := w.now\n", "rec_ := c.rec_, committed_ms := w.now + 1\n"),
    ("M", "fail time shifted", "(failStore s role (rsn, w.now))", "(failStore s role (rsn, w.now + 1))"),
    ("M", "create wrong nonce", "(s, .created s.session_id s.nonce_hex s.join_token s.token_expires_ms)", "(s, .created s.session_id s.session_id s.join_token s.token_expires_ms)"),
    ("M", "create wrong token", "(s, .created s.session_id s.nonce_hex s.join_token s.token_expires_ms)", "(s, .created s.session_id s.nonce_hex \"x\" s.token_expires_ms)"),
    ("M", "create wrong id", "(s, .created s.session_id s.nonce_hex s.join_token s.token_expires_ms)", "(s, .created s.nonce_hex s.nonce_hex s.join_token s.token_expires_ms)"),
    ("M", "created time zero", "      created_ms := w.now, finished_ms := none\n", "      created_ms := 0, finished_ms := none\n"),
    ("M", "token expiry from zero", "token_expires_ms := w.now + K.JOIN_TOKEN_TTL_S * 1000", "token_expires_ms := K.JOIN_TOKEN_TTL_S * 1000"),
    ("M", "result route loses transcripts", "  | some r => (s, .record r)", "  | some r => (s, .record { r with transcripts := fun _ => none })"),
    ("M", "result route loses commits", "  | some r => (s, .record r)", "  | some r => (s, .record { r with commits := fun _ => none })"),
    ("M", "view record loses rows", "  result := s.result\n  error := s.error", "  result := s.result.map fun r => { r with attempts := [] }\n  error := s.error"),
    ("M", "view id wrong", "  session_id := s.session_id\n  seq := s.seq", "  session_id := s.nonce_hex\n  seq := s.seq"),
    ("V", "self check reads play_nano_time", "self_os_ok t.self_os_delta t.sample_rate (cal_for t cal_us)", "self_os_ok (t.play_nano_time : ℤ) t.sample_rate (cal_for t cal_us)"),
    ("V", "self check reads play_frame_position", "self_os_ok t.self_os_delta t.sample_rate (cal_for t cal_us)", "self_os_ok (t.play_frame_position : ℤ) t.sample_rate (cal_for t cal_us)"),
    ("V", "self check reads rec_frame0_nano_time", "self_os_ok t.self_os_delta t.sample_rate (cal_for t cal_us)", "self_os_ok (t.rec_frame0_nano_time : ℤ) t.sample_rate (cal_for t cal_us)"),
]


def build(tag, vtxt, mtxt):
    root = f"{work}/{tag}"
    os.makedirs(f"{root}/ServerFv")
    for name, txt in (("Verdict", vtxt), ("Machine", mtxt)):
        open(f"{root}/ServerFv/{name}.lean", "w").write(txt)
        p = subprocess.run(["lake", "env", "bash", "-c", f"LEAN_PATH={root}:$LEAN_PATH lean -R {root} -o {root}/ServerFv/{name}.olean {root}/ServerFv/{name}.lean"],
                           capture_output=True, text=True)
        if p.returncode != 0:
            return root, f"does not compile: {[l for l in p.stdout.splitlines() if 'error' in l][:2]}"
    return root, None


def mutant(ix):
    which, name, a, b = MUT[ix]
    src = m_defs if which == "M" else v_defs
    if src.count(a) != 1:
        return f"MUTANT {name}: BAD PATTERN count={src.count(a)}"
    txt = src.replace(a, b)
    root, err = build(f"m{ix}", txt if which == "V" else v_defs, txt if which == "M" else m_defs)
    if err:
        shutil.rmtree(root)
        return f"MUTANT {name}: NO BUILD {err}"
    rc, path, e, first = replay(f"{small} {more}", root)
    shutil.rmtree(root)
    tag = "caught" if rc == 1 and first else ("SURVIVED" if rc in (0, 3) else f"RUN ERROR {e}")   # rc 1 with no MISMATCH line is a compile error, not a catch
    return f"MUTANT {name}: {tag} rc={rc} at {path}"


root, err = build("control", v_defs, m_defs)
assert err is None, err
rc, path, e, first = replay(f"{small} {more}", root)
print(f"CONTROL definitions-only copy, no change: rc={rc} {first} {e}")
rc2, *_ = replay(small)
print(f"CONTROL real build, untampered copy of the first lines: rc={rc2}")
shutil.rmtree(root)
if rc not in (0, 3) or rc2 not in (0, 3):   # 3 is only coverage or sessions short, which a short copy can be
    sys.exit("a control failed, so the rest would mean nothing")
with ThreadPoolExecutor(12) as ex:
    a = list(ex.map(tamper, range(len(TAMPER))))
    b = list(ex.map(mutant, range(len(MUT))))
for r in a + b:
    print(r)
print("tamper total", len(a), "missed", sum("MISSED" in r for r in a))
missed = sum("MISSED" in r for r in a)
caught = sum(": caught" in r for r in b)
print("mutants total", len(b), "caught", caught, "survived", sum("SURVIVED" in r for r in b),
      "other", len(b) - caught - sum("SURVIVED" in r for r in b))
shutil.rmtree(work)
failed = missed + len(b) - caught
print("replay_checks rc", 1 if failed else 0)
sys.exit(1 if failed else 0)
