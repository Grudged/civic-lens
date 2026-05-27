"""Legistar Web API client (Granicus). Clark County's public records API — no key required.

Docs: https://webapi.legistar.com/  ·  OData v1 ($filter / $orderby / $top).
Surface we use:
  /bodies                         governing bodies
  /events?$filter=...             meetings (date, agenda/minutes files, location)
  /events/{id}/eventitems         agenda items (substantive ones have a non-null MatterId)
  /eventitems/{id}/votes          roll-call votes for a decided item
"""
from __future__ import annotations

import httpx

from .config import LEGISTAR_BASE

UA = "CivicLens/0.1 (+https://grudged.io; public-good civic transparency)"
TIMEOUT = 30.0


def _get(path: str, params: dict | None = None):
    with httpx.Client(timeout=TIMEOUT, headers={"User-Agent": UA, "Accept": "application/json"}) as c:
        r = c.get(f"{LEGISTAR_BASE}{path}", params=params or {})
        r.raise_for_status()
        return r.json()


def _dt_literal(iso_date: str) -> str:
    """OData v1 datetime literal, e.g. datetime'2026-05-01'."""
    return f"datetime'{iso_date}'"


def list_events(body_id: int, since: str, until: str) -> list[dict]:
    """Meetings for one body in [since, until] (ISO dates), oldest first."""
    flt = (f"EventBodyId eq {int(body_id)} and EventDate ge {_dt_literal(since)} "
           f"and EventDate le {_dt_literal(until)}")
    return _get("/events", {"$filter": flt, "$orderby": "EventDate"})


def get_event_items(event_id: int) -> list[dict]:
    """All agenda items for a meeting, in agenda order. Procedural rows (MatterId null) are
    filtered by the collector; substantive matters carry titles + action outcomes."""
    return _get(f"/events/{int(event_id)}/eventitems", {"$orderby": "EventItemAgendaSequence"})


def get_item_votes(event_item_id: int) -> list[dict]:
    """Roll-call votes for a decided agenda item. Best-effort: [] on any error (not every item
    has a recorded roll call — proclamations, withdrawn items, etc.)."""
    try:
        return _get(f"/eventitems/{int(event_item_id)}/votes")
    except httpx.HTTPError:
        return []
