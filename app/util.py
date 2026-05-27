from datetime import datetime


def fmt_date(iso: str, with_time: bool = True) -> str:
    """'2026-06-02T09:00' -> 'Tuesday, June 2, 2026 · 9:00 AM'. Tolerant of date-only + junk."""
    if not iso:
        return ""
    try:
        if "T" in iso:
            dt = datetime.fromisoformat(iso)
            base = dt.strftime("%A, %B ") + str(dt.day) + dt.strftime(", %Y")
            return f"{base} · {dt.strftime('%-I:%M %p')}" if with_time else base
        d = datetime.fromisoformat(iso[:10])
        return d.strftime("%A, %B ") + str(d.day) + d.strftime(", %Y")
    except ValueError:
        return iso


def fmt_date_short(iso: str) -> str:
    """'2026-06-02T09:00' -> 'Jun 2, 2026'."""
    try:
        d = datetime.fromisoformat(iso[:10])
        return d.strftime("%b ") + str(d.day) + d.strftime(", %Y")
    except (ValueError, TypeError):
        return (iso or "")[:10]
