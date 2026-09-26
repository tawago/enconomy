"""Reviewer attacks on option A (JBL250) against the real fixtures. Writes circuit inputs only;
proving/verification runs separately (Vega binary / circom witness) under ../tools/heavy.sh.

  $PY review/attacks.py scan-self            # A: later self-arrival candidates per far session
  $PY review/attacks.py self <sess8> <key> <j> out.json      # A: exact-mode input, sub-window after the true arrival
  $PY review/attacks.py noise <sess8> <fc> <bw> <rms> [out.json] # B: narrowband interference, cand-mode early cross
  $PY review/attacks.py xrange in.json out.json               # C: one sample out of int16, curve recomputed
  $PY review/attacks.py swap                                  # D: role swap on the signed fixtures
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfiltfilt

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import twin  # noqa: E402

sys.path.insert(0, str(twin.FIELD))
import fieldanalysis as fa  # noqa: E402

HM = (twin.M - 1) // 2
KP = 512
CM_PER_SAMPLE = fa.SPEED_OF_SOUND_CM_S / 2 / twin.SR


def cands(tw, K):
    """All lags the circuit accepts as candidates (score >= T0, local max, half rule inside the window)."""
    e = np.asarray(tw["env2"], dtype=np.float64)
    out = []
    for j in np.nonzero(tw["lm"] & tw["ok"])[0]:
        if 4 * e[j] >= e[j: j + twin.LOOK + 1].max():
            out.append(int(j))
    return out


def make_input(xs, cI, cQ, Kp, mode, arr, h, g, nhr=2):
    """Circuit input in the same format as twin.dump, for a chosen arrival in the sub-window."""
    sub = twin.twin_arrival(xs, cI, cQ, h, g, Kp, twin.T0, full=True)
    env2 = [int(v) for v in sub["env2"]]
    E_ = [int(v) for v in sub["E"]]
    B, cn2 = sub["B"], sub["cn2"]
    assert Kp - arr > twin.LOOK
    assert sub["lm"][arr] and sub["ok"][arr] and 4 * env2[arr] >= max(env2[arr: arr + twin.LOOK + 1]), "not a candidate"
    inp = {"cI": [int(v) for v in cI], "cQ": [int(v) for v in cQ], "x": [int(v) for v in xs],
           "I": [int(v) for v in sub["I"]], "Q": [int(v) for v in sub["Q"]],
           "arr": arr, "sel": [1 if k <= arr else 0 for k in range(Kp + 1)]}
    if mode == "exact":
        assert sub["arr"] == arr, ("not the first candidate of the sub-window", sub["arr"], arr)
        rsn, hrw = [], []
        for j in range(Kp):
            if j >= arr:
                rsn.append([0, 0, 0])
            elif env2[j] * B < E_[j] * cn2:
                rsn.append([1, 0, 0])
            elif j + 1 < Kp and env2[j] <= env2[j + 1]:
                rsn.append([0, 1, 0])
            elif j == 0 or env2[j] < env2[j - 1]:
                rsn.append([0, 0, 1])
            else:
                m = max(range(j, min(j + twin.LOOK + 1, Kp)), key=lambda t: env2[t])
                assert 4 * env2[j] < env2[m]
                rsn.append([0, 0, 0])
                hrw.append((j, m))
        assert len(hrw) <= nhr
        inp["rsn"] = rsn
        inp["hr_f"] = [[int(w < len(hrw) and k == hrw[w][0]) for k in range(Kp)] for w in range(nhr)]
        inp["hr_g"] = [[int(w < len(hrw) and k == hrw[w][1]) for k in range(Kp)] for w in range(nhr)]
    meta = {"fir": [int(v) for v in h], "B": B, "cn2": cn2, "Kp": Kp, "arr": arr,
            "score_at_arr": float(sub["score"][arr])}
    return inp, meta


def write(out, inp, meta):
    Path(out).write_text(json.dumps(inp))
    Path(out).with_suffix(".meta.json").write_text(json.dumps(meta, indent=1))


def load_key(sess8, key, x_override=None):
    d = next(twin.SESS.glob(sess8 + "*"))
    session, res, rec = twin.load(d)
    wins = twin.windows(session, rec)
    E, Lr = key.split("_at_")
    lo, hi = wins[(E, Lr)]
    cI, cQ = twin.templates(session["seed_hex"], E)
    xf = rec[Lr]["x"] if x_override is None else x_override
    return d, session, res, rec, lo, hi - lo, cI, cQ, E, Lr, xf


def flights():
    return {json.loads(l)["session"]: json.loads(l) for l in open(HERE.parent / "build/twin_all.jsonl")
            if "flight_twin" in json.loads(l)}


def scan_self():
    """A: after the true self arrival, which later lags are circuit candidates? A sub-window that
    starts after the true arrival makes 'exact' prove that later lag. Later self = smaller flight."""
    h, g = twin.fir()
    fl = flights()
    for s8, row in fl.items():
        f = row["flight_twin"]
        for key in ("A_at_A", "B_at_B"):
            d, session, res, rec, lo, K, cI, cQ, E, Lr, xf = load_key(s8, key)
            x = twin.q16(xf)
            tw = twin.twin_arrival(x[lo - HM: lo + K + twin.L - 1 + HM], cI, cQ, h, g, K)
            i = tw["arr"]
            cs = [j for j in cands(tw, K) if j > i]
            near = [(j, j - i, f - CM_PER_SAMPLE * (j - i)) for j in cs if -20 < f - CM_PER_SAMPLE * (j - i) < 60]
            print(json.dumps({"session": s8, "label": session["labels"].get("label_cm"), "key": key,
                              "flight": round(f, 1), "arr": i, "later_cands_first5": [(j, j - i) for j in cs[:5]],
                              "n_later": len(cs), "near_making": [(j, dl, round(ff, 1)) for j, dl, ff in near[:4]]}))


def self_attack(s8, key, j, out):
    h, g = twin.fir()
    d, session, res, rec, lo, K, cI, cQ, E, Lr, xf = load_key(s8, key)
    x = twin.q16(xf)
    tw = twin.twin_arrival(x[lo - HM: lo + K + twin.L - 1 + HM], cI, cQ, h, g, K)
    i = tw["arr"]
    prev = max([c for c in cands(tw, K) if c < j] + [i])
    s0 = max(prev + 1, j - 256)
    xs = x[lo + s0 - HM: lo + s0 + KP + twin.L - 1 + HM]
    inp, meta = make_input(xs, cI, cQ, KP, "exact", j - s0, h, g)
    f = flights()[s8]["flight_twin"]
    meta.update({"attack": "self window starts after the true self arrival", "session": d.name, "key": key,
                 "true_arr_abs": lo + i, "fake_arr_abs": lo + j, "shift_samples": j - i,
                 "flight_honest_cm": f, "flight_claimed_cm": f - CM_PER_SAMPLE * (j - i)})
    write(out, inp, meta)
    print(json.dumps({k: v for k, v in meta.items() if k != "fir"}))


def null_bar(xw, E, h, g, K, n=64, seed0=0):
    """Live-bar stand-in: max score of n random codes (same role) over the window, Gumbel T (fieldanalysis)."""
    y = np.convolve(xw.astype(np.float64), h[::-1].astype(np.float64), mode="valid")
    cs = np.concatenate([[0.0], np.cumsum(y * y)])
    En = cs[twin.L: twin.L + K] - cs[:K]
    xc = xw[HM:].astype(np.float64)
    nfft = 1 << int(np.ceil(np.log2(len(xc) + twin.L)))
    X = np.fft.rfft(xc, nfft)
    mx = []
    rng = np.random.default_rng(seed0)
    for _ in range(n):
        sh = rng.bytes(16).hex()
        cI, cQ = twin.templates(sh, E)
        cn2 = float(np.dot(cI, cI))
        I = np.fft.irfft(X * np.conj(np.fft.rfft(cI.astype(float), nfft)), nfft)[:K]
        Q = np.fft.irfft(X * np.conj(np.fft.rfft(cQ.astype(float), nfft)), nfft)[:K]
        sc = np.sqrt((I * I + Q * Q) * g * g / (En * cn2))
        mx.append(float(sc.max()))
    T, mode = fa._gumbel_T(np.asarray(mx))
    return T, mx


def noise_attack(s8, fc, bw, rms, out=None, key="B_at_A", seed=1):
    """B: the cheater plays narrowband in-band noise near its own mic (simulated by digital addition).
    Chance peaks rise above the fixed floor T0; cand mode then accepts any of them as the cross arrival.
    Earlier cross = smaller flight."""
    h, g = twin.fir()
    d, session, res, rec, lo, K, cI, cQ, E, Lr, xf = load_key(s8, key)
    rng = np.random.default_rng(seed)
    sos = butter(6, [fc - bw / 2, fc + bw / 2], btype="bandpass", fs=twin.SR, output="sos")
    a, b = lo - HM - 4800, lo + K + twin.L + HM + 4800
    nz = sosfiltfilt(sos, rng.standard_normal(b - a))
    nz *= rms / nz.std()
    xf2 = np.array(xf, dtype=np.float64)
    xf2[a:b] += nz
    x = twin.q16(xf2)
    xw = x[lo - HM: lo + K + twin.L - 1 + HM]
    tw = twin.twin_arrival(xw, cI, cQ, h, g, K)
    x0 = twin.q16(xf)
    tw0 = twin.twin_arrival(x0[lo - HM: lo + K + twin.L - 1 + HM], cI, cQ, h, g, K)
    i0 = tw0["arr"]
    cs = cands(tw, K)
    f = flights()[s8]["flight_twin"]
    early = [(j, i0 - j, f - CM_PER_SAMPLE * (i0 - j), float(tw["score"][j])) for j in cs if j < i0]
    near = [t for t in early if -20 < t[2] < 60]
    T, mx = null_bar(xw, E, h, g, K)
    info = {"session": d.name[:8], "key": key, "fc": fc, "bw": bw, "rms": rms, "flight_honest": round(f, 1),
            "true_arr": i0, "twin_arr_noisy_T0": tw["arr"],
            "true_score_noisy": round(100 * float(tw["score"][i0]), 2),
            "n_T0_cands_before_true": len(early), "n_near_making": len(near),
            "near_making_first3": [(j, dl, round(ff, 1), round(100 * s, 2)) for j, dl, ff, s in near[:3]],
            "live_bar_T_pct": round(100 * T, 2), "null_max_median_pct": round(100 * float(np.median(mx)), 2),
            "null_max_max_pct": round(100 * float(np.max(mx)), 2)}
    print(json.dumps(info))
    if out and near:
        j = near[0][0]
        s0 = j - 256
        xs = x[lo + s0 - HM: lo + s0 + KP + twin.L - 1 + HM]
        inp, meta = make_input(xs, cI, cQ, KP, "cand", j - s0, h, g)
        meta.update(info)
        meta.update({"attack": "narrowband interference, early cross arrival in cand mode",
                     "fake_arr_abs": lo + j, "true_arr_abs": lo + i0, "shift_samples": j - i0,
                     "flight_claimed_cm": f - CM_PER_SAMPLE * (i0 - j)})
        write(out, inp, meta)
        print("wrote", out, "arr", j - s0, "score", meta["score_at_arr"])


def xrange_attack(inp_path, out):
    """C: set one sample outside int16, recompute the curve exactly so Freivalds and the rule still hold."""
    base = json.loads(Path(inp_path).read_text())
    meta = json.loads(Path(inp_path).with_suffix(".meta.json").read_text())
    h, g = twin.fir()
    xs = np.asarray(base["x"], dtype=np.int64)
    cI, cQ = np.asarray(base["cI"]), np.asarray(base["cQ"])
    Kp = len(base["I"])
    xs[HM + 20] = 100_000        # 17 bits, not an int16 sample; before the arrival
    mode = "exact" if "rsn" in base else "cand"
    inp, m2 = make_input(xs, cI, cQ, Kp, mode, base["arr"], h, g)
    m2["attack"] = "x[31+20] = 100000 (outside int16), curve recomputed"
    write(out, inp, m2)
    print(json.dumps({k: v for k, v in m2.items() if k != "fir"}))


def swap():
    """D: combine the signed fixture halves with the roles swapped. flight -> -flight."""
    for f in sorted((HERE.parents[1] / "fixtures").glob("*.json")):
        fx = json.loads(f.read_text())
        hA, hB = fx["roles"]["A"]["half_samples"], fx["roles"]["B"]["half_samples"]
        fl = fa.SPEED_OF_SOUND_CM_S / 2 * (hA - hB) / twin.SR
        sw = fa.SPEED_OF_SOUND_CM_S / 2 * (hB - hA) / twin.SR
        ok = -20 < sw < 60
        print(f"{fx['session_id'][:8]} label {fx['label_cm']:5.0f} flight {fl:7.1f} {fx['verdict']:8s} "
              f"swapped {sw:7.1f} -> {'NEAR (passes)' if ok else 'rejected'}"
              f"{'  <-- was NOT_NEAR' if ok and fx['verdict'] != 'NEAR' else ''}")


def trunc_attack(s8, key, out=None):
    """E: cand mode on a prover-positioned K=512 sub-window. A T0-passing local max that the receiver
    rejects by the half rule becomes a 'candidate' if the sub-window ends before its veto lag: the
    circuit does not enforce arr <= K-1-LOOK. Earlier cross = smaller flight."""
    h, g = twin.fir()
    d, session, res, rec, lo, K, cI, cQ, E, Lr, xf = load_key(s8, key)
    x = twin.q16(xf)
    tw = twin.twin_arrival(x[lo - HM: lo + K + twin.L - 1 + HM], cI, cQ, h, g, K)
    i = tw["arr"]
    e = np.asarray(tw["env2"], dtype=np.float64)
    f = flights()[s8]["flight_twin"]
    sign = 1 if Lr == E else -1          # self: later -> smaller flight; cross: earlier -> smaller flight
    rej = [int(j) for j in np.nonzero(tw["lm"] & tw["ok"])[0] if j < i]
    for j in rej:
        veto = next(m for m in range(j, j + twin.LOOK + 1) if 4 * e[j] < e[m])
        fl = f - CM_PER_SAMPLE * (i - j)
        print(json.dumps({"session": s8, "key": key, "true_arr": i, "rejected_peak": j, "first_veto": veto,
                          "shift": j - i, "score": round(100 * float(tw["score"][j]), 2),
                          "flight_honest": round(f, 1), "flight_claimed": round(fl, 1)}))
        if out and -20 < fl < 60:
            s0 = veto - KP                    # sub-window ends at veto - 1: the veto is cut off
            xs = x[lo + s0 - HM: lo + s0 + KP + twin.L - 1 + HM]
            inp, meta = make_input_trunc(xs, cI, cQ, KP, j - s0, h, g)
            meta.update({"attack": "cand sub-window ends before the half-rule veto", "session": d.name,
                         "key": key, "true_arr_abs": lo + i, "fake_arr_abs": lo + j,
                         "flight_honest_cm": f, "flight_claimed_cm": fl})
            write(out, inp, meta)
            print("wrote", out)
            return


def make_input_trunc(xs, cI, cQ, Kp, arr, h, g):
    sub = twin.twin_arrival(xs, cI, cQ, h, g, Kp, twin.T0, full=True)
    env2 = [int(v) for v in sub["env2"]]
    assert sub["lm"][arr] and sub["ok"][arr] and 4 * env2[arr] >= max(env2[arr:]), "not a truncated candidate"
    inp = {"cI": [int(v) for v in cI], "cQ": [int(v) for v in cQ], "x": [int(v) for v in xs],
           "I": [int(v) for v in sub["I"]], "Q": [int(v) for v in sub["Q"]],
           "arr": arr, "sel": [1 if k <= arr else 0 for k in range(Kp + 1)]}
    return inp, {"fir": [int(v) for v in h], "B": sub["B"], "cn2": sub["cn2"], "Kp": Kp, "arr": arr,
                 "score_at_arr": float(sub["score"][arr])}


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "scan-self":
        scan_self()
    elif cmd == "self":
        self_attack(sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5])
    elif cmd == "noise":
        noise_attack(sys.argv[2], float(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5]),
                     sys.argv[6] if len(sys.argv) > 6 else None)
    elif cmd == "xrange":
        xrange_attack(sys.argv[2], sys.argv[3])
    elif cmd == "swap":
        swap()
    elif cmd == "trunc":
        trunc_attack(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None)
