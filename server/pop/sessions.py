"""Session documents and pairing (contract §3, §9.1).

created -join-> joined -confirm x2-> confirmed -arm x2-> started -> done ; any -> aborted.
This module covers create / join / confirm / abort / view, arm (§4.3, §4.4), commit (§5.2, §7.2),
transcript / fail / timeout / retry / result (§7.1, §8) and the optional recording upload (§9).

seed_hex never leaves the server; bed keys are derived per (role, attempt) from it (jbl250.bed_key).
nonce_hex is shown only from `confirmed` on. A phone gets its own play PCM + own bed at arm and the
partner's bed only after its own commit; the partner's play PCM is never sent.

Choices the contract leaves open:
  - arm is idempotent for the same (attempt, sample_rate); another sample_rate after arming = 409.
  - arm with rtt_min_ms > 300 is refused (400 bad_request); the phone should refuse first.
  - commit is accepted only from t0 + B_PLAY_S + CODE_S (all sounds over by schedule), else 409 too_early.
  - a repeated identical commit returns the partner bed again; a different one is 409 already_committed.
  - a bad commit (signature / fields) is rejected with 400 and does not change the session
    (a phone may resend). A bad transcript from a member is final: 400 + done NOT_NEAR (§8.2).
  - transcript / fail need the sender's own commit first (409 bad_state); fail may also come
    before commit (capture_failed, self_not_heard, ...), from `confirmed` or `started`.
  - a signed transcript or fail for an older attempt is 409 stale_attempt and changes nothing
    (the retry already happened); a resend of the same transcript is idempotent, another one
    is 409 already_submitted.
  - self_os_delta is checked when both halves are in (combine), not at submit, around the device's
    enrollment calibration cal_us as snapshotted at arm (per_role cal_us, 0 = none; in the record's devices).
  - timeout = started and not both transcripts by t0 + TRANSCRIPT_DEADLINE_S, checked lazily
    on every load; `by` = the silent role (null if both).
  - the view carries `last_failure` {attempt, reason, by, text} so a phone can show why it
    re-arms; `error` is the final reason once done (null for NEAR), as for aborted.
  - the result record also carries `commits` {role: {commit_b64, sig_b64}} and `user_text`
    so verify_record() can re-check everything offline.

POPT v2 (docs/pop-transcript-v2.md), the version switch:
  - each phone picks its transcript version at arm: "popt": 1 (default, pop-v1 unchanged) or 2. It is pinned
    for that role and attempt (re-arm with another popt = 409); the two roles may differ (the plaintext
    verdict doesn't care; an option A pair proof needs both at 2).
  - v2 arm also returns own_code {cI_b64, cQ_b64, n} (int8); commit also returns partner_code, both at the
    phone's sr. Beds (float PCM) are still sent, for the v1 rule in meta.
  - commit and transcript must carry the armed version; POPC v2 commits rec_root; the transcript's
    code_commit must equal the Poseidon2 code_commitment (popt2.code_commit) of the codes sent.
  - v2 recording upload is checked against rec_root (Poseidon2/BN254 oalib tree; run off the event loop).

Option A proofs (pop/zk.py), after the verdict:
  - only once the session is done with NEAR, per role, for the final attempt, POPT v2 at 44.1 / 48 kHz, from a
    device holding an SBcred3. validAt = t0_ms // 1000 of that attempt (view `zk_valid_at`, record `zk.valid_at`).
  - the server derives the whole public vector itself (signed transcript, its own codes and issuer, the uploaded
    salt); credential checks (issuer, validAt <= expiry) run before the SNARK verifier.
  - s["zk"][role] keeps the last outcome; a verified proof is final (same bytes again = idempotent, other = 409),
    a rejected one may be replaced. The record's `zk` block mirrors it (without the salt).
"""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import secrets
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np

from pop import calibration as CAL
from pop import constants as K
from pop import human as H, invite, jbl250, popctx, popt2, poseidon2, verdict as V, zk
from pop import issuer as sbcred
from pop.codec import REC_KEY, b64d, decode_commit, decode_transcript, pcm, version_of
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


def _policy(s: dict) -> dict:
    return s.get("policy") or {"human": "none"}


def _iso(ms: int | None) -> str | None:
    return None if ms is None else datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="milliseconds")


def _int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


class Sessions:
    def __init__(self, store: Store, now_ms: Callable[[], int], gain_db: float = 0.0,
                 data_dir: str | Path | None = None, tune_db: float = 0.0):
        self.store, self.now_ms, self.gain_db, self.tune_db = store, now_ms, gain_db, tune_db
        self.data_dir = None if data_dir is None else Path(data_dir)
        self.code_attester: Callable[[bytes, int, str, bytes], dict] | None = None   # main.py: issuer.attest_code

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
        if s["state"] == "started" and now > s["t0_ms"] + K.TRANSCRIPT_DEADLINE_S * 1000:
            silent = [r for r in ROLES if not s["submitted"][r]]
            return self._failed(s, "timeout", silent[0] if len(silent) == 1 else None)
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
    def create(self, host: dict, context: dict | None = None, policy: dict | None = None) -> dict:
        """context (already validated by the route) -> nonce = PopCtx (worldid 01 §5); else random."""
        now = self.now_ms()
        sid = secrets.token_hex(16)
        not_before = now // 1000
        nonce_hex = secrets.token_hex(32) if context is None else popctx.nonce(
            context["chain_id"], context["consumer"], context["ctx_hash"], not_before, sid).hex()
        s = {
            "session_id": sid,
            "seed_hex": secrets.token_hex(32),
            "nonce_hex": nonce_hex,
            "not_before": not_before, "context": context, "policy": policy or {"human": "none"},
            "human": H.empty_human() if (policy or {}).get("human") == "worldid" else None,
            "join_token": secrets.token_hex(16),
            "token_expires_ms": now + K.JOIN_TOKEN_TTL_S * 1000,
            "state": "created", "attempt": 0, "seq": 0,
            "created_ms": now, "updated_ms": now, "finished_ms": None,
            "host_device_id": host["device_id"], "guest_device_id": None,
            "confirmed": _flags(), "armed": _flags(), "committed": _flags(), "submitted": _flags(),
            "t0_ms": None, "result": None, "error": None,
            "attempts": [], "last_failure": None,
            "per_role": {"A": {}, "B": {}},  # arm/commit/transcript data, keyed by role
        }
        self._save(s)
        exp_s = s["token_expires_ms"] // 1000
        inv = invite.encode(s["session_id"], s["join_token"], exp_s, key_hint(bytes.fromhex(host["pubkey"])))
        return {"session_id": s["session_id"], "join_token": s["join_token"],
                "expires_at_ms": s["token_expires_ms"], "invite_b64url": invite.b64url(inv),
                "invite_qr": invite.to_qr(inv),
                "nonce": s["nonce_hex"], "not_before": not_before, "context": context, "policy": s["policy"]}

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

    @staticmethod
    def _popt(s: dict, role: str) -> int:
        return s["per_role"][role].get("popt", 1)

    def _arm_material(self, s: dict, role: str) -> dict:
        sr = s["per_role"][role]["sample_rate"]
        key = self._key(s, role)
        play, info = jbl250.render(key, role, sr, self.gain_db, self.tune_db)
        out = {"attempt": s["attempt"], "sample_rate": sr, "play": pcm(play),
               "own_bed": pcm(jbl250.template(key, role, sr))}
        if self.tune_db:   # only when set, so the default response stays exactly pop-v1
            out["tune_db"] = {"requested": info["tune_db_requested"], "applied": round(info["tune_db_applied"], 3),
                              "max": round(info["tune_db_max"], 3), "peak": round(info["peak"], 4)}
        if self._popt(s, role) == 2:   # v1 response stays exactly pop-v1
            out["popt"] = 2
            out["own_code"] = popt2.code_wire(key, role, sr)
            out["delta"] = popt2.delta(sr)
        return out

    def arm(self, s: dict, role: str, attempt, sample_rate, rtt_min_ms, popt=None) -> dict:
        if s["state"] not in ("confirmed", "started"):
            raise PopError(409, "bad_state", s["state"])
        if _policy(s)["human"] == "worldid" and not H.both_verified(s.get("human")):
            raise PopError(409, "human_missing", "both roles need a verified World ID (two different humans)")
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt != s["attempt"]:
            raise PopError(400, "bad_attempt", f"current attempt is {s['attempt']}")
        if not isinstance(sample_rate, int) or isinstance(sample_rate, bool) or not K.SR_MIN <= sample_rate <= K.SR_MAX:
            raise PopError(400, "bad_sample_rate", f"{K.SR_MIN}..{K.SR_MAX}")
        if not isinstance(rtt_min_ms, (int, float)) or isinstance(rtt_min_ms, bool) or not 0 <= rtt_min_ms <= MAX_RTT_MS:
            raise PopError(400, "bad_request", f"rtt_min_ms must be 0..{MAX_RTT_MS}")
        popt = 1 if popt is None else popt
        if not _int(popt) or popt not in K.POPT_VERSIONS:
            raise PopError(400, "bad_request", f"popt must be one of {list(K.POPT_VERSIONS)}")
        if s["armed"][role]:
            if s["per_role"][role]["sample_rate"] != sample_rate:
                raise PopError(409, "bad_state", "already armed at another sample_rate")
            if self._popt(s, role) != popt:
                raise PopError(409, "bad_state", "already armed with another popt")
            return self._arm_material(s, role)
        if s["state"] != "confirmed":
            raise PopError(409, "bad_state", s["state"])
        s["per_role"][role] = {"sample_rate": sample_rate, "rtt_min_ms": float(rtt_min_ms), "armed_ms": self.now_ms(),
                               "popt": popt, "cal_us": self._cal_us(s, role)}
        s["armed"][role] = True
        if all(s["armed"].values()):
            s["state"], s["t0_ms"] = "started", self.now_ms() + T0_DELAY_MS
        self._save(s)
        return self._arm_material(s, role)

    # -- commit, then reveal the partner bed (§5.2, §7.2)
    def _partner_bed(self, s: dict, role: str) -> dict:
        other = OTHER[role]
        sr = s["per_role"][role]["sample_rate"]
        out = {"partner_bed": pcm(jbl250.template(self._key(s, other), other, sr))}
        if self._popt(s, role) == 2:
            out["partner_code"] = popt2.code_wire(self._key(s, other), other, sr)
            mine = s["per_role"][role]
            out["code_commit"] = mine.get("code_commit")
            out["code_attest"] = mine.get("code_attest")
        return out

    def _code_commit(self, s: dict, role: str) -> bytes:
        """What a v2 transcript of `role` must carry: own + partner codes at role's sr."""
        sr, other = s["per_role"][role]["sample_rate"], OTHER[role]
        return popt2.code_commit(popt2.code(self._key(s, role), role, sr), popt2.code(self._key(s, other), other, sr))

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
        ver = version_of(c)
        if ver != self._popt(s, role):
            raise PopError(400, "transcript_mismatch", f"POPC version {ver} != armed popt {self._popt(s, role)}")
        mine = s["per_role"][role]
        if s["committed"][role]:
            if mine["commit_b64"] != commit_b64:
                raise PopError(409, "already_committed", "")
            return self._partner_bed(s, role)
        if self.now_ms() < s["t0_ms"] + int((K.B_PLAY_S + K.CODE_S) * 1000):
            raise PopError(409, "too_early", "commit before the schedule ends")
        mine.update({"commit_b64": commit_b64, "commit_sig_b64": sig_b64,
                     "commit_sha256": hashlib.sha256(raw).hexdigest(), REC_KEY[ver]: c[REC_KEY[ver]].hex(),
                     "committed_ms": self.now_ms()})
        if ver == 2:   # the Poseidon2 code_commit the transcript must carry, attested by the issuer key
            cc = self._code_commit(s, role)
            mine["code_commit"] = cc.hex()
            if self.code_attester is not None:
                mine["code_attest"] = self.code_attester(bytes.fromhex(s["nonce_hex"]), s["attempt"], role, cc)
        s["committed"][role] = True
        self._save(s)
        return self._partner_bed(s, role)

    # -- retry (§8.2): attempt k failed, k + 1 < MAX_ATTEMPTS
    def next_attempt(self, s: dict, reason: str, by: str | None) -> dict:
        if s["attempt"] + 1 >= K.MAX_ATTEMPTS:
            raise PopError(409, "bad_state", "no attempts left")
        s["attempts"].append({"attempt": s["attempt"], "outcome": "failed", "reason": reason, "by": by,
                              "per_role": s["per_role"], "t0_ms": s["t0_ms"]})
        s["last_failure"] = {"attempt": s["attempt"], "reason": reason, "by": by, "text": V.USER_TEXT.get(reason)}
        s["attempt"] += 1
        s["state"], s["t0_ms"] = "confirmed", None
        s["armed"], s["committed"], s["submitted"] = _flags(), _flags(), _flags()
        s["per_role"] = {"A": {}, "B": {}}
        return self._save(s)

    # -- transcript, fail, verdict (§7.1, §8)
    def _dev(self, s: dict, role: str) -> dict | None:
        dev_id = s["host_device_id"] if role == "A" else s["guest_device_id"]
        return self.store.get_device(dev_id) if dev_id else None

    def _cal_us(self, s: dict, role: str) -> int:
        """The device's enrollment calibration now (0 = none); arm snapshots it per attempt."""
        return ((self._dev(s, role) or {}).get("cal_us")) or 0

    def _pk(self, s: dict, role: str) -> bytes:
        dev_id = s["host_device_id"] if role == "A" else s["guest_device_id"]
        return bytes.fromhex(self.store.get_device(dev_id)["pubkey"])

    def _failed(self, s: dict, reason: str, by: str | None) -> dict:
        """Measurement failure at the current attempt: retry if one is left, else final NOT_NEAR."""
        if reason in V.RETRY_REASONS and s["attempt"] + 1 < K.MAX_ATTEMPTS:
            return self.next_attempt(s, reason, by)
        return self._finalize(s, "NOT_NEAR", reason, None, "failed", by)

    def _finalize(self, s: dict, verdict: str, reason: str | None, flight: float | None, outcome: str,
                  by: str | None) -> dict:
        s["attempts"].append({"attempt": s["attempt"], "outcome": outcome, "reason": reason, "by": by,
                              "verdict": verdict, "flight_cm": flight, "per_role": s["per_role"], "t0_ms": s["t0_ms"]})
        s["state"], s["error"] = "done", reason
        s["finished_ms"] = self.now_ms()
        s["result"] = self._record(s, verdict, reason, flight)
        self._save(s)
        self._write(s["session_id"], "result.json", json.dumps(s["result"], indent=1).encode())
        return s

    def _record(self, s: dict, verdict: str, reason: str | None, flight: float | None) -> dict:
        """§8.4 (+ commits, user_text). Built from the final attempt's per-role data."""
        devices, transcripts, commits = {}, {}, {}
        for r in ROLES:
            dev_id = s["host_device_id"] if r == "A" else s["guest_device_id"]
            d = self.store.get_device(dev_id) if dev_id else None
            pr = s["per_role"][r]
            if d is not None:
                devices[r] = {"device_id": d["device_id"], "pubkey": d["pubkey"], "display_name": d["display_name"],
                              "model": d["model"], "attested": d["attested"], "security_level": d["security_level"],
                              "sample_rate": pr.get("sample_rate"), "half": pr.get("half"), "popt": pr.get("popt", 1),
                              "cal_us": pr.get("cal_us", 0)}
            if "transcript_b64" in pr:
                transcripts[r] = {"transcript_b64": pr["transcript_b64"], "sig_b64": pr["sig_b64"],
                                  "sha256": pr["transcript_sha256"]}
            if "commit_b64" in pr:
                commits[r] = {"commit_b64": pr["commit_b64"], "sig_b64": pr["commit_sig_b64"]}
        return {
            "proto": K.PROTO, "session_id": s["session_id"], "session_nonce": s["nonce_hex"],
            "context": s.get("context"), "not_before": s.get("not_before"), "policy": _policy(s),
            "human": self._human_record(s), "pair_tag": (s.get("human") or {}).get("pair_tag"),
            "attempt": s["attempt"], "verdict": verdict, "reason": reason,
            "user_text": V.USER_TEXT.get(reason) if reason else None,
            "flight_cm": flight, "t0_ms": s["t0_ms"],
            "created_at": _iso(s["created_ms"]), "finished_at": _iso(s["finished_ms"]),
            "devices": devices, "transcripts": transcripts, "commits": commits,
            "zk": self.zk_public(s),
            "attempts": [{k: a.get(k) for k in ("attempt", "outcome", "reason", "by")}
                         | ({"verdict": a["verdict"], "flight_cm": a["flight_cm"]} if a.get("outcome") == "verdict" else {})
                         for a in s["attempts"]],
        }

    @staticmethod
    def _human_record(s: dict) -> dict | None:
        """Full per-role World ID results (proofs included; no raw bodies, no connector_uri)."""
        h = s.get("human")
        if not h:
            return None
        drop = ("raw", "connector_uri", "detail")
        return {**{r: {k: v for k, v in (h.get(r) or {}).items() if k not in drop} for r in ROLES},
                "pair_tag": h.get("pair_tag")}

    def _write(self, sid: str, name: str, data: bytes) -> Path | None:
        if self.data_dir is None:
            return None
        d = self.data_dir / "sessions" / sid
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_bytes(data)
        return d / name

    def _stale(self, s: dict, attempt) -> None:
        if s["state"] in ("confirmed", "started") and _int(attempt) and attempt < s["attempt"]:
            raise PopError(409, "stale_attempt", f"attempt {attempt} already over; current is {s['attempt']}")

    def transcript(self, s: dict, role: str, dev: dict, transcript_b64, sig_b64, meta) -> dict:
        try:
            raw, sig = b64d(transcript_b64), b64d(sig_b64)
        except ValueError:
            raw = sig = None
        if raw is not None:
            try:
                t = decode_transcript(raw)
            except ValueError:
                t = None
            if t is not None and t["attempt"] < s["attempt"] and verify_raw(self._pk(s, role), raw, sig):
                self._stale(s, t["attempt"])
        if s["state"] != "started":
            raise PopError(409, "bad_state", s["state"])
        mine = s["per_role"][role]
        if s["submitted"][role]:
            if mine["transcript_b64"] == transcript_b64 and mine["sig_b64"] == sig_b64:
                return {"accepted": True, "state": s["state"], "attempt": s["attempt"]}
            raise PopError(409, "already_submitted", "")
        if not s["committed"][role]:
            raise PopError(409, "bad_state", "commit first")
        ver = self._popt(s, role)
        try:
            if raw is None:
                raise V.Reject("transcript_mismatch", "bad base64")
            t = V.check_transcript(raw, sig, role=role, pk_self=bytes.fromhex(dev["pubkey"]),
                                   pk_partner=self._pk(s, OTHER[role]), nonce=bytes.fromhex(s["nonce_hex"]),
                                   attempt=s["attempt"], commit_sha256=bytes.fromhex(mine["commit_sha256"]),
                                   rec=bytes.fromhex(mine[REC_KEY[ver]]), sample_rate=mine["sample_rate"],
                                   version=ver, code_commit=self._code_commit(s, role) if ver == 2 else None)
        except V.Reject as e:
            self._finalize(s, "NOT_NEAR", e.reason, None, "rejected", role)
            raise PopError(400, e.reason, e.detail) from None
        meta = meta if isinstance(meta, dict) else {}
        if len(json.dumps(meta)) > 65536:
            meta = {"_dropped": "meta over 64 KiB"}
        mine.update({"transcript_b64": transcript_b64, "sig_b64": sig_b64, "meta": meta,
                     "transcript_sha256": hashlib.sha256(raw).hexdigest(), "half": t["half"],
                     "self_os_delta": t["self_os_delta"], "submitted_ms": self.now_ms()})
        s["submitted"][role] = True
        if not all(s["submitted"].values()):
            self._save(s)
        else:
            ts = {r: decode_transcript(b64d(s["per_role"][r]["transcript_b64"])) for r in ROLES}
            try:
                out = V.combine(ts["A"], ts["B"], {r: s["per_role"][r].get("cal_us", 0) for r in ROLES})
            except V.Reject as e:   # unreachable after check_transcript on both sides; kept as a guard
                self._finalize(s, "NOT_NEAR", e.reason, None, "rejected", None)
                raise PopError(400, e.reason, e.detail) from None
            s["last_flight_cm"] = out["flight_cm"]
            if out["verdict"] is None:
                self._failed(s, out["reason"], out["by"])
            else:
                self._finalize(s, out["verdict"], out["reason"], out["flight_cm"], "verdict", None)
        return {"accepted": True, "state": s["state"], "attempt": s["attempt"]}

    def fail(self, s: dict, role: str, attempt, reason) -> dict:
        if reason not in V.PHONE_REASONS:
            raise PopError(400, "bad_reason", f"one of {sorted(V.PHONE_REASONS)}")
        if not _int(attempt):
            raise PopError(400, "bad_attempt", "")
        self._stale(s, attempt)
        if s["state"] not in ("confirmed", "started"):
            raise PopError(409, "bad_state", s["state"])
        if attempt != s["attempt"]:
            raise PopError(400, "bad_attempt", f"current attempt is {s['attempt']}")
        if s["submitted"][role]:
            raise PopError(409, "already_submitted", "")
        s["per_role"][role]["fail"] = {"reason": reason, "ms": self.now_ms()}
        return self._failed(s, reason, role)

    def result(self, s: dict) -> dict:
        if s["result"] is None:
            raise PopError(404, "no_result", s["state"])
        return s["result"]

    # -- optional recording upload (§9): int16 mono WAV whose frames hash to the committed rec_sha256 (v1)
    #    or build the committed rec_root (v2). Pure CPU for v2; main.py runs it in a worker thread.
    def recording(self, s: dict, role: str, attempt, wav_bytes: bytes, meta) -> dict:
        if not _int(attempt):
            raise PopError(400, "bad_attempt", "")
        pr = s["per_role"][role] if attempt == s["attempt"] else next(
            (a["per_role"][role] for a in s["attempts"] if a["attempt"] == attempt and "per_role" in a), {})
        ver = pr.get("popt", 1)
        want = pr.get(REC_KEY[ver])
        if want is None:
            raise PopError(409, "bad_state", "no commit for that attempt")
        try:
            with wave.open(io.BytesIO(wav_bytes)) as w:
                if w.getsampwidth() != 2 or w.getnchannels() != 1:
                    raise PopError(400, "bad_request", "need int16 mono WAV")
                frames = w.readframes(w.getnframes())
        except (wave.Error, EOFError) as e:
            raise PopError(400, "bad_request", f"wav: {e}") from None
        if ver == 1 and hashlib.sha256(frames).hexdigest() != want:
            raise PopError(400, "transcript_mismatch", "recording sha256 != committed rec_sha256")
        if ver == 2:
            x = np.frombuffer(frames, dtype="<i2")
            if x.size > poseidon2.CAP:
                raise PopError(400, "bad_request", "recording longer than the rec_root tree")
            if poseidon2.to_bytes32(poseidon2.rec_root(x)).hex() != want:
                raise PopError(400, "transcript_mismatch", "recording rec_root != committed rec_root")
        path = self._write(s["session_id"], f"recording_{role}_{attempt}.wav", wav_bytes)
        if path is not None and meta is not None:
            self._write(s["session_id"], f"recording_{role}_{attempt}.json", json.dumps(meta, indent=1).encode())
        return {"ok": True, "stored": path is not None}

    # -- option A proofs (pop/zk.py)
    @staticmethod
    def zk_valid_at(s: dict) -> int | None:
        return None if s["t0_ms"] is None else s["t0_ms"] // 1000

    @staticmethod
    def zk_entry(s: dict, role: str) -> dict | None:
        return (s.get("zk") or {}).get(role)

    def zk_public(self, s: dict) -> dict:
        ent = {r: None if e is None else {k: v for k, v in e.items() if k != "salt"}
               for r in ROLES for e in [self.zk_entry(s, r)]}
        st = [e["status"] for e in ent.values() if e]
        status = ("rejected" if "rejected" in st else "verified" if st.count("verified") == 2
                  else "proving" if "proving" in st else "partial" if st else "none")
        attest = {r: s["per_role"][r].get("code_attest") for r in ROLES if s["per_role"][r].get("code_attest")}
        return {"valid_at": self.zk_valid_at(s), "status": status, **ent, "circuit": zk.CIRCUIT,
                "vk_sha256": zk.VK_PINS[zk.CIRCUIT], "code_attest": attest or None}

    def zk_expected(self, s: dict, role: str, dev: dict, attempt, circuit, salt: int, issuer_pub: bytes) -> list[int]:
        """The public vector a proof by `role` must carry. PopError = wrong moment/request; V.Reject = the proof's
        credential can't pass (recorded like a failed proof)."""
        if s["state"] != "done" or (s["result"] or {}).get("verdict") != "NEAR":
            raise PopError(409, "bad_state", "proofs are taken after a NEAR verdict")
        if not _int(attempt) or attempt != s["attempt"]:
            raise PopError(400, "bad_attempt", f"the verdict is from attempt {s['attempt']}")
        pr = s["per_role"][role]
        if pr.get("popt", 1) != 2 or "transcript_b64" not in pr:
            raise PopError(409, "bad_state", "no POPT v2 transcript for this role")
        sr = pr["sample_rate"]
        if sr not in zk.CIRCUITS:
            raise PopError(409, "bad_state", f"no circuit at {sr} Hz (only {sorted(zk.CIRCUITS)} are provable)")
        if circuit != zk.CIRCUITS[sr]:
            raise V.Reject("circuit_unknown", f"{circuit!r}: the {sr} Hz circuit is {zk.CIRCUITS[sr]}")
        d = self.store.get_device(dev["device_id"])
        if not d or not d.get("cred"):
            raise PopError(409, "no_credential", "enroll with holder_commit to get an SBcred3")
        valid_at = self.zk_valid_at(s)
        try:
            c = sbcred.check(bytes.fromhex(d["cred"]), bytes.fromhex(d["cred_sig"]), issuer_pub, valid_at)
        except sbcred.CredError as e:
            raise V.Reject(e.code, e.detail) from None
        t = decode_transcript(b64d(pr["transcript_b64"]))
        if c["pub"] != t["pk_self"]:
            raise V.Reject("transcript_mismatch", "credential key != transcript key")
        other = OTHER[role]
        return zk.public_vector(t, popt2.code(self._key(s, role), role, sr), popt2.code(self._key(s, other), other, sr),
                                issuer_pub, valid_at, salt)

    def zk_record(self, session_id: str, role: str, entry: dict, proof: bytes | None = None,
                  public: list[int] | None = None) -> dict:
        """Store one proof outcome (reloads: verification ran off the event loop). A verified proof is written next
        to result.json as proof_<role>_<attempt>.bin (bb `proof`, 10,304 B) + public_inputs_<role>_<attempt>.bin
        (12 x 32 B); entry["files"] has their paths relative to the data dir, entry["public_inputs"] the hex values."""
        s = self.load(session_id)
        if proof is not None and public is not None:
            names = {"proof": f"proof_{role}_{entry['attempt']}.bin",
                     "public_inputs": f"public_inputs_{role}_{entry['attempt']}.bin"}
            p1 = self._write(s["session_id"], names["proof"], proof)
            self._write(s["session_id"], names["public_inputs"], zk.to_file(public))
            if self.code_attester is not None:   # the issuer vouches for public input #5 of this very proof
                entry = {**entry, "code_attest": self.code_attester(bytes.fromhex(s["nonce_hex"]), entry["attempt"],
                                                                    role, zk.to_file([public[4]]))}
            entry = {**entry, "public_inputs": zk.hexes(public),
                     "files": None if p1 is None else {k: f"sessions/{s['session_id']}/{v}" for k, v in names.items()}}
        s.setdefault("zk", {"A": None, "B": None})[role] = entry
        if s["result"] is not None:
            s["result"]["zk"] = self.zk_public(s)
            self._write(s["session_id"], "result.json", json.dumps(s["result"], indent=1).encode())
        self._save(s)
        return s

    # -- view (§9)
    def view(self, s: dict, role: str) -> dict:
        me_id = s["host_device_id"] if role == "A" else s["guest_device_id"]
        other_id = s["guest_device_id"] if role == "A" else s["host_device_id"]
        me = self.store.get_device(me_id)
        other = self.store.get_device(other_id) if other_id else None
        # World ID sessions show the nonce to members from create/join (01 §9 row 3); plain sessions keep
        # the v1 rule (the app treats nonce != null as "both confirmed").
        shown = all(s["confirmed"].values()) or _policy(s)["human"] == "worldid"
        return {
            "session_id": s["session_id"], "seq": s["seq"], "state": s["state"], "attempt": s["attempt"],
            "role": role,
            "nonce": s["nonce_hex"] if shown else None,
            "context": s.get("context"), "not_before": s.get("not_before"), "policy": _policy(s),
            "human": H.public_status(s.get("human")),
            "self": {"device_id": me["device_id"], "display_name": me["display_name"], "pubkey": me["pubkey"],
                     "cal_us": me.get("cal_us") or 0, "calibration": CAL.public(me)},
            "partner": None if other is None else {
                "device_id": other["device_id"], "display_name": other["display_name"], "model": other["model"],
                "attested": other["attested"], "security_level": other["security_level"], "pubkey": other["pubkey"],
                "cal_us": other.get("cal_us") or 0},
            "confirmed": dict(s["confirmed"]), "armed": dict(s["armed"]),
            "committed": dict(s["committed"]), "submitted": dict(s["submitted"]),
            "popt": {r: s["per_role"][r].get("popt") for r in ROLES},
            "t0_ms": s["t0_ms"],
            "zk_valid_at": self.zk_valid_at(s),
            "constants": {"a_play_s": K.A_PLAY_S, "b_play_s": K.B_PLAY_S, "lead_s": K.LEAD_S, "capture_s": K.CAPTURE_S},
            "result": s["result"],
            "error": s["error"],
            "last_failure": s.get("last_failure"),
        }
