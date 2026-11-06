# poc/clients: frame tx tools for chain 1337

The ChirpGas builder, its dry runs and the keeper were removed from this repo. Older sections below still describe them.

Written 2026-11-02. Pre-event research for the ETHGlobal Mumbai Continuity disclosure.
No tx was sent. Only read-only calls hit `https://altmempool.forshtat.com` (ethrex) and `/rpc` (sidecar).
Keys are deterministic P-256 **test** keys derived from a label (`testKey("deviceA")`). They hold nothing.
viem 2.56 and @noble/curves 1.9 come from `../../../../relayer/node_modules`. Nothing installed here.

**Update 2026-11-02, after `../../04-refuter-report.md`.** The builder now matches `ChirpGasSponsor`:
- D includes `sender` and `seq`.
- epoch = `T / 86400`.
- deadline = `deadlineFor(T)`.
- R = `beaconValue(T, salt)`.
- limits are 4,000 / 12,000 / 60,000.

**Update 2026-11-02, attester co-sign (`../../09-gap-fixes.md` item 1).** `chirpgasTx` adds `signatures[2]`: secp256k1, signer = attester, msg = D. The layout is 65 bytes `v || r || s`, with v the bare recovery id 0/1 and low-s, as in ethrex `validate_frame_signatures` and sidecar `signature.ts`. The attester key is a deterministic TEST key (`testSecpKey("chirpgas-test-attester")`), never the relayer key. `signAll` takes `{scheme}` per entry, and `{signature}` to use one made elsewhere (B's phone, the server). `selftest` checks entry 2 twice: with noble, and with viem `recoverAddress`, which is the sidecar's own call. It also checks that high-s and v=27 are refused, that entry 2's bytes move the sig hash, and that the sum is 92,200 (97,200 with frame 2 at 65k).

`selftest` checks a golden vector against `poc-validation-rules/test/GoldenVector.t.sol` (match). There's a new `--one-sig` send shape and a new `dryrun-s2-fees.cjs`. Why: `../../05-design-fixes.md`.

## Files

| File | What it does |
| --- | --- |
| `frame-lib.cjs` | The encoder. 9-item tracer envelope, raw tx, tx hash, sig hash, wire JSON, P-256 sign/check, ChirpGas digest `D` and epoch key |
| `build-frame-tx.cjs` | CLI: `regress`, `selftest`, `chirpgas [--estimate] [--wire]`, `raw < tx.json` |
| `probe-overrides.cjs` | Live: does either endpoint take a state override? Plus the no-code-sender signature check |
| `dryrun-chirpgas-shape.cjs` | Live: the full ChirpGas envelope through estimate and simulate, to see where it stops |
| `dryrun-s2-fees.cjs` | Live, read-only: estimate with fees omitted vs real fees vs the one-sig shape. Omitting fees fails `Insufficient max fee per gas` (base fee 7) |
| `demo.sh` | curl + jq wrappers: build, estimate, simulate, send (guarded), status, explorer, admissions, reputation, receipt |
| `check-frame-tx.cjs` | Unchanged. The older, independent re-encoder. Kept as a second regression |
| `gift-shape.cjs` | W4 Gas Gift: `giftDigest`, `giftTx` (B's account pays, B signs D once), `selftest` = golden vs `GoldenVectorGift.t.sol` (match) + estimate copy keeps B's entry. Offline |
| `humanhub-shape.cjs` | W1 HumanHub: `humanKey`, `hubDigest`, `humanhubTx` (sender = hub, 3 frames, A/B/attester all explicit msg = D, nobody signs the sig hash). `selftest` = golden vs `GoldenVectorHub.t.sol` (match), entries pass the sidecar checks, 2nd phone of a human gets the same key, estimate copy keeps all entries, a fee re-wrap keeps sigs valid (the hub caps tip/cost). Sum 80,200. Offline |

## What works

- **Regression.** `node build-frame-tx.cjs regress` re-encodes the two live txs and gets the same hash, both straight and after a round-trip through the wire JSON:
  `0x578d67aa…17c7` (EOA, secp256k1) and `0x4670c63e…9b03` (contract wallet, keyed nonce, explicit signer). The sig hash for `0x578d…` matches `check-frame-tx.cjs`.
- **Signing.** Entry 1 (device B, `msg = D`) is signed first, because its bytes stay in the sig hash. Entry 0 (device A, empty msg) then signs the sig hash. Both are low-s, `r||s||qx||qy`, signer = `keccak(qx||qy)[12:]`. `selftest` checks with the sidecar's own rules, then checks that entry 0's bytes are elided and entry 1's bytes are committed.
- **The live sidecar's signature rule passes for both entry shapes.** The evidence is indirect, so here is the chain:
  1. The sidecar's `validate()` checks signatures (frameTx.ts ~334) before the missing-trace check (~380).
  2. With a valid tx, the sidecar error moves past signatures to `validation frame 1: the frame's default code reported failure`.
  3. Negative control: flip one nibble and the sidecar says `Invalid frame transaction signature`. ethrex says `frame signature list does not authenticate the sender`, only for the flipped one.
  This holds for a no-code sender with an explicit signer, for sender = A's own address with signer `0x`, and for the 2-entry ChirpGas tx.
- **Expiry frame encoding.** The 8-byte BE deadline is read correctly: a deadline in the past gets `validation frame 0: reverted`, a future one passes frame 0. ethrex recognizes the shape as `OnlyVerifyPay` with the leading expiry frame.
- **demo.sh.** Every read wrapper ran against live. `send` is written but was never run with `CONFIRM_SEND=yes`. Without it, it refuses (exit 3).

## Gotchas found (they change the plan)

1. **The sidecar estimate rewrites body-frame limits before it checks signatures.** `eth_estimateFrameTransactionGas` sets every frame after the prefix to `10,000,000 / 10,000,000` (executor `modules/eth.ts`). That changes the sig hash, so a tx signed with its real limits fails the estimate with `Invalid frame transaction signature`. Fix: sign an estimate copy with 10M body limits (`--estimate`), then sign again with the real limits for the send. On the phones, that means two signatures per meeting, or estimating with laptop test keys. Decide before Nov 5.
2. **Frame 0 needs 3,000 gas just to enter.** At the plan's 1,000: `ran out of gas (the frame's gas limit 1000 cannot cover its entry charge of 3000 gas)`. This is a cold-account charge on every frame target (ethrex `vm.rs` ~3760, Amsterdam pricing 3,000, not 2,600). I set frame 0 to 3,500. (Now 4,000 / 12,000 / 60,000, sum 89,400. See 05-design-fixes F2/F3.) Every helper STATICCALL in frames 1 and 2 probably costs 3,000 cold as well, so the 20k/45k limits are now tighter than the plan thought.
3. **`maxFeePerGas` must be at least the base fee (7 at the probe).** Below that: `Insufficient max fee per gas`. `skandha_getGasPrice` said 9.
4. **The estimate message can hide a recent-root failure.** With a fake root ref, ethrex says `EIP-8272 recent-root reference is not committed`. The sidecar files it under the `recent-root` rule, but its message text is the frame halt (`describeStructuredFailure` wins, frameTx.ts ~395). Read the ethrex column too (`demo.sh simulate`).

## State overrides: no

Neither endpoint takes one. Tried on live with approve-all code (`6003600080aa`) plus 1000 ETH injected at the no-code sender:

| Call | Result |
| --- | --- |
| sidecar estimate `[tx, overrides]` | ignored (same error as baseline) |
| sidecar estimate `[tx, "latest", overrides]` | ignored |
| sidecar estimate `[{...tx, stateOverride}]` | ignored |
| ethrex simulate `[raw, latest, {trace, stateOverrides}]` | ignored |
| ethrex simulate `[raw, latest, {trace, stateOverride}]` | ignored |
| ethrex simulate with 4 params | `Expected one to three params` |

The source agrees. The sidecar dispatches only `params[0]`. ethrex's options struct has only `trace`, and unknown keys are dropped silently. `debug_traceCall` rejects overrides outright (`tracing.rs`).

So the planned "dry run with sponsor/account/registry injected" can't run on the live devnet. Without deploying, I can't answer any of these:

## Untested

- Storage rule: unstaked rejection of the foreign `humanOf` reads. Needs the contracts on a chain.
- 0xB6 RECENTROOTREFLOAD: never run. A real committed root ref is needed too; I had none.
- STATICCALL to 0x100 inside VERIFY under `precompiles: []`: not run, but settled from source (`../../notes/precompile-rule.md`): the sidecar rejects it on CODE_ACCESS. Native signature schemes 1 and 2 never hit that rule.
- Real verify gas of P256Account + ChirpGasSponsor.
- ~~D encoding vs the contract~~: done. The golden vector matches forge (D, epoch key, key-set hash, deadline, beacon R). The `pay(Attestation)` layout matches `ChirpGasSponsorLogic.Attestation`.
- `--one-sig` (10M body limits in the real send): the estimate accepts the shape, and the block gas limit is 60M. Not tested: inclusion, any block state-gas cap, any sidecar per-tx cap.
- Account, sponsor, MeetBook addresses, beacon source id, `slot` (349197) and `root` are placeholders. `T` and the deadline use the wall clock. Chain time was within ~2 min of it.

Only route for these: the local ethrex + sidecar (plan PoC 1), or a deploy on Nov 5.

## Run

```sh
node build-frame-tx.cjs regress      # live read, must print hashMatch true twice
node build-frame-tx.cjs selftest     # offline
node probe-overrides.cjs             # live read
node dryrun-chirpgas-shape.cjs       # live read
./demo.sh build --estimate && ./demo.sh estimate tx.json && ./demo.sh simulate tx.json
```
