# poc-native-evp: can EVP recovery run inside VERIFY?

**No.** Not on the live devnet, not with a 100k cap. SHA-256 alone blows the budget, about 2.5x over.
The two ES256 signatures themselves are fine: both ride as native scheme-2 entries at 6,700 each.
What doesn't fit is proving that those signed digests belong to the token we parse. That proof is SHA-256, and VERIFY can't call 0x02.

So the tx has to be split. VERIFY checks the native entries and approves execution. A body frame does the full check with the precompile, then rotates.
The rescuer pays the gas, never the account.

All runs on 2026-11-03. No tx, no network, test keys only (`keys/`, from `mint.mjs`).

## 1. ES256 JWS as a scheme-2 entry: works

Rule, from the source:

- ethrex `crates/vm/levm/src/vm.rs` `validate_frame_signatures` (~L905-1010). Scheme 2 = 128 bytes `r||s||qx||qy`. Needs `0<r<n` and `0<s<=n/2`. Signer = `keccak(qx||qy)[12:]`. Msg is the sig hash when empty, or an explicit 32 bytes. An explicit all-zero msg is rejected (L921). Verification goes through the p256_verify routine with a scratch gas counter, outside the EVM. **VERIFIED**
- sidecar `packages/executor/src/services/FrameTxService/signature.ts` L19-26, L58-79. Same rule. noble 1.8.1 `p256.verify(sig, msg, pub, {lowS:false})`, prehash off by default in 1.x, so msg is used as the digest. **VERIFIED**
- sidecar `validationPrefix.ts` L10-35, L282-293 (FRA-040): the prefix `limits.execution` sum, plus 6,700 per P256 entry, must be at most 100,000. **VERIFIED**

So a JWS maps straight across: msg = `sha256(JWS signing input)`, signer = `keccak(x||y)[12:]` of the JWK, sig = r||s with s low-s normalized.

`node entries.cjs` → `results/entries.txt` (re-run today, all pass). It uses frame-lib.cjs plus a line-by-line port of the sidecar rule.

| | EVT (issuer key) | KB-JWT (Chrome cnf key) |
|---|---|---|
| signing input | 395 B | 291 B |
| JWS s came out high-s | no | **yes** |
| high-s as-is: plain ECDSA math | valid | valid |
| high-s as-is: sidecar port / frame-lib | rejected | rejected |
| s → n−s: plain ECDSA, sidecar port, frame-lib | valid, valid, ok | valid, valid, ok |
| tampered input / double-hashed msg / wrong signer | all rejected | all rejected |

So normalization is required, and it's safe: (r, n−s) is still a valid signature for the same key and msg. About half of real Chrome KB-JWTs will need it. The wallet does it, not the browser.

Full tx: 3 entries (EVT, KB, new key over the sig hash with empty msg). Each passes the sidecar port. FRA-040 sum = 79,900 limits + 20,100 = 100,000. Raw tx is 1,755 B.

Mapping note: in forge, `Sig.msg = 0` stands for an *empty* msg, i.e. the new-key entry signs the sig hash. On chain, never send an explicit zero msg.

## 2. SHA-256 with no precompile, measured

`gen_sha.py` writes `yul/sha256.yul`, a standalone Yul contract. Fully unrolled. 1-lane mode, plus a SWAR mode that runs 4 messages at once in 64-bit lanes. `build.sh` compiles it, and `NativeEvpCheck` reaches it with STATICCALL.
It's correct: matches 0x02 on every length 0..260, a fuzz run (256 cases), and all EVP slices. The precompile is used only as the test oracle.

`forge test -vv`, warm calls, caller-side gas. Real sample token, 861 B:

| hash job | blocks | gas |
|---|---:|---:|
| sha256 of 1 block (call overhead included) | 1 | 23,820 |
| KB-JWT signing input only (291 B) | 5 | **111,592** |
| EVT signing input only (395 B) | 7 | 155,410 |
| whole token | 14 | 308,809 |
| EVT + KB, 1 lane | 12 | 265,618 |
| EVT + KB, SWAR 4-lane | 7 steps | **176,935** (best) |
| EVT + KB + sd_hash, SWAR | 8 steps | 203,940 |

That's about 22k per extra block. Unoptimized Yul. The Yul optimizer ran over 16 min on the full file and I killed it. A 1-lane-only build was still optimizing when this README was written, so optimized numbers are **UNREACHABLE** for now.
It doesn't matter. Counting ops in one round gives an estimated floor of about 12k per block, even with a perfect compiler.

Claim checks (`src/NativeEvpCheck.sol`, from EvpVerifier.sol minus P256VERIFY): offsets, header hash, email, email_verified, both iats against a deadline, cnf x/y → KB signer address, aud, nonce = keccak(newKey), sd_hash, new-key signer.

| `check()` variant | gas |
|---|---:|
| claims only, digests trusted | **40,725** |
| + Yul SWAR, 2 digests | 218,041 |
| + Yul SWAR, 3 digests | 247,769 |
| + Yul 1-lane, 3 digests | 354,470 |
| + 0x02 precompile, 2 digests (body frame) | 41,951 |
| + 0x02 precompile, 3 digests (body frame) | **45,360** |

Negatives all revert: wrong digest, wrong signer per entry, stale iat, other newKey, KB reused with another EVT (sd_hash).

Side note: the hasher's runtime is 34,312 B, over EIP-170's 24,576. It would need splitting to deploy. That doesn't change the verdict.

## 3. VERIFY budget, all-in

| item | gas |
|---|---:|
| 3 P256 entries (issuer, KB, new key) | 20,100 |
| expiry frame (TIMESTAMP is banned elsewhere) | 4,000 |
| account frame, cold access (Amsterdam `COLD_ACCOUNT_ACCESS_AMSTERDAM` = 3,000, gas_cost.rs L287) | 3,000 |
| claim checks | 40,725 |
| SHA-256, EVT + KB, best measured | 176,935 |
| hasher cold access, extra over warm | 2,900 |
| keyed nonce first use, if the account pays with a keyed nonce | (+20,000) |
| **total** | **~247,700** vs 100,000 |

Floor check, with no measured hashing at all: 20,100 + 4,000 + 3,000 + 40,725 = 67,825. That leaves 32k for SHA-256. Even at a perfect 12k per block, KB alone is 5 blocks = 60k. EVT is another 7 on top. Dead, whatever the optimizer does.

You can't skip either hash. Without them, nothing ties the token bytes we parse to the digest the issuer or Chrome actually signed.

## Verdict: the forced split

```
frame 0  VERIFY  rescuer account   APPROVE_PAYMENT (0x1)      rescuer pays; its own entry/key
frame 1  VERIFY  recovering acct   APPROVE_EXECUTION (0x2)    cheap, see below
frame 2  SENDER  recovering acct   full EVP check + rotate    precompiles OK here
```

**VERIFY (frame 1), about 4-5k of execution:**
- `SIGPARAM(0, 0x00)` == registered issuer address.
- Read newKey with FRAMEDATALOAD. Check `SIGPARAM(2, 0x00) == keccak(newKey)[12:]` and `SIGPARAM(2, 0x02) == 0`. That second check means the new key signed this exact tx.
- APPROVE 0x2.

Prefix total ≈ 20,100 entries + ~3k cold + ~2k logic + the rescuer's frame and entry (~10k). That's ~35k, well under 100k. The expiry frame is optional: the body can read TIMESTAMP.

**Body (frame 2):** sha256 via 0x02, then compare to `SIGPARAM(0|1, 0x02)`, parse claims, check cnf → `SIGPARAM(1, 0x00)`, nonce = keccak(newKey), iat against TIMESTAMP, then rotate.
- Check gas is measured: 45,360. The rotate is not: 2 SSTOREs for a 64-byte key, ~25k estimated. So ~70k.
- SIGPARAM has no frame-mode gate (ethrex `opcode_handlers/frame_tx.rs` ~L620-670, 2 gas), so body frames can read entry msgs. **VERIFIED**
- APPROVE scopes 0x1/0x2/0x3: `common/types/transaction.rs` L2252-2256, `frame_tx.rs` L94-187. **VERIFIED**

**Why the rescuer must pay:** VERIFY only proves the issuer signed *something*. Any real EVT, for any email, passes it, and old ones are public on chain. If the account paid its own gas, a stranger could replay junk that passes VERIFY and fails in the body, and burn the account's balance. So the account approves execution only, and the payer is the rescuer, who eats the cost of their own failed attempts.
Replay of a good one is harmless: the body rotates to the same newKey, and the iat window bounds freshness.

Keyed nonce: with scope 0x2 the account's nonce isn't charged in VERIFY. The 20k first-use charge lands only on a payer that uses a keyed nonce.

## Files

- `entries.cjs`: step 1, builds and checks the entries → `results/entries.txt`
- `gen_sha.py`, `build.sh`, `yul/sha256.yul` (`yul/sha256_1lane.yul` for the optimizer), `build/*.bin`
- `src/NativeEvpCheck.sol`: claim checks, with hashMode 0 / 1 / 4 / 2 (precompile)
- `test/Sha.t.sol`, `test/Check.t.sol`, `test/YulSha.sol`, `test/Fixture.sol` (from mint.mjs)

Run: `./build.sh && forge test -vv` and `node entries.cjs`.
