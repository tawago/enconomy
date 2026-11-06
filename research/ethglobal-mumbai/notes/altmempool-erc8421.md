# ERC-8421 alt mempool: what the code and the live devnet actually do

Researched 2026-11-02 (UTC 2026-11-01 ~18:50). Sources read:

- Docs site, all 40 pages from https://docs.altmempool.wtf/sitemap-0.xml (every page carries "Content created from source code using generative AI").
- Landing page https://altmempool.wtf
- ERC-8421 draft, ethereum/ERCs PR #2028, file at commit 493ba8ac: https://github.com/ethereum/ERCs/raw/493ba8ac3be97dc5cf6335eb97d2e8e9f95983c5/ERCS%2Ferc-8421.md (PR open, last update 2026-10-01)
- https://hackmd.io/@matt/frame-mempool
- forshtat/mempool-workshop-sidecar @ 2e22ff0a (2026-10-25, only branch `master`)
- forshtat/mempool-workshop @ d2f342a1 (2026-10-25)
- forshtat/ethrex branch eip8141-tracer @ 9aa3645d (the live node reports exactly this build)

Shallow clones are in `tmp/`. Nothing was executed. I sent only read-only JSON-RPC calls: chainId, clientVersion, skandha_config, listReputation and eth_estimateFrameTransactionGas dry runs. No transactions, no keys.

## TL;DR (read this first)

1. **The live sidecar has no staked gas budget.** It caps the whole validation prefix at 100,000 gas (sum of `limits.execution` plus the signature cost). Stake does not change that. I confirmed this with dry runs on the live devnet. That breaks the prize's "verification budget above 100k gas" route on today's devnet. The docs, the ERC, the landing page and the devnet README all describe a staked budget (1M or 2.5M), but the code does not have one.
2. What stake does unlock today, in code: wider storage reads, BALANCE/SELFBALANCE, and lifting the pending-tx caps. That covers the prize's other route, "more flexible state access (ERC-20 or daily-quota paymasters)". **This is the route that works today.**
3. TIMESTAMP and NUMBER are banned in every validation frame, staked or not. The one exception is TIMESTAMP inside the EXPIRY_VERIFIER predeploy (0x…8141), and that only applies in ethrex's own check. The sidecar skips the expiry frame entirely.
4. Precompile risk (inferred from code, not tested): the sidecar's code-access check would reject a VERIFY frame that STATICCALLs a precompile (ecrecover, bn254 pairing, P256VERIFY), because the live config has `precompiles: []`. This matters for any in-EVM ZK verifier.
5. P-256 is a protocol signature scheme (`scheme: 2`, cost 6,700 gas against the 100k cap). Our hardware P-256 keys can sign frame txs natively, with no Solidity verifier.
6. Faucet: the code has one (`skandha_explorer_faucet`, 1 ETH per address per hour), but **no faucet was reachable today**. The documented endpoint, the workshop gateway (altmempoolgateway.forshtat.com), returned HTTP 502. The sidecar at altmempool.forshtat.com/rpc has no `faucetEnabled` flag in `skandha_explorer_info`.

## 1. Gas budgets

| Source | Unstaked | Staked | Status |
| --- | --- | --- | --- |
| ERC-8421 draft (PR #2028) | `MAX_VERIFY_GAS_PER_ENTITY = 100_000` | `MAX_VERIFY_GAS_STAKED_ENTITY = 1_000_000` | VERIFIED (draft lines 38-39, 169-173) |
| Landing page altmempool.wtf | 250k "per entity" | 2.5M | VERIFIED as what the page says ("250k gas per entity fits a minimal proof check without stake", "A staked sender gets 2.5M gas"). The docs say the draft "has not been updated yet". |
| Sidecar code (what actually runs) | 100,000 total for the prefix | **same 100,000** | VERIFIED, see below |
| Docs "differences" page: sidecar has "a single MAX_VERIFY_GAS of 100,000 … with a separate staked budget" | | | CONTRADICTED by the code: there is no staked budget anywhere in the sidecar source |
| Devnet README / docs staking guide: the admission report shows "`MAX_VERIFY_GAS_STAKED_ENTITY` … as the effective gas cap" | | | CONTRADICTED by code and by the live dry run |

The code: `packages/executor/src/services/UserOpValidation/utils/validationPrefix.ts` (https://github.com/forshtat/mempool-workshop-sidecar/blob/2e22ff0a2898e69ea4bf5275bce1be8581a8582a/packages/executor/src/services/UserOpValidation/utils/validationPrefix.ts#L286-L299)

- line 10: `export const MAX_VERIFY_GAS = BigInt(100_000);`
- line 44: `MAX_VERIFY_STATE_GAS = BigInt(500_000)` (the state-gas cap is still enforced, although ERC-8421 dropped it)
- lines 286-292: `totalVerifyGas = executionSum + sigCost; if (totalVerifyGas > MAX_VERIFY_GAS) reject`. It sums every frame from 0 to the last prefix frame, expiry_verify included, with no stake lookup.
- Signature costs (line 24): ARBITRARY 100, SECP256K1 2,800, P256 6,700.
- A grep for `STAKED_ENTITY|PER_ENTITY` over the sidecar's .ts finds nothing outside docs and plans.

ethrex `ethrex_simulateFrameTransaction` (crates/networking/rpc/ethrex.rs ~398-470) hard-fails only on signature cost > max_verify_gas (default `FRAME_TX_MAX_VERIFY_GAS = 100_000`, crates/common/types/transaction.rs:2249; it can be changed with `ETHREX_MEMPOOL_MAX_VERIFY_GAS`). The prefix-gas check there is "now purely informational". So the cap is the sidecar's own rule.

**Live dry runs** with `eth_estimateFrameTransactionGas` on https://altmempool.forshtat.com/rpc and a `[self_verify, sender]` frame list:

| Sender | Prefix exec limit | Result |
| --- | --- | --- |
| 0x1111…1111 (unstaked, no code) | 150,000 | `validation prefix execution gas sum 150000 + signature-verification cost 0 = 150000 exceeds MAX_VERIFY_GAS 100000` |
| 0x095410aaF4029d6ac590f616c21D0C6C65002224 (staked 0.012 ETH, delay 86400, `isStaked: true` per `skandha_explorer_listReputation`) | 150,000 | same error |
| same staked sender | 1,500,000 | same error |
| same staked sender | 90,000 | gets past the cap (fails later on a nonce mismatch, as expected) |

VERIFIED: on today's devnet a staked entity gets no extra validation gas.

Other gas facts:
- Whole tx: `userOpGasLimit` 25,000,000 (live config). The block per-tx gas cap (EIP-7825) is enforced by ethrex. VERIFIED (skandha_config).
- Gas the body frames use after the prefix is not part of the verify budget at all. VERIFIED (validationPrefix.ts only sums 0..lastPrefixIndex; eth.ts estimate comment).
- Docs: 7 nonce keys made a VERIFY frame run out of gas at 30k, while 80k worked. VERIFIED as a docs claim only (rules/budget page).
- Devnet uses the Amsterdam+ gas model: a transfer to a new account costs 21,000 + 183,600 state gas, so use 250k. Contract deploy: "900k reverted, 6M works" (workshop.config.json5). VERIFIED as docs/config claims.

## 2. Staking mechanics

- Registry: `NaiveStakingRegistry` at `0xd51c04d7a0b01124e84de152f4e56d9eecb22d2f` (the address in the live skandha_config). VERIFIED.
- Interface: `addStake(uint32 unstakeDelaySec) payable`, `unlockStake()`, `withdrawStake(address payable)`, `getDepositInfo(address) → (uint256 stake, uint32 unstakeDelaySec, uint64 withdrawTime)`. Everything is keyed on `msg.sender`. VERIFIED (docs concepts/entities-and-stake; the ABI in StakingRegistryService/index.ts).
- A contract wallet can stake itself: in a self-relay tx, a SENDER frame calls the registry with value, acting as tx.sender. A paymaster or factory contract needs its own code that forwards `addStake`. VERIFIED (docs guides/staking).
- Live thresholds: `minStake = 0.01 ETH` (10000000000000000 wei), `minUnstakeDelay = 0`. VERIFIED (skandha_config). ERC-8421 wants 86400 s and about USD 1000. The workshop stakes 0.012 ETH with an 86400 delay.
- `checkStake` (ReputationService.ts): not banned, stake ≥ minStake, delay ≥ minUnstakeDelay, `withdrawTime == 0`. VERIFIED.
- Quirk: the BALANCE/SELFBALANCE exemption checks `stake > minStake` (strictly greater, frameTx.ts:702). Every other check uses ≥. Stake more than 0.01. VERIFIED.
- `unlockStake()` drops staked status at once. VERIFIED (code: withdrawTime != 0).
- Stake is never slashed. VERIFIED (ERC + docs).

What stake buys **in the sidecar code**:
- BALANCE/SELFBALANCE allowed.
- Storage: an unstaked entity that touches slots outside the sender's storage (its own storage, its associated slots, or reads of foreign contracts) is rejected with `unstaked <role> accessed … slot …`. A staked entity passes. Writes to non-associated foreign slots are always forbidden (frameTx.ts 740-807). VERIFIED (code). This roughly matches ERC STORAGE-031/032/033.
- Pending caps: when an entity is over its cap, staked status lets it through (reputation.ts `checkStake` after `cappedCount > max`). VERIFIED.
- **Not** a bigger gas budget (see §1).

## 3. Reputation parameters

| Param | Sidecar (live) | ERC-8421 | Status |
| --- | --- | --- | --- |
| minInclusionDenominator | 10 | 10 | VERIFIED |
| throttlingSlack | 10 | 10 | VERIFIED |
| banSlack | 50 | 50 | VERIFIED |
| THROTTLED_ENTITY_MEMPOOL_COUNT | 4 | 4 | VERIFIED (MempoolService/constants.ts) |
| Sender pending cap | 4 linear txs per sender (`MAX_MEMPOOL_USEROPS_PER_SENDER`); keyed-nonce txs are exempt | 4 per (sender,key), 64 per unstaked sender | VERIFIED; the two differ |
| Unstaked payer allowance | `10 + floor(inclusionRate*10) + min(included, 10000)` | `10 + inclusionRate * min(included, 10000)` | VERIFIED; the formulas differ |
| Decay | linear: `seen*(1 - elapsedHours/24)` since the last update, so **zero after 24 h idle** | `value*23//24` every hour (about 4 days) | VERIFIED (ReputationEntry.ts); docs CONTRADICTED for the sidecar |

- State formula: `floor(seen/10) > included + 50` → BANNED; `> included + 10` → THROTTLED; otherwise ok. VERIFIED (ReputationEntry.ts).
- `seen` is bumped for payer and factory on every admission, but for the sender only when the sender is staked (reputation.ts 203-221). Reputation is per address. So an unstaked sender in `[only_verify, pay]` never accrues `seen` and can't be banned. In `[self_verify]` the sender is also the payer, so it does accrue `seen`. VERIFIED (code).
- `included` is bumped for sender, payer and factory on inclusion. VERIFIED.
- The workshop's step 9 "cheats" with `debug_bundler_setReputation` (open on the devnet). Organic bans are hard to reproduce there. VERIFIED (workshop README).
- Blame attribution (REPUTATION-310..330) is in the ERC. I did not trace it in the sidecar.

## 4. Banned opcodes and storage rules in VERIFY frames

Sidecar banned set (frameTx.ts:68-87, https://github.com/forshtat/mempool-workshop-sidecar/blob/2e22ff0a2898e69ea4bf5275bce1be8581a8582a/packages/executor/src/services/UserOpValidation/validators/frameTx.ts#L68-L87): GASPRICE, GASLIMIT, DIFFICULTY, **TIMESTAMP**, BASEFEE, BLOCKHASH, **NUMBER**, SELFBALANCE*, BALANCE*, ORIGIN, GAS, COINBASE, SELFDESTRUCT, RANDOM, PREVRANDAO, INVALID, BLOBHASH, BLOBBASEFEE. (*allowed for stake > minStake.) GAS directly before a *CALL is not counted: ethrex's tracer drops it (erc7562_tracer.rs 96-130, 519-527). Plus:
- CREATE banned outside the factory role. CREATE2 at most once in the factory, otherwise banned.
- A nested CALL with value is always banned.
- An out-of-gas revert anywhere in the frame is banned.
- Touching an address with code size ≤2 that is not in `precompiles` is banned, as is EXTCODE* on the ENTRY_POINT (0x…aa).

ethrex's own validation observer (vm.rs 4205-4272, https://github.com/forshtat/ethrex/blob/9aa3645d795945c64400f41a70aace0edfa7f383/crates/vm/levm/src/vm.rs#L4205-L4272) also flags SLOTNUM, TLOAD/TSTORE and CALLCODE (outside deploy). It allows TIMESTAMP only when `code_address == EXPIRY_VERIFIER` (0x…8141).

**TIMESTAMP / NUMBER: banned.** VERIFIED in ERC (via EIP-8141), docs, sidecar code and ethrex. Staking does not help. Ways around it:
- Use an `expiry_verify` frame (target 0x…8141) as the first frame for a deadline. The sidecar skips it in compliance checks but counts its gas.
- Use EIP-8272 recent roots, or keep the freshness check off-chain or in the body frames.
- For the "fresh EVT" or daily-quota idea: the day index can't come from TIMESTAMP in VERIFY. A day index the user passes in calldata is not safe. expiry_verify only checks `deadline >= now`, so a user could claim a future day and reset their quota. Instead, a staked entity reads "now" from a foreign slot that someone else keeps updated (an epoch-counter contract, or the EIP-8272 recent-root store). The other option is to enforce the quota in a body frame.

Storage (ERC STORAGE-010..033; the sidecar implements the earlier PR #6 version):
- The sender's own storage is always allowed.
- Slots associated with the sender (value == addr, or keccak(addr||x)+0..128) in another contract are allowed. If the tx has a deploy frame, the factory must be staked.
- Staked entity: own storage, read-only access to any non-entity contract, write access to its own associated slots.
- Unstaked non-sender entity: nothing.
- Writes are possible only in deploy or pre_verify (DEFAULT-mode) frames. VERIFY frames are static.
- TLOAD/TSTORE are treated like SLOAD/SSTORE.
- The canonical mempool (ethrex) allows only the sender's storage.
- Associated-slot detection uses the keccak preimages from the trace. VERIFIED (utils `isSlotAssociatedWith`, docs ASSOC).

Prefix shapes allowed: `[self_verify]`, `[deploy, self_verify]`, `[only_verify, pay]`, `[deploy, only_verify, pay]`. Each approving frame may have one `pre_verify` right before it. An optional leading `expiry_verify` is also allowed. No ATOMIC_BATCH_FLAG in the prefix, and no VERIFY frame after it. VERIFIED (validationPrefix.ts, ERC PREFIX-010).

Precompiles: ERC CALLING-040 allows 0x01-0x11 and P256VERIFY. In the sidecar, CODE_ACCESS (frameTx.ts 810-827) rejects any touched address with code size ≤2 unless it is in `networkConfig.precompiles`, and the live config has `"precompiles":[]`. ethrex's tracer records contract size on every CALL/STATICCALL with no precompile skip (system.rs ~575, erc7562_tracer.rs 713). So a VERIFY frame that STATICCALLs 0x08 (bn254 pairing, used by UltraHonk/Groth16 verifiers) or 0x01 would likely be rejected with "accesses un-deployed contract address". This is inferred from code (https://github.com/forshtat/mempool-workshop-sidecar/blob/2e22ff0a2898e69ea4bf5275bce1be8581a8582a/packages/executor/src/services/UserOpValidation/validators/frameTx.ts#L810-L827, live `precompiles: []`, and https://github.com/forshtat/ethrex/blob/9aa3645d795945c64400f41a70aace0edfa7f383/crates/vm/levm/src/opcode_handlers/system.rs#L572-L578, which records the size with no precompile skip). I did not test it live, because that would need a deployed contract. Test it on day 1 with `eth_estimateFrameTransactionGas` against a tiny contract that calls a precompile, or ask Pierre/Alex.

## 5. Gateway / RPC methods

Sidecar `/rpc` (VERIFIED: docs reference/rpc-methods + api constants):
- `eth_sendFrameTransaction [tx JSON]` → hash.
- `eth_estimateFrameTransactionGas [partialTx]`. This is a free dry run that runs the full admission rules. **Use it as the test harness.**
- `eth_getFrameTransactionByHash`, `eth_getFrameTransactionReceipt`, `skandha_frameTransactionStatus` (New/Pending/Submitted/OnChain/Finalized/Cancelled/Reverted).
- `skandha_getGasPrice`, `skandha_config`, `skandha_connectedPeers`, `skandha_subscribe/unsubscribe` (WS).
- `skandha_explorer_*`, including `listReputation`, `getTransaction` (per-rule admission report) and `faucet`.
- `debug_bundler_*` admin methods. They are open on the devnet; don't call `clear*` or `set*`.
- With `--redirectRpc` it proxies a whitelist of `eth_*` reads plus `eth_sendRawTransaction`.

ethrex root URL: standard RPC plus `ethrex_simulateFrameTransaction [rawTx, block?, {trace:true}]`, which returns ERC-7562 trace, prefixShape, payer, maxCost and violation. `ethrex_submitPrivilegedFrameTransaction [rawTx]` is unauthenticated on the devnet. `eth_sendRawTransaction` with type 0x06 goes through canonical rules.

Tx JSON shape: `{chainId, nonce | nonceKeys+nonceSeq, sender, frames:[{mode 0/1/2, flags (approve scope bits 0-1, 0x4 atomic), target|null, limits:{execution,state}, value, data}], signatures:[{scheme 0/1/2, signer, msg, signature}], fees:{maxPriorityFeePerGas,maxFeePerGas,maxFeePerBlobGas}, blobVersionedHashes, recentRootReferences?}`. VERIFIED (SendFrameTransaction.dto.ts, docs submit page). Builder library: `@forshtat/hegota-support` (npm, used by the workshop; it provides the Solidity `sigparam`/`approve` helpers too).

## 6. Devnet endpoints and faucet

| Thing | Value | Status (2026-11-01 18:50 UTC) |
| --- | --- | --- |
| Execution RPC (ethrex) | https://altmempool.forshtat.com | VERIFIED up, chain 0x539, `ethrex/v23.0.0-eip8141-tracer-9aa3645d…`, block ~0x55190 |
| Sidecar RPC | https://altmempool.forshtat.com/rpc (wss same path) | VERIFIED up, `skandha/v4.1.1-` |
| Workshop gateway | https://altmempoolgateway.forshtat.com/rpc | UNREACHABLE (HTTP 502). The workshop sends everything here. |
| Explorer | https://explorer.altmempool.wtf/ | VERIFIED HTTP 200 (older README link altmempoolexplorer.forshtat.com not checked) |
| Chain ID / block time | 1337 / 6 s | VERIFIED chain id; block time from docs |
| Standard mempool id | QmcFZKUX9qoo3StwVycJTAhwdiqbEjcwNvQVK246p3z1rk | VERIFIED (skandha_config) |
| Relayer | 0x5544596212F91984C986A919C8026DF0576816f9 (the published genesis key) | VERIFIED (skandha_config) |
| Faucet | `skandha_explorer_faucet [address]`, 1 ETH, once per hour per address (FaucetService: `FAUCET_AMOUNT = 1 ETH`, cooldown 3,600,000 ms); "Faucet" button in the explorer; needs `--explorer.enable` + `SKANDHA_FAUCET_KEY` | VERIFIED in code. The only documented endpoint (the gateway) is UNREACHABLE (502). altmempool.forshtat.com/rpc `skandha_explorer_info` has no `faucetEnabled`, so it has no faucet there. The docs page guides/devnet says "There is no faucet." That matches today's reality, while the README and workshop say there is one. I did not call the faucet. Fallback per docs: fund yourself from the published genesis key. That needs a private key, which I did not use. |
| Predeploys | NONCE_MANAGER 0x…8250, RECENT_ROOT 0x…8272, EXPIRY_VERIFIER 0x…8141, plus replayed LINK, USDT, USDC, WETH9, Permit2, Uniswap v4, Tornado 0.1, Railgun, BAYC | VERIFIED as docs/README claims; full list in sidecar deployments/devnet.md |

The recap says "multiple alt mempool devnets will run … plus a faucet" at the hackathon. Those devnets may run newer code that has the per-entity budget. Not knowable today. UNREACHABLE.

## 7. What this means for our project

- **Don't build the pitch on "ZK proof > 100k in VERIFY, staked"** until a devnet admits it. Today it gets rejected, staked or not.
- The best fit today is the prize's second route, flexible state access. Example: a staked **humans-only sponsor paymaster** (`[only_verify, pay]` shape) whose pay frame reads a foreign registry, such as a World ID nullifier set or a proximity-attestation registry. A daily quota fits too: the paymaster keeps a per-user counter in its own storage, written through a `pre_verify` frame. The staked paymaster also drops the 1-pending-per-paymaster limit. All of this sits under 100k if the heavy proof is checked **off the VERIFY path**.
- Where to put the heavy proof:
  - (a) In a body (SENDER/DEFAULT) frame after the prefix. The paymaster then pays for failed proofs. That is bounded by reputation, and is fine for a demo.
  - (b) As a precomputed attestation. Verify the proof once in a normal tx that writes an "attested" bit into a registry, then the VERIFY frame only reads that bit. The read is foreign storage, so the entity must be staked. **This is the strongest demo of "stake unlocks state access".**
  - (c) If the hackathon devnet ships per-entity budgets, move the verifier into VERIFY. Check the precompile issue in §4 first.
- Signing: use `scheme: 2` (P256) signature entries with our hardware keys. That is 6,700 gas, verified by the protocol before any frame runs.
- Day-1 harness: `eth_estimateFrameTransactionGas` against https://altmempool.forshtat.com/rpc returns the exact rule that fails, without sending anything.

## Open items

- Whether the Mumbai devnets run a sidecar with per-entity budgets (ask Pierre/Alex at the Nov 5 workshop).
- Live test of precompile calls inside VERIFY.
- The docs site and the sidecar disagree on decay, caps and allowance formula. Trust the code for the devnet.
