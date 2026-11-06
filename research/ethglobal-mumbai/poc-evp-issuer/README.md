# PoC: on-chain EVP token verify gas

Question: can a contract check an all-ES256 EVP token (issuer EVT + browser KB-JWT) inside a 100k gas VERIFY budget?

Answer: yes for one token. About 63k gas of execution, with the P-256 precompile at 0x100. Two tokens (the multi-member rule) do not fit.

Update 2026-11-02: gas fits, but the live sidecar rejects it inside VERIFY anyway. `EvpVerifier` STATICCALLs 0x100 (P-256) and 0x02 (sha256), and with live `precompiles: []` the sidecar's CODE_ACCESS rule rejects both before gas matters (`../notes/precompile-rule.md`). It works unchanged in an execution frame, a normal tx, or a sidecar with `precompiles` set (our hot spare).

Built 2026-11-02. Local only. No transactions sent, no real keys used.

## Files

- `mint.mjs`: Node 24, no npm deps. Makes fresh P-256 test keys (in `keys/`, gitignored), mints `EVT~KB-JWT`, writes `test/Fixture.sol` and `sample-token.txt`. Uses `cast keccak` for keccak256.
- `src/EvpVerifier.sol`: the verifier.
- `test/EvpVerifier.t.sol`: gas tests and 10 negative tests: wrong newKey, KB signed by a non-cnf key, other email, other aud, other issuer, stale iat, tampered EVT, tampered KB, KB-JWT reused with a different EVT (sd_hash), bad hint.
- `test/Prof.t.sol`: micro-benchmarks (decoder slope, sha256, copy). The helpers are `internal`, not `private`, only so this harness can inherit them. Nothing extra is external.
- `lib/forge-std`: copied from forge-std v1.11.0 (8e40513), gitignored.

Run:

```
node mint.mjs                 # new keys + fixture each run
forge test -vv
```

## Token shape (from the spec)

Per `../notes/evp.md` and draft-hardt-email-verification-02:

- EVT header `{"alg":"ES256","typ":"evt+jwt","kid":"pop-1"}`.
- EVT payload `iss, iat, cnf.jwk {kty EC, crv P-256, x, y}, email, email_verified: true`.
- Issuance token = `EVT~` (SD-JWT, zero disclosures).
- KB-JWT header `{"alg":"ES256","typ":"kb+jwt"}`, payload `aud, nonce, iat, sd_hash`.
- `sd_hash = b64url(SHA-256("EVT~"))`, tilde included.
- Our choices: `newKey` = new owner P-256 pubkey `x||y` (64 bytes). `nonce = "0x" + lowercase hex keccak256(newKey)`. The RP page sets this string as the `nonce` attribute.
- Sample token is 861 bytes.

## What the contract checks

Input: the exact string Chrome gives the page, one packed `uint256` of 15 byte offsets, and `newKey`.

1. Offset hints point at the dots and the `~`. Each is checked.
2. EVT header pinned by keccak (pins alg, typ, kid).
3. Issuer ES256 signature: sha256 of `b64h.b64p`, call 0x100 with the pinned issuer key. Success means 32 bytes equal to 1.
4. EVT payload decoded on-chain (base64url). Then:
   - `"email":"<email>"`: keccak of the bytes vs stored hash, plus the closing quote.
   - `"email_verified":true`.
   - `"iat":` is within `[now - maxAge, now + 60]`.
   - `"x":"…"`, `"y":"…"`: decoded to get the browser key (the cnf binding).
5. KB-JWT ES256 signature, checked with that cnf key. This step is what binds the KB-JWT to the EVT.
6. KB payload:
   - `"aud":"<origin>"`: keccak vs stored.
   - `"nonce":"0x…"` must equal hex(keccak(newKey)).
   - `"iat":` freshness.
   - `"sd_hash":"…"` must equal sha256 of `EVT~`.

The contract never scans JSON. Each claim is a fixed-literal compare at a caller-given offset. A wrong hint reverts.

Why offsets are safe enough here:

- The issuer signs the EVT JSON. The browser key signs the KB JSON.
- Inside a JSON string a quote is always escaped (`\"`). So the pattern `"email":"` cannot be faked inside another value, such as an email local-part.
- The KB-JWT is written by whoever holds the browser key. That is the person who got the EVT, so a forged KB claim gains nothing.

Not checked (PoC):

- `iss`: the pinned issuer key stands in for it.
- KB header `typ`: Chrome's exact header bytes are unknown, so it is not pinned.
- Duplicate JSON keys: our issuer never emits them.
- Nesting: we assume `"x":"` only appears under `cnf.jwk`. That holds for our own issuer.
- Low-s: EIP-7951 does not require it, so signatures are malleable.
- Replay: `verify` is a `view` and keeps no state. The account must act on it: rotating to `newKey` makes a replay a no-op, because the nonce commits to that key. Any other use needs a used-nonce record.
- Non-canonical base64 tail bits.
- Email case: Chrome 156+ echoes the email byte-exact. Store the hash of the exact string the user will type.

## Gas (forge 1.4.3, solc 0.8.30, via-ir, optimizer runs 1,000,000, evm osaka)

| Measure | Gas |
| --- | --- |
| `verify` execution, warm call (closest to a VERIFY frame's own cost) | **63,111** |
| `verify` execution, cold call (+2,600 account access) | 67,728 |
| Calldata, 1,092 bytes (EIP-2028) | 15,804 |
| Full standalone tx: 21,000 + calldata + warm exec (a top-level tx has `to` warm and no CALL opcode) | ~99,900 (borderline) |
| EIP-7623 floor for this calldata | 60,510 (below the standard cost, so it does not bind) |
| One 0x100 call from Solidity, warm | 7,243 (6,900 precompile + call/abi overhead) |
| base64url decoder slope | ~775 gas per 32 chars (31 chunks per token, ~24k) |

Sensitivity: each extra payload char costs ~24 gas (775 per 32). Longer `iss`, email or extra Chrome KB claims raise the 63k a little. It is not a fixed number.

Rough split of the 63k: base64 decode ~24k, two P-256 ~14.5k, the rest ~24k (memory, three sha256, keccaks, digit parsing, hint checks).

Does it fit 100k?

- VERIFY frame, `MAX_VERIFY_GAS = 100,000` (`../notes/altmempool-erc8421.md`): one token, yes. That leaves ~37k headroom.
  - Assumption: calldata and the 21k intrinsic are tx intrinsic gas, not frame execution. Not checked against the sidecar's frame-gas accounting.
- Real account, config read from storage instead of immutables:
  - 4 cold SLOADs (issuer x/y, email hash, aud hash) add ~8.4k, so ~72k.
  - Better: store one config hash. Pass the config in calldata and check it: one SLOAD, ~2.2k extra.
- Multi-member rule (two EVTs on one domain): ~126k execution. **Does not fit 100k.** Options:
  - a staked entity on the alt mempool (draft 1M, but the live sidecar has no staked budget: see the altmempool note);
  - or verify outside VERIFY (an execution frame, a relayer, a normal tx).
- Standalone EOA-sent tx: ~100k all-in. That is on the line, but no 100k cap applies there.
- Without the precompile: daimo p256-verifier is "about 330k gas" per signature. Two signatures come to ~660k. Not viable for VERIFY.

What made the difference:

- optimizer_runs 200 → 1M: 85k → 68k. At 200 runs solc loaded the 32-byte SWAR masks with CODECOPY instead of PUSH32.
- SWAR decoder (32 chars per step) instead of a per-char table: decode 300 chars went 72.6k (per-char loop, runs 200) → 14.6k (SWAR, runs 200) → 8.2k (SWAR, runs 1M).

Ideas to cut more (not done):

- Decode only the claim windows, not the whole payloads (skips `iss` and `kty`/`crv`).
- Pass `bx, by` as words and compare their encoded form. That saves 2 decoder chunks.
- Drop the `sd_hash` check: the cnf key is fresh per request, so it adds little. That saves ~2 chunks + 1 sha256.

## Claims

| Claim | Status | Source |
| --- | --- | --- |
| P256VERIFY lives at `0x100`, costs 6900 gas, 160-byte input `h,r,s,qx,qy`, returns 32 bytes `…01` on success, 0 bytes on failure, never reverts | VERIFIED | https://eips.ethereum.org/EIPS/eip-7951 |
| EIP-7951 does not require low-s ("not required to be non-malleable per NIST FIPS 186-5") | VERIFIED | same |
| EIP-7951 is in Fusaka; mainnet 2025-12-03 21:49:11 UTC (epoch 411392), Sepolia 2025-10-14 (epoch 272640) | VERIFIED | https://eips.ethereum.org/EIPS/eip-7607 |
| Forge 1.4.3 with `evm_version = "osaka"` runs 0x100 locally (`vm.signP256` signature verified, 32-byte output) | VERIFIED (test `test_p256_precompile_alone`) | local |
| daimo p256-verifier: "Verifying a signature costs about 330k gas" | VERIFIED | https://github.com/daimo-eth/p256-verifier |
| Frame-tx VERIFY cap is 100,000 gas (sidecar and ERC-8421 draft) | VERIFIED earlier | `../notes/altmempool-erc8421.md` |
| The frame devnet (ethrex) has 0x100 enabled for contract calls | UNREACHABLE (not tested; the notes say P-256 is a protocol signature scheme there, which suggests support) | `../notes/altmempool-erc8421.md` |
| Real Chrome KB-JWT bytes match our layout | UNREACHABLE (no live Chrome run). The offsets design is layout-agnostic, so key order does not matter | — |

## Next steps for the hackathon

- Mint a real token from Chrome against our ES256-only issuer. Feed it to `verify` with offsets computed in JS (the same `offsets()` function as `mint.mjs`).
- Put `verify` behind a VERIFY frame on the devnet. Read the admission report's frame gas to confirm the ~63k.
- For two members, put one EVT in VERIFY and one in an execution frame. Or stake.
