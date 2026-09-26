"""POPT v2 codes and per-rate constants (docs/pop-transcript-v2.md §3). Port of optionA-v2/oa_rate.py.

  cI, cQ      = band-masked bed template at the listener's sr and its Hilbert pair, truncated to L,
                int8 with one common scale 127 / max(|cI|, |cQ|) (numpy round, half to even)
  code_commit = sha256("pop-code-v2" | cI_self | cQ_self | cI_partner | cQ_partner), int8 bytes, signer's sr
  delta       = DELTA_MS * sr // 1000   (the circuit's self window half-width)

The server derives the codes and sends them (own_code at arm, partner_code after the POPC v2 commit): a phone
can't reproduce this FFT path bit for bit. RATES holds what the app's integer twin needs (FIR h, B); only
48 kHz and 44.1 kHz have circuits, so only they are listed. The plaintext verdict works at any rate.
"""
from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

import numpy as np

from pop import constants as K
from pop import jbl250

CODE_TAG = b"pop-code-v2"
NFFT = 1 << 17

# oa_rate.params(sr): h = firwin(63, [2000, 18000], kaiser 6) scaled to max|h| = 127, g = rms gain 3-16 kHz,
# B = round(g^2 / T0_V2^2). Hard-coded: the float design isn't portable. Checked against the spike in tests.
RATES = {
    48000: {"L": 12000, "B": 4474747, "delta": 96, "wpre": 7200, "wpost": 12000,
            "h": [0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 1, 2, 0, 2, 2, 0, 4, -1, 0, 2, -7, 0, -5, -13, 0, -19, -13, 0, -45,
                  27, 127, 27, -45, 0, -13, -19, 0, -13, -5, 0, -7, 2, 0, -1, 4, 0, 2, 2, 0, 2, 1, 0, 1, 0, 0, 0, 0,
                  0, 0, 0, 0, 0]},
    44100: {"L": 11025, "B": 3792174, "delta": 88, "wpre": 6615, "wpost": 11025,
            "h": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 2, 1, 1, 3, 0, 4, -1, 0, 1, -7, 1, -12, -6, -8, -22, 4, -40,
                  15, 127, 15, -40, 4, -22, -8, -6, -12, 1, -7, 1, 0, -1, 4, 0, 3, 1, 1, 2, 0, 1, 0, 0, 0, 0, 0, 0,
                  0, 0, 0, 0, 0]},
}


def delta(sr: int) -> int:
    return K.DELTA_MS * int(sr) // 1000


def _mask(sr: int) -> np.ndarray:
    f = np.fft.rfftfreq(NFFT, 1.0 / sr)
    return ((f >= K.BAND_HZ[0]) & (f <= K.BAND_HZ[1])).astype(np.float64)


def code_from_template(c: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """float bed template (length L) -> (cI, cQ) int8."""
    c = np.asarray(c, dtype=np.float64)
    L = c.size
    C = np.fft.rfft(c, NFFT) * _mask(sr)
    cm = np.fft.irfft(C, NFFT)
    A = np.zeros(NFFT, dtype=complex)
    A[: NFFT // 2 + 1] = C
    A[1: NFFT // 2] *= 2.0
    a = np.fft.ifft(A)
    cI, cQ = cm[:L], a.imag[:L]
    s = (2 ** (K.TEMPLATE_BITS - 1) - 1) / max(np.abs(cI).max(), np.abs(cQ).max())
    return np.round(cI * s).astype(np.int8), np.round(cQ * s).astype(np.int8)


@lru_cache(maxsize=32)
def _code(key: bytes, role: str, sr: int) -> tuple[bytes, bytes]:
    cI, cQ = code_from_template(jbl250.template(key, role, sr), sr)
    return cI.tobytes(), cQ.tobytes()


def code(key: bytes, role: str, sr: int) -> tuple[bytes, bytes]:
    """int8 (cI, cQ) bytes of `role`'s bed under `key`, as heard by a listener at sr."""
    return _code(bytes(key), role, int(sr))


def code_wire(key: bytes, role: str, sr: int) -> dict:
    cI, cQ = code(key, role, sr)
    return {"cI_b64": base64.b64encode(cI).decode(), "cQ_b64": base64.b64encode(cQ).decode(), "n": len(cI)}


def code_commit(self_code: tuple[bytes, bytes], partner_code: tuple[bytes, bytes]) -> bytes:
    return hashlib.sha256(CODE_TAG + self_code[0] + self_code[1] + partner_code[0] + partner_code[1]).digest()


def config() -> dict:
    """For GET /v1/config: what the app's integer twin needs per circuit rate."""
    return {str(sr): dict(v) for sr, v in RATES.items()}
