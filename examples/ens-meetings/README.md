# ENS meetings example

`<label>.enconomy.eth` for phones, and a meeting recorded on chain when two named phones get a NEAR. An outside developer could build this: it uses only the core's public HTTP routes, its device statement and its presence record. It has its own database and imports nothing from the core.

It isn't part of `./demo`, and the current app can't use it: its ENS screen calls core routes that are gone. No app ships here yet, see [What its future app must do](#what-its-future-app-must-do).

## What it proves

Two attested-phone keys that hold names met, according to the core's signed record. That's all a `Met` event says.

## What it doesn't

- **That two people met.** Attestation limits who can claim to real phones, nothing more. It doesn't count humans.
- **That the claimant runs your app.** The core doesn't check `attestationApplicationId`, so any app on a real phone can attest. One phone can also mint many keys, and each key can claim a name. With no daily cap, **the hot key's gas is exposed** to anyone with a real phone. Keep little ETH on it.
- **Anything without trusting the core.** The core's signature is trusted for the verdict, `attested` and the ZK status. This backend rechecks the transcript hashes and device signatures, not the distance or the attestation chains. The record carries the evidence if you want to check those yourself.
- **Revocation, verified boot or app identity.** The core pins Google's roots but checks none of these, see the header of `server/pop/attestation.py`.
- **That imported names were attested under the pin.** Imported rows came from the old table and aren't rechecked, and a meeting only looks at whether both devices hold registered names.
- **Every meeting.** Phones deliver records, the core pushes nothing. A dead phone means no record until a phone retries.

The core's Android attestation pin hasn't been tried on a real phone yet. Until a real enroll passes, treat `attested` on Android as untested.

## Run the backend

```sh
cp .env.example .env
curl -s "$CORE_URL/v1/config" | jq -r .presence.pubkey     # paste into ENS_CORE_PRESENCE_PUBKEY
uv sync
uv run --env-file .env uvicorn --factory backend.main:create_app --port 8100
uv run pytest
```

`ENS_CORE_PRESENCE_PUBKEY` is pinned by hand and never fetched at runtime, so a fake core can't vouch for itself. If the core's key is ever regenerated, copy the new one and restart. Real keys never go in this folder: `ENS_KEY_FILE` points outside it, and `.env` is gitignored.

## API

**`POST /v1/names/claim`** `{device_statement, label, ts, sig_b64}`. `device_statement` is what the core's enroll or `GET /v1/device/statement` returned. `sig_b64` is the device key's signature (SHA256withECDSA, raw `r||s`) over:

```
b"ens-claim-v1\n" + canonical({"device_id": ..., "label": ..., "ts": <unix ms>})
```

`canonical` is the core's: `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=True)`. The tag keeps this apart from the core's `pop-req-v1` requests.

Answers `{label, name, status, tx}`, status `pending`. Checks, in order:

| Check | Refusal |
|---|---|
| Core signature on the statement | 401 `bad_statement` |
| Statement format | 401 `bad_statement` |
| Statement age, at most `ENS_STATEMENT_MAX_AGE_S` | 401 `statement_stale`: fetch a new one |
| `device_id == sha256(pubkey)[:16]` | 401 `bad_statement` |
| Device signature | 401 `auth_bad_signature` |
| `ts` within 60 s | 401 `auth_stale` |
| Not seen before | 401 `auth_replay` |
| Platform is a phone, not web | 403 `not_allowed` |
| `attested` is true | 403 `not_attested` |
| Label is 3-32 of `a-z`, `0-9`, `-` | 400 `bad_label` |
| One label per device | 409 `already_claimed` |
| One device per label | 409 `label_taken` |

A `failed` row can claim again, also with another label: it never reached the chain, so it's no rename.

**`POST /v1/names/read`** `{device_statement, ts, sig_b64}`, signed the same way with `label` null. Same shape as above, status `none` if there's no name. A statement isn't secret, so the signature is what proves the caller.

**`POST /v1/presence`** `{body, sig_b64}`, the `presence` block from the core's session result. Open route: the core's signature is the auth, and one meeting per session bounds the gas. Beyond that signature it redoes `device_id` from each pubkey, each transcript's `sha256` and each device's signature over its transcript. A NEAR needs both halves. Delivering again is fine. A later record for the same session must match in everything except `zk`, otherwise 409. An older `zk` never replaces a newer one.

## On chain at the claim

A claim goes `pending` and wakes one worker thread inside the backend, which sends `register` then `touch` at once and sets `registered` or `failed`. One thread means the shared key has no nonce race within this process. It sleeps until woken, and pending rows are retried at startup after a crash. There is no daily cap.

A label already registered on chain counts as done, with no tx: that's how a crash after the tx recovers. It also means **a label someone registered by hand that isn't in `ens_names` goes to the first claimer**. And a crash between `register` and `touch` leaves the name registered without its `Member` event.

## Import from an old core database

```sh
uv run python -m backend.import_names <old pop.sqlite> [ens.sqlite]
```

Opens the source read-only and copies `ens_names` with status, tx, error and claimed_at unchanged. Run it again and nothing changes. Imported rows have no statement or pubkey. **Imported `pending` rows go on chain when the backend starts**, and those phones aren't rechecked, so look at the warning it prints.

## Meetings

A delivered record goes to the worker, which runs the bridge: a NEAR between two named phones becomes one `record` on `MeetResolver`, and when the signed `zk.status` is `verified` it fetches the core's public ZK bundle, verifies and marks. Status lives in `presence_records`. Details, including when ZK gets marked with no on-chain verify, in [bridge/README.md](bridge/README.md).

## Contracts

`contracts/`, see its README. Never rerun the `ens.sh` bootstrap: a fresh build predicts another address, so it would deploy a new resolver and repoint the name. Addresses come from `contracts/deployments/sepolia.json`.

| Sepolia | Address |
|---|---|
| MeetResolver | `0xfc300a640ccdEFF0e61f7875D55A9Cd22eb51346` |
| UserRegistry | `0x3dC7A13410B3C2B3dA8029BCfA60E358E3AA59B1` |
| PhoneVerifier | `0x5b69C5a7D3e5A56D33809b9B95d02984D4aFa791` |
| PairVerifier | `0xfFA0cf3d79E2a27bC11b9E67eDB979a9b5BE3Fd7` |
| VerifyLog | `0x53D6DB2580466FeE5F07c4Bb7b4c07C41797B996` |

More in [ENS.md](ENS.md), including the live site.

## What its future app must do

Nothing is built yet. The app:

1. Has its own `applicationId` and enrolls by itself with the core. Device keys are per app, so it gets a new key, and old names stay with the old key. Android first. Keep the `device_statement` the enroll returns.
2. Calibrates, as any core app does.
3. Claims the subname right after calibration: ask for a label, sign, `POST /v1/names/claim`. Then `POST /v1/names/read` until it says `registered` or `failed`. On `failed`, offer another claim.
4. Refetches the statement on `statement_stale`, with the signed `GET /v1/device/statement` on the core, then claims again with a new `ts`.
5. Tells the user plainly on `not_attested` and `not_allowed`. Web is never allowed here.
6. Runs a session through the core as usual.
7. Delivers the record after the result: take `presence` from `GET /v1/session/{id}/result` and `POST /v1/presence`. Either phone can do it, both is fine, so both should. Keep a small local queue and retry until accepted, surviving an app restart.
8. Delivers again when ZK finishes. Wait for `zk.pair.status` to settle: a record delivered before the pair proof is marked with no on-chain verify, and it can't be added later, see [bridge/README.md](bridge/README.md).

## Security checks that moved here

| Check | Where |
|---|---|
| Only an attested phone can claim | `tests/test_names.py`: `test_web_and_unattested_refused`, `test_web_is_refused_before_the_label_is_looked_at`, `test_foreign_key_statement_refused`, `test_tampered_statement_refused`, `test_statement_checks`, `test_someone_elses_statement_refused`, `test_signature_covers_label_and_ts` |
| One name per device, one device per name | `tests/test_names.py`: `test_claim_once`, `test_label_taken` |
| This backend holds only its own secret, the Sepolia key, outside the repo | `tests/test_independence.py`: `test_env_example_has_no_keys`, plus `.gitignore` for `.env`, `data/` and `*.sqlite` |

## Design doc corrections

`docs/ens-meetings-design.md` and `docs/pop-contract.md` are gitignored, so they aren't in this branch and this work didn't change them. They need these fixes by hand.

`docs/ens-meetings-design.md`, which was never fully the code. It plans an ENS package inside the core:

- §6, everything under `server/pop/ens/`, `ens_hook` and the `ens` block in the result: not in the core. The backend is here, and it reads presence records.
- §6.2 and §9, `POP_ENS_DAILY_BUDGET_WEI`, `POP_ENS_MAX_CLAIMS_PER_HOUR`, the per-person caps and `status=budget`: **no daily cap, by decision**, and no claim rate cap. Gas exposure is above.
- §6.4 claim precondition "device must exist and be attested": a signed claim plus the core's device statement. There's no device table here.
- §0 and §6.4 meeting gate: code today is NEAR plus both devices holding registered, different names. No consent step and no per-meeting attestation check.
- §6.4 iOS `key_kind == "secure_enclave"`: the core reports `trust_tier` `app_attest`, because the key kind is only self-reported.
- §9 and WP-4a: Google's roots are pinned now, but `attestationApplicationId` isn't checked, so the §9 rule still holds: say "app-signed", not "hardware-attested".
- §5 and §10, `contracts/` paths for `MeetResolver`: `examples/ens-meetings/contracts/`.
- §4 and §10, `bootstrap.py`, `data/ens-state.json`: `contracts/script/ens.sh` and `contracts/deployments/sepolia.json`.

`docs/pop-contract.md`:

- §2.2: enroll also returns `device_statement`, and `GET /v1/device/statement` refetches it.
- §8.4: the result also holds `presence` `{body, sig_b64}`. Its format is in `server/README.md`, "Presence record".
- §9: add the statement route. `GET /v1/config` also publishes `presence`.
