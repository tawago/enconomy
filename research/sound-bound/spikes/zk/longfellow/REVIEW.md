# Review of the longfellow track (SBzk1)

Adversarial review, 2026-09-26. Reviewer added `review/synth.py`, `review/attacks.sh` and `logs/review_attacks.log`. No builder code was changed.

Verdict: the circuit is sound for what it claims. The threshold, the role/key crossing, the byte and bit ranges and the Fiat-Shamir binding all hold up, both on paper and under attack. The gaps are in the statement design and the verifier policy: the nullifier binds nothing, the issuer key isn't pinned, and nothing stops one device from filling both roles. None of that is in the arithmetic.

## 1. Numbers re-run (all through `tools/heavy.sh`, M2, load avg 5.3)

| What | Builder | Reviewer |
| --- | --- | --- |
| Recompile circuit | 3.8 s, 828 MB, id `924e3238…` | 3.79 s, 852 MB, id `924e32380812c146…`, file **byte-identical** to `out/sbzk1.circuit` (`[heavy] 4.8s`) |
| Prove, b9e4dd4b (builder benched 180ca04b), 3 runs | 0.70–0.72 s | 0.711 / 0.720 / 0.717 s; 0.87–0.88 s wall incl. load; RSS 255–281 MB (`time -l`: 267–295 MB) |
| Verify, 3 runs | 0.40–0.46 s | 0.459–0.462 s; 0.62 s wall; RSS 203–207 MB |
| Proof size | 386.5–388.7 KB | 386,796–388,044 B |
| `run_tests.sh` | 81/81 | 81/81 (`[heavy] 53.2s`) |
| Reviewer attacks | – | 38/38 as expected (`[heavy] 24.9s`) |

The builder's numbers reproduce.

## 2. Soundness audit

| Point | Finding |
| --- | --- |
| Unconstrained inputs | Every `vinput<N>` goes through `Logic::input()`, which calls `assert_is_bit`. So all bytes are forced into 0..255, and the 64-bit range vectors hold real bits. There is no `<--`-style hint anywhere. SHA block witnesses use the vendor BitPlucker, which constrains them. |
| Field wrap in the threshold | \|1715·d\| < 2^43 and 6·sr < 2^35, both far below p ≈ 2^256. A negative `lo`/`hi` becomes p − small, which has no 64-bit representation. Tested at d = ±(2^32 − 1) (S5, S6): rejected. |
| Threshold math | Verdict is −20 < 17150·d/sr < 60. Multiply by sr/10 and it becomes −2·sr < 1715·d < 6·sr, which is exactly what `lo`/`hi` encode. Edges at sr = 48000: d = 167 (59.67 cm) passes, 168 (60.03) fails, −55 (−19.65) passes, −56 (−20.01) fails. Matches `common.verdict`. sr = 0 can't pass: it would need 1715·d ≥ 1 and ≤ −1 at once (reasoned, not run; `prep.py` divides by sr). |
| Sign convention | d = half_A − half_B, where A is index 0 and gets the constant role byte 0x41 in its signed transcript. Swapping roles makes each device's signature cover a transcript with the wrong role byte. A1 swaps 2dc2eb59 (7.86 cm → −7.86 cm, still inside the window, so only role binding can stop it): rejected. |
| Key crossing | The same `dpk` wires feed the credential, the ECDSA key, "own" in this role's transcript and "partner" in the other role's. A2 splices A of 9afb91c6 with B of d283370f (same two devices, would read 17.5 cm): rejected under either session's nonce. |
| `now <= exp` byte order | `Memcmp::arrange` treats byte n−1 as least significant, i.e. big-endian, which matches the encoding. The builder's `expired` test (exp + 1) can't tell the byte orders apart. A3 can: now = 0x6ade3500 > exp = 0x6ade34e1 is rejected, and now = 0x6ade33ff and now = exp are accepted. |
| `signed32` | Sign bit is `v[31]` = MSB of `b[0]`, correct for big-endian i32. |
| Hash in field | SHA-256 is computed bit-wise in Fp256. No Poseidon, so no alpha/field issue. Digest → Elt is reduced mod p (vendor pattern). About 2^-32 of honest digests fall at or above p, where the honest prover would fail. That costs completeness, not soundness. |
| Fiat-Shamir | `zk_verifier.h`: absorb the Ligero root, then `initialize_sumcheck_fiat_shamir` writes the circuit id, all 587 public inputs and `nterms` zeros before any challenge. Label `sound-bound/SBzk1`. The commitment covers the full private witness plus the pad. OK. The circuit id is inside the transcript, so a proof made for a different circuit fails. The verifier still has to load its own circuit file. |
| Forging prover | This is the honest algorithm running on a bad witness with its self-checks removed. Its forged proofs being rejected shows the verifier actually enforces the constraints. It is not a soundness proof. Honest witness + `--force` verifies, so the forger is faithful. |
| Low-S | Not enforced (builder test `highs`). The statement binds messages, not signature bytes, and the nullifier doesn't use the signature, so this is harmless. |

## 3. Attacks (real fixtures unless marked)

| # | Attack | Result |
| --- | --- | --- |
| A1 | Role swap on 2dc2eb59 (swapped flight −7.86 cm would pass the window) | prover refuses; forged proof **REJECTED** |
| A2 | Cross-session splice, 211 cm + 225 cm sessions → 17.5 cm; nonce of X, then of Y | refused; forged **REJECTED** (both) |
| A3 | Expiry with a byte-order trap (now past exp only in big-endian) | **REJECTED**; the two in-date cases accepted |
| A4 | Same session 180ca04b, fresh random holder secret → new nullifier | **ACCEPTED**. Unlimited valid proofs per session with distinct nullifiers (known gap 1, now demonstrated) |
| A5 | Proof + 8 junk bytes / one byte flipped | junk **ACCEPTED** (reader ignores the trailer); flip **REJECTED** |
| S1–S6 | synthetic: threshold edges and i32 extremes | all as expected (see §2) |
| S8 | synthetic: one device key signs both the A and B transcripts (d = 10) | **ACCEPTED** |
| S1/S3/S8 | synthetic: signed by a self-made issuer | **ACCEPTED** by `sbzk verify`, which takes `issuer_x/y` from `public.txt` |

## 4. Issues

Major:

1. **Nullifier is meaningless as built** (builder gap 1, confirmed by A4). Anyone holding the four signed blobs can prove, and the server holds them if halves meet there. Each new `holder_secret` gives a fresh nullifier, so double-counting is unbounded. The proof says "session N was NEAR", not "I was in it". Fix: SBcred2 with `sha256(holder_secret)` in the credential, plus an equality check (+1 SHA block).
2. **Issuer key is not pinned by the verifier.** It is a public input read from `public.txt`. Anyone can self-issue credentials to software keys (S1/S3/S8 all verified this way). Fix: the verifier hardcodes the allowed issuer key(s) and compares before verifying. This is a policy fix; the circuit is unchanged.
3. **Public nonce equals the session id.** Whoever issued the nonce (the server) knows which device pair ran the session. So against the server, hiding the keys inside the proof buys nothing. Only third-party verifiers are blind. Fix is a design choice: a verifier-chosen challenge, or a nonce the server can't map to a pair.

Minor:

4. **No `dpk_A != dpk_B` check** (S8). If an attested app ever signs a transcript naming itself as partner, one phone can "meet" itself. The app should refuse that before signing. The circuit check is also cheap: a 512-bit inequality, a few hundred gates.
5. **`attempt` is any u8.** The protocol allows 0 or 1. The verifier should reject attempt > 1. Public `attempt` also leaks that a retry happened.
6. **Proof encoding is malleable** (A5, trailing bytes accepted). Not a soundness issue, but don't hash proof bytes as an id. Fix: reject if `ReadBuffer` has bytes left.
7. **High-S accepted, `sr` not pinned, `n_ts` = 1, ~2^-32 honest-failure rate from the mod-p digest.** All low risk; `sr` is signed by both phones.

## 5. Claim corrections

- "the library absorbs the public inputs into the transcript": true. It also absorbs the circuit id (`zk_common.h:167`), so a proof is tied to the circuit even before the verifier pins the file.
- "`expired` tamper shows the expiry check": it shows now > exp is caught only for a +1 step. It does not show byte order. A3 now covers that.
- "4 real NEAR fixtures": the device keys are the same two Secure Enclave keys in all 12 sessions, which is what makes the A2 splice meaningful.
- Phone numbers stay estimates. Their basis (two vendor ratios) is reasonable.

## 6. Reproduce

    cd research/sound-bound/spikes/zk/longfellow
    ../tools/heavy.sh review-lf-attacks ./review/attacks.sh     # 38 cases, ~25 s
