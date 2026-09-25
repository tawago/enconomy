"""pop-v1 server: enrollment, signed-request auth, pairing, arm/start, commit (contract §2-§5, §9).

Run: uv run python -m pop            (0.0.0.0:8000)
 or: uv run uvicorn --factory pop.main:create_app --host 0.0.0.0 --port 8000

Env: POP_DB (default data/pop.sqlite), POP_ALLOW_UNATTESTED=1, POP_GAIN_DB (0), POP_UPLOAD_RECORDINGS (1).
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from pop import constants as K
from pop.attestation import AttestationError, verify_chain
from pop.auth import Authenticator
from pop.crypto import device_id as derive_device_id, load_pub
from pop.errors import PopError
from pop.sessions import Sessions
from pop.store import SqliteStore, Store

SERVER_DIR = Path(__file__).resolve().parents[1]
SECURITY_LEVELS = {"strongbox", "tee", "software", "unknown"}
HEX = re.compile(r"^[0-9a-f]*$")

log = logging.getLogger("pop")
if not log.handlers:
    log.setLevel(logging.INFO)
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(_h)


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


def wall_ms() -> int:
    return time.time_ns() // 1_000_000


@dataclass
class Settings:
    db: str = field(default_factory=lambda: os.environ.get("POP_DB", str(SERVER_DIR / "data" / "pop.sqlite")))
    allow_unattested: bool = field(default_factory=lambda: _env_bool("POP_ALLOW_UNATTESTED", False))
    gain_db: float = field(default_factory=lambda: float(os.environ.get("POP_GAIN_DB", "0")))
    upload_recordings: bool = field(default_factory=lambda: _env_bool("POP_UPLOAD_RECORDINGS", True))
    now_ms: Callable[[], int] = wall_ms


def _hex(s: str, nbytes: int) -> bytes | None:
    s = s.lower() if isinstance(s, str) else ""
    if len(s) != 2 * nbytes or not HEX.match(s):
        return None
    return bytes.fromhex(s)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="milliseconds")


class EnrollIn(BaseModel):
    nonce: str
    device_id: str
    pubkey: str
    display_name: str
    model: str = ""
    security_level: str = "unknown"
    chain: list[str] | None = None


class JoinIn(BaseModel):
    join_token: str


class ArmIn(BaseModel):
    attempt: Any = None
    sample_rate: Any = None
    rtt_min_ms: Any = None


class CommitIn(BaseModel):
    commit_b64: str
    sig_b64: str


def create_app(settings: Settings | None = None, store: Store | None = None) -> FastAPI:
    cfg = settings or Settings()
    db = store or SqliteStore(cfg.db)
    auth = Authenticator(db, cfg.now_ms)
    sessions = Sessions(db, cfg.now_ms, cfg.gain_db)

    app = FastAPI(title="pop-v1")
    app.state.cfg, app.state.store, app.state.sessions = cfg, db, sessions

    @app.exception_handler(PopError)
    async def _pop_error(_req, e: PopError):
        return JSONResponse({"error": e.code, "detail": e.detail}, status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def _bad_request(_req, e: RequestValidationError):
        return JSONResponse({"error": "bad_request", "detail": str(e.errors())[:500]}, status_code=400)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_req, e: StarletteHTTPException):
        return JSONResponse({"error": "not_found" if e.status_code == 404 else "http_error", "detail": str(e.detail)},
                            status_code=e.status_code)

    @app.middleware("http")
    async def _log(request: Request, call_next):
        t = time.monotonic()
        resp = await call_next(request)
        log.info("%s %s %s -> %d (%.0fms) dev=%s", request.client.host if request.client else "?", request.method,
                 request.url.path, resp.status_code, (time.monotonic() - t) * 1000,
                 request.headers.get("x-pop-device", "-"))
        return resp

    async def device(request: Request) -> dict:
        body = await request.body()
        path = request.scope.get("raw_path", request.url.path.encode()).decode("latin-1")
        qs = request.scope.get("query_string", b"").decode("latin-1")
        return auth.check(request.method, path + ("?" + qs if qs else ""), body, request.headers)

    # -- public
    @app.get("/health")
    @app.get("/v1/health")
    async def health():
        return {"ok": True, "proto": K.PROTO, "server_ms": cfg.now_ms(), "allow_unattested": cfg.allow_unattested}

    @app.get("/v1/time")
    async def server_time():
        return {"server_ms": cfg.now_ms()}

    @app.get("/v1/config")
    async def config():
        return {**K.table(), "allow_unattested": cfg.allow_unattested, "gain_db": cfg.gain_db,
                "upload_recordings": cfg.upload_recordings}

    # -- enrollment (§2.2)
    @app.get("/v1/enroll/nonce")
    async def enroll_nonce():
        n = secrets.token_hex(32)
        exp = cfg.now_ms() + K.ENROLL_NONCE_TTL_S * 1000
        db.add_nonce(n, exp)
        return {"nonce": n, "expires_at_ms": exp}

    @app.post("/v1/enroll")
    async def enroll(req: EnrollIn):
        nonce = _hex(req.nonce, 32)
        if nonce is None or not db.take_nonce(nonce.hex(), cfg.now_ms()):
            raise PopError(400, "enroll_bad_nonce", "unknown, used or expired nonce")
        pub = _hex(req.pubkey, 65)
        try:
            if pub is None:
                raise ValueError("pubkey must be hex65")
            load_pub(pub)
        except ValueError as e:
            raise PopError(400, "enroll_key_mismatch", str(e)) from None
        dev_id = derive_device_id(pub)
        if req.device_id.lower() != dev_id:
            raise PopError(400, "enroll_key_mismatch", "device_id != sha256(pubkey)[:16]")
        name = req.display_name.strip()
        if not 1 <= len(name) <= 32:
            raise PopError(400, "bad_request", "display_name must be 1..32 chars")
        reported = req.security_level if req.security_level in SECURITY_LEVELS else "unknown"
        if req.chain is None:
            if not cfg.allow_unattested:
                raise PopError(400, "enroll_bad_chain", "chain required (POP_ALLOW_UNATTESTED is off)")
            att = {"security_level": reported, "chain_pem": None, "root_sha256": None}
            attested = False
        else:
            try:
                att = verify_chain(req.chain, pub, nonce)
            except AttestationError as e:
                raise PopError(400, e.code, e.detail) from None
            attested = True
            if att["security_level"] != reported:
                log.warning("enroll %s: reported security_level=%s, attestation says %s", dev_id, reported, att["security_level"])
        now = cfg.now_ms()
        db.put_device({"device_id": dev_id, "pubkey": pub.hex(), "display_name": name, "model": req.model[:64],
                       "security_level": att["security_level"], "security_level_reported": reported,
                       "attested": attested, "chain_pem": att["chain_pem"], "root_sha256": att["root_sha256"],
                       "enrolled_at": _iso(now)})
        log.info("enrolled %s %r model=%r attested=%s level=%s", dev_id, name, req.model, attested, att["security_level"])
        return {"device_id": dev_id, "attested": attested, "security_level": att["security_level"],
                "enrolled_at": _iso(now)}

    # -- pairing (§3)
    @app.post("/v1/session")
    async def create_session(dev: dict = Depends(device)):
        return sessions.create(dev)

    @app.post("/v1/session/{sid}/join")
    async def join(sid: str, req: JoinIn, dev: dict = Depends(device)):
        s = sessions.join(sid, dev, req.join_token)
        return sessions.view(s, "B")

    @app.get("/v1/session/{sid}")
    async def get_session(sid: str, after: int = -1, timeout_s: float = 0, dev: dict = Depends(device)):
        s = sessions.load(sid)
        role = sessions.member(s, dev)
        deadline = time.monotonic() + max(0.0, min(timeout_s, K.LONGPOLL_MAX_S))
        while s["seq"] <= after and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
            s = sessions.load(sid)
        return sessions.view(s, role)

    @app.post("/v1/session/{sid}/confirm")
    async def confirm(sid: str, dev: dict = Depends(device)):
        s = sessions.load(sid)
        role = sessions.member(s, dev)
        return sessions.view(sessions.confirm(s, role), role)

    # -- setup + commit-then-reveal (§4.3, §4.4, §5.2)
    @app.post("/v1/session/{sid}/arm")
    async def arm(sid: str, req: ArmIn, dev: dict = Depends(device)):
        s = sessions.load(sid)
        role = sessions.member(s, dev)
        return sessions.arm(s, role, req.attempt, req.sample_rate, req.rtt_min_ms)

    @app.post("/v1/session/{sid}/commit")
    async def commit(sid: str, req: CommitIn, dev: dict = Depends(device)):
        s = sessions.load(sid)
        role = sessions.member(s, dev)
        return sessions.commit(s, role, dev, req.commit_b64, req.sig_b64)

    @app.post("/v1/session/{sid}/abort")
    async def abort(sid: str, dev: dict = Depends(device)):
        s = sessions.load(sid)
        role = sessions.member(s, dev)
        return sessions.view(sessions.abort(s, role), role)

    return app
