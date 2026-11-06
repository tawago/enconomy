"""ENS meetings backend: name claims and presence record intake. Uses only what the core publishes.

Run: uv run --env-file .env uvicorn --factory backend.main:create_app
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.chain import Chain
from backend.config import Settings
from backend.core import (STATEMENT_FORMAT, TAG_RECORD, TAG_STATEMENT, canonical, device_id, load_pub, record_problem,
                          verify_raw, verify_signed)
from backend.errors import ApiError
from backend.store import Store, view
from backend.worker import Worker
from bridge.bridge import Bridge, Cfg

log = logging.getLogger("ens")

CLAIM_TAG = b"ens-claim-v1\n"
SKEW_MS = 60_000
FUTURE_MS = 60_000      # a statement from a core clock this far ahead still counts
MAX_BODY = 1 << 20      # the intake is open; a real record is tens of KB
PHONES = ("android", "ios")


def claim_message(label, dev_id: str, ts: int) -> bytes:
    """What the device signs. The read signs the same with label null, which can never claim. canonical() keeps any
    JSON label unambiguous, so even a bad label gets past the signature and answers bad_label."""
    return CLAIM_TAG + canonical({"device_id": dev_id, "label": label, "ts": ts})


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="seconds")


async def _body(request: Request) -> dict:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise ApiError(413, "too_large", "")
    try:
        body = json.loads(raw)
    except (ValueError, RecursionError):
        raise ApiError(400, "bad_request", "body must be JSON") from None
    if not isinstance(body, dict):
        raise ApiError(400, "bad_request", "body must be an object")
    return body


class DeviceAuth:
    """A signed request from a device the core vouches for. There is no device table: the statement is the proof."""

    def __init__(self, core_pubkey: bytes, max_age_s: int, now_ms):
        self.core_pubkey, self.max_age_ms, self.now_ms = core_pubkey, max_age_s * 1000, now_ms
        self._seen: dict[bytes, int] = {}   # signed message -> forget after (ms). Not the sig: anyone can flip s.
        self._lock = threading.Lock()

    def check(self, req: dict, label) -> dict:
        """Returns the verified statement's body. Order: core signature, format and freshness, device_id,
        device signature, ts skew, replay."""
        st = req.get("device_statement")
        if not verify_signed(self.core_pubkey, TAG_STATEMENT, st):
            raise ApiError(401, "bad_statement", "not signed by the core")
        b = st["body"]
        if b.get("format") != STATEMENT_FORMAT:
            raise ApiError(401, "bad_statement", "format")
        now = self.now_ms()
        at = b.get("issued_at_ms")
        if type(at) is not int or now - at > self.max_age_ms or at - now > FUTURE_MS:
            raise ApiError(401, "statement_stale", "fetch a new one from the core")
        try:
            pub = bytes.fromhex(b["pubkey"])
            load_pub(pub)
        except (KeyError, TypeError, ValueError):
            raise ApiError(401, "bad_statement", "pubkey") from None
        if b.get("device_id") != device_id(pub):
            raise ApiError(401, "bad_statement", "device_id != sha256(pubkey)[:16]")
        ts = req.get("ts")
        try:
            msg = claim_message(label, b["device_id"], ts)
            sig = base64.b64decode(req["sig_b64"], validate=True)
        except (KeyError, TypeError, ValueError, binascii.Error, RecursionError):
            raise ApiError(401, "auth_bad_signature", "") from None
        if type(ts) is not int or not verify_raw(pub, msg, sig):
            raise ApiError(401, "auth_bad_signature", "")
        if abs(now - ts) > SKEW_MS:
            raise ApiError(401, "auth_stale", f"ts={ts} now={now}")
        with self._lock:
            self._seen = {k: v for k, v in self._seen.items() if v > now}
            if msg in self._seen:
                raise ApiError(401, "auth_replay", "")
            self._seen[msg] = ts + SKEW_MS + 1
        return b


def create_app(settings: Settings | None = None, chain=None, now_ms=None, http_get=None) -> FastAPI:
    settings = settings or Settings.from_env()
    now_ms = now_ms or (lambda: int(time.time() * 1000))
    cfg = Cfg(rpc=settings.rpc, keyFile=settings.key_file, deployments=settings.deployments,
              zkDeployments=settings.zk_deployments, db=settings.db, coreUrl=settings.core_url, log=settings.log)
    if chain is None:
        chain = Chain(cfg["rpc"], cfg["keyFile"], cfg.resolver, cfg.registry)
    store = Store(settings.db)
    worker = Worker(store, chain, Bridge(store, chain, cfg, http_get))
    auth = DeviceAuth(settings.core_pubkey, settings.statement_max_age_s, now_ms)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        worker.start()
        try:
            yield
        finally:
            worker.stop()
            store.close()

    app = FastAPI(title="ens-meetings", lifespan=lifespan)
    app.state.store, app.state.worker = store, worker

    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, e: ApiError):
        return JSONResponse({"error": e.code, "detail": e.detail}, status_code=e.status)

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/v1/names/claim")
    async def claim(request: Request):
        req = await _body(request)
        label = req.get("label")
        b = auth.check(req, label)
        if b.get("platform") not in PHONES:
            raise ApiError(403, "not_allowed", "ENS names are for phones")
        if b.get("attested") is not True:
            raise ApiError(403, "not_attested", "ENS names are for attested phones")
        row = store.claim(req["device_statement"], label, _iso(now_ms()))
        log.info("ens claim %s -> %s", b["device_id"], row["label"])
        worker.wake()
        return view(row)

    @app.post("/v1/names/read")
    async def read(request: Request):
        b = auth.check(await _body(request), None)
        return view(store.get_name(b["device_id"]))

    @app.post("/v1/presence")
    async def presence(request: Request):
        """Open: the core's signature is the auth, and one meeting per session bounds the gas."""
        rec = await _body(request)
        if not verify_signed(settings.core_pubkey, TAG_RECORD, rec):
            raise ApiError(401, "bad_record_signature", "not signed by the core")
        if (problem := record_problem(rec["body"])) is not None:
            raise ApiError(400, "bad_record", problem)
        status = store.put_record(rec["body"], rec["sig_b64"], _iso(now_ms()))
        # a redelivery changes nothing, but it's also the retry for a record a chain or network error left undone
        if status != "unchanged" or store.is_undone(rec["body"]["session_id"]):
            worker.wake()
        return {"session_id": rec["body"]["session_id"], "status": status}

    return app
