"""Camera limits for the map, taken from the school coordinates."""
from __future__ import annotations

import math

from ..config import MIAMI_BOUNDS
from ..db import connect

MAP_BUFFER_MILES = 30
_EARTH_MILES = 3958.8


def expand_bounds(
    south: float, west: float, north: float, east: float, miles: float
) -> tuple[float, float, float, float]:
    """Grow a lat/lon box by `miles` on each side.

    Latitude uses a constant miles-per-degree. Longitude uses the midpoint
    latitude, where a degree of longitude is shorter than at the equator.
    """
    miles_per_deg_lat = _EARTH_MILES * math.pi / 180
    dlat = miles / miles_per_deg_lat
    mid_lat = (south + north) / 2
    dlon = miles / (miles_per_deg_lat * math.cos(math.radians(mid_lat)))
    return south - dlat, west - dlon, north + dlat, east + dlon


def dataset_map_bounds(buffer_miles: float = MAP_BUFFER_MILES) -> dict[str, float]:
    """Bounding box of every school, plus `buffer_miles` on each side.

    Falls back to the county box when the database has no coordinates, so
    map config still loads before the database is built.
    """
    fallback = MIAMI_BOUNDS
    try:
        con = connect()
    except RuntimeError:
        south, west, north, east = fallback
        return {"south": south, "west": west, "north": north, "east": east}
    try:
        row = con.execute(
            """SELECT MIN(lat) AS south, MAX(lat) AS north,
                      MIN(lon) AS west, MAX(lon) AS east
               FROM schools
               WHERE lat IS NOT NULL AND lon IS NOT NULL"""
        ).fetchone()
    finally:
        con.close()
    if row is None or row["south"] is None:
        south, west, north, east = fallback
        return {"south": south, "west": west, "north": north, "east": east}
    south, west, north, east = expand_bounds(
        float(row["south"]), float(row["west"]), float(row["north"]), float(row["east"]), buffer_miles
    )
    return {"south": south, "west": west, "north": north, "east": east}
