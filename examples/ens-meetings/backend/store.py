"""The example's own sqlite: ens_names (one label per device, set once, never renamed) and presence_records."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from pathlib import Path

from backend.core import canonical, zk_progress
from backend.errors import ApiError

PARENT = "enconomy.eth"
LABEL_RE = re.compile(r"^[a-z0-9-]{3,32}$")   # same rule as contracts/script/ens.sh

# pubkey, trust_tier, statement: null on rows imported from an old core database
SCHEMA = """
CREATE TABLE IF NOT EXISTS ens_names (
  device_id TEXT PRIMARY KEY, label TEXT NOT NULL UNIQUE, claimed_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', tx TEXT, error TEXT,
  pubkey TEXT, trust_tier TEXT, statement TEXT);
CREATE TABLE IF NOT EXISTS presence_records (
  session_id TEXT PRIMARY KEY, body TEXT NOT NULL, sig_b64 TEXT NOT NULL, verdict TEXT,
  received_at TEXT NOT NULL, updated_at TEXT NOT NULL);
"""


def view(row: dict | None) -> dict:
    if row is None:
        return {"label": None, "name": None, "status": "none", "tx": None}
    return {"label": row["label"], "name": f"{row['label']}.{PARENT}", "status": row["status"], "tx": row["tx"]}


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

    # -- names
    def get_name(self, device_id: str) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM ens_names WHERE device_id = ?", (device_id,)).fetchone()
        return None if row is None else dict(row)

    def claim(self, statement: dict, label, now_iso: str) -> dict:
        """statement: already verified. The row comes back as inserted, pending, whatever the worker does next."""
        body = statement["body"]
        dev = body["device_id"]
        if not isinstance(label, str) or not LABEL_RE.fullmatch(label):
            raise ApiError(400, "bad_label", "3-32 chars of a-z, 0-9, -")
        with self.lock:
            if (have := self.get_name(dev)) is not None and have["status"] != "failed":
                raise ApiError(409, "already_claimed", f"this phone is {have['label']}.{PARENT}")
            self.db.execute("BEGIN")
            try:
                if have is not None:  # could not be registered: never onchain, so a retry is not a rename
                    self.db.execute("DELETE FROM ens_names WHERE device_id = ?", (dev,))
                self.db.execute("INSERT INTO ens_names(device_id, label, claimed_at, pubkey, trust_tier, statement) "
                                "VALUES (?, ?, ?, ?, ?, ?)",
                                (dev, label, now_iso, body["pubkey"], body.get("trust_tier"),
                                 json.dumps(statement, sort_keys=True)))
            except sqlite3.IntegrityError:
                self.db.execute("ROLLBACK")
                raise ApiError(409, "label_taken", f"{label}.{PARENT} is taken") from None
            self.db.execute("COMMIT")
            return self.get_name(dev)

    def names_with_status(self, status: str) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM ens_names WHERE status = ?", (status,))]

    def set_claim(self, device_id: str, label: str, status: str, tx: str | None = None, error: str | None = None) -> None:
        with self.lock:
            self.db.execute("UPDATE ens_names SET status = ?, tx = COALESCE(?, tx), error = ? "
                            "WHERE device_id = ? AND label = ?", (status, tx, error, device_id, label))

    # -- presence records
    def get_record(self, session_id: str) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM presence_records WHERE session_id = ?", (session_id,)).fetchone()
        return None if row is None else dict(row)

    def put_record(self, body: dict, sig_b64: str, now_iso: str) -> str:
        """stored, updated (more proofs than before) or unchanged. Only zk may differ between records of a session;
        the core guarantees it, so anything else is 409. Bodies are kept as canonical text, so they still verify."""
        text = canonical(body).decode()
        sid = body["session_id"]
        with self.lock:
            have = self.get_record(sid)
            if have is None:
                self.db.execute("INSERT INTO presence_records(session_id, body, sig_b64, verdict, received_at, updated_at) "
                                "VALUES (?, ?, ?, ?, ?, ?)", (sid, text, sig_b64, body.get("verdict"), now_iso, now_iso))
                return "stored"
            old = json.loads(have["body"])
            if _fixed(old) != _fixed(body):
                raise ApiError(409, "record_conflict", "differs from the stored record outside zk")
            if have["body"] == text or zk_progress(body) < zk_progress(old):
                return "unchanged"
            self.db.execute("UPDATE presence_records SET body = ?, sig_b64 = ?, updated_at = ? WHERE session_id = ?",
                            (text, sig_b64, now_iso, sid))
            return "updated"


def _fixed(body: dict) -> bytes:
    return canonical({k: v for k, v in body.items() if k != "zk"})
