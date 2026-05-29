# Civic Lens

Plain-English coverage of Clark County, Nevada government meetings. A free, no-account public-good
tool: it reads the county's public meeting record and turns dense agendas into briefs ordinary
residents can follow — what's coming up, what was decided, and how each member voted. Every summary
links back to the official record and is labeled as AI-generated.

Part of the Grudged "access infrastructure" line (sibling to FirstEmbark / Open Scholarships).

## Phase 1 (this build)
- **Source:** Clark County **Legistar Web API** (`webapi.legistar.com/v1/clark`) — public, no key.
- **Bodies:** Board of Commissioners, Planning Commission, Zoning Commission.
- **Coverage:** upcoming agendas *and* past outcomes (roll-call votes included).
- **Summaries:** Gemma 4 (MLX) writes a plain-English meeting overview + one-sentence rewrite of each
  agenda item. Topics are tagged deterministically (keyword vocabulary in `app/topics.py`).
- **Map:** `/map` plots every land-use/zoning item with a mappable location (MapLibre + OpenFreeMap
  tiles). Coordinates come from the free Clark County address locator (exact corners) with a township
  centroid fallback; data served as GeoJSON at `/api/map.geojson`. Per-meeting pages get a mini-map.
- **Surface:** server-rendered SEO pages — `/`, `/map`, `/meeting/{id}`, `/body/{slug}`, `/topic/{slug}`,
  `/about`, plus `/sitemap.xml`, `/robots.txt`, and JSON APIs at `/api/meetings` and `/api/map.geojson`.

## Architecture
```
collect.py          Legistar -> civic.db (meetings, agenda_items, item_votes, topics)  [deterministic]
geocode_job.py      civic.db titles -> Clark County locator / centroids -> geocodes    [deterministic]
summarize_job.py    civic.db -> Gemma (MLX) -> overviews + plain rewrites              [best-effort]
app/                FastAPI: render.py (HTML), main.py (routes), legistar/summarize/topics/geocode/db
```
SQLite at `DB_PATH` (`/data/civic.db` on Arch). Summaries call MLX on the Mac (`MLX_URL`); if MLX is
unreachable the site still renders the raw agenda — a summary outage never breaks a page.

## Run (dev, on the Mac where MLX lives)
```bash
python -m venv venv && venv/bin/pip install -r requirements.txt
cp .env.example .env
DB_PATH=./civic.db venv/bin/python collect.py            # pull meetings
DB_PATH=./civic.db venv/bin/python geocode_job.py        # map coordinates (Clark County locator)
DB_PATH=./civic.db venv/bin/python summarize_job.py      # Gemma summaries (MLX on :8321)
DB_PATH=./civic.db venv/bin/uvicorn app.main:app --port 8902
```

## Deploy (Arch)
1. Clone to `/home/grudged/repos/civic-lens`, create venv + `pip install -r requirements.txt`.
2. `cp .env.example .env`; set `DB_PATH=/data/civic.db`, `PUBLIC_BASE_URL=https://<domain>`,
   `MLX_URL=http://192.168.0.79:8321` (the Mac).
3. `sudo ufw allow from 192.168.0.0/24 to any port 8902`
4. Install units from `deploy/` (`civic-lens.service` + collect/summarize `.service`/`.timer`),
   `systemctl enable --now`.
5. Nginx `.lan` proxy + public domain as needed.

## Next (phase 2)
- Topic / neighborhood email + Telegram alerts.
- CCSD School Board (BoardDocs) and City of Las Vegas (PrimeGov).
- Wire-in: knowledge compiler + training pairs, Mission Control tab, monitoring, integration-health.

> Independent civic project — not affiliated with or endorsed by Clark County.
