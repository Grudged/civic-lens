#!/usr/bin/env python3
"""Civic Lens collector — daily snapshot of Clark County meeting summaries from the local Civic
Lens API into warehouse.db `civic_meetings` (one row per meeting, UPSERT/idempotent).

Public civic data + AI summaries, no PII. Feeds Mission Control visibility and the knowledge
compiler (Gemma learns local-government context from the plain-English overviews).

Deployed to ~/data-collectors/ on Arch (edited in place there; this repo copy is the reference).
"""
import json
import logging

import httpx
from db import ensure_table, get_conn

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger("civic")

STATS_URL = "http://127.0.0.1:8902/api/stats"

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS civic_meetings (
    event_id     INTEGER PRIMARY KEY,
    body_name    TEXT,
    body_slug    TEXT,
    meeting_date TEXT,
    status       TEXT,
    item_count   INTEGER,
    overview     TEXT,
    topics_json  TEXT,
    collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


def collect():
    try:
        r = httpx.get(STATS_URL, timeout=15)
        r.raise_for_status()
        s = r.json()
    except Exception as e:
        log.warning("civic stats fetch failed: %s — skipping", e)
        return

    conn = get_conn()
    try:
        ensure_table(conn, CREATE_TABLE)
        for m in s.get("recent", []):
            conn.execute(
                """
                INSERT INTO civic_meetings
                    (event_id, body_name, body_slug, meeting_date, status, item_count,
                     overview, topics_json, collected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(event_id) DO UPDATE SET
                    status=excluded.status,
                    item_count=excluded.item_count,
                    overview=COALESCE(excluded.overview, civic_meetings.overview),
                    topics_json=excluded.topics_json,
                    collected_at=excluded.collected_at
                """,
                (m["event_id"], m.get("body_name"), m.get("body_slug"), m.get("meeting_date"),
                 m.get("status"), m.get("item_count"), m.get("overview"),
                 json.dumps(m.get("topics", []))),
            )
        conn.commit()
    finally:
        conn.close()
    log.info("civic: %s meetings (%s summarized)", s.get("total_meetings"), s.get("summarized"))


if __name__ == "__main__":
    collect()
