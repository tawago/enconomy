# bridge

Laptop watcher: PoP server results -> `MeetResolver` txs on Ethereum Sepolia. Python 3 stdlib + foundry `cast`. Same key as `contracts/script/ens.sh` (`~/.enconomy/ens-sepolia.key`, attester). Runs on the PoP server's laptop and reads its data dir directly (the public https://pop.enconomy.dev is only a tunnel to that same server on :8001).

```sh
cd bridge
./bridge status                      # rpc, resolver, key/attester, zk verifier, registered names + onchain counts, last processed
./bridge run                         # poll every 3 s (once = one pass)
./bridge record alice bob [sid]      # manual; with a sid that has a result.json the real evidence/timeBucket is used
./bridge import-names map.json       # {"<device_id>": "alice"} -> ens_names as registered (hand-mapped, already onchain)
./bridge zk-verify <meetingId> ~/.enconomy/zk/pinned/A/proof ~/.enconomy/zk/pinned/A/public_inputs
```

## What `run` does

For every `<dataDir>/sessions/<sid>/result.json` (written by `server/pop/sessions.py`):

1. `verdict == "NEAR"` only. Devices `A`/`B` -> labels via registered `ens_names` rows (`device_id` only). Skipped with a logged reason: unmapped device, same label, bad label, label not registered.
2. `record(meetingId, keccak(labelA), keccak(labelB), timeBucket, evidence)`, design §5.1:
   - `meetingId = keccak256("enconomy/meet/v1" ‖ bytes16(session_id))`
   - `timeBucket = t0_ms // 3_600_000`
   - `evidence = keccak256(bytes32(transcripts.A.sha256) ‖ bytes32(transcripts.B.sha256))`
   Already onchain (`meetingOf.exists` / `DuplicateMeeting`) counts as done.
3. When `zk.status == "verified"`: for each role, if `proof_<role>_<attempt>.bin` and `public_inputs_<role>_<attempt>.bin` (raw 32-byte words, bb format) sit in the session dir and a phone verifier is configured, `eth_call` then send `verify(bytes,bytes32[])` (~4.26 M gas). Then `markZkVerified(meetingId)`. Skipped if the meeting is already zk/void.

## App ENS claims

The app claims `<label>.enconomy.eth` per device (`POST /v1/device/ens`). `server/pop/ens.py` only stores it: table `ens_names` in `<dataDir>/pop.sqlite` (`popDb` / `POP_DB`). It is the only `device_id -> label` map; `UNIQUE(label)` stops a second claim of a name.

Each pass, before results, every `status = 'pending'` row: `registry.register(label, admin, 0x0, MeetResolver, 0, now + 90 d)`, then `touch(label)` (= `ens.sh claim`). Already registered onchain counts as done. Writes back `status` `registered` (+ `tx`) or `failed` (+ `error`). A failed row can be re-claimed from the app.

Registered rows are the map for step 1. `import-names` seeds devices whose names were registered by hand (`ens.sh claim`): `INSERT OR IGNORE`, status `registered`, no tx.

First run with no state file marks every existing session `preexisting` (not recorded). `--backfill` records them instead.

Nonce: always `pending`, retried on nonce races. On real Sepolia each send first waits while another `ens.sh` / `cast send` / `forge script` runs (shared key).

## Files and config

| | |
|---|---|
| `state.json` | gitignored. Per session: status (`recorded`, `duplicate`, `skipped`, `ignored`, `preexisting`), meetingId, tx, zk txs. Delete an entry to retry a skip. |
| `log.jsonl` | gitignored. One JSON line per action (`ts, action, msg, chain, url, tx, meetingId, labels, firstTime`). No session ids / device names: safe for the web page. |
| `config.json` | optional, see `config.example.json`. |
| `popDb` | server sqlite with `ens_names`, default `<dataDir>/pop.sqlite`. Reads rows, writes status; `import-names` inserts. |
| `../contracts/deployments/sepolia.json` | resolver, attester. |
| `../contracts/deployments/zk-sepolia.json` | `phoneVerifier`, `verifyLog` (win over config.json). With `verifyLog` the verify tx is `VerifyLog.verifyAndLog(phoneVerifier, proof, publicInputs)` (emits `Verified`); else a plain tx to `phoneVerifier.verify`. |

Env overrides: `ETH_RPC`, `ENS_KEY_FILE`, `POP_DATA_DIR`, `POP_DB`, `BRIDGE_STATE`, `BRIDGE_LOG`, `BRIDGE_CONFIG`, `ENS_OUT`, `ZK_OUT`.

## Fork run

```sh
anvil --fork-url https://ethereum-sepolia-rpc.publicnode.com --hardfork osaka --chain-id 11155111 --port 8645 --silent &
cast rpc anvil_setBalance 0x7Dc35E0c67Bd247f61f3cc5053a16E4FC94e8860 0x8AC7230489E80000 --rpc-url http://127.0.0.1:8645
export ETH_RPC=http://127.0.0.1:8645 BRIDGE_STATE=/tmp/fork-state.json BRIDGE_LOG=/tmp/fork-log.jsonl POP_DATA_DIR=/tmp/fakedata
./bridge once --backfill
```

Keep fork state/log separate from the real `state.json` (same resolver address on both).
