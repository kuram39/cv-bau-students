#!/usr/bin/env python3
"""Populate `skill_industry_map` from ESCO occupations + occupation-skill relations.

The target-role-first matcher needs: given an ISCO occupation code, which
ESCO skills are essential or optional? This script joins two raw_esco
files to answer that:

  Pass 1: occupations_en.csv (~3k rows)
          → in-memory dict {occupationUri → iscoGroup}.
  Pass 2: stream occupationSkillRelations_en.csv (~126k rows)
          → resolve skillUri to local skill_id, look up isco_code from
            pass-1 map, batch-insert into SkillIndustryMap.

Idempotent: UniqueConstraint(skill_id, isco_code, relation_type) dedupes
on re-run.

Run AFTER scripts/load_esco_csv.py --raw-dir data/raw_esco.

Usage:
    python -m scripts.load_esco_occupations
    python -m scripts.load_esco_occupations --raw-dir data/raw_esco

License: ESCO is CC BY 4.0 — see NOTICES.md.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from scripts.load_esco_csv import DEFAULT_EN_SUBDIR
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from cv_bau_students.db import get_session, init_db
from cv_bau_students.db_models import Skill, SkillIndustryMap

COMMIT_BATCH = 1000


def _index_occupations(occupations_csv: Path) -> dict[str, str]:
    """Pass 1: in-memory map of occupationUri → ISCO 4-digit code."""
    if not occupations_csv.exists():
        raise FileNotFoundError(
            f"Expected ESCO occupations file at {occupations_csv}. "
            f"Run scripts/load_esco_csv.py first to confirm raw_esco/ is unpacked."
        )
    out: dict[str, str] = {}
    with occupations_csv.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            uri = (row.get("conceptUri") or "").strip()
            isco = (row.get("iscoGroup") or "").strip()
            if uri and isco:
                out[uri] = isco
    return out


def _build_uri_to_id_map() -> dict[str, int]:
    """Single in-memory load of ESCO skill URI → local skill_id."""
    out: dict[str, int] = {}
    with get_session() as session:
        for row in session.execute(
            select(Skill.id, Skill.esco_uri).where(Skill.esco_uri.is_not(None))
        ).all():
            out[row.esco_uri] = row.id
    return out


def load_occupations(
    raw_dir: Path,
    *,
    en_subdir: str = DEFAULT_EN_SUBDIR,
    verbose: bool = True,
) -> dict[str, int]:
    """Populate SkillIndustryMap from ESCO occupation→skill relations.

    Returns counts: {
        "rows": N,
        "skipped_unknown_skill": K,
        "skipped_no_isco": M,
    }.
    """
    init_db()
    en_dir = raw_dir / en_subdir
    occ_uri_to_isco = _index_occupations(en_dir / "occupations_en.csv")
    skill_uri_to_id = _build_uri_to_id_map()
    if verbose:
        print(f"  indexed {len(occ_uri_to_isco)} occupations, " f"{len(skill_uri_to_id)} skills.")

    rel_path = en_dir / "occupationSkillRelations_en.csv"
    if not rel_path.exists():
        raise FileNotFoundError(f"Missing {rel_path}")

    rows_written = 0
    skipped_unknown = 0
    skipped_no_isco = 0
    pending = 0
    session = None
    try:
        with rel_path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                occ_uri = (row.get("occupationUri") or "").strip()
                skill_uri = (row.get("skillUri") or "").strip()
                relation_type = (row.get("relationType") or "").strip()
                if not occ_uri or not skill_uri or not relation_type:
                    continue
                isco = occ_uri_to_isco.get(occ_uri)
                if not isco:
                    skipped_no_isco += 1
                    continue
                skill_id = skill_uri_to_id.get(skill_uri)
                if skill_id is None:
                    skipped_unknown += 1
                    continue

                if session is None:
                    session = get_session().__enter__()
                session.execute(
                    sqlite_insert(SkillIndustryMap)
                    .values(
                        skill_id=skill_id,
                        isco_code=isco,
                        occupation_uri=occ_uri,
                        relation_type=relation_type,
                    )
                    .prefix_with("OR IGNORE")
                )
                rows_written += 1
                pending += 1
                if pending >= COMMIT_BATCH:
                    session.commit()
                    pending = 0
                    if verbose:
                        print(
                            f"    wrote {rows_written:>6} rows, "
                            f"skipped {skipped_unknown:>5} unknown-skill, "
                            f"{skipped_no_isco:>5} no-isco"
                        )
    finally:
        if session is not None:
            session.commit()
            session.close()

    if verbose:
        print(
            f"\nDone. Wrote {rows_written} rows. "
            f"Skipped {skipped_unknown} unknown-skill, "
            f"{skipped_no_isco} no-isco occupations."
        )
    return {
        "rows": rows_written,
        "skipped_unknown_skill": skipped_unknown,
        "skipped_no_isco": skipped_no_isco,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Load ESCO occupation-skill mapping.")
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw_esco"))
    args = parser.parse_args()
    if not args.raw_dir.exists():
        print(f"Missing raw_dir: {args.raw_dir}", file=sys.stderr)
        return 1
    counts = load_occupations(args.raw_dir)
    print(f"Loaded {counts['rows']} skill-industry rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
