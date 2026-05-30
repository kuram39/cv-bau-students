#!/usr/bin/env python3
"""Populate `skill_hierarchy` from ESCO's broaderRelationsSkillPillar.

Reads `data/raw_esco/.../broaderRelationsSkillPillar_en.csv` (~20k
rows), resolves both `conceptUri` and `broaderUri` to local
`skills.id` values via the `Skill.esco_uri` index, and writes one
`SkillHierarchy(parent_id=broader_id, child_id=concept_id)` row per
edge. Idempotent: re-runs upsert via composite PK.

Both endpoints must already exist in the `skills` table — concrete
skills and SkillGroups both. Phase 11b loads both.

Run AFTER scripts/load_esco_csv.py --raw-dir data/raw_esco.

Usage:
    python -m scripts.load_esco_hierarchy
    python -m scripts.load_esco_hierarchy --raw-dir data/raw_esco

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
from cv_bau_students.db_models import Skill, SkillHierarchy

COMMIT_BATCH = 1000


def _build_uri_to_id_map() -> dict[str, int]:
    """Single in-memory load of all ESCO URIs → skill_id for fast joins."""
    out: dict[str, int] = {}
    with get_session() as session:
        for row in session.execute(
            select(Skill.id, Skill.esco_uri).where(Skill.esco_uri.is_not(None))
        ).all():
            out[row.esco_uri] = row.id
    return out


def load_hierarchy(
    raw_dir: Path,
    *,
    en_subdir: str = DEFAULT_EN_SUBDIR,
    verbose: bool = True,
) -> dict[str, int]:
    """Read broaderRelationsSkillPillar_en.csv and populate SkillHierarchy.

    Returns counts: {"edges": N, "skipped_unknown_uri": K}.
    """
    init_db()
    en_path = raw_dir / en_subdir / "broaderRelationsSkillPillar_en.csv"
    if not en_path.exists():
        raise FileNotFoundError(
            f"Expected ESCO hierarchy file at {en_path}. "
            f"Run scripts/load_esco_csv.py first to confirm raw_esco/ is unpacked."
        )

    uri_to_id = _build_uri_to_id_map()
    if verbose:
        print(f"  indexed {len(uri_to_id)} ESCO URIs in local skills table.")

    edges = 0
    skipped = 0
    pending = 0
    session = None
    try:
        with en_path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                child_uri = (row.get("conceptUri") or "").strip()
                parent_uri = (row.get("broaderUri") or "").strip()
                if not child_uri or not parent_uri:
                    continue
                child_id = uri_to_id.get(child_uri)
                parent_id = uri_to_id.get(parent_uri)
                if child_id is None or parent_id is None:
                    skipped += 1
                    continue
                if child_id == parent_id:
                    continue  # self-edge, shouldn't happen but be defensive

                if session is None:
                    session = get_session().__enter__()
                # ON CONFLICT DO NOTHING — composite PK handles dedup.
                session.execute(
                    sqlite_insert(SkillHierarchy)
                    .values(parent_id=parent_id, child_id=child_id)
                    .prefix_with("OR IGNORE")
                )
                edges += 1
                pending += 1
                if pending >= COMMIT_BATCH:
                    session.commit()
                    pending = 0
                    if verbose:
                        print(f"    inserted {edges:>6} edges so far, " f"skipped {skipped:>6}")
    finally:
        if session is not None:
            session.commit()
            session.close()

    if verbose:
        print(
            f"\nDone. Inserted {edges} hierarchy edges. "
            f"Skipped {skipped} edges referencing unknown URIs."
        )
    return {"edges": edges, "skipped_unknown_uri": skipped}


def main() -> int:
    parser = argparse.ArgumentParser(description="Load ESCO skill hierarchy.")
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw_esco"))
    args = parser.parse_args()
    if not args.raw_dir.exists():
        print(f"Missing raw_dir: {args.raw_dir}", file=sys.stderr)
        return 1
    counts = load_hierarchy(args.raw_dir)
    print(f"Loaded {counts['edges']} edges (skipped {counts['skipped_unknown_uri']}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
