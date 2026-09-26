# Option A in Noir/UltraHonk: how heavy it really is

2026-09-26. Question: if option A (the audio rule proven inside the proof) moves from circom + Spartan2/Hyrax to Noir + UltraHonk so a contract can verify it, what does it cost? Everything was built and run; the full circuit proves on the real fixture.

Labels: **M** = MEASURED here (M2, 8 GB, shared with other jobs, load average 3.5–14 during the runs; heavy steps through `research/sound-bound/spikes/zk/tools/heavy.sh`). **X** = EXTRAPOLATED (method stated). **C** = CITED (URL). **E** = ESTIMATE.

Toolchain: nargo 1.0.0-beta.22, bb 5.0.0-nightly.20260522 (the opt3 pair), forge/anvil (solc 0.8.34, Prague).
Source: `research/worldid/prototypes/optA-noir/` (circuits in `noir/`, `gen_inputs.py`, `tamper.py`, `run.sh`, `gas.sh`, `forge/`). Build outputs and logs stay in the session scratchpad (`scratchpad/optA/`).

## Short answer

- **It runs, end to end.** The whole option A statement is one Noir program:
  - transcript and credential ECDSA;
  - 26 opened leaves under the signed `rec_root`;
  - the Freivalds self curve, FIR energy and arrival rule;
  - the partner bar;
  - the hiding half commitment.

  It executes on the real `180ca04b_48k` fixture for both roles, proves, and verifies natively and in a Solidity verifier. 9 of 9 tampers per role are rejected. (M)
- **Size: 972,858 UltraHonk gates → 2^20**, 92.8% full. That is the onchain variant: templates private, their Poseidon2 commitment public. The faithful variant with the 48k templates public is 905,644. circom was 1,228,446 R1CS constraints. The pair circuit is 3,459 gates. (M)
- **M2 (8 GB, shared):**
  - prove **8.9–11.1 s** at 8 threads (25 s on one thread);
  - peak **~1.6 GB** (footprint; RSS 1.1–1.56 GB);
  - witness 3.0 s;
  - verify ~10 ms.

  (M)
- **Proof 10,304 B** plus 384 B of public inputs (12 fields). (M)
- **Gas:** each phone proof costs **2,729,067** execution / **2,905,781** tx gas; the pair proof 2,227,780 / 2,352,894 (M). A session (2 phones + pair) is ≈ 7.7M execution (E).
- **Public templates are impossible onchain:** 129M execution gas plus 1.55 MB of calldata (M). Private templates bound to a server-attested Poseidon2 commitment cost **+115k gates** (+67k versus the faithful circuit) and keep 2^20 (M).
- **Phones (E):**
  - iPhone 16/17 Pro ~6–14 s;
  - flagship Android ~20–25 s;
  - mid-range Android ~30–45 s;
  - ~1.6 GB everywhere, so a 6 GB+ phone (on iOS, with the increased-memory-limit entitlement).
- **Feasibility: conditional yes.** It costs 5.6× option C's gates, ~4× its prove time and ~3–4× its memory, for the same proof size and gas. The conditions:
  - the app signs a Poseidon2 `rec_root` and `code_commit`;
  - the server attests the code commitment;
  - phones have 6 GB+ and users accept 10–45 s proofs;
  - nothing big is added to the plain circuit. It has only 75.7k gates of headroom. Adding the POPC commit-signature check measures 1,049,713 gates, 1,137 over the line, so it would double to 2^21 (M).
- **Lever, built and measured:** checking the FIR outputs by one random evaluation instead of recomputing them gives **855,525 gates** (−12%). On the same machine state it proves ~15–20% faster with ~18% less memory (1.32 GB). With it, the POPC check fits at 932,379 gates. Both run on the real witness (M).
- **Uncertain:**
  - no phone run;
  - the M2 was loaded;
  - only the FIR lever is built;
  - bb is a nightly and the port is unaudited;
  - the split-trust caveat of the circom review (F3) is unchanged.

## 1. What was ported

Source statement: `research/sound-bound/spikes/zk/optionA-v2/circuits/main/oa2t_s48.circom` (48 kHz, POPT v2) and `oa2t_pair.circom`. The Noir port proves the same statement, part for part:

| part | circom (oa2t_s48) | Noir port |
|---|---|---|
| (1) transcript | 311-byte POPT v2 rebuilt from fields, SHA-256, ECDSA-P256 by the hidden device key (zkID gadget, native field) | same bytes taken as a private array, fixed/public bytes asserted; `sha256` lib; `std::ecdsa_secp256r1` blackbox |
| credential | SBcred3 (111 B), SHA-256, issuer ECDSA, `validAt ≤ expiry` | same |
| pinned values | `sr == SR`, `delta == 96`, own X ≠ partner X, `p_self = a_self − sod`, `a_partner = a_self ± half` | same (X compared as 2 × 128-bit limbs) |
| (2) recording | 26 leaves × 1,024 int16, 16-bit range, Poseidon7 leaf sponge, 4-ary depth-4 path, 10-bit offsets, barrel shifter | same leaves, u16 inputs, **Poseidon2** leaf sponge (23 perms), 4-ary depth-4 path (node = 2 perms), offsets, **ROM (dynamic array read)** instead of the barrel shifter |
| (3) Fiat–Shamir + Freivalds | Poseidon7 sponge over 398 values → r, ρ; `r^{L−1}`-scaled prefix-sum identity | **Poseidon2** sponge over the same 398 values; the same identity in streaming form with `r^{−n}` (equivalent, r ≠ 0) |
| energy, rule | 63-tap FIR energy prefix, cn2, 96-bit comparisons, monotone selector u | same |
| (5) partner | one lag, I/Q/E direct, 96-bit bar, window `[p_partner − 150 ms, p_partner + 250 ms]` | same |
| (6) output | `halfCommit = Poseidon7(…, sr, half, salt, X_self, X_partner)` | Poseidon2 over the same values (X as limbs) |
| pair | opens both commitments, crossed keys, i32 halves, rates in range, NEAR by cross-multiplication | same |

Deliberate differences:

- **Hashes.** Poseidon7 over the P-256 field → Poseidon2 over BN254 (bb blackbox, t = 4). So `rec_root` and (onchain variant) `code_commit` in the signed transcript change, and the app must compute the Poseidon2 tree. The circuit also checks that `rec_root` is a canonical BN254 element.
- **Field.** BN254 (254 bits) instead of secq256r1 (256 bits). Every integer bound in the statement is ≤ 96 bits (70 in the pair), so nothing wraps.
- **ECDSA low-S.** The bb blackbox rejects high-S; the prover normalizes `s → n − s` (anyone can, no key needed). The circom gadget accepted both.
- **Templates (onchain variant).** Private int8 (u8 + 128, range-checked), bound to a public Poseidon2 commitment. See §4.

Two main circuits:

- `noir/phone` — **onchain variant**: public = nonce (2), attempt, roleB, code_commit (1), issuer key (4 × 128-bit limbs), sr, validAt; returns halfCommit. 12 public fields.
- `noir/phone_pub` — **faithful variant**: the circom public interface, i.e. the 48,000 template values are public inputs and code_commit is SHA-256 (2 limbs), recomputed by the verifier. 48,013 public fields.

## 2. circom baseline: where the 1.23M constraints go

COUNTED from the generated `oa2t_s48.circom` (formula per template); the sum is checked against the MEASURED compile total (`optionA-v2/logs/compile_oa2t_s48.log`: 1,228,446 non-linear constraints). The signature part is the remainder.

| part | constraints | share | how counted |
|---|---:|---:|---|
| int16 range checks, 26 leaves × 1,024 × 16 bits | 425,984 | 34.7% | Num2Bits(16) per sample |
| barrel shifters, self + partner (10 stages each) | 259,568 | 21.1% | Σ stage widths: 130,734 + 128,814, + 2 × Num2Bits(10) |
| transcript + SBcred3: 7 SHA-256 blocks, 2 ECDSA (native field), byte/bit decompositions | 242,888 | 19.8% | remainder (≈ 215k SHA at ~30.8k/block from `t_sha2k`, ≈ 25k ECDSA, ≈ 3k bits) |
| Poseidon7 leaf sponges, 26 × 5 perms × 700 | 91,000 | 7.4% | |
| self Freivalds: powers, prefix sums, 3 per template sample, I/Q sums | 60,771 | 4.9% | 12,191 + 12,192 + 36,000 + 386 + 2 |
| partner: I, Q (24,000), FIR energy (12,000), cnp (12,000), bar, window | 48,165 | 3.9% | |
| Merkle paths, 26 × (8 + 4 × 348) | 36,400 | 3.0% | |
| per-lag rule: selector 385 + 193 × (5 + 96) | 19,878 | 1.6% | |
| Fiat–Shamir sponge, 27 perms × 700 | 18,900 | 1.5% | |
| self FIR energy (12,192, one per output: the 31-tap sum is free in R1CS) | 12,192 | 1.0% | |
| cn2 of the own template | 12,000 | 1.0% | |
| halfCommit | 700 | 0.1% | |
| **total** | **1,228,446** | | = compile log (M) |

The pair circuit `oa2t_pair` is 1,612 constraints (M, `logs/compile_oa2t_pair.log`). No r1cs was recompiled for this note.

## 3. Noir port: gates

All MEASURED with `bb gates` (the `circuit_size` field).

| circuit | ACIR opcodes | gates | dyadic size |
|---|---:|---:|---|
| `phone` (onchain variant) | 471,316 | **972,858** | 2^20 = 1,048,576 (92.8% full, 75,718 gates of headroom) |
| `phone_pub` (faithful: 48k public templates) | 420,829 | **905,644** | 2^20 |
| `pair` | 57 | **3,459** | 2^12 |

The dyadic size is confirmed two ways: bb downloaded exactly 1,048,576 CRS points for the phone vk, and the generated Solidity verifiers carry `N = 1048576, LOG_N = 20` (phone) and `N = 4096` (pair).

**Where the 972,858 gates go.** Two measurements, both MEASURED at full size:

- *Leave-one-out*: the full circuit recompiled with one part replaced by a stub that keeps every input in use (`noir/loo/gen_loo.py`). The difference is that part's marginal cost inside the real circuit. The stubbed full circuit reproduces 972,858 exactly.
- *Standalone*: each part as its own program at full size (`noir/c_*`). These include their own input range checks and fixed tables, so they overlap and don't add up.

| part | marginal in full circuit (M) | standalone program (M) | circom (§2) |
|---|---:|---:|---:|
| (1) transcript + SBcred3: 2 × SHA-256 (311 B, 111 B), 2 × ECDSA-P256 blackbox, byte checks | **166,315** | 170,730 | 242,888 |
| (3)+(4) self side: cn2, selector, ROM window (12,254 reads of 13,312), FIR energy, Freivalds, rule | **319,566** | 376,376 (incl. input ranges) | 104,841 + 130,734 barrel |
| (5) partner side: cnp, ROM window (12,062 reads), FIR energy, I/Q, bar | **242,908** | 309,636 (incl. input ranges) | 48,165 + 128,814 barrel |
| (2) leaf packing + Poseidon2 leaf sponges + Merkle paths, 26 leaves | **70,666** | 113,363 (incl. u16 ranges) | 127,400 |
| template commitment (onchain variant only): packing + 518 Poseidon2 perms | **54,836** | 115,332 (incl. u8 ranges) | – |
| (3) Fiat–Shamir sponge, 398 values, 133 perms | **10,108** | – | 18,900 |
| (6) halfCommit | **311** | – | 700 |
| inputs: 48,000 template bytes (u8 range) | ≈ 60,400 (X: phone − phone_pub, see §4) | – | – |
| inputs: 26,624 samples (u16 range) | ≈ 39,900 (X: 1.5 gates each, micro benchmark) | – | 425,984 |
| rest (t/sig bytes, offsets, window bounds, fixed range tables) | ≈ 7,900 (remainder) | | |

Inside each side, from micro benchmarks of the same shapes (M, `scratchpad/optA/micro`):

- **ROM window ≈ 76.7k per side.** A 13,312-entry table with 12,254 dynamic reads costs 76,696 gates: about 3.2 per table entry plus 2.8 per read.
- **FIR energy ≈ 12 gates per output** (12,018 for 1,000 outputs): the 31 non-zero taps cost ~10 gates of additions, then one gate for y². Self has 12,192 outputs, partner 12,000, so ≈ 290k of the 562k both sides cost.
- The Freivalds loop, I/Q, cn2 and the rule are the rest (~7 gates per template sample on the self side).

Why the Noir and circom profiles differ:

| cost | circom R1CS | UltraHonk | effect |
|---|---:|---:|---|
| int16 range check | 16 | ~1.5 (lookup-based) | −386k |
| hash, per absorbed field element | 46.7 (Poseidon7 t=16: 700 / 15) | 24.3 (Poseidon2 t=4: 73 / 3) | −66k (leaves, paths, FS, halfCommit: 147.0k → 81.1k) |
| shift by a secret offset | 10 × 2 barrel stages ≈ 10.6 per sample | ROM ≈ 6.2 per sample | −106k |
| SHA-256 block | ~30.8k | ~5.1k | −180k (signature part as a whole: 242.9k → 166.3k) |
| ECDSA-P256 | ~12k (native field) | ~65–72k (non-native) | +105k |
| 31-tap FIR output | 1 (linear combination is free) | ~12 | **+266k** |

The FIR is the one place PLONK-style arithmetization is much worse than R1CS: R1CS gets linear combinations for free, UltraHonk pays about one gate per three terms.

## 4. Public inputs: the realistic onchain version

The circom statement makes the four 12,000-value templates public (48,000 field elements). That is fatal onchain, MEASURED on the faithful variant:

| | faithful `phone_pub` (48,013 public inputs) | onchain `phone` (12 public inputs) |
|---|---:|---:|
| gates | 905,644 | 972,858 |
| prove, M2 | 9.08 s, 1.42 GB RSS | 8.9–11.1 s, 1.10–1.56 GB RSS |
| proof + public inputs | 10,304 B + 1,536,416 B | 10,304 B + 384 B |
| verify() execution gas (forge) | **129,134,825** | **2,729,067** |
| calldata gas, 4/16 per byte (EIP-7623 floor) | 15.7M (39.1M) | 0.16M (0.41M) |
| verdict | impossible: 8× the L1 per-tx cap of 2^24 ≈ 16.8M gas (EIP-7825, C: https://eips.ethereum.org/EIPS/eip-7825), and a 1.55 MB tx is far above geth's 128 KB txpool limit (E) | fits one tx: 2,905,781 tx gas on anvil (M) |

**Design used (built and measured): templates private, bound by a server-attested commitment.**

- The prover passes the four templates as private `u8` arrays (value + 128). The range checks make the packing injective.
- The circuit packs them 31 bytes per element (1,552 elements), hashes them with Poseidon2 (518 perms, `TAG_CODE`) and exposes the result as the public input `code_commit`.
- The same value is the signed `code_commit` field of the transcript (32 bytes). It replaces SHA-256("pop-code-v2" ‖ templates): SHA-256 over 48 KB inside the circuit would be ~751 blocks ≈ 3.8M gates (E, at the measured ~5.1k per block).
- `code_commit` is also absorbed into the Fiat–Shamir sponge. That was the review's condition for private templates.
- The contract learns the correct `code_commit` per (session, role, attempt) from the server: posted onchain, or signed with a key the contract knows (secp256k1 → `ecrecover`, a few thousand gas; E). That is the same trust as today's circom verifier, which derives the templates from the seed the server reveals.

**Cost of the binding, MEASURED:**

- Poseidon2 commitment (packing + hashing): **54,836 gates** (leave-one-out).
- u8 range checks on 48,000 bytes: **≈ 60,400 gates** (X: `phone − phone_pub = 67,214 = 54,836 + range − 48,001` public-input rows, so ≈ 1.26 gates per byte).
- Total **≈ 115k** (the standalone `c_code` program: 115,332). Net versus the faithful circuit: **+67,214 gates**, and it still fits 2^20.

**Not feasible: deriving the templates in-circuit from a signed seed.** A template is a band-masked bed rendered through a 2^17-point float FFT, its Hilbert pair through another FFT, then int8 quantization (`optionA-v2/oa_rate.py`). Reproducing that bit for bit in a circuit means fixed-point FFTs of 131,072 points: millions of gates at least (E). Not built.

## 5. Measurements (M2)

Real fixture: `180ca04b_48k` (30 cm label, NEAR, flight 33.94 cm), role A unless noted. MEASURED unless labeled otherwise.

**What the witness is.**

- **Real:** the audio, the templates, the claimed curve I/Q, the selector u, the leaf indices, SBcred3 with the real issuer signature, the salt and every transcript field except two.
  - The capture is regenerated from the field WAV exactly as `build_fixtures_popt2.py` did (the `build/` cache is gone).
  - It is checked sample for sample against the circom witness (`optionA-v2/inputs/popt2_180ca04b_48k_A.input.json`).
- **Recomputed:** `rec_root` (Poseidon2 tree over the same 256 leaves) and `code_commit` (Poseidon2 commitment).
  - The 311-byte transcript is then **re-signed by the same Secure Enclave key** of this Mac (`enclave/sesign`, `keys/A.seblob`, read only).
  - The issuer signature is normalized to low-S.
- **Role B:** same pipeline.

| step | result |
|---|---|
| `nargo compile` phone | 56.8 s, 2.27 GB peak footprint (1.68 GB max RSS) |
| `nargo compile` phone_pub | 53.1 s, 1.90 GB |
| witness prep (`gen_inputs.py`: capture, Poseidon2 tree via the unconstrained `helper`, 2 SE signatures) | 1.7 s |
| `nargo execute` phone | **3.0 s**, 0.34 GB peak footprint (0.46 GB RSS). Output halfCommit `0x271f…63e1`, equal to the helper's. Role B: `0x25a5…d546`, equal too |
| `bb write_vk` (incl. first download of the 2^20 CRS, 64 MB) | 9.2 s, 1.49 GB RSS; vk 1,888 B |
| `bb prove`, 8 threads, `-t evm` (keccak transcript, ZK), 5 runs | **8.85, 9.85, 9.94 s** (load 3.5–6.3); **10.56 s** (A), **11.08 s** (B) (load 5.9–7.4). User CPU 38–45 s |
| memory during prove | max RSS 1.10–1.56 GB, peak footprint **1.57–1.61 GB** in every run (footprint counts compressed pages too, so it is the stable number) |
| `bb prove` with 4 / 2 / 1 threads | 12.09 / 16.37 / **25.00 s** (load 7–9.5); peak footprint 1.58–1.59 GB at every thread count |
| `bb prove --slow_low_memory`, alone and with `--storage_budget 4g` / `1g` | 12.25 / 11.74 / 10.97 s, peak footprint 1.59–1.60 GB: **no memory saving** in this bb build for this circuit. Proofs verify |
| `bb verify` (native) | OK, ~10 ms, 15 MB |
| proof | **10,304 B**; public inputs 384 B (12 fields) |
| Solidity verifier | `PhoneVerifier` 17,337 B runtime (+ `RelationsLib` 7,964 B and `ZKTranscriptLib` 6,108 B, linked), under EIP-170 |
| `verify()` gas | **2,729,067** execution (forge, `gasleft`); **2,905,781** tx gas on anvil (Prague, incl. 21k and calldata). Flipping the last public input reverts |
| pair | execute OK; prove 0.10 s, 26 MB; proof 7,232 B + 224 B public (7 fields); verify 2,227,780 execution / 2,352,894 tx |
| faithful `phone_pub` | execute OK (same halfCommit); prove 9.08 s, 1.42 GB RSS; proof 10,304 B + 1,536,416 B public; verify 129,134,825 execution gas |

Artifacts a phone would carry:

- the circuit (`phone.json` 14.6 MB, of which the gzipped ACIR is 9.8 MB);
- the 2^20 CRS (64 MB, or 32 MB compressed);
- the vk (1.9 KB).

The witness file is 4.3 MB gzipped. There is no per-circuit proving key: bb rebuilds it in ~1.7 s inside `prove`.

**Session gas** (E, from the measured parts): two phone proofs plus the pair proof:

- 7,685,914 execution;
- 8,164,456 as three txs.

If the halves were public, as in option C, the pair proof could be replaced by the contract's integer NEAR check: ≈ 5.5M. But then the chain sees the distance.

**Compiler hazard found on the way** (M). Noir 1.0.0-beta.22 blows up in memory on this circuit shape:

- Big arrays written inside loops: 10.9 GB peak footprint and 77 s for three 12k-entry prefix arrays.
- `std::as_witness` or long `+=` chains:
  - 2.0 GB at 9,600 steps, versus 94 MB for the same loop with a hint + assert;
  - the first partner-side draft reached 9.6 GB before being killed.

The library is therefore written as streaming loops with small ring buffers, and it forces witnesses with `w(e)` (hint + one assert). Anyone extending the circuit has to keep to that style.

## 6. Tampers (both roles, real fixture)

`tamper.py`: each case edits the honest `Prover.toml` and runs `nargo execute`. If execution fails there is no witness, so there is no proof. Both roles give the same result.

| case | what | rejected at |
|---|---|---|
| `sample` | one opened self sample +1 | Merkle digit selection, `lib.nr:117` (leaf hash changed) |
| `curve` | claimed I_0 + 1 | Freivalds identity, `lib.nr:433` |
| `u_later` | arrival selector one lag later, transcript unchanged | Σu = a_self − p_self + δ, `lib.nr:369` |
| `resign_late` | compromised app re-signs `a_self' = p_self + δ` (sod' = δ, same p_self and a_partner) with the real SE key | self rule, 96-bit check (`self_side`): the true arrival earlier in the window scores ≥ bar |
| `resign_early` | compromised app re-signs `a_partner' = a_partner − 100` with the real SE key | partner bar, 96-bit check (`partner_side`) |
| `nonce` | public nonce_hi xor 1 | transcript nonce check, `lib.nr:235` |
| `half` | signed half +30 in the witness bytes, not re-signed | device ECDSA, `lib.nr:253` |
| `sr` | public sr = 44,100 on the 48 kHz circuit | sr check, `lib.nr:239` |
| `swap_role` | public roleB flipped, same signed bytes | role byte, `lib.nr:233` |

This covers every tamper mode of the circom suite (`run_tests_popt2.py tampers`: 7 modes × 2 rate modes × 2 roles, plus 4 self_os_delta cases) except the mixed-rate runs and the sod cases, which need the 44.1 kHz circuit. `curve` and `u_later` are new.

Not re-run in Noir: the 214 pair edge cases and the NOT_NEAR sessions. The pair circuit was executed and proved only on the honest NEAR session.

## 7. Phones

Nothing ran on a phone. Published numbers first (C), then the estimate (E).

Published mobile numbers for Noir/bb (none gives gate counts next to phone times, so they serve as device ratios):

- **mopro, native bb through noir_rs, same circuit** (StealthNote JWT): iPhone 16 Pro 2.626 s, M1 Pro 2.02 s, so the iPhone is **1.30×** the M1 Pro time. An Android emulator (Pixel 8) took 4.786 s. C: https://zkmopro.org/blog/noir-integraion/
- **mopro docs, Noir Keccak256:** 349 ms on the iOS target (an M3 MacBook Air running the iPad build), 1,303 ms on a Pixel 6, so the Pixel 6 is **3.7×**. C: https://zkmopro.org/docs/0.2/performance/
- **Same M2, other prover (zkID Spartan2):** iPhone 17 **0.63×** and Pixel 10 Pro **2.3×** the M2 time. C: zkID's published mobile numbers, via `research/sound-bound/spikes/zk/openac/README.md`
- **ZKPassport, production Noir/UltraHonk on phones:**
  - base proofs take "10s to 50s … depending on the type of signature algorithm … and the mobile device";
  - ECDSA IDs "should not exceed 2GB of RAM";
  - it ships "a 128MB SRS … for circuits up to the 2^21 subgroup size".
  - C: https://docs.zkpassport.id/faq
- **Rarimo, Noir passport on Android (bb 0.66.0):** brainpoolP512r1 2.7 GB RAM, 1 min 7 s; secp521r1 2.9 GB, 1 min. No gate counts. C: https://github.com/rarimo/passport-zk-circuits-noir
- **iOS memory:**
  - jetsam caps each app well below physical RAM;
  - `com.apple.developer.kernel.increased-memory-limit` raises the cap, but not on 4 GB devices (iPhone 11 and earlier);
  - one iPhone 17 Pro (8 GB) app peaked at ~4,651 MB with it.
  - C: https://zenn.dev/mtfum/articles/ios_memory_entitlements?locale=en

Estimate for this circuit (E). Method: the M2 time times each cited device ratio. Memory stays at the measured ~1.6 GB, because it is dominated by the 2^20 polynomials, which are the same on any CPU.

| device class | prove | peak memory | fits? |
|---|---|---|---|
| iPhone 16 / 17 Pro | **~6–14 s** (0.63–1.3 × the M2's 9–11 s) | ~1.6 GB | yes, with the increased-memory-limit entitlement (6–8 GB devices) |
| flagship Android (Pixel 10 Pro class) | **~20–25 s** (2.3×) | ~1.6 GB | yes (8–12 GB devices) |
| mid-range / older Android (Pixel 6 class) | **~30–45 s** (3–4×) | ~1.6 GB | 6 GB yes; 4 GB borderline |
| 4 GB iPhones, 2–3 GB Android | – | – | no (E) |

Also on the phone:

- **Witness generation:** 3.0 s on the M2 with nargo, which includes parsing a 470 KB TOML. Through noir_rs the ACVM runs the same way: ~2–6 s (E).
- **Thermals:** sustained 10–45 s all-core load will throttle phones (E, not modeled).
- **Thread scaling, M2:** 1 → 2 → 4 → 8 threads = 25.0 → 16.4 → 12.1 → 10.6 s. The prover gets only ~2.4× from 8 threads, so a phone with 2 big cores and 4 little ones loses less than its core count suggests (E).

For comparison, the circom/Spartan2 phone estimate in `optionA-v2/README.md` is iPhone 17 ~2.5–3 s and Pixel 10 Pro ~7–10 s, at ~2 GB (E).

## 8. Side by side

| | option A, circom + Spartan2/Hyrax (today) | **option A, Noir + UltraHonk (this note)** | option C, Noir + UltraHonk (`opt3-*.md`) |
|---|---|---|---|
| what the proof shows | audio rule on the committed recording + signatures | same | signatures only; the phone computes `half` |
| size | 1,228,446 R1CS (M) | **972,858 gates → 2^20** (M) | 173,104 gates → 2^18 (M) |
| witness | 0.37–0.42 s, C++ witnesscalc (M) | 3.0 s, nargo execute (M) | 0.23 s (M) |
| prove, M2 | 4.49 s fresh + 2.2 s pk load; 4.7 s warm (M) | **8.9–11.1 s** at 8 threads; 25 s at 1 thread (M) | 1.6–2.8 s (M) |
| peak memory, M2 | 1.93 GB footprint (M) | **1.57–1.61 GB** footprint, 1.1–1.56 GB RSS (M) | 0.38–0.43 GB RSS (M) |
| keys / setup | pk = vk = 470 MB (11.7 MB zstd); transparent (Hyrax) | no pk; universal KZG SRS, 2^20 points = 64 MB; vk 1.9 KB | same, 2^18 SRS |
| proof | 1,648,255 B, incl. 1.54 MB of public templates; proof proper ~80–110 KB (M) | **10,304 B** + 384 B public (M) | 9,536 B + 480 B (M) |
| native verify | 0.27 s warm, 1.24 s fresh + 1.8 s vk load (M) | ~10 ms (M) | ~10 ms (M) |
| EVM verify | none: Hyrax over T-256 has no EVM verifier | **2,729,067** execution / **2,905,781** tx (M) | 2,605,707 execution / 2,774,790 tx (M) |
| onchain per session | – | 2 phones + pair: 7.69M execution, 8.16M as 3 txs (E from M parts) | `checkHalves`: 5.59M in one tx (M) |
| phone (E) | iPhone 17 ~2.5–3 s, Pixel 10 Pro ~7–10 s, ~2 GB | iPhone 16/17 Pro ~6–14 s, flagship Android ~20–25 s, mid Android 30–45 s, ~1.6 GB | 2–3 s flagship, 5–8 s mid Android, ~0.4 GB |
| hash | Poseidon7 over P-256 (own parameters, unaudited) | Poseidon2 over BN254 (bb) | Poseidon2 |
| transcript change | POPT v2 | POPT v2 with Poseidon2 `rec_root` and `code_commit` | none (POPT v2 as is) |

Against option C, the audio statement makes each phone proof about **5.6×** the gates, **~4×** the prove time and **~3–4×** the memory. The proof size and the gas per proof are about the same. Against today's Spartan2 prover it is **~2× slower** to prove on the M2 (~1.5× end to end, since Spartan2 also loads a 470 MB key) but uses **less memory**, has a **160× smaller** proof file (the Spartan2 file carries the 1.54 MB of public templates; against its ~80–110 KB proof proper it is 8–11× smaller), needs no 470 MB key, and is the only one of the two a contract can verify.

## 9. Levers and the 2^20 cliff

**Headroom of the plain port.** 1,048,576 − 972,858 = **75,718 gates** before the circuit doubles to 2^21 (≈ 2× time and memory, E).

**One lever and one extra check, built and measured** (`noir/phone_opt`, `noir/phone_opt_popc`, `noir/phone_popc`; same real witness):

| circuit | gates (M) | dyadic | real witness (M) |
|---|---:|---|---|
| `phone` (plain port) | 972,858 | 2^20 | executes, proves, verifies |
| `phone_opt`: FIR claim-and-check | **855,525** (−117,333, −12.1%) | 2^20, 193,051 headroom | executes (same halfCommit), proves, verifies; proof 10,304 B; Solidity verify 2,729,069 gas |
| `phone_opt_popc`: + POPC commit signature | **932,379** (+76,854) | 2^20, 116,197 headroom | executes with a real SE signature over the Poseidon2 POPC |
| `phone_popc`: plain port + POPC signature | **1,049,713** (+76,855) | **2^21**: 1,137 gates over 2^20 | not proved |

- **FIR claim-and-check** (`phone_opt`):
  - The prover supplies the 24,192 FIR outputs (offset by 2^25, range-checked to 26 bits).
  - They are packed 9 per element into the Fiat–Shamir sponge before r.
  - They are checked with one evaluation: `Σ_m r^(m+62) y_m = Σ_t h_t r^(62−t) (T_{t+N} − T_t)`, where `T_i = Σ r^i' w_i'` is the window's power prefix.
  - The self Freivalds identity now reads the same prefix, `(T_{n+K+31} − T_{n+31}) r^(−n−31)`, so the separate S prefix is gone.
  - Same statement. The extra soundness error is ≤ (N + 62)/p ≈ 2^−240 per identity.
- **POPC commit signature** (the POPC v2, 71 B, signed by the same device key): **+76,854 gates** (M). This is the check the opt3 review wanted for the onchain path. It ties the proof to the pre-reveal commitment, which the server enforces today.
  - With the FIR lever it fits (932,379).
  - Without the lever it lands at 1,049,713, **1,137 gates over the 2^20 line**. The plain port plus this one check would double to 2^21.

Prove, all three in one heavy.sh session so the load is the same (load average 10–14, so all are slower than §5):

| circuit | prove, 8 threads (M) | peak footprint (M) | user CPU (M) |
|---|---|---|---|
| `phone` | 16.41, 14.70 s | 1.61–1.62 GB | 49 s |
| `phone_opt` | 13.36, 11.73 s | **1.32–1.33 GB** | 44 s |
| `phone_opt_popc` | 12.78, 14.60 s | 1.41–1.43 GB | 47 s |

So the FIR lever cuts prove time by ~15–20% and peak memory by ~18% on the same machine state. Scaled to the quieter runs of §5 that is ≈ 7.5–9 s and ~1.3 GB (X: same ratios). All three proofs verify.

Not built (E):

- **Shared Merkle nodes** for the 13 contiguous leaves per side: −10k.
- **44.1 kHz circuit** (L = 11,025, 12 leaves per side): ~8% smaller.
- **Split the per-phone proof** into a self-side and a partner-side proof, linked by a hiding commitment to `rec_root`:
  - each is ~2^19, so peak memory ≈ halves (~0.8 GB);
  - total prove time about the same;
  - onchain cost doubles to ~5.5M per phone.
  - This is the lever for 4 GB phones; low-memory mode didn't help (§5).
- **2^19 isn't reachable for this statement.** Even with the FIR lever, the audio part alone is ≈ 574k gates (X: 855,525 − 166,315 for the signatures − ~115k for the template binding), above 524,288. Getting there would take a smaller statement (e.g. a shorter template, which changes the false-accept analysis) or moving the signature into another proof.

## 10. Not measured / uncertain

- **No phone run.** Every phone number is E, built from device ratios measured on other circuits (and, for the zkID ratio, another prover).
- **Machine load.** The M2 was shared (load 3.5–14, other sessions' Android/Gradle/Xcode builds in the heavy queue). One queued run was killed from outside at load 30+ and redone. A quiet M2 would probably prove in ~8 s (E), but that wasn't measured.
- **Not measured:**
  - the L1 data fee on World Chain for ~10.7 KB of calldata per proof;
  - whether the OP stack applies an EIP-7825-style per-tx cap. The onchain variant is far below it either way.
- **Not audited:**
  - bb is a nightly, and the secp256r1 blackbox needs low-S (the prover normalizes);
  - this port. The tamper suite is 9 cases × 2 roles on one session, not the circom suite's full 48 + 32 + 28 + 214 runs.
- **Unchanged from the circom review:**
  - the proof adds security only if capture, `rec_root` and `p_self` come from something more trusted than the arrival code (REVIEW F3);
  - the completeness gap (|self_os_delta| ≤ 2 ms in the circuit versus 50 ms on the server);
  - one person with two phones (F4);
  - no freshness or context binding;
  - the pair proof alone accepts made-up halves; the session verifier (or contract) must link it to the per-phone halfCommits (F1).
- **App changes needed:** the app must build the Poseidon2 tree (256 leaves) and sign the Poseidon2 `rec_root` and `code_commit`. The server must publish or sign the Poseidon2 code commitment per (session, role, attempt).
- **Not built:** the Merkle and split levers; the 44.1 kHz circuit (one circuit per sample rate, as in circom); a contract that links the pair proof to the two phone proofs. The FIR-lever circuit (`phone_opt`) was executed, proved and verified (Solidity `verify()` 2,729,069 execution gas, M, the same as `phone`), but its tamper suite was not repeated.

## Reproduce

```
# everything (compile, witness, prove, verify, Solidity gas, tampers); heavy steps take the heavy.sh lock
research/worldid/prototypes/optA-noir/run.sh 180ca04b_48k A

# pieces
PY=scratchpad/optA/venv/bin/python3        # any python with numpy + soundfile (research/proximity-echo/.venv was removed mid-run)
NARGO=$BIN/nargo $PY research/worldid/prototypes/optA-noir/gen_inputs.py 180ca04b_48k A $S/noir   # Prover.toml for phone, phone_pub, pair, phone_opt, phone_opt_popc
(cd $S/noir/phone && nargo execute phone && bb write_vk -b target/phone.json -o vk -t evm \
   && /usr/bin/time -l bb prove -b target/phone.json -w target/phone.gz -k vk/vk -o out -t evm \
   && bb verify -k vk/vk -p out/proof -i out/public_inputs -t evm)
cd research/worldid/prototypes/optA-noir/forge && RDIR=$S/noir/phone/out PDIR=$S/noir/pair/out forge test -vv
python3 noir/loo/gen_loo.py $S/noir     # leave-one-out variants for the gate breakdown
NARGO=$BIN/nargo python3 tamper.py $S/noir A
```

`BIN` = the opt3 toolchain dir (`scratchpad/onchain-zk/opt3-nonnative-p256/bin`), `S` = `scratchpad/optA`. Logs: `scratchpad/optA/logs/` (compile, execute, prove ×9, scaling, loo, tamper, gas).
