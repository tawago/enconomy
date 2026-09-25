"""Persistence behind a small interface. SqliteStore(":memory:") for tests, a file for the server.

devices: one row per enrolled key (contract §2.2). sessions: a JSON document per session;
the session module owns its shape. Replay cache is in memory (lives 120 s, see auth.py).
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Protocol


class Store(Protocol):
    def add_nonce(self, nonce_hex: str, expires_ms: int) -> None: ...
    def take_nonce(self, nonce_hex: str, now_ms: int) -> bool: ...
    def get_device(self, device_id: str) -> dict | None: ...
    def put_device(self, dev: dict) -> None: ...
    def get_session(self, session_id: str) -> dict | None: ...
    def put_session(self, s: dict) -> None: ...


_SCHEMA = """
CREATE TABLE IF NOT EXISTS enroll_nonces (nonce TEXT PRIMARY KEY, expires_ms INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS devices (
  device_id TEXT PRIMARY KEY, pubkey TEXT NOT NULL, display_name TEXT NOT NULL, model TEXT NOT NULL,
  security_level TEXT NOT NULL, security_level_reported TEXT NOT NULL, attested INTEGER NOT NULL,
  chain_pem TEXT, root_sha256 TEXT, enrolled_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (session_id TEXT PRIMARY KEY, doc TEXT NOT NULL);
"""

_DEV_COLS = ["device_id", "pubkey", "display_name", "model", "security_level", "security_level_reported",
             "attested", "chain_pem", "root_sha256", "enrolled_at"]


class SqliteStore:
    def __init__(self, path: str | Path = ":memory:"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._db.executescript(_SCHEMA)

    def add_nonce(self, nonce_hex, expires_ms):
        with self._lock:
            self._db.execute("INSERT INTO enroll_nonces(nonce, expires_ms) VALUES (?, ?)", (nonce_hex, expires_ms))

    def take_nonce(self, nonce_hex, now_ms):
        """Single use: consumed even if it turns out expired or the enroll fails later."""
        with self._lock:
            row = self._db.execute("SELECT expires_ms, used FROM enroll_nonces WHERE nonce = ?", (nonce_hex,)).fetchone()
            if row is None or row["used"]:
                return False
            self._db.execute("UPDATE enroll_nonces SET used = 1 WHERE nonce = ?", (nonce_hex,))
            return now_ms <= row["expires_ms"]

    def get_device(self, device_id):
        with self._lock:
            row = self._db.execute("SELECT * FROM devices WHERE device_id = ?", (device_id,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["attested"] = bool(d["attested"])
        return d

    def put_device(self, dev):
        vals = [int(dev[c]) if c == "attested" else dev.get(c) for c in _DEV_COLS]
        with self._lock:
            self._db.execute(f"INSERT OR REPLACE INTO devices({','.join(_DEV_COLS)}) VALUES ({','.join('?' * len(_DEV_COLS))})", vals)

    def get_session(self, session_id):
        with self._lock:
            row = self._db.execute("SELECT doc FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        return None if row is None else json.loads(row["doc"])

    def put_session(self, s):
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO sessions(session_id, doc) VALUES (?, ?)", (s["session_id"], json.dumps(s)))
