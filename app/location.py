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

_ABBR = [("Boulevard", "Blvd"), ("Avenue", "Ave"), ("Street", "St"), ("Road", "Rd"),
         ("Drive", "Dr"), ("Parkway", "Pkwy"), ("Highway", "Hwy"), ("Lane", "Ln")]


def extract(title: str) -> dict:
    t = title or ""
    out: dict = {"location": None, "acres": None, "zone": None}

    m = _LOC.search(t)
    if m:
        loc = re.sub(r"\s+", " ", m.group(1)).strip().rstrip(".")
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
