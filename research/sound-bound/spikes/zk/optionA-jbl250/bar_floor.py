"""Live 64-code bar vs a fixed floor T0 on the JBL250 walk (reads result.json only).

Per window: Gumbel (loc, s) recovered from the stored null median and T = isf(1e-4/3);
P(chance max > T0) = Gumbel sf(T0) is what the fixed floor gives in that room.
  python bar_floor.py [T0 ...]
"""
import json, math, sys
from pathlib import Path
import twin

T0s = [float(v) for v in sys.argv[1:]] or [0.08, 0.09, 0.10]
p = 1e-4 / 3
zq = -math.log(-math.log(1 - p))
zm = -math.log(math.log(2))
rows = []
for d in twin.sessions():
    r0 = json.loads((d / "result.json").read_text())["probes"]["JBL250"]["rounds"][0]
    for key, a in r0["arrivals"].items():
        T, m = a["T"] / 100, a["null_median"] / 100
        s = (T - m) / (zq - zm)
        loc = m - zm * s
        rows.append((d.name[:8], key, T, m, a["null_max"] / 100, a["right_pct"] / 100, loc, s))
print(f"windows {len(rows)}  live T {min(r[2] for r in rows):.4f}..{max(r[2] for r in rows):.4f}  "
      f"null median {min(r[3] for r in rows):.4f}..{max(r[3] for r in rows):.4f}  "
      f"arrival score min {min(r[5] for r in rows):.4f}")
for T0 in T0s:
    pe = [1 - math.exp(-math.exp(-(T0 - loc) / s)) for *_, loc, s in rows]
    print(f"T0={T0:.3f}: windows with T0 < live T: {sum(T0 < r[2] for r in rows)}; "
          f"P(chance max > T0) per window: max {max(pe):.2e}, median {sorted(pe)[len(pe)//2]:.2e}; "
          f"arrivals below T0: {sum(r[5] < T0 for r in rows)}")
