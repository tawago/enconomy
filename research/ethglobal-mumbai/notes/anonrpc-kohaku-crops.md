# Anon-RPC, Kohaku, CROPS, Walletbeat

Checked 2026-11-02.
Sources read: the live pages, plus local reads of three repos.
anon-rpc is at commit c8980fb (2026-10-24).
kohaku is at adfcb46 (2026-10-31).
walletbeat is at 5bcbc3d (2026-11-01).
No third-party code was run.
The only network calls were read-only `eth_getCode` lookups against public RPCs.

## 1. Anon-RPC

### What it is

- It is a standard plus a reference implementation, not a hosted service. VERIFIED.
  - From the README: "lets a wallet or application make anonymized RPC requests by running hash-pinned client code inside a sandboxed worker".
  - https://github.com/ethereum/anon-rpc
- Mechanism, step by step. VERIFIED, from `docs/integrate-wallet.md` and `SPEC.md`.
  1. An on-chain "specifier" contract stores `workerHash()` (keccak256 of a JS bundle) and `workerResolvers()` (URLs or `kps:` locations).
  2. The harness reads the specifier once through a bootstrap RPC. This one read is not anonymized.
  3. The harness downloads the bundle and runs it only if its keccak256 matches. The doc says: "The hash is the trust; the URLs are merely suggestions".
  4. The bundle runs in a Web Worker inside a null-origin sandboxed iframe. It cannot touch the DOM, cookies or keys. It gets a small capability API: inbound fetch calls, the KPS transport, storage scoped to its specifier, and logging.
  5. The worker does the anonymizing itself, over Tor, Nym, a Sphinx mixnet and so on. Anon-RPC has no anonymity technique of its own. It is a plug-in slot for networks.
  6. KPS means key-pinned streams. Peers are identified by certificate hash, with no CA and no domain. Browsers use WebRTC. The spec has native harnesses use QUIC (SPEC §10). https://ethereum.github.io/kps/
- What the host gets back is a normal `fetch`. `worker.fetch` can be passed straight into a viem custom transport or an ethers getUrl hook. VERIFIED (integrate-wallet.md).
- Per-call `anonOptions.isolationKey`, added in spec 0.4.0 (2026-10-23), asks the network to keep calls made under different keys unlinkable, for example one key per account. Whether a key is honored depends on the network. VERIFIED (CHANGELOG.md).

### Trust model and limits

All VERIFIED from integrate-wallet.md, "The trust model, honestly":

- You trust whoever controls the specifier contract. The owner can ship new versions or renounce to freeze the hash.
- The bootstrap RPC is trusted for one read. If it lies, it can point you at different code.
- The worker sees every request, "including signed transactions before broadcast". It can observe, censor or lie. The sandbox shrinks the blast radius but does not remove the need for trust.
- Recap claim "Tx senders remain visible regardless": VERIFIED, with a nuance. Anon-RPC can carry `eth_sendRawTransaction` and hide the IP, but the sender address is still public on-chain. It hides who reads, not what goes on-chain.
- The Kohaku `anon` provider adapter has no confidentiality toward the destination RPC, which sees the requests in full. The Nox worker runs TLS inside the worker, so its exit node relays without reading. VERIFIED (adopters.json5).

### How an app routes reads through it by default

The prize rule is "Your app routes its RPC reads through Anon-RPC by default." VERIFIED, quoted from https://ethglobal.com/events/mumbai/prizes, which is still marked "(tbc: final review pending)".

Minimal browser path. VERIFIED from integrate-wallet.md and the Kohaku provider source.

```ts
import { AnonRpcWorker } from "@anon-rpc/browser-harness"; // npm 0.4.0, published 2026-10-28
const worker = new AnonRpcWorker({
  address: "0x700dA3193D35fA54Cd3fBf29B66f2a2A0385659e", // tor-js specifier, mainnet
  config: { gateways: ["152.236.3.22:12298:uEiCH0VdbhryzJcMtCfB0vLA4sOvHdQ4hq5w7CopcwU59bQ"] },
  preExisting: { rpcProvider: bootstrapEip1193 }, // one non-anonymous read
});
// viem: http transport with fetchFn: worker.fetch, or custom({ request }) wrapping worker.fetch
```

Rules of thumb from the guide:

- Keep one long-lived worker per network.
- Calls made before `ready` are buffered.
- `close()` tears everything down.

Kohaku packages the same thing as `anon({ specifier, rpcUrl, workerConfig, bootstrap })` in `@kohaku-eth/provider/anon` (npm 0.1.0-alpha.14). It adds a 120 s boot timeout and receipt polling of 4 s / 5 min. VERIFIED (packages/provider/src/anon/index.ts, docs/pages/provider.mdx).

"By default" means booting the anon worker at app start and pointing every read at it. A settings toggle does not count. Both current adopters are opt-in toggles, so they would not meet the prize wording:

- Privacy Pools: "Off by default".
- Kiwi News: "when readers turn on the anon-rpc switch".

VERIFIED (adopters.json5). Being on by default is a real way to stand out.

### Maturity

- Spec version 0.4.0 (2026-10-23). There have been 7 versions since 0.1.0 (2026-06-24), and several were breaking. VERIFIED (CHANGELOG.md).
- `@anon-rpc/browser-harness` 0.4.0 is on npm. VERIFIED (`npm view`).
- There is no native harness:
  - `node-harness` is a QuickJS prototype, "Not yet a conforming harness", and is not on npm (`npm view` returns 404). VERIFIED.
  - There is no Android or iOS harness. The guide says "Browser-only ... A native harness would be a separate package." VERIFIED.
  - The repo also has `impl/browser-extension-harness`, an MV3 extension harness. VERIFIED (directory listing).
- Live networks, from adopters.json5. VERIFIED.

| id | kind | specifier | chain | notes |
| --- | --- | --- | --- | --- |
| passthrough | reference | 0x4fd77be300f31c5fe6ab266d35d27750a3478d27 | mainnet | plain fetch, no anonymity |
| tor-js | network | 0x700dA3193D35fA54Cd3fBf29B66f2a2A0385659e | mainnet | Tor in WASM. Demo gateway "may disappear at any time — run your own". Bootstrap delay. |
| nym | network | 0x3aCD9742C68F6d993066Ae25533e09b9e1f60eD0 | mainnet | ~18 MB bundle, a few seconds to bootstrap |
| nox | network | 0x35133267A8F7EC35046a83DCA0f4Ca8A6e1b7A9A | Sepolia | Sphinx mixnet, TLS inside the worker |

- I checked that all four specifier addresses have contract code (3655 bytes each), using `eth_getCode` on publicnode mainnet and Sepolia. VERIFIED, read-only.
- The adopters list has two apps: Privacy Pools (tor-js) and Kiwi News (tor-js). No wallets are listed. VERIFIED.
- No audit is mentioned anywhere in the repo or on the site. VERIFIED that it is absent from the pages read.
- The tor gateway hard-coded in Kohaku's `examples/anon-rpc-poc/src/main.ts` (170.64.236.147) differs from the one in adopters.json5 (152.236.3.22). Gateways change, so check the current one on hack day. VERIFIED (both files).
- Kohaku code still links `github.com/privacy-ethereum/anon-rpc`. The canonical repo is now `github.com/ethereum/anon-rpc`. VERIFIED (provider/src/anon/index.ts line 36).
- The prize also accepts "produces anonymity via a new Anon-RPC worker". For that, a simple demo app is enough. Ideas listed on the prize page: "portfolio dashboard", "block explorer", "network health checker / playground". VERIFIED (prizes page).

## 2. Kohaku SDK

From the README at https://github.com/ethereum/kohaku: "Privacy-first js tooling for the Ethereum ecosystem". It warns "NOT READY FOR PRODUCTION USE ... UNAUDITED CODE". There is a sister Rust repo, ethereum/kohaku-rs. VERIFIED.

| package | README status | repo version | what |
| --- | --- | --- | --- |
| @kohaku-eth/privacy-pools | OK | 0.1.0-alpha.36 | Privacy Pools shielded-pool lib |
| @kohaku-eth/tornado-cash | OK | 0.1.0-alpha.33 | Tornado lib |
| @kohaku-eth/railgun | WIP, "under maintenance" | 0.0.1-alpha.31 | Railgun lib |
| @kohaku-eth/plugins | OK | 0.0.1-alpha.20 | one plugin interface for shielded pools |
| @kohaku-eth/provider | OK | 0.1.0-alpha.14 | adapters: ethers, viem, Helios, Colibri (verified light clients), and `anon` (Anon-RPC) |
| @kohaku-eth/social-recovery | WIP, "interfaces only" | 0.0.1-alpha.1 (npm shows 0.0.0) | social recovery SDK for the "recovery kit" contracts |
| @kohaku-eth/pq-account | OK | n/a | post-quantum ERC-4337 account |
| also | | | mimc-tree, poseidon, poseidon-lean-imt |

All VERIFIED from the README and package.json files.

Notes on social recovery:

- The package "holds no signer and sends no transaction". Every write comes back as a prepared call. VERIFIED (README).
- Recovery methods exist in the source tree:
  - `method-passkey`: a WebAuthn P-256 assertion, with low-s normalization.
  - `method-ecdsa`.
  - `method-zkpassport`.
  - `method-aadhaar`, an optional peer dependency on `@anon-aadhaar/core`.
- So the source is ahead of the README's "interfaces only" line. VERIFIED (directory listing at adfcb46). I did not check whether the clients and orchestrator are complete.
- The recovery-kit contracts are not in this repo, and I did not find their address or repo. UNREACHABLE.

The `pq-account` package fits the recap's alt-mempool and PQ angle.

## 3. CROPS, from the EF Mandate

The blog post (2026-03-13, by the EF Board) has only one line: "Ethereum must, above all, remain censorship resistant, open source, private, and secure (CROPS)." VERIFIED. https://blog.ethereum.org/2026/03/13/ef-mandate

Per-letter definitions, from https://ethereum.org/foundation/mandate/ (PDF at https://ethereum.foundation/ef-mandate.pdf, not read). VERIFIED.

- **C, Censorship Resistance:** "No actor can selectively exclude valid use or break functionality, including by gaining durable, non-competitive control of any critical mechanisms." The mandate says work must be "maximally unstoppable", "without incorporating centralized intermediaries or kill switches".
- **O, Open Source and Free, as in Freedom:** "No privileged code or hidden specifications." "All work must be public and auditable: no proprietary 'black boxes.'" "All work must also be forkable."
- **P, Privacy:** "User data is not exposed beyond necessity or against their interests."
- **S, Security:** "Things must do what they claim to do, no more and no less."

The mandate names "wallets, RPC providers" as "partially centralized surfaces". This is the gap Anon-RPC targets. VERIFIED.

The CROPS App prize, quoted from https://ethglobal.com/events/mumbai/prizes (marked tbc). VERIFIED.

- "one CROPS property is the reason it exists, without giving up the other three". Judges say "structural (works without you) beats cosmetic (a setting)".
- The README section titled CROPS must cover what the user depends on, the license, what third parties learn, and how keys and data are protected.
- A demo video of 3 minutes max.
- No third-party trackers.
- The prize page's own example: "a wallet a user can fully recover with nothing from you: no server, API or relayer". That matches the recap's "recover wallet by meeting friends" idea.
- The CROPS Upgrade prize is Continuity Track only. Only work done at the hackathon is judged, and you need a before and after video.
- "One EF prize per project. EF judges decide where it fits best." You cannot stack Anon-RPC with CROPS. VERIFIED. The recap says the same.

## 4. Walletbeat criteria

Source: https://walletbeat.eth.limo and github.com/walletbeat/walletbeat, src/schema. VERIFIED.

There are five categories: Security, Privacy, Self-sovereignty, Transparency and Ecosystem. Hardware wallets get a sixth, Maintenance.

- **Privacy:** address correlation ("Is your wallet address linkable to other information about yourself?"), multi-address correlation, app isolation, privacy hygiene, private token transfers, hardware privacy.
- **Security:** account recovery, duress resistance, passkey implementation, scam prevention, audits and bounties, security best practices, transaction legibility, user safety, plus the hardware items (firmware, supply chain, HW wallet support).
- **Self-sovereignty:** account portability, account unruggability, chain verification (light client such as Helios), L1 provider independence, permissions management, transaction inclusion.
- **Transparency:** source code license, funding, fee transparency, orderflow transparency, release process, reputation.
- **Ecosystem:** account abstraction, address resolution (ENS), browser integration, chain abstraction, HW interop, transaction batching.

Where RPC privacy shows up:

- Address correlation gets a PARTIAL rating if "The wallet allows an external provider to learn the relationship between a user's wallet address and their IP address by default".
- A PASS requires that it "proxies all network requests carrying the user's wallet address".
- The suggested fix names "Oblivious HTTP, Tor, or other similar techniques".
- Source: privacy/address-correlation.ts.

Stages: Stage 0 → 0.5 → 1 → 2 (src/schema/stages/software-wallet-stages.ts).

- Stage 1 privacy criteria:
  - "Token transfers and balances must be private by default."
  - "Wallet addresses must not be linkable to sensitive personal information."
  - "Multiple wallet addresses must not be correlatable with one another."
- Stage 2 criteria:
  - "Wallet addresses must not be correlatable with any user information, including IP address."
  - "The wallet must verify the integrity of the Ethereum chain."
  - "The wallet must offer app-specific accounts by default when connecting to apps."

Anon-RPC by default, with one isolationKey per address, targets exactly the IP and multi-address criteria. VERIFIED, by reading the criteria text against the anon-rpc spec. This is my mapping, not Walletbeat's own claim.

## 5. What this means for the enconomy build

Decisions recorded, made without the user:

- **Anon-RPC is browser-only today, so only the Kotlin/Wasm web app (webapp.enconomy.dev) can use it.**
  - The Android and iOS apps have no harness. Building a native harness is a hackathon-sized project by itself.
  - For the phones, a WebView with a null-origin iframe and WebRTC might work. That is UNTESTED.
  - Decision: if we target Anon-RPC, do it in the web app through JS interop with `@anon-rpc/browser-harness`.
- **On by default is the key to the prize, and nobody listed ships it.** Use tor-js or Nym on mainnet reads. Use Nox when the reads go to Sepolia, which is the ENS/Safe chain enconomy uses.
  - The specifier's chain is not the target chain. Any worker can fetch any RPC URL.
  - We should run our own Tor gateway rather than rely on the demo gateway.
- **One EF prize per project.** Anon-RPC ($5k pool, $2.5k first) and CROPS App ($3.5k pool, $2k first) are mutually exclusive. Anon-RPC also costs nothing extra if the recovery or CROPS app is browser-based. Even so, judges pick only one prize.
- **Recovery angle and Kohaku:**
  - `@kohaku-eth/social-recovery` already has a passkey (P-256) method and an Anon Aadhaar method, which fits an India venue.
  - enconomy's hardware P-256 keys and proximity proofs could become a new `IRecoveryMethod` ("met in person").
  - That gives a structural C and P lead for CROPS, and matches the prize example word for word.
  - Risk: the recovery-kit contracts were not found, and the SDK is alpha.
- **Writing the CROPS README is cheap:** list dependencies (the World ID app, Sepolia RPC, the anon network), the license, what each third party learns, and the key handling (secure enclave P-256).

## Open items

- Find the recovery-kit contracts (repo and Sepolia addresses). UNREACHABLE so far.
- Check that the Tor and Nox gateways are live on Nov 5. Expect a boot delay of several seconds or more.
- Confirm the final prize text, since the page says "tbc: final review pending".
