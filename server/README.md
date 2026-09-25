# pop server

FastAPI server for proof of presence, pop-v1. The spec is `../docs/pop-contract.md`. This part covers health/time/config, device enrollment, signed-request auth, pairing (create, invite, join, confirm, abort), arm/start (T0) and commit-then-reveal. Transcript, fail and result reuse the same session document; see `pop/sessions.py`.

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
| `POP_ALLOW_UNATTESTED` | off | `1` accepts `chain: null` at enroll and stores the device as `attested: false`. Use it for emulators and fake phones. |
| `POP_GAIN_DB` | `0` | Play gain, reported in `/v1/config`. |
| `POP_UPLOAD_RECORDINGS` | `1` | Reported in `/v1/config`. |
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
| `test_auth.py` | good, missing headers, unknown device, stale (±61 s), replay, wrong key, tampered body, query covered by the signature |
| `test_invite.py` | 49-byte layout, QR form, rejects |
| `test_jbl250.py` | vendored generator vs goldens (`tests/golden/*.f32`) and vs `fieldprobes` itself (read-only import, skipped without `research/`); sample rates 36k..96k; peak limit; bed key per (session, role, attempt) |
| `test_arm_commit.py` | `/v1/time` ping; arm material (own play + own bed only) and `t0 = now + 3 s` once both armed; bad sample rate / attempt / rtt; unauthenticated and non-member refused; partner bed absent before commit, released after (at the committer's rate); `too_early`; commit signature / role / attempt / nonce checks; attempt 1 gets new codes |
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

## Notes and choices the contract leaves open

- A wrong `join_token` gets 403 `bad_token`. The contract has no code for it. The real token still works after a wrong guess.
- Join check order: 404, `self_join`, `already_joined`, `bad_token`, `token_expired`. A reused token (session already joined) therefore gets 409 `already_joined`, even from the original guest.
- An expired token moves the session to `aborted` with `error: "timeout"`. So does a live session older than 10 min. Both are checked lazily on access.
- `POST /v1/session` also returns `invite_qr` (`"pop1:" + invite_b64url`). The session view's `self` and `partner` also carry `pubkey`, and `partner` carries `security_level`. All of these are additions to the contract.
- `confirm` is idempotent, and `abort` on a finished session returns the view unchanged.
- The replay cache is in memory, so a restart forgets it. The 60 s ts window still applies.
- Long-poll re-reads the store every 100 ms.
