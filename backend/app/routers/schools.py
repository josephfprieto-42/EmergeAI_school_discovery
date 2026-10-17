from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .. import db

router = APIRouter(prefix="/api/schools", tags=["schools"])


def get_con(request: Request):
    return request.app.state.con


@router.get("")
def list_schools(
    con=Depends(get_con),
    category: Optional[str] = Query(None, description="Comma-separated: public,charter,private,early_childhood"),
    grade: Optional[int] = Query(None, ge=-2, le=12, description="Child grade: -2 infant, -1 PK, 0 K, 1-12"),
    fl_grade: Optional[str] = Query(None, description="Comma-separated FLDOE letter grades e.g. A,B"),
    bbox: Optional[str] = Query(None, description="south,west,north,east"),
    q: Optional[str] = Query(None, description="Name/address search"),
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    radius: Optional[float] = Query(None, description="Miles; requires lat/lon"),
    program: Optional[str] = Query(None, description="Verified theme or type: stem, arts, language, magnet, choice, gifted"),
    religious: Optional[bool] = Query(None, description="School-reported religious schools from the Florida directory"),
    scholarship: Optional[bool] = Query(None, description="School-reported state scholarship participants"),
    assigned: Optional[bool] = Query(None, description="Only the attendance-zone school for lat/lon"),
    limit: int = Query(4000, le=5000),
):
    cats = category.split(",") if category else None
    fls = [g.strip().upper() for g in fl_grade.split(",")] if fl_grade else None
    box = None
    if bbox:
        try:
            s, w, n, e = (float(x) for x in bbox.split(","))
            box = (s, w, n, e)
        except ValueError as err:
            raise HTTPException(400, "bbox must be south,west,north,east") from err
    origin = (lat, lon) if lat is not None and lon is not None else None
    rows = db.fetch_schools(
        con, categories=cats, grade=grade, fl_grades=fls, bbox=box, q=q,
        program=program, religious=True if religious else None,
        scholarship=True if scholarship else None, limit=limit,
    )
    items = [db.row_to_school(r, origin) for r in rows]
    db.annotate_assignments(con, items, origin)
    if assigned and origin:
        items = [i for i in items if i.get("assigned_zones")]
    if origin and radius:
        items = [i for i in items if i["distance_miles"] is not None and i["distance_miles"] <= radius]
    if origin:
        items.sort(key=lambda i: i["distance_miles"])
    return {"count": len(items), "items": items}


@router.get("/{school_id}")
def get_school(school_id: int, con=Depends(get_con), lat: Optional[float] = None, lon: Optional[float] = None):
    row = db.fetch_school(con, school_id)
    if not row:
        raise HTTPException(404, "School not found")
    origin = (lat, lon) if lat is not None and lon is not None else None
    school = db.row_to_school(row, origin)
    db.attach_offerings(con, [school])
    db.annotate_assignments(con, [school], origin)
    return school
