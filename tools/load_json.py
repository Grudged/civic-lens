#!/usr/bin/env python3
"""Rebuild the SQLite DB from data/civic.json — Hetzner runs this on container start and after
each `git pull`. Builds into a temp file then atomically renames over DB_PATH, so an in-flight
request never sees a half-written DB. Run from the repo root: `python tools/load_json.py`.
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # make `app` importable

from app.config import DB_PATH  # noqa: E402
from app.db import SCHEMA  # noqa: E402

JSON_PATH = Path(os.getenv("CIVIC_JSON", Path(__file__).resolve().parent.parent / "data" / "civic.json"))


def load() -> None:
    data = json.loads(JSON_PATH.read_text())
    tables = data["tables"]

    tmp = f"{DB_PATH}.tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(tmp)
    conn.executescript(SCHEMA)
    total = 0
    for table, rows in tables.items():
        if not rows:
            continue
        cols = list(rows[0].keys())
        placeholders = ",".join("?" * len(cols))
        conn.executemany(
            f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({placeholders})",
            [tuple(r.get(c) for c in cols) for r in rows],
        )
        total += len(rows)
    conn.commit()
    conn.close()
    os.replace(tmp, DB_PATH)  # atomic
    print(f"rebuilt {DB_PATH} from {JSON_PATH} ({total} rows)")


if __name__ == "__main__":
    load()
