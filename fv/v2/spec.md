# v2 spec: the protocol without the server, and the fixed rule

Stage 2 of [`../ROADMAP.md`](../ROADMAP.md). Nothing here is built: there is no device code and no circuit. The Lean models in [`protocol/`](protocol/README.md) and [`zkp/`](zkp/README.md) follow this file.

It starts from [`../v1/informal-spec.md`](../v1/informal-spec.md) Part 2 (F1 to F11, FP1 to FP6, FN1 to FN6) and fixes what was vague or broken there. Open choices and the defaults taken are in [`QUESTIONS.md`](QUESTIONS.md).

The direct WebRTC link and the words used here come from [ADR 0001](adr/0001-direct-webrtc-link-and-plain-words.md). The ADR has the table of old and new words.

Ids from v1 keep their meaning: C1 to C25, CP1 to CP5, CN1 to CN7 (informal-spec Part 1), M and V (`../v1/server/spec.md`), gaps 1 to 10 (`../v1/README.md`, Findings).

**What v2 claims, and what it doesn't.** Nobody in the middle decides the result. Anyone holding the log and the two keys can recheck it. The rule rejects silence, and a gain trick like v1's tone stops working. It does not claim "proven proximity". A device still signs its own gap (CN1). A NEAR without a proof means two keys signed two numbers. A helper next to the partner still wins (CN4, CN5).

**Warning (K3).** A device that sends a wrong gap or a wrong self timing on purpose can force a retry, and in the retry it already knows the honest gap. Against such a device, sending the hash of the gap first protects nothing. The owner accepts this (Q8): v2 does not expect modified apps, and an implementer who does can add attestation (Q3).

## 1. Parties and trust

- **A, B.** Two devices. A makes the invite (host), B joins it (guest). Each has a signing key `sk_A`, `sk_B` with public keys `pk_A`, `pk_B`. Each has a person who taps confirm.
- **Link.** A WebRTC data channel between A and B, set up by two QR codes (F1). No server carries messages. The link is reliable and ordered, and WebRTC encrypts it. No property depends on that: the model lets a dishonest device send any message at any time.
- **Reader.** Anyone who gets a log and checks it later. Knows the two keys it cares about from somewhere else.
- **Nothing in the middle.** No forwarding server, no seed holder, no verdict signer, no issuer, no attestation service (decision 3: every key is just a key).

**Attacker.** One dishonest device D. D runs any code, holds its own key, and sends the honest device any message at any time, in any order, or none. It can't sign with the honest device's key, and can't find hash collisions. Plus an outsider on the same network, who sees encrypted packets between two local addresses. WebRTC checks each side's certificate against the fingerprint in the QR code, so the outsider can't join the link without changing a QR code (OOB). Two dishonest devices are out of scope: together they can sign anything.

**Assumptions, all named, none an axiom.**

- **SIG.** Signatures can't be forged: a valid signature under `pk_X` on a message means X signed that message.
- **HASH.** `H` has no collisions we can find. Lean takes this as "H is injective" on the inputs used.
- **HIDE.** `H(blind ‖ x)` with a fresh random 32-byte `blind` tells nothing about `x`. The same for a seed hash `H("seed" ‖ ... ‖ seed)`, since the seed is 32 random bytes. And the code key derivation (F3) behaves like a random function of the seed, as v1's server spec assumed for `bed_key` (A6). Used by FP2's "can't steer" reading and by FP3. Not modeled in Lean, stated.
- **RAND.** An honest device's random values (`r`, `seed`, `salt`, `blind`) are fresh and unknown to D until sent.
- **OOB.** Both QR codes reach the other device unchanged: A's `INVITE` reaches B, and B's `JOIN` reaches A (F1). They are the only messages that don't travel on the link.

## 2. Messages

### 2.1 Common form

Every message on the link has this signed form:

```
m   = tag ‖ sid ‖ role ‖ attempt ‖ peer ‖ body
sig = Sign(sk_role, "pop-p2p-v2" ‖ m)
```

- `tag` names the message kind, so a signature on one kind is useless as another (v1 had this by layout, D1 in the server spec; the draft didn't say).
- `sid`, `role`, `attempt` bind the message to one session, one sender role, one attempt.
- `peer = H(seen)`, where `seen` is the set of every partner message the sender has accepted so far in this session, written as their hashes in sorted order. A device that has accepted none puts `sid`. The receiver checks that `peer` is `H` of some subset of its own sent messages, and that this subset holds at least the message named in the "answers" column below. A set, not a list: the check asks which messages were accepted, not in what order. This makes the log a chain: once the honest device has answered, D can't swap any earlier message of its own and still show a valid log. See hole K1.

On receipt, an honest device always checks, in this order: the tag is one it expects now, the signature verifies under the partner's key, `sid` is its own, `role` is the partner's role, `attempt` is its current attempt, `peer` passes the check above. `JOIN` is the exception: it has no `sid` yet, so A checks only its signature under the `pk_B` it carries and the body checks in the table. A message that fails any of these is **dropped** and changes nothing (a dishonest partner may send junk and replays). A message that passes these but fails a body check is **final**: the device signs `FAIL` with that reason, stops the session, and the outcome is NOT_NEAR. The one exception is `TIME`, whose failure is a retry reason (F4). This mirrors v1, where a bad recording hash changed nothing (C14) and a bad transcript was final (C17).

An exact duplicate of a message already accepted is dropped, so a replay can't move a device twice. A device accepts at most one partner message per slot `(role, attempt, tag)`. Once a slot is filled, the tag is no longer one it "expects now", so a second, different message for it is dropped.

A message dropped by these checks, or one that failed a body check, is not **accepted**. It goes into neither `seen` nor the log.

**Resend.** A device resends its own messages for the current attempt, the same bytes, until the partner's answer to each arrives or the session ends. Its `FAIL` for attempt k keeps being resent after it moves to k + 1, until a partner message for k + 1 arrives. A resend is not a new message: the device signs each message once, and the log holds each signed message once. Duplicates are dropped, so this is safe. It only matters for liveness: a message for attempt k + 1 that arrives while the receiver is still on k is dropped, and comes again later. The link is reliable and ordered, so between honest devices a resend only matters for a message the partner dropped as not expected yet, such as one that arrived before the confirm tap.

If the link closes, no further message arrives, so the timeout rules of F10 apply and the session ends. A new link needs new QR codes, and those start a new session.

`INVITE` and `JOIN` are QR codes, so only someone who sees the screens reads them. They hold public keys, randoms and `ctx`. The WebRTC offer and answer travel in the same QR codes. Every later message travels on the link, which WebRTC encrypts, so an outsider on the network reads only addresses, sizes and times. The spec adds no encryption of its own (Q13). Encryption is not part of any property below and isn't modeled.

### 2.2 Session messages

| Step | Kind | From | Body | answers | Honest sender sends when | Receiver body checks, failure |
|---|---|---|---|---|---|---|
| F1a | `INVITE` (QR code, not signed) | A | `pk_A`, `r_A` (32 random bytes), `ctx` | none | A's person asked to pair | B: well-formed, `pk_A != pk_B`. Else B ignores it. |
| F1b | `JOIN` (QR code, signed) | B | `pk_A`, `pk_B`, `r_A`, `r_B` (32 random bytes), `ctx` | INVITE | B scanned an invite, B's person accepted it | A: `pk_A`, `r_A`, `ctx` are this invite's, the invite is unused and under 120 s old (C6), `pk_B != pk_A`. Else drop. |

B scans A's QR code, then A scans B's. A's QR code carries the `INVITE` and, next to it, A's WebRTC offer. B's QR code carries the `JOIN` and, next to it, B's WebRTC answer. The offer and the answer are not part of either message. They are not signed and not in the log, so the log holds no network address.

When A accepts the `JOIN`, the link opens, and every later message travels on it. Both devices must be on the same local network, because the design uses no STUN or TURN server (ADR 0001).

Then `sid = H("pop-p2p-v2" ‖ pk_A ‖ pk_B ‖ r_A ‖ r_B ‖ ctx)`. `sid` takes the 32-byte `session_nonce` slot in POPC and POPT, so the layouts stay. A `JOIN` has no `sid` field, its signature is on the body. Its role is B and its attempt 0.

Both screens then show the partner and the person taps confirm (C8). No message is needed. An honest device sends nothing for attempt 0 before its own person confirmed.

**Who checks whom.** Each device takes the other's key from a QR code it scanned itself (OOB): B from the `INVITE`, A from the `JOIN`. In v1 only the guest checked the host's key (C7). The confirm tap stays (C8). An outsider can't put its own key in place of B's without changing B's QR code, which closes hole K6 (Q9). The WebRTC offer and answer are not part of `sid` or of any signed message, and no property reads them.

### 2.3 Attempt messages, for attempt `k` in {0, 1}

Each device has a sample rate `sr` (36000 to 96000, C10). Constants as today: A plays at `t0`, B at `t0 + 0.95 s`, each captures 2.5 s from `t0 - 0.5 s` (C12). So the sounds are over at `t0 + 1.2 s` and the capture at `t0 + 2.0 s`.

| Step | Kind | From | Body | answers | Honest sender sends when | Receiver body checks, failure |
|---|---|---|---|---|---|---|
| F2 | `SEED_HASH` | both | `hs = H("seed" ‖ sid ‖ role ‖ k ‖ seed)`, own `sr` | k = 0: none. k = 1: partner FAIL for 0 | k = 0: confirmed. k = 1: both FAILs for 0 held (F10) | `sr` in 36000..96000. Else final, `transcript_mismatch`. |
| F3 | `SALT` | both | `salt` (32 random bytes) | partner SEED_HASH | holds partner `SEED_HASH` for k | none beyond 2.1 |
| F4 | `TIME` | A | `t0` (A's wall clock, ms) | B's SALT | holds B's `SALT` for k. Picks `t0 = now + 5 s` | B expects `TIME` only once it holds A's `SALT` for k (before that it is dropped, and comes again by resend). B: `now_B + 1 s <= t0 <= now_B + 30 s`. Else B signs `FAIL(time)`, a retry reason. |
| F5 | `REC_HASH` | both | `rec_root` (the hash of the recording, as in POPC v2) | A: B's SALT. B: A's TIME | holds partner `SALT` for k, and own capture over: own clock `>= t0 + 2.0 s` | none beyond 2.1 |
| F6 | `SEED_VALUE` | both | `seed` | partner REC_HASH | holds partner `REC_HASH` for k, and sent its own (so its clock is past `t0 + 2.0 s`) | `H("seed" ‖ sid ‖ partner role ‖ k ‖ seed) = partner hs`. Else final, `seed_mismatch`. |
| F7 | (local) | both | | | holds partner `SEED_VALUE` | own and partner arrival by the detection rule (section 5). The gap is the number of samples from A's sound to B's sound in the device's own recording (POPT field `half`). A local failure gives `FAIL` with a retry reason (C13). |
| F8a | `GAP_HASH` | both | `c = H("tx" ‖ blind ‖ t ‖ sig_t)` | partner SEED_VALUE | F7 gave a gap | none beyond 2.1 |
| F8b | `GAP_VALUE` | both | `blind`, `t`, `sig_t` | partner GAP_HASH | holds partner `GAP_HASH` for k | see below. Any failure is final, `transcript_mismatch` or `signature_invalid`. |
| F10 | `FAIL` | either | `retry` (one bit: is `reason` a retry reason), `reason` | none | a local failure, a timeout, a partner's retry `FAIL`, a pair that gives `impossible_flight` or `self_timestamp_mismatch`, or a final check failed. See F10. | none. Kept in the log. |

**Codes (F3, new detail).** `key_X = H("bed" ‖ sid ‖ role_X ‖ k ‖ seed_X ‖ salt_Y)` where Y is X's partner. The code a device plays is `render(key_X, role_X, sr_X)`. The partner code a device listens for is rendered at its own rate: Y renders `render(key_X, role_X, sr_Y)`. That is why `sr` is signed in F2, before any seed is sent (hole K8). `render` must be bit-exact on every platform and in the reader (hole K9). A device can't render its own code before it holds the partner's `SALT`, so it never plays, captures, sends `REC_HASH` or `SEED_VALUE` for k without it. Otherwise its seed could go out before the salt that fixes its code, and D could pick the salt afterwards.

**Transcript (F8).** `t` is a POPT v2 transcript (`docs/pop-transcript-v2.md`), with `session_nonce = sid`. `sig_t = Sign(sk, t)` is the same POPT signature the circuit checks. The receiver checks, in order: `c = H("tx" ‖ blind ‖ t ‖ sig_t)` for the partner's `GAP_HASH`; `sig_t` verifies under the partner key; `t.pk_self` is the partner key, `t.pk_partner` its own; `t.role`, `t.nonce = sid`, `t.attempt = k`; `t.sample_rate` is the partner's signed `sr`; `t.rec_root` is the partner's `REC_HASH` root and `t.commit_hash = H(partner REC_HASH)`; `t.delta = delta(sr)`; `t.code_commit` equals `popt2.code_commit` (Poseidon2, as the code does today, not the sha256 line in `docs/pop-transcript-v2.md`) of the two codes it derives itself at the partner's rate. This is C17 with the server's stored values replaced by signed messages. The gap (`half`), `self_os_delta`, `a_self`, `p_partner` and the play times stay free, as in V6.

**F9, verdict.** Local and pure, section 4.

**F10, failures and retry.** A device signs `FAIL(reason)` for attempt k:

- before it sent its own `GAP_VALUE` for k: on a local measurement failure (`capture_failed`, `glitch`, `self_not_heard`, `self_timestamp_mismatch`, `partner_not_heard`), on `time`, on a partner's retry `FAIL` for k (it answers with `FAIL(partner_failed)`, also a retry reason), or on `timeout` (no progress by its own `t0 + 20 s`, or 60 s after its last new message, resends not counted, before `t0` exists). These are retry reasons.
- on any final check failure above, at any point. These are final.
- after it sent its own `GAP_VALUE` for k: on a final check failure, or when it holds both `GAP_VALUE`s for k and F9 gives `impossible_flight` or `self_timestamp_mismatch`. Those two results are retry reasons, as in C22. It answers a partner's retry `FAIL` only in that same case. It never signs a timeout after it sent its `GAP_VALUE`. If the partner's `GAP_VALUE` never comes, the device stops at session end with the attempt incomplete (FN1), or NOT_NEAR if it holds a partner `FAIL` for k. This keeps two honest devices from disagreeing when the link is slow: one can't hold NEAR while the other signed a failure.

The `FAIL` body carries one bit, `retry`, that says whether its reason is a retry reason. A receiver and a reader read that bit, not the reason code (section 4). If the bit and the reason disagree, the bit decides. A `FAIL` answers no message, so the "answers" column says none. Its `peer` still covers every partner message the device accepted.

A device signs at most one `FAIL` per attempt. If it already signed one, a partner `FAIL` for k only completes the pair: it signs no `partner_failed` answer. After signing a retry `FAIL`, a device waits, up to session end, for the partner's `FAIL` for k. Attempt k + 1 starts only when `k + 1 < 2`, the device holds a retry-reason `FAIL` for k from both sides, and either it has not sent `GAP_VALUE` for k or F9 gave `impossible_flight` or `self_timestamp_mismatch` for k. Otherwise the session ends. So those two results retry once, as in C22 (Q8). NEAR, `too_far` and a mismatch stay final. New seeds, salts and `t0` for each attempt.

Two honest devices can lose a session this way. B sent its `GAP_VALUE` for k. A times out after its `GAP_HASH`, before its own `GAP_VALUE`, and signs a retry `FAIL`. B has sent its `GAP_VALUE` and holds no pair, so it neither answers nor moves on. Both logs then give NOT_NEAR by A's `FAIL`, and nobody gets NEAR. This costs completeness, not agreement. The rule stays as it is. The run needs a timeout at one exact point, so it is rare. And if B answered here, a cheater in A's place could read B's gap, sign a retry `FAIL`, and get the K3 retry without signing a wrong gap.

This retry reopens hole K3. Once both gaps are sent, a retry hands the partner a number it can use, and a dishonest device can force the retry by sending a gap that gives `impossible_flight`, or a `self_os_delta` out of tolerance that gives `self_timestamp_mismatch`. A log that holds both `GAP_VALUE`s for attempt 0 shows the case. A log D hands over may not: `verify` doesn't check that a log is complete, so D can leave out the honest `GAP_VALUE` for attempt 0. Attempt 0 then looks like a run where the honest device failed before it sent its gap, and attempt 1 still verifies as NEAR. So a reader can't rule the case out from the log.

A session also ends after 600 s on the device's own clock (C6).

**F11, log.** For the session: `INVITE`, `JOIN`, without the WebRTC offer and answer. For each attempt held: the device's own sent messages and the partner messages it accepted, each with its signature, in order. Nothing that was dropped or failed a body check goes in. A `FAIL(seed_mismatch)` stands alone: the bad `SEED_VALUE` it answers is not in the log. Since `seed`, `salt`, `sr` are inside, a reader can rederive both codes and check `code_commit`, which `verify_record` can't do today (`verdict.py:174`). Proofs, if any, are attached (decision 2). The log holds no audio and no `cal_us`.

## 3. What the server did, and what does it now

| Server job (C rule) | Where it goes in v2 | Who enforces it | Changes |
|---|---|---|---|
| Join token, session age (C6) | Invite under 120 s, used once, checked by A at `JOIN`. Session age on each device's own clock | each honest device | No shared clock. A dishonest device keeps no timer. |
| Carrying messages between the devices | The link: a WebRTC data channel set up by two QR codes (F1) | nobody, the link is trusted for nothing | No server in a run. Both devices need the same local network (ADR 0001). |
| Guest checks host key (C7) | B takes `pk_A` from the `INVITE` QR code, A takes `pk_B` from the `JOIN` QR code | both | Both directions now (K6 closed). |
| Both confirm, World ID (C8) | Each person taps confirm on their own device | each honest device | World ID is out (FN4, roadmap out of scope). |
| State order (C9) | Each device's state machine, the "sends when" column | each honest device | Order binds honest devices only. |
| Arm: attempt, rate, t0 (C10) | `sr` in `SEED_HASH` (F2). `t0` in `TIME` (F4) | receiver checks `sr` range, B checks `t0` bounds | RTT check gone. `t0` is completeness only: no property reads it (CP4: the offset cancels). |
| Secret sounds, `bed_key` from the seed (C11) | Seed hash, salt, seed value (F2, F3, F6), codes from `key_X` | both | Within an attempt a device can't pick its code (FP2). Over a session it gets two draws, by failing attempt 0 on purpose (K16). The generator must be ported bit-exact (K9). |
| Play and capture schedule (C12) | Same | app | none |
| Own arrival (C13) | The v2 detection rule | app, circuit | Rule changes (section 5). |
| Recording hash after the schedule, signed, right role, attempt, nonce (C14) | `REC_HASH` (F5) sent after own capture | honest sender | A receiver can't check the partner's clock, and doesn't need to: the gate on `SEED_VALUE` (F6) is what CP1 needs. |
| Partner code only after own recording hash (C15) | `SEED_VALUE` only after holding the partner's `REC_HASH` and sending its own, after its own capture | honest sender | Now both directions are gated by the honest side. (FP1) |
| Measure (C16) | F7 | app | none |
| Transcript checks (C17) | `GAP_VALUE` receiver checks (F8) | each honest device, and the reader | Stored server values become signed messages. |
| Blind gap (C18) | `GAP_HASH` then `GAP_VALUE` (F8) | honest sender | The last device to send its `GAP_VALUE` holds the full log (FN1). A retry after both `GAP_VALUE`s shows the partner the honest gap (K3, accepted with a warning). |
| Verdict (C19, C20, C21) | F9, same math, section 4 | both devices, any reader | `cal_us` gone (v2 transcripts only). |
| Retries and deadline (C22) | F10 | each honest device | As C22: a failed measurement, `impossible_flight` and a self timing mismatch retry once. With no server, the retry no longer hides the gap (K3). |
| Log and replay (`verify_record`, V7) | F11, section 4 | any reader | Codes can be rechecked. Reader must pin keys. Reader must compare the stated verdict (V7 hole). |
| Proofs after NEAR (C23) | Optional, carried in the log | the reader decides (decision 2) | The circuit's issuer input goes (roadmap stage 4). |
| Chain attestation, Safe, ENS (C24, C25) | Out: examples with their own backends | | |
| Device vouching (C2 to C5) | Nothing (decision 3) | | Every key is just a key (FN2). |

## 4. The verdict

The v1 math is kept as is (`server/pop/verdict.py`, V1 to V4). Only v2 transcripts exist, so every self check runs with `cal = 0`: the app folds its calibration into `p_self` before signing, so `self_os_delta` is already the residual (`verdict.py:13-16`). This is the `cal_us` choice. The log carries no `cal_us`, which also removes the unsigned-`cal_us` hole of V7.

`Outcome(log, k)` for the last attempt k in the log, a pure function:

1. If a `FAIL` for k is in the log: NOT_NEAR. The reason is A's `FAIL` reason if A signed one, else B's. Fixed order, so arrival order doesn't matter.
2. Else, if both `GAP_VALUE` for k are in the log and pass the F8 checks against the rest of the log: `combine(t_A, t_B)` with cal 0, always A's transcript first. That gives NEAR, NOT_NEAR `too_far`, or no verdict with `impossible_flight` or `self_timestamp_mismatch`. The last two read as NOT_NEAR with that reason. On attempt 0 the devices then retry (F10).
3. Else: incomplete. A reader treats it as no NEAR.

`combine` is C19 (roles A and B, same `sid` in the nonce slot, same attempt, keys crossed and different), C20 (`|self_os_delta| <= 50 ms` at the signed rate, both edges in) and C21 (exact rational flight; `<= -20` impossible, `>= 60` too far, NEAR between, ties as in `Pair.lean`). It returns the same thing on both devices because it reads only the two transcripts, in role order.

A NEAR says: two keys signed two transcripts for this `sid` and attempt, and the numbers in them fall in range. With a proof attached it says more, as far as the circuit goes (`../v1/README.md`, "What `presence_sound` says").

`verify(pkA, pkB, log)` for a reader: the log's keys must equal the ones the reader pinned; one `INVITE` and one `JOIN`, and at most one message per slot `(role, attempt, tag)`; every signature checks; every `peer` is `H` of a set of the partner's messages in the log that holds the named one; every seed matches its `hs`; `code_commit` is rederived; every message is for attempt 0 or 1; a `TIME` is from A; a message for attempt 1 needs a retry `FAIL` for attempt 0 from each side in the log; then `Outcome`. A `FAIL`'s signature is checked and its `retry` bit is read. Its reason code is not checked. If the bit and the reason disagree, the bit decides. A `verdict` field written into the log is compared, never trusted. `verify` returns the `sid` with the outcome, so a reader that expects one session can compare it.

Without the one-per-slot check K1 comes back: D could keep its first `GAP_HASH`, which the honest `GAP_VALUE` names, and add a second `GAP_HASH`, `GAP_VALUE` pair holding a gap picked after seeing the honest one. With it, D's only `GAP_HASH` must be the one the honest `peer` hashes over (HASH).

`verify` judges the log it is shown. It can't tell that the log is the whole session: D can drop a later attempt, and an attempt 1 NEAR becomes the attempt 0 NOT_NEAR. This only goes one way. A retried attempt is always NOT_NEAR: either no `GAP_VALUE` was sent, or the pair gave `impossible_flight` or `self_timestamp_mismatch`. And D can reach NOT_NEAR anyway by adding its own `FAIL` (K12).

## 5. The v2 detection rule

Today the rule takes loudness through the FIR filter and the match from raw samples (gap 2), and lets zero loudness pass (gap 1). The v2 rule is `../v1/next-version-fixes.md` fixes 1, 2 and 3 together.

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

**Model shape.** One honest device is a state machine: `step : State → Input → State × List Msg`. An input is any message (the attacker), a clock tick, a local result (capture done, measurement, person tapped). Clock ticks only move forward: the attacker chooses the messages, not the honest device's clock. Properties FP1 to FP4 hold for every input sequence with forward ticks. FP5 and FP6 are lemmas about the pure functions `Outcome` and `verify`, not two-device simulations. `H` and `Sign`/`Verify` are abstract, with HASH and SIG as hypotheses or structure fields. Plain Lean core for the protocol. One property per file.

### Protocol

**FP1, order.** For every input sequence: if the honest device sends `SEED_VALUE` for attempt k, it had already accepted a partner `REC_HASH` and a partner `SALT` for (sid, k) and sent its own `REC_HASH`, and when it sent that `REC_HASH` its clock was past `t0 + 2.0 s`.
*Assumes:* forward ticks, for "its clock is still past it now". *Does not give:* that `REC_HASH` is the hash of real audio (CN1, CN2). The code is played out loud anyway, so a mic near the honest device hears it (CN3).

**FP2, fixed code.** If the honest device accepts a partner `SEED_VALUE(seed)` for k, then `H("seed" ‖ sid ‖ partner role ‖ k ‖ seed)` equals the `hs` it accepted for k. It sent its own `SALT` for k only after accepting that `hs`. Under HASH, at most one seed is ever accepted for (sid, k), so the partner's code has one value.
*Assumes:* HASH. RAND and HIDE for "D couldn't steer its code within the attempt", which is reasoning, not a theorem. Over a session D gets a second draw by failing attempt 0 on purpose (K16). *Does not give:* that a derived code is a good code. The floor in the v2 rule rejects a zero-energy template (RS), so the all-128 code of gap 5 can't pass even if derived.

**FP3, blind gap.** The honest device sends `GAP_VALUE` for k only after it accepted the partner's `GAP_HASH` for k. After sending `GAP_VALUE` for k it moves to attempt k + 1 only when it holds both `GAP_VALUE`s for k and F9 gave `impossible_flight` or `self_timestamp_mismatch`.
*Assumes:* HIDE, stated, not modeled. *Does not give:* that the gap is true (CN1). It does not protect against a device that forces a retry: D can send a gap that gives `impossible_flight`, or a `self_os_delta` out of tolerance, learn the honest gap, and use it in attempt 1 (K3). It doesn't stop the gap leaking into a later session with the same partner (K4), or devices sharing numbers outside the protocol. The last device to send its `GAP_VALUE` still holds the full log (FN1).

**FP4, freshness.** Every message after `JOIN` that the honest device accepts carries its current `sid`. A's `JOIN` check pins its own fresh `r_A`. `sid` contains its own fresh `r`. So under HASH, if its `r` differs from the one in an old log, no message of that log is accepted. (A reader sees the old `sid` in `verify`'s result; whether it wanted that `sid` is up to the reader, FN3.)
*Assumes:* HASH, RAND. *Does not give:* replay protection at a reader. A consumer has to mark `sid` as used (FN3).

**FP5, agreement.** Two pieces, neither a two-device simulation.
(a) A lemma about the pure function: `Outcome` step 2 reads only `(t_A, t_B)`, in role order, so equal pairs give equal outcomes.
(b) A single-device invariant: an honest device signs at most one `GAP_VALUE` per k (resends are the same bytes), and the partner `GAP_VALUE` it accepts matches the one partner `GAP_HASH` it accepted. After its own `GAP_VALUE` it signs a `FAIL` for k only on a final check failure, or a retry `FAIL` when the pair it holds gives `impossible_flight` or `self_timestamp_mismatch`.
On paper: if both devices are honest, each `GAP_VALUE` one accepts is the only one the other sent (b, twice, plus HASH). So when both hold a pair, it is the same pair, and by (a) the same outcome. A retry `FAIL` after a `GAP_VALUE` comes only from the verdict of that same pair, which is then not NEAR on either device. An honest partner never fails a final check. So the outcomes can still differ, but never as NEAR on one honest device and NOT_NEAR on the other. If the link closes mid-exchange, one side can hold NEAR and the other be incomplete, or one side hold `impossible_flight` and the other its own retry `FAIL`. The run in F10 where A fails after its `GAP_HASH` gives NOT_NEAR on both.
*Assumes:* HASH. *Does not give:* that the honest device learns the outcome when D walks away after the honest device's `GAP_VALUE` (FN1).

**FP6, third-party check.** For keys the reader pinned: `verify` returns `Outcome` of the log when every check passes, and rejects otherwise. Changing any message without the signer's key fails (SIG). D re-signing one of its own messages fails once a later honest message carries it in `seen`, or once it is fixed by D's own `GAP_HASH` (HASH). With the one-per-slot check, in a log that holds the honest device's `GAP_VALUE` for k, every one of D's messages for k up to its `GAP_HASH` is the one the honest device accepted, and the content of D's `GAP_VALUE` (`blind`, `t`, `sig_t`) is fixed by that `GAP_HASH`. D's `FAIL`s are fixed by nothing: D can add one and turn its own log into NOT_NEAR, which is X2.
*Assumes:* SIG, HASH, reader-pinned keys. *Does not give:* anything about the air, or who holds a key (decision 3). A NEAR log does not mean the honest device saw NEAR. D can send a bad `GAP_VALUE` to the honest device, which then signs a final `FAIL`, and later show a reader a log with its good `GAP_VALUE` and without that `FAIL`. That is FN1 in another shape (K10). The honest person did confirm the session.

### Rule

**RC, score ceiling.** For any `y`, `ci`, `cq` of the same length: `M <= E · cn2`. So `M / (E · cn2) <= 1` whenever `E · cn2 > 0`. Proof: Cauchy–Schwarz on `I` and on `Q`, added.
*Assumes:* `I`, `Q`, `E` over the same `y`, and `cq` inside `cn2`. Without `cq` in `cn2`, it fails: one nonzero `ci` and a large `cq` give any score. *Does not give:* that noise fails. How often noise passes depends on `BAR` and the codes (stage 3).

**RS, silence rejected.** If `y = 0` everywhere, `Pass` is false. Since the filter is linear, digital silence (`w = 0`) gives `y = 0`. If `cn2 = 0` (all-128 templates), `Pass` is false for every recording.
*Assumes:* `FLOOR >= 1`. *Does not give:* that quiet sound fails. The 48 kHz taps sum to 3 and the 44.1 kHz taps to 1, not 0 (`popt2.py` `RATES`). So a constant offset of one step gives `E > 0` and, with `FLOOR = 1` and a nonzero template, passes the floor (K11). It is judged by the ratio test alone.

**RT, gain cancels.** For any integer `g != 0`: `BAR · M(g·y) >= E(g·y) · cn2` iff `BAR · M(y) >= E(y) · cn2`. Both sides scale by `g^2`. So the filter's gain at one frequency drops out, and the v1 tone's route (match through gain 1, loudness through gain 0.14, about 1,400 times too high a score) is gone: by RC no score is above 1.
*Assumes:* nothing. *Does not give:* that a 500 Hz tone fails. That is now a plain correlation between the tone and the code, which depends on the code and phase. It is checked by rerunning `circuit-cases` and the stage 3 recordings, not in Lean. The floor part of `Pass` is not scale-free, on purpose.

**What v1 theorems flip.** `Bar.partner_silence_accepts` and `self_silence_accepts` should become false under the v2 rule (RS). The tone witness was a `circuit-cases` run, not a theorem, so it flips in `nargo`, not in Lean.

## 7. Known holes

Found while reviewing Part 2. K1, K2, K5, K6, K7, K8 are fixed above. K3 is open and accepted. The rest stay open.

- **K1, equivocation (fixed by `peer`).** In the draft, nothing the honest device signed named D's messages. D could send its gap after seeing the honest one, then sign a new `GAP_HASH`, `GAP_VALUE` pair with another gap, and show a reader a log that verifies. Same trick at F5 after learning the honest seed: sign a new recording hash. Each honest message now carries `H` of every partner message it has accepted (`seen`). This needs the one-per-slot rule, live and in `verify` (section 4), or D just keeps both hashes in the log.
- **K2, F8 could be brute-forced (fixed by `blind`).** The draft hashed `transcript ‖ sig`. The partner already knows most transcript fields (keys, `sid`, rate, `rec_root` from F5, `code_commit` after F6). The gap is a small integer. Hiding then rested only on the signature being unpredictable. A random `blind` makes it explicit.
- **K3, a retry after the gap is sent leaks it (open, accepted).** In v1 the server hid the number on retry (M6). In v2, after both `GAP_VALUE`s D knows the honest gap. D can force a retry by sending a gap that gives `impossible_flight`, or a `self_os_delta` out of tolerance that gives `self_timestamp_mismatch` (K14), and attempt 1's honest gap is within jitter of attempt 0's. So D can pick the gap that gives NEAR in attempt 1. Never retrying after a `GAP_VALUE` would close it. The owner keeps the v1 retry (Q8): v2 does not expect modified apps, and an implementer who does can add attestation (Q3). A timeout after a `GAP_VALUE` still never retries. A reader can't rule the case out: a log that holds both `GAP_VALUE`s for attempt 0 shows it, but D can hand over a log without the honest one (F10).
- **K4, the gap leaks across sessions.** Any finished log shows both gaps. D can start a new session with the same partner and use the old gap. v1 had this too ("not studied", M6). Each new session needs the honest person's confirm tap. Open.
- **K5, no domain separation (fixed by the common form).** The draft didn't say what each signature covers. A seed hash without `sid`, role and attempt could be copied from the partner or replayed.
- **K6, one-way pairing (fixed by the second QR code).** If A got B's key only over the network, an active outsider could drop B's `JOIN` and send its own, so A would measure with the outsider's key while B got nothing. Only the confirm tap of A's person would stand in the way. B's `JOIN` is a QR code that A scans (F1, Q9), and OOB covers both QR codes. The fix rests on OOB and on WebRTC checking the certificate fingerprints. Neither has been tested.
- **K7, timing is local (fixed by saying so).** No receiver can check the partner's clock. Every gate is on the honest sender's own clock. `t0` only matters for completeness.
- **K8, the rate must be signed before the seed is sent (fixed in F2).** Codes are rendered at the listener's rate (`popt2.py`, `_code_commit` in `sessions.py`), so a reader needs both rates to recheck `code_commit`.
- **K9, the generator isn't portable.** `popt2.py` says a phone can't reproduce the FFT path bit for bit. Devices and readers must derive the same templates, or `code_commit` can't be rechecked and honest devices will disagree. Needs an integer generator (roadmap stage 5). Open.
- **K10, FN1 stays.** The last device to send its `GAP_VALUE` holds the full log. D can keep a NEAR log the honest device never got. The honest person did confirm the session, so D can't make one without them.
- **K11, the floor only catches exact silence.** `FLOOR = 1` rejects `y = 0`. The taps sum to 3 (48 kHz) and 1 (44.1 kHz), so any DC offset has energy. The click (gap 3) and very quiet noise are left to the ratio test. A higher floor is a stage 3 question (fix 2, "Consider").
- **K12, either device can end a session NOT_NEAR (X2 stays).** `FAIL` needs nothing from the partner. NOT_NEAR is no finding about distance. Dropping a later attempt from the log does the same (section 4): a log can't prove it is the whole session.
- **K13, circuit gaps 6 to 10 stay.** Partner side is "loud enough", not "first". A window past the capture end is no longer silence-safe to pass: if its whole filter span is padding, `E = 0` and RS rejects it. One that straddles the end still reads padding, and the transcript still has no capture length. Some signed fields are never read by the circuit. The partner key isn't checked in-circuit. Public inputs must be pinned by whoever verifies, now including the two keys and `code_commit`. Roadmap stage 4 picks which to fix.
- **K14, the self timing check binds honest devices only.** `self_os_delta` is reported, not recomputed (C20). Unchanged from v1. In v2 it is also a way to force the retry of K3: D reports an offset out of tolerance, and needs no plausible gap for it.
- **K15, network metadata.** No third party carries messages, so no server sees who talks to whom, when, and how much. Someone on the same network still sees two local addresses exchange encrypted packets. Not studied.
- **K16, two draws of a code per session.** D sees its own code once it holds the honest `SALT`, and the honest code once it holds the honest `SEED_VALUE`. Before any `GAP_VALUE`, it can sign `FAIL(capture_failed)` (or, as A, send a bad `t0`) and get fresh seeds and salts in attempt 1. So D can pick the better of two codes, its own or the honest one. Not unlimited: the honest salt still comes after D's seed hash, and there are only two attempts. One attempt per session closes it, at the cost of completeness (Q19). Open.
