# SAFE guard preflight (2026-09-27)

Chain: **Ethereum Sepolia, chainId 11155111** (not World Chain 4801).
RPC: `https://ethereum-sepolia-rpc.publicnode.com`.

## Chain facts (checked with cast)

| check | result |
|---|---|
| `cast chain-id` | 11155111 |
| latest block gas limit | 60,000,000 (block 11,787,018) |
| per-tx gas cap | Sepolia runs Fusaka, so EIP-7825 caps a tx at 16,777,216. Not probed on the RPC (estimateGas ignores it); forge/anvil `osaka` enforce it, so tests budget against 16.7M. |
| P-256 precompile `0x100` (RIP-7212 / EIP-7951) | returns `1` on the standard valid vector |

## Safe: v1.5.0 (canonical, all have code on Sepolia, `VERSION()` = "1.5.0")

| contract | address |
|---|---|
| Safe (singleton) | `0xFf51A5898e281Db6DfC7855790607438dF2ca44b` |
| SafeL2 (use this: events for indexers) | `0xEdd160fEBBD92E350D4D398fb636302fccd67C7e` |
| SafeProxyFactory | `0x14F2982D601c9458F93bd70B218933A6f8165e7b` |
| CompatibilityFallbackHandler (NOT set, see below) | `0x3EfCBb83A4A7AfcB4F68D501E2c2203a38be77f4` |
| MultiSend | `0x218543288004CD07832472D464648173c77D7eB7` |
| MultiSendCallOnly | `0xA83c336B20401Af773B6219BA5027174338D1836` |
| ExtensibleFallbackHandler | `0x85a8ca358D388530ad0fB95D0cb89Dd44Fc242c3` |

Source: safe-deployments `src/assets/v1.5.0/*.json`, `networkAddresses["11155111"] = canonical`.
Library: `safe-smart-account` tag `v1.5.0` (`dc437e8f`). 1.4.1 (singleton `0x41675C09…`, L2 `0x29fcB43b…`, factory `0x4e1DCf7A…`) also present; not used.

Fallback handler: `address(0)` at setup. The compat handler validates EIP-1271 signatures, which would let owners sign permits that move tokens without `execTransaction`, so they skip the guard.

## Deployer

Reuse the funded ENS key by path, not by copy: `SAFE_KEY_FILE=~/.enconomy/ens-sepolia.key` in `contracts/.env` (gitignored).
Address `0x7Dc35E0c67Bd247f61f3cc5053a16E4FC94e8860`, 0.966 ETH at preflight, nonce 32.
Same key as the ENS lane: do not broadcast while an ENS script is running (nonce clash).

## Presence verifier (pluggable)

Guard calls `IPopPresenceVerifier.verify(safeTxHash, presenceProof)`. Two implementations:

1. `PopAttestationVerifier`: server P-256 attestation, `pop-safe-v2` digest (spec 01 §8.2). Works today.
2. `NoirPresenceVerifier`: wraps the bb UltraHonk verifiers. Stub + mock until the ZK lane ships.

### Noir option A, as it stands in the ZK worktree (`f7c124c`)

Toolchain: nargo 1.0.0-beta.22, bb 5.0.0-nightly.20260522, `bb prove -t evm` (keccak, ZK flavor). Solidity interface `verify(bytes proof, bytes32[] publicInputs) returns (bool)`, two linked libs (`RelationsLib`, `ZKTranscriptLib`).

Three proofs per session:

**phone proof** (circuit `oaN_s48`, one per role, `PhoneVerifier`, N = 2^20, vk sha256 `769ac931…`): proof 10,304 B, 12 public inputs (verifier constant 20 = 12 + 8 pairing limbs carried in the proof):

| # | name | onchain check |
|---|---|---|
| 0,1 | `nonce_hi`, `nonce_lo` | = session_nonce[0:16], [16:32]; session_nonce = PopCtx(chainId, safe, safeTxHash, notBefore, sid) |
| 2 | `attempt` | same in A, B, pair |
| 3 | `role_b` | 0 for A, 1 for B |
| 4 | `code_commit` | free (server vouches via POPCC1 off chain) |
| 5..8 | `issuer` X hi/lo, Y hi/lo | = pinned server issuer P-256 key |
| 9 | `sr` | = pair `sr_a` / `sr_b` |
| 10 | `valid_at` | freshness vs `block.timestamp` |
| 11 | `halfCommit` | = pair `commit_a` / `commit_b` |

**pair proof** (`noir/pair`, `PairVerifier`, 7 public inputs, verifier constant 15): `nonce_hi, nonce_lo, attempt, commit_a, commit_b, sr_a, sr_b`. Proves NEAR (-20 < distance < 60 cm) from the two private half values and distinct device keys (`xa != xb`). Not produced by the server yet.

The circuits expose no World ID nullifier, pairTag or device key hash. Human uniqueness stays a server claim (attestation path).

Gas: research numbers (older circuit) 2.9M tx per phone proof, 2.35M pair, about 7.7M execution per session. Fits the 16.7M tx cap, but the 2^20 `oaN_s48` verifier is unmeasured. Test with a 16.7M budget.

`presenceProof` for the Noir path (proposal): `abi.encode(uint64 notBefore, bytes16 sid, bytes proofA, bytes32[12] pubA, bytes proofB, bytes32[12] pubB, bytes proofPair, bytes32[7] pubPair)`.

## Decisions

- Verifier address: immutable in the guard. Switching attestation → Noir = deploy a new guard, then `setGuard` through a normal (proof-gated) Safe tx. No timelock code needed.
- Escape hatch: per spec 02 §5.
