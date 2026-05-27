"""Gemma (MLX) summarization — plain-English meeting overview + per-item rewrites.

Everything here is BEST-EFFORT: any failure returns None / falls back to raw titles, so a
summary outage never breaks a page. Lesson carried from the FirstEmbark coach: the 26B model
will NOT emit clean JSON (it rambles / loops), so prompts are plain-text and parsing is
line-based — never ask it for structured data.
"""
from __future__ import annotations

import logging

import httpx

from .config import MLX_MODEL, MLX_URL

log = logging.getLogger("civic.summarize")
TIMEOUT = 120.0


def _chat(system: str, user: str, max_tokens: int = 700, temperature: float = 0.3) -> str | None:
    payload = {
        "model": MLX_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    try:
        with httpx.Client(timeout=TIMEOUT) as c:
            r = c.post(f"{MLX_URL}/v1/chat/completions", json=payload)
            r.raise_for_status()
            return (r.json()["choices"][0]["message"]["content"] or "").strip()
    except (httpx.HTTPError, KeyError, ValueError, IndexError) as e:
        log.warning("MLX chat failed: %s", e)
        return None


def overview(body_name: str, date_label: str, item_titles: list[str], past: bool) -> str | None:
    """2–3 sentence plain-English overview of what the meeting covers/covered."""
    if not item_titles:
        return None
    tense = ("This meeting already happened — summarize what the board took up and decided."
             if past else "This meeting is upcoming — summarize what the board will take up.")
    items = "\n".join(f"- {t}" for t in item_titles[:40])
    system = ("You explain local government plainly for ordinary residents of Las Vegas. "
              "Write in plain English at an 8th-grade reading level. Be neutral and factual — "
              "never invent details that aren't in the agenda. No preamble, no bullet points.")
    user = (f"{tense}\nBody: {body_name}\nDate: {date_label}\n\nAgenda items:\n{items}\n\n"
            "Write 2–3 sentences telling a resident what this meeting is mainly about and why it "
            "might matter to them. Do not list every item; give the gist.")
    out = _chat(system, user, max_tokens=240)
    return out or None


def rewrite_items(item_titles: list[str]) -> list[str]:
    """Rewrite each agenda-item title as one plain-English sentence, preserving order and count.
    Returns a list aligned to the input; falls back to the original title for any item that
    can't be parsed back (so length always matches)."""
    if not item_titles:
        return []
    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(item_titles))
    system = ("You translate dense local-government agenda items into plain English for residents. "
              "Keep each to ONE clear sentence. Be neutral and faithful — do not add facts. "
              "Output exactly one line per item, prefixed with its number and a period, in the "
              "same order. No headers, no blank lines, no extra commentary.")
    user = (f"Rewrite each of these {len(item_titles)} agenda items as one plain sentence:\n\n"
            f"{numbered}")
    out = _chat(system, user, max_tokens=60 + 45 * len(item_titles))
    parsed = _parse_numbered(out, len(item_titles)) if out else {}
    return [parsed.get(i, item_titles[i]) for i in range(len(item_titles))]


def _parse_numbered(text: str, n: int) -> dict[int, str]:
    """Parse 'N. sentence' lines into {index: sentence} (0-based). Tolerant of extra lines."""
    import re
    out: dict[int, str] = {}
    for line in text.splitlines():
        m = re.match(r"\s*(\d+)[.)]\s*(.+)", line)
        if not m:
            continue
        idx = int(m.group(1)) - 1
        if 0 <= idx < n:
            out[idx] = m.group(2).strip()
    return out
