#!/usr/bin/env python3
"""Normalise scraped job-ad JSON dumps into JobAd rows.

Reads `data/raw_ads/scraped/*.json` (gitignored), maps the scraper's
schema to our `JobAd` Pydantic model, persists via the repository.

Conservative mapping — when a field is missing or ambiguous, defaults
are filled (`remote_mode='onsite'`, `level='medior'`) and the original
text lands in `raw_text` so downstream LLMs can recover if needed.
"""

import json
import sys
from pathlib import Path

from cv_bau_students.config import SCRAPED_ADS_DIR
from cv_bau_students.db import init_db
from cv_bau_students.jobads.repo import store_ad
from cv_bau_students.models import JobAd, LanguageRequirement


def _normalise(record: dict) -> JobAd | None:
    """Map a scraped record into a JobAd. Returns None when the row is
    too sparse to use (no title or no description text)."""
    title = (record.get("title") or "").strip()
    raw_text = (record.get("description") or record.get("text") or "").strip()
    if not title or not raw_text:
        return None

    must_have = _list_field(record, ("must_have", "requirements", "skills_required"))
    nice_to_have = _list_field(record, ("nice_to_have", "preferred", "skills_nice"))

    return JobAd(
        title=title,
        employer=record.get("company") or record.get("employer"),
        location=record.get("location") or "Czech Republic",
        remote_mode=record.get("remote_mode") or "onsite",  # type: ignore[arg-type]
        level=record.get("level") or "medior",  # type: ignore[arg-type]
        domain=record.get("domain") or "general",
        must_have=must_have,
        nice_to_have=nice_to_have,
        languages_required=_languages(record),
        raw_text=raw_text,
        source="scraped",
        ad_url=record.get("url") or record.get("link"),
    )


def _list_field(record: dict, keys: tuple[str, ...]) -> list[str]:
    for key in keys:
        value = record.get(key)
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [chunk.strip() for chunk in value.split(",") if chunk.strip()]
    return []


def _languages(record: dict) -> list[LanguageRequirement]:
    items = record.get("languages") or record.get("languages_required") or []
    out: list[LanguageRequirement] = []
    for item in items:
        if isinstance(item, dict):
            out.append(
                LanguageRequirement(
                    language=str(item.get("language", "")).strip(),
                    min_level=str(item.get("min_level", "")).strip(),
                )
            )
    return out


def main() -> int:
    if not SCRAPED_ADS_DIR.exists():
        print(f"No scraped-ads directory at {SCRAPED_ADS_DIR}", file=sys.stderr)
        return 1

    init_db()
    written = 0
    for file in sorted(Path(SCRAPED_ADS_DIR).glob("*.json")):
        with file.open(encoding="utf-8") as f:
            payload = json.load(f)
        records = payload if isinstance(payload, list) else [payload]
        for record in records:
            ad = _normalise(record)
            if ad is None:
                continue
            store_ad(ad)
            written += 1

    print(f"Wrote {written} scraped ads.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
