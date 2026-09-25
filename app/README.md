# pop app (KMP, Android)

Proof-of-presence phone app. Contract: `../docs/pop-contract.md`.

Enroll (Keystore P-256, StrongBox if present, attestation chain), pairing by NFC tap or QR, then the full run: clock sync, arm, record + play at t0, self check, signed commitment, partner bed, partner arrival, signed transcript, result. One automatic retry on a failed measurement (server driven).

Layout (`composeApp/src/`):
- `commonMain/.../pop/` — `App.kt` (Compose), `PopController.kt` (screens, enroll, pairing), `RunFlow.kt` (`PopRun`: arm .. result, §4-§8), `Transcript.kt` (269-byte transcript, 71-byte commit, §7), `AudioRun.kt` / `ClockSync.kt` (timing), `PopApi.kt` (wire types + client, §2.3 signing), `Signing.kt` (`DeviceKey`/`DeviceKeystore`, request message, DER -> r||s), `Bytes.kt` (hex, base64, SHA-256), `Platform.kt` (expect decls).
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

## Run (§4-§8)

`PopRun` (commonMain) per attempt: pre-flight (volume ≥ 60 %, no BT/wired out, mic permission) -> 10 × `/v1/time` (refuse above 300 ms rtt) -> `arm` (own play PCM + own bed) -> open mic + track, build the 128 null codes while waiting -> long-poll `t0_ms` -> record t0 − 1 s .. t0 + 2 s, play at A 0 s / B 0.95 s -> `PopRound.selfCheck` (flat blocks, own arrival, own arrival vs OS timestamp) -> sign + POST the 71-byte commit -> partner bed -> partner window (flat blocks again, partner arrival) -> half -> sign + POST the 269-byte transcript (+ meta) -> upload the capture WAV if `/v1/config` says so -> poll.

- A failed step posts `/fail {attempt, reason}`. Retry is decided by the server: the view goes back to `confirmed` with attempt 1 and the phone re-arms, showing why. `too_far`, signature and mismatch reasons are final.
- A 409 on commit / transcript / fail = the partner already moved the session on; the phone follows the view.
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
