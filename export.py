#!/usr/bin/env python3
"""Export civic.db → data/civic.json — the text artifact pushed to git.

Hetzner rebuilds its SQLite from this JSON (tools/load_json.py), so the public site never needs
the binary DB. Stable output (sorted keys) keeps git diffs clean. Run after summarize_job.py.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from app.db import db

OUT = Path(__file__).resolve().parent / "data" / "civic.json"
TABLES = ["meetings", "agenda_items", "item_votes", "meeting_summaries"]


def export() -> None:
    payload = {"exported_at": datetime.now(timezone.utc).isoformat(), "tables": {}}
    with db() as conn:
        for t in TABLES:
            payload["tables"][t] = [dict(r) for r in conn.execute(f"SELECT * FROM {t}").fetchall()]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1, sort_keys=True, default=str) + "\n")
    n = sum(len(v) for v in payload["tables"].values())
    print(f"exported {n} rows across {len(TABLES)} tables -> {OUT}")


if __name__ == "__main__":
    export()
