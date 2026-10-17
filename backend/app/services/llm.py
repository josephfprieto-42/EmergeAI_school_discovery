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
from ..schemas import (
    ActivityPlace,
    ActivityUpdate,
    ChatMessage,
    Child,
    ChildUpdate,
    Household,
    HouseholdPatch,
    ListUpdate,
    PreferencePatch,
    Preferences,
    Question,
    SchoolExplanation,
    Stage,
)
from . import discovery

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

EXTRACT_SYSTEM = """You extract a preference PATCH for a parent searching for schools in Miami-Dade County, Florida.
Return ONLY a JSON object. Omit every key this message does not change. Do not echo unchanged preferences.

{
  "reset": false,
  "location_text": string,
  "radius_miles": number,
  "min_fl_grade": "A"|"B"|"C",
  "notes": string,
  "clear_fields": string[],
  "categories": {"op": "add"|"remove"|"replace"|"clear", "values": string[]},
  "priorities": {"op": "add"|"remove"|"replace"|"clear", "values": string[]},
  "keywords": {"op": "add"|"remove"|"replace"|"clear", "values": string[]},
  "children": {"op": "add"|"remove"|"replace"|"clear", "children": [{"grade": int, "label": string|null}]},
  "prefer_near": "home"|"work"|"route",
  "household": {
    "work_location_text": string,
    "work_schedule_text": string,
    "needs_after_school_care": boolean,
    "activities": {"op": "add"|"remove"|"replace"|"clear", "activities": [{"label": string, "location_text": string|null, "child_label": string|null}]},
    "activity_interests": {"op": "add"|"remove"|"replace"|"clear", "values": string[]},
    "clear_fields": string[]
  }
}

Rules:
- Unspecified constraints stay stored. Do not repeat them.
- clear_fields drops a constraint the parent gave up. Allowed names: "location_text", "radius_miles", "min_fl_grade", "notes", "categories", "priorities", "keywords", "children", "prefer_near", "household".
- location_text is where the family LIVES or wants the school: a bare "near Coral Gables", "in Kendall", "33156", or "2nd grader near X" is location_text. Only places tied to a job ("I work in Brickell", "my office is downtown", "commute to Doral") go to household.work_location_text, and places tied to an activity ("ballet in Coconut Grove") go to that activity's location_text. One message often has all three: keep them separate and always fill location_text when a home area is present.
- household.work_schedule_text is the parent's own words about hours ("I work until 6", "night shifts").
- household.needs_after_school_care is true for "work until 5/6/7", "late pickup", "both work full time", "need aftercare", "extended day"; false when they say pickup is covered.
- household.activities are recurring things a child already does, with the place when stated ("ballet in Coconut Grove" -> label "ballet", location_text "Coconut Grove").
- household.activity_interests is a subset of ["arts","stem","language","sports"] derived from activities: music/dance/theater/art -> "arts"; robotics/coding/science club -> "stem"; Spanish/French/Mandarin lessons -> "language"; soccer/swim/gymnastics/karate/tennis -> "sports".
- household.clear_fields allowed: "work_location_text", "work_schedule_text", "needs_after_school_care", "activities", "activity_interests". "forget my work", "I changed jobs" -> clear work_location_text.
- prefer_near: "closer to work"/"near my office" -> "work"; "on the way to work"/"on my commute" -> "route"; "closer to home" -> "home". Include it only when they say which.
- "also", "another child", "as well" on a list -> op "add".
- "only", "just", "instead", "switch to" -> op "replace" for that list.
- "not", "no longer", "drop", "remove", "forget" a specific item -> op "remove". Use clear_fields when they drop the constraint entirely ("anywhere", "any school type", "no minimum grade").
- "start over", "reset", "forget everything", "new search" -> reset true, then include ONLY constraints written in that same message. Never carry anything over from history or stored preferences; a bare "start over" is exactly {"reset": true}.
- Use clear_fields only when the parent drops a constraint without replacing it. "only charters" is categories replace, not a clear.
- Grades: -2 infant/toddler (under 3), -1 pre-K (3-4), 0 kindergarten (5), 1..12. Convert ages with grade = age - 5.
- categories values are a subset of ["public","charter","private","early_childhood"]. "daycare"/"preschool" => early_childhood.
- priorities values are a subset of ["academics","distance","small_school","large_school","diversity","stem","arts","language","magnet","religious","montessori","special_needs","gifted","affordability","early_childhood"].
- keywords are program words to match in names, e.g. "Montessori", "bilingual", "IB", "Catholic".
- radius: "walking distance" ~1, "close" ~3, "willing to drive" ~10. Include radius_miles only when they mention distance.
- label is a short phrase from the parent ("7-year-old", "kindergartner"), or null.
- Include several children when the parent mentions more than one.
- Answers to a pending question: when the assistant's last message asked about one thing, a bare reply is the answer to it and nothing else. "kindergarten" -> children add grade 0; "Coral Gables" or "33156" -> location_text; "public or charter" -> categories replace; "5 miles" -> radius_miles 5; "strong academics" -> priorities add. A bare answer is never a reset.
- "Any type is fine" / "no preference" -> clear_fields ["categories"]; "distance doesn't matter" / "any distance" -> clear_fields ["radius_miles"]; "any grade is fine" -> clear_fields ["min_fl_grade"]; "nothing in particular" -> clear_fields ["priorities"]. Do not invent a value for a topic the parent declined."""


_NEG = r"not|no|drop|without|no longer|forget|don't care about|do not care about"
_REPLACE = r"only|just|instead|switch to"
_VAGUE_PLACES = {
    "the county",
    "miami-dade",
    "miami dade",
    "miami dade county",
    "the area",
    "the city",
    "town",
    "here",
}


def _negated(text: str, rx: str) -> bool:
    return re.search(rf"\b(?:{_NEG})\b(?:\s+\w+){{0,4}}\s+(?:{rx})", text) is not None


def _replace_intent(text: str, rx: str) -> bool:
    return re.search(rf"\b(?:{_REPLACE})\b(?:\s+\w+){{0,4}}\s+(?:{rx})", text) is not None


def _list_op(text: str, mention_rx: str, adding_extra_child: bool = False) -> str:
    if adding_extra_child or re.search(r"\b(also|another|as well|other child|second child)\b", text):
        return "add"
    if _replace_intent(text, mention_rx):
        return "replace"
    return "add"


def _fallback_patch(text: str, prior: Optional[Preferences] = None, pending: Optional[str] = None) -> PreferencePatch:
    """Regex extraction. `pending` is the topic the advisor just asked about, so a
    bare reply ("Coral Gables", "3") is read as that answer."""
    t = text.lower().strip()
    kwargs: dict = {}
    if re.search(r"\b(start over|start again|reset|forget everything|new search|from scratch)\b", t):
        kwargs["reset"] = True

    clears: list[str] = []
    dont_care = re.search(r"\b(doesn'?t matter|does not matter|no preference|don'?t mind|whatever works|not important|not picky)\b", t)
    if re.search(r"\b(anywhere|whole county|countywide|any distance|no (distance|radius) limit|forget the (location|distance|radius)|distance doesn'?t matter)\b", t) or (dont_care and pending == "radius"):
        clears.append("radius_miles")
        if re.search(r"\b(anywhere|forget the location|no specific (location|area)|whole county|countywide)\b", t):
            clears.append("location_text")
    if re.search(r"\b(any (school )?type( of school)?( is fine| works)?|no preference on type|forget the (category|school type))\b", t) or (dont_care and pending == "categories"):
        clears.append("categories")
    if re.search(r"\b(no minimum grade|any (state |fl |florida )?grade( is fine| works)?|drop the grade requirement|forget the (minimum|a-rating|grade requirement))\b", t) or (dont_care and pending == "min_fl_grade"):
        clears.append("min_fl_grade")
    if re.search(r"\b(no priorities|forget (the |my )?priorities|nothing in particular|no particular priorit)\b", t) or (dont_care and pending == "priorities"):
        clears.append("priorities")

    location = None
    # Work and activity places are not where the family lives.
    t_home = re.sub(r"\b(?:work(?:s|ing)?|office is|job is|commute)\s+(?:in|near|at|to|out of|downtown in)\s+" + _PLACE_RX, " ", t)
    t_home = re.sub(r"\b(?:in|at|near)\s+(?:my|our|the)\s+(?:work|office|job)\b", " ", t_home)
    for word in _ACTIVITY_WORDS:
        t_home = re.sub(rf"\b(?:{word})\b(?:\s+(?:class|classes|lessons|practice|team|club))?\s+(?:in|at|near)\s+" + _PLACE_RX, " ", t_home)
    m = re.search(r"\b(33\d{3})\b", t_home)
    if m:
        location = m.group(1)
    else:
        m = re.search(r"(?:near|in|around|close to|live in|living in|from)\s+([a-z][a-z .'-]{2,40}?)(?:[,.;]|\s+(?:and|with|for|my|our|looking|want|need|she|he|they|until|till)\b|$)", t_home)
        if m:
            place = m.group(1).strip(" .")
            if place not in _VAGUE_PLACES:
                location = place
    if location is None and pending == "location" and not clears and not dont_care:
        # A bare place name in reply to "where do you live?"
        bare = text.strip(" .!?")
        if 0 < len(bare.split()) <= 6 and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 .,'#/-]{1,60}", bare) and bare.lower() not in _VAGUE_PLACES and not re.search(r"\b(grade|school|work|miles?|kinder|pre-?k|infant|toddler)\b", t):
            location = bare.lower()
    if location and "location_text" not in clears:
        kwargs["location_text"] = location

    children: list[tuple[int, str]] = []
    for age_s in re.findall(r"(\d{1,2})\s*(?:-|to)?\s*months?[- ]old", t):
        months = int(age_s)
        if months < 36:
            children.append((-2, f"{months}-month-old"))
    for age_s in re.findall(r"(\d{1,2})\s*(?:-|to)?\s*(?:year|yr)s?[- ]old", t):
        age = int(age_s)
        grade = -2 if age < 3 else -1 if age < 5 else max(0, min(12, age - 5))
        children.append((grade, f"{age}-year-old"))
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[- ]grade", t)
    if m:
        grade = max(0, min(12, int(m.group(1))))
        children.append((grade, f"grade {grade}"))
    if re.search(r"\bkindergart|\bkinder\b", t):
        children.append((0, "kindergartner"))
    if re.search(r"\bpre-?k|preschool|vpk|\b3[- ]year|\b4[- ]year", t) and not any(g == -1 for g, _ in children):
        children.append((-1, "pre-K"))
    if re.search(r"\binfant|toddler|newborn|baby|daycare|day care|child ?care", t) and not any(g == -2 for g, _ in children):
        children.append((-2, "infant/toddler"))
    if re.search(r"\bhigh school|\bhighschool", t) and not children:
        children.append((9, "high school"))
    if re.search(r"\bmiddle school", t) and not children:
        children.append((6, "middle school"))
    if re.search(r"\belementary", t) and not children:
        children.append((1, "elementary"))
    if not children and pending == "children":
        # "3", "3rd", "grade 3", "third", "a kindergartner and a 3rd grader" are handled above or here.
        m = re.fullmatch(r"(?:grade\s*)?(\d{1,2})(?:st|nd|rd|th)?(?:\s*grade)?", t)
        if m and 0 <= int(m.group(1)) <= 12:
            children.append((int(m.group(1)), f"grade {int(m.group(1))}"))
        else:
            words = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12}
            m = re.search(r"\b(" + "|".join(words) + r")\b(?:\s*grade)?", t)
            if m:
                children.append((words[m.group(1)], f"grade {words[m.group(1)]}"))
    if children:
        dedup: dict[int, str] = {}
        for grade, label in children:
            dedup.setdefault(grade, label)
        child_rx = r"\d{1,2}\s*(?:year|yr)|grade|kindergart|kinder|pre-?k|preschool|infant|toddler|high school|middle school|elementary|baby|newborn"
        adding = bool(re.search(r"\b(also|another|as well|other child|second child)\b", t))
        correcting = bool(re.search(r"\b(actually|instead|now in|going into)\b", t))
        if _negated(t, child_rx) and not adding:
            op = "remove"
        elif correcting and not adding and len(dedup) == 1 and prior is not None and len(prior.children) <= 1:
            op = "replace"
        else:
            op = _list_op(t, child_rx, adding_extra_child=adding)
        kwargs["children"] = ChildUpdate(op=op, children=[Child(grade=g, label=label) for g, label in dedup.items()])  # type: ignore[arg-type]

    cat_rx = {
        "public": r"\bpublic\b",
        "charter": r"\bcharters?\b",
        "private": r"\b(?:private|catholic|christian|jewish|religious|parochial)\b",
        "early_childhood": r"\b(?:daycare|day care|child ?care|preschool|head start|infants?|toddlers?)\b",
    }
    cat_add, cat_remove = [], []
    for name, rx in cat_rx.items():
        if not re.search(rx, t):
            continue
        if _negated(t, rx):
            cat_remove.append(name)
        else:
            cat_add.append(name)
    if cat_add or cat_remove:
        mention = "|".join(rx for name, rx in cat_rx.items() if name in cat_add or name in cat_remove)
        if cat_add and not cat_remove:
            kwargs["categories"] = ListUpdate(op=_list_op(t, mention), values=cat_add)  # type: ignore[arg-type]
        elif cat_remove and not cat_add:
            kwargs["categories"] = ListUpdate(op="remove", values=cat_remove)
        elif _replace_intent(t, mention):
            kwargs["categories"] = ListUpdate(op="replace", values=cat_add)
        else:
            kwargs["categories"] = ListUpdate(op="add", values=cat_add)

    if "radius_miles" not in clears:
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:miles?|mi)\b", t)
        if m:
            miles = float(m.group(1))
            if 0 < miles <= 40:
                kwargs["radius_miles"] = miles
        elif "walking" in t:
            kwargs["radius_miles"] = 1.0
        elif re.search(r"\bclose|nearby|near me", t):
            kwargs["radius_miles"] = 3.0

    checks = {
        "academics": r"academ|best school|top rated|high.?performing|test score|a-rated|\"a\" school|grade a",
        "distance": r"\bclose\b|nearby|walk|commute|short drive",
        "small_school": r"small school|small class|smaller|intimate",
        "large_school": r"big school|large school|lots of",
        "stem": r"\bstem\b|science|technology|engineering|robotic|coding|\bmath\b",
        "arts": r"\barts?\b|music|theat|danc|performing|design",
        "language": r"bilingual|dual.?language|spanish|french|immersion|international|\bib\b",
        "magnet": r"\bmagnet\b",
        "religious": r"catholic|christian|jewish|hebrew|religious|church|faith|parochial|islamic",
        "montessori": r"montessori",
        "special_needs": r"special needs|autis|iep|\bese\b|disabilit|therap|dyslex",
        "gifted": r"gifted|advanced|honors|accelerat",
        "affordability": r"afford|cheap|\bfree\b|tuition|budget|scholarship|voucher",
        "early_childhood": r"daycare|day care|preschool|pre-?k|infant|toddler|head start",
    }
    pri_add, pri_remove = [], []
    for name, rx in checks.items():
        if _negated(t, rx):
            pri_remove.append(name)
        elif re.search(rx, t):
            pri_add.append(name)
    if pri_add and not pri_remove and "priorities" not in clears:
        mention = "|".join(checks[name] for name in pri_add)
        kwargs["priorities"] = ListUpdate(op=_list_op(t, mention), values=pri_add)  # type: ignore[arg-type]
    elif pri_remove and not pri_add:
        kwargs["priorities"] = ListUpdate(op="remove", values=pri_remove)

    kw_add, kw_remove = [], []
    for kw in ("montessori", "bilingual", "catholic", "christian", "jewish", "hebrew", "ib", "international", "magnet", "stem", "arts", "academy", "preparatory", "lutheran", "episcopal", "baptist"):
        if not re.search(rf"\b{kw}\b", t):
            continue
        label = kw.title() if kw != "ib" else "IB"
        if _negated(t, rf"\b{kw}\b"):
            kw_remove.append(label)
        else:
            kw_add.append(label)
    if kw_add and not kw_remove:
        mention = "|".join(re.escape(k.lower()) for k in kw_add)
        kwargs["keywords"] = ListUpdate(op=_list_op(t, mention), values=kw_add)  # type: ignore[arg-type]
    elif kw_remove and not kw_add:
        kwargs["keywords"] = ListUpdate(op="remove", values=kw_remove)

    m = re.search(r"\b([abc])[- ]rated|at least (?:an? )?([abc])\b|only (?:an? )?([abc]) schools", t)
    if m and "min_fl_grade" not in clears:
        kwargs["min_fl_grade"] = (m.group(1) or m.group(2) or m.group(3)).upper()

    if re.search(r"\b(on (?:the|my) way to work|on (?:my|the) commute|along (?:my|the) commute|between home and work)\b", t):
        kwargs["prefer_near"] = "route"
    elif re.search(r"\b(clos(?:e|er) to (?:my )?(?:work|office|job)|near (?:my )?(?:work|office|job))\b", t):
        kwargs["prefer_near"] = "work"
    elif re.search(r"\b(clos(?:e|er) to home|near home)\b", t):
        kwargs["prefer_near"] = "home"

    household = _fallback_household(t)
    if household is not None:
        kwargs["household"] = household
    if re.search(r"\b(forget (?:my|our|the) (?:household|family|work and schedule))\b", t):
        clears.append("household")

    if clears:
        kwargs["clear_fields"] = [c for c in clears if c not in ("location_text",) or "location_text" not in kwargs]
        kwargs["clear_fields"] = [c for c in kwargs["clear_fields"] if not (c == "radius_miles" and "radius_miles" in kwargs)]
    return PreferencePatch(**kwargs)


_ACTIVITY_WORDS: dict[str, str] = {
    # label regex -> interest
    "ballet": "arts", "dance": "arts", "piano": "arts", "violin": "arts", "guitar": "arts", "music": "arts",
    "choir": "arts", "theater": "arts", "theatre": "arts", "drama": "arts", "art class": "arts", "painting": "arts",
    "robotics": "stem", "coding": "stem", "chess": "stem", "science club": "stem", "math club": "stem",
    "spanish lessons": "language", "french lessons": "language", "mandarin": "language", "hebrew school": "language",
    "soccer": "sports", "swim": "sports", "swimming": "sports", "gymnastics": "sports", "karate": "sports",
    "taekwondo": "sports", "jiu[- ]?jitsu": "sports", "tennis": "sports", "basketball": "sports", "baseball": "sports",
    "football": "sports", "volleyball": "sports", "track": "sports", "cheer": "sports", "martial arts": "sports",
}
_PLACE_RX = r"([a-z][a-z .'-]{2,40}?)(?:[,.;]|\s+(?:and|with|for|my|our|we|on|every|twice|after|at|until|till|looking|want|need)\b|$)"


def _fallback_household(t: str) -> Optional[HouseholdPatch]:
    kwargs: dict = {}
    clears: list[str] = []

    if re.search(r"\b(forget (?:my|the) (?:work|office|job)|no longer work|changed jobs|don't work there)\b", t):
        clears.append("work_location_text")
    else:
        m = re.search(
            r"\b(?:i|we|my (?:husband|wife|partner|spouse)|both)\s+(?:both\s+)?work(?:s|ing)?\s+(?:in|near|at|downtown in|out of)\s+" + _PLACE_RX,
            t,
        )
        if not m:
            m = re.search(r"\b(?:my|our) (?:office|job|work) is (?:in|near|at|downtown in)\s+" + _PLACE_RX, t)
        if not m:
            m = re.search(r"\bcommute to\s+" + _PLACE_RX, t)
        if m:
            place = m.group(1).strip(" .")
            if place not in _VAGUE_PLACES and not re.match(r"^(from|until|till|late|nights?|days?|home|full time)$", place):
                kwargs["work_location_text"] = place
        elif re.search(r"\b(?:i|we)\s+(?:both\s+)?work\s+downtown\b", t):
            kwargs["work_location_text"] = "downtown Miami"

    m = re.search(
        r"\b((?:i|we|both(?: of us)?)\s+(?:both\s+)?work(?:s|ing)?(?:\s+(?!until|till)\w+){0,3}\s+(?:until|till|past|through)\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?|night shifts?|nights|evening shifts?|work(?:ing)? (?:full[- ]time|long hours|late)|(?:late|after[- ]hours) pick-?ups?)\b",
        t,
    )
    if m:
        kwargs["work_schedule_text"] = m.group(1).strip()

    if re.search(r"\b(pick-?up (?:is )?(?:covered|handled)|grandma picks? up|no aftercare needed|don't need after ?care)\b", t):
        kwargs["needs_after_school_care"] = False
    elif re.search(
        r"\b(work(?:s|ing)?(?:\s+(?!until|till)\w+){0,3}\s+(?:until|till|past|through)\s+(?:[5-9]|1[0-2])(?::\d{2})?\s*(?:pm)?\b|late pick-?up|pick(?:ing)? (?:him|her|them|up) (?:up )?late|after-?care|after[- ]school care|extended day|both work full[- ]time|both work|need(?:s)? care (?:until|till|after))",
        t,
    ):
        kwargs["needs_after_school_care"] = True

    activities: list[ActivityPlace] = []
    interests: list[str] = []
    if re.search(r"\b(no (?:more )?activities|drop the activities|forget (?:the|their|her|his) activities)\b", t):
        clears.append("activities")
        clears.append("activity_interests")
    else:
        for word, interest in _ACTIVITY_WORDS.items():
            m = re.search(rf"\b({word})\b(?:\s+(?:class|classes|lessons|practice|team|club))?(?:\s+(?:in|at|near)\s+{_PLACE_RX})?", t)
            if not m:
                continue
            label = re.sub(r"\s+", " ", m.group(1)).strip()
            place = m.group(2).strip(" .") if m.lastindex and m.lastindex >= 2 and m.group(2) else None
            if place in _VAGUE_PLACES:
                place = None
            if label.lower() == "track" and not re.search(r"\btrack (?:team|practice|and field)\b", t):
                continue
            if label.lower() in {"music", "dance", "art class"} and re.search(rf"\b(?:school|academy|program)s? (?:with|for|that (?:has|offers)) (?:strong |good )?{label}", t):
                continue  # a program wish, already captured as a priority
            if not any(a.label.lower() == label.lower() for a in activities):
                activities.append(ActivityPlace(label=label, location_text=place))
            if interest not in interests:
                interests.append(interest)
    if activities:
        removing = _negated(t, "|".join(re.escape(a.label.lower()) for a in activities))
        op = "remove" if removing else "add"
        kwargs["activities"] = ActivityUpdate(op=op, activities=activities)  # type: ignore[arg-type]
        if not removing:
            kwargs["activity_interests"] = ListUpdate(op="add", values=interests)
    if clears:
        kwargs["clear_fields"] = clears
    if not kwargs:
        return None
    return HouseholdPatch(**kwargs)


def _prefs_stated(prefs: Preferences) -> bool:
    return bool(
        prefs.location_text
        or prefs.children
        or prefs.categories
        or prefs.priorities
        or prefs.keywords
        or prefs.radius_miles
        or prefs.min_fl_grade
        or prefs.notes
    )


_TOPIC_FIELD: dict[str, str] = {
    "children": "children",
    "location": "location_text",
    "categories": "categories",
    "priorities": "priorities",
    "radius": "radius_miles",
    "work": "household",
    "min_fl_grade": "min_fl_grade",
}


def _enforce_explicit(patch: PreferencePatch, message: str, prior: Optional[Preferences], pending: Optional[str] = None) -> PreferencePatch:
    """Regex catches explicit resets, clears, and replacements the model sometimes omits."""
    fb = _fallback_patch(message, prior, pending)
    data = patch.model_dump()
    if fb.reset:
        data["reset"] = True
        if set(fb.model_fields_set) == {"reset"} and len(message.split()) <= 5:
            # A bare "start over": the model sometimes re-adds constraints from history.
            data = PreferencePatch(reset=True).model_dump()
    # A short reply to a question is an answer, never a fresh search. It also cannot
    # introduce constraints the parent did not type: keep only the pending topic's
    # field plus anything the regex independently found in the same words.
    if pending and len(message.split()) <= 6 and not fb.reset:
        data["reset"] = False
        allowed = {_TOPIC_FIELD.get(pending)} | set(fb.model_fields_set)
        for field in ("location_text", "radius_miles", "min_fl_grade", "notes", "prefer_near", "categories", "priorities", "keywords", "children", "household"):
            if field not in allowed:
                data[field] = None
        if "clear_fields" not in fb.model_fields_set:
            data["clear_fields"] = [c for c in data["clear_fields"] if c == _TOPIC_FIELD.get(pending)]
    # Bare answers the model sometimes leaves out.
    if pending == "children" and patch.children is None and fb.children is not None:
        data["children"] = fb.children.model_dump()
    if pending == "radius" and patch.radius_miles is None and fb.radius_miles is not None and "radius_miles" not in fb.clear_fields:
        data["radius_miles"] = fb.radius_miles
    if pending == "categories" and patch.categories is None and fb.categories is not None:
        data["categories"] = fb.categories.model_dump()
    if pending == "min_fl_grade" and patch.min_fl_grade is None and fb.min_fl_grade is not None:
        data["min_fl_grade"] = fb.min_fl_grade
    data["clear_fields"] = list(dict.fromkeys([*patch.clear_fields, *fb.clear_fields]))
    for field in ("categories", "priorities", "keywords", "children"):
        fb_upd = getattr(fb, field)
        if fb_upd is None or fb_upd.op not in {"remove", "replace", "clear"}:
            continue
        current = getattr(patch, field)
        if current is None or current.op == "add":
            data[field] = fb_upd.model_dump()
    if patch.prefer_near is None and fb.prefer_near is not None:
        data["prefer_near"] = fb.prefer_near
    # The regex strips work/activity places before looking for the home area, so when the
    # model drops a bare "near X" on a turn with no stored home, trust the regex.
    if (
        not data.get("location_text")
        and fb.location_text
        and "location_text" not in data["clear_fields"]
        and not (prior and prior.location_text)
    ):
        data["location_text"] = fb.location_text
    if fb.household is not None:
        if patch.household is None:
            data["household"] = fb.household.model_dump()
        else:
            hh = patch.household.model_dump()
            hh["clear_fields"] = list(dict.fromkeys([*patch.household.clear_fields, *fb.household.clear_fields]))
            if hh.get("needs_after_school_care") is None and fb.household.needs_after_school_care is not None:
                hh["needs_after_school_care"] = fb.household.needs_after_school_care
            data["household"] = hh
    # The model sometimes pairs a clear with the replacement value. That is a replace,
    # not a clear, unless the regex also saw the parent drop the constraint.
    for field in ("location_text", "radius_miles", "min_fl_grade", "categories", "priorities", "keywords", "children", "prefer_near"):
        value = data.get(field)
        if isinstance(value, dict):
            value = value.get("values") if value.get("op") in {"add", "replace"} else None
        if field in data["clear_fields"] and value not in (None, [], "") and field not in fb.clear_fields:
            data["clear_fields"] = [c for c in data["clear_fields"] if c != field]
    return PreferencePatch.model_validate(data)


def extract_patch(
    message: str,
    history: list[ChatMessage],
    prior: Optional[Preferences],
    household: Optional[Household] = None,
    pending: Optional[str] = None,
) -> tuple[PreferencePatch, bool]:
    client = _get_client()
    if not client:
        return _fallback_patch(message, prior, pending), False
    msgs: list[dict[str, str]] = [{"role": "system", "content": EXTRACT_SYSTEM}]
    if pending:
        msgs.append({"role": "system", "content": f"The assistant's last message asked about: {pending}. A short reply answers that."})
    if prior is not None and _prefs_stated(prior):
        msgs.append({"role": "system", "content": "Stored preferences (do not echo unchanged fields): " + prior.model_dump_json()})
    if household is not None and not household.is_empty():
        msgs.append({"role": "system", "content": "Stored household (remembered across searches; do not re-ask or echo unchanged fields): " + household.model_dump_json(exclude_none=True)})
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
        return _enforce_explicit(PreferencePatch.model_validate(data), message, prior, pending), True
    except Exception:  # noqa: BLE001
        return _fallback_patch(message, prior, pending), False


# ----------------------------------------------------------------------------------
# Explanations
# ----------------------------------------------------------------------------------

EXPLAIN_SYSTEM = """You are a knowledgeable, warm Miami-Dade school counselor helping a parent choose among schools.
You are given the parent's preferences and a JSON list of candidate schools that were ALREADY filtered and ranked by a deterministic algorithm using verified public data (Miami-Dade County GIS, Florida DOE school grades, NCES).

Rules:
- Use ONLY facts present in the JSON. Never invent programs, test scores, tuition, reviews, or reputations.
- When a value is null, say it is not reported rather than guessing.
- Florida DOE grades (A-F) and achievement percentages exist only for public and charter schools; private and early-childhood providers have none.
- Be concrete: cite distance, grade, achievement numbers, enrollment, ratios, published programs, and FHSAA sports.
- serves_grades, when present, lists the requested grade codes this school covers (-2 infant, -1 PK, 0 K, 1-12). When more than one child was requested, say which child the school fits.
- cost, when present, is "tuition-free" for public schools, charter schools, Head Start, and Early Head Start, or "not reported" for private schools and licensed child care. Never estimate a dollar amount. When the parent asked about cost, cite this.
- household, when present, describes the family: work_label (where a parent works), work_schedule_text (their words about hours), needs_after_school_care, and activities (what the children already do, with a place when known). Use it to frame the fit; never ask for it again.
- detour_miles is how many miles the school adds to the home-to-work trip (0 means it is on the way). work_miles is distance from work. activity_detours lists the same for each activity place. Cite these numbers when present.
- after_school_care true means a county-licensed after-school or extended-care provider operates on that campus; after_school_care_names lists them. Mention it only when true. Hours of operation, bell times, and bus routes are not in the data: say "hours not reported" when the schedule matters.
- programs, when present, are magnet and parent-choice program names published by Miami-Dade County Public Schools. Cite those names. Do not invent programs that are not in the list. A school with no programs list has none in that directory; do not treat that as proof it lacks a theme.
- eligibility and admission_note on a program are catalog rules, not a determination that a particular child qualifies. Magnet admission is an application and random selection; living in the attendance boundary does not admit the student. Choice programs give in-boundary students priority for remaining seats, and transportation is typically not provided.
- assigned_zones, when present, means the home point falls inside that school's published attendance polygon for the listed level and grades. Absence of assigned_zones means this address is not inside a stored boundary for that school, not that the district has no boundary.
- religious, denomination, nonprofit, accreditation, and scholarship_programs come from the school's own annual Florida private-school survey. Say "school-reported" and cite directory_survey_year. A scholarship participation flag is not a tuition amount and does not mean a seat is available. directory_outdated true means the survey year is 2023 or earlier; do not treat those facts as current.
- academics, when present, is Civil Rights Data Collection 2021-22 enrollment: ap_enrollment, ap_math, ap_science, ap_compsci, ap_language, ib_enrollment, gifted_enrollment. A number is students enrolled, not a promise about the current year. Null means that count was not reported. Do not say a school "does not offer" AP or gifted when the count is null.
- sports, when present, are FHSAA interscholastic teams (sport and team, such as Boys or Girls) for member high schools. Cite only sports in that list. If sports is absent and the school serves grade 9 or above, say it is not in the FHSAA directory. For elementary and middle schools, say FHSAA covers high-school sports only. Clubs, and sports outside that directory, are not in the data.
- Mention real tradeoffs (farther away, lower grade, larger size, no state data, etc.).
- Keep each 'why' to 1-2 sentences and each 'tradeoffs' to one sentence.
- Each candidate has a pin number, 1 through N, in the order given. Those numbers are the map pins. Pin 1 is the top pick. Do not promote another school ahead of it.
- The summary must name every pin by its number and school name, in that order, in one short conversational paragraph. Do not skip a pin or change the order. Use only facts in the JSON.

Conversation control (the payload carries these; follow them exactly):
- known: topics the parent has already covered. Never ask about them and never restate them as questions.
- changes: the exact list of what this turn changed. When non-empty, open the summary with one short clause that restates THOSE items in your own words; never mention a change that is not in the list. When empty, do not claim anything changed.
- stage: "preliminary" means only the grade or only the place is known. Say these are first matches and name the one missing thing that would sharpen them. "refined" means both are known; speak normally.
- ask_about: when null, follow_up MUST be null. When set, follow_up is exactly ONE question about that topic and nothing else, phrased naturally. Suggested wording is in ask_text; you may reword it but keep the topic.

Return ONLY JSON:
{
  "summary": string,                // a short paragraph that names map pins 1 through N in order
  "follow_up": string|null,         // see ask_about
  "explanations": [ {"school_id": int, "why": string, "tradeoffs": string} ]  // one per candidate, same order
}"""


def _compact(s: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "id", "name", "category", "subtype", "address", "city", "grades_text", "enrollment", "capacity",
        "distance_miles", "fl_grade", "fl_grade_prev1", "fl_grade_prev2", "ela_ach", "math_ach", "sci_ach", "ss_ach",
        "grad_rate", "pct_points", "pct_econ_disadvantaged", "student_teacher_ratio", "frl_pct", "magnet",
        "fl_title_i", "year_established", "coed", "license_expires", "website", "serves_grades", "cost",
        "detour_miles", "work_miles", "activity_detours", "programs", "academics", "sports",
        "assigned_zones", "attendance_levels", "religious", "denomination", "nonprofit", "accreditation",
        "scholarship_programs", "directory_survey_year", "directory_outdated",
    )
    out = {k: s.get(k) for k in keep if s.get(k) not in (None, [], "")}
    if out.get("programs"):
        out["programs"] = [
            {"name": p.get("name"), "kind": p.get("kind"), "eligibility": p.get("eligibility"), "admission_note": p.get("admission_note")}
            for p in out["programs"][:12]
        ]
    if out.get("assigned_zones"):
        out["assigned_zones"] = [
            {"level": z.get("level"), "grade_low": z.get("grade_low"), "grade_high": z.get("grade_high")}
            for z in out["assigned_zones"][:3]
        ]
    if out.get("sports"):
        out["sports"] = [{"sport": p.get("sport"), "team": p.get("team")} for p in out["sports"][:16]]
    if s.get("after_school_care"):
        out["after_school_care"] = True
        out["after_school_care_names"] = s.get("after_school_care_names") or []
    if s.get("ranking"):
        out["rank_reasons"] = s["ranking"].get("reasons")
        out["rank_score"] = s["ranking"].get("score")
    return out


def _fmt(v, suffix="") -> str:
    return "not reported" if v is None else f"{v}{suffix}"


def _household_payload(household: Optional[Household], work_label: Optional[str]) -> Optional[dict[str, Any]]:
    if household is None or household.is_empty():
        return None
    out: dict[str, Any] = {}
    if household.work_location_text:
        out["work_label"] = work_label or household.work_location_text
    if household.work_schedule_text:
        out["work_schedule_text"] = household.work_schedule_text
    if household.needs_after_school_care is not None:
        out["needs_after_school_care"] = household.needs_after_school_care
    if household.activities:
        out["activities"] = [a.model_dump(exclude_none=True) for a in household.activities]
    if household.activity_interests:
        out["activity_interests"] = list(household.activity_interests)
    return out


def _fallback_explain(
    prefs: Preferences,
    schools: list[dict[str, Any]],
    household: Optional[Household] = None,
    work_label: Optional[str] = None,
    changes: Optional[list[str]] = None,
    question: Optional[Question] = None,
    stage: Stage = "refined",
    origin: Optional[tuple[float, float]] = None,
) -> tuple[str, Optional[str], list[SchoolExplanation]]:
    exps: list[SchoolExplanation] = []
    needs_care = bool(household and household.needs_after_school_care)
    sports = bool(household and "sports" in household.activity_interests)
    for s in schools:
        bits = []
        if s.get("distance_miles") is not None:
            bits.append(f"{s['distance_miles']:.1f} miles from your location")
        if s.get("detour_miles") is not None:
            if s["detour_miles"] <= 0.5:
                bits.append("on the way to work")
            else:
                bits.append(f"adds {s['detour_miles']:.1f} miles to your commute")
        elif s.get("work_miles") is not None:
            bits.append(f"{s['work_miles']:.1f} miles from work")
        for entry in s.get("activity_detours") or []:
            if entry.get("detour_miles") is not None and entry["detour_miles"] <= 0.5:
                bits.append(f"on the way to {entry['label']}")
            else:
                bits.append(f"{entry['miles']:.1f} miles from {entry['label']}")
        if s.get("after_school_care"):
            names = s.get("after_school_care_names") or []
            bits.append((names[0] + " runs" if names else "a county-licensed provider runs") + " after-school care on campus")
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
            bits.append("matches " + ", ".join(h.split(":")[-1] for h in hits[:2]))
        program_names = [p.get("name") for p in (s.get("programs") or []) if p.get("name")]
        if program_names:
            bits.append("programs include " + ", ".join(program_names[:2]))
        academics = s.get("academics") or {}
        if academics.get("ap_enrollment"):
            bits.append(f"{academics['ap_enrollment']} students enrolled in AP in 2021-22")
        if academics.get("gifted_enrollment"):
            bits.append(f"{academics['gifted_enrollment']} students in gifted or talented in 2021-22")
        sport_names = []
        for row in s.get("sports") or []:
            label = row.get("sport")
            if label and label not in sport_names:
                sport_names.append(label)
        if sports and sport_names:
            bits.append("FHSAA sports include " + ", ".join(sport_names[:3]))
        if s.get("cost") == "tuition-free":
            bits.append("tuition-free")
        why = f"{s['name']} is " + "; ".join(bits) + "." if bits else f"{s['name']} matches your grade and area filters."
        trade = []
        if s.get("cost") == "not reported":
            trade.append("tuition is not reported")
        if needs_care and not s.get("after_school_care") and s.get("subtype") not in ("daycare", "head_start", "early_head_start"):
            trade.append("after-school care and hours are not reported")
        if sports and not sport_names and (s.get("grade_high") or -1) >= 9:
            trade.append("this school is not in the FHSAA sports directory")
        elif sports and not sport_names:
            trade.append("FHSAA lists high-school sports only")
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
    summary = ""
    if changes:
        summary = "Got it: " + "; ".join(c[0].lower() + c[1:] for c in changes) + ". "
    pins = "; ".join(f"pin {i} is {s['name']}" for i, s in enumerate(schools, start=1))
    summary += (
        f"I filtered Miami-Dade providers by your criteria using distance, Florida DOE results, size, and program signals. On the map, {pins}."
        if pins
        else "I filtered Miami-Dade providers by your criteria, and none matched."
    )
    if stage == "preliminary":
        summary += " " + discovery.preliminary_note(prefs, household, origin)
    if "affordability" in prefs.priorities:
        summary += " Public, charter, and Head Start providers are tuition-free. Private school and child-care prices are not published, so they are not estimated."
    if household and household.work_location_text:
        summary += f" Distances account for your commute to {work_label or household.work_location_text}."
    if needs_care:
        summary += " On-campus after-school care comes from county child-care licenses; school hours are not published."
    return summary, (question.text if question else None), exps


def explain(
    prefs: Preferences,
    schools: list[dict[str, Any]],
    household: Optional[Household] = None,
    work_label: Optional[str] = None,
    changes: Optional[list[str]] = None,
    question: Optional[Question] = None,
    stage: Stage = "refined",
    known: Optional[set[str]] = None,
    origin: Optional[tuple[float, float]] = None,
) -> tuple[str, Optional[str], list[SchoolExplanation], bool]:
    """Explain ranked rows. The follow-up question is decided by the caller
    (discovery); the model may only reword it, never add or swap one."""
    client = _get_client()
    if not client or not schools:
        s, f, e = _fallback_explain(prefs, schools, household, work_label, changes, question, stage, origin)
        return s, f, e, False
    payload: dict[str, Any] = {
        "preferences": prefs.model_dump(exclude_none=True),
        "candidates": [{"pin": i, **_compact(s)} for i, s in enumerate(schools, start=1)],
        "stage": stage,
        "known": sorted(known or []),
        "changes": list(changes or []),
        "ask_about": question.topic if question else None,
        "ask_text": question.text if question else None,
    }
    hh = _household_payload(household, work_label)
    if hh:
        payload["household"] = hh
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
            _, _, fb = _fallback_explain(prefs, [s for s in schools if s["id"] not in have], household, work_label)
            exps.extend(fb)
        order = {s["id"]: i for i, s in enumerate(schools)}
        exps.sort(key=lambda e: order.get(e.school_id, 99))
        summary = (data.get("summary") or "").strip()
        if not summary:
            summary, _, _ = _fallback_explain(prefs, schools, household, work_label, changes, question, stage, origin)
        # Gate the question: none when discovery has nothing to ask; the template when the model went quiet.
        follow: Optional[str] = None
        if question is not None:
            model_q = (data.get("follow_up") or "").strip()
            follow = model_q if model_q.endswith("?") and len(model_q) <= 220 else question.text
        return summary, follow, exps, True
    except Exception:  # noqa: BLE001
        s, f, e = _fallback_explain(prefs, schools, household, work_label, changes, question, stage, origin)
        return s, f, e, False


# ----------------------------------------------------------------------------------
# One-school briefing (the profile "Ask AI" button)
# ----------------------------------------------------------------------------------

DESCRIBE_SYSTEM = """You are a knowledgeable, warm Miami-Dade school counselor. A parent opened one school and asked what it is like.
You are given a JSON object of verified public data for that school only (Miami-Dade County GIS, Florida DOE school grades, NCES, and the other catalogs named in the fields).

Rules:
- Use ONLY facts present in the JSON. Never invent programs, test scores, tuition, reviews, hours, bus routes, or reputations.
- When a value is absent, say it is not reported rather than guessing.
- Florida DOE grades and achievement percentages exist only for public and charter schools. If category is private or early_childhood, say Florida does not publish school grades or test results for that type of provider.
- Be concrete: cite the address, grades served, miles_from_selected_location when present (say "from your location", never "point of interest"), the state grade, achievement numbers as percents such as 71%, enrollment or capacity, student-teacher ratio, published programs, CRDC counts, and FHSAA sports.
- A gifted, AP, or IB count is a 2021-22 headcount. Do not describe it as a focus, culture, or reputation.
- Mention a topic only when its field is in the JSON. When do_not_mention is present, those topics must not appear at all, including to say they are missing or not offered.
- magnet false only means NCES did not flag a magnet. Do not turn that into a claim about choice admission.
- Write plain sentences. No markdown, links, headings, or bullet lists.
- Do not add a closing judgment. Avoid words such as overall, excellent, supportive, well-rounded, or significant.
- cost is "tuition-free" for public schools, charter schools, Head Start, and Early Head Start, or "not reported" for private schools and licensed child care. Never estimate a dollar amount.
- programs, when present, are magnet and parent-choice program names published by Miami-Dade County Public Schools. Cite those names. Do not invent programs that are not in the list.
- eligibility and admission_note are catalog rules, not a determination that a particular child qualifies. Living in the attendance boundary does not admit a student to a magnet.
- assigned_zones, when present, means the parent's location falls inside that school's published attendance polygon. Say so, and say boundary residence is not magnet or choice admission.
- religious, denomination, nonprofit, accreditation, and scholarship_programs come from the school's own Florida private-school survey. Say "school-reported" and cite directory_survey_year when present. A scholarship flag is not a tuition amount.
- academics, when present, is Civil Rights Data Collection 2021-22 enrollment. A number is students enrolled that year. Do not say a school "does not offer" AP or gifted when the count is absent.
- sports, when present, are FHSAA interscholastic teams. Cite only sports in that list.
- after_school_care true means a county-licensed provider operates on campus. Hours are not in the data.
- Write 2 to 4 short paragraphs of plain prose a parent can read. Cover what the school is and where, who it serves, the academic record or why none is published, then programs, sports, attendance, and cost when those fields exist.
- Do not give a ranked recommendation and do not ask the parent a follow-up question.

Return ONLY JSON: {"answer": string}"""


_KIND = {
    "traditional": "district public school",
    "charter": "charter school",
    "private": "private school",
    "daycare": "licensed child-care provider",
    "head_start": "Head Start provider",
    "early_head_start": "Early Head Start provider",
    "alternative": "alternative school",
    "special_center": "special education center",
    "primary_learning_center": "primary learning center",
    "virtual": "virtual school",
}


def _pct(value: Any) -> Optional[str]:
    if value is None:
        return None
    return f"{round(float(value))}%"


def _grade_span(school: dict[str, Any]) -> str:
    from ..db import grade_label

    low, high = school.get("grade_low"), school.get("grade_high")
    if low is not None and high is not None:
        start, end = grade_label(low), grade_label(high)
        return start if start == end else f"{start}–{end}"
    return school.get("grades_text") or "grades not reported"


def _tuition_label(school: dict[str, Any]) -> str:
    if school.get("cost"):
        return school["cost"]
    if school.get("category") in ("public", "charter") or school.get("subtype") in ("head_start", "early_head_start"):
        return "tuition-free"
    return "not reported"


def _brief_payload(school: dict[str, Any]) -> dict[str, Any]:
    payload = _compact({**school, "cost": _tuition_label(school)})
    if payload.get("distance_miles") is not None:
        payload["miles_from_selected_location"] = payload.pop("distance_miles")
    for key in ("phone", "zip", "ela_gains", "math_gains", "college_career_accel", "license_number"):
        if school.get(key) not in (None, "", []):
            payload[key] = school[key]
    history = school.get("grade_history")
    if isinstance(history, dict) and history:
        years = sorted(history, key=lambda year: str(year), reverse=True)[:6]
        payload["grade_history"] = {year: history[year] for year in years}
    silent: list[str] = []
    if not payload.get("programs"):
        silent.append("magnet or choice programs")
    academics = payload.get("academics") or {}
    if not academics:
        silent.append("Advanced Placement, IB, and gifted enrollment")
    else:
        if not academics.get("ap_enrollment"):
            silent.append("Advanced Placement")
        if not academics.get("ib_enrollment"):
            silent.append("IB")
        if not academics.get("gifted_enrollment"):
            silent.append("gifted enrollment")
    if not payload.get("sports"):
        silent.append("sports")
    if silent:
        payload["do_not_mention"] = silent
    return payload


def _fallback_describe(school: dict[str, Any]) -> str:
    name = school.get("name") or "This provider"
    kind = _KIND.get(school.get("subtype") or "")
    if not kind:
        kind = {
            "public": "public school",
            "charter": "charter school",
            "private": "private school",
            "early_childhood": "early childhood provider",
        }.get(school.get("category"), "school")
    place = ", ".join(
        part
        for part in (
            school.get("address"),
            " ".join(bit for bit in (school.get("city"), school.get("zip")) if bit) or None,
        )
        if part
    )
    opening = f"{name} is a {kind}" + (f" at {place}." if place else ".")
    if school.get("distance_miles") is not None:
        opening += f" It is {float(school['distance_miles']):.1f} miles from your location."
    if school.get("phone"):
        opening += f" Phone: {school['phone']}."

    facts = [f"It serves {_grade_span(school)}."]
    if school.get("enrollment"):
        facts.append(f"Enrollment is {int(school['enrollment']):,}.")
    elif school.get("capacity"):
        facts.append(f"Licensed capacity is {int(school['capacity']):,}.")
    if school.get("student_teacher_ratio"):
        facts.append(f"The student-teacher ratio is {round(float(school['student_teacher_ratio']))}:1.")
    if school.get("frl_pct") is not None:
        facts.append(f"{_pct(school['frl_pct'])} of students are reported as eligible for free or reduced-price lunch.")
    if school.get("year_established"):
        facts.append(f"It was established in {school['year_established']}.")
    if school.get("coed") == "coed":
        facts.append("Enrollment is co-ed.")
    elif school.get("coed") in ("boys", "girls"):
        facts.append(f"It enrolls {school['coed']}.")
    if school.get("magnet"):
        facts.append("NCES lists it as a magnet school.")

    paragraphs = [opening, " ".join(facts)]
    category = school.get("category")
    if category in ("public", "charter") and school.get("fl_grade"):
        academic = [f"The Florida DOE 2025-26 school grade is {school['fl_grade']}."]
        if school.get("fl_grade_prev1"):
            academic.append(f"The prior-year grade was {school['fl_grade_prev1']}.")
        scores = []
        for label, key in (
            ("ELA proficiency", "ela_ach"),
            ("math proficiency", "math_ach"),
            ("science", "sci_ach"),
            ("social studies", "ss_ach"),
            ("ELA learning gains", "ela_gains"),
            ("math learning gains", "math_gains"),
            ("graduation rate", "grad_rate"),
            ("college and career acceleration", "college_career_accel"),
        ):
            shown = _pct(school.get(key))
            if shown:
                scores.append(f"{label} {shown}")
        if scores:
            academic.append("Reported results: " + "; ".join(scores) + ".")
        if school.get("pct_points") is not None:
            academic.append(f"It earned {_pct(school['pct_points'])} of possible accountability points.")
        if school.get("pct_econ_disadvantaged") is not None:
            academic.append(f"{_pct(school['pct_econ_disadvantaged'])} of students are economically disadvantaged.")
        if school.get("fl_title_i"):
            academic.append("It is a Title I school.")
        paragraphs.append(" ".join(academic))
    elif category in ("public", "charter"):
        paragraphs.append("No 2025-26 Florida DOE school grade was published for this school.")
    else:
        unpublished = "private schools" if category == "private" else "early childhood providers"
        paragraphs.append(
            f"Florida does not publish school grades or test results for {unpublished}. "
            "The details here come from Miami-Dade County's public directory."
        )

    extras: list[str] = []
    programs = [p.get("name") for p in (school.get("programs") or []) if p.get("name")]
    if programs:
        extras.append("M-DCPS magnet and choice programs include " + ", ".join(programs[:8]) + ".")
        notes = [p.get("admission_note") for p in school.get("programs") or [] if p.get("admission_note")]
        if notes:
            extras.append(notes[0])
    academics = school.get("academics") or {}
    enrolled = []
    for label, key in (("Advanced Placement", "ap_enrollment"), ("the IB diploma", "ib_enrollment"), ("gifted and talented programs", "gifted_enrollment")):
        if academics.get(key):
            enrolled.append(f"{int(academics[key]):,} students in {label}")
    if enrolled:
        extras.append("In the 2021-22 Civil Rights Data Collection, this school reported " + "; ".join(enrolled) + ".")
    sports: list[str] = []
    for row in school.get("sports") or []:
        label = row.get("sport")
        if not label:
            continue
        if row.get("team"):
            label = f"{label} ({str(row['team']).lower()})"
        if label not in sports:
            sports.append(label)
    if sports:
        extras.append("FHSAA sports include " + ", ".join(sports[:12]) + ".")
    zones = school.get("assigned_zones") or []
    if zones:
        levels = " and ".join(zone.get("level") for zone in zones if zone.get("level"))
        extras.append(
            f"Your location is inside this school's published {levels} attendance area. "
            "Living in the boundary is not the same as admission to a magnet or choice program."
        )
    elif school.get("attendance_levels"):
        extras.append("This campus has a published " + " and ".join(school["attendance_levels"]) + " attendance area.")
    if school.get("religious") is True:
        faith = f": {school['denomination']}" if school.get("denomination") else ""
        year = f" ({school['directory_survey_year']} survey)" if school.get("directory_survey_year") else ""
        extras.append(f"The school reported a religious affiliation{faith}{year}.")
    elif school.get("religious") is False:
        extras.append("The school reported that it is not religious.")
    if school.get("accreditation"):
        extras.append(f"School-reported accreditation: {school['accreditation']}.")
    if school.get("scholarship_programs"):
        extras.append(
            "It reported participating in " + ", ".join(school["scholarship_programs"]) + ". That is not a tuition amount."
        )
    cost = _tuition_label(school)
    if cost == "tuition-free":
        extras.append("This provider is tuition-free.")
    else:
        extras.append("Tuition is not reported.")
    if school.get("after_school_care"):
        names = school.get("after_school_care_names") or []
        who = names[0] if names else "A county-licensed provider"
        extras.append(f"{who} runs after-school care on this campus. Hours are not reported.")
    if school.get("license_number"):
        expiry = f", listed expiration {school['license_expires']}" if school.get("license_expires") else ""
        extras.append(f"DCF license {school['license_number']}{expiry}.")
    if extras:
        paragraphs.append(" ".join(extras))
    return "\n\n".join(paragraphs)


def describe_school(school: dict[str, Any]) -> tuple[str, bool]:
    """A grounded profile of one school. Falls back to the public-record sentences without a key."""
    fallback = _fallback_describe(school)
    client = _get_client()
    if not client:
        return fallback, False
    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": DESCRIBE_SYSTEM},
                {"role": "user", "content": json.dumps(_brief_payload(school))},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        answer = (data.get("answer") or "").strip()
        if len(answer) < 40:
            return fallback, False
        return answer, True
    except Exception:  # noqa: BLE001
        return fallback, False
