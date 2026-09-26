# Opt3 Noir circuits on real POPT v2 fixtures

2026-09-26. Does `half` / `pair` prove and verify on real device transcripts, and does PopGuard accept them onchain?

Short answer: yes, with two caveats.
- The real SBcred3 can't be opened as-is. Its holder_commit is Poseidon7 over the P-256 base field; the circuit expects Poseidon2 over BN254.
- Real signatures have to be converted to low-S first.

Everything else is unchanged and real: transcripts, Secure Enclave signatures, issuer key, expiry, and holder secrets.

## Setup

- Toolchain: nargo 1.0.0-beta.22, bb 5.0.0-nightly.20260522, forge (solc 0.8.34). Binaries are in the session scratchpad (`scratchpad/onchain-zk/opt3-nonnative-p256/bin`).
- Circuits, vk and Solidity verifiers are the already-built ones. The circuits are byte-identical to the repo's, and no circuit was changed.
- New files:
  - `prototypes/opt3-noir-p256/noir/gen_real.py`: fixture → `half/Prover.toml`, `half/ProverB.toml`, `pair/Prover.toml`
  - `prototypes/opt3-noir-p256/run_real.sh`: execute + prove + verify for one fixture
  - `prototypes/opt3-noir-p256/forge/test/Real.t.sol`: verifier + PopGuard on the proof files (`RDIR=<run dir>`)
- Fixtures: `research/sound-bound/spikes/zk/fixtures/popt_v2/` (read only). They are all iPhone Secure Enclave. There is no Android keystore fixture in popt_v2.
- `now` = 1790400000 (2026-09-26). Credential expiry is 1792947425, so the credentials are valid. scope = 0x5afe, context = 0x0123456789abcdef.

```
python3 noir/gen_real.py FIXTURE.json NOIR_DIR --cred bn --lows     # NARGO=... for hashhelper
bash run_real.sh 180ca04b_48k            # [--tamper-a], TAG=_x for the out dir
cd forge && RDIR=<runs/NAME> forge test --match-contract RealTest -vv
```

## Quirks found

1. **Holder commit mismatch (real blocker for as-is credentials).** Fixture SBcred3 holder_commit = `p7.sponge16(TAG_HOLD, [hs])`, which is Poseidon over the P-256 Fp. The circuit checks `Poseidon2_bn254(hs)`. With `--cred real`, `nargo execute` fails at `lib.nr:73` (the holder commit loop).
   - Workaround (`--cred bn`): re-issue SBcred3-bn with the same device key, the same expiry and `Poseidon2_bn254(holder_secret_dev)`, signed by the same dev issuer key (`enclave/keys/issuer_dev.pem`, openssl, DER → r‖s).
   - Real fix, pick one: issue SBcred3-bn from the server, or port p7 into Noir (non-native field, costly).
2. **High-S rejected by the bb secp256r1 blackbox.** Secure Enclave emits high-S sometimes (180ca04b B's device sig), and openssl does too (both fixture cred sigs).
   - Without normalizing, half B fails at `lib.nr:78`.
   - `--lows` maps s → n−s. Anyone can do this, with no key, so the prover does it.
   - Probe circuit on the *real* cred plus the *real* issuer sig: low-S → `true`, high-S → `false`. So the real issuer signature itself verifies in-circuit once normalized.
3. Transcript offsets (role 5, nonce 7, pk 40/105, sr 169, half 173, sod 233) match `enclave/popt.py` v2. Device sigs are raw r‖s (64 B). Keys are SEC1 uncompressed. No other conversion was needed.

## Results

NEAR, 180ca04b_48k (30 cm label, flight 33.94 cm, SE/SE):

| step | result | time (M2, machine load avg 20–47, so inflated) |
|---|---|---|
| nargo execute half A / B / pair | OK | 1.6 s / – / 1.2 s |
| bb prove half A | OK | 10.7 s, 276 MB |
| bb prove half B | OK | 10.8 s, 264 MB |
| bb prove pair | OK | 12.5 s, 488 MB |
| bb verify A / B / pair | all OK | 0.03–0.45 s |

The earlier clean measurement was 2.4 s for half on the same machine. The 10 s here is load, not the data.

Also fully OK (execute, prove, verify, onchain): 180ca04b_mix (B at 44.1 kHz) and 2dc2eb59_48k (5 cm).

Onchain (forge test, execution gas via `gasleft`, same for all three NEAR runs):

| call | result | gas |
|---|---|---|
| HalfVerifier.verify (A) | PASS | 2,619,553 |
| PairVerifier.verify | PASS | 2,676,556 |
| PopGuard.checkHalves | PASS | 5,280,292 |
| PopGuard.checkPair | PASS | 2,722,816 |

These are execution-only numbers. The earlier anvil figures (5.59M / 2.90M) are tx gas including calldata.

## Negative cases

| case | result |
|---|---|
| 2940913c_48k NOT_NEAR (76.8 cm) | Both halves prove and verify, since a half has no distance rule. Pair execute fails at `main.nr:21` (`f < 60·sa·sb`). `checkHalves` reverts with `not near`. |
| b2a5f86d_48k NOT_NEAR (60.38 cm, just over the bound) | Pair execute fails at `main.nr:21`. The boundary holds. |
| 180ca04b_48k_sodfar (B self_os_delta 2401 > 2400) | Half B and pair fail at `lib.nr:85` (self-timestamp tolerance). |
| tamper: flip 1 byte of A's transcript (half field) | Half A and pair fail at `lib.nr:78` (device sig). No witness, so no proof. Half B is unaffected. |

## Not covered

- Android keystore signatures, because no popt_v2 fixture has them.
- Fully unmodified SBcred3, which is blocked by quirk 1.
