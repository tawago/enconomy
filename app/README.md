# pop app (KMP, Android)

Proof-of-presence phone app. Contract: `../docs/pop-contract.md`.

Now: enroll (Keystore P-256, StrongBox if present, attestation chain), signed Ktor client for the whole contract API, Home with Host / Join. Pairing (§3): Host shows the invite as QR and serves it over NFC HCE; Join reads it by NFC reader mode or camera QR; both see a Confirm screen. Run, Result are placeholders.

Layout (`composeApp/src/`):
- `commonMain/.../pop/` — `App.kt` (Compose), `PopController.kt` (screens, enroll), `PopApi.kt` (wire types + client, §2.3 signing), `Signing.kt` (`DeviceKey`/`DeviceKeystore`, request message, DER -> r||s), `Bytes.kt` (hex, base64, SHA-256), `Platform.kt` (expect decls).
- `commonMain/.../pop/dsp/` — DSP lane only (§6).
- `androidMain/.../pop/` — `AndroidDeviceKeystore.kt`, `MainActivity.kt`, `Platform.android.kt`, manifest, cleartext config.
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

## Install

```
adb install -r composeApp/build/outputs/apk/debug/composeApp-debug.apk
adb shell am start -n com.enconomy.pop/.MainActivity
adb logcat -s PopKeystore
```

Server URL defaults to `http://192.168.0.34:8000`. It is editable and remembered. Same Wi-Fi as the Mac, or `adb reverse tcp:8000 tcp:8000` and `http://127.0.0.1:8000`.

Tap **Ping server** (`/v1/time` + `/v1/config`), then **Enroll**.
