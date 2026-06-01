"""Server-rendered HTML for Civic Lens — the SEO surface IS the product, so pages render fully
in the initial HTML (no client framework). Design "The Public Record": Newsreader display +
Public Sans body, newsprint + ballot-indigo + civic-brass, a civic-docket structure. Distinct
from the other Grudged products per BRAND.md; carries the shared "A Grudged project" mark.
"""
from __future__ import annotations

import html
import json
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

from .config import AI_DISCLAIMER, BODIES, PUBLIC_BASE_URL

from . import glossary, location, topics
from .util import fmt_date, fmt_date_short

_PACIFIC = ZoneInfo("America/Los_Angeles")  # Clark County meetings are Pacific time

_FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?'
    'family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;0,6..72,600;1,6..72,400'
    '&family=Public+Sans:ital,wght@0,400;0,500;0,600;0,700;1,400&display=swap" rel="stylesheet">'
)
_UMAMI = ('<script defer src="https://analytics.grudged.io/script.js" '
          'data-website-id="a593cc84-67df-424e-8912-70f04fa9e298"></script>')

_NAV = [
    ("/", "Latest"),
    ("/map", "Map"),
    ("/body/board-of-commissioners", "Commissioners"),
    ("/body/planning-commission", "Planning"),
    ("/body/zoning-commission", "Zoning"),
    ("/about", "About"),
]

# Self-hosted MapLibre (keeps script-src 'self'); OpenFreeMap tiles are allowed in the CSP.
MAP_HEAD = '<link rel="stylesheet" href="/static/vendor/maplibre/maplibre-gl.css">'
MAP_BODY_END = ('<script src="/static/vendor/maplibre/maplibre-gl.js"></script>'
                '<script src="/static/js/map.js" defer></script>'
                '<script src="/static/js/calc.js" defer></script>')


def _esc(s) -> str:
    return html.escape(str(s)) if s is not None else ""


def _person(name: str) -> str:
    """Legistar gives 'Last, First' — show 'First Last'."""
    if name and "," in name:
        last, first = name.split(",", 1)
        return f"{first.strip()} {last.strip()}"
    return name or ""


def page(title: str, description: str, canonical_path: str, body: str, robots: str | None = None,
         head_extra: str = "", body_end: str = "") -> str:
    canonical = f"{PUBLIC_BASE_URL}{canonical_path}"
    robots_tag = f'<meta name="robots" content="{robots}">' if robots else ""
    nav = "".join(f'<a href="{h}">{_esc(t)}</a>' for h, t in _NAV)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(title)}</title>
<meta name="description" content="{_esc(description)}">
<link rel="canonical" href="{_esc(canonical)}">
{robots_tag}
<meta property="og:type" content="website">
<meta property="og:site_name" content="Civic Lens">
<meta property="og:title" content="{_esc(title)}">
<meta property="og:description" content="{_esc(description)}">
<meta property="og:url" content="{_esc(canonical)}">
<meta name="twitter:card" content="summary">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='86'>🏛️</text></svg>">
{_FONTS}
<link rel="stylesheet" href="/static/css/app.css">
{head_extra}
{_UMAMI}
</head>
<body>
<header class="masthead">
  <div class="mast-inner">
    <a class="wordmark" href="/">Civic<span>Lens</span></a>
    <nav class="mast-nav" aria-label="Primary">{nav}</nav>
  </div>
  <p class="mast-tag">Plain-English coverage of Clark County government</p>
</header>
<main id="main">
{body}
</main>
<footer class="site-footer">
  <div class="foot-inner">
    <p class="foot-disclaimer">{_esc(AI_DISCLAIMER)}</p>
    <p class="foot-src">Meeting data from the public <a href="https://clark.legistar.com" target="_blank" rel="noopener">Clark County Legistar</a> record. Summaries written by an AI assistant; this is an independent civic project, not affiliated with Clark County.</p>
    <p class="grudged-mark"><a href="https://grudged.io" target="_blank" rel="noopener">A Grudged project ↗</a></p>
  </div>
</footer>
<script src="/static/js/countdown.js" defer></script>
{body_end}
</body>
</html>"""


def map_page() -> str:
    bodies = "".join(f'<option value="{b["slug"]}">{_esc(b["name"])}</option>' for b in BODIES.values())
    topic_opts = "".join(f'<option value="{s}">{_esc(topics.label(s))}</option>' for s in topics.TOPICS)
    legend = "".join(
        f'<span class="lg-item"><span class="lg-dot {cls}"></span>{_esc(lbl)}</span>'
        for cls, lbl in (("upcoming", "Up for decision"), ("passed", "Approved"),
                         ("failed", "Denied"), ("decided", "Other action")))
    return f"""
<section class="lede-block">
  <p class="kicker">Clark County, Nevada</p>
  <h1>Where the county is deciding.</h1>
  <p class="lede">Every zoning, land-use, and development item with a mappable location — pinned to
  the corner it concerns. Amber pins are coming up for a decision; green and red are already
  decided. Click a pin for the plain-English brief and a link to the full meeting record.</p>
</section>

<section class="calc" aria-labelledby="calc-h">
  <p class="kicker">Find your representatives</p>
  <h2 id="calc-h">Who decides for this address?</h2>
  <form id="calc-form" class="calc-form" role="search" autocomplete="off">
    <label class="vh" for="calc-input">Street address</label>
    <input id="calc-input" class="calc-input" type="text"
           placeholder="178 Shaded Peak St, Henderson NV"
           inputmode="text" autocapitalize="words" spellcheck="false" required />
    <button class="calc-submit" type="submit">Look up</button>
    <p class="calc-hint">Address only — we don't store it. Clark County addresses work best.</p>
  </form>
  <div id="calc-status" class="calc-status" role="status" aria-live="polite"></div>
  <div id="calc-results" class="calc-results" hidden></div>
</section>

<h2 class="section-h">The development docket</h2>
<div class="map-controls" role="group" aria-label="Map filters">
  <label class="ctl"><span>Body</span>
    <select id="flt-body"><option value="">All bodies</option>{bodies}</select></label>
  <label class="ctl"><span>Status</span>
    <select id="flt-status">
      <option value="">Upcoming &amp; decided</option>
      <option value="upcoming">Up for decision</option>
      <option value="decided">Decided</option>
    </select></label>
  <label class="ctl"><span>Topic</span>
    <select id="flt-topic"><option value="">All topics</option>{topic_opts}</select></label>
  <span class="map-count" id="map-count"></span>
</div>
<div class="map-legend">{legend}<span class="lg-note">Hollow pins are approximate (neighborhood level).</span></div>
<div id="map" class="map-canvas" data-src="/api/map.geojson"></div>
<p class="map-foot muted">Pins are placed from the official agenda wording via the Clark County
address locator; some are approximate. {_esc(AI_DISCLAIMER)}</p>
"""


def _stamp(action_name, passed_flag, status) -> str:
    if status == "upcoming":
        return '<span class="stamp upcoming">Upcoming</span>'
    if passed_flag == 1:
        return '<span class="stamp passed">Passed</span>'
    if passed_flag == 0:
        return '<span class="stamp failed">Failed</span>'
    if action_name:
        return f'<span class="stamp neutral">{_esc(action_name)}</span>'
    return '<span class="stamp neutral">No action recorded</span>'


def _topic_pills(slugs: list[str]) -> str:
    if not slugs:
        return ""
    pills = "".join(f'<a class="pill" href="/topic/{s}">{_esc(topics.label(s))}</a>' for s in slugs)
    return f'<div class="pills">{pills}</div>'


def _dateline(body_name: str, date_iso: str) -> str:
    return f'<p class="dateline">{_esc(body_name)} <span>·</span> {_esc(fmt_date_short(date_iso))} <span>·</span> Las Vegas</p>'


def _countdown_span(meeting_date: str, status: str) -> str:
    """A self-contained countdown phrase ('in 5d 14h') as a <span class="countdown" data-when=…>.
    Server renders a static fallback (SEO / no-JS); countdown.js upgrades it to a live ticker.
    Empty for past meetings. Server clock is Pacific = the meeting tz, and the audience is local,
    so the naive datetime compares correctly on both ends."""
    if status != "upcoming":
        return ""
    try:
        dt = datetime.fromisoformat(meeting_date).replace(tzinfo=_PACIFIC)
    except ValueError:
        return ""
    secs = (dt - datetime.now(_PACIFIC)).total_seconds()
    if secs <= 0:
        text, soon = "happening today", True
    else:
        days, rem = divmod(int(secs), 86400)
        hrs, rem = divmod(rem, 3600)
        if days >= 1:
            text = f"in {days}d {hrs}h"
        elif hrs >= 1:
            text = f"in {hrs}h {rem // 60}m"
        else:
            text = f"in {int(secs // 60)}m"
        soon = secs < 2 * 86400
    cls = "countdown soon" if soon else "countdown"
    # data-when carries the explicit Pacific offset (…-07:00) so any visitor's browser computes the
    # right remaining time regardless of their own timezone.
    return f'<span class="{cls}" data-when="{_esc(dt.isoformat())}">{text}</span>'


# ---- listing card ----------------------------------------------------------
def dispatch_card(m: dict, gist: str | None) -> str:
    snippet = gist or f'{m["item_count"]} agenda items'
    stamp = '<span class="stamp upcoming">Upcoming</span>' if m["status"] == "upcoming" else '<span class="stamp neutral">Decided</span>'
    # The card is a <div>, NOT an <a>: the topic pills are themselves <a> links and anchors can't
    # nest (a nested <a> auto-closes the card anchor, spilling the pills out as siblings). A
    # stretched overlay link makes the whole card clickable while the pills stay individually live.
    label = f'{_esc(m["body_name"])} {_esc(fmt_date(m["meeting_date"], with_time=False))}'
    cd = _countdown_span(m["meeting_date"], m["status"])
    cd_line = f'<p class="cd-line">&#9203; {cd}</p>' if cd else ''
    return (
        f'<div class="dispatch">'
        f'<a class="stretch" href="/meeting/{m["event_id"]}" aria-label="{label}"></a>'
        f'{_dateline(m["body_name"], m["meeting_date"])}'
        f'<h3>{_esc(m["body_name"])}</h3>'
        f'<p class="when">{_esc(fmt_date(m["meeting_date"]))}</p>'
        f'{cd_line}'
        f'<p class="dispatch-gist">{_esc(snippet)}</p>'
        f'{_topic_pills(json.loads(m.get("agg_topics") or "[]"))}'
        f'<div class="card-foot">{stamp}<span class="go">Read the brief →</span></div>'
        f'</div>'
    )


# ---- meeting record page ---------------------------------------------------
def meeting_record(m: dict, items: list[dict], votes_by_item: dict[int, list], overview: str | None,
                   has_geo: bool = False) -> str:
    title_h = f'{_esc(m["body_name"])} — {_esc(fmt_date(m["meeting_date"], with_time=False))}'
    when = _esc(fmt_date(m["meeting_date"]))
    loc = f' <span>·</span> {_esc(m["location"])}' if m.get("location") else ""

    gist = ""
    if overview:
        gist = (f'<section class="gist"><h2>The gist</h2><p>{glossary.annotate(overview)}</p>'
                f'<p class="disclaimer">{_esc(AI_DISCLAIMER)}</p></section>')

    sources = []
    if m.get("agenda_url"):
        sources.append(f'<a href="{_esc(m["agenda_url"])}" target="_blank" rel="noopener">Official agenda (PDF) ↗</a>')
    if m.get("minutes_url"):
        sources.append(f'<a href="{_esc(m["minutes_url"])}" target="_blank" rel="noopener">Official minutes (PDF) ↗</a>')
    if m.get("legistar_url"):
        sources.append(f'<a href="{_esc(m["legistar_url"])}" target="_blank" rel="noopener">Full record on Legistar ↗</a>')
    source_row = f'<div class="source-row">{"".join(sources)}</div>' if sources else ""

    mini_map = (f'<section class="meeting-map-sec"><h2>On the map</h2>'
                f'<div id="meeting-map" class="map-canvas mini" data-src="/api/map.geojson?meeting={m["event_id"]}"></div>'
                f'<p class="map-foot muted">Locations pinned from the agenda wording — some approximate.</p>'
                f'</section>') if has_geo else ""

    cd = _countdown_span(m["meeting_date"], m["status"])
    cd_banner = (f'<div class="cd-banner">&#9203; {cd}'
                 f'<span class="cd-msg">— there\'s still time to make your voice heard before this meeting.</span>'
                 f'</div>') if cd else ''

    docket = "".join(_docket_item(it, m["status"], votes_by_item.get(it["event_item_id"], [])) for it in items)
    docket_sec = (f'<section class="docket"><h2>Agenda <span class="count">{len(items)} items</span></h2>'
                  f'<p class="docket-hint">Dotted terms have plain-English explanations — hover or tap them.</p>'
                  f'<ol class="docket-list">{docket}</ol></section>') if items else \
                 '<section class="docket"><p class="muted">No agenda items posted yet.</p></section>'

    return (
        f'<article class="record">'
        f'{_dateline(m["body_name"], m["meeting_date"])}'
        f'<h1>{title_h}</h1>'
        f'<p class="when">{when}{loc}</p>'
        f'{cd_banner}{gist}{source_row}{mini_map}{docket_sec}'
        f'</article>'
    )


def _where_html(w: dict) -> str:
    """A compact 'where' line (cross-streets · acreage · zone) pulled from the raw title, so the
    location survives into the quick view instead of hiding in the official wording."""
    if not (w["location"] or w["acres"] or w["zone"]):
        return ""
    bits = []
    if w["location"]:
        if w.get("map_query"):
            url = "https://www.google.com/maps/search/?api=1&query=" + quote(w["map_query"])
            bits.append(f'<a class="w-loc maplink" href="{_esc(url)}" target="_blank" '
                        f'rel="noopener">{_esc(w["location"])} <span class="ext-arr">↗</span></a>')
        else:
            bits.append(f'<span class="w-loc">{_esc(w["location"])}</span>')
    if w["acres"]:
        bits.append(f'<span class="w-meta">{_esc(w["acres"])} acres</span>')
    if w["zone"]:
        bits.append(f'<span class="w-meta">{_esc(w["zone"])} Zone</span>')
    inner = ' <span class="w-sep">·</span> '.join(bits)
    return f'<p class="item-where"><span class="pin" aria-hidden="true">📍</span> {inner}</p>'


def _docket_item(it: dict, status: str, votes: list) -> str:
    seq = it.get("sequence")
    num = f'<span class="item-num">{int(seq)}</span>' if seq is not None else '<span class="item-num">—</span>'
    text = it.get("plain_summary") or it.get("title") or ""
    raw = ""
    if it.get("plain_summary") and it.get("title") and it["plain_summary"] != it["title"]:
        raw = f'<details class="raw"><summary>Official wording</summary><p>{_esc(it["title"])}</p></details>'
    topiclist = _topic_pills(json.loads(it.get("topics") or "[]"))
    movers = ""
    if it.get("mover"):
        sec = f' · seconded by {_esc(_person(it["seconder"]))}' if it.get("seconder") else ""
        movers = f'<p class="movers">Moved by {_esc(_person(it["mover"]))}{sec}</p>'
    return (
        f'<li class="docket-item">'
        f'<div class="item-head">{num}{_stamp(it.get("action_name"), it.get("passed_flag"), status)}{topiclist}</div>'
        f'<p class="item-text">{glossary.annotate(text)}</p>'
        f'{_where_html(location.extract(it.get("title") or ""))}'
        f'{raw}{movers}{_votes_html(votes)}'
        f'</li>'
    )


def _vote_label(vote: str) -> str:
    """'Voting Aye' -> 'Aye' (Legistar prefixes vote values with 'Voting ')."""
    v = (vote or "").strip()
    return v[7:] if v.lower().startswith("voting ") else v


def _votes_html(votes: list) -> str:
    if not votes:
        return ""
    # Legistar values are e.g. "Voting Aye" / "Voting Nay" / "Absent" / "Abstain" / "Recused" —
    # match by substring, not exact, so "Voting Aye" counts as an aye (not "other").
    def val(v):
        return (v["vote"] or "").strip().lower()
    ayes = [v for v in votes if "aye" in val(v) or "yea" in val(v) or val(v) in ("yes", "approve", "for")]
    nays = [v for v in votes if "nay" in val(v) or val(v) in ("no", "against")]
    other = [v for v in votes if v not in ayes and v not in nays]
    tally = f'<span class="tally">{len(ayes)}–{len(nays)}'
    tally += f' · {len(other)} other' if other else ""
    tally += "</span>"
    roll = " · ".join(f'{_esc(_person(v["person"]))} <em>({_esc(_vote_label(v["vote"]))})</em>' for v in votes)
    return f'<div class="votes"><span class="votes-label">Vote</span> {tally}<p class="roll">{roll}</p></div>'


# ---- landing + body + topic pages -----------------------------------------
def landing(upcoming: list[dict], recent: list[dict], gist_by_event: dict[int, str]) -> str:
    def cards(rows):
        return "".join(dispatch_card(m, gist_by_event.get(m["event_id"])) for m in rows) or '<p class="muted">Nothing here yet — check back soon.</p>'
    return (
        '<section class="lede-block">'
        '<p class="kicker">Clark County, Nevada</p>'
        '<h1>Know what your local government is doing.</h1>'
        '<p class="lede">Plain-English briefs on what the Board of Commissioners, Planning Commission, '
        'and Zoning Commission are taking up — and what they decided, including how each member voted. '
        'Free, no account. Every summary links back to the official record.</p>'
        '</section>'
        f'<section class="feed"><h2 class="section-h">Upcoming meetings</h2><div class="dispatch-list">{cards(upcoming)}</div></section>'
        f'<section class="feed"><h2 class="section-h">Recently decided</h2><div class="dispatch-list">{cards(recent)}</div></section>'
    )


def body_page(slug: str, name: str, rows: list[dict], gist_by_event: dict[int, str]) -> str:
    cards = "".join(dispatch_card(m, gist_by_event.get(m["event_id"])) for m in rows) or '<p class="muted">No meetings on record yet.</p>'
    return (
        f'<section class="lede-block"><p class="kicker">Clark County</p><h1>{_esc(name)}</h1>'
        f'<p class="lede">Every {_esc(name)} meeting we have on record, newest first — upcoming agendas and past decisions.</p></section>'
        f'<section class="feed"><div class="dispatch-list">{cards}</div></section>'
    )


def topic_page(slug: str, label_txt: str, rows: list[dict]) -> str:
    cards = "".join(dispatch_card(m, None) for m in rows) or '<p class="muted">Nothing tagged with this topic yet.</p>'
    return (
        f'<section class="lede-block"><p class="kicker">Topic</p><h1>{_esc(label_txt)}</h1>'
        f'<p class="lede">Recent Clark County meetings with agenda items about {_esc(label_txt.lower())}.</p></section>'
        f'<section class="feed"><div class="dispatch-list">{cards}</div></section>'
    )


def about_page() -> str:
    bodies = "".join(f'<li><a href="/body/{m["slug"]}">{_esc(m["name"])}</a></li>' for m in BODIES.values())
    return (
        '<section class="prose">'
        '<p class="kicker">About</p><h1>What this is</h1>'
        '<p>Local government decides an enormous amount about daily life — what gets built next door, '
        'how tax money is spent, how the county is policed — but the records are dense and hard to follow. '
        'Civic Lens reads Clark County’s public meeting agendas and turns them into plain-English briefs, '
        'so any resident can see what’s coming up and what was decided.</p>'
        '<h2>How it works</h2>'
        '<p>Meeting data comes from Clark County’s public Legistar record. An AI assistant writes the '
        'plain-English summaries. <strong>AI can be wrong</strong> — every brief links to the official '
        'agenda and record so you can verify anything before you rely on it. This is an independent '
        'civic project and is not affiliated with or endorsed by Clark County.</p>'
        f'<h2>What we cover</h2><ul class="body-list">{bodies}</ul>'
        '<p class="muted">More bodies and cities (CCSD School Board, City of Las Vegas) are planned.</p>'
        '</section>'
    )


def not_found(message: str) -> str:
    return (f'<section class="prose"><p class="kicker">Not found</p><h1>{_esc(message)}</h1>'
            '<p><a href="/">← Back to the latest meetings</a></p></section>')
