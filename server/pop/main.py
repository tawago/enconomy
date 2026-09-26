"""pop-v1 server: enrollment, signed-request auth, pairing, arm/start, commit, transcript, verdict (contract §2-§9).
POPT v2 (docs/pop-transcript-v2.md) is opt-in per phone with "popt": 2 at arm; see pop/sessions.py.

Run: uv run python -m pop            (0.0.0.0:8000)
 or: uv run uvicorn --factory pop.main:create_app --host 0.0.0.0 --port 8000

Env: POP_DB (default data/pop.sqlite), POP_DATA_DIR (default data/; result.json + recordings under
sessions/<id>/), POP_ALLOW_UNATTESTED=1, POP_GAIN_DB (0), POP_TUNE_DB (0, tune-only boost, bed level fixed), POP_UPLOAD_RECORDINGS (1),
POP_IOS_APP_ID (TEAMID.com.enconomy.pop, App Attest), POP_IOS_ROOT_PEM (path, overrides the Apple root),
POP_ISSUER_KEY (PEM or hex) / POP_ISSUER_KEY_FILE (default data/issuer.pem), POP_ISSUER_AUTOGEN (1), POP_CRED_TTL_S,
POP_ZK_VERIFIER (popprover binary, default ../app/prover/target/release/popprover), POP_ZK_KEYS (default data/zk/,
<circuit>.pk.zst served at /v1/zk/keys), POP_ZK_VK_DIR (<circuit>.vk, default POP_ZK_KEYS), POP_ZK_WRAP (prefix).
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
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
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from pop import calibration as CAL
from pop import constants as K
from pop.appattest import APPLE_ROOT_PEM, verify_app_attest
from pop.attestation import AttestationError, verify_chain
from pop.auth import Authenticator
from pop.crypto import device_id as derive_device_id, load_pub, verify_raw
from pop import issuer as sbcred
from pop import consumers, jbl250, popt2, zk
from pop.errors import PopError
from pop.human import WorldID
from pop.sessions import Sessions
from pop.verdict import Reject
from pop.store import SqliteStore, Store

SERVER_DIR = Path(__file__).resolve().parents[1]
SECURITY_LEVELS = {"strongbox", "tee", "software", "unknown"}
IOS_KEY_KINDS = {"secure_enclave", "software"}
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
    tune_db: float = field(default_factory=lambda: float(os.environ.get("POP_TUNE_DB", "0")))
    upload_recordings: bool = field(default_factory=lambda: _env_bool("POP_UPLOAD_RECORDINGS", True))
    data_dir: str | None = field(default_factory=lambda: os.environ.get("POP_DATA_DIR", str(SERVER_DIR / "data")))
    ios_app_id: str | None = field(default_factory=lambda: os.environ.get("POP_IOS_APP_ID") or None)
    ios_root_pem: bytes = field(default_factory=lambda: _read_root(os.environ.get("POP_IOS_ROOT_PEM")))
    issuer_key: str | None = field(default_factory=lambda: os.environ.get("POP_ISSUER_KEY") or None)
    issuer_key_file: str = field(default_factory=lambda: os.environ.get(
        "POP_ISSUER_KEY_FILE", str(SERVER_DIR / "data" / "issuer.pem")))
    issuer_autogen: bool = field(default_factory=lambda: _env_bool("POP_ISSUER_AUTOGEN", True))
    cred_ttl_s: int = field(default_factory=lambda: int(os.environ.get("POP_CRED_TTL_S", str(sbcred.CRED_TTL_S))))
    zk_verifier: str | None = field(default_factory=lambda: os.environ.get("POP_ZK_VERIFIER") or _default_prover())
    zk_keys: str = field(default_factory=lambda: os.environ.get("POP_ZK_KEYS", str(SERVER_DIR / "data" / "zk")))
    zk_vk_dir: str | None = field(default_factory=lambda: os.environ.get("POP_ZK_VK_DIR") or None)
    zk_wrap: str | None = field(default_factory=lambda: os.environ.get("POP_ZK_WRAP") or None)
    chain_id: int = field(default_factory=lambda: int(os.environ.get("POP_CHAIN_ID", "4801")))
    test_kinds: bool = field(default_factory=lambda: _env_bool("POP_TEST_KINDS", False))
    worldid_rp_id: str | None = field(default_factory=lambda: os.environ.get("POP_WORLDID_RP_ID") or None)
    worldid_fake: bool = field(default_factory=lambda: _env_bool("POP_WORLDID_FAKE", False))
    worldid_app_id: str | None = field(default_factory=lambda: os.environ.get("POP_WORLDID_APP_ID") or None)
    worldid_signing_key: str | None = field(default_factory=lambda: os.environ.get("POP_WORLDID_SIGNING_KEY") or None)
    worldid_signing_key_file: str = field(default_factory=lambda: os.environ.get(
        "POP_WORLDID_SIGNING_KEY_FILE", str(SERVER_DIR / "data" / "worldid-rp.key")))
    worldid_env: str = field(default_factory=lambda: os.environ.get("POP_WORLDID_ENV", "production"))
    worldid_allow_legacy: bool = field(default_factory=lambda: _env_bool("POP_WORLDID_ALLOW_LEGACY", False))
    worldid_sidecar: str = field(default_factory=lambda: os.environ.get("POP_WORLDID_SIDECAR", "http://127.0.0.1:8787"))
    worldid_return_to: str = field(default_factory=lambda: os.environ.get("POP_WORLDID_RETURN_TO", "enconomy://worldid"))
    worldid_portal: str = field(default_factory=lambda: os.environ.get("POP_WORLDID_PORTAL", "https://developer.world.org"))
    worldid_poll_s: float = field(default_factory=lambda: float(os.environ.get("POP_WORLDID_POLL_S", "1.5")))
    worldid_sandbox: bool = field(default_factory=lambda: _env_bool("POP_WORLDID_SANDBOX", False))  # simulator per role, test sessions
    worldid_bg_poll: bool = True   # tests turn it off and drive polls through the status long-poll
    now_ms: Callable[[], int] = wall_ms


def _default_prover() -> str | None:
    p = SERVER_DIR.parent / "app" / "prover" / "target" / "release" / "popprover"
    return str(p) if p.exists() else None


def _read_root(path: str | None) -> bytes:
    return Path(path).read_bytes() if path else APPLE_ROOT_PEM


def _hex(s: str, nbytes: int) -> bytes | None:
    s = s.lower() if isinstance(s, str) else ""
    if len(s) != 2 * nbytes or not HEX.match(s):
        return None
    return bytes.fromhex(s)


ADDR_RE = re.compile(r"^0x[0-9a-f]{40}$")
B32_RE = re.compile(r"^0x[0-9a-f]{64}$")


def parse_session_in(raw: bytes, cfg: Settings) -> tuple[dict | None, dict]:
    """POST /v1/session body (worldid 01 §9 row 1, §7.2 policy table) -> (context, policy)."""
    try:
        body = json.loads(raw) if raw.strip() else {}
    except ValueError:
        raise PopError(400, "bad_request", "body must be JSON") from None
    if not isinstance(body, dict):
        raise PopError(400, "bad_request", "body must be an object")
    ctx, pol = body.get("context"), body.get("policy")
    if pol is not None and not (isinstance(pol, dict) and pol.get("human") in ("worldid", "none")):
        raise PopError(400, "bad_policy", "policy.human must be worldid|none")
    if ctx is None:
        return None, {"human": pol["human"] if pol else "none"}
    if pol is not None and pol["human"] != "worldid":
        raise PopError(400, "bad_policy", "a context always requires World ID")
    if not isinstance(ctx, dict):
        raise PopError(400, "bad_request", "context must be an object")
    kind = consumers.kinds(cfg.test_kinds).get(ctx.get("kind"))
    if kind is None:
        raise PopError(400, "bad_kind", str(ctx.get("kind"))[:40])
    cid = ctx.get("chain_id")
    if not _int_strict(cid) or cid != cfg.chain_id:
        raise PopError(400, "bad_chain", f"chain_id must be {cfg.chain_id}")
    if not isinstance(ctx.get("consumer"), str) or not ADDR_RE.match(ctx["consumer"]):
        raise PopError(400, "bad_request", "consumer must be lowercase 0x + 40 hex")
    if not isinstance(ctx.get("ctx_hash"), str) or not B32_RE.match(ctx["ctx_hash"]):
        raise PopError(400, "bad_request", "ctx_hash must be lowercase 0x + 64 hex")
    try:
        want = kind.validate(ctx)
    except PopError:
        raise
    except (KeyError, TypeError, ValueError) as e:
        raise PopError(400, "context_mismatch", str(e)[:200]) from None
    if want != bytes.fromhex(ctx["ctx_hash"][2:]):
        raise PopError(400, "context_mismatch", "ctx_hash does not match the kind fields")
    if not cfg.worldid_rp_id and not cfg.worldid_fake:
        raise PopError(503, "worldid_unavailable", "POP_WORLDID_RP_ID is not set")
    return ctx, {"human": "worldid"}


def _int_strict(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="milliseconds")


class AppAttestIn(BaseModel):
    key_id: str
    attestation: str


class EnrollIn(BaseModel):
    nonce: str
    device_id: str
    pubkey: str
    display_name: str
    model: str = ""
    security_level: str = "unknown"
    chain: list[str] | None = None
    platform: str = "android"
    key_kind: str | None = None
    app_attest: AppAttestIn | None = None
    holder_commit: str | None = None
    # enrollment calibration (pop/calibration.py) + device-key signature over calibration.message(nonce, cal)
    calibration: dict | None = None
    cal_sig_b64: str | None = None


class JoinIn(BaseModel):
    join_token: str


class ArmIn(BaseModel):
    attempt: Any = None
    sample_rate: Any = None
    rtt_min_ms: Any = None
    popt: Any = None


class CommitIn(BaseModel):
    commit_b64: str
    sig_b64: str


class TranscriptIn(BaseModel):
    transcript_b64: str
    sig_b64: str
    meta: dict[str, Any] | None = None


class FailIn(BaseModel):
    attempt: Any = None
    reason: Any = None


def create_app(settings: Settings | None = None, store: Store | None = None, verifier=None,
               worldid_transport=None) -> FastAPI:
    """verifier: anything with zk.Verifier's verify(circuit, proof, expected) / available(circuit) (tests fake it).
    worldid_transport: an httpx transport for the IDKit sidecar + Portal calls (tests pass httpx.MockTransport)."""
    cfg = settings or Settings()
    if cfg.worldid_fake and not cfg.test_kinds:
        raise RuntimeError("POP_WORLDID_FAKE requires POP_TEST_KINDS=1")
    if cfg.worldid_env != "production" and not cfg.worldid_fake:
        raise RuntimeError("POP_WORLDID_ENV must be production (the staging path is cut, worldid 01 §0.5)")
    db = store or SqliteStore(cfg.db)
    auth = Authenticator(db, cfg.now_ms)
    sessions = Sessions(db, cfg.now_ms, cfg.gain_db, cfg.data_dir, cfg.tune_db)
    issuer = sbcred.Issuer(sbcred.load_key(cfg.issuer_key, cfg.issuer_key_file, cfg.issuer_autogen), cfg.cred_ttl_s)

    zkv = verifier or zk.Verifier(cfg.zk_verifier, cfg.zk_vk_dir or cfg.zk_keys, cfg.zk_wrap)
    wid = WorldID(cfg, sessions, db, worldid_transport)

    app = FastAPI(title="pop-v1")
    app.state.cfg, app.state.store, app.state.sessions, app.state.issuer = cfg, db, sessions, issuer
    app.state.zk, app.state.worldid = zkv, wid

    @app.exception_handler(PopError)
    async def _pop_error(req: Request, e: PopError):
        req.state.pop_err = f"{e.code} {e.detail}".strip()
        return JSONResponse({"error": e.code, "detail": e.detail}, status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def _bad_request(req: Request, e: RequestValidationError):
        req.state.pop_err = "bad_request " + str(e.errors())[:200]
        return JSONResponse({"error": "bad_request", "detail": str(e.errors())[:500]}, status_code=400)

    @app.exception_handler(StarletteHTTPException)
    async def _http(req: Request, e: StarletteHTTPException):
        req.state.pop_err = f"{'not_found' if e.status_code == 404 else 'http_error'} {e.detail}"
        return JSONResponse({"error": "not_found" if e.status_code == 404 else "http_error", "detail": str(e.detail)},
                            status_code=e.status_code)

    @app.middleware("http")
    async def _log(request: Request, call_next):
        t = time.monotonic()
        resp = await call_next(request)
        err = getattr(request.state, "pop_err", None) if resp.status_code >= 400 else None
        log.info("%s %s %s -> %d (%.0fms) dev=%s%s", request.client.host if request.client else "?", request.method,
                 request.url.path, resp.status_code, (time.monotonic() - t) * 1000,
                 request.headers.get("x-pop-device", "-"), f" err={err}" if err else "")
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
        return {"ok": True, "proto": K.PROTO, "server_ms": cfg.now_ms(), "allow_unattested": cfg.allow_unattested,
                "worldid": await wid.health()}

    @app.get("/v1/time")
    async def server_time():
        return {"server_ms": cfg.now_ms()}

    @app.get("/v1/config")
    async def config():
        return {**K.table(), "allow_unattested": cfg.allow_unattested, "gain_db": cfg.gain_db,
                "tune_db": cfg.tune_db, "tune_db_max": (mx := {str(sr): jbl250.max_safe_tune_db(sr) for sr in K.ZK_RATES}),
                "tune_db_applied": {sr: {r: min(cfg.tune_db, v) for r, v in m.items()} for sr, m in mx.items()},
                "upload_recordings": cfg.upload_recordings, "issuer": issuer.public(), "popt2_rates": popt2.config(),
                "zk": {"circuits": {str(sr): c for sr, c in zk.CIRCUITS.items()}, "vk_sha256": dict(zk.VK_PINS),
                       "keys": "/v1/zk/keys", "verifier": {c: zkv.available(c) for c in zk.CIRCUIT_SR}},
                "worldid": wid.config(), "chain": {"chain_id": cfg.chain_id}}

    # -- option A proving keys: public, static, Range for resume (docs/pop-prover.md)
    @app.get("/v1/zk/keys")
    async def zk_keys():
        return {"keys": await asyncio.to_thread(zk.key_manifest, cfg.zk_keys)}

    @app.get("/v1/zk/keys/{name}")
    async def zk_key(name: str):
        p = Path(cfg.zk_keys) / name
        if not zk.KEY_FILE.match(name) or not p.is_file():
            raise PopError(404, "not_found", "no such proving key")
        sha = await asyncio.to_thread(zk.file_sha256, p)
        return FileResponse(p, media_type="application/zstd", headers={"X-Pop-Sha256": sha})

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
        hold = None
        if req.holder_commit is not None:
            try:
                hold = sbcred.parse_holder_commit(req.holder_commit)
            except sbcred.CredError as e:
                raise PopError(400, e.code, e.detail) from None
        cal = None
        if req.calibration is not None:
            try:
                cal = CAL.parse(req.calibration)
            except CAL.CalError as e:
                raise PopError(400, e.code, e.detail) from None
            try:
                csig = base64.b64decode(req.cal_sig_b64 or "", validate=True)
            except (binascii.Error, ValueError):
                csig = b""
            if not verify_raw(pub, CAL.message(nonce.hex(), cal), csig):
                raise PopError(400, "bad_calibration", "cal_sig_b64 is not the device key's signature")
        if req.platform == "ios":
            att, attested, key_kind = _enroll_ios(req, pub, nonce)
            reported = att["security_level"]
        elif req.platform != "android":
            raise PopError(400, "bad_request", "platform must be android or ios")
        else:
            key_kind = "android_keystore"
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
                    log.warning("enroll %s: reported security_level=%s, attestation says %s", dev_id, reported,
                                att["security_level"])
        now = cfg.now_ms()
        cred = issuer.issue(pub, hold, now // 1000) if hold is not None else None
        db.put_device({"device_id": dev_id, "pubkey": pub.hex(), "display_name": name, "model": req.model[:64],
                       "security_level": att["security_level"], "security_level_reported": reported,
                       "attested": attested, "chain_pem": att["chain_pem"], "root_sha256": att["root_sha256"],
                       "enrolled_at": _iso(now), "platform": req.platform, "key_kind": key_kind,
                       "attest_key_id": att.get("key_id"),
                       "holder_commit": hold.hex() if hold else None, "cred": cred["cred"].hex() if cred else None,
                       "cred_sig": cred["sig"].hex() if cred else None, "cred_expiry": cred["expiry"] if cred else None,
                       **CAL.columns(cal, _iso(now))})
        log.info("enrolled %s %r %s model=%r attested=%s level=%s", dev_id, name, req.platform, req.model, attested,
                 att["security_level"])
        out = {"device_id": dev_id, "attested": attested, "security_level": att["security_level"],
               "platform": req.platform, "key_kind": key_kind, "enrolled_at": _iso(now),
               "calibration": CAL.public(db.get_device(dev_id))}
        if cred:
            out["credential"] = {"format": "SBcred3", "cred_b64": base64.b64encode(cred["cred"]).decode(),
                                 "sig_b64": base64.b64encode(cred["sig"]).decode(), "expiry": cred["expiry"],
                                 "issuer_pubkey": issuer.pub.hex()}
        return out

    def _enroll_ios(req: EnrollIn, pub: bytes, nonce: bytes) -> tuple[dict, bool, str]:
        """App Attest binds the signing key via clientDataHash; the key kind itself is only reported."""
        kind = next((k for k in (req.key_kind, req.security_level) if k in IOS_KEY_KINDS), "unknown")
        if req.chain is not None:
            raise PopError(400, "bad_request", "ios sends app_attest, not chain")
        if req.app_attest is None:
            if not cfg.allow_unattested:
                raise PopError(400, "enroll_bad_attestation", "app_attest required (POP_ALLOW_UNATTESTED is off)")
            return {"security_level": kind, "chain_pem": None, "root_sha256": None}, False, kind
        try:
            att = verify_app_attest(req.app_attest.attestation, req.app_attest.key_id, pub, nonce, cfg.ios_app_id,
                                    cfg.ios_root_pem)
        except AttestationError as e:
            raise PopError(400, e.code, e.detail) from None
        return {**att, "security_level": kind}, True, kind

    # -- recalibrate: a new calibration for the signed-in device (signed-request auth covers the body)
    @app.post("/v1/device/calibration")
    async def recalibrate(request: Request, dev: dict = Depends(device)):
        try:
            body = json.loads(await request.body() or b"{}")
            cal = CAL.parse(body.get("calibration") if isinstance(body, dict) else None)
        except ValueError:
            raise PopError(400, "bad_request", "json body with a calibration object") from None
        except CAL.CalError as e:
            raise PopError(400, e.code, e.detail) from None
        db.put_device({**dev, **CAL.columns(cal, _iso(cfg.now_ms()))})
        log.info("recalibrated %s cal_us=%d sr=%d route=%s backend=%s", dev["device_id"], cal["cal_us"],
                 cal["sample_rate"], cal["route"], cal["backend"])
        return {"device_id": dev["device_id"], "calibration": CAL.public(db.get_device(dev["device_id"]))}

    # -- pairing (§3)
    @app.post("/v1/session")
    async def create_session(request: Request, dev: dict = Depends(device)):
        context, policy = parse_session_in(await request.body(), cfg)
        return sessions.create(dev, context, policy)

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

    # -- World ID (worldid 01 §6, §7.2, §9 rows 4/5)
    @app.post("/v1/session/{sid}/worldid/start")
    async def worldid_start(sid: str, request: Request, dev: dict = Depends(device)):
        s = sessions.load(sid)
        role = sessions.member(s, dev)
        body = await request.body()
        try:
            b = json.loads(body) if body.strip() else {}
        except ValueError:
            raise PopError(400, "bad_request", "body must be JSON") from None
        env = b.get("env") if isinstance(b, dict) else None
        return await wid.start(s, role, env)

    @app.get("/v1/session/{sid}/worldid")
    async def worldid_status(sid: str, timeout_s: float = 0, dev: dict = Depends(device)):
        s = sessions.load(sid)
        role = sessions.member(s, dev)
        return await wid.status(s["session_id"], role, timeout_s)

    # -- setup + commit-then-reveal (§4.3, §4.4, §5.2)
    @app.post("/v1/session/{sid}/arm")
    async def arm(sid: str, req: ArmIn, dev: dict = Depends(device)):
        s = sessions.load(sid)
        role = sessions.member(s, dev)
        return sessions.arm(s, role, req.attempt, req.sample_rate, req.rtt_min_ms, req.popt)

    @app.post("/v1/session/{sid}/commit")
    async def commit(sid: str, req: CommitIn, dev: dict = Depends(device)):
        s = sessions.load(sid)
        role = sessions.member(s, dev)
        return sessions.commit(s, role, dev, req.commit_b64, req.sig_b64)

    # -- transcript, fail, result (§7, §8)
    @app.post("/v1/session/{sid}/transcript")
    async def transcript(sid: str, req: TranscriptIn, dev: dict = Depends(device)):
        s = sessions.load(sid)
        role = sessions.member(s, dev)
        return sessions.transcript(s, role, dev, req.transcript_b64, req.sig_b64, req.meta)

    @app.post("/v1/session/{sid}/fail")
    async def fail(sid: str, req: FailIn, dev: dict = Depends(device)):
        s = sessions.load(sid)
        role = sessions.member(s, dev)
        return sessions.view(sessions.fail(s, role, req.attempt, req.reason), role)

    @app.get("/v1/session/{sid}/result")
    async def result(sid: str, dev: dict = Depends(device)):
        s = sessions.load(sid)
        sessions.member(s, dev)
        return sessions.result(s)

    @app.post("/v1/session/{sid}/recording")
    async def recording(sid: str, request: Request, dev: dict = Depends(device)):
        s = sessions.load(sid)
        role = sessions.member(s, dev)
        form = await request.form()
        wav, meta_raw = form.get("wav"), form.get("meta")
        if wav is None or isinstance(wav, str):
            raise PopError(400, "bad_request", "multipart field 'wav' (file) required")
        try:
            meta = json.loads(meta_raw) if isinstance(meta_raw, str) else None
        except ValueError:
            raise PopError(400, "bad_request", "meta must be JSON") from None
        attempt = meta.get("attempt", s["attempt"]) if isinstance(meta, dict) else s["attempt"]
        data = await wav.read()
        return await asyncio.to_thread(sessions.recording, s, role, attempt, data, meta)

    # -- option A proof upload, per role, after NEAR (pop/zk.py)
    @app.post("/v1/session/{sid}/proof")
    async def proof(sid: str, request: Request, dev: dict = Depends(device)):
        s = sessions.load(sid)
        role = sessions.member(s, dev)
        form = await request.form()
        pf, meta_raw = form.get("proof"), form.get("meta")
        if pf is None or isinstance(pf, str):
            raise PopError(400, "bad_request", "multipart field 'proof' (file) required")
        try:
            meta = json.loads(meta_raw) if isinstance(meta_raw, str) else None
        except ValueError:
            meta = None
        if not isinstance(meta, dict):
            raise PopError(400, "bad_request", "meta must be a JSON object {attempt, circuit, salt}")
        data = await pf.read()
        if not 0 < len(data) <= zk.MAX_PROOF_BYTES:
            raise PopError(400, "bad_request", f"proof must be 1..{zk.MAX_PROOF_BYTES} bytes")
        try:
            salt = zk.parse_salt(meta.get("salt"))
        except ValueError as e:
            raise PopError(400, "bad_request", str(e)) from None
        attempt, circuit = meta.get("attempt", s["attempt"]), meta.get("circuit")
        sha = hashlib.sha256(data).hexdigest()
        prev = sessions.zk_entry(s, role)
        if prev and prev["status"] == "verified":
            if prev["proof_sha256"] == sha and prev["attempt"] == attempt:
                return {"status": "verified", "role": role, "zk": sessions.zk_public(s)}
            raise PopError(409, "already_submitted", "a proof for this role is already verified")
        entry = {"attempt": attempt, "circuit": circuit, "proof_sha256": sha, "proof_bytes": len(data),
                 "at_ms": cfg.now_ms()}
        try:
            want = sessions.zk_expected(s, role, dev, attempt, circuit, salt, issuer.pub)
            await asyncio.to_thread(zkv.verify, circuit, data, want)
        except Reject as e:
            sessions.zk_record(sid, role, {**entry, "status": "rejected", "reason": e.reason, "detail": e.detail})
            log.info("proof %s %s rejected: %s %s", sid, role, e.reason, e.detail)
            raise PopError(400, e.reason, e.detail) from None
        except zk.Unavailable as e:
            raise PopError(503, "zk_unavailable", str(e)) from None
        s = sessions.zk_record(sid, role, {**entry, "status": "verified", "reason": None, "detail": None,
                                           "half_commit": want[0], "salt": str(salt)}, data)
        log.info("proof %s %s verified (%s)", sid, role, circuit)
        return {"status": "verified", "role": role, "zk": sessions.zk_public(s)}

    @app.post("/v1/session/{sid}/abort")
    async def abort(sid: str, dev: dict = Depends(device)):
        s = sessions.load(sid)
        role = sessions.member(s, dev)
        return sessions.view(sessions.abort(s, role), role)

    return app
