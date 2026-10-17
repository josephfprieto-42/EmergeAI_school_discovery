"""Download public program, coursework, and sports files for Miami-Dade schools.

Sources, all keyless:

- Miami-Dade magnet and parent-choice programs
  https://yourchoicemiami.org/program-search
  One row per published program, joined later on the M-DCPS location number in the URL.

- Civil Rights Data Collection 2021-22, via the Urban Institute Education Data Portal
  https://educationdata.urban.org/documentation/
  AP, IB, and gifted-and-talented enrollment for LEA 1200390. Counts are summed
  across race and sex. Negative reserve codes (missing, not applicable) are not
  treated as zero.

- FHSAA member-school directory
  https://www.fhsaahome.org/widget/school-directory-locations
  Interscholastic sports for member high schools. Staff names on the directory
  page are not stored.

Nothing is inferred. A school absent from a file stays unmatched.
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import httpx

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
CHOICE_URL = "https://yourchoicemiami.org/program-search"
CRDC_URL = "https://educationdata.urban.org/api/v1/schools/crdc/ap-ib-enrollment/2021/race/sex/"
FHSAA_URL = "https://www.fhsaahome.org/widget/school-directory-locations"
LEAID = "1200390"


class _ChoiceParser(HTMLParser):
    """Pull school number, name, and program titles from one search page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.schools: list[dict] = []
        self._school: dict | None = None
        self._kind: str | None = None
        self._capture: str | None = None
        self._buf: list[str] = []
        self._test = False
        self._in_list = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k: v or "" for k, v in attrs}
        classes = set(attr.get("class", "").split())
        if tag == "div" and classes == {"school"}:
            self._flush_program()
            if self._school and self._school.get("mdcps_id"):
                self.schools.append(self._school)
            self._school = {"mdcps_id": None, "name": None, "programs": []}
            self._kind = None
            self._in_list = False
            return
        if self._school is None:
            return
        if tag == "a" and "school=" in attr.get("href", ""):
            match = re.search(r"school=(\d+)", attr["href"])
            if match:
                self._school["mdcps_id"] = match.group(1).zfill(4)
            if "schoolName" in classes or (self._school["name"] is None and tag == "a"):
                self._capture = "name"
                self._buf = []
        elif tag == "h4":
            self._flush_program()
            self._capture = "kind"
            self._buf = []
        elif tag == "ul" and "programList" in classes:
            self._in_list = True
        elif tag == "li" and self._kind and self._in_list:
            self._flush_program()
            self._capture = "program"
            self._buf = []
            self._test = False
        elif tag == "small" and self._capture == "program":
            self._capture = "flag"

    def handle_endtag(self, tag: str) -> None:
        if tag in {"a", "h4"} and self._capture in {"name", "kind"}:
            text = _clean("".join(self._buf))
            if self._capture == "name" and self._school is not None and text:
                self._school["name"] = text
            elif self._capture == "kind":
                low = text.lower()
                if "magnet" in low:
                    self._kind = "magnet"
                elif "choice" in low:
                    self._kind = "choice"
                else:
                    self._kind = None
            self._capture = None
            self._buf = []
        elif tag == "small" and self._capture == "flag":
            self._capture = "program"
        elif tag == "ul" and self._in_list:
            self._flush_program()
            self._in_list = False
        elif tag == "li" and self._capture == "program":
            self._flush_program()

    def handle_data(self, data: str) -> None:
        if self._capture == "flag" and re.search(r"test required|audition", data, re.I):
            self._test = True
        elif self._capture in {"name", "kind", "program"}:
            self._buf.append(data)

    def close(self) -> None:
        self._flush_program()
        if self._school and self._school.get("mdcps_id"):
            self.schools.append(self._school)
        super().close()

    def _flush_program(self) -> None:
        if self._capture == "program" and self._school is not None and self._kind:
            name = _clean("".join(self._buf))
            if name and re.search(r"[A-Za-z]", name) and len(name) > 2:
                self._school["programs"].append({
                    "name": name,
                    "kind": self._kind,
                    "test_required": self._test,
                })
        if self._capture == "program":
            self._capture = None
            self._buf = []
            self._test = False


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _get(client: httpx.Client, url: str, **kwargs) -> httpx.Response:
    response = client.get(url, **kwargs)
    response.raise_for_status()
    return response


def fetch_choice_programs(client: httpx.Client) -> dict:
    schools: dict[str, dict] = {}
    page = 1
    while page <= 20:
        response = _get(client, CHOICE_URL, params={
            "grade": "",
            "program_type": "",
            "subtheme": "",
            "theme": "",
            "display": "100",
            "pg": str(page),
        })
        parser = _ChoiceParser()
        parser.feed(response.text)
        parser.close()
        fresh = 0
        for school in parser.schools:
            key = school["mdcps_id"]
            current = schools.setdefault(key, {"mdcps_id": key, "name": school["name"], "programs": []})
            if school.get("name"):
                current["name"] = school["name"]
            seen = {(p["kind"], p["name"]) for p in current["programs"]}
            for program in school["programs"]:
                marker = (program["kind"], program["name"])
                if marker not in seen:
                    current["programs"].append(program)
                    seen.add(marker)
                    fresh += 1
        print(f"  choice page {page}: {len(parser.schools)} schools, {fresh} new programs")
        if not parser.schools or fresh == 0:
            break
        page += 1
        time.sleep(0.3)
    rows = [s for s in schools.values() if s["programs"]]
    return {
        "source": CHOICE_URL,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "schools": rows,
    }


def _reported(value: object) -> int | None:
    """A CRDC count, or None when the cell is a negative reserve code."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = int(value)
    return number if number >= 0 else None


def fetch_crdc(client: httpx.Client) -> dict:
    fields = (
        "enrl_AP", "enrl_AP_math", "enrl_AP_science", "enrl_AP_compsci",
        "enrl_AP_language", "enrl_AP_other", "enrl_IB", "enrl_gifted_talented",
    )
    # race 99 / sex 99 is the published total. The other rows repeat it by group.
    totals: dict[str, dict[str, int | None]] = {}
    parts: dict[str, dict[str, int | None]] = {}
    url: str | None = CRDC_URL
    params: dict[str, str] | None = {"leaid": LEAID}
    pages = 0
    while url:
        response = _get(client, url, params=params)
        payload = response.json()
        pages += 1
        for row in payload.get("results") or []:
            nces = str(row.get("ncessch") or "")
            if not nces:
                continue
            is_total = row.get("race") == 99 and row.get("sex") == 99
            is_part = row.get("race") in range(1, 8) and row.get("sex") in (1, 2)
            if not is_total and not is_part:
                continue
            target = totals if is_total else parts
            bucket = target.setdefault(nces, {field: None for field in fields})
            for field in fields:
                count = _reported(row.get(field))
                if count is None:
                    continue
                if is_total:
                    bucket[field] = count
                else:
                    bucket[field] = (bucket[field] or 0) + count
        url = payload.get("next")
        params = None
        print(f"  crdc page {pages}: {len(totals)} schools so far")
    for nces, fallback in parts.items():
        bucket = totals.setdefault(nces, {field: None for field in fields})
        for field in fields:
            if bucket[field] is None and fallback[field] is not None:
                bucket[field] = fallback[field]
    return {
        "source": CRDC_URL,
        "year": 2021,
        "leaid": LEAID,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "results": [{"ncessch": nces, **counts} for nces, counts in sorted(totals.items())],
    }


_MARKER = re.compile(
    r"geocodeAddress\(\s*\"[^\"]+\"\s*,\s*\"[^\"]+\"\s*,\s*geocoder\s*,\s*map\s*,\s*\"[^\"]+\"\s*,\s*\"(.*?)\"\s*\)",
    re.S,
)
_FIELD = re.compile(r"font-weight:600\\?'>([^<]+):</span>\s*([^<]*)")


def _sport_parts(label: str) -> tuple[str, str | None]:
    if "," in label:
        sport, group = label.split(",", 1)
        return sport.strip(), group.strip() or None
    return label.strip(), None


def fetch_fhsaa(client: httpx.Client) -> dict:
    page = _get(client, FHSAA_URL).text
    options = re.findall(r'<select[^>]*name="sport_id">(.*?)</select>', page, re.S)
    if not options:
        raise RuntimeError("FHSAA sport list was not on the directory page")
    sports = re.findall(r'<option value="(\d+)">([^<]+)</option>', options[0])
    sports = [(sid, _clean(name)) for sid, name in sports if sid and name.lower() != "select"]
    rows = []
    for sport_id, label in sports:
        body = _get(client, FHSAA_URL, params={"sport_id": sport_id, "school_id": ""}).text
        schools = []
        seen: set[tuple[str, str]] = set()
        for blob in _MARKER.findall(body):
            text = blob.replace("\\'", "'").replace("\\n", " ")
            fields = {re.sub(r"\s+", " ", k).strip(" :"): _clean(v) for k, v in _FIELD.findall(text)}
            full_name = fields.get("School Full Name")
            short = re.search(r"firstHeading[^>]*>([^<]+)", text)
            name = full_name or (_clean(short.group(1)) if short else "")
            zip_code = fields.get("Physical Zip") or ""
            if not name or (name, zip_code) in seen:
                continue
            seen.add((name, zip_code))
            schools.append({
                "name": name,
                "zip": zip_code or None,
                "address": fields.get("Street Address") or None,
            })
        sport, group = _sport_parts(label)
        rows.append({
            "sport_id": sport_id,
            "label": label,
            "sport": sport,
            "group": group,
            "schools": schools,
        })
        print(f"  fhsaa {label}: {len(schools)} schools")
        time.sleep(0.2)
    return {
        "source": FHSAA_URL,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "sports": rows,
    }


def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    wanted = set(sys.argv[1:]) or {"choice", "crdc", "fhsaa"}
    with httpx.Client(timeout=90, headers={"User-Agent": UA}, follow_redirects=True) as client:
        if "choice" in wanted:
            print("M-DCPS choice programs")
            choice = fetch_choice_programs(client)
            path = RAW / "mdcps_programs.json"
            path.write_text(json.dumps(choice))
            programs = sum(len(s["programs"]) for s in choice["schools"])
            print(f"  {len(choice['schools'])} schools, {programs} programs -> {path.name}")

        if "crdc" in wanted:
            print("CRDC 2021-22 AP, IB, and gifted enrollment")
            crdc = fetch_crdc(client)
            path = RAW / "crdc_academics.json"
            path.write_text(json.dumps(crdc))
            print(f"  {len(crdc['results'])} schools -> {path.name}")

        if "fhsaa" in wanted:
            print("FHSAA sports directory")
            fhsaa = fetch_fhsaa(client)
            path = RAW / "fhsaa_sports.json"
            path.write_text(json.dumps(fhsaa))
            print(f"  {len(fhsaa['sports'])} sports -> {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
