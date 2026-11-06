"""Test phones and a fake chain. The core key is the vector's throwaway key, so vector records verify as they are."""
from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from backend.core import STATEMENT_FORMAT, TAG_RECORD, TAG_STATEMENT, canonical, device_id
from backend.main import claim_message

VECTOR = json.loads((Path(__file__).parent / "fixtures/presence_vector.json").read_text())
CORE_KEY = ec.derive_private_key(int(VECTOR["throwaway_private_key_hex"], 16), ec.SECP256R1())
CORE_PUB = bytes.fromhex(VECTOR["pubkey_hex"])


def sign_raw(sk, msg: bytes) -> bytes:
    r, s = decode_dss_signature(sk.sign(msg, ec.ECDSA(hashes.SHA256())))
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def core_sign(tag: bytes, body: dict, key=CORE_KEY) -> dict:
    return {"body": body, "sig_b64": base64.b64encode(sign_raw(key, tag + canonical(body))).decode()}


def sign_record(body: dict, key=CORE_KEY) -> dict:
    return core_sign(TAG_RECORD, body, key)


class Clock:
    def __init__(self, ms=1_790_000_000_000):
        self.ms = ms

    def __call__(self) -> int:
        self.ms += 1   # two requests never share a ts by accident
        return self.ms


class FakeChain:
    def __init__(self):
        self.calls, self.onchain = [], set()
        self.fail = None
        self.busy = self.overlapped = False

    def counts(self, label):
        return label in self.onchain, 0, 0, 0

    def _act(self, what, label):
        self.overlapped = self.overlapped or self.busy
        self.busy = True
        time.sleep(0.005)
        self.busy = False
        self.calls.append((what, label))
        if self.fail:
            raise RuntimeError(self.fail)

    def register(self, label):
        self._act("register", label)
        self.onchain.add(label)
        return "0x" + hashlib.sha256(label.encode()).hexdigest()

    def touch(self, label):
        self._act("touch", label)


class Phone:
    def __init__(self, client, clock, platform="android", attested=True, core_key=CORE_KEY):
        self.client, self.clock = client, clock
        self.platform, self.attested, self.core_key = platform, attested, core_key
        self.sk = ec.generate_private_key(ec.SECP256R1())
        self.pub = self.sk.public_key().public_bytes(serialization.Encoding.X962,
                                                     serialization.PublicFormat.UncompressedPoint)
        self.device_id = device_id(self.pub)

    def statement(self, **over) -> dict:
        body = {"format": STATEMENT_FORMAT, "device_id": self.device_id, "pubkey": self.pub.hex(),
                "attested": self.attested, "platform": self.platform,
                "trust_tier": "tee" if self.attested else "unattested", "issued_at_ms": self.clock.ms, **over}
        return core_sign(TAG_STATEMENT, body, self.core_key)

    def signed(self, label, statement=None, ts=None) -> dict:
        ts = self.clock() if ts is None else ts
        sig = sign_raw(self.sk, claim_message(label, self.device_id, ts))
        return {"device_statement": statement or self.statement(), "label": label, "ts": ts,
                "sig_b64": base64.b64encode(sig).decode()}

    def claim(self, label, **kw):
        return self.client.post("/v1/names/claim", json=self.signed(label, **kw))

    def read(self):
        return self.client.post("/v1/names/read", json=self.signed(None))


def wait_for(cond, timeout=3.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return
        time.sleep(0.005)
    raise AssertionError("condition not met in time")


def settled(app) -> bool:
    return not app.state.store.names_with_status("pending")
