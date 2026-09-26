
## real-phone-pop-baseline

Status: UNRESOLVABLE NOW (needs hands on two phones). Treat as a blocker for both SAFE and POOL demos.

What is known (2026-09-26):
- No real-phone run of the native app has ever happened. `server/data/sessions/` does not exist (only `server/data/zk/`). VERIFIED (`ls server/data`).
- No iPhone audio data of any kind exists. All 78 research sessions (research/sound-bound/data/sessions 41, spikes/melody/fieldtest 37) are Mac Chrome + Android 10 Chrome; zero iPhone user agents. VERIFIED (grep user_agent).
- The whole JBL250 evidence base is 12 sessions, one room, Mac + Android. VERIFIED (research/2026-09-26-sound-bound-decision.md lines 53, 132-134).
- Server rule: NEAR iff -20 < flight < 60 cm; flight >= 60 is NOT_NEAR `too_far`, not retried; flight <= -20 or self_os_delta fail triggers one retry. VERIFIED (server/pop/constants.py NEAR_CM=60, server/pop/verdict.py decide()). So 30 cm and 200 cm sit well away from the edges; a clean test.
- Only simulated end-to-end checks pass: `tests/test_flow_fake_phones.py` (NEAR 0/30, too_far 100/200) and app `LiveServerRunTest` (fake room, real DSP). VERIFIED (server/README.md, app/README.md). These do not exercise mic/speaker latency, iOS AVAudioSession, AGC/EC, or Android 20 ms glitches.
- At check time: Android APK built (app/composeApp/build/outputs/apk/debug/composeApp-debug.apk, 15:36); Android phone on USB but `adb devices` = `unauthorized` (accept the USB-debugging prompt); iPhone not connected (`xcrun devicectl list devices` = none). VERIFIED.

iPhone-specific risks nobody has seen yet:
1. Free Apple team: no App Attest, no NFC. iPhone enrolls a Secure Enclave key with no attestation, which the server rejects unless started with `POP_ALLOW_UNATTESTED=1`. VERIFIED (server/README.md test_enroll_ios row; app/README.md line 90, 103).
2. iPhone host shows QR only (no HCE); iPhone guest needs QR too on free team. Plan pairing as Android host + iPhone scans QR, or iPhone host + Android scans.
3. `.playAndRecord` + `.measurement` + `.defaultToSpeaker` never checked on hardware: earpiece routing, AGC, output latency vs the -150/+250 ms search window. UNVERIFIED.
4. Android native AAudio glitch rate unknown (browser: 13 x 20 ms blocks per 816 s). UNVERIFIED.
5. ATS: plain http only to LAN IPs (`NSAllowsLocalNetworking`); use the Mac LAN IP or a cloudflared https URL. VERIFIED (app/README.md line 125).

Protocol to resolve (about 30 min once the in-flight workflow lands):
1. Server: `cd server && POP_ALLOW_UNATTESTED=1 uv run python -m pop` (port 8000), plus `cloudflared tunnel --url http://localhost:8000` if phones are not on the Mac's Wi-Fi.
2. Android: accept USB debugging, `adb install -r app/composeApp/build/outputs/apk/debug/composeApp-debug.apk` (rebuild with `-Ppop.serverUrl=<url>` or set the URL in-app). iPhone: Developer Mode on, Xcode Run from `app/iosApp/iosApp.xcodeproj` with `POP_SERVER_URL` set, trust the profile.
3. Both: Ping server, Enroll, media volume >= 60%, no Bluetooth audio, hold the phones speaker-to-speaker height, same quiet room.
4. 10 sessions at 30 cm (tape measure, center to center), 10 at 200 cm. Alternate host role (5 Android host, 5 iPhone host) so both sign directions are covered.
5. Record per session from `GET /v1/session/{id}/result` (also `server/data/sessions/<id>/result.json`): verdict, flight_cm, attempt used (0 or 1), last_failure.reason, and whether the proof upload succeeded. A one-liner: `for f in server/data/sessions/*/result.json; do jq -c '{v:.verdict,f:.flight_cm,r:.reason,a:.attempt}' (keys per server/pop/verdict.py:159; check the record nesting on first run) $f; done`.
6. Pass gate: >= 9/10 NEAR at 30 cm (a retry that ends NEAR counts as pass, but log retry rate), and 10/10 NOT_NEAR at 200 cm (a false NEAR at 2 m is a security failure, not a flake, so zero tolerance). Also expect 30 cm flight_cm within about 10-50 and 200 cm around 170-230; a systematic offset means a latency bug even if verdicts pass.

If it fails: first suspects in order are iOS enrollment (unattested flag), iOS audio route/latency (arrival outside window -> `impossible_flight`/timeout retries), Android glitch (flat-block check drops), clock-sync on cellular.

Design-doc impact: the World ID / chain layer must consume only the server's result record (verdict NEAR + session id + both roles), so it can be built and tested in parallel with fake NEAR records (`tests/sim2.py`), but no SAFE/POOL demo claim is final until this table exists. Keep a demo fallback: two Android phones, or Android + Mac browser, if iPhone fails.

## payee-cannot-verify-leaf

**Status: resolved (spec + scratchpad test).** Blocks: pool.

**Problem.** `presenceLeaf = Poseidon(TAG_PRES, payerTag, payeeCommitment)`. If Q's phone signs a nonce derived from an opaque leaf, P can meet a real human Q and bind the meeting to a leaf that pays sybil R. Then the pool only enforces "P met someone".

**Fix. Q never signs anything it did not recompute.**

1. Q already knows `value` and `payeePre`, because it made them (pool.md §4.2 step 2). It keeps both locally for the session.
2. P sends `payerTag = Poseidon(TAG_PAYER, existingNullifier)` to Q. Channel: the session `context` (bridge.md §4), e.g. `context = {chain_id, consumer: pool, ctx_hash, kind: "pool-xfer", pool: {payer_tag, value}}`. The server sees `payerTag` anyway (pool.md §4.2 step 4).
3. Before Confirm, which is when the nonce is revealed and the POPC commit is signed, Q's app computes:
   ```
   pc     = Poseidon(value, LABEL_TRANSFER, payeePre)            // its own value + payeePre, not the server's
   leaf   = Poseidon(TAG_PRES, context.pool.payer_tag, pc)
   ctx    = keccak256(abi.encode("pool-xfer-v1", POOL_ADDR, leaf))  // POOL_ADDR and chainId are app constants, not taken from the server
   nonce  = keccak256(abi.encode(keccak256("pop-ctx-v1"), chainId, POOL_ADDR, ctx, notBefore, sessionId))
   ```
   It then requires `ctx == context.ctx_hash` and `nonce == session.nonce_hex`. On any mismatch it refuses Confirm with `context_mismatch` and does not start the World ID request either, since signal = `encodePacked(nonce, role)`.
4. The circuit already forces the spend to output exactly the `payeeCommitment` inside the leaf (`presenceTransfer.circom`, `presenceRoot === pr.out`, line 93). So a leaf Q approved can only pay Q's note, with Q's `value`.
5. Q treats the payment as done only when `pc` appears as a state-tree `LeafInserted`, not when the presence leaf is posted. A fake `payerTag` from P can't be caught by Q, but it only makes the leaf useless: P can't spend against it (test case 8). Q just doesn't get paid, and Q can see that.

**Scratchpad test.** VERIFIED(`node payeecheck.cjs` in `scratchpad/pool/privacy-pools-core/packages/circuits/pres/`, using the compiled V2 `outT/presenceTransfer_js/presenceTransfer.wasm`, poseidon-lite, viem, snarkjs `wtns.calculate`):

| # | case | result |
|---|---|---|
| 1 | server ctx built from leafR (pays sybil R); Q checks with its own pcQ | REFUSE context_mismatch(ctx) |
| 2 | honest ctx from leafQ | CONFIRM |
| 3 | leaf built with value 1100, Q expects 1200 | REFUSE context_mismatch(ctx) |
| 4 | ctx matches but nonce derived from another ctx | REFUSE context_mismatch(nonce) |
| 5 | circuit: presence tree has leafQ, P pays Q | SAT |
| 6 | circuit: tree has leafQ, P pays R (wrong payeeCommitment) | UNSAT (line 93, presence root) |
| 7 | circuit: tree has leafR, i.e. what happens if Q signs an opaque leaf | SAT. This is the attack the check blocks |
| 8 | fake payerTag: Q's check passes; P spends its real note against that leaf | UNSAT. Harmless to Q; Q stays unpaid |
| 9 | `payerTag` vs `nullifierHash` for the same nullifier | different (2128…2267 vs 8314…9161) |

**Linkability of payerTag.** `payerTag = Poseidon2(TAG_PAYER, n)`. The chain later shows `nullifierHash = Poseidon1(n)`. These are different circomlib Poseidon instances (t=3 and t=2, with different round constants), and there's a domain tag on top. Linking them requires `n`, a Poseidon preimage. So Q and the attester can't link a meeting to the spend's nullifier. VERIFIED(case 9; the preimage-resistance argument is standard). The residual leak: the same note used in two sessions gives the same payerTag, so those two attempts are linkable to each other. Fine, since the attester sees both sessions anyway. Fresh-note-per-payment removes it.

**What this does and doesn't cover.**
- It covers a malicious payer with an honest server, which is the Q&A attack. P can't get Q's signature, Q's World ID proof or Q's audio run onto a leaf that doesn't pay Q.
- It doesn't cover a malicious attester in tier 1, where the server EOA calls `postPresence(leaf)` directly. The server could post leafR regardless of what Q signed. Closing that needs tier 2 (bridge.md §4-5). The contract takes both phones' POPT/POPC P-256 signatures over `nonce` (RIP-7212 precompile on World Chain) plus `leaf`, recomputes `ctx` and `nonce` onchain, and only then inserts. Say in the doc: "demo = tier 1, attester trusted to post only the ctx-matched leaf; tier 2 removes that trust." The server must at least recompute `leaf` from P's `payerTag` and Q's device-signed `payeeCommitment` submission, and check `keccak(abi.encode("pool-xfer-v1", pool, leaf)) == ctx_hash` before posting.
- Q's `payeePre` must be fresh per payment request. A reused `pc` makes LeanIMT revert `LeafAlreadyExists` at transfer time (pool.md §5).

**Implementer checklist.**
- server `POST /v1/session`: accept `context.pool.{payer_tag, value}` and expose it in the guest's session view.
- app: add `PoolCtx.check(payerTag, value, payeePre, ctx_hash, nonce_hex, notBefore, sessionId)`, gated before Confirm and before IDKit. Error code `context_mismatch`. Show "receive `value` from <display>" only after the check passes.
- server, before posting: run the same recompute plus the ctx equality.
- tests: port cases 1-4 to app unit tests (Kotlin; Poseidon parity via existing `zk/` Poseidon code if BN254-circomlib compatible, UNVERIFIED) and cases 5-8 to circuit tests.

## human-to-device-mapping

Status: partially resolved. The physical facts (who is Orb-verified, which phone holds each credential) need a 10-minute check with the team. The design choice doesn't have to wait for it.

### What is known

- **One Orb-verified human, World ID app on an Android phone, same-device flow works.** The spike got two real Proof of Human v4 proofs, Portal `success:true`, `environment:"production"`, at 2026-09-25 00:44 and 00:45. Both came from LAN IP 192.168.0.58. The integrity JWT says `iss: attestation.worldcoin.org, app_version 1.0.503, platform android`. VERIFIED(`~/dev/worldid-spike/backend/logs/backend.log` lines 58-70, JWT decoded).
  - Whether that Android is the PoP Android: UNVERIFIED. It is likely, since the user owns one Android and one iPhone (memory `pop-app-build-status.md`). The adb serial currently attached is `1B251FDF6008Z3`, status unauthorized.
  - Both proofs are probably the same human (same phone, one minute apart). Different actions give different nullifiers, so the log can't tell.
- **iOS same-device: not tested.** It is documented only: the official Swift sample uses a custom-scheme `return_to` plus `UIApplication.open(connectorURL)` (see `mobile-wallet.md`).
- **Cross-device QR: not tested by us.** It is the documented IDKit pattern: the same `connectorURI` is either opened on the device or shown as a QR. VERIFIED(`~/dev/worldid-spike/docs/idkit-research-brief.md:31,129-132`).
- **Universal link routing, checked live:**
  - iOS AASA gives `/verify` and `/verify/*` only to `35RXKB6738.org.world.id` (the World ID app). World Money (`org.worldcoin.insight`) doesn't claim `/verify`. The AASA also lists an App Clip `org.world.id.Clip`.
  - Android `assetlinks.json` gives `handle_all_urls` to both `org.world.id` and `com.worldcoin`. With both installed, which one opens `/verify` depends on their manifests (UNVERIFIED). The spike answer came from the World ID app.
  - Without the app, `world.org/verify?...` returns 307 to `/download?...&worldid=true`.
  - VERIFIED(`curl https://world.org/.well-known/apple-app-site-association`, `curl https://world.org/.well-known/assetlinks.json`, `curl -I https://world.org/verify?t=wld&i=x&k=y`, all 2026-09-26).
- **One account per device, and the account moves; it doesn't copy.** World's help center says each device holds a single account. Moving an account means logging in on the new phone, and the article tells you to delete the app on the old phone. The World ID app and World Money share one identity, so verification carries over. VERIFIED(support.world.org articles 32888556742675, 36071378920467, 54673496231699, fetched via the Zendesk API `/api/v2/help_center/en-us/articles/<id>.json`, updated 2026-09-18/25).
  - Consequence: putting a second person's World ID on the team's PoP iPhone means that person logs into their own account on someone else's phone and risks disturbing their personal install. Don't do this.
  - Putting the *same* human's World ID on both PoP phones makes both roles return the same person. `pair_tag` would show one human, and the distinct-human demo fails.
- **Face Auth / presence check.** IDKit has `require_user_presence` (default `false`). When it's `true`, World App runs a presence check, and the error `user_presence_failed` means the check failed or was not completed. VERIFIED(`scratchpad/wid/idkit/js/packages/core/src/types/config.ts:61-62`, `rust/core/src/error.rs:125-127`, `bridge.rs:578-581`; idkit HEAD 16bc527f, 2026-09-23).
  - The help center also says the World ID app "may ask you to complete Face Authentication" for some features. VERIFIED(support article 31589092274195).
  - So the credential holder must physically hold their own phone. It can't be handed to a teammate.
- **Name clash.** World ID now ships a credential called **"Proof of Presence"** ("proves you're present with just a selfie"). VERIFIED(support article 55499979675667). Judges will confuse it with our acoustic PoP. The pitch should say "co-presence" or "proof of proximity", or disambiguate explicitly.

### Decision for the design doc (both SAFE and POOL)

1. **Mapping rule.** Each human proves with World ID on the phone that already holds their credential. Never move a credential to a PoP phone for the demo.
2. **Both modes on every role.** Implement both modes, chosen by a button:
   - **Same device**: open `connectorURI` with `return_to` to our scheme.
   - **Other phone**: render `connectorURI` as a QR on the PoP phone's screen, scanned with the human's personal phone camera.
   - Both are the same IDKit request with the same bridge polling, so the extra mode costs only a QR render. Kotlin can use zxing core; iOS can use `CIQRCodeGenerator`. No new dependency on the server.
3. **Expected stage setup (to confirm).**
   - Human A = the owner of the Android PoP phone. A uses same-device, which is proven on Android.
   - Human B = second team member. B scans the QR on the iPhone PoP phone with B's personal phone, taking the cross-device path.
   - Cross-device is also the *safer* path on iOS: the PoP app never leaves the foreground, so there's no background kill and no audio-session loss. The whole iOS custom-scheme `return_to` question goes away for the demo.
4. **Order stays as in `docs/pop-human-adapters.md`.** Both World ID proofs happen before the audio run. RP signature TTL is 300 s (spike brief line 26), so do the World ID step within 5 min of the `/rp-context` call. Re-fetch rp-context on retry.
5. **Timing budget.** Same-device measured about 20-30 s from rp-context to verify: 00:43:32 to 00:43:59, then 00:45:10 to 00:45:22 (spike log). Cross-device adds the QR scan, about 5-10 s more. Not measured.

### What remains, and the cheapest check

- **Who is Orb-verified?** Ask the team; it needs 2 distinct humans. Each person opens the World ID app, Credentials tab, and checks for "Proof of Human". Also check for a "Face Auth update required" banner: a pre-March-2024 Orb verification may need re-auth at an Orb (support article 46534638088723), and that would break the demo.
- **Cross-device QR returns a proof.** Test with the existing spike:
  1. Run the backend.
  2. In the Android spike app, tap Get nullifier and copy `connectorURI` from `adb logcat -s WorldIdSpike`.
  3. Cancel the app switch and keep the app polling. Or build the request on the Mac with `@worldcoin/idkit-core` and a small node script that polls.
  4. Run `qrencode -t ansiutf8 '<uri>'` and scan it with human B's phone camera.
  5. Expect `portal-verify-resp status 200` in `backend.log`, with a nullifier different from human A's.
- **iOS same-device** is only needed if human B's own phone is the PoP iPhone. Test it by building the Swift IDKit sample with `returnTo = "idkitsample://callback"`.
- **Android chooser.** If the Android phone has both World Money and the World ID app installed, check that `/verify` opens the World ID app and not a chooser.

## pop-works-on-demo-phones

Status: UNRESOLVED NOW. Needs a person holding the two phones. Blocker for both SAFE and POOL.

Answer: No. The current app (POPT v2 + option A ZK) has never produced a verdict on the demo pair (Android + iPhone, free team) through a tunnel.
- No run evidence exists: no pop sqlite anywhere (repo, /tmp), no pop server or cloudflared running. VERIFIED(`find`, `ps`, 2026-09-26).
- At check time `adb devices` shows the Android as `unauthorized`, and `xcrun devicectl list devices` finds no iPhone. VERIFIED(command).
- The memory note says both the Android and iOS apps are untested on real phones. The iPhone build has only been checked in the simulator. VERIFIED(memory pop-app-build-status.md, app/README.md).
- The ZK integration is still uncommitted in app/ (zk/, iosProver/, nativeInterop/ untracked). The server side landed at ba81f84. VERIFIED(git status).

What is known, as a proxy:
- Server pipeline with fake phones on HEAD (ba81f84): `tests/test_flow_v2.py` + `tests/test_flow_fake_phones.py` gave 46 passed, 2 skipped. The 2 skips are the field-recording tests, because my scratch copy had no research data. VERIFIED(scratchpad `uv run pytest`, 118 s).
- Ranging on real hardware, from the 2026-09-23/24 web prototype (Mac + Android browser, same JBL250/four-arrival math; NOT the native app and NOT the iPhone), 38 sessions in research/sound-bound/data/sessions. Verdict rule is NEAR iff -20 < flight_cm < 60 (docs/pop-contract.md §8). Usable rounds:
  - 0 cm: 24/24 NEAR
  - 5 cm: 7/8 NEAR
  - 30 cm: 34/35 NEAR, max 39.7
  - 60 cm: 0/22 NEAR, 60.0..71.8
  - 100 cm: 0/18 NEAR, 94..117
  - 150 cm: 0/4 NEAR, 154
  - 200 cm: 0/7 NEAR, 132..188
  VERIFIED(script over result.json).
  - False NEAR at 60 cm or more: 0 of 51 usable rounds. The refusal path looks safe, and a far round that is not usable ends as NOT_NEAR anyway: 17/24 at 200 cm and 10/28 at 100 cm were not usable, and the contract turns that into a retry, then NOT_NEAR.
  - Failure found: 2 close-range rounds read about -320 cm (5 cm and 30 cm). That is below -20, so the verdict is a false NOT_NEAR. So at 30 cm expect roughly 1 in 30 false refusals, before the retry.
- For the "owners apart" demo, NOT_NEAR at 150 cm is deterministic in practice. It comes out either as too_far (flight 130-190) or as a failed measurement leading to NOT_NEAR. The prototype never came close to a false NEAR at 1 m or more. The unknown is NEAR at 30 cm on iPhone + Android native.

Risks still open (all need the phones):
1. iPhone audio path: AVAudioSession mode, echo cancellation or voice processing, output latency. The 2026-09-23 handoff lists "repeat walk on iPhone + Android" as not done.
2. Option A proof runs after NEAR. On an M2 it costs about 5 s and 1.9 GB peak (docs/pop-prover.md). Phone RAM and time are unmeasured. The SAFE/POOL flow must not wait on the proof unless it has been measured.
3. Tunnel latency: the 25 s long-poll fits under Cloudflare's 100 s limit (server/README.md). Wall time per session is unmeasured.
4. Free Apple team: the app must be re-signed every 7 days, and App Attest/NFC are off, so pairing uses QR.

Cheapest way to close this (about 45 min, needs the user):
1. Authorize adb on the Android (accept the prompt on the phone). Plug in the iPhone, trust the Mac, and turn on Developer Mode.
2. `cd server && POP_ALLOW_UNATTESTED=1 uv run python -m pop` + `cloudflared tunnel --url http://localhost:8000`, then build both apps with that URL (app/README.md).
3. Protocol:
   - 10 runs at 30 cm and 10 runs at 150 cm, plus 5 at 30 cm with venue noise (a laptop playing crowd audio at about 70 dBA).
   - Log verdict, reason, flight_cm, attempts, and wall time from tap to verdict and from tap to zk verified.
   - Pull this from `GET /v1/sessions/<sid>/result` or from the server DB.
4. Pass gate:
   - 150 cm: 10/10 NOT_NEAR.
   - 30 cm: at least 9/10 NEAR after the retry.
   - Median wall time under 15 s to verdict.
   - The proof finishes on both phones without an OOM.
   If NEAR fails on the iPhone, check echoCancellation/voice processing first.

Design impact: SAFE/POOL must treat "NOT_NEAR" as the default and demo-safe path. Show the NEAR happy path with a pre-recorded fallback video in case the venue is noisy. Gate the tx on the server's NEAR result record, not on the ZK proof finishing, until phone proof timing is measured.

## integration-freeze-point

Status: partially resolved (server frozen now; app freezes on one pending commit). Checked 2026-09-26 16:11 JST.

### What the other workflow is and where it stands
- It is `pop-zk-readiness`, run from the "EthGlobal hackathon project" session (tmux 0:@0.%2). Script: `~/.claude/projects/-Users-takahiro-ogawa-dev-enconomy/055795ca-.../workflows/scripts/pop-zk-readiness-wf_e80a3322-982.js`. VERIFIED (read script + journal.jsonl).
- Chunks and owners (script lines 108-131): S5, S6, S7 own `server/`; K1, A5, A6 own `app/composeApp/src/`; P1 owns `app/prover/`; **P2 owns all of `app/`**. Measure and Integration phases must not edit files (lines 148, 154). VERIFIED.
- Done and committed: S5 2d70342, S6 c9fa84a, K1 38cc0ad, A5 46d0d0c, P1 d275938, A6 ce03696, **S7 ba81f84 (last server chunk)**. VERIFIED (`git log`, journal).
- Still open: P2 "prover integration in app". Built 15:18-16:02; `review:P2#0` started 16:02 and is running. Then optional fix + re-review, then commit with message `app: on-device proving after near`, then Measure (phones are plugged in), then Integration (read-only). VERIFIED (journal, tmux pane).
- ETA (ESTIMATE from earlier chunk timings: reviews 3-25 min, fixes ~30 min): P2 commit ~16:30-17:30 JST; workflow end ~17:30-18:30. After that, its orchestrator said it will "go through [review results] including open issues", so 0-2 follow-up commits are possible.

### Freeze points
- **Server: `ba81f84`** (`server: proof upload, verification and proving key download`). `git status server/` is clean; no remaining chunk owns `server/`. VERIFIED.
  - OpenAPI snapshot: scratchpad `freeze/openapi-ba81f84.json`, sha256 `6304b552f453065d3b44a55fd5deed81b9c273d1dc6afa4ad3a2d9513d3ef9b9` (made with `create_app().openapi()`, `uv run --offline`). Routes: GET /health, /v1/health, /v1/time, /v1/config, /v1/zk/keys, /v1/zk/keys/{name}, /v1/enroll/nonce; POST /v1/enroll, /v1/session, /v1/session/{sid}/{join,confirm,arm,commit,transcript,fail,recording,proof,abort}; GET /v1/session/{sid}, /v1/session/{sid}/result. VERIFIED.
  - Note: FastAPI's schema hides the real bodies of `/proof` and `/recording` (they read `request.form()`), and `POST /v1/session` takes no body model today. Use the source, not the schema, for those.
- **App: the commit whose subject is `app: on-device proving after near`** (not created yet). Find it with `git log -1 --format=%H --grep='^app: on-device proving after near'`. Until it exists, `App.kt`, `PopApi.kt`, `PopController.kt`, `RunFlow.kt`, `build.gradle.kts` are uncommitted P2 edits (+321/-8 in the four .kt files) and line numbers will move. VERIFIED (`git diff --stat`).
- **Gate for any World ID agent to start editing app/ or server/:** (1) that app commit exists; (2) `git status --porcelain -- app server | grep -v '^??'` is empty; (3) the pop-zk-readiness run shows finished in session %2. Pin the design doc to the HEAD hash at that moment.

### Found while checking: app and server disagree on the proof upload (live bug in the in-flight work)
- Server `ba81f84` `main.py:393-435`: `POST /v1/session/{sid}/proof` wants **multipart** `proof` (file) + `meta` JSON `{attempt, circuit, salt}`.
- App working tree `PopController.kt:538-549` sends **JSON** `{attempt, role, circuit, sample_rate, valid_at, half_commit, salt, proof_b64}` via `api.postJson`.
- Starlette `Request.form()` returns an empty `FormData()` for `application/json` (checked in `server/.venv/.../starlette/requests.py:309-310`), so the server answers 400 `bad_request` "multipart field 'proof' (file) required". The app only treats 404/405 as "server takes no proofs yet", so users see "upload failed: bad_request". VERIFIED by reading both sides; not run end to end.
- Whoever fixes it: P2 owns `app/`, so the cheap fix is the app sending multipart via the existing `PopApi.signedRaw(...)` (the `/recording` pattern). Tell the pop-zk-readiness orchestrator (session %2) if its review misses it. World ID work must not start on top of a broken proof path, because `zk.status` feeds the attestation below.
- Also: app `ResultRecord.valid_at` (PopApi.kt:139) does not exist on the server; the server exposes `zk_valid_at` (view) and `zk.valid_at` (record). Both fall back to `t0_ms // 1000`, so values agree today, but the field name is dead.

### Other lane touching the same files
- The ENS design workflow (session %1, writes `docs/ens-meetings-design.md`) plans edits to `sessions.py` (`publish`, view fields, `ens_hook` in `_finalize`, hook in `zk_record`), `main.py` (Settings, `/v1/config.ens`, `/v1/ens/*`, `/v1/session/{id}/publish`), `store.py`, `pyproject.toml` (+`web3==8.0.0`), and `PopApi.kt`/`PopController.kt`/`App.kt` (its §"work packages", lines 744-798). VERIFIED (grep of that doc).
- `docs/pop-human-adapters.md:106-108` already reserves `POST /v1/session` body `policy {adapter, min_strength}`, `GET /v1/session/{id}/human/context`, `POST /v1/session/{id}/human`.
- Rule: one lane edits `server/` at a time and one lane edits `app/` at a time, small commits, rebase before start. World ID lane goes first on `POST /v1/session` (it defines the body), ENS rebases onto it. If only one product ships, drop the other lane.

### Who does what, and when
Owner: the World ID implementation workflow (a new one), after the gate above. Not the ZK workflow (out of its scope: `pop-human-adapters.md` "World ID adapter is NOT in scope", script line 26). Two serialized packages, server first because the app needs the new fields.

**WID-S (server, base ba81f84, anchors are stable)**
1. `main.py:319-321` `create_session`: add body model `SessionIn(BaseModel): context: str | None = None` (0x + 64 hex, the chain-side intent hash, e.g. safeTxHash or payment-intent hash) and `policy: dict | None = None` (reserved per human-adapters doc). Must still accept `{}` (the app sends `"{}"`, PopApi.kt `createSession`) and the signed-body auth (`device()` hashes the raw body) keeps working unchanged.
2. `sessions.py:137-158` `Sessions.create(host)` gains `context: bytes | None`. Replace `"nonce_hex": secrets.token_hex(32)` (line 142) with: `nonce_salt = token_bytes(32)`; `nonce = sha256(b"enconomy/pop-nonce/v1" ‖ context32 ‖ nonce_salt)` when context is given, else keep random. Store `context_hex`, `nonce_salt_hex`. SHA-256, not keccak: both sides already have it (`hashlib`; app `Bytes.kt:35 object Sha256`), EVM has the sha256 precompile (0x02), and no new dependency. The nonce stays 32 bytes, so POPC/POPT layouts and the circuit's `nonceHi/nonceLo` public inputs (`zk.py:84-86`) need no change. VERIFIED (source).
3. `sessions.py:526-549` `view()`: add `"context"` and `"nonce_salt"` (same visibility rule as `nonce`, line 535: only after both confirm) so both phones can recompute the nonce.
4. `sessions.py:318-345` `_record()`: add `"context"`, `"nonce_salt"`, and a `"human"` block (World ID result per role, nullifiers, `pair_tag`).
5. New `server/pop/human.py` (World ID verify) + routes in `main.py` after `/abort` (line 437): `GET /v1/session/{sid}/human/context`, `POST /v1/session/{sid}/human`. State lives in the session doc as `s["human"]` like `s["zk"]` (`sessions.py:513-524`), so no `store.py` change. Arm gating goes in `sessions.py:212` `arm()` behind a policy flag (default off, keeps v1/v2 tests green).
6. New public read `GET /v1/session/{sid}/attestation` next to `result` (`main.py:370-374`, which is member-only): redacted record `{session_id, session_nonce, context, nonce_salt, attempt, verdict, finished_at, zk.status, human.pair_tag}` + server signature. Key and signature scheme are for the chain design to pick (EIP-712/secp256k1 needs keccak: comes free if the ENS lane lands `web3==8.0.0`; else add `eth-account` or `pycryptodome`). Publish the attester public key/address in `/v1/config` (`main.py:209-215`).
7. Tests: new `tests/test_worldid.py`, `tests/test_attestation.py`; existing `test_flow_v2.py`, `test_zk.py` must stay green (`cd server && uv run pytest -q`, 378 passed + 1 skipped at ba81f84 per the S7 report).

**WID-A (app, base = the P2 commit; anchor by symbol, lines are from the 16:02 P2 tree)**
1. `PopApi.kt` `createSession()` (line 238): take `SessionReq(context: String? = null, policy: JsonObject? = null)`; `SessionView` (line ~103): add `context`, `nonce_salt`, `human`; `ResultRecord` (line ~129): add `context`, `nonce_salt`, `session_nonce`. New calls `humanContext(id)`, `human(id, req)`, `attestation(id)`.
2. `PopController.kt` `host()` (line 323): pass the context (from a deep link / QR of the Safe tx or payment intent). `confirmPartner()` (line 427): after nonce is known and before `runSession`, recompute `sha256("enconomy/pop-nonce/v1" ‖ context ‖ nonce_salt)` and refuse to run on mismatch; then the IDKit hop (new expect/actual in a new `human/` package; open World App, wait for the callback, `POST /human`).
3. `App.kt` `Confirm` composable (line 178): show the context (short hash + what it is) and "nonce checks out"; `Result` (line 244): show attestation status.
4. Leave `zk/`, `RunFlow.kt`, `ProofRunner.kt` alone (P2 territory, not needed).

### What remains unknown and the cheapest way to close it
- The exact app freeze hash: run the `git log --grep` command above after ~17:30 JST, or ask session %2 ("EthGlobal hackathon project").
- Whether P2's review/fix changes `PopApi.kt` signatures: diff `git show <P2>:app/.../PopApi.kt` against the list above once it lands; only `createSession`, `SessionView`, `ResultRecord` matter here.
- Whether the orchestrator of %2 will fix the proof upload shape in app (multipart) or server (accept JSON): ask it directly; the design doc should cite whichever shape ends up committed.

## mainnet-480-ops

**Answer.** Getting onto 480 is cheap and fast. Verification is one free Etherscan key. Measured 2026-09-26 ~07:15 UTC.

**Getting ETH onto 480**
- Fastest: bridge from Base / OP / Arbitrum / Ethereum with **Relay** or **Across**. Relay quote Base→480, 0.01 ETH: `timeEstimate = 2 s`, fee $0.023. Across Base→480 WETH: `estimatedFillTimeSec = 1`. VERIFIED (`POST api.relay.link/quote`, `GET app.across.to/api/suggested-fees?...originChainId=8453&destinationChainId=480`). Both list 480 as enabled (`GET api.relay.link/chains`).
- Native OP deposit from L1 works without any UI. Send ETH to `OptimismPortalProxy 0xd5ec14a83B7d95BE1E2Ac12523e2dEE12Cbeea6C` (portal v5.6.1, `paused()=false`). Or call `L1StandardBridgeProxy 0x470458C91978D2d929704489Ad730DC3E3001113`. VERIFIED (superchain-registry `superchain/configs/mainnet/worldchain.toml`, `cast call`).
  - Measured lag: an L1 deposit in block 26059966 was included as a `0x7e` tx in L2 block 35535053, **70 s** after the L1 block. So about 1.5–2 min end to end. L1 gas was 0.058 gwei; a plain send to the portal estimates 128,554 gas (about $0.02). VERIFIED (cast, L1Block predeploy `0x4200…0015`).
  - Commands: `cast send 0xd5ec14a83B7d95BE1E2Ac12523e2dEE12Cbeea6C --value 0.01ether --rpc-url https://ethereum-rpc.publicnode.com --private-key $PK`. This credits the same address on 480. Use an EOA only; a contract sender gets an aliased address.
  - The "~12 min" figure for Superbridge in blog posts is UNVERIFIED and inconsistent with our measurement.
- CEX direct withdrawal to "World Chain" for ETH: UNVERIFIED (no source found). Fallback: withdraw to Base or Arbitrum, then Relay or Across (about 2 s).
- Official bridge list: docs.world.org/world-chain/providers/bridges. VERIFIED.

**How much ETH (it's almost free)**
- 480 gas price is 0.0015 gwei (base fee 0.0005 gwei). VERIFIED (`cast gas-price`, `cast base-fee`).
- L1 data fee upper bound, from GasPriceOracle `0x420…000F` `getL1FeeUpperBound`: 600 B tx = 6.9e9 wei; 6 KB = 6.6e10; 25 KB deploy = 2.7e11 wei. VERIFIED.
- A 3M-gas deploy is about 4.5e-6 ETH L2 + 3e-7 L1, under $0.02 at ETH $2,690. A Safe `execTransaction` costs about $0.001.
- **Budget:** bridge **0.01 ETH** (about $27) per key. That is a margin of more than 100×.

**Who funds what**
- The team funds everything from a personal wallet via Relay or Across, **now, before building**. Nobody else pays: World App gas sponsorship covers World App user txs, not our EOA (see mobile-wallet.md U10).
- Keys: `DEPLOYER` (forge scripts) and `RELAYER` (server hot key that calls `execTransaction` / pool `transfer`). Give each 0.005–0.01 ETH. Keep the relayer key only in the server env. One key for both roles is acceptable for the hackathon.
- **SAFE demo balance:** the relayer or deployer sends 0.002 ETH to the Safe after `createProxyWithNonce`. The demo tx moves 0.0001 ETH to a visible recipient.
- **POOL demo balance:** each demo payer deposits 0.001 ETH (relayer-funded deposit, or from a funded payer EOA).
- Add a server startup check: `eth_getBalance(RELAYER) < 0.001 ETH` → log loudly and put it in `/health`.

**Explorer and verification**
- Worldscan (worldscan.org) is Etherscan. It uses the **Etherscan API V2** with `chainid=480` (4801 for Sepolia) and one Etherscan.io key: `https://api.etherscan.io/v2/api?chainid=480`. VERIFIED (`GET api.etherscan.io/v2/chainlist`).
- World 480 and 4801 are on the **Free** tier. Docs: "Source code and ABI endpoints are available on all chains for every API plan". VERIFIED (docs.etherscan.io/supported-chains). A keyless call returns `Missing/Invalid API Key`, so a key is required. Get it by signing up at etherscan.io → API Keys; it takes a few minutes.
- Foundry 1.4.3 knows chain 480 as `world` and routes to Etherscan. VERIFIED: `forge verify-contract … --chain 480 --etherscan-api-key DUMMY` prints "deployed on world", then "Invalid API Key".
- Commands:
  - `forge script script/Deploy.s.sol --rpc-url https://worldchain-mainnet.g.alchemy.com/public --broadcast --verify --chain 480 --etherscan-api-key $ETHERSCAN_API_KEY --private-key $DEPLOYER_PK`
  - After the fact: `forge verify-contract <addr> src/PopGuard.sol:PopGuard --chain 480 --etherscan-api-key $ETHERSCAN_API_KEY --constructor-args $(cast abi-encode "constructor(address)" <signer>) --watch`
- Keyless fallbacks (both VERIFIED reachable):
  - Blockscout at `https://worldchain-mainnet.explorer.alchemy.com`. It has an Etherscan-compatible `/api` that returns source without a key. Flags: `--verifier blockscout --verifier-url https://worldchain-mainnet.explorer.alchemy.com/api/`.
  - Sourcify supports 480 and 4801 (`sourcify.dev/server/chains`): `--verifier sourcify`.
  - These do NOT turn the Worldscan page green. Judges on worldscan.org need the Etherscan path.
- Public RPCs answering chainId 480: `worldchain-mainnet.g.alchemy.com/public`, `480.rpc.thirdweb.com`, `worldchain.drpc.org`. VERIFIED.
- Present on 480 (codesize > 0): CREATE2 deployer `0x4e59b448…956C`, Safe Singleton Factory `0x914d7Fec…43d7`, Multicall3 `0xcA11bde0…CA11`. VERIFIED. Safe 1.5.0 addresses are in safe.md.

**Still open (cheap to close)**
1. No real verify run yet (no key or funds in this session). Tonight, 10 min: get the Etherscan key, fund DEPLOYER, deploy `Counter` with `--verify`, and confirm the green check on worldscan.org.
2. CEX → World Chain ETH withdrawal is unconfirmed. Don't rely on it; use CEX → Base → Relay.

**Design impact:** both SAFE and POOL can target 480 with no schedule risk from funds or gas. Add `ETHERSCAN_API_KEY`, `DEPLOYER_PK` and `RELAYER_PK` to the env template. Put `--verify --chain 480` in every deploy script. Add a relayer balance check to server `/health`. Fund 0.01 ETH per key via Relay now.

## end-to-end-latency-budget

Status: partially resolved. The budget is built from measured parts. Phone-side DSP and prove times, and venue upload speed, are still unmeasured. The design calls below don't depend on them.

### Measured parts

| Stage | Time | Source |
|---|---|---|
| World ID hop, rp-context to our `/verify` (same-device, Android, one human, app already set up) | 27.7 s and 12.0 s | VERIFIED(`~/dev/worldid-spike/backend/logs/backend.log`: 00:43:32.0 to 00:43:59.8, 00:45:10.0 to 00:45:22.1) |
| Portal v4 `/verify` call | 1.02 s, 1.08 s | VERIFIED(same log, `POST /verify 200 (1022ms)`, `(1079ms)`) |
| Arm to t0 | fixed 3.0 s after the second arm | VERIFIED(docs/pop-contract.md §4, server/README.md test_arm_commit) |
| Capture | t0 - 1 s to t0 + 2 s. Commit allowed from t0 + 1.2 s. Transcript deadline t0 + 20 s, then retry | VERIFIED(pop-contract §4, server/README.md) |
| Clock sync | 10 x `GET /v1/time`, refuse if rtt_min > 300 ms. That's 0.5-3 s | VERIFIED(pop-contract §4.1). Time over a tunnel: UNVERIFIED |
| Server verdict | set as soon as the second transcript arrives (`combine()`), not gated on the recording or the proof | VERIFIED(server/README.md "POST /transcript checks...") |
| Recording upload | the phone uploads the capture WAV (~240 KB at 48 kHz, 2.5 s int16) **before** it long-polls for the verdict | VERIFIED(app RunFlow.kt `afterCapture`: `api.transcript` then `upload(k, cap)` then `waitNext`) |
| World Chain block time | 2.0 s on 4801 and 480 (100 blocks = 200 s). Sepolia blocks were near empty (1-3 txs) | VERIFIED(eth_getBlockByNumber on `worldchain-sepolia.g.alchemy.com/public` and mainnet, 2026-09-26: blocks 34929716 to 34929816, ts diff 200) |
| Option A proof size | 1,648,255 B (s48), 1.52 MB (s44) | VERIFIED(`ls -la server/data/zk/test/*.proof`, docs/pop-prover.md) |
| Option A prove, M2 | ~1 s key load + 0.4 s witness + 2.2-3.7 s prove, 1.9 GB peak. Phone: not measured | VERIFIED(docs/pop-prover.md), phone UNVERIFIED |
| Option A **server verify**, per proof | `popprover verify` reloads the 470 MB vk on every call. This dev Mac was under load (load avg 52 on 8 cores, 8 GB): 42.7 s and 47.4 s wall, with `vk_load_ms` 16.2-16.6 s, `verify_ms` 25.8-31.1 s, 6.5 s user CPU, 572 MB RSS. Idle machine: about 5-8 s (the test_zk.py header says the vk load alone is ~5 s) | VERIFIED(`popprover verify oa2t_s48.vk popt2_180ca04b_48k_A.proof ...public.json` run twice under `/usr/bin/time -l`, `RESULT verify ACCEPT`). Idle number UNVERIFIED |
| Auto-prove gate | the app starts the proof after NEAR only on an unmetered network (`startProof(ev, res, allowMetered = false)`). On cellular or a metered hotspot it doesn't start at all | VERIFIED(PopController.kt line ~477) |
| Proving key | 11.7 MB `.pk.zst` (s48) downloaded once, with Range resume | VERIFIED(docs/pop-prover.md) |

Not measured: tunnel upload of 1.6 MB. The cloudflared quick-tunnel experiment was blocked by the sandbox. Arithmetic: 1.6 MB takes 2.6 s at 5 Mbit/s up, 13 s at 1 Mbit/s, and 26 s at 0.5 Mbit/s (a congested venue). That's per phone, and both phones upload at once.

### Decisions

1. **The SAFE attestation (and the POOL presence leaf) is issued on the verdict alone.** It must not wait for option A ZK verification. The gate is NEAR + both World ID `/verify` ok + both phones' signatures over `safeTxHash`. Reasons:
   - Waiting would add phone prove time (unmeasured, likely 10-40 s, 1.9 GB peak), an upload of 1.6 MB x 2 (3-26 s), and a server verify of 5-8 s idle or ~45 s loaded, run twice. That's 20-100 s, with a real chance of stalling.
   - On a metered network the proof never starts.
   - The ZK proof runs afterwards and shows as a "ZK-verified" badge on the result screen and in the record. The pitch calls it "privacy-preserving evidence, checked after the fact". Don't put it on the guard's critical path.
   - An optional `requireZk` policy flag can exist but stays off for the demo.
2. **World ID hops run in parallel, one per human, before arm.** Nothing serializes them:
   - The action `pop:<sid>` and signal `sid+role` need only the session id.
   - Each human uses their own World ID phone.
   - The server keeps two independent rp-contexts, each with a 300 s TTL.
   - Start role A's hop right after session create, and role B's right after join. Enable "Confirm" only after that phone's own `/verify` succeeds. The server refuses `arm` until both roles have a verified nullifier and `nullifier_A != nullifier_B`.
   - Parallel wall time = the slower hop (~13-29 s, plus 5-10 s for cross-device QR, UNVERIFIED), instead of the sum (~26-65 s).
3. **Recording upload off for the demo.** Set `upload_recordings=false` in `/v1/config`, or move the upload after `waitNext`, so the ~240 KB doesn't sit between the verdict and the UI. This is an app/server change for the integrating workflow. Don't touch it from here.
4. **Relay:** the server relayer sends `execTransaction` right when the attestation and both owner signatures exist. Wait for the receipt with a 500 ms polling interval. viem's default can be seconds; set `pollingInterval: 500`. Expect inclusion in 1-4 s at 2 s blocks.
5. **Pre-warm before recording:** both phones enrolled with credentials, proving keys cached, the Safe deployed with the guard enabled and funded, the relayer funded, World ID apps unlocked (Face Auth not pending), and `require_user_presence=false`.

### Budget for one approval (parallel World ID, pre-warmed, attestation on verdict)

| Stage | Low | High | Notes |
|---|---|---|---|
| Propose tx, create session, show QR, guest scans, join | 5 s | 12 s | UNVERIFIED; join token TTL 120 s |
| World ID, both in parallel (incl. Portal verify) | 13 s | 35 s | measured 12-27 s + 1 s; cross-device +5-10 s |
| Both confirm | 1 s | 4 s | overlaps the end of the World ID step if the UI allows |
| Clock sync + arm + prepare audio | 1 s | 4 s | rtt over tunnel UNVERIFIED |
| arm to t0 to capture end (t0 + 2 s) | 5 s | 6 s | fixed by protocol |
| DSP self-check, commit, partner bed, measure, transcript | 1 s | 6 s | phone DSP time UNVERIFIED |
| Verdict to UI (recording upload off) | 0.2 s | 1 s | long-poll wakes within 100 ms |
| Owner signatures over `safeTxHash` + server attestation | 0.5 s | 2 s | the phones can pre-sign at confirm time |
| Relay + inclusion + receipt | 2 s | 5 s | 2 s blocks |
| **Total, happy path** | **~30 s** | **~75 s** | typical estimate ~45 s |

- A retry (attempt 1 after a glitch) adds about 8-12 s. The World ID step is reused within the same session.
- Sequential World ID instead of parallel adds another 13-35 s, for about 45-110 s.
- Waiting on ZK would add 20-100 s more.

### Does it fit the 4 min video without speed-ups?

Yes, with parallel World ID and a verdict-only attestation. Rules: 2-4 min, not sped up. VERIFIED(worldid-prize.md "Demo video"). Plan, 240 s:

| Segment | Time |
|---|---|
| Problem + product | ~35 s |
| Success path live (together, 30 cm, tx executes, explorer) | ~50 s |
| Failure path | ~40 s |
| Architecture / World ID + ZK badge | ~40 s |
| Close | ~15 s |
| **Total** | **~180 s**, leaving ~60 s slack |

For the failure path, the cheapest honest version is:
- attempt `execTransaction` without an attestation: an instant guard revert, 5 s;
- plus one "apart" run at 2 m: the full session to `NOT_NEAR too_far`, which never retries (VERIFIED server/README.md), about 35-50 s including a fresh World ID pair.

If the World ID step runs long, a hard cut (not a speed-up) during the wait is most likely allowed, but the rules as quoted don't address cuts (UNVERIFIED; ask ETHGlobal or show a visible clock).

Live finalist demo (4 min + Q&A): one success run fits. Do the failure path as the instant revert, or pre-record it.

### What remains, and the cheapest way to close it

1. **One instrumented dry run on the demo phones + tunnel.**
   - The server already stamps every request. Add an INFO log line with `ms` per route plus the session `seq` changes, or tail uvicorn access logs with timestamps.
   - Stages: create, join, rp-context A/B, verify A/B, confirm A/B, time pings, arm A/B, t0, commit A/B, transcript A/B, verdict, sign, relay send, receipt.
   - That gives every row above in one run, about 10 minutes of work.
2. **Phone prove time + RAM** (pixel/iPhone) via the app's existing prover bench (`benchStatus` in PopController). This matters only for the badge, not the gate.
3. **Server verify on an idle machine.** Rerun the `popprover verify` command above with nothing else running. If it's still >10 s, keep the vk resident: a long-lived verifier process instead of a subprocess per proof. That's for the integrating workflow.
4. **Venue uplink:** `curl -w '%{time_total}' --data-binary @proof -X POST <tunnel>/...` from a phone hotspot at the venue.

## laptop-wallet-phone-pop-handoff

**Status: resolved (spec + scratchpad prototype of all three codecs and one QR hop).** Blocks: pool.

**Decision: topology (b).** Note secrets, the payer's and the payee's, and all Groth16 proving live in a laptop wallet (`poolwallet`, TS: poseidon-lite + viem + snarkjs, per pool.md §7.1). Phones only do PoP + World ID, plus a byte check on a ctx they get **by QR from their own wallet**. No deep links: a laptop can't open an app on a phone. The server is not the channel either, because the server is who the ctx check guards against.

Why not (a), with the payee note on the phone:
- The app has no BN254 circomlib Poseidon. `zk/Poseidon7.kt` is x^7 over the P-256 field. VERIFIED(`server/pop/poseidon7.py:1-25`, `app/.../zk/`).
- The app has no keccak either. VERIFIED(grep: no hits in `app/composeApp/src/commonMain`, `build.gradle.kts`).
- The payee's later withdraw needs a BN254 prover the phone doesn't have (pool.md §7.3).
- So (a) costs a Kotlin Poseidon port, secret storage, and still an export to the laptop.
- (b) needs only sha256 (`Bytes.kt:86`) and the QR scan/render the app already has: iOS `CIQRCodeGenerator`/AVCapture, Android ZXing + ML Kit. VERIFIED(`Pairing.ios.kt:228-341`, `build.gradle.kts:133-137`).

**Supersedes two things:**
- **The phone check in "payee-cannot-verify-leaf".** `PoolCtx.check(payerTag, value, payeePre, …)` moves from the phone to the payee *wallet*. The phone only compares the ctx.
- **Its ctx formula.** The ctx becomes sha256, to match the sha256 nonce in "integration-freeze-point" WID-S.2:
  ```
  ctx_hash = sha256("enconomy/pool-xfer/v1" ‖ u256be(chainId) ‖ pool[20] ‖ u256be(leaf))
           = Solidity sha256(abi.encodePacked("enconomy/pool-xfer/v1", block.chainid, address(this), leaf))
  nonce    = sha256("enconomy/pop-nonce/v1" ‖ ctx_hash ‖ nonce_salt[32])   (server, unchanged from WID-S.2)
  ```
  VERIFIED: viem `sha256(encodePacked(['string','uint256','address','uint256'], …))` gives the same bytes as the raw concat.

**Where secrets live.**
- `payeeNullifier` and `payeeSecret` (31 random bytes each, < p) are born in the **payee wallet** and never leave it. File `wallet-<name>.json`: `{reqId, value, payeeNullifier, payeeSecret, label: LABEL_TRANSFER, status: pending|received(leafIndex)}`.
  - Write that file **before** showing `popreq1`. If the file is lost after the transfer, the funds are lost.
- The payer's note secrets stay in the payer wallet.
- Phones hold nothing pool-related beyond the session.
- The server sees only `leaf` and `ctx_hash`, never `value`, `payeePre` or `payerTag`. That's better than the pool.md §4.2 MVP channel.
- Demo: one laptop runs both wallet profiles (P and Q), so hops H1 and H2 are in-process. Only the two `popctx1` hops are physical. Say it on stage: "each party's wallet would be their own device".

**Message sequence** (WP/WQ = payer/payee wallet, PP/PQ = payer/payee phone, S = server):
```
H1 WQ → WP  popreq1  (QR or paste)      Q asks for value; hands payeePre
H2 WP → WQ  popoff1  (QR or paste)      P hands payerTag for that reqId
    WP and WQ each compute pc = P3(value, LABEL_TRANSFER, payeePre), leaf = P3(TAG_PRES, payerTag, pc), ctx.
    WQ uses ITS OWN value/payeePre. The two ctx must match (trivial on one laptop).
H3 WP → PP  popctx1 role=0 (QR, laptop screen → phone camera)
H4 WQ → PQ  popctx1 role=1 (QR)          PQ stores expectedCtx before joining
H5 PP → S   POST /v1/session {context: ctx_hex, consumer: {kind:"pool-xfer", chain_id:480, address:pool, leaf:"0x…"}}
            S recomputes ctx from (chain_id, address, leaf); mismatch → 400 context_mismatch
H6 PP → PQ  pop1 invite (existing QR/NFC, Invite.kt)
H7 both phones, at confirm (view has context + nonce_salt + nonce):
            require view.context == sha256-ctx(expected popctx1) && nonce == sha256(tag‖context‖salt) && now < expiresAt
            else refuse Confirm + no IDKit: context_mismatch / expired. UI: "pay|receive <value> ETH" from the QR.
H8 World ID ×2, audio, verdict NEAR → S calls pool.postPresence(leaf) (tier 1)
H9 WP watches PresencePosted(leaf) on chain (it knows leaf; no session id needed) → proves → relayer
H10 WQ watches LeafInserted(pc) → status=received. Withdraw later from WQ.
```

**Byte layouts.** All big-endian. Text is `<prefix>` + base64url, no padding (same as `Invite.toQr`).

| prefix | bytes | layout |
|---|---|---|
| `popreq1:` | 97 | `"PRQ1"`4 · ver 0x01 1 · chainId u32 4 · pool 20 · value u128 16 · payeePre 32 (< p) · expiresAt u32 4 · reqId 16 |
| `popoff1:` | 53 | `"POF1"`4 · ver 0x01 1 · reqId 16 · payerTag 32 |
| `popctx1:` | 82 | `"PCX1"`4 · ver 0x01 1 · role 1 (0 payer/host, 1 payee/guest) · chainId u32 4 · pool 20 · leaf 32 · value u128 16 (display only; bound via leaf) · expiresAt u32 4 |

- `popctx1` carries the `leaf`, not the ctx. The phone derives the ctx with sha256, and the host phone passes the `leaf` to S in H5.
- Measured QR sizes, EC level M: popreq1 = 138 chars, v8 (49 modules); popoff1 = 79 chars, v5; popctx1 = 118 chars, v6 (41 modules). VERIFIED(prototype).

**Prototype.** VERIFIED(`node hop.cjs` in `scratchpad/handoff/`, qrcode 1.5.4 + jsQR 1.4.0 + pngjs, poseidon-lite from `scratchpad/pool`):
- WQ/WP ctx agree.
- `popctx1` rendered as a 180×180 PNG (4 px/module) and decoded back byte-equal.
- Phone check results:
  - honest → CONFIRM;
  - server binds a leaf paying sybil R → REFUSE ctx;
  - right ctx, foreign nonce → REFUSE nonce;
  - payer alters value → REFUSE ctx.
- Test vector (payerTag=5, value=1200, payeePre=7, chain 480, pool 0x11…11):
  - leaf `11011320419327886381298776674271937664568292783180157783978689262892574625042`
  - ctx `cf4c10abd582fb22574cfd97ff9000a4b36746734473e5d9f3720daa04db9749`
  - nonce(salt=0×32) `96a5248cb17d236856879409a37539cd1fc0137c354d2494526d662ab62ab062`
  - popctx1 (expiresAt 1790000000) `popctx1:UENYMQEBAAAB4BERERERERERERERERERERERERERGFgvvkP_AwdXQ2-zyoUW5cZZ01Vqg2EPrDDGbPEszRIAAAAAAAAAAAAAAAAAAASwarE7gA`

**Not tested:**
- A real phone camera reading a laptop screen. Cheapest check: open `popctx1.png` fullscreen and scan it with the existing Android/iOS scanner screen. It's a v6 code, far smaller than typical pairing QRs, so expected fine.
- Kotlin decode parity. Cheapest check: port `decCtx` + the ctx/nonce check to `commonTest` and pin the test vector above.

**Implementer checklist:**
- **app:**
  - `PopController.onQrText` currently drops everything but `pop1:` (line ~386). Dispatch `popctx1:` into a new `PoolCtx` codec (commonMain, sha256 only). Store `expectedCtx` and clear it at session end or on expiry.
  - `host()`: if an `expectedCtx` with role 0 is set, send `context` + `consumer`.
  - Confirm gate is the H7 check. It replaces the WID-A.2 generic check when a context exists. A session with a context but no scanned `popctx1` → prompt "scan your wallet's code".
- **server** (extends WID-S.1):
  - `SessionIn.consumer: {kind, chain_id, address, leaf} | None`.
  - For `kind == "pool-xfer"`, recompute the ctx with hashlib and reject a mismatch.
  - Keep the `leaf` in the session doc and record for the poster.
  - Refuse a second NEAR-bound session for the same ctx. A re-post would revert `LeafAlreadyExists` anyway.
- **wallet** (laptop CLI/webpage):
  - `request`: popreq1 out, secrets persisted.
  - `offer`: popreq1 in → popoff1 out.
  - `ctx`: popoff1 in → verify → popctx1 QR on screen.
  - `watch` → `prove` → `relay`.
  - Reject `payeePre ≥ p`, expired codes, and reqId mismatch.
- **Alternative, not chosen:** S signs an attestation over the ctx, and the wallet submits `postPresence(leaf, att)` itself, with the contract recomputing the ctx. That keeps the server pool-agnostic, but it needs a signed-attestation verifier in the pool contract plus a lookup-by-ctx endpoint. Revisit only for tier 2.

---

## owner-device-registry

Status: RESOLVED (design + fork-tested prototype). Needs one server change (attestation carries device ids) and one demo-ops rule (never re-enroll / wipe the server DB after Safe creation without running the rotate path).

Prototype (scratchpad, temporary; copy before it's gone): `/private/tmp/claude-501/-Users-takahiro-ogawa-dev-enconomy/3d9dd236-bf59-4c81-91f5-6bb7c5ebc6e3/scratchpad/devreg/` — `src/PopSafeGuard.sol` (guard + `PopSafeSetup`), `test/DeviceRegistry.t.sol`, `test/Vector.t.sol`, `script/CreatePopSafe.s.sol`. `forge test` → 5/5 PASS on forks of 4801 (SafeL2 1.4.1, Safe 1.5.0) and 480 (SafeL2 1.5.0). VERIFIED(forge 1.4.3, solc 0.8.28 via-IR, osaka).

### Answer in one paragraph

The server attestation carries the two device ids; the guard holds a per-Safe allowlist `deviceOwner[safe][dev] => owner`. A tx passes only if both attested devices are registered to **two different current Safe owners**. Devices are registered in the **same tx that creates the Safe** (a delegatecall helper in `Safe.setup` writes the guard slot and calls `guard.initSafe` as the Safe). A reinstall produces a new key and locks that owner's phone out; it is fixed by (1) **re-enroll by meeting**: the new phone runs a PoP session with a co-owner's still-registered phone, and the only tx allowed with one unknown device is `replaceDevice(old,new)`/`addDevice(new, otherOwner)` for exactly that device; or (2) when no registered phone is left, the **timelocked escape hatch**: an owner calls `announce(safe, safeTxHash)`, after `delay` that exact tx runs without PoP, but only if it is a recovery call (device admin, issuer rotation, owner management, `setGuard(0)`).

### Why the device id must come from the server attestation (not the transcript, not World ID)

- The server already knows both keys: result record `devices.{A,B}.pubkey` (hex65) and it enforces `transcript.pk_self == enrolled key` and `A.pk_partner == B.pk_self` (`docs/pop-contract.md` §8.4 L444, check table L391/L394). VERIFIED(read).
- `device_id = hex(sha256(pubkey65)[:16])` (contract §2.1 L39). Onchain id = **full `sha256(pubkey65)`** (32 bytes; its first 16 bytes are the server `device_id`). The guard never needs the key itself.
- Tier-2 (guard re-verifies both POPT signatures onchain, ~2×7.6k gas + 2×311 B calldata) proves only that the devices signed *some* session with that nonce; the NEAR verdict is still the server's word. Not worth it for the hackathon. Optional later.
- World ID cannot bind owners: v4 nullifiers are one-time per (human, rp, action) ("Authenticators will not issue a nullifier more than once"), so an enrollment nullifier can't be matched later. VERIFIED(`research/worldid/notes/worldid.md` §1.4, §3). Session proofs give continuity but not uniqueness and are untested with PoH (UNVERIFIED) → not used for the registry. World ID stays per-tx "two distinct humans" (pair_tag), bound in the attestation digest.

### Attestation v2 (replaces safe.md §6.1 "POP1")

```
tail (last 172 bytes of execTransaction.signatures, after owner sigs and any 1271 dynamic parts):
  pairTag(32) ‖ devA(32) ‖ devB(32) ‖ expiry(u64 BE, 8) ‖ r(32) ‖ s(32) ‖ "POP2"(4)
digest = sha256("pop-safe-v2" ‖ uint256 chainId(32) ‖ address safe(20) ‖ safeTxHash(32)
                ‖ pairTag(32) ‖ devA(32) ‖ devB(32) ‖ uint64 expiry(8))          // 199-byte preimage
sig    = P-256 ECDSA(POP_ATTEST_KEY, prehashed digest), raw r‖s
devA   = sha256(bytes.fromhex(record.devices.A.pubkey)), devB likewise (role order; guard is order-agnostic)
```

Pinned vector (Solidity `guard.digest` == Python hashlib, VERIFIED `test/Vector.t.sol`):
`chainId=480, safe=0x1111…1111, safeTxHash=0x…22, pairTag=0x…33, devA=0x…44, devB=0x…55, expiry=1790000000` → `0x923a0f96071090da810c42c7f0c43c56fefd454497a45fcde7138b1a45829720`.

Server: sign only when verdict NEAR, final attempt, session `purpose.safe_tx_hash` matches, and (World ID policy) both human results passed. It does **not** need to know the Safe's device list; the guard enforces membership.

### Guard storage and rules (`PopSafeGuard`, one instance serves many Safes, state keyed by `msg.sender`)

```solidity
struct Cfg { uint256 qx; uint256 qy; uint32 delay; bool init; }
mapping(address => Cfg) public cfg;                                   // safe => issuer key, escape delay
mapping(address => mapping(bytes32 => address)) public deviceOwner;   // safe => sha256(pubkey65) => owner
mapping(address => mapping(bytes32 => uint256)) public readyAt;       // safe => safeTxHash => unlock time

function initSafe(uint256 qx, uint256 qy, uint32 delay, bytes32[] devs, address[] owners) external; // once, msg.sender = safe
function addDevice(bytes32 dev, address owner) external;      // onlySafe; owner must be isOwner
function removeDevice(bytes32 dev) external;                  // onlySafe
function replaceDevice(bytes32 oldDev, bytes32 newDev) external; // onlySafe; keeps the owner
function setIssuer(uint256 qx, uint256 qy) external;           // onlySafe
function announce(address safe, bytes32 safeTxHash) external;  // caller must be an owner of safe
function cancel(bytes32 safeTxHash) external;                  // onlySafe (a PoP-gated veto)
```

`checkTransaction` order:
1. `operation == DELEGATECALL` only to MultiSendCallOnly 1.4.1 `0x9641…02e2` / 1.5.0 `0xA83c…1836`.
2. `h = getTransactionHash(..., nonce()-1)`.
3. If `readyAt[safe][h] != 0`: revert `TooEarly` before it; else allow only recovery calls — `to == guard` with `addDevice|removeDevice|replaceDevice|setIssuer`, or `to == safe` with `setGuard(0)` (0xe19a9dd9, arg must be 0), `swapOwner` 0xe318b52b, `addOwnerWithThreshold` 0x0d582f13, `removeOwner` 0xf8dc5dd9, `changeThreshold` 0x694e80c3 (selectors VERIFIED `test_selectors`); value 0, CALL. Anything else `NotRecoveryTx`. Owner signatures are still required by Safe itself.
4. Else parse/verify the POP2 tail (P-256 precompile `0x100`), expiry, `devA != devB`.
5. Both registered → owners must differ (`SameOwner`) and both still `isOwner` (removing an owner silently disables their phones).
6. Exactly one unknown → allowed only if the tx is `guard.addDevice(unknownDev, o)` or `guard.replaceDevice(old, unknownDev)` and the slot's owner ≠ the known device's owner (a co-owner witnesses in person). Else `UnknownDevice`.
7. Both unknown → `UnknownDevice`.

### Setup tx (one tx, no guard-less window)

`SafeProxyFactory.createProxyWithNonce(singleton, Safe.setup(owners, 2, to=PopSafeSetup, data=PopSafeSetup.setup(guard, qx, qy, delay, devs, owners), fallbackHandler, 0,0,0), salt)`. `Safe.setup` runs `setupOwners` before the `to/data` delegatecall, so `initSafe` can check `isOwner`. `PopSafeSetup.setup` does `sstore(GUARD_SLOT, guard)` then `guard.initSafe(...)` (a CALL from delegatecall context ⇒ `msg.sender == safe`). VERIFIED(fork tests read the guard slot after creation; 419–429k gas incl. proxy).
- Script: `script/CreatePopSafe.s.sol`, env `OWNER_A/B, PUB_A/B (hex65 from the PoP session view/result), ISSUER_X/Y, DELAY, FACTORY, SINGLETON, FALLBACK, SALT, [GUARD, SETUP]`. Dry-run on a 480 fork with SafeL2 1.5.0 `0xEdd1…7C7e`, factory `0x14F2…5e7b`, handler `0x3EfC…77f4`: SIMULATION COMPLETE, ~2.46M gas incl. deploying guard+helper. VERIFIED(`forge script --fork-url https://worldchain-mainnet.g.alchemy.com/public`).
- App flow: "Create shared wallet" = run one PoP session between the two phones (founding meeting), read both `pubkey`s from the session view, then the relayer sends the create tx. Owners array index i ↔ devs index i.

### Fork-tested scenarios (all PASS on 1.4.1 L2 / 1.5.0 / 1.5.0 L2)

| # | Scenario | Result |
|---|---|---|
| 1 | owners' registered phones A,B met, either role order | executes (~105–117k gas measured in test harness, incl. cold storage) |
| 2 | two strangers' enrolled phones, valid issuer sig | `UnknownDevice` |
| 3 | phone A + stranger, spend | `UnknownDevice` |
| 4 | owner A holds two registered phones | `SameOwner` |
| 5 | **A reinstalls → new key** | spend `UnknownDevice` (locked for A) |
| 6 | new A meets registered B, `replaceDevice(oldA,newA)` | executes (~97–109k); old key deleted; spend works again. Stranger trying `addDevice(stranger, ownerB)` with witness B → `SameOwner`; wrong device in calldata → `UnknownDevice` |
| 7 | **both phones reinstalled** | non-owner `announce` → `NotOwner`; before delay `TooEarly`; announced *spend* after delay → `NotRecoveryTx`; announced `replaceDevice` ×2 (nonces n, n+1 announced together) execute; new phones spend |
| 8 | owner o3 removed via `removeOwner` | o3's registered phone → `UnknownDevice` |
| 9 | announce + delay, `setGuard(0)` | guard slot cleared (full escape) |

### What reinstall actually does to keys (facts for the demo runbook)

- **Every Enroll rotates the key.** `PopController.enroll()` calls `keystore.generate()`, which calls `delete()` first on both platforms. `forgetKey()` deletes too. VERIFIED(app/.../PopController.kt L211–266, AndroidDeviceKeystore.kt `generate`, DeviceKeystore.ios.kt `generate`).
- **Server DB loss also rotates keys.** A signed call that gets `auth_unknown_device` sends the app to the Enroll screen, and Enroll generates a new key (PopController.kt L196–197). Android cannot re-enroll the old key anyway: its attestation challenge is fixed at keygen, the server wants a fresh nonce. ⇒ Back up `server/data/pop.sqlite` (`POP_DB`) and never wipe it after a Safe is created. VERIFIED(code read, server/pop/main.py L72).
- **Android uninstall / Clear data deletes Keystore keys.** VERIFIED([developer.android.com restore-credentials](https://developer.android.com/agents/skills/identity/restore-credentials/skill); [Keystore system](https://developer.android.com/privacy-and-security/keystore)).
- **iOS uninstall:** keychain items (incl. the SE key, tag `pop-device-v1`) usually survive app deletion ([Apple forums 72271](https://developer.apple.com/forums/thread/72271?page=2), not an Apple guarantee — UNVERIFIED for current iOS), but `Prefs` are wiped, `storedEnrollment()` returns null, the user hits Enroll, and `generate()` deletes the old key. Same outcome: new key. `AfterFirstUnlockThisDeviceOnly` ⇒ no backup/migration to a new phone.
- So "key lost" is the normal case, not an edge case. Everything in app storage (device key, holder secret, any in-app owner key) is lost together.

### Owner keys vs device keys (decide in the design doc)

- If Safe owners are `P256Owner(device key)` (safe.md §6.2), losing the phone also loses the owner key. In a 2-of-2 that is unrecoverable even with the escape hatch (Safe still needs 2 owner sigs). Rule: **either** owners are separate keys that survive reinstall (external wallet / backed-up EOA), **or** use 2-of-3 with a recovery owner (team laptop EOA, no registered device), so recovery = recovery owner + surviving owner sign `swapOwner` + `replaceDevice` via the hatch.
- The guard does not check that the two present devices' owners are among the signers. With a recovery owner that means "both humans' phones were together, any 2 owners signed". Optional stricter rule: parse the signer set (`checkNSignatures` / ecrecover) and require it ⊇ {owner(devA), owner(devB)}. Not implemented.

### Demo runbook items

- Create the Safe **after** final app installs on both demo phones. If anything reinstalls: run scenario 6 (meet a registered phone) — takes one PoP session + one tx.
- Demo `delay`: 300 s (show the hatch live) or 1 day; production 7 days.
- Onchain device hashes link the Safe to its phones across txs. Fine for SAFE; do not reuse this pattern for POOL.

### Remaining unknowns and cheapest check

1. Server attestation endpoint with `devA/devB` + `purpose.safe_tx_hash`: owned by the server workflow; hand them the digest spec + vector above.
2. Live gas on 480 for spend with registry (test numbers include harness overhead): deploy and `cast estimate` once.
3. Whether `announce` should also be callable by `P256Owner` contracts (they can't send txs): add a forwarding method on P256Owner, or let the relayer announce with an owner's P-256 signature. Only matters if owners are device-bound.

## tx-composition-ux

**Status: resolved (decision + prototype, hash parity verified in 3 languages).** Blocks: safe.

**Decision: the host phone composes the SafeTx. The server relays it. The guest phone recomputes everything and shows the decoded transfer on the existing Confirm screen.** No laptop composer, no CLI, no Safe Tx Service, no Safe{Wallet} UI. The laptop is optional and read-only: a projector page showing Safe balance, the pending tx, the verdict and the explorer link.

Why the phone, not a laptop dApp:
- The host phone already creates the session (`POST /v1/session`, signed) and shows the `pop1` QR. If it also builds the tx, the context exists before pairing with no extra hop. A laptop composer needs a new unsigned "proposal" endpoint, a proposal-to-session link, and a second QR. That's more moving parts and more to fake.
- The trust anchor is the phone anyway. Whatever composes the tx, each phone must recompute `safeTxHash` itself. So a laptop adds nothing to security.
- The `pop1` invite stays **49 bytes, unchanged**. The tx never goes in a QR; it travels in the session `context`.
- The CLI (`cast`) is only a dev fallback for making test sessions.

### Flow (SAFE, 2-of-2, chain C, Safe S)

1. **Host, "New payment" screen.** Pick a Safe from "My Safes" (a local list set up at Safe creation or import: `{chainId, safe, label}`). Then pick an asset from the app's token table for that chainId, a recipient (paste or scan an address), and an amount.
2. **Host reads state.** It reads `nonce()` (selector `0xaffed0e0`) and the balance by JSON-RPC `eth_call` / `eth_getBalance`, straight from the public RPC with ktor (480 `https://worldchain-mainnet.g.alchemy.com/public`, 4801 `https://worldchain-sepolia.g.alchemy.com/public`).
   - A lying nonce source can't redirect funds. The worst case is a hash that never executes. So routing the nonce through our server is also acceptable.
3. **Host builds the SafeTx.**
   - Fields: `operation=0`, `safeTxGas=baseGas=gasPrice=0`, `gasToken=refundReceiver=0x0`.
   - ETH: `to=recipient`, `value=wei`, `data=0x`.
   - ERC-20: `to=token`, `value=0`, `data=a9059cbb ‖ word(recipient) ‖ word(amount)`.
   - It computes `safeTxHash` locally (code below).
4. **Host creates the session.** `POST /v1/session` with:
   ```json
   {"context": {"kind": "safe-tx", "chain_id": 480, "consumer": "0x<safe>", "ctx_hash": "0x<safeTxHash>",
     "safe_tx": {"to": "0x..", "value": "dec", "data": "0x..", "operation": 0, "safe_tx_gas": "0", "base_gas": "0",
                 "gas_price": "0", "gas_token": "0x0..0", "refund_receiver": "0x0..0", "nonce": "dec"}}}
   ```
   - The server recomputes `safeTxHash` from `safe_tx` and rejects a mismatch (`context_mismatch`).
   - It stores `not_before = now_s`.
   - It sets `nonce_hex = keccak256(abi.encode(keccak256("pop-ctx-v1"), uint256 chainId, address consumer, bytes32 ctxHash, uint64 notBefore, bytes16 sessionId))` (bridge.md §4) instead of `token_hex(32)`.
   - This is a server change owned by the other workflow; this section is the spec for it.
5. **Guest scans `pop1` and joins.** `GET /v1/session/{id}` returns `context` + `not_before` to both roles.
6. **Confirm screen (both phones), before the Confirm button is enabled:**
   - `context.chain_id` must equal an app-known chain, and `context.consumer` must be in the local "My Safes" list. Otherwise: `unknown_safe`.
   - Recompute `safeTxHash` from `context.safe_tx` and require it to equal `context.ctx_hash`. Otherwise: `context_mismatch`.
   - `decode()` must not return `Refused` (rules below).
   - Only then render the approval card and enable Confirm:
     ```
     Approve from Safe 0x3fAD…03dc (World Chain)
     Send 1.5 WLD to 0x2222…2222
     Safe nonce 7 · tx 0x3204…a3ce
     ```
     Show the full recipient address on tap, and the first and last 4 bytes of the hash so the two people can read them to each other.
7. **Right after the confirm response reveals `nonce`**, and before the World ID request, clock sync, arm, or any POPC/POPT signature: recompute `popCtxNonce(chainId, safe, safeTxHash, not_before, session_id)` and require it to equal `nonce`. Otherwise abort with `context_mismatch`.
   - This has to happen after confirm, not before, because `nonce` is hidden until `confirmed` (pop-contract §3.3). That's harmless: nothing is signed between Confirm and this check.
8. **After NEAR**, each phone signs **its own recomputed `safeTxHash`**, never a digest from the server (owner key per mobile-wallet.md §3.2). The server or relayer assembles `ownerSigs ‖ popTail` and calls `execTransaction`. Both phones then show the tx link.

Result: the phone never signs a server-supplied digest blindly. Every signed thing (POPC/POPT nonce, World ID signal `encodePacked(nonce, role)`, owner signature) traces back to fields the phone decoded and displayed.

### Decoder rules (allowlist; anything else is refused, never shown as raw hex)

| Case | Condition | Display |
|---|---|---|
| native transfer | `data` empty, `op=0` | `Send <formatUnits(value,18)> ETH to <to>` |
| ERC-20 transfer | `to` in the app token table for chainId, `data.len==68`, selector `a9059cbb`, address word's top 12 bytes zero, `value==0` | `Send <amount/10^dec> <SYM> to <rcpt>` |
| Safe admin | `to == safe`, canonical length. Allowed: `setGuard 0xe19a9dd9`, `setModuleGuard 0xe068df37`, `addOwnerWithThreshold 0x0d582f13`, `changeThreshold 0x694e80c3` | `Safe settings: setGuard(0x…)` in warning colour |
| refused | `operation != 0`; any of safeTxGas/baseGas/gasPrice ≠ 0 or gasToken/refundReceiver ≠ 0 (a nonzero gasPrice + refundReceiver lets the executor drain the Safe through the refund); value together with calldata; unknown selector; self-call to `enableModule 0x610b5925`, `setFallbackHandler 0xf08a0323`, `removeOwner 0xf8dc5dd9`, `swapOwner 0xe318b52b`, `disableModule 0xe009cfde` (these bypass or weaken the guard, safe.md §4.2); non-canonical ABI (extra bytes, dirty address padding) | error card with the code, Confirm stays disabled |

Token table, app constant per chainId:
- 480:
  - WLD `0x2cFc85d8E48F8EAB294be644d9E25C3030863003`, 18 decimals. VERIFIED(`cast call … symbol()/decimals()` on 480 → "WLD"/18)
  - USDC `0x79A02482A880bCE3F13e09Da970dC34db4CD24d1`, 6 decimals. VERIFIED(same → "USDC"/6)
- 4801: native ETH only, unless we deploy a MockERC20 (then add its address). WLD/USDC on 4801: UNVERIFIED, not looked up.
- Never read symbol or decimals from the server or from an arbitrary token contract at display time; a contract can return any symbol.

The admin entries are needed because the Safe's first transactions (`setGuard(PopGuard)`, and on 1.5.0 `setModuleGuard`) go through the same flow. Removing the guard (`setGuard(0)`) goes through the escape-hatch path (safe.md §4.1), not through this screen.

### Hash code: verified parity

`SafeTx.safeTxHash()`:
```
domainSeparator = keccak256(0x47e79534…69218 ‖ uint256 chainId ‖ word(safe))
structHash      = keccak256(0xbb8310d4…286d8 ‖ word(to) ‖ uint256 value ‖ keccak256(data) ‖ uint256 operation ‖
                            uint256 safeTxGas ‖ uint256 baseGas ‖ uint256 gasPrice ‖ word(gasToken) ‖ word(refundReceiver) ‖ uint256 nonce)
safeTxHash      = keccak256(0x19 ‖ 0x01 ‖ domainSeparator ‖ structHash)
```
The same for Safe 1.3.0+, 1.4.1 and 1.5.0. VERIFIED: protocol-kit gives the same hash for version "1.4.1" and "1.5.0" on the all-fields vector below.

Prototype: `scratchpad/txux/kt/src/commonMain/kotlin/SafeTx.kt`. It is pure commonMain Kotlin with no dependencies, so it also runs on iOS/Native:
- Keccak-256 (about 45 lines)
- decimal ↔ uint256 conversion without BigInteger
- `SafeTx`, `popCtxNonce`, and `decode` (the allowlist above)

Tests are in `src/commonTest/kotlin/SafeTxTest.kt`, 9/9 pass (`JAVA_HOME=<jdk21> ./gradlew jvmTest`; Gradle 8.14 fails on the default JDK 26, so use Homebrew openjdk@21). The scratchpad is temporary; the vectors are the durable part:

| # | tx (Safe `0x3fad7600f309b0c3d60a57023b0262460b0603dc`, a live SafeL2 1.4.1 proxy on 480) | safeTxHash |
|---|---|---|
| 1 | chain 480, nonce 0, to `0x1111…1111`, value 1e16, data `0x` | `0x960376ecf47efc7cff7bfae13f9f9f1f678c1429cb6489486a3ef315df1f59a5` |
| 2 | chain 480, nonce 0, to WLD, `transfer(0x2222…2222, 1.5e18)` | `0x320418179acf57e8607ddcb3f82e113cb45d0d7579b95ccb81ee04afc056a3ce` |
| 3 | chain 480, nonce 0, to = safe, `setGuard(0x3333…3333)` | `0x29e1fbc2114cbf3e89bf83db0a08b3faf7b502b2fc6d60691e0fcf132df7c2f7` |
| 4 | chain 480, nonce 42, to `0xA83c…1836`, value 123456789, data `0xdeadbeef00`, op 1, safeTxGas 50000, baseGas 21000, gasPrice 7, gasToken USDC, refundReceiver `0x4444…4444` | `0x321d09105a40b0d115e6f2b294208a0fac9eb117f88c3d7ca5e036484aa591e1` |
| 5 | same as 4 but chain 4801 | `0xb0bcdc64af0c7fe223a8b673357104673dc659be0b9c98a9970d932a3c8cb2ac` |
| N | `popCtxNonce(480, safe, hash#1, notBefore=1790000000, sid=0x00112233445566778899aabbccddeeff)` | `0x9fc7507c663ae43d4f8d56ba4b805fdf9e928e565141666a47630aa7fd04b121` |

Verification per row:
- Rows 1–4 match three ways: onchain `getTransactionHash(...)` via `eth_call` on 480, `@safe-global/protocol-kit@8.0.7` `calculateSafeTransactionHash`, and the Kotlin prototype. VERIFIED(`scratchpad/txux/js/vec.mjs`, `vec2.mjs`; viem 2.56.8).
- Row 5 matches between protocol-kit and Kotlin.
- Row N matches between Kotlin, `cast keccak $(cast abi-encode "f(bytes32,uint256,address,bytes32,uint64,bytes16)" …)` and Python. VERIFIED.
- Python (server-side port, `scratchpad/txux/safetx.py`) asserts rows 1, 4 and N. VERIFIED.

Two gotchas to pin in the implementation:
- **Server trap:** Python `hashlib.sha3_256` is **not** Keccak-256. `sha3_256(b"")` is `a7ffc6f8…`, while keccak is `c5d24601…`. VERIFIED(run). The server has no keccak dependency today (`server/pyproject.toml`: fastapi, cryptography, numpy, cbor2). Add `pycryptodome` (`from Crypto.Hash import keccak`) or `eth-hash[pycryptodome]`.
- **`bytes16` in `abi.encode` is right-padded** (`sid ‖ 16 zero bytes`); `uint64` is left-padded. Both are covered by row N.

### Implementer checklist

- **app (commonMain):**
  - Add `safe/SafeTx.kt`: port the prototype file as is, and copy the vectors table into `commonTest`.
  - Add a `MySafes` store (`{chainId, safe, label}`) and a per-chain `TokenTable`.
  - Add a "New payment" screen (host), a `ctx` field on `createSession()` (`PopApi.kt:240` currently sends `"{}"`), a `context`/`not_before` pair on `SessionView`, and the approval card plus pre-Confirm gate in `App.kt` `Confirm()` (L178).
  - Add the post-confirm nonce gate in `PopController.confirmPartner()` (L428), before World ID and arm.
  - New error codes: `unknown_safe`, `context_mismatch`, `refused_<reason>`.
- **server:**
  - `POST /v1/session` accepts `context`, recomputes the hash, and derives the nonce (`sessions.py:142`).
  - `GET /v1/session/{id}` returns `context` and `not_before` from `joined` on, not only after confirm.
  - The same recompute runs again before signing the PoP attestation and before relaying `execTransaction`.
- **Optional laptop page:** a read-only `GET /demo/safe/{chain}/{safe}` that polls the session and shows the balance, the decoded pending tx, the verdict and the tx link. It's for the audience, not a trust surface.

### What remains
- Whether the owner signature is a secp256k1 EOA or a P-256 `P256Owner` doesn't change this flow. Both sign the phone's own `safeTxHash`.
- Not tested on a device: the Kotlin/Native (iOS) build of `SafeTx.kt`. The code only uses `Long`/`ByteArray` and stdlib `rotateLeft`, so the risk is low. The cheapest check is `./gradlew :composeApp:iosSimulatorArm64Test` once the file lands in `app/`.

## visible-failure-path

**Status: resolved (forge fork test on 480 + anvil-fork broadcast).** Blocks: pool.

**Answer.** Show two failures, in this order. The main one ends as a red tx on the explorer. The second one is a World ID rejection on the phone.

**F1, main: "they never met, the payer tries anyway" → onchain revert `UnknownPresenceRoot(root)`.**
1. Phones 2 m apart. Server says NOT_NEAR `too_far` (server/pop/verdict.py). No `postPresence`, so no new `PresencePosted` event. Show the pool's Events tab: count unchanged.
2. The payer wallet has a **"Send anyway"** button. It builds its own local presence tree with its own leaf in it, and proves `PresenceTransfer` against that root. The proof is *valid* (show `snarkjs groth16 verify` → OK on screen). The circuit only proves membership in *some* root. The chain's job is to check that the root was posted by the attester.
3. The relayer sends it **without simulation** (fixed gas limit). The tx mines with status 0 and the error `UnknownPresenceRoot(uint256)`, selector `0xfed58dd0`, arg = the fake root.
4. Why this isn't fake: it's exactly what a cheating payer would do. The proof is real. Only the missing meeting makes it fail.

Measured, VERIFIED (scratchpad `vfail/`; `forge test --fork-url https://worldchain-mainnet.g.alchemy.com/public`, chain id 480; the real V2 proof from `pool/privacy-pools-core/packages/circuits/pres/outT`):

| test | result |
|---|---|
| F1: proof verifies (`verifyProof` true), root not posted | revert `UnknownPresenceRoot(8123…3933)` |
| S: attester posts root, then transfer | ok, 275,594 gas in test; 297,717 gasUsed as a tx |
| F2: root posted, `payeeCommitment` edited (pay someone else) | revert `InvalidProof()` (`0x09bde339`) |
| F3: same proof twice | revert `NullifierAlreadySpent(nh)` (`0x9c7bbc21`) |
| F4: non-attester posts presence | revert `NotAttester()` |

Anvil fork of 480, real broadcast, VERIFIED:
- `cast estimate` → `execution reverted: custom error 0xfed58dd0: 11f5…397d`. A normal relayer would refuse to send.
- `cast send --gas-limit 600000` → mined, **status 0x0, gasUsed 38,850**. The root check runs before the pairing, so a failed tx costs about 39k gas, about 6e-8 ETH at 0.0015 gwei.
- Then `postPresenceRoot` status 1 (68,824 gas) → the same transfer status 1 (297,717) → replay status 0 (38,850).

**Contract rules (the PresencePool must follow them):**
- Use custom errors, not `require` strings. Names and args:
  - `InvalidContext(uint256 got, uint256 want)`
  - `UnknownStateRoot(uint256)`
  - `UnknownPresenceRoot(uint256)`
  - `NullifierAlreadySpent(uint256)`
  - `InvalidProof()`
  - `NotAttester()`
- Check order in `transfer`: context → state root → **presence root** → nullifier → `verifyProof`. That order makes F1 cheap and gives it its specific name.
- `InvalidProof` is generic on purpose. The chain can't tell "wrong payee" from junk, so don't demo F2 as the headline.
- Verify the pool on Worldscan (Etherscan API V2, `chainid=480`; see mainnet-480-ops). That way the tx page decodes the error name. Etherscan shows reverts as "Fail with Custom Error '…'" for verified contracts. VERIFIED ([etherscan announcement](https://x.com/etherscan/status/1452955443991494661)). That it works the same on worldscan.org for an L2 tx: UNVERIFIED. The cheapest check is one reverted tx after the first deploy. Fallback: the Blockscout explorer (`worldchain-mainnet.explorer.alchemy.com`), plus the wallet decoding the revert via the ABI and showing "No meeting on record for this payment".

**Relayer rule.** Normal mode is `eth_estimateGas` first. On a revert, return `{error: "UnknownPresenceRoot", data}` and don't broadcast. Demo mode is `POST /relay {…, force: true}`, enabled only by the env `RELAY_ALLOW_FORCE=1`: send with `gas=600000`, return the tx hash, and let the wallet open `worldscan.org/tx/<hash>`. Never enable force in a non-demo deploy (it burns about 39k gas per call; trivial on 480, but it's a grief vector).

**F2, secondary: same human on both phones → rejected before any audio.**
- Nullifiers are deterministic per (human, rp, action). With `action = pop:<sid>` the same human gives the same nullifier on both phones.
- **Unknown-unknown found:** World App itself refuses a second proof for an action whose nullifier has already been verified. IDKit returns the error `nullifier_replayed`. VERIFIED: the idkit arena case `error_nullifier_replayed` ("Verifies once for a stable action, then requests another proof for it", `scratchpad/mw/idkit/js/examples/nextjs/app/arena/ui.tsx:506-518`, idkit commit 16bc527, 2026-09-23) and `rust/core/src/error.rs:133-135,198`.
- So there are two outcomes, depending on timing:
  - (a) A's proof has already gone through the Portal `/verify` → B's phone gets the IDKit error `nullifier_replayed`.
  - (b) Both proofs are made before either is verified → the server sees `nullifier_A == nullifier_B`.
- Whether the World App's refusal needs a Portal `/verify` first or only a proof generation: UNVERIFIED. The cheapest test is the arena case with one World App account, 5 min.
- Server spec (not implemented yet: `grep same_human server/` is empty; the adapter design in docs/pop-human-adapters.md §3):
  - When the second human proof arrives, compare nullifiers **before** calling the Portal for it.
  - If they're equal, return `409 {"error":"same_human","message":"Both phones are the same World ID. Two different people must meet."}`, mark the session `aborted/same_human`, and don't `postPresence`.
- The app maps both `same_human` (server) and `nullifier_replayed` (IDKit, role B) to that one message. It's off-chain, so it's the secondary beat, not the headline.

**Not used as the failure path:** "NOT_NEAR → the proof can't be built". The honest wallet never even tries, so nothing is visible. F1 replaces it by making the dishonest wallet try.

**Demo order (about 40 s extra):** success run → F1 (phones far apart, Send anyway, red tx on worldscan) → optional F2 (one World App scans both QRs, rejected).

**Implementer checklist**
- pool contract: the errors above, in the check order above. Forge tests F1–F4 are copied from `scratchpad/vfail/test/FailPath.t.sol`; run them with `--fork-url` on 480.
- wallet: a "Send anyway" debug action that proves against a local tree `{ownLeaf}` (LeanIMT, depth 1 or 2), plus an ABI error decoder that maps the 6 selectors to user text.
- relayer: estimate-then-send, and the `force` flag behind `RELAY_ALLOW_FORCE`.
- server: the `same_human` check (before the Portal call), plus the app mapping of `nullifier_replayed`.
- verify the pool on Worldscan at deploy, and confirm on the first forced revert that the error name shows.

## anonymity-set-demo-honesty

**Answer.** In a fresh pool with 1–2 deposits the demo hides almost nothing from a chain observer: the only unspent note funded the transfer, and Q's withdraw is the only one after it. Fix it with three cheap rules, and scope the claim down in writing.

1. **Fixed deposit denomination: `DENOM = 0.001 ether`.** Add `require(msg.value == DENOM)` in `deposit`. Every deposit is then an equal candidate funder. Reason: `Deposited(depositor, commitment, label, value, precommitment)` is public, so odd amounts are fingerprints. VERIFIED(`privacy-pools-core/packages/contracts/src/interfaces/IPrivacyPool.sol:39`, `PrivacyPool.sol:82-106`, scratchpad clone d494b63)
2. **Payment amounts from a small menu, `{0.0002, 0.0003, 0.0005, 0.001}` ETH, enforced in the UI only.** The transfer circuit stays as is (amount private). Withdraw stays unrestricted, so change notes never get stuck. Reason: `withdrawnValue` is a public signal and `Withdrawn(processooor, value, nullifier, newCommitment)` is public. A unique cash-out amount links Q's exit to the transfer. VERIFIED(`withdraw.circom:17,85-91`; `IPrivacyPool.sol:50`)
3. **Seed decoys from a script before the demo:**
   - 12 decoy deposits (0.001 each) from 12 fresh EOAs;
   - P's real deposit interleaved among them, hours before the demo, never right before the meeting;
   - about 6 decoy withdraws (menu amounts, relayed, to fresh addresses) after the demo transfer.

   **No decoy transfers and no decoy presence leaves.** A withdraw of a deposit note looks the same as a withdraw of a payee note: the label is a private input, and only ASP membership is proven (`withdraw.circom:32,75-77`). So decoy deposits and withdraws are enough, and the attester never mints a fake ticket. That keeps the "attester can't authorize transfers without a meeting" story clean.
   - Cost on 480: 13 deposits × ~290k gas + 6 withdraws × ~400k gas ≈ 6.2M gas × 0.0015 gwei ≈ 1e-5 ETH, plus 0.012 ETH locked, recoverable by withdraw or ragequit. VERIFIED gas price (earlier section `mainnet-480-ops`); gas per call from pool.md §1.1 (forge).

**Model result** (scratchpad `anonset/anonset.py`; observer = public events plus the "last deposit before the transfer" and "same withdraw value" heuristics):

| scenario | funder set | payee-withdraw set |
| --- | --- | --- |
| A fresh pool, 1 deposit, pay 0.0003 | 1 | 1 |
| B fresh pool, odd amount 0.0137 | 1 (value match) | 1 |
| C 12 decoys, P deposits last | 13, but the timing heuristic picks P | 1 (unique value) |
| D 12 decoys, P interleaved, menu amounts, decoys withdraw from the menu | 13 | 4 |
| E like D, pay = the whole note 0.001 | 13 | 7 |

VERIFIED(`python3 anonset.py`, 2026-09-26). The model is a toy: it assumes observers use only value and timing.

**Demo choice:** scenario D or E.
- E (pay exactly 0.001, whole note, zero-value change) has the best set, but the "amount is hidden" beat is weaker, since every note is 0.001.
- D shows a hidden non-denomination amount.
- Recommendation: **D, pay 0.0003**. Q does not withdraw on stage. If the withdraw is shown, it runs after the decoy withdraws are in.

**Exact privacy claim for the README/pitch:**

- **Chain observer learns:**
  - who deposited and when (always 0.001);
  - that a presence leaf was posted, and that a transfer happened seconds later;
  - every cash-out's amount and recipient address.

  It does **not** learn which deposit paid, the transfer amount, or which cash-out is the payee's, beyond an anonymity set of about 13 funders and about 4 same-amount exits in our demo.
- **Honest caveat 1:** the 12 decoys are ours. They are all funded from one team wallet, so a chain analyst who clusters funding sources removes them, and the real anonymity set of this demo is **1 human**. The contracts and circuit give privacy only in proportion to real traffic. Say this on the slide: "crowd simulated by a script".
- **Honest caveat 2:** the leaf-to-transfer timing is adjacent. That is harmless onchain, because the leaf carries no identity in privacy mode (`deviceA/B = 0`). The fix in production is batched leaves plus delayed transfers.
- **Server (attester + relayer) learns:**
  - who met whom and when (device identities, World ID nullifiers per session);
  - `payerTag`, `payeeCommitment`, and `value` in the MVP channel.

  So it can find the exact transfer tx, because `payeeCommitment` is a public output. It does **not** learn which deposit funded it: `payerTag = Poseidon(TAG_PAYER, n)`, while the chain shows `Poseidon(n)`. VERIFIED(pool.md "Linkability of payerTag", case 9).
  - Caveat: our server is also the relayer. If Q's own device submits the withdraw, the server sees Q's device/IP next to the recipient address and links Q to the cash-out. Demo mitigation: submit the withdraw from the laptop wallet, and state the limit. Production mitigation: a third-party relayer.
- **Counterparty:**
  - Q learns the amount and P's PoP display identity, not P's deposit or address.
  - P learns `payeePre` and `payeeCommitment` (it can't spend them). But P knows the amount, so P can match Q's cash-out by amount and time inside a small set. Mitigation: the same menu amounts, and Q waits before withdrawing.

**One-line pitch that doesn't overclaim:** "Amounts and the payer-to-payee link are hidden inside the pool; privacy grows with the crowd, and in this demo the crowd is simulated."

**Conflict to decide:** the onchain World ID gate at deposit (pool.md §4.4) makes every decoy deposit need a real World App proof: 12 phone confirmations on mainnet, and staging-simulator proofs are still untested against `0x703a…`. Options:
- drop the deposit gate for the demo and keep World ID at the PoP server (recommended);
- run the gate only on P's deposit, via an `onlyGatedOrSeeder` switch, and disclose it;
- scan 12 times.

Status: resolved for the design. Remaining: nothing blocks. Optional: rerun `anonset.py` with the final menu and decoy counts.

## bn254-poseidon-parity

**Answer: one hash, "circomlib Poseidon(n)" over BN254 Fr (t = n+1, x^5, RF 8, RP 56/57/56 for t 2/3/4, circomlibjs `poseidon_constants.json`). Seven implementations agree byte for byte on 18 golden vectors plus a 7-leaf LeanIMT. Verified by running them, not by reading.** V(scratchpad `pp/ci.sh`)

Who uses what:

| Party | Needs | Use | Status |
| --- | --- | --- | --- |
| Circuits (`PresenceTransfer`, 0xbow `Withdraw`) | Poseidon(1/2/3), LeanIMT | `circomlib@2.0.5` `circuits/poseidon.circom` | V, circom 2.1.8 witness = golden |
| Contracts | T2 (nullifierHash, not needed onchain), T3 (LeanIMT), T4 (deposit commitment) | `poseidon-solidity@0.0.5` (latest on npm, last publish 2023-04-22) `PoseidonT3/T4`; `@zk-kit/lean-imt.sol@2.0.0` | V, forge 1.4.3 test |
| TS laptop wallet | all note/leaf/tree hashes | `poseidon-lite@0.3.0` `poseidon1/2/3` + `@zk-kit/lean-imt@2.2.2` | V |
| 0xbow SDK (if reused) | same | `maci-crypto@2.5.0` `poseidon` (-> `@zk-kit/poseidon-cipher@0.3.2` `poseidonPerm`) | V, agrees |
| Server | `presenceLeaf = Poseidon3(TAG_PRES, payerTag, payeeCommitment)` before `postPresence`, if it builds the leaf from the two phones' pieces | new pure-Python port, ~25 lines + constants JSON, 4.3 ms/hash | V |
| Kotlin app (only if payee notes live on the phone) | `payeePre` = Poseidon2, `payeeCommitment` = Poseidon3, leaf recompute = Poseidon2+3 | new `PoseidonBn254` on the existing `BigNat` (commonMain, no deps) + generated constants | V on JVM; 58-69 ms/hash (bit-serial `BigNat.rem`), ~4 hashes per payment, fine for a demo; iOS/Android timing U |

- `ctx_hash` needs **no** Poseidon: it is `keccak256(abi.encode("pool-xfer-v1", pool, presenceLeaf))`. Side note: server has no keccak today (`server/pyproject.toml`: fastapi, cryptography, numpy, cbor2 ...). `hashlib.sha3_256` is NOT keccak256; add `eth-hash[pycryptodome]` or `pycryptodome`. And `abi.encode` with a `string` is dynamic encoding (offset + length + padded data); use `eth_abi.encode(["string","address","bytes32"], ...)`, or change the tag to `bytes32` to make it trivial. V(pyproject), encoding rule from Solidity ABI spec.
- Do NOT touch the app's `Poseidon7` / `server/pop/poseidon7.py`: P-256 field, width 7, different constants. Name the new one `PoseidonBn254` so nobody mixes them up.

Input-range behavior (all agree, V):
- Inputs >= r are silently reduced mod r everywhere: circom witness gen, poseidon-lite, circomlibjs, maci-crypto, poseidon-solidity (`mod(mload(..), F)`), the Python and Kotlin ports. `Poseidon2(r+1, 2) == Poseidon2(1, 2)`, `Poseidon2(2^256-1, 0) == Poseidon2((2^256-1) mod r, 0)`.
- So a non-canonical value never breaks a leaf, but two different uint256s can hash the same. Rule: every party canonicalizes to `< r` before hashing and before storing. `InternalLeanIMT._insert` reverts on `leaf >= SNARK_SCALAR_FIELD`, and Groth16 verifiers reject public inputs `>= r`, so non-canonical values fail loudly only at those two points.
- Secrets: draw 31 random bytes (always `< r`), as pool.md §4.1 says.

Golden vectors (hex, 32-byte big-endian; full file with inputs is `pp/golden.json`, sha256 `028daf7f…28ff`):

```
Poseidon1(0)          = 0x2a09a9fd93c590c26b91effbb2499f07e8f7aa12e2b4940a3aed2411cb65e11c
Poseidon1(1)          = 0x29176100eaa962bdc1fe6c654d6a3c130e96a4d1168b33848b897dc502820133
Poseidon2(1,2)        = 0x115cc0f5e7d690413df64c6b9662e9cf2a3617f2743245519e19607a4417189a   // the well-known circomlib vector
Poseidon2(0,0)        = 0x2098f5fb9e239eab3ceac3f27b81e481dc3124d55ffed523a839ee8446b64864
Poseidon3(1,2,3)      = 0x0e7732d89e6939c0ff03d5e58dab6302f3230e269dc5b968f725df34ab36d732
Poseidon3(0,0,0)      = 0x0bc188d27dcceadc1dcfb6af0a7af08fe2864eecec96c5ae7cee6db31ba599aa
Poseidon2(r-1,r-1)    = 0x2c6bd813a6338781378d8706cb82fd4216ab52b752ccd41564d7b98756a6e0fb
Poseidon3(r-1,r-1,r-1)= 0x294e7ab38f79bf9f691b3ab92039bbc5718f4c6b69c785cb44032662ea0111f2

pool chain (pool.md §4.1 formulas). r(s) = ascii(s) right-padded with '.' to 31 bytes, as a big-endian int:
  nul=r("existingNullifier") sec=r("existingSecret") qn=r("payeeNullifier") qs=r("payeeSecret")
  value=1e15 (0x38d7ea4c68000), label=0x1234567890abcdef
precommitment   = P2(nul,sec)                                  = 0x22715ad87ad9eec157e49316dd55276216f53020b04036d7bfb0b7802039070e
commitment      = P3(value,label,precommitment)                = 0x032f7c84073eb32a2b9cc2665e43b6a4fa526371641dc0353f70f178da6b0dd4
nullifierHash   = P1(nul)                                      = 0x22aac6b02eae5a8e7e27d6ba3343e7c4add725d9bc8cc22cfde0c0304f9f9f75
payerTag        = P2(TAG_PAYER,nul)                            = 0x27acd345b39f772b72801517b32f99afa4ec1fbc1dede42219340d12b77a7c82
payeePre        = P2(qn,qs)                                    = 0x23fa76442330b09c4b75becdb6d7d720325858166110f749262581806ed08e93
payeeCommitment = P3(value,LABEL_TRANSFER,payeePre)            = 0x2c86dec4c1f102d16517b90c8147265ab6b8be0c2bd2905fd571d8ecab780e99
presenceLeaf    = P3(TAG_PRES,payerTag,payeeCommitment)        = 0x1b7f106ab8af96f910677aa65f849357b1518cbed012e899b8f2b9b275b5c2a4
LeanIMT(PoseidonT3) root after inserting the 7 pool values above in order = 0x204f6c81b4e42a78adc893fd0e8efab0264fa7d0fa1c927d7a432a8e2669c785
```

Other measured facts:
- Gas inside a forge test (linked public library call): `PoseidonT3.hash` 22,810, `PoseidonT4.hash` 39,589. V
- Constants source of truth: circomlibjs 0.1.7 `src/poseidon_constants.json` (sha256 `354f31bb…3f2c`). Extracted t2..t4 subset `pp/poseidon_bn254_t2_t4.json` is 42 KB (C: 128/195/256 entries; M: 2x2/3x3/4x4). poseidon-lite ships the same values base64-packed. V

Artifacts (scratchpad `/private/tmp/claude-501/-Users-takahiro-ogawa-dev-enconomy/3d9dd236-bf59-4c81-91f5-6bb7c5ebc6e3/scratchpad/pp/`):
- `golden.json` (18 cases + LeanIMT roots), `gen.mjs` (poseidon-lite vs circomlibjs wasm/reference/opt), `circ.cjs` + `h{1,2,3}.circom` (circom witness), `maci.cjs`, `forge/test/Golden.t.sol` (reads `../golden.json`), `poseidon_bn254.py` + `poseidon_bn254_t2_t4.json`, `kt/PoseidonBn254.kt` + generated `kt/PoseidonBn254Params.kt` (built on a copy of `app/.../zk/BigNat.kt`), `ci.sh` runs all of them.

What implementers must do:
1. Copy `golden.json` into the contracts repo as `test/fixtures/poseidon_golden.json`, plus `Golden.t.sol` (needs `fs_permissions` read on it). This becomes the CI test for the Solidity and LeanIMT side.
2. The TS wallet runs the same JSON in a vitest/node test against `poseidon-lite` and `@zk-kit/lean-imt`. The circuit test computes the witness for `pool_presenceLeaf` and checks it.
3. The server adds `pop/poseidon_bn254.py` + constants JSON and a pytest over `golden.json`.
4. The app (only if the payee holds notes on the phone) adds `zk/PoseidonBn254.kt` + generated params in commonMain and a commonTest over the pool chain vectors. If 60 ms/hash is too slow on iOS: a Montgomery BN254 Fr like `Fp.kt`, or Barrett reduction in `BigNat.rem`.
5. Pin versions: `poseidon-lite@0.3.0`, `poseidon-solidity@0.0.5`, `circomlib@2.0.5`, `@zk-kit/lean-imt@2.2.x`, `@zk-kit/lean-imt.sol@2.0.0`.

Still U: Kotlin/Native (iOS) and ART (Android) speed of the BigNat port. Cheapest check: run the commonTest on the iOS simulator and an Android device, timing 10 hashes.

## venue-acoustics-network

Status: partially resolved. Noise tolerance measured offline on real recordings; tunnel measured live. Still open: one on-site calibration (absolute SPL of our sound vs the hall), iPhone native audio, the venue network itself.

### Acoustics: noise injection into the 12 real JBL250 sessions

Method. Scratchpad `…/scratchpad/venue/noise_sweep.py`. Took the recorded field sessions (`research/sound-bound/spikes/melody/fieldtest/data/sessions/`, Mac + Android Chrome, big quiet room, handheld, vol mid; 30 cm ×3, 100 cm ×2, 200 cm ×1), added noise to both recordings, reran the unchanged analyzer (`fieldanalysis._analyze`, JBL250 only, rule "first"). Noise: pink (HVAC/crowd proxy), 10-voice babble (macOS `say`, 22 kHz voices so HF is under-represented), "music" (pink + 60 Hz kick, PA proxy). Level swept 0 to −30 dB broadband re the partner sound at the listener. 120 runs. VERIFIED(command, outputs `out_*.jsonl`).

Results:
- **Noise never produced a wrong verdict.** 0 of 120 runs flipped NEAR/NOT_NEAR. Every failure was a miss (`below_null…`, partner not found), which the server handles as a failed measurement → auto retry (attempt 1, fresh codes) → then NOT_NEAR. The live-null bar rises with the noise, as designed. VERIFIED.
- **Break point: the weakest listener's in-band SNR (2–18 kHz, partner sound vs noise) of about −12 to −14 dB.** Above −11.5 dB both rounds were always usable; below −14 dB rounds start getting lost. Same for all three noise types once expressed in-band. VERIFIED.
- Flight readings under noise drift up a little near the break point (30 cm reads 33 → 41 cm with pink/music at −10 dB), still far from the 60 cm line. VERIFIED.
- Babble is the easy case: speech has little energy above 2 kHz. For the same dBA, in-band level is **babble −9.3 dB, pink/music −2.1 dB** re the A-weighted level (computed on the synthetic noises). E.
- Touch-distance rows are invalid: scaling noise to a very loud partner clipped the Mac recording. A real hall's noise is absolute, so closer phones only help. But it shows **clipping kills the run** (self-arrival lost), so don't put a phone on top of a PA speaker.

Absolute mapping (rough). Using the Android CDD input-sensitivity target (90 dB SPL at 1 kHz → RMS 2500/32768 for VOICE_RECOGNITION, https://source.android.com/docs/compatibility/5.1/android-5.1-cdd) on the Android recordings: the partner (Mac speaker, vol mid) arrived at about **67–70 dB SPL in-band at 30 cm**, 60 at 100 cm. Chrome's capture path may not follow CDD gain, so ±10 dB. UNVERIFIED calibration.

| Hall | In-band noise (E) | In-band SNR at 30 cm | Headroom to −12 dB |
|---|---|---|---|
| 70 dBA crowd talk | ~61 dB | ~+6..+9 | ~18–21 dB |
| 70 dBA PA music | ~68 dB | ~0..+2 | ~12–14 dB |
| 80 dBA next to a PA stack | ~78 dB | ~−10..−8 | ~2–4 dB, marginal |

Phones side by side (~10 cm) add roughly +6–10 dB over 30 cm (inverse distance, E). Media volume 100% vs "mid" adds more.

Answer: **yes for a normal hall and a judge's table (≤ 75 dBA), side by side, volume max. Risky only right next to the PA or stage speakers.** Failure is always "not heard", never a wrong verdict.

### Network

- **Quick tunnel limits** (https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/): 200 in-flight requests (429 above), no SSE, no SLA, testing only. VERIFIED. Our API uses long-poll, not SSE, so fine.
- **Quick tunnel measured from here** (cloudflared 2026.5.2, edge `nrt10`): `ha-connections:1` (one connection, no redundancy), protocol quic by default. New-connection TTFB median 124 ms, p90 190, max 983; keep-alive RTT median 59, min 29, p90 112 ms. 40/40 OK. VERIFIED(curl, python).
- **Long-poll through the tunnel:** 25 s and 60 s held requests both returned 200 with `--protocol http2`. VERIFIED(curl). Server long-poll max is 25 s (`server/README.md` l.37).
- **Ports:** cloudflared needs outbound 7844 TCP+UDP (QUIC on UDP, HTTP/2 on TCP), https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/tunnel-with-firewall/. VERIFIED. Venue Wi-Fi may block UDP or 7844; the laptop on a phone hotspot avoids that. Automatic QUIC→HTTP/2 fallback: UNVERIFIED, so start it with `--protocol http2` explicitly (tested, works).
- **Clock sync is fine over the tunnel.** App takes the min-RTT of 10 pings and refuses above 300 ms (`ClockSync.MAX_RTT_MS`, app commonMain). Error ≤ RTT/2 per phone, so ~15–50 ms each on the tunnel, inside the −150/+250 ms search window (`server/pop/constants.py` SEARCH_PRE_S/POST_S). Field sessions already ran with phone rtt_min 43–80 ms. VERIFIED(code, meta_B.json).
- **iOS ATS:** only `NSAllowsLocalNetworking` (`app/iosApp/iosApp/Info.plist:51-54`). trycloudflare / ngrok are public HTTPS with valid certs, so ATS is satisfied. Plain `http://<LAN IP>` also works. Android allows cleartext everywhere (`res/xml/network_security_config.xml`). VERIFIED(code).
- **Quick tunnel URL changes every restart.** Both phones must be re-pointed (the in-app URL field, saved per phone; `app/README.md` l.57). The invite doesn't carry the URL (`server/README.md` l.39). Stable options:
  - ngrok free: one fixed `*.ngrok-free.app` dev domain, API clients skip the interstitial (non-browser UA, or header `ngrok-skip-browser-warning: 1`), but **1 GB/month and 20k requests/month** (https://ngrok.com/docs/pricing-limits/free-plan-limits/). ngrok 3.39.6 is installed with an authtoken. VERIFIED.
  - Named Cloudflare tunnel: needs a domain on Cloudflare plus `cloudflared tunnel login` (no `cert.pem` on this Mac today; there's a 2022 tunnel credential `~/.cloudflared/92efd87b-….json` of unknown state). VERIFIED(ls, `cloudflared tunnel list` error).
- **Proving keys are big:** `oa2t_s48.pk` 470 MB, `oa2t_s44.pk` 449 MB raw (`research/sound-bound/spikes/zk/optionA-v2/keys/`); served via `/v1/zk/keys` (zstd). **Download them on both phones at home over LAN.** Never at the venue: slow on a hotspot, and it would eat the whole ngrok monthly quota. Proof upload is ~1.6 MB per phone, fine. VERIFIED(ls).
- **World ID needs internet on each phone,** separate from our server: the World ID app (fetches its proof inputs) and our app polling `bridge.worldcoin.org` (`research/worldid/notes/mobile-wallet.md` §1). The deep link carries no data, so if polling can't reach the bridge, the proof is lost. Cellular on both phones covers it.

### Retry cost and World ID nullifiers

- Audio failure inside one session is cheap: MAX_ATTEMPTS = 2 (`server/pop/constants.py:29`), attempt 1 gets new codes. The World ID action/signal is per session (`pop:<sid>`, signal = nonce‖role), not per attempt, so **an in-session audio retry doesn't need new World ID proofs**. VERIFIED(code, `docs/pop-human-adapters.md` l.74).
- Only if both attempts fail do you need a new session, so new World ID proofs (~one app switch per phone). v4 nullifiers are one-time per action, but a new session means a new action, so it's allowed, just slow. UNVERIFIED: whether the World ID app or Portal rate-limits many actions per RP per human in a short time (`max_verifications_reached` exists in the error list).
- Design lever: `docs/pop-human-adapters.md` l.48 puts World ID **before** the audio run, because the app switch would kill the iOS audio session mid-run. Running it **after the NEAR verdict** avoids that too, and a failed audio session then costs no World ID step. Recommend for the demo: World ID after NEAR, bound through the same session nonce. This is a design choice for the doc owner; server/app untouched.

### Demo-day runbook (derived)

1. Laptop and both phones on one **phone hotspot** (or each phone on its own cellular data and the laptop on the hotspot). Avoid venue Wi-Fi: client isolation, blocked UDP/7844, captive portals.
2. Server: `cloudflared tunnel --protocol http2 --url http://localhost:8000`, or better a fixed ngrok dev domain baked into both builds (`-Ppop.serverUrl` / `POP_SERVER_URL`) so a tunnel restart doesn't mean re-typing URLs.
3. Proving keys cached on both phones beforehand. The app pins their sha256.
4. Media volume 100% (preflight only demands 60%, `AudioEngine.android.kt:112`), speaker not Bluetooth, **phones side by side**, not on a PA speaker. Screens up, hands off the mic holes.
5. Before judging: do one full dry run at the booth. If the partner isn't heard, move away from the speakers.
6. Pre-recorded backup video of the full flow (audio NEAR → World ID ×2 → onchain tx).

### What's left and the cheapest way to close it

1. **Absolute calibration (5 min):** play JBL250 on the demo phones at 100% and read a free SPL-meter app at 10 cm and 30 cm, then read the hall's dBA at the booth. Compare with the table above (break point: in-band SNR −12 dB).
2. **Real noisy walk (15 min):** play a conference-hall / crowd recording at ~70 dBA from a laptop or speaker 1–2 m away, do 5 runs side by side and 5 at 100 cm with the native apps (iPhone + Android). Expect 10/10 correct and ≤ 1 retry.
3. **Hotspot test (5 min):** full flow including World ID on cellular with the tunnel you'll use on stage. Time it end to end.
4. Unknown: iPhone native capture (`.measurement` mode) under noise. Not in any recording yet.

## safe-guard-trust-tier

Status: RESOLVED (decision made). Checked 2026-09-26 against HEAD `ba81f84` (server) and `ce03696` (app POPT v2).

### Decision
- **SAFE guard = attestation-only (tier 1).** Ship `PopSafeGuard` exactly as in `## owner-device-registry`: POP2 tail, P-256 issuer sig over the 199-byte digest, device ids checked against `deviceOwner[safe]`. No POPT parsing, no SBcred3, no rate constants onchain.
- **Tier 2 runs offchain in the audience viewer**: the viewer fetches both POPT v2 transcripts + phone sigs from the public attestation/record, re-runs `PopBridge.verify` logic (JS port, or `eth_call` against an undeployed-bytecode code override on 480 as bridge.md §1.2 did), and shows "phones' hardware signatures check out, distance recomputed: NEAR". Zero risk to funds if it breaks.
- `bridge.md` §7 "SAFE → tier 2" is **superseded** for the hackathon build. Implementing agents: do not put `PopBridge` into the guard.

### Why
1. **Tier 2 alone does not remove server trust.** The SBcred3 issuer key is the same PoP server (`server/pop/issuer.py`, `POP_ISSUER_KEY`). A hacked server can issue SBcred3 for two software keys it holds, sign two POPT v2 transcripts, and PopBridge says NEAR. Tier 2 only helps when combined with the per-Safe device registry (hardware keys pinned at Safe creation). And once the registry pins the keys, the SBcred3 check is redundant. VERIFIED (read issuer.py L1-85, bridge.md §6 `checkCred`).
2. **Tier 2 + registry still trusts the app.** A patched app can lie about `half` (bridge.md §3.1 row c); only option A ZK closes that, and it is offchain. So onchain tier 2 moves trust from "server" to "server-or-app", not to zero. Not worth freezing into a guard today.
3. **Immutable coupling to moving targets.** A tier-2 guard hard-codes the 311 B layout, `C_CM_S=34300`, `NEAR_CM=60`, `IMPOSSIBLE_CM=-20`, `SELF_OS_TOL_MS=50`, and the verdict formula. Another workflow is still committing app/ changes; a guard is removable only through itself (brick risk, safe.md §4.1).
4. Gas is not the reason: tier 2 adds ~82k + 622 B calldata, trivial on 480. The reason is correctness risk under a 17 h cut.

### Facts pinned (for the viewer, and for any later tier-2 guard)
- **POPT v2 layout is identical in app and server.** Server `server/pop/codec.py` (last touched `c9fa84a`): `_TX = ">4sBcB32s65s65sIi32sQQQi32s"` (269) + `_TX2X = ">IIH32s"` (42) = 311. App `Transcript.kt` @ `ce03696` `transcript2()/decodeTranscript2()`: same fields, same offsets, big-endian. `git diff ce03696 HEAD` on `Transcript.kt`, `codec.py`, `docs/pop-transcript-v2.md`: empty; Transcript.kt not in the working-tree dirty list. VERIFIED (read both, git diff).
- Offsets: magic 0 (4) · ver 4 (=0x02) · role 5 ('A'=0x41/'B'=0x42) · attempt 6 · session_nonce 7 (32) · pk_self 39 (65, 0x04‖X‖Y) · pk_partner 104 (65) · sample_rate u32 169 · half i32 173 · rec_root 177 (32) · play_frame_position u64 209 · play_nano_time u64 217 · rec_frame0_nano_time u64 225 · self_os_delta i32 233 · commit_hash 237 (32) · a_self u32 269 · p_partner u32 273 · delta u16 277 · code_commit 279 (32). Phone sig = P-256 over sha256(311 raw bytes).
- **Layout id** (use this string verbatim if a guard/viewer needs a version tag): `sha256("POPT|v2|len311|magic4@0 ver1@4 role1@5 attempt1@6 nonce32@7 pk_self65@39 pk_partner65@104 sample_rate_u32@169 half_i32@173 rec_root32@177 play_frame_position_u64@209 play_nano_time_u64@217 rec_frame0_nano_time_u64@225 self_os_delta_i32@233 commit_hash32@237 a_self_u32@269 p_partner_u32@273 delta_u16@277 code_commit32@279|BE")` = `0x9114333fd84d7c4feb43ab7becb92e69e907ff6c3a344e94c0465fac084b952a`. VERIFIED (python hashlib).
- Verdict constants today: `server/pop/constants.py` L22-27 `IMPOSSIBLE_CM=-20, NEAR_CM=60, SPEED_OF_SOUND_CM_S=34300, SELF_OS_TOL_MS=50`; match PopBridge. VERIFIED.
- **Credential TTL:** `CRED_TTL_S = 30*86400` (`server/pop/issuer.py:26`), env `POP_CRED_TTL_S` default `2592000` (`server/pop/main.py:83`, `server/README.md:27`). With the default, a credential issued at enrollment today lives until ~2026-10-26, so demo day is safe. Risk only if someone sets `POP_CRED_TTL_S` short in the demo env. The attestation-only guard does not read SBcred3, so TTL cannot brick it. Viewer: use `validAt = session t0_s`, not "now", so old sessions still verify. VERIFIED (read).

### If tier 2 is added later (post-hackathon)
- New contract `PopSafeGuardV3`, swapped in by a PoP-gated `setGuard(new)` tx (the old guard allows it with a valid POP2 attestation; or via the escape hatch).
- Constructor pins `bytes32 layoutId` (value above) and the four verdict constants; revert if a transcript's version byte ≠ 2 or length ≠ 311.
- Check transcript pubkeys against `deviceOwner[safe][sha256(pubkey65)]`, drop SBcred3 entirely (no TTL dependency, no issuer trust for keys).
- Keep the POP2 server sig too ("both" mode, +~7k gas) so the server's code/recording checks still count.
- Pitch line then: "the server alone can't approve your tx; it needs both owners' registered phones to sign this exact tx's nonce."

### Pitch wording for the hackathon (tier 1)
"The chain trusts the enconomy attester the way it trusts an oracle. Every attestation publishes both phones' hardware-signed transcripts; anyone can recompute the distance in the viewer and see the server didn't make it up." Do not claim the server can't forge presence.

### Remaining unknowns
- The public attestation endpoint must expose both raw POPT v2 transcripts + phone sigs (base64) for the viewer. Not in WID-S step 6's field list yet; add `transcripts.{A,B}.{raw_b64,sig_b64}` there. Cheapest: one line in the design doc's server package.
- Re-check `git diff ce03696 <app freeze commit> -- app/composeApp/src/commonMain/kotlin/com/enconomy/pop/Transcript.kt` is empty once the P2 commit lands; if not, recompute the layout id.

## ens-lane-collision

Status: partially resolved. The facts and the shared server spec are settled below. Two choices only the user can make: which lanes ship at Tokyo, and which partner prizes to enter. Checked 2026-09-26.

### Facts

- **Tokyo partners, 7 total.** World $15k, 1inch $7k, ENS $10k, Uniswap Foundation $10k, Sui $5k, Curvegrid $3k, Intercepta $2.5k. VERIFIED(curl https://ethglobal.com/events/tokyo2026/prizes → scratchpad `tokyo-prizes.txt` lines 22-37)
- **Pick limit: 3 partners.** A partner with several tracks counts once. VERIFIED(worldid-prize.md §B, from tokyo2026/info/details)
- **ENS tracks.**
  - "Best Use of ENSv2", $6k (3k/2k/1k), open to Classic. Must be "built on ENSv2 (Sepolia)", "central to the product, not a cosmetic add-on", with a live demo link and open source.
  - "Best Integration of ENSv2 into an Existing Project", $4k, Continuity only.
  - VERIFIED(same page, lines 265-320)
- **Nothing else fits us.**
  - 1inch needs Aqua/SwapVM contracts.
  - Uniswap needs a Uniswap-stack contribution.
  - Sui needs the Sui chain.
  - Curvegrid is a stablecoin/agent sample app.
  - Intercepta needs x402 agent payments plus a live Intercepta API call.
  - Neither SAFE, POOL nor ENS-meetings meets any of those without a new build. VERIFIED(same page).
  - **So only 2 of the 3 picks are realistic: World and ENS. The third slot stays empty** unless someone bolts on an Intercepta screen before a POOL payment. That is weak and not recommended.
- **Chains really differ.**
  - ENS lane: Ethereum Sepolia 11155111, because ENSv2 exists only there. VERIFIED(ens-meetings-design.md §0; ENS prize text "ENSv2 (Sepolia)").
  - SAFE/POOL: World Chain 480 (pool.md item 6, mainnet-480-ops). SAFE could also use 4801 or Sepolia (safe.md §1).
  - Different keys, funds and relayers:
    - ENS hot key is secp256k1 via web3 on Sepolia, funded 0.2-0.5 ETH.
    - SAFE attester is P-256 per safe.md.
    - 480 relayer needs 0.01 ETH.
- **World ID code collision is real.** VERIFIED(grep of both docs):

| Item | ENS doc | Adapters doc / SAFE / POOL |
|---|---|---|
| action | fixed `enconomy-name:<parent>` (§4.3, env `POP_WORLDID_ACTION`) | per session `pop:<sid>` (pop-human-adapters.md §2) |
| signal | `device_id` (hex32 text, no `0x`) | `0x ‖ nonce32 ‖ role byte` |
| nullifier store | `persons.wid_nullifier TEXT UNIQUE` (§6.3) | `UNIQUE(kind, nullifier)` in the session doc |
| semantics | same nullifier again = recovery **relink** | same nullifier again = **replay reject** |
| credential check | "level field equals orb" (WP-9) | `identifier`/`issuer_schema_id` |
| env | `POP_ENS_REQUIRE_WORLDID`, `POP_WORLDID_RP_ID`, `POP_WORLDID_ACTION` | none yet |

- **The ENS doc's "orb level" check is a v3 idea.** v4 verify responses carry `identifier: "proof_of_human"` + `issuer_schema_id: 1`. Legacy v3 proofs carry `identifier: "orb"`. There is no `level` field. VERIFIED(scratchpad `wid/api-reference_developer-portal_verify.md` lines 7, 61, 79-80, 423)
- **Signal hashing trap.** IDKit hashes a string signal as raw bytes when it is a valid non-empty even-length `0x` hex string. Any other string is hashed as UTF-8.
  - So `device_id` (32 hex chars, no `0x`, `server/pop/crypto.py:12-13`) is hashed as 32 ASCII bytes.
  - `"0x"+device_id` is hashed as 16 raw bytes.
  - If the server and app disagree on this, `signal_hash` mismatches.
  - VERIFIED(worldcoin/idkit @16bc527 `rust/core/src/crypto.rs:347-359`, `types.rs:300-310`)
- **The server has no keccak today.** Its deps are fastapi, uvicorn, cryptography, numpy, python-multipart, cbor2 (`server/pyproject.toml`). `hashlib.sha3_256` is not keccak256.
  - The spike signer (`~/dev/worldid-spike/backend/app/signing.py`: `hash_to_field`, `rp_message`, `sign_request`, parity-tested against JS in `parity/sign.mjs`) uses `eth-account>=0.13`.
  - The ENS lane plans `web3==8.0.0`, which pulls in eth-account.
  - VERIFIED(read files)
- **The ENS lane also plans edits** to `sessions.py`, `main.py` (Settings, `/v1/config`), `store.py` and `pyproject.toml`. The same files the World ID WID-S package touches (see integration-freeze-point). VERIFIED.

### Answers

1. **Is ENS still in scope?** User decision. Recommendation: **yes, as the ENS-prize lane, but World ID is built once, in the SAFE/POOL lane, and ENS consumes it.**
   - ENS is the only second partner that fits.
   - It needs no World ID to qualify for the ENS prize.
   - For Tokyo, keep `POP_ENS_REQUIRE_WORLDID=0` (the doc's own P0 default) unless the shared module below is already merged. In that case turning it on is config plus one call.
   - World judges one "trust moment". Two different World ID moments in one video dilute it. The World story is SAFE (or POOL). The ENS story is "names + met counters on ENSv2".
2. **Which 3 partner prizes?** Recommendation:
   - (a) World, Best Use of IDKit. The Agents track counts under the same partner, so enter it only if it fits for free.
   - (b) ENS, Best Use of ENSv2 on Classic, or the $4k Integration track if the team is on Continuity (open question in worldid-prize.md).
   - (c) none. Don't spend hours chasing a third partner.
3. **One World ID module for both action kinds?** **Yes, and it must be one module.** Spec below. Both design docs should link to it and drop their own World ID details.
4. **Demo/chain cost.**
   - One submission, one video. It shows the SAFE/POOL flow on 480 (World) and ends with the same NEAR session bumping `met` on Sepolia (ENS). Order the steps so one PoP run feeds both.
   - The ENS worker is async and doesn't block the verdict (§ENS "never blocks the verdict").
   - If time is short, ENS goes into the video as a 30 s tail, or is dropped.
   - Two relayer keys are fine: `POP_ENS_HOT_KEY_FILE` (Sepolia) and `POP_CHAIN_RELAYER_KEY` (480). Never share one nonce owner across chains.

### Shared spec: `server/pop/human.py` (World ID only; both lanes import it)

```python
# deps: add "eth-account>=0.13" (or web3==8.0.0 if the ENS lane lands first; it includes eth-account). Pin in uv.lock once.
PORTAL = "https://developer.world.org/api/v4/verify/{rp_id}"

@dataclass(frozen=True)
class ActionSpec:
    kind: str            # "session" | "fixed"
    action: str          # exact string sent to IDKit
    signal: str          # exact string sent to IDKit; ALWAYS "0x"+hex so it is hashed as bytes
    on_reuse: str        # "reject" (session) | "return_existing" (fixed: caller may relink)

def session_action(sid: str, nonce32: bytes, role: str) -> ActionSpec:
    # role byte: b"A"=0x41, b"B"=0x42
    return ActionSpec("session", f"pop:{sid}", "0x" + (nonce32 + role.encode()).hex(), "reject")

def fixed_action(name: str, device_id: str) -> ActionSpec:
    # name from registry, e.g. "enconomy-name:enconomy.eth"; device_id is hex32 -> 16 raw bytes
    assert name in FIXED_ACTIONS
    return ActionSpec("fixed", name, "0x" + device_id, "return_existing")

FIXED_ACTIONS = {f"enconomy-name:{os.environ.get('POP_ENS_PARENT','enconomy.eth')}"}  # registry; add more here, nowhere else

def hash_to_field(b: bytes) -> int: return int.from_bytes(keccak(b), "big") >> 8
def signal_hash(sig: str) -> int:        # mirrors idkit crypto.rs hash_signal
    h = sig[2:] if sig.startswith("0x") else None
    raw = bytes.fromhex(h) if h and len(h) % 2 == 0 and all(c in "0123456789abcdefABCDEF" for c in h) else sig.encode()
    return hash_to_field(raw)

def rp_context(spec: ActionSpec) -> dict       # port of worldid-spike signing.sign_request, TTL 300 s
async def verify(spec: ActionSpec, idkit_result: dict) -> HumanResult   # raises Reject(code)
```

`verify` does these checks in order. Failure codes follow pop-human-adapters.md §4:
1. POST the IDKit result verbatim to the Portal. Non-2xx → `human_invalid`.
2. `result.environment == POP_WORLDID_ENV`, default `production` → else `human_invalid`.
3. `result.action == spec.action` → else `human_invalid`.
4. Exactly one response item.
   - Accept `identifier == "proof_of_human" and issuer_schema_id == 1`.
   - Accept `identifier == "orb"` only if `POP_WORLDID_ALLOW_LEGACY=1`.
   - Else `human_level`, which replaces the ENS doc's `worldid_level`.
5. `int(signal_hash) == signal_hash(spec.signal)` → else `human_invalid`.
6. Nullifier: `n = int(nullifier, 0)`, stored as a decimal string. Insert into the one table below. On conflict:
   - `on_reuse == "reject"` → `human_replay`. The Portal returns 200 with `nullifier_reused`, so only this table enforces replay.
   - `on_reuse == "return_existing"` → return the existing row's `subject`.

One table, created by `human.py` itself (`CREATE TABLE IF NOT EXISTS`, so `store.py` doesn't change):

```sql
CREATE TABLE IF NOT EXISTS wid_nullifiers (
  rp_id TEXT NOT NULL, action TEXT NOT NULL, nullifier TEXT NOT NULL,   -- decimal
  kind TEXT NOT NULL,                  -- session | fixed
  subject TEXT NOT NULL,               -- session: "<sid>:<role>"; fixed: person_id (ENS lane fills it)
  environment TEXT NOT NULL, created_at INTEGER NOT NULL,
  PRIMARY KEY (rp_id, action, nullifier));
```

- The ENS lane drops `persons.wid_nullifier`. It looks up the person by `(rp_id, fixed action, nullifier)` → `subject`.
- The session lane still checks `nullifier_A != nullifier_B` (`same_human`) and computes `pair_tag` as in pop-human-adapters.md.

Pinned env. It lives in `Settings` in `main.py`, once:

| Env | Default | Used by |
|---|---|---|
| `POP_WORLDID_APP_ID` | none | IDKit request (app side reads it from `/v1/config.worldid`) |
| `POP_WORLDID_RP_ID` | none (World ID off if unset) | both |
| `POP_WORLDID_SIGNING_KEY_FILE` | `data/worldid-rp.key` (0600, gitignored) | rp_context |
| `POP_WORLDID_ENV` | `production` | both |
| `POP_WORLDID_ALLOW_LEGACY` | `0` | both |
| `POP_ENS_REQUIRE_WORLDID` | `0` | ENS claim only; gates the call, never the module |

- Remove `POP_WORLDID_ACTION` from the ENS doc. The fixed action comes from `FIXED_ACTIONS`, built from `POP_ENS_PARENT`.
- `/v1/config` gains one block, `"worldid": {"app_id", "rp_id", "environment", "fixed_actions": [...]}`, shared by both lanes. The `ens.worldid` sub-block goes away.
- One rp_id and one app in the Developer Portal serve both lanes. Actions are auto-created on first verify (worldid-prize.md §E), so no Portal setup is needed per action.

Edit order (one lane per file at a time; see integration-freeze-point):
1. WID-S lands `human.py`, the env and `/v1/config.worldid`.
2. ENS WP-4 rebases onto it and calls `human.verify(fixed_action(...))` in `/v1/ens/claim` step 3.
3. The chain attester and relayer keys stay per lane and per chain (ENS: secp256k1 on Sepolia; SAFE/POOL: its own key on 480).

### What remains, and the cheapest way to close it

- **User, 1 minute:**
  - (a) ship ENS at Tokyo: yes/no;
  - (b) SAFE or POOL;
  - (c) partner picks: World + ENS + none?
  - (d) Classic or Continuity track. This decides the ENS track: Best Use $6k vs Integration $4k.
- **Doc edits (not done here; this task may only write this file):**
  - `docs/ens-meetings-design.md` §4.3, §6.3 (`persons.wid_nullifier`), §6.4 (`/v1/config.ens.worldid`), the env table (`POP_WORLDID_*`), WP-9 ("level field equals orb", signal `device_id`): replace with a link to this spec.
  - The main World ID design doc: include this spec as its `human.py` section.
- **Unverified:** that the Portal's `result.environment` field is present at top level in the v4 response for PoH. The spike logged `environment:"production"` (human-to-device-mapping). Confirm with one real verify.

## safe-worldid-marginal-value

Status: RESOLVED for the design decision. Two facts remain UNVERIFIED (World App behaviour, listed at the end); they only matter for the stretch option.

### Answer

- **What World ID stops in SAFE: "the phones are together, but the humans aren't acting."** The device registry proves that two registered *phones* were within ~60 cm. Owner signatures prove that two *keys* signed. Neither proves that a live human pressed anything. Two co-owners' phones on the same nightstand, or both phones in one thief's bag, pass registry + signatures if the owner keys live in the app (P256Owner / in-app keys, see `owner-device-registry`). A per-tx World ID Proof of Human from each role closes that. It forces **two distinct, live, Orb-verified humans to approve this exact `safeTxHash`** within the root window (~1 h).
- **What it does not stop:** "A carries both phones and B proves World ID remotely." Nothing in the World ID proof binds it to the phone that made the PoP run. The proof's `integrity_bundle` is World App's own attestation (JWT `aud` = our rp_id); it has no link to our device key. So state the guarantee honestly: *registered phones together (server + onchain registry) AND two distinct humans approved this tx (onchain)*. It is **not** "both humans are standing there". Coercion in person is also not stopped (use the timelock/spend cap, not World ID).
- **Enforce it onchain, in the guard, on World Chain 480.** Don't rely on a server "human ok" bit. The guard calls `verify` on `0x00000000009E00F9FE82CfeeBB4556686da094d7` twice. It pins `rpId`, `issuerSchemaId = 1`, and a `signalHash` it recomputes itself from the tx context. It requires `nullifierA != nullifierB` and recomputes `pairTag = sha256("pop-pair-v1" ‖ min ‖ max)` from the two nullifiers. The server's P-256 attestation signs that same `pairTag`, so the PoP verdict and the two humans are glued together. The cost is ~0.8M gas per Safe tx, which is fractions of a cent on 480. With only a server bit, a judge is right to call World ID decorative: the chain would accept a server that never asked for World ID.
- **Do not use `verifySession` for owner binding in the MVP.** A standalone session proves "same World ID as enrollment" but **not distinct humans**. One human can mint any number of sessions (random `oprf_seed` per creation), so he can enroll as both owners. The binding that would fix this (a uniqueness proof with `session_id: "create"`) is in the protocol, and it is verifiable onchain today via the public `verifyProofAndSignals`. But IDKit 4.3 doesn't expose it, and World App support is unverified. Keep it as a stretch goal (option S+ below).

### Threat table

R = device registry + owner sigs (+ server PoP attestation), no World ID. U = R + per-tx PoH uniqueness proofs from both roles, verified onchain (recommended). S = R + standalone session proofs (enrolled once, `verifySession` per tx). S+ = session created *bound* to a uniqueness proof at enrollment, then `verifySession` per tx.

| Threat | R | U | S | S+ |
|---|---|---|---|---|
| One owner phone lost/stolen | blocked (needs other owner's registered phone + 2 sigs) | blocked, no change | blocked, no change | blocked, no change |
| One human holds both owners' phones (thief, or owner A takes B's phone); owner keys on the phones | **passes** | needs a 2nd real Orb human for every tx (any accomplice, not B) | needs B's World ID (B's World App + face if `require_user_presence`) | same as S |
| Malware/agent drives both phones while they sit together (nightstand) | **passes** | blocked unless World App on 2 humans' phones is also compromised | blocked, same | blocked, same |
| Bot-farmed / Sybil co-owners: one person enrolls as both owners to fake "2 independent signers" | **passes** (registry only checks 2 different owner addresses) | blocked per tx (needs an accomplice every tx) | **passes** (1 human, 2 sessions) | blocked at enrollment |
| B consents remotely while A carries both phones | passes | passes | passes | passes |
| Owner coerced in person | passes | passes | passes | passes |
| Server key compromised (mints PoP attestations) | passes | still needs 2 live humans onchain | still needs enrolled World IDs | same |
| Cost per Safe tx | ~105-117k gas | + 2 × ~419k | + 2 × ~419k | + 2 × ~419k, and enrollment 2 × ~419k |
| Buildable today | yes | yes (Portal-proven proof shape, onchain replay passes) | IDKit `createSession`/`proveSession` with `.constraints(proofOfHuman)`; PoH in sessions UNVERIFIED | needs a raw bridge request; World App support UNVERIFIED |

The rows where World ID changes the outcome are the reason to pick **Proof of Human** (not Selfie Check, not Passport). The attack is "one actor, or no human at all, stands in for two people". Only PoH (`issuerSchemaId = 1`) has one-per-human uniqueness. Pin it in the guard: the experiment below shows a PoH proof fails as schema 11, so calldata can't swap the schema silently in either direction. That is the pitch for "minimum sufficient credential".

### Experiments (World Chain 480, eth_call at historical block 35464531, spike proof `spike-1790264612780`)

Script: `scratchpad/wsess/run.sh` (session scratchpad). VERIFIED(cast 1.4.3, `https://worldchain-mainnet.g.alchemy.com/public`, 2026-09-26).

| # | Call | Result |
|---|---|---|
| 1 | `verify(...)`, schema 1, baseline | `0x` pass |
| 2 | `verifySession(rpId, nonce, sh, exp, 1, 0, sid=0, [nullifier, action], proof)`, i.e. a uniqueness proof passed as a session proof | revert `0x4a7f394f` `InvalidAction()`. The deployed V2 requires the session "action" top byte = `0x02` |
| 3 | Same, with the action top byte forced to `0x02` | revert `0x7fcdd1f4` `ProofInvalid()` |
| 4 | **`verifyProofAndSignals(..., sessionId=0, proof)`**, selector `0xdef1c2c6` | `0x` pass. The generic entry is **public** on the deployed impl `0xff93a0146bf6E7557B63315efeCe083Ca07D4C73` (selector present in its bytecode, along with `verifySession` `0x9adc603e`; `verifyWithSession` `0x8cd72920` absent) |
| 5 | `verifyProofAndSignals(..., sessionId=1, proof)` | `ProofInvalid()`. `sessionId` is public signal #14, so a bound proof checks against the stored commitment |
| 6 | `verify` with `issuerSchemaId = 11` | `ProofInvalid()` (the schema is bound in-circuit) |
| 7 | `verifySession` with unregistered `rpId = 1` | `ProofInvalid()` (no separate "unknown RP" error) |
| gas | `cast estimate` `verify` / `verifyProofAndSignals` | **419,429 / 419,153** whole-tx, including 21k intrinsic + calldata. Execution alone is ~390k; bridge.md's 288k is `verifyCompressedProof` only |
| now | `verify` at latest block | `0x9dd854d3` `InvalidMerkleRoot()`: proofs must land within the 3600 s root window |

What this settles:
- `verifySession` is live, and it domain-separates session vs uniqueness proofs through the action prefix (`0x02` vs `0x00`).
- A **session-bound uniqueness proof (S+) can be verified onchain today without `verifyWithSession`**: call `verifyProofAndSignals(nullifier, action, rpId, nonce, signalHash, expiresAtMin, 1, 0, sessionId, proof)` and have the guard itself require `sessionId != 0` and `action >> 248 == 0`. That is exactly what the unreleased V3 `verifyWithSession` does (`UnreleasedWorldIDVerifierV3.sol` L52-82, world-id-protocol @ 7ac826e).
- No real session proof was available, so a *passing* `verifySession` is not demonstrated. Cheapest check: in the spike, run IDKit `createSession` then `proveSession` with `.constraints(CredentialRequest(ProofOfHuman, signal))`, then `cast call verifySession` within 1 h. (Presets throw for session flows: `idkit js/packages/core/src/request.ts:709`. Constraints work: `idkit rust/core/src/bridge.rs:2720-2770` test builds a PoH session request.)

### Guard spec (U, recommended), added to the POP2 guard from `owner-device-registry`

```solidity
IWorldIDVerifier constant WID = IWorldIDVerifier(0x00000000009E00F9FE82CfeeBB4556686da094d7); // 480 only
uint64  immutable RP_ID;            // our rp_id as u64 (spike: 0x1469245f4f78143c, registered in RpRegistry 0xD9A2…BbC)
uint64  constant  POH = 1;          // issuerSchemaId, pinned
struct Human { uint256 nullifier; uint256 nonce; uint64 expiresAtMin; uint256[5] proof; }
// appended to the signatures tail, or passed in a module call:
//   Human hA, Human hB, uint256 actionField, bytes16 sid, uint64 notBefore
// guard:
//   sessionNonce = keccak256(abi.encode("pop-ctx-v1", block.chainid, address(this), safeTxHash, notBefore, sid))   // bridge.md §4
//   shA = uint256(keccak256(abi.encodePacked(sessionNonce, bytes1('A')))) >> 8;  shB likewise with 'B'
//   require(actionField >> 248 == 0 && !usedAction[actionField]); usedAction[actionField] = true;
//   WID.verify(hA.nullifier, actionField, RP_ID, hA.nonce, shA, hA.expiresAtMin, POH, 0, hA.proof);   // reverts on failure
//   WID.verify(hB.nullifier, actionField, RP_ID, hB.nonce, shB, hB.expiresAtMin, POH, 0, hB.proof);
//   require(hA.nullifier != hB.nullifier);
//   require(sha256(abi.encodePacked("pop-pair-v1", min(nA,nB), max(nA,nB))) == attested pairTag);        // glue to server PoP attestation
```

- The signal is recomputed from `safeTxHash`, never read from calldata, so a proof can't be moved to another tx. The `nonce` (RP nonce) is not checked by the verifier; binding comes from the signal. Replay of the same tx is already prevented by the Safe nonce, and `usedAction` blocks reuse of one session.
- The action stays `"pop:" + sid`, as in `docs/pop-human-adapters.md`. The guard only needs A.action == B.action and unused. It needs no string rebuild.
- The server still pins `environment == "production"` and the nullifier checks offchain. The chain repeats the parts that matter.
- Demo chain is **480** (the only v4 verifier). A 4801 demo can't have onchain World ID. There, fall back to the server bit and say so on the slide.

### Option S+ (stretch: "the enrolled distinct humans")

- Enrollment (once per owner): a uniqueness proof with action `"safe-enroll:" + chainId + ":" + safe`, with `session_id: "create"` in the request. The guard verifies it with `verifyProofAndSignals(..., sessionId≠0)`, stores `ownerSession[safe][owner] = sessionId`, and requires distinct nullifiers across owners.
- Per tx: `verifySession(RP_ID, nonce, sh_i, exp, POH, 0, ownerSession[safe][owner_i], [sNull, randAction], proof)`.
- This moves the "one human carries both phones" row from "needs any accomplice" to "needs B personally", and fixes the Sybil row permanently.
- Blockers, both UNVERIFIED:
  1. IDKit 4.3 maps uniqueness requests to `SessionRef::None` (`bridge.rs:747-756`). We would have to hand-build the bridge `proof_request` with `proof_type:"uniqueness", session_id:"create"`, which protocol primitives accept (`world-id-protocol crates/primitives/src/request/mod.rs:601`). Whether World App honours it is unknown.
  2. Whether World App issues PoH credentials inside session flows.
- Cheapest check for both: one run with the spike Android app and a patched idkit-core request, then `cast call` within 1 h.

## wallet-log-sync-rpc-limits

**Answer.** Don't make tree correctness depend on any one RPC's log caps. Two layers:

1. **Primary: read the trees from contract views, not logs.** `PresencePool` keeps an append-only `uint256[]` per tree (state, presence, ASP) next to each LeanIMT, and exposes `leavesRange(uint8 tree, uint256 start, uint256 count) view returns (uint256[])`, `treeSize(uint8)` and `treeRoot(uint8)`. The wallet pins one block `B = eth_blockNumber - 2`, reads pages of 1,000 leaves with `eth_call` at `B`, rebuilds with `@zk-kit/lean-imt`, and asserts `localRoot == treeRoot(t)` and `localSize == treeSize(t)` at `B`. Any public 480 RPC works, including the Alchemy public URL every note uses, because eth_call has no range cap. Cost: one extra fresh SSTORE per insert, about 22k gas, so under $0.001 on 480. It also removes the need for a deploy block.
2. **Fallback / tail: logs, chunked, with the same root check.** Log RPC = `https://worldchain-mainnet.gateway.tenderly.co`, 10,000-block chunks (0xbow SDK default `blockChunkSize: 10000`, `packages/sdk/src/types/rateLimit.ts:46`), from `deployBlock` in the deploy JSON. On any error, drop to `https://480.rpc.thirdweb.com` at 1,000-block chunks. Cache leaves to disk keyed by (pool address, tree, lastBlock). A sync is done only when the rebuilt root and size equal `currentRoot()` / `currentTreeSize()` read with `eth_call` at the sync's `toBlock`. If they don't match, redo the sync from the cache start. Never ship a proof before this check passes, which is the guard against `UnknownStateRoot`.

**Measured on 2026-09-26, head ≈ 35,536,000** (`$S/gl.py`, `$S/sync.py`; `$S` = session scratchpad; VERIFIED by curl/python against each URL):

| RPC | getLogs cap (actual) | Notes |
|---|---|---|
| `worldchain-mainnet.g.alchemy.com/public` | **100 blocks inclusive** (`to-from = 99` ok, `= 100` rejected, -32600) | ~0.22 s/call. 3,000 blocks = 31 calls in 6.7 s. 10k blocks ≈ 100 calls ≈ 22 s; 50k ≈ 110 s |
| Alchemy **keyed free tier** | **10 blocks** for "other chains"; 10,000 on PAYG | VERIFIED https://www.alchemy.com/docs/reference/eth-getlogs. So "use a keyed Alchemy URL" is *worse* than the public one unless it's PAYG |
| `worldchain.drpc.org` (free) | a 101-block range (`to-from = 100`) passed; 200 blocks and up are rejected with the misleading message "ranges over 10000 blocks are not supported on free plan" (code 35) | Also gave "Temporary internal error" once. Don't use it |
| `480.rpc.thirdweb.com` | **1,000 blocks** (`to-from = 1000` ok, 10,000 rejected, -32005) | 20k blocks = 21 calls in 7.5 s, same 40 logs as Tenderly |
| `worldchain-mainnet.gateway.tenderly.co` | **no block cap** (5,000,000 blocks → 4,796 logs in 3.4 s); **20,000-result cap** with error -32602 "Query returned more than 20000 results. Try with this block range [...]" | Headers: `x-tdly-limit: 20` weighted units per window per IP, `x-tdly-egress-limit: 1000000000` = **1 GB/day per IP**. Our tests used ~34 MB of it. A web-search summary said "3,000 results"; we observed 20,000. The docs page I fetched (docs.tenderly.co/node/pricing) doesn't say. UNVERIFIED which figure is documented |
| `worldchain-mainnet.public.blastapi.io` | dead: "Blast API is no longer available" | — |
| `worldchain.api.onfinality.io/public`, `rpc.worldchain.dev` | empty reply / no answer | — |

**Unknown unknowns found:**
- **Tenderly returned a silently truncated result.** A WETH (`0x4200…0006`) query over 50,000 blocks returned `n=3` logs, all in the last block, **with no error**, twice in a row. A few minutes later the same query returned the proper >20k error. A client that trusts `result` would build a short tree. That's why the root/size check is mandatory, and why views beat logs. VERIFIED (`gl.py`, WETH, `H-50000..H`)
- **Venue NAT.** Tenderly's keyless limits are per IP. At a hackathon everyone shares the venue IP, so both the 20 units/window and the 1 GB/day egress are shared with strangers. Expect 429s on stage. The views path over Alchemy public avoids this. Otherwise, hotspot the laptop.
- **`LeafInserted(uint256 _index, uint256 _leaf, uint256 _root)` has no indexed fields, and `_index` is the size *after* the insert** (`State.sol:151` emits `_merkleTree.size`). So the position is `_index - 1`. Order by `(blockNumber, logIndex)`, not by `_index` alone. VERIFIED (0xbow `packages/contracts/src/contracts/State.sol`)
- **ASP tree has no insert event in 0xbow.** Our fork inserts the ASP label on deposit, plus `LABEL_TRANSFER` in the constructor, which emits nothing. A log-based mirror must seed leaf 0 = `LABEL_TRANSFER` and then append each `Deposited._label` (`IPrivacyPool.sol:39`) in log order. The views path makes this moot. If logs are kept, emit an explicit `AspInserted(index, leaf, root)` so the mirror can't drift.
- **zk-kit `LeanIMTData` has no index→leaf storage.** It keeps `sideNodes` and `leaves` (leaf→index+1). A leaf list can't be read back without the extra array. VERIFIED (`@zk-kit/lean-imt.sol/InternalLeanIMT.sol:7`)
- **The 0xbow SDK already chunks.** `DataService.generateBlockRanges` + `fetchLogsWithRetry` do exponential backoff (`packages/sdk/src/core/data.service.ts:411-470`). Reuse it with `blockChunkSize: 10000` against Tenderly, or 1000 against thirdweb. With 100 against Alchemy public it works, just slowly. It does **not** check the root afterwards; add that.
- Root history is 64 (`ROOT_HISTORY_SIZE`). If more than 64 inserts land between the sync and the tx, the proof's root expires. That won't happen on stage, but re-sync right before proving anyway.

**Cheapest next step:** add the three views to `PresencePool`. Then add a `wallet sync --verify` test in forge/anvil that seeds 2,000 decoy leaves and checks views-sync == log-sync == `currentRoot()`. Run it once against 480 after seeding the decoys and before recording.

## presence-poster-owner

Status: RESOLVED (decision + fork-tested prototype). Checked 2026-09-26 against HEAD `847400e` (app P2 landed) / server `ba81f84` (clean).

### Decision
- **Poster = `poolposter`, a loop inside the laptop wallet package (`poolwallet`, TS + viem).** Not in `server/`. Not in the ENS lane.
- **`postPresence` becomes permissionless, gated by a server P-256 signature**, not by `msg.sender == ATTESTER`. The poster's key only pays gas. This replaces `onlyAttester` / `address ATTESTER` in pool.md §5 and supersedes H8's "S calls postPresence" and the "alternative, not chosen" line in `## laptop-wallet-phone-pop-handoff`.
- Signing key = `POP_ATTEST_KEY`, the same P-256 key and 0x100 precompile the SAFE guard uses (POP2), with its own domain tag. So the server needs **no web3 / eth-account**. `cryptography>=43` (already in `server/pyproject.toml`) signs it. VERIFIED (pyproject read; signer below uses only `cryptography`).
- One 480 gas key, `RELAYER_PK`, lives in `poolwallet` and is also the key that relays `pool.transfer` (pool.md §4.2 step 6). One process, one sender, one nonce owner on 480. The ENS lane's Sepolia hot key stays separate.

### Why not the other two options
- **Inside `_finalize`**: the ENS lane already puts `ens_hook` there (`docs/ens-meetings-design.md:465`), needs web3/eth-account plus an async worker in the server, and a trusted onlyAttester key. Two lanes in one function; no gain.
- **ENS lane's `web3==8.0.0` worker**: couples POOL to whether ENS ships (ens-lane-collision says ENS may be dropped). And a Sepolia worker is the wrong chain.
- **Sidecar with an onlyAttester key reading an unsigned endpoint** (the suggested method as written): if it sits in the laptop wallet, the payer's machine holds the key that makes presence true, so the payer can post any leaf. The signed attestation removes that. Cost: +P-256 verify, about 7k gas.

### Contract change (pool)
```solidity
uint256 public immutable ATTEST_QX; uint256 public immutable ATTEST_QY;   // POP_ATTEST_KEY, from /v1/config
mapping(uint256 => bool) public presencePosted;
error BadAttestation(); error Expired(uint64 expiry); error LeafAlreadyPosted(uint256 leaf);
event PresencePosted(uint256 indexed index, uint256 leaf, uint256 root, bytes32 pairTag);

function presenceDigest(uint256 leaf, bytes32 pairTag, uint64 expiry) public view returns (bytes32) {
  return sha256(abi.encodePacked("pop-pool-v1", block.chainid, address(this), leaf, pairTag, expiry)); // 135-byte preimage
}
function postPresence(uint256 leaf, bytes32 pairTag, uint64 expiry, bytes32 r, bytes32 s) external {
  if (block.timestamp > expiry) revert Expired(expiry);
  if (presencePosted[leaf]) revert LeafAlreadyPosted(leaf);
  (bool ok, bytes memory ret) = address(0x100).staticcall(abi.encode(presenceDigest(leaf, pairTag, expiry), r, s, ATTEST_QX, ATTEST_QY));
  if (!ok || ret.length != 32 || abi.decode(ret, (uint256)) != 1) revert BadAttestation();
  presencePosted[leaf] = true;
  _presence._insert(leaf); /* push root */ emit PresencePosted(idx, leaf, root, pairTag);
}
```
- Preimage: `"pop-pool-v1"`(11) ‖ u256 chainId(32) ‖ pool(20) ‖ u256 leaf(32) ‖ pairTag(32) ‖ u64 expiry BE(8) = 135 bytes. sig = P-256 ECDSA over the prehashed digest, raw r‖s. The 0x100 precompile does not check low-s, so no normalization is needed.
- The leaf already binds the transfer (ctx = sha256(... ‖ pool ‖ leaf)), so the digest needs no ctx or nonce.
- Vector: key `0xC0FFEE`, chain 480, pool `0x5615dEB798BB3E4dFa0139dFa1b3D433Cc23b72f`, leaf = the handoff test leaf `1101132041…625042`, pairTag `0x33…33`, expiry 1790000000 → digest `0xcf8db6e6efb8aade57d4e3c37fbc30f447ba14ac1bd97cb11bd2d776a3d6e1aa`. Solidity `digest()` == Python hashlib. VERIFIED (forge test, below).
- **0x100 is live on World Chain.** `eth_call` to `0x…0100` with a valid vector returns `1` on both 480 and 4801. VERIFIED (`cast call 0x…0100 <d‖r‖s‖qx‖qy> --rpc-url https://worldchain-{mainnet,sepolia}.g.alchemy.com/public` → `0x…01`). Local anvil needs `--hardfork osaka`, or 0x100 is empty and every post reverts `BadAttestation`. VERIFIED (hit it).

### Server change (in WID-S; no new deps, `_finalize` untouched)
1. `SessionIn.consumer = {kind:"pool-xfer", chain_id, address, leaf}` (already in the handoff checklist). The server recomputes the ctx.
2. `store.py`: table `ctx_sessions(ctx_hex TEXT PRIMARY KEY, session_id TEXT NOT NULL)` + `claim_ctx(ctx, sid) -> bool` and `ctx_session(ctx) -> sid | None`. `create()` claims it. The claim is refused (409 `context_in_use`) while the holder session is still open or ended NEAR. It can be re-claimed after a final NOT_NEAR/abort, or once the join token expired unused. This is the "refuse duplicate ctx" rule, enforced in the server.
3. New public route **`GET /v1/ctx/{ctx_hash}/attestation`** (no device auth). It looks up the sid via `ctx_session`, then returns the same redacted body as WID-S.6 `GET /v1/session/{sid}/attestation` (which stays for the SAFE viewer). The wallet knows the leaf, so it knows the ctx, but never learns the sid (phones create the session in H5). Lookup by ctx avoids one more phone→laptop hop. The ctx is unguessable before the leaf is public, so this leaks nothing new.
   - 404 `unknown_ctx` → no session yet (the poster keeps polling).
   - `{state, verdict}` while running or after a non-NEAR end.
   - On NEAR + human policy OK: add `consumer: {kind, chain_id, address, leaf, att: {v:"pop-pool-v1", pair_tag, expiry, r, s}}`. The signature is computed **in the GET handler** from the stored record, with `expiry = finished_s + POP_POOL_ATT_TTL_S` (default 900). So nothing in `_finalize` changes (the ENS lane owns that hook). `pair_tag` = `s["human"].pair_tag`. If the policy requires World ID and it's missing → no `att`, `reason:"human_missing"`.
4. `/v1/config` adds `attest: {alg:"p256", qx, qy}` (the SAFE lane needs the same thing; one field serves both).
5. Tests: `tests/test_pool_attestation.py`. Digest vector above; the claim and re-claim rules; no `att` on NOT_NEAR; no auth needed.

Server-lane coordination: the ZK workflow (`pop-zk-readiness`) has no chunk left that owns `server/` (last was S7 `ba81f84`, `git status server/` clean; app P2 landed as `847400e`). VERIFIED (`git log`, `git status`). So these edits are not in *its* freeze. They belong to the World ID lane's WID-S package, and ENS rebases onto it (per `## integration-freeze-point` / `## ens-lane-collision`). Nothing here touches `_finalize` or `zk_record`, which are the ENS hook points.

### Poster loop (`poolwallet poster`, prototype `scratchpad/poster/poolposter.mjs`)
- Input: the ctx (hex) of each pending transfer the wallet built in H2/H3. Start polling **before** the phones pair.
- Loop per ctx: `GET /v1/ctx/{ctx}/attestation` every 500 ms. Retry on 404 or fetch errors. Stop on a final non-NEAR, or when `now > expiresAt` of the popctx1.
- On `att`: check `kind == "pool-xfer"`, `chain_id == 480`, `address == pool`, and `leaf == the wallet's own leaf` (never post a leaf the wallet didn't build).
- Then **through one serial queue** (the only nonce owner): `readContract posted(leaf)` → skip if true; `simulateContract postPresence` → decode the named error; `nonce = getTransactionCount(pending)`; `writeContract({...request, nonce})`; `waitForTransactionReceipt({pollingInterval: 500, timeout: 60_000})`. Then the same queue sends `transfer` after the proof (H9).
- **Don't** use viem's `nonceManager` with concurrent sends. In the first run, two sessions for the same leaf raced: one failed after it had taken a nonce, which left a gap, and the next two sends failed "nonce too high". Serial queue + pending nonce fixed it. VERIFIED (prototype runs 1 and 2).
- Fee: viem defaults on 480 are fine (base fee ~257k wei at the time of test). Budget: postPresence ≈ 60–78k gas here (+ LeanIMT insert in the real pool, pool.md §6: ~60–100k).

### Evidence (scratchpad `poster/`)
- `forge test --fork-url https://worldchain-mainnet.g.alchemy.com/public` (osaka, solc 0.8.28): 5/5 PASS. Covers digest vector; post from an arbitrary sender (60,122 gas); duplicate → `LeafAlreadyPosted`; wrong leaf → `BadAttestation`; expired → `Expired`. VERIFIED.
- End to end on an anvil fork of 480 (`--hardfork osaka --block-time 2`), with a mock of the attestation endpoint signing via Python `cryptography` and viem 2.56.8. Sessions s1..s5 plus an unknown one, where s4 = same leaf as s1 and s5 = same leaf as s2. Result: s5 posted (nonce 2, 77,833 gas, 1.18 s after ready), s1 posted (nonce 3, 60,721 gas, 3.3 s, queued behind s5), s2/s4 "leaf already posted, skip", s3 "NOT_NEAR, nothing to post", unknown "unknown". VERIFIED (`node poolposter.mjs s1 s2 s3 s4 s5 nope`).
- The prototype mock polls by sid. The real route is by ctx (step 3 above); same body.

### Remaining unknowns and the cheapest checks
- Server behind a laptop/venue network: the poster needs to reach the server URL. It does already, since the wallet runs on the same demo laptop. Check the venue network once (`## venue-acoustics-network`).
- `POP_ATTEST_KEY` gen and storage: shared with SAFE. Whoever does the SAFE server package makes it once (`data/attest.key`, 0600). Not a POOL item.
- Real LeanIMT insert gas inside `postPresence`: measure when the pool contract is assembled (`forge test --gas-report`).

## same-action-reproof

**Answer: both notes are half right. Same human + same action always gives the same nullifier (it's a deterministic OPRF output). The World ID app hands it out again for 10 minutes after the first proof. After that it refuses with `nullifier_replay`. The Portal `/api/v4/verify` never refuses a reused nullifier. It returns `success: true` with `"message": "Proof verified successfully (nullifier reuse)"`. Enforcing one-time use is the RP's job.**

Evidence from source (no phone test yet):

- **Authenticator (World App core = walletkit).** `worldcoin/walletkit` v0.24.1 @9c7a59d (2026-09-24), `crates/walletkit-core/src/authenticator/mod.rs:629-690`:
  - It generates the nullifier, then checks `store.is_nullifier_replay(nullifier, now)`. If that hits, it returns `Err(WalletKitError::NullifierReplay)` (serialized as `"nullifier_replay"`, `error.rs:97-99`).
  - On success it calls `replay_guard_set(nullifier, now)`.
  - VERIFIED(read source)
- **Grace window.** `storage/cache/nullifiers.rs:17-27,37-45`:
  - `REPLAY_REQUEST_NBF_SECONDS = 600`. The lookup only counts entries with `inserted_at < now - 600`, so a re-proof within 10 minutes passes and returns the same nullifier. The comment says this is on purpose: "a proof that failed to reach the RP can be retried".
  - The TTL is 1 year.
  - The guard is a **local SQLite cache on the phone**, not a network pool. It is idempotent: the first insert time is kept, so re-proving inside the window doesn't extend it.
  - VERIFIED(read source)
- **Protocol spec.** `world-id-protocol` @7ac826e `docs/world-id-4-specs/README.md:78,159,175,328`:
  - "Authenticators will not issue a nullifier more than once."
  - The planned "Oblivious Nullifier Pool" service does not exist in the repo. Services are only gateway, indexer, oprf-node, relay and faux-issuer.
  - `crates/authenticator/src/prove.rs:267-290` leaves the replay check to the caller ("The caller must ensure the nullifier has not been used before").
  - VERIFIED(read source)
- **IDKit.** It maps both `"nullifier_replayed"` and `"nullifier_replay"` to `AppError::NullifierReplayed` (`idkit rust/core/src/error.rs:198`). JS exposes `IDKitErrorCodes.NullifierReplayed = "nullifier_replayed"`. So the RP sees a normal IDKit error, not a proof. VERIFIED(read source)
- **Portal v4.** `worldcoin/developer-portal` @cb3305e (2026-09-25), `web/api/v4/verify/uniqueness-proof/handler.ts:222-270`:
  - It runs `CheckNullifierV4`. If the nullifier exists, it skips the insert and returns HTTP 200 `success: true`, with the original `created_at` and `"(nullifier reuse)"`.
  - A unique-constraint race is also treated as success.
  - Portal-registered actions still have `max_verifications`. Dynamic `pop:<sid>` actions are auto-created on first verify and have no counter.
  - VERIFIED(read source)
- **Onchain.** `WorldIDVerifier.verify(...)` is `external view` (`IWorldIDVerifier.sol:96-106`) and stores nothing. The RP contract must keep `mapping(nullifier=>bool)`. VERIFIED(read source)
- **Docs.** "The same person verifying the same action always produces the same nullifier" and "your backend must check that the nullifier hasn't been used before" (docs.world.org idkit/integrate, Step 6). The 4.0 migration doc says "nullifiers are one-time-use… `session_id` is the stable link across requests". VERIFIED(scratchpad `wid/world-id_idkit_integrate.md:433-437`, `wid/world-id_4-0-migration.md:26-34`)

Still UNVERIFIED:

- (a) That the shipping World App build uses walletkit ≥ the version with this 10-min NBF. The replay guard exists, but the exact window in production is unconfirmed.
- (b) Whether a reinstall or phone restore wipes the guard. It's a local cache, so probably yes.
- (c) The exact error the RP sees.

Cheapest check: ~/dev/worldid-spike, one Orb human, action `reproof-test-<ms>`.

1. Prove, then prove again within 2 min. Expect the same nullifier, and Portal 200 with "nullifier reuse".
2. Wait 11 min and prove again. Expect IDKit error `nullifier_replayed`, no proof.

About 15 min.

Design impact:

- **SAFE "fixed action per Safe, re-proved every tx" is dead.** It only works within 10 min of the first proof. For "the same humans who enrolled", use **session proofs**: create a session with the uniqueness proof at enrollment, store `session_id` per owner, then `verifySession` on each tx. The other option is per-tx actions (`pop:<sid>`), comparing the nullifiers only for distinctness, not identity.
- **Per-session `pop:<sid>` retry.**
  - Within 10 min of the phone's first World ID proof, the phone can re-prove the same sid+role and gets the same nullifier. So the server must treat "same nullifier, same sid, same role" as **idempotent OK**, not as a replay.
  - Reject the nullifier only when it shows up under the other role, or for a different signal. Portal gives no help here because it says 200 either way.
  - After 10 min, or on `nullifier_replayed`, the app must start a new sid.
- **ENS "same nullifier again → relink" recovery** works only inside 10 min. Real recovery must use session proofs (`session_id`), which is what World's migration doc prescribes.
- **Sybil safety comes from our own nullifier table (server DB or contract mapping), never from the World App.** The app-side guard is a local cache and a privacy feature, not a security boundary.

## analog-relay-wormhole

**Answer: yes.** Two colluding people with genuine, attested phones can get NEAR from any distance with an analog audio wormhole (one relay per direction: a mic next to one phone's speaker, a speaker next to the other phone's mic). Nothing in the live pipeline detects it. It needs deliberate hardware and both device owners cooperating. Attestation and World ID don't touch it.

**Pass condition** (server/pop/verdict.py: `flight = c/2 * (half_A/sr_A - half_B/sr_B)`, NEAR iff -20 < flight < NEAR_CM = 60, server/pop/constants.py):

    flight_cm = 34300/2 * (tau_AB + tau_BA)        (mean of the two directions)
    tau_dir   = leg1/c + L_dir + leg2/c
    NEAR iff  mean(L_AB, L_BA) + (leg1+leg2)/c < 1.749 ms

- The budget is the **mean** of the two directions, so they can be unequal. Example: a 2.9 ms digital link one way plus a 0.2 ms wire the other way still passes. UNVERIFIED on hardware; it follows from the formula.
- The "first qualified peak" rule (dsp_ref.measure_arrival) prefers the relay path over any real direct path, because the relay path arrives first. A relay also works between phones 3 m apart behind a wall.

**Experiment.** VERIFIED by simulation (scratchpad `.../scratchpad/relay/relay_sim.py`). It runs the real server DSP (`pop.dsp_ref.measure_arrival`, `half`, `verdict.decide`, jbl250 sounds, 48 kHz). Room A and room B are separate: RT60 0.35 s and 0.8 s. Each phone has its own unknown speaker lag. The chain filter is "wired" (300 Hz–12 kHz cheap transducers) or "fm" (50 Hz–15 kHz). Both legs are 3 cm.

| case | flight_cm | verdict |
| --- | --- | --- |
| genuine 10 / 30 / 100 cm, same room | 8.9 / 28.9 / 99.0 | NEAR / NEAR / NOT_NEAR |
| relay L = 0 ms (wired / fm) | 5.7 / 6.8 | NEAR |
| relay L = 0.5 ms | 22.9 / 23.9 | NEAR |
| relay L = 1.0 ms | 40.0 / 41.1 | NEAR |
| relay L = 1.4 ms | 54.0 / 54.7 | NEAR |
| relay L = 1.6 ms | 60.7 / 61.5 | NOT_NEAR |
| relay L = 3 / 4 ms | ~109 / ~143 | NOT_NEAR |
| relay L = 0.5 ms, legs 1 / 10 / 20 cm | 18.9 / 37.2 / 57.2 | NEAR |
| relay L = 0.5 ms, loop feedback echo at -6 dB | 22.9 | NEAR |

With 3 cm legs, about **1.5 ms of electronic latency still passes**. The only visible trace is the partner matched-filter score: 0.90 genuine vs 0.79 relayed (0.76 with FM band-limiting). The null bar is about 0.1, so it stays far above it. Real partner scores are not calibrated, so this can't serve as a gate.

**Which links fit the budget:**

| link | added latency | passes 60 cm? |
| --- | --- | --- |
| wired analog (mic preamp -> cable -> amp), any km | µs electronics + ~5 µs/km on copper or fiber (physics) | yes, for tens to hundreds of km of fiber in principle |
| analog FM / UHF wireless mic (companded) | "virtually no latency" ([TV Tech](https://www.tvtechnology.com/opinions/avoiding-audio-problems-with-wireless-microphone-systems), UNVERIFIED datasheet value); range ~100 m, so km needs a wire or a repeater | yes |
| Dante / AoIP on LAN or dark fiber | 0.125–0.25 ms network min ([Audinate](https://dev.audinate.com/GA/dante-controller/userguide/webhelp/content/latency.htm), [Q-SYS](https://blogs.qsc.com/systems/2022/07/03/dante-latency-a-few-details/)) + ADC/DAC delay (UNVERIFIED, ~0.3–1 ms) | borderline yes |
| digital wireless mic, e.g. Shure GLX-D | 4.0 ms ([spec sheet](https://content-files.shure.com/Pubs/GLX-D/GLX-D_Specification_Sheet.pdf)) | no on its own (~143 cm); yes paired with a near-zero reverse path (mean rule) |
| Bluetooth, phone or VoIP call, internet | ≥ 20–100+ ms | no |

**What the pipeline could detect (none of it is implemented today):**
- Live server: only `half` + `self_os_delta` reach it. There is no DRR, no room check and no score gate. The research analyzer computes DRR but never gates on it. Without a threshold change, **no detection exists.**
- Tightening NEAR_CM doesn't help. At 20 cm the budget is 0.58 ms, and an analog wire still passes. It only kills digital links.
- Room-signature cross-check: compare the self-hear reverb tail (EDC/RT60 per band) across both files. Same room gives similar tails. A relay gives two rooms, plus a doubled tail on the relayed code. Costs an attacker two matched or dead rooms. It's a speed bump that needs calibration data, and it isn't worth doing for the hackathon.
- Loop-echo check (own code coming back 2·(legs+L) later) is beatable with isolation, and genuine sessions have similar reflections. Weak.
- **Strong fix: a second physical channel whose wormhole is much harder to build.** Example: UWB two-way ranging with 802.15.4z STS (iOS Nearby Interaction / Android UWB). A 60 cm budget there is about 2 ns of RF relay, which is not feasible. Limits: only on UWB phones, and the value comes through the genuine app, not hardware-signed. iPhone↔Android phone-to-phone UWB support is UNVERIFIED. Cheaper speed bumps: a BLE nonce beacon with an RSSI floor, or a Wi-Fi BSSID-set match (Android only; iOS can't scan). Both can also be relayed.

**Design-doc wording (threat table):** "Colluding pair + analog audio wormhole: PASSES. Mean added relay latency < ~1.5 ms (3 cm legs). Needs both owners' genuine phones, both owners cooperating and custom hardware. Mitigation: none in v1; admitted limit; roadmap: UWB STS cross-check, room-signature check."

**Impact:**
- SAFE: low. Everyone who can run the wormhole is a required owner, so they already consent. The PoP guard is aimed at remote key theft, and a thief can't run the relay without both attested phones.
- POOL: high. "Payer and payee met IRL" is exactly the claim colluders can fake. The pitch must say "two enrolled phones were acoustically coupled within ~60 cm, or a deliberate wormhole was built". It can't be sold as compliance-grade proof of meeting.
- research/2026-09-25-cheating-participant-and-trust.md L40 ("outside relayer can only add delay") should gain this row.

**Still open (cheapest way to close):** real hardware confirmation. About $20 bench: 2x MAX9814 electret mic boards + 2x PAM8403 amp + 2 small speakers + 2x 10–50 m audio cable. Phones in two rooms, or 3 m apart with a barrier. Run the real app flow and record flight_cm and partner scores. Expected result from the sim: flight ≈ legs + ~0, NEAR.

## presencepool-e2e-unbuilt

**Answer: yes, it works end to end with real Groth16 proofs on a 480 fork.** I wrote and ran it: deposit (fixed DENOM, label auto-inserted into an onchain ASP LeanIMT), then `postPresence(leaf)` into an onchain presence LeanIMT, then `transfer` (PresenceTransfer proof, 2 inserts: change first, then payee), then a payee withdraw with 0xbow's **unchanged production `withdraw.zkey`** against a *historical* ASP root, then the payer's change withdraw, then a ragequit of an untouched deposit. All green. V(forge test + anvil broadcast, below)

Code, all in the scratchpad (`$S/ppe2e`, `$S` = `/private/tmp/claude-501/-Users-takahiro-ogawa-dev-enconomy/3d9dd236-bf59-4c81-91f5-6bb7c5ebc6e3/scratchpad`). Copy it as the starting point:

- `src/PresencePool.sol` (234 lines): one contract, native ETH, no Entrypoint. Fork of 0xbow `State.sol` + `PrivacyPool.sol` + `PrivacyPoolSimple` @ `d494b63`.
- `src/{WithdrawalVerifier,CommitmentVerifier}.sol`: 0xbow's, byte-for-byte. `src/TransferVerifier.sol`: snarkjs 0.7.5 export, contract renamed, pragma 0.8.28.
- `src/lib/`: `InternalLeanIMT.sol` + `Constants.sol` from `@zk-kit/lean-imt-sol` 2.0.0, and `PoseidonT3/T4.sol` from `poseidon-solidity`.
- `js/prove.mjs` (72 lines): FFI prover. Modes `transfer|withdraw|ragequit`. It rebuilds the trees from the leaf lists with `@zk-kit/lean-imt` 2.2.2 + `poseidon-lite` 0.3.0, runs `snarkjs.groth16.fullProve` and prints the ABI proof. This is also the shape of the laptop-wallet prover.
- `test/PresencePoolE2E.t.sol`: `forge test --ffi -vv` (forks `https://worldchain-mainnet.g.alchemy.com/public`, asserts `chainid == 480`). 2/2 pass in about 14–22 s.
- `script/E2E.s.sol`: the same flow as separate broadcast txs, for real receipt gas.
- `keys/transfer.zkey`: new single-party dev setup (pot18 + 1 contribution; sha256 `0dc708db1dd4657f…`) of `outT/presenceTransfer.r1cs`, which is the LABEL_TRANSFER build: 15,243 constraints, 5 public inputs, 3 outputs. **The old `outT/t.zkey` is stale**: it was made from the label-0 r1cs at 16:02, before the 16:07 rebuild. Don't use it.

### What the run proved (each item is an assert in `test_e2e`)

1. **SCOPE and context in the fork match what the circuits need.**
   - `SCOPE = keccak256(abi.encodePacked(address(this), block.chainid, 0xEeee…EEeE)) % p`, 0xbow's formula with `ASSET = NATIVE_ASSET`.
   - Withdraw `context = keccak256(abi.encode(Withdrawal{address processooor, bytes data}, SCOPE)) % p`, 0xbow's formula and struct shape.
   - The circuit treats context as an opaque public input (`contextSquared`), so any formula works as long as the contract and the prover agree. The production zkey verified with our SCOPE on 480 (`SCOPE = 17246250…755416` in the test run; it changes with the deploy address).
   - Transfer context: `TRANSFER_CONTEXT = keccak256(abi.encode("pop-transfer-v1", SCOPE)) % p`, a per-pool constant. That's fine, because a front-runner who resubmits the proof produces the identical outcome (no value leaves the pool, and the outputs are fixed by the proof). V
2. **ASP handling:**
   - The constructor inserts `LABEL_TRANSFER = 0x706f702d7472616e73666572` as ASP leaf 0.
   - `deposit` inserts `label = keccak256(abi.encodePacked(SCOPE, ++nonce)) % p` right after the state insert.
   - `withdraw` accepts any of the last 64 ASP roots.
   - The test builds the payee's proof, then **a new deposit moves the ASP root** (asserted `proofASPRoot != aspRoot()`), and the relayed withdraw still succeeds. 0xbow's `== latestRoot()` rule would have reverted there. The payee note (label `LABEL_TRANSFER`) passes the unchanged `Withdraw(32)` ASP-membership check. V
3. **LeafInserted order in `transfer`:** `_insert(change)` then `_insert(payee)`. In the anvil receipt (tx `0xea1ecdb1…`, block 35536694), `LeafInserted(3, change=11454960…128747, …)` comes first, then `LeafInserted(4, payee=14271521…710480, …)`, then `Transferred(nullifierHash, change, payee)`. The payee finds its note by matching its own `payeeCommitment` in `LeafInserted`, **not** by position. The `_index` field is 1-based (`size` after insert, as in 0xbow), so the leaf's 0-based position is `_index - 1`. V
4. **Presence gating:**
   - With only an unrelated leaf posted, `prove.mjs transfer` exits non-zero (witness UNSAT). V
   - `postPresence` from a non-attester reverts `OnlyAttester`. V
   - The transfer proof was made against a presence root that was then superseded by another `postPresence`. It still verifies, so the 64-root history on the presence tree works. V
5. Transfer replay reverts `NullifierAlreadySpent`. The payee got exactly `TV` at a fresh address, with `data = abi.encode(recipient, feeRecipient, feeBPS=0)`. The payer's change note (own label) withdrew directly. Charlie's untouched deposit ragequit with 0xbow's production `commitment.zkey`. Final pool balance = the one remaining deposit. V
6. JS↔chain parity: the roots computed by `prove.mjs` from the shadow leaf lists equal `currentRoot()`/`aspRoot()`/`presenceRoot()` (asserted). V

### Gas (real receipts, anvil `--fork-url` 480 at block ~35,536,6xx, separate txs, via-ir, optimizer 10k runs)

| tx | gasUsed |
| --- | --- |
| `deposit` (1st / 2nd / 3rd) | 346,325 / 324,038 / 313,096 |
| `postPresence` (1st / 2nd leaf) | 137,163 / 146,779 |
| **`transfer`** (state tree 2→4 leaves) | **496,015** |
| `withdraw`, relayed, payee note | 453,175 |
| `ragequit` | 277,128 |
| deploy: WithdrawalVerifier / CommitmentVerifier / TransferVerifier / PresencePool | 541,697 / 410,849 / 542,069 / 1,847,667 |

- Verifier `verifyProof` is 234,572 in both the transfer and the withdraw verifier. A PoseidonT3 hash is about 18k; T4 about 34.5k.
- **The 450–500k transfer estimate holds only for a tiny tree.** Each LeanIMT insert costs about 18k × (number of hashes on the path, up to the depth). E: about 600k at 1k leaves, and up to about 850k worst case at depth 10. That's still under $0.01 at 0.0018 gwei on 480.

### Unknown-unknowns this surfaced (act on these)

1. **`poseidon-solidity` compiled by forge with `via_ir` is 40,026 B (T3) / 51,527 B (T4), which is over EIP-170.** `forge test` doesn't enforce the limit, but a real broadcast fails with ``PoseidonT3 is above the contract size limit``. V
   - Fix, verified on the fork: deploy the package's **precompiled** bytecode through the Arachnid CREATE2 proxy `0x4e59b44847b379578588920cA78FbF26c0B4956C` (present on 480). Send `require('poseidon-solidity').PoseidonT3.data` (and the same for T4) as a tx to the proxy. That lands at `PoseidonT3 0x3333333C0A88F9BE4fd23ed0536F9B6c427e3B93` (23,478 B, 5,141,252 gas) and `PoseidonT4 0x4443338EF595F44e0121df4C21102677B142ECF0` (14,189 B, 3,124,614 gas). Neither is on 480 yet (cast codesize = 0).
   - Then link: `--libraries src/lib/PoseidonT3.sol:PoseidonT3:0x3333333C0A88F9BE4fd23ed0536F9B6c427e3B93 --libraries src/lib/PoseidonT4.sol:PoseidonT4:0x4443338EF595F44e0121df4C21102677B142ECF0`.
   - Budget about 8.3M gas once. Anyone can do it, and it's idempotent.
2. The test file needs `via_ir = true` (stack too deep). `PresencePool.sol` itself was compiled via-ir in the run above. 0xbow deploys via-ir too (`profile.optimized`).
3. Forge's in-test `gasleft()` deltas are wrong for a per-tx budget, because one test = one tx and slots stay warm. Use the anvil broadcast numbers above.
4. The ASP insert makes deposits about 25–55k more expensive than 0xbow's (0xbow measured 288,653 via Entrypoint).
5. The payee client can use raw snarkjs with 0xbow's `withdraw.wasm` + `withdraw.zkey` (sha256 `2a893b42…de677`, identical in `final-keys/` and in the SDK's `dist/node/artifacts/`). The 0xbow SDK `proveWithdrawal` also works, **but only if it is fed our onchain ASP tree** (rebuilt from `ASPLeafInserted` events), not 0xbow's ASP API.

### Not covered (still U)

- The World ID gate on `deposit` is not wired. The ERC-20/USDC variant isn't built.
- Only anvil-fork, not a live 480 deploy. The cheapest next step is to run `script/E2E.s.sol` against 480 with a funded key: about 18M gas total including Poseidon, which is about 0.00003 ETH at the current gas price.
- The transfer zkey is a single-party dev setup, so it is not production-sound.

Repro:

```
cd $S/ppe2e
forge test --ffi -vv
# for real gas: anvil --fork-url https://worldchain-mainnet.g.alchemy.com/public --port 8547,
# deploy the two Poseidon libs via the proxy,
# then forge script script/E2E.s.sol --rpc-url http://127.0.0.1:8547 --broadcast --slow --ffi <--libraries …>
```

## demo-actual-trust-level

Status: RESOLVED. Checked 2026-09-26 against server HEAD `ba81f84` (server/ unchanged since).

### Short answer

**Yes.** On the server as it runs today, one person with a laptop script, no phone, no sound and no mic, gets a NEAR record between two "devices". A lent World ID then adds the second human. That is worse than the question assumed:
- **Android attestation is decorative even with `POP_ALLOW_UNATTESTED` off.** `verify_chain` checks that the links sign each other, that the leaf key matches, and the KeyDescription challenge. It does **not** pin a Google root (server/pop/attestation.py L5 docstring, server/README.md "NOT verified: the root pinned to Google's roots... So a self-made chain passes today"). A self-made root → intermediate → leaf gets `attested: true` and any claimed `security_level` (the level is read from the attacker's own KeyDescription).
- **iOS is solid only when the flag is off** and `POP_IOS_APP_ID` is set (Apple root pinned, server/pop/appattest.py). The demo iPhone is on a free team, so it sends `app_attest: null`, and the server **must** run `POP_ALLOW_UNATTESTED=1` (app/README.md L127, server/README.md L19/L90). With the flag on, anyone can enroll any software key as `platform: ios` and get `security_level: secure_enclave` (self-reported).
- **The verdict trusts the phone's `half`.** No audio reaches the server unless the phone chooses to upload it. ZK option A proves the arithmetic over a recording the prover committed to. A synthetic recording is a valid input, so ZK adds nothing against a forger (research/2026-09-25-cheating-participant-and-trust.md "Why ZK can't fix it").
- **So onchain tier 2 gives no protection here.** The server enrolled the forged keys and issues SBcred3 to them. The forged transcripts carry valid signatures by those keys, and a PopBridge recompute says NEAR. This matches `## safe-guard-trust-tier` Why (1).

### Experiment (VERIFIED)

Scratch copy of server/ at `.../scratchpad/trust/server/`, test `tests/test_forge_nosound.py`, run with server/.venv python. 3 passed:
1. `allow_unattested=False`. Two software P-256 keys enroll with self-made Android chains (`tests/phones.make_chain`). Both return `attested: True, security_level: 'tee'`. Then a full POPT v2 run through `tests/sim2.World2`, where the "air" is numpy in one process: **`NEAR 29.78 cm`**, and the result record shows both devices `attested: True`.
2. `allow_unattested=False`, iOS with `app_attest: null` → 400 `enroll_bad_attestation`.
3. `allow_unattested=True`, iOS with `app_attest: null` → 200 `attested: False, security_level: secure_enclave`.

The repo's own fake-phone harness (tests/sim.py, sim2.py, app `LiveServerRunTest.kt`) is a working forger. It needs about 0 lines of new attack code.

### Demo server flags (what it will actually run with)

- `POP_ALLOW_UNATTESTED=1`: **required**, because the iPhone is on a free team. Every runbook in the repo starts the server with it (app/README.md L79/L90, `## pop-works-on-demo-phones` step 2). The value is public: `GET /health` and `/v1/config` return `allow_unattested` (server/pop/main.py L203/L211).
- `POP_IOS_APP_ID` unset (free team has no App Attest). No Play Integrity anywhere (grep: no hits in server/ or app/).
- `POP_ISSUER_KEY_FILE` = `server/data/issuer.pem`, autogenerated on the laptop. The same key signs SBcred3, and per the SAFE design it also signs the onchain POP2 attestation.

### Threat table (for the design doc)

| # | Attack | Blocked by (design) | Demo build (today's server + free-team iPhone) | Production path |
|---|---|---|---|---|
| 1 | **Solo forger, no sound**: script/emulator makes two keys, fakes both transcripts | platform attestation (genuine app + HW key) | **OPEN.** Android: a self-made chain passes (flag irrelevant). iOS: the flag accepts null. VERIFIED above | Android: pin Google roots (legacy RSA roots + new ECDSA P-384 "Key Attestation CA1", in use from 2026-02-01), check `attestationApplicationId` (package + signing digest), `verifiedBootState=Verified`, level ≥ TEE, revocation list `https://android.googleapis.com/attestation/status` (VERIFIED developer.android.com/privacy-and-security/security-key-attestation), or use github.com/android/keyattestation. iOS: paid team, App Attest, flag off. Add Play Integrity / App Attest assertions per session (not implemented) |
| 2 | **One-cheater edit**: genuine partner, cheater's patched app shifts its own code to hide a remote relay | genuine-app attestation | **OPEN** (same hole as 1: a patched APK passes because attestationApplicationId is unchecked) | same as 1. Rooted-but-attesting phone = arms race |
| 3 | **World ID lender**: a remote human does the second World ID proof (cross-device QR sent over chat) | nothing. `signal = sid+role` binds the proof to the session, not to a place | **OPEN** (docs/pop-human-adapters.md L78 admits it). `require_user_presence` proves the lender is at *their* phone, not near ours | **OPEN** in production too. Only mitigation is economic (World ID nullifier per action caps it to 1 session per lender per action). Admit it |
| 1+3 | **Solo forger + lender = onchain presence, no sound** | 1 and 3 together | **OPEN end to end** for POOL. For SAFE, see row 6 | closes only once row 1 closes |
| 4 | **Analog relay wormhole**: colluding pair, genuine phones | nothing in v1 | OPEN (`## analog-relay-wormhole`) | OPEN. Roadmap: UWB STS cross-check, room signature |
| 5 | **Server compromise**: holds issuer + attester key | nothing. The server is the oracle | OPEN (the key lives in a file on the demo laptop) | tier 2 + per-Safe device registry moves trust to "server or app", not zero. HSM/KMS for the issuer key |
| 6 | **SAFE: one owner spends alone** | owner sigs (2-of-2) + `PopSafeGuard` device registry: `devA`/`devB` must be the two owners' devices **registered at Safe creation** (`## owner-device-registry`) | **BLOCKED** if the founding meeting was honest. A forger can't sign as the co-owner's registered device without that phone. The Safe also still needs both owners' signatures. **OPEN** if the attacker controlled creation, e.g. showed a fake "B" device at the founding meeting: B must check their own device id on screen | same. Plus row 1 fixes, so a forged device can't enroll in the first place |
| 7 | **POOL: payer and payee both the attacker** (fake meeting between two own addresses) | attestation + distinct World IDs | **OPEN** (rows 1 + 3). The pool has no registry, so nothing pins keys | closes with row 1. Row 3 (lender) and row 4 (wormhole) stay |

Cheapest demo-day hardening (server workflow owns it; about 30 min; does not break the demo):
1. `POP_UNATTESTED_ALLOW=<device_id,...>`: accept `app_attest: null` only for the pinned demo iPhone's device id. Others get 400. That closes the "any key as ios" door while the iPhone stays unattested.
2. Pin Android `root_sha256` to the Google roots. First read the demo Android's stored `root_sha256` from `server/data/pop.sqlite` after it enrolls, and confirm it is one of Google's (needs the phone, 2 min).
3. Refuse to sign an onchain attestation (POP2 / onchain adapter) unless both devices are `attested: true` **or** in the allowlist. Put an `attested` bit per device in the attestation, so the chain and the viewer can show "iPhone: unattested (free dev team)".

Without these, the demo's honest claim is "the demo server trusts our two enrolled phones".

### Agreed Q&A answer (2 sentences)

"In this demo build the server trusts our two enrolled phones: the iPhone is on a free dev team with no App Attest, so a patched client could fake a meeting. We don't hide that. The fix is the standard one: App Attest on iOS, pinned Google key attestation with app-id and boot-state checks on Android, and in the Safe, the owners' phone keys are pinned at wallet creation, so even today one owner can't fake the other owner's phone."

### Remaining unknowns

- Is the demo Android chain actually rooted at Google, and which root? Cheapest check: after enroll, `sqlite3 server/data/pop.sqlite "select device_id,root_sha256,security_level from devices"` and compare with the roots on the Android doc page above. Needs the phone.
- Whether the server workflow adopts hardening items 1–3 before freeze. Ask it, and hand it this section.

## signal-0x-hex-semantics

**Answer: resolved offline. All five implementations hash the same bytes when the signal is `"0x" + lowercase hex(nonce32 ‖ role1)`.** Kotlin 4.0.7, Swift 4.0.11, JS idkit-core 4.2.4, Python `keccak>>8` and Solidity `uint256(keccak256(abi.encodePacked(...)))>>8` all give the same field element. The only step not yet run is one live Portal `/api/v4/verify` from a phone with this signal. It needs World App on a device.

**The `0x` rule is already in both pinned SDKs.** It is not new at HEAD. It landed in `e516ddb` "fix: align rust signal hashing (#226)" on 2026-04-26. It first shipped in Swift 4.0.8 and Kotlin 4.0.4. VERIFIED(`git log -S decode_prefixed_hex_signal`, `git tag`/log in scratchpad idkit clone). Between release commits `7ba4912` (Kotlin 4.0.7) and `2cd8a91` (Swift 4.0.11), `rust/` is identical (`git diff 7ba4912 2cd8a91 --stat -- rust/` is empty). HEAD `16bc527` only adds the Self Check response variants to `types.rs`. The signal code is unchanged. VERIFIED(git diff).

### Exact rule (idkit-core at 7ba4912, `rust/core/src/types.rs:81-156`, `crypto.rs:326-359`)
- `Signal.fromString(s)`: if `s` starts with **lowercase** `0x`, the rest is non-empty, the rest has even length, and `hex::decode` succeeds (upper- or lowercase digits), then the input is those raw bytes. Anything else is the UTF-8 bytes of `s`. So `0X…`, odd length, a bare `0x`, and hex with no prefix are all hashed as text.
- `Signal.fromBytes(b)`: the input is `b` as given.
- The hash is `keccak256(input) >> 8`, printed as `0x%064x` (lowercase, 66 chars).
- **Every preset takes `signal: String?` and calls `Signal::from_string`** (`preset.rs:247-284`). This covers Kotlin `Preset.ProofOfHuman(signal=)` and Swift `.proofOfHuman(signal:)`, so the `0x` string form is what the spike's call path actually uses. To pass raw bytes you have to use the constraints builder with `CredentialRequest(type, Signal.fromBytes(bytes))`. Both routes produce the same hash.
- v4 path: `CredentialRequest.to_protocol_item` sends the **decoded bytes** as `RequestItem.signal` (hex-serialized). World App hashes them again with `FieldElement::from_arbitrary_raw_bytes` = keccak>>8 (world-id-primitives 0.11.0, `lib.rs:147`, `request/mod.rs:217`). The legacy v3 fallback hashes `legacy_signal` with the same `from_string` (`bridge.rs:663-667`). This is consistent across all three places. VERIFIED(source)

### Canonical form (pin this in the design doc)
- `role` = `0x41` ('A') or `0x42` ('B'), the same byte as POPT offset 5.
- Base signal, 33 bytes: `abi.encodePacked(bytes32 sessionNonce, bytes1 role)`.
- SAFE variant, 65 bytes, only if we bind the tx: `abi.encodePacked(bytes32 sessionNonce, bytes1 role, bytes32 safeTxHash)`.
- Phone: `signal = "0x" + bytes.toHex().lowercase()` passed to the preset. Always lowercase `0x`. Never build it from `sid:role` text.
- Server (Python): `expected = "0x%064x" % (int.from_bytes(keccak(nonce + role [+ safeTxHash]), "big") >> 8)`.
- Guard (Solidity): `uint256(keccak256(abi.encodePacked(nonce, role[, safeTxHash]))) >> 8`.

### Golden vectors (nonce = 0x0102…1f20, i.e. bytes 1..32; safeTxHash = 0xa0a1…bebf)
| case | input bytes hashed | signal_hash |
|---|---|---|
| role A: `0x` string, or bytes | `0102…1f20 41` | `0x00f1e798c6ed3bcb906f718970b751a4bd52fb795009c0657e4fc870ff8921bf` |
| role B | `0102…1f20 42` | `0x00923edef036657804affe6b100f9464df1905cd8ed80cd216d884fafb241ad6` |
| A + safeTxHash | `0102…1f20 41 a0…bf` | `0x00a24848399c2b94d69eac4b4ebdfb44f38264433811047392a099b6863b4ccb` |
| `0x` + UPPERCASE hex digits, A | decoded, same as row 1 | `0x00f1e798…ff8921bf` |
| TRAP `0X…` prefix, A | UTF-8 of the text | `0x0021662d45d184b724d907f59dcbec0e412c41b1b93d79ef5c9554d0ad5da7c6` |
| TRAP hex with no `0x`, A | UTF-8 of the text | `0x008804cb60edef661a2000ac23607d21b291240d0324375ec0f1ce747838c570` |
| TRAP server hashes the `"0x…"` text as UTF-8 | UTF-8 | `0x00febab5de664b471093ddb6c4b360a6d6396310ebe818a649341cf1085c69a7` |
| `sess_0102:A` text | UTF-8 | `0x001210cd8d7bee0c8a28d3b79a9f7ff9f653c7e276b00156f7aef96a9c86471e` |
| `spike` (old spike constant) | UTF-8 | `0x0022ec8cb931f2fe813df7a9380c0ead38cf6d798b02260c0f9c08f3fb50b989` |

Who reproduced these, all VERIFIED by running them in the scratchpad (`sigvec/`):
- Rust idkit-core at `7ba4912`: `hash_signal`, and `to_protocol_item().signal_hash()` agrees (`sigvec/idkit-407/rust/core/examples/golden.rs`).
- **Kotlin**: the 4.0.7 AAR's own `classes.jar` (`~/.m2/.../idkit-4.0.7.aar`, which the spike's `build-idkit-from-source.sh` built from source at `7ba4912`). Its `IDKit.hashSignal(String|ByteArray)` ran on the JVM through JNA against a host `libidkit.dylib` built from the same commit (`sigvec/aar/Vec.kt`).
- **Swift**: the published `github.com/worldcoin/idkit-swift` tag 4.0.11, binary `IDKitFFI.xcframework` (checksum `98849ec5…b682`, macOS slice). `IDKit.version == "4.0.11"`. `hashSignal(String|Data)` checked (`sigvec/swvec`).
- JS: `@worldcoin/idkit-core` 4.2.4 `hashSignal`.
- Python: `eth_hash`.
- Solidity: forge test (`sigvec/sol/test/Sig.t.sol`, PASS).

Not covered: the GitHub Packages 4.0.7 AAR binary itself (it needs a `read:packages` token). It is built from the same release commit, so expect the same result. UNVERIFIED binary identity.

### Server/guard consequences (they matter more than the SDK question)
1. **Portal v4 does not recompute the signal.** It checks the ZK proof against whatever `signal_hash` the request body carries, and defaults it to `0x0` when the field is missing. It also rejects uppercase hex (`/^0x[\dabcdef]+$/`). VERIFIED(developer-portal `cb3305e`, `web/api/v4/verify/request-schema.ts:19-21,75-78`, `uniqueness-proof/verify-v4.ts:28`). So **the server must put its own computed `expected` into `responses[i].signal_hash` before calling Portal. Alternatively it can check that the phone's value equals `expected`.** If it forwards the phone's value unchecked, a proof made for any other signal passes. Today neither `server/` nor the spike backend checks signal_hash at all. VERIFIED(grep, no hits).
2. The guard and the pool contract compute the hash in Solidity from `(nonce, role[, safeTxHash])` they already hold, and never take a hash from the caller. It matches the SDK byte for byte (forge vectors above).
3. Format the server's hex with `"0x%064x"` (lowercase, zero-padded). That matches IDKit's `{:#066x}` and the Portal regex.

### What remains
- One live run per platform. Set the spike's `Preset.ProofOfHuman(signal = "spike")` to the row-1 vector string (`"0x0102…1f2041"`) and do a real World App flow. Assert that the returned `responses[0].signal_hash == 0x00f1e798…21bf`, then POST to `/api/v4/verify` with the server-computed value. About 10 minutes per phone. It confirms that World App hashes the decoded bytes (source says yes: `RequestItem.signal_hash`).
- Design decision (not a hashing issue): if `safeTxHash` goes into the signal, the World ID step has to run after the tx is fixed. That makes each proof tx-specific, and a new tx needs new proofs.

**Design impact:** pin the byte layout above plus the golden table in the doc. Phones pass the lowercase `0x` string to the preset. The server overwrites or checks `signal_hash` with its own keccak>>8 before Portal verify. The guard recomputes the hash in Solidity. No SDK change or pin bump is needed.

## zk-artifact-persistence

**Headline: the scratchpad set is already broken. Don't copy it; regenerate once and freeze.** VERIFIED (commands below, run 2026-09-26).

- `outT/t.zkey`, `outT/vk.json` and `vgas/src/PresenceTransferVerifier.sol` (IC0x `4791909847…183064`) were built at 16:02 from the **label-0** circuit. `presenceTransfer.circom`, the r1cs and the wasm were changed at 16:07 to `LABEL_TRANSFER = 0x706f702d7472616e73666572` (pool.md §249). Same constraint count (15,243), different circuit.
- `snarkjs zkey verify outT/presenceTransfer.r1cs pot18.ptau outT/t.zkey` gives `INVALID: Circuit does not match`. The same zkey against a label-0 recompile gives `ZKey Ok!`.
- `groth16 prove outT/t.zkey outT/tin.wtns` (current wasm) then `groth16 verify outT/vk.json` gives `Invalid proof`. The old 16:02 `proof.json` still verifies. So every "V2 proof" number (242k gas, the `visible-failure-path` fork test) is the label-0 build. The gas carries over; the keys don't.
- Lesson: **"verifier IC0 == vkey IC[0]" does not catch this.** The verifier and the vkey both came from the stale zkey, so they agree with each other. The gate has to tie the **circuit source** to the zkey (`zkey verify`), and the **wasm** to the zkey (a proof made with the committed wasm is accepted by the committed .sol).

**Canonical home (proposal): a new top-level `pool/`, outside the other workflow's paths.** Plain git, no LFS: git-lfs isn't installed here (`git lfs` gives "not a git command"), the zkey is 8.6 MB and the wasm 2.5 MB, well under GitHub's 50 MB warning and 100 MB block (docs.github.com "About large files on GitHub", UNVERIFIED this session). The root `.gitignore` ignores neither `*.zkey` nor `*.wasm` (VERIFIED `git check-ignore`). It does ignore `/docs` at the root, which doesn't matter here.

```
pool/
  .gitignore                       circuits/build/   contracts/out/   contracts/cache/
  circuits/
    package.json                   pins circomlib 2.0.5, snarkjs 0.7.5 (exact, not ^)
    src/presenceTransfer.circom    + commitment.circom, merkleTree.circom (0xbow copies, include "circomlib/...")
    fixtures/tin.json, tin_over.json, tin_wrongpayee.json
    freeze.sh                      ONE-SHOT setup; refuses if zk/.../presenceTransfer.zkey exists
    check.sh                       CI gate (below)
  zk/presence_transfer/            <- CANONICAL, committed, never regenerated
    presenceTransfer.zkey          8,640,968 B
    presenceTransfer.wasm          2,502,431 B (witness gen for browser/Node wallets)
    vkey.json
    beacon.txt                     World Chain block hash used as the beacon
    MANIFEST.sha256                sha256 of all of the above + .sol + .circom
  contracts/src/TransferVerifier.sol   snarkjs export, renamed, pragma 0.8.28
  contracts/test/TransferVerifierPin.t.sol + fixture.json
```

The payee cash-out keeps 0xbow's `withdraw.zkey`/`WithdrawalVerifier.sol` from the pinned fork commit `d494b63`. Vendor them under `pool/zk/withdraw/` with their sha256, not as a submodule, so a cold clone works.

**ptau: use PSE ppot `ppot_0080_14.ptau` (18,967,698 B), not the 302 MB pot18.** sha256 `3ca1149e9349b22b0ee0649399cfb787677129b7b1189d1899fc0d615d9583db`, URL `https://pse-trusted-setup-ppot.s3.eu-central-1.amazonaws.com/pot28_0080/ppot_0080_14.ptau`. 2^14 = 16,384 ≥ 15,243 constraints + 9 public. VERIFIED: downloaded and hashed it, and a zkey built from pot18 also passes `zkey verify` against it (`ZKey Ok!`, 2 min). So pot14 and pot18 are the same ceremony prefix. Don't commit the ptau. `freeze.sh` downloads it into `build/` and checks the hash. pot18's sha256, for the record: `9693220206afab749e3d88d4ab5fdf5d36120ea102e7e587ccea0e7a5208e711`.

**Freeze procedure, prototyped end to end.** VERIFIED in `scratchpad/zkpersist/proto/pool/`, 1–2 min on the M2:
1. `circom 2.1.8 src/presenceTransfer.circom --r1cs --wasm --O2 -l node_modules`
2. `groth16 setup r1cs ppot_0080_14.ptau t0.zkey`, then `zkey contribute` (64 B of urandom, never written to disk), then `zkey beacon … <World Chain block hash> 10`. Still effectively trusted-by-us, but it's a real phase-2 with a public beacon. Say "single-party + beacon, dev setup" in the README.
3. `zkey export verificationkey` and `zkey export solidityverifier`, then sed `Groth16Verifier` to `TransferVerifier` and `pragma solidity 0.8.28;`.
4. Write `MANIFEST.sha256`, then run `check.sh`.

`check.sh`, the CI gate: all of it passed on the prototype (`ALL CHECKS PASSED`, forge 3/3), and the stale `t.zkey` fails it at step 2:
1. `shasum -c MANIFEST.sha256`
2. Recompile the r1cs from the committed .circom, then `snarkjs zkey verify r1cs ppot14 zkey` must print `ZKey Ok!`. This ties source + ptau to the zkey.
3. `zkey export verificationkey` must `cmp` equal to `vkey.json`.
4. `tin_over` and `tin_wrongpayee` must be UNSAT with the committed wasm (Num2Bits line 56; presence root line 93).
5. `wtns calculate` with the committed wasm, `groth16 prove` with the committed zkey, then `groth16 verify vkey.json`. Write `contracts/test/fixture.json`.
6. `forge test --match-contract TransferVerifierPin`:
   - `test_canonicalProofAccepted`: the committed .sol accepts the fixture proof, and a flipped `payeeCommitment` gives false.
   - `test_ic0MatchesVkey`: the .sol source contains `IC0x = <vkey.IC[0][0]>;` (the 0xbow-style check, kept but not relied on).
   - `test_deployedMatches`: with `--fork-url` and `TRANSFER_VERIFIER=<addr>`, `keccak(addr.code) == keccak(new TransferVerifier().code)`. Run it right after the 480 deploy and put the address in the README.

Determinism: recompiling the unchanged .circom with circom 2.1.8 gave a byte-identical wasm (sha `4fc906fa…` both in outT and in the prototype) and the same circuit hash `28163db6 9424b671…`. VERIFIED on this machine; cross-machine not tested. The gate only depends on the r1cs circuit hash, which `zkey verify` checks.

**Which copy is canonical:** `pool/zk/presence_transfer/*` at the commit that deploys TransferVerifier on 480. Tag it `pool-zk-v1`, record the tag, the MANIFEST sha of the zkey and the verifier address in `pool/README.md`, and copy the MANIFEST into the deploy script's broadcast JSON. Wallets (web/Node: the wasm + zkey; native mopro: the zkey, with witnesscalc built from the same .circom) must load from that path or from a URL, and check the zkey sha256 against the MANIFEST before proving. Belt and braces: attach the zkey/wasm/vkey to a GitHub release for the tag too.

**Rules for implementers**
- Never run `freeze.sh` twice. Any circuit edit after deploy means a new verifier + a new pool (or an upgradable verifier slot). Decide that before deploy: an immutable `TRANSFER_VERIFIER`, as pool.md §5 has it, means a circuit change strands deposits.
- Freeze only after the circuit is final: `LABEL_TRANSFER`, `presDepth=20`, `maxTreeDepth=32`, the public input order `[nullifierHash, changeCommitment, payeeCommitment, stateRoot, stateTreeDepth, presenceRoot, presenceTreeDepth, context]`. Fix the stale "label 0" comment in the header of `presenceTransfer.circom` while at it.
- Don't reuse the prototype zkey (sha `ea877bf2…`) as canonical. It lives in the scratchpad and will be lost, so freeze again inside the repo.
- Throw away `outT/t.zkey`, `outT/vk.json`, `vgas/src/PresenceTransferVerifier.sol` and the hardcoded proof in `vgas/test/T.t.sol` (all label-0).

Remains open: creating `pool/` itself (the next implementation step; nothing written to the repo by me beyond this note); cross-machine wasm determinism (cheap: run `check.sh` in CI on Linux); whether mopro's arkworks loader reads this snarkjs zkey (cheap: `circom-prover` test with the fixture). The prototype scripts are ready to copy: `scratchpad/zkpersist/proto/pool/circuits/{freeze.sh,check.sh}` and `contracts/test/TransferVerifierPin.t.sol`.

## demo-video-capture

Status: mostly resolved. Rule text and the edit question are settled. Two capture risks were found and have workarounds. The iPhone QuickTime workaround and the webcam framing still need a 5 min dry run (steps below).

### Exact rule text (Tokyo 2026)

VERIFIED(curl https://ethglobal.com/events/tokyo2026/info/details, "Tips for a Great Demo Video"):
- "Must be between 2 and 4 minutes: Videos under 2 minutes or over 4 minutes will be automatically rejected during upload."
- "Show your project in action and skip any unnecessary waiting **(The video can be edited to remove any unnecessary waiting)**."
- "Use slides to summarize key points: no more than 4 bullet points per slide."
- Breaking any of these gets the video sent back for re-submission: "DO NOT export … less than 720p (Upload will fail)", "DO NOT exceed the 4-minute submission length (Upload will fail)", "DO NOT speed up the video", "DO NOT play music with text … (instead of talking)", "**DO NOT use mobile phones to record the video submission**", "DO NOT use a text to speech synthesizer / AI Voiceover".

What this means:
1. **Cuts are explicitly allowed. Speed-up is not.** The 45 s approval, the World ID hops (12-28 s, see end-to-end-latency-budget), the proof upload and the block wait can all be jump-cut. Put a small "(cut: 20 s proving)" label on each cut so it stays honest. Fitting under 4 min is a pacing problem, not a rule problem.
2. **"Mobile phones to record."** The wording targets the recording device, meaning a phone camera filming a laptop. Nothing says whether phone-camera B-roll or an on-device screen recording counts. UNVERIFIED either way. The safe reading, which we follow: **no frame of the final video comes from a phone camera.** Screen captures of the phones' own displays show the product itself, so they're low risk, but we still take them from the laptop where we can. Cheapest way to settle it: one message to ETHGlobal staff in Discord (#support or the event channel) tonight: "Our product is two phones meeting. Is a laptop webcam shot of the phones plus phone screen captures OK?"

### Capture plan (all on the laptop, MacBook Air M2 8 GB)

| Feed | Tool | Setting that matters |
|---|---|---|
| Table shot: two phones, hands, both screens visible | MacBook FaceTime HD camera (1080p on the M2 Air) via QuickTime "New Movie Recording" or OBS; laptop screen tilted down or the laptop on a stack of books looking down at the table | Camera only, not Continuity Camera (that's an iPhone camera, which breaks our safe reading) |
| Android screen | `brew install scrcpy` (stable 4.1, not installed yet, VERIFIED `brew info scrcpy`), then `scrcpy --no-audio --no-control --record=android.mp4` over USB (adb present at ~/Library/Android/sdk/platform-tools) | **`--no-audio` is mandatory.** scrcpy forwards audio by default on Android 11+, and the default `output` source "disables playback on the device". VERIFIED(https://github.com/Genymobile/scrcpy/blob/master/doc/audio.md). The PoP beep would go to the Mac and the run would fail. `--audio-dup` exists (Android 13+) but "apps can opt out", so don't rely on it |
| iPhone screen | QuickTime > New Movie Recording > Camera = iPhone, over USB. It's a macOS feature: no Apple developer team, no signing | **Risk: QuickTime mirroring mutes iPhone audio and plays it on the Mac.** An Apple Community report says "Both approaches [QuickTime and AirPlay] disable the iPhone audio when the mirroring begins" (https://discussions.apple.com/thread/255406558, Jan 2024). Our own app, VERIFIED(app/.../AudioEngine.ios.kt `preflight()` + `externalOutput()`), then refuses to run with "Audio goes to <port>. Disconnect it so the phone speaker plays", and a route change during a run aborts with `capture_failed` ("audio route changed", `observe()`). So QuickTime + iPhone will likely block PoP |
| iPhone fallback | iOS Control Center Screen Recording, **microphone off**, started before arming. Then AirDrop the .mp4 to the Mac | No route change: ReplayKit with the mic off doesn't touch the app's AVAudioSession (UNVERIFIED on our build; test once). It's a screen capture, not the phone camera, so it's within our reading of the rule |
| Laptop: explorer / Safe UI / pool UI, World ID web hop | QuickTime "New Screen Recording" or OBS display capture | none |
| Voice | Human voiceover recorded on the laptop mic afterwards (QuickTime "New Audio Recording"). Never TTS | Recording it after capture keeps PoP beeps out of the voice track and lets you narrate over the cuts |

Compositing: ffmpeg is installed (/opt/homebrew/bin/ffmpeg). Use a 1920x1080 canvas with the table shot as the background and the two phone captures as side panels. Line up the clips on the audible PoP chirp in the table-shot audio against the phone UI state change. Example:
```
ffmpeg -i table.mov -i android.mp4 -i iphone.mp4 -i voice.m4a -filter_complex \
"[0:v]scale=1920:1080[bg];[1:v]scale=-2:900[a];[2:v]scale=-2:900[i];\
[bg][a]overlay=40:90[t];[t][i]overlay=W-w-40:90[v]" \
-map "[v]" -map 3:a -c:v libx264 -crf 20 -pix_fmt yuv420p -c:a aac out.mp4
```
Cut with `-ss/-to` segments plus the concat demuxer. Check `ffprobe` height ≥ 720 and duration 120-240 s before uploading; the upload rejects anything outside.

### Other gotchas
- **Laptop load.** 8 GB M2. `popprover verify` took 43-47 s with a 572 MB RSS under load (end-to-end-latency-budget). Screen recording, the webcam, the local server and verify all at once will stall. Run the server or verifier on another machine, or record the laptop screen in a separate take from the phone run.
- **Start every capture before arming** and don't start or stop any of them mid-run. On iOS any route change aborts the run.
- **scrcpy over USB keeps adb attached.** That's harmless for audio. Check that the phone isn't in a USB audio accessory mode (with `--no-audio` it shouldn't be).
- **Webcam test blocked here.** The ffmpeg avfoundation capture from this shell hung, likely on a camera permission (TCC) prompt. Grant the camera to Terminal/QuickTime/OBS once, by hand.
- Take the table shot in a quiet corner. The rule says "avoid background noise and echo", and PoP needs the quiet too (see venue-acoustics-network).

### Suggested 3:30 cut
0:00-0:20 problem + one line on World ID gate. 0:20-0:50 World ID verify on both phones (cut the waits). 0:50-1:50 phones apart → FAIL shown, phones together → NEAR (the money shot: table cam + both screens, real time, no cuts during the chirp). 1:50-2:40 the action executes (Safe tx / private transfer) and the explorer shows it (cut the block wait). 2:40-3:30 how it works, one slide with ≤4 bullets, plus a disclosure line on pre-existing research.

### Remaining unknowns, cheapest check
1. Does QuickTime mirroring actually silence our iPhone, or trigger our preflight refusal? Plug in, open New Movie Recording with the iPhone as camera, and open the app's preflight screen (1 min). If it passes, try setting QuickTime's microphone to "MacBook Air Microphone" instead of the iPhone. Otherwise use the Control Center recording.
2. Does iOS Control Center screen recording (mic off) leave PoP working? Do one run.
3. Are phone screen recordings OK under the rule? Ask staff in Discord.

## worldid-hop-vs-confirm-order

Status: resolved (design). Not measured on device: the iOS return-from-World-App timing. With this spec it's off the audio path, so it doesn't need measuring.

### Findings

- Hiding the nonce until `confirmed` is a UI convention, not a security property.
  - Where it's hidden: `server/pop/sessions.py:531` (`shown = all(s["confirmed"].values())`) and `:535`. VERIFIED(grep).
  - It's generated at create as `secrets.token_hex(32)` (`sessions.py:142`). VERIFIED.
  - The only thing that pins it is a test: `server/README.md:65` (test_pairing: "nonce appears only after both confirm"). VERIFIED.
  - No doc gives a reason for the secrecy. Searched: pop-contract §3.3/§7, pop-transcript-v2, pop-prover, cheating-participant research, sound-bound decision, zk-gap research. The nonce is a freshness and binding tag signed into POPC/POPT (offset 7) and put in the ZK `halfCommit`. VERIFIED(grep).
- Code secrecy comes from `seed_hex`, which is never sent. Bed keys are derived per (role, attempt) (`sessions.py:7-9`). The partner's bed is released only after your own commit. VERIFIED.
  - Knowing the nonce early lets you precompute nothing useful. A POPC/POPT still needs the real recording hash and the codes, which you only get after arm and commit.
  - The nonce is still unpredictable before `create`, so freshness holds.
- So the adapters doc (L74, signal = `encodePacked(nonce, role)`) is right, and the latency-budget premise ("signal needs only sid+role") is wrong. As specced, they deadlock: Confirm is gated on verify, and verify needs the nonce, which only exists after confirm.
- Server timeouts: nothing between confirm and arm except `SESSION_MAX_AGE_S = 600` from create. `JOIN_TOKEN_TTL_S = 120` covers only created to joined. The app polls 120 s for t0 after arm. VERIFIED(`server/pop/constants.py:45-46`, `RunFlow.kt`).
  - So "hop between confirm and arm" wouldn't break the server.
  - It would break the app flow: `PopController.confirmPartner()` goes straight into `runSession()` (clock sync, then arm, then `engine.prepare`). VERIFIED(PopController.kt:427-441).
  - It would also add 13-35 s and put the World App round trip right before AVAudioSession/AudioRecord start.

### Spec: reveal the nonce to members at create/join; World ID runs before Confirm

Server (other workflow owns it; this is the spec):
1. `POST /v1/session` response adds `nonce` (hex32) for the host.
2. `view()`: set `shown = True` for any member. The view is already member-only (signed, `not_member` 403). So the guest sees it once joined, the host always.
   - One-line change at `sessions.py:531`.
   - Update test_pairing: the nonce is visible at joined, never to non-members, and `seed` still never appears.
3. Contract §3.3 step 3 and §9 (`"nonce": null (before confirmed)`) become: "`nonce` is shown to members from create (host) / join (guest)."
4. `POST /v1/session/{id}/human`: expected signal = `0x ‖ nonce_hex ‖ hex(role byte 'A'|'B')` from the server's own `nonce_hex`. Check the Portal result's signal hash against `keccak(signal) >> 8`. Mismatch → `human_invalid`.
5. Gate `arm` (not `confirm`) on both roles having a verified nullifier and `nA != nB` (`human_missing` / `same_human`), as adapters doc §4 already says.
   - Confirm stays ungated on the server, so the UI can overlap it.
6. With the derived nonce (bridge.md §4, `popCtxNonce`): the server sets `nonce_hex` from the formula. The view shows `context` + `not_before` + `nonce` at join, and nothing else changes.

Phone:
- Host: right after the create response, compute `signal = nonce ‖ 'A'` and fetch `GET /human/context` (rp_context, action `pop:<sid>`). Launch World ID while the QR/NFC invite is showing.
- Guest: right after `join` returns (or the first view with `nonce != null`), do the same with role `'B'`.
- If `context` is present (SAFE/POOL): recompute `popCtxNonce(chainId, consumer, ctxHash, not_before, sid)` and require it to equal the view's `nonce` **before** launching World ID and before enabling Confirm. Otherwise `context_mismatch`.
  - This moves bridge.md step 7 ahead of Confirm, which is strictly better: the approval card, the nonce check, and the World ID signal all happen before any consent tap.
  - The phone could compute the nonce itself without the server showing it, but the server should show it anyway. Random-nonce sessions (no context) need it, and one code path is simpler.
- Enable Confirm when both hold: partner shown (and key hint OK), and own `/human` verify returned OK.
  - The Confirm tap happens in the foreground after the user is back from World App. `confirmPartner()` → clock sync → arm → audio then runs with no app switch in between. Most of iOS's return-from-World-App risk leaves the audio path. The route change or audio-session interruption from switching apps is still untested, but now it lands before a user tap, not right before AVAudioSession start.
- Retry attempts reuse the World ID result (same nonce, same action). No second hop.

### Critical path after the change

create → (A hop ∥ QR show + scan + join → B hop) → both confirm → clock sync → arm → +3 s t0. The hops overlap the pairing, so they cost max(hop A, hop B) minus the join time, about 13-35 s. That's what the latency budget already assumed; it's now actually true. Confirm-to-audio needs no app switch. The ~45 s video budget holds.

### Residual / what changes in the threat model

- Revealing the nonce earlier gives a remote World ID lender a slightly longer window. That gap is already accepted in adapters doc L78 ("a real second human lending their World ID remotely... no signal choice fixes that"), and 13-35 s after confirm was enough anyway. No new attack.
- Someone who photographs the QR gets the sid but not a random nonce (the view needs a member signature). With a derived nonce they'd also need `context` + `not_before`. Either way the nonce isn't secret material, so nothing is lost.
- Declining Confirm after a successful World ID burns only a per-session action nullifier (`pop:<sid>`), which is harmless.
- To measure (optional): one device run, World App → back to our app → tap Confirm → AudioRecord start, on iPhone. Check for an `AVAudioSession.interruptionNotification`. Cheapest check: log `interruption`/`routeChange` notifications in the iOS audio engine during the instrumented dry run (end-to-end-latency-budget, "What remains" #1).

## ctx-nonce-formula-drift

**Answer: the canonical formula is the `keccak256("pop-ctx-v1")` / consumer = Safe form.** The guard spec U (`## safe-worldid-marginal-value`, guard block) and bridge.md §1 item 5 (L15) are wrong. Both use a string-literal domain, and spec U also uses `address(this)` (the guard). Fix those two lines. Don't create a second definition. VERIFIED (Python, forge and cast agree; the Kotlin prototype row N in `## tx-composition-ux` already matches the canonical form).

### Frozen definition (copy this into the design doc as the only definition)
```
DOMAIN        = keccak256("pop-ctx-v1")        // bytes32 constant
              = 0x2c71bde9118937099ebb172d5845794f571cc2982d44a563b229d1ea0db2af2f
session_nonce = keccak256(abi.encode(
    bytes32 DOMAIN,
    uint256 chainId,     // 480 on the demo
    address consumer,    // SAFE: the Safe proxy (msg.sender inside checkTransaction). POOL: the pool contract (address(this) there)
    bytes32 ctxHash,     // SAFE: safeTxHash. POOL: keccak256(abi.encode("pool-xfer-v1", POOL_ADDR, leaf)) (## payee-cannot-verify-leaf)
    uint64  notBefore,   // unix seconds, server clock at session create
    bytes16 sid))        // bytes.fromhex(session_id); server session_id = token_hex(16), 32 lowercase hex chars (server/pop/sessions.py:140)
signal        = abi.encodePacked(bytes32 session_nonce, bytes1 role)   // role 0x41 'A' / 0x42 'B'
signalHash    = uint256(keccak256(signal)) >> 8                        // "0x%064x"; phone passes "0x"+lowercase hex(signal) to IDKit
action        = "pop:" + session_id (text, unchanged)
```
Preimage is exactly **192 bytes** (6 static words):

| word | content | encoding trap |
|---|---|---|
| 0 | DOMAIN | a hash, not the string. `abi.encode("pop-ctx-v1", …)` makes a dynamic head (offset 0xc0) plus a tail, so it gives a different hash |
| 1 | chainId | uint256 big-endian, left zero pad |
| 2 | consumer | 12 zero bytes + 20-byte address |
| 3 | ctxHash | raw 32 |
| 4 | notBefore | uint64, **left** zero pad to 32 |
| 5 | sid | bytes16, **left-aligned, right zero pad** (`sid ‖ 00×16`). Encoding it as uint128 (left pad) gives a different hash |

Guard code (replaces the spec-U line):
```solidity
bytes32 constant POP_CTX_DOMAIN = keccak256("pop-ctx-v1");
// inside checkTransaction; msg.sender is the Safe
bytes32 h = ISafe(msg.sender).getTransactionHash(to, value, data, operation, safeTxGas, baseGas, gasPrice, gasToken, refundReceiver, ISafe(msg.sender).nonce() - 1);
bytes32 n = keccak256(abi.encode(POP_CTX_DOMAIN, block.chainid, msg.sender, h, notBefore, sid));
uint256 shA = uint256(keccak256(abi.encodePacked(n, bytes1(0x41)))) >> 8;
uint256 shB = uint256(keccak256(abi.encodePacked(n, bytes1(0x42)))) >> 8;
```
Why consumer = the Safe, not the guard: the server and the phones know the Safe address from `context.consumer`, and the phones check it against "My Safes" (`## tx-composition-ux` step 6). One guard serves many Safes (`## owner-device-registry`), so the guard address carries no per-wallet meaning. Also, a Safe's domain separator already binds chainId + Safe, so this adds no weakness. For POOL, the pool contract *is* the consumer and the verifier, so `address(this)` is correct there.

### Golden vectors
Inputs G: chainId 480, consumer `0x5afe5afe5afe5afe5afe5afe5afe5afe5afe5afe`, ctxHash `0xa0a1…bebf` (bytes 0xa0..0xbf), notBefore 1790000000, sid `0x00112233445566778899aabbccddeeff`.

| case | value |
|---|---|
| G nonce | `0x2b9a8528bf222c8cf60dd97fb416183376bd4bc5425b29c02583518590ef75c9` |
| G signal A (IDKit string) | `0x2b9a8528bf222c8cf60dd97fb416183376bd4bc5425b29c02583518590ef75c941` |
| G signalHash A | `0x002916db5141cfe5584c6de9cf6f45579e83422ecdf3260c31e30bc7f2b964c6` |
| G signalHash B | `0x0097c2b664c193be4b2699e4224cd1c6c3bb1f8de93919ebee7d7e346f25ff2b` |
| N nonce: real Safe `0x3fad7600f309b0c3d60a57023b0262460b0603dc`, ctx = tx-composition row 1 safeTxHash `0x960376ec…df1f59a5`, same nb/sid | `0x9fc7507c663ae43d4f8d56ba4b805fdf9e928e565141666a47630aa7fd04b121` (= existing row N) |
| N signalHash A | `0x008f770c3f6700ffa8277d98ae286f59448b26c40ecc9b59eb4236aec76f5637` |
| N signalHash B | `0x00e9c210433251df53d3a8650bc8f0b54e5ad84ffcc0593e2785d0778f92199a` |
| POOL, G inputs but consumer `0x9001…9001` | nonce `0xab8e50bb766db52b752932e48a63148cf015ac1a17c1345c35d4765f51027d66` |
| TRAP spec U literal (string domain, consumer = guard `0x6a7d…6a7d`) | `0x5acffbeffd0ba155be27ac0beba39e9100dd749fc15b72ca842a6855cf78becf` |
| TRAP string domain, consumer = Safe | `0x36603c76b65742d4039f5fb98950286cfeac74c033b263139045e8beaf472430` |
| TRAP hash domain, consumer = guard | `0xa0b4077ef6736018b1ddbc33a5d4b3e3c28a211f1a52566e6d400f7aecd6ff8b` |
| TRAP sid as uint128 | `0xa3993cf3f5bce4adc7c16d5e5c9c50e78dbde87ce9e1b933ad53fc8665440661` |

VERIFIED:
- Python pycryptodome 3.23.0: `scratchpad/ctxnonce/vec.py`.
- forge solc 0.8.28: `scratchpad/ctxnonce/sol/test/Ctx.t.sol`, 3/3 PASS. It asserts G, N, and all four traps, using real Solidity `abi.encode("pop-ctx-v1", …)` for the string traps.
- `cast keccak $(cast abi-encode "f(bytes32,uint256,address,bytes32,uint64,bytes16)" …)` gives the same G nonce.
- Kotlin: nonce row N comes from the `## tx-composition-ux` prototype, and signalHash from the IDKit 4.0.7 `hashSignal` (`## signal-0x-hex-semantics`).
- UNVERIFIED: Swift nonce. No Swift keccak+ABI code has been run. Swift IDKit `hashSignal` is verified for signalHash only.

### Implementation gotchas
- **Python keccak:** `hashlib.sha3_256` is NOT keccak256, because the padding differs. `server/` has no keccak today (pyproject deps: fastapi, cryptography, numpy, cbor2; `cryptography` has SHA3 only). Add `pycryptodome` (`Crypto.Hash.keccak`) or `eth-hash[pycryptodome]`.
- **Kotlin:** `org.kotlincrypto.hash:sha3` 0.8.0 `Keccak256` (KMP), per mobile-wallet.md. The app has no keccak today (grep empty).
- Build the preimage by hand as 6 × 32-byte words; don't pull in an ABI library. Every language asserts `len == 192` and the G and N vectors in a unit test before the guard, server or app code lands:
  - server: `tests/test_popctx.py`
  - app: `commonTest/PopCtxTest.kt`
  - guard: forge `PopCtx.t.sol` (copy `scratchpad/ctxnonce/sol`)
- Put this in a `PopCtx` library used by both the guard and the pool, so the Solidity side can't drift again.

**What remains:** a Swift port of the nonce (only if iOS computes the nonce itself; the Kotlin shared module covers iOS if KMP is used, so probably nothing). Also fix the two drifted lines: unknowns-resolved spec-U guard comment and bridge.md L15.

**Design impact:** blocker cleared. The design doc gets one `PopCtx` section with the frozen formula, the 192-byte layout and the golden vectors G and N (plus the traps). The spec-U guard line and bridge.md L15 must be corrected to `abi.encode(POP_CTX_DOMAIN, block.chainid, msg.sender, …)`. Each of server, app and forge gets a golden-vector test first.

## product-pick-and-cutline

Status: RESOLVED as a recommendation plus a timed plan. The pick itself is the user's call. Default if nobody answers by 17:30 JST: **SAFE, no POOL stretch.** Checked 2026-09-26 17:00 JST.

### Freeze pin (VERIFIED 17:00)
- The app freeze landed early: `847400ef5fce196e0e07c5e415f55c5a455b63b0` "app: on-device proving after near", 16:48 JST. Server content is unchanged since `ba81f84`. VERIFIED(`git log --grep`; `git diff 847400e -- app server` empty).
- pop-zk-readiness is in its read-only Integration phase (started 16:49). Measure phase measured nothing: "no phone is attached". VERIFIED(journal wf_e80a3322-982, last 8 lines).
- The multipart proof-upload bug from `## integration-freeze-point` is fixed in 847400e (`PopApi.kt:306` sends multipart through `signedRaw`). VERIFIED(grep).
- `Transcript.kt` is unchanged from `ce03696` to `847400e`, so the POPT v2 layout id `0x9114…952a` still holds. VERIFIED(`git diff --stat`, empty).
- **Design doc base = `847400e`.** T0 = 17:30 JST, once Integration ends. From T0 to the 09:00 deadline is 15.5 h. The plan submits at 08:00, so the working window is 14.5 h.

### Pick: SAFE. Why not POOL, and why no POOL stretch
1. **Rubric fit.** The IDKit prize literally lists "protection of an important account action". A 2-of-2 treasury tx is that trust moment. PoH gives the minimum-sufficient story directly: two distinct humans, one-per-human uniqueness. VERIFIED(worldid-prize.md §B; `## safe-worldid-marginal-value`)
2. **Honest security story.** SAFE row 6 of the `## demo-actual-trust-level` table is BLOCKED by the per-Safe device registry, even on today's weak attestation. POOL row 7 (payer and payee are the same attacker) is OPEN on the demo build. In Q&A, SAFE holds up and POOL doesn't.
3. **Competitor.** Rebind (same event) already ships "pays only when two different World IDs" on a job pool. POOL looks derivative. VERIFIED(worldid-prize.md §F)
4. **Build size.**
   - SAFE adds: one guard plus a setup helper (fork-tested, `## owner-device-registry`), server WID-S (context, human routes, attestation), app WID-A (context check, IDKit hop, SafeTx compose), and a read-only projector page.
   - POOL adds all of that, plus: a TS laptop wallet with notes, snarkjs, a LeanIMT shadow, and a QR ctx handoff; a presence poster; Poseidon CREATE2 deploys; decoy seeding; and a "Send anyway" failure path. That is about 2× the surface.
   - Both need the same unproven piece: a real-phone NEAR.
5. **POOL as a stretch splits the agents.** It shares nothing with SAFE past the attestation. Recommendation: **no POOL code tonight.** Use one roadmap slide: "same attestation also gates a private pool; E2E runs on a 480 fork" (`## presencepool-e2e-unbuilt`, which is true and already done).

**Question for the user (one line):** "SAFE only, POOL as a roadmap slide. OK?" Also ask the track question (Classic or Continuity, worldid-prize.md Open Q1). If the team is on Classic with pre-existing work, no World prize is possible at all, so this outranks the product pick.

### Lanes after T0 (one editor per tree)
- **L-chain** (contracts/, new dir): `PopSafeGuard` + `PopSafeSetup` + deploy scripts on 480. It doesn't need phones until Safe creation, which needs the enrolled device ids.
- **L-server** (server/): WID-S steps 1–7 from `## integration-freeze-point`, plus `same_human` 409 and the POP2 attestation with device ids, `pair_tag` and the transcripts.
- **L-app** (app/): WID-A. It starts once the L-server fields exist (rebase on the L-server commit).
- **L-ops** (humans): phones, Orb check, funding, Etherscan key, Discord question on video rules.
- ENS lane: park it until CP4 passes (see `## ens-lane-collision`).

### Checkpoints (JST, hard times; a checkpoint is missed at its time, not later)

| # | By | Pass condition (measurable) | Fallback if missed |
|---|---|---|---|
| CP0 | 17:30 | (a) The user says SAFE. (b) Track known. (c) Two Orb-verified humans confirmed: each opens World ID app > Credentials > "Proof of Human", with no Face Auth re-auth banner. (d) `DEPLOYER` and `RELAYER` each hold 0.01 ETH on 480 via Relay/Across. (e) Etherscan API key in env. (f) pop-zk-readiness shows finished. | (a) no answer → go SAFE. (b) Classic with pre-existing work → message ETHGlobal staff now about switching to Continuity, and keep building. (c) only one Orb human → find an Orb-verified hacker at the World booth by CP3. Last resort: `selfieCheck` for both roles, with the claim restated as "two distinct live World App humans" (UNVERIFIED: whether selfieCheck nullifiers are per-human stable). (d)/(e) 10 min, no real fallback needed. |
| CP1 | 19:30 (T+2h) | Real-phone PoP on the demo pair (Android + iPhone, `POP_ALLOW_UNATTESTED=1`, tunnel): at least 4/5 NEAR at 30 cm, 5/5 NOT_NEAR at 150 cm, median tap-to-verdict under 15 s. Logged from `GET /v1/session/<sid>/result`. Protocol: `## pop-works-on-demo-phones` (cut from 10+10 runs to 5+5). | 19:30–21:00: iOS debug only (echo cancellation / voice processing first, then swap host and guest). **21:00 hard stop:** sideload the APK on a second Android (a teammate's or borrowed; Android needs no unattested flag) and demo Android + Android. L-chain, L-server and L-app keep going on the fake-phone harness (`tests/sim2`) meanwhile, so they don't block on this. |
| CP2 | 20:30 (T+3h) | `PopSafeGuard` deployed and verified on worldscan.org (480). A 2-of-2 Safe created through `PopSafeSetup`, with the two enrolled device ids registered and funded with 0.002 ETH. A tx without an attestation reverts, and the revert is visible on worldscan. | Verification fails → Blockscout/Sourcify (`## mainnet-480-ops`). Device ids not ready (CP1 late) → deploy the guard now and create the Safe right after the phones enroll. Never re-enroll after that point. |
| CP3 | 22:30 (T+5h) | World ID works end to end from the app for both roles, production environment. A uses same-device (Android). B uses cross-device QR scanned by B's own phone. The server logs two Portal `success` responses with different nullifiers. `same_human` returns 409 when one human scans both. | **Server-only World ID via a laptop page:** IDKit JS 4.3.0 page per role, opened from the session, verified by our server, stored in `s["human"]`. The phone app is untouched for World ID. This is allowed by the prize ("verify on the server"). Trigger it at 22:30 if the Kotlin/Swift IDKit hop isn't returning proofs; Kotlin IDKit isn't on Maven Central, and that is the risk. |
| CP4 | 01:30 (T+8h) | One real `execTransaction` on 480 gated by a real NEAR plus two World ID proofs, receipt on worldscan, 0.0001 ETH to a visible recipient. Plus one "apart" run ending NOT_NEAR `too_far` with no tx sent. **Sub-decision at 23:30:** is the onchain World ID `verify` in the guard (U-mode, ~0.8M gas) wired? If not, drop to the server-signed `pair_tag` in the attestation and say so on the slide. | App-side SafeTx composing broken → compose with `cast` from the laptop using the session `context` (dev fallback in `## tx-composition-ux`); the phones still do PoP + World ID + owner sigs. Relay broken → send `execTransaction` with `cast send` by hand. |
| CP5 | 03:00 (T+9.5h) | Feature freeze. Three full dry runs back to back with the per-stage timing log (`## end-to-end-latency-budget` §remaining 1). Upload of recordings off. ZK shown only as a later badge, never gating. | Anything not green at 03:00 is cut, not fixed. The failure path shrinks to the instant guard revert (5 s). |
| CP6 | 05:00 (T+11.5h) | Raw footage captured on the laptop: table webcam, scrcpy `--no-audio`, iPhone Control Center recording with mic off, laptop screen. Takes: 2× success, 1× apart, 1× revert. | Use the best take from the CP5 dry runs (keep all captures running during dry runs, so every dry run is also a take). |
| CP7 | 06:30 (T+13h) | Video cut with a human voiceover, 2–4 min, at least 720p, cuts labeled, not sped up. Checked with `ffprobe`. | Drop the architecture segment. Success plus revert alone fits in about 2:10. |
| CP8 | 08:00 | Submitted: README with a pre-existing work section (first commit `c9c36f6`, worldid-spike), AI attribution, spec files (this directory + design doc), `WORLD_FEEDBACK.md` (four debrief items), trust-moment paragraph + credential rationale. | 08:00–09:00 is the only buffer. Never plan work into it. |

### Rules the design doc must state
- Every checkpoint has an owner lane and a single yes/no. At a miss, take the fallback immediately. No "15 more minutes".
- Do the CP1 phone test before any UI polish. Until CP1 passes, all integration runs on the fake-phone harness.
- The attestation is issued on the verdict alone, never on ZK (already decided in `## end-to-end-latency-budget`).
- Pre-warm list before every take: enrolled, keys cached, Safe funded, relayer funded, World App unlocked, `require_user_presence=false`.

### Still unknown, and the cheapest way to find out
1. The user's pick and the track: one message now.
2. Two Orb humans: a 2-minute check in each person's World ID app.
3. Whether the native iPhone PoP works at all: CP1 itself, 45 min with both phones on USB (`adb` currently `unauthorized` → accept the prompt on the phone).
4. The pop-zk-readiness Integration phase may produce follow-up commits: re-run `git log -3` at 17:30 and re-pin if HEAD moved under app/ or server/.

## track-eligibility-disclosure

Status: partially resolved. Track is known. Staff acceptance is not; only staff can answer that.

**Track facts (VERIFIED, read-only look at the logged-in ETHGlobal project form, 2026-09-26 ~17:00 JST; nothing was saved or changed)**
- Nothing is "registered" on the team page. You pick the track inside the submission form: Project > "Select prizes" > "Continuity Mode" > "Select your track for ETHGlobal Tokyo 2026". The two options are "Building from Scratch" and "Continuity Track".
- Right now it is set to **Building from Scratch (Classic)**. The sidebar rules say "Project should start from scratch. You may not add features to existing work".
- The project has not been submitted yet (showcase slug /showcase/enconomy-9m8x8 returns 404; the form is missing its logo, banner and 3 screenshots). The radio button can still be switched. A human should do that, because the choice has consequences.
- The form's own rules: "You will only be eligible for the prizes from the track you select". "Team members must be on the same track as the project". The team has 1 member.
- Partner picker: max 3 partners, and World counts as one ($15,000).
- World prizes on the Tokyo prize page (VERIFIED https://ethglobal.com/events/tokyo2026/prizes): Best Use of IDKit $5k (2 x $2.5k), Best Use of World ID for Agents $5k (2 x $2.5k), and the **Continuity-only** "[Cont] Best IDKit Use Case" $2.5k and "Best Use of World ID for Agents (Continuity)" $2.5k.
  => **On Continuity, the realistic World upside is the two $2.5k Continuity prizes, not the $5k pools.** That is UNVERIFIED as final. The form wording implies it, but ask staff.
- Hacking began **2026-09-25T12:00Z = 21:00 JST** (VERIFIED, event page JSON `"slug":"hacking-begins","startTime":"2026-09-25T12:00:00.000Z"`).

**Pre-existing work facts (VERIFIED: git, stat, gh)**
- Repo tawago/enconomy was created 2026-09-25T17:52Z (02:52 JST Sep 26, after kickoff). It is PUBLIC (`gh repo view`).
- First commit `c9c36f6 2026-09-26 02:52 JST "Initial commit: research prototypes and docs"`: 151 files, +50,783 lines. The file mtimes of those files: 15 from Apr 2026, 3 Jun, 17 Jul, 72 on Sep 21-25, 32 touched Sep 26. So the research import is clearly pre-event, and some of it is months old. Contents: research/proximity-echo, research/sound-bound (acoustic ranging, ZK spikes), research/fuzzy-commitment, circuits/copresence.circom, research notes.
- `~/dev/worldid-spike`: dirs created 2026-09-24 23:01-23:36 JST, pre-event. FastAPI RP signer + Portal v4 verify proxy + KMP Android IDKit 4.0.7 spike + docs/idkit-research-brief.md. It is not in the repo. Its git has no commits.
- In-event history: 28 commits from 03:23 JST Sep 26 on (contract, server, Android/iOS app, ZK prover integration). Single author `tawago`, and none of the commits carry an AI co-author line.

**Rules that decide this (VERIFIED https://ethglobal.com/rules, /events/tokyo2026/info/details, /info/start)**
- Classic: "Projects built before the event ... won't qualify for partner prizes or the Finalist category". Pre-existing project-specific code "not allowed". The acoustic PoP research is project-specific, so **as submitted today (Classic), the World prizes are at real risk.** The honest defense is thin: "research prototypes, not the product". The first commit is literally 50k lines of project-specific code.
- Continuity: "bring an existing open-source repository or extend an existing private/commercial product". The pre-existing work must be clearly documented, and the new work must be open source. "Ship a Feature" (a private prior codebase, released as open source) fits us better than "Extend Open Source". The repo did not exist publicly before the event.
- All tracks: written disclosure to ETHGlobal staff plus full details in the repo history, video and description. Undisclosed work leads to DQ, revoked prizes and a ban. "Single commits of large files without proper history" are "assumed to be unqualified unless proven otherwise". c9c36f6 is exactly that, so the disclosure must name it.
- AI (info/details): "AI tools should be used to assist ... not to create the entire project. Submissions that rely entirely on AI without meaningful contributions from team members may not be eligible for partner prizes". You must document where and how AI was used. Spec-driven workflows must include spec files, prompts and planning artifacts in the repo. /rules itself says nothing about AI (checked).

**Decision for the design doc**
- Default recommendation: **switch to Continuity before submitting**, and disclose. Classic plus a 50k-line project-specific import is the path most likely to be DQ'd. Continuity caps the World upside at about $2.5k-5k but keeps us eligible. Get staff sign-off first, if possible.
- If staff say "Classic is fine as long as you disclose", stay Classic for the $5k pools. Get that answer in writing (a Discord message or help-desk ticket) and quote it in the README.

**What remains (cheapest way to close it: 10 min at the help desk or on Discord #help, tonight, before the 09:00 JST 2026-09-27 deadline)**
Ask these exact questions:
1. "Solo team, project Enconomy. Before kickoff I had private research prototypes for acoustic proximity (months old) and a one-day World ID IDKit spike. I imported them as the first commit (c9c36f6, 50k lines) at 02:52 JST. The product (app, server, contract, ZK integration, World ID) was built during the event in 28 commits. Classic or Continuity?"
2. "On Continuity, am I eligible only for World's two [Cont] $2.5k prizes, or also for the main $5k IDKit pool? Can Continuity projects be finalists?"
3. "Most of the code was written by Claude Code agents that I orchestrated (specs, prompts and workflow scripts are in the repo). Does that meet 'meaningful contributions from team members'?"
Record the answers here and in the README.

**Draft for the submission README (paste, then fill the brackets)**

```
## Pre-existing work (disclosure)
Hacking began 2026-09-25 21:00 JST. Work that existed before that:
- Commit c9c36f6 (imported 2026-09-26 02:52 JST, 151 files): my private research prototypes,
  written Apr–Sep 25 2026: research/proximity-echo, research/sound-bound (acoustic
  ranging, code design, early ZK circuit spikes), research/fuzzy-commitment,
  circuits/copresence.circom, research notes. Imported as one commit; not built at the event.
- A World ID / IDKit 4 feasibility spike (Sep 24, separate private folder, not in this repo):
  Python RP-signing port + Portal v4 verify proxy + Android IDKit 4.0.7 test.
  Reused here: [list files/functions, or "nothing copied"].
Built during the event (commits b7faa02 onward): proof-of-presence contract, FastAPI
server (enrollment, sessions, verdict, SBcred3 issuance, proof verification), KMP
Android + iOS app (audio engine, attested keys, NFC/QR pairing, on-device prover),
World ID integration, [SAFE module / POOL] product, demo.
Track: [Continuity – Ship a Feature | Classic, per staff answer on <date/time, who>].

## AI usage
Built with Claude Code (Anthropic) as a coding agent. I wrote the product idea,
threat model, protocol choices and acceptance tests, and I reviewed and field-tested every change on
real phones. Agents wrote most implementation code from specs I wrote.
- Specs / planning artifacts: docs/, research/ (incl. research/worldid/notes/*), design doc [path].
- Agent prompts and workflow scripts: [path, e.g. ai/prompts/, ai/workflows/ — export them before submission].
- Per-area breakdown: [server/: agent-written, human-reviewed; app/: ...; circuits/: ...; contract: ...].
```

**Action items for the design doc**
- Before submitting, copy the workflow scripts and prompts into the repo (for example `ai/`). The rules require it. They currently live only in Claude Code session folders (6 session dirs under ~/.claude/projects/-Users-takahiro-ogawa-dev-enconomy/).
- The track radio lives in the submission form. The human flips it. Agents must not.
- Demo video: no AI voiceover and no TTS. Record it with a human voice.

## second-distinct-human-credential

**Status: partially resolved.** How many Orb humans the team has is a question only the team can answer (10 min, see "Still open"). Everything else below was checked live on 2026-09-26 at 07:59 UTC.

### Answer

1. **Staging/simulator fallback is closed unless someone opens a window. The gate is live in production.** VERIFIED (probe below). A replayed spike proof sent to `POST https://developer.world.org/api/v4/verify/rp_1469245f4f78143c`:
   - `environment:"staging"` returns 403 `{"code":"environment_not_allowed","detail":"Staging verification is not open for this app. Open a staging window with the set_world_id_staging_verification tool, ..."}`.
   - `environment:"sandbox"` gets the same 403, so sandbox is gated too.
   - Removing `integrity_bundle` gives the same 403.
   - A bogus `x-staging-verification-token` gives the same 403.
   - Control: `environment:"production"` gets past the gate. It then fails on `integrity_verification_failed`, because the bundle JWT expired. So the Portal now checks the integrity bundle on PoH proofs as well.
2. **How to open the window.** VERIFIED (source: developer-portal @ cb3305e, `web/api/mcp/index.ts` L213–225, L1249–1290; `web/api/v4/verify/staging-access.ts`):
   - Call the Portal MCP tool `set_world_id_staging_verification {app_id, enabled:true}` at `https://developer.world.org/api/mcp` with header `Authorization: Bearer api_...` (a team API key).
   - It returns a token **once**. The token stays valid for 24 h, and re-opening the window invalidates the old one.
   - Every staging verify then needs the header `x-staging-verification-token: <token>`.
   - Only a team member should do this. I did not open a window: it changes the security posture of the production RP.
3. **Simulator proofs carry `issuer_schema_id = 128` ("faux issuer"), not 1.** VERIFIED (`web/api/v4/verify/request-schema.ts` L46–66): `identifier:"proof_of_human"` with 128 is accepted only when `environment ∈ {staging, sandbox}`.
   - So a server that pins `issuer_schema_id == 1` and `environment == production` rejects simulator proofs on two counts. That is correct, and it stays that way in production.
   - The Portal success body does **not** echo `issuer_schema_id`. It returns only `results[{identifier, success, nullifier}]` (VERIFIED, spike log 2026-09-25 00:45).
   - Our server must read `responses[i].issuer_schema_id` from the request body before forwarding. The Portal binds that value into the proof, because issuerSchemaId is a public input of the verifier.
   - Why the Portal gates staging (its own comment): simulator credentials are mintable at will, so an open staging path gives one person unlimited fresh nullifiers. For us that means **pair_tag distinctness means nothing under staging.**
4. **Selfie Check cannot turn one human into two.**
   - The nullifier depends on (World ID leaf, rp_id, action), **not** on which credential was used. The same person gets the same nullifier with PoH or with Selfie. VERIFIED ([C] in `~/dev/worldid-spike/docs/idkit-research-brief.md` L66, from the spec).
   - Selfie Check only helps if the second human has a World ID App account but no Orb verification.
5. **Selfie Check v4 (`issuer_schema_id 11`, identifier `"selfie"`, also `"face"`).** VERIFIED (source):
   - The Portal requires `integrity_bundle.version == 2` and a `sybil_score` for it. Otherwise it returns `selfie_check_requires_integrity_v2` or `missing_sybil_score` (`index.ts` L206–222; `integrity-bundle.ts` L220–243, L684–690).
   - SDK support differs:
     - `@worldcoin/idkit-core` 4.3.0 has the preset `selfieCheck()`. VERIFIED (tarball `dist/index.d.ts` L738).
     - Swift `idkit-swift` 4.0.11 has **no** v4 `selfieCheck` preset, only `selfieCheckLegacy` (a 3.0 proof, marked "Preview: contact us"). VERIFIED (`Sources/IDKit/IDKit.swift` L606–611; `Preset` enum cases).
     - Kotlin `com.worldcoin:idkit:4.0.7` (local AAR used by the spike) is the same: no `SelfieCheck` preset.
     - Both native SDKs do expose `CredentialType.SELFIE` and `builder.constraints(ConstraintNode)`. So v4 Selfie can be requested through constraints (VERIFIED by javap / generated swift). Whether World App actually answers that request with a v4 Selfie proof is UNVERIFIED.
   - Docs: Selfie is "medium assurance", "does not provide a strict one-person-one-account guarantee", and "anyone with World ID App" can do it (docs `world-id/credentials/11.mdx`, docs clone @ 10536b5).
   - So one person with two phones and two World App accounts can likely hold two Selfie credentials. `sybil_score` is only a risk signal, with no documented thresholds.

### Decision for the design doc

Pinned server config (and onchain, if used): `environment == "production"`, `issuer_schema_id == 1`, `nullifier_A != nullifier_B`. Do not relax it for the demo. Fallbacks, in order:

- **A. Two real PoH humans, production (default).** No code change.
  - If the team has only one Orb human, borrow a second one at the venue: World booth staff or another hacker. If the judge has World ID, use the judge; that makes the demo stronger.
  - The second human only needs World App with PoH on their own phone.
  - Cross-device use needs IDKit's `connectorURI` shown as a QR code and scanned by their World App. The spike only tested same-phone deep links. UNVERIFIED for our app.
- **B. One human only, so show the rejection as the required "meaningful alternative path".**
  - The same person verifies both roles, gets the same nullifier under action `pop:<sid>` (the only way pair_tag collapses), and the server returns `same_human`.
  - This satisfies prize requirement 4 ("rejection / ineligible user") for free. Keep it in the demo even if A works.
- **C. Second human has World App but no Orb: Selfie Check.**
  - Server accepts `{1, 11}` **only** as an explicitly lower tier, e.g. `pair_assurance = "poh+selfie"`, shown in the UI and the output record.
  - Needs integrity bundle v2 and the constraints API on native. Test it before relying on it.
  - It weakens the "minimum sufficient = PoH" story. Use it only if A fails.
- **D. Staging + simulator (last resort).**
  - A team member opens the window through MCP. The server gets `WORLD_STAGING_TOKEN`, attaches the header **only** when `DEMO_STAGING=1`, and then accepts `environment=="staging" && issuer_schema_id==128`.
  - The UI must show a "TEST IDENTITIES" banner. Close the window after the demo (`enabled:false`).
  - Never build the header into the production path.
  - Onchain: the staging verifier is `0x703a6316c975DEabF30b637c155edD53e24657DB` (World Chain 480). Whether issuer 128 is registered there is UNVERIFIED.

Credential rationale for judges (unchanged): the protected property is "two **different** unique humans met". Only PoH (1) gives one-person-one-nullifier. Selfie (11) proves liveness, not uniqueness. Passport (9303) proves a unique document, not a unique person.

### Evidence / commands

- Probe: `scratchpad/stagegate/{prod,staging,sandbox,staging_nobundle}.json`, built from the last `portal-verify-req` in `~/dev/worldid-spike/backend/logs/backend.log`, then `curl -X POST https://developer.world.org/api/v4/verify/rp_1469245f4f78143c -H content-type:application/json --data @<f>`, run at 2026-09-26T07:59:45Z.
- Portal source: `scratchpad/developer-portal` @ cb3305e (2026-09-25).
- SDKs:
  - `https://registry.npmjs.org/@worldcoin/idkit-core/-/idkit-core-4.3.0.tgz`
  - `codeload.github.com/worldcoin/idkit-swift/tar.gz/refs/tags/4.0.11`
  - `~/.m2/repository/com/worldcoin/idkit/4.0.7/idkit-4.0.7.aar`
  - The GitHub releases API shows idkit-swift latest 4.0.11 (2026-08-09) and idkit-kotlin latest 3.1.0 (the v4 Kotlin SDK is not released there).

### Still open (cheapest way to close)

1. **Human count.** Each teammate opens World App, goes to the Credentials tab, and checks for "Proof of Human" and any Face Auth re-auth banner. 10 min. Nobody else can do this.
2. **Does World App return a v4 Selfie proof to a native constraints request?** Have the non-Orb person run the spike app with `constraints(Item(CredentialRequest(SELFIE)))` and check that the Portal returns 200 with `identifier:"selfie"`. About 20 min. Alternative: use a JS page built on idkit-core 4.3.0 `selfieCheck()` with our app_id.
3. **Staging window with a real simulator proof** (only if D is chosen). A team member with a Portal API key opens the window, then one simulator proof goes through the spike backend with the header. 15 min. I skipped this on purpose: auto-mode blocked the API key use, and opening the window changes the production RP.

## rp-onchain-registration

Status: RESOLVED, except one live fresh-proof `eth_call` for a new rp (needs a human with World App; recipe below). Checked 2026-09-26 08:02 UTC, 480 block 35537049.

### Answer

- **Spike rp is fully registered on 480, prod and staging.** `rp_1469245f4f78143c` (= u64 `1470746745086940220`, from `app_957c2f7367de651c77a4c2a4e9cb9a7d`):
  - RpRegistry `0xD9A213A92Bca460D56cDbBF4d775b48fB5925BbC` `getRp` → `(initialized=true, active=true, manager=0x4c629fcd…848B, signer=0xd0221b8F…8582, oprfKeyId=1470746745086940220, "worldid-spike")`. VERIFIED(cast call).
  - Prod OprfKeyRegistry `0x0D8b461799474207A3d223553d4d5e6609cb0c69` `getOprfPublicKeyAndEpoch` → key `(1901519838…695943, 1690244139…108215)`, epoch 0. VERIFIED(cast call). This is the registry the prod verifier reads (`WorldIDVerifier.getOprfKeyRegistry()` = `0x0D8b…0c69`, VERIFIED).
  - Staging verifier `0x703a…57DB` reads a different OprfKeyRegistry `0xb2C02253ee7bFEDF50F5D015658857099980E91F`; the spike key is there too. VERIFIED(cast call).
  - Portal: `GET https://developer.world.org/api/v4/rp-status/rp_1469245f4f78143c` → `{"production_status":"registered","staging_status":"registered"}`. No auth. VERIFIED(curl). Unknown rp → 404 `not_found`.
- **Registration is automatic, triggered by one click in the Portal.** Flow: app page → "Enable World ID 4.0" dialog → generate/choose signer key → Portal calls `register_rp(app_id, mode:"managed", signer_address)`. VERIFIED(`worldcoin/developer-portal` @ cb3305e: `web/scenes/PortalV3/.../EnableWorldId40/Dialog/index.tsx:119`, `web/api/helpers/rp-registration-flows.ts:81`).
  - The Portal sends a 4337 UserOp from its KMS-managed manager key: `RpRegistry.register(rpId, manager, signer, domain)`. That calls `OprfKeyRegistry.initKeyGen(uint160(rpId))`. The OPRF nodes then run DKG and emit `SecretGenFinalize`. VERIFIED(`world-id-protocol` @ 7ac826e `contracts/src/core/RpRegistry.sol:246-274`).
  - Spike timing: `RpRegistered` at block 35462287 (2026-09-24 14:30:13 UTC, tx `0xe56b9e04…4a3c` via EntryPoint `0x0000000071727De2…a032`). `SecretGenFinalize` at block 35462299 (14:30:37 UTC, tx `0xa1ea1663…cbd2`). **Key ready 24 s after registration.** VERIFIED(Blockscout `worldchain-mainnet.explorer.alchemy.com/api?module=logs` + cast tx).
  - The UI polls `rp-status` every 5 s while `pending`. If the UserOp doesn't settle within about 5 min, it shows `failed` with a Retry button (`PENDING_TIMEOUT_MS = 5 min`, `retry_rp` mutation). VERIFIED(source `api/v4/rp-status/[rp_id]/index.ts`, `use-rp-registration-controller.ts`).
  - Registration fee is 0 (`getRegistrationFee()` → 0, fee token `0x0`). VERIFIED(cast call).
  - "Staging" Portal apps can't enable 4.0 (`staging_not_supported`). Create the app as production. VERIFIED(source `rp-registration-flows.ts:95`).
  - `rp_id = "rp_" + hex(uint64(keccak256(utf8(app_id)))[0:8])`, so it's known the moment the app exists. VERIFIED(`web/lib/rp.ts`; `cast keccak app_957c…9a7d` → `0x1469245f4f78143c…`).
- **Correction to experiment 7 (`safe-worldid-marginal-value`).** An rp with no OPRF key does **not** fail as `ProofInvalid`. It reverts `UnknownId(uint160)` = `0xfbf20062` + the id, from `OprfKeyRegistry.getOprfPublicKey`. `rpId = 1` gave `ProofInvalid` because rp 1 *has* an OPRF key (a test key: `getOprfPublicKey(1)` returns a point) while not being in RpRegistry (`getRp(1)` → `RpIdDoesNotExist` `0x3200e7c0`). VERIFIED(spike proof at block 35464531: rp=`…220` → `0x`; rp=1 → `0x7fcdd1f4`; rp=`…221` → `0xfbf20062…1469245f4f78143d`).
  - So there are two distinct signals. `0xfbf20062` means the rp has no key: not registered, or keygen not finished. `0x7fcdd1f4` means a key exists but the inputs are wrong: rpId, action, signal, nonce, schema, or `expiresAtMin`.
  - A deleted key reverts `DeletedId(uint160)` `0x1b02ded7`.
- **The verifier never reads RpRegistry.** `WorldIDVerifier.verifyProofAndSignals` only calls `_oprfKeyRegistry.getOprfPublicKey(uint160(rpId))`. It doesn't check `active`, the signer or the RP signature. VERIFIED(`WorldIDVerifier.sol:151-210`, no RpRegistry reference). Consequences:
  - A deactivated rp still verifies onchain.
  - The rp signature is enforced only by World App and Portal `/verify`.
- **Portal `/verify` success implies onchain registration.** `/api/v4/verify` refuses unless the DB row is `registered` (`api/v4/verify/index.ts:149`). `rp-status` only promotes a row to `registered` after it reads it onchain with the Portal's own manager and signer. VERIFIED(source). If Portal verify passes and onchain fails, the problem is **not** registration. Look instead at:
  1. The root window: `0x9dd854d3` `InvalidMerkleRoot`, i.e. more than 1 h.
  2. The wrong verifier: prod `0x0000…94d7` vs staging `0x703a…`, which use different OPRF registries.
  3. Action/signal encoding: `ProofInvalid`.

### Decision: reuse the spike app or make a new one

Recommend a **new Portal app "enconomy"**, created now, before any demo work. Disclose the spike anyway ("World ID integration pattern prototyped in worldid-spike before the event").
- Cost: about 2 min of clicks and about 30 s onchain. It needs a new signer key, which goes into the server `.env`, and a new `RP_ID`.
- The guard and pool take `RP_ID` as a **constructor/immutable arg**, never a literal. Then switching apps is just a redeploy.
- Fallback if the new app is stuck `pending`/`failed` after Retry: keep the spike rp (already proven end to end) and disclose it.

### Gate (run right after creating the app; paste results into the build log)

```sh
WC=https://worldchain-mainnet.g.alchemy.com/public
APP=app_xxx; RPHEX=$(cast keccak "$APP" | cut -c3-18); RP=$((16#$RPHEX)); echo rp_$RPHEX $RP
curl -s https://developer.world.org/api/v4/rp-status/rp_$RPHEX               # want production_status:"registered"
cast call 0xD9A213A92Bca460D56cDbBF4d775b48fB5925BbC "getRp(uint64)((bool,bool,address,address,uint160,string))" $RP --rpc-url $WC
#   want (true,true,<manager>,<signer == address of WORLD_SIGNING_KEY>,<RP>,...)
cast call 0x0D8b461799474207A3d223553d4d5e6609cb0c69 "getOprfPublicKey(uint160)((uint256,uint256))" $RP --rpc-url $WC
#   want a non-zero point; 0xfbf20062 = keygen not done yet (wait 30 s, retry)
```

Then comes the one step still open, which needs a human with an Orb-verified World App. Produce one fresh PoH proof for the new rp (spike `/rp-context` → IDKit with the new app_id), and within 1 h run the `verify(...)` `cast call` from the worldid.md appendix, with the new `RP` and live block. Expected `0x`. This is UNVERIFIED for the new rp until done. It is the only remaining unknown, and it takes about 5 min.

**Design impact:** create the enconomy Portal app (prod, Enable World ID 4.0) today and run the gate. `RP_ID` becomes a deploy parameter, and the server `/health` embeds `rp-status`. Onchain error mapping in the server/UI:
- `0xfbf20062` → "rp not registered / keygen pending"
- `0x7fcdd1f4` → "proof inputs mismatch"
- `0x9dd854d3` → "proof older than 1 h, redo World ID"

## verifier-pin-vs-demo-env

**Answer.** Don't hardcode either one. The guard holds an immutable two-entry allowlist, `PROD = 0x00000000009E00F9FE82CfeeBB4556686da094d7` and `STAGING = 0x703a6316c975DEabF30b637c155edD53e24657DB`. Each Safe picks one in `initSafe` (`cfg[safe].wid`). `rpId` can stay an immutable constant: the same `rpId` works in both environments. The demo can run on **staging with simulator identities**, and that was tested today, onchain. Prod also works with real World ID app proofs, as the earlier replay showed. The Portal staging gate is live, but it only blocks the Portal. It has no effect on the contract.

### What was tested (2026-09-26 ~08:05 UTC, World Chain 480, block ts 1790409915)

1. **A simulator proof passes `0x703a` onchain.** VERIFIED (command).
   - Proof source: Node + `@worldcoin/idkit-core` 4.2.4, `environment:"staging"`, `proofOfHuman({signal:"vpin-signal"})`, our RP `rp_1469245f4f78143c`, RP sig from the spike key. The connector URI was pasted into simulator.worldcoin.org with "World ID 4.0" mode (the default); it showed "Presented". The bridge returned `protocol_version:"4.0"`, `environment:"staging"`, `issuer_schema_id:1`, `identifier:"proof_of_human"`.
   - `cast call 0x703a… "verify(uint256,uint256,uint64,uint256,uint256,uint64,uint64,uint256,uint256[5])" nullifier hash_to_field(action) 1470746745086940220 nonce signal_hash expires_at_min 1 0 proof` → `0x` (no revert). `cast estimate` = **414,813 gas** (21k base included).
   - The same args against prod `0x…94d7` revert `0x9dd854d3` `InvalidMerkleRoot()`. The two trees are separate.
   - Changing the signal hash on staging reverts `0x7fcdd1f4` `ProofInvalid()`, so the check has teeth.
   - The proof is saved at `scratchpad/vpin/result.json` and the script at `scratchpad/vpin/req.mjs`. Node needs a `fetch` shim for `file:` URLs to load the IDKit WASM.
   - Simulator gotcha: type the URI in one shot (`form_input`, or a real paste). Typing it character by character makes the paste box fire as soon as the partial URL matches (`k=` accepts any prefix), and you get "Invalid QR code" or "Something went wrong".
2. **Prod works with real proofs.** Earlier replay of `spike-1790264612780` at a historical block passed, with 419,429 gas (worldid.md §1.8). VERIFIED (earlier cast replay).
3. **The Portal staging gate is live on developer.world.org.** A dummy proof with `environment:"staging"` to `POST /api/v4/verify/rp_1469245f4f78143c` → **403** `environment_not_allowed` ("Staging verification is not open for this app. Open a staging window with the set_world_id_staging_verification tool…"). The same body with `"production"` → 400 `verification_failed`, meaning it went through to the contract. VERIFIED (curl, 08:00 UTC). Source: `developer-portal@cb3305e web/api/v4/verify/staging-access.ts`. The window lasts 24 h and needs the `x-staging-verification-token` header.
4. **Our RP is registered in both environments, with the same signer.**
   - `getOprfKeyIdAndSigner(0x1469245f4f78143c)` → `(1470746745086940220, 0xd0221b8F…8582)` on prod RpRegistry `0xD9A2…BbC` and on staging RpRegistry `0x37d2462fE7B4a07987263AAd062C6593C4f567b9`.
   - The OPRF public keys differ: prod OprfKeyRegistry `0x0D8b…0c69`, staging `0xb2C02253ee7bFEDF50F5D015658857099980E91F`.
   - So **nullifiers differ per environment** for the same person and action.
   - The Portal source says every v4 RP "is duplicated onto the staging registry" (staging-access.ts comment). VERIFIED (cast).
5. **Mutability of the verifiers themselves.** Both proxies use impl `0xff93…4c73`, `admin()` = 0 (UUPS). Owners: prod `0xc534a745…3e77` (a contract, 171 B, likely a multisig); staging `0x0459B1592C4e1A2cFB2F0606fDe0F7D9E7995E9A` (**an EOA**). The owner can swap registries, the Groth16 verifier, or the impl at any time (`updateWorldIDRegistry` / `updateOprfKeyRegistry` / `updateVerifier` are `onlyOwner`). Staging can change under us without notice. VERIFIED (cast; WorldIDVerifier.sol L247-290).
6. **Freshness is the same in both.** `rootValidityWindow = 3600` s on both registries (`0x8556…A16D` staging, `0x0000…67d4` prod). The latest root is always valid, and a superseded one stays valid for 1 h. `minExpirationThreshold = 18000` s. **Rule: submit the Safe tx within about 1 h of generating the proof, in either env.** VERIFIED (cast; WorldIDRegistry.sol L161-168).

### Design, ready to implement

```solidity
address constant WID_PROD    = 0x00000000009E00F9FE82CfeeBB4556686da094d7;
address constant WID_STAGING = 0x703a6316c975DEabF30b637c155edD53e24657DB;
uint64  constant RP_ID       = 0x1469245f4f78143c;   // same rpId in both registries
struct Cfg { ...; address wid; }                     // set once in initSafe
function initSafe(..., address wid) external {       // require(wid == WID_PROD || wid == WID_STAGING)
event HumanEnv(address indexed safe, address wid);   // UI shows a "STAGING — simulator identities" badge
function setHumanEnv(address wid) external;          // msg.sender == safe only, so it goes through the PoP-gated
                                                     // execTransaction path (or the escape hatch). No redeploy.
```

- Don't let `wid` be an arbitrary address. A wrong or fake verifier would make the "onchain World ID" claim empty, and a judge who reads the code will see it.
- Key used nullifiers by `(wid, nullifier)`. Staging and prod nullifiers never collide in meaning.
- `signal_hash = keccak256(bytes(signal)) >> 8`. Checked: `vpin-signal` → `0x006b9f…20a9`, matching the bridge output.

### Consequences for the server and the demo

- **The server must not verify staging proofs through the Portal.** Without a window it gets a 403. Pick one:
  - (a) Open a 24 h window on demo day via the Developer Portal MCP tool `set_world_id_staging_verification`, and send `x-staging-verification-token` on every call.
  - (b) **Recommended:** in staging, the server checks the proof with an `eth_call` of `verify` on `0x703a` (the same call as above; no gate, no token). The Safe tx is then checked again onchain anyway.
- **Honesty.** Staging identities are free: the simulator made 5 identities on page load ("Generating first five identities…"). A staging demo proves the pipeline works. It does not prove the owners are unique humans. Say so on the screen (the badge) and in the README. If two teammates have Orb-verified World ID, run the headline take on prod with `setHumanEnv(WID_PROD)`, one PoP-gated tx. Keep staging as the fallback take.
- **Runbook line:** "Demo Safe env = STAGING | PROD (read `cfg(safe).wid`). Generate both human proofs, then submit within 60 min. The server human check is eth_call to the same `wid`."

### Still open

- Whether the simulator shows a *different* identity per browser profile or per "identity" pick, so two owners get two distinct nullifiers. It very likely does (5 identities are generated), but it's untested. Cheapest check: two simulator tabs with different `/id/0x…` and the same action; compare the nullifiers.
- Whether the prod path works *today*: needs a fresh World ID app proof plus `cast call` on `0x…94d7` within 1 h. Same script with `node req.mjs production`, scanned by a real phone.

## portal-app-identity-and-rp

**Answer: create a new production app named `enconomy`, configured for World ID 4.0 (the Portal calls it "managed" mode). A new rp_id can be used about 30–60 s after registration, in Portal verify and onchain alike. Keep the spike app only as a fallback. If we fall back to it, rename it to `enconomy` and disclose it.**

What the judges see today with the spike app:
- The World ID consent screen gets its name from Portal `POST /api/v4/proof-context/{rp_id}`, which the authenticator calls "before rendering proof request modals". The live answer for the spike app is `{"app_id":"app_957c2f7367de651c77a4c2a4e9cb9a7d","rp_id":"rp_1469245f4f78143c","name":"worldid-spike","is_verified":false,...}`. So the video would show **"worldid-spike"**. VERIFIED(curl 2026-09-26; developer-portal@cb3305e `web/api/v4/proof-context/[id]/index.ts` L60-68, L207-210). Whether World App renders exactly this `name` string: UNVERIFIED on a device.
- `name` is `verified_app_metadata.name ?? unverified_app_metadata.name`. While an app is unverified, its name can be edited in Portal > Configuration > Basic information (`isEditable = verification_status === "unverified"`). So renaming the spike app changes the prompt text and keeps the rp_id. VERIFIED(`web/scenes/PortalV3/.../Configuration/BasicInformation/index.tsx` L87, L286).
- Onchain, the spike RP was registered at World Chain block 35462287 (2026-09-24 23:30:13 JST, tx `0xe56b9e04…c4a3c`) with `unverifiedWellKnownDomain = "worldid-spike"`. Renaming in the Portal does not change this onchain string. Only someone reading the explorer would see it. VERIFIED(`cast logs` RpRegistered on RpRegistry `0xD9A213A92Bca460D56cDbBF4d775b48fB5925BbC`, topic rpId `0x1469245f4f78143c`).
- The spike app is a production app (`app_…`, not `app_staging_…`), and its status is `{"production_status":"registered","staging_status":"registered"}`. VERIFIED(curl `/api/v4/rp-status/rp_1469245f4f78143c`).

How a new app becomes usable:
1. `rp_id = "rp_" + hex16(uint64(keccak256(utf8(app_id))[0:8]))`. It is fixed by the app_id, so it is known right after the app is created. VERIFIED(`web/lib/rp.ts` L11-23).
2. "Enable World ID 4.0" in the Portal (or the Portal MCP tools `create_app` then `configure_world_id`) does the following:
   - generates the signer wallet;
   - returns the **private signing key once** ("Private keys are returned only at generation/rotation time");
   - submits an ERC-4337 UserOp `RpRegistry.register(rpId, manager=Portal KMS key, signer, appName)` on chain 480;
   - best-effort mirrors the registration to the staging registry;
   - sets the DB status to `pending`.
   **Staging apps cannot use 4.0** (`staging_not_supported`), so make a production app. VERIFIED(`web/api/helpers/rp-registration-flows.ts` L81-372; `web/api/mcp/index.ts` ~L1150-1185).
3. `RpRegistry.register` calls `OprfKeyRegistry.initKeyGen(oprfKeyId = rpId)` in the same tx. The OPRF nodes then run a DKG, which ends in `SecretGenFinalize`. Until it finishes, `OprfKeyRegistry(0x0D8b461799474207A3d223553d4d5e6609cb0c69).getOprfPublicKey(uint160(rpId))` reverts with selector `0xfbf20062`. `WorldIDVerifier.verify` reads exactly that key at L175-176, so a proof cannot be made or verified before then. VERIFIED(world-id-protocol `RpRegistry.sol` L260/273, `WorldIDVerifier.sol` L174-176; `cast call` on an unknown id reverts, on the spike id returns a point; the verifier's `getOprfKeyRegistry()` = `0x0D8b…0c69`).
4. **Measured propagation.** Over the last 100 RP registrations on 480 (blocks 35337911–35536745, about 4.6 days), `RpRegistered` → `SecretGenRound1` happened in the same block every time. `SecretGenRound1` → `SecretGenFinalize` took min **24 s**, median **24 s**, max **72 s**. There were 0 `KeyGenAbort` and 0 `NotEnoughProducers` events. The spike's own key finalized 12 blocks (24 s) after registration. VERIFIED(`cast logs` via `https://worldchain-mainnet.gateway.tenderly.co`; block time 2 s checked; script `scratchpad/rpprop/an.py`). The public Alchemy RPC caps `eth_getLogs` at 100 blocks, so use Tenderly for log scans.
5. **Portal gate.** `/api/v4/verify/{rp_id}` and `/proof-context` return `400 rp_not_active` until the DB row says `registered`. The row flips from `pending` only when `/api/v4/rp-status/{rp_id}` reads the chain: onchain `initialized && active`, and the manager and signer are Portal-owned. So **poll `GET /api/v4/rp-status/{rp_id}` until `production_status == "registered"`**; that step is what moves the row. A row still pending after 5 min goes to `failed`. VERIFIED(`web/api/v4/verify/index.ts` L149-152; `web/api/v4/rp-status/[rp_id]/index.ts`, `PENDING_TIMEOUT_MS = 5 min`; `rp-utils.ts mapOnChainToDbStatus`).
6. **Dynamic actions** work for any registered RP. When the action is missing, the verify handler creates it; nothing is gated per app or by age. VERIFIED(`uniqueness-proof/handler.ts` L191-203).
7. **Portal verify and onchain verify are the same check.** Portal v4 verifies uniqueness proofs by `eth_call` to the onchain Verifier contract (`verifyProofOnChain` in `temporal-rpc.ts`, chain 480). So a proof that returns `success:true` with `environment:"production"` passes `verify()` on `0x00000000009E00F9FE82CfeeBB4556686da094d7`, as long as it is still inside its validity window. VERIFIED(`uniqueness-proof/verify-v4.ts` L1-21, `handler.ts` L110-113). The Portal's prod `VERIFIER_CONTRACT_ADDRESS` is not in the repo (the `.env.example` value is zero). That it equals `0x…9E00F9…` is inferred from the spike replay passing there: UNVERIFIED directly.

**Readiness check for the new rp_id, no phone needed.** All three must hold:
```
curl -s https://developer.world.org/api/v4/rp-status/$RP_ID            # production_status == "registered"
cast call 0xD9A213A92Bca460D56cDbBF4d775b48fB5925BbC "getOprfKeyIdAndSigner(uint64)" 0x${RP_ID#rp_} --rpc-url $WC   # signer == our signer address
cast call 0x0D8b461799474207A3d223553d4d5e6609cb0c69 "getOprfPublicKey(uint160)((uint256,uint256))" 0x${RP_ID#rp_} --rpc-url $WC  # no revert
```
Also check the consent name with `curl -X POST .../api/v4/proof-context/$RP_ID -d '{"action":"pop:probe","environment":"production"}'` → `name == "enconomy"`.

**Secrets.** The repo is public (`git@github.com:tawago/enconomy.git`). The root `.gitignore` and `server/.gitignore` both ignore `.env` and `.env.*`; `git check-ignore server/.env` matches. VERIFIED. Put these in `server/.env`, following the spike's names:
- `WORLD_APP_ID`
- `WORLD_RP_ID`
- `WORLD_SIGNING_KEY` (secp256k1 hex; never logged)
- `WORLD_SIGNER_ADDRESS`

At startup, check that the signer address derived from the key matches `getOprfKeyIdAndSigner`. The spike's `/health` already does this (`signer_matches_key`). The spike keys live in `~/dev/worldid-spike/.env`. That repo has no commits and ignores `.env`. Do not copy those keys into enconomy unless we choose the fallback.

**Recommendation.**
- Create a new app now: name `enconomy`, production, World ID 4.0. Registration and DKG take about 1 min. Setting it up takes about 5 min of the user's Portal time.
- The name is baked into the onchain `unverifiedWellKnownDomain` at registration, so set it **before** enabling 4.0.
- It gives a clean app name in the video and no pre-existing-artifact disclosure for the RP.
- Fallback, if Portal creation fails at the event: rename the spike app to `enconomy`, and list "World ID Portal app/RP created 2026-09-24 in a spike" as pre-existing work.

**Still open (needs the user: Portal login plus the Orb-verified phone, about 10 min):**
1. Create the app and enable 4.0.
2. Poll rp-status and log the time to `registered` (expect ≤ 90 s).
3. Point the spike backend's `.env` copy at the new ids and run one real proof through `/api/v4/verify/{new_rp_id}` with action `pop:<32hex>`.
4. `eth_call verify()` on `0x…9E00F9…` with that proof within 5 min, using the recipe in worldid.md §replay.

Our code does not predict any failure here. The only live risk is a Portal- or World App-side cache of the app name or RP. Two things were not done because both need the user's account and phone: creating the app and running a real proof.

## server-driven-idkit-connector

Status: partially resolved. Everything up to "World App scans the QR" is VERIFIED on this Mac against the live production bridge. A real scan followed by Portal verify 200 through the sidecar has not been run. That needs a human with a World ID phone, about 5 minutes (steps below).

**Answer: yes.** A Node sidecar next to FastAPI can create the IDKit v4 request and poll the bridge, and the phones only render or open `connector_uri`. Proven:
- `@worldcoin/idkit-core` 4.2.4 runs in Node 24 (ESM) with a 6-line fetch shim.
- A Python-signed `rp_context` goes in (spike `app/signing.py`).
- The request is created on `bridge.worldcoin.org` in about 1.3-1.8 s.
- `connectorURI = https://world.org/verify?t=wld&i=<uuid>&k=<aes key>[&return_to=...]` comes back.
- `pollOnce()` returns `waiting_for_connection`.

VERIFIED(`scratchpad/idkitnode/sidecar.mjs`, `idkit-sidecar.mjs`, `client.py`, run 2026-09-26 17:07 JST, request ids `27a64b75-…`, `b2146d47-…`, `65d12dbd-…`).

**Facts found**
- **The WASM is bundled, not fetched from a CDN.** `dist/idkit_wasm_bg.wasm` (870,020 B) ships in the npm tarball. wasm-bindgen init does `fetch(new URL("idkit_wasm_bg.wasm", import.meta.url))` (CJS build: `pathToFileURL(__filename)`). VERIFIED(`dist/index.js:2208-2213`, `index.cjs:2212`).
- **Without a shim, Node fails** in both ESM and CJS with `Failed to initialize IDKit WASM: TypeError: fetch failed`, because Node's fetch rejects `file:` URLs. `initIDKit()` calls `__wbg_init()` with no argument, and neither `initSync` nor the wasm namespace is exported, so the only hook is `globalThis.fetch`. VERIFIED(`noshim.mjs`, `cjs.cjs`; `dist/index.js:2222-2236`, export list line 3144). `src/lib/wasm.ts` is unchanged at the 4.3.0 source (idkit HEAD 16bc527), so the shim applies to 4.3.0 too. VERIFIED(git log).
- **Node takes the bridge path.** `isInWorldApp()` is false in Node, so `.preset()` goes to the WASM bridge transport. VERIFIED(`dist/index.js:2903-2935`; `isNode() = true` printed).
- **The bridge protocol**, from `rust/core/src/bridge.rs:919-1300`:
  - Create: `POST https://bridge.worldcoin.org/request {iv: b64(12B), payload: b64(AES-256-GCM(json))}` → `{request_id}`.
  - Poll: `GET /response/{id}`, unauthenticated → `{status: initialized|retrieved|completed, response: {iv, payload}|null}`.
  - The key exists only in the `k=` URL param and in the sidecar's memory.
  - VERIFIED: `curl https://bridge.worldcoin.org/response/b2146d47-…` → `{"status":"initialized","response":null}`, and an unknown id gives 404.
- **The request payload** (decrypted debug report):
  - `proof_request{action: field(0x00f7…), nonce, oprf_key_id: 0x1469245f4f78143c (= rp_id hex), proof_requests: [{identifier: "proof_of_human", issuer_schema_id: 1, signal: "0x…"}], proof_type: "uniqueness", rp_id, signature, created_at, expires_at, version: 1}`
  - plus `package_name: "idkit_js_core"`, `environment: "production"`, `verification_level: "orb"`.
  - `allow_legacy_proofs: true` appears in the payload even though `false` was passed, so the `proofOfHuman` preset sets it itself. VERIFIED(debug report). Not an issue for us, but the Kotlin spike's payload hasn't been diffed against it.
- **`return_to` works server-side.** Passing `return_to: "enconomy://worldid"` to the sidecar puts `&return_to=enconomy%3A%2F%2Fworldid` in the URI. So one server path serves both modes: same-device `openUri`, and other-phone QR. VERIFIED(`client.py` output).
- **npm install gate.** On this machine the npm config has `before = now-7d`, which refuses 4.3.0 (published 2026-09-19T16:54Z) until 2026-09-26T16:54Z. The test used **4.2.4** (2026-08-31, the same version as the spike's parity signer). Pin `@worldcoin/idkit-core@4.2.4`. VERIFIED(`npm view … time`, `npm config get before`).

**Why the real scan should work (not yet tested).** The World App only sees `i` and `k`. It pulls the encrypted request from the bridge and posts an encrypted response back. It cannot tell who polls. The bridge client (`bridge.rs`) is the same Rust core the Android Kotlin 4.0.7 build uses, and that build already got Portal `success:true` twice (see human-to-device-mapping). The only differences are `package_name`/`package_version` in the payload. UNVERIFIED end to end.

**Sidecar, tested code (copy into e.g. `server/idkit-sidecar/`, own `package.json` with `"@worldcoin/idkit-core": "4.2.4"`):**

```js
import { createServer } from "node:http"; import { readFileSync } from "node:fs"; import { fileURLToPath } from "node:url";
const realFetch = globalThis.fetch;                       // shim: wasm-bindgen fetches a file: URL
globalThis.fetch = async (i, o) => (i instanceof URL && i.protocol === "file:")
  ? new Response(readFileSync(fileURLToPath(i)), { headers: { "content-type": "application/wasm" } }) : realFetch(i, o);
const { IDKit, proofOfHuman } = await import("@worldcoin/idkit-core");   // dynamic import AFTER the shim
const reqs = new Map();                                   // request_id -> {req, created}; drop after 10 min
// POST /requests {app_id, action, signal, rp_context{rp_id,nonce,created_at,expires_at,signature}, return_to?, environment?}
//   req = await IDKit.request({app_id, action, rp_context, allow_legacy_proofs:false, environment, return_to}).preset(proofOfHuman({signal}))
//   -> {request_id: req.requestId, connector_uri: req.connectorURI}
// GET /requests/:id -> st = await req.pollOnce() -> {status: st.type, error: st.error, result: st.result}
//   status in waiting_for_connection | awaiting_confirmation | confirmed | failed; delete entry on confirmed/failed
// listen 127.0.0.1 only
```

(The full 40-line file is in `scratchpad/idkitnode/idkit-sidecar.mjs` while the scratchpad lives.)

**Design for the doc (both SAFE and POOL)**
1. `POST /v1/session/{sid}/worldid/start {role}`. The server:
   - signs `rp_context` (Python, the spike signer);
   - builds `signal = encodePacked(nonce, role)`;
   - calls the sidecar;
   - stores `request_id` on the session row;
   - returns `{connector_uri, expires_at}` to the phone of that role only.
2. The phone shows a QR of `connector_uri` (zxing / `CIQRCodeGenerator`), or opens it (same-device). Then it long-polls `GET /v1/session/{sid}/worldid/{role}`. The server polls the sidecar every 1-2 s. On `confirmed` it forwards `result` unchanged to `POST https://developer.world.org/api/v4/verify/{rp_id}` (existing spike code) and stores the nullifier.
3. **Removed from the app:**
   - iOS: the SPM `idkit-swift`, the Swift `WorldIdProver` class, the Kotlin-Swift interface, and the background-hop problem (mobile-wallet.md U3). The pending request now lives on the server, so an app kill loses nothing; the phone just re-polls.
   - Android: the GitHub Packages dependency `com.worldcoin:idkit:4.0.7` and its token.
   - Kept: a QR renderer, and for same-device an `enconomy://worldid` intent-filter / `CFBundleURLTypes` that only brings the app back.
4. **Security.** `k` (the AES key) is now on the server. That's fine: the server sees the proof anyway to verify it. Serve `connector_uri` only to the authenticated device of that role. Anyone holding the URI can answer with their own World ID, same as the phone-driven QR. The nullifier plus `signal = nonce‖role` binding is what counts.
5. **Ops.** One more process. Run it as `node server/idkit-sidecar/index.mjs`, bound to 127.0.0.1:8787. Add a `/health` check that the sidecar answers.
6. **Python port instead?** Doable but not worth it. It would need:
   - AES-GCM plus the two bridge calls (easy);
   - rebuilding the `proof_request` JSON above, with action hash-to-field, `oprf_key_id` and signal encoding;
   - converting the v2/v2.1 bridge response into the `IDKitResult` shape that Portal expects (`proof_response_with_claims_to_idkit_result`, `bridge.rs:411-545`).

   That's roughly half a day with protocol drift risk, versus 40 lines of Node.

**What remains, cheapest check (5 min, needs one World ID human)**
```
cd scratchpad/idkitnode     # or the committed sidecar
ENVFILE=~/dev/worldid-spike/.env POLLS=90 node sidecar.mjs "pop:sidecar-scan-1" | tee out.txt
qrencode -t ansiutf8 "$(head -1 out.txt | jq -r .connectorURI)"   # scan with phone camera -> World ID app
# expect status waiting_for_connection -> awaiting_confirmation -> confirmed; then:
jq -c 'select(.status=="confirmed").result' out.txt | curl -s -XPOST localhost:8000/verify -H 'content-type: application/json' -d @<(jq -c '{action:"pop:sidecar-scan-1",result:.}')
# expect portal_status 200, success:true (spike backend running)
```

## guard-u-never-executed

**Answer: yes, now. The combined guard ran a real Safe `execTransaction` with two real World ID v4 proofs, on a 480 fork pinned to block 35464545.** It executed in forge and as a broadcast tx on anvil from a separate relayer EOA: status 1, gasUsed **886,554**, `eth_estimateGas` **899,940**. No caller or proxy restriction. The 664 B tail parses fine behind EOA and EIP-1271 owner sigs. The nullifier-to-pairTag glue matches the server's Python byte for byte. All 8 negatives revert with the expected error. VERIFIED(forge 1.4.3 / anvil 1.4.3, `https://worldchain-mainnet.g.alchemy.com/public`, 2026-09-26).

What stays unproven: the **final signal and action formulas with real proofs**. The only real proofs we have were made with signal `"spike"` and two different actions, so the test guard overrides those two functions (details below). Every other line of the guard is the production code.

Prototype (scratchpad, temporary, copy before it's gone): `/private/tmp/claude-501/-Users-takahiro-ogawa-dev-enconomy/3d9dd236-bf59-4c81-91f5-6bb7c5ebc6e3/scratchpad/guardu/`
- `src/PopSafeGuardU.sol`: the devreg `PopSafeGuard` (POP2 + registry + hatch) plus `_verifyHumans`.
- `test/GuardU.t.sol`: 11 tests, 11 PASS.
- `script/Anvil.s.sol`: the anvil broadcast run.
- `fixtures/spike-proofs.json`: both proofs and the fork block.

### Fixture: two real proofs that verify forever at one block
- Proof A is `spike-1790264612780`, `expiresAtMin` 1790264612. Proof B is `spike-1790264710529`, `expiresAtMin` 1790264710. Both come from `~/dev/worldid-spike/backend/logs/backend.log`. They share the Merkle root `proof[4] = 4811…6258`.
- Both pass `verify` at **block 35464545** (ts 1790264729). Block 35464531, used earlier, predates proof B. VERIFIED(`cast call … --block 35464545` → `0x` for both).
- Implementation at that block: `0xff93a014…4c73`, the same V2 as today.
- Safe L2 1.5.0 `0xEdd1…7C7e`, factory `0x14F2…5e7b` and CompatibilityFallbackHandler `0xfd07…Ec99` all have code at that block.
- Forking 1900 blocks later (+3800 s) gives `InvalidMerkleRoot` `0x9dd854d3`. So the window is real and the pin is what makes the fixture permanent.
- **Don't `vm.warp` in these tests.** `isValidRoot` and `ExpirationTooOld` both read `block.timestamp`.

### Tail layout that was executed (freeze this)
```
signatures = ownerSigs (static 65·k, then EIP-1271 dynamic parts)
           ‖ WID block (492 B): sid(16) ‖ notBefore(u64 BE, 8) ‖ hA(232) ‖ hB(232) ‖ "WID1"(4)
           ‖ POP2 tail (172 B): pairTag ‖ devA ‖ devB ‖ expiry(u64 BE) ‖ r ‖ s ‖ "POP2"
h (232 B)  = nullifier(32) ‖ rpNonce(32) ‖ expiresAtMin(u64 BE, 8) ‖ proof[0..4](5·32)
```
- The run used 2 owners: an EOA plus a `P256Owner` contract signature with a 96 B dynamic part at offset 130.
- Total `signatures` = 890 B. `execTransaction` calldata = 1,284 B (473 zero bytes).
- Safe's `checkNSignatures` ignores the trailing 664 B. VERIFIED(test + anvil tx).

### Guard logic that ran (order matters)
1. POP2 attestation. It is unchanged from `## owner-device-registry`.
2. WID magic, then `nA != nB` (`SameHuman`), then `sha256("pop-pair-v1" ‖ min ‖ max) == POP2.pairTag` (`PairTagMismatch`). These checks come first because they are cheap.
3. `n = keccak256(abi.encode(keccak256("pop-ctx-v1"), chainid, msg.sender /*Safe*/, safeTxHash, notBefore, sid))`, as in `## ctx-nonce-formula-drift`.
4. Two calls: `WID.verify(nX, actionOf(sid), RP_ID, rpNonceX, keccak(n‖role)>>8, expX, 1, 0, proofX)`, with role 0x41 for A and 0x42 for B. The verifier reverts on failure, and the revert data bubbles up through Safe unchanged.
5. **`actionOf(sid) = keccak256("pop:" ‖ lowercase hex(sid)) >> 8` is computed onchain**. No action is taken from calldata.
   - `test_actionOf_matches_text` shows it equals hashing the text `pop:00112233…eeff`.
   - Gas for the hex loop is negligible.

### Results (fork 480 at block 35464545, Safe L2 1.5.0, owners = EOA + P256Owner)
| test | expected | result |
|---|---|---|
| real exec, proofs A,B, POP2 with pairTag from nullifiers | executes, bob +1 ETH, nonce 1 | PASS. 820,275 gas in-test (no intrinsic or calldata) |
| replay the identical blob | revert (Safe nonce moved) | PASS |
| same nullifier twice (hA,hA) | `SameHuman` | PASS |
| roles swapped (hB in slot A) | verifier `ProofInvalid` 0x7fcdd1f4 | PASS |
| proofs bound to the 1 ETH tx, owners + server sign a 2 ETH tx | `ProofInvalid` | PASS |
| POP2 pairTag not derived from the nullifiers | `PairTagMismatch` | PASS |
| no WID block (owner sigs ‖ POP2 only) | `NoHumans` | PASS |
| one bit flipped in proof B | `ProofInvalid` | PASS |
| production guard (no overrides) fed the spike proofs | `ProofInvalid`: the signal is recomputed, never read from calldata | PASS |
| same, forked 3800 s later | `InvalidMerkleRoot` | PASS |
| pairTag: Solidity `pairTagOf(nA,nB)`, either order, vs `popzk.pair_tag` (research/sound-bound/spikes/zk/verifier/popzk.py L179) | `0xe0a248dd5ec084994b2aca7fee294660f9ee6a93dd5a3a49f6d2b1d7d78c76bb` | PASS. Also identical in Python for hex input and decimal-string input |

**Anvil broadcast** (anvil `--fork-block-number 35464545 --hardfork osaka`):
- `forge script` deployed P256Owner, guard, setup and Safe.
- A different EOA then sent `execTransaction`. Tx `0x57c6…552f` in block 35464552 (ts 1790264807), status 1, **gasUsed 886,554**, 2 logs. `cast estimate` gave 899,940 (+1.5%).
- So a relayer that calls `eth_estimateGas` first gets a working limit.
- Caveat: anvil used the Osaka P-256 price (6,900 per call vs 3,450 under RIP-7212 on OP chains). Live 480 should come in a few k gas lower. UNVERIFIED on live 480.

### The four worries, one by one
1. **Verifier called from a contract.** Every entry point is `external view onlyProxy onlyInitialized`. `onlyProxy` checks `address(this)`, not the caller. There is no `msg.sender` or `tx.origin` check. VERIFIED(world-id-protocol @7ac826e `contracts/src/core/WorldIDVerifier.sol` L98-210 + this test). A `view` guard can call it: the guard compiles `view` and the staticcall path works.
2. **Tail with owner sigs.** Works with EOA + 1271 dynamic parts ahead of it. VERIFIED.
3. **Gas.** About 887k used and about 900k estimated per spend.
   - **The fixed "force mode" limit of 600,000 in `## visible-failure-path` would run out of gas for SAFE.** Use estimate × 1.2, and a force limit of at least 1,100,000 for SAFE. Keep 600k for the pool.
   - 480 block gas is not a constraint.
4. **uint256 → 32-byte BE parity.** `abi.encodePacked("pop-pair-v1", uint256 lo, uint256 hi)` equals Python `b"pop-pair-v1" + a.to_bytes(32,"big") + b.to_bytes(32,"big")` with numeric sort.
   - Portal returns nullifiers zero-padded to 64 hex digits (`0x0df44f…`, log L70), so lexicographic and numeric order agree.
   - The server must still sort numerically, as popzk does.

### Found along the way (design impact)
- **One action for both roles is load-bearing.** The two spike proofs are very likely the same human (same phone and IP in the log). They have different nullifiers only because their actions differ, and they passed `nA != nB` in the harness. So the guard must derive a single action from `sid` for both slots, as `actionOf` does here. Never accept per-role or caller-supplied actions. Otherwise one human with two actions looks like two distinct humans.
- The rpNonce is only a public input. The verifier doesn't check it against anything, and the guard doesn't need to (binding comes from the signal). VERIFIED(source L150-210).
- No onchain nullifier store is needed for SAFE. The proofs are bound to `safeTxHash`, which includes the Safe nonce, and the guard stays `view`.

### What remains, and the cheapest way to close it
- **A positive run with the final signal and action formulas.** It needs **two Orb-verified humans**. One human gets the same nullifier for the same action, so the guard correctly returns `SameHuman`. Steps:
  1. Create a server session for a fixed Safe tx.
  2. Both phones run IDKit with action `pop:<sid>` and signal `"0x"+hex(n‖role)`.
  3. Save both responses and the current block number.
  4. Paste them into `fixtures/`.
  5. Run the production `PopSafeGuard` (no `SpikeGuard`) on a fork at that block.
  - This takes about 15 min. The Safe address and `safeTxHash` must be fixed before the proofs are made, so deploy the Safe on the fork with a deterministic salt (`createProxyWithNonce` gives the same address on fork and live), or derive `safeTxHash` for the known address first.
- A live-480 gas number (a single `cast estimate` after deploy). The P-256 price difference is the only expected delta.
- Where the prototype goes: copy `guardu/src` + `test` + `fixtures` into the SAFE contracts package when implementation starts. The `SpikeGuard` harness is test-only.

## transfer-circuit-soundness-review

**Answer: now reviewed. No fund-losing hole found in `PresenceTransfer(32,20)` or `PresencePool.transfer`. Three things to act on: (1) a 0-value transfer is SAT today, so decide the policy and add `IsZero` at freeze (+1 constraint); (2) the circuit accepts aliased depths `p-31..p-1` / `p-43..p-1`, and the contract bound is the only thing that rejects them (harmless, because depth never feeds the root); (3) the real risk is the single-party zkey, not the constraints. A forged transfer proof can mint a payee note of any value and drain the pool, so cap TVL and add a contribution plus a beacon.**

Scope: `scratchpad/pool/privacy-pools-core/packages/circuits/pres/presenceTransfer.circom` (the LABEL_TRANSFER build; r1cs sha1 `bcc93ddf…` is identical to `ppe2e/keys/presenceTransfer.r1cs`), plus `commitment.circom`, `merkleTree.circom` and `ppe2e/src/PresencePool.sol`. Tools: circomspect 0.9.0, circom 2.1.8 `--inspect`, snarkjs 0.7.5 `wtns check` against the r1cs, and forge with real Groth16 proofs over FFI. Artifacts are in `scratchpad/soundness/`: `circomspect*.txt`, `inspect.txt`, `cases.mjs`, `forge/test/TransferSoundness.t.sol`, `presenceTransferNZ.circom`.

### Static analysis (VERIFIED: `circomspect -L node_modules -l INFO presenceTransfer.circom` and `merkleTree.circom commitment.circom`)
Main template: 4 findings, all benign.
- `remaining <== existingValue - transferValue` may overflow. Covered: `remaining` and `transferValue` each go through `Num2Bits(128)`, so `existingValue = remaining + transferValue < 2^129`, no wrap. `tv = p-1` and `tv = 2^128` are UNSAT (witness test).
- `contextSquared` is used in only one constraint. Intended: it's the standard dummy square that binds a public input.
- `chC.nullifierHash` unused. The change note's Poseidon(1) is wasted (~240 constraints); it is still constrained inside `chC`, so there's no soundness impact.
- Libs: "`LessThan` compares values > p/2" is the depth aliasing below. The `Num2Bits` aliasing warning only matters for n ≥ 254; here n is 32, 20, 7 or 128.
- `circom --inspect`: 4 CA02 warnings. The unused bits of `r1.out`/`r2.out` and `LessThan.n2b.out` are normal for range checks; `chC.nullifierHash` is the same as above.

### Witness tests against the r1cs (VERIFIED: `node scratchpad/soundness/cases.mjs`, `wtns calculate` + `wtns check`)
| case | result |
|---|---|
| good; full spend (change = 0) | SAT |
| **transferValue = 0** | **SAT** |
| newNullifier == existingNullifier | UNSAT |
| stateTreeDepth 0 (real 2), 32 | SAT: depth is not bound to the path |
| stateTreeDepth 33 / p-32 | UNSAT |
| **stateTreeDepth p-1, p-31** | **SAT** (LessEqThan(6) wraps: `x+31` fits 6 bits) |
| presenceTreeDepth 20 / 21 / p-44 | SAT / UNSAT / UNSAT |
| **presenceTreeDepth p-1, p-43** | **SAT** |
| tv = 2^128; tv = p-1 | UNSAT |

### Checklist (manual, each line checked against source)
1. **Every private signal is constrained.** `label` goes into inC and chC (P3). `existingValue` → inC, remaining. `existingNullifier` → P1, P2(pre), P2(payerTag), IsEqual. `existingSecret` → P2(pre). `newNullifier`/`newSecret` → chC. `transferValue` → remaining, Num2Bits, pc. `payeePrecommitment` → pc. Siblings and index → the LeanIMT path. The 3 outputs are deterministic hashes of constrained inputs, so there are no free outputs. Index bits at levels with a zero sibling are free, but they are private and change nothing. VERIFIED (read).
2. **Arity separation.** Poseidon(1) is used only for nullifierHash. Poseidon(2) covers precommitment `(nul,sec)`, payerTag `(TAG_PAYER,nul)` and Merkle nodes. Poseidon(3) covers the note commitment, the payee commitment (same format, on purpose) and the presence leaf `(TAG_PRES,payerTag,pc)`. circomlib Poseidon uses t-specific round constants, so a value can't be both a P2 and a P3 output: no leaf↔node second preimage, and no "spend a presence leaf as a note" (that would need `pc = P2(n,s)` with `pc` a P3 output). Residual: payerTag has the same shape as a precommitment with `nullifier = TAG_PAYER`. It is never published or placed in a tree, so there's no attack. The trees are also separate: the state and presence root histories are different mappings (`test_stateRootAsPresenceRoot_rejected`). VERIFIED (read + test).
3. **Value conservation.** `existing = remaining + tv`, both < 2^128. VERIFIED (witness).
4. **One ticket = one transfer.** The leaf binds `payerTag = P2(TAG_PAYER, existingNullifier)` and `pc`, which contains the value and payeePre. The nullifier is spent once, and nullifierHash = P1(nul) is the same across transfer, withdraw and ragequit in one mapping. VERIFIED: `test_transferThenWithdrawSameNote_rejected` asserts `withdraw.pub[1] == transfer.pub[0]` and the withdraw reverts `NullifierAlreadySpent`.
5. **Contract bounds.** `s[4] > 32 || s[6] > 20` reverts `InvalidTreeDepth`; this is load-bearing only against the aliased depths. Roots must be in their own 64-slot history, and `_known` rejects 0. `s[7] == TRANSFER_CONTEXT`. Public inputs < p: the snarkjs verifier runs `checkField` on all 8 signals (VERIFIED `grep -c checkField TransferVerifier.sol` = 8). Outputs go through `InternalLeanIMT._insert`, which reverts on ≥ p, 0 or a duplicate. Same pattern as 0xbow `PrivacyPool.withdraw`.
6. **Context** is a per-pool constant `keccak(abi.encode('pop-transfer-v1', SCOPE)) % p`, bound through `contextSquared`. It binds pool and chain (SCOPE includes `address(this)` and `chainid`). It does not bind a relayer or fee, which is fine: there are no fees, and a front-runner who submits the same proof produces identical state.
7. **LABEL_TRANSFER.** The payee note is `P3(tv, 0x706f702d7472616e73666572, payeePre)`. It can't be ragequit (`depositors[LABEL_TRANSFER] == 0`, existing `test_negative`). It always passes ASP, because the constructor inserts the label as ASP leaf 0. With the current auto-approve ASP this changes nothing. If a real ASP is added later, every payee note bypasses it; say so. Stale header comment: "(0xbow note format, label 0)" should say LABEL_TRANSFER.
8. **Attester power.** A compromised ATTESTER can only post leaves, i.e. remove the presence gate. It cannot spend anyone's note, because the payer still needs the note secrets. It can't see the amount either, because `pc` is hashed. So the attester can't enforce `value > 0`, and that check has to live in the circuit.
9. **Zero-value policy.** Recommendation: reject. Add to the circuit, right after `r2`:
   `component nz = IsZero(); nz.in <== transferValue; nz.out === 0;`
   VERIFIED: it compiles to 15,244 constraints (+1), good input SAT, tv=0 UNSAT (`scratchpad/soundness/presenceTransferNZ.circom`, `casesNZ.mjs`). Do it before the freeze and zkey regen, then flip `test_zeroValueTransfer_currentlyAccepted` to `expectRevert(InvalidProof)` (a 0-value proof can't be generated at all). If you keep 0 allowed, the only effect is a 0-value payee note that burns one presence ticket, with no fund impact.
10. **Trusted setup.** Groth16 soundness rests on the zkey. Whoever holds the single-party toxic waste can forge a transfer with any `payeeCommitment` value and withdraw the whole pool. Mitigations: the contribution + World Chain beacon + `zkey verify` flow already specified in this file (ptau section), and a hard TVL cap for the demo (fixed `DENOM = 0.001 ETH`, few deposits). Say "dev setup, capped TVL" to judges.

### Forge negative tests (VERIFIED: `cd scratchpad/soundness/forge && forge test` → 12 passed, 0 failed; chainid 480 set, no fork)
`test_good` (plus replay → `NullifierAlreadySpent`), `test_stateDepthAlias_validProof_contractRejects` (a real proof with `stateTreeDepth = p-1`: `TransferVerifier.verifyProof` returns **true**, the pool reverts `InvalidTreeDepth`), `test_presenceDepthAlias_validProof_contractRejects` (p-43), `test_depthLieInRange_isHarmless`, `test_pubSignalPlusP_rejected` (nullifierHash/change/payee + p → `InvalidProof`, so there's no nullifier aliasing), `test_rootPlusP_rejected`, `test_swapOutputs_rejected`, `test_wrongContext_rejected`, `test_unknownPresenceRoot_rejected`, `test_stateRootAsPresenceRoot_rejected`, `test_zeroValueTransfer_currentlyAccepted`, `test_transferThenWithdrawSameNote_rejected`. The file needs `ffi = true` and `js/prove.mjs` (ppe2e's prover plus an optional 3rd argv: a JSON override merged into the circuit input). Copy it next to `PresencePoolE2E.t.sol` when the pool code moves into the repo.

### Not done / remaining
- No formal under-constraint tool (Picus / ZKAP / Ecne). Cheapest next step: `picus` on the r1cs (Docker, about 30 min). With the manual checklist, circomspect and the witness matrix, "circomspect + written checklist + negative tests" is an honest claim; "formally verified" is not.
- No independent human reviewer.

Judge line: "The only new circuit is 15k constraints. It reuses 0xbow's audited CommitmentHasher and LeanIMT. We ran circomspect and circom --inspect, wrote a signal-by-signal checklist and 12 forge negative tests with real proofs. The setup is dev-grade (contribution + public beacon) and the pool is TVL-capped."
