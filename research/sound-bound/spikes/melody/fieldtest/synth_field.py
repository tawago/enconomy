"""Two-phone simulation of one whole fieldtest session.  CONTRACT.md section 9.

  python synth_field.py --dist-cm 30 --room small --noise quiet [--ppm-a 20 --ppm-b -30]
                        [--slip B:9.0] [--sr-a 48000 --sr-b 44100] [--seed hex] [--out data/synth]
  python synth_field.py --walk      # 0/30/100/200 cm x small/big, quiet, random ppm; prints compare table

Writes session.json, meta_A/B.json, recording_A/B.wav exactly as a real run, then
runs fieldanalysis.analyze_session on it.

Room model (differs from bakeoff.rir on purpose, after the verifier's critique):
early reflections fall with their own path length.  A reflection arriving d s
after the direct sound travelled r_direct + c*d metres and has amplitude
early_coef * (1 m / path); `early` is that coefficient range (the amplitude a
reflection would have at a 1 m path, with the self direct path at 12 cm = 1.0).
So at 2 m the direct sound is no longer beaten by fixed-level reflections.
The diffuse tail keeps a fixed energy per room (diffuse field does not depend
on distance), as in bakeoff.

STRESS CASE, NOT A FIELD PREDICTION.  tail = 1.2 puts the critical distance at
0.12 / 1.2 = 10 cm in both rooms (DRR -1.6 dB on the 12 cm self path, -9.5 dB at
30 cm, -26 dB at 200 cm).  Sabine gives ~0.5 m for a small room at RT60 0.5 s.
So 200 cm here is much harsher than a real room: the direct sound sits near the
null bar and a diffuse-tail peak can be 2x louder.  Use the sim to check wiring,
drift, slips and the decision logic; do not rank probes by its 200 cm margins.
(Kept as the contract pins it: calibrated to real N30 self-path scores.)

Choices not pinned by the contract:
  - Early reflection delays: small 0.7-8 ms, big 1-15 ms after the direct sound.
  - ppm defaults: random within +-50 when not given.  Mic gain 0.3 (self-path
    RMS ~0.04 FS); the WAV is float, never clipped by the simulator.
  - Scene randomness (latencies, rooms, devices, noise) is seeded from the
    session seed, so a seed reproduces a session.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.fft import next_fast_len
from scipy.signal import butter, fftconvolve, resample, sosfilt

HERE = Path(__file__).resolve().parent
MELODY = HERE.parent
for _p in (str(HERE), str(MELODY), str(HERE.parents[2])):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import fieldprobes as fp  # noqa: E402
import melody_probes as mp  # noqa: E402  read-only: speaker()

C_M_S = 343.0
SELF_M = 0.12                 # speaker -> own mic
TOUCH_M = 0.02                # label 0 cm = touching, 2 cm between speaker and partner mic
LAT_S = (0.02, 0.08)          # per-phone output and input latency
RESID_S = 0.005               # clock-sync residual, +-
PPM_MAX = 50.0                # default random sample-clock error, +-
COLOR_DB = 6.0                # unknown speaker / mic EQ ripple per phone
MIC_GAIN = 0.3                # self-path direct lands ~0.04 RMS
SLIP_S = 0.020                # Android dropped block
ROOMS = {
    "small": {"rt60": 0.5, "tail": 1.2, "early": (0.05, 0.12), "early_delay_s": (0.0007, 0.008)},
    "big":   {"rt60": 1.0, "tail": 1.2, "early": (0.02, 0.06), "early_delay_s": (0.001, 0.015)},
}
NOISE_DB = {"quiet": -40.0, "music": -20.0, "talk": -20.0}   # re self-path direct RMS


def _rng(seed_hex, *parts) -> np.random.Generator:
    d = hashlib.sha256("|".join(["synth", seed_hex, *map(str, parts)]).encode()).digest()
    return np.random.default_rng(int.from_bytes(d[:16], "big"))


# ------------------------------------------------------------ copied from bakeoff.py, sr-parametric
def add_delayed(buf, sig, t_s, sr):
    """Add sig into buf at fractional time t_s via an FFT phase ramp."""
    n0 = int(np.floor(t_s * sr))
    frac = t_s * sr - n0
    m = next_fast_len(len(sig) + 64)
    spec = np.fft.rfft(sig, m)
    spec *= np.exp(-2j * np.pi * np.arange(len(spec)) * frac / m)
    y = np.fft.irfft(spec, m)
    a, b = max(n0, 0), min(len(buf), n0 + m)
    if b > a:
        buf[a:b] += y[a - n0 : b - n0]


def warp(x, eps):
    """Time-stretch by (1+eps), band-limited."""
    if eps == 0:
        return x
    big = next_fast_len(len(x) * 8)
    m = int(round(eps * big))
    if m == 0:
        return x
    pad = np.zeros(big)
    pad[: len(x)] = x
    y = resample(pad, big + m)
    return y[: len(x) + max(m, 0) + 64]


def color_fir(rng, sr):
    """Smooth random EQ +-COLOR_DB, linear phase, fixed length (same delay on every path)."""
    nfft = 512
    f = np.fft.rfftfreq(nfft, 1 / sr)
    knots = np.geomspace(200, 20000, 12)
    db = np.interp(np.log(np.maximum(f, 1)), np.log(knots), rng.uniform(-COLOR_DB, COLOR_DB, 12))
    h = np.fft.fftshift(np.fft.irfft(10 ** (db / 20), nfft))[1:] * np.hanning(nfft - 1)
    return h / np.sum(h)


def rir(rng, room, r_direct, sr):
    """Direct 1/r tap, four early reflections that fall with their path length, diffuse tail."""
    rt60 = room["rt60"]
    n = int(1.5 * rt60 * sr)
    h = np.zeros(n)
    h[0] = SELF_M / r_direct
    for _ in range(4):
        d = rng.uniform(*room["early_delay_s"])
        path = r_direct + d * C_M_S
        h[int(round(d * sr))] += rng.uniform(*room["early"]) / path * rng.choice([-1, 1])
    t = np.arange(n) / sr
    tt = np.clip(t - 0.003, 0, None)
    tail = rng.normal(0, 1, n) * 10 ** (-3.0 * t / rt60) * (1 - np.exp(-tt / 0.010))
    tail *= room["tail"] / np.sqrt(np.sum(tail ** 2))
    return h + tail


# ------------------------------------------------------------ noise
def _noise(kind, n, sr, rng, ref_rms):
    lvl = ref_rms * 10 ** (NOISE_DB[kind] / 20)
    t = np.arange(n) / sr
    if kind == "quiet":
        x = rng.normal(0, 1, n)
    elif kind == "music":
        x = np.zeros(n)
        seg = int(0.4 * sr)
        for _ in range(6):   # six voices, a new note every 0.4 s, phase-continuous
            f = np.exp(rng.uniform(np.log(200), np.log(5000), n // seg + 2))
            fi = np.repeat(f, seg)[:n]
            ph = 2 * np.pi * np.cumsum(fi) / sr
            env = 0.6 + 0.4 * np.cos(2 * np.pi * (t % 0.4) / 0.4)
            x += env * (np.sin(ph) + 0.3 * np.sin(2 * ph))
    elif kind == "talk":
        w = rng.normal(0, 1, n)
        x = sosfilt(butter(2, (100, 4000), "bandpass", fs=sr, output="sos"), w)
        x = sosfilt(butter(1, 500, "lowpass", fs=sr, output="sos"), x) * 0.7 + x * 0.3
        syl = np.clip(np.sin(2 * np.pi * 4.0 * t + rng.uniform(0, 6.28)), 0, None) ** 2
        pauses = np.repeat(rng.random(n // sr + 2) < 0.75, sr)[:n]
        x *= syl * pauses
    else:
        raise ValueError(kind)
    return x * lvl / max(np.sqrt(np.mean(x * x)), 1e-12)


# ------------------------------------------------------------ session
def simulate(dist_cm, room, noise, ppm_a=None, ppm_b=None, slip=None, sr_a=48000, sr_b=48000,
             seed=None, out=None, gain_db=None, analyze=True, quiet_print=False):
    seed = seed or secrets.token_bytes(32).hex()
    sched = json.loads(json.dumps(fp.SCHEDULE))
    gain_db = {p: float((gain_db or {}).get(p, 0.0)) for p in fp.PROBES}
    rng = _rng(seed, "scene")
    srs = {"A": int(sr_a), "B": int(sr_b)}
    ppm = {"A": ppm_a if ppm_a is not None else float(rng.uniform(-PPM_MAX, PPM_MAX)),
           "B": ppm_b if ppm_b is not None else float(rng.uniform(-PPM_MAX, PPM_MAX))}
    lat_out = {r: float(rng.uniform(*LAT_S)) for r in fp.ROLES}
    lat_in = {r: float(rng.uniform(*LAT_S)) for r in fp.ROLES}
    resid = {r: float(rng.uniform(-RESID_S, RESID_S)) for r in fp.ROLES}
    dist_m = TOUCH_M if dist_cm <= 0 else dist_cm / 100.0
    lead = sched["lead_s"]
    sid = f"synth-{room}-{int(round(dist_cm))}cm-{secrets.token_hex(4)}"
    out_dir = Path(out or HERE / "data" / "synth") / sid
    out_dir.mkdir(parents=True, exist_ok=True)

    recs, metas, renders = {}, {}, {r: {} for r in fp.ROLES}
    for L in fp.ROLES:
        sr = srs[L]
        n = int(round(sched["record_total_s"] * sr))
        buf = np.zeros(n)
        mic = color_fir(_rng(seed, "mic", L, sr), sr)
        for E in fp.ROLES:
            spk = color_fir(_rng(seed, "spk", E, sr), sr)
            r = SELF_M if E == L else dist_m
            h = rir(_rng(seed, "rir", E, L), ROOMS[room], r, sr)
            path = fftconvolve(h, np.convolve(spk, mic))
            eps = 0.0 if E == L else (1 + ppm[L] * 1e-6) / (1 + ppm[E] * 1e-6) - 1
            cache = {}
            for pl in fp.plays(sched, E):
                p = pl["probe"]
                if p not in cache:
                    code, info = fp.render(seed, p, E, sr, gain_db[p])
                    if E == L:
                        renders[E][p] = info
                    cache[p] = fftconvolve(warp(mp.speaker(code.astype(np.float64), sr), eps), path)
                t = (lead + pl["offset_s"] + lat_out[E] + lat_in[L] + resid[E] - resid[L]
                     + r / C_M_S) * (1 + ppm[L] * 1e-6)
                add_delayed(buf, cache[p], t, sr)
        # self-path direct RMS reference = own N1s code through speaker + colour
        ref = mp.speaker(fp.generate(seed, "N1s", L, sr).astype(np.float64), sr)
        ref = np.convolve(ref, np.convolve(color_fir(_rng(seed, "spk", L, sr), sr), mic))
        ref_rms = float(np.sqrt(np.mean(ref ** 2)))
        buf += _noise(noise, n, sr, _rng(seed, "noise", L), ref_rms)
        if noise != "quiet":   # the mic self-noise floor is always there
            buf += _noise("quiet", n, sr, _rng(seed, "floor", L), ref_rms)
        buf *= MIC_GAIN
        if slip and slip[0] == L:
            i = int(round(slip[1] * sr))
            buf = np.concatenate([buf[:i], np.zeros(int(round(SLIP_S * sr))), buf[i:]])[:n]
        recs[L] = buf.astype(np.float32)

        start_ctx = float(2.0 + rng.uniform(0, 1))
        cap = start_ctx - lead
        metas[L] = {
            "role": L, "sample_rate": sr, "capture_start_ctx_s": cap, "capture_frames": n,
            "start_ctx_s": start_ctx,
            "plays": [{"probe": d["probe"], "k": d["k"], "ctx_s": start_ctx + d["offset_s"],
                       "clamped": False} for d in fp.plays(sched, L)],
            "clock": {"server_offset_ms": resid[L] * 1000, "rtt_ms_min": 0.0, "samples": 10},
            "context": {"base_latency_s": None, "output_latency_s": None, "state": "running"},
            "track_settings": {"echoCancellation": False, "noiseSuppression": False,
                               "autoGainControl": False, "sampleRate": sr, "channelCount": 1},
            "blocks": {"count": n // 128, "frames": n, "discontinuities": 0, "missing_frames": 0},
            "probes_loaded": {p: {"n": len(fp.generate(seed, p, L, sr)), "sr": sr} for p in sched["order"]},
            "user_agent": "synth_field.py", "events": [],
        }

    params = {"dist_cm": dist_cm, "dist_m": dist_m, "room": room, "room_model": ROOMS[room],
              "noise": noise, "ppm": ppm, "lat_out_s": lat_out, "lat_in_s": lat_in,
              "resid_s": resid, "slip": list(slip) if slip else None, "sr": srs,
              "self_m": SELF_M, "mic_gain": MIC_GAIN,
              "truth_flight_cm": 100 * (dist_m - SELF_M)}
    session = {
        "version": fp.VERSION, "session_id": sid,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "seed_hex": seed,
        "labels": {"label_cm": dist_cm, "room": room if room in ("small", "big") else "other",
                   "pose": "table", "noise": noise, "note": "synth"},
        "schedule": {**sched, "start_server_ms": None},
        "gain_db": gain_db,
        "roles": {r: {"client_id": f"synth-{r}", "sample_rate": srs[r], "user_agent": "synth_field.py",
                      "render": renders[r]} for r in fp.ROLES},
        "synthetic": params,
    }
    (out_dir / "session.json").write_text(json.dumps(session, indent=1))
    for L in fp.ROLES:
        (out_dir / f"meta_{L}.json").write_text(json.dumps(metas[L], indent=1))
        sf.write(str(out_dir / f"recording_{L}.wav"), recs[L], srs[L], subtype="FLOAT")
    res = None
    if analyze:
        import fieldanalysis
        res = fieldanalysis.analyze_session(out_dir)
        if not quiet_print:
            print(f"truth flight {params['truth_flight_cm']:.1f} cm, ppm A {ppm['A']:+.1f} B {ppm['B']:+.1f}")
            fieldanalysis.print_result(res)
    return out_dir, res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist-cm", type=float, default=30.0)
    ap.add_argument("--room", default="small", choices=sorted(ROOMS))
    ap.add_argument("--noise", default="quiet", choices=sorted(NOISE_DB))
    ap.add_argument("--ppm-a", type=float)
    ap.add_argument("--ppm-b", type=float)
    ap.add_argument("--slip", help="L:t  insert 20 ms of zeros at t s in L's recording")
    ap.add_argument("--sr-a", type=int, default=48000)
    ap.add_argument("--sr-b", type=int, default=48000)
    ap.add_argument("--seed")
    ap.add_argument("--out")
    ap.add_argument("--walk", action="store_true")
    a = ap.parse_args(argv)
    if a.walk:
        import compare
        dirs = []
        for room in ("small", "big"):
            for d in (0, 30, 100, 200):
                od, res = simulate(d, room, "quiet", out=a.out, quiet_print=True)
                print(f"{od.name}: runtime {res.get('runtime_s', 0):.1f} s", flush=True)
                dirs.append(od)
        print(compare.table(compare.load(dirs)))
        return 0
    slip = None
    if a.slip:
        role, t = a.slip.split(":")
        slip = (role.strip().upper(), float(t))
    _, res = simulate(a.dist_cm, a.room, a.noise, a.ppm_a, a.ppm_b, slip, a.sr_a, a.sr_b,
                      a.seed, a.out)
    return 0 if res and res.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
