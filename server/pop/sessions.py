"""Session documents and pairing (contract §3, §9.1).

created -join-> joined -confirm x2-> confirmed -arm x2-> started -> done ; any -> aborted.
This module covers create / join / confirm / abort / view. Arm, commit, transcript, fail and
result extend the same document (fields reserved below).

seed_hex never leaves the server. nonce_hex is shown only from `confirmed` on.
"""
from __future__ import annotations

import hmac
import secrets
from typing import Callable

from pop import constants as K
from pop import invite
from pop.crypto import key_hint
from pop.errors import PopError
from pop.store import Store

ROLES = ("A", "B")
LIVE = ("created", "joined", "confirmed", "started")


def _flags() -> dict:
    return {"A": False, "B": False}


class Sessions:
    def __init__(self, store: Store, now_ms: Callable[[], int]):
        self.store, self.now_ms = store, now_ms

    # -- persistence
    def _save(self, s: dict) -> dict:
        s["seq"] += 1
        s["updated_ms"] = self.now_ms()
        self.store.put_session(s)
        return s

    def _expire(self, s: dict) -> dict:
        now = self.now_ms()
        if s["state"] == "created" and now > s["token_expires_ms"]:
            s["state"], s["error"] = "aborted", "timeout"
            return self._save(s)
        if s["state"] in LIVE and now - s["created_ms"] > K.SESSION_MAX_AGE_S * 1000:
            s["state"], s["error"] = "aborted", "timeout"
            return self._save(s)
        return s

    def load(self, session_id: str) -> dict:
        s = self.store.get_session(session_id.lower())
        if s is None:
            raise PopError(404, "not_found", "unknown session")
        return self._expire(s)

    @staticmethod
    def role_of(s: dict, device_id: str) -> str | None:
        if device_id == s["host_device_id"]:
            return "A"
        if device_id == s["guest_device_id"]:
            return "B"
        return None

    def member(self, s: dict, dev: dict) -> str:
        role = self.role_of(s, dev["device_id"])
        if role is None:
            raise PopError(403, "not_member", "")
        return role

    # -- pairing
    def create(self, host: dict) -> dict:
        now = self.now_ms()
        s = {
            "session_id": secrets.token_hex(16),
            "seed_hex": secrets.token_hex(32),
            "nonce_hex": secrets.token_hex(32),
            "join_token": secrets.token_hex(16),
            "token_expires_ms": now + K.JOIN_TOKEN_TTL_S * 1000,
            "state": "created", "attempt": 0, "seq": 0,
            "created_ms": now, "updated_ms": now, "finished_ms": None,
            "host_device_id": host["device_id"], "guest_device_id": None,
            "confirmed": _flags(), "armed": _flags(), "committed": _flags(), "submitted": _flags(),
            "t0_ms": None, "result": None, "error": None,
            "attempts": [],
            "per_role": {"A": {}, "B": {}},  # arm/commit/transcript data, keyed by role
        }
        self._save(s)
        exp_s = s["token_expires_ms"] // 1000
        inv = invite.encode(s["session_id"], s["join_token"], exp_s, key_hint(bytes.fromhex(host["pubkey"])))
        return {"session_id": s["session_id"], "join_token": s["join_token"],
                "expires_at_ms": s["token_expires_ms"], "invite_b64url": invite.b64url(inv),
                "invite_qr": invite.to_qr(inv)}

    def join(self, session_id: str, guest: dict, token: str) -> dict:
        s = self.load(session_id)
        if guest["device_id"] == s["host_device_id"]:
            raise PopError(400, "self_join", "")
        if s["guest_device_id"] is not None:
            raise PopError(409, "already_joined", "")
        if not isinstance(token, str) or not hmac.compare_digest(token.lower(), s["join_token"]):
            raise PopError(403, "bad_token", "")
        if s["state"] != "created" or self.now_ms() > s["token_expires_ms"]:
            raise PopError(410, "token_expired", "")
        s["guest_device_id"] = guest["device_id"]
        s["state"] = "joined"
        return self._save(s)

    def confirm(self, s: dict, role: str) -> dict:
        if s["state"] == "confirmed" or (s["state"] == "joined" and s["confirmed"][role]):
            return s  # idempotent
        if s["state"] != "joined":
            raise PopError(409, "bad_state", s["state"])
        s["confirmed"][role] = True
        if all(s["confirmed"].values()):
            s["state"] = "confirmed"
        return self._save(s)

    def abort(self, s: dict, role: str) -> dict:
        if s["state"] in ("done", "aborted"):
            return s
        s["state"], s["error"] = "aborted", "aborted"
        s["attempts"].append({"attempt": s["attempt"], "outcome": "aborted", "reason": "aborted", "by": role})
        s["finished_ms"] = self.now_ms()
        return self._save(s)

    # -- view (§9)
    def view(self, s: dict, role: str) -> dict:
        me_id = s["host_device_id"] if role == "A" else s["guest_device_id"]
        other_id = s["guest_device_id"] if role == "A" else s["host_device_id"]
        me = self.store.get_device(me_id)
        other = self.store.get_device(other_id) if other_id else None
        shown = all(s["confirmed"].values())
        return {
            "session_id": s["session_id"], "seq": s["seq"], "state": s["state"], "attempt": s["attempt"],
            "role": role,
            "nonce": s["nonce_hex"] if shown else None,
            "self": {"device_id": me["device_id"], "display_name": me["display_name"], "pubkey": me["pubkey"]},
            "partner": None if other is None else {
                "device_id": other["device_id"], "display_name": other["display_name"], "model": other["model"],
                "attested": other["attested"], "security_level": other["security_level"], "pubkey": other["pubkey"]},
            "confirmed": dict(s["confirmed"]), "armed": dict(s["armed"]),
            "committed": dict(s["committed"]), "submitted": dict(s["submitted"]),
            "t0_ms": s["t0_ms"],
            "constants": {"a_play_s": K.A_PLAY_S, "b_play_s": K.B_PLAY_S, "lead_s": K.LEAD_S, "capture_s": K.CAPTURE_S},
            "result": s["result"],
            "error": s["error"],
        }
