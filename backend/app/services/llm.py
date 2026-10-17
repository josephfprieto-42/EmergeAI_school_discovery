"""OpenAI-backed preference extraction and grounded explanations, with deterministic
fallbacks so the API works without a key.

The LLM never sees the full database. It receives (1) the conversation to extract a
Preferences object and (2) a compact JSON of the already-ranked candidates to explain.
It is instructed to cite only fields present in that JSON.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from ..config import OPENAI_API_KEY, OPENAI_MODEL
from ..schemas import ChatMessage, Preferences, SchoolExplanation

_client = None


def llm_available() -> bool:
    return bool(OPENAI_API_KEY)


def _get_client():
    global _client
    if _client is None and OPENAI_API_KEY:
        from openai import OpenAI

        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client


# ----------------------------------------------------------------------------------
# Preference extraction
# ----------------------------------------------------------------------------------

EXTRACT_SYSTEM = """You extract structured school-search preferences for a parent in Miami-Dade County, Florida.
Return ONLY a JSON object matching this schema (omit keys you cannot infer; do not guess):
{
  "location_text": string|null,   // address, neighborhood, ZIP, landmark they live near or want to search around
  "child_grade": int|null,        // -2 infant/toddler (under 3), -1 pre-K (3-4 yrs), 0 kindergarten (5 yrs), 1..12. Convert ages: grade = age - 5.
  "child_grades": int[],          // all children if several
  "categories": string[],         // subset of ["public","charter","private","early_childhood"]; "daycare"/"preschool" => early_childhood; empty if not stated
  "radius_miles": number|null,    // if they mention a distance or commute. "walking distance" ~1, "close" ~3, "willing to drive" ~10
  "priorities": string[],         // subset of ["academics","distance","small_school","large_school","diversity","stem","arts","language","magnet","religious","montessori","special_needs","gifted","affordability","early_childhood"]
  "keywords": string[],           // specific program words to match in names, e.g. "Montessori", "bilingual", "IB", "Catholic"
  "min_fl_grade": "A"|"B"|"C"|null, // only if they insist on a minimum state grade
  "notes": string|null            // anything else relevant, one sentence
}
Merge with the previously extracted preferences when provided; newer statements override older ones."""


def _fallback_extract(text: str, prior: Optional[Preferences]) -> Preferences:
    t = text.lower()
    p = prior.model_copy(deep=True) if prior else Preferences()

    m = re.search(r"\b(33\d{3})\b", t)
    if m:
        p.location_text = m.group(1)
    else:
        m = re.search(r"(?:near|in|around|close to|live in|living in|from)\s+([a-z][a-z .'-]{2,40}?)(?:[,.;]|\s+(?:and|with|for|my|our|looking|want|need)\b|$)", t)
        if m:
            p.location_text = m.group(1).strip()

    ages = re.findall(r"(\d{1,2})\s*(?:-|to)?\s*(?:year|yr)s?[- ]old", t)
    grades: list[int] = []
    for a in ages:
        a = int(a)
        grades.append(-2 if a < 3 else -1 if a < 5 else max(0, min(12, a - 5)))
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[- ]grade", t)
    if m:
        grades.append(max(0, min(12, int(m.group(1)))))
    if re.search(r"\bkindergart|\bkinder\b", t):
        grades.append(0)
    if re.search(r"\bpre-?k|preschool|vpk|\b3[- ]year|\b4[- ]year", t) and -1 not in grades:
        grades.append(-1)
    if re.search(r"\binfant|toddler|newborn|baby|daycare|day care|child ?care", t) and -2 not in grades:
        grades.append(-2)
    if re.search(r"\bhigh school|\bhighschool", t) and not grades:
        grades.append(9)
    if re.search(r"\bmiddle school", t) and not grades:
        grades.append(6)
    if re.search(r"\belementary", t) and not grades:
        grades.append(1)
    if grades:
        p.child_grades = sorted(set(grades))
        p.child_grade = p.child_grades[0]

    cats: list[str] = list(p.categories)
    if re.search(r"\bpublic\b", t):
        cats.append("public")
    if re.search(r"\bcharter", t):
        cats.append("charter")
    if re.search(r"\bprivate|catholic|christian|jewish|religious|parochial", t):
        cats.append("private")
    if re.search(r"\bdaycare|day care|child ?care|preschool|head start|infant|toddler", t):
        cats.append("early_childhood")
    p.categories = list(dict.fromkeys(c for c in cats if c in ("public", "charter", "private", "early_childhood")))  # type: ignore[assignment]

    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:miles?|mi)\b", t)
    if m:
        p.radius_miles = float(m.group(1))
    elif "walking" in t:
        p.radius_miles = 1.0
    elif re.search(r"\bclose|nearby|near me", t) and not p.radius_miles:
        p.radius_miles = 3.0

    pri = set(p.priorities)
    checks = {
        "academics": r"academ|best school|top rated|high.?performing|test score|a-rated|\"a\" school|grade a",
        "distance": r"close|near|walk|commute|short drive",
        "small_school": r"small school|small class|smaller|intimate",
        "large_school": r"big school|large school|lots of",
        "stem": r"stem|science|technology|engineering|robotic|coding|math",
        "arts": r"\bart|music|theat|danc|performing|design",
        "language": r"bilingual|dual.?language|spanish|french|immersion|international|\bib\b",
        "magnet": r"magnet",
        "religious": r"catholic|christian|jewish|hebrew|religious|church|faith|parochial|islamic",
        "montessori": r"montessori",
        "special_needs": r"special needs|autis|iep|ese\b|disabilit|therap|dyslex",
        "gifted": r"gifted|advanced|honors|accelerat",
        "affordability": r"afford|cheap|free|tuition|budget|scholarship|voucher",
        "early_childhood": r"daycare|day care|preschool|pre-?k|infant|toddler|head start",
    }
    for k, rx in checks.items():
        if re.search(rx, t):
            pri.add(k)
    p.priorities = sorted(pri)  # type: ignore[assignment]

    kws = set(p.keywords)
    for kw in ("montessori", "bilingual", "catholic", "christian", "jewish", "hebrew", "ib", "international", "magnet", "stem", "arts", "academy", "preparatory", "lutheran", "episcopal", "baptist"):
        if re.search(rf"\b{kw}\b", t):
            kws.add(kw.title() if kw != "ib" else "IB")
    p.keywords = sorted(kws)

    m = re.search(r"\b([abc])[- ]rated|at least (?:an? )?([abc])\b|only (?:an? )?([abc]) schools", t)
    if m:
        p.min_fl_grade = (m.group(1) or m.group(2) or m.group(3)).upper()  # type: ignore[assignment]
    return p


def extract_preferences(message: str, history: list[ChatMessage], prior: Optional[Preferences]) -> tuple[Preferences, bool]:
    client = _get_client()
    if not client:
        return _fallback_extract(message, prior), False
    msgs: list[dict[str, str]] = [{"role": "system", "content": EXTRACT_SYSTEM}]
    if prior:
        msgs.append({"role": "system", "content": "Previously extracted preferences: " + prior.model_dump_json(exclude_none=True)})
    for h in history[-8:]:
        msgs.append({"role": h.role, "content": h.content})
    msgs.append({"role": "user", "content": message})
    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=msgs,
            response_format={"type": "json_object"},
            temperature=0,
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        data = {k: v for k, v in data.items() if v is not None}
        if prior:
            merged = prior.model_dump()
            merged.update(data)
            data = merged
        prefs = Preferences.model_validate(data)
        if prefs.child_grade is None and prefs.child_grades:
            prefs.child_grade = prefs.child_grades[0]
        return prefs, True
    except Exception:  # noqa: BLE001
        return _fallback_extract(message, prior), False


# ----------------------------------------------------------------------------------
# Explanations
# ----------------------------------------------------------------------------------

EXPLAIN_SYSTEM = """You are a knowledgeable, warm Miami-Dade school counselor helping a parent choose among schools.
You are given the parent's preferences and a JSON list of candidate schools that were ALREADY filtered and ranked by a deterministic algorithm using verified public data (Miami-Dade County GIS, Florida DOE school grades, NCES).

Rules:
- Use ONLY facts present in the JSON. Never invent programs, test scores, tuition, reviews, or reputations.
- When a value is null, say it is not reported rather than guessing.
- Florida DOE grades (A-F) and achievement percentages exist only for public and charter schools; private and early-childhood providers have none.
- Be concrete: cite distance, grade, achievement numbers, enrollment, ratios, and name-based program signals.
- Mention real tradeoffs (farther away, lower grade, larger size, no state data, etc.).
- Keep each 'why' to 1-2 sentences and each 'tradeoffs' to one sentence.

Return ONLY JSON:
{
  "summary": string,                // 2-3 sentences addressed to the parent, summarizing what you looked for and the top pick
  "follow_up": string|null,         // one clarifying question if preferences were vague (e.g., missing location or grade), else null
  "explanations": [ {"school_id": int, "why": string, "tradeoffs": string} ]  // one per candidate, same order
}"""

COMPARE_SYSTEM = """You are a Miami-Dade school counselor. Compare the given schools side by side for a parent using ONLY the JSON data provided (verified public data). Never invent facts; say 'not reported' for nulls.
Return ONLY JSON: {"summary": string (3-4 sentences), "tradeoffs": [string, ...] (3-6 concise bullet-style sentences, each naming the schools involved)}"""


def _compact(s: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "id", "name", "category", "subtype", "address", "city", "grades_text", "enrollment", "capacity",
        "distance_miles", "fl_grade", "fl_grade_prev1", "fl_grade_prev2", "ela_ach", "math_ach", "sci_ach", "ss_ach",
        "grad_rate", "pct_points", "pct_econ_disadvantaged", "student_teacher_ratio", "frl_pct", "magnet",
        "fl_title_i", "year_established", "coed", "license_expires", "website",
    )
    out = {k: s.get(k) for k in keep if s.get(k) is not None}
    if s.get("ranking"):
        out["rank_reasons"] = s["ranking"].get("reasons")
        out["rank_score"] = s["ranking"].get("score")
    return out


def _fmt(v, suffix="") -> str:
    return "not reported" if v is None else f"{v}{suffix}"


def _fallback_explain(prefs: Preferences, schools: list[dict[str, Any]]) -> tuple[str, Optional[str], list[SchoolExplanation]]:
    exps: list[SchoolExplanation] = []
    for s in schools:
        bits = []
        if s.get("distance_miles") is not None:
            bits.append(f"{s['distance_miles']:.1f} miles from your location")
        if s.get("fl_grade"):
            bits.append(f"rated {s['fl_grade']} by the Florida DOE" + (f" (was {s['fl_grade_prev1']} the prior year)" if s.get("fl_grade_prev1") and s['fl_grade_prev1'] != s['fl_grade'] else ""))
        if s.get("ela_ach") is not None and s.get("math_ach") is not None:
            bits.append(f"{s['ela_ach']:.0f}% ELA and {s['math_ach']:.0f}% math proficiency")
        if s.get("grades_text"):
            bits.append(f"serves {s['grades_text']}")
        if s.get("enrollment"):
            bits.append(f"{s['enrollment']:,} students")
        elif s.get("capacity"):
            bits.append(f"licensed capacity {s['capacity']}")
        if s.get("student_teacher_ratio"):
            bits.append(f"{s['student_teacher_ratio']:.0f}:1 student-teacher ratio")
        hits = (s.get("ranking") or {}).get("keyword_hits") or []
        if hits:
            bits.append("name signals " + ", ".join(h.split(":")[-1] for h in hits[:2]))
        why = f"{s['name']} is " + "; ".join(bits) + "." if bits else f"{s['name']} matches your grade and area filters."
        trade = []
        if s.get("category") in ("private", "early_childhood"):
            trade.append("no Florida DOE grade or test data is published for this type of provider")
        elif not s.get("fl_grade"):
            trade.append("no state grade is reported for this school")
        elif s["fl_grade"] in ("C", "D", "F"):
            trade.append(f"state grade is {s['fl_grade']}")
        if s.get("distance_miles") and prefs.radius_miles and s["distance_miles"] > prefs.radius_miles:
            trade.append(f"farther than your {prefs.radius_miles:g}-mile preference")
        if "small_school" in prefs.priorities and (s.get("enrollment") or 0) > 800:
            trade.append("larger than a typical small school")
        exps.append(SchoolExplanation(school_id=s["id"], why=why, tradeoffs="; ".join(trade).capitalize() + "." if trade else "No major tradeoffs found in the available data."))
    top = schools[0]["name"] if schools else "no schools"
    summary = f"I filtered Miami-Dade providers by your criteria and ranked {len(schools)} using distance, Florida DOE results, size, and program signals. {top} ranks first."
    follow = None
    if not prefs.location_text:
        follow = "Where in Miami-Dade do you live (neighborhood, ZIP, or address) so I can rank by distance?"
    elif prefs.child_grade is None:
        follow = "How old is your child, or what grade will they be entering?"
    return summary, follow, exps


def explain(prefs: Preferences, schools: list[dict[str, Any]]) -> tuple[str, Optional[str], list[SchoolExplanation], bool]:
    client = _get_client()
    if not client or not schools:
        s, f, e = _fallback_explain(prefs, schools)
        return s, f, e, False
    payload = {"preferences": prefs.model_dump(exclude_none=True), "candidates": [_compact(s) for s in schools]}
    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "system", "content": EXPLAIN_SYSTEM}, {"role": "user", "content": json.dumps(payload)}],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        by_id = {s["id"]: s for s in schools}
        exps = [SchoolExplanation(**e) for e in data.get("explanations", []) if e.get("school_id") in by_id]
        if len(exps) < len(schools):
            have = {e.school_id for e in exps}
            _, _, fb = _fallback_explain(prefs, [s for s in schools if s["id"] not in have])
            exps.extend(fb)
        order = {s["id"]: i for i, s in enumerate(schools)}
        exps.sort(key=lambda e: order.get(e.school_id, 99))
        return data.get("summary") or "", data.get("follow_up"), exps, True
    except Exception:  # noqa: BLE001
        s, f, e = _fallback_explain(prefs, schools)
        return s, f, e, False


def _fallback_compare(schools: list[dict[str, Any]]) -> tuple[str, list[str]]:
    names = [s["name"] for s in schools]
    trade: list[str] = []
    graded = [s for s in schools if s.get("fl_grade")]
    if graded:
        best = max(graded, key=lambda s: FL_ORDER.get(s["fl_grade"], 0))
        if len({s["fl_grade"] for s in graded}) == 1:
            trade.append(f"All graded schools ({', '.join(s['name'] for s in graded)}) hold a Florida DOE grade of {best['fl_grade']}.")
        else:
            trade.append(f"{best['name']} has the strongest Florida DOE grade ({best['fl_grade']}); " + ", ".join(f"{s['name']} is {s['fl_grade']}" for s in graded if s is not best) + ".")
    ungraded = [s["name"] for s in schools if not s.get("fl_grade")]
    if ungraded:
        trade.append(", ".join(ungraded) + (" has" if len(ungraded) == 1 else " have") + " no state grade or test data published (private/early-childhood providers are not graded).")
    dists = [s for s in schools if s.get("distance_miles") is not None]
    if dists:
        near = min(dists, key=lambda s: s["distance_miles"])
        far = max(dists, key=lambda s: s["distance_miles"])
        if near is not far:
            trade.append(f"{near['name']} is closest at {near['distance_miles']:.1f} mi; {far['name']} is farthest at {far['distance_miles']:.1f} mi.")
    enr = [s for s in schools if s.get("enrollment")]
    if len(enr) > 1:
        sm = min(enr, key=lambda s: s["enrollment"])
        lg = max(enr, key=lambda s: s["enrollment"])
        trade.append(f"{sm['name']} is the smallest ({sm['enrollment']:,} students) and {lg['name']} the largest ({lg['enrollment']:,}).")
    ratios = [s for s in schools if s.get("student_teacher_ratio")]
    if len(ratios) > 1:
        lo = min(ratios, key=lambda s: s["student_teacher_ratio"])
        trade.append(f"{lo['name']} has the lowest student-teacher ratio ({lo['student_teacher_ratio']:.0f}:1).")
    summary = f"Comparing {', '.join(names[:-1])} and {names[-1]} using verified public data. " + (trade[0] if trade else "")
    return summary, trade


FL_ORDER = {"A": 5, "B": 4, "C": 3, "D": 2, "F": 1}


def compare(prefs: Optional[Preferences], schools: list[dict[str, Any]]) -> tuple[str, list[str], bool]:
    client = _get_client()
    if not client:
        s, t = _fallback_compare(schools)
        return s, t, False
    payload = {"preferences": prefs.model_dump(exclude_none=True) if prefs else None, "schools": [_compact(s) for s in schools]}
    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "system", "content": COMPARE_SYSTEM}, {"role": "user", "content": json.dumps(payload)}],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        return data.get("summary") or "", [str(t) for t in data.get("tradeoffs", [])], True
    except Exception:  # noqa: BLE001
        s, t = _fallback_compare(schools)
        return s, t, False
