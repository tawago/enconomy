# Live EVP in real Chrome, fully local

Nov 3, 2026. Result: **works.** Real Chrome minted `EVT~KB` for `alice@tawago.test` with `nonce` = the DESIGN.md ctx vector. The unchanged `poc-evp-issuer` verifier accepts it in forge. 13 tokens minted, 13 verify. Two more under a CSP header later the same day: 15 of 15.

Nothing left this machine. No DNS change, no tunnel, no on-chain tx. Server binds 127.0.0.1 only. Keys are fresh test keys in `tmp/keys/` (gitignored).

## Setup

- Chrome: Google Chrome stable **156.0.8078.80** (arm64, macOS 27.2). It auto-updated from 156.0.8078.74 during the session; the first launch ran .74, every token came from .80.
- One https server, `serve.mjs`, on 127.0.0.1:8443, self-signed P-256 cert for `tawago.test` and `*.tawago.test`. It routes by `Host`:
  - `tawago.test` -> `../issuer-worker/worker.mjs`, unchanged, with `ISSUER_HOST=tawago.test`, `EMAIL=alice@tawago.test`, `FAKE_DNS=1`. ES256 only.
  - `recover.tawago.test` -> `rp.html`.
- Every request is logged with headers and body to `tmp/requests.jsonl`.
- Driver: `cdp.mjs`, Node 24 global WebSocket, no npm.

Exact switches (`launch.sh`, also written to `tmp/chrome-argv.txt`):

```
--user-data-dir=<live-chrome/tmp/profile>
--no-first-run --no-default-browser-check
--remote-debugging-port=9333
--enable-features=EmailVerificationProtocol
--host-resolver-rules=MAP tawago.test 127.0.0.1:8443, MAP recover.tawago.test 127.0.0.1:8443, EXCLUDE localhost
--dns-txt-resolver-url-prefix=https://tawago.test/dns?name=
--ignore-certificate-errors
--auto-grant-email-verification-permission-for-testing
--enable-logging=stderr --v=0            (debug only)
```

Run:

```
node serve.mjs &                       # needs tmp/keys/{tls.key,tls.crt,issuer.jwk.json}, see below
./launch.sh --auto-grant-email-verification-permission-for-testing &
node cdp.mjs login                     # issuer cookie + Set-Login
node cdp.mjs flow                      # nonce = ctx-vector evpNonce; writes tmp/token-latest.txt
node analyze.mjs token-chrome-1.txt tmp/keys/issuer.jwk.json
node fixture.mjs tmp/keys/issuer.jwk.json token-chrome-1.txt tokens/*.txt
cd verify && forge test -vv
```

Keys: `openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -keyout tmp/keys/tls.key -out tmp/keys/tls.crt -days 30 -subj /CN=tawago.test -addext "subjectAltName=DNS:tawago.test,DNS:*.tawago.test"` and `node ../issuer-worker/keygen.mjs > tmp/keys/issuer.jwk.json`. If you remake the issuer key, the saved tokens no longer verify against it; mint new ones.

## What worked first time

- `--host-resolver-rules` with a port (`MAP host 127.0.0.1:8443`) works. Chrome still thinks the origin is `https://tawago.test` on 443, so `iss=tawago.test` stays a bare host and `Host:` / `@authority` is `tawago.test`. No root, no 443 bind.
- `--dns-txt-resolver-url-prefix` works on stable 156. Chrome asked `GET /dns?name=_email-verification.tawago.test`.
- `.test` is an unknown TLD; Chrome treated `tawago.test` as its own eTLD+1 and fetched web-identity at `https://tawago.test/.well-known/web-identity`.
- The issuer worker's RFC 9421 check passed on Chrome's real request (13/13). So `worker.mjs`'s signature base is right.
- CDP key events (`Input.dispatchKeyEvent` per char, then Tab) count as user typing (`last_modifier == kUser`).
- Verified Email setting was already on in a fresh profile (`chrome://settings/contactInfo`, "Automatically verify your email").

## Failures, in order

1. **No trigger at all, no log.** Cause: I set the nonce with `tok.nonce = "0x…"` (IDL slot only). Chrome 156's renderer reads `token_element.GetAttribute("nonce")` (`components/autofill/content/renderer/email_verification_handler.cc` at tag 156.0.8078.74). The attribute was absent, the callback got `""`/none, and the delegate returned silently. Fix: `setAttribute("nonce", n)`. **This contradicts `evp-flow.md` §1** ("Chrome reads the internal nonce slot, so `el.nonce = …` works, also under CSP"). That is true on `main`, not on 156. Consequence I guessed at the time: under a header CSP Blink blanks the `nonce` attribute. Tested later (CSP header run below): it does not blank an attribute set by script after load, so a header CSP is fine. `chrome://autofill-internals` showed nothing about EVP for this case.
2. **Native permission bubble.** With the nonce fixed, Chrome ran DNS, metadata, web-identity, accounts, then stopped at a browser-UI bubble: "Verify this email automatically? While you're signed in, tawago.test can confirm alice@tawago.test on supported sites… [Not now] [Verify]". Screenshot: `tmp/prompt-native-bubble.png` (full desktop capture, kept in gitignored tmp). CDP cannot click it (not a page target). I did not click it with OS automation. Fix: the test switch `--auto-grant-email-verification-permission-for-testing` (`components/autofill/core/common/autofill_switches.cc`), read in `EmailVerifierDelegate::TriggerVerification`. From source, not tested: after one real "Verify" click Chrome seems to store `allowed` per email in the pref `kAutofillEmailVerificationState` and skip the bubble next time. Check before the demo leans on it.
3. My own bug: `node cdp.mjs flow alice@tawago.test ""` passed an empty nonce; Chrome silently did nothing (no request). Fixed with `||`. Same silent failure as 1: an empty nonce produces no network traffic, so look at the page, not the issuer log.
4. First launch after a kill did not open the debug port within 4 s. Waiting 6 s fixed it.

## Bytes Chrome produced

Token 1 (`token-chrome-1.txt`, 870 bytes), decoded in `analysis-1.json`:

```
EVT header  {"alg":"ES256","typ":"evt+jwt","kid":"tawago-1"}          (ours)
KB header   {"alg":"ES256","typ":"kb+jwt"}                            (Chrome)
KB payload  {"aud":"https://recover.tawago.test","iat":1793692936,"nonce":"0x22cbad28b2d580114630eb65e51e47305a5d6efbbb8c6d48fca64bd7d4b5655a","sd_hash":"m-74TJoXj-MpwYMOvL2mIA3Rj4M1Bbw0sPUxZ7hEED4"}
```

- KB header: exactly `{"alg":"ES256","typ":"kb+jwt"}`. No `kid`, no `jwk`. Same bytes in all 13. The contract can pin it by keccak.
- KB claim order: `aud, iat, nonce, sd_hash`, no spaces. Same in all 13. Confirms the `base::DictValue` guess in `evp-flow.md` §2.
- `nonce` is passed through byte-exact: `0x` + 64 lowercase hex.
- `aud` = `https://recover.tawago.test` (no port, no slash).
- KB `iat` = issuance second; EVT `iat` equal in this run.
- Signatures: raw 64-byte r||s for both. **High-s happens.** Over 12 sampled tokens Chrome's KB `s` was spread uniformly over (0, n); 7 of 13 KB sigs were high-s. Chrome does not normalize. The issuer (Node WebCrypto) doesn't either. EIP-7951 at 0x100 accepts both, so fine; a contract must not demand low-s.
- `sd_hash` = b64url(SHA-256(EVT + "~")), matches.
- Browser key is fresh per request (13 distinct `cnf` keys).

Chrome's requests to the issuer (from `tmp/requests.jsonl`):

- `GET /dns?name=_email-verification.tawago.test`, `/.well-known/email-verification`, `/jwks`: `Sec-Fetch-Dest: email-verification`, no cookie.
- `GET /.well-known/web-identity`: `Sec-Fetch-Dest: webidentity`, no cookie. `GET /accounts`: `webidentity`, with cookie.
- `POST /issue`: body `{"email":"alice@tawago.test"}` (29 bytes), `Origin: null`, `Sec-Fetch-Dest: email-verification`, cookie, and

```
content-digest:  sha-256=:<b64>:
signature-key:   sig=hwk;alg="ES256";crv="P-256";kty="EC";x="…";y="…"
signature-input: sig=("@method" "@authority" "@path" "content-digest" "signature-key");created=1793692936
signature:       sig=:<b64 of 64-byte r||s>:
```

  `x`/`y` in Signature-Key are the same key as the EVT `cnf.jwk`.

## Forge verify

`verify/` is a forge project with `src/EvpVerifier.sol` and `lib/forge-std` symlinked from `../../poc-evp-issuer` (contract unchanged, same compiler settings). `fixture.mjs` writes `verify/test/LiveFixture.sol` from the live tokens; offsets use `indexOf`, so order doesn't matter.

Trick: the PoC checks `nonce == hex(keccak(newKey))`. Passing the 224-byte ctx preimage as `newKey` makes that `nonce == ctx`. No contract change needed for this test.

`forge test -vv` (forge 1.4.3): 6 pass.

- `test_all_tokens`: all 15 Chrome tokens verify (13 first run + 2 CSP run) (issuer sig, cnf binding, KB sig, aud, email, email_verified, nonce == ctx, both iat, sd_hash).
- `test_first_token_gas`: 870-byte token, **63,176 gas** warm. PoC synthetic was 63,111.
- `test_revert_other_ctx` (one bit of deadline flipped -> `BadClaim(12)`), `test_revert_other_aud` (`https://recover.tawago.com`), `test_revert_stale` (iat + 901 s).

## For the build

- Recovery page: `tokenField.setAttribute("nonce", evpNonce)` before the email field blurs. Don't rely on `el.nonce` on 156. A header CSP is fine (see the CSP run below); the earlier advice "no nonce-CSP header" was a guess and is withdrawn.
- Demo: one real click on the "Verify" bubble per email per profile, or launch the demo Chrome with the auto-grant switch. Say which on stage.
- Contract: pin KB header keccak (`{"alg":"ES256","typ":"kb+jwt"}`) if you want; offsets can now be fixed for the KB since order and header are stable. Keep accepting high-s.
- `evp-flow.md` §1 nonce-slot row and §10 "no live Chrome run" are out of date; this file wins for Chrome 156.

## CSP header run (Nov 3, later, for REFUTE.md section 5)

Question: DESIGN section 9 wants a header CSP on the recovery page. Under a header CSP, Blink hides `nonce` attributes. Does a dynamic `setAttribute("nonce", ...)` still mint?

Answer: **yes.** Same Chrome 156.0.8078.80, same profile, same switches. `serve.mjs` now takes `CSP_MODE`; `cdp.mjs flow` takes `SETTER=attr|idl` and prints the attribute as Chrome will read it.

| CSP header | how the nonce was set | attribute read back | `POST /issue` | token |
| --- | --- | --- | --- | --- |
| none (control) | both | value | yes | yes |
| `default-src 'self'; script-src 'self'; ...`, script in `/rp.js` | both | value | yes | `tokens/tok-csp-self.txt` |
| same | `setAttribute` only | value | yes | yes |
| `script-src 'nonce-<random>'; ...`, inline script with that nonce | both | value | yes | `tokens/tok-csp-nonce.txt` |
| same | `setAttribute` only | value | yes | yes |
| same | `el.nonce = ` only | `null` | **no** | none, no error |

- Blink hides nonce attributes present at parse time. It does not blank one set later by script on an input. The hiding never touched our field.
- The IDL-only row repeats failure 1 under CSP: nothing happens, nothing is logged.
- The two saved tokens carry the vector ctx as `nonce` and verify in `verify/` (now 15/15).
- So DESIGN section 9 keeps the header CSP. Use `default-src 'self'` with the script in its own file; it needs no per-response nonce.

One more harness bug, same family as failure 3: `node cdp.mjs flow "" ...` typed an empty email (`??` keeps `""`). Fixed with `||`.

## Files

- `serve.mjs`, `rp.html`, `launch.sh`, `cdp.mjs`, `analyze.mjs`, `fixture.mjs`
- `token-chrome-1.txt`, `tokens/tok-*.txt`: 13 real tokens (test keys)
- `analysis-1.json`: decoded token 1
- `verify/`: forge project, `test/Live.t.sol`, generated `test/LiveFixture.sol`
- `tmp/` (gitignored): keys, profile, `requests.jsonl`, `chrome.log`, `prompt-native-bubble.png`
