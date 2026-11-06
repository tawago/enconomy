# WVP: the rules

Page script is the attacker. A compromised renderer is out of scope: the browser's activation bit is set by renderer messages. A script played the wallet in all checks.

## 1. The origin comes from the browser

**Rule.** A login is bound to origin O only if the browser says the tab's top frame is at O. `sw.mjs` takes `port.sender.origin` and requires `frameId` 0. No message field carries an origin. The patched browser also reads `GetLastCommittedOrigin()` itself.

**Stops.** A page lying about its origin. A's proof or token, on a challenge B really issued, gets `wrong_nonce` from B.

**Doesn't stop.** A lookalike site. It gets a login for its own origin, if you sign in there.

## 2. A login needs a real click

**Rule.** A login starts only from a trusted click on `button[data-wvp-signin]`, or a trusted Enter in the field. The switch only locks the field. There's no prompt, and the wallet shows only when the approval is missing or expired.

- **Stock Chrome:** this check is `login.js` reading `isTrusted`. Nothing else backs it, so it's weaker.
- **Patched browser:** `prove` also calls `wvpPrivate.approve`, which consumes the tab's transient activation in the browser process. One gesture is good for one attempt. No gesture gives `no_activation`.
- A login that went to enrollment resumes without a new gesture. The grant is per tab, single use, and lasts 5 s.

**Stops.** A script's `.click()`, on both builds.

**Doesn't stop.** Clickjacking, also on a first visit. A hidden Sign in under a fake button gets a real click. With the switch on, the site learns you hold a valid credential. The proof only works for that page's origin. On the patched browser, any gesture on the page counts for about 5 s, and then only `login.js` narrows it to the button.

## 3. The typed value must match

**Rule.** A named login exists only if the typed value equals the approved name or address, after normalizing. Otherwise `no_match`, and nothing is signed. Text counts only if each edit was a real key, paste or IME session.

**Stops.** A page asking for a name you didn't type. `bob.eth` when enrolled as `alice.eth`.

**Doesn't stop.** Our event rules are a list and may be incomplete. A page that gets past them learns only that you hold a name it already guessed. Any field with this markup can ask, whatever its label says.

## 4. A named login covers this site and this challenge

**Rule.** K signs `["wvp-direct-login-v1", origin, challenge, now, claim]`. Site S accepts only if all of these hold. The site rebuilds the bytes with its own origin and an unused challenge it issued (`wrong_nonce`). A wallet signature recovers the message's address (`wrong_wallet`). The message names this K (`wrong_key`). It's unexpired and lasts at most 7 days (`expired`, `bad_lifetime`). Its domain is on the site's pinned list (`wrong_domain`). A name resolves to that address (`not_owner`). It's in the exact form `createSiweMessage` writes (`bad_message`).

**Stops.** Replay at another site. Reuse of a challenge. Swapping K. A sold name, at the next lookup. An approval signed for another domain.

**Doesn't stop phishing.** The approval is a bearer power. If you approve an attacker's K with the pinned domain, they log in as you at every site pinning it, named and anonymous, until expiry. There's no revocation: Revoke deletes K on this browser only. A wallet with a SIWE domain check should warn on the wrong page. Not tested. A wallet without one, or a blind-signing prompt, won't. The host of the pinned page is a small trusted party: if it's compromised, it can ask for its own K.

**Limits.** Only plain EOAs: `ecrecover`, no ERC-1271. Selling the name doesn't cut off a typed address until expiry.

## 5. One signature, one K, two modes

**Rule.** One signature approves K for named and anonymous. The issuer takes that signature in the background. K must also sign `["wvp-issue-v1", issuer origin, nonce]`, for a one-time nonce from `/nonce`. Then the issuer applies the same checks, plus the ENS lookup, and signs the credentials.

**Stops.** A site replaying your signature to get credentials: `no_key_proof`, since it has no K. A different K: `key_mismatch`. A reused or unknown nonce: `nonce_unknown_or_used`. No holder text reaches the signed credential, so the forged digest stays shut.

**Doesn't stop.** K's public key reaches every site on a named login, while anonymous proofs use the same K. So anonymous unlinkability rests on the proof hiding K. The only check is a byte search for K's x and y in one anonymous bundle: not found. That's not a zero-knowledge argument, and OpenAC isn't audited. Don't claim unlinkable.

The issuer can still issue false credentials, and it sees your name and address once. Credentials round down to the hour, so in the last hour anonymous asks the wallet again. Not tried.
