# WVP onboarding example

An admin gives someone `bob.blob.eth` in person. The admin taps approve, the person's laptop and the admin's phone beep, and only then does the name get created. An outside developer could build this: the backend uses only the core's signed presence record and its published format. It has its own database and imports nothing from the core.

It isn't part of `./demo`. It needs a small change in the core's web app, see [The beep](#the-beep).

**This has never run end to end.** See [Fake or untested](#fake-or-untested).

## What it proves

The core says the admin's registered phone was NEAR another device, in a session bound to this exact name and address. The admin had approved that same name and address on the admin page before the record was accepted.

After that, login doesn't change. Bob's wallet approves a browser as usual and the site reads the name's address at each login. A site can add `--org blob.eth` to refuse names from anywhere else. The admin can later repoint or clear the name on the admin page, see [Names on the admin page](#names-on-the-admin-page), and that's the off switch.

## What it doesn't

- **Anything the site can see.** The site never sees the beep. It only sees that a name exists under `blob.eth`, so it trusts whoever holds that admin key.
- **Anything without trusting this backend and the core.** The core's signature is trusted for the verdict. This backend rechecks the transcript hashes and device signatures, not the distance.
- **Who was at the other end.** The record shows the admin's phone and some other device. The other device is never tied to the wallet. Whoever beeps, the name still goes to the address the admin approved.
- **That Bob controls the address.** The joiner page only asks the wallet for its address, and nothing is signed. Anyone can request a name for any address, so the admin has to check the address in front of Bob. Control is only shown at Bob's first login.
- **Strong keys.** The admin key sits on this backend as a hot key, wherever `subname.mjs` loads it from. The laptop's web key is a software key, and a web device is never attested. The phone's key is pinned by id, and this backend doesn't read `attested`.
- **A safe admin page.** One shared passcode from the environment, sent in the clear if you serve it over plain http. That one passcode also repoints and clears real names on the devnet, and there's no other auth and no rate limit on guessing it. It's fine for a demo, not for anything that matters. `POST /v1/requests` is open and has no rate limit.
- **Freshness.** A record has no expiry here. An unspent NEAR for an approved request still counts later.

## Run it

One laptop and one Pixel. The laptop is Bob and the backend, the Pixel is the admin. The Pixel keeps the core app it already has: it joins as a guest, and that path didn't change.

**1. The core, with the new web app.** `build_web.sh` replaces `server/web-app/` with `rsync --delete`, so don't run it under a core that's serving someone. `POP_DELIVER_ORIGIN` is the one place this web app will send a record. It must be the origin of `ONBOARD_PUBLIC_URL`. Port 8001 must be free.

```sh
POP_DELIVER_ORIGIN=http://localhost:8400 app/scripts/build_web.sh
POP_WEB_DIR=web-app ./demo up --web
```

The Pixel and the laptop must use the same core. The laptop opens the core at `http://localhost:8001/app/`, since a browser only gives the mic to localhost or https. The Pixel reaches the same core at `https://pop.enconomy.dev` through the tunnel, or on the LAN with `--no-tunnel` and the laptop's address under Server in the app.

**2. The Pixel.** Open the core app and enroll if it hasn't. On Home, open Device details and note the `device` value. That's `ONBOARD_ADMIN_DEVICE`.

**3. The ENS folder.** `subname.mjs` is in `research/ethglobal-mumbai/devnet/ens-v2/`, with the admin key under `keys/`. That whole folder is gitignored, so use the checkout that has it. Its `README.md` says how to deploy `blob.eth`, on devnet chain 1337 only, and `subname.mjs` refuses any other chain. That chain needs to be up.

**4. This backend.**

```sh
cd examples/wvp-onboarding
cp .env.example .env
curl -s http://localhost:8001/v1/config | jq -r .presence.pubkey     # paste into ONBOARD_CORE_PRESENCE_PUBKEY
curl -s http://localhost:8001/v1/config | jq -r .chain.chain_id      # must equal ONBOARD_CHAIN_ID
# set ONBOARD_ADMIN_DEVICE, ONBOARD_ADMIN_PASSCODE, and ONBOARD_ENS_DIR if the default doesn't reach the folder
uv sync
uv run --env-file .env uvicorn --factory backend.main:create_app --host 0.0.0.0 --port 8400
```

**5. Bob asks.** On the laptop, in a browser with a wallet, open `http://localhost:8400/`. Connect the wallet, type `bob`, tap Ask the admin.

**6. The admin approves.** On the Pixel's browser, open `http://<laptop-lan-address>:8400/admin`. Enter the passcode, check the full address against Bob's wallet, tap Approve.

**7. The beep.** Bob's page changes to Open the beep page. That opens the core's web app, which shows a code. If this browser never enrolled, enroll first and tap Host. On the Pixel, open the core app, tap Join and scan the code. Both confirm, both Start, keep them side by side.

**8. The name.** On a NEAR the web app hands the record to this backend, which runs `subname.mjs`. Bob's page shows `bob.blob.eth is yours`. If the script fails, Bob's page says so: tap Done on the laptop, then Host, and beep again.

**9. Sign in.** Start the sites with the org setting, and sign in as usual.

```sh
cd wvp
node demo/servers.mjs --owner 0x<any 40 hex> --no-issuer --ens deployment --deployment <deployment file> --org blob.eth
```

`--owner` is required by `servers.mjs` but only fills its local table, which `--ens deployment` doesn't read.

## API

`ctx_hash` is `keccak256("wvp-onboarding-v1\n" || name || "\n" || lowercase address)`.

**`POST /v1/requests`** `{label, address}`. The same name and address is the same request. Asking again after a decline or a clear puts it back in front of the admin. Refuses 400 `bad_label`, 400 `bad_address`, 409 `label_taken`. Answers the request, as below.

**`GET /v1/requests/{ctx_hash}`** `{ctx_hash, label, name, address, status, ens, last_error, beep_url}`. Status is `pending`, `approved`, `declined`, `issued` or `cleared`. The admin's page and the joiner's page both read this: there's no separate status route. `ens` is the JSON line from `subname.mjs`, `{name, address, tx}`.

**`GET /v1/admin/requests`**, **`POST /v1/admin/requests/{ctx_hash}/approve`** and **`/decline`**. They need the header `x-admin-passcode`, else 401 `bad_passcode`.

**`GET /v1/admin/names`**, **`POST /v1/admin/names`**, **`POST /v1/admin/names/{label}`**, **`POST /v1/admin/names/{label}/clear`** and **`GET /v1/admin/jobs/{id}`**. See [Names on the admin page](#names-on-the-admin-page).

**`POST /v1/presence`** `{body, sig_b64}`, the `presence` block from the core's result. Open route: the core's signature is the auth, and the request comes from the record. Checks, in order:

| Check | Refusal |
|---|---|
| Core signature | 401 `bad_record_signature` |
| Record format, transcripts, device signatures | 400 `bad_record` |
| Verdict is NEAR | 403 `not_near` |
| `context` is exactly `{chain_id, consumer: address, ctx_hash}` of a request here | 403 `context_mismatch` |
| Request is approved | 409 `not_approved` |
| The admin's device is in `devices` | 403 `admin_device_missing` |
| Nobody took the label meanwhile | 409 `label_taken` |
| This session wasn't spent | 409 `session_used` |
| `subname.mjs` exits 0 with a JSON line | 502 `ens_failed` |

A failed script gives the session back, so it can try again. Sends run one at a time.

Pages: `GET /` for the joiner, `GET /admin` for the admin. `GET /v1/config` is `{org, chain_id}`.

## Names on the admin page

Below the requests, `/admin` lists every name issued through onboarding or added on that page, each with the address read from the chain just then, through the universal resolver, as the sites read it. You can change a name's wallet, clear it, or add a new one. It's how you show the cutoff: change the wallet, and every browser the old wallet approved stops working at its next login.

**This page controls real names on the devnet, and one passcode is all that guards it.**

All of these need the header `x-admin-passcode`, else 401 `bad_passcode`. The passcode never goes in a URL.

| Route | Body | Refusal |
|---|---|---|
| `GET /v1/admin/names` | | Answers `{org, job, names: [{label, name, address, read_ok}]}`. `read_ok` false means the read failed, not that the name is empty. `job` is the send that's running, or null. |
| `POST /v1/admin/names` | `{label, address}` | 400 `bad_label`, 400 `bad_address`, 409 `label_taken`, 409 `busy` |
| `POST /v1/admin/names/{label}` | `{address}` | The same, with 404 `no_name` in place of `label_taken` |
| `POST /v1/admin/names/{label}/clear` | | 400 `bad_label`, 404 `no_name`, 409 `busy` |
| `GET /v1/admin/jobs/{id}` | | 404 `no_job` |

A send can take minutes and a proxy gives up sooner, so the three POSTs answer 202 at once with a job, and the page polls it: `{id, kind, label, name, status, old, address, target, tx, note, error}`. `status` is `running`, `done` or `failed`. `address` is read from the chain after the send, and that read decides the outcome. A clear reads null. Jobs live in memory, so a restart forgets them.

- **One at a time.** They share one lock with the beep's sends, since there's one admin key. A second send while one runs gets 409 `busy`.
- **Adding never overwrites.** If the chain already has an address for that label, nothing is sent. The name joins the list as it is, and `note` says `already_set`. That's also how a name made outside this backend gets on the list.
- **Clearing frees the label.** Its requests go to `cleared`, an approved one included, so giving it again needs a new request, a new yes and a new beep.
- **An address with mixed case must pass its checksum.** The zero address is refused: clear is its own route.

## The beep

The core has no idea what a name is. It carries a plain context `{chain_id, consumer, ctx_hash}` into the session nonce and the signed record, as it does for the Safe example. `consumer` here is the address that gets the name.

The core's app could never set a context, and only a session member can read the result. On the laptop, the only member is the web app. So its change has two parts, both off unless the URL asks:

1. `/app/?chain_id=&consumer=&ctx_hash=&deliver=` hosts with that context, if `deliver` passes the check below. `PopApi.createSession` takes an optional context, and `PopController.hostContext` holds it.
2. After a NEAR, the web app posts the raw `presence` block to `deliver`. `ResultRecord` gained a `presence` field, and `main.kt` posts it. Any answer from the backend ends it. With no answer, it tries up to five times.

The record holds device keys and transcripts, and the `deliver` URL comes from the link. So the origin of `deliver` must equal the one baked in at build time: `POP_DELIVER_ORIGIN`, or `-Ppop.deliverOrigin`, written to `PopBuildConfig.DELIVER_ORIGIN` like the API base. Otherwise the page ignores all four parameters and behaves as the plain web app. With nothing baked in, no link can deliver. One build serves one backend, and moving the backend means rebuilding.

CORS on this backend allows `POST` only from the origin of `ONBOARD_WEB_APP_URL`.

No change to the server or any circuit. **The Pixel needs no rebuild:** it joins as a guest, and a guest never reads a context. It also means the Pixel shows nothing about the name. The admin page is where the human approves, and the record's `ctx_hash` ties that approval to the session.

## Site setting

`wvp/site/serve.mjs --org blob.eth`, also on `wvp/demo/servers.mjs`, default off. A claim that doesn't end in `.blob.eth` is refused with `not_in_org`, before any lookup. A typed address counts as outside, since it reads no ENS. An anonymous proof is unaffected: it names nothing. Run the site with `--no-proofs` if that matters, as `servers.mjs --no-issuer` does.

## Fake or untested

Run once, with no browser: this backend on a free port, a throwaway presence key and a fake `subname.mjs`. Seen: the success, and the refusals `bad_record_signature`, `context_mismatch`, `not_near`, `not_approved`, `admin_device_missing`, `label_taken`, `bad_label`, `bad_passcode`. A record for a finished request got `not_approved`. `session_used` never fired. It matters once a name is cleared and the same name and address is asked for again: the old record has the same context, and this is what refuses it. The replay is refused by `not_approved`. The record was the core's published test vector, re-signed with its throwaway key and a new context, so never a real session.

Never run:

- A real beep with a context from the web app. The Kotlin change has compiled for the web target, once, and that build has never been opened. Neither the origin check nor the delivery has run.
- The real `subname.mjs`, through the beep or the admin page. Its interface was read from the code, not seen running: `node subname.mjs <label> <address>` in that folder, one JSON line `{name, address, tx}` on stdout with no `ok` field, and a non-zero exit if refused. The admin page has only been run with a fake one. Its chain read has run for real.
- Either page in a browser, with a wallet or on a phone. CORS from the web app.
- The site's `--org` setting. `node --check` only.

Not here: a change made outside this backend. The list reads the chain, so it shows a repoint from the ENS folder, but this backend doesn't hear about a clear from there. Its label stays taken until you clear it on the page too.
