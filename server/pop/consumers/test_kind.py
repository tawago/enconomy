"""Shared-layer test kind (spec 01 §9): ctx_hash is taken as-is, only its shape is checked.
Attestations use tag pop-test-v1 (no contract accepts it) and may carry fake/staging/sandbox humans."""
from __future__ import annotations

from pop import attest

KIND = "test"
TAG = b"pop-test-v1"


def validate(context: dict) -> bytes:
    return bytes.fromhex(context["ctx_hash"][2:])


def digest(s: dict, dev_a: bytes, dev_b: bytes, expiry: int) -> bytes:
    c = s["context"]
    return attest.tagged_digest(TAG, c["chain_id"], c["consumer"], c["ctx_hash"], s["human"]["pair_tag"],
                                dev_a, dev_b, expiry)
