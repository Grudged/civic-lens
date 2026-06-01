"""Point-in-polygon district lookup + representative join.

Loads `data/districts/*.geojson` once at process boot, builds a Shapely STRtree per
layer, and offers a `lookup(lat, lng)` that returns the matching district per layer
in O(log n).

Reps live in two files merged at boot:
  - `data/representatives_nv.json` — scraped state legislators (see scrape_legislators.py)
  - `data/representatives_seed.yaml` — hand-curated federal, regents, county, city, CCSD

Lookups also pull the rep's recent votes from civic-lens `item_votes` when the rep's
`short_name` matches the `person` column on votes the agenda harvester has collected.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from shapely.geometry import Point, mapping, shape
from shapely.strtree import STRtree

from .db import db

log = logging.getLogger("districts")

ROOT = Path(__file__).resolve().parent.parent
DISTRICTS_DIR = ROOT / "data" / "districts"
MANIFEST_PATH = DISTRICTS_DIR / "manifest.json"
REPS_NV_PATH = ROOT / "data" / "representatives_nv.json"
REPS_SEED_PATH = ROOT / "data" / "representatives_seed.yaml"


@dataclass
class LayerIndex:
    layer_id: str
    label: str
    sort_order: int
    geometries: list = field(default_factory=list)      # shapely polygons
    district_ids: list[str] = field(default_factory=list)  # parallel array
    tree: STRtree | None = None
    # geojson-style geometry dicts, parallel to `geometries`. Cached at load
    # time so /api/districts can return the matched polygon inline for the
    # client's map overlay without a second round-trip.
    geom_json: list[dict] = field(default_factory=list)


_layers: dict[str, LayerIndex] = {}
_reps_by_key: dict[tuple[str, str], dict] = {}     # (layer_id, district_id) -> rep dict
_loaded = False


def load() -> None:
    """Idempotent boot: load manifest + GeoJSON + reps. Safe to call multiple times."""
    global _loaded
    if _loaded:
        return
    _load_layers()
    _load_reps()
    _loaded = True
    log.info(
        "districts ready: %d layers, %d reps",
        len(_layers),
        len(_reps_by_key),
    )


def _load_layers() -> None:
    if not MANIFEST_PATH.exists():
        log.warning("districts manifest missing at %s — calculator disabled", MANIFEST_PATH)
        return

    manifest = json.loads(MANIFEST_PATH.read_text())
    for entry in manifest.get("layers", []):
        layer_id = entry["layer_id"]
        path = ROOT / entry["geojson_path"]
        if not path.exists():
            log.warning("layer %s missing at %s — skipping", layer_id, path)
            continue
        fc = json.loads(path.read_text())
        idx = LayerIndex(
            layer_id=layer_id,
            label=entry["label"],
            sort_order=entry.get("sort_order", 100),
        )
        for f in fc.get("features", []):
            geom = f.get("geometry")
            props = f.get("properties") or {}
            district_id = props.get("district_id")
            if not geom or not district_id:
                continue
            try:
                g = shape(geom)
            except Exception as e:
                log.warning("layer %s: bad geometry — %s", layer_id, e)
                continue
            if g.is_empty:
                continue
            idx.geometries.append(g)
            idx.district_ids.append(str(district_id))
            idx.geom_json.append(geom)
        idx.tree = STRtree(idx.geometries) if idx.geometries else None
        _layers[layer_id] = idx
        log.info("loaded layer %s: %d polygons", layer_id, len(idx.geometries))


def _normalize_district(val) -> str:
    if val is None:
        return ""
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    return str(val).strip()


def _load_reps() -> None:
    # State legislators from the scraper
    if REPS_NV_PATH.exists():
        payload = json.loads(REPS_NV_PATH.read_text())
        for r in payload.get("reps", []):
            key = (r["layer_id"], _normalize_district(r["district"]))
            _reps_by_key[key] = r
        log.info("loaded %d state legislators from %s", len(payload.get("reps", [])), REPS_NV_PATH.name)
    else:
        log.warning("no NV legislator file at %s — state-level reps will be empty", REPS_NV_PATH)

    # Hand-curated federal/regents/local
    if REPS_SEED_PATH.exists():
        with REPS_SEED_PATH.open() as f:
            seed = yaml.safe_load(f) or {}
        for r in seed.get("reps", []):
            key = (r["layer_id"], _normalize_district(r["district"]))
            _reps_by_key[key] = r
        log.info("loaded %d seeded reps from %s", len(seed.get("reps", [])), REPS_SEED_PATH.name)


def lookup(lat: float, lng: float) -> list[dict]:
    """Return one entry per layer with the matched district + rep (if known).

    Lookup time is O(log n) per layer thanks to STRtree; with ~104 polygons total
    across 8 layers, a single call returns in well under a millisecond.
    """
    load()
    pt = Point(lng, lat)  # GeoJSON / Shapely use (lng, lat)
    results: list[dict] = []
    for layer in sorted(_layers.values(), key=lambda x: x.sort_order):
        district_id, geometry = _find_district(layer, pt)
        rep = _reps_by_key.get((layer.layer_id, district_id)) if district_id else None
        results.append({
            "layer_id": layer.layer_id,
            "label": layer.label,
            "district": district_id,
            "geometry": geometry,
            "rep": rep,
            "recent_votes": _recent_votes_for(rep) if rep else [],
        })
    return results


def _find_district(layer: LayerIndex, pt: Point) -> tuple[str | None, dict | None]:
    if not layer.tree:
        return None, None
    # STRtree.query() returns candidate indices that *might* contain the point
    # (R-tree filters by bounding box). Confirm with .contains() per candidate.
    candidates = layer.tree.query(pt)
    for i in candidates:
        if layer.geometries[i].contains(pt):
            return layer.district_ids[i], layer.geom_json[i]
    return None, None


def _recent_votes_for(rep: dict, limit: int = 5) -> list[dict]:
    """Pull the rep's last N votes from item_votes joined to meetings.

    Matching is intentionally fuzzy: `item_votes.person` carries whatever string
    the agenda harvester captured (typically "Lastname" or "Firstname Lastname"),
    so we match by short_name with a wildcard. Returns [] for reps whose body
    isn't in civic-lens' Legistar coverage.
    """
    short = (rep.get("short_name") or "").strip()
    if not short:
        return []
    pattern = f"%{short}%"
    rows = []
    with db() as conn:
        rows = conn.execute(
            """
            SELECT m.event_id, m.body_name, m.meeting_date,
                   a.title, a.action_name, a.passed_flag,
                   v.vote
            FROM item_votes v
            JOIN agenda_items a ON a.event_item_id = v.event_item_id
            JOIN meetings    m ON m.event_id = a.event_id
            WHERE LOWER(v.person) LIKE LOWER(?)
            ORDER BY m.meeting_date DESC
            LIMIT ?
            """,
            (pattern, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def layer_list() -> list[dict]:
    """Public layer metadata for clients that want to render the map overlay."""
    load()
    return [
        {"layer_id": l.layer_id, "label": l.label, "sort_order": l.sort_order,
         "count": len(l.geometries)}
        for l in sorted(_layers.values(), key=lambda x: x.sort_order)
    ]


# Address geocoder — reuses the Clark County composite locator that civic-lens already
# hits for intersections, but uses SingleLine for a full street address. Same endpoint,
# different query field semantics.
_GEOCODER_URL = (
    "https://maps.clarkcountynv.gov/arcgis/rest/services/Locators/"
    "Clark_County_Composite/GeocodeServer/findAddressCandidates"
)
_MIN_SCORE = 70.0


def geocode_address(address: str) -> dict | None:
    """Resolve a street address via Clark County's composite locator. Returns
    {'lat', 'lng', 'matched_address', 'score'} or None on no match."""
    import httpx
    addr = re.sub(r"\s+", " ", address).strip()
    if not addr:
        return None
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(_GEOCODER_URL, params={
                "SingleLine": addr,
                "outFields": "Match_addr,Score,Addr_type",
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
    if score < _MIN_SCORE:
        return None
    loc = c.get("location") or {}
    if "x" not in loc or "y" not in loc:
        return None
    return {
        "lat": round(float(loc["y"]), 6),
        "lng": round(float(loc["x"]), 6),
        "matched_address": (c.get("attributes") or {}).get("Match_addr") or addr,
        "score": score,
    }
