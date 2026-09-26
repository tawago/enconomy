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
| `ENS_SITE_URL` | `https://ens.enconomy.dev/` (changing it later = one `setSite` tx on rerun, same address; but see the bytecode-drift caveat in `web/README.md`) |
| `ENS_OUT` | `deployments/sepolia.json` |

## Real Sepolia

```sh
cd contracts
./script/ens.sh addr                 # fund this address (0.1+ Sepolia ETH is plenty)
cast call 0xabe76f6c8dfced81aa5a2bb8034202a7136b94ca "isAvailable(string)(bool)" enconomy \
  --rpc-url https://ethereum-sepolia-rpc.publicnode.com       # must be true (or already ours)
ENS_SITE_URL=https://ens.enconomy.dev/ ./script/ens.sh bootstrap   # ~9 txs, waits ~60 s commit->reveal; rerun = setSite only
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

A Safe 1.5.0 (SafeL2) that only moves money when its two phone owners are physically together. Chain facts: `PREFLIGHT.md`. Addresses and demo txs: `DEPLOYMENTS.md`.

## Pieces

```
phone A + phone B ── PoP session (context kind "safe-tx", ctx_hash = safeTxHash) ──► server/
   each phone at Confirm: POST /v1/session/<sid>/safe/owner-sig  (P-256 over "pop-safe-owner-v1" ‖ safeTxHash)
server/  NEAR ─► GET /v1/session/<sid>/attestation ─► att.tail_hex (172 B POP2, "pop-safe-v2", signed by data/attest*.pem)
relayer/ relay.mjs <sid> ─► checks hash/nonce/guard/devices on chain ─► execTransaction(…, ownerSigs ‖ POP2 ‖ 000000ac ‖ "POPV")
Safe ─► PopSafeGuard.checkTransaction ─► IPopPresenceVerifier.verifyPresence(safe, safeTxHash, qx, qy, presence)
```

- `src/PopSafeGuard.sol`: the tx guard, plus `PopSafeSetup`, which sets the guard inside `Safe.setup`. Each Safe has its own issuer key (qx, qy) and a device registry (`sha256(pub65)` → owner). Escape hatch: `announce`, wait `delay`, then execute within `grace`. Only recovery calls are allowed there. `cancel`/`cancelAll` exist too. The guard refuses delegatecall, `gasPrice > 0`, `enableModule`, `setFallbackHandler`, `setModuleGuard`, threshold < 2, and `setGuard` to a guard that hasn't run `initSafe`.
- `src/P256Owner.sol`: an EIP-1271 owner for one phone P-256 key (uses the `0x100` precompile), plus a CREATE2 factory. The phone signs `"pop-safe-owner-v1" ‖ safeTxHash` with SHA256withECDSA, as raw r‖s. High s is accepted.
- `src/interfaces/IPopPresenceVerifier.sol`: `verifyPresence(safe, safeTxHash, qx, qy, presence) → (devA, devB)`. It reverts if the proof is invalid. The verifier is **immutable per guard**. To switch verifiers, deploy a new guard, run a PoP tx `newGuard.initSafe(...)`, then a PoP tx `setGuard(newGuard)`. No timelock is needed, since both steps need presence.
- `src/verifiers/PopAttestationVerifier.sol`: checks the server's P-256 `pop-safe-v2` attestation (spec 01 §8.2). **Live now.**
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

The demo Safe's issuer is a dev key: X `0xe456d477…8242`, Y `0x08f1c0b3…60e8`. The same key is at `server/data/attest-demo.pem` (gitignored, 0600, derived from `ISSUER_KEY` in `.env.demo`). The server's default `data/attest.pem` is a **different** key, so run the server with `POP_ATTEST_KEY_FILE=data/attest-demo.pem`. Otherwise every spend reverts with `BadAttestation`.

## Run the demo

**A. Chain-only replay (no phones, no server).** This already ran on Sepolia; see `DEPLOYMENTS.md`.

```sh
cd contracts && SALT=$(date +%s) script/sepolia_demo.sh   # reuses deployments/11155111.json; new Safe + spend + guardian no-presence revert
```

**B. Real phones → server → relayer → Sepolia.**

1. Enroll both phones on the server as usual. Read their pubkeys: `sqlite3 server/data/pop.sqlite "select device_id, display_name, '0x'||pubkey from devices"`.
2. Create a Safe for those phones. The demo Safe holds test keys, so real phones would get `UnknownDevice`.
   ```sh
   cd contracts; set -a; . ./.env; set +a     # SAFE_KEY_FILE
   PRIVATE_KEY=$(cat ${SAFE_KEY_FILE/#\~/$HOME}) PUB_A=0x04… PUB_B=0x04… \
   GUARDIAN_1=0x1291992a1BE4e3b37e1fB5423a22dC2379b94FDb GUARDIAN_2=0xD2f5b64C51369E1158cD6ad56d6358407Bc3D3De \
   ISSUER_X=0xe456d477fdff5a857ea08d43beaf5a342675d558321930a44c610b75944d8242 \
   ISSUER_Y=0x08f1c0b3d93980977ff941d64044e361d264759b50082bbe3058f33537ed60e8 \
   DELAY=300 GRACE=600 SALT=$(date +%s) GUARD=0x1e0AD6528e6769508A241b78b73A6F9b1342bb3B \
   SETUP=0x3d4e549F13CCee540884481b35Fd1CA42A9E0707 OWNER_FACTORY=0x99565991Ec5414Ee2d3A2fA48Ab4d92efBd2466e \
   forge script script/CreatePopSafe.s.sol --rpc-url sepolia --broadcast --slow
   cast send <safe> --value 0.002ether --rpc-url sepolia --private-key …
   ```
   Don't broadcast while `ens.sh` runs, because the deployer key is shared.
3. Start the server: `cd server && POP_ATTEST_KEY_FILE=data/attest-demo.pem POP_CHAIN_ID=11155111 POP_UNATTESTED_ALLOW=<iphone device_ids> uv run python -m pop`. `GET /v1/config` → `attest.qx/qy` must equal ISSUER_X/Y.
4. The app creates a session with `context = {kind: "safe-tx", chain_id: 11155111, consumer: <safe lowercase>, ctx_hash: safeTxHash, safe_tx: {to, value, data, operation, safe_tx_gas, base_gas, gas_price, gas_token, refund_receiver, nonce}}`. The allowlist accepts a native transfer, or Sepolia USDC `transfer`. Each phone posts its owner sig at Confirm, and then they run the PoP session.
5. Relay:
   ```sh
   cd relayer && npm ci
   RELAYER_PK=0x… EXPECT_SAFE=<safe> POP_SERVER_URL=http://127.0.0.1:8000 node relay.mjs <sid> --wait
   # or keep it running: RELAYER_PK=… ./watch.sh   (polls server/data/pop.sqlite every 1 s)
   ```
   The output is one JSON line with `status`, `tx_hash` and an Etherscan link. Refusals come back as short user-facing texts (`TEXT` in `relay.mjs`).

The server only signs `pop-safe-v2` when both humans have **production** World ID (`nonprod_humans` otherwise). It also needs NEAR, both owner sigs, and attested devices, or devices listed in `POP_UNATTESTED_ALLOW`. The attestation lives 15 min (`POP_ATT_TTL_S`).

Recovery: `script/Recover.s.sol` (`MODE=announce`, wait `DELAY`, then `MODE=exec`). The guardian keys are in `.env.guardians`. The hatch can remove the guard, reinstall a phone, or rotate the issuer.

## Tests

```sh
forge build && forge test                                   # 37 pass, fork suite skipped
FORK=1 forge test --match-contract PopSafeForkTest          # 19/19 against Sepolia's canonical Safe 1.5.0
anvil --fork-url https://sepolia.gateway.tenderly.co --hardfork osaka --port 8612 --silent &
RPC=http://127.0.0.1:8612 script/anvil_smoke.sh             # deploy, create, spend, forced revert, hatch
RPC=http://127.0.0.1:8612 ../relayer/test/dryrun.sh         # real server code → relayer → fork
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

1. Put the final bb verifiers (`bb write_solidity_verifier -t evm`) in `contracts/src/honk/PhoneVerifier.sol` and `PairVerifier.sol`, and give the contracts distinct names. Add `src/honk/*.sol` to `compilation_restrictions` in `foundry.toml` (`via_ir = false, max_optimizer_runs = 1`). The fixtures in `test/fixtures/zk` show the setup.
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
