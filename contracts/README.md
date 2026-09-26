# contracts

`MeetResolver` (ENSIP-10 resolver for `enconomy.eth` and every `<label>.enconomy.eth`) plus bash+cast bootstrap/ops for ENSv2 Sepolia. Spec: `docs/ens-meetings-design.md` §5.

- `src/MeetResolver.sol` — counters keyed on registry `resource`, existence-gated reads, ERC-7996 declared (UR calls us directly).
- `abi/ens/*.json` — ENS ABIs from contracts-v2 `71a3b733` (see `abi/ens/SOURCE.txt`).
- `out-abi/MeetResolver.json` — our ABI, for web/ and server/ (`script/export_abi.sh`).
- `script/ens.sh` — bootstrap + ops. Idempotent: reads chain state before each write.
- `deployments/sepolia.json` — written by bootstrap.

Single key: admin == hot == attester, key file `~/.enconomy/ens-sepolia.key` (override `ENS_KEY_FILE`). Never commit it.

## Env

| var | default |
|---|---|
| `ETH_RPC` | `https://ethereum-sepolia-rpc.publicnode.com` |
| `ENS_KEY_FILE` | `~/.enconomy/ens-sepolia.key` |
| `ENS_PARENT` | `enconomy.eth` |
| `ENS_EVENT_NAME` | `ETHGlobal Tokyo 2026` |
| `ENS_SITE_URL` | `https://enconomy.pages.dev/` (changing it later = one `setSite` tx on rerun, same address) |
| `ENS_OUT` | `deployments/sepolia.json` |

## Real Sepolia

```sh
cd contracts
./script/ens.sh addr                 # fund this address (0.1+ Sepolia ETH is plenty)
cast call 0xabe76f6c8dfced81aa5a2bb8034202a7136b94ca "isAvailable(string)(bool)" enconomy \
  --rpc-url https://ethereum-sepolia-rpc.publicnode.com       # must be true (or already ours)
ENS_SITE_URL=https://<project>.pages.dev/ ./script/ens.sh bootstrap   # ~9 txs, waits ~60 s commit->reveal
./script/ens.sh bootstrap            # rerun: "txs sent: 0"

# demo pre-seed / Plan B (no server)
./script/ens.sh claim alice          # register (roles 0, owner = our key, 90 d) + touch
./script/ens.sh record alice bob     # random session id; prints meetingId + firstTime
./script/ens.sh zk <meetingId>
./script/ens.sh void <meetingId>
./script/ens.sh status alice.enconomy.eth   # all keys through the Universal Resolver
```

Commit `deployments/sepolia.json` after the real run.

## Fork smoke

```sh
anvil --fork-url https://ethereum-sepolia-rpc.publicnode.com --hardfork osaka --chain-id 11155111 --port 8611 --silent &
cast rpc anvil_setBalance 0x7Dc35E0c67Bd247f61f3cc5053a16E4FC94e8860 0x8AC7230489E80000 --rpc-url http://127.0.0.1:8611
export ETH_RPC=http://127.0.0.1:8611 ENS_OUT=$PWD/.smoke/sepolia.json
./script/ens.sh bootstrap && ./script/ens.sh bootstrap        # 2nd: txs sent: 0
for l in alice bob carol; do ./script/ens.sh claim $l; done
./script/ens.sh record alice bob; ./script/ens.sh record alice bob; ./script/ens.sh record alice carol
./script/ens.sh status alice.enconomy.eth     # met "2", meetings "3"
./script/ens.sh status zzghost.enconomy.eth   # all ""
```

On anvil the script skips the 60 s wait with `evm_increaseTime` + `evm_mine`.

## Notes

- `Meeting.void` in the spec is `voided` here (`void` is a Solidity keyword). `meetingOf(id)` returns `(resLo, resHi, exists, zk, voided)`.
- `touch` also emits `TextChanged(url)` so the explorer lists `url`.
- Gas on fork: `record` first pair ~315k, repeat ~223k (mostly the 3+3 `TextChanged` string events).

---

# SAFE: PoP Safe guard (Ethereum Sepolia 11155111)

A Safe 1.5.0 (SafeL2) that only moves money when its two phone owners are physically together. Chain facts and addresses: `PREFLIGHT.md`.

- `src/PopSafeGuard.sol` — tx guard + `PopSafeSetup` (sets the guard inside `Safe.setup`). Per-Safe issuer key, device registry (`sha256(pub65)` → owner), escape hatch (`announce` → `delay` → execute within `grace`, recovery calls only), `cancel`/`cancelAll`. Refuses delegatecall, `gasPrice > 0`, `enableModule`, `setFallbackHandler`, `setModuleGuard`, threshold < 2, `setGuard` to a guard that hasn't `initSafe`d.
- `src/P256Owner.sol` — EIP-1271 owner for a phone P-256 key (`0x100` precompile) + CREATE2 factory. Phone signs `"pop-safe-owner-v1" ‖ safeTxHash`.
- `src/interfaces/IPopPresenceVerifier.sol` — `verifyPresence(safe, safeTxHash, qx, qy, presence) → (devA, devB)`, reverts if invalid. **Immutable per guard**: switching verifiers = new guard, PoP tx `newGuard.initSafe(...)`, PoP tx `setGuard(newGuard)`.
- `src/verifiers/PopAttestationVerifier.sol` — server P-256 `pop-safe-v2` attestation (the 172 B `POP2` tail, spec 01 §8.2). Works today.
- `src/verifiers/NoirPresenceVerifier.sol` — option A: 2 phone proofs (`oaN_s48`, 12 public inputs) + 1 pair proof (7) through bb UltraHonk verifiers, linked onchain (PopCtx nonce from `safeTxHash`, attempt, roles, issuer, sr, halfCommit, `valid_at` freshness). Returns `(0, 0)`: circuits expose no device ids yet, so the guard then requires two device-owning signers. TODOs in the file.
- `src/lib/PopCtx.sol`, `src/lib/PopAttest.sol` — spec 01 §5 / §8.2, golden vectors in `test/PopCtx.t.sol`.

`execTransaction.signatures` = `ownerSigs ‖ presence ‖ u32 BE len(presence) ‖ "POPV"`. Attestation path: `presence` = the server's 172 B `tail_hex`, so the relayer appends `tail ‖ 000000ac ‖ 504f5056`. No `POPV` suffix = hatch path. Fallback handler is always `address(0)` (the compat handler lets two owners sign permits past the guard).

## Test

```sh
forge build && forge test                                   # local EVM (osaka), Safe 1.5.0 from lib/
FORK=1 forge test --match-contract PopSafeForkTest          # Sepolia fork, canonical Safe 1.5.0 (rpc_endpoints.sepolia)
anvil --fork-url https://sepolia.gateway.tenderly.co --hardfork osaka --port 8612 --silent &
RPC=http://127.0.0.1:8612 script/anvil_smoke.sh             # deploy, create, spend, forced revert, hatch
```

`NoirRealGasTest` runs the real iPhone fixtures (`test/fixtures/zk`) through the real bb verifiers: phone A 4.08M, phone B 4.07M, pair 3.32M execution gas; the whole `execTransaction` about 11.9M execution, about 12.4M tx gas with calldata (29.6 KB signatures), under the 16,777,216 per-tx cap.

## Deploy (Sepolia)

```sh
PRIVATE_KEY=$(cat ~/.enconomy/ens-sepolia.key) forge script script/Deploy.s.sol --rpc-url sepolia --broadcast   # ~3.4M gas
# Noir guard later: VERIFIER=noir PHONE_VERIFIER=0x… PAIR_VERIFIER=0x… MAX_AGE=900 OWNER_FACTORY=… SETUP=… (same command)
```
Writes `deployments/11155111.json` (commit it). Anvil forks keep chainid 11155111: always set `DEPLOY_OUT=deployments/anvil-11155111.json`. Shared key with the ENS lane: don't broadcast while `ens.sh` runs.

Create the Safe: `script/CreatePopSafe.s.sol` (env list in the file; `PUB_A/PUB_B` from the server `devices` table). Recovery: `script/Recover.s.sol` (`MODE=announce`, wait `DELAY`, `MODE=exec`; guardian keys in `.env.guardians`, gitignored).
