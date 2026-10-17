"""Merge attendance boundaries, choice/magnet programs, and the private-school directory.

Reads the snapshots in data/raw/ and updates data/schoolmatch.db in place.
Existing school rows and ids are kept. Re-running replaces only the enrichment tables.

Does not infer programs, tuition, or eligibility from school names.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

import identity
from program_themes import themes_for_program

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "schoolmatch.db"
REPORT_PATH = ROOT / "data" / "audit" / "enrichment_report.json"

BOUNDARY_SOURCE = "mdc_attendance_boundary"
PROGRAM_SOURCE = "yourchoicemiami"
DIRECTORY_SOURCE = "fldoe_private_directory"

MAGNET_NOTE = (
    "Magnet programs require an application and, when seats are limited, a random selection. "
    "Living in the attendance boundary does not admit a student. Application window is October 1 through January 15."
)
CHOICE_NOTE = (
    "Parent Choice programs give priority to students who live in the school's attendance boundary. "
    "Remaining seats are offered through the Choice application. Transportation is typically not provided."
)

SCHOOL_COLUMNS = {
    "verified_programs": "TEXT",
    "attendance_levels": "TEXT",
    "religious": "INTEGER",
    "denomination": "TEXT",
    "nonprofit": "INTEGER",
    "accreditation": "TEXT",
    "scholarship_programs": "TEXT",
    "directory_survey_year": "INTEGER",
    "directory_outdated": "INTEGER",
}


def parse_grade_span(text: str | None) -> tuple[int | None, int | None]:
    if not text:
        return None, None
    s = unescape(str(text)).replace("\xa0", " ").upper().replace("–", "-").replace("—", "-")
    if s.strip() in {"", "0", "N/A", "NA"}:
        return None, None
    tokens = {"PK": -1, "PREK": -1, "PRE-K": -1, "VPK": -1, "K": 0, "KG": 0}
    vals = []
    for part in re.split(r"[-/,]| TO |&", s):
        p = part.strip()
        if p in tokens:
            vals.append(tokens[p])
        elif p.isdigit() and 0 <= int(p) <= 12:
            vals.append(int(p))
        elif p.startswith("PK"):
            vals.append(-1)
    if not vals:
        return None, None
    return min(vals), max(vals)


def epoch_ms_to_date(value) -> str | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return None


def ensure_columns(cur: sqlite3.Cursor) -> None:
    have = {row[1] for row in cur.execute("PRAGMA table_info(schools)")}
    for name, decl in SCHOOL_COLUMNS.items():
        if name not in have:
            cur.execute(f"ALTER TABLE schools ADD COLUMN {name} {decl}")


def ensure_tables(cur: sqlite3.Cursor) -> None:
    cur.executescript(
        """
        DROP TABLE IF EXISTS attendance_zones;
        DROP TABLE IF EXISTS school_programs;
        DROP TABLE IF EXISTS private_directory;
        CREATE TABLE attendance_zones (
          id INTEGER PRIMARY KEY,
          level TEXT NOT NULL,
          object_id INTEGER,
          mdcps_id TEXT,
          school_id INTEGER,
          name TEXT,
          grades_text TEXT,
          grade_low INTEGER,
          grade_high INTEGER,
          min_lon REAL, min_lat REAL, max_lon REAL, max_lat REAL,
          rings_json TEXT NOT NULL,
          feature_modified TEXT,
          collected_at TEXT NOT NULL,
          source TEXT NOT NULL,
          match_method TEXT
        );
        CREATE INDEX idx_zones_school ON attendance_zones(school_id);
        CREATE TABLE school_programs (
          id INTEGER PRIMARY KEY,
          school_id INTEGER,
          name TEXT,
          kind TEXT,
          test_required INTEGER NOT NULL DEFAULT 0,
          source TEXT NOT NULL,
          mdcps_id TEXT,
          program_type TEXT,
          program_name TEXT,
          themes TEXT,
          eligibility TEXT,
          admission_note TEXT,
          school_name TEXT,
          address TEXT,
          match_method TEXT,
          source_url TEXT,
          collected_at TEXT
        );
        CREATE INDEX idx_programs_school ON school_programs(school_id);
        CREATE TABLE private_directory (
          id INTEGER PRIMARY KEY,
          school_id INTEGER,
          school_code TEXT,
          name TEXT,
          address TEXT,
          city TEXT,
          zip TEXT,
          grades_text TEXT,
          survey_year INTEGER,
          outdated INTEGER NOT NULL DEFAULT 0,
          religious INTEGER,
          denomination TEXT,
          nonprofit INTEGER,
          coed TEXT,
          accreditation TEXT,
          scholarships TEXT,
          enrollment INTEGER,
          match_method TEXT,
          source TEXT NOT NULL,
          collected_at TEXT NOT NULL,
          verification TEXT NOT NULL
        );
        """
    )


def _bbox(rings: list) -> tuple[float, float, float, float] | None:
    pts = [pt for ring in rings for pt in ring]
    if not pts:
        return None
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    return min(lons), min(lats), max(lons), max(lats)


def _tag_source(cur: sqlite3.Cursor, school_id: int, source: str) -> None:
    row = cur.execute("SELECT sources FROM schools WHERE id = ?", (school_id,)).fetchone()
    current = json.loads(row[0] or "[]")
    if source not in current:
        current.append(source)
        cur.execute("UPDATE schools SET sources = ? WHERE id = ?", (json.dumps(current), school_id))


def _clear_enrichment(cur: sqlite3.Cursor) -> None:
    cur.execute(
        "DELETE FROM school_sources WHERE source IN (?, ?, ?)",
        (BOUNDARY_SOURCE, PROGRAM_SOURCE, DIRECTORY_SOURCE),
    )
    for row in cur.execute("SELECT id, sources FROM schools"):
        current = json.loads(row[1] or "[]")
        kept = [s for s in current if s not in {BOUNDARY_SOURCE, PROGRAM_SOURCE, DIRECTORY_SOURCE}]
        if kept != current:
            cur.execute("UPDATE schools SET sources = ? WHERE id = ?", (json.dumps(kept), row[0]))
    cur.execute("UPDATE schools SET " + ", ".join(f"{name} = NULL" for name in SCHOOL_COLUMNS))


def schools_by_mdcps(cur: sqlite3.Cursor) -> dict[str, list[sqlite3.Row]]:
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in cur.execute(
        "SELECT id, mdcps_id, name, category, subtype FROM schools WHERE mdcps_id IS NOT NULL AND mdcps_id != ''"
    ):
        grouped.setdefault(row[1], []).append(row)
    return grouped


def match_mdcps(grouped: dict[str, list[sqlite3.Row]], mdcps_id: str | None) -> tuple[list[int], str]:
    if not mdcps_id:
        return [], "unmatched"
    key = str(mdcps_id).strip().zfill(4)
    rows = grouped.get(key) or []
    chosen = [r for r in rows if r[3] in {"public", "charter"} and r[4] != "primary_learning_center"]
    if not chosen:
        chosen = [r for r in rows if r[3] in {"public", "charter"}]
    if not chosen:
        return [], "unmatched"
    method = "mdcps_id" if len(chosen) == 1 else "mdcps_id_multiple"
    return [r[0] for r in chosen], method


def ingest_boundaries(cur: sqlite3.Cursor, grouped: dict[str, list[sqlite3.Row]]) -> dict:
    payload = json.loads((RAW / "mdc_attendance_boundaries.json").read_text())
    collected = payload["collected_at"]
    seen: set[tuple] = set()
    matched_schools: set[int] = set()
    unmatched = 0
    modified: list[str] = []
    kept = 0
    defaults = {"elementary": (-1, 5), "middle": (6, 8), "high": (9, 12)}
    for feature in payload["features"]:
        boundary = feature["boundary"]
        key = (feature["level"], boundary.get("OBJECTID"))
        if key in seen:
            continue
        seen.add(key)
        raw_id = str(boundary.get("ID") or "").strip()
        mdcps_id = raw_id.zfill(4) if raw_id and raw_id != "0" else None
        school_ids, method = match_mdcps(grouped, mdcps_id)
        school_id = school_ids[0] if school_ids else None
        if school_id is None:
            unmatched += 1
        else:
            matched_schools.add(school_id)
        rings = feature.get("rings") or []
        box = _bbox(rings)
        grades = boundary.get("GRADES")
        lo, hi = parse_grade_span(grades)
        if lo is None:
            lo, hi = defaults[feature["level"]]
        modified_on = epoch_ms_to_date(boundary.get("MODIFIEDDATE"))
        if modified_on:
            modified.append(modified_on)
        cur.execute(
            """INSERT INTO attendance_zones (
                 level, object_id, mdcps_id, school_id, name, grades_text, grade_low, grade_high,
                 min_lon, min_lat, max_lon, max_lat, rings_json, feature_modified, collected_at, source, match_method
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                feature["level"], boundary.get("OBJECTID"), mdcps_id, school_id, boundary.get("NAME"),
                grades, lo, hi,
                None if box is None else box[0], None if box is None else box[1],
                None if box is None else box[2], None if box is None else box[3],
                json.dumps(rings), modified_on, collected, BOUNDARY_SOURCE,
                method if school_id else "unmatched",
            ),
        )
        if school_id:
            _tag_source(cur, school_id, BOUNDARY_SOURCE)
        kept += 1
    levels: dict[int, set[str]] = {}
    for row in cur.execute("SELECT DISTINCT school_id, level FROM attendance_zones WHERE school_id IS NOT NULL"):
        levels.setdefault(row[0], set()).add(row[1])
    for sid, vals in levels.items():
        cur.execute("UPDATE schools SET attendance_levels = ? WHERE id = ?", (json.dumps(sorted(vals)), sid))
        cur.execute(
            "INSERT INTO school_sources (school_id, source, source_id, name, address, match_method) VALUES (?,?,?,?,?,?)",
            (sid, BOUNDARY_SOURCE, None, None, None, "mdcps_id"),
        )
    return {
        "status": "integrated",
        "records": kept,
        "matched_schools": len(matched_schools),
        "unmatched_zones": unmatched,
        "feature_modified_min": min(modified) if modified else None,
        "feature_modified_max": max(modified) if modified else None,
        "collected_at": collected,
        "source": payload.get("source"),
        "license": "Miami-Dade County public ArcGIS service. Attribute Miami-Dade County GIS and M-DCPS School Operations.",
    }


def _program_rows() -> tuple[list[dict], list[str]]:
    files = [
        "mdcps_choice_page1.json",
        "mdcps_choice_page2.json",
        "mdcps_choice_page3.json",
        "mdcps_magnet_page1.json",
        "mdcps_magnet_page2.json",
    ]
    rows: list[dict] = []
    missing = []
    for name in files:
        path = RAW / name
        if not path.exists():
            missing.append(name)
            continue
        rows.extend(json.loads(path.read_text()))
    return rows, missing


def _program_type(row: dict) -> str:
    heading = (row.get("program_heading") or "").lower()
    return "magnet" if "magnet" in heading else "choice"


def _eligibility(name: str) -> str | None:
    notes = []
    if re.search(r"auditions required", name, re.I):
        notes.append("Auditions required")
    if re.search(r"test required", name, re.I):
        notes.append("Test required")
    return "; ".join(notes) or None


def ingest_programs(cur: sqlite3.Cursor, grouped: dict[str, list[sqlite3.Row]]) -> dict:
    rows, missing = _program_rows()
    collected = "2026-10-17T16:40:00+00:00"
    matched_schools: set[int] = set()
    unmatched = []
    inserted = 0
    for row in rows:
        ptype = _program_type(row)
        mdcps_id = str(row.get("mdcps_id")).zfill(4) if row.get("mdcps_id") else None
        school_ids, method = match_mdcps(grouped, mdcps_id)
        if not school_ids:
            unmatched.append({"mdcps_id": mdcps_id, "name": row.get("name")})
            targets = [None]
            method = "unmatched"
        else:
            targets = school_ids
        note = MAGNET_NOTE if ptype == "magnet" else CHOICE_NOTE
        for program in row.get("programs") or []:
            themes = themes_for_program(program, ptype)
            for sid in targets:
                eligibility = _eligibility(program)
                test_required = 1 if eligibility and "Test required" in eligibility else 0
                cur.execute(
                    """INSERT INTO school_programs (
                         school_id, name, kind, test_required, source,
                         mdcps_id, program_type, program_name, themes, eligibility, admission_note,
                         school_name, address, match_method, source_url, collected_at
                       ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        sid, program, ptype, test_required, PROGRAM_SOURCE,
                        mdcps_id, ptype, program, json.dumps(themes), eligibility, note,
                        row.get("name"), row.get("address"), method, row.get("source_url"), collected,
                    ),
                )
                inserted += 1
                if sid:
                    matched_schools.add(sid)
    by_school: dict[int, list[dict]] = {}
    for row in cur.execute(
        "SELECT school_id, program_type, program_name, themes, eligibility FROM school_programs WHERE school_id IS NOT NULL"
    ):
        by_school.setdefault(row[0], []).append({
            "type": row[1], "name": row[2], "themes": json.loads(row[3]), "eligibility": row[4],
        })
    for sid, programs in by_school.items():
        cur.execute("UPDATE schools SET verified_programs = ? WHERE id = ?", (json.dumps(programs), sid))
        _tag_source(cur, sid, PROGRAM_SOURCE)
        cur.execute(
            "INSERT INTO school_sources (school_id, source, source_id, name, address, match_method) VALUES (?,?,?,?,?,?)",
            (sid, PROGRAM_SOURCE, None, None, None, "mdcps_id"),
        )
    return {
        "status": "integrated" if not missing else "partial",
        "school_rows": len(rows),
        "programs": inserted,
        "matched_schools": len(matched_schools),
        "unmatched_schools": len(unmatched),
        "unmatched_sample": unmatched[:8],
        "missing_snapshot_files": missing,
        "collected_at": collected,
        "source": "https://yourchoicemiami.org/program-search",
        "access": "Public catalog. Scripted clients get a Sucuri JavaScript challenge, which this pipeline does not solve. These rows were read in a browser.",
        "license": "Attribute Miami-Dade County Public Schools. A listed program is not a promise of admission.",
    }


def _yes_no(value: str | None) -> int | None:
    v = (value or "").strip().lower()
    if v in {"yes", "y"}:
        return 1
    if v in {"no", "n"}:
        return 0
    return None


def _html_rows(html: str) -> list[list[str]]:
    parsed = []
    for row in re.findall(r"<tr[\s\S]*?</tr>", html, re.I):
        parsed.append([
            unescape(re.sub(r"<[^>]+>", "", cell)).replace("\xa0", " ").strip()
            for cell in re.findall(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", row, re.I)
        ])
    return parsed


def load_directory() -> tuple[list[dict], str]:
    meta_path = RAW / "fl_private_directory_dade.json"
    collected = datetime.now(timezone.utc).isoformat()
    if meta_path.exists():
        collected = json.loads(meta_path.read_text()).get("collected_at") or collected
    table = _html_rows((RAW / "fl_private_directory_dade.xlsx").read_text(errors="replace"))
    header = table[0]
    index = {name: i for i, name in enumerate(header)}

    def col(cells: list[str], name: str) -> str:
        i = index.get(name)
        return cells[i] if i is not None and i < len(cells) else ""

    records = []
    for cells in table[1:]:
        if len(cells) < len(header):
            cells = cells + [""] * (len(header) - len(cells))
        enrollment = 0
        for label in ["Pre-K", "Kindergarten", *[f"Grade {n}" for n in range(1, 13)]]:
            try:
                enrollment += int(float(col(cells, label) or 0))
            except ValueError:
                pass
        year_text = col(cells, "Last Annual Survey Year")
        year = int(year_text) if year_text.isdigit() else None
        scholarships = []
        for label, column in (
            ("Florida Tax Credit Scholarship", "FTC Participant"),
            ("FES Unique Abilities Scholarship", "FES Unique Abilities Participant"),
            ("PEP Hybrid Scholarship", "PEP Participant"),
            ("FES Educational Options", "FES Educational Options Participant"),
        ):
            if _yes_no(col(cells, column)) == 1:
                scholarships.append(label)
        records.append({
            "school_code": col(cells, "School Code") or None,
            "name": col(cells, "School Name"),
            "address": col(cells, "Address 1"),
            "city": col(cells, "City"),
            "zip": (col(cells, "Zip") or "")[:5] or None,
            "grades_text": col(cells, "Grade Levels") or None,
            "survey_year": year,
            "outdated": 1 if year is not None and year <= 2023 else 0,
            "religious": _yes_no(col(cells, "Religious")),
            "denomination": col(cells, "Denomination") or None,
            "nonprofit": _yes_no(col(cells, "Non-Profit")),
            "coed": {"coed": "coed", "boys": "boys", "girls": "girls"}.get(col(cells, "Student Type").lower()),
            "accreditation": col(cells, "Accreditation") or None,
            "scholarships": scholarships,
            "enrollment": enrollment or None,
        })
    return records, collected


def match_private(record: dict, candidates: list[sqlite3.Row]) -> tuple[sqlite3.Row | None, str, float]:
    zip_code = record["zip"]
    pool = [c for c in candidates if zip_code and c[3] and str(c[3])[:5] == zip_code]
    if not pool:
        pool = candidates
    target = identity.normalize_address(record["address"])
    scored = []
    for cand in pool:
        sim = identity.name_similarity(record["name"], cand[1])
        addr = identity.normalize_address(cand[2])
        same = bool(target and addr and (target == addr or target in addr or addr in target))
        scored.append((same, sim, cand))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    if not scored:
        return None, "unmatched", 0.0
    same, sim, cand = scored[0]
    second = scored[1][1] if len(scored) > 1 else 0.0
    if same and sim >= 0.55:
        return cand, "name_and_address", sim
    if sim >= 0.86 and sim - second >= 0.08 and (not zip_code or (cand[3] and str(cand[3])[:5] == zip_code)):
        return cand, "name_zip", sim
    return None, "unmatched", sim


def ingest_directory(cur: sqlite3.Cursor) -> dict:
    records, collected = load_directory()
    candidates = cur.execute(
        "SELECT id, name, address, zip, grade_low, grade_high, grades_text, enrollment, coed FROM schools WHERE category = 'private'"
    ).fetchall()
    used: dict[int, float] = {}
    matched = unmatched = religious_yes = scholarship = stale = 0
    verification = "school-reported annual survey; Florida DOE does not verify accuracy"
    for record in records:
        if record["outdated"]:
            stale += 1
        if record["religious"] == 1:
            religious_yes += 1
        if record["scholarships"]:
            scholarship += 1
        cand, method, score = match_private(record, candidates)
        school_id = None
        if cand is not None and used.get(cand[0], -1) < score:
            school_id = cand[0]
            used[cand[0]] = score
            matched += 1
        else:
            unmatched += 1
            method = "unmatched" if cand is None else "unmatched_duplicate"
        cur.execute(
            """INSERT INTO private_directory (
                 school_id, school_code, name, address, city, zip, grades_text, survey_year, outdated,
                 religious, denomination, nonprofit, coed, accreditation, scholarships, enrollment,
                 match_method, source, collected_at, verification
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                school_id, record["school_code"], record["name"], record["address"], record["city"], record["zip"],
                record["grades_text"], record["survey_year"], record["outdated"], record["religious"],
                record["denomination"], record["nonprofit"], record["coed"], record["accreditation"],
                json.dumps(record["scholarships"]), record["enrollment"], method, DIRECTORY_SOURCE, collected, verification,
            ),
        )
        if school_id is None or record["outdated"]:
            continue
        cur.execute(
            """UPDATE schools SET religious = ?, denomination = ?, nonprofit = ?, accreditation = ?,
                      scholarship_programs = ?, directory_survey_year = ?, directory_outdated = 0
               WHERE id = ?""",
            (
                record["religious"], record["denomination"], record["nonprofit"], record["accreditation"],
                json.dumps(record["scholarships"]) if record["scholarships"] else None,
                record["survey_year"], school_id,
            ),
        )
        current = cur.execute(
            "SELECT grade_low, enrollment, coed FROM schools WHERE id = ?", (school_id,)
        ).fetchone()
        lo, hi = parse_grade_span(record["grades_text"])
        if current[0] is None and lo is not None:
            cur.execute(
                "UPDATE schools SET grade_low = ?, grade_high = ?, grades_text = ? WHERE id = ?",
                (lo, hi, record["grades_text"], school_id),
            )
        if current[1] is None and record["enrollment"]:
            cur.execute("UPDATE schools SET enrollment = ? WHERE id = ?", (record["enrollment"], school_id))
        if current[2] is None and record["coed"]:
            cur.execute("UPDATE schools SET coed = ? WHERE id = ?", (record["coed"], school_id))
        _tag_source(cur, school_id, DIRECTORY_SOURCE)
        cur.execute(
            "INSERT INTO school_sources (school_id, source, source_id, name, address, match_method) VALUES (?,?,?,?,?,?)",
            (school_id, DIRECTORY_SOURCE, record["school_code"], record["name"], record["address"], method),
        )
    return {
        "status": "integrated",
        "records": len(records),
        "matched_schools": matched,
        "unmatched": unmatched,
        "survey_year_2023_or_older_not_applied": stale,
        "religious_yes_in_directory": religious_yes,
        "scholarship_participants_in_directory": scholarship,
        "collected_at": collected,
        "source": "https://www.floridaschoolchoice.org/information/privateschooldirectory/DownloadExcelFile.aspx",
        "verification": verification + " Rows from 2023 or earlier stay in private_directory and are not copied onto school profiles.",
        "not_tuition": "Scholarship participation is not a tuition amount.",
    }


def main() -> int:
    if not DB_PATH.exists():
        raise SystemExit(f"missing {DB_PATH}")
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    ensure_columns(cur)
    ensure_tables(cur)
    _clear_enrichment(cur)
    grouped = schools_by_mdcps(cur)
    boundaries = ingest_boundaries(cur, grouped)
    programs = ingest_programs(cur, grouped)
    directory = ingest_directory(cur)
    con.commit()
    coverage = {
        "schools": cur.execute("SELECT COUNT(*) FROM schools").fetchone()[0],
        "schools_with_attendance_zone": cur.execute("SELECT COUNT(*) FROM schools WHERE attendance_levels IS NOT NULL").fetchone()[0],
        "schools_with_verified_program": cur.execute("SELECT COUNT(*) FROM schools WHERE verified_programs IS NOT NULL").fetchone()[0],
        "private_profiles_with_directory_facts": cur.execute("SELECT COUNT(*) FROM schools WHERE directory_survey_year IS NOT NULL").fetchone()[0],
        "school_reported_religious": cur.execute("SELECT COUNT(*) FROM schools WHERE religious = 1").fetchone()[0],
        "school_reported_not_religious": cur.execute("SELECT COUNT(*) FROM schools WHERE religious = 0").fetchone()[0],
        "scholarship_participants_on_profiles": cur.execute("SELECT COUNT(*) FROM schools WHERE scholarship_programs IS NOT NULL").fetchone()[0],
    }
    con.close()
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "integrated": {
            "attendance_boundaries": boundaries,
            "choice_and_magnet_programs": programs,
            "private_school_directory": directory,
        },
        "unavailable": [
            {
                "source": "Florida DCF CARES public search",
                "url": "https://caressearch.myflfamilies.com/PublicSearch/",
                "reason": "Every search requires a bearer token and a reCAPTCHA v3 token. Operating hours and inspection history were not collected.",
            },
            {
                "source": "DCF statewide child-care list",
                "url": "https://www.myflfamilies.com/sites/default/files/2023-11/Public%20-%202023-11-1%20-%20Statewide.pdf",
                "reason": "The public statewide file found is dated 2023-11-01 and has no operating hours. It was not ingested.",
            },
            {
                "source": "Tuition, bell times, bus routes, special-education catalog",
                "reason": "No current bulk dataset was found in the time box. FLDOE alt_ese in this database is zero for every graded school, so it was not surfaced. Nothing was inferred from school names.",
            },
        ],
        "coverage": coverage,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(json.dumps(coverage, indent=2))
    print(f"report -> {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
