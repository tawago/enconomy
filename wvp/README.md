# WVP

WVP is the wallet version of Chrome's Email Verification Protocol. You approve once with your wallet. Then your browser proves "I own `alice.eth`" to any site, with no wallet popup and no issuer watching.

**This is a prototype. A script played the wallet in every run. No person has clicked through it, and no real wallet has touched it.**

There are two builds:

- **Extension on stock Chrome.** Ran on a Mac. The full test pass ran here.
- **Patched Chromium with the same extension.** Ran on Linux x64 only. It adds a browser-side gesture check and a native prompt. See `../browser/`.

## How it works

1. The extension makes a browser key, K. K can sign but can't be exported.
2. Your wallet signs one message: "Approve browser key K for `alice.eth` and `0x...` until this time."
3. The issuer checks the signature and looks up the ENS name. It signs two SD-JWT credentials over K, one for the name and one for the address. They last 24 h at most.
4. The browser runs OpenAC's slow Prepare step once per credential and keeps the result.
5. A site puts a challenge in its form. You type your name and leave the field, or flip Anonymous.
6. The extension makes a proof, bound to the origin Chrome reports and to the challenge. No wallet is involved. It puts the proof in a hidden field.
7. The site sends the token to its server. The server checks the challenge, origin, claim, issuer key and proof.

The issuer sees your name and address when you enroll. It never sees which sites you visit.

A site only writes this. It calls nothing:

```html
<form>
  <input type="text" autocomplete="wvp">
  <input type="checkbox" data-wvp-anonymous>
  <input type="hidden" autocomplete="wvp-token" nonce="64 lowercase hex chars">
</form>
```

The token is JSON: `{v, challenge, now, claim, bundle}`. `claim` is the name, the lowercase address, or `null`. The page can follow progress through `data-wvp-state` on the hidden field and a `wvp-state` event.

## Run it

Ran on Node 24 and Chrome 157, on an 8 GB Mac. Close other big apps. The prover peaks near 3 GiB and each site server near 1.1 GiB.

First make the third-party folder. `prover/README.md` has the steps. Nothing in this repo contains those files. Then:

```sh
cd wvp
npm ci --ignore-scripts
export WVP_THIRD_PARTY=/path/to/third_party
extension/build.sh                 # Makes extension/build/extension. Not checked in.
node demo/try-it.mjs               # Opens Chrome on a temp profile. You type. Quit Chrome to stop.
node demo/try-it.mjs --smoke       # A script plays you for one login, then it quits.
```

The demo makes a throwaway wallet key and issuer key on each start. Both live only in memory. Everything stays on 127.0.0.1, with `*.test` names mapped for that one Chrome. Set `WVP_CHROME` if Chrome isn't at the usual Mac path.

To try a real wallet, use a throwaway account. This hasn't been done:

1. Run `node demo/servers.mjs --owner 0xYOUR_ADDRESS`.
2. Start Chrome on a new profile with `--host-resolver-rules="MAP *.test 127.0.0.1"`.
3. Install the wallet. Load `extension/build/extension` unpacked.

We don't know if a wallet will inject and sign on an http page.

## Folders

| Folder | What |
|---|---|
| `extension/` | Extension source and `build.sh` |
| `issuer/` | Issuer logic and its server, with the enrollment page |
| `site/` | The site check and a demo site server |
| `key-host/` | Stands in for a CDN. Serves the two proving keys |
| `lib/` | Rules shared by issuer, site and extension |
| `demo/` | Starts everything. Holds the labelled fake wallet |
| `prover/` | Our wrapper, the SDK patch, and how to get the rest |

`extension/src/sw.mjs` works on both builds. It uses `chrome.wvpPrivate` only if the patched browser provides it.

The manifest's `key` is a public key: 2048-bit RSA, in SPKI form. It only fixes the extension's ID. Its private half is not in this repo.

## Real and fake

| Part | Status |
|---|---|
| Chrome, MV3 extension, threads in an offscreen document | **Real.** Temp profile, loaded through the debug protocol, not a store. |
| Site origin in the proof | **Real**, from the browser. On `.test` names mapped to 127.0.0.1. http only. |
| Site servers, sessions, verify, challenge check | **Real.** Separate processes. |
| Prepare, Show, reblind | **Real** proofs with the published 1k keys. Modified OpenAC build. |
| K | **Real** and non-extractable. Export was refused, also after a restart. |
| Issuer code | **Real.** Throwaway key, localhost. |
| Wallet | **FAKE.** A script signs with a throwaway key. The prompt is drawn by the demo and labelled FAKE WALLET on screen. |
| User | **FAKE** in test runs. A script sends trusted input through the debug protocol. On the Linux build, a script sent real X input. |
| ENS | **FAKE.** A local table. Nothing is registered. `alice.eth` here has nothing to do with the real name. |
| Mainnet ENS lookup | **Real but separate.** `mainnetLookup` in `lib/ens-lookup.mjs` read `vitalik.eth` on 2 RPCs. It isn't wired into the login flow. |
| Key download speed | **FAKE.** Real bytes from localhost, about 1 s. It took 24 s once on a real network. |
| Expired credential test | **FAKE expiry.** A hook set the extension's local copy of `exp` back. |
| Attack tests | Real proofs against real site code, but our own scripts. **Not an audit.** |
| Soundness, unlinkability | **Not proven, not audited.** |

## What you should know

- **OpenAC is modified.** Stock OpenAC never ran. See the table below.
- **Not audited.** No one outside this project has reviewed it.
- **The issuer is trusted, also in anonymous mode.** An anonymous proof tells the site "a valid credential from this issuer". The issuer can issue false credentials, and it sees your name and address. A sold ENS name keeps working until expiry.
- **Fake wallet and ENS table,** unless you bring a real wallet and wire in a real lookup. Neither has been done.
- **The name slot is 63 bits.** A name with a colliding digest gets a credential that a site accepts for the victim's name. scrypt raised a guess from about 8 ns to 58 ms and 32 MiB. The salt is fixed, and GPU cost isn't measured. A bigger slot needs a new circuit and new keys.
- **The K slot is still open.** A forged digest placed in K's x gets a real Prepare over a forged name. Only the missing secret for that x stops Show. Getting both costs about 2^128 by reasoning, not by test. This is where a review should start. The fix, K signing at issue, isn't built.
- **The patched browser was built and run on Linux only.** A judge can't run it on a Mac. The extension on stock Chrome can run on a Mac, without the native prompt or the gesture check.

More weak points:

- **Clickjacking.** On stock Chrome, a page put an invisible switch over a fake button, and a real click made a hidden proof for that page. On the patched build the native prompt guards the first use per origin and mode. Later uses are still open. The damage: the site learns you hold a valid credential.
- **"The user typed this" is our code reading events.** It held against every trick we tried, but it's a list and may be incomplete. Any gesture opens a window of about 5 s on the patched build, and then only this list stands in the way.
- **Any field with this markup can ask.** A site can label the box "search names". If you type your own name, it gets a proof.
- **Autofill and password managers get no proof.** A site script that rewrites the field as you type also blocks it.
- **Thin privacy evidence.** Upstream leaves blind values in proofs that link them. The holder wipes those and the site refuses unwiped proofs. The check is a byte comparison of 3 proofs. It's not a zero-knowledge argument. A site can't recognize a returning anonymous user, on purpose.
- **Thin byte-flip sweep.** About 0.4% of proof bytes. It wasn't rerun on this issuer. Neither was the first test suite. 48 of 495 flips passed OpenAC's verify alone, so the site's own form check in `lib/bundle.mjs` is required.
- **You need an ENS name to enroll.** An address with no name can't.
- **Revoke is local.** It deletes K here. The issuer has no revocation list.
- **http only.** https wasn't tested.
- **The offscreen document holds 2.4 to 3 GiB and never closes.**
- **`__debug` is still in the service worker.** Pages can't reach it. It's a test hook, and one call changes the local expiry.
- **Site denial of service.** `/challenge` is open and verify blocks about 1.4 s.
- **Time slack.** The holder picks `now`, and the site allows 300 s either way. So a cheater gets 5 min past expiry.
- **The extension runs on every page it serves.** Here that's `*.test`. A real build would carry a broad permission warning.
- **Not tried on the patched build:** the suite run on stock Chrome, including A's proof at B, a restart with the same profile, the toolbar popup. A page that resizes under the prompt wasn't tried either.

### The forged digest

An earlier version had a real hole, found in our own review. The circuit only proves a disclosure's digest is somewhere in the signed payload. Our issuer signed the holder-chosen name, so a cheater hid a forged digest inside their own name. They got a real server to answer `{"loggedIn":true,"name":"alice.eth"}`, and logged in with an expired credential.

The fix: the issuer no longer signs the name, and `lib/payload-check.mjs` refuses any digest-shaped text it doesn't expect. No circuit or key changed. Keep that check. Our circuit-cases passed 28 of 28 and 13 of 13 checks. The old issuer accepts the forgery in the same test, and this one doesn't. Those tests aren't in this folder.

### What differs from stock OpenAC

Pin: `privacy-ethereum/zkID` at `b395e09c225ff45b003f0087c28e2e208e22f944`. Spartan2 and `ecdsa-spartan2` sources, `show.wasm` and the published 1k keys aren't changed.

| What | Stock | What ran | Why |
|---|---|---|---|
| SDK `present()` | Takes a raw device key | Also takes a ready signature | K must stay unreadable |
| Prover WASM glue | wasm-bindgen output | Our wrapper around the pinned Spartan2 | The tools couldn't be installed |
| `jwt_1k.wasm` | circom 2.2.3 | circom 2.1.8, pragma rewritten | Same reason |
| Key handling | Decoded on each call | Decoded once and kept | Speed |
| Threads | One | 4, with a hand-made pool. Needs `RUSTC_BOOTSTRAP=1` and `-Zbuild-std` | Speed |
| Blind values in the proof | Left in, which links proofs | Holder wipes them | Upstream linking bug |
| Site check | SDK verify | SDK verify plus a form check tied to byte offsets | SDK verify doesn't read those bytes |
| Name claim | Any | A 63-bit scrypt digest of the name | The slot only holds 19 digits |

## Measured numbers

The raw logs and test drivers aren't published. Each run below had a script as the wallet.

### Extension on stock Chrome

Mac14,2, Apple M2, 8 GB, macOS 27.2, Chrome 157.0.8103.38, Node 24.22.1, AC power, other work running. One test run, 108 of 108 checks. "Login" starts when you leave the field and ends at the site's answer.

| What | Value |
|---|---:|
| Login, all 12, median | 4.87 s |
| Named / anonymous / address, median | 4.87 / 4.75 / 4.93 s |
| First login at a site that hadn't verified yet | 6.85 s |
| Show + reblind, median of 12 | 3.36 s (3.24 to 3.45) |
| Site's verify | About 1.45 s, first one about 3 s |
| Enrollment, extension's part | 21.1 s first time, 19.1 and 18.8 s later |
| of which two Prepares and saves | 18.6, 17.9, 17.6 s |
| First login overall, from the click on approve | 28.4 s |
| Prover process peak | 2,979 MiB |
| Each site server peak | About 1,140 MiB |
| Proof / token | 165,749 B / about 221 KB |
| Stored Prepare state | 90 MB |
| Holder download / site keys / extension | About 293 MB / about 280 MB / 14 MB |

Proving isn't under 3 s. Those speeds need kept keys, opt-level 3 and 4 threads. Same machine, closest build to stock, one thread, Chrome 156: Prepare 14.8 s, Show 7.98 s, Verify 4.70 s. In Node with the plain wrapper, one thread: 14.39, 7.91, 5.06 s. Both are earlier runs, with heavy swap. Neither is stock.

### Patched Chromium

Linux x64, 32 vCPU Xeon 2.80 GHz, 125 GB RAM, Ubuntu 24.04, other jobs running. Tag 157.0.8103.38. One run each.

| What | Value |
|---|---:|
| Login with no prompt, `is_debug=false`, `dcheck_always_on=false` | 8.5 s |
| Same, `dcheck_always_on=true` | 9.9 s |
| Demo binary, 57,566 steps | 1 h 38 m 09 s |
| Output folder / `chrome` binary | 7.2 GB / 533 MB |
| Patch build, first good one, 173 steps | 1 m 18 s |

The gap to the Mac's 4.87 s looks like the Xeon against the M2. That's a guess.

Runs on this build, with scripted X input: `alice.eth`, Tab, fake wallet, Sign, native prompt, Prove gave `Verified: alice.eth`. On Site B, Anonymous and "Not now" gave no proof, then Prove gave `Verified: anonymous`. `bob.eth` gave no proof and no prompt. A second login at the same site gave no prompt and no wallet. A plain form with a submit button clicked at once waited, then posted 233,951 bytes. The gesture check is in `../browser/SPEC.md`.

## Not included

- Test suites, raw logs and screenshots. So you can't rerun the numbers or the circuit-cases from this folder.
- Path C, the version that proves wallet ownership directly in the circuit. It wasn't run: no setup, no proof.
- zkID, the keys and all binaries. See `prover/README.md`.
