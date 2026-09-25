# ZK gap research, 2026-09-26

Question: can one proof be hardware-bound (tied to the phone's P-256 enclave key), private (hides who met whom from third parties) and fast on a phone? Yesterday it looked like we had to pick two.

Answer: yes, all three together are possible today. The obstacle was circom over BN254, not ZK in general. Separately, option A (the analysis inside the proof) can shrink about 6,800×, but it still adds no security.

Two multi-agent runs, each checked by an independent fact-checker. Raw results: session scratchpad `research.json`, `shrink.json`. Code: `sound-bound/spikes/zk/shrink/`.

Every number below was checked against its primary source unless it is marked as an estimate.

## 1. Hardware key + privacy on a phone: solved elsewhere

| System | What it proves | Phone time | Notes |
| --- | --- | --- | --- |
| Google longfellow-zk (Ligero + sumcheck) | 1 ECDSA P-256 signature, hidden sig | 31 ms iPhone 15+, 53 ms Pixel 9 (single thread) | pk and hash public in this benchmark |
| longfellow toy credential | issuer sig + hidden device-key sig + 3 SHA blocks | 289 ms iPhone 15+, 572 ms Pixel 9, 291 KB proof | closest to our statement |
| longfellow full mdoc | 2 ECDSA + SHA over 2.2 KB + CBOR | 437 ms iPhone 15+, 931 ms Pixel 9 | Apache-2.0, audited (reviews found circuit bugs, fixed in v0.8.4), used by Google Wallet age checks, IETF individual draft |
| OpenAC (PSE): circom `--prime secq256r1` + Spartan2/Hyrax on T-256 | 1 ECDSA under the hidden device key | 99 ms iPhone 17, 340 ms Pixel 10 Pro, 40 KB proof | same circom workflow; ~2 GiB peak RAM |
| circom + BN254, non-native P-256 | same | ~2M constraints, 26 s desktop | dead end |
| zkVMs (SP1, RISC Zero, Jolt) | same | no phone numbers | SP1 not ZK without a wrap; Lattice Jolt has no ZK yet; zk-Jolt (Dory) is alpha |

Circom works fine in P-256's own field (secq256r1). Our local circom 2.1.8 already has the prime; zkID needs 2.2.3.

## 2. Design to copy: the digital-ID wallet pattern

1. **Enroll once.** Our server checks App Attest or Android Key Attestation in the clear, then issues a P-256 credential over the phone's hardware public key.
2. **Per meeting.** The enclave signs this meeting's transcript. The phone proves, without revealing its key: "a key with a valid credential signed this", plus thresholds and a nullifier.

Why the attestation chain stays out of the proof: App Attest is rooted in P-384, and Android chains use P-384, SHA-384 or RSA-4096. That is heavy and unsupported in longfellow.

**Protocol finding.** delta splits by file, so each attested app can compute its own half on the phone and have its enclave sign that half. Signature (2), the separate measurer, goes away, and no audio processing is needed in the proof.

## 3. Holes the fact-checkers found (must fix)

- **Nullifier.** Enclave keys can't compute a PRF, and ECDSA is randomized. Use a holder software secret the issuer never sees. Otherwise the issuer, who holds every device key, can de-anonymize.
- **Linkability through public inputs.** OS output timestamps reveal boot time. App Attest's signCount is unique per key. Keep both private inside the proof.
- **Poseidon in P-256's field.** Poseidon with α=5 is not a permutation there (5 divides p−1), so inputs collide trivially. Use α=7, or SHA-256.
- **Android attestation challenge.** It is fixed before the key exists, so it can't contain pk_dev. It must carry an enrollment nonce instead.
- **Issuer tagging.** A malicious issuer could give each user a unique issuer key. Publish the issuer keys in a transparency list.
- **Our own server** links both phones through IP and timing anyway. ZK hides the meeting only from third parties.
- **Leaked Android factory keyboxes** spoof Key Attestation. Accept RKP-only (short-lived) certificates.

## 4. Option A can shrink about 6,800×

Tested on all 18 field sessions and re-run by the checker under realistic windows. The stack:

- **Code.** Per-round PRF QPSK chips (1 s at 8 kchip/s) replace the multisine. Correlation becomes additions, and the threshold can be derived analytically.
- **Recording.** 16 k complex baseband, notch filter, then 1-bit sign (2-bit if margin runs short).
- **Receiver.** Fixed threshold T instead of 64 null codes, no ppm bank (0 ppm lost nothing: flight error ≤ 2.1 cm), earliest-crossing rule, one-sided checks (a cheater gains only from a late self or an early cross arrival).
- **Windows.** Self ±1–2 ms, anchored by attested native OS timestamps. Cross dense over ±10 ms.
- **Result.** ~1.1M R1CS per round (~0.53M per phone). Decisions 15/0/0 on both probes. Margin min 2.1 dB on JB and 5.9 dB on N1s. NEAR max 34 cm, FAR min 101.5 cm.

What doesn't work:
- Shortening the code (250 ms: margin 0.0–0.4 dB with realistic windows).
- Capturing the recording as 1-bit without the notch first (JB loses 24 of 144 arrivals).
- The web timing prior: Android/Chrome jumps in 2.67 ms steps, up to 22.7 ms. Native timestamps are not yet measured.

Even at this size, A adds no security: the prover still supplies the recording. It is only worth doing if the analysis runner is untrusted.

## 5. Bugs in today's protocol (independent of ZK)

- `fieldprobes._sub` has no round index, so round 1 replays round 0's code. A participant who heard round 0 can pre-play round 1. Fix: derive the code per round from (seed, role, probe, k), with commit-reveal.
- The sound-bound server sends `seed_hex` to both clients, so each phone knows the partner's code. The fieldtest server renders the audio server-side; check that the seed is not sent.

## Next

1. **Spike: OpenAC on the M2 with a real Secure Enclave key.** Clone privacy-ethereum/zkID (the `wallet-unit-poc` folder), run the `show` circuit, and sign SHA256(nonce‖half-result) with a CryptoKit Secure Enclave key.
2. **Spike: longfellow-zk.** Build a toy-credential circuit where an issuer P-256 key certifies pk_dev and pk_dev signs the App Attest-shaped digest. Time it on the M2, then on a phone.
3. **Fix the round-index bug** and derive codes per role and per round.
4. **Measure native OS output-timestamp accuracy** on iOS and Android. Both the anti-cheat check and the small option A depend on it.
