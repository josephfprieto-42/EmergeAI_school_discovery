"""Normalize raw public datasets into data/schoolmatch.db (SQLite).

Inputs (data/raw/):
  mdc_public.json, mdc_charter.json, mdc_private.json, mdc_daycare.json, mdc_headstart.json
      Miami-Dade County Open Data (ArcGIS) point layers
  nces_directory.json   NCES CCD directory for LEA 1200390 via Urban Institute API
  SchoolGrades26.xlsx   Florida DOE 2025-26 School Grades (statewide; filtered to district 13)

Only values present in the sources are stored. Missing values are NULL.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "schoolmatch.db"

# Grade encoding: -2 infant/toddler, -1 PK, 0 K, 1..12
GRADE_TOKENS = {
    "PK": -1, "PREK": -1, "PRE-K": -1, "VPK": -1, "PK3": -1, "PK4": -1, "PK6": -1,
    "K": 0, "KG": 0, "KIN": 0, "KINDERGARTEN": 0,
}


def parse_grade_span(text: str | None) -> tuple[int | None, int | None]:
    if not text:
        return None, None
    s = str(text).strip().upper().replace("–", "-")
    if s in {"", "0", "N/A", "NA"}:
        return None, None
    parts = [p.strip() for p in re.split(r"[-/,]| TO ", s) if p.strip()]
    vals: list[int] = []
    for p in parts:
        if p in GRADE_TOKENS:
            vals.append(GRADE_TOKENS[p])
        elif p.isdigit():
            n = int(p)
            if 0 <= n <= 12:
                vals.append(n)
        elif p.startswith("PK"):
            vals.append(-1)
    if not vals:
        return None, None
    return min(vals), max(vals)


def clean(v):
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def to_int(v):
    v = clean(v)
    if v in (None, "", 0, "0"):
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def to_float(v):
    v = clean(v)
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def epoch_ms_to_date(v):
    if not v:
        return None
    try:
        return datetime.fromtimestamp(int(v) / 1000, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return None


def norm_site(v) -> str | None:
    v = clean(v)
    if not v:
        return None
    if not v.lower().startswith("http"):
        v = "http://" + v
    return v


SCHEMA = """
DROP TABLE IF EXISTS schools;
DROP TABLE IF EXISTS school_grades;
DROP TABLE IF EXISTS school_stats;
DROP TABLE IF EXISTS schools_fts;

CREATE TABLE schools (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,
  source_id TEXT,
  mdcps_id TEXT,
  name TEXT NOT NULL,
  category TEXT NOT NULL,      -- public | charter | private | early_childhood
  subtype TEXT NOT NULL,       -- traditional | charter | private | daycare | head_start | early_head_start | alternative | special_center | primary_learning_center | virtual
  address TEXT, city TEXT, zip TEXT, phone TEXT, website TEXT,
  lat REAL NOT NULL, lon REAL NOT NULL,
  grade_low INTEGER, grade_high INTEGER, grades_text TEXT,
  enrollment INTEGER, capacity INTEGER,
  year_established INTEGER, coed TEXT,
  license_number TEXT, license_expires TEXT,
  status TEXT,
  region TEXT
);
CREATE INDEX idx_schools_cat ON schools(category);
CREATE INDEX idx_schools_latlon ON schools(lat, lon);
CREATE INDEX idx_schools_mdcps ON schools(mdcps_id);

CREATE TABLE school_grades (
  school_id INTEGER PRIMARY KEY REFERENCES schools(id),
  year INTEGER NOT NULL,
  grade TEXT,
  grade_prev1 TEXT, grade_prev2 TEXT,
  grade_history TEXT,          -- JSON {year: grade}
  ela_ach REAL, ela_gains REAL, ela_gains_low25 REAL,
  math_ach REAL, math_gains REAL, math_gains_low25 REAL,
  sci_ach REAL, ss_ach REAL,
  ms_accel REAL, grad_rate REAL, college_career_accel REAL,
  pct_points REAL, pct_tested REAL,
  pct_econ_disadvantaged REAL,
  title_i INTEGER, charter INTEGER, alt_ese INTEGER,
  school_type TEXT             -- 01 Elementary, 02 Middle, 03 High, 04 Combination
);

CREATE TABLE school_stats (
  school_id INTEGER PRIMARY KEY REFERENCES schools(id),
  year INTEGER NOT NULL,
  ncessch TEXT,
  enrollment INTEGER,
  frl_count INTEGER, frl_pct REAL,
  teachers_fte REAL, student_teacher_ratio REAL,
  magnet INTEGER, title_i_schoolwide INTEGER, title_i_eligible INTEGER,
  locale INTEGER,
  nces_grade_low INTEGER, nces_grade_high INTEGER
);

CREATE VIRTUAL TABLE schools_fts USING fts5(name, address, city, content='schools', content_rowid='id');
"""


def load_features(name: str) -> list[dict]:
    return json.loads((RAW / name).read_text())["features"]


def insert_school(cur: sqlite3.Cursor, row: dict) -> int:
    cols = ",".join(row.keys())
    qs = ",".join("?" for _ in row)
    cur.execute(f"INSERT INTO schools ({cols}) VALUES ({qs})", list(row.values()))
    return cur.lastrowid


def ingest_mdc(cur: sqlite3.Cursor) -> dict[str, int]:
    """Insert all MDC layers. Returns {mdcps_id: school_id} for public+charter joins."""
    by_mdcps: dict[str, int] = {}
    counts: dict[str, int] = {}

    # Charter first so overlapping IDs resolve to the charter record.
    charter_ids: set[str] = set()
    for f in load_features("mdc_charter.json"):
        a = f["attributes"]
        if not a.get("LAT") or not a.get("LON"):
            continue
        mid = str(a.get("ID") or "").strip().zfill(4) if a.get("ID") else None
        lo, hi = parse_grade_span(a.get("GRADE"))
        sid = insert_school(cur, dict(
            source="mdc_gis_charter", source_id=str(a["OBJECTID"]), mdcps_id=mid,
            name=clean(a["NAME"]), category="charter", subtype="charter",
            address=clean(a.get("ADDRESS")), city=clean(a.get("CITY")), zip=str(a.get("ZIPCODE") or "") or None,
            phone=clean(a.get("PHONE")), website=norm_site(a.get("WEBSITE")),
            lat=a["LAT"], lon=a["LON"], grade_low=lo, grade_high=hi, grades_text=clean(a.get("GRADE")),
            enrollment=to_int(a.get("ENROLLMNT")), capacity=to_int(a.get("CAPACITY")),
            year_established=None, coed=None, license_number=None, license_expires=None,
            status="Active", region=None,
        ))
        if mid:
            by_mdcps[mid] = sid
            charter_ids.add(mid)
        counts["charter"] = counts.get("charter", 0) + 1

    subtype_by_type = {
        "E": "traditional", "M": "traditional", "S": "traditional", "U": "traditional",
        "ALT": "alternative", "SPC": "special_center", "PLC": "primary_learning_center",
    }
    for f in load_features("mdc_public.json"):
        a = f["attributes"]
        t = clean(a.get("TYPE"))
        if t in {"A", "O"}:  # administrative buildings, adult/technical education
            continue
        if not a.get("LAT") or not a.get("LON"):
            continue
        mid = str(a.get("ID") or "").strip().zfill(4) if a.get("ID") else None
        if mid and mid in charter_ids:
            continue
        name = clean(a["NAME"]) or ""
        subtype = subtype_by_type.get(t or "", "traditional")
        if "virtual" in name.lower():
            subtype = "virtual"
        lo, hi = parse_grade_span(a.get("GRADES"))
        sid = insert_school(cur, dict(
            source="mdc_gis_public", source_id=str(a["OBJECTID"]), mdcps_id=mid,
            name=name, category="public", subtype=subtype,
            address=clean(a.get("ADDRESS")), city=clean(a.get("CITY")), zip=str(a.get("ZIPCODE") or "") or None,
            phone=clean(a.get("PHONE")), website=None,
            lat=a["LAT"], lon=a["LON"], grade_low=lo, grade_high=hi,
            grades_text=clean(a.get("GRADES")) if clean(a.get("GRADES")) != "0" else None,
            enrollment=to_int(a.get("ENROLLMNT")), capacity=to_int(a.get("CAPACITY")),
            year_established=None, coed=None, license_number=None, license_expires=None,
            status="Active", region=clean(a.get("REGION")),
        ))
        if mid:
            by_mdcps[mid] = sid
        counts["public"] = counts.get("public", 0) + 1

    for f in load_features("mdc_private.json"):
        a = f["attributes"]
        status = clean(a.get("STATUS"))
        if status and status.lower().startswith("clos"):
            continue
        if not a.get("LAT") or not a.get("LON"):
            continue
        lo, hi = parse_grade_span(a.get("GRDLEVEL"))
        coed = {"C": "coed", "B": "boys", "G": "girls"}.get((clean(a.get("COED")) or "").upper())
        insert_school(cur, dict(
            source="mdc_gis_private", source_id=str(a["OBJECTID"]), mdcps_id=None,
            name=clean(a["NAME"]), category="private", subtype="private",
            address=clean(a.get("ADDRESS")), city=clean(a.get("CITY")), zip=str(a.get("ZIPCODE") or "") or None,
            phone=clean(a.get("PHONE")), website=norm_site(a.get("WEBSITE")),
            lat=a["LAT"], lon=a["LON"], grade_low=lo, grade_high=hi, grades_text=clean(a.get("GRDLEVEL")),
            enrollment=to_int(a.get("ENROLLMENT")), capacity=None,
            year_established=to_int(a.get("YEARESTB")), coed=coed,
            license_number=None, license_expires=None,
            status=status or None, region=None,
        ))
        counts["private"] = counts.get("private", 0) + 1

    for f in load_features("mdc_headstart.json"):
        a = f["attributes"]
        if not a.get("LAT") or not a.get("LON"):
            continue
        early = (clean(a.get("EARLYHS")) or "").upper() == "Y" or clean(a.get("TYPE")) == "EHS"
        insert_school(cur, dict(
            source="mdc_gis_headstart", source_id=str(a["OBJECTID"]), mdcps_id=None,
            name=clean(a["NAME"]), category="early_childhood",
            subtype="early_head_start" if early else "head_start",
            address=clean(a.get("ADDRESS")), city=clean(a.get("CITY")), zip=str(a.get("ZIPCODE") or "") or None,
            phone=clean(a.get("PHONE")), website=norm_site(a.get("WEBSITE")),
            lat=a["LAT"], lon=a["LON"],
            grade_low=-2 if early else -1, grade_high=-1,
            grades_text="Early Head Start (0-3) & Head Start (3-5)" if early else "Head Start (ages 3-5)",
            enrollment=None, capacity=None, year_established=None, coed=None,
            license_number=None, license_expires=None, status="Active", region=None,
        ))
        counts["headstart"] = counts.get("headstart", 0) + 1

    for f in load_features("mdc_daycare.json"):
        a = f["attributes"]
        if not a.get("LAT") or not a.get("LON"):
            continue
        insert_school(cur, dict(
            source="mdc_gis_daycare", source_id=str(a["OBJECTID"]), mdcps_id=None,
            name=clean(a["NAME"]), category="early_childhood", subtype="daycare",
            address=clean(a.get("ADDRESS")), city=clean(a.get("CITY")), zip=str(a.get("ZIPCODE") or "") or None,
            phone=clean(a.get("PHONE")), website=None,
            lat=a["LAT"], lon=a["LON"], grade_low=-2, grade_high=-1,
            grades_text="Licensed child care (infant-PK)",
            enrollment=None, capacity=to_int(a.get("CAPACITY")), year_established=None, coed=None,
            license_number=clean(a.get("LICNUM")), license_expires=epoch_ms_to_date(a.get("LICEXP")),
            status="Licensed", region=None,
        ))
        counts["daycare"] = counts.get("daycare", 0) + 1

    print("MDC inserted:", counts)
    return by_mdcps


def ingest_fldoe(cur: sqlite3.Cursor, by_mdcps: dict[str, int]) -> None:
    path = RAW / "SchoolGrades26.xlsx"
    if not path.exists():
        print("WARNING: SchoolGrades26.xlsx not found; skipping FLDOE grades")
        return
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb.active
    rows = ws.iter_rows(values_only=True)
    hdr = None
    for r in rows:
        if r and r[0] == "District Number":
            hdr = list(r)
            break
    if hdr is None:
        raise RuntimeError("FLDOE header row not found")
    year_cols = [(int(re.search(r"(\d{4})", h).group(1)), i) for i, h in enumerate(hdr) if h and re.match(r"(Informational Baseline )?Grade \d{4}$", h)]
    idx = {h: i for i, h in enumerate(hdr)}

    def g(r, key):
        i = idx.get(key)
        return r[i] if i is not None else None

    def yn(v):
        v = clean(v)
        return None if v is None else int(str(v).upper().startswith("Y"))

    matched = 0
    total = 0
    for r in rows:
        if not r or r[0] != "13":
            continue
        total += 1
        num = str(g(r, "School Number")).zfill(4)
        sid = by_mdcps.get(num)
        if not sid:
            continue
        history = {str(y): clean(r[i]) for y, i in year_cols if clean(r[i])}
        cur.execute(
            """INSERT OR REPLACE INTO school_grades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                sid, 2026, clean(g(r, "Grade 2026")), clean(g(r, "Grade 2025")), clean(g(r, "Grade 2024")),
                json.dumps(history),
                to_float(g(r, "English Language Arts Achievement")),
                to_float(g(r, "English Language Arts Learning Gains")),
                to_float(g(r, "English Language Arts Learning Gains of the Lowest 25%")),
                to_float(g(r, "Mathematics Achievement")),
                to_float(g(r, "Mathematics Learning Gains")),
                to_float(g(r, "Mathematics Learning Gains of the Lowest 25%")),
                to_float(g(r, "Science Achievement")),
                to_float(g(r, "Social Studies Achievement")),
                to_float(g(r, "Middle School Acceleration")),
                to_float(g(r, "Graduation Rate 2024-25")),
                to_float(g(r, "College and Career Acceleration 2024-25")),
                to_float(g(r, "Percent of Total Possible Points")),
                to_float(g(r, "Percent Tested")),
                to_float(g(r, "Percent of Economically Disadvantaged Students")),
                yn(g(r, "Title I")), yn(g(r, "Charter School")), yn(g(r, "Alternative/ESE Center School")),
                clean(g(r, "School Type")),
            ),
        )
        matched += 1
    print(f"FLDOE: {total} Miami-Dade rows, {matched} matched to GIS schools")


def ingest_nces(cur: sqlite3.Cursor, by_mdcps: dict[str, int]) -> None:
    path = RAW / "nces_directory.json"
    if not path.exists():
        print("WARNING: nces_directory.json not found; skipping NCES stats")
        return
    d = json.loads(path.read_text())
    year = d["year"]
    matched = 0
    for r in d["results"]:
        num = str(r.get("seasch") or "").split("-")[-1].zfill(4)
        sid = by_mdcps.get(num)
        if not sid:
            continue
        enr = to_int(r.get("enrollment"))
        fte = to_float(r.get("teachers_fte"))
        frl = to_int(r.get("free_or_reduced_price_lunch"))
        ratio = round(enr / fte, 1) if enr and fte and fte > 0 else None
        if ratio is not None and (ratio > 45 or ratio < 4):
            ratio = None  # implausible FTE reporting; treat as not reported rather than mislead
        frl_pct = round(100 * frl / enr, 1) if frl is not None and enr else None
        lo = r.get("lowest_grade_offered")
        hi = r.get("highest_grade_offered")
        lo = lo if isinstance(lo, int) and -2 <= lo <= 12 else None
        hi = hi if isinstance(hi, int) and -2 <= hi <= 12 else None
        cur.execute(
            "INSERT OR REPLACE INTO school_stats VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, year, r.get("ncessch"), enr, frl, frl_pct, fte, ratio,
             r.get("magnet") if r.get("magnet") in (0, 1) else None,
             r.get("title_i_schoolwide") if r.get("title_i_schoolwide") in (0, 1) else None,
             r.get("title_i_eligible") if r.get("title_i_eligible") in (0, 1) else None,
             r.get("urban_centric_locale"), lo, hi),
        )
        # Fill grade span / enrollment gaps on the school row from NCES.
        cur.execute(
            """UPDATE schools SET
                 grade_low = COALESCE(grade_low, ?),
                 grade_high = COALESCE(grade_high, ?),
                 enrollment = COALESCE(enrollment, ?)
               WHERE id = ?""",
            (lo, hi, enr, sid),
        )
        matched += 1
    print(f"NCES {year}: {len(d['results'])} rows, {matched} matched to GIS schools")


def main() -> int:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.executescript(SCHEMA)
    by_mdcps = ingest_mdc(cur)
    ingest_fldoe(cur, by_mdcps)
    ingest_nces(cur, by_mdcps)
    # Derive grades_text where it was missing but NCES provided a span.
    cur.execute(
        """UPDATE schools SET grades_text =
             (CASE grade_low WHEN -2 THEN 'Infant' WHEN -1 THEN 'PK' WHEN 0 THEN 'K' ELSE CAST(grade_low AS TEXT) END)
             || '-' ||
             (CASE grade_high WHEN -2 THEN 'Infant' WHEN -1 THEN 'PK' WHEN 0 THEN 'K' ELSE CAST(grade_high AS TEXT) END)
           WHERE grades_text IS NULL AND grade_low IS NOT NULL AND grade_high IS NOT NULL"""
    )
    cur.execute("INSERT INTO schools_fts(rowid, name, address, city) SELECT id, name, address, city FROM schools")
    con.commit()
    for row in cur.execute("SELECT category, subtype, COUNT(*) FROM schools GROUP BY 1,2 ORDER BY 1,2"):
        print("  ", row)
    print("grades:", cur.execute("SELECT COUNT(*) FROM school_grades").fetchone()[0],
          "stats:", cur.execute("SELECT COUNT(*) FROM school_stats").fetchone()[0])
    con.close()
    print("wrote", DB_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
