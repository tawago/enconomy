"""Consumer kinds (worldid spec 01 §9). Each module: KIND, TAG, validate(context) -> ctx_hash bytes,
digest(s, dev_a, dev_b, expiry) -> the attestation digest.

`safe-tx` (spec 02 §7) is always on. `test` is registered only when POP_TEST_KINDS=1.
"""
from __future__ import annotations

import os
from types import ModuleType

from pop.consumers import safe_tx, test_kind


def kinds(test_kinds: bool | None = None) -> dict[str, ModuleType]:
    if test_kinds is None:
        test_kinds = os.environ.get("POP_TEST_KINDS", "0").strip().lower() in ("1", "true", "yes", "on")
    out: dict[str, ModuleType] = {safe_tx.KIND: safe_tx}
    if test_kinds:
        out[test_kind.KIND] = test_kind
    return out
