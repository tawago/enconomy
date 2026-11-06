# Server side: does the server follow its rules?

**What this shows.** The server follows its rules on signed numbers. That covers the basic proximity flow, on a hand-written Lean copy of the rules, on a walk over the real routes, and on a replay that compares the two.

**What this does not show.** It does not show a phone told the truth about the air (CN1). A phone can still sign a false half, and theorem `X1` says so: two signers can reach NEAR with numbers they picked, and nothing in the verdict reads sound. A NEAR means two keys signed two numbers that fit a range. It is not a proof of proximity.

**Read this before quoting anything.** Every review track ended on a **fail**. Some of those fails were fixed afterwards and not reviewed again. Some were not fixed. See [Review verdicts](#review-verdicts) and [Known gaps](#known-gaps). Nothing here should be called verified.

**Scope.** Sessions with `context=None` and policy `human=none` only. No claim about World ID, Safe, attestation, ENS, the bridge, zk routes, recording upload, enrolment attestation parsing or DSP.

**Pinned code.** This work is pinned to `main` at commit `9db1490`. Later commits changed `server/pop/sessions.py`, `main.py`, `constants.py` and 12 other files under `server/pop/` (`git diff --stat 9db1490 HEAD -- server/pop`). **Nothing has been rerun against them.** Line numbers in these files are for `9db1490`.

Files: [`spec.md`](spec.md) has the rules and properties. `lean/ServerFv/` has the proofs and the replay. `tests/test_walk.py` is the walk. `logs/` holds the runs cited here.

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
lake env lean ServerFv/Machine.lean
```

Expected: `Build completed successfully (18189 jobs).` The count can differ on another machine. Axiom lines: Machine 56, Verdict 29, all within `propext`, `Classical.choice`, `Quot.sound`. Any `sorryAx` means a broken proof. Log: `logs/lean-final.txt`.

```bash
bash checks/machine_all.sh     # build, fresh check, axiom scan, traces, 21 mutants, about 2 min
```

Expected: `fresh rc=0`, `traces rc=0`, `mutants total 21 survived 0 bad pattern 0`. Log: `logs/lean-machine-checks-2.txt`. **Read those lines. Its exit code only follows the mutants** (see Known gaps).

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

Expected: `59 passed`, about 13 min. Log: `logs/walk-final.txt`. Fewer sessions can fail on coverage only: 500 sessions missed two targets (`logs/walk-final-500.txt`).

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
python3 checks/replay_checks.py $T/walk-20261106.jsonl 12000 $T/directed.jsonl     # about 8 min
```

Expected: 6016 sessions, 94075 lines, 83169 steps, 0 mismatches, rc=0, then 60 of 60 tampers and 87 of 87 rule changes caught. Logs: `logs/replay.txt`, `logs/replay-checks.txt`, `logs/replay-exit-codes.txt`. The `replay_checks.py` arguments above are rebuilt from the log's description and were not copied from a saved command.

The same seed should give the same trace bytes. So compare your trace sha256 with `logs/replay.txt`. If they match, this `test_walk.py` makes those traces. That has not been tried on another machine.

## What ran on which file

**The final walk ran 1000 sessions**, as the first line of `logs/walk-final.txt` says: seed 20261106, 59 passed, rc=0. It is the only full walk log for the current test file (sha256 `02243d66...` before the comment edit below).

**Older 2000-session runs were on an earlier version of the test.** `logs/walk.txt` has 28 tests and predates the current file. Another 2000-session run of 59 tests also predates the last edit, and no log of it was kept. A later 2000-session run made the traces: 59 passed, then seeds 7001 and 7002 with the walk test alone, 1 passed each. Only the tails are kept (`logs/replay-exit-codes.txt`), and no file hash was recorded. By file time it ran after the last edit. The trace check above would settle that.

**Files edited after the final runs.** To take private run details out for this public repo, comment and docstring lines changed in `test_walk.py`, `recheck.py`, `recheck_m6_fail.py`, `Replay.lean`, `lakefile.toml` and all four scripts in `lean/checks/`. **No check ran after that.** So hashes in the logs are of the files before the edit. `logs/post-run-edits.txt` lists each file with lines changed and both hashes. `Machine.lean` and `Verdict.lean` did not change.

In the logs, paths, job ids and upload lines came out, and short notes were added. Results were not changed. `replay_checks.py` also last ran before a one-line comment edit in `Replay.lean`.

## Review verdicts

Reviews marked Opus were by Claude Opus agents. The trace reviews and the critic were judged by **Codex (gpt-6-astra)**, with Opus running the jobs and feeding it the output.

| Track | Reviewer | Rounds | Last verdict | Why | What happened after |
| --- | --- | --- | --- | --- | --- |
| `spec.md` | Opus | 3 | **fail** | M6 report table was false: a `/fail` gives the same report as `combine`. Create row missed a 500. | Fixed. New script: 17 pass, 0 fail. No re-review. Three smaller notes left (see gaps). |
| `test_walk.py` | Opus | 3 | **fail** | Review didn't finish: it saw none of its jobs end, so its own extra mutations stay unconfirmed. | Final walk ran after: 59 passed. No re-review. The overclaim it raised, "every byte", is still there. |
| `Verdict.lean` | Opus | 3 | **fail** | `X1`'s docstring claims more than `X1` states. | Docstring now says what the statement pins. The statement isn't strengthened. A copy proved with the fix. |
| `Machine.lean` | Opus | 3 | **fail** | Two doc claims: who needs one-to-one keys, and `M8_keys`'s hash hypothesis. | Fixed, rebuilt, 21 of 21 mutants broke. `M8_keys` narrowed. No re-review. |
| `Replay.lean` | Codex, Opus ran jobs | 3 | **fail** | A false pass: one label kind for wire, signature and hash. Some dropped fields undisclosed. | **Not fixed.** Disclosed here and at the top of `logs/replay.txt`. |
| Whole work, critic | Codex, Opus read files, ran nothing | 1 | **fail** | Real gaps remain, no new wrong-verdict bug. | **Not fixed.** Listed below. |

A final `lake build` and final walk ran after these. They are runs, not reviews.

## Each property

"Lean" means proved on the hand-written model, under named hypotheses, with no `sorry`. "Walk" means checked after every step on sampled runs of the real routes; "named mutation" means a weakened server was caught for that property in `logs/walk-final.txt`. "Replay" means the Lean table agreed with Python on sampled traces, on the compared fields. Those two are testing, not proof. The Lean-to-Python link is never a proof.

The last review of every track failed, so read the status column together with the table above.

| Id | Lean theorem | Walk | Replay | Reading or spot run | Note |
| --- | --- | --- | --- | --- | --- |
| V1 | `V1` | yes, named mutation | partly: role guard never exercised | `recheck.py` | |
| V2 | `V2` | yes | through `combine` | `recheck.py` | Over rationals. NaN gives NEAR, no caller passes it. |
| V3 | `V3`, `V3_ties`, `V3_circuit`, `V3_near_gives_range`, `V3_range_does_not_give_near` | yes, no named mutation | through `combine` | `recheck.py` | Bridges to `Pair.distance_iff`. |
| V4 | `V4`, `V4_cal`, `V4_edges` | yes, named mutation | through `combine` | `recheck.py` | |
| V5 | `V5_combine_swapped`, `V5_record_swapped`, `V5_record_swapped_mixed_versions`, `V5_record_all_swapped`, `V5_live_other_role` | yes, named mutation | no | `recheck.py` | `V5_record` takes "A never signed these bytes" as an input premise. |
| V6 | `V6`, `V6_free` | no check of its own, no named mutation | partly | `recheck.py` | Decoded fields and signature bits are recorded facts in the replay. |
| V7 | **none on a reachable final record** | yes, on direct records | no | `recheck.py`, each row | Pieces only. `verify_record` is not in `Machine.step`. |
| V8 | none | no check of its own, no named mutation | flight within 0.005 | `recheck.py` | Display rounding. |
| M1 | `M1_terminal`, `M1_edges` | yes, named mutations | yes | | `M1_edges` covers states only. "Other fields change only by a row" rests on reading, plus `Frame` and `Inv`. |
| M2 | `M2` | yes, named mutation | yes | | |
| M3 | `M3`, `M3_signed` | yes, named mutation | yes | | `M3_signed` needs `Unforgeable`. |
| M4 | `M4` | yes, no named mutation | yes | | |
| M5 | `M5_codes`, `M5_partner_code`, `M5_no_strings`, `M5_create_token` | yes, named mutations | sounds by name only | | Scan reads response bodies only. |
| M6 | `M6`, `M6_view_ignores` | yes, named mutations | yes | `recheck_m6_fail.py` | Scan reads response bodies only. |
| M7 | `M7` | yes, named mutation | yes | | |
| M8 | `M8_retry_wipes`, `M8_pins`, `M8_stale_*`, `M8_old_commit_*`, `M8_keys`, `bed_msg_eq_iff` | yes, named mutations | yes | | `M8_keys` needs no collision among four messages. |
| M9 | `M9`, `M9_table`, `M9_confirmed` | yes, no named mutation | yes | | Takes only `Reachable`. |
| M10 | `M10_*` | yes, named mutation | yes | `recheck.py` | |
| M11 | `M11` | yes, named mutation | yes | `recheck.py` | One clock read per step in Lean. |
| M12 | `M12_*` | only through the table check, no named mutation | partly: no-auth load untested | `recheck.py` | Route list by reading. |
| M13 | `M13`, `M13_t0` | under M1's snapshot, no named mutation | yes | | |
| M14 | **none general** | yes, no named mutation | yes | spot cases | Fragments only. |
| R1 | none, auth is not modeled | spot cases | no, status only | `recheck.py` | |
| D1 | none | no | no | reading only | |
| X1 | `X1_core`, `X1`, `X1_witness_v1`, `X1_witness_v2`, `X1_on_layout`, `Witness.reaches_near` | no | no | `recheck.py`, v1 and v2 | **Overclaims, see gaps.** The session result is one concrete v1 run only. |
| X2 | **none general** | only through the table check, no named mutation | table rows only | `recheck.py` | |
| Guard at `sessions.py:454-456` | `combine_guard_unreachable`, `afterStore_accepted`, `combine_guard_on_request` | | | | Needs ids and keys one to one. |
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

Also in the Lean theorems, and not in that table: `Powers` (what the signers can do) and `hsha` (the hash gives 32 bytes), both hypotheses of `X1`. They are not facts proved about `codec.py` or real SHA-256.

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

**From the last reviews, still open.**

1. **`X1` says less than its docstring.** Its conclusion pins halves, rates, recording values and versions, but not keys, self deltas or `code_commit`. So "two signers holding their enrolled keys" is not what it states. The fix is six equalities and a rebuild. A copy proved with them, before the witness section, so `X1_on_layout` still needs the same update.
2. **The replay has a false pass.** `Replay.lean` gives wire, signature and hash values one label kind. Changing the record's transcript hash to hold the transcript string passes all four traces. It doesn't change a verdict, since `verify_record` doesn't read that field. It is a checker defect.
3. **Dropped fields the replay's header doesn't list:** record `policy`, `human`, `pair_tag`, and view `policy`, `human`. The trace's projection also discards unexpected extra Python keys before the strict compare. So "the whole record" in the log means the compared part.

**From the critic.**

4. **`X1` as a session result is missing.** `spec.md` asks for it over all allowed halves and rates, v1 and v2. Lean has the verdict theorem plus one concrete v1 run at 48000.
5. **No general Lean theorem for M14, X2, or V7 on a reachable final record.** D1 is reading only. R1 has no Lean model of auth.
6. **The link to Python is sampled.** Replay takes base64 acceptance, signature results and decoded fields from the trace, swaps auth for a label, and doesn't test `check_commit` or the no-auth load. The layout has four sample vectors. A2, A3, A9 are reading only.
7. **`scan_response` says "every byte of every response" but reads only the body.** It's a checker gap, not evidence of a leak.
8. **`machine_all.sh` exits on the mutants' code only.** A failed fresh check or trace run still gives rc 0. Kept logs show those steps passed, so read the step lines.
9. **`Powers` and hash width have no row in `spec.md`'s assumption table.** They are listed above instead.
10. **Walk mutations name no target for M4, M9, M12, M13, M14, V3, V6, V8.** Some are hit by accident. `minimize()` runs only when a walk fails, and no kept run shows it working.
11. **Run records are thin.** The full 2000-session output isn't kept, only tails. Traces aren't kept. Hashes for Python files other than `sessions.py`, `verdict.py` and `main.py` aren't recorded.
12. **`spec.md` section 5 is a history table.** It now says so. The table above is the current list.

**Smaller ones.**

13. Six guards survive one-place Lean mutants, so only reading and traces hold them: `fail`'s `already_submitted`, attempt check and `PHONE_REASONS`, `arm`'s rtt range and re-arm at another rate, `view`'s nonce gate. No M row asks for them. `fail`'s `already_submitted` is the one worth a theorem.
14. The trace `E2 beats E3 with one tx` in `checks/machine_traces.lean` is mislabelled: no transcript gets in.
15. Thin replay coverage: 1 repeat with a nonzero half, both self checks failing only in directed cases, 3 each of isolated v2 refusals. `combine`'s role guard is never exercised. Any `auth_` code passes. Every create is by phone A at time zero.
16. Replay counts id changes as sessions, and doesn't enforce one create per session. The real traces are clean.
17. Sound generation is shared by the trace writer and the server, so a generator bug would be on both sides.
18. The walk runs sessions one at a time with fresh phones, so effects across sessions and one device in two sessions aren't tried.
19. Spec wording left as is: a cheaper one-sided end through `/fail partner_mismatch` with no commit (C18 still holds), M8's wording on older commits, and the view row on the long poll's extra loads.
20. A float `cal_us` in a JSON record is truncated by `int()` at `verdict.py:69`. Live values are ints.

## What is not done

- Nothing was rerun against code newer than `9db1490`.
- No re-review after the last fixes on any track.
- The clean-clone steps above were not run as written.
- uvicorn was not run, only FastAPI's test client. No race was tried, and no phone ran.
- No proof links the Lean table to the Python. Only sampled replay does.
- The three known 500s, the R1-edge millisecond and the long poll's sleep aren't generated by the walk.
- `Err.internal` is never hit in the replay.
- DSP and the air are out of scope. Nothing here narrows CN1.
