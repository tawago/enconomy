"""Consumer kinds (worldid spec 01 §9). Each module: KIND, TAG, validate(context) -> ctx_hash bytes.

`test` is registered only when POP_TEST_KINDS=1. `safe-tx` is specified in 02 and added once frozen.
"""
from __future__ import annotations

import os
from types import ModuleType

from pop.consumers import test_kind


def kinds(test_kinds: bool | None = None) -> dict[str, ModuleType]:
    if test_kinds is None:
        test_kinds = os.environ.get("POP_TEST_KINDS", "0").strip().lower() in ("1", "true", "yes", "on")
    out: dict[str, ModuleType] = {}
    if test_kinds:
        out[test_kind.KIND] = test_kind
    return out
