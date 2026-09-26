"""Per-phone size table for option A on the JBL250 receiver: measured circom counts + modeled parts.

  python cost_table.py

Measured (circom 2.1.8 --O2, BN254, this folder): see MEAS. Everything else is a formula below,
with its unit costs also measured here (Poseidon, SHA-256 block) or taken from the fits.
"""
SR = 48_000
L = 12_000            # 250 ms template
K_WEB = 19_200        # -150/+250 ms window
M = 63                # FIR taps (45 nonzero)
KSUB = 512            # sub-window: 225-sample leaf alignment + 243 lags (arr-1 .. arr+240) + slack

MEAS = {              # constraints, measured compiles
    ("core", 512): 339_746, ("core", 1024): 393_204, ("core", 19_200): 2_281_108,
    ("cand", 512): 414_689, ("cand", 1024): 518_835,
    ("exact", 512): 422_071, ("exact", 1024): 533_385, ("exact", 2048): 755_449,
}
POSEIDON16 = 609      # measured (circomlib Poseidon(16))
POSEIDON2 = 240       # measured
SHA_BLOCK = 30_328    # measured: circomlib Sha256, constraints per extra 512-bit block
HASH_PER_SCORE = 2 * POSEIDON16 / 15      # I and Q absorbed as field elements
HASH_PER_SAMPLE = 16 + POSEIDON16 / 225   # int16 range check + packed absorb


def fit(mode):
    ks = sorted(k for (m, k) in MEAS if m == mode and k <= 2048)
    k0, k1 = ks[-2], ks[-1]
    s = (MEAS[(mode, k1)] - MEAS[(mode, k0)]) / (k1 - k0)
    return s, MEAS[(mode, k1)] - s * k1


def r1cs(mode, K):
    if (mode, K) in MEAS:
        return MEAS[(mode, K)], "measured"
    s, b = fit(mode)
    return int(round(s * K + b)), f"extrapolated ({s:.1f}/lag)"


def no_hash(mode, K):
    """Same statement with the window and curve committed by the proof system (commit-and-prove):
    drop the in-circuit Poseidon of x and of (I, Q)."""
    c, _ = r1cs(mode, K)
    nx = K + L - 1 + M - 1
    return int(c - K * HASH_PER_SCORE - nx * HASH_PER_SAMPLE)


def merkle_path(K, depth=13):
    # leaves = 225-sample Poseidon chunks (already paid inside Commit16); a contiguous leaf range
    # needs ~2 sibling paths up a depth-13 tree (27 s x 48 k = 1.3 M samples = 5,760 leaves)
    return 2 * depth * POSEIDON2


def sha_window(K):
    nbytes = 2 * (K + L - 1 + M - 1)
    return (nbytes * 8 + 65 + 511) // 512 * SHA_BLOCK


def live_bar(K, n_null=64, hashed=True):
    # per null code: template Freivalds 3L + K lags x (claimed I,Q [+hash] + Horner 2 + env2 2
    # + upper-bound compare W=88) ; window max must be proven from above for the cross side
    per = 3 * L + K * ((HASH_PER_SCORE if hashed else 0) + 2 + 2 + 89)
    return int(n_null * per)


def glitch_check(span_s=1.4, hashed=True):
    # 20 ms flat-block check over the span between the windows: per sample IsZero(x_i - x_(i-1))
    # (2) + run counter/reset (2) + range on the run length (~1 amortized); samples outside the
    # correlation windows must also be committed
    n = int(span_s * SR)
    return int(n * (5 + (HASH_PER_SAMPLE if hashed else 0)))


def main():
    print(f"unit costs: Poseidon(16) {POSEIDON16}, Poseidon(2) {POSEIDON2}, SHA-256 block {SHA_BLOCK}; "
          f"hash per score {HASH_PER_SCORE:.1f}, per sample {HASH_PER_SAMPLE:.1f}")
    for mode in ("core", "cand", "exact"):
        s, b = fit(mode)
        print(f"fit {mode:5s}: {s:7.2f} per lag + {b:9.0f}")
    print()
    print("per arrival (one window of the phone's own file):")
    rows = [("core  K=19,200 (Freivalds+FS only)", "core", K_WEB),
            ("exact K=19,200 (web window, rule exact)", "exact", K_WEB),
            ("cand  K=512    (one-sided: claimed lag is a candidate)", "cand", KSUB),
            ("exact K=512    (native OS-timestamp window, ~+-5 ms)", "exact", KSUB)]
    for name, mode, K in rows:
        c, how = r1cs(mode, K)
        print(f"  {name:58s} {c:>10,}  {how:26s}  no in-circuit hash: {no_hash(mode, K):>10,}")
    print()
    print("per phone (self + cross arrival in its own file), R1CS constraints:")
    ex_web, _ = r1cs("exact", K_WEB)
    ca_sub, _ = r1cs("cand", KSUB)
    ex_sub, _ = r1cs("exact", KSUB)
    mp = merkle_path(K_WEB)
    variants = [
        ("P1 web windows, both arrivals exact", 2 * ex_web + 2 * mp, 2 * no_hash("exact", K_WEB)),
        ("P2 web windows, self exact + cross one-sided", ex_web + ca_sub + 2 * mp,
         no_hash("exact", K_WEB) + no_hash("cand", KSUB)),
        ("P3 native timestamps, self exact +-5 ms + cross one-sided", ex_sub + ca_sub + 2 * mp,
         no_hash("exact", KSUB) + no_hash("cand", KSUB)),
    ]
    for name, c, nh in variants:
        print(f"  {name:58s} {c:>12,}   commit-and-prove: {nh:>12,}")
    print()
    print("add-ons (modeled):")
    print(f"  rec binding, Poseidon-Merkle path per window          {mp:>12,}")
    print(f"  rec binding, SHA-256 over one web window (int16)      {sha_window(K_WEB):>12,}")
    print(f"  rec binding, SHA-256 over one 512-lag sub-window       {sha_window(KSUB):>12,}")
    print(f"  rec binding, SHA-256 over the whole 27 s float32 WAV   {(5_184_044 * 8 + 65 + 511) // 512 * SHA_BLOCK:>12,}")
    print(f"  live 64-code bar, cross window, hashed                 {live_bar(K_WEB):>12,}")
    print(f"  live 64-code bar, cross window, commit-and-prove       {live_bar(K_WEB, hashed=False):>12,}")
    print(f"  template hashed instead of public (2 x 12k 8-bit)      {int(2 * L * (8 + POSEIDON16 / 450)):>12,}")
    print(f"  20 ms glitch check over 1.4 s span, hashed             {glitch_check():>12,}")
    print(f"  20 ms glitch check over 1.4 s span, commit-and-prove   {glitch_check(hashed=False):>12,}")


if __name__ == "__main__":
    main()
