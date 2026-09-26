"""World ID gate (worldid 01 §6.2-§6.10, §7.2, §9 rows 4/5/7).

Per role, s["human"][role]["status"]:
  idle -start-> requested -waiting_for_connection-> waiting -awaiting_confirmation-> awaiting
  -confirmed-> verifying (nullifier reserved, raw result persisted, Portal call in flight) -ok-> verified
  any -failed(code) | expired (300 s) | same_human-> failed -start-> requested (new rp_context, same action)

One request per role serves "This phone" (open connector_uri) and "Other phone" (QR). The IDKit sidecar
(server/idkit-sidecar/, node) creates the request and polls the bridge; this module signs rp_context,
polls the sidecar (a background task per role, plus the status long-poll, so a restart resumes), runs
verify() (§6.4) and keeps the nullifier table (§6.5, the only replay guard: the Portal answers 200 on reuse).

Concurrency (§6.4): sessions are whole-doc read-modify-write with no lock. Never hold a loaded session
across an await: re-load after every await, change only s["human"], save, all without awaiting.
One uvicorn worker. Polls of one (sid, role) are serialized by an asyncio.Lock.

Fake mode (POP_WORLDID_FAKE=1, needs POP_TEST_KINDS=1, §6.10): step 8 makes no network call and stores
environment "fake"; everything else runs unchanged.

Sandbox per role (POP_WORLDID_SANDBOX=1): POST /worldid/start {"env": "sandbox"} builds the request with IDKit
environment "staging"; the phone opens it in the World ID Simulator (connector_uri is the simulator link). Polling
runs as in production; on "confirmed" the nullifier is taken from the bridge result (else
sha256("pop-mock-v1" || device_id || session_id)) with no Portal verify, environment "sandbox". Only in a session
whose context is absent or kind "test". The nullifier table is keyed by env, so sandbox never meets production.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import sqlite3
import time
import urllib.parse
from typing import Any, Callable

import httpx

from pop import popctx, worldid_rp
from pop.errors import PopError

log = logging.getLogger("pop")

ROLES = ("A", "B")
REQUEST_TTL_S = 300          # rp_context TTL; a request older than this is human_expired
REUSE_S = 240                # /worldid/start reuses a live request younger than this
PENDING = ("requested", "waiting", "awaiting")
BRIDGE = {"waiting_for_connection": "waiting", "awaiting_confirmation": "awaiting"}
PORTAL_BACKOFF = (0.5, 1.0, 2.0)
FAKE_BANNER = "*** FAKE WORLD ID: TEST IDENTITIES, NO REAL HUMANS ***"
SANDBOX_ENV = "sandbox"
SIMULATOR = "https://simulator.worldcoin.org/?connect_url="

_SCHEMA = """
CREATE TABLE IF NOT EXISTS wid_nullifiers (
  rp_id TEXT NOT NULL, action TEXT NOT NULL, nullifier TEXT NOT NULL,
  env TEXT NOT NULL, kind TEXT NOT NULL, subject TEXT NOT NULL, created_at INTEGER NOT NULL,
  PRIMARY KEY (rp_id, env, action, nullifier));
"""


class HumanError(Exception):
    def __init__(self, status: int, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.status, self.code, self.detail = status, code, detail


def empty_human() -> dict:
    return {"A": {"status": "idle", "issued_nonces": []}, "B": {"status": "idle", "issued_nonces": []},
            "pair_tag": None}


def pair_tag(n_a: str, n_b: str) -> str:
    """§6.6: sha256("pop-pair-v1" || lo || hi), numerically sorted 32-byte BE."""
    lo, hi = sorted((int(n_a, 16), int(n_b, 16)))
    return "0x" + hashlib.sha256(b"pop-pair-v1" + lo.to_bytes(32, "big") + hi.to_bytes(32, "big")).hexdigest()


def canon_field(x: Any) -> str:
    if isinstance(x, int) and not isinstance(x, bool):
        v = x
    elif isinstance(x, str):
        v = int(x, 16) if x[:2].lower() == "0x" else int(x, 10)
    else:
        raise ValueError("not a field element")
    if not 0 <= v < 1 << 256:
        raise ValueError("out of range")
    return "0x%064x" % v


def expected_signal_hash(nonce_hex: str, role: str) -> str:
    return popctx.signal_hash_hex(popctx.signal(bytes.fromhex(nonce_hex), role))


def public_status(h: dict | None) -> dict | None:
    """The view's human block: status (+ error) per role and pair_tag; no proofs."""
    if h is None:
        return None
    out: dict = {"pair_tag": h.get("pair_tag")}
    for r in ROLES:
        e = h.get(r) or {}
        out[r] = ({"status": e.get("status", "idle")} | ({"error": e["error"]} if e.get("error") else {})
                  | ({"env": SANDBOX_ENV} if e.get("sandbox") else {}))
    return out


def mock_nullifier(device_id: str, session_id: str) -> str:
    return "0x" + hashlib.sha256(b"pop-mock-v1" + device_id.encode() + session_id.encode()).hexdigest()


def both_verified(h: dict | None) -> bool:
    if not h:
        return False
    a, b = h.get("A") or {}, h.get("B") or {}
    return (a.get("status") == b.get("status") == "verified" and a.get("nullifier") and b.get("nullifier")
            and a["nullifier"] != b["nullifier"])


class Nullifiers:
    """wid_nullifiers in the server's sqlite (created here; store.py is unchanged)."""

    def __init__(self, store):
        self.db, self.lock = store._db, store._lock
        with self.lock:
            self.db.executescript(_SCHEMA)

    def reserve(self, rp_id: str, env: str, action: str, nullifier: str, subject: str, now_s: int) -> str | None:
        """Insert-or-conflict in one step. None = inserted; else the subject already holding it."""
        with self.lock:
            try:
                self.db.execute("INSERT INTO wid_nullifiers VALUES (?,?,?,?,?,?,?)",
                                (rp_id, action, nullifier, env, "session", subject, now_s))
                return None
            except sqlite3.IntegrityError:
                row = self.db.execute("SELECT subject FROM wid_nullifiers WHERE rp_id=? AND env=? AND action=? "
                                      "AND nullifier=?", (rp_id, env, action, nullifier)).fetchone()
                return row["subject"]

    def release(self, rp_id: str, env: str, action: str, nullifier: str, subject: str) -> None:
        with self.lock:
            self.db.execute("DELETE FROM wid_nullifiers WHERE rp_id=? AND env=? AND action=? AND nullifier=? "
                            "AND subject=?", (rp_id, env, action, nullifier, subject))

    def rows(self) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM wid_nullifiers")]


class WorldID:
    """Everything World ID on the server. `sessions` is pop.sessions.Sessions (load/_save)."""

    def __init__(self, cfg, sessions, store, transport: httpx.AsyncBaseTransport | None = None,
                 sleep: Callable[[float], Any] = asyncio.sleep):
        self.cfg, self.sessions, self.sleep = cfg, sessions, sleep
        self.fake = bool(cfg.worldid_fake)
        self.rp_id = cfg.worldid_rp_id or ("rp_fake" if self.fake else None)
        self.app_id = cfg.worldid_app_id or ("app_fake" if self.fake else None)
        self.env = "fake" if self.fake else cfg.worldid_env
        self.key = None
        if self.rp_id:
            try:
                self.key = worldid_rp.load_key(cfg.worldid_signing_key_file, cfg.worldid_signing_key, self.fake)
            except (OSError, ValueError) as e:
                log.error("worldid: signing key unusable: %s", type(e).__name__)
        if self.rp_id and not self.key:
            log.error("worldid: no RP signing key (POP_WORLDID_SIGNING_KEY_FILE); /worldid/start answers 503")
        self.enabled = bool(self.rp_id and self.key and self.app_id)
        self.nullifiers = Nullifiers(store)
        self.http = httpx.AsyncClient(transport=transport, timeout=10)
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._last_poll: dict[tuple[str, str], float] = {}
        self._tasks: dict[tuple[str, str], asyncio.Task] = {}
        self._rp_status: tuple[float, Any] = (0.0, None)
        if self.fake:
            log.warning(FAKE_BANNER)

    # -- helpers
    def now_s(self) -> int:
        return self.cfg.now_ms() // 1000

    def _lock(self, sid: str, role: str) -> asyncio.Lock:
        return self._locks.setdefault((sid, role), asyncio.Lock())

    def _set(self, sid: str, role: str, **fields) -> dict:
        """Re-load, merge into s["human"][role], save. No await inside."""
        s = self.sessions.load(sid)
        h = s["human"][role]
        h.update(fields)
        if h.get("status") != "failed":
            h.pop("error", None)
        self.sessions._save(s)
        return s

    def _log(self, sid: str, role: str, status: str, nullifier: str | None = None, start_s: int | None = None):
        ms = None if start_s is None else self.cfg.now_ms() - start_s * 1000
        log.info("worldid %s %s %s %s %s", sid, role, status, (nullifier or "-")[:10], ms)

    @staticmethod
    def require_policy(s: dict) -> None:
        if (s.get("policy") or {}).get("human") != "worldid" or not s.get("human"):
            raise PopError(409, "bad_state", "this session has no World ID policy")

    def _expired(self, h: dict) -> bool:
        return h.get("status") in PENDING and self.now_s() - (h.get("request_created_s") or 0) > REQUEST_TTL_S

    # -- start (§9 row 4)
    async def start(self, s: dict, role: str, env: str | None = None) -> dict:
        self.require_policy(s)
        sandbox = env == SANDBOX_ENV
        if env not in (None, "production", SANDBOX_ENV):
            raise PopError(400, "bad_request", "env must be production|sandbox")
        if sandbox and (not self.cfg.worldid_sandbox
                        or (s.get("context") is not None and (s.get("context") or {}).get("kind") != "test")):
            raise PopError(403, "sandbox_not_allowed", "sandbox World ID needs POP_WORLDID_SANDBOX=1 and a test session")
        if not self.enabled:
            raise PopError(503, "worldid_unavailable", "World ID is not configured on this server")
        sid = s["session_id"]
        if s["guest_device_id"] is None:
            raise PopError(409, "not_joined", "the guest has not joined yet")
        if s["state"] not in ("joined", "confirmed"):
            raise PopError(409, "bad_state", s["state"])
        h = s["human"][role]
        if h["status"] == "verified":
            raise PopError(409, "already_verified", "")
        if h["status"] == "verifying":
            raise PopError(409, "bad_state", "verifying")
        now = self.now_s()
        if (h["status"] in PENDING and now - h.get("request_created_s", 0) < REUSE_S and h.get("connector_uri")
                and bool(h.get("sandbox")) == sandbox):
            self._spawn(sid, role)
            return self._start_out(h)
        action = popctx.action(sid)
        rp = worldid_rp.sign_request(self.key, action=action, ttl=REQUEST_TTL_S, now=now)
        rp_context = {"rp_id": self.rp_id, "nonce": rp["nonce"], "created_at": rp["created_at"],
                      "expires_at": rp["expires_at"], "signature": rp["sig"]}
        body = {"app_id": self.app_id, "action": action, "signal": popctx.signal_str(bytes.fromhex(s["nonce_hex"]), role),
                "rp_context": rp_context,
                "environment": "staging" if sandbox else "production" if self.fake else self.env,
                "return_to": self.cfg.worldid_return_to}
        # the nonce counts as issued before the await: a proof for it must never be refused as unknown
        s = self.sessions.load(sid)
        s["human"][role].setdefault("issued_nonces", []).append(rp["nonce"])
        self.sessions._save(s)
        try:
            r = await self.http.post(self.cfg.worldid_sidecar.rstrip("/") + "/requests", json=body)
            out = r.json() if r.status_code == 200 else None
            if not (isinstance(out, dict) and out.get("request_id") and out.get("connector_uri")):
                raise ValueError(f"sidecar {r.status_code}")
        except (httpx.HTTPError, ValueError) as e:
            log.warning("worldid %s %s: sidecar create failed: %s", sid, role, e)
            raise PopError(503, "worldid_unavailable", "IDKit sidecar unreachable") from None
        s = self.sessions.load(sid)
        h = s["human"][role]
        if h["status"] in ("verified", "verifying"):
            raise PopError(409, "already_verified" if h["status"] == "verified" else "bad_state", "")
        uri = SIMULATOR + urllib.parse.quote(out["connector_uri"], safe="") if sandbox else out["connector_uri"]
        h.update({"status": "requested", "request_id": out["request_id"], "connector_uri": uri,
                  "request_created_s": now, "rp_nonce": rp["nonce"], "sandbox": sandbox})
        h.pop("error", None)
        self.sessions._save(s)
        self._log(sid, role, "requested", start_s=now)
        self._spawn(sid, role)
        return self._start_out(h)

    @staticmethod
    def _start_out(h: dict) -> dict:
        return {"request_id": h["request_id"], "connector_uri": h["connector_uri"],
                "expires_at_s": h["request_created_s"] + REQUEST_TTL_S, "status": h["status"]}

    # -- polling
    def _spawn(self, sid: str, role: str) -> None:
        if not self.cfg.worldid_bg_poll:
            return
        t = self._tasks.get((sid, role))
        if t is not None and not t.done():
            return
        try:
            self._tasks[(sid, role)] = asyncio.get_running_loop().create_task(self._poll_loop(sid, role))
        except RuntimeError:
            pass

    async def _poll_loop(self, sid: str, role: str) -> None:
        try:
            while True:
                await self.sleep(self.cfg.worldid_poll_s)
                st = await self.poll_once(sid, role, force=True)
                if st not in PENDING:
                    return
        except PopError:
            return
        except Exception:   # never let a background task die silently
            log.exception("worldid poll %s %s", sid, role)

    async def poll_once(self, sid: str, role: str, force: bool = False) -> str:
        """One sidecar poll for a pending role (rate-limited to worldid_poll_s unless force). Returns the status."""
        async with self._lock(sid, role):
            s = self.sessions.load(sid)
            if not s.get("human"):
                return "idle"
            h = s["human"][role]
            if h["status"] == "verifying" and h.get("raw") is not None:
                # a crash or restart between step 7 and step 9: re-run with the persisted result (we hold the lock)
                try:
                    await self.verify(sid, role, h["raw"])
                    return "verified"
                except HumanError:
                    return "failed"
            if h["status"] not in PENDING:
                return h["status"]
            if s["state"] in ("done", "aborted"):
                return h["status"]
            if self._expired(h):
                self._set(sid, role, status="failed", error="human_expired")
                self._log(sid, role, "failed:human_expired", start_s=h.get("request_created_s"))
                return "failed"
            key, mono = (sid, role), time.monotonic()
            if not force and mono - self._last_poll.get(key, 0.0) < self.cfg.worldid_poll_s:
                return h["status"]
            self._last_poll[key] = mono
            rid = h["request_id"]
            try:
                r = await self.http.get(f"{self.cfg.worldid_sidecar.rstrip('/')}/requests/{rid}")
                out = r.json()
            except (httpx.HTTPError, ValueError) as e:
                log.warning("worldid %s %s: sidecar poll failed: %s", sid, role, e)
                return h["status"]
            if r.status_code == 404:        # sidecar restarted and lost the request: the phone must start again
                s = self._set(sid, role, status="failed", error="worldid_unavailable")
                return "failed"
            if r.status_code != 200 or not isinstance(out, dict):
                return h["status"]
            s = self.sessions.load(sid)
            h = s["human"][role]
            if h.get("request_id") != rid or h["status"] not in PENDING:
                return h["status"]           # replaced or finished meanwhile
            st = out.get("status")
            if st in BRIDGE:
                if h["status"] != BRIDGE[st]:
                    self._set(sid, role, status=BRIDGE[st])
                    self._log(sid, role, BRIDGE[st], start_s=h.get("request_created_s"))
                return BRIDGE[st]
            if st == "failed":
                err = str(out.get("error") or "failed")[:64]
                self._set(sid, role, status="failed", error=err)
                self._log(sid, role, "failed:" + err, start_s=h.get("request_created_s"))
                return "failed"
            if st == "confirmed" and h.get("sandbox"):
                return self._accept_sandbox(sid, role, out.get("result"))
            if st == "confirmed":
                try:
                    await self.verify(sid, role, out.get("result"))
                    return "verified"
                except HumanError:
                    return "failed"
            return h["status"]

    # -- sandbox (no verification)
    def _accept_sandbox(self, sid: str, role: str, res: Any) -> str:
        """Simulator proof: take its nullifier as is (or the mock one), no Portal, no chain. No await inside."""
        s = self.sessions.load(sid)
        h = s["human"][role]
        try:
            nullifier = canon_field(res["responses"][0]["nullifier"])
        except (KeyError, IndexError, TypeError, ValueError):
            dev = s["host_device_id"] if role == "A" else s["guest_device_id"]
            nullifier = mock_nullifier(dev or "", sid)
        action = popctx.action(sid)
        subject = f"{sid}:{role}"
        holder = self.nullifiers.reserve(self.rp_id, SANDBOX_ENV, action, nullifier, subject, self.now_s())
        if holder is not None and holder != subject:
            self._set(sid, role, status="failed", error="same_human")
            self._log(sid, role, "failed:same_human")
            return "failed"
        h.pop("error", None)
        h.update({"status": "verified", "nullifier": nullifier, "action": action, "environment": SANDBOX_ENV,
                  "verified_at": self.now_s()})
        if both_verified(s["human"]):
            s["human"]["pair_tag"] = pair_tag(s["human"]["A"]["nullifier"], s["human"]["B"]["nullifier"])
        self.sessions._save(s)
        log.warning("worldid %s %s verified SANDBOX (simulator, not verified)", sid, role)
        return "verified"

    # -- verify (§6.4)
    async def verify(self, sid: str, role: str, res: Any) -> dict:
        """Runs steps 1-9; on failure records status failed + code on the role and raises HumanError."""
        try:
            return await self._verify(sid, role, res)
        except HumanError as e:
            s = self.sessions.load(sid)
            if s["human"][role].get("status") != "verified":
                self._set(sid, role, status="failed", error=e.code, detail=e.detail[:200])
            self._log(sid, role, "failed:" + e.code)
            raise

    async def _verify(self, sid: str, role: str, res: Any) -> dict:
        if self.fake:
            log.warning(FAKE_BANNER)
        s = self.sessions.load(sid)
        h = s["human"][role]
        if h["status"] == "verified":
            return h
        subject = f"{sid}:{role}"
        action = popctx.action(sid)
        # 1. exactly one response
        if not isinstance(res, dict) or not isinstance(res.get("responses"), list) or len(res["responses"]) != 1 \
                or not isinstance(res["responses"][0], dict):
            raise HumanError(400, "human_invalid", "need exactly one response")
        r0 = res["responses"][0]
        # 2. action
        if res.get("action") != action:
            raise HumanError(400, "human_invalid", "action mismatch")
        # 3. nonce we issued for this role
        issued = h.get("issued_nonces") or []
        try:
            rp_nonce = canon_field(res.get("nonce"))
        except (ValueError, TypeError):
            raise HumanError(400, "human_invalid", "bad nonce") from None
        if rp_nonce not in issued:
            raise HumanError(400, "human_invalid", "nonce was not issued for this role")
        # 4. Proof of Human only, read from the request body (the Portal does not echo it)
        legacy = self.cfg.worldid_allow_legacy and r0.get("identifier") == "orb"
        if not legacy and (r0.get("identifier") != "proof_of_human" or r0.get("issuer_schema_id") != 1):
            raise HumanError(400, "human_level", f"identifier={r0.get('identifier')!r} "
                                                 f"issuer_schema_id={r0.get('issuer_schema_id')!r}")
        env = res.get("environment")
        if not self.fake and env not in (None, self.env):
            raise HumanError(400, "human_invalid", f"environment {env!r}")
        # 5. signal: recompute, compare if present, overwrite (the Portal does not recompute it)
        want = expected_signal_hash(s["nonce_hex"], role)
        if r0.get("signal_hash") is not None:
            try:
                got = canon_field(r0["signal_hash"])
            except (ValueError, TypeError):
                got = None
            if got != want:
                raise HumanError(400, "human_invalid", "signal_hash mismatch")
        r0 = {**r0, "signal_hash": want}
        body = {**res, "responses": [r0]}
        try:
            nullifier = canon_field(r0.get("nullifier"))
        except (ValueError, TypeError):
            raise HumanError(400, "human_invalid", "bad nullifier") from None
        # 6. reserve the nullifier (sync insert, no await between check and insert)
        holder = self.nullifiers.reserve(self.rp_id, self.env, action, nullifier, subject, self.now_s())
        if holder is not None and holder != subject:
            raise HumanError(409, "same_human", "both roles used the same World ID")
        # 7. persist the raw result before the Portal call
        self._set(sid, role, status="verifying", raw=body, nullifier=nullifier)
        self._log(sid, role, "verifying", nullifier, h.get("request_created_s"))
        # 8. environment
        try:
            if self.fake:
                out_env = "fake"
            else:
                out_env = await self._portal(body)
        except HumanError:
            self.nullifiers.release(self.rp_id, self.env, action, nullifier, subject)
            raise
        # 9. store
        s = self.sessions.load(sid)
        hr = s["human"][role]
        hr.pop("raw", None)
        hr.pop("error", None)
        hr.pop("detail", None)
        hr.update({"status": "verified", "nullifier": nullifier, "signal_hash": want, "action": action,
                   "environment": out_env, "issuer_schema_id": r0.get("issuer_schema_id"),
                   "expires_at_min": r0.get("expires_at_min"), "rp_nonce": rp_nonce,
                   "proof": [str(x) for x in (r0.get("proof") or [])], "verified_at": self.now_s()})
        if both_verified(s["human"]):
            s["human"]["pair_tag"] = pair_tag(s["human"]["A"]["nullifier"], s["human"]["B"]["nullifier"])
        self.sessions._save(s)
        self._log(sid, role, "verified", nullifier, hr.get("request_created_s"))
        return hr

    async def _portal(self, body: dict) -> str:
        url = f"{self.cfg.worldid_portal.rstrip('/')}/api/v4/verify/{self.rp_id}"
        last = "unreachable"
        for i in range(len(PORTAL_BACKOFF) + 1):
            try:
                r = await self.http.post(url, json=body)
            except httpx.HTTPError as e:
                last = type(e).__name__
            else:
                try:
                    out = r.json()
                except ValueError:
                    out = None
                if r.status_code < 500:
                    if r.status_code == 200 and isinstance(out, dict) and out.get("success") is True:
                        if out.get("environment") != "production" or self.env != "production":
                            raise HumanError(400, "human_invalid", f"portal environment {out.get('environment')!r}")
                        return "production"
                    code = out.get("code") if isinstance(out, dict) else None
                    log.warning("worldid portal %d %s", r.status_code, str(out)[:300])
                    raise HumanError(400, "human_invalid", f"portal {r.status_code} {code or ''}".strip())
                last = f"portal {r.status_code}"
            if i < len(PORTAL_BACKOFF):
                await self.sleep(PORTAL_BACKOFF[i])
        raise HumanError(400, "human_invalid", last)

    # -- status long-poll (§9 row 5)
    async def status(self, sid: str, role: str, timeout_s: float) -> dict:
        s = self.sessions.load(sid)
        self.require_policy(s)
        initial = s["human"][role]["status"]
        deadline = time.monotonic() + max(0.0, min(timeout_s, 25.0))
        while True:
            if initial in PENDING or initial == "verifying":
                self._spawn(sid, role)
                await self.poll_once(sid, role)
            s = self.sessions.load(sid)
            h = s["human"][role]
            if h["status"] != initial or h["status"] not in PENDING or time.monotonic() >= deadline:
                break
            await asyncio.sleep(0.2)
        other = s["human"]["B" if role == "A" else "A"]
        out = {"role": role, "status": h["status"], "error": h.get("error"),
               "partner": {"status": other.get("status", "idle")}, "pair_tag": s["human"].get("pair_tag")}
        if h["status"] in PENDING:
            out.update({"request_id": h.get("request_id"), "connector_uri": h.get("connector_uri"),
                        "expires_at_s": h.get("request_created_s", 0) + REQUEST_TTL_S})
        return out

    # -- health / config
    def config(self) -> dict:
        return {"app_id": self.app_id, "rp_id": self.rp_id, "environment": self.env, "fake": self.fake,
                "enabled": self.enabled}

    async def health(self) -> dict:
        if not self.enabled:
            return {"enabled": False, "fake": self.fake}
        out = {"enabled": True, "fake": self.fake, "rp_id": self.rp_id}
        try:
            r = await self.http.get(self.cfg.worldid_sidecar.rstrip("/") + "/health", timeout=1.0)
            out["sidecar_ok"] = r.status_code == 200 and r.json().get("ok") is True
            out["sidecar"] = r.json().get("idkit")
        except (httpx.HTTPError, ValueError, AttributeError):
            out["sidecar_ok"] = False
        if not self.fake:
            t, v = self._rp_status
            if time.monotonic() - t > 60 or v is None:
                try:
                    r = await self.http.get(f"{self.cfg.worldid_portal.rstrip('/')}/api/v4/rp-status/{self.rp_id}",
                                            timeout=3.0)
                    v = r.json().get("production_status") if r.status_code == 200 else f"http {r.status_code}"
                except (httpx.HTTPError, ValueError, AttributeError):
                    v = "unreachable"
                self._rp_status = (time.monotonic(), v)
            out["rp_status"] = v
        return out
