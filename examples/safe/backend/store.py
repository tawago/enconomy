"""The example's own sqlite: spends, owner signatures, signed sessions and relay jobs. Spends are keyed by their
safeTxHash, so a row can't be overwritten with a different transaction."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from backend.core import canonical

SCHEMA = """
CREATE TABLE IF NOT EXISTS spends (
  ctx_hash TEXT PRIMARY KEY, chain_id INTEGER NOT NULL, safe TEXT NOT NULL, safe_tx TEXT NOT NULL, what TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS owner_sigs (
  ctx_hash TEXT NOT NULL, pubkey TEXT NOT NULL, sig TEXT NOT NULL, PRIMARY KEY (ctx_hash, pubkey));
CREATE TABLE IF NOT EXISTS attestations (
  session_id TEXT PRIMARY KEY, ctx_hash TEXT NOT NULL, att TEXT NOT NULL, body TEXT NOT NULL, sig_b64 TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS relay_jobs (
  session_id TEXT PRIMARY KEY, ctx_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', result TEXT);
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

    def _one(self, sql: str, *args) -> dict | None:
        with self.lock:
            row = self.db.execute(sql, args).fetchone()
        return None if row is None else dict(row)

    # -- spends
    def put_spend(self, ctx_hash: str, chain_id: int, safe: str, safe_tx: dict, what: dict) -> None:
        with self.lock:
            self.db.execute("INSERT OR IGNORE INTO spends(ctx_hash, chain_id, safe, safe_tx, what) VALUES (?, ?, ?, ?, ?)",
                            (ctx_hash, chain_id, safe, json.dumps(safe_tx, sort_keys=True), json.dumps(what)))

    def get_spend(self, ctx_hash: str) -> dict | None:
        row = self._one("SELECT * FROM spends WHERE ctx_hash = ?", ctx_hash)
        if row is not None:
            row["safe_tx"], row["what"] = json.loads(row["safe_tx"]), json.loads(row["what"])
        return row

    # -- owner signatures. The first valid one stays: any valid one does the same on chain.
    def put_owner_sig(self, ctx_hash: str, pubkey: str, sig: str) -> None:
        with self.lock:
            self.db.execute("INSERT OR IGNORE INTO owner_sigs(ctx_hash, pubkey, sig) VALUES (?, ?, ?)",
                            (ctx_hash, pubkey, sig))

    def owner_sig(self, ctx_hash: str, pubkey: str) -> str | None:
        row = self._one("SELECT sig FROM owner_sigs WHERE ctx_hash = ? AND pubkey = ?", ctx_hash, pubkey)
        return None if row is None else row["sig"]

    # -- attestations and relay jobs
    def get_attestation(self, session_id: str) -> dict | None:
        row = self._one("SELECT * FROM attestations WHERE session_id = ?", session_id)
        if row is not None:
            row["att"], row["body"] = json.loads(row["att"]), json.loads(row["body"])
        return row

    def attest_once(self, record: dict, ctx_hash: str, make_att) -> dict:
        """make_att() signs, so it runs only for a session not signed yet. The attestation and its job land together."""
        sid = record["body"]["session_id"]
        with self.lock:
            if (have := self.get_attestation(sid)) is not None:
                return have["att"]
            att = make_att()
            self.db.execute("BEGIN")
            try:
                self.db.execute("INSERT INTO attestations(session_id, ctx_hash, att, body, sig_b64) VALUES (?, ?, ?, ?, ?)",
                                (sid, ctx_hash, json.dumps(att), canonical(record["body"]).decode(), record["sig_b64"]))
                self.db.execute("INSERT INTO relay_jobs(session_id, ctx_hash) VALUES (?, ?)", (sid, ctx_hash))
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
            self.db.execute("COMMIT")
            return att

    def job(self, session_id: str) -> dict | None:
        return self._one("SELECT * FROM relay_jobs WHERE session_id = ?", session_id)

    def latest_job(self, ctx_hash: str) -> dict | None:
        return self._one("SELECT * FROM relay_jobs WHERE ctx_hash = ? ORDER BY rowid DESC LIMIT 1", ctx_hash)

    def pending_jobs(self) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM relay_jobs WHERE status = 'pending' ORDER BY rowid")]

    def set_job(self, session_id: str, status: str, result: str) -> None:
        with self.lock:
            self.db.execute("UPDATE relay_jobs SET status = ?, result = ? WHERE session_id = ?",
                            (status, result, session_id))

    def requeue_job(self, session_id: str) -> None:
        """A redelivery is the retry for a job that didn't succeed. relay.mjs never sends twice."""
        with self.lock:
            self.db.execute("UPDATE relay_jobs SET status = 'pending', result = NULL WHERE session_id = ? AND status != 'success'",
                            (session_id,))
