# World ID example

Two different humans met. Each phone proves a World ID to this backend before the measurement. The core then measures the two phones and signs a record, and this backend answers whether two different verified humans were on that NEAR.

An outside developer could build this: it uses only the core's public HTTP routes and its signed presence record. It has its own database and imports nothing from the core. The core stores no human data.

It isn't part of `./demo`, and the core app has no World ID screen. No app ships here yet, see [What its future app must do](#what-its-future-app-must-do).

The removed Kotlin app code for this feature (`WorldId.kt`, `PopController.kt` and `App.kt` under `app/composeApp/src/commonMain/kotlin/com/enconomy/pop/`) was last in commit `1e80216`.

## What it proves

Two different World ID proofs, bound to this nonce and role, by the devices that were NEAR, according to the core's signed record.

## What it doesn't

- **That the two humans were there. A real second human lending their World ID remotely isn't stopped.** World ID proves a human approved it, not where they stand.
- **One human across sessions.** The action is `pop:<session_id>`, per session, so a nullifier limits one human per session. The same two people can meet again, and the same human can be in any number of sessions.
- **Anything without trusting the core.** The core's signature is trusted for the verdict and `attested`. This backend rechecks the transcript hashes and device signatures, not the distance.
- **That the app ran the gate.** A patched app can skip it and the core will measure anyway. This backend still answers `met: false`. It doesn't check order either: a World ID finished after the measurement, by the same device key, still counts.
- **That the core app works with this.** It has no World ID screen.

## Run

```sh
cp .env.example .env
curl -s "$CORE_URL/v1/config" | jq -r .presence.pubkey     # paste into WID_CORE_PRESENCE_PUBKEY
# WID_RP_ID, WID_APP_ID: from the World ID developer portal. WID_SIGNING_KEY_FILE: the path of the RP key.
(cd sidecar && npm ci && node index.mjs) &
uv sync
uv run --env-file .env uvicorn --factory backend.main:create_app --port 8300
uv run pytest
```

- One uvicorn worker. `WID_CORE_PRESENCE_PUBKEY` is pinned by hand and never fetched at runtime, so a fake core can't vouch for itself.
- Real keys never go in this folder. `.env`, `data/` and `*.key` are gitignored.

Old nullifier rows from before the split, once, optional:

```sh
uv run python -m backend.import_nullifiers <old pop.sqlite> [world-id.sqlite]
```

The source opens read-only and a second run changes nothing. Old rows have the action `pop:<old sid>`, so they can't collide with a new session. It's record-keeping.

## API

**`POST /v1/worldid/start`** and **`POST /v1/worldid/status`** take the same device request:

```json
{"session_nonce": "<64 hex>", "session_id": "<32 hex>", "role": "A", "pubkey": "04...", "ts": 1790000003000, "sig_b64": "..."}
```

`sig_b64` is P-256 (SHA256withECDSA, raw `r||s`) by that key over `wid-device-v1\n` + canonical JSON of the other five fields. `ts` is ms, within 5 minutes of now. There's no device table: the key is whatever was enrolled with the core, and the record checks that later.

- `start` answers `{request_id, connector_uri, expires_at_s, status}`. Open `connector_uri` in World App. The first start for a nonce pins its `session_id`, another is 409 `session_id_mismatch`. The first start for a role pins its key, another is 409 `pubkey_mismatch`.
- `status` does one sidecar poll per call, so the phone polls. It answers `{role, status, error, partner: {status}}`. Steps are `idle, requested, waiting, awaiting, verifying, verified, failed`. After `failed`, start again.
- Refusals while verifying: 409 `same_human`, 409 `nullifier_used`, 400 `human_invalid`, 400 `human_level`.

**`POST /v1/record`** `{body, sig_b64}`, the `presence` block from the core's result. Open route: the core's signature is the auth. Either phone can deliver, and delivering again is fine. A forged or altered record is 401 `bad_record_signature`, one signed but malformed is 400 `bad_record`. Otherwise 200:

```json
{"met": true, "reason": null, "session_id": "...", "session_nonce": "...", "finished_at": "...", "flight_cm": "30.37",
 "trust_tier": {"A": "tee", "B": "tee"}}
```

`met` is true only if all of these hold. `reason` is the first that doesn't:

| Holds | `reason` |
|---|---|
| Verdict is NEAR | `not_near` |
| World ID state exists for both roles of `session_nonce` | `no_world_id` |
| Stored `session_id` equals the record's | `session_id_mismatch` |
| Both roles verified | `role_unverified` |
| The two nullifiers differ | `same_human` |
| Each role's stored key equals `devices[role].pubkey` | `pubkey_mismatch` |

The answer is stored per nonce and carries no nullifiers. A delivery works it out again, so a record that came before World ID finished gets its real answer on the retry.

## What its future app must do

Nothing is built yet. The app:

1. Has its own `applicationId`, enrolls with the core and calibrates by itself, as any core app does.
2. Creates the core session with `early_nonce: true`, so both phones see the nonce before Confirm.
3. Doesn't treat `nonce != null` as both confirmed. With `early_nonce` it no longer means that. Read the session state.
4. Runs World ID on both phones **before Arm**, because the iOS app switch can kill audio. Signs with the device key it enrolled with the core, and waits for `verified` on both roles (`partner.status`). This gate is a courtesy: the backend is the real check.
5. Runs the session through the core as usual.
6. After the result, takes `presence` from `GET /v1/session/{id}/result` and sends it to `POST /v1/record`. Either phone, both is fine, so both should. Retry from a small queue that survives a restart, until a 200.
7. Shows `met`, and says plainly why not when `reason` is set.

## Security checks that stayed

| Check | Where |
|---|---|
| Two different humans: the same nullifier for both roles is refused | `tests/test_human.py`: `test_same_human_refused` |
| The signal matches this nonce and role, a proof from elsewhere fails | `tests/test_human.py`: `test_proof_from_elsewhere_fails` |
| A nullifier can't be reused | `tests/test_record.py`: `test_imported_nullifier_refused` |
| Forged or altered record refused, verdict must be NEAR | `tests/test_record.py`: `test_forged_or_altered_record_refused`, `test_far_is_not_met` |
