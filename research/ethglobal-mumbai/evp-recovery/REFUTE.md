# REFUTE: adversarial review of DESIGN.md and what was built

Nov 3, 2026. Checked against `DESIGN.md`, `contracts/`, `live-chrome/`, `ens-half/`, the ethrex source in `../tmp/ethrex` (docs/eip-8141.md, vm.rs, frame_tx.rs, transaction.rs, gas_cost.rs), the sidecar in `../tmp/mempool-workshop-sidecar`, and the alt-mempool docs in `../tmp/docs`. Nothing was run on a chain. Forge results are the ones in `contracts/results/2026-11-03-forge.txt`.

Tags: FATAL = the demo cannot work as written. SERIOUS = wrong, stale, or untested on the critical path. MINOR = fix when passing.

## Verdict in one paragraph

The shape is admissible and the crypto binding holds. The real holes are elsewhere: the body frame needs state gas that nothing in the plan budgets (one copied line turns this FATAL), DESIGN tells the page to set the nonce the way live Chrome ignores, ENS on Sepolia no longer resolves our names, and the proximity line in the demo script claims more than the audio gives. The 3-day plan is feasible only if the ENS oracle flip, v1.1, and the Sepolia receipt are cut today and the local `.test` harness is the fallback demo.

## 1. Frame layout: admissible

Holds. `[expiry, VERIFY A scope 2, VERIFY L scope 1, SENDER]` is ethrex's `OnlyVerifyPay` shape (`transaction.rs` `validation_prefix`, `validate_prefix_structure`): only_verify must target the sender, the pay frame has no target restriction, the expiry frame must be first with flags 0, value 0, state 0 and 8 bytes of data. All true in `contracts/src/EvpRecoveryAccount.sol` `_verifyEvpStart`.

Frame 2 (L, EOA, default code) is now closed, not OPEN. `frame_tx.rs` `execute_default_verify`: PAY-only scope reads **signature index 1**, needs SECP256K1, empty msg, signer == target, then approves. Gas used is 0. The frame pays only the 3,000 cold-account entry. DESIGN's sig[1] = L is the right slot; sig[0] = L would fail. The 8,000 limit is fine; 4,000 would do.

Budget: ethrex sums `frame_indices` (excludes the expiry frame) plus signature cost: 25,000 + 8,000 + 9,500 = 42,500. The sidecar sums every frame up to the last prefix frame including expiry: 46,500. Both under 100,000. DESIGN's number matches the sidecar's rule.

MINOR: L is a non-canonical payer (canonical = runtime code hash match). ethrex's canonical mempool caps `MAX_PENDING_TXS_USING_NON_CANONICAL_PAYMASTER = 1`: one L-paid tx pending at a time. Fine on stage; say it.

MINOR: `n == 2` in `_verifyFrame` means the owner can never send a 2-entry tx of its own. Design limit, not a bug.

## 2. VERIFY under 100k: yes, with one caveat

Holds. Frame 1 measured 18,041 cold, modeled 21,441 against 25,000.

MINOR: finish was 114 under DESIGN's 15,000; the contracts README already raised it to 18,000. DESIGN section 4.3 still says 15,000. Update it.

MINOR: `gas_cost.rs` line 346 says EIP-8038 raises cold SLOAD to 3,000 at Amsterdam, but `COLD_STORAGE_ACCESS_AMSTERDAM` is 2,100 at line 288. The bench assumed 2,100. If that constant moves to 3,000 before the event, frame 1 loses 2,700 of its 3,559 margin. Check the devnet's ethrex commit.

MINOR: frame 3 targets A, which frame 1 already warmed. Entry is 100 there, not 3,000. The body model is 2,900 high. Harmless.

## 3. Body frame state gas

FATAL: nothing in the plan budgets state gas for frame 3, and the only existing builder sets it to zero.

DESIGN section 12 says "EIP-8037 state gas on the pending slot write, not modeled. Give frame 3 a state limit." Here is the number and why it matters.

- Inside a frame tx the frame's `limits.state` is the only source of state gas. `vm.rs` `increase_state_gas`: "Exhausting it halts the frame even with execution gas remaining, and nothing spills across the boundary."
- A fresh storage slot costs `STATE_BYTES_PER_STORAGE_SET * 1530 = 64 * 1530 = 97,920` state gas.
- Storage layout: `owner` slot 0; `pendingOwner` (20 bytes) and `readyAt` (8 bytes) pack into slot 1; `recoveryNonce` slot 2. On a fresh deploy the first start writes slot 1 and slot 2 from zero: **195,840** state gas. After a cancel, slot 1 is zero again: 97,920 on the next start.
- `poc/clients/gift-shape.cjs` line 42 sets the body to `{ execution: bodyGas ?? 60000, state: 0 }` unless building for estimate. If `evp-start-shape.cjs` copies that line, every start halts in frame 3 for want of state gas. VERIFY passed, so L pays the full max cost and nothing rotates.

Fixes, pick both: set `recoveryNonce = 1` in the constructor so slot 2 is never fresh; take `limits.state` from the sidecar's `estimateFrameTransactionGas` (it returns per-frame `state`, `modules/eth.ts` line 448) or hardcode 100,000 for frame 3. L's balance must cover state limits too: `total_gas_limit` includes them.

Not a bug but note: under EIP-8037 the execution side of the SSTORE drops to 10,000 (`STORAGE_WRITE_AMSTERDAM`), so the forge body number (97,424, Osaka pricing) is a few thousand high. Good direction.

## 4. Payer, griefing, replay: holds

- Order is right. `APPROVE_PAYMENT` reverts if `sender_approved == false`; frame 1 approves execution before frame 2 pays.
- Junk tokens cost L. `test_grief_junkTokenIsPaidByLaptop` shows VERIFY approved execution only. The self-paid shape is refused.
- Replay dies in VERIFY: ctx carries `recoveryNonce`, which bumps on start, cancel and finish, and A's legacy nonce bumps on payment. The malleated high-s twin dies the same way (`test_highS_malleatedTwinCannotReplay`).
- Restart while pending (holder of L plus the mail session resets `readyAt`) is disclosed in the contracts README. Keep it in the project README.
- The phone's entry is an explicit-msg signature and does not commit to the frame list (sidecar SIGNATURE rule warns about exactly this). It is safe here because VERIFY pins the frame count to 4 and frame 3's selector and head, and L's sig-hash signature commits to every byte. If the frame-count pin is ever relaxed, this becomes a hole.
- Positive: `finishRotation()` is `external` with no auth and only checks `readyAt`. L, or anyone, can finish with a plain legacy tx. DESIGN 4.3's "if A is empty, build the L-paid finish shape" is unnecessary. A does not need ETH at all.

## 5. aud and nonce against live Chrome: binding holds, DESIGN's page instructions do not

What the 13 live tokens prove: `nonce` passes through byte-exact as `0x` + 64 lowercase hex, `aud` is the committed origin with no port and no slash, KB header and claim order are stable, `sd_hash` matches, both signatures verify with the unchanged PoC verifier (63,176 gas). The contract's `_nonce` and `aud` checks match these bytes. Good.

SERIOUS: DESIGN section 5 step 4 says `tokenField.nonce = evpNonce`. Live Chrome 156 read `GetAttribute("nonce")` and did nothing for the IDL slot (live-chrome failure 1). DESIGN says it wins over its siblings, so a page built from DESIGN mints nothing, with no error anywhere. Change the line to `setAttribute("nonce", evpNonce)`.

SERIOUS: (untested) DESIGN section 9 makes a header CSP the XSS defense. A header-delivered CSP makes Blink hide `nonce` attributes present at parse time. A later `setAttribute` on an inserted element should survive, but `live-chrome/serve.mjs` sent no CSP header, so the combination that DESIGN prescribes has never minted a token. One run with the real CSP header before the page is finished.

SERIOUS: (demo) the native "Verify this email automatically?" bubble stopped the flow until `--auto-grant-email-verification-permission-for-testing` was added. The demo either launches Chrome with that switch (say so on stage) or someone clicks "Verify" once and the pref persisting is unverified. Not in DESIGN section 10's risk list.

MINOR: the EVT carries `exp = iat + 300` and the body ignores it, accepting up to 900 s. Not a hole, since ctx and the expiry frame bound the attempt, but a judge will ask why the chain is looser than the issuer.

MINOR: the body's `FUTURE_SKEW` is 60 s against `block.timestamp`. If the devnet's block timestamps lag wall clock by more than a minute, every token is "from the future" and the body reverts. Compare the latest block timestamp to the laptop clock before the demo.

MINOR: `emailHash` is keccak of the bytes the issuer echoes. If the user types `Alice@tawago.com`, the worker accepts it (case-insensitive compare) and echoes it as typed, and the body reverts on `emailHash`. Lowercase in the page before Tab.

MINOR: Chrome updated itself from .74 to .80 during the live session. Pin or re-test the demo laptop's Chrome on the day.

Frame entries, separate from the token: ethrex rejects the whole tx for a high-s P-256 entry or a 27/28 `v`. The phone's software key must low-s normalize (DESIGN says so) and the builder must emit `v` in {0, 1}. The token's own high-s signatures are fine; 0x100 accepts them.

## 6. Proximity: what DESIGN says is honest, what the demo says is not

DESIGN section 5 is right: QR gives the key-input guarantee, audio adds "in earshot", the server is a trust root for the verdict, and against a stolen laptop it proves nothing.

SERIOUS: (honesty) the demo line at 0:30, "The phone that gets the key has to be in the room," is the one claim the audio cannot back. In a recovery the new phone is the attacker. The 2026-09-25 memo shows one cheating endpoint fakes NEAR by editing its own file with any relay device near the honest side, and a browser phone has no attestation. Two tabs on one laptop also read NEAR. On chain, `transcriptHash` is 32 opaque bytes nobody checks. With sound-bound, nothing is signed; the laptop takes the Python server's word. Say "was in earshot of my laptop, as far as my laptop's microphone can tell" or drop the line.

SERIOUS: (plumbing, not in DESIGN) the recovery page lives at `https://recover.tawago.com` (Pages). The sound-bound server runs on the LAN with a self-signed cert. The phone side is proven: 41 sound-bound sessions ran with Android Chrome as role B against that server, so `getUserMedia` through the self-signed cert works. The open gap is the laptop: for the Pages-origin page to fetch `transcriptHash` it needs CORS from that server and a cert the laptop trusts (a `fetch` gets no interstitial to click through). None of this is in section 11. The alternative that already works is `live-chrome/launch.sh`: `--host-resolver-rules` mapping `recover.tawago.com` and `tawago.com` to the local server. Then the page, the issuer and the session API share one server and `aud` is still the real string. Disclose the switches if used on stage.

MINOR: "scan the QR with the laptop camera" needs a decoder. Chrome on macOS has `BarcodeDetector` built in; use it rather than vendoring a library into a page that is meant to be dependency-free.

MINOR: `transcriptHash = keccak(session.json ‖ sha256(wavA) ‖ sha256(wavB) ‖ result.json)` is defined but the server that serves it is "not written" (section 12). The laptop cannot recompute it (it never sees the phone's WAV), so it is a server-chosen value. Fine for binding, say so.

## 7. ENS: the half that is built is honest; DESIGN is stale against it

SERIOUS: `ens-half/README.md` section 0 found that ENS moved the Sepolia v2 root. The Universal Resolver no longer finds `enconomy.eth`; `enconomy` is AVAILABLE in the new tree. DESIGN sections 7 and 10 still say "Sepolia has `alice.enconomy.eth`" and the demo's 0:00 and 2:30 lines resolve it. Today they resolve nothing through ENS. Either the user re-registers in the new tree (`ens.sh` hardcodes old addresses, memory says do not rerun bootstrap blind) or the demo page calls `MeetResolver.resolve()` directly and the slide stops saying "ENS resolved it".

SERIOUS: `MeetResolver` has no `setText` and ignores coin types other than 60. The mirror and receipt need the patch deployed (new CREATE2 address), the resolver re-pointed for `enconomy.eth` and `alice`, and two attester-key txs. Measured on Sepolia: 1.21M gas for the config multicall, 0.84M for the receipt. All of it is the user's keys. DESIGN section 11 step 6 ("Then ENS mirror + receipt") hides four user actions.

Call the 2a flip now, as "no": DS on tawago.com takes 1-2 days from Nov 3, `IssuerRegistry` is unwritten, the oracle deploy needs about 25M gas of 1337 ETH, the proof builder needs the user's dnspython, and `DNSSECImpl` fits the 2^24 cap with 0.6% headroom. Four user-gated conditions by Nov 5 noon is not a plan. The 2c text in ens-half section 4 is honest and enough.

MINOR: "ENS DNS path broken by root KSK 38696" is stated in ens-options and ens-half and is consistent with the oracle dry run (anchors 20326 + 38696 verified a cloudflare.com chain on 1337). Not re-derived here.

## 8. Demo feasible in 3 days: only with cuts

What exists and passes: the account (81 forge tests), the token check against 13 real Chrome tokens, the ctx vector end to end, the ENS dry runs. What is not written: the start-shape builder, the recovery page (keccak, L keygen, session join, EVP field, tx build), the phone signing panel, the sound-bound session API and `transcriptHash`, the ENS mirror and receipt wiring, the issuer on real paths.

SERIOUS: the user-gated steps are not called out. What only the user can do, each on the critical path of the "real DNS" story: the `_email-verification` TXT, the `recover.tawago.com` CNAME and Pages deploy, the Worker deploy at the apex, Sepolia attester-key txs, the ENS re-register decision, DNSSEC. Any one missing on Nov 5 morning forces the `.test` harness. Plan for the harness and treat the real DNS path as the upgrade.

SERIOUS: DESIGN section 11 step 1 says nothing moves without the faucet. The devnet guide says there is no faucet; one genesis account's key is published on purpose in the sidecar repo (`deploy/devnet/genesis.values.env`, present in `../tmp`). Fund L from it with a plain transfer at 250,000 gas (a brand-new account costs 183,600 state gas on this network). Block time is 6 s, which closes DESIGN's "unknown". A 120 s `DELAY` is 20 blocks; the video cut stands.

SERIOUS: nothing has run on an EIP-8141 chain. The one call that turns every MODELED number into MEASURED: `ethrex_simulateFrameTransaction` on `https://altmempool.forshtat.com` with `trace: true`. It returns `prefixShape`, per-frame execution and state `gasUsed`, and whether 0x100 and 0x02 work in frame 3 on this devnet. But it runs against real head state and takes no overrides (`poc/clients/README.md` "State overrides: no"). With A undeployed, frame 1 hits default code with EXEC scope and fails on the P-256 entry; with L unfunded, frame 2 reverts on balance. So the order on Nov 5 morning is: fund a deployer and L from the genesis key, deploy A with a test owner, then simulate with the real start tx. Two funded txs, then one free call. Do that before any page code. The judges' Mumbai devnet may run a different commit; ask.

Cut list for a green v1 by Nov 7: ENS 2a (no), v1.1 guardian (no unless the phone gate passes on Nov 4 and v1 is green by Nov 6 noon, as DESIGN says), the Sepolia receipt (only if the re-register happens on Nov 5). Keep: start, cancel, finish on 1337, the live token on stage, the replay and other-origin beats.

## What held

- Prefix shape admissible in the canonical mempool and the sidecar. Default-code payer confirmed in source.
- VERIFY measured under 100k with margin. Finish limit already fixed to 18,000.
- Chrome nonce byte-exact, `aud` as pinned, KB layout stable, high-s present and accepted, 13/13 tokens verify.
- Replay dead on `recoveryNonce`; griefing lands on L; relayer cannot tamper.
- ENS half says what it is: a mirror, not a trust root.

## Fix order

1. State limit on frame 3 (97,920 per fresh slot; 195,840 on a fresh account) and `recoveryNonce = 1` in the constructor.
2. `setAttribute("nonce", ...)` in DESIGN section 5; test the CSP header once.
3. Fund L and a deployer from the genesis key, deploy A, then run `ethrex_simulateFrameTransaction` with the real start tx.
4. Decide ENS: re-register or direct resolver call. Rewrite DESIGN section 7 and the 0:00 / 2:30 lines.
5. Rewrite the 0:30 line.
6. Add the permission bubble, the LAN server plumbing, and the genesis-key funding to sections 10 to 12.
7. Finish limit 18,000 in DESIGN 4.3; drop the "A empty" fallback; note L can finish with a legacy tx.
