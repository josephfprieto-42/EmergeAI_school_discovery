from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..config import GOOGLE_GEOCODING_KEY, GOOGLE_MAP_ID, GOOGLE_MAPS_BROWSER_KEY, MIAMI_BOUNDS, MIAMI_CENTER, OPENAI_API_KEY
from ..services.geocode import geocode

router = APIRouter(prefix="/api", tags=["geo"])


@router.get("/config")
def config():
    """Public, browser-safe configuration. Only the Maps JavaScript key is exposed
    (it must be HTTP-referrer restricted in Google Cloud)."""
    return {
        "maps_browser_key": GOOGLE_MAPS_BROWSER_KEY or None,
        "map_id": GOOGLE_MAP_ID or None,
        "center": {"lat": MIAMI_CENTER[0], "lng": MIAMI_CENTER[1]},
        "bounds": {
            "south": MIAMI_BOUNDS[0],
            "west": MIAMI_BOUNDS[1],
            "north": MIAMI_BOUNDS[2],
            "east": MIAMI_BOUNDS[3],
        },
        "features": {
            "llm": bool(OPENAI_API_KEY),
            "google_geocoding": bool(GOOGLE_GEOCODING_KEY),
            "google_maps": bool(GOOGLE_MAPS_BROWSER_KEY),
        },
    }


@router.get("/geocode")
def geocode_endpoint(q: str = Query(..., min_length=2)):
    res = geocode(q)
    if not res:
        raise HTTPException(404, "Could not locate that place in Miami-Dade County")
    return res
