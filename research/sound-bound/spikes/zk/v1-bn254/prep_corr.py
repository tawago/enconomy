"""Build circuit input for corr_bench from a real field recording, plus the
exact integer answers the circuit must reproduce.

Session c72ce4b6 (30 cm, big room), JB round 0, B's code heard at A (t=13.78775 s).
Usage: python prep_corr.py L K out.json
"""
import json
import sys
from pathlib import Path

import numpy as np
from scipy.signal import hilbert

FIELD = Path(__file__).resolve().parents[2] / "melody" / "fieldtest"
sys.path.insert(0, str(FIELD))
import fieldprobes as fp          # noqa: E402
from fieldanalysis import _read_wav  # noqa: E402

SESSION = next((FIELD / "data" / "sessions").glob("c72ce4b6*"))
T_ARRIVAL = 13.78775   # result.json: JB round 0, B_at_A


def q16(v, scale):
    return np.clip(np.round(v * scale), -32768, 32767).astype(np.int64)


def main(L, K, out):
    seed = json.loads((SESSION / "session.json").read_text())["seed_hex"]
    x, sr = _read_wav(SESSION / "recording_A.wav")
    c = fp.template(seed, "JB", "B", sr)
    a = hilbert(c)
    tI, tQ = a.real[:L], a.imag[:L]
    s = 32767 / max(np.abs(tI).max(), np.abs(tQ).max())
    tI, tQ = q16(tI, s), q16(tQ, s)

    n0 = int(round(T_ARRIVAL * sr))
    lo = n0 - K // 2
    seg = x[lo: lo + L + K - 1]
    rec = q16(seg, 32767 / max(np.abs(seg).max(), 1e-12))

    I = [int(np.dot(rec[k:k + L], tI)) for k in range(K)]
    Q = [int(np.dot(rec[k:k + L], tQ)) for k in range(K)]
    E = [int(np.dot(rec[k:k + L], rec[k:k + L])) for k in range(K)]
    env2 = [i * i + q * q for i, q in zip(I, Q)]
    cc = int(np.dot(tI, tI))
    score = [(e2 / (e * cc)) ** 0.5 for e2, e in zip(env2, E)]

    Path(out).write_text(json.dumps({"rec": rec.tolist(), "tI": tI.tolist(), "tQ": tQ.tolist()}))
    Path(out).with_suffix(".expect.json").write_text(json.dumps(
        {"session": SESSION.name, "sr": sr, "lag0_sample": lo, "I": I, "Q": Q, "E": E,
         "env2": env2, "score": score}, indent=1))
    print(f"sr={sr} lags {lo}..{lo + K - 1} score={['%.3f' % v for v in score]}")


if __name__ == "__main__":
    main(int(sys.argv[1]), int(sys.argv[2]), sys.argv[3])
