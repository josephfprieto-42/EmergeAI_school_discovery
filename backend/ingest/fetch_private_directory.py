"""Download the Miami-Dade extract of the Florida private school directory.

The directory page is a public Excel download provided as a service to the public
under section 1002.42, Florida Statutes. robots.txt does not disallow this path.

DOE states that schools submit the annual survey and that the department does not
verify it. The saved file keeps that limitation in the metadata.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "raw" / "fl_private_directory_dade.xlsx"
META = ROOT / "data" / "raw" / "fl_private_directory_dade.json"
PAGE = "https://www.floridaschoolchoice.org/information/privateschooldirectory/DownloadExcelFile.aspx"
UA = "SchoolMatchMiami/1.0 (public directory download; Miami-Dade only)"

# Checkbox indexes on the public form, read from the rendered labels.
DADE = "ctl00$ContentPlaceHolder1$cblSelectDistrict$12"
EXTRA = [
    "ctl00$ContentPlaceHolder1$cblAdditionalInformation$0",   # nonprofit
    "ctl00$ContentPlaceHolder1$cblAdditionalInformation$1",   # FTC
    "ctl00$ContentPlaceHolder1$cblAdditionalInformation$2",   # enrollment by grade
    "ctl00$ContentPlaceHolder1$cblAdditionalInformation$3",   # grades
    "ctl00$ContentPlaceHolder1$cblAdditionalInformation$4",   # student type
    "ctl00$ContentPlaceHolder1$cblAdditionalInformation$5",   # accreditation
    "ctl00$ContentPlaceHolder1$cblAdditionalInformation$6",   # religious
    "ctl00$ContentPlaceHolder1$cblAdditionalInformation$7",   # denomination
    "ctl00$ContentPlaceHolder1$cblAdditionalInformation$8",   # FES unique abilities
    "ctl00$ContentPlaceHolder1$cblAdditionalInformation$9",   # PEP
    "ctl00$ContentPlaceHolder1$cblAdditionalInformation$10",  # FES educational options
]


def _hidden(html: str) -> dict[str, str]:
    fields = {}
    for match in re.finditer(r'<input[^>]*type="hidden"[^>]*>', html, re.I):
        tag = match.group(0)
        name = re.search(r'name="([^"]+)"', tag)
        value = re.search(r'value="([^"]*)"', tag)
        if name:
            fields[name.group(1)] = value.group(1) if value else ""
    return fields


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=120, headers={"User-Agent": UA}, follow_redirects=True) as client:
        page = client.get(PAGE)
        page.raise_for_status()
        fields = _hidden(page.text)
        if "__VIEWSTATE" not in fields:
            raise RuntimeError("directory form did not return a viewstate")
        data = dict(fields)
        data[DADE] = "on"
        for name in EXTRA:
            data[name] = "on"
        data["ctl00$ContentPlaceHolder1$btnDownload"] = "Download"
        posted = client.post(PAGE, data=data, headers={"Referer": PAGE})
        posted.raise_for_status()
        body = posted.content
        content_type = posted.headers.get("content-type", "")
    if body[:2] != b"PK" and b"<html" in body[:500].lower():
        raise RuntimeError(f"directory download returned HTML ({content_type}, {len(body)} bytes), not a workbook")
    OUT.write_bytes(body)
    META.write_text(
        '{"source": "%s", "collected_at": "%s", "district": "DADE", '
        '"verification": "school-reported annual survey; Florida DOE does not verify accuracy", '
        '"statute": "1002.42, Florida Statutes"}\n'
        % (PAGE, datetime.now(timezone.utc).isoformat())
    )
    print(f"{len(body)} bytes -> {OUT.name} ({content_type})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
