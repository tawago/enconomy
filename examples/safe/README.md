# Safe example

A 2-of-4 Safe on Sepolia that only spends when its two phone owners got a NEAR from the core. An outside developer could build this: it uses only the core's public HTTP routes and its signed presence record. It has its own database and imports nothing from the core.

It isn't part of `./demo`, and the current app can't use it: its Safe screen calls core routes that are gone, and its `ContextGate` still needs the old `kind` field. No app ships here yet, see [What its future app must do](#what-its-future-app-must-do).

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

## What its future app must do

Nothing is built yet. The app:

1. Has its own `applicationId`, enrolls with the core and calibrates as any core app does.
2. Host: `POST /v1/spends`, gets `ctx_hash`. Guest: `GET /v1/spends/{ctx_hash}` with the hash from the host.
3. On both phones: recompute the `safeTxHash` from `safe_tx`, and refuse if it differs.
4. On both phones: **run the allowlist itself before Confirm**, and **show what the transaction does**, not just `to` and an ETH amount. A token `approve` reads as 0 ETH.
5. Creates the core session with the plain context `{chain_id, consumer: <safe, lowercase>, ctx_hash}`.
6. At Confirm, each phone signs and sends `owner-sig` to this backend.
7. Runs the session through the core as usual.
8. After the result, takes `presence` from `GET /v1/session/{id}/result` and sends it to `POST /v1/spends/{ctx_hash}/presence`. Either phone, both is fine, so both should. Retry until accepted, surviving an app restart. Then read `/relay`.
9. Says plainly on `unattested_device` that this phone can't spend.

## Security checks that stayed

| Check | Where |
|---|---|
| Allowlist refuses a bad transaction, even with a good NEAR | `tests/test_presence.py`: `test_registration_refuses_a_bad_tx`, `test_good_near_does_not_sign_a_bad_tx` |
| Forged or altered record refused | `tests/test_presence.py`: `test_forged_record_refused`, `test_altered_record_refused` |
| NEAR, this `safeTxHash`, attested per the record | `tests/test_presence.py`: `test_not_near_refused`, `test_wrong_ctx_hash_refused`, `test_attested_false_refused` |
| Digest agrees with the Solidity | `tests/test_safe_tx.py`: `test_digest_matches_solidity` |
