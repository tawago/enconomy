"""ENS name claims: one <label>.enconomy.eth per device, set once, never renamed.

The server only records the claim (ens_names in its sqlite, created here; store.py is unchanged). The bridge
(bridge/bridge.py) registers pending rows onchain with the admin key and writes status / tx back. ens_names is the
only device -> label map (the bridge reads registered rows; `bridge.py import-names` seeds hand-mapped devices).
"""
from __future__ import annotations

import re
import sqlite3

from pop.errors import PopError

PARENT = "enconomy.eth"
LABEL_RE = re.compile(r"^[a-z0-9-]{3,32}$")   # same rule as contracts/script/ens.sh and the bridge

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ens_names (
  device_id TEXT PRIMARY KEY, label TEXT NOT NULL UNIQUE, claimed_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', tx TEXT, error TEXT);
"""


def view(row: dict | None) -> dict:
    if row is None:
        return {"label": None, "name": None, "status": "none", "tx": None}
    return {"label": row["label"], "name": f"{row['label']}.{PARENT}", "status": row["status"], "tx": row["tx"]}


class Names:
    def __init__(self, store):
        self.db, self.lock = store._db, store._lock
        with self.lock:
            self.db.executescript(_SCHEMA)

    def get(self, device_id: str) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM ens_names WHERE device_id = ?", (device_id,)).fetchone()
        return None if row is None else dict(row)

    def claim(self, dev: dict, label, now_iso: str) -> dict:
        if dev.get("platform") == "web":
            raise PopError(403, "not_allowed", "ENS names are for phones")
        if not isinstance(label, str) or not LABEL_RE.fullmatch(label):
            raise PopError(400, "bad_label", "3-32 chars of a-z, 0-9, -")
        if (have := self.get(dev["device_id"])) is not None and have["status"] != "failed":
            raise PopError(409, "already_claimed", f"this phone is {have['label']}.{PARENT}")
        with self.lock:
            try:
                if have is not None:  # the bridge could not register it: never onchain, so a retry is not a rename
                    self.db.execute("DELETE FROM ens_names WHERE device_id = ?", (dev["device_id"],))
                self.db.execute("INSERT INTO ens_names(device_id, label, claimed_at) VALUES (?, ?, ?)",
                                (dev["device_id"], label, now_iso))
            except sqlite3.IntegrityError:
                raise PopError(409, "label_taken", f"{label}.{PARENT} is taken") from None
        return self.get(dev["device_id"])
