# Laptop <-> phone proximity for EVP key rotation

Nov 3, 2026. Scope: the proximity leg of "rotate a smart account's key with EVP + ENS + a laptop/phone proximity proof, in an EIP-8141 frame tx". EVP verification and ENS details belong to the sibling notes; here they only show up where the proximity session binds to them.

Marks: VERIFIED = primary source opened or run here. CONTRADICTED = source says otherwise. UNREACHABLE = could not check without phones, a live chain or third-party code. Everything else is a proposal.

## Short answer

- What already ran on a Mac laptop browser is the **sound-bound** page (Flask + plain JS), as role A, with Android Chrome as role B. It worked. The Kotlin/Wasm PoP web build has never done a real audio run.
- A laptop page cannot make a scheme-2 frame signature over a raw digest with WebCrypto or a passkey. Both always hash first. They only verify when `msg = sha256(something)`, and VERIFY can't call the 0x02 precompile (a pure-Yul SHA-256 from the sibling spike could fill in, at unmeasured gas). Three ways around it below. The default is a WebCrypto non-extractable key plus a "pin in VERIFY, check in body" split.
- One 32-byte value ties it all together: `sessionNonce = PopCtx(chainId, account, ctxHash(newKey, recoveryNonce, deadline), notBefore, sid)`. It is the EVP `nonce`, it is signed inside both proximity transcripts, and it goes into the digest `D` the laptop signs. VERIFY recomputes it with keccak only.
- Be honest about what proximity proves. Against a stranger relaying between two honest devices, it is a real bound. Against a malicious new phone (in recovery, that is the attacker), it is not. One cheating side can fake NEAR (2026-09-25 memo). Here proximity binds *which* phone gets the key to a session the user started at the laptop. The security gate is still guardian key + EVP + timelock.
- Flag for the parent: this tx shape is self-paid and reads only the account's own storage. It is public-mempool admissible, so nothing about it is alt-mempool specific. The report already says the same of Meet-to-Recover.

## 1. What runs on a Mac laptop browser today

| Thing | State | Evidence |
| --- | --- | --- |
| sound-bound page, Mac Chrome as A + Android Chrome as B | **Works.** 41 session dirs on 2026-09-23/24. Every role-A user agent is `Macintosh; Intel Mac OS X 10_15_7`, every role-B one is `Android 10; K` | VERIFIED: `research/sound-bound/data/sessions/*/session.json` |
| Verdicts as stored | 0 cm: 6 NEAR, 1 UNDECIDED. 5 cm: 1/1. 30 cm: 8 NEAR, 1 UND. 60 cm: 6 UND (the 45-80 cm gray zone, by design). 100 cm: 5 FAR, 2 UND. 150: 1 FAR. 200: 2 FAR, 4 UND. Never NEAR at 100 cm or more, never FAR at 30 cm or less | VERIFIED: tallied from `result.json`. Some files predate the 2026-09-24 analysis fix, so they are stale |
| Offline re-run with today's `analysis.py` | 5c425adf (5 cm) and 3fc15a66 (30 cm), both stored UNDECIDED, now read NEAR 12.1 / 26.4 cm. e28e1d35 (0 cm) reads NEAR 1.8. 4056bce2 (100 cm) reads FAR 94.1 | VERIFIED: run here on copies in the scratchpad, `server/.venv` python, with a scipy stand-in for the missing `soundfile` |
| Echo cancellation off on Mac Chrome | honored | VERIFIED: handoff doc + quality flags |
| Mac clipping at touch | 2,247 samples, harmless | VERIFIED (re-run above) |
| Clock sync | 10 pings over HTTP, min RTT, server time mapped into `AudioContext` time | VERIFIED: `static/app.js` |
| Who decides | The server. Python matched filter over both uploaded WAVs. The browsers only play, record and upload | VERIFIED: `server.py` `analyze_and_broadcast` |
| Signing in sound-bound | **None.** No keys, no transcript signatures. The handoff's step 5 "sign and verify" was never started | VERIFIED |
| PoP web build (Kotlin/Wasm, `app/composeApp/src/wasmJsMain`, served at `/app/`) | Built, deployed to webapp.enconomy.dev. **No real audio run in a browser.** The README itself calls browser timing jitter "the open question" | VERIFIED (README + memory). Working audio is UNREACHABLE |
| PoP web build key | Software P-256 via `@noble/curves`, hex in `localStorage` (`pop.key.sk`), signs with `p256SignHash` (raw digest) | VERIFIED: `Crypto.web.kt` |
| iPhone in a browser | never tried on either stack | VERIFIED absence |
| Chrome automation through the self-signed cert | failed in September, so all browser runs were by hand | VERIFIED: handoff |

**Latency.** In sound-bound, the time from the scheduled start to `result.json` written was 5.5-7.1 s across 37 sessions (file mtime minus `start_server_ms`). The start itself is 2 s after both pages arm, so arm to verdict is about **7.5-9 s**. VERIFIED. The PoP protocol uses `t0 = now + 3 s` and a 2.5 s capture (`docs/pop-contract.md`). Pairing by QR, typing the EVP email, the Chrome EVP mint and frame-tx inclusion on the devnet add human seconds plus an unknown block time. Not measured.

## 2. What the laptop can sign with

| Key | Lives where | Scheme-2 frame sig possible? | Notes |
| --- | --- | --- | --- |
| WebCrypto ECDSA P-256, `extractable:false` | browser profile, IndexedDB (CryptoKey is serializable) | Only as `msg = sha256(X)`. Spec Sign step: "Let M be the result of performing the digest operation specified by hashAlgorithm using message". No prehash mode | VERIFIED (W3C WebCrypto, 23.7.1). Export refused with `InvalidAccessError`, VERIFIED (spec + run). It dies when site data is cleared. Whether Chrome on Mac wraps it with the OS keychain: not checked |
| WebAuthn passkey, ES256 | platform authenticator (iCloud Keychain / Google Password Manager) | Only as `msg = sha256(authData ‖ sha256(clientDataJSON))`. The challenge sits inside clientDataJSON as base64url | VERIFIED (WebAuthn L3: "assertion signature of the concatenation authenticatorData ‖ hash", ES256 = ECDSA w/ SHA-256, challenge = base64url). Usually synced (BE flag), so "laptop" really means "the user's passkey account". The page can read BE but can't force a device-bound key |
| Software P-256 (noble or hand-rolled), raw digest | `localStorage` / IndexedDB as bytes | **Yes, directly** | What the PoP web build does today. Script-readable, so XSS or an extension takes it. Demo tier |
| Anything hardware-bound the page controls | — | — | None. No WebCrypto option asks for TPM or Secure Enclave keys |

The scheme-2 check is in sidecar `FrameTxService/signature.ts` 18-75. The msg is the sig_hash when empty, else exactly 32 non-zero bytes. P-256 needs `0 < s <= n/2`, signer = `keccak(qx‖qy)[12:]`, and `p256.verify(sig, msg, pub, {lowS:false})` with no hashing. VERIFIED (source read).

`proximity-sigcheck/sigcheck.mjs` (Node built-ins only, own keccak and P-256 code, fresh in-memory keys) shows all of this (VERIFIED, 9/9 pass):
- A WebCrypto sig fails as scheme 2 with `msg = D` and passes with `msg = sha256(D)`.
- A passkey-shaped sig passes only with `msg = sha256(authData‖sha256(cdj))`.
- A software raw-digest sig passes with `msg = D`.
- WebCrypto doesn't promise low-s (one run gave high-s, a re-run on Nov 3 gave low-s). Anyone can flip it to low-s; no key is needed. The vectors file is regenerated with fresh keys on every run.
- PopCtx reproduces the pinned G vector.

Vectors are in `proximity-sigcheck/vectors.json`.

**The new phone's key (sig[0], over sig_hash) must sign raw digests.** An explicit `msg = sha256(sig_hash)` can't work, because the msg is part of the hashed tx (`notes/eip8141-family.md`). So on the phone, use the native PoP app with `poc-phone-signing/patch/app.patch`, or a software key in the phone browser. A WebCrypto key in the phone browser cannot be `newKey`.

## 3. Getting a laptop signature through VERIFY (no 0x02 there)

| Option | VERIFY does | Body frame does | Cost / risk |
| --- | --- | --- | --- |
| A. Software raw-digest guardian | `SP_MSG(1) == D` (keccak), signer ∈ guardians. Identical to `RecoverableP256Account._guardianSigner` | nothing extra | Zero new contract code. The key is script-readable |
| **B. WebCrypto non-extractable, pin-then-check (default)** | signer ∈ guardians; `SP_MSG(1) == m`, where `m` is a fixed word in `startRotation` calldata; recompute `D` with keccak from calldata + `recoveryNonce` | `require(sha256(D) == m)` via 0x02, then EVP check, then set pending | About 20 lines on top of RecoverableP256Account. If it fails, the fee is spent and nothing changes. Old `(m, sig)` pairs become public after a rotation, so anyone can replay them to burn the account's gas (the body reverts on the nonce). That is griefing only |
| C. Passkey | as B, `m` pinned | rebuild `sha256(authData‖sha256(cdj))`, check `cdj.challenge == b64url(D)`, type and origin | Most robust key, most body code (JSON/base64 in Solidity). Not built |

Why B is the default for Nov 5: the key can't be exported by script, it is cheap, and the pattern is the same one the EVP check needs anyway (precompiles in a body frame). Fall back to A if time runs out, since A needs no contract change.

**Interaction with the sibling native-EVP spike.** `evp-recovery/poc-native-evp/` has a pure-Yul SHA-256 (`Sha256Yul.sol`, no 0x02 call) and puts EVP itself into VERIFY with 3 native P-256 entries. Its own printout says the sidecar sum is already `79,900 + 3 × 6,700 = 100,000`, exactly at the cap (seen in `results/entries.txt`, not re-run by me). So:
- "VERIFY can't run sha256" is too strong. It can't call 0x02, but Yul SHA-256 works, so B could check `sha256(D) == m` in VERIFY (one block) and drop the griefing hole. The gas for one block is not measured here.
- If EVP goes native in VERIFY, the laptop's entry is a 4th native signature (+6,700) and won't fit under 100k. Then the laptop signature has to move to body-frame calldata, checked with 0x100. That is allowed, but only the body enforces it, so it's the same griefing caveat as B.
- If EVP stays in the body (about 63k, `poc-evp-issuer`), B as written fits easily.

The parent has to pick one of these. It decides where the laptop signature lives.

## 4. Binding: one nonce, one digest

```
ROT_DOMAIN   = keccak256("enconomy/evp-rotate/v1")
ctxHash      = keccak256(ROT_DOMAIN ‖ addr newKey ‖ u256 recoveryNonce ‖ u256 deadline)
sessionNonce = PopCtx(chainId, consumer = account, ctxHash, notBefore, sid)       // docs/worldid/01 §5, unchanged
evpNonce     = lowercase hex(sessionNonce)                                         // <input autocomplete="email-verification-token" nonce=…>
T            = keccak256(POPT_laptop ‖ POPT_phone)   // both transcripts sign sessionNonce; sound-bound fallback: hash of session.json + both wav sha256 + result.json
GUARD_DOMAIN = keccak256("enconomy/evp-rotate/guardian/v1")
D            = keccak256(GUARD_DOMAIN ‖ chainId ‖ account ‖ newKey ‖ recoveryNonce ‖ sessionNonce ‖ T ‖ deadline)
m            = sha256(D)        // option B; option A signs D itself
```

- The EVP token can't move to another key or session: Chrome sets the KB-JWT `nonce` from the page attribute (`notes/evp.md` §8), and `sessionNonce` commits to `newKey`, `account`, `recoveryNonce` and `deadline`.
- The audio run can't move either: both transcripts sign `sessionNonce` (PopCtx is already wired this way in the PoP app and server).
- `T` is outside the EVP nonce on purpose, so EVP can run before or during the audio run. `sid` is inside both, which is enough.
- `D` recomputes in VERIFY with keccak only. `recoveryNonce` comes from storage, `deadline` from frame 0, the rest from frame 2 calldata.

## 5. Message flow

```
New phone P (app, raw-digest newKey)      Server S (relay + session)            Laptop L (Chrome page, guardian key)          Chain
 read owner/recoveryNonce  ─────────────────────────────────────────────────────────────────────────────────────────────▶ eth_call
 POST /session {account,newKey,nonce,deadline} ▶ sid, notBefore, sessionNonce = PopCtx(…)
 show pop1 QR (sid)                                                         ◀── webcam scan / paste link
                                            ◀── join                         show account, newKey fingerprint, deadline
                                                                             recompute sessionNonce locally (refuse on mismatch)
                                                                             EVP: email field, nonce=evpNonce → Chrome mints SD-JWT+KB
 confirm, clock sync, arm  ───────────────▶  t0 = now+3 s  ◀──────────────── confirm, clock sync, arm
 ========= audio: each plays its own secret code, records 2.5 s, commit then reveal =========
 POPT_P signed by newKey (digest mode) ──▶   verdict NEAR/NOT_NEAR  ──────▶  fetch both POPTs, re-check verdict (viewer logic)
                                                                             on NEAR: T, D, m=sha256(D); sign m (WebCrypto)
                                            ◀── {m, sig_L, qL, EVT, KB}
 build frame tx:
   frame 0 VERIFY 0x..8141 deadline
   frame 1 VERIFY self
   frame 2 SENDER self startRotation(newKey, sessionNonce, T, m, evp…)
   sig[0] P256 newKey, msg = 0x (sig_hash; covers sig[1] since its msg is explicit)
   sig[1] P256 laptop guardian, msg = m
 eth_sendFrameTransaction ────────────────────────────────────────────────────────────────────────────────────────────▶ VERIFY: sig[0]==newKey, sig[1]∈guardians, m pinned, D via keccak
                                                                                                                         body: sha256(D)==m, EVP verify (~63k, 0x100+0x02), pending=newKey, readyAt
 after DELAY: finishRotation (pinned 1-sig path, already in RecoverableP256Account)
```

What each side signs:

| Signer | Over | Why |
| --- | --- | --- |
| New phone, `newKey` | its POPC/POPT (digest of the transcript, `sessionNonce` inside) | ties the phone that was in the room to the key that gets installed |
| New phone, `newKey` | frame sig_hash | proves it holds the key and pins every frame, including the laptop's explicit-msg entry |
| Laptop, its PoP device key | its POPC/POPT | its half of the measurement |
| Laptop, guardian key (same key is fine) | `m = sha256(D)` | "I, an enrolled guardian, saw NEAR for this newKey, this session, this recoveryNonce, before this deadline" |
| Chrome's own EVP key (Chrome-generated, the page can't choose it) | KB-JWT with `nonce = evpNonce` | email control, bound to this session |
| Server | nothing on chain | relay only. The laptop re-checks the verdict before it signs. With sound-bound as the audio stack, the laptop has to trust the server's verdict (no signed transcripts there) |

Gas, modeled from the report's per-item numbers and not run: expiry frame ~4k + self VERIFY ~12-15k + 2 native P-256 13.4k + frame entries. That comes to roughly 30-40k, well under the 100k cap. EVP's ~63k sits in the body frame, where the cap doesn't apply.

## 6. What proximity really proves here

- **Guardian enrollment comes first.** The laptop key has to be registered as a guardian before the phone is lost. A WebCrypto key dies with "clear site data". A passkey survives, but it is really the user's iCloud or Google account, not the laptop.
- **Outside relayer between honest laptop and phone:** reads FAR. The four-arrival bound holds. This is a real guarantee.
- **Malicious new phone** (the attacker in a recovery): it controls its own half of the formula. With any relay device near the laptop during the run, for example the victim's phone on a call with a scammer, it can edit its self-hear and read NEAR (`research/2026-09-25-cheating-participant-and-trust.md`). Neither sound-bound nor the PoP web build stops this. The PoP defense is app attestation, and a browser can't do that. Phone call codecs may cut the 2-18 kHz probe, but the relay test was never run. UNREACHABLE.
- So pitch it as **"the phone that gets the key was in earshot of your laptop when you approved"**, not as an unforgeable distance bound. The gates against takeover are guardian key + EVP email + timelock with owner cancel.
- Two tabs on one machine defeat the premise, and the server doesn't stop it (app README). The contract should at least require the guardian signer to differ from `newKey`.

## 7. What can be tested now on this Mac, no phones

| Test | Command / how | Status |
| --- | --- | --- |
| Signature formats + binding vectors | `node evp-recovery/proximity-sigcheck/sigcheck.mjs` | **done, 9/9** |
| Offline verdicts on the 41 real Mac+Android captures | copy a session dir out, run `research/sound-bound/analysis.py <dir>` with `server/.venv` python. Needs a `soundfile` stand-in (scipy) or `soundfile` installed | done for 4 sessions (above). The other 37 haven't been re-run |
| PopCtx + full PoP flow with fake phones (software keys, real field recordings as background) | `cd server && uv run pytest -q tests/test_popctx.py tests/test_flow_fake_phones.py` | not run here (first-party, should work) |
| Contract: B-style guardian pin + `startRotation` body check | fork `poc-validation-rules/src/RecoverableP256Account.sol`, forge tests with the sigcheck vector (`D`, `m`, WebCrypto `r,s`) | not built |
| Frame tx build/sign with a laptop explicit-msg entry | `poc/clients/frame-lib.cjs` selftest + add an entry with `msg = m` | not run (uses viem/noble from `relayer/node_modules`) |
| Laptop page: WebCrypto keygen into IndexedDB, sign `m`, EVP field with `nonce` | a single Chrome page on localhost. EVP needs the origin trial or `chrome://flags/#email-verification-protocol` | not built. Hand test only (automation failed on the cert interstitial before) |
| Acoustic self-loop on the Mac (its own speaker to its own mic) | sound-bound page, one role | proves the capture plumbing only, not proximity |
| Real proximity, laptop + phone | needs the Android phone | UNREACHABLE today |

## Conflict with account-design.md (read Nov 3, after this note was written)

`account-design.md` picks a different shape. Laptop holds a secp256k1 EOA `L` (test key, page-held) and is the payer, signing the sig hash last (scheme 1). The phone signs an explicit `msg = ctx` once, at chirp time, because the sidecar estimate rewrites body limits and moves the sig hash. EVP sits in a body frame (1a/1c), prefix modeled ~46.5k.

What changes here if that shape wins:
- The "new phone signs raw sig_hash" rule in §2 goes away. The phone signs an explicit 32-byte `ctx`. Its key must still sign raw digests (scheme 2 checks `msg` raw), so a WebCrypto key on the phone is still out unless `ctx` is defined as `sha256(...)` and VERIFY can hash it (Yul).
- The laptop needs no P-256 trick at all: a software secp256k1 key signs the sig hash. That is option A in spirit (script-readable key). Options B/C only matter if we want a non-extractable laptop key.
- Laptop-as-payer also removes my "self-paid" griefing note: junk costs L, not the account.
- The sidecar sum for EVP-in-VERIFY (1b) is confirmed at `79,900 + 20,100 = 100,000` in `poc-native-evp/results/entries.txt`. No room for a 4th native entry, so under 1b the laptop can't add a P-256 entry; a secp256k1 payer entry (2,800) also wouldn't fit unless prefix limits shrink.

The binding in §4 works under both shapes: put `T` and `sessionNonce` into `ctx`.

## Open

- Pick the audio stack for Nov 5. Sound-bound in both browsers is the proven path (audio tested Mac+Android), but nothing is signed and the server decides; the phone then needs a software raw-digest `newKey`. The alternative is the PoP app on the phone plus the PoP web build on the laptop: signed transcripts and commit-reveal, but browser audio was never run.
- Where the guardian set and the email hash come from: account storage or an ENS record. The ENS note owns this. VERIFY can't read ENS unless staked, and chain 1337 has no ENS.
- Mumbai devnet block time and whether 0x02/0x100 work in body frames there (report Q6).
