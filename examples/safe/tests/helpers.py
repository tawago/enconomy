"""Test phones and records. The core key is the vector's throwaway key, so vector records verify as they are."""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from backend.core import TAG_RECORD, canonical, device_id
from backend.safe_tx import owner_message

VECTOR = json.loads((Path(__file__).parent / "fixtures/presence_vector.json").read_text())
CORE_KEY = ec.derive_private_key(int(VECTOR["throwaway_private_key_hex"], 16), ec.SECP256R1())
CORE_PUB = bytes.fromhex(VECTOR["pubkey_hex"])

T0_MS = 1_790_000_003_000
NOW_MS = T0_MS + 60_000
CHAIN = 11155111
SAFE = "0x" + "5afe" * 10
SID = "ab" * 16
Z = "0x" + "00" * 20


def sign_raw(sk, msg: bytes) -> bytes:
    r, s = decode_dss_signature(sk.sign(msg, ec.ECDSA(hashes.SHA256())))
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def sign_record(body: dict, key=CORE_KEY) -> dict:
    return {"body": body, "sig_b64": base64.b64encode(sign_raw(key, TAG_RECORD + canonical(body))).decode()}


def tx(**k) -> dict:
    t = {"to": "0x" + "11" * 20, "value": "1000", "data": "0x", "operation": 0, "safe_tx_gas": "0", "base_gas": "0",
         "gas_price": "0", "gas_token": Z, "refund_receiver": Z, "nonce": "0"}
    t.update(k)
    return t


class Phone:
    def __init__(self, attested=True):
        self.attested = attested
        self.sk = ec.generate_private_key(ec.SECP256R1())
        self.pub = self.sk.public_key().public_bytes(serialization.Encoding.X962,
                                                     serialization.PublicFormat.UncompressedPoint)

    def owner_sig(self, ctx_hash: str) -> dict:
        sig = sign_raw(self.sk, owner_message(bytes.fromhex(ctx_hash[2:])))
        return {"pubkey": self.pub.hex(), "sig": "0x" + sig.hex()}

    def device(self) -> dict:
        return {"device_id": device_id(self.pub), "pubkey": self.pub.hex(), "attested": self.attested}

    def half(self, name: str) -> dict:
        raw = f"transcript {name}".encode()
        return {"transcript_b64": base64.b64encode(raw).decode(), "sha256": hashlib.sha256(raw).hexdigest(),
                "sig_b64": base64.b64encode(sign_raw(self.sk, raw)).decode()}


def near_record(a: Phone, b: Phone, ctx_hash: str, sid=SID, verdict="NEAR", consumer=SAFE, chain_id=CHAIN,
                t0_ms=T0_MS, key=CORE_KEY) -> dict:
    """A record two test phones could really have, in the shape the core signs."""
    finished = datetime.fromtimestamp((t0_ms + 1500) / 1000, timezone.utc).isoformat(timespec="milliseconds")
    return sign_record({"format": "pop-presence-v1", "session_id": sid, "t0_ms": t0_ms, "attempt": 0,
                        "context": {"chain_id": chain_id, "consumer": consumer, "ctx_hash": ctx_hash},
                        "not_before": t0_ms // 1000 - 3, "verdict": verdict, "reason": None, "finished_at": finished,
                        "transcripts": {"A": a.half("A"), "B": b.half("B")},
                        "devices": {"A": a.device(), "B": b.device()},
                        "zk": {"status": "none", "A": None, "B": None, "pair": None}}, key)
