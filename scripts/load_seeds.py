#!/usr/bin/env python3
"""Idempotent loader: CSV seeds → SQLite tables.

Reads `taxonomy_seed.csv` + `level_checklists.csv` from the package
`data/` directory and (re)populates the `skills`, `skill_aliases`,
`skill_hierarchy`, and `level_checklists` tables. Truncate-then-insert
pattern — safe to re-run any time the human-edited CSV changes.

Run via `python scripts/load_seeds.py`. Picks up `CV_BAU_STUDENTS_DB_URL`
from the environment if you want to load into a non-default backend.
"""

import csv
import sys
from pathlib import Path

from sqlalchemy import delete

from cv_bau_students.config import LEVEL_CHECKLISTS_CSV, TAXONOMY_SEED_CSV
from cv_bau_students.db import get_session, init_db
from cv_bau_students.db_models import (
    LevelChecklist,
    Skill,
    SkillAlias,
    SkillHierarchy,
)


def _truncate_taxonomy(session) -> None:
    """Order matters — child rows first."""
    session.execute(delete(SkillHierarchy))
    session.execute(delete(SkillAlias))
    session.execute(delete(LevelChecklist))
    session.execute(delete(Skill))


def _load_taxonomy(session, csv_path: Path) -> dict[str, int]:
    """Insert skills + aliases + hierarchy from the seed CSV.

    Returns canonical_name → id so the checklist loader can FK-resolve.
    """
    canonical_to_id: dict[str, int] = {}

    # Pass 1: insert skills (need their ids before aliases / hierarchy).
    with csv_path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            skill = Skill(
                canonical_name=row["canonical_name"].strip(),
                family=row["family"].strip() or None,
            )
            session.add(skill)
        session.flush()
        for s in session.query(Skill).all():
            canonical_to_id[s.canonical_name] = s.id

    # Pass 2: aliases + hierarchy.
    with csv_path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            canonical = row["canonical_name"].strip()
            canonical_id = canonical_to_id[canonical]
            aliases_field = row.get("aliases", "").strip()
            if aliases_field:
                for raw_alias in aliases_field.split("|"):
                    alias = raw_alias.strip().lower()
                    if alias:
                        session.add(SkillAlias(alias=alias, canonical_id=canonical_id))
            parent = row.get("parent", "").strip()
            if parent:
                parent_id = canonical_to_id.get(parent)
                if parent_id is None:
                    print(
                        f"WARN: parent {parent!r} for {canonical!r} not found — skipped",
                        file=sys.stderr,
                    )
                    continue
                session.add(SkillHierarchy(parent_id=parent_id, child_id=canonical_id))

    return canonical_to_id


def _load_checklists(session, csv_path: Path, canonical_to_id: dict[str, int]) -> int:
    inserted = 0
    with csv_path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            skill_name = row["skill"].strip()
            skill_id = canonical_to_id.get(skill_name)
            if skill_id is None:
                print(
                    f"WARN: checklist references unknown skill {skill_name!r} — skipped",
                    file=sys.stderr,
                )
                continue
            bridgeable_raw = row.get("bridgeable_in_months", "").strip()
            bridgeable = int(bridgeable_raw) if bridgeable_raw.isdigit() else None
            session.add(
                LevelChecklist(
                    domain=row["domain"].strip(),
                    level=row["level"].strip(),
                    skill_id=skill_id,
                    bridgeable_in_months=bridgeable,
                    notes=(row.get("notes") or "").strip() or None,
                )
            )
            inserted += 1
    return inserted


def main() -> int:
    if not TAXONOMY_SEED_CSV.exists():
        print(f"Missing seed file: {TAXONOMY_SEED_CSV}", file=sys.stderr)
        return 1
    if not LEVEL_CHECKLISTS_CSV.exists():
        print(f"Missing seed file: {LEVEL_CHECKLISTS_CSV}", file=sys.stderr)
        return 1

    init_db()
    with get_session() as session:
        _truncate_taxonomy(session)
        canonical_to_id = _load_taxonomy(session, TAXONOMY_SEED_CSV)
        n_skills = len(canonical_to_id)
        n_checklist = _load_checklists(session, LEVEL_CHECKLISTS_CSV, canonical_to_id)

    print(f"Loaded {n_skills} skills + {n_checklist} checklist rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
