# Server FV: does the server follow its rules?

Yes, on signed numbers. A hand-written Lean copy of the rules is proved, a random walk drives the real routes, and a replay checks that the two agree.

It does not show that a phone told the truth about the room (CN1). Two signers can reach NEAR with numbers they made up, and `X1` / `X1_session` prove exactly that. A NEAR means two keys signed two numbers that fit a range. That's not a proof of proximity.

Some last reviews failed, and their fixes weren't reviewed again. So don't call any of this verified. See [Reviews](#reviews).

**Scope.** Plain sessions only: `context=None`, `early_nonce=False`. Not covered: contexts, zk routes, device statements, recording upload, enrolment, DSP. The walk checks the signed presence copy in the record, and nothing else here does.

**Which code.** The `server/` in the same checkout. Line numbers in these docs are for 5863e9c. They're only pointers. Rerun the checks after any change to `server/pop/`, since nothing does it for you.

**Files.** `spec.md` has the rules and properties. `lean/ServerFv/` has the proofs and the replay. `tests/test_walk.py` is the walk. `reviews/` has the kept review reports. Runs write to `logs/`, which git ignores.

## Run it

You need Python 3.12 with the server's deps, and `elan` for Lean.

```bash
cd server && uv sync --group dev --python 3.12 && cd ..
PY=$PWD/server/.venv/bin/python fv/v1/server/run_all.sh     # or: python | lean
```

- `python` runs the spec rechecks and the walk (1000 sessions, seed 20261106), then makes four traces.
- `lean` builds, rechecks `Verdict.lean`, compares the byte layout, and runs `machine_all.sh` with its 34 mutants.
- `all` does both, then the replay and `replay_checks.py`.

Traces are seeded, so each run makes them fresh and nothing is stored. Exit code 0 means every step passed. A full run takes about 50 minutes on a big Linux machine, and longer on a laptop. Delete scratch `.lean` files in `ServerFv/` first, or `machine_all.sh` picks them up and fails.

## Results

Last full run 2026-11-09, on 5863e9c plus the issue #43 edits, Python 3.12.3. Every step passed.

| Step | Result |
| --- | --- |
| `recheck.py` | 192 pass |
| `recheck_m6_fail.py` | 17 pass |
| Walk | 62 passed, every one of the 45 mutations caught by the property it targets |
| Traces | 3 seeds of 2000 sessions plus 32 directed cases |
| `lake build` | 18241 jobs, no `sorry`, standard axioms only |
| Layout vectors | 4 of 4 match `codec.py` |
| `machine_all.sh` | 27 files clean, 34 of 34 mutants break a proof |
| Replay | 6032 sessions, 83329 steps, 0 mismatches, all 35 coverage targets hit |
| `replay_checks.py` | 67 of 67 tampers caught. 103 of 104 rule changes caught, and the last one can't be reached (gap 21). |

These are runs, not reviews. The Lean-to-Python link is sampled, never proved.

## What changed since 9db1490

Until issue #43 all this was pinned to 9db1490. Five later commits changed `server/pop/`. Inside the scope:

- **create** ignores `policy` now, so `bad_policy` is gone. `early_nonce` must be a boolean.
- **The document, record and view** lost `policy`, `human` and `pair_tag`.
- **The record** gained `presence`, a signed copy of part of the record plus both device rows. The walk rebuilds it and checks the signature. Lean and the replay leave it out, because its signature is random and can't go in a seeded trace.
- **arm** lost the World ID guard, which could never fire here anyway.
- **`/relay` is gone.** `/zk/bundle` is now the only route that loads a session without auth.
- **Web devices** can calibrate up to 150000 µs, and `self_os_can_pass` covers that.

No rule in `Machine.step` or `verdict.py` changed.

## Reviews

Early rounds were Claude Opus agents. From 2026-11-09 on, Codex (gpt-6-astra) reviews read-only, and Opus fixes and checks each claim. No reports from before 2026-11-09 were kept, so those verdicts come from run notes. Codex reports are in [`reviews/2026-11-09-codex.md`](reviews/2026-11-09-codex.md).

| What | Last verdict | Open after the fixes |
| --- | --- | --- |
| `spec.md` | pass | Two nits fixed, not re-reviewed |
| `Machine.lean` | pass | none |
| `Verdict.lean` | **fail**: docstrings claimed more than the statements | Fixed, **not re-reviewed** |
| `test_walk.py` | **fail**: run records didn't match | Fixed. The newer walk changes passed Codex. |
| `Replay.lean` | **fail**: a false pass, labels of one kind | Fixed, chunk reviews passed, **no full re-review** |
| Circuit `Commit`, `Chain` | **fail**: wording only, no proof defect | Fixed, not re-reviewed |
| Whole work, critic | pass | none |
| Codex 2026-11-09: M14, `X1_session`, checkers, replay, walk | pass after fixes | low items in gaps 4, 5 and 8 |
| Docs | Codex first pass only | Fixed, not re-reviewed |

## Each property

"Lean" means proved on the hand-written model under named hypotheses. "Walk" means checked after every step of the real routes. "Named mutation" means a weakened server got caught for that property. Walk and replay are testing, not proof.

| Id | Lean | Walk | Replay | Note |
| --- | --- | --- | --- | --- |
| V1 | `V1`, `combine_role_guard`, `combine_ok_roles` | named mutation | role guard never hit | |
| V2 | `V2` | yes | via `combine` | Over rationals. NaN would give NEAR, and no caller passes NaN. |
| V3 | `V3` and four more | yes | via `combine` | Bridges to `Pair.distance_iff`. |
| V4 | `V4`, `V4_cal`, `V4_edges` | named mutation | via `combine` | |
| V5 | `V5_*` | named mutation | no | One lemma takes "A never signed these bytes" as a premise. |
| V6 | `V6`, `V6_free` | no | partly | |
| V7 | `V7_session` and more | on direct records | no | Rows 3 and 4 match the reason only. Says nothing if a device row is missing. |
| V8 | none | no | flight within 0.005 | Display rounding. |
| M1 | `M1_terminal`, `M1_edges` | named mutations | yes | `M1_edges` covers states only. |
| M2 | `M2` | named mutation | yes | |
| M3 | `M3`, `M3_signed` | named mutation | yes | `M3_signed` needs `Unforgeable`. |
| M4 | `M4` | yes | yes | |
| M5 | `M5_*` | named mutations | sounds by name | The walk scans bodies and headers. |
| M6 | `M6`, `M6_view_ignores` | named mutations | yes | |
| M7 | `M7` | named mutation | yes | |
| M8 | `M8_*`, `bed_msg_eq_iff` | named mutations | yes | `M8_keys` needs no collision among four messages. |
| M9 | `M9`, `M9_table`, `M9_confirmed` | yes | yes | |
| M10 | `M10_*` | named mutation | yes | |
| M11 | `M11` | named mutation | yes | Lean reads the clock once per step. |
| M12 | `M12_*` | table check only | no-auth load untested | |
| M13 | `M13`, `M13_t0` | under M1 | yes | |
| M14 | `M14`, `M14_any`, `*_err_doc` | yes | 5 of 6 rule changes, the sixth unreachable | An error leaves the doc as it was, except a rejected `/transcript`, which may store one of two NOT_NEAR docs (`TxReject`). Gap 5 lists what's still loose. |
| R1 | none, auth isn't modeled | spot cases | status only | |
| D1 | none | no | no | Reading only. |
| X1 | `X1`, `X1_keys`, `X1_session` and more | no | no | Any allowed pick of numbers reaches NEAR, on one fixed schedule. |
| X2 | `X2_*` | table check only | table rows | `/fail` and bad-transcript lemmas are about the handler on any doc, not shown reachable. |
| Guards of `/fail`, `arm`, `view` | `fail_ok_iff`, `arm_ok_rtt`, `view_nonce_gate` and more | | yes | Mutants break five of them. The rest are proved but not mutation-tested. |

## Assumptions

Full wording is in `spec.md` section 2.

- **A1.** The server is honest. A cheating server can report anything.
- **A2.** It runs as one worker process. Nothing enforces that.
- **A3.** No await between load and save.
- **A4.** Signatures can't be forged.
- **A5.** SHA-256 and the 16-byte `device_id` don't collide.
- **A6.** The seed stays secret.
- **A7.** The clock doesn't go back.
- **A8.** The store returns what was last saved.
- **A9.** Out-of-scope routes don't touch the core fields.
- **A10.** Every save works. **That's false in the real code** (E500-meta). It loses progress, not safety.
- **`Powers`, `hsha`, `hb64`** are hypotheses about what signers can do, hash width, and base64. They aren't proved about the real code.

## Bugs found

No wrong verdict. All low severity, not fixed. Repros are in `spec.md` section 6, and fixes for the next version are in [`../next-version-fixes.md`](../next-version-fixes.md).

| Id | Where | What happens |
| --- | --- | --- |
| R1-gap | `auth.py:45-46` | The replay cache keys on the signature string, so another spelling of the same signature counts as new. |
| R1-edge | `auth.py:36, 44` | A request stamped 60 s ahead is accepted again at exactly +120000 ms. |
| E500-ts | `auth.py:36` | A huge `X-Pop-Ts` gives 500, not 401. |
| E500-fail | `sessions.py:468` | A list as `reason` gives 500. |
| E500-join | `sessions.py:182` | A non-ASCII join token gives 500. |
| E500-create | `main.py:138-141` | A very deep body gives 500, and nothing is stored. |
| E500-meta | `sessions.py:444-447` | A very deep `meta` breaks later saves. The partner gets 500s for up to about 600 s. It stalls the session but never changes a verdict. |

## Known gaps

The numbers are kept so references from the Lean files still work.

1. **Closed.** `X1` pins less than its docstring once said. The docstrings now say what each statement pins, and `X1_keys` adds the keys, deltas and `code_commit`.
2. **Closed.** The replay had a false pass. Labels are now read by kind, and the tampers for it are caught.
3. **Open, deferred.** The replay doesn't compare record `context`, `zk`, `presence` or view `context`. They're listed in `Replay.lean`.
4. **Closed on the model.** `X1_session`: any allowed pick ends on a reachable `done` doc that says NEAR and stores the exact strings that were sent. Limits: one fixed schedule, the hypotheses `Powers`/`hsha`/`hb64`, and Lean stores the exact flight where Python rounds to 2 decimals. The layout examples use all-zero values, so they can't show an A/B swap.
5. **Mostly closed.** `M14`, `M14_any`, `TxReject`, `V7_session`, `X2_*`. Still loose: the unchanged-doc case allows any status, the combine branch doesn't pin the reason, and `M14_any`'s "doc before load" case is unconditional. X2's `/fail` lemmas aren't on reachable docs. D1 is reading only, and R1 has no model.
6. **Open.** The Lean-to-Python link is sampled. The replay takes base64, signature and decoder results from the trace, and the layout has four sample vectors.
7. **Closed.** The walk scans headers too, not just bodies.
8. **Closed.** `machine_all.sh` now fails on any failed step, read error, empty filter, or bad argument. Still open (low): `owner()` in `machine_mutants.py` doesn't find where a declaration ends.
9. **Closed.** `Powers`, `hsha` and `hb64` have rows in `spec.md`.
10. **Open.** No walk mutation targets M4, M9, M12, M13, M14, V3, V6 or V8, and no run has shown `minimize()` working.
11. **Closed by removal.** Logs aren't kept anymore. `run_all.sh` prints the commit it ran on. The old logs are in git at 5863e9c.
12. **Closed.** `spec.md` section 5 is marked as history.
13. **Closed.** All six guards that used to survive mutants now break a proof.
14. **Closed.** The mislabelled trace `E2 beats E3 with one tx` is fixed and proved.
15. **Narrowed.** The directed cases cover more now. But every create in the traces is by phone A at time zero, and `combine`'s role guard is never hit.
16. **Closed.** A second create, or a reused session id, is now a replay mismatch.
17. **Open.** The trace writer and the server share the sound generator, so a generator bug would show up on both sides.
18. **Open.** Sessions run one at a time with fresh phones. Nothing tries one device in two sessions.
19. **Closed.** Spec wording for `/fail partner_mismatch`, old commits and the long poll.
20. **Open.** A float `cal_us` in a JSON record gets truncated by `int()`. Live values are ints.
21. **Closed by allow-list.** One replay rule change survives because no step can reach it. Lean mutants catch it.
22. **Closed.** The replay now keeps a recording value's length, and `?` never equals `?`.

## Not done

- Nothing reruns the checks by itself. After a server change, run `run_all.sh` by hand.
- No full re-review after the fixes to `Verdict.lean`, `test_walk.py`, `Chain.lean` and `Replay.lean`, or of the docs.
- Codex's low items are still open: gaps 4, 5 and 8.
- No uvicorn, no race, no phone. Only FastAPI's test client.
- The walk doesn't generate the three known 500s, the R1-edge millisecond, or the long poll's sleep.
- DSP and the room are out of scope. Nothing here narrows CN1.
