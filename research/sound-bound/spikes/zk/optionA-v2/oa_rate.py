"""Per-sample-rate receiver of option A on POPT v2 (docs/pop-transcript-v2.md).

The optionA-v2 twin (optionA-jbl250/twin.py) is fixed at 48 kHz. Each phone signs its own sample rate
(contract §4.2), and the per-phone circuit is compiled for one rate, so everything rate-dependent is a
function of sr here. At sr = 48,000 every value equals the 48 kHz twin's (checked in selftest()).

  L      = round(CODE_S * sr)                  template length (12,000 at 48 kHz, 11,025 at 44.1 kHz)
  h, g   = 63-tap 8-bit band-pass FIR (2-18 kHz, Kaiser 6) designed at sr, and its rms passband gain
  B      = round(g^2 / T0^2), T0 = 9 %          score >= T0  <=>  env2 * B >= E * cn2
  cI, cQ = masked bed template at sr and its Hilbert pair, 8-bit, common scale
  WPRE, WPOST = round(0.150 sr), round(0.250 sr)  partner window around p_partner (contract §4.4)
  DELTA  = DELTA_MS * sr // 1000                 self window half-width (2 ms: 96 / 88 frames)
Rate-independent: T0, M = 63 taps (HM = 31), the 1,024-sample leaf, the Poseidon7 parameters.

Templates and code_commit are what the verifier derives from the revealed per-(session, role, attempt) code
seed. Here the seed is the field session's seed_hex (fieldprobes bed), as in the rest of the spike.
"""
from __future__ import annotations

import hashlib
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ZK = HERE.parent
FIELD = ZK.parent / "melody" / "fieldtest"
sys.path.insert(0, str(FIELD))
sys.path.insert(0, str(ZK / "optionA-jbl250"))

T0 = 0.09
M_TAPS = 63
HM = (M_TAPS - 1) // 2
BC, BH = 8, 8
DELTA_MS = 2
PROBE = "JBL250"
CODE_TAG = b"pop-code-v2"


@lru_cache(None)
def fir(sr: int):
    import fieldprobes as fp
    from scipy.signal import firwin, freqz
    h = firwin(M_TAPS, [fp.BAND_HZ[0], fp.BAND_HZ[1]], pass_zero=False, fs=sr, window=("kaiser", 6.0))
    hi = np.round(h * (2 ** (BH - 1) - 1) / np.abs(h).max()).astype(np.int64)
    w, H = freqz(hi.astype(float), worN=4096, fs=sr)
    band = (w > 3000) & (w < 16000)
    g = float(np.sqrt(np.mean(np.abs(H[band]) ** 2)))
    return tuple(int(v) for v in hi), g


@lru_cache(None)
def params(sr: int) -> dict:
    h, g = fir(sr)
    B = int(round(g * g / (T0 * T0)))
    L = int(round(0.25 * sr))
    return {"sr": sr, "L": L, "h": list(h), "g": g, "B": B, "HM": HM, "M": M_TAPS,
            "WPRE": int(round(0.150 * sr)), "WPOST": int(round(0.250 * sr)), "DELTA": DELTA_MS * sr // 1000}


def geometry(sr: int) -> dict:
    p = params(sr)
    K = 2 * p["DELTA"] + 1
    NS = K + p["L"] - 1 + 2 * HM
    NP = p["L"] + 2 * HM
    return {"K": K, "NS": NS, "NLS": -(-(1023 + NS) // 1024), "NP": NP, "NLP": -(-(1023 + NP) // 1024)}


def width_W(sr: int) -> int:
    p = params(sr)
    L, h, B = p["L"], p["h"], p["B"]
    imax = 32768 * 127 * L
    env2 = 2 * imax * imax
    ymax = 32768 * sum(abs(v) for v in h)
    Emax = L * ymax * ymax
    cmax = Emax * 127 * 127 * L
    W = (max(cmax, env2 * B) + 1).bit_length() + 1
    assert W < 250
    return W


@lru_cache(None)
def templates(seed_hex: str, emitter: str, sr: int):
    """(cI, cQ) int8 lists for the bed of `emitter`, rendered at sr (what the listener at sr correlates)."""
    import fieldprobes as fp
    L = params(sr)["L"]
    c = fp.template(seed_hex, PROBE, emitter, sr).astype(np.float64)
    assert len(c) == L, (len(c), L)
    nfft = 1 << 17
    C = np.fft.rfft(c, nfft) * fp.rx_mask(PROBE, nfft, sr)
    cm = np.fft.irfft(C, nfft)
    A = np.zeros(nfft, dtype=complex)
    A[: nfft // 2 + 1] = C
    A[1: nfft // 2] *= 2.0
    a = np.fft.ifft(A)
    cI, cQ = cm[:L], a.imag[:L]
    s = (2 ** (BC - 1) - 1) / max(np.abs(cI).max(), np.abs(cQ).max())
    return tuple(int(v) for v in np.round(cI * s)), tuple(int(v) for v in np.round(cQ * s))


def code_commit(cIs, cQs, cIp, cQp) -> bytes:
    """SHA-256("pop-code-v2" | int8 cI_self | cQ_self | cI_partner | cQ_partner), all at the signer's sr."""
    b = b"".join(np.asarray(v, dtype=np.int8).tobytes() for v in (cIs, cQs, cIp, cQp))
    return hashlib.sha256(CODE_TAG + b).digest()


def corr_exact(x, c, K, L):
    v = np.lib.stride_tricks.sliding_window_view(np.asarray(x[: K + L - 1], dtype=np.int64), L)
    c = np.asarray(c, dtype=np.int64)
    out = np.empty(K, dtype=np.int64)
    for k0 in range(0, K, 1024):
        out[k0: k0 + 1024] = v[k0: k0 + 1024] @ c
    return out


def curve(xw, cI, cQ, K, sr):
    """xw = x[lo-HM : lo+K+L-1+HM] (int16). -> (I, Q, E) Python ints, lags lo .. lo+K-1."""
    p = params(sr)
    L = p["L"]
    xw = np.asarray(xw, dtype=np.int64)
    assert len(xw) == K + L - 1 + 2 * HM
    I = corr_exact(xw[HM:], cI, K, L)
    Q = corr_exact(xw[HM:], cQ, K, L)
    h = np.asarray(p["h"], dtype=np.int64)
    y = np.convolve(xw, h[::-1], mode="valid")
    assert len(y) == K + L - 1
    cs = [0]
    for v in y:
        cs.append(cs[-1] + int(v) * int(v))
    E = [cs[k + L] - cs[k] for k in range(K)]
    return [int(v) for v in I], [int(v) for v in Q], E


def passes(I, Q, E, cn2, sr):
    B = params(sr)["B"]
    return [(i * i + q * q) * B >= e * cn2 for i, q, e in zip(I, Q, E)]


def score(I, Q, E, cn2, sr):
    g = params(sr)["g"]
    return [float(np.sqrt((i * i + q * q) * g * g / (e * cn2))) if e else 0.0 for i, q, e in zip(I, Q, E)]


def earliest(x, cI, cQ, lo, hi, sr):
    """Earliest lag in [lo, hi) with score >= T0 on capture x. -> (lag or None, score, I, Q, E)."""
    K = hi - lo
    L = params(sr)["L"]
    I, Q, E = curve(x[lo - HM: lo + K + L - 1 + HM], cI, cQ, K, sr)
    cn2 = sum(v * v for v in cI)
    ok = passes(I, Q, E, cn2, sr)
    j = next((j for j, v in enumerate(ok) if v), None)
    sc = score(I, Q, E, cn2, sr)
    return (None if j is None else lo + j), (None if j is None else sc[j]), I, Q, E


def selftest():
    import twin as tw1
    p = params(48_000)
    h, g = tw1.fir()
    assert p["h"] == [int(v) for v in h] and abs(p["g"] - g) < 1e-15 and p["B"] == tw1.bconst(g, T0)
    assert p["L"] == tw1.L and p["WPRE"] == 7200 and p["WPOST"] == 12000 and p["DELTA"] == 96
    seed = "5b" * 32
    a = templates(seed, "A", 48_000)
    b = tw1.templates(seed, "A")
    assert list(a[0]) == [int(v) for v in b[0]] and list(a[1]) == [int(v) for v in b[1]]
    for sr in (48_000, 44_100):
        print(sr, {k: v for k, v in params(sr).items() if k != "h"}, geometry(sr), "W", width_W(sr))
    print("oa_rate selftest ok (48 kHz equals the optionA-v2 twin)")


if __name__ == "__main__":
    selftest()
