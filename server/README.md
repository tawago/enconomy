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
cd server && POP_PORT=8001 uv run python -m pop          # .env: World ID ids, POP_TEST_KINDS=1, POP_WORLDID_SANDBOX=1, POP_ALLOW_UNATTESTED=1
cloudflared tunnel --config ~/.cloudflared/enconomy-pop.yml run enconomy-pop   # pop.enconomy.dev -> localhost:8001
```

- The World ID IDKit sidecar must also be running: `cd server/idkit-sidecar && npm ci && node index.mjs` (listens on 127.0.0.1:8787, `POP_WORLDID_SIDECAR`). Without it World ID start answers 503 `worldid_unavailable`; check `/health` → `worldid.sidecar_ok`.
- `POP_WORLDID_SANDBOX=1` lets a phone use the World ID Simulator in `test` sessions; without it that phone gets 403 `sandbox_not_allowed`.
- `POP_TEST_KINDS=1` is required for the app's "Host with World ID (test)" button; without it session create answers 400 `bad_kind`.
- The apps are built with `-Ppop.serverUrl=https://pop.enconomy.dev` (Android) / `POP_SERVER_URL` in `iosApp/Configuration/Local.xcconfig`. A server URL saved in the app wins over the built-in one: Server → Reset to default.

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
| `POP_ZK_VERIFIER` | `~/.enconomy/zk/pinned/bin/bb` | Barretenberg `bb` v5.0.0-nightly.20260522 (pinned; must match the vk and the onchain verifier). The server runs `bb verify -t evm` on every proof against its own public vector. Missing = proof routes answer 503 `zk_unavailable`. |
| `POP_ZK_PROVER` | `~/.enconomy/zk/android/target/release/zkprove` | Host build of `app/zkprove` (ACVM witness + UltraHonk prove). Used by delegated proving (`POST /v1/session/{id}/proof/delegate`). |
| `POP_ZK_DIR` | team build + pinned dirs | Circuit artifacts served at `/v1/zk/keys/`: `oaN_s48.json` (circuit), `oaN_s48.vk`, `bn254_g1_2p20.dat` (CRS). Served only when size and sha256 match the pins in `pop/zk.py`. |
| `POP_ZK_WRAP` | unset | Command prefix for `bb` / `zkprove`, e.g. a memory-limit wrapper on an 8 GB Mac. |
| `POP_HOST`, `POP_PORT` | `0.0.0.0`, `8000` | Only used by `python -m pop`. |
| `POP_WORLDID_APP_ID`, `POP_WORLDID_RP_ID` | unset | Portal app id and `rp_…`. RP unset = World ID off: a create with a `context` answers 503 `worldid_unavailable`. |
| `POP_WORLDID_SIGNING_KEY_FILE` | `data/worldid-rp.key` | RP signer (secp256k1 hex, 0600, gitignored). `POP_WORLDID_SIGNING_KEY` (hex) wins over the file. |
| `POP_WORLDID_SIDECAR` | `http://127.0.0.1:8787` | IDKit sidecar (`idkit-sidecar/`). |
| `POP_WORLDID_RETURN_TO` | `enconomy://worldid` | `return_to` of every request. |
| `POP_WORLDID_PORTAL` | `https://developer.world.org` | Portal base for `/api/v4/verify/{rp_id}` and `/api/v4/rp-status/{rp_id}`. |
| `POP_WORLDID_POLL_S` | `1.5` | Sidecar poll interval. |
| `POP_WORLDID_ALLOW_LEGACY` | `0` | Accept `identifier:"orb"` v3 proofs. Keep 0. |
| `POP_WORLDID_FAKE` | `0` | Fake World ID (tests, live app tests). Refused (exit 2) unless `POP_TEST_KINDS=1`. Stores `environment:"fake"`. |
| `POP_WORLDID_SANDBOX` | `0` | Allow `POST /v1/session/{sid}/worldid/start` with `{"env":"sandbox"}`: IDKit request with environment `staging`, `connector_uri` = World ID Simulator link (`https://simulator.worldcoin.org/?connect_url=…`). Polled like production; on confirm the nullifier comes from the simulator proof (else `sha256("pop-mock-v1"‖device_id‖session_id)`), no Portal verify, `environment:"sandbox"`. Context-less or `test`-kind sessions only, else 403 `sandbox_not_allowed`. The other role stays production; the nullifier table is per env. |
| `POP_TEST_KINDS` | `0` | Enables `context.kind == "test"`. |
| `POP_CHAIN_ID` | `11155111` | The only accepted `context.chain_id` (Ethereum Sepolia). |
| `POP_ATTEST_KEY_FILE` | `data/attest.pem` | Chain attester, P-256 PEM (not the issuer key). Loaded if present, else created 0600. A Safe pins its qx/qy (`/v1/config` `attest`): back it up, never regenerate. |
| `POP_ATT_TTL_S` | `900` | Attestation `expiry = finished_s + TTL`. |
| `POP_UNATTESTED_ALLOW` | empty | Comma list of device_ids that may be unattested and still get a chain attestation (the free-team iPhone). |

`python -m pop` also reads `server/.env` (gitignored; real env vars win). Run **one** uvicorn worker: World ID state is read-modify-write on the session doc and relies on a single event loop.

### How phones reach it

- **Same Wi-Fi (LAN).** Get the Mac's IP with `ipconfig getifaddr en0` and set the app base URL to `http://<ip>:8000`. The app allows cleartext HTTP. Every device request is signed, so plain HTTP is OK for the hackathon. Guest Wi-Fi with client isolation blocks this; use cloudflared instead.
- **cloudflared (any network).** Run `cloudflared tunnel --url http://localhost:8000` and set the printed `https://*.trycloudflare.com` URL as the base URL on both phones. The signed path is the request path plus query, not the host, so auth works through the tunnel. Long-poll (`timeout_s` up to 25 s) fits inside Cloudflare's 100 s limit.

Both phones must use the same base URL. The invite does not carry the server URL.

Check it: `curl http://<ip>:8000/health`.

## World ID gate

Spec: `docs/worldid/01-shared-worldid-presence.md` §6, §7.2, §9, §10. Code: `pop/human.py` (verify pipeline, nullifier table `wid_nullifiers`, per-role state machine, sidecar polls), `pop/worldid_rp.py` (rp_context signer, pure Python port of the worldid-spike signer, pinned to the §6.3 vectors).

A session created with a `context` (or `policy: {human: "worldid"}`) needs a verified Proof of Human from **two different humans** before `arm` (else 409 `human_missing`). Per role, after the guest joined:

| route | what |
|---|---|
| `POST /v1/session/{sid}/worldid/start` (signed, member) | `{request_id, connector_uri, expires_at_s, status}`. One request per role (action `pop:<sid>`, signal `0x` + nonce + role byte). Reused if under 240 s old, else re-signed. 409 `not_joined`, `already_verified`, `bad_state` (no World ID policy, or the session is done/aborted: a failed run needs a new session); 503 `worldid_unavailable` (no RP/key, sidecar down) |
| `GET /v1/session/{sid}/worldid?timeout_s=` (signed, member, ≤ 25 s) | `{role, status, error, partner:{status}, pair_tag}` (+ `connector_uri` while pending). Returns on the next status change |

Status per role: `idle → requested → waiting → awaiting → verifying → verified`, or `failed` with `error` = `same_human` (409 in 01 §6.9), `human_invalid`, `human_level`, `human_expired` (300 s), `user_rejected` / other IDKit error, `worldid_unavailable` (sidecar lost the request). `start` again after `failed` gives a new request, same action. Verify pins `identifier == proof_of_human`, `issuer_schema_id == 1`, the action, a nonce we issued to that role, recomputes and overwrites `signal_hash`, reserves the nullifier (same role = idempotent, other role = `same_human`), persists the raw result, then calls the Portal (3 retries on 5xx/network; requires `success` and `environment == "production"`). A Portal reject releases the nullifier. The view shows `human: {A:{status,error?}, B:…, pair_tag}`; the result record carries full per-role results (proofs) and `pair_tag`. `/v1/config` has `worldid` and `chain`; `/health` has `worldid: {enabled, fake, sidecar_ok, rp_status}`.

Real run (two terminals):

```sh
cd server/idkit-sidecar && npm ci && node index.mjs          # 127.0.0.1:8787, /health -> {"ok":true,"idkit":"4.2.4"}
cd server && uv run python -m pop                             # with POP_WORLDID_APP_ID/RP_ID in server/.env, key in data/worldid-rp.key
```

Fake mode (no Portal, no bridge, no humans; never a production-tagged result):

```sh
node server/idkit-sidecar/fake.mjs            # FAKE_POLLS=2, FAKE_SAME_HUMAN=1 (both roles one nullifier), FAKE_REJECT=1 (user_rejected)
cd server && POP_DATA_DIR=/tmp/pop-live POP_DB=/tmp/pop-live/pop.sqlite POP_ISSUER_KEY_FILE=/tmp/pop-live/issuer.pem \
  POP_ALLOW_UNATTESTED=1 POP_TEST_KINDS=1 POP_WORLDID_FAKE=1 POP_WORLDID_APP_ID=app_test POP_WORLDID_RP_ID=rp_0000000000000001 \
  POP_WORLDID_SIGNING_KEY_FILE=/tmp/pop-live/worldid-rp.key POP_PORT=8765 uv run python -m pop
```

In fake mode the RP key file is generated if missing, and the log says `*** FAKE WORLD ID: TEST IDENTITIES, NO REAL HUMANS ***`.

Not built (cut, 01 §0.5): the laptop IDKit page routes (`/human/context`, `POST /human`), staging eth_call, ENS fixed actions.

## SAFE: safe-tx consumer + chain attestation

`context.kind == "safe-tx"` is always on (`pop/consumers/safe_tx.py`): the 10-key `safe_tx` object is parsed strictly, the allowlist refuses delegatecall, gas/refund fields, Safe self-calls, value+data and anything but a native transfer or an ERC-20 `transfer` of a listed token (Sepolia: USDC `0x1c7d…7238`), and `ctx_hash` must equal the recomputed `safeTxHash` on `POP_CHAIN_ID` for the Safe `consumer`. The session nonce is PopCtx over that `ctx_hash`.

- `POST /v1/session/{sid}/safe/owner-sig` (member) `{"sig":"0x"+r||s}`: the phone's P256Owner signature over `"pop-safe-owner-v1" || safeTxHash`, checked against the caller's device key. 409 `not_safe_tx` / `too_late`, 400 `bad_owner_sig`.
- `GET /v1/session/{sid}/attestation` (public, by sid): after NEAR, two verified **production** World ID humans (`fake`/`staging`/`sandbox` → `nonprod_humans`), attested or allow-listed devices and the right chain, signs `pop-safe-v2` once and caches it. `att.tail_hex` is the 172 B `POP2` tail `PopAttestationVerifier` reads; `safe.owner_sigs` is only filled when `att` is. The relayer (`../relayer`) frames it for `PopSafeGuard`: `ownerSigs || tail || 000000ac || "POPV"`.

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
| `test_zk.py` | option A proofs: public vector == the spike's `popt2_*.public.json` (4 fixtures); the real verifier (`popprover` host build, spike vk, a real `oa2t_s48` proof of fixture 180ca04b_48k A under `data/zk/test/`, skipped when missing) accepts it and refuses another salt (halfCommit), another validAt, another issuer, a corrupted proof, a wrong vk pin; upload endpoint with a fake verifier: before the verdict, both roles verified (48k + 44.1k), idempotent resend / 409, wrong salt then fixed, wrong issuer in the proof, credential from another issuer, expired credential, wrong circuit, bad meta/attempt, no credential, NOT_NEAR, v1 role, verifier missing (503); key download: manifest, sha256 header, Range resume, 416, names |
| `test_popt2.py` | POPT v2 (311 B) / POPC v2 layout, pinned vector sha256, rejects (length/version mix, rec_root >= p); Poseidon7 perm/sponge/node/leaf/root vectors, lockstep = scalar; int8 codes and `code_commit`; exact `decide()` ties at -20 / 60 cm (68.6 kHz) and random parity with the pair-circuit inequality; `/v1/config` v2 keys. With `research/` (read-only): codec and Poseidon7 vs the spike, per-rate table vs `oa_rate.params`, every `fixtures/popt_v2` session (12 JBL250 x 48k/mix + sodfar/sodwide) through `check_commit`/`check_transcript`/`combine` with server-derived `code_commit`, rec_root from the dumped trees + sampled leaves (2 full captures; `POP_SLOW=1` all), the app's integer rule (`tests/twin2.py`) finding the signed arrivals |
| `test_flow_v2.py` | fake phones on v2 (`tests/sim2.py`): NEAR with real rec_root, codes on the wire, too far, mixed v1 + v2 pair, bad code_commit / delta final, 50 ms tolerance edge, POPC version vs arm, v1-armed phone sending v2, `popt` validation, non-canonical rec_root, rec_root recording upload |
| `test_result_math.py` | flight at mixed sample rates, swap flips the sign, -20 / 60 boundaries, self_os tolerance, pinned null-code literals, Gumbel vs scipy, flat runs |
| `test_flow_fake_phones.py` | two fake phones (`tests/sim.py`, software keys, `dsp_ref` as DSP) over HTTP: NEAR at 0/30 cm, NOT_NEAR `too_far` at 100/200 cm with no retry, glitch (20 ms zero block) -> retry -> NEAR, two failures -> final, timeout -> retry, stale transcript/fail after a retry, swapped role (sign flip), relayed partner transcript, tampered bytes, every field check, replay from another session, transcript before commit, impossible flight and self-timestamp retries, `/fail` checks, result access, offline `verify_record` on swapped records, recording upload hash check, and a real field recording as room background (skipped without the wavs) |
| `test_worldid.py` | rp_context vectors (§6.3), nonce is a field element, pairTag vectors; fake-mode happy path (sidecar request body, reuse < 240 s, `human_missing` arm gate, statuses, pair_tag, `already_verified`); sim2 fake phones with a context + World ID -> NEAR, record has humans + pair_tag; `same_human` then retry with another human; same proof again = idempotent, A's nullifier for B = `same_human`; proof replayed into another session; bad signal / action / nonce / two responses / schema 128 / `orb` -> `human_invalid` / `human_level`; `user_rejected`; expiry (240 s re-sign, 300 s `human_expired`, restart); `not_joined`, no-policy and aborted sessions refused, non-member 403; sidecar down 503; no key 503; fake needs `POP_TEST_KINDS`; Portal path: signal overwrite, 503×2 then ok, 400 releases the nullifier, wrong environment, staging result; concurrent verifies + confirm |
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
