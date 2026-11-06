# poc-phone-signing

Item 4 of `03-synth-plan.md`. The phone has to sign a raw 32-byte digest so the signature passes EIP-8141 scheme 2 (P256). Today the app signs in message mode (`SHA256withECDSA`, `...MessageX962SHA256`), so it really signs `sha256(digest)` and fails. This spike is the digest-mode code, the tests, and a patch for `app/`. Nothing under `app/` was touched.

## What's here

- `common/FrameSig.kt`: pure Kotlin, safe for commonMain. Low-s normalize (`s -> n - s`, bytewise, no BigInteger), signer = `keccak256(qx||qy)[12:]`, 128-byte scheme-2 field `r||s||qx||qy`, and a `FrameKey` interface with `signDigest(digest32)`. DER to r||s reuses the app's `derToRawRs` (a verbatim copy sits in `common/AppSigningCopy.kt` so this compiles on its own).
- `android/AndroidFrameKeystore.kt`: new alias `pop-frame-v1`, `setDigests(DIGEST_NONE, DIGEST_SHA256)`, `NONEwithECDSA` over the 32 bytes, StrongBox first, then TEE, then a plain key on emulators only.
- `ios/IosFrameKey.kt`: Kotlin/Native, `kSecKeyAlgorithmECDSASignatureDigestX962SHA256` on the existing Secure Enclave key. iOS doesn't need a new key because the algorithm is picked at sign time.
- `ios/sign_digest.swift`: the same Security.framework calls, run on this Mac.
- `patch/app.patch`: wires it into the app (details below).
- `jvm-test/`: a tiny Gradle project (Kotlin 2.2.20, kotlincrypto Keccak, same versions as the app). It also has `android-compile`, which type-checks the Android file against `android-35/android.jar`.
- `noble-check.cjs`: re-verifies the vectors with `@noble/curves`, the library the sidecar uses.
- `verify-printout.cjs`: for Nov 5. Paste what the debug button prints and it says PASS or FAIL.
- `run.sh`: re-runs everything that runs on a laptop.

## Scheme-2 rules tested

These come from the sidecar source, not from memory: `tmp/mempool-workshop-sidecar/packages/executor/src/services/FrameTxService/signature.ts`. Lines 19-35 cover msg: empty means sig_hash, an explicit msg must be exactly 32 bytes and not all zero. Lines 58-79 cover P256: 128 bytes, `0 < r < n`, `0 < s <= n/2`, signer == last 20 bytes of `keccak(qx||qy)`, and `p256.verify(msg)` with `lowS:false` and no prehash. `jvm-test/src/test/kotlin/Scheme2.kt` is a port of that code. Its P256VERIFY is plain BigInteger curve math, so it shares nothing with the signer.

## Measured (2026-11-02, this M2 Mac)

- JVM, `./gradlew test`, all 7 tests green:
  - 256 SunEC `NONEwithECDSA` signatures over random digests. 128 came out high-s. Each of those was valid ECDSA but rejected by scheme 2, and accepted after normalizing. Every normalized one passes as an explicit msg and as an empty msg over sig_hash, and Java's own verifier agrees.
  - Low-s edges (`n/2`, `n/2+1`, `1`, `n-1`, `0`, `n`) plus 10k random s values against BigInteger. Normalizing is idempotent and leaves r alone.
  - The trap: a `SHA256withECDSA` signature fails against the raw digest and passes against `sha256(digest)`.
  - Rejections: wrong signer, the first 20 bytes instead of the last 20, zero msg, 31-byte msg, 127-byte signature, wrong digest.
- macOS Security.framework (`sign_digest.swift`), 64 signatures each from a software key and an ephemeral Secure Enclave key. `DigestX962SHA256` is supported on both, and every signature passes scheme 2 after low-s. The SE key really is SE-backed: its `kSecAttrTokenID` is `com.apple.setoken`, the same check the app uses for `securityLevel`. On the last run 29 and 26 of the 64 came out high-s (35 and 36 on the first run), so Apple doesn't normalize and we have to. The message-mode signatures over the same bytes all fail. The SE result was a surprise: an unsigned CLI could create a non-permanent SE key.
- noble 1.9.1 (from `relayer/node_modules`; the sidecar pins 1.8.1, and both are 1.x with the same verify API): 24/24 vectors pass with `lowS:false` and `lowS:true`. The raw high-s ones fail `lowS:true`, as expected, and none verify with `prehash:true`.
- Patch: `git apply --check` is clean against `53604e3`. I applied it to a copy of `app/` in the scratchpad, never the real one. `compileDebugKotlinAndroid`, `compileKotlinIosSimulatorArm64` and `compileKotlinWasmJs` all build. `testDebugUnitTest` passes: the new `FrameSigTest` 3/3 and the existing `SigningTest` 3/3. `assembleDebug` builds an APK.
- `verify-printout.cjs` self-test: a good printout gives PASS, and a message-mode printout gives FAIL with `verifiesSha256OfDigest: true`.

## The patch

- `Signing.kt`: `DeviceKeystore.frameKey(): FrameKey`. The default throws, so FakeKey and JvmKey still compile.
- Decision: the plan said `signDigest` on `DeviceKey`. I put it on a separate `FrameKey` because on Android the enrolled `pop-device-v1` key is SHA256-only and physically can't do it. iOS and web return the device key itself (`IosDeviceKey : DeviceKey, FrameKey`). Android returns `pop-frame-v1`, created on first use.
- Consequence: on Android the registry's `deviceAddr` is the signer of `pop-frame-v1`, not of the enrolled key. Registration has to send `frameKey().signerAddress`. Re-enrolling (`delete()`) wipes the frame key too.
- `FrameSig.kt`: the common file plus `FRAME_TEST_DIGEST = sha256("pop-frame-test-v1")` and `frameKeyReport()`, which prints `frame-key / signer / digest / rs / qxqy / sign_ms` and sends the same text to stdout (logcat `System.out`).
- `PopController.signTestDigest()` plus a "Sign test digest" button in the Server panel, shown only when `isDebugBuild()` is true. The output lands in `s.info`.
- Web: `signDigest` uses the existing noble `p256SignHash` and normalizes to low-s.

## Untested (only a real phone can prove these)

- Whether StrongBox accepts `DIGEST_NONE` at keygen. If it refuses, the code falls back to TEE and logs why. Check `securityLevel` in the printout. TEE is fine for the demo, StrongBox is a bonus.
- Whether TEE/KeyMint `NONEwithECDSA` gives a signature over exactly our 32 bytes. JVM SunEC has the same contract, but that isn't the phone.
- Whether attestation works on the second alias. The code passes a challenge, but nothing is wired to send the chain.
- iPhone Secure Enclave with the persistent, enrolled `pop-device-v1` key. The Mac SE is the same API and the same kind of chip, but not the same device.
- Sign latency on hardware (`sign_ms` in the printout).
- The emulator. I booted `Pixel_7_API_36` and installed the patched debug APK, but it sat at a PIN lock after the cold boot, so I stopped there. Side effect: the emulator now has the patched debug build of `com.enconomy.pop`, data kept. The next normal install replaces it. Even the emulator only proves the format, not hardware.

## Nov 5, 10 minutes

1. `git apply research/ethglobal-mumbai/poc-phone-signing/patch/app.patch`, then build debug for the Pixel and the iPhone.
2. Tap Server, then "Sign test digest". Copy the text, or run `adb logcat -s System.out`.
3. `node verify-printout.cjs printout.txt`. PASS means the device works with scheme 2. FAIL with `verifiesSha256OfDigest: true` means the phone hashed again. Then use the fallbacks in `03-synth-plan.md` (software P-256 key wrapped by hardware).
