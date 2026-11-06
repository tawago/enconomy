# WVP browser: the three rules

Page script is the attacker. A compromised renderer is out of scope, see the end. "Checked" means run on this patched build on 2026-11-06, with scripted X input, one try each. A script played the wallet. No person has used it.

## 1. The origin given to the prover comes from the browser process

**Rule.** A proof is bound to origin O only if the browser's own record says the tab's top frame is at O.

**How.** `sw.mjs` takes `port.sender.origin`, which the browser fills in, and `frameId` must be 0. Then `wvpPrivate.approve` reads `GetPrimaryMainFrame()->GetLastCommittedOrigin()` in the browser process. A mismatch stops it. `bindNonce(origin, nonce)` is the only use. No message field carries an origin, so a page has nothing to lie with.

**Checked.** The native prompt showed `http://site-a.test:8802`, `http://site-b.test:8803` and `http://race.test:8805` on the right tabs. Site A and B each accepted their own proof.

**Not rerun on this build.** The test where A's proof is sent to B (`wrong_nonce`). It passed with the extension on stock Chrome. The site code and binding are the same.

## 2. A page can't trigger a proof without real user activation

**Rule.** No proof, and no enrollment tab, unless the tab's top frame has transient activation. One gesture is good for one attempt.

**How.** The first thing `prove` does, before reading any credential, is `approve` with `requireActivation`, which calls `ConsumeTransientUserActivation()` in the browser process. Next comes the stricter check in `login.js`: real keys, a real leave, a trusted click on the switch. Then the native prompt, once per origin and mode.

**One exception.** A login that passed the gate and went to enrollment resumes without a new gesture, because the gesture was in the other tab. The grant is per tab, single use, and dies after 5 s. The prompt still shows.

**Checked**, asking through the extension's own port:

```
no gesture:             no_activation
after a real click:     passes the gate, goes on to enrollment
same click, second use: no_activation
```

Also: Tab 6.5 s after the last key still passes, since Tab is itself a gesture. "Not now" gives no proof.

**Holes.**

- Any gesture on the page counts for about 5 s. A page script can use that window, and then only `login.js` stands between it and a proof. That list of rules may be incomplete.
- Clickjacking on a site you already allowed still works. The prompt only guards the first time per origin and mode. For anonymous, the site learns you hold a valid credential.
- The prompt can't be covered, since it's browser UI. Not tested against a page that resizes or scrolls under it.

## 3. The typed name must match the credential

**Rule.** A named proof exists only if the typed value equals the credential's name or address, after normalizing.

**How.** `parseIdentifier(typed)`, then `id.claim` against `h.name` and `h.address`, in the service worker, before the prompt. No match gives `no_match` and no proof. The site's `siteCheck` then checks the claim against the proof (`wrong_policy`).

**Checked.** `bob.eth` on Site A, enrolled as `alice.eth`: "No proof", no prompt.

**Hole.** "Typed" is `login.js` reading events. A name forged into the field that passes those rules gets a proof, but only for the holder's real name, bound to that page's origin. So the page learns the holder has that name, which it had to guess first.

## Out of scope

- **Compromised renderer.** The browser's activation bit is set by renderer messages, per the comment in `RenderFrameHostImpl::UpdateUserActivationState`. So this gate is against page script, not against a compromised renderer.
- `autocomplete` isn't read by the browser in this design. `login.js` reads it.
