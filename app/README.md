# pop app (KMP, Android + iOS)

Proof-of-presence phone app. Contract: `../docs/pop-contract.md`.

Enroll (Keystore P-256, StrongBox if present, attestation chain), pairing by NFC tap or QR, then the full run: clock sync, arm, record + play at t0, self check, signed commitment, partner bed, partner arrival, signed transcript, result. One automatic retry on a failed measurement (server driven).

Layout (`composeApp/src/`):
- `commonMain/.../pop/` — `App.kt` (Compose), `PopController.kt` (screens, enroll, pairing), `RunFlow.kt` (`PopRun`: arm .. result, §4-§8), `Transcript.kt` (269-byte transcript, 71-byte commit, §7), `AudioRun.kt` / `ClockSync.kt` (timing), `PopApi.kt` (wire types + client, §2.3 signing), `Signing.kt` (`DeviceKey`/`DeviceKeystore`, request message, DER -> r||s), `Bytes.kt` (hex, base64, SHA-256), `Platform.kt` (expect decls).
- `commonMain/.../pop/dsp/` — DSP lane only (§6).
- `androidMain/.../pop/` — `AndroidDeviceKeystore.kt`, `MainActivity.kt`, `Platform.android.kt`, manifest, cleartext config.
- `iosMain/.../pop/` — `MainViewController.kt` (Compose host), `Platform.ios.kt`, `AudioEngine.ios.kt`, `DeviceKeystore.ios.kt`, `Pairing.ios.kt`. `iosTest/` — `readTestResource` actual, audio engine and QR/pairing tests (`AudioEngineIosTest.kt`, `PairingIosTest.kt`).
- `commonTest/` — `kotlin("test")`, coroutines-test, ktor mock. `commonTest/resources/` is on the unit-test classpath; read with `readTestResource("dsp/x.json")`.

Enrollment is per server URL. Changing the URL or tapping Re-enroll makes a new key, so a new `device_id`. The attestation challenge is baked into the key, so a key cannot be re-enrolled with a fresh nonce.

If attested keygen fails (some emulators), the app makes a plain key and sends `chain: null`. The server then needs `POP_ALLOW_UNATTESTED=1`.

`security_level`: from `KeyInfo.securityLevel` on API 31+. Below 31: `software` if not in secure hardware, `strongbox` if StrongBox keygen worked, else `tee`.

## Pairing

- `Invite.kt` (commonMain): 49-byte codec, `pop1:` QR form, expiry, host key hint, APDU framing (`PopApdu`). Tests: `InviteCodecTest` (vector from `server/pop/invite.py`).
- `Pairing.android.kt`: `PopHceService` (AID `F0454E434F504F50`, `res/xml/apduservice.xml`, category other) answers SELECT with `InviteBeacon.current() ‖ 9000`, else `6A82`. The beacon is set only while the host is on the invite screen. Host screen also sets the service as preferred (`CardEmulation.setPreferredService`).
- Guest: `enableReaderMode(NFC_A | SKIP_NDEF_CHECK | NO_PLATFORM_SOUNDS)` while on Join, `IsoDep.transceive(SELECT)`. QR: CameraX preview + ML Kit barcode (bundled model). QR render: ZXing core.
- NFC off: "Turn on NFC" button, QR still works. No NFC: QR only. State rechecked on resume.
- Host invite bytes: server `invite_b64url` when present (checked against session id, token, own key hint), else built locally. Expired unjoined invite -> new session automatically.
- Guest checks `sha256(partner pubkey)[:8]` == invite hint after join; mismatch -> abort, `partner_mismatch`.
- Cancel on Host/Join/Confirm aborts the server session (best effort).

## Build

```
cd app
cp ~/dev/worldid-spike/app/local.properties .     # sdk.dir, gitignored
export JAVA_HOME=$(/usr/libexec/java_home -v 21)  # JDK 26 is too new for Gradle 8.14
../research/sound-bound/spikes/zk/tools/heavy.sh pop-app ./gradlew :composeApp:assembleDebug :composeApp:testDebugUnitTest
# APK: composeApp/build/outputs/apk/debug/composeApp-debug.apk
```

Server URL is baked in at build time (`PopBuildConfig.SERVER_URL`, generated into `composeApp/build/generated/popBuildConfig/` by `genPopBuildConfig`):

```
./gradlew :composeApp:assembleDebug -Ppop.serverUrl=https://xyz.trycloudflare.com
POP_SERVER_URL=http://192.168.0.34:8000 ./gradlew :composeApp:assembleDebug
```

Order: `-Ppop.serverUrl`, then `POP_SERVER_URL`, then `http://10.0.2.2:8000` (the host Mac from the emulator).

## Install

```
adb install -r composeApp/build/outputs/apk/debug/composeApp-debug.apk
adb shell am start -n com.enconomy.pop/.MainActivity
adb logcat -s PopKeystore
```

Server URL defaults to the build value (above). It is editable and remembered; a saved URL wins over the build value, and **Reset to ...** under the field drops it. Same Wi-Fi as the Mac, or `adb reverse tcp:8000 tcp:8000` and `http://127.0.0.1:8000`.

Signed requests (§2.3): `X-Pop-Ts` = wall clock + server offset. The offset comes from one `GET /v1/time` before the first signed call (midpoint of the rtt) and again on `auth_stale`, then the call is re-sent once. Still `auth_stale` = "Phone clock is off; set automatic time."

Tap **Ping server** (`/v1/time` + `/v1/config`), then **Enroll**.

## Run (§4-§8)

`PopRun` (commonMain) per attempt: pre-flight (volume ≥ 60 %, no BT/wired out, mic permission) -> 10 × `/v1/time` (refuse above 300 ms rtt) -> `arm` (own play PCM + own bed) -> open mic + track -> long-poll `t0_ms` -> record t0 − 1 s .. t0 + 2 s, play at A 0 s / B 0.95 s -> build own 128 null codes (only after capture; no DSP while the mic is open) -> `PopRound.selfCheck` (flat blocks, own arrival, own arrival vs OS timestamp) -> sign + POST the 71-byte commit -> partner bed (partner null codes build meanwhile) -> partner window (flat blocks again, partner arrival) -> half -> sign + POST the 269-byte transcript (+ meta) -> upload the capture WAV if `/v1/config` says so -> poll.

- A failed step posts `/fail {attempt, reason}`. Retry is decided by the server: the view goes back to `confirmed` with attempt 1 and the phone re-arms, showing why. `too_far`, signature and mismatch reasons are final.
- A 409 on commit / transcript / fail = the partner already moved the session on; the phone follows the view.
- `400 bad_attempt` on arm (or `transcript_mismatch` on commit) with the view already at a later attempt = the partner's `/fail` won the race; the phone re-reads the view and re-arms at the current attempt.
- Pre-flight or clock problems stop before arm (nothing sent); fix and tap **Start**.
- Any other error aborts the session and shows `aborted` with the detail.
- Result screen: NEAR / NOT NEAR, `flight_cm`, the §8.3 text, attempts.

Transcript golden vector: `server/tests/test_transcript_codec.py` (`VEC`, `VEC_SHA`, `COMMIT_SHA`); the same literals are in `commonTest/.../TranscriptCodecTest.kt`.

Live check without phones: `LiveServerRunTest` (androidUnitTest) runs two in-process phones (software keys, a fake room instead of mic/speaker, real DSP) through the real server. Skipped unless `POP_LIVE_URL` is set:

```
cd server && POP_ALLOW_UNATTESTED=1 POP_DB=/tmp/pop.sqlite POP_DATA_DIR=/tmp/pop POP_PORT=8765 uv run python -m pop &
cd app && POP_LIVE_URL=http://127.0.0.1:8765 ./gradlew :composeApp:testDebugUnitTest --tests 'com.enconomy.pop.LiveServerRunTest' --rerun
```

It checks NEAR at 30 cm, `too_far` at 150 cm with no retry, and a 20 ms dropped block on B -> glitch -> attempt 1 -> NEAR.

## Two-phone demo

1. Server on the Mac: `cd server && uv run python -m pop` (listens on `0.0.0.0:8000`).
   - Same Wi-Fi: base URL `http://$(ipconfig getifaddr en0):8000`.
   - Any network: `cloudflared tunnel --url http://localhost:8000`, base URL = the printed `https://*.trycloudflare.com`.
   - Phones with a real attestation chain need nothing else. If a phone enrolls with `chain: null` (no attested keygen), start the server with `POP_ALLOW_UNATTESTED=1`.
2. Build once, install on both phones: `adb -s <serial> install -r composeApp/build/outputs/apk/debug/composeApp-debug.apk`.
3. On each phone: set the same Server URL, **Ping server**, pick a name, **Enroll**. Media volume up (≥ 60 %), no Bluetooth headphones.
4. Host phone: tap **Host**. It shows a QR and serves the invite over NFC.
5. Guest phone: tap **Join**, then tap the phones back to back (NFC) or scan the host's QR.
6. Both: check the partner name, tap **Confirm** (allow the microphone the first time).
7. Keep the phones side by side on the table, speakers free, room quiet. Each plays one short sound; the result shows on both in a few seconds.
8. **Again** goes back to Home. Recordings and `result.json` land in `server/data/sessions/<id>/`.

## iOS

`iosApp/iosApp.xcodeproj` (hand-written, no xcodegen) hosts `MainViewController()` from the static `ComposeApp` framework. The **Compile Kotlin Framework** build phase runs `./gradlew :composeApp:embedAndSignAppleFrameworkForXcode` (JDK 21 via `java_home`).

Status: all implemented: platform basics (prefs, device model, clocks, screen-on, mic permission), audio engine (`AudioEngine.ios.kt`), Secure Enclave key + App Attest (`DeviceKeystore.ios.kt`), Core NFC reader and QR draw/scan (`Pairing.ios.kt`). NFC and App Attest need a paid team (`POP_PAID = 1`).

App Attest: the server's `POP_IOS_APP_ID` must be `TEAMID.<BUNDLE_ID>` (your `TEAM_ID` and `BUNDLE_ID` from `Local.xcconfig`, e.g. `ABCDE12345.com.enconomy.pop`).

Tests: `./gradlew :composeApp:iosSimulatorArm64Test` runs all of `commonTest`, DSP parity included. The simulator reads the fixtures straight from `src/commonTest/resources` (absolute path baked in by `genTestResourceDir`).

Pairing on iOS: no HCE, so an iPhone host shows QR only. An iPhone guest reads an Android host's card with Core NFC (paid build only), else scans QR.

### Run on your iPhone (free Apple ID)

1. Xcode > Settings > Accounts: add your Apple ID (makes a "Personal Team").
2. Create `iosApp/Configuration/Local.xcconfig` (gitignored):
   ```
   TEAM_ID = ABCDE12345
   POP_SERVER_URL = http:/$()/192.168.0.34:8000
   ```
   Team ID: Xcode > target iosApp > Signing & Capabilities > Team shows it; picking the team there works too, but edits the project file. The `$()` keeps `//` from being read as a comment.
3. If the free team says the bundle id is taken, add `BUNDLE_ID = com.<you>.pop` to `Local.xcconfig`.
4. iPhone: Settings > Privacy & Security > Developer Mode on (reboots). Plug in, trust the Mac.
5. Open `iosApp/iosApp.xcodeproj`, pick the phone, Run. First launch: Settings > General > VPN & Device Management > trust your developer profile.
6. Free-team apps expire after 7 days; Run again to reinstall.

Server URL: baked in like Android (`PopBuildConfig.SERVER_URL`), from `POP_SERVER_URL` in the xcconfig (passed to Gradle as an env var). Simulator: `http://localhost:8000` (the default). Real iPhone: the Mac LAN IP (`ipconfig getifaddr en0`) or a `cloudflared` https URL. ATS allows plain HTTP to local hosts and IPs only (`NSAllowsLocalNetworking`). The in-app field still overrides it.

The free build has no entitlements (`iosApp.entitlements` is empty): QR pairing only, and the key enrolls unattested (`chain: null`, server needs `POP_ALLOW_UNATTESTED=1`).

### Paid build

`POP_PAID = 1` in `Local.xcconfig` switches to `iosApp-paid.entitlements`: NFC tag reading (`TAG`, SELECT AID `F0454E434F504F50` listed in Info.plist) and App Attest (`POP_APPATTEST_ENV`, default `development`). It also sets Info.plist `PopNfcReader = YES`, which turns the NFC reader on in the app. Needs a paid team with those capabilities on the App ID.

### Command line (no signing)

```
cd app/iosApp
../../research/sound-bound/spikes/zk/tools/heavy.sh ios xcodebuild -project iosApp.xcodeproj -scheme iosApp \
  -destination 'platform=iOS Simulator,name=iPhone 16 Pro' -derivedDataPath build/dd CODE_SIGNING_ALLOWED=NO build
# device: -destination 'generic/platform=iOS'
```

## Option A proof on the phone (POPT v2)

After a NEAR verdict on a v2 run, the phone proves its half with `app/prover` (docs/pop-prover.md):

- `zk/WitnessInput.kt` builds the `oa2t_s48` / `oa2t_s44` witness JSON from the signed POPT v2 bytes, the capture, the rec tree, own + partner int8 codes and the SBcred3 (port of spike `prep_popt2.py`). It first re-checks what the circuit needs (integer rule at a_self / a_partner, `|self_os_delta| <= delta`, geometry, code_commit, rec_root, credential expiry vs validAt) and refuses in ms instead of after the native witness.
- `zk/ProvingKeys.kt`: keys from `GET /v1/zk/keys/<circuit>.pk.zst`, sha256 pinned, cached in `filesDir/zk` / `Application Support/zk` (no backup), resumable (`.part` + Range), one refetch on a bad hash. On mobile data the proof waits for "Download and prove" (Wi-Fi recommended, ~12 MB).
- Keys come from `app/prover/keys/oa2t_s48.pk.zst` / `oa2t_s44.pk.zst` (gitignored; zstd of the spike's `oa2t_s48.pk` / `oa2t_s44.pk`, sha256 = the pins in `ProvingKeys.kt`). The server serves `POP_ZK_KEYS` (default `server/data/zk/`, empty in a fresh checkout): before any phone test either copy both files there or start the server with `POP_ZK_KEYS=../app/prover/keys`. Otherwise the first download is a 404 (`not_served`).
- `zk/ProofRunner.kt`: memory guard (skip when RAM < ~3.4 GB or Android free < ~1.5 GB; iOS: skip when `os_proc_available_memory` + footprint < ~1.95 GB, i.e. no increased-memory-limit), key, witness input, open key, constraint check (public vector must equal the derived one), prove, close; native calls on `Dispatchers.Default`, one prover instance at a time (live proof and bench share a lock; a cancelled prove holds it until the native call returns). Then `POST /v1/session/{id}/proof` multipart: file `proof` (raw bytes) + `meta` `{"attempt","circuit","salt"}` (salt decimal), as in `server/pop/main.py`. 409 `already_submitted` shows as verified; 503 `zk_unavailable`, 404 or any reject keep the proof in `zk/`.
- Key missing on a metered network: the phone stays on v2 and waits for "Download and prove" (docs/pop-prover.md says fall back to v1; v2 is chosen before the verdict, so it can't be undone per run).
- validAt = `valid_at` of the result when the server sends one, else t0 of the attempt in unix seconds.
- Result screen shows the proof status; **Prover bench** (Home) proves a bundled fixture (`composeResources/files/zk/bench_*.json`, `commonTest/resources/zk/tools/gen_bench.py`) and shows witness parity with the spike, key load / check / prove time, proof size, peak footprint (Android VmRSS/VmHWM + native heap, iOS phys_footprint + ledger peak).

Native lib wiring: Android copies `prover/dist/android/arm64-v8a/libpop_prover.so` into generated jniLibs (`copyProverSo`); iOS links `prover/dist/ios/PopProver.xcframework` through cinterop `src/nativeInterop/cinterop/popprover.def` (static lib embedded in the klib). Without `dist/` the app still builds (`ProverLib.available = false`, iOS uses `src/iosNoProver`). `-Ppop.buildProver=true` rebuilds the libs first (run the whole gradle under heavy.sh). iOS paid builds request `com.apple.developer.kernel.increased-memory-limit`.

Heavy checks:
```
S=<dir with oa2t_s48.pk.zst>
POP_ZK_DUMP=/tmp/zkin ./gradlew :composeApp:testDebugUnitTest --tests '*WitnessInputTest' --rerun
prover/target/release/popprover check $S/oa2t_s48.pk.zst /tmp/zkin/180ca04b_48k_A.input.json   # ACCEPT
POP_ZK_KEYS=$S ./gradlew :composeApp:iosSimulatorArm64Test                                    # proves on the simulator
```
