# v2 spec: the protocol without the server, and the fixed rule

Written 2026-11-10. Stage 2 of [`../ROADMAP.md`](../ROADMAP.md). Nothing here is built. No device code, no circuit, no model yet. This file is what the v2 Lean models will follow.

It starts from [`../v1/informal-spec.md`](../v1/informal-spec.md) Part 2 (F1 to F11, FP1 to FP6, FN1 to FN6) and fixes what was vague or broken there. Anything not in the sources is marked **new in v2 draft**. Open choices and the defaults taken are in [`QUESTIONS.md`](QUESTIONS.md).

Ids from v1 keep their meaning: C1 to C25, CP1 to CP5, CN1 to CN7 (informal-spec Part 1), M and V (`../v1/server/spec.md`), gaps 1 to 10 (`../v1/README.md`, Findings).

**What v2 claims, and what it doesn't.** Nobody in the middle decides the result. Anyone holding the record and the two keys can recheck it. The rule rejects silence, and a gain trick like v1's tone stops working. It does not claim "proven proximity". A device still signs its own half (CN1). A NEAR without a proof means two keys signed two numbers. A helper next to the partner still wins (CN4, CN5).

## 1. Parties and trust

- **A, B.** Two devices. A makes the invite (host), B joins it (guest). Each has a signing key `sk_A`, `sk_B` with public keys `pk_A`, `pk_B`. Each has a person who taps confirm.
- **Mailbox.** Moves bytes between A and B. Trusted for nothing. It can drop, delay, reorder, replay and duplicate. It can't forge a signature.
- **Reader.** Anyone who gets a record and checks it later. Knows the two keys it cares about from somewhere else.
- **Nothing in the middle.** No seed holder, no verdict signer, no issuer, no attestation service (decision 3: every key is just a key).

**Attacker.** One dishonest device D. D runs any code, holds its own key, controls the mailbox, and sees every message. It can't sign with the honest device's key, and can't find hash collisions. Plus a passive outsider who reads the mailbox and changes nothing. Two dishonest devices are out of scope: together they can sign anything.

**Assumptions, all named, none an axiom.**

- **SIG.** Signatures can't be forged: a valid signature under `pk_X` on a message means X signed that message.
- **HASH.** `H` has no collisions we can find. Lean takes this as "H is injective" on the inputs used.
- **HIDE.** `H(blind ‖ x)` with a fresh random 32-byte `blind` tells nothing about `x`. The same for a seed commit `H("seed" ‖ ... ‖ seed)`, since the seed is 32 random bytes. And the code key derivation (F3) behaves like a random function of the seed, as v1's server spec assumed for `bed_key` (A6). Used by FP2's "can't steer" reading and by FP3. Not modeled in Lean, stated.
- **RAND.** An honest device's random values (`r`, `seed`, `salt`, `blind`) are fresh and unknown to D until sent.
- **OOB.** The invite QR or NFC tap (F1) reaches B unchanged. It is the only channel that is not the mailbox.

## 2. Messages

### 2.1 Common form (new in v2 draft)

Every mailbox message is one signed record:

```
m   = tag ‖ sid ‖ role ‖ attempt ‖ peer ‖ body
sig = Sign(sk_role, "pop-p2p-v2" ‖ m)
```

- `tag` names the message kind, so a signature on one kind is useless as another (v1 had this by layout, D1 in the server spec; the draft didn't say).
- `sid`, `role`, `attempt` bind the message to one session, one sender role, one attempt.
- `peer = H(seen)`, where `seen` is the set of every partner message the sender has accepted so far in this session, written as their hashes in sorted order. A device that has accepted none puts `sid`. The receiver checks that `peer` is `H` of some subset of its own sent messages, and that this subset holds at least the message named in the "answers" column below. A set, not a list, because the mailbox may reorder: a partner can accept a `FAIL` before a delayed `TXC`. This makes the record a chain: once the honest device has answered, D can't swap any earlier message of its own and still show a valid record. See hole K1.

On receipt, an honest device always checks, in this order: the tag is one it expects now, the signature verifies under the partner's key, `sid` is its own, `role` is the partner's role, `attempt` is its current attempt, `peer` passes the check above. `JOIN` is the exception: it has no `sid` yet, so A checks only its signature under the `pk_B` it carries and the body checks in the table. A message that fails any of these is **dropped** and changes nothing (the mailbox may carry junk and replays). A message that passes these but fails a body check is **final**: the device signs `FAIL` with that reason, stops the session, and the outcome is NOT_NEAR. The one exception is `TIME`, whose failure is a retry reason (F4). This mirrors v1, where a bad commit changed nothing (C14) and a bad transcript was final (C17).

An exact duplicate of a message already accepted is dropped, so a replay can't move a device twice. A device accepts at most one partner message per slot `(role, attempt, tag)`. Once a slot is filled, the tag is no longer one it "expects now", so a second, different message for it is dropped.

A message dropped by these checks, or one that failed a body check, is not **accepted**. It goes into neither `seen` nor the record.

**Resend (new in v2 draft).** A device resends its own messages for the current attempt, the same bytes, until the partner's answer to each arrives or the session ends. Its `FAIL` for attempt k keeps being resent after it moves to k + 1, until a partner message for k + 1 arrives. A resend is not a new message: the device signs each message once, and the record holds each signed message once. Duplicates are dropped, so this is safe. It only matters for liveness: a message for attempt k + 1 that arrives while the receiver is still on k is dropped, and comes again later.

`JOIN` travels in the clear: it holds only public keys and randoms. Every later payload is encrypted with a key from `ECDH(sk_self, pk_partner)` and `sid`, so after `JOIN` the mailbox reads only a box id, sizes and times (new in v2 draft, QUESTIONS Q13). From `JOIN` it does learn both keys, both randoms and `ctx`. Encryption is not part of any property below and isn't modeled.

### 2.2 Session messages

| Step | Kind | From | Body | answers | Honest sender sends when | Receiver body checks, failure |
|---|---|---|---|---|---|---|
| F1a | `INVITE` (QR/NFC, not signed, not mailbox) | A | `pk_A`, `r_A` (32 random bytes), `ctx`, box id | none | A's person asked to pair | B: well-formed, `pk_A != pk_B`. Else B ignores it. |
| F1b | `JOIN` | B | `pk_A`, `pk_B`, `r_A`, `r_B` (32 random bytes), `ctx` | INVITE | B read an invite, B's person accepted it | A: `pk_A`, `r_A`, `ctx` are this invite's, the invite is unused and under 120 s old (C6), `pk_B != pk_A`. Else drop. |

Then `sid = H("pop-p2p-v2" ‖ pk_A ‖ pk_B ‖ r_A ‖ r_B ‖ ctx)`. `sid` takes the 32-byte `session_nonce` slot in POPC and POPT, so the layouts stay. A `JOIN` has no `sid` field, its signature is on the body. Its role is B and its attempt 0.

Both screens then show the partner and the person taps confirm (C8). No message is needed. An honest device sends nothing for attempt 0 before its own person confirmed.

**Who checks whom.** B checks A's key: it came by the invite (OOB). A checks B's key only through its person's confirm tap. This is C7 as today: only the guest checks the host's key. Under the attacker above it's enough: if B is dishonest, B's key is just the key A measured with. It isn't enough against an active outsider on the mailbox (hole K6, Q9).

### 2.3 Attempt messages, for attempt `k` in {0, 1}

Each device has a sample rate `sr` (36000 to 96000, C10). Constants as today: A plays at `t0`, B at `t0 + 0.95 s`, each captures 2.5 s from `t0 - 0.5 s` (C12). So the sounds are over at `t0 + 1.2 s` and the capture at `t0 + 2.0 s`.

| Step | Kind | From | Body | answers | Honest sender sends when | Receiver body checks, failure |
|---|---|---|---|---|---|---|
| F2 | `SEEDC` | both | `hs = H("seed" ‖ sid ‖ role ‖ k ‖ seed)`, own `sr` | k = 0: none. k = 1: partner FAIL for 0 | k = 0: confirmed. k = 1: both FAILs for 0 held (F10) | `sr` in 36000..96000. Else final, `transcript_mismatch`. |
| F3 | `SALT` | both | `salt` (32 random bytes) | partner SEEDC | holds partner `SEEDC` for k | none beyond 2.1 |
| F4 | `TIME` | A | `t0` (A's wall clock, ms) | B's SALT | holds B's `SALT` for k. Picks `t0 = now + 5 s` | B expects `TIME` only once it holds A's `SALT` for k (before that it is dropped, and comes again by resend). B: `now_B + 1 s <= t0 <= now_B + 30 s`. Else B signs `FAIL(time)`, a retry reason. |
| F5 | `RECC` | both | `rec_root` (the v2 recording commit, as POPC v2) | A: B's SALT. B: A's TIME | holds partner `SALT` for k, and own capture over: own clock `>= t0 + 2.0 s` | none beyond 2.1 |
| F6 | `REVEAL` | both | `seed` | partner RECC | holds partner `RECC` for k, and sent its own (so its clock is past `t0 + 2.0 s`) | `H("seed" ‖ sid ‖ partner role ‖ k ‖ seed) = partner hs`. Else final, `seed_mismatch`. |
| F7 | (local) | both | | | holds partner `REVEAL` | own and partner arrival by rule R2 (section 5). A local failure gives `FAIL` with a retry reason (C13). |
| F8a | `TXC` | both | `c = H("tx" ‖ blind ‖ t ‖ sig_t)` | partner REVEAL | F7 gave a half | none beyond 2.1 |
| F8b | `TXO` | both | `blind`, `t`, `sig_t` | partner TXC | holds partner `TXC` for k | see below. Any failure is final, `transcript_mismatch` or `signature_invalid`. |
| F10 | `FAIL` | either | `reason` | the last accepted partner message, if any | a local failure, a timeout, a partner's retry `FAIL`, or a final check failed. See F10. | none. Recorded. |

**Codes (F3, new detail).** `key_X = H("bed" ‖ sid ‖ role_X ‖ k ‖ seed_X ‖ salt_Y)` where Y is X's partner. The code a device plays is `render(key_X, role_X, sr_X)`. The partner code a device listens for is rendered at its own rate: Y renders `render(key_X, role_X, sr_Y)`. That is why `sr` is signed in F2, before anything is revealed (hole K8). `render` must be bit-exact on every platform and in the reader (hole K9). A device can't render its own code before it holds the partner's `SALT`, so it never plays, captures, sends `RECC` or `REVEAL` for k without it. Otherwise its seed could go out before the salt that fixes its code, and D could pick the salt afterwards.

**Transcript (F8).** `t` is a POPT v2 transcript (`docs/pop-transcript-v2.md`), with `session_nonce = sid`. `sig_t = Sign(sk, t)` is the same POPT signature the circuit checks. The receiver checks, in order: `c = H("tx" ‖ blind ‖ t ‖ sig_t)` for the partner's `TXC`; `sig_t` verifies under the partner key; `t.pk_self` is the partner key, `t.pk_partner` its own; `t.role`, `t.nonce = sid`, `t.attempt = k`; `t.sample_rate` is the partner's signed `sr`; `t.rec_root` is the partner's `RECC` root and `t.commit_hash = H(partner RECC)`; `t.delta = delta(sr)`; `t.code_commit` equals `popt2.code_commit` (Poseidon2, as the code does today, not the sha256 line in `docs/pop-transcript-v2.md`) of the two codes it derives itself at the partner's rate. This is C17 with the server's stored values replaced by signed messages. `half`, `self_os_delta`, `a_self`, `p_partner` and the play times stay free, as in V6.

**F9, verdict.** Local and pure, section 4.

**F10, failures and retry (changed from C22, new in v2 draft).** A device signs `FAIL(reason)` for attempt k:

- before it sent its own `TXO` for k: on a local measurement failure (`capture_failed`, `glitch`, `self_not_heard`, `self_timestamp_mismatch`, `partner_not_heard`), on `time`, on a partner's retry `FAIL` for k (it answers with `FAIL(partner_failed)`, also a retry reason), or on `timeout` (no progress by its own `t0 + 20 s`, or 60 s after its last new message, resends not counted, before `t0` exists). These are retry reasons.
- on any final check failure above, at any point. These are final.
- after it sent its own `TXO` for k: only on a final check failure. It never signs a timeout after opening. If the partner's `TXO` never comes, the device stops at session end with the attempt incomplete (FN1). This keeps two honest devices from disagreeing when the mailbox is slow: one can't hold NEAR while the other signed a failure.

A device signs at most one `FAIL` per attempt. If it already signed one, a partner `FAIL` for k only completes the pair: it signs no `partner_failed` answer. After signing a retry `FAIL`, a device waits, up to session end, for the partner's `FAIL` for k. Attempt k + 1 starts only when `k + 1 < 2` and the device holds a retry-reason `FAIL` for k from both sides and it has not sent `TXO` for k. Otherwise the session ends. So `impossible_flight` and a partner's `self_timestamp_mismatch` found by F9 are final in v2 (C22 retried them). The reason is hole K3: once a half is open, a retry hands the partner a number it can use. New seeds, salts and `t0` for each attempt.

A session also ends after 600 s on the device's own clock (C6).

**F11, record.** For the session: `INVITE`, `JOIN`. For each attempt held: the device's own sent messages and the partner messages it accepted, each with its signature, in order. Nothing that was dropped or failed a body check goes in. A `FAIL(seed_mismatch)` stands alone: the bad `REVEAL` it answers is not in the record. Since `seed`, `salt`, `sr` are inside, a reader can rederive both codes and check `code_commit`, which `verify_record` can't do today (`verdict.py:174`). Proofs, if any, ride along (decision 2). The record holds no audio and no `cal_us`.

## 3. What the server did, and what does it now

| Server job (C rule) | Where it goes in v2 | Who enforces it | Changes |
|---|---|---|---|
| Join token, session age (C6) | Invite under 120 s, used once, checked by A at `JOIN`. Session age on each device's own clock | each honest device | No shared clock. A dishonest device keeps no timer. |
| Guest checks host key (C7) | B checks `pk_A` from the invite | B | A only has the confirm tap (K6). |
| Both confirm, World ID (C8) | Each person taps confirm on their own device | each honest device | World ID is out (FN4, roadmap out of scope). |
| State order (C9) | Each device's state machine, the "sends when" column | each honest device | Order binds honest devices only. |
| Arm: attempt, rate, t0 (C10) | `sr` in `SEEDC` (F2). `t0` in `TIME` (F4) | receiver checks `sr` range, B checks `t0` bounds | RTT check gone. `t0` is completeness only: no property reads it (CP4: the offset cancels). |
| Secret sounds, `bed_key` from the seed (C11) | Seed commit, salt, reveal (F2, F3, F6), codes from `key_X` | both | Within an attempt a device can't pick its code (FP2). Over a session it gets two draws, by failing attempt 0 on purpose (K16). The generator must be ported bit-exact (K9). |
| Play and capture schedule (C12) | Same | app | none |
| Own arrival (C13) | Rule R2 | app, circuit | Rule changes (section 5). |
| Commit after the schedule, signed, right role, attempt, nonce (C14) | `RECC` (F5) sent after own capture | honest sender | A receiver can't check the partner's timing over a mailbox, and doesn't need to: the reveal gate (F6) is what CP1 needs. |
| Partner code only after own commit (C15) | `REVEAL` only after holding the partner's `RECC` and sending its own, after its own capture | honest sender | Now both directions are gated by the honest side. (FP1) |
| Measure (C16) | F7 | app | none |
| Transcript checks (C17) | `TXO` receiver checks (F8) | each honest device, and the reader | Stored server values become signed messages. |
| Blind half (C18) | `TXC` then `TXO` (F8) | honest sender | Last opener holds the full record (FN1). Retry after opening is gone (K3). |
| Verdict (C19, C20, C21) | F9, same math, section 4 | both devices, any reader | `cal_us` gone (v2 transcripts only). |
| Retries and deadline (C22) | F10 | each honest device | Retry only if nothing was opened. |
| Record and replay (`verify_record`, V7) | F11, section 4 | any reader | Codes can be rechecked. Reader must pin keys. Reader must compare the stated verdict (V7 hole). |
| Proofs after NEAR (C23) | Optional, carried in the record | the reader decides (decision 2) | The circuit's issuer input goes (roadmap stage 4). |
| Chain attestation, Safe, ENS (C24, C25) | Out: examples with their own backends | | |
| Device vouching (C2 to C5) | Nothing (decision 3) | | Every key is just a key (FN2). |

## 4. The verdict

The v1 math is kept as is (`server/pop/verdict.py`, V1 to V4). Only v2 transcripts exist, so every self check runs with `cal = 0`: the app folds its calibration into `p_self` before signing, so `self_os_delta` is already the residual (`verdict.py:13-16`). This is the `cal_us` choice. The record carries no `cal_us`, which also removes the unsigned-`cal_us` hole of V7.

`Outcome(record, k)` for the last attempt k in the record, a pure function:

1. If a `FAIL` for k is in the record: NOT_NEAR. The reason is A's `FAIL` reason if A signed one, else B's. Fixed order, so arrival order doesn't matter.
2. Else, if both `TXO` for k are in the record and pass the F8 checks against the rest of the record: `combine(t_A, t_B)` with cal 0, always A's transcript first. That gives NEAR, NOT_NEAR `too_far`, or no verdict with `impossible_flight` or `self_timestamp_mismatch`. In v2 the last two are final, so they read as NOT_NEAR with that reason.
3. Else: incomplete. A reader treats it as no NEAR.

`combine` is C19 (roles A and B, same `sid` in the nonce slot, same attempt, keys crossed and different), C20 (`|self_os_delta| <= 50 ms` at the signed rate, both edges in) and C21 (exact rational flight; `<= -20` impossible, `>= 60` too far, NEAR between, ties as in `Pair.lean`). It returns the same thing on both devices because it reads only the two transcripts, in role order.

A NEAR says: two keys signed two transcripts for this `sid` and attempt, and the numbers in them fall in range. With a proof attached it says more, as far as the circuit goes (`../v1/README.md`, "What `presence_sound` says").

`verify(pkA, pkB, record)` for a reader: the record's keys must equal the ones the reader pinned; one `INVITE` and one `JOIN`, and at most one message per slot `(role, attempt, tag)`; every signature checks; every `peer` is `H` of a set of the partner's messages in the record that holds the named one; every seed opens its `hs`; `code_commit` is rederived; then `Outcome`. A `FAIL`'s signature is checked, its reason is not. A `verdict` field written into the record is compared, never trusted. `verify` returns the `sid` with the outcome, so a reader that expects one session can compare it.

Without the one-per-slot check K1 comes back: D could keep its first `TXC`, which the honest `TXO` names, and add a second `TXC`, `TXO` pair holding a half picked after seeing the honest one. With it, D's only `TXC` must be the one the honest `peer` hashes over (HASH).

`verify` judges the record it is shown. It can't tell that the record is the whole session: D can drop a later attempt, and an attempt 1 NEAR becomes the attempt 0 NOT_NEAR. This only goes one way. A retried attempt was never opened, so it is always NOT_NEAR. And D can reach NOT_NEAR anyway by adding its own `FAIL` (K12).

## 5. The detection rule R2

Today the rule takes loudness through the FIR filter and the match from raw samples (gap 2), and lets zero loudness pass (gap 1). R2 is `../v1/next-version-fixes.md` fixes 1, 2 and 3 together.

**Inputs at one lag.** `w` = the recording, centered (`x - 32768`), read at `n + T - 1` positions from the window start, with `T = 63` taps. `y[m] = Σ_t h[t] · w[m + t]` for `m < n` (`n = L`, 12000 at 48 kHz), the same FIR as `yI` in `PartnerGlue.lean`. So `y` reads `T - 1` samples past the window, from the real recording, never zero padding the window itself. `ci`, `cq` = the code templates, centered (`c - 128`), length `n`.

```
I   = Σ ci[m] · y[m]          Q = Σ cq[m] · y[m]          (was: on w, the raw window)
E   = Σ y[m]^2                                             (same as v1)
cn2 = Σ ci[m]^2 + Σ cq[m]^2                                (was: Σ ci^2 only)
M   = I^2 + Q^2
Pass(BAR, FLOOR) :=  E · cn2 >= FLOOR   and   BAR · M >= E · cn2
```

All integers. `I`, `Q` and `E` must sum over the same `y[m]`. `FLOOR >= 1`. `BAR >= 1`.

- **Self side.** The arrival is the first lag in the self window where `Pass` holds. A lag that fails either part counts as "not yet". (In v1 a lag was "not yet" only when `BAR · M < E · cn2`.)
- **Partner side.** Some lag in the partner window passes, at the lag the transcript names. "Any passing lag", as in v1 (gap 6, fix 6, kept, Q17).

**Parameters.** `BAR`, the taps `h`, `FLOOR` and the bit widths are not fixed. Stage 3 of the roadmap (real recordings) sets them. Fix 1 guesses about 123 (`1 / 0.09^2`). Adding `cq` to `cn2` roughly doubles the denominator, so keeping the same correlation bar would need about twice that. Neither is checked. Every theorem below is stated for any `BAR`, any `h`, any `FLOOR >= 1`.

**Must agree, bit for bit:** the `phone` circuit (`oalib` `self_side`, `partner_side`), the app (`Popt2Rule.kt`, `earliest` and the partner check) and the Python reference (`server/pop/popt2.py`). Same `h`, `BAR`, `FLOOR`, window alignment, `cn2` with `cq`, and integer widths. The app is the live path: without a required proof, the circuit-only fix leaves the stock app still running the old rule (fix 1, "Must match").

## 6. Properties, as they'll be modeled

**Model shape.** One honest device is a state machine: `step : State → Input → State × List Msg`. An input is any message (the attacker), a clock tick, a local result (capture done, measurement, person tapped). Clock ticks only move forward: the attacker controls the mailbox, not the honest device's clock. Properties FP1 to FP4 hold for every input sequence with forward ticks. FP5 and FP6 are lemmas about the pure functions `Outcome` and `verify`, not two-device simulations. `H` and `Sign`/`Verify` are abstract, with HASH and SIG as hypotheses or structure fields. Plain Lean core for the protocol. One property per file.

### Protocol

**FP1, order.** For every input sequence: if the honest device sends `REVEAL` for attempt k, it had already accepted a partner `RECC` and a partner `SALT` for (sid, k) and sent its own `RECC`, and when it sent that `RECC` its clock was past `t0 + 2.0 s`.
*Assumes:* forward ticks, for "its clock is still past it now". *Does not give:* that `RECC` commits to real audio (CN1, CN2). The code is played out loud anyway, so a mic near the honest device hears it (CN3).

**FP2, fixed code.** If the honest device accepts a partner `REVEAL(seed)` for k, then `H("seed" ‖ sid ‖ partner role ‖ k ‖ seed)` equals the `hs` it accepted for k. It sent its own `SALT` for k only after accepting that `hs`. Under HASH, at most one seed is ever accepted for (sid, k), so the partner's code has one value.
*Assumes:* HASH. RAND and HIDE for "D couldn't steer its code within the attempt", which is reasoning, not a theorem. Over a session D gets a second draw by failing attempt 0 on purpose (K16). *Does not give:* that a derived code is a good code. The floor in R2 rejects a zero-energy template (RS), so the all-128 code of gap 5 can't pass even if derived.

**FP3, blind half.** The honest device sends `TXO` for k only after it accepted the partner's `TXC` for k. After sending `TXO` for k it sends nothing for attempt k + 1.
*Assumes:* HIDE, stated, not modeled. *Does not give:* that the half is true (CN1). It doesn't stop the half leaking into a later session with the same partner (K4), or devices sharing numbers outside the protocol. The last opener still holds the full record (FN1).

**FP4, freshness.** Every message after `JOIN` that the honest device accepts carries its current `sid`. A's `JOIN` check pins its own fresh `r_A`. `sid` contains its own fresh `r`. So under HASH, if its `r` differs from the one in an old record, no message of that record is accepted. (A reader sees the old `sid` in `verify`'s result; whether it wanted that `sid` is up to the reader, FN3.)
*Assumes:* HASH, RAND. *Does not give:* replay protection at a reader. A consumer has to mark `sid` as used (FN3).

**FP5, agreement.** Two pieces, neither a two-device simulation.
(a) A lemma about the pure function: `Outcome` step 2 reads only `(t_A, t_B)`, in role order, so equal pairs give equal outcomes.
(b) A single-device invariant: an honest device signs at most one `TXO` per k (resends are the same bytes), and the partner `TXO` it accepts opens the one partner `TXC` it accepted. After its own `TXO` it signs a `FAIL` for k only on a final check failure.
On paper: if both devices are honest, each `TXO` one accepts is the only one the other sent (b, twice, plus HASH). So both hold the same pair, and by (a) the same outcome. An honest partner never fails a final check, so the only other case is one device complete and the other incomplete, never NEAR against NOT_NEAR.
*Assumes:* HASH. *Does not give:* that the honest device learns the outcome when D walks away after the last opening (FN1).

**FP6, third-party check.** For keys the reader pinned: `verify` returns `Outcome` of the record when every check passes, and rejects otherwise. Changing any message without the signer's key fails (SIG). D re-signing one of its own messages fails once a later honest message carries it in `seen`, or once it is fixed by D's own `TXC` (HASH). With the one-per-slot check, in a record that holds the honest device's `TXO` for k, every one of D's messages for k up to its `TXC` is the one the honest device accepted, and the content of D's `TXO` (`blind`, `t`, `sig_t`) is fixed by that `TXC`. D's `FAIL`s are fixed by nothing: D can add one and turn its own record into NOT_NEAR, which is X2.
*Assumes:* SIG, HASH, reader-pinned keys. *Does not give:* anything about the air, or who holds a key (decision 3). A NEAR record does not mean the honest device saw NEAR. D can send a bad `TXO` to the honest device, which then signs a final `FAIL`, and later show a reader a record with its good `TXO` and without that `FAIL`. That is FN1 in another shape (K10). The honest person did confirm the session.

### Rule

**RC, score ceiling.** For any `y`, `ci`, `cq` of the same length: `M <= E · cn2`. So `M / (E · cn2) <= 1` whenever `E · cn2 > 0`. Proof: Cauchy–Schwarz on `I` and on `Q`, added.
*Assumes:* `I`, `Q`, `E` over the same `y`, and `cq` inside `cn2`. Without `cq` in `cn2`, it fails: one nonzero `ci` and a large `cq` give any score. *Does not give:* that noise fails. How often noise passes depends on `BAR` and the codes (stage 3).

**RS, silence rejected.** If `y = 0` everywhere, `Pass` is false. Since the filter is linear, digital silence (`w = 0`) gives `y = 0`. If `cn2 = 0` (all-128 templates), `Pass` is false for every recording.
*Assumes:* `FLOOR >= 1`. *Does not give:* that quiet sound fails. The 48 kHz taps sum to 3 and the 44.1 kHz taps to 1, not 0 (`popt2.py` `RATES`). So a constant offset of one step gives `E > 0` and, with `FLOOR = 1` and a nonzero template, passes the floor (K11). It is judged by the ratio test alone.

**RT, gain cancels.** For any integer `g != 0`: `BAR · M(g·y) >= E(g·y) · cn2` iff `BAR · M(y) >= E(y) · cn2`. Both sides scale by `g^2`. So the filter's gain at one frequency drops out, and the v1 tone's route (match through gain 1, loudness through gain 0.14, about 1,400 times too high a score) is gone: by RC no score is above 1.
*Assumes:* nothing. *Does not give:* that a 500 Hz tone fails. That is now a plain correlation between the tone and the code, which depends on the code and phase. It is checked by rerunning `circuit-cases` and the stage 3 recordings, not in Lean. The floor part of `Pass` is not scale-free, on purpose.

**What v1 theorems flip.** `Bar.partner_silence_accepts` and `self_silence_accepts` should become false under R2 (RS). The tone witness was a `circuit-cases` run, not a theorem, so it flips in `nargo`, not in Lean.

## 7. Known holes

Found while reviewing Part 2. K1, K2, K3, K5, K7, K8 are fixed above. The rest stay open.

- **K1, equivocation (fixed by `peer`).** In the draft, nothing the honest device signed named D's messages. D could open its half after seeing the honest one, then sign a new `TXC`, `TXO` pair with another half, and show a reader a record that verifies. Same trick at F5 after learning the honest seed: sign a new recording commit. Each honest message now carries `H` of every partner message it has accepted (`seen`). This needs the one-per-slot rule, live and in `verify` (section 4), or D just keeps both commits in the record.
- **K2, F8 could be brute-forced (fixed by `blind`).** The draft hashed `transcript ‖ sig`. The partner already knows most transcript fields (keys, `sid`, rate, `rec_root` from F5, `code_commit` after F6). The half is a small integer. Hiding then rested only on the signature being unpredictable. A random `blind` makes it explicit.
- **K3, a retry after opening leaks the half (fixed by F10).** In v1 the server hid the number on retry (M6). In the draft, after both `TXO`s D knows the honest half, can force `impossible_flight` or just stop (timeout was a retry reason), and attempt 1's honest half is within jitter of attempt 0's. Now nothing retries once the honest device has opened.
- **K4, the half leaks across sessions.** Any finished record shows both halves. D can start a new session with the same partner and use the old half. v1 had this too ("not studied", M6). Each new session needs the honest person's confirm tap. Open.
- **K5, no domain separation (fixed by the common form).** The draft didn't say what each signature covers. A seed commit without `sid`, role and attempt could be copied from the partner or replayed.
- **K6, pairing is one-way.** A gets B's key only over the mailbox. With one dishonest device that's fine. An active outsider on the mailbox could drop B's `JOIN` and send its own, so A measures with the outsider's key while B gets nothing. Only A's person's confirm tap stands in the way. Two-way NFC, or a second QR, closes it (Q9). The draft said "both devices check the other's key" without a channel for A.
- **K7, timing is local (fixed by saying so).** No receiver can check the partner's clock. Every gate is on the honest sender's own clock. `t0` only matters for completeness.
- **K8, the rate must be signed before the reveal (fixed in F2).** Codes are rendered at the listener's rate (`popt2.py`, `_code_commit` in `sessions.py`), so a reader needs both rates to recheck `code_commit`.
- **K9, the generator isn't portable.** `popt2.py` says a phone can't reproduce the FFT path bit for bit. Devices and readers must derive the same templates, or `code_commit` can't be rechecked and honest devices will disagree. Needs an integer generator (roadmap stage 5). Open.
- **K10, FN1 stays.** The last device to open holds the full record. D can keep a NEAR record the honest device never got. The honest person did confirm the session, so D can't make one without them.
- **K11, the floor only catches exact silence.** `FLOOR = 1` rejects `y = 0`. The taps sum to 3 (48 kHz) and 1 (44.1 kHz), so any DC offset has energy. The click (gap 3) and very quiet noise are left to the ratio test. A higher floor is a stage 3 question (fix 2, "Consider").
- **K12, either device can end a session NOT_NEAR (X2 stays).** `FAIL` needs nothing from the partner. NOT_NEAR is no finding about distance. Dropping a later attempt from the record does the same (section 4): a record can't prove it is the whole session.
- **K13, circuit gaps 6 to 10 stay.** Partner side is "loud enough", not "first". A window past the capture end is no longer silence-safe to pass: if its whole filter span is padding, `E = 0` and RS rejects it. One that straddles the end still reads padding, and the transcript still has no capture length. Some signed fields are never read by the circuit. The partner key isn't checked in-circuit. Public inputs must be pinned by whoever verifies, now including the two keys and `code_commit`. Roadmap stage 4 picks which to fix.
- **K14, the self timing check binds honest devices only.** `self_os_delta` is reported, not recomputed (C20). Unchanged from v1.
- **K15, the mailbox sees metadata.** Even encrypted, it sees who talks to whom, when, and how much. Not studied.
- **K16, two draws of a code per session.** D sees its own code once it holds the honest `SALT`, and the honest code once it holds the honest `REVEAL`. Before any `TXO`, it can sign `FAIL(capture_failed)` (or, as A, send a bad `t0`) and get fresh seeds and salts in attempt 1. So D can pick the better of two codes, its own or the honest one. Not unlimited: the honest salt still comes after D's seed commit, and there are only two attempts. One attempt per session closes it, at the cost of completeness (Q19). Open.

## 8. Review log

**2026-11-10, attack pass.** Codex (gpt-6-astra, high, read-only) was asked to break this spec as one dishonest device that also runs the mailbox. Eight findings. Each was checked against the text here.

- **Confirmed, fixed.**
  1. Two `TXC`s from D in one record: `verify` had no one-per-slot check, so K1 came back. Now one message per `(role, attempt, tag)`, live and in `verify`.
  2. Code grinding through retries: bounded to two draws per session. Wording in section 3 and FP2, new hole K16, Q19.
  3. No salt gate at B: B could take `TIME` and reveal before holding A's `SALT`, so D could pick the salt after seeing B's seed. Now nobody plays, captures, commits or reveals without the partner's `SALT`.
  5. FP1 needed forward clock ticks. FP5 needed a single-device invariant next to the pure lemma. FP4 claimed something about `verify` it has no input for. All three restated; `verify` now returns the `sid`.
  6. A reordered first message of attempt 1 was lost for good. Resend rule added.
  7. The record didn't say whether rejected messages go in. Now: own sent plus accepted only. A `FAIL`'s reason is not checked by the reader.
  8. B didn't check `pk_A != pk_B`. Added.
- **Rejected as a new break.** 4, dropping attempt 1 from the record. It only turns NEAR into NOT_NEAR, which D can already do with its own `FAIL` (K12). Noted in section 4 and K12.
- **Checks that passed.** Skewing `t0` (only A sets it, B bounds it, every gate is on the own clock), a garbage `RECC` (CN1, as listed), replay across sessions, attempts and roles, reflection of A's messages as B's, `JOIN` replay, and invite reuse.

**Re-check of the changes.** Three findings, all confirmed and fixed. The resend rule lost a dropped retry `FAIL` once the sender had moved to attempt 1: a `FAIL` is now resent until a partner message for the next attempt arrives. FP5's "sends one `TXO`" clashed with resends: now "signs one", and a record holds each signed message once. Two `FAIL`s from one device in one attempt broke one-per-slot: a device now signs at most one `FAIL` per attempt. These last fixes had no further Codex pass.
