# WVP

WVP is the wallet version of Chrome's Email Verification Protocol. You approve once with your wallet. Then your browser logs you in to any site, as your ENS name, your address or anonymously, with no more wallet popups.

**This is a prototype.** The repoint story has been run once by hand with Rabby, plain EOA accounts, on our own ENS v2 deployment on devnet chain 1337. Everything automated still uses a scripted wallet.

**The main way to try it is the extension in plain stock Chrome.** It needs no special build. It runs on a Mac.

A patched Chromium runs the same extension. It adds two things:

- **No install.** The extension ships beside the binary.
- **The browser's own real-click check.** In stock Chrome that check is only the extension's `login.js`, which is weaker.

The patched build ran on Linux x64 only. See `../browser/`.

## How it works

**Enrolling, once.**

1. Your first Verify (see below) opens a small window with a static approval page at `enroll.test:8806`. A wallet needs a web page to inject into. If the window can't be opened, it's a plain tab.
2. The extension makes a browser key, K. K can sign but can't be exported.
3. Your wallet signs one message: "Approve browser key K to log in to websites as `alice.eth` and `0x...`, or anonymously, until this time. No other use." It lasts 24 h. No issuer is needed for this.
4. In the background, the browser takes that signature to the issuer. K answers a nonce from the issuer, so a site holding your signature can't do this. The issuer signs two SD-JWT credentials over K. The browser then runs OpenAC's slow Prepare step, with no wallet.

**Named login, first time on a site.** Type your name and leave the field, or click Sign in, or press Enter. A dark bubble opens under the field: "Verify this name automatically?", with Not now and Verify. Verify is the go-ahead. If this browser has no approval yet, the approval window comes next. Then K signs this site's origin and challenge. The site checks K's signature, the wallet's approval, and that ENS says the wallet owns the name. There's no issuer and no circuit. Not now closes the bubble and sends nothing.

**Named login, after that.** The extension remembers that you pressed Verify on this site, under this approval. With a valid approval there's no bubble. Press Enter or click Sign in, and you're in. A new approval means a new K, maybe a new wallet, so every site asks again. Remove approval forgets the sites too.

**Anonymous login.** Tick the box, which only locks the field, and click Sign in. There's no bubble, because no name goes to the site. It shows only on a site that can check proofs. The extension makes a zero-knowledge proof, bound to the site's origin and challenge. The site checks it against the issuer's key. If Prepare is still running, you wait. If the issuer is down, named login still works, and anonymous tells you to try later. The wallet doesn't ask again.

### What the site sees

| Login | The site sees |
|---|---|
| Named, typed a name | The name, your wallet address, K's public key, the signed message and your wallet's signature |
| Named, typed an address | The same, including the name. The whole signed message goes along. A name-only site refuses this |
| Anonymous | That you hold a valid, unexpired credential from this issuer. K should stay hidden, see below |

K's public key is the same at every site until you enroll again. So sites can link your named logins. They see your address anyway. A site holds your wallet's signature, but without K it can't log in as you.

The issuer sees your name and address once, right after you sign, even if you never use anonymous. It never sees which sites you visit.

### What a site writes

A site calls nothing:

```html
<form>
  <input type="text" autocomplete="wvp">
  <input type="checkbox" data-wvp-anonymous>
  <input type="hidden" autocomplete="wvp-token" nonce="64 lowercase hex chars">
  <button type="button" data-wvp-signin>Sign in</button>
  <div data-wvp-status></div>
</form>
```

The extension fills the hidden field with JSON. A named token is `{v: 2, kind: "direct", challenge, now, claim, message, walletSig, key, loginSig}`. An anonymous one is `{v: 1, challenge, now, claim: null, bundle}`. The page can follow progress through `data-wvp-state` on the hidden field and a `wvp-state` event. It draws its own spinner and check from that. `done` means a token was made, not that the site accepted it. A real press on Sign in or Enter sets the state at once, `idle` if there's none yet, so a page that sees no state a moment later knows the extension isn't in this tab and can say so.

`data-wvp-status` is optional. The extension writes reasons the page must not learn into a closed shadow root there, one line at a time, in a fixed font and height. With no such element, the page gets state only. Besides that line, the extension draws one thing on a page, the Verify bubble. No other overlay and no toast.

**The bubble is drawn by the extension, inside the page.** It's a closed shadow root in the top layer. So a page can't read it or press it, but a page can cover it or draw a look-alike. A shipped browser would draw it itself, outside the page. Chrome does that for EVP. Our Chromium patch still holds a native prompt, but it's switched off, so that build shows this same bubble. See `../browser/README.md`.

A login starts on a real click on Verify, or, on a site already verified, a real click on Sign in or Enter in the field. A page's script can't press Verify: it has no way into the closed root, and the handler checks `isTrusted` and the target. Verify also ignores clicks in its first 500 ms, and the bubble closes if a script edits its element.

Leaving the field can open the bubble, and nothing more. On a site already verified, it does nothing. That's one difference from Chrome's EVP, which goes ahead when you leave the field, because its token stays empty until submit. Here the page can read the token as soon as it's written, and Chrome marks a script's `blur()` as trusted, so leaving the field can't count as you agreeing.

If the site refuses a token, its page sets `data-wvp-verdict` on the hidden field to the reason and fires a bubbling `wvp-verdict` event. That's how the extension hears `not_owner`.

A site server started with `--name-only` refuses logins that read no ENS, with reason `name_only`. A typed address reads no ENS, so it would get past a repoint. This is a site setting. The demo sites turn it on.

## Run it

Ran on Node 24 and Chrome 157. Close other big apps. The prover peaks near 3 GiB and each site server near 1.1 GiB.

First make the third-party folder. `prover/README.md` has the steps. Nothing in this repo contains those files. Then:

```sh
cd wvp
npm ci --ignore-scripts
export WVP_THIRD_PARTY=/path/to/third_party
extension/build.sh                 # Makes extension/build/extension. Not checked in.
node demo/try-it.mjs               # Opens Chrome on a temp profile. You type. Quit Chrome to stop.
```

`--smoke` and `--smoke-repoint` are out of date. They predate the bubble and never click Verify, so they stop there and fail. Runs described below as seen with them are from before the bubble.

The demo makes two throwaway wallet keys and an issuer key on each start. They live only in memory. Its wallet prompt and the bar above the approval page are labelled "Demo wallet (scripted)" on screen. Blobzon and BlobChannel, at `blobzon.test:8802` and `blobchannel.test:8803`, are fictional demo sites. Their names are parodies, and their goods and videos are drawn from plain shapes. Everything stays on 127.0.0.1, with `*.test` names mapped for that one Chrome. Set `WVP_CHROME` if Chrome isn't at the usual Mac path.

To try a real wallet, use a throwaway account. Only Rabby has been tried, once, by hand. For Rabby there's a ready path, see [The same story with Rabby](#the-same-story-with-rabby). By hand, any wallet:

1. Run `node demo/servers.mjs --owner 0xYOUR_ADDRESS`.
2. Start Chrome on a new profile with `--host-resolver-rules="MAP *.test 127.0.0.1"`.
3. Install the wallet. Load `extension/build/extension` unpacked.

Other wallets are untried.

### The repoint story

A wallet approves this browser. A site logs you in by name, reading ENS at each login. Then the name's address record moves to a new wallet. The same browser with the same approval gets `not_owner`. You approve with the new wallet, and you're in under the same name.

```sh
node demo/try-it.mjs --repoint         # You play it. The steps print in the terminal.
node demo/repoint.mjs alice.eth 0xNEW  # The repoint itself, in another terminal.
```

Both start no issuer, no key host and no verifying keys. Named login doesn't need them, and no Prepare starts because the issuer can't be reached. So anonymous is off here. The extension still has to be built once.

On `not_owner`, the extension forgets the approval and says so in the form. Your next Sign in opens the bubble, and Verify opens the approval window. Pick Wallet B in the Demo wallet bar. Approving makes a new K.

Seen with `--smoke-repoint` on stock Chrome, before the bubble, a script playing the user and both wallets. Wallet A logged in as `alice.eth`. After the table edit, the same approval got `not_owner`. Wallet B approved and logged in as `alice.eth`. A typed address got `name_only`. A script's `.click()` on Sign in, with the name typed for real and an approval in place, did nothing: no tab, no token, no result. A real click on that same field then logged in with no wallet prompt, with the site's answer in under 0.1 s. The page then holds its spinner and check for about a second on purpose, so a person can see them. The table edit stands in for the cold key and the chain, so this run didn't touch a chain.

The sites leave out the anonymous box here, because they can't check proofs. From reading the code, not from a run: a hand-made anonymous token gets `no_proofs`.

### The repoint story on a chain

The same story on our own ENS v2 deployment on devnet chain 1337. It isn't real ENS, and the wallet is still FAKE.

```sh
node demo/try-it.mjs --repoint --ens deployment --deployment <deployment.json> --name probe.eth --wallet-a-key <hot key file>
```

Sites read the chain at each login. Wallet A signs with the key in that file. It's read when the demo starts and handed to Chrome in memory, so it isn't written to the build or the repo. Wallet B is a new throwaway key. The repoint is the cold-key transaction from `repoint.mjs`, which must sit beside the deployment file. The hand run prints the exact command. The demo stops first unless the name points at Wallet A, and prints the command that puts it back. It doesn't point the name back at the end. Anyone who can read the approval page's memory can read that key, so use a key that holds nothing.

Seen with `--smoke-repoint` on stock Chrome, before the bubble, a script playing the user and both wallets: Wallet A logged in as `probe.eth`, a cold-key transaction moved the name to Wallet B, the same approval got `not_owner`, Wallet B approved and logged in.

### The same story with Rabby

Run once by hand: the user played the repoint story with Rabby, plain EOA accounts, on our own ENS v2 deployment on devnet chain 1337. The small approval window and the bubble were built after that run, so Rabby hasn't been tried with them.

```sh
node demo/try-it.mjs --wallet-setup   # Once. Opens Chrome on its own kept profile, at Rabby's store page. You install it and make two throwaway accounts.
node demo/try-it.mjs --repoint --real-wallet --ens deployment --deployment <deployment.json> --name probe.eth
```

Nothing fake is injected, and you do every step, including switching accounts in Rabby. The script never sees a wallet key. Never import a seed phrase that holds real money. Each start wipes WVP's data and the demo sites' data, so the first login asks for approval. The rest of the profile stays, Rabby included. ENS is still our own deployment on devnet 1337. `--profile DIR` picks another folder.

To read a chain with no demo, start the sites with `--ens deployment --deployment file.json`. The file holds `{ rpc, chainId, universalResolver }`. `demo/repoint.mjs` only changes the table.

## Folders

| Folder | What |
|---|---|
| `extension/` | Extension source and `build.sh` |
| `issuer/` | Issuer logic and server. `serve-approve.mjs` is the static approval page, a separate server |
| `site/` | The two site checks, `direct-verify.mjs` and `site-check.mjs`, a demo site server, and the two fictional sites in `brands/` |
| `key-host/` | Stands in for a CDN. Serves the two proving keys |
| `lib/` | Rules shared by issuer, site and extension |
| `demo/` | Starts everything. Holds the labelled fake wallet |
| `prover/` | Our wrapper, the SDK patch, and how to get the rest |

`extension/src/sw.mjs` works on both builds. It uses `chrome.wvpPrivate` only if the patched browser provides it.

The manifest's `key` is a public key: 2048-bit RSA, in SPKI form. It only fixes the extension's ID. Its private half is not in this repo.

## Real and fake

| Part | Status |
|---|---|
| Chrome, MV3 extension, threads in an offscreen document | **Real.** Temp profile, or a kept one with `--real-wallet`. Loaded through the debug protocol, not a store. |
| Site origin | **Real**, from the browser. On `.test` names mapped to 127.0.0.1. http only. |
| Site servers, sessions, both checks, challenge check | **Real.** Separate processes. |
| Prepare, Show, reblind | **Real** proofs with the published 1k keys. Modified OpenAC build. |
| K | **Real** and non-extractable. |
| Issuer code | **Real.** Throwaway key, localhost. |
| Wallet | **FAKE** in every automated run. A script signs with a throwaway key, or in chain mode with the key file you pass. The prompt is drawn by the demo and labelled. **Real once:** the user ran `--real-wallet` by hand with Rabby, plain EOA accounts, on our devnet 1337 deployment. |
| User | **FAKE** in automated runs, and a person in that one Rabby run. A script sends trusted input through the debug protocol. On the Linux build, a script sent real X input. |
| ENS | **FAKE** in the default demo. A local table in a temp file, read again at each login. Nothing is registered. `alice.eth` here has nothing to do with the real name. In chain mode: real ENS v2 contracts, our own deployment on devnet 1337, not real ENS. |
| Repoint | **FAKE** in the default demo. `demo/repoint.mjs` edits that file. No chain, no transaction, no cold key. In chain mode: a real cold-key transaction on devnet 1337. |
| Second wallet | **FAKE** in automated runs. A second throwaway key, picked in the Demo wallet bar on the approval page. With `--real-wallet`, your second Rabby account, run once by hand. |
| Name-only | **Real** check, but a site setting. A site without it still takes a typed address until expiry. |
| Chain lookup | **Real on our devnet.** `--ens deployment` reads a Universal Resolver through viem. Tried only against our own deployment on chain 1337. |
| Mainnet ENS lookup | **Partly.** `site/serve.mjs --ens mainnet --rpc URL` is read-only. The verifier refused a throwaway wallet claiming `vitalik.eth` on a real read. It wasn't tried through the live site. The issuer's server uses only the table. |
| Approval page | **Local**, on http. |
| Key download speed | **FAKE.** Real bytes from localhost. |
| Attack tests | Real tokens and proofs against real site code, but our own scripts. **Not an audit.** |
| Soundness, unlinkability | **Not proven, not audited.** |

## What you should know

- **OpenAC is modified.** Stock OpenAC never ran. See the table below.
- **Not audited.** No one outside this project has reviewed it.
- **One real-wallet run, by hand.** The user played the repoint story once with Rabby on our devnet deployment, not on real ENS. Everything automated still uses a scripted wallet. No wider testing.
- **Only plain EOAs.** There's no ERC-1271, so a Safe can't enroll.
- **Sites see K's public key on a named login.** Anonymous proofs use the same K. So anonymous unlinkability depends on the proof hiding K. The only check is a byte search for K's x and y in one anonymous bundle: not found. That's not a zero-knowledge argument. **Don't call it unlinkable.**
- **Phishing an approval logs in as you until expiry.** Whoever holds K and your signature can do it, at every site pinning that approval domain, named and anonymous. There's no revocation. Remove approval, in the toolbar popup, deletes K on this browser only. Sites refuse more than 7 days, and the extension asks for 24 h.
- **The bubble is not a trust surface.** The extension draws it inside the page. A page can cover it or draw a look-alike, and it can tell the bubble opened, so it can tell a first use from a return. A shipped browser would draw it natively. The patched build's native prompt is off.
- **The bubble doesn't say what the site gets.** It says what the approval does. That a site sees your name and wallet address is in the site's form, if the site keeps that line, and in the approval window.
- **Clickjacking stays.** A page can place a decoy over the bubble that lets clicks through, so a real click lands on Verify. On a site already verified, a hidden Sign in under a fake button gets a real click, on both builds. With the switch on, the site learns you hold a valid credential. A named login still needs a typed value that matches.
- **The real-click check is weaker in stock Chrome.** It's only `login.js` reading `isTrusted`. A script's `.click()` does nothing. But nothing in the browser backs that check up.
- **The issuer is trusted in anonymous mode.** The proof tells the site "a valid credential from this issuer". The issuer can issue false credentials. It sees your name and address once. A sold name keeps working for anonymous until expiry.
- **The approval page's host is a small trusted party.** Sites and the issuer pin it. If it's compromised, it can ask for an approval of its own K.
- **Fake wallet and ENS table,** unless you bring a real wallet and use a real lookup.
- **Nothing tells you at the moment of a return login what a site saw.** The form says it before the click, if the site keeps that line. After, it's the toolbar badge and popup. Pin the icon, or you won't see the badge.
- **The status line is not a trust surface.** A page can hide it or draw a look-alike. Only the toolbar popup is out of the page's reach.
- **The name slot is 63 bits.** A colliding name gets a credential that passes a proof-based name check. scrypt raised a guess from about 8 ns to 58 ms and 32 MiB. The salt is fixed, and GPU cost isn't measured. The extension no longer makes named proofs. The demo sites, being name-only, refuse them. A site without `--name-only` still accepts them.
- **The K slot residual.** A forged digest placed in K's x gets a real Prepare over a forged name. Only the missing secret for that x stops Show. Getting both costs about 2^128 by reasoning, not by test. The issuer now also requires K to sign a nonce. Whether that closes this hasn't been reviewed. Start a review here.
- **The patched browser is a Linux demo.** It was built and run on Linux only.

More weak points:

- **Our "typed" rules are a list and may be incomplete.** Any gesture opens a window of about 5 s on the patched build, and then only `login.js` narrows it.
- **Any field with this markup can ask.** A site can label the box "search names". If you type your own name and click, it gets your login.
- **Autofill and password managers get no login.** A site script that rewrites the field as you type also blocks it.
- **Thin privacy evidence.** Upstream leaves blind values in proofs that link them. The holder wipes those and the site refuses unwiped proofs. The check was a byte comparison of 3 proofs.
- **Thin byte-flip sweep.** About 0.4% of proof bytes, and not rerun on this issuer. 48 of 495 flips passed OpenAC's verify alone, so the form check in `lib/bundle.mjs` is required.
- **You need an ENS name to enroll.** An address with no name can't.
- **Selling or repointing a name** stops named login at the next lookup, not before. A session already open stays open until sign out. Anonymous keeps working until expiry. A typed address also does, unless the site is name-only.
- **A site can make you approve again.** The extension can't see a site's answer, so it trusts the page's `not_owner`, once, right after a token it made from your click. One lying site drops your approval everywhere. It gets nothing from that: approving again takes your wallet's signature, on the pinned approval page.
- **http only.** https wasn't tested.
- **The offscreen document holds 2.4 to 3 GiB and never closes.**
- **Prepare still makes the address credential.** Only the name credential is used now. That's wasted time.
- **`__debug` is still in the service worker.** Pages can't reach it. It's a test hook, and one call changes the local expiry.
- **Site denial of service.** `/challenge` is open, and a proof check blocks about 1.4 s.
- **Time slack.** The holder picks `now`, and the site allows 300 s either way.
- **The extension runs on every page it serves.** Here that's `*.test`. A real build would carry a broad permission warning.
- **Not tried:** expiry in the browser, the last hour when anonymous asks the wallet again, a plain form with a submit button marked as Sign in, a second anonymous login, and a restart with the same profile.

### The forged digest

An earlier version had a real hole, found in our own review. The circuit only proves a disclosure's digest is somewhere in the signed payload. Our issuer signed the holder-chosen name, so a cheater hid a forged digest inside their own name. They got a real server to answer `{"loggedIn":true,"name":"alice.eth"}`, and logged in with an expired credential.

The fix: the issuer no longer signs the name, and `lib/payload-check.mjs` refuses any digest-shaped text it doesn't expect. No circuit or key changed. Keep that check. Rerun on the current path, our circuit-cases passed 37 of 37 checks. The old issuer still accepts the forgery in the same test, and this one doesn't. The HTTP version of the test wasn't rerun. Those tests aren't in this folder.

### What differs from stock OpenAC

Pin: `privacy-ethereum/zkID` at `b395e09c225ff45b003f0087c28e2e208e22f944`. Spartan2 and `ecdsa-spartan2` sources, `show.wasm` and the published 1k keys aren't changed. This only concerns anonymous login. Named login doesn't use OpenAC.

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

### Current flow, patched Chromium

A Linux x64 machine, other jobs possibly running. Tag 157.0.8103.38. **One run each.** "dcheck build" is `is_debug=false` with `dcheck_always_on=true`, which is slower. "Demo build" has it false.

| What | Value | Build |
|---|---:|---|
| Fresh profile, one signature, named login | 0.3 s | dcheck |
| Same, with the issuer killed | 0.3 s | dcheck |
| Named login again, no wallet | 0.2 s | Demo, before one K |
| Background Prepare, two credentials | 78 s, about 20 s to prove and 15 s to save each | dcheck |
| Anonymous on Site B while Prepare runs, from the click | 72.5 s | dcheck |
| Anonymous after the issuer came back, from the click | 90.8 s | dcheck |
| Named token / anonymous token | 1,144 B / about 221 KB | |
| Site's check of a named token, one-off | 160 ms first, about 3 ms after | |
| Same, with a real mainnet read that refused | 222 ms, including 2 reads | |

Also seen on this build: a script's `.click()` did nothing, `bob.eth` gave no proof, and a second wallet prompt never came. A's token and A's proof, each on B's real challenge, got `wrong_nonce` from B. Site C, whose table names another owner, gave `not_owner`.

### Current flow, stock Chrome

No timed numbers yet. The bubble hasn't been timed. Before the bubble, one scripted run passed: a script's `.click()` did nothing, one signature, named on Site A, anonymous on Site B, no second wallet prompt.

### Proof path, earlier flow

These predate the Sign in button and direct login. A login then started when you left the field, and all modes used a proof. Anonymous still uses this proof path. The 108 checks of that run were not rerun on the current flow.

A different machine, stock Chrome 157.0.8103.38, Node 24.22.1, other work running. One test run.

| What | Value |
|---|---:|
| Anonymous login, median of 4 | 4.75 s |
| First login at a site that hadn't verified yet | 6.85 s |
| Show + reblind, median of 12 | 3.36 s (3.24 to 3.45) |
| Site's verify | About 1.45 s, first one about 3 s |
| Two Prepares and saves | 18.6, 17.9, 17.6 s |
| Prover process peak | 2,979 MiB |
| Each site server peak | About 1,140 MiB |
| Proof / token | 165,749 B / about 221 KB |
| Stored Prepare state | 90 MB |
| Holder download / site keys / extension | About 293 MB / about 280 MB / 14 MB |

Proving isn't under 3 s. Those speeds need kept keys, opt-level 3 and 4 threads. Same machine, closest build to stock, one thread, Chrome 156: Prepare 14.8 s, Show 7.98 s, Verify 4.70 s. In Node with the plain wrapper, one thread: 14.39, 7.91, 5.06 s. Both are earlier runs. Neither is stock.

On the Linux machine above, one earlier proof login took 8.5 s on the Demo build and 9.9 s on the dcheck build. Most of the gap to the other machine looks like hardware. That's a guess.

### Building the patched browser

Same Linux machine. Demo binary, 57,566 steps: 1 h 38 m 09 s. Output folder 7.2 GB, `chrome` 533 MB. Patch build, first good one, 173 steps: 1 m 18 s.

## Not included

- Test suites, raw logs and screenshots. So you can't rerun the numbers or the circuit-cases from this folder.
- Path C, the version that proves wallet ownership directly in the circuit. It wasn't run: no setup, no proof.
- zkID, the keys and all binaries. See `prover/README.md`.
