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
| `POP_IOS_APP_ID` | unset | App Attest appId, `TEAMID.<BUNDLE_ID>` (e.g. `ABCDE12345.com.enconomy.pop`; must match the iOS build's `TEAM_ID` and `BUNDLE_ID`). Unset = every iOS attestation is refused. |
| `POP_IOS_ROOT_PEM` | Apple root | Path to a PEM that replaces the embedded Apple App Attestation Root CA (tests pass their own root through `Settings`). |
| `POP_GAIN_DB` | `0` | Play gain, reported in `/v1/config`. |
| `POP_UPLOAD_RECORDINGS` | `1` | Reported in `/v1/config`. |
| `POP_ISSUER_KEY` | unset | SBcred3 issuer private key, P-256: PEM, or 64 hex (the scalar). Wins over the file. |
| `POP_ISSUER_KEY_FILE` | `data/issuer.pem` | Issuer key file (PEM). Created (0600) on first run if missing. Gitignored; never commit it. |
| `POP_ISSUER_AUTOGEN` | `1` | `0` refuses to start without an issuer key instead of generating one. |
| `POP_CRED_TTL_S` | `2592000` | Credential lifetime (30 days, as the spike). |
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
| `test_sbcred3.py` | SBcred3 bytes and signature vs every `fixtures/popt_v2` credential (read-only); enrolling a fixture key with the spike's dev issuer reproduces its 111 bytes; issue + store; v1 enroll without `holder_commit`; bad `holder_commit` (>= p, length, hex); expired and foreign-issuer credentials; key from env hex/PEM, autogen file; `popzk.verify_phone` (read-only import) accepts our issuer when pinned, `issuer_unknown` otherwise, `validAt` mismatch for an expired credential. `POP_ZK_CHECK=1` also runs the real `oa2t_s48` circuit (`oa2zk check` under `tools/heavy.sh`, ~15 s) on a spike witness with a credential this server issued: accepted, and refused when expired or under the dev issuer. |
| `test_invite.py` | 49-byte layout, QR form, rejects |
| `test_jbl250.py` | vendored generator vs goldens (`tests/golden/*.f32`) and vs `fieldprobes` itself (read-only import, skipped without `research/`); sample rates 36k..96k; peak limit; bed key per (session, role, attempt) |
| `test_arm_commit.py` | `/v1/time` ping; arm material (own play + own bed only) and `t0 = now + 3 s` once both armed; bad sample rate / attempt / rtt; unauthenticated and non-member refused; partner bed absent before commit, released after (at the committer's rate); `too_early`; commit signature / role / attempt / nonce checks; attempt 1 gets new codes |
| `test_transcript_codec.py` | 269-byte transcript / 71-byte commit layout, offsets, pinned sha256 of a known vector (same literal goes in the Kotlin test) |
| `test_popt2.py` | POPT v2 (311 B) / POPC v2 layout, pinned vector sha256, rejects (length/version mix, rec_root >= p); Poseidon7 perm/sponge/node/leaf/root vectors, lockstep = scalar; int8 codes and `code_commit`; exact `decide()` ties at -20 / 60 cm (68.6 kHz) and random parity with the pair-circuit inequality; `/v1/config` v2 keys. With `research/` (read-only): codec and Poseidon7 vs the spike, per-rate table vs `oa_rate.params`, every `fixtures/popt_v2` session (12 JBL250 x 48k/mix + sodfar/sodwide) through `check_commit`/`check_transcript`/`combine` with server-derived `code_commit`, rec_root from the dumped trees + sampled leaves (2 full captures; `POP_SLOW=1` all), the app's integer rule (`tests/twin2.py`) finding the signed arrivals |
| `test_flow_v2.py` | fake phones on v2 (`tests/sim2.py`): NEAR with real rec_root, codes on the wire, too far, mixed v1 + v2 pair, bad code_commit / delta final, 50 ms tolerance edge, POPC version vs arm, v1-armed phone sending v2, `popt` validation, non-canonical rec_root, rec_root recording upload |
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

## POPT v2 (option A)

`docs/pop-transcript-v2.md`, behind a per-phone switch; pop-v1 is unchanged when `popt` is absent.

- `POST /arm` takes `"popt": 1 | 2` (default 1). It is pinned for that role and attempt (another value on re-arm = 409). The roles may differ; an option A pair proof needs both at 2 and `sample_rate` in `zk_rates` (44100, 48000).
- v2 arm adds `popt: 2`, `delta` (`DELTA_MS*sr//1000`) and `own_code {cI_b64, cQ_b64, n}`: int8 band-masked bed template + Hilbert pair at the phone's rate, one common scale (`pop/popt2.py`, same math as the spike's `oa_rate.templates`). The commit response adds `partner_code` (same form, the partner's bed at my rate). Float beds are still sent.
- `POST /commit` needs the armed version: POPC v2 = `"POPC" 0x02 role attempt nonce rec_root`, rec_root < p.
- `POST /transcript` v2 (311 B) adds to the v1 checks: version = armed, `rec_root` = committed, `delta` = `DELTA_MS*sr//1000`, `code_commit` = `sha256("pop-code-v2" | own cI | own cQ | partner cI | partner cQ)` of the codes sent. `SELF_OS_TOL_MS` (50, one constant for v1, v2 and the app via `/v1/config`) still bounds `self_os_delta`; the circuit needs <= `delta` (2 ms), so 2..50 ms passes here and can't be proved.
- `decide()` takes the exact `Fraction` flight, so exact -20 / 60 cm ties match `oa2t_pair` (`c*N <= -40*S`, `c*N >= 120*S`).
- `/recording` for a v2 attempt recomputes rec_root (Poseidon7 x^7, depth-4 4-ary tree, `pop/poseidon7.py`, ~2.5 s per 48 kHz capture, in a worker thread).
- `/v1/config` adds `popt_versions, delta_ms, t0_v2, fir_taps, template_bits, leaf, tree_depth, zk_rates` and `popt2_rates` (per rate: `L, B, delta, wpre, wpost, h`, what the app's integer rule needs).
- The result record's `devices[role].popt` and the view's `popt {A, B}` say which version each side used. `verify_record` re-checks v2 records except `code_commit` (needs the seed).

Poseidon7 params (`pop/p7params/params_t{5,16}.json`) are copied from `research/sound-bound/spikes/zk/optionA-v2/poseidon7/`; the code is a port of `p7.py` + `rectree.py` (no runtime import from research/).

## SBcred3 credential (option A, ZK readiness)

Optional at enroll. Send `holder_commit` (64 hex, a P-256 base-field element < p; the app keeps the 31-byte holder secret and sends `Poseidon7.sponge16(6, [secret])`). After the attestation checks pass the server signs

```
cred = "SBcred3" || X || Y || expiry u64 BE (unix s) || holder_commit (32 BE)      111 bytes, X||Y without 0x04
sig  = ECDSA P-256 over SHA-256(cred), raw r||s
```

and adds `"credential": {"format": "SBcred3", "cred_b64", "sig_b64", "expiry", "issuer_pubkey"}` to the enroll response. The layout is the spike's (`research/sound-bound/spikes/zk/optionA-v2/build_fixtures_popt2.py` `cred3`, circuit `gen_popt2.py`). It is stored on the device row (`holder_commit`, `cred`, `cred_sig`, `cred_expiry`). Without `holder_commit` the enroll is plain pop-v1. `GET /v1/config` publishes the issuer under `issuer` (`pubkey` SEC1 hex, `pub_x`, `pub_y`, `cred_ttl_s`); the verifier pins it as the circuit's public `issuerX/issuerY`.

What it proves: the circuit checks the issuer signature and `validAt <= expiry` (`pop/issuer.py` `check` is the same check in plain Python). The per-phone circuits don't open `holder_commit`; it is signed but only used by the `_nf` variant. A credential means "this key was enrolled here with a passing attestation", not "a distinct person".
