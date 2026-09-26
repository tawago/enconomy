# Review: openac-t256 (sound-bound on secq256r1 + Spartan2), 2026-09-26

Adversarial review of `circuits/sb.circom`, `prover/src/main.rs`, `prep_inputs.py`, and the zkID and Spartan2 pieces they lean on. No builder code was changed. I added one file, `review_attacks.py`, which builds the attack inputs below.

**Bottom line.** The numbers reproduce. The circuit does what the README says, and I found no under-constrained signal in `sb.circom`. It has one real statement gap: **nothing forces pubA ≠ pubB**. One credentialed key that signs both roles gets a valid NEAR proof. I proved and verified that end to end. There is also a privacy leak the README doesn't list: the **nonce is public**, so the two participants' proofs link to each other. And a verifier that doesn't pin the bounds itself can be fooled.

## 1. Re-run (all through `tools/heavy.sh`, M2 8 GB, fixture 180ca04b)

| run | mine | builder |
| --- | --- | --- |
| SBHalf v1, prove (fresh process) | witness 96 ms, prove 587 ms, wall 1.45 s, RSS 0.46 GB | 86 / 587 ms median, wall 1.2 s, 0.48 GB |
| SBHalf v1, verify (fresh) | 243 ms (+288 ms vk load), wall 0.6 s | 227–268 ms |
| SBPair v1, prove (fresh), run 1 | witness 179 ms, prove 918 ms, wall 2.05 s, RSS 0.57 GB | 157 / 866 ms median, wall 1.9 s, 0.86 GB |
| SBPair v1, prove (fresh), run 2 | witness 155 ms, prove 891 ms, wall 1.76 s, RSS 0.72 GB, footprint 0.50 GB | footprint 0.44 GB (their prove log) |
| SBPair v1, verify (fresh) | 391 / 389 ms, ACCEPT | 373–394 ms |
| proof size | 60,543 B | 60,543 B |
| constraints / wires | 481,159 / 476,558 (compile log, n_witness) | same |

- Timing matches within noise.
- Peak RSS moves between 0.57 and 0.86 GB across runs because the pk is mmapped, so its file pages count toward RSS depending on the page cache. "Peak memory footprint" (0.44–0.50 GB) is the steadier number to quote.
- Two proofs of the same input differ byte for byte, as expected with randomized blinding.

## 2. Tamper attacks on real fixtures

Inputs come from `review_attacks.py <outdir>`. "check" means witness generation plus a direct R1CS check. "proof" means a real Spartan2 prove and verify.

| # | attack | result |
| --- | --- | --- |
| 1 | **Swap roles on the touch fixture 2dc2eb59.** Swapped d = −22 (−7.9 cm) sits *inside* the bounds, so only the role byte and the crossed pubs can stop it. | **rejected** (ECDSA fails for devA and devB) |
| 2 | Splice: A slot from 180ca04b and B slot from b550cf12, both NEAR, 180ca04b's nonce | **rejected** (devB ECDSA fails, and the crossed-pub transcript fails) |
| 3 | Both halves +1000 samples, so d is unchanged, without re-signing | **rejected** (ECDSA fails for both) |
| 4 | v2: holder A's secret with `me = 1` | **rejected** (holder commit fails) |
| 5 | 200 cm fixture 9afb91c6, with the prover putting dHi = 10⁶ in its witness | check **accepts**. Proof verified against the honest expected publics: **rejected** (public IO mismatch). Proof verified against publics that echo the proof's dHi: **accepted**. So soundness here lives entirely in the verifier recomputing dLo/dHi. |
| 6 | **Self-pairing.** One key (a throwaway dev key, credential from the dev issuer) signs the role-A and role-B transcripts with own = partner = itself, d = 10 | check **accepts**. Real proof: **verify ACCEPT**. |

The builder's `swap` test on 180ca04b doesn't isolate the signature layer. There, swapped d = −93 < −56, so the −20 cm bound rejects it on its own. Attack 1 fills that gap, and it holds.

## 3. Soundness audit

### Holds

- **Bytes and ints.** Every byte array goes through `BytesBits` (Num2Bits(8)): pubs, halves, rec, ts, exp, commit, holderSecret. The nonce limbs are checked to 128 bits, attempt to 8, sr to 32, validAt to 64. `sb.circom` has no `<--`.
- **Threshold.** SignedI32 is correct two's complement. a = sA − sB + 2³⁴ ∈ (2³⁴ − 2³², 2³⁴ + 2³²), dLo + 2³⁴ and dHi + 2³⁴ are range-checked to 35 bits, and LessThan(36) is safe.
- **Bounds formula.** Checked exhaustively for d ∈ [−5000, 5000] at sr ∈ {1, 8k, 16k, 22.05k, 34.3k, 44.1k, 48k, 96k}: `dLo < d < dHi` matches `−20 < 17150·d/sr < 60` in exact rationals, with 0 mismatches.
- **Sign convention.** d = halfA − halfB, with halfA pulled from the 0x41 transcript. That matches flight = c/2·(halfA − halfB)/sr.
- **Transcripts.** Both are rebuilt from shared public nonce, attempt and sr. The role bytes are constants 0x41 and 0x42, and the pubs are crossed (A: own = pubA, partner = pubB; B: the reverse). Each role's device pub bytes are the same bytes the issuer signed in its credential.
- **ECDSA** (zkID gadget):
  - K_add range-checks every scalar (sInv, r, m) to < n, and r ≠ 0 and sInv ≠ 0 are enforced.
  - The pub is checked on the curve, so sInv·Q ≠ O.
  - HashModScalarField pins its limbs to canonical form.
  - The digest check is x(R) == r with no mod n. That is stricter than ECDSA and costs only a ~2⁻¹²⁸ completeness loss.
  - Soundness of the incomplete-addition ladder rests on the halo2-style argument and zkID's audit fixes. I read it but didn't re-prove it.
- **Malleability.** High-S is accepted. That's harmless here: signatures stay private and feed nothing public.
- **Fiat–Shamir** (Spartan2 d687dbb, `zk_spartan.rs` verify and `SplitR1CSInstance::validate`). The vk digest (the R1CS), the public values and comm_W_rest are all absorbed before the first challenge τ. The sumcheck masks and claims are absorbed before their challenges. Blinding is added by the library (`zk_r1cs.rs`, 4 blind vars). Nothing committed is missing from the transcript.
- **Hash choice.** The circuit uses no Poseidon, only SHA-256. I confirmed gcd(5, p−1) = 5 (α=5 Poseidon is broken in this field) and gcd(7, p−1) = 1.

### Issues

1. **pubA ≠ pubB not enforced (major).** One credentialed key can sign both roles and produce a NEAR proof alone (attack 6). The decision doc's combiner rule ("one role A and one role B, same pair of keys") doesn't forbid equal keys either. Today only the app's signing policy blocks it, and the whole point of the proof is to not trust the combiner. The fix is cheap, about 3 constraints (comparing x alone also rejects Q_B = −Q_A, which is fine):

       component samePub = IsEqual(); samePub.in[0] <== xA.out; samePub.in[1] <== xB.out; samePub.out === 0;

   Also have the app refuse to sign when partner_pub == own_pub. A person with two enrolled phones still gets through; only the issuer can limit that, e.g. one holder commit per attested identity.
2. **Public nonce links the two participants' proofs (major for the privacy goal).** In v2, A and B each make a proof with the same public nonce. Any two verifiers who compare can see those two presentations are the same meeting. The server that issued the nonce can map any proof back to the pair. Fix: keep the nonce private and verify a server signature over (nonce, expiry) inside the circuit (+1 ECDSA ≈ 14k, plus 1–2 SHA blocks). Publish only the nullifier and an epoch.
3. **Bounds and sr are verifier policy, not circuit policy (minor, but easy to get wrong).** Attack 5 shows the circuit accepts any dLo/dHi. The verifier must:
   - compute them itself from sr;
   - whitelist sr (e.g. {44100, 48000}). A signed but absurd sr only widens the bounds in samples, and an honest app never signs one, but a buggy app would;
   - pin the issuer key, the vk hash, nonce freshness and the nullifier registry.

   `sbzk verify` does the right thing (exact vector compare, length included). Spartan2's own `verify` returns the proof's public values *without* checking their count against the vk, so any other verifier must compare length and values, not just call `verify`.
4. **v1 nullifier unbound (major, already disclosed).** Confirmed. Use v2.
5. **Leakage through publics (minor).** sr (device class), attempt (a retry happened) and validAt (coarse time) are public. The issuer key is public too, so the issuer-tagging hole from the gap doc applies unless keys are published in a transparency list. os_ts, pubs, halves, rec hashes and signatures stay private, as claimed. The combiner still sees the partner's os_ts (already disclosed).
6. **Transferable proof (minor).** No verifier or context binding, so a proof can be forwarded. Harmless if the nullifier registry is global. Otherwise add a public context field.

## 4. Claim corrections

- "HashModScalarField rejects digests ≥ p … a retry fixes it." It doesn't reject. It reduces D − p (mod n), so the honest ECDSA check fails, which has the same effect. **A retry doesn't fix it**: ECDSA randomness doesn't change the digest. Only a different transcript works (new attempt, or new ts). For a credential, it has to be re-issued, since every proof with that credential fails. Probability ≈ 2⁻³² per message, so negligible, but the stated remedy is wrong.
- "Rejected: swapped roles" (on 180ca04b). True, but the −20 cm bound alone rejects that case. The signature-layer test is attack 1 above, and it passes.
- "0.86 GB max RSS for the prove process." That's one sample. I measured 0.57–0.72 GB RSS and a 0.50 GB footprint. Quote a range, or the footprint.
- "Poseidon α=7 … would save ~180k." Only with Poseidon constants and round counts generated for the P-256 field at α=7. circomlib's constants are BN254/α=5 and can't be reused. The estimate is still an estimate.
- ZK comes from the unaudited Spartan2 fork (`zk_spartan`). The README should say that next to "zero knowledge".

## 5. Reproduce

    ../enclave/.venv/bin/python review_attacks.py /tmp/atk
    ../tools/heavy.sh review-checks bash -c 'for a in swap_touch splice shift_both wide_bounds selfpair; do ./sbzk.sh check sb_pair_v1 /tmp/atk/atk_$a.input.json | grep RESULT; done; ./sbzk.sh check sb_pair_v2 /tmp/atk/atk_v2_me_flip.input.json | grep RESULT'
    ../tools/heavy.sh review-selfpair bash -c './sbzk.sh prove sb_pair_v1 /tmp/atk/atk_selfpair.input.json /tmp/atk/s.proof && ./sbzk.sh verify sb_pair_v1 /tmp/atk/s.proof /tmp/atk/atk_selfpair.public.json'

The self-pair attack generates a fresh throwaway P-256 key on each run and never prints it.
