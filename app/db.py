import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
    event_id     INTEGER PRIMARY KEY,    -- Legistar EventId
    body_id      INTEGER NOT NULL,
    body_name    TEXT,
    body_slug    TEXT,
    meeting_date TEXT,                    -- ISO datetime (EventDate + EventTime merged)
    status       TEXT,                    -- 'upcoming' | 'past'
    location     TEXT,
    agenda_url   TEXT,                    -- official agenda PDF
    minutes_url  TEXT,                    -- official minutes PDF (when posted)
    legistar_url TEXT,                    -- official InSite meeting page
    fetched_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_meetings_date ON meetings(meeting_date);
CREATE INDEX IF NOT EXISTS idx_meetings_body ON meetings(body_slug);

CREATE TABLE IF NOT EXISTS agenda_items (
    event_item_id INTEGER PRIMARY KEY,    -- Legistar EventItemId
    event_id      INTEGER NOT NULL,
    matter_id     INTEGER,
    sequence      INTEGER,
    title         TEXT,                    -- raw EventItemTitle
    action_name   TEXT,                    -- e.g. "approved", "denied"
    passed_flag   INTEGER,                 -- 1 passed / 0 failed / NULL n/a
    mover         TEXT,
    seconder      TEXT,
    matter_type   TEXT,
    plain_summary TEXT,                    -- Gemma: one plain-English sentence
    topics        TEXT                     -- JSON list of topic tags
);
CREATE INDEX IF NOT EXISTS idx_items_event ON agenda_items(event_id);

CREATE TABLE IF NOT EXISTS item_votes (
    event_item_id INTEGER NOT NULL,
    person        TEXT NOT NULL,
    vote          TEXT,                    -- Aye / Nay / Abstain / Absent / Recused
    PRIMARY KEY (event_item_id, person)
);

CREATE TABLE IF NOT EXISTS meeting_summaries (
    event_id     INTEGER PRIMARY KEY,
    overview     TEXT,                     -- Gemma plain-English meeting overview
    topics       TEXT,                     -- JSON aggregate topic tags
    model        TEXT,
    generated_at TEXT
);
"""


@contextmanager
def db():
    """Connection that commits on clean exit and always closes (no FD leak in long uptime)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    parent = Path(DB_PATH).parent
    if str(parent):
        parent.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.executescript(SCHEMA)
