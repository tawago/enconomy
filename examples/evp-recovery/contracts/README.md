# EVP recovery account (DESIGN.md sections 3, 4, 6)

Nov 3, 2026, proof check added Nov 6. Forge only. No tx sent, no real keys, no network. No real proof runs here: the proof tests use mock verifiers.

Run:

```
node script/mint-fixtures.mjs     # fresh test keys in keys/, writes test/Fixture.sol
forge test --offline              # 158 tests
forge test --offline --match-contract GasBench -vv
```

Output of the last run: `results/2026-11-06-forge.txt`. Mutation sweep of the proof checks: `results/2026-11-06-mutants.txt`. Earlier: `results/2026-11-03-forge-fixes.txt` (after REFUTE.md), `results/2026-11-03-forge.txt`.

## Files

| File | What |
| --- | --- |
| `src/EvpRecoveryAccount.sol` | `RecoverableP256Account` copied from `poc-validation-rules`, plus the 2-sig EVP start branch, `evpVerify`, `startRotationEvp`, `laptop`, `laptopDeviceX`, `configHash`, `setLaptop`, `setLaptopDevice`, `setConfig`, `ctxFor`, `evpCtx`, `popNonceFor`, `checkEvp` |
| `src/pop/` | `PopCtx`, `PopAttest` copied. `IPopPresenceVerifier` and `EvpNoirPresenceVerifier` adapted from `contracts/`: 11-input pair, device Xs checked, no TIMESTAMP |
| `src/EvpCheck.sol` | `poc-evp-issuer/src/EvpVerifier.sol`, turned into an internal check. Config from calldata, nonce = ctx, aud by length + quote, 900 s window |
| `src/frame/*` | copied unchanged from `poc-validation-rules` (pragma relaxed to `^0.8.28`) |
| `script/mint-fixtures.mjs` | node stdlib only. Own keccak, checked against `../ctx-vector.json` before it writes anything. Mints 13 tokens |
| `test/EvpRecovery.t.sol` | 89 logic tests on MockEnv with a mock presence verifier. The account sits at `0xacac..` on chain 1337 with nonce 7. GOOD is the shared vector; VERIFY tests use a real P-256 phone key and GOOD_PHONE, since `0xeeee..` has no (qx, qy) |
| `test/EvpPresence.t.sol` | 50 tests: the real adapter with mock Honk verifiers and real POPCC1 signatures, then account + adapter + script-minted token. Each paired check is hit on each side. `MockHonk` can refuse given proof bytes and hold a proof to its own inputs |
| `test/GasBench.t.sol` | 12 gas tests on the real contract, mux helper stubbed, ethrex charges added, proofs mocked, proof cost cited. One burns the cited costs through the real 63/64 call chain |
| `test/LiveToken.t.sol` | 3 tests: the 15 real Chrome tokens from `../live-chrome/verify/test/LiveFixture.sol` through `checkEvp`. They cannot reach the body or frame 1 (minted past the vector's deadline, name `0xeeee..`), and a test pins that |
| `test/StateGas.t.sol` | 4 tests: no start writes a fresh slot (EIP-8037 state gas), across deploy, cancel and finish |

## What the page has to reproduce

- `ctx` exactly as DESIGN.md section 3. `test_vector_ctxMatchesFile` reads `../ctx-vector.json` at test time.
- `Config = (uint256 issuerX, uint256 issuerY, bytes32 emailHash, bytes32 audHash, uint256 popIssuerX, uint256 popIssuerY, address presenceVerifier)`.
  `configHash = keccak256(abi.encode(cfg))`, seven words, 224 bytes.
  `emailHash = keccak(email bytes)`, `audHash = keccak(origin bytes)`, no quotes.
- `startRotationEvp(address newKey, bytes32 sessionTag, uint256 deadline, Config cfg, bytes token, uint256 offs)`.
  Head: newKey at 4, sessionTag at 36, deadline at 68, cfg at 100..323, token offset at 324, offs at 356.
- `evpVerify(uint64 notBefore, bytes16 sid, uint256 qx, uint256 qy, Config cfg, bytes bundle)` is frame 1's data. `bundle = abi.encode(EvpNoirPresenceVerifier.Bundle)`.
- `offs` is 16 x uint16. Fields 0..14 are the PoC's (`mint-fixtures.mjs offsets()`). Field 15 is new: the byte length of the aud string.
- Before sending, the page can `eth_call checkEvp(token, offs, cfg, ctx)`. Same code as the body.

## VERIFY, 2-sig branch

Own storage: `laptop`, `laptopDeviceX`, `owner`, `recoveryNonce`, `configHash`. Calls `cfg.presenceVerifier`, so this needs our own sidecar.

- Entered only through `evpVerify`. The fallback refuses 2 sigs.
- 4 frames, current frame 1, frame 1 mode VERIFY, scope EXECUTION. It approves EXECUTION only, never payment.
- Frame 0: target 0x8141, VERIFY. Deadline from its 8 bytes.
- Frame 2: VERIFY, target `laptop`, scope PAYMENT. `sig[1]`: secp256k1, empty msg, signer `laptop`.
- Frame 3: SENDER, target self, selector `startRotationEvp`. No length pin. Calldata deadline must equal frame 0's. Dirty high bits on newKey are refused.
- `newKey` not zero, not owner. `sig[0]`: empty ARBITRARY entry, not read. The phone signature was dropped: its transcript signs popNonce, which commits ctx, which holds newKey. Tests still expect it.
- `keccak(cfg) == configHash`, `keccak(qx||qy)[12:] == newKey`, `laptopDeviceX != 0`.
- `cfg.presenceVerifier.verifyPresence(popNonce, laptopDeviceX, qx, popIssuer, notBefore, deadline, bundle)`.

## Body

`configHash` check, `now <= deadline`, newKey not owner, then the token: issuer ES256, cnf key, KB ES256, aud, email, `email_verified`, both iats in `[now - 900, now + 60]`, sd_hash, nonce == `"0x" + hex(ctx)`. Then `pendingOwner`, `readyAt = now + DELAY`, `recoveryNonce++`.

## Tests, by name

- Vector: ctx, preimage, DOMAIN, frame 0 bytes, audHash, emailHash; live ctx at the vector's address.
- Happy path: VERIFY approves EXECUTION only; body lands; offline `checkEvp`.
- Replay: same tx after start (dies in VERIFY), same token twice, after cancel (old dies, a fresh nonce-9 token works), token for the next attempt.
- Wrong aud, and the prefix origin `https://recover.tawago.com.evil.example` with the honest length hint.
- Wrong nonce: other key's ctx, a plain value, other sessionTag, other newKey with the good token.
- Stale iat (-1000 s), future iat (+200 s), window edge at deadline, expired.
- Wrong issuer: token from another key; relayer swaps cfg (configHash stops it).
- Other email, KB by a non-cnf key, tampered KB, bad hint.
- High-s: KB high-s passes, issuer high-s passes, the high-s twin of a landed token cannot replay.
- Laptop leg: wrong payer frame target, wrong signer, wrong scheme, explicit msg, not paying, not VERIFY, no laptop enrolled. Laptop alone is not an owner.
- Phone leg: other msg, sig hash instead of ctx, other signer, wrong scheme; relayer swaps newKey or sessionTag; deadline mismatch and stretch.
- Layout: no expiry, frame count, frame index, other body function, other target, other mode.
- Early finish, finish after the delay, stranger finish, cancel by owner, pending key cannot cancel or call other functions, guardian 3-sig path still green.

Griefing paths from `threat-model.md` 2.7:

- `test_grief_freshKeyWithoutLaptop`: a fresh key plus an old public token, no laptop. Dies in VERIFY. Nobody pays.
- `test_grief_accountNeverPaysStart`: the self-paid shape (frame 1 flags 3) is refused.
- `test_grief_junkTokenIsPaidByLaptop`: a junk token passes VERIFY, reverts in the body, state does not move. VERIFY approved EXECUTION only, so the laptop paid.
- `test_finish_early_bodyReverts`: the accepted grief from DESIGN 4.3.

## Gas (forge 1.4.3, solc 0.8.30 via-ir, runs 1M, evm osaka)

Measured = forge, cold accounts and slots. Modeled = measured + 3,000 entry + 400 Amsterdam surcharge per cold account in VERIFY (cancel and finish: the mux helper; start frame 1: helper, adapter, phone and pair verifiers), or + 3,000 entry (body). Same method as `poc-validation-rules`. Frame 1 adds 11,473,237 cited from `../../poc-verifier-gas/README.md` for the OLD 7-input bundle.

That plain sum isn't the margin. EIP-150 holds gas back at account to adapter and adapter to verifier. `test_budget_start_frame1_forwarded` burns the cited phone cost through the real account and adapter at the 12M limit: the largest pair that fits is 3,524,568 against 3,320,074 cited, so about 204,000 is left for the 11-input pair, whose cost is unmeasured. Burn mocks only, 1,000 gas steps; a real verifier also holds back gas at its own precompile calls.

| Frame | Measured | Modeled | Limit |
| --- | ---: | ---: | ---: |
| start 0 expiry | - | ~3,050 (poc) | 4,000 |
| start 1 account VERIFY, with mock proofs: frame pins, decode, adapter, 2 x P-256 | 82,905 | 87,505; with cited proofs 11,560,742 as a plain sum | **12,000,000** |
| start 2 laptop pay, default code | - | OPEN | 8,000 |
| start sig entries 6,700 + 2,800 | | 9,500 | |
| **start prefix sum** | | | **12,021,500 / 16,000,000**, our sidecar only. The public cap of 100,000 rejects it |
| start 3 body `startRotationEvp` (EVP + pending write) | 80,461 | 83,461 | 110,000 exec; state from estimate, floor 100,000 |
| start frame 3 calldata, 1,316 bytes, token 871 | | 19,028 (intrinsic) | |
| start frame 1 data, 30,052 bytes at real proof sizes | | 462,832 (intrinsic) | |
| **start tx under EIP-7825**, state excluded | | **12,627,388** | **16,777,216** |
| cancel 0 VERIFY (owner) | 7,303 | 10,703 | 12,000 |
| cancel 1 body | 11,783 (pre-refund, warm after VERIFY) | | |
| finish 0 VERIFY (pendingOwner) | 11,460 | 14,860 | **18,000** (DESIGN's 15,000 leaves 140) |
| finish 1 body | 13,795 (pre-refund, warm after VERIFY) | | |

State gas: a fresh slot costs 97,920 and a frame cannot borrow it from execution gas. The account now never leaves slot 1 or slot 2 at zero (`slot1Keep` packed into slot 1, `recoveryNonce` starts at 1), so a start writes no fresh slot. The body number dropped 17,100 at that fix for the same reason (slot 1 is now a non-zero rewrite). Forge prices Osaka; the devnet's SSTORE side is a few thousand lower under EIP-8037. Still give frame 3 a state limit: if the account is ever set up another way, 97,920 per fresh slot is what it needs. Not modeled: the real cost of the laptop's pay frame (ethrex source says 0 used + 3,000 entry; default code reads `sig[1]`).

## Deviations from DESIGN.md, and why

- EVT header is no longer pinned (the PoC pinned it by hash). Config is DESIGN's seven fields. The issuer key is ours and signs only EVTs. `typ` is unchecked on both JWTs.
- `offs` grew a 16th field (aud length). DESIGN keeps `audHash` of the bare origin, so the length has to come from somewhere. The closing quote is checked, so a longer origin cannot pass.
- Finish VERIFY limit: 18,000, not 15,000.
- The body also checks `now <= deadline` and `newKey != owner`. Cheap, and the frame-0 expiry is then not the only guard.

## Known, not fixed

- The real proof, its verifier and the 11-input pair circuit don't exist. The mutants in `results/2026-11-06-mutants.txt` show the tests notice lost checks, with mock proofs only.
- Whoever holds `L` and the mail session can start again while a rotation is pending. Each start replaces the pending key and resets `readyAt`. Only the owner's cancel stops it. Same as the stolen-laptop row in DESIGN section 9.
- `recoveryNonce` lives in slot 2 and starts at 1. Slot 1 = `pendingOwner` (20) + `readyAt` (8) + `slot1Keep` (4, set to 1, never cleared). A tool that writes slot 1 raw must keep bit 224 set, or the next start needs 97,920 state gas (`test_stateGas_withoutKeepWordStartIsFresh`).
- `L` is a non-canonical payer: ethrex keeps one `L`-paid tx pending at a time.
- Cancel and finish no longer zero slot 1, so they lose the Osaka clear refund (4,800) they used to get. The table shows pre-refund numbers, so it did not move.
- `finishRotation()` needs no auth. Anyone can finish with a plain legacy tx after `readyAt`, so `A` needs no ETH for it.
- Nothing here has run on an EIP-8141 chain. 0x100 and 0x02 from a SENDER frame on the devnet are untested.
