# Frame account contracts

The ChirpGas sponsor, its registry, HumanHub and their gas benches were removed from this repo. Older sections below still describe them and their test counts.

Written 2026-11-02. Forge only. No tx sent, no keys. One read-only `eth_call` to 0x100 on the public devnet.

Run: `forge test --offline` (78 tests).

**Update 2026-11-02, attester co-sign (`../09-gap-fixes.md` item 1):** `signatures[2]` is secp256k1 from the new immutable `ATTESTER` (the acoustic server's key) over the same D, else `NoAttest`. `SIG_COUNT` 3. Frame 2: 30,600 forge, 54,449 modeled first tx (limit 60,000). Sidecar sum 92,200. Golden vector now pins the attester's 65-byte entry; forge `vm.sign` and noble give the same bytes. Output: `results/2026-11-02-attester.txt`. The tables below are the pre-attester numbers.

**Update 2026-11-02, after `../04-refuter-report.md`:** D now commits to `sender` and `seq`. The deadline is pinned to `deadlineFor(T)`. Frame limits are re-cut to 4,000 / 12,000 / 60,000 (sum 89,400), and forge runs them with the ethrex charges modeled. There's a golden vector shared with the JS builder. Why: `../05-design-fixes.md`. Output: `results/2026-11-02-design-fixes.txt`. Probe + its gas need P256VERIFY: `FOUNDRY_PROFILE=osaka forge test --offline --match-contract Probe -vv`. Gas: `forge test --offline --match-contract GasBench -vv`.

## What's here

| File | What |
| --- | --- |
| `src/ChirpGasSponsor.sol` | Frame 2 of the plan. Pins 4 frames and 2 sigs, reads the expiry deadline, pins frame 3 to `MeetBook.met(B, transcript)`, checks the beacon `keccak(T, salt) == R`, freshness, B's sig over D, the registry reads, the key count / key-set hash / epoch key / seq, max cost, then APPROVE(payment). `stake()` / `unlockStake()` / `withdrawStake()` forward to the staking registry. `ChirpGasSponsorSixHelpers` is the same logic on the old helpers, kept only for the gas comparison |
| `src/ChirpHumansRegistry.sol`, `src/IHumansRegistry.sol` | `register(device, account, nullifier)`, `humanOf`, `accountOf`, `deviceOf`, `beat()`. One device per human, and re-registering is rate-limited (`REREGISTER_DELAY`, deploy with 1 hour, see `../07-round2-fixes.md` S3). `beat()` takes T from `block.timestamp` itself and writes `keccak(T, salt)` to 0x..8272. It also stores `lastBeatT` for the heartbeat fallback |
| `src/MeetBook.sol` | The user action. It emits `Met(account, partnerDevice, transcript)` |
| `src/frame/FrameEnvLiveMux.sol`, `gen_mux.py` | One helper that dispatches all six frame opcodes, replacing the six separate helpers. This is the plan's gas lever. Bytecode comes from `gen_mux.py` |
| `src/ProbeAccount.sol` | `self_verify` that STATICCALLs 0x100 with the geth vector, needs a 32-byte 1, then approves. Only `signatures[0].signer == owner` can use it |
| `src/RecoverableP256Account.sol` | Fallback I14. owner, guardians, `startRotation`, `cancelRotation`, `finishRotation`, timelock |
| `test/ChirpGas.t.sol`, `Recoverable.t.sol`, `Probe.t.sol` | Logic tests on MockEnv |
| `test/GasBench.t.sol`, `GasBenchProbe.t.sol` | Gas on the real contracts, see below. `test_budget_*` run each frame with what ethrex would leave it |
| `test/GoldenVector.t.sol` | Fixed inputs -> D, epoch key, key-set hash, deadline. `poc/clients` selftest asserts the same hex |

Sponsor tests: happy path, unregistered A, unregistered B, same human (two ways, see below), stale T, forged T, wrong key count, extra key, old epoch key, seq 4 ok / seq 5 rejected, max cost over, frame 3 not MeetBook, frame 3 wrong args or length, extra frame, partner signed another digest, second account on the same device, not entry point, epoch boundary, attester (missing entry, wrong scheme, wrong signer, bound to seq, attester without partner, other meeting). Plus registry rules, beat, and MeetBook.

Recovery tests: normal owner, stranger, explicit msg, happy recovery, duplicate guardian, non-guardian, guardian signed another key, stretched deadline, missing expiry frame, extra frame or wrong body call, new key must sign, finish before and after the delay, cancel by owner, replay after cancel, body functions only callable by self, pending key can only call finish, guardian set.

## Gas per VERIFY frame (forge, measured)

Method: the real contracts, but each helper address is etched with a stub. The stub has the same shape as the helper, except that instead of running the frame opcode it looks the value up in a table in its own code. Contracts are deployed in `setUp`, so every account and slot is cold in the test tx. The number is `vm.lastCallGas().gasTotalUsed` of the frame call, which is what the frame gas limit has to cover. Pricing is Cancun (cold account 2,600). The stub costs about 25-35 gas more per call than the real helper.

| Frame | 1 mux helper | 6 helpers |
| --- | ---: | ---: |
| Frame 2, `ChirpGasSponsor.pay` (incl. cold registry + 3 cold SLOADs) | **28,731** (29,143 after sender+seq went into D) | 50,543 (50,912) |
| Frame 1, P256Account (`only_verify`) | **5,261** | 14,599 |
| Recovery `self_verify` (3 sigs, 3 own SLOADs) | **20,513** | n/a |
| Recoverable normal `self_verify` | **7,887** | n/a |
| ProbeAccount (osaka, includes 0x100's 6,900) | n/a | 20,536 |

**Superseded, see the next table.** The old line read: sidecar sum = 13,400 sigs + 1,000 (frame 0) + 8,000 + 35,000 = ~57k. That was wrong. It missed the 3,000 frame-entry charge and the 20,000 keyed-nonce first use (04-refuter F2/F3, both confirmed in ethrex source).

Modeled for ethrex (`test_budget_*`). The body gets `limit - 3000 entry - 400 per cold account`. The APPROVE stub burns 20,000 (`gen_mux.py stub(20000)`):

| Frame | Modeled use | Limit |
| --- | ---: | ---: |
| 0 expiry (arithmetic) | ~3,050 | 4,000 |
| 1 P256AccountMux | 8,661 | 12,000 |
| 2 sponsor, first tx of the epoch | 52,992 | 60,000 (the plan's 45k OOGs, tested) |
| 2 sponsor, later tx | ~32,900 | 60,000 |
| sigs | 13,400 | |
| sidecar sum | | **89,400 / 100,000** |

Older note: With six helpers it would be ~89k, which is too tight. Amsterdam's cold account is 3,000, which adds ~400 per helper and ~400 for the registry. A recovery tx: 20,100 sigs + 1,000 + 25,000 = ~46k. Canonical intrinsic is extra and not in the sidecar sum.

The plan's estimates were 14k for the account frame and 35k for the sponsor frame. The six-helper numbers come in at 14.6k and 50.5k. The sponsor went over because I added the frame-3 pins and the `accountOf` read.

## Envelope contract (for the TS builder, item 2). This overrides the plan where they differ

```
frames (exactly 4):
  0 VERIFY  target=0x..8141  flags=0  data = be64(deadline)                 (8 bytes)
  1 VERIFY  target=null      flags=2  data = ""                             (sender = P256AccountMux(deviceA))
  2 VERIFY  target=sponsor   flags=1  data = pay((refIndex, T, beaconSalt, partnerDevice, transcript))
  3 SENDER  target=MeetBook           data = met(partnerDevice, transcript) (exactly 68 bytes)
signatures (exactly 3):
  [0] P256, signer = deviceA, msg empty (sig hash)                 -- signed LAST
  [1] P256, signer = partnerDevice, msg = D
  [2] SECP256K1, signer = sponsor.ATTESTER(), msg = D             -- 65 bytes v||r||s, v bare 0/1, low-s
D        = keccak(abi.encode(keccak("enconomy.ChirpGas.v1"), chainid, sponsor, sender, seq, S, R, deviceA, partnerDevice, transcript))
R        = keccak(abi.encode(uint256 T, bytes32 beaconSalt))   -- from the registry's Beat(T, salt, value) event
recent_root_references[refIndex] = (registry.sourceId(), S, R)   S = slot the beat landed in (usable from S+1)
epoch    = T / 86400            (NOT S / 14400)
nonce_keys = [sponsor.epochKey(epoch)]  nonce_seq < 5;  TXPARAM 0x0F = keccak(abi.encode(1, key))
deadline == deadlineFor(T) = min(T + 900, (T/86400 + 1)*86400 - 1)   (pinned, S3)
limits   = frame0 4000, frame1 12000, frame2 60000 (execution), state 0
```

Deploy order: registry, then MeetBook, then the sponsor (it needs `registry.sourceId()`), then each phone's P256AccountMux. Only after that, `register(device, account, nullifier)`. The registry stores `accountOf[device]`, and the sponsor requires it to equal `tx.sender`, so registering before the account exists means `WrongAccount` at admission.

ProbeAccount accepts any signature scheme on `signatures[0]`, on purpose: the laptop dry-run key will be secp256k1.

## Checked in ethrex source (tmp/ethrex, frame_tx.rs and docs/eip-8272.md)

- FRAMEPARAM 0x00 on a null-target frame returns the resolved sender (`frame.target.unwrap_or(ctx.tx.sender)`, line 544). So pinning frame 1 to `sender` works.
- FRAMEDATALOAD past the end zero-fills, it doesn't halt (around line 430). So `>> 192` on the 8-byte expiry data is fine.
- Operand order matches the mux: FRAMEPARAM `[param, frameIndex]` with frameIndex on top; SIGPARAM the same; FRAMEDATALOAD offset on top; RECENTROOTREFLOAD `[field, index]` with field on top.

## Decisions (user away)

1. **Epoch boundary: fixed, not just documented.** The epoch is now `T / EPOCH_SECONDS`, and VERIFY requires the deadline to fall in the same epoch. So a tx under key e can't land after e ends, and only one bucket is ever open: exactly 5 per epoch. The cost is a dead window from the epoch boundary until the first beat after it (up to 8 min a day). This differs from the plan, which derived the epoch from S. That is OK because the registry takes T from `block.timestamp` in `beat()`, so the keeper can't steer it either. `test_epochBoundary_oneBucket` shows the old-beacon tx being rejected after the boundary.
2. **`accountOf[deviceA] == sender`, a third foreign SLOAD.** Keyed nonces are per sender. Without this, one registered device could open N P256Accounts and get N×5 txs a day. `test_secondAccountSameDevice` covers it. It's also stake-gated, which doesn't change anything for the demo.
3. **Frame 3 pinned exactly**: mode SENDER, length 68, `met` selector, and partner + transcript equal to the attestation. Sig count is pinned to 3 (was 2 before the attester co-sign).
4. **Same human.** The real registry allows one device per human. Moving a human to B's device unbinds A's device, so that attack fails on `NotHuman`. The sponsor's `SameHuman` branch is only reachable with a raw registry. Both are tested.
5. **Recovery freshness without a keeper**: D commits to the expiry deadline. There's no 8272 reference, so no server is in the loop. The guardian app has to pick a deadline ~15 min out.
6. **Bug found in the old sketch**: `P256Account` had a `receive()`. A VERIFY frame with empty data goes to `receive()` and never APPROVEs. I removed it there and in the new accounts. The bench caught it: the frame used 55 gas.
7. New contracts use the mux helper. `P256AccountMux` is the frame-1 build target. `P256Account` keeps the six helpers (minus the `receive()` fix), for the old tests and the comparison.
8. **2026-11-02, refuter round.** D binds `sender` + `seq`: one partner signature = one tx (was: 5 txs per meeting). The deadline is pinned (`deadlineFor`). The `EpochBoundary` error is gone, because the pin's epoch clip covers it. I didn't touch RecoverableP256Account or ProbeAccount: their frame limits also need the 3,000 entry charge added when they're built for real.

## Measured outside forge

- `eth_call` to 0x100 with the vector on `https://altmempool.forshtat.com/rpc` returns `...01`. So the node HAS P256VERIFY. Whether the sidecar lets a VERIFY frame touch it is now settled from source: it does not. CODE_ACCESS rejects any call target with code size <= 2 that is not in `precompiles`, and live `precompiles` is `[]` (`../notes/precompile-rule.md`). ProbeAccount should come back with `payer accesses un-deployed contract address 0x...0100 with opcode STATICCALL`; a green result means the Mumbai sidecar has `precompiles` set.

## Untested

- Nothing here has run on an EIP-8141 chain: the mux bytecode, the 0xB6 helper, FRAMEDATALOAD on the body frame, APPROVE through the mux DELEGATECALL.
- The gas numbers are forge with stubs, plus modeled ethrex charges (entry 3,000, Amsterdam +400 per cold account, 20k nonce first use). Not a real ethrex run. Warm state does carry across frames (read in vm.rs `commit_backup`, not run).
- The stake flip, i.e. that the three registry reads are rejected unstaked and admitted staked. That's the Nov 5 dry run.
- The ProbeAccount dry run against the sidecar. Expected red on CODE_ACCESS (from source); the run only confirms.
- Registry `beat()` against the real 0x..8272. In forge the call goes to an empty account.
- Sponsor griefing (S3): the pinned deadline narrows it but doesn't close it. Two colluding registered humans re-signing every beat can still get the sponsor banned on one sidecar node. See `../05-design-fixes.md`.
- Recovery griefing: a pending key holder can send early `finishRotation` txs that revert in the body and burn the account's gas. The owner should cancel. Theft (thief holds the owner key) isn't covered: the thief can cancel forever.

---

## W4 Gas Gift (`../08-wildcards.md` W4), 2026-11-02

B's own phone account pays for A's tx. No sponsor, no registry, no stake, zero SLOAD. The fallback if staking or the registry breaks on stage.

Files: `src/GiftP256Account.sol` (P256AccountMux + `gift(cap)`; P256Account.sol untouched), `test/Gift.t.sol` (26, MockEnv), `test/GasBenchGift.t.sol` (5), `test/GoldenVectorGift.t.sol` (1), builder `../poc/clients/gift-shape.cjs`. Output: `results/2026-11-02-gift.txt`. Run: `forge test --offline --match-contract Gift -vv`.

```
frames (exactly 4):
  0 VERIFY  target=0x..8141  flags=0  data = be64(deadline)
  1 VERIFY  target=null      flags=2  data = ""            (A's P256AccountMux, entry 0)
  2 VERIFY  target=giftB     flags=1  data = gift(cap)
  3 SENDER  target=any                data = A's call
signatures (exactly 2): [0] A, P256, sig hash   [1] B = giftB.owner, P256, msg = D
D = keccak(abi.encode(keccak("enconomy.Gift.v1"), chainid, giftB, sender, TXPARAM 0x0F keysHash, seq, deadline, cap, bodyHash))
bodyHash = keccak(frame3.target || frame3.data)        TX_MAX_COST <= cap        approves PAYMENT only
```

Gas (forge stub + modeled ethrex, same method as above):

| | Use | Limit |
| --- | ---: | ---: |
| gift frame, measured | 13,967 | |
| gift frame, A on key 0 (legacy nonce) | 17,367 | 20,000 |
| gift frame, A on a fresh keyed lane (+20k first use) | 37,416 | 40,000 |
| sidecar sum, 4k + 12k + gift + 2 x 6,700 | | 49,400 / 69,400 |

The wildcard's ~15k was low (20 mux calls + body hash); the budget has room, so I raised the limit, didn't trim checks.

Decisions (user away):
1. **Explicit D, not B over the sig hash.** The sidecar estimate rewrites body limits, which moves the sig hash (`../poc/clients/README.md` gotcha 1). D leaves out fees and limits; `cap` bounds them. So B's phone signs once, and the estimate copy and the send share B's entry (`gift-shape.cjs selftest` checks it). Cost: B trusts `cap`, not exact fees.
2. **D binds the key-set hash and seq**, so one gift = one tx. ethrex rejects empty `nonce_keys` (`transaction.rs` ~2675), so there is no zero-key replay. "First tx only" is B's app's policy, not on-chain.
3. **Payment only.** Flags 2/3 on the gift frame revert. B's entry over the sig hash (msg empty) is refused, and a ChirpGas partner entry (other domain) can't match D.
4. B's account must hold ETH: APPROVE(payment) debits `max cost` from the frame target (`frame_tx.rs` apply_approve). Unused gas is refunded to B (`vm.rs` ~3291).

Untested: never run on ethrex/sidecar. Admission as a non-sender payer (canonical: one pending tx per non-canonical paymaster, 08-wildcards) is unchecked. FRAMEDATALOAD at offset 64 of the body frame is untested on a chain.

---

## W1 HumanHub (`../08-wildcards.md` W1), 2026-11-02

One staked contract is sender and payer for every human. Quota = the protocol's nonce counter for `key = keccak(DOMAIN, hub, humanOf[A], epoch)`, `seq < 5`. Registry stays foreign (`ChirpHumansRegistry`, unchanged). An alternate to ChirpGas, not a replacement: `ChirpGasSponsor.sol` and its tests are untouched.

Files: `src/HumanHub.sol`, `src/HumanMeetBook.sol` (body, records humans keyed by caller), `test/HumanHub.t.sol` (37, MockEnv), `test/GasBenchHub.t.sol` (4), `test/GoldenVectorHub.t.sol` (1), builder `../poc/clients/humanhub-shape.cjs`. Output: `results/2026-11-02-humanhub.txt`. Run: `forge test --offline --match-contract 'HumanHub|Hub' -vv`. Full suite green on default and osaka.

```
frames (exactly 3), sender = hub:
  0 VERIFY  target=0x..8141  flags=0  data = be64(deadlineFor(T))
  1 VERIFY  target=null      flags=3  data = verify(Attestation)      self_verify, APPROVE(3)
  2 SENDER  target=HumanMeetBook  value 0, gas >= 60k  data = met(hA, hB, transcript)
signatures (exactly 3), none over the sig hash:
  [0] A P-256 msg=D   [1] B P-256 msg=D   [2] attester secp256k1 msg=D
D = keccak(abi.encode(keccak("enconomy.HumanHub.v1"), chainid, hub, key, seq, S, R, devA, devB, transcript))
```

### Gas vs ChirpGas

| | ChirpGas | HumanHub |
| --- | ---: | ---: |
| Prefix limits | 4k + 12k + 60k | 4k + 60k |
| Signature entries (2 P-256 + 1 secp256k1) | 16,200 | 16,200 |
| **Sidecar sum** (cap 100k) | **92,200** | **80,200** |
| Paying frame, forge raw | 30,600 | 29,768 |
| Paying frame, modeled ethrex, first tx of epoch (incl. 20k nonce) | 54,449 | 53,617 |
| Account frame (P256AccountMux) | 8,661 | none |
| Foreign SLOADs | 3 | 2 (no `accountOf`) |

08's 77.4k is the same shape without the attester entry (09 item 1 added it to both). The hub limit could drop to 56k (sum 76.2k); kept at 60k for margin. The hub frame does more checks than ChirpGas frame 2 (entry 0 msg, body value, gas floor, two body words, tip), and they eat what the dropped SLOAD saved. The real saving is the whole frame 1.

### What it buys

- **Quota per human, not per account.** A second phone, a re-register, or a new account all land on the same key. `test_secondDeviceSameHuman` and `test_reregisterKeepsKey` pass with no extra code. ChirpGas needs `accountOf` plus `REREGISTER_DELAY` for this.
- **Concurrency.** Self Relay shape: the sidecar resolves the role to payer = sender (`frameTx.ts` `resolveRoleAddr`). `reputation.ts` `exempt()` skips the per-entity cap for keyed self-pay txs. `checkNonceKeyConflict` allows one pending tx per (hub, key). So: one pending per human, N humans pending at once on one sender.
- **No per-user account to deploy.** P256Account leaves the critical path.
- **Estimate copy = send copy.** D has no fees and no limits, so the sidecar's 10M body rewrite doesn't touch any signature. No second phone signature (`humanhub-shape.cjs selftest` checks it).

### What it costs

- **Stake is chosen, not forced.** The hub is the sender, so its own storage is free. Stake is needed only because the registry stays foreign (`unstaked payer accessed <registry>`). The slide should say so (08 cost list).
- **The envelope has no owner.** Anyone holding the three signatures can re-wrap it: fees, limits, hash. The hub pins every spending knob:
  - frame count and layout;
  - body target, mode, words, and `value == 0` (a SENDER frame spends the hub's ETH);
  - body gas `>= MIN_BODY_GAS` (a starved body would burn the human's seq);
  - `max_priority_fee <= MAX_TIP` (TXPARAM 0x03; caps what a re-wrapping builder pockets);
  - `max cost <= MAX_COST`.
- **Deviation from 08: `maxCost` is not in D.** TXPARAM 0x06 is `max_fee x total_gas_limit` (intrinsic, calldata and signature costs included), which the phone can't compute at the meeting, and a golden vector would have to copy ethrex's gas formula. The tip cap plus the cost cap bound the same thing.
- **One reputation entity for everyone.** A griefer's dropped txs throttle the hub, and that hits every human. ChirpGas's sponsor has the same exposure.

### Linkability tradeoff

ChirpGas: the nonce key `keccak(DOMAIN, sponsor, epoch)` is the same for everyone, so the key says nothing. Linking a tx to a human takes two registry reads: `accountOf` gives sender to device, `humanOf` gives device to nullifier. A new phone means a new account and a new sender.

HumanHub: the sender is the same for everyone, but the key carries the human, in clear, in the envelope. Nullifiers are public (`humanOf` storage, `Registered` events). So anyone can compute `humanKey(h, epoch)` for every registered human and every day, and bucket every hub tx by human:
- from the mempool, before inclusion, with no state read;
- across phone swaps and re-registrations (that's the quota feature itself);
- with seq showing how much of the day's quota is used.

The device address in entry 0 is visible in both designs, so "who" doesn't get worse. "Stable across devices" and "readable without state" do. It can't be fixed inside VERIFY: the hub has to derive the key from public data with keccak, and an unlinkable per-human quota needs a ZK nullifier, which doesn't fit under 100k with precompiles banned. World ID nullifiers are app-scoped, so this doesn't link outside the app. The MeetBook graph is public in both designs anyway. ChirpGas makes no privacy claim (README P row), and this keeps it that way. Say it on the slide.

Untested: never run on ethrex or the sidecar. Not exercised anywhere yet: a self_verify sender that reads foreign storage while staked, scope-3 APPROVE through the mux DELEGATECALL, TXPARAM 0x03 and FRAMEPARAM 0x08 / 0x01 on a chain, FRAMEDATALOAD at body offset 68. The GasBench base tables only hold offsets < 64, so `GasBenchHub` etches offset 68 itself. The stake flip for this shape still needs a Nov 5 dry run (gate in 08).

---

# VERIFY-frame design constraints under ERC-8421: humans-only sponsor (A) and zone pool (B)

Written 2026-11-02. Read-only work. No transactions, no keys. Read-only RPC calls only (`skandha_config`, `eth_getCode`, `eth_getBlockByNumber`, `admin_nodeInfo`, one `ethrex_simulateFrameTransaction` dry run).

## TL;DR

1. **A fits today's devnet, even unstaked, if VERIFY reads no storage.** Three envelope features replace storage. Humans root: an EIP-8272 recent-root reference. Partner proof: a second P-256 signature entry with an explicit digest. Daily quota: a keyed nonce (`key = keccak(sponsor, epoch)`, `nonce_seq < QUOTA`). The sketch (`src/HumansOnlySponsor.sol`) does zero SLOADs and calls no precompile.
2. **Freshness works without TIMESTAMP.** Lower bound: the slot of a recent-root reference. The protocol guarantees `1 <= head_slot - S <= 8191`, and the partner signed over a root that was unpredictable before S. Upper bound: an `expiry_verify` first frame. The protocol enforces `deadline >= block.timestamp`. Our VERIFY reads the deadline with FRAMEDATALOAD and requires `deadline <= time(S) + WINDOW`. Without the lower bound, a user could pick a future epoch and burn future quota now.
3. **Stake still matters for A, but for throughput, not storage.** An unstaked sponsoring payer may have only about 10 pending txs. Staked and ACTIVE has no cap. The storage version (A2: own-storage quota written in a `pre_verify` frame) needs stake, and it adds a reputation risk that A1 does not have: a quota race.
4. **B cannot be admitted on today's sidecar, staked or not.** Its storage story is clean: no SLOAD; nullifier = keyed nonce; root = recent-root reference. Two things block it. Groth16 verification costs about 242k–263k gas, above the hard 100,000 cap (the code has no staked budget). Also, the verifier's precompile calls hit CODE_ACCESS, because live `precompiles` is `[]`. Noir UltraHonk (2.73M gas) does not fit even the ERC's 1M staked budget.
5. **P-256 phones need a contract account.** ethrex default code approves only SECP256K1 entries. `src/P256Account.sol` is about 20 lines and reads no storage.

## Sources

| Short name | What | Link |
| --- | --- | --- |
| ERC | ERC-8421 draft, PR #2028 @ 493ba8ac | https://github.com/ethereum/ERCs/raw/493ba8ac3be97dc5cf6335eb97d2e8e9f95983c5/ERCS%2Ferc-8421.md |
| SC | sidecar (skandha fork) @ 2e22ff0a, the code the devnet runs | https://github.com/forshtat/mempool-workshop-sidecar/tree/2e22ff0a2898e69ea4bf5275bce1be8581a8582a |
| SC/frameTx | opcode, storage and code rules | `packages/executor/src/services/UserOpValidation/validators/frameTx.ts` |
| SC/prefix | shapes, gas cap | `packages/executor/src/services/UserOpValidation/utils/validationPrefix.ts` |
| SC/rep | pending caps, seen/included | `packages/executor/src/services/MempoolService/reputation.ts`, `.../ReputationService.ts`, `packages/executor/src/entities/ReputationEntry.ts` |
| EX | ethrex eip8141-tracer @ 9aa3645d, the node the devnet runs | https://github.com/forshtat/ethrex/tree/9aa3645d795945c64400f41a70aace0edfa7f383 |
| EX docs | `docs/eip-8141.md`, `docs/eip-8250.md`, `docs/eip-8272.md` in EX | same tree |
| LIVE | `skandha_config` and node info, https://altmempool.forshtat.com/rpc and https://altmempool.forshtat.com | queried 2026-11-01 19:00 UTC |

Local clones: `../tmp/mempool-workshop-sidecar`, `../tmp/ethrex`. Earlier notes: `../notes/altmempool-erc8421.md`.

## Rule-by-rule table

"SC" is what actually runs on the devnet. Where SC and ERC disagree, design for SC on the devnet and for ERC long term.

| Rule | ERC-8421 draft | Sidecar code (what runs) | ethrex | A1 (no-storage sponsor) | B (zone pool) | Status |
| --- | --- | --- | --- | --- | --- | --- |
| Prefix shapes | PREFIX-010: `[self_verify]`, `[deploy,self_verify]`, `[only_verify,pay]`, `[deploy,only_verify,pay]`; `pre_verify` before any approving frame; optional leading `expiry_verify` | Same 12 shapes (SC/prefix 178-216) | ethrex recognizes `pre_verify` in simulate RPC only (EX `docs/superpowers/specs/2026-09-29-pre-verify-frame-recognition-design.md`) | `[expiry_verify, only_verify, pay]` | `[self_verify]` + one SENDER frame | VERIFIED |
| Verify gas | BUDGET-010: per entity, 100k unstaked, 1M staked | One sum over the whole prefix + signature cost <= 100,000, no stake lookup (SC/prefix 10, 286-292) | Prefix-gas check is informational in simulate (EX `crates/networking/rpc/ethrex.rs` 445-560) | Fits (estimate below) | Does not fit: Groth16 242k-263k | CONTRADICTED for staked: ERC says "MAX_VERIFY_GAS_STAKED_ENTITY = 1_000_000"; SC has `MAX_VERIFY_GAS = BigInt(100_000)` only |
| Signature cost | Counts toward tx.sender (BUDGET-010) | Added to the one sum: SECP256K1 2,800, P256 6,700 (SC/prefix 24-28) | Same table | 2 x P256 = 13,400 | 0 (no signatures) | VERIFIED |
| State gas cap | None ("No cap on state gas") | `MAX_VERIFY_STATE_GAS = 500_000` (SC/prefix 44) | 500k in canonical | Not an issue (no writes) | Not an issue | CONTRADICTED: ERC "This document places no cap on state gas"; SC enforces 500k |
| Banned opcodes | EIP-8141 list; BALANCE/SELFBALANCE allowed when staked (OPCODES-010) | GASPRICE, GASLIMIT, DIFFICULTY, TIMESTAMP, BASEFEE, BLOCKHASH, NUMBER, SELFBALANCE*, BALANCE*, ORIGIN, GAS, COINBASE, SELFDESTRUCT, RANDOM, PREVRANDAO, INVALID, BLOBHASH, BLOBBASEFEE (SC/frameTx 68-87). *Allowed if `stake > minStake`, strictly greater (702) | Also bans SLOTNUM, TLOAD, TSTORE, CALLCODE; TIMESTAMP allowed only while code_address == 0x..8141 (EX `crates/vm/levm/src/vm.rs` 4180-4275) | Uses none. Gets time from envelope | Uses none | VERIFIED |
| Opcode scan depth | Whole frame | Recurses into every nested call (`getOpcodesInfo`, SC `UserOpValidation/utils.ts` 107-130) | Per executing contract | A STATICCALL into 0x..8141 from our code would show TIMESTAMP in a sub-call. So we read the expiry frame instead of calling the verifier | n/a | VERIFIED (code); the rejection itself is inferred, not run |
| SLOTNUM | Not listed (EIP PR #12066 open) | Not in SC banned set | Banned, but only reported as a canonical violation, which simulate no longer gates on (EX ethrex.rs 445-560) | Do not use it. It changes between admission and inclusion | Do not use | Inferred from code: SC would likely admit a VERIFY that reads SLOTNUM. Not tested |
| Storage: sender's own | STORAGE-010 always | `addr === sender` skipped for every role (SC/frameTx 745) | Canonical: only sender storage | P256Account uses only immutables | Pool storage free, but the sketch reads none | VERIFIED |
| Storage associated with sender in a non-entity contract | STORAGE-021/022 allowed (022 needs a staked factory) | Allowed, reads and writes, for any role (SC/frameTx 760-771) | Not allowed canonically | Not needed | Not needed | VERIFIED |
| Entity's own storage | STORAGE-031: staked only | `addr === entityAddr` -> needs stake (772) | Not allowed canonically | A2 only (humanOf, used) | n/a (pool is sender, so free) | VERIFIED |
| Foreign read | STORAGE-032: staked, read-only, non-entity contract | `writes[slot] == null` -> needs stake (774) | Not allowed | Avoided by the recent-root reference | Avoided | VERIFIED |
| Foreign write | STORAGE-033: staked, slots associated with entity | Non-associated foreign write always rejected (776-789) | Not allowed | None | None | VERIFIED |
| Writes in prefix | Only `deploy` and `pre_verify` (VERIFY is static) | Same; `pre_verify` = DEFAULT frame with same target as the next approving frame (SC/prefix 68-84) | Observer still flags SSTORE outside deploy, but simulate no longer gates on it | None in A1. A2 writes in `pre_verify` | None | VERIFIED (code). End-to-end inclusion of a `pre_verify` write not tested |
| `pre_verify` status | Approving frame MUST check FRAMEPARAM status 0x05 | Not checked by the node (cannot be) | n/a | n/a | n/a | VERIFIED; A2 sketch checks it |
| Precompiles | CALLING-040: 0x01-0x11 and P256VERIFY allowed | CODE_ACCESS rejects any touched address with code size <= 2 not in `precompiles` (SC/frameTx 810-827). Default `precompiles: []` (SC `config.ts` 671). LIVE: `"precompiles": []` | Tracer records contract size on every CALL-family target, no precompile skip (EX `crates/vm/levm/src/opcode_handlers/system.rs` 575-578) | Uses no precompile. No `sha256()` either (that is 0x02) | Groth16 needs 0x06/0x07/0x08: rejected | CONTRADICTED: ERC allows "the core precompiles 0x01 to 0x11"; SC rejects them on the live config. Rejection not run end-to-end (my dry run returned no trace because no frame approved payment). Settled from source 2026-11-02: `../notes/precompile-rule.md` |
| Nested CALL with value | Banned | Banned (561) | Banned | None | None | VERIFIED |
| OOG revert | Banned (OPCODES-040) | Banned (660) | n/a | Size frame limits with margin | Same | VERIFIED |
| P-256 signatures | SIGNATURE-010, explicit `msg` allowed | Off-chain check; signer = `keccak(qx‖qy)[12:]`; low-s required (SC `FrameTxService/signature.ts`) | Same; canonical low-s is a consensus rule | Partner entry: `msg = D`, `signer = B` | none | VERIFIED |
| Default code | n/a | n/a | Approves only a SECP256K1 entry over the sig hash (EX `opcode_handlers/frame_tx.rs` 877-915) | P-256 phone needs `P256Account` | Pool has code | VERIFIED |
| APPROVE in a helper | n/a | n/a | Requires `current_call_frame.to == frame target`; DELEGATECALL keeps `to` (frame_tx.rs 267-296) | Helper pattern works | Same | VERIFIED (code) |
| Recent roots | not in ERC | Passes `RECENT_ROOT` rule when ethrex checked them | Checked before frames: `1 <= current_slot - slot <= 8191` and committed; RECENTROOTREFLOAD 0xB6 reads envelope only (EX `docs/eip-8272.md`) | Humans root + freshness | Pool root + zone root | VERIFIED (code). LIVE: predeploy code at 0x..8272 present; blocks carry `slotNumber` (block 348673 -> slot 349197) |
| Expiry | PREFIX-080: drop when deadline < head time | Leading `expiry_verify` is skipped for shape and compliance, but its gas counts (SC/prefix 183, 250-292) | 26-byte predeploy: 8-byte BE deadline, reverts if `deadline < timestamp` (EX `crates/vm/system_contracts.rs` 110-124); LIVE code matches | Upper bound for freshness | Optional | VERIFIED |
| Keyed nonces | LIFECYCLE-010..030: contiguous seqs, same key+seq = replacement; 4 per (sender,key), 64 per unstaked sender | Keyed txs where the entity is the sender are exempt from caps (SC/rep 81-95) | Canonical pool: per-key holder; a second tx sharing any key is rejected unless it is a fee bump (EX `docs/eip-8250.md`) | Quota counter | Nullifier | VERIFIED |
| Sender pending cap | 64 unstaked, none staked ACTIVE | 4 linear txs; keyed txs exempt (SC/rep 132, constants.ts) | n/a | 1 pending per epoch key (ethrex pool) | No cap on SC | CONTRADICTED: ERC "SAME_SENDER_MEMPOOL_COUNT 64"; SC `MAX_MEMPOOL_USEROPS_PER_SENDER = 4` |
| Unstaked payer cap | `10 + inclusionRate * min(included, 10000)` | `10 + floor(rate*10) + min(included, 10000)` (SC `ReputationService.ts` 203-216) | n/a | About 10 pending network-node-wide until it builds history, or stake | n/a (self-pay) | CONTRADICTED: formulas differ |
| seen / included | Per entity; staked sender blamed for all (REPUTATION-330) | Payer and factory always bumped; sender only when staked (SC/rep 213) | n/a | Payer = sponsor accrues | Unstaked pool never accrues seen, so never throttled on SC | VERIFIED |
| Decay | `value * 23 // 24` hourly | Linear to zero after 24 h idle (`ReputationEntry.ts` 40-48) | n/a | Faster recovery on SC | same | CONTRADICTED |
| Stake | MIN_UNSTAKE_DELAY 86400, about USD 1000 | LIVE `minStake` 0.01 ETH, `minUnstakeDelay` 0; registry 0xd51c04d7a0b01124e84de152f4e56d9eecb22d2f | n/a | Stake > 0.01 (strict) for BALANCE | Same | VERIFIED |
| Whitelists | n/a | LIVE all empty, `relayOpsWithWhitelistedEntities: false` | n/a | no shortcut | no shortcut | VERIFIED |

## Design A: humans-only gas sponsor

### A1 (recommended): no storage in VERIFY

Frames:

```
0 expiry_verify  VERIFY flags=0 target=0x..8141  data=uint64 deadline
1 only_verify    VERIFY flags=2 target=null      sender = P256Account(device A)
2 pay            VERIFY flags=1 target=Sponsor   data=pay(Attestation)
3.. SENDER       user actions
```

Envelope: `signatures[0]` = A over sig hash (P256). `signatures[1]` = B over `D` (P256, explicit msg). `nonce_keys = [keccak(DOMAIN, sponsor, epoch)]`, `nonce_seq < QUOTA`. `recent_root_references[i] = (HUMANS_SOURCE, S, R)`.

`D = keccak(DOMAIN, chainid, sponsor, S, R, A, B, transcriptHash)`. The phones sign this 32-byte digest during the meeting, with no extra hashing. Android Keystore (digest NONE) and the Secure Enclave can sign a raw digest. This is an assumption; check it on the phones on day 1. Signers must normalize s to low-s.

| Question | A1 answer |
| --- | --- |
| Storage read in VERIFY | None. Humans root comes from RECENTROOTREFLOAD; constants are immutables (in code) |
| Storage written | None by code. The protocol bumps NONCE_MANAGER at APPROVE |
| Unstaked OK? | Yes for opcode and storage rules. Limit: about 10 pending sponsored txs (unstaked payer allowance) |
| Staked buys | Lifts the pending cap while ACTIVE (SC: stake is checked only when the cap is exceeded) |
| Gas | Estimate: sponsor frame 35k-50k (about 20 helper STATICCALLs, 6 cold; 2 Merkle proofs of depth 20 = 40 keccaks), account frame about 8k, 13.4k signature cost, expiry frame about 1k. Total about 60k-75k against the 100k sum. Not measured on chain. Amsterdam access-cost repricing could raise it |
| World ID | Used at registration only: leaf = keccak(account, deviceKey, nullifierHash), one leaf per nullifier. The devnet has no World ID verifier (v4 is on World Chain 480), so registration needs an operator or a bridge |

Freshness: see the section below. Quota: the epoch is `S / EPOCH_SLOTS`. Because `deadline <= time(S) + WINDOW` and the deadline must be in the future, S is within WINDOW of now. So only the current epoch, or the previous one at a boundary, is usable.

Reputation risks (A1):

- Expired before inclusion: dropped under PREFIX-080, but SC does not undo `seen`. Keep WINDOW at 10-15 min, not 1 min. Bound: ban needs `seen/10 > included + 50`.
- Same key, same seq twice: a replacement (LIFECYCLE-020) or a silent drop after inclusion (PROPAGATION-040). No penalty.
- Third parties cannot invalidate pending txs: nothing the frame reads can change. The humans root is keyed by raw slot, and it ages out only after 8191 slots, long after WINDOW.
- The sponsor's own balance: SOLVENCY reserves max cost per pending tx. Withdrawing sponsor ETH invalidates pending txs; that is the operator's fault.
- Not a mempool risk, but real: two signatures do not prove proximity. Two colluding humans can sign remotely. Proximity soundness stays in the acoustic protocol or its ZK proof, which runs off the VERIFY path. "Human pass" renting is not stopped either.

### A2 (contrast): storage version, needs stake

`src/HumansOnlySponsorStaked.sol`. Frames: `[expiry_verify, only_verify, pre_verify(consume), pay]`.

| Question | A2 answer |
| --- | --- |
| Storage read in VERIFY | `humanOf[sender]`, `humanOf[partner]`: the sponsor's own storage |
| Storage written | `used[human][epoch]`, in `pre_verify`, the sponsor's own storage |
| Unstaked OK? | No. SC: `unstaked payer accessed ... slot` (frameTx.ts 772, 798-806) |
| Gain over A1 | Per-human quota without a one-device-per-human rule; instant revocation |
| New risk | Quota race. N pending txs of one human all pass `consume` at the head. Only QUOTA land. The rest fail revalidation and count against the staked payer. Revocation also invalidates pending txs |

Pick: A1 as the build. Stake it anyway for the pending cap and for the "stake" story. Keep A2 as the slide that shows what stake unlocks, if the prize judges want "daily-quota paymaster" literally.

## Design B: zone privacy pool withdrawal

`src/ZonePool.sol`. Frames: `[self_verify(pool), SENDER(recipient, value = DENOMINATION - feeCap)]`.

| Question | B answer |
| --- | --- |
| Storage read in VERIFY | None. Roots: RECENTROOTREFLOAD (pool root + DAO zone root). Nullifier: TXPARAM 0x10. Payout: FRAMEPARAM. Verifier keys: in verifier code |
| Storage written | None by code. NONCE_MANAGER[pool, nullifier] goes 0 -> 1 at APPROVE (protocol). That is the nullifier set |
| Must check | `len(frames) == 2`; the payout frame's mode, target, value, empty data; one nonce key, seq 0; `max cost <= feeCap`; both root source ids. APPROVE covers every later SENDER frame, and the pool is the sender. An unpinned frame list lets a prover add frames that spend the pool |
| Unstaked OK? | Storage rules: yes. Pending caps on SC: keyed and self-pay, so exempt. An unstaked sender never accrues `seen` on SC, so it is never throttled |
| Public inputs | Roots enter the proof as BN254 field elements. A keccak root can exceed the field, so the pool tree and the DAO zone root must both be Poseidon (or truncated) roots. The sketch's `publishRoot` keccak placeholder is not proof-compatible |
| Blockers today | Gas: Groth16 verify 242k-263k (forge-measured under Cancun pricing, `research/worldid/notes/pool.md`; Amsterdam repricing of 0x06-0x08 not checked) > 100,000, and SC has no staked budget. Precompiles: 0x06/0x07/0x08 rejected while `precompiles: []`. UltraHonk 2.73M per proof (`research/worldid/notes/implementer-prompt-optA-noir.md`) exceeds even 1M |
| Staked buys | On the ERC draft: up to 1M per entity, enough for Groth16, not for UltraHonk. On SC: nothing for gas |
| Double spend | Same nullifier = same `(pool, key, seq 0)`, so it is a replacement, never two inclusions |
| Front-running | A copy with a higher fee still pays the same recipient. It only moves fee within feeCap |
| Reputation risks | Staked pool (REPUTATION-330) absorbs every failure. Failures come only from: references aging out (8191 slots = 13.65 h at 6 s), pool balance below reserved max costs, reorgs. Invalid proofs fail at admission, so they never count as seen. They still cost each node a ~250k-gas simulation (spam, handled by rate limits) |

Exits for B, in order of preference:

1. If the Mumbai devnets run per-entity budgets (ERC 1M staked, or the landing page's 2.5M) and populate `precompiles`: use Groth16 (circom) in VERIFY. Stake the pool. Ask Pierre/Alex on Nov 5.
2. Otherwise, run our own sidecar as a custom mempool: set `precompiles`, and patch `MAX_VERIFY_GAS` (it is a code constant, not config). ERC-8421 allows custom mempools. The demo then shows admission in our mempool, not the standard one.
3. Fallback that fits the standard mempool today: B-lite. The pool pays only for withdrawals that carry an A1-style fresh human attestation (cheap), and the proof is verified in a body frame. A junk proof costs the pool one fee, but only for a registered human under a quota. This costs privacy (the device signature links the human), so present it as a demo fallback only.

## Freshness without TIMESTAMP

| Mechanism | Gives | Rules | Cost / risk | Status |
| --- | --- | --- | --- | --- |
| EIP-8272 reference slot S (RECENTROOTREFLOAD field 1) | Lower bound if the root was unpredictable before S; protocol window `1 <= head - S <= 8191` | Envelope only, no storage, any stake | 127k gas per root write; root usable from S+1 | VERIFIED (code + live predeploy + live slot numbers) |
| `expiry_verify` frame 0, read with FRAMEPARAM/FRAMEDATALOAD | Upper bound: included at or before the deadline; mempool drops after | Frame exempt from tracing (PREFIX-100); its gas counts | Must be frame 0; at most one | VERIFIED (code + live bytecode) |
| STATICCALL to 0x..8141 from our VERIFY | Same upper bound, in-line | ethrex allows; SC scans nested opcodes and would see TIMESTAMP | Probably rejected on SC | Inferred, not tested |
| Epoch counter in own storage, bumped by a keeper | Coarse "now" | Staked read (STORAGE-031) | Each bump invalidates pending txs keyed to the old epoch -> reputation hit; accept current and previous to soften | Design option, not built |
| SLOTNUM in VERIFY | Exact slot | ethrex flags it; SC banned set lacks it | Mass invalidation at every slot. Do not use | Inferred |
| Freshness in a body frame | Anything | No rules | Sponsor pays for stale txs | Fallback |

Combined, A1 gets `time(S) < inclusion <= deadline <= time(S) + WINDOW`. `time(S) = GENESIS + S * 6` on the devnet. My estimate of GENESIS is about 1791464620, from two blocks (slot 328156 at t=1793433556, slot 349197 at t=1793559802; 6.0 s per slot). The live chain config has `derivedSlotTime: null`, so the slot comes from the CL. Confirm GENESIS before deploying.

## Solidity sketches

| File | What |
| --- | --- |
| `src/frame/FrameEnv.sol` | Opcode ids and virtual accessors |
| `src/frame/FrameEnvLive.sol` | Raw-bytecode helpers for TXPARAM, FRAMEPARAM, FRAMEDATALOAD, SIGPARAM, RECENTROOTREFLOAD (new; hegota-support 0.0.1 has none for 0xB6) and APPROVE |
| `src/P256Account.sol` | Sender account for a P-256 phone |
| `src/HumansOnlySponsor.sol` | A1 |
| `src/HumansOnlySponsorStaked.sol` | A2 |
| `src/HumansRegistry.sol` | Publishes `keccak(treeRoot, salt)` to 0x..8272 |
| `src/ZonePool.sol` | B |
| `test/Designs.t.sol`, `test/MockEnv.sol` | 15 logic tests against a mock envelope (no forge-std) |

Results: `forge build --offline` compiles with solc 0.8.28. `forge test --offline`: 15 passed. They cover the A1 happy path; stale deadline; quota used; old epoch key; same human; partner signed another digest; account signed by an unregistered key; not ENTRY_POINT. For the account: approves its allowed scope; rejects SECP256K1. For B: the happy path; an extra frame; nonce seq 1; fee above cap; proof bound to recipient. The tests check logic only. Gas numbers from the mock are meaningless (its envelope lives in storage). The helper bytecode and operand order follow the ethrex docs and hegota-support's devnet helpers. The new 0xB6 helper has not run on a chain.

Run: `cd poc-validation-rules && forge build --offline && forge test --offline`.

## Decisions taken (user away)

- A1 is the build target. A2 is a slide.
- Quota is per sender account. Each leaf is `keccak(account, deviceKey, nullifierHash)`, and the registry allows one leaf per World ID nullifier. So per account = per human. VERIFY binds the account (TXPARAM sender) to the device key that signed entry 0, and B's account to the key that signed entry 1. Device rotation must be rate-limited in the registry, or a human could reset quota.
- Two signature entries, not three: A's sig-hash signature already commits to the frame data that contains D.
- `EPOCH_SLOTS = 14400` (24 h at 6 s), `WINDOW = 900 s`, `QUOTA = 5` in tests. All are constructor parameters.
- B uses Groth16, not UltraHonk, for anything that must run in VERIFY.

## Day-1 checks (Nov 5), all with `eth_estimateFrameTransactionGas`

1. A1 end to end on the devnet: deploy P256Account, the sponsor and the registry, then dry-run. This confirms the 0xB6 helper, the gas sum and the expiry frame read.
2. A precompile call inside VERIFY: confirm the CODE_ACCESS rejection (expected from source, `../notes/precompile-rule.md`), and ask whether the Mumbai devnets set `precompiles`.
3. Whether the Mumbai devnets have per-entity budgets. This decides B.
4. Whether the phones can sign a raw 32-byte digest with P-256 and produce low-s (or normalize).
