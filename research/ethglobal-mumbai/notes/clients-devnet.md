# Clients, tooling and devnets for frame transactions

Written 2026-11-02 (JST). Probes ran 2026-11-01 18:50 to 19:06 UTC from this Mac.
Scope: forshtat/ethrex `eip8141-tracer`, Nethermind PR 12526, libraries that build and sign frame txs, the alt mempool devnet and its explorer.
Rules followed: read-only RPC only, no keys, no sends, no third-party code run. Third-party sources were read from tarballs in the session scratchpad.

Tags: VERIFIED (checked against a primary source or a live probe), CONTRADICTED (source quoted), UNREACHABLE (could not check; not a refutation), UNTESTED (plausible, not run).

---

## 0. The five things that matter

1. **Stake does not raise the verify gas cap on the live sidecar.** The code has one flat cap of 100,000 for everyone. Stake today only relaxes storage rules. A ZK proof check (about 194k to 263k gas) is rejected. Details in section 3.
2. **The gateway is down.** `altmempoolgateway.forshtat.com/rpc` returned HTTP 502 on both probes. The workshop and the faucet route through it. The miner node works.
3. **Each devnet speaks a different envelope.** A library built for one chain does not encode for another. Pick the devnet first, then the library. Table in section 5.
4. **Our phone keys cannot make a native P256 frame signature as they are.** They hash before signing. The protocol wants a signature over the raw sig hash. There are two workarounds. Section 6.
5. **P256VERIFY (0x100) is live on all three frame devnets.** VERIFIED by `eth_call` with a known-good vector. That makes the ARBITRARY-signature workaround cheap.

---

## 1. Devnets: what answers, and what it is

| Name | Chain ID | Endpoints | Client | Status at probe |
| --- | --- | --- | --- | --- |
| Alt mempool devnet ("miner") | 1337 (`0x539`) | ethrex: `https://altmempool.forshtat.com` ; sidecar: `https://altmempool.forshtat.com/rpc` | ethrex `eip8141-tracer` @ `9aa3645d` + sidecar (Skandha fork) v4.1.1 | Up. Head 348,555 at 18:51:34 UTC. Idle |
| Alt mempool gateway | 1337 | `https://altmempoolgateway.forshtat.com/rpc` | sidecar, gossips to the miner | HTTP 502 at 18:5x, 19:05 and 19:12 UTC. UNREACHABLE |
| Hegotá testnet (lambdaclass) | 8141 (`0x1fcd`) | `https://rpc1|rpc2|rpc3.privacy.ethrex.xyz`, `https://dora.privacy.ethrex.xyz`, `https://faucet.privacy.ethrex.xyz` | `ethrex/v23.0.0-hegota-testnet-hotfix-64b8fc09` | Up, head 651,667. Block scans timed out twice; slow |
| bogota-devnet-2 (ethpandaops) | 7076692741 (`0x1a5cdc305`) | `https://rpc.bogota-devnet-2.ethpandaops.io`, dora, faucet, beacon under the same domain | geth, ethrex, nethermind, reth (2 nodes each) | Up, head 22,936. Busy: 283 frame txs in the last 20 blocks (spamoor) |
| Old ethrex EIP-8141 devnet | 3151908 | `https://rpc1.eip-8141.ethrex.xyz` | ethrex | Empty reply. UNREACHABLE |

Evidence and notes:

- VERIFIED. `eth_chainId` on `https://altmempool.forshtat.com` returned `0x539`. `web3_clientVersion` returned `ethrex/v23.0.0-eip8141-tracer-9aa3645d795945c64400f41a70aace0edfa7f383/...`. That is the tip of the branch (commit 2026-10-01). Source: https://github.com/forshtat/ethrex/tree/eip8141-tracer
- VERIFIED. `/rpc` `web3_clientVersion` returned `skandha/v4.1.1-`. `skandha_explorer_info` returned `chainId 1337, bundlingMode auto, p2pEnabled true, minInclusionDenominator 10, throttlingSlack 10, banSlack 50`, and no `faucetEnabled` field. So the miner does not serve the faucet. The sidecar docs say the faucet runs on the gateway ("docs(devnet): run the faucet on the gateway", commit 2026-10-24). With the gateway down, the faucet is down too (inference).
- VERIFIED. `skandha_explorer_peers` on the miner returned `[]`. No gossip peer was connected at probe time. This matches the gateway being down.
- VERIFIED. The 300 most recent blocks on chain 1337 held 0 transactions. The last included frame tx in the admission log was `0x578d67aa...17c7` at 2026-11-01 08:07 UTC.
- VERIFIED. bogota-devnet-2 node list from `https://config.bogota-devnet-2.ethpandaops.io/api/v1/nodes/inventory`. The geth nodes run image `ethpandaops/geth:bogota-devnet-1`. The repo is https://github.com/ethpandaops/bogota-devnets (devnet-1 torn down 2026-10-29, devnet-2 genesis 2026-10-29 14:30 UTC).
- VERIFIED. Hegotá testnet facts (chain 8141, predeploys `0x…8141` expiry verifier, `0x…8250` NONCE_MANAGER, `0x…8272` RECENT_ROOT_ADDRESS, 200M block gas, `ethrex_simulateFrameTransaction` served publicly, `debug` not served) come from `scripts/hegota-testnet/USER-GUIDE.md` on the forshtat/ethrex branch.
- CONTRADICTED, minor. The docs site says "There is no faucet" (`guides/devnet.md` in https://github.com/forshtat/mempool-workshop-documentation). The sidecar devnet readme says "Ask the faucet: press **Faucet** in the explorer, or call `skandha_explorer_faucet`" (https://github.com/forshtat/mempool-workshop-sidecar/blob/master/deploy/devnet/devnet-readme.md). The readme is newer.

### Which devnet is "the" devnet for the prize?

UNREACHABLE. The recap says "Multiple alt mempool devnets will run with keyed nonces and recent roots live, plus a faucet." None is announced yet. The only one with an alt mempool today is chain 1337. bogota-devnet-2 and chain 8141 have no sidecar. Ask on Nov 5.

---

## 2. Explorer `altmempoolexplorer.forshtat.com`

- VERIFIED. Reachable, HTTP 200. Title "Frame pool explorer". It is a single-page React app.
- VERIFIED. `https://explorer.altmempool.wtf/` also returns 200. The docs list both URLs and call the difference TBD.
- VERIFIED (read from the JS bundle `/assets/index-BBMhStMv.js`). The app has no backend of its own. It calls JSON-RPC on two preset nodes: `Gateway https://altmempoolgateway.forshtat.com/rpc` and `Miner https://altmempool.forshtat.com/rpc`.
- Its methods: `skandha_explorer_info`, `skandha_explorer_listTransactions`, `skandha_explorer_listAdmissions`, `skandha_explorer_getTransaction`, `skandha_explorer_peers`, `skandha_explorer_listReputation`, `skandha_explorer_faucet`, plus a websocket `skandha_subscribe`. You can call them yourself with curl. That is handy for a demo script that prints "admitted" from the node's own report.

### What the admission log shows (miner, last 200 entries)

Window: 2026-10-26 23:54 to 2026-11-01 08:30 UTC. VERIFIED from `skandha_explorer_listAdmissions`.

- Outcomes: 123 included, 47 rejected, 30 dropped.
- 114 came in by gossip, 86 by direct RPC.
- Every admission carries a rule-by-rule report: `gas-limit, recent-root, prefix, structure, signature, simulation, trace-alignment, OP-061, execution, mempool, out-of-gas, OP-011, create, storage, COD-010, entrypoint-access`.
- Keyed nonces are in use. Several txs had a single non-zero 32-byte `nonceKeys` entry.
- Verify-gas sums of the included txs: 15,000 up to 99,900. **None above 100,000.**
- Top rejection: `structure`, "validation prefix execution gas sum 280000 + signature-verification cost 2800 = 282800 exceeds MAX_VERIFY_GAS 100000". Others asked for 150k, 250k, 276k, 300k, 305k and 1.2M. All were rejected the same way.
- One `storage` rejection: "unstaked payer accessed 0x33e7… slot 0x…0". That is the rule stake relaxes.
- Nine entities in the reputation list are staked at 0.012 ETH, the workshop's `stakeEth`.

---

## 3. Verify gas budget: what the live code enforces

CONTRADICTED. The recap says the pool "must be staked" to get the higher budget. The devnet readme says a staked entity gets "`MAX_VERIFY_GAS_STAKED_ENTITY` (not the tighter unstaked `MAX_VERIFY_GAS_PER_ENTITY`) as the effective gas cap" (`deploy/devnet/devnet-readme.md`, line 119).

The code on `master` says otherwise. From `packages/executor/src/services/UserOpValidation/utils/validationPrefix.ts`:

```ts
export const MAX_VERIFY_GAS = BigInt(100_000);
...
const totalVerifyGas = executionSum + sigCost;
if (totalVerifyGas > MAX_VERIFY_GAS) { return { valid: false, reason: `... exceeds MAX_VERIFY_GAS ...` } }
```

- No branch on stake. I searched the whole source tree for `STAKED_ENTITY`, `PER_ENTITY` and `MAX_VERIFY_GAS`. The only code hit for `STAKED_ENTITY` is `SAME_UNSTAKED_ENTITY_MEMPOOL_COUNT` in `ReputationService.ts`, which is a pending-count limit, not gas. VERIFIED.
- The live data agrees: no tx above 100k was ever included (section 2).
- The workshop's "staked tx accepted" step (`step_8`) shows a **storage** violation, not a gas one. `ViolatingWallet.sol` says: "the standard alt-mempool rejects it for an unstaked entity … and admits it once the wallet is staked." VERIFIED from https://github.com/forshtat/mempool-workshop.
- The docs site admits the gap: "The sidecar's rules come from an earlier ERC-7562-derived draft (`forshtat/ERCs` PR #6) … The two are not equivalent." Budget table: draft 100,000 / 1,000,000, landing page 250,000 / 2,500,000. (`project/differences.md`.)

What fits under 100k today:

| Check | Gas | Source | Fits? |
| --- | --- | --- | --- |
| Groth16 BN254 verify | 194,396 (216,112 with call + calldata) | https://github.com/NethermindEth/frame-verify-gas | No |
| Our Groth16 presence circuits | 242,116 / 262,840 | `research/worldid/notes/pool.md` | No |
| Our UltraHonk proofs | about 2.73M per proof | `research/worldid/notes/implementer-prompt-optA-noir.md` | No, not even under the 1M draft staked cap |
| P256 frame signature (scheme 2) | 6,700 intrinsic | ethrex `docs/eip-8141.md` | Yes |
| P256VERIFY precompile call | 6,900 (EIP-7951); `eth_estimateGas` of a bare call = 25,581 incl. 21k base | live probe | Yes |
| ECDSA (scheme 1) | 2,800 | ethrex `docs/eip-8141.md` | Yes |

NethermindEth/frame-verify-gas also says the effective budget is "about 79k gas (`MAX_VERIFY_GAS` minus the intrinsic and nonce deductions)". And: "aggregation is the path being explored in EIP-8288, rather than raising the budget." UNTESTED by me.

Consequences for the plan:

- On today's 1337 devnet, the prize line "verification budget above 100k gas" cannot be shown through the standard alt mempool. Only "more flexible state access" can (stake, then read foreign storage; or an ERC-20 / daily-quota paymaster).
- If the hackathon devnets ship ERC-8421 per-entity budgets, a staked Groth16 verifier (about 200 to 260k) fits under both 1M and 2.5M. UltraHonk (2.7M) fits neither. **Move the on-chain proof to Groth16 if it has to run inside VERIFY.**
- Fallback if budgets stay at 100k: run our own sidecar as a custom mempool with a higher constant (a one-line change in our own fork), on our own ethrex. The sidecar relays through `ethrex_submitPrivilegedFrameTransaction`, which skips ethrex's own mempool rules (section 4). Whether judges accept "admitted by our custom mempool" is an open question.
- Another fallback: keep VERIFY small (P256 or ECDSA plus a nullifier check) and verify the ZK proof in an execution frame. Then the proof no longer gates validity, which weakens the story.

---

## 4. forshtat/ethrex `eip8141-tracer`

Repo: https://github.com/forshtat/ethrex/tree/eip8141-tracer (fork of lambdaclass/ethrex; 446 commits ahead, 223 behind lambdaclass main; tip `9aa3645d`, 2026-10-01). VERIFIED via GitHub API.

### What works (from the branch docs, plus probes where marked)

- Type `0x06` frame txs with modes DEFAULT 0, VERIFY 1, SENDER 2. No POST_TX (EIP-7906) on this profile (`@forshtat/hegota-support` README: "`frame(profile, "POST_TX", ...)` throws on the tracer profile").
- Signatures `[scheme, signer, msg, signature]`. Scheme 0 ARBITRARY, 1 SECP256K1 (`v||r||s`, bare v 0/1), 2 P256 (`r||s||qx||qy`, 128 bytes, low-s required). Intrinsic cost 100 / 2,800 / 6,700. Source: branch `docs/eip-8141.md`.
- EIP-8250 keyed nonces with `NONCE_MANAGER` at `0x…8250`. EIP-8272 recent roots at `0x…8272`, as a top-level `recent_root_references` field. That field is not in the current EIP text (hegota-support README, "Where devnets already differ from the EIP text").
- Mempool validation prefix simulation with ERC-7562 style banned opcodes and storage rules, as a local policy. Recognized shapes: `self_verify`, `deploy+self_verify`, `only_verify+pay`, `deploy+only_verify+pay`. Recognizes ERC-8421 `pre_verify` frames (commit 2026-09-30).
- Canonical paymaster recognized by runtime code hash `0xda42f0d1…c4d45c`.
- Receipts carry `payer` and `frameReceipts`. VERIFIED on tx `0x578d…17c7`.
- Extra RPC: `ethrex_simulateFrameTransaction(rawTx [, block [, {"trace": true}]])` dry-runs a tx and reports validity, payer, prefix shape and per-frame gas. It never touches the mempool. Preconditions: the tx must decode, the signatures must fit `MAX_VERIFY_GAS`, the signatures must authenticate `sender`, and total gas must fit the cap.
- Extra RPC: `ethrex_submitPrivilegedFrameTransaction(rawTx [, targetBlock])`. It forces the tx into the next payload build, "bypassing ethrex's mempool admission entirely". It is unauthenticated on the public devnet. The sidecar uses it to land alt-mempool txs.
- Tracer `erc7562FrameTracer` for `debug_traceTransaction`. `debug_traceCall` cannot express frames and returns `[]`.

### Known gaps (branch docs)

- Blob-carrying frame txs are rejected at the mempool.
- `SETDELEGATE` (EIP-7819) is missing, so rule FRA-060 is only partly covered.
- A mined tx whose SENDER frame reverts still burns its nonces. Simulate first.
- New-account transfers cost about 204,600 gas, not 21,000 (EIP-8037 state gas).
- Devnet readme: "One transaction in flight per sender" for linear nonces. Use keyed nonces for parallel txs.

### How to run it

- Image: `ghcr.io/forshtat/ethrex:eip8141-tracer-latest`. Also `ghcr.io/forshtat/eip8141-devnet:latest`, which adds `fixtures/genesis/l1-hegota.json` and funded dev keys. VERIFIED public on ghcr. **Both are amd64 only** (manifest index lists `amd64` plus an attestation). On Apple Silicon they need emulation.
- No native macOS build: "ethrex doesn't build natively on macOS (its `sha3-asm`/`keccak-asm` dependencies emit assembly the Mach-O assembler rejects)" (sidecar `P2P.md`).
- Local dev chain, from the sidecar's `test/e2e/ethrex-devnet.sh`: chain id 9, genesis `l1-hegota.json`, Hegotá active from genesis, RPC on `127.0.0.1:8555`. You must pass `--http.api eth,net,web3,ethrex,debug`, or `eth_sendFrameTransaction` fails with "Method not found".
- Sidecar on top: `bun install && bun run build`, copy `config.json.default`, set `rpcEndpoint`, `relayers`, and the sentinel entry point `0x00000000000000000000000000000000000000aa` everywhere. Then `./skandha standalone` (RPC on `:14337/rpc`), or `./skandha node` for p2p.
- UNTESTED here. The Docker daemon was not running. I would not have run third-party images anyway under this task's rules.

### The recap's "only ethrex validates frame txs; geth cannot yet"

- VERIFIED that the sidecar README says it: "ethrex's `eip8141-tracer` branch is currently the only one that does; a standard client such as geth cannot validate or simulate frame transactions at all."
- CONTRADICTED as a statement about clients in general. Nethermind merged frame txs with in-pool prefix simulation (section 4b). geth, reth and nethermind all run frame txs on bogota-devnet-2 (inventory above).
- Still true for the **alt mempool**. The sidecar calls `ethrex_simulateFrameTransaction` and `ethrex_submitPrivilegedFrameTransaction`, plus `debug_traceCall`. Only this ethrex fork exposes them. VERIFIED by grep of `packages/executor/src`.

## 4b. Nethermind PR 12526

https://github.com/NethermindEth/nethermind/pull/12526

- VERIFIED. Title "feat(eip8141): implement frame transactions (EIP-8250 keyed nonces, EIP-8272 recent roots, blob support)". Author svlachakis. Opened 2026-07-21. **Merged 2026-09-24** into `master` (merge commit `5246d0c7`). +41,673 / -1,262, 346 files. Branch name `eip8141-frame-txs-devnet7`.
- VERIFIED. Included in release v2.2.2 (2026-10-26). GitHub compare `5246d0c…2.2.2` shows behind_by 0.
- Scope from the PR body: type-6 envelope, DEFAULT/VERIFY/SENDER plus EIP-7906 POST_TX, secp256k1 and P256 signatures, atomic batches, sponsored payers, `MAX_VERIFY_GAS` at ingress, in-pool prefix simulation, keyed nonces with a `NONCE_MANAGER` predeploy, recent roots, blob frame txs with a network wrapper. It activates under the "Bogota" alias (`Eip8141TransitionTimestamp`, geth-genesis `bogotaTime`).
- Where it runs: bogota-devnet-2 (`ethpandaops/nethermind:bogota-devnet-2`, branch `bogota-devnet-2` @ `d087d9a` per https://notes.ethereum.org/@ethpandaops/bogota-devnet-2). That devnet pins EIP-8141 `spec@f1bcca1b`, a later revision than the 1337 devnet's `4a9ad32c`.
- Not usable behind the alt mempool sidecar (no `ethrex_*` methods). For us it matters as a second client, not as a build target.

---

## 5. Libraries to build and sign frame txs

The main trap: **three envelopes are in the wild**.

| Envelope | Chains | Shape |
| --- | --- | --- |
| tracer / testnet | 1337 (alt mempool), 8141 (privacy.ethrex) | 9 items: `[chain_id, nonce_keys, nonce_seq, sender, frames, signatures, fees[3], blob_hashes, recent_root_refs]`, frame = `[mode, flags, target, [execution, state], value, data]` |
| hegota-devnet | 3151908 (EIP-7906 devnet) | 11 items, three flat fee fields (hegota-support README) |
| bogota-devnet-2 | 7076692741 | EIP-8141 `spec@f1bcca1b`. The RPC JSON uses other names (`executionGas`, `stateGas`, `maxFee`, scalar `nonce`, no `nonceKeys`). Encoding not checked |

The 1337 and 8141 layouts match. I checked this from `scripts/hegota-testnet/frametx.py` (8141) against my own encoder, which reproduced 1337 tx hashes. UNTESTED byte for byte on 8141, because no 8141 frame tx could be fetched (scans timed out).

`sig_hash = keccak256(0x06 || rlp(envelope with signature bytes emptied for every entry whose msg is empty))`. Signer `0x` means `tx.sender`. For P256, the signer address is `keccak256(qx || qy)[12:]` (EIP-8141 text, https://eips.ethereum.org/EIPS/eip-8141).

| Library | Lang | Targets | Signing | State | Notes |
| --- | --- | --- | --- | --- | --- |
| `@forshtat/hegota-support` 0.0.1 | TS (viem peer) | profiles `ethrex-eip8141-tracer` (1337) and `ethrex-hegota-devnet` (3151908) | secp256k1 only (`signTx`) | On npm since 2026-10-25. The README says "Not published to npm yet", which is CONTRADICTED by `npm view` | Also ships `HegotaSupport.sol`: Solidity wrappers for APPROVE, TXPARAM, SIGPARAM and the rest via Yul helpers. Used by the workshop. Best fit for 1337 |
| `@jaw.id/frametx-kit` 0.5.0 | TS (viem peer) | chain 8141 (`hegotaTestnet`) | secp256k1 and **P256** (`privateKeyToP256Account`, low-s, `r||s||qx||qy`) | npm, modified 2026-10-08 | Has `sendFrameTransaction`, `frameActions` for viem, gas pricing. It warns that WebCrypto and passkeys cannot sign a raw digest. Probably also encodes 1337 (same layout), UNTESTED |
| ch4r10t33r/viem `frames` branch | TS | old devnet 3151908 (per ethrex `scripts/eip8141-devnet/README.md`) | ECDSA | Last push 2026-09-22 | Likely a stale layout. Avoid |
| sidecar `test/e2e/helpers.ts` + `FrameTxService/codec.ts` | TS | 1337 | secp256k1 | in sidecar repo | The docs point here for `buildUnsignedFrameTx`, `signFrameTx`, `toWire` |
| `frametx.py` (ethrex `scripts/hegota-testnet/`) | Python | 8141 | secp256k1 (separate submit scripts) | in repo, no pip package | Needs `eth_hash`. Has a golden vector |
| ethrex crates (`FrameTransaction` in `crates/common/types/transaction.rs`) | Rust | the ethrex profile | n/a | in repo | The reference encoder. Heavy dependency |
| decentri-dev/open-engine | Rust | anything with `ethrex_simulateFrameTransaction` | canonical paymaster signer | 2026-09 | A relay and broadcaster service, not a small library |
| leekt/FrameTx-toolkit | Rust/Solidity | patched revm, foundry, solc | n/a | 2026-10-13 | For writing and testing frame contracts locally. Includes vFrame, a stock-EVM emulation |
| ethpandaops/spamoor `scenarios/frametx-fuzz` | Go | bogota-devnet-2 | ECDSA | active | Load generator; the reference for that devnet's shape |
| ethers fork | — | — | — | none found | GitHub search for ethers + 8141 returned nothing |

My own PoC (VERIFIED): `research/ethglobal-mumbai/poc/clients/check-frame-tx.cjs`. It uses only the viem already in `relayer/node_modules`. It fetches a mined tx from chain 1337, re-encodes it, checks `keccak(raw) == hash`, recomputes `sig_hash`, and recovers the secp256k1 signer.

- `0x578d…17c7` (EOA self-relay): hash match true, recovered `0xcdC9…0a90` = sender.
- `0x4670…9b03` (contract wallet, keyed nonce, explicit `signer`): hash match true, recovered `0x6c12…63DE` = the `signer` field.
- The same script on a bogota-devnet-2 tx crashes on missing `nonceKeys`. That is the envelope gap above, shown concretely.

How to submit on 1337: `eth_sendFrameTransaction` on the sidecar `/rpc` takes the **JSON form**, not raw bytes (`guides/submit-a-transaction.md` in the docs repo). Raw `0x06` bytes sent to ethrex with `eth_sendRawTransaction` go to ethrex's canonical mempool instead.

Recommendation: on 1337, use `@forshtat/hegota-support` for encoding and the Solidity helpers. Borrow frametx-kit's P256 signing code path if we sign with scheme 2. Keep `check-frame-tx.cjs` as a regression check against the live chain.

---

## 6. Fit with the enconomy phone keys

VERIFIED from our own code:

- Android `AndroidDeviceKeystore.kt:74`: `.setDigests(KeyProperties.DIGEST_SHA256)`, StrongBox when available. Signs with `SHA256withECDSA`.
- iOS `DeviceKeystore.ios.kt:278`: `kSecKeyAlgorithmECDSASignatureMessageX962SHA256`.

Both hash the input before signing. A scheme-2 frame signature must be over the raw 32-byte sig hash. So **today's keys cannot produce a valid scheme-2 signature**.

A trick that does **not** work: putting `msg = sha256(sig_hash)`. When `msg` is not empty, the signature bytes are not elided, so they are part of `sig_hash` itself. The definition becomes circular.

Two routes (pick one in the build plan):

1. **New raw-digest keys.** iOS: `kSecKeyAlgorithmECDSASignatureDigestX962SHA256` takes a 32-byte digest. Android: an EC key with `DIGEST_NONE` (`NONEwithECDSA`). UNTESTED whether StrongBox accepts `DIGEST_NONE`; I recall it only supports SHA-256, so it may fall back to the TEE. Cost: 6,700 gas, and the protocol does the check. A clean story: "the phone's secure element signs the tx natively."
2. **Keep the keys. Use scheme 0 ARBITRARY plus P256VERIFY in the VERIFY frame.** The account code reads the sig hash (`TXPARAM`), takes `sha256` of it (precompile 0x02), copies the 128 signature bytes (`SIGPARAM` param 0x04, allowed only for ARBITRARY), then calls `P256VERIFY` at 0x100. Rough cost: about 7k precompile + 100 intrinsic + glue. That fits under 100k. Precompile live on 1337, 8141 and bogota-devnet-2 (VERIFIED, `poc/clients/probe-p256verify.sh`). UNTESTED end to end. Check that the sidecar's opcode rules allow the 0x100 and 0x02 precompile calls in VERIFY.

Route 2 needs no app change. Route 1 is the better demo. Both stay far under the cap.

---

## 7. Open questions for Pierre and Alex (Nov 5)

1. Will the hackathon devnets run the ERC-8421 per-entity budgets? Which numbers: 100k/1M or 250k/2.5M? Today the sidecar is flat 100k.
2. Which chain ID and gateway URL will the judges check for "admitted on the devnet"? Will the gateway and the faucet be back?
3. Does an admission by our own custom sidecar count, or only the standard mempool's?
4. Will the hackathon devnet keep the tracer envelope (top-level `recent_root_references`), or move to the current EIP text?
5. Is `ethrex_submitPrivilegedFrameTransaction` how inclusion works at the event too, or will there be a real builder pull?

## Sources

- https://github.com/forshtat/ethrex/tree/eip8141-tracer (docs/eip-8141.md, scripts/hegota-testnet/USER-GUIDE.md, scripts/eip8141-devnet/*)
- https://github.com/forshtat/mempool-workshop-sidecar (README, P2P.md, deploy/devnet/devnet-readme.md, validationPrefix.ts)
- https://github.com/forshtat/mempool-workshop (README, workshop.config.json5, contracts/src/ViolatingWallet.sol)
- https://github.com/forshtat/hegota-support ; https://www.npmjs.com/package/@forshtat/hegota-support
- https://github.com/forshtat/mempool-workshop-documentation (project/differences.md, rules/budget.md, guides/devnet.md, guides/submit-a-transaction.md)
- https://github.com/JustaLab-co/frametx-kit ; https://www.npmjs.com/package/@jaw.id/frametx-kit
- https://github.com/NethermindEth/nethermind/pull/12526
- https://github.com/NethermindEth/frame-verify-gas
- https://github.com/ethpandaops/bogota-devnets ; https://notes.ethereum.org/@ethpandaops/bogota-devnet-2
- https://eips.ethereum.org/EIPS/eip-8141
- https://github.com/ethereum/go-ethereum/blob/master/core/vm/testdata/precompiles/p256Verify.json (test vector)
- https://altmempoolexplorer.forshtat.com , https://explorer.altmempool.wtf
