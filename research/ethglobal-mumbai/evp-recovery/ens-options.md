# ENS in EVP recovery: options and the cross-chain gap

Nov 3, 2026. Question: what does ENS add to "lose phone, prove email with EVP on the laptop, chirp a new phone, rotate the key in an EIP-8141 frame tx"?
Short answer: less than hoped, for a reason nobody had checked. ENS's own DNS integration is broken right now on mainnet and Sepolia. The bare DNSSEC oracle works, and it also runs on chain 1337.

Marks: VERIFIED = primary source opened or call made today. CONTRADICTED = source says otherwise. UNREACHABLE = could not check. MODELED = our estimate. PLAUSIBLE = likely, not proven.
Raw numbers: `ens-oracle-1337/results.txt`. Probe: `ens-oracle-1337/src/OracleProbe.sol` (eth_call initcode, never sent).

## 0. Three facts that decide this

**1. ENS's live DNS path can't verify any proof today.** VERIFIED (calls at mainnet block 26,332,769 and Sepolia 12,053,794, Nov 3 07:26 UTC).
- The root DNSKEY set is now signed by key 38696 only (dig, RRSIG valid Oct 31 to Nov 21). That's the root KSK rollover.
- The contracts ENS wires to `.com` and `.dev` (DNSRegistrar for import, OffchainDNSResolver for ENSIP-17) point to old oracles. Mainnet: `0x0fc3…30C5`. Sepolia: `0xe62E…8653`. Both trust only anchors 19036 and 20326.
- A fresh proof (`_dmarc.cloudflare.com`) reverts on both with `NoMatchingProof`.
- The standalone oracles from our earlier notes do have 38696 and pass: mainnet `0x668a…62aa` (~569k), Sepolia `0xE634…39ec` (565,900).
- So DNS import and ENSIP-17 are dead until ENS repoints those contracts. Enabling DNSSEC on tawago.com doesn't change that. ENS could fix it before Nov 5. Re-check then (one `cast estimate`, section 6).
- Also on Sepolia, the old oracle's alg 13 is the pre-precompile Solidity code (3,905 bytes). If it ever works again, it costs about 1.4M per P-256 step, not 70k.

**2. Chain 1337 can run the oracle.** VERIFIED.
- Precompiles answer on the miner: 0x02 (sha256), 0x05 (modexp), 0x100 (P256VERIFY, fresh openssl test key, returned 1).
- So the oracle works in a normal tx or a body frame. It can't run in VERIFY (no precompiles in the prefix, `../notes/precompile-rule.md`), and at ~0.5M it's far past the 100k cap anyway.
- Full probe on 1337: deploy + wire + verify the cloudflare.com chain. `verifyRRSet` costs 488,307 execution gas, the same as on mainnet.

**3. The account already pins the issuer key itself.** `threat-model.md` §2 argues that a key pinned by the owner at setup is stronger than any DNS or ENS pin. The Cloudflare account runs DNS, registrar, inbound mail and maybe the RP origin, so DNSSEC just moves trust to that one login. I agree. So ENS here is for discovery and audit. It's not a trust root, and it shouldn't sit on the recovery path.

## 1. Options

### (a) DNSSEC oracle proves the issuer TXT records, into an issuer registry

What: one normal tx proves `_email-verification.tawago.com TXT "iss=…"` plus our own `_evp-key.tawago.com TXT "<P-256 key or its hash>"`. A small `IssuerRegistry` stores `issuerKey[domainHash]`. The account's `configHash` (or its VERIFY code) gets the issuer from there.

| | |
| --- | --- |
| Chains | Sepolia or mainnet via the standalone oracle (works today). 1337 only after we deploy our own copy (section 2). Not via ENS's DNSRegistrar (fact 1) |
| Gas | ~566k for one small TXT, .com chain, P-256 (VERIFIED Sepolia 565,900). Second TXT in the same call: about +50k (MODELED, `../notes/dnssec-probes.md` §2). Plus registry SSTOREs, ~45k (MODELED). Total ~0.66M. Later key rotations can skip the root chain if the registry caches the zone DNSKEY: ~50-60k (MODELED) |
| Trust | DNS root + .com + Cloudflare's zone keys + whoever controls the Cloudflare login. Weaker than an owner-pinned key (fact 3). Stronger than "the issuer's https endpoint says so" |
| Demo cost | Blocked until tawago.com is signed. DNSSEC is off today (VERIFIED earlier). Cloudflare's DS auto-add "can take one to two days", so enable by Nov 3-4 or it's not ready Nov 5. Cloudflare TXT RRSIGs last ~2 days, so build the proof at demo time. Needs our own issuer to publish an ES256 key (exists: `issuer-worker/keys/issuer.jwk.json`) |

### (b) ENS name points at the recovering account; text records hold the recovery config

What: `alice.enconomy.eth` (Sepolia, ENSv2) resolves to the account on 1337 and holds `configHash`, the issuer domain, `emailHash`, and the guardian/new-device key hashes. A DNS-imported name (`tawago.com` in ENS) would be the "your domain is your identity" version.

| | |
| --- | --- |
| Chains | Sepolia (ENSv2, our `enconomy.eth` registry). Nothing on 1337 can read it |
| Gas | Subname claim already works via `bridge/` (`register` + `touch`). Text records: ~50-70k each on a standard resolver (MODELED). DNS import: oracle proof plus the claim, and it doesn't work today anyway (fact 1) |
| Trust | Whoever controls the ENS name can rewrite the config. That's one more admin-level attacker (`threat-model.md` §2). So the records may only *mirror* what's pinned in the account, never feed it |
| Demo cost | MeetResolver has no `setText`. It serves only its own computed keys (`met`, `meetings`, `zk`, `description`, `url`) (VERIFIED, `contracts/src/MeetResolver.sol` 252-300). Either add a settable key or two (contract change plus redeploy or new resolver) or use a separate name with a stock resolver. The 1337 address would go in ENSIP-11 `addr(node, 0x80000000 \| 1337)`. MeetResolver answers `addr(bytes32,uint256)` but computes it. Same gap |
| Privacy | `emailHash` in a public text record can be brute-forced from a list of likely addresses. Store a salted commitment, or nothing |

### (c) ENSIP-17 gasless DNSSEC (`ENS1 <resolver>` TXT)

| | |
| --- | --- |
| Chains | Mainnet. Sepolia has the contracts (OffchainDNSResolver `0x179B…8583`, gateway `https://dnssec-oracle.ens.domains/`, VERIFIED) |
| Gas | Zero tx. The oracle runs inside `eth_call` |
| Trust | Same as DNS import. The gateway can refuse to answer but can't forge records |
| Demo cost | Dead today: the callback uses the stale oracle (fact 1), and the domains aren't signed. Even fixed, it only gives a name that resolves. Nothing on 1337 reads it. Drop it |

### (d) Other ideas

- **d1. Recovery receipt back to ENS.** After the key rotates on 1337, `bridge/` (same attester key) writes a `recovered` counter or text record on `alice.enconomy.eth` on Sepolia. Display only. The trust is the attester key, the same as today's meeting records. Cheap: about one `record`-sized tx. Good for the demo's "see it on ENS" moment.
- **d2. ENS as the meeting log.** The chirp that authorizes the new phone already creates a PoP session. The existing bridge turns NEAR verdicts into MeetResolver records. A recovery chirp can show up the same way, with no new contract.
- **d3. Use the oracle without ENS.** That's just (a). It's worth saying because "ENS DNSSEC oracle" ≠ "ENS registry". The oracle needs no registry, no names and no `.eth`. That's why it ports to 1337.
- **d4. A shared issuer registry as the alt-mempool hook.** See section 3.

## 2. The cross-chain gap: ENS on Sepolia, frame txs on 1337

Chain 1337 has no ENS. Three ways across.

### 2a. Deploy the oracle to 1337 on Nov 5

- Contracts (only these four): `DNSSECImpl` 10,219 B runtime, `RSASHA256Algorithm` 2,811 B, `P256SHA256Algorithm` 1,039 B, `SHA256Digest` 812 B. VERIFIED (compiled from ens-contracts staging, sizes read back from the probe).
- Algorithms: both domains need alg 8 (RSA/SHA-256, root and .dev), alg 13 (P-256: .com and Cloudflare zones) and digest 2 (SHA-256). No SHA-1, no Ed25519. Anchors: root DS 20326 + 38696 (copy `anchors()` from the mainnet `0x668a…` oracle). VERIFIED.
- Precompiles: modexp (RSA), sha256 and P256VERIFY are all live on 1337 (fact 2). The oracle needs no special build. VERIFIED.
- Gas on 1337 (the chain has EIP-8037 state pricing, so deploys cost far more than on mainnet). VERIFIED by probe:

| Step | 1337 | Mainnet |
| --- | ---: | ---: |
| Deploy DNSSECImpl | 16,505,055 | 2,220,545 |
| Deploy 2 algorithms + digest | 7,722,688 | 1,030,546 |
| 3 setters | 337,876 | 73,516 |
| `verifyRRSet`, cloudflare.com small TXT | 488,307 | 488,307 |

- Open: DNSSECImpl alone estimates 17,290,115 on 1337. That's above the 2^24 = 16,777,216 per-tx cap. ethrex caps only *regular* gas at 2^24 under 8037 (`crates/blockchain/payload.rs` ~975; EIP-7825's flat cap applies only Osaka to pre-Amsterdam, `blockchain.rs` ~4141). Code deposit is state gas, so it probably fits. PLAUSIBLE, not proven: an estimate with `gas=0x1000000` came back as exactly 0x1000000, which is ambiguous. Fallback: rebuild with lower optimizer runs (smaller code, less deposit gas), or ask the devnet team.
- Money: base fee 7 wei, so ~25M gas is nothing. But we need funded 1337 ETH, and the gateway/faucet returned 502 again today (07:26 UTC). UNREACHABLE.
- Clock: 1337's block timestamp tracks wall time (3 s off). RRSIG windows check out. VERIFIED.
- Trust: the same as the oracle on mainnet, given the same anchors. Fully permissionless: nobody's key sits between DNS and the 1337 registry. Our own deploy, so a judge has to trust that we copied the code and anchors faithfully. Show the bytecode diff against Sepolia's `0xE634…`. Runtime code differs only by immutables, MODELED.
- Effort: about half a day, plus the DNSSEC-on dependency for a real domain. Before tawago.com is signed you can only prove someone else's TXT (cloudflare.com), which proves the plumbing, not our issuer.

### 2b. Bridge a Sepolia-verified result into a 1337 registry (the `bridge/` pattern)

- Pattern: `bridge/bridge.py` watches results and sends txs with one attester key (`~/.enconomy/ens-sepolia.key`). VERIFIED (`bridge/README.md`).
- Here: verify the TXT with Sepolia's standalone oracle, then the bridge key writes `issuerKey[domain]` on 1337.
- Trust cost: the 1337 side trusts the attester key, not DNSSEC. The Sepolia proof becomes decoration, since whoever holds the key can write any issuer key. That's *weaker* than the owner pin we already have (fact 3), and it costs ~0.6M on Sepolia plus a relayer.
- Only upside: it reuses running code. Not recommended.

### 2c. Two honest halves

- 1337: the frame tx recovers the account. The issuer key is pinned in `configHash` by the owner at setup. No ENS on the critical path.
- Sepolia: `alice.enconomy.eth` is the account's name. It mirrors the config (issuer domain, the `configHash` value, the 1337 address) and gets the d1 recovery receipt. If tawago.com is signed in time, one Sepolia tx proves `_evp-key.tawago.com` with the standalone oracle. The UI shows "DNSSEC says key X, the 1337 account pins key X".
- Trust: stated plainly, nothing pretends to be trustless across chains.
- Cost: low. The subname flow exists. Needs a settable text key (section 1b) or a stock resolver name.

## 3. Foreign registry read in VERIFY and the EF alt-mempool prize

Source: sidecar `packages/executor/src/services/UserOpValidation/validators/frameTx.ts` 740-807 and `utils.ts` 82-105 (`isSlotAssociatedWith`), commit 2e22ff0. VERIFIED (code read).

- Any non-sender slot read → not public-mempool. The canonical mempool allows only the sender's own storage (`../notes/eip8141-family.md` "Public mempool rules").
- In the alt mempool:
  - Registry slot keyed by the **sender address** (`mapping(address account => key)`, slot within +128 of `keccak(A ‖ slot)`) counts as "associated" → readable **unstaked** (when there's no factory frame).
  - Slot keyed by **domain or issuer** (`issuerKey[keccak("tawago.com")]`), shared by all users → not associated → **stake required**, else `unstaked <role> accessed … slot …`.
- So: a shared, DNSSEC-fed issuer registry read in VERIFY makes the tx alt-mempool-only *and* staked. That's exactly the prize's "more flexible state access" route, and it's a better story than ChirpGas's: many accounts trust one registry entry, and a key rotation in DNS rotates them all.
- The catch is gas. Precompiles are banned in the prefix, so EVP-in-VERIFY only works through the native path (`poc-native-evp`). That path sums to **exactly 100,000** (79,900 frame limits + 3 × 6,700 sig entries; VERIFIED printout `poc-native-evp/results/entries.txt`, not re-run). A cold STATICCALL to the registry plus a cold SLOAD adds ~5-6k (MODELED: 2,600 + 2,100 + call overhead). It doesn't fit as a bolt-on. You'd need ~6k trimmed from the Yul SHA-256 or from frame limits, or one fewer sig entry.
- In a body frame there's no storage rule. Any mempool takes it. It shows nothing alt-only.
- Also: VERIFY reads only what's *already* in the registry. The 0.5M DNSSEC proof is always a separate earlier tx (on 1337, so 2a is a prerequisite for this variant).

## 4. Recommendation

**Build 2c (two honest halves). Keep 2a + section 3 as the stretch, with clear flip conditions.**

Why: on Nov 7 the likely state is DNSSEC just turned on or still propagating, the 1337 faucet unknown, and ENS's DNS path still stale. 2c works in all three cases and doesn't fight the threat model. The owner-pinned key is the trust root, and ENS is the name plus a public mirror.

Flip to 2a (+ section 3 if going for the alt-mempool prize) when all of these hold by Nov 5 midday:
1. `dig +dnssec DS tawago.com` returns a DS, and `poc/dnssec-gas/run.sh _evp-key.tawago.com TXT` against Sepolia `0xE634…` succeeds.
2. We have 1337 ETH (faucet or the EF team).
3. A real deploy of DNSSECImpl on 1337 lands (the 2^24 question).
4. For section 3 only: the native-EVP VERIFY gets ~6k under the cap.

Don't do: 2b (worse trust than what we have), (c) ENSIP-17 and DNS import (broken today, and they never reach 1337).

Action today (user, not this agent): turn on DNSSEC for tawago.com in Cloudflare now. That's the only long-lead item, and it costs nothing if unused.

## 5. What ENS gives, one line each

| Option | Chain | Gas | Trust | Status today |
| --- | --- | --- | --- | --- |
| (a) oracle → issuer registry | Sepolia/mainnet now; 1337 after 2a | ~0.66M once, ~55k per rotation with cached zone key | DNS + Cloudflare login | Blocked: tawago.com unsigned |
| (b) name + recovery text records | Sepolia | ~50-70k per record | ENS name owner (mirror only) | Needs resolver with `setText` |
| (c) ENSIP-17 | mainnet/Sepolia | 0 | DNS | Broken: stale anchors |
| DNS-imported name | mainnet/Sepolia | proof + claim | DNS | Broken: stale anchors |
| d1 recovery receipt | Sepolia | ~1 bridge tx | attester key | Ready (existing bridge) |
| 2a oracle on 1337 | 1337 | ~24.6M deploy, 0.49M per proof | DNS, permissionless | Faucet down; 2^24 deploy unclear |
| 2b bridge to 1337 | Sepolia → 1337 | 0.6M + relay | attester key | Not recommended |
| Section 3 shared registry in VERIFY | 1337 alt mempool, staked | +5-6k in VERIFY | DNS (via 2a) | Over the 100k cap by ~6k |

## 6. Re-check commands (read-only)

```sh
# is ENS's .com DNS path fixed? (expect success, not NoMatchingProof 0x06cde0f3)
PY=<venv python> ORACLE=$(cast call 0xB32cB5677a7C971689228EC835800432B339bA2B 'oracle()(address)' --rpc-url https://ethereum-rpc.publicnode.com) \
  poc/dnssec-gas/run.sh _dmarc.cloudflare.com TXT
# tawago.com signed yet?
dig +dnssec DS tawago.com @1.1.1.1
```
