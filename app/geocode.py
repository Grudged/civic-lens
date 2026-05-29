"""Turn an extracted agenda location (cross-streets + township) into a lat/lng.

Two free, no-key layers, best to worst precision:
  1. **Clark County composite geocoder** (authoritative county ArcGIS locator) for the exact street
     intersection — it resolves "Decatur Boulevard & Tropicana Avenue" to a corner. Feed it the bare
     "STREET1 & STREET2" only; a trailing city/state makes the intersection matcher miss.
  2. **Township centroid** fallback — a neighborhood-level pin for the "within AREA" part when an exact
     corner isn't available (non-intersection phrasings, or a corner the locator can't place).

Everything is cached in the `geocodes` table keyed on a normalized location key, so a given corner is
geocoded once and reused across every item that references it. This module is pure lookups (no DB);
geocode_job.py owns the cache + walks the agenda.
"""
from __future__ import annotations

import os

import httpx

# Clark County's public composite locator. No key. Override via env for a self-hosted/alt locator.
GEOCODER_URL = os.getenv(
    "GEOCODER_URL",
    "https://maps.clarkcountynv.gov/arcgis/rest/services/Locators/Clark_County_Composite/GeocodeServer/findAddressCandidates",
)
MIN_SCORE = float(os.getenv("GEOCODER_MIN_SCORE", "80"))

# Clark County township / municipality centroids (lat, lng) for the neighborhood-level fallback.
# Keys are lowercased; normalize_area() strips "the "/" Township" before lookup.
CENTROIDS: dict[str, tuple[float, float]] = {
    "las vegas": (36.1716, -115.1391),
    "north las vegas": (36.1989, -115.1175),
    "henderson": (36.0395, -114.9817),
    "boulder city": (35.9786, -114.8319),
    "mesquite": (36.8055, -114.0672),
    "paradise": (36.0972, -115.1467),
    "spring valley": (36.1080, -115.2450),
    "enterprise": (36.0136, -115.2400),
    "sunrise manor": (36.2110, -115.0730),
    "winchester": (36.1397, -115.0911),
    "whitney": (36.0980, -115.0370),
    "summerlin south": (36.1100, -115.3340),
    "summerlin": (36.1780, -115.3290),
    "lone mountain": (36.2540, -115.2790),
    "mountain springs": (36.0119, -115.5030),
    "laughlin": (35.1678, -114.5730),
    "indian springs": (36.5686, -115.6700),
    "searchlight": (35.4647, -114.9183),
    "moapa valley": (36.5430, -114.4480),
    "moapa": (36.6800, -114.6000),
    "logandale": (36.5980, -114.4790),
    "overton": (36.5430, -114.4480),
    "bunkerville": (36.7700, -114.1300),
    "mount charleston": (36.2716, -115.6457),
    "blue diamond": (36.0455, -115.4070),
    "goodsprings": (35.8336, -115.4380),
    "sandy valley": (35.8158, -115.6360),
    "cal-nev-ari": (35.2900, -114.9100),
    "jean": (35.7780, -115.3230),
    "primm": (35.6100, -115.3890),
    "red rock": (36.1300, -115.4200),
    "sloan": (35.9400, -115.2100),
    "mountains edge": (36.0090, -115.3290),
    # Broad unincorporated planning regions — a rough valley-quadrant pin, clearly flagged 'area'.
    "northwest county": (36.3000, -115.3000),
    "south county": (35.9000, -115.2500),
    "northeast county": (36.3200, -115.0500),
}


def normalize_area(area: str | None) -> str | None:
    if not area:
        return None
    a = area.strip().lower()
    a = a.removeprefix("the ").removesuffix(" township").strip()
    a = a.removeprefix("town of ").removeprefix("city of ").strip()
    return a or None


def cache_key(ex: dict) -> str | None:
    """A stable key shared by every item at the same location. Exact corner if we have streets,
    otherwise the township. None for items with no usable location (they get no pin)."""
    s1, s2 = ex.get("street1"), ex.get("street2")
    if s1 and s2:
        return f"{s1} & {s2}".lower()
    area = normalize_area(ex.get("area"))
    if area:
        return f"area::{area}"
    return None


def label_for(ex: dict) -> str:
    return ex.get("location") or ex.get("area") or "Clark County"


def _intersection_query(s1: str, s2: str) -> str:
    return f"{s1} & {s2}"


def geocode_intersection(s1: str, s2: str, client: httpx.Client) -> tuple[float, float, float] | None:
    """Resolve a street intersection via the Clark County locator. Returns (lat, lng, score) or None."""
    try:
        r = client.get(GEOCODER_URL, params={
            "SingleLine": _intersection_query(s1, s2),
            "outFields": "Addr_type,Score",
            "outSR": "4326",
            "maxLocations": "1",
            "f": "json",
        })
        r.raise_for_status()
        cands = r.json().get("candidates") or []
    except (httpx.HTTPError, ValueError):
        return None
    if not cands:
        return None
    c = cands[0]
    score = float(c.get("score") or 0)
    if score < MIN_SCORE:
        return None
    loc = c.get("location") or {}
    if "x" not in loc or "y" not in loc:
        return None
    return (round(float(loc["y"]), 6), round(float(loc["x"]), 6), score)


def area_centroid(area: str | None) -> tuple[float, float] | None:
    a = normalize_area(area)
    return CENTROIDS.get(a) if a else None


def resolve(ex: dict, client: httpx.Client) -> dict | None:
    """Best available fix for an extracted location: exact corner, else township centroid, else 'none'.
    Returns a dict ready for the geocodes table, or None if there's nothing to geocode."""
    if cache_key(ex) is None:
        return None
    base = {"label": label_for(ex), "lat": None, "lng": None,
            "precision": "none", "source": None, "score": None}

    s1, s2 = ex.get("street1"), ex.get("street2")
    if s1 and s2:
        hit = geocode_intersection(s1, s2, client)
        if hit:
            lat, lng, score = hit
            base.update(lat=lat, lng=lng, precision="point", source="clarkcounty", score=score)
            return base

    centroid = area_centroid(ex.get("area"))
    if centroid:
        base.update(lat=centroid[0], lng=centroid[1], precision="area", source="centroid")
    return base
