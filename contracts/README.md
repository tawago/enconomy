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
