# v1-bn254: option A vs option C (circom 2.1.8, BN254, Groth16)

Question: how heavy is a ZK proof of co-presence if (A) the audio analysis runs inside the circuit, or (C) the circuit only proves an attested, signed result?

Answer: C is 14,268 constraints and proves in seconds with snarkjs. A is about 7.4 billion constraints for one ranging round even when cut down to its core, 28× the largest Groth16 setup that exists (2^28). A is out in this form (see `../shrink/` for how far it can shrink).

Background on why C is enough: `../../../../2026-09-25-cheating-participant-and-trust.md`.

Note: `binding.circom` still has signature (2), the separate measurer. The 2026-09-26 protocol drops it (each phone signs its own half). It also verifies EdDSA over BabyJubJub, not the phone's P-256 enclave key.

## Files

| file | what |
| --- | --- |
| `circuits/commit16.circom` | range-check int16 samples, pack 15 per field element, Poseidon(16) chain |
| `circuits/corr.circom` | option A core: I/Q matched filter at K lags, window energy, commitments |
| `circuits/corr_bench.circom` | L=3600 (75 ms), K=4. Proved end to end |
| `circuits/corr_l12k.circom`, `corr_l48k.circom` | K=1 at 250 ms and 1 s, compiled for counts only |
| `circuits/binding.circom` | option C: seed commitment, 3 EdDSA, thresholds, nullifier |
| `prep_corr.py` | real recording → circuit input + exact expected ints |
| `prep_binding.mjs` | real result.json → valid signed input with throwaway keys |
| `check_public.py` | circuit outputs vs Python ints |
| `build/` | r1cs, wasm, witnesses, zkeys, vks, proofs of the runs below (gitignored). `build/count/corr_l12k.r1cs` is the count-only compile; `build/probe_full*.json` is `prep_corr.py 48000 9` output (1 s × 9 lags, never proved) |

The shared powers of tau is `../build/pot18.ptau` (one level up, gitignored).

Data: fieldtest session `c72ce4b6` (30 cm, big room), JB round 0, B's code at A, t = 13.78775 s.

## Run

From this folder (`v1-bn254/`), after `npm i` in the parent:

    PY=../../../../proximity-echo/.venv/bin/python3
    HEAVY=$PWD/../tools/heavy.sh
    $PY prep_corr.py 3600 4 build/corr_bench_input.json
    F=../../melody/fieldtest/data/sessions/c72ce4b6b37548c78dd3410ceca40aa4
    node prep_binding.mjs build/binding_input.json $F/session.json $F/result.json
    cd circuits
    circom binding.circom --r1cs --wasm -o ../build
    $HEAVY corr_bench circom corr_bench.circom --r1cs --wasm -o ../build
    cd ../build
    [ -f ../../build/pot18.ptau ] || curl -L -o ../../build/pot18.ptau https://pse-trusted-setup-ppot.s3.eu-central-1.amazonaws.com/pot28_0080/ppot_0080_18.ptau
    S=../../node_modules/.bin/snarkjs
    for c in corr_bench binding; do
      node ${c}_js/generate_witness.js ${c}_js/$c.wasm ${c}_input.json $c.wtns
      $HEAVY setup-$c $S groth16 setup $c.r1cs ../../build/pot18.ptau $c.zkey
      $S zkey export verificationkey $c.zkey ${c}_vk.json
      $HEAVY prove-$c $S groth16 prove $c.zkey $c.wtns ${c}_proof.json ${c}_public.json
      $S groth16 verify ${c}_vk.json ${c}_public.json ${c}_proof.json
    done
    python3 ../check_public.py corr_bench_public.json corr_bench_input.expect.json

After the 2026-09-26 move both circuits were recompiled from here: r1cs byte-identical to the stored ones (binding 14,268 constraints, 8.8 s; corr_bench 235,289, 210 s under heavy.sh with other load). Setup/prove not rerun.

## Results (2026-09-25)

Page with diagrams and chart: https://claude.ai/artifact/V36AHAkV77kBn7VEJnN6tB

| circuit | constraints | prove (snarkjs, M2, median of 3) | peak RAM | zkey |
| --- | ---: | ---: | ---: | ---: |
| binding (C) | 14,268 | 1.5 s | 0.6 GB | 9.3 MB |
| corr_bench (A, 75 ms × 4 lags) | 235,289 | 11.0 s | 1.5 GB | 168 MB |
| corr_l12k (A, 250 ms × 1 lag) | 710,801 | compiled only | | |
| A minimal, one round (model) | ~7.4e9 | | | |

corr_bench outputs match the Python integer math exactly. The corr_l48k compile was stopped after 16 min on 8 GB; its count (~2.84M) comes from the model.

Cost model for `corr.circom`, fitted to the compiled counts:

    constraints ≈ 16 × (samples range-checked) + 2·L·K + (L+K−1) + 2K + ~610 per 225 samples hashed

Not built: band mask, normalization divide, ppm bank, null codes, first-peak rule, the template derived from the seed, any FFT.
