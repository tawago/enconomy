# ENS meetings example

`<label>.enconomy.eth` for phones, and a meeting recorded on chain when two named phones get a NEAR. An outside developer could build this: it uses only the core's public HTTP routes, its device statement and its presence record. It has its own database and imports nothing from the core.

## Run the backend

```sh
cp .env.example .env     # set ENS_CORE_PRESENCE_PUBKEY: presence.pubkey from the core's GET /v1/config
uv sync
uv run --env-file .env uvicorn --factory backend.main:create_app --port 8100
uv run pytest
```

`ENS_CORE_PRESENCE_PUBKEY` is pinned by hand and never fetched at runtime, so a fake core can't vouch for itself. Real keys never go in this folder: `ENS_KEY_FILE` points outside it.

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

`contracts/`, see its README. Addresses come from `contracts/deployments/sepolia.json`. Never rerun the `ens.sh` bootstrap.
