"""Progressive discovery: decide when results are worth showing and which single
question to ask next.

Everything here is deterministic. The LLM only phrases what this module decides,
so a topic the parent already covered (or already declined) is never asked again.
"""

from __future__ import annotations

from typing import Any, Optional

from ..schemas import Household, Preferences, PreferencePatch, Question, QuestionOption, Stage, Topic

# Order matters: the first unknown, unasked topic is the next question.
TOPIC_ORDER: tuple[Topic, ...] = ("children", "location", "categories", "priorities", "radius", "work", "min_fl_grade")

# Topics a parent settles without stating a value ("any type is fine").
_CLEAR_TO_TOPIC: dict[str, Topic] = {
    "categories": "categories",
    "radius_miles": "radius",
    "min_fl_grade": "min_fl_grade",
    "priorities": "priorities",
}

PRIORITY_LABEL: dict[str, str] = {
    "academics": "strong academics",
    "distance": "a short trip",
    "small_school": "a small school",
    "large_school": "a large school",
    "diversity": "diversity",
    "stem": "STEM",
    "arts": "the arts",
    "language": "language programs",
    "magnet": "magnet programs",
    "religious": "a religious school",
    "montessori": "Montessori",
    "special_needs": "special-needs support",
    "gifted": "gifted programs",
    "affordability": "tuition-free options",
    "early_childhood": "early childhood",
}

CATEGORY_LABEL: dict[str, str] = {
    "public": "public",
    "charter": "charter",
    "private": "private",
    "early_childhood": "child care",
}

TOPIC_LABEL: dict[Topic, str] = {
    "children": "your child's grade",
    "location": "where you live",
    "categories": "a school type",
    "priorities": "what matters most",
    "radius": "how far you'll travel",
    "work": "where you work",
    "min_fl_grade": "a minimum state grade",
}


def grade_phrase(grade: int) -> str:
    if grade == -2:
        return "an infant or toddler"
    if grade == -1:
        return "a pre-K child"
    if grade == 0:
        return "a kindergartner"
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(grade if grade < 20 else grade % 10, "th")
    return f"a {grade}{suffix} grader"


def _noun(grade: int) -> str:
    """grade_phrase without its article: 'kindergartner', '3rd grader'."""
    phrase = grade_phrase(grade)
    return phrase.split(" ", 1)[1] if phrase.startswith(("a ", "an ")) else phrase


def known_topics(prefs: Preferences, household: Optional[Household], origin: Optional[tuple[float, float]]) -> set[Topic]:
    known: set[Topic] = set()
    if prefs.children:
        known.add("children")
    if prefs.location_text or origin:
        known.add("location")
    if prefs.categories:
        known.add("categories")
    if prefs.priorities:
        known.add("priorities")
    if prefs.radius_miles is not None:
        known.add("radius")
    if household and household.work_location_text:
        known.add("work")
    if prefs.min_fl_grade:
        known.add("min_fl_grade")
    return known


def stage_for(prefs: Preferences, origin: Optional[tuple[float, float]]) -> Stage:
    has_children = bool(prefs.children)
    has_place = bool(prefs.location_text or origin)
    if has_children and has_place:
        return "refined"
    if has_children or has_place:
        return "preliminary"
    return "discovering"


def settled_by_patch(patch: PreferencePatch) -> list[Topic]:
    """Topics the parent closed this turn without giving a value."""
    return [_CLEAR_TO_TOPIC[f] for f in patch.clear_fields if f in _CLEAR_TO_TOPIC]


_SETTLED_PHRASE: dict[Topic, str] = {
    "categories": "Any school type",
    "radius": "No distance limit",
    "min_fl_grade": "No minimum state grade",
    "priorities": "No particular priorities",
}


def acknowledge_settled(changed: list[str], settled: list[Topic]) -> list[str]:
    """Add a phrase for each topic the parent declined, unless the diff already said it."""
    out = list(changed)
    for topic in settled:
        phrase = _SETTLED_PHRASE.get(topic)
        if phrase and phrase not in out:
            out.append(phrase)
    return out


def _opt(label: str, message: str) -> QuestionOption:
    return QuestionOption(label=label, message=message)


def _question(topic: Topic, prefs: Preferences, household: Optional[Household]) -> Question:
    if topic == "children":
        return Question(
            topic="children",
            text="How old is your child, or what grade are they entering? If you have more than one, tell me about each.",
            options=[
                _opt("Infant / toddler", "an infant or toddler"),
                _opt("Pre-K", "pre-K"),
                _opt("Kindergarten", "kindergarten"),
                _opt("Elementary", "elementary school"),
                _opt("Middle school", "middle school"),
                _opt("High school", "high school"),
            ],
        )
    if topic == "location":
        return Question(
            topic="location",
            text="Where in Miami-Dade do you live, or where should the school be close to? A neighborhood, ZIP, or address works.",
            options=[],
        )
    if topic == "categories":
        return Question(
            topic="categories",
            text="Do you have a school type in mind?",
            options=[
                _opt("Public", "public schools"),
                _opt("Charter", "charter schools"),
                _opt("Private", "private schools"),
                _opt("Any type is fine", "any school type is fine"),
            ],
        )
    if topic == "priorities":
        return Question(
            topic="priorities",
            text="What matters most to you?",
            options=[
                _opt("Strong academics", "strong academics"),
                _opt("Small school", "a small school"),
                _opt("Bilingual", "bilingual programs"),
                _opt("STEM", "STEM programs"),
                _opt("Close to home", "close to home"),
                _opt("Tuition-free", "tuition-free options"),
            ],
        )
    if topic == "radius":
        return Question(
            topic="radius",
            text="How far are you willing to travel?",
            options=[
                _opt("Within 2 mi", "within 2 miles"),
                _opt("Within 5 mi", "within 5 miles"),
                _opt("Within 10 mi", "within 10 miles"),
                _opt("Distance doesn't matter", "distance doesn't matter"),
            ],
        )
    if topic == "work":
        return Question(
            topic="work",
            text="Where do you work? I can rank schools by how far out of your way they are.",
            options=[],
        )
    return Question(
        topic="min_fl_grade",
        text="Should I limit this to schools with a certain Florida DOE grade?",
        options=[
            _opt("A only", "only A-rated schools"),
            _opt("A or B", "at least a B"),
            _opt("Any grade is fine", "any state grade is fine"),
        ],
    )


def _applies(
    topic: Topic,
    prefs: Preferences,
    household: Optional[Household],
    origin: Optional[tuple[float, float]],
    results: list[dict[str, Any]],
) -> bool:
    if topic in ("children", "location", "priorities"):
        return True
    if topic == "categories":
        return len({s.get("category") for s in results}) > 1
    if topic == "radius":
        if origin is None:
            return False
        dists = [s["distance_miles"] for s in results if s.get("distance_miles") is not None]
        return not dists or max(dists) > 5
    if topic == "work":
        return bool(household and (household.needs_after_school_care or household.work_schedule_text))
    if topic == "min_fl_grade":
        return any(s.get("fl_grade") for s in results)
    return False


def next_question(
    prefs: Preferences,
    household: Optional[Household],
    origin: Optional[tuple[float, float]],
    asked: list[str],
    results: list[dict[str, Any]],
) -> Optional[Question]:
    known = known_topics(prefs, household, origin)
    for topic in TOPIC_ORDER:
        if topic in known or topic in asked:
            continue
        if _applies(topic, prefs, household, origin, results):
            return _question(topic, prefs, household)
    return None


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def changes(
    prior: Preferences,
    prefs: Preferences,
    prior_household: Optional[Household],
    household: Optional[Household],
) -> list[str]:
    """Short phrases describing what this turn changed, for acknowledgement."""
    out: list[str] = []

    before = {c.grade: c for c in prior.children}
    after = {c.grade: c for c in prefs.children}
    added = [g for g in after if g not in before]
    removed = [g for g in before if g not in after]
    if len(before) == 1 and len(after) == 1 and added and removed:
        out.append(f"Grade changed to {_noun(added[0])}")
    else:
        if added:
            out.append("Added " + _join([grade_phrase(g) for g in added]))
        if removed:
            out.append("Removed " + _join([grade_phrase(g) for g in removed]))

    if prefs.location_text != prior.location_text:
        if prefs.location_text:
            place = prefs.location_text
            out.append(f"Searching near {place.title() if place == place.lower() else place}")
        elif prior.location_text:
            out.append("Location cleared")

    if sorted(prefs.categories) != sorted(prior.categories):
        if not prefs.categories:
            out.append("Any school type")
        elif not prior.categories:
            out.append("Limited to " + _join([CATEGORY_LABEL[c] for c in prefs.categories]) + " schools")
        elif not set(prior.categories) & set(prefs.categories):
            out.append("Switched to " + _join([CATEGORY_LABEL[c] for c in prefs.categories]) + " only")
        else:
            add = [c for c in prefs.categories if c not in prior.categories]
            drop = [c for c in prior.categories if c not in prefs.categories]
            if add:
                out.append("Added " + _join([CATEGORY_LABEL[c] for c in add]) + " schools")
            if drop:
                out.append("Dropped " + _join([CATEGORY_LABEL[c] for c in drop]) + " schools")

    add = [p for p in prefs.priorities if p not in prior.priorities]
    drop = [p for p in prior.priorities if p not in prefs.priorities]
    if add:
        out.append("Prioritizing " + _join([PRIORITY_LABEL.get(p, p) for p in add]))
    if drop:
        out.append("No longer weighting " + _join([PRIORITY_LABEL.get(p, p) for p in drop]))

    kw_add = [k for k in prefs.keywords if k.lower() not in {x.lower() for x in prior.keywords}]
    kw_drop = [k for k in prior.keywords if k.lower() not in {x.lower() for x in prefs.keywords}]
    if kw_add:
        out.append("Looking for " + _join(kw_add))
    if kw_drop:
        out.append("Dropped the " + _join(kw_drop) + " requirement")

    if prefs.radius_miles != prior.radius_miles:
        if prefs.radius_miles is not None:
            out.append(f"Within {prefs.radius_miles:g} miles")
        else:
            out.append("No distance limit")

    if prefs.min_fl_grade != prior.min_fl_grade:
        if prefs.min_fl_grade:
            out.append(f"{prefs.min_fl_grade}-rated or better")
        else:
            out.append("No minimum state grade")

    if prefs.prefer_near != prior.prefer_near and prefs.prefer_near:
        out.append({"home": "Measuring from home", "work": "Measuring from work", "route": "Measuring along your commute"}[prefs.prefer_near])

    ph = prior_household or Household()
    hh = household or Household()
    if hh.work_location_text != ph.work_location_text:
        if hh.work_location_text:
            out.append(f"Remembered: you work in {hh.work_location_text}")
        elif ph.work_location_text:
            out.append("Forgot your workplace")
    if hh.work_schedule_text != ph.work_schedule_text and hh.work_schedule_text:
        out.append(f"Noted your hours: {hh.work_schedule_text}")
    if hh.needs_after_school_care != ph.needs_after_school_care and hh.needs_after_school_care is not None:
        out.append("Noted: late pickup needed" if hh.needs_after_school_care else "Noted: pickup is covered")
    before_acts = {a.label.lower() for a in ph.activities}
    after_acts = {a.label.lower(): a for a in hh.activities}
    for key, act in after_acts.items():
        if key not in before_acts:
            out.append(f"Remembered: {act.label}" + (f" in {act.location_text}" if act.location_text else ""))
    for key in before_acts - set(after_acts):
        out.append(f"Dropped {key}")
    if ph and not ph.is_empty() and hh.is_empty():
        out.append("Forgot your household details")
    return out


def intro(changed: list[str], prefs: Preferences, household: Optional[Household]) -> str:
    """Summary for a turn that is not ready to rank yet."""
    if changed:
        return "Got it: " + "; ".join(c[0].lower() + c[1:] for c in changed) + "."
    if not prefs.children and not prefs.location_text:
        return "Happy to help you find a school in Miami-Dade. I rank real providers using public data, so a couple of details go a long way."
    return "Thanks. One more thing and I can show you matches."


def preliminary_note(prefs: Preferences, household: Optional[Household], origin: Optional[tuple[float, float]]) -> str:
    """What the parent gave so far and the single thing that would sharpen results."""
    known = known_topics(prefs, household, origin)
    have = [TOPIC_LABEL[t] for t in ("children", "location") if t in known]
    missing = [TOPIC_LABEL[t] for t in ("children", "location") if t not in known]
    text = "These are first matches"
    if have:
        text += " based on " + _join(have)
    text += "."
    if missing:
        text += f" Tell me {_join(missing)} to sharpen them."
    return text
