"""Deterministic filtering and scoring of schools against structured preferences.

Every component of the score is derived from stored data; the breakdown is returned so
the UI and the LLM can cite exactly why a school ranked where it did.
"""
from __future__ import annotations

import math
import sqlite3
from typing import Any, Optional

from .. import db
from ..schemas import Preferences

FL_GRADE_POINTS = {"A": 1.0, "B": 0.75, "C": 0.5, "D": 0.25, "F": 0.0, "I": None}

# Keyword -> program tags. Matching is done against the school name (the only program
# signal present in the public sources) plus NCES magnet flag and subtype.
PRIORITY_KEYWORDS: dict[str, list[str]] = {
    "stem": ["stem", "science", "technology", "engineering", "math", "steam", "robotics", "tech"],
    "arts": ["arts", "art ", "performing", "music", "design", "visual", "theater", "dance"],
    "language": ["bilingual", "dual language", "international", "french", "spanish", "chinese", "ib ", "baccalaureate", "world"],
    "magnet": ["magnet", "academy", "preparatory", "prep", "international", "center for"],
    "religious": ["catholic", "christian", "baptist", "jewish", "hebrew", "yeshiva", "lutheran", "episcopal", "methodist", "presbyterian", "adventist", "islamic", "academy of the holy", "st.", "saint", "our lady", "church", "temple", "chabad", "torah"],
    "montessori": ["montessori"],
    "special_needs": ["exceptional", "ese", "special", "therapeutic", "autism", "learning center", "achievement", "cooper", "educational center"],
    "gifted": ["gifted", "honors", "advanced", "accelerated", "international baccalaureate", "ib "],
    "early_childhood": ["early", "learning", "child", "children", "kids", "little", "preschool", "pre-k", "prek", "head start", "montessori", "academy", "daycare", "day care", "nursery"],
}

DEFAULT_WEIGHTS = {
    "distance": 0.30,
    "academics": 0.30,
    "size": 0.10,
    "keywords": 0.20,
    "fit": 0.10,
}


def weights_for(prefs: Preferences) -> dict[str, float]:
    w = dict(DEFAULT_WEIGHTS)
    p = set(prefs.priorities)
    if "academics" in p:
        w["academics"] += 0.2
    if "distance" in p:
        w["distance"] += 0.2
    if "small_school" in p or "large_school" in p:
        w["size"] += 0.15
    if p & {"stem", "arts", "language", "magnet", "religious", "montessori", "special_needs", "gifted"} or prefs.keywords:
        w["keywords"] += 0.2
    if prefs.categories and "early_childhood" in prefs.categories:
        # Early childhood providers have no academic data; emphasize distance and fit.
        w["academics"] *= 0.2
        w["distance"] += 0.2
    total = sum(w.values())
    return {k: v / total for k, v in w.items()}


def grade_from_age(age: float) -> int:
    if age < 3:
        return -2
    if age < 5:
        return -1
    return max(0, min(12, int(round(age - 5))))


def _keyword_hits(school: dict[str, Any], prefs: Preferences) -> list[str]:
    hay = f"{school.get('name') or ''} {school.get('subtype') or ''}".lower()
    hits: list[str] = []
    for kw in prefs.keywords:
        k = kw.lower().strip()
        if k and k in hay:
            hits.append(kw)
    for pr in prefs.priorities:
        for tok in PRIORITY_KEYWORDS.get(pr, []):
            if tok in hay:
                hits.append(f"{pr}:{tok.strip()}")
                break
    if "magnet" in prefs.priorities and school.get("magnet"):
        hits.append("magnet:NCES magnet flag")
    if "religious" in prefs.priorities and school.get("category") == "private":
        pass
    if "early_childhood" in prefs.priorities and school.get("category") == "early_childhood":
        hits.append("early_childhood:provider")
    return hits


def score_school(school: dict[str, Any], prefs: Preferences, w: dict[str, float]) -> dict[str, Any]:
    parts: dict[str, float] = {}
    reasons: list[str] = []

    # Distance: 1.0 at 0 miles, decays to ~0 at the search radius (or 10 mi default).
    radius = prefs.radius_miles or 10.0
    dist = school.get("distance_miles")
    if dist is not None:
        parts["distance"] = max(0.0, 1.0 - (dist / radius) ** 1.2)
        reasons.append(f"{dist:.1f} mi away")
    else:
        parts["distance"] = 0.5

    # Academics: FLDOE grade + percent of points + achievement (only when available).
    fl = school.get("fl_grade")
    gp = FL_GRADE_POINTS.get(fl or "")
    if gp is not None:
        pct = school.get("pct_points")
        ach = [v for v in (school.get("ela_ach"), school.get("math_ach")) if v is not None]
        acad = 0.6 * gp
        acad += 0.25 * (pct / 100.0) if pct is not None else 0.25 * gp
        acad += 0.15 * (sum(ach) / len(ach) / 100.0) if ach else 0.15 * gp
        parts["academics"] = acad
        reasons.append(f"FLDOE grade {fl}")
        prev = school.get("fl_grade_prev1")
        if prev and fl and prev != fl:
            reasons.append(f"was {prev} last year")
    else:
        parts["academics"] = 0.45 if school.get("category") in ("private", "early_childhood") else 0.35
        if school.get("category") in ("public", "charter"):
            reasons.append("no state grade reported")

    # Size preference.
    enr = school.get("enrollment") or school.get("nces_enrollment") or school.get("capacity")
    if enr:
        if "small_school" in prefs.priorities:
            parts["size"] = 1.0 / (1.0 + math.exp((enr - 500) / 150))
        elif "large_school" in prefs.priorities:
            parts["size"] = 1.0 - 1.0 / (1.0 + math.exp((enr - 900) / 300))
        else:
            parts["size"] = 0.6
        reasons.append(f"{enr:,} students" if school.get("enrollment") else f"capacity {enr:,}")
    else:
        parts["size"] = 0.5

    # Keywords / programs.
    hits = _keyword_hits(school, prefs)
    want = len(prefs.keywords) + len([p for p in prefs.priorities if p in PRIORITY_KEYWORDS])
    if want:
        parts["keywords"] = min(1.0, len(hits) / max(1, min(want, 2)))
        if hits:
            reasons.append("matches " + ", ".join(h.split(":")[-1] for h in hits[:3]))
    else:
        parts["keywords"] = 0.5

    # Fit: student/teacher ratio, min grade, category preference.
    fit = 0.5
    ratio = school.get("student_teacher_ratio")
    if ratio:
        fit += 0.25 * max(-1.0, min(1.0, (18 - ratio) / 8))
        reasons.append(f"{ratio:.0f}:1 student-teacher ratio")
    if prefs.categories and school.get("category") in prefs.categories:
        fit += 0.25
    parts["fit"] = max(0.0, min(1.0, fit))

    total = sum(w[k] * parts.get(k, 0.5) for k in w)
    return {"score": round(total, 4), "components": {k: round(v, 3) for k, v in parts.items()}, "reasons": reasons, "keyword_hits": hits}


def retrieve_and_rank(
    con: sqlite3.Connection,
    prefs: Preferences,
    origin: Optional[tuple[float, float]],
    limit: int = 6,
) -> tuple[list[dict[str, Any]], int]:
    grade = prefs.child_grade
    if grade is None and prefs.child_grades:
        grade = prefs.child_grades[0]
    categories = list(prefs.categories) if prefs.categories else None
    if categories is None and grade is not None and grade < 0:
        categories = ["early_childhood", "public", "private", "charter"]
    fl_grades = None
    if prefs.min_fl_grade:
        fl_grades = {"A": ["A"], "B": ["A", "B"], "C": ["A", "B", "C"]}[prefs.min_fl_grade]

    rows = db.fetch_schools(con, categories=categories, grade=grade, fl_grades=fl_grades)
    items = [db.row_to_school(r, origin) for r in rows]

    radius = prefs.radius_miles or (8.0 if origin else None)
    if origin and radius:
        within = [i for i in items if i["distance_miles"] <= radius]
        # Widen progressively if the radius was too tight.
        r = radius
        while len(within) < 5 and r < 25:
            r *= 1.5
            within = [i for i in items if i["distance_miles"] <= r]
        items = within

    # Exclude administrative / non-enrolling entries when the parent is looking for a school.
    if grade is not None and grade >= 0:
        items = [i for i in items if i.get("subtype") not in ("primary_learning_center",) or i.get("enrollment")]

    w = weights_for(prefs)
    for i in items:
        i["ranking"] = score_school(i, prefs, w)
    items.sort(key=lambda i: i["ranking"]["score"], reverse=True)
    return items[:limit], len(items)
