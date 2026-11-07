from __future__ import annotations


class ApiError(Exception):
    """-> HTTP status + {"error": code, "detail": detail}, the same shape as the core's errors."""

    def __init__(self, status: int, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.status, self.code, self.detail = status, code, detail
