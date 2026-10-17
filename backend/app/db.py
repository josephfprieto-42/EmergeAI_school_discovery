from __future__ import annotations

import json
import math
import re
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
    sources = d.get("sources")
    if isinstance(sources, str):
        try:
            d["sources"] = json.loads(sources)
        except json.JSONDecodeError:
            d["sources"] = [sources]
    hist = d.pop("grade_history", None)
    d["grade_history"] = json.loads(hist) if hist else None
    d["grade_low_label"] = grade_label(d.get("grade_low"))
    d["grade_high_label"] = grade_label(d.get("grade_high"))
    for k in ("fl_title_i", "magnet", "title_i_schoolwide"):
        if d.get(k) is not None:
            d[k] = bool(d[k])
    d["after_school_care"] = bool(d.get("after_school_care"))
    for key in ("verified_programs", "attendance_levels", "scholarship_programs"):
        raw = d.get(key)
        if isinstance(raw, str):
            try:
                d[key] = json.loads(raw)
            except json.JSONDecodeError:
                d[key] = None
        elif raw is None:
            d[key] = [] if key != "verified_programs" else []
    if not d.get("verified_programs"):
        d["verified_programs"] = []
    if not d.get("attendance_levels"):
        d["attendance_levels"] = []
    if not d.get("scholarship_programs"):
        d["scholarship_programs"] = []
    for key in ("religious", "nonprofit", "directory_outdated"):
        if key in d and d[key] is not None:
            d[key] = bool(d[key])
    care_names = d.get("after_school_care_names")
    if isinstance(care_names, str):
        try:
            d["after_school_care_names"] = json.loads(care_names)
        except json.JSONDecodeError:
            d["after_school_care_names"] = [care_names]
    else:
        d["after_school_care_names"] = care_names or []
    if origin:
        d["distance_miles"] = round(haversine_miles(origin[0], origin[1], d["lat"], d["lon"]), 2)
    else:
        d["distance_miles"] = None
    return d


def attach_offerings(con: sqlite3.Connection, schools: list[dict[str, Any]]) -> None:
    """Add programs, coursework counts, and FHSAA sports stored for these schools."""
    if not schools:
        return
    wanted = {school["id"] for school in schools}
    programs: dict[int, list[dict[str, Any]]] = {}
    columns = {row[1] for row in con.execute("PRAGMA table_info(school_programs)")}
    if "program_name" in columns:
        note_sql = ", admission_note" if "admission_note" in columns else ", NULL"
        program_sql = f"""SELECT school_id, program_name, program_type, themes, eligibility{note_sql}
                         FROM school_programs WHERE school_id IS NOT NULL
                         ORDER BY program_type, program_name"""
    else:
        program_sql = "SELECT school_id, name, kind, NULL, NULL, NULL FROM school_programs ORDER BY kind, name"
    for sid, name, kind, themes, eligibility, admission_note in con.execute(program_sql):
        if sid not in wanted or not name:
            continue
        parsed_themes: list[str] = []
        if isinstance(themes, str) and themes:
            try:
                loaded = json.loads(themes)
            except json.JSONDecodeError:
                loaded = []
            if isinstance(loaded, list):
                parsed_themes = [str(item) for item in loaded]
        note = eligibility or ""
        programs.setdefault(sid, []).append({
            "name": name,
            "kind": kind,
            "themes": parsed_themes,
            "eligibility": eligibility,
            "admission_note": admission_note,
            "test_required": bool(re.search(r"test required", note, re.I)),
            "audition_required": bool(re.search(r"audition", note, re.I)),
        })
    academics: dict[int, dict[str, Any]] = {}
    for row in con.execute("SELECT * FROM school_academics"):
        item = dict(row)
        sid = item.pop("school_id")
        if sid in wanted and any(item.get(key) is not None for key in item if key != "year"):
            academics[sid] = item
    sports: dict[int, list[dict[str, Any]]] = {}
    for sid, sport, team in con.execute(
        "SELECT school_id, sport, team FROM school_sports ORDER BY sport, team"
    ):
        if sid in wanted:
            sports.setdefault(sid, []).append({"sport": sport, "team": team})
    for school in schools:
        sid = school["id"]
        if sid in programs:
            school["programs"] = programs[sid]
        if sid in academics:
            school["academics"] = academics[sid]
        if sid in sports:
            school["sports"] = sports[sid]


def annotate_assignments(con: sqlite3.Connection, schools: list[dict[str, Any]], origin: tuple[float, float] | None) -> None:
    """Mark schools whose attendance zone contains the origin. Missing zones stay an empty list."""
    grouped: dict[int, list[dict[str, Any]]] = {}
    if origin:
        from .services.zones import assignments_by_school

        grouped = assignments_by_school(con, origin[0], origin[1])
    for school in schools:
        school["assigned_zones"] = grouped.get(school["id"], [])


def fetch_schools(
    con: sqlite3.Connection,
    *,
    categories: Iterable[str] | None = None,
    grade: int | None = None,
    fl_grades: Iterable[str] | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    ids: Iterable[int] | None = None,
    q: str | None = None,
    program: str | None = None,
    religious: bool | None = None,
    scholarship: bool | None = None,
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
    if program:
        where.append(
            """s.id IN (
                 SELECT school_id FROM school_programs
                 WHERE school_id IS NOT NULL AND (program_type = ? OR themes LIKE ?)
               )"""
        )
        params.extend([program, f'%"{program}"%'])
    if religious:
        where.append("s.religious = 1")
    if scholarship:
        where.append("s.scholarship_programs IS NOT NULL")
    sql = SCHOOL_SELECT
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " LIMIT ?"
    params.append(limit)
    return con.execute(sql, params).fetchall()


def fetch_school(con: sqlite3.Connection, school_id: int) -> sqlite3.Row | None:
    return con.execute(SCHOOL_SELECT + " WHERE s.id = ?", (school_id,)).fetchone()
