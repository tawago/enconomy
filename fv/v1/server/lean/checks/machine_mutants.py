"""One-place changes to a copy of ServerFv/Machine.lean. Each must break a proof.
Run from fv/v1/server/lean: python3 checks/machine_mutants.py
The file in the repo is not changed. A mutant that still compiles is printed as SURVIVED.
Exit code 0 only if every mutant broke a proof. A survivor or a pattern that doesn't match gives 1."""
import os, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

src = open('ServerFv/Machine.lean').read()
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
]

def run(ix):
    name, a, b = M[ix]
    n = src.count(a)
    if n != 1:
        return f"MUTANT {name}: BAD PATTERN count={n}"
    txt = src.replace(a, b)
    fn = f'/tmp/machfix_mut_{ix}.lean'
    open(fn, 'w').write(txt)
    p = subprocess.run(['lake', 'env', 'lean', fn], capture_output=True, text=True)
    os.remove(fn)
    out = p.stdout + p.stderr
    errs = [int(m.group(1)) for m in re.finditer(r'machfix_mut_\d+\.lean:(\d+):\d+: error', out)]
    ls = txt.split('\n')
    def owner(k):
        for i in range(k - 1, -1, -1):
            m = re.match(r'(?:private )?(theorem|def|structure)\s+(\S+)', ls[i])
            if m: return m.group(2)
        return '?'
    tag = 'broke' if p.returncode != 0 and errs else 'SURVIVED'
    return f"MUTANT {name}: {tag} rc={p.returncode} errors={len(errs)} in={sorted(set(owner(k) for k in errs))}"

with ThreadPoolExecutor(6) as ex:
    res = list(ex.map(run, range(len(M))))
for r in res:
    print(r)
print('mutants total', len(res), 'survived', sum('SURVIVED' in r for r in res), 'bad pattern', sum('BAD PATTERN' in r for r in res))
print('mutants done')
sys.exit(1 if any('SURVIVED' in r or 'BAD PATTERN' in r for r in res) else 0)
