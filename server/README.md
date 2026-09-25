# pop server

FastAPI server for proof of presence, pop-v1. The spec is `../docs/pop-contract.md`. It covers health/time/config, device enrollment, signed-request auth, pairing (create, invite, join, confirm, abort), arm/start (T0), commit-then-reveal, signed transcripts, the verdict, retry, the result record and the optional recording upload. See `pop/sessions.py` (state), `pop/verdict.py` (checks and flight) and `pop/dsp_ref.py` (Python reference of the phone DSP).

## Run

```sh
cd server
uv sync
uv run python -m pop                     # listens on 0.0.0.0:8000
# or
uv run uvicorn --factory pop.main:create_app --host 0.0.0.0 --port 8000
```

| Env | Default | What |
|---|---|---|
| `POP_DB` | `data/pop.sqlite` | SQLite file. `data/` is gitignored. |
| `POP_DATA_DIR` | `data/` | `sessions/<id>/result.json` and uploaded `recording_<role>_<attempt>.wav`. |
| `POP_ALLOW_UNATTESTED` | off | `1` accepts `chain: null` (Android) or `app_attest: null` (iOS) at enroll and stores the device as `attested: false`. Use it for emulators, the iOS simulator, a free Apple personal team and fake phones. |
| `POP_IOS_APP_ID` | unset | App Attest appId, `TEAMID.com.enconomy.pop`. Unset = every iOS attestation is refused. |
| `POP_IOS_ROOT_PEM` | Apple root | Path to a PEM that replaces the embedded Apple App Attestation Root CA (tests pass their own root through `Settings`). |
| `POP_GAIN_DB` | `0` | Play gain, reported in `/v1/config`. |
| `POP_UPLOAD_RECORDINGS` | `1` | Reported in `/v1/config`. |
| `POP_HOST`, `POP_PORT` | `0.0.0.0`, `8000` | Only used by `python -m pop`. |

### How phones reach it

- **Same Wi-Fi (LAN).** Get the Mac's IP with `ipconfig getifaddr en0` and set the app base URL to `http://<ip>:8000`. The app allows cleartext HTTP. Every device request is signed, so plain HTTP is OK for the hackathon. Guest Wi-Fi with client isolation blocks this; use cloudflared instead.
- **cloudflared (any network).** Run `cloudflared tunnel --url http://localhost:8000` and set the printed `https://*.trycloudflare.com` URL as the base URL on both phones. The signed path is the request path plus query, not the host, so auth works through the tunnel. Long-poll (`timeout_s` up to 25 s) fits inside Cloudflare's 100 s limit.

Both phones must use the same base URL. The invite does not carry the server URL.

Check it: `curl http://<ip>:8000/health`.

## Tests

```sh
uv run pytest -q
```

| File | Covers |
|---|---|
| `test_public.py` | `/health`, `/v1/time`, `/v1/config`, error shape |
| `test_enroll.py` | synthetic attestation chain (root, intermediate, leaf with KeyDescription): good, wrong challenge, wrong leaf key, broken link, missing extension, leaf-only chain, garbage; reused/expired/unknown nonce; unattested accepted only with the flag; re-enroll; display_name bounds |
| `test_enroll_ios.py` | embedded Apple root self-verifies; App Attest with a self-made root/intermediate (real Apple vectors need a paid team): good (dev and prod aaguid), wrong nonce, other pubkey, tampered credCert nonce, wrong appId, bad aaguid, counter != 0, fmt, credentialId, keyId, foreign intermediate, missing extension, garbage, fake chain vs the real Apple root, no `POP_IOS_APP_ID`; unattested SE key only with the flag; `platform` default and unknown; old sqlite migrates |
| `test_auth.py` | good, missing headers, unknown device, stale (±61 s), replay, wrong key, tampered body, query covered by the signature |
| `test_invite.py` | 49-byte layout, QR form, rejects |
| `test_jbl250.py` | vendored generator vs goldens (`tests/golden/*.f32`) and vs `fieldprobes` itself (read-only import, skipped without `research/`); sample rates 36k..96k; peak limit; bed key per (session, role, attempt) |
| `test_arm_commit.py` | `/v1/time` ping; arm material (own play + own bed only) and `t0 = now + 3 s` once both armed; bad sample rate / attempt / rtt; unauthenticated and non-member refused; partner bed absent before commit, released after (at the committer's rate); `too_early`; commit signature / role / attempt / nonce checks; attempt 1 gets new codes |
| `test_transcript_codec.py` | 269-byte transcript / 71-byte commit layout, offsets, pinned sha256 of a known vector (same literal goes in the Kotlin test) |
| `test_result_math.py` | flight at mixed sample rates, swap flips the sign, -20 / 60 boundaries, self_os tolerance, pinned null-code literals, Gumbel vs scipy, flat runs |
| `test_flow_fake_phones.py` | two fake phones (`tests/sim.py`, software keys, `dsp_ref` as DSP) over HTTP: NEAR at 0/30 cm, NOT_NEAR `too_far` at 100/200 cm with no retry, glitch (20 ms zero block) -> retry -> NEAR, two failures -> final, timeout -> retry, stale transcript/fail after a retry, swapped role (sign flip), relayed partner transcript, tampered bytes, every field check, replay from another session, transcript before commit, impossible flight and self-timestamp retries, `/fail` checks, result access, offline `verify_record` on swapped records, recording upload hash check, and a real field recording as room background (skipped without the wavs) |
| `test_pairing.py` | create + invite decode + host key hint; join; 404 / self_join / bad_token / token_expired / already_joined / not_member; confirm (nonce appears only after both confirm); long-poll wake-up and timeout; abort; 10-min expiry; seed never in a response |

Tests use a fake clock and `SqliteStore(":memory:")`. The fake phones in `tests/phones.py` hold software P-256 keys and sign exactly like the app will.

## Codes and reveal

`seed_hex` never leaves the server. Bed key = `sha256("pop-v1|<seed>|JBL250|<role>|<attempt>|bed")` (`pop/jbl250.py`), so a retry gets fresh beds for both roles. `POST /arm` returns my play PCM and my bed; `POST /commit` (signed 71-byte commitment, only after `t0 + 1.2 s`) returns the partner's bed at my sample rate. No route returns the partner's play PCM.

Goldens: `research/proximity-echo/.venv/bin/python3 server/tests/golden/make_golden.py` rewrites `tests/golden/*.f32` from fieldprobes (raw float32; `*.npy` is gitignored here).

## Attestation: what is and isn't verified

Verified at `POST /v1/enroll`:
- The nonce exists, is unused and unexpired. It is consumed on first use, even if the enroll fails.
- The chain has at least 2 certs, and each cert is signed by the next.
- The leaf public key equals `pubkey`.
- The leaf carries the KeyDescription extension (`1.3.6.1.4.1.11129.2.1.17`), and its `attestationChallenge` equals the nonce.
- `device_id == sha256(pubkey)[:16]`.

`security_level` is taken from `attestationSecurityLevel`. The level the app reports is stored separately, and a mismatch is only logged.

NOT verified: the root pinned to Google's roots (its sha256 is stored as `root_sha256` for later), revocation / RKP, `attestationApplicationId` (package + signing digest), verified-boot state, a minimum security level, and cert validity dates. So a self-made chain passes today. It proves only possession of the key and freshness of the nonce.

### iOS (contract §2.2.1)

`platform: "ios"` takes `app_attest: {key_id, attestation}` instead of `chain`. The App Attest key is not the Secure Enclave signing key; the signing key is bound by `clientDataHash = sha256(nonce || sha256(pubkey65))`, which the app passes to `attestKey`. Verified: `fmt`, x5c chain to the pinned Apple App Attestation Root CA, the credCert nonce extension (`1.2.840.113635.100.8.2`) == `sha256(authData || clientDataHash)`, `sha256(credCert key) == keyId == credentialId`, `rpIdHash == sha256(POP_IOS_APP_ID)`, `signCount == 0`, aaguid `appattestdevelop` / `appattest`. NOT verified: cert validity dates, the receipt, revocation. `key_kind` (`secure_enclave` / `software`) is only reported and becomes `security_level`. Without App Attest (free team, simulator) the app sends `app_attest: null`, which needs `POP_ALLOW_UNATTESTED=1`.

## Notes and choices the contract leaves open

- A wrong `join_token` gets 403 `bad_token`. The contract has no code for it. The real token still works after a wrong guess.
- Join check order: 404, `self_join`, `already_joined`, `bad_token`, `token_expired`. A reused token (session already joined) therefore gets 409 `already_joined`, even from the original guest.
- An expired token moves the session to `aborted` with `error: "timeout"`. So does a live session older than 10 min. Both are checked lazily on access.
- `POST /v1/session` also returns `invite_qr` (`"pop1:" + invite_b64url`). The session view's `self` and `partner` also carry `pubkey`, and `partner` carries `security_level`. All of these are additions to the contract.
- `confirm` is idempotent, and `abort` on a finished session returns the view unchanged.
- The replay cache is in memory, so a restart forgets it. The 60 s ts window still applies.
- Long-poll re-reads the store every 100 ms.

## Transcript, verdict, retry (§7, §8)

`POST /transcript` checks, in order: layout, signature by the sender's enrolled key, `pk_self` = that key, role = the sender's session role, nonce, attempt, `pk_partner` = the partner's enrolled key, `sample_rate` = the armed rate, `commit_hash` = sha256 of the stored commit, `rec_sha256` = the committed one. Any failure is 400 and a final NOT_NEAR (`signature_invalid` / `transcript_mismatch`), never retried. When both are in, `combine()` re-checks the pair (one A one B, same nonce and attempt, crossed keys), then `self_os_delta`, then `flight = c/2 (half_A/sr_A - half_B/sr_B)`.

| Outcome | Next |
|---|---|
| -20 < flight < 60 | done, NEAR |
| flight >= 60 | done, NOT_NEAR `too_far`, no retry |
| flight <= -20, self_os_delta off, a phone `/fail`, no transcript by t0 + 20 s | attempt 0: back to `confirmed`, attempt 1, fresh beds; attempt 1: done, NOT_NEAR with that reason |

`GET /result` returns the §8.4 record (also written to `data/sessions/<id>/result.json`). It adds `commits` and `user_text`; `pop.verdict.verify_record(record)` re-runs every check offline from the record alone.

Choices the contract leaves open (see also the `pop/sessions.py` docstring):
- exactly -20 cm is `impossible_flight` (the check says >= -20 passes, the verdict needs > -20).
- self_os_delta is checked when both transcripts are in, not at submit.
- a signed transcript or fail for an older attempt is 409 `stale_attempt` and changes nothing. A resend of the same transcript is idempotent; a different one is 409 `already_submitted`.
- `/fail` accepts `capture_failed, glitch, self_not_heard, self_timestamp_mismatch, partner_not_heard` (retry) and `partner_mismatch` (final). It works from `confirmed` too (audio failed while arming).
- the session view adds `last_failure {attempt, reason, by, text}`; `error` holds the final reason once done (null for NEAR).
- `/recording` (multipart `wav` + `meta` JSON with `attempt`) needs the WAV's int16 frames to hash to that attempt's committed `rec_sha256`, else 400 `transcript_mismatch`.

`dsp_ref.py` uses Python `round` (half to even) for every rate-derived count; the Kotlin port must use `kotlin.math.round`. Flat runs are the maximal runs of t with x[t+1] == x[t], returned as [first t, last t + 1).
