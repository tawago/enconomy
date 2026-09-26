"""Parity: Python signer vs official Node signer (@worldcoin/idkit-core/signing 4.2.4).

Node side is driven by parity/sign.mjs, which stubs crypto.getRandomValues (bytes 0..31)
and Date.now so both sides sign identical inputs.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.signing import address_of, hash_to_field, recover_signer, sign_request

PARITY = Path(__file__).resolve().parents[1] / "parity"
RAND = bytes(range(32))
KEY = "0x" + "ab" * 32


def node_sign(key, action, now):
    args = ["node", str(PARITY / "sign.mjs"), action if action is not None else "", str(now)]
    env = {**os.environ, "SIGN_KEY": key}  # env, not argv: keeps the key out of ps and tracebacks
    r = subprocess.run(args, capture_output=True, text=True, cwd=PARITY, env=env)
    assert r.returncode == 0, "sign.mjs failed"
    out = r.stdout
    return json.loads(out)


node_ok = shutil.which("node") and (PARITY / "node_modules" / "@worldcoin" / "idkit-core").exists()
needs_node = pytest.mark.skipif(not node_ok, reason="run `npm install` in backend/parity")


def test_hash_to_field_vectors():
    assert hash_to_field(b"").hex() == "00c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a4"
    assert hash_to_field(b"test_signal").hex() == "00c1636e0a961a3045054c4d61374422c31a95846b8442f0927ad2ff1d6112ed"


@pytest.mark.parametrize("action,sig", [
    (None, "0x14f693175773aed912852a601e9c0fd30f2afe2738d31388316232ce6f64ae9e4edbfb19d81c4229ba9c9fca78ede4b28956b7ba4415f08d957cbc1b3bdaa4021b"),
    ("test-action", "0x05594adb6c1495768a38d523d7d6ee6356b2c31231919198794ed022ade7d08f73753f83bd167067d99c9b969d28e9222315837c66af25867b041273a6d5056f1b"),
])
def test_official_doc_vectors(action, sig):
    s = sign_request(KEY, action=action, rand=RAND, now=1700000000)
    assert s["nonce"] == "0x008ae1aa597fa146ebd3aa2ceddf360668dea5e526567e92b0321816a4e895bd"
    assert s["sig"] == sig


@needs_node
@pytest.mark.parametrize("action", [None, "test-action", "spike-1700000000000", "日本語-アクション", "a" * 300])
@pytest.mark.parametrize("now", [1700000000, 1790000000])
def test_parity_with_node(action, now):
    n = node_sign(KEY, action, now)
    p = sign_request(KEY, action=action, rand=RAND, now=now)
    assert p["msg"] == n["msg"]
    assert p["nonce"] == n["nonce"]
    assert p["created_at"] == n["createdAt"] and p["expires_at"] == n["expiresAt"]
    assert p["sig"] == n["sig"]


@needs_node
def test_parity_with_real_key():
    """Same comparison with the real .env signing key (value never printed)."""
    from dotenv import dotenv_values
    env = dotenv_values(Path(__file__).resolve().parents[2] / ".env")
    key = env.get("WORLD_SIGNING_KEY")
    if not key:
        pytest.skip("no .env key")
    k = key if key.startswith("0x") else "0x" + key
    n = node_sign(k, "spike-parity", 1790000000)
    p = sign_request(key, action="spike-parity", rand=RAND, now=1790000000)
    assert p["sig"] == n["sig"], "python/node signature mismatch on real key"
    addr = env.get("WORLD_SIGNER_ADDRESS")
    assert recover_signer(p["msg"], p["sig"]).lower() == address_of(key).lower()
    if addr:
        assert address_of(key).lower() == addr.lower(), "signing key does not match WORLD_SIGNER_ADDRESS"
