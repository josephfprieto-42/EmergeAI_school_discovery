from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .. import sessions
from ..schemas import HouseholdState, SessionState
from ..services.discovery import TOPIC_ORDER

router = APIRouter(prefix="/api", tags=["sessions"])
TOPICS = set(TOPIC_ORDER)


def get_sessions(request: Request):
    return request.app.state.sessions


@router.get("/sessions/{session_id}", response_model=SessionState)
def read_session(session_id: str, con=Depends(get_sessions)):
    stored = sessions.get_session(con, session_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="Session not found")
    household = sessions.get_household(con, stored.get("household_id"))
    return SessionState(
        session_id=stored["id"],
        messages=stored["messages"],
        preferences=stored["preferences"],
        origin=stored["origin"],
        origin_label=stored["origin_label"],
        recommendation=stored["recommendation"],
        household_id=household["id"] if household else None,
        household=household["household"] if household else None,
        asked=[t for t in stored.get("asked", []) if t in TOPICS],
    )


@router.get("/households/{household_id}", response_model=HouseholdState)
def read_household(household_id: str, con=Depends(get_sessions)):
    stored = sessions.get_household(con, household_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="Household not found")
    return HouseholdState(
        household_id=stored["id"],
        household=stored["household"],
        work=stored["work"],
        work_label=stored["work_label"],
    )


@router.delete("/households/{household_id}", status_code=204)
def forget_household(household_id: str, con=Depends(get_sessions)):
    if not sessions.delete_household(con, household_id):
        raise HTTPException(status_code=404, detail="Household not found")
    return Response(status_code=204)


@router.delete("/sessions/{session_id}/origin", status_code=204)
def forget_origin(session_id: str, con=Depends(get_sessions)):
    if not sessions.clear_origin(con, session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return Response(status_code=204)


@router.delete("/sessions/{session_id}", status_code=204)
def remove_session(session_id: str, con=Depends(get_sessions)):
    sessions.delete_session(con, session_id)
    return Response(status_code=204)
