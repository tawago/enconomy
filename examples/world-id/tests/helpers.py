"""Test phones, the core's throwaway key from the vector, and a mocked sidecar + Portal in one httpx transport."""
from __future__ import annotations

import base64
import hashlib
import json
import uuid
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from backend.core import TAG_RECORD, canonical
from backend.main import TAG_DEVICE

VECTOR = json.loads((Path(__file__).parent / "fixtures/presence_vector.json").read_text())
CORE_KEY = ec.derive_private_key(int(VECTOR["throwaway_private_key_hex"], 16), ec.SECP256R1())
CORE_PUB = bytes.fromhex(VECTOR["pubkey_hex"])

T0_MS = 1_790_000_003_000
NONCE = "c1" * 32
SID = "ab" * 16


def sign_raw(sk, msg: bytes) -> bytes:
    r, s = decode_dss_signature(sk.sign(msg, ec.ECDSA(hashes.SHA256())))
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def sign_record(body: dict, key=CORE_KEY) -> dict:
    return {"body": body, "sig_b64": base64.b64encode(sign_raw(key, TAG_RECORD + canonical(body))).decode()}


class Clock:
    def __init__(self):
        self.ms = T0_MS

    def __call__(self) -> int:
        return self.ms

    def advance(self, seconds: int) -> None:
        self.ms += seconds * 1000


class Phone:
    def __init__(self, client, clock, role: str):
        self.client, self.clock, self.role = client, clock, role
        self.sk = ec.generate_private_key(ec.SECP256R1())
        self.pub = self.sk.public_key().public_bytes(serialization.Encoding.X962,
                                                     serialization.PublicFormat.UncompressedPoint)

    def signed(self, nonce=NONCE, sid=SID, role=None, **over) -> dict:
        body = {"session_nonce": nonce, "session_id": sid, "role": role or self.role, "pubkey": self.pub.hex(),
                "ts": self.clock()}
        return body | {"sig_b64": base64.b64encode(sign_raw(self.sk, TAG_DEVICE + canonical(body))).decode()} | over

    def start(self, **k) -> httpx.Response:
        return self.client.post("/v1/worldid/start", json=self.signed(**k))

    def status(self, **k) -> httpx.Response:
        return self.client.post("/v1/worldid/status", json=self.signed(**k))

    def until(self, want: str, n: int = 10, **k) -> httpx.Response:
        """Status calls until the role reaches `want` or a call is refused. Each call is one sidecar poll."""
        for _ in range(n):
            r = self.status(**k)
            if r.status_code != 200 or r.json()["status"] == want:
                return r
        raise AssertionError(r.text)


def fake_nullifier(who: str, action: str) -> str:
    return "0x00" + hashlib.sha256(f"fake-human:{who}:{action}".encode()).hexdigest()[:62]


class FakeWorld:
    """Sidecar (POST /requests, GET /requests/:id) + Portal (/api/v4/verify). Each role is its own human by default."""

    def __init__(self):
        self.reqs: dict[str, dict] = {}
        self.polls = 2
        self.same_human = False
        self.mutate = None                 # fn(result, entry) -> result
        self.portal: list = []             # queued (status, body) answers; default success
        self.portal_bodies: list = []

    async def __call__(self, req: httpx.Request) -> httpx.Response:
        p = req.url.path
        if req.url.host == "127.0.0.1":
            if p == "/requests" and req.method == "POST":
                b = json.loads(req.content)
                rid = str(uuid.uuid4())
                self.reqs[rid] = {"b": b, "role": "A" if b["signal"][-2:] == "41" else "B", "polls": 0, "terminal": None}
                return httpx.Response(200, json={"request_id": rid, "connector_uri": f"https://world.org/verify?t={rid}"})
            if p.startswith("/requests/"):
                return self._poll(self.reqs.get(p.split("/")[-1]))
        if "/api/v4/verify/" in p:
            body = json.loads(req.content)
            self.portal_bodies.append(body)
            if self.portal:
                st, out = self.portal.pop(0)
                return httpx.Response(st, json=out)
            return httpx.Response(200, json={"success": True, "environment": "production", "action": body["action"],
                                             "nullifier": body["responses"][0]["nullifier"]})
        return httpx.Response(404)

    def _poll(self, e: dict | None) -> httpx.Response:
        if e is None:
            return httpx.Response(404, json={"error": "unknown_request"})
        if e["terminal"]:
            return httpx.Response(200, json=e["terminal"])
        e["polls"] += 1
        if e["polls"] <= self.polls:
            st = "waiting_for_connection" if e["polls"] == 1 else "awaiting_confirmation"
            return httpx.Response(200, json={"status": st, "error": None, "result": None})
        b = e["b"]
        who = "X" if self.same_human else e["role"]
        res = {"protocol_version": "4.0", "nonce": b["rp_context"]["nonce"], "action": b["action"],
               "environment": "production",
               "responses": [{"identifier": "proof_of_human", "issuer_schema_id": 1,
                              "nullifier": fake_nullifier(who, b["action"]),
                              "expires_at_min": b["rp_context"]["created_at"],
                              "proof": ["1", "2", "3", "4", "5"]}]}
        if self.mutate:
            res = self.mutate(res, e)
        e["terminal"] = {"status": "confirmed", "error": None, "result": res}
        return httpx.Response(200, json=e["terminal"])
