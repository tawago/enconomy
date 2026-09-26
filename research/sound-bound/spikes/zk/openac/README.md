# openac: sound-bound statement on OpenAC (circom secq256r1 + Spartan2/Hyrax)

The whole co-presence statement, both phones' enclave signatures and the issuer credentials, as one circom circuit over P-256's own base field. It is proved with PSE zkID's Spartan2 pipeline (OpenAC, eprint 2026/251), using real Secure Enclave signatures from `../fixtures`.

Headline (measured, M2 8 GB): the two-role proof has 481k constraints. Prove takes 0.87 s, plus 0.16 s for the witness. Peak RSS is 0.86 GB, the proof is 60.5 KB, and verify takes 50 ms warm (0.39 s in a fresh process). All 47 accept/reject tests pass. SHA-256 is 87% of the circuit.

> **Status 2026-09-26 (afternoon): deferred.** The user moved the focus to option A. Everything below still uses the spike's SBv1 transcript (215 B), not the app's POPT v1 (269 B, `docs/pop-contract.md` §7.1), and it still assumes one sample rate. Before option C can consume what the app signs, it needs the POPT v1 switch.
>
> Started and left in a working state:
> - `circuits/popt.circom` and `circuits/main/popt_pair{,_nf}.circom`:
>   - POPT v1 rebuilt byte for byte (65-byte SEC1 keys, contract offsets);
>   - `|self_os_delta| ≤ 50·sr/1000` per role;
>   - both signed rates, with the cross-multiplied −20/60 cm check;
>   - pubA ≠ pubB;
>   - timestamps, rec_sha256 and commit_hash private.
> - They compile: 483,000 constraints (no nullifier), and 573,191 with the optional "none"-adapter nullifier. Compare 481,159 / 511,813 for SBv1.
> - `prover/` (`sbzk`) now links them and has an `inspect` command (SNARK-verify and print the public values). It was rebuilt, and the old suite still passes: `logs/tests_check_after_popt.log`, 26/26, plus a fresh sb_pair_v1 prove/verify/inspect in `logs/proof_after_popt.log`.
> - POPT v1 fixtures with real enclave signatures exist (`../fixtures/popt_v1/`, 27 files, incl. 48/44.1 kHz pairs). `server/pop/verdict.verify_record` accepts all of them as expected (`../verifier/check_fixtures_server.log`).
>
> Not done:
> - witness prep, setup, proofs and tests for `popt_pair`;
> - an option C path in `../verifier/popzk.py`.

## Statement

Circuit `SBPair(N_TS=1, CRED_V)` in `circuits/sb.circom`.

**Public**
- `nonceHi`, `nonceLo`: the 32-byte session nonce as 2 × 128-bit limbs.
- `attempt`
- `issuerX`, `issuerY`
- `sr`
- `dLo`, `dHi`: sample bounds.
- `validAt`: unix seconds.
- Output: `nullifier`.

The verifier computes the bounds from `sr` with exact integer math: −20 cm < c/2·d/sr < 60 cm ⇔ `dLo < d < dHi`, where `dLo = floor(−20·sr/17150)` and `dHi = ceil(60·sr/17150)`. At 48 kHz that gives −56 < d < 168.

**Private**
- Both device pubs (64 bytes each).
- Both halves (i32).
- Both recording hashes.
- Both `os_ts` (u64).
- Both device signatures (r, s⁻¹).
- Both credential expiries and issuer signatures.
- `holderSecret` (32 bytes).
- v2 only: both holder commitments, plus the bit `me` (which role is the prover).

**Checks**
1. Nonce, attempt and sr are decomposed into bits, so they are range-checked. `validAt` is checked to be under 2^64.
2. Role A's transcript is rebuilt in-circuit, byte for byte in the SBv1 layout: `"SBv1"|nonce|attempt|0x41|pubA|pubB|sr|halfA|recA|n_ts|tsA`. Role B's is `…|0x42|pubB|pubA|…|halfB|recB|…|tsB`. Nonce, attempt and sr come from the public inputs, and the pubs are the same signals in both transcripts, crossed.
3. For each role, ECDSA P-256 is checked with that role's pub over SHA-256(transcript) mod n (zkID `ECDSA` + `HashModScalarField`).
4. For each role, `cred = "SBcred1"|pub|expiry` (v1) or `"SBcred2"|pub|expiry|holder_commit` (v2) is built from the same pub bytes. The issuer's ECDSA over SHA-256(cred) must verify against the public issuer key, and `validAt ≤ expiry`.
5. `dLo < halfA − halfB < dHi`. The halves are decoded as two's complement and the comparison is done on integers shifted by 2^34.
6. `nullifier` = the first 31 bytes of SHA-256(holderSecret ‖ nonce). This is SHA-256, not circomlib Poseidon: α=5 is not a permutation here because 5 | p−1.
7. v2 only: SHA-256("SBhold1" ‖ holderSecret) must equal the holder commitment in the prover's credential (role A if `me=0`, B if `me=1`).

`os_ts`, the rec hashes, the pubs and the halves never leave the witness.

**One-role variant** `SBHalf` (cost reference): one device's credential and its signed transcript. The public inputs are the same, with `roleB` in place of `dLo`/`dHi`. It outputs `nullifier` and `half`, and the partner pub stays private.

**v1 vs v2.** v1 is exactly the requested statement on the enclave track's SBcred1 credentials. v2 binds the nullifier to a credential. It re-issues SBcred2 credentials with the throwaway dev issuer key (`../enclave/keys/issuer_dev.pem`) and keeps the real enclave device signatures, which don't cover the credential.

## Results (all measured on this M2 unless marked)

The ours rows come from `logs/bench_*` (5 reps in one process, keys loaded) and `logs/prove_*`/`verify_*` (fresh process under `/usr/bin/time -l`). The zkID rows come from `logs/zkid_bench_1k.log` and `logs/zkid_show_prove.log`.

| circuit | R1CS constraints | witness (C++) | prove | verify warm / fresh proc | proof | pk / vk | setup | peak RSS (prove proc) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **SBPair v1** (2 roles) | 481,159 | 157 ms (138–181) | **866 ms** (858–938) | 52 ms / 373–394 ms | 60,543 B | 134.3 / 134.3 MB | 1.5 s | 0.86 GB |
| SBPair v2 (bound nullifier) | 511,813 | 166 ms | 926 ms (885–959) | 51 ms / 411–427 ms | 60,543 B | 141.9 / 141.9 MB | 1.6 s | 0.87 GB |
| SBHalf v1 (1 role) | 270,976 | 86 ms | 587 ms (557–857) | 46 ms / 227–268 ms | 60,543 B | 81.0 / 81.0 MB | 0.8 s | 0.48 GB |
| SBHalf v2 | 300,885 | 95 ms | 616 ms (585–683) | 54 ms / 252–271 ms | 60,543 B | 88.5 / 88.5 MB | 0.9 s | 0.55 GB |
| zkID Show (their bench, 1k) | 19,084 | incl. | 135 ms (+54 reblind) | 42 ms | 46.29 KB | 4.64 MB | 76 ms | 42 MB (show prove alone) |
| zkID Prepare jwt_1k | 1,013,532 | incl. | 2,000 ms (+737 reblind) | 1,477 ms | 75.99 KB | 261.9 MB | 3.9 s | 1.77 GB (whole bench proc) |

- **Wall time per proof process** (heavy.sh): pair_v1 1.9 s and half_v1 1.2 s. This covers pk mmap/decode (0.2–0.5 s), witness and prove.
- **Cost split (pair v1)**, from measured gadget sizes: 14 SHA-256 blocks at 29.7–30.1k each (circomlib, measured 29,725 for 1 block and 120,221 for 4) ≈ 419k (87%). 4 ECDSA at 14,094 each (zkID `ecdsa` main, measured) ≈ 56k (12%). Glue ≈ 6k. Transcripts are 215 bytes = 4 blocks each, credentials 2 blocks, nullifier 2 blocks.
- **Proof size** is identical (60,543 B) across variants. Presumably the Hyrax commitment depends on the padded witness size, and all four pad to the same power of two (not checked).
- **Fresh-process verify** includes computing the vk digest (a `OnceCell`, not serialized). The vk carries the whole R1CS, which is why it's 134 MB.
- **zkID reproduction vs their README** (M5 24 GB): Show 57 ms prove / 19 ms verify / 40.51 KB there, against 135 / 42 ms / 46.29 KB here. Prepare 1k: 1,119 / 740 ms there, against 2,000 / 1,477 ms here.

## Correctness checks

- **`logs/tests_check.log`** (26/26). Witness generation plus a direct R1CS satisfiability check, no proving:
  - All 12 fixtures: the 4 NEAR fixtures are accepted and the 8 NOT_NEAR fixtures are rejected. That includes b2a5f86d, the 60 cm label that read 62.9 cm (d=176 ≥ 168).
  - Rejected on the NEAR fixture 180ca04b: B's half +30 without re-signing, swapped roles, wrong nonce, one bit flipped in A's device sig s, the wrong issuer key, and `validAt` after expiry.
  - v2 and half-v2 reject a holder secret that doesn't match the commitment.
  - v1 **accepts** a foreign holder secret with a different nullifier. This is expected: it demonstrates that the v1 nullifier is unbound.
  - Both half variants accept both roles A and B.
- **`logs/tests_proofs.log`** (21/21). Real Spartan2 proofs for all four circuits: the honest proof verifies. Verify is rejected when the expected nonce differs, when the expected nullifier differs, and for a proof with one flipped byte (`InvalidPCS`). A pair proof for 180ca04b checked against b550cf12's public inputs is also rejected.
- The public outputs match Python's independent computation (nullifier, limbs, bounds).

A limit on these tests: witness-level rejection shows that the honest computation of the tampered inputs violates a constraint. It doesn't prove the gadgets are sound against a malicious witness. That rests on zkID's gadgets (see the audit-fix comments in `vendor/zkID/.../ecdsa/ecdsa.circom` and `p256/mul.circom`) and on review of `sb.circom`.

## How to run

    ./run_all.sh          # everything below, heavy steps via ../tools/heavy.sh

Step by step:

    ../enclave/.venv/bin/python prep_inputs.py 180ca04b [--variant pair_v1|pair_v2|half_v1|half_v2] [--role A|B] [--tamper half|swap|nonce|badsig|issuer|expired|holder]
    ../tools/heavy.sh compile-sb_pair_v1 ./compile.sh sb_pair_v1           # circom 2.2.3 --prime secq256r1
    (cd prover && CARGO_TARGET_DIR=../../vendor/target ../../tools/heavy.sh sbzk-build cargo build --release)
    ./fix_gmp.sh && (rebuild)                                             # see gaps: GMP x18 bug
    ./sbzk.sh setup  sb_pair_v1
    ./sbzk.sh check  sb_pair_v1 inputs/180ca04b_pair_v1.input.json
    ./sbzk.sh prove  sb_pair_v1 inputs/180ca04b_pair_v1.input.json out/p.proof
    ./sbzk.sh verify sb_pair_v1 out/p.proof inputs/180ca04b_pair_v1.public.json
    python3 run_tests.py check | proofs
    ./zkid.sh benchmark --size 1k --input ../circom/inputs/jwt/1k/default.json   # their pipeline

## Files

| file | what it is |
| --- | --- |
| `circuits/sb.circom` | our templates |
| `circuits/main/*.circom` | the four mains |
| `prep_inputs.py` | fixture → witness input + expected public values; the tamper modes; v2 re-issue |
| `prover/` | `sbzk` Rust CLI (Spartan2 `zk_spartan::R1CSSNARK` on `T256HyraxEngine`, witnesscalc-linked C++ witness gen) |
| `run_tests.py` | the accept/reject tests |
| `sbzk.sh`, `zkid.sh` | wrappers that put the witnesscalc dylibs on the loader path (`/usr/bin/time` strips `DYLD_*`, so the wrappers set it inside) |
| `keys/`, `out/`, `inputs/`, `build/` | generated, gitignored |

## Vendor pins

| component | pin |
| --- | --- |
| zkID | https://github.com/privacy-ethereum/zkID @ `b395e09c225ff45b003f0087c28e2e208e22f944` (`vendor/zkID`) |
| circom | v2.2.3 (`ad44e915`), `cargo install --root vendor/circom-2.2.3`, symlinked at `vendor/bin/circom`. `~/.cargo/bin/circom` (2.1.8) untouched |
| Spartan2 | 0xVikasRushi/Spartan2 `d687dbb639eccbdd21e62fecec97c5826bc4dbbf` (branch openac-sdk) |
| circom-scotia | `bd39c019dba20d32ce5727e2408632dbca269e82` |
| witnesscalc-adapter | zkmopro `e5a82bcb7d54a4694fc0662c51b01d99134e686c` |
| witnesscalc | zkmopro `707dc54877ad3226042d959d7ec956ae540a9a3e` |
| GMP | 6.2.1 in the witnesscalc build, replaced by Homebrew 6.3.0 |
| circomlib | 2.0.5 (zkID's yarn.lock) |

zkID's `ecdsa-spartan2` won't compile with no JWT circuit compiled (E0282 in `prepare_circuit.rs`), so `jwt_1k` was compiled to build it.

## Failures, gaps, deviations

- **GMP 6.2.1 x18 bug (found here).** witnesscalc builds GMP 6.2.1. On Apple arm64 its `mpn` assembly uses register x18, which Darwin reserves. The result was random segfaults in `__gmpn_mul_1` under `mpz_gcdext` (field inverse), in about 25% of pair witness runs, with the same input each time.
  - Swapping in GMP 6.3.0 (`fix_gmp.sh`) gave 30 of 30 clean runs and all tests passing.
  - zkID's own binary links the same GMP. iOS is also Darwin arm64, so the phone build is probably exposed too (not tested on a phone). Worth reporting upstream.
- **v1 nullifier is unbound**, as the requested statement is written: any holder secret gives a valid proof, so a prover can mint unlimited nullifiers per nonce (test `pair_v1 tamper holder` accepts). v2 fixes this with a holder commitment inside the credential, which costs +30.7k constraints (one SHA block). The enclave track still issues SBcred1, so moving to SBcred2 is an issuer-side change.
- **Deviations from the requested public list.**
  - `sr` is public. The sample bounds only mean something for a known sr, and 48000 isn't identifying.
  - `validAt` plus an expiry check were added: the credential carries an expiry, and ignoring it would be a hole.
  - The bounds are passed as signed sample counts (a negative `dLo` is encoded as p−56).
- **The prover learns the partner's private fields.** A two-role proof needs one party to hold both signed transcripts, so the combiner sees the partner's `os_ts`, rec hash and half. The ZK hides them from the verifier only. Since `os_ts` reveals boot time, a per-role proof (`SBHalf`) plus a private pairing check would avoid this. That design isn't built here: `SBHalf` has no pair binding and publishes the half, so it's a cost reference only.
- **Completeness corner.** `HashModScalarField` rejects digests ≥ p, so about 2^-32 of honest transcripts would fail to prove. A retry with a new attempt fixes it.
- **High-S signatures are accepted**, as ECDSA allows. This doesn't matter for this statement.
- The pub bytes are packed mod p with no canonical check. That's safe because the same bytes are signed by both the issuer and the device.
- `N_TS=1` is fixed at compile time, and the fixtures' `os_ts` are placeholders, not real OS timestamps.
- **No phone run.** All numbers are from the M2.
- **Size lever (estimate, not built).** SHA-256 is 87% of the circuit. The transcript hash has to stay SHA-256 because the enclave signs SHA-256. The credential digest and the nullifier could use a hash that is sound in this field: Poseidon with α=7 (7 ∤ p−1), not circomlib's α=5. That would save about 180k, taking the pair to about 300k constraints.
- **Observation on zkID itself (not exploited).** Their Show circuit hashes claim names with circomlib `Poseidon` (α=5) over secq256r1, where x^5 isn't a bijection. Colliding preimages are random field elements, not packed ≤31-byte names, so practical impact looks low. But it's the same α=5 issue flagged in the gap memo.

## Phone estimate (estimate, not measured)

Basis: zkID's published mobile numbers against the same pipeline measured on this M2.

- **Show circuit:** M2 135 ms, iPhone 17 85 ms (0.63×), Pixel 10 Pro 308 ms (2.3×).
- **Prepare (1920 B JWT):** iPhone 17 2,102 ms, Pixel 10 Pro 5,161 ms. That circuit's constraint count was not measured; ~1.5M is estimated by interpolating the 1k/2k key sizes.

Scaling the pair v1 (M2 ≈ 1.02 s witness + prove) by both routes:
- iPhone 17: ≈ 0.65–0.7 s
- Pixel 10 Pro: ≈ 1.7–2.3 s
- Proof: 60.5 KB
- Proving memory: ~0.9 GB on the M2. zkID reports 2.27 GiB app peak for their ~1.5M Prepare.

A one-role proof would be roughly 0.4 s on iPhone 17 and 1.1–1.5 s on Pixel 10 Pro.
