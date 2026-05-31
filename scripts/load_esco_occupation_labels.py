#!/usr/bin/env python3
"""Populate the `occupations` table with ESCO occupation labels (en + cs).

The role→ISCO resolver (`roles/isco_resolver.py`) matches an ad's title
and domain against occupation labels to pick the right ISCO-08 group,
then `SkillIndustryMap` supplies that group's expected skill set. Labels
must live in the DB (and thus in `seed.sqlite.gz`) because `data/raw_esco/`
is gitignored and absent on Streamlit Cloud.

Reads `occupations_en.csv` + `occupations_cs.csv`, storing per row:
`conceptUri`, `iscoGroup`, `preferredLabel`, and the newline-separated
`altLabels` as a JSON list. Idempotent: UniqueConstraint(occupation_uri,
lang) + OR IGNORE dedupes on re-run.

Run AFTER scripts/load_esco_csv.py --raw-dir data/raw_esco.

Usage:
    python -m scripts.load_esco_occupation_labels
    python -m scripts.load_esco_occupation_labels --raw-dir data/raw_esco

License: ESCO is CC BY 4.0 — see NOTICES.md.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from scripts.load_esco_csv import DEFAULT_CS_SUBDIR, DEFAULT_EN_SUBDIR
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from cv_bau_students.db import get_session, init_db
from cv_bau_students.db_models import Occupation

COMMIT_BATCH = 1000


def _split_alt_labels(raw: str | None) -> list[str]:
    """ESCO altLabels are newline-separated within one cell."""
    if not raw:
        return []
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _load_one(occupations_csv: Path, lang: str, *, verbose: bool) -> int:
    if not occupations_csv.exists():
        raise FileNotFoundError(
            f"Expected ESCO occupations file at {occupations_csv}. "
            f"Run scripts/load_esco_csv.py first to confirm raw_esco/ is unpacked."
        )
    written = 0
    pending = 0
    with occupations_csv.open(encoding="utf-8") as f, get_session() as session:
        for row in csv.DictReader(f):
            uri = (row.get("conceptUri") or "").strip()
            isco = (row.get("iscoGroup") or "").strip()
            label = (row.get("preferredLabel") or "").strip()
            if not uri or not isco or not label:
                continue
            session.execute(
                sqlite_insert(Occupation)
                .values(
                    occupation_uri=uri,
                    isco_code=isco,
                    preferred_label=label,
                    alt_labels=_split_alt_labels(row.get("altLabels")),
                    lang=lang,
                )
                .prefix_with("OR IGNORE")
            )
            written += 1
            pending += 1
            if pending >= COMMIT_BATCH:
                session.commit()
                pending = 0
    if verbose:
        print(f"  {lang}: wrote {written} occupation labels from {occupations_csv.name}")
    return written


def load_occupation_labels(
    raw_dir: Path,
    *,
    en_subdir: str = DEFAULT_EN_SUBDIR,
    cs_subdir: str = DEFAULT_CS_SUBDIR,
    verbose: bool = True,
) -> dict[str, int]:
    """Load en + cs occupation labels into the `occupations` table."""
    init_db()
    en = _load_one(raw_dir / en_subdir / "occupations_en.csv", "en", verbose=verbose)
    cs = _load_one(raw_dir / cs_subdir / "occupations_cs.csv", "cs", verbose=verbose)
    return {"en": en, "cs": cs}


def main() -> int:
    parser = argparse.ArgumentParser(description="Load ESCO occupation labels (en + cs).")
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw_esco"))
    args = parser.parse_args()
    if not args.raw_dir.exists():
        print(f"Missing raw_dir: {args.raw_dir}", file=sys.stderr)
        return 1
    counts = load_occupation_labels(args.raw_dir)
    print(f"Loaded {counts['en']} en + {counts['cs']} cs occupation labels.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
