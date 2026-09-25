"""Circuit-friendly arrival rule on real N1s data: arrival = earliest lag in the window with
score >= k*T (no local-max / half-max logic).  This is what a prover-named-lag circuit can
enforce cheaply: cross arrivals need only score(t) >= T (a cheater gains only by claiming
EARLIER, which needs an above-T lag there); self arrivals need score < T on every lag
before t in the window (a cheater gains by claiming LATER).

Prints per session: label, baseline decision (result.json), first-crossing decision per
variant, and round flights.  Variants reuse receiver_variants.py.

  $PY first_crossing.py
"""
import json
import sys
import numpy as np

sys.path.insert(0, __import__("os").path.dirname(__file__))
import receiver_variants as rv  # noqa: E402

rv.N_NULL = 4
USE = ["V0 full 1s float, ppm0 (no bank)", "1-bit diff(RAW x), 1-bit template",
       "baseband 2-18 kHz /3 1-bit", "1s noncoherent 4 slices"]
KT = (1.0, 1.5)


def dec(fl):
    if len(fl) < 2: return "UND"
    if max(fl) - min(fl) > 40: return "UND"
    m = float(np.median(fl)); return "NEAR" if m < 45 else "FAR" if m > 80 else "UND"


def main():
    sessions = sorted(p for p in (rv.FIELD / "data" / "sessions").iterdir() if (p / "result.json").exists())
    rows = []
    shifts = {(v, kt): {"self": [], "cross": []} for v in USE for kt in KT}
    for sd in sessions:
        sess = json.loads((sd / "session.json").read_text()); res = json.loads((sd / "result.json").read_text())
        seed = sess["seed_hex"]; lab = sess["labels"]["label_cm"]
        rec = {L: rv._read_wav(sd / f"recording_{L}.wav") for L in "AB"}
        fl = {(v, kt): [] for v in USE for kt in KT}
        base = []
        for rd in res["probes"]["N1s"]["rounds"]:
            if rd.get("flight_cm") is None:
                continue
            base.append(rd["flight_cm"])
            t = {(v, kt): {} for v in USE for kt in KT}
            for key, a in rd["arrivals"].items():
                E, L = key.split("_at_")
                x, sr = rec[L]
                lo = int(round(a["window"][0] * sr)); hi = int(round(a["window"][1] * sr)); nl = hi - lo
                Lt = sr + 200
                seg = x[lo: hi + Lt]
                seg = np.concatenate([seg, np.zeros(max(0, nl + Lt - len(seg)))])
                xm = rv.masked(seg, sr)
                ts = [rv.masked(tt, sr) for tt in
                      [rv.fp.template(seed, "N1s", E, sr)] + [rv.fp.null_template(seed, "N1s", E, sr, i) for i in range(rv.N_NULL)]]
                ref_i = int(round(a["t"] * sr)) - lo
                for v in USE:
                    r = rv.VARIANTS[v](xm, seg, ts, sr, nl)
                    out, D = r[0], r[1]; M = r[3] if len(r) > 3 else 1
                    env, sc = out[0]
                    T = rv.ray_T(np.concatenate([o[1] for o in out[1:]]), len(sc), M)
                    for kt in KT:
                        ab = np.nonzero(sc >= kt * T)[0]
                        if not len(ab):
                            continue
                        i = int(ab[0]) * D
                        t[(v, kt)][key] = a["t"] + (i - ref_i) / sr
                        shifts[(v, kt)]["self" if E == L else "cross"].append(1000 * (i - ref_i) / sr)
            for k_, tt in t.items():
                if len(tt) == 4:
                    fl[k_].append(rv.C / 2 * ((tt["B_at_A"] - tt["A_at_A"]) - (tt["B_at_B"] - tt["A_at_B"]))
                                  - (rd.get("drift_cm") or 0))
        rows.append((sd.name[:8], lab, res["probes"]["N1s"]["decision"]["label"], base, fl))
        print(f"  {sd.name[:8]}", file=sys.stderr)

    print("| session | label cm | baseline | " + " | ".join(f"{v[:22]} k={kt}" for v in USE for kt in KT) + " |")
    print("|---|---|---|" + "---|" * (len(USE) * len(KT)))
    for s, lab, bd, base, fl in sorted(rows, key=lambda r: (r[1] if r[1] is not None else 999)):
        cells = [f"{dec(f)} {np.median(f):.0f}" if f else "UND -" for f in (fl[(v, kt)] for v in USE for kt in KT)]
        print(f"| {s} | {lab} | {bd} {np.median(base):.0f} | " + " | ".join(cells) + " |")
    print("\nshift of first-crossing vs baseline arrival, ms (negative = earlier)")
    for (v, kt), d in shifts.items():
        print(f"  {v[:34]:34s} k={kt}: self med {np.median(d['self']):+.3f} min {np.min(d['self']):+.3f} | "
              f"cross med {np.median(d['cross']):+.3f} min {np.min(d['cross']):+.3f}")


if __name__ == "__main__":
    main()
