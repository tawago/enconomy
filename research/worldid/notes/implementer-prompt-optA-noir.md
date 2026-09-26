# Prompt for the app/server implementer: ZK moves to option A on Noir

Decision (2026-09-26): keep **option A** (audio rule proven inside the proof) but move it from **circom + Spartan2/Hyrax (T-256)** to **Noir + Barretenberg UltraHonk (BN254)**, so a contract (Safe guard on World Chain Sepolia 4801) can verify it. Spartan2 has no EVM verifier; this is the only reason for the move.

## Why (measured, M2, real fixture 180ca04b_48k)

- Full option A statement ported to Noir, runs on real fixtures both roles, 9/9 tampers rejected per role.
- 972,858 gates (2^20, 93% full). circom was 1,228,446 constraints.
- Prove 8.9–11 s (8 threads), ~1.6 GB peak. Proof 10.3 KB + 12 public fields.
- Onchain verify: 2.73M gas per phone proof, 2.23M pair proof, ~7.7M per session (~$1.4 on L1 today, ~$0.02 on World Chain).
- Phone estimate (not run yet): iPhone Pro 6–14 s, flagship Android 20–25 s, mid Android 30–45 s. Needs 6 GB+ phones; iOS needs `com.apple.developer.kernel.increased-memory-limit`.
- Details: `research/worldid/notes/onchain-zk/optA-noir.md`. Circuits and scripts: `research/worldid/prototypes/optA-noir/` (`noir/phone`, `noir/pair`, `noir/oalib`, `gen_inputs.py`, `tamper.py`, `run.sh`, `gas.sh`, `forge/`). Toolchain: nargo 1.0.0-beta.22, bb 5.0.0-nightly.20260522.

## What changes for you

1. **Hashes: Poseidon7 over P-256 → Poseidon2 over BN254** (bb blackbox permutation, t = 4, sponge rate 3). Exact definitions are in `noir/oalib/src` (`leaf_hash`, `node_hash`, `code_commitment`, sponge tags). Match them bit for bit.
   - `rec_root` (app computes, transcript signs, server checks): same tree shape (1,024-sample leaves, 4-ary, depth 4), new hash. Must be a canonical BN254 element.
   - `code_commit`: Poseidon2 commitment over the private int8 templates (onchain variant).
   - `halfCommit`: Poseidon2 over the same values as before.
   - Credential `holder_commit`: Poseidon2_BN254(holder_secret).
   - Server: port these hashes in Python with shared test vectors from the Noir code; app: Kotlin common code. Pin vectors in tests on both sides.
2. **Templates become private.** The 48k template values are no longer public inputs (public costs 129M gas). The proof exposes only `code_commit`. The **server must attest the code commitment** (sign `(nonce, attempt, role, code_commit)` or equivalent) so the verifier knows the codes came from the real server.
3. **Phone prover swap:** `app/prover` (Rust Spartan2 crate, JNI / xcframework) → Barretenberg UltraHonk. Options: mopro's Noir support, Swoir (iOS), or bb built for iOS/Android. Witness from nargo's ACVM (Noir compiled program JSON). No per-circuit 470 MB proving key anymore; bb needs the universal CRS for 2^20 (check the file size and ship/download it once). Keep the "check before prove" behavior.
4. **Server verifier:** `popprover verify` → `bb verify` with the pinned vk hash (or rely on the onchain verifier). Replace `VK_PINS` / `oa2t_s48|s44` circuit ids with the Noir circuit ids. 44.1 kHz needs its own compiled circuit (same code, different constants), like s44 today.
5. **ECDSA low-S:** bb rejects high-S signatures. Normalize `s → n − s` before proving (no key needed). Secure Enclave returns high-S about half the time.
6. **Nonce bound to the onchain context:** `session_nonce` derived from `safeTxHash` + chainId + Safe address before the meeting (PopCtx, `docs/worldid/01` §5). Needed whatever the ZK choice.

## What stays

Audio run, pairing, commit-then-reveal, transcript byte layout (only the hash values inside change), Secure Enclave / Keystore signing, enrollment and attestation, server verdict logic.

## Constraints and traps

- **No headroom.** The plain circuit has ~75k gates left under 2^20. Adding the POPC commit-signature check measures 1,049,713 → spills to 2^21 (double cost). If you add any check, use the **FIR shortcut** (`phone_opt`: prover supplies FIR outputs, circuit checks one random evaluation): 855,525 gates, 932,379 with the POPC check, ~15–20% faster, 1.32 GB. `phone_opt` proves/verifies but has no tamper tests yet — add them.
- bb is a nightly; pin exact nargo/bb versions in both app and server builds.
- Nothing has run on a real phone yet. First milestone: prove the real fixture on the iPhone and the Android, record time and peak memory.
- Trust caveat unchanged: the proof only adds security if capture, `rec_root` and `p_self` come from something more trusted than the app's arrival code (attested app).

## Acceptance

1. Python + Kotlin Poseidon2 vectors equal the Noir `oalib` outputs (leaf, node, rec_root, code_commit, halfCommit, holder_commit).
2. App produces a witness for fixture 180ca04b_48k A and B; `nargo execute` succeeds; bb proves and verifies on both phones; time + memory logged.
3. Server `bb verify` accepts the phone proofs and rejects a tampered transcript byte, wrong code_commit attestation, wrong nonce.
4. `forge test` in `research/worldid/prototypes/optA-noir/forge` passes against proofs produced by the app.
