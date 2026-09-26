"""Poseidon (HADES, x^alpha S-box) parameters for the P-256 base field, alpha = 7.

RESEARCH INSTANTIATION. Re-implements the reference parameter scripts of the Poseidon authors
(extern/hadeshash: calc_round_numbers.py, generate_parameters_grain.sage) in plain Python, because
sage is not installed here. Validated by regenerating circomlib's BN254 / alpha=5 parameters
(round numbers for t = 2..17, round constants and MDS for t = 2, 3): see `--selftest`.

  python gen_params.py --selftest            # reproduce circomlib (BN254, alpha 5)
  python gen_params.py 5 16                  # write params_t5.json, params_t16.json (P-256, alpha 7)

Why alpha = 7: x -> x^alpha is a permutation of F_p iff gcd(alpha, p - 1) = 1. For the P-256 base
field p - 1 is divisible by 2, 3 and 5 (so circomlib's alpha = 5 and alpha = 3 both fail), and
gcd(7, p - 1) = 1.

Round numbers: security level M = 128 bits, the inequalities of the latest reference script
(statistical, interpolation, three Groebner bounds, and the 2023/537 binomial bound), smallest
S-box count, then the reference security margin (R_F + 2, R_P * 1.075 rounded up).
MDS: Cauchy matrix from the Grain stream (reference create_mds_p), then accepted only if the
characteristic polynomial of M^i is irreducible for every i = 1..2t. That is a sufficient
condition for the reference's Algorithms 1-3 (no invariant subspace of any M^i, hence no
infinitely long subspace trail); it may reject matrices the reference would keep, in which case
the next Cauchy candidate from the same stream is taken (recorded as `mds_candidate`).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
P256 = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
BN254 = 21888242871839275222246405745257275088548364400416034343698204186575808495617


# ---------------------------------------------------------------- round numbers
def _log(x, base):
    return math.log(x) / math.log(base)


def _log2_binom(n, k):
    # log2 C(n, k) for real n >= k >= 0 via lgamma (sage's binomial(real, real) is the gamma form)
    if k < 0 or n < k:
        return -math.inf
    return (math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)) / math.log(2)


def sat(p, t, R_F, R_P, alpha, M, version):
    n = p.bit_length()
    log2p = _log(p, 2)
    R_F_1 = 6 if M <= (math.floor(log2p - (alpha - 1) / 2.0)) * (t + 1) else 10      # statistical
    R_F_2 = 1 + math.ceil(_log(2, alpha) * min(M, n)) + math.ceil(_log(t, alpha)) - R_P  # interpolation
    if version == "old":
        # hadeshash before 2023 (the version circomlib's table came from)
        R_F_3 = 1 + _log(2, alpha) * min(M / 3.0, log2p / 2.0) - R_P
        R_F_4 = t - 1 + min(_log(2, alpha) * M / float(t + 1), _log(2, alpha) * log2p / 2.0) - R_P
        rmax = max(math.ceil(R_F_1), math.ceil(R_F_2), math.ceil(R_F_3), math.ceil(R_F_4))
        return R_F >= rmax
    R_F_3 = _log(2, alpha) * min(M, log2p) - R_P                                           # Groebner 1
    R_F_4 = t - 1 + _log(2, alpha) * min(M / float(t + 1), log2p / 2.0) - R_P              # Groebner 2
    R_F_5 = (t - 2 + (M / float(2 * _log(alpha, 2))) - R_P) / float(t - 1)                # Groebner 3
    rmax = max(math.ceil(R_F_1), math.ceil(R_F_2), math.ceil(R_F_3), math.ceil(R_F_4), math.ceil(R_F_5))
    # eprint 2023/537 (binomial / Groebner-4) bound, as added to the reference script
    r_temp = math.floor(t / 3.0)
    over = (R_F - 1) * t + R_P + r_temp + r_temp * (R_F / 2.0) + R_P + alpha
    under = r_temp * (R_F / 2.0) + R_P + alpha
    bl = _log2_binom(over, under)
    if bl == math.inf:
        bl = M + 1
    cost_gb4 = math.ceil(2 * bl)
    return R_F >= rmax and cost_gb4 >= M


def round_numbers(p, t, alpha, M=128, version="new", margin=True):
    """Reference find_FD_round_numbers with cost = S-box count (R_F * t + R_P)."""
    best = None
    for R_P_t in range(1, 500):
        for R_F_t in range(4, 100):
            if R_F_t % 2:
                continue
            if sat(p, t, R_F_t, R_P_t, alpha, M, version):
                rf, rp = R_F_t, R_P_t
                if margin:
                    rf += 2
                    rp = int(math.ceil(rp * 1.075))
                cost = rf * t + rp
                if best is None or cost < best[0] or (cost == best[0] and rf < best[1]):
                    best = (cost, rf, rp)
                break          # larger R_F at this R_P only costs more
    return best[1], best[2]


# ---------------------------------------------------------------- Grain LFSR (reference)
class Grain:
    def __init__(self, field, sbox, n, t, R_F, R_P):
        bits = (f"{field:02b}" + f"{sbox:04b}" + f"{n:012b}" + f"{t:012b}" + f"{R_F:010b}" + f"{R_P:010b}"
                + "1" * 30)
        self.s = [int(b) for b in bits]
        assert len(self.s) == 80
        for _ in range(160):
            self._clock()

    def _clock(self):
        s = self.s
        nb = s[62] ^ s[51] ^ s[38] ^ s[23] ^ s[13] ^ s[0]
        s.pop(0)
        s.append(nb)
        return nb

    def bit(self):
        nb = self._clock()
        while nb == 0:
            self._clock()
            nb = self._clock()
        return self._clock()

    def bits(self, n):
        v = 0
        for _ in range(n):
            v = (v << 1) | self.bit()
        return v


def round_constants(g: Grain, p, n, t, R_F, R_P):
    out = []
    for _ in range((R_F + R_P) * t):
        v = g.bits(n)
        while v >= p:
            v = g.bits(n)
        out.append(v)
    return out


def cauchy(g: Grain, p, n, t):
    while True:
        rl = [g.bits(n) % p for _ in range(2 * t)]
        while len(set(rl)) != len(rl):
            rl = [g.bits(n) % p for _ in range(2 * t)]
        xs, ys = rl[:t], rl[t:]
        if any((a + b) % p == 0 for a in xs for b in ys):
            continue
        return [[pow(a + b, -1, p) for b in ys] for a in xs]


# ---------------------------------------------------------------- MDS security check
def matmul(A, B, p):
    n = len(A)
    return [[sum(A[i][k] * B[k][j] for k in range(n)) % p for j in range(n)] for i in range(n)]


def charpoly(A, p):
    """Faddeev-LeVerrier over F_p (p > n). Returns coefficients c[0..n], monic, c[n] = 1, low first."""
    n = len(A)
    I = [[int(i == j) for j in range(n)] for i in range(n)]
    Mk = [[0] * n for _ in range(n)]
    c = [0] * (n + 1)
    c[n] = 1
    for k in range(1, n + 1):
        Mk = matmul(A, Mk, p)
        for i in range(n):
            Mk[i][i] = (Mk[i][i] + c[n - k + 1]) % p
        AM = matmul(A, Mk, p)
        tr = sum(AM[i][i] for i in range(n)) % p
        c[n - k] = (-tr * pow(k, -1, p)) % p
    return c


def pmod(a, f, p):
    a = a[:]
    df = len(f) - 1
    inv = pow(f[-1], -1, p)
    while len(a) - 1 >= df and any(a):
        if a[-1] == 0:
            a.pop()
            continue
        q = a[-1] * inv % p
        sh = len(a) - 1 - df
        for i in range(df + 1):
            a[sh + i] = (a[sh + i] - q * f[i]) % p
        a.pop()
    while len(a) > 1 and a[-1] == 0:
        a.pop()
    return a


def pmulmod(a, b, f, p):
    r = [0] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        if x:
            for j, y in enumerate(b):
                r[i + j] = (r[i + j] + x * y) % p
    return pmod(r, f, p)


def ppowx(e, f, p):
    """x^e mod f."""
    r, b = [1], pmod([0, 1], f, p)
    while e:
        if e & 1:
            r = pmulmod(r, b, f, p)
        b = pmulmod(b, b, f, p)
        e >>= 1
    return r


def pgcd(a, b, p):
    def norm(x):
        x = x[:]
        while len(x) > 1 and x[-1] == 0:
            x.pop()
        return x
    a, b = norm(a), norm(b)
    while not (len(b) == 1 and b[0] == 0):
        a, b = b, norm(pmod(a, b, p)) if len(b) > 1 else [0]
    return a


def irreducible(f, p):
    """Rabin: deg n monic f irreducible iff x^(p^n) = x mod f and gcd(x^(p^(n/q)) - x, f) = 1."""
    n = len(f) - 1
    qs = [q for q in range(2, n + 1) if n % q == 0 and all(q % d for d in range(2, q))]
    xp = ppowx(p, f, p)                       # x^p mod f
    # x^(p^k) = xp composed k times; compute by modular composition
    def frob_k(k):
        r = [0, 1]
        for _ in range(k):
            r = compose(r, xp, f, p)
        return r
    xn = frob_k(n)
    if pmod(xn, f, p) != [0, 1]:
        return False
    for q in qs:
        g = frob_k(n // q)
        g = g + [0] * (2 - len(g))
        g[1] = (g[1] - 1) % p
        if len(pgcd(f, g, p)) != 1:
            return False
    return True


def compose(a, b, f, p):
    """a(b(x)) mod f, Horner."""
    r = [0]
    for c in reversed(a):
        r = pmulmod(r, b, f, p)
        r[0] = (r[0] + c) % p
    return pmod(r, f, p)


def mds_ok(Mx, p):
    t = len(Mx)
    Mi = Mx
    for i in range(1, 2 * t + 1):
        if not irreducible(charpoly(Mi, p), p):
            return False, i
        Mi = matmul(Mi, Mx, p)
    return True, None


# ---------------------------------------------------------------- generate
def generate(p, t, alpha, R_F, R_P, check_mds=True):
    n = p.bit_length()
    g = Grain(1, 0, n, t, R_F, R_P)
    C = round_constants(g, p, n, t, R_F, R_P)
    cand = 0
    while True:
        Mx = cauchy(g, p, n, t)
        if not check_mds:
            break
        ok, fail_i = mds_ok(Mx, p)
        if ok:
            break
        cand += 1
    return {"p": hex(p), "t": t, "alpha": alpha, "R_F": R_F, "R_P": R_P, "security_bits": 128,
            "C": [hex(c) for c in C], "M": [[hex(v) for v in row] for row in Mx], "mds_candidate": cand,
            "note": "research instantiation (reference Grain + round-number scripts re-implemented)"}


def selftest():
    import re
    js = (HERE.parents[1] / "node_modules/circomlibjs/src/poseidon_constants.json")
    ref = json.loads(js.read_text())
    table = [56, 57, 56, 60, 60, 63, 64, 63, 60, 66, 60, 65, 70, 60, 64, 68]
    # circomlib rounds R_P up to a multiple of t (paper instances); compare after the same rounding
    up = lambda v, t: -(-v // t) * t
    got_old = [up(round_numbers(BN254, t, 5, version="old")[1], t) for t in range(2, 18)]
    got_new = [up(round_numbers(BN254, t, 5, version="new")[1], t) for t in range(2, 18)]
    print("circomlib R_P                ", table)
    print("ours, old script, rounded up ", got_old, "match" if got_old == table else "MISMATCH")
    print("ours, 2023 script, rounded up", got_new, "match" if got_new == table else "MISMATCH")
    for t in (2, 3):
        prm = generate(BN254, t, 5, 8, table[t - 2], check_mds=False)
        C_ok = [int(c, 16) for c in prm["C"]] == [int(c, 16) for c in ref["C"][t - 2]]
        M_ok = [[int(v, 16) for v in r] for r in prm["M"]] == [[int(v, 16) for v in r] for r in ref["M"][t - 2]]
        print(f"t={t}: round constants {'match' if C_ok else 'MISMATCH'} ({len(prm['C'])}), "
              f"MDS {'match' if M_ok else 'MISMATCH'}; our irreducibility check on it: {mds_ok([[int(v,16) for v in r] for r in prm['M']], BN254)}")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit()
    assert math.gcd(7, P256 - 1) == 1 and math.gcd(5, P256 - 1) == 5 and math.gcd(3, P256 - 1) == 3
    for t in [int(a) for a in sys.argv[1:]]:
        rf_o, rp_o = round_numbers(P256, t, 7, version="old")
        rf, rp = round_numbers(P256, t, 7, version="new")
        prm = generate(P256, t, 7, rf, rp)
        prm["round_numbers_old_script"] = [rf_o, rp_o]
        (HERE / f"params_t{t}.json").write_text(json.dumps(prm, indent=0))
        print(f"P-256 alpha=7 t={t}: R_F={rf} R_P={rp} (old script: {rf_o}/{rp_o}); "
              f"S-boxes {rf * t + rp}; R1CS ~{4 * (rf * t + rp)}; MDS candidate #{prm['mds_candidate']}")
