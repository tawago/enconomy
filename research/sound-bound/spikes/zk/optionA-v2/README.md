# optionA-v2: the half proven from the recording

One proof per phone. It says: this device signed this transcript, and the half in it is what the rule gives on the signed recording. Anyone holding the recording and the signed transcript can make the proof, and anyone can check it. The phone's own arrival code doesn't have to be trusted.

Everything below was measured on the M2 (8 GB, shared) on 2026-09-26, unless it's marked as an estimate. Heavy steps went through `../tools/heavy.sh`, and the logs are in `logs/`.

## Update: aligned with the app/server (POPT v2), 2026-09-26 afternoon

The circuits below were rebuilt against the real app transcript. Everything from "Short version" on describes the first spike (SBv2, one sample rate, key-derived pairTag). It's kept for its measurements, and its circuits (`oa2_*`) still build.

The new circuits are `oa2t_*`:

| file | what |
| --- | --- |
| `../../../../../docs/pop-transcript-v2.md` | the POPT v2 proposal (311 bytes) and what the app/server must change |
| `oa_rate.py` | everything that depends on the rate (L, FIR, B, windows, delta, templates, code_commit) as a function of sr. At 48 kHz it's identical to the old twin (`selftest`) |
| `rectree.py` | rec_root: the same Poseidon7 leaf and node as `poseidon7/p7.py`, with a depth-4 tree over the 2.5 s capture |
| `gen_popt2.py` | generates `oa2t_s48` / `oa2t_s44` (per phone, one circuit per rate), `oa2t_s48_nf` (with the optional nullifier) and `oa2t_pair` |
| `build_fixtures_popt2.py` | POPT v2 fixtures in `../fixtures/popt_v2/`, with real Secure Enclave signatures |
| `prep_popt2.py`, `run_tests_popt2.py` | witness inputs, tamper modes, accept/reject tests |
| `bench_popt2.sh`, `chain_popt2.sh` | prover build, setup and bench, all through `../tools/heavy.sh` |
| `../verifier/popzk.py` | session verifier (per-phone proofs + pair proof), `../verifier/test_session_a.py` |

### Statement now

**Per phone** (`oa2t_s48` for 48 kHz, `oa2t_s44` for 44.1 kHz):

- **Transcript and signature.** The 311-byte POPT v2 transcript is rebuilt at its fixed offsets, with 65-byte SEC1 keys (`04‖X‖Y`) and the `"POPT" | 0x02 | role | attempt` order. It's ECDSA-P-256 signed (over sha256) by the hidden device key.
- **Credential.** The key carries an unexpired SBcred3 issuer credential.
- **Pinned values.** The signed `sample_rate` must equal the circuit's rate, and the signed `delta` must equal the circuit's δ. Own X ≠ partner X.
- **Derived values.** `p_self = a_self − self_os_delta` and `a_partner = a_self ± half` come from signed fields.
- **Audio part.** The rest is the same as before: int16 samples opened under the signed `rec_root`, the self rule in `[p_self − δ, p_self + δ]`, the partner bar in `[p_partner − 150 ms, p_partner + 250 ms]`.
- **Public:** nonce, attempt, roleB, code_commit, the four templates, issuer, sr, validAt.
- **Output:** `halfCommit = Poseidon7(nonce, attempt, roleB, sr, half, salt, X_self, X_partner)`.
- **Private:** everything else, including the three timestamps, self_os_delta, commit_hash, rec_root, the pubs and the half.

**Pair** (`oa2t_pair`):

- **Public:** nonce, attempt, commitA, commitB, srA, srB.
- **Openings.** It opens both commitments (roleB 0 and 1) with crossed X_A and X_B, and X_A ≠ X_B.
- **Ranges.** The halves are i32, and both rates are in [36000, 96000].
- **Verdict.** NEAR is checked by integer cross-multiplication: `34300·N + 40·S ≥ 1` and `120·S − 34300·N ≥ 1`, with `N = hA·srB − hB·srA` and `S = srA·srB`. The 70-bit range checks can't wrap, because |values| < 2^66.

**Removed:** the key-derived `pairTag`. The session link is the public nonce. Crossed keys and A ≠ B are now proven inside the pair proof, from the hiding halfCommits, so nothing public names a device. The pair tag for proof of human is computed by the verifier from the two adapter nullifiers.

**Optional:** `--nf` adds the holder-secret nullifier (`Poseidon7(TAG_NULL; secret, nonce)`, bound to the credential), for the `none` adapter only.

### Results (M2 8 GB, shared; same-session re-run of the old circuit for a fair comparison)

| circuit | constraints | witness | prove, fresh process | prove, warm | verify warm / fresh | peak footprint (prove) | pk = vk | proof file |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| before: `oa2_d2_sig` (SBv2, 48 k, pairTag) | 1,247,378 | 0.35–0.43 s | 4.70 s (3.72 s earlier, less load) | 4.93–5.15 s | 0.28–0.30 / 1.15 s | 1.95 GB | 487 MB | 1,648,319 B |
| **after: `oa2t_s48`** (POPT v2, 48 k) | **1,228,446** | 0.37–0.42 s | **4.49 s** | 4.70–4.76 s | 0.27–0.28 / 1.24 s | 1.93 GB | 470 MB | 1,648,255 B |
| **after: `oa2t_s44`** (POPT v2, 44.1 k) | **1,152,227** | 0.31–0.40 s | 4.70 s | 4.48–4.59 s | 0.25–0.28 / 1.21 s | 1.89 GB | 449 MB | 1,523,455 B |
| after: `oa2t_s48_nf` (+ nullifier) | 1,229,734 | not proved | | | | | | |
| before: `oa2_pair` (one sr) | 1,518 | 2 ms | 51 ms | 50–53 ms | 13–17 ms | 8 MB | 1.3 MB | 39,649 B |
| **after: `oa2t_pair`** (two sr, crossed keys) | **1,612** | 1 ms | 58 ms | 54–57 ms | 15–18 ms / 20 ms | 8 MB | 1.3 MB | 39,649 B |

- **Why the per-phone circuit got smaller (−18.9k).** The tree is depth 4 instead of 6 (2.5 s capture, not the whole 87 s file). That saves 2 Poseidon t=5 nodes per opened leaf, about 18k. The pairTag sponge and the nullifier are gone too.
- **Why the SHA cost didn't grow.** POPT v2 is 311 bytes, the largest size that still fits 5 SHA blocks, the same as SBv2 (265 B). `p_self` and `a_partner` are signed implicitly, as exact functions of signed fields.
- **Time.** Prove time tracks size, but the machine was shared: load average 4–55 during the day. Take ±15%.
- **Compile** (circom, `--O2`): 35 min for s48 (load average ~50), 15 min for s44, 13 min for nf (`--no-c`). Peak 1.6 GB.
- **Setup:** 5.0–5.4 s at 1.6–1.7 GB.
- **Logs:** `logs/compile_oa2t_*.log`, `logs/setup_oa2t_*.log`, `logs/bench_oa2t_*.txt`, `logs/rebench_oa2_d2_sig_same_session.txt`.

### Tests (all logs in `logs/popt2_*.txt`, `../verifier/*.log`)

| suite | result |
| --- | --- |
| `run_tests_popt2.py phones` (C++ witness + full R1CS check) | **48/48**: all 12 sessions × {48k/48k, 48k/44.1k} × 2 roles are accepted, and the public values equal what the verifier derives |
| `run_tests_popt2.py tampers` | **32/32** rejected: half not re-signed, sr swapped, wrong nonce, role flipped, one opened sample +1, a compromised app re-signing a later a_self or an earlier a_partner. Both on 48k/48k and on the mixed session, both roles. Plus the signed `self_os_delta` = 2,401 frames (> 50 ms) and 97 frames (> δ = 96; see gaps) |
| `run_tests_popt2.py pairs` | **28/28**: the 8 NEAR pairs (4 sessions × 2 rate modes) accepted, the 16 NOT_NEAR rejected (incl. b2a5f86d at 60.4 / 60.6 cm). Rejected: srB changed, same key in both roles, a cross-session splice. Made-up halves 0/0 are **accepted by the pair circuit** (expected; only the session verifier stops them) |
| `run_tests_popt2.py edges` | **214/214**: halves at ±3 around both bounds for 10 rate pairs (incl. 48000/44100, 36000/96000, and exact ties at 68,600 Hz). Accept iff the exact rule says NEAR |
| `../verifier/edge_cases.py` (server venv) | 644 cases, integer rule vs `server/pop/verdict.decide(flight_cm(...))`: identical except 8 **exact ties** (flight exactly −20 or 60 cm, possible only at rates like 68,600 = 2 × 34,300, not at 44.1/48 k). There, the server's float flight rounds to 59.99999999999936 and says NEAR. The circuit does what `decide()` means. The server would need `Fraction` or integer math to agree bit for bit |
| `../verifier/check_v2_verdicts_server.py` | 26/26 v2 fixtures: the server's decide/self_os_ok on the signed halves gives the fixture's verdict |
| `../verifier/test_session_a.py` (real Spartan2 proofs) | **23/23**, see `../verifier/test_session_a.log` |

The session verifier run covered:

- **Accepted:** honest NEAR at 48k/48k and at the mixed 48k/44.1k rate, with and without adapter nullifiers (pair_tag computed).
- **200 cm session without a pair proof:** NOT_NEAR.
- **Rejected:**
  - a forced pair proof for 200 cm (`proof_invalid`);
  - a pair proof over made-up halves (`transcript_mismatch`);
  - forced per-phone proofs for half +30, for self_os_delta over tolerance, and for a re-signed late a_self (`proof_invalid`);
  - role swap, one proof in both roles, and two cross-session splices (`transcript_mismatch`);
  - wrong nonce and wrong attempt;
  - a 44.1 kHz proof under the 48 kHz circuit id, and a forced pair proof with srB changed (`proof_invalid`);
  - an unknown circuit, and a vk that doesn't match the pinned id (`circuit_unknown`);
  - another issuer (`issuer_unknown`);
  - another validAt;
  - another session's templates;
  - equal adapter nullifiers (`same_human`).

### Fixtures (`../fixtures/popt_v2/`, 26 files)

- **Coverage.** 12 JBL250 sessions × {`48k`, `mix`}, plus 2 signed tamper fixtures.
- **Signatures.** 104 real Secure Enclave signatures (POPT v2 + POPC v2 per role).
- **What's real:** the audio. Each capture is 2.5 s cut from the field WAV at the fieldtest's t0 − 0.5 s, and rounded to int16.
- **Mixed rate.** In `mix`, B's capture is resampled 48 → 44.1 kHz (`resample_poly` 147/160, exact frame alignment). B's arrivals are re-detected by the twin at 44.1 kHz, with 44.1 kHz templates and FIR. So the 44.1 kHz half is measured, not scaled.
  - Flights agree with the 48k mode within 0.3 cm.
  - Verdicts: 8 NEAR and 16 NOT_NEAR over both modes, as in v1.
- **What's emulated:**
  - `self_os_delta`, uniform in ±1 ms;
  - `p_partner`, the schedule-expected arrival;
  - `play_frame_position` / `play_nano_time` / `rec_frame0_nano_time`, built so the contract's §4.4 formula reproduces `p_self` exactly (`../enclave/emulate.py`);
  - the nonce: `sha256("POPnonce-dev|" ‖ session ‖ "|v2-" ‖ mode)`;
  - attempt 0.

### Ready / not ready

Ready (spike grade):

- **Transcript.** The circuit consumes the exact POPT v2 bytes the proposal defines. Real enclave signatures verify in-circuit.
- **Sample rates.** Per-phone sample rates work end to end: a mixed 48/44.1 kHz session is proven and verified.
- **Distance check.** The cross-multiplied check equals `decide()` except at exact ties, where the circuit is the exact one.
- **Privacy.** No key-derived public value. The pair tag comes from the adapters.
- **Session verifier.** It pins the circuit ids (vk sha256) and the issuer, derives every public input, and links pair ↔ phones.

Not ready:

- **POPT v2 exists only here.** The app and server still sign and check v1. The app has to run the integer twin rule on its int16 capture, and compute a Poseidon7 root.
- **Completeness gap.** The circuit needs `|self_os_delta| ≤ 2 ms`, but the server tolerates 50 ms. Real OS timestamp accuracy hasn't been measured, and all `self_os_delta` values in the fixtures are emulated.
- **One circuit per rate.** Each sample rate needs its own circuit and ~0.45 GB proving key. Only 48 k and 44.1 k exist.
- **Size.** ~1.2M constraints: 4.5 s and 1.9 GB per phone on the M2, estimated 7–10 s and ~2 GB on a Pixel 10 Pro. The proof file is 1.5–1.65 MB because it carries the public templates.
- **Split trust (REVIEW F3).** The trust model is still split: the proof adds security only if capture, rec_root and p_self come from something more trusted than the arrival code.
- **Unaudited primitives.** Poseidon7 (our own parameters), the zk_spartan fork and the zkID ECDSA gadget haven't been audited.
- **Not in the circuit:**
  - the 8 ms flat-block glitch check;
  - the POPC commit (commit_hash) consistency. The server checks it at session time; the verifier can't.
  - nonce freshness and nullifier uniqueness. The caller of `popzk.py` has to do these.
- **Templates are public** and derived from the field seed. The real protocol needs the server to reveal per-(session, role, attempt) code seeds after the session.
- **The prover doesn't refuse an unsatisfied witness.** It turns it into a proof that fails verification (seen in the tests). An app should run `check` first.


## Short version

- **Built and works.** The build covers the circom statement over secq256r1, a Spartan2/Hyrax prover (the OpenAC stack), a Poseidon α=7 hash for the P-256 field, the Merkle recording commitment, the Freivalds self curve, the one-sided partner check, the half commitment, a pair statement, 12 re-signed Secure Enclave fixtures, an integer twin and the tamper suite.
- **Size.** One phone, with signature and credential, is **1.23–1.33 M constraints**: prove **3.5–5.3 s**, 1.9–2.0 GB peak, verify 0.2 s warm (1.1–1.7 s in a fresh process). The proof proper is about 80–110 KB. The serialized proof is 1.65 MB because it carries the 48k public template values.
- **δ barely matters.** The cost comes from the 250 ms template (12,000 samples per window), not from the width of the self window. The range checks are 42%, the barrel shifters 26%, Poseidon7 16%, the signature and credential about 20% of the whole.
- **Every tamper was rejected**, including the reviewer's late-window attack. No NEAR proof could be made for the 100 cm or 200 cm sessions.
- **The trust boundary moved; it didn't go away.** The self window is only as good as the signed `p_self`. If the app signs a late `p_self`, the rule runs from there (shown below). That's the OS-timestamp check, and its accuracy hasn't been measured.

## What's built

| file | what |
| --- | --- |
| `poseidon7/gen_params.py`, `params_t{3,5,16}.json` | Poseidon α=7 parameters for the P-256 base field. The reference Grain-LFSR and round-number scripts, re-implemented in Python. Self-test: reproduces circomlib's BN254 α=5 constants, MDS and round numbers exactly |
| `poseidon7/p7.py`, `circuits/p7.circom` | permutation, sponge, leaf hash, 4-ary tree. Python and circom agree on test vectors |
| `twin2.py` | integer twin of the new receiver: earliest lag with score ≥ 9%, exact circuit math |
| `build_fixtures2.py`, `fixtures/*.json` | SBv2 transcripts signed by the real Secure Enclave keys (`../enclave/sesign`), with SBcred3 credentials from the dev issuer |
| `gen_circuit.py`, `circuits/main/*.circom` | `oa2_d{1,2,5}_{sig,audio}`, `oa2_pair`, `oa2_d2_audio_w60` |
| `prep.py` | fixture → witness input plus expected public values, and the tamper modes |
| `prover/` (`oa2zk`), `oa2zk.sh`, `fix_gmp.sh` | a copy of `../openac/prover` (Spartan2 `zk_spartan`, T-256 Hyrax, witnesscalc C++) with the circuit list changed, plus the same GMP 6.3 fix |
| `run_tests.py`, `bench.sh`, `provable_range.py`, `fa_budget.py` | the tests, benchmarks and analyses |

## Transcript v2 (SBv2, 265 bytes, 5 SHA blocks)

`"SBv2" | nonce(32) | attempt u8 | role u8 | own_pub(64) | partner_pub(64) | sr u32 | half i32 | rec_root(32) | p_self u32 | p_partner u32 | delta u16 | a_self u32 | a_partner u32 | code_commit(32) | n_ts u8 | ts u64`

- **`rec_root`** is a 4-ary Poseidon7 Merkle root.
  - Leaves are 1,024 int16 samples, packed 15 per field element, 69 elements per leaf.
  - The tree is 6 levels deep (4,096 leaves, 87 s at 48 kHz). Missing leaves are zero leaves.
- **`code_commit`** = SHA-256("SBcode2" ‖ the int8 bytes of cI_self, cQ_self, cI_partner, cQ_partner).
- **SBcred3** = "SBcred3" ‖ pub ‖ expiry ‖ holder_commit, where holder_commit = Poseidon7(holder secret). The issuer signs it with SHA-256 and ECDSA P-256.

## Statement (one phone, role R)

**Public inputs:**
- nonce (2 limbs), attempt, roleB
- code_commit (2 limbs)
- the four 12,000-value templates: cI and cQ for own and partner
- issuer key, sr, validAt

**Outputs:**
- `halfCommit` = Poseidon7(nonce, attempt, roleB, half, salt)
- `nullifier` = Poseidon7(holder secret, nonce)
- `pairTag` = Poseidon7(nonce, pubA.x, pubB.x)

Everything else is private, including the device key and all transcript fields.

1. **Signature and credential.** The transcript is rebuilt byte for byte, and its SHA-256 is checked against the hidden device key with ECDSA (zkID gadget, reused through `../openac/circuits/sb.circom`). The device key has an SBcred3 credential from the public issuer and hasn't expired at validAt. The holder secret opens holder_commit. Own pub ≠ partner pub. The signed `delta` equals the circuit's δ.
2. **Recording.** Every opened sample passes a 16-bit range check. Each 1,024-sample leaf is hashed, and its path is checked against `rec_root`.
   - Self leaves start at the leaf holding `p_self − δ − 31`.
   - Partner leaves start at the leaf holding `a_partner − 31`.
   - A 10-stage barrel shifter moves the sample offset inside the leaf to position 0. That's what pins each window to its signed position.
3. **Correlation.** For the self window, the claimed curve I_j, Q_j (j < K = 2δ+1) is checked in one Schwartz–Zippel identity.
   - r and ρ come from a Poseidon7 sponge over nonce, attempt, role, rec_root, p_self, p_partner, δ, a_self, a_partner, code_commit and all claimed I, Q.
   - The samples enter through rec_root and the leaf positions. The template enters through code_commit.
   - The partner's I and Q are computed directly: one lag, 2 × 12,000 products.
4. **Self.** score(a_self) ≥ bar, and score(k) < bar for every k in [p_self − δ, a_self). Also a_self ∈ [p_self − δ, p_self + δ].
5. **Partner.** score(a_partner) ≥ bar, and a_partner ∈ [p_partner − 150 ms, p_partner + 250 ms]. The w60 variant uses [−20, +40] ms.
6. **Half.** half = a_partner − a_self for A and a_self − a_partner for B, and it must equal the signed half. The output is `halfCommit`.

**The bar, without division.** score ≥ 9% is written as env2·B ≥ E·cn2.
- env2 = I² + Q².
- E is the sum of y² over the 12,000-sample window, where y is the 63-tap 8-bit band-pass FIR of x.
- cn2 = Σ cI², computed in the circuit.
- B = round(g²/0.09²) = 4,474,747.
- Each comparison goes through a 96-bit range check. The worst case, full-scale int16 with 8-bit templates, needs 95 bits, far below p.

**Pair statement (`oa2_pair`, 1,518 constraints).** It opens both halfCommits (roles 0 and 1, same nonce and attempt) and checks dLo < halfA − halfB < dHi, i.e. −20 < flight < 60 cm. The verifier also checks that both per-phone proofs carry the same nonce, attempt and pairTag.

**Verifier's own duties:**
- derive the templates from the revealed per-(session, role, attempt) code seed, and recompute code_commit from them;
- pin the issuer key, the circuit (vk) and δ;
- compute dLo and dHi from sr.

The `audio` variants drop part 1. There, rec_root, p_self and p_partner are public inputs, and they stand in for the signed values.

## Template: public, after the reveal

The template is a public input. The verifier derives it from the code seed, which the server reveals after the session. This fits the commit-then-reveal order in the decision memo:

- The partner code needs to be secret only until the phone has committed its recording. The server releases it only after it gets the enclave-signed rec_root.
- By proof time, both codes have been handed out, and they are per attempt and never reused. Publishing them afterwards gives an attacker nothing.
- It's free in the circuit. A private template would need an 8-bit range check and a hash for each of its 48k values: about 0.4 M range constraints plus about 80k of hashing.
- The signed `code_commit` ties the proof to the codes the app actually used. A proof made with another session's template fails the signature (circuit level) or the public-input comparison (verifier level).

The cost is that the proof carries 48k public values, 1.54 MB. A verifier that derives the template itself could take them out of the serialized proof. That isn't done here.

## Hash choice: Poseidon α=7, research instantiation

Why α=7: gcd(α, p−1) is 5 for α=5 and 3 for α=3, so neither x^5 nor x^3 permutes the field. gcd(7, p−1) = 1.

Parameters, 128-bit target (`logs/poseidon7_params.txt`):

| width | R_F | R_P | S-boxes | constraints per permutation | MDS |
| --- | --- | --- | --- | --- | --- |
| t = 16 (sponge) | 8 | 47 | 175 | 700 | 3rd Cauchy candidate |
| t = 5 (4-ary node) | 8 | 46 | 86 | 344 | 5th Cauchy candidate |

How they were derived:
- Round numbers use the reference inequalities: statistical, interpolation, three Gröbner bounds and the eprint 2023/537 binomial bound. The reference margin is applied (R_F + 2, R_P × 1.075).
- The MDS matrix is a Cauchy matrix from the Grain stream. It's accepted only if the characteristic polynomial of M^i is irreducible for i = 1..2t. That's sufficient for no invariant subspace trails, and stricter than the reference's Algorithms 1–3. That's why later candidates were taken.
- **Validation:** the same code regenerates circomlib's BN254 α=5 round constants and MDS for t = 2 and 3 exactly. Its round numbers for t = 2..17 match circomlib's table after circomlib's rounding of R_P up to a multiple of t (`logs/poseidon7_selftest.txt`).
- Not audited. Treat it as a research instantiation.

**SHA-256 instead, measured.** One 2 KB leaf (1,024 samples) costs **1,015,833 constraints** in circomlib on secq256r1 (`t_sha2k`). The same leaf in Poseidon7 costs **19,884**: 16,384 for the range checks and 3,500 for the hash. Opening 26–27 leaves with SHA would be about 27 M constraints, so SHA is out.

## Twin vs the reference, and fixtures

`twin2.py` runs on 12 sessions × 2 rounds × 4 arrivals = 96 arrivals (`logs/twin2_all.txt`).

| check | result |
| --- | --- |
| twin (integer) vs fieldanalysis float correlation, same rule (earliest ≥ 9%, 0 ppm) | 81/96 identical, 95/96 within 1 sample, 1 off by 4 samples (b2a5f86d A_at_B, score 9.01%, right at the bar). The twin is never later |
| twin vs result.json ("first" rule) | 0.08–0.40 ms earlier (4–19 samples), matching the audio implementer's 0.08–0.42 ms |
| flight, twin vs result.json | −5.4 to +2.1 cm. **Verdict agrees 24/24 rounds** |
| scores | the first crossing sits just above the bar (9.0% and up). The highest score more than 1 ms before an arrival is 5.5%. The twin's FIR normalization reads a little higher than fieldanalysis' 4.9% |

**Fixtures v2** (`fixtures/`, round 0, 72 real Secure Enclave signatures: 12 sessions × 2 roles × 3 δ):
- halves from the twin;
- `p_self` = the true self arrival minus an offset drawn uniformly from [−δ, δ], seeded per session, role and δ. This is **emulated**: native timestamps don't exist yet;
- `p_partner` = the start of the schedule-derived web window plus 150 ms.

Verdicts match the v1 fixtures 12/12. Round-0 flight changes by −2.9 to +1.4 cm with the rule change. b2a5f86d (the 60 cm label) reads 60.4 cm → NOT_NEAR, as in v1 (62.9).

## Results (session 180ca04b, role A)

| circuit | δ | constraints | witness (C++) | prove, fresh process | prove, warm reps | verify warm / fresh | peak footprint (prove) | pk = vk | proof file |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| sig + audio | 1 ms | 1,226,950 | 0.33 s | 3.49 s | 3.5–3.8 s | 0.19–0.21 / 1.15 s | 1.93 GB | 477 MB | 1,648,319 B |
| sig + audio | 2 ms | 1,247,378 | 0.35 s | 3.72 s | 3.8–4.5 s | 0.20–0.29 / 1.15 s | 1.89 GB | 487 MB | 1,648,319 B |
| sig + audio | 5 ms | 1,329,918 | 0.37 s | 5.30 s | 4.8–7.2 s | 0.22–0.26 / 1.72 s | 2.01 GB | 527 MB | 1,648,319 B |
| audio only | 1 ms | 982,548 | 0.36 s | 3.02 s | 2.9–3.2 s | 0.11 / 0.95 s | 1.00 GB | 384 MB | 1,613,935 B |
| audio only | 2 ms | 1,002,976 | 0.26 s | 3.53 s | 3.0–3.1 s | 0.10–0.11 / 0.94 s | 1.15 GB | 395 MB | 1,613,935 B |
| audio only | 5 ms | 1,085,516 | 0.29 s | 3.49 s | 3.6 s | 0.18–0.19 / 1.10 s | 1.85 GB | 459 MB | 1,648,223 B |
| audio only, partner window w60 | 2 ms | 1,002,976 (same) | | | | | | | |
| pair | – | 1,518 | 2 ms | 51 ms | 50–53 ms | 13–17 ms | 8 MB | 1.3 MB | 39,649 B |

How to read the table:
- **Proof size.** The proof file carries the public values, and the templates alone are 48,000 × 32 B = 1.54 MB. The proof proper is about 78 KB (padded to 2^20) or about 112 KB (padded to 2^21). These come from subtraction, not a separate measurement.
- **Setup** takes 3.6–5.0 s at 1.8–2.2 GB RSS.
- **Wall time for one fresh prove process:** 6.0–10.1 s (heavy.sh). This includes 0.9–5 s of pk loading.
- **Signature and credential share:** 244k constraints, SBv2 5 SHA blocks, SBcred3 2 blocks, 2 ECDSA, 4 Poseidon7 sponges. It adds about 0.4–1.8 s to the prove.
- **The partner window changes nothing in cost.** Only two constants differ; confirmed by the w60 compile. What it changes is the false-accept budget (below).
- **Machine load.** The machine was shared and swapping (5.8 GB of swap in use during the compiles), so times spread up to ±30%.

**Where the 1.0 M audio constraints go** (d2, counted from the circuit and matching the compile within 0.1%):

| part | constraints | share |
| --- | ---: | ---: |
| int16 range checks, 26 leaves × 1,024 samples × 16 | 426k | 42% |
| barrel shifters, 10 stages × about 13k, self and partner | 260k | 26% |
| Poseidon7: leaves 91k, paths 55k, FS sponge 19k, commitment 0.7k | 165k | 16% |
| self Freivalds identity (powers, prefix sums, 3L) | 61k | 6% |
| partner I, Q, E (3L) | 36k | 4% |
| energy, cn2 | 36k | 4% |
| per-lag rule, 193 × about 103 | 20k | 2% |

## Tampers (all rejected)

The tests ran through witness generation plus constraint checks (wasm and C++ `check`), and through real proofs.

| test | where | result |
| --- | --- | --- |
| Reviewer's late-window attack: claim a later self arrival (a_self = p_self + δ) | audio d1/d2/d5, both roles, 180ca04b and 9afb91c6 | rejected by the self rule: the real arrival inside [p_self − δ, a_self) scores ≥ bar (per-lag range `rk[j]`, named in the C++ trace) |
| Same, with the lie signed by the enclave (compromised app, valid signature) | sig d2 on 180ca04b; sig d1/d2/d5 on all six 100/200 cm sessions, both roles | rejected by the self rule. A real proof forced from the bad witness (9afb91c6 A) fails verify with InvalidSumcheckProof. One case (7711d899 A, δ=5) was vacuous: the emulated offset put the honest arrival exactly at p_self + δ, so no later lag was claimable |
| Shift the window start (p_self + 200 samples) | sig: signature fails. audio: the witness is valid for the moved window (9afb91c6 A would read a later arrival), but the proof's public pSelf ≠ the pinned value, so the verifier rejects | the window is only as good as the signed p_self |
| Later echo as self arrival (strongest peak after the arrival, 6–15 samples later, score 38–48%) | audio, 4 cases per δ | rejected (self rule) |
| Earlier partner arrival, 100 samples early, no peak there | audio all δ; sig resigned on all 100/200 cm sessions | rejected (partner score < bar) |
| Altered claimed score, I_j + 1 | audio all δ | rejected (Freivalds identity) |
| Altered sample in an opened chunk (+1) | audio all δ, sig d2 | rejected (Merkle path) |
| Sample out of int16 (40000) | audio d2 | rejected (range check) |
| Wrong Merkle path (off-path child +1); leaf index shifted by one | audio d2 | rejected (path, index) |
| Swapped role / sign | sig: signature fails. audio: halfCommit/roleB ≠ the pinned publics; a real proof checked against flipped roleB is rejected at verify | rejected |
| Template from another session | sig: signature fails (code_commit). audio: the witness fails the arrival rule; a real proof checked against the other template is rejected at verify | rejected |
| a_self outside p_self ± δ | audio d2 | rejected (Σu constraint) |
| Altered halfCommit, pSelf or template in the verifier's public input; one flipped proof byte | real d2 proof | rejected (`logs/verify_public_tamper.txt`) |

Counts:

| run | result |
| --- | --- |
| audio d2 | 52/52 |
| audio d1/d5 | 56/56 |
| sig d2 tampers | 16/16 |
| honest sig, 12 sessions × 2 roles × 3 δ | 72/72 accepted, public outputs equal Python's |
| pair, d2 | 12/12: 4 NEAR accepted, 8 NOT_NEAR rejected |

**100 and 200 cm end to end** (7711d899, d1ee4fb0, ef0b6e11, 9afb91c6, d283370f, f3ff0ee8; δ = 1, 2 and 5 ms; `logs/notnear_d*_wasm.txt`):
- Honest per-phone proofs are accepted, and the pair statement rejects them: 126/126 as expected, one vacuous case skipped as noted above.
- Real Spartan2 proofs for 9afb91c6 and d1ee4fb0 (both roles) verify. A pair proof forced from their halves fails verify (`logs/e2e_notnear_proofs.txt`).
- **The smallest flight any accepted witness can reach** (`logs/provable_range.txt`): the self arrival is forced, so only the partner lag can move, and moving it earlier needs a lag ≥ bar. The minimum is therefore the honest flight: 98.3, 96.5, 110.8, 210.4, 225.1 and 219.4 cm. Allowed later partner lags only push the flight up, to 402–707 cm.

## False-accept budget of the one-sided partner check

The proof accepts any lag ≥ 9% in the window. A cheater gains only from an earlier one, which has to be a chance match.

Chance level was measured with 64 wrong codes per cross window, using the twin's normalization, on 24 windows (`fa_budget.py`):
- the highest null score was 7.10%;
- the Gumbel tail gives P(chance ≥ 9% anywhere in 19,200 lags): median 6.7e-7, worst window 1.2e-5.

Per attempt (upper bound, scaled by window length):

| window | lags | median | worst window | worst, with one retry |
| --- | ---: | ---: | ---: | ---: |
| w400 [−150, +250] ms | 19,200 | 6.7e-7 | 1.2e-5 | 2.4e-5 |
| w150 [−50, +100] ms | 7,200 | 2.5e-7 | 4.5e-6 | 9.0e-6 |
| w60 [−20, +40] ms | 2,880 | 1.0e-7 | 1.8e-6 | 3.6e-6 |

On the web data only w400 is complete: cross arrivals sat 74–138 ms late. The tighter windows need native timestamps and a calibrated latency in `p_partner`.

## Remaining gaps

- **`p_self` is the anchor.** The proof enforces the rule from the signed p_self. An app that signs a late p_self moves the window, and the audio-only run above shows that's all it takes. The defense is the attested app plus the OS-timestamp check, whose accuracy hasn't been measured. `p_self` is emulated in the fixtures.
- **The partner arrival is one-sided.** The proof alone admits any lag ≥ bar in the window. The signed a_partner pins the value, and the false-accept table bounds the cheat.
- **Not in the circuit:** the 20 ms flat-block glitch check. The −20 cm floor lives in the pair statement.
- **The fixed 9% bar is fitted to one room.** In noise, real arrivals can fall below it: a completeness loss that means more retries.
- **Mac recordings are float32, rounded to int16.** The app has to record and commit int16.
- **Poseidon7 is our own re-implementation** of the reference parameter scripts. It's validated against circomlib but not audited. zk_spartan (the 0xVikasRushi fork) is unaudited too.
- **The prover doesn't check satisfiability.** `oa2zk prove` turns an unsatisfying witness into a proof, which verify then rejects (seen). Harmless, but a real app should run `check` first.
- **Privacy.** The nonce and the templates are public, so the two phones' proofs link to each other. pairTag does the same by design. The combiner that makes the pair proof sees both halves and salts.
- **Keys and proof size.** pk and vk are 0.48–0.53 GB each (they carry the R1CS). The serialized proof carries 1.54 MB of template.
- **Size levers, estimates only (not built):**
  - p_self public: the verifier pre-shifts the self template, saving about 130k;
  - shared Merkle nodes for the contiguous leaves: about −40k;
  - commit-and-prove for the curve through Spartan2's precommitted witness and challenges: −20k to −46k;
  - the range checks (42%) stay as long as samples are packed for hashing.

## Phone estimate (ESTIMATE, not measured)

The basis is OpenAC on the same stack: M2 1.02 s → iPhone 17 about 0.65×, Pixel 10 Pro about 1.7–2.3× (`../openac/README.md`).

| | M2, measured | iPhone 17, estimate | Pixel 10 Pro, estimate |
| --- | --- | --- | --- |
| per phone, sig, δ = 2 ms (witness + prove) | 4.1 s | about 2.5–3 s | about 7–10 s |
| memory | 1.9 GB peak footprint | about 2 GB | about 2 GB, likely too much for mid-range Android |
| pk on the device | about 490 MB | | |

## Run

    PY=../../../../proximity-echo/.venv/bin/python3; H=../tools/heavy.sh
    python3 poseidon7/gen_params.py --selftest; python3 poseidon7/gen_params.py 3 5 16
    $PY twin2.py all; $PY build_fixtures2.py; $PY fa_budget.py; $PY provable_range.py
    $PY gen_circuit.py p7; for d in 1 2 5; do $PY gen_circuit.py oa2 $d audio; $PY gen_circuit.py oa2 $d sig; done; $PY gen_circuit.py pair
    $H compile-X ./compile.sh oa2_d2_sig            # each circuit; 8-15 min, 1.2-2.5 GB
    (cd prover && CARGO_TARGET_DIR=../../vendor/target $H build cargo build --release); ./fix_gmp.sh; (rebuild)
    $PY prep.py 180ca04b 2 A sig; ./bench.sh oa2_d2_sig 180ca04b_d2_A_sig
    python3 run_tests.py tamper_audio 2 --wasm; python3 run_tests.py tamper_sig 2 --wasm
    python3 run_tests.py honest 2 --wasm; python3 run_tests.py notnear 2 --wasm; python3 run_tests.py pairs 2 --wasm


## Follow-ups from review (2026-09-26) — status after the POPT v2 pass

- **Sample rate.** DONE in `oa2t_pair` (cross-multiplied, both signed rates). Was: the pair circuit assumes one rate, but the app/server let each phone use its own (`docs/pop-contract.md` §4.2; the server computes `half_A/sr_A − half_B/sr_B`). Change the pair check to integer cross-multiplication with both signed rates.
- **Pair tag.** DONE: removed; crossed keys proven inside the pair proof from hiding commitments; pair tag from the adapter nullifiers in `../verifier/popzk.py`. Was: it's derived from the nonce and both device keys, so the issuer can recompute it and name the pair. Replace it with a random pairing secret signed by both phones.
- **Session verifier.** DONE: `../verifier/popzk.py`, 23/23 end-to-end tests. Was: implement the pair ↔ per-phone binding checks (`review/verify_session.py` is a sketch). Without it, a pair proof with made-up halves verifies.
- **One human per role.** Verifier side DONE (`same_human`, pair_tag); the adapters themselves live in the server. Was: out of scope for the circuit. It goes in a proof-of-human adapter (e.g. World ID with a per-session action; distinct nullifiers mean distinct humans).
