# Bridge: getting a PoP NEAR verdict onchain

Date: 2026-09-26. Scope: how a contract (Safe guard/module, or a privacy pool) can trust "two distinct humans' devices were < 60 cm apart for THIS transaction", at what gas, and with what trust.

Tags: **V(source)** = verified by me, with the URL or the command. **U** = unverified. **E** = my estimate.

Scratchpad with everything I ran: `/private/tmp/claude-501/-Users-takahiro-ogawa-dev-enconomy/3d9dd236-bf59-4c81-91f5-6bb7c5ebc6e3/scratchpad/bridge/` (`popv/` = the forge prototype below, `live.txt` = precompile vectors from real Secure Enclave fixtures). The scratchpad is temporary, so the core contract code is copied into §6.

## TL;DR

1. **P256VERIFY at `0x…0100` is live** on World Chain mainnet (480), World Chain Sepolia (4801), Ethereum Sepolia and Ethereum mainnet. It accepts **real Secure Enclave signatures from our own POPT v2 fixtures, high-s ones included**. It costs about 6,900 gas (EIP-7951 pricing, not RIP-7212's 3,450). V(cast, §1.1)
2. **The phones' signed transcripts can be checked onchain, and the verdict can be recomputed there.** I built a Solidity prototype that parses two POPT v2 transcripts, verifies the two phone signatures and the two SBcred3 issuer credentials with the precompile, checks the cross-keys, device A ≠ B, `self_os_delta`, and computes flight with exact integer math. On live World Chain (eth_call with a code override): 30 cm fixture → NEAR, 200 cm mixed-rate fixture → NOT_NEAR. **81,825 gas for the whole tx**, V(§1.2). This is "tier 2": a hacked server alone can't mint a presence.
3. **The option A ZK proof can't be verified onchain in any practical way.** It's Spartan2/Hyrax over T-256 (P-256 base field), 1.5–1.65 MB, and there's no precompile. A zkVM wrap to Groth16 costs roughly 1e10+ cycles per proof, so hours and dollars (E). A native BN254 re-proof is dead: every field op is non-native. Instead, the attestation carries the proof hashes and the vk hash, and anyone can re-verify offchain. §3.4
4. **World ID 4.0 is verified onchain only on World Chain 480** (prod `0x00000000009E00F9FE82CfeeBB4556686da094d7`, staging `0x703a6316c975DEabF30b637c155edD53e24657DB`). Groth16 verify is **288,153 gas measured**, so about 300–320k per proof with the registry reads (E). Two humans cost about 0.63M gas, which is fractions of a cent on 480 (base fee 0.0005 gwei today). V(forge test, cast)
5. **Context binding needs no app or transcript change.** Today `session_nonce` is `secrets.token_hex(32)` (`server/pop/sessions.py:142`). Derive it instead: `nonce = keccak256(abi.encode("pop-ctx-v1", chainId, consumer, ctxHash, notBefore, sessionId))`. The phones already sign the nonce in POPT/POPC, and the World ID signal is already `encodePacked(nonce, role)` (`docs/pop-human-adapters.md`). So one server-side change binds the audio run and both World ID proofs to the Safe tx or pool transfer **before the run**.
6. **Recommendation.** Build one `PresenceRegistry` on World Chain 480 with two submit paths:
   - `submitAttested` (tier 1): server EIP-712 signature plus the World ID proofs onchain. Private: no device keys.
   - `submitTranscripts` (tier 2): phone P-256 signatures plus the onchain verdict plus the World ID proofs. Device keys become public.

   Consumers (the Safe guard, the pool) read `presence[ctxHash]`. **SAFE → tier 2. POOL → tier 1**, or later an in-circuit check of the attestation.

## 1. Verified facts

### 1.1 P256VERIFY precompile (0x0000000000000000000000000000000000000100)

| Chain | chain id | RIP-7212 test vector | Our Secure Enclave fixtures (4 POPT + 4 SBcred3 sigs) | Bad input |
|---|---|---|---|---|
| World Chain mainnet (`https://worldchain-mainnet.g.alchemy.com/public`, client `world-chain/v2.4.3-dcd2e94`) | 480 | `…01` | all `…01` | empty `0x` |
| World Chain Sepolia (`https://worldchain-sepolia.g.alchemy.com/public`) | 4801 | `…01` | all `…01` | empty |
| Ethereum Sepolia (`https://ethereum-sepolia-rpc.publicnode.com`) | 11155111 | `…01` | all `…01` | empty |
| Ethereum mainnet (`https://ethereum-rpc.publicnode.com`) | 1 | `…01` | n/a | empty |
| Base Sepolia, OP Sepolia | 84532, 11155420 | `…01` | n/a | empty |

- V(cast call, 2026-09-26). Input is 160 bytes: `hash(32) ‖ r(32) ‖ s(32) ‖ x(32) ‖ y(32)`. It returns 32 bytes `…01` on success and **empty returndata on failure**, not `…00`. Check `out.length == 32 && out == 1`.
- **High-s is accepted.** 7 of the 8 fixture signatures (CryptoKit Secure Enclave, and the issuer's) are high-s, and all verify. So the contract does NOT need low-s normalization. But then ECDSA signatures are malleable, so **never use signature bytes as a replay key**. Use the nonce or ctxHash. V(`live.txt` + cast)
- The hash input is `sha256(message)`, which matches the phone's `SHA256withECDSA` / CryptoKit over the raw POPT bytes. The SBcred3 issuer signature is over `sha256(cred111)`. V(forge test passes with `sha256(cred)`)
- **Gas.** `eth_estimateGas` of a constructor that staticcalls 0x100, minus the same constructor calling a warm empty address, is **7,379** on all four chains. That's 6,900 (EIP-7951) plus returndata and require overhead. With RIP-7212's 3,450 it would be about 3.9k. So World Chain already charges Fusaka pricing. V(cast estimate), and the attribution to 6,900 is inferred. EIP-7951 spec: https://eips.ethereum.org/EIPS/eip-7951 (6,900 gas, address 0x100).
- EIP-2935 (history of the last 8,191 block hashes at `0x0000F90827F1C53a10cb7A02335B175320002935`) has code on 480, 4801 and Sepolia. World Chain blocks are 2 s (100 blocks = 200 s), so its window is about 4.5 h. Sepolia is 12 s. V(cast codesize, cast block)

### 1.2 Onchain transcript verifier prototype (tier 2), measured

`popv/src/PopBridge.sol` (full code in §6). It checks:

- POPT v2 layout, 311 B;
- roles A/B, same nonce and attempt;
- `A.pk_partner == B.pk_self` and the reverse;
- device A ≠ device B;
- both phone signatures;
- both SBcred3 credentials: key = transcript key, `expiry ≥ validAt`, issuer signature;
- `|self_os_delta| ≤ 50 ms·sr/1000`;
- flight, exactly: `flightX = 34300·(half_A·sr_B − half_B·sr_A)`, NEAR iff `−20·2·sr_A·sr_B < flightX < 60·2·sr_A·sr_B`. This is the same integer rule as `server/pop/verdict.py flight_exact` and `constants.SPEED_OF_SOUND_CM_S = 34300`.

| Fixture (`research/sound-bound/spikes/zk/fixtures/popt_v2/`) | label | Result | flightX / den |
|---|---|---|---|
| `180ca04b_48k` (48k/48k) | 30 cm | NEAR ✓ | 156,408,000,000 / 4.608e9 = 33.9 cm |
| `9afb91c6_mix` (48k/44.1k) | 200 cm | NOT_NEAR ✓ | 891,721,110,000 / 4.2336e9 = 210.6 cm |
| either, 1 bit flipped in transcript A | – | reverts `BadSig` ✓ | |

- forge (osaka EVM, via_ir): execution 45,744 gas.
- **Live World Chain 480 and 4801**, `cast call` with `--override-code` on the harness: same results. The eth_estimateGas of the whole tx with a state override on 480 and Sepolia is **81,825 gas** (1,764 B ABI calldata). V
- At 480's current price (base fee 0.000503 gwei, gas price about 0.0015 gwei) that's about 1.2e-7 ETH of L2 execution plus the L1 data fee. Negligible either way.

### 1.3 World ID 4.0 onchain

- **Addresses** (World Chain 480 only; code size 0 at both on 4801 and Sepolia): prod proxy `0x00000000009E00F9FE82CfeeBB4556686da094d7`, staging proxy `0x703a6316c975DEabF30b637c155edD53e24657DB`. Both proxies point at impl `0xff93a0146bf6e7557b63315efece083ca07d4c73`, read from EIP-1967 slot `0x3608…bbc`. Groth16 verifier: prod `0x00000000003f3659fA84731896ba1C417b8F8A25`, staging `0x72EF65C95e7569024c8Bc37F055A781E7Cc61C66`. `getTreeDepth()=30`, `getMinExpirationThreshold()=18000` s. V(cast; https://docs.world.org/world-id/idkit/onchain-verification; `worldcoin/world-id-protocol@7ac826e` `contracts/deployments/core/*.json`)
- **Deployed selectors:**
  - `verify(uint256 nullifier,uint256 action,uint64 rpId,uint256 nonce,uint256 signalHash,uint64 expiresAtMin,uint64 issuerSchemaId,uint256 credentialGenesisIssuedAtMin,uint256[5] zeroKnowledgeProof)` = `0xfd184bea`, present.
  - `verifySession(uint64,uint256,uint256,uint64,uint64,uint256,uint256,uint256[2],uint256[5])` = `0x9adc603e`, present.
  - `verifyWithSession(...)` = `0x8cd72920`, **absent**. It's in `UnreleasedWorldIDVerifierV3.sol` only, even though the spec README describes it.

  V(grep the selector in the impl bytecode)
- **What it checks** (`WorldIDVerifier.sol:151-210`):
  - Merkle root `proof[4]` is valid in WorldIDRegistry;
  - issuer schema is registered;
  - OPRF key for `rpId`;
  - `expiresAtMin + 18000 ≥ block.timestamp`;
  - the Groth16 proof over 15 public signals (nullifier, schema, issuer pk, expiresAtMin, genesis, root, depth, rpId, action, oprf pk, **signalHash**, **nonce**, sessionId);
  - V2 `verify` requires the action's top byte to be 0.

  It is `view`: **it stores no nullifiers, checks no RP signature, and doesn't hash the signal.** The caller passes `signalHash` and must compute it itself. The caller must also keep `usedNullifier`. V(source)
- **Gas:** the repo's `test/core/Verifier.t.sol::testVerifyNullifier` reports `verifyCompressedProof` = **288,153 gas**. V(forge test --gas-report). With 3 registry reads and the proxy it's about 300–320k per `verify`. E
- The legacy v3 `WorldIDRouter` exists on 480 (`0x17B354dD2595411ff79041f930e491A4Df39A278`), 4801 (`0x57f928158C3EE7CDad1e4D8642503c4D0201f611`) and Sepolia (`0x469449f251692e0779667583026b5a1e99512157`, per docs). It only takes the legacy presets (3.0 proofs), so it's not our path. V(cast codesize + docs)

### 1.4 EAS

- OP Stack predeploys on World Chain 480 **and** 4801:
  - EAS `0x4200000000000000000000000000000000000021`, `version()` = `"1.4.1-beta.3"`, `getSchemaRegistry()` = `0x…0020`;
  - SchemaRegistry `0x4200000000000000000000000000000000000020`, `version()` = `"1.3.1-beta.2"`.

  V(cast; https://docs.optimism.io/chain/identity/contracts-eas)
- Ethereum Sepolia: EAS `0xC2679fBD37d54388Ce493F1DB75320D236e1815e`, SchemaRegistry `0x0a7E2Ff54e76B8E6659aedc9103FB21c038050D0`. V(cast `getSchemaRegistry`)
- **No easscan explorer for World Chain**: `worldchain.easscan.org` and `worldchain-sepolia.easscan.org` don't resolve; `sepolia.easscan.org` returns 200. No EAS logs on 480 in the last 9,000 blocks. V(curl, cast logs)

### 1.5 Other contracts seen on the target chains

- Safe v1.4.1 `Safe` `0x29fcB43b46531BcA003ddC8FCB67FFE91900C762`, `SafeL2` `0x41675C099F32341bf84BFc5382aF534df5C7461a`, `SafeProxyFactory` `0x4e1DCf7AD4e460CfD30791CCC4F9c8a4f820ec67`. They have code on 480, 4801 and Sepolia. V(cast codesize); details are in `safe.md`.
- SP1 verifier gateways (`0x397A5f7f…`, `0x3B604117…`) exist on Sepolia, **not on 480**. V(cast codesize)

## 2. Unverified / conflicting

- **The P256 cost on 480 = 6,900 by spec**: inferred from a 7,379 gas diff. I didn't find a World Chain doc naming the hardfork that switched pricing. It doesn't matter for design.
- **Does the simulator (`environment: "staging"`) produce v4 proofs that the staging verifier `0x703a…` accepts onchain?** Untested (also open in `worldid.md`). It decides whether the onchain demo needs two Orb-verified humans.
- **How IDKit sets `expires_at_min`.** If it's "now", onchain World ID must be submitted within about 5 h (the 18,000 s threshold). U
- **`bytes1 role` in the World ID signal**: `pop-human-adapters.md` doesn't say whether it's ASCII `'A'`/`'B'` (0x41/0x42) or 0/1. I assume 0x41/0x42, same as POPT byte 5. **It must be pinned in the doc before the app builds it.**
- **Whether the World App refuses a second proof for the same (rp, action)** (the Oblivious Nullifier Pool, per `idkit-research-brief.md`). If it doesn't, equal nullifiers still catch it. Either way the contract must check `nullifierA != nullifierB` with the **same action**.
- **The zkVM wrap cost** (§3.4) is a back-of-envelope estimate from the 0.27 s native verify. Nobody has measured it. I also didn't confirm SP1's precompile list; I believe secp256r1 is accelerated and T-256 isn't.
- **EAS `attest` gas** of about 100–150k per attestation. U (not measured)
- The spec README describes `verifyWithSession`, but the deployed contract lacks it (§1.3). So **no onchain session-bound uniqueness proofs today**. Only plain `verifySession` (continuity, no uniqueness binding) is deployed.

## 3. The options, honestly

### 3.1 Trust table

What a single bad actor can fake, per path:

| Path | Server alone fakes presence? | One human with 2 phones? | Remote accomplice lends a World ID? | Phones cheat the DSP? | Device keys public? | Gas (480) |
|---|---|---|---|---|---|---|
| (a) server EIP-712 attestation only | **yes** | only if server lies | yes | only if server lies | no | ~35k + storage |
| (a) + World ID onchain | yes (presence), no (humans) | no | yes | – | no | ~0.67M |
| (c) tier 2: transcripts + P256 onchain + World ID onchain | **no**: needs both phones to sign a transcript with this nonce | no | yes | yes (a patched app can lie about `half`); option A offchain closes it | **yes** | ~0.72M |
| (d) option A proof onchain | no | no | yes | no | no (ZK) | infeasible (§3.4) |
| (b) EAS | same as whatever feeds it | | | | | +~100k+ U |

- **Still trusted in tier 2:**
  - The issuer's enrollment checks: attestation chains are verified offchain.
  - The server keeping the codes secret and enforcing commit-then-reveal. A server that leaks partner codes to a cheating phone breaks the audio assumption.
  - The app's DSP, unless option A is verified.
- **Onchain can't check** POPC ordering or `code_commit` (it needs the seed). Say so in the pitch: "a compromised server can't move your money, it can only refuse service".

### 3.2 (a) Server EIP-712 attestation

- It's the simplest path. The server gets a **secp256k1 attestor key**, separate from the P-256 SBcred3 issuer key, because it needs `eth_account` / `encode_typed_data` tooling and matches what EAS delegated attestations use.
- `ecrecover` costs 3,000 gas. Reusing the P-256 issuer key through the precompile would also work (6,900).

```
EIP712Domain(name="enconomy-pop", version="1", chainId=480, verifyingContract=PresenceRegistry)
Presence(bytes32 ctxHash, bytes32 sessionNonce, bytes16 sessionId, bytes32 pairTag,
         uint256 nullifierA, uint256 nullifierB, bytes32 deviceA, bytes32 deviceB,
         uint64 t0, uint64 notBefore, uint64 expiresAt, int32 flightMm,
         uint8 verdict, uint8 humanKind, bytes32 zkDigest)
```

`deviceA`/`deviceB` = `keccak256(pubkey65)`, or `bytes32(0)` in privacy mode (POOL). `zkDigest` = `keccak256(vkHashA ‖ proofSha256A ‖ vkHashB ‖ proofSha256B)`, or 0 when there's no ZK.

### 3.3 (b) EAS

- It's available as a predeploy on 480/4801. But it has no explorer there and no usage, and a consumer contract has to query it by UID.
- It adds gas and an indirection for nothing a custom registry doesn't do.
- **Use it only as an optional mirror** for demo visibility, and on Sepolia at that (easscan works there).
- Schema string, if we do it: `bytes32 ctxHash,bytes32 sessionNonce,bytes32 pairTag,uint256 nullifierA,uint256 nullifierB,uint64 t0,int32 flightMm,uint8 verdict,uint8 humanKind,bytes32 zkDigest`, revocable=false, with `resolver` = the PresenceRegistry, so an attestation only lands if the registry accepts it.

### 3.4 (d) Option A ZK onchain

- **The proof system:** `zk_spartan::R1CSSNARK<T256HyraxEngine>`, from the zkID Spartan2 fork rev `d687dbb` (`app/prover/README.md`, `Cargo.toml`).
  - Per phone: 1.23M R1CS (s48), a 1,648,255 B proof, 0.27 s warm verify on the M2.
  - Pair: 39,649 B (`research/sound-bound/spikes/zk/README.md`).
- **Native EVM verify:** 1.6 MB of calldata is about 26M gas of calldata alone (16 gas per byte, E), above a block. The Hyrax MSMs over T-256 have no precompile (T-256 isn't P-256; P256VERIFY only does ECDSA). **Out.**
- **Re-prove in Groth16/BN254:** everything is P-256-field native (Poseidon7 over the P-256 field, in-circuit ECDSA). Non-native emulation is about 100× (the spike README puts one non-native P-256 ECDSA in BN254 at about 2M constraints), so 1e8+ constraints. **Out.**
- **zkVM (SP1 / RISC Zero) runs the Spartan verifier, then a Groth16 wrap:** a 0.27 s native verify with non-accelerated 256-bit field arithmetic is about 1e10–5e10 RISC-V cycles. E. That's hours on a prover network per proof and $10–100-ish (E), and it needs the SP1 gateway deployed on 480 (it isn't). **Not for the hackathon.**
- **Do instead:**
  - The server verifies the option A proofs (it already does: `server/pop/zk.py`) and puts `zkDigest` in the attestation.
  - Publish the proofs (IPFS or `GET /v1/session/{id}/proof`) so anyone can re-run `popprover verify` against the pinned vk.
  - That's "publicly auditable", not "trustless". Pitch it that way.

### 3.5 (e) World ID in the same tx

- It works on 480 only. The contract must:
  1. pin `rpId`, `issuerSchemaId = 1` (Proof of Human), and the verifier address (prod, or staging for the demo);
  2. compute `signalHash_r = uint256(keccak256(abi.encodePacked(sessionNonce, bytes1(role)))) >> 8` itself, never from calldata;
  3. require the **same `action` for A and B**, with `nullifierA != nullifierB`. Otherwise one human proves twice under two actions, gets two different nullifiers, and passes as "two humans";
  4. keep `usedNullifier[n]`;
  5. submit within about 5 h of proof creation (U, §2).
- The World ID `nonce` public input is whatever the RP put in `rp_context`. The contract doesn't need to check it; the signal carries the binding. Recording it is harmless.
- **Action.** It stays `"pop:" + session_id`. The contract doesn't need to recompute it. It only needs A.action == B.action and the action unused (`usedAction[action]`). In tier 1 the server also signs `action` inside the attestation.

## 4. Binding the context before the run

This is what stops a presence proof being reused for another tx.

**Idea:** the phones already sign `session_nonce` (POPT offset 7, POPC offset 7), and the World ID signal is `encodePacked(session_nonce, role)`. So derive the nonce from the context:

```
ctxHash   = consumer-defined 32 bytes
            SAFE: safeTxHash (EIP-712 of the Safe tx; already includes chainId, Safe address, Safe nonce)
            POOL: keccak256(abi.encode("pool-xfer-v1", poolAddress, transferCommitment/publicInputsHash))
session_nonce = keccak256(abi.encode(
    keccak256("pop-ctx-v1"), uint256 chainId, address consumer, bytes32 ctxHash,
    uint64 notBefore,            // server time at session create, unix s
    bytes16 sessionId))          // random, already exists
```

- **Server change** (the other workflow owns `server/`; this is a proposal):
  - `POST /v1/session` takes optional `context: {chain_id, consumer, ctx_hash, kind: "safe-tx"|"pool-xfer", display: {...}}` and sets `nonce_hex` from the formula instead of `token_hex(32)` (`sessions.py:142`).
  - The session view shows `context` + `not_before` to the guest.
  - Without `context`, keep the random nonce.
- **App change** (small, later): before Confirm, recompute the nonce from `context` and abort on mismatch (`context_mismatch`), then show "Approve: send 1.2 ETH to 0xabc… from Safe 0xdef…" from `display`.
  - Without this check, a malicious server could bind a different tx than the user thinks.
  - With it, the phone's signature *is* the user's consent to that ctx.
- **Order of events** (unchanged from contract + adapters):
  1. ctx known;
  2. create session;
  3. join, confirm (nonce revealed);
  4. World ID A/B, with signal = (nonce, role);
  5. arm, audio run, transcripts;
  6. verdict;
  7. submit onchain.

  Everything after step 3 is bound to ctx.
- **The contract recomputes the nonce** from `(chainid, consumer=msg.sender or param, ctxHash, notBefore, sessionId)` and checks that it equals the transcripts' nonce (tier 2) or the attested nonce (tier 1). Then `consumed[ctxHash] = true`, or the consumer checks it once.
- **Freshness.** `notBefore` is only server-claimed. For tier 2, if the server shouldn't be trusted even on time, use a recent block hash instead: put `anchorBlockNumber` + `blockhash` in the preimage, and the contract checks it through `blockhash()` (256 blocks = 8.5 min on 480) or EIP-2935 (8,191 blocks ≈ 4.5 h on 480). That proves "the run happened after block N" without any trusted clock. Add `expiresAt = notBefore + TTL` (e.g. 15 min) checked against `block.timestamp`.
- **Retries.** Attempts 0/1 share the nonce, and that's fine. The registry records the attempt.

## 5. Minimal onchain PresenceAttestation (registry storage)

```solidity
struct PresenceAttestation {        // stored at presence[ctxHash]
    bytes32 sessionNonce;           // = derived nonce (§4); proves ctx binding
    bytes32 pairTag;                // sha256("pop-pair-v1" || min(nA,nB) || max(nA,nB)) as in pop-human-adapters.md, or keccak if cheaper; pick one
    uint256 nullifierA;             // World ID 4.0, same action, != nullifierB
    uint256 nullifierB;
    bytes32 deviceA;                // keccak256(pubkey65) (tier 2 / SAFE); 0 in privacy mode
    bytes32 deviceB;
    uint64  t0;                     // tier 1: server t0 (s); tier 2: block.timestamp at submit
    uint64  expiresAt;
    int32   flightMm;               // informational
    uint8   tier;                   // 1 = server-attested, 2 = transcripts verified onchain
    uint8   humanKind;              // 0 none, 1 worldid-4 (verified onchain), 2 worldid via server
    bytes32 zkDigest;               // 0 or hash of (vk, proof) pairs verified offchain
}
```

- 6–8 storage slots, about 130–170k gas for first-time writes. E. **Cheaper:** store only `keccak256(abi.encode(att))` plus `used` (1 slot, about 22k), and emit the full struct in `PresenceRecorded(ctxHash, att)`. A consumer that needs the fields gets them as calldata and checks the hash.
- `ctxHash` is the key, so one presence serves exactly one tx.
- The Safe tx nonce, or the pool nullifiers, make the ctx itself single-use.

### Contract surface (World Chain 480)

```solidity
interface IPresenceRegistry {
    function submitAttested(PresenceInput calldata p, bytes calldata serverSig, WorldIdProof[2] calldata h) external;
    function submitTranscripts(bytes calldata tA, bytes calldata sA, bytes calldata tB, bytes calldata sB,
                               bytes calldata credA, bytes calldata credSigA, bytes calldata credB, bytes calldata credSigB,
                               CtxInput calldata c, WorldIdProof[2] calldata h) external;
    function isPresent(bytes32 ctxHash) external view returns (bool);          // NEAR, unexpired, unconsumed
    function consume(bytes32 ctxHash) external;                                // only the ctx's consumer
}
struct WorldIdProof { uint256 nullifier; uint256 action; uint256 nonce; uint64 expiresAtMin; uint256[5] proof; }
struct CtxInput { address consumer; bytes32 ctxHash; uint64 notBefore; bytes16 sessionId; }
```

- `rpId`, `issuerSchemaId = 1`, `credentialGenesisIssuedAtMin = 0`, the verifier address, the issuer P-256 key (X,Y) and the attestor address are **immutable, or owner-rotatable**.
- `signalHash` is computed inside.
- Relayer-friendly: anyone can submit, because everything is bound by signatures and proofs.

## 6. Prototype code (tested; `popv/src/PopBridge.sol`)

Build: forge 1.4.3, solc 0.8.28, `evm_version = "osaka"` (so the local EVM has 0x100), `via_ir = true` (stack depth).

```solidity
library PopBridge {
    address constant P256 = address(0x100);
    uint256 constant C_CM_S = 34300; int256 constant NEAR_CM = 60; int256 constant IMPOSSIBLE_CM = -20; uint256 constant SELF_OS_TOL_MS = 50;
    struct Half { uint8 role; uint8 attempt; bytes32 nonce; bytes32 pkX; bytes32 pkY; bytes32 ptX; bytes32 ptY; uint32 sr; int32 half; int32 selfOs; }
    function p256(bytes32 h, bytes32 r, bytes32 s, bytes32 x, bytes32 y) internal view returns (bool) {
        (bool ok, bytes memory out) = P256.staticcall(abi.encode(h, r, s, x, y));
        return ok && out.length == 32 && uint256(bytes32(out)) == 1;           // failure = empty returndata
    }
    function parse(bytes calldata t) internal pure returns (Half memory h) {   // POPT v2, docs/pop-transcript-v2.md §1
        require(t.length == 311 && bytes5(t[0:5]) == bytes5(0x504f505402) && t[39] == 0x04 && t[104] == 0x04);
        h.role = uint8(t[5]); h.attempt = uint8(t[6]); h.nonce = w(t,7);
        h.pkX = w(t,40); h.pkY = w(t,72); h.ptX = w(t,105); h.ptY = w(t,137);
        h.sr = u32(t,169); h.half = int32(u32(t,173)); h.selfOs = int32(u32(t,233));
    }
    // SBcred3 = "SBcred3" || X || Y || expiry u64 BE || holder_commit (111 B); issuer sig over sha256(cred)
    function checkCred(bytes calldata cred, bytes calldata sig, bytes32 ix, bytes32 iy, bytes32 x, bytes32 y, uint64 at) internal view {
        require(cred.length == 111 && bytes7(cred[0:7]) == bytes7("SBcred3") && w(cred,7) == x && w(cred,39) == y);
        require(uint64(bytes8(cred[71:79])) >= at && p256(sha256(cred), w(sig,0), w(sig,32), ix, iy));
    }
    function verify(...) internal view returns (bool near, bytes32 nonce, int256 flightX, Half memory a, Half memory b) {
        a = parse(tA); b = parse(tB);
        require(a.role == 0x41 && b.role == 0x42 && a.nonce == b.nonce && a.attempt == b.attempt);
        require(a.ptX == b.pkX && a.ptY == b.pkY && b.ptX == a.pkX && b.ptY == a.pkY && !(a.pkX == b.pkX && a.pkY == b.pkY));
        require(p256(sha256(tA), w(sA,0), w(sA,32), a.pkX, a.pkY) && p256(sha256(tB), w(sB,0), w(sB,32), b.pkX, b.pkY));
        checkCred(cA, csA, issuerX, issuerY, a.pkX, a.pkY, validAt); checkCred(cB, csB, issuerX, issuerY, b.pkX, b.pkY, validAt);
        // |self_os_delta|*1000 <= 50*sr for both
        int256 den = 2 * int256(uint256(a.sr)) * int256(uint256(b.sr));
        flightX = int256(C_CM_S) * (int256(a.half) * int256(uint256(b.sr)) - int256(b.half) * int256(uint256(a.sr)));
        near = flightX > IMPOSSIBLE_CM * den && flightX < NEAR_CM * den;  nonce = a.nonce;
    }
}
```

Notes for implementers:

- **`validAt` for credential expiry:** use `block.timestamp`. The ZK path uses `t0_ms // 1000`; onchain can't see t0.
- **The verdict rule is the server's `combine()`, bit for bit, except retries.** Onchain accepts any attempt whose own transcripts give NEAR. The server's retry rules can't produce a different NEAR from the same two signed transcripts, so this is safe.
- **Not checked onchain:** `code_commit`, the POPC commit, the recording. The server enforces those. The registry can additionally require the tier 1 server signature in tier 2 ("both") if we want the server's view too. That costs about 3k gas more.

## 7. Implications for the SAFE idea

- **Use tier 2.** Owners are public anyway, so device keys onchain cost nothing in privacy. The big pitch line: "the enconomy server can't approve your Safe tx: the contract checks both phones' hardware-key signatures and does the distance math itself".
- **Owner ↔ device binding:** register each owner's device key hash in the guard/module at setup (`owner → keccak(pubkey65)`). Each owner's EOA signs that registration, or the Safe itself does it through a Safe tx.
  - At execution, require `{deviceA, deviceB}` ⊂ registered owner devices, and the two devices belong to two different owners.
  - World ID adds "two distinct humans". With per-session actions, World ID can't say *which* humans (its nullifiers are unlinkable by design).
  - For "same World ID as the enrolled owner" you'd need `verifySession` + stored sessionIds (deployed), but that's continuity, not uniqueness; the uniqueness-bound `verifyWithSession` isn't deployed (§1.3).
  - **Recommendation:** device registry = who; World ID = two different humans. Good enough for the demo.
- **ctxHash = safeTxHash.** In Safe v1.4.1 the guard's `checkTransaction` gets the tx params, not the hash, and the nonce is already incremented, so the guard recomputes with `nonce - 1`. U. The SAFE agent must check this in `Safe.sol`.
- **PoP is pairwise.** For an n-of-m Safe with n > 2 you need multiple sessions (A–B, B–C), and closeness isn't transitive (≤ 120 cm across 3). For the demo, 2-of-2 or 2-of-3.
- **The phone's P-256 key could itself be a Safe signer**, through Safe's passkey/P-256 signer contracts using the same 0x100 precompile. U. That would let the phone approve and prove presence with one key. It's a stretch goal; see `safe.md`.
- Gas: about 82k (transcripts) + about 630k (2× World ID) + storage, fractions of a cent on 480.

## 8. Implications for the POOL idea

- **Tier 2 leaks the social graph:** stable device pubkeys onchain link every meeting of the same two phones. **Use tier 1 in privacy mode:** `deviceA = deviceB = 0`, plus the server-signed nonce, pairTag and nullifiers.
  - World ID nullifiers are fresh per action, so they're unlinkable across meetings.
  - Round `t0` to a bucket (e.g. 10 min), or omit it, to cut timing correlation.
- **The honest trust statement:** "the operator attests presence; World ID onchain proves two distinct humans; the operator can't know amounts (pool ZK), but it knows who met whom and when" (our server sees device ids).
- **ctx = the pool tx's public-input hash** (new commitments / nullifiers / recipient-commitment). It must be fixed **before** the audio run, so the payer builds the transfer first and then starts PoP with that ctxHash. That affects the UX order: build tx, meet, prove, submit.
- **Stronger option later:** the server signs the attestation with an in-circuit-friendly key (EdDSA-BabyJubJub or Poseidon-friendly, about 10k constraints in BN254 circom). The pool's own transfer circuit then proves "a valid presence attestation exists for this transfer's ctx" privately. The session, the time and even the pair_tag stay hidden. World ID would then also have to move offchain (server-verified) or be verified onchain separately (the nullifier is public but unlinkable). This is a POOL-circuit design task, U, and not needed for the demo.
- The option A proof still stays offchain (§3.4).

## 9. Open questions

1. Does staging (`environment: "staging"`, the simulator) produce v4 proofs that `0x703a…` (the staging WorldIDVerifier on 480) accepts? This decides whether the demo needs two Orb-verified humans. Test it with one simulator proof via `cast call`.
2. Is our `rp_id` registered in the staging OPRF key registry (`getOprfPublicKey(rpId)` non-zero on the staging stack)? Check with cast once the rp_id is known.
3. IDKit's `expires_at_min` semantics: how long after proving can it still be verified onchain?
4. Pin the `bytes1 role` encoding in the World ID signal (0x41/0x42 proposed).
5. The server owners (other workflow) accept the nonce derivation (§4) + `context` in `POST /v1/session`, and the app adds the context check and display before Confirm.
6. pairTag hash: keep `sha256` (as in the adapters doc; about 100 gas on EVM) or switch to keccak? Keep sha256 for one definition everywhere.
7. SAFE: the exact guard hook and safeTxHash recomputation in v1.4.1 (`nonce - 1`?). Module vs guard.
8. POOL: which pool codebase (Railgun is on Ethereum/Polygon/Arbitrum/BSC; is there a World Chain deployment?) and whether its circuit can take an extra public input `ctxHash`/`presenceRoot`.
9. Do we want tier 2 to also require the server signature, for defense in depth (code secrecy is server-side anyway)?
10. For the issuer key onchain: pin the prod issuer pubkey from `GET /v1/config` (`issuer.pub_x/pub_y`), with a rotation plan.

## Sources

- https://eips.ethereum.org/EIPS/eip-7951 (P256VERIFY 0x100, 6,900 gas)
- https://docs.world.org/world-id/idkit/onchain-verification (4.0 addresses, `verify` signature, caller stores nullifiers, legacy router table)
- https://github.com/worldcoin/world-id-protocol @ `7ac826e6` (2026-09-25): `contracts/src/core/WorldIDVerifier.sol`, `WorldIDVerifierV2.sol`, `UnreleasedWorldIDVerifierV3.sol`, `contracts/deployments/core/{production,staging}.json`, `docs/world-id-4-specs/README.md` (session proofs), `contracts/test/core/Verifier.t.sol` (gas)
- https://docs.optimism.io/chain/identity/contracts-eas (EAS predeploys)
- https://hackmd.io/@nebra-one/ByoMB8Zf6 (Groth16 ≈ 181k + 6k·ℓ gas, consistent with the 288k measured at ℓ = 15 + decompression)
- https://github.com/succinctlabs/sp1-contracts (gateway; no 480 deployment found)
- Local: `docs/pop-transcript-v2.md`, `docs/pop-human-adapters.md`, `git show HEAD:docs/pop-contract.md` §8, `server/README.md` (SBcred3), `server/pop/verdict.py`, `server/pop/sessions.py:142`, `research/sound-bound/spikes/zk/README.md`, `app/prover/README.md`, `~/dev/worldid-spike/docs/idkit-research-brief.md`
