import datetime as dt
import hashlib
import html
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from . import geocode, location, render, topics
from .config import BODIES, PUBLIC_BASE_URL
from .db import db, init_db

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Civic Lens", version="0.1.0", lifespan=lifespan)

_CSP = (
    "default-src 'self'; "
    "script-src 'self' https://analytics.grudged.io; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; "
    # MapLibre tiles/glyphs/sprites come from OpenFreeMap; the map's GL worker is a blob.
    "img-src 'self' data: blob: https://tiles.openfreemap.org; "
    "connect-src 'self' https://analytics.grudged.io https://tiles.openfreemap.org; "
    "worker-src blob:; "
    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("Content-Security-Policy", _CSP)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    return resp


# ---- shared queries --------------------------------------------------------
_MEETING_COLS = """m.event_id, m.body_id, m.body_name, m.body_slug, m.meeting_date, m.status,
    m.location, m.agenda_url, m.minutes_url, m.legistar_url,
    (SELECT count(*) FROM agenda_items a WHERE a.event_id = m.event_id) AS item_count,
    s.topics AS agg_topics, s.overview AS overview"""


def _meetings(where: str, params: tuple, order: str, limit: int = 50) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            f"SELECT {_MEETING_COLS} FROM meetings m "
            f"LEFT JOIN meeting_summaries s ON s.event_id = m.event_id "
            f"{where} ORDER BY m.meeting_date {order} LIMIT ?",
            params + (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def _gist(rows: list[dict], n: int = 165) -> dict[int, str]:
    out = {}
    for r in rows:
        ov = r.get("overview")
        if ov:
            out[r["event_id"]] = (ov[: n - 1] + "…") if len(ov) > n else ov
    return out


# ---- pages -----------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def home():
    upcoming = _meetings("WHERE m.status='upcoming'", (), "ASC", 12)
    recent = _meetings("WHERE m.status='past'", (), "DESC", 12)
    gist = _gist(upcoming + recent)
    body = render.landing(upcoming, recent, gist)
    desc = "Plain-English briefs on Clark County Board of Commissioners, Planning, and Zoning meetings — what's coming up and what was decided."
    return HTMLResponse(render.page("Civic Lens — Clark County meetings in plain English", desc, "/", body))


@app.get("/meeting/{event_id}", response_class=HTMLResponse)
def meeting(event_id: int):
    with db() as conn:
        m = conn.execute(
            f"SELECT {_MEETING_COLS} FROM meetings m LEFT JOIN meeting_summaries s "
            f"ON s.event_id = m.event_id WHERE m.event_id = ?", (event_id,)).fetchone()
        if m is None:
            return HTMLResponse(render.page("Meeting not found", "", f"/meeting/{event_id}",
                                            render.not_found("We don't have that meeting."), robots="noindex"),
                                status_code=404)
        m = dict(m)
        items = [dict(r) for r in conn.execute(
            "SELECT * FROM agenda_items WHERE event_id=? ORDER BY sequence", (event_id,)).fetchall()]
        votes_by_item: dict[int, list] = {}
        if items:
            ids = [it["event_item_id"] for it in items]
            vrows = conn.execute(
                f"SELECT event_item_id, person, vote FROM item_votes "
                f"WHERE event_item_id IN ({','.join('?'*len(ids))}) ORDER BY person", ids).fetchall()
            for v in vrows:
                votes_by_item.setdefault(v["event_item_id"], []).append(dict(v))

    has_geo = any(geocode.cache_key(location.extract(it.get("title") or "")) for it in items)
    body = render.meeting_record(m, items, votes_by_item, m.get("overview"), has_geo=has_geo)
    from .util import fmt_date
    title = f'{m["body_name"]} — {fmt_date(m["meeting_date"], with_time=False)} | Civic Lens'
    desc = (m.get("overview") or f'{m["item_count"]} agenda items for the {m["body_name"]}.')[:200]
    head_extra = render.MAP_HEAD if has_geo else ""
    body_end = render.MAP_BODY_END if has_geo else ""
    return HTMLResponse(render.page(title, desc, f"/meeting/{event_id}", body,
                                    head_extra=head_extra, body_end=body_end))


@app.get("/body/{slug}", response_class=HTMLResponse)
def body_view(slug: str):
    meta = next((b for b in BODIES.values() if b["slug"] == slug), None)
    if meta is None:
        return HTMLResponse(render.page("Not found", "", f"/body/{slug}",
                                        render.not_found("Unknown body."), robots="noindex"), status_code=404)
    rows = _meetings("WHERE m.body_slug=?", (slug,), "DESC", 60)
    body = render.body_page(slug, meta["name"], rows, _gist(rows))
    desc = f'Clark County {meta["name"]} meetings in plain English — upcoming agendas and past decisions.'
    return HTMLResponse(render.page(f'{meta["name"]} — Clark County | Civic Lens', desc, f"/body/{slug}", body))


@app.get("/topic/{slug}", response_class=HTMLResponse)
def topic_view(slug: str):
    if slug not in topics.TOPICS:
        return HTMLResponse(render.page("Not found", "", f"/topic/{slug}",
                                        render.not_found("Unknown topic."), robots="noindex"), status_code=404)
    # meetings that have at least one item tagged with this topic, newest first
    with db() as conn:
        rows = conn.execute(
            f"SELECT {_MEETING_COLS} FROM meetings m "
            f"LEFT JOIN meeting_summaries s ON s.event_id = m.event_id "
            f"WHERE m.event_id IN (SELECT event_id FROM agenda_items WHERE topics LIKE ?) "
            f"ORDER BY m.meeting_date DESC LIMIT 60", (f'%"{slug}"%',)).fetchall()
    rows = [dict(r) for r in rows]
    label = topics.label(slug)
    body = render.topic_page(slug, label, rows)
    return HTMLResponse(render.page(f"{label} — Clark County meetings | Civic Lens",
                                    f"Clark County meetings about {label.lower()}.", f"/topic/{slug}", body))


@app.get("/about", response_class=HTMLResponse)
def about():
    return HTMLResponse(render.page("About Civic Lens", "How Civic Lens turns Clark County meeting records into plain-English briefs.", "/about", render.about_page()))


@app.get("/map", response_class=HTMLResponse)
def map_page():
    desc = ("An interactive map of Clark County land-use and zoning items — see where development, "
            "rezonings, and use permits are up for decision, and how they were decided.")
    return HTMLResponse(render.page("Development map — Clark County | Civic Lens", desc, "/map",
                                    render.map_page(), head_extra=render.MAP_HEAD, body_end=render.MAP_BODY_END))


# ---- map data --------------------------------------------------------------
def _map_state(status: str, passed_flag) -> str:
    """Colour bucket: upcoming (pending) vs the decided outcomes."""
    if status == "upcoming":
        return "upcoming"
    if passed_flag == 1:
        return "passed"
    if passed_flag == 0:
        return "failed"
    return "decided"


def _jitter(seed, amp: float = 0.012) -> tuple[float, float]:
    """Deterministic small offset so multiple neighborhood-level pins at one centroid don't stack."""
    h = int(hashlib.md5(str(seed).encode()).hexdigest(), 16)
    dlat = ((h & 0xFFFF) / 0xFFFF - 0.5) * 2 * amp
    dlng = (((h >> 16) & 0xFFFF) / 0xFFFF - 0.5) * 2 * amp
    return dlat, dlng


def _map_features(rows: list[dict], geo: dict[str, dict]) -> list[dict]:
    feats = []
    for r in rows:
        ex = location.extract(r["title"] or "")
        key = geocode.cache_key(ex)
        g = geo.get(key) if key else None
        if not g or g["lat"] is None:
            continue
        lat, lng = g["lat"], g["lng"]
        if g["precision"] == "area":
            dlat, dlng = _jitter(r["event_item_id"])
            lat, lng = lat + dlat, lng + dlng
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(lng, 6), round(lat, 6)]},
            "properties": {
                "id": r["event_item_id"],
                "meeting_id": r["event_id"],
                "url": f"/meeting/{r['event_id']}",
                "state": _map_state(r["status"], r["passed_flag"]),
                "status": r["status"],
                "body": r["body_slug"],
                "body_name": r["body_name"],
                "date": (r["meeting_date"] or "")[:10],
                "text": r["plain_summary"] or r["title"],
                "where": ex.get("location") or g.get("label"),
                "zone": ex.get("zone"),
                "acres": ex.get("acres"),
                "topics": json.loads(r.get("topics") or "[]"),
                "precision": g["precision"],
            },
        })
    return feats


@app.get("/api/map.geojson")
def api_map(body: str | None = None, topic: str | None = None, status: str | None = None,
            days: int | None = None, meeting: int | None = None):
    where, params = [], []
    if body:
        where.append("m.body_slug=?"); params.append(body)
    if status in ("upcoming", "past"):
        where.append("m.status=?"); params.append(status)
    if meeting is not None:
        where.append("a.event_id=?"); params.append(meeting)
    if topic:
        where.append("a.topics LIKE ?"); params.append(f'%"{topic}"%')
    if days is not None:
        today = dt.date.today()
        where.append("substr(m.meeting_date,1,10) BETWEEN ? AND ?")
        params += [(today - dt.timedelta(days=days)).isoformat(),
                   (today + dt.timedelta(days=days)).isoformat()]
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    with db() as conn:
        rows = [dict(r) for r in conn.execute(
            f"SELECT a.event_item_id, a.event_id, a.title, a.plain_summary, a.passed_flag, "
            f"a.topics, m.body_slug, m.body_name, m.meeting_date, m.status "
            f"FROM agenda_items a JOIN meetings m ON m.event_id=a.event_id {clause} "
            f"ORDER BY m.meeting_date DESC", tuple(params)).fetchall()]
        geo = {r["geo_key"]: dict(r) for r in conn.execute(
            "SELECT geo_key, label, lat, lng, precision FROM geocodes WHERE lat IS NOT NULL").fetchall()}
    return JSONResponse({"type": "FeatureCollection", "features": _map_features(rows, geo)},
                        media_type="application/geo+json")


# ---- machine surfaces ------------------------------------------------------
@app.get("/api/health")
def health():
    with db() as conn:
        n = conn.execute("SELECT count(*) c FROM meetings").fetchone()["c"]
    return {"status": "ok", "service": "civic-lens", "meetings": n}


@app.get("/api/meetings")
def api_meetings(status: str | None = None, body: str | None = None, limit: int = 50):
    where, params = [], []
    if status in ("upcoming", "past"):
        where.append("m.status=?"); params.append(status)
    if body:
        where.append("m.body_slug=?"); params.append(body)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = _meetings(clause, tuple(params), "DESC", min(limit, 200))
    for r in rows:
        r["agg_topics"] = json.loads(r.get("agg_topics") or "[]")
        r.pop("overview", None)
    return JSONResponse(rows)


@app.get("/api/stats")
def api_stats():
    """Aggregate snapshot for the nightly collector + knowledge compiler (no PII). Includes the
    recent summarized meetings so Gemma's knowledge base gets real civic content to learn from."""
    with db() as conn:
        total = conn.execute("SELECT count(*) c FROM meetings").fetchone()["c"]
        by_status = {r["status"]: r["c"] for r in conn.execute(
            "SELECT status, count(*) c FROM meetings GROUP BY status").fetchall()}
        by_body = {r["body_slug"]: r["c"] for r in conn.execute(
            "SELECT body_slug, count(*) c FROM meetings GROUP BY body_slug").fetchall()}
        summarized = conn.execute("SELECT count(*) c FROM meeting_summaries WHERE overview IS NOT NULL").fetchone()["c"]
        items = conn.execute("SELECT count(*) c FROM agenda_items").fetchone()["c"]
        recent = [dict(r) for r in conn.execute(
            "SELECT m.event_id, m.body_name, m.body_slug, m.meeting_date, m.status, s.overview, s.topics, "
            "(SELECT count(*) FROM agenda_items a WHERE a.event_id=m.event_id) item_count "
            "FROM meetings m LEFT JOIN meeting_summaries s ON s.event_id=m.event_id "
            "ORDER BY m.meeting_date DESC LIMIT 20").fetchall()]
    for r in recent:
        r["topics"] = json.loads(r.get("topics") or "[]")
    return {"total_meetings": total, "by_status": by_status, "by_body": by_body,
            "summarized": summarized, "total_items": items, "recent": recent}


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return f"User-agent: *\nAllow: /\nSitemap: {PUBLIC_BASE_URL}/sitemap.xml\n"


@app.get("/sitemap.xml")
def sitemap():
    today = dt.date.today().isoformat()
    urls = [("/", "1.0"), ("/about", "0.4")]
    urls += [(f'/body/{b["slug"]}', "0.7") for b in BODIES.values()]
    urls += [(f"/topic/{s}", "0.5") for s in topics.TOPICS]
    with db() as conn:
        for r in conn.execute("SELECT event_id FROM meetings ORDER BY meeting_date DESC"):
            urls.append((f'/meeting/{r["event_id"]}', "0.8"))
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for path, pri in urls:
        loc = html.escape(f"{PUBLIC_BASE_URL}{path}")
        parts.append(f"<url><loc>{loc}</loc><lastmod>{today}</lastmod><priority>{pri}</priority></url>")
    parts.append("</urlset>")
    return Response("\n".join(parts), media_type="application/xml")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
