"""WVP onboarding example: an admin gives a name under the org, after a beep with the person in the room.
Uses only what the core publishes, and trusts only what its signed presence record says.

Run: uv run --env-file .env uvicorn --factory backend.main:create_app --host 0.0.0.0 --port 8400
"""
from __future__ import annotations

import hmac
import json
import logging
import re
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode

from Crypto.Hash import keccak
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from backend.config import Settings
from backend.core import TAG_RECORD, record_problem, verify_signed
from backend.errors import ApiError
from backend.store import Store

log = logging.getLogger("onboarding")

MAX_BODY = 1 << 20      # the intake is open; a real record is tens of KB
CTX_TAG = b"wvp-onboarding-v1\n"
LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
ENS_TIMEOUT_S = 180
PAGES = Path(__file__).parent / "pages"


def ctx_hash_of(name: str, address: str) -> str:
    """keccak256(tag || name || "\\n" || lowercase address). The name is ascii by LABEL_RE."""
    h = keccak.new(digest_bits=256)
    h.update(CTX_TAG + name.encode("ascii") + b"\n" + address.encode("ascii"))
    return "0x" + h.hexdigest()


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


def run_subname(ens_dir: Path, label: str, address: str) -> dict:
    """node <ens-dir>/subname.mjs <label> <address>. Success is exit 0 and a JSON object on the last line of stdout.
    Raises RuntimeError with a short reason. Nothing the script says on stderr reaches a client."""
    try:
        p = subprocess.run(["node", str(ens_dir / "subname.mjs"), label, address], cwd=ens_dir,
                           capture_output=True, text=True, timeout=ENS_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(type(e).__name__) from None
    if p.returncode != 0:
        log.warning("subname.mjs exit %s: %s", p.returncode, p.stderr[-300:])
        raise RuntimeError(f"exit {p.returncode}")
    lines = [ln for ln in p.stdout.splitlines() if ln.strip()]
    try:
        out = json.loads(lines[-1])
    except (IndexError, ValueError):
        raise RuntimeError("no JSON line") from None
    if not isinstance(out, dict) or out.get("ok") is False:
        raise RuntimeError("script refused")
    return out


def create_app(settings: Settings | None = None, now_ms=None, runner=None) -> FastAPI:
    settings = settings or Settings.from_env()
    now_ms = now_ms or (lambda: int(time.time() * 1000))
    runner = runner or run_subname
    store = Store(settings.db)
    issue_lock = threading.Lock()       # one admin key, so one send at a time

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            store.close()

    app = FastAPI(title="wvp-onboarding-example", lifespan=lifespan)
    # The web app runs on the core's origin and delivers the record from there.
    app.add_middleware(CORSMiddleware, allow_origins=[settings.web_origin], allow_methods=["POST"],
                       allow_headers=["content-type"])

    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, e: ApiError):
        return JSONResponse({"error": e.code, "detail": e.detail}, status_code=e.status)

    def require_admin(request: Request) -> None:
        got = request.headers.get("x-admin-passcode", "")
        if not hmac.compare_digest(got.encode(), settings.admin_passcode.encode()):
            raise ApiError(401, "bad_passcode", "")

    def context_of(req: dict) -> dict:
        return {"chain_id": settings.chain_id, "consumer": req["address"], "ctx_hash": req["ctx_hash"]}

    def view(req: dict) -> dict:
        query = urlencode({**context_of(req), "deliver": f"{settings.public_url}/v1/presence"})
        return {"ctx_hash": req["ctx_hash"], "label": req["label"], "name": req["name"], "address": req["address"],
                "status": req["status"], "ens": json.loads(req["ens"]) if req["ens"] else None,
                "last_error": req["last_error"], "beep_url": f"{settings.web_app_url}?{query}"}

    def request_or_404(ctx_hash: str) -> dict:
        if (req := store.get(ctx_hash)) is None:
            raise ApiError(404, "no_request", "POST /v1/requests first")
        return req

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/")
    def join_page():
        return FileResponse(PAGES / "join.html")

    @app.get("/admin")
    def admin_page():
        return FileResponse(PAGES / "admin.html")

    @app.get("/v1/config")
    def config():
        return {"org": settings.org, "chain_id": settings.chain_id}

    @app.post("/v1/requests")
    async def post_request(request: Request):
        req = await _body(request)
        label, address = req.get("label"), req.get("address")
        if not isinstance(label, str) or not LABEL_RE.fullmatch(label):
            raise ApiError(400, "bad_label", "lowercase letters, digits and inner hyphens")
        if not isinstance(address, str) or not ADDR_RE.fullmatch(address):
            raise ApiError(400, "bad_address", "0x + 40 hex")
        if store.label_issued(label):
            raise ApiError(409, "label_taken", "")
        address, name = address.lower(), f"{label}.{settings.org}"
        ctx_hash = ctx_hash_of(name, address)
        return view(store.put(ctx_hash, label, name, address, now_ms()))

    @app.get("/v1/requests/{ctx_hash}")
    def get_request(ctx_hash: str):
        """What the admin reads, and what the joiner's page polls for its status."""
        return view(request_or_404(ctx_hash))

    @app.get("/v1/admin/requests")
    def pending(request: Request):
        require_admin(request)
        return {"requests": [view(r) for r in store.pending()]}

    @app.post("/v1/admin/requests/{ctx_hash}/{decision}")
    def decide(ctx_hash: str, decision: str, request: Request):
        require_admin(request)
        status = {"approve": "approved", "decline": "declined"}.get(decision)
        if status is None:
            raise ApiError(404, "not_found", "")
        request_or_404(ctx_hash)
        if not store.decide(ctx_hash, status):
            raise ApiError(409, "not_pending", "")
        return view(store.get(ctx_hash))

    def issue(rec: dict, req: dict) -> dict:
        ctx_hash, session_id = req["ctx_hash"], rec["body"]["session_id"]
        with issue_lock:
            if (req := store.get(ctx_hash))["status"] != "approved":
                raise ApiError(409, "not_approved", req["status"])
            if store.label_issued(req["label"]):
                raise ApiError(409, "label_taken", "")
            if not store.claim_session(rec, ctx_hash):
                raise ApiError(409, "session_used", "")
            try:
                ens = runner(settings.ens_dir, req["label"], req["address"])
            except RuntimeError as e:
                store.release_session(session_id)
                store.set_error(ctx_hash, str(e))
                raise ApiError(502, "ens_failed", str(e)) from None
            store.issued(ctx_hash, ens)
            log.info("issued %s to %s, session %s: %s", req["name"], req["address"], session_id, json.dumps(ens))
            return view(store.get(ctx_hash))

    @app.post("/v1/presence")
    async def presence(request: Request):
        """Open: the core's signature is the auth. Which request it spends comes from the record, never from the caller."""
        rec = await _body(request)
        if not verify_signed(settings.core_pubkey, TAG_RECORD, rec):
            raise ApiError(401, "bad_record_signature", "not signed by the core")
        body = rec["body"]
        if (problem := record_problem(body)) is not None:
            raise ApiError(400, "bad_record", problem)
        if body.get("verdict") != "NEAR":
            raise ApiError(403, "not_near", str(body.get("verdict"))[:40])
        ctx = body.get("context")
        ctx_hash = ctx.get("ctx_hash") if isinstance(ctx, dict) else None
        req = store.get(ctx_hash) if isinstance(ctx_hash, str) else None
        if req is None or ctx != context_of(req):
            raise ApiError(403, "context_mismatch", "the record is for no request here")
        if req["status"] != "approved":
            raise ApiError(409, "not_approved", req["status"])
        # record_problem has tied each device_id to its pubkey
        if not any(d.get("device_id") == settings.admin_device for d in body["devices"].values()):
            ids = [d.get("device_id") for d in body["devices"].values()]
            log.warning("no admin device in session %s, devices were %s", body["session_id"], ids)
            raise ApiError(403, "admin_device_missing", "")
        return await run_in_threadpool(issue, rec, req)

    return app
