# EVP (Email Verification Protocol): pinned facts

Checked 2026-11-02. Each claim is marked VERIFIED, CONTRADICTED (quote) or UNREACHABLE.
"Chromium trunk" means github.com/chromium/chromium mirror, read on 2026-11-02 (source read only, nothing run).

## Decision (2026-11-02): EVP and DNSSEC are out for Mumbai

Recap sections 5 and 6 are about a third of the research, and 03-07 never said this outright, so here it is. EVP and the DNSSEC anchoring are **not built for Mumbai**. There are four reasons:
1. The live sidecar has `precompiles: []`, so CODE_ACCESS rejects any VERIFY that touches 0x100 (P256VERIFY) or 0x02 (SHA-256) (`precompile-rule.md`). An EVT check needs both: two P-256 verifies and SHA-256 over the signing inputs and `sd_hash`. A native scheme-2 entry can check the issuer's ES256, but it can't bind the JWT's contents without SHA-256 (`08-wildcards.md`).
2. Gas, even if the precompiles were allowed: one ES256 token is about 63k of execution (`poc-evp-issuer`, warm call), which fits. The two-person rule needs two tokens, about 126k, which is over the flat 100k verify cap.
3. Gmail, the only live issuer, is Ed25519 on both signatures, and gmail.com has no DNSSEC. So the user base that exists today can't be anchored trustlessly.
4. Chrome generates the KB key itself, so the browser key can't be the chirping device key. The only binding is `nonce`.

What would revive it: a sidecar with `precompiles` set or per-entity verify budgets over 100k; then our own DNSSEC P-256 domain with an `["ES256"]` issuer, one token per tx, in a normal tx or a staked payer frame. The origin-trial token expiry of 2026-11-17 is after the Nov 8 submission. It only matters if someone replays the demo after the event, and then they need a fresh token.

The UNREACHABLE and open items below about Workspace coverage (s6) and a live ES256-only Chrome test (Open items) are **moot for Mumbai**. They are not open questions. They matter again only if EVP is revived.

## TL;DR for the hackathon

- Token is an SD-JWT: `<EVT>~<KB-JWT>` with zero disclosures. EVT `typ=evt+jwt`, KB-JWT `typ=kb+jwt`.
- Chrome picks the browser key from the issuer's `signing_alg_values_supported`, **first recognized entry wins**. `["ES256"]` gives a P-256 browser key. Empty or missing list gives Ed25519. A list with only unknown algs fails.
- Gmail advertises `["EdDSA"]` only and signs with Ed25519, no `kid`. So Gmail tokens are Ed25519 on both signatures. No cheap on-chain path for Gmail.
- gmail.com has no DNSSEC. Trustless on-chain anchoring of Gmail via DNSSEC is impossible.
- Our own issuer with `["ES256"]` gives an all-P-256 token (issuer sig + KB sig). Both are EIP-7951 / RIP-7212 checkable. sd_hash is SHA-256, also cheap on-chain.
- Android IS supported since Chrome 154. The recap is out of date there.
- Origin trial runs through Chrome 160. Tokens made before the extension expire 2026-11-17, so a fresh token is needed. For local dev, `chrome://flags/#email-verification-protocol` (flag name VERIFIED in chromium `chrome/browser/flag-metadata.json`; that it bypasses the OT token is per PyEVP README, untested).
- Third-party OT works since 154 only if the registrant is same-site to the issuer. A random dApp embedding a script cannot use it for Gmail.
- Mac stable on 2026-11-02 is at main@1706539 (= 156). 157 goes stable 2026-11-03, staggered rollout, so expect 156 or 157 during hacking (Nov 5-7). Ed25519/EdDSA dual spelling, exact-email echo, hyphenated Sec-Fetch-Dest all apply.

## 1. Token format and claims

| Claim | Status | Source |
| --- | --- | --- |
| Token is SD-JWT; Chrome returns issuer JWT + KB-JWT, no disclosures | VERIFIED | Aug 2026 blog: "returns only the Issuer-signed JWT and the Key Binding JWT without any disclosures included." https://developer.chrome.com/blog/email-verification-august-2026 |
| Parse with an SD-JWT parser, not by splitting on `~` | VERIFIED | same post |
| Issuance response is `{"issuance_token": "<sd-jwt>~"}`, trailing tilde required | VERIFIED | https://developer.chrome.com/docs/identity/email-verification/issuer |
| EVT header `typ: "evt+jwt"` | VERIFIED | IETF draft-02 s5.1; Chromium `evt_verifier.cc` rejects other typ (`kSdJwtInvalidTyp`) |
| Old README example shows `typ: evp-sd-jwt` | CONTRADICTED by current impl | WICG README (last update May 19 2026) decodes to `typ: evp-sd-jwt`; Chromium trunk requires `evt+jwt`. Use `evt+jwt`. https://github.com/WICG/email-verification-protocol |
| EVT required claims: `iss` (HTTPS origin), `iat`, `cnf.jwk`, `email`, `email_verified: true` | VERIFIED | draft-02 s5.1 https://www.ietf.org/archive/id/draft-hardt-email-verification-02.html ; Chromium checks each (MissingIss/Iat/Cnf/Email, InvalidEmailVerified) |
| `exp` | Not in draft-02. Chrome issuer guide example sets `exp = iat+300`. Chrome does not require it. | draft-02; issuer guide |
| KB-JWT claims: `aud` (RP origin, no path/slash), `nonce`, `iat`, `sd_hash` | VERIFIED | draft-02 s6.1; verifier guide https://developer.chrome.com/docs/identity/email-verification/verifier ; Chromium `email_verification_request.cc` sets aud = committed origin, sd_hash = b64url(SHA-256(issuance token string)) |
| Chrome iat window | VERIFIED (code) | `evt_verifier.cc`: both EVT and KB iat must be within now-5 min .. now+1 min |
| Chrome 156+: issuer must echo `email` byte-for-byte as submitted, else Chrome rejects | VERIFIED | issuer guide: "From Chrome 156, the browser checks that the EVT `email` claim matches the requested `email` byte-for-byte."; Oct 2026 blog https://developer.chrome.com/blog/email-verification-october-2026 |
| RP should still compare email case-insensitively | VERIFIED | verifier guide |
| `kid` optional; Gmail omits it, iterate JWKS | VERIFIED | Oct 2026 blog; live JWKS below has no `kid` |
| Recap links draft-00; current is draft-02 (2026-08-25), individual draft, no WG. Update the link. | VERIFIED | https://datatracker.ietf.org/doc/draft-hardt-email-verification/ |
| Spec says it does NOT prove inbox delivery | VERIFIED | WICG README: "they do NOT assert that the email was actually delivered to the user's inbox." |

## 2. Algorithms

### Issuer signature (EVT)

- Chromium accepts EVT `alg` in {`Ed25519`, `EdDSA`, `RS256`, `ES256`}. VERIFIED (code, `evt_verifier.cc` line ~37).
- IETF draft-02: "the polymorphic `EdDSA` identifier MUST NOT be used"; `Ed25519` SHOULD be in the list. VERIFIED. Chrome still accepts `EdDSA` during migration (crbug 561405995).
- Chrome emits only `Ed25519` since commit 273742834b "[EVP] Use fully-specified algorithm identifiers" (2026-09-28, main@1706493). Current Mac stable is at main@1706539, so this is in stable. VERIFIED.

### Browser key (cnf.jwk, KB-JWT, HTTP Message Signature)

- Selection code (Chromium trunk, `EmailVerificationRequest::Verify`): loop over `signing_alg_values_supported` in order; `Ed25519`/`EdDSA` -> Ed25519, `RS256` -> RSA-2048, `ES256` -> P-256; first hit breaks. Empty list -> Ed25519. Non-empty list with nothing known -> `kWellKnownUnsupportedSigningAlgorithm`. VERIFIED (code).
- Before 2026-09-28 the loop matched `EdDSA`, `RS256`, `ES256` (no `Ed25519`). So `ES256` works on Chrome 154/155 too. VERIFIED (code at parent commit).
- Same key signs the HTTP request and the KB-JWT; issuer copies it into `cnf.jwk`. VERIFIED (code comment: "Matches what the browser conveyed in the Signature-Key header, and so what the issuer echoes back in `cnf.jwk`").
- Recap claim "Advertise ES256 only: the browser key defaults to Ed25519 otherwise": VERIFIED with nuance. Default Ed25519 applies only when the list is empty. If the list holds Ed25519 before ES256, Chrome picks Ed25519. Putting ES256 first is enough; ES256-only is the safest.
- Issuer guide says "Chrome 154 and 155 require `"EdDSA"` in `signing_alg_values_supported`". That is about issuers who want Ed25519. It does not block ES256-only (code above). PLAUSIBLE reading; not tested in a live browser.
- Issuer guide does not explain ES256 selection at all. VERIFIED absence.

## 3. Chrome 153 HTTP Message Signatures change

- Chrome <=152: `application/x-www-form-urlencoded` POST with a signed `request_token` JWT (ephemeral key in `jwk` header). VERIFIED (Aug blog; issuer guide).
- Chrome 153+: `application/json` body `{"email": ...}` plus `Signature`, `Signature-Input`, `Signature-Key`, `Content-Digest` (sha-256). VERIFIED (Aug blog). Chromium commit 17dea46841 "[evp] Use message signatures (in addition to request_token)" 2026-07-31.
- Covered components: `"@method" "@authority" "@path" "content-digest" "signature-key"`, with `created`. VERIFIED (draft-02 s4.1, Chromium `CreateMessageSignatureParams`). No cookie covered (code comment links dickhardt/email-verification issue 11).
- Issuer MUST reject `created` more than 300 s off. VERIFIED (draft-02).
- `Signature-Key: sig=hwk;alg=...;kty=...;crv=...;x=...` (draft-hardt-httpbis-signature-key). From Chrome 156 `alg` is present and fully specified; older Chrome may omit it. VERIFIED (issuer guide; commit 273742834b message says pre-fix requests lacked required `alg`).
- `Sec-Fetch-Dest`: `emailverification` on <=153, `email-verification` on 154+. Accept both. VERIFIED (Oct blog; issuer guide).
- Aug blog says Chrome 153 reaches stable "at the end of August"; chromiumdash says 153 stable 2026-09-08. Minor date mismatch: https://chromiumdash.appspot.com/fetch_milestone_schedule?mstone=153

## 4. Origin trial

- Started Chrome 150, desktop. VERIFIED (Aug and Oct blogs).
- Register: https://developer.chrome.com/origintrials#/view_trial/10696049115004929 ; RP serves the token on the page with the email form. Issuers need no token. VERIFIED (OT blog https://developer.chrome.com/blog/email-verification-protocol-origin-trial).
- Extended through Chrome 160; old tokens expire 2026-11-17; renew. VERIFIED (verifier guide). Chrome 160 stable 2027-01-05 (chromiumdash).
- Third-party OT: not supported as of August (Aug blog); supported from 154 with "the origin trial registrant and the issuer must be same-site" (Oct blog). VERIFIED. For our use the RP page is ours, so first-party token is fine.
- User side: signed in to the provider in the same profile; "Verified Email" enabled at `chrome://settings/contactInfo`. VERIFIED (verifier guide).
- Dev flag `chrome://flags/#email-verification-protocol`: name VERIFIED in chromium `chrome/browser/flag-metadata.json`. Usable without OT token per PyEVP README https://github.com/gaato/pyevp (not a Google source, untested).
- Page API: `<input autocomplete="email">` + hidden `<input autocomplete="email-verification-token" nonce="...">`; no `navigator.credentials.get`. Verification fires when the user leaves the email field (Aug blog). VERIFIED.
- Android: recap says desktop only. CONTRADICTED: "Starting in Chrome 154, Chrome for Android supports email verification." (Oct blog). Not tested by us.
- Edge has an origin trial too. Per draft-02 s12 implementation status. Not checked further.
- Ship: "preparing to ship", no date. VERIFIED (Oct blog).

## 5. Issuer metadata and discovery

- DNS: `_email-verification.<email-domain> TXT "iss=<bare lowercase host>"`; only one TXT at that name. VERIFIED (draft-02 s3.1; Chromium commit f947146324 "Require a bare host name in the DNS iss= record" 2026-09-30).
- `/.well-known/email-verification` fields: `issuer` (origin, byte-equal to serving origin), `issuance_endpoint` (required), `jwks_uri`, `signing_alg_values_supported` (optional), `private_email_supported` (optional bool, draft-02). VERIFIED.
- Chrome rejects a mismatched `issuer`, but still allows it missing because "Google's issuer does not publish it yet" (code TODO crbug 565774086). Live Google doc now does include `issuer`. VERIFIED (code + curl).
- Login check: Chrome reads IdP sign-in status (Login Status API; `Set-Login` header or `navigator.login.setStatus`) and the FedCM `/.well-known/web-identity` -> `accounts_endpoint`; the email must be in the accounts list. VERIFIED (code, issuer guide).
- Google's web-identity lives at `https://google.com/.well-known/web-identity`, not accounts.google.com (accounts.google.com returns 404). VERIFIED by curl. This matches FedCM's eTLD+1 rule. So own issuer: serve web-identity at the registrable domain.
- RP should validate DNSSEC where the domain is signed. VERIFIED (draft-02 s10.4).

Live probe (dig/curl, 2026-11-02):

```
_email-verification.gmail.com      "iss=accounts.google.com"
_email-verification.googlemail.com (none)
_email-verification.google.com     (none)
others tried (outlook.com icloud.com proton.me hello.coop ethglobal.com anthropic.com): none

https://accounts.google.com/.well-known/email-verification
{"issuer":"https://accounts.google.com",
 "issuance_endpoint":"https://accounts.google.com/gsi/email-verification/issue",
 "jwks_uri":"https://verifiablecredentials-pa.googleapis.com/.well-known/vc-public-jwks",
 "signing_alg_values_supported":["EdDSA"]}
JWKS: 5 keys, all OKP/Ed25519, alg EdDSA, no kid.
gmail.com: no DS record, no RRSIG on the TXT (not DNSSEC-signed).
```

## 6. Workspace / custom domains with Google

- No Google doc says Google's issuer covers Workspace or custom domains. UNREACHABLE (no source found; searched Chrome docs, Workspace help, blogs). MOOT for Mumbai (EVP is out, see Decision).
- Mechanically, a Workspace domain would need the TXT pointing at accounts.google.com, and Google's issuer would have to agree to sign for it. Google's own corp domain google.com has no TXT. googlemail.com has none either.
- Treat as: Gmail only. Workspace = not covered until proven by a live Chrome test with a Workspace account on a domain whose admin adds the TXT. Do not plan the demo on it.

## 7. Libraries (versions on 2026-11-02)

| Library | Version | Notes |
| --- | --- | --- |
| PyEVP (`pyevp`) | 0.2.0 (2026-10-04), alpha | RP + issuer; badge "spec: draft-hardt-02"; "Tested with Chrome 154". https://pypi.org/project/pyevp/ |
| `@aspect-evp/core`/`issuer`/`verifier`/`cli` (repo aspect-evp/evp-js) | 0.2.0 (2026-07-14) | This is "evp-js"; no npm package named `evp-js`. Published before Chrome 153; README has no message-signature text. Likely stale. |
| `@hellocoop/email-verification` | 3.1.0 (2026-09-01) | Hellō (draft author's company). README shows EdDSA/RS256/ES256; no message-signature text in README. |
| `email-verification-api` | 0.2.0 (2026-09-07) | EVT+KB verifier, unknown author. |
| go-evp (OffloopHQ) | no tags; last push 2026-07-09 | RP verifier only; pre-153 era. https://github.com/OffloopHQ/go-evp |
| `@sd-jwt/core` | 0.24.1 | used in Chrome demos |
| `jose` | 6.2.14 | used in Chrome demos |
| `http-message-sig` | 0.3.0 (Cloudflare web-bot-auth) | Chrome issuer demo |
| `structured-headers` | 2.1.1 | Chrome issuer demo |

Recap names "evp-js, PyEVP, go-evp (verifier only)": VERIFIED as existing; only PyEVP shows signs of tracking Chrome 154+. Pin: `pyevp==0.2.0`, `@sd-jwt/core@0.24.1`, `jose@6.2.14`, `http-message-sig@0.3.0`, `structured-headers@2.1.1`.

## 8. What this means for the on-chain design (recap s6)

- Own DNSSEC domain + own issuer with `signing_alg_values_supported: ["ES256"]` -> issuer sig P-256, browser key P-256. On-chain: two P-256 verifies (EIP-7951) + SHA-256 for sd_hash and signing inputs. JWS ES256 sigs are raw r||s, 64 bytes. Fine.
- Chrome itself verifies the EVT before handing it to the page (EvtVerifier in browser). The page also gets the final string; nothing stops us from sending it on-chain.
- Chrome generates the browser key itself inside `Verify` (`GenerateEcP256()` / `GenerateEd25519()`); the page cannot supply it. So recap s6 option "the key-binding key equals the chirping device key" is CONTRADICTED by Chromium trunk. Only `nonce` can bind the EVT to the proximity session.
- Nonce: the RP page sets `nonce` attribute, so nonce = hash(new key) or hash(proximity session) works.
- `sd_hash` = b64url(SHA-256(issuance token string)) and that string includes the trailing `~`. The on-chain hash must include it. aud = page origin, so the contract must pin the expected origin string.
- iat freshness: Chrome enforces 5 min at mint time; the contract should enforce its own window using block.timestamp.
- Gmail path stays Ed25519 + no DNSSEC -> needs a key registry or ZK; not trustless.
- Own issuer must also serve FedCM web-identity + accounts endpoint + Login Status, echo email byte-exact, accept both Sec-Fetch-Dest spellings, and verify message signatures with `created` within 300 s.

## Open items

All moot for Mumbai (EVP is out, see Decision at the top). Kept for a revival.

- Live test: ES256-only issuer on Chrome 156/157 desktop and Android. Not done (no browser run here).
- No library was confirmed to verify ES256 `hwk` message-signature requests on the issuer side. The PoC issuer may need hand-rolled RFC 9421 verification (small: rebuild signature base, verify P-256 r||s).
- Does Chrome enforce origin-trial for issuer pages? Docs say no token needed for issuers. Fine.
- Workspace coverage: needs a live test.
