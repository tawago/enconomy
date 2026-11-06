# EIP-8141 family: frames, keyed nonces, recent roots, assertions

Checked 2026-11-02. Sources are the raw EIP files on `ethereum/EIPs` master.
Spec text quoted below is pinned to these commits:

- EIP-8141 at `dc5d5fa688` (2026-11-01, "Transaction nonce check boundary")
- EIP-8250 at `1a086d5c67` (2026-10-19)
- EIP-8272 at `5e32ce9abb` (2026-10-08)
- EIP-7906 at `9099f412d2` (2026-10-27)
- EIP-8081 (Hegotá meta) last touched `25b1952395` (2026-10-20)

Specs churn weekly. 8141 had about 40 commits since July.
The devnet build will likely lag master. Ask on Nov 5 which commit the devnet runs.

PoC script: `notes/poc/eip8141_poc.py` (stdlib only, `python3 -I`).
It reproduces the EIP-8272 test vector, shows the P-256 hashing trap below, and does the gas sums.

## 0. Recap claims, checked

| Recap claim | Verdict |
|---|---|
| 8141 scheduled for Hegotá | VERIFIED. SFI on 2026-08-27 (commit `e400af2874`, "SFI EIP-8141"). EIP-8081 lists only 7805 and 8141 as Scheduled. https://github.com/ethereum/EIPs/blob/master/EIPS/eip-8081.md |
| Hegotá Q2 2027, not confirmed | VERIFIED. ethereum.org: "Expected on mainnet Q2 2027 · Date not yet confirmed" (page updated Oct 2, 2026). EIP-8081 activation table is empty. https://ethereum.org/roadmap/hegota/ |
| 8250 and 8272 "on the proposal list but not scheduled" | Out of date. They are now CFI (Considered), one step above Proposed. Moved PFI to CFI at ACDE246 (commit `95176db61e`, 2026-09-24). Still not Scheduled. https://github.com/ethereum/EIPs/commit/95176db61e5751e44964fb5e0766412cf2bf6e9a |
| Recent roots is EIP-8272 | VERIFIED. "EIP-8272: Recent Roots for Frame Transactions", Draft, created 2026-05-15. https://eips.ethereum.org/EIPS/eip-8272 |
| 7906 status | CFI, moved at the same ACDE246. Not scheduled. |
| Toni argued 8250/8272 should join FOCIL + frames | VERIFIED in spirit. The EF Protocol Architecture post (Justin, Thomas, Toni, Vitalik) groups frames + keyed nonces + recent roots as a "Native privacy" bundle: "Keyed nonces let many users share the pool sender without competing for one linear nonce." 7906 only "Depending on its readiness." https://hackmd.io/@Nerolation/H19nO85VGe (post date not shown) |
| lightclient, "Frames are all you need", Sep 2026 | VERIFIED. Dated 2026.09.05. https://lightclient.io/blog/frames-are-all-you-need/ |
| 7906 = "POST_TX frame with a state-diff opcode" | CONTRADICTED by the current spec. The blog says "the POST_TX frame ... the TXDIFF and related instructions". The EIP now says: mode `ASSERT` = 3, opcodes `TXTRACE` (0xb6) and `EVENTDATACOPY` (0xb7). Same idea, new names. |
| Keyed nonce from a nullifier means "spends do not block each other" | Half true. Replay-independent, yes. But 8250 says: "This EIP preserves EIP-8141's limit of one pending frame transaction per sender in the public mempool." A shared-sender pool still gets one pending withdrawal at a time in the public mempool. Concurrency needs another mempool (alt mempool / custom rules). |
| Relayer-free withdrawals "may fit the public mempool" | Only if the verify part fits 100k gas. See section 6. A Honk or Groth16 verifier does not. |
| Signature aggregation is a "SIGNATURE frame mode" | Blog idea only. The concrete EIP is EIP-8288 "In-mempool signature and proof aggregation" (Vitalik, Coratger, Draft, created 2026-06-03). Not in EIP-8081 at all. |

## 1. EIP-8141 frame transaction, current shape

All claims in sections 1-5 are VERIFIED against the pinned commits above unless marked otherwise.

Type `0x06`. https://eips.ethereum.org/EIPS/eip-8141 . Payload:

```
[chain_id, nonce, sender, frames, signatures, fees, blob_versioned_hashes]
frames     = [[mode, flags, target, limits, value, data], ...]
limits     = [execution, state]
signatures = [[scheme, signer, msg, signature], ...]
fees       = [max_fee, max_priority_fee_per_gas]
```

Facts:

- `sender` is an explicit field. No outer signature over the envelope.
- 1 to 64 frames (`MAX_FRAMES`). Intrinsic 12000 + 475 per frame.
- Two gas budgets per frame: `execution` and `state` (EIP-8037 state gas). Neither borrows from the other or from other frames.
- `max_fee` is a single total-wei budget for execution, state and blob gas. Not per-gas.
- `value` is allowed only on `SENDER` frames.
- `ENTRY_POINT` is `address(0xaa)`. It is `caller` for `DEFAULT` and `VERIFY`.
- `ORIGIN` returns the frame's caller, not the old tx origin.
- Transient storage is wiped between frames.
- EIP-3607 is not applied. Contract accounts can be `sender`.
- Receipt: `[cumulative_gas_used, payer, [[status, [exec, state], logs], ...]]`. No tx-level status. Status 2 = skipped by a failed batch.

### Modes

| mode | name | caller | notes |
|---|---|---|---|
| 0 | DEFAULT | ENTRY_POINT | normal call, used for deploy and post-op |
| 1 | VERIFY | ENTRY_POINT | runs as STATICCALL. Only `APPROVE` may change context. Revert or halt = whole tx invalid |
| 2 | SENDER | tx.sender | needs `sender_approved == true`, else tx invalid |

EIP-7906 adds mode 3 `ASSERT`. EIP-8288 proposes another for signatures.

### Flags

- bits 0-1: allowed approval scope (0 none, 1 payment, 2 execution, 3 both).
- bit 2: atomic batch (`0x4`), only on DEFAULT/SENDER. Batches never contain VERIFY and never carry approval scope.
- bits 3+: reserved, tx invalid if set.

### APPROVE (0xaa)

Stack: `offset, length, scope`. It ends the frame like `RETURN` and sets tx-scoped state.

- Only code running as the frame's `resolved_target` may call it (`ADDRESS == resolved_target`). DELEGATECALLed libraries can too, so treat them as trusted.
- `scope` must be non-zero and inside `frame.flags & 3`.
- `APPROVE_EXECUTION` (2): only when target is `tx.sender`. Sets `sender_approved`. Once only.
- `APPROVE_PAYMENT` (1): reverts if `payer` already set, if target balance is short, or **if `sender_approved` is still false**. So execution must be approved first.
- `APPROVE_EXECUTION_AND_PAYMENT` (3): target must be sender. Does both.
- Payment approval bumps the sender nonce, sets `payer = resolved_target`, and takes `max_cost` from the payer up front. Unused gas goes back to the payer.
- If the frame that called APPROVE later reverts, the approval is rolled back.

### Payer selection

- `payer` = the target of the first surviving frame that runs `APPROVE` with payment scope.
- No frame sets `payer` → tx invalid.
- Validation prefix = frames up to and including that frame. The rest is the execution body.
- Payer can be the sender (scope 3), a paymaster contract, or any EOA via default code.
- Default code (empty-code target, VERIFY): needs a `SECP256K1` entry, empty `msg`, signer == target. Index 0 if the scope includes execution, else index 1. So an EOA sponsor puts its signature at index 1.
- Default code only accepts SECP256K1. A P-256 key cannot drive an empty-code account. You need deployed code.

### Signatures list

| scheme | name | bytes | gas |
|---|---|---|---|
| 0 | ARBITRARY | any, readable by `SIGDATACOPY` | 100 |
| 1 | SECP256K1 | v‖r‖s (65) | 2800 |
| 2 | P256 | r‖s‖qx‖qy (128) | 6700 |

- Protocol checks every SECP256K1/P256 entry before any frame runs. One bad entry = tx invalid.
- P256 signer address = `keccak256(qx‖qy)[12:]`. Low-s required. P256VERIFY itself accepts high-s, so normalize `s → n − s` before sending.
- Empty `msg` = signed over `compute_sig_hash(tx)`. That hash elides raw signature bytes but commits to their length. Pick fixed-length encodings.
- Raw bytes of protocol schemes are not visible to the EVM (kept for future aggregation). EVM sees metadata via `SIGPARAM`.

### New opcodes in 8141

| op | name | gas | what |
|---|---|---|---|
| 0xaa | APPROVE | memory only | see above |
| 0xb0 | TXPARAM(param) | 2 | type, nonce, sender, fees, blob count, sig hash (0x08), frame count, current index, sig count, state gas left |
| 0xb1 | FRAMEDATALOAD(frameIndex, offset) | 3 | read any frame's data |
| 0xb2 | FRAMEDATACOPY | like CALLDATACOPY | copy any frame's data |
| 0xb3 | FRAMEPARAM(frameIndex, param) | 2 | target, limits, mode, flags, data length, status, value, gas used |
| 0xb4 | SIGPARAM(sigIndex, param) | 2 | resolved signer, scheme, msg, length (ARBITRARY only) |
| 0xb5 | SIGDATACOPY | like CALLDATACOPY | raw bytes, ARBITRARY only |

All halt outside a frame tx. VERIFY code can read later frames' data. That is how a paymaster checks "the next frame pays me".

### Expiry verifier

Canonical contract at `0x81413f0cF12e9b6a49B1D0439E081c577D57FfFf`. A VERIFY frame with 8-byte big-endian deadline. Reverts if `block.timestamp > deadline`. In the public mempool it must be frame 0. Deployed by a keyless tx, not by the fork.

### Public mempool rules (8141 section "Mempool")

- `MAX_VERIFY_GAS` = 100,000. Covers signature checks plus the sum of `limits.execution` across the validation prefix.
- `MAX_VERIFY_STATE_GAS` = 500,000.
- Four accepted prefixes: `[self_verify]`, `[deploy, self_verify]`, `[only_verify, pay]`, `[deploy, only_verify, pay]`. An expiry frame may go in front.
- Validation may read only the sender's storage. No `TIMESTAMP`, `NUMBER`, `BALANCE`, `SLOTNUM`, `GAS` (except right before a call), etc.
- Calls to other existing contracts and precompiles are fine if they read no outside storage. So P256VERIFY (0x100) and SHA256 (0x02) are usable.
- Paymasters: a canonical paymaster (code-matched, timelocked withdrawals) can serve many. Any other paymaster gets 1 pending tx at a time.
- One pending frame tx per sender.
- Anything else goes to private or alt mempools.

## 2. EIP-8250 keyed nonces

https://eips.ethereum.org/EIPS/eip-8250 . Draft. CFI for Hegotá. Authors Thiery, Wahrstätter, lightclient, Vitalik.

- Replaces `nonce` with `nonce_keys` (list of uint256, at most 16, strictly increasing) and `nonce_seq` (uint64).
- `nonce_keys == []` = old account nonce.
- Otherwise each key has a counter in `NONCE_MANAGER` = `0x8250968C12e01A19d6F667b9B2F3b3A4d0e51cB7`, slot `keccak256(pad32(sender) ‖ key)`. The contract code just reverts. Only the protocol writes it.
- All selected keys must equal `nonce_seq` before the tx.
- `nonce_seq == 2**64-1` means single-use. Each key must be unused, and is burned forever. This is the nullifier mode.
- Consumed inside the payment `APPROVE`. It stays consumed even if later frames revert. Spent-once is atomic.
- Cost per key: 12,100 execution gas (intrinsic) plus 97,920 state gas on first use.
- With `MAX_VERIFY_STATE_GAS` = 500,000, only 5 fresh keys fit one public-mempool tx (PoC sum). The protocol max is 16.
- New TXPARAM: 0x0D legacy nonce, 0x0E key count, 0x0F keys hash, 0x10 first key.
- Security note from the EIP: verifier code must authenticate the whole key set (`TXPARAM(0x0F)`), not just key 0. Otherwise an attacker can add keys and burn them.
- Public mempool: identity becomes `(sender, nonce_keys, nonce_seq)`, but still one pending tx per sender.

Spec drift: the 8250 text shows `fees = [max_priority_fee_per_gas, max_fee_per_gas, max_fee_per_blob_gas]`. Current 8141 has `fees = [max_fee, max_priority_fee_per_gas]`. 8250 is stale on this point. Ask the devnet team which encoding they use.

## 3. EIP-8272 recent roots

https://eips.ethereum.org/EIPS/eip-8272 . Draft. CFI. Authors Thiery, Vitalik, Wahrstätter, lightclient. Requires 7843 (SLOTNUM) and 8141.

- One contract at `0x8272D9679689Ea2f307140CdF9002D27dC00Ffff`. Deployed by a keyless tx.
- Write: any address calls it with 64 bytes `salt ‖ root`. Source id = `keccak256(msg.sender ‖ salt)`. Stored at ring index `slot mod 8192`.
- Check: a VERIFY frame with `target = RECENT_ROOT_ADDRESS`, flags 0, value 0, state limit 0, and 1 to 16 tuples of 72 bytes: `source_id(32) ‖ slot(8, BE) ‖ root(32)`.
- A root written in slot S is usable from slot S+1 for 8191 slots. That is about 27.3 h, assuming 12 s slots. EIP-7782 (shorter slots) is not in Glamsterdam's Scheduled list (EIP-7773) nor in any EIP-8081 list, so 12 s holds for Hegotá as specced. If slots ever drop to 6 s, the window halves to about 13.6 h.
- Only the last write per `(source, slot)` counts. If you need several roots per slot, write one aggregate root.
- Public mempool order: `[expiry_verify?] [recent_root_verify?] [deploy?] [account validation] ...`.
- The frame's gas counts toward `MAX_VERIFY_GAS`.
- Account code finds the checked tuples with `FRAMEPARAM` and `FRAMEDATALOAD`. It must check target, mode, flags, length and `status == 1`.
- The root is opaque bytes32. The app decides what it commits to. The source can be any EOA or contract. No registration step.
- PoC: our keccak reproduces the EIP's test vector (`source_id b938…ca85`, `entry_hash 0a0d…51b8`, `storage_key 5f02…74c3`). The two domain hashes match the PUSH32 constants in `RECENT_ROOT_CODE`. VERIFIED locally.

## 4. EIP-7906 transaction assertions

https://eips.ethereum.org/EIPS/eip-7906 . Draft. CFI. Authors Forshtat, Nacson, Tirosh, Weiss, Svantes, Ankushin, lightclient.

- New mode `ASSERT` = 3. ASSERT frames must be a trailing suffix. They run read-only. `APPROVE` is not allowed.
- If an ASSERT frame fails, the whole execution body reverts. The validation prefix stays (fee paid, nonce used). The tx is still included.
- `TXTRACE` (0xb6, param on top, then index). Costs 100 gas each. Reads net diff since tx start: balances, storage slots, code hashes, nonces, events, gas pre-charge, gas payer. Sorted by address, then slot. Events in emit order.
- `EVENTDATACOPY` (0xb7) copies event data.
- Both halt outside an ASSERT frame.
- Accounts must check in VERIFY that their ASSERT frame is present. The protocol does not force it.
- Reference values should come from signed frame data or `before` values, not from state the body can change.

## 5. lightclient, "Frames are all you need" (2026-09-05)

https://lightclient.io/blog/frames-are-all-you-need/

- Goals: key rotation, crypto-agility, PQ via aggregation, sender/payer split, no relayers, privacy pools in the public mempool with FOCIL, programmable validity.
- Two properties: extensibility and observability.
- Extensions, none touching the envelope: expiry contract, recent roots, assertions (POST_TX / TXDIFF in the blog), SWEEP opcode (APPROVE plus refund redirect, not in any EIP I found), SIGNATURE frame mode (became EIP-8288).
- Revert protection is named as something the public mempool can't do safely.
- Other chains can restrict frames to a fixed menu, e.g. keystores.
- Closing line: "The envelope is solved. The standard forms are where the work is now."

## 6. What this means for our build

### 6a. P-256 hardware keys: the hashing trap

Our app signs with `SHA256withECDSA` (Android) and `kSecKeyAlgorithmECDSASignatureMessageX962SHA256` (iOS). See `app/composeApp/src/commonMain/kotlin/com/enconomy/pop/Signing.kt` and `DeviceKeystore.ios.kt:278`.
That signs `sha256(message)`.
EIP-8141 P256 checks `P256VERIFY(msg = sig_hash, …)` with the raw 32-byte `sig_hash`.
So a message-mode signature over `sig_hash` fails. The PoC shows it: false against `sig_hash`, true against `sha256(sig_hash)`.

Explicit `msg = sha256(sig_hash)` does not help. An explicit msg is part of the hashed tx, so it would have to contain its own hash.

Two ways out:

1. Sign in digest mode. On iOS use `…DigestX962SHA256` with the 32-byte sig_hash. On Android use `NONEwithECDSA` / `DIGEST_NONE`. Then use the native P256 scheme (6,700 gas, could be aggregated later). UNREACHABLE (not tested, no device run): whether StrongBox and the Secure Enclave allow digest mode on our existing keys. A key's allowed digests are set when it is created, so we may need new keys.
2. Keep message mode. Put the 128 bytes in an `ARBITRARY` entry with empty msg. Account code runs `SIGDATACOPY`, then the SHA256 precompile on `TXPARAM(0x08)`, then P256VERIFY. About 7k gas. Add 2-4k for reading the stored key, so about 10k total. Fits the public mempool. Cannot be aggregated.

Either way the sender must be a deployed smart account holding the key in its own storage. Default code only knows secp256k1. A CREATE2 address is not `keccak(qx‖qy)[12:]`, so the key's own address cannot be the sender with code on it.

Normalize high-s before sending in both cases.

### 6b. ZK proofs do not fit the public mempool

- Measured in this repo: UltraHonk verify about 2.77M gas (`research/worldid/notes/onchain-zk/opt3-nonnative-p256.md`). Groth16 `verifyProof` 228,804 gas (`opt2-server-credential.md`).
- `MAX_VERIFY_GAS` is 100,000. Both are over. A proof check inside VERIFY needs the alt mempool (which raises the budget) or a private path.
- That lines up with the "$5,000 alt mempool" prize framing: "Verification budget above 100k gas".
- Option: do signatures and recent-root checks in VERIFY (cheap, public-mempool shape), and put the proof check in a SENDER frame after payment. Downside: a bad proof only reverts the body. The payer still pays, and keyed nonces are still burned.

### 6c. Recent roots as a meeting registry

- The PoP server (or a contract) can write a per-slot root of accepted meetings, `salt = "pop-meetings-v1"`.
- A frame tx then carries `recent_root_verify` with `(source_id, slot, root)`. Account VERIFY code checks a Merkle path from frame data against it.
- This is public-mempool legal. It is the only way to read outside state there.
- The 27 h window (12 s slots) fits "met at the event yesterday".
- Write cost: one SSTORE per slot per source. First write per ring index creates a slot (state gas).

### 6d. Keyed nonces as a one-meeting-one-claim nullifier

- The slot is `keccak256(pad32(sender) ‖ key)`. Keys are scoped per sender.
- So a single-use key `H("pop" ‖ pairTag)` is a global nullifier only if every claim goes through one shared sender (a "meeting pool" account, the privacy-pool pattern 8250 is built for). Then the protocol burns it at payment approval and no nullifier table is needed.
- If each phone sends from its own smart account, the key only stops that account from claiming twice. Two different accounts can both use the same key. Cross-account dedup then still needs a contract nullifier table (written in a SENDER frame, not atomic with approval) or a root-based check via 8272.
- Security rule: authenticate `TXPARAM(0x0F)` (the whole key set) in VERIFY.
- Limit: one pending tx per sender in the public mempool, even with keyed nonces. With a shared sender that means one claim in flight at a time there.

### 6e. Assertions

- Wallet-safety demo: an ASSERT frame that says "only this ENS record changed, ETH balance moved by at most the fee".
- Only if the devnet ships 7906. It is CFI, not scheduled. Ask on Nov 5.

## 7. Open questions for Nov 5

- Which 8141 commit does the devnet (ethrex eip8141-tracer) run? Fee field order? Two-dimensional state gas?
- Are 8250 and 8272 live on the devnet? At which addresses? (Spec addresses need the keyless deploy txs.)
- Is 7906 there?
- Is the alt mempool budget above 2.8M gas, or do we need Groth16 (about 230k)?
- Can our phone keys sign in digest mode, or do we go the ARBITRARY route?
