from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..schemas import RecommendRequest, RecommendResponse
from ..services import llm, ranking
from ..services.geocode import geocode

router = APIRouter(prefix="/api", tags=["recommend"])


def get_con(request: Request):
    return request.app.state.con


@router.post("/recommend", response_model=RecommendResponse)
def recommend(req: RecommendRequest, con=Depends(get_con)):
    prefs, used_llm_extract = llm.extract_preferences(req.message, req.history, req.preferences)

    origin = req.origin
    origin_label = None
    if prefs.location_text:
        geo = geocode(prefs.location_text)
        if geo:
            origin = (geo["lat"], geo["lon"])
            origin_label = geo["label"]
    if origin and not origin_label:
        origin_label = "your selected location"

    results, considered = ranking.retrieve_and_rank(con, prefs, origin, limit=req.limit)
    summary, follow_up, explanations, used_llm_explain = llm.explain(prefs, results)

    if not results:
        summary = "I couldn't find providers matching all of those filters. Try widening the distance, removing a category, or checking the location."
        if not follow_up:
            follow_up = "Would you like me to search a wider area?"

    return RecommendResponse(
        preferences=prefs,
        origin=origin,
        origin_label=origin_label,
        summary=summary,
        follow_up=follow_up,
        results=results,
        explanations=explanations,
        candidates_considered=considered,
        llm_used=used_llm_extract or used_llm_explain,
    )
