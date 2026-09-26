"""Shared constants and byte layouts for optionA-v2.

Receiver (new decisions, 2026-09-26): earliest sample whose normalized score >= bar, fixed floor
T0 = 9 %, 0 ppm, no live bar. Integer form, exactly what the circuit checks:
    I_k = sum_n cI[n] x[k+n],  Q_k = sum_n cQ[n] x[k+n],  env2_k = I_k^2 + Q_k^2      (L = 12,000)
    y = h * x (63-tap 8-bit band-pass, centred), E_k = sum_{m<L} y[k+m]^2, cn2 = sum cI^2
    score_k >= T0   <=>   env2_k * B >= E_k * cn2,   B = round(g^2 / T0^2)
Templates cI, cQ (8-bit), FIR h, gain g: optionA-jbl250/twin.py (reused unchanged).
"""
from __future__ import annotations

import hashlib
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ZK = HERE.parent
sys.path.insert(0, str(ZK / "optionA-jbl250"))
sys.path.insert(0, str(ZK / "enclave"))
sys.path.insert(0, str(HERE / "poseidon7"))

SR = 48_000
L = 12_000
M_TAPS = 63
HM = (M_TAPS - 1) // 2          # 31
T0 = 0.09
WPRE = int(0.150 * SR)          # partner window [p_partner - WPRE, p_partner + WPOST]
WPOST = int(0.250 * SR)
DELTAS_MS = (1, 2, 5)
PARTNER_WINDOWS_MS = {"w400": (150, 250), "w150": (50, 100), "w60": (20, 40)}
C_CM_S = 34300.0
ROLE_BYTE = {"A": 0x41, "B": 0x42}
P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
N_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551


def delta_samples(ms):
    return ms * SR // 1000


def geometry(delta):
    """Circuit sizes for a self tolerance delta (samples)."""
    K = 2 * delta + 1
    NS = K + L - 1 + 2 * HM                 # self samples needed
    NLS = -(-(1023 + NS) // 1024)
    NP = L + 2 * HM                         # partner samples needed
    NLP = -(-(1023 + NP) // 1024)
    return {"K": K, "NS": NS, "NLS": NLS, "NP": NP, "NLP": NLP}


# ------------------------------------------------------------------ transcript v2
def transcript_v2(nonce, attempt, role, own_pub, partner_pub, sr, half, rec_root, p_self, p_partner,
                  delta, a_self, a_partner, code_commit, ts):
    """SBv2 (265 bytes with one timestamp), big-endian:
    "SBv2" | nonce(32) | attempt u8 | role u8 | own_pub(64) | partner_pub(64) | sr u32 | half i32
    | rec_root(32, Poseidon7 Merkle root, canonical < p) | p_self u32 | p_partner u32 | delta u16
    | a_self u32 | a_partner u32 | code_commit(32) | n_ts u8 | ts u64 * n_ts
    """
    assert len(nonce) == 32 and len(own_pub) == 64 and len(partner_pub) == 64 and len(code_commit) == 32
    assert 0 <= rec_root < P
    return (b"SBv2" + nonce + struct.pack(">BB", attempt, ROLE_BYTE[role]) + own_pub + partner_pub
            + struct.pack(">Ii", sr, half) + rec_root.to_bytes(32, "big")
            + struct.pack(">IIHII", p_self, p_partner, delta, a_self, a_partner) + code_commit
            + struct.pack(">B", len(ts)) + b"".join(struct.pack(">Q", t) for t in ts))


def code_commit(cIs, cQs, cIp, cQp):
    """SHA-256("SBcode2" | int8 cI_self | cQ_self | cI_partner | cQ_partner). The verifier recomputes it
    from the public templates (derived from the session's revealed per-role, per-attempt code seed)."""
    import numpy as np
    b = b"".join(np.asarray(v, dtype=np.int8).tobytes() for v in (cIs, cQs, cIp, cQp))
    return hashlib.sha256(b"SBcode2" + b).digest()


def cred_v3(pub, expiry, hold_commit):
    """SBcred3 = "SBcred3" | device_pub(64) | expiry u64 | holder_commit(32) (Poseidon7, canonical)."""
    return b"SBcred3" + pub + struct.pack(">Q", expiry) + hold_commit.to_bytes(32, "big")


def flight_cm(half_a, half_b, sr=SR):
    return C_CM_S / 2 * (half_a - half_b) / sr


def verdict(fl):
    return "NEAR" if -20 < fl < 60 else "NOT_NEAR"


def low_s(r, s):
    return (r, N_ORDER - s, True) if s > N_ORDER // 2 else (r, s, False)
