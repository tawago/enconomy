"""import_names on a small fixture sqlite built here. Never run against real data in tests."""
import hashlib
import sqlite3

import pytest

from backend.import_names import import_names, main
from backend.store import Store

OLD_SCHEMA = """CREATE TABLE ens_names (
  device_id TEXT PRIMARY KEY, label TEXT NOT NULL UNIQUE, claimed_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', tx TEXT, error TEXT);
  CREATE TABLE devices (device_id TEXT PRIMARY KEY);"""
ROWS = [("d1", "alice", "2026-01-01T00:00:00+00:00", "registered", "0xaa", None),
        ("d2", "bobby", "2026-01-02T00:00:00+00:00", "pending", None, None),
        ("d3", "carol", "2026-01-03T00:00:00+00:00", "failed", None, "boom")]


@pytest.fixture
def old(tmp_path):
    p = tmp_path / "old dir" / "pop.sqlite"     # a space, because the path goes through a URI
    p.parent.mkdir()
    db = sqlite3.connect(p)
    db.executescript(OLD_SCHEMA)
    db.executemany("INSERT INTO ens_names VALUES (?, ?, ?, ?, ?, ?)", ROWS)
    db.commit()
    db.close()
    return p


def rows(dst):
    s = Store(dst)
    try:
        return [tuple(r) for r in s.db.execute("SELECT device_id, label, claimed_at, status, tx, error, pubkey, "
                                               "trust_tier, statement FROM ens_names ORDER BY device_id")]
    finally:
        s.close()


def test_copies_rows_unchanged(old, tmp_path):
    dst = tmp_path / "ens.sqlite"
    assert import_names(old, dst) == {"read": 3, "added": 3, "kept": 0, "pending_added": 1}
    assert rows(dst) == [(*r, None, None, None) for r in ROWS]


def test_idempotent(old, tmp_path):
    dst = tmp_path / "ens.sqlite"
    import_names(old, dst)
    assert import_names(old, dst) == {"read": 3, "added": 0, "kept": 3, "pending_added": 0}
    assert len(rows(dst)) == 3


def test_existing_rows_stay(old, tmp_path):
    dst = tmp_path / "ens.sqlite"
    s = Store(dst)
    s.db.execute("INSERT INTO ens_names(device_id, label, claimed_at, status) VALUES ('new', 'alice', 't', 'registered')")
    s.close()
    assert import_names(old, dst)["added"] == 2
    assert ("new", "alice") in [(r[0], r[1]) for r in rows(dst)] and "d1" not in [r[0] for r in rows(dst)]


def test_source_is_read_only(old, tmp_path):
    before = hashlib.sha256(old.read_bytes()).hexdigest()
    import_names(old, tmp_path / "ens.sqlite")
    assert hashlib.sha256(old.read_bytes()).hexdigest() == before
    assert sorted(p.name for p in old.parent.iterdir()) == ["pop.sqlite"]


def test_cli_prints_counts_and_warns_about_pending(old, tmp_path, capsys):
    assert main([str(old), str(tmp_path / "ens.sqlite")]) == 0
    out = capsys.readouterr()
    assert "added 3" in out.out and "1 imported rows are pending" in out.err and "onchain" in out.err


def test_cli_missing_source_or_table(tmp_path, capsys):
    dst = tmp_path / "ens.sqlite"
    assert main([str(tmp_path / "nope.sqlite"), str(dst)]) == 1
    no_table = tmp_path / "empty.sqlite"
    sqlite3.connect(no_table).close()
    assert main([str(no_table), str(dst)]) == 1
    assert main([str(dst), str(dst)]) == 1
