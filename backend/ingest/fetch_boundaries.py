"""Download Miami-Dade public-school attendance boundaries from county ArcGIS.

Source (public, keyless):
  https://gis.miamidade.gov/arcgis/rest/services/CommunityServices/MD_Educational/MapServer
  layers 9 elementary, 11 middle, 10 high

Geometry is stored in WGS84. No scraping. One paged query per layer.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "raw" / "mdc_attendance_boundaries.json"
SERVICE = "https://gis.miamidade.gov/arcgis/rest/services/CommunityServices/MD_Educational/MapServer"
LAYERS = {
    "elementary": 9,
    "high": 10,
    "middle": 11,
}
UA = "SchoolMatchMiami/1.0 (public ArcGIS research; attendance boundaries)"


def _short(attrs: dict, marker: str) -> dict:
    out = {}
    for key, value in attrs.items():
        if marker in key:
            out[key.split(".")[-1]] = value
    return out


def _fetch_layer(client: httpx.Client, level: str, layer_id: int) -> list[dict]:
    url = f"{SERVICE}/{layer_id}/query"
    features: list[dict] = []
    offset = 0
    page = 100
    while True:
        params = {
            "where": "1=1",
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": "4326",
            "geometryPrecision": "5",
            "f": "json",
            "resultOffset": offset,
            "resultRecordCount": page,
        }
        response = client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise RuntimeError(payload["error"])
        batch = payload.get("features") or []
        for feature in batch:
            attrs = feature.get("attributes") or {}
            boundary = _short(attrs, "AttendanceBoundary.")
            site = _short(attrs, ".SchoolSite.")
            rings = (feature.get("geometry") or {}).get("rings") or []
            features.append({
                "level": level,
                "layer_id": layer_id,
                "boundary": boundary,
                "site": site,
                "rings": rings,
            })
        print(f"  {level}: {len(features)}", flush=True)
        if not payload.get("exceededTransferLimit") or not batch:
            break
        offset += len(batch)
        time.sleep(0.3)
    return features


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    collected = datetime.now(timezone.utc).isoformat()
    all_features: list[dict] = []
    with httpx.Client(timeout=120, headers={"User-Agent": UA}) as client:
        meta = client.get(f"{SERVICE}/9", params={"f": "json"})
        meta.raise_for_status()
        description = (meta.json().get("description") or "")[:800]
        copyright_text = meta.json().get("copyrightText") or ""
        for level, layer_id in LAYERS.items():
            print(f"fetching {level} layer {layer_id}", flush=True)
            all_features.extend(_fetch_layer(client, level, layer_id))
    # Guard against a state-plane response, which would silently break point-in-polygon.
    sample = next((f for f in all_features if f["rings"]), None)
    if sample:
        lon, lat = sample["rings"][0][0]
        if not (-83 < lon < -79 and 24 < lat < 27):
            raise RuntimeError(f"geometry is not WGS84 Miami-Dade: {lon}, {lat}")
    payload = {
        "source": SERVICE,
        "collected_at": collected,
        "description": description,
        "copyright": copyright_text,
        "features": all_features,
    }
    OUT.write_text(json.dumps(payload))
    print(f"{len(all_features)} zones -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
