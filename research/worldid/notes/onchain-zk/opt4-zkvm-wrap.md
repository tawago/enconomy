# Option 4: wrap the Spartan2/Hyrax proofs in a zkVM, verify Groth16 onchain

2026-09-26. Scratch: `/private/tmp/claude-501/.../scratchpad/onchain-zk/opt4-zkvm-wrap/` (`vcount/`, `rvmul/`, `cycles.py`, `sp1-contracts/`).

## Short answer

One tx, and not an expensive one. The heavy part is offchain.

- Phones make their Spartan2 proofs as today.
- An aggregator (our server, or anyone) runs the Spartan2 verifier inside SP1 or RISC Zero and gets back one Groth16 proof of about 260 B.
- A Safe guard calls a verifier that we deploy ourselves. Measured cost: **~280k gas execution** for verify, decode and burning the pairTag.

What it costs:
- The zkVM run is **0.7–2.3 G cycles** (option C) or **5–16 G** (option A, two phones).
- Proving is minutes on a prover network and cents to ~$2 per session.
- None of it can be proved on this Mac.

## What was measured

### Verifier work
MEASURED with `vcount`: vk shape and native verify on real proofs, M2.

The Spartan verifier cost is dominated by one thing: evaluating the R1CS matrices A, B, C at the random point. That is O(nnz) field multiplications mod the P-256 prime. The MSMs (on T-256, mod n) are small next to it.

| proof | constraints (padded) | nnz A+B+C | eq tables | MSM points | native verify (digest cached / fresh incl. vk digest) | proof |
|---|---|---|---|---|---|---|
| OpenAC sb_half_v2 | 300,888 (2^19) | 1,897,236 | 2^19 + 2^20 | 512 + 1024 + ~100 | 59 ms / 467 ms | 60,543 B |
| OpenAC sb_pair_v2 | 511,816 (2^19) | 3,232,744 | 2^19 + 2^20 | 512 + 1024 + ~100 | 67 ms / 736 ms | 60,543 B |
| option A oa2t_s48 (1 phone) | 1,228,450 (2^21) | 10,490,385 | 2^21 + 2^22 | 2048 + 1024 + ~100 | 180 ms / 1.99 s | 1,648,255 B, 48,011 public |

- The vk carries the whole R1CS: 88 MB (half), 142 MB (pair), 470 MB (s48).
- `verify()` hashes the entire vk with Keccak before it starts. A guest must not do that. Bake the matrices into the guest ELF, so that the program vkey commits to them, and hardcode the digest.

### Cycles in a zkVM
Built from the counts above. Per-op costs are MEASURED as static RISC-V asm from rustc for a fully unrolled Montgomery mulmod over P-256 p:
- rv64: 280 instructions, straight line;
- rv32im: ~872 dynamic;
- addmod (rv64): 59.

Loop and MSM overheads are ESTIMATE. The rv64+precompile column assumes ~50 cycle-equivalents per `uint256_mulmod` call (ESTIMATE, not measured).

| guest workload | mulmod | rv64 software (SP1 v6) | rv32 software (R0) | rv64 + mulmod precompile |
|---|---|---|---|---|
| C: 1x pair_v2 | 7.0 M | 2.3 G | 6.8 G | 0.7 G |
| C: 2x half_v2 + combine (phone-local halves) | 10.2 M | 3.4 G | 9.9 G | 1.0 G |
| A: 2x s48 + pair logic | 48 M | 15.9 G | 46.6 G | 4.8 G |

Precompiles:
- **What helps:** the generic 256-bit modmul, SP1 `uint256_mulmod` or R0 `bigint2`. The field is the P-256 base field p, and T-256 coordinates are mod n. Both are 256-bit, so a generic modmul fits both.
- **What does not help:**
  - the secp256r1 curve precompile (SP1/R0 p256), because the MSM runs on T-256, not P-256;
  - sha256, keccak: only the transcript uses Keccak, and it is small.

Toolchain: SP1 and RISC Zero were **not installed**. The disk had 1–2.8 GB free, and SP1 local core proving needs 16 GB+ RAM, Groth16 16 GB+ (CITED https://docs.succinct.xyz/docs/sp1/getting-started/hardware-requirements). So the cycle counts come from the native instrumentation above, not from an SP1 execute run. That is the next thing to do on a bigger box: port `R1CSSNARK::verify` into a guest, which needs rayon removed and the vk digest hardcoded, then run `execute`.

### Onchain verification
MEASURED with forge, sp1-contracts @ d362972, v6.0.0 verifiers, real SP1 fixture proof.

| call | gas |
|---|---|
| SP1 Groth16 `verifyProof` | 224,739 |
| SP1 Plonk `verifyProof` | 280,055 |
| `PopGate.check`: Groth16 verify + decode (ctx, pairTag, near) + replay mapping (`test/PopGate.t.sol`) | 279,958 |
| deploy SP1VerifierGroth16 | 2,634,965 (12 KB) |

On top of this come the 21k base cost and ~6k of calldata (356 B proof + 96 B public values). **~310k total, one tx.**

### Chains
MEASURED by `eth_getCode` on the public Alchemy RPCs:
- The SP1 gateways (Groth16 `0x397A5f7f…dA9B`, Plonk `0x3B604117…185e`) are **absent on 480 and 4801**. They are not in the sp1-contracts `deployments/` list either.
- The RISC Zero router is not listed for World Chain (CITED https://dev.risczero.com/api/blockchain-integration/contracts/verifier).
- The deterministic CREATE2 deployer `0x4e59…956c` exists on both chains.

So we deploy the verifier ourselves, pinned to one version, for ~2.6M gas. Both projects document self-deployment.

## Proving cost and latency

- **Succinct network.** Pricing is an auction: base fee plus a bid per PGU, and a PGU is roughly one cycle (CITED https://docs.succinct.xyz/docs/sp1/optimizing-programs/prover-gas). No public $/PGU was found.
- **Throughput.** SP1 Hypercube does ~600 M-cycle blocks in ~10 s on 16×5090 (CITED https://blog.succinct.xyz/real-time-proving-16-gpus/, and the Sept 2026 ethproofs writeup). That is ~60 M cycles/s per 16-GPU cluster (ESTIMATE). For our 1 G cycles: ~15–20 s on a cluster, ~5 min on one GPU.
- **Groth16 wrap.** Adds ~14–40 s (CITED, search results summarizing SP1 benchmarks and issue #2674).
- **Boundless.** Median clearing price under $0.04 per billion cycles (CITED https://x.com/boundless_xyz/status/2008896304810807584). ESTIMATE per session: $0.27 (C pair) to $1.9 (A, rv32 software). Bonsai is shut down; Boundless replaces it.
- **This Mac (8 GB, no CUDA).** Not feasible (MEASURED by requirements: 16 GB+). Execute-only would fit.
- **End to end.** ESTIMATE: 1–5 min from the phones' proofs to the Groth16 proof, dominated by network queueing plus the wrap.

## Statement the guest proves

Public values (abi-encoded; SP1 commits their sha256):
- `context`: safeTxHash or session nonce;
- `pairTag = H(nfA, nfB)`;
- `near = 1`;
- `issuerKeyHash`;
- `validAt`.

Inside the guest:
1. Verify both phones' Spartan proofs against baked-in vks.
2. Check the public values:
   - the same nonce;
   - the issuer is pinned;
   - the bounds come from sr;
   - option C only: `dLo < halfA − halfB < dHi` over the two half proofs;
   - option A only: rerun the pair logic.
3. Derive pairTag from the two nullifiers.

**The 48k public values (option A).** These are the templates, derived from the code seed the server reveals. The guest takes the seed and regenerates them, or takes them as private input and commits `sha256(templates)`. Either way they never reach the chain. The onchain public input is one 32-byte digest.

**Context binding.** The inner proofs bind the session nonce. The nonce must be derived from the safeTxHash before the audio session, e.g. `nonce = H(safeTxHash ‖ salt)`, and the guest checks that. Otherwise anyone could re-wrap an old proof for a new tx.

## Trust model

- **Soundness** rests on four things:
  - Spartan2/Hyrax: DLog on T-256, zkID fork, unaudited;
  - the zkVM STARK (SP1 Hypercube is formally verified at the RISC-V constraint level);
  - the BN254 Groth16 wrap with its trusted setup;
  - our own deployed verifier and guest program vkey.
- **Privacy.** The prover network sees only ZK Spartan proofs plus their public values: nonce, issuer, sr, halves (option C half variant), nullifiers and templates. It never sees device keys, signatures or transcripts. Chain observers see context, pairTag and near.
- **Liveness.** Depends on a prover market, or on our own GPU box.

## What is missing to ship

1. A real guest port and an `execute` run to replace the ESTIMATE rows. Needs a ≥16 GB box.
2. A compact matrix encoding in the ELF. 84% of the values fit in 64 bits, and 59% are ±1. The pair matrices are ~115 MB raw, and ELF/memory limits are unchecked.
3. Nonce ← safeTxHash binding in the app/server flow.
4. Option C on POPT v2 (OpenAC still uses SBv1).
5. Verifier deployment on 4801/480, plus a Safe guard around `PopGate`.
6. Prover choice: Succinct network account, Boundless, or own GPU.
7. An alternative that avoids the O(nnz) matrix work entirely: switch the inner proof to a SPARK/preprocessed Spartan so the guest's matrix work drops to log size. Cuts cycles ~5–10x (ESTIMATE).

## Review (soundness)

Adversarial pass, 2026-09-26. Checked against the note, `PopGate.t.sol` in the scratch sp1-contracts, `openac/circuits/sb.circom`, `openac/REVIEW.md`, `optionA-v2/README.md`, `verifier/popzk.py`.

1. **Code seed / templates not bound to the server (blocker, option A).** The note lets the guest take templates as private input and commit `sha256(templates)`, but `PopGate` decodes only `(ctx, pairTag, near)` and checks no digest. Regenerating from a seed has the same hole: nothing proves the seed came from the real server. `popzk.py` lists "the code seed was revealed by the real server" as a caller check; in opt4 the caller is the untrusted aggregator. Fix: the guest verifies a server P-256 signature over `(nonce, attempt, code_seed)` (SP1's p256 precompile makes this cheap), or the gate checks a published seed commitment.
2. **Option C phone-half variant does not bind the two halves (major).** `SBHalf` keeps `partnerPub` private and unchecked, so nothing cross-links half A to half B or proves pubA ≠ pubB. The guest statement in this note lacks `nfA ≠ nfB` and `{roleB_A, roleB_B} = {0, 1}`. Without them, one device signs both roles and makes NEAR alone (openac REVIEW issue 1, same attack). Even with them, a person with two credentials under different holder secrets passes. Option C also trusts the phone-computed half, so a patched app signs any half. The cheapest cycle row (C) has weaker soundness than A, and the note doesn't say so.
3. **pairTag undefined for option A; nullifier gives no uniqueness (major).** The measured circuit `oa2t_s48` has no nullifier (`_nf` wasn't proved). The optionA-v2 README moves the pair tag to World ID adapter nullifiers, which this guest doesn't verify. Where a nullifier exists, it is `H(holderSecret ‖ nonce)`: fresh every session. So `pairTag` never repeats, and `used[(ctx, tag)]` protects nothing beyond `ctx`. Replay safety rests entirely on ctx being the real safeTxHash (below).
4. **"Rerun the pair logic" leaks device keys (major, option A).** Re-opening the halfCommits natively needs `X_self`, `X_partner`, `half` and `salt` as guest inputs. Prover markets see guest stdin, and Boundless requests are public. The guest must verify the `oa2t_pair` Spartan proof instead. Otherwise the claim "never sees device keys" is false.
5. **Gate isn't bound to the Safe tx and can be griefed (major).** `check` is external and permissionless. It never compares `ctx` to the safeTxHash being executed, and it burns `used` on first call. Anyone can copy the proof from the mempool and call `check` first, and the real Safe execution then reverts with "replay". `validAt` and the issuer aren't decoded onchain. `validAt` is prover-chosen, so an expired credential passes if an old `validAt` is used, and there is no revocation. Fix: the guard computes the safeTxHash itself, requires `ctx == safeTxHash`, lets only the Safe call it, and checks `validAt` against `block.timestamp`.
6. **Hidden from the chain, not from the server (major for the privacy goal).** The nonce is public in every inner proof and is guest input. The server issues it to known devices, and with `nonce = H(safeTxHash ‖ salt)` the aggregator holds the salt. So the server, or any prover-market observer who colludes with it, maps safeTxHash to the device pair (openac REVIEW issue 2). The trust model should say so. Otherwise the nonce must be kept private in-circuit, with a server signature checked inside.
7. **Public-value length (minor).** Spartan2 `verify` returns the publics without checking their count against the vk (openac REVIEW issue 3). The guest must compare length and values exactly, not just call `verify`.

Holds up: the Groth16 wrap hides the guest inputs from the chain. The inner proofs are ZK (`zk_spartan.rs`, blinding added by the library), so handing them to a prover network leaks only their public values. Gas numbers are fine (fixture public values, not the PoP layout, but decode cost is negligible).

## Review (numbers)

2026-09-26, adversarial pass. Re-ran `forge test --gas-report` in `sp1-contracts/contracts`.

**Holds up**
- Gas reproduces exactly (MEASURED): Groth16 `verifyProof` 224,739; Plonk 280,055 (v6); `PopGate` test 287,571 incl. call overhead; deploy 2,634,965. Fixture is SP1's fibonacci proof (96 B public values, 356 B proof), and Groth16 verify cost doesn't depend on the program, so using it is fair.
- Answer to the user's question stands: **one tx**, ~0.3M gas for the gate.
- rv64 mulmod = 280 static instructions checked in `rvmul/`.

**Issues**
1. **The low end, 0.7 G / $0.27, is a proof nobody can make privately.** `sb_pair_v2` needs one party holding both signed transcripts (openac/README.md:150). `half_v2` "has no pair binding and publishes the half, cost reference only" (same line). So "2× half + combine" (1.0–3.4 G) also can't just be summed. A pair binding still has to be added to the half circuit, and its size isn't known. The honest C row is ≥1.0 G, plus the cost of that binding.
2. **The cycle model leaves out memory cost.** Matrix eval does a random lookup into `eq_y` for every nnz: 32 MB (pair) and 128 MB (s48), with a 115–470 MB matrix stream on top.
   - RISC Zero charges ~1.1k cycles to page in each 1 KB page, fresh in every segment (ESTIMATE).
   - At ~500 nnz per 2^20-cycle segment, that adds about 0.5M cycles per segment, roughly **1.5–2× the rv32 numbers**. With the bigint accelerator it may dominate.
   - SP1 has the same shape: memory events per shard for each distinct address.
   - The flat "15 cycles per nnz" overhead is also low. It takes ~14 loads alone, so +10% (ESTIMATE).
3. **Summary mixes columns.** "15–20 s on a cluster" uses the 1 G precompile case. The price uses rv32 software. At the same ~60 M cycles/s, option A at 5–16 G is **80–270 s** of cluster time before the wrap. Nothing says so.
4. **The gate prototype doesn't do what the table says.**
   - `PopGate` never checks `ctx == safeTxHash`, so any valid proof passes for any tx.
   - The replay key is `(ctx, pairTag)`, not the pairTag. The same pair can sign unlimited contexts.
   - `issuerKeyHash` and `validAt` (from the statement section) aren't decoded or checked.
   - Adding these checks costs a few k gas. The listed gate is still incomplete.
5. **The ~310k total leaves out the Safe.** It doesn't count `execTransaction`, the owner signature checks or the guard hook, which adds ~50–80k (ESTIMATE). It also doesn't say how the proof gets to the guard: `checkTransaction` only sees Safe params, so the proof would ride in `signatures` or go through a module. World Chain's L1 data fee isn't mentioned either.
6. **Labels.**
   - rv32 mulmod "~872 dynamic" comes from a 189-line static loop. The rv32 addmod file is empty, and its cost of 120 is a guess marked MEASURED.
   - The precompile figure of ~50 cycles per call is the whole basis of the 0.7/1.0/4.8 G column and is unverified.
   - "Formally verified" SP1 Hypercube: EF has since reported a bug in it (https://zkevm.ethereum.foundation/blog/sp1-fv).
7. **Boundless price is from a marketing tweet.** It's a median, and the Groth16 wrap and request minimums may not be included. Treat $0.04/G as a floor.

**Net.** One tx at ~0.3–0.4M gas is solid. Offchain cost and latency are likely **1.5–2× the note's numbers**, and the cheapest row isn't a valid private design yet. The first thing to measure is an SP1/R0 `execute` of the matrix-eval loop alone on the pair vk, which fits in 8 GB for execute only.
