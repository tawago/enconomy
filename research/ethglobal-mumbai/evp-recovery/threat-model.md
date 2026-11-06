# Threat model: EVP + proximity + frame-tx key recovery

Nov 3, 2026. Adversarial pass over the "lost phone" recovery idea. Privacy pools are out of scope.

Marks: VERIFIED = primary source opened today or earlier in this folder's notes and re-read now. CONTRADICTED = the source says otherwise. UNREACHABLE = no primary source. PLAUSIBLE = reasoning, not tested.

Revised Nov 3, afternoon, after the sibling notes landed (`account-design.md`, `proximity.md`, `poc-native-evp/`, `issuer-worker/`). What changed:

- `account-design.md` §6 and `proximity.md` §3 both pick a **laptop-resident key** as the second signer. Section 5.0 below says what that buys and what it does not: two factors against the remote phisher and the issuer, one factor against a stolen laptop.
- Section 2.7's first draft said "write `usedIssuerDigest` in VERIFY." CONTRADICTED: VERIFY runs as STATICCALL. The write has to sit in a `pre_verify` frame. Fixed.
- Native EVP in VERIFY (`poc-native-evp`) lands at exactly 100,000. It leaves no room for a guardian entry. Section 5 now states that trade.
- The hackathon issuer's session is a constant HMAC cookie with no logout. Section 2.2.
- New attacker 2.9: the session / PoP server.

## 0. The system, in one breath

- Smart account. Owner = a P-256 key in the phone's secure hardware. The phone is gone.
- Recovery: on a laptop, in Chrome, the user types `alice@<domain>`. Chrome mints an EVP token (EVT from the issuer, KB-JWT from a fresh Chrome key). The page sets the KB-JWT `nonce`. We set `nonce` to commit to the new phone's key, and to the acoustic session between laptop and new phone.
- A frame tx (EIP-8141) rotates the key. The new phone signs the tx's sig hash with its new key (native scheme 2). The EVT is checked on chain.
- Timelock: rotation starts, waits, then finishes. The old key can cancel during the wait.

The one sentence that drives everything below: **a single EVT proves that a browser profile holding a live issuer session for `alice@<domain>` asked RP origin X to bind nonce N.** It authenticates a session, not a person and not a device. Every attacker is a question of who holds that session, or who chooses N.

## 1. Facts the model rests on

| Fact | Status | Source |
| --- | --- | --- |
| KB-JWT required claims: `aud` = RP origin, `nonce` from the RP's session, `iat`, `sd_hash`. The RP must check all four | VERIFIED | draft-hardt-email-verification-02 s6.1.2, s6.5 |
| `nonce` "MUST be unique per verification request and SHOULD be valid for a limited time window" | VERIFIED | draft-02 s2.2 |
| The draft's security section does not discuss phishing at all | VERIFIED (absence) | draft-02 s10 |
| DNS delegation is "the residual risk of the design, and it is not mitigated elsewhere in this document." RPs SHOULD check DNSSEC where the domain is signed | VERIFIED | draft-02 s10.4 |
| Chrome "fetches the token in the background after the email is entered or autofilled." No consent UI is described | VERIFIED | Chrome verifier guide |
| Chrome makes the KB key itself; the page cannot supply it. Only `nonce` binds the token to anything of ours | VERIFIED | Chromium `EmailVerificationRequest::Verify`, per `../notes/evp.md` s8 |
| Chrome checks EVT and KB `iat` within now-5 min .. now+1 min at mint time | VERIFIED (code) | `../notes/evp.md` s1 |
| Chrome 156+ checks the EVT `email` byte for byte against what was typed | VERIFIED | Chrome issuer guide, per `../notes/evp.md` |
| Gmail issuer signs Ed25519 on both signatures, gmail.com unsigned | VERIFIED | `../notes/evp.md` s5 live probe |
| tawago.com and enconomy.dev have no DS and no DNSKEY; both are on Cloudflare DNS and Cloudflare Registrar; tawago.com inbound mail is Cloudflare Email Routing | VERIFIED (dig, whois, task facts) | `../notes/dnssec-probes.md` s1 |
| VERIFY frames cannot call 0x100 (P-256) or 0x02 (sha256) on the live sidecar (`precompiles: []`, CODE_ACCESS). TIMESTAMP is banned except the expiry predeploy. Body frames may call anything | VERIFIED | `../notes/precompile-rule.md`, sidecar `frameTx.ts` 810-827 |
| Native scheme-2 entry: `msg` is empty (sig hash) or an explicit 32 bytes; signer = keccak(qx‖qy)[12:]; low-s required; verified in Rust before any frame runs, 6,700 gas against the cap | VERIFIED | ethrex `vm.rs` 905-1025, read today |
| The sig hash commits to every frame and its calldata; signatures over it can't be re-pointed | VERIFIED | same, `compute_sig_hash` |
| Reads of foreign storage in VERIFY need stake; the sender's own slots are free | VERIFIED | sidecar `frameTx.ts` 740-806, read today |
| One ES256 EVT+KB check costs ~63k gas with 0x100 and 0x02 | VERIFIED (forge) | `../poc-evp-issuer/README.md` |
| The acoustic NEAR verdict is enforced by the app, never by the chain. One cheating endpoint can fake NEAR. A browser build cannot attest | VERIFIED (our own analysis) | `../../2026-09-25-cheating-participant-and-trust.md` |
| VERIFY frames run as STATICCALL. Storage writes are possible only in `deploy` and `pre_verify` frames; the sender's own storage is always allowed | VERIFIED | `../notes/eip8141-family.md` modes table; `../tmp/erc-8421.md` STORAGE section, STORAGE-010 |
| Sidecar STORAGE rule skips `addr === sender` entirely, reads and writes | VERIFIED (read today) | sidecar `frameTx.ts` ~745 |
| Pure-Yul SHA-256 lets VERIFY check both ES256 signatures natively; the sidecar sum is `79,900 + 3 x 6,700 = 100,000`, exactly the cap | VERIFIED (printout, not re-run) | `poc-native-evp/results/entries.txt` |
| In the sample token the issuer `s` is already low, Chrome's KB `s` is high; the `n-s` flip passes both the sidecar port and frame-lib | VERIFIED (local run) | same file |
| Hackathon issuer: login is a shared-secret password form; the session cookie is `HMAC(LOGIN_SECRET, EMAIL)`, the same value every login, `Max-Age=86400`, no logout, no revocation | VERIFIED (source) | `issuer-worker/worker.mjs` 27-35, 121-131 |
| A laptop WebCrypto key is non-extractable but dies with "clear site data"; a passkey is usually synced, so it is the user's Google/Apple account; a software raw-digest key is readable by any script on the page | VERIFIED | `proximity.md` §2 |

Two consequences before any attacker shows up:

1. **The EVT is checked in a body frame, not in VERIFY.** It needs 0x100, 0x02 and a clock. All three are banned in VERIFY. So the payer has already paid before the token is examined. VERIFY can only look at native signatures and the account's own storage. (`poc-native-evp` shows a way around it with Yul SHA-256, at the full 100k. See 5.)
2. **JWS ES256 signatures are not always low-s.** ethrex rejects high-s. The submitter flips `s` to `n-s` off chain before putting a JWS signature into a native entry. VERIFIED on the sample token: the KB signature needed the flip, the issuer's did not.

## 2. Attackers

Legend for each row: what EVP's `aud`+`nonce` already do; what proximity adds; what timelock + old-key cancel adds.

### 2.1 Remote phisher: lures the user to a fake page

What happens: the user types `alice@domain` into the phisher's form. Chrome mints a token in the background, no prompt (VERIFIED, verifier guide). The phisher needs a first-party origin-trial token on their own origin, which anyone can register (VERIFIED, OT page per `../notes/evp.md` s4).

- **aud + nonce:** `aud` is the phisher's origin. The contract pins our origin, so the token is rejected. This works, and only because the contract pins `aud`. If the contract trusted an off-chain verifier that forgot `aud`, the phisher wins outright. So: `aud` is load-bearing. Reverse-proxy phishing (attacker in the middle) also lands on the attacker's origin, because Chrome sets `aud` from the committed origin, not from page content. VERIFIED (Chromium `email_verification_request.cc` per `../notes/evp.md`).
- **XSS on the real recovery page is the remote phisher winning outright.** Right `aud`, attacker's nonce, and if the laptop key is a WebCrypto key (5.0) the script signs with it too. Chrome mints with no prompt. Keep the page dependency-free and CSP-locked; that is the whole defense.
- **The real phishing hole is nonce substitution on the real page.** If the real RP page accepts the "new key" from a URL parameter, a pasted string, or a QR the user is told to show, the phisher sends "open this link to recover" and the real page mints a token for the attacker's key with the real `aud`. The attacker's own phone then signs the frame tx. Nothing in EVP stops that.
- **Proximity:** this is the one place a laptop-to-phone session helps against a remote attacker. If the new key can only enter the page through the acoustic channel, a remote phisher cannot inject it. A played-back audio file does not work: the ranging is two-way and the other side must submit its own recording (VERIFIED, cheating-participant note). The attacker would need a live accomplice device in the room, which is the stolen-laptop case, not the remote one. Honest caveat: a QR scanned by the laptop camera gives nearly the same guarantee. Audio is a channel, not a proof.
- **Timelock + cancel:** the user still has no old key (the phone is lost), so cancel is empty here. The timelock only buys time to notice.

Verdict: stopped by `aud` plus "key enters via the short-range channel only." Proximity is load-bearing against this attacker only as the input channel for the new key. The chain never sees the audio.

### 2.2 Stolen laptop with a live issuer session

What happens: the thief opens Chrome, visits the real recovery page, types `alice@domain`, pairs their own phone. Every check passes: the session is real, `aud` is right, `nonce` commits to the thief's key, the thief's phone was next to the laptop.

- **aud + nonce:** nothing. The thief is the RP user.
- **Proximity:** nothing. The thief holds both devices. Any laptop-to-phone proof is a proof about the thief's two devices.
- **DBSC (device-bound session cookies):** nothing. The TPM is in the stolen laptop. DBSC fights cookie export, not device theft (VERIFIED, `../00-recap-input.md` s5 says as much).
- **Timelock + cancel:** works only if the user still has the old phone. In the "lost phone" story they do not. Note the opposite case: laptop stolen, phone fine. Then cancel works and the user should also kill the issuer session.
- **A laptop-resident second key** (the `laptop` slot in `account-design.md` §6, the WebCrypto guardian in `proximity.md` §3): nothing. It sits on the same stolen machine. The thief signs with it the same way the user would. Non-extractable only means the thief cannot copy it elsewhere; they do not need to.
- **The hackathon issuer makes this worse.** Its cookie is `HMAC(LOGIN_SECRET, EMAIL)`, constant across logins, valid 24 h, with no logout endpoint (VERIFIED). A copied cookie works until `LOGIN_SECRET` rotates. And the login itself is a password form, so the secret is phishable like any password.
- **OS login** is the actual defense: a locked screen, a short auto-lock. That is outside our system.

Verdict: a single EVT falls to this attacker, and so does EVT plus any key that lives on the laptop. This is the attacker that makes a second factor on a device the recoverer does not hold mandatory.

### 2.3 Issuer compromise, DNS takeover, Cloudflare account takeover

Three doors into one room.

- **Issuer key or server compromise:** mint an EVT for any address at the domain with any `nonce`. Single-EVT rule falls. `aud` and `nonce` are the attacker's to choose. Proximity: nothing, attacker's own phone. Timelock + cancel: helps only if the old phone exists.
- **DNS takeover of `_email-verification.<domain>`:** draft-02 calls this the residual risk (VERIFIED, s10.4). But our contract pins the issuer *key*, not the DNS record. So Chrome would accept an attacker's issuer, the chain would not. DNS takeover collapses into "can they also get the pinned key rotated." It matters only at enrollment or when the pin is rotated through an ENS/DNSSEC proof.
- **DNSSEC does not fix this for us today.** Both domains are unsigned (VERIFIED). If DNSSEC is turned on, Cloudflare holds the zone keys. A Cloudflare account takeover then signs whatever TXT it likes, and an ENS oracle proof will validate it. For tawago.com the same Cloudflare account also runs the registrar, DNS, Email Routing (so password-reset mail for the issuer login) and, if we host the RP page on Pages, the RP origin too. That one account is the root of every leg: issuer delegation, issuer-key pin via DNSSEC, `aud` origin, and the mailbox. Pinning the issuer key by the owner's signature at setup is strictly stronger than trusting DNS, because it removes Cloudflare from the recovery path. PLAUSIBLE for the ENS-import route; VERIFIED that Cloudflare runs DNS, registrar and inbound mail.
- **ENS text record as the pin:** if the issuer key hash lives in an ENS text record, whoever controls that ENS name is one more admin-class attacker. Keep the pin in the account's own storage, set by the owner key.

Verdict: the issuer is a full trust root for the EVP leg. Nothing in EVP, proximity or the timelock changes that. Only a second factor the issuer does not control does.

### 2.4 Malicious domain admin

- Own issuer: the admin *is* the issuer operator. Same as 2.3.
- Google Workspace domain: the admin resets the mailbox password, logs in, has a live session. Same as 2.2. And Google's issuer is Ed25519 with no DNSSEC, so there is no cheap on-chain check anyway (VERIFIED, `../notes/evp.md`).
- Email is a domain-granted credential. Whoever grants it can take it back. EVP inherits that exactly.

Verdict: identical to issuer compromise. For a personal domain the "admin" is the user, so this is self-inflicted. For a company domain it is HR plus IT.

### 2.5 Malicious relayer or payer

- The frame tx's sig hash commits to every frame, target and calldata (VERIFIED, ethrex). A relayer can't change `newKey`, the token or the transcript.
- The relayer can **withhold**. A self-paid tx removes the relayer, so censorship is bounded by the mempool, not by us.
- The relayer can **read** the token and the transcript, since they go on chain anyway. The email string is in the EVT payload. If that is a privacy issue, the contract compares a hash of the email and the token still has to be in calldata, so the email is public. Accept it or hash at a different layer.
- A sponsor-payer that reverts the body on purpose: the sponsor pays, not the account. Only a problem if the sponsor is also the only path.

Verdict: `aud`+`nonce`+sig hash already stop tampering. Proximity and timelock add nothing here. The relayer is a courier.

### 2.6 Replay of old tokens

- A mined recovery tx makes its token public forever. With `nonce = keccak(newKey)` only, the same token restarts a rotation to the same key after the owner cancelled it. `startRotation` replaces any pending rotation (VERIFIED, `RecoverableP256Account.sol`), so a replay also knocks out someone else's pending rotation.
- Chrome's 5-minute `iat` check happens at mint time, in the browser. It does nothing on chain unless the contract re-checks `iat` against `block.timestamp` in the body frame. The PoC does (`maxAge`), VERIFIED.
- Fix: `nonce = keccak(account, chainid, newKey, recoveryNonce, deadline)`. The nonce dies with the attempt. Add the `iat` window and an expiry frame. Together: a token is good for one attempt, for minutes.
- Proximity and timelock add nothing against replay by themselves.

Verdict: solved by what goes into `nonce`, not by any new primitive.

### 2.7 Griefing the account's gas

This one is structural.

- The EVT check sits in a body frame. VERIFY runs first and the payer pays whatever VERIFY approves. If the account self-pays and VERIFY's recovery branch accepts "any new P-256 key signing the sig hash," then **anyone with a fresh key can submit a recovery tx that passes VERIFY and reverts in the body.** The account pays the body gas every time. The sidecar's per-sender pending cap also fills with junk, so the real recovery gets stuck behind it. PLAUSIBLE on the cap; VERIFIED on the gas.
- Fix inside VERIFY, without precompiles: require a native scheme-2 entry from the **pinned issuer key** over an explicit 32-byte `msg`. That `msg` is the sha256 of the EVT signing input, computed off chain. The protocol verifies the issuer's P-256 signature over it in Rust, 6,700 gas, no precompile call. The body frame later recomputes sha256 and checks it equals the entry's `msg`. A griefer now needs a real issuer signature to get past VERIFY. VERIFIED that explicit-msg entries work this way (ethrex `vm.rs`).
- Residue: a public old token still carries a real issuer signature. The first draft said "VERIFY writes `usedIssuerDigest[msg] = true`." **CONTRADICTED.** VERIFY is a STATICCALL; writes are allowed only in `deploy` and `pre_verify` frames (ERC-8421 STORAGE section, VERIFIED). So the write goes in a `pre_verify` DEFAULT frame right before the account's VERIFY frame, own storage (STORAGE-010; the sidecar skips the sender address, VERIFIED). Cost: entry 3,000 + one zero-to-nonzero SSTORE ~22,100 + state gas, about 25-30k of the prefix. MODELED. If the tx is invalid the write never lands, so a failed VERIFY burns nothing. Two semantics I could not pin: a DEFAULT frame gets a per-frame `status`, it does not invalidate the tx by reverting (`../notes/eip8141-family.md` 169), so the `pre_verify` frame must do `require(!used[msg]); used[msg] = true` itself and VERIFY must check that frame's `status == 1`. And whether a DEFAULT-mode frame can read `SIGPARAM` to learn `msg` at all. PLAUSIBLE, both in 6. Each issuer signature then buys the griefer exactly one failed body. For an own issuer that only signs for its users, the griefer's supply is "tokens already on chain," each burned once.
- Simpler, and what `account-design.md` Option 2 does: the **laptop EOA `L` pays** the start tx. Then junk tokens cost `L`, not the account, and only someone who can make `L` sign can submit at all. Griefing collapses into "who holds L," which is the stolen-laptop case. For the demo this is enough, and the issuer entry becomes optional.
- Third way: put the whole EVP check in VERIFY with Yul SHA-256 (`poc-native-evp`). Then the `nonce` claim (which commits to `recoveryNonce`) is checked before payment and old tokens die with no storage write. Price: the full 100k, no room for anything else. See 5.
- Alternative: a separate recovery sponsor pays and simulates first. Then griefing hits the sponsor. Fine for a demo, a new trust point in production.

Verdict: the single-EVT, self-paid design is griefable by anyone. Close it one of three ways: L pays (cheapest, demo), native issuer entry + a `pre_verify` used-digest write (self-paid, keeps the guardian entry), or native EVP in VERIFY (self-paid, no guardian entry).

### 2.8 Not in the brief but it changes the answer: stolen phone, not lost

The current contract protects against loss, not theft (VERIFIED, comment in `RecoverableP256Account.sol`). A thief with an unlocked phone holds the owner key, drains the account, and cancels every rotation forever. The timelock + old-key cancel is then a weapon for the thief. A guardian veto or a guardian-driven rotation that the owner key cannot cancel is needed for theft. Out of scope for the hackathon, in scope for any honest README.

### 2.9 Not in the brief either: the session / PoP server

`proximity.md` §5 puts a server between laptop and phone: it hands out `sid`, `notBefore`, `sessionNonce`, relays the audio verdict.

- **Nonce substitution by the server:** the laptop recomputes `sessionNonce` from the fields it can see and refuses on mismatch (`proximity.md` §5). Then a bad server can only deny service. If the page skips that recompute, the server chooses which `newKey` the EVT binds to, which is attacker 2.1 again with a different face.
- **Verdict forgery:** with the sound-bound stack the server computes NEAR from two uploaded WAVs and nothing is signed (VERIFIED, `proximity.md` §1). The laptop and the guardian take the server's word. A bad server says NEAR for any pair. With the PoP app the transcripts are signed and the laptop re-checks, so the server is a courier.
- **aud + nonce, timelock:** nothing beyond the recompute above. Proximity: the server *is* the proximity layer here, so it cannot defend against itself.

Verdict: with sound-bound, the server is a trust root on par with the issuer. With signed PoP transcripts plus a local recompute of `sessionNonce`, it drops to a relay.

## 3. What proximity actually adds

Be blunt. The chain sees a 32-byte transcript hash. It cannot tell a real acoustic session from `keccak("x")`. NEAR is a verdict an app produces and refuses to sign without. A browser cannot attest, so the laptop side is never a trusted endpoint (VERIFIED, cheating-participant note).

Sharper than that: in a recovery, **the attacker is the new phone.** The 2026-09-25 note shows one cheating endpoint fakes NEAR by editing its own self-hear, given any relay device near the honest side, for example the victim's own phone on a call with a scammer. Attesting the *guardian's* phone does not help, because the edit happens in the attacker's file. Only attestation of the new phone closes it, and a browser new phone has none. Whether a phone-call codec passes the 2-18 kHz probe was never tested (UNREACHABLE, `proximity.md` §6).

So acoustics binds *which* key the guardian approves. It does not prove the guardian met Alice. That proof is the guardian's eyes. The guardian app or policy has to refuse remote ceremonies ("someone on the phone asked me to tap approve"), because the audio layer cannot.

Also from `proximity.md` §6: two tabs on one machine pass the server's NEAR check. The contract's `guardian != newKey` rule (already in `RecoverableP256Account`) is necessary, not sufficient. With software keys an attacker makes both on one laptop and the rule is satisfied.

So, with one person in the loop:

| Attacker | Proximity adds |
| --- | --- |
| Remote phisher | The new key enters the page only through a short-range channel. Blocks link/paste/QR-from-chat key injection. Same strength as a camera-scanned QR. |
| Stolen laptop | Nothing. Thief holds both devices. |
| Issuer / DNS / admin | Nothing. Attacker brings their own phone. |
| Relayer | Nothing. |
| Replay | Nothing. |
| Griefing | Nothing. |

Proximity between two devices held by the same party proves nothing about who that party is. It becomes load-bearing exactly when a signer the recoverer does **not** control has to be in the room: a guardian's attested phone, which signs the transcript with a key the attacker cannot get. Then "near" means "this guardian agreed, here, now," and every attacker in 2.2 to 2.4 has to add physical co-location with a willing guardian to their shopping list.

## 4. What timelock + old-key cancel actually adds

- Covers every case where the user still holds the old phone: stolen laptop, issuer compromise, admin, phisher who somehow got a token. The owner sees `RotationStarted` and cancels.
- Covers nothing in the headline story, because the old phone is gone. There, the timelock only gives time to notice and to tell the guardian.
- Turns into a liability under phone theft (2.8).
- Needed anyway: it is the only thing that makes "one factor fell" survivable when the user is still around.

## 5. Minimal rule set that makes proximity load-bearing

### 5.0 First, the sibling notes' choice: EVT + a laptop key

`account-design.md` §6 enrolls the laptop EOA as `laptop`. `proximity.md` §3 makes the laptop's WebCrypto key the guardian. Same idea: the second signer lives on the laptop. Plainly:

| Attacker | EVT + laptop key |
| --- | --- |
| Remote phisher (2.1) | two factors. The phisher has neither the session nor the key |
| Issuer key compromise (2.3) | two factors. The issuer can mint, it cannot sign with the laptop key |
| **RP origin compromise** (Cloudflare account, Pages deploy key, XSS, a bad dependency) | **one factor.** A WebCrypto key is origin-scoped: any script on the origin can call `sign()`, no export needed. Next time the user types their email on the real page, the attacker's script mints an EVT for its own nonce and signs its own D with the laptop key. Only a passkey resists this, because it demands a user-presence prompt per signature |
| Domain admin (2.4) | two factors, unless the admin also runs the RP origin (for tawago.com, same Cloudflare account) |
| Stolen laptop (2.2) | **one factor.** Session and key are on the same machine; the thief pairs any phone |
| Relayer, replay, griefing | as before; griefing lands on `L` if `L` pays |

Key flavour matters for 2.2 and for the key's own life:
- WebCrypto non-extractable: cannot be copied off the laptop, but a thief with the laptop does not need to, and any script on the origin can invoke it. Dies on "clear site data", so the user can lose their recovery path by cleaning their browser. VERIFIED (`proximity.md` §2).
- Passkey: synced. "Laptop" is then the user's Google or Apple account. If the email is Gmail, both factors hang off one Google account. Not two roots. Its one real advantage: a user-presence prompt per signature, so page script cannot sign silently.
- Software raw-digest key in `localStorage`: any script on the page reads it. XSS turns 2.1 into a full takeover. Demo tier only.

So the hackathon design, as the siblings have it, accepts the stolen-laptop loss. It should say so in the README: "if your laptop is stolen unlocked with your mail signed in, the thief can start a recovery; the 120 s window and your old phone are the only brakes." For a lost phone there is no old phone, so the brake is the window alone.

### 5.0b The gas trade, stated once

Native EVP in VERIFY (`poc-native-evp`) is `79,900 + 3 x 6,700 = 100,000` (VERIFIED printout). The 79,900 is the spike's *configured* prefix limits, set to land on the cap, not measured usage. I tried `forge test --match-test test_gas` there: it does not compile right now (`Sha256Lib.sol` moved to `attic/`, a sibling is mid-refactor). So real headroom is UNREACHABLE here. At the configured limits a fourth native entry (guardian, 6,700) does not fit. **Unless measured VERIFY usage comes in at or under ~73k, native EVP in VERIFY and a guardian signature in VERIFY cannot coexist under the 100k cap.** Pick one:
- Guardian is the load-bearing factor: EVP goes in the body frame (63k, no cap). This is what 5.B below does.
- "EVP checked in the mempool" is the headline: no guardian entry. Then the second factor is the laptop key, with 5.0's loss.

### 5.1 The two multi-member variants

Two variants of the multi-member rule, judged on independence from the attackers above.

**A. Two EVTs.** Alice's own-issuer token plus a second email token.

- Google as the second issuer: Ed25519, no `kid`, no DNSSEC. No cheap on-chain check. VERIFIED. Off-chain attester would have to vouch, which is a new trust root.
- Two tokens from the same own issuer: same session, same laptop, same issuer. Falls to 2.2, 2.3, 2.4 at the same time. Independence is zero.
- Two tokens from two own issuers on two domains: better against issuer compromise, still falls to the stolen laptop if both sessions live in one Chrome profile. And it is two body-frame checks, ~126k, fine in a body but heavy.

**B. One EVT + one guardian phone present.** Recommended.

VERIFY (prefix, no precompiles, own storage only):

1. Expiry frame 0 with a deadline about 15 min out.
2. `sig[0]`: new phone, scheme 2, `msg` empty (sig hash). Proves the new phone holds the key and commits to every frame.
3. `sig[1]`: issuer key, scheme 2, explicit `msg = sha256(EVT signing input)`, `s` normalised. Pinned issuer address in the account's storage. This is the anti-griefing gate. The `usedIssuerDigest[msg]` mark goes in a `pre_verify` frame, not here (VERIFY cannot write; see 2.7). Or skip both and let `L` pay.
4. `sig[2]`: guardian phone, scheme 2, explicit `msg = D = keccak(DOMAIN, chainid, account, newKey, recoveryNonce, transcriptHash, deadline)`. Guardian in `isGuardian`. Guardian app signs only after its own NEAR verdict with the new phone. This is the existing `RecoverableP256Account` guardian entry with one of the two guardians swapped for an EVT.

Body frame (SENDER, precompiles fine, clock fine):

5. `EvpVerifier.verify(token, offs, …)`: issuer signature recomputed and `sha256(signing input) == sig[1].msg`; KB-JWT signature with the `cnf` key; `aud` == pinned origin; `nonce == keccak(account, chainid, newKey, recoveryNonce, deadline)`; `iat` within window; `sd_hash`.
6. `startRotation(newKey, transcriptHash)`; `recoveryNonce++`.

Then the wait, owner cancel, `finishRotation` by the new key after `readyAt`. Keep DELAY long enough for the guardian to be told if the owner is unreachable.

Why B and not A, attacker by attacker:

| Attacker | A (two EVTs, own issuer) | B (EVT + guardian) |
| --- | --- | --- |
| Remote phisher | stopped by `aud` | stopped by `aud`, and needs a guardian in the room |
| Stolen laptop | **falls** | needs a guardian who meets the thief and agrees |
| Issuer / DNS / Cloudflare | **falls** | needs a guardian |
| Domain admin | **falls** | needs a guardian |
| Relayer | stopped | stopped |
| Replay | stopped by nonce design | stopped by nonce design + `recoveryNonce` in D |
| Griefing | stopped by issuer entry + used digest | stopped the same way, and the guardian sig is a second free gate |
| Guardian collusion | n/a | **falls** if guardian + any one of the above. One guardian is the price of one-person UX |
| Guardian fooled remotely (3.) | n/a | **falls** if the guardian approves over a phone call and the new phone cheats NEAR. Policy, not code |
| Session / PoP server (2.9) | falls with sound-bound | guardian app re-checks signed transcripts; server is a relay |
| Stolen phone (2.8) | falls | falls; needs a veto path |

Prefix gas for B, modeled: expiry 4k + account VERIFY ~25k + 3 x 6,700 + optional `pre_verify` ~25-30k = **~75-80k**, under the cap with EVP in the body. If `L` pays instead of the account, drop the `pre_verify` and add L's 2,800 + ~8k pay frame: ~60k.

What B costs: the user must have enrolled one guardian device ahead of time, and the guardian must be physically present at recovery. That is the whole point: the attacker's shopping list now contains a person.

What B keeps from the headline idea: EVP still does real work. It replaces the second guardian. A user with one friend and one email domain can recover; before, they needed two friends. And the laptop-to-phone session still carries the new key into the page, closing the link-injection hole.

## 6. Open questions

- SSTORE in VERIFY: settled, no. VERIFY is STATICCALL (VERIFIED). A `pre_verify` DEFAULT frame may write own storage per ERC-8421 and the sidecar skips the sender address (VERIFIED, source). Whether ethrex itself charges or restricts anything extra for that frame: UNREACHABLE without a run.
- `pre_verify` used-digest path (2.7): can a DEFAULT frame read `SIGPARAM`; does VERIFY see the frame's `status`. Neither checked against ethrex source. PLAUSIBLE.
- Native-EVP VERIFY headroom: measured gas per SHA-256 block and real frame usage. The spike's `test_gas` exists but did not compile when I ran it (mid-refactor). UNREACHABLE today.
- Does a phone-call audio codec pass the 2-18 kHz probe, i.e. is the relay attack on the new phone practical? Never run. UNREACHABLE.
- `issuer-worker` is demo-grade: constant HMAC cookie, no logout. Before any real use it needs per-login random sessions, revocation, and a passkey instead of a shared secret.
- Per-sender pending cap exact behaviour under junk recovery txs: not measured.
- Whether Chrome will mint a token for our ES256-only issuer on 156/157 at all: never run in a live browser (UNREACHABLE, same as `../notes/evp.md`).
- Guardian app must refuse to sign D unless NEAR and unless `newKey` equals the key it just met. Same shape as the Kohaku method's `signingInput` throw. Not built for this flow.
- ENS: where the issuer-key pin lives. The threat answer is "in the account, set by the owner key." If the demo needs ENS to be visible, use it for display (name to account), never as the pin.
