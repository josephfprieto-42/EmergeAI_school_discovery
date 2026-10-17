"""Map official program titles to recommendation themes.

Themes come from the program name published by the district catalog.
They are never inferred from the school name.
"""
from __future__ import annotations

import re

# Longer phrases first so "international baccalaureate" wins over a stray token.
_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("stem", (
        "stem", "steam", "science", "engineering", "robotics", "information technology",
        "biomedical", "biomed", "computer", "coding", "marine science", "mathematics",
        "aerospace", "health science", "cyber", "engineering & robotics",
    )),
    ("arts", (
        "performing arts", "visual arts", "fine arts", "music", "dance", "theater",
        "theatre", "band", "chorus", "drama", "film", "design", "arts", "art",
    )),
    ("language", (
        "dual language", "bilingual", "world language", "spanish", "french", "chinese",
        "haitian", "creole", "international studies", "language",
    )),
    ("gifted", (
        "international baccalaureate", "cambridge", "ap capstone", "gifted",
        "advanced placement", "honors",
    )),
    ("special_needs", (
        "varying exceptionalities", "exceptional student", "special education",
        "autism", "exceptional",
    )),
]


def _has(phrase: str, title: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", title) is not None


def themes_for_program(program_name: str, program_type: str | None = None) -> list[str]:
    title = (program_name or "").lower()
    found: list[str] = []
    for theme, phrases in _RULES:
        if any(_has(p, title) for p in phrases):
            found.append(theme)
    if program_type == "magnet" and "magnet" not in found:
        found.append("magnet")
    if program_type == "choice" and "choice" not in found:
        found.append("choice")
    # "IB" is its own token. The phrase rule above covers the spelled-out name.
    if _has("ib", title) and "gifted" not in found:
        found.append("gifted")
    return found
