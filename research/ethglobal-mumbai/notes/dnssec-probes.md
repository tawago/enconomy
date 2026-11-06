# DNSSEC probes and on-chain cost (2026-11-02)

Context: recap section 6 ("On-chain EVP design") wants to prove `_email-verification.<domain>` plus an issuer-key TXT on-chain through the ENS DNSSEC oracle.
Raw dig output: `notes/raw/dnssec-dig-2026-11-02.txt`.
Gas PoC (read-only, no tx, no keys): `poc/dnssec-gas/` (build_proof.py, prefixes.py, run.sh).

## TL;DR

- Neither of your domains is signed right now. enconomy.dev and tawago.com have no DS and no DNSKEY. Both use Cloudflare DNS and Cloudflare Registrar.
- Fix: click "Enable DNSSEC" in Cloudflare for both today. Cloudflare Registrar adds the DS itself, but via CDS scanning, which "can take one to two days". Hacking starts Nov 5. Do it Nov 2 or 3.
- Cloudflare signs with algorithm 13 (P-256). So your zone level will be P-256. VERIFIED: docs call it "Cloudflare's preferred cipher choice"; Registrar DS auto-add "can take one to two days" (https://developers.cloudflare.com/dns/dnssec/). Also seen live: cloudflare.com and cloudflare.dev DNSKEYs are alg 13.
- gmail.com is unsigned. `_email-verification.gmail.com` exists (`iss=accounts.google.com`) but cannot be proven on-chain.
- The ENS oracle on mainnet and Sepolia already uses the EIP-7951 precompile for algorithm 13. I checked this on-chain.
- Measured full proof (root to a small TXT, .com zone, P-256): about 569k gas (eth_estimateGas, includes 21k base and calldata). Under a .dev zone: about 630k up to the zone DNSKEY, plus about 50k for the TXT, so roughly 680k.
- Same .com proof with the old Solidity P-256 code (state override): 4.58M up to the zone DNSKEY, 6.18M with the big TXT. So the precompile is a 7-8x cut for full proofs.
- The recap says "over 1M gas" for one-time setup. Verification alone is lower (0.57-0.68M). Storing the key adds more. Not a contradiction, just an upper bound.
- Trap: Cloudflare signs records live with short RRSIG windows (seen: 2 days for a TXT). The oracle checks `block.timestamp` against inception/expiration. Build the proof right before you submit it.

## 1. dig probes (resolver 1.1.1.1, 2026-11-02 03:48 JST)

| Query | Result | Algorithm |
|---|---|---|
| TXT `_email-verification.gmail.com` | `"iss=accounts.google.com"`, TTL 3600, no RRSIG, no `ad` flag | none (unsigned) |
| DS gmail.com | NODATA; com NSEC3 opt-out record covers it | insecure delegation |
| DNSKEY gmail.com | NODATA (SOA ns1.google.com) | none |
| DS enconomy.dev | NODATA; dev NSEC3 proves no DS (`ad` set) | insecure |
| DNSKEY enconomy.dev | NODATA (SOA fay.ns.cloudflare.com) | none |
| DS tawago.com | NODATA; com NSEC3 opt-out | insecure |
| DNSKEY tawago.com | NODATA (SOA fay.ns.cloudflare.com) | none |
| DNSKEY . | KSK 20326, KSK 38696, ZSK 8763 | 8 (RSASHA256) |
| DS dev | `60074 8 2` | 8, digest 2 (SHA-256) |
| DNSKEY dev | KSK 60074, ZSK 59746 (1024-bit, 128-byte sigs) | 8 |
| DS com | `19718 13 2` | 13, digest 2 |
| DNSKEY com | KSK 19718, ZSK 65344 | 13 (ECDSAP256SHA256) |
| DNSKEY cloudflare.com (reference) | KSK 2371, ZSK 34505; DS `2371 13 2` | 13 |

Also checked authoritative servers directly (no recursion): ns-tld1.charlestonroadregistry.com has no DS for enconomy.dev; a.gtld-servers.net has no DS for tawago.com; fay.ns.cloudflare.com returns no DNSKEY for either. VERIFIED.

RDAP for enconomy.dev (pubapi.registry.google): `delegationSigned: False, zoneSigned: True`, registrar CloudFlare, Inc. "zoneSigned: True" is odd given no DNSKEY is served. Treat the zone as unsigned in practice. whois tawago.com (local `whois`, 2026-11-02): `DNSSEC: unsigned`, Registrar Cloudflare, Inc. VERIFIED.

`delv` on this Mac fails ("no crypto support"), so I did not get a local validation verdict. The `ad` flag from 1.1.1.1 is the validation signal used.

Chains you will get after enabling:
- tawago.com: root (8) -> com (13) -> tawago.com (13). Two RSA steps, rest P-256.
- enconomy.dev: root (8) -> dev (8) -> enconomy.dev (13). Four RSA steps, then P-256. A bit more gas.

Side fact: Verisign moved .com and .net to algorithm 13 in 2023 (https://blog.verisign.com/security/dnssec-algorithm-update/, VERIFIED by the DS/DNSKEY above). ICANN has an open 2026 proceeding on a root KSK algorithm rollover; Verisign's comment favors algorithm 13 (https://www.icann.org/en/public-comment/proceeding/proposed-root-ksk-algorithm-rollover-03-02-2026/submissions/verisign-inc-06-04-2026, from search snippet, page not read: UNREACHABLE for detail). The root is still algorithm 8 today.

## 2. ENS DNSSEC oracle

Source: https://github.com/ensdomains/ens-contracts/tree/staging/contracts/dnssec-oracle (default branch is `staging`; there is no `main`).

Algorithms and digests, from the deploy script `deploy/dnssec-oracle/10_deploy_oracle.ts` and checked live with read-only `eth_call` on `algorithms(uint8)` and `digests(uint8)`:

| ID | Contract | Mainnet address | Sepolia address |
|---|---|---|---|
| alg 5, 7 | RSASHA1Algorithm | 0x58E0383E21f25DaB957F6664240445A514E9f5e8 | 0x81d71DF6921F04BBf5347eaE737223073bA57646 |
| alg 8 | RSASHA256Algorithm | 0xaee0E2c4d5AB2fc164C8b0Cc8D3118C1c752C95E | 0xA1fdd748479064Bc4386ff8af7EA14DA8760172B |
| alg 13 | P256SHA256Algorithm (precompile) | 0xB091C4F6FAc16eDDA5Ee1E0f4738f80011905878 | 0x034262bE25dc0E304E04E111F2A6Bf1dBF1e260f |
| alg 15 (Ed25519) | not set (0x0) | | |
| digest 1 | SHA1 | 0x9c9fcEa62bD0A723b62A2F1e98dE0Ee3df813619 | 0x0e3656B31D7b1DD662cCf73C0547A73e5dD79B71 |
| digest 2 | SHA256 | 0xCFe6edBD47a032585834A6921D1d05CB70FcC36d | 0x975E539780920aE80314B64A9aDf9996cbc71bA4 |
| digest 4 (SHA-384) | not set | | |

- DNSSECImpl: mainnet 0x668ad4467129d49ecbe6274d95197797c0e262aa (deployed block 26,230,856), Sepolia 0xe634932ea96ee07a3461c6c78968928a56bd39ec. From `deployments/*/DNSSECImpl.json`. VERIFIED by live calls.
- Anchors on mainnet: two root DS records, key tags 20326 and 38696 (read via `anchors()`). VERIFIED.
- Recap claim "supports RSA/SHA-256 and P-256": VERIFIED. It also still accepts RSASHA1 (5, 7). No Ed25519, no SHA-384.
- API: `verifyRRSet(RRSetWithSignature[])` returns `(bytes rrs, uint32 inception)`. Each element is `{rrset, sig}` where `rrset` is RRSIG RDATA without the signature followed by the canonical RRs (RFC 4035 5.3.2). The chain starts at the root DNSKEY, checked against the anchors. It is a `view` function. Storing anything is your contract's job.
- Time check: `verifyRRSet(input)` uses `block.timestamp`; `verifyRRSet(input, currentTime)` exists too. It reverts with `SignatureExpired` / `SignatureNotValidYet`.

### P-256 via EIP-7951

- PR #509 "feat: Replace EllipticCurve with EIP-7951 P-256 precompile for Algorithm 13", merged 2026-01-26 into staging (https://github.com/ensdomains/ens-contracts/pull/509). VERIFIED via `gh pr view`.
- `P256SHA256Algorithm.verify` checks sig length 64, key length 68, then calls `P256Precompile.verify(sha256(data), r, s, qx, qy)`, a staticcall to 0x100. VERIFIED from source.
- The mainnet deployment artifact (commit c76c5ad, 2026-02-25, block 24,526,617) lists P256Precompile.sol in its sources. The oracle's `algorithms(13)` points to it. VERIFIED.
- EIP-7951: Final, address 0x100, 6900 gas, 160-byte input, returns 32-byte 1 on success and empty on failure (https://eips.ethereum.org/EIPS/eip-7951). VERIFIED. ENS pre-zeroes the output buffer, so an empty return reads as false. Fine.
- The PR text claims "~200k+ gas -> ~3,500 gas per verification". The 3,500 matches RIP-7212's old 3450 price; EIP-7951 charges 6900. Old cost per P-256 step in my test was about 1.38-1.43M, not 200k. CONTRADICTED on both numbers ("Gas reduction: ~200k+ gas → ~3,500 gas per verification", PR #509 body).
- Precompile is live on mainnet: proofs with P-256 steps verified in my calls. VERIFIED by execution.

### Gas per proof (measured)

Method: `build_proof.py` fetches each RRset plus RRSIG from 1.1.1.1 with dnspython 2.7.0 and builds the oracle input. `cast estimate` against mainnet, block about 26,321,823, at increasing chain lengths. Numbers are cumulative and include the 21k base fee and calldata. For "old" I overrode the code at the alg-13 address with the previous deployment (0x0faa24e538bA4620165933f68a9d142f79A68091) using an `eth_estimateGas` state override.

Chain for `cloudflare.com TXT` (huge 2,936-byte TXT RRset) and `_dmarc.cloudflare.com TXT` (223 bytes):

| Step | Alg | Cumulative (precompile) | Old Solidity P-256 |
|---|---|---|---|
| . DNSKEY (vs anchors) | 8 | 220,003 | 220,003 |
| com DS | 8 | 333,890 | 333,890 |
| com DNSKEY | 13 | 404,408 | 1,785,264 |
| cloudflare.com DS | 13 | 446,513 | 3,159,406 |
| cloudflare.com DNSKEY | 13 | 519,102 | 4,584,268 |
| big TXT (2.9 KB) | 13 | 781,948 | 6,175,401 |
| small TXT (_dmarc) instead | 13 | 568,552 | not run |

The small TXT proof on Sepolia's oracle: 565,888. VERIFIED.

Chain for `cloudflare.dev` (stand-in for enconomy.dev): . DNSKEY 220,003 -> dev DS 333,854 -> dev DNSKEY 488,197 -> cloudflare.dev DS 553,042 -> cloudflare.dev DNSKEY 630,186. Add about 50k for a small TXT.

Reading the numbers:
- Each P-256 step now costs 42k-73k. The 6.9k precompile is a small part. The rest is RR parsing, DS hashing, memory and calldata.
- The root DNSKEY step is the single biggest cost (220k): 844-byte RRset plus a 256-byte RSA sig.
- Keep TXT RRsets small. The proof covers the whole RRset at that name, not one string. Put the issuer-key hash under its own label (e.g. `_evp-key.tawago.com`), not at the apex next to other TXT records.
- Both TXT records (`_email-verification` and the key TXT) share the chain down to the zone DNSKEY. Send one call with both at the end, or verify the chain once and store the zone DNSKEY. That saves about 0.5M on the second record.

## 3. ENSIP-17 (Gasless DNS Resolution)

https://docs.ens.domains/ensip/17. Status Final, author nick.eth, created 2024-02-09. VERIFIED.
- TXT format: `ENS1 <resolver-name-or-address> [context]`. Only the first field of each TXT record is read.
- OffchainDNSResolver uses CCIP-Read (EIP-3668). A gateway fetches the DNSSEC proofs. The callback verifies them with the oracle.
- Needs DNSSEC enabled on the name. Same trust model as DNS import. A gateway can refuse to answer but cannot forge records.
- Relevance: once DNSSEC is on, `tawago.com` or `enconomy.dev` can resolve in ENS without any tx. Add `ENS1 <resolver>` TXT. This could replace or sit next to the Sepolia MeetResolver plan. On mainnet only, unless the Sepolia OffchainDNSResolver is set up for DNS TLDs (not checked).

## 4. ENS forum thread on EIP-7951

https://discuss.ens.domains/t/updating-dnssec-verification-with-eip-7951/21754. VERIFIED (fetched).
- Posted 2025-12-25 by estmcmxci. Proposes swapping EllipticCurve for the 0x100 precompile, following the ModexpPrecompile pattern.
- nick.eth said on 2026-01-07 he would review it. Author reported the merge to staging on 2026-01-27.
- The thread text has no gas numbers. It links a demo with benchmarks and a test suite: https://github.com/eurekaetcetera/dnssec-solutions/tree/master/ens-p256-test (not opened).

## 5. What this means for the EVP-on-chain design

- Plan works only after DNSSEC is on. Today the proof is impossible for both domains. Highest-priority action.
- Decision (made without asking): use tawago.com as the demo issuer domain. Its chain is root(8) -> com(13) -> zone(13). That is the cheapest available (about 0.57M for one small TXT). Keep enconomy.dev as backup (about 0.68M).
- Gmail cannot be proven via DNSSEC: VERIFIED (gmail.com has no DS). Matches the recap's limits section.
- Freshness: Cloudflare's live-signed TXT RRSIGs last about 2 days (seen inception 2026-10-31 17:53Z, expiry 2026-11-02 19:53Z for `_dmarc.cloudflare.com`). DNSKEY RRSIGs last about 2 months; .com DS RRSIGs about 1 week. So proof input cannot be pre-baked days ahead. Fetch it at demo time. To cut later proofs to one P-256 step plus parsing (about 50-60k), store the verified zone DNSKEY in your own contract and call the alg-13 contract `verify(key, data, sig)` directly on the TXT RRset. The oracle itself always starts from the root anchors and has no cache. Your contract then has to repeat the RRSIG checks (name, type, labels, time window, key tag) on its own.
- Demo can run on Sepolia: the oracle there has the same algorithm table and gave the same gas (565,888).

## Open items

- After enabling, re-run: `dig +dnssec DS tawago.com`, `dig +dnssec DNSKEY tawago.com`, and `PY=<venv python> poc/dnssec-gas/run.sh _email-verification.tawago.com TXT`.
- Check that the Sepolia OffchainDNSResolver covers .com / .dev before relying on ENSIP-17 on Sepolia.
- The RDAP `zoneSigned: True` for enconomy.dev may mean DNSSEC was toggled once on Cloudflare and is pending or half-enabled. Look at the Cloudflare dashboard.
