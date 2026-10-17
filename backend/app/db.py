from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "schoolmatch.db"

SCHOOL_SELECT = """
SELECT s.*,
       g.grade AS fl_grade, g.grade_prev1 AS fl_grade_prev1, g.grade_prev2 AS fl_grade_prev2, g.grade_history,
       g.ela_ach, g.ela_gains, g.math_ach, g.math_gains, g.sci_ach, g.ss_ach,
       g.grad_rate, g.college_career_accel, g.pct_points, g.pct_econ_disadvantaged,
       g.title_i AS fl_title_i, g.school_type AS fl_school_type,
       st.frl_pct, st.teachers_fte, st.student_teacher_ratio, st.magnet, st.title_i_schoolwide,
       st.enrollment AS nces_enrollment
FROM schools s
LEFT JOIN school_grades g ON g.school_id = s.id
LEFT JOIN school_stats st ON st.school_id = s.id
"""


def connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise RuntimeError(f"Database not found at {DB_PATH}. Run: python backend/ingest/fetch_mdc_gis.py && python backend/ingest/fetch_nces.py && python backend/ingest/build_db.py")
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def grade_label(n: int | None) -> str | None:
    if n is None:
        return None
    return {-2: "Infant", -1: "PK", 0: "K"}.get(n, str(n))


def row_to_school(row: sqlite3.Row, origin: tuple[float, float] | None = None) -> dict[str, Any]:
    d = dict(row)
    d["zip"] = d.get("zip")
    hist = d.pop("grade_history", None)
    d["grade_history"] = json.loads(hist) if hist else None
    d["grade_low_label"] = grade_label(d.get("grade_low"))
    d["grade_high_label"] = grade_label(d.get("grade_high"))
    for k in ("fl_title_i", "magnet", "title_i_schoolwide"):
        if d.get(k) is not None:
            d[k] = bool(d[k])
    if origin:
        d["distance_miles"] = round(haversine_miles(origin[0], origin[1], d["lat"], d["lon"]), 2)
    else:
        d["distance_miles"] = None
    return d


def fetch_schools(
    con: sqlite3.Connection,
    *,
    categories: Iterable[str] | None = None,
    grade: int | None = None,
    fl_grades: Iterable[str] | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    ids: Iterable[int] | None = None,
    q: str | None = None,
    limit: int = 5000,
) -> list[sqlite3.Row]:
    where: list[str] = []
    params: list[Any] = []
    cats = [c for c in (categories or []) if c]
    if cats:
        where.append(f"s.category IN ({','.join('?' * len(cats))})")
        params.extend(cats)
    if grade is not None:
        where.append("s.grade_low IS NOT NULL AND s.grade_high IS NOT NULL AND s.grade_low <= ? AND s.grade_high >= ?")
        params.extend([grade, grade])
    fls = [g for g in (fl_grades or []) if g]
    if fls:
        where.append(f"g.grade IN ({','.join('?' * len(fls))})")
        params.extend(fls)
    if bbox:
        s, w, n, e = bbox
        where.append("s.lat BETWEEN ? AND ? AND s.lon BETWEEN ? AND ?")
        params.extend([s, n, w, e])
    id_list = list(ids or [])
    if id_list:
        where.append(f"s.id IN ({','.join('?' * len(id_list))})")
        params.extend(id_list)
    if q:
        tokens = [t for t in "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in q).split() if t]
        if tokens:
            match = " ".join(f'"{t}"*' for t in tokens)
            where.append("s.id IN (SELECT rowid FROM schools_fts WHERE schools_fts MATCH ?)")
            params.append(match)
    sql = SCHOOL_SELECT
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " LIMIT ?"
    params.append(limit)
    return con.execute(sql, params).fetchall()


def fetch_school(con: sqlite3.Connection, school_id: int) -> sqlite3.Row | None:
    return con.execute(SCHOOL_SELECT + " WHERE s.id = ?", (school_id,)).fetchone()
