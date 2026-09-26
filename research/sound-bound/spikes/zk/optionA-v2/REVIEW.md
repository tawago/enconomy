# Review of optionA-v2, 2026-09-26

Adversarial review of the builder's README and code in this folder. I didn't edit the builder's files. What I added is in `review/`:

- `review/attacks.py`: builds the new attack inputs (`review/inputs/`).
- `review/verify_session.py`: a verifier sketch that does the README's "verifier's own duties" and the cross-proof checks in code.
- `review/pairtag_deanon.py`: recovers who met from the public pairTag.
- `review/run.sh`: every proof run, as one `../tools/heavy.sh review-oa2` job (105 s wall). Output: `review/logs/run.txt`.

The M2 was shared and loaded at the time (load average 10 to 19, another session held the heavy lock before me).

## Bottom line

The circuits are sound for what they state. I found no under-constrained signal, no leaf-alignment hole, no Fiat-Shamir omission and no overflow. Every forgery I built was rejected, including four real forced proofs.

The unbound window start from the option A review is fixed. Both windows now open from one signed Merkle root at positions pinned by signed values.

"A verified NEAR pair proof implies an honest NEAR, given an honest attested app" holds **only together with verifier code that doesn't exist yet**:

- On its own, the pair proof accepts made-up halves. I made a real, verifying NEAR pair proof for the 200 cm session (attack X4).
- It's rejected only when the verifier also checks: commitA and commitB against the two per-phone halfCommits, pairTag equality, the derived inputs and sr.
- The README lists those checks in prose. No code does them, and the `pairs` test never links a pair proof to per-phone proofs.
- With my verifier sketch in place, all the splices and fabrications are rejected.

Two more things about the claim itself:

- "Honest NEAR" means two credentialed devices were near each other, not two people. One person with two phones passes. The fixtures themselves are two keys in one Mac's Secure Enclave.
- With an honest app, the proof re-derives what the app already signed. Under a compromised app, the recording and p_self are as forgeable as a_self. The added security exists only if capture, rec_root and p_self sit in a component that's more trusted than the arrival code. That's not today's architecture.

## 1. Reproduction (through heavy.sh)

| run | builder | re-run |
| --- | --- | --- |
| oa2_d2_sig honest prove, 180ca04b A (fresh process) | 3.72 s, 1.89 GB peak, 1,648,319 B | prove **3.96 s** (witness 0.42 s, pk load 2.0 s), peak footprint **1.96 GB**, 1,648,319 B |
| same, 180ca04b B | – | prove **3.88 s**, peak **2.00 GB** |
| verify, fresh process | 1.15 s | **1.24 / 1.17 s** ACCEPT (vk load 1.4–1.5 s on top) |
| oa2_pair honest, 180ca04b | prove 51 ms, verify 13–17 ms | prove **48 ms**, verify **20 ms**, ACCEPT, 39,649 B |
| constraint counts | d1/d2/d5 sig 1,226,950 / 1,247,378 / 1,329,918; pair 1,518 | same numbers in the compile logs. The oa2_pair r1cs header also shows 1,518 |
| end to end, 180ca04b (A proof + B proof + pair proof, my verifier) | – | **NEAR accepted** |

I didn't re-run setup, the compiles, or the twin and fixture builds.

## 2. New attacks (none in the builder's list)

Per-phone attacks run on oa2_d2_sig with real Secure Enclave-signed fixtures. For each one: C++ witness plus R1CS `check`, then a real proof forced from the witness (the prover doesn't refuse), then `verify` against the honest public values.

| # | attack | check | forced real proof |
| --- | --- | --- | --- |
| X1 | **Merkle path from another position.** Self leaves and paths of leaves leafS+1 … leafS+13, with the index input left at leafS | REJECT (MerklePath, digit selection) | **REJECT** (InvalidSumcheckProof) |
| X1b | **Leaf moved inside its parent.** The first self leaf's level-0 children swapped, so the leaf sits in its neighbour's slot | REJECT (MerklePath) | **REJECT** |
| X2 | **Window start re-split.** leafS − 1 with offset + 1024, so the same start in samples | REJECT (Num2Bits(10) on oS; Freivalds then fails too) | **REJECT** |
| X6 | **Role-ordered template swap.** A's proof with cI_s ↔ cI_p swapped and code_commit set to what B signed (a real signed value) | REJECT (ECDSA: A signed the other order; the partner bar then fails too) | **REJECT** |
| X7 | **Curve shifted by one lag.** I, Q claimed as the true curve of the next lag, so a structured lie, not +1 | REJECT (Freivalds identity) | **REJECT** |
| X3 | **Cross-session splice in the pair.** 180ca04b's nonce and commitA (30 cm), with 9afb91c6's commitB (200 cm) | REJECT (Pair: commitB opening) | **REJECT** |
| X5 | **One role in both slots.** commitA reused as commitB | REJECT (commitB opening: roleB = 1 is hashed in) | **REJECT** |
| X8 | **i32 wrap.** halfA − 2³², so that halfA − halfB looks NEAR mod 2³² | REJECT (Num2Bits(32) on halfA + 2³¹) | **REJECT** |
| X4 | **Made-up halves, combiner side.** 9afb91c6 (200 cm), halfA = halfB = 0, fresh salts and commitments | **ACCEPT** | **pair verify ACCEPT**. Rejected only by my verifier: commitA ≠ the per-phone halfCommit_A |
| E1 | **Cross-session, end to end.** 9afb91c6 A proof + 180ca04b B proof + 180ca04b pair proof | – | my verifier: B's SNARK is valid, its nonce/code/templates ≠ derived → REJECT |
| E2 | **One proof in both roles.** 180ca04b A proof submitted as B | – | my verifier: roleB and templates ≠ derived → REJECT |
| E3 | **pairTag deanonymisation.** Nonce and pairTag of 180ca04b, 100 "enrolled" pubs | – | the real pair found among 9,900 candidates in 36 s of pure Python (`review/logs/pairtag_deanon.txt`) |

Not built because the statement already rules them out on paper:

- **Partner lag outside the window via field wrap.** a_partner and p_partner are signed u32. The two 33-bit range checks can't wrap. In the audio variant, a_partner = HM + 1024·leafP + oP with 12- and 10-bit checks.
- **Non-canonical leaf index.** leafS goes through Num2Bits(12), and oS ∈ [0, 1024), so leafS is unique for a given p_self.
- **Hash collision on truncated fields.** code_commit is carried as two range-checked 128-bit limbs, so nothing is truncated. The circuit outputs are full field elements.

## 3. Soundness audit

Things checked and OK:

- **`<--` usage.** None in the generated code, `oa2lib.circom` or `p7.circom`. It appears only in circomlib (Num2Bits, IsZero, LessThan) and in the zkID ECDSA gadget, which the OpenAC review covered.
- **Unused inputs.** Every private input is used. The compiler reports 48 private inputs "not in witness" for sig and 2 for audio. Those are signals fixed by linear constraints (byte → bits recomposition, aSelf/aPartner through `usum` and `oP`) and substituted away. That's benign.
- **Leaf alignment.** oS = p_self − δ − 31 − 1024·leafS goes through a 10-bit check, and leafS through a 12-bit check. So leafS and the offset are unique. `Barrel1024` gives out[i] = in[i + o] (stage sizes checked), and the leaf count covers NS + 1023 (13 × 1024 ≥ 13,277). The partner side works the same way from a_partner.
  - Merkle: the digit selection formula is right for all four digits, idx = first + i, and the path goes to the signed root.
  - Leaf hash (t = 16 sponge) and node hash (t = 5) are different permutations with different tags.
  - The int16 check is on x + 32768, and the packing (15 × 16 bits = 240 < 256) is injective.
- **Index windows.** The self Freivalds uses x[p_self − δ + k], k < K + L − 1. The energy uses y centred on the same samples, and h is symmetric. The indexes stay inside NS = 12,254 (maximum index used: 12,253). The partner side stays inside NP = 12,062.
- **Freivalds.** acc = r^(L−1) Σ_j r^j Σ_n (cI + ρcQ)[n]·x[n + j] = lhs2, exact. Soundness error ≤ (N + L)/p ≈ 2⁻²⁴¹.
- **Fiat-Shamir.** r and ρ come from the sponge over nonce, attempt, roleB, recRoot, p_self, p_partner, δ, a_self, a_partner, code_commit, I and Q.
  - Everything the identity depends on is fixed before the challenge. The samples are fixed through recRoot + p_self (Merkle binding), and u through a_self (monotone, with Σu = a_self − p_self + δ).
  - The templates are not absorbed. They're bound only through code_commit, which the verifier recomputes as SHA-256 of the templates it derives. That's sound, but only while the verifier really derives both. Absorb them if the templates ever become private or prover-supplied.
  - At the Spartan level, the transcript absorbs the vk digest and the public values before comm_W (`r1cs/mod.rs:809–850`, d687dbb).
- **The bar.** D = E·cn2 − B·env2 is compared through W = 96-bit range checks, and the signs are right: D − 1 ≥ 0 before the arrival, −D ≥ 0 at it.
  - All the quantities are exact integers below p, because I and Q are forced to the true correlation.
  - Worst case: env2·B needs 95 bits and E·cn2 needs 89 bits, the same with −128 as with 127 in the template.
  - The claim "95 bits, far below p" holds. W only affects completeness. Soundness would need |D| near p − 2⁹⁶, which can't happen.
- **Half, per role.** half = (1 − 2·roleB)(a_p − a_s). That's t_BA − t_AA for A and t_BB − t_AB for B, as in the decision memo.
  - The role byte is built from the roleB bits (0x41 / 0x42), and the signed i32 has to equal half.
  - The pair circuit hard-codes roleB 0/1 inside the two commitments, and checks −56 < d < 168 (−19.6 to 59.7 cm at 48 kHz).
- **Nullifier and pairTag.** There's one nullifier per (holder secret, nonce). The holder secret has to open the credential's holder_commit, so one credential gives one nullifier per session. xO ≠ xP is enforced.
  - The pairTag equality check stops a third device from joining a session with a borrowed nonce.
  - A key and its negation share x, but the negated key has no credential.
- **Poseidon α = 7.** gcd(7, p − 1) = 1. The params JSON uses the P-256 base field (checked: p equals P-256's p, Grain n = 256). The circom constants equal the JSON.
  - Recomputed by hand, the interpolation bound gives R_F + R_P ≥ 49 for t = 16 and 48 for t = 5. With R_F = 6 that's R_P = 43 / 42. With the margin that's R_F 8 and R_P 47 / 46, as stated.
  - It's a Cauchy MDS with a stricter-than-reference invariant-subspace test. The permutation layout is 4 full + R_P partial + 4 full rounds.
  - One note: Grain's init doesn't encode α (neither does the reference), so the constants are the ones an α = 5 instance with the same (p, t, R_F, R_P) would get. That's harmless.
  - Still an unaudited instantiation, as the README says.

## 4. Findings

**F1 (major; critical if shipped as is): the pair's links to the per-phone proofs exist only in prose.**

- `oa2_pair` binds only (nonce, attempt, commitA, commitB, dLo, dHi). Whoever holds the salts can commit to any halves. X4 is a real, verifying NEAR pair proof for a 200 cm session.
- What stops it is the verifier comparing commitA and commitB with the per-phone halfCommits, plus pairTag equality, the derived templates and code_commit, the pinned issuer/vk/δ, dLo and dHi from sr, and nonce freshness.
- None of that is implemented. `oa2zk verify` compares one proof with a JSON that `prep.py` wrote from the fixtures, and `run_tests.py pairs` builds pair inputs straight from the fixtures.
- The "12/12 pairs" and "no NEAR for 100/200 cm" results show the pair *circuit* is right. They don't show that a session verifier rejects a cheat.
- Fix: ship the session verifier, e.g. `review/verify_session.py`. It derives every public input, reads the outputs from the proofs, checks the pairTags are equal and the nullifiers differ, and verifies the pair against the two halfCommits. It rejects X4, E1 and E2 and accepts the honest 180ca04b session.

**F2 (major, privacy; not in the gap list): pairTag deanonymises the devices to anyone who knows the device public keys.**

- pairTag = H(nonce, xA, xB), and the nonce is public. The issuer knows every enrolled pub. Testing a suspect against N devices costs N hashes, and all pairs cost N² (E3).
- This brings back exactly the issuer de-anonymisation that the holder-secret nullifier was meant to prevent (ZK gap research §3). The README says pairTag "links the two proofs by design". It doesn't say it names them.
- Fix: pairTag = H(nonce, k), with k a random pairing secret the phones exchange over BLE or QR and put in both signed transcripts (+32 bytes, a few constraints). Or derive it from both holder secrets through a two-party commitment.

**F3 (major, claim framing): the proof adds security only under a split-trust model the app doesn't have.**

- The `resign_late` and `resign_early` tests model an app whose enclave will sign a false a_self or a_partner, but which still commits the genuine recording and the genuine p_self.
- Any code that can feed the enclave a false a_self can just as well feed it a synthesized recording (rec_root) and a shifted p_self. The README concedes p_self but not rec_root.
- With an honest app, the per-phone proof re-derives what the signature already covers. So "the phone's own arrival code doesn't have to be trusted" is true only if capture, the rec_root computation and the p_self timestamp run in a component that's more trusted than the arrival code (a separate attested module or an OS service). Otherwise option A still adds no security, as the gap research says.
- Fix: say so in the README, or name the trusted capture component.

**F4 (major for "proof of presence", not a circuit bug; not in the gap list): one person with two phones fills both roles.**

- Holder secrets are chosen by the user and never seen by the issuer, so two credentialed devices of one person give two different nullifiers. xO ≠ xP and pairTag don't care who owns the keys.
- The fixtures prove it: both roles are two keys in the same Mac's Secure Enclave, and the 180ca04b session verifies end to end.
- The verifier also doesn't check nullifier_A ≠ nullifier_B (it isn't among the listed duties), so even one holder secret shared across two devices isn't caught.
- A device can also hold several unexpired credentials (after re-issue). Then it has several nullifiers per session.
- Fix: this is an issuer policy (one live credential per person, bound at enrollment), plus a nullifier-inequality check in the verifier. The README should state that NEAR means two devices, not two people.

**F5 (minor): sr is per proof, and the pair assumes one rate.**

- Each per-phone proof carries its own public sr, and dLo and dHi are computed "from sr". A Mac at 44.1 kHz with an Android at 48 kHz can legitimately sign different rates. The halves are then in different units, and halfA − halfB means nothing.
- Fix: require srA = srB in the verifier (or scale inside the pair statement), and fix one capture rate in the app.

**F6 (minor): other gaps missing from the list.**

- The Merkle tree doesn't commit the recording length. Missing leaves hash like digital silence. That's harmless for soundness.
- 32-byte fields (partner pub, rec_root) are packed mod p, so non-canonical encodings alias. Only a lying app could use that, and the partner pub isn't under the credential. Harmless under an honest app.
- The nullifier ignores the attempt, so a retry's proof collides with the first attempt's under a double-use database. That's intended if "one presence per session" is the rule, but write it down.

## 5. The builder's gap list

| gap | stated? | comment |
| --- | --- | --- |
| p_self is the anchor | yes | also rec_root, see F3 |
| one-sided partner lag | yes | the FA budget is fair. With an honest app the lag is signed anyway |
| glitch check not in the circuit | yes | the −20 cm floor catches a 3.4 m shift only for separations below about 3.2 m. A 3.2–4.0 m pair with a glitch in B's file reads NEAR. So it depends entirely on the phone-side flat-block check |
| 9% bar fitted to one room | yes | |
| float32 vs int16 | yes | |
| Poseidon7 / zk_spartan unaudited | yes | |
| prover makes proofs from bad witnesses | yes | confirmed by every forced proof above. Verify always rejected |
| linkability: nonce, templates, pairTag | partly | pairTag **identifies** the devices to the issuer (F2), it doesn't just link |
| verifier duties | prose only | F1 |
| one person, two devices; nullifier inequality | **no** | F4 |
| sr mismatch | **no** | F5 |

## 6. Files

- `review/logs/run.txt`: all proofs, checks and the session verifier runs.
- `review/logs/pairtag_deanon.txt`: E3.
- `review/out/*.proof`: the honest and attack proofs (git-ignored by the folder's `out/` and `inputs/` rules).
