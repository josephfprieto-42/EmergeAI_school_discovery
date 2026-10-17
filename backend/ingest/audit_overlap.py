"""Audit school datasets for internal duplicates and cross-source overlap.

Writes data/audit/overlap_report.json. Does not modify schoolmatch.db;
rebuild with build_db.py to apply the same merges.
"""
from __future__ import annotations

import sys
from pathlib import Path

import build_db
import identity

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    publishable, excluded, raw_counts = build_db.collect_mdc()
    attributes, attr_counts = build_db.collect_attributes()
    raw_counts.update(attr_counts)
    school_links = identity.link_records(publishable)
    attr_links = identity.link_attributes(publishable, attributes)
    report = identity.build_report(publishable, school_links, attributes, attr_links, excluded, raw_counts)
    out = ROOT / "data" / "audit" / "overlap_report.json"
    identity.write_report(out, report)
    print(identity.format_summary(report))
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
