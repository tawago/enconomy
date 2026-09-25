# pop app (KMP, Android)

Proof-of-presence phone app. Contract: `../docs/pop-contract.md`.

Now: enroll (Keystore P-256, StrongBox if present, attestation chain), signed Ktor client for the whole contract API, Home with Host / Join. Host creates a session and long-polls it. Join, Run, Result are placeholders.

Layout (`composeApp/src/`):
- `commonMain/.../pop/` — `App.kt` (Compose), `PopController.kt` (screens, enroll), `PopApi.kt` (wire types + client, §2.3 signing), `Signing.kt` (`DeviceKey`/`DeviceKeystore`, request message, DER -> r||s), `Bytes.kt` (hex, base64, SHA-256), `Platform.kt` (expect decls).
- `commonMain/.../pop/dsp/` — DSP lane only (§6).
- `androidMain/.../pop/` — `AndroidDeviceKeystore.kt`, `MainActivity.kt`, `Platform.android.kt`, manifest, cleartext config.
- `commonTest/` — `kotlin("test")`, coroutines-test, ktor mock. `commonTest/resources/` is on the unit-test classpath; read with `readTestResource("dsp/x.json")`.

Enrollment is per server URL. Changing the URL or tapping Re-enroll makes a new key, so a new `device_id`. The attestation challenge is baked into the key, so a key cannot be re-enrolled with a fresh nonce.

If attested keygen fails (some emulators), the app makes a plain key and sends `chain: null`. The server then needs `POP_ALLOW_UNATTESTED=1`.

`security_level`: from `KeyInfo.securityLevel` on API 31+. Below 31: `software` if not in secure hardware, `strongbox` if StrongBox keygen worked, else `tee`.

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
