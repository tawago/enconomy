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

Configuration: copy `.env.example` to `.env` and fill it in (`python -m pop` reads it; real env vars win).

### Demo server (ETHGlobal Tokyo)

The demo runs on the laptop on port 8001 and is published at **https://pop.enconomy.dev** through a Cloudflare named tunnel:

```sh
cd server && POP_PORT=8001 uv run python -m pop          # .env: POP_ALLOW_UNATTESTED=1
cloudflared tunnel --config ~/.cloudflared/enconomy-pop.yml run enconomy-pop   # pop.enconomy.dev -> localhost:8001
```

- The apps are built with `-Ppop.serverUrl=https://pop.enconomy.dev` (Android) / `POP_SERVER_URL` in `iosApp/Configuration/Local.xcconfig`. A server URL saved in the app wins over the built-in one: Server → Reset to default.

| Env | Default | What |
|---|---|---|
| `POP_DB` | `data/pop.sqlite` | SQLite file. `data/` is gitignored. |
| `POP_DATA_DIR` | `data/` | `sessions/<id>/result.json` and uploaded `recording_<role>_<attempt>.wav`. |
| `POP_ALLOW_UNATTESTED` | off | `1` accepts `chain: null` (Android) or `app_attest: null` (iOS) at enroll and stores the device as `attested: false`. Use it for emulators, the iOS simulator, a free Apple personal team and fake phones. |
| `POP_IOS_APP_ID` | unset | App Attest appId, `TEAMID.<BUNDLE_ID>` (e.g. `ABCDE12345.com.enconomy.pop`; must match the iOS build's `TEAM_ID` and `BUNDLE_ID`). Unset = every iOS attestation is refused. |
| `POP_IOS_ROOT_PEM` | Apple root | Path to a PEM that replaces the embedded Apple App Attestation Root CA (tests pass their own root through `Settings`). |
| `POP_ANDROID_ROOT_PEM` | Google roots | Path to a PEM whose certs' public keys replace the pinned Google attestation roots (tests pass their own pins through `Settings`). |
| `POP_GAIN_DB` | `0` | Play gain, reported in `/v1/config`. |
| `POP_UPLOAD_RECORDINGS` | `1` | Reported in `/v1/config`. |
| `POP_ISSUER_KEY` | unset | SBcred3 issuer private key, P-256: PEM, or 64 hex (the scalar). Wins over the file. |
| `POP_ISSUER_KEY_FILE` | `data/issuer.pem` | Issuer key file (PEM). Created (0600) on first run if missing. Gitignored; never commit it. |
| `POP_ISSUER_AUTOGEN` | `1` | `0` refuses to start without an issuer key instead of generating one. |
| `POP_CRED_TTL_S` | `2592000` | Credential lifetime (30 days, as the spike). |
| `POP_ZK_VERIFIER` | `~/.enconomy/zk/pinned/bin/bb` | Barretenberg `bb` v5.0.0-nightly.20260522 (pinned; must match the vk and the onchain verifier). The server runs `bb verify -t evm` on every proof against its own public vector. Missing = proof routes answer 503 `zk_unavailable`. |
| `POP_ZK_PROVER` | `~/.enconomy/zk/android/target/release/zkprove` | Host build of `app/zkprove` (ACVM witness + UltraHonk prove). Used by delegated proving (`POST /v1/session/{id}/proof/delegate`). |
| `POP_ZK_DIR` | team build + pinned dirs | Circuit artifacts served at `/v1/zk/keys/`: `oaN_s48.json` (circuit), `oaN_s48.vk`, `bn254_g1_2p20.dat` (CRS). Served only when size and sha256 match the pins in `pop/zk.py`. |
| `POP_ZK_WRAP` | unset | Command prefix for `bb` / `zkprove`, e.g. a memory-limit wrapper on an 8 GB Mac. |
| `POP_HOST`, `POP_PORT` | `0.0.0.0`, `8000` | Only used by `python -m pop`. |
| `POP_CHAIN_ID` | `11155111` | The only accepted `context.chain_id` (Ethereum Sepolia). |
| `POP_PRESENCE_KEY_FILE` | `data/presence.pem` | Signs device statements and presence records, P-256 PEM. Loaded if present, else created 0600. The server refuses to start if it is the issuer key. Outside parties pin the public key (`/v1/config` `presence`): back it up, never regenerate. |
| `POP_ALLOW_WEB` | `0` | `1` accepts `platform: "web"` at enroll (the browser build, `app/README.md` "Web"): software P-256 key, `key_kind` / `security_level` `software`, `attested: false`, no chain / app_attest. `POP_ALLOW_UNATTESTED=1` also lets web in. |
| `POP_WEB_DIR` | unset | Directory with the web build (`app/scripts/build_web.sh` fills `server/web-app/`, gitignored), served at `/app/` after every API route (`.wasm` as `application/wasm`). Relative paths are from `server/`. Refused (exit 2) if it is missing or inside `server/data`. Same origin as the API, so no CORS. |
| `POP_CORS_ORIGINS` | empty | Comma list of origins allowed to call the API from a browser (e.g. `http://localhost:8080` for `wasmJsBrowserDevelopmentRun`, `https://ens.enconomy.dev` for the Workers-hosted app). Methods GET/POST/OPTIONS; headers `X-Pop-Device`, `X-Pop-Ts`, `X-Pop-Sig`, `Content-Type`, `Range`; exposes `Content-Range`, `Accept-Ranges`. Off by default. |

`python -m pop` also reads `server/.env` (gitignored; real env vars win). Run **one** uvicorn worker: sessions are read-modify-write on the session doc and the replay cache is in memory.

Web app on the same origin (`https://pop.enconomy.dev/app/` through the existing tunnel):

```sh
app/scripts/build_web.sh                 # -> server/web-app/
cd server && POP_ALLOW_WEB=1 POP_WEB_DIR=web-app uv run python -m pop
```

### How phones reach it

- **Same Wi-Fi (LAN).** Get the Mac's IP with `ipconfig getifaddr en0` and set the app base URL to `http://<ip>:8000`. The app allows cleartext HTTP. Every device request is signed, so plain HTTP is OK for the hackathon. Guest Wi-Fi with client isolation blocks this; use cloudflared instead.
- **cloudflared (any network).** Run `cloudflared tunnel --url http://localhost:8000` and set the printed `https://*.trycloudflare.com` URL as the base URL on both phones. The signed path is the request path plus query, not the host, so auth works through the tunnel. Long-poll (`timeout_s` up to 25 s) fits inside Cloudflare's 100 s limit.

Both phones must use the same base URL. The invite does not carry the server URL.

Check it: `curl http://<ip>:8000/health`.

## Plain context

A session can carry `context = {"chain_id", "consumer", "ctx_hash"}`, exactly those keys, anything else is 400 `bad_context`. `chain_id` must be `POP_CHAIN_ID`. The session nonce is PopCtx over it (`pop/popctx.py`), and it lands in the signed presence record as it is. The core doesn't check what `ctx_hash` means: that's up to whoever reads the record. The Safe spend built on this moved to `examples/safe`.

`POST /v1/session` also takes `early_nonce: true`: members see the nonce from create and join instead of from `confirmed` on, so a service can bind to it before Arm. World ID does that in `examples/world-id`. A non-bool is 400 `bad_request`. Unknown keys are ignored.

## Tests

```sh
uv run pytest -q
```

| File | Covers |
|---|---|
| `test_public.py` | `/health`, `/v1/time`, `/v1/config`, error shape |
| `test_enroll.py` | synthetic attestation chain (root, intermediate, leaf with KeyDescription): good, wrong challenge, wrong leaf key, broken link, missing extension, leaf-only chain, garbage; unknown root, Google pins refusing the test chain, forged child under a real leaf, non-CA intermediate, software level, old rows no longer attested; reused/expired/unknown nonce; unattested accepted only with the flag; re-enroll; display_name bounds |
| `test_enroll_ios.py` | embedded Apple root self-verifies; App Attest with a self-made root/intermediate (real Apple vectors need a paid team): good (dev and prod aaguid), wrong nonce, other pubkey, tampered credCert nonce, wrong appId, bad aaguid, counter != 0, fmt, credentialId, keyId, foreign intermediate, missing extension, garbage, fake chain vs the real Apple root, no `POP_IOS_APP_ID`; unattested SE key only with the flag; `platform` default and unknown; old sqlite migrates |
| `test_auth.py` | good, missing headers, unknown device, stale (±61 s), replay, wrong key, tampered body, query covered by the signature |
| `test_sbcred3.py` | SBcred3 bytes and signature vs every `fixtures/popt_v2` credential (read-only); enrolling a fixture key with the spike's dev issuer reproduces its 111 bytes; issue + store; v1 enroll without `holder_commit`; bad `holder_commit` (>= p, length, hex); expired and foreign-issuer credentials; key from env hex/PEM, autogen file; `popzk.verify_phone` (read-only import) accepts our issuer when pinned, `issuer_unknown` otherwise, `validAt` mismatch for an expired credential. `POP_ZK_CHECK=1` also runs the real `oa2t_s48` circuit (`oa2zk check` under `tools/heavy.sh`, ~15 s) on a spike witness with a credential this server issued: accepted, and refused when expired or under the dev issuer. |
| `test_invite.py` | 49-byte layout, QR form, rejects |
| `test_jbl250.py` | vendored generator vs goldens (`tests/golden/*.f32`) and vs `fieldprobes` itself (read-only import, skipped without `research/`); sample rates 36k..96k; peak limit; bed key per (session, role, attempt) |
| `test_arm_commit.py` | `/v1/time` ping; arm material (own play + own bed only) and `t0 = now + 3 s` once both armed; bad sample rate / attempt / rtt; unauthenticated and non-member refused; partner bed absent before commit, released after (at the committer's rate); `too_early`; commit signature / role / attempt / nonce checks; attempt 1 gets new codes |
| `test_transcript_codec.py` | 269-byte transcript / 71-byte commit layout, offsets, pinned sha256 of a known vector (same literal goes in the Kotlin test) |
| `test_zk.py` | option A proofs: public vector == the spike's `popt2_*.public.json` (4 fixtures); the real verifier (`popprover` host build, spike vk, a real `oa2t_s48` proof of fixture 180ca04b_48k A under `data/zk/test/`, skipped when missing) accepts it and refuses another salt (halfCommit), another validAt, another issuer, a corrupted proof, a wrong vk pin; upload endpoint with a fake verifier: before the verdict, both roles verified (48k + 44.1k), idempotent resend / 409, wrong salt then fixed, wrong issuer in the proof, credential from another issuer, expired credential, wrong circuit, bad meta/attempt, no credential, NOT_NEAR, v1 role, verifier missing (503); key download: manifest, sha256 header, Range resume, 416, names |
| `test_popt2.py` | POPT v2 (311 B) / POPC v2 layout, pinned vector sha256, rejects (length/version mix, rec_root >= p); Poseidon7 perm/sponge/node/leaf/root vectors, lockstep = scalar; int8 codes and `code_commit`; exact `decide()` ties at -20 / 60 cm (68.6 kHz) and random parity with the pair-circuit inequality; `/v1/config` v2 keys. With `research/` (read-only): codec and Poseidon7 vs the spike, per-rate table vs `oa_rate.params`, every `fixtures/popt_v2` session (12 JBL250 x 48k/mix + sodfar/sodwide) through `check_commit`/`check_transcript`/`combine` with server-derived `code_commit`, rec_root from the dumped trees + sampled leaves (2 full captures; `POP_SLOW=1` all), the app's integer rule (`tests/twin2.py`) finding the signed arrivals |
| `test_flow_v2.py` | fake phones on v2 (`tests/sim2.py`): NEAR with real rec_root, codes on the wire, too far, mixed v1 + v2 pair, bad code_commit / delta final, 50 ms tolerance edge, POPC version vs arm, v1-armed phone sending v2, `popt` validation, non-canonical rec_root, rec_root recording upload |
| `test_result_math.py` | flight at mixed sample rates, swap flips the sign, -20 / 60 boundaries, self_os tolerance, pinned null-code literals, Gumbel vs scipy, flat runs |
| `test_flow_fake_phones.py` | two fake phones (`tests/sim.py`, software keys, `dsp_ref` as DSP) over HTTP: NEAR at 0/30 cm, NOT_NEAR `too_far` at 100/200 cm with no retry, glitch (20 ms zero block) -> retry -> NEAR, two failures -> final, timeout -> retry, stale transcript/fail after a retry, swapped role (sign flip), relayed partner transcript, tampered bytes, every field check, replay from another session, transcript before commit, impossible flight and self-timestamp retries, `/fail` checks, result access, offline `verify_record` on swapped records, recording upload hash check, and a real field recording as room background (skipped without the wavs) |
| `test_presence.py` | presence key, canonical bytes, device statement; presence record from real flows: verify, tamper, stable across GET, members only, evidence, late ZK signing, re-enroll, failed and aborted sessions, the test vector |
| `test_safe_removed.py` | Safe routes and config blocks are gone; a plain context session lands its context in the signed record; an extra context key is refused |
| `test_worldid_removed.py` | World ID routes and config blocks are gone; no `policy`, `human` or `pair_tag` in create, view or result; a session arms and finishes with no World ID, also when an old client sends `policy` |
| `test_pairing.py` | create + invite decode + host key hint; join; 404 / self_join / bad_token / token_expired / already_joined / not_member; confirm (nonce appears only after both confirm); long-poll wake-up and timeout; abort; 10-min expiry; seed never in a response |

Tests use a fake clock and `SqliteStore(":memory:")`. The fake phones in `tests/phones.py` hold software P-256 keys and sign exactly like the app will.

## Codes and reveal

`seed_hex` never leaves the server. Bed key = `sha256("pop-v1|<seed>|JBL250|<role>|<attempt>|bed")` (`pop/jbl250.py`), so a retry gets fresh beds for both roles. `POST /arm` returns my play PCM and my bed; `POST /commit` (signed 71-byte commitment, only after `t0 + 1.2 s`) returns the partner's bed at my sample rate. No route returns the partner's play PCM.

Goldens: `research/proximity-echo/.venv/bin/python3 server/tests/golden/make_golden.py` rewrites `tests/golden/*.f32` from fieldprobes (raw float32; `*.npy` is gitignored here).

## Attestation: what is and isn't verified

Verified at `POST /v1/enroll`:
- The nonce exists, is unused and unexpired. It is consumed on first use, even if the enroll fails.
- The chain has at least 2 certs, and each cert is signed by the next.
- The last cert's public key is a pinned Google attestation root (sha256 of SubjectPublicKeyInfo, see `pop/attestation.py`).
- Every cert above the leaf has BasicConstraints `ca=true` and no KeyDescription. The leaf key is app-controlled, so otherwise a real phone could sign a forged child under its own leaf.
- The leaf public key equals `pubkey`.
- The leaf carries the KeyDescription extension (`1.3.6.1.4.1.11129.2.1.17`), `attestationSecurityLevel` is `tee` or `strongbox`, and `attestationChallenge` equals the nonce.
- `device_id == sha256(pubkey)[:16]`.

`security_level` is taken from `attestationSecurityLevel`. The level the app reports is stored separately, and a mismatch is only logged.

A chain that fails any of these is a 400, also with `POP_ALLOW_UNATTESTED=1`, which only opens the `chain: null` path. So an emulator or non-Google device that sends its own chain is refused, and has to send none. Rows from before the pin may still say `attested=1`. `attestation.device_attested(row, roots)` rechecks a stored chain under the pins, except the challenge, whose nonce isn't kept.

NOT verified: revocation / RKP, `attestationApplicationId` (package + signing digest), so any app on a real phone can attest, verified-boot state, and cert validity dates (Google's first root cert expired 2026-05-24, but its key is still a live anchor). No real phone chain has run against the pins yet: there is no recorded chain in `tests/fixtures`.

### iOS (contract §2.2.1)

`platform: "ios"` takes `app_attest: {key_id, attestation}` instead of `chain`. The App Attest key is not the Secure Enclave signing key; the signing key is bound by `clientDataHash = sha256(nonce || sha256(pubkey65))`, which the app passes to `attestKey`. Verified: `fmt`, x5c chain to the pinned Apple App Attestation Root CA, the credCert nonce extension (`1.2.840.113635.100.8.2`) == `sha256(authData || clientDataHash)`, `sha256(credCert key) == keyId == credentialId`, `rpIdHash == sha256(POP_IOS_APP_ID)`, `signCount == 0`, aaguid `appattestdevelop` / `appattest`. NOT verified: cert validity dates, the receipt, revocation. `key_kind` (`secure_enclave` / `software`) is only reported and becomes `security_level`. Without App Attest (free team, simulator) the app sends `app_attest: null`, which needs `POP_ALLOW_UNATTESTED=1`.

## Device statement (`pop/presence.py`)

The core's signed word about one device, for a service with no device table of its own. `POST /v1/enroll` returns it as `device_statement`; `GET /v1/device/statement` (signed request) returns a fresh one. Shape: `{"body": {...}, "sig_b64": "..."}`.

Body: `format` (`pop-device-statement-v1`), `device_id`, `pubkey` (hex65), `attested`, `platform`, `trust_tier`, `issued_at_ms`.

`attested` is rechecked against the pinned roots on every statement, so an old row from before the Android pin says false. `trust_tier`:

| Device | `trust_tier` |
|---|---|
| Android, attested | its attested level, `strongbox` or `tee` |
| iOS, attested | `app_attest` (App Attest binds the key; the key kind is only reported) |
| Web | `software` |
| Anything else unattested | `unattested`, whatever level it reported |

To verify: take the P-256 key from `/v1/config` `presence.pubkey` once and pin it, don't fetch it at runtime. Check SHA256withECDSA, raw `r||s` base64, over `b"pop-device-statement-v1\n" + canonical(body)`. Then check `device_id == sha256(pubkey)[:16]` as hex and that `issued_at_ms` is fresh enough for you.

`canonical(body)` is `json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)` as ASCII bytes. Values are strings, ints, bools, null, lists and objects only; a float raises. Keys sort by code point. Tags differ per format, so a statement can't pass as a presence record.

The signature means this core saw that key and its attestation evidence. It doesn't say who holds the phone; see "Attestation" above for what the evidence doesn't cover.

## Presence record (`pop/presence.py`)

The core's signed word that two devices did, or didn't, end up near each other in one session. It is `presence` in the result, `{"body": {...}, "sig_b64": "..."}`, delivered by the member-only `GET /v1/session/{sid}/result` (the view's `result` carries the same). Whoever needs it, a phone hands over; the core pushes nothing.

Body:

| Field | Value |
|---|---|
| `format` | `pop-presence-v1` |
| `session_nonce`, `session_id`, `attempt`, `t0_ms` | hex, hex, int, int or null (the final attempt) |
| `context`, `not_before` | the session's context or null, unix seconds |
| `verdict`, `reason` | `NEAR` / `NOT_NEAR`, null or the reason |
| `flight_cm` | string with two decimals like `"30.37"`, or null. Never a float |
| `finished_at` | ISO 8601 UTC |
| `transcripts` | per role `{transcript_b64, sig_b64, sha256}`; `sig_b64` is the device's signature over the transcript bytes |
| `devices` | per role `{device_id, pubkey, attested, platform, security_level, trust_tier, key_kind, chain_pem, root_sha256, attest_key_id}` |
| `zk` | same as the result's `zk` block (no salts) |

No display name: it isn't this record's business.

To verify: pin `/v1/config` `presence.pubkey` once, don't fetch it at runtime. Check SHA256withECDSA, raw `r||s` base64, over `b"pop-presence-v1\n" + canonical(body)`, with `canonical` as under "Device statement". Then, if you don't want to take the core's word, redo the rest yourself: `sha256(pubkey)[:16] == device_id`, the transcript's `sha256`, each device's signature over its transcript, and the certificate chain. `tests/fixtures/presence_vector.json` has a throwaway key, a NEAR record from a real flow, the statement format and both canonical byte strings (`uv run python -m tests.make_presence_vector` rebuilds it). Signatures are randomized, so verify them rather than compare them.

What the signature means: this core ran the session, checked both transcripts and reached this verdict, and it held this evidence for these devices at the end of the session. It doesn't say who held the phones. `security_level` is self-reported unless `attested`; read `trust_tier` (table under "Device statement"). `attested` is rechecked against the pinned roots when the record is made. `chain_pem` and `root_sha256` are null for an unattested or web device. On iOS they are the App Attest certificates and `attest_key_id` is the App Attest key id; on Android `attest_key_id` is null.

Rules:

- A record exists for every result. So verdicts, rejected transcripts and final failures all get one with whatever they have: `transcripts` holds only the transcripts accepted, and `flight_cm` and `t0_ms` can be null. A rejected transcript is never in it.
- An aborted session, expired ones included, has no result and no record (`/result` 404 `no_result`). A result from before this feature stays without one.
- The body is fixed when the session finishes. Devices are as they were then, so a later re-enroll changes nothing. Only `zk` changes as proofs come in, and each change gets a new signature; all other fields stay byte-identical. So the same session can have several valid records: take the one with the most advanced `zk`. Between changes, repeated GETs return the same bytes.
- `chain_pem` lets a session partner see your attestation chain, as they could already see your key.

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

## Enrollment calibration (`pop/calibration.py`)

Optional at enroll: `"calibration": {"cal_us", "sample_rate", "route", "backend", "samples_us"?}` plus `cal_sig_b64` = device-key signature (raw r||s) over `"pop-cal-v1\n<nonce hex>\n<cal_us>\n<sample_rate>\n<route>\n<backend>"`. The app measures its audio-check self offset `CAL_N` = 5 times, takes the median in µs, rejects a spread > 1 ms or a median outside −2..50 ms, and clamps −2..0 ms to 0 (`from_samples`; `samples_us`, when sent, must reproduce `cal_us`). `POST /v1/device/calibration {"calibration": {...}}` (signed request) replaces it ("Recalibrate"). Stored on the device row (`cal_us`, `cal_sample_rate`, `cal_route`, `cal_backend`, `cal_at`, `cal_samples`), returned as `calibration` in the enroll response, `self.cal_us` / `self.calibration` / `partner.cal_us` in the session view, and `devices[role].cal_us` in the result record (snapshotted at arm). The plaintext self check is `|self_os_delta − cal_frames| ≤ SELF_OS_TOL_MS` (exact: `|d·1e6 − cal_us·sr| ≤ 50·1000·sr`); no calibration = `cal_us` 0 = the old rule. SBcred3 and every circuit input are unchanged.

## Option A proofs (after NEAR)

Per role, once the session is `done` with NEAR, for the final attempt, POPT v2 at 48 / 44.1 kHz, from a device that holds an SBcred3:

```
POST /v1/session/{sid}/proof          signed like every device call; multipart
  meta  = {"attempt": 0, "circuit": "oa2t_s48" | "oa2t_s44", "salt": "<decimal or 0x-hex, < 2^248>"}
  proof = bincode R1CSSNARK (app/prover output, ~1.6 MB)
-> 200 {"status": "verified", "role", "zk": <record zk block>}
-> 400 transcript_mismatch | issuer_unknown | credential_expired | circuit_unknown | proof_invalid | bad_request | bad_attempt
-> 409 bad_state (no NEAR yet, v1 role, no circuit at that rate) | no_credential | already_submitted
-> 503 zk_unavailable (verifier binary or vk not configured; nothing recorded)
```

The server builds the whole public vector itself (`pop/zk.py`, same order and reason codes as the spike's `verifier/popzk.py` `verify_phone`): `halfCommit = Poseidon7.sponge16(8, [nonceHi, nonceLo, attempt, roleB, sr, half, salt, X_self, X_partner])` from the signed transcript and the uploaded salt, nonce/attempt/role, `code_commit` and the four int8 codes it sent, its issuer key, `sr`, and `validAt = t0_ms // 1000` of the attempt (view `zk_valid_at`, record `zk.valid_at`; the app proves with that value). Before the SNARK it checks the device's SBcred3 in plain Python (issuer signature, `validAt <= expiry`, key = transcript key). Then `popprover verify <vk> <proof> <expected.json>` must accept and match every value; the first mismatching index gives the reason (0 halfCommit, nonce/attempt/role/codes -> `transcript_mismatch`, issuer -> `issuer_unknown`, sr/validAt -> `transcript_mismatch`). The vk file must hash to the pin.

A verified proof is final (same bytes again = 200, others = 409); a rejected one can be replaced. The result record gains `zk {valid_at, status: none|partial|verified|rejected, A, B}` (per role: status, reason, circuit, proof_sha256, half_commit; not the salt), `result.json` is rewritten, and the proof is kept as `sessions/<id>/proof_<role>_<attempt>.bin`. The pair proof (`oa2t_pair`) is not made here yet.

Proving keys: `GET /v1/zk/keys` lists what is in `POP_ZK_KEYS` (`circuit, sample_rate, url, size, sha256, vk_sha256`); `GET /v1/zk/keys/<circuit>.pk.zst` serves the file with `Range` (206 / 416) and `X-Pop-Sha256`. Public, no auth (the pk is public; soundness rests on the vk pin). `GET /v1/config` adds `zk {circuits, vk_sha256, keys, verifier}`.

Test proof (once, gitignored): `research/sound-bound/spikes/zk/tools/heavy.sh s7-prove ../app/prover/target/release/popprover prove <spike keys>/oa2t_s48.pk <spike inputs>/popt2_180ca04b_48k_A.input.json data/zk/test/popt2_180ca04b_48k_A.proof`.
