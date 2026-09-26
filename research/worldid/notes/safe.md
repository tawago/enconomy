# Safe + proof of presence: research note

Date: 2026-09-26. Scope: how to make a Safe execute only when its owners were physically together, where Safe runs (World Chain 480 / 4801, Ethereum Sepolia), and what tooling a native app can use. Also what carries over to the POOL idea.

Tags: **V(...)** = verified, with the source or command. **U** = unverified.

Prototype (fork tests, all passing) lives in the scratchpad, which is temporary:
`/private/tmp/claude-501/-Users-takahiro-ogawa-dev-enconomy/3d9dd236-bf59-4c81-91f5-6bb7c5ebc6e3/scratchpad/popguard/` (`src/PopGuard.sol`, `src/P256Owner.sol`, `src/DenyModuleGuard.sol`, `test/*.t.sol`). The code that matters is copied into §6 below, so this note stands on its own.

---

## 0. TL;DR

- **Recommended SAFE design:** use a Safe **transaction guard** (`setGuard`). It checks a **server-issued presence attestation**, a P-256 signature over `(chainId, safe, safeTxHash, pair_tag, expiry)`. The attestation is **appended to the `signatures` bytes** of `execTransaction`, so no extra transaction is needed. The guard recomputes `safeTxHash` itself, using `nonce() - 1`. Verification uses the P-256 precompile at `0x…0100`, which is live on 480, 4801 and Sepolia. Prototyped and passing on a World Chain Sepolia fork, against the real deployed Safe 1.4.1 and 1.5.0 singletons. The whole transaction costs about 74–84k gas.
- **Optional:** make the phones' hardware P-256 keys (Keystore / Secure Enclave, the same keys PoP enrolls) the Safe **owners**, through a tiny EIP-1271 contract per phone. Then the device that proved presence is also the device that signs. Prototyped: a 2-of-2 with P-256 owners costs about 84k gas (1.5.0) or 97k (1.4.1).
- **Hard gotchas:**
  - Modules bypass the transaction guard. That includes the 4337 module, which every World App wallet has.
  - A guard can brick the Safe, because removing the guard itself goes through the guard.
  - `checkTransaction` does not receive `safeTxHash`.
  - `delegatecall` can overwrite the guard slot.
  - The Safe{Wallet} UI cannot append our attestation.
- **Chain choice:**
  - **World Chain mainnet 480** has everything: Safe 1.4.1 + 1.5.0, the hosted Transaction Service (`wc`), the Safe{Wallet} UI, the World ID v4 verifier, and P-256.
  - **World Chain Sepolia 4801** has the Safe 1.4.1 contracts and P-256, but **no Transaction Service, no Safe{Wallet} UI, no SafeL2 1.5.0 and no World ID v4 verifier**.
  - **Ethereum Sepolia** has the Safe contracts, the Transaction Service and the UI, but no World ID v4.
- **Trust:** onchain enforcement is only as strong as the PoP server's attestation key. The option A proofs (Spartan/popprover) are not EVM-verifiable. The chain trusts the server, the same way it trusts a price oracle. Say so in the pitch.

---

## 1. Verified facts

### 1.1 Safe contract versions and extension points

| Fact | Source |
|---|---|
| Latest release tag is `v1.5.0` (tag commit 2025-07-03). `main` has moved past it (53 files changed in `contracts/`), but `VERSION` on main is still `"1.5.0"`. | V(`git clone safe-global/safe-smart-account`; `git tag`; `git show v1.5.0`) |
| `execTransaction` order (1.4.1 and 1.5.0): `onBeforeExecTransaction` → compute `txHash` with **`nonce++`** → `checkSignatures` → **`guard.checkTransaction(to,value,data,operation,safeTxGas,baseGas,gasPrice,gasToken,refundReceiver,signatures,msg.sender)`** → execute → `guard.checkAfterExecution(txHash, success)`. | V(`contracts/Safe.sol` @v1.5.0 L127–204) |
| The guard gets **no `safeTxHash` in `checkTransaction`**, only in `checkAfterExecution`. The nonce is already incremented, so the guard must call `getTransactionHash(..., nonce()-1)`. | V(Safe.sol; prototype `test_v141_*`, `test_v150_*` pass using `nonce()-1`) |
| Transaction guard interface id `0xe6d7a83a`. `setGuard` checks `supportsInterface` (error `GS300`). Guard slot `0x4a204f620c8c5ccdca3fd54d003badd85ba500436a431f0cbda4f558c93c34c8`. No public `getGuard`; read the slot with `getStorageAt` or `eth_getStorageAt`. | V(`base/GuardManager.sol` @v1.4.1 and @v1.5.0) |
| **1.4.1: `execTransactionFromModule` calls no guard at all.** | V(`base/ModuleManager.sol` @v1.4.1; prototype: an enabled module drained ETH past PopGuard on both 1.4.1 and 1.5.0) |
| **1.5.0 adds a module guard:** `setModuleGuard(address)`, interface `IModuleGuard` id `0x58401ed8`, `checkModuleTransaction(to,value,data,operation,module) returns (bytes32)` and `checkAfterModuleExecution(bytes32,bool)`. Slot `0xb104e0b93118902c651344349b610029d694cfdec91c589c91ebafbcd0289947`. The transaction guard is still **not** called for module transactions. | V(ModuleManager.sol @v1.5.0 L11–45, L94–121, L258; prototype `test_v150_moduleGuard_blocks_module` passes) |
| Contract (EIP-1271) owner signatures: 1.5.0 calls `isValidSignature(bytes32 safeTxHash, bytes)` and expects `0x1626ba7e`. 1.4.1 calls the **legacy** `isValidSignature(bytes data, bytes)`, where `data` is the EIP-712 preimage `0x1901‖domainSeparator‖structHash`, and expects `0x20c13b0b`. An owner contract must implement both. | V(Safe.sol @v1.4.1 L315; @v1.5.0 `checkContractSignature`; `ISignatureValidator.sol`) |
| Signature encoding: `threshold × 65` static bytes, owners strictly ascending. Kinds by `v`: `v=0` contract signature (`r`=owner, `s`=offset to `len‖sig` in the dynamic part), `v=1` approved hash, `v>30` eth_sign, else ECDSA. **Bytes after what Safe reads are ignored**, so extra data can be appended. | V(`checkNSignatures` @v1.5.0; prototype appends 108 bytes and Safe accepts) |
| `SAFE_TX_TYPEHASH = 0xbb8310d486368db6bd6f849402fdd73ad53d316b5a4b2644ad6efe0f941286d8`, `DOMAIN_SEPARATOR_TYPEHASH = 0x47e79534a245952e8b16893a336b85a3d9ea9fa8c573f3d803afb92a79469218` (domain = `{chainId, verifyingContract}`). | V(Safe.sol @v1.5.0 L57, L62, L398) |
| 1.5.0 adds an overloaded `checkNSignatures(address executor, bytes32, bytes, uint256)`, so a module or guard can check owner signatures, including pre-approved hashes. | V(CHANGELOG v1.5.0) |
| Example guards shipped with 1.5.0: `OnlyOwnersGuard`, `DelegateCallTransactionGuard`, `ReentrancyTransactionGuard`, `DebugTransactionGuard`. `OnlyOwnersGuard` deliberately **doesn't revert in `fallback()`**, "to avoid issues in case of a Safe upgrade… the Safe would be locked". | V(`contracts/examples/guards/*` @v1.5.0) |
| Safe docs: "Since a Safe Guard has full power to block Safe transaction execution, a broken Guard can cause a denial of service for a Safe." | V(https://docs.safe.global/advanced/smart-account-guards) |
| A guard that reverts blocks `setGuard(address(0))` too: the Safe cannot remove it. | V(prototype `test_brick_guard_cannot_be_removed`) |
| 1.5.0 removed `transfer`/`send` in favour of `call`, which opens possible reentrancy for extensions. | V(CHANGELOG v1.5.0) |

### 1.2 Deployments (the singleton factory produces the same address on every chain)

All from `safe-global/safe-deployments` (commit `7b1fb6d`, 2026-09-08). Bytecode and `VERSION()` checked with `cast` against the public RPCs: 480 `https://worldchain-mainnet.g.alchemy.com/public`, 4801 `https://worldchain-sepolia.g.alchemy.com/public`, Sepolia `https://ethereum-sepolia-rpc.publicnode.com`.

| Contract | Address | 480 | 4801 | Sepolia |
|---|---|---|---|---|
| Safe 1.4.1 | `0x41675C099F32341bf84BFc5382aF534df5C7461a` | ✔ "1.4.1" | ✔ | ✔ |
| SafeL2 1.4.1 | `0x29fcB43b46531BcA003ddC8FCB67FFE91900C762` | ✔ "1.4.1" | ✔ | ✔ |
| SafeProxyFactory 1.4.1 | `0x4e1DCf7AD4e460CfD30791CCC4F9c8a4f820ec67` | ✔ | ✔ | ✔ |
| CompatibilityFallbackHandler 1.4.1 | `0xfd0732Dc9E303f09fCEf3a7388Ad10A83459Ec99` | ✔ | ✔ | ✔ |
| MultiSend 1.4.1 | `0x38869bf66a61cF6bDB996A6aE40D5853Fd43B526` | ✔ | ✔ | ✔ |
| MultiSendCallOnly 1.4.1 | `0x9641d764fc13c8B624c04430C7356C1C7C8102e2` | ✔ | ✔ | ✔ |
| SafeToL2Setup 1.4.1 | `0xBD89A1CE4DDe368FFAB0eC35506eEcE0b1fFdc54` | listed | listed | listed |
| Safe 1.5.0 | `0xFf51A5898e281Db6DfC7855790607438dF2ca44b` | ✔ "1.5.0" | ✔ "1.5.0" (not in safe-deployments for 4801) | ✔ |
| SafeL2 1.5.0 | `0xEdd160fEBBD92E350D4D398fb636302fccd67C7e` | ✔ "1.5.0" | **✘ no code** | ✔ |
| SafeProxyFactory 1.5.0 | `0x14F2982D601c9458F93bd70B218933A6f8165e7b` | ✔ | ✔ | ✔ |
| CompatibilityFallbackHandler 1.5.0 | `0x3EfCBb83A4A7AfcB4F68D501E2c2203a38be77f4` | ✔ | **✘** | ✔ |
| MultiSendCallOnly 1.5.0 | `0xA83c336B20401Af773B6219BA5027174338D1836` | ✔ | ✔ | ✔ |
| MultiSend 1.5.0 | `0x218543288004CD07832472D464648173c77D7eB7` | listed | U | listed |
| Safe Singleton Factory | `0x914d7Fec6aaC8cd542e72Bca78B30650d45643d7` | ✔ | ✔ | ✔ |
| CREATE2 deployer (Arachnid) | `0x4e59b44847b379578588920cA78FbF26c0B4956C` | ✔ | ✔ | ✔ |
| Safe4337Module v0.3.0 (EntryPoint v0.7) | `0x75cf11467937ce3F2f357CE24ffc3DBF8fD5c226` | ✔ | ✔ | ✔ |
| SafeModuleSetup v0.3.0 | `0x2dd68b007B46fBe91B9A7c3EDa5A7a1063cB5b47` | ✔ | ✔ | listed |
| EntryPoint v0.7 | `0x0000000071727De22E5E9d8BAf0edAc6f37da032` | ✔ | ✔ | U |
| SafeWebAuthnSharedSigner (passkey 0.2.1) | `0x94a4F6affBd8975951142c3999aEAB7ecee555c2` | ✔ code | ✔ code | listed |
| DaimoP256Verifier | `0xc2b78104907F722DABAc4C69f826a522B2754De4` | ✔ | ✔ | listed |
| SafeWebAuthnSignerFactory 0.2.1 | `0x1d31F259eE307358a26dFb23EB365939E8641195` | ✘ | ✘ | listed |
| Safe7579 adapter | `0x7579EE8307284F293B1927136486880611F20002` | ✔ code | ✔ code | ✔ code |
| Safe7579 launchpad | `0x7579011aB74c46090561ea277Ba79D510c6C00ff` | ✔ code | ✔ code | ✔ code |
| Rhinestone module registry | `0x000000000069E2a187AEFFb852bF3cCdC95151B2` | ✔ | ✔ | ✔ |
| Zodiac ModuleProxyFactory | `0x000000000000aDdB49795b0f9bA5BC298cDda236` | ✔ | **✘** | ✔ |
| Zodiac Delay mastercopy | `0xd54895B1121A2eE3f37b502F507631FA1331BED6` | ✔ | **✘** | ✔ |
| Zodiac Roles v2 mastercopy | `0x9646fDAD06d3e24444381f44362a3B0eB343D337` | ✔ | **✘** | ✔ |
| Multicall3 / CreateX / Permit2 | `0xcA11…CA11` / `0xba5E…a5Ed` / `0x0000…8BA3` | ✔ | ✔ | ✔ |

"listed" means it's in the deployments JSON, but I didn't `cast` it. The module addresses come from `@safe-global/safe-modules-deployments@3.0.10`. The Safe7579, registry and Zodiac addresses: code presence is V(cast), but which contract sits at each address is from docs and memory, except the registry, which is V(`@rhinestone/module-sdk@0.4.0` `REGISTRY_ADDRESS`).

### 1.3 P-256 precompile (important for both ideas)

- `0x0000000000000000000000000000000000000100` returned `1` for a fresh valid P-256 vector on **480, 4801 and Sepolia**. For a corrupted input it returned empty output (so the check must be `ret.length == 32 && ret == 1`). V(`cast call`, vector made with `cryptography` in `server/.venv`)
- In a forge fork, the call cost about 7.6k gas as measured (`evm_version = "osaka"`). V(prototype `test_p256_precompile_fork`). U: exact gas on the live chains. RIP-7212 says 3450; EIP-7951 (Osaka) says 6900.
- Input: `abi.encode(bytes32 digest, r, s, qx, qy)`. The **digest is the SHA-256 the phone computed**. Android `SHA256withECDSA` over message M signs `sha256(M)`, so onchain we pass `sha256(M)`. Low-s is not enforced.

### 1.4 Safe off-chain infrastructure

| Fact | Source |
|---|---|
| The hosted Transaction Service **supports World Chain**: `https://api.safe.global/tx-service/wc`, version 6.11.0, indexing chain 480. | V(`curl …/tx-service/wc/api/v1/about/` → 200; `/about/ethereum-rpc/` → chain_id 480) |
| **No hosted tx service for World Chain Sepolia 4801.** Safe's config service returns `"No Chain matches the given query."` for 4801. `api-kit` has no 4801 entry. (`wch-sepolia` is **Whitechain** Sepolia, chain 1874. Don't confuse the two.) | V(`curl https://safe-config.safe.global/api/v1/chains/4801/`; api-kit 5.0.3 bundle; `…/tx-service/wch-sepolia/api/v1/about/ethereum-rpc/` → chain 1874) |
| Safe{Wallet} UI config for 480: shortName `wc`, `recommendedMasterCopyVersion` `1.5.0`, features include `EIP1271`, `SAFE_APPS`, `COUNTERFACTUAL`, `NESTED_SAFES`, `PROPOSERS`, `TX_SIMULATION`. **No `ZODIAC_ROLES`, `RECOVERY` or `SPENDING_LIMIT` on 480**, while Sepolia (`sep`) has them. | V(`curl https://safe-config.safe.global/api/v1/chains/{480,11155111}/`) |
| `api.safe.global` needs an API key for real use: `Authorization: Bearer <key>`. Keyless use is "exploration only", limited to 2 RPS and 5,000 requests a month. `api-kit` 5.x **throws unless `apiKey` is given** when it targets api.safe.global. | V(https://docs.safe.global/core-api/how-to-use-api-keys; api-kit 5.0.3 `SafeApiKit` constructor) |
| Propose endpoint: `POST {base}/api/v2/safes/{safe}/multisig-transactions/`, body `{...safeTxData, contractTransactionHash, sender, signature, origin}`. Confirmations: `{base}/api/v1/multisig-transactions/{safeTxHash}/confirmations/`. | V(api-kit 5.0.3 bundle) |
| npm (2026-09-26): `@safe-global/protocol-kit` 8.0.7, `api-kit` 5.0.3, `relay-kit` 6.1.1, `types-kit` 4.0.1, `safe-deployments` 1.37.63, `safe-modules-deployments` 3.0.10, `@rhinestone/module-sdk` 0.4.0, `@gnosis-guild/zodiac` 5.0.1, `permissionless` 0.4.1. | V(`npm view`) |
| Safe modules repo moved to the `safe-fndn` GitHub org. | V(search result URLs `github.com/safe-fndn/safe-modules`) |

### 1.5 World App wallets are Safes

- Sampled five `UserOperationEvent` senders from the last 20 blocks on 480. Every one is a **SafeL2 1.4.1** proxy (slot0 = `0x29fc…C762`): **1 EOA owner, threshold 1, one module = Safe4337Module v0.3.0 `0x75cf…c226`, fallback handler = the same module, guard slot empty.** V(`cast logs` on EntryPoint v0.7 + `getOwners/getThreshold/getModulesPaginated/storage`). U: that these senders are World App users specifically. It is very likely: the World docs list the same 1.4.1 + 4337 module under "Gnosis Safe 1.4.1" / "Gnosis Modules" (https://docs.world.org/world-chain/reference/useful-contracts.md).
- MiniKit `signTypedData` returns `{signature, address, version}`. Error codes include `invalid_contract` ("contract or domain is invalid") and `disallowed_operation`. V(https://docs.world.org/mini-apps/commands/sign-typed-data.md)
- MiniKit `sendTransaction` runs as a 4337 userOp on 480 and returns a `userOpHash`. **Contracts must be allowlisted in the Developer Portal.** Non-allowlisted contracts are refused with `invalid_contract`. V(https://docs.world.org/mini-apps/commands/send-transaction)
- The Mini App contract rules for custody contracts: immutable, or upgradeable only with TFH holding 1 of 2 upgrade keys; no admin withdrawal of user funds; ≥90% test coverage for custody logic; no hardcoded privileged addresses. V(https://docs.world.org/mini-apps/guidelines/smart-contract-development-guidelines.md)

### 1.6 World ID onchain (only what matters for the Safe design; see `worldid.md` for the full picture)

- v4 `WorldIDVerifier.verify(nullifier, action, rpId, nonce, signalHash, expiresAtMin, issuerSchemaId, credentialGenesisIssuedAtMin, uint256[5] proof)` is deployed on **480 only**: prod `0x00000000009E00F9FE82CfeeBB4556686da094d7`, staging `0x703a6316c975DEabF30b637c155edD53e24657DB`. Code on 480 ✔, **4801 ✘**. V(docs onchain-verification.md; `cast codesize`)
- v3 `WorldIDRouter.verifyProof` (Orb only, `groupId = 1`): 480 `0x17B354dD2595411ff79041f930e491A4Df39A278`, 4801 `0x57f928158C3EE7CDad1e4D8642503c4D0201f611`. Code ✔ on both. V(docs; cast)

### 1.7 Prototype results (forge 1.4.3, solc 0.8.28 via-IR, fork of 4801 at the real Safe singletons)

| Test | Result |
|---|---|
| 2-of-2 SafeL2 1.4.1 + PopGuard: tx without attestation reverts `NoAttestation`; expired reverts `Expired`; valid attestation executes | PASS, whole tx ≈ 84.0k gas |
| Same on Safe 1.5.0 (L1 singleton) | PASS, ≈ 73.2k gas |
| Enabled module calls `execTransactionFromModule` with PopGuard set | **Module drains funds on 1.4.1 and 1.5.0** (the tx guard is bypassed) |
| 1.5.0 + module guard that reverts | the module call is blocked. PASS |
| Guard that always reverts, then try `setGuard(0)` | reverts, so the Safe is bricked. PASS (the brick is confirmed) |
| 2-of-2 whose owners are `P256Owner` EIP-1271 contracts (phone-style `sha256(safeTxHash)` P-256 signatures) | PASS: 1.5.0 ≈ 84.2k, 1.4.1 ≈ 97.0k gas |

---

## 2. Unverified / conflicting

- **Safe4337Module v0.3.0 with Safe 1.5.0:** the docs say "1.4.1 or newer". I didn't test it. U.
- **SafeL2 1.5.0 on 4801:** missing. It could be deployed permissionlessly through the Safe Singleton Factory with the exact v1.5.0 build (solc 0.7.6, optimizer off, salt 0). U. Easier: use SafeL2 1.4.1 or the Safe 1.5.0 L1 singleton on 4801. L2 events matter only to indexers, and 4801 has no Safe indexer anyway.
- **Safe{Wallet} UI with a custom guard:** it will show the guard and let owners sign, but when it executes it won't append our attestation, so execution reverts. Probably it also shows a "unknown guard" warning. U (not tried in the UI).
- **Transaction Service and appended bytes:** the service stores per-owner confirmations. The final `signatures` blob is assembled by whoever executes, so the tail never touches the service. U whether the service's pre-validation or simulation (`TX_SIMULATION`) flags the transaction as failing without the tail. Very likely it does.
- **Can MiniKit `signTypedData` sign a `SafeTx` for a *different* Safe?** That would let a World App wallet be an owner of our PoP Safe. It may be refused (`invalid_contract` / `disallowed_operation`). What the returned signature is (the owner EOA's ECDSA, or a Safe-wrapped 1271 blob) is also U. Needs a live test inside World App.
- **Safe7579 addresses:** code is present at `0x7579EE83…0002` and `0x7579011a…00ff`, but I didn't confirm they are the current audited release. A search result called `0x7579EE…` the "safe4337ModuleAddress" in 7579 setups, which fits (adapter = module + fallback handler). U.
- **Precompile gas:** 7.6k measured in a forge fork with osaka rules; the live chain cost may differ. U.
- **World Chain PBH (Priority Blockspace for Humans):** uses a `PBH4337Module` / `PBHEntryPoint` for Safe 4337 userOps with World ID proofs. It's live on mainnet (https://world.org/blog/announcements/priority-blockspace-launches-for-13-million-humans-on-world-chain-mainnet). I didn't look up addresses. Possible bonus story ("human-prioritized Safe execution"), not needed. U.

---

## 3. Design space for "execute only if owners were together"

| # | Mechanism | How PoP is checked | Pros | Cons |
|---|---|---|---|---|
| A | **Tx guard + attestation appended to `signatures`** (prototyped) | `checkTransaction` recomputes `safeTxHash`, parses a 108-byte tail, checks expiry, then P-256 verifies the issuer signature | One transaction. Owners use any signer. The attestation is bound to the exact tx (hash includes nonce) → no replay. Works on 1.4.1 and 1.5.0. | Safe{Wallet} UI can't execute. Module bypass (§4.2). Brick risk (§4.1). |
| B | **Tx guard + onchain attestation store** | Anyone calls `PopRegistry.attest(safe, safeTxHash, pairTag, expiry, sig)` first; the guard checks `attested[safe][h] >= now` | Execution works from the Safe{Wallet} UI or the tx service unchanged. | Two transactions. The same caveats as A otherwise. |
| C | **Presence as a required co-signer**: owners = {A, B, P}, threshold 3; `P` is an EIP-1271 contract that accepts the issuer attestation as its "signature" | Safe's own `checkNSignatures` calls `P.isValidSignature` | No guard, so no guard bricking. The UI supports EIP-1271 owners (`EIP1271` feature). Composes with any threshold: n humans + P. | Removing P also needs P, so the same liveness dependency on the issuer. Needs threshold = n+1, so it's clumsy for "2 of 3 humans + presence": the threshold can't force P to be one of the signers. |
| D | **Module executor**: Safe threshold set so owners never execute directly; `PopModule.exec(tx, ownerSigs, attestation, worldIdProofs)` verifies everything, then `execTransactionFromModule` | module code | Can verify World ID v4 proofs onchain at execution time (480 only). The cleanest place for per-tx human checks. | Direct `execTransaction` must be blocked by a guard or an unreachable threshold, or the module is decorative. Module guard only on 1.5.0. More code. |
| E | **ERC-7579 via Safe7579**: a PoP *validator* or *hook* module | validator for 4337 userOps / hook around execution | Fits the AA / bundler flow; the registry is present on 480 and 4801. | Hooks apply only to executions routed through the adapter; plain `execTransaction` bypasses them unless a guard is also set. More moving parts and SDKs. Not worth it in a hackathon. |
| F | **Zodiac Delay / Roles** | not a PoP check by itself; Delay could serve as the **escape hatch** (§4.1) | Audited, and the UI knows it | Missing on 4801 (✘ in §1.2). The 480 UI has no `ZODIAC_ROLES` feature flag. |

**Pick for the hackathon: A, plus the escape hatch and module rules in §4. Fall back to B if the demo must execute from the Safe{Wallet} UI.** D is the "full World ID onchain" upgrade on 480.

"Recently together" vs "together for this tx": A and B bind presence to **one `safeTxHash`**. That is stronger and simpler: the PoP session is run *for* that transaction. A "recent window" design (`lastMet[pair] > now - 10min`, any tx) needs a device↔owner binding and invites "meet once, drain later". Avoid it, unless a spending cap goes with it.

---

## 4. Gotchas (each with its mitigation)

### 4.1 Guard bricks the Safe
Removing the guard (`setGuard(0)`) is itself a Safe transaction, so it goes through `checkTransaction`. V(prototype). If the PoP server dies, its key is lost, or the phones are lost, the funds are stuck.
- Mitigation in the guard: an **escape hatch**. Allow, without an attestation, a transaction whose `to == safe`, `operation == CALL`, and `data == setGuard(address(0))`, but only if it was **announced** at least `T` ago (`announceEscape(safeTxHash)`, callable only by the Safe or any owner; the guard records the time). Demo value: `T = 1 day`; production: 7 days.
- Or the owners can put Zodiac Delay on 480 as an alternative path. That is more setup.
- Also: never make `fallback()` revert (Safe's own `OnlyOwnersGuard` pattern). Keep `checkAfterExecution` a no-op.

### 4.2 Modules bypass the transaction guard
- 1.4.1: no module guard exists. Rule: **a PoP Safe on 1.4.1 has zero modules.** The guard should revert `enableModule` / `setFallbackHandler` to anything outside an allowlist; `to == safe` plus the selector check works for this.
- 1.5.0: also call `setModuleGuard(popModuleGuard)`. It can deny everything, or require an attestation stored onchain (variant B), since `checkModuleTransaction` gets no signatures.
- **Do not enable the 4337 module on the PoP Safe.** Its `executeUserOp` path is `execTransactionFromModule`, so it would skip PoP. For gasless execution, use a relayer EOA that calls `execTransaction` with `gasPrice = 0` (anyone may submit; the owner signatures and the attestation are what count).

### 4.3 The guard has no `safeTxHash`
Recompute it: `ISafe(msg.sender).getTransactionHash(to, value, data, operation, safeTxGas, baseGas, gasPrice, gasToken, refundReceiver, ISafe(msg.sender).nonce() - 1)`. V(prototype). `msg.sender` is the Safe, so a guard can serve many Safes.

### 4.4 delegatecall
`operation == 1` runs foreign code in the Safe's storage, so it can `sstore` over the guard slot, the module list or the owners. It still needs PoP for that one transaction, but after it, PoP is gone. Rule: revert `operation == DELEGATECALL` unless `to` ∈ {MultiSendCallOnly 1.4.1 `0x9641…02e2`, MultiSendCallOnly 1.5.0 `0xA83c…1836`}. Those execute only CALLs. Never allow `MultiSend` (the full version, which can delegatecall).

### 4.5 Reentrancy / statefulness
Keep `checkTransaction` `view` (as in the prototype). Replay is already stopped: the attestation binds `safeTxHash`, which binds the Safe nonce. If you add state (e.g. a "used" mark), write it in `checkTransaction`; don't rely on `checkAfterExecution` (1.5.0 uses `call`, so the executed call can reenter).

### 4.6 Signature-tail parsing
- The tail is the **last** 108 bytes: `pairTag(32) ‖ expiry(uint64, 8) ‖ r(32) ‖ s(32) ‖ "POP1"(4)`.
- Contract-signature dynamic data must come before the tail. The offsets in `s` are measured from the start of `signatures`, so appending never breaks them. V(the P256Owner and PopGuard tests both pass; I didn't combine them in one test, but the layouts are independent).
- Mitigate misuse by domain-separating the digest: `sha256("pop-safe-v1" ‖ chainId ‖ safe ‖ safeTxHash ‖ pairTag ‖ expiry)`.

### 4.7 Nonce and ordering
- Safe executes strictly by nonce. The attestation is per `safeTxHash`, so it is per nonce. If another transaction lands first, the attestation is dead, and the owners must meet again. With a 2-owner Safe that's fine.
- Keep `expiry` short (e.g. 10 min) so a stale attestation can't be held back and used later.

### 4.8 Issuer key
- Don't reuse the SBcred3 issuer key (`POP_ISSUER_KEY`) for onchain attestations. Use a separate key, `POP_ATTEST_KEY`, with a different domain tag.
- P-256 lets the server reuse its crypto stack (`cryptography`); the verify costs about 7.6k gas.
- Key rotation: make `(qx, qy)` settable only by the Safe itself (`msg.sender == safe`, per-Safe config), not by a deployer admin. The World App rules forbid privileged admin addresses on custody contracts (§1.5).

---

## 5. Native mobile app (Kotlin / Swift) without the Safe UI

It is feasible and needs no JS:
1. **Hash:** EIP-712, `domainSeparator = keccak(abi.encode(0x47e7…9218, chainId, safe))`, `safeTxHash = keccak(0x19 ‖ 0x01 ‖ domainSeparator ‖ keccak(abi.encode(0xbb83…86d8, to, value, keccak(data), operation, safeTxGas, baseGas, gasPrice, gasToken, refundReceiver, nonce)))`. Or read `getTransactionHash(...)` with one `eth_call`, which is simplest and exact.
2. **Owner key options:**
   - **(a) Phone hardware P-256 key as the owner via a `P256Owner` EIP-1271 contract** (prototyped, §6.2). The phone signs the 32-byte `safeTxHash` with `SHA256withECDSA` / `SecKeyCreateSignature(.ecdsaSignatureMessageX962SHA256)` and sends raw `r‖s`; the app already has DER→raw conversion. One CREATE2-deployed contract per device, or one registry contract keyed by pubkey. This ties "the device that proved presence" to "the device that authorized the spend".
   - **(b) secp256k1 software key** (Keystore and the Secure Enclave don't do k1). Wrap it with a hardware AES key. KMP libs: `fr.acinq.secp256k1:secp256k1-kmp` 0.24.0, `org.kotlincrypto.hash:sha3` 0.8.0 (Keccak-256); JVM-only alternative: `org.web3j:core` 6.0.0. V(Maven Central metadata).
   - **(c) World App wallet as the owner:** blocked on the §2 unknowns.
3. **Propose / collect signatures:**
   - On 480 or Sepolia: POST to the tx service (§1.4), with an API key held by *our server*, not shipped in the app.
   - On 4801 there's no service, so collect signatures through our own server (the PoP server already pairs the two phones, so it can carry the SafeTx and both signatures).
4. **Execute:** any EOA (the server relayer, `gasPrice = 0`) calls `execTransaction(..., ownerSigs ‖ popTail)`. The phones need no ETH.

### Deploy + enable guard via Foundry (script outline)

The prototype `_deploy` / `_exec` does exactly this on a fork.

```
1. PopGuard g = new PopGuard(qx, qy)                         // or CREATE2 via 0x4e59…956C
2. safe = SafeProxyFactory(0x4e1D…ec67 | 1.5.0: 0x14F2…5e7b).createProxyWithNonce(
      singleton = SafeL2 1.4.1 0x29fc…C762 (4801) | SafeL2 1.5.0 0xEdd1…7C7e (480/Sepolia),
      initializer = abi.encodeCall(Safe.setup, (owners[], threshold, to, data, fallbackHandler, 0, 0, 0)),
      saltNonce)
   // setGuard can't be set inside setup directly (setup has no guard param): either
   //   (i) setup(to = SetupHelper, data = delegatecall that sstore's GUARD_STORAGE_SLOT), or
   //   (ii) first Safe tx = setGuard(g), signed by the owners (prototype does (ii)).
3. 1.5.0: second tx setModuleGuard(denyAll) (or include in a MultiSendCallOnly batch; that is a DELEGATECALL to 0xA83c…1836).
4. fund the Safe; every later tx needs ownerSigs ‖ popTail.
```

Commands: `forge script script/Deploy.s.sol --rpc-url https://worldchain-sepolia.g.alchemy.com/public --broadcast --private-key $PK`. Explorers: 480 `https://worldscan.org`, 4801 `https://sepolia.worldscan.org` (from World docs links). Contract verification on worldscan: U (not tried).

---

## 6. Code that matters (from the prototype)

### 6.1 PopGuard (core; add the §4 rules before real use)

```solidity
function checkTransaction(address to, uint256 value, bytes memory data, uint8 operation,
    uint256 safeTxGas, uint256 baseGas, uint256 gasPrice, address gasToken,
    address payable refundReceiver, bytes memory signatures, address) external view {
    bytes32 h = ISafeMin(msg.sender).getTransactionHash(to, value, data, operation, safeTxGas,
        baseGas, gasPrice, gasToken, refundReceiver, ISafeMin(msg.sender).nonce() - 1);
    uint256 n = signatures.length;
    if (n < 108) revert NoAttestation();
    bytes32 pairTag; uint64 expiry; bytes32 r; bytes32 s; bytes4 magic;
    assembly {
        let p := add(add(signatures, 32), sub(n, 108))
        pairTag := mload(p)
        expiry  := shr(192, mload(add(p, 32)))
        r := mload(add(p, 40))
        s := mload(add(p, 72))
        magic := mload(add(p, 104))
    }
    if (magic != 0x504f5031) revert NoAttestation();          // "POP1"
    if (block.timestamp > expiry) revert Expired();
    bytes32 d = sha256(abi.encodePacked("pop-safe-v1", block.chainid, msg.sender, h, pairTag, expiry));
    (bool ok, bytes memory ret) = address(0x100).staticcall(abi.encode(d, r, s, qx, qy));
    if (!ok || ret.length != 32 || abi.decode(ret, (uint256)) != 1) revert BadAttestation();
}
function supportsInterface(bytes4 id) external pure returns (bool) { return id == 0xe6d7a83a || id == 0x01ffc9a7; }
function checkAfterExecution(bytes32, bool) external pure {}
```

Server side, the attestation the PoP server signs after a NEAR verdict:

```
digest = sha256("pop-safe-v1" ‖ uint256 chainId ‖ address safe(20) ‖ bytes32 safeTxHash ‖ bytes32 pair_tag ‖ uint64 expiry)
sig    = P-256 ECDSA(POP_ATTEST_KEY, prehashed digest) → r‖s
tail   = pair_tag ‖ expiry(8, BE) ‖ r ‖ s ‖ "POP1"
```

`abi.encodePacked` of `uint256` is 32 bytes and `address` is 20. The Python side must match these widths exactly; pin a test vector.

The `safeTxHash` must reach the PoP session. Put it in the session at create time (`POST /v1/session` `purpose: {kind: "safe", chain_id, safe, safe_tx_hash}`), and have the World ID `signal` include it too. Otherwise one meeting could authorize a different transaction.

### 6.2 P256Owner (phone hardware key as a Safe owner)

```solidity
function _ok(bytes32 h, bytes memory sig) internal view returns (bool) {   // sig = r‖s
    (bytes32 r, bytes32 s) = abi.decode(sig, (bytes32, bytes32));
    (bool ok, bytes memory ret) = address(0x100).staticcall(abi.encode(sha256(abi.encodePacked(h)), r, s, x, y));
    return ok && ret.length == 32 && abi.decode(ret, (uint256)) == 1;
}
function isValidSignature(bytes32 h, bytes memory sig) external view returns (bytes4) { return _ok(h, sig) ? bytes4(0x1626ba7e) : bytes4(0xffffffff); }            // 1.5.0
function isValidSignature(bytes memory data, bytes memory sig) external view returns (bytes4) { return _ok(keccak256(data), sig) ? bytes4(0x20c13b0b) : bytes4(0xffffffff); } // 1.4.1
```

Signature blob for 2 contract owners (owners sorted by address):

`[r=owner1, s=130, v=0][r=owner2, s=226, v=0][len=64 ‖ r1 ‖ s1][len=64 ‖ r2 ‖ s2]` (plus the PoP tail if a guard is set).

---

## 7. Implications for the SAFE idea

- It is buildable in hackathon time. The core contract is about 60 lines and proven on a fork. The rest is plumbing: the session carries `safeTxHash`, the server signs the attestation, a relayer executes.
- **Chain:**
  - The demo runs on **World Chain mainnet 480** if an onchain World ID v4 check is wanted (only there), or if the Safe{Wallet} UI / tx service should show the Safe. Gas is cheap.
  - **4801** works for a pure-contract demo with our own server as the signature collector, and World ID verified off-chain (Portal) or through the v3 router.
  - Don't split across chains.
- **World ID placement, in order of effort:**
  1. The server verifies both World ID proofs (Portal `/v4/verify`) and folds `pair_tag` (from the two nullifiers, `docs/pop-human-adapters.md`) into the signed attestation. The chain sees only the issuer signature.
  2. Variant D on 480: the module verifies both v4 proofs onchain through `0x0000…94d7`, with `signal` bound to `safeTxHash`. The chain then checks humanness itself; PoP is still the server's word.
- **Story for judges:** "a Safe where the co-signers must be two verified humans who are physically in the same room: onchain-enforced, per transaction". The phone hardware keys can be the owners (P256Owner), so there's no seed phrase anywhere.
- **Scope:**
  - Must: A + escape hatch + no modules / delegatecall rules.
  - Nice to have: B for UI compatibility, P256Owner owners, and 1.5.0 plus a module guard.
- **Remaining trust gap to state honestly:** the PoP verdict is the server's attestation (the ZK proofs are verified off-chain by popprover). A remote World ID lender plus one person holding both phones still defeats the "two humans" claim (`pop-human-adapters.md` §2).

## 8. Implications for the POOL idea

- The Safe machinery itself is irrelevant to a privacy pool. What carries over:
  - the **P-256 precompile** at `0x100` on 480, 4801 and Sepolia (about 7.6k gas; verified), so the pool contract can check a server attestation or a device signature directly;
  - the **attestation format** (§6.1, with `safeTxHash` → the pool's `transferCommitment` / nullifier);
  - the per-action binding lesson: bind presence to the exact transfer, not a time window.
- World App wallets are Safe 1.4.1 + 4337 module (§1.5). A pool deposit from World App would go through MiniKit `sendTransaction` (a 4337 userOp). **The pool contract must be allowlisted in the Developer Portal** (§1.5), and custody-contract rules apply: immutable or TFH co-signed upgrades, ≥90% test coverage. That is a real process cost for POOL; SAFE avoids it if the Safe isn't driven from inside World App.
- For privacy: an attestation onchain that contains `pair_tag` links the two parties' meeting to the transfer. For POOL, the attestation must be consumed **inside the ZK circuit** (or be committed as a hidden value); otherwise it leaks who met whom. P-256 inside a BN254 circuit is costly (non-native field). So POOL needs either a BN254-friendly attester signature (e.g. EdDSA over Baby Jubjub, or Poseidon-based) or the attester signing a commitment only. That is a genuine unknown for POOL, not for SAFE.
- On-chain World ID v4 is on 480 only, the same constraint for both ideas.

## 9. Open questions

1. Can MiniKit `signTypedData` (inside World App) sign a `SafeTx` EIP-712 for a *foreign* Safe, and what exactly is the signature format? This decides whether World App wallets can be owners of the PoP Safe. Needs a live test.
2. Is the Safe{Wallet} UI required in the demo? If yes, switch to variant B (an attestation stored onchain) and test on 480 that the UI executes with a custom guard set.
3. What is the escape-hatch delay, and who may announce it (any owner vs threshold)? Is a Zodiac Delay module on 480 acceptable instead (with module-guard implications on 1.5.0)?
4. Should the attester key be P-256 (reuse the server crypto; about 7.6k gas) or secp256k1 (`ecrecover`, about 3k gas, tooling everywhere)? P-256 is recommended for SAFE; POOL may want a SNARK-friendly key instead.
5. How does `safeTxHash` enter the PoP session and the World ID `signal`? It needs a server API change (`POST /v1/session` purpose field) owned by the server workflow. Coordinate; don't edit `server/` from here.
6. Should the Safe be 1.5.0 (module guard, new EIP-1271) or 1.4.1 (everything present on 4801, same as World App wallets)? 480: pick 1.5.0. 4801: 1.4.1, or the 1.5.0 L1 singleton (verified working).
7. Does gas sponsorship go through our relayer EOA (simple) or PBH / 4337 (World-native story, but the module bypasses the guard)? Recommend the relayer.
8. Live P-256 precompile gas on 480 (for the pitch numbers): run `cast estimate` against a deployed PopGuard.
