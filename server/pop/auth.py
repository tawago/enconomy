"""Signed-request auth (contract §2.3).

msg = "pop-req-v1\\n<METHOD>\\n<PATH?QUERY>\\n<sha256 hex of body>\\n<X-Pop-Ts>"
X-Pop-Device = device_id, X-Pop-Ts = unix ms, X-Pop-Sig = base64 std of raw r||s.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
from typing import Callable

from pop import constants as K
from pop.crypto import verify_raw
from pop.errors import PopError
from pop.store import Store


def request_message(method: str, path_qs: str, body: bytes, ts: str) -> bytes:
    return "\n".join(["pop-req-v1", method.upper(), path_qs, hashlib.sha256(body).hexdigest(), ts]).encode()


class Authenticator:
    def __init__(self, store: Store, now_ms: Callable[[], int]):
        self.store, self.now_ms = store, now_ms
        self._seen: dict[tuple[str, str, str], int] = {}  # (device, ts, sig) -> forget after (ms)

    def check(self, method: str, path_qs: str, body: bytes, headers) -> dict:
        dev_id, ts, sig_b64 = headers.get("x-pop-device"), headers.get("x-pop-ts"), headers.get("x-pop-sig")
        if not dev_id or not ts or not sig_b64:
            raise PopError(401, "auth_bad_signature", "missing X-Pop-* headers")
        dev = self.store.get_device(dev_id)
        if dev is None:
            raise PopError(401, "auth_unknown_device", dev_id)
        now = self.now_ms()
        if not ts.isdigit() or abs(now - int(ts)) > K.AUTH_SKEW_S * 1000:
            raise PopError(401, "auth_stale", f"ts={ts} now={now}")
        try:
            sig = base64.b64decode(sig_b64, validate=True)
        except (binascii.Error, ValueError):
            raise PopError(401, "auth_bad_signature", "sig not base64") from None
        if not verify_raw(bytes.fromhex(dev["pubkey"]), request_message(method, path_qs, body, ts), sig):
            raise PopError(401, "auth_bad_signature", "")
        self._seen = {k: v for k, v in self._seen.items() if v > now}
        key = (dev_id, ts, sig_b64)
        if key in self._seen:
            raise PopError(401, "auth_replay", "")
        self._seen[key] = now + K.AUTH_REPLAY_S * 1000
        return dev
