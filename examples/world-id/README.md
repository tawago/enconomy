# World ID example

Two different humans met. Each phone proves a World ID to this backend before the measurement. The core then measures the two phones and signs a record, and this backend answers whether two different verified humans were on that NEAR.

An outside developer could build this: it uses only the core's public HTTP routes and its signed presence record. It has its own database and imports nothing from the core. The core stores no human data.

It isn't part of `./demo`, and the core app has no World ID screen. This example has its own copy of the app, see [App](#app). It has never been compiled.

## What it proves

Two different World ID proofs, bound to this nonce and role, by the devices that were NEAR, according to the core's signed record.

## What it doesn't

- **That the two humans were there. A real second human lending their World ID remotely isn't stopped.** World ID proves a human approved it, not where they stand.
- **One human across sessions.** The action is `pop:<session_id>`, per session, so a nullifier limits one human per session. The same two people can meet again, and the same human can be in any number of sessions.
- **Anything without trusting the core.** The core's signature is trusted for the verdict and `attested`. This backend rechecks the transcript hashes and device signatures, not the distance.
- **That the app ran the gate.** A patched app can skip it and the core will measure anyway. This backend still answers `met: false`. It doesn't check order either: a World ID finished after the measurement, by the same device key, still counts.
- **That the core app works with this.** It has no World ID screen. Only the copy in `app/` runs this flow.

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

## App

`app/` is this example's own full copy of the mobile and web app (Android, iOS, web), taken from the core's `app/` at commit `1e80216` and trimmed to the proximity flow plus World ID. There's no SDK and it shares no code with the core.

**This copy has never been compiled or run, and neither have its tests.** It's reference code, kept as a past example. Nobody built it after the edits, so treat it as a careful draft.

The flow:

1. `applicationId` and iOS bundle id are `com.enconomy.pop.worldid`. It enrolls with the core and calibrates by itself, as any core app does.
2. Host creates the core session with `{"early_nonce": true}`, so both phones see the nonce from join on.
3. It doesn't treat `nonce != null` as both confirmed. Confirm waits on the session's `state`.
4. On the Confirm screen, so before Arm, because the iOS app switch can kill audio, both phones run World ID through this backend: `POST /v1/worldid/start`, open `connector_uri` in World App (or show it as a QR code to another phone, the default on iOS and web), then poll `POST /v1/worldid/status`. Requests are signed with the device key enrolled with the core. World App comes back on `enconomy://worldid`, this example's return link and the backend's `WID_RETURN_TO` default. Confirm stays off until both roles are `verified`. This gate is a courtesy: the backend is the real check.
5. The core measures as usual.
6. After NEAR, it takes `presence` from the core's result and sends it to `POST /v1/record`. Both phones do. Records wait in a small queue in Prefs that survives a restart, and retry until a 200. A 4xx drops the record, since a retry can't fix it.
7. The Result screen shows `met`, and says plainly why not when `reason` is set.

Settings: **World ID backend** under Server on Home, or at build time `-Ppop.worldIdUrl=` or `POP_WORLD_ID_URL`. The default is `http://10.0.2.2:8300`, the host from the Android emulator. The core's URL works as in the core app, and `app/README.md` in the core covers build and install.

Removed from the source: ENS, Safe, `ContextGate`, `PopCtx`, the World ID Simulator switch (this backend only takes production), and the core routes the split removed (`/session/{id}/worldid`, `/attestation`, `/safe`, `/relay`, `/device/ens`). `LiveWorldIdTest` went too, it tested those routes. `WorldIdTest` is rewritten for this backend.

Left out on purpose: `app/prover`, `app/zkprove`, built binaries and build output. If anyone ever builds this, they come from the core's `app/`: copy `app/zkprove` to `examples/world-id/app/zkprove`. Without it the Gradle tasks skip the prover and the app runs without on-phone proofs.

Expected to need fixing if someone builds it:

- **Compile errors.** Imports and small type mismatches, most likely in the new `WorldId.kt`, `PopController.kt` and `App.kt`. `WorldIdApi`'s client setup is the least sure part.
- **Web and CORS.** The web app is served by the core, so calls to this backend are cross-origin, and the backend has no CORS setting. Add `CORSMiddleware` with the core's origin, or proxy it.
- **Android.** The Kotlin package and `namespace` stay `com.enconomy.pop`, only `applicationId` changed. The NFC AID is the core app's too, so with both installed the tap can reach the wrong one.
- **iOS.** Paid builds need the core's `POP_IOS_APP_ID` set to `TEAMID.com.enconomy.pop.worldid` for App Attest, and the core takes one value. Xcode's team and signing are per machine, as in the core. World App once aborted on approve on an iPhone X (iOS 16), and the old answer, the simulator, is gone.
- **Session age.** A core session lives 600 s from create, World ID included. A slow World ID step aborts it.
- **Tests.** `LiveServerRunTest` needs a running core, and the fixtures are the core's as of `84f9d71`, so they can go stale.

## Security checks that stayed

| Check | Where |
|---|---|
| Two different humans: the same nullifier for both roles is refused | `tests/test_human.py`: `test_same_human_refused` |
| The signal matches this nonce and role, a proof from elsewhere fails | `tests/test_human.py`: `test_proof_from_elsewhere_fails` |
| A nullifier can't be reused | `tests/test_record.py`: `test_imported_nullifier_refused` |
| Forged or altered record refused, verdict must be NEAR | `tests/test_record.py`: `test_forged_or_altered_record_refused`, `test_far_is_not_met` |
