"""Shared-layer test kind (spec 01 §9): ctx_hash is taken as-is, only its shape is checked."""
from __future__ import annotations

KIND = "test"
TAG = b"pop-test-v1"


def validate(context: dict) -> bytes:
    return bytes.fromhex(context["ctx_hash"][2:])
