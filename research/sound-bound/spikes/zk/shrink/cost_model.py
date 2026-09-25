"""Constraint / row estimates per ranging round (4 arrivals) for receiver variants.

R1CS unit costs (circom-style, from ../README.md fit and standard gadgets):
  mult (witness x witness)          1
  linear combination (const coeffs) 0      (circom --O2 folds it; nnz grows instead)
  b-bit range check / bit decomp    b
  compare two b-bit values          b + 1
  Poseidon(16) absorbing 15 elems   610    (README fit: 610 per 225 int16 samples)
Plonkish-with-lookups unit costs (halo2 / plonky3 style, order of magnitude):
  mult-add gate                     1 row
  range check via 16-bit table      1 lookup per 16-bit limb
  popcount(xnor) of 8+8 bits        1 lookup in a 2^16 table
  dynamic index x[tau+n]            1 lookup per fetched sample (RAM/table argument)
  Poseidon2 permutation (t=16)      ~ 30 rows, absorbs 15 elems
  add/linear op                     ~ 1/4 row (width-4 custom gate)

  python cost_model.py
"""
import math

SR = 48_000


def poseidon_r1cs(n_elems):
    return 610 * math.ceil(n_elems / 15)


def fmt(x):
    return f"{x:.2e}"


def rows():
    out = []
    # ---------------------------------------------------------------- baseline
    L, K = 48_000, 19_200
    naive = 4 * 2 * L * K
    out.append(("naive A (README): 1 code, 1 s @48k real, 0.4 s window, I/Q", naive,
                f"4 arrivals x 2 x L{L} x K{K}"))
    corr_per_round = 2 * (7 * 65 + 1) + 2 * (65 + 1)
    out.append(("current receiver as specified (64 nulls, 7 ppm, partner)", corr_per_round * 2 * L * K,
                f"{corr_per_round} correlations x 2LK"))

    # ------------------------------------------------ V3 prover-named lags only
    # cross: 3 lags (claimed + 2 neighbours for local max); self: dense from window start.
    for name, Kself in (("V3 named lags, self dense over 0.15 s pre-window", int(0.15 * SR)),
                        ("V3+V4 named lags, self dense over +-1 ms OS-timestamp window", int(0.002 * SR)),
                        ("V3+V4 named lags, self dense over +-25 ms (web, no OS ts)", int(0.050 * SR))):
        c = 2 * (2 * L * 3) + 2 * (2 * L * Kself)
        out.append((name, c, f"2 cross x 2L x 3 + 2 self x 2L x {Kself}"))

    # ------------------------------------------------ V4 OS timestamps, dense, no naming
    for W_ms in (5, 25):
        Kw = int(2 * W_ms / 1000 * SR)
        out.append((f"V4 window +-{W_ms} ms dense (no naming)", 4 * 2 * L * Kw, f"4 x 2L x {Kw}"))

    # ------------------------------------------------ V6/V7 complex baseband QPSK chips, 1-bit
    Lc = 16_000                    # 1 s at 16 k complex (2-18 kHz), 1 chip per 2 samples at 8 kchip/s ok
    per_lag_bits = 4 * Lc          # I*I, Q*Q, I*Q, Q*I bit products per lag
    for W_ms in (1, 5, 25, 200):
        Kw = int(2 * W_ms / 1000 * 16_000)
        dense = 4 * per_lag_bits * Kw
        out.append((f"V6 baseband 16k complex, 1-bit x 1-bit, dense +-{W_ms} ms (no packing)", dense,
                    f"4 arr x 4 Lc{Lc} x K{Kw}"))
        # stranded packing: 8 bit-digits per field element, 15 lags per block product
        packed = 4 * (4 * Lc * Kw / 64 + 56 * Kw)
        out.append((f"V8 same + stranded packing (ZEN-style), dense +-{W_ms} ms", packed,
                    f"4 arr x (4 Lc K/64 + 56 K), K={Kw}"))

    # ------------------------------------------------ V9 Schwartz-Zippel
    for (tag, Lx, Kx, cmp_bits) in (("48k real int16, 0.4 s window", 48_000, 19_200, 75),
                                    ("16k complex 1-bit, 0.4 s window", 16_000, 6_400, 31),
                                    ("16k complex 1-bit, +-5 ms window", 16_000, 160, 31)):
        N = Lx + Kx
        horner = (N + 2 * Lx + 2 * (N + Lx)) if "real" in tag else 2 * (N + Lx + (N + Lx)) * 2
        cmp = Kx * (4 + cmp_bits)
        out.append((f"V9 SZ identity, {tag}", 4 * (horner + cmp),
                    f"4 x (Horner {horner} + K{Kx} x {4 + cmp_bits} compare); needs in-proof challenge"))
    return out


def extras():
    """Per-arrival side costs that do not scale with lags."""
    L = 48_000; N = L + 19_200
    print("\nside costs per arrival (R1CS):")
    print(f"  int16 range checks, 67.2k samples          {16 * N:>10,}")
    print(f"  Poseidon over 67.2k int16 (15/elem)          {poseidon_r1cs(N / 15):>10,}")
    print(f"  1-bit booleanity, 2 x 16.5k (I,Q)            {2 * 16_500:>10,}")
    print(f"  Poseidon over 33k bits (253/elem)            {poseidon_r1cs(33_000 / 253):>10,}")
    print(f"  template 16k QPSK chips from Poseidon: bits + hash {32_000 + poseidon_r1cs(32_000 / 253):>6,}")
    print(f"  multisine template, 16k random phases (cos/sin ~30 each) + linear IFFT ~ {16_000 * 60 + 800_000:,}")
    print(f"  multisine QPSK phases via SZ closed form C(r)=((1-r^N)/N) sum S_k/(1-w^k r): ~ {16_000 * 6:,}")


def best_stack():
    """QPSK chips 1 s, 16 k complex 1-bit, OS-anchored windows, fixed T, first crossing."""
    Lc = 16_000
    def arrival(K, sz=False):
        bits = 2 * (Lc + K)
        hashc = poseidon_r1cs(bits / 253)
        if sz:   # Horner on X (Lc+K), C (Lc), Y (2Lc+K), re+im, needs in-proof challenge
            corr = 2 * ((Lc + K) + Lc + (2 * Lc + K))
        else:    # stranded packing, 8 bit-digits per element, 2 extractions of 225 per 8 lags
            corr = 4 * Lc * K // 64 + 56 * K
        cmp = 35 * K
        return bits + hashc + corr + cmp, dict(bits=bits, hash=hashc, corr=corr, cmp=cmp)
    tmpl = 2 * (32_000 + poseidon_r1cs(32_000 / 253))
    merkle = 4 * 3 * 240
    binding = 14_268
    print("\nbest stack, one round (R1CS):")
    for tag, Ks, Kc, sz in (("self +-2 ms, cross +-10 ms, stranded", 64, 320, False),
                            ("self +-2 ms, cross +-5 ms, stranded", 64, 160, False),
                            ("self +-2 ms stranded, cross +-10 ms SZ", 64, 320, True)):
        s_, sd = arrival(Ks); c_, cd = arrival(Kc, sz)
        tot = 2 * s_ + 2 * c_ + tmpl + merkle + binding
        print(f"  {tag}: self {s_:,} {sd}  cross {c_:,} {cd}")
        print(f"     round = 2x{s_:,} + 2x{c_:,} + templates {tmpl:,} + merkle {merkle:,} + binding {binding:,}"
              f" = {tot:,}  ({7.37e9 / tot:,.0f}x below naive); per-phone half ~ {(s_ + c_ + tmpl // 2):,}")


if __name__ == "__main__":
    best_stack()
    base = None
    print("| variant | constraints / round | vs naive | arithmetic |\n|---|---|---|---|")
    for name, c, how in rows():
        base = base or c
        print(f"| {name} | {fmt(c)} | {base / c:,.0f}x | {how} |")
    extras()
