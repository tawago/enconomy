# Onchain private PoP: options 2 / 3 / 4 compared

2026-09-26. Sources: `opt2-server-credential.md`, `opt3-nonnative-p256.md`, `opt4-zkvm-wrap.md` and their review sections. Option 1 (keys and transcripts in the clear) is out.
Labels: M = MEASURED on this M2 or anvil/forge, C = CITED (URL in the option note), E = ESTIMATE.

## Short answer to "option 4: one tx or many?"

One tx. One Groth16 proof, about 280k gas for the gate (M), about 310k with base cost and calldata, plus the Safe exec overhead (E). The expensive part is offchain: a zkVM proving job that costs minutes and cents to a few dollars per session (E).

## The table

| | **2a: server met-record, Groth16** | **3: P-256 inside Noir/UltraHonk** | **4: zkVM wraps Spartan2 into Groth16** |
|---|---|---|---|
| Idea | Server checks the meeting as today, then signs a small Poseidon record. Phone proves it holds one. | Each phone proves "my hidden enrolled key signed this transcript". The contract combines the two halves. | Aggregator verifies the phones' existing Spartan2 proofs inside SP1/RISC Zero and posts one Groth16 proof. |
| Onchain gas | 285k per tx (M). About 260k over a plain Safe exec. | 5.59M for two proofs plus the combine (M). About 2% of a World Chain block, under a cent at 0.0005 gwei (E). | 280k gate (M), ~310k per tx (E). Verifier deploy 2.6M, done once (M). |
| Tx count | 1 | 1 | 1 |
| Circuit size | 5.4k constraints (M) | 173k gates per phone (M) | Guest: ≥1.0 G cycles for C, 5–16 G for A. Memory cost is not modeled, so maybe 1.5–2× more (E). |
| Prove time, M2 | 0.5–0.8 s with snarkjs (M) | 1.6–2.4 s, ~420 MB (M) | Can't run on this Mac: it needs 16 GB+ RAM (C) |
| Prove time, phone | ~150–200 ms with rapidsnark (E from mopro C) | 2–3 s on a flagship, 5–8 s on a mid Android, ~400 MB (E) | Phone side is unchanged. Aggregator: 1–5 min end to end, $0.3–2+ per session (E; the price comes from one tweet, so treat it as a floor) |
| Proof size | 256 B | 9.5 KB × 2, ~20 KB calldata | 356 B |
| Who can forge presence | **The server key.** A compromised server can mint records. To pass a Safe gate it also needs the victim's holder secret `s`. | **The issuer**, by enrolling non-hardware keys, same as today. Also a rooted phone, because the app computes `half`. | Aggregator plus unaudited Spartan2 fork plus zkVM plus Groth16 setup. With A it's a **blocker** today: nothing binds the code seed to the server, so the aggregator picks the codes. |
| Revealed onchain | nullifier, pairTag, ctx, `now` | pair_tag, nullifiers, nonce, role, both `half` values (so the distance), sample rate (so the platform), ctx | ctx, pairTag, near |
| Revealed to the server | Issue time vs proof time. A stable pairTag lets it narrow the pair down over repeated txs. | Everything: it issued the nonce and stores `half`, so it can map an onchain event to its two devices. | The same as 3 through the public nonce. Also, with A the prover network sees the device keys unless the guest verifies the pair proof. |
| Tonight (hackathon) | Feasible. Contracts and circuit already run. Still to build: a server issue endpoint (EdDSA-BabyJub in Python), holding `s`, the guard. | Tight. The circuit works, but a mobile bb build (mopro/Swoir) is untested, and SBcred4 plus nonce binding are needed. | No. There's no guest yet, and no box to prove on. |
| After | Phase-2 ceremony, bind `hc` to a device at enrollment, per-session nullifier, short expiry. | Context binding in circuit, a phone-only nonce/tag secret, add the POPC commit check (~250k gates), audit. | Guest port, `execute` on 16 GB+, compact matrices, a prover-market account, bind the seed to the server. |
| A → C semantics? | **No.** The chain trusts the server's verdict, so option A keeps running on the server unchanged. | **Yes.** The phone computes `half`; the audio is not in the circuit. | Either. With A it costs 5–16 G cycles and has the seed blocker. With C it's cheaper but inherits C's weaker soundness. |
| Measured vs estimated | Circuit, proof, gas, replay/ctx reverts: M. Phone time: E. | Gates, prove, gas, negative tests: M. Phone: E. The circom path (3.3M constraints) was never proved. | Gas, native verifier work: M. Every cycle, cost and latency number: E. No zkVM ran. |

No option has an L1 data fee number yet. On World Chain (OP stack) it matters most for option 3's ~20 KB of calldata. Measure it on 4801.

## Holes shared by all three prototypes

1. **Freshness and context.** None proves "present at *this* tx". Fix: the phone derives the session nonce from `safeTxHash` before the audio run, the circuit or guest checks it, and the guard compares ctx with the safeTxHash it computes itself.
2. **Front-running.** Every standalone `check`/`consume` is permissionless and burns the nullifier. Only call it from inside the guard's `checkTransaction`, with the proof riding at the tail of `signatures`. Not built anywhere.
3. **"Two devices" means "two enrolled keys".** One phone can attest two keys. Fix: one key per attested device (App Attest / Key Attestation device id), enforced at enrollment.
4. **The server can link.** It issues the nonce. Every option needs a phone-chosen blinded nonce to hide the pair from the server.

## Recommendation

**(a) Tonight's Safe demo, due Sun 09:00 JST: option 2a, bound variant.**
- It's the only one that is small, already runs on anvil, and needs no new phone crypto stack.
- Put `H(safeTxHash)` in the session nonce, so the meeting is tied to the tx. The server learns which tx; accept that for the demo.
- Minimum fixes:
  - holder pid in the record;
  - nullifier per session, not per phone;
  - expiry ~120 s;
  - owner-only allowlist;
  - guard derives safeTxHash itself.
- If mopro/rapidsnark isn't ready in time, prove with snarkjs on the Mac from the phone's `s`, and say so on stage.
- Server-side option A stays as is.

**(b) Real product: option 3.**
- The chain checks the hardware-key signatures itself, and the server drops to "enrolls attested keys". That's the trust cut the user wants.
- 5.6M gas is cheap on World Chain.
- It means moving to option C semantics: the app-computed `half` is trusted. Accept that openly, or keep A's audio check server-side as a second, non-onchain signal.
- Order of work:
  1. Context binding.
  2. Server-unlinkable nonce/tag.
  3. SBcred4 with a BN254 Poseidon2 holder commit.
  4. Measure a mobile bb prover.
  5. Audit.
- Keep 2b (Merkle roots) as a stopgap if the phone prover slips. Keep 4 only if the audio-in-circuit soundness of A proves essential. It's the most infrastructure and the least measured.
