"""Copy ens_names rows from an old core pop.sqlite into this example's database. The source opens read-only.

  uv run python -m backend.import_names <old pop.sqlite> [ens.sqlite]

Status, tx, error and claimed_at are kept. INSERT OR IGNORE, so a second run changes nothing and rows already here
stay. Imported pending rows go onchain the next time the backend starts.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote

from backend.store import Store

COLUMNS = "device_id, label, claimed_at, status, tx, error"


def import_names(src: str | Path, dst: str | Path) -> dict:
    src, dst = Path(src).resolve(), Path(dst).resolve()
    if src == dst:
        raise ValueError("source and target are the same file")
    old = sqlite3.connect(f"file:{quote(str(src))}?mode=ro", uri=True)
    try:
        rows = old.execute(f"SELECT {COLUMNS} FROM ens_names").fetchall()
    finally:
        old.close()
    store = Store(dst)
    added = pending = 0
    try:
        for row in rows:
            n = store.db.execute(f"INSERT OR IGNORE INTO ens_names({COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)", row).rowcount
            added += n
            pending += n if row[3] == "pending" else 0
    finally:
        store.close()
    return {"read": len(rows), "added": added, "kept": len(rows) - added, "pending_added": pending}


def main(argv: list[str]) -> int:
    if len(argv) not in (1, 2):
        print(__doc__)
        return 2
    dst = argv[1] if len(argv) == 2 else os.environ.get("ENS_DB", "data/ens.sqlite")
    try:
        c = import_names(argv[0], dst)
    except (sqlite3.Error, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"read {c['read']}, added {c['added']}, already there {c['kept']}")
    if c["pending_added"]:
        print(f"warning: {c['pending_added']} imported rows are pending: they will be sent onchain, with gas, "
              "when the backend starts", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
