#!/usr/bin/env python3
"""Scrape current NV Senate + Assembly rosters from leg.state.nv.us.

Writes `data/representatives_nv.json` — name, district, party, photo, term-end, email,
phones — for every sitting state legislator. Runs once after each general election (2-yr
cadence); no key, no auth, no rate limits to worry about (2 page fetches).

The Nevada Legislature's site is the authoritative source — photos and contact info
live under the current Session number in the image path (e.g. `Session/84th2027/...`).
After a new session starts, photo URLs change; re-run this scraper.

Emails on the page are Cloudflare-obfuscated; decoded inline (simple XOR cipher).

Federal + Regents + local council reps stay hand-curated (`data/representatives_seed.yaml`)
and are merged at app boot — they're not on this site.
"""
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger("scrape_legislators")

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "data" / "representatives_nv.json"
USER_AGENT = "civic-lens/0.1 (+https://civic.grudged.io)"
ROSTERS = {
    "nv_senate": "https://www.leg.state.nv.us/App/Legislator/A/Senate/Current",
    "nv_assembly": "https://www.leg.state.nv.us/App/Legislator/A/Assembly/Current",
}
PROFILE_BASE = "https://www.leg.state.nv.us"

PARTY_MAP = {"democratic": "D", "republican": "R", "independent": "I", "nonpartisan": "NP"}


def decode_cfemail(hex_str: str) -> str:
    """Decode a Cloudflare-obfuscated email. The first byte is the XOR key; the rest is
    the email's hex-encoded bytes XOR'd with that key."""
    key = int(hex_str[:2], 16)
    return "".join(chr(int(hex_str[i : i + 2], 16) ^ key) for i in range(2, len(hex_str), 2))


def normalize_name(last_first: str) -> tuple[str, str]:
    """'Buck, Carrie Ann' -> ('Carrie Ann Buck', 'Buck'). Quoted nicknames are stripped from
    the full name but kept available if we ever want them."""
    last_first = last_first.strip()
    if "," in last_first:
        last, first = (s.strip() for s in last_first.split(",", 1))
    else:
        last, first = last_first, ""
    first = re.sub(r'\s*"[^"]+"', "", first).strip()
    full = f"{first} {last}".strip() if first else last
    return full, last


def parse_roster(html: str, layer_id: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    reps: list[dict] = []

    # Each legislator is two adjacent <tr> rows: header row (photo, name, party, district,
    # county) followed by a details row (term, email, rooms, phones). They share an anchor
    # href like /App/Legislator/A/Senate/Current/{district}.
    rows = soup.select("tr.thisRow")
    i = 0
    while i < len(rows):
        header = rows[i]
        cells = header.find_all("td")
        if len(cells) < 5:
            i += 1
            continue

        link = header.select_one('a[href*="/App/Legislator/A/"]')
        if not link:
            i += 1
            continue
        href = link.get("href", "")
        m = re.search(r"/Current/(\d+)", href)
        if not m:
            i += 1
            continue
        district = m.group(1)

        img = header.select_one("img")
        photo_url = img.get("src") if img else None

        # data-order attributes carry the raw values without the &nbsp;/markup noise.
        name_cell = cells[1]
        party_cell = cells[2]
        full_name, short_name = normalize_name(
            name_cell.get("data-order") or name_cell.get_text(strip=True)
        )
        party_raw = (party_cell.get("data-order") or party_cell.get_text(strip=True)).lower()
        party = PARTY_MAP.get(party_raw, party_raw[:1].upper() or None)

        # The details row sits at rows[i+1]. Pull labeled fields by walking the field name
        # spans — order isn't guaranteed (some legislators omit a phone), so don't index.
        details: dict[str, str] = {}
        if i + 1 < len(rows):
            for fname in rows[i + 1].select("span.fieldName"):
                label = fname.get_text(strip=True).rstrip(":")
                field = fname.find_next("span", class_="field")
                if field:
                    details[label] = field.get_text(" ", strip=True)

            email = None
            cf = rows[i + 1].select_one(".__cf_email__")
            if cf and cf.get("data-cfemail"):
                try:
                    email = decode_cfemail(cf["data-cfemail"])
                except Exception:
                    log.warning("Failed to decode email for %s (district %s)", full_name, district)

        rep_id = f"{layer_id}:{district}"
        reps.append(
            {
                "rep_id": rep_id,
                "layer_id": layer_id,
                "district": district,
                "full_name": full_name,
                "short_name": short_name,
                "party": party,
                "term_ends": details.get("Term Ends"),
                "photo_url": photo_url,
                "profile_url": f"{PROFILE_BASE}{href}" if href.startswith("/") else href,
                "contact_email": email,
                "contact_phone": details.get("Carson City Phone") or details.get("Work Phone"),
                "office_carson_city": details.get("Carson City Room"),
                "office_las_vegas": details.get("Las Vegas Room"),
                "source": "leg.state.nv.us",
            }
        )
        i += 2

    return reps


def fetch(url: str) -> str:
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30.0) as client:
        r = client.get(url)
        r.raise_for_status()
        return r.text


def main() -> int:
    all_reps: list[dict] = []
    for layer_id, url in ROSTERS.items():
        log.info("Fetching %s", url)
        html = fetch(url)
        reps = parse_roster(html, layer_id)
        log.info("Parsed %d legislators from %s", len(reps), layer_id)
        all_reps.extend(reps)

    senate = [r for r in all_reps if r["layer_id"] == "nv_senate"]
    assembly = [r for r in all_reps if r["layer_id"] == "nv_assembly"]
    if len(senate) != 21:
        log.warning("Expected 21 senators, got %d", len(senate))
    if len(assembly) != 42:
        log.warning("Expected 42 assembly members, got %d", len(assembly))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "leg.state.nv.us scrape",
        "count": len(all_reps),
        "reps": all_reps,
    }
    OUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    log.info("Wrote %d representatives → %s", len(all_reps), OUT_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
