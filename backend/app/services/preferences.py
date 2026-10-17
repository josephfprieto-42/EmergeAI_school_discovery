"""Merge a one-turn preference patch into the stored preferences.

Omitted patch fields stay as they are. List fields change only through an
explicit add, remove, replace, or clear. `reset` starts from empty preferences
and then applies whatever else the same message stated.
"""
from __future__ import annotations

from typing import Optional, Sequence

from ..schemas import (
    ActivityInterest,
    ActivityPlace,
    ActivityUpdate,
    Category,
    Child,
    ChildUpdate,
    ClearField,
    Household,
    HouseholdPatch,
    ListUpdate,
    PreferencePatch,
    Preferences,
    Priority,
)

ACTIVITY_INTERESTS: tuple[ActivityInterest, ...] = ("arts", "stem", "language", "sports")

CATEGORIES: tuple[Category, ...] = ("public", "charter", "private", "early_childhood")
PRIORITIES: tuple[Priority, ...] = (
    "academics",
    "distance",
    "small_school",
    "large_school",
    "diversity",
    "stem",
    "arts",
    "language",
    "magnet",
    "religious",
    "montessori",
    "special_needs",
    "gifted",
    "affordability",
    "early_childhood",
)


def merge(prior: Optional[Preferences], patch: PreferencePatch) -> Preferences:
    base = Preferences() if patch.reset or prior is None else prior.model_copy(deep=True)
    stated = patch.model_fields_set

    if "location_text" in stated and patch.location_text and patch.location_text.strip():
        base.location_text = patch.location_text.strip()
    if "radius_miles" in stated and patch.radius_miles is not None:
        base.radius_miles = patch.radius_miles
    if "min_fl_grade" in stated and patch.min_fl_grade:
        base.min_fl_grade = patch.min_fl_grade
    if "notes" in stated and patch.notes and patch.notes.strip():
        base.notes = patch.notes.strip()
    if "prefer_near" in stated and patch.prefer_near:
        base.prefer_near = patch.prefer_near

    if patch.categories is not None:
        base.categories = _apply_str_list(base.categories, patch.categories, CATEGORIES)  # type: ignore[assignment]
    if patch.priorities is not None:
        base.priorities = _apply_str_list(base.priorities, patch.priorities, PRIORITIES)  # type: ignore[assignment]
    if patch.keywords is not None:
        base.keywords = _apply_keywords(base.keywords, patch.keywords)
    if patch.children is not None:
        base.children = _apply_children(base.children, patch.children)

    for field in patch.clear_fields:
        _clear(base, field)

    return _sync(base)


def _apply_str_list(current: Sequence[str], update: ListUpdate, allowed: Sequence[str]) -> list[str]:
    allow = set(allowed)
    values = [v for v in update.values if v in allow]
    if update.op == "clear":
        return []
    if update.op == "replace":
        return list(dict.fromkeys(values))
    if update.op == "remove":
        drop = set(values)
        return [item for item in current if item not in drop]
    return list(dict.fromkeys([*current, *values]))


def _apply_keywords(current: Sequence[str], update: ListUpdate) -> list[str]:
    values = [v.strip() for v in update.values if v and v.strip()]
    if update.op == "clear":
        return []
    if update.op == "replace":
        return _dedupe_ci(values)
    if update.op == "remove":
        drop = {v.lower() for v in values}
        return [item for item in current if item.lower() not in drop]
    return _dedupe_ci([*current, *values])


def _dedupe_ci(values: Sequence[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _apply_children(current: Sequence[Child], update: ChildUpdate) -> list[Child]:
    if update.op == "clear":
        return []
    if update.op == "replace":
        return list(update.children)
    if update.op == "remove":
        drop = {c.grade for c in update.children}
        return [c for c in current if c.grade not in drop]
    by_grade = {c.grade: c.model_copy() for c in current}
    for child in update.children:
        existing = by_grade.get(child.grade)
        if existing is None:
            by_grade[child.grade] = child.model_copy()
        elif child.label:
            existing.label = child.label
    return list(by_grade.values())


def _clear(prefs: Preferences, field: ClearField) -> None:
    if field == "location_text":
        prefs.location_text = None
    elif field == "radius_miles":
        prefs.radius_miles = None
    elif field == "min_fl_grade":
        prefs.min_fl_grade = None
    elif field == "notes":
        prefs.notes = None
    elif field == "categories":
        prefs.categories = []
    elif field == "priorities":
        prefs.priorities = []
    elif field == "keywords":
        prefs.keywords = []
    elif field == "children":
        prefs.children = []
    elif field == "prefer_near":
        prefs.prefer_near = None
    # "household" is handled by merge_household; the preferences object carries none of it.


def merge_household(prior: Optional[Household], patch: Optional[HouseholdPatch], reset: bool = False) -> Household:
    """Fold one turn's household delta into the stored household.

    The household is not wiped by a preferences reset: "start over" means a new
    search, not a new family. Pass reset=True only for an explicit "forget my household".
    """
    base = Household() if reset or prior is None else prior.model_copy(deep=True)
    if patch is None:
        return base
    stated = patch.model_fields_set

    if "work_location_text" in stated and patch.work_location_text and patch.work_location_text.strip():
        base.work_location_text = patch.work_location_text.strip()
    if "work_schedule_text" in stated and patch.work_schedule_text and patch.work_schedule_text.strip():
        base.work_schedule_text = patch.work_schedule_text.strip()
    if "needs_after_school_care" in stated and patch.needs_after_school_care is not None:
        base.needs_after_school_care = patch.needs_after_school_care

    if patch.activities is not None:
        base.activities = _apply_activities(base.activities, patch.activities)
    if patch.activity_interests is not None:
        base.activity_interests = _apply_str_list(base.activity_interests, patch.activity_interests, ACTIVITY_INTERESTS)  # type: ignore[assignment]

    for field in patch.clear_fields:
        if field == "work_location_text":
            base.work_location_text = None
        elif field == "work_schedule_text":
            base.work_schedule_text = None
        elif field == "needs_after_school_care":
            base.needs_after_school_care = None
        elif field == "activities":
            base.activities = []
        elif field == "activity_interests":
            base.activity_interests = []
    return base


def _apply_activities(current: Sequence[ActivityPlace], update: ActivityUpdate) -> list[ActivityPlace]:
    incoming = [a.model_copy() for a in update.activities if a.label and a.label.strip()]
    for a in incoming:
        a.label = a.label.strip()
    if update.op == "clear":
        return []
    if update.op == "replace":
        return _dedupe_activities(incoming)
    if update.op == "remove":
        drop = {a.label.lower() for a in incoming}
        return [a for a in current if a.label.lower() not in drop]
    merged: list[ActivityPlace] = [a.model_copy() for a in current]
    for a in incoming:
        existing = next((m for m in merged if m.label.lower() == a.label.lower()), None)
        if existing is None:
            merged.append(a)
            continue
        if a.location_text:
            existing.location_text = a.location_text
        if a.child_label:
            existing.child_label = a.child_label
    return merged


def _dedupe_activities(values: Sequence[ActivityPlace]) -> list[ActivityPlace]:
    out: list[ActivityPlace] = []
    seen: set[str] = set()
    for a in values:
        key = a.label.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out


def _sync(prefs: Preferences) -> Preferences:
    by_grade: dict[int, Child] = {}
    for child in prefs.children:
        existing = by_grade.get(child.grade)
        if existing is None:
            by_grade[child.grade] = child
        elif child.label and not existing.label:
            existing.label = child.label
    prefs.children = [by_grade[grade] for grade in sorted(by_grade)]
    if prefs.children:
        prefs.child_grades = [c.grade for c in prefs.children]
        prefs.child_grade = prefs.children[0].grade
    else:
        prefs.child_grades = []
        prefs.child_grade = None
    return prefs
