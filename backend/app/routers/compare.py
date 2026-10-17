from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import db
from ..schemas import CompareRequest, CompareResponse
from ..services import llm

router = APIRouter(prefix="/api", tags=["compare"])


def get_con(request: Request):
    return request.app.state.con


@router.post("/compare", response_model=CompareResponse)
def compare(req: CompareRequest, con=Depends(get_con)):
    rows = db.fetch_schools(con, ids=req.ids)
    if len(rows) < 2:
        raise HTTPException(404, "Need at least two valid school ids")
    by_id = {r["id"]: db.row_to_school(r, req.origin) for r in rows}
    schools = [by_id[i] for i in req.ids if i in by_id]
    summary, tradeoffs, used = llm.compare(req.preferences, schools)
    return CompareResponse(schools=schools, summary=summary, tradeoffs=tradeoffs, llm_used=used)
