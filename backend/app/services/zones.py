"""Point-in-polygon lookup for Miami-Dade attendance boundaries.

Polygons are loaded once per database file and reused. A missing table means the
enrichment has not been applied yet; lookups then return nothing.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from ..db import DB_PATH

_CACHE: dict[str, Any] = {"mtime": None, "zones": []}


def _point_in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat):
            denom = (yj - yi) or 1e-15
            if lon < (xj - xi) * (lat - yi) / denom + xi:
                inside = not inside
        j = i
    return inside


def point_in_rings(lon: float, lat: float, rings: list[list[list[float]]]) -> bool:
    """Even-odd fill, so holes and multipart rings both work."""
    inside = False
    for ring in rings:
        if len(ring) >= 3 and _point_in_ring(lon, lat, ring):
            inside = not inside
    return inside


def _load(con: sqlite3.Connection) -> list[dict[str, Any]]:
    mtime = DB_PATH.stat().st_mtime if isinstance(DB_PATH, Path) and DB_PATH.exists() else None
    if _CACHE["mtime"] == mtime and _CACHE["zones"]:
        return _CACHE["zones"]
    try:
        rows = con.execute(
            """SELECT school_id, level, name, grades_text, grade_low, grade_high,
                      min_lon, min_lat, max_lon, max_lat, rings_json, feature_modified
               FROM attendance_zones"""
        ).fetchall()
    except sqlite3.OperationalError:
        _CACHE["mtime"] = mtime
        _CACHE["zones"] = []
        return []
    zones = []
    for row in rows:
        zones.append({
            "school_id": row[0],
            "level": row[1],
            "name": row[2],
            "grades_text": row[3],
            "grade_low": row[4],
            "grade_high": row[5],
            "min_lon": row[6],
            "min_lat": row[7],
            "max_lon": row[8],
            "max_lat": row[9],
            "rings": json.loads(row[10]),
            "feature_modified": row[11],
        })
    _CACHE["mtime"] = mtime
    _CACHE["zones"] = zones
    return zones


def clear_cache() -> None:
    _CACHE["mtime"] = None
    _CACHE["zones"] = []


def zones_containing(con: sqlite3.Connection, lat: float, lon: float) -> list[dict[str, Any]]:
    found = []
    for zone in _load(con):
        if zone["min_lon"] is None:
            continue
        if not (zone["min_lon"] <= lon <= zone["max_lon"] and zone["min_lat"] <= lat <= zone["max_lat"]):
            continue
        if point_in_rings(lon, lat, zone["rings"]):
            found.append({k: v for k, v in zone.items() if k != "rings"})
    return found


def assignments_by_school(con: sqlite3.Connection, lat: float, lon: float) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for zone in zones_containing(con, lat, lon):
        sid = zone.get("school_id")
        if sid is None:
            continue
        bucket = grouped.setdefault(sid, [])
        if not any(item["level"] == zone["level"] for item in bucket):
            bucket.append(zone)
    return grouped
