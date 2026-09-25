"""Distance sweep and separation analysis for the Proximity-Echo simulation.

Runs each condition over several random seeds (each seed re-rolls noise and the per-trial
beep template), aggregates the score statistics, and reports how well the positive
(same-room) conditions separate from the negative (different-room / attacker) ones.

It reports three discriminators side by side:
  * score (mean)  — the paper's (c_a + c_b) / 2
  * max(c_a, c_b) — the lenient variant from the progress report
  * min(c_a, c_b) — both directions must agree; the security-conservative choice, and the
                    cleanest separator under the asymmetric directional-mic regime.

Run:
    python sweep.py            # default sweep, 5 seeds, L=12 (fast)
    python sweep.py --beeps 20 --seeds 8
"""

from __future__ import annotations

import argparse
import statistics

import scenarios
import scene


def _disc(r: dict) -> dict:
    ca, cb = r["c_a"], r["c_b"]
    return {"mean": r["score"], "max": max(ca, cb), "min": min(ca, cb)}


def run_condition(name: str, trial_factory, seeds: list[int], beeps: int) -> dict:
    rows = []
    for s in seeds:
        trial = trial_factory(s)
        r = scene.run_trial(trial, beeps_per_device=beeps)
        rows.append({"c_a": r["c_a"], "c_b": r["c_b"], **_disc(r)})
    agg = {}
    for key in ("c_a", "c_b", "mean", "max", "min"):
        vals = [row[key] for row in rows]
        agg[key] = (statistics.mean(vals), statistics.pstdev(vals))
    return {"name": name, "rows": rows, "agg": agg}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--beeps", type=int, default=12, help="beeps per device (paper=20)")
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--snr", type=float, default=48.0)
    args = ap.parse_args()
    seeds = list(range(1, args.seeds + 1))

    # Positive conditions use the favorable orientation (laptop mic toward phone) so both
    # directions have a chance — that is the regime the protocol is supposed to accept.
    def fav(distance):
        def make(seed):
            from scene import Room, Trial, compute_shared_room_rirs, laptop, phone
            room = Room(dims=(4.5, 3.5, 2.7), absorption=0.22, max_order=12)
            cx, cy, cz = 2.25, 1.75, 0.75
            lap = laptop((cx - distance / 2, cy, cz), facing_az_deg=0.0)
            ph = phone((cx + distance / 2, cy, cz), speaker_az_deg=180.0)
            rirs = compute_shared_room_rirs(room, lap, ph)
            return Trial(lap, ph, rirs, f"same_{distance*100:.0f}cm", snr_db=args.snr, agc=False, seed=seed)
        return make

    conditions = [
        ("same_room_10cm",     fav(0.10),  True),
        ("same_room_30cm",     fav(0.30),  True),
        ("same_room_100cm",    fav(1.00),  True),
        ("different_rooms",    lambda s: scenarios.different_rooms(snr_db=args.snr, agc=False, seed=s), False),
        ("remote_attacker",    lambda s: scenarios.remote_attacker(snr_db=args.snr, agc=False, seed=s), False),
        ("colocated_attacker", lambda s: scenarios.colocated_attacker(snr_db=args.snr, agc=False, seed=s), False),
    ]

    print(f"seeds={seeds} beeps_per_device={args.beeps} snr_db={args.snr}\n")
    header = f"{'condition':<20} {'class':<4} {'c_a':>12} {'c_b':>12} {'mean':>12} {'max':>12} {'min':>12}"
    print(header)
    print("-" * len(header))
    results = []
    for name, factory, is_pos in conditions:
        res = run_condition(name, factory, seeds, args.beeps)
        res["is_pos"] = is_pos
        results.append(res)
        a = res["agg"]
        cls = "POS" if is_pos else "neg"
        print(f"{name:<20} {cls:<4} "
              + " ".join(f"{a[k][0]:>+6.3f}±{a[k][1]:<4.2f}" for k in ("c_a", "c_b", "mean", "max", "min")))

    # Separation: smallest positive minus largest negative for each discriminator.
    print("\nseparation margin (min positive mean − max negative mean; >0 means separable):")
    for disc in ("mean", "max", "min"):
        pos = [r["agg"][disc][0] for r in results if r["is_pos"]]
        neg = [r["agg"][disc][0] for r in results if not r["is_pos"]]
        margin = min(pos) - max(neg)
        flag = "SEPARABLE" if margin > 0 else "overlap"
        print(f"  {disc:<5}  min(pos)={min(pos):+.3f}  max(neg)={max(neg):+.3f}  margin={margin:+.3f}  [{flag}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
