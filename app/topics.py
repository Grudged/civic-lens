"""Deterministic topic tagging for agenda items.

Keyword-based on purpose: civic categories are stable and a fixed vocabulary is far more reliable
(and free) than asking a 26B model to tag consistently. Patterns are word-boundary regex with
explicit variants — bare substrings over-match (e.g. "park" hit "Parkinson", "road" hit "broad",
"fund" hit "foundation"). Distinctive long stems (develop, construct, appropriat) stay as prefixes.
Each slug drives /topic/{slug}; an item can carry several tags, emitted in TOPICS order (stable).
"""
from __future__ import annotations

import re

# slug -> (label, [regex fragments])
TOPICS: dict[str, tuple[str, list[str]]] = {
    "land-use":      ("Zoning & Land Use", [r"\bzon(e|ed|es|ing)\b", r"\brezon", r"\bland[- ]use\b",
                                            r"\bparcel", r"\bsubdivi", r"\bplat(s|ting)?\b", r"\bsetback",
                                            r"\bvariance", r"\buse permit", r"\bnonconform", r"\bmaster plan",
                                            r"\bcomprehensive plan"]),
    "development":   ("Development", [r"\bdevelop", r"\bconstruct", r"\bsite plan", r"\btentative map",
                                      r"\bfinal map\b", r"\bdesign review"]),
    "housing":       ("Housing", [r"\bhousing\b", r"\baffordable", r"\bapartment", r"\bresidential",
                                  r"\bhomeless", r"\brental(s)?\b", r"\bdwelling", r"\bmulti[- ]?family",
                                  r"\bsingle[- ]family"]),
    "budget":        ("Budget & Finance", [r"\bbudget", r"\bappropriat", r"\bfund(s|ing|ed)?\b", r"\bfiscal",
                                           r"\baudit", r"\btax(es|ed|ation|payer|payers)?\b", r"\brevenue",
                                           r"\bexpenditure", r"\bbond(s)?\b", r"\bgrant(s)?\b", r"\binterlocal",
                                           r"\bpurchase", r"\bprocure", r"\bcontract(s)?\b", r"\bagreement"]),
    "public-safety": ("Public Safety", [r"\bpolice\b", r"\bmetro\b", r"\bfire", r"\bsheriff", r"\bfatality",
                                        r"\bemergenc", r"\bambulance", r"\bcrim(e|inal)", r"\bmarshal",
                                        r"\bdetention"]),
    "transportation":("Transportation", [r"\broad(s|way|ways)?\b", r"\bstreet", r"\btraffic", r"\btransit\b",
                                         r"\bRTC\b", r"\bhighway", r"\bpedestrian", r"\bbicycle", r"\bbike lane",
                                         r"\bairport", r"\bright[- ]of[- ]way", r"\bintersection", r"\bpaving",
                                         r"\bsidewalk"]),
    "parks":         ("Parks & Recreation", [r"\bpark(s|way|land|ing)?\b", r"\brecreation", r"\btrail(s|head|heads)?\b",
                                             r"\bopen space", r"\bcommunity center", r"\bball ?field", r"\baquatic"]),
    "environment":   ("Water & Environment", [r"\bwater", r"\bsewer", r"\bflood", r"\bdrainage", r"\bair quality",
                                              r"\benvironment", r"\bsustainab", r"\bsolar\b", r"\benergy\b",
                                              r"\bconservation"]),
    "business":      ("Business & Licensing", [r"\blicens", r"\bliquor", r"\bcannabis", r"\bmarijuana", r"\bgaming\b",
                                               r"\bbusiness", r"\bfranchise", r"\bvendor", r"\bbrothel", r"\btavern"]),
    "health":        ("Health & Social Services", [r"\bhealth", r"\bsocial service", r"\bsenior(s)?\b", r"\bchild care",
                                                    r"\bchildren", r"\bwelfare", r"\bmedic", r"\bmental",
                                                    r"\bclinic", r"\bnutrition"]),
    "governance":    ("Governance & Elections", [r"\belection", r"\bappointment", r"\bappoint\b", r"\bbylaw",
                                                 r"\bcharter", r"\bredistrict", r"\bpublic hearing",
                                                 r"\bboard appointment"]),
}

_COMPILED = {slug: (label, re.compile("|".join(frags), re.I)) for slug, (label, frags) in TOPICS.items()}


def tag(text: str) -> list[str]:
    """Return matching topic slugs for an agenda-item title (stable order)."""
    t = text or ""
    return [slug for slug, (_, rx) in _COMPILED.items() if rx.search(t)]


def label(slug: str) -> str:
    entry = TOPICS.get(slug)
    return entry[0] if entry else slug
