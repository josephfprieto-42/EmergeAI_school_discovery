"""Attach published programs, coursework counts, and high-school sports.

Programs join on the M-DCPS location number. Coursework joins on the NCES id
already stored from the Common Core of Data. Sports join only when the FHSAA
directory name matches one high school in this catalog and not two.
"""
from __future__ import annotations

import json
import re
import sqlite3
from difflib import SequenceMatcher
from pathlib import Path

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"

_DROP = {"high", "school", "schools", "the", "of", "and", "at", "for", "a", "an", "hs"}


def _tag(cur: sqlite3.Cursor, school_id: int, source: str) -> None:
    row = cur.execute("SELECT sources FROM schools WHERE id = ?", (school_id,)).fetchone()
    current = json.loads(row[0] or "[]")
    if source not in current:
        current.append(source)
        cur.execute("UPDATE schools SET sources = ? WHERE id = ?", (json.dumps(current), school_id))


def _source(cur: sqlite3.Cursor, school_id: int, source: str, source_id: str, name: str | None) -> None:
    cur.execute(
        """INSERT INTO school_sources (school_id, source, source_id, name, address, match_method)
           VALUES (?,?,?,?,?,?)""",
        (school_id, source, source_id, name, None, "published_directory"),
    )
    _tag(cur, school_id, source)


def _compact(name: str) -> str:
    text = name.lower().replace("’", "").replace("'", "")
    text = re.sub(r"\bst\.?\b", "saint", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return "".join(sorted(token for token in text.split() if token not in _DROP))


def _zip5(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")[:5]


def ingest_programs(cur: sqlite3.Cursor, by_mdcps: dict[str, list[int]], same_school) -> None:
    path = RAW / "mdcps_programs.json"
    if not path.exists():
        print("WARNING: mdcps_programs.json not found; skipping choice programs")
        return
    payload = json.loads(path.read_text())
    matched_schools = 0
    program_rows = 0
    unmatched = 0
    for school in payload.get("schools") or []:
        mid = str(school.get("mdcps_id") or "").zfill(4)
        programs = school.get("programs") or []
        if not mid or not programs:
            continue
        sids = [
            sid for sid in (by_mdcps.get(mid) or [])
            if cur.execute("SELECT category FROM schools WHERE id = ?", (sid,)).fetchone()[0] in {"public", "charter"}
        ]
        if len(sids) > 1 and school.get("name"):
            named = []
            for sid in sids:
                row_name = cur.execute("SELECT name FROM schools WHERE id = ?", (sid,)).fetchone()[0]
                if same_school(school["name"], row_name):
                    named.append(sid)
            if named:
                sids = named
        if not sids:
            unmatched += 1
            continue
        matched_schools += 1
        for sid in sids:
            for program in programs:
                name = (program.get("name") or "").strip()
                kind = program.get("kind")
                if not name or kind not in {"magnet", "choice"}:
                    continue
                cur.execute(
                    """INSERT INTO school_programs (school_id, name, kind, test_required, source)
                       VALUES (?,?,?,?,?)""",
                    (sid, name, kind, 1 if program.get("test_required") else 0, "mdcps_choice"),
                )
                program_rows += 1
            _source(cur, sid, "mdcps_choice", mid, school.get("name"))
    print(f"M-DCPS programs: {matched_schools} schools, {program_rows} programs, {unmatched} unmatched")


def ingest_academics(cur: sqlite3.Cursor) -> None:
    path = RAW / "crdc_academics.json"
    if not path.exists():
        print("WARNING: crdc_academics.json not found; skipping CRDC coursework")
        return
    payload = json.loads(path.read_text())
    by_nces: dict[str, list[int]] = {}
    for sid, nces in cur.execute("SELECT school_id, ncessch FROM school_stats WHERE ncessch IS NOT NULL"):
        by_nces.setdefault(str(nces), []).append(sid)
    matched = 0
    fields = (
        "enrl_AP", "enrl_AP_math", "enrl_AP_science", "enrl_AP_compsci",
        "enrl_AP_language", "enrl_AP_other", "enrl_IB", "enrl_gifted_talented",
    )
    for row in payload.get("results") or []:
        sids = by_nces.get(str(row.get("ncessch") or ""))
        if not sids:
            continue
        values = tuple(row.get(field) for field in fields)
        if not any(value is not None for value in values):
            continue
        for sid in sids:
            cur.execute(
                """INSERT OR REPLACE INTO school_academics VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (sid, payload.get("year") or 2021, *values),
            )
            _source(cur, sid, "crdc", str(row.get("ncessch")), None)
        matched += 1
    print(f"CRDC {payload.get('year')}: {len(payload.get('results') or [])} rows, {matched} matched")


def _match_sports_school(name: str, zip_code: str | None, hosts: list[tuple]) -> int | None:
    """Return one school id, or None when the directory name is not unique here."""
    signature = _compact(name)
    if len(signature) < 4:
        return None
    ranked: list[tuple[float, int, str]] = []
    for sid, host_name, host_zip in hosts:
        host_signature = _compact(host_name)
        if not host_signature:
            continue
        if signature == host_signature:
            score = 1.0
        elif min(len(signature), len(host_signature)) >= 10 and (signature in host_signature or host_signature in signature):
            score = 0.92
        else:
            score = SequenceMatcher(None, signature, host_signature).ratio()
        ranked.append((score, sid, host_zip or ""))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    best = ranked[0][0]
    zip5 = _zip5(zip_code)
    zip_hits = [sid for score, sid, host_zip in ranked if score >= max(0.9, best - 0.03) and zip5 and zip5 == _zip5(host_zip)]
    strong = [sid for score, sid, _host_zip in ranked if score >= 0.96]
    if len(set(zip_hits)) == 1 and best >= 0.9:
        return zip_hits[0]
    if len(set(strong)) == 1:
        return strong[0]
    if len(strong) > 1 and zip5:
        zipped = [sid for score, sid, host_zip in ranked if score >= 0.96 and zip5 == _zip5(host_zip)]
        if len(set(zipped)) == 1:
            return zipped[0]
    return None


def ingest_sports(cur: sqlite3.Cursor) -> None:
    path = RAW / "fhsaa_sports.json"
    if not path.exists():
        print("WARNING: fhsaa_sports.json not found; skipping FHSAA sports")
        return
    payload = json.loads(path.read_text())
    hosts = cur.execute(
        """SELECT id, name, zip FROM schools
           WHERE category IN ('public', 'charter', 'private') AND grade_high >= 9"""
    ).fetchall()
    cache: dict[tuple[str, str], int | None] = {}
    rows = 0
    schools: set[int] = set()
    for sport in payload.get("sports") or []:
        label = (sport.get("sport") or "").strip()
        team = sport.get("group")
        if not label:
            continue
        for member in sport.get("schools") or []:
            key = (member.get("name") or "", member.get("zip") or "")
            if key not in cache:
                cache[key] = _match_sports_school(key[0], key[1] or None, hosts)
            sid = cache[key]
            if sid is None:
                continue
            cur.execute(
                "INSERT INTO school_sports (school_id, sport, team, source) VALUES (?,?,?,?)",
                (sid, label, team, "fhsaa"),
            )
            rows += 1
            if sid not in schools:
                schools.add(sid)
                _source(cur, sid, "fhsaa", key[0], key[0])
    print(f"FHSAA sports: {rows} team rows on {len(schools)} schools ({len(cache)} directory schools considered)")


def ingest(cur: sqlite3.Cursor, by_mdcps: dict[str, list[int]], same_school) -> None:
    ingest_programs(cur, by_mdcps, same_school)
    ingest_academics(cur)
    ingest_sports(cur)
