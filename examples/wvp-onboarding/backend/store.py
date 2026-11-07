"""The example's own sqlite: requests keyed by ctx_hash, sessions already spent on a name, and names the admin added by hand."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from backend.core import canonical

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
  ctx_hash TEXT PRIMARY KEY, label TEXT NOT NULL, name TEXT NOT NULL, address TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', ens TEXT, last_error TEXT, created_ms INTEGER NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS one_issued_per_label ON requests(label) WHERE status = 'issued';
CREATE TABLE IF NOT EXISTS used_sessions (
  session_id TEXT PRIMARY KEY, ctx_hash TEXT NOT NULL, body TEXT NOT NULL, sig_b64 TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS names (label TEXT PRIMARY KEY, name TEXT NOT NULL, created_ms INTEGER NOT NULL);
"""


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

    def get(self, ctx_hash: str) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM requests WHERE ctx_hash = ?", (ctx_hash,)).fetchone()
        return None if row is None else dict(row)

    def label_issued(self, label: str) -> bool:
        with self.lock:
            return self.db.execute("SELECT 1 FROM requests WHERE label = ? AND status = 'issued' UNION ALL SELECT 1 FROM names WHERE label = ?",
                                   (label, label)).fetchone() is not None

    def known_names(self) -> list[dict]:
        """Issued through onboarding, or added on the admin page."""
        with self.lock:
            rows = self.db.execute("SELECT label, name FROM requests WHERE status = 'issued' UNION SELECT label, name FROM names ORDER BY label")
            return [dict(r) for r in rows]

    def add_name(self, label: str, name: str, now_ms: int) -> None:
        with self.lock:
            self.db.execute("INSERT OR IGNORE INTO names(label, name, created_ms) VALUES (?, ?, ?)", (label, name, now_ms))

    def free_label(self, label: str) -> None:
        """The name was cleared on chain. An approval for it goes too, so giving it again needs a new yes from the admin."""
        with self.lock:
            self.db.execute("DELETE FROM names WHERE label = ?", (label,))
            self.db.execute("UPDATE requests SET status = 'cleared' WHERE label = ? AND status IN ('issued', 'approved')", (label,))

    def put(self, ctx_hash: str, label: str, name: str, address: str, now_ms: int) -> dict:
        """The same name and address is the same request. Asking again after a decline or a clear puts it back in front of the admin."""
        with self.lock:
            self.db.execute("INSERT OR IGNORE INTO requests(ctx_hash, label, name, address, created_ms) VALUES (?, ?, ?, ?, ?)",
                            (ctx_hash, label, name, address, now_ms))
            self.db.execute("UPDATE requests SET status = 'pending', ens = NULL, last_error = NULL WHERE ctx_hash = ? AND status IN ('declined', 'cleared')", (ctx_hash,))
        return self.get(ctx_hash)

    def pending(self) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM requests WHERE status = 'pending' ORDER BY created_ms LIMIT 50")]

    def decide(self, ctx_hash: str, status: str) -> bool:
        """Only a pending request can be decided."""
        with self.lock:
            cur = self.db.execute("UPDATE requests SET status = ? WHERE ctx_hash = ? AND status = 'pending'", (status, ctx_hash))
            return cur.rowcount == 1

    def claim_session(self, record: dict, ctx_hash: str) -> bool:
        """False if this session was spent already."""
        body = record["body"]
        with self.lock:
            cur = self.db.execute("INSERT OR IGNORE INTO used_sessions(session_id, ctx_hash, body, sig_b64) VALUES (?, ?, ?, ?)",
                                  (body["session_id"], ctx_hash, canonical(body).decode(), record["sig_b64"]))
            return cur.rowcount == 1

    def release_session(self, session_id: str) -> None:
        """The script failed, so the session bought nothing. The same record may try again."""
        with self.lock:
            self.db.execute("DELETE FROM used_sessions WHERE session_id = ?", (session_id,))

    def issued(self, ctx_hash: str, ens: dict) -> None:
        with self.lock:
            self.db.execute("UPDATE requests SET status = 'issued', ens = ?, last_error = NULL WHERE ctx_hash = ?",
                            (json.dumps(ens), ctx_hash))

    def set_error(self, ctx_hash: str, error: str) -> None:
        with self.lock:
            self.db.execute("UPDATE requests SET last_error = ? WHERE ctx_hash = ?", (error, ctx_hash))
