"""The example's own sqlite. wid_state has one row per (session_nonce, role). wid_nullifiers is the only replay
guard, because the Portal answers 200 on reuse. meetings holds the answer for each delivered record."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS wid_state (
  session_nonce TEXT NOT NULL, role TEXT NOT NULL, session_id TEXT NOT NULL, pubkey TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'idle', error TEXT, detail TEXT, issued_nonces TEXT NOT NULL DEFAULT '[]',
  rp_nonce TEXT, request_id TEXT, connector_uri TEXT, request_created_s INTEGER, nullifier TEXT, verified_at INTEGER,
  created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
  PRIMARY KEY (session_nonce, role));
CREATE INDEX IF NOT EXISTS wid_state_nonce ON wid_state (session_nonce);
CREATE TABLE IF NOT EXISTS wid_nullifiers (
  rp_id TEXT NOT NULL, action TEXT NOT NULL, nullifier TEXT NOT NULL,
  env TEXT NOT NULL, kind TEXT NOT NULL, subject TEXT NOT NULL, created_at INTEGER NOT NULL,
  PRIMARY KEY (rp_id, env, action, nullifier));
CREATE TABLE IF NOT EXISTS meetings (
  session_nonce TEXT PRIMARY KEY, answer TEXT NOT NULL, received_at INTEGER NOT NULL);
"""

FIELDS = {"status", "error", "detail", "issued_nonces", "rp_nonce", "request_id", "connector_uri", "request_created_s",
          "nullifier", "verified_at"}


class Store:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.db.executescript(SCHEMA)

    def close(self) -> None:
        with self.lock:
            self.db.close()

    # -- state
    def get(self, nonce: str, role: str) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM wid_state WHERE session_nonce = ? AND role = ?", (nonce, role)).fetchone()
        if row is None:
            return None
        return dict(row) | {"issued_nonces": json.loads(row["issued_nonces"])}

    def session_id_for(self, nonce: str) -> str | None:
        with self.lock:
            row = self.db.execute("SELECT session_id FROM wid_state WHERE session_nonce = ? LIMIT 1", (nonce,)).fetchone()
        return None if row is None else row["session_id"]

    def create(self, nonce: str, role: str, session_id: str, pubkey: str, now_s: int) -> dict:
        with self.lock:
            self.db.execute("INSERT INTO wid_state(session_nonce, role, session_id, pubkey, created_at, updated_at) "
                            "VALUES (?, ?, ?, ?, ?, ?)", (nonce, role, session_id, pubkey, now_s, now_s))
        return self.get(nonce, role)

    def update(self, nonce: str, role: str, now_s: int, **fields) -> None:
        assert set(fields) <= FIELDS, fields
        if "issued_nonces" in fields:
            fields["issued_nonces"] = json.dumps(fields["issued_nonces"])
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self.lock:
            self.db.execute(f"UPDATE wid_state SET {sets}, updated_at = ? WHERE session_nonce = ? AND role = ?",
                            (*fields.values(), now_s, nonce, role))

    # -- nullifiers
    def reserve(self, rp_id: str, env: str, action: str, nullifier: str, subject: str, now_s: int) -> str | None:
        """Insert-or-conflict in one step. None = inserted; else the subject already holding it."""
        with self.lock:
            try:
                self.db.execute("INSERT INTO wid_nullifiers VALUES (?,?,?,?,?,?,?)",
                                (rp_id, action, nullifier, env, "session", subject, now_s))
                return None
            except sqlite3.IntegrityError:
                row = self.db.execute("SELECT subject FROM wid_nullifiers WHERE rp_id=? AND env=? AND action=? "
                                      "AND nullifier=?", (rp_id, env, action, nullifier)).fetchone()
                return row["subject"]

    def release(self, rp_id: str, env: str, action: str, nullifier: str, subject: str) -> None:
        with self.lock:
            self.db.execute("DELETE FROM wid_nullifiers WHERE rp_id=? AND env=? AND action=? AND nullifier=? "
                            "AND subject=?", (rp_id, env, action, nullifier, subject))

    def nullifier_rows(self) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM wid_nullifiers")]

    # -- meetings
    def put_meeting(self, nonce: str, answer: dict, now_s: int) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO meetings VALUES (?, ?, ?)", (nonce, json.dumps(answer), now_s))

    def get_meeting(self, nonce: str) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT answer FROM meetings WHERE session_nonce = ?", (nonce,)).fetchone()
        return None if row is None else json.loads(row["answer"])
