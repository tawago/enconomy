"""Does the replay in ServerFv/Replay.lean catch anything? A checker that can't fail shows nothing.

Run from fv/v1/server/lean: python3 checks/replay_checks.py TRACE.jsonl [lines] [MORE_TRACES...]
MORE_TRACES are added to the honest runs of part 2, and aren't tampered with.
It only uses a copy of the first `lines` lines of TRACE; 0 or no value means the whole trace. The trace and the repo files aren't changed.
A copy short of the replay's session floor or coverage targets gives the control rc=3, and then the run stops: use the whole trace.
Two parts:
  1. TAMPER. Change one fact in a copy of the trace. The replay must report a mismatch.
  2. MUTANTS. Change one rule in a copy of the definitions of Verdict.lean and Machine.lean, proofs cut out. The replay must
     report a mismatch on the honest trace. A mutant that passes is printed as SURVIVED. That has two possible meanings: the sampled
     runs don't reach that rule, or they do and the rule only moves something the compare can't see. Read the rule to tell which.
A control comes first: the same input the mutants get (the copy plus MORE_TRACES), with no change, must give rc=0, on the
definitions-only copy and on the real build. The tampers use the copy alone and must give rc=1.
UNREACHABLE below is a short, explicit list of mutants that no trace can reach, each with the Lean theorem that says why. Such a
mutant that survives is printed as "SURVIVED, allowed" and doesn't fail the run. Every other survivor does.
REPLAY_FILE=<path> runs another copy of the replay instead of ServerFv/Replay.lean, for a before-and-after comparison.
REPLAY_ONLY=<regex> in the environment runs only the tampers and mutants whose name matches. It is for a quick check of a few rows;
a filtered run is not the full check, and a filter that matches nothing exits 1.
Exit code 0 only if every control passes, every tamper is caught, and every mutant builds and is caught or is on the UNREACHABLE list. Else 1.
These results show the server follows its rules on signed numbers. They do not show a phone told the truth about the air (CN1).
"""
import copy, json, os, random, re, shutil, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor



def trace_path(a):
    """A trace path must be an existing regular file and not look like an option: Replay.lean reads
    `--stop-first` or `--min-sessions=N` as flags, so a path like that would be skipped. Returned absolute."""
    if not a or a.startswith("-") or not os.path.isfile(a):
        sys.exit(f"FAIL: trace path {a!r} is not an existing regular file (or starts with '-'). replay_checks rc 1")
    return os.path.abspath(a)


if len(sys.argv) < 2:
    sys.exit("usage: replay_checks.py TRACE [KEEP] [EXTRA_TRACE...]")
trace = trace_path(sys.argv[1])
keep = int(sys.argv[2]) if len(sys.argv) > 2 else 0
keep = keep or 10 ** 9   # 0: the whole trace
more = [trace_path(a) for a in sys.argv[3:]]   # extra trace paths, kept as a list: no joining, no shell
work = tempfile.mkdtemp(prefix="replay_checks_")
small = f"{work}/small.jsonl"
with open(trace) as f, open(small, "w") as g:
    lines = []
    for i, l in enumerate(f):
        if i > keep:
            break
        lines.append(l)
    g.writelines(lines)


REPLAY = os.environ.get("REPLAY_FILE", "ServerFv/Replay.lean")   # another copy of the replay, for a baseline run


_LAKE_ENV = None


def lake_env(leanpath):
    """The environment `lake env` gives, with `leanpath` put first on LEAN_PATH. Read once, then reused."""
    global _LAKE_ENV
    if _LAKE_ENV is None:
        p = subprocess.run(["lake", "env", "env", "-0"], capture_output=True, check=True)
        _LAKE_ENV = dict(kv.split("=", 1) for kv in p.stdout.decode().split("\0") if "=" in kv)
    env = dict(_LAKE_ENV)
    env["LEAN_PATH"] = leanpath + os.pathsep + env.get("LEAN_PATH", "")
    return env


def replay(files, leanpath=None, src=None):
    """files: a list of trace paths."""
    src = src or REPLAY
    cmd = ["lake", "env", "lean", "--run", src, *files]
    env = None
    if leanpath:
        cmd = ["lean", "--run", src, *files]
        env = lake_env(leanpath)
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


SESSIONS = []   # session ids of the copy, in order
for x in parsed[1:]:
    if not SESSIONS or SESSIONS[-1] != x["session"]:
        SESSIONS.append(x["session"])


def two_later(x):
    """A good create whose session has at least two sessions after it in the copy."""
    return is_created(x) and x["session"] in SESSIONS and SESSIONS.index(x["session"]) + 2 < len(SESSIONS)


def second_create(out, i):
    """Send the same good create again, right after the first. The document is the same afterwards, so only the
    one-create rule can see it."""
    out.insert(i + 1, out[i])


def id_comes_back(out, i):
    """Give the session two after this one this session's id. Its own lines are all honest, so only the seen-id rule can see it."""
    old, new = SESSIONS[SESSIONS.index(parsed[i]["session"]) + 2], parsed[i]["session"]
    for k in range(1, len(out)):
        if parsed[k]["session"] == old:
            y = copy.deepcopy(parsed[k])
            y["session"] = new
            out[k] = json.dumps(y) + "\n"


def has_rec(x):
    return x["after"] and isinstance(x["after"]["per_role"]["A"].get("rec"), list)


def all_rec_unknown(out, i):
    """Every rec in every before and after of the copy says "?", the trace's word for a value it can't name."""
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "rec":
                    o[k] = "?"
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    for k in range(1, len(out)):
        y = json.loads(out[k])
        walk(y.get("before"))
        walk(y.get("after"))
        out[k] = json.dumps(y) + "\n"


# The Lean side of "? vs ?": a copy of the replay whose recV shows "?" for every rec, as it does for a value of the wrong kind.
# The #guard on an honest rec would stop that copy from building, so it goes too.
REC_UNKNOWN = [("  | .num n => .arr [.int 32, .int n]\n", "  | .num n => .str \"?\"\n"),
               ("#guard (cmp \"p\" (recV (.num 5)) (Lean.toJson ([32, 5] : List Nat))).isNone\n", "")]


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
    ("txh holds the sig label", lambda x: x["after"] and x["after"]["per_role"]["A"].get("txh"),
     lambda x: x["after"]["per_role"]["A"].update(txh=x["after"]["per_role"]["A"]["txs"])),
    # Gaps 15 and 16. The first two edit the whole copy (a "file" change), not one line.
    ("second good create in a session", is_created, second_create, "file"),
    ("session id comes back", two_later, id_comes_back, "file"),
    # Codex D1 and D2. The rec keeps its length. "?" on both sides is a mismatch: both sides say "?" for every rec here.
    ("rec of 33 bytes, leading 00", has_rec, setp(["after", "per_role", "A", "rec"], lambda r: [33, r[1]]), None, r"\.rec\[0\]$"),
    ("'?' vs '?' at every rec", has_rec, (all_rec_unknown, REC_UNKNOWN), "lean", r"\.rec$"),
    ("auth code swapped", lambda x: x["op"].get("auth") == "stale_old" and x["code"] == "auth_stale", setp(["code"], "auth_bad_signature")),
    ("auth code swapped on a step", lambda x: x["op"]["op"] != "create" and x["op"].get("auth") == "unknown_device" and x["code"] == "auth_unknown_device",
     setp(["code"], "auth_stale")),
]


def tamper(ix):
    name, pred, change, *kind = TAMPER[ix]
    want = kind[1] if len(kind) > 1 else None
    kind = kind[:1]
    i = find(name, pred)
    x = copy.deepcopy(parsed[i])
    out = list(lines)
    src = None
    if kind == ["lean"]:   # change the whole copy and run a changed copy of the replay
        change, edits = change
        txt = open(REPLAY).read()
        for a, b in edits:
            assert txt.count(a) == 1, f"{name}: pattern count {txt.count(a)}"
            txt = txt.replace(a, b)
        src = f"{work}/t{ix}_Replay.lean"
        open(src, "w").write(txt)
        change(out, i)
    elif kind == ["file"]:
        change(out, i)
    elif change is None:   # move a phone's starting calibration on the create line of that session, up front
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
    rc, path, err, first = replay([f], src=src)
    os.remove(f)
    ok = rc == 1 and first and (not want or re.search(want, path))   # where it must be caught, when that matters
    return f"TAMPER {name}: {'caught' if ok else 'MISSED'} rc={rc} at {path} {err}"


# ------------------------------------------------------------ mutants

m_src = open("ServerFv/Machine.lean").read()
cut = m_src.index("/-- `Reachable e clock s`")
m_defs = m_src[:cut] + "\nend Machine\nend ServerFv\n"
v_src = open("ServerFv/Verdict.lean").read()
cut = v_src.index("/-- A signed record as `verify_record` reads it")
v_defs = v_src[:cut] + "\nend ServerFv\n"

g = {"M14X": []}   # machine_mutants.py's extra-file list; the replay copies use only the one-place change
txt = open("checks/machine_mutants.py").read()
exec(txt[txt.index("M = ["):txt.index("\nargs = sys.argv")], g)   # the table only, not its command-line filter
MUT = [("M", *x[:3]) for x in g["M"]] + [
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
    # Gap 2: the trace labels a hash with its wire string's label, so these pass only if Replay.lean reads labels by kind.
    ("M", "tx hash is the wire", "transcript_sha256 := e.p.sha256 raw, half := t.half", "transcript_sha256 := transcript_b64, half := t.half"),
    ("M", "commit hash is the wire", "commit_sha256 := e.p.sha256 raw, rec_ := c.rec_", "commit_sha256 := commit_b64, rec_ := c.rec_"),
    ("M", "record tx hash is the wire", "⟨t.transcript_b64, t.sig_b64, t.transcript_sha256⟩", "⟨t.transcript_b64, t.sig_b64, t.transcript_b64⟩"),
    ("M", "record tx wire and sig swapped", "⟨t.transcript_b64, t.sig_b64, t.transcript_sha256⟩", "⟨t.sig_b64, t.transcript_b64, t.transcript_sha256⟩"),
]

# Mutants no trace can reach. Each one changes a branch that Machine.step can't take, so no honest trace can show it, and a
# replay that passes it says nothing wrong. Each entry names the Lean theorem that rules the branch out. machine_mutants.py must still
# catch each one through a proof; this list only stops the replay from failing on it. Keep it short: a survivor not listed here fails the run.
UNREACHABLE = {
    # afterStore's last branch, `| _, _ => (s0, .error 500 .internal)`, runs only when combine refuses two stored transcripts.
    # combine_guard_unreachable (Machine.lean) says that on a Core document with both submitted, combine succeeds
    # (with Function.Injective e.pk, which the replay's .pk labels give), and afterStore_accepted builds on it. So the branch
    # is never taken and replay-2.txt lists `internal` as never hit. machine_mutants.py catches this one through the M14 proofs.
    "M14 afterStore internal keeps new doc": "combine_guard_unreachable",
}

ONLY = os.environ.get("REPLAY_ONLY")
if ONLY:
    TAMPER = [t for t in TAMPER if re.search(ONLY, t[0])]
    MUT = [m for m in MUT if re.search(ONLY, m[1])]
    print(f"REPLAY_ONLY={ONLY!r}: {len(TAMPER)} tampers, {len(MUT)} mutants. A filtered run, not the full check.")
    if not TAMPER and not MUT:
        print(f"FAIL: REPLAY_ONLY={ONLY!r} matches no tamper and no mutant. replay_checks rc 1")
        sys.exit(1)


def build(tag, vtxt, mtxt):
    root = f"{work}/{tag}"
    os.makedirs(f"{root}/ServerFv")
    for name, txt in (("Verdict", vtxt), ("Machine", mtxt)):
        open(f"{root}/ServerFv/{name}.lean", "w").write(txt)
        p = subprocess.run(["lean", "-R", root, "-o", f"{root}/ServerFv/{name}.olean", f"{root}/ServerFv/{name}.lean"],
                           capture_output=True, text=True, env=lake_env(root))
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
    rc, path, e, first = replay([small, *more], root)
    shutil.rmtree(root)
    tag = "caught" if rc == 1 and first else ("SURVIVED" if rc in (0, 3) else f"RUN ERROR {e}")   # rc 1 with no MISMATCH line is a compile error, not a catch
    if tag == "SURVIVED" and name in UNREACHABLE:
        tag = f"SURVIVED, allowed: no trace can reach it ({UNREACHABLE[name]})"
    return f"MUTANT {name}: {tag} rc={rc} at {path}" + (f"  [{first[first.find(' at '):][:240]}]" if ONLY and first else "")


root, err = build("control", v_defs, m_defs)
assert err is None, err
rc, path, e, first = replay([small, *more], root)
print(f"CONTROL definitions-only copy, no change: rc={rc} {first} {e}")
rc2, _, _, first2 = replay([small, *more])
print(f"CONTROL real build, the same untampered input: rc={rc2} {first2}")
shutil.rmtree(root)
if rc != 0 or rc2 != 0:   # 3 means the copy is short of sessions or targets, and then a survivor could be only that
    sys.exit("a control failed, so the rest would mean nothing")
print("UNREACHABLE allow-list:", "; ".join(f"{k} ({v})" for k, v in UNREACHABLE.items()))
with ThreadPoolExecutor(12) as ex:
    a = list(ex.map(tamper, range(len(TAMPER))))
    b = list(ex.map(mutant, range(len(MUT))))
for r in a + b:
    print(r)
print("tamper total", len(a), "missed", sum("MISSED" in r for r in a))
missed = sum("MISSED" in r for r in a)
caught = sum(": caught" in r for r in b)
allowed = sum("SURVIVED, allowed" in r for r in b)
print("mutants total", len(b), "caught", caught, "survived", sum("SURVIVED" in r for r in b), "of them allowed (unreachable)", allowed,
      "other", len(b) - caught - sum("SURVIVED" in r for r in b))
shutil.rmtree(work)
failed = missed + len(b) - caught - allowed
print("replay_checks rc", 1 if failed else 0)
sys.exit(1 if failed else 0)
