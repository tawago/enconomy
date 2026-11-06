# FIXES: what changed after REFUTE.md

Nov 3, 2026. One line per finding: did it hold, what I checked, what changed. No tx sent, no DNS touched, nothing exposed. Chrome runs were local only (127.0.0.1, throwaway profile).

Forge after the fixes: 84 pass, 0 fail (`contracts/results/2026-11-03-forge-fixes.txt`). Live verify: 15 of 15 Chrome tokens pass (`live-chrome/verify`).

## 1. FATAL: frame 3 has no state-gas budget

**Holds.** Checked in ethrex: `vm.rs` `increase_state_gas` (a frame spends only its own pool, no spill), `gas_cost.rs` (64 bytes per slot, 1530 per byte = 97,920), the SSTORE handler (charge only when original == current == 0 and new != 0, so no refund carries across txs). `poc/clients/gift-shape.cjs` line 42 does set `state: 0`.

**One more thing the refuter said in passing, and it matters most:** after every cancel *and every finish*, slot 1 is zero again. So `recoveryNonce = 1` alone fixes only the first start. Every later start would still need 97,920.

**Fix, in the contract:**
- `recoveryNonce = 1` in the constructor.
- A `uint32 slot1Keep = 1` packed after `readyAt` in slot 1 (20 + 8 + 4 bytes). `delete pendingOwner; delete readyAt` leave it alone, so slot 1 never goes to zero. Layout checked with `forge inspect`; `recoveryNonce` is still slot 2, so the tests and ctx are unchanged.
- New `test/StateGas.t.sol`: a fresh deploy leaves slots 1 and 2 non-zero; start, cancel, start, finish writes no fresh slot; with the keep word zeroed by hand the start writes exactly one fresh slot (the control).
- Side effect: body execution dropped from 97,424 to 80,324 (slot 1 is a non-zero rewrite now).
- `GasBench._setPending` keeps the keep bit.

**Fix, in DESIGN 4.1:** frame 3 gets `state` from the sidecar's per-frame estimate, floor 100,000. "Never copy gift-shape line 42." `L`'s balance must cover `total_gas_limit`, which includes state limits (`transaction.rs` `total_gas_limit`).

I did not write `evp-start-shape.cjs`. That is build work, not a fix.

## 2. SERIOUS: DESIGN said `tokenField.nonce = evpNonce`

**Holds.** `live-chrome/README.md` failure 1. Re-checked today: under a CSP header, `el.nonce = …` alone made no request and no token.

**Fix:** DESIGN section 5 step 4 now says `setAttribute("nonce", evpNonce)` and says why. `evp-flow.md` section 1's nonce row marked superseded for Chrome 156.

## 3. SERIOUS: header CSP + dynamic nonce never tested

**Was true. Now tested, and it works.** `serve.mjs` takes `CSP_MODE=self|nonce`, `cdp.mjs` takes `SETTER=attr|idl`. Chrome 156.0.8078.80:

- `default-src 'self'; script-src 'self'`, script in `/rp.js`: mints, with both setters and with `setAttribute` alone.
- `script-src 'nonce-<random>'`, inline script: mints with `setAttribute`; with IDL only, nothing.
- The attribute reads back intact after `setAttribute` under both headers. Blink's nonce hiding does not touch an attribute set later by script.
- Two of these tokens carry the vector ctx and verify in forge.

**Fix:** DESIGN section 9 keeps the header CSP and names `default-src 'self'`. `live-chrome/README.md` has a new "CSP header run" section and withdraws its earlier "no nonce-CSP header" advice, which was a guess.

Also fixed a harness bug: `cdp.mjs flow "" …` typed an empty email (`??` keeps `""`). That cost me two false negatives before the control passed.

## 4. SERIOUS: native permission bubble not in the risk list

**Holds.** `live-chrome/README.md` failure 2 and `tmp/prompt-native-bubble.png`. Every run today used the auto-grant switch.

**Fix:** DESIGN section 10 lists it first in the risks and says to name the switches on stage. "Does one manual click persist" is in section 12.

## 5. SERIOUS: "the phone that gets the key has to be in the room"

**Holds.** DESIGN's own section 5 and 9 already said the audio is binding, not proof. The demo line said more.

**Fix:** 0:30 is now "The new key came in by camera, and a phone was in earshot of my laptop, as far as its mic can tell." Section 5 lists why: the new phone may be the attacker, one cheater fakes NEAR, two tabs read NEAR, sound-bound signs nothing, `transcriptHash` is opaque and server-chosen. The CROPS "S" line is softened to match.

## 6. SERIOUS: Pages-origin page fetching the LAN server

**Holds on reading.** Not tested: nothing serves CORS today and I would not set up a trusted cert. The phone side does work through the self-signed cert (41 sessions in the Sept notes).

**Fix:** DESIGN section 11 makes the `--host-resolver-rules` harness plan A and the Pages origin the upgrade, and lists CORS + trusted cert as a user-gated row. Section 5 adds `BarcodeDetector` for the QR.

## 7. SERIOUS: ENS Sepolia root moved

**Holds, from `ens-half/README.md` section 0.** I did not re-query Sepolia today (no network calls in this pass).

**Fix:** DESIGN section 7 rewritten. Default demo shows no ENS. If a name is shown, the page calls `MeetResolver.resolve()` directly and the slide says "our resolver". The 0:00 and 2:30 lines no longer claim ENS.

## 8. SERIOUS: MeetResolver has no setText; 2a should be "no" now

**Holds,** from `ens-half/README.md` section 1 and the patch. Gas numbers (1.21M config, 0.84M receipt) are theirs.

**Fix:** section 7 lists the five user steps (re-register, deploy patched resolver, re-point, two attester txs) and the Nov 5 noon cutoff. 2a is called "no, decided Nov 3" with the refuter's five reasons. Section 8 no longer leans on a faucet.

## 9. SERIOUS: user-gated steps hidden

**Holds.** Section 11 step 4 and step 6 each hid several user actions.

**Fix:** section 11 has a table of what only the user can do and what each one unlocks. Any one missing on Nov 5 morning means plan A.

## 10. SERIOUS: no faucet; genesis key; block time 6 s

**Partly.** The genesis key and the 6 s block time hold (`genesis.values.env`: `SLOT_DURATION_MS="6000"`, a throwaway key published on purpose; 120 × 1530 = 183,600 for a new account). The faucet claim is contradicted inside the sources themselves: the public guide (`tmp/docs/guides_devnet`) says there is no faucet, while the sidecar repo's `deploy/devnet/devnet-readme.md` describes `skandha_explorer_faucet` on the gateway. Ours returned 502 twice.

**Fix:** section 11 plans on the genesis key, gas limit 250,000 for transfers, warns about shared-nonce collisions, and treats a working faucet as a bonus. Block time moved from "unknown" to closed; 120 s = 20 blocks.

I did not send the transfer. That is Nov 5.

## 11. SERIOUS: nothing ran on an 8141 chain; simulate takes no overrides

**Holds.** `poc/clients/README.md` "State overrides: no" (five call shapes tried live, source agrees).

**Fix:** section 11 order is now: fund deployer and `L` from the genesis key, deploy `A`, simulate the real start tx with `trace: true`, then page code. Section 12 keeps `0x02`/`0x100` in a SENDER frame and the pay-frame cost open until that call.

## Minors taken while passing

- Finish VERIFY limit 18,000 in DESIGN 4.3.
- The "A empty → L-paid finish shape" is gone. `finishRotation()` has no auth, so anyone can finish with a legacy tx.
- Pay frame cost: ethrex source says default code reads `sig[1]`, uses 0, pays 3,000 entry. Table updated.
- Prefix: noted ethrex sums 42,500, the sidecar 46,500.
- Non-canonical payer: one `L`-paid tx pending at a time. In DESIGN 8 and the contracts README.
- Risk list: block timestamp vs laptop clock (60 s skew), lowercase the email, pin Chrome.
- Section 12: cold SLOAD 2,100 vs a possible 3,000 on the devnet's commit; EVT `exp` 300 s vs body 900 s.

## Not done, on purpose

- No on-chain tx, no funding, no simulate call. All of it waits for Nov 5, in the order in section 11.
- `evp-start-shape.cjs`, the recovery page, the phone panel: build work.
- `threat-model.md` and `account-design.md` not edited. DESIGN says it wins over them.
