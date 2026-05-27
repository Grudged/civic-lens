"""Gemma enrichment pass — meeting overviews + per-item plain-English rewrites.

Runs after collect.py. Best-effort and safe to re-run (skips already-summarized meetings unless
--force). On Arch, set MLX_URL to the Mac's LAN IP (the model lives on the Mac).

Run:  python summarize_job.py [--limit N] [--force]
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from app import summarize
from app.config import MLX_MODEL
from app.db import db, init_db
from app.util import fmt_date

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("civic.summarize_job")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(limit: int | None = None, force: bool = False) -> None:
    init_db()
    where = "" if force else "WHERE s.event_id IS NULL"
    with db() as conn:
        rows = conn.execute(
            f"SELECT m.event_id, m.body_name, m.meeting_date, m.status FROM meetings m "
            f"LEFT JOIN meeting_summaries s ON s.event_id = m.event_id {where} "
            f"ORDER BY m.meeting_date DESC").fetchall()
    rows = rows[:limit] if limit else rows
    log.info("summarizing %d meetings", len(rows))
    for r in rows:
        _do_meeting(r["event_id"], r["body_name"], r["meeting_date"], r["status"] == "past")


def _do_meeting(event_id: int, body_name: str, mdate: str, past: bool) -> None:
    with db() as conn:
        items = conn.execute(
            "SELECT event_item_id, title FROM agenda_items WHERE event_id=? ORDER BY sequence",
            (event_id,)).fetchall()
    titles = [it["title"] for it in items]
    if not titles:
        log.info("event %s: no items, skipping", event_id)
        return

    ov = summarize.overview(body_name, fmt_date(mdate), titles, past)
    rewrites = summarize.rewrite_items(titles)

    with db() as conn:
        for it, rw in zip(items, rewrites):
            conn.execute("UPDATE agenda_items SET plain_summary=? WHERE event_item_id=?",
                         (rw, it["event_item_id"]))
        agg: list[str] = []
        for tr in conn.execute("SELECT topics FROM agenda_items WHERE event_id=?", (event_id,)).fetchall():
            for t in json.loads(tr["topics"] or "[]"):
                if t not in agg:
                    agg.append(t)
        conn.execute(
            "INSERT OR REPLACE INTO meeting_summaries (event_id, overview, topics, model, generated_at) "
            "VALUES (?,?,?,?,?)", (event_id, ov, json.dumps(agg), MLX_MODEL, _now()))
    log.info("event %s: %d items rewritten, overview=%s", event_id, len(items), bool(ov))


if __name__ == "__main__":
    args = sys.argv[1:]
    force = "--force" in args
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    run(limit=limit, force=force)
