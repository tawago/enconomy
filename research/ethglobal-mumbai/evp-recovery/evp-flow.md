# EVP laptop flow: what Chrome actually does, and how to test it

Checked 2026-11-03. Chromium = github.com/chromium/chromium `main`, read only, nothing run.
Tags: VERIFIED (primary source opened), CONTRADICTED, UNREACHABLE, PLAUSIBLE (my reading, not tested).
Main files read: `content/browser/webid/delegation/{dns_request,email_verification_request,email_verifier_network_request_manager,evt_verifier,sd_jwt}.cc`, `content/browser/webid/{network_request_manager,idp_network_request_manager,idp_accounts_parser}.cc`, `components/autofill/content/browser/integrators/email_verifier/email_verifier_delegate.cc`, `components/autofill/content/renderer/email_verification_handler.cc`, `chrome/browser/about_flags.cc`, `third_party/blink/renderer/platform/runtime_enabled_features.json5`, `chrome/browser/chrome_content_browser_client.cc`.

## Short answer

- The nonce can carry a 32-byte hash as `0x` + 64 hex. Chrome has no length cap and no format rule. It must be non-empty. VERIFIED.
- `aud` is the page's committed origin, set by the browser. The page can't change it. The contract can and should pin it. VERIFIED.
- There IS a command-line switch that replaces issuer DNS discovery: `--dns-txt-resolver-url-prefix=<url>`. Undocumented, added for WPT tests, in Chrome 156+. VERIFIED. So we can test with `alice@tawago.com` before touching DNS.
- Chrome does not check DNSSEC. It asks `dns.google` over HTTPS and ignores the AD bit. VERIFIED.
- Simplest real setup: issuer at `https://tawago.com` itself, served by Worker routes on a few paths. TXT `iss=tawago.com`. PLAUSIBLE (design choice).

## 1. Page side (the recovery page on the laptop)

| Fact | Status | Source |
| --- | --- | --- |
| Markup: `<input autocomplete="email">` plus `<input type="hidden" autocomplete="email-verification-token" nonce="...">` in the **same form**. `<input hidden>` also accepted. | VERIFIED | renderer `email_verification_handler.cc` `FindTokenFieldForEmailField` |
| **Superseded for Chrome 156.** On `main` Chrome reads the internal nonce slot. Stable 156 reads `GetAttribute("nonce")`: `el.nonce = …` alone mints nothing, silently. Use `setAttribute("nonce", …)`. It works under a header CSP too. | LIVE, Chrome 156.0.8078.80 | `live-chrome/README.md` failure 1 and "CSP header run" |
| The nonce is read **when the email field loses focus**. Set it before the user tabs out. | VERIFIED | delegate `OnFieldLostFocus` -> `QueryNonce` |
| Trigger only if the email was typed by the user (`last_modifier == kUser`) and is a valid address. A fill from Chrome autofill is a second path (`OnFillOrPreviewForm`). | VERIFIED | delegate |
| **Dedup gotcha:** same field + same lowercase email will not trigger again (LRU of 5). To retry with a new nonce, reload the page or change the email. | VERIFIED | delegate `last_verified_values_` |
| Empty nonce: flow stops with "The email verification token field has no nonce or an empty nonce attribute." Also KB check fails `kKbMissingNonce`. | VERIFIED | delegate `kTokenFieldHasNoNonce`; `evt_verifier.cc` |
| No nonce length limit or charset rule in Chrome. It goes into the KB-JWT JSON as a string. | VERIFIED (absence in code path renderer -> mojo -> `sd_jwt.cc`) | |
| Spec wants a random nonce, >=128 bits, unique per request. A hash of public data is not "random". | VERIFIED (draft-02 §2.2) | Mitigation: put the chirp transcript hash (which has fresh randomness) inside ctx. Unique per attempt anyway because of `recoveryNonce`. |
| Token lands in the hidden field right before the `submit` event (`WillSendSubmitEvent`). Only if the email field still holds the same value. Use a real submit or `form.requestSubmit()`, then `preventDefault()` and read the field. | VERIFIED | renderer handler |
| Page must be top-level or same-origin with all ancestors. No cross-origin iframe, no fenced frame, no opaque origin. | VERIFIED | `email_verification_request.cc` `CheckIfVerifiable` |
| Debug strings show in `chrome://autofill-internals` (e.g. "feature or origin trial is not enabled", "user turned off email verification in the settings"). | VERIFIED (strings in delegate) | |

## 2. aud

- KB payload `aud = GetLastCommittedOrigin().Serialize()`: `https://host` or `https://host:port`, no slash, no path. VERIFIED (`email_verification_request.cc` Verify).
- Chrome checks `aud` against the same origin before it hands the token to the page. VERIFIED (`evt_verifier.cc` `kKbInvalidAudience`).
- On chain: yes, check it. The browser key signs the KB payload, so `aud` is as trusted as the rest of the KB. Store `keccak("https://recover.tawago.com")` in the config hash; compare at the `"aud":"` offset (the PoC already does this). A phishing page on another origin gets its own origin in `aud` and fails. VERIFIED design, already tested in `../poc-evp-issuer` (negative test "other aud").
- KB payload key order: Chrome builds it with `base::DictValue` (a sorted map), so keys come out as `aud, iat, nonce, sd_hash`, no spaces. PLAUSIBLE (code reading, no live token yet). The offsets design doesn't depend on it.
- Which origin to use:
  - Demo / real: one fixed origin we own, e.g. `https://recover.tawago.com` (Pages) or the existing `https://webapp.enconomy.dev`. Pick once; it goes into the account config.
  - Quick tunnel tests: the origin changes each run (`https://<random>.trycloudflare.com`). Deploy the test account with that aud, or make aud a per-deploy parameter. A named tunnel with a fixed hostname avoids this but needs a CNAME (a DNS change, user's call).

## 3. Turning EVP on: flag vs origin trial

- `chrome://flags/#email-verification-protocol`, `kOsAll` (desktop and Android). VERIFIED (`about_flags.cc`).
- If the feature is **overridden on** (flag, or `--enable-features=EmailVerificationProtocol`), Chrome enables EVP "no matter what the OT status is". If not overridden, it needs the default-on feature AND a first-party or third-party OT token on the page. VERIFIED (delegate `GetOrCreateEmailVerifier`).
- OT config: `origin_trial_os: [win, mac, linux, chromeos, android]`, `origin_trial_allows_third_party: true`. VERIFIED (`runtime_enabled_features.json5`).
- OT runs through Chrome 160; old tokens expire 2026-11-17. VERIFIED earlier (`../notes/evp.md` §4). For our own laptop and phone, use the flag. Use an OT token only if a judge's Chrome must run it.
- User pref must be on: Settings > Autofill > "Verified Email" (`chrome://settings/contactInfo`). VERIFIED (delegate `kUserPrefDisabled`; verifier guide).

## 4. Android Chrome 154+

- "Starting in Chrome 154, Chrome for Android supports email verification." Same API, same prerequisites. Setting: Settings > Addresses and more > Verified Email. VERIFIED (Chrome blog, Oct 2026).
- Android stable today: 156.0.8078.79. VERIFIED (chromiumdash `fetch_releases`).
- Command-line switches on a non-rooted phone: enable `chrome://flags` "Enable command line on non-rooted devices", put switches in `/data/local/tmp/chrome-command-line`. VERIFIED (chromium.org "Run Chromium with flags"). That this works on **stable** Chrome (not just Canary/dev): PLAUSIBLE, not tested. The first token in that file is ignored by convention (`_ --switch ...`): PLAUSIBLE.
- Not tested on a phone by us. UNREACHABLE.
- For our flow the laptop does EVP; the phone only chirps. Android EVP is a bonus.

## 5. Issuer endpoints Chrome needs

Order of calls (VERIFIED, `email_verification_request.cc`):
1. TXT `_email-verification.<email domain>` via the resolver (section 6). Exactly one record, starts with `iss=`, value must be a bare host. Issuer = `https://` + host.
2. In parallel:
   - `GET https://<iss>/.well-known/email-verification` (at the issuer host itself, uncredentialed). `issuer` must equal the origin byte-for-byte if present. `issuance_endpoint` required, same origin as issuer. `jwks_uri`, `signing_alg_values_supported` optional. Put `["ES256"]` to get a P-256 browser key.
   - Login Status check: if Chrome knows the issuer is logged out, stop. Unknown counts as logged in.
   - `GET https://<eTLD+1 of iss>/.well-known/web-identity` (FedCM). Must have **both** `accounts_endpoint` and `login_url` (else Chrome looks for `provider_urls` and fails). `accounts_endpoint` must be same origin as the issuer.
   - `GET accounts_endpoint` with cookies. Needs an account with `id` and the email (case-insensitive match).
3. `POST issuance_endpoint`, JSON `{"email":…}`, cookies, `Sec-Fetch-Dest: email-verification`, RFC 9421 headers. Reply `{"issuance_token":"<EVT>~"}`.
4. Chrome fetches JWKS, verifies EVT, builds KB, verifies again, then gives it to the page.

Details that bite:
- web-identity is fetched at the **eTLD+1** (`ComputeWellKnownUrl`, private registries included). For `evp.tawago.com` it is `https://tawago.com/.well-known/web-identity`. VERIFIED.
- `trycloudflare.com` and `pages.dev` are on Chrome's bundled public suffix list, so `<x>.trycloudflare.com` is its own eTLD+1: everything can live on one host. `workers.dev` is also a suffix, but a worker host is `<name>.<acct>.workers.dev`, whose eTLD+1 is `<acct>.workers.dev`, so web-identity would be fetched at the account root. Avoid `workers.dev` for the issuer. VERIFIED (`net/base/registry_controlled_domains/effective_tld_names.dat`).
- Cookies on accounts and issuance: initiator is the RP origin, so Strict cookies never go; cross-site needs `SameSite=None; Secure`. VERIFIED (`network_request_manager.cc`; issuer guide troubleshooting).
- Chrome never opens `login_url` in the EVP flow. The user must sign in at the issuer first. VERIFIED (no login path in EVP code).
- Both `.well-known` responses must be `Content-Type: application/json`. VERIFIED (issuer guide).
- RFC 9421 base Chrome signs: `"@method": POST`, `"@authority": <host[:non-default port]>`, `"@path"`, `"content-digest"`, `"signature-key"`, then `"@signature-params": ("@method" "@authority" "@path" "content-digest" "signature-key");created=N`. `Signature-Key: sig=hwk;alg="ES256";crv="P-256";kty="EC";x="…";y="…"` (JWK fields, sorted, `d` dropped). Same signer as the JWT, so ES256 is raw r||s. VERIFIED (`CreateMessageSignature*`). `../evp-recovery/issuer-worker/worker.mjs` rebuilds this base correctly as far as I can read.
- EVT and KB `iat` must be within now-5 min .. now+1 min. VERIFIED (`evt_verifier.cc`).
- Echo `email` byte-for-byte (156+). VERIFIED (issuer guide).

## 6. Overriding DNS discovery (local testing)

VERIFIED (`content/browser/webid/delegation/dns_request.cc`):

```
static constexpr char kDnsTxtResolverUrlPrefixSwitch[] = "dns-txt-resolver-url-prefix";
... if (cmd->HasSwitch(...)) prefix = cmd->GetSwitchValueASCII(...);
    else prefix = GetContentClient()->browser()->GetDnsTxtResolverUrlPrefix();
query_url = prefix + EscapeQueryParamValue(hostname)
```

- Default prefix in Chrome: `https://dns.google/resolve?type=txt&do=1&name=`. VERIFIED (`chrome_content_browser_client.cc`).
- The response must look like dns.google JSON: `Status` 0, `Answer[]` with `type` 16 and `data` (unquoted string). VERIFIED (parser + live probe of gmail).
- Added in commit c5bb976936 "[EVP] Add initial WPT test coverage…" at main@1704840. 156 branched at 1706539, so it is in 156 and 157, not in 155. VERIFIED (GitHub commit + chromiumdash).
- No public doc mentions it (web search found nothing). Treat it as a test hook that may change.
- AD bit is never read. Chrome trusts dns.google. VERIFIED. (`do=1` is in the URL but unused.)
- Negative caching: dns.google answered NXDOMAIN for `_email-verification.tawago.com` with SOA TTL 1800. If Chrome asks before the TXT exists, expect up to ~30 min of stale "no record". VERIFIED probe; cache behaviour PLAUSIBLE.
- Other knobs found: `FedCmPreservePortsForTesting` feature lets `iss=` carry a port and serves web-identity at the issuer host. VERIFIED (code). Not needed with tunnels.

## 7. Issuer login options

- The spec leaves user auth to the issuer: "valid authentication cookies", else 401 `authentication_required`. VERIFIED (draft-02 §8.4).
- So a passkey login is fine. Chrome just needs a cookie and `Set-Login: logged-in` (or `navigator.login.setStatus("logged-in")`). VERIFIED (issuer guide).
- Minimal passkey on a Worker without a database (PLAUSIBLE design):
  - One-time enroll page: `navigator.credentials.create` with rpId `tawago.com`; read `response.getPublicKey()` (SPKI) and `rawId`; paste both into Worker secrets `PASSKEY_SPKI`, `PASSKEY_ID`.
  - Login: challenge = HMAC(secret, time bucket), stateless. Verify assertion with WebCrypto: data = authenticatorData || SHA-256(clientDataJSON); check `type`, `challenge`, `origin`, rpIdHash, UP/UV flags. The WebAuthn signature is DER, WebCrypto wants raw r||s, so convert.
- Hackathon shortcut: the sibling worker uses a shared secret form. Fine for tests. Passkey is the upgrade.

## 8. Minimal Cloudflare Worker issuer for tawago.com

Recommended layout: issuer origin = `https://tawago.com` (the apex already serves a site, 200 today). Worker routes only on:

```
tawago.com/.well-known/email-verification
tawago.com/.well-known/web-identity
tawago.com/evp/*        (jwks, accounts, login, issue)
```

Why apex: issuer origin and the web-identity eTLD+1 are the same, so no split. Same-origin rule for accounts and issuance holds. Option B: `evp.tawago.com` as the issuer, plus a route for `tawago.com/.well-known/web-identity` pointing to `https://evp.tawago.com/accounts` and `/login`.

Needs:
- Secrets: `ISSUER_JWK` (P-256, made locally), `EMAIL` (the one mailbox), `LOGIN_SECRET` or passkey SPKI.
- Metadata: `{"issuer":"https://tawago.com","issuance_endpoint":"https://tawago.com/evp/issue","jwks_uri":"https://tawago.com/evp/jwks","signing_alg_values_supported":["ES256"]}`.
- web-identity: `{"accounts_endpoint":"https://tawago.com/evp/accounts","login_url":"https://tawago.com/evp/login"}`.
- Cookie `Path=/evp; Secure; HttpOnly; SameSite=None`.
- `../evp-recovery/issuer-worker/worker.mjs` already does all of this on a single host with paths `/jwks`, `/accounts`, `/login`, `/issue`. For the apex layout, move those under `/evp/` (and set `ISSUER_HOST=tawago.com`). As written it fits the quick-tunnel test unchanged.
- Workspace / Cloudflare Email Routing is irrelevant to EVP: EVP never sends mail. The issuer just vouches for the address. Honest caveat: our issuer vouches for whoever has the login. It proves "the tawago.com issuer said so", not inbox control.

Ready-to-paste TXT (do not publish until you decide; one record only at that name):

```
Type:    TXT
Name:    _email-verification            (in zone tawago.com)
Content: iss=tawago.com
TTL:     Auto
```

For Option B use `iss=evp.tawago.com`. Do not add `https://`, a port or a path: Chrome rejects them.

## 9. Tunnel test plan (laptop, no DNS change)

Nothing below has been run. `cloudflared 2026.10.3` is installed at `/opt/homebrew/bin/cloudflared`.

1. Keys: `cd research/ethglobal-mumbai/evp-recovery/issuer-worker && node keygen.mjs > keys/issuer.jwk.json` (fresh test key).
2. Two quick tunnels (two sites, so cookies are tested cross-site):
   - `cloudflared tunnel --url http://127.0.0.1:8787` -> note `https://A.trycloudflare.com` (issuer)
   - `cloudflared tunnel --url http://127.0.0.1:8788` -> note `https://B.trycloudflare.com` (recovery page)
3. Start servers:
   - `ISSUER_HOST=A.trycloudflare.com EMAIL=alice@tawago.com LOGIN_SECRET=<pick> FAKE_DNS=1 node serve.mjs issuer 8787`
   - `node serve.mjs rp 8788`
4. Smoke check with curl: `/.well-known/email-verification`, `/.well-known/web-identity`, `/jwks`, `/dns?name=_email-verification.tawago.com` all on A return JSON.
5. Fresh Chrome profile (must be a new process for switches to apply):
   ```
   open -na "Google Chrome" --args --user-data-dir="$PWD/chrome-evp-profile" \
     --enable-features=EmailVerificationProtocol \
     --dns-txt-resolver-url-prefix="https://A.trycloudflare.com/dns?name="
   ```
   Check `chrome://version` shows 156+ and the switches.
6. In that profile: turn on Verified Email at `chrome://settings/contactInfo`. Open `https://A.trycloudflare.com/login`, sign in (sets cookie + `Set-Login`).
7. Open `https://B.trycloudflare.com/`. Paste a test new-key, press Set nonce, type `alice@tawago.com`, press Tab. Allow the prompt. Press Get token.
8. If nothing happens: `chrome://autofill-internals` (flow result text), DevTools Issues, and the issuer log lines in the terminal (each request prints with `Sec-Fetch-Dest`).
9. Check the token offline: `aud` must be `https://B.trycloudflare.com`, `nonce` the value set. Feed it to `../poc-evp-issuer` `verify` with that aud and issuer key.
10. Phone (optional): put the same two switches in `/data/local/tmp/chrome-command-line` (see section 4), force-stop Chrome, repeat 6-7 on the phone.

Then the real path (after the user adds the TXT and deploys the Worker): drop `--dns-txt-resolver-url-prefix`, keep the flag, use `alice@tawago.com` against `https://tawago.com`. Watch the 30-minute negative cache.

## 10. Open

- No live Chrome run yet: real KB bytes, prompt UI, Android. UNREACHABLE today.
- Whether Android stable honours `/data/local/tmp/chrome-command-line`. PLAUSIBLE.
- The rp.html sketch uses SHA-256 for the nonce; the contract expects keccak(ctx). Swap before wiring.
