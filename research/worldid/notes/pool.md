# POOL: presence-gated private transfer, research note

2026-09-26. Scope: which privacy-pool design to fork for "a private payment only goes through if payer and payee (two World ID humans) physically met", where the presence condition enters, and the exact circuits. Everything built lives in the scratchpad (`$S` = `/private/tmp/claude-501/-Users-takahiro-ogawa-dev-enconomy/3d9dd236-bf59-4c81-91f5-6bb7c5ebc6e3/scratchpad/pool`), nothing in the repo was touched except this file.

Tags: **V(src)** = verified, with the source or command. **U** = unverified. **E** = estimate.

## 0. TL;DR

1. **Fork 0xbow Privacy Pools** (`0xbow-io/privacy-pools-core`, Apache-2.0, circom 2.2 + Groth16/BN254 + foundry, solc 0.8.28). I cloned it, built it, and ran its tests with real proofs: unit 108/110 pass, integration (real snarkjs proofs over FFI) 10/10 pass. Gas: deposit 288,653, withdraw 293k–446k, relayed withdraw 375k–479k. V(forge, §1.1)
2. **Railgun is out: its code is "UNLICENSED" / "No License is provided for any party under any circumstances"**, and it has 13×13 circuit variants plus governance/proxy baggage. Tornado Nova is MIT but circom 0.5 / solc 0.7 / forked snarkjs, from 2022. FHE (Zama, Fhenix) isn't on World Chain. Aztec is its own L2. V(§1.2–1.6)
3. **The presence condition enters as (a): a Merkle root of presence leaves, used as a public input of a new transfer circuit.** The PoP attester (our server) inserts each leaf into an onchain Poseidon LeanIMT. That resolves the open issue in `safe.md` §8 ("P-256 inside BN254 is costly"): the circuit never checks a signature. The contract's `onlyAttester` access control on the insert is the authentication, so the circuit only needs Poseidon Merkle membership.
   - (b), an onchain precondition on addresses, leaks payer↔payee.
   - (c), an ASP-style set keyed by deposit labels, leaks the payer's deposit to the attester and to anyone who reads the ASP leaves.
4. **Minimal viable circuit, `PresenceTransfer(32, 20)`, built and proven** (§5.2): one input note → change note + payee note. Amount, payer and payee are all hidden onchain.
   - `presenceLeaf = Poseidon(TAG_PRES, Poseidon(TAG_PAYER, existingNullifier), payeeCommitment)`
   - 15,243 constraints (O2), Groth16 prove 3.05 s wall on the M2 with the snarkjs CLI, zkey 8.6 MB.
   - Solidity `verifyProof` gas 242,116. Negative tests (over-spend, wrong payee) are UNSAT. V
5. **The payee cashes out with 0xbow's unchanged `withdraw` circuit and its real ceremony zkey.** Payee notes carry a constant label `LABEL_TRANSFER` that sits in the ASP tree. So only one new circuit needs a (hackathon, single-party) setup. V (the ceremony vkey `IC0` equals the deployed `WithdrawalVerifier.sol` constant)
6. **Deploy on World Chain mainnet 480.** The v4 `WorldIDVerifier` is only there (prod `0x00000000009E00F9FE82CfeeBB4556686da094d7`, staging `0x703a…57DB`); 4801 has no code at either. Gas price was 0.0015 gwei when I checked, so a 500k-gas tx costs about 7.5e-7 ETH. V(cast)
7. **Biggest risk isn't contracts or circuits, it's the client prover** (the payer needs a BN254 Groth16 prover plus note/tree sync). §7 lists the options. The honest cut if time runs short: the phones do presence and World ID, and a laptop "wallet" (TS + snarkjs) holds notes and proves.

## 1. Verified facts

### 1.1 0xbow Privacy Pools (the fork base)

- Repo `github.com/0xbow-io/privacy-pools-core`, commit `d494b63e79f33bb2b0c8ece6cdacdca465c3b884` (2026-09-23). Yarn workspaces: `packages/{circuits,contracts,relayer,sdk}`. License Apache-2.0 (`SPDX` in `PrivacyPool.sol`). V(clone)
- Live on Ethereum (14 pools), Optimism (2), BSC (2), Arbitrum (3). **Not on World Chain.** V(https://privacy.eth.sh/ via search summary; no 480/4801 entries in `packages/contracts/script` or `sdk`, grep)
- **Circuits** (`packages/circuits/circuits/`):
  - `commitment.circom`: `nullifierHash = Poseidon(nullifier)`, `precommitment = Poseidon(nullifier, secret)`, `commitment = Poseidon(value, label, precommitment)`.
  - `merkleTree.circom`: `LeanIMTInclusionProof(maxDepth)` (zk-kit LeanIMT, dynamic depth, Poseidon2).
  - `withdraw.circom`: `Withdraw(32)`.
    - Public `[withdrawnValue, stateRoot, stateTreeDepth, ASPRoot, ASPTreeDepth, context]` and outputs `[newCommitmentHash, existingNullifierHash]`.
    - The public-signal order in the verifier is `[newCommitmentHash, existingNullifierHash, withdrawnValue, stateRoot, stateTreeDepth, ASPRoot, ASPTreeDepth, context]` (`ProofLib.sol`).
    - It proves the input note is in the state tree, the **label** is in the ASP tree, the 128-bit ranges hold, the new nullifier ≠ the old one, and the change note equals `Poseidon(existing − withdrawn, label, Poseidon(newNullifier, newSecret))`.
  - Size: 36,832 constraints (circomkit/O1), 17,442 non-linear at O2. V(`snarkjs r1cs info`, `circom --O1/--O2`)
- **Contracts** (`packages/contracts/src/contracts/`):
  - `State.sol`: LeanIMT state tree, `ROOT_HISTORY_SIZE = 64`, `MAX_TREE_DEPTH = 32`, `nullifierHashes` mapping.
  - `PrivacyPool.sol`:
    - `deposit(depositor, value, precommitment)` (onlyEntrypoint). `label = keccak256(abi.encodePacked(SCOPE, ++nonce)) % SNARK_SCALAR_FIELD`, and `commitment = PoseidonT4.hash([value, label, precommitment])`.
    - `withdraw(Withdrawal{processooor, data}, WithdrawProof)` checks: `msg.sender == processooor`, `context == keccak256(abi.encode(withdrawal, SCOPE)) % p`, known state root, `ASPRoot == ENTRYPOINT.latestRoot()`.
    - `ragequit` (original depositor only).
  - `Entrypoint.sol` holds the ASP roots (`updateRoot(root, ipfsCID)` by `ASP_POSTMAN`), `relay()` with fees, and deposits. `PrivacyPoolSimple` = native ETH, `PrivacyPoolComplex` = ERC-20.
- **Build:** `yarn install` took 122 s. `forge build` fails out of the box under forge 1.4.3. Fixes I needed, all in the scratchpad copy:
  1. `FOUNDRY_AUTO_DETECT_REMAPPINGS=false`. Otherwise the hoisted `@openzeppelin/contracts@3.4.2-solc-0.7` wins.
  2. Remap `lean-imt/` through a symlink named without `.sol`. Forge mangles `lean-imt.sol/` into `lean-imt.solInternalLeanIMT.sol`.
  3. Add `poseidon-solidity/`, `@openzeppelin/contracts/`, `@openzeppelin/contracts-upgradeable/` and `solidity-stringutils/` (clone `Arachnid/solidity-stringutils`) to `remappings.txt`.

  V(forge 1.4.3)
- **Tests:**
  - `forge test --match-contract Unit`: 108 pass, 2 fail (not investigated; unrelated suites).
  - `forge test --match-contract IntegrationNative --ffi` (forks Ethereum mainnet; I set `ETHEREUM_MAINNET_RPC=https://ethereum-rpc.publicnode.com`): **10/10 pass in 299 s**.
  - `--gas-report`:
    - `Entrypoint.deposit`: 288,653
    - `PrivacyPool.withdraw`: min 293,619 / avg 411,233 / max 446,278
    - `Entrypoint.relay`: avg 374,814 / max 479,005

  V
- **Proving:** `snarkjs groth16 fullprove` of the default withdraw input takes 13.9 s wall through `npx` (snarkjs 0.7.5). Most of that is node/npx startup plus the single-threaded witness step. Prove alone from a witness is about 4 s (§5). V
- **Ceremony:** `packages/circuits/trusted-setup/final-keys/withdraw.{zkey,vkey}`. `vkey.IC[0].x = 2091785278…058181` equals `IC0x` in `verifiers/WithdrawalVerifier.sol`, so the repo's zkey is the production one. V(python + grep)

### 1.2 Railgun

- Circuits `Railgun-Privacy/circuits-v2`: `JoinSplit(nInputs, nOutputs, depth)`.
  - Public inputs: `merkleRoot, boundParamsHash, nullifiers[], commitmentsOut[]`.
  - EdDSA-Poseidon signature over the hash of the public inputs.
  - `nullifier = Poseidon(nullifyingKey, leafIndex)`, `npk = Poseidon(mpk, random)`, `commitment = Poseidon(npk, token, value)`, 120-bit values.

  V(clone `src/library/joinsplit.circom`)
- Contracts `Railgun-Privacy/contract`, hardhat:
  - `BoundParams{treeNumber, minGasPrice, unshield, chainID, adaptContract, adaptParams, commitmentCiphertext[]}`
  - `CommitmentCiphertext{bytes32[4] ciphertext, blindedSenderViewingKey, blindedReceiverViewingKey, annotationData, memo}`

  V(clone `contracts/logic/Globals.sol`)
- **License: `circuits-v2/License.md` = "No License is provided for any party under any circumstances."** The contract's `package.json` is `"license": "UNLICENSED"`, and so is its SPDX. **Forking is not permitted.** V
- SDK `@railgun-community/wallet@10.4.0` loads a Groth16 prover per platform. V(docs.railgun.org getting-started)
- Deployed on Ethereum, BNB, Polygon and Arbitrum. **Not World Chain.** U-ish: secondary sources (altrady, L2BEAT), no official list fetched.
- **Private POI:**
  - List providers (Chainalysis, Elliptic, …); a 1 h "unshield-only standby" after shielding.
  - Recursive SNARK proofs of non-inclusion, served by POI nodes.
  - **Enforced by wallets and broadcasters, not onchain.**

  V(docs.railgun.org/wiki/assurance/private-proofs-of-innocence)

### 1.3 Tornado Nova

- `tornadocash/tornado-nova`, last commit 2022-03-30, MIT (SPDX) / ISC (package).
- `Transaction(levels, nIns, nOuts)` 2-in/2-out and 16-in, with `extDataHash` binding `ExtData{recipient, extAmount, relayer, fee, encryptedOutput1, encryptedOutput2, isL1Withdrawal, l1Fee}`. UTXO `commitment = hash(amount, pubkey, blinding)`.
- circom `^0.5.45`, solc `^0.7.0`, forked snarkjs/circomlib git deps. V(clone)
- The best existing *shielded transfer with hidden amounts* design, but the toolchain is stale.
- OFAC delisted Tornado Cash on 2025-03-21. V(https://www.coindesk.com/policy/2025/03/21/u-s-government-removes-tornado-cash-sanctions)

### 1.4 FHE: Zama and Fhenix

- Zama Protocol host chains: mainnet Ethereum, Polygon, Gateway, BSC, HyperEVM, Solana; testnet Ethereum Sepolia, Gateway testnet, BSC testnet, Polygon Amoy. **No World Chain.**
- Public decryption is async and 3-step: `FHE.makePubliclyDecryptable` → relayer → `FHE.checkSignatures`.

  V(https://docs.zama.org/protocol/protocol/overview.md?ask=…)
- ERC-7984 (confidential fungible token; OpenZeppelin `confidential-contracts`): encrypted amounts, **public sender and recipient addresses**. V(docs.openzeppelin.com/confidential-contracts/token, zama.org/post/erc-7984…)
- Fhenix CoFHE: Ethereum, Arbitrum and Base (+ Sepolias). No World Chain. V(search summary of fhenix.io blog / cofhe docs; not fetched first-hand)

### 1.5 Others

- **Semaphore v4:** `Semaphore 0x8A1fd199516489B0Fb7153EB5f075cDAC83c693D`, `SemaphoreVerifier 0x4DeC9E3784EcC1eE002001BfE91deEf4A48931f8`, `PoseidonT3 0xB43122Ecb241DD50062641f089876679fd06599a`. All three have **no code on 480 or 4801**. V(docs.semaphore.pse.dev/deployed-contracts + cast code). Semaphore v4 uses the same LeanIMT as 0xbow.
- **zkBob:** Polygon USDC pool sunset 2025-01-31; Optimism pools remain. V(blog.zkbob.com). Not relevant for us.
- **EY Nightfall_4:** `EYBlockchain/nightfall_4_CE`, a ZK rollup ("experimental"). Too heavy. V(github search result)
- **Aztec:** its own L2. Alpha mainnet since 2026-03-31, Alpha V5 2026-07-21, 72 s blocks. U(news aggregators). It can't read World Chain state; out.
- **ERC-5564 / ERC-6538:** Announcer `0x55649E01B5Df198D18D95b5cc5051630cfD45564` (Final; `announce(uint256 schemeId, address stealthAddress, bytes ephemeralPubKey, bytes metadata)`). Registry `0x6538E6bf4B0eBd30A8Ea093027Ac2422ce5d6538`. **Both have code on 480, none on 4801.** V(eips.ethereum.org/EIPS/eip-5564 + cast code)
- **Noir/UltraHonk Solidity verifiers:** about 24 KB after squeezing (default >24,576 B), 7,232-byte proofs, bb.js 4.1.1 browser proving 18.8 s cold / 1.5 s warm (one data point). V(search summary, noir-lang discussion #8560 and others; no gas figure found). Groth16 (about 240–260k gas, 256-byte proof) is cheaper and simpler here.

### 1.6 World Chain facts the pool needs

- RPC `https://worldchain-mainnet.g.alchemy.com/public` → chain id 480. `https://worldchain-sepolia.g.alchemy.com/public` → 4801. V(cast chain-id)
- `WorldIDVerifier` v4:
  - prod `0x00000000009E00F9FE82CfeeBB4556686da094d7`, staging `0x703a6316c975DEabF30b637c155edD53e24657DB`. Both are proxies on **480** (code 177 / 285 hex chars) with impl `0xff93a0146bf6e7557b63315efece083ca07d4c73`.
  - `0x703a…` has **no code on 4801**.
  - Signature: `verify(uint256 nullifier, uint256 action, uint64 rpId, uint256 nonce, uint256 signalHash, uint64 expiresAtMin, uint64 issuerSchemaId, uint256 credentialGenesisIssuedAtMin, uint256[5] zeroKnowledgeProof) view`.
  - `action = uint256(keccak256(bytes(action))) >> 8`.

  V(https://docs.world.org/world-id/idkit/onchain-verification + cast)
- The v4 verifier resolves `oprfPublicKey` from `OprfKeyRegistry` by `rpId` and checks `issuerSchemaId` in `CredentialSchemaIssuerRegistry`. **It doesn't check the RP signature or the nonce**; nullifier replay is the app's job. V(`worldcoin/world-id-protocol` `contracts/src/core/WorldIDVerifier.sol` L151–210)
- Tokens on 480: WLD `0x2cFc85d8E48F8EAB294be644d9E25C3030863003` (18), USDC `0x79A02482A880bCE3F13e09Da970dC34db4CD24d1` (6), WETH `0x4200…0006` (18). Permit2 `0x000000000022D473030F116dDEE9F6B43aC78BA3` has code. V(cast)
- CREATE2 deployers `0x4e59b44847b379578588920cA78FbF26c0B4956C` and `0x914d7Fec6aaC8cd542e72Bca78B30650d45643d7` exist on 480 and 4801. EntryPoint v0.7 `0x0000000071727De22E5E9d8BAf0edAc6f37da032` too. V(cast)
- `poseidon-solidity` deterministic addresses (`PoseidonT3 0x3333333C0A88F9BE4fd23ed0536F9B6c427e3B93`, `T4 0x4443338EF595F44e0121df4C21102677B142ECF0`) are **not deployed** on 480 or 4801. Forge links and deploys them as libraries during `forge script`, so no action is needed; just expect two extra deploy txs. V(cast)
- Gas price: 480 at 0.0015 gwei, 4801 at 0.0011 gwei. V(cast gas-price, 2026-09-26)
- MiniKit `sendTransaction`:
  - chain 480 only;
  - **every contract and token must be allowlisted in the Developer Portal, else `invalid_contract`**;
  - Permit2 AllowanceTransfer only (no SignatureTransfer in v2);
  - daily tx limit.

  V(https://docs.world.org/mini-apps/commands/send-transaction)

### 1.7 Prototypes built here (scratchpad)

| Artifact | Path under `$S/privacy-pools-core/packages/circuits/pres/` | Result |
| --- | --- | --- |
| `presenceWithdraw.circom` (variant V1: 0xbow withdraw + presence leaf bound to the public `recipient`) | `presenceWithdraw.circom`, `mkinput.cjs` | 23,023 constraints at O2 (48,587 at O1), 11 public signals. Good input SAT, wrong recipient UNSAT. Proves in about 4 s. `verifyProof` **262,840 gas** |
| `presenceTransfer.circom` (variant V2, recommended) | `presenceTransfer.circom`, `mkinputT.cjs` | **15,243 constraints**, 5 public inputs + 3 outputs. Good input SAT; over-spend and wrong payee pre-commitment UNSAT. `groth16 prove` 3.05 s wall (13.1 s user; multi-threaded). zkey 8.6 MB. `verifyProof` **242,116 gas**; a flipped `payeeCommitment` → false |
| Verifier gas harness | `$S/vgas/` (`forge test -vv`) | numbers above |

Setup used `research/sound-bound/spikes/zk/build/pot18.ptau` (read only). snarkjs 0.7.5 (the root `node_modules/snarkjs`; the `circom_tester`-nested snarkjs exports a `^0.6.11` verifier, so don't use it). circom 2.1.8 locally: I set `pragma circom 2.1.8` in the copies; 0xbow pins `2.2.0`, which is needed only for the pragma.

## 2. Unverified / conflicting

- `worldid-prize.md` and `mobile-wallet.md` say a Railgun-like pool is "not realistic in ~17 h". **Partly refuted for the contracts and circuits:**
  - 0xbow builds, tests and proves as is;
  - the new circuit is 15k constraints and already SAT/UNSAT-tested;
  - the contract delta is about 150 lines (§6).

  **Still true for the client:** note storage, tree sync from events, and a BN254 prover on the phone are new work (§7).
- `safe.md` §8 says POOL needs a SNARK-friendly attester signature in-circuit. **Not needed** with the onchain-tree design: the attester writes leaves into a contract, and the circuit proves Merkle membership only.
- Onchain `WorldIDVerifier.verify` for **per-session (unregistered) actions**: the Portal path works (worldid-spike). Onchain the action is just a field element, and the OPRF key is per `rpId`, so it should work. U (untested with a real proof). Also U: whether our RP's `rpId` has an OPRF key in `OprfKeyRegistry` on 480. If `getOprfPublicKey(rpId)` returns zero or reverts, onchain verify can't work for us. Test: `cast call <OprfKeyRegistry> "getOprfPublicKey(uint160)" <rpId>` (get the registry from `WorldIDVerifier.getOprfKeyRegistry()`).
- Mobile proving time for the 15k-constraint circuit: U. E: 1–3 s native (rapidsnark/arkworks) on a 2023+ phone, 5–15 s with snarkjs in a WebView.
- 2 failing unit suites in 0xbow: not investigated. The integration suite, which is what we reuse, is green.
- Railgun chain list: from secondary sources only.

## 3. Where the presence condition enters

| | Mechanism | Hides payer's deposit | Hides payee | Hides amount | Trust | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| **(a) public input: presence root** | attester inserts a hidden leaf binding (payer note, payee note) into an onchain LeanIMT; the transfer circuit proves membership | yes | yes | yes (V2) | attester can mint tickets (can't move funds) | **pick** |
| (b) onchain precondition | contract checks `presence[payer][payee]` or an attester sig on `(payerAddr, payeeAddr)` before release | no, public | no | only with FHE | same | a fallback demo only ("escrow"); it isn't private |
| (c) ASP-like set of met pairs | ASP leaves = `H(label, payee)`; reuse 0xbow's ASP slot | no: the label is public at deposit, so the attester (and the IPFS leaf list) learns which deposit pays whom | partly | no | same | leaks; reject |

Why a leaf bound to the **note nullifier** and not to an address:

- **One-shot.** The ticket dies when the note is spent. The change note has a new nullifier, so another payment needs another meeting. No extra "presence nullifier" is needed.
- **Unlinkable.** The attester learns `payerTag = Poseidon(TAG_PAYER, nullifier)`. The chain later shows `nullifierHash = Poseidon(nullifier)`, a different hash, and nobody can link the two without `nullifier`.
- **Non-transferable ticket.** Only the holder of that note can use it, not just anyone who got a ticket.

Why the leaf carries the **full payee note commitment** (`payeeCommitment = Poseidon(value, LABEL_TRANSFER, payeePrecommitment)`):

- The meeting authorizes exactly that amount to exactly that note. The payer can't send a different amount.
- The payee knows what to watch for: the commitment appears in `LeafInserted`.
- The payee needs no note ciphertext, because they created the secrets. No encrypted memo, no viewing keys.

## 4. Recommended design (V2: presence-gated shielded transfer)

### 4.1 Objects

```
SNARK_SCALAR_FIELD p = 21888242871839275222246405745257275088548364400416034343698204186575808495617
TAG_PAYER      = 0x706f702d7061796572          // ascii "pop-payer"
TAG_PRES       = 0x706f702d70726573            // ascii "pop-pres"
LABEL_TRANSFER = 0x706f702d7472616e73666572    // ascii "pop-transfer"; nonzero, << p, never equal to a keccak%p deposit label in practice

note (0xbow format):  commitment = PoseidonT4(value, label, PoseidonT3(nullifier, secret))
                      nullifierHash = PoseidonT2(nullifier)          // circomlib Poseidon(1)
payer:  payerTag        = Poseidon(TAG_PAYER, existingNullifier)     // Poseidon(2)
payee:  payeePre        = Poseidon(payeeNullifier, payeeSecret)      // Poseidon(2), random 31-byte secrets
        payeeCommitment = Poseidon(value, LABEL_TRANSFER, payeePre)  // Poseidon(3)
leaf:   presenceLeaf    = Poseidon(TAG_PRES, payerTag, payeeCommitment)
```

Poseidon here is circomlib Poseidon (BN254). The JS side uses `poseidon-lite` (`poseidon1/2/3`) and the Solidity side `poseidon-solidity` `PoseidonT3/T4`. V (JS↔circuit parity: the witnesses in §1.7 were built with poseidon-lite plus `@zk-kit/lean-imt` 2.x and satisfied the circuit)

### 4.2 Flow (payer P, payee Q)

1. **P funds the pool once.**
   - `deposit(precommitment)` with ETH (or an ERC-20 variant).
   - Optional World ID gate at deposit (§4.4).
   - The label is auto-inserted into the ASP tree.
2. **Payment request.** Q's app draws `payeeNullifier, payeeSecret` and computes `payeePre` and `payeeCommitment` for the agreed `value`. It sends `{value, payeePre}` to P. MVP channel: the PoP session app payload via the server (the server sees `value`). Better: QR/NFC, or encrypt to P's device key.
3. **P picks one note** with `existingValue ≥ value` and computes `payerTag` and `presenceLeaf`.
4. **PoP session** as today: pair, both World ID proofs (`action = pop:<sid>`, distinct nullifiers), audio run, verdict.
   - Both apps submit their piece, signed with the device key: P `payerTag`, Q `payeeCommitment`.
   - Q's app recomputes the leaf from `payerTag` and its own `payeeCommitment` and shows "receive `value` from <name>".
   - Tier-2 hardening, aligned with `bridge.md` §4: the session is created with `context.ctx_hash = keccak256(abi.encode("pool-xfer-v1", pool, presenceLeaf))`, so the phones' POPT signatures and World ID signals commit to the leaf.
5. **Server, on NEAR + human policy OK:** `pool.postPresence(presenceLeaf)` (onlyAttester), or through the shared `PresenceRegistry` from `bridge.md` with `deviceA/B = 0` (privacy mode).
6. **P proves `PresenceTransfer`** with:
   - public inputs `stateRoot, stateTreeDepth, presenceRoot, presenceTreeDepth, context`;
   - outputs `existingNullifierHash, changeCommitment, payeeCommitment`.

   P sends the proof to the relayer (our server's hot wallet), which calls `pool.transfer(...)`. P's own address never touches the chain.
7. **Q** sees `payeeCommitment` in `LeafInserted(index, leaf, root)` and now holds a note with `label = LABEL_TRANSFER`. Cash-out: the standard 0xbow `withdraw` to any address via relay (the ASP tree contains `LABEL_TRANSFER`). Or pay onwards with another meeting.

### 4.3 What each party and the public learn

| Observer | Learns |
| --- | --- |
| Public chain | a presence leaf was posted at t (a meeting happened, not who or how much); a transfer happened (nullifier + 2 new commitments; nothing about amount or parties); cash-outs show amount + recipient address only |
| Attester (our server) | who met whom (it already knows from PoP), `payerTag`, `payeeCommitment`; in the MVP channel also `value` and `payeePre`. It **can't** tell which deposit funded it, or when Q cashes out |
| Payee Q | the amount (agreed) and nothing about P's deposit (the payee note has its own label) |
| Payer P | `payeePre` (it can't spend: it lacks `payeeNullifier` and `payeeSecret`) |

- **Timing leak:** leaf insertion at time t, then the transfer shortly after. Mitigations: batch leaves every N minutes, and delay the transfer. With few users the anonymity set is tiny anyway. Say so.
- **Attester power:** it can post fake tickets, i.e., authorize transfers between people who didn't meet. It **can't** move or freeze funds (ragequit and withdraw don't depend on it). Pitch line: "a compromised server can issue a bogus meeting, never take your money".

### 4.4 World ID placement

- **MVP:** World ID is verified at the PoP server (existing adapter design; Portal v4 `/verify`; distinct nullifiers). No World ID data goes onchain next to the transfer, since that would link the parties (`mobile-wallet.md` §5 agrees).
- **Onchain option (prize story, "IDKit in an onchain flow"):** gate `deposit` with `WorldIDVerifier.verify`:
  - `signal = 0x ‖ abi.encodePacked(address(pool), precommitment)`, so a front-runner can't steal the proof;
  - `action = "pool-deposit:" + hex(precommitment)` or any per-deposit string. Nullifiers are one-time per (rp, action), so a fixed action allows one deposit per human, ever.
  - Store `usedNullifier`, and only then insert the label into the ASP tree.

  The story: "only verified humans' money can move, and only between humans who met". Cost about 300k gas per deposit (bridge.md measured 288,153 for the Groth16 part). Needs the §2 `rpId`/OPRF check first. U
- **Don't** put `nullifierA/B` or `pair_tag` onchain in the same tx as the transfer.

## 5. Circuits (exact)

### 5.1 Reused unchanged

- `withdraw.circom` `Withdraw(32)` + `final-keys/withdraw.zkey` + `WithdrawalVerifier.sol` (the payee's cash-out, and the payer's own withdrawals).
- `commitment.circom` (ragequit; `CommitmentVerifier.sol`).

### 5.2 New: `PresenceTransfer(32, 20)` (prototype file: `$S/privacy-pools-core/packages/circuits/pres/presenceTransfer.circom`)

The payee note uses `LABEL_TRANSFER`, as below, so the unchanged withdraw circuit can find the label in the ASP tree (LeanIMT forbids leaf 0). The prototype first used label 0 and was re-run with `LABEL_TRANSFER`: still 15,243 constraints, the good input SAT, over-spend and wrong payee UNSAT. V (the §1.7 prove/gas numbers are from the label-0 build; the constraint count is identical, so they carry over)

```circom
pragma circom 2.2.0;
include "./commitment.circom";   // CommitmentHasher
include "./merkleTree.circom";   // LeanIMTInclusionProof, pulls circomlib poseidon/comparators/mux1

template PresenceTransfer(maxTreeDepth, presDepth) {
  signal input stateRoot; signal input stateTreeDepth;
  signal input presenceRoot; signal input presenceTreeDepth;
  signal input context;
  signal input label; signal input existingValue; signal input existingNullifier; signal input existingSecret;
  signal input newNullifier; signal input newSecret;
  signal input transferValue; signal input payeePrecommitment;
  signal input stateSiblings[maxTreeDepth]; signal input stateIndex;
  signal input presenceSiblings[presDepth]; signal input presenceIndex;
  signal output existingNullifierHash; signal output changeCommitment; signal output payeeCommitment;

  component inC = CommitmentHasher();
  inC.value <== existingValue; inC.label <== label; inC.nullifier <== existingNullifier; inC.secret <== existingSecret;
  existingNullifierHash <== inC.nullifierHash;
  component st = LeanIMTInclusionProof(maxTreeDepth);
  st.leaf <== inC.commitment; st.leafIndex <== stateIndex; st.siblings <== stateSiblings; st.actualDepth <== stateTreeDepth;
  stateRoot === st.out;

  signal remaining <== existingValue - transferValue;
  component r1 = Num2Bits(128); r1.in <== remaining;
  component r2 = Num2Bits(128); r2.in <== transferValue;

  component ne = IsEqual(); ne.in[0] <== existingNullifier; ne.in[1] <== newNullifier; ne.out === 0;
  component chC = CommitmentHasher();
  chC.value <== remaining; chC.label <== label; chC.nullifier <== newNullifier; chC.secret <== newSecret;
  changeCommitment <== chC.commitment;

  var LABEL_TRANSFER = 0x706f702d7472616e73666572;
  component pc = Poseidon(3);
  pc.inputs[0] <== transferValue; pc.inputs[1] <== LABEL_TRANSFER; pc.inputs[2] <== payeePrecommitment;
  payeeCommitment <== pc.out;

  var TAG_PAYER = 0x706f702d7061796572; var TAG_PRES = 0x706f702d70726573;
  component pt = Poseidon(2); pt.inputs[0] <== TAG_PAYER; pt.inputs[1] <== existingNullifier;
  component lf = Poseidon(3); lf.inputs[0] <== TAG_PRES; lf.inputs[1] <== pt.out; lf.inputs[2] <== payeeCommitment;
  component pr = LeanIMTInclusionProof(presDepth);
  pr.leaf <== lf.out; pr.leafIndex <== presenceIndex; pr.siblings <== presenceSiblings; pr.actualDepth <== presenceTreeDepth;
  presenceRoot === pr.out;

  signal contextSquared <== context * context;
}
component main {public [stateRoot, stateTreeDepth, presenceRoot, presenceTreeDepth, context]} = PresenceTransfer(32, 20);
```

- **Verifier public-signal order** (snarkjs: outputs first, then public inputs in declaration order):
  `[0] existingNullifierHash, [1] changeCommitment, [2] payeeCommitment, [3] stateRoot, [4] stateTreeDepth, [5] presenceRoot, [6] presenceTreeDepth, [7] context`. V(public.json)
- `presDepth = 20` allows 1M meetings; the LeanIMT depth is dynamic. `maxTreeDepth = 32` must match 0xbow's state tree.
- `transferValue = 0` is allowed. It would create a zero-value payee note; harmless, but the contract may reject `transferValue == 0` indirectly (it can't see it). Leave it.
- **Setup:** `snarkjs groth16 setup presenceTransfer.r1cs <ptau ≥ 2^15> t.zkey`. That is single-party, dev only; say so. Optionally add a contribution and a beacon. Export `zkey export solidityverifier` with **snarkjs 0.7.x**, rename the contract to `TransferVerifier`, and set `pragma` to 0.8.28.

### 5.3 Fallback circuit V1 (public amount, address payee)

`presenceWithdraw.circom`: 0xbow `Withdraw(32)` plus public `presenceRoot, presenceTreeDepth, recipient`, with `leaf = Poseidon(TAG_PRES, Poseidon(TAG_PAYER, existingNullifier), recipient)`.

- The payee is a fresh address (or an ERC-5564 stealth address; the announcer is live on 480).
- Hides only the payer's deposit.
- 23k constraints, 262,840 verify gas.

Use it only if the payee note flow (§7) is too much.

## 6. Contract delta (fork `PrivacyPoolSimple`, drop `Entrypoint`)

One contract, `PresencePool is State` (native ETH), deployed on 480:

```solidity
// roles
address public immutable ATTESTER;              // server hot key (secp256k1 EOA) or the bridge PresenceRegistry
ITransferVerifier public immutable TRANSFER_VERIFIER;   // new
IVerifier public immutable WITHDRAWAL_VERIFIER;         // 0xbow WithdrawalVerifier, unchanged
IVerifier public immutable RAGEQUIT_VERIFIER;           // 0xbow CommitmentVerifier, unchanged
uint256 constant LABEL_TRANSFER = 0x706f702d7472616e73666572;

// presence tree
LeanIMTData internal _presence;  uint256[64] presenceRoots; uint32 presenceRootIdx;
event PresencePosted(uint256 indexed index, uint256 leaf, uint256 root);
function postPresence(uint256 leaf) external;          // onlyAttester; _presence._insert(leaf); push root
function isKnownPresenceRoot(uint256 r) public view returns (bool);

// ASP tree, onchain, no postman
LeanIMTData internal _asp; uint256[64] aspRoots; ...
constructor: _asp._insert(LABEL_TRANSFER)
deposit(uint256 precommitment) payable -> label = keccak256(abi.encodePacked(SCOPE, ++nonce)) % p;
    commitment = PoseidonT4.hash([msg.value, label, precommitment]); _insert(commitment); _asp._insert(label);
    [optional] require WorldIDVerifier.verify(...) first (§4.4)

// transfer
struct TransferProof { uint256[2] pA; uint256[2][2] pB; uint256[2] pC; uint256[8] pubSignals; }
function transfer(TransferProof calldata p) external {
  require(p.pubSignals[7] == uint256(keccak256(abi.encode(address(this), block.chainid, "pop-transfer-v1"))) % p_);
  require(p.pubSignals[4] <= 32 && p.pubSignals[6] <= 20);
  require(_isKnownRoot(p.pubSignals[3]));            // state root history
  require(isKnownPresenceRoot(p.pubSignals[5]));
  require(TRANSFER_VERIFIER.verifyProof(p.pA, p.pB, p.pC, p.pubSignals));
  _spend(p.pubSignals[0]);
  _insert(p.pubSignals[1]);                           // change
  _insert(p.pubSignals[2]);                           // payee (LeanIMT reverts LeafAlreadyExists on a dup)
  emit Transferred(p.pubSignals[0], p.pubSignals[1], p.pubSignals[2]);
}

// withdraw: 0xbow's, with ONE change: ASPRoot must be a known ASP root (history), not == latest,
// because the ASP tree now grows on every deposit (a race otherwise).
// relay: drop Entrypoint.relay; withdraw(Withdrawal{processooor: relayer, data: abi.encode(recipient, feeRecipient, feeBPS)})
// can keep 0xbow's context rule; pay the fee inside withdraw, or set fee 0 (World Chain gas is ~free; our relayer pays).
```

- Gas (E, from the measured parts): `transfer` ≈ 242k verify + 2 LeanIMT inserts (each about 60–100k at depth ≤ 20) + nullifier SSTORE ≈ **450–500k**. `postPresence` ≈ 60–100k. `deposit` ≈ 290k (+ about 300k with World ID). On 480 each is well under $0.01.
- Keep `ragequit` so a stuck depositor can always exit. It needs `depositors[label]`, so it doesn't work for payee notes (their label isn't a deposit); payees exit via `withdraw`.
- Remove `Entrypoint`, vetting fees, `windDown`, upgradeability and `BatchRelayer`. `Constants.SNARK_SCALAR_FIELD` stays.

## 7. Client work (the real schedule risk)

The payer needs: note secrets storage, a state-tree mirror (from `LeafInserted` events), a presence-tree mirror (`PresencePosted`), the ASP tree (for Q's withdraw), witness generation and a Groth16 BN254 prove. 0xbow's `packages/sdk` (TS) has the tree and proof plumbing. V(repo layout; API not read in depth)

Options, fastest first:

1. **Laptop wallet (TS, node, snarkjs + `@zk-kit/lean-imt` + `poseidon-lite` + viem).** It holds P's and Q's notes and proves in about 3 s. The phones stay the presence and World ID devices. Lowest risk, and the demo is honest if stated.
2. **Server-side proving: NO.** The server would learn note secrets and link everything.
3. **Native, in the KMP app.** `app/prover` already depends on mopro `witnesscalc_adapter` (circom C++ witness). Adding mopro `circom-prover` (arkworks or rapidsnark backend) for BN254 Groth16 is the natural path. It's a second native prover build for Android and iOS, and `mobile-wallet.md` flags the iOS memory/free-team risk. The zkey is 8.6 MB and the circuit 15k constraints, far smaller than option A (470 MB pk, 1.9 GB peak), so memory isn't the problem; build time is. U
4. WebView/snarkjs inside the app: works in principle; 5–15 s (E).

A Mini App is a poor fit: deposits via MiniKit come from the user's public World App Safe (fine for deposits only), every contract must be allowlisted, and mainnet only (§1.6).

## 8. Implications for the SAFE idea

- **SAFE doesn't need any of this.** Owners' identities are public in a Safe anyway, so presence can be a plain onchain check (a guard reads the `PresenceRegistry` entry for the `safeTxHash`). No circuit, no note sync, no second prover. SAFE is strictly cheaper on the client.
- **Shared pieces with POOL (build them once):**
  - the attester and `PresenceRegistry` on **480** (World ID v4 onchain only exists there);
  - `ctx_hash` session binding (`bridge.md` §4): for SAFE `ctx_hash = safeTxHash`, for POOL `keccak256(abi.encode("pool-xfer-v1", pool, presenceLeaf))`;
  - the relayer EOA.
- If SAFE is chosen, the privacy work here becomes a stretch "private payout from the Safe": the Safe deposits into `PresencePool`, and payouts go out through presence tickets.
- Gas and chain facts from §1.6 (480, gas price, allowlisting for Mini Apps) apply equally.

## 9. Implications for the POOL idea

- It's feasible in a day **for contracts plus circuit** (fork plus about 150 lines of Solidity plus one 15k-constraint circuit that already exists in prototype). It's **not** feasible for a polished in-app wallet unless option 7.1 (laptop wallet) is accepted.
- Differentiator versus Rebind (same event, "two distinct World IDs", per `worldid-prize.md`): **physical co-presence plus amount/party privacy.** The demo should show the failure path: the same payment attempted from 2 m away → no leaf → proof generation fails (UNSAT), and the transfer is impossible.
- It must be pitched as "0xbow Privacy Pools fork + presence-gated shielded transfer", not "Railgun-like". Railgun's code can't legally be reused.
- Minimum demo script:
  1. P deposits 0.001 ETH.
  2. Q shows a request.
  3. Phones meet (World ID ×2 + audio).
  4. The leaf is posted.
  5. P's transfer is relayed, and the explorer shows no amount or addresses.
  6. Q withdraws to a fresh address.
  7. Failure run: phones far apart → no leaf → the transfer can't be proven.

## 10. Open questions

1. **Who holds notes and proves: the laptop wallet (7.1) or the in-app native prover (7.3)?** It decides whether POOL fits the remaining time.
2. **Is `postPresence` called by a server EOA directly, or through the shared `PresenceRegistry` (`bridge.md` tier 1/2)?** It affects the server API (owned by the other workflow): a new signed endpoint for per-role app payloads (`payerTag` / `payeeCommitment`), and `context` on `POST /v1/session`.
3. **Channel for `{value, payeePre}` from Q to P:** via the server in clear (MVP), or QR/NFC, or ECIES to P's device key?
4. **Onchain World ID at deposit: yes or no?** First check that our `rpId` has an OPRF key on 480 (§2) and whether staging proofs (simulator) verify against `0x703a…`.
5. **Asset:** native ETH (simplest; `PrivacyPoolSimple`) or USDC `0x79A0…24d1` (needs `PrivacyPoolComplex` and approve/Permit2)?
6. **Trusted setup for `PresenceTransfer`:** a single-party dev setup is acceptable for the demo? (Recommended: yes, say it in the README.)
7. **Mainnet 480 only** (World ID v4 onchain, ERC-5564) versus 4801 for a no-World-ID-onchain build: which? The pool itself works on either; 4801 lacks `WorldIDVerifier` v4 and the 5564 announcer.
8. Do we care about the 2 failing 0xbow unit suites? (Probably not; check before claiming "all tests pass".)

## Sources

- https://github.com/0xbow-io/privacy-pools-core (commit d494b63, cloned)
- https://github.com/Railgun-Privacy/circuits-v2, https://github.com/Railgun-Privacy/contract (cloned; license files)
- https://docs.railgun.org/developer-guide/wallet/getting-started, https://docs.railgun.org/wiki/assurance/private-proofs-of-innocence
- https://github.com/tornadocash/tornado-nova (cloned)
- https://docs.world.org/world-id/idkit/onchain-verification, https://docs.world.org/world-id/reference/contracts, https://github.com/worldcoin/world-id-protocol (cloned, `contracts/src/core/WorldIDVerifier.sol`)
- https://docs.world.org/mini-apps/commands/send-transaction
- https://docs.semaphore.pse.dev/deployed-contracts
- https://eips.ethereum.org/EIPS/eip-5564
- https://docs.zama.org/protocol/protocol/overview, https://docs.openzeppelin.com/confidential-contracts/token, https://www.zama.org/post/erc-7984-the-confidential-token-standard-explained
- https://www.fhenix.io/blog/unlocking-encrypted-computation-on-arbitrum-cofhe-is-live-on-testnet-4
- https://blog.zkbob.com/polygon-sunsets-january-31-2025/
- https://github.com/EYBlockchain/nightfall_4_CE
- https://privacy.eth.sh/ (Privacy Pools chain counts)
- https://www.coindesk.com/policy/2025/03/21/u-s-government-removes-tornado-cash-sanctions
- https://ethglobal.com/events/tokyo2026/prizes/world (World tracks: Best Use of IDKit, World ID for Agents)
- cast against `https://worldchain-mainnet.g.alchemy.com/public` (480) and `https://worldchain-sepolia.g.alchemy.com/public` (4801)
