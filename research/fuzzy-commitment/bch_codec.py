"""BCH codec wrapper using bchlib."""

import bchlib
import numpy as np
from dataclasses import dataclass
from typing import Optional

BCH_M = 9
BCH_T = 50


@dataclass
class DecodeResult:
    success: bool
    data: Optional[bytes]
    corrected_errors: int
    message: str


class BCHCodec:
    def __init__(self, t: int = BCH_T, m: int = BCH_M):
        self.t = t
        self.m = m
        self.bch = bchlib.BCH(t=t, m=m)
        self.ecc_bits = self.bch.ecc_bits
        self.ecc_bytes = self.bch.ecc_bytes
        self.n = (2 ** m) - 1
        self.data_bytes = (self.n - self.ecc_bits) // 8

    @property
    def params(self) -> dict:
        return {
            'n': self.n,
            'k': self.data_bytes * 8,
            't': self.t,
            'm': self.m,
            'ecc_bits': self.ecc_bits,
            'ecc_bytes': self.ecc_bytes,
        }

    def encode(self, data: bytes) -> bytes:
        """Encode data with BCH, returns data + ECC bytes."""
        if len(data) > self.data_bytes:
            data = data[:self.data_bytes]
        elif len(data) < self.data_bytes:
            data = data + b'\x00' * (self.data_bytes - len(data))

        ecc = self.bch.encode(data)
        return data + ecc

    def decode(self, codeword: bytes) -> DecodeResult:
        """Decode BCH codeword, attempt error correction."""
        expected_len = self.data_bytes + self.ecc_bytes
        if len(codeword) != expected_len:
            return DecodeResult(
                success=False,
                data=None,
                corrected_errors=0,
                message=f"Invalid codeword length: {len(codeword)} != {expected_len}"
            )

        data = bytearray(codeword[:self.data_bytes])
        ecc = bytearray(codeword[self.data_bytes:])

        try:
            nerr = self.bch.decode(data, ecc)
        except Exception as e:
            return DecodeResult(
                success=False,
                data=None,
                corrected_errors=0,
                message=f"Decode exception: {e}"
            )

        if nerr < 0:
            return DecodeResult(
                success=False,
                data=None,
                corrected_errors=0,
                message=f"Too many errors to correct (>{self.t})"
            )

        self.bch.correct(data, ecc)
        return DecodeResult(
            success=True,
            data=bytes(data),
            corrected_errors=nerr,
            message=f"Corrected {nerr} errors"
        )

    def encode_bits(self, data: bytes) -> np.ndarray:
        """Encode and return as bit array."""
        codeword = self.encode(data)
        bits = np.unpackbits(np.frombuffer(codeword, dtype=np.uint8))
        return bits[:self.n_bits]

    @property
    def n_bits(self) -> int:
        return (self.data_bytes + self.ecc_bytes) * 8

    def decode_bits(self, bits: np.ndarray) -> DecodeResult:
        """Decode from bit array."""
        padded_len = ((len(bits) + 7) // 8) * 8
        padded = np.zeros(padded_len, dtype=np.uint8)
        padded[:len(bits)] = bits
        codeword = np.packbits(padded).tobytes()
        return self.decode(codeword)


_default_codec = BCHCodec()


def get_params() -> dict:
    return _default_codec.params


def encode(data: bytes) -> bytes:
    return _default_codec.encode(data)


def decode(codeword: bytes) -> DecodeResult:
    return _default_codec.decode(codeword)


def encode_bits(data: bytes) -> np.ndarray:
    return _default_codec.encode_bits(data)


def decode_bits(bits: np.ndarray) -> DecodeResult:
    return _default_codec.decode_bits(bits)
