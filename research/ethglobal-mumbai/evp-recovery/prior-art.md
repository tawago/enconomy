# Prior art: key recovery, and where "EVP + proximity + frame tx" sits

Nov 3, 2026 (rechecked 16:20 JST against `poc-native-evp`). Scope: recover or rotate a smart account key. Privacy pools are out.

Marks: VERIFIED = I opened the primary source today (or ran the probe). CONTRADICTED = the source says otherwise. UNREACHABLE = could not get a primary source. SNIPPET = search-result text only, page not opened. MODELED = our own estimate, not run.

## Our idea in one table, so the comparisons are fair

| | EVP + proximity + frame tx |
| --- | --- |
| Trust root | The authority is the user's email domain, through DNSSEC (root KSK -> TLD -> domain zone) and an EVP issuer key published under it, plus the account's own timelock. Proximity is **binding, not a second factor**: Chrome makes the EVP key itself, so the chirp is what ties the token minted on the laptop to the phone hardware key that becomes the new owner. Proximity becomes a real second factor only if the laptop key is enrolled on the account in advance (Mac Secure Enclave raw-digest signing is already verified). Otherwise someone holding the email session can chirp their own two devices; only the timelock and owner cancel stop them. Recommended demo variant: pre-enrolled laptop key. |
| What the user does | On the laptop, enters their email; Chrome mints an EVP token whose `nonce` binds the new key. Laptop and phone chirp. Both sign. One frame tx starts the rotation. Wait out the delay. |
| On-chain cost | VERIFY: native P-256 sigs at 6,700 each run outside the EVM. Our closest built thing, RecoverableP256Account recovery `self_verify`, measured 20,513 (forge, 3 sigs, 3 own SLOADs); whole recovery tx modeled ~46k plus 3,000 per frame entry. The EVP check is ~63k (poc-evp-issuer, forge) and **sits in a body frame today**, because prefix/VERIFY frames can't call 0x100 or 0x02. Upgrade path: pass the issuer and Chrome sigs as native scheme-2 entries and redo SHA-256 in pure Yul. The entries are valid under both checkers, sidecar port and frame-lib: VERIFIED (`poc-native-evp/results/entries.txt`). That test set the prefix limits to hit the 100,000 cap on purpose, so it checks the sig-cost math, not that frame 1's real code fits in the ~70-75k left over. That fit is UNREACHABLE until the Yul SHA-256 compiles (account-design.md models ~95k+). The Yul SHA-256 gas is UNREACHABLE right now: that PoC is mid-refactor and does not compile (Sha256Lib moved to `attic/`). It fits only at about 4k gas per block or less. DNSSEC proof of the issuer key: ~0.57M (.com, P-256 zone) to ~0.68M (.dev), once per issuer key, not per recovery. |
| Hard limits | tawago.com and enconomy.dev have no DNSSEC today. Gmail is Ed25519 and unsigned, so the biggest EVP issuer can't be anchored. Chrome makes the KB key itself, so the only link between token and meeting is `nonce`. Proximity is enforced by the apps; the chain sees signatures, not sound. Frame txs exist only on devnets; chain 1337 has no ENS. |

Sources: `../2026-11-02-report.md`, `../notes/evp.md`, `../notes/dnssec-probes.md`, `../poc-validation-rules/README.md` (gas table), `../poc-evp-issuer/README.md`. All VERIFIED (our own measured or recorded results).

## 1. ZK Email recovery (zkemail/email-recovery)

| | |
| --- | --- |
| Trust root | Guardians' email providers (their DKIM keys) + a DKIM key registry fed by an oracle + Groth16-style ZK verifier + the account's timelock. The oracle is ic-dns-oracle: "mini consensus over 30 computers to create a threshold ECDSA signature on top of a rotated key", each pulling from several DNS resolvers. No DNSSEC today; it is listed as a future improvement. |
| What user does | Setup: pick guardian emails, threshold, delay, expiry. Each guardian replies to an acceptance email. Recovery: guardians reply to a recovery email; a relayer proves and submits `handleRecovery`; after the delay anyone calls `completeRecovery`. |
| On-chain cost | Per-guardian ZK proof verify plus module bookkeeping. No gas figure found in the repo page, docs or audit summary: UNREACHABLE. Floor: our own Groth16 measurement is 189k+ per proof. |
| Modules | `SafeEmailRecoveryModule` (Safe), `UniversalEmailRecoveryModule` and `EmailRecoveryModule` (ERC-7579 executors; their `onInstall` breaks 4337 rules, install after deploy). Covers lost keys, not stolen ones: a thief can uninstall the module. |
| What we add | No relayer and no oracle committee if the domain is DNSSEC-signed. Proximity binds the email proof to the new device key. Native P-256 in VERIFY: tens of k gas, not hundreds. Recovery uses the account's own email; no guardian set needed (zkEmail can also use your own second email as a guardian, so this is a small gain). |
| What we lack | Guardian privacy (zkEmail hides guardian emails on chain; an EVP token in calldata shows the email unless hashed). Works with Gmail; we can't. Has audits (Ackee, Matter Labs on the registry). Runs on mainnet chains today; we need a frame-tx devnet. |

Registry detail, from `UserOverrideableDKIMRegistry.sol` (VERIFIED): a key hash is valid when its "set" score reaches 2. A main-authorizer approval counts 1 before `setTimestampDelay` passes and 2 after. A user's own approval counts 2. Either side can revoke; the user can undo a main-authorizer-only revoke. No DNSSEC code anywhere in it. The header says the main authorizer is "the contract owner", but the code sets them separately: minor doc mismatch.

### Swap the DKIM oracle for an ENS DNSSEC proof of `<selector>._domainkey.<domain>`?

Feasible in principle, not drop-in, and blind to most users.

- Who is even provable (dig @1.1.1.1, today, VERIFIED):
  - gmail.com, icloud.com, yahoo.com, fastmail.com: no DS. Impossible.
  - outlook.com: zone signed (alg 13), and the `selector1._domainkey` CNAME is signed. But it points into `outbound.protection.outlook.com`, and the answer has no `ad` flag. Not provable end to end.
  - proton.me: provable. `protonmail._domainkey.proton.me` (RRSIG alg 8) CNAMEs to `...domains.proton.ch` (TXT RRSIG alg 13), and the resolver sets `ad`.
  - tawago.com: has `cf2024-1._domainkey` (RSA, ~420 bytes), but no DS. Not provable until DNSSEC is on.
- Gas: one chain to a small TXT is ~0.57M (.com, measured). A 2048-bit DKIM TXT is ~420 bytes, between our small TXT (~50k step) and the 2.9 KB one (~260k step). Proton needs two chains (proton.me to the CNAME, proton.ch to the TXT), so roughly 1.0-1.3M. MODELED, not run, and the .ch TLD step was not probed: running it needs dnspython, which I did not install here.
- Glue work: `verifyRRSet` returns raw RRs. Our contract has to follow the CNAME, check names, parse the TXT, base64-decode the `p=` key. Doable, a few hundred lines.
- Poseidon mismatch: ic-dns-oracle has a Poseidon canister, which suggests the registry stores a Poseidon hash of the key limbs because the circuit wants that. Getting from raw RSA bytes on chain to the same Poseidon hash in Solidity is costly. So "swap the oracle" likely means storing keccak/sha256 and changing the verifier side too. PLAUSIBLE (SNIPPET; repo not opened).
- RRSIG windows: Cloudflare live-signs TXT with ~2-day RRSIGs. The registry only needs the proof once per key, so this is fine for a registry, unlike a per-tx check.
- Verdict: a nice "fewer parties" upgrade for signed domains (proton, our own once signed), at ~0.6-1.3M per key, paid once per DKIM rotation. It does nothing for Gmail users, who are most zkEmail users.

Sources: https://github.com/zkemail/email-recovery (VERIFIED), https://github.com/zkemail/zk-email-verify/blob/main/packages/contracts/UserOverrideableDKIMRegistry.sol (VERIFIED), https://docs.zk.email/architecture/security-considerations (VERIFIED), https://docs.zk.email/architecture/dkim-verification (VERIFIED), https://docs.zk.email/account-recovery/ (VERIFIED), ic-dns-oracle via https://awesome.ecosyste.ms/projects/github.com%2Fzkemail%2Fic-dns-oracle (SNIPPET), Ackee audit https://ackee.xyz/blog/zkemail-email-recovery-audit-summary/ (SNIPPET).

## 2. Sui zkLogin

| | |
| --- | --- |
| Trust root | OAuth provider's JWT signature + validator quorum (2f+1) agreeing on provider JWKs + Groth16 trusted setup + user salt. Salt and prover services are not trusted with funds but can link identity to address. |
| What user does | Makes an ephemeral key, puts it in the OAuth nonce, logs in with Google etc., gets salt + proof, signs with the ephemeral key until `max_epoch`. "Recovery" of a lost device = log in again. |
| On-chain cost | Native to Sui, a Groth16 verify per session. Not comparable to EVM gas. |
| Losses | Lost salt = lost account. Lost OAuth account = lost access; docs suggest a multisig with a second provider. |
| What we add | Nonce binding is the same trick (EVP `nonce` = hash of new key). We add a chirp that binds the token to a hardware key on the phone, not an ephemeral software key. Second factor only if the laptop key was enrolled beforehand. Ethereum, not Sui. No salt service. |
| What we lack | zkLogin is shipped, at the protocol level, for Gmail. Our root (DNSSEC) excludes Gmail. They have a validator oracle for JWKs; Ethereum has no equivalent, which is why we need DNSSEC. |

Source: https://docs.sui.io/concepts/cryptography/zklogin (VERIFIED).

## 3. Kohaku social recovery (EF, `packages/social-recovery`)

| | |
| --- | --- |
| Trust root | Clauses of thresholds over credentials; each credential is a method module (ECDSA wallet, passkey, zkPassport, Anon Aadhaar) + config. Wait period, then consume; cancels by owner, by approver proofs, or by veto. |
| What user does | Setup a commitment on chain (body backed up off chain). On loss, gather approvals: each approver signs a per-place EIP-712 digest, then submit. |
| On-chain cost | Not measurable: contracts live in `defi-wonderland/social-recovery-contracts`, not this repo; SDK descriptors are zero addresses. Version 0.0.1-alpha.1, "NOT READY FOR PRODUCTION". |
| Our spike, not kept in this repo | `MetInPersonMethod` fits `IRecoveryMethod` without bending it. Guardian and new phone both sign `meetDigest = keccak(MEET_DOMAIN, kohakuDigest, transcriptHash, newPhone)`. tsc clean, 18/18 self-test. A module would cost two 0x100 calls (6,900 each), unmeasured. |
| What we add | A new method kind (met in person) and an EVP method would be another. Kohaku is the natural home for "email + proximity" as two credentials in one clause. |
| What we lack | Kohaku can't be demoed on chain: nothing deployed. Kohaku's module path uses precompiles in ordinary execution, not VERIFY, so it doesn't need frame txs at all; the frame tx is our framing, not a Kohaku requirement. |

Sources: the kohaku repo, `packages/social-recovery/README.md` (VERIFIED).

## 4. Safe: Safe{RecoveryHub} and Candide social recovery module

| | |
| --- | --- |
| Trust root | RecoveryHub: a "recoverer" (yourself, a friend, or a company like Sygnum Bank or Coincover) behind a Zodiac Delay Modifier. Candide: N guardian addresses, threshold, grace period; Candide itself can be a guardian after an email/SMS OTP. |
| What user does | Pick recoverers/guardians while you still have the key. On loss, they propose a new owner, wait the delay, finalize. Current owner can cancel during the delay. |
| On-chain cost | Ordinary Safe module calls with ECDSA approvals. No figure on Candide's page. Cheap compared to ZK. |
| What we add | No custodian or OTP server: the email check is a browser-signed EVP token anchored in DNS, not Candide's server saying "the OTP matched". Proximity ties the email proof to the new device key held by the person with the email. |
| What we lack | Shipped, audited, on mainnet, with real recovery partners. Candide's email/SMS guardian is the honest pragmatic version of what we do: a trusted signer. Ours replaces trust in Candide with trust in the email domain + DNSSEC. |

Sources: https://docs.candide.dev/wallet/plugins/recovery-with-guardians/ (VERIFIED), https://help.safe.global/articles/9622260218-account-recovery-with-saferecoveryhub (SNIPPET: Zodiac Delay Modifier, cancel button), https://safe.global/blog/safe-launches-safe-recoveryhub-joining-forces-with-sygnum-bank-and-coincover (SNIPPET).

## 5. Passkey wallets: Coinbase Smart Wallet, Clave

**Coinbase Smart Wallet**

| | |
| --- | --- |
| Trust root | Any owner (address or P-256 passkey) can act alone. Recovery = a "recovery key", a plain Ethereum key from a phrase, added as another owner while you still have the passkey. Synced passkeys (iCloud, Google Password Manager) lean on the cloud account. |
| What user does | Write down a recovery phrase in advance. On loss, enter it, register a new passkey, pay a fee. |
| On-chain cost | One owner-add call. Owner changes can be replayed cross-chain via `executeWithoutChainIdValidation` (self-calls to owner add/remove and upgrade only). |
| What we add | No seed phrase to store. "Recovery factor" is your email domain + a device in the room. |
| What we lack | Coinbase's model is simple and live. If the passkey is cloud-synced, Apple/Google already do recovery for them; our pitch only matters for device-bound keys (Secure Enclave / StrongBox raw keys, which we use). |

Sources: https://github.com/coinbase/smart-wallet (VERIFIED: owners, cross-chain replay; README describes no recovery), https://help.coinbase.com/en/wallet/getting-started/smart-wallet-recovery (SNIPPET: recovery phrase must be set while you still have the passkey).

**Clave** (zkSync Era, native AA)

| | |
| --- | --- |
| Trust root | Secure Enclave / TrustZone P-256 key, verified on chain via RIP-7212. Recovery options: "Cloud" and "Social", both timelocked. |
| What user does | Pick guardians or cloud backup; on loss, trigger recovery and wait. |
| On-chain cost | Not found. |
| What we add | Same hardware-key idea, but on L1-style frame txs with native P-256 in VERIFY instead of a precompile call; recovery without a cloud backup. |
| What we lack | Clave shipped, was audited (Cantina). Cloud backup detail unknown. |

Sources: SNIPPET only (zksync.mirror.xyz, cantina.xyz portfolio, Celo forum). Treat as background, not citation-grade.

## 6. Argent

| | |
| --- | --- |
| Trust root | Guardians (friends' wallets, hardware wallets, or Argent's own guardian service with email/2FA). Majority of guardians approve recovery. Owner can cancel during the security period. Guardians can also lock the wallet (5-day period). |
| What user does | Add guardians (36 h delay per added guardian except the first). On loss, guardians approve, wait the security period. |
| On-chain cost | Small: signature checks in the wallet contract. No figure found. |
| Conflict | Recovery window is 36 h in older posts, 48 h in newer posts and support pages. Sources disagree; treat 48 h as current. |
| What we add | Argent's email guardian is Argent's server. EVP moves the email check to a signed token checkable on chain (if the domain is DNSSEC-signed). |
| What we lack | Argent pioneered this UX years ago, on mainnet and Starknet. |

Sources: SNIPPET (argent.xyz blog, support.argent.xyz). Not opened.

## 7. EIP-7702

- Status Final, Standards Track Core. VERIFIED.
- The EOA key signs the authorization and can sign a new one: the check accepts accounts whose code is "empty or already delegated". Delegated EOAs can still originate transactions (EIP-3607 relaxed). Delegating to `0x0` restores "original purity". VERIFIED (quotes from the EIP).
- So 7702 cannot rotate the root key. Any "recovery" a delegate contract does is a second key added beside the old one. If the old key leaked, the thief can re-delegate and undo it. The EIP doesn't say "cannot rotate" in words; this is a direct reading of its rules.
- What we add: a real smart account under EIP-8141 whose validation is code. After rotation the old key is just a stale owner value; it has no protocol-level power. This is our cleanest positioning line.
- What we lack: 7702 is live on mainnet; 8141 isn't.

Source: https://eips.ethereum.org/EIPS/eip-7702 (VERIFIED).

## Summary table

| System | Trust root | User effort | On-chain cost | Live? |
| --- | --- | --- | --- | --- |
| ZK Email | DKIM + 30-node ICP threshold oracle + main authorizer + timelock | guardians reply to emails | ZK verify per guardian, 189k+ floor (UNREACHABLE exact) | yes, audited |
| zkLogin | OAuth JWT + Sui validator JWK quorum + salt + Groth16 setup | log in with Google | native Sui | yes |
| Kohaku | per-method modules, threshold clauses | gather approvals | unknown, nothing deployed | no |
| Safe RecoveryHub / Candide | recoverer or guardians (+ Candide OTP server) + delay | ask guardians | low (ECDSA) | yes |
| Coinbase SW | recovery phrase key (or cloud passkey sync) | keep a phrase | one owner add | yes |
| Clave | guardians or cloud, timelock | ask guardians | unknown | yes (zkSync) |
| Argent | guardians incl. Argent email service, 48 h | ask guardians | low | yes |
| 7702 | the original EOA key, forever | n/a | n/a | yes |
| **Ours** | email domain via DNSSEC + EVP issuer key, two chirping devices, timelock | type email on laptop, chirp with phone | ~46-55k recovery tx (native P-256) + ~63k EVP body frame; ~0.6M once per issuer key | devnet only |

## Honest pitch

Every live recovery scheme leans on someone: a guardian, a recovery company, an OTP server, a 30-node DNS oracle, or a phrase you stored. We try to lean on things you already have: your own email domain, proven on chain through DNSSEC and the ENS oracle with no extra committee, and two of your own devices standing next to each other. The rotation runs as one EIP-8141 frame tx, where the phone keys' P-256 signatures are checked natively for a few thousand gas and the old key loses all power, which EIP-7702 can't give you. What we don't have: Gmail users can't use it (Ed25519, unsigned zone), neither of our domains is signed yet, the EVP check runs in a body frame because VERIFY can't touch precompiles (moving it into VERIFY hangs on an unmeasured Yul SHA-256), the "they were close" part is enforced by our apps and not by the chain, and frame txs only exist on devnets without ENS. So it's a working demo of a trust-minimized path for people who control a signed domain, plus a Kohaku-shaped method that could carry it to mainnet later. Not a replacement for zkEmail or Safe recovery today.
