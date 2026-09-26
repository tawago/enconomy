# App <-> server contract: Noir option A (oaN_s48)

Circuit: `noir/phone` of research/worldid/prototypes/optA-noir, nargo 1.0.0-beta.22, bb 5.0.0-nightly.20260522 (AztecProtocol/barretenberg), UltraHonk `-t evm` (keccak, ZK). 48 kHz only. A 44.1 kHz session is not provable: the app skips it and sends nothing.

## Circuit id

`oaN_s48` (the only one). `meta.circuit` / `circuit` in every request below.

## Files the phone downloads

`GET /v1/zk/keys/<file>`, same route and Range/resume behavior as today (200 or 206, `Content-Range`, `Content-Length`). The app pins size + sha256 and refuses anything else.

| file | what | bytes | sha256 |
|---|---|---|---|
| `oaN_s48.json` | nargo artifact `phone/target/phone.json` (ABI + ACIR) | 14,620,501 | `5499f99eed7aecfd6615ab470cfed7a3345e28954385005d8080b810aaf04f3a` |
| `bn254_g1_2p20.dat` | BN254 CRS, 2^20 uncompressed G1 points (`~/.bb-crs/bn254_g1.dat`, first 64 MiB) | 67,108,864 | `5d0ff516149e0c6644ab16567b914c9d02bf41f872c1129af8436b41d4d82c62` |
| `oaN_s48.vk` | `bb write_vk -t evm` (`~/.enconomy/zk/pinned/vk/vk`) | 1,888 | `769ac93112de4ec2f970d33233108d19124612b9b2ae54b8b531a23ecaa23f06` |

Server-side source files: `~/.enconomy/zk/optA/noir/phone/target/phone.json`, `~/.bb-crs/bn254_g1.dat`, `~/.enconomy/zk/pinned/vk/vk`. The server's `KEY_FILE` regex must allow these three names.

## Hashes inside the signed bytes (changed)

- POPC v2 `[39:71]` and POPT v2 `[177:209]` `rec_root` = oalib Poseidon2 rec tree root (256 leaves over the capture zero-padded to 262,144 samples, 4-ary, depth 4), 32 B big-endian, canonical (< BN254 r).
- POPT v2 `[279:311]` `code_commit` = oalib `code_commitment(c_is, c_qs, c_ip, c_qp)` over the four int8 templates as u8 = v + 128 (self I, self Q, partner I, partner Q, at the signer's rate), 32 B big-endian.
- halfCommit = `hash_n(TAG_HALF=8, [nonce_hi, nonce_lo, attempt, role_b, sr, half (signed, mod r), salt, X_own hi128, X_own lo128, X_partner hi128, X_partner lo128])`. It is the circuit's return value (public input #12).
- `holder_commit` / SBcred3: unchanged.

## Proof upload (phone proved it)

`POST /v1/session/{id}/proof`, signed, multipart:
- part `proof` (file): raw proof, exactly the bytes of `bb prove -t evm -o <dir>` `<dir>/proof` (10,304 B).
- part `public_inputs` (file): exactly `<dir>/public_inputs`, 12 x 32 B big-endian (384 B).
- part `meta`: JSON `{"attempt": int, "circuit": "oaN_s48", "salt": "<decimal>"}`.

Public input order (ABI order, return value last):
`nonce_hi, nonce_lo, attempt, role_b, code_commit, issuer[0..3] (X hi128, X lo128, Y hi128, Y lo128), sr, valid_at, halfCommit`.
The server rebuilds the first 11 from the signed transcript + its issuer key + `valid_at`, checks they equal the uploaded ones, recomputes halfCommit from `salt` and checks #12, then `bb verify -t evm -k oaN_s48.vk -p proof -i public_inputs`.

Reply: as today, `{"status": "verified", "role", "zk": {...}}`, or 4xx `{code, detail}`.

## Delegated proof (server proves)

`POST /v1/session/{id}/proof/delegate`, signed, `Content-Type: application/json`:
```
{"attempt": int, "circuit": "oaN_s48", "salt": "<decimal>", "inputs": { <Noir ABI input map> }}
```
`inputs` = the full `noir/phone` input map, keys = ABI parameter names, the same values the phone would feed its own ACVM:
- `Field` -> decimal string (`"123"`), already reduced mod r (negative values as r - |v|).
- `u8/u16/u32/u64` -> JSON number.
- `bool` -> `true` / `false`.
- arrays -> nested JSON arrays.

Parameters (phone.json ABI order): `nonce_hi, nonce_lo, attempt, role_b, code_commit, issuer[4], sr, valid_at, t[311], sig[64], exp[8], hold[32], csig[64], salt, c_is[12000], c_qs[12000], c_ip[12000], c_qp[12000], xs[13312], chs[13][4][4], leaf_s, xp[13312], chp[13][4][4], leaf_p, ci[193], cq[193], u[193]`. Templates are u8 = int8 + 128; samples are u16 = int16 + 32768. `sig`, `csig` are raw r||s, already low-S. About 400 KB of JSON.

Server: check the public part against the session exactly as for an upload (`inputs.nonce_*`, `attempt`, `role_b`, `code_commit`, `issuer`, `sr`, `valid_at` must equal what it would expect; `inputs.t` must equal the stored signed transcript), write `Prover.toml` (or feed JSON to the ACVM), `nargo execute` + `bb prove -t evm`, then record the result exactly like a phone-uploaded proof (same zk entry, plus `"delegated": true`).

Reply: either synchronous `200 {"status": "verified", "role", "zk"}` / 4xx like the upload, or `202 {"status": "proving"}`. After 202 the app polls `GET /v1/session/{id}/result` every 2 s (up to 3 min) and reads `zk.<role>.status` (so `/result` must carry the `zk` block, `sessions.zk_public(s)`) (`verified` / `rejected` + `reason`). While proving, `zk.<role>` may be `{"status": "proving", ...}`.

The server sees the audio samples of the two opened windows for this proof; the chain and the public never do.

## Server side, as implemented (server/pop/zk.py, sessions.py, main.py)

What the app must match beyond the sections above:

- **Config.** `GET /v1/config` → `zk: {circuits: {"48000": "oaN_s48"}, vk_sha256: {"oaN_s48": "769ac931…"}, keys: "/v1/zk/keys", verifier: {"oaN_s48": bool}, delegate: {"oaN_s48": bool}, n_public: 12}`. `GET /v1/zk/keys` lists only files whose size + sha256 match the pins above (`{circuit, sample_rate, file, url, size, sha256, vk_sha256}`). `GET /v1/zk/keys/<file>` serves them with `X-Pop-Sha256`, Range supported. Server source dir: `POP_ZK_DIR/<file>` if present, else the default paths above.
- **Commit (POPC v2).** The commit response now also carries `code_commit` (64 hex, the Poseidon2 value the transcript's `[279:311]` must hold) and `code_attest` (below). The app may use this value or compute its own; they must be equal or the transcript is rejected (`transcript_mismatch`, "code_commit").
- **Proof upload.** `public_inputs` part is optional. If sent, it is compared with the server's vector first so the error names the field: `public[0|1]` nonce, `[2]` attempt, `[3]` role, `[4]` code_commit, `[5..8]` issuer (`issuer_unknown`), `[9]` sr, `[10]` validAt, `[11]` halfCommit (salt). bb always verifies against the server's own vector. `meta.salt`: decimal or `0x` hex, < 2^248.
- **Delegate.** Always async: `202 {"status": "proving", "role", "zk"}`. Immediate `400` (nothing proved) when a public input in `inputs` differs from the server's (same `public[i]` names, prefixed `inputs`), `inputs.t` ≠ the stored signed transcript, `inputs.salt` ≠ `salt`, or the map isn't exactly the 27 ABI names. Repeating the call while proving returns 202 again; after `verified` it's `409 already_submitted`. `503 zk_unavailable` = no prover on this server. Value encoding: Field as decimal string (`0x` hex also accepted), integers as non-negative JSON numbers, bools as JSON bools. The server runs `zkprove full` (zkmobile/android/zkprove host build: noir 1.0.0-beta.22 ACVM + bb 5.0.0-nightly.20260522 bbapi, `-t evm` bytes), one job at a time, ~13 s on the M2; the Prover.toml lives in a 0700 temp dir only for the run.
- **zk block** (`/result` → `zk`, also in `result.json`):
  ```
  {"valid_at", "status": "none|partial|proving|verified|rejected", "circuit": "oaN_s48", "vk_sha256",
   "code_attest": {"A": {...}, "B": {...}} | null,      # from commit time
   "A"|"B": null | {"attempt", "circuit", "prover": "phone|server", "delegated": bool, "at_ms", "status",
                    "reason", "detail", "proof_sha256", "proof_bytes", "half_commit", "prove_ms" (server only),
                    "public_inputs": ["0x<64 hex>" x 12], "files": {"proof", "public_inputs"}, "code_attest"}}
  ```
  Reasons on `rejected`: `proof_invalid` (bb said no), `transcript_mismatch`, `issuer_unknown`, `credential_expired`, `circuit_unknown`, `witness_failed` (delegate: the ACVM rejected the input map), `zk_unavailable` (delegate: server-side failure, retry). A rejected entry may be replaced by a new upload / delegate.

## Code attestation (server → verifier)

The templates are private; the proof exposes only `code_commit` (public #5). The issuer key vouches for it:
```
msg = "POPCC1" (6 B) || session_nonce (32 B) || attempt (u8) || role ('A'|'B', 1 B) || code_commit (32 B BE)   = 72 B
sig = ECDSA P-256 over SHA-256(msg), issuer key (= the SBcred3 issuer, public #6..9), raw r||s, low-S
code_attest = {"code_commit": hex, "msg_hex", "sig_hex", "issuer_pubkey": "04…", "format": "POPCC1"}
```
Per verified proof, `zk.<role>.code_attest` signs exactly that proof's public input #5. A verifier checks: sig over msg under the issuer key in public #6..9; msg nonce = public #1 || #2 (16 B each), attempt = #3, role = #4 (0 → 'A', 1 → 'B'), code_commit = #5.

## Onchain bridge (laptop, reads the server's files)

- `result.json` at `$POP_DATA_DIR/sessions/<session_id>/result.json` (default `POP_DATA_DIR` = `server/data`).
- Per verified role: `zk.<role>.files.proof` and `.public_inputs` are paths **relative to `POP_DATA_DIR`**:
  `sessions/<sid>/proof_<role>_<attempt>.bin` (raw `bb prove -t evm` proof, 10,304 B) and
  `sessions/<sid>/public_inputs_<role>_<attempt>.bin` (12 x 32 B big-endian).
- `zk.<role>.public_inputs` = the same 12 values as `0x` hex strings (`bytes32[]` order for `PhoneVerifier.verify(bytes proof, bytes32[] publicInputs)`).
- Circuit / vk: `oaN_s48`, vk sha256 `769ac93112de4ec2f970d33233108d19124612b9b2ae54b8b531a23ecaa23f06` (`~/.enconomy/zk/pinned/vk/vk`, matches `~/.enconomy/zk/pinned/PhoneVerifier.sol`). Checked: both stored fixture proofs pass `bb verify -t evm` with that vk.
- The pair proof (`noir/pair`) is not produced by the server yet.
