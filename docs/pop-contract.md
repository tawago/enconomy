# Proof-of-presence contract (pop-v1)

Two Android phones pair, each plays JBL250 once, both record, each computes its own half of the four-arrival distance, signs it with a Keystore P-256 key, the server combines halves: NEAR (< 60 cm) or not.

Source: `research/2026-09-26-sound-bound-decision.md` (protocol), `research/2026-09-25-cheating-participant-and-trust.md` (threat model), `research/2026-09-26-zk-gap-research.md` §5 (bugs fixed here). Reference code: `research/sound-bound/spikes/melody/fieldtest/` (`fieldprobes.py`, `fieldanalysis.py`). Read-only; never edit anything under `research/`.

Out of scope: World ID, ENS, onchain, ZK. ZK is deferred (another agent owns it); the transcript in §7 is shaped so it can consume it later without a change.

Rule for builders: if this file is silent, pick the simplest option and write it in your module docstring / README. If this file is wrong, follow its spirit and say so in your report.

## 1. Components and layout

| Path | Owner | What |
| --- | --- | --- |
| `server/` | server | Python 3.11+, FastAPI, uv, pytest. `pyproject.toml`, `pop/` package, `tests/`, `data/` (gitignored: sqlite + recordings). Pattern: `~/dev/worldid-spike/backend/`. |
| `server/pop/jbl250.py` | server | Vendored JBL250 generator (port of `fieldprobes` JBL250 path + `melody_probes._multisine/_fade`). Golden-tested against fieldprobes. |
| `server/pop/dsp_ref.py` | server | Python reference of the phone DSP (§6), used for fixtures and the fake-phone e2e. numpy only. |
| `app/` | app | KMP Android, package `com.enconomy.pop`. Pattern: `~/dev/worldid-spike/app/` (Gradle 8.14, Kotlin 2.2.20, Compose 1.9.0, Ktor 3.2.3, AGP 8.11.1; minSdk 24, JDK 21). Copy `local.properties` from the spike. |
| `app/composeApp/src/commonMain/kotlin/com/enconomy/pop/` | app | Session state machine, HTTP client, transcript encoding, invite codec. Pure Kotlin. |
| `app/composeApp/src/commonMain/kotlin/com/enconomy/pop/dsp/` | dsp | ALL signal code (§6). Pure Kotlin, no Android imports. |
| `app/composeApp/src/commonTest/kotlin/com/enconomy/pop/dsp/` + `commonTest/resources/dsp/` | dsp | Parity tests + committed fixtures. |
| `app/composeApp/src/androidMain/kotlin/com/enconomy/pop/` | app | Keystore, attestation, AudioTrack/AudioRecord, NFC HCE + reader, QR (CameraX + ML Kit or ZXing), foreground service. |
| `tools/dsp-fixtures/` | dsp | `make_fixtures.py`: fieldtest recordings -> `commonTest/resources/dsp/*.json`. Uses `research/proximity-echo/.venv/bin/python3`. |

Server listens on `0.0.0.0:8000`, plain HTTP on the LAN (app manifest allows cleartext, as the spike). Every device request is signed (§2), so HTTP is acceptable for the hackathon.

Constants shared by all three sides live in one table (§6.1). Server exposes them at `GET /v1/config`; app asserts equality at startup (mismatch = refuse to run).

## 2. Device enrollment and request auth

### 2.1 Key

| Item | Value |
| --- | --- |
| Alias | `pop-device-v1` |
| Spec | `KeyGenParameterSpec(alias, PURPOSE_SIGN)`, `ECGenParameterSpec("secp256r1")`, `DIGEST_SHA256`, `setAttestationChallenge(nonce)`, `setIsStrongBoxBacked(true)`; on `StrongBoxUnavailableException` retry without StrongBox (TEE). |
| Signing | `Signature.getInstance("SHA256withECDSA")` over raw message bytes. Output DER; app converts to raw `r||s` (64 bytes, big-endian, each 32) before sending. Only `r||s` ever goes on the wire. Low-s not required. |
| Public key | SEC1 uncompressed, 65 bytes `04||X||Y`. |
| `device_id` | hex of first 16 bytes of `sha256(pubkey65)` (32 hex chars). |
| Security level | App reports `KeyInfo.securityLevel` (API 31+) as `"strongbox" \| "tee" \| "software" \| "unknown"`; server also parses it from the attestation. |

### 2.2 Enroll

1. `GET /v1/enroll/nonce` -> `{nonce: hex32}` (32 random bytes, TTL 10 min, single use).
2. Generate the key with `setAttestationChallenge(nonce bytes)`. `KeyStore.getCertificateChain(alias)` -> chain.
3. `POST /v1/enroll` `{nonce, device_id, pubkey: hex65, display_name (1..32 chars), model: Build.MODEL, security_level, chain: [base64 DER leaf, ..., root] | null}`. Unsigned (there is no device yet). Response `{device_id, enrolled_at}`.

Server verification (best effort, hackathon grade):

| Checked | How |
| --- | --- |
| nonce exists, unused, unexpired | store |
| leaf cert public key == `pubkey` | `cryptography` parse |
| attestation extension present (OID `1.3.6.1.4.1.11129.2.1.17`) and `attestationChallenge == nonce bytes` | ASN.1 parse of KeyDescription (field 4) |
| each cert signed by the next | `cryptography` verify, failure = reject |
| `device_id == sha256(pubkey)[:16]` | recompute |

NOT verified (say so in `README`): root pinned to Google roots, revocation / RKP, `attestationApplicationId` (package + signing digest), verified-boot state, minimum security level, cert validity dates. With `POP_ALLOW_UNATTESTED=1` (env), `chain: null` is accepted and stored with `attested: false` (emulators, fake phones in tests). Default off.

Store: `devices(device_id PK, pubkey, display_name, model, security_level, attested, chain_pem, enrolled_at)`.

Re-enroll with the same `device_id` replaces the row only if the pubkey is identical (same key regenerated is impossible; a new key gets a new id).

#### 2.2.1 iOS enroll

Signing key: Secure Enclave P-256 (`kSecAttrTokenIDSecureEnclave`), same wire format as §2.1 (`pubkey` 65 bytes, raw `r||s`). The simulator has no Secure Enclave, so there it is a software key.

App Attest (`DCAppAttestService`) makes its own key; the app cannot attest the signing key directly. The binding is through `clientDataHash`:

```
clientDataHash = sha256(nonce_bytes || sha256(pubkey65))      // 32 + 32 bytes in, 32 out
DCAppAttestService.generateKey() -> keyId
DCAppAttestService.attestKey(keyId, clientDataHash) -> attestation (CBOR)
```

`POST /v1/enroll` `{nonce, device_id, pubkey, display_name, model, platform: "ios", key_kind: "secure_enclave" | "software", security_level: same as key_kind, chain: null, app_attest: {key_id: base64 std, attestation: base64 std} | null}`. `platform` defaults to `"android"`. `key_id` is the base64 string `generateKey` returns. Response adds `platform`, `key_kind`.

Server checks (`server/pop/appattest.py`): `fmt == "apple-appattest"`; `x5c = [credCert, intermediate]` chains to the Apple App Attestation Root CA (embedded, sha256 `1cb9823b…c932`); credCert extension `1.2.840.113635.100.8.2` nonce == `sha256(authData || clientDataHash)` (else `enroll_bad_challenge`); `sha256(credCert pubkey65) == keyId == credentialId`; `rpIdHash == sha256(appId)` with `appId = TEAMID.<BUNDLE_ID>` (e.g. `ABCDE12345.com.enconomy.pop`) from env `POP_IOS_APP_ID`; `signCount == 0`; aaguid `appattestdevelop` or `appattest\0\0\0\0\0\0\0`. Other failures: `enroll_bad_attestation`. Not checked: validity dates, receipt, revocation.

`app_attest: null` (free personal team: no App Attest entitlement; simulator: App Attest unsupported) is accepted only with `POP_ALLOW_UNATTESTED=1`, stored `attested: false`. `attested: true` on iOS means "a genuine app instance saw this nonce and this pubkey"; that the signing key lives in the Secure Enclave is only reported (`key_kind`), not proven.

Store adds `platform`, `key_kind` (`android_keystore` on Android), `attest_key_id` (hex).

### 2.3 Request auth (every device request after enroll)

Headers:

| Header | Value |
| --- | --- |
| `X-Pop-Device` | `device_id` |
| `X-Pop-Ts` | unix ms, decimal |
| `X-Pop-Sig` | base64 (std, padded) of raw `r||s` |

Message signed (ASCII, `\n` separators, no trailing newline):

```
pop-req-v1\n<METHOD>\n<PATH incl. query, no host>\n<sha256 hex of body bytes, empty body = sha256("")>\n<X-Pop-Ts>
```

Server: |now − ts| ≤ 60 s, replay cache of `(device_id, ts, sig)` for 120 s, verify with the stored pubkey. Failures: 401 `{"error":"auth_bad_signature" | "auth_stale" | "auth_replay" | "auth_unknown_device"}`.

## 3. Pairing

Roles: Host = A = card side (NFC HCE or shows QR). Guest = B = reader side (taps or scans).

### 3.1 Create

`POST /v1/session` (host, signed) -> `{session_id: hex32, join_token: hex32, expires_at_ms}`. Token TTL 120 s, single use. Server: `sessions(session_id, seed_hex (32 random bytes, NEVER sent), nonce_hex (32 random bytes), state, attempt, host_device_id, guest_device_id, ...)`.

### 3.2 Invite bytes (49 bytes)

| Offset | Len | Field |
| --- | --- | --- |
| 0 | 4 | magic `"POP1"` |
| 4 | 1 | version `0x01` |
| 5 | 16 | session_id (raw bytes of the hex32) |
| 21 | 16 | join_token (raw) |
| 37 | 4 | expires_at, unix seconds, u32 BE |
| 41 | 8 | host key hint: first 8 bytes of `sha256(host pubkey65)` |

QR payload: `pop1:` + base64url (no padding) of the 49 bytes (~71 chars). App accepts either form. No server URL inside; both apps carry the same base URL setting (editable, remembered, as the spike).

NFC HCE (host): `HostApduService`, `apduservice.xml` category `other`, AID `F0454E434F504F50` (F0 = proprietary, then ASCII "ENCOPOP"). Reader (guest): `NfcAdapter.enableReaderMode(FLAG_READER_NFC_A | FLAG_READER_SKIP_NDEF_CHECK | FLAG_READER_NO_PLATFORM_SOUNDS)`, `IsoDep.transceive`.

| APDU | Bytes |
| --- | --- |
| SELECT | `00 A4 04 00 08 F0 45 4E 43 4F 50 4F 50 00` |
| Response OK | 49 invite bytes `‖ 90 00` |
| Response no invite ready | `6A 82` |

The host regenerates the invite on each new session; the service answers with the current one only while the host is on the invite screen.

### 3.3 Join and confirm

1. Guest: `POST /v1/session/{id}/join` `{join_token}` (signed) -> `{session, ...}`. Errors: 404 unknown, 410 `token_expired`, 409 `already_joined`, 400 `self_join` (same device).
2. Both poll `GET /v1/session/{id}` and see `partner: {device_id, display_name, model, attested}`. Guest also checks the invite's key hint against `sha256(partner pubkey)[:8]` (mismatch = abort, `partner_mismatch`).
3. Each: `POST /v1/session/{id}/confirm` `{}`. Both confirmed -> state `confirmed`, response includes `nonce` (hex32) and both pubkeys.

## 4. Setup

### 4.1 Clock sync

10 × `GET /v1/time` -> `{server_ms}`. Per ping: `t0 = System.nanoTime()` before, `t1` after; `rtt = t1 − t0`; keep the ping with the smallest rtt; `offset_ns = server_ms·1e6 − (t0 + rtt/2)`. So `server_ms(now) = (System.nanoTime() + offset_ns)/1e6`. Run after confirm, before arm. Report `rtt_min_ms` in arm. Refuse to arm if `rtt_min_ms > 300`.

Phone time base everywhere: `System.nanoTime()` (== `CLOCK_MONOTONIC`, the clock `AudioTimestamp.nanoTime` uses).

### 4.2 Sample rate

Preferred 48000. App reads `AudioManager.PROPERTY_OUTPUT_SAMPLE_RATE`; if 36000 ≤ rate ≤ 96000 use it, else 48000. Play and record at the same rate. App reports `sample_rate` at arm; server renders that phone's PCM at that rate. The two phones may differ.

### 4.3 Arm

`POST /v1/session/{id}/arm` `{attempt, sample_rate, rtt_min_ms}` -> `{attempt, sample_rate, play: {pcm_b64, n}, own_bed: {pcm_b64, n}}`.

- `play` = full JBL250 waveform for MY role (tune + secret bed), float32 LE base64, `n = round(0.25·sr)` samples, gain per `POP_GAIN_DB` (default 0; peak-limited to 0.95 as `fieldprobes.render`).
- `own_bed` = my bed template (what I correlate against for my self arrival). Partner's bed is NOT here (§5).
- App: open AudioRecord and AudioTrack, fill the track, then poll for start.

Audio settings (androidMain):

| Item | Value |
| --- | --- |
| AudioRecord | source `UNPROCESSED` if `AudioManager.getProperty(PROPERTY_SUPPORT_AUDIO_SOURCE_UNPROCESSED) == "true"` else `VOICE_RECOGNITION`; `ENCODING_PCM_16BIT`, mono, `sample_rate`; buffer ≥ 1 s. If `AcousticEchoCanceler/NoiseSuppressor/AutomaticGainControl.isAvailable()`, create on the session id and `setEnabled(false)`. |
| AudioTrack | `USAGE_MEDIA`, `CONTENT_TYPE_SONIFICATION`, `ENCODING_PCM_FLOAT`, mono, `sample_rate`, `MODE_STATIC`, `PERFORMANCE_MODE_LOW_LATENCY`. Buffer = `PRIMER_S` (0.3 s) of zeros ‖ the play PCM. Sound onset is track frame `PRIMER_FRAMES = round(0.3·sr)`. |
| Pre-flight | media volume ≥ 60% of max (else block with message), no Bluetooth/wired output route (`AudioManager.getDevices(GET_DEVICES_OUTPUTS)` has no A2DP/headset), foreground service with `microphone` type on Android 14+. |

### 4.4 Start and schedule

Both armed -> server sets `t0_ms = now + 3000` (server clock) and state `started`. App gets `t0_ms` from the poll.

| Time (rel. t0) | A | B |
| --- | --- | --- |
| −1.0 s | `AudioRecord.startRecording()` | same |
| 0.0 s (`A_PLAY_S`) | `AudioTrack.play()` at `t0 − PRIMER_S` (so the sound starts at t0) | records |
| 0.95 s (`B_PLAY_S`) | records | `play()` at `t0 + 0.95 − PRIMER_S` |
| 2.0 s | stop recording | stop recording |

Capture window kept and hashed: exactly `CAPTURE_FRAMES = round(2.5·sr)` int16 frames starting at the frame nearest `t0 − LEAD_S` (`LEAD_S = 0.5`). Frame→time: `AudioRecord.getTimestamp(ts, TIMEBASE_MONOTONIC)` after ≥ 0.5 s of recording; `rec_frame0_ns = ts.nanoTime − ts.framePosition·1e9/sr`. Playback: after the track drains, `AudioTrack.getTimestamp(ts)`; `play_onset_ns = ts.nanoTime + (PRIMER_FRAMES − ts.framePosition)·1e9/sr`. If `getTimestamp` returns false, fall back to the scheduled `play()` call time + `AudioManager` output latency estimate and set `ts_source = "fallback"` (server flags it; still accepted in v1).

Expected arrivals (frame index in the capture):

```
expected_self    = (play_onset_ns − capture_frame0_ns) · sr / 1e9
expected_partner = (t0_ns + partner_offset_s·1e9 − capture_frame0_ns) · sr / 1e9,   partner_offset_s = 0.95 (A listening to B) or 0 (B listening to A)
t0_ns = t0_ms·1e6 − offset_ns
```

Search window per arrival: `[expected − 0.150 s, expected + 0.250 s)` in frames, clipped to the capture. If clipping leaves < 3 frames: failure `capture_failed`.

## 5. Codes: derivation and commit-then-reveal

### 5.1 Derivation (server only; fixes `fieldprobes._sub` missing attempt)

```
bed_key(role, attempt)  = sha256("pop-v1|" + seed_hex + "|JBL250|" + role + "|" + str(attempt) + "|bed")     # 32-byte digest
bed = multisine(PCG64(int.from_bytes(bed_key, "big")), sr, band=(2000, 18000), dur=0.25)   # numpy, exact fieldprobes math
```

`jbl250.py` API (vendored, exact port):

```python
generate(bed_key: bytes, role: str, sr: int) -> np.ndarray[float32]     # tune + bed, RMS 0.15   (fieldprobes.generate with _rng seeded by bed_key)
render(bed_key, role, sr, gain_db=0.0) -> (np.ndarray[float32], info)   # peak-limited to 0.95
template(bed_key, role, sr) -> np.ndarray[float64]                        # scale * faded bed (what the receiver correlates with)
```

Golden test: `bed_key = sha256(f"fieldtest-v1|{seed}|JBL250|{role}|bed")` must reproduce `fieldprobes.generate/template(seed, "JBL250", role, sr)` for seed `"5b"*32`, roles A/B, sr 44100/48000, max abs diff ≤ 1e-6. Run once, store the expected arrays as `server/tests/golden/jbl250_*.npy` (small: 12000 floats each), so the server tests never import `research/`.

Tune (public): `JBL250_TUNE`, `JBL250_HARM_AMP`, envelopes and constants copied verbatim from `fieldprobes.py` lines 63-85. Every partial < 1800 Hz.

A retry (attempt 1) gets new bed keys for both roles. `attempt ∈ {0, 1}`.

### 5.2 Reveal order (per phone, per attempt)

| Step | Phone does | Server gives |
| --- | --- | --- |
| arm | reports sr | own `play` PCM + own bed template |
| record + self check | finds own arrival, flat-block check, hashes capture | — |
| commit | `POST /v1/session/{id}/commit` with signed commitment (§7.2) | partner's bed template (`partner_bed: {pcm_b64, n}` at MY sr), only now |
| measure | finds partner arrival, computes half, signs transcript | — |
| submit | `POST /v1/session/{id}/transcript` | ack; result when both are in |

The server never sends a phone the partner's play PCM, the partner's bed before that phone's commit, or any seed. `GET` of another role's material does not exist.

### 5.3 PCM wire format

`pcm_b64` = base64 (std, padded) of little-endian IEEE float32 samples, mono. `n` = sample count; app verifies `len == 4·n` and `n == round(0.25·sr)`. Templates are float64 on the server, sent as float32; the phone converts to double.

## 6. On-phone checks and DSP (the Kotlin port)

Package `com.enconomy.pop.dsp`, pure Kotlin, `DoubleArray` everywhere, no Android imports. Public API (commonMain):

```kotlin
object PopDsp {
  fun nullTemplate(sessionIdHex: String, emitter: Char, attempt: Int, i: Int, sr: Int): DoubleArray
  fun measureArrival(capture: ShortArray, sr: Int, template: DoubleArray, nulls: List<DoubleArray>,
                     expectedFrame: Double): Arrival          // one window
  fun flatRuns(capture: ShortArray, sr: Int): List<IntRange>  // [start, end) frames
  fun half(selfArrival: Int, partnerArrival: Int, role: Char): Int  // A: t_BA − t_AA ; B: t_BB − t_AB
}
data class Arrival(val found: Boolean, val frame: Int, val score: Double, val bar: Double, val nullMax: Double,
                   val windowLo: Int, val windowHi: Int, val strongestFrame: Int, val strongestScore: Double, val why: String?)
```

### 6.1 Constants (identical on server `pop/constants.py`, `dsp_ref.py`, Kotlin `PopConstants`)

| Name | Value | Reason |
| --- | --- | --- |
| `PROTO` | `"pop-v1"` | |
| `SR_MIN, SR_MAX` | 36000, 96000 | 18 kHz band edge must fit |
| `CODE_S` | 0.25 | JBL250 |
| `BAND_HZ` | 2000, 18000 | receiver mask; tune is below |
| `FADE_S` | 0.005 | raised-cosine edges |
| `TARGET_RMS`, `MAX_PEAK` | 0.15, 0.95 | render |
| `PRIMER_S` | 0.3 | silence before the sound starts the output path |
| `LEAD_S` | 0.5 | capture starts at t0 − LEAD_S |
| `CAPTURE_S` | 2.5 | capture length |
| `A_PLAY_S`, `B_PLAY_S` | 0.0, 0.95 | |
| `SEARCH_PRE_S`, `SEARCH_POST_S` | 0.150, 0.250 | |
| `SEGMENT_MARGIN_S` | 0.1 | audio each side of a window's segment |
| `N_NULL` | 64 | |
| `NULL_P` | 1e-4 | |
| `NULL_P_SAFETY` | 3.0 | T = isf(NULL_P / 3) |
| `FLOOR_SCORE` | 0.05 | fixed public floor; field bars for JBL250 sit at 0.07–0.08 |
| `HALF_FRAC` | 0.5 | |
| `HALF_LOOKAHEAD_S` | 0.005 | |
| `FLAT_RUN_MIN_S` | 0.008 | ≥ 8 ms constant run = dropped block |
| `IMPOSSIBLE_CM` | −20 | |
| `NEAR_CM` | 60 | |
| `SPEED_OF_SOUND_CM_S` | 34300 | |
| `SELF_OS_TOL_MS` | 50 | self arrival vs OS timestamp; loose until measured (decision note wants ~1 ms) |
| `TRANSCRIPT_DEADLINE_S` | 20 | after t0 |
| `MAX_ATTEMPTS` | 2 | attempt 0, 1 |

### 6.2 Null codes on the phone

Same family as the real bed (a 0.25 s random-phase multisine on the 4 Hz grid over 2–18 kHz, faded), but from a SHA-256 stream, not PCG64, so Kotlin and Python match bit for bit:

```
seed_i   = sha256("pop-null-v1|" + session_id_hex + "|" + E + "|" + attempt + "|" + i)      # E = emitter role 'A'|'B', i = 0..63, decimal ASCII
n        = round(0.25 · sr);  k_lo = 500;  k_hi = min(4500, n/2 − 1)   (bins on the 4 Hz grid: 2000/4 .. 18000/4)
phases   : words w_j = u32 BE from the byte stream sha256(seed_i ‖ u32be(0)) ‖ sha256(seed_i ‖ u32be(1)) ‖ ...   (8 words per digest)
           φ_k = 2π · w_(k − k_lo) / 2^32   for k = k_lo..k_hi in order
x[t]     = (2/n) · Σ_{k=k_lo..k_hi} cos(2π k t / n + φ_k),   t = 0..n−1        (== numpy irfft of spec[k] = e^{iφ_k})
fade     : r[m] = 0.5·(1 − cos(π (m + 0.5)/F)),  F = max(1, round(0.005·sr));  x[0..F) *= r, x[n−F..n) *= r reversed
```

Scale is irrelevant (scores are normalized). Kotlin computes `x` by inverse FFT (Bluestein for non-power-of-2 `n`), Python by `np.fft.irfft`; parity within 1e-9 relative.

The phone needs 64 nulls for E = self and 64 for E = partner: 128 templates, computed once per attempt (cache).

### 6.3 One window: correlation, bar, arrival

Input: capture `x` (int16 → double `/32768`), template `c` (length L = round(0.25·sr)), nulls `c_i`, expected frame `e`.

1. Window `[w0, w1) = [round(e − 0.150·sr), round(e + 0.250·sr))`, clipped to `[0, len(x))`. Fewer than 3 frames → `found=false, why="window_outside_capture"`.
2. Segment `[a, b) = [max(0, w0 − M), min(len, w1 + L + M))`, `M = round(0.1·sr)`. `nfft` = smallest power of two ≥ `(b − a) + L`.
3. Mask `m[f]` on the rfft grid of `nfft`: 1 for `2000 ≤ f ≤ 18000`, else 0 (`f = bin · sr / nfft`).
4. `X = rfft(x[a:b], nfft) · m`; `xm = irfft(X, nfft)[0 : b−a]` (masked segment, real); `cs` = cumulative sum of `xm²` with `cs[0] = 0`.
5. For each template `c` (real, nulls): `C = rfft(c, nfft) · m`; `‖c‖ = sqrt((|C_0|² + 2·Σ_{1..nfft/2−1}|C_k|² + |C_{nfft/2}|²)/nfft)`; one-sided product `Z_k = 2 · X_k · conj(C_k)` for `k = 0..nfft/2`, `Z_k = 0` above; `corr = ifft(Z)` (complex, length nfft, unnormalized-inverse convention: `ifft` divides by nfft as numpy does); `env[n] = |corr[n]|` for `n ∈ [w0−a, w1−a)`.
6. `score[n] = env[n] / (nx[n] · ‖c‖ + 1e-30)`, `nx[n] = sqrt(max(cs[min(n+L, b−a)] − cs[n], 0))`.
7. Null maxima `s_i = max(score_i over the window)`, i = 0..63. Gumbel MLE on `{s_i}` (§6.4) → `T_g = loc − scale · ln(−ln(1 − p))`, `p = NULL_P / NULL_P_SAFETY`. If the fit fails or is non-finite, `T_g = max(s_i)`. Bar `T = max(T_g, max(s_i), FLOOR_SCORE)`.
8. "First" rule: candidates are `n ∈ [1, len−2]` with `env[n] ≥ env[n−1] && env[n] > env[n+1] && score[n] ≥ T`, in increasing n. Accept the first with `env[n] ≥ HALF_FRAC · max(env[n .. n+look])`, `look = round(0.005·sr)` (clipped to the window). None → `found=false`, `why = "below_bar"` if max score < T else `"no_peak"`.
9. Output frame = `a + (w0 − a) + n` (capture-relative), `score`, `bar = T`, `strongest` = argmax score in the window.

All FFT sizes: correlation at power-of-two `nfft`; templates via §6.2 at arbitrary `n`. One radix-2 complex FFT plus Bluestein is enough.

### 6.4 Gumbel MLE (must match `scipy.stats.gumbel_r.fit` within 1% on T)

Given samples `s_1..s_N`: start `β0 = std(s)·√6/π`, `μ0 = mean(s) − 0.5772156649·β0`. Newton on β with `g(β) = β − mean(s) + Σ s_i e^{−s_i/β} / Σ e^{−s_i/β}` (derivative numerically, step 1e-6·β, or analytic), until `|Δβ| < 1e-10·β` or 200 iterations; then `μ = −β · ln(mean(e^{−s_i/β}))`. `isf(p) = μ − β · ln(−ln(1 − p))`.

### 6.5 Flat-block check

`flatRuns`: runs of ≥ `round(0.008·sr)` consecutive frames where `x[t+1] == x[t]` (int16 exact). Return `[start, end)` where `end − start ≥ min_n`. A round fails (`glitch`) if any run intersects `[min(w0 of both windows), max(w1 of both windows) + L)`. Check runs BEFORE commit (self window) and again after the partner window is known; either hit = `glitch`.

### 6.6 Per-phone procedure and checks (in order)

| # | Step | Failure reason |
| --- | --- | --- |
| 1 | Capture exactly `CAPTURE_FRAMES` frames; `rec_sha256 = sha256(int16 LE bytes)` | `capture_failed` |
| 2 | Self window at `expected_self`; `flatRuns` over it | `glitch` |
| 3 | Self arrival with own bed + 64 nulls(E=self) | `self_not_heard` |
| 4 | `self_os_delta = t_self − expected_self` (frames); reject if `|delta| > SELF_OS_TOL_MS·sr/1000` | `self_timestamp_mismatch` |
| 5 | Commit (§7.2); receive partner bed | (server errors) |
| 6 | Partner window at `expected_partner`; flat runs over union of both windows + L | `glitch` |
| 7 | Partner arrival with partner bed + 64 nulls(E=partner) | `partner_not_heard` |
| 8 | `half = A: t_BA − t_AA ; B: t_BB − t_AB` (int frames, my sr). `own_flight_hint_cm` not computed on the phone (needs both halves). | |
| 9 | Sign transcript (§7.1), submit | |

A phone that fails at any step posts `POST /v1/session/{id}/fail {attempt, reason}` (signed) instead of a transcript. The −20 cm check is server side (needs both halves).

### 6.7 Parity tolerance (Kotlin vs `dsp_ref.py`, same fixture bytes)

| Quantity | Tolerance |
| --- | --- |
| null template samples | rel 1e-9 |
| `score` at any frame | rel 1e-6 |
| null maxima | rel 1e-6 |
| bar `T` | rel 1% (MLE solver differs) |
| arrival frame | exact when both decisions (found/not) match; test fails if decisions differ |
| `half` | exact |
| flat runs | exact |

`dsp_ref.py` vs `fieldanalysis.py` (golden, run by `tools/dsp-fixtures/make_fixtures.py`, not by CI): arrival within ±1 sample on every JBL250 arrival of the 12 field sessions when both find it; bar within 10% (different null families). Report deviations in the fixture file's `notes`.

## 7. Signed transcript

Fixed-length big-endian binary, no length prefixes. Signature: ECDSA P-256, `SHA256withECDSA` over the bytes (i.e. the signed digest is `sha256(bytes)`), raw `r||s` 64 bytes. ZK later: prove knowledge of a signature by an enrolled key over `sha256(transcript)`; every field is at a fixed offset.

### 7.1 Transcript (269 bytes)

| Off | Len | Field | Encoding |
| --- | --- | --- | --- |
| 0 | 4 | magic | `"POPT"` |
| 4 | 1 | version | `0x01` |
| 5 | 1 | role | ASCII `'A'`(0x41) / `'B'`(0x42) |
| 6 | 1 | attempt | u8 |
| 7 | 32 | session_nonce | raw |
| 39 | 65 | pk_self | SEC1 uncompressed |
| 104 | 65 | pk_partner | SEC1 uncompressed |
| 169 | 4 | sample_rate | u32 |
| 173 | 4 | half | i32, frames at `sample_rate` (A: t_BA − t_AA, B: t_BB − t_AB) |
| 177 | 32 | rec_sha256 | sha256 of the capture int16 LE bytes |
| 209 | 8 | play_frame_position | u64, `AudioTimestamp.framePosition` of own playback |
| 217 | 8 | play_nano_time | u64, `AudioTimestamp.nanoTime` |
| 225 | 8 | rec_frame0_nano_time | u64, capture frame 0 in `System.nanoTime()` |
| 233 | 4 | self_os_delta | i32 frames, `t_self − expected_self` |
| 237 | 32 | commit_hash | `sha256(commit bytes)` (§7.2) |

JSON envelope on the wire: `{transcript_b64, sig_b64, meta: {...}}`. `meta` is unsigned diagnostics: `t_self, t_partner, expected_self, expected_partner` (frames), `score_self, bar_self, score_partner, bar_partner, null_max_*`, `ts_source`, `security_level`, `output_latency_ms` (AudioManager), `flat_runs`, `model`. Server stores meta verbatim for debugging; verdict never uses it.

### 7.2 Commitment (71 bytes)

| Off | Len | Field |
| --- | --- | --- |
| 0 | 4 | `"POPC"` |
| 4 | 1 | version `0x01` |
| 5 | 1 | role |
| 6 | 1 | attempt |
| 7 | 32 | session_nonce |
| 39 | 32 | rec_sha256 |

Wire: `POST /v1/session/{id}/commit {commit_b64, sig_b64}`. Server verifies role/attempt/nonce/signature against the sender, stores, releases `partner_bed`. `commit_hash` in the transcript must equal `sha256` of the stored commit bytes and `rec_sha256` must match; else `transcript_mismatch`.

## 8. Result

### 8.1 Server checks (both transcripts of the same attempt)

| Check | Failure |
| --- | --- |
| signature valid for the sender's enrolled key; `pk_self` == that key | `signature_invalid` |
| roles: exactly one A (host) and one B (guest), matching the session | `transcript_mismatch` |
| both `session_nonce` == session's; both `attempt` == current | `transcript_mismatch` |
| A.pk_partner == B.pk_self and B.pk_partner == A.pk_self | `transcript_mismatch` |
| `commit_hash`/`rec_sha256` match the stored commit | `transcript_mismatch` |
| `|self_os_delta| ≤ SELF_OS_TOL_MS·sr/1000` | `self_timestamp_mismatch` |
| `flight = c/2 · (half_A/sr_A − half_B/sr_B)` (seconds → cm) ≥ −20 | `impossible_flight` |

Verdict: `NEAR` iff `−20 < flight_cm < 60`, else `NOT_NEAR`. No gray zone.

### 8.2 Retry rules

| Event at attempt k | Next |
| --- | --- |
| both transcripts valid, flight ≥ 60 | final `NOT_NEAR`, reason `too_far`. Never retry. |
| both valid, −20 < flight < 60 | final `NEAR` |
| any failed-measurement reason (from a phone's `fail`, or server `impossible_flight`, `self_timestamp_mismatch`, `capture_failed`, `timeout` = no transcript by t0 + 20 s) and k == 0 | attempt 1: new bed keys, state back to `confirmed`; phones re-arm (new t0) |
| same, k == 1 | final `NOT_NEAR`, reason = the failure |
| `signature_invalid` / `transcript_mismatch` / auth error | final `NOT_NEAR` with that reason, no retry (a broken client is not a measurement failure) |

Both phones fail → reason = first received.

### 8.3 Reasons and user text

| reason | user-facing |
| --- | --- |
| `too_far` | "Too far apart. Hold the phones side by side." |
| `partner_not_heard` | "Partner not heard. Check volume and try again." |
| `self_not_heard` | "Your own sound was not heard. Check volume and mic." |
| `glitch` | "Recording glitch, trying again." |
| `impossible_flight` | "Measurement failed, trying again." |
| `self_timestamp_mismatch` | "Audio timing off, trying again." |
| `capture_failed` | "Audio capture failed, trying again." |
| `timeout` | "Partner did not finish in time." |
| `signature_invalid` | "Device signature invalid." |
| `transcript_mismatch` | "Session data mismatch." |
| `partner_mismatch` | "Invite does not match this partner." |
| `aborted` | "Session aborted." |

### 8.4 Result record (`GET /v1/session/{id}/result`, also stored as `data/sessions/{id}/result.json`)

```json
{
  "proto": "pop-v1",
  "session_id": "hex32",
  "session_nonce": "hex32",
  "attempt": 0,
  "verdict": "NEAR" | "NOT_NEAR",
  "reason": null | "<reason>",
  "flight_cm": 33.2,
  "t0_ms": 1790000000000,
  "created_at": "iso", "finished_at": "iso",
  "devices": {
    "A": {"device_id", "pubkey": "hex65", "display_name", "model", "attested", "security_level", "sample_rate", "half"},
    "B": { ... }
  },
  "transcripts": {
    "A": {"transcript_b64", "sig_b64", "sha256": "hex of sha256(transcript bytes)"},
    "B": { ... }
  },
  "attempts": [ {"attempt": 0, "outcome": "failed", "reason": "glitch", "by": "B"}, {"attempt": 1, "outcome": "verdict"} ]
}
```

This record (two transcripts + two signatures + enrolled pubkeys) is what ZK/onchain consumes later. Recordings are never part of it.

## 9. HTTP API and state machines

All JSON. Signed = §2.3 headers required. `{id}` = session_id. Errors: `{"error": "<code>", "detail": "..."}`.

| Method | Path | Signed | Request | Response | Errors |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/time` | no | — | `{server_ms}` | |
| GET | `/v1/config` | no | — | constants table §6.1 + `{proto, allow_unattested, gain_db}` | |
| GET | `/v1/enroll/nonce` | no | — | `{nonce, expires_at_ms}` | |
| POST | `/v1/enroll` | no | §2.2 | `{device_id, attested, enrolled_at}` | 400 `enroll_bad_chain`, `enroll_bad_challenge`, `enroll_bad_nonce`, `enroll_key_mismatch` |
| POST | `/v1/session` | yes | `{}` | `{session_id, join_token, expires_at_ms, invite_b64url}` | |
| POST | `/v1/session/{id}/join` | yes | `{join_token}` | session view | 404, 410 `token_expired`, 409 `already_joined`, 400 `self_join` |
| GET | `/v1/session/{id}?after=<seq>&timeout_s=25` | yes | — | session view (long-poll: returns when `seq > after` or timeout) | 404, 403 `not_member` |
| POST | `/v1/session/{id}/confirm` | yes | `{}` | session view | 409 `bad_state` |
| POST | `/v1/session/{id}/arm` | yes | `{attempt, sample_rate, rtt_min_ms}` | `{attempt, sample_rate, play, own_bed}` | 409 `bad_state`, 400 `bad_sample_rate`, 400 `bad_attempt` |
| POST | `/v1/session/{id}/commit` | yes | `{commit_b64, sig_b64}` | `{partner_bed: {pcm_b64, n}}` | 409 `bad_state`, 400 `signature_invalid`, 400 `transcript_mismatch` |
| POST | `/v1/session/{id}/transcript` | yes | `{transcript_b64, sig_b64, meta}` | `{accepted: true, state}` | same |
| POST | `/v1/session/{id}/fail` | yes | `{attempt, reason}` | session view | 400 `bad_reason` |
| POST | `/v1/session/{id}/recording` | yes | multipart `wav` (int16 mono WAV of the capture) + `meta` JSON | `{ok}` | optional; stored at `data/sessions/{id}/recording_{role}_{attempt}.wav`; sha256 must equal the committed `rec_sha256` else 400 |
| POST | `/v1/session/{id}/abort` | yes | `{}` | session view | |
| GET | `/v1/session/{id}/result` | yes | — | §8.4 | 404 `no_result` |

Session view:

```json
{"session_id", "seq": 7, "state": "started", "attempt": 0, "role": "A",
 "nonce": "hex32" | null (before confirmed),
 "self": {"device_id","display_name"},
 "partner": {"device_id","display_name","model","attested","pubkey"} | null,
 "confirmed": {"A": true, "B": false}, "armed": {"A": true, "B": false},
 "committed": {"A": false, "B": false}, "submitted": {"A": false, "B": false},
 "t0_ms": null | 1790000000000,
 "constants": {"a_play_s": 0.0, "b_play_s": 0.95, "lead_s": 0.5, "capture_s": 2.5},
 "result": null | <§8.4>,
 "error": null | "<reason>"}
```

`seq` increments on every state or flag change. Long-poll is the only push mechanism (no SSE/websocket). Recordings upload after the transcript when `config.upload_recordings` is true (default true for the hackathon).

### 9.1 Server session states

```
created ─join─> joined ─confirm×2─> confirmed ─arm×2─> started(t0) ─commit/transcript─> done
   │                                     ▲                                  │
   └──────── abort / token expiry ──> aborted                     failure at attempt 0 ──> confirmed (attempt=1, fresh keys)
```

`done` carries the result. A session older than 10 min without `done` is `aborted` (`timeout`).

### 9.2 Phone state machine (commonMain `PopController`)

| State | Enter | Exit |
| --- | --- | --- |
| `Unenrolled` | first launch | enroll ok → `Idle` |
| `Idle` | | Host tap → `Inviting`; Guest tap → `Scanning` |
| `Inviting` (A) | `POST /session`, show QR + HCE active | poll shows partner → `Confirming` |
| `Scanning` (B) | NFC reader mode + camera | invite decoded → `Joining` → `Confirming` |
| `Confirming` | show partner name/model; user taps Confirm | both confirmed → `Arming` |
| `Arming` | clock sync, `arm`, open audio, fill track | poll `t0_ms` → `Running` |
| `Running` | schedule record start/play/stop by `t0` | capture done → `SelfCheck` |
| `SelfCheck` | steps §6.6 1–4 | ok → `Committing`; fail → `Failing(reason)` |
| `Committing` | `commit`, get partner bed | → `Measuring` |
| `Measuring` | §6.6 6–8 | ok → `Submitting`; fail → `Failing` |
| `Submitting` | sign, `transcript`, optional recording upload | → `WaitingResult` |
| `Failing(reason)` | `fail` | → `WaitingResult` |
| `WaitingResult` | poll | result → `Done`; state back to `confirmed` with attempt+1 → `Arming` (show reason text) |
| `Done` | show verdict + flight_cm + reason | Again → `Idle` |

Any error/abort → `Done` with `aborted`. Mic + speaker are released on leaving `Running`.

## 10. Test plan

### 10.1 Server (`server/tests`, `uv run pytest`)

| Test | What |
| --- | --- |
| `test_jbl250_golden` | `jbl250.generate/template` vs stored `.npy` goldens (produced once from fieldprobes; script `server/tests/golden/make_golden.py` uses the proximity-echo venv). |
| `test_null_codes` | `dsp_ref.null_template` vectors: first 8 samples for `(session "00"*16, 'A', 0, 0, 48000)` pinned as literals; same literals in the Kotlin test. |
| `test_auth` | request signing: good, stale, replay, wrong key. |
| `test_enroll` | synthetic chain built with `cryptography` carrying the attestation extension with the right/wrong challenge; unattested allowed only with env. |
| `test_transcript_codec` | encode/decode 269/71 bytes, offsets, known vector hash. |
| `test_flow_fake_phones` | two in-process fake phones (httpx `TestClient`, software P-256 keys, `POP_ALLOW_UNATTESTED=1`, `dsp_ref` as their DSP) run the whole flow. Captures come from **real fieldtest recordings**: crop `[t0−0.5, t0+2.0)` around a JBL250 round of `recording_A/B.wav`. The field bed belongs to the old seed, so the crop is the room/noise bed and the fake phone adds the session's own rendered play PCM (from `/arm`) and the partner's (fetched by the test harness, not the phone) at the four field-measured arrival frames (`result.json`), amplitude ×0.3. Assert NEAR for 0/30 cm sessions, NOT_NEAR for 100/200, retry on an injected 20 ms zero block in B between the two arrivals (attempt 1, then verdict), `too_far` never retries, swapped roles rejected (`transcript_mismatch`), commit before reveal enforced (partner bed 409 before commit). |
| `test_result_math` | flight from halves at mixed sample rates (48000/44100), −20 rule. |

Field data path is read via env `POP_FIELD_DATA=research/sound-bound/spikes/melody/fieldtest/data/sessions` and the test skips if absent (wav files are gitignored). The injected-PCM captures for CI are ALSO written by `make_fixtures.py` into `server/tests/fixtures/*.json` (same format as §10.2), so CI runs without the wavs.

### 10.2 DSP fixtures (`tools/dsp-fixtures/make_fixtures.py` → `app/composeApp/src/commonTest/resources/dsp/`)

Self-contained JSON, int16 audio as base64, total < 5 MB. Six (session, round) picks: `2dc2eb59 k0` (touch), `b9e4dd4b k0` (30), `b2a5f86d k1` (60, reads 60.0), `d1ee4fb0 k0` (100), `f3ff0ee8 k0` (200), plus `glitch_synth` = `180ca04b k0` with 20 ms of zeros inserted in B between the two arrivals. Each file:

```json
{"name": "b9e4dd4b_k0", "label_cm": 30, "sr": 48000, "session_id_hex": "<32 hex used for null seeds>", "attempt": 0,
 "listeners": {
   "A": {"segment_pcm16_b64": "...", "segment_offset": 0,
         "windows": {"self": {"expected": 1234.0, "template_f32_b64": "..."}, "partner": {"expected": 46800.0, "template_f32_b64": "..."}},
         "expect": {"self": {"found": true, "frame": 1240, "score": 0.332, "bar": 0.0765, "null_max": 0.061},
                    "partner": {...}, "flat_runs": [], "half": 45566}},
   "B": {...}},
 "expect_flight_cm": 26.1, "expect_verdict": "NEAR", "notes": "..."}
```

`segment` = capture crop `[min window lo − 0.1 s, max window hi + 0.25 s + 0.1 s)` per listener (≈ 1.9 s int16 ≈ 0.24 MB b64), templates = the field bed templates (float32 b64, 48 KB each) since Kotlin cannot regenerate a PCG64 bed. Expected values come from `dsp_ref.py` run on the cropped int16 data (not from `fieldanalysis`), so Kotlin parity is exact by construction; `notes` records the `dsp_ref` vs `fieldanalysis` deviation (±1 sample allowed).

### 10.3 Kotlin commonTest

| Test | Tolerance §6.7 |
| --- | --- |
| `NullTemplateTest` | pinned literals + full-vector hash vs Python (`sha256` of the doubles formatted `%.12e`, listed in the fixture) |
| `GumbelTest` | pinned 64 maxima → T within 1% of scipy |
| `ArrivalParityTest` | every fixture window: found/frame/score/bar |
| `FlatRunTest` | glitch fixture: exact runs; clean fixtures: none |
| `HalfAndVerdictTest` | half per listener exact; `flight_cm` via the §8 formula within 0.1 cm; verdict |
| `TranscriptCodecTest` | 269/71-byte layout, known-vector sha256 equals the server test's literal |
| `InviteCodecTest` | 49 bytes round trip, QR string, APDU response framing |

Gradle: `export JAVA_HOME=$(/usr/libexec/java_home -v 21)`; run builds under `research/sound-bound/spikes/zk/tools/heavy.sh <label> ./gradlew ...` (read-only use of that script). `./gradlew :composeApp:testDebugUnitTest` for commonTest, `:composeApp:assembleDebug` for the APK.

### 10.4 Device smoke (manual, before the demo)

Two phones, table, quiet: touch, 30, 100 cm × 3. Log `meta` per transcript (`self_os_delta`, scores, bars, `ts_source`). If `self_os_delta` clusters far from 0 or beyond ±50 ms, raise `SELF_OS_TOL_MS` on both sides and note it.
