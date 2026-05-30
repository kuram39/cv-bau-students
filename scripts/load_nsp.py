#!/usr/bin/env python3
"""Layer Czech NSP / CDK competencies on top of the ESCO base.

NSP (Národní soustava povolání) + CDK (Centrální databáze kompetencí)
publish Czech-native phrasings + CZ-ISCO occupation codes via the
data.mpsv.cz open-data portal. We use them as a *secondary* source —
they enrich rather than replace ESCO entries:

  * If an NSP competency matches an existing ESCO skill (by name or
    aliased name), attach its NSP code + any extra Czech aliases.
  * If an NSP competency has no ESCO match, insert as a stand-alone
    `Skill` row with `source="nsp"` on its aliases.

Run AFTER `scripts/load_esco.py`. Idempotent: re-running upserts.

Usage:
    python scripts/load_nsp.py --source data/raw_nsp/competencies.json
    python scripts/load_nsp.py --api                       # pull live

API base (subject to change — verify before each run):
    https://data.mpsv.cz/od/soubory/sablona-nsp-kompetence
    https://portal.mpsv.cz/sus/api/

License: CC0 (data.mpsv.cz open data terms).
"""

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select, update

from cv_bau_students.db import get_session, init_db
from cv_bau_students.db_models import Skill, SkillAlias
from cv_bau_students.taxonomy.repo import resolve_skill


def _load_local(path: Path) -> list[dict]:
    """Load an NSP competency dump from disk.

    Expected shape (per data.mpsv.cz CSV → JSON export):
        [
          {
            "kod": "k123",
            "nazev": "Programování v jazyce Python",
            "synonyma": ["Python programming", "vývoj v Pythonu"],
            "typ": "odborná dovednost",
            "cz_isco": ["25120", "25121"]
          },
          ...
        ]
    """
    if not path.exists():
        print(f"NSP source not found: {path}", file=sys.stderr)
        sys.exit(2)
    return json.loads(path.read_text(encoding="utf-8"))


def _persist_competency(comp: dict) -> tuple[int, int]:
    """Returns (skills_touched, aliases_added)."""
    code = (comp.get("kod") or "").strip()
    name = (comp.get("nazev") or "").strip()
    if not name:
        return 0, 0
    synonyms = [s.strip() for s in comp.get("synonyma", []) if s.strip()]
    nsp_type = (comp.get("typ") or "skill").strip()

    # 1. Try to attach to existing skill (ESCO match).
    match = resolve_skill(name)
    aliases_added = 0
    with get_session() as session:
        if match is not None:
            skill_id, _ = match
            if code:
                session.execute(update(Skill).where(Skill.id == skill_id).values(nsp_code=code))
        else:
            # Insert stand-alone (no ESCO equivalent).
            existing = session.execute(
                select(Skill).where(Skill.canonical_name == name)
            ).scalar_one_or_none()
            if existing is None:
                row = Skill(
                    canonical_name=name,
                    nsp_code=code or None,
                    skill_type=_map_type(nsp_type),
                )
                session.add(row)
                session.flush()
                skill_id = row.id
            else:
                skill_id = existing.id
                if code:
                    session.execute(update(Skill).where(Skill.id == skill_id).values(nsp_code=code))

        # 2. Synonyms as CS aliases.
        for syn in synonyms:
            alias_lower = syn.lower().strip()
            if not alias_lower:
                continue
            exists = session.execute(
                select(SkillAlias.id).where(
                    SkillAlias.alias == alias_lower,
                    SkillAlias.lang == "cs",
                    SkillAlias.source == "nsp",
                )
            ).scalar_one_or_none()
            if exists:
                continue
            session.add(
                SkillAlias(
                    alias=alias_lower,
                    canonical_id=skill_id,
                    lang="cs",
                    source="nsp",
                )
            )
            aliases_added += 1
    return 1, aliases_added


def _map_type(nsp_type: str) -> str:
    t = nsp_type.lower()
    if "odborná" in t or "technická" in t:
        return "skill"
    if "měkká" in t or "mekka" in t or "osobnost" in t:
        return "transversal"
    if "jazyk" in t:
        return "language"
    return "skill"


def main_args(*, source: Path, api: bool = False, verbose: bool = True) -> int:
    """Programmatic entry point — usable from tests."""
    init_db()

    if api:
        print(
            "NSP live API path not yet wired — see docs/TAXONOMY_SOURCES.md\n"
            "Download CDK competency CSV from data.mpsv.cz and convert to JSON.",
            file=sys.stderr,
        )
        return 1

    competencies = _load_local(source)
    touched = 0
    aliases = 0
    for comp in competencies:
        t, a = _persist_competency(comp)
        touched += t
        aliases += a

    if verbose:
        print(f"Touched {touched} skills, added {aliases} NSP aliases.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Load NSP / CDK competencies.")
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("data/raw_nsp/competencies.json"),
        help="Path to a pre-downloaded NSP competency JSON dump.",
    )
    parser.add_argument(
        "--api",
        action="store_true",
        help="Pull live from data.mpsv.cz instead of local file. TODO: wire endpoint.",
    )
    args = parser.parse_args()
    return main_args(source=args.source, api=args.api)


if __name__ == "__main__":
    sys.exit(main())
