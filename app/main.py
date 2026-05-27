import datetime as dt
import html
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from . import render, topics
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
    "img-src 'self' data:; connect-src 'self' https://analytics.grudged.io; "
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

    body = render.meeting_record(m, items, votes_by_item, m.get("overview"))
    from .util import fmt_date
    title = f'{m["body_name"]} — {fmt_date(m["meeting_date"], with_time=False)} | Civic Lens'
    desc = (m.get("overview") or f'{m["item_count"]} agenda items for the {m["body_name"]}.')[:200]
    return HTMLResponse(render.page(title, desc, f"/meeting/{event_id}", body))


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
