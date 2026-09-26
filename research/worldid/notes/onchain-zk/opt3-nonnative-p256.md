# Option 3: prove the P-256 signatures inside an EVM-verifiable proof

2026-09-26. Question: can a phone make a private PoP proof that a contract (Safe guard) verifies, with the P-256 checks done inside the proof and the device key hidden?

Short answer: yes, with Noir + UltraHonk. One phone's half is 173k gates and proves in 2.4 s on the M2. The full pair check fits in one tx at 5.6M gas (two per-phone proofs) or 2.9M gas (one pair proof). circom/Groth16 would cost about 0.3M gas, but its circuit is 3.3M constraints per phone. It can't be built on this machine, and it's too heavy for phones today.

Labels: **MEASURED** = run here (M2, 8 GB, other jobs running). **CITED** = published number, with the URL. **ESTIMATE** = my inference.

Prototype source: `research/worldid/prototypes/opt3-noir-p256/`. Build outputs stay in the session scratchpad.

## 1. What the circuit proves

The inputs are the real POPT v2 layout (311 B) and the SBcred3 layout (111 B). The data is synthetic: fresh P-256 keys signed by Node `crypto`.

Per phone (`noir/half`):

- **Private inputs:** transcript, device signature, credential, issuer signature, holder secret.
- **Checks:**
  - Transcript header: magic, version 2, role A/B, SEC1 key prefixes.
  - `cred.device_pub == transcript.pk_self`, and `now < cred.expiry`.
  - `cred.holder_commit == Poseidon2(holder_secret)`.
  - ECDSA-P256(`pk_self`, sha256(transcript)) and ECDSA-P256(issuer, sha256(cred)).
  - `|self_os_delta| ≤ 50 ms`, and `pk_self != pk_partner`.
- **Public inputs:** issuer key (4×128-bit), `now`, `scope`, `context`.
- **Public outputs:** role, attempt, nonce (2 fields), sample_rate, half, `pair_tag = Poseidon2(nonce, pk_A, pk_B, attempt)` with the keys ordered by role, and `nullifier = Poseidon2(holder_secret, scope)`.

How the two halves link without revealing devices: each transcript already contains both keys (`pk_self`, `pk_partner`), so both phones compute the same `pair_tag`. When A's tag equals B's tag and the roles are A and B, collision resistance gives these facts:

- B's hidden signer is exactly A's hidden partner, and the reverse.
- Both keys hold issuer credentials.
- The two keys differ.

The chain sees only the tag. The tag includes the session nonce, so it doesn't link across sessions.

The combine runs in the contract (`PopGuard.checkHalves`):

- same issuer, `now` within 10 min of `block.timestamp`, same scope and context;
- roles A and B, same attempt, nonce and tag;
- NEAR: `-20·srA·srB < 17150·(hA·srB − hB·srA) < 60·srA·srB`, the same integers as `server/pop/verdict.py`;
- the two nullifiers differ and are unused; then both proofs are verified.

Pair variant (`noir/pair`): both halves and the NEAR check sit in one circuit, and the outputs are nonce, tag and 2 nullifiers. The catch: one prover needs B's holder secret too. See §4.

Negative checks (MEASURED): a replayed tx reverts with `nullified`. A flipped `half` public input fails verification. With one holder secret on both phones, `same holder` reverts.

## 2. Numbers

### Noir 1.0.0-beta.22 + bb 5.0.0-nightly.20260522 (the bbup-mapped pair), UltraHonk, `-t evm` (keccak, ZK)

| | half (per phone) | pair |
| --- | ---: | ---: |
| gates (`bb gates`) | 173,104 → 2^18 (MEASURED) | 341,282 → 2^19 (MEASURED) |
| of which 1 ECDSA-P256 blackbox | ~65–72k (a lone verify circuit is 72,665 incl. fixed overhead) (MEASURED) | |
| SHA-256, 311 B + 111 B (7 blocks) | ~36k (MEASURED, standalone 35,992) | |
| prove, M2, 8 threads, vk precomputed | 1.8–2.8 s, median ~2.4 s over 6 runs (MEASURED) | 3.2–3.5 s (MEASURED) |
| peak RSS while proving | 380–430 MB (MEASURED) | 600–740 MB (MEASURED) |
| proof | 9,536 B (MEASURED) | 9,920 B (MEASURED) |
| public inputs | 15 fields (MEASURED) | 12 fields (MEASURED) |
| verifier contract | 17.3 KB runtime + 2 linked libraries, under EIP-170 (MEASURED) | same |
| `verify()` tx gas (anvil, Prague) | 2,774,790 (MEASURED) | 2,838,382 (MEASURED) |
| `verify()` execution only (gasleft wrapper) | 2,605,707 (MEASURED) | |
| full guard tx | `checkHalves`, 2 proofs + combine + 2 SSTOREs: **5,592,327** (MEASURED) | `checkPair`: **2,901,409** (MEASURED) |

Cross-check: Base measured Noir P-256 verification at 2,396,575 gas (CITED, https://blog.base.dev/benchmarking-zkp-systems).

### circom (circom-dl by distributed-lab, the Rarimo team's library) + Groth16

| | value |
| --- | ---: |
| 1 ECDSA-P256 verify (`verifyECDSABigInt(64,4,P-256)`) | 1,558,296 non-linear constraints; compile 79 s, 3.5 GB RSS (MEASURED, r1cs piped to /dev/null) |
| PSE circom-ecdsa-p256 for comparison | 1,972,905 constraints, 1.2 GB pkey, 26 s prove, 56 GB RAM to build (CITED, https://github.com/privacy-scaling-explorations/circom-ecdsa-p256/blob/master/README.md) |
| SHA-256 311 B + 111 B, circomlib | 210,968 (MEASURED) |
| per-phone statement | ~3.33M → 2^22 ptau (4.8 GB), zkey ~2 GB (ESTIMATE from the counts above) |
| pair statement | ~6.7M → 2^23 (ESTIMATE) |
| Groth16 verify gas | 225,770 execution with 6 public inputs (MEASURED with a snarkjs verifier from `v1-bn254/binding.zkey`). With ~12 public inputs and calldata, about 290k per proof (ESTIMATE) |
| Groth16 verify gas, cited | 347,665 (CITED, Base blog above) |
| prove time | Base: Groth16 on a ~2M-constraint P-256 circuit takes 40–50 s on 8 vCPU (CITED, same). 3.3M here → ~70–90 s laptop (ESTIMATE) |

Not proved: this machine can't hold the ptau and zkey. The disk had under 100 MB free during the run, and the 280 MB r1cs write ran it out. A 2^22 setup also needs a per-circuit phase-2 ceremony.

Gotcha: the anvil/`cast` tx gasUsed for the snarkjs verifier read 36,847, which is wrong. The number above comes from a `gasleft()` wrapper; the Honk tx and wrapper numbers agree.

### Phones

Everything in this subsection is CITED or ESTIMATE; nothing ran on a phone.

- Noir P-256, one signature (about the size of `ecdsa1` here):
  - M1 MacBook: 2.06 s, multithreaded.
  - Samsung A23 (Android): ~6 s.
  - iPhone 16/Pro: out of memory, but that was in-browser wasm.
  - CITED, https://hyli.ghost.io/benchmarking-in-browser-p256-ecdsa-proving-systems/
- Native Noir via mopro/noir_rs, a JWT circuit: iPhone 16 Pro 2.63 s against 2.02 s on an M1 Pro, so about 1.3× desktop. CITED, https://zkmopro.org/blog/noir-integraion/
- Our half circuit on a recent phone: **~3–6 s, ~400 MB** with native bb (noir_rs / Swoir / mopro). Older Android: maybe 10 s+. ESTIMATE, scaled from the 2.4 s M2 figure by the ratios above.
- Pair circuit: ~5–10 s, ~700 MB (ESTIMATE).
- circom per phone at 3.3M constraints: a ~2 GB zkey to ship, and memory several times that. No cited phone number exists at this size for P-256; the ethereum/csp-benchmarks issue #305 notes circom has no P-256 entry yet. Treat it as not viable on phones without a much better P-256 gadget. The 503k-constraint secp256k1 work (zk.golf techniques, csp-benchmarks PR #302) suggests ~0.5–0.6M per verify is possible (ESTIMATE). That's still ~1.3M per phone.

## 3. Answers to the task questions

- **Per-phone proofs or one pair proof?** Per-phone proofs plus the onchain combine. It's built and it works. Each phone proves only its own half, and no phone sees the other's holder secret or credential. The cost is two verifies (5.6M gas).
- **One tx?** Yes, in both variants. 5.6M gas is ~19% of a 30M block (ESTIMATE; I didn't check World Chain's block gas limit). Calldata is ~19 KB for two proofs.
- **Linking without revealing devices:** the shared `pair_tag` (§1). Nonce and attempt are public too, so the contract can bind them to the Safe context: `nonce == keccak(safeTxHash, salt)` is checked outside the circuit (not built yet).
- **RIP-7212 P256VERIFY doesn't help:** it needs the key and message in the clear, which the user rejected.

## 4. Trust model

- **Issuer (server):** trusted to enroll only attested hardware keys. A malicious issuer can mint credentials for software keys and fake presence. Same as today.
- **Device and app:** the proof shows an enrolled key signed the transcript. It doesn't show the audio produced `half`; the app computes it. A rooted phone that can drive its enclave key can sign any `half`. This is the same trust as option C; option A (audio in circuit) isn't EVM-friendly.
- **Proof system:** UltraHonk with Aztec's universal SRS, so no per-circuit ceremony. The bb ECDSA-secp256r1 blackbox is used in production by zkPassport; I haven't looked for an audit. bb is a nightly.
- **Privacy from the chain:**
  - Hidden: device keys, credentials, holder secrets.
  - Visible: pair_tag, nullifiers, nonce, role, attempt, sample rate, both `half` values (so the distance), context, scope.
- **Privacy from the server:** it knows nonce ↔ devices, so it can recompute pair_tag and link the onchain event to the devices. The fix, not built:
  - keep the nonce private;
  - have phone A register the nonce as `H(context, r)` with a phone-only `r`;
  - prove that relation in-circuit (a few k gates).
- **Holder commitment:** SBcred3 today uses Poseidon7 over the P-256 field. This prototype assumes a BN254 Poseidon2 commit in the same slot, so the credential format has to change (SBcred4).

## 5. Missing before shipping

1. A mobile prover:
   - bundle bb via mopro / noir_rs (iOS: Swoir);
   - ship the ~2^18 SRS slice (~16 MB) and the circuit;
   - measure time and RAM on a real iPhone and a mid Android.
2. SBcred4, with a BN254 Poseidon2 holder commit, issued by the server.
3. Context binding (nonce derived from safeTxHash) and server-unlinkable nonces (§4).
4. The Safe guard: wire `PopGuard` into `checkTransaction`, choose the nullifier scope (per Safe tx or per action), handle issuer key rotation (the issuer key is a public input, so rotation needs no redeploy).
5. Gas. Options, none built:
   - a recursive aggregator that folds two half proofs into one EVM proof (~2.9M gas, and no secret sharing, unlike the pair circuit);
   - a Groth16 wrap of the Honk proof (~0.3M gas).
6. The pair circuit as built needs B's holder secret at A. Don't use it except under recursion.
7. Audit: circuit-level range checks, low-s assumption (the blackbox rejects high-s; the prover normalizes), key-on-curve (covered by the issuer signature over the key bytes).

## Review (soundness)

2026-09-26, adversarial pass over `noir/poplib`, `noir/half`, `noir/pair`, `forge/src/PopGuard.sol`.

Checked and fine (MEASURED):
- Unused public inputs are still bound. Flipping `now`, `scope` or `context` in `public_inputs` makes `bb verify` fail.
- No nullifier malleability through `x + r`. The Honk verifier requires `publicInputs[i] < P` (HalfVerifier.sol:571).
- The pair_tag crossing logic is sound: equal tags plus roles A/B force `A.self == B.partner` and `A.partner == B.self`.

Real problems:

1. **No freshness, no context binding (blocker).**
   - `context` only goes in as a public input (`let _ = context;`). Nothing ties it to the signed transcript.
   - The contract never checks the nonce.
   - POPT v2 carries only monotonic nano times, so an old transcript pair can be proven later with a fresh `now`.
   - Today, replay is stopped only by `used[H(secret, scope)]`, and `scope` is `immutable`. So each holder can pass the guard once, ever.
   - If scope becomes per-tx to fix that, one old meeting authorizes unlimited future txs.
   - Either way, the proof doesn't show presence at tx time.
   - Needed: a nonce derived from ctx (or ctx inside the signed transcript), proven in-circuit, plus a freshness rule.
2. **pair_tag can be enumerated (major, privacy).**
   - The tag is `Poseidon2(nonce, pkA, pkB, attempt)`, and the nonce and attempt are public outputs.
   - Anyone with a list of enrolled device keys can test every pair against each onchain event. That's the server's DB, or pooled lists from past partners, since every transcript holds the partner key. At 10k devices it's ~1e8 Poseidon hashes.
   - The server doesn't even need the tag. It creates the nonce (`server/pop/sessions.py:142`) and stores `half` and `sample_rate` per role (`sessions.py:331`), and all three are public onchain.
   - Hiding the nonce (§4 fix) isn't enough on its own. `half` also has to be hidden or kept off the server, and the tag needs a secret only the phones know.
3. **"Two devices" really means "two enrolled keys" (major).**
   - `device_id = sha256(pubkey)[:16]` (`main.py:252`), and `holder_commit` is chosen by the client (`main.py:259`).
   - So one phone can generate and attest two hardware keys (Keystore aliases, or several App Attest keys), enroll them with two holder secrets, and sign both the A and B transcripts.
   - Both `pk_self != pk_partner` and the `same holder` check pass.
   - Re-enrolling also mints fresh nullifiers, so the nullifier limits per enrollment, not per phone or person.
4. **Front-run griefing (major).**
   - `checkHalves` is permissionless and burns the nullifiers.
   - Anyone who sees the calldata (mempool, relayer, co-signer) can submit it first, and the Safe tx then reverts with `nullified`.
   - With an immutable scope, that holder is locked out for good.
   - `ctx` isn't stored, so a guard can't accept "presence already recorded for ctx".
5. **Minor.**
   - A public `sample_rate` leaks the platform (44.1k vs 48k).
   - `now` is chosen by the prover and reveals roughly when the proof was made.
   - `half.nr` doesn't range-check `sr` or `half` (`pair.nr` does). That's harmless given the app-trust assumption, but it's inconsistent.

## Review (numbers)

Reviewer pass, 2026-09-26. Re-ran the prototype from the scratchpad build.

**Numbers that hold (MEASURED again):**
- `bb gates`: half 173,104, pair 341,282. Exact match.
- Prove, M2: half 1.59–1.62 s, 409–427 MB RSS (3 runs). Pair 2.91 s, 786 MB. Faster than the note's 2.4 s median (less load now). The pair RSS is a bit above the note's 600–740 MB range.
- Witness generation (`nargo execute`, half): 0.23 s, 141 MB. The note leaves it out; a phone pays it too. Small.
- Proof 9,536 B / 9,920 B; public inputs 480 B / 384 B. Exact match.
- Gas (fresh anvil, Prague): verify half 2,774,790; verify pair 2,838,382; `checkHalves` 5,592,327; `checkPair` 2,901,409; replay reverts `nullified`. Exact match. Gotcha: `gas.sh` only runs if anvil time is set near the proof's `now` (0x6ab13b80 = 2026-09-21); on a default anvil the guard reverts `now` and the script dies on a JSON error.
- Context is really bound: flipping one bit of public input [6] (`context`) makes `bb verify` fail, even though the circuit only does `let _ = context`.
- circom arithmetic checks out: 2 × 1,558,296 + 210,968 = 3.33M → 2^22.

**Issues:**
1. **Context binding doesn't hold end to end (major).** `context` is just a public input the prover picks when it proves. Nothing ties it to the transcript: the nonce is whatever the transcript says, and the contract never checks it. So a NEAR transcript pair recorded once can be proved later for any safeTxHash. Today the fixed `scope` (immutable in `PopGuard`) hides this, because each holder's nullifier works exactly once, ever, per guard. A real guard needs a nullifier per tx or per epoch, and then stale-session replay opens up. The note does list "nonce from safeTxHash" as missing, but requirement (3) isn't met by what was built, and the summary line "bound to a context" overstates it. The fix is cheap: the contract checks `nonce == H(ctx, salt)`, or the circuit does (a few k gates). But the session nonce is server-issued, so the server has to accept a phone-chosen nonce.
2. **The onchain check is weaker than the server's `check_transcript` (minor to major, depending on threat model).** Not checked: the POPC v2 commit signature, `commit_hash`, `rec_root`, `delta`, `code_commit` against the server's codes, and `SR_MIN ≤ sr ≤ SR_MAX` (`checkHalves` has no sr range; only the pair circuit bounds sr). Under the stated trust model (the app computes `half`), these add little. Still, the onchain path accepts transcripts from a session the server never ran. Cost to close, ESTIMATE:
   - commit sig + SHA over 71 B: +~75–80k gates → ~250k. Still 2^18, but only ~10k of headroom.
   - a server signature over (nonce, codes) is a third ECDSA → 2^19. That roughly doubles prove time and RAM (pair circuit data: 2.9 s, ~790 MB on M2).
3. **Gas is framed against the wrong chain (minor, but it changes the recommendation).** World Chain block gas limit is 280,000,000 on mainnet and 480,000,000 on Sepolia, with mainnet base fee 0.0005 gwei (MEASURED via public RPC `eth_getBlockByNumber`). So 5.59M is 2% of a block, not "19% of 30M". Execution cost ≈ 2.8e-6 ETH (ESTIMATE, sub-cent). The L1 data fee for ~20 KB of incompressible proof calldata isn't estimated. It's probably cents at current blob fees, but measure it on Sepolia. On World Chain, the recursive aggregator and Groth16 wrap in §5 aren't needed for gas. Their costs are also missing: the aggregator verifies two Honk proofs in-circuit (likely 2^20–2^21, ESTIMATE, server-side), and a Groth16 wrap of Honk means non-native BN254 arithmetic, i.e. millions of constraints.
4. **Phone estimate is optimistic for mid Android (minor).** The cited A23 number is ~6 s for one ECDSA (~72k gates) in browser wasm. Our half is 2.4× the gates. Scaling by the M1-wasm vs M2-native ratio gives ~5–8 s native on A23-class hardware, not 3–6 s. For flagships, 2–3 s native (1.3× the 1.6–2.4 s desktop time) is plausible. All ESTIMATE until mopro runs on a device.
5. **The pair variant's 2.90M gas is a headline number for a design the note says not to use** (it needs B's holder secret at A). The fair comparison is 5.59M.

**Not an issue:** calldata is ~20.1 KB, so the EIP-7623 floor (~0.8M) sits well below execution gas. The note's disk warning is real: 77 MB free during this review.
