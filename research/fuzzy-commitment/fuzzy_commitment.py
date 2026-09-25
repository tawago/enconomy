"""Fuzzy commitment generation and reproduction."""

import os
import hashlib
import numpy as np
from dataclasses import dataclass
from typing import Optional

from bch_codec import BCHCodec, get_params


@dataclass
class CommitmentResult:
    commitment: np.ndarray
    secret_hash: str
    secret: bytes
    bch_params: dict


@dataclass
class ReproductionResult:
    success: bool
    key_match: bool
    reproduced_hash: Optional[str]
    original_hash: str
    hamming_distance: int
    disagreement_pct: float
    decode_success: bool
    corrected_errors: int
    message: str


def generate_commitment(bit_vector: np.ndarray, secret: Optional[bytes] = None) -> CommitmentResult:
    """Generate a fuzzy commitment from a bit vector.

    Args:
        bit_vector: 511-bit feature vector
        secret: Optional secret bytes. If None, random secret is generated.

    Returns:
        CommitmentResult with commitment bits, secret hash, and BCH params
    """
    codec = BCHCodec()

    if secret is None:
        secret = os.urandom(codec.data_bytes)
    elif len(secret) < codec.data_bytes:
        secret = secret + b'\x00' * (codec.data_bytes - len(secret))
    elif len(secret) > codec.data_bytes:
        secret = secret[:codec.data_bytes]

    codeword_bits = codec.encode_bits(secret)

    if len(bit_vector) != codec.n_bits:
        raise ValueError(f"bit_vector must be {codec.n_bits} bits, got {len(bit_vector)}")

    commitment = np.bitwise_xor(codeword_bits, bit_vector.astype(np.uint8))

    secret_hash = hashlib.sha256(secret).hexdigest()[:16]

    return CommitmentResult(
        commitment=commitment,
        secret_hash=secret_hash,
        secret=secret,
        bch_params=codec.params,
    )


def reproduce_commitment(
    commitment: np.ndarray,
    bit_vector: np.ndarray,
    original_hash: str,
) -> ReproductionResult:
    """Attempt to reproduce the secret from a commitment using a new bit vector.

    Args:
        commitment: The commitment bits (codeword XOR original_bits)
        bit_vector: New 511-bit feature vector to reproduce with
        original_hash: Hash of the original secret for verification

    Returns:
        ReproductionResult with match status and diagnostics
    """
    codec = BCHCodec()

    if len(bit_vector) != codec.n_bits:
        raise ValueError(f"bit_vector must be {codec.n_bits} bits, got {len(bit_vector)}")

    candidate_codeword = np.bitwise_xor(commitment, bit_vector.astype(np.uint8))

    decode_result = codec.decode_bits(candidate_codeword)

    hamming_dist = int(np.sum(commitment != codec.encode_bits(decode_result.data if decode_result.data else b'\x00' * codec.data_bytes) ^ bit_vector.astype(np.uint8)))

    original_bits = np.bitwise_xor(commitment, codec.encode_bits(decode_result.data if decode_result.data else b'\x00' * codec.data_bytes))
    hamming_dist = int(np.sum(original_bits != bit_vector.astype(np.uint8)))
    disagreement_pct = hamming_dist / codec.n_bits * 100

    if not decode_result.success:
        return ReproductionResult(
            success=False,
            key_match=False,
            reproduced_hash=None,
            original_hash=original_hash,
            hamming_distance=hamming_dist,
            disagreement_pct=disagreement_pct,
            decode_success=False,
            corrected_errors=0,
            message=decode_result.message,
        )

    reproduced_hash = hashlib.sha256(decode_result.data).hexdigest()[:16]
    key_match = reproduced_hash == original_hash

    return ReproductionResult(
        success=True,
        key_match=key_match,
        reproduced_hash=reproduced_hash,
        original_hash=original_hash,
        hamming_distance=hamming_dist,
        disagreement_pct=disagreement_pct,
        decode_success=True,
        corrected_errors=decode_result.corrected_errors,
        message=f"Decoded successfully, corrected {decode_result.corrected_errors} errors, key {'matches' if key_match else 'MISMATCH'}",
    )


def compute_raw_hamming(bits1: np.ndarray, bits2: np.ndarray) -> tuple[int, float]:
    """Compute raw Hamming distance between two bit vectors."""
    distance = int(np.sum(bits1 != bits2))
    pct = distance / len(bits1) * 100
    return distance, pct
