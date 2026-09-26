# World ID stack, as of 2026-09-26

Research note for the SAFE / POOL decision. Everything is tagged:

- **V(src)**: verified from primary source, onchain call, or our own logs.
- **U**: unverified, inferred, or conflicting.

Scratch clones (commit dates): `worldcoin/world-id-protocol` 7ac826e (2026-09-25), `worldcoin/idkit` 16bc527 (2026-09-23), `worldcoin/developer-docs` 10536b5 (2026-09-23), `worldcoin/minikit-js` 54eafe0 (2026-09-20), `worldcoin/world-id-agent-plugin` 72bb597 (2026-09-23). They live in the session scratchpad under `wid/`.

Prior work reused here: `~/dev/worldid-spike` (Android KMP + FastAPI). Its backend log, `backend/logs/backend.log`, has real production v4 proofs from 2026-09-24. Its brief, `docs/idkit-research-brief.md`, covers the IDKit and mobile details in more depth than this note.

---

## 0. TL;DR for the design doc

1. **The protocol is World ID 4.0. IDKit is 4.x.**
   - The RP registers in the Developer Portal and gets `app_id`, `rp_id` and `signing_key`.
   - Every request carries a backend-signed `rp_context`.
   - The proof is made in the World ID app, not in our app.
2. **Per-session dynamic actions work without registration.** Two independent sources show it:
   - Our spike verified two different unregistered actions (`spike-1790264612780`, `spike-1790264710529`) in production. The Portal returned `success: true`.
   - The official `@worldcoin/human-in-the-loop` package defaults the action to the tool-call id.
3. **Nullifiers are one-time-use in v4.**
   - The nullifier is deterministic per (World ID, rp_id, action).
   - The authenticator refuses to issue it twice.
   - So a failed PoP run after the World ID step can't be retried with the same action. Retry means a new session id, which means a new action.
4. **Onchain v4 verification exists, but only in these places:**
   - **World Chain mainnet (480)**, via `WorldIDVerifier`. The production and staging proxies both live on chain 480. There is **no v4 verifier on any testnet**.
   - Base and Arc (and Tempo), via `WorldIDSatellite` bridges. These are marked WIP/unaudited and lag World Chain by about an hour.
   - We replayed a real spike proof through `eth_call` at a historical block, and it passed. It costs about 400k gas.
5. **Onchain proofs go stale fast.**
   - `expiresAtMin + 18000 s` must be at least `block.timestamp`, so there are 5 h after the RP signature is created.
   - The root must still be valid: either the latest root, or at most 3600 s after it was set.
   - So a proof collected at a meeting has to land onchain within about 1 h. We can't keep it for later.
6. **The contract must pin these values:** `issuerSchemaId = 1` (Proof of Human), `rpId`, the action, and the signal hash. If they come from calldata, anyone can swap in a Passport or Selfie proof, or another action.
7. **Prize fit.** The World track has two $5k prizes:
   - "Best Use of IDKit" (2 × $2.5k).
   - "Best Use of World ID for Agents" (2 × $2.5k). This is an OIDC product at `sandbox.auth.world.org`, not IDKit.
   - Both SAFE and POOL fit IDKit's "trust moment" framing. Proof of Human is the minimum sufficient credential for "two *distinct* humans".

---

## 1. Verified facts

### 1.1 Protocol version and registration

| Fact | Source |
|---|---|
| The current protocol is World ID 4.0. Proof responses carry `protocol_version:"4.0"`. Legacy 3.0 proofs are still accepted when `allow_legacy_proofs: true`. | V(developer-docs `world-id/idkit/integrate.mdx`; spike log 2026-09-25 00:44) |
| The Portal issues `app_id`, `rp_id` and `signing_key`. Older apps must click "Enable World ID 4.0". | V(`integrate.mdx` step 2) |
| An RP is registered **onchain** in `RpRegistry` on World Chain as `RelyingParty{initialized, active, manager, signer, oprfKeyId, unverifiedWellKnownDomain}`, and `oprfKeyId == rpId`. | V(`contracts/src/core/interfaces/IRpRegistry.sol`; `WorldIDVerifier.sol:174`) |
| Our spike RP `rp_1469245f4f78143c` is registered. Its `rpId` is uint64 `0x1469245f4f78143c` = `1470746745086940220`. The onchain signer is `0xd0221b8F6f1fcDb506Ecb66fFc658626dddE8582`, which matches the spike's `WORLD_SIGNER_ADDRESS`. | V(`cast call 0xD9A213A92Bca460D56cDbBF4d775b48fB5925BbC "getOprfKeyIdAndSigner(uint64)" 0x1469245f4f78143c`, World Chain) |
| An `rp_id` string is `"rp_" + 16 lowercase hex chars` of a u64. | V(`world-id-protocol/crates/primitives/src/rp.rs` test `rp_123456789abcdef0`) |

### 1.2 RP signature (`rp_context`)

- The message is 49 bytes, or 81 bytes with an action:
  - `0x01`
  - `nonce(32)`
  - `created_at u64be`
  - `expires_at u64be`
  - optionally `hash_to_field(utf8(action))(32)`
- The signature is secp256k1 over the EIP-191 personal_sign of that message. It is encoded as `r‖s‖v` with v = 27 or 28.
- `nonce = hash_to_field(random32)`.
- The default TTL is 300 s.
- V(`world-id-protocol/crates/primitives/src/rp.rs:107`; `developer-docs world-id/idkit/signatures.mdx` §Algorithm).
- Python port with parity tests against the official Node signer: `~/dev/worldid-spike/backend/app/signing.py`. V(spike README, tests).
- Session requests are signed **without** an action. V(`session-proofs.mdx`).
- A reused nonce gives the error `duplicate_nonce`. V(`error-codes.mdx`)

### 1.3 Hashing: action and signal

- `hash_to_field(b) = uint256(keccak256(b)) >> 8`. V(`idkit/rust/core/src/crypto.rs:326`; `world-id-protocol/crates/primitives/src/lib.rs:147 from_arbitrary_raw_bytes`)
- **Action field** = `hash_to_field(utf8(action))`. In Solidity: `uint256(keccak256(bytes(action))) >> 8`.
  - An unreduced hash can revert with `PublicInputNotInField`.
  - The deployed V2 verifier also reverts with `InvalidAction()` (0x4a7f394f) if the top byte is nonzero.
  - V(`onchain-verification.mdx`; `WorldIDVerifierV2.sol`; probed onchain: `verify(...)` with action `0xff00…` reverts `0x4a7f394f`)
- **Signal hash**. A string that is valid, non-empty, even-length `0x` hex is decoded to bytes. Any other string is hashed as UTF-8. Then `hash_to_field`.
  - So `signal = "0x" + hex(abi.encodePacked(...))` means Solidity can recompute it as `uint256(keccak256(abi.encodePacked(...))) >> 8`.
  - V(`crypto.rs` `hash_signal`, doc comment)

### 1.4 Nullifier semantics

- The nullifier is deterministic per (World ID leaf, rpId, action), computed by a threshold OPRF. It doesn't depend on which authenticator or device made the proof. V(`world-id-4-specs/README.md` §Definitions, §Multi-key)
- **One-time use**: "Authenticators will not issue a nullifier more than once." V(spec README line 78)
  - So the nullifier is **not** a pseudonymous user id any more.
  - For returning-user continuity, v4 has **session proofs** instead.
- The format is a 0x-hex 256-bit value, below the BN254 scalar field. Store it as `NUMERIC(78,0)` with `UNIQUE(nullifier, action)`. V(`integrate.mdx` step 6)
- The Portal verifies cryptographic validity only. **Our backend or contract must store nullifiers.** V(`integrate.mdx` step 6: "The Developer Portal confirms the proof is cryptographically valid, but your backend must check that the nullifier hasn't been used before")
- Uniqueness sets are **per credential**. One person can have PoH in one World ID and a passport credential in another. V(spec §Session Proofs, "Uniqueness sets are independent")
  - So "two different humans" holds only if both proofs are `issuer_schema_id = 1` (PoH).

### 1.5 Credentials and verification levels (v4)

| Preset | `issuer_schema_id` | Assurance | Note |
|---|---|---|---|
| `proofOfHuman` | 1 | Orb, unique human | Falls back to legacy Orb when legacy proofs are allowed |
| `passport` | 9303 | Unique NFC document, not unique human | Falls back to legacy Document |
| `selfieCheck` | 11 | Liveness plus face similarity, returns `sybil_score`, **not** one-per-human | Docs recommend using it with sessions |
| `identityCheck` | — | Attribute attestation | Preview; you must contact World |
| `orbLegacy`, `deviceLegacy`, `documentLegacy`, `selfieCheckLegacy` | — | Return 3.0 proofs | "Device" exists only as legacy |

- `require_user_presence` adds a fresh liveness check to any preset. On failure the error is `user_presence_failed`.
- V(`developer-docs world-id/idkit/credentials.mdx`; `/credentials/1|9303|11`; spike brief §3; `error-codes.mdx`)

### 1.6 v4 proof payload

```
{ protocol_version:"4.0", nonce, action, environment,
  responses:[{ identifier:"proof_of_human", issuer_schema_id:1, nullifier:"0x…",
               signal_hash:"0x…", expires_at_min:<unix s>, proof:[5 × uint256 decimal] }],
  integrity_bundle?:{version, signature_format:"android_keystore"|"apple_app_attest", timestamp, signature, jwt} }
```

- `proof[0..3]` is a compressed Groth16 proof over BN254. `proof[4]` is the WorldIDRegistry Merkle root. V(`IWorldIDVerifier.sol` natspec)
- In the spike's production proof, `expires_at_min` equals `rp_context.created_at` (1790264612). So in practice the 5 h onchain window starts at signing time. V(spike log)
- Our real proof carried an `integrity_bundle` (Android Keystore). Its JWT `aud` = `rp_1469245f4f78143c` and `iss` = `attestation.worldcoin.org`. V(spike log, JWT decoded)

### 1.7 Cloud verification (Developer Portal)

- The endpoint is `POST https://developer.world.org/api/v4/verify/{rp_id}`. It needs no auth.
  - It accepts v4 uniqueness proofs, session proofs and legacy v3 proofs. Forward the IDKit result unchanged.
  - V(openapi `developer-docs/openapi/developer-portal.json`; spike log)
- Success response: `{success:true, action, nullifier, created_at, environment:"production"|"staging"|"sandbox", session_id?, results:[…], message}`. V(openapi `VerifyV4SuccessResponse`; spike log)
- Error codes seen for real:
  - `all_verifications_failed` with `verification_failed` "execution reverted (unknown custom error)", for a garbage proof.
  - `validation_error` "action is required for uniqueness proofs".
  - `validation_error` "At least one response item is required".
  - V(spike log 2026-09-24)
- **The `environment` field comes from the client. The backend must pin it to `production`.** Otherwise a staging or sandbox (test) proof passes. V(`agents/human-in-the-loop/integrate.mdx` code comment; `integrate.mdx` step 5)
- Other Portal endpoints (V, openapi):
  - `POST /api/v2/create-action/{app_id}` (Bearer API key) creates an "incognito action" with `max_verifications` (default 1).
  - `POST /api/v1/precheck/{app_id}`
  - `POST /api/v2/verify/{app_id}` (legacy)
  - MiniKit endpoints.

### 1.8 Onchain verification, v4

Interface (V: `contracts/src/core/interfaces/IWorldIDVerifier.sol`, `onchain-verification.mdx`):

```solidity
function verify(uint256 nullifier, uint256 action, uint64 rpId, uint256 nonce, uint256 signalHash,
                uint64 expiresAtMin, uint64 issuerSchemaId, uint256 credentialGenesisIssuedAtMin,
                uint256[5] calldata zeroKnowledgeProof) external view;           // reverts on failure
function verifySession(uint64 rpId, uint256 nonce, uint256 signalHash, uint64 expiresAtMin,
                uint64 issuerSchemaId, uint256 credentialGenesisIssuedAtMin, uint256 sessionId,
                uint256[2] calldata sessionNullifier, uint256[5] calldata zeroKnowledgeProof) external view;
```

What `verifyProofAndSignals` checks (V, `WorldIDVerifier.sol:151-200`):

- `isValidRoot(proof[4])`. Otherwise `InvalidMerkleRoot()`, 0x9dd854d3.
- The issuer schema is registered. Otherwise `UnregisteredIssuerSchemaId()`, 0xc7eb504d.
- The OPRF public key is looked up by rpId.
- `expiresAtMin + minExpirationThreshold >= block.timestamp`. Otherwise `ExpirationTooOld()`, 0xf00ab3b4.
- The Groth16 proof verifies. Otherwise `ProofInvalid()`, 0x7fcdd1f4.

It does **not** check the RP signature or nonce freshness, and it does **not** store nullifiers. Our contract does both.

Deployments, all V by `cast codesize`/`cast call` on 2026-09-26 and `contracts/deployments/*.json`:

| Env | Chain | Contract | Address |
|---|---|---|---|
| prod | World Chain 480 | WorldIDVerifier proxy | `0x00000000009E00F9FE82CfeeBB4556686da094d7` |
| staging | World Chain 480 | WorldIDVerifier proxy | `0x703a6316c975DEabF30b637c155edD53e24657DB` |
| prod | World Chain 480 | WorldIDRegistry proxy | `0x0000000000aE079eB8a274cD51c0f44a9E4d67d4` |
| prod | World Chain 480 | RpRegistry proxy | `0xD9A213A92Bca460D56cDbBF4d775b48fB5925BbC` |
| prod | World Chain 480 | CredentialSchemaIssuerRegistry | `0x941239840F4d9668da8be76b568e836b50685d2c` |
| prod | World Chain 480 | OprfKeyRegistry | `0x0D8b461799474207A3d223553d4d5e6609cb0c69` |
| prod | Base 8453 | WorldIDSatellite proxy | `0x8127DB9301683553a2610a046dE24dde741A1B80` (not in docs table, but in the repo deployments; live) |
| prod | Arc 5042 | WorldIDSatellite proxy | `0x304E14e4dC0508C0927e3b307a2C18422C07E394` |
| prod | Tempo 4217 | WorldIDSatellite proxy | `0x0E874EAf3c634f1b3C74Ca56B56C8b0B24f3c1DE` |
| staging | Base 8453 | WorldIDSatellite proxy | `0xcC72Ca7BfB5E55613505EceBB6C97dA5E1131E21` |

- Both the production and staging World Chain proxies currently point at implementation `0xff93a0146bf6E7557B63315efeCe083Ca07D4C73`. That is V2 logic: it has the `InvalidAction` top-byte check. V(`cast implementation`)
- `verifyWithSession` (a uniqueness proof bound to a new session) is **not deployed**. Calling it reverts with no data. It lives in `UnreleasedWorldIDVerifierV3.sol`. V(probe)
- Live parameters on World Chain prod:
  - `getMinExpirationThreshold() = 18000` s
  - `getTreeDepth() = 30`
  - `WorldIDRegistry.getRootValidityWindow() = 3600` s
  - Base satellite: `ROOT_VALIDITY_WINDOW = 3600`, `MIN_EXPIRATION_THRESHOLD = 18000`
  - V(cast)
- The Base satellite root lagged. The latest Base root was relayed at ts 1790401485, while `now` was 1790404877, a lag of about 57 min. The satellite uses a **permissioned gateway** (owner-attested relay).
  - The crosschain README says: "work in progress and unaudited. DO NOT USE IN PRODUCTION".
  - Our RP's OPRF key *is* present on the Base satellite.
  - V(cast; `contracts/src/crosschain/README.md`)
- **End-to-end replay of a real proof.**
  - We replayed spike proof `spike-1790264612780` against the World Chain prod verifier at block 35464531 (ts 1790264701, about 90 s after the proof). It **passed**; the call returned empty with no revert.
    - Args: action = `hash_to_field("spike-1790264612780")`, rpId = 1470746745086940220, issuerSchemaId = 1, genesisMin = 0.
  - The same call at the latest block reverts `InvalidMerkleRoot`, because the root has expired.
  - Flipping one bit of the nullifier gives `ProofInvalid`.
  - `cast estimate` = **419,429 gas**, including the 21k base cost.
  - V(commands in the appendix)

### 1.9 Onchain verification, legacy v3 (`WorldIDRouter`)

- `verifyProof(uint256 root, uint256 groupId, uint256 signalHash, uint256 nullifierHash, uint256 externalNullifierHash, uint256[8] proof)`.
  - `groupId = 1` (Orb only onchain).
  - `externalNullifierHash = hashToField(abi.encodePacked(hashToField(abi.encodePacked(appId)), action))`.
  - V(`developer-docs world-id/reference/contracts.mdx`, `onchain-verification.mdx` §1)
- Router addresses (docs):

  | Chain | Mainnet | Testnet |
  |---|---|---|
  | World Chain | `0x17B354dD2595411ff79041f930e491A4Df39A278` | WC Sepolia `0x57f928158C3EE7CDad1e4D8642503c4D0201f611` |
  | Ethereum | `0x163b09b4fe21177c455d850bd815b6d583732432` | Sepolia `0x469449f251692e0779667583026b5a1e99512157` |
  | Base | `0xBCC7e5910178AFFEEeBA573ba6903E9869594163` | Base Sepolia `0x42FF98C4E85212a5D31358ACbFe76a621b50fC02` |
  | Optimism | `0x57f928158C3EE7CDad1e4D8642503c4D0201f611` | OP Sepolia `0x11cA3127182f7583EfC416a8771BD4d11Fae4334` |
  | Polygon | `0x515f06B36E6D3b707eAecBdeD18d8B384944c87f` | — |

  - Code presence was verified onchain for WC mainnet, WC Sepolia and Base. The rest come from the docs only.
- The docs page is marked deprecated. It's only useful if a user returns a legacy proof, or for a testnet-only demo with simulator credentials (U: whether the simulator still issues v3 proofs usable on Sepolia).

### 1.10 SDKs (versions as of 2026-09-26)

| Package | Version | Note |
|---|---|---|
| `@worldcoin/idkit-core` (JS/WASM) | 4.3.0 | `IDKit.request/createSession/proveSession`, `signRequest` in `/signing` |
| `@worldcoin/idkit` (React) | 4.3.0 | `IDKitRequestWidget`, `IDKitSessionWidget` |
| Swift SPM `worldcoin/idkit-swift` | tag 4.0.11 | UniFFI |
| Kotlin `com.worldcoin:idkit` | 4.0.7 | **Not on Maven Central** (`repo1.maven.org/.../com/worldcoin/idkit/maven-metadata.xml` returns 404). GitHub Packages or a build from source; the spike has `scripts/build-idkit-from-source.sh` |
| Go `github.com/worldcoin/idkit/go/idkit` | — | `SignRequest` |
| `@worldcoin/minikit-js` / `-react` | 2.0.3 | MiniKit v2: no verify; use IDKit |
| `@worldcoin/human-in-the-loop` | 0.2.1 | Agent approval via IDKit |
| `@worldcoin/agentkit` | 0.2.1 | x402 plus AgentBook on World Chain |

- Sources: V(`npm view`; `git ls-remote idkit-swift`; `idkit/kotlin/gradle.properties`; maven 404).
- `@worldcoin/idkit-react-native` is deprecated and pre-v4. V(spike brief)

### 1.11 Mobile flow

- `connectorURI` works both as a same-device universal link into the World ID app (then back via `return_to`) and as a cross-device QR code. V(`integrate.mdx`; spike Android run)
- A custom-scheme `return_to` is proven on Android (`worldidspike://callback`). V(spike README)
- The deep link carries no data. The result comes from bridge polling (`bridge.worldcoin.org`, AES-256-GCM). V(spike README; spike brief)
- iOS has no deferred deep link. Use invite-code mode: a 6-character code, 15-minute TTL, one-shot. V(`verification-flows.mdx`)
- Error codes (28): `user_rejected`, `verification_rejected`, `credential_unavailable`, `malformed_request`, `invalid_network`, `inclusion_proof_pending`, `inclusion_proof_failed`, `unexpected_response`, `connection_failed`, `max_verifications_reached`, `failed_by_host_app`, `invalid_rp_signature`, `nullifier_replayed`, `duplicate_nonce`, `unknown_rp`, `inactive_rp`, `timestamp_too_old`, `timestamp_too_far_in_future`, `invalid_timestamp`, `rp_signature_expired`, `user_presence_failed`, `identity_attributes_not_matched`, `generic_error`, `invalid_rp_id_format`, `timeout`, `cancelled`. V(`error-codes.mdx`)

### 1.12 Session proofs

- `IDKit.createSession({app_id, rp_context})` gives a `session_id` (`session_<128 hex>`) plus an initial proof.
- `IDKit.proveSession(savedSessionId, …)` gives a proof that it is the same World ID. The response carries `session_nullifier: [nullifier, randomAction]`.
- No action is used. The RP signature is made without an action.
- V(`session-proofs.mdx`; openapi `session_v4` example)
- `sessionId = encode(H(DS_C‖leafIndex‖r), oprf_seed)`, with a **random oprf_seed on each creation**. So one human can mint many sessions: sessions give continuity, **not uniqueness**. V(spec §Session Proofs)
- Binding a uniqueness proof to a new session (`sessionId="create"`) is specified but needs `verifyWithSession`, which is not deployed. V(spec; probe)
- The docs show sessions with `selfieCheck()`. Whether `proofOfHuman` works with sessions is U; the older brief found that presets throw on session flows in the code.

### 1.13 Staging, simulator and sandbox

- **Staging**: `environment:"staging"` together with `simulator.worldcoin.org`. V(`integrate.mdx` step 4)
- **Sandbox**: `environment:"sandbox"`, using separate World ID app builds (TestFlight, and a private Play track), requested per team in the Portal under "World ID Sandbox". It has simulated verification, resettable accounts and toggleable fraud gating. Verify against the same production `/api/v4/verify`. V(`sandbox/what-is-sandbox.mdx`, `sandbox-access.mdx`)
- The prize page lists the Simulator `https://simulator.worldcoin.org/id/0x18310f83` and the iOS sandbox TestFlight `https://testflight.apple.com/join/Tub7zuyD`. V(scratchpad `wid/tokyo_prizes.txt`, from ethglobal.com/events/tokyo2026/prizes)

### 1.14 MiniKit, Mini Apps and World Chain

- MiniKit 2.x covers `walletAuth`, `sendTransaction`, `signMessage`, `signTypedData`, `pay`, `share`, permissions, notifications and so on.
  - `MiniKit.verify` is gone. IDKit runs inside a mini app over native transport, with no QR.
  - V(`mini-apps/commands/verify.mdx`, `world-id/idkit/mini-apps.mdx`)
- `sendTransaction({chainId:480, transactions:[{to,data,value?}…]})` returns a `userOpHash`, not a transaction hash. Poll `GET /api/v2/minikit/userop/{hash}`.
  - Every contract entrypoint and Permit2 token must be **allowlisted** in the Portal. Otherwise you get `invalid_contract` or `disallowed_operation`.
  - Permit2 allowance transfers are recommended. SignatureTransfer is gone in v2.
  - V(`send-transaction.mdx`)
- Gas: "World App sponsors gas fees for most transactions on Worldchain, subject to transaction minimums and restrictions." V(`mini-apps/more/faq.mdx`)
- Testnets: "mini app needs to be developed on mainnet (we don't support testnet)". V(same FAQ)
- The microphone works in mini apps via `getUserMedia`. Speaker and ultrasonic behaviour is undocumented. V/U(spike brief §4)
- On 2026-09-17 World split into the **World ID app** (identity) and **World Money** (wallet and mini apps). V(news: criptocurrencies.com 2026-09-19, kucoin, parameter.io) U(exact developer impact)
- World Chain: mainnet 480, Sepolia 4801, public RPC `https://worldchain-mainnet.g.alchemy.com/public`. V(`world-chain/quick-start/info.mdx`; cast)
- These contracts are present on **both 480 and 4801**, V(cast codesize):
  - Safe 1.4.1 SafeL2 `0x29fcB43b46531BcA003ddC8FCB67FFE91900C762`
  - SafeProxyFactory 1.4.1 `0x4e1DCf7AD4e460CfD30791CCC4F9c8a4f820ec67`
  - Safe 1.4.1 `0x41675C099F32341bf84BFc5382aF534df5C7461a`
  - `0x14F2982D601c9458F93bd70B218933A6f8165e7b` (believed to be the Safe 1.5.0 factory, U)
  - Permit2 `0x000000000022D473030F116dDEE9F6B43aC78BA3`
  - EntryPoint v0.7 `0x0000000071727De22E5E9d8BAf0edAc6f37da032`
- The RIP-7212 P-256 verify precompile (`0x0000…0100`) works on 480 and 4801. V(`cast call`, fresh signature, returned `1`)

### 1.15 World ID for Agents (a separate prize)

- The prize text: "Integrate with the official World ID for Agents on dev environment provided for the event" and "We are mocking proofs now, so you don't need sandbox app anymore". V(prize page)
- It is an **OIDC provider**. From `https://sandbox.auth.world.org/.well-known/openid-configuration`:
  - issuer `https://sandbox.auth.world.org`
  - authorize `/api/v1/authorize`, token `/api/v1/token`, **device authorization** `/api/v1/device_authorization`
  - grants `authorization_code` and `device_code`, PKCE S256
  - `subject_types_supported: ["pairwise"]`
  - `acr_values_supported: ["https://world.org/oidc/acr/orb-v3"]`
  - `prompt: none|login`
  - RS256 id_token, JWKS `/.well-known/jwks.json`
  - V(curl)
- The pairwise `sub` is a **stable per-human, per-client identifier**, which v4 nullifiers no longer give. Fresh auth works via RFC 9470 step-up. V(sandbox docs page)
- The client is registered via `/portal` or the MCP `https://sandbox.auth.world.org/mcp` (plugin `worldcoin/world-id-agent-plugin`). The callback must be HTTPS; localhost is rejected. V(plugin README)
- AgentKit (`@worldcoin/agentkit`, x402 plus AgentBook registry on World Chain) and human-in-the-loop are separate docs products. V(`developer-docs/agents/*`)

### 1.16 Prize criteria ("Best Use of IDKit", $5k, up to 2 × $2.5k)

The criteria (V, prize page text in scratchpad):

- Use IDKit in a working app, mini app or onchain flow.
- Verify on the server or onchain.
- Explain the trust moment and why the credential is the *minimum sufficient* one.
- Demo one success and one alternative path (cancel, unavailable credential, rejection, ineligible user).
- Include a debrief: time to first success, friction, missing capability, the one improvement that would matter most.

---

## 2. Unverified / conflicting

1. **Portal replay handling.**
   - The spike README says the Portal returns 200 with "nullifier reuse" for a reused nullifier. The log has no such case, and the openapi doesn't say.
   - Also untested: whether the Portal rejects a reused `nonce`, and whether it checks that `nonce` came from our signer. Treat the Portal as a stateless validity check and enforce everything ourselves.
2. **Does the simulator (`environment:"staging"`) still issue v4 proofs?** And does the staging `WorldIDVerifier` (`0x703a…`) accept them onchain? Both are untested. This decides whether an onchain demo is possible without two Orb-verified humans.
3. **Sandbox** is documented around Selfie Check. Whether it simulates PoH (schema 1) is U.
4. **How many team members are Orb-verified.** The spike produced real PoH proofs, so at least one person is. A distinct-human demo needs **two**.
5. **Base satellite freshness.** We saw about 57 min of lag. A proof made against the newest World Chain root may not verify on Base until that root is relayed, and after that only for 3600 s. Cadence and reliability are unknown. Don't use it for the demo.
6. **Sessions with `proofOfHuman`.** The docs show sessions only with `selfieCheck`. PoH-session support and the UX ("a reusable identifier that can link interactions" warning) are untested.
7. **`allow_legacy_proofs: true`** may return a v3 proof, which has a different onchain verifier (Router, uint256[8]). For onchain, set it to `false`. What users without a v4 credential then see is untested.
8. **World ID app vs World Money split.** Which app IDKit deep links open (the World ID app, per the docs wording) and where mini apps run (World Money) come from news, not from dev docs.
9. **Whether World Money wallets are Safe smart accounts** that a mini app could add a module or guard to. It's likely blocked (`disallowed_operation`), but untested. The docs only say transactions are 4337 user ops.
10. **Rate limits** on `/api/v4/verify` and the bridge are undocumented. The only 429 in the docs is the PoH issuer refresh endpoint. `max_verifications` applies only to Portal-created (incognito) actions; dynamic actions have no Portal-side counter.
11. **iOS audio after the World ID app switch.** Still untested. The design already puts the human step before the audio run.

---

## 3. Implications for SAFE (Safe that executes only when owners are together)

**What World ID gives:** each signer at the meeting is a distinct PoH human, bound to *this* Safe transaction.

**What it can't give with v4 uniqueness proofs:** "this is the *same* human who enrolled as owner". Nullifiers are one-time, so an enrollment nullifier can't be matched later. The options:

- **(a) Owners are keys, humans are per-execution.** The Safe owners stay ECDSA keys (the phones' wallets or passkeys). At execution, the module or guard requires k PoH proofs:
  - action = `"safe:" + chainId + ":" + safe + ":" + safeNonce`, which is unique per tx, so each human proves once per tx.
  - signal = `abi.encodePacked(safeTxHash, signerAddress)`.
  - The contract checks the nullifiers are pairwise distinct. This proves "k distinct humans approved", not "the enrolled humans".
  - Pair it with the PoP attestation (the pair_tag computed from those nullifiers). **Simplest, and fully onchain-verifiable.**
- **(b) Session proofs.** Enroll each owner with `createSession`, store `sessionId` in the module, and at execution require `verifySession` with that sessionId. This gives "same World ID as enrolled".
  - But one human can create sessions twice and enroll as two owners. Uniqueness at enrollment needs `verifyWithSession`, which is not deployed.
  - It's also untested with PoH.
- **(c) The OIDC pairwise `sub`** (World ID for Agents) as a stable owner id. It works offchain only, since it's a JWT. That's server trust, so it's poor for a Safe.

Chain and timing constraints:

- Deploy on **World Chain mainnet (480)**. It is the only chain with a production-grade v4 verifier. There is no v4 testnet, and gas is cheap: about 420k per proof, so about 0.85M for two owners.
- The whole "meet → PoP verdict → World ID proofs → execTransaction" flow must land within about 1 h (root validity) and 5 h (expiry). Proofs can't be collected now and executed next week. The UX has to be "execute at the meeting".
- The PoP verdict itself is **not onchain-verifiable**: popprover is Spartan over T-256, not EVM. So the PoP part of the guard is either:
  - a server (issuer) signature over `(safeTxHash, pair_tag, verdict, time)`, checked with P-256. The RIP-7212 precompile at `0x…0100` is live on World Chain 480 and 4801: V(`cast call` with a fresh valid P-256 vector returned `1`), or
  - a secp256k1 attester key.
  This is a trust assumption to state plainly.
- Safe 1.4.1 and the factory are on World Chain. The module or guard is ours.
- World App / World Money wallets are probably not Safes we can install modules into, so plan a **separate Safe**, deployed by us, with the owners' own keys.
- The phones already hold hardware keys (Keystore / Secure Enclave, P-256). Owners could be P-256 signers via Safe passkey or WebAuthn modules (U, for another agent).
- Prize story: "unlock shared funds only when k distinct humans are physically together". PoH is minimal because the attack is one person pretending to be several owners. The alternative path to demo: the same human on both phones gives equal nullifiers, and execution reverts.

## 4. Implications for POOL (private transfer that needs PoP between payer and payee)

- The same per-session pattern:
  - action = `"pop:" + sid` (sid random, reveals nothing).
  - signal binds the role plus a commitment to the transfer, for example `abi.encodePacked(session_nonce, role, noteCommitmentOrTransferHash)`.
  - Two PoH proofs with distinct nullifiers give `pair_tag`.
- **Privacy.**
  - A World ID nullifier is unlinkable across actions and never reveals the human. Putting the two proofs in pool calldata leaks only "a PoP-gated transfer happened at time T", plus whatever the action and signal encode. So the action must be random (sid) and the signal must be a hiding commitment.
  - A relayer is needed so that `msg.sender` doesn't link payer addresses (MiniKit sendTransaction would expose the World App wallet).
- **No recursion.**
  - Verifying a World ID Groth16 proof inside the pool's circuit (BN254 in BN254) costs millions of constraints. Composition has to happen at the contract: `verify()` both World ID proofs in the same tx as the shielded transfer, and bind them through the signal to a public input of the pool proof (for example the transfer's public `extDataHash` or a nullifier).
- **Timing.** The transfer must land within about 1 h of the World ID proofs (root window), so it must be "pay at the meeting". That fits the story.
- **Chain.** Again World Chain 480 mainnet only (v4). Railgun or Privacy Pools deployments on World Chain need checking by another agent (U). A testnet demo would force a fall back to v3 routers plus simulator proofs (U whether that still works), or to server-side Portal verification with an onchain attester.
- **Uniqueness semantics.** Distinct nullifiers prove payer ≠ payee human. They don't stop a colluding real second human (a remote World ID lender); the adapters doc already records this limit.

## 5. Implications for our server (either idea)

- Reuse `worldid-spike/backend/app/signing.py` (parity-tested) for `rp_context`. Keep a separate rp_context per phone, because each gets a fresh nonce.
- Pin these in `/verify`:
  - `environment == "production"`
  - `action == "pop:" + sid`
  - `nonce ∈ issued_nonces[sid][role]`
  - `issuer_schema_id == 1`
  - `signal_hash == hash_to_field(signal_bytes)`
  - `UNIQUE(nullifier, action)`
  - `nullifier_A != nullifier_B`
- Keep the raw IDKit result, so the same proofs can be resubmitted to the World Chain verifier by a contract within the time window.
- For the contract call:
  - `rpId = int(rp_id[3:], 16)`
  - `action = int(keccak(utf8(action)), 16) >> 8`
  - `proof = [int(x) for x in responses[0].proof]`
  - `credentialGenesisIssuedAtMin = 0`
  - `issuerSchemaId = 1` (pinned in the contract)

## 6. Open questions (ordered by how much they block)

1. How many Orb-verified humans are on the team at the venue? (Two are needed for a real distinct-human demo.)
2. Does the simulator or sandbox issue v4 PoH proofs that the **staging** World Chain verifier `0x703a…` accepts? This needs a 10-minute test: IDKit JS with `environment:"staging"`, then `cast call` the staging verifier.
3. Does v4 `/verify` reject a replayed nonce or nullifier? We need one real replay test with the second spike proof.
4. SAFE only: accept "k distinct humans per tx" (option a), or do we need "the enrolled humans" (sessions, with PoH support untested and no onchain uniqueness binding)?
5. How does the PoP verdict get onchain? Server P-256 attestation (the RIP-7212 precompile is live on World Chain, V) or a secp256k1 attester. What does the contract trust?
6. Is World Chain mainnet acceptable for the demo? That means real ETH for deploys, and no testnet for v4.
7. Target the Agents prize too (OIDC device-flow login as the "human approval" step of an agent-proposed Safe tx)? It needs a separate client registration at `sandbox.auth.world.org`.
8. Does iOS keep the app alive across the IDKit hop and resume via `return_to` (custom scheme)?

---

## Appendix: reproduce the onchain replay

```sh
WC=https://worldchain-mainnet.g.alchemy.com/public; V=0x00000000009E00F9FE82CfeeBB4556686da094d7
ACTF=$(python3 -c "print(int('$(cast keccak spike-1790264612780)',16)>>8)")
P='[24643224222707417029235725305950213670563643092921051588895189505834811955013,14761244667611688071578738893930367803737017631766736836509722972277099603488,18686117517150256267261864360170007600795782682159741038080100617914270529257,36800890520520620314742234858180444131156994310855377760873443653148406885981,4811351604658854053044351946818995910976871300870904331801469560226850856258]'
cast call $V "verify(uint256,uint256,uint64,uint256,uint256,uint64,uint64,uint256,uint256[5])" \
  0x162aa2ced980fe203e8f444fd161cbfecb8079444c811f49c1e36d91b42e8a53 $ACTF 1470746745086940220 \
  0x00cdad407e31b93f4101ea84c3a382039f587d5ffbae86bb766a6ac1ce7c0343 \
  0x0022ec8cb931f2fe813df7a9380c0ead38cf6d798b02260c0f9c08f3fb50b989 1790264612 1 0 "$P" \
  --rpc-url $WC --block 35464531          # → 0x (pass); at latest → 0x9dd854d3 InvalidMerkleRoot
```

## Sources

- https://docs.world.org/world-id/idkit/integrate · /credentials · /session-proofs · /signatures · /onchain-verification · /verification-flows · /error-codes · /mini-apps
- https://docs.world.org/world-id/sandbox/what-is-sandbox · /sandbox-access
- https://docs.world.org/world-id/reference/contracts (v3, deprecated)
- https://docs.world.org/mini-apps/commands/send-transaction · /mini-apps/more/faq
- https://docs.world.org/agents/human-in-the-loop/integrate · /agents/agent-kit/integrate
- https://github.com/worldcoin/developer-docs (openapi/developer-portal.json)
- https://github.com/worldcoin/world-id-protocol (contracts/src/core/*, contracts/deployments/*, docs/world-id-4-specs/README.md, docs/WIPs/wip-101.md, crates/primitives/src/{lib,rp}.rs)
- https://github.com/worldcoin/idkit (rust/core/src/{crypto,rp_signature}.rs, kotlin/gradle.properties)
- https://github.com/worldcoin/world-id-agent-plugin
- https://sandbox.auth.world.org/docs · https://sandbox.auth.world.org/.well-known/openid-configuration
- https://ethglobal.com/events/tokyo2026/prizes (copy in scratchpad `wid/tokyo_prizes.txt`)
- https://criptocurrencies.com/2026/09/19/world-money-super-app-launch/ · https://www.kucoin.com/news/flash/world-launches-self-custody-super-app-world-money-in-150-countries
- Onchain: World Chain 480 via `https://worldchain-mainnet.g.alchemy.com/public`, Base via `https://mainnet.base.org`, WC Sepolia via `https://worldchain-sepolia.g.alchemy.com/public` (cast 1.4.3, 2026-09-26)
- Local: `~/dev/worldid-spike/backend/logs/backend.log`, `~/dev/worldid-spike/docs/idkit-research-brief.md`
