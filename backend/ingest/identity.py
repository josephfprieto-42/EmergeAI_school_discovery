"""School identity resolution across Miami-Dade source files.

A school, the campus it sits on, and a program offered there are different
things. Records merge only when they are the same school (shared state school
number at one campus, the same license at one campus, or the same name at the
same address). Sharing an address or a coordinate is never enough on its own.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable, Optional

SOURCE_RANK = {
    "mdc_gis_charter": 0,
    "mdc_gis_public": 1,
    "mdc_gis_private": 2,
    "mdc_gis_headstart": 3,
    "mdc_gis_daycare": 4,
    "nces": 5,
    "fldoe": 6,
}

_STOP = frozenset({
    "the", "of", "and", "at", "for", "a", "an", "inc", "llc", "corp", "co",
    "school", "schools", "academy", "academies", "center", "centre",
    "campus", "site", "miami", "dade", "florida", "fl",
})
_PUNCT = re.compile(r"[^a-z0-9\s]")
_SPACE = re.compile(r"\s+")
_UNIT = re.compile(r"\b(?:ste|suite|apt|unit|floor|#)\b.*$")
_ADDR = (
    (r"\bnorth\b", "n"),
    (r"\bsouth\b", "s"),
    (r"\beast\b", "e"),
    (r"\bwest\b", "w"),
    (r"\bstreet\b", "st"),
    (r"\bavenue\b", "ave"),
    (r"\bboulevard\b", "blvd"),
    (r"\bdrive\b", "dr"),
    (r"\broad\b", "rd"),
    (r"\bcourt\b", "ct"),
    (r"\blane\b", "ln"),
    (r"\bterrace\b", "ter"),
    (r"\bplace\b", "pl"),
    (r"\bcircle\b", "cir"),
    (r"\bhighway\b", "hwy"),
    (r"\bparkway\b", "pkwy"),
)
_BLANK_LICENSE = frozenset({"", "EXEMPT", "N/A", "NA", "NONE", "0"})
_MAIN_CAMPUS = frozenset({"", "main", "main campus", "main office", "main center"})
# Tokens that may differ without making two names different organizations.
_MODIFIERS = frozenset({
    "north", "south", "east", "west", "campus", "preschool", "elementary", "middle",
    "high", "senior", "junior", "hs", "es", "ms", "pk", "pre", "ii", "iii", "iv",
    "2", "3", "4", "charter", "prep", "preparatory", "learning", "daycare", "day",
    "care", "child", "children", "early", "head", "start", "ehs", "annex", "building",
    "main", "upper", "lower",
})


def normalize_address(addr: Optional[str]) -> str:
    if not addr:
        return ""
    s = addr.lower().replace(".", " ").replace(",", " ").replace("'", "")
    s = _UNIT.sub(" ", s)
    for pat, rep in _ADDR:
        s = re.sub(pat, rep, s)
    s = _PUNCT.sub(" ", s)
    return _SPACE.sub(" ", s).strip()


def name_tokens(name: Optional[str]) -> frozenset[str]:
    s = (name or "").lower().replace("'", "").replace("’", "")
    s = _PUNCT.sub(" ", s)
    return frozenset(t for t in s.split() if t not in _STOP and len(t) > 1)


def name_similarity(a: Optional[str], b: Optional[str]) -> float:
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return 0.0
    inter = ta & tb
    if not inter:
        return 0.0
    jaccard = len(inter) / len(ta | tb)
    contain = len(inter) / min(len(ta), len(tb))
    extra = (ta | tb) - inter
    # A shorter name inside a longer one counts only when the extra words are
    # campus or grade modifiers, not a different operator ("FCAA at ...").
    if extra and extra <= _MODIFIERS and contain >= 0.9 and min(len(ta), len(tb)) >= 2:
        score = max(jaccard, contain)
    elif min(len(ta), len(tb)) == 1 and len(next(iter(inter))) < 8:
        score = jaccard
    else:
        score = jaccard
    ratio = SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio()
    if ratio >= 0.92 and (not extra or extra <= _MODIFIERS):
        score = max(score, ratio)
    return score


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _campus_label(label: Optional[str]) -> str:
    s = _SPACE.sub(" ", (label or "").strip().lower())
    return "" if s in _MAIN_CAMPUS else s


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s[:48] or "school"


@dataclass
class Record:
    source: str
    source_id: str
    name: str
    category: str
    subtype: str
    program_kind: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    mdcps_id: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    zip: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    grade_low: Optional[int] = None
    grade_high: Optional[int] = None
    grades_text: Optional[str] = None
    enrollment: Optional[int] = None
    capacity: Optional[int] = None
    year_established: Optional[int] = None
    coed: Optional[str] = None
    license_number: Optional[str] = None
    license_expires: Optional[str] = None
    status: Optional[str] = None
    region: Optional[str] = None
    campus_label: Optional[str] = None
    exclude_reason: Optional[str] = None
    address_norm: str = field(init=False)
    license_key: Optional[str] = field(init=False)

    def __post_init__(self) -> None:
        self.address_norm = normalize_address(self.address)
        lic = (self.license_number or "").strip().upper()
        self.license_key = None if lic in _BLANK_LICENSE else lic
        if self.mdcps_id:
            self.mdcps_id = str(self.mdcps_id).strip().zfill(4)


@dataclass(frozen=True)
class Link:
    left: int
    right: int
    relation: str
    score: float
    reason: str


@dataclass(frozen=True)
class AttrLink:
    school_index: int
    attr_index: int
    relation: str
    score: float
    reason: str


def _distance(a: Record, b: Record) -> Optional[float]:
    if a.lat is None or a.lon is None or b.lat is None or b.lon is None:
        return None
    return haversine_miles(a.lat, a.lon, b.lat, b.lon)


def _grades_overlap(a: Record, b: Record) -> Optional[bool]:
    if None in (a.grade_low, a.grade_high, b.grade_low, b.grade_high):
        return None
    if a.grade_high < b.grade_low or b.grade_high < a.grade_low:  # type: ignore[operator]
        return False
    return True


def _programs_incompatible(a: Record, b: Record) -> bool:
    kinds = {a.program_kind, b.program_kind}
    if "admin" in kinds:
        return True
    if "plc" in kinds and kinds != {"plc"}:
        return True
    if "headstart" in kinds and "school" in kinds:
        return True
    if "afterschool" in kinds and kinds != {"afterschool"}:
        return True
    if "daycare" in kinds and "school" in kinds and ({a.category, b.category} & {"public", "charter"}):
        return True
    return False


def _link(relation: str, score: float, reason: str) -> tuple[str, float, str]:
    return relation, score, reason


def classify(a: Record, b: Record) -> Optional[tuple[str, float, str]]:
    """Return (relation, score, reason) or None when the records are unrelated."""
    if a.program_kind == "attribute" or b.program_kind == "attribute":
        return None
    sim = name_similarity(a.name, b.name)
    dist = _distance(a, b)
    addr_match = bool(a.address_norm and a.address_norm == b.address_norm)
    # Early Head Start and Head Start are different programs, even in the same building.
    if a.program_kind == "headstart" and b.program_kind == "headstart" and a.subtype != b.subtype:
        if addr_match or (dist is not None and dist <= 0.05):
            return _link("same_campus_different_program", sim, "early Head Start and Head Start share a location")
        return None
    overlap = _grades_overlap(a, b)

    if a.mdcps_id and b.mdcps_id and a.mdcps_id != b.mdcps_id:
        if addr_match or (dist is not None and dist <= 0.08):
            if sim >= 0.8:
                return _link("ambiguous", sim, "different school numbers with similar names at the same location")
            return _link("same_campus_different_program", sim, "different school numbers share a location")
        return None

    if a.mdcps_id and a.mdcps_id == b.mdcps_id:
        kinds = {a.program_kind, b.program_kind}
        if "plc" in kinds and a.program_kind != b.program_kind:
            relation = "same_campus_different_program" if addr_match else "same_identity_different_campus"
            return _link(relation, 1.0, "primary learning center shares a school number with the instructional school")
        if _campus_label(a.campus_label) and _campus_label(b.campus_label) and _campus_label(a.campus_label) != _campus_label(b.campus_label):
            return _link("same_identity_different_campus", 1.0, "same school number, different campus labels")
        if overlap is False:
            return _link("same_identity_different_campus", 1.0, "same school number, non-overlapping grade spans")
        if addr_match:
            return _link("same_school", 1.0, "same school number and campus")
        if dist is not None and dist <= 0.1 and sim >= 0.75:
            return _link("ambiguous", sim, "same school number, nearby but different addresses")
        return _link("same_identity_different_campus", 1.0, "same school number, different address")

    if a.license_key and a.license_key == b.license_key:
        if _programs_incompatible(a, b):
            if addr_match:
                return _link("same_campus_different_program", sim, "same license number but different programs")
            return _link("ambiguous", sim, "same license number on different programs")
        if addr_match:
            return _link("same_school", max(sim, 0.9), "same license number and campus")
        if dist is not None and dist <= 0.08 and sim >= 0.6:
            return _link("ambiguous", sim, "same license number, nearby but different addresses")
        return _link("ambiguous", sim, "same license number at different locations")

    if a.license_key and b.license_key and a.license_key != b.license_key:
        if addr_match and sim >= 0.55:
            return _link("ambiguous", sim, "same address and partial name match but different license numbers")
        if addr_match:
            return _link("same_campus_different_program", sim, "different licenses share an address")
        return None

    if _programs_incompatible(a, b):
        close = dist is not None and dist <= 0.05 and sim >= 0.45
        if addr_match or close:
            return _link("same_campus_different_program", sim, "distinct programs share a location")
        return None

    if addr_match:
        private_daycare = (
            {a.category, b.category} <= {"private", "early_childhood"}
            and "daycare" in {a.program_kind, b.program_kind}
            and "school" in {a.program_kind, b.program_kind}
        )
        if sim >= 0.82 and {a.category, b.category} == {"public", "private"}:
            return _link("ambiguous", sim, "public and private records share a name and address")
        if sim >= 0.82 and overlap is not False:
            return _link("same_school", sim, "same name and campus")
        if sim >= 0.82 and overlap is False and private_daycare and "school" in {a.program_kind, b.program_kind}:
            return _link("same_school", sim, "same provider listed as a school and a licensed program")
        if sim >= 0.82:
            return _link("same_campus_different_program", sim, "same name and address but non-overlapping grades")
        if sim >= 0.5:
            return _link("ambiguous", sim, "same address with a partial name match")
        return _link("same_campus_different_program", sim, "shared address only")

    if dist is not None and dist <= 0.1 and sim >= 0.92 and overlap is not False:
        return _link("ambiguous", sim, "very similar names and nearby coordinates but different addresses")
    return None


def link_records(records: list[Record]) -> list[Link]:
    id_index: dict[str, list[int]] = defaultdict(list)
    addr_index: dict[str, list[int]] = defaultdict(list)
    lic_index: dict[str, list[int]] = defaultdict(list)
    cell_index: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, rec in enumerate(records):
        if rec.exclude_reason or rec.program_kind == "attribute":
            continue
        if rec.mdcps_id:
            id_index[rec.mdcps_id].append(i)
        if rec.address_norm:
            addr_index[rec.address_norm].append(i)
        if rec.license_key:
            lic_index[rec.license_key].append(i)
        if rec.lat is not None and rec.lon is not None:
            cell_index[(int(round(rec.lat * 1000)), int(round(rec.lon * 1000)))].append(i)

    seen: set[tuple[int, int]] = set()
    links: list[Link] = []

    def consider(i: int, j: int) -> None:
        if i == j:
            return
        if i > j:
            i, j = j, i
        if (i, j) in seen:
            return
        seen.add((i, j))
        hit = classify(records[i], records[j])
        if hit:
            relation, score, reason = hit
            links.append(Link(i, j, relation, score, reason))

    def pairs(buckets: Iterable[list[int]]) -> None:
        for bucket in buckets:
            for a in range(len(bucket)):
                for b in range(a + 1, len(bucket)):
                    consider(bucket[a], bucket[b])

    pairs(id_index.values())
    pairs(addr_index.values())
    pairs(lic_index.values())
    for (cx, cy), bucket in cell_index.items():
        neighbors = list(bucket)
        for dx in (0, 1):
            for dy in (0, 1):
                if dx == 0 and dy == 0:
                    continue
                neighbors.extend(cell_index.get((cx + dx, cy + dy), []))
        if len(neighbors) > 80:
            continue
        for a in range(len(neighbors)):
            for b in range(a + 1, len(neighbors)):
                consider(neighbors[a], neighbors[b])
    return links


def link_attributes(schools: list[Record], attrs: list[Record]) -> list[AttrLink]:
    index: dict[str, list[int]] = defaultdict(list)
    for i, school in enumerate(schools):
        if school.mdcps_id and not school.exclude_reason:
            index[school.mdcps_id].append(i)
    links: list[AttrLink] = []
    for j, attr in enumerate(attrs):
        hits = index.get(attr.mdcps_id or "", [])
        if not hits:
            continue
        for i in hits:
            links.append(AttrLink(i, j, "enriched", 1.0, "shared state school number"))
        instructional = [i for i in hits if schools[i].program_kind != "plc"]
        sims = [name_similarity(schools[i].name, attr.name) for i in instructional]
        if sims and max(sims) < 0.34:
            links.append(AttrLink(instructional[0], j, "ambiguous", max(sims), "school number matches but names look unrelated"))
    return links


def _find(parent: list[int], x: int) -> int:
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def _union(parent: list[int], a: int, b: int) -> None:
    ra, rb = _find(parent, a), _find(parent, b)
    if ra != rb:
        parent[rb] = ra


def cluster_same_school(n: int, links: list[Link]) -> list[list[int]]:
    parent = list(range(n))
    for link in links:
        if link.relation == "same_school":
            _union(parent, link.left, link.right)
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[_find(parent, i)].append(i)
    return list(groups.values())


def assign_campus_keys(records: list[Record], links: list[Link]) -> dict[int, str]:
    parent = list(range(len(records)))
    for link in links:
        if link.relation in {"same_school", "same_campus_different_program"}:
            _union(parent, link.left, link.right)
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(len(records)):
        groups[_find(parent, i)].append(i)
    keys: dict[int, str] = {}
    for members in groups.values():
        addrs = [records[i].address_norm for i in members if records[i].address_norm]
        if addrs:
            key = Counter(addrs).most_common(1)[0][0]
        else:
            rec = records[members[0]]
            key = f"geo:{rec.lat:.4f},{rec.lon:.4f}" if rec.lat is not None and rec.lon is not None else f"id:{rec.source}:{rec.source_id}"
        for i in members:
            keys[i] = key
    return keys


def choose_primary(group: list[Record]) -> Record:
    def key(rec: Record) -> tuple:
        return (
            0 if rec.program_kind == "school" else 1,
            0 if rec.category == "charter" else 1,
            SOURCE_RANK.get(rec.source, 9),
            0 if rec.enrollment else 1,
            -len(rec.name or ""),
        )

    return min(group, key=key)


def merge_records(group: list[Record], campus_key: Optional[str]) -> tuple[dict, list[dict]]:
    primary = choose_primary(group)
    ordered = sorted(group, key=lambda rec: SOURCE_RANK.get(rec.source, 9))

    def pick(attr: str):
        for rec in ordered:
            value = getattr(rec, attr)
            if value not in (None, ""):
                return value
        return None

    lows = [rec.grade_low for rec in group if rec.grade_low is not None]
    highs = [rec.grade_high for rec in group if rec.grade_high is not None]
    grade_low = min(lows) if lows else None
    grade_high = max(highs) if highs else None
    grades_text = primary.grades_text
    if primary.grade_low != grade_low or primary.grade_high != grade_high:
        grades_text = None

    mdcps_ids = {rec.mdcps_id for rec in group if rec.mdcps_id}
    mdcps = next(iter(mdcps_ids)) if len(mdcps_ids) == 1 else primary.mdcps_id
    license_number = next((rec.license_number for rec in ordered if rec.license_key), None)
    license_expires = next((rec.license_expires for rec in ordered if rec.license_expires), None)
    licenses = {rec.license_key for rec in group if rec.license_key}
    if mdcps:
        identity_key = f"mdcps:{mdcps}"
    elif len(licenses) == 1:
        identity_key = f"lic:{next(iter(licenses))}"
    else:
        identity_key = f"local:{_slug(primary.name)}:{campus_key or primary.source_id}"

    sources: list[str] = []
    for rec in ordered:
        if rec.source not in sources:
            sources.append(rec.source)
    category = "charter" if any(rec.category == "charter" for rec in group) else primary.category
    subtype = "charter" if category == "charter" else primary.subtype
    row = {
        "source": primary.source if category != "charter" else next(rec.source for rec in group if rec.category == "charter"),
        "source_id": primary.source_id if category != "charter" else next(rec.source_id for rec in group if rec.category == "charter"),
        "mdcps_id": mdcps,
        "name": primary.name if category != "charter" else next(rec.name for rec in group if rec.category == "charter"),
        "category": category,
        "subtype": subtype,
        "address": primary.address or pick("address"),
        "city": primary.city or pick("city"),
        "zip": primary.zip or pick("zip"),
        "phone": primary.phone or pick("phone"),
        "website": primary.website or pick("website"),
        "lat": primary.lat if primary.lat is not None else pick("lat"),
        "lon": primary.lon if primary.lon is not None else pick("lon"),
        "grade_low": grade_low,
        "grade_high": grade_high,
        "grades_text": grades_text or pick("grades_text"),
        "enrollment": pick("enrollment"),
        "capacity": pick("capacity"),
        "year_established": pick("year_established"),
        "coed": pick("coed"),
        "license_number": license_number,
        "license_expires": license_expires,
        "status": primary.status or pick("status"),
        "region": pick("region"),
        "identity_key": identity_key,
        "campus_key": campus_key,
        "campus_label": primary.campus_label or None,
        "sources": json.dumps(sources),
    }
    provenance = [
        {
            "source": rec.source,
            "source_id": rec.source_id,
            "name": rec.name,
            "address": rec.address,
            "match_method": "primary" if rec is primary else "same_school",
        }
        for rec in group
    ]
    return row, provenance


def _pair_key(left: str, right: str) -> str:
    a, b = sorted((left, right))
    return f"{a}|{b}"


def build_report(
    schools: list[Record],
    school_links: list[Link],
    attrs: list[Record],
    attr_links: list[AttrLink],
    excluded: list[Record],
    raw_counts: dict[str, int],
) -> dict:
    overlap: dict[str, Counter] = defaultdict(Counter)
    for link in school_links:
        left, right = schools[link.left], schools[link.right]
        overlap[_pair_key(left.source, right.source)][link.relation] += 1
    enriched_ids: dict[str, set[str]] = defaultdict(set)
    for link in attr_links:
        school, attr = schools[link.school_index], attrs[link.attr_index]
        overlap[_pair_key(school.source, attr.source)][link.relation] += 1
        if link.relation == "enriched" and school.mdcps_id:
            enriched_ids[_pair_key(school.source, attr.source)].add(school.mdcps_id)

    clusters = cluster_same_school(len(schools), school_links)
    merged = [group for group in clusters if len(group) > 1]
    internal_groups: dict[str, dict[str, int]] = defaultdict(lambda: {"groups": 0, "extra_rows": 0})
    cross_groups = 0
    cross_extra = 0
    for group in merged:
        sources = {schools[i].source for i in group}
        extra = len(group) - 1
        if len(sources) == 1:
            src = next(iter(sources))
            internal_groups[src]["groups"] += 1
            internal_groups[src]["extra_rows"] += extra
        else:
            cross_groups += 1
            cross_extra += extra

    by_identity: dict[str, set[str]] = defaultdict(set)
    for rec in schools:
        if rec.mdcps_id and rec.program_kind not in {"plc", "admin"}:
            by_identity[rec.mdcps_id].add(rec.address_norm or f"{rec.lat},{rec.lon}")

    ambiguous: list[dict] = []
    for link in school_links:
        if link.relation != "ambiguous":
            continue
        left, right = schools[link.left], schools[link.right]
        ambiguous.append({
            "left_source": left.source,
            "left_source_id": left.source_id,
            "left_name": left.name,
            "left_address": left.address,
            "right_source": right.source,
            "right_source_id": right.source_id,
            "right_name": right.name,
            "right_address": right.address,
            "score": round(link.score, 3),
            "reason": link.reason,
        })
    for link in attr_links:
        if link.relation != "ambiguous":
            continue
        school, attr = schools[link.school_index], attrs[link.attr_index]
        ambiguous.append({
            "left_source": school.source,
            "left_source_id": school.source_id,
            "left_name": school.name,
            "left_address": school.address,
            "right_source": attr.source,
            "right_source_id": attr.source_id,
            "right_name": attr.name,
            "right_address": attr.address,
            "score": round(link.score, 3),
            "reason": link.reason,
        })
    ambiguous.sort(key=lambda item: item["score"], reverse=True)

    overlap_out = {}
    for pair, counts in overlap.items():
        item = {relation: counts[relation] for relation in counts}
        if pair in enriched_ids:
            item["enriched_identities"] = len(enriched_ids[pair])
        overlap_out[pair] = item

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "raw_counts": raw_counts,
        "publishable_counts": dict(Counter(rec.source for rec in schools)),
        "excluded": dict(Counter(f"{rec.source}:{rec.exclude_reason}" for rec in excluded)),
        "attribute_counts": dict(Counter(rec.source for rec in attrs)),
        "overlap_by_pair": overlap_out,
        "internal_duplicate_groups": dict(internal_groups),
        "cross_source_merged_groups": cross_groups,
        "cross_source_rows_collapsed": cross_extra,
        "multi_campus_identities": sum(1 for places in by_identity.values() if len(places) > 1),
        "ambiguous_count": len(ambiguous),
        "ambiguous": ambiguous[:400],
        "rules": [
            "Same school: shared MDCPS/state school number on one campus, the same real license on one campus, or a strong name match at the same normalized address.",
            "Same school number at a different address is one identity with multiple campuses and is not collapsed.",
            "Head Start, after-school care, and primary learning centers stay separate from the instructional school even at the same address.",
            "A shared address or nearby coordinates without a name or identifier match is a campus link, not a merge.",
            "NCES and FLDOE rows enrich the matching school number. They are not inserted as separate schools.",
            "Partial name matches and conflicting licenses are flagged for review and left unmerged.",
        ],
    }


def format_summary(report: dict) -> str:
    lines = ["School identity audit"]
    lines.append("Raw rows: " + ", ".join(f"{k}={v}" for k, v in sorted(report["raw_counts"].items())))
    if report["excluded"]:
        lines.append("Excluded: " + ", ".join(f"{k}={v}" for k, v in sorted(report["excluded"].items())))
    header = f"{'dataset pair':42} {'same_school':>11} {'other_campus':>13} {'other_program':>14} {'enriched':>9} {'ambiguous':>10}"
    lines.append(header)
    for pair, counts in sorted(report["overlap_by_pair"].items()):
        lines.append(
            f"{pair:42} {counts.get('same_school', 0):11} {counts.get('same_identity_different_campus', 0):13} "
            f"{counts.get('same_campus_different_program', 0):14} {counts.get('enriched', 0):9} {counts.get('ambiguous', 0):10}"
        )
    lines.append(
        f"Merged duplicate groups inside one dataset: {sum(v['groups'] for v in report['internal_duplicate_groups'].values())} "
        f"({sum(v['extra_rows'] for v in report['internal_duplicate_groups'].values())} extra rows)"
    )
    lines.append(
        f"Cross-source schools merged: {report['cross_source_merged_groups']} groups, {report['cross_source_rows_collapsed']} extra rows"
    )
    lines.append(f"School numbers with more than one campus: {report['multi_campus_identities']}")
    lines.append(f"Ambiguous matches flagged for review: {report['ambiguous_count']}")
    return "\n".join(lines)


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2))
