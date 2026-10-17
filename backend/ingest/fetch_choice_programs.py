"""Download M-DCPS magnet and parent-choice programs from the public catalog.

https://yourchoicemiami.org/program-search

robots.txt allows the public pages (only /wp-admin/ is disallowed).
Pages are requested slowly, with an identifying user agent. There is no login.
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "raw" / "mdcps_choice_programs.json"
BASE = "https://yourchoicemiami.org/program-search"
UA = "SchoolMatchMiami/1.0 (public program catalog; rate-limited)"
PAUSE = 0.6


def _text(fragment: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def parse_schools(html: str, program_type: str) -> list[dict]:
    schools = []
    for block in html.split('<div class="school">')[1:]:
        sid = re.search(r"school-details\?school=(\d+)", block)
        name = re.search(r'class="schoolName"><a[^>]*>(.*?)</a>', block, re.S)
        address = re.search(r'class="schoolAddress">(.*?)</div>', block, re.S)
        programs = [_text(p) for p in re.findall(r"<li><span[^>]*>(.*?)</span></li>", block, re.S)]
        programs = [p for p in programs if p]
        schools.append({
            "mdcps_id": sid.group(1).zfill(4) if sid else None,
            "name": _text(name.group(1)) if name else None,
            "address": _text(address.group(1)) if address else None,
            "programs": programs,
            "program_type": program_type,
            "source_url": f"https://yourchoicemiami.org/program-search/school-details?school={sid.group(1)}" if sid else BASE,
        })
    return schools


def _page_count(html: str, program_type: str) -> int:
    pages = [int(n) for n in re.findall(rf"program_type={program_type}&pg=(\d+)", html)]
    return max(pages) if pages else 1


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    collected = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []
    with httpx.Client(timeout=40, headers={"User-Agent": UA}, follow_redirects=True) as client:
        robots = client.get("https://yourchoicemiami.org/robots.txt")
        robots.raise_for_status()
        if "Disallow: /program-search" in robots.text:
            raise RuntimeError("robots.txt disallows /program-search")
        for program_type in ("choice", "magnet"):
            first = client.get(BASE, params={"program_type": program_type, "display": 100, "pg": 1})
            first.raise_for_status()
            html = first.text
            if "sucuri" in html.lower() or "you are being redirected" in html.lower():
                raise RuntimeError(
                    "yourchoicemiami.org returned a bot challenge. "
                    "This script does not solve it. Use the saved page snapshots in data/raw/."
                )
            if "schoolName" not in html:
                raise RuntimeError(f"{program_type} page did not contain the public catalog")
            pages = _page_count(html, program_type)
            batch = parse_schools(html, program_type)
            print(f"{program_type} page 1/{pages}: {len(batch)} schools", flush=True)
            rows.extend(batch)
            for page in range(2, pages + 1):
                time.sleep(PAUSE)
                response = client.get(BASE, params={"program_type": program_type, "display": 100, "pg": page})
                response.raise_for_status()
                batch = parse_schools(response.text, program_type)
                print(f"{program_type} page {page}/{pages}: {len(batch)} schools", flush=True)
                rows.extend(batch)
            time.sleep(PAUSE)
    payload = {
        "source": BASE,
        "collected_at": collected,
        "note": "Program names as published. Admissions eligibility rules are not on these list pages.",
        "schools": rows,
    }
    OUT.write_text(json.dumps(payload))
    print(f"{len(rows)} school rows -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
