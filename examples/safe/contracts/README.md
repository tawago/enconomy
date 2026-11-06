# contracts

The PoP Safe guard and its verifiers. The generated ZK verifiers stay in the core at [`contracts/zk`](../../../contracts/zk/README.md). `deployments/zk-sepolia.json` is a copy of `contracts/deployments/zk-sepolia.json`.

`MeetResolver`, its ENS ABIs, `ens.sh` and `deployments/sepolia.json` moved to [`examples/ens-meetings/contracts`](../../ens-meetings/contracts/README.md). The deployed addresses didn't change.

---


# SAFE: PoP Safe guard (Ethereum Sepolia 11155111)

A Safe 1.5.0 (SafeL2) that only moves money when its two phone owners are physically together. Chain facts: `PREFLIGHT.md`. Addresses and demo txs: `DEPLOYMENTS.md`.

## Pieces

```
phone A + phone B ── core session (plain context, ctx_hash = safeTxHash) ──► core server, signed presence record
   each phone: POST /v1/spends/<safeTxHash>/owner-sig on the backend  (P-256 over "pop-safe-owner-v1" ‖ safeTxHash)
../backend  record + both owner sigs ─► att.tail_hex (172 B POP2, "pop-safe-v2", signed with SAFE_ATTEST_KEY_FILE)
../relayer  relay.mjs (job from the backend) ─► checks hash/nonce/guard/devices on chain ─► execTransaction(…, ownerSigs ‖ POP2 ‖ 000000ac ‖ "POPV")
Safe ─► PopSafeGuard.checkTransaction ─► IPopPresenceVerifier.verifyPresence(safe, safeTxHash, qx, qy, presence)
```

- `src/PopSafeGuard.sol`: the tx guard, plus `PopSafeSetup`, which sets the guard inside `Safe.setup`. Each Safe has its own issuer key (qx, qy) and a device registry (`sha256(pub65)` → owner). Escape hatch: `announce`, wait `delay`, then execute within `grace`. Only recovery calls are allowed there. `cancel`/`cancelAll` exist too. The guard refuses delegatecall, `gasPrice > 0`, `enableModule`, `setFallbackHandler`, `setModuleGuard`, threshold < 2, and `setGuard` to a guard that hasn't run `initSafe`.
- `src/P256Owner.sol`: an EIP-1271 owner for one phone P-256 key (uses the `0x100` precompile), plus a CREATE2 factory. The phone signs `"pop-safe-owner-v1" ‖ safeTxHash` with SHA256withECDSA, as raw r‖s. High s is accepted.
- `src/interfaces/IPopPresenceVerifier.sol`: `verifyPresence(safe, safeTxHash, qx, qy, presence) → (devA, devB)`. It reverts if the proof is invalid. The verifier is **immutable per guard**. To switch verifiers, deploy a new guard, run a PoP tx `newGuard.initSafe(...)`, then a PoP tx `setGuard(newGuard)`. No timelock is needed, since both steps need presence.
- `src/verifiers/PopAttestationVerifier.sol`: checks the backend's P-256 `pop-safe-v2` attestation (spec 01 §8.2). **Live now.**
- `src/verifiers/NoirPresenceVerifier.sol`: the Noir option A adapter over the bb UltraHonk verifiers. Built and gas-tested, **not deployed**.
- `src/lib/PopCtx.sol`, `src/lib/PopAttest.sol`: implement spec 01 §5 and §8.2. Golden vectors are in `test/PopCtx.t.sol`.

Signature layout: `execTransaction.signatures` = `ownerSigs ‖ presence ‖ u32 BE len(presence) ‖ "POPV"`. With no `POPV` suffix the tx takes the hatch path. The fallback handler is always `address(0)`, because the compat handler would let two guardians sign permits that skip the guard.

## Addresses (Sepolia)

| | address |
|---|---|
| PopAttestationVerifier | `0xD9E2F407424a7422E195d034ECc4fC932120d96F` |
| PopSafeGuard (attestation verifier) | `0x1e0AD6528e6769508A241b78b73A6F9b1342bb3B` |
| PopSafeSetup | `0x3d4e549F13CCee540884481b35Fd1CA42A9E0707` |
| P256OwnerFactory | `0x99565991Ec5414Ee2d3A2fA48Ab4d92efBd2466e` |
| demo Safe (2-of-4, **test** phone keys) | `0x1399D5F9B91B92EF8220E9328743Ac5F370Ed6d4` |
| SafeL2 1.5.0 / SafeProxyFactory 1.5.0 (canonical) | `0xEdd160fEBBD92E350D4D398fb636302fccd67C7e` / `0x14F2982D601c9458F93bd70B218933A6f8165e7b` |

The demo Safe's issuer is a dev key: X `0xe456d477…8242`, Y `0x08f1c0b3…60e8`. The same key is at `server/data/attest-demo.pem` (gitignored, 0600, derived from `ISSUER_KEY` in `.env.demo`). Point the backend's `SAFE_ATTEST_KEY_FILE` at it, or every spend reverts with `BadAttestation`.

## Run the demo

**A. Chain-only replay (no phones, no server).** This already ran on Sepolia; see `DEPLOYMENTS.md`.

```sh
cd examples/safe/contracts && SALT=$(date +%s) script/sepolia_demo.sh   # reuses deployments/11155111.json; new Safe + spend + guardian no-presence revert
```

**B. Real phones → server → relayer → Sepolia.**

1. Enroll both phones on the server as usual. Read their pubkeys: `sqlite3 server/data/pop.sqlite "select device_id, display_name, '0x'||pubkey from devices"`.
2. Create a Safe for those phones. The demo Safe holds test keys, so real phones would get `UnknownDevice`.
   ```sh
   cd examples/safe/contracts; set -a; . ./.env; set +a     # SAFE_KEY_FILE
   PRIVATE_KEY=$(cat ${SAFE_KEY_FILE/#\~/$HOME}) PUB_A=0x04… PUB_B=0x04… \
   GUARDIAN_1=0x1291992a1BE4e3b37e1fB5423a22dC2379b94FDb GUARDIAN_2=0xD2f5b64C51369E1158cD6ad56d6358407Bc3D3De \
   ISSUER_X=0xe456d477fdff5a857ea08d43beaf5a342675d558321930a44c610b75944d8242 \
   ISSUER_Y=0x08f1c0b3d93980977ff941d64044e361d264759b50082bbe3058f33537ed60e8 \
   DELAY=300 GRACE=600 SALT=$(date +%s) GUARD=0x1e0AD6528e6769508A241b78b73A6F9b1342bb3B \
   SETUP=0x3d4e549F13CCee540884481b35Fd1CA42A9E0707 OWNER_FACTORY=0x99565991Ec5414Ee2d3A2fA48Ab4d92efBd2466e \
   forge script script/CreatePopSafe.s.sol --rpc-url sepolia --broadcast --slow
   cast send <safe> --value 0.002ether --rpc-url sepolia --private-key …
   ```
   Don't broadcast while the ENS example's `ens.sh` runs, because the deployer key is shared.
3. Run the backend, see [`../README.md`](../README.md). The rest of the flow and what it does and doesn't prove are there.

## Tests

```sh
forge build && forge test                                   # 38 pass, fork suite skipped
FORK=1 forge test --match-contract PopSafeForkTest          # 19/19 against Sepolia's canonical Safe 1.5.0
anvil --fork-url https://sepolia.gateway.tenderly.co --hardfork osaka --port 8612 --silent &
RPC=http://127.0.0.1:8612 script/anvil_smoke.sh             # deploy, create, spend, forced revert, hatch
```

## Gas

| path | gas |
|---|---|
| deploy (verifier + guard + setup + owner factory) | ~3.4M (0.006 ETH on Sepolia) |
| spend with POP2 attestation (live tx `0x137acc8f…`) | 157,502 |
| Noir: phone proof A / B / pair (real iPhone fixtures, real bb verifiers) | 4.08M / 4.07M / 3.32M execution |
| Noir: full `execTransaction` (incl. 2x POPCC1, ~+22K) | ~11.96M execution, ~12.43M tx gas (29.9 KB signatures) |
| limits | per-tx cap 16,777,216 (Fusaka), block 60M. Each bb verifier is ~17 KB, under 24 KB |

## ZK team: plugging in the Noir verifier

The adapter is `src/verifiers/NoirPresenceVerifier.sol`. Its `presence` is `abi.encode(Bundle)`:

```solidity
struct Bundle { uint64 notBefore; bytes16 sid; bytes proofA; bytes32[] pubA; bytes proofB; bytes32[] pubB; bytes proofPair; bytes32[] pubPair; bytes ccSigA; bytes ccSigB; }
```

Public inputs, and how they are linked on chain:

| phone proof (A and B, 12) | onchain check |
|---|---|
| 0 `nonce_hi`, 1 `nonce_lo` | `PopCtx.nonce(chainid, safe, safeTxHash, notBefore, sid)` split into 128-bit halves; equal in all three proofs |
| 2 `attempt` | equals pair #2 |
| 3 `role_b` | A = 0, B = 1 |
| 4 `code_commit` | bound by the server's POPCC1 sig (`ccSigA` / `ccSigB`, raw r‖s): P-256 over `sha256("POPCC1" ‖ nonce ‖ u8 attempt ‖ 'A'/'B' ‖ code_commit)` under the pinned issuer, checked with the 0x100 precompile. Else `BadCodeAttest(0/1)` |
| 5..8 `issuer` | = the Safe's (qx hi128, qx lo128, qy hi128, qy lo128) |
| 9 `sr` | A = pair #5 `sr_a`, B = pair #6 `sr_b` |
| 10 `valid_at` | A == B, `notBefore ≤ valid_at ≤ now + 300`, `now ≤ valid_at + MAX_AGE` (default 86,400 s = 24 h) |
| 11 `halfCommit` | A = pair #3 `commit_a`, B = pair #4 `commit_b` |

| pair proof (7) | |
|---|---|
| 0 `nonce_hi`, 1 `nonce_lo`, 2 `attempt`, 3 `commit_a`, 4 `commit_b`, 5 `sr_a`, 6 `sr_b` | proves NEAR and `xa != xb` |

Important: `issuer` here is the Safe's pinned (qx, qy). With the Noir guard, a Safe must be created with `ISSUER_X/Y` = the server's **SBcred3 issuer** key (`server/data/issuer.pem`, published by `GET /v1/config` as `issuer.pub_x` / `pub_y`): X `0x0a0ad09977240bdc4e46a6c38c9faa88ddd24674a06f722e92426d299ecc5bed`, Y `0xbf99508f8f84d3a6f36f9cae47c130310d1830f481c58d2bd0f67e8a3ca2a661`. It signs both the proofs' issuer inputs and POPCC1. **Not** the attest-demo key (`attest-demo.pem`) that the attestation verifier's Safe pins.

Steps:

1. Put the final bb verifiers (`bb write_solidity_verifier -t evm`) in `src/honk/PhoneVerifier.sol` and `PairVerifier.sol`, and give the contracts distinct names. Add `src/honk/*.sol` to `compilation_restrictions` in `foundry.toml` (`via_ir = false, max_optimizer_runs = 1`). The fixtures in `test/fixtures/zk` show the setup.
2. Deploy each verifier's two external libraries, then the linked verifier:
   ```sh
   K=$(cat ~/.enconomy/ens-sepolia.key); R=sepolia
   for L in RelationsLib ZKTranscriptLib; do forge create src/honk/PhoneVerifier.sol:$L --rpc-url $R --private-key $K --broadcast; done
   forge create src/honk/PhoneVerifier.sol:PhoneVerifier --rpc-url $R --private-key $K --broadcast \
     --libraries src/honk/PhoneVerifier.sol:RelationsLib:0x… --libraries src/honk/PhoneVerifier.sol:ZKTranscriptLib:0x…
   # same for PairVerifier.sol
   ```
   `test/NoirRealGas.t.sol::_deployLinked` does the same thing by hand.
3. Deploy the adapter and a new guard. On Sepolia the script defaults to the live PhoneVerifier `0x5b69…a791`, PairVerifier `0xfFA0…3Fd7`, Setup and OwnerFactory, and `MAX_AGE=86400`: `VERIFIER=noir DEPLOY_OUT=deployments/11155111-noir.json PRIVATE_KEY=$K forge script script/Deploy.s.sol --rpc-url sepolia --broadcast --slow`. The output is a new `NoirPresenceVerifier` and a `PopSafeGuard` bound to it.
4. Create a Safe with `GUARD=<noir guard>` and `ISSUER_X/Y` = the SBcred3 issuer. To move an existing Safe instead, use two PoP txs: `initSafe`, then `setGuard`.
5. Check the proofs against the adapter: swap your proofs into `test/fixtures/zk/{A,B,pair}` and run `forge test --match-contract NoirRealGasTest -vv`. Gas must stay under the 16.7M per-tx cap.
6. Relayer: the Noir path isn't wired yet. The server has to return `{not_before, sid, proofA, pubA, proofB, pubB, proofPair, pubPair, ccSigA, ccSigB}` (`ccSig*` = `zk.<role>.code_attest.sig_hex`). The relayer then passes `presence = abi.encode(Bundle)` framed with `u32 len ‖ "POPV"`, in place of `att.tail_hex`. Use `sid` = the 16 raw session-id bytes that PopCtx uses.

Open TODOs (in the file):
- The circuits expose no device key or hash, pairTag or nullifier, so the adapter returns `(0, 0)`. The guard then only requires two device-owning signers, and human uniqueness stays a server claim. Exposing `sha256(pub65)` of both devices (or X hi/lo) as pair public inputs would let the adapter return `(devA, devB)` and bind devices like POP2 does.
- Pin the vk hashes once the pair proof is final.
