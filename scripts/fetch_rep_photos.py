#!/usr/bin/env python3
"""Download representative headshots from each rep's official source.

Pulls 31 photos (4 US House + 13 NV Regents + 7 Clark County Commission +
7 CCSD Trustees) into `app/static/reps/{rep_id}.jpg`. Re-run after each
election cycle when seats turn over.

LV City Council + Henderson City Council photos aren't included — those
sites either don't expose direct image URLs or 403 on programmatic fetch.
Those rows show the placeholder pattern until added manually.

Sources are public official pages; photos are public-domain (federal) or
official government portraits and clearly redistributable for civic use.
"""
import json
import logging
import sys
from pathlib import Path

import httpx

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger("fetch_rep_photos")

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "app" / "static" / "reps"
# Wikimedia / Wikipedia rate-limit generic "Mozilla" UAs to 429. Their bot policy
# requires a contact-bearing identifier — meet that and the downloads go through.
USER_AGENT = "civic-lens/0.1 (https://civic.grudged.io; chris@grudged.io)"

# rep_id → source URL. Filenames mirror rep_id verbatim so they match what
# the seed YAML expects (`photo_url: /static/reps/<rep_id>.jpg`).
SOURCES: dict[str, str] = {
    # U.S. House — Wikipedia infobox originals (public-domain federal portraits).
    "us_house:1": "https://upload.wikimedia.org/wikipedia/commons/6/6d/Dina_Titus_official_photo.jpg",
    "us_house:2": "https://upload.wikimedia.org/wikipedia/commons/1/17/Mark_Amodei_official_photo_%28cropped%29.jpg",
    "us_house:3": "https://susielee.house.gov/sites/evo-subsites/susielee-evo.house.gov/files/styles/large/public/evo-media-image/119th-congress-rep-susie-lee-official-protrait.jpg",
    "us_house:4": "https://upload.wikimedia.org/wikipedia/commons/6/61/Steven_Horsford_118th.jpeg",

    # Nevada Board of Regents — direct uploads from the NSHE site.
    "nv_regents:1":  "https://nshe.nevada.edu/regents/wp-content/uploads/sites/3/2025/01/Fernandez-Carlos-D-240x300.jpg",
    "nv_regents:2":  "https://nshe.nevada.edu/regents/wp-content/uploads/sites/3/2024/11/McGrath-Jennifer-J-240x300.jpg",
    "nv_regents:3":  "https://nshe.nevada.edu/regents/wp-content/uploads/sites/3/2022/02/regent-photo-byron-brooks-240x300.jpg",
    "nv_regents:4":  "https://nshe.nevada.edu/regents/wp-content/uploads/sites/3/2025/01/Bautista-Aaron-240x300.jpg",
    "nv_regents:5":  "https://nshe.nevada.edu/regents/wp-content/uploads/sites/3/2022/04/regent-photo-patrick-boylan-240x300.jpg",
    "nv_regents:6":  "https://nshe.nevada.edu/regents/wp-content/uploads/sites/3/2023/01/regent-photo-heather-brown-240x300.jpg",
    "nv_regents:7":  "https://nshe.nevada.edu/regents/wp-content/uploads/sites/3/2023/01/regent-photo-susan-brager-240x300.jpg",
    "nv_regents:8":  "https://nshe.nevada.edu/regents/wp-content/uploads/sites/3/2024/12/Goicoechea-Pete-200x300.jpg",
    "nv_regents:9":  "https://nshe.nevada.edu/regents/wp-content/uploads/sites/3/2022/04/regent-photo-carol-del-carlo-240x300.jpg",
    "nv_regents:10": "https://nshe.nevada.edu/regents/wp-content/uploads/sites/3/2022/04/regent-photo-joseph-arrascada-240x300.jpg",
    "nv_regents:11": "https://nshe.nevada.edu/regents/wp-content/uploads/sites/3/2023/01/regent-photo-jeffrey-downs-240x300.jpg",
    "nv_regents:12": "https://nshe.nevada.edu/regents/wp-content/uploads/sites/3/2022/04/regent-photo-amy-carvalho-240x300.jpg",
    "nv_regents:13": "https://nshe.nevada.edu/regents/wp-content/uploads/sites/3/2023/01/regent-photo-stephanie-goodman-240x300.jpg",

    # Clark County Commission — official Adobe AEM-hosted portraits.
    "cc_commission:A": "https://www.clarkcountynv.gov/adobe/assets/urn:aaid:aem:216e1b45-bc22-4f67-9ddb-6af03b44cf8c/as/commissioner-naft-dist-a.jpg",
    "cc_commission:B": "https://www.clarkcountynv.gov/adobe/assets/urn:aaid:aem:6e201ef6-6aaa-47bc-9ea3-1c54202ebd69/as/commissioner-kirkpatrick-dist-b.jpg",
    "cc_commission:C": "https://www.clarkcountynv.gov/adobe/assets/urn:aaid:aem:d2f2d7c7-5d31-4d0b-9a02-423ccce4d989/as/commissioner-becker-dist-c.jpg",
    "cc_commission:D": "https://www.clarkcountynv.gov/adobe/assets/urn:aaid:aem:a7f197d7-f947-4987-9235-161775bc136a/as/commissioner-mccurdy-ii-dist-d.jpg",
    "cc_commission:E": "https://www.clarkcountynv.gov/adobe/assets/urn:aaid:aem:b2de002e-8832-4492-b3a6-491cf8dacd23/as/commissioner-segerblom-dist-e.jpg",
    "cc_commission:F": "https://www.clarkcountynv.gov/adobe/assets/urn:aaid:aem:83fba492-9def-41bd-ae69-40c72bb61337/as/commissioner-jones-dist-f.jpg",
    "cc_commission:G": "https://www.clarkcountynv.gov/adobe/assets/urn:aaid:aem:6c1b8a56-975f-4ade-ba2a-8c897996561f/as/commissioner-gibson-dist-g.jpg",

    # CCSD Trustees — Finalsite CDN URLs, current as of the 2025 board cycle.
    "ccsd_trustees:A": "https://resources.finalsite.net/images/f_auto,q_auto/v1764872958/ccsdnet/xp21wk3vouyih4bex2is/E-Stevens-2025-Headshot-Edited-1-r21l901dwlfomq6kuvfldedsvs86anhgp23rf8au9w.jpg",
    "ccsd_trustees:B": "https://resources.finalsite.net/images/f_auto,q_auto/v1764872665/ccsdnet/glmbs3wkk39xql4srqov/L-Dominguez-2025-Headshot-Edited-r21kzxve1316q1ccrgg1u6our2vt3oils7q9w7qg90.jpg",
    "ccsd_trustees:C": "https://resources.finalsite.net/images/f_auto,q_auto/v1764872313/ccsdnet/ndoqrzx7wpnvbbpvj5gc/T-Henry-2025-Headshot-Edited-r21kujasqdmtyr6zbmca01sfsbituc261gorjxqy10.jpg",
    "ccsd_trustees:D": "https://resources.finalsite.net/images/f_auto,q_auto/v1764872214/ccsdnet/xeydbtyjoq8aeu9yaknl/Zamora-2025-r79dwsdp4xhq0bnhhcr1sujrciio4l8zuyk5ryqev8.jpg",
    "ccsd_trustees:E": "https://resources.finalsite.net/images/f_auto,q_auto/v1764872501/ccsdnet/y2mbm6haww2fdztncbdk/L-Biassotti-Headshot-2025-r21kxje8kbqt1wtysf2dgsig3mq1fizasbplqrao5g.jpg",
    "ccsd_trustees:F": "https://resources.finalsite.net/images/f_auto,q_auto/v1764872124/ccsdnet/hy9xtt5lvn9log2zqfo6/Adams-2024-1.jpg",
    "ccsd_trustees:G": "https://resources.finalsite.net/images/f_auto,q_auto/v1764872599/ccsdnet/ujyk1qyxw0sdlopd5sjh/Cavazos_2025.jpg",
}


def safe_filename(rep_id: str) -> str:
    """`us_house:1` → `us_house-1.jpg` (colon is fine on Mac/Linux but ugly in URLs)."""
    return rep_id.replace(":", "-") + ".jpg"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    saved: list[tuple[str, str, int]] = []  # rep_id, filename, bytes
    failed: list[tuple[str, str]] = []      # rep_id, reason

    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30.0, follow_redirects=True) as client:
        for rep_id, url in SOURCES.items():
            try:
                r = client.get(url)
                r.raise_for_status()
            except Exception as e:
                failed.append((rep_id, f"{type(e).__name__}: {e}"))
                continue
            data = r.content
            # Sanity: photos are typically 5-200KB. Anything below 2KB is almost
            # certainly an HTML error page or placeholder.
            if len(data) < 2048:
                failed.append((rep_id, f"too small ({len(data)} bytes)"))
                continue
            fname = safe_filename(rep_id)
            (OUT_DIR / fname).write_bytes(data)
            saved.append((rep_id, fname, len(data)))
            log.info("saved %s (%d bytes)", fname, len(data))

    print("\n=== Saved ===")
    for rep_id, fname, n in saved:
        print(f"  {rep_id:22s} → /static/reps/{fname}  ({n // 1024} KB)")
    if failed:
        print("\n=== Failed ===")
        for rep_id, reason in failed:
            print(f"  {rep_id:22s} {reason}")
    print(f"\n{len(saved)}/{len(SOURCES)} downloaded.")
    # Emit a YAML-ready map of rep_id → photo_url so the seed update is mechanical.
    yaml_path = OUT_DIR / "_photo_paths.json"
    yaml_path.write_text(json.dumps(
        {rid: f"/static/reps/{safe_filename(rid)}" for rid, _, _ in saved},
        indent=2,
    ) + "\n")
    print(f"\nWrote {yaml_path} for seed YAML update.")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
