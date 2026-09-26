# Option 2: server-trusted credential, Groth16 on BN254

2026-09-26. Prototype runs end to end: circuit, proof, Solidity verifier, gate contract on anvil.
Code: `/private/tmp/claude-501/-Users-takahiro-ogawa-dev-enconomy/3d9dd236-bf59-4c81-91f5-6bb7c5ebc6e3/scratchpad/onchain-zk/opt2-server-credential/`
(`circuits/core.circom`, `opt2a.circom`, `opt2b.circom`, `gen_inputs.js`, `sol/src/PopGate.sol`, `run_anvil.sh`, `bench.js`).

## Idea

The server already checks both P-256 transcript signatures, the attestation and the NEAR verdict. After NEAR it issues a small BN254-friendly "met record" to the phone. The phone proves in Groth16 that it holds a valid record without showing the record. The chain then trusts the server's key, not the phones' hardware keys.

- **2a:** the server signs the record with EdDSA-Poseidon over BabyJubJub. The contract pins the server key.
- **2b:** the server adds the record as a leaf of a Poseidon Merkle tree (depth 20) and posts the root onchain. The proof shows tree membership, like Semaphore.

## Statement

The phone has a long-term holder secret `s` (software secret, not in the Secure Enclave). It sends `hc = Poseidon(1, s)` inside the signed transcript, so the hardware key vouches for `hc` at issuance.

The server keeps a stable pseudonym per device, for example `pid = HMAC(serverKey, device_id)`, reduced to a field element. After NEAR it builds this record:

```
M = Poseidon(2, hc, partnerPid, sessionId, verdict=1, expiry)
```

It returns the fields plus an EdDSA signature (2a), or the leaf index and Merkle path (2b).

| | 2a | 2b |
|---|---|---|
| private | s, partnerPid, sessionId, verdict, expiry, R8x, R8y, S | same, minus the signature, plus path[20], idx[20] |
| public in | Ax, Ay (server key), scope, ctx, now | root, scope, ctx, now |
| public out | nullifier, pairTag | nullifier, pairTag |

What the circuit checks:
- `hc = Poseidon(1, s)` and M is rebuilt from the private fields.
- `verdict == 1`.
- `now <= expiry` (40-bit comparison).
- 2a: the EdDSA signature over M verifies. 2b: M is a leaf under `root`.
- `nullifier = Poseidon(3, s, sessionId)`. Each met record can be used once per holder.
- `pairTag = Poseidon(4, s, partnerPid, scope)`, where `scope = uint160(safe)`. The tag is stable per (holder, partner, Safe). Tags do not link across Safes.
- `ctx = safeTxHash >> 8`. A Groth16 proof is bound to its public inputs, so a proof for one safeTx fails for any other. Tested: changing ctx makes `verifyProof` return false.

What the contract checks (`PopGate2a` / `PopGate2b`):
1. `pairTag` is on the Safe's allowlist. The owner registers it once; the phone computes it offchain.
2. `nullifier` is unused.
3. `now` is within [block.timestamp − 300 s, block.timestamp + 60 s].
4. 2b only: `root` is a known root.
5. The proof verifies with the server key pinned (2a) and `scope = address(this)`.
6. It marks the nullifier as spent. Replay reverts with `spent` (tested).

Both phones can register their own pairTag, so either one can prove.

## Numbers

| | 2a EdDSA | 2b Merkle d=20 | source |
|---|---|---|---|
| constraints | 5,385 | 6,018 | MEASURED (circom 2.1.8) |
| witness wasm | 4.5 MB | 3.7 MB | MEASURED |
| zkey (phone download) | 3.9 MB | 4.1 MB | MEASURED |
| prove on M2, snarkjs in-process (wasm witness + prove) | 617–740 ms (5 runs) | 682–729 ms | MEASURED |
| prove on M2, snarkjs CLI incl. node start | 1.3–1.4 s, peak RSS ~430 MB | 1.4–1.6 s | MEASURED |
| proof | 256 B (8 × 32 B) | 256 B | MEASURED |
| `consume` calldata | 388 B | 420 B (one more word) | MEASURED (2a) |
| `verifyProof` call gas | 228,804 | 222,157 | MEASURED (anvil trace) |
| whole `consume` tx gas | 285,109 | 281,046 | MEASURED (anvil) |
| `postRoot` tx gas | none | 45,576 per root | MEASURED |
| phone prove (rapidsnark + witnesscalc) | ~150–200 ms on 2023–24 flagships, <1 s on older phones | same | ESTIMATE from CITED(https://zkmopro.org/docs/performance): Semaphore-32, a bigger circuit, proves in 143 ms (iPhone 16 Pro) and 166 ms (S23 Ultra) |

Setup used pot18 plus one test contribution. Shipping needs a real phase-2 ceremony for these ~6k-constraint circuits. That ceremony is small, but it is per circuit.

Gotcha: `cast estimate` on the snarkjs verifier reports ~44k gas. That number is wrong. The verifier's pairing staticcall fails quietly at low gas and returns false instead of reverting, so gas estimation settles on a gas limit where the check fails. Use a trace or a real tx.

**It fits in one tx.** A Safe guard cannot take extra arguments in `checkTransaction`. The proof (~420 B) would ride on the tail of the `signatures` bytes, which Safe ignores beyond the owner signatures, or go through a module call. This part is not built (ESTIMATE). Total cost is roughly one normal Safe exec plus ~285k gas.

## What the server learns (privacy)

- **At issuance:** device ids, `hc`, `sessionId`, `pid`, expiry. It knew all of this already, apart from `hc`, which is new.
- **Onchain:** the chain sees nullifier, pairTag, ctx, scope, now. Linking these to a device takes `s`. The server never sees `s`, and the proof is zero-knowledge. So the server cannot tell cryptographically which pair backed which Safe tx.
- **Leaks left:**
  1. Timing. The server knows when each record was issued, and the proof's `now` is public. Few sessions in a window means a small anonymity set. 2b is worse: every root post shows issuance count and timing onchain, and root freshness shrinks the set further.
  2. pairTag is linkable within one Safe on purpose, since the Safe registered it.
  3. Variant "bound": put `H(safeTxHash)` into the POPT session nonce and the record. Then the meeting itself is tied to that exact tx (the current design binds the proof, not the meeting). It costs about one equality constraint, but the server learns device pair → safeTxHash → Safe.

## What a compromised server key can do

- **Mint met records at will.** It can make them for any `hc` or pid, with no meeting and no attestation. The hardware keys give no onchain guarantee in this option. The server key is the whole trust root.
- **Allowlisted gates (the Safe case).** A forged record passes only if the attacker also holds the victim's `s`, because pairTag and nullifier need `s`. So the bypass takes server key + phone secret, or server + a colluding owner phone that asks for a record without meeting. Server compromise alone does not open a Safe gate.
- **Open gates** ("any two enrolled devices met"): unlimited fake passes.
- **Deanonymize past proofs:** no.
- **Block service:** yes. It can refuse to issue (DoS), and in 2b it can withhold roots or paths.
- **2a revocation:** only by rotating the key, which kills every credential. Forgeries leave no trace.
- **2b:** every leaf goes through a public root. Issuance is at least countable and auditable against the server's session log, and a bad batch can be revoked by dropping its root. Forged leaves still look normal.

## 2a vs 2b

- 2a: no onchain issuance step, and a credential works right away. Anonymity set = all unexpired records the key signed. It is the simpler option.
- 2b: costs one ~46k-gas post per batch, and the holder waits for the next root. In return you get revocation, public counts, and no signature in the circuit.
- They cost the same to verify. I'd pick 2a for the hackathon and 2b if auditability matters.

## Missing to ship

1. Server endpoint: take `hc` in the transcript, issue M + EdDSA sig (circomlibjs/`babyjubjub` port in Python), assign pid.
2. Phone prover: mopro + rapidsnark with the 4 MB zkey and a native witness generator. Store `s` encrypted under the hardware key.
3. Safe guard that parses the proof from the signatures tail. Nullifier storage, chain id in scope (`scope = keccak(chainid, safe) >> 8`).
4. Phase-2 ceremony.
5. Decide on the bound variant (server learns tx) vs detached (proof bound, meeting not).
6. Optional: expose a distance bucket or thresholds in M and check them against a public policy (a few constraints).

## Review (soundness)

Adversarial pass, 2026-09-26. Code read: `circuits/core.circom`, `opt2a/b.circom`, `sol/src/PopGate.sol`, `gen_inputs.js`.

1. **Holder side is bound to `s`, not to a hardware key (major).** The record and pairTag carry `partnerPid` but no holder pid. `s` is a software secret. So the proof really says "partner B's device met *some* enrolled device that knows `s`". Anyone holding `s` (cloud backup, malware, or B itself if it ever learns `s`) plus any enrolled device X can meet B and pass as A. With B colluding, B's second phone is enough: one person posing as two. Fix: server pins `hc` to one device at enrollment (reject `hc` from any other key), and add holder pid to M.
2. **`hc` is not in the transcript today (minor).** POPT v2 (`docs/pop-transcript-v2.md`) has no holder field. The existing binding is SBcred3 `holder_commit` at enrollment (`server/pop/issuer.py`), which is a P-256-field commitment, not `Poseidon(1,s)`. Either add a field or bind `hc` at enrollment. Enrollment-binding also fixes #1.
3. **2b: server controls the allowlist (major, prototype bug).** `PopGate2b.addPair` is `require(msg.sender == issuer)`. The issuer is the server's hot key. A compromised server adds its own pairTag and mints a leaf, so it opens every 2b gate alone. This contradicts "server compromise alone does not open a Safe gate". 2a has it right (owner only).
4. **One meeting = many spends (major).** `spent` is per gate contract and the nullifier has no scope. One record works once at every gate/Safe the holder is on, and on every chain (4801 and 480), until expiry. Both phones also get their own nullifier per session, so one meeting authorizes two txs. The note's "once per holder" is only true per gate. If the policy is "one meeting, one tx", use a global nullifier registry, or put `scope` in the nullifier and accept per-Safe reuse knowingly.
5. **Detached mode lets the holder bank records (major).** The 300 s window checks proof time, not meeting time. Expiry is set by the server (prototype: +3600 s). A holder can meet B several times, keep the records, and later sign txs with B absent and unaware. B never consents to a specific tx. Needs a short expiry (e.g. 120 s after meeting) or the bound variant.
6. **Stable pairTag enables intersection deanonymization by the server (major, privacy).** Each Safe tx shows the same pairTag and a public `now`. The server knows which pairs had unexpired records at each moment. With k txs it intersects those sets, and with short expiries (needed for #5) the set shrinks to one pair fast. The note lists timing but treats it as one-shot. Mitigation: long expiry (which conflicts with #5), or no stable tag (put the allowlist in a Merkle root and prove membership, costs ~20 Poseidons).
7. **Standalone `consume` can be front-run (minor, prototype).** Anyone can copy the proof from the mempool and call `consume` first, burning the nullifier without executing the Safe tx. It is harmless once inside `checkTransaction`, since the guard derives `safeTxHash` itself. Don't ship the standalone form.

Checked and fine: `ctx = safeTxHash>>8` (248-bit binding; safeTxHash already covers chainid + Safe); Groth16 malleability is blocked by the nullifier; snarkjs verifier range-checks public inputs; depth-fixed Merkle with arity-2 nodes vs arity-6 leaf has no level confusion; server can't compute pairTag/nullifier without `s`.

Verdict: the crypto is sound for "server says a NEAR meeting happened". The gaps are in what gets bound: the holder's device (#1), who controls the allowlist (#3), and how often and when a record can be spent (#4, #5). Fix those before claiming properties (1) and (3).

## Review (numbers)

Re-checked 2026-09-26 on the same M2.

**Confirmed (re-MEASURED):**
- Constraints: 5,385 (2a) and 6,018 (2b), from `snarkjs r1cs info`.
- zkey: 3.9 MB and 4.1 MB.
- Gas on a fresh anvil: `verifyProof` 228,804 (trace), `consume` 285,109 (2a) and 281,046 (2b), `postRoot` 45,576.
- `consume` calldata: 388 B.
- A replay reverts with `spent`. A wrong safeTxHash reverts with `proof` (checked with `cast call`). `run_anvil.sh` itself only prints a JSONDecodeError on these two lines and never shows the revert reason.
- The `cast estimate` ≈44k gotcha is real.

**Issues:**
1. **One meeting is good for two txs, and for about an hour (major).**
   - The nullifier is `H(3, s, sessionId)`, so each phone gets its own. When a Safe allowlists both phones' pairTags, as the note suggests ("either one can prove"), one meeting authorizes two txs.
   - The 300 s window checks the proof's `now`, not when the meeting happened. `gen_inputs.js` sets `expiry = now + 3600`, so any tx within an hour of the meeting passes.
   - Fix: make the nullifier per session, e.g. `H(sessionId)` or `H(pairSecret, sessionId)`. Also set a short expiry, or take the bound variant.
2. **The prover side is a software secret, not hardware (major).**
   - Nothing pins `hc` to a device. The server takes whatever `hc` a transcript carries, and the record does not include the prover's own pid.
   - So anyone with a copy of `s` (backup, malware), any enrolled device, and a real meeting with partner P gets a valid record for the victim's pairTag.
   - The claim "the hardware key vouches for hc" holds for one transcript only.
   - Fix: register `hc` once per device at enrollment and refuse any other `hc`, or put the prover's pid in M and pairTag.
3. **In the 2b prototype, the server runs the allowlist (minor).** `PopGate2b.addPair` requires `msg.sender == issuer`, the server key. That contradicts "the owner registers it" and gives a compromised server one more lever.
4. **Scope comes from the gate address (minor).** Scope is `address(this)`, the gate. One guard shared by several Safes needs `scope = msg.sender`, meaning the Safe, plus the chain id.
5. **2b prove time is a best case (minor).** My re-run: 2a 532–777 ms, 2b 804–1,515 ms (5 runs each, other jobs running). The note's 0.68–0.73 s for 2b is a quiet-machine number. Phones are unaffected: the ESTIMATE of ~150–200 ms is reasonable. Mopro's Semaphore-32 numbers are rapidsnark 143 / 166 ms plus witness 10–22 ms, CITED(https://zkmopro.org/docs/performance). That page gives no constraint count, so "bigger circuit" is unverified.
6. **Cost is not converted to money (minor).**
   - The note gives no L1 data fee for World Chain (OP stack) for the ~0.4 KB of proof calldata, and no USD figure.
   - "Safe exec + ~285k" counts the 21k base tx twice. The extra on top of a Safe exec is about 260k (verifier 229k, plus about 22k for the nullifier SSTORE, plus calldata).
