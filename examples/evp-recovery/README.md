# EVP recovery example

You lost your phone. A laptop, a verified email and a new phone next to the laptop move the account to the new phone, after a 120 s delay. One frame tx on chain 1337 checks all three proofs in VERIFY and the email token in its body.

Hackathon build. Happy path only, no tests of its own. `contracts/test` still expects the old phone signature, so 11 of its 158 tests fail, 9 on that check and 2 gas budget tests that weren't traced.

## What it proves

- The laptop's enrolled key and the new phone's key took part in a session that three proofs call NEAR.
- That session is bound to this account, this new key, this recovery nonce and this deadline.
- `alice@tawago.test` was verified by the pinned email issuer, with a token bound to the same `ctx`.
- L, the enrolled laptop account, signed and paid.

## What it doesn't

- **That the devices were really close, if one side cheats.** One cheating side can fake NEAR.
- **That the laptop key is safe.** It's a software key in the browser, and L is a test key in a local file.
- **Anything about the hardware.** No attestation: web devices never have it, and this run allows unattested phones.
- **A real email check.** The issuer is a local fake on `tawago.test`, with the login secret in the source.
- **That the new phone agreed to this tx.** Its signature over `ctx` was dropped as redundant: its transcript signs `popNonce`, which commits `ctx`, and `ctx` holds `newKey`.
- **That the new key works.** `finishRotation` isn't signed by the new key and anyone can call it. A wrong Y still hashes to an address, and that address becomes a dead owner.
- **Silence and tone.** Open since FV v1: a silent recording and a pure tone aren't ruled out.

## The signature list

The start tx has one real signature, L's. It still has two entries, because ethrex's default code reads index 1 for a payment-only frame, so L can't sit at index 0. Entry 0 is an empty ARBITRARY entry that costs 100 gas and that nothing reads.

## Runbook

Needs `uv`, `node`, `cast`, Chrome, `cloudflared`, and `npm ci` done in `relayer/` (the tx builder loads viem from there). All paths are from `examples/evp-recovery`.

### Once

```sh
./run keys                        # TLS cert and email issuer key in .run/keys
scripts/build_pair_named.sh       # pair_named.json where the core looks for it
(cd contracts && forge build)     # via-ir, from contracts/foundry.toml. Heavy on a small machine
```

### Start, one terminal each

```sh
./run core        # :8001, own data in .run/core, POP_PAIR_CIRCUIT=named, chain 1337
./run sidecar     # our sidecar on :14337, 16M verify cap
./run backend     # :8100
./run front       # https on 127.0.0.1:8443: page, issuer, proxy to backend and core
./run chrome      # demo profile, opens the issuer login and the page
```

The phone needs to reach the core over https. Run a tunnel to `:8001`, for example `cloudflared tunnel --config <config> run enconomy-pop`, and set the app's **Server URL** field to it. The debug APK's baked-in default is the emulator address, so this step is needed.

### Enroll and deploy

1. In the demo Chrome, sign in on the `tawago.test` tab. The secret is `local-test-secret`.
2. Open `https://recover.tawago.test/app/` with no `?context=`. Tap to start, enroll, and copy the X it shows.
3. Deploy the account. The funding key file holds one hex line and must have ETH on 1337:

```sh
python3 -I scripts/setup.py --laptop-x <X> --funding-key-file <file> [--owner <address>]
```

This makes L in `.env` if needed, funds it, checks the verifiers on chain hold the VKs the core proves with, pins the core's issuer key, and writes `.run/deploy.json`. Wiping `.run/core` makes a new issuer key, so re-enroll both devices and deploy again.

### The run

Everything from step 2 to the mined tx has to fit in 15 minutes. If it runs out, press "Use this key" again and redo the session.

1. Install `app/composeApp/build/outputs/apk/debug/composeApp-debug.apk`. Enroll on the phone, then show its key QR (128 hex: qx, then qy).
2. On `https://recover.tawago.test/`, paste or scan the key, then press **Use this key**.
3. Press **Open the chirp app**. On the laptop, **Tap to start** to allow the mic.
4. On the phone, **Join** and scan the laptop's QR. Hold them close. **Confirm** on both.
5. After NEAR, the proofs need no taps. Go back to the page and wait for "Ready".
6. Click the email field, type `alice@tawago.test` in lowercase, press Tab. Chrome mints the token and the page sends the tx. The tx hash and frames show when it's mined, usually within a minute. Chrome fills the token only on submit, so the page submits about 4 s after Tab.
7. Wait out the 120 s, press **Finish**. If it errors right at zero, the chain clock is behind: press it again. The page shows owner == new key.

## Layout

| Path | What |
| --- | --- |
| `contracts/` | The account and adapter, moved from `research/ethglobal-mumbai/evp-recovery` |
| `backend/` | `/v1/recovery/{start,submit,finish,state}`, and `send_start.cjs`, the 4-frame tx |
| `scripts/setup.py` | Deploys the account |
| `web/` | `recover.html`, the https front, the Chrome launcher |
| `issuer/` | The local email issuer |
| `app/` | Web and Android app that hosts and joins the session |

The research docs stay in `research/ethglobal-mumbai/evp-recovery`. `contracts/test` reads the live Chrome tokens from there.
