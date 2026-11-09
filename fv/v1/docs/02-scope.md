# Scope: what we verify, what we trust

## Pipeline

1. **App** records, finds arrival times (Kotlin, on device). Outside the circuit.
2. **Each phone signs its half** as a plain number.
3. **The server decides NEAR** from those two numbers (`server/pop/verdict.py:165`). No circuit has run yet.
4. **`phone` circuit, optional, after NEAR** (`server/pop/sessions.py:604-605`), checks the arrival times against
   the signed recording. Outputs a hiding commitment to `half` = gap between "heard my own beep" and "heard
   partner's beep". This is **detection**.
5. **`pair` circuit, optional,** opens both `half` values, checks `c/2 · (hA/srA − hB/srB)` ∈ (−20, 60) cm.
   This is **ranging**.

Everything below covers steps 4 and 5.

Step 3 has its own work now: [`../server/README.md`](../server/README.md), basic flow only, `context=None`, `early_nonce=False`, on the checkout's own `server/`. This shows the server follows its rules on signed numbers. A phone can still sign a false half (CN1, X1).

When a proof is made, the circuit doesn't trust the app's search. It rechecks the answer against the signed
recording, so a wrong arrival on that recording gets rejected. Without a proof, nothing rechecks the app. And even
with one, this is not "if the app lies, the circuit rejects":

- The prover supplies the recording, and a dishonest app can build it.
- The phone gets its own code before capture. So the self side binds nothing against a dishonest app.
- The partner side binds only "the partner's code passes the test at that lag". Silence passes that today.

See [05-spike-results.md](05-spike-results.md).

## Blocks (`oalib/src/lib.nr` + mains)

| | Block | What it checks | ~Lines | Difficulty |
|---|---|---|---|---|
| A | `check_signed`, `be_f`, `signed32`, `unpack_issuer` | transcript bytes/offsets, device sig, credential, expiry, field extraction | 110 | easy–medium |
| B | `open_leaves`, `merkle_root`, `leaf_hash` | the samples come from the signed recording at the right offset | 50 | medium |
| C | Freivalds part of `self_side` (`fs_challenges`, `lhs == acc`) | the claimed correlation curve I, Q is the real one (random spot check) | 50 | medium–hard |
| D | arrival rule in `self_side` (`u` flags, 96-bit checks) | score < bar before `a_self`, ≥ bar at it | 50 | medium–hard, **the heart** |
| E | `partner_side` | partner's code scores ≥ bar at `a_partner` | 40 | medium |
| F | `phone_core` glue | window offsets (10-bit), WPRE/WPOST window (33-bit), half commitment | 70 | easy |
| G | `pair/src/main.nr` | distance inequality, rate ranges, crossed keys | 37 | easy |
| H | `code_commitment` | templates bound to the signed code commit | 10 | easy |

About 400 lines of real logic. The `_opt` variant (`phone_core_opt`, ~275 lines) is the same claim with a
cheaper FIR check. **Deployed is `phone`, not `phone_opt`**, meaning the `PhoneVerifier` on Sepolia. The live Safe guard doesn't call it
(`contracts/deployments/11155111.json`). The ENS bridge calls it for its optional check (`bridge/bridge.py:543`).
The VK_HASH in `contracts/zk/src/PhoneVerifier.sol`
(`0x2991b4b8…1aba`) matches the `PhoneVerifier.sol` generated from the built circuit; `phone_opt` is `0x2495c674…74a4`.
Verify `phone_core`; skip `_opt`.

## What each proof says (one line each)

All of these now have Lean theorems, under named hypotheses. Verdicts are in [05-spike-results.md](05-spike-results.md).
`Chain.lean` joins them. Its closing review found no proof defect and failed only on wording, since fixed.

- **A** (`Signed.lean`): the fields we use (`a_self`, `half`, `sod`, `rec_root`, keys…) are the bytes at the spec offsets of a
  transcript that verified under a key inside a credential the issuer's key verified, unexpired at `valid_at`. "Really signed"
  needs the named unforgeability hypotheses. "Keys" means X coordinates: partner Y is never read.
- **B** (`Commit.lean`): `xs[i]` = recording sample `p_self − 96 − 31 + i`, given `rec_root` is a tree over that recording and
  no Poseidon2 collision on the opened paths. The circuit doesn't enforce the first part.
- **C** (`Freivalds.lean`): for a witness fixed in advance, at most 193p of the p² challenges pass with a false I, Q, so odds
  ≤ 193/p, below 2⁻²⁴⁶. Needs p prime. That the real hash output misses them is the random-oracle assumption, unproved.
- **D**: see 01-primer.
- **E**: `BAR × match_p ≥ loudness_p` at `a_partner`.
- **F**: `a_partner − p_partner` ∈ [−WPRE, WPOST]; given Poseidon2 is collision resistant, commitment binds nonce,
  attempt, role, sr, half, salt, both keys. (`half_commit_binds` assumes this at the two openings.)
- **G**: accepts ⇔ −20 < 17150 · (hA/srA − hB/srB) < 60, both rates in [36000, 96000], no wraparound.
  Hand check: |n| < 2⁴⁹, so `34300·n + 40·s` < 2⁷⁰ ≪ p.
- **H** (`Commit.lean`): `code_commit` = Poseidon2 sponge over the four templates. One commitment means one set of templates,
  under `CodeBinds`.
- **All** (`Chain.lean`): `phone_sound` and `presence_sound`. Under all the hypotheses, the signed numbers obey the literal tests
  and -20 < flight < 60. Nothing here says a beep was heard or where the phones were. Silence meets every hypothesis.

## Trusted base (assumed, not proven)

- The server: it holds the seed, derives the codes, decides the verdict and signs the credential and chain
  attestation. Every live property rests on it. A cheating server can report any verdict, though it can't forge device signatures.
- SHA-256, ECDSA P-256, Poseidon2: secure. In Lean they are opaque, and each use is a named hypothesis on these exact inputs.
  Full list in [05-spike-results.md](05-spike-results.md).
- Fiat-Shamir: the hash output acts like a fresh random challenge, and p is prime
- The Lean model equals the Noir code. Hand-written. Lampe can't replace it today.
- Noir compiler (nargo 1.0.0-beta.22) and Barretenberg UltraHonk: compile and prove faithfully
- The Solidity verifier matches the vk
- Physics: rooms, multipath, speaker/mic latency (measurement only)
- Protocol-level cheating (relay, collusion, the 2026-09-25 single-cheater hole): a different kind of FV
  (Tamarin/ProVerif), not this one

## Things the formal spec will force us to state

- **E checks "loud enough", not "first".** D proves the self arrival is the first lag that passes the test; E only
  proves the partner's code passes it at `a_partner`, anywhere inside the WPRE/WPOST window. September's notes list it as
  a bounded gap. No source ties it to echoes. It still needs a written choice: gap 6, owner to confirm.
- **The app and the circuit use the same bar on v2.** `max(Gumbel, decoy max, floor)` (`PopDsp.kt:102`) is v1 code.
  `PopRound2.kt:18` says it isn't run. `Popt2Rule.earliest` uses only `passes(.., rate.B)`. So no stricter live bar
  stands between a stock app and what the circuit accepts. Only the flat-run glitch check and the self-timestamp
  tolerance do.
- **"Over the bar" doesn't mean "heard".** The test is `BAR × match ≥ loudness`, and 0 ≥ 0 passes.
- **Every `assert_max_bit_size` is a "≥ 0" claim** that needs a no-wraparound bound.
- **`p_self` and `p_partner` are the signer's numbers.** So "first of 193 lags" and the partner window sit where the signer puts them.
- **Keys means X coordinates.** The circuit never reads partner Y. The server compares whole keys (`verdict.py:159`).
