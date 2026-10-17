from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
GOOGLE_MAPS_BROWSER_KEY = os.getenv("GOOGLE_MAPS_BROWSER_KEY", "").strip()
GOOGLE_GEOCODING_KEY = os.getenv("GOOGLE_GEOCODING_KEY", "").strip() or GOOGLE_MAPS_BROWSER_KEY
GOOGLE_MAP_ID = os.getenv("GOOGLE_MAP_ID", "").strip()
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]

# Miami-Dade County approximate center / bounds used for geocode biasing.
MIAMI_CENTER = (25.76, -80.30)
MIAMI_BOUNDS = (25.13, -80.90, 25.98, -80.10)  # south, west, north, east
