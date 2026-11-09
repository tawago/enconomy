"""One-place changes to a copy of ServerFv/Machine.lean. Each must break a proof.
Run from fv/v1/server/lean: python3 checks/machine_mutants.py [--no-extra] [name filter ...]
The file in the repo is not changed. A mutant that still compiles is printed as SURVIVED.
A mutant may name extra ServerFv/*.lean files (4th field). Their text, with `import` lines removed,
is put after the mutated Machine.lean in the order given (dependency order), so the theorems in those
files are checked against the mutated code too.
Name filters keep only mutants whose name contains one of them. --no-extra drops the extra files,
as a sanity check that a mutant caught only by an extra file then survives.
Before any mutant runs, a control copy (Machine.lean + the same extra files, not mutated) is compiled for each
extra-file set. It must compile with no error, or that set's mutants count as failed.
A mutant counts as broke only if an error lands in one of its expected theorems (EXPECT below).
Exit code 0 only if every mutant broke an expected theorem. A survivor, an error only elsewhere,
a failed control, a pattern that doesn't match, or a filter that keeps no mutant gives 1."""
import os, re, shutil, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor

src = open('ServerFv/Machine.lean').read()
M14X = ["M14Handlers", "M14Transcript", "M14"]

def extra_text(names):
    out = []
    for n in names:
        t = open(f'ServerFv/{n}.lean').read()
        out.append('\n'.join(l for l in t.split('\n') if not l.startswith('import ')))
    return '\n'.join(out)
# name, old text, new text, theorems we expect to break (at least one of them, or a lemma under them)
M = [
 ("no commit gate", "else if w.now < s.t0_ms.getD 0 + K.COMMIT_GATE_MS then", "else if False then"),
 ("partner code at arm (own_bed slot)",
  ".armMaterial s.attempt sr (_code s role) (_code s role)", ".armMaterial s.attempt sr (_code s role) (_code s (OTHER role))"),
 ("third attempt allowed",
  "if isRetry reason && Nat.blt (s.attempt + 1) K.MAX_ATTEMPTS then next_attempt s reason by_",
  "if isRetry reason && Nat.blt (s.attempt + 1) 3 then next_attempt s reason by_"),
 ("retry without attempt limit",
  "if isRetry reason && Nat.blt (s.attempt + 1) K.MAX_ATTEMPTS then next_attempt s reason by_",
  "if isRetry reason then next_attempt s reason by_"),
 ("age check dropped",
  "else if live s.state = true ∧ w.now - s.created_ms > K.SESSION_MAX_AGE_S * 1000 then", "else if False then"),
 ("started after one arm", "let s2 := _save (if all2 a = true then", "let s2 := _save (if a role = true then"),
 ("join skips token", "else if token.toLower ≠ s.join_token then .error (403, .bad_token)", "else if False then .error (403, .bad_token)"),
 ("self join allowed", "if guest = s.host_device_id then .error (400, .self_join)", "if False then .error (400, .self_join)"),
 ("fail on done not refused",
  "else if ¬ (s.state = .confirmed ∨ s.state = .started) then\n        .error (409, .bad_state)", "else if False then\n        .error (409, .bad_state)"),
 ("non-member passes as A", "| none => (s1, .error 403 .not_member)", "| none => handle e w s1 .A dev o"),
 ("bad transcript writes NEAR",
  "(_finalize e w s .NOT_NEAR (some rsn) none .rejected (some role),", "(_finalize e w s .NEAR (some rsn) none .rejected (some role),"),
 ("deadline one ms later",
  "else if s.state = .started ∧ w.now > s.t0_ms.getD 0 + K.TRANSCRIPT_DEADLINE_S * 1000 then",
  "else if s.state = .started ∧ w.now > s.t0_ms.getD 0 + K.TRANSCRIPT_DEADLINE_S * 1000 + 1 then"),
 ("retry keeps per_role", "    submitted := _flags\n    per_role := fun _ => {} }\n\n/-- `_finalize`", "    submitted := _flags }\n\n/-- `_finalize`"),
 ("commit signature not checked", "if e.p.verify_raw (e.pk dev) raw sig = false then", "if False then"),
 ("repeat commit refused", "else (s, _partner_bed s role)                                                 -- 296", "else (s, .error 409 .already_committed)"),
 ("repeat transcript refused", "(s, .accepted s.state s.attempt)                                              -- 424-425", "(s, .error 409 .already_submitted)"),
 ("stale check ignores state", "(s.state = .confirmed || s.state = .started) && Decidable.decide (attempt < (s.attempt : ℤ))", "Decidable.decide (attempt < (s.attempt : ℤ))"),
 ("retry keeps t0", "    state := .confirmed\n    t0_ms := none\n", "    state := .confirmed\n"),
 ("abort clears t0", "    state := .aborted, error := some .aborted\n", "    state := .aborted, error := some .aborted, t0_ms := none\n"),
 ("commit rewrites t0", "  _save { s with\n    per_role := upd s.per_role role { s.per_role role with commit := some cd }\n",
  "  _save { s with\n    t0_ms := s.t0_ms.map (· + 1)\n    per_role := upd s.per_role role { s.per_role role with commit := some cd }\n"),
 ("both transcripts in answers an error",
  "(s1, .accepted s1.state s1.attempt)                                             -- 462", "(s1, .error 400 .bad_request)"),
 # Gap 14: E2 must win over E3. With E3 checked first, E3 finishes the E2 run instead.
 ("E3 before E2",
  "  else if live s.state = true ∧ w.now - s.created_ms > K.SESSION_MAX_AGE_S * 1000 then\n"
  "    _save { s with state := .aborted, error := some .timeout }\n"
  "  else if s.state = .started ∧ w.now > s.t0_ms.getD 0 + K.TRANSCRIPT_DEADLINE_S * 1000 then\n"
  "    _failed e w s (some .timeout) (silent s)\n",
  "  else if s.state = .started ∧ w.now > s.t0_ms.getD 0 + K.TRANSCRIPT_DEADLINE_S * 1000 then\n"
  "    _failed e w s (some .timeout) (silent s)\n"
  "  else if live s.state = true ∧ w.now - s.created_ms > K.SESSION_MAX_AGE_S * 1000 then\n"
  "    _save { s with state := .aborted, error := some .timeout }\n",
  ["WitnessE2"]),
 # Gap 5, M14: an error answer writes nothing.
 ("M14 commit too_early saves", "(s, .error 409 .too_early)", "(_save s, .error 409 .too_early)", M14X),
 ("M14 arm bad_state saves", "then (s, .error 409 .bad_state)    -- 231-232", "then (_save s, .error 409 .bad_state)    -- 231-232", M14X),
 ("M14 transcript already_submitted saves",
  "else (s, .error 409 .already_submitted)", "else (_save s, .error 409 .already_submitted)", M14X),
 ("M14 afterStore internal keeps new doc",
  "| _, _ => (s0, .error 500 .internal)", "| _, _ => (s, .error 500 .internal)", M14X),
 ("M14 viewOr error saves", "| .error (st, c) => (s, .error st c)", "| .error (st, c) => (_save s, .error st c)", M14X),
 ("M14 non-member saves", "| none => (s1, .error 403 .not_member)", "| none => (_save s1, .error 403 .not_member)", M14X),
 # Gap 13: guards of /fail.
 ("fail after transcript allowed",
  "else if s.submitted role = true then .error (409, .already_submitted)", "else if False then .error (409, .already_submitted)",
  ["GuardsFail"]),
 ("fail attempt not checked",
  "else if n ≠ (s.attempt : ℤ) then .error (400, .bad_attempt)", "else if False then .error (400, .bad_attempt)", ["GuardsFail"]),
 ("fail reason not checked",
  "if rsn ∉ PHONE_REASONS then .error (400, .bad_reason)", "if False then .error (400, .bad_reason)", ["GuardsFail"]),
 # Gap 13: guards of /arm and the view's nonce.
 ("arm rtt not checked",
  "if rttOk rtt = false then (s, .error 400 .bad_request)", "if False then (s, .error 400 .bad_request)", ["GuardsArmView"]),
 ("re-arm rate not checked",
  "if (s.per_role role).arm.map (·.sample_rate) ≠ some sr then", "if False then", ["GuardsArmView"]),
 ("nonce shown before confirm",
  "nonce := if all2 s.confirmed = true then some s.nonce_hex else none", "nonce := some s.nonce_hex", ["GuardsArmView"]),
]

# Theorems each mutant is expected to break: at least one error must be inside one of them.
EXPECT = {
 "no commit gate": ["commit_inv"],
 "partner code at arm (own_bed slot)": ["arm_material_codes"],
 "third attempt allowed": ["failed_inv", "frame_failed"],
 "retry without attempt limit": ["failed_inv", "frame_failed"],
 "age check dropped": ["expire_fresh", "expire_inv", "expire_link", "frame_expire"],
 "started after one arm": ["arm_inv", "frame_arm"],
 "join skips token": ["join_ok"],
 "self join allowed": ["join_inv", "join_ok"],
 "fail on done not refused": ["M1_terminal", "M4", "fail_inv", "frame_fail"],
 "non-member passes as A": ["M12_non_member", "M1_terminal", "M4", "M5_codes", "M5_no_strings", "frame_step", "step_inv", "step_records", "t0_step"],
 "bad transcript writes NEAR": ["transcript_inv"],
 "deadline one ms later": ["expire_fresh"],
 "retry keeps per_role": ["M8_retry_wipes", "next_attempt_inv"],
 "commit signature not checked": ["commit_inv"],
 "repeat commit refused": ["M10_commit_different", "M10_commit_repeat_answer", "commit_shape"],
 "repeat transcript refused": ["M10_tx_different", "M10_tx_repeat_answer"],
 "stale check ignores state": ["M10_over_transcript", "M8_stale_fail", "M8_stale_transcript"],
 "retry keeps t0": ["M8_retry_wipes", "next_attempt_inv"],
 "abort clears t0": ["abort_inv", "t0_abort"],
 "commit rewrites t0": ["commitStore_inv", "t0_commit"],
 "both transcripts in answers an error": ["afterStore_accepted"],
 "E3 before E2": ["E2_beats_E3_one_tx"],
 "M14 commit too_early saves": ["commit_inv", "commit_shape", "frame_commit"],
 "M14 arm bad_state saves": ["arm_err_doc", "arm_inv", "frame_arm"],
 "M14 transcript already_submitted saves": ["M10_tx_different", "M10_tx_repeat", "frame_transcript", "transcript_err_doc", "transcript_inv"],
 "M14 afterStore internal keeps new doc": ["afterStore_err_doc", "afterStore_inv", "frame_afterStore", "t0_afterStore"],
 "M14 viewOr error saves": ["M12_member", "frame_viewOr", "viewOr_err_doc", "viewOr_inv"],
 "M14 non-member saves": ["M12_non_member", "M14", "frame_step", "step_inv"],
 "fail after transcript allowed": ["fail_ok_iff"],
 "fail attempt not checked": ["fail_ok_iff"],
 "fail reason not checked": ["fail_ok_iff"],
 "arm rtt not checked": ["arm_ok_rtt"],
 "re-arm rate not checked": ["arm_rate_matches"],
 "nonce shown before confirm": ["view_nonce_gate", "view_nonce_hidden"],
}

args = sys.argv[1:]
no_extra = '--no-extra' in args
filters = [a for a in args if a != '--no-extra']
if filters:
    M = [m for m in M if any(f in m[0] for f in filters)]
if not M:
    print('no mutant matches', filters)
    print('mutants done')
    sys.exit(1)

def extras_of(m):
    return () if no_extra else tuple(m[3]) if len(m) > 3 else ()

tmpdir = tempfile.mkdtemp(prefix='machfix_')
DECL = re.compile(r'(?:@\[[^\]]*\]\s*)*(?:private |protected |noncomputable )*(theorem|lemma|def|abbrev|structure|inductive|instance)\s+(\S+)')

def compile_(fn, txt):
    """Compile txt; return (rc, [(line, kind, name)] of errors)."""
    path = os.path.join(tmpdir, fn)
    open(path, 'w').write(txt)
    p = subprocess.run(['lake', 'env', 'lean', path], capture_output=True, text=True)
    os.remove(path)
    out = p.stdout + p.stderr
    ls = txt.split('\n')
    def owner(k):
        for i in range(k - 1, -1, -1):
            m = DECL.match(ls[i])
            if m: return m.group(1), m.group(2)
        return '?', '?'
    errs = [int(m.group(1)) for m in re.finditer(re.escape(fn) + r':(\d+):\d+: error', out)]
    # an error the regex can't place still counts as an error
    if p.returncode != 0 and not errs:
        errs = [0]
    return p.returncode, [(k, *owner(k)) for k in errs]

def with_extra(txt, extra):
    return txt + '\n' + extra_text(extra) + '\n' if extra else txt

def control(ix, extra):
    try:
        rc, errs = compile_(f"machfix_control_{ix}.lean", with_extra(src, extra))
    except OSError as e:
        return False, f"CONTROL {list(extra)}: FAILED {e}"
    ok = rc == 0 and not errs
    return ok, f"CONTROL {list(extra)}: {'clean' if ok else 'FAILED'} rc={rc} errors={len(errs)} in={sorted(set(n for _, _, n in errs))}"

def run(ix, ctl_ok):
    name, a, b = M[ix][:3]
    extra = extras_of(M[ix])
    if not ctl_ok[extra]:
        return f"MUTANT {name}: CONTROL FAILED for {list(extra)}"
    if name not in EXPECT:
        return f"MUTANT {name}: NO EXPECT entry"
    n = src.count(a)
    if n != 1:
        return f"MUTANT {name}: BAD PATTERN count={n}"
    rc, errs = compile_(f'machfix_mut_{ix}.lean', with_extra(src.replace(a, b), extra))
    names = sorted(set(nm for _, _, nm in errs))
    hit = sorted(set(nm for _, kind, nm in errs if kind in ('theorem', 'lemma') and nm in EXPECT[name]))
    if rc != 0 and hit:
        tag = 'broke'
    elif rc != 0:
        tag = 'UNEXPECTED (no error in an expected theorem)'
    else:
        tag = 'SURVIVED'
    return f"MUTANT {name}: {tag} rc={rc} errors={len(errs)} in={names} expected_hit={hit}"

try:
    sets = sorted(set(extras_of(m) for m in M))
    with ThreadPoolExecutor(6) as ex:
        cres = list(ex.map(control, range(len(sets)), sets))
    ctl_ok = {}
    for st, (ok, line) in zip(sets, cres):
        print(line); ctl_ok[st] = ok
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(lambda i: run(i, ctl_ok), range(len(M))))
finally:
    shutil.rmtree(tmpdir, ignore_errors=True)
for r in res:
    print(r)
good = sum(': broke ' in r for r in res)
print('mutants total', len(res), 'no-extra' if no_extra else '', 'broke', good, 'survived', sum('SURVIVED' in r for r in res),
      'unexpected', sum('UNEXPECTED' in r for r in res), 'bad pattern', sum('BAD PATTERN' in r for r in res),
      'control failed', sum(not v for v in ctl_ok.values()))
print('mutants done')
sys.exit(0 if good == len(res) and all(ctl_ok.values()) else 1)
