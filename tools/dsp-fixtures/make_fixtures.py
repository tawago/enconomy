"""Field recordings -> Kotlin DSP parity fixtures (contract section 10.2).

  research/proximity-echo/.venv/bin/python3 tools/dsp-fixtures/make_fixtures.py [--check]

Writes app/composeApp/src/commonTest/resources/dsp/{<name>.json, nulls.json, index.json}.
Reads research/sound-bound/spikes/melody/fieldtest (fieldprobes for the field bed templates,
session.json/meta/result.json + wavs) read-only.  Expected values come from dsp_ref.py
run on the exact cropped int16 bytes and float32 templates stored in the fixture.
--check: rebuild in memory and diff against the files on disk (exit 1 on change).
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import sys

sys.dont_write_bytecode = True   # never write into research/
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.stats import gumbel_r

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIELD = ROOT / "research/sound-bound/spikes/melody/fieldtest"
SESSIONS = FIELD / "data/sessions"
OUT = ROOT / "app/composeApp/src/commonTest/resources/dsp"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(FIELD))
import dsp_ref as ref  # noqa: E402
import fieldprobes as fp  # noqa: E402  read-only

PROBE = "JBL250"
C_CM_S = 34300.0
NEAR_CM, IMPOSSIBLE_CM = 60.0, -20.0
GLITCH_S = 0.020
PICKS = [  # (name, session prefix, round k, glitch listener)
    ("2dc2eb59_k0", "2dc2eb59", 0, None),
    ("b9e4dd4b_k0", "b9e4dd4b", 0, None),
    ("b2a5f86d_k1", "b2a5f86d", 1, None),
    ("d1ee4fb0_k0", "d1ee4fb0", 0, None),
    ("f3ff0ee8_k0", "f3ff0ee8", 0, None),
    ("glitch_synth", "180ca04b", 0, "B"),
]
N_SCORE_PROBES = 24
NULL_VECTORS = [  # (session_id_hex, emitter, attempt, i, sr); first one also stored in full
    ("00" * 16, "A", 0, 0, 48000),
    ("00" * 16, "B", 0, 0, 48000),
    ("00" * 16, "A", 1, 0, 48000),
    ("00" * 16, "A", 0, 63, 48000),
    ("00" * 16, "A", 0, 0, 44100),
    ("0123456789abcdef" * 2, "B", 1, 7, 44100),
    ("0123456789abcdef" * 2, "A", 0, 5, 96000),
    ("0123456789abcdef" * 2, "B", 0, 1, 36000),
]


def b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def f32(a) -> np.ndarray:
    return np.asarray(a, dtype=np.float64).astype("<f4")


def other(r):
    return "B" if r == "A" else "A"


def to_int16(x: np.ndarray) -> np.ndarray:
    """What an AudioRecord PCM_16 capture would hold: round(x * 32768), clipped."""
    return np.clip(np.round(np.asarray(x, dtype=np.float64) * 32768.0), -32768, 32767).astype(np.int16)


def load_session(prefix):
    d = next(SESSIONS.glob(prefix + "*"))
    s = json.loads((d / "session.json").read_text())
    res = json.loads((d / "result.json").read_text())
    rec = {}
    for L in fp.ROLES:
        meta = json.loads((d / f"meta_{L}.json").read_text())
        info = sf.info(str(d / f"recording_{L}.wav"))
        assert info.channels == 1, info
        x, sr = sf.read(str(d / f"recording_{L}.wav"), dtype="float64")   # web capture: float32 wavs
        rec[L] = {"x": to_int16(x), "sr": int(sr), "meta": meta}
    return d, s, res, rec


def expected_frames(s, rec, L, k):
    """{E: expected onset frame in L's full recording} as fieldanalysis derives it."""
    meta, sr = rec[L]["meta"], rec[L]["sr"]
    cap, start = float(meta["capture_start_ctx_s"]), float(meta["start_ctx_s"])
    own = {(p["probe"], int(p["k"])): float(p["ctx_s"]) for p in meta["plays"]}
    out = {}
    for E in fp.ROLES:
        if E == L:
            exp = own[(PROBE, k)] - cap
        else:
            exp = start + fp.offset_s(s["schedule"], PROBE, E, k) - cap
        out[E] = exp * sr
    return out


def score_probes(corr, w0_seg):
    sc = corr["score"]
    n = len(sc)
    idx = sorted(set(int(round(j * (n - 1) / (N_SCORE_PROBES - 1))) for j in range(N_SCORE_PROBES))
                 | {int(np.argmax(sc))})
    return [[w0_seg + i, float(sc[i])] for i in idx]


def build_pick(name, prefix, k, glitch_at):
    d, s, res, rec = load_session(prefix)
    sid = s["session_id"]
    seed = s["seed_hex"]
    label = float(s["labels"]["label_cm"])
    notes = []
    listeners = {}
    tpl = {}
    for L in fp.ROLES:
        sr = rec[L]["sr"]
        L_n = int(round(ref.CODE_S * sr))
        M = int(round(ref.SEGMENT_MARGIN_S * sr))
        exp_full = expected_frames(s, rec, L, k)
        wins = {E: ref.window(e, sr, len(rec[L]["x"])) for E, e in exp_full.items()}
        lo = max(0, min(w[0] for w in wins.values()) - M)
        hi = min(len(rec[L]["x"]), max(w[1] for w in wins.values()) + L_n + M)
        seg = rec[L]["x"][lo:hi].copy()
        if glitch_at == L:
            mid = int(round((exp_full["A"] + exp_full["B"]) / 2)) - lo
            g = int(round(GLITCH_S * sr))
            seg[mid: mid + g] = 0
            notes.append(f"{L}: {g} zero samples written at segment frame {mid} (between the two arrivals)")
        for E in fp.ROLES:
            if (E, sr) not in tpl:
                tpl[(E, sr)] = f32(fp.template(seed, PROBE, E, sr))
        runs = ref.flat_runs(seg, sr)
        exp = {}
        wjson = {}
        arrivals = {}
        for kind, E in (("self", L), ("partner", other(L))):
            e_seg = exp_full[E] - lo
            c = tpl[(E, sr)].astype(np.float64)
            nulls = [ref.null_template(sid, E, k, i, sr) for i in range(ref.N_NULL)]
            a = ref.measure_arrival(seg, sr, c, nulls, e_seg)
            corr = a.pop("_corr")
            arrivals[kind] = a
            wjson[kind] = {"expected": e_seg, "emitter": E, "template_f32_b64": b64(tpl[(E, sr)])}
            exp[kind] = {**a, "null_maxima": corr["null_maxima"].tolist(),
                         "score_probes": score_probes(corr, corr["w0"])}
            # golden: fieldanalysis arrival of the same (E, L, k)
            fa = next(r for r in res["probes"][PROBE]["rounds"] if r["k"] == k)
            key = f"{E}_at_{L}"
            fa_arr = fa["arrivals"].get(key)
            if fa_arr and a["found"]:
                fa_frame = int(round(fa_arr["t"] * sr)) - lo
                dev = a["frame"] - fa_frame
                bar_dev = a["bar"] / (fa_arr["T"] / 100) - 1
                notes.append(f"{key}: dsp_ref vs fieldanalysis frame {dev:+d}, bar {100 * bar_dev:+.1f}%"
                             + ("" if abs(dev) <= 1 else "  (OUTSIDE +-1: fieldanalysis ppm bank / segment differ)"))
            else:
                notes.append(f"{key}: dsp_ref found={a['found']} fieldanalysis found={bool(fa_arr)}")
        both = [arrivals["self"], arrivals["partner"]]
        L_n = int(round(ref.CODE_S * sr))
        g_lo = min(x["window_lo"] for x in both)
        g_hi = max(x["window_hi"] for x in both) + L_n
        self_hi = arrivals["self"]["window_hi"] + L_n
        exp["flat_runs"] = [list(r) for r in runs]
        exp["glitch_self"] = ref.runs_hit(runs, arrivals["self"]["window_lo"], self_hi)
        exp["glitch"] = ref.runs_hit(runs, g_lo, g_hi)
        exp["half"] = (ref.half(arrivals["self"]["frame"], arrivals["partner"]["frame"], L)
                       if all(x["found"] for x in both) else None)
        listeners[L] = {"sr": sr, "segment_offset": int(lo), "segment_pcm16_b64": b64(seg.astype("<i2")),
                        "windows": wjson, "expect": exp}
    hA, hB = listeners["A"]["expect"]["half"], listeners["B"]["expect"]["half"]
    flight = verdict = None
    if listeners["A"]["expect"]["glitch"] or listeners["B"]["expect"]["glitch"]:
        verdict = "glitch"
    elif hA is not None and hB is not None:
        flight = C_CM_S / 2 * (hA / listeners["A"]["sr"] - hB / listeners["B"]["sr"])
        verdict = ("impossible_flight" if flight < IMPOSSIBLE_CM else
                   "NEAR" if flight < NEAR_CM else "NOT_NEAR")
    fa_round = next(r for r in res["probes"][PROBE]["rounds"] if r["k"] == k)
    notes.append(f"fieldanalysis flight {fa_round['flight_cm']:.2f} cm; dsp_ref flight "
                 + ("-" if flight is None else f"{flight:.2f} cm"))
    return {"name": name, "session": d.name, "round": k, "label_cm": label,
            "session_id_hex": sid, "attempt": k, "listeners": listeners,
            "expect_flight_cm": flight, "expect_verdict": verdict, "notes": notes}


def build_nulls():
    vecs = []
    for j, (sid, E, att, i, sr) in enumerate(NULL_VECTORS):
        x = ref.null_template(sid, E, att, i, sr)
        t = np.arange(len(x))
        v = {"session_id_hex": sid, "emitter": E, "attempt": att, "i": i, "sr": sr, "n": len(x),
             "seed_hex": ref.null_seed(sid, E, att, i).hex(),
             "first8": x[:8].tolist(), "last4": x[-4:].tolist(),
             "sum": float(x.sum()), "sumsq": float((x * x).sum()),
             "wsum": float((x * ((t % 97) - 48)).sum()), "maxabs": float(np.abs(x).max())}
        if j == 0:
            v["full_f64_b64"] = b64(x.astype("<f8"))
        vecs.append(v)
    rng = np.random.default_rng(7)
    g = rng.gumbel(0.05, 0.004, 64)
    return {"vectors": vecs, "gumbel": [{"maxima": g.tolist(), "bar": ref.gumbel_bar(g),
                                         "fit": list(map(float, gumbel_r.fit(g)))}]}


def main():
    check = "--check" in sys.argv
    files = {}
    for name, prefix, k, g in PICKS:
        files[f"{name}.json"] = build_pick(name, prefix, k, g)
    files["nulls.json"] = build_nulls()
    files["index.json"] = {"fixtures": [p[0] for p in PICKS]}
    changed = 0
    total = 0
    for fn, obj in files.items():
        txt = json.dumps(obj, indent=None, separators=(",", ":"), allow_nan=False) + "\n"
        total += len(txt)
        p = OUT / fn
        if check:
            if not p.exists() or p.read_text() != txt:
                print("changed:", fn)
                changed += 1
        else:
            OUT.mkdir(parents=True, exist_ok=True)
            p.write_text(txt)
        if fn not in ("nulls.json", "index.json"):
            e = {L: obj["listeners"][L]["expect"] for L in fp.ROLES}
            print(f"{fn:20s} {len(txt) / 1e6:.2f} MB  verdict {obj['expect_verdict']}  flight "
                  f"{obj['expect_flight_cm'] if obj['expect_flight_cm'] is None else round(obj['expect_flight_cm'], 2)}  "
                  f"half A {e['A']['half']} B {e['B']['half']}")
            for n in obj["notes"]:
                print("   ", n)
    print(f"total {total / 1e6:.2f} MB -> {OUT}")
    assert total < 5e6, "fixtures over 5 MB"
    sys.exit(1 if changed else 0)


if __name__ == "__main__":
    main()
