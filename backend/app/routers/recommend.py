from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from typing import Optional

from .. import sessions
from ..schemas import Household, RecommendRequest, RecommendResponse
from ..services import discovery, llm, ranking
from ..services.geocode import geocode
from ..services.preferences import merge, merge_household

router = APIRouter(prefix="/api", tags=["recommend"])


def get_con(request: Request):
    return request.app.state.con


def get_sessions(request: Request):
    return request.app.state.sessions


def _resolve_work(
    prior: Household,
    household: Household,
    stored_work: Optional[tuple[float, float]],
    stored_label: Optional[str],
) -> tuple[Optional[tuple[float, float]], Optional[str]]:
    """Coordinates for the workplace. Re-geocoded when the place text changed or was never stored."""
    if not household.work_location_text:
        return None, None
    changed = household.work_location_text != prior.work_location_text
    if stored_work and not changed:
        return stored_work, stored_label
    geo = geocode(household.work_location_text)
    if geo:
        return (geo["lat"], geo["lon"]), geo["label"]
    return (None, None) if changed else (stored_work, stored_label)


def _activity_points(household: Household) -> list[ranking.ActivityPoint]:
    points: list[ranking.ActivityPoint] = []
    for activity in household.activities:
        if not activity.location_text:
            continue
        geo = geocode(activity.location_text)
        if geo:
            points.append(ranking.ActivityPoint(label=activity.label, lat=geo["lat"], lon=geo["lon"]))
    return points


@router.post("/recommend", response_model=RecommendResponse)
def recommend(req: RecommendRequest, con=Depends(get_con), sessions_con=Depends(get_sessions)):
    stored = sessions.get_session(sessions_con, req.session_id) if req.session_id else None
    if stored is None:
        session_id = sessions.create_session(sessions_con, req.household_id)
        stored = sessions.get_session(sessions_con, session_id)
    if stored is None:
        raise RuntimeError("Failed to create a chat session")

    session_id = stored["id"]
    household_id = sessions.ensure_household(sessions_con, session_id, stored.get("household_id") or req.household_id)
    stored_household = sessions.get_household(sessions_con, household_id) or {"household": Household(), "work": None, "work_label": None}
    prior_household: Household = stored_household["household"]

    prior = stored["preferences"]
    last = stored.get("recommendation")
    pending = last.question.topic if last is not None and last.question is not None else None
    patch, used_llm_extract = llm.extract_patch(req.message, stored["messages"], prior, prior_household, pending=pending)
    prefs = merge(prior, patch)
    household = merge_household(prior_household, patch.household, reset="household" in patch.clear_fields)
    changes = discovery.changes(prior, prefs, prior_household, household)
    work, work_label = _resolve_work(prior_household, household, stored_household["work"], stored_household["work_label"])
    activity_points = _activity_points(household)
    # One question per topic per session. A reset starts the discovery over.
    asked: list[str] = [] if patch.reset else list(stored.get("asked") or [])
    settled = discovery.settled_by_patch(patch)
    changes = discovery.acknowledge_settled(changes, settled)
    for topic in settled:
        if topic not in asked:
            asked.append(topic)

    cleared_location = bool(prior.location_text) and not prefs.location_text
    stated_place = "location_text" in patch.model_fields_set and bool(prefs.location_text)
    origin = stored["origin"]
    origin_label = stored["origin_label"]
    if cleared_location:
        origin = None
        origin_label = None
    elif stated_place:
        geo = geocode(prefs.location_text or "")
        if geo:
            origin = (geo["lat"], geo["lon"])
            origin_label = geo["label"]
        elif req.origin:
            origin = req.origin
            origin_label = req.origin_label or "your selected location"
    elif req.origin:
        origin = req.origin
        origin_label = req.origin_label or origin_label or "your selected location"
    elif origin is None and prefs.location_text:
        geo = geocode(prefs.location_text)
        if geo:
            origin = (geo["lat"], geo["lon"])
            origin_label = geo["label"]
    if origin and not origin_label:
        origin_label = "your selected location"

    rank_prefs = prefs
    if prefs.radius_miles is None and req.radius_miles is not None:
        rank_prefs = prefs.model_copy(update={"radius_miles": req.radius_miles})

    stage = discovery.stage_for(prefs, origin)
    if stage == "discovering":
        # Nothing to rank on yet: acknowledge what we learned and ask the first thing.
        results, considered, groups = [], 0, None
        explanations = []
        used_llm_explain = False
        question = discovery.next_question(prefs, household, origin, asked, results)
        summary = discovery.intro(changes, prefs, household)
        follow_up = question.text if question else None
    else:
        results, considered, groups = ranking.retrieve_and_rank(
            con,
            rank_prefs,
            origin,
            limit=req.limit,
            household=household,
            work=work,
            activity_points=activity_points,
        )
        question = discovery.next_question(prefs, household, origin, asked, results)
        results = results[:5]
        summary, follow_up, explanations, used_llm_explain = llm.explain(
            prefs,
            results,
            household=household,
            work_label=work_label,
            changes=changes,
            question=question,
            stage=stage,
            known=discovery.known_topics(prefs, household, origin),
            origin=origin,
        )
        if not results:
            summary = "I couldn't find providers matching all of those filters. Try widening the distance, removing a category, or checking the location."
            if not follow_up:
                follow_up = "Would you like me to search a wider area?"
    if question is not None:
        question = question.model_copy(update={"text": follow_up or question.text})
        if question.topic not in asked:
            asked.append(question.topic)

    response = RecommendResponse(
        session_id=session_id,
        household_id=household_id,
        household=household,
        preferences=prefs,
        origin=origin,
        origin_label=origin_label,
        work=work,
        work_label=work_label,
        activity_points=[{"label": p.label, "lat": p.lat, "lon": p.lon} for p in activity_points],
        summary=summary,
        follow_up=follow_up,
        stage=stage,
        changes=changes,
        question=question,
        results=results,
        groups=groups,
        explanations=explanations,
        candidates_considered=considered,
        llm_used=used_llm_extract or used_llm_explain,
    )
    assistant = f"{summary}\n\n{follow_up}" if follow_up else summary
    persisted = response.model_dump(mode="json")
    stored_origin = origin if req.remember_location else None
    stored_label = origin_label if req.remember_location else None
    if not req.remember_location:
        persisted["origin"] = None
        persisted["work"] = None
        persisted["activity_points"] = []
    # The workplace text is part of the household; its coordinates follow the same consent as home.
    sessions.save_household(
        sessions_con,
        household_id,
        household,
        work if req.remember_location else None,
        work_label if req.remember_location else None,
    )
    sessions.save_turn(
        sessions_con,
        session_id,
        prefs,
        stored_origin,
        stored_label,
        req.message,
        assistant,
        persisted,
        asked=asked,
    )
    return response
