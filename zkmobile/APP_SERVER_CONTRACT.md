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
