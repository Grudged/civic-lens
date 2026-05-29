"""Extract the 'where' from a raw Legistar agenda title — cross-streets / area, acreage, and zone.

Land-use items follow a stable pattern ("...on 9.46 acres in a CR (Commercial Resort) Zone.
Generally located east of Las Vegas Boulevard South and south of Harmon Avenue within Paradise."),
so a deterministic regex pull is reliable. Gemma's plain summary drops these details; this puts the
location back in the quick view so residents can tell if something is near them. Returns Nones for
items with no location (proclamations, budget, etc.) so the line simply doesn't render.
"""
from __future__ import annotations

import re

_LOC = re.compile(r"\blocated\s+(.+?)(?:\.(?:\s|$)|$)", re.I | re.S)
_ACRES = re.compile(r"(\d+(?:\.\d+)?)\s*acres?\b", re.I)
_ZONE = re.compile(r"\bin\s+an?\s+(.+?)\s+Zone\b", re.I)
# The dominant "[dir] of STREET1 and [dir] of STREET2 within AREA" intersection pattern → a clean
# map query. Other phrasings just don't get a map link (the text location still shows).
_STREETS = re.compile(
    r"(?:north|south|east|west)\s+of\s+(.+?)\s+and\s+(?:north|south|east|west)\s+of\s+(.+?)"
    r"(?:\s+within\s+(.+?))?$", re.I)
# The trailing "within AREA" (township / town) — present even when the streets don't follow the
# intersection pattern, so it powers a neighborhood-level pin when an exact corner isn't available.
_WITHIN = re.compile(r"\bwithin\s+(?:the\s+)?(.+?)(?:\s+Township)?\s*$", re.I)


def _clean_area(area: str | None) -> str | None:
    a = re.sub(r"\([^)]*\)", " ", area or "")          # drop "(description on file)" etc.
    a = re.sub(r"\s+", " ", a).strip().rstrip(".").strip()
    a = re.sub(r"^the\s+", "", a, flags=re.I)
    a = re.sub(r"\s+Township$", "", a, flags=re.I)
    a = re.sub(r"\s+planning area$", "", a, flags=re.I)
    return a or None


def _clean_street(s: str | None) -> str | None:
    s = re.sub(r"\([^)]*\)", " ", s or "")             # drop "(alignment)" — breaks the locator
    s = re.sub(r"\s+", " ", s).strip().rstrip(",").strip()
    return s or None

_ABBR = [("Boulevard", "Blvd"), ("Avenue", "Ave"), ("Street", "St"), ("Road", "Rd"),
         ("Drive", "Dr"), ("Parkway", "Pkwy"), ("Highway", "Hwy"), ("Lane", "Ln")]


def extract(title: str) -> dict:
    t = title or ""
    out: dict = {"location": None, "acres": None, "zone": None, "map_query": None,
                 "street1": None, "street2": None, "area": None}

    m = _LOC.search(t)
    if m:
        raw = re.sub(r"\s+", " ", m.group(1)).strip().rstrip(".")
        sm = _STREETS.search(raw)
        if sm:
            s1, s2 = _clean_street(sm.group(1)), _clean_street(sm.group(2))
            area = _clean_area(sm.group(3))
            out["street1"], out["street2"] = s1, s2
            out["area"] = area
            if s1 and s2:
                out["map_query"] = f"{s1} & {s2}, {area or 'Las Vegas'}, NV"
        if out["area"] is None:
            wm = _WITHIN.search(raw)
            if wm:
                out["area"] = _clean_area(wm.group(1))
        loc = raw
        for word, abbr in _ABBR:
            loc = re.sub(rf"\b{word}\b", abbr, loc)
        if loc:
            out["location"] = loc[0].upper() + loc[1:]

    a = _ACRES.search(t)
    if a:
        out["acres"] = a.group(1)

    z = _ZONE.search(t)
    if z:
        zone = re.sub(r"\s+", " ", z.group(1)).strip()
        if 0 < len(zone) < 60:  # guard against a runaway capture
            out["zone"] = zone

    return out
