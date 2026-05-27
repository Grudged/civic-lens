"""Plain-English glossary for civic jargon — powers the hover/tap "what this means" tooltips.

Deterministic on purpose: definitions of legal/land-use terms must be stable and correct, not
AI-improvised. `annotate()` escapes the text, then wraps the first occurrence of each known term
in a tooltip span. Definitions are curated constants (trusted); the term text stays escaped.
"""
from __future__ import annotations

import html
import re

# (regex, plain definition). Longer / more specific phrases first so they win over bare words.
TERMS: list[tuple[str, str]] = [
    (r"conditional use permits?|use permits?",
     "Special permission to use land in a way the zoning doesn't automatically allow (e.g. putting senior housing on a particular lot)."),
    (r"waivers? of development standards|waivers?",
     "Permission to relax or skip a normal building rule — like allowing a taller building or a narrower driveway than the code requires."),
    (r"variances?",
     "A one-off exception to a zoning rule (such as height or how far a building must sit from the property line) for a specific property."),
    (r"design review",
     "The county reviewing how a project will look and lay out before it's approved."),
    (r"reclassif\w*|rezon\w*|zone change|zoning map",
     "Changing the official rules for what can be built on a piece of land — e.g. switching it from homes to shops."),
    (r"rights?-of-way|right[ -]of[ -]way",
     "Public land set aside for roads, sidewalks, or utilities."),
    (r"vacate and abandon|vacate|abandon",
     "The county giving up a strip of public road or land it no longer needs (often so it can be used by an adjacent project)."),
    (r"tentative maps?|final maps?",
     "A proposed (tentative) or approved (final) plan for splitting a property into separate lots."),
    (r"setbacks?",
     "How far a building must sit back from property lines, streets, or neighbors."),
    (r"easements?",
     "A right to use part of someone's land for a specific purpose, like utility lines or access."),
    (r"general plan|master plan",
     "The county's long-term blueprint for how an area should grow."),
    (r"mixed[- ]use",
     "A development that combines homes with shops or offices in one place."),
    (r"nonconforming",
     "An existing use or building that no longer fits the current zoning rules."),
    (r"held in abeyance|abeyance",
     "Put on hold and pushed to a later meeting."),
    (r"public hearing",
     "A part of the meeting where residents can speak before the board decides."),
    (r"ordinances?",
     "A local law passed by the county."),
    (r"entitlements?",
     "The government approvals a project needs before it can be built."),
    (r"parcels?",
     "A defined piece of land."),
]
_COMPILED = [(re.compile(rf"\b(?:{pat})\b", re.I), defn) for pat, defn in TERMS]


def annotate(text: str) -> str:
    """Escape `text` and wrap the first occurrence of each known term in a tooltip span.
    Returns trusted HTML. Matches are found on the original escaped string and spliced in
    left-to-right with overlaps dropped, so terms are never wrapped inside another term's tooltip."""
    safe = html.escape(text or "")
    spans: list[tuple[int, int, str]] = []
    for rx, defn in _COMPILED:
        m = rx.search(safe)
        if m:
            spans.append((m.start(), m.end(), defn))
    if not spans:
        return safe
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))  # leftmost, then longest

    out, cursor, last_end = [], 0, -1
    for start, end, defn in spans:
        if start < last_end:
            continue  # overlaps a term we already placed
        out.append(safe[cursor:start])
        term = safe[start:end]
        out.append(
            f'<span class="term" tabindex="0">{term}'
            f'<span class="tip" role="tooltip">{html.escape(defn)}</span></span>'
        )
        cursor, last_end = end, end
    out.append(safe[cursor:])
    return "".join(out)
