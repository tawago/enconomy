# DESIGN: lost phone, email + laptop + new phone, one frame tx

Nov 3, 2026. Revised the same day after `REFUTE.md`; what changed and why is in `FIXES.md`. This is the one design for Nov 5-7. It settles the siblings (`threat-model.md`, `account-design.md`, `proximity.md`, `evp-flow.md`, `ens-options.md`, `poc-native-evp/`). Where they disagree, this file wins.

Marks: MEASURED = forge or a local run in this folder. MODELED = our estimate. OPEN = not checked.

## 0. One paragraph

Alice's smart account `A` is owned by a P-256 key on her phone. The phone is gone. On her laptop, in Chrome, she opens the recovery page, chirps with her new phone, and types `alice@tawago.com`. Chrome mints an EVP token whose `nonce` commits to the new key and to that chirp. One EIP-8141 frame tx starts a rotation: the new phone signs the binding digest, the laptop's enrolled key `L` pays and signs the tx, a VERIFY frame checks the chirp's three proofs, the body frame checks the email token with the precompiles and sets `pendingOwner`. After `DELAY` anyone finishes. The old key can cancel in between. ENS is display only, and on Sepolia it is broken today (section 7). Nothing on the critical path reads ENS or DNS.

## 1. The decision: laptop key, not guardian phone

`threat-model.md` §5 wants one EVT plus a guardian phone in the room signing `D` in VERIFY. `account-design.md` §6 wants two-step with the laptop EOA paying and acting as the second factor. Both agree on two-step with timelock and owner cancel. The disagreement is the second factor.

**Build the laptop key.** Three reasons, in order:

1. One human on stage. A "guardian" played by the same person proves nothing to a judge. A real guardian is a third device and a second person, and the demo already has a laptop, a new phone, a server, an issuer and a devnet.
2. The phone raw-digest signing test (Nov 2 gate) is still not run on a phone. The guardian path needs it on a second phone. The laptop path needs it on none: the new phone can use a software key in its browser (section 5).
3. The guardian path already exists untouched: `RecoverableP256Account`'s 3-sig Meet-to-Recover branch. Nothing is lost. EVT + guardian is spec'd below as v1.1 (section 4.5) and built only if the phone gate passes.

**What this costs, said plainly.** A stolen unlocked laptop with the mail session alive and the recovery page's key in it can start a recovery. The 120 s window and the old phone are the only brakes. For a lost phone there is no old phone, so the brake is the window alone. This goes in the README in those words. The threat model's table (section 9) does not soften it.

## 2. Actors and keys

| Who | Key | Scheme | Signs | Notes |
| --- | --- | --- | --- | --- |
| Account `A` | the contract | - | - | sender of every tx. Storage: `owner`, `pendingOwner`+`readyAt`, `recoveryNonce`, `laptop`, `configHash`, guardians (existing) |
| New phone `N` | P-256, raw digest | 2 (6,700) | explicit `msg = ctx`, once, at chirp time | software key in the phone browser for v1; native app key is the upgrade (section 5) |
| Laptop `L` | secp256k1, software, in page storage | 1 (2,800) | sig hash, empty msg, last | payer and enrolled second factor. Demo tier: script-readable. WebCrypto and passkeys cannot be `L`: no secp256k1, no raw digest, cannot be an EOA payer. `proximity.md` options B/C are moot while `L` pays |
| Chrome | P-256 KB key, Chrome's own | - | KB-JWT with `nonce = ctx` | only `nonce` binds the token to us |
| Issuer | P-256, `issuer-worker/keys` | - | EVT | pinned in `configHash` by the owner at deploy. Not from DNS, not from ENS |
| Old phone | the current `owner` | 2 | cancel | lost in the headline story |
| PoP server | P-256 issuer key, pinned as `popIssuer` in `configHash` | - | SBcred3 credentials, POPCC1 code attestations | relays and sets `t0`. Its NEAR verdict is off the critical path: the chain checks the proofs (section 5). It can deny service, and can help a cheating phone (section 9) |

`aud` is one fixed origin: **`https://recover.tawago.com`** (Cloudflare Pages). It goes into `configHash` at deploy. Quick tunnels change origin per run, so a tunnel-test account is deployed with that tunnel's origin. Do not mix the two.

## 3. ctx: one digest, one byte layout

```
DOMAIN = keccak256("enconomy.EvpRecover.v1")
       = 0x3ced9c60f4b427def1b0a2d7585279e5ea811b83e43b1c5208e29c2e975e2ddc

preimage = abi.encode(bytes32 DOMAIN, uint256 chainId, address account, address newKey,
                      uint256 recoveryNonce, bytes32 sessionTag, uint256 deadline)   // 224 bytes, 7 words
ctx      = keccak256(preimage)
evpNonce = "0x" + lowercase hex(ctx)       // the <input autocomplete="email-verification-token"> nonce
phone entry: scheme 2, signer = newKey, msg = ctx
frame 0 data = be64(deadline)              // 8 bytes, big-endian uint64
popNonce = PopCtx.nonce(chainId, account, ctx, notBefore, sid)   // all three proofs carry split(popNonce)
```

- `newKey` is an address: `keccak(qx‖qy)[12:]`. It equals `sig[0].signer` and becomes `pendingOwner`.
- `sessionTag` is 32 bytes the page picks **before** the chirp. Same ABI slot and same bytes as the old `transcriptHash`, so the preimage, `ctx-vector.json` (which keeps that key name) and the 15 live tokens are untouched. It is no longer a hash of the recording. That would be circular: the proof commits to ctx, so ctx cannot contain anything from the proof. `proximity.md` §4's layered `ctxHash / sessionNonce / D` and `proximity-sigcheck/vectors.json` stay replaced.
- `deadline` is in ctx, in frame 0 and in `startRotationEvp` calldata. VERIFY checks calldata == frame 0.
- `recoveryNonce` is read from storage in VERIFY and bumps on start, cancel and finish.

Test vector (`cast keccak` + `cast abi-encode`, 1.4.3). Also in `ctx-vector.json` next to this file.

```
chainId        1337
account        0xacacacacacacacacacacacacacacacacacacacac
newKey         0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee
recoveryNonce  7
sessionTag     0x7777777777777777777777777777777777777777777777777777777777777777
deadline       1793000900
preimage  0x3ced9c60f4b427def1b0a2d7585279e5ea811b83e43b1c5208e29c2e975e2ddc
          0000000000000000000000000000000000000000000000000000000000000539
          000000000000000000000000acacacacacacacacacacacacacacacacacacacac
          000000000000000000000000eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee
          0000000000000000000000000000000000000000000000000000000000000007
          7777777777777777777777777777777777777777777777777777777777777777
          000000000000000000000000000000000000000000000000000000006adf05c4
ctx       0x22cbad28b2d580114630eb65e51e47305a5d6efbbb8c6d48fca64bd7d4b5655a
evpNonce  "0x22cbad28b2d580114630eb65e51e47305a5d6efbbb8c6d48fca64bd7d4b5655a"
frame0    0x000000006adf05c4
audHash   keccak("https://recover.tawago.com") = 0x40a200302bc729ecd1978338601741801f5a8c0d8b981a0c2af99ca739b006d0
emailHash keccak("alice@tawago.com")           = 0x9e2c0cedad43a65e524ec636197b290e6d3b38ac6eb7dbf4d492b656021d2db8
```

Forge: `keccak256(abi.encode(...))` gives this directly. JS and the laptop page: concatenate the seven 32-byte words, keccak. The page needs a vendored keccak (`rp.html` uses SHA-256 as a stand-in today: swap it).

## 4. Transactions

Frame limits are the sidecar's `execution` limits. Each frame also has a `state` limit (EIP-8037). Inside a frame tx that budget is all the frame gets: run out and the frame halts, even with execution gas left (ethrex `vm.rs` `increase_state_gas`). Cancel and finish fit the public prefix cap of 100,000. The start does not: it needs our sidecar's 16,000,000 (section 5). The cap counts the sum of prefix limits + 6,700 per P-256 entry + 2,800 per secp256k1 entry. Measured numbers: `EvpVerifier.verify` 63,111 warm (`poc-evp-issuer`), recovery `self_verify` 20,513 and normal `self_verify` 7,887 (`poc-validation-rules`), frame entry 3,000 and expiry ~3,050 (ethrex source, modeled in forge), keyed-nonce first use 20,000 (avoided: key 0).

### 4.1 Start

```
0 VERIFY  target=0x..8141  flags=0 (expiry)   data=be64(deadline)                              limit  4,000
1 VERIFY  target=A         flags=2 (EXEC)     data=evpVerify(notBefore, sid, qx, qy, cfg, bundle)  limit 12,000,000
2 VERIFY  target=L (EOA)   flags=1 (PAY)      data=""  default code                            limit  8,000
3 SENDER  target=A                            data=startRotationEvp(newKey, sessionTag, deadline, cfg, token, offs)
                                                                                               limit 110,000 exec + state (below)
sigs: [0] P-256 signer=N msg=ctx     [1] secp256k1 signer=L msg=empty (sig hash)
nonce_keys=[0] (legacy lane, no 20k)   sender=A   payer=L
```

VERIFY (frame 1, new branch, sig count 2, frame count 4; reads own storage only, then calls the presence verifier):
- frame 0 is the expiry predeploy in VERIFY mode; read `deadline`.
- frame 2: mode VERIFY, target == `laptop`, flags PAY. `sig[1]`: scheme 1, empty msg, signer == `laptop`.
- frame 3: mode SENDER, target == `A`, selector == `startRotationEvp`. Calldata is variable length (token), so pin selector + fixed ABI offsets: `newKey` at 4, `sessionTag` at 36, `deadline` at 68. Require calldata `deadline` == frame 0's.
- recompute `ctx` with keccak from those plus `recoveryNonce` (SLOAD).
- `sig[0]`: scheme 2, `SP_MSG == ctx`, signer == `newKey`, `newKey != 0`, `newKey != owner`.
- the proof bundle, section 5.
- APPROVE(EXEC).

Body (frame 3, `onlySelf`, precompiles and TIMESTAMP fine):
- `keccak(cfg) == configHash` (issuerX, issuerY, emailHash, audHash, popIssuerX, popIssuerY, presenceVerifier). One SLOAD.
- `EvpVerifier.verify(token, offs, cfg, ctx)`: issuer ES256 over EVT (0x100, 0x02), `cnf` key, KB ES256, `aud` == audHash, `email` == emailHash, `email_verified`, both `iat` in `[now - 900, now + 60]` (`MAX_AGE` = the 15 min deadline, so expiry and age agree), `sd_hash`, and **`nonce == evpNonce(ctx)`** (was `keccak(newKey)` in the PoC; change it). The body recomputes ctx the same way VERIFY did.
- `pendingOwner = newKey; readyAt = now + DELAY; recoveryNonce++; emit RotationStarted`.

Gas, start:

| Line | Gas | Mark |
| --- | ---: | --- |
| frame 0 expiry | 4,000 limit | MEASURED ~3,050 use |
| frame 1 A VERIFY | 12,000,000 limit | 87,505 MEASURED with mock proofs (forge + entry + 4 cold accounts at +400: helper, adapter, phone and pair verifiers) + 11,473,237 CITED for the old 7-input bundle = 11,560,742 as a plain sum. That sum ignores EIP-150: 63/64 forwarding holds gas back at account to adapter and adapter to verifier. Run through the real account and adapter with burn mocks at the cited phone cost, the largest pair that fits is 3,524,568 against 3,320,074 cited, so **about 204,000 is left** for the 11-input pair, whose cost is unmeasured. MEASURED with burn mocks, `test_budget_start_frame1_forwarded`; no real verifier |
| frame 2 L pay, default code | 8,000 limit | source: default code reads `sig[1]`, uses 0, entry 3,000 (ethrex `frame_tx.rs` `execute_default_verify`) |
| sig entries 6,700 + 2,800 | 9,500 | ethrex |
| **prefix** | **12,021,500 / 16,000,000** (our sidecar sum incl. expiry). Over the public 100,000 | MODELED |
| frame 1 data, 30,052 B | 462,832, outside the frame | MEASURED size at real proof sizes, 16 per byte. Probe mined 28,000 B for 446,300 |
| **tx under EIP-7825** | **12,627,388 / 16,777,216** | MODELED `test_budget_start_txCap`. State gas excluded from this cap |
| body: EVP verify | 63,111 | MEASURED warm |
| body: configHash SLOAD + ctx keccak | ~2,500 | MODELED |
| body: pending slot + nonce, both already non-zero | ~5,800 | DERIVED from the 17,100 drop in the measured total; rows are parts, the total is the measurement |
| body: entry | 3,000 | ethrex |
| **body** | **80,461** measured, 83,461 with entry; + calldata 19,028 | MEASURED forge, Osaka pricing |
| body state gas | 0 fresh slots | MEASURED `StateGas.t.sol` |

**State gas, frame 3.** A slot that goes from zero to non-zero costs 64 × 1530 = 97,920 state gas. The first version wrote two fresh slots on a fresh account (195,840) and one after every cancel or finish. Fixed in the contract: `recoveryNonce` starts at 1 and slot 1 carries a keep word that is never cleared, so no start writes a fresh slot (`contracts/test/StateGas.t.sol`). The builder still sets frame 3's `state` limit to the sidecar's per-frame `state` estimate, floor 100,000. Never copy `poc/clients/gift-shape.cjs` line 42 (`state: 0`). A start that halts in frame 3 has already passed VERIFY, so `L` pays the full cost and nothing rotates. `L`'s balance must cover `total_gas_limit × maxFee`, and that includes every frame's state limit: now about 12.73M × maxFee (12,727,388 with the 100,000 state floor), since the payer is charged up front for the 12M frame.

Native EVP in VERIFY is dead: best SHA-256 176,935 for EVT + KB, ~247,700 all-in (`poc-native-evp`, MEASURED). The split above is forced, not chosen.

Griefing, one line: `L` pays, so junk tokens cost `L`, not `A`. A bad proof dies in VERIFY and costs nobody anything. A bad token still dies in the body and costs `L` the whole prefix, about 12M gas. No `pre_verify` used-digest frame, no issuer native entry. Both stay out.

### 4.2 Cancel (old key)

```
0 VERIFY  target=A  flags=3 (EXEC+PAY)  data=""            limit 12,000
1 SENDER  target=A                      data=cancelRotation()
sigs: [0] P-256 signer=owner msg=empty
```
Existing path. Prefix ~19k (7,887 + 3,000 + 6,700 + ~1,400). Body ~10k. Self-paid.

### 4.3 Finish (new phone, after `readyAt`)

```
0 VERIFY  target=A  flags=3 (EXEC+PAY)  data=""            limit 18,000
1 SENDER  target=A                      data=finishRotation()
sigs: [0] P-256 signer=pendingOwner msg=empty (sig hash)
```
Existing path, frames pinned. VERIFY modeled 14,860, so the limit is 18,000 (15,000 left 140). Body ~14k. Self-paid by `A`. `finishRotation()` has no auth and checks only `readyAt`, so `L` or anyone can also finish with a plain legacy tx to `A`. That is the fallback when `A` holds no ETH; no L-paid frame shape is needed. Known grief: `N` can send the frame finish early, body reverts, `A` pays. Only `N` can do it. Accept.

### 4.4 Branches in VERIFY, by sig count

| sigs | frames | who | path |
| ---: | ---: | --- | --- |
| 1 | any | `owner` | normal, cancel |
| 1 | 2 | `pendingOwner` | finish (existing) |
| 2 | 4 | `N` + `L` | **EVP start (new)** |
| 3 | 3 | `N` + 2 guardians | Meet-to-Recover (existing, untouched) |

### 4.5 v1.1, not built unless the phone gate passes: EVT + guardian present

Same start tx with a third entry: `sig[2]` P-256 guardian over `D = keccak(abi.encode(GUARD_DOMAIN, chainId, A, newKey, recoveryNonce, sessionTag, deadline))`, `isGuardian[signer]`, `signer != newKey`. VERIFY requires it when `guardianCount > 0`. The guardian phone chirps with the new phone in the PoP app (signed transcripts) and signs only on its own NEAR. Prefix +6,700 + ~2k = ~55k. This is what stops the stolen laptop. Go condition: raw-digest signing works on the iPhone by Nov 6 noon and v1 is green.

## 5. Proximity: where it is load-bearing, and the stack

Rewritten Nov 6. Before this, `transcriptHash` was 32 opaque bytes nobody checked. Now frame 1 checks the real Noir proof bundle in VERIFY, and the two devices in the proof must be the preregistered laptop and the new phone.

**What moved.**

| Thing | Before | Now |
| --- | --- | --- |
| Slot in ctx | `transcriptHash`, a server-chosen hash from after the chirp | `sessionTag`, picked by the page before the chirp |
| Proof of the chirp | none on chain | phone A, phone B, pair, verified in frame 1 |
| Frame 1 limit | 25,000 | 12,000,000 |
| Mempool | canonical shape | our own sidecar only: 16M verify cap, precompiles allowed |
| Laptop | secp256k1 payer `L` | `L` stays, and `laptopDeviceX` adds its P-256 device X. Set in the constructor, read at start, no fresh slot |
| Config | issuer, email, aud | plus PoP issuer and presence verifier, so `configHash` covers them |

**The check, frame 1, after the frame pins.** `popNonce = PopCtx.nonce(chainid, A, ctx, notBefore, sid)` with ctx at the nonce before the bump. No circularity: the proof commits to ctx, ctx does not contain the proof. Then `verifyPresence` requires all three proofs to carry `split(popNonce)`, the pinned issuer, the POPCC1 signatures, `valid_at` in window, `(xa_hi, xa_lo) == split(laptopDeviceX)` and `(xb_hi, xb_lo) == split(qx)`, with `keccak(qx‖qy)[12:] == newKey`. Roles pinned: laptop = A, new phone = B.

**Frame 1 data is signed, and also does not need to be.** On our ethrex `compute_sig_hash` keeps all frame data verbatim, VERIFY frames included (`transaction.rs`), so `L`'s signature covers it, and `L` must sign after the proofs exist. This matches `../notes/eip8141-family.md` section 1: an empty `msg` elides raw signature bytes only, not frame data. The phone's entry signs only ctx. So each field is bound on its own as well: `notBefore` and `sid` through `popNonce`, `cfg` through `configHash`, `(qx, qy)` through `newKey`, the public inputs through the checks here plus the proofs themselves, the POPCC1 signatures through nonce, attempt, role and code commit. The proof bytes are bound only by verifying. Another valid bundle for the same `popNonce` and devices would pass, and that is the same session. `test_e2e_frame1FieldsBoundWithoutSig` changes each field with `L`'s signature out of the picture, proofs mocked.

A bad proof reverts frame 1, so the tx is invalid and `L` pays nothing.

**Do xa and xb really name the signing keys? Yes, read from source, X only.** `check_signed` (oalib `lib.nr` 213-300) verifies the transcript signature with `px = t[40..72]` and takes `x_own` from those same bytes; the credential covers the same X and Y. `phone_core` hashes `x_own, x_partner` into `halfCommit` under `TAG_HALF` (527-534). The adapter requires `halfCommit == commit_a / commit_b`, and the pair circuit opens those with `(xa, xb)` and `(xb, xa)`. Limbs are `[hi, lo]`, the same split as `PopCtx.split`. Y is not committed: `(x, -y)` also matches, but that key is the negation of the same private key, and `sig[0]` still has to come from `newKey`.

**`valid_at`.** TIMESTAMP is banned in the prefix (sidecar `frameTx.ts`), so the ported check hangs off frame 0's deadline, which the expiry predeploy holds against the clock: `notBefore <= valid_at <= deadline + 300` and `deadline <= valid_at + maxAge`. That gives the old upper age bound or tighter. The future bound is looser than the old `now + 300`. Use `maxAge` of at least 1200, the 900 s window plus the 300 s skew: the deadline comes off the laptop's clock and `valid_at` off the server's (`t0_ms // 1000`), so at 900 a laptop running ahead of the server fails an honest early chirp, after the proving (`test_adapter_laptopClockAhead_maxAge`). Nobody pays, but Chrome's dedup means reload and chirp again. Raising it weakens nothing real, since the prover picks `valid_at` anyway.

**The pair verifier does not exist yet.** The contract requires an 11-input pair: the existing 7 plus `xa_hi, xa_lo, xb_hi, xb_lo`. `noir/pair` keeps `xa` and `xb` private, and the circuits are frozen for formal verification, so that change is gated on the user. Until then this path cannot accept a real proof.

| | Status |
| --- | --- |
| Account, adapter, nonce, device, issuer, config, POPCC1, window checks | forge, mock Honk verifiers (`EvpPresence.t.sol`, `EvpRecovery.t.sol`) |
| 12M VERIFY + 28,000 B through our sidecar | mined, but a burn loop, not this contract |
| Proof cost | cited for the old 7-input pair: phone 4.07M x2, pair 3.31M, 11.47M total (`../poc-verifier-gas/README.md`) |
| 11-input pair circuit, VK, verifier, its cost | never built |
| This account or the adapter on any EIP-8141 chain | never run |
| A real proof through `evpVerify` | never run |
| 30,052 B of frame data on chain | never sent; 28,000 B is the most sent |
| ethrex `max_verify_gas` above 12M | unknown |

**Stack.** The bundle needs POPT v2 transcripts and SBcred3 credentials, so sound-bound cannot feed it: it signs nothing. Mac Chrome + Android Chrome on sound-bound remains the only pair with 41 recorded sessions, and it no longer reaches this contract. The PoP web build is the candidate; laptop ZK is untried and no prover is wired to this flow. The Python verdict is off the critical path.

**Server gap.** `server/pop` cannot run this flow today. Written nowhere yet, all outside this folder: a context kind for EVP (`parse_session_in` only takes kinds from `consumers.kinds`, and its `validate` must recompute ctx from `chain_id`, `consumer`, `newKey`, `recoveryNonce`, `sessionTag`, `deadline`); a way to take a context without World ID (a context forces `policy.human = worldid` today, `main.py` 166-167 and 188-190); and `POP_CHAIN_ID=1337`, since the default is Sepolia and the route refuses any other chain. Without a context the server picks a random nonce, and `commit()` then rejects a transcript over `popNonce`. No real session has run this sequence.

**Device keys.** The new phone's `newKey` must also be its PoP device key: it signs the transcript and, raw, ctx. A software key in the browser can do both. Both devices need an SBcred3 from the pinned issuer with expiry at or after `valid_at`, so the laptop's credential can lapse between enrolling and the recovery, and a brand-new phone needs one issued before it can chirp. Neither step is written.

**Still only what it is.** Pitch it as "a phone was in earshot of my laptop". In a recovery the new phone could be the attacker's, and one cheating endpoint can fake NEAR (2026-09-25 memo). Against a stolen laptop it proves nothing: the thief holds both devices.

**Sequence, fixed by ctx coming first and the laptop being role A.** The server makes the session's creator role A and fixes its nonce from `ctx_hash` at create time (`sessions.py` `role_of`, `create`). So the laptop must know ctx, then create the session. Chirp after ctx, EVP after the chirp.

1. Phone: make `N`. Show QR = `qx ‖ qy`. No session yet.
2. Laptop: scan with the camera, derive and pin `newKey`. Show account, `newKey` fingerprint.
3. Laptop: read `recoveryNonce`, pick `sessionTag`, `deadline = now + 15 min`, compute ctx. A nonce change means start over.
4. Laptop: create the session as host (role A) with the EVP context → `sid`, `notBefore`, `nonce`, invite. Stop unless `nonce` equals `popNonceFor(ctx, notBefore, sid)`. Show the invite QR.
5. Phone: scan the invite, join as guest (role B) with `N` as its device key. Laptop: if the guest's key isn't the pinned `qx, qy`, stop.
6. Both: clock sync, arm, chirp, each signing a transcript over `popNonce`. Then the proofs.
7. Laptop: `tokenField.setAttribute("nonce", evpNonce)` **before** the email field loses focus. Not `tokenField.nonce = …`: Chrome 156 reads only the attribute, and the IDL slot alone mints nothing with no error (`live-chrome/README.md`, failure 1 and the CSP run). Lowercase the email in the page. Type `alice@tawago.com`, Tab. Chrome mints in the background. `form.requestSubmit()`, `preventDefault()`, read the token.
8. Phone: sign ctx (one tap). Post the entry.
9. Laptop: build the tx with frame 1 data final, `L` signs the sig hash last, send through our sidecar.

QR decode on the laptop: Chrome's built-in `BarcodeDetector`, no vendored library.

Chrome dedups the same field + same email (LRU 5). A failed attempt means reload the page and chirp again. Put that in the demo risk list. Chrome's `iat` window is 5 min at mint. The body's `MAX_AGE` is 900 s, the same as the deadline, so a tx the expiry frame lets through never fails the body on age alone. Proving time now sits between the chirp and the token, inside that 15 minutes: not measured for this flow.

## 6. Contract changes (on `RecoverableP256Account`)

- Storage: `address laptop`, `bytes32 configHash`. Both set in the constructor. `setLaptop`, `setConfig` as `onlySelf` later.
- VERIFY: the 2-sig branch (section 4.1). Reuse `_pinSelfCall` for mode/target/selector, drop the length check for this frame.
- Body: `startRotationEvp(address newKey, bytes32 sessionTag, uint256 deadline, Config cfg, bytes token, uint256 offs) onlySelf` → verify, then the existing `startRotation` internals.
- `EvpVerifier`: nonce compare against `evpNonce(ctx)`; `iat` window from `block.timestamp`; already has `aud`, email, `cnf`, `sd_hash`.
- Tests: happy path with the vector above; wrong `L`; wrong `sig[0].msg`; deadline mismatch; other `aud`; other nonce; replay after cancel (nonce bump); 3-sig branch still green; finish before/after `readyAt`.
- `frame-lib.cjs`: a `evp-start-shape.cjs` like `gift-shape.cjs`: entry 0 explicit msg signed first, entry 1 over the sig hash last.

About a day with tests, per `account-design.md` §6. Same estimate here.

## 7. ENS: display only, and broken on Sepolia today

**Build 2c, and only if the user acts.** The issuer key, email hash and `aud` are pinned in `configHash` by the owner at deploy. Chain 1337 has no ENS. Nothing on the critical path reads ENS.

**What changed.** ENS moved the Sepolia v2 root (`ens-half/README.md` section 0). The Universal Resolver no longer finds `enconomy.eth`; in the new tree the label is available. So `alice.enconomy.eth` resolves nothing through ENS today, with or without our patch. Direct calls to our `MeetResolver.resolve()` still work.

**Default for the demo: no ENS on screen.** Show the 1337 account address. If a name is shown, the page calls `MeetResolver.resolve()` directly and the slide says "our resolver", not "ENS resolved it".

**Upgrade, all of it the user's keys and the user's call:**

1. Re-register `enconomy.eth` in the new tree. `ens.sh` hardcodes the old registrar, root and UserRegistry impl. Do not rerun `ens.sh bootstrap` blind.
2. Deploy the patched resolver (`ens-half/meetresolver-settext.patch`: `setText`, `setAddr` for coin types other than 60). New CREATE2 address.
3. Point `enconomy.eth` and `alice` at it.
4. Attester tx: config mirror multicall, 1.21M gas measured by `eth_estimateGas`.
5. Attester tx: `recovered` receipt after `RotationFinished`, 0.84M gas.

Only if 1 happens by Nov 5 noon. Otherwise ENS is cut.

**2a (DNSSEC oracle on 1337 + issuer registry): no. Decided Nov 3.** DS on tawago.com takes 1-2 days, `IssuerRegistry` is unwritten, the oracle deploy needs ~25M gas of 1337 ETH, the proof builder needs the user's dnspython, and `DNSSECImpl` fits the 2^24 cap with 0.6% headroom. ENS's own DNS path (DNSRegistrar, ENSIP-17) is broken by the root KSK 38696 rollover anyway. The 2c text in `ens-half/README.md` section 4 is what we say.

## 8. Prize: CROPS App

**One EF prize for this project: CROPS App.** Not the alt mempool.

**Corrected Nov 6: the start tx is no longer canonical-mempool admissible.** Its prefix is 12,021,500 against 100,000 and it calls precompiles and a foreign verifier in VERIFY, so it needs our own sidecar. Whether that still fits this prize is open. Cancel and finish are unchanged. `L` is a non-canonical payer, so ethrex keeps at most one `L`-paid tx pending at a time. Fine on stage.

The alt-mempool version exists on paper and fits: Option 1c issuer native entry (`msg = sha256(EVT signing input)`, 6,700) plus a VERIFY read of `issuerKey[keccak("tawago.com")]` from a shared registry. That is a foreign SLOAD, so alt mempool with a staked sender, prefix ~59k. Declined for Nov 5: it needs the oracle on 1337 feeding that registry (section 7 flip), 0.012 ETH stake for `A`, and funding (section 11). Without the oracle the registry is a setter anyone can see through.

CROPS lines for the README:
- C: the rule is contract code; any node running our sidecar config relays the start, the public one rejects it; no sponsor, no keeper, no beacon. The issuer and the PoP server can deny service, not forge.
- O: MIT in the first event commit (still TODO at repo root).
- P: the email string is in calldata. Public. Say it. Hash-only variants need a used-nonce record; not built.
- S: email proof + enrolled laptop key + a phone in earshot of the laptop (as far as its mic can tell) + 120 s owner cancel. Stolen laptop falls. Stolen phone (thief holds the owner key) is not covered: the thief cancels forever.

## 9. Attackers

| Attacker | Result | Why |
| --- | --- | --- |
| Remote phisher, own page | stopped | `aud` is their origin; and `newKey` only enters via the chirp session; and no `L` |
| Reverse-proxy phisher | stopped | Chrome sets `aud` from the committed origin |
| XSS / bad deploy on `recover.tawago.com` | **falls** | `L` is script-readable; Chrome mints with no prompt. Defense: dependency-free page, header CSP `default-src 'self'`, no inline script. Tested: a header CSP does not stop the dynamic `setAttribute("nonce")` from minting (`live-chrome/README.md`, CSP run). One factor left: the 120 s window |
| Stolen unlocked laptop, mail signed in | **falls** | thief holds `L` and the session, pairs any phone. Brakes: 120 s window, old phone cancel (absent in the lost-phone story), OS lock |
| Issuer key / server compromise | stopped | can mint any EVT, cannot sign with `L`. Falls together with the laptop |
| DNS takeover of `_email-verification.tawago.com` | stopped | Chrome would accept the new issuer; the account pins the old key. DNS is not on the chain path |
| Cloudflare account takeover | **falls** (same as XSS) | it runs DNS, registrar, Pages (the `aud` origin) and inbound mail. One login. Said in the README |
| Domain admin | as issuer | for a personal domain, that is Alice |
| Relayer / payer | nothing to gain | sig hash commits to every frame and byte; the email is public anyway |
| Replay of a mined token | stopped | ctx carries `recoveryNonce` and `deadline`; the KB `nonce` is ctx; `iat` window in the body |
| Junk recovery txs (griefing `A`) | stopped | `L` pays. Junk costs the submitter |
| Early `finishRotation` | accepted | only `N` can, burns its own future account's gas |
| PoP server lies NEAR | no effect on chain, once the 11-input pair exists | the chain never reads the verdict. The proofs need transcripts signed by both device keys. It cannot swap `newKey`: the laptop pins it from the QR and recomputes ctx itself, and frame 1 checks it. It holds the issuer key and the codes, so it can help a cheating phone, next row |
| Malicious new phone fakes NEAR with a relay | **falls** for the proximity leg only | audio is binding, not proof (2026-09-25 memo). One cheating endpoint is enough. Still needs `L` and the session |
| Stolen phone (thief has `owner`) | **not covered** | thief drains and cancels. Needs a guardian veto. Out of scope, in the README |
| Two tabs on one machine | n/a in v1 | with no guardian the rule `newKey != owner` is all there is |

## 10. Demo, 3 minutes

| t | Screen | Line |
| --- | --- | --- |
| 0:00 | explorer: `A`, `owner` = old key | "This account lives on a phone. The phone is gone." |
| 0:15 | laptop: the recovery page. Phone: page with QR | "No seed phrase. My email, my laptop, a new phone." |
| 0:30 | laptop scans the phone, phone scans the invite, arm, chirp, then the proofs (time not measured) | "The new key came in by camera, and a phone was in earshot of my laptop, as far as its mic can tell." |
| 0:50 | type the email, Tab. Token appears. Show `nonce` == ctx, `aud` == origin | "Chrome asked my domain's issuer. The token names this key and this chirp." |
| 1:10 | phone tap. Laptop sends. Explorer: `RotationStarted`, `readyAt` +120 s | "One transaction. My laptop paid. The chain checked the email itself." |
| 1:30 | attacker beat: replay the same tx with a new key → rejected in VERIFY; a copy of the page on another origin → token `aud` fails (offline check) | "Replay dies with the nonce. Phishing dies with the origin." |
| 2:10 | wait out the window (cut or canned: 120 s is 20 blocks) | "The old phone, if I still had it, could say no here." |
| 2:30 | finish. `owner` = new key. If the ENS upgrade happened: the receipt on Sepolia | "Recovered." (add "ENS has the receipt" only if section 7's upgrade landed) |
| 2:50 | one slide: what is checked where | "Keys and proofs in VERIFY on our own sidecar, email in the body frame, 120 s to change your mind." |

Say on stage what the demo Chrome runs with: `--enable-features=EmailVerificationProtocol`, `--auto-grant-email-verification-permission-for-testing`, and, on the harness, `--host-resolver-rules` and `--dns-txt-resolver-url-prefix`.

Risks:

- **Permission bubble.** Chrome stops at a native "Verify this email automatically?" bubble. CDP cannot click it. Either launch with `--auto-grant-email-verification-permission-for-testing`, or click "Verify" once by hand; whether that choice persists is unverified.
- **Silent nonce.** `el.nonce = …` mints nothing on Chrome 156. Only `setAttribute`. Same for an empty nonce or email: no request, no error.
- **Chrome version.** Chrome updated itself from .74 to .80 during one session. Pin or re-test the demo laptop's Chrome on the day.
- **Dedup.** Same field + same email: reload and chirp again on retry.
- **Clock.** The body allows `iat` up to 60 s in the future of `block.timestamp`. Compare the latest block timestamp with the laptop clock before the demo. Compare the server clock too: `valid_at` comes off it, the deadline off the laptop (section 5).
- **Email case.** `emailHash` is over the exact bytes. Lowercase in the page.
- **Block time** is 6 s (`SLOT_DURATION_MS=6000`).
- **LAN plumbing.** See section 11, plan A.

## 11. Nov 5-7 order

**Plan A is the local harness.** The real-DNS path is the upgrade. Plan A: `live-chrome/launch.sh` style Chrome with `--host-resolver-rules` mapping `recover.<domain>` and `<domain>` to one local server that serves the page, the issuer and the sound-bound session API. `aud` is still the real origin string, so the account deployed for plan A pins that string. Why: a Pages-origin page (`https://recover.tawago.com`) fetching the LAN sound-bound server needs CORS headers on that server and a certificate the laptop trusts (`fetch` gets no interstitial). Neither is built. The phone side already works through a self-signed cert (41 sessions, Android Chrome as role B). Deploy the 1337 account with the `aud` of the path you will use; do not mix.

**Only the user can do these.** Each one missing on Nov 5 morning means plan A.

| Step | Needed for |
| --- | --- |
| `_email-verification.tawago.com` TXT | Chrome finds the real issuer |
| `recover.tawago.com` CNAME + Pages deploy | the real `aud` origin |
| Issuer Worker deploy at the apex | real issuer paths |
| CORS + trusted cert on the sound-bound server, or skip and use plan A | Pages page talks to the LAN |
| ENS re-register + patched resolver + 2 attester txs (section 7) | any ENS on screen |
| DNSSEC | nothing now (2a is off) |

**Funding.** No faucet to rely on. The public devnet guide says there is none (`tmp/docs/guides_devnet`); the sidecar repo's own `devnet-readme.md` describes a gateway faucet, and ours returned 502 twice. Plan on the shared genesis key published on purpose in the sidecar repo (`deploy/devnet/genesis.values.env`, throwaway, devnet only). Send plain transfers with gas limit 250,000: a brand-new account costs 183,600 state gas on this network. Shared key means nonce collisions; retry.

Order:

1. Nov 5 morning, before any page code: fund a deployer and `L` from the genesis key. Deploy `A` with a test owner, `L`, and the plan-A config.
2. Build the real start tx (`evp-start-shape.cjs`, frame 3 state limit per section 4.1) and call `ethrex_simulateFrameTransaction` on `https://altmempool.forshtat.com` with `trace: true`. It takes no state overrides (`poc/clients/README.md`), so `A` must exist and `L` must be funded first. It answers: `prefixShape`, per-frame execution and state gas, whether 0x100 and 0x02 work in a SENDER frame, the real cost of `L`'s pay frame. Turns every MODELED number into MEASURED. The judges' Mumbai devnet may run another ethrex commit: ask.
3. Contract branch is done (`contracts/`, 158 forge tests, proofs mocked). Redeploy only if step 2 says so.
4. Recovery page: vendored keccak, `L` keygen, session create as host, QR via `BarcodeDetector` and the invite QR, `setAttribute("nonce")`, tx build.
5. Phone page: QR, invite scan, signing panel on the PoP web build's role-B page.
6. First end-to-end on the devnet.
7. Nov 5 noon: ENS upgrade go/no-go (section 7). Nov 6 noon: v1.1 go/no-go (phone gate).

Cut list for a green v1 by Nov 7: ENS 2a (already no), v1.1 guardian unless its gate passes, the Sepolia receipt unless the re-register happens. Keep: start, cancel, finish on 1337, the live token on stage, the replay and other-origin beats.

## 12. Open

- Real cost of `L`'s default-code pay frame. Source says 0 used + 3,000 entry; 8,000 limit stays. Simulate tells.
- `0x02` and `0x100` from inside a SENDER frame on the devnet: untested until step 2.
- `COLD_STORAGE_ACCESS_AMSTERDAM` is 2,100 in our ethrex checkout, though a comment says EIP-8038 raises it to 3,000. If the devnet runs 3,000, frame 1 loses a few thousand of its roughly 204,000 margin, small next to the unmeasured 11-input pair, and body and cancel/finish margins shrink too. Check the devnet's commit.
- Phone raw-digest signing on Pixel and iPhone (Nov 4). Gates only the upgrade and v1.1.
- The server's EVP context kind, no-World-ID path and chain id (section 5), and the phone signing panel. Not written. Section 5 says why sound-bound no longer feeds the contract.
- Whether one manual "Verify" click persists across runs.
- `issuer-worker` is demo-grade: constant HMAC cookie, no logout. Said in the README.
- The EVT says `exp = iat + 300`; the body accepts up to 900 s. Not a hole (ctx and the expiry frame bound the attempt), but say why if asked.

Closed since the first version: devnet block time (6 s), state gas on the pending write (no fresh slot), live Chrome token from our issuer (15 minted, 15 verify), header CSP with dynamic nonce (works), 1337 ETH (genesis key), ENS 2a (no).
