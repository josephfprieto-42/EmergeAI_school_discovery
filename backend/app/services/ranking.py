"""Deterministic filtering and scoring of schools against structured preferences.

Every component of the score is derived from stored data; the breakdown is returned so
the UI and the LLM can cite exactly why a school ranked where it did.
"""
from __future__ import annotations

import math
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Optional

from .. import db
from ..schemas import Household, Preferences

FL_GRADE_POINTS = {"A": 1.0, "B": 0.75, "C": 0.5, "D": 0.25, "F": 0.0, "I": None}

# Household activity interests that map onto a program priority. Sports are scored
# from the FHSAA directory instead of a name search.
ACTIVITY_TO_PRIORITY = {"arts": "arts", "stem": "stem", "language": "language"}
# Activity wording -> the sport name published by FHSAA. Longer phrases first.
_SPORT_TERMS = (
    ("flag football", "flag football"),
    ("beach volleyball", "beach volleyball"),
    ("water polo", "water polo"),
    ("cross country", "cross country"),
    ("track", "track and field"),
    ("cheer", "cheerleading"),
    ("soccer", "soccer"),
    ("swim", "swimming"),
    ("basketball", "basketball"),
    ("baseball", "baseball"),
    ("softball", "softball"),
    ("football", "football"),
    ("volleyball", "volleyball"),
    ("tennis", "tennis"),
    ("golf", "golf"),
    ("wrestling", "wrestling"),
    ("lacrosse", "lacrosse"),
    ("bowling", "bowling"),
    ("weightlifting", "weightlifting"),
)
ON_THE_WAY_MILES = 0.5


@dataclass
class ActivityPoint:
    label: str
    lat: float
    lon: float


@dataclass
class RouteContext:
    """Where the week actually happens: home, work, and the places the children already go."""

    origin: Optional[tuple[float, float]] = None
    work: Optional[tuple[float, float]] = None
    activities: list[ActivityPoint] = field(default_factory=list)
    mode: str = "home"  # home | work | route
    needs_care: bool = False
    sports_interest: bool = False
    sport_terms: list[str] = field(default_factory=list)

    @property
    def home_work_miles(self) -> Optional[float]:
        if self.origin and self.work:
            return db.haversine_miles(self.origin[0], self.origin[1], self.work[0], self.work[1])
        return None


def build_context(
    prefs: Preferences,
    origin: Optional[tuple[float, float]],
    household: Optional[Household],
    work: Optional[tuple[float, float]],
    activity_points: Optional[list[ActivityPoint]],
) -> RouteContext:
    mode = prefs.prefer_near or ("route" if work and origin else "home")
    if mode == "route" and not (work and origin):
        mode = "work" if work else "home"
    if mode == "work" and not work:
        mode = "home"
    return RouteContext(
        origin=origin,
        work=work,
        activities=list(activity_points or []),
        mode=mode,
        needs_care=bool(household and household.needs_after_school_care),
        sports_interest=bool(household and "sports" in household.activity_interests),
        sport_terms=_sport_terms(household),
    )


def _sport_terms(household: Optional[Household]) -> list[str]:
    """FHSAA sport names mentioned in the family's activities."""
    if household is None:
        return []
    found: list[str] = []
    for activity in household.activities:
        label = activity.label.lower()
        for needle, sport in _SPORT_TERMS:
            if needle in label and sport not in found:
                # "football" also sits inside "flag football", which is its own sport.
                if needle == "football" and "flag football" in label:
                    continue
                found.append(sport)
                break
    return found


def _offers_sport(school: dict[str, Any], sport: str) -> bool:
    for row in school.get("sports") or []:
        name = (row.get("sport") or "").lower()
        if sport == "football":
            if name == "football (11 man)" or name == "football":
                return True
            continue
        if sport in name:
            return True
    return False


def with_household(prefs: Preferences, household: Optional[Household]) -> Preferences:
    """Fold activity interests that the catalog can see into the ranking priorities."""
    if household is None:
        return prefs
    extra = [ACTIVITY_TO_PRIORITY[i] for i in household.activity_interests if i in ACTIVITY_TO_PRIORITY]
    extra = [p for p in extra if p not in prefs.priorities]
    if not extra:
        return prefs
    return prefs.model_copy(update={"priorities": [*prefs.priorities, *extra]})


def _detour(origin: tuple[float, float], point: tuple[float, float], school: dict[str, Any]) -> float:
    direct = db.haversine_miles(origin[0], origin[1], point[0], point[1])
    via = db.haversine_miles(origin[0], origin[1], school["lat"], school["lon"]) + db.haversine_miles(school["lat"], school["lon"], point[0], point[1])
    return max(0.0, via - direct)


def annotate_route(school: dict[str, Any], ctx: RouteContext) -> None:
    """Attach commute and activity distances. Every value comes from coordinates in the catalog."""
    school["work_miles"] = None
    school["detour_miles"] = None
    school["activity_miles"] = None
    school["activity_detours"] = []
    if ctx.work:
        school["work_miles"] = round(db.haversine_miles(ctx.work[0], ctx.work[1], school["lat"], school["lon"]), 2)
        if ctx.origin:
            school["detour_miles"] = round(_detour(ctx.origin, ctx.work, school), 2)
    if ctx.activities:
        dists = []
        for a in ctx.activities:
            d = db.haversine_miles(a.lat, a.lon, school["lat"], school["lon"])
            dists.append(d)
            entry: dict[str, Any] = {"label": a.label, "miles": round(d, 2)}
            if ctx.origin:
                entry["detour_miles"] = round(_detour(ctx.origin, (a.lat, a.lon), school), 2)
            school["activity_detours"].append(entry)
        school["activity_miles"] = round(min(dists), 2)


def anchor_miles(school: dict[str, Any], ctx: RouteContext) -> Optional[float]:
    """The distance the parent cares about under the current mode."""
    if ctx.mode == "work":
        return school.get("work_miles")
    if ctx.mode == "route":
        legs = []
        if school.get("detour_miles") is not None:
            legs.append(school["detour_miles"])
        legs.extend(e["detour_miles"] for e in school.get("activity_detours") or [] if e.get("detour_miles") is not None)
        if legs:
            return round(sum(legs) / len(legs), 2)
        return school.get("distance_miles")
    return school.get("distance_miles")

# Keyword -> program tags. Matching uses the school name, published magnet and
# choice program titles, and CRDC coursework counts.
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


# Faith words that mean the parent still wants private schools in an affordable search.
_FAITH_KEYWORDS = {
    "catholic",
    "christian",
    "jewish",
    "hebrew",
    "lutheran",
    "episcopal",
    "baptist",
    "islamic",
    "muslim",
    "parochial",
    "religious",
    "faith",
}


def keeps_private_schools(prefs: Preferences) -> bool:
    """Private K-12 stays when the parent asked for it, including by faith."""
    if "private" in prefs.categories:
        return True
    if "religious" in prefs.priorities:
        return True
    return any(kw.lower().strip() in _FAITH_KEYWORDS for kw in prefs.keywords)


def _is_tuition_free(school: dict[str, Any]) -> bool:
    if school.get("category") in ("public", "charter"):
        return True
    return school.get("subtype") in ("head_start", "early_head_start")


def cost_label(school: dict[str, Any]) -> str:
    return "tuition-free" if _is_tuition_free(school) else "not reported"


def _drop_unpriced_private(items: list[dict[str, Any]], prefs: Preferences) -> list[dict[str, Any]]:
    """Drop private K-12 when the parent asked for low cost and did not ask for private or religious.

    Licensed child care stays: its price is unpublished, and it is the supply for infants.
    """
    if "affordability" not in prefs.priorities or keeps_private_schools(prefs):
        return items
    return [i for i in items if i.get("category") != "private"]


def weights_for(prefs: Preferences, ctx: Optional[RouteContext] = None) -> dict[str, float]:
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
    if "affordability" in p and not keeps_private_schools(prefs):
        # Separate tuition-free providers from child care whose price is unpublished.
        w["cost"] = 0.35
    grades = requested_grades(prefs)
    if ctx is not None and ctx.origin and "magnet" not in p and (not grades or any(g >= 0 for g in grades)):
        # Neighborhood assignment is a real eligibility fact for boundary schools.
        # Magnet admission does not follow the boundary, so that search does not use this weight.
        w["assigned"] = 0.12
    if ctx is not None and ctx.needs_care:
        # Only on-campus licensed after-school care and full-day child care are known facts.
        w["care"] = 0.25
    if ctx is not None and ctx.mode in ("work", "route"):
        w["distance"] += 0.1
    if ctx is not None and (ctx.sport_terms or ctx.sports_interest):
        w["sports"] = 0.22
    total = sum(w.values())
    return {k: v / total for k, v in w.items()}


def grade_from_age(age: float) -> int:
    if age < 3:
        return -2
    if age < 5:
        return -1
    return max(0, min(12, int(round(age - 5))))


def _token_in(tok: str, hay: str) -> bool:
    """Whole-word match so "art" does not fire on "heart" or "ib" on "exhibit"."""
    t = tok.strip()
    if not t:
        return False
    return re.search(rf"(?<!\w){re.escape(t)}(?!\w)", hay) is not None


def _program_haystacks(school: dict[str, Any]) -> tuple[str, str]:
    """School-name text, then published program titles, kept separate so a hit can name its source."""
    name = f"{school.get('name') or ''} {school.get('subtype') or ''}".lower()
    titles = []
    for program in school.get("programs") or []:
        titles.append(program.get("name") or "")
        titles.extend(program.get("themes") or [])
    academics = school.get("academics") or {}
    if academics.get("ib_enrollment"):
        titles.append("International Baccalaureate")
    if academics.get("gifted_enrollment"):
        titles.append("gifted")
    if any(academics.get(key) for key in ("ap_enrollment", "ap_math", "ap_science", "ap_compsci", "ap_language", "ap_other")):
        titles.append("advanced placement")
    if academics.get("ap_math") or academics.get("ap_science") or academics.get("ap_compsci"):
        titles.append("STEM")
    if academics.get("ap_language"):
        titles.append("language")
    return name, " ".join(titles).lower()


def _keyword_hits(school: dict[str, Any], prefs: Preferences) -> list[str]:
    name_hay, program_hay = _program_haystacks(school)
    hay = f"{name_hay} {program_hay}"
    hits: list[str] = []
    for kw in prefs.keywords:
        k = kw.lower().strip()
        if k and k in hay:
            hits.append(kw)
    for pr in prefs.priorities:
        for tok in PRIORITY_KEYWORDS.get(pr, []):
            if program_hay and _token_in(tok, program_hay):
                hits.append(f"verified:{pr}:{tok.strip()}")
                break
            if _token_in(tok, name_hay):
                hits.append(f"{pr}:{tok.strip()}")
                break
    if "magnet" in prefs.priorities and any(p.get("kind") == "magnet" for p in school.get("programs") or []):
        hits.append("verified:magnet:magnet program")
    elif "magnet" in prefs.priorities and school.get("magnet"):
        hits.append("magnet:nces magnet flag")
    if "gifted" in prefs.priorities and (school.get("academics") or {}).get("gifted_enrollment"):
        if not any(hit.startswith("gifted:") for hit in hits):
            hits.append("gifted:gifted enrollment")
    if school.get("religious") is False:
        hits = [h for h in hits if not h.startswith("religious:")]
    if school.get("religious") is True and "religious" in prefs.priorities:
        hits = [h for h in hits if not h.startswith("religious:")]
        hits.append("verified:religious:school-reported")
    if "early_childhood" in prefs.priorities and school.get("category") == "early_childhood":
        hits.append("early_childhood:provider")
    return hits


def _sports_part(school: dict[str, Any], ctx: RouteContext) -> tuple[float, str]:
    """Score FHSAA sports. Elementary and middle schools are not penalized: that directory is high school only."""
    names = school.get("sports") or []
    high_school = (school.get("grade_high") or -1) >= 9
    if ctx.sport_terms:
        offered = [sport for sport in ctx.sport_terms if _offers_sport(school, sport)]
        if offered:
            return 1.0, "FHSAA: " + ", ".join(offered)
        if names:
            return 0.35, "FHSAA sports do not include " + ", ".join(ctx.sport_terms)
        if high_school:
            return 0.25, "not in the FHSAA sports directory"
        return 0.5, "FHSAA lists high-school sports only"
    if names:
        shown = []
        for row in names:
            label = row.get("sport") or ""
            if label and label not in shown:
                shown.append(label)
        return 1.0, "FHSAA sports include " + ", ".join(shown[:4])
    if high_school:
        return 0.3, "not in the FHSAA sports directory"
    return 0.5, "FHSAA lists high-school sports only"


def _care_part(school: dict[str, Any]) -> tuple[float, str]:
    names = school.get("after_school_care_names") or []
    if school.get("after_school_care") and names:
        return 1.0, f"{names[0]} after-school care on campus"
    if school.get("after_school_care"):
        return 1.0, "licensed after-school care on campus"
    if school.get("subtype") in ("daycare", "head_start", "early_head_start"):
        return 1.0, "licensed child care"
    return 0.3, "after-school care not reported"


def score_school(school: dict[str, Any], prefs: Preferences, w: dict[str, float], ctx: Optional[RouteContext] = None) -> dict[str, Any]:
    parts: dict[str, float] = {}
    reasons: list[str] = []
    ctx = ctx or RouteContext()

    # Distance: 1.0 at 0 miles, decays to ~0 at the search radius (or 10 mi default).
    # Under "work" the anchor is the workplace; under "route" it is the detour the
    # school adds to the home-to-work trip (and to any activity trip).
    radius = prefs.radius_miles or 10.0
    dist = school.get("distance_miles")
    if ctx.mode == "work" and school.get("work_miles") is not None:
        wm = school["work_miles"]
        parts["distance"] = max(0.0, 1.0 - (wm / radius) ** 1.2)
        reasons.append(f"{wm:.1f} mi from work")
        if dist is not None:
            reasons.append(f"{dist:.1f} mi from home")
    elif ctx.mode == "route" and school.get("detour_miles") is not None:
        detour_radius = prefs.radius_miles or 5.0
        anchor = anchor_miles(school, ctx) or 0.0
        parts["distance"] = max(0.0, 1.0 - (anchor / detour_radius) ** 1.2)
        dm = school["detour_miles"]
        reasons.append("on the way to work" if dm <= ON_THE_WAY_MILES else f"adds {dm:.1f} mi to your commute")
        if dist is not None:
            reasons.append(f"{dist:.1f} mi from home")
    elif dist is not None:
        parts["distance"] = max(0.0, 1.0 - (dist / radius) ** 1.2)
        reasons.append(f"{dist:.1f} mi away")
    else:
        parts["distance"] = 0.5
    for entry in school.get("activity_detours") or []:
        if ctx.mode == "route" and entry.get("detour_miles") is not None:
            if entry["detour_miles"] <= ON_THE_WAY_MILES:
                reasons.append(f"on the way to {entry['label']}")
            else:
                reasons.append(f"{entry['detour_miles']:.1f} mi detour to {entry['label']}")
        else:
            reasons.append(f"{entry['miles']:.1f} mi from {entry['label']}")

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
    want = len(prefs.keywords) + len([p for p in prefs.priorities if p in PRIORITY_KEYWORDS or p == "magnet"])
    if want:
        parts["keywords"] = min(1.0, len(hits) / max(1, min(want, 2)))
        verified = [h.split(":")[-1] for h in hits if h.startswith("verified:")]
        named = [h.split(":")[-1] for h in hits if not h.startswith("verified:")]
        if verified:
            reasons.append("verified program " + ", ".join(verified[:3]))
        if named:
            reasons.append("name signal " + ", ".join(named[:2]))
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

    if "affordability" in prefs.priorities:
        free = _is_tuition_free(school)
        scholarships = school.get("scholarship_programs") or []
        if free:
            reasons.append("tuition-free")
        elif scholarships and not school.get("directory_outdated"):
            reasons.append(f"participates in {scholarships[0]}; tuition amount not reported")
        else:
            reasons.append("price not reported")
        if "cost" in w:
            if free:
                parts["cost"] = 1.0
            elif scholarships and not school.get("directory_outdated"):
                parts["cost"] = 0.55
            else:
                parts["cost"] = 0.15

    if "assigned" in w:
        grades = requested_grades(prefs)
        relevant = []
        for zone in school.get("assigned_zones") or []:
            lo, hi = zone.get("grade_low"), zone.get("grade_high")
            if lo is None or hi is None:
                continue
            if not grades or any(lo <= grade <= hi for grade in grades):
                relevant.append(zone)
        if relevant:
            parts["assigned"] = 1.0
            zone = relevant[0]
            reasons.append(f"assigned {zone['level']} school for this address")
        else:
            parts["assigned"] = 0.0

    if ctx.needs_care:
        care, care_reason = _care_part(school)
        reasons.append(care_reason)
        if "care" in w:
            parts["care"] = care
    if "sports" in w:
        sport_score, sport_reason = _sports_part(school, ctx)
        reasons.append(sport_reason)
        parts["sports"] = sport_score

    total = sum(w[k] * parts.get(k, 0.5) for k in w)
    return {"score": round(total, 4), "components": {k: round(v, 3) for k, v in parts.items()}, "reasons": reasons, "keyword_hits": hits}


def requested_grades(prefs: Preferences) -> list[int]:
    grades: list[int] = []
    for child in prefs.children:
        if child.grade not in grades:
            grades.append(child.grade)
    if grades:
        return grades
    for grade in prefs.child_grades:
        if grade not in grades:
            grades.append(grade)
    if prefs.child_grade is not None and prefs.child_grade not in grades:
        grades.insert(0, prefs.child_grade)
    return grades


def _covers(school: dict[str, Any], grade: int) -> bool:
    lo, hi = school.get("grade_low"), school.get("grade_high")
    return lo is not None and hi is not None and lo <= grade <= hi


def _serves(school: dict[str, Any], grades: list[int]) -> list[int]:
    return [grade for grade in grades if _covers(school, grade)]


def _apply_radius(items: list[dict[str, Any]], prefs: Preferences, origin: Optional[tuple[float, float]], ctx: Optional[RouteContext] = None) -> list[dict[str, Any]]:
    ctx = ctx or RouteContext(origin=origin)
    anchored = origin if ctx.mode == "home" else (ctx.work or origin)
    if ctx.mode == "route":
        radius = prefs.radius_miles or 5.0
    else:
        radius = prefs.radius_miles or (8.0 if anchored else None)
    if not (anchored and radius):
        return items

    def miles(i: dict[str, Any]) -> Optional[float]:
        return anchor_miles(i, ctx)

    within = [i for i in items if miles(i) is not None and miles(i) <= radius]
    widened = radius
    while len(within) < 5 and widened < 25:
        widened *= 1.5
        within = [i for i in items if miles(i) is not None and miles(i) <= widened]
    return within


def _drop_admin(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [i for i in items if i.get("subtype") not in ("primary_learning_center",) or i.get("enrollment")]


def _rank(items: list[dict[str, Any]], prefs: Preferences, grades: list[int], ctx: Optional[RouteContext] = None) -> list[dict[str, Any]]:
    w = weights_for(prefs, ctx)
    ranked: list[dict[str, Any]] = []
    for src in items:
        school = dict(src)
        school["ranking"] = score_school(school, prefs, w, ctx)
        if "affordability" in prefs.priorities:
            school["cost"] = cost_label(school)
        served = _serves(school, grades)
        school["serves_grades"] = served
        if len(grades) > 1 and served:
            school["ranking"]["reasons"].append("serves " + ", ".join(db.grade_label(g) or str(g) for g in served))
        ranked.append(school)
    ranked.sort(key=lambda i: i["ranking"]["score"], reverse=True)
    return ranked


def _base_filters(prefs: Preferences, grades: list[int]) -> tuple[Optional[list[str]], Optional[list[str]]]:
    categories = list(prefs.categories) if prefs.categories else None
    if categories is None and len(grades) == 1 and grades[0] < 0:
        categories = ["early_childhood", "public", "private", "charter"]
    fl_grades = None
    if prefs.min_fl_grade:
        fl_grades = {"A": ["A"], "B": ["A", "B"], "C": ["A", "B", "C"]}[prefs.min_fl_grade]
    return categories, fl_grades


def retrieve_and_rank(
    con: sqlite3.Connection,
    prefs: Preferences,
    origin: Optional[tuple[float, float]],
    limit: int = 6,
    household: Optional[Household] = None,
    work: Optional[tuple[float, float]] = None,
    activity_points: Optional[list[ActivityPoint]] = None,
) -> tuple[list[dict[str, Any]], int, Optional[list[dict[str, Any]]]]:
    """Return (results, candidates_considered, groups).

    groups is set only when no school can serve every child. results is always
    the flat list the map reads: the shared list, or the deduped per-child tops.
    """
    prefs = with_household(prefs, household)
    ctx = build_context(prefs, origin, household, work, activity_points)
    grades = requested_grades(prefs)
    categories, fl_grades = _base_filters(prefs, grades)

    def load(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
        out = []
        for r in rows:
            school = db.row_to_school(r, origin)
            annotate_route(school, ctx)
            out.append(school)
        db.attach_offerings(con, out)
        db.annotate_assignments(con, out, origin)
        return out

    if len(grades) <= 1:
        grade = grades[0] if grades else None
        rows = db.fetch_schools(con, categories=categories, grade=grade, fl_grades=fl_grades)
        items = load(rows)
        items = _drop_unpriced_private(items, prefs)
        items = _apply_radius(items, prefs, origin, ctx)
        if grade is not None and grade >= 0:
            items = _drop_admin(items)
        ranked = _rank(items, prefs, grades, ctx)
        return ranked[:limit], len(ranked), None

    # A state-grade minimum applies to graded schools. It must not hide
    # infant/pre-K providers when the household also has an older child.
    mixed_early = any(g < 0 for g in grades) and any(g >= 0 for g in grades)
    rows = db.fetch_schools(con, categories=categories, grade=None, fl_grades=None if mixed_early else fl_grades)
    items = load(rows)
    items = [i for i in items if _serves(i, grades)]
    items = _drop_unpriced_private(items, prefs)

    def _meets_fl(school: dict[str, Any]) -> bool:
        return not fl_grades or school.get("fl_grade") in fl_grades

    covering = [i for i in items if len(_serves(i, grades)) == len(set(grades))]
    if mixed_early and fl_grades:
        covering = [i for i in covering if _meets_fl(i)]
    if all(g >= 0 for g in grades):
        covering = _drop_admin(covering)
    covering = _apply_radius(covering, prefs, origin, ctx)
    if covering:
        ranked = _rank(covering, prefs, grades, ctx)
        return ranked[:limit], len(ranked), None

    labels = {c.grade: c.label for c in prefs.children}
    groups: list[dict[str, Any]] = []
    flat: list[dict[str, Any]] = []
    seen: set[int] = set()
    considered: set[int] = set()
    for grade in grades:
        subset = [i for i in items if _covers(i, grade)]
        if grade >= 0 and fl_grades:
            subset = [i for i in subset if i.get("fl_grade") in fl_grades]
        if grade >= 0:
            subset = _drop_admin(subset)
        subset = _apply_radius(subset, prefs, origin, ctx)
        ranked = _rank(subset, prefs, grades, ctx)
        for school in ranked:
            considered.add(school["id"])
        top = ranked[:limit]
        for school in top:
            if school["id"] not in seen:
                seen.add(school["id"])
                flat.append(school)
        groups.append(
            {
                "grade": grade,
                "label": labels.get(grade),
                "results": top,
                "candidates_considered": len(ranked),
            }
        )
    return flat, len(considered), groups
