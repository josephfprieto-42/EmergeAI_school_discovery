"""Download the NCES Common Core of Data directory for Miami-Dade County Public Schools
(LEA 1200390) via the Urban Institute Education Data API. No API key required.

Source: https://educationdata.urban.org/documentation/schools.html
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

API = "https://educationdata.urban.org/api/v1/schools/ccd/directory/{year}/"
LEAID = "1200390"  # Miami-Dade County Public Schools (includes district-sponsored charters)
RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"


def fetch(year: int) -> list[dict]:
    rows: list[dict] = []
    url: str | None = API.format(year=year)
    params = {"leaid": LEAID}
    with httpx.Client(timeout=90) as client:
        while url:
            r = client.get(url, params=params)
            r.raise_for_status()
            d = r.json()
            rows.extend(d.get("results", []))
            url = d.get("next")
            params = {}
    return rows


def main() -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for year in (2023, 2022):
        print(f"fetching NCES CCD {year} ...", end=" ", flush=True)
        try:
            rows = fetch(year)
        except Exception as e:  # noqa: BLE001
            print(f"failed: {e}")
            continue
        if rows:
            out = RAW_DIR / "nces_directory.json"
            out.write_text(json.dumps({"year": year, "leaid": LEAID, "results": rows}))
            print(f"{len(rows)} rows -> {out.name}")
            return 0
        print("empty")
    return 1


if __name__ == "__main__":
    sys.exit(main())
