"""Which flights can the per-phone statement prove at all, per session (round 0, pinned web window)?

Self arrival: forced (first lag >= bar from p_self - delta), so one value.
Partner arrival: any lag >= bar inside [p_partner - 150 ms, p_partner + 250 ms]. Both halves shrink the
flight when the partner arrival moves earlier, so the smallest provable flight uses the earliest such lag
in both files, i.e. the honest one. Prints the smallest and largest provable flight per session.

  $PY provable_range.py  -> logs/provable_range.txt
"""
from common2 import HERE, flight_cm, verdict
import twin2

lines = []
for d in twin2.tw1.sessions():
    s8 = d.name[:8]
    _, session, *_ = twin2.load(s8)
    a = twin2.arrivals(s8, 0, keep_curve=True)
    sA, sB = a["A_at_A"]["n"], a["B_at_B"]["n"]
    pA = [a["B_at_A"]["lo"] + j for j, ok in enumerate(a["B_at_A"]["ok"]) if ok]   # partner lags >= bar, A's file
    pB = [a["A_at_B"]["lo"] + j for j, ok in enumerate(a["A_at_B"]["ok"]) if ok]
    fmin = flight_cm(min(pA) - sA, sB - min(pB))
    fmax = flight_cm(max(pA) - sA, sB - max(pB))
    lines.append(f"{s8} label {session['labels']['label_cm']:5.0f}  provable flight {fmin:7.1f} .. {fmax:8.1f} cm  "
                 f"(lags >= bar: A file {len(pA)}, B file {len(pB)})  smallest -> {verdict(fmin)}")
    print(lines[-1], flush=True)
(HERE / "logs" / "provable_range.txt").write_text("\n".join(lines) + "\n")
