"""Synthetic end-to-end check for sound-bound analysis.

Builds fake session directories (contract layout) for two simulated phones,
runs analyze_session on them, and prints a table.  This is a sanity script,
not a test suite: run it by hand, read the numbers.

  python synth_check.py
"""

from __future__ import annotations

import json
import pathlib
import shutil

import numpy as np
import soundfile as sf

import probes
from analysis import analyze_session

SCRATCH = pathlib.Path(
    "/private/tmp/claude-501/-Users-takahiro-ogawa-dev-enconomy-research-proximity-echo"
    "/26bd5281-92b7-40ad-8374-472856ce1c02/scratchpad/sb-synth"
)
SEED = "5b" * 32
SR = 48000
PERIOD = 1.0
B_OFFSET = 0.5
ROUNDS = 4
LEAD = 0.5
TOTAL = 5.5
C = 343.0
SELF_M = 0.12          # mic-to-own-speaker path on a phone
NOISE_DB = -40.0
RT60 = 0.4
REVERB_LEVEL = 0.05    # fixed room return, independent of source distance
REVERB_START_S = 0.003


def add_delayed(buf, sig, t_s, amp, sr, rng=None):
    """Add sig into buf at fractional time t_s, via an FFT phase ramp."""
    n0 = int(np.floor(t_s * sr))
    frac = t_s * sr - n0
    m = 1 << int(np.ceil(np.log2(len(sig) + 64)))
    pad = np.zeros(m)
    pad[: len(sig)] = sig
    spec = np.fft.rfft(pad)
    k = np.fft.rfftfreq(m, 1.0 / m)
    spec *= np.exp(-2j * np.pi * k * frac / m)
    y = np.fft.irfft(spec, m) * amp
    a, b = n0, min(len(buf), n0 + m)
    if a < 0 or b <= a:
        return
    buf[a:b] += y[: b - a]


def add_reverb(buf, sig, t_s, sr, rng):
    """Exponentially decaying dense tail, fixed level, starting a few ms late."""
    n_taps = 400
    delays = rng.uniform(REVERB_START_S, RT60, n_taps)
    order = np.argsort(delays)
    delays = delays[order]
    # -60 dB over RT60
    gains = 10 ** (-3.0 * delays / RT60) * rng.normal(0, 1, n_taps)
    gains *= REVERB_LEVEL / np.sqrt(np.sum(gains**2))
    for dly, g in zip(delays, gains):
        add_delayed(buf, sig, t_s + dly, g, sr)


def build_session(root: pathlib.Path, d_m: float, rng, mutate=None) -> pathlib.Path:
    """One synthetic two-phone exchange at cross distance d_m."""
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    pa = probes.generate(SEED, "A", SR).astype(np.float64)
    pb = probes.generate(SEED, "B", SR).astype(np.float64)
    pr = {"A": pa, "B": pb}

    # Per-device unknowns.  The audio stack latency really is 20-200 ms and
    # differs per phone; the ctx clock is offset by the same stack on the way
    # in and on the way out, so what the analysis cannot know is only the
    # small residual.  The big latency is what the delta formula cancels.
    lat = {"A": rng.uniform(0.020, 0.200), "B": rng.uniform(0.020, 0.200)}
    resid = {"A": rng.uniform(-0.005, 0.005), "B": rng.uniform(-0.005, 0.005)}
    ctx_off = {"A": rng.uniform(0, 500), "B": rng.uniform(0, 500)}  # clock offset

    # absolute (acoustic) times, 0 = server start
    emit = {
        "A": [k * PERIOD + lat["A"] for k in range(ROUNDS)],
        "B": [B_OFFSET + k * PERIOD + lat["B"] for k in range(ROUNDS)],
    }
    cap_true = {r: -LEAD + lat[r] + resid[r] for r in ("A", "B")}

    n = int(round(TOTAL * SR))
    recs = {}
    for listener in ("A", "B"):
        buf = rng.normal(0, 10 ** (NOISE_DB / 20.0) * 0.05, n)
        for emitter in ("A", "B"):
            dist = SELF_M if emitter == listener else d_m
            amp = 1.0 if emitter == listener else SELF_M / max(d_m, 0.01)  # 1/r
            for k in range(ROUNDS):
                t = emit[emitter][k] + dist / C - cap_true[listener]
                add_delayed(buf, pr[emitter], t, amp, SR)
                add_reverb(buf, pr[emitter], t, SR, rng)
        recs[listener] = buf

    if mutate:
        mutate(recs, pr, emit, cap_true)

    for role in ("A", "B"):
        sf.write(str(root / f"recording_{role}.wav"),
                 np.clip(recs[role], -1.0, 1.0).astype(np.float32), SR, subtype="FLOAT")
        meta = {
            "role": role,
            "sample_rate": SR,
            "capture_start_ctx_s": -LEAD + ctx_off[role],
            "start_ctx_s": ctx_off[role],
            "scheduled_plays_ctx_s": [
                (k * PERIOD + (B_OFFSET if role == "B" else 0.0)) + ctx_off[role]
                for k in range(ROUNDS)
            ],
            "clock": {"server_offset_ms": 0.0, "rtt_ms_min": 8.0, "samples": 10},
            "context": {"base_latency_s": 0.01, "output_latency_s": lat[role],
                        "state": "running"},
            "track_settings": {"echoCancellation": False, "noiseSuppression": False,
                               "autoGainControl": False, "sampleRate": SR,
                               "channelCount": 1},
            "blocks": {"count": n // 128, "frames": n, "discontinuities": 0,
                       "missing_frames": 0},
            "events": [],
        }
        (root / f"meta_{role}.json").write_text(json.dumps(meta, indent=2))

    (root / "session.json").write_text(json.dumps({
        "session_id": root.name, "created_at": "2026-09-23T00:00:00Z",
        "seed_hex": SEED, "label_cm": d_m * 100, "note": "synthetic",
        "schedule": {"start_server_ms": 0.0, "period_s": PERIOD,
                     "b_offset_s": B_OFFSET, "rounds": ROUNDS,
                     "record_lead_s": LEAD, "record_total_s": TOTAL},
        "roles": {r: {"client_id": r, "sample_rate": SR, "user_agent": "synth"}
                  for r in ("A", "B")},
    }, indent=2))
    return root


def f(v, spec="8.1f"):
    return "     -  " if v is None else format(v, spec)


def main():
    SCRATCH.mkdir(parents=True, exist_ok=True)
    print(f"probe: {probes.PROBE_DURATION_S*1000:.0f} ms, {probes.BAND_HZ[0]}-{probes.BAND_HZ[1]} Hz, "
          f"A/B margin {probes.crosscorr_margin_db(SEED, SR):.1f} dB")
    print(f"self path {SELF_M*100:.0f} cm -> expected flight_cm ~ 100*d - {SELF_M*100:.0f}\n")
    print(f"{'d_true_m':>8} {'expect_cm':>9} {'flight_med':>10} {'spread':>7} "
          f"{'drr_AB':>7} {'drr_BA':>7} {'xfire_min':>9} {'usable':>6} {'decision':>10}")
    for d in (0.05, 0.10, 0.30, 1.00, 3.00):
        rng = np.random.default_rng(int(d * 1000) + 7)
        root = build_session(SCRATCH / f"d{int(d*100):04d}", d, rng)
        res = analyze_session(root)
        s = res.get("summary", {})
        good = [r for r in res.get("rounds", []) if r["usable"]]
        drr_ab = np.median([r["drr_AB_db"] for r in good if r["drr_AB_db"] is not None]) if good else None
        drr_ba = np.median([r["drr_BA_db"] for r in good if r["drr_BA_db"] is not None]) if good else None
        print(f"{d:>8.2f} {100*d - SELF_M*100:>9.1f} {f(s.get('flight_cm_median'),'10.1f')} "
              f"{f(s.get('flight_cm_spread'),'7.1f')} {f(drr_ab,'7.1f')} {f(drr_ba,'7.1f')} "
              f"{f(s.get('crossfire_db_min'),'9.1f')} "
              f"{s.get('usable_rounds')}/{s.get('total_rounds')}".ljust(0)
              + f" {res['decision']['label']:>10}")

    print("\nfailure cases (d = 0.30 m):")

    # (a) 960 zero samples inside round 1 of recording_B
    def mut_zero(recs, pr, emit, cap_true):
        t = emit["A"][1] - cap_true["B"]
        i = int(round(t * SR))
        recs["B"][i - 200 : i - 200 + 960] = 0.0

    rng = np.random.default_rng(101)
    res = analyze_session(build_session(SCRATCH / "fail_zero", 0.30, rng, mut_zero))
    bad = [r["k"] for r in res["rounds"] if not r["usable"]]
    gap = [r["k"] for r in res["rounds"]
           if any(s.startswith("timeline_gap") for s in r["reasons"])]
    ok = (bad == [1] and gap == [1])
    print(f"  [{'PASS' if ok else 'FAIL'}] (a) 20 ms zero run in B round 1: "
          f"unusable rounds={bad}, timeline_gap rounds={gap}, "
          f"flat runs B={len(res['quality']['B']['flat_runs'])}")

    # (b) loud late replica of A's own probe in recording_A
    def mut_replica(recs, pr, emit, cap_true):
        for k in range(ROUNDS):
            t = emit["A"][k] + SELF_M / C - cap_true["A"] + 0.060
            add_delayed(recs["A"], pr["A"], t, 2.0, SR)

    rng = np.random.default_rng(202)
    base = analyze_session(build_session(SCRATCH / "fail_replica_base", 0.30,
                                         np.random.default_rng(202)))
    res = analyze_session(build_session(SCRATCH / "fail_replica", 0.30, rng, mut_replica))
    moved = []
    gaps = []
    for r0, r1 in zip(base["rounds"], res["rounds"]):
        if r0["t_AA_s"] is None or r1["t_AA_s"] is None:
            moved.append(999.0)
            continue
        moved.append(abs(r1["t_AA_s"] - r0["t_AA_s"]) * 1000.0)
        gaps.append(r1["detail"].get("A_at_A", {}).get("gap_ms", 0.0))
    ok = max(moved) < 0.5
    print(f"  [{'PASS' if ok else 'FAIL'}] (b) 2x replica 60 ms late in A: "
          f"max |t_AA shift| = {max(moved):.3f} ms, gap to strongest = "
          f"{np.median(gaps):.1f} ms (expect ~60)")

    # (c) wrong code in B's cross slot
    def mut_wrongcode(recs, pr, emit, cap_true):
        for k in range(ROUNDS):
            t = emit["A"][k] + 0.30 / C - cap_true["B"]
            add_delayed(recs["B"], pr["A"], t, -(SELF_M / 0.30), SR)   # remove A's probe
            add_delayed(recs["B"], pr["B"], t, (SELF_M / 0.30), SR)    # put B's there

    rng = np.random.default_rng(303)
    res = analyze_session(build_session(SCRATCH / "fail_wrongcode", 0.30, rng, mut_wrongcode))
    bad = [r["k"] for r in res["rounds"] if not r["usable"]]
    why = sorted({s for r in res["rounds"] for s in r["reasons"]})
    cf = [r["crossfire_db"].get("A_at_B") for r in res["rounds"]]
    cf = [v for v in cf if v is not None]
    ok = (len(bad) == ROUNDS and res["decision"]["label"] == "UNDECIDED")
    print(f"  [{'PASS' if ok else 'FAIL'}] (c) A's slot in B carries B's code: "
          f"unusable={bad}, reasons={why}, crossfire A_at_B = "
          f"{('%.1f dB' % np.median(cf)) if cf else 'n/a'}, decision={res['decision']['label']}")
    print(f"\nartifacts under {SCRATCH}")


if __name__ == "__main__":
    main()
