# App invariants: what the phone code must get right

The app finds the beep. If a proof is made, after NEAR, the circuit checks the answer, and an honest app's bug normally means the phone fails to prove.

So on the proof path most app bugs cost **completeness** (an honest phone can't prove), not **soundness** (a cheater passes). On the plaintext path nothing rechecks the half, so an app bug that changes it can change the verdict (`verdict.py:165`). A lying app isn't always caught either: the prover supplies the recording, and the circuit's test has gaps ([05-spike-results.md](05-spike-results.md)). What a cheater can't fake rests on the server, plus the circuit where a proof is made. The issuer credential doesn't show the key was attested (row 14).

App code matters for three things: does an honest phone get a valid proof, is the user safe (keys, signing order, replay), and privacy.

This list comes from one analyst reading the code. Only rows 1 and 2 are proved. Row 5 is checked by a script. Rows 8 and 12 got a second, closer reading with file:line evidence. Rows 3, 4 and 9 are half done: `Commit.lean` proves the circuit side, and the Kotlin side isn't modeled. The rest is reading, not checked by any tool. The analyst found no circuit hole in app-side review. The circuit gaps are in [05-spike-results.md](05-spike-results.md).

## Categories

- **parity**: the app and the circuit compute the same thing. Failure costs completeness on the proof path. On the plaintext path, a wrong half goes straight into the verdict.
- **soundness, enforced elsewhere**: a cheater depends on this, but the server or hardware enforces it, not the app.
- **honest-user safety**: protects a user who plays fair.
- **privacy**: what leaks, and to whom.

## Table

Paths are under `app/composeApp/src/` or `server/pop/`, shortened as found in the code.

| # | Invariant | Category | Where | How to verify | Effort | Status | Concern |
|---|---|---|---|---|---|---|---|
| 1 | The app's pass test is the circuit's test. Popt2Rule.passes(I,Q,E,cn2,B) returns true exactly when (I^2+Q^2)*B >= E*cn2 over the integers. The circuit uses the same predicate: before the arrival it requires d-1 >= 0 (E*cn2 > BAR*env2, so no pass), at the arrival -d >= 0 (a pass), and on the partner side BAR*penv2 - ep*cnp >= 0. cn2 sums cI only, in both places. | parity | app/composeApp/src/commonMain/kotlin/com/enconomy/pop/dsp/Popt2Rule.kt:98-110, 210-240 (U128); circuit lib.nr:399-405 (self), 471-472 (partner), 354-359 (cna) | Lean proof of a pure function: model ULong as Nat mod 2^64, prove a 64x64->128 mul lemma, then add-with-carry, timesSmall under a product bound, and the 128-bit compare | half a day | **Proved**, `AppPasses.lean` | The docstring bound (\|I\|,\|Q\| < 2^62, B < 2^32) is too weak: timesSmall truncates hi*s. Counterexample inside the docstring bound: I=2^61, Q=0, B=2^31, E=1, cn2=1. The true answer is pass (2^153 >= 1), but the function returns false (the high word wraps to 0). Live inputs can't get there: \|I\| <= 12000*127*32768 < 2^35.6. |
| 2 | Turning the signed transcript bytes into numbers gives the same values in the app and the circuit. be(off,n) = be_f(t,off,n). half and self_os_delta read with .toInt() equal signed32 = be_f - msb*2^32. pSelf = a_self - sod, and aPartner = a_self + (1-2*role_b)*half. | parity | Transcript.kt:51-52, 106-139; lib.nr be_f 171-177, signed32 179-182, check_signed 283-295 | Lean proof of a pure function: bytes as Fin 256 lists, Int32 two's complement modelled as BitVec 32 / Int.bmod | 1-2 h | **Proved**, `AppParity.lean` | a_self and p_partner are u32 in the circuit but decoded with .toInt(). Encode requires >= 0, so values stay below 2^31; the theorem needs that as a hypothesis. |
| 3 | Leaf packing matches. OaHash.leafHashU builds the same 69 field elements as lib.nr leaf_hash: element k = sum over j<15 with 15k+j<1024 of u[15k+j]*65536^j, each below 2^240 < p. Samples past the capture are u = 32768 on both sides. | parity | zk/OaHash.kt:59-83; lib.nr:85-100; WitnessInput.kt:132-137 (xs padding) | Lean proof (sponge abstracted as a function of the element list); limb bit placement c[bit/32] \|= v << (bit%32) | 2-3 h | not done. Circuit side only: `Commit.leaf_packing_injective`. `OaHash.kt` isn't modeled. | none |
| 4 | Merkle path layout matches merkle_root. For idx < 256, RecTree2.path(idx)[l] holds the 4 children of node idx/4^l's parent. Child number (idx >> 2l) & 3 is level l's node, and the node hash of the group is level l+1's node. So an honest root passes all 4 selector asserts. | parity | zk/OaHash.kt:94-124; lib.nr merkle_root 108-121, open_leaves 124-130 | Lean proof over an abstract hash on lists (levels built by chunking by 4) | 3-4 h | not done. Circuit side only: `Commit.open_leaves_complete`, `selector_picks`. `OaHash.kt` isn't modeled. | none |
| 5 | The FIR taps and BAR are the same everywhere. The nonzero entries of Popt2Rates.builtIn[48000].h are exactly NZT/NZH. sum\|h\| = 415. B = 4474747 = BAR. L, delta, wpre and wpost match lib.nr and server popt2.RATES. | parity | dsp/Popt2Rule.kt:28-37; lib.nr:23-37; server/pop/popt2.py:28-37 | `fv/v1/zkp/popfv/scripts/rates_parity.py`. Lean by decide on literal arrays is still possible. | 30 min | **Script: matches**, see below | none |
| 6 | The integer accumulators in earliest/Curve never overflow. Each 512-term chunk stays under 2^31 (512*127*32768 = 2130706432). FIR y stays under 2^23.7. Prefix energy cs stays under 2^62.4, even for the widest window (K up to 19200). (I^2+Q^2)*B < 2^95 and E*cn2 < 2^89. All of that also fits the circuit's 96-bit checks, so an honest proof can be made. | parity | dsp/Popt2Rule.kt:96,139-170; zk/WitnessInput.kt:205-229; lib.nr:405,472 | Lean arithmetic bound lemmas (norm_num), given \|x\| <= 32768 and \|c\| <= 127 | 1-2 h | not done | The chunk bound needs templates in [-127,127]. Popt2Code.fromB64 doesn't reject -128. The server never sends -128 (round of scale 127), but at -128 the bound becomes 2^31 and would overflow. |
| 7 | The earliest pass over the app's wide window, if it lands within delta of p_self, is also the first pass in the circuit's narrow window [p_self-96, p_self+96]. E, I and Q depend only on absolute sample positions, with zero padding on both sides. The FFT pre-screen never skips a lag that really passes. | parity | dsp/PopRound2.kt:52-65; dsp/Popt2Rule.kt:127-208; WitnessInput.kt:115-118 (exact re-check) | Window part: Lean on an abstract pass predicate (easy). FFT slack bound: floating point, property test only (WitnessInput re-checks exactly, so a miss only costs completeness) | 1 h (window); not cheaply verifiable (FFT) | not done | none |
| 8 | The pre-checks before proving mirror the circuit. leafS = (p_self-delta-hm)/1024 makes os = p_self-96-31-1024*leafS land in [0,1024), so the 10-bit check passes; same for op. u = (j < ja) with ja < K is monotone, u[K-1] = 0, and sum u = a_self - p_self + delta. a_partner - p_partner is in [-WPRE, WPOST]. own X != partner X. | parity | zk/WitnessInput.kt:85-119,174; lib.nr:360-369, 503-507, 525-526, 275-277 | Lean proof of pure integer facts (Nat div/mod, List sum of indicator) | 1-2 h | **Read only: matches**, see below. No Lean. | none |
| 9 | code_commit packs the same bytes as absorb_bytes. The app packs each template as u8 = v+128, 31-byte big-endian chunks, with the last chunk of 12000 = 387*31 + 3 bytes left short (not padded), in the order cI_self, cQ_self, cI_partner, cQ_partner. | parity | zk/CodeCommit.kt:10-26; zk/OaHash.kt:147-166; lib.nr:148-168; server popt2.py:80-85 | Lean proof of the packing (sponge abstract), or the existing nargo golden vector | 1-2 h | not done. Circuit side only: `Commit.packing_injective`. `CodeCommit.kt` isn't modeled. | none |
| 10 | The recording is fixed before the partner's code is revealed. The app builds rec_root, signs POPC v2 (rec_root) and sends it. It gets partner_code only from the commit response, then signs POPT v2, whose commit_hash = sha256(POPC). The server releases partner_code only after a valid, signed commit for the current attempt and nonce, and not before t0+schedule (too_early). | soundness, enforced elsewhere | RunFlow.kt:254-296; server/pop/sessions.py:261-309; verdict.py:134-138 | Protocol model in Tamarin/ProVerif (ordering + hash binding); the server code is the trusted part | 1-2 days | not done | The order holds, but it protects something only if passing needs the partner's code. Silence passes the partner check without it, a tone may too, and on the plaintext path the half isn't tied to audio at all. |
| 11 | Nonce and attempt are fresh and replay is blocked. The server mints session nonces (secrets.token_hex(32) or PopCtx). The app only echoes them. The server checks role/attempt/nonce on commit and transcript, and rejects old or changed messages (stale_attempt, already_committed). nonce_hi, nonce_lo and attempt are public inputs of the phone and pair proofs. | soundness, enforced elsewhere | server/pop/sessions.py:149, 287-295, 404-406; verdict.py:122-127; RunFlow.kt:134-136; zk.py public_vector | Protocol model (Tamarin); on-chain replay of a used nonce is outside the app | 1-2 days (with the item above) | not done | The app signs any 32-byte nonce the server gives it. It has no freshness check of its own, so honest-user replay safety rests on the server. |
| 12 | Each thing the device key signs carries its own fixed prefix, so a signature for one purpose can't be passed off as another. The formats are: 'POPC'+ver (71 B), 'POPT'+ver (269/311 B), 'pop-req-v1\n...', 'pop-cal-v1\n...', and OWNER_MSG_TAG 'pop-safe-owner-v1' + 32 B. | honest-user safety | Transcript.kt:67-122; Signing.kt:68-74; Calibration.kt:65-67; chain/SafeTx.kt:86-89; PopController.kt:684-690 | Lean: show the first bytes of the five message encoders are pairwise different (pure, decidable); full cross-protocol safety needs a protocol model | 1 h (prefix lemma) | **Read only: holds**, see below. No Lean. | none |
| 13 | The device key can't leave the secure hardware. Android: AndroidKeyStore P-256, PURPOSE_SIGN only, StrongBox then TEE, attestation challenge = enroll nonce; the plain-key fallback runs only on emulators. iOS: Secure Enclave + privateKeyUsage, AfterFirstUnlockThisDeviceOnly; software/Prefs keys only on the simulator. | honest-user safety | androidMain/.../AndroidDeviceKeystore.kt:42-81; iosMain/.../DeviceKeystore.ios.kt:95-145,189-202 | Platform guarantee. The server can't confirm it on Android today, because attestation.py doesn't pin the root (attestation.py:5-6). iOS App Attest, when sent, is checked against Apple's root (appattest.py). Not verifiable in Lean | n/a | not done | none |
| 14 | **Not true today.** The issuer signs SBcred3 for any device that enrols with a holder commit, attested or not (main.py:441). The only gate is enrolment. With flags off, a device with no attestation is refused, but Android doesn't pin the root, so a self-made chain passes and gets `attested: true`. With POP_ALLOW_UNATTESTED or POP_ALLOW_WEB, no chain is needed, and `./demo` sets the first. The circuit verifies the device and issuer signatures, which says nothing about hardware. | soundness, enforced elsewhere | server/pop/main.py:414-468, attestation.py:74, appattest.py:80; lib.nr check_signed 245-275 | Code fix first, then server review; the circuit part is block A | n/a | not met today | iOS sends no X.509 chain. App Attest only runs when paidBuild is set (DeviceKeystore.ios.kt:141). Otherwise enroll needs POP_ALLOW_UNATTESTED. The attestation leg depends on deploy flags. Only chainatt.py:53 gates on `attested`. sessions.py:363, 673 and chainatt.py:103 just pass it on. App.kt:559 shows it as an "Attested key" pill, which misleads, because a self-made chain also gets the flag. Fix: pin the root and issue only to attested keys. |
| 15 | The salt is fresh and secret per proof. salt = secureRandomBytes(31), below 2^248 < p. That hides half in halfCommit from anyone watching the chain. | privacy | PopController.kt:1004,1055; WitnessInput.kt:87,127; lib.nr:528-534 | Platform RNG guarantee; hiding of Poseidon2 is a hash assumption | n/a | not done | The salt goes to the server (proof meta, needed for the pair witness). It hides half only from the chain, not from the server. The server sees half in plaintext in POPT anyway. For a session with a context, the plain half is public anyway to anyone with the sid, once the session is done: `GET /v1/session/{sid}/attestation` returns the transcripts (chainatt.py:107). A session with no context gets a 404 (chainatt.py:79-80). |
| 16 | The recording stays on the phone unless uploading is enabled. | privacy | RunFlow.kt:243,299; PopController.kt:140,464; server main.py:97 | Not verifiable formally; config review | n/a | not done | upload_recordings defaults to True on the server, so by default the full 2.5 s capture goes to the server. Delegated proving (PopController.kt:1055-1061, used on web) also ships the whole witness: 2x13 leaves of audio, codes, credential and signatures. |
| 17 | The issuer credential is accepted only if it names our key and our holder commit, and the issuer matches the one pinned by /v1/config. | honest-user safety | zk/Holder.kt:61-85 | Property test | 30 min | not done | none |

## What was proven

### Row 1: `Popt2Rule.passes` (`AppPasses.lean`). Audit: pass, after one fix round.

The app's pass test is exact. `passes_correct_real`: with |I|, |Q| ≤ 2^36, E and cn2 below 2^63 and B below 2^32, it returns yes exactly when (I²+Q²)·B ≥ E·cn2. It handles `Long.MIN_VALUE` too.

It matches the circuit: `passes_iff_partner_fits`, `passes_iff_self_arrival`, `not_passes_iff_self_before`.

**Bug in a comment (Lean: `docstring_bound_hole`).** `Popt2Rule.kt:98` promises exact answers for |I|, |Q| < 2^62 and B < 2^32. That's false. `passes(2^61, 0, 1, 1, 2^31)` returns false, though 2^153 ≥ 1. The missing condition is (I²+Q²)·B < 2^128. Real inputs stay below 2^35.6 for I and Q, so live code can't reach this. The comment's `cn2 < 2^32` is wrong too: its own test uses 9164281855. Fix the comment.

Limits:
- The theorems assume the circuit's ii, qq, ep, cnp equal the app's I, Q, E, cn2. Nothing proves the app computes those the way the circuit does.
- The self-side theorems assume |I|, |Q| < 2^36. That is the block C assumption, because `ci` and `cq` are free values in the circuit.
- B is any value below 2^23. The value 4474747 matches in both files by reading, and no theorem pins it.
- Only `passes` is covered. The float FFT screen in `earliest()` isn't. A skipped lag costs completeness only.
- Faithful to Kotlin by reading. The vectors of `Popt2RuleTest.kt` hold on the Lean model (`popt2RuleTest_vectors`). It never ran on a JVM.

### Row 2: transcript decoding (`AppParity.lean`). Fable audit: pass. Role mutant ran in Lean 2026-11-06, Opus only.

Role mutant: the role tie (`lib.nr` 233) weakened to "`t[5]` is `0x41` or `0x42`", not tied to `role_b`. `transcript_parity` stopped proving (`error: simp made no progress`, `sorryAx` in its axioms), and `hole_pSelf_overflow` inherited the `sorryAx`. The weakened statement is false: `role_mutant_refuted` compiled with no `sorryAx`, role byte `'A'` with the circuit told role B. The mutant file is deleted.

The app and the circuit read the same numbers from the signed bytes.

- `ktBe_eq_beN`: the Kotlin `be` loop gives the circuit's `be_f` value, up to 7 bytes. The 8-byte fields aren't covered.
- `signed_parity`: `.toInt()` matches `signed32`.
- `encode_roundtrip`: what `W.be` writes decodes back to the same value.
- `transcript_parity`: with `a_self < 2^31`, the circuit's `p_self` and `a_partner` are true integers below 2^33, and Kotlin's getters match them mod 2^32. They match exactly when the value fits in an Int.
- `encoder_to_circuit`: from app numbers to circuit values, end to end.

**Getters can wrap (Lean: `hole_pSelf_overflow`).** `aSelf = 2^31-1`, `selfOsDelta = -2^31` gives circuit `p_self = 2^32-1` but Kotlin `pSelf = -1`. Completeness only. By reading, a valid proof can't reach this case, since `sum u = sod + 96` limits `sod`. `aPartner` has the same shape, without its own witness. Suggested fix: compute both in Long.

### Row 5: rate constants (`scripts/rates_parity.py`). Script, not Lean.

Reads `lib.nr`, `Popt2Rule.kt` and `popt2.py` as text and fails on any difference. Result: 42 comparisons, 0 differences, `ALL OK`.

- 48 kHz, all three files: L 12000, B = BAR 4474747, delta 96, wpre 7200, wpost 12000. `NZT`/`NZH` expand to the same 63 taps. 31 are nonzero and sum|h| = 415.
- 44.1 kHz, app against server only: L 11025, B 3792174, delta 88, wpre 6615, wpost 11025. No circuit carries these.
- `--selftest` changes each number by one, one at a time: 352 changes, 352 caught.

Limit: it shows the numbers match. It doesn't show that the code uses them correctly. It doesn't cover the live `/v1/config` values (`Popt2Rate.sameAs`).

### Row 12: signed message prefixes. Reading only, no tool checked this.

Every message the device key signs starts with a fixed literal. Nothing variable comes before it.

| Message | First bytes | Built at | Signed at | Other side |
|---|---|---|---|---|
| Commit | `POPC` | `Transcript.kt:70` | `RunFlow.kt:209,268` | `codec.py:23` |
| Transcript | `POPT` | `Transcript.kt:78,108` | `RunFlow.kt:236,302` | `codec.py:27` |
| Request | `pop-r` | `Signing.kt:69` | `Signing.kt:74` | `auth.py:20` |
| Calibration | `pop-c` | `Calibration.kt:66` | `PopController.kt:391` | `calibration.py:70` |
| Safe owner | `pop-s` | `SafeTx.kt:38,88` | `PopController.kt:688` | `safe_tx.py:17`, `P256Owner.sol:20` |

The five differ within the first 5 bytes. Those seven `sign` calls are all the `DeviceKey.sign` calls in `commonMain` (the helper at `RunFlow.kt:313` wraps the four `RunFlow` ones). The Android, iOS and web files only implement it.

Limits: this says the messages can't be mistaken for each other. It doesn't say each verifier acts safely on what it accepts. That needs a protocol model. The issuer's `SBcred3` signature is a different key and isn't covered.

### Row 8: pre-proof checks. Reading only, no tool checked this.

| Circuit needs | App pre-check, `WitnessInput.kt` | Circuit, `lib.nr` |
|---|---|---|
| `os` fits 10 bits | 106 (`lo − hm ≥ 0`), 110 (`leafS` by division, so `os` is the remainder) | 503-504 |
| `op` fits 10 bits | 106, 111 | 506-507 |
| Leaf index fits 8 bits | 112 (`leaf + NL ≤ 256`) | 109, 127 |
| Windows fit the opened leaves | 109 (`Geometry` gives 13 per side). Largest end by arithmetic: self 1023 + 12254 = 13277, partner 1023 + 12062 = 13085, both within 13312 | 27-30 |
| `u[K-1] = 0`, monotone | 113 (`ja` below 193), 174 (`u = it < ja`) | 361, 365 |
| `sum u` = target | 116 and 174 give `sum u = aSelf − lo = a_self − p_self + 96` | 369, 521 |
| `a_partner` in window | 107, both ends included | 525-526, both ends included |
| Own X ≠ partner X | 90, on the same 32 bytes | 275-277 |
| Delta | 85 | 241 |
| Pass rule | 117-119, exact, same integers as row 1 | 404-405, 471-472 |

So they match by reading. The row's old citations 500-507, 523-524 and 279 were off and are fixed above.

Traced while reading:

- `WitnessInput.kt:104` lets `selfOsDelta = -2^31` through (`abs` overflow, see below). It's still rejected, at line 106 or 112 if `lo` wraps, and otherwise at 113: `aSelf − lo` works out to `sod + 96`, even with Int wrap, and that's negative.
- Every Int wrap of `pSelf`, `lo` or `aPartner` I traced is rejected at line 106 or 112.
- One mismatch, completeness only. A transcript with `p_partner ≥ 2^31` decodes negative, so `pPartner = -1` can pass line 107 while the circuit reads 2^32−1 and fails. The app's own encoder refuses this (`Transcript.kt:117`), so only a transcript from elsewhere gets there.
- The app's search window is half-open (`PopRound2.kt:50`), and the circuit's includes the end. The app's is the smaller of the two, so it's harmless.

## Concerns

From the analyst, unchanged in meaning:

- Popt2Rule.passes docstring (Popt2Rule.kt:98) gives an insufficient precondition. timesSmall drops the high part of hi*s. Concrete wrong answer inside the stated bound: passes(2^61, 0, 1, 1, 2^31) = false, but the true answer is true. Unreachable live because |I| < 2^35.6. Fix the comment, or add require(i,q < 2^40).
- RecTree.kt is the old Poseidon7/P-256 tree and is dead for POPT v2. Only Popt2Config uses it, for LEAF/DEPTH constants. The live tree is OaHash.recTree/recTreeParallel (Poseidon2/BN254). docs/pop-transcript-v2.md §1-2 is stale too: it says rec_root is Poseidon7/P-256 and code_commit is sha256('pop-code-v2'...). The code and circuit use Poseidon2 code_commitment. Any FV doc should cite OaHash.kt.
- app/prover/src/lib.rs and docs/pop-prover.md describe the old circom/Spartan R1CS prover (oa2t_s48, R1CSSNARK). The deployed path is Noir phone + bb UltraHonk (zk.py, zkprove). lib.rs is not part of the deployed trust base.
- The circuit treats holder_commit ('hold') as opaque bytes and never proves knowledge of the holder secret. Holder.kt uses Poseidon7 for it, and OaHash.kt:184 says no convention was picked. No soundness effect today: the device key carries identity. But the holder secret adds nothing yet.
- iOS attestation: no cert chain, and App Attest only when paidBuild. Otherwise the server needs POP_ALLOW_UNATTESTED. The device-key leg of soundness depends on deploy flags on both platforms. On Android the unpinned root makes it weak even with flags off (attestation.py:5-6).
- Privacy: upload_recordings defaults to True (server main.py:97), so raw room audio is uploaded. Delegated proving ships the full private witness. The salt goes to the server. ZK hiding is against the chain only.
- Completeness: 44.1 kHz has rate constants but no compiled circuit (circuitFor returns null). An OS timestamp error of 2-50 ms passes the plaintext server but can't be proved (|sod| <= delta = 96 frames).
- Completeness: Popt2Code.fromB64 doesn't reject -128. With -128 the Int chunk bound in earliest reaches exactly 2^31 and overflows. The server never emits -128.
- Design (already in 02-scope): the app takes the earliest pass over a 19200-lag window, while the circuit only checks 193 lags around p_self. That's consistent, since the app's pick is also first in the subwindow. But the circuit doesn't show there was no pass in [p_self-WPRE, p_self-96).

From the verifiers, by reading only:

- `WitnessInput.kt:104` uses `abs(selfOsDelta) > d`. Kotlin `abs(Int.MIN_VALUE)` stays negative, so -2^31 slips past this check. Later geometry checks rejected the cases tried. Worth a cleanup.
- `decodeTranscript2` doesn't check `aSelf >= 0`; only the encoder does. With a first byte ≥ 128, Kotlin reads a negative number and the circuit a large positive one. It looks like a completeness edge, not traced through the app.
- The -128 overflow in the `earliest` chunk needs a template byte of -128 and a sample of -32768 on all 512 terms. `WitnessInput.Curve` uses Long, so it doesn't have this. `passes` itself is safe at -128.

## Next cheap wins

Pure code, each 30 minutes to 3 hours by the analyst's estimate:

1. Row 12: signed message prefixes differ. Read, not yet in Lean.
2. Row 8: pre-proof checks mirror the circuit. Read, not yet in Lean.
3. Row 5: the script covers it. `decide` in Lean is optional.
4. Row 6: no overflow in the arrival search.
5. Row 9: `code_commit` byte packing.
6. Rows 3, 4 and 9: model the Kotlin in `OaHash.kt` and `CodeCommit.kt`, and connect it to `Commit.lean`, which has the circuit side.

Rows 10 and 11 need a protocol tool (Tamarin). Rows 13, 15 and 16 rest on platform guarantees or config, and no formal proof applies. Row 14 isn't met today and needs a code fix first. Row 17 is a property test.
