# EVP recovery for a frame-tx account: account and tx design

Nov 3, 2026. Starting point: `../poc-validation-rules/src/RecoverableP256Account.sol`.
Goal: lost phone. On the laptop, prove your email with EVP. Chirp the laptop with a new phone. Rotate the account to the new phone's key with an EIP-8141 frame tx.
Privacy pools are out. Nothing here was run on a frame-tx chain. All gas is MODELED from our forge numbers plus the live charges, unless marked.

Marks: VERIFIED = primary source opened (our own code or results count). MODELED = our estimate. UNREACHABLE = could not check.

## 0. The rules this design has to live with

| Rule | Status | Source |
| --- | --- | --- |
| Prefix (VERIFY + pay) capped at 100k flat: sig costs + sum of prefix frame `execution` limits. Stake doesn't raise it | VERIFIED | `../2026-11-02-report.md`, sidecar `validationPrefix.ts:10` |
| Prefix frames can't call any precompile (0x100, 0x02 too). Body frames can | VERIFIED | `../notes/precompile-rule.md` |
| TIMESTAMP banned in prefix. Only clock: expiry predeploy frame 0, upper bound only | VERIFIED | report, `../notes/eip8141-family.md` |
| Native sig entries: scheme 1 secp256k1 2,800, scheme 2 P-256 6,700, run in Rust, not EVM. Explicit 32-byte `msg` allowed; P-256 checks it raw (no prehash). Low-s required | VERIFIED | eip8141-family §1, precompile-rule "Native signature schemes" |
| Frame entry 3,000 each. Keyed nonce first use 20,000 | VERIFIED (ethrex source, per report) | report |
| Foreign storage reads in prefix need a staked entity (alt mempool) | VERIFIED | report, `frameTx.ts` 745-806 |
| EOA payer via default code: needs a secp256k1 entry, empty msg (sig hash), signer == target, at index 1 when scope is payment only | VERIFIED (spec text in our notes) | eip8141-family "Payer selection" |
| APPROVE(payment) needs execution approved first; payer pays even if body frames revert; nonce burns at payment APPROVE | VERIFIED | eip8141-family APPROVE, 8250 |
| ethrex rejects empty `nonce_keys`; key 0 = legacy lane, no 20k | VERIFIED (our Gift notes, ethrex `transaction.rs` ~2675) | `../poc-validation-rules/README.md` W4 |
| EVP verify in EVM: 63,111 gas warm, uses 0x100 x2 and 0x02 x3 | VERIFIED (forge) | `../poc-evp-issuer/README.md` |
| Chrome makes the KB key; only `nonce` can bind token to our session | VERIFIED | `../notes/evp.md` §8 |

Sample token sizes (counted from `../poc-evp-issuer/sample-token.txt`, VERIFIED): EVT signing input 395 chars = 7 SHA-256 blocks. KB signing input 291 chars = 5 blocks. `EVT~` for sd_hash 483 chars = 8 blocks. Whole token 861 bytes.

## 1. Pieces common to all three options

**Actors.**
- Account `A`: the frame-tx smart account being recovered. Always the tx `sender`.
- Laptop: Chrome with the email session. Mints the EVP token. Holds a secp256k1 EOA `L` (rescuer key, test key in the demo).
- New phone: fresh raw-digest P-256 key `N` (raw-digest signing VERIFIED on Mac Secure Enclave, not yet on phones).
- Old phone: lost. Its key `owner` is still on chain.

**Account storage (own slots only).** `owner`, `pendingOwner` + `readyAt` (packed, one slot), `recoveryNonce`, `configHash` = keccak(issuerX, issuerY, emailHash, audHash). Optional `laptop` (enrolled L). The verifier gets the config in calldata and checks it against `configHash`: one SLOAD instead of four (idea from poc-evp-issuer README).

**Binding digest D.** The phone signs it during the chirp. The KB nonce carries it.

```
ctx = keccak(DOMAIN, chainid, A, N, recoveryNonce, transcriptHash, deadline)
EVP nonce attribute = "0x" + hex(ctx)          (Chrome puts it in the KB-JWT)
phone entry: scheme 2, signer N, msg = ctx       (explicit msg, raw digest)
```

Why explicit msg for the phone and not the sig hash: the sidecar estimate rewrites body limits and so moves the sig hash (`../poc/clients` gotcha 1, same reason Gift uses D). The phone signs once, at chirp time. The laptop signs the sig hash last, after the estimate.

The `proximity-sigcheck` agent uses the same field set (chainId, account, newKey, recoveryNonce, deadline, transcriptHash) in `vectors.json`. Align DOMAIN and encoding with it before coding.

**Proximity.** The chain sees signatures, not sound. `transcriptHash` (from the chirp) goes into ctx, so the token, the phone sig and the meeting are one bundle. It's a real second factor only if L is enrolled on the account in advance (`laptop` slot). Otherwise it only binds: anyone with your email session can chirp their own two devices, and only the timelock + old-key cancel stops them.

**ENS.** Chain 1337 has no ENS, so nothing in the prefix reads ENS. Three places it can go, cheapest first:
1. UI: `alice.eth` (Sepolia/mainnet) resolves to A's address on the devnet via a text record. Off-chain read only. Zero risk.
2. Setup: `configHash` comes from the email domain's issuer key, proven once via the ENS DNSSEC oracle (0.57-0.68M, once per issuer key, body/normal tx). Blocked today: tawago.com and enconomy.dev have no DNSSEC. Depends on the `ens-oracle-1337` agent getting an oracle onto 1337.
3. Body frame read: start reads the issuer key from an ENS/oracle-backed registry instead of `configHash`. Fine in a body frame (no storage rule there). In VERIFY it would be a foreign read: alt mempool + stake. Not worth it here.

**Freshness.**
- Body frame: `iat` in `[block.timestamp - MAX_AGE, block.timestamp + 60]`. TIMESTAMP is fine there.
- Prefix frame (only if EVP moves into VERIFY): parse `iat`, require `deadline <= iat + MAX_AGE`, where deadline is frame 0's data. The expiry predeploy enforces `now <= deadline`, so `now <= iat + MAX_AGE` follows. No TIMESTAMP needed. No lower bound, but `iat` is issuer-signed and Chrome only accepts iat within 5 min at mint.
- ctx commits to `deadline`, so a phone signature dies with its tx.

**Replay.** Three layers:
- `recoveryNonce` is in ctx and bumps on start, cancel and finish. Old tokens and old phone sigs die.
- The KB nonce is ctx, so one token = one attempt on one account on one chain.
- Protocol nonce: use key 0 (legacy lane). No 20k. A dedicated recovery lane `nonce_keys=[R]` costs 20k on first use and gains little, because the public mempool still allows one pending tx per sender.

## 2. Option 1: one-shot rotation in one frame tx

Owner flips to N inside one tx. No waiting.

### 1a. EVP in a body frame (works today)

```
0 VERIFY  target=0x..8141   flags=0  data=be64(deadline)                         limit 4,000
1 VERIFY  target=A          flags=2  data=""          (only_verify, scope EXEC)   limit 25,000
2 VERIFY  target=L (EOA)    flags=1  data=""          (default code, scope PAY)   limit 8,000
3 SENDER  target=A          data=recoverNow(N, transcriptHash, deadline, cfg, token, hints)
sigs: [0] P256 signer N msg=ctx   [1] SECP256K1 signer L msg=empty (sig hash)
```

- Sender A, payer L (laptop EOA). The new phone has no ETH, and the account must not pay for junk (see griefing).
- VERIFY (frame 1): layout pins (4 frames, frame 3 selector + self target), recompute ctx from frame 3 data with keccak, check sig 0 is scheme 2, signer == N from frame 3, msg == ctx. If `laptop` is enrolled, check sig 1 signer == laptop. Reads `recoveryNonce` (+ `laptop`). Own storage only.
- Body (frame 3): `EvpVerifier` (0x100 + 0x02 allowed here), config vs `configHash`, iat window, KB nonce == ctx, then `owner = N`, `recoveryNonce++`.
- Mempool: `[expiry, only_verify, pay]` is a public-mempool prefix. L is a non-canonical payer, so 1 pending tx at a time. Fine.
- Gas, prefix: 4,000 + 25,000 + 8,000 + 6,700 + 2,800 = **~46.5k / 100k** (MODELED; frame-1 limit is from the measured 20,513 recovery self_verify; L's default-code cost is UNREACHABLE, 8k is a guess with entry 3k). Fresh keyed lane: +20k.
- Gas, body: ~63k EVP + ~2.2k config SLOAD + ~5k owner SSTORE + ~5k nonce = **~75-80k** + ~15.8k calldata. No cap on body.
- Griefing: anyone who can make L sign can submit a junk token. Body reverts, L pays, A is untouched except the nonce bump. OK.
- Weakness: no window. Email session + a laptop key (any key if not enrolled) = instant takeover, and the old key can't cancel. Bad for a recovery story.

### 1b. EVP in VERIFY via native sig entries (depends on the SHA-256 PoC)

The trick: let the protocol check the two ES256 signatures as native scheme-2 entries with an explicit msg, and only compute the hashes in EVM.

```
sigs: [0] P256 N msg=ctx  [1] P256 issuer msg=sha256(EVT signing input)
      [2] P256 cnf key msg=sha256(KB signing input)   [3] optional laptop
```

VERIFY recomputes both SHA-256 in pure Yul (no 0x02), checks `SIGPARAM(1).signer == issuer addr` (keccak(qx||qy)[12:] from config) and `SIGPARAM(2).signer == keccak(cnf.x||cnf.y)[12:]` decoded from the EVT. Then the claim checks as in 1a, freshness via `deadline <= iat + MAX_AGE`. Issuer and Chrome sigs may be high-s; the laptop flips s -> n-s before submitting (still a valid ECDSA sig).

Prefix budget: sigs 3 x 6,700 = 20.1k (+2.8k L, or self-paid). Expiry 4k. That leaves ~70-75k for frame 1, of which ~15-20k is entry, SLOADs, layout and claim decoding (decode only the claim windows, not whole payloads). So SHA-256 gets **~50-55k for 12 blocks (7 EVT + 5 KB), i.e. under ~4.2k gas per block**. sd_hash adds 8 more blocks: drop it (the cnf key is fresh per request; poc-evp-issuer README already lists it as optional).

- If the Yul SHA-256 lands at or under ~4k/block: 1b fits. Self-paid works (junk fails in VERIFY, so no griefing). Public mempool, own storage only. That's the "EVP checked natively in the mempool" headline.
- If it lands at the plain-EVM norm (my guess ~8-10k/block single lane; the 4-lane SWAR compressor only helps with independent messages, and EVT and KB are just 2 chains): 12 blocks = ~100k+. Does not fit. Stay with body-frame EVP.

### 1c. Pin in VERIFY, check in body (no Yul SHA-256 at all)

Middle road, same idea as `threat-model.md` (fix inside VERIFY) and `proximity.md` option B.

- Add a native entry: scheme 2, signer = issuer, msg = sha256(EVT signing input) computed off chain. The protocol checks the issuer's P-256 sig in Rust, 6,700 gas, no precompile.
- VERIFY only checks `SIGPARAM(k).signer == issuer addr` (from `configHash`). It takes the msg as given.
- Body recomputes sha256 of the EVT input with 0x02 and requires it == that entry's msg. Then the usual EVP checks.
- Entries pass both checkers after s -> n-s (the sample KB-JWT was high-s): VERIFIED, `poc-native-evp/results/entries.txt`.
- Prefix: 1a + 6,700 = **~53k / 100k** (MODELED). Add the KB entry too and it's ~60k, but pinning its signer to the cnf key means decoding the EVT in VERIFY. Skip that.
- What it buys: junk tokens now need a real issuer signature to get past VERIFY. What it doesn't: any token from that issuer passes VERIFY (other users, stale tokens), because VERIFY can't see the email without hashing. So self-paid by A is still griefable by anyone who can mint at that issuer. With our own issuer for tawago.com that's only domain users; with a big issuer it's everyone. Keep L as payer unless the issuer is yours.
- Works the same as the start tx of option 2. Doesn't depend on the SHA-256 PoC.

## 3. Option 2: two-step, start then finish (recommended)

### Start tx

```
0 VERIFY  target=0x..8141   flags=0  data=be64(deadline)                         limit 4,000
1 VERIFY  target=A          flags=2  data=""          (only_verify, scope EXEC)   limit 25,000
2 VERIFY  target=L (EOA)    flags=1  data=""          (default code, scope PAY)   limit 8,000
3 SENDER  target=A          data=startRotationEvp(N, transcriptHash, deadline, cfg, token, hints)
sigs: [0] P256 signer N msg=ctx   [1] SECP256K1 signer L msg=empty
```

- Same shape as 1a. Only the body changes: it sets `pendingOwner = N`, `readyAt = now + DELAY`, `recoveryNonce++` instead of writing `owner`.
- The existing `startRotation(newKey, transcript)` is 68 bytes and `onlySelf`. Add a sibling `startRotationEvp` that verifies the token then calls the same internal logic. Keep the guardian path untouched.
- Storage, body: `pendingOwner`/`readyAt` share one slot (zero -> nonzero ~22.1k, plus EIP-8037 state gas), `recoveryNonce` ~5k. Body ~63k + ~2.2k + ~27k = **~92k** + calldata (MODELED).
- Prefix: **~46.5k / 100k**, same as 1a.
- Mempool: public. Own storage only. No stake.

### Cancel (old key, if you still have it, or a thief with the email but not the phone)

Normal owner tx: `[self_verify, SENDER cancelRotation()]`, already built and tested. Prefix ~ 7,887 measured frame + 3,000 entry + 6,700 sig, limit 12k: **~19k**.

### Finish tx

Already built: `RecoverableP256Account` VERIFY branch "1 sig, signer == pendingOwner", frames pinned to `[self_verify, SENDER finishRotation()]`.

```
0 VERIFY  target=A  flags=3  data=""            (self_verify, scope EXEC+PAY)   limit ~15,000
1 SENDER  target=A  data=finishRotation()       (4 bytes)
sigs: [0] P256 signer N msg=empty (sig hash)
```

- Sender A, payer A (self-paid; recovered accounts usually hold ETH). Or L again via `[only_verify, pay]` if A is empty.
- VERIFY: N is `pendingOwner`, layout pinned. Reads `owner`, `pendingOwner`. Prefix ~ **22k**.
- Body: `block.timestamp >= readyAt`, `owner = N`, clear pending, nonce++. ~15k.
- Known grief (README "Untested"): N can send finish before `readyAt`; VERIFY can't see time, so the body reverts and A pays. Only N can do it, so N only burns its own future account. Accept. The prefix has no lower-bound clock (expiry is upper bound only), so there's no cheap fix. Or let L pay finish too.
- No EVP in finish, so it doesn't care about the SHA-256 result.

### Why two-step wins

- Timelock + cancel is the only defense when the email gets phished. Lost phone: you wait DELAY. Stolen email: your phone cancels.
- Every heavy or precompile step sits in a body frame, which the live sidecar doesn't police. Works on today's rules whatever the SHA-256 PoC says.
- Demo: DELAY = 120 s (constructor already takes it).

## 4. Option 3: multi-member rule

Rule: k of n people at a domain (e.g. alice@tawago.com and bob@tawago.com) approve. Each brings an EVP token and a device that chirps with N.

```
0 VERIFY  expiry
1 VERIFY  target=A  flags=2   (checks N + each member device signs ctx; members = own mapping)
2 VERIFY  target=L  flags=1   (payer)
3 SENDER  target=A  data=startRotationMulti(N, ..., token_alice, token_bob, hints)
sigs: [0] N msg=ctx  [1] member1 device msg=ctx  [2] member2 device msg=ctx  [3] L sig hash
```

- Prefix: 4k + ~30k + 8k + 3 x 6,700 + 2,800 = **~65k** (MODELED). Fits.
- Body: two tokens ~126k + storage ~27k = **~155k** + ~32k calldata. Fine in a body frame, impossible in VERIFY (two tokens break 100k even with the native path: 24 blocks).
- Variant: one approval per tx (`approvals[recoveryNonce][emailHash] = true`), rotation starts when k is reached. Smaller txs, more state, more txs to demo.
- Org twist with ENS: the member list is the ENS name of the domain (`tawago.com` imported via DNSSEC), read in the body frame. In VERIFY that's a foreign read: alt mempool + stake. Only interesting if aiming at the alt-mempool prize.
- Upside: offboarded staff lose power when their mailbox dies. Downside for a 3-day hack: two humans, two Chrome profiles, three devices chirping, two tokens per demo. Too much surface.

## 5. Side by side

| | 1a one-shot, body EVP | 1b one-shot, native EVP | 2 two-step (start body EVP, finish native) | 3 multi-member |
| --- | --- | --- | --- | --- |
| Sender / payer | A / laptop EOA L | A / A or L | start A / L; finish A / A | A / L |
| VERIFY checks | layout, ctx, N sig, (L enrolled) | + issuer & KB entries, Yul SHA-256, claims, iat via deadline | start: like 1a. finish: N == pendingOwner, pinned layout | layout, N + k member device sigs |
| Body checks | EVP 63k, iat, rotate | rotate | start: EVP, set pending + readyAt. finish: readyAt, rotate | k tokens, set pending |
| Storage in VERIFY | own | own | own | own (ENS member list = foreign, staked) |
| Mempool | public | public | public | public (alt + stake if ENS read in VERIFY) |
| Prefix gas | ~46.5k | ~95k+ unless SHA-256 <= ~4k/block | ~46.5k / ~22k | ~65k |
| Body gas | ~80k | ~10k | ~92k / ~15k | ~155k |
| Replay | recoveryNonce in ctx + KB nonce, key 0 | same | same; nonce bumps start/cancel/finish | same, per attempt |
| Freshness | iat via TIMESTAMP in body; deadline in ctx | `deadline <= iat + MAX_AGE` + expiry frame | start like 1a; finish via readyAt in body | like 1a |
| Old key can cancel | no | no | yes | yes |
| Depends on SHA-256 PoC | no | yes | no (upgrade path only) | no |

## 6. Recommendation for the 3-day hack

Build **Option 2**, start tx with body-frame EVP, laptop EOA as payer.

- Reuses what exists: `RecoverableP256Account` (finish, cancel, timelock, nonce bumps, tests), `EvpVerifier` (63k, 15 tests), frame-lib builder, Gift's explicit-D trick.
- New code: `startRotationEvp` + a third VERIFY branch ("2 sigs: N over ctx + L over sig hash, frames pinned to [expiry, A, L, SENDER startRotationEvp]"), `configHash`, optional `laptop` slot. Roughly a day with tests.
- Enroll the laptop EOA as `laptop` at deploy. Then the pitch is honest: email + your laptop + your new phone in the same room, plus a 120 s window where the old phone can say no.
- ENS: use it as the name in the UI (Sepolia text record pointing at the devnet account) and as the stated route for `configHash` via DNSSEC once a domain is signed. Don't put it on the critical path.

**If the SHA-256 PoC comes back cheap** (12 blocks + overhead fit ~50k, i.e. <= ~4k/block): move the start check into VERIFY (2b = 1b's VERIFY + 2's pending/timelock). Then start can be self-paid by A, junk tokens die in the mempool, and the demo line becomes "the email proof is checked before anyone pays". Keep the body-frame version as the fallback build; the frame layouts differ only in frame 1's code and the sig list.

**If it comes back expensive:** Option 2 as above. Optional upgrade: pin the issuer entry in VERIFY and check its msg in the body (1c), ~53k prefix. Stops random junk; not other tokens from the same issuer, so keep L paying.

## 7. Open, in order of how much they change this

1. Yul SHA-256 gas per block (parallel agent). Threshold ~4k/block for the native path.
2. Real cost of L's default-code pay frame on ethrex (I guessed 8k limit). UNREACHABLE without a run.
3. Whether ethrex lets SENDER-frame code STATICCALL 0x100/0x02 on the Mumbai devnet (node has P256VERIFY: VERIFIED by `eth_call`; inside a frame body: untested).
4. EIP-8037 state gas for the pending slot write: separate `state` limit on frame 3, not modeled.
5. Phone raw-digest signing on Pixel/iPhone (still the gate from the Nov 2 report).
6. A live Chrome token from an ES256-only issuer, so the hints and claim offsets match real bytes.
7. Align ctx encoding with `proximity-sigcheck/vectors.json`.
