# enconomy integration surface for a World ID + onchain product

Date: 2026-09-26. Scope: what the running PoP system produces after NEAR, what the human/output adapters decided, what is built vs only designed, and what an `onchain` output adapter needs. Read against HEAD `ba81f84` plus the working tree (another workflow is editing `app/` and `server/` right now; line refs may drift).

Tags: **V(src)** = verified in that file / command. **U** = unverified or inferred.

---

## 0. One-paragraph answer

After NEAR the server holds a JSON result record: two 269 B (v1) or 311 B (v2) transcripts, each ECDSA-P-256-signed by an attested device key, the two signed commits, both device pubkeys, verdict, `flight_cm`, `t0_ms`. **The record itself is not signed by anyone**, is only readable by the two member devices (signed GET), and carries no World ID data, no `pair_tag`, no policy. Optional per-role option-A proofs (Spartan2/Hyrax over the P-256 field, ~1.6 MB each) are verified server-side only; the pair proof is not made. World ID is **designed** (`docs/pop-human-adapters.md`) and **spiked** separately (`~/dev/worldid-spike`, real PoH proofs verified against Portal v4 with per-session unregistered actions), but **zero World ID code is in `server/` or `app/`**. Useful discovery: the **P-256 precompile (RIP-7212, address `0x…0100`) is live on World Chain mainnet (480) and Sepolia (4801)**, so a contract can check the device signatures and the SBcred3 issuer signature directly, and recompute the verdict from the two transcripts. A PoP session needs both phones online and co-located at the same moment; the audio core is ~5 s, a whole session with pairing and two World ID hops is realistically 1–2 min.

---

## 1. Verified facts

### 1.1 Artifacts after a NEAR verdict

**Result record** `GET /v1/session/{id}/result`, also `server/data/sessions/{id}/result.json`. Built in `Sessions._record`. V(`server/pop/sessions.py` `_record`, ~L318–345)

```jsonc
{
  "proto": "pop-v1",
  "session_id": "hex32",            // 16 random bytes, server-made
  "session_nonce": "hex32",         // 32 random bytes, server-made; shown to phones only after both confirm
  "attempt": 0|1,                   // final attempt
  "verdict": "NEAR"|"NOT_NEAR", "reason": null|"<code>", "user_text": null|"...",
  "flight_cm": 26.1,                // float, rounded to 0.01
  "t0_ms": 1790000000000,           // server clock
  "created_at": "iso", "finished_at": "iso",
  "devices": { "A"|"B": { "device_id", "pubkey": "hex65 SEC1", "display_name", "model", "attested": bool,
                         "security_level", "sample_rate", "half", "popt": 1|2 } },
  "transcripts": { "A"|"B": { "transcript_b64", "sig_b64", "sha256": "hex(sha256(transcript))" } },
  "commits":     { "A"|"B": { "commit_b64", "sig_b64" } },
  "zk": { "valid_at": t0_ms//1000, "status": "none|partial|verified|rejected",
          "A"|"B": null | { "attempt", "circuit", "proof_sha256", "proof_bytes", "at_ms", "status", "reason",
                            "detail", "half_commit" } },   // salt stripped
  "attempts": [ {"attempt","outcome","reason","by", ("verdict","flight_cm")} ]
}
```

- **Who signs what.** V(`docs/pop-contract.md` §7, `server/pop/verdict.py`)
  - Each transcript: the device key, ECDSA P-256 over `sha256(transcript)`, raw `r‖s` 64 B, no low-s rule.
  - Each commit (71 B `POPC`): same device key.
  - Result record: **nobody**. No server signature, no attester key. V(grep: `_record` returns a dict; `main.py` has no signing on `/result`).
  - SBcred3 credential (optional, at enroll): the server's issuer key, P-256, over `sha256(cred)`. V(`server/pop/issuer.py`)
- **Access.** `/result` needs the §2.3 signed headers and session membership (`sessions.member` → 403 `not_member`). No public/read-only view, no webhook, no push. Only long-poll on `GET /v1/session/{id}`. V(`server/pop/main.py` `result()`, `get_session()`)
- **Offline check.** `pop.verdict.verify_record(rec)` re-runs every signature, commit, crossed-key and flight check from the record alone. It trusts the listed pubkeys (no attestation data in the record) and skips v2 `code_commit` (needs the server seed). V(`server/pop/verdict.py` L162–181)

**Transcript POPT v1, 269 B** (big-endian, fixed offsets). V(`docs/pop-contract.md` §7.1)

| Off | Len | Field |
|---|---|---|
| 0 | 4 | `"POPT"` |
| 4 | 1 | version `0x01` |
| 5 | 1 | role `'A'`/`'B'` |
| 6 | 1 | attempt |
| 7 | 32 | session_nonce |
| 39 | 65 | pk_self (SEC1 `04‖X‖Y`) |
| 104 | 65 | pk_partner |
| 169 | 4 | sample_rate u32 |
| 173 | 4 | half i32 (frames) |
| 177 | 32 | rec_sha256 |
| 209 | 8 | play_frame_position |
| 217 | 8 | play_nano_time |
| 225 | 8 | rec_frame0_nano_time |
| 233 | 4 | self_os_delta i32 |
| 237 | 32 | commit_hash = sha256(POPC) |

**POPT v2, 311 B**: same offsets up to 269, `rec_sha256` → `rec_root` (Poseidon7 Merkle root, P-256 field), then `a_self` u32 @269, `p_partner` u32 @273, `delta` u16 @277, `code_commit` 32 @279. Opt-in per phone at arm (`"popt": 2`). V(`docs/pop-transcript-v2.md` §1, `server/README.md` "POPT v2")

**Verdict math** (all integers, easy onchain). V(`server/pop/verdict.py` `flight_exact`, `decide`; contract §8.1)
- Pair checks: one A one B; same nonce and attempt; `A.pk_partner == B.pk_self`, `B.pk_partner == A.pk_self`, keys differ; `|self_os_delta| ≤ 50 ms·sr/1000` each.
- `flight_cm = 34300/2 · (half_A/sr_A − half_B/sr_B)`. NEAR iff `−20 < flight < 60`. Exact `Fraction`; the pair circuit uses `c·N ≤ −40·S`, `c·N ≥ 120·S`.

**Device keys.** V(contract §2)
- P-256, Android Keystore/StrongBox or iOS Secure Enclave. `device_id = hex(sha256(pub65)[:16])`.
- Attestation (Android key chain / iOS App Attest) is checked at enroll only; `attested` bool is stored. Root not pinned to Google, no Play Integrity, no revocation. `POP_ALLOW_UNATTESTED=1` accepts no attestation. V(`server/README.md` "Attestation")
- **Keys are per device, stable across sessions.** Anything that publishes them makes a device's meetings linkable.

**SBcred3.** V(`server/pop/issuer.py`, `server/README.md` "SBcred3")
- `cred = "SBcred3" ‖ X(32) ‖ Y(32) ‖ expiry u64 BE ‖ holder_commit(32)` = 111 B; `sig = ECDSA-P256(issuer, sha256(cred))`.
- Issued only if the app sends `holder_commit` at enroll. TTL 30 days (`POP_CRED_TTL_S`).
- Issuer pubkey published at `GET /v1/config` → `issuer {alg:"ES256", pubkey, pub_x, pub_y, cred_format, cred_ttl_s}`.
- Meaning: "this key enrolled here with passing attestation". Not a human, not unique.

**ZK public inputs** (per phone, `oa2t_s48` / `oa2t_s44`). V(`server/pop/zk.py` docstring + `public_vector`)
```
public = [halfCommit, nonceHi, nonceLo, attempt, roleB, codeHi, codeLo, cIs[L], cQs[L], cIp[L], cQp[L],
          issuerX, issuerY, sr, validAt]          length 1 + 6 + 4L + 4, L = 12000 (48k) / 11025 (44.1k)
halfCommit = Poseidon7.sponge16(8, [nonceHi, nonceLo, attempt, roleB, sr, half mod p, salt, X_self, X_partner])
```
- Field = P-256 base field. Prover: Spartan2 / Hyrax on T-256 (`popprover`). Proof ~1.65 MB (48k), 1.52 MB (44.1k). vk pins s48 `488e44c9…5a3d`, s44 `7c5cb18c…e4e0`. V(`server/pop/zk.py` `VK_PINS`, `docs/pop-prover.md`)
- Public vector is ~48k values (4L int8 templates). **Not EVM-verifiable** in any practical sense (no Spartan/Hyrax-on-T-256 EVM verifier, MB-scale proof). U for "no verifier exists", but structurally obvious.
- Pair circuit `oa2t_pair` public = `[nonceHi, nonceLo, attempt, commitA, commitB, srA, srB]`; not produced by server or app yet. V(`research/sound-bound/spikes/zk/optionA-v2/circuits/main/oa2t_pair.circom` L45, `server/README.md` "The pair proof (oa2t_pair) is not made here yet")
- The server fixes every public value itself (it knows the seed/codes and salt), so today's ZK proves "the phone's arrival rule ran on its committed recording" to **the server**, not to a third party. A third party can't re-derive the code templates without the seed. V(`zk.py` docstring; `popzk.py` needs `code_seed_hex`)

**pair_tag / nullifiers.**
- Designed: `pair_tag = sha256("pop-pair-v1" ‖ min(nA, nB) ‖ max(nA, nB))`, each as 32 B BE. V(`docs/pop-human-adapters.md` §1)
- Implemented only in the spike verifier `research/sound-bound/spikes/zk/verifier/popzk.py` (`--nullifiers NA NB`). **Not in `server/`.** V(grep `pair_tag|nullifier` over `server/` and `app/`: no hits)

### 1.2 Human-adapter design: what is already decided

V(`docs/pop-human-adapters.md`)

- Layers: human adapter (per role) → presence core (unchanged) → output adapter (`api | ens | onchain`).
- `HumanAdapter` protocol: `kind`, `strength` (0 devices, 1 weak, 2 unique human), `context(session_id, role)`, `verify(session_id, role, payload) -> HumanResult{kind, nullifier, strength, display, evidence}`.
- Rules: policy fixed at session create (`{adapter, min_strength}`); **both roles pass the human step before arm** (iOS app switch likely kills audio); `nullifier_A != nullifier_B` else `same_human`; `UNIQUE(kind, nullifier)`; adapter proves humanness, never location.
- `worldid` adapter:
  - action `"pop:" + session_id` (fresh nullifier per session → meetings unlinkable via World ID);
  - signal `0x ‖ abi.encodePacked(bytes32 session_nonce, bytes1 role)` (nonce, not session id; no device key);
  - verify via Portal v4, check `environment`, `action`, `signal_hash == keccak(signal) >> 8`, nullifier unused, nullifiers differ.
- `ens` (strength 1) and `none` (strength 0) adapters are specified.
- Output `onchain`: "an attestation (pair_tag, verdict, adapter kind, time bucket) for contracts to gate on". No format, chain, signer, or contract chosen.
- API additions planned: `POST /v1/session` takes `policy`; new signed `GET /v1/session/{id}/human/context` and `POST /v1/session/{id}/human`; record adds `human {A, B}` and `pair_tag`; errors `human_missing | human_invalid | same_human | human_replay`.
- ZK: composition at the verifier; World ID proof and keccak never enter our circuits; drop the key-derived pairTag.

### 1.3 Implemented vs designed

| Piece | State | Source |
|---|---|---|
| Enroll, request auth, pairing (QR/NFC), arm/commit/transcript, verdict, retry, result record | implemented, tested with fake phones; real phones untested at time of memory note | V(`server/README.md` tests table; memory `pop-app-build-status`) |
| POPT v2, rec_root, int8 codes | implemented server + app, opt-in | V(`server/README.md`, app `dsp/Popt2Rule.kt`, `zk/RecTree.kt`) |
| SBcred3 issuance | implemented (server), app side in progress (untracked `zk/Holder.kt`, `HolderStore.kt`) | V(`issuer.py`, git status) |
| Per-phone option-A proof upload + verify | implemented server (`POST /v1/session/{sid}/proof`); app prover integration in progress by the other workflow | V(`main.py`, `zk.py`, untracked `app/.../zk/ProofRunner.kt`) |
| Pair proof `oa2t_pair` | circuit exists in spike; not produced or verified by server/app | V(`server/README.md`) |
| Human adapters (World ID / ENS / none), policy, `/human` endpoints | **design only** | V(grep `worldid|idkit|nullifier|pair_tag` in `server/`, `app/`: none) |
| pair_tag | spike verifier only | V(`popzk.py`) |
| Output adapters `ens`, `onchain` | **design only**, one table row each | V(`pop-human-adapters.md` §3) |
| World ID flow itself | working spike outside this repo: `~/dev/worldid-spike` (FastAPI `/rp-context`, `/verify` → Portal v4; KMP Android app with `com.worldcoin:idkit:4.0.7`; iOS not included) | V(`~/dev/worldid-spike/backend/README.md`, `app/README.md`) |

**World ID spike evidence** V(`~/dev/worldid-spike/backend/logs/backend.log` 2026-09-25 00:43–00:45 JST):
- Unregistered dynamic actions (`spike-<ms>`) verified `200 success:true`, `environment: production`, `protocol_version: 4.0`, `identifier: proof_of_human`, `issuer_schema_id: 1`.
- Portal returns the nullifier as **0x-hex** (e.g. `0x162aa2ce…8a53`), not decimal.
- The proof payload has `proof: [5 decimal strings]` (Groth16 compressed + Merkle root per the brief), `expires_at_min`, `signal_hash`, and an `integrity_bundle` (Android Keystore sig + JWT from `attestation.worldcoin.org`, `aud = rp_id`).
- Time from `/rp-context` to `/verify`: 27 s and 12 s in the two successful runs (one human, same phone, World App already set up).
- App ID `app_957c…9a7d`, RP ID `rp_1469245f4f78143c` (spike's portal app).

### 1.4 HTTP API today

V(`server/pop/main.py`)

| Method | Path | Auth |
|---|---|---|
| GET | `/health`, `/v1/health`, `/v1/time`, `/v1/config` | none |
| GET | `/v1/zk/keys`, `/v1/zk/keys/{circuit}.pk.zst` (Range) | none |
| GET | `/v1/enroll/nonce` | none |
| POST | `/v1/enroll` (android chain / ios app_attest, optional `holder_commit` → SBcred3) | none |
| POST | `/v1/session` → `{session_id, join_token, expires_at_ms, invite_b64url, invite_qr}` | device |
| POST | `/v1/session/{sid}/join` | device |
| GET | `/v1/session/{sid}?after=&timeout_s=` (long-poll ≤ 25 s) | member |
| POST | `/v1/session/{sid}/confirm`, `/arm`, `/commit`, `/transcript`, `/fail`, `/abort` | member |
| POST | `/v1/session/{sid}/recording` (multipart WAV) | member |
| POST | `/v1/session/{sid}/proof` (multipart proof + `{attempt, circuit, salt}`) | member |
| GET | `/v1/session/{sid}/result` | member |

Auth message: `pop-req-v1\n<METHOD>\n<PATH?query>\n<sha256hex(body)>\n<ts_ms>`, headers `X-Pop-Device`, `X-Pop-Ts`, `X-Pop-Sig` (base64 `r‖s`), ±60 s, in-memory replay cache. V(contract §2.3)

Storage: SQLite (`POP_DB`), session doc as JSON, files under `data/sessions/<id>/`. No chain client, no web3 dependency. V(`server/pop/store.py` exists; `pyproject.toml` not re-checked, U for "no web3 dep")

### 1.5 Timing and liveness

V(`server/pop/constants.py`, `sessions.py`, contract §3–§4, §9.1)

| Step | Bound / typical |
|---|---|
| Join token TTL | 120 s |
| Whole session max age | 600 s, then `aborted/timeout` |
| Clock sync | 10 × `/v1/time`, refuse if min rtt > 300 ms |
| Both armed → `t0` | `t0 = now + 3000 ms` (`T0_DELAY_MS`) |
| Recording | `t0 − 1 s` … `t0 + 2 s`; A plays at 0, B at 0.95 s; capture 2.5 s |
| Commit allowed | from `t0 + 1.2 s` |
| Transcript deadline | `t0 + 20 s`, else `timeout` → retry |
| Retry | once (`MAX_ATTEMPTS = 2`), full re-arm, new t0 |
| World ID rp_context TTL | 300 s (brief §1, and spike `expires_at − created_at = 300`) |
| World ID hop, per person | 12–27 s observed in the spike (above) |
| Option-A proof (after NEAR) | key 11.7 MB download once; M2: ~1 s key load, 0.4 s witness, 2.2–3.7 s prove, ~1.9 GB peak; phone untested (`docs/pop-prover.md`) |

- **Both phones must be online to the same server at the same time.** Pairing, confirm, arm and t0 go through the server; the commit-then-reveal step needs a server round trip mid-run (partner code released only after commit). There is no offline or phone-to-phone mode. V(contract §5.2, §9)
- **Both must be physically co-located at t0**, obviously.
- Proof upload is asynchronous after NEAR, no deadline in code other than credential expiry ≥ `validAt`. V(`sessions.zk_expected`)
- Realistic end to end, no World ID: tap-to-NEAR ~20–40 s (pairing + confirm + ~5 s audio + DSP). With two sequential World ID hops before arm: ~1–2 min. U (only the parts above are measured).

### 1.6 Onchain primitives checked by command

- **RIP-7212 P256VERIFY precompile at `0x0000000000000000000000000000000000000100` returns `1` for a valid P-256 signature on World Chain mainnet (chainId `0x1e0` = 480) and World Chain Sepolia (`0x12c1` = 4801).** V(command: `eth_call` with `sha256(m)‖r‖s‖x‖y` via `https://worldchain-{mainnet,sepolia}.g.alchemy.com/public`; script at scratchpad `p256call.py`)
  - Consequence: a contract can verify POPT device signatures (they sign `sha256(transcript)`, exactly the precompile's input) and the SBcred3 issuer signature without any server-side re-signing.
- WorldIDVerifier addresses from the brief: `0x00000000009E00F9FE82CfeeBB4556686da094d7` has code on World Chain mainnet (87 B, proxy-sized) and **none on World Chain Sepolia**; `0x703a6316c975DEabF30b637c155edD53e24657DB` (brief calls it "staging") has code on mainnet (141 B), **none on Sepolia**. V(command: `eth_getCode`). Where staging lives on testnets is not established here (U; another track owns it).

---

## 2. Unverified / conflicting

1. **Nullifier encoding.** Adapter doc says "decimal string, NUMERIC(78,0)"; Portal v4 returns 0x-hex. `popzk.py` accepts both. Pick one canonical form (32 B BE) before hashing into `pair_tag`. V(conflict: doc vs spike log)
2. **Signal choice.** Adapter doc: `(bytes32 session_nonce, bytes1 role)`. IDKit brief §5: `(sid, pk_i)`. The task prompt paraphrased it as `sid + role`. The doc's version is the decided one. The nonce is only shown after both confirm, so the World ID hop must sit between confirm and arm. Fine with the "before audio" rule, but it makes the ordering strict: pair → confirm → World ID ×2 → arm.
3. **"Per-session actions work unregistered."** Confirmed in production for one human with `spike-<ms>` actions. Not tested: action string `pop:<32 hex>` (colon, length), two different humans on one action, same human twice on one action (should fail at the World App's nullifier pool, per brief — U).
4. **`docs/pop-contract.md`** is staged as deleted in the git index (`D `) while the file on disk equals HEAD. Someone intends to remove or move it. Treat HEAD as authoritative for now. V(`git status`, `diff`)
5. **Contract §8.4 says "This record … is what ZK/onchain consumes later."** But the record is unsigned and member-only, so as-is nothing onchain can consume it without trusting whoever relays it.
6. **v2 `code_commit`** can't be checked by a third party (needs seed). So a third party verifying transcripts trusts the server for "codes were secret and released only after commit" in both v1 and v2.
7. **Pair proof** exists as a circuit only; the adapter doc's "composition at the verifier" is realised only in the spike `popzk.py`, which also needs the code seed.
8. **Real-phone status.** Memory says phones untested as of the last note; the other workflow may have changed that. U.
9. **Onchain World ID verify call shape** (`WorldIDVerifier.verify(...)` args for v4, 15 public signals) is from the brief, not re-read here. U; belongs to the World ID track.

---

## 3. What an `output adapter: onchain` needs

Nothing exists. Three shapes, in order of trust in the server:

**(a) Server attestation (simplest).**
- New attester key. Either secp256k1 for EIP-712 / EAS, or reuse P-256 and check with the `0x100` precompile.
- Attestation payload (fixed): `pair_tag`, `session_nonce`, `verdict`, `t0_bucket`, `adapter_kind`, `min_strength`, maybe `flight_bucket`. Plus whatever the product needs to bind (Safe address + txHash; or pool note commitment).
- Contract: `ecrecover` / P256 check against a pinned attester, `mapping(bytes32 pair_tag => bool used)`.
- Trust: the server (it already holds the seed, so it can lie about codes anyway).

**(b) Contract re-checks the presence core (discovered option).**
- Calldata: two transcripts (269/311 B), two `r‖s`, two SBcred3 (111 B) + issuer sigs. Commits not needed (commit_hash is inside the signed transcript; only the server can match it to the reveal order).
- Contract checks: both SBcred3 signed by pinned issuer (P256), `cred.pubkey == transcript.pk_self`, both transcript sigs (P256), roles, same nonce/attempt, crossed keys, `self_os_delta` bound, integer flight, NEAR.
- Add World ID: two `WorldIDVerifier.verify` calls with `signal = abi.encodePacked(nonce, role)` recomputed from the transcripts, `nullifierA != nullifierB`, `pair_tag` stored as used.
- Remaining server trust: SBcred3 issuance (= attestation at enroll), nonce freshness, code secrecy and reveal order. Nothing else.
- Cost: 4 P256 calls (~3,450 gas each under RIP-7212; U on World Chain's exact pricing) + 2 World ID verifies + ~1 KB calldata. Cheap on World Chain.
- Privacy cost: puts both **stable device pubkeys**, `flight`, timestamps and the nonce onchain. Every meeting of a device becomes linkable. Fine for a Safe (owners are public anyway); bad for a privacy pool.
- Server change needed: none for the core; `result` must be fetchable by the relayer (today member-only; the phone can relay it itself, since members can read it).

**(c) ZK onchain.** The option-A proofs are Spartan/Hyrax over the P-256 field, ~1.6 MB, with ~48k public values including the secret-derived templates. Not EVM-verifiable. A Groth16/BN254 wrapper would be a new circuit and a new project. Out of scope for the hackathon. U (no attempt made).

Server/API additions for any of (a)/(b):
- `policy` on `POST /v1/session`; `/human/context` and `/human` endpoints; `human{A,B}` and `pair_tag` in the record (all per adapter doc §4).
- A product binding field set at session create, e.g. `purpose: {kind: "safe", safe, chainId, safeTxHash}` or `{kind: "pool", commitment}`. It must be inside something signed: either in the World ID signal, or derived into the nonce (e.g. `nonce = keccak(random ‖ purpose)`), or a new transcript field. **Today nothing ties a PoP session to a transaction.** This is the single biggest missing link.
- A public, unauthenticated or bearer-token read of the (redacted) record or of the attestation, so a relayer/dApp can fetch it. Today only the two phones can.
- If (a): attester key env (`POP_ATTESTER_KEY`), `GET /v1/session/{id}/attestation` returning `{payload, sig}`, attester pubkey/address in `/v1/config`.
- Optional: chain submitter (server pays gas) vs phone/dApp submits. The app has no wallet today.

---

## 4. Implications for SAFE (Safe multisig + presence module/guard)

- **Fits the core well.** The core proves exactly "two enrolled devices together at t0". A Safe guard/module needs "owners X and Y were together, recently, for this tx".
- **Owner ↔ device binding is missing.** Device keys are P-256 and not wallet keys. Needs a registration step: each owner signs (EOA / passkey) `bind(device_pubkey)` into the module. With option (b) the module can then check `transcript.pk_self ∈ ownerDevices[owner]` via the P256 precompile. Owners are public in a Safe, so exposing device pubkeys costs little.
- **Tx binding is missing.** The PoP nonce is random and server-made. The design must carry `safeTxHash` into something signed per session (see §3). Cheapest without touching the transcript layout: make `session_nonce = keccak256(serverRandom ‖ safeTxHash)` and have the module recompute it from a disclosed `serverRandom`, or put `safeTxHash` into the World ID signal. Both need a server change at session create.
- **World ID role is awkward.** Per-session actions give fresh, unlinkable nullifiers, so World ID proves "two distinct humans", not "these two are the Safe's owners". For a Safe the owner keys already identify the parties; World ID adds "not one person with two phones" (and `nullifierA != nullifierB`). A stable per-owner World ID binding (fixed action per Safe) collides with the "one proof per (rp, action)" rule in the brief. Open.
- **n-of-m.** PoP is strictly pairwise (roles A/B, two slots). 3+ owners needs several pairwise sessions (star around one device, or a chain), each binding the same safeTxHash. Timing: 10-min session cap, retry once.
- Both owners must be online and together when approving. That is the product claim, not a bug.

## 5. Implications for POOL (confidential payment gated by presence)

- **Privacy clash.** Everything the core emits is linkable: stable device pubkeys, display names, models, `t0_ms`, flight, IPs at the server. Option (b) onchain would publish the payer–payee meeting. A pool must take only an unlinkable token onchain.
- **Workable shape (U, needs design):** after NEAR + two World ID proofs, the server (trusted, as it already is) adds a commitment to a "met" set, or signs a blinded/committed ticket; the payer's private transfer proof shows membership. That means a new BN254 circuit (Railgun-style) plus a server-held Merkle tree or signer. The existing Spartan proofs can't be reused onchain.
- **pair_tag** from per-session nullifiers is already unlinkable across sessions and not computable by the issuer. It is the natural public "meeting id" / nullifier for spending a presence ticket once.
- **Binding the payment** (amount/recipient note) to the session has the same missing link as SAFE, but it must stay hidden: bind a commitment, not the payee address.
- **Timing:** payer and payee both online at the meeting; the transfer itself can happen later if the ticket carries an expiry (`t0_bucket`).
- Much more new crypto than SAFE. SAFE can reuse the discovered P256-precompile path nearly as is.

---

## 6. Open questions

1. Where does the tx/purpose binding go: nonce derivation, World ID signal, or a new transcript field (would change 269/311 B layouts that the other workflow and the circuits depend on)?
2. Attester for the onchain adapter: new secp256k1 key (EIP-712/EAS) or reuse the P-256 issuer with the precompile? Is EAS deployed on World Chain (U)?
3. Is the contract-side re-check (option b) acceptable for SAFE given it leaks device pubkeys and flight onchain?
4. World ID for SAFE: prove "distinct humans" only (per-session action) or "the same human who registered as owner" (needs a stable binding; conflicts with one-proof-per-action)?
5. Who submits onchain: phone (needs a wallet in the KMP app), dApp in a browser, or server relayer?
6. Which chain: World Chain mainnet has WorldIDVerifier; Sepolia doesn't at the brief's addresses. Demo on mainnet with real gas, or find the testnet deployment?
7. Does `pop:<32hex>` pass as an action exactly as `spike-<ms>` did? Two humans on one action verified end to end?
8. Should `/result` get a public redacted view (by token) for relayers, or does the phone relay it?
9. n-of-m for SAFE: pairwise sessions with shared purpose, or extend roles beyond A/B (large change to the core)?
10. Is `SELF_OS_TOL_MS = 50` acceptable for a money-moving gate? Every 1 ms of tolerance ≈ 17 cm of fake closeness for a cheating phone (`research/2026-09-25-cheating-participant-and-trust.md`). With 50 ms the single-cheater bound is weak; a genuine attested app is the real defense.

## 7. Risks

- Onchain claims rest on server trust (seed, reveal order, attestation) no matter the shape; say so in the pitch.
- Attestation is hackathon-grade (no Google root pin, no Play Integrity, unattested allowed by env flag). An onchain gate inherits that.
- Record is unsigned today; anything built on "the server said NEAR" needs a new signer first.
- Stable device keys leak linkage if published (fatal for POOL, fine for SAFE).
- World ID hop + audio on iOS: app switch vs audio session untested; order must be confirm → World ID ×2 → arm.
- Other workflow is changing `app/` and `server/`; endpoint shapes above may move.
