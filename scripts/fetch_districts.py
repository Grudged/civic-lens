#!/usr/bin/env python3
"""Fetch all district polygon layers from public ArcGIS Feature/Map Services.

Pulls 8 layers (US House, NV Senate/Assembly/Regents, Clark Co Commission,
Vegas wards, Henderson wards, CCSD trustees) as GeoJSON in WGS84 and writes
them to `data/districts/{layer_id}.geojson`.

Re-run after each redistricting cycle (≈ every 10 years) or after any local
council/trustee remap. Sources are public, no key required.

The `feature_key` for each layer is the property on each feature that holds
the district identifier ('1', '29', 'D', etc.). Verified against each layer's
schema on first run; the loader logs the actual field types so we notice if
a publisher renames a field.
"""
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import httpx

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger("fetch_districts")

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "districts"
USER_AGENT = "civic-lens/0.1 (+https://civic.grudged.io)"


@dataclass
class Layer:
    layer_id: str               # internal id — also becomes the filename
    label: str                  # human label for UI
    sort_order: int
    service_url: str            # FeatureServer or MapServer
    layer_index: int            # the layer id within the service
    feature_key: str            # field that holds the district identifier
    expected_count: int | None  # sanity check; None to skip


LAYERS: list[Layer] = [
    Layer(
        layer_id="us_house",
        label="U.S. House of Representatives",
        sort_order=10,
        service_url="https://services9.arcgis.com/UU5yXg9PV67U0ebq/arcgis/rest/services/2021Congressional_Final_SB1_Amd2/FeatureServer",
        layer_index=3,
        feature_key="DISTRICT",
        expected_count=4,
    ),
    Layer(
        layer_id="nv_senate",
        label="Nevada State Senate",
        sort_order=20,
        service_url="https://services9.arcgis.com/UU5yXg9PV67U0ebq/arcgis/rest/services/2021Senate_Final_SB1_Amd2/FeatureServer",
        layer_index=1,
        feature_key="DISTRICT",
        expected_count=21,
    ),
    Layer(
        layer_id="nv_assembly",
        label="Nevada State Assembly",
        sort_order=30,
        service_url="https://services9.arcgis.com/UU5yXg9PV67U0ebq/arcgis/rest/services/2021Assembly_Final_SB1_Amd2/FeatureServer",
        layer_index=0,
        feature_key="DISTRICT",
        expected_count=42,
    ),
    Layer(
        layer_id="nv_regents",
        label="Nevada Board of Regents",
        sort_order=40,
        service_url="https://services9.arcgis.com/UU5yXg9PV67U0ebq/arcgis/rest/services/2021Regents_BDR_Final/FeatureServer",
        layer_index=2,
        feature_key="DISTRICT",
        expected_count=13,
    ),
    Layer(
        layer_id="cc_commission",
        label="Clark County Commission",
        sort_order=50,
        service_url="https://maps.clarkcountynv.gov/arcgis/rest/services/AdminServ/CommissionerDistrict_p/FeatureServer",
        layer_index=0,
        feature_key="COMMISSION",
        expected_count=7,
    ),
    Layer(
        layer_id="ccsd_trustees",
        label="Clark County School District Trustees",
        sort_order=60,
        service_url="https://services1.arcgis.com/F1v0ufATbBQScMtY/arcgis/rest/services/CCSD_Trustees_2020_JAN_2025/FeatureServer",
        layer_index=426,
        feature_key="DISTRICT",       # 'A'..'G'; TRUSTEE holds the rep's name
        expected_count=7,
    ),
    Layer(
        # services1's CLV_WARDS layer 337 returns 91 precinct-level polygons; the
        # services2 mirror at layer 3 has the 6 merged ward polygons we actually
        # want. Same publisher (City of Las Vegas), different ArcGIS org.
        layer_id="lv_ward",
        label="Las Vegas City Council Ward",
        sort_order=70,
        service_url="https://services2.arcgis.com/MLoS3Qx4BXmDoTIY/arcgis/rest/services/CLV_WARDS/FeatureServer",
        layer_index=3,
        feature_key="WARD",
        expected_count=6,
    ),
    Layer(
        layer_id="hen_ward",
        label="Henderson City Council Ward",
        sort_order=80,
        service_url="https://maps.cityofhenderson.com/arcgis/rest/services/public/Elections/MapServer",
        layer_index=1,
        feature_key="WARD",
        expected_count=4,
    ),
]


def query_geojson(client: httpx.Client, layer: Layer) -> dict:
    """Query the layer for all features as GeoJSON in WGS84.

    ArcGIS services cap a single response at ~1000–2000 records. None of our layers
    come close (largest is Assembly at 42), so we don't paginate. If a future layer
    grows past the cap, add resultOffset-based paging here.
    """
    url = f"{layer.service_url}/{layer.layer_index}/query"
    params = {
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
    }
    full = f"{url}?{urlencode(params)}"
    log.info("Querying %s (%s)", layer.layer_id, full)
    r = client.get(full)
    r.raise_for_status()
    fc = r.json()
    if fc.get("type") != "FeatureCollection":
        raise RuntimeError(f"{layer.layer_id}: unexpected response (type={fc.get('type')})")
    return fc


def verify_feature_key(fc: dict, layer: Layer) -> str:
    """Confirm the configured feature_key exists; if not, try common fallbacks.

    Returns the actual field name to use. Logs loudly when the configured key is
    missing — that's the signal a publisher renamed something and we need to
    update LAYERS.
    """
    features = fc.get("features") or []
    if not features:
        raise RuntimeError(f"{layer.layer_id}: zero features returned")
    props = features[0].get("properties") or {}
    if layer.feature_key in props:
        return layer.feature_key

    # Fallback: pick the first field whose name looks district-ish and has values
    # that differ across features (so we don't mis-pick e.g. a county field).
    candidates = ["DISTRICT", "WARD", "COMMISSION", "TRUSTEE", "DIST", "DISTRICT_NO", "DIST_NUM", "NAME"]
    for cand in candidates:
        if cand in props:
            log.warning(
                "%s: configured key %r missing; using fallback %r. Update LAYERS.",
                layer.layer_id, layer.feature_key, cand,
            )
            return cand
    raise RuntimeError(
        f"{layer.layer_id}: no district field found. "
        f"Properties: {list(props.keys())[:15]}"
    )


def normalize_district_value(val) -> str:
    """ArcGIS sometimes types district as Double (1.0); stringify as plain ints
    when possible so '1' matches '1' across layers."""
    if val is None:
        return ""
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    return str(val).strip()


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary: list[tuple[str, int, str]] = []  # layer_id, count, actual_key

    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60.0) as client:
        for layer in LAYERS:
            try:
                fc = query_geojson(client, layer)
            except Exception as e:
                log.error("%s: fetch failed — %s", layer.layer_id, e)
                summary.append((layer.layer_id, -1, "FETCH_ERROR"))
                continue

            features = fc.get("features") or []
            actual_key = verify_feature_key(fc, layer)

            # Normalize the district identifier into a stable string field so the
            # endpoint can do `feature.properties.district_id` regardless of source.
            for f in features:
                props = f.setdefault("properties", {})
                props["district_id"] = normalize_district_value(props.get(actual_key))

            if layer.expected_count is not None and len(features) != layer.expected_count:
                log.warning(
                    "%s: expected %d features, got %d",
                    layer.layer_id, layer.expected_count, len(features),
                )

            out_path = OUT_DIR / f"{layer.layer_id}.geojson"
            out_path.write_text(json.dumps(fc) + "\n")
            log.info("Wrote %d features → %s (key=%s)", len(features), out_path, actual_key)
            summary.append((layer.layer_id, len(features), actual_key))

    # Manifest tells the API which files to load and how to label them.
    manifest = {
        "as_of": __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "layers": [
            {
                "layer_id": l.layer_id,
                "label": l.label,
                "sort_order": l.sort_order,
                "geojson_path": f"data/districts/{l.layer_id}.geojson",
                "source_url": f"{l.service_url}/{l.layer_index}",
            }
            for l in LAYERS
        ],
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    print("\n=== Summary ===")
    for layer_id, count, key in summary:
        print(f"  {layer_id:18s} count={count:4d}  key={key}")
    failures = [s for s in summary if s[1] < 0]
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
