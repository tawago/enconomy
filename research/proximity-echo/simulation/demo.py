"""Run the labelled scenario matrix once and (optionally) write the rendered WAVs so they
can be inspected with the existing analysis tools, exactly like a live trial.

The pipeline is driven through its production JOINT entry point (as server.py does), and
every row reports the capture-validity verdict plus the sim's ground-truth alias/swap
counts (fix-plan §B2) — an ACCEPT that rides on aliased selections is now impossible to
hide.

Run:
    python demo.py                 # print the matrix
    python demo.py --save ../data/sim_audio   # also write <label>_initiator.wav / _observer.wav
"""

from __future__ import annotations

import argparse

import scenarios
import scene
from scene import Room, Trial, compute_shared_room_rirs, laptop, phone


def favorable(distance_m: float, seed: int = 1) -> Trial:
    room = Room(dims=(4.5, 3.5, 2.7), absorption=0.22, max_order=12)
    cx, cy, cz = 2.25, 1.75, 0.75
    lap = laptop((cx - distance_m / 2, cy, cz), facing_az_deg=0.0)
    ph = phone((cx + distance_m / 2, cy, cz), speaker_az_deg=180.0)
    rirs = compute_shared_room_rirs(room, lap, ph)
    return Trial(lap, ph, rirs, f"fav_{distance_m*100:.0f}cm", snr_db=48.0, agc=False, seed=seed)


def _verdict(r: dict) -> str:
    if not r["capture_valid"]:
        return "WITHHELD"
    return "ACCEPT" if r["proximity_verdict"] else "reject"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", default=None, help="directory to write rendered WAVs")
    ap.add_argument("--beeps", type=int, default=12)
    args = ap.parse_args()

    matrix = [
        ("same_room_30cm_favorable", favorable(0.30)),
        ("same_room_100cm_favorable", favorable(1.00)),
        ("same_room_30cm_adverse", scenarios.same_room(0.30, laptop_facing_az_deg=180.0,
                                                       phone_speaker_az_deg=0.0, snr_db=48, agc=False)),
        ("different_rooms", scenarios.different_rooms(snr_db=48, agc=False)),
        ("remote_attacker", scenarios.remote_attacker(snr_db=48, agc=False)),
        ("colocated_attacker", scenarios.colocated_attacker(snr_db=48, agc=False)),
        ("adverse_alias", scenarios.adverse_alias()),
        ("partner_latch", scenarios.partner_latch()),
        ("late_android", scenarios.late_android()),
        ("partner_in_self_tail", scenarios.partner_in_self_tail()),
        ("deaf_laptop", scenarios.deaf_laptop()),
        ("colliding_clocks", scenarios.colliding_clocks()),
    ]
    print(f"{'scenario':<26}{'c_a':>8}{'c_b':>8}{'mean':>8}{'min':>8}{'alias':>7}{'swap':>6}  {'verdict':<9}  reason")
    print("-" * 104)
    for label, trial in matrix:
        trial.label = label
        r = scene.run_trial(trial, beeps_per_device=args.beeps, save_wav_dir=args.save)
        reason = ",".join(r["failure_reasons"]) if r["failure_reasons"] else ""
        print(f"{label:<26}{r['c_a']:>+8.3f}{r['c_b']:>+8.3f}{r['score']:>+8.3f}"
              f"{min(r['c_a'], r['c_b']):>+8.3f}{r['alias_count']:>7}{r['swap_count']:>6}  "
              f"{_verdict(r):<9}  {reason}")
    if args.save:
        print(f"\nWAVs written to {args.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
