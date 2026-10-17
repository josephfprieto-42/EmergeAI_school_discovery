"""Download official Miami-Dade public school websites.

The county public-school GIS layer has no website field. The district directory
does: ``GET https://mdcpswebapps2.dadeschools.net/api/schools/{number}?details=true``
returns a ``web`` URL for that location number.

A URL is kept only when the directory returns it and a browser-style GET of
that exact URL finishes with HTTP 2xx. Nothing is guessed or rewritten.
The district homepage (no school path or query) is not stored as a school site.

Uses curl because this host rejects the TLS handshake from macOS Python 3.9.
"""
from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"
API = "https://mdcpswebapps2.dadeschools.net/api/schools/{number}?details=true"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
GENERIC_HOSTS = {
    "dadeschools.net",
    "www.dadeschools.net",
    "www2.dadeschools.net",
    "www3.dadeschools.net",
}
WORKERS = 8


def public_location_numbers() -> list[str]:
    """Location numbers for public schools the GIS build actually publishes."""
    payload = json.loads((RAW / "mdc_public.json").read_text())
    numbers: set[str] = set()
    for feature in payload.get("features") or []:
        attrs = feature.get("attributes") or {}
        if attrs.get("TYPE") in {"A", "O"}:
            continue
        if not attrs.get("LAT") or not attrs.get("LON") or not attrs.get("ID"):
            continue
        numbers.add(str(attrs["ID"]).strip().zfill(4))
    return sorted(numbers)


def acceptable_website(url: str | None) -> str | None:
    """Return the URL when it is an absolute http(s) school link, else None."""
    if not isinstance(url, str):
        return None
    url = url.strip()
    parsed = urlparse(url)
    host = parsed.netloc.lower().split(":")[0]
    if parsed.scheme not in {"http", "https"} or not host:
        return None
    if host in GENERIC_HOSTS and parsed.path in {"", "/"} and not parsed.query:
        return None
    return url


def curl(url: str, *, body: bool) -> tuple[int | None, str]:
    cmd = [
        "curl", "-sS", "-L", "--max-time", "25", "-A", UA,
        "-o", "/dev/stdout" if body else "/dev/null",
        "-w", "\n%{http_code}",
        url,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
    except (subprocess.TimeoutExpired, OSError):
        return None, ""
    if proc.returncode != 0:
        return None, ""
    text = proc.stdout or ""
    if "\n" not in text:
        return None, ""
    payload, code = text.rsplit("\n", 1)
    try:
        status = int(code.strip())
    except ValueError:
        return None, ""
    return status, payload if body else ""


def lookup(number: str) -> tuple[str, str | None, str | None, str]:
    """Return (location number, directory name, website or None, skip reason)."""
    status, payload = curl(API.format(number=number), body=True)
    if status is None:
        status, payload = curl(API.format(number=number), body=True)
    if status != 200 or not payload:
        return number, None, None, "directory_unavailable"
    try:
        record = json.loads(payload)
    except json.JSONDecodeError:
        return number, None, None, "directory_unavailable"
    if not isinstance(record, dict):
        return number, None, None, "directory_unavailable"
    name = record.get("name") if isinstance(record.get("name"), str) else None
    website = acceptable_website(record.get("web"))
    if not website:
        return number, name, None, "no_website"
    web_status, _ = curl(website, body=False)
    if web_status is None or not (200 <= web_status < 300):
        web_status, _ = curl(website, body=False)
    if web_status is None or not (200 <= web_status < 300):
        return number, name, None, f"link_not_ok:{web_status if web_status is not None else 'error'}"
    return number, name, website, ""


def main() -> int:
    numbers = public_location_numbers()
    print(f"checking {len(numbers)} public location numbers ...", flush=True)
    kept: list[dict[str, str]] = []
    skipped: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(lookup, number) for number in numbers]
        done = 0
        for future in as_completed(futures):
            number, name, website, reason = future.result()
            done += 1
            if website:
                row = {"mdcps_id": number, "website": website}
                if name:
                    row["name"] = name.strip()
                kept.append(row)
            else:
                skipped[reason] = skipped.get(reason, 0) + 1
            if done % 40 == 0 or done == len(numbers):
                print(f"  {done}/{len(numbers)} checked, {len(kept)} working", flush=True)
    kept.sort(key=lambda row: row["mdcps_id"])
    out = {
        "source": API,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "rule": "Directory web field, stored only when GET of that URL returns HTTP 2xx.",
        "schools": kept,
    }
    path = RAW / "mdcps_websites.json"
    path.write_text(json.dumps(out, indent=2) + "\n")
    print(f"kept {len(kept)} -> {path.name}")
    if skipped:
        print("skipped:", ", ".join(f"{k}={v}" for k, v in sorted(skipped.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
