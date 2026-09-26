# bridge

Laptop watcher: PoP server results -> `MeetResolver` txs on Ethereum Sepolia. Python 3 stdlib + foundry `cast`. Same key as `contracts/script/ens.sh` (`~/.enconomy/ens-sepolia.key`, attester).

```sh
cd bridge
cp names.example.json names.json     # fill: device_id (or display_name) -> label
./bridge status                      # rpc, resolver, key/attester, zk verifier, names + onchain counts, last processed
./bridge run                         # poll every 3 s (once = one pass)
./bridge record alice bob [sid]      # manual; with a sid that has a result.json the real evidence/timeBucket is used
./bridge zk-verify <meetingId> ~/.enconomy/zk/pinned/A/proof ~/.enconomy/zk/pinned/A/public_inputs
```

## What `run` does

For every `<dataDir>/sessions/<sid>/result.json` (written by `server/pop/sessions.py`):

1. `verdict == "NEAR"` only. Devices `A`/`B` -> labels via `names.json` (`device_id` first, then `display_name`). Skipped with a logged reason: unmapped device, same label, bad label, label not registered.
2. `record(meetingId, keccak(labelA), keccak(labelB), timeBucket, evidence)`, design §5.1:
   - `meetingId = keccak256("enconomy/meet/v1" ‖ bytes16(session_id))`
   - `timeBucket = t0_ms // 3_600_000`
   - `evidence = keccak256(bytes32(transcripts.A.sha256) ‖ bytes32(transcripts.B.sha256))`
   Already onchain (`meetingOf.exists` / `DuplicateMeeting`) counts as done.
3. When `zk.status == "verified"`: for each role, if `proof_<role>_<attempt>.bin` and `public_inputs_<role>_<attempt>.bin` (raw 32-byte words, bb format) sit in the session dir and a phone verifier is configured, `eth_call` then send `verify(bytes,bytes32[])` (~4.26 M gas). Then `markZkVerified(meetingId)`. Skipped if the meeting is already zk/void.

First run with no state file marks every existing session `preexisting` (not recorded). `--backfill` records them instead.

Nonce: always `pending`, retried on nonce races. On real Sepolia each send first waits while another `ens.sh` / `cast send` / `forge script` runs (shared key).

## Files and config

| | |
|---|---|
| `names.json` | gitignored. `{"<device_id>": "alice", "Pixel 6": "bob"}`; `_`-keys ignored. Device ids: `devices.A.device_id` in any `result.json`, or the server's `devices` table. |
| `state.json` | gitignored. Per session: status (`recorded`, `duplicate`, `skipped`, `ignored`, `preexisting`), meetingId, tx, zk txs. Delete an entry to retry a skip. |
| `log.jsonl` | gitignored. One JSON line per action (`ts, action, msg, chain, url, tx, meetingId, labels, firstTime`). No session ids / device names: safe for the web page. |
| `config.json` | optional, see `config.example.json`. |
| `../contracts/deployments/sepolia.json` | resolver, attester. |
| `../contracts/deployments/zk-sepolia.json` | `phoneVerifier`, `verifyLog` (win over config.json). With `verifyLog` the verify tx is `VerifyLog.verifyAndLog(phoneVerifier, proof, publicInputs)` (emits `Verified`); else a plain tx to `phoneVerifier.verify`. |

Env overrides: `ETH_RPC`, `ENS_KEY_FILE`, `POP_DATA_DIR`, `BRIDGE_STATE`, `BRIDGE_LOG`, `BRIDGE_NAMES`, `BRIDGE_CONFIG`, `ENS_OUT`, `ZK_OUT`.

## Fork run

```sh
anvil --fork-url https://ethereum-sepolia-rpc.publicnode.com --hardfork osaka --chain-id 11155111 --port 8645 --silent &
cast rpc anvil_setBalance 0x7Dc35E0c67Bd247f61f3cc5053a16E4FC94e8860 0x8AC7230489E80000 --rpc-url http://127.0.0.1:8645
export ETH_RPC=http://127.0.0.1:8645 BRIDGE_STATE=/tmp/fork-state.json BRIDGE_LOG=/tmp/fork-log.jsonl POP_DATA_DIR=/tmp/fakedata
./bridge once --backfill
```

Keep fork state/log separate from the real `state.json` (same resolver address on both).
