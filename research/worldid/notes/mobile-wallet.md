# Mobile side: World ID proof, tx signing, Mini App vs native

Date: 2026-09-26. Scope: how the native KMP app (Android Kotlin + iOS Swift) gets a World ID proof, how it signs Ethereum / Safe things, and whether a World Mini App can replace or wrap the native app. Target: 2–3 day hackathon demo, 1 Android + 1 iPhone, **free Apple personal team**.

Tags: **V(src)** = verified at that URL / command / file. **U** = unverified or inferred. Scratch clones used: `scratchpad/mw/{idkit,idkit-swift,minikit-js,safe-modules}` (session scratchpad, not in repo).

---

## 0. Answer in five lines

1. **World ID on phone: go native, per platform.** Android `com.worldcoin:idkit:4.0.7` (already proven end to end in `~/dev/worldid-spike`), iOS SPM `idkit-swift` 4.0.11 behind a Swift class that implements a Kotlin interface. Flow = open `https://world.org/verify?...` → World ID app → back via custom-scheme `return_to` → poll the bridge. Custom schemes need no entitlement, so the free Apple team is fine.
2. **Signing: server-relayed, phone signs 32-byte digests only.** No WalletConnect, no MetaMask, no ETH on phones. Each phone holds a software secp256k1 key (`fr.acinq.secp256k1:secp256k1-kmp` 0.24.0). The server builds the Safe tx / pool tx, the phones sign the hash, the server's funded relayer EOA submits on World Chain Sepolia (4801).
3. **World App is not a WalletConnect wallet** for outside apps (U, strongly indicated). Its wallet is a Safe, and outside World App you reach it only by exporting the owner key into MetaMask. Don't plan on it.
4. **Mini App is a no-go for the audio part.** WKWebView only supports the `echoCancellation` constraint (no AGC / NS switch), there's no `.measurement` mode / `UNPROCESSED` source, no hostTime/latency data, and no hardware-attested keys. A hybrid (Mini App wallet UI + native PoP app) is possible but adds mainnet-only, contract allowlisting, three apps per phone and an untested webview→native deep link. Not worth it: the World prize says "functioning application, mini app, or onchain flow", so a native app qualifies.
5. **Order on screen:** World ID step (app switch) **before** the audio run, and the signing step **after** NEAR. Never switch apps during audio.

---

## 1. Verified facts

### 1.1 World app landscape (changed 2026-09-17)

- World split identity from money: **World ID app** (identity, proofs) and **World Money** (wallet, payments, Mini Apps). V([criptocurrencies.com 2026-09-19](https://criptocurrencies.com/2026/09/19/world-money-super-app-launch/), [world.org/blog/announcements/world-money](https://world.org/blog/announcements/world-money))
- App Store today (US and JP): `org.world.id` "World ID — Proof of Human" 1.0.601 (first release 2026-08-10), and `org.worldcoin.insight` "World App — Real Human Network" 4.0.2700. No separate "World Money" listing found; World App is likely being turned into World Money by update (U). V(`itunes.apple.com/search?term=world+id&country=us|jp`, `lookup?id=6760839426`, `lookup?id=1560859847`)
- Play Store: `com.worldcoin` (World App) and `org.world.id` both exist (HTTP 200). V(`curl play.google.com/store/apps/details?id=...`)
- **The World ID proof in our Android spike came from the World ID app, not World App.** The `integrity_bundle.jwt` in the proof payload says `"app_version":"1.0.503","platform":"android","iss":"attestation.worldcoin.org"`; 1.0.x is the World ID app's version line. V(`~/dev/worldid-spike/backend/logs/backend.log`, 2026-09-25 00:43, base64-decoded JWT). Inference that 1.0.503 = `org.world.id` is U but very likely.
- ⇒ Demo phones need the **World ID app** installed and Orb-verified. World App / World Money is only needed on the Mini App route.

### 1.2 IDKit native SDKs

| Item | Value | Source |
| --- | --- | --- |
| Monorepo | `github.com/worldcoin/idkit` (Rust core + UniFFI bindings), last commit 2026-09-23 | V(git clone) |
| Swift | SPM `https://github.com/worldcoin/idkit-swift.git`, tag **4.0.11** (2026-08-09), binaryTarget `IDKitFFI.xcframework.zip` checksum `98849ec5…eb682`, iOS 15+ | V(`idkit-swift/Package.swift`, `gh api .../releases`) |
| Kotlin | `com.worldcoin:idkit` **4.0.7** (2026-08-09), **GitHub Packages only**, needs a token with `read:packages`; not on Maven Central (metadata 404) | V(`gh api /orgs/worldcoin/packages/maven/com.worldcoin.idkit/versions`, `repo1.maven.org/.../com/worldcoin/idkit` → empty) |
| KMP artifact | none | V(no such package) |
| JS | `@worldcoin/idkit-core` / `@worldcoin/idkit` 4.x (WASM) | V(`idkit-research-brief.md` §1) |
| Go | `go/idkit`: **signing only** (`signing.go`), no request/bridge client | V(`ls idkit/go/idkit`) |

- **Proof of Human preset in Swift**: there's no `proofOfHuman()` helper in 4.0.11, only the generated enum case `Preset.proofOfHuman(signal: String?)`. Helpers exist only for `orbLegacy` and `selfieCheckLegacy`. Don't use those; they give 3.0 proofs. V(`idkit-swift/Sources/IDKit/IDKit.swift:581,610`, `Generated/idkit_core.swift:4545`). Kotlin is the same: `Preset.ProofOfHuman(signal)`. V(brief §4, spike)
- **Connector URL**: `https://world.org/verify?t=wld&i=<request_id>&k=<b64 AES key>[&return_to=<urlenc>]`. Staging is `staging.world.org/verify`, sandbox is `sandbox.world.org/verify`. V(`rust/core/src/bridge.rs:60-62, 1063-1098`)
- **Bridge**: `POST /request` (the key never leaves the client), then `GET /response/:id` (unauthenticated) for polling. V(`bridge.rs:962, 1129-1144`)
- **`return_to` on iOS is officially supported with a custom scheme.** The official iOS sample sets `returnTo = "idkitsample://callback"`, opens the connector with `UIApplication.shared.open(connectorURL)` and handles the return in `.onOpenURL`. V(`idkit/swift/Examples/IDKitSampleApp/README.md`, `ContentView.swift:138,187,212,246`). This closes the brief's open question "iOS custom-scheme return_to [U]" at the documentation level. It hasn't been device-tested by us yet.
- **The return deep link carries no data.** The result comes from bridge polling (`pollUntilCompletion`, or `pollStatusOnce` in a loop). The pending request object lives in memory. If the OS kills our app while the World ID app is in front, the attempt is lost and has to be retried. V(`~/dev/worldid-spike/app/README.md` Notes; Swift API `pollUntilCompletion(options: IDKitPollOptions(pollIntervalMs:timeoutMs:))` from [docs.world.org/world-id/idkit/swift](https://docs.world.org/world-id/idkit/swift))
- **Proven end to end on Android** (2026-09-25): per-attempt unregistered action `spike-<ms>`, Portal `POST /api/v4/verify/{rp_id}` → 200 `"Proof verified successfully"`, `protocol_version:"4.0"`, `identifier:"proof_of_human"`, `issuer_schema_id:1`. V(`backend.log`)
- **The Portal does not reject a reused nullifier.** It returns 200 with "nullifier reuse", so our server must enforce `UNIQUE`. V(`worldid-spike/backend/README.md`)

### 1.3 Free Apple personal team (the "Apple Developer" column)

From Apple's capability table (parsed from raw HTML, because WebFetch's summary was wrong). V([developer.apple.com/help/account/reference/supported-capabilities-ios](https://developer.apple.com/help/account/reference/supported-capabilities-ios), `curl` + regex on `icon-checksolid`)

| Capability | Paid (ADP) | Free |
| --- | --- | --- |
| App Attest | yes | **no** |
| Associated Domains (universal links) | yes | **no** |
| NFC Tag Reading | yes | **no** |
| Push notifications | yes | **no** |
| Increased Debugging Memory Limit / Extended Virtual Addressing | yes | **no** |
| Background modes | yes | yes |
| Keychain sharing | yes | yes |

Consequences:
- **We can't receive universal links, but we don't need them.** `return_to` uses a custom URL scheme, which is just `CFBundleURLTypes` in Info.plist and needs no entitlement. We *open* `https://world.org/verify`; the World ID app owns that universal link, not us.
- **The iPhone's PoP device key will be unattested** (no App Attest). That matches the repo, where `iosApp.entitlements` is empty and `iosApp-paid.entitlements` holds NFC + App Attest + increased memory. V(`app/iosApp/iosApp/*.entitlements`)
- **No NFC pairing on the iPhone.** Use QR (the camera needs no entitlement).
- **No increased memory limit**, so the iOS ZK prover may get jetsammed. That belongs to the other workflow, but it matters here too: the more memory we use, the more likely iOS kills the app while it sits in the background during the World ID hop.
- **Secure Enclave keys need no entitlement** (U, standard `SecKeyCreateRandomKey` with `kSecAttrTokenIDSecureEnclave`; the repo already does this in `DeviceKeystore.ios.kt`).

### 1.4 Hardware keys can't hold an Ethereum (secp256k1) key

- Android KeyMint `EcCurve` = `P_224, P_256, P_384, P_521, CURVE_25519`. There's no secp256k1. V([AOSP EcCurve.aidl](https://android.googlesource.com/platform/hardware/interfaces/+/refs/heads/main/security/keymint/aidl/android/hardware/security/keymint/EcCurve.aidl))
- iOS Secure Enclave: P-256 only (CryptoKit exposes only `SecureEnclave.P256`). U(from API surface, not re-fetched; the Apple doc page didn't render for the fetcher)
- ⇒ There are two ways to get an Ethereum signer on the phone:
  - (a) A **software secp256k1 key**, wrapped at rest by a Keystore/SE key (AES-GCM on Android, or ECIES with an SE P-256 key on iOS).
  - (b) **Use the hardware P-256 key directly as a Safe owner** through Safe's WebAuthn signer contracts (see §1.6).

### 1.5 Wallet libraries (native)

| Lib | Version | Platforms | Source |
| --- | --- | --- | --- |
| `fr.acinq.secp256k1:secp256k1-kmp` | 0.24.0 (2026-08-13) | Android (JNI `-jni-android`), iOS arm64 / sim (native cinterop), JVM | V(Maven Central metadata, repo README, artifact listing) |
| `org.kotlincrypto.hash:sha3` (keccak) | 0.8.0 | KMP | V(Maven Central metadata) |
| `org.web3j:core` | 6.0.0 | JVM/Android only | V(Maven Central metadata) |
| Reown AppKit Android `com.reown:appkit` | 1.6.17 (2026-09-14) | Android only | V(Maven Central, `gh api reown-com/reown-kotlin/releases`) |
| Reown Swift | 2.4.0 (2026-09-14) | iOS only | V(`gh api reown-com/reown-swift/releases`) |
| Reown KMP | none | — | U(no artifact found) |

### 1.6 World Chain: the contracts the mobile side would touch

`eth_getCode` byte length on the Alchemy public RPCs, mainnet 480 and Sepolia 4801. V(curl `eth_getCode`, 2026-09-26)

| Contract | Address | 480 | 4801 |
| --- | --- | --- | --- |
| Safe v1.4.1 singleton | `0x41675C099F32341bf84BFc5382aF534df5C7461a` | 23579 B | 23579 B |
| SafeL2 v1.4.1 | `0x29fcB43b46531BcA003ddC8FCB67FFE91900C762` | 24421 B | 24421 B |
| SafeProxyFactory v1.4.1 | `0x4e1DCf7AD4e460CfD30791CCC4F9c8a4f820ec67` | 3054 B | 3054 B |
| Permit2 | `0x000000000022D473030F116dDEE9F6B43aC78BA3` | yes | yes |
| EntryPoint v0.7 | `0x0000000071727De22E5E9d8BAf0edAc6f37da032` | yes | yes |
| SafeWebAuthnSharedSigner (passkey v0.2.1) | `0x94a4F6affBd8975951142c3999aEAB7ecee555c2` | 2954 B | 2954 B |
| SafeWebAuthnSignerFactory **v0.2.0** | `0xF7488fFbe67327ac9f37D5F722d83Fc900852Fbf` | 2350 B | 2350 B |
| SafeWebAuthnSignerFactory v0.2.1 | `0x1d31F259eE307358a26dFb23EB365939E8641195` | **0 (not deployed)** | **0** |
| DaimoP256Verifier | `0xc2b78104907F722DABAc4C69f826a522B2754De4` | yes | yes |
| FCLP256Verifier v0.2.1 | `0xA86e0054C51E4894D88762a017ECc5E5235f5DBA` | yes | yes |

- The RIP-7212 P-256 precompile at `0x…0100` is live on 480 and 4801. V(per `research/worldid/notes/repo-surface.md` §0, not re-run here)
- **Safe WebAuthn verification details:**
  - Signing message = `sha256(authenticatorData ‖ sha256(clientDataJSON))`, where `clientDataJSON = {"type":"webauthn.get","challenge":"<b64url(hash)>",<clientDataFields>}`.
  - It checks the authenticator flag bits (UP = 0x01, UV = 0x04).
  - It verifies with `verifySignatureAllowMalleability`, so high-s is fine.
  - V(`safe-modules/modules/passkey/contracts/libraries/WebAuthn.sol:50,68,134-160,231-237,313-327`)
  - ⇒ A raw Keystore/SE P-256 key can produce a valid signature. The app builds the `authenticatorData` and `clientDataJSON` bytes itself and signs them with `SHA256withECDSA` (Android) or `.ecdsaSignatureMessageX962SHA256` (iOS). Keystore gives random-s DER; convert it to r, s. U(not run end to end).
- `SafeWebAuthnSharedSigner` keeps **one** P-256 signer per Safe, in the Safe's storage, via `configure()`, which must be DELEGATECALLed. For two P-256 owners, use the factory to make per-key signer proxies. V(`4337/SafeWebAuthnSharedSigner.sol:133-137`). Note that only the v0.2.0 factory is deployed on World Chain, and 0.2.1 lists security fixes over 0.2.0. V(`CHANGELOG.md`)

### 1.7 Mini Apps (MiniKit)

- A Mini App is a web app in a webview inside World App: Android WebView, iOS **WKWebView**. V([webview-spec](https://docs.world.org/mini-apps/more/webview-spec.md))
- **"Opening new browser windows is prohibited. All navigation remains within the current WebView instance."** No alert dialogs on iOS. V(same)
- MiniKit current: `@worldcoin/minikit-js` **2.0.3**, repo last commit 2026-09-20. Commands: `attestation, pay, wallet-auth, send-transaction, sign-message, sign-typed-data, share-contacts, request-permission, get-permissions, send-haptic-feedback, share, chat, close-miniapp`. There is **no open-URL / open-external-app command**. V(`minikit-js/packages/core/src/commands/types.ts:9-37`)
- `MiniKit.showProfileCard` does `window.open("worldapp://profile?...")`, i.e. World App intercepts its own scheme. Whether `window.open("enconomy://...")` or `location.href = "enconomy://..."` reaches the OS is **not documented** (U). V(`minikit.ts:651-668`)
- **World ID in a Mini App = IDKit** (`@worldcoin/idkit`). "MiniKit 2.x does not proxy verification requests". Inside World App it uses the native transport, no QR. V([world-id/idkit/mini-apps](https://docs.world.org/world-id/idkit/mini-apps.md))
- **Microphone**:
  - Needs World App ≥ 2.8.85 and MiniKit ≥ 1.9.6.
  - Needs two grants: `requestPermission("microphone")` for the Mini App, plus the OS grant for World App.
  - It uses plain `navigator.mediaDevices.getUserMedia`.
  - It turns off when the Mini App or World App closes.
  - The docs say nothing about EC/NS/AGC, speaker output, latency, or iOS vs Android.
  - V([reference/microphone](https://docs.world.org/mini-apps/reference/microphone.md))
- **WebKit supports only `echoCancellation`** among the three processing constraints:
  - `RealtimeMediaSourceSupportedConstraints` has `supportsEchoCancellation` and no AGC / noise-suppression flags. V([WebKit source](https://raw.githubusercontent.com/WebKit/WebKit/main/Source/WebCore/platform/mediastream/RealtimeMediaSourceSupportedConstraints.h))
  - `echoCancellation:false` has worked since 2019 (bug 179411, RESOLVED FIXED). V(bugs.webkit.org REST)
  - The `autoGainControl` constraint is still **NEW / unimplemented** (bug 204444, last touched 2026-04-06). V(bugs.webkit.org REST)
  - Android WebView (Chromium) accepts all three constraints (U: standard Chromium behaviour, not re-checked).
- **Transactions**:
  - `MiniKit.sendTransaction({chainId: 480, transactions:[...]})` returns a `userOpHash`, not a tx hash. Resolve it via `GET https://developer.world.org/api/v2/minikit/userop/{hash}` or `useUserOperationReceipt`.
  - Every contract entrypoint and Permit2 token must be **allowlisted** in Developer Portal → Mini App → Permissions. Otherwise you get `invalid_contract`.
  - V([send-transaction](https://docs.world.org/mini-apps/commands/send-transaction.md))
- **Mainnet only**: "mini app needs to be developed on mainnet (we don't support testnet)". Gas is sponsored for verified users. V([mini-apps FAQ](https://docs.world.org/mini-apps/more/faq.md))
- **The World App wallet is a Safe.** MiniKit's SIWE verifier first tries ECDSA recovery, then falls back to EIP-1271 `isValidSignature(bytes32,bytes)` == `0x1626ba7e` on the wallet address, "for smart contract wallets (Safe)". V(`minikit-js/packages/core/src/commands/wallet-auth/siwe.ts:28-60,291-310`). Also stated by World's own blog (search snippet: "smart contract wallet uses Safe{Core}"). U(blog not fetched)
- `MiniKit.attestation({requestHash})` returns an opaque JWT from World App. It's an app-integrity token, not a device key we control. V([attestation](https://docs.world.org/mini-apps/commands/attestation.md))

### 1.8 World App as a WalletConnect wallet

- We found no World doc or MiniKit code path that makes World App a WalletConnect *wallet* for outside dapps.
- The World help center path for "use my World wallet elsewhere" is **export the private key → import it into MetaMask → connect MetaMask to the Safe{Wallet} UI via WalletConnect**. After export, World App stops sponsoring gas.
- U: the source is the help article ([support.world.org …/38808889982867](https://support.world.org/hc/en-us/articles/38808889982867-How-do-I-export-and-use-my-private-key)) as seen in search snippets. The page itself is behind a Cloudflare challenge (403 to WebFetch and curl).

### 1.9 Prize fit

- **Best Use of IDKit** ($5k, up to 2 × $2.5k) requirements:
  - "Integrate IDKit in a functioning application, mini app, or onchain flow"
  - server **or** onchain verification
  - explain the trust moment and the credential choice
  - show a success plus one failure path
  - give integration feedback
- V([ethglobal.com/events/tokyo2026/prizes](https://ethglobal.com/events/tokyo2026/prizes))
- ⇒ **No Mini App requirement.** The native app qualifies.

### 1.10 What the repo's native audio does that a webview can't

- **iOS**:
  - `.playAndRecord` + `.measurement` (no AGC / voice processing) + `.defaultToSpeaker`.
  - Frame timing from the tap's `hostTime − inputLatency`, playback scheduled at a player sample time, and `outputLatency`.
  - An interruption aborts with `capture_failed`.
  - V(`app/composeApp/src/iosMain/kotlin/com/enconomy/pop/AudioEngine.ios.kt:100-117`)
- **Android**: `AudioSource.UNPROCESSED` when the HAL supports it, else `VOICE_RECOGNITION`. It explicitly handles AEC / NS / AGC. V(`AudioEngine.android.kt:15-18,61,88,172`)
- None of that is reachable from `getUserMedia` / WebAudio in a WKWebView, and PoP transcripts must be signed by an attested device key, which a webview can't hold.

---

## 2. Unverified / conflicting

| # | Claim | Status / how to settle |
| --- | --- | --- |
| U1 | Which app answers `https://world.org/verify` on **iOS** when both World ID app and World App are installed | U. Android evidence points to the World ID app (1.0.503). Test on the iPhone: tap the connector, see which app opens. |
| U2 | iOS custom-scheme `return_to` works in the current World ID app | Documented in the official iOS sample; not device-tested by us. If it fails, the user switches back manually and polling still completes (no data travels in the deep link). |
| U3 | Our app survives in the background on iOS while the World ID app is in front | U. Low risk if the World ID step runs before audio and before any ZK proving (heavy memory). If it's killed, the in-memory `IDKitRequest` is lost. Mitigation: the server-driven variant (§3.1-B) keeps the request on the server. |
| U4 | AVAudioSession comes back clean after returning from the World ID app | U. The audio engine should be started fresh after the hop (it's per run anyway). Needs a device check. |
| U5 | Mini App can navigate to a custom scheme (`enconomy://`) | U. Docs forbid new windows. MiniKit only uses `worldapp://`. Needs a test in World App. |
| U6 | World App (World Money) will sign an EIP-712 **SafeTx** for a different Safe via `signTypedData` (making the World App Safe an owner of our Safe) | U. It might be flagged (`malicious_operation` / `disallowed_operation` exist as sendTransaction errors). Not needed for the native plan. |
| U7 | Mini Apps now live in World Money, and whether World App 4.x still holds World ID credentials for in-webview IDKit | News says Mini Apps moved to World Money; the IDKit docs still say "inside World App". U. |
| U8 | Android WebView honours `autoGainControl:false` / `noiseSuppression:false` with an unprocessed source | U. Irrelevant if we stay native. |
| U9 | Raw Keystore/SE P-256 signature accepted by `SafeWebAuthnSharedSigner` with self-built authenticatorData | U. Contract logic says yes (§1.6). A foundry fork test would settle it in ~1 h. |
| U10 | Gas sponsorship on World Chain for our own relayer | No. Sponsorship applies to World App users' txs. Our relayer pays; 4801 faucet ETH is enough. U: exact faucet availability. |
| U11 | World blog says the World App wallet is Safe{Core} | Search-snippet only; code evidence (MiniKit SIWE EIP-1271 path) agrees. |

Conflict found and resolved: WebFetch summarised Apple's capability table as "all available to free accounts". The raw HTML shows App Attest, Associated Domains, NFC, Push and the memory limit are **paid only**. Trust §1.3.

---

## 3. Recommended architecture (hackathon, native only)

### 3.1 World ID step (both products share it)

**A. Native SDK per platform (primary).**

```
commonMain:
  interface WorldIdProver {
      /** opens World ID app, returns the raw IDKit result JSON (to forward untouched to server) */
      suspend fun prove(ctx: WorldIdContext): WorldIdOutcome
  }
  data class WorldIdContext(appId, rpId, action, signalHex, environment, rpNonce, createdAt, expiresAt, rpSig, returnTo)
  sealed interface WorldIdOutcome { Ok(resultJson: String); Err(code: String) }

androidMain: AndroidWorldIdProver
  - IDKit.request(IDKitRequestConfig(..., returnTo = "enconomy://worldid")).preset(Preset.ProofOfHuman(signalHex))
  - startActivity(Intent(ACTION_VIEW, connectorURI))
  - withContext(IO) { loop pollStatusOnce() every 1.5 s, 120 s timeout }   // blocking calls → IO
  - MainActivity (singleTask) gets enconomy://worldid; the deep link only flags "returned"

iosMain: expect nothing. A Kotlin interface is exported as an ObjC protocol.
iosApp (Swift): final class SwiftWorldIdProver: NSObject, WorldIdProver   // SPM idkit-swift 4.0.11
  - IDKit.request(config: IDKitRequestConfig(appId:, action:, rpContext:, allowLegacyProofs: false,
        returnTo: "enconomy://worldid", environment: .production)).preset(.proofOfHuman(signal: signalHex))
  - UIApplication.shared.open(request.connectorURL)
  - await request.pollUntilCompletion(options: .init(pollIntervalMs: 1500, timeoutMs: 120_000))
  - injected at startup: MainViewControllerKt.setWorldIdProver(SwiftWorldIdProver())
```

Plumbing:
- Android: add an `<intent-filter>` with `VIEW` / `DEFAULT` / `BROWSABLE` and `<data android:scheme="enconomy" android:host="worldid"/>` to `MainActivity`. Gradle: the GitHub Packages repo for `com.worldcoin:idkit:4.0.7` (or `mavenLocal` via the spike's `scripts/build-idkit-from-source.sh`).
- iOS: add `CFBundleURLTypes` → `enconomy`, handle `.onOpenURL` in `iOSApp.swift`. Add the SPM package to the Xcode project, not to Gradle.
- Kotlin suspend functions exported to Swift show up as completion-handler / async methods. A Swift class can conform to a Kotlin interface (standard K/N ObjC export, [kotlinlang.org/docs/native-objc-interop.html](https://kotlinlang.org/docs/native-objc-interop.html)). U: whether Swift can implement a Kotlin **suspend** interface method directly. The safer choice is a callback signature: `fun prove(ctx, onDone: (WorldIdOutcome) -> Unit)`.
- Server side, unchanged from `docs/pop-human-adapters.md`:
  - `GET /v1/session/{id}/human/context` returns `{app_id, rp_id, action:"pop:"+sid, signal, rp_context}`.
  - The phone posts the raw result.
  - The server calls Portal v4 verify, checks `signal_hash`, `environment`, nullifier `UNIQUE`, and `nullifier_A != nullifier_B`.

**B. Server-driven connector (fallback if the iOS Swift shim eats time).**
- A small Node sidecar next to the FastAPI server runs `@worldcoin/idkit-core` to create the request (it holds the AES key) and polls the bridge.
- The phone only gets `connectorURI` from our server, opens it, and long-polls our server. This is pure `commonMain`, with no native SDK on either phone.
- Costs: one extra process. The bridge key sits on our server, which is fine because the server is the RP and verifies anyway.
- U: `idkit-core` WASM loading under Node ESM (`new URL(..., import.meta.url)` should work in Node). Test it first if B is chosen.

**Screen order per phone:**

```
pair (QR)
  → [World ID hop: app switch]
  → server: both humans OK
  → audio run
  → NEAR
  → [sign step]
  → relayer submits
  → show tx link
```

The switch happens before the audio engine starts, per `docs/pop-human-adapters.md` rule 2.

### 3.2 Signing step (tx or Safe signature)

**Pick: embedded software secp256k1 key + server relayer.** Why:
- One path for both platforms, all in `commonMain` (`secp256k1-kmp` + keccak).
- No second app, no WalletConnect session, no ETH on phones.
- Works on free iOS team.
- Testnet (4801) allowed.

Layout:
- The key is generated on first launch.
  - Android: stored AES-GCM-encrypted with a Keystore key.
  - iOS: Keychain, `kSecAttrAccessibleWhenUnlockedThisDeviceOnly`, optionally ECIES-wrapped by an SE P-256 key.
  - The address is derived as `keccak(pub64)[12:]` (phone or server).
- Enrolment: the phone sends its eth address, signed by the attested PoP device key (P-256). The server can then say "this eth owner ↔ this enrolled device".
- Sign API:
  - The phone gets `{digest, human_readable, typed_data}` from the server.
  - It **recomputes the digest locally** from `typed_data` (EIP-712) so a lying server can't swap the tx. This costs about 60 lines of EIP-712 hashing in Kotlin. For a 2-day build, showing the digest and trusting the server is acceptable, but say so in the threat model.
  - It returns `r‖s‖v` (65 B, v = 27/28).
- The relayer is a server EOA funded on World Chain Sepolia. It calls `execTransaction` (SAFE) or the pool's `transact` (POOL).

**Stretch (strong story, 1 extra day of risk): the hardware P-256 PoP key *is* the Safe owner.**
- Mechanism: `SafeWebAuthnSignerFactory` v0.2.0 (`0xF748…2Fbf`, deployed on 480/4801) creates a signer proxy per device pubkey, which becomes a Safe owner.
- Signature = contract signature (v = 0) → `isValidSignature` → WebAuthn check against the RIP-7212 precompile.
- The phone synthesises:
  - `authenticatorData` = 37 B: rpIdHash ‖ flags 0x05 ‖ signCount
  - `clientDataFields`
- It then signs `sha256(authData ‖ sha256(clientDataJSON))` with the same attested key that signs the POPT transcript.
- Result: the Safe owner and the presence witness are one hardware key.
- Caveats: the iPhone key is unattested on the free team, the v0.2.0 factory is older than v0.2.1, and there's no software fallback if it breaks. Decide after a foundry fork test (U9).

**Rejected for the demo:**
- **Reown AppKit / WalletConnect to MetaMask.**
  - It's two SDKs (Android-only and Swift-only, no KMP) and a second wallet app on each phone.
  - Two app switches per signature.
  - World Chain Sepolia has to be added in MetaMask by hand.
  - It adds nothing to the World prize.
- **World App as a wallet via WalletConnect**: not offered (U, §1.8).
- **Mini App wallet (World App Safe via MiniKit)**:
  - mainnet only and allowlisting (§1.7)
  - a third app per phone
  - an untested webview → native link (U5)
  - SafeTx signing by World App is uncertain (U6)

### 3.3 Why not a Mini App wrapper (answering task item 3 directly)

- **Audio can't move into the Mini App.**
  - WKWebView gives `echoCancellation:false` at best. AGC can't be disabled (WebKit bug 204444 open).
  - There's no `.measurement` mode and no hostTime / inputLatency / outputLatency data to reproduce `AudioEngine.ios.kt` timing.
  - The mic dies when the Mini App closes.
  - A webview can't hold a Keystore / App Attest key to sign POPT transcripts.
- **Mini App → native app hand-off has no documented API** (no open-URL command; new windows prohibited).
  - A working hand-off without deep links: the Mini App shows a 6-char session code or QR, the user opens the enconomy app by hand, and the Mini App polls our server for the verdict.
  - It works, but on iOS it's two manual app switches per person, and the audio app must be foreground anyway.
- **The iOS app switch kills audio.** This doesn't matter as long as switches happen only before or after the audio run. That's true for the native plan and also for the hybrid.
- **Cost of the hybrid on top of native:**
  - a second Developer Portal app (Mini App `app_id`)
  - an HTTPS tunnel (ngrok)
  - contract allowlisting
  - mainnet deploys
  - World App / World Money installed and verified on both phones
- **Benefit:** a World-native wallet UX and gas sponsorship. The prize doesn't require it.
- Verdict: **skip for the hackathon.** Mention it as the "production distribution" story in the pitch.

### 3.4 Demo phone checklist

- Both phones:
  - World ID app (`org.world.id`) installed, Orb-verified (Proof of Human).
  - Same `environment` as the RP (production; the spike used production).
  - enconomy app installed (Android via adb, iOS via Xcode free team; the profile lasts 7 days).
  - Online to the server (LAN or tunnel).
- Android: pre-fetch the IDKit AAR (GitHub token with `read:packages`) **before** the venue Wi-Fi.
- iOS: trust the developer certificate in Settings → General → VPN & Device Management.
- Relayer: fund an EOA on World Chain Sepolia (4801). RPC `https://worldchain-sepolia.g.alchemy.com/public`, explorer `worldchain-sepolia.explorer.alchemy.com`. V([docs world-chain info](https://docs.world.org/world-chain/quick-start/info.md))
- Failure path for the prize: the same human on both phones → `same_human` (equal nullifiers), or `user_rejected` in the World ID app.

---

## 4. Implications for SAFE idea

- **Owners:**
  - Hackathon: two phone-held secp256k1 EOAs, threshold 2-of-2.
  - Stretch: owners = device P-256 keys via WebAuthn signer proxies (§3.2).
  - The Safe singletons and proxy factory v1.4.1 are on World Chain Sepolia (§1.6).
- **Presence gate:**
  - A Safe Guard (`checkTransaction`) or module checks a PoP attestation bound to the exact `safeTxHash`.
  - The simplest binding: the PoP session's World ID `signal` includes `safeTxHash`, or the server-issued attestation signs `(safeTxHash, sid, pair_tag, expiry)`.
  - This is the onchain-side agent's call. Mobile only needs to show and sign the `safeTxHash`.
- **Flow on phones:**
  1. One phone proposes a tx.
  2. The server computes the SafeTx EIP-712 digest (domain `{chainId: 4801, verifyingContract: safe}`).
  3. Both phones do World ID → audio → NEAR.
  4. Each phone signs the same digest.
  5. The relayer sorts the signatures by owner address ascending and calls `execTransaction`.
  - A single session covers both the presence proof and both signatures. That's a clean 60–90 s demo.
- **Why World App's own Safe isn't the shared wallet:**
  - We can't add a Guard to users' World App Safes.
  - Mini App txs are allowlist-gated and mainnet.
  - A separate "together-Safe" whose owners are the two phones is the right demo object.
- **"Unique human per owner"** comes from World ID at *execution* time (per-session action). It doesn't bind a human to an owner key permanently. If they want "owner = this human", register a nullifier for a fixed action at Safe creation. But a PoH nullifier for a fixed action can be produced **once ever** (brief §2), so it's usable for enrolment, not for every tx.

## 5. Implications for POOL idea

- The mobile signing part is the same pattern: the phone signs, the relayer submits.
- **But a Railgun-like pool needs client-side ZK for the spend** (note commitments, nullifiers, Merkle path, usually Groth16/BN254). That means a **second** mobile prover next to the PoP option-A prover.
  - No KMP library exists; it would be a mopro/rapidsnark-style native build per platform.
  - With the iPhone on a free team (no increased memory limit), this is a real schedule risk. U: no pool-circuit sizes checked here.
- Relayer submission is standard for pools (it hides the sender's gas payer). The server relayer fits naturally.
- **The Mini App route would be worse for POOL:**
  - World App's `sendTransaction` goes from the user's public Safe, which defeats privacy unless it only calls a relayer.
  - Contract allowlisting exposes the pool contract.
  - Mainnet only.
- The World ID nullifiers of payer and payee must **not** be written onchain next to the private transfer, or they link the parties per session. Per-session actions keep them unlinkable across sessions, but within one tx they reveal "these two humans met". Keep the World ID check at the server / attester and put only an attester signature onchain. Or accept the leak and document it.
- The mobile verdict is that SAFE is materially cheaper on the mobile side: no extra prover, same sign-a-digest API.

---

## 6. Open questions (ordered, with the cheapest test)

1. **iOS World ID hop on a real iPhone (free team)**: which app opens, whether `enconomy://worldid` returns, whether polling completes, and whether our app survives. *Test:* build the official `IDKitSampleApp` or our shim; 30 min.
2. **Swift conformance to a Kotlin interface** from the shared framework (callback form). *Test:* 20-line spike in `iosApp`.
3. **Audio after the hop**: start a PoP run right after returning from the World ID app on the iPhone; check for `capture_failed`.
4. **Stretch signer**: does the `SafeWebAuthnSharedSigner` / v0.2.0 proxy accept a Keystore-made signature with synthetic `authenticatorData`? *Test:* foundry fork of 4801 + a Python P-256 signer; 1 h.
5. **Server-driven fallback**: does `@worldcoin/idkit-core` create a request and poll in plain Node? *Test:* 15 min script.
6. Does the Developer Portal's World ID app need **staging vs production** alignment with the phones' World ID app build? The spike used production and worked on Android.
7. (Only if a Mini App is reconsidered) Does `location.href = "enconomy://..."` from a World App Mini App open the native app on iOS and Android? Does World App sign a SafeTx typed-data for a foreign Safe?
8. (POOL only) Which pool circuit, what proving time and memory on an iPhone without the increased-memory entitlement?

## 7. Risks

- **The IDKit Kotlin AAR is GitHub-Packages-only**, so venue Wi-Fi or a token hiccup blocks the Android build. Mitigation: cache it in `~/.m2` now.
- **iOS app killed in the background during the World ID hop** (memory pressure, no increased-memory entitlement) loses the in-memory request. Mitigation: do the World ID hop first, before loading ZK keys, or use the server-driven variant.
- **Free-team iOS** means an unattested device key, no NFC, and a 7-day profile. Re-sign before demo day.
- **The embedded software eth key is not hardware-protected** (secp256k1 isn't in Keystore / SE). State it. The stretch P-256 path fixes it.
- **World's app split is two weeks old.** Deep-link ownership, app names and docs may shift. Pin SDK versions (Kotlin 4.0.7, Swift 4.0.11) and re-check the World ID app version on demo phones.
- **Showing only the server-computed digest** lets a malicious server swap the tx. Fine for a demo; say so, or add local EIP-712 recompute.
- **POOL doubles the mobile ZK load.**
