"""Writes tests/fixtures/presence_vector.json: run from server/ with `uv run python -m tests.make_presence_vector`.

A real NEAR flow through the app with test phones, signed by a throwaway key that is in the file on purpose. Keys and
data go to a temp dir. An outside implementation should verify the signatures and reproduce the canonical bytes.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from pop import presence
from pop.main import Settings, create_app
from pop.store import SqliteStore
from tests.phones import TEST_ANDROID_ROOTS, Clock
from tests.sim import Knobs, World

OUT = Path(__file__).parent / "fixtures" / "presence_vector.json"
THROWAWAY_KEY = "7e57" * 16


def main() -> None:
    sk = ec.derive_private_key(int(THROWAWAY_KEY, 16), ec.SECP256R1())
    clock = Clock()
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "presence.pem").write_bytes(sk.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                          serialization.NoEncryption()))
        cfg = Settings(db=":memory:", now_ms=clock, data_dir=tmp, android_roots=TEST_ANDROID_ROOTS,
                       issuer_key_file=str(d / "issuer.pem"),
                       presence_key_file=str(d / "presence.pem"), worldid_signing_key_file=str(d / "worldid-rp.key"),
                       worldid_bg_poll=False, worldid_poll_s=0.0)
        client = TestClient(create_app(cfg, SqliteStore(":memory:")))
        w = World(client, clock, 30, Knobs(), Knobs(sr=44100, mono_off_ns=9_000_000_000, sync_err_ms=-3, out_lat_ms=25))
        w.pair(attested=True)
        w.run_attempt(0)
        record = w.result().json()["presence"]
        statement = w.a.get("/v1/device/statement").json()
        pub = client.get("/v1/config").json()["presence"]["pubkey"]
    assert record["body"]["verdict"] == "NEAR"
    OUT.write_text(json.dumps({
        "note": "Throwaway test key and test phones, nothing real. Signatures are randomized: verify them, don't compare.",
        "throwaway_private_key_hex": THROWAWAY_KEY, "pubkey_hex": pub,
        "record_tag": presence.TAG_RECORD.decode(), "record": record,
        "record_canonical_hex": presence.canonical(record["body"]).hex(),
        "statement_tag": presence.TAG_STATEMENT.decode(), "statement": statement,
        "statement_canonical_hex": presence.canonical(statement["body"]).hex(),
    }, indent=1) + "\n")


if __name__ == "__main__":
    main()
