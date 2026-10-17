"""Download school / child-care point layers from Miami-Dade County Open Data (ArcGIS).

Writes one JSON file per layer into data/raw/. No API key required.
Source: https://gis-mdc.opendata.arcgis.com/
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

BASE = "https://services.arcgis.com/8Pc9XBTAsYuxx9Ny/arcgis/rest/services"
LAYERS = {
    "public": "SchoolSite_gdb",
    "charter": "CharterSchool_gdb",
    "private": "PrivateSchool_gdb",
    "daycare": "Daycare_gdb",
    "headstart": "HeadStart_gdb",
}
RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"


def fetch_layer(service: str) -> list[dict]:
    """Page through a FeatureServer layer and return all features (WGS84)."""
    url = f"{BASE}/{service}/FeatureServer/0/query"
    features: list[dict] = []
    offset = 0
    page = 2000
    with httpx.Client(timeout=60) as client:
        while True:
            params = {
                "where": "1=1",
                "outFields": "*",
                "outSR": "4326",
                "f": "json",
                "resultOffset": offset,
                "resultRecordCount": page,
            }
            r = client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                raise RuntimeError(data["error"])
            batch = data.get("features", [])
            features.extend(batch)
            if not data.get("exceededTransferLimit") or not batch:
                break
            offset += len(batch)
    return features


def main() -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for key, service in LAYERS.items():
        print(f"fetching {service} ...", end=" ", flush=True)
        feats = fetch_layer(service)
        out = RAW_DIR / f"mdc_{key}.json"
        out.write_text(json.dumps({"service": service, "features": feats}))
        print(f"{len(feats)} features -> {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
