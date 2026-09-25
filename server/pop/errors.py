from __future__ import annotations


class PopError(Exception):
    """-> HTTP status + {"error": code, "detail": detail} (contract §9)."""

    def __init__(self, status: int, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.status, self.code, self.detail = status, code, detail
