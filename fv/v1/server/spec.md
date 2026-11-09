# Server spec: the proximity core

Step 2 of [`docs/01-primer.md`](../docs/01-primer.md), for the server. Informal rules: [`informal-spec.md`](../informal-spec.md) Part 1 (ids C1.., CP1..5, CN1..7).

Line numbers are for `server/pop/` at 5863e9c. They are only pointers: every check (`run_all.sh`) runs on the `server/` in the same checkout, so a behaviour change shows up as a failing run, while a line number can go stale without one. `informal-spec.md` Part 1 was written against an older commit, 53604e3. Paths without a folder are in `server/pop/`, except `Pair.lean`, which is `fv/v1/zkp/popfv/Popfv/Pair.lean`.

Runs cited here come from [`spec-checks/recheck.py`](spec-checks/recheck.py); `run_all.sh` runs it. Log lines are named by their id, like `T-create`. That script drives the real server through its HTTP routes, with a fake clock and throwaway keys. It uses FastAPI's test client. uvicorn itself was not run. A second script does the same for the `/fail` report cases of M6 and for E500-create: [`tests/recheck_m6_fail.py`](tests/recheck_m6_fail.py).

## 1. What this covers

**In plain words.** Two phones each send the server a signed number, the half. The server turns the two numbers into a verdict. This spec pins down the rules the server follows while doing that: who may do what, in what order, what each phone gets to see, and how the verdict comes out of the numbers.

**It says nothing about the air.** These results show the server follows its rules on signed numbers. They do not show a phone told the truth about the air (CN1). A NEAR means two keys signed two numbers that fit a range. It does not mean two phones were close. Property X1 states this as a target to prove, not as a footnote. Do not read anything here as "proven proximity".

**Covered:**

- `verdict.py`: `decide`, `flight_exact`, `self_os_ok`, `check_commit`, `check_transcript`, `combine`, `verify_record`.
- `codec.py`: the field list and field ranges. Not byte parsing proofs.
- `constants.py`.
- `sessions.py`: `create`, `join`, `confirm`, `abort`, `arm`, `commit`, `next_attempt`, `transcript`, `fail`, `_expire`, `_failed`, `_finalize`, `_record`, `view`.
- `main.py` session routes, for auth, membership and load-before-handler only.
- `auth.py`.
- `jbl250.bed_key`, the derivation only.

**Modeled with `context=None` and `early_nonce=False`.** Every statement below is about such a session.

**Not covered, no claim made:** sessions with a context (`popctx.py`) or with `early_nonce`, zk proof routes, the presence signature beyond the walk's check of the record copy (`presence.py`), device statements, recording upload, enrolment and its attestation parsing, DSP. World ID, Safe, chain attestation and ENS left the core for `examples/` and are not in `server/pop/` any more.

Those out-of-scope routes share the session document, so section 2 says why they can be set aside (assumption A9).

## 2. Assumptions

Named, so a reader can reject any of them.

| Id | Assumption | Where it shows up | Used by |
| --- | --- | --- | --- |
| A1 | **Honest server.** The code runs as written. A cheating server can report anything (`informal-spec.md`, "Who is trusted"). | all | all |
| A2 | **One uvicorn worker process.** | `__main__.py:27` passes no `workers`. `server/README.md:68` asks for one. Nothing enforces it for a `uvicorn --factory` start. | M1 to M3, M5 to M14: each handler must see the latest stored document. R1: the replay cache is per process (`auth.py:26`). |
| A3 | **No await between load and save on the session routes.** Each handler is one uninterrupted step. Read and confirmed for confirm, arm, commit, transcript, fail, abort (`main.py:480-484, 487-510, 707-711`) and join (`main.py:465-468`). The body and the auth dependency are awaited before the load (`main.py:287-291`). The long poll awaits, but it loads again after each sleep and doesn't save a stale copy (`main.py:474-478`). | | M1 to M3, M5 to M14: each handler must be one uninterrupted step. |
| A4 | **Signatures can't be forged.** P-256 ECDSA. A second valid signature on a message already signed is not a forgery: low-s is not required (`crypto.py:32`), so anyone can flip s to n - s. | `crypto.py:31-42` | M3, M5, M10 |
| A5 | **SHA-256 has no collisions, and neither does the 16-byte truncated `device_id`.** So one `device_id` means one public key, and a re-enrol (`store.py:85`, `main.py:403`, `main.py:449`) can't change the key behind an id. That keeps "enrolled key of that role" stable, since `_pk`, `_record` and `view` read the device row when they run. | `crypto.py:12-13`, `main.py:347-349`, `sessions.py:332-334` | M3, M8 (`M8_keys`: four bed keys, see M8), the guard at `sessions.py:457-459` |
| A6 | **The seed is secret and the derivation hides it.** 32 random bytes (`sessions.py:155`). One phone's code tells it nothing about the seed or about the other role's key. Without this a phone could compute the partner's code from its own, and M5 would say nothing. | `jbl250.py:41-47`, `sessions.py:209-210` | M5, M8 |
| A7 | **The clock is one number that doesn't go back between requests.** `wall_ms` is `time.time_ns` (`main.py:80-81`), so a step backward on the machine would break this. | `sessions.py:97` | M5, M11, R1 |
| A8 | **The store returns what was last saved.** `get_session` builds a fresh copy from JSON each time (`store.py:87-90`). So edits made in memory and never saved are gone at the end of the request. | `store.py:82-94` | The whole model: M1 to M3, M5 to M14. M14 leans on it most. |
| A9 | **Out-of-scope routes don't move the core fields, for this kind of session.** Recording writes files and doesn't save the document (`sessions.py:489-516`). The zk routes only work after NEAR (`sessions.py:606-607`). They only write `s["zk"]`, `result["zk"]` and `result["presence"]`, and their save moves `seq` and `updated_ms` (`sessions.py:107-108, 572-575, 649-652`). These can happen on this kind of session. So M1 and M2 leave those four fields out. All by reading. | | M1, M2 |
| A10 | **Every save works.** The model has no failed save. **The real code breaks this:** a member can make a save raise (E500-meta, section 6). A save that raises stores nothing, since `json.dumps` runs before the write (`store.py:92-94`). So the safety properties, which are about the stored document, still hold. What is lost is progress: a table row that should run doesn't. | `sessions.py:106-110`, `store.py:92-94` | The effects in section 3.5, E1 to E3 firing, and the "leaves started" sentence in M9 |
| Powers | **What two signers can do.** Any commit or transcript whose fields fit the wire ranges and widths can be written as bytes that decode to it (`write_commit`, `write_transcript`), and the holder of either enrolled key can sign any bytes (`sign`). | `Verdict.lean`, `structure Powers` | Hypothesis of `X1`, `X1_keys` and `X1_session`. Not proved of `codec.py`. `Powers_satisfiable` shows it holds on the Lean copy of the layout, whose stand-in signatures have no security. |
| hsha | **The hash gives 32 bytes.** `p.width (p.sha256 m) = 32` for every message. | `Verdict.lean`, hypothesis `hsha` of `X1` | `X1`, `X1_keys`, `X1_session`. Not proved of real SHA-256 in Lean; true of it by its definition. |
| hb64 | **Each byte string has a base64 spelling.** For every `x` some `y` decodes to it. | `X1Session.lean`, hypothesis `hb64` of `X1_session` | `X1_session` only. Not proved of `base64` in Python. |

Not assumed, and not covered: anything about the transport. A captured request is a separate matter, see R1-gap in section 6.

## 3. The model

### 3.1 Fields kept

The session document is created at `sessions.py:153-167`.

| Field | Values | Notes |
| --- | --- | --- |
| `state` | created, joined, confirmed, started, done, aborted | `LIVE` is the first four (`sessions.py:81`) |
| `attempt` | 0 or 1 | |
| `seq` | number | +1 on every save (`sessions.py:107`) |
| `host_device_id`, `guest_device_id` | id; guest may be none | roles A and B (`sessions.py:132-137`) |
| `confirmed`, `armed`, `committed`, `submitted` | one flag per role | |
| `t0_ms`, `created_ms`, `token_expires_ms`, `finished_ms` | number or none | |
| `result` | record or none | |
| `error` | reason or none | |
| `attempts` | list of (attempt, outcome, reason, by, ...) | |
| `last_failure` | (attempt, reason, by, text) or none | |
| `per_role[r]` | `sample_rate`, `popt`, `cal_us`, commit bytes and signature, `commit_sha256`, `rec`, transcript bytes and signature, `half`, `self_os_delta`, `fail`, `transcript_sha256`, and `code_commit` in v2 | wiped on retry. `rtt_min_ms` is left out (section 3.3). |
| `session_id`, `nonce_hex`, `seed_hex`, `join_token` | opaque | never rewritten |

### 3.2 Fields abstracted

- **Signatures** are a predicate `Sig(pk, msg, sig)`. It stands for `verify_raw` (`crypto.py:31`).
- **Hashes** are opaque functions with no collisions. `commit_sha256`, `transcript_sha256`, `rec_sha256`, `rec_root`.
- **Codes** are one opaque value `Code(seed, role, attempt)`. The real one is PCM from `jbl250.template` keyed by `bed_key`. `bed_key = sha256("pop-v1|seed|JBL250|role|attempt|bed")` (`jbl250.py:47`, C11). The opaque value hides how keys become PCM, so nothing here shows that two different keys give different sound.
- **`code_commit`** (v2) is an opaque value of the two codes at that role's rate (`sessions.py:271-274`).
- **Clock** is a number. Each model step reads one value. The real code reads the clock several times in a handler. This matters in two places. M11 says how for `finished_ms`. In `join`, the `now > expiry` half of the guard (`sessions.py:184`) can only fire through a second read after the load, since E1 fires otherwise. Then it gives 410 and the state stays created (log lines `T-join`). A one-read model never takes that path.
- **Base64 and byte layout** are a parse that gives a field record or fails. `half` and `self_os_delta` are signed 32-bit, `sample_rate` is unsigned 32-bit, `attempt` is unsigned 8-bit (`codec.py:26-29`).
- **Responses** are kept, because M5 and M6 are about them. A response is one of: `Created(session_id, nonce, join_token, ...)`, `Own(code)`, `Partner(code)`, `View(...)`, `Ack`, `Record`, `Error`. `Created` goes only to the host (`sessions.py:171-174`). Its invite fields carry the same token.

### 3.3 Fields dropped

`display_name`, `model`, `attested`, `security_level`, `rtt_min_ms` (kept as an arm guard only), `updated_ms`, `tune_db`, `gain_db`, the `result.json` file, `context`, `early_nonce`, `zk`, `presence`, `not_before`, `last_flight_cm`, and in `per_role[r]`: `code_attest`, `armed_ms`, `committed_ms`, `submitted_ms`.

`last_flight_cm` is written at `sessions.py:460` and survives a retry, since `next_attempt` doesn't clear it. Nothing in `server/pop/` reads it back, so dropping it changes no behaviour.

**`meta` is dropped too, under A10 only.** No check and no response reads it, and the record leaves it out. But it isn't free of effects. `transcript` stores it after a size check with no depth check (`sessions.py:444-447`), and the attempts row saves it two levels deeper (`sessions.py:314-315, 344-345`). So a deep enough `meta` makes a later save raise. See E500-meta in section 6. With A10 false, the model's table doesn't describe that session until `abort` or E2 ends it.

`_record` copies `attested` from the device row when the session finishes (`sessions.py:362-366`). Out of scope, noted only.

### 3.4 Before every operation

Each route does these in order. FastAPI parses the JSON body before it runs the auth dependency, so bad JSON is answered with no auth at all.

| Step | Failure | Stored document |
| --- | --- | --- |
| JSON parse. Only on routes with a body model (join, arm, commit, transcript, fail; `main.py:465, 487, 493, 500, 506`), and only when the content type says JSON. | 400 `bad_request`, with `json_invalid` in the detail (`main.py:266-269`). A body too deep for the parser gets 400 `http_error` instead (seen with good auth, log lines `E500-meta`; before auth by reading, same parse step). No auth, no load, so even an unknown session gets 400. | unchanged |
| Auth (`main.py:287-291`, `auth.py:28-49`): device known, ts within 60 s of now, signature over method, path and query, body hash and ts, not seen before | 401, except an `X-Pop-Ts` that `int` can't read, which is a 500 (E500-ts, section 6) | unchanged |
| Body shape (`main.py:197-221`). Valid JSON of the wrong shape reaches here, so with no auth it gets 401, and with good auth 400. | 400 `bad_request`, before any load | unchanged |
| Query, view only (`main.py:471`). `after=x` and the like. | 400 `bad_request`, after auth and before any load, so an unknown session gets 400 and a due timeout doesn't fire (log lines `Order`) | unchanged |
| `load` (`sessions.py:125-129`): session known. The id is lowered first. | 404 | unchanged |
| `load` runs `_expire` | None in the model, given A10. In the real code its save can raise, a 500 to every route that loads (E500-meta). | **may change, and stays changed even if a later step fails.** If the save raises: unchanged. |
| `member` (`sessions.py:139-143`) | 403 | no further change |

create, confirm, abort, view and result have no body model, so for them auth comes first. A body the parser skips (no content type, or `text/plain`) fails at the body shape step, or at auth if that fails first. Seen in the log, lines `Order`.

`create` has no load. `join` loads inside `Sessions.join` and has no member step.

### 3.5 Transition table

"Unchanged" means the stored document is what the load left. r is the sender's role, r' the partner's. Guards run top to bottom, and the order matters.

| Op | Guard, in order | Effect | Errors, nothing changes | Errors that change state |
| --- | --- | --- | --- | --- |
| **E1** `_expire`, token (`sessions.py:114-116`) | state = created and now > `token_expires_ms` | state aborted, error timeout. No `finished_ms`, no attempts row. | | |
| **E2** `_expire`, age (`:117-119`) | state live and now - `created_ms` > 600000. Checked before E3. | state aborted, error timeout. No `finished_ms`, no attempts row. Also no result, even with one transcript in. | | |
| **E3** `_expire`, deadline (`:120-122`) | state = started and now > t0 + 20000 | `_failed(timeout, by)`. `by` is the silent role if exactly one, else none. | | |
| **create** (`:146-174`, `main.py:460-463`) | authenticated, then `parse_session_in` (`main.py:135-164`). An empty body is fine and means no context, `early_nonce=False`. A `policy` field, which older servers read, is ignored. | New document: state created, attempt 0, host = sender, fresh seed, nonce and token, flags false. Returns nonce and token to the host. | After auth, nothing stored: not JSON 400 `bad_request`, not an object 400 `bad_request`, `early_nonce` not a boolean 400 `bad_request`. Log lines `T-create`. A body nested past the parser limit: uncaught RecursionError, a 500, also nothing stored (E500-create, section 6). Context errors are out of scope, and so is `early_nonce=True`. | |
| **join** (`:176-188`) | sender = host: 400 `self_join`. guest set: 409 `already_joined`. Token wrong, after lowering it: 403 `bad_token`. state != created or now > expiry: 410 `token_expired`. | guest = sender, state joined. | all four guards; non-ASCII token: uncaught TypeError, a 500 (section 6) | |
| **confirm** (`:190-198`) | state = confirmed, or joined with own flag set: return as is. state != joined: 409 `bad_state`. | `confirmed[r]`. When both: state confirmed. | 409 | |
| **abort** (`:200-206`) | state done or aborted: return as is. | state aborted, error aborted, attempts row, `finished_ms`. | | |
| **arm** (`:231-257`) | state not in (confirmed, started): 409. attempt != current: 400 `bad_attempt`. Rate out of 36000..96000: 400. rtt out of 0..300: 400. popt null or absent means 1; any other value but the integers 1 and 2: 400. If `armed[r]`: another rate or popt 409, else own material again, no change. state != confirmed: 409. | `per_role[r]` = rate, rtt, time, popt, `cal_us` snapshot. `armed[r]`. When both: state started, t0 = now + 3000. Returns `Own(Code(seed, r, attempt))`. | all listed | |
| **commit** (`:276-308`) | state != started: 409. Bad base64 or layout: 400. `Sig` fails: 400 `signature_invalid`. role, attempt or nonce wrong: 400 `transcript_mismatch`. Version != armed: 400. If `committed[r]`: another `commit_b64` 409 `already_committed`, else `Partner(...)` again, no change. now < t0 + 1200: 409 `too_early`. | Stores commit, signature, hash, rec, time. `committed[r]`. Returns `Partner(Code(seed, r', attempt))`. | all listed | |
| **transcript** (`:411-465`) | (a) parses, attempt < current, `Sig` ok, state confirmed or started: 409 `stale_attempt`. (b) state != started: 409. (c) `submitted[r]`: same transcript and signature strings `Ack`, else 409 `already_submitted`. (d) not `committed[r]`: 409. (e) Bad base64 in `transcript_b64` or `sig_b64`, or `check_transcript` fails, see below. | Stores transcript, half, delta. `submitted[r]`. If the partner's isn't in: save, `Ack`. If both in: `combine`, then: verdict none: `_failed(reason, by)`. verdict set: `_finalize(verdict, reason, flight, "verdict", none)`. | (a) to (d) | **(e) fails: `_finalize(NOT_NEAR, reason, none, "rejected", r)`, session done, 400.** Final even at attempt 0. Bad base64 counts too (`sessions.py:434-435`, log line `T-tx`). |
| **fail** (`:467-480`) | reason not in `PHONE_REASONS`: 400. attempt not an int: 400. attempt < current, state confirmed or started: 409 `stale_attempt`. state not in (confirmed, started): 409. attempt > current: 400. `submitted[r]`: 409. | `per_role[r].fail`. Then `_failed(reason, r)`. No commit or arm needed. | all listed; `reason` = a list: uncaught TypeError, a 500 | |
| **view, result** (`:656-684`, `:482-485`) | result: none yet: 404. | none beyond the load. The view's long poll loads again after each sleep (`main.py:475-477`), and each `load` runs `_expire` (`sessions.py:125-129`, `:112-123`). So E1 to E3 can fire, and save, more than once inside one view request. | | |

**Step (e), order.** First base64 (`sessions.py:434-435`, reason `transcript_mismatch`). Then `check_transcript` (`verdict.py:112-143`): layout, signature, version, `pk_self`, role, nonce, attempt, `pk_partner`, rate = armed, rate in range, `commit_hash`, rec, then v2 only `delta` and `code_commit`.

**Internal steps.**

| Step | Rule | Effect |
| --- | --- | --- |
| `_failed` (`sessions.py:336-340`) | reason in `RETRY_REASONS` and attempt + 1 < 2 | `next_attempt` |
| | otherwise | `_finalize(NOT_NEAR, reason, none, "failed", by)` |
| `next_attempt` (`:311-321`) | attempt + 1 >= 2: 409. Unreachable, `_failed` is its only caller. | attempts row keeps old `per_role`. `last_failure` set. attempt + 1. state confirmed, t0 none. `armed`, `committed`, `submitted` reset, `per_role` wiped. `confirmed` stays. |
| `_finalize` (`:342-353`) | | attempts row. state done, error = reason, `finished_ms`, `result = _record(...)`, then `result["presence"]`, the core's signature over a copy of part of the record and the two device rows (`presence.record_body`). Saved. Then `result.json` is written. |

**When a save raises (A10 false).** This is an error path the rows above don't list. The request gets a 500. The stored document stays as it was, and edits in memory are gone. The rows it reaches are every path through `_failed` or `_finalize` once `meta` is at the deep depths: the partner's transcript, `fail`, a bad transcript, and E3. `abort` and E2 add no `per_role` to a row, and `commit` saves the plain document, so those still work. See E500-meta.

**Which reasons retry** (`verdict.py:37-41`). `capture_failed`, `glitch`, `self_not_heard`, `self_timestamp_mismatch`, `partner_not_heard`, `impossible_flight`, `timeout`. Not `partner_mismatch`, which a phone can send at `/fail` and is final at once. Not `too_far`, `signature_invalid`, `transcript_mismatch`.

**Guard at `sessions.py:457-459`.** `combine` raising after both sides passed `check_transcript` is unreachable, given A5, which keeps each id's key the same between the two checks, and given that different ids have different keys. That second fact comes from enrol, which refuses an id that isn't `sha256(pub)[:16]` (`main.py:347-349`, `crypto.py:12-13`). The comment there says so too. The model keeps the guard, in `afterStore`. In Lean, `combine_guard_unreachable`, `afterStore_accepted` and `combine_guard_on_request` show it can't fire, under `Function.Injective e.pk`.

## 4. Properties

Every property here has the same limit: it is about the server and signed numbers (CN1).

### Verdict math

**V1 (C19, C20, C21).** Let `ta`, `tb` be transcripts that each passed `check_transcript`, so rates are in 36000..96000 and halves are signed 32-bit. Let `pair` mean: `ta.role = A`, `tb.role = B`, same nonce, same attempt, `ta.pk_partner = tb.pk_self`, `tb.pk_partner = ta.pk_self`, `ta.pk_self != tb.pk_self`. Then:

- `combine` raises `Reject(transcript_mismatch)` iff not `pair` (`verdict.py:155-160`).
- `combine` returns verdict NEAR iff `pair`, and `self_os_ok` holds for both, and -20 < flight < 60, with flight the exact `flight_exact(ha, sra, hb, srb)`.
- If `pair` holds and a self check fails: verdict none, reason `self_timestamp_mismatch`, `by` = the first failing role, A checked first (`verdict.py:161-164`).

*Restated.* The hypothesis on rates is needed. `combine` has no rate check of its own: rate 0 raises `ZeroDivisionError` (log line `doc-combine`). Only a direct call can reach that.

**V2 (C21).** For every rational f, `decide(f)` is exactly one of: `(None, impossible_flight)` iff f <= -20; `(NOT_NEAR, too_far)` iff f >= 60; `(NEAR, None)` iff -20 < f < 60.

*Limit.* `decide(float("nan"))` returns NEAR (`verdict.py:83-87`, log line `V2-note`). `combine` is the only caller in `server/pop/` and always passes a Fraction (`verdict.py:165-166`), so this can't be reached today. The statement is over rationals for that reason.

**V3.** For integers hA, hB in [-2^31, 2^31) and rates srA, srB in [36000, 96000], let N = hA·srB - hB·srA and S = srA·srB. Then -20 < `flight_exact` < 60 iff -40·S < 34300·N < 120·S. This is the same test as the pair circuit: `Pair.lean:35-36, 46-47`, and `distance_iff` at `Pair.lean:110-116` proves that test equals the rational range, strict at both ends, on this same domain.

*Limits.* The server's code has no integer form. Only the docstring has it (`verdict.py:10-11`), so this is a statement about `flight_exact`. The circuit has no self check, so a server NEAR implies the circuit's range test, but not the other way round.

**V4 (C20).** `self_os_ok(d, sr, cal)` holds iff |d·10^6 - cal·sr| <= 50·1000·sr, integers, both edges included (`verdict.py:69`). In `combine`, cal is the snapshot `cal_us` for a v1 transcript and 0 for a v2 transcript (`verdict.py:162`), per transcript, so a pair may mix. Boundaries at 48000 with no cal: ±2400 pass, ±2401 fail. With cal 10000 µs: 480 ± 2400 pass, one more fails. The snapshot comes from `arm`, which reads the device row at that moment (`sessions.py:252, 328-330`). How the row got its `cal_us` (enrol, recalibrate) is out of scope. A5 pins the key, not the calibration.

**V5.** A swapped pair is rejected. The reason depends on the path:

| Path | Result |
| --- | --- |
| `combine(tb, ta)` | `transcript_mismatch` (`verdict.py:155`) |
| `verify_record` with transcripts swapped and keys in place | `signature_invalid` (`verdict.py:116`) |
| `verify_record` with transcripts, commits and keys all swapped | `transcript_mismatch`, from `check_commit` role (`verdict.py:97`) |
| Live: a phone signs a transcript with the other role | `transcript_mismatch`, final (`verdict.py:122`, `sessions.py:441-443`) |

*Restated.* The docstring says `transcript_mismatch` only (section 6).

**V6 (C17).** If `check_transcript` returns t, then all of these hold:

- `Sig(pk_self, raw, sig)`, and t's version = `version`.
- `t.pk_self = pk_self`, `t.role = role`, `t.nonce = nonce`, `t.attempt = attempt`, `t.pk_partner = pk_partner`.
- 36000 <= `t.sample_rate` <= 96000. If `sample_rate` was given, they are equal.
- `commit_sha256` was given and `t.commit_hash` equals it. `rec` was given and t's rec field equals it.
- If version 2: `t.delta = popt2.delta(t.sample_rate)`, and if `code_commit` was given, they are equal.

Nothing above pins these fields: `half`, `self_os_delta`, `play_frame_position`, `play_nano_time`, `rec_frame0_nano_time`, and in v2 `a_self` and `p_partner`. So the sender chooses them freely. For `half` and `self_os_delta` that is on purpose, and it is what CN1 is about.

**V7 (replay).** Let R be a final record from `_finalize`, with a commit and transcript for both roles. Then `verify_record(R)` does not raise, and the mapping is:

| How the session ended | Record | `verify_record` returns |
| --- | --- | --- |
| outcome verdict, NEAR | NEAR, reason none, flight x | NEAR, none, x, by none |
| outcome verdict, too_far | NOT_NEAR, too_far, flight x | NOT_NEAR, too_far, x, by none |
| outcome failed, from `combine`, `impossible_flight`, attempt 1 | NOT_NEAR, `impossible_flight`, flight none | verdict none, same reason, flight a number |
| outcome failed, from `combine`, `self_timestamp_mismatch`, attempt 1 | NOT_NEAR, same reason, flight none, attempts row `by` = r | verdict none, same reason, flight none, by r |
| outcome rejected, or a final fail or timeout | at least one transcript missing | raises `Reject` |

The last row was run for all three: rejected, final fail, final timeout (log lines `V7`).

*Limits.* The first two were run. The last two are by reading.

In Lean (2026-11-07), on the model, through `toRR`: `V7_session` covers every reachable final record with no key assumption. Rows 1 and 2 match verdict, reason and flight (`V7_both`, `V7_verdict_row`, `V7_near`). Rows 3 and 4 match the reason only; the record says NOT_NEAR with flight none at attempt 1, replay's flight is a number for `impossible_flight` and none for `self_timestamp_mismatch` (`V7_failed_row`, `V7_failed_row_flight`), and `by` is read from the doc's last attempts row. Row 5 rejects with the reason not pinned (`V7_missing`), and nothing is said when a device row is missing, where Python raises `KeyError`. `V7_both` keeps a reject case with `transcript_mismatch`; `V7_both_inj` removes it and needs `Function.Injective e.pk`. That `verify_record` does not raise is not fully pinned for row 5.

- `verify_record` never compares against the record's `verdict`, `reason`, `flight_cm`, or `devices[r].half`. Changing them changes nothing. A reader must compare for themselves.
- `devices[r].cal_us` is under no device signature (`verdict.py:189`). Changing it moves a v1 replay. v2 ignores it.
- The record supplies its own keys (`verdict.py:177`). A reader must already know the two device keys (`informal-spec.md`, "Who is trusted").
- Offline it passes `sample_rate=None` and no `code_commit`, and it can't check timing or order. So it is weaker than the live checks, which is why live acceptance implies replay acceptance, and not the reverse.

**V8 (added). Display.** `result.flight_cm` is `round(float(f), 2)` (`verdict.py:167`). NEAR can show 60.0 (hA 95 at 48000, hB -67 at 44100, f = 59.998) or -20.0 (hA 79 at 48000, hB 124 at 44100, f = -19.996). A consumer must read `verdict`, not decide again from `flight_cm`.

### State machine

**M1 (C9).** *Restated.* The core fields change only by a row of section 3.5. Core fields means section 3.1 without `seq`, and `result` without `result["zk"]`. The zk routes also write `s["zk"]`, `result["zk"]`, `seq` and `updated_ms` on this kind of session, after NEAR (A9). None of those is a core field. From done or aborted no row changes `state`: E1 to E3 need a live state, confirm, arm, commit, transcript and fail refuse, abort returns as is, join refuses.

**M2.** Once `result` is set, these fields of it never change: `verdict`, `reason`, `flight_cm`, `attempt`, `devices`, `transcripts`, `commits`, `attempts`. `state` and `error` don't change either.

*Restated.* `result["zk"]` does change, and so does `result["presence"]`, which holds a copy of `zk` and is signed again when it changes (`_result_zk`, `sessions.py:390-397`). `result.json` is rewritten. So do `seq` and `updated_ms`. All from the zk routes, out of scope (A9). Without a zk route, `presence` is fixed at `_finalize` like the rest; the walk checks its body against the record and its signature under the presence key.

**M3 (CP3, C17, C19).** If `result.verdict = NEAR`, then for k = `result.attempt` and each role r:

1. `committed[r]` and `submitted[r]`, and they were accepted while `attempt = k`.
2. `Sig(pk(r), commit_raw_r, commit_sig_r)`, where pk(r) is the enrolled key of r's device. The commit has role r, attempt k, this session's nonce.
3. `Sig(pk(r), raw_r, sig_r)`. The transcript has `pk_self = pk(r)`, `pk_partner = pk(r')`, role r, attempt k, this nonce, `commit_hash` = hash of that commit, rec = that commit's rec.
4. `combine` on those two transcripts, with the `cal_us` snapshots, returned NEAR.

It says nothing about NOT_NEAR. NOT_NEAR needs no such pair (X2).

**M4.** NEAR has one source. `_finalize` is the only writer of `result` (`sessions.py:348`). Its call sites are `:340`, `:442`, `:458`, `:464`. The first three pass the literal `"NOT_NEAR"`. Only `:464` passes `out["verdict"]`, from `combine`.

**M5 (CP1, C14, C15).** A response holding `Code(seed, r', k)` to the device of role r comes only from `commit()` (`sessions.py:295, 308`, via `_partner_bed`, only called there). At that point: state = started, attempt = k, `committed[r]`, and that commit was accepted at a clock read >= t0 + 1200. `arm` returns only r's own code (`sessions.py:216-229`). `seed_hex` appears in no response: it is read only at `sessions.py:210`, and `create`, `view` and `_record` don't list it. `join_token` is returned only by `create`, in `Created`, to the host.

*Scope.* Over the routes in scope. It says only what the server sends. The partner's code is also played out loud, and a colluding partner can hand it over at arm (CP1).

*Note.* The partner's commit isn't needed. A device can get r' code before r' has committed.

**M6 (CP2, C18).** While state is live, no response to a device holds the partner's `half`, `self_os_delta` or transcript. `view` exposes `result`, which is none until done (`sessions.py:681`), and doesn't expose `per_role`, `attempts` or `last_flight_cm`. The arm response holds the sender's own material. The transcript response holds `accepted`, `state`, `attempt`. The commit response holds the partner's code (M5) and the sender's own `code_commit`, `code_attest`. None of them holds the partner's half, delta or transcript.

**What does leak, while live:**

- `submitted`, `committed`, `armed`, `confirmed` flags for both roles, and `seq`. So a phone sees when the partner moved.
- `last_failure` = `{attempt, reason, by, text}`, for the old attempt. `text` is a fixed string for the reason (`sessions.py:316`). No number is in it. Both phones see the same report.
- The partner's `pubkey`, `cal_us`, `popt`, `t0_ms`, device fields (`sessions.py:671-678`). None is a half. The partner's rate isn't shown.

**What each report says.** `combine` checks A's self delta, then B's, then flight, and stops at the first that fails (`verdict.py:161-166`). So a report from `combine` says more than its own reason. But a report doesn't always come from `combine`. `self_timestamp_mismatch` is in `PHONE_REASONS` (`verdict.py:40`), so a phone can post it at `/fail`, where `combine` never runs. Only `impossible_flight` always comes from `combine`, since no phone can post it. Seen in both logs, lines `M6-leak`.

| `last_failure` | Comes from | What it means, by where it came from |
| --- | --- | --- |
| `impossible_flight`, by none | `combine` only | Both self checks passed, and flight <= -20. So the partner's `self_os_delta` was in range, and its half lies on one side of a line, if the phone knows or guesses the partner's rate. |
| `self_timestamp_mismatch`, by A | `combine`, or A's `/fail` | From `combine`: A's self check failed. Nothing about B's self check or the flight, since neither was computed. From `/fail`: no self check was run, so nothing about any delta. |
| `self_timestamp_mismatch`, by B | `combine`, or B's `/fail` | From `combine`: A's self check passed and B's failed. Nothing about the flight. From `/fail`: no self check was run, so nothing about any delta. |
| any other retry reason | never `combine` | `timeout`, by the silent role or none. Or a phone's report from `/fail`, by that phone. It says nothing about a half, but it can be read as the partner's own claim. |

**The two sources look the same.** A phone reading a report that names its partner can't tell from the report alone that `combine` ran. So `by` = B doesn't tell A that A's self check passed, or that B's delta was out of range. Repro: A commits and submits with `self_os_delta` 5000 at 48000, far out of range. B commits and sends no transcript, just `/fail` with `self_timestamp_mismatch`. A's view shows the report by B. A's view is then equal, field by field for state, attempt, flags, report and result, to a run where A's delta was 0 and B's real transcript failed in `combine`. The flags reset on retry, so they don't help afterwards.

A phone can read more only when it knows the partner couldn't have used `/fail`, or knows `combine` ran. That takes knowledge from outside the report:

- The report names this phone, and it knows it sent no `/fail`. So B, reading "by B", learns A's delta was in range and its own wasn't.
- This phone's own transcript answer shows the attempt moved. `combine` ran inside that request.
- This phone saw `submitted` true for the partner earlier in that attempt. The partner's `/fail` is then 409 `already_submitted`. So A, having seen B's flag, reads "by B" as A passed and B failed.

And a phone that sent no transcript for that attempt knows `combine` didn't run. A phone that sent its transcript first and never saw the partner's flag can't tell.

So a report from `combine` is one of three outcomes, and it isn't a single bit about the half. No number is shown. There is at most one report in a session, since there is at most one retry.

**When it arrives.** It comes after this phone's transcript for that attempt is fixed, if `combine` ran. **It also comes before this phone signs for attempt 1.** How close attempt 1's numbers would be to attempt 0's is not studied.

**After a one-sided end** the session is no longer live, and the result shows the half that was in (bad transcript, final fail, final timeout; `sessions.py:365`, log lines `M6: session over` and `M6: final fail`). Once the session is started and it has committed, a phone can cause this at will by sending a bad transcript. C18 says this can't help because the session is over. That is right for that session. Whether it helps in a later session, against the same partner, is not studied.

**M7 (CP5).** `attempt` is 0 or 1. It is written only at `sessions.py:317`, after the guard at `:312` and `:338`. So at most two measured attempts. Each needs both phones to arm again, since `next_attempt` resets `armed`. An attempt can also end with no measurement (`/fail`).

**M8.** No data from attempt k can count in attempt k + 1:

- `next_attempt` wipes `per_role` and the flags (`sessions.py:319-320`).
- `commit` and `check_transcript` pin the attempt (`sessions.py:286`, `verdict.py:126`).
- A signed older transcript or a fail for an older attempt is 409 `stale_attempt`, no change (`_stale`, called at `sessions.py:421-422` and `:472`). An older commit has no stale check. It is 400 `transcript_mismatch`, no change, after the state gate (`:277`) and the signature check (`:284`), at the attempt compare (`:286-287`).
- *Restated.* Keys differ by derivation: `bed_key` hashes the role and the attempt, so four inputs give four keys under A5 (`jbl250.py:47`). In Lean, `M8_keys` needs no collision among those four messages only, and `bed_msg_eq_iff` shows the four messages differ with no hash assumption. The first draft said codes differ. That different keys give different PCM isn't argued here. `Code(seed, role, attempt)` hides it, and DSP is out of scope.

*Limit.* The numbers and `rec` can be repeated. Nothing stops a phone signing the same half and the same recording hash again at attempt 1, with the new attempt number. This property is about the signed records, not about freshness of audio.

**M9 (induction invariant).** After every row of section 3.5, with r either role. Here ⇒ means "implies", and ⇔ means "exactly when".

| State | Must hold |
| --- | --- |
| all | attempt in {0, 1}. Host set, host != guest. `submitted[r]` ⇒ `committed[r]` ⇒ `armed[r]`. `attempts[i].attempt = i`. |
| all | `result` set ⇔ state = done. `committed[r]` ⇒ `per_role[r]` has the commit. `submitted[r]` ⇒ `per_role[r]` has the transcript. `armed[r]` ⇔ `per_role[r]` has a rate. |
| all | `confirmed` flags only go from false to true. |
| created | guest none, all flags false, t0 none, attempt 0. |
| joined | guest set, not both confirmed, armed, committed, submitted false, t0 none, attempt 0. |
| confirmed | guest set, both confirmed, not both armed, none committed, none submitted, t0 none. |
| started | guest set, both confirmed, both armed, t0 set, not both submitted, `per_role[r]` has rate and popt. |
| done | `finished_ms` set, `error = result.reason`. If verdict: both submitted. |
| aborted | result none. error is aborted (from abort, `finished_ms` set) or timeout (from E1 or E2, `finished_ms` none). |

The implication `submitted ⇒ committed ⇒ armed` holds in every state, since only `next_attempt` clears a flag, and it clears all three. `fail` adds only a `fail` key, which a retry wipes.

"Never all-submitted and still started" is the row in `started`. It is about the stored document. Given A10, the last transcript leaves started (`sessions.py:451-464`). If its save raises (E500-meta), nothing is stored, so the stored document still has one role not submitted, and the session stays started. Either way the row holds, so E3 always finds a silent role. A row that raises stores nothing, so "after every row" covers it too.

**M10 (C14, C17).** Per role and per attempt, at most one commit and one transcript are ever stored. The first accepted stays. While the session is started at that attempt, a repeat returns the same kind of answer and changes nothing. After that, a repeat is refused and still changes nothing:

- A transcript from an older attempt gets 409 `stale_attempt` while the state is confirmed or started, and 409 `bad_state` once done or aborted (log lines `doc-resend`).
- A commit from an older attempt gets 409 `bad_state` if not started, and 400 `transcript_mismatch` if started at the next attempt.

While started, a different one gets:

- A different commit that passes the checks before it (layout, signature, role, attempt, nonce, version) is 409 `already_committed`. One that fails those is 400 (`sessions.py:279-294`).
- A different transcript is 409 `already_submitted` while started, with no signature check (`sessions.py:426-429`).

No case stores anything. Log lines `M10`.

*Note.* The commit repeat compares `commit_b64` only, so a fresh signature passes and isn't stored. The transcript repeat compares both strings, so a fresh signature is 409 (section 6).

**M11 (C6, C22).** *Restated.* If `result.verdict = NEAR`, then at the load at the top of the finalizing request, the clock read `n` had n <= t0 + 20000 and n - `created_ms` <= 600000. Both edges pass, since `_expire` is strict `>` (`sessions.py:117, 120`). Also both commits were at or after t0 + 1200, and t0 >= arm time + 3000.

`finished_ms` is a later clock read in the same handler (`sessions.py:347`), so it can pass t0 + 20000 by the handler's run time. Seen in the log, line `M11-restated`. In a model with one clock read per step, `finished_ms = n` and the bound holds on `finished_ms`.

**M12 (C6).** *Restated.* The first draft said "every session-mutating route is an authenticated member". The run shows that's not all of it:

- Every handler change comes from an authenticated sender. confirm, arm, commit, transcript, fail, abort are also members (`main.py:483, 490, 496, 503, 509, 710`). `create` makes the sender host. `join` makes the sender guest, with the token.
- **`_expire` is the exception.** It runs in `load`, before the member check. Any caller who knows the session id fires it: a non-member's GET, and with no auth at all `/zk/bundle` (`main.py:593`). The change is only what the clock already dictates, so a member's next request would do the same. Seen in the log, lines `M12-restated`.
- Roles are fixed. `host_device_id` is written only at create, `guest_device_id` only at join, while none (`sessions.py:162, 180, 186`).
- A != B. `guest_device_id != host_device_id` by `self_join` (`sessions.py:178`). The id is a function of the key, so different ids mean different keys, with no assumption needed.

**M13 (added). Fixed fields.** `session_id`, `seed_hex`, `nonce_hex`, `join_token`, `created_ms`, `token_expires_ms`, `host_device_id` are written once, at create. `t0_ms` is written once per attempt: set at the second arm, cleared on retry (`sessions.py:255, 318`).

**M14 (added). Failed requests leave no trace.** Every error row marked unchanged raises before any save. Edits in memory are thrown away, given A8. The one error that changes state on purpose is the bad transcript. In Lean, `M14` and `M14_any`: after any error the stored doc is the one before the load (bad JSON, no auth, bad shape) or the one the load left. The exception is a `/transcript` from member `role` answering 400 with reason `rsn`. Since 2026-11-09 it is pinned by `TxReject`: the stored doc is a NOT_NEAR `_finalize`, outcome `rejected`, no flight, of exactly one of two docs, the loaded doc blaming `role` when the transcript check rejects (`sessions.py:441-443`), or the loaded doc with this transcript stored blaming no role when `combine` rejects (`:457-459`). Not pinned: that a 400 always finalizes (the unchanged case has no status limit), which reason `combine` gives, and when `M14_any`'s case "the doc before the load" may occur. A save that raises also leaves no trace (A10, log lines `E500-meta`), but it is a 500, and the work it should have done doesn't happen. *Note.* `_finalize` saves, then writes `result.json` (`sessions.py:351-352`). A full disk gives a 500 with the session already final.

**R1 (added, auth).** A request is accepted only if the device row exists, the ts is within 60 s, and the device's key signed `pop-req-v1`, method, path and query, body hash, ts (`auth.py:19-20, 28-43`).

Replay. Let `first` be the clock read when a (device, ts, signature string) was first accepted. Given A7:

- For every later read n before `first` + 120000, the same triple is refused: `auth_replay`, or `auth_stale` if the ts has aged out.
- At exactly n = `first` + 120000 the entry is forgotten (`auth.py:44`, which keeps it only while v > now). The ts check still passes in one case only: ts = `first` + 60000, a ts signed a full 60 s ahead. Then the same triple is accepted a second time.
- For every n after that, the ts check refuses it (`auth.py:36`).

So with no restart, a triple is accepted at most twice, and the second time only at that one millisecond (R1-edge, section 6). *Not* covered: the same signature in another spelling (R1-gap, section 6). The cache is per process and lost on restart (`auth.py:26`).

**D1 (added, by reading).** The three signed message kinds in scope can't be read as each other: `POPC` (71 bytes), `POPT` (269 or 311 bytes), `pop-req-v1\n...` (`codec.py:23-28`, `auth.py:20`). So a signature on one is no use as another, under A4. Calibration and owner-sig messages are out of scope and not checked.

### Known holes

**X1 (CN1). The hole, stated as a theorem target.** For any integers hA, hB in [-2^31, 2^31), the wire range (`codec.py:29`), and rates in 36000..96000, with -20 < `flight_exact` < 60, two signers holding their enrolled keys, who pick those numbers, pick any recording hash (for v2, any value below the field size, `codec.py:43-45`), set `self_os_delta` to pass, and never touch audio, reach `result.verdict = NEAR`, provided they send every step in order and on time. In v2 they copy `delta` and `code_commit` from the server's replies. No step of section 3.5 reads audio. A half of 2^31 can't be encoded (`struct.error`), so no such run exists. Seen in the log on both v1 and v2, lines `X1`.

So a proof of X1 is a proof that the server's verdict can't tell distance by itself. It must be proved next to M3, so nobody reads M3 as more than it is.

In Lean (2026-11-07, conclusion strengthened 2026-11-09): `X1_session` proves this target on the model, for every allowed pick, v1 and v2, mixed versions too, on one fixed schedule. Its conclusion `X1Reached` says the run starts from the given `create` at `T`, keeps `sid`, `nonce`, `seed` and `token`, ends `done` at `T + 4411` with a NEAR record at the exact flight, and that the stored commits and transcripts carry the picked recording values, halves and self deltas. It rests on the hypotheses `Powers`, `hsha` and `hb64` (section 2). `X1_session_on_layout` shows they can all hold at once; its instances use one all-zero value for both recording values and the nonce, and self deltas 0. Lean stores the exact flight, Python `round(float(f), 2)` (`verdict.py:167`). See `README.md`.

**X2 (added, CP3, CP5).** One member can end a session as NOT_NEAR or aborted, with no measurement. What each way needs from the other member:

| Way | Needs | Why |
| --- | --- | --- |
| `/abort` | nobody else | any live state, even right after create |
| `/fail` twice, or `partner_mismatch` once | both confirmed | state must be confirmed or started (`sessions.py:473`). No arm or commit is needed: `fail` never reads them (`:467-480`). `partner_mismatch` is not a retry reason (`verdict.py:37-41`), so one `/fail` with it is final at once (`_failed`, `sessions.py:336-340`). That is the cheapest one-sided end. |
| one bad transcript | both armed, and the sender's own commit at t0 + 1200 or later | state must be started, and committed comes first |

So NOT_NEAR is no finding about distance either. Seen in the log, lines `X2` and `T-fail`.

In Lean (2026-11-07): `X2_abort` is a full step on a reachable doc that is live after the load, and `X2_abort_after_create` covers the host alone. The `/fail` and bad-transcript rows (`X2_fail_final`, `X2_fail_partner_mismatch`, `X2_fail_twice`, `X2_bad_transcript`, `X2_fail_needs`, `X2_tx_needs`) are about the handler on an arbitrary doc with state hypotheses, not shown reachable and with no load. Their needs are shown as states (confirmed or started; started and committed), not as both members having confirmed or armed.

## 5. What checks each property

**Note, 2026-11-07. This table is history, not the current list.** The current status of each property is the table in [`README.md`](README.md). The "Plan" column below was written before the Lean work and the walk.

**Note, 2026-11-06.** This table is older than the Lean work. `lean/ServerFv/Verdict.lean` and `lean/ServerFv/Machine.lean` now exist. The machine's checks, M13 included, are in `lean/checks/machine_all.sh`. The Lean table is compared with the real Python on sampled runs by `lean/ServerFv/Replay.lean`; `run_all.sh` runs both. That is testing, not a proof that the two are equal. These results show the server follows its rules on signed numbers. They do not show a phone told the truth about the air (CN1).

At the time this table was written, nothing in it was proved in Lean. "Run" means seen in the output of `spec-checks/recheck.py` or `tests/recheck_m6_fail.py`, and only for the cases that script has. It is a spot check, not a walk over all orders. "Plan" is what should check it next. A reviewer also ran a separate random walk over the table. Its log wasn't kept, so nothing below counts it.

| Id | Run so far | Plan |
| --- | --- | --- |
| V1 | `V1-route`: flight at and next to -20 and 60, and self delta at and next to ±2400, through the routes. Exact ties at rate 68600. Direct calls in V2, V3, V4. `doc-combine`. | Lean on a model of `combine` |
| V2 | Seven values, NaN note | Lean |
| V3 | 200,000 random inputs and two exact ties at rate 68600. Circuit side already proved, `Pair.distance_iff` (arithmetic only). | Lean, bridge to `Pair.distance_iff` |
| V4 | Direct calls: boundaries at 48000 and 44100, cal, v2. Self delta edges through the routes are under `V1-route`. | Lean |
| V5 | All four rows | Lean for `combine`, walk for the rest |
| V6 | Spot cases only | Lean, by reading the guards in order |
| V7 | Each row of the mapping. The last row with rejected, final fail, final timeout. The first two limits. | Walk on real code, Lean for the mapping on the model |
| V8 | Two examples, direct and through the routes | Walk |
| M1 | Spot cases on done | Lean, induction on the table. Walk to show the table matches the code |
| M2 | Reading | Lean, walk |
| M3 | Reading, X1 walk reaches it | Lean |
| M4 | Reading of four call sites | Reading, and a walk that never sees NEAR otherwise |
| M5 | Gate at 1199 and 1200, seed and token scan on one walk | Lean for order, walk scanning every response body |
| M6 | Scans of views and all response bodies on some walks. `M6-leak`: the order of self and flight checks, four cases. Second log, `M6-leak`: `/fail` and `combine` give the same report, when a phone can tell them apart, and `/fail` refuses `impossible_flight` and `timeout`. | Lean over the response type, walk |
| M7 | Retry and final | Lean |
| M8 | Stale cases, four keys | Lean, walk |
| M9 | Reset after retry, and the stored document after a failed save. **Mostly reading.** | Lean, induction. Walk asserts it after every step |
| M10 | Commit and transcript repeats, a different one of each, a different commit with a wrong signature, a transcript resent after a retry, a done and an abort | Lean, walk |
| M11 | Exact edges, tick-clock case | Lean with one clock read per step, walk for edges |
| M12 | Non-member on six routes, no auth, second join, self join, lazy timeouts | Walk. Reading for the route list |
| M13 | Lean, `M13` and `M13_t0`, checked by `machine_all.sh` | Lean |
| M14 | Spot cases in M5, M8, M10 | Walk |
| R1 | Exact replay. The window edges at + 119999, + 120000, + 120001. | Walk |
| Section 3.4 order | Log lines `Order` | Walk |
| create errors | Log lines `T-create`: four refusals, empty body, no auth. Second log, lines `E500-create`. | Walk |
| join second clock read, lowering | Log lines `T-join` | Walk |
| E500-meta, A10 | A scan of depths, then the full sequence at each depth in the band | Reading for the cause. uvicorn not run. |
| D1 | Not run | Reading only |
| X1 | v1 and v2, one halves pair each. v1 at both ends of the wire range and at rates 36000 and 96000. 2^31 can't be encoded. | Lean as a reachability theorem, walk |
| X2 | `/fail` twice, `partner_mismatch`, bad transcript, `/abort` alone after create. `/fail` and a bad transcript refused before their needs are met. | Walk |
| A2, A3, A9 | Not run | Reading only. Stay assumptions |

## 6. Where code, docstrings and `informal-spec.md` disagree

**Code reports, with a repro. Not fixed, per the rules of this work.**

| Id | Where | What happens | Repro | Does it matter |
| --- | --- | --- | --- | --- |
| R1-gap | `auth.py:45-46`, `auth.py:39`, `crypto.py:32` | The replay cache keys on the signature's base64 string. The same signature in another spelling, or with s flipped to n - s, counts as new. | Take a valid signed POST. Send it again with `X-Pop-Sig` last character before `==` changed in its unused bits, or with s = n - s. Both 200. Log lines `R1-gap`. | Replay, not forgery. It needs a captured request and fits inside the 60 s window. Session routes are guarded or repeat safely, so a repeat does little there. A replayed `POST /v1/session` makes an extra session. Low. |
| R1-edge | `auth.py:36, 44` | The window to forget (120 s) ends exactly when a ts signed 60 s ahead is still just in range. The same headers are accepted a second time. | `POST /v1/session` with `X-Pop-Ts` = now + 60000: 200. Same headers at + 119999: 401 `auth_replay`. At + 120000: 200. At + 120001: 401 `auth_stale`. Log lines `R1-edge`. | One millisecond, and it needs a captured request with a ts a full 60 s ahead. Low. |
| E500-ts | `auth.py:36` | `isdigit` passes, then `int` raises `ValueError`. It happens after the device lookup and before the signature check. | Known device id, `X-Pop-Ts` of 5000 digits: 500, not 401, through the test client. `X-Pop-Ts` = superscript 2 raises the same, seen by a direct call to `check`, since the test client changes header bytes. An unknown device gets 401. Log lines `E500-ts`. uvicorn not run. | Low. Anyone who knows a device id gets a 500, on their own request. Document unchanged. |
| E500-fail | `sessions.py:468` | `reason` is `Any`. A list is unhashable, so `in` raises TypeError. | `POST /fail {"attempt":0,"reason":[]}`. Uncaught, 500. Document unchanged. | Low. A member hurts only their own request. |
| E500-meta | `sessions.py:444-447`, `:314-315`, `:344-345`, `main.py:216` | `meta` has a size limit and no depth limit. A row in `attempts` holds `per_role`, which puts `meta` two levels deeper than in the plain document. At the right depth the first save works and every later save with such a row raises `RecursionError`. No wrong verdict results, and no NEAR is stored. But the session can't finish, and for a stretch the partner can't read or abort it. | Depth counts containers with the outer dict, so `{"x": [[...]]}` with depth - 1 lists. Python 3.12, FastAPI test client. A commits and posts a valid transcript with such a `meta`. **Depth 9989 or 9990:** A gets 200. B's transcript with NEAR numbers gets 500, and so does a resend. B's `/fail` and a bad transcript also get 500. Stored state stays started. Abort before the deadline still works. At t0 + 20000, view works. From t0 + 20001, view, abort and even the no-auth `/zk/bundle` gets 500, since E3's save in `load` raises. After created + 600001, E2 wins and the session is aborted, timeout, no result. **Depth 9988 and below:** normal. **Depth 9991, 9992:** 500 on A's own request, document unchanged. **Depth 9993 and up:** 400 `http_error`, on parsing. The exact depths belong to this Python and this setup. Log lines `E500-meta`. uvicorn not run. | Low. A member can already end a session. What this adds: the partner gets 500s up to about 600 s, and can't abort for most of that time. It is a stall, not a verdict, so it doesn't change X2's table. |
| E500-join | `sessions.py:182` | `hmac.compare_digest` raises on non-ASCII strings. | `POST /join {"join_token":"é"}`. Uncaught, 500. Document unchanged. | Low. |
| E500-create | `main.py:138-141` | `parse_session_in` catches only `ValueError`. A body nested past the parser limit raises `RecursionError`. | Authenticated `POST /v1/session` with a body of 12000 nested lists: uncaught, 500, nothing stored. At depths 5000, 9000, 9900 and 9990: 400 `bad_request`, "body must be an object". Depth 10000 and up: 500, in this scan. Depths 9991 to 9999 were not tried. No auth: 401, since auth comes first here. The exact depths belong to this Python and this setup. Second log, lines `E500-create`. uvicorn not run. | Low. A known device hurts only its own request. |

**Docstrings against code.**

| Where | Says | Code | Matters |
| --- | --- | --- | --- |
| `sessions.py:8` | Nonce is shown only from `confirmed` on, unless `early_nonce` | `create` returns it to the host at once (`:174`). Only `view` hides it (`:663, 667`). | No weight for the verdict. The host made the session, the nonce pins the session and not the time, and the t0 gate still applies. The guest gets it only after both confirm. The app reads a null nonce in `view` as "both confirmed", so don't remove the hiding. |
| `sessions.py:3` | "any -> aborted" | done can't abort (`:201`) | Wording. `informal-spec.md` C9 has it right: any live state. |
| `sessions.py:12` | Arm repeats are idempotent for (attempt, rate) | Also popt. rtt is not compared. | No. |
| `sessions.py:15` | A repeated identical commit returns the bed | Compares `commit_b64` only. A fresh signature passes and isn't stored (log `M10`). The same bytes in another base64 spelling are 409. | No. Same content either way. |
| `sessions.py:18-19` | "transcript / fail need the sender's own commit first", then "fail may also come before commit" | Contradicts itself. `fail` never reads `committed` (`:467-480`). | Doc only. C9 and CP5 are right. |
| `sessions.py:21-22` | A resend of the same transcript is idempotent | Only while started and before the session moves on. After a retry: 409 `stale_attempt`, from the check at `:421-422`. After done or abort: 409 `bad_state`, from `:423` (log `doc-resend`). A fresh signature on the same transcript is 409 `already_submitted`, unlike commit. | A phone that lost the response to its last transcript gets 409 and must read `view`. No safety effect. |
| `verdict.py:5` | `verify_record` re-runs "every check" | It can't check timing, order, armed rate or `code_commit` (`:174, :186-188`). It doesn't compare the verdict. `cal_us` is unsigned. | Yes for anyone relying on it. See V7. |
| `verdict.py:8` | `flight <= IMPOSSIBLE_CM` "retry" | `combine` gives verdict none. At attempt 1 that is a final NOT_NEAR, and a replay gives none where the record says NOT_NEAR. | Yes, for a consumer comparing. See V7. |
| `verdict.py:20-21` | A swapped pair is `transcript_mismatch` | Depends on the path. `verify_record` with swapped transcripts gives `signature_invalid`. See V5. | Doc only. It is refused either way. |
| `verdict.py:42` | `FINAL_REASONS` | Never read. `_failed` uses `RETRY_REASONS`. | Dead code. |
| `verdict.py:82` | "a float is compared as given" | NaN gives NEAR. No caller passes a float. | Not today. |
| `verdict.py:153` | "safe on its own" | No rate check. Rate 0 raises. | Not reachable in the live flow. |

**`informal-spec.md` against code.**

| Rule | Says | Code | Matters |
| --- | --- | --- | --- |
| C6 | A session lasts at most 600 s | Lazy. The state turns only at the next `load`. E1 and E2 write no `finished_ms`. A done session isn't touched. | Wording. M11 has the exact form. |
| C14, C15 | Gate at t0 + 1.2 s | Matches (`sessions.py:296`). But capture runs to t0 + 2.0 s (C12, `constants.py:10-11`), so the gate is "sounds over by schedule", not "capture over". A phone committing at the gate has hashed a recording that isn't finished yet, if it claims the whole capture. | No check depends on it. Worth knowing when reading CP1. |
| C18 | "That half can't help, because the session is over." | True for that session. A phone can force this read with a bad transcript, at attempt 0. A cheaper one-sided end exists: `/fail partner_mismatch` once both have confirmed, with no arm or commit (X2). It ends the session before any half is sent, so C18 still holds. | Later sessions not studied. |
| CP2 | "A retry shows only the reason" | Also `by` and the flags. See M6. The report arrives before the phone signs for attempt 1. | Small. One of three outcomes, no number, once per session. Not one bit: `impossible_flight` also says the partner's self check passed. `self_timestamp_mismatch` by B says A's passed only if `combine` ran. A phone can't always tell that, since B's `/fail` gives the same report. See M6. Say it, don't hide it. |

**The first draft of these properties against code.** Restated above, each marked: V1 (hypothesis), V5 (reason), V7 (mapping), M1 (core fields), M2 (`zk` carved out), M8 (keys, not codes), M11 (two clock reads), M12 (`_expire`). None was removed. M6 was also restated after review: the first wording called the report one bit. Facts handed in and rechecked: decide's three-way split, the integer form, the display values, `_finalize` sites, replay mapping, the 1200 ms gate, strict deadlines, the `create` nonce, no exposure of `last_flight_cm` and `per_role`. All agreed.

**Not checked here.** No phone ran. Nothing in the app was read for this spec, except the note at `sessions.py:662` on how it reads the nonce. No Lean ran for this spec.
