"""World ID example backend: two different humans met. Device requests are self-contained, public key plus signature.
There is no device table, and it uses nothing of the core but the presence record.

Run: uv run --env-file .env uvicorn --factory backend.main:create_app
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
import re
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend import worldid_rp
from backend.config import Settings
from backend.core import ROLES, SID_RE, TAG_RECORD, canonical, load_pub, record_problem, verify_raw, verify_signed
from backend.errors import ApiError
from backend.human import ENV, WorldID
from backend.store import Store

MAX_BODY = 1 << 20      # the intake is open
TAG_DEVICE = b"wid-device-v1\n"
NONCE_RE = re.compile(r"^[0-9a-f]{64}$")
PUBKEY_RE = re.compile(r"^04[0-9a-f]{128}$")
TS_WINDOW_MS = 5 * 60 * 1000


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


def device_request(req: dict, now_ms: int) -> tuple[str, str, str, str]:
    """{session_nonce, session_id, role, pubkey, ts, sig_b64}, signed by that key over a tag + canonical(the rest).
    It proves the key made this request. Nothing yet says the key was in this session: the record does that."""
    nonce, sid, role, pubkey, ts = (req.get(k) for k in ("session_nonce", "session_id", "role", "pubkey", "ts"))
    if not isinstance(nonce, str) or not NONCE_RE.fullmatch(nonce):
        raise ApiError(400, "bad_request", "session_nonce must be lowercase 64 hex")
    if not isinstance(sid, str) or not SID_RE.fullmatch(sid):
        raise ApiError(400, "bad_request", "session_id must be lowercase 32 hex")
    if not isinstance(role, str) or role not in ROLES:
        raise ApiError(400, "bad_request", "role must be A or B")
    if not isinstance(pubkey, str) or not PUBKEY_RE.fullmatch(pubkey):
        raise ApiError(400, "bad_request", "pubkey must be lowercase 65-byte SEC1 hex")
    if type(ts) is not int:
        raise ApiError(400, "bad_request", "ts must be an integer, ms")
    pub = bytes.fromhex(pubkey)
    try:
        load_pub(pub)
        sig = base64.b64decode(req.get("sig_b64"), validate=True)
    except (TypeError, ValueError, binascii.Error):
        raise ApiError(400, "bad_request", "pubkey or sig_b64") from None
    body = {"session_nonce": nonce, "session_id": sid, "role": role, "pubkey": pubkey, "ts": ts}
    if not verify_raw(pub, TAG_DEVICE + canonical(body), sig):
        raise ApiError(401, "bad_device_signature", "")
    if abs(now_ms - ts) > TS_WINDOW_MS:
        raise ApiError(401, "stale_request", "ts is too far from now")
    return nonce, sid, role, pubkey


def why_not_met(store: Store, body: dict) -> str | None:
    """None if two different verified humans met in this NEAR session, else the first thing that fails."""
    if body.get("verdict") != "NEAR":
        return "not_near"
    nonce = body["session_nonce"]
    rows = {r: store.get(nonce, r) for r in ROLES}
    if not all(rows.values()):
        return "no_world_id"
    if any(row["session_id"] != body["session_id"] for row in rows.values()):
        return "session_id_mismatch"
    if any(row["status"] != "verified" or not row["nullifier"] for row in rows.values()):
        return "role_unverified"
    if rows["A"]["nullifier"] == rows["B"]["nullifier"]:
        return "same_human"
    if any(row["pubkey"] != body["devices"][r]["pubkey"] for r, row in rows.items()):
        return "pubkey_mismatch"
    return None


def create_app(settings: Settings | None = None, now_ms=None, transport=None, sleep=asyncio.sleep) -> FastAPI:
    settings = settings or Settings.from_env()
    now_ms = now_ms or (lambda: int(time.time() * 1000))
    key = worldid_rp.load_key(str(settings.signing_key_file), None)
    if key is None:
        raise ValueError("no RP signing key: point WID_SIGNING_KEY_FILE at it")
    store = Store(settings.db)
    wid = WorldID(settings, store, key, now_ms, transport, sleep)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            await wid.http.aclose()
            store.close()

    app = FastAPI(title="world-id-example", lifespan=lifespan)
    app.state.store, app.state.worldid = store, wid

    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, e: ApiError):
        return JSONResponse({"error": e.code, "detail": e.detail}, status_code=e.status)

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/v1/config")
    def config():
        return {"app_id": settings.app_id, "rp_id": settings.rp_id, "environment": ENV,
                "device_tag": TAG_DEVICE.decode()}

    @app.post("/v1/worldid/start")
    async def start(request: Request):
        return await wid.start(*device_request(await _body(request), now_ms()))

    @app.post("/v1/worldid/status")
    async def status(request: Request):
        return await wid.status(*device_request(await _body(request), now_ms()))

    @app.post("/v1/record")
    async def record(request: Request):
        """The core's signature is the auth, so either phone can deliver. Delivering again just works the answer out
        again: a record that came before a role finished World ID gets its real answer on the retry."""
        rec = await _body(request)
        if not verify_signed(settings.core_pubkey, TAG_RECORD, rec):
            raise ApiError(401, "bad_record_signature", "not signed by the core")
        body = rec["body"]
        if (problem := record_problem(body)) is not None:
            raise ApiError(400, "bad_record", problem)
        nonce = body.get("session_nonce")
        if not isinstance(nonce, str) or not NONCE_RE.fullmatch(nonce):
            raise ApiError(400, "bad_record", "session_nonce")
        reason = why_not_met(store, body)
        answer = {"met": reason is None, "reason": reason, "session_id": body["session_id"], "session_nonce": nonce,
                  "finished_at": body.get("finished_at"), "flight_cm": body.get("flight_cm"),
                  "trust_tier": {r: body["devices"].get(r, {}).get("trust_tier") for r in ROLES}}
        store.put_meeting(nonce, answer, now_ms() // 1000)
        return answer

    return app
