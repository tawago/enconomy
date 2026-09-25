"""Session documents and pairing (contract §3, §9.1).

created -join-> joined -confirm x2-> confirmed -arm x2-> started -> done ; any -> aborted.
This module covers create / join / confirm / abort / view, arm (§4.3, §4.4), commit (§5.2, §7.2)
and next_attempt (§8.2 retry). Transcript, fail and result extend the same document.

seed_hex never leaves the server; bed keys are derived per (role, attempt) from it (jbl250.bed_key).
nonce_hex is shown only from `confirmed` on. A phone gets its own play PCM + own bed at arm and the
partner's bed only after its own commit; the partner's play PCM is never sent.

Choices the contract leaves open:
  - arm is idempotent for the same (attempt, sample_rate); another sample_rate after arming = 409.
  - arm with rtt_min_ms > 300 is refused (400 bad_request); the phone should refuse first.
  - commit is accepted only from t0 + B_PLAY_S + CODE_S (all sounds over by schedule), else 409 too_early.
  - a repeated identical commit returns the partner bed again; a different one is 409 already_committed.
  - a bad commit (signature / fields) is rejected with 400 and does not change the session;
    turning it into a final NOT_NEAR is the result step's job.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Callable

from pop import constants as K
from pop import invite, jbl250
from pop.codec import b64d, decode_commit, pcm
from pop.crypto import key_hint, verify_raw
from pop.errors import PopError
from pop.store import Store

ROLES = ("A", "B")
OTHER = {"A": "B", "B": "A"}
MAX_RTT_MS = 300
T0_DELAY_MS = 3000
LIVE = ("created", "joined", "confirmed", "started")


def _flags() -> dict:
    return {"A": False, "B": False}


class Sessions:
    def __init__(self, store: Store, now_ms: Callable[[], int], gain_db: float = 0.0):
        self.store, self.now_ms, self.gain_db = store, now_ms, gain_db

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

    # -- arm / start (§4.3, §4.4)
    def _key(self, s: dict, role: str) -> bytes:
        return jbl250.bed_key(s["seed_hex"], role, s["attempt"])

    def _arm_material(self, s: dict, role: str) -> dict:
        sr = s["per_role"][role]["sample_rate"]
        key = self._key(s, role)
        play, _ = jbl250.render(key, role, sr, self.gain_db)
        return {"attempt": s["attempt"], "sample_rate": sr, "play": pcm(play),
                "own_bed": pcm(jbl250.template(key, role, sr))}

    def arm(self, s: dict, role: str, attempt, sample_rate, rtt_min_ms) -> dict:
        if s["state"] not in ("confirmed", "started"):
            raise PopError(409, "bad_state", s["state"])
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt != s["attempt"]:
            raise PopError(400, "bad_attempt", f"current attempt is {s['attempt']}")
        if not isinstance(sample_rate, int) or isinstance(sample_rate, bool) or not K.SR_MIN <= sample_rate <= K.SR_MAX:
            raise PopError(400, "bad_sample_rate", f"{K.SR_MIN}..{K.SR_MAX}")
        if not isinstance(rtt_min_ms, (int, float)) or isinstance(rtt_min_ms, bool) or not 0 <= rtt_min_ms <= MAX_RTT_MS:
            raise PopError(400, "bad_request", f"rtt_min_ms must be 0..{MAX_RTT_MS}")
        if s["armed"][role]:
            if s["per_role"][role]["sample_rate"] != sample_rate:
                raise PopError(409, "bad_state", "already armed at another sample_rate")
            return self._arm_material(s, role)
        if s["state"] != "confirmed":
            raise PopError(409, "bad_state", s["state"])
        s["per_role"][role] = {"sample_rate": sample_rate, "rtt_min_ms": float(rtt_min_ms), "armed_ms": self.now_ms()}
        s["armed"][role] = True
        if all(s["armed"].values()):
            s["state"], s["t0_ms"] = "started", self.now_ms() + T0_DELAY_MS
        self._save(s)
        return self._arm_material(s, role)

    # -- commit, then reveal the partner bed (§5.2, §7.2)
    def _partner_bed(self, s: dict, role: str) -> dict:
        other = OTHER[role]
        sr = s["per_role"][role]["sample_rate"]
        return {"partner_bed": pcm(jbl250.template(self._key(s, other), other, sr))}

    def commit(self, s: dict, role: str, dev: dict, commit_b64, sig_b64) -> dict:
        if s["state"] != "started":
            raise PopError(409, "bad_state", s["state"])
        try:
            raw, sig = b64d(commit_b64), b64d(sig_b64)
            c = decode_commit(raw)
        except ValueError as e:
            raise PopError(400, "transcript_mismatch", str(e)) from None
        if not verify_raw(bytes.fromhex(dev["pubkey"]), raw, sig):
            raise PopError(400, "signature_invalid", "commit")
        if c["role"] != role or c["attempt"] != s["attempt"] or c["nonce"] != bytes.fromhex(s["nonce_hex"]):
            raise PopError(400, "transcript_mismatch", "role/attempt/nonce")
        mine = s["per_role"][role]
        if s["committed"][role]:
            if mine["commit_b64"] != commit_b64:
                raise PopError(409, "already_committed", "")
            return self._partner_bed(s, role)
        if self.now_ms() < s["t0_ms"] + int((K.B_PLAY_S + K.CODE_S) * 1000):
            raise PopError(409, "too_early", "commit before the schedule ends")
        mine.update({"commit_b64": commit_b64, "commit_sig_b64": sig_b64,
                     "commit_sha256": hashlib.sha256(raw).hexdigest(), "rec_sha256": c["rec_sha256"].hex(),
                     "committed_ms": self.now_ms()})
        s["committed"][role] = True
        self._save(s)
        return self._partner_bed(s, role)

    # -- retry (§8.2): attempt k failed, k + 1 < MAX_ATTEMPTS
    def next_attempt(self, s: dict, reason: str, by: str | None) -> dict:
        if s["attempt"] + 1 >= K.MAX_ATTEMPTS:
            raise PopError(409, "bad_state", "no attempts left")
        s["attempts"].append({"attempt": s["attempt"], "outcome": "failed", "reason": reason, "by": by,
                              "per_role": s["per_role"], "t0_ms": s["t0_ms"]})
        s["attempt"] += 1
        s["state"], s["t0_ms"] = "confirmed", None
        s["armed"], s["committed"], s["submitted"] = _flags(), _flags(), _flags()
        s["per_role"] = {"A": {}, "B": {}}
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
