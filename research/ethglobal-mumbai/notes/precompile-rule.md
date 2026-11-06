# Precompiles inside VERIFY: what the live sidecar does (settled from source)

Written 2026-11-02. Sources pinned: sidecar `forshtat/mempool-workshop-sidecar` @ 2e22ff0, node `forshtat/ethrex` eip8141-tracer @ 9aa3645 (clones in `tmp/`, read only). Live checks were read-only JSON-RPC to `https://altmempool.forshtat.com/rpc`: `skandha_config` and six `eth_getCode` calls. Nothing was run, no tx, no keys.

## Short answer

Yes. Under the live config (`precompiles: []`) a VERIFY frame that STATICCALLs 0x100, 0x02, 0x01 or 0x06-0x08 is rejected at admission by the sidecar's CODE_ACCESS rule. The node itself is fine with it; the sidecar rejects on top. The native P256 and secp256k1 signature schemes never go through the EVM, so they cannot trip the rule. ProbeAccount will be rejected. The EVP 63k path is dead inside VERIFY and fine in a body frame.

## The chain, line by line

### 1. The node records the code size of every call target, precompile or not

ethrex `crates/vm/levm/src/opcode_handlers/system.rs`, STATICCALL handler, lines 572-578:

```rust
        // ERC-7562/EIP-8141 validation-diagnostics: record the contract size
        // at first access to `address` (see the CALL handler's identical
        // comment above for the full rationale).
        if vm.erc7562_tracer.active {
            let code_len = target_code.code().len();
            vm.erc7562_tracer
                .on_contract_size_access(u8::from(Opcode::STATICCALL), address, || code_len);
        }
```

Same shape for CALL (lines 90-93), CALLCODE (288-291), DELEGATECALL (432-435). The tracer stores it as-is, `crates/vm/levm/src/erc7562_tracer.rs` lines 713-732:

```rust
    pub fn on_contract_size_access(
        &mut self,
        opcode: u8,
        addr: Address,
        code_len_fn: impl FnOnce() -> usize,
    ) {
        if !self.active {
            return;
        }
        let Some(frame) = self.call_stack.last_mut() else {
            return;
        };
        frame
            .contract_size
            .entry(addr)
            .or_insert_with(|| ContractSizeWithOpcode {
                contract_size: code_len_fn(),
                opcode,
            });
    }
```

The word "precompile" does not appear anywhere in `erc7562_tracer.rs`. There is no skip. `target_code` is the code stored at the address. For a precompile that is empty. Confirmed live with `eth_getCode` on 0x01, 0x02, 0x06, 0x07, 0x08, 0x100: all return `0x`. So the trace entry for a STATICCALL to 0x100 is `contractSize: 0, opcode: 0xfa`, keyed by the lowercase address (H160 serde).

### 2. The sidecar turns "size <= 2 and not in my list" into a rejection

`packages/executor/src/services/UserOpValidation/validators/frameTx.ts` lines 810-827:

```ts
      await check(EXPLORER_RULES.CODE_ACCESS, () => {
        const contractSizes = getContractSizes(currentNumLevel, {});
        for (const addr of Object.keys(contractSizes)) {
          if (
            addr !== sender &&
            contractSizes[addr].contractSize <= 2 &&
            !this.networkConfig.precompiles.includes(addr.toLowerCase())
          ) {
            const { opcode } = contractSizes[addr];
            throw new RpcError(
              `${role} accesses un-deployed contract address ${addr} with opcode ${
                EVM_OPCODES["0x" + Number(opcode).toString(16)]
              }`,
              RpcErrorCodes.INVALID_OPCODE
            );
          }
        }
      });
```

`getContractSizes` (`UserOpValidation/utils.ts` 268-284) merges `contractSize` maps over the whole call tree of the frame, so a precompile called from a helper two levels down is still caught.

The list it consults is the config. Default: `packages/executor/src/config.ts` line 671 `precompiles: [],`. Live, from `skandha_config` on 2026-11-02:

```
precompiles: []
whitelistedEntities: { paymaster: [], account: [], factory: [], external: [] }
relayOpsWithWhitelistedEntities: false
```

So every precompile address hits the rule. Expected message for a `self_verify` frame (ProbeAccount's shape, role "payer" per `validationPrefix.ts` line 108):

```
payer accesses un-deployed contract address 0x0000000000000000000000000000000000000100 with opcode STATICCALL
```

For the ChirpGas shape (`only_verify` = role "sender", `pay` = role "payer", lines 124 and 136) the prefix is the role of whichever frame made the call.

### 3. No escape hatch

The five entity checks (BANNED_OPCODE, CREATE, STORAGE, CODE_ACCESS, ENTRYPOINT_ACCESS, lines 692-840) all run and all get recorded in the report, then the first failure in source order is thrown (line 844 `const err = violations[0]`). A contract that touches no foreign storage, like ProbeAccount, has CODE_ACCESS as its first and only failure.

The whitelist branch (lines 845-865) waives only errors that carry `data.accessed`. The CODE_ACCESS error carries no data. The per-role whitelists (lines 870-889) are empty on the live node. The only thing that lets a precompile through is the `precompiles` config.

### 4. The node disagrees with the sidecar

ethrex's own canonical-mempool observer explicitly allows precompile targets. `crates/vm/levm/src/vm.rs` lines 4378-4381:

```rust
        // Precompiles are always valid targets.
        if precompiles::is_precompile(&target, self.env.config.fork, self.vm_type) {
            return Ok(());
        }
```

So `ethrex_simulateFrameTransaction` on the same tx reports the frame clean (`canonicalMempoolValid` stays true, no `CallToNonexistentOrDelegated`), and the sidecar rejects it on top. In the explorer's rule-by-rule report that is one green column (node) and one red row (sidecar CODE_ACCESS). P256VERIFY is a real precompile on this node: `precompiles.rs` 221-227 `active_since_fork: Osaka`, listed in `PRECOMPILES` (266), and the earlier `eth_call` with the geth vector returned `...01`.

### 5. Scope: body frames are not checked

`erc7562TraceAdapter.ts` 60-70, `selectPrefixTrace`:

```ts
  const epTopLevelCalls = trace
    .filter((entry) => entry.frameIndex <= lastPrefixIndex)
```

Only frames `0..lastPrefixIndex` (the validation prefix) go through `checkEntityCompliance`. A SENDER or any later frame can call 0x100, sha256, pairing, anything. The rule is purely about VERIFY (and pre_verify / pay) frames.

### 6. The ERC says the opposite

`tmp/erc-8421.md` line 195: "[CALLING-040] Precompiles that access nothing in the blockchain state or environment are allowed. These include the core precompiles 0x01 to 0x11 and the P256VERIFY precompile." The docs site repeats it (`docs/rules_opcodes.txt` 34). The code only honours that when the operator fills the list. No sidecar test exercises CODE_ACCESS either way (grep of `packages/executor/test` for "un-deployed" / "CODE_ACCESS": nothing).

## Native signature schemes do not touch the rule

Scheme 1 (secp256k1) and scheme 2 (P256) are checked before any frame runs, as plain function calls.

ethrex `vm.rs` `validate_frame_signatures` (905-1025). P256 branch, lines 1002-1012:

```rust
                let Ok(result) = crate::precompiles::p_256_verify(
                    &Bytes::from(calldata),
                    &mut scratch_gas,
                    fork,
                    crypto,
                ) else {
                    return false;
                };
                if result.len() != 32 || result[31] != 1 {
                    return false;
                }
```

`scratch_gas` is `u64::MAX` (line 929), the doc comment on line 900 says the gas deduction "is ignored". secp256k1 is the same with `crate::precompiles::ecrecover` at line 951. This is a Rust call into the precompile's math, not a CALL opcode: no `on_contract_size_access`, no trace entry, nothing for the sidecar to see. The sidecar does its own copy in `packages/executor/src/services/FrameTxService/signature.ts` lines 73-79:

```ts
    // Per EIP-8141 line 319: signature validation does not happen in EVM
    // execution, so ecrecover/P256VERIFY are NOT precompile calls here —
    // this is the same pure off-chain math the P256VERIFY precompile
    // performs, done directly with @noble/curves' secp256r1 implementation.
    // Uncompressed SEC1 public key encoding: 0x04 || qx (32 bytes) || qy (32 bytes).
    const publicKey = new Uint8Array([0x04, ...toBytes(qx), ...toBytes(qy)]);
    return p256.verify({ r, s }, toBytes(msg), publicKey, { lowS: false });
```

Cost is the flat 6,700 per P256 entry against the 100k cap (`validationPrefix.ts` 27), nothing else. The ChirpGas lead design (two scheme-2 entries, keccak opcode only, no precompile) is untouched by this rule.

## Conclusions

**ProbeAccount** (`poc-validation-rules/src/ProbeAccount.sol`, STATICCALL to 0x100 in `_verifyFrame`): rejected by the live sidecar on CODE_ACCESS with the message above. The node side of the same dry run passes. Running it Nov 5 is confirmation, not an open question; a green result would mean the Mumbai sidecar has `precompiles` populated, which is plan open question 3.

**EVP fallback, the 63k 0x100 path** (`poc-evp-issuer/src/EvpVerifier.sol`): dead inside VERIFY on this config, twice over. Line 188 STATICCALLs 0x100 and `_sha256Slice` (line 204) STATICCALLs 0x02 three times per token. The rule fires before gas matters. It works unchanged in an execution frame, a normal tx, or on any sidecar whose list includes `0x...0100` and `0x...02`. Its 63k figure stays a true gas number, just not a VERIFY number here.

**Anything ZK in VERIFY** (Groth16 needs 0x06/0x07/0x08): same rejection, on top of the 100k cap.

**The knob.** Sidecar `config.ts` 556-560: `SKANDHA_PRECOMPILES` env var, a comma-separated list, lowercased and space-stripped by `fromEnvVar` (681-695), or `precompiles: [...]` in `config.json`. The `config.json` path is not lowercased, and the check is `includes(addr.toLowerCase())` against full 20-byte lowercase keys, so write entries as `0x0000000000000000000000000000000000000100`, lowercase, full width. For the local hot spare set it in `config.json`. For Mumbai, ask on Nov 5 what the devnet sidecar has in `skandha_config.precompiles`; that one field decides whether any precompile-based verifier is admissible.
