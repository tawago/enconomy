"""ENS left the core for examples/ens-meetings. Old databases keep their ens_names rows as they were, for its import script."""
import sqlite3

from fastapi.testclient import TestClient

from pop.main import Settings, create_app
from pop.store import SqliteStore
from tests.phones import TEST_ANDROID_ROOTS, Phone, make_chain

OLD_ENS_NAMES = """CREATE TABLE ens_names (
  device_id TEXT PRIMARY KEY, label TEXT NOT NULL UNIQUE, claimed_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', tx TEXT, error TEXT)"""  # as pop/ens.py made it


def _tables(db):
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_routes_are_gone(client, clock):
    assert client.get("/v1/device/ens").status_code == 404
    assert client.post("/v1/device/ens", json={"label": "carol"}).status_code == 404
    p = Phone(client, clock, "phone")
    n = client.get("/v1/enroll/nonce").json()["nonce"]
    assert client.post("/v1/enroll", json=p.enroll_body(n, make_chain(p.sk.public_key(), bytes.fromhex(n)))).status_code == 200
    assert p.get("/v1/device/ens").status_code == 404
    assert p.post("/v1/device/ens", {"label": "carol"}).status_code == 404


def test_fresh_store_has_no_ens_names(client):
    assert "ens_names" not in _tables(SqliteStore(":memory:")._db)
    assert "ens_names" not in _tables(client.app.state.store._db)


def test_old_sqlite_with_ens_names_still_opens(tmp_path, clock):
    path = tmp_path / "old" / "pop.sqlite"
    path.parent.mkdir()
    old = sqlite3.connect(path)
    old.execute(OLD_ENS_NAMES)
    row = ("d1", "carol", "2026-09-26T00:00:00Z", "registered", "0xabc", None)
    old.execute("INSERT INTO ens_names VALUES (?, ?, ?, ?, ?, ?)", row)
    old.commit()
    old.close()

    store = SqliteStore(path)
    cfg = Settings(db=str(path), now_ms=clock, data_dir=str(tmp_path), android_roots=TEST_ANDROID_ROOTS,
                   issuer_key_file=str(tmp_path / "issuer.pem"),
                   presence_key_file=str(tmp_path / "presence.pem"))
    client = TestClient(create_app(cfg, store))
    assert client.get("/v1/config").status_code == 200
    assert client.get("/v1/device/ens").status_code == 404
    assert tuple(store._db.execute("SELECT * FROM ens_names").fetchone()) == row
