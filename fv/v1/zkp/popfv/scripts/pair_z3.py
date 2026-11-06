"""Independent z3 cross-check of block G (noir/pair/src/main.nr), separate from the Lean proof.

Field elements are z3 Ints in [0, p). Every field operation is reduced mod p explicitly:
    red(e) = e - q*p with a fresh integer q and 0 <= red(e) < p.
assert_max_bit_size::<k>(e)  <=>  red(e) < 2^k.
Hashes / commitment checks are omitted (opaque, binding out of scope; they constrain nothing else).

Checks:
  SOUND    field constraints hold, but the integer claim fails  -> expect unsat
  COMPLETE honest integer inputs satisfy the claim, but some field constraint fails -> expect unsat
  EDGES    z3 finds in-range inputs at exactly X = -20 and X = 60 (sat); evaluated concretely mod p,
           the circuit rejects them, so both inequalities are strict
  SAT      sanity: the constraints are satisfiable at all -> expect sat
Run:  uv run --with z3-solver python scripts/pair_z3.py
"""
import sys
from z3 import Int, Ints, Solver, And, Or, Not, If, sat, unsat

P = 21888242871839275222246405745257275088548364400416034343698204186575808495617
TIMEOUT_MS = 300_000


class Field:
    def __init__(self, s):
        self.s = s
        self.k = 0

    def red(self, e):
        """Return a fresh var equal to e mod p (Noir field arithmetic)."""
        self.k += 1
        q, r = Int(f"q{self.k}"), Int(f"r{self.k}")
        self.s.add(r == e - q * P, 0 <= r, r < P)
        return r

    def fits(self, e, k):
        return self.red(e) < 2 ** k


def circuit(F, half_a, half_b, sr_a, sr_b):
    """Constraints of main.nr lines 26-36 (25 is the key check, trivially independent)."""
    sa, sb = sr_a, sr_b  # u32 as Field, < p already
    c = []
    c.append(F.fits(half_a + 2147483648, 32))      # line 26
    c.append(F.fits(half_b + 2147483648, 32))      # line 27
    c.append(F.fits(sa - 36000, 17))               # line 28
    c.append(F.fits(96000 - sa, 17))               # line 29
    c.append(F.fits(sb - 36000, 17))               # line 30
    c.append(F.fits(96000 - sb, 17))               # line 31
    n = F.red(F.red(half_a * sb) - F.red(half_b * sa))  # line 33
    s = F.red(sa * sb)                                  # line 34
    c.append(F.fits(34300 * n + 40 * s - 1, 70))   # line 35
    c.append(F.fits(120 * s - 34300 * n - 1, 70))  # line 36
    return And(c)


def signed(x):
    """Canonical signed representative of a field element."""
    return If(x < (P - 1) // 2 + 1, x, x - P)


def in_ranges(hA, hB, srA, srB):
    return And(-2**31 <= hA, hA < 2**31, -2**31 <= hB, hB < 2**31,
               36000 <= srA, srA <= 96000, 36000 <= srB, srB <= 96000)


def claim(hA, hB, srA, srB):
    """-20 < 17150 (hA/srA - hB/srB) < 60, multiplied by 2 srA srB > 0 (valid since srA, srB > 0)."""
    n = hA * srB - hB * srA
    s = srA * srB
    return And(in_ranges(hA, hB, srA, srB), -40 * s < 34300 * n, 34300 * n < 120 * s)


def run(name, s, want):
    s.set("timeout", TIMEOUT_MS)
    r = s.check()
    ok = (r == want)
    print(f"{name:10s} z3: {r}  (expected {want})  {'OK' if ok else 'MISMATCH'}")
    if r == sat:
        m = s.model()
        print("   model:", {str(d): m[d] for d in m.decls() if not str(d).startswith(('q', 'r'))})
    return ok


def main():
    ok = True

    # SOUND: field-level witness that passes but breaks the integer claim.
    s = Solver(); F = Field(s)
    half_a, half_b, sr_a, sr_b = Ints("half_a half_b sr_a sr_b")
    s.add(0 <= half_a, half_a < P, 0 <= half_b, half_b < P)
    s.add(0 <= sr_a, sr_a < 2**32, 0 <= sr_b, sr_b < 2**32)
    s.add(circuit(F, half_a, half_b, sr_a, sr_b))
    s.add(Not(claim(signed(half_a), signed(half_b), sr_a, sr_b)))
    ok &= run("SOUND", s, unsat)

    # COMPLETE: honest integers satisfying the claim, embedded as field elements, but rejected.
    s = Solver(); F = Field(s)
    hA, hB, srA, srB = Ints("hA hB srA srB")
    s.add(claim(hA, hB, srA, srB))
    ha_f, hb_f = If(hA >= 0, hA, hA + P), If(hB >= 0, hB, hB + P)
    s.add(Not(circuit(F, ha_f, hb_f, srA, srB)))
    ok &= run("COMPLETE", s, unsat)

    # EDGES: z3 finds in-range inputs with X == -20 exactly (34300 n == -40 s) and X == 60
    # (34300 n == 120 s). Then the circuit is evaluated on them concretely, in exact mod-p
    # arithmetic: lines 35/36 must reject (so both edges are strict, the '- 1' does it).
    for nm, edge in [("EDGE-20", lambda n, s_: 34300 * n == -40 * s_),
                     ("EDGE60", lambda n, s_: 34300 * n == 120 * s_)]:
        hA, hB, srA, srB = Ints("hA hB srA srB")
        n, s_ = hA * srB - hB * srA, srA * srB
        s = Solver(); s.add(in_ranges(hA, hB, srA, srB), edge(n, s_))
        good = run(nm, s, sat)
        ok &= good
        if good:
            m = s.model()
            a, b, ra, rb = (m[v].as_long() for v in (hA, hB, srA, srB))
            fa, fb = a % P, b % P
            nf = (fa * rb - fb * ra) % P
            sf = (ra * rb) % P
            l35 = (34300 * nf + 40 * sf - 1) % P
            l36 = (120 * sf - 34300 * nf - 1) % P
            acc = l35 < 2**70 and l36 < 2**70
            print(f"   line35 val bits={l35.bit_length()}  line36 val bits={l36.bit_length()}  "
                  f"accepted={acc}  (expected False)  {'OK' if not acc else 'MISMATCH'}")
            ok &= not acc

    # SAT sanity: some accepted input exists.
    s = Solver(); F = Field(s)
    half_a, half_b, sr_a, sr_b = Ints("half_a half_b sr_a sr_b")
    s.add(0 <= half_a, half_a < P, 0 <= half_b, half_b < P, 0 <= sr_a, sr_a < 2**32, 0 <= sr_b, sr_b < 2**32)
    s.add(circuit(F, half_a, half_b, sr_a, sr_b))
    ok &= run("SAT", s, sat)

    print("ALL OK" if ok else "FAILURES")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
