"""Civic Lens collector — pull Clark County meetings from Legistar into civic.db.

Deterministic only (no Gemma): meetings, substantive agenda items, topic tags, and roll-call
votes for decided items. Idempotent (INSERT OR REPLACE keyed on Legistar ids), so it's safe to
run nightly. Gemma enrichment is a separate pass (summarize_job.py).

Run:  python collect.py            (default window: 120 days back, 60 days ahead)
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone

import httpx

from app import legistar, topics
from app.config import BODIES, LEGISTAR_INSITE
from app.db import db, init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("civic.collect")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(s) -> str | None:
    s = (s or "").strip()
    return s or None


def _merge_datetime(event_date: str, event_time) -> str:
    """Legistar gives EventDate (midnight ISO) + EventTime ("9:00 AM"). Merge to ISO 'YYYY-MM-DDTHH:MM'."""
    d = (event_date or "")[:10]
    t = _clean(event_time)
    if t:
        for fmt in ("%I:%M %p", "%I %p", "%H:%M"):
            try:
                return f"{d}T{datetime.strptime(t, fmt).strftime('%H:%M')}"
            except ValueError:
                continue
    return d


def _insite_url(ev: dict) -> str | None:
    # Legistar exposes a public meeting page; field name varies, so try the known ones.
    for k in ("EventInSiteURL", "EventInSiteUrl", "EventComment"):
        u = _clean(ev.get(k))
        if u and u.lower().startswith("http"):
            return u
    return f"{LEGISTAR_INSITE}/MeetingDetail.aspx?ID={ev.get('EventId')}"


def collect(since_days: int = 120, until_days: int = 60, fetch_votes: bool = True) -> dict:
    init_db()
    today = date.today()
    since = (today - timedelta(days=since_days)).isoformat()
    until = (today + timedelta(days=until_days)).isoformat()
    stats = {"meetings": 0, "items": 0, "votes": 0}

    for body_id, meta in BODIES.items():
        try:
            events = legistar.list_events(body_id, since, until)
        except httpx.HTTPError as e:
            log.warning("body %s events failed: %s", body_id, e)
            continue
        log.info("body %s (%s): %d events", body_id, meta["name"], len(events))

        for ev in events:
            event_id = ev.get("EventId")
            if event_id is None:
                continue
            mdate = _merge_datetime(ev.get("EventDate", ""), ev.get("EventTime"))
            is_past = mdate[:10] < today.isoformat()
            with db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO meetings (event_id, body_id, body_name, body_slug, "
                    "meeting_date, status, location, agenda_url, minutes_url, legistar_url, fetched_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (event_id, body_id, meta["name"], meta["slug"], mdate,
                     "past" if is_past else "upcoming", _clean(ev.get("EventLocation")),
                     _clean(ev.get("EventAgendaFile")), _clean(ev.get("EventMinutesFile")),
                     _insite_url(ev), _now()),
                )
            stats["meetings"] += 1
            stats["items"] += _collect_items(event_id, is_past and fetch_votes, stats)
    log.info("done: %s", stats)
    return stats


def _collect_items(event_id: int, fetch_votes: bool, stats: dict) -> int:
    try:
        items = legistar.get_event_items(event_id)
    except httpx.HTTPError as e:
        log.warning("event %s items failed: %s", event_id, e)
        return 0
    # Replace this meeting's items wholesale so re-runs reflect agenda/outcome updates.
    with db() as conn:
        ids = [r["event_item_id"] for r in conn.execute(
            "SELECT event_item_id FROM agenda_items WHERE event_id=?", (event_id,)).fetchall()]
        if ids:
            conn.execute(f"DELETE FROM item_votes WHERE event_item_id IN ({','.join('?'*len(ids))})", ids)
        conn.execute("DELETE FROM agenda_items WHERE event_id=?", (event_id,))

    count = 0
    for it in items:
        if it.get("EventItemMatterId") is None:   # skip procedural rows (headers, "PAGE BREAK", …)
            continue
        title = _clean(it.get("EventItemTitle"))
        if not title:
            continue
        item_id = it.get("EventItemId")
        with db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO agenda_items (event_item_id, event_id, matter_id, sequence, "
                "title, action_name, passed_flag, mover, seconder, matter_type, topics) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (item_id, event_id, it.get("EventItemMatterId"), it.get("EventItemAgendaSequence"),
                 title, _clean(it.get("EventItemActionName")), it.get("EventItemPassedFlag"),
                 _clean(it.get("EventItemMover")), _clean(it.get("EventItemSeconder")),
                 _clean(it.get("EventItemMatterType")), json.dumps(topics.tag(title))),
            )
        count += 1
        if fetch_votes and it.get("EventItemActionName"):
            stats["votes"] += _collect_votes(item_id)
    return count


def _collect_votes(item_id: int) -> int:
    votes = legistar.get_item_votes(item_id)
    n = 0
    for v in votes:
        person = _clean(v.get("VotePersonName"))
        if not person:
            continue
        with db() as conn:
            conn.execute("INSERT OR REPLACE INTO item_votes (event_item_id, person, vote) VALUES (?,?,?)",
                         (item_id, person, _clean(v.get("VoteValueName"))))
        n += 1
    return n


if __name__ == "__main__":
    sd = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    ud = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    collect(since_days=sd, until_days=ud)
