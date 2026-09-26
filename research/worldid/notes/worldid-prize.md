# World prize at ETHGlobal: what we are actually competing for

Researched 2026-09-26 ~15:40–16:30 JST. Tags: **VERIFIED(source)** means I read it at that source or ran the command. **UNVERIFIED** means inferred or not found.

## TL;DR

1. **The event is ETHGlobal Tokyo 2026 (Sep 25–27), and submissions close Sun 2026-09-27 09:00 JST.** At the time of writing (Sat 15:40 JST) that is about 17 hours away. Anything in the design doc that can't be built and filmed tonight will not count at this event. The next ETHGlobal event with a World prize is Mumbai (Nov 5–7, $20k from World, details not published yet).
2. World's Tokyo prizes: **Best Use of IDKit** ($5k, up to 2 × $2.5k), **Best Use of World ID for Agents** ($5k, 2 × $2.5k), and Continuity-only versions of both ($2.5k each).
3. **No Mini App, World Chain or onchain verification is required.** Server verification through the Developer Portal is explicitly allowed. What is judged: one real "trust moment", the minimum sufficient credential and why, a success path plus one failure path, and a written integration debrief.
4. **The biggest risk is eligibility, not tech.** The repo's first commit (2026-09-26 02:52 JST) is a 151-file, 50,783-line import of research prototypes that existed before the event. `~/dev/worldid-spike` (IDKit 4 spike, Sep 24) also predates it. ETHGlobal rules: on the Classic track, pre-existing project-specific work makes you **ineligible for partner prizes and finalists**, and undisclosed pre-existing work can mean disqualification and a ban. Before anything else, find out which track the team registered for.
5. Technical facts that change the design:
   - The v4 onchain verifier exists **only on World Chain mainnet** (production and staging proxies). There is nothing on World Chain Sepolia (checked with `eth_getCode`).
   - As of 2026-09-25, the production Portal **rejects simulator/staging proofs** unless the team opens a 24 h staging window and sends a token header.
   - Actions are **auto-created on first verify**, so a per-session `pop:<sid>` works.
   - The Portal **does not reject a reused nullifier** (it returns success with `nullifier_reused`), so our server has to reject it.
   - Kotlin IDKit 4 is **not on Maven Central**.

---

## Verified facts

### A. Which event

| Event | Dates | World prize | Status | Source |
|---|---|---|---|---|
| **ETHGlobal Tokyo 2026** | Sep 25–27, 2026. Submissions due **2026-09-27T00:00Z = 09:00 JST** | $15,000 | happening now | VERIFIED(https://ethglobal.com/events/tokyo2026/info/details; `submissionDeadline":"2026-09-27T00:00:35Z"` in page JSON) |
| ETHGlobal Mumbai | Nov 5–7, 2026. Submissions due 2026-11-08T03:30Z | $20,000, "Prize details coming soon" | upcoming | VERIFIED(https://ethglobal.com/events/mumbai/prizes, page JSON startTime/endTime) |
| ETHOnline 2026 (async) | Sep 4–16, 2026 | $7,000 | over | VERIFIED(https://ethglobal.com/events/ethonline2026/prizes page JSON) |

Why Tokyo:
- It is the only event running today.
- The repo's commits are all 2026-09-26 JST.
- The memory notes say "2026-09-26 hackathon build".
- 2026 calendar: Cannes Apr 3–5, NYC Jun 12–14, Lisbon Jul 24–26, Tokyo Sep 25–27, Mumbai Q4. VERIFIED(https://x.com/ETHGlobal/status/1992919708589576215, search snippet)

Tokyo schedule (UTC → JST):
- World workshop "World's latest products (IDP vs IDKit)": Fri Sep 25 17:30 JST, 5F.
- Submissions due: Sun 09:00 JST.
- Partner judging: 09:30.
- Finalist judging: 09:30, 4F.
- Finalists notified: 15:15.
- Closing: 15:30.

VERIFIED(page JSON in https://ethglobal.com/events/tokyo2026/prizes). The exact hacking-start time is UNVERIFIED (not in the schedule JSON; likely Fri Sep 25 evening JST).

Total Tokyo prize pool: $52,500. Sponsors: World $15k, ENS $10k, Uniswap $10k, 1inch $7k, Sui $5k, Curvegrid $3k, Intercepta $2.5k. VERIFIED(tokyo2026/prizes)

### B. World's Tokyo prizes (verbatim essentials)

Source for all of B: VERIFIED(https://ethglobal.com/events/tokyo2026/prizes, fetched with curl and stripped)

**🪪 Best Use of IDKit: $5,000, up to 2 teams × $2,500**

> Build a product that uses IDKit to solve a real trust moment: an event where a product needs to know something meaningful about a person before it grants access, completes an action, or changes a user's experience.
> Use the credential that is proportionate to your use case—such as Proof of Human, Passport/NFC, or Selfie Check (Now live with Sybil score). We are not rewarding the most credentials used. We are rewarding the best decision about which credential is needed, why it is needed, and how it improves a real product experience.
> Strong examples could include fair access to a scarce benefit, a privacy-preserving eligibility check, recovery or protection of an important account action, or a workflow that becomes safer or simpler because it can verify the right level of human trust.

Qualification requirements:
1. Integrate IDKit in a functioning application, mini app, or onchain flow.
2. Use at least one supported World ID credential and verify the result on the server or onchain as appropriate.
3. Clearly explain the specific product event requiring trust and why the chosen credential is the minimum sufficient assurance.
4. Demonstrate a successful verification and one meaningful alternative path, such as cancellation, unavailable credential, rejection, or an ineligible user.
5. Include a short integration debrief/feedback: time to first success, friction encountered, missing capability or documentation, and the one improvement with the greatest impact.

Links: docs.world.org/world-id/idkit/integrate, /idkit/credentials, /credentials/1 (PoH), /credentials/9303 (Passport/NFC), /credentials/11 (Selfie Check Beta), /idkit/verification-flows, developer.worldcoin.org, idkit-js-example.vercel.app.

**🤖 Best Use of World ID for Agents: $5,000, up to 2 teams × $2,500**

> ![We are mocking proofs now, so you don't need sandbox app anymore]!
> Build an application using World ID for Agents. We are especially interested in agentic products, but any compelling use case is eligible. Show what becomes possible when an application can ask a person to authenticate or complete a fresh verification at the moment. Strong submissions will show a meaningful action that needs a human identity or approval layer, not simply a login screen added to an existing product.

Requirements:
1. Integrate with the official World ID for Agents dev environment provided for the event.
2. Demonstrate the full journey: request → user completion → validated result → protected action.
3. Demonstrate a denied, expired, cancelled or otherwise unsuccessful path where the protected action does not occur.
4. Validate results in a secure backend; don't expose client secrets or treat an unvalidated client response as authorization.
5. Include an integration debrief (same four items as IDKit).

Links: http://sandbox.auth.world.org/docs, https://github.com/worldcoin/world-id-agent-plugin, http://sandbox.auth.world.org/portal.

**🎉 [Cont] Best IDKit Use Case: $2,500** and **🎉 Best Use of World ID for Agents (Continuity): $2,500**
- "This prize is only available to Continuity Track participants."
- The requirements are the same as the Classic versions. The Agents one adds: "Proofs are using fake identities, DO NOT rely in them for production".

Other World resources listed: Simulator https://simulator.worldcoin.org/id/0x18310f83, iOS Sandbox app TestFlight https://testflight.apple.com/join/Tub7zuyD.

**Answers to the task's direct questions**

| Question | Answer | Basis |
|---|---|---|
| Must it be a Mini App? | **No.** "functioning application, mini app, or onchain flow" | VERIFIED(prize text) |
| Must it deploy on World Chain? | **No.** World Chain is not mentioned in any Tokyo World prize | VERIFIED(prize text) |
| Onchain vs cloud verification? | **Either.** "verify the result on the server or onchain as appropriate" | VERIFIED(prize text) |
| Bonus for World ID for Agents / a specific SDK? | It is a separate $5k track, not a bonus. The IDKit track rewards credential *choice*, not the number of credentials | VERIFIED(prize text) |
| How many partner prizes can we pick? | Up to 3 partners. "If a partner has multiple tracks, you can be eligible for all of them while only counting as 1 Partner Prize." | VERIFIED(tokyo2026/info/details) |
| Do we have to present at the World booth? | No. "partners will evaluate submissions based on the materials you provide." A booth visit is optional | VERIFIED(tokyo2026/info/details) |

### C. ETHGlobal rules that bind us

VERIFIED(https://ethglobal.com/events/tokyo2026/info/details, https://ethglobal.com/events/tokyo2026/info/start, https://ethglobal.com/rules):

**Classic "From Scratch" track**
- "all work on your project must begin after the hackathon officially starts. Any prior project-specific code, designs, or assets are not allowed unless they're from public libraries or starter kits."
- "Projects built before the event may still participate but won't qualify for partner prizes or the Finalist category."

**Continuity tracks** ("Extend Open Source" / "Ship a Feature")
- May build on an existing codebase.
- "must clearly document what work existed before the hackathon and must include substantive new features … developed during the event."
- "All new parts of extending an existing project must remain open source."

**All tracks**
- "you must disclose any pre-existing work in writing to the ETHGlobal team and include full details in your submission (repo history, video, and description). If … a submission contains undisclosed pre-existing work or materially misrepresents what was built during the hackathon, the project may be disqualified, prizes revoked, and the team may be banned from future events."
- Version control: "Any repositories with single commits of large files without proper history will be default assumed to be unqualified unless proven otherwise."

**AI tools**
- Allowed, but attribution is required: document where and how AI was used, per file or part.
- "Submissions that rely entirely on AI without meaningful contributions from team members may not be eligible for partner prizes or finalist consideration."
- Spec-driven workflows: "you must include all spec files, prompts, and planning artifacts in your submission repository." This design doc and the research notes count and should be in the repo.

**Demo video** (optional but strongly encouraged)
- 2–4 minutes, at least 720p.
- Not sped up.
- Not recorded on a mobile phone.
- **No text-to-speech or AI voiceover.**
- No "music with text instead of talking".

**Finalist judging**
- 4 min demo + 3 min Q&A.
- Criteria: Technicality, Originality, Practicality, Usability, WOW.

### D. Pre-existing work in this repo (facts for disclosure)

VERIFIED(`git log` in /Users/takahiro_ogawa/dev/enconomy; `ls -la ~/dev/worldid-spike`):

- `c9c36f6 2026-09-26 02:52 +0900 Initial commit: research prototypes and docs`: 151 files, +50,783 lines. Contents: research/sound-bound, proximity-echo, fuzzy-commitment, ZK spikes. Memory notes date this work to 2026-09-22…25, before kickoff.
- Everything after that (from 03:23 JST): the app/, server/, contract, iOS/Android and ZK integration commits are on 2026-09-26, during the event. It is incremental history (~28 commits).
- `~/dev/worldid-spike` (files dated 2026-09-24): FastAPI RP signer + Portal v4 verify proxy + KMP Android IDKit 4.0.7 spike. It is pre-existing too. If we reuse its code (for example the Python `signRequest` port with parity tests), disclose it.

Honest framing that fits the rules:
- **"Research and feasibility prototypes (acoustic ranging, circuit spikes, World ID spike) predate the event. The product was built during the event: app, server, contract, ZK integration, World ID integration and the SAFE/POOL product."**
- Submit on the Continuity track if at all possible.
- Put a `PRE-EXISTING.md`-style section in the README listing the pre-event paths and the first-commit hash.
- Tell ETHGlobal staff in writing (Discord or email), as the rules require.

### E. World ID 4.0 / IDKit facts needed for the design

All VERIFIED at the cited docs page (fetched as `.md` from docs.world.org) unless marked.

**Packages (VERIFIED: npm registry, GitHub API, Maven Central, on 2026-09-26)**

| Package | Version / status |
|---|---|
| `@worldcoin/idkit-core` | 4.3.0 |
| `@worldcoin/idkit` (React) | 4.3.0 |
| `@worldcoin/idkit-server` | 1.1.1 |
| `@worldcoin/minikit-js` | 2.0.3 |
| idkit-swift | 4.0.11 (2026-08-09) |
| Kotlin `com.worldcoin:idkit` | **Not on Maven Central.** `repo1.maven.org/maven2/com/worldcoin/idkit/` → 404; only legacy `idkit-kotlin` 3.x exists. Get it from GitHub Packages (needs a `read:packages` token) or build from source. The spike README documents both routes. |

**Flow** (https://docs.world.org/world-id/idkit/integrate)
1. The backend signs an RP context with `signing_key`.
   - Algorithm: EIP-191 secp256k1 over `0x01 ‖ nonce32 ‖ created_at_u64be ‖ expires_at_u64be ‖ hash_to_field(action)`.
   - `hash_to_field(x) = keccak256(x) >> 8`.
   - Default TTL 300 s.
   - Test vectors: https://docs.world.org/world-id/idkit/signatures. The spike already has a parity-tested Python port.
2. The client calls `IDKit.request({app_id, action, rp_context, allow_legacy_proofs, environment, return_to}).preset(proofOfHuman({signal}))` → `connectorURI` → `pollUntilCompletion()`.
3. The backend forwards the result **verbatim** to `POST https://developer.world.org/api/v4/verify/{rp_id}`.
   - Check that `environment` is what you expect.
   - Store the nullifier as `NUMERIC(78,0)` with `UNIQUE(nullifier, action)`.

**v4 uniqueness response fields**
- `protocol_version:"4.0"`, `nonce`, `action`, `environment`.
- `responses[]`: `{identifier:"proof_of_human", signal_hash, proof:[5], nullifier, issuer_schema_id:1, expires_at_min}`.

**Session proofs** (https://docs.world.org/world-id/idkit/session-proofs)
- `IDKit.createSession(...)`, no action.
- Returns a stable `session_id` plus a per-proof `session_nullifier:[nullifier, action]`.
- Rule of thumb from the 4.0 migration guide: "use `nullifier` for one-time uniqueness and `session_id` for continuity."
- In 4.0, nullifiers are one-time-use (for replay), and `session_id` is the stable link.

**Credentials** (https://docs.world.org/world-id/idkit/credentials)

| Preset | Credential |
|---|---|
| `proofOfHuman` | Orb, issuer_schema_id 1 (with legacy Orb fallback) |
| `passport` | NFC, 9303 |
| `selfieCheck` | 11, medium assurance. "Anyone with World ID App can complete the flow—no Orb or document credential is required." Returns `sybil_score` + `integrity_bundle` |
| `identityCheck` | preview, contact World |

Also `require_user_presence` (liveness) can be added to any preset.

**Dynamic actions work.** VERIFIED(source: worldcoin/developer-portal @ cb3305e, `web/api/v4/verify/uniqueness-proof/handler.ts` L191–203: "If action doesn't exist, create it"). This matches the earlier spike result recorded in docs/pop-human-adapters.md.

**The Portal does not reject reused nullifiers.**
- It returns 200 with `"Proof verified successfully (nullifier reuse)"` / `nullifier_reused: true`.
- VERIFIED(same handler.ts L223–276; also observed in the worldid-spike backend README). **Our server must enforce uniqueness.**

**Staging/simulator proofs are gated on production.**
- Commit `fix(verify): bind v4 verification environment to the app (H1 #3989287) (#2307)`, 2026-09-25T15:21Z.
- On a non-staging Portal deployment, `environment:"staging"` (or `"sandbox"`) now requires two things:
  1. a staging window opened by the app team via the Developer Portal MCP tool `set_world_id_staging_verification` (24 h window);
  2. the header `x-staging-verification-token`.
- Otherwise the Portal returns 403 `environment` not allowed.
- VERIFIED(`web/api/v4/verify/staging-access.ts`, `index.ts` L176–204). Whether this is already deployed to developer.world.org is UNVERIFIED (it merged about 1 day ago).

**Onchain v4 verification** (https://docs.world.org/world-id/idkit/onchain-verification)
- Signature: `IWorldIDVerifier.verify(uint256 nullifier, uint256 action, uint64 rpId, uint256 nonce, uint256 signalHash, uint64 expiresAtMin, uint64 issuerSchemaId, uint256 credentialGenesisIssuedAtMin, uint256[5] proof) view`
- `action = uint256(keccak256(bytes(action))) >> 8`.

| Deployment | Address |
|---|---|
| World Chain production | `0x00000000009E00F9FE82CfeeBB4556686da094d7` |
| World Chain staging | `0x703a6316c975DEabF30b637c155edD53e24657DB` |
| Arc | `0x304E14e4dC0508C0927e3b307a2C18422C07E394` |

VERIFIED(`eth_getCode`): both World Chain proxies have code on **mainnet (480)** and **none on World Chain Sepolia (4801)**. A v4 onchain verify in a demo means World Chain *mainnet* (real ETH for gas).

Legacy v3 `WorldIDRouter.verifyProof(root, groupId=1, signalHash, nullifierHash, externalNullifierHash, uint256[8])`:

| Chain | Address |
|---|---|
| World Chain mainnet | `0x17B354dD2595411ff79041f930e491A4Df39A278` |
| World Chain Sepolia | `0x57f928158C3EE7CDad1e4D8642503c4D0201f611` |

Code present at both (eth_getCode).

**Safe on World Chain**
- Canonical Safe 1.4.1 addresses have bytecode on both World Chain mainnet and Sepolia:
  - SafeL2 `0x29fcB43b46531BcA003ddC8FCB67FFE91900C762`
  - Safe `0x41675C099F32341bf84BFc5382aF534df5C7461a`
  - SafeProxyFactory `0x4e1DCf7AD4e460CfD30791CCC4F9c8a4f820ec67`
- VERIFIED(`eth_getCode` via https://worldchain-{mainnet,sepolia}.g.alchemy.com/public). Identity is inferred from the canonical addresses, not from a verified-source check.

**World ID for Agents** (the Tokyo "Agents" track)
- It is the **Human Continuity IdP**, an OIDC provider, not IDKit.
- Issuer `https://sandbox.auth.world.org`.
- Endpoints: `/api/v1/authorize`, `/api/v1/token`, `/api/v1/device_authorization`.
- Grants: `authorization_code`, `device_code`.
- Pairwise `sub`; `auth_time` for freshness; `prompt=login`; `acr` `https://world.org/oidc/acr/orb-v3`; PKCE S256; RS256 ID tokens.
- VERIFIED(https://sandbox.auth.world.org/.well-known/openid-configuration, https://sandbox.auth.world.org/docs).
- Clients are registered through the plugin's MCP (`https://sandbox.auth.world.org/mcp`, scope `developer-portal:manage`).
- It needs an HTTPS callback: "sandbox does not accept HTTP localhost callbacks". VERIFIED(world-id-agent-plugin README).
- The prize page says proofs are now mocked (no sandbox app needed).

### F. Past World winners (what wins)

VERIFIED by crawling `https://ethglobal.com/showcase?events=<ev>&page=N`, filtering for the World org logo (`organizations/3zpxc`), then reading each project page's prize badge.

**NYC 2026 (Jun)**
| Track | Winners |
|---|---|
| Track A AgentKit | 1st *Proof-of-Human* (bot-proof scarce drops, 1 human = 1 raffle slot, web + agents); 2nd *Mars*; 3rd *AgentRank* |
| Track B World ID | 1st *pinch* (robot posts bounties; humans World-ID-verify to claim and physically free the robot; Hedera payouts); 2nd *Distro* |
| Track C Continuity | 1st *Justify* |
| Track D ProveKit | *Aragorn*, *Vouch DeFi* (World ID + cloud verify + Noir/ProveKit, on Arc) |

**Cannes 2026 (Apr)**
| Track | Winners |
|---|---|
| Best use of World ID 4.0 | 1st *VEIL VPN* (also an overall top-10 finalist; "human-only servers" with World ID); 2nd *HumanAttentionToken* |
| AgentKit | *AgentGate*, *Groundtruth*, *CaaS* |
| Minikit 2.0 | *Genie*, *Joust* |

**Lisbon 2026 (Jul)**
| Track | Winners |
|---|---|
| Selfie Check Beta | 1st *BananaMesh* (BLE mesh presence data, Selfie Check liveness gates which device signal is whitelisted); 2nd *Commitment Issues* ("Face ID for git commits: agents write code, a human signs") |
| Selfie Check Continuity | *Human Bond*, *TreasureHunt* (NFC treasure hunt at real events with World ID sybil gates) |
| Identity Check Continuity | *Novi Corpus*, *NpmGuard* |
| AgentKit | *HORS*, *BookerBob*, *Turing Swap* |

**Buenos Aires (Nov 2025) and New Delhi**
- Mostly World Mini Apps (a pool prize), e.g. *Halo*, *Yield Circle*, *Token Hunt*, *marriageDAO*, *WorldBNB*.
- The prize names didn't parse on those older pages.

Patterns:
- Winners mostly **do not** deploy on World Chain (Hedera, Arc and others are common).
- Mini Apps dominated only in 2025, when World had a Mini App track.
- 2026 winners have a physical or real-world hook: robots, BLE presence, IRL events. World ID is a hard gate on a meaningful action, and they give a clear "what breaks without it".
- Human approval of a high-stakes action ("Commitment Issues") won.

**Direct competitor at this event.** *Rebind* (github.com/toorcn/Rebind, created 2026-09-26 05:16Z): "A job pool that pays only when the buyer and the worker are two different World IDs."
- An ERC-8183 hook reverts `complete()` with `SameHuman` or `Unproven`.
- Settles on World Chain Sepolia.
- Uses the sandbox (Agents) World ID.
- VERIFIED(GitHub API + README). Its "two distinct humans before money moves" overlaps with POOL. Our difference is **physical co-presence**, which it doesn't have.

---

## Unverified / conflicting

- **Which track the team registered for (Classic vs Continuity).** This decides whether the $2.5k Classic IDKit prize is even possible. Only the team's hacker dashboard shows it. UNVERIFIED.
- **Whether the staging-gate change (2026-09-25) is live on developer.world.org.** If it is, simulator-based demos against a production RP fail with 403 until a staging window is opened. If it isn't, `environment:"staging"` still works. UNVERIFIED. Test once with the real rp_id.
- Hacking start time for Tokyo (likely Fri Sep 25 evening JST): UNVERIFIED.
- Whether the Agents-track "mocked proofs" means the IdP issues tokens without any World App step: UNVERIFIED. The prize text says so; the docs don't.
- Buenos Aires / New Delhi exact World prize names per winner: not extracted (old page layout). UNVERIFIED.
- Docs pages disagree on naming: "staging" vs "sandbox". The Portal code maps `sandbox → staging` for the verifier but has a separate integrity attestation issuer for sandbox. VERIFIED in code; the docs are inconsistent.
- The `verification-flows` page covers UX only (hot, cold and semi-cold flows; iOS invite codes with a 15-min TTL). It has no protocol detail.
- Whether judges will accept a non-open-source repo: the Continuity rules require the new parts to be open source. The GitHub `tawago/enconomy` visibility is UNVERIFIED.
- Mumbai World prize requirements: not published. UNVERIFIED.

---

## Implications for the SAFE idea (Safe multisig + PoP guard)

**Fit with the IDKit rubric: strong.**
- The trust moment is concrete: "execute a treasury transaction". It maps to the prize's own example, "protection of an important account action".
- The failure path is natural: the owners are apart (FAR verdict), one owner cancels, the same human appears twice, or the World ID proof is stale. The guard reverts.
- "Commitment Issues" (a human approves an agent action) and "pinch" (a physical-world gate) both won on the same shape.

**Credential choice.** This is what judges score, so we need one rationale sentence.
- **Setup:** each owner binds their Safe owner key to a World ID *session* (`IDKit.createSession`, store `session_id` per owner key).
- **Execution:** each owner proves *that same session* plus PoP NEAR.
- The minimum-sufficient argument: we don't need global uniqueness at every tx. We need "the same human who enrolled as owner is here now, and the two owners are different humans".
  - Distinctness: check once at setup, with two uniqueness proofs whose nullifiers differ.
  - Continuity plus liveness at execution: session proof with `require_user_presence`.
- PoH (Orb) vs Selfie Check:
  - PoH is the honest choice if we claim "each owner is a distinct unique human" (it is high assurance).
  - Selfie Check (no Orb needed, has `sybil_score`) is enough if the claim is only "a live human, the same one as at setup".
  - Pick one and write the sentence. UNVERIFIED: that session proofs work with `proofOfHuman`. The docs show it with `selfieCheck` and say "session proofs for returning users".

**Onchain vs server.**
- A v4 onchain verify is mainnet-only (World Chain 480).
- The cheapest robust path: the server verifies World ID (Portal) and PoP (popprover), then signs an attestation `(safe, txHash, pair_tag, expiry)` with an issuer key. A Safe **Guard** `checkTransaction` checks that signature.
- The prize allows server verification, so this is fine.
- Safe 1.4.1 is on World Chain Sepolia and mainnet (bytecode verified), so the Safe itself can live on World Chain Sepolia with no World ID contract needed.

**Scope for 17 h.**
- One Guard contract (~100 lines), one server endpoint that issues the attestation, and one web page (Safe tx builder + IDKit JS) or a Safe{Wallet} flow.
- Feasible if the PoP app/server finish.
- Kotlin IDKit is not on Maven Central, so do the World ID step in a web page (IDKit JS / React), or reuse the worldid-spike GitHub-Packages route.

**Demo risk.**
- It needs two owners, each with a World ID, and each producing a *different* nullifier.
- With real World App that is two real humans (PoH needs two Orb-verified accounts; Selfie Check needs two World App accounts).
- With the simulator it needs the staging window (see Unverified).

## Implications for the POOL idea (private payment released only after an IRL meeting)

**Fit with the rubric: good story, weaker minimum-credential story, much bigger build.**
- The trust moment: "release a confidential payment". The claim: "payer and payee are two distinct humans who physically met".
- Per-payment uniqueness with `action = pop:<sid>` fits the existing adapter design exactly:
  - distinct nullifiers means distinct humans;
  - `pair_tag` is derived from both nullifiers;
  - a fresh action per session means meetings are unlinkable.
- PoH is the proportionate credential here, because the protected property is *two different unique humans*. Selfie Check's sybil score is weaker.

**Competition.** Rebind (same event) already ships "pays only when two different World IDs", onchain on World Chain Sepolia. POOL must lead with **physical presence**, or it looks like a copy.

**Build size.**
- A Railgun-like shielded pool (note commitments, Merkle tree, nullifiers, a withdraw circuit, relayer) is **not** realistic in the remaining ~17 h on top of the unfinished PoP integration.
- A credible hackathon cut is a "private escrow":
  1. The payer deposits into an escrow keyed by a commitment.
  2. The release needs a server attestation of PoP NEAR plus two World ID nullifiers plus the payee address.
  3. Privacy is limited to "amount/recipient hidden until release" or only "meeting unlinkable".
- Say plainly in the write-up that it is not a full shielded pool, or the Q&A will expose it.

**Onchain.** The same as SAFE: v4 onchain verify is World Chain mainnet only, so use a server attestation.

**Privacy tension to write down.**
- Posting nullifiers or `pair_tag` onchain links the payment to a meeting.
- `pop:<sid>` actions keep meetings unlinkable to each other, but the escrow release itself becomes public.

## Cross-cutting guidance for the design doc

1. **Submission package** (from the World prize text), so the implementing agents treat these as deliverables:
   - a "trust moment + credential rationale" paragraph;
   - a success run plus a *filmed* failure run;
   - `WORLD_FEEDBACK.md` (time to first success, friction, missing docs, top improvement).
2. **Server rules.** Our server, not the Portal, must:
   - reject reused nullifiers;
   - check `action == pop:<sid>`;
   - check `signal_hash == keccak(signal)>>8`;
   - check `environment == production`;
   - check `nullifier_A != nullifier_B`.
3. **Environment.** Use a production `environment` and real World App on the demo phones. It avoids the new staging gate. The spike already worked this way.
4. **Order of steps.** Keep the World ID step **before** the audio run: an iOS app switch kills the audio session (docs/pop-human-adapters.md).
5. **Video.** Record the demo video with a human voice. No TTS. This matters because the repo has TTS tooling and generated films. Record the screen on a laptop, not a phone.
6. **Partner prizes.** Up to 3 partners.
   - World counts as one, and it covers both its tracks.
   - ENS has a Continuity-only "Best Integration of ENSv2 into Existing Project" ($4k). It fits an existing project and the `ens` output adapter already designed.

---

## Open questions (the user must answer)

1. **Track:** did the team register for Classic or Continuity at Tokyo? If Classic, ask ETHGlobal staff now (Discord #help or email) whether a switch to Continuity is possible, given the pre-event research commit. Classic plus pre-existing work means no partner prizes.
2. **Target:** confirm the target is Tokyo (deadline Sun 09:00 JST) and not Mumbai (Nov 5–7). This decides whether the design doc is a 12-hour cut or a 6-week plan.
3. **Humans for the demo:** how many distinct World ID humans are available (Orb-verified PoH? World App accounts for Selfie Check?). The demo needs two distinct nullifiers.
4. **Environment:** production (real World App) or staging (simulator)? If staging, someone with Developer Portal access must open a staging window (MCP tool `set_world_id_staging_verification`) and put the token in server config.
5. **Credential:** PoH (Orb, distinct unique humans) or Selfie Check (+ session proofs, liveness)? We need one written reason for the IDKit rubric.
6. **Agents track:** also go after "World ID for Agents"? It is OIDC, not IDKit, and needs an HTTPS callback plus a sandbox client registration. It fits SAFE only if an agent proposes the Safe tx and humans approve by meeting.
7. **Repo:** is the repo public (Continuity requires the new parts to be open source), and who writes the pre-existing-work disclosure?
8. **Spike code:** reuse the worldid-spike code (Python RP signer, Kotlin IDKit wiring)? If yes, disclose it as pre-existing.
