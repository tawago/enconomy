# ENS meetings contracts

`MeetResolver` (ENSIP-10 resolver for `enconomy.eth` and every `<label>.enconomy.eth`) plus bash+cast ops for ENSv2 Sepolia. Its own Foundry project: nothing here reads the core's `contracts/`. Spec: `docs/ens-meetings-design.md` §5.

- `src/MeetResolver.sol` — counters keyed on registry `resource`, existence-gated reads, ERC-7996 declared (UR calls us directly).
- `abi/ens/*.json` — ENS ABIs from contracts-v2 `71a3b733` (see `abi/ens/SOURCE.txt`).
- `out-abi/MeetResolver.json` — our ABI (`script/export_abi.sh`).
- `script/ens.sh` — bootstrap + ops. Idempotent: reads chain state before each write.
- `deployments/sepolia.json` — the live addresses. Written by the original bootstrap.
- `deployments/zk-sepolia.json` — a copy of `contracts/deployments/zk-sepolia.json`, so the bridge reads `phoneVerifier` and `verifyLog` from here. The core keeps the original, and a redeploy there has to be copied over by hand.

Single key: admin == hot == attester, key file `~/.enconomy/ens-sepolia.key` (override `ENS_KEY_FILE`). Never commit it.

## Do not rerun bootstrap

**Do not rerun bootstrap, addresses come from `deployments/sepolia.json`.**

`ens.sh bootstrap` predicts the `MeetResolver` address from the bytecode of a fresh build. The metadata hash at the end of that bytecode changes with the build settings, and this move changed it: the new project has no `safe-smart-account` remapping. Bootstrap would then see no code at the predicted address, deploy a new resolver and repoint the 2LD. The prediction already missed the deployed `0xfc30…1346` before the move (see the 2026-09-27 caveat in `../web/README.md`).

Checked at the move, old project against new, same compiler: the runtime code is byte-identical up to the CBOR metadata tail, and the creation code differs only in the 32 hash bytes inside that tail.

To change the site, send `setSite` directly: `cast send <meetResolver> 'setSite(string,string)' "ETHGlobal Tokyo 2026" <url>`.

## Live addresses (Sepolia)

| | address |
|---|---|
| MeetResolver | `0xfc300a640ccdEFF0e61f7875D55A9Cd22eb51346` |
| UserRegistry | `0x3dC7A13410B3C2B3dA8029BCfA60E358E3AA59B1` |
| admin, hot, attester | `0x7Dc35E0c67Bd247f61f3cc5053a16E4FC94e8860` |
| deploy block | 11786877 |

## Tests

```sh
git submodule update --init lib/forge-std
forge test     # test/MeetResolver.t.sol, a mock registry, no chain
```

## Env

| var | default |
|---|---|
| `ETH_RPC` | `https://ethereum-sepolia-rpc.publicnode.com` |
| `ENS_KEY_FILE` | `~/.enconomy/ens-sepolia.key` |
| `ENS_PARENT` | `enconomy.eth` |
| `ENS_EVENT_NAME` | `ETHGlobal Tokyo 2026` |
| `ENS_SITE_URL` | `https://ens.enconomy.dev/` |
| `ENS_OUT` | `deployments/sepolia.json` |

## Real Sepolia

```sh
cd examples/ens-meetings/contracts
./script/ens.sh addr                 # fund this address (0.1+ Sepolia ETH is plenty)

# demo pre-seed / Plan B (no server)
./script/ens.sh claim alice          # register (roles 0, owner = our key, 90 d) + touch
./script/ens.sh record alice bob     # random session id; prints meetingId + firstTime
./script/ens.sh zk <meetingId>
./script/ens.sh void <meetingId>
./script/ens.sh status alice.enconomy.eth   # all keys through the Universal Resolver
```

## Fork smoke

Only on a local fork, where bootstrap can't touch the real 2LD.

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
- The key is shared with the Safe deploys in `contracts/`: don't send from both at once.
