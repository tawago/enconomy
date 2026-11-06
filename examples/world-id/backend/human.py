"""World ID per (session_nonce, role).

  idle -start-> requested -waiting_for_connection-> waiting -awaiting_confirmation-> awaiting
  -confirmed-> verifying (nullifier reserved, Portal call in flight) -ok-> verified
  any -failed(code) | expired (300 s) | same_human-> failed -start-> requested (new rp_context, same action)

The sidecar (node, IDKit) creates the request and polls the bridge. This module signs rp_context, polls the sidecar
once per status call, and verifies the result. Everything runs on one event loop with one uvicorn worker, so a row
read after an await and written before the next one can't race.

session_id comes from the client. The action is pop:<session_id> and a nullifier is per action, so a second session_id
would give one human a second nullifier. The first start for a nonce pins it. The record intake compares it against
what the core signed.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

import httpx

from backend import popctx, worldid_rp
from backend.errors import ApiError

log = logging.getLogger("world-id")

ENV = "production"
REQUEST_TTL_S = 300          # rp_context TTL; a request older than this is human_expired
REUSE_S = 240                # start reuses a live request younger than this
PENDING = ("requested", "waiting", "awaiting")
BRIDGE = {"waiting_for_connection": "waiting", "awaiting_confirmation": "awaiting"}
PORTAL_BACKOFF = (0.5, 1.0, 2.0)


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


class WorldID:
    def __init__(self, cfg, store, key: str, now_ms: Callable[[], int],
                 transport: httpx.AsyncBaseTransport | None = None, sleep: Callable[[float], Any] = asyncio.sleep):
        self.cfg, self.store, self.key, self.now_ms, self.sleep = cfg, store, key, now_ms, sleep
        self.http = httpx.AsyncClient(transport=transport, timeout=10)

    def now_s(self) -> int:
        return self.now_ms() // 1000

    def _set(self, nonce: str, role: str, **fields) -> None:
        if fields.get("status") not in (None, "failed"):
            fields.setdefault("error", None)
            fields.setdefault("detail", None)
        self.store.update(nonce, role, self.now_s(), **fields)

    # -- pins
    def check_pins(self, nonce: str, session_id: str, role: str, pubkey: str) -> dict | None:
        """The nonce's session_id and the role's device key, if they're pinned yet. Returns the role's row."""
        have = self.store.session_id_for(nonce)
        if have is not None and have != session_id:
            raise ApiError(409, "session_id_mismatch", "this nonce is pinned to another session_id")
        row = self.store.get(nonce, role)
        if row is not None and row["pubkey"] != pubkey:
            raise ApiError(409, "pubkey_mismatch", "this role is pinned to another device key")
        return row

    # -- start
    async def start(self, nonce: str, session_id: str, role: str, pubkey: str) -> dict:
        now = self.now_s()
        row = self.check_pins(nonce, session_id, role, pubkey) or self.store.create(nonce, role, session_id, pubkey, now)
        if row["status"] == "verified":
            raise ApiError(409, "already_verified", "")
        if row["status"] == "verifying":
            if now - row["updated_at"] < REQUEST_TTL_S:
                raise ApiError(409, "bad_state", "verifying")
            self._set(nonce, role, status="failed", error="worldid_unavailable", nullifier=None)   # died mid-Portal
            row = self.store.get(nonce, role)
        if row["status"] in PENDING and now - (row["request_created_s"] or 0) < REUSE_S:
            return self._start_out(row)
        action = popctx.action(session_id)
        rp = worldid_rp.sign_request(self.key, action=action, ttl=REQUEST_TTL_S, now=now)
        rp_context = {"rp_id": self.cfg.rp_id, "nonce": rp["nonce"], "created_at": rp["created_at"],
                      "expires_at": rp["expires_at"], "signature": rp["sig"]}
        body = {"app_id": self.cfg.app_id, "action": action, "signal": popctx.signal_str(bytes.fromhex(nonce), role),
                "rp_context": rp_context, "environment": ENV, "return_to": self.cfg.return_to}
        # the nonce counts as issued before the await: a proof for it must never be refused as unknown
        self._set(nonce, role, issued_nonces=row["issued_nonces"] + [rp["nonce"]])
        try:
            r = await self.http.post(self.cfg.sidecar + "/requests", json=body)
            out = r.json() if r.status_code == 200 else None
            if not (isinstance(out, dict) and out.get("request_id") and out.get("connector_uri")):
                raise ValueError(f"sidecar {r.status_code}")
        except (httpx.HTTPError, ValueError) as e:
            log.warning("worldid %s %s: sidecar create failed: %s", nonce[:12], role, e)
            raise ApiError(503, "worldid_unavailable", "IDKit sidecar unreachable") from None
        row = self.store.get(nonce, role)
        if row["status"] in ("verified", "verifying"):
            raise ApiError(409, "already_verified" if row["status"] == "verified" else "bad_state", "")
        self._set(nonce, role, status="requested", request_id=out["request_id"], connector_uri=out["connector_uri"],
                  request_created_s=now, rp_nonce=rp["nonce"])
        return self._start_out(self.store.get(nonce, role))

    @staticmethod
    def _start_out(row: dict) -> dict:
        return {"request_id": row["request_id"], "connector_uri": row["connector_uri"],
                "expires_at_s": row["request_created_s"] + REQUEST_TTL_S, "status": row["status"]}

    # -- status: one sidecar poll per call
    async def status(self, nonce: str, session_id: str, role: str, pubkey: str) -> dict:
        row = self.check_pins(nonce, session_id, role, pubkey)
        if row is not None and row["status"] in PENDING:
            await self._poll(nonce, role, row)
            row = self.store.get(nonce, role)
        other = self.store.get(nonce, "B" if role == "A" else "A")
        out = {"role": role, "status": row["status"] if row else "idle", "error": row["error"] if row else None,
               "partner": {"status": other["status"] if other else "idle"}}
        if row is not None and row["status"] in PENDING:
            out.update({"request_id": row["request_id"], "connector_uri": row["connector_uri"],
                        "expires_at_s": row["request_created_s"] + REQUEST_TTL_S})
        return out

    async def _poll(self, nonce: str, role: str, row: dict) -> None:
        if self.now_s() - (row["request_created_s"] or 0) > REQUEST_TTL_S:
            self._set(nonce, role, status="failed", error="human_expired")
            return
        rid = row["request_id"]
        try:
            r = await self.http.get(f"{self.cfg.sidecar}/requests/{rid}")
            out = r.json()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("worldid %s %s: sidecar poll failed: %s", nonce[:12], role, e)
            return
        if r.status_code == 404:        # sidecar restarted and lost the request: the phone must start again
            self._set(nonce, role, status="failed", error="worldid_unavailable")
            return
        if r.status_code != 200 or not isinstance(out, dict):
            return
        row = self.store.get(nonce, role)
        if row["request_id"] != rid or row["status"] not in PENDING:
            return                      # replaced or finished meanwhile
        st = out.get("status")
        if st in BRIDGE:
            self._set(nonce, role, status=BRIDGE[st])
        elif st == "failed":
            self._set(nonce, role, status="failed", error=str(out.get("error") or "failed")[:64])
        elif st == "confirmed":
            await self.verify(nonce, role, out.get("result"))

    # -- verify
    async def verify(self, nonce: str, role: str, res: Any) -> None:
        """On failure records status failed + code on the role, then raises the ApiError for the caller to answer."""
        try:
            await self._verify(nonce, role, res)
        except ApiError as e:
            self._set(nonce, role, status="failed", error=e.code, detail=e.detail[:200], nullifier=None)
            log.info("worldid %s %s failed: %s", nonce[:12], role, e.code)
            raise

    async def _verify(self, nonce: str, role: str, res: Any) -> None:
        row = self.store.get(nonce, role)
        action = popctx.action(row["session_id"])
        subject = f"{nonce}:{role}"
        # 1. exactly one response
        if not isinstance(res, dict) or not isinstance(res.get("responses"), list) or len(res["responses"]) != 1 \
                or not isinstance(res["responses"][0], dict):
            raise ApiError(400, "human_invalid", "need exactly one response")
        r0 = res["responses"][0]
        # 2. action
        if res.get("action") != action:
            raise ApiError(400, "human_invalid", "action mismatch")
        # 3. nonce we issued for this role
        try:
            rp_nonce = canon_field(res.get("nonce"))
        except (ValueError, TypeError):
            raise ApiError(400, "human_invalid", "bad nonce") from None
        if rp_nonce not in row["issued_nonces"]:
            raise ApiError(400, "human_invalid", "nonce was not issued for this role")
        # 4. Proof of Human only, read from the request body (the Portal does not echo it)
        if r0.get("identifier") != "proof_of_human" or r0.get("issuer_schema_id") != 1:
            raise ApiError(400, "human_level", f"identifier={r0.get('identifier')!r} "
                                               f"issuer_schema_id={r0.get('issuer_schema_id')!r}")
        if res.get("environment") not in (None, ENV):
            raise ApiError(400, "human_invalid", f"environment {res.get('environment')!r}")
        # 5. signal: recompute, compare if present, overwrite (the Portal does not recompute it)
        want = expected_signal_hash(nonce, role)
        if r0.get("signal_hash") is not None:
            try:
                got = canon_field(r0["signal_hash"])
            except (ValueError, TypeError):
                got = None
            if got != want:
                raise ApiError(400, "human_invalid", "signal_hash mismatch")
        body = {**res, "responses": [{**r0, "signal_hash": want}]}
        try:
            nullifier = canon_field(r0.get("nullifier"))
        except (ValueError, TypeError):
            raise ApiError(400, "human_invalid", "bad nullifier") from None
        # 6. reserve the nullifier (sync insert, no await between check and insert)
        holder = self.store.reserve(self.cfg.rp_id, ENV, action, nullifier, subject, self.now_s())
        if holder is not None and holder != subject:
            if holder.startswith(nonce + ":"):
                raise ApiError(409, "same_human", "both roles used the same World ID")
            raise ApiError(409, "nullifier_used", "this World ID was already used for this action")
        self._set(nonce, role, status="verifying", nullifier=nullifier)
        # 7. the Portal
        try:
            await self._portal(body)
        except ApiError:
            self.store.release(self.cfg.rp_id, ENV, action, nullifier, subject)
            raise
        # 8. store
        self._set(nonce, role, status="verified", nullifier=nullifier, rp_nonce=rp_nonce, verified_at=self.now_s())
        log.info("worldid %s %s verified", nonce[:12], role)

    async def _portal(self, body: dict) -> None:
        url = f"{self.cfg.portal}/api/v4/verify/{self.cfg.rp_id}"
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
                        if out.get("environment") != ENV:
                            raise ApiError(400, "human_invalid", f"portal environment {out.get('environment')!r}")
                        return
                    code = out.get("code") if isinstance(out, dict) else None
                    log.warning("worldid portal %d %s", r.status_code, str(out)[:300])
                    raise ApiError(400, "human_invalid", f"portal {r.status_code} {code or ''}".strip())
                last = f"portal {r.status_code}"
            if i < len(PORTAL_BACKOFF):
                await self.sleep(PORTAL_BACKOFF[i])
        raise ApiError(400, "human_invalid", last)
