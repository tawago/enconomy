# Server side: does the server follow its rules?

**What this shows.** The server follows its rules on signed numbers. That covers the basic proximity flow, on a hand-written Lean copy of the rules, on a walk over the real routes, and on a replay that compares the two.

**What this does not show.** It does not show a phone told the truth about the air (CN1). A phone can still sign a false half, and theorems `X1` and `X1_session` say so: two signers can reach NEAR with numbers they picked, and nothing in the verdict reads sound. A NEAR means two keys signed two numbers that fit a range. It is not a proof of proximity.

**Read this before quoting anything.** The last re-reviews of `spec.md` and `Machine.lean` passed, and so did the last critic. The `Verdict.lean` and `test_walk.py` re-reviews failed. Their defects were fixed afterwards and not reviewed again. The Lean files added on 2026-11-07 each had one chunk review, which ended on pass, but no track review. On 2026-11-09 Codex (gpt-6-astra) reviewed the work again, found defects in M14, `X1_session`, the checkers, the replay and the docs, and passed the fixes on re-review, with low items left open (report: [`reviews/2026-11-09-codex.md`](reviews/2026-11-09-codex.md)). See [Review verdicts](#review-verdicts) and [Known gaps](#known-gaps). Nothing here should be called verified.

**Scope.** Sessions with `context=None` and policy `human=none` only. No claim about World ID, Safe, attestation, ENS, the bridge, zk routes, recording upload, enrolment attestation parsing or DSP.

**Pinned code.** This work is pinned to `main` at commit `9db1490`. Later commits changed `server/pop/sessions.py`, `main.py`, `constants.py` and 12 other files under `server/pop/` (`git diff --stat 9db1490 HEAD -- server/pop`). **Nothing has been rerun against them.** Line numbers in these files are for `9db1490`.

Files: [`spec.md`](spec.md) has the rules and properties. `lean/ServerFv/` has the proofs and the replay. `tests/test_walk.py` is the walk. `logs/` holds the runs cited here. `reviews/` holds the review reports that were kept.

## Reproduce from a fresh clone

These commands use only plain tools. **They have not been run start to finish as written from a clean clone.** Each step ran on a prepared Linux machine, with the same folder layout and Python 3.12. That machine used its own Python environment, not `server/uv.lock`, and its package versions were not recorded. So `uv sync` below may give other versions. On a Mac you may need `sha256sum` from coreutils for `replay_all.sh`.

Put the code under proof in place first. A plain clone holds newer server code, so skipping this tests the wrong thing. This changes only your throwaway clone.

```bash
git clone <this repo> pop-fv && cd pop-fv
rm -rf server && git checkout 9db1490 -- server
cd server && uv sync --group dev --python 3.12 && source .venv/bin/activate && cd ..
```

Install `elan` for Lean. It picks the version in `lean-toolchain`. The times below are from one run, and vary by machine.

### Lean proofs

```bash
cd fv/v1/server/lean
lake exe cache get      # downloads prebuilt Mathlib
lake build
lake env lean ServerFv/Verdict.lean      # recheck without the build cache
```

Expected: `Build completed successfully (18241 jobs).` The count can differ on another machine. Axiom lines, one per `#print axioms`: Machine 56, Verdict 29, and one per main theorem in each 2026-11-07 file, all within `propext`, `Classical.choice`, `Quot.sound`. Any `sorryAx` means a broken proof. Log: `logs/lean-final-4.txt`, the circuit model build (`zkp/popfv`), the server build and then `machine_all.sh` in one run, 2026-11-09. It starts with the sha256 of every source file it checked; all match the files here except `V7Facts.lean` and `V7Missing.lean`, whose headers changed after it (docstrings only, rebuilt in `logs/lean-v7-docstrings.txt`, hashes in `logs/post-run-edits.txt`). `Verdict.lean` changed in docstrings only since `logs/lean-final.txt`; the build in `lean-final-4.txt` rebuilt it, with its 29 axiom lines.

```bash
bash checks/machine_all.sh     # build, fresh check of each file, axiom scan, word scan, traces, 34 mutants, about 4 min
```

It checks `Machine.lean` and every other file in `ServerFv/` except `Verdict.lean` and `Replay.lean`. Remove any scratch `.lean` file from `ServerFv/` first, or the glob picks it up and it fails. Expected: every `fresh rc=0`, `traces rc=0`, `mutants total 34  broke 34 survived 0 unexpected 0 bad pattern 0 control failed 0`, then `overall rc=0`. The exit code is 1 if any step fails. Log: `logs/lean-final-4.txt`; its `machine_all` part alone is `logs/lean-machine-checks-6.txt`. `lean-machine-checks-4.txt` and `-5.txt` are the runs during the checker fixes, and `logs/machine-checks-negative.txt` shows four broken inputs each ending rc=1 (unreadable scan file, broken extra file, filter matching nothing, `sorryAx` in an axiom list Lean wraps over lines). All these runs named the repo's 27 files as arguments instead of using the glob, because the box copy held old scratch files; the steps are the same.

### Spec rechecks, on the real routes

```bash
cd fv/v1/server
python spec-checks/recheck.py     # 191 PASS lines, "done, 0 failed", about 30 s
PYTHONPATH=../../../server python spec-checks/layout_vectors.py logs/lean-verdict.txt
cd tests && python recheck_m6_fail.py     # 17 PASS lines, "done, 0 failed"
```

Logs: `logs/spec-recheck.txt`, `logs/layout-vectors.txt`, `logs/spec-recheck-m6-fail.txt`. Depth numbers in `E500-*` belong to Python 3.12 and this setup.

### Walk

```bash
cd fv/v1/server/tests
env PYTHONPATH=../../../../server python -m pytest -q test_walk.py --walk-sessions 1000
```

Expected: `62 passed`, about 13 min. 62 = 7 single tests, 45 mutation cases, 7 pair-clause cases and 3 `verify_record` cases. Log: `logs/walk-final-3.txt`, seed 20261106, rc=0, 810 s. It records the sha256 of `test_walk.py` (`c31e507a...`, the current file), `conftest.py` and the 33 server files used, which match `git show 9db1490:<path>`. Each of the 45 mutations is caught by its wanted property. `view_header_holds_seed` shows `M5,M6`: the extra header also trips the M6 allow-list. `view_header_holds_partner_sig` must show the partner-sig scan's own line (`[M6] partner sig_b64 in a response to view while live`), so the allow-list alone can't pass it. The new `stored_rec_33_bytes` (a stored recording value with a leading 00 byte, same number) is caught as M1: the walk now keeps a recording value as `[length, value]`, and any `?` in the stored-doc projection fails M1. Fewer sessions can fail on coverage only: 500 sessions missed two targets (`logs/walk-final-500.txt`, an older file).

### Replay of the Lean table on real traces

Traces are not in the repo, about 68 MB each. Make them, then replay. From `fv/v1/server/tests`:

```bash
T=/tmp/pop-traces; mkdir -p $T
env PYTHONPATH=../../../../server python -m pytest -q -p no:cacheprovider test_walk.py --walk-seed 20261106 --walk-sessions 2000 --trace-out $T/walk-20261106.jsonl
env PYTHONPATH=../../../../server python -m pytest -q -p no:cacheprovider test_walk.py::test_walk --walk-seed 7001 --walk-sessions 2000 --trace-out $T/walk-7001.jsonl
env PYTHONPATH=../../../../server python -m pytest -q -p no:cacheprovider test_walk.py::test_walk --walk-seed 7002 --walk-sessions 2000 --trace-out $T/walk-7002.jsonl
env PYTHONPATH=../../../../server python -m pytest -q -p no:cacheprovider test_walk.py::test_directed_cases --directed-trace-out $T/directed.jsonl
```

From `fv/v1/server/lean`:

```bash
bash checks/replay_all.sh $T/walk-20261106.jsonl $T/walk-7001.jsonl $T/walk-7002.jsonl $T/directed.jsonl
python3 checks/replay_checks.py $T/walk-20261106.jsonl 0 $T/directed.jsonl     # 0 = whole trace, about 10 min
```

Expected, `replay_all.sh`: 6032 sessions, 94251 lines, 83329 steps, 0 mismatches, all 35 chosen targets reached, rc=0. Run one at a time, `walk-7002` gives rc=0, `walk-20261106` and `walk-7001` give rc=3 (a coverage target missed, no mismatch), and the directed trace is under the session floor; the script only notes those. Log: `logs/replay-4.txt`, on the v5 traces (trace format `pop-walk-trace-4`). It records the sha256 of every Lean file and script it ran and of the four traces. Since the 2026-11-09 fixes a recording value is compared as `[length in bytes, value]`, and `?` (a value of the wrong kind, or an unknown Python value) never equals anything, `?` included.

Then `replay_checks.py`: both controls rc=0 on the same untampered input the rule changes get, 67 of 67 tampers caught, 104 rule changes with 103 caught and 1 allowed, `replay_checks rc 0`, about 10 min. Log: `logs/replay-checks-5.txt`, with the sha256 of its sources and traces. The two new tampers: a 33-byte recording value with a leading 00 (caught at `.rec[0]`), and `?` against `?` at every recording value, run on a patched `Replay.lean` that shows every recording value as `?` (caught at `.rec`). The baseline that would show the old `cmp` missing the second was not run. With `REPLAY_ONLY` set to a pattern that matches nothing, the script exits 1; the logged run had no filter. Every trace path must be an existing regular file that does not start with `-` (else `Replay.lean` would read `--stop-first` or `--min-sessions=N` as a flag and skip it), and is passed absolute with no shell; the log opens with two `--stop-first` demos, each rc=1. `logs/replay-checks-4.txt` is the same run on the script before these fixes. The allowed one is "M14 afterStore internal keeps new doc", on an allow-list of unreachable changes that the script prints. It changes the 500 `internal` branch of `afterStore`. No trace reaches that branch (`internal` is under codes never hit), and `combine_guard_unreachable` says no step gets there, given one-to-one keys. The Lean mutant run catches it through the M14 proofs (`logs/lean-final-4.txt`). Any other survivor fails the run. A run with the `Replay.lean` from before gaps 15 and 16 misses all four tampers added then (header of `replay-checks-3.txt`, an older round).

A number of lines other than 0 cuts the trace. 12000 lines puts the control under the session floor, so the run fails on purpose (`logs/replay-checks-2-first12000.txt`, an older script). The older logs `logs/replay-3.txt`, `logs/replay-checks-3.txt`, `logs/replay-2.txt`, `logs/replay-checks-2.txt`, `logs/replay.txt`, `logs/replay-checks.txt` and `logs/replay-exit-codes.txt` are for older copies of `Replay.lean`, `replay_checks.py` or the trace format.

The v5 traces were made by the current `test_walk.py` (`c31e507a...`) on the same box and at the same time as `walk-final-3.txt`: seed 20261106 with 2000 sessions, 62 passed; 7001 and 7002 with the walk test alone, 1 passed each; the directed cases, 1 passed. Their sha256 are in the header of `replay-4.txt` (directed `ef88cfd8...`, 32 sessions). The trace projection changed with the 2026-11-09 fixes, so the v4 traces (`logs/traces-v4.txt`) are the old format; the current replay ran on v5 only. Same seed, same bytes was shown for v4, not checked again for v5. Not tried on another machine.

## What ran on which file

**The final walk ran 1000 sessions on the current `test_walk.py`**: `logs/walk-final-3.txt`, seed 20261106, 62 passed, rc=0. Its header holds the sha256 of `test_walk.py` (`c31e507a...`), which matches the file in this folder. The 2000-session v5 trace runs used the same file: 62 passed for seed 20261106, 1 passed each for 7001 and 7002 with the walk test alone (header of `walk-final-3.txt`).

**Older runs were on earlier versions of the test.** `logs/walk-final-2.txt` (61 passed, `672f8de7...`, before the 2026-11-09 fixes), `logs/traces-v4.txt`, `logs/walk-final.txt` (59 passed, sha256 `02243d66...`) and `logs/walk.txt` (28 tests) predate the current file. A 2000-session run of 59 tests made the v3 traces; only its tails are kept (`logs/replay-exit-codes.txt`), with no file hash.

**Files edited after the 2026-11-07 runs.** To take private run details out for this public repo, comment and docstring lines changed in `test_walk.py`, `recheck.py`, `recheck_m6_fail.py`, `Replay.lean`, `lakefile.toml` and all four scripts in `lean/checks/`. `logs/post-run-edits.txt` lists each file with lines changed and both hashes. `Machine.lean` and `Verdict.lean` did not change. In the logs, paths, job ids and upload lines came out, and short notes were added. Results were not changed. That pass missed the job labels in ten older logs; they came out on 2026-11-09, noted at the end of `post-run-edits.txt`.

Two problems with that record, found by the `test_walk.py` re-review. Both are now marked in `post-run-edits.txt` itself:

- The committed `test_walk.py` (`7ebfec1a...`) does not have the "after" hash there. A second edit went unrecorded. The file of that time (`672f8de7...`) was backed by `walk-final-2.txt` instead; the current one (`c31e507a...`) is backed by `walk-final-3.txt`.
- The "Rerun after these edits" lines give no log, file hash or job id, and their numbers repeat the older logs. They are marked unbacked.

**Runs on the current files.** The full build and `machine_all.sh` (`logs/lean-final-4.txt`), the replay (`logs/replay-4.txt`, `logs/replay-checks-5.txt`) and the walk (`logs/walk-final-3.txt`) ran on the current Lean files, the current `Replay.lean`, `machine_all.sh`, `machine_mutants.py`, `replay_checks.py` and `test_walk.py`. Each of these logs now starts with the sha256 of the sources it ran. Later changes: the `V7Facts.lean` and `V7Missing.lean` headers (docstrings, `logs/lean-v7-docstrings.txt`), the `machine_all.sh` checker fixes (rerun on the box, `logs/lean-machine-checks-7.txt`), and the `replay_checks.py` changes (empty-filter exit, no shell, trace-path checks; full run redone in `logs/replay-checks-5.txt`). Other 2026-11-09 logs: `lean-x1-session.txt` (the `X1_session` fix, built alone), `lean-machine-checks-4.txt`, `-5.txt` and `machine-checks-negative.txt` (checker fixes). The M14 fix was built alone with no log kept; `lean-final-4.txt` builds and checks it. Logs `lean-final-3.txt`, `lean-final-2.txt`, `lean-machine-checks-3.txt`, `replay-3.txt`, `replay-2.txt`, `replay-checks-3.txt`, `replay-checks-2*.txt`, `walk-final-2.txt` and `traces-v4.txt` are from earlier rounds and are kept for the record.

## Review verdicts

Reviews in rounds 1 to 3 marked Opus were by Claude Opus agents. The trace reviews and the first critic were judged by **Codex (gpt-6-astra)**, with Opus running the jobs and feeding it the output. For round 4 (the `RR-*` re-reviews and the second critic, 2026-11-07 into 11-08) the reviewer model was not recorded. They read files and ran at most a rebuild. No report from rounds 1 to 4 was kept; the verdicts below are from the run notes.

From 2026-11-09 on, reviews are by **Codex (gpt-6-astra)**, read-only. Opus agents drive them: they hand Codex the files, fix what it finds, run the jobs, and check each finding against the source before calling it confirmed or refuted. Reports, with Codex thread ids: [`reviews/2026-11-09-codex.md`](reviews/2026-11-09-codex.md).

| Track | Reviewer | Rounds | Last verdict | Why | What happened after |
| --- | --- | --- | --- | --- | --- |
| `spec.md` (RR-spec) | Opus, then not recorded | 4 | **pass** | M6 report table, the create row and the E500-create row checked against 9db1490 and both logs. Nits only: the `parse_session_in` range ran one line long, the E500-create depths read as tested at every depth. | Both nits fixed. `Machine.lean`'s two `spec.md` nits fixed too (A5 row, guard note). Not reviewed again. |
| `Machine.lean` (RR-machine) | Opus, then not recorded | 4 | **pass** | The one-to-one-keys header and `M8_keys`'s hash hypothesis hold. Nits in `spec.md` only. | Nits fixed in `spec.md`. 34 of 34 Lean mutants break a proof (`logs/lean-final-4.txt`). |
| `Verdict.lean` (RR-verdict) | Opus, then not recorded | 4 | **fail** | `X1_on_layout` and `X1_on_layout_keys` said "all-zero recording values", which their statements didn't pin. This README cited an X1 copy that wasn't in the repo and miscounted its equalities. The `X1` paragraph on `ccA` and the `X1_core` "any numbers" read as statement-level claims. | `X1_on_layout_keys` now pins both recording values. The `X1_on_layout`, `X1`, `X1_core` and `X1_session_on_layout` docstrings now say only what each statement pins. README fixed. **Not reviewed again.** |
| `test_walk.py` (RR-walk) | Opus, then not recorded | 4 | **fail** | Run records: the "after" hash in `post-run-edits.txt` doesn't match the committed file, its rerun lines have no log, the README was stale, and the new header check had no run. | Full walk, 61 passed (`logs/walk-final-2.txt`). The two comments it flagged are fixed. `post-run-edits.txt` marks both problems. Not reviewed again as a track; the 2026-11-09 walk changes passed Codex (row below), and the current file gives 62 passed (`logs/walk-final-3.txt`). |
| `Replay.lean` | Codex, Opus ran jobs | 3 | **fail** | A false pass: one label kind for wire, signature and hash. Some dropped fields undisclosed. | Labels read by kind, dropped fields listed, gaps 15 and 16 added. Two chunk reviews of those changes passed. **No track re-review**; the 2026-11-09 Codex review covered only its D1 to D3 changes. |
| Circuit `Commit.lean`, `WitnessCommit.lean` (RR-commit) | Opus, then not recorded | see `05` | **fail** | `05-spike-results.md` said the recheck witness was in a scratch file, but `WitnessCommit.lean` is in the repo. Its mutant claim had no log. | Doc fixed. Mutants now logged in `../zkp/logs/chain-mutants.txt`. `WitnessCommit.lean` wording fixed. Not reviewed again. |
| Circuit `Chain.lean` (RR-chain-a, RR-chain-b) | Opus, then not recorded | see `05` | **fail**, both | Wording only: the header and one docstring listed less than `silence_satisfies_presence_sound` exports, `PhoneTypes` read as a full list, "loud recording" lacked a qualifier, and the Chain mutants had no log. No proof defect. | Wording fixed in `Chain.lean` and the docs. Mutants logged in `../zkp/logs/chain-mutants.txt`. Not reviewed again. |
| Whole work, critic | Codex, then not recorded | 2 | **pass** | Every gap called closed has a theorem that builds or a log line behind it. No false claim found. Wording, provenance and open items listed. | Its listed items are taken into this README and the logs. |
| Whole work, 2026-11-09 first pass | Codex astra | 1 | findings | M14 left the finalized doc open (high). `X1_session` didn't pin the run or the stored values. Checkers passed on a read error, an unrelated compile error, an empty filter. Replay dropped recording length and matched `?` to `?`; one walk mutation was caught by the allow-list only. Doc and log slips. | All fixed this round, see the rows below and gaps 1, 2, 4, 5, 8, 11. |
| M14 fix (`M14Transcript.lean`, `M14.lean`) | Codex astra, Opus checked | 1 | **pass** | `TxReject` pins the two docs a 400 may finalize and whom each blames. Open, low to medium: the unchanged-doc case has no status limit, so a 400 that skips the finalize still fits; the combine branch doesn't tie the reason to `combine`; `M14_any`'s `= s` case is unconditional. | Open items listed in gap 5. Not fixed. |
| `X1_session` fix (`X1Session.lean`) | Codex astra, Opus checked | 1 | **pass** | `X1Reached` pins the run from `create` at `T` and the stored values. Low: the layout instances set both recording values and the nonce to all-zero and both self deltas to 0, so they can't show an A/B swap. | Listed in gap 4. Not fixed. |
| Checkers (`machine_all.sh`, `machine_mutants.py`) | Codex astra, Opus checked | 2 | **pass** | Round 1 fixes hold. Round 2 found more, low: the axiom allow-list's dots are regex wildcards (`ClassicalXchoice` passes, confirmed); an explicit `""` argument skips the per-file checks; `owner()` has no end of declaration. | Allow-list and empty argument fixed (gap 8, `logs/lean-machine-checks-7.txt`). `owner()` open. Not re-reviewed. |
| Replay and walk (`Replay.lean`, `test_walk.py`, `replay_checks.py`) | Codex astra, Opus checked | 1 | **pass** | D1 to D3 fixed. Low: `REPLAY_ONLY` matching nothing exits 0. D4 was this README. | D4 fixed in gap 2. The filter now exits 1 (gap 22). Not re-reviewed. |
| Docs (this README, `spec.md`, `coverage.md`, V7 headers, old logs) | Codex astra first pass only | 0 | not re-reviewed | E1 to E6. | Fixed in this doc pass. **Not reviewed again.** |

Each Lean file added on 2026-11-07 also had one chunk review that tried to refute it. All ended pass. Three passed only after a fix: `X2.lean` (a docstring said no flight was stored), `V7Session.lean` (docstrings said rows 3 and 4 match the verdict and flight) and `X1SessionTx.lean` (did not finish building).

The runs listed under [What ran on which file](#what-ran-on-which-file) are runs, not reviews.

## Each property

"Lean" means proved on the hand-written model, under named hypotheses, with no `sorry`. "Walk" means checked after every step on sampled runs of the real routes; "named mutation" means a weakened server was caught for that property in `logs/walk-final-3.txt`. "Replay" means the Lean table agreed with Python on sampled traces, on the compared fields. Those two are testing, not proof. The Lean-to-Python link is never a proof.

Several last reviews failed and their fixes were not reviewed again, so read the status column together with the table above.

| Id | Lean theorem | Walk | Replay | Reading or spot run | Note |
| --- | --- | --- | --- | --- | --- |
| V1 | `V1`, `combine_role_guard`, `combine_ok_roles` | yes, named mutation | partly: role guard never exercised | `recheck.py` | `combine_role_guard` is about the model only. The guard is unreachable through `step`, so no trace checks it. |
| V2 | `V2` | yes | through `combine` | `recheck.py` | Over rationals. NaN gives NEAR, no caller passes it. |
| V3 | `V3`, `V3_ties`, `V3_circuit`, `V3_near_gives_range`, `V3_range_does_not_give_near` | yes, no named mutation | through `combine` | `recheck.py` | Bridges to `Pair.distance_iff`. |
| V4 | `V4`, `V4_cal`, `V4_edges` | yes, named mutation | through `combine` | `recheck.py` | |
| V5 | `V5_combine_swapped`, `V5_record_swapped`, `V5_record_swapped_mixed_versions`, `V5_record_all_swapped`, `V5_live_other_role` | yes, named mutation | no | `recheck.py` | `V5_record_swapped_mixed_versions` takes "A never signed these bytes" as an input premise. |
| V6 | `V6`, `V6_free` | no check of its own, no named mutation | partly | `recheck.py` | Decoded fields and signature bits are recorded facts in the replay. |
| V7 | `V7_session`, `V7_both`, `V7_both_inj`, `V7_near`, `V7_verdict_row`, `V7_failed_row`, `V7_failed_row_flight`, `V7_missing`, `V7_missing_submitted`, `resultFacts` | yes, on direct records | no | `recheck.py`, each row | On a reachable final record, through `toRR`. Rows 1 and 2: verdict, reason and flight match. Rows 3 and 4: the reason only, and replay's flight is a number or none as the row says. Row 5: every replay rejects, reason not pinned. Says nothing when a device row is missing (Python raises `KeyError`). `V7_session` needs no key assumption. `V7_both_inj` rules out its reject case, and only it needs `Function.Injective e.pk`. |
| V8 | none | no check of its own, no named mutation | flight within 0.005 | `recheck.py` | Display rounding. |
| M1 | `M1_terminal`, `M1_edges` | yes, named mutations | yes | | `M1_edges` covers states only. "Other fields change only by a row" rests on reading, plus `Frame` and `Inv`. |
| M2 | `M2` | yes, named mutation | yes | | |
| M3 | `M3`, `M3_signed` | yes, named mutation | yes | | `M3_signed` needs `Unforgeable`. |
| M4 | `M4` | yes, no named mutation | yes | | |
| M5 | `M5_codes`, `M5_partner_code`, `M5_no_strings`, `M5_create_token` | yes, named mutations | sounds by name only | | The walk scans bodies and headers. `view_header_holds_seed` is caught as M5 by the header scan (and M6 by the allow-list). |
| M6 | `M6`, `M6_view_ignores` | yes, named mutations | yes | `recheck_m6_fail.py` | The walk checks headers against an allow-list too. `view_header_holds_partner_sig` is caught as M6. |
| M7 | `M7` | yes, named mutation | yes | | |
| M8 | `M8_retry_wipes`, `M8_pins`, `M8_stale_*`, `M8_old_commit_*`, `M8_keys`, `bed_msg_eq_iff` | yes, named mutations | yes | | `M8_keys` needs no collision among four messages. |
| M9 | `M9`, `M9_table`, `M9_confirmed` | yes, no named mutation | yes | | Takes only `Reachable`. |
| M10 | `M10_*` | yes, named mutation | yes | `recheck.py` | |
| M11 | `M11` | yes, named mutation | yes | `recheck.py` | One clock read per step in Lean. |
| M12 | `M12_*` | only through the table check, no named mutation | partly: no-auth load untested | `recheck.py` | Route list by reading. |
| M13 | `M13`, `M13_t0` | under M1's snapshot, no named mutation | yes | | |
| M14 | `M14`, `M14_any`, and `*_err_doc` per handler | yes, no named mutation | yes; 5 of 6 M14 rule changes caught, the sixth unreachable and allow-listed | spot cases | Any error leaves the stored doc as it was before the load (bad JSON, no auth, bad shape) or as the load left it. One exception: a `/transcript` from member `role` that answers 400 with reason `rsn` may store a NOT_NEAR `_finalize` of exactly one of two docs (`TxReject`): the loaded doc, blaming `role`, when the transcript check rejects (`sessions.py:438-440`), or the loaded doc with this transcript stored, blaming no role, when `combine` rejects (`:454-456`). Not pinned: that a 400 really finalizes (the unchanged case has no status limit), which reason `combine` gives, and when `M14_any`'s first case (the doc before the load) is allowed. |
| R1 | none, auth is not modeled | spot cases | no, status only | `recheck.py` | |
| D1 | none | no | no | reading only | |
| X1 | `X1_core`, `X1`, `X1_witness_v1`, `X1_witness_v2`, `X1_on_layout`, `Witness.reaches_near`, `X1_keys`, `X1_of_keys`, `X1_on_layout_keys`, `X1_session`, `X1_session_on_layout`, `X1_session_on_layout_edges` | no | no | `recheck.py`, v1 and v2 | Session result for every allowed pick, v1 and v2, on one fixed schedule, run from a given `create` at `T`, with the stored commits and transcripts pinned (`X1Reached`). Hypotheses `Powers` and `hsha` for all three; `hb64` for `X1_session` only. The docstrings now say what each statement pins, see gap 1. |
| X2 | `X2_abort`, `X2_abort_after_create`, `X2_fail_final`, `X2_fail_partner_mismatch`, `X2_fail_twice`, `X2_fail_needs`, `X2_bad_transcript`, `X2_tx_needs` | only through the table check, no named mutation | table rows only | `recheck.py` | Abort: a full step on a reachable doc. `/fail` and bad transcript: the handler on an arbitrary doc with state hypotheses, not shown reachable, with no load. `X2_bad_transcript`'s hypotheses are not shown to hold together on a reachable doc. |
| Guard at `sessions.py:454-456` | `combine_guard_unreachable`, `afterStore_accepted`, `combine_guard_on_request` | | | | Needs ids and keys one to one. |
| Guards of `/fail`, `arm`, `view` | `fail_ok_iff`, `fail_submitted_refused`, `fail_ok_attempt`, `fail_ok_reason`, `M10_no_fail_after_tx`, `arm_ok_rtt`, `arm_ok_rtt_range`, `arm_rate_matches`, `arm_other_rate_error`, `view_nonce_gate`, `view_nonce_hidden` | | yes, rule changes caught | | Mutants broke `fail_ok_iff`, `arm_ok_rtt`, `arm_rate_matches`, `view_nonce_gate`, `view_nonce_hidden` (`logs/lean-final-4.txt`). The others are proved, not separately mutation-tested. |
| E2 before E3, one transcript in | `Witness.E2_beats_E3_one_tx` | | | | The trace of the same name now gets a transcript in at 594301. |
| A2, A3, A9 | | | | reading only | Stay assumptions. |

## Assumptions

Full wording in `spec.md` section 2.

- **A1** honest server: the code runs as written. A cheating server can report anything.
- **A2** one uvicorn worker process. Nothing enforces it for a `uvicorn --factory` start.
- **A3** no await between load and save on the session routes.
- **A4** signatures can't be forged.
- **A5** SHA-256 and the 16-byte truncated `device_id` have no collisions.
- **A6** the seed is secret and the derivation hides it.
- **A7** the clock doesn't go back between requests.
- **A8** the store returns what was last saved.
- **A9** out-of-scope routes don't move the core fields of this kind of session.
- **A10** every save works. **False in the real code**, see E500-meta. That loses progress, not safety.

- **Powers**, **hsha**, **hb64**: what the signers can do, the hash gives 32 bytes, each byte string has a base64 spelling. `Powers` and `hsha` are hypotheses of `X1`, `X1_keys` and `X1_session`; `hb64` of `X1_session` only. Rows in `spec.md` section 2. They are not facts proved about `codec.py`, real SHA-256 or base64.

## Findings in the code

No wrong verdict was found. All are low severity and not fixed, per the rules of this work. Repros are in `spec.md` section 6. For the next version: [`../next-version-fixes.md`](../next-version-fixes.md).

| Id | Where, at 9db1490 | What happens |
| --- | --- | --- |
| R1-gap | `auth.py:45-46` | The replay cache keys on the signature string. Another spelling, or s flipped to n - s, counts as new. |
| R1-edge | `auth.py:36, 44` | A request with a ts 60 s ahead is accepted again at exactly + 120000 ms. |
| E500-ts | `auth.py:36` | A very long digit string in `X-Pop-Ts` gives 500, not 401. |
| E500-fail | `sessions.py:465` | `reason` as a list gives 500. |
| E500-join | `sessions.py:181` | A non-ASCII join token gives 500. |
| E500-create | `main.py:155-158` | A very deep body gives 500, nothing stored. |
| E500-meta | `sessions.py:441-444` | A very deep `meta` makes later saves raise. The partner gets 500s for up to about 600 s. A stall, not a verdict. |

Also known: code commit bytes are equal at rates 95999 and 96000 (a rule of the code, and `sample_rate` is checked on its own). Docstrings against code are listed in `spec.md` section 6, among them `verify_record`, which doesn't re-run "every check".

## Known gaps

Numbers are kept from the earlier list so old references still work. Closed gaps stay listed, with what closed them.

**From the reviews.**

1. **`X1` says less than its docstring. Closed, with the limit stated.** `X1` itself is unchanged: its conclusion pins halves, rates, recording values and versions, not keys, self deltas or `code_commit`. `X1_keys` (`ServerFv/X1Keys.lean`) has the same hypotheses and adds eight equalities: `pk_self`, `pk_partner`, `self_os_delta` and `code_commit`, for A and for B. `X1_of_keys` shows it implies `X1`'s conclusion. `X1_on_layout_keys` shows its hypotheses can hold, for v1 and v2, and now pins both recording values to all-zero too. The docstrings of `X1_core`, `X1`, `X1_on_layout` and `X1_session_on_layout(_edges)` now say what each statement pins, and that recording values, nonce and token there are what the proof feeds in, not what the statement says. Log: `logs/lean-final-4.txt`. **Limit:** the statement of `X1_on_layout` still doesn't pin recording values. For the session, `X1_session` now exposes the stored commits and transcripts (gap 4), and `X1_session_on_layout(_edges)` inherit that.
2. **The replay had a false pass. Closed in code.** `Replay.lean` now reads labels by kind (`wireLbl`, `sigLbl`, `hashLbl`), so a hash field holding a wire string is a mismatch. The three rule changes that put a wire string in a hash field and one that swaps the record's wire and signature, plus the tamper "txh holds the sig label", are all caught (`logs/replay-checks-5.txt`; the swap is caught at `after.result.tx.A`). A chunk review passed; no track re-review.
3. **Dropped fields. Disclosed, not compared.** Record `policy`, `human`, `pair_tag` and view `policy`, `human` are listed in `Replay.lean` and in `logs/replay-4.txt`, with the note that the trace is a projection on fixed key lists. Comparing them needs fields the model doesn't have. Deferred.

**From the critic.**

4. **`X1` as a session result. Closed on the model.** `X1_session` (`ServerFv/X1Session.lean`): for any setting, two devices with different enrolled keys, halves in the signed 32-bit range, rates in 36000..96000, v1 or v2 on each side, 32-byte recording values, and self deltas that pass, with -20 < exact flight < 60, `X1Reached` holds. That is: the nine requests it lists, run from the given `create` at `T` with the given `sid`, `nonce`, `seed` and `token`, end on a `done` document at `T + 4411` that is `Reachable` and keeps those values, whose record says NEAR, no reason, attempt 0, at the exact flight, with both device rows and the very commit and transcript strings sent. Each commit decodes to its role, attempt 0, `nonce`, `recA`/`recB` and version; each transcript to its recording value, half, self delta (`dlA`/`dlB`) and enrolled key; the doc's own rows store the same. Fixed 2026-11-09 after Codex found the old conclusion said none of this. `X1_session_on_layout` and `X1_session_on_layout_edges` show the hypotheses can hold, including both rate ends at once (halves 0 there, not the ends of the half range). Log: `logs/lean-x1-session.txt`, then `logs/lean-final-4.txt`. Limits: one fixed schedule; `Powers`, `hsha`, `hb64` and, for v2, a 32-byte `code_commit` are hypotheses; the layout's stand-in signatures have no security. The stored flight is the exact rational; Python stores `round(float(f), 2)` (`verdict.py:167`), so the two can differ past two decimals. The layout instances set `recA`, `recB` and the nonce all to the same all-zero value and both self deltas to 0, so as tests they can't show an A/B swap or the nonce standing in for a recording value (Codex, low; the theorem itself is for every pick).
5. **General Lean theorems for M14, X2 and V7. Mostly closed.** M14: `M14`, `M14_any`. Since 2026-11-09 the transcript exception is pinned by `TxReject`: the 400 stores a NOT_NEAR finalize of the loaded doc blaming the sender (bad transcript) or of the loaded doc with this transcript stored blaming no role (combine reject), nothing else. Still open (Codex, low to medium): the unchanged-doc case carries no status limit, so a handler answering 400 with a reason and skipping the finalize would also fit; the combine branch needs only a passing check, not that `combine` rejected with that reason; `M14_any` allows the doc from before the load after any error, without tying that to the pre-load failures. V7 on a reachable final record: `V7_session`, with rows 3 and 4 matching the reason only, and nothing said when a device row is missing. X2: `X2_abort` is a full step on a reachable doc. The `/fail` and bad-transcript theorems (`X2Fail.lean`) are about the handler on an arbitrary doc with state hypotheses: no load, no `Reachable`. That those hypotheses hold together on a reachable doc is not shown for `X2_bad_transcript`. **Still open:** D1 is reading only. R1 has no Lean model of auth.
6. **The link to Python is sampled.** Unchanged. Replay takes base64 acceptance, signature results and decoded fields from the trace, swaps auth for a label, and doesn't test `check_commit` or the no-auth load. The layout has four sample vectors. A2, A3, A9 are reading only.
7. **The walk's scans read only response bodies. Closed.** `test_walk.py` reads headers too: an allow-list of names, exact `content-type` and `content-length`, and the M5 and M6 string scans over header lines. The full walk on it passed, and both header mutations were caught (`logs/walk-final-3.txt`). Since 2026-11-09 `view_header_holds_partner_sig` must show the partner-sig scan's own failure line, so it is no longer caught by the allow-list alone. The v5 walk traces were written with the check on (`logs/replay-4.txt` header).
8. **`machine_all.sh` exited on the mutants' code only. Closed.** It now exits 1 if the build, any fresh check, the axiom scan, the word scan, the traces or the mutants fail. Since 2026-11-09 (Codex): a word scan that can't read a file fails, each set of extra files gets a control compile that must be clean, a mutant counts only if an error lands in an expected theorem, a filter that picks no mutant fails, and axiom lists Lean wraps over lines are read whole. `logs/machine-checks-negative.txt` shows four broken inputs each ending rc=1. `logs/lean-final-4.txt` ends with `overall rc=0`. Fixed 2026-11-09 after Codex round 2: the allow-list is a whole-line fixed-string match, so `ClassicalXchoice` fails; an empty argument, a name with spaces or a missing file fails the run before any check; the word scan allows leading whitespace before `axiom`, `unsafe` and `partial`; file names are kept in a quoted array, so none is globbed; every stage of the axiom-list pipelines is checked and the names read must cover every printed list; every grep in the per-file checks and the traces fails the run on a read error. `logs/lean-machine-checks-7.txt` shows the full run (34 of 34 mutants, `overall rc=0`) and four broken inputs ending rc=1: `""`, `ClassicalXchoice`, an injected failing grep in the name extraction, a file named `[M]achine.lean`. Still open (low): `owner()` in `machine_mutants.py` finds the nearest declaration above an error with no end-of-declaration check, so an error in a later `example` or namespace could count for an expected theorem. In the logged run `owner()` places every error in a theorem: the four mutants that broke more than their expected theorems broke other theorems, no `def`.
9. **`Powers` and hash width had no row in `spec.md`'s assumption table. Closed.** Rows `Powers`, `hsha` and `hb64` are in `spec.md` section 2.
10. **Walk mutations name no target for M4, M9, M12, M13, M14, V3, V6, V8.** Unchanged. Some are hit by accident. `minimize()` runs only when a walk fails, and no kept run shows it working.
11. **Run records are thin. Mostly closed.** `logs/walk-final-3.txt` records the sha256 of `test_walk.py`, `conftest.py` and the 33 server files. Since 2026-11-09 the Lean and replay logs do too: `lean-final-4.txt` (every `ServerFv` file, `checks/*`, lake files, `popfv` sources), `replay-4.txt` and `replay-checks-5.txt` (Lean files, scripts and traces). Older logs still rest on file times. Traces aren't kept in the repo. The 2026-11-09 review reports are kept in `reviews/`; reports from rounds 1 to 4 were not.
12. **`spec.md` section 5 is a history table. Closed.** Its stale opener now reads as history. The table above is the current list.

**Smaller ones.**

13. **Six guards survived one-place Lean mutants. Closed.** Each of the six mutants now breaks a proof (`logs/lean-final-4.txt`, 34 of 34): `fail_ok_iff` for the three `/fail` guards, `arm_ok_rtt`, `arm_rate_matches`, and `view_nonce_gate` with `view_nonce_hidden`. `fail_submitted_refused`, `fail_ok_attempt`, `fail_ok_reason`, `M10_no_fail_after_tx`, `arm_ok_rtt_range` and `arm_other_rate_error` are proved but appear in no mutant's break list. The same six rule changes are caught in replay.
14. **Mislabelled trace. Closed.** `E2 beats E3 with one tx` now commits at 594300 and gets its transcript in at 594301, then E2 aborts it at 620000. `machine_all.sh` checks both lines. `Witness.E2_beats_E3_one_tx` proves the same run.
15. **Thin replay coverage. Narrowed.** Directed cases now include a repeat with nonzero halves and one isolated v2 `delta` and v2 `code_commit` refusal each; the replay counts 17 repeat transcripts with a nonzero half (`logs/replay-4.txt`). A 401 code must now be one the auth label gives, and the host is read from the create's actor. Still open: every create in the traces is by phone A at time zero, so a host other than A is checked but never exercised. `combine`'s role guard has a model theorem (`combine_role_guard`) but is never exercised in replay. Both self checks failing is still only in directed cases.
16. **Replay counted id changes as sessions and allowed two creates. Closed.** A second good create in a session, or a session id that comes back within one trace file, is a mismatch. Tampers for both are caught (`logs/replay-checks-5.txt`).
17. Sound generation is shared by the trace writer and the server, so a generator bug would be on both sides.
18. The walk runs sessions one at a time with fresh phones, so effects across sessions and one device in two sessions aren't tried.
19. **Spec wording. Closed.** `spec.md` now says: `/fail partner_mismatch` needs only both confirmed, no arm or commit, and is final at once (X2 table and C18, which still holds); an older commit is 400 `transcript_mismatch` with no stale check (M8); the long poll reloads and can fire E1 to E3 within one view request (view row).
20. A float `cal_us` in a JSON record is truncated by `int()` at `verdict.py:69`. Live values are ints.
21. **One replay rule change survived. Closed by an allow-list.** "M14 afterStore internal keeps new doc" changes a branch no step reaches. `replay_checks.py` now lists it as unreachable, prints it as allowed, and exits 0; any other survivor fails the run. The Lean mutant run catches it.
22. **The replay dropped a recording value's length, and `?` matched `?`. Closed in code, 2026-11-09 (Codex D1, D2).** The walk and `Replay.lean` now keep a recording value as `[length in bytes, value]`, so a 33-byte value with a leading 00 no longer equals the 32-byte one. `?`, for a value of the wrong kind or an unknown Python value, never equals anything; in the walk any `?` in the stored-doc projection fails M1. Caught: walk mutation `stored_rec_33_bytes` (`logs/walk-final-3.txt`), tampers "rec of 33 bytes, leading 00" and "'?' vs '?' at every rec" (`logs/replay-checks-5.txt`). The baseline showing the old `cmp` miss was not run. Since 2026-11-09 `replay_checks.py` exits 1 when `REPLAY_ONLY` matches no tamper and no mutant (run by hand, rc=1, no log), passes trace paths as lists with no shell, and rejects a trace path that is not a regular file or starts with `-`. Full rerun: `logs/replay-checks-5.txt`, same counts, rc 0.

## What is not done

- Nothing was rerun against code newer than `9db1490`.
- No track re-review after the fixes to `Verdict.lean`, `test_walk.py`, `Chain.lean` and the circuit docs, after the `Replay.lean` changes, or of this doc pass. The 2026-11-09 Codex re-reviews covered only the M14, `X1_session`, checker and replay/walk fixes.
- The low items Codex left open on 2026-11-09 are not fixed: M14 status limit and `M14_any` (gap 5), the layout instances' symmetry (gap 4), `owner()` (gap 8). The checker allow-list, empty argument and empty `REPLAY_ONLY` are fixed (gaps 8, 22), not re-reviewed.
- The clean-clone steps above were not run as written.
- uvicorn was not run, only FastAPI's test client. No race was tried, and no phone ran.
- No proof links the Lean table to the Python. Only sampled replay does.
- The three known 500s, the R1-edge millisecond and the long poll's sleep aren't generated by the walk.
- `Err.internal` is never hit in the replay. A create by a phone other than A, or later than time zero, never happens in the traces.
- DSP and the air are out of scope. Nothing here narrows CN1.
