# Review of optionA-jbl250, 2026-09-26

Adversarial review of the builder's report and code in this folder. I didn't edit the builder's files. Everything I added is in `review/`:

- `review/attacks.py`: generates the attack inputs.
- `review/vega-rx/`: a copy of `vega/` with two opt-in additions (listed at the end).
- `review/logs/`: all outputs.

Heavy runs went through `../tools/heavy.sh`. The M2 was shared with other agents at the time (load average about 3.5 to 5).

## Bottom line

The math of the curve check is right: the Freivalds identity, the normalization, and the "first" rule gadget. The numbers reproduce.

The security claim does not hold as built. The report says "a proven NEAR implies an honest NEAR". I made the verifier accept NEAR on real fixtures whose honest verdict is NOT_NEAR, including a 200 cm session proven at 15.7 cm. That proof passes with both Groth16 and Vega.

- The main hole is that the window start is not bound. The builder lists this as a gap, but the headline claims rely on it being bound.
- A second hole is a one-line bug that isn't in the gap list: the half-rule lookahead can be cut off by the window end.
- The Vega circuit also isn't the same statement as the circom one: it has no int16 range check on the window samples. Adding that check multiplies the P3 cost by about 2.5.

## 1. Re-run (through heavy.sh)

| run | builder | re-run |
| --- | --- | --- |
| Vega exact K=512 (180ca04b B_at_A) | 144,918 constraints, prove 365–403 ms, verify 47 ms, 0.58 GB | same count, prove **385–466 ms**, verify 49–53 ms, 0.59 GB RSS, 847,916 B; heavy wall 2.0 s |
| Vega cand K=512 | prove 341–357 ms, 0.74 GB | prove **359–372 ms**, verify 48–50 ms, 0.62 GB |
| Groth16 exact K=512 (existing zkey) | prove 19.3 s, 1.84–1.92 GB, verify 0.60 s, 807 B | witness 1.2 s; prove **20.0 s** heavy wall, 1.90 GB; verify 0.56 s OK; proof.json 804 B |
| twin.py, all 48 arrivals | 46 identical, 2 off by ±1 | output byte-identical to `build/twin_all.jsonl` |
| check_fixtures.py | 12/12 | 12/12 |
| bar_floor.py | T0 = 9%: chance ≤ 3.2e-6 per window | same (3.20e-6 max, 1.74e-7 median) |
| tamper.py | 13/13 | 13/13 |

I didn't re-run the Groth16 setup (486 s) or the K=19,200 circom compile.

## 2. Attacks on the real fixtures

Each claimed flight is the twin flight with one arrival moved, using flight = c/2·(halfA − halfB)/sr, c = 34,300 cm/s (0.357 cm per sample).

| # | attack | target | result |
| --- | --- | --- | --- |
| A | **Self window starts after the true self arrival.** Exact mode, K=512 sub-window starting just after the previous candidate. The claimed self arrival is later, so the flight shrinks. | 9afb91c6 (label 200 cm, honest 210.8 NOT_NEAR): A_at_A claimed 546 samples late | **ACCEPTED**: Vega exact verify=ACCEPT, circom witness OK, **Groth16 prove + verify OK** (`review/atkA_9afb91c6_proof.json`). Claimed flight **15.7 cm, NEAR**. |
| A | same | d1ee4fb0 (label 100, honest 95.4): 107 samples late | **ACCEPTED** (Vega + circom witness). Claimed flight 57.2 cm, NEAR. |
| E | **Lookahead cut off.** Cand mode, K=512 sub-window that ends right before the half-rule veto of an earlier peak the receiver rejected. The claimed cross arrival is earlier, so the flight shrinks. | b2a5f86d (label 60, honest 62.9 NOT_NEAR): A_at_B, the rejected peak 12 samples early (score 9.49%) | **ACCEPTED** by the builder's `oa-vega` cand. Claimed flight 58.6, NEAR. With the one-constraint fix (below): **REJECTED** (InvalidSumcheckProof); honest cand and exact inputs still ACCEPT. |
| C | **Sample outside int16** (x = 100,000; curve recomputed so Freivalds and the rule still hold) | 180ca04b B_at_A K=512 | circom: **rejected** (Num2Bits). Vega: **ACCEPTED**. Vega with the range check added: rejected. |
| D | **Template swap.** Verify the real Groth16 proof against the role-A template, or against another session's role-B template. | 180ca04b | **Rejected** both times (Invalid proof). |
| D' | **Roles swapped when combining halves** (flight → −flight), all 12 signed fixtures | fixtures | Only 2dc2eb59 (touch, 7.9 → −7.9) passes, and it was NEAR anyway. No NOT_NEAR fixture passes once swapped: the −20 cm floor catches them. The floor and the role check are in the combiner, not in any proof. |
| B | **Narrowband in-band interference** to push chance peaks above the fixed floor T0 (100/300/1000 Hz wide, rms 0.01–0.05, simulated by digital addition) | 7711d899, 9afb91c6 cross windows | **Failed**: no candidate above T0 before the true arrival. Null maxima went down (median 3.6–4.5%). For a secret code with a flat spectrum, the chance-score variance is about 1/N whatever the interference spectrum, so the fixed floor holds against this. Side effect: at rms ≥ 0.03 the true arrival fell to 8.2–8.9%, below T0 but above the live bar (6.1–7.7%). The circuit then fails a measurement the live receiver would keep (a completeness problem, not soundness). |

Scan (`review/logs/scan_self.txt`): every self window has 3–16 later lags that pass as candidates. Attack A makes a NEAR out of 4 of the 8 NOT_NEAR sessions: 9afb91c6, d1ee4fb0, 2940913c, b2a5f86d.

## 3. Soundness findings

**S1 (critical): the window position is not bound, so "exact" is only "first inside a window the prover chose".**

- `lo` and the sub-window start `s0` are outside the statement.
- `hx` (circom) and the Vega precommitment cover the window's contents but not where the window sits in the recording.
- Nothing ties the self window and the cross window to the same recording.

So the self proof in exact mode is no stronger than cand mode (attack A). The one-sided argument ("self exact ⇒ proven self ≤ honest self") needs the self window to start at an attested point before the true arrival. The same holds for P3's "native OS-timestamp window": it is only sound if the OS output timestamp is signed or attested and the window start is computed from it inside the circuit.

Fix:
- Make the signed OS timestamp (or the schedule offset) a public input and compute `lo` from it in the circuit.
- Commit the recording as indexed leaves and open the window at that index: a Poseidon-Merkle tree on BN254, or on T-256 a hash with α=7 or a shared witness.
- Put both windows under one recording commitment.

Until then, the halves are not proven.

**S2 (major, not in the builder's gap list): the lookahead end is not enforced.**

- The circuit sets only `sel[K−1] = 0`, so arr ≤ K−2.
- The README says "arr must be in [1, K−2] with 240 lags of lookahead … beyond these the prover can't prove". Only `twin.dump` asserts that; the circuit doesn't.
- With a sub-window placed by the prover, a peak the receiver rejects by the half rule becomes a candidate (attack E).

Fix: add `sel[K−1−LOOK] === 0` (circom) or `enforce(sel[k−1−LOOK] = 0)` (Vega). Tested in `review/vega-rx` (`OA_LOOK_FIX=1`): it rejects the attack, and the honest exact and cand inputs still verify. Adds 1 constraint.

**S3 (major): Vega has no int16 range check on x.**

- circom range-checks x inside `Commit16`. `vega/src/main.rs` precommits x as raw field elements, so the Vega statement is about a vector over F_p, not int16 audio (attack C).
- Integer semantics (energy, the T0 comparison) rely on no wrap-around. With unconstrained x that is no longer guaranteed.
- `cost_table.no_hash()` also subtracts the 16-bit range check along with the hash. So every "commit-and-prove" figure leaves it out.

Measured with the check added (`review/vega-rx`, `review/logs/vega_rx_range.txt`):

| circuit | builder (no range) | with int16 range |
| --- | ---: | ---: |
| exact K=512 | 144,918 (2^18), 0.37–0.40 s | **358,659 (2^19), 0.47–0.57 s**, 0.78 GB |
| cand K=512 | 137,526, 0.34–0.36 s | **351,267, 0.45–0.50 s**, 0.76 GB |
| exact K=19,200 | 2,350,102 (2^22), 7.5–8.3 s | **2,881,539 (2^22), 8.1 s**, 1.93 GB |
| **P3 per phone (exact 512 + cand 512)** | 0.28 M, ~0.75 s | **0.71 M, ~1.0 s on M2** (sum of measured parts) |
| P2 per phone (exact 19,200 + cand 512) | 2.49 M | **3.23 M** (sum of measured parts) |

The check can be dropped only if x is later bound to a commitment the enclave made over the same int16 vector in Vega's own precommit layout. That doesn't exist yet.

**S4 (major, known): the half is not a proven quantity.**

- half = (lo_cross + arr_cross) − (lo_self + arr_self) is computed outside the proofs.
- None of the proofs carry role, session keys, nonce or attempt.
- `hx` isn't linked to the signed `rec_hash` (SHA-256 of float32).

Role crossing is prevented only because the verifier supplies the role's template, which attack D shows works. Two caveats:

- The Vega harness's `verify=ACCEPT` compares the proof's public values with the prover's own input JSON. A real verifier must derive cI/cQ from (seed, role, attempt) itself.
- Codes today have no attempt index (memo §4), so a proof from attempt 1 would verify for attempt 2.

**S5 (minor): Fiat-Shamir.**

- circom: r = Poseidon(hx, H(I,Q)). This covers the whole committed witness (x range-checked and packed injectively, 15×16 bits < 254; I and Q as field elements). It leaves out the public template. That is safe only because the verifier fixes cI/cQ; hashing them is standard Frozen-Heart hygiene and costs 0.22 M.
- Vega (vendor c0ee2590): the transcript absorbs the vk digest and all public values (cI, cQ, arr) before the precommitted commitment. The verifier re-derives the challenges and rejects a mismatch (`vega_sc_zkp.rs:283–304`, `721–722`; `r1cs/mod.rs:1585–1595`). The transcript is Keccak. OK.
- Schwartz-Zippel error ≤ (N+L)/p ≈ 2^−238 (BN254) / 2^−240 (T-256). OK.

**S6 (minor): hash and field.**

- Poseidon α=5 is valid on BN254 (r−1 ≡ 1 mod 5).
- On the P-256 base field (the T-256 scalar field), p−1 is divisible by **both 5 and 3**. So any Poseidon on T-256 needs α=7 (or another hash). The README mentions only α=5.
- Vega uses no in-circuit hash today.

**S7 (minor): other gadget checks, all OK.**

- Boolean and monotone selector, and sum = arr+1: OK.
- Reason bits:
  - Exactly one reason iff k < arr. Duplicate half-rule slots on one lag are forced to fail (sum 2 ≠ 1).
  - (a) to (d) are an exact negation of "candidate".
  - Lag 0 gets a free reason (c), the same as the receiver, which never picks lag 0.
- Magnitudes stay far from the field. Worst case at full-scale int16: env2·B < 2^95 (WA = 96), C < 2^85 (W = 88).

**S8 (minor): leakage and setup.**

- `hx` is an unsalted, deterministic hash of 31k audio samples and it's public. A silent or clipped window is guessable, and the same window always gives the same `hx`. Add a blinding salt, or use Vega's hiding commitment instead.
- The public template reveals both session codes to whoever sees the proof.
- The public arr plus lo reveals the distance to the verifier. That's inherent in the per-phone-half design.
- The Groth16 zkey is a single-party dev setup (whoever holds the toxic waste can forge). The builder states this.

The following items don't apply to this track: no OS timestamp or keys go into the circuit, there is no nullifier, and there is no ECDSA, so low-S malleability doesn't come up.

## 4. Claim corrections

- "Exact mode proves arr equals the fixed-floor receiver's arrival" and "a proven NEAR implies an honest NEAR" are false as built. Both need S1 and S2 fixed. The K=512 "exact" Groth16 proof proves a first candidate inside a window the prover chose.
- "arr must be in [1, K−2] with 240 lags of lookahead … beyond these the prover can't prove": the lookahead part isn't enforced (S2).
- The Vega circuit is "the same statement" only without the int16 range check. P3 is **0.71 M constraints and ~1.0 s on the M2**, not 0.28 M and ~0.75 s. P2 is 3.23 M, not 2.49 M. The phone estimate for P3 should scale by the same factor (label: estimate).
- "T0 … only matters for an honest-but-unlucky run, not for a cheater": this held against the interference attack I tried (B). But in noise the fixed floor also drops real arrivals that the live bar keeps (8.2–8.9% vs a bar of 6.1–7.7%). That means more failed measurements, and so more retries, which count against the false-accept budget.
- Everything else I re-ran matches, within machine noise.

## Tiny additions (all under `review/`, none to builder files)

- `review/vega-rx/src/main.rs`: a copy of `vega/src/main.rs` with the int16 range on x (on by default, `OA_NO_XRANGE` turns it off) and `OA_LOOK_FIX` (`sel[K−1−LOOK] = 0`). Built into the shared `build/vega-target` as `oa-vega-rx`.
- Recommended one-liners for the builder, not applied:
  - `gen_circuit.py`: add `sel[K - 1 - LOOK] === 0;` after `sel[K - 1] === 0;`.
  - `vega/src/main.rs`: the same constraint, plus `range(x + 32768, 16)` for every x.

## Reproduce

    PY=../../../proximity-echo/.venv/bin/python3   # from this folder: $PY = the venv above
    $PY review/attacks.py swap
    $PY review/attacks.py scan-self
    $PY review/attacks.py self 9afb91c6 A_at_A 11146 review/atkA_9afb91c6_selfshift.json
    $PY review/attacks.py trunc b2a5f86d A_at_B review/atkE_b2a5f86d_trunc.json
    $PY review/attacks.py xrange build/in_exact_K512.json review/atkC_xrange.json
    $PY review/attacks.py noise 7711d899 5000 300 0.05
    ../tools/heavy.sh x build/vega-target/release/oa-vega review/atkA_9afb91c6_selfshift.json review/atkA_9afb91c6_selfshift.meta.json exact 1
    OA_LOOK_FIX=1 ../tools/heavy.sh x build/vega-target/release/oa-vega-rx review/atkE_b2a5f86d_trunc.json review/atkE_b2a5f86d_trunc.meta.json cand 1
