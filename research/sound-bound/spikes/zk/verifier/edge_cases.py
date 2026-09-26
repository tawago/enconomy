"""Edge semantics of the cross-multiplied NEAR check vs server/pop/verdict.decide() (the reference).

  server/.venv/bin/python edge_cases.py        # -> edge_cases.json + summary
Imports server/pop read-only. For each (sr_A, sr_B) and halves around both thresholds, compares
  exact integer rule (what oa2t_pair enforces): NEAR iff 34300 N + 40 S > 0 and 120 S - 34300 N > 0,
                                                 N = hA srB - hB srA, S = srA srB
  server: decide(flight_cm(hA, srA, hB, srB))   (floats)
Exact ties need 34300 | 120 S or 40 S, e.g. sr 68,600 (= 2 x 34,300) where d = 240 is exactly 60 cm.
The cases also feed run_tests_popt2.py edges (circuit-level check through the pair witness).
"""
import json
import sys
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
sys.path.insert(0, str(REPO / "server"))
from pop import constants as K  # noqa: E402
from pop.verdict import decide, flight_cm  # noqa: E402

C, LO, HI = K.SPEED_OF_SOUND_CM_S, K.IMPOSSIBLE_CM, K.NEAR_CM


def exact(ha, sa, hb, sb):
    n, s = ha * sb - hb * sa, sa * sb
    if C * n <= 2 * LO * s:
        return "impossible_flight"
    if C * n >= 2 * HI * s:
        return "too_far"
    return "NEAR"


def server(ha, sa, hb, sb):
    v, why = decide(flight_cm(ha, sa, hb, sb))
    return "NEAR" if v == "NEAR" else why


def boundary_ha(hb, sa, sb, cm):
    """Rational hA where flight == cm exactly."""
    return Fraction(2 * cm * sa * sb, C * sb) + Fraction(hb * sa, sb)


def main():
    pairs = [(48000, 48000), (48000, 44100), (44100, 48000), (44100, 44100), (36000, 96000), (96000, 36000),
             (68600, 68600), (68600, 72030), (72030, 68600), (47999, 44101)]
    cases, mism = [], []
    for sa, sb in pairs:
        for hb in (0, 45000, 41300, -12345, 2**31 - 1 - 200000):
            for cm in (LO, HI):
                b = boundary_ha(hb, sa, sb, cm)
                for ha in range(int(b) - 3, int(b) + 4):
                    if not -2**31 <= ha < 2**31:     # halves are signed i32 on the wire
                        continue
                    e, s = exact(ha, sa, hb, sb), server(ha, sa, hb, sb)
                    exact_tie = C * (ha * sb - hb * sa) == 2 * cm * sa * sb
                    row = {"srA": sa, "srB": sb, "hA": ha, "hB": hb, "exact": e, "server": s, "tie": exact_tie,
                           "flight_float": flight_cm(ha, sa, hb, sb)}
                    cases.append(row)
                    if e != s:
                        mism.append(row)
    (HERE / "edge_cases.json").write_text(json.dumps(cases))
    ties = [c for c in cases if c["tie"]]
    print(f"{len(cases)} cases, {len(ties)} exact ties, {len(mism)} exact-vs-server mismatches")
    for c in ties:
        print("  tie", c)
    for c in mism:
        print("  MISMATCH", c)
    only_ties = all(c["tie"] for c in mism)
    print("every mismatch is an exact tie where the server's float flight rounds across the bound; "
          "the integer rule is exact" if only_ties else "NON-TIE MISMATCH: investigate")
    return 0 if only_ties else 1


if __name__ == "__main__":
    sys.exit(main())
