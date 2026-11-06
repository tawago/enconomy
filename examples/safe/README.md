# Safe example

A 2-of-4 Safe on Sepolia that only spends when its two phone owners got a NEAR from the core. An outside developer could build this: it uses only the core's public HTTP routes and its signed presence record. It has its own database and imports nothing from the core.

It isn't part of `./demo`, and the core app has no Safe screen. This example has its own copy of the app in `app/`, see [App](#app). It has never been compiled.

## What it proves

Two device keys that registered as this Safe's owners were near each other, according to the core's signed record, and both signed this exact transaction. The record is bound to the transaction: its context holds the `safeTxHash`, and that goes into the session nonce.

The attestation format is unchanged (`pop-safe-v2`), so the deployed guard needs no redeploy.

## What it doesn't

- **That two people were there. One person holding both owners' phones can spend.** The attestation uses a fixed `pair_tag` and proves no humans. World ID is out of this flow.
- **Anything without trusting the core.** The core's signature is trusted for the verdict and `attested`. This backend rechecks the transcript hashes and device signatures, not the distance or the attestation chains. It reads `attested` only from the record.
- **That the claimant runs your app.** The core doesn't check `attestationApplicationId`. The core's Android pin hasn't been tried on a real phone yet, so treat `attested` on Android as untested.
- **Delivery.** Phones deliver records, the core pushes nothing. A dead phone means no send until a phone retries. The attestation runs out `SAFE_ATT_TTL_S` after the record's `finished_at`.

Unattested iPhones and web devices can't spend, and neither can an Android that fails the pin. There's no override.

## Run

```sh
cp .env.example .env
curl -s "$CORE_URL/v1/config" | jq -r .presence.pubkey     # paste into SAFE_CORE_PRESENCE_PUBKEY
# SAFE_ATTEST_KEY_FILE: the path of the existing key the guard pins, server/data/attest-demo.pem in the main checkout
(cd relayer && npm ci)
uv sync
uv run --env-file .env uvicorn --factory backend.main:create_app --port 8200
uv run pytest
```

- `SAFE_CORE_PRESENCE_PUBKEY` is pinned by hand and never fetched at runtime, so a fake core can't vouch for itself.
- `SAFE_ATTEST_KEY_FILE` is never generated here. Point at the file, don't copy or print it. Another key means `BadAttestation` on chain. `GET /v1/config` `attest.qx/qy` must equal the Safe's `ISSUER_X/Y`. The backend won't start if this key is the core's presence key.
- Real keys never go in this folder. `.env`, `data/` and `*.pem` are gitignored.

## API

All keyed by `ctx_hash`, the `safeTxHash`. That makes them content-addressed: a stranger can't overwrite someone's spend.

**`POST /v1/spends`** `{chain_id, safe, safe_tx}`. `safe_tx` has the 10 keys `to, value, data, operation, safe_tx_gas, base_gas, gas_price, gas_token, refund_receiver, nonce`. Answers `{ctx_hash, what}`, where `what` is what the allowlist found. The allowlist takes a native transfer or an ERC-20 `transfer` of a listed token, and refuses the rest with 400 `context_refused`.

**`GET /v1/spends/{ctx_hash}`** the stored spend, so the guest phone can check it. The core doesn't carry `safe_tx`.

**`POST /v1/spends/{ctx_hash}/owner-sig`** `{pubkey, sig}`. P-256 over `"pop-safe-owner-v1" || ctx_hash` (SHA256withECDSA), `sig` is lowercase `0x` + `r||s`. Stored per pubkey.

**`POST /v1/spends/{ctx_hash}/presence`** `{body, sig_b64}`, the `presence` block from the core's result. Open route: the core's signature is the auth. Either phone can deliver, and delivering again is fine: it returns the same attestation and retries a send that didn't succeed. Answers `{session_id, ctx_hash, att, relay}`. Checks, in order:

| Check | Refusal |
|---|---|
| Core signature | 401 `bad_record_signature` |
| Record format, transcripts, device signatures | 400 `bad_record` |
| Verdict is NEAR | 403 `not_near` |
| Spend is registered | 404 `no_spend` |
| Record context is this spend, stored `safe_tx` hashes to `ctx_hash` | 403 `context_mismatch` |
| `chain_id == SAFE_CHAIN_ID` | 403 `bad_chain` |
| `attested` is true for both devices in the record | 403 `unattested_device` |
| Allowlist, run again | 400 `context_refused` |
| Owner sigs stored for both record devices | 409 `owner_sigs_missing` |
| `finished_at + SAFE_ATT_TTL_S` not passed | 403 `expired` |

**`GET /v1/spends/{ctx_hash}/relay`** `{status, session_id, result}` of the latest job, or `{status: "none"}`. Status is `pending` or whatever `relay.mjs` printed: `success`, `reverted`, `skipped`, `error`.

**`GET /v1/config`** `{chain_id, attest, owner_msg_tag, tokens}`.

## Sending

One worker thread in the backend runs `relay.mjs` per job, so the gas key sends serially. It sleeps until a record arrives, and pending jobs rerun at startup. `relay.mjs` is idempotent through `data/relay-out/<sid>.json`. It uses the attestation, or on a Noir guard fetches the core's public `GET /v1/session/{sid}/zk/bundle`.

`relay.mjs` has no test on chain right now: its fixture and dry run went with the move, and the backend tests fake it.

## Contracts

`contracts/`, see [its README](contracts/README.md). Deployed addresses didn't change.

| Sepolia | Address |
|---|---|
| PopSafeGuard | `0x1e0AD6528e6769508A241b78b73A6F9b1342bb3B` |
| PopAttestationVerifier | `0xD9E2F407424a7422E195d034ECc4fC932120d96F` |
| PopSafeSetup | `0x3d4e549F13CCee540884481b35Fd1CA42A9E0707` |
| P256OwnerFactory | `0x99565991Ec5414Ee2d3A2fA48Ab4d92efBd2466e` |
| Demo Safe, test phone keys | `0x1399D5F9B91B92EF8220E9328743Ac5F370Ed6d4` |

**Existing Safes won't match a new app.** Device keys are per `applicationId`, so a new app's phones get new keys, and a Safe that registered the old ones reverts with `UnknownDevice`. Create a new Safe for the new keys.

## App

`app/` is a full copy of the mobile and web app, Android, iOS and Kotlin/Wasm, from commit `1e80216`. It's trimmed to the proximity flow plus this spend, with the core's current session API. Application id and bundle id are `com.enconomy.pop.safe`. The Kotlin package stays `com.enconomy.pop`. It's reference code: **nobody has compiled or run this copy, not once.** There's no SDK under it and none is planned.

What it does:

1. Enrolls with the core and calibrates as any core app does. The Safe screen holds the backend URL and the Safe. Both phones save the same two once. A guest refuses a session for any other Safe.
2. Host: builds the `safe_tx`, a native transfer or a listed token's `transfer`, runs the allowlist on the phone, then `POST /v1/spends` and checks the answer against its own hash.
3. Host: creates the core session with the plain context `{chain_id, consumer: <safe, lowercase>, ctx_hash}`.
4. Guest: joins, takes `ctx_hash` from the session's context, then `GET /v1/spends/{ctx_hash}`. The core doesn't carry `safe_tx`.
5. Guest: recomputes the `safeTxHash` and runs the allowlist on the phone, and refuses the session if either fails. The allowlist in `chain/Allowlist.kt` is a port of `allowlist()` in `backend/safe_tx.py`, with its own token table, so the backend's `what` is never what's shown.
6. Confirm shows what the transaction does: for a token transfer the token, amount, recipient and token contract. It also says a spend doesn't prove two different humans.
7. At Confirm each phone signs and sends `owner-sig` to this backend. Once both confirmed, each recomputes the PopCtx nonce before any audio.
8. Runs the session through the core as usual.
9. After a NEAR, each phone takes `presence` from `GET /v1/session/{id}/result`, unchanged, and sends it to `POST /v1/spends/{ctx_hash}/presence`. It retries on `owner_sigs_missing`, a 5xx or no network, and keeps what's pending in Prefs, so a restart picks it up. Any other refusal is final and shown. `unattested_device` says plainly this phone can't spend.
10. Shows the status from `GET /v1/spends/{ctx_hash}/relay`.

Calls for the spend go only to this backend (`SafeBackend.kt`, unsigned, its own URL). The app doesn't call any core Safe route, there are none left.

**Left out:** `app/prover`, `app/zkprove` and every built binary. They come from the core's `app/`, copy them to `examples/safe/app/` if you ever build this. Without them the app builds without on-phone proofs (`ProverLib.available = false`), as the core's does. A spend doesn't need a phone proof when the guard takes the attestation.

### If someone compiles it

Expect to fix:

- **Compile errors from the trim.** Hand-edited with no compiler: `PopController.kt`, `App.kt`, `PopApi.kt`, `SafeBackend.kt` and `chain/`. Look for missing or unused imports, and types around the new `spend` and `safe` state. The tests in `commonTest/.../chain/` have never run either, though their hash and nonce vectors are copied from checked ones.
- **Gradle and Xcode versions.** As they stood at `1e80216`. JDK 21 for Gradle. The Xcode project has never been opened at this path.
- **Reaching the backend.** The default URL `http://10.0.2.2:8200` only works from the Android emulator. Real phones need the LAN address on the Safe screen and uvicorn with `--host 0.0.0.0`.
- **Web and CORS.** The backend has no CORS middleware, so a page on another origin can't call it. Web devices are unattested and can't spend anyway, they end at `unattested_device`.
- **iOS App Attest.** The core's `POP_IOS_APP_ID` must become `TEAMID.com.enconomy.pop.safe`. It holds one app id, so a core can't serve both this and the core app attested.
- **Android, next to the core app on one phone.** Both claim the same NFC AID `F0454E434F504F50`, so a tap may reach the wrong app. Install one, or change the AID in both this app's `apduservice.xml` and `Invite.kt` or `Pairing.android.kt`, wherever the reader sends it.
- **Paths.** `scripts/build_web.sh` writes to `app/build/web/`, and it no longer takes the repo's heavy-job lock, so on a small machine wrap it yourself. The generators under `commonTest/resources/zk/tools/` still assume the core's layout. `app/README.md` below its first lines describes the core.
- **Keys.** Device keys are per application id, so this app needs a new Safe, as above.

## Security checks that stayed

| Check | Where |
|---|---|
| Allowlist refuses a bad transaction, even with a good NEAR | `tests/test_presence.py`: `test_registration_refuses_a_bad_tx`, `test_good_near_does_not_sign_a_bad_tx` |
| Forged or altered record refused | `tests/test_presence.py`: `test_forged_record_refused`, `test_altered_record_refused` |
| NEAR, this `safeTxHash`, attested per the record | `tests/test_presence.py`: `test_not_near_refused`, `test_wrong_ctx_hash_refused`, `test_attested_false_refused` |
| Digest agrees with the Solidity | `tests/test_safe_tx.py`: `test_digest_matches_solidity` |
