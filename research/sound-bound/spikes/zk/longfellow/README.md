# longfellow track: the sound-bound statement in longfellow-zk

The implemented protocol has each phone compute and sign its own half, so no audio goes into the proof. What's left is signatures, hashes and one comparison. That fits longfellow-zk well: Google's Ligero + sumcheck prover with native P-256 ECDSA circuits (eprint 2024/2010, IETF draft-google-cfrg-libzk).

**Result:** the full two-role statement works, and it works on the real Secure Enclave fixtures. The M2 proves it in **0.71 s** on one thread and verifies it in **0.40–0.46 s**. The proof is **387 KB** and peak RAM is **~280 MB**. The 4 NEAR fixtures verify. The 8 NOT_NEAR fixtures and every tampering case are refused by the honest prover, and the verifier rejects them even when a forging prover produces a proof.

## Statement (circuit `SBzk1`, one circuit over the P-256 base field)

Public inputs: issuer public key (x, y), `nonce[32]`, `attempt` (u8), `now` (u64), `nullifier[32]`.

Private inputs: for each role R ∈ {A, B}: the device public key (64 bytes), `half_R` (i32), `rec_hash_R`, `ts_R` (u64, `n_ts` fixed at 1), the credential expiry, the issuer signature and the device signature. Shared between the roles: `sr` (u32) and `holder_secret[32]`. There are also SHA block witnesses and two 64-bit range witnesses.

The circuit checks all of the following:

1. For R = A and B: `cred_R = "SBcred1" | dpk_R | exp_R`. The issuer's ECDSA P-256 signature over `sha256(cred_R)` verifies under the public issuer key, and `now <= exp_R`.
2. For R = A and B: `tr_R = "SBv1" | nonce | attempt | role_R | dpk_R | dpk_other | sr | half_R | rec_R | 0x01 | ts_R`, 215 bytes. The role byte is the constant 0x41 or 0x42. The same `dpk` wires feed the credential, the ECDSA key and both transcripts, crossed between the roles, so the partner key in each transcript is forced to equal the other role's credentialed key. The public nonce and attempt feed both transcripts. ECDSA under `dpk_R` over `sha256(tr_R)` verifies.
3. Threshold, where `d = half_A - half_B` is signed. The protocol rule is −20 < 17150·d/sr < 60 cm. The circuit writes it as two non-negative values: `1715·d + 2·sr − 1` and `6·sr − 1715·d − 1` must both lie in [0, 2^64). Each is a bit decomposition checked against the value in the field. The rule matches `enclave/common.py`'s `verdict()` on all 12 fixtures.
4. `nullifier == sha256(holder_secret | nonce)`.

That is 4 ECDSA verifications and 14 SHA-256 blocks: 2 per credential, 4 per transcript and 2 for the nullifier. All messages have fixed length, so padding is constant and no block muxing is needed. The ECDSA and SHA gadgets are the vendor ones (`circuits/ecdsa/verify_circuit.h` `verify_signature3`, `circuits/sha/flatsha256_circuit.h` packed). The layout follows the vendor toy credential (`circuits/tests/anoncred/small.h`).

What the proof hides: both device keys, both halves and the flight distance, the recording hashes, the timestamps, the expiries and `sr`. The verifier learns only "a NEAR meeting in session `nonce` between two issuer-credentialed keys", plus the nullifier.

## Results (M2 MacBook, 8 GB, shared machine; all measured)

| What | Size | Prove | Verify | Peak RSS | Proof |
| --- | --- | --- | --- | --- | --- |
| **SBzk1, our statement** (4 ECDSA + 14 SHA blocks + range) | depth 12, 1,129,385 wires, 3,485,672 quad terms, 35,331 inputs (587 public) | **0.70–0.72 s** (5 runs, load avg ≈ 4) | **0.40–0.46 s** | prove 264–285 MB, verify 185–206 MB | **386.5–388.7 KB** |
| SBzk1 compile (one-time) | circuit file 42.0 MB raw, 0.66 MB zstd -19 | 3.8 s | – | 828 MB | – |
| vendor 1× ECDSA, pk + e public (`BM_ECDSAZK*/1`) | 24,477 wires, 49,646 quad terms | 33.6 ms | 23.2 ms | – | – |
| vendor 2× / 3× ECDSA (first run, load avg ≈ 35) | – | 53 / 120 ms | 38 / 42 ms | – | – |
| vendor toy credential (`BM_AnonCred`: issuer sig + hidden device-key sig + 7 SHA blocks) | 592,555 wires, 1,799,704 quad terms | 389 ms (load ≈ 4); 405 ms (load ≈ 35) | – | 572 MB (includes its in-process compile) | – |
| vendor SHA-256 in GF(2^128) (`BM_ShaZK_fp2_128/n`, load ≈ 35) | – | 1 / 2 / 4 / 8 blocks: 10.5 / 16.6 / 28.1 / 50.4 ms | – | – | – |
| vendor full mdoc (`BM_MdocProver/Verifier`: 2 ECDSA + SHA over the MSO + CBOR, hash circuit in GF(2^128) + MAC) | two circuits | 504 ms (load ≈ 6–8) | 273 ms | 1.28 GB (includes in-process circuit generation) | – |

- **Timing:** the prover is single-threaded (user time ≈ wall time). The "prove" column covers commit and prove only. On top of that come 0.15 s to load the 42 MB circuit file and ~2 ms to build the witness (SHA plus ECDSA witness tables).
- **Where the size goes (derived from the vendor sizes, not measured separately):** 4 ECDSA ≈ 0.2 M of the 3.49 M quad terms. The remaining ~94% is the 14 SHA blocks done in the P-256 field, about 235 k terms per block.
- **Logs:** `logs/bench.log` (timing runs), `logs/tests.log` (accept/reject matrix), `logs/vendor_bench.log`, `logs/vendor_mdoc.log`.

### Phone estimate (estimate, not measured)

Two vendor benchmarks have published phone numbers, and both ran on this M2 in this session:

| Benchmark | iPhone 15+ | Pixel 9 | M2 | iPhone / M2 | Pixel / M2 |
| --- | --- | --- | --- | --- | --- |
| toy credential | 289 ms | 572 ms | 389 ms | 0.74 | 1.47 |
| full mdoc | 437 ms | 931 ms | 504 ms | 0.87 | 1.85 |

SBzk1 proves in 0.71 s on the M2. Applying those ratios gives about **0.5–0.6 s on iPhone 15-class** and about **1.0–1.3 s on Pixel 9**, single-threaded, with ~300 MB of RAM for proving. This assumes our circuit scales like the vendor ones.

## Correctness checks (`run_tests.sh`: 81/81 pass, see `logs/tests.log`)

The fixtures are the 12 real JBL250 sessions. Their device signatures come from real Secure Enclave keys, and the issuer is a software dev key.

- Before building anything, `prep.py` rebuilds both transcripts and both credentials from the fixture fields. It checks them byte-for-byte against `transcript_hex` and `cred_hex`, and checks all four ECDSA signatures in pure Python.
- **Accept:** all 4 NEAR fixtures (180ca04b 33.2 cm, 2dc2eb59 7.9, b550cf12 31.8, b9e4dd4b 26.1) prove and verify. 180ca04b also proves with B as the prover, which gives a different nullifier.
- **NOT_NEAR** (all 8 fixtures: 62.9 to 224.7 cm, all with valid signatures): the honest prover refuses. A forged proof is rejected by the verifier. This includes b2a5f86d at 62.88 cm, just past the 60 cm line (d = 176 against a limit of 167).
- **Tampering on the private side**, on 180ca04b and 2dc2eb59. Each case is refused by the prover, and the forged proof is rejected by the verifier:
  - `half`: A's half + 1
  - `role`: A and B data swapped, which would flip the sign
  - `nonce_w`: the witness uses a nonce the phones did not sign
  - `sig`: one bit of A's device signature flipped
  - `credsig`: one bit of B's issuer signature flipped
  - `expired`: now = expiry + 1
- **Tampering on the public side:** an honest proof is rejected when the verifier's nonce, attempt, issuer key, `now` or nullifier differs from what it was proved with. A proof for session X checked against session Y's public inputs is rejected, and so is a truncated proof.
- **Forging prover** (`gen_forge.sh`, test only): generated from the vendor prover with its three "refuse bad witness" checks removed, so the verifier actually sees a proof built from a bad witness. A sanity check confirms that its proofs on an honest witness still verify.
- **Informational:** a high-S version of a valid device signature (s → n − s) is accepted. The circuit does not enforce low-S, which does not matter for this statement.

## How to run

```sh
cd research/sound-bound/spikes/zk
# 1. vendor (once): longfellow-zk + gtest/benchmark built from source into vendor/deps
git clone https://github.com/google/longfellow-zk vendor/longfellow-zk   # pin b762b93b
git clone https://github.com/google/googletest vendor/googletest          # 4267679b
git clone https://github.com/google/benchmark vendor/benchmark            # ac13143d
tools/heavy.sh lf-deps sh longfellow/build_deps.sh
cd vendor/longfellow-zk && D=$PWD/../deps && CXX=clang++ CC=clang cmake -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_PREFIX_PATH=$D -DCMAKE_CXX_FLAGS="-I$D/include" -DCMAKE_EXE_LINKER_FLAGS="-L$D/lib" -S lib -B clang-build-release
cd ../.. && tools/heavy.sh lf-build-core make -C vendor/longfellow-zk/clang-build-release -j 4 \
  verify_test flatsha256_circuit_test small_test mdoc_zk_test
# 2. ours (needs brew openssl@3 + zstd, already present)
cd longfellow
cmake -S . -B build -DCMAKE_CXX_COMPILER=clang++ && ../tools/heavy.sh lf-sbzk-build cmake --build build -j 4
../tools/heavy.sh lf-sbzk-compile ./build/sbzk compile out/sbzk1.circuit
PY=../../../../proximity-echo/.venv/bin/python3
$PY prep.py ../fixtures/180ca04b.json out/180ca04b            # [--tamper half|role|nonce_w|sig|credsig|expired|highs] [--prover B]
../tools/heavy.sh lf-prove ./build/sbzk prove out/sbzk1.circuit out/180ca04b/witness.txt out/180ca04b/proof.bin
./build/sbzk verify out/sbzk1.circuit out/180ca04b/public.txt out/180ca04b/proof.bin
../tools/heavy.sh lf-sbzk-tests ./run_tests.sh                 # full accept/reject matrix
../tools/heavy.sh lf-bench ./bench.sh                          # timings + vendor comparison
```

Files: `sbzk_circuit.h` (the statement), `sbzk.cc` (compile / prove / verify CLI and witness builder), `prep.py` (fixture → witness/public, tamper variants), `gen_forge.sh` + `sbzk_forge.h` (test-only forging prover), `run_tests.sh`, `bench.sh`, `build_deps.sh`.

Vendor pins: longfellow-zk `b762b93b4ebfc67f2df311d96dbca132390d3cd1` (2026-09-23), googletest `4267679b6887f349f17b01ccd70c9e3483689b25`, google/benchmark `ac13143d96b61cec419b49f76e58d2045aba8536`.

## Gaps

1. **The nullifier is not bound to the holder.** `SBcred1` has no commitment to `holder_secret`, so a prover can pick any secret and get a fresh nullifier every time. As built, the nullifier only proves that the prover knows *some* preimage. Worse, anyone holding both signed halves (for example the server, if the halves meet there) can produce a proof. Fix: `SBcred2 = … | sha256(holder_secret)` (the issuer sees only the hash), plus a check in the circuit that the hash matches. That costs about 1 more SHA block, and the credential stays at 2 blocks up to 119 bytes.
2. **One proof speaks for one holder.** The prover needs the partner's signed transcript, credential and issuer signature. If both phones want a credit, that is two proofs with two nullifiers. Which role the prover played is not revealed.
3. **SHA is ~94% of the circuit** because it runs in the P-256 field. Production mdoc moves SHA into a GF(2^128) circuit and binds the two circuits with a MAC (`circuits/mac`). The vendor GF(2^128) SHA benchmark (8 blocks in 50 ms) suggests a 2–4× faster prover (estimate, not built). A shorter transcript also helps: 215 bytes means 4 blocks.
4. **Fixed format:** `n_ts = 1`, `sr` is private and shared by both roles (not pinned to 48000), and the timestamps in the fixtures are placeholders.
5. **Public `now`:** a precise value could help link proofs, so use day granularity. The issuer key is public, so the issuer-tagging issue (research memo §3) still needs a transparency list.
6. **Low-S is not enforced** (see the informational check above). This is harmless here.
7. **Circuit identity:** the verifier must pin the circuit hash (`sbzk compile` prints the id prefix `924e3238…`). The Fiat-Shamir label is `sound-bound/SBzk1` and the public inputs are absorbed into the transcript by the library.
8. **Not measured:** the phone numbers (the estimate above) and cold-start circuit load on a phone.
9. **Out of scope by design:** attestation (App Attest / Key Attestation) is checked by the issuer at enrollment, not inside the proof. The proof also does not make the audio honest; that rests on the attested app (trust note).
