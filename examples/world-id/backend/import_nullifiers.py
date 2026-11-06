"""Copy wid_nullifiers rows from an old core pop.sqlite into this example's database. The source opens read-only.

  uv run python -m backend.import_nullifiers <old pop.sqlite> [world-id.sqlite]

INSERT OR IGNORE, so a second run changes nothing and rows already here stay. Old rows have the action pop:<old sid>,
so they can't collide with a new session: this is record-keeping.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote

from backend.store import Store

COLUMNS = "rp_id, action, nullifier, env, kind, subject, created_at"


def import_nullifiers(src: str | Path, dst: str | Path) -> dict:
    src, dst = Path(src).resolve(), Path(dst).resolve()
    if src == dst:
        raise ValueError("source and target are the same file")
    old = sqlite3.connect(f"file:{quote(str(src))}?mode=ro", uri=True)
    try:
        rows = old.execute(f"SELECT {COLUMNS} FROM wid_nullifiers").fetchall()
    finally:
        old.close()
    store = Store(dst)
    added = 0
    try:
        for row in rows:
            added += store.db.execute(f"INSERT OR IGNORE INTO wid_nullifiers({COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                      row).rowcount
    finally:
        store.close()
    return {"read": len(rows), "added": added, "kept": len(rows) - added}


def main(argv: list[str]) -> int:
    if len(argv) not in (1, 2):
        print(__doc__)
        return 2
    dst = argv[1] if len(argv) == 2 else os.environ.get("WID_DB", "data/world-id.sqlite")
    try:
        c = import_nullifiers(argv[0], dst)
    except (sqlite3.Error, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"read {c['read']}, added {c['added']}, already there {c['kept']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
