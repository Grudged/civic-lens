"""Geocoding pass — resolve agenda-item locations to lat/lng for the map.

Runs after collect.py. Walks agenda items, extracts the "where" from each title, and fills the
`geocodes` cache: an exact corner from the Clark County locator when possible, else a township
centroid. A location is geocoded once and shared across every item that references it, so re-runs
only touch new corners. Best-effort: a locator outage just leaves a key uncached for next time.

Run:  python geocode_job.py [--refresh]   (--refresh re-geocodes everything, e.g. after a locator fix)
"""
from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone

import httpx

from app import geocode, location
from app.db import db, init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("civic.geocode_job")

_UA = "CivicLens/0.1 (+https://civic.grudged.io)"
_NET_PAUSE = 0.25  # polite gap between locator calls


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(refresh: bool = False) -> dict:
    init_db()
    with db() as conn:
        cached = set() if refresh else {
            r["geo_key"] for r in conn.execute("SELECT geo_key FROM geocodes").fetchall()}
        titles = [r["title"] for r in conn.execute(
            "SELECT title FROM agenda_items WHERE title IS NOT NULL").fetchall()]

    # One extracted location per new key (first occurrence wins; they describe the same place).
    todo: dict[str, dict] = {}
    for title in titles:
        ex = location.extract(title)
        key = geocode.cache_key(ex)
        if key and key not in cached and key not in todo:
            todo[key] = ex

    log.info("%d agenda items · %d new locations to geocode (refresh=%s)", len(titles), len(todo), refresh)
    stats = {"point": 0, "area": 0, "none": 0}

    with httpx.Client(timeout=20, headers={"User-Agent": _UA}) as client:
        for i, (key, ex) in enumerate(todo.items(), 1):
            needs_net = bool(ex.get("street1") and ex.get("street2"))
            res = geocode.resolve(ex, client)
            if res is None:
                continue
            stats[res["precision"]] = stats.get(res["precision"], 0) + 1
            with db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO geocodes "
                    "(geo_key, label, lat, lng, precision, source, score, geocoded_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (key, res["label"], res["lat"], res["lng"], res["precision"],
                     res["source"], res["score"], _now()))
            if i % 25 == 0:
                log.info("  %d/%d …", i, len(todo))
            if needs_net:
                time.sleep(_NET_PAUSE)

    log.info("done: %s", stats)
    return stats


if __name__ == "__main__":
    run(refresh="--refresh" in sys.argv[1:])
