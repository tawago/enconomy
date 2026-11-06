"""Safe example backend: takes a transaction, two owner signatures and the core's presence record, then attests.
Uses only what the core publishes, and trusts only what the record says.

Run: uv run --env-file .env uvicorn --factory backend.main:create_app
"""
from __future__ import annotations

import json
import logging
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend import attester
from backend.config import Settings
from backend.core import ROLES, TAG_RECORD, load_pub, record_problem, verify_raw, verify_signed
from backend.errors import ApiError
from backend.safe_tx import ADDR, OWNER_MSG_TAG, TOKENS, allowlist, owner_message, parse_safe_tx, safe_tx_hash
from backend.store import Store
from backend.worker import Worker, run_node

log = logging.getLogger("safe")

MAX_BODY = 1 << 20      # the intake is open; a real record is tens of KB
SIG64_RE = re.compile(r"^0x[0-9a-f]{128}$")


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


def _expiry(body: dict, ttl_s: int) -> int:
    """From the record's own finish, never from now: an old record can't get a fresh attestation."""
    try:
        finished = datetime.fromisoformat(body["finished_at"])
    except (KeyError, TypeError, ValueError):
        raise ApiError(400, "bad_record", "finished_at") from None
    if finished.tzinfo is None:
        raise ApiError(400, "bad_record", "finished_at has no offset")
    return int(finished.timestamp()) + ttl_s


def create_app(settings: Settings | None = None, now_ms=None, wake=None, runner=None) -> FastAPI:
    settings = settings or Settings.from_env()
    now_ms = now_ms or (lambda: int(time.time() * 1000))
    key = attester.load_key(settings.attest_key_file)
    if attester.public_bytes(key) == settings.core_pubkey:
        raise ValueError("the attest key is the core's presence key: they must stay separate")
    store = Store(settings.db)
    worker = Worker(store, settings, runner or run_node)
    wake = wake or worker.wake

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        worker.start()
        try:
            yield
        finally:
            worker.stop()
            store.close()

    app = FastAPI(title="safe-example", lifespan=lifespan)
    app.state.store, app.state.worker = store, worker

    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, e: ApiError):
        return JSONResponse({"error": e.code, "detail": e.detail}, status_code=e.status)

    def spend_or_404(ctx_hash: str) -> dict:
        if (spend := store.get_spend(ctx_hash)) is None:
            raise ApiError(404, "no_spend", "POST /v1/spends first")
        return spend

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/v1/config")
    def config():
        tokens = [{"address": a, "symbol": s, "decimals": d} for a, (s, d) in TOKENS.get(settings.chain_id, {}).items()]
        return {"chain_id": settings.chain_id, "attest": attester.public(key), "owner_msg_tag": OWNER_MSG_TAG.decode(),
                "tokens": tokens}

    @app.post("/v1/spends")
    async def post_spend(request: Request):
        req = await _body(request)
        chain_id, safe = req.get("chain_id"), req.get("safe")
        if type(chain_id) is not int or not 0 < chain_id < 2 ** 63:
            raise ApiError(400, "bad_context", "chain_id")
        if not isinstance(safe, str) or not ADDR.fullmatch(safe):
            raise ApiError(400, "bad_context", "safe")
        t = parse_safe_tx(req.get("safe_tx"))
        safe20 = bytes.fromhex(safe[2:])
        what = allowlist(chain_id, safe20, t)
        ctx_hash = "0x" + safe_tx_hash(chain_id, safe20, t).hex()
        store.put_spend(ctx_hash, chain_id, safe, req["safe_tx"], what)
        return {"ctx_hash": ctx_hash, "what": what}

    @app.get("/v1/spends/{ctx_hash}")
    def get_spend(ctx_hash: str):
        return spend_or_404(ctx_hash)

    @app.post("/v1/spends/{ctx_hash}/owner-sig")
    async def owner_sig(ctx_hash: str, request: Request):
        req = await _body(request)
        spend_or_404(ctx_hash)
        pubkey, sig = req.get("pubkey"), req.get("sig")
        try:
            pub = bytes.fromhex(pubkey.removeprefix("0x"))
            load_pub(pub)
        except (AttributeError, ValueError):
            raise ApiError(400, "bad_request", "pubkey must be 65-byte SEC1 hex") from None
        if not isinstance(sig, str) or not SIG64_RE.fullmatch(sig):
            raise ApiError(400, "bad_request", "sig must be lowercase 0x + 128 hex")
        if not verify_raw(pub, owner_message(bytes.fromhex(ctx_hash[2:])), bytes.fromhex(sig[2:])):
            raise ApiError(400, "bad_owner_sig", "")
        store.put_owner_sig(ctx_hash, pub.hex(), sig)
        return {"ctx_hash": ctx_hash, "pubkey": pub.hex()}

    @app.post("/v1/spends/{ctx_hash}/presence")
    async def presence(ctx_hash: str, request: Request):
        """Open: either phone delivers, and the core's signature is the auth. Every refusal leaves nothing behind,
        so the phone can deliver again once what was missing is there."""
        rec = await _body(request)
        if not verify_signed(settings.core_pubkey, TAG_RECORD, rec):
            raise ApiError(401, "bad_record_signature", "not signed by the core")
        body = rec["body"]
        if (problem := record_problem(body)) is not None:
            raise ApiError(400, "bad_record", problem)
        if body.get("verdict") != "NEAR":
            raise ApiError(403, "not_near", str(body.get("verdict"))[:40])
        spend = spend_or_404(ctx_hash)
        want = {"chain_id": spend["chain_id"], "consumer": spend["safe"], "ctx_hash": ctx_hash}
        if body.get("context") != want:
            raise ApiError(403, "context_mismatch", "the record is for another transaction")
        safe20 = bytes.fromhex(spend["safe"][2:])
        try:
            t = parse_safe_tx(spend["safe_tx"])
        except ApiError:
            raise ApiError(403, "context_mismatch", "stored safe_tx doesn't parse") from None
        if "0x" + safe_tx_hash(spend["chain_id"], safe20, t).hex() != ctx_hash:
            raise ApiError(403, "context_mismatch", "stored safe_tx doesn't hash to ctx_hash")
        if spend["chain_id"] != settings.chain_id:
            raise ApiError(403, "bad_chain", f"chain_id must be {settings.chain_id}")
        # only the record's word: the core may know better than any older copy of a device
        devices = body["devices"]
        if not all(devices[r].get("attested") is True for r in ROLES):
            raise ApiError(403, "unattested_device", "")
        allowlist(spend["chain_id"], safe20, t)
        pubs = [bytes.fromhex(devices[r]["pubkey"]).hex() for r in ROLES]
        if not all(store.owner_sig(ctx_hash, p) for p in pubs):
            raise ApiError(409, "owner_sigs_missing", "both phones send their owner-sig first")

        sid = body["session_id"]
        if store.get_attestation(sid) is None:
            expiry = _expiry(body, settings.att_ttl_s)
            if expiry <= now_ms() // 1000:
                raise ApiError(403, "expired", f"expiry={expiry}")
        else:
            expiry = None
        att = store.attest_once(rec, ctx_hash, lambda: attester.attestation(key, want, pubs[0], pubs[1], expiry))
        store.requeue_job(sid)  # a redelivery is also the retry for a job that failed
        job = store.job(sid)
        if job["status"] != "success":
            wake()
        log.info("safe presence %s -> %s", sid, job["status"])
        return {"session_id": sid, "ctx_hash": ctx_hash, "att": att, "relay": job["status"]}

    @app.get("/v1/spends/{ctx_hash}/relay")
    def relay(ctx_hash: str):
        if (job := store.latest_job(ctx_hash)) is None:
            return {"status": "none"}
        return {"status": job["status"], "session_id": job["session_id"],
                "result": json.loads(job["result"]) if job["result"] else None}

    return app
