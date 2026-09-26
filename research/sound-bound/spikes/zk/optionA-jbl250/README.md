# optionA-jbl250: the JBL250 receiver inside the proof

Question: how small can a sound proof of "this committed recording yields half = h under the receiver rule" get, for the protocol in `../../../../2026-09-26-sound-bound-decision.md` (JBL250, one play per phone, 250 ms secret bed, −150/+250 ms windows, "first" rule, each phone proves its own half)?

Answer:

- The correlation curve costs almost nothing once it is checked with Freivalds / Schwartz-Zippel instead of computed: the whole 19,200-lag curve for one arrival is **136,798 constraints** (instead of ~460 M for the naive products). Measured, real size, real recording, and it rejects a single altered score.
- What costs is everything around it. In circom/Groth16 the Fiat-Shamir hash of the recording window and of the claimed curve costs 2.1 M of the 2.3 M core. The "first" rule over a 19,200-lag window adds ~2.2 M, mostly 88-bit range checks. A full per-phone proof over web-sized windows comes to ~4.9–9.0 M R1CS. That doesn't fit snarkjs on 8 GB.
- With a commit-and-prove system (Spartan2/Vega: the window and curve are precommitted, challenges come from the transcript, no in-circuit hash) the exact rule over the full web window is **2.35 M constraints, proved in 7.5–8.4 s on the M2 (1.8–2.2 GB)**. With native OS-timestamp windows it drops to **~0.28 M per phone, ~0.7 s on the M2**. Measured.
- The live 64-code bar can't go in (~117–216 M). A fixed floor T0 = 9% plus a one-sided argument replaces it and loses nothing on the walk (see below).
- The analysis runner is proven honest, but the recording still comes from the phone. Same caveat as `../../../../2026-09-26-zk-gap-research.md` §4: option A adds security only if the capture is attested separately from the analysis.

## Statement proven (one arrival)

Public: template `cI, cQ` (12,000 values each, 8-bit, the masked secret bed and its Hilbert pair), arrival lag `arr`, and the output `hx`. Private: int16 window `x` (K + L − 1 + 62 samples), claimed curve `I_k, Q_k` (k < K), selector bits, reasons, half-rule witnesses.

1. `hx = Poseidon-chain(x)`, each sample range-checked to int16. This is the recording commitment; binding `hx` to the signed `rec_hash` is modeled, not built (see gaps).
2. Curve: `r = Poseidon(hx, H(I, Q))`, `rho = Poseidon(r)`, and
   `r^(L−1) · Σ_k r^k (I_k + rho·Q_k) = Σ_n (cI_n + rho·cQ_n) · r^(L−1−n) · (S[n+K] − S[n])`, with `S[m] = Σ_{i<m} r^i x_i`.
   A wrong curve passes with probability ≤ (N+L)/p ≈ 2^−238. Cost is O(L + K), and only the K scores are claimed, with no convolution tails.
3. Normalization: `y = h ⊛ x` with a fixed 63-tap integer band-pass (2–18 kHz, 45 nonzero taps, linear in-circuit), `E_k = Σ_{m<L} y_{k+m}²`, `cn2 = Σ cI²`. The condition `score ≥ T0` is written as `env2_k · B ≥ E_k · cn2`, where `env2 = I² + Q²` and `B = round(g²/T0²)` (g = FIR gain) is a circuit constant.
4. Rule ("first", fixed floor T0 = 9%, lookahead 240 = 5 ms):
   - `arr` is a candidate: score ≥ T0, `env2[arr] ≥ env2[arr−1]`, `env2[arr] > env2[arr+1]`, and `4·env2[arr] ≥ env2[m]` for m in [arr, arr+240].
   - **exact mode** only: every lag k < arr carries a proven reason: (a) score < T0, (b) env2_k ≤ env2_{k+1}, (c) env2_k < env2_{k−1}, or (d) a half-rule reject with witness m ∈ [k, k+240], env2_m > 4·env2_k (up to NHR = 2).
   - Together these make `arr` exactly the reference rule's arrival (with T0, 0 ppm).

Per phone: two such proofs over two windows of its own file (self and partner). half = (lo_cross + arr_cross) − (lo_self + arr_self). The window starts `lo` come from the phone's own timeline (gap).

**One-sided variant (cand mode for the cross arrival).** A cheater faking NEAR wants a late self arrival or an early cross arrival (the flight formula in the decision memo). "arr is a candidate" alone forces arr ≥ the true first candidate, so a cross arrival can only be claimed late. "No candidate before arr" forces arr ≤ the true one, so a self arrival can only be claimed early. Either way the proven flight is ≥ the honest flight: a NEAR proof implies an honest NEAR. The same argument lets the circuit use one fixed T0 on both sides whatever live bar the phone applies itself (a higher bar only removes candidates). The live bar stays a phone-side policy that can only make the phone more conservative.

## Receiver twin vs fieldanalysis (all 12 JBL250 sessions, round 0)

`twin.py` runs the circuit's exact integer math: int16 x, 8-bit template, 8-bit 63-tap FIR, T0 = 9%, no ppm bank, no live bar.

| check | result |
| --- | --- |
| 48 arrivals vs `result.json` | 46 identical, 2 differ by 1 sample (both cross arrivals where fieldanalysis picked a ±50 ppm bank template) |
| halves vs signed fixtures (`../fixtures`) | 12/12 within 1 sample, 12/12 same verdict; flight differs by ≤ 0.36 cm (`check_fixtures.py`) |
| live bar T on the walk | 7.06–8.27% (not the ~4% in the memo); arrival scores ≥ 16.9% |
| T0 = 9% | above every live T and below every arrival score. Gumbel from the stored nulls: chance max > T0 ≤ 3.2e−6 per window (live target 3.3e−5) (`bar_floor.py`) |
| half-rule rejects before the arrival | 4 of 48 arrivals, 1–2 each: NHR = 2 covers all |
| lags before arrival | 10,600–13,636 (window start + 150 ms + 70–130 ms latency), so the self proof needs the whole window unless OS timestamps anchor it |
| quantization | 8-bit template/FIR same result as 10/12-bit; 6-bit still ≤ 1 sample; 4-bit breaks (flights off by metres) |

The circuit input for session 180ca04b, file A: self arrival lag 11,676 at sample 1,094,076, partner arrival lag 11,118 at sample 1,139,118. Half = 45,042 = the fixture's signed `half_samples`; both are proven at full window size (Vega).

## Results

Machine: Apple M2, 8 GB, shared. Every heavy run went through `../tools/heavy.sh`; times are its `[heavy]` wall times or the prover's own timers. Logs are in `logs/`.

### circom 2.1.8 → Groth16 (snarkjs), BN254, in-circuit Poseidon Fiat-Shamir

| circuit | constraints | status | numbers |
| --- | ---: | --- | --- |
| core K=19,200 (Freivalds + FS only), real size | 2,281,108 | measured compile (390 s, 2.66 GB) | too big for snarkjs on 8 GB |
| exact K=19,200 (full web window, exact rule) | ~4,475,000 | **extrapolated** (216.9/lag, from K=512/1024/2048). The compile was aborted at 12 min with a 7.6 GB footprint and swapping | |
| exact K=512, real L, real recording (sub-window around 180ca04b B_at_A) | 422,071 | **proved** | setup 486.5 s with pot19; prove 19.3 s ×3; 1.9 GB; verify 0.60 s; proof 807 B JSON; zkey 366 MB |
| cand K=512 | 414,689 | measured compile | |

Tamper tests on exact K=512 (`tamper.py`, witness generation must fail): all 13 pass. The cases:

- one score +1 before, at and after the arrival, and at the last lag
- one sample +1 with the scores kept, and a sample out of int16
- arrival claimed 1 or 2 lags late (with each reason a, b, c) or 3 lags early
- a planted fake peak

The five curve tampers fail at the Freivalds line. Groth16 verify also rejects a proof whose public `arr`, `hx` or `cI[0]` was changed.

Per-lag cost (fit): 104.4 core (81.2 of it is hashing I, Q; 18.7 per sample is hashing x), 203.4 cand, 216.9 exact. The 88-bit range check per lag is ~89 of that.

### Spartan2 / Vega (commit-and-prove), T-256 Hyrax, zero-knowledge, same statement, no in-circuit hash

Same inputs as above. `vendor/Spartan2` @ c0ee2590, `vega_sc_zkp::VegaZkSNARK`. x, I and Q are precommitted; r and rho are transcript challenges.

| circuit | constraints (padded) | setup | prove (M2, all cores) | prove 1 thread | verify | peak RAM | proof |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| core K=19,200, real size | 136,798 (2^18) | 0.23 s | 0.38–0.39 s | | 40–43 ms | 0.52 GB | 848 KB* |
| **exact K=19,200, cross (B_at_A)** | 2,350,102 (2^22) | 9.7 s | **7.5–8.3 s** | 11.0 s | 0.25 s | 1.79 GB | 912 KB* |
| **exact K=19,200, self (A_at_A)** | 2,350,102 | 8.5 s | 8.4 s | | 0.21 s | 2.24 GB | 912 KB* |
| exact K=512 | 144,918 (2^18) | 0.5 s | 0.37–0.40 s | 1.2 s | 47 ms | 0.58 GB | 848 KB* |
| cand K=512 | 137,526 (2^18) | 0.46 s | 0.34–0.36 s | | 47 ms | 0.74 GB | 848 KB* |

\* The serialized proof carries the 24,001 public values; 24,001 × 32 B ≈ 768 KB of it is the template. The proof proper is ~80–145 KB (by subtraction, not measured separately).

Tamper: one score +1 → `verify=REJECT (InvalidSumcheckProof)`, at K=512 and at K=19,200.

### Per phone (self + cross in its own file)

From `cost_table.py`; R1CS counts.

| variant | circom/Groth16 (in-circuit FS) | commit-and-prove (Vega) | Vega prove on M2 |
| --- | ---: | ---: | --- |
| P1 web windows, both arrivals exact | ~8.96 M (model) | 4.70 M (2 × 2.35 M measured) | ~16 s (2 × measured) |
| P2 web windows, self exact + cross one-sided | ~4.90 M (model) | 2.49 M (measured parts) | ~8.3 s (sum of measured) |
| P3 native OS-timestamp self window (±5 ms) + cross one-sided | 0.85 M (measured parts) | 0.28 M (measured parts) | ~0.75 s (sum of measured) |

Modeled add-ons, per window unless noted:

| add-on | constraints |
| --- | ---: |
| recording binding, Poseidon-Merkle path | ~6 k |
| recording binding, SHA-256 over the int16 window | 29.7 M |
| recording binding, SHA-256 over a 512-lag sub-window | 11.9 M |
| recording binding, SHA-256 over the whole 27 s float32 WAV (today's fixture `rec_hash`) | 2.46 G |
| live 64-code bar, hashed / commit-and-prove | 216 M / 117 M |
| template hashed instead of public | 0.22 M |
| 20 ms glitch check over the 1.4 s span, hashed / commit-and-prove | 1.6 M / 0.34 M |
| transcript + ECDSA + credential | separate track (`../openac`, `../longfellow`) |

Unit costs are measured here: Poseidon(16) 609, Poseidon(2) 240, SHA-256 30,328 per block.

## Can a phone prove it?

Labeled estimates:

- **P3 on Vega/Spartan2 T-256** (0.28 M constraints, ~0.75 s and <1 GB on the M2): yes. The basis is OpenAC's published ECDSA proof, 99 ms on iPhone 17 and 340 ms on Pixel 10 Pro, on the same stack. That suggests a recent phone is within 1–3× of the M2, so P3 would take ~1–2 s on a phone. The ECDSA/credential proof comes on top, in the same field; a shared-witness link to the recording is available in that stack.
- **P2 on Vega** (2.5 M constraints, ~8 s and ~2 GB on the M2): borderline, ~10–25 s and 2 GB, likely too much memory for mid-range Android.
- **circom/Groth16**: P3 at 0.85 M needs pot20; snarkjs would take ~40 s on the M2 (not measured), and a ~730 MB zkey on the phone. P1/P2 at 5–9 M: no.
- **longfellow-zk** (sumcheck + Ligero): not tried for this circuit. It handles SHA-256 cheaply, which would make a SHA-based `rec_hash` less painful. The curve check itself needs a challenge after committing the curve, which is its native mode. Worth a port only if P3 stays the target.

So the precondition for a phone is native OS output timestamps (self window ±1–5 ms) plus a commit-and-prove system. That's the same precondition the shrink study found, now with the real JBL250 numbers.

## Run

From this folder (PY = `../../../../proximity-echo/.venv/bin/python3`, HEAVY = `../tools/heavy.sh`):

    $PY twin.py > build/twin_all.jsonl            # twin vs result.json, all JBL250 sessions
    python3 check_fixtures.py                     # twin halves vs signed fixtures
    $PY bar_floor.py 0.085 0.09 0.10              # fixed floor vs live bar
    python3 cost_table.py                         # per-phone table
    # circom / Groth16, K=512 exact
    $PY gen_circuit.py 512 --mode exact           # also: --mode cand|core, any K
    $PY twin.py --dump 180ca04b B_at_A 512 build/in_exact_K512.json --mode exact
    (cd circuits && $HEAVY compile ~/.cargo/bin/circom arrival_exact_K512.circom --r1cs --wasm --O2 -o ../build)
    cd build
    node arrival_exact_K512_js/generate_witness.js arrival_exact_K512_js/arrival_exact_K512.wasm in_exact_K512.json exact512.wtns
    S=../../node_modules/.bin/snarkjs
    $HEAVY setup node --max-old-space-size=7000 $S groth16 setup arrival_exact_K512.r1cs ../../build/pot19.ptau exact512.zkey
    $S zkey export verificationkey exact512.zkey exact512_vk.json
    $HEAVY prove $S groth16 prove exact512.zkey exact512.wtns exact512_proof.json exact512_public.json
    $S groth16 verify exact512_vk.json exact512_public.json exact512_proof.json
    cd .. && $PY tamper.py build/in_exact_K512.json build/arrival_exact_K512_js
    # Spartan2/Vega (vendor/Spartan2 cloned at c0ee2590)
    (cd vega && CARGO_TARGET_DIR=../build/vega-target $HEAVY build cargo build --release)
    $PY twin.py --dump 180ca04b B_at_A 19200 build/in_exact_K19200_B_at_A.json --mode exact --lead 11118
    $HEAVY vega build/vega-target/release/oa-vega build/in_exact_K19200_B_at_A.json build/in_exact_K19200_B_at_A.meta.json exact 2 [--tamper]

`pot19.ptau` is PSE ppot_0080_19 in `../build/` (downloaded for this run).

## Files

| file | what |
| --- | --- |
| `twin.py` | integer receiver twin, all-session comparison, circuit input dump (window or sub-window) |
| `gen_circuit.py`, `circuits/lib.circom` | emits `circuits/arrival_<mode>_K<K>.circom` (FIR constants inlined) |
| `tamper.py` | altered-input tests against the circom witness generator |
| `vega/` | same statement as a bellpepper circuit for Spartan2/Vega with precommitted x, I, Q |
| `bar_floor.py`, `check_fixtures.py`, `cost_table.py` | floor analysis, fixture cross-check, per-phone model |
| `circuits/count/` | SHA-256 / Poseidon unit-cost probes |
| `logs/` | outputs of the runs above |

## Gaps

- **Recording binding is not built.** `hx` is a Poseidon chain over the int16 window. The phone signs `rec_hash` = SHA-256 of the float32 WAV, which no circuit can open (2.46 G constraints). The fix is to sign a chunked Poseidon-Merkle root over int16 PCM (225-sample leaves, window aligned to leaves, ~6 k per window), or in Vega a shared witness commitment with the capture step. The window position (`lo`, from the phone's timeline and play timestamps) is also not proven.
- **Poseidon in the P-256 field.** The Vega run needs no hash. Any in-circuit hash on T-256 must not be Poseidon α=5 (gap memo §3).
- **Mac recordings are float32, not int16-exact.** The twin rounds them; arrivals are unchanged. Android files are int16-exact.
- **Receiver deviations.** Fixed floor T0 = 9% instead of the live 64-code Gumbel bar. No ppm bank: 2 of 48 arrivals move by 1 sample; JBL250 doesn't apply the bank to the flight anyway. FIR-normalized energy instead of the brick-wall mask; the template is truncated to L. Scores come out 0–2 points higher than fieldanalysis. Decisions are unchanged on all 12 sessions, but that is one room and one afternoon.
- **T0 = 9% is fitted to one room.** In noisy or tonal rooms the live bar may rise above it, and the circuit would then accept a chance match that the phone's live bar rejects. That only matters for the cross arrival of an honest-but-unlucky run, not for a cheater, who gains nothing beyond what the honest earliest candidate gives.
- **Completeness limits of exact mode.** At most 2 half-rule rejects before the arrival; lag 0 has no local-max test; arr must be in [1, K−2] with 240 lags of lookahead in the (sub-)window. Beyond these the prover can't prove, which counts as a failed measurement, never a false accept.
- **Not in the circuit:** the 20 ms flat-block check (modeled 0.34–1.6 M), the −20 cm floor, and the self-arrival vs OS-timestamp check (it needs attested timestamps as input). The split check isn't in either.
- **Template is a public input** (24,000 values). The verifier must know the session's codes, and the template isn't derived from the seed in-circuit. Hashing it costs 0.22 M; deriving it (PCG64 + 4,000-tone multisine) is out of reach.
- **Not measured:** exact K=19,200 compile count (extrapolated), phone runs of anything, rapidsnark, and longfellow for this circuit. Groth16 setup is a single-party dev setup on pot19.
- **Security framing.** The proof makes the analysis verifiable, but the phone still chooses its recording. This is useful only with attested capture (enclave-signed `rec_hash` before the partner code is revealed), which is the case the decision memo's commit-then-reveal already sets up.
