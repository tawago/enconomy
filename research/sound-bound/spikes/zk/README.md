# zk spike

Can a proof of co-presence be hardware-bound (phone enclave key), private (third parties can't see who met whom) and fast on a phone? Memos: `../../../2026-09-26-zk-gap-research.md` (conclusions, holes), `../../../2026-09-26-sound-bound-decision.md` (the implemented protocol: each phone computes and signs its own half), `../../../2026-09-25-cheating-participant-and-trust.md`.

## Layout

| folder | what |
| --- | --- |
| `v1-bn254/` | first spike, circom + Groth16 on BN254. Option A (analysis in circuit: `corr*.circom`, `commit16.circom`) vs option C (`binding.circom`: prove a signed result). Own README with run steps |
| `shrink/` | Python re-scoring of the 18 field sessions under circuit-shrinking receiver changes, plus a constraint cost model. Own README |
| `tools/heavy.sh` | `tools/heavy.sh <label> <cmd...>`: machine-wide lock for heavy jobs (big builds, circom > ~200k constraints, setup, prove). Use it |
| `enclave/`, `fixtures/` | real Secure Enclave P-256 keys on the M2 (Swift CLI `sesign`), 12 signed JBL250 fixtures (transcript + credential per role) |
| `openac/` | our statement in circom over secq256r1, proved with zkID's Spartan2/Hyrax on T-256. README + REVIEW.md |
| `longfellow/` | our statement in Google longfellow-zk (Ligero + sumcheck, P-256 field). README + REVIEW.md |
| `optionA-v2/` | option A with signature, credential and Merkle recording commitment. Since the POPT v2 pass: `oa2t_s48` / `oa2t_s44` (per phone, per rate) + `oa2t_pair` (two rates). README + REVIEW.md |
| `verifier/` | `popzk.py`: the option A session verifier (per-phone proofs + pair proof); `test_session_a.py`; server cross-checks (`check_fixtures_server.py`, `check_v2_verdicts_server.py`, `edge_cases.py`); `pinned.json` (circuit ids = sha256 of the vks) |
| `fixtures/popt_v1/`, `fixtures/popt_v2/` | POPT v1 (269 B, contract §7.1) and POPT v2 (311 B, `docs/pop-transcript-v2.md`) fixtures from the 12 JBL250 sessions, 48k/48k and 48k/44.1k, real Secure Enclave signatures. Built by `enclave/build_popt_fixtures.py` and `optionA-v2/build_fixtures_popt2.py`; timestamps emulated (`enclave/emulate.py`) |
| `optionA-jbl250/` | option A for the JBL250 receiver: integer twin, Freivalds correlation check, circom/Groth16 and Spartan2 (Vega) builds. README + REVIEW.md |
| `vendor/` | third-party clones, gitignored; pin commits in the folder's README |
| `build/pot18.ptau` | shared powers of tau (2^18, PSE ppot), gitignored |
| `node_modules/`, `package.json` | shared: circomlib, circomlibjs, snarkjs. `npm i` here |

Tools: circom 2.1.8 at `~/.cargo/bin/circom`; Python venv `../../../proximity-echo/.venv/bin/python3`.

## Headline results so far

- **Option C (v1, BN254)**: 14,268 constraints, 1.5 s prove with snarkjs on M2, 0.6 GB. But EdDSA/BabyJubJub keys, not the phone's P-256 key; non-native P-256 in BN254 is ~2M constraints, a dead end.
- **Option A naive (v1)**: ~7.4e9 constraints per round (model; corr_bench 235,289 proved in 11.0 s and matched Python exactly). Out.
- **Option A shrunk (`shrink/`)**: ~1.1M R1CS per round, ~0.53M per phone (estimate), decisions still correct on all labeled sessions. Still adds no security: the prover supplies the recording.
- **Hardware + privacy + phone speed are possible together** (research, not measured here): longfellow-zk proves one hidden P-256 ECDSA in 31 ms on iPhone 15+ (toy credential 289 ms); OpenAC (circom `--prime secq256r1` + Spartan2/Hyrax) 99 ms on iPhone 17. The blocker was BN254, not ZK.
- **Protocol**: each phone computes its own half (A: t_BA − t_AA, B: t_BB − t_AB) and its enclave signs it, so the separate measurer signature goes away and no audio processing needs to be in the proof.
- **Holes to fix** (memo §3, §5): nullifier needs a holder secret; keep timestamps/signCount private; Poseidon α=5 is broken in P-256's field; round-index bug in `fieldprobes._sub`; server sends `seed_hex` to both phones.

## Spike v2 results (2026-09-26, M2 8 GB, all reproduced by a reviewer)

Statement for C: two roles, issuer P-256 credential over each device key, device P-256 signature over the rebuilt 215-byte transcript, crossed roles and keys, −20 < flight < 60 cm, nullifier. Real Secure Enclave signatures from 12 JBL250 sessions: the 4 NEAR sessions are accepted, all 8 NOT_NEAR are refused, and tampered inputs (half, role swap, nonce, signature bit) are rejected.

| prover | size | prove | verify | proof | RAM |
| --- | --- | --- | --- | --- | --- |
| OpenAC circom/secq256r1 + Spartan2 (`openac/`) | 481k R1CS (v2 with holder-bound nullifier: 512k) | 0.87 s + 0.16 s witness | 0.05 s warm, 0.39 s cold | 60.5 KB | 0.86 GB |
| longfellow-zk (`longfellow/`) | 3.49M quad terms, 1.13M wires | 0.71 s | 0.43 s | 387 KB | 0.28 GB |
| option A, JBL250, Freivalds curve check, full 19,200-lag window, Spartan2 | 137k R1CS | 0.38 s | 0.04 s | 848 KB | 0.52 GB |
| option A, exact "first" rule, full window, one arrival, Spartan2 | 2.35M R1CS | 8 s | 0.25 s | 912 KB | 2.2 GB |

Phone estimates (not measured): C about 0.5–2 s. Longfellow spends ~94% of its circuit on SHA-256 in the P-256 field, so moving SHA to GF(2^128) like mdoc does should cut it a lot.

Holes found by the reviewers (fix before any product use):
- **Both C builds:** nothing forces device A ≠ device B, so one phone can meet itself (a real proof verified). ~3 constraints to fix.
- **Nullifier:** unbound unless the credential commits to the holder secret (`openac` v2 does this, +31k).
- **Verifier policy:** must pin the issuer key and the circuit id (longfellow accepted a self-issued credential).
- **Public nonce:** lets our server map a proof to its device pair. ZK hides who met whom only from third parties.
- **Option A (critical):** the search-window start isn't bound, so the reviewer turned a 200 cm session into a verified 15.7 cm NEAR. There's also a lookahead off-by-one, and the samples in the Spartan2 build have no range check (with it: ~0.71M, ~1 s). The recording commitment isn't linked to the signed rec_hash (SHA-256 over the float WAV is infeasible; the app should sign an int16 Poseidon/Merkle root instead). The fixed floor is 9%; the live bar on the walk is 7–8%, not the ~4% the decision memo says.

## Must match the app/server (`docs/pop-contract.md`): status 2026-09-26

The user moved the focus to option A, and option C is deferred.

| item | option A (`optionA-v2/oa2t_*`) | option C (`openac/`) |
| --- | --- | --- |
| transcript format | **done**: consumes POPT v2 (311 B), proposed in `docs/pop-transcript-v2.md`. That's POPT v1 plus `a_self`, `p_partner`, `delta`, `code_commit`, with `rec_root` replacing `rec_sha256` | **not done**: the tested circuits still use SBv1 (215 B). `circuits/popt.circom` (POPT v1, 269 B, crossed rates, self_os_delta tolerance, A ≠ B) compiles (`popt_pair` 483,000 / `popt_pair_nf` 573,191 constraints) and is linked into `sbzk`. It hasn't been set up, proved or tested |
| per-phone sample rates | **done**: each phone's circuit is compiled for its rate and pins the signed sr. The pair checks `−20 < c/2·(hA/srA − hB/srB) < 60` by integer cross-multiplication. Tested end to end at 48/44.1 kHz | in `popt.circom` only (untested) |
| session verifier | **done**: `verifier/popzk.py`, 23/23 real-proof tests | not started |
| pair tag | **done**: key-derived pairTag removed. The verifier computes `sha256("pop-pair-v1" ‖ min ‖ max)` from the adapter nullifiers and rejects equal ones (`same_human`) | openac never had one; its v2 nullifier is the optional "none"-adapter variant |

Found on the way: at an exact tie (flight exactly −20 or 60 cm, only possible at rates such as 68,600 Hz), `server/pop/verdict.py` decides on a float that can round across the bound. Example: sr 68,600/68,600 with halves 45,240/45,000 is exactly 60 cm, and the server says NEAR. The circuit uses the exact rule. See `verifier/edge_cases.txt`. That's harmless at 44.1 and 48 kHz, where no exact ties exist.

### Option A after the POPT v2 pass (M2 8 GB, shared)

| circuit | constraints | prove (fresh / warm) | verify warm / fresh | peak | proof |
| --- | ---: | --- | --- | --- | ---: |
| `oa2_d2_sig` before (SBv2, 48 k) | 1,247,378 | 4.70 / 4.9–5.2 s | 0.28–0.30 / 1.15 s | 1.95 GB | 1,648,319 B |
| `oa2t_s48` after (POPT v2) | 1,228,446 | 4.49 / 4.7–4.8 s | 0.27–0.28 / 1.24 s | 1.93 GB | 1,648,255 B |
| `oa2t_s44` after (POPT v2, 44.1 k) | 1,152,227 | 4.70 / 4.5–4.6 s | 0.25–0.28 / 1.21 s | 1.89 GB | 1,523,455 B |
| `oa2_pair` before → `oa2t_pair` after | 1,518 → 1,612 | 51 → 58 ms | 13–17 → 15–20 ms | 8 MB | 39,649 B |

**Tests** (details in `optionA-v2/README.md`):

| suite | result |
| --- | --- |
| per-phone honest | 48/48 |
| per-phone tampers | 32/32 |
| pair | 28/28 (8 NEAR accepted, 16 NOT_NEAR rejected, incl. mixed rate) |
| edge semantics | 214/214 |
| session verifier on real proofs | 23/23 |
| server cross-checks | 27/27 v1, 26/26 v2 |

**Ready (spike grade):**
- POPT v2 byte layout proven with real enclave signatures;
- per-phone rates;
- no key-derived public tag;
- a session verifier that pins circuit ids and the issuer.

**Not ready:**
- the app/server still speak v1 only;
- `|self_os_delta| ≤ 2 ms` in the circuit vs 50 ms on the server, and OS timestamps unmeasured (all emulated);
- one circuit + 0.45 GB key per rate;
- about 2 GB / 7–10 s estimated on a Pixel;
- Poseidon7 and zk_spartan unaudited;
- templates derived from the field seed, not from a server reveal;
- nonce freshness and nullifier uniqueness are the caller's job;
- option C still on SBv1.

## Run

    npm i
    cd v1-bn254   # see v1-bn254/README.md
    cd shrink     # see shrink/README.md
