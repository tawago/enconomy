# bridge

Presence records -> `MeetResolver` txs on Ethereum Sepolia, plus a small CLI. It works from this example's own `ens.sqlite`, and asks the core for one thing: the public ZK bundle over HTTP. Sends with foundry `cast`, using the same key as `contracts/script/ens.sh` (`~/.enconomy/ens-sepolia.key`, attester).

It isn't a separate process anymore. The backend's worker thread calls it after each claim, each new record and at startup, so there is nothing to poll and the shared key sends serially.

```sh
bridge/bridge status                  # rpc, resolver, key/attester, zk verifier, names + onchain counts, record counts
bridge/bridge run                     # prints how to start the backend, which runs the worker
bridge/bridge record alice bob [sid]  # manual; with a sid in presence_records the real evidence and timeBucket are used
bridge/bridge zk-verify <meetingId> <proof> <public_inputs>   # raw files, 32-byte words
bridge/bridge import-names <old core sqlite> [ens.sqlite]     # same as python -m backend.import_names
```

The wrapper runs from the example root, so give relative paths from there.

## What a pass does

1. Pending claims: `register` then `touch`, see the example README.
2. Each undone record in `presence_records`. Non-NEAR is marked `ignored` and never sends anything.
3. Device ids `A`/`B` -> labels through registered `ens_names` rows. Skipped with a stored reason: unmapped device, same label, bad label, label not registered. A skipped record stays undone, so it records on a later pass, right after the missing claim for instance.
4. `record(meetingId, keccak(labelA), keccak(labelB), timeBucket, evidence)`, all from the signed body. These formulas don't change, `tests/test_bridge.py` pins them against values from real `cast`:
   - `meetingId = keccak256("enconomy/meet/v1" ‖ bytes16(session_id))`
   - `timeBucket = t0_ms // 3_600_000`
   - `evidence = keccak256(bytes32(transcripts.A.sha256) ‖ bytes32(transcripts.B.sha256))`

   Already on chain (`meetingOf.exists` / `DuplicateMeeting`) counts as done. Any other revert from the preflight call is a skip with its name.
5. When the signed `zk.status` is `verified`, and the meeting isn't zk or void yet: with a phone verifier configured, `GET {ENS_CORE_URL}/v1/session/{sid}/zk/bundle`, then for each role `eth_call` and send `verify(bytes,bytes32[])` (about 4.26 M gas). Then `markZkVerified(meetingId)`.

## ZK rules

The bundle is public and unsigned, so the signed record decides what counts.

| Bundle | What happens |
|---|---|
| Each proof's sha256 equals `proof_sha256` in the record, inputs equal the record's `public_inputs` | Verify, then mark |
| Anything differs, or it's for another session | **Refused**: no verify tx, no mark, reason stored, record stays undone. No proof goes if any is wrong |
| 404, the bundle isn't out | **Verify skipped with a logged reason, and zk is still marked** |
| Core has no proof file for a role | That role's verify skipped, logged, still marked |
| Network error, or another HTTP status | Nothing marked, reason stored, retried on a later pass |
| Verifier's `eth_call` says no | Not sent, logged, still marked. The manual `zk-verify` stops here instead |

The 404 row needs saying. The bundle is 404 until the **pair** proof verifies, while `zk.status` is `verified` once both **phone** proofs do. The old bridge read proof files directly and could verify at that point. This one can't, so a record delivered between those two moments gets marked without an on-chain verify, and a later redelivery won't add one because the meeting is done. For the tx, deliver the record after the pair proof finishes or run `zk-verify` by hand. `markZkVerified` means "the core verified the proofs", and that has always been its meaning.

## Retries

No timer. A record a chain or network error left undone goes again on the next wake: any claim, any new record, a redelivery of that record, or a restart. Each verify tx is stored as it's sent, so a failure on B doesn't resend A.

## What changed from the old watcher

- It used to run beside the core and read its session files and sqlite. Those reads are gone: the app delivers records to `POST /v1/presence`.
- `state.json` is gone. Per-session status lives in `presence_records`: `status`, `reason`, `meeting_id`, `labels`, `tx`, `first_time`, `time_bucket`, `gas`, `zk_done`, `verify_tx`, `zk_tx`. Clear `status` and wake the worker to retry by hand.
- No first-run `preexisting` marking and no `--backfill`. Intake has no history: a session counts once its record is delivered, whenever that is. To record an old one, deliver its record.
- `once` is gone, the backend does it. `run` only explains that.
- `import-names` now takes an old core sqlite. The JSON map form is gone, since those rows are in that database's `ens_names`.

## Files and config

| | |
|---|---|
| `log.jsonl` | gitignored. One JSON line per action (`ts, action, msg, chain, url, tx, meetingId, labels, firstTime`). No session or device ids: safe to publish. |
| `config.json` | optional, gitignored, see `config.example.json`. |
| `../data/ens.sqlite` | names and records. |
| `../contracts/deployments/sepolia.json` | resolver, registry, parent. |
| `../contracts/deployments/zk-sepolia.json` | `phoneVerifier`, `verifyLog` (win over config.json). With `verifyLog` the verify tx is `VerifyLog.verifyAndLog(phoneVerifier, proof, publicInputs)`, which emits `Verified`. Else a plain tx to `phoneVerifier.verify`. |

Env: `ETH_RPC`, `ENS_KEY_FILE`, `ENS_DB`, `ENS_DEPLOYMENTS`, `ENS_ZK_DEPLOYMENTS`, `ENS_CORE_URL`, `BRIDGE_LOG`, `BRIDGE_CONFIG`.

Nonce: always `pending`, retried on nonce races. On real Sepolia each send first waits while another `ens.sh` / `cast send` / `forge script` runs, since they can share the key. A CLI `record` beside a running backend counts as one of those.

## Fork run

```sh
anvil --fork-url https://ethereum-sepolia-rpc.publicnode.com --hardfork osaka --chain-id 11155111 --port 8645 --silent &
cast rpc anvil_setBalance 0x7Dc35E0c67Bd247f61f3cc5053a16E4FC94e8860 0x8AC7230489E80000 --rpc-url http://127.0.0.1:8645
export ETH_RPC=http://127.0.0.1:8645 ENS_DB=/tmp/fork-ens.sqlite BRIDGE_LOG=/tmp/fork-log.jsonl
bridge/bridge status
```

Keep fork data apart from the real `ens.sqlite`: same resolver address on both.
