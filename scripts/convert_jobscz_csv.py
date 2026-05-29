#!/usr/bin/env python3
"""Convert Apify Jobs.cz scraper CSV → JSON compatible with normalise_scraped_ads.py.

Drops noisy columns (locations/1..2, fields/*, salary, html), maps the
flat scraper schema to our JobAd-friendly shape, and writes a single
JSON array to `data/raw_ads/scraped/<source-stem>.json`.

Usage:
    python scripts/convert_jobscz_csv.py path/to/dataset.csv [more.csv ...]

Idempotent: re-running overwrites the output JSON. Dedup across input
files is keyed on `job_id`.
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

from cv_bau_students.config import SCRAPED_ADS_DIR

# Permissive — scraper rows can carry massive HTML descriptions.
csv.field_size_limit(sys.maxsize)


LEVEL_KEYWORDS = [
    ("lead", "lead"),
    ("head of", "lead"),
    ("principal", "lead"),
    ("senior", "senior"),
    ("sr. ", "senior"),
    ("medior", "medior"),
    ("middle ", "medior"),
    ("intermediate", "medior"),
    ("junior", "junior"),
    ("jr.", "junior"),
    ("trainee", "junior"),
    ("intern", "junior"),
    ("praktikant", "junior"),
]

DOMAIN_KEYWORDS = [
    ("data analyst", "data-analyst"),
    ("data analyt", "data-analyst"),
    ("data scientist", "data-analyst"),
    ("data engineer", "data-analyst"),
    ("front-end", "frontend-developer"),
    ("frontend", "frontend-developer"),
    ("front end", "frontend-developer"),
    ("react", "frontend-developer"),
    ("vue", "frontend-developer"),
    ("back-end", "backend-developer"),
    ("backend", "backend-developer"),
    ("back end", "backend-developer"),
    ("java", "backend-developer"),
    ("python", "backend-developer"),
    ("php", "backend-developer"),
    ("fullstack", "backend-developer"),
    ("full-stack", "backend-developer"),
    ("ux", "ux-designer"),
    ("ui design", "ux-designer"),
    ("product designer", "ux-designer"),
    ("qa", "qa-engineer"),
    ("tester", "qa-engineer"),
    ("project manager", "project-manager"),
    ("projektový manažer", "project-manager"),
    ("scrum master", "project-manager"),
    ("product manager", "project-manager"),
    ("controller", "controller"),
    ("finanční analytik", "controller"),
    ("marketing analyt", "marketing-analyst"),
    ("marketing manager", "marketing-analyst"),
    ("seo specialist", "marketing-analyst"),
]


def _detect_level(title: str, description: str) -> str:
    haystack = f"{title} {description}".lower()
    for needle, level in LEVEL_KEYWORDS:
        if needle in haystack:
            return level
    return "medior"  # default per the normaliser's contract


def _detect_domain(title: str, professions: list[str], category: str) -> str:
    haystack = " ".join([title, category, *professions]).lower()
    for needle, domain in DOMAIN_KEYWORDS:
        if needle in haystack:
            return domain
    # Discard junky scraper classifier paths ("jd/is*it:..."); default
    # "general" so the matcher's domain-based level checklist skips
    # cleanly instead of NULLing on a path string.
    return "general"


def _detect_remote_mode(description: str, location: str) -> str:
    body = (description or "").lower()
    if "remote" in body or "fully remote" in body or "home office" in body or "100 % home" in body:
        if "hybrid" in body:
            return "hybrid"
        return "remote"
    if "hybrid" in body or "částečně z domova" in body:
        return "hybrid"
    return "onsite"


_WS_RE = re.compile(r"\s+")


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return _WS_RE.sub(" ", text).strip()


def convert_one(csv_path: Path, seen_ids: set[str]) -> list[dict]:
    """Read a Jobs.cz CSV and return a list of JSON-ready records.

    `seen_ids` is mutated to deduplicate across multiple input files.
    """
    records: list[dict] = []
    with csv_path.open(encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            job_id = (row.get("job_id") or "").strip()
            dedup_key = job_id or (row.get("url") or "").strip()
            if not dedup_key or dedup_key in seen_ids:
                continue
            seen_ids.add(dedup_key)

            title = _clean(row.get("title"))
            description = _clean(row.get("description_text"))
            if not title or not description:
                continue

            professions = [
                _clean(row.get(f"professions/{i}")) for i in range(6) if row.get(f"professions/{i}")
            ]
            city = _clean(row.get("locations/0/city")) or _clean(row.get("location"))

            record = {
                "job_id": job_id,
                "title": title,
                "company": _clean(row.get("company")),
                "location": city or "Czech Republic",
                "remote_mode": _detect_remote_mode(description, city),
                "level": _detect_level(title, description),
                "domain": _detect_domain(title, professions, _clean(row.get("category"))),
                "description": description,
                "category": _clean(row.get("category")),
                "professions": professions,
                "search_keyword": _clean(row.get("search_keyword")),
                "search_location": _clean(row.get("search_location")),
                "suitable_for_graduate": _clean(row.get("suitable_for_graduate")).lower()
                in {"true", "1", "yes"},
                "date_posted": _clean(row.get("date_posted")),
                "url": _clean(row.get("url")),
                "source_file": csv_path.name,
            }
            records.append(record)
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert Jobs.cz scraper CSV → JSON.")
    parser.add_argument("csv_paths", nargs="+", type=Path)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Override output JSON file path. Default: data/raw_ads/scraped/<stem>.json",
    )
    args = parser.parse_args()

    SCRAPED_ADS_DIR.mkdir(parents=True, exist_ok=True)

    seen_ids: set[str] = set()
    grouped: dict[Path, list[dict]] = {}
    for csv_path in args.csv_paths:
        if not csv_path.exists():
            print(f"WARN: missing {csv_path}", file=sys.stderr)
            continue
        records = convert_one(csv_path, seen_ids)
        out_path = args.out or (SCRAPED_ADS_DIR / f"{csv_path.stem}.json")
        grouped.setdefault(out_path, []).extend(records)

    written = 0
    for out_path, records in grouped.items():
        with out_path.open("w", encoding="utf-8") as fh:
            json.dump(records, fh, ensure_ascii=False, indent=2)
        print(f"Wrote {len(records)} records → {out_path}")
        written += len(records)

    print(f"\nTotal unique ads written: {written}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
