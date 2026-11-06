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


def keccak256(data: bytes) -> bytes:
    """Keccak-f[1600] with rate 136, the original padding: hashlib's sha3_256 isn't this. Golden values in test_bridge."""
    def rol(a, n):
        n %= 64
        return ((a << n) | (a >> (64 - n))) & (2 ** 64 - 1)

    def f(A):
        R = 1
        for _ in range(24):
            C = [A[x][0] ^ A[x][1] ^ A[x][2] ^ A[x][3] ^ A[x][4] for x in range(5)]
            D = [C[(x + 4) % 5] ^ rol(C[(x + 1) % 5], 1) for x in range(5)]
            A = [[A[x][y] ^ D[x] for y in range(5)] for x in range(5)]
            x, y = 1, 0
            cur = A[x][y]
            for t in range(24):
                x, y = y, (2 * x + 3 * y) % 5
                cur, A[x][y] = A[x][y], rol(cur, (t + 1) * (t + 2) // 2)
            for y in range(5):
                T = [A[x][y] for x in range(5)]
                for x in range(5):
                    A[x][y] = T[x] ^ (~T[(x + 1) % 5] & T[(x + 2) % 5])
            for j in range(7):
                R = ((R << 1) ^ ((R >> 7) * 0x71)) % 256
                if R & 2:
                    A[0][0] ^= 1 << ((1 << j) - 1)
        return A

    pad = 136 - len(data) % 136
    msg = bytearray(data) + b"\x00" * pad
    msg[len(data)] ^= 0x01
    msg[-1] ^= 0x80
    A = [[0] * 5 for _ in range(5)]
    for off in range(0, len(msg), 136):
        for i in range(17):
            A[i % 5][i // 5] ^= int.from_bytes(msg[off + 8 * i:off + 8 * i + 8], "little")
        A = f(A)
    return b"".join(A[i % 5][i // 5].to_bytes(8, "little") for i in range(4))


class FakeHttp:
    """url -> (status, json); anything else answers 404, like the bundle before the pair proof."""

    def __init__(self):
        self.routes, self.calls = {}, []

    def __call__(self, url):
        self.calls.append(url)
        got = self.routes.get(url, (404, None))
        if isinstance(got, Exception):
            raise got
        return got


class FakeChain:
    """MeetResolver as far as the bridge can see it. calls: every tx, in order."""

    def __init__(self):
        self.calls, self.onchain = [], set()
        self.fail = None
        self.busy = self.overlapped = False
        self.meetings, self.would_revert, self.send_revert = {}, None, None
        self.verify_result = "true"
        self.me = "0x" + "aa" * 20

    def keccak_hex(self, hexdata):
        return "0x" + keccak256(bytes.fromhex(hexdata.removeprefix("0x"))).hex()

    def keccak_str(self, s):
        return self.keccak_hex(s.encode().hex())

    def is_fork(self):
        return False

    def tx_link(self, h):
        return h

    def revert_name(self, msg):
        return msg

    def meeting(self, mid):
        return self.meetings.get(mid, {"exists": False, "zk": False, "voided": False})

    def _tx(self, what, args):
        self.calls.append((what, args))
        if self.fail:
            raise RuntimeError(self.fail)
        return {"transactionHash": f"0x{what}{len(self.calls)}", "gasUsed": "0x10"}

    def record_would(self, mid, lha, lhb, tb, ev):
        if self.would_revert:
            raise RuntimeError(self.would_revert)
        return "true"

    def record(self, mid, lha, lhb, tb, ev):
        if self.send_revert:
            raise RuntimeError(self.send_revert)
        rc = self._tx("record", (mid, lha, lhb, tb, ev))
        self.meetings[mid] = {"exists": True, "zk": False, "voided": False}
        return rc

    def verify_call(self, verifier, proof, inputs):
        return self.verify_result

    def verify_send(self, verifier, verify_log, proof, inputs):
        return self._tx("verify", (verifier, verify_log, proof, inputs))

    def mark_zk(self, mid):
        rc = self._tx("mark", mid)
        self.meetings[mid]["zk"] = True
        return rc

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
        self.transcript_sigs = {}

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


def near_record(a: Phone, b: Phone, sid: str, t0_ms=1_790_000_003_000, verdict="NEAR", zk=None) -> dict:
    """A record two test phones could really have: both signed their transcript, the core key signed the body."""
    def half(p, name):
        raw = f"transcript {sid} {name}".encode()
        # ECDSA is randomized, and a later record of a session must match outside zk: sign once
        sig = p.transcript_sigs.setdefault(raw, sign_raw(p.sk, raw))
        return {"transcript_b64": base64.b64encode(raw).decode(), "sha256": hashlib.sha256(raw).hexdigest(),
                "sig_b64": base64.b64encode(sig).decode()}

    return sign_record({"format": "pop-presence-v1", "session_id": sid, "t0_ms": t0_ms, "verdict": verdict,
                        "transcripts": {"A": half(a, "A"), "B": half(b, "B")},
                        "devices": {"A": {"device_id": a.device_id, "pubkey": a.pub.hex()},
                                    "B": {"device_id": b.device_id, "pubkey": b.pub.hex()}},
                        "zk": zk or {"status": "none", "A": None, "B": None, "pair": None}})


def wait_for(cond, timeout=3.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return
        time.sleep(0.005)
    raise AssertionError("condition not met in time")


def settled(app) -> bool:
    return not app.state.store.names_with_status("pending")
