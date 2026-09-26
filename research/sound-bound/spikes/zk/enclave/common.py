"""Shared byte layouts for sound-bound fixtures (SBv1 transcript, SBcred1 credential)."""
import struct

C_CM_S = 34300.0
P256_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
ROLE_BYTE = {"A": 0x41, "B": 0x42}


def transcript(nonce: bytes, attempt: int, role: str, own_pub: bytes, partner_pub: bytes,
               sr: int, half: int, rec_hash: bytes, ts: list[int]) -> bytes:
    assert len(nonce) == 32 and len(own_pub) == 64 and len(partner_pub) == 64 and len(rec_hash) == 32
    assert 0 <= attempt < 256 and len(ts) < 256
    return (b"SBv1" + nonce + struct.pack(">BB", attempt, ROLE_BYTE[role]) + own_pub + partner_pub
            + struct.pack(">Ii", sr, half) + rec_hash + struct.pack(">B", len(ts))
            + b"".join(struct.pack(">Q", t) for t in ts))


def credential(device_pub: bytes, expiry_unix: int) -> bytes:
    assert len(device_pub) == 64
    return b"SBcred1" + device_pub + struct.pack(">Q", expiry_unix)


def low_s(r: int, s: int) -> tuple[int, int, bool]:
    if s > P256_N // 2:
        return r, P256_N - s, True
    return r, s, False


def flight_cm(half_a: int, half_b: int, sr: int) -> float:
    return C_CM_S / 2 * (half_a - half_b) / sr


def verdict(fl: float) -> str:
    return "NEAR" if -20 < fl < 60 else "NOT_NEAR"
