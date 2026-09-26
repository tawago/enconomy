"""Attestation body for one Safe spend, produced by the REAL server code (TEST KEYS ONLY).

Phones 0xA1 / 0xB1 enroll, open a safe-tx session on Ethereum Sepolia, sign the owner message through
POST /safe/owner-sig; the session is then marked done (NEAR by default, production humans, attested devices)
and GET /v1/session/{sid}/attestation signs pop-safe-v2 with attester key 0xC0FFEE.
usage (from relayer/): uv run --project ../server python test/make_fixture.py <safe> <to> <wei> <nonce> [NOT_NEAR]
"""
import json
import sys
import tempfile
from pathlib import Path

SERVER = Path(__file__).resolve().parents[2] / "server"
sys.path.insert(0, str(SERVER))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from pop.consumers import safe_tx as S  # noqa: E402
from pop.crypto import device_id, pub_bytes, sign_raw  # noqa: E402
from pop.main import Settings, create_app  # noqa: E402
from pop.store import SqliteStore  # noqa: E402
from tests.phones import Phone  # noqa: E402
from tests.test_safe_tx import ctx_of, finish, tx  # noqa: E402

safe, to, wei, nonce = sys.argv[1].lower(), sys.argv[2].lower(), sys.argv[3], sys.argv[4]
verdict = sys.argv[5] if len(sys.argv) > 5 else "NEAR"
tmp = Path(tempfile.mkdtemp())
(tmp / "attest.pem").write_bytes(ec.derive_private_key(0xC0FFEE, ec.SECP256R1()).private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
cfg = Settings(db=":memory:", data_dir=str(tmp), issuer_key_file=str(tmp / "issuer.pem"),
               worldid_signing_key_file=str(tmp / "rp.key"), attest_key_file=str(tmp / "attest.pem"),
               worldid_rp_id="rp_0123456789abcdef", worldid_bg_poll=False)
c = TestClient(create_app(cfg, SqliteStore(":memory:")))
clock = cfg.now_ms
phones = []
for name, k in (("A", 0xA1), ("B", 0xB1)):
    p = Phone(c, clock, name, "Pixel 8")
    p.sk = ec.derive_private_key(k, ec.SECP256R1())
    p.pub = pub_bytes(p.sk.public_key())
    p.device_id = device_id(p.pub)
    assert p.enroll().status_code == 200
    phones.append(p)
a, b = phones
ctx = ctx_of(11155111, tx(to=to, value=wei, nonce=nonce), safe=safe)
r = a.post("/v1/session", {"context": ctx})
assert r.status_code == 200, r.text
sid = r.json()["session_id"]
assert b.post(f"/v1/session/{sid}/join", {"join_token": r.json()["join_token"]}).status_code == 200
h = bytes.fromhex(ctx["ctx_hash"][2:])
for p in phones:
    r = p.post(f"/v1/session/{sid}/safe/owner-sig", {"sig": "0x" + sign_raw(p.sk, S.owner_message(h)).hex()})
    assert r.status_code == 200, r.text
finish(c, sid, a, b, verdict=verdict, sigs=False)
body = c.get(f"/v1/session/{sid}/attestation").json()
print(json.dumps(body, indent=1))
