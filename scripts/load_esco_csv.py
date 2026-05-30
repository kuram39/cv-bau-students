#!/usr/bin/env python3
"""ESCO ingest — two entry points.

`load_raw_esco(raw_dir)` reads the official ESCO v1.2.x CSV download
(36 files, CS+EN pairs) and bulk-loads skills + skillGroups +
altLabels into the `skills` and `skill_aliases` tables. This is the
**local** ingest path — run once after downloading raw_esco/.

`load_csv_subset(skills_csv, aliases_csv)` reads the simplified export
format produced by `scripts/export_esco_subset.py`. Kept for the
slow-fallback Cloud replay path (the fast path is `seed.sqlite.gz`
gunzip-restore handled by bootstrap.py).

Both paths share `Skill` + `SkillAlias` schema and are idempotent —
re-runs upsert by `esco_uri`; aliases dedupe on
`UniqueConstraint(alias, lang, source)`.

Raw ESCO format details (per v1.2.1):
    skills_{cs,en}.csv headers:
      conceptType, conceptUri, skillType, reuseLevel, preferredLabel,
      altLabels, hiddenLabels, status, modifiedDate, scopeNote,
      definition, inScheme, description
    skillGroups_{cs,en}.csv headers:
      conceptType, conceptUri, preferredLabel, altLabels, hiddenLabels,
      status, modifiedDate, scopeNote, inScheme, description, code
    altLabels delimiter: `\\n` (newline character INSIDE the field)
    skillType values: 'skill/competence', 'knowledge', ''
    Join key (CS↔EN): conceptUri

License: ESCO is CC BY 4.0 — see NOTICES.md.

Usage:
    python -m scripts.load_esco_csv --raw-dir data/raw_esco         # full local load
    python -m scripts.load_esco_csv --skills-csv path/to/seed.csv   # legacy replay
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from sqlalchemy import select, update

from cv_bau_students.db import get_session, init_db
from cv_bau_students.db_models import Skill, SkillAlias

# Default subdirectory names inside data/raw_esco/. The official ESCO ZIP
# extracts to these exact names; if the user renames them, pass
# --cs-dir / --en-dir explicitly.
DEFAULT_CS_SUBDIR = "ESCO dataset - v1.2.1 - classification - cs - csv"
DEFAULT_EN_SUBDIR = "ESCO dataset - v1.2.1 - classification - en - csv"

# Batch commit cadence — flush every N rows to keep memory flat on the
# 14k-row skills file + 640-row skillGroups file. Both fit comfortably
# in memory, but we batch anyway for parity with the larger 11c loaders.
COMMIT_BATCH = 1000


def _map_skill_type(raw: str) -> str:
    """ESCO uses 'skill/competence', 'knowledge', or empty. Our column
    stores the shorter canonical form."""
    raw = (raw or "").lower().strip()
    if "knowledge" in raw:
        return "knowledge"
    if not raw:
        return "skill"
    if "language" in raw:
        return "language"
    return "skill"


def _split_alt_labels(raw: str) -> list[str]:
    """altLabels field is `\\n`-delimited per ESCO spec."""
    if not raw:
        return []
    return [s.strip() for s in raw.split("\n") if s.strip()]


def _index_cs_by_uri(cs_path: Path) -> dict[str, tuple[str | None, list[str]]]:
    """Pre-read CS file into {conceptUri: (preferredLabel, altLabels)}.

    CS file is small enough (~14k rows × ~500 bytes ≈ 7 MB) to fit in
    memory; trading RAM for a single sequential scan of EN.
    """
    out: dict[str, tuple[str | None, list[str]]] = {}
    if not cs_path.exists():
        return out
    with cs_path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            uri = (row.get("conceptUri") or "").strip()
            if not uri:
                continue
            cs_pref = (row.get("preferredLabel") or "").strip() or None
            cs_alts = _split_alt_labels(row.get("altLabels", ""))
            out[uri] = (cs_pref, cs_alts)
    return out


def _ingest_concept_file(
    en_path: Path,
    cs_path: Path,
    *,
    label: str,
    verbose: bool = True,
) -> tuple[int, int]:
    """Generic ingest for both skills_*.csv and skillGroups_*.csv.

    Both files share the conceptUri + preferredLabel + altLabels triple
    we care about; skills_*.csv has the extra skillType column.

    Returns (skills_written, aliases_written).
    """
    if not en_path.exists():
        if verbose:
            print(f"  WARN: missing {en_path} — skipped {label} ingest.", file=sys.stderr)
        return 0, 0
    cs_index = _index_cs_by_uri(cs_path)
    if verbose:
        print(f"  {label}: indexed {len(cs_index)} CS rows; streaming EN...")

    skills_written = 0
    aliases_written = 0
    pending = 0
    session = None
    try:
        with en_path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                uri = (row.get("conceptUri") or "").strip()
                if not uri:
                    continue
                en_pref = (row.get("preferredLabel") or "").strip() or None
                en_alts = _split_alt_labels(row.get("altLabels", ""))
                skill_type = _map_skill_type(row.get("skillType", ""))
                # skillGroups don't have skillType column; default to 'skillGroup'
                if "skillGroup" in label:
                    skill_type = "skillGroup"

                cs_pref, cs_alts = cs_index.get(uri, (None, []))
                canonical = cs_pref or en_pref
                if not canonical:
                    continue

                if session is None:
                    session = get_session().__enter__()

                # Upsert by esco_uri.
                existing = session.execute(
                    select(Skill).where(Skill.esco_uri == uri)
                ).scalar_one_or_none()
                if existing is None:
                    # Avoid colliding with a same-named manual seed.
                    collision = session.execute(
                        select(Skill).where(Skill.canonical_name == canonical)
                    ).scalar_one_or_none()
                    if collision is not None:
                        session.execute(
                            update(Skill)
                            .where(Skill.id == collision.id)
                            .values(
                                esco_uri=uri,
                                canonical_name_en=en_pref,
                                skill_type=skill_type,
                            )
                        )
                        skill_id = collision.id
                    else:
                        new = Skill(
                            canonical_name=canonical,
                            canonical_name_en=en_pref,
                            esco_uri=uri,
                            skill_type=skill_type,
                        )
                        session.add(new)
                        session.flush()
                        skill_id = new.id
                else:
                    session.execute(
                        update(Skill)
                        .where(Skill.id == existing.id)
                        .values(
                            canonical_name=canonical,
                            canonical_name_en=en_pref,
                            skill_type=skill_type,
                        )
                    )
                    skill_id = existing.id
                skills_written += 1

                # AltLabels → SkillAlias rows.
                for alias_text, lang in (
                    *((a, "cs") for a in cs_alts),
                    *((a, "en") for a in en_alts),
                ):
                    a_lower = alias_text.lower().strip()
                    if not a_lower:
                        continue
                    exists = session.execute(
                        select(SkillAlias.id).where(
                            SkillAlias.alias == a_lower,
                            SkillAlias.lang == lang,
                            SkillAlias.source == "esco",
                        )
                    ).scalar_one_or_none()
                    if exists:
                        continue
                    session.add(
                        SkillAlias(
                            alias=a_lower,
                            canonical_id=skill_id,
                            lang=lang,
                            source="esco",
                        )
                    )
                    aliases_written += 1

                pending += 1
                if pending >= COMMIT_BATCH:
                    session.commit()
                    pending = 0
                    if verbose:
                        print(
                            f"    {label}: wrote {skills_written:>6} skills, "
                            f"{aliases_written:>6} aliases so far"
                        )
    finally:
        if session is not None:
            session.commit()
            session.close()
    return skills_written, aliases_written


def load_raw_esco(
    raw_dir: Path,
    *,
    cs_subdir: str = DEFAULT_CS_SUBDIR,
    en_subdir: str = DEFAULT_EN_SUBDIR,
    verbose: bool = True,
) -> dict[str, int]:
    """Ingest the official ESCO v1.2.x CSV bundle from `raw_dir`.

    Loads both skills_*.csv (~14k concrete skills) and skillGroups_*.csv
    (~640 group concepts). SkillGroups land in the same `skills` table
    with `skill_type='skillGroup'` — Phase 11c hierarchy edges point to
    these, so they must be present as foreign-key targets.

    Returns counts: {"skills": N, "aliases": M, "skill_groups": K}.
    """
    init_db()
    cs_dir = raw_dir / cs_subdir
    en_dir = raw_dir / en_subdir
    if not en_dir.exists():
        raise FileNotFoundError(
            f"Expected ESCO EN directory at {en_dir}. "
            f"Download from https://esco.ec.europa.eu/en/use-esco/download "
            f"and extract into {raw_dir}."
        )

    if verbose:
        print(f"Loading ESCO from {raw_dir}")
        print(f"  CS dir: {cs_dir}")
        print(f"  EN dir: {en_dir}")

    skills_written, aliases_written = _ingest_concept_file(
        en_dir / "skills_en.csv",
        cs_dir / "skills_cs.csv",
        label="skills",
        verbose=verbose,
    )
    groups_written, group_aliases = _ingest_concept_file(
        en_dir / "skillGroups_en.csv",
        cs_dir / "skillGroups_cs.csv",
        label="skillGroups",
        verbose=verbose,
    )

    if verbose:
        print(
            f"\nDone. Skills: {skills_written}, SkillGroups: {groups_written}, "
            f"Aliases: {aliases_written + group_aliases}."
        )

    return {
        "skills": skills_written,
        "skill_groups": groups_written,
        "aliases": aliases_written + group_aliases,
    }


def load_csv_subset(
    skills_csv: Path,
    aliases_csv: Path | None,
) -> dict[str, int]:
    """Read the simplified export CSVs from `scripts/export_esco_subset.py`.

    Kept for the slow-fallback Cloud replay path. The fast path is the
    `seed.sqlite.gz` gunzip-restore handled by bootstrap.py — see
    Phase 11d.

    Returns counts: {"skills": N, "aliases": M}.
    """
    init_db()
    skills_written = 0
    aliases_written = 0

    canonical_to_id: dict[str, int] = {}

    with skills_csv.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        with get_session() as session:
            for row in reader:
                canonical = (row.get("canonical_name") or "").strip()
                if not canonical:
                    continue
                canonical_en = (row.get("canonical_name_en") or "").strip() or None
                esco_uri = (row.get("esco_uri") or "").strip() or None
                skill_type = (row.get("skill_type") or "").strip() or None
                nsp_code = (row.get("nsp_code") or "").strip() or None
                family = (row.get("family") or "").strip() or None

                existing = None
                if esco_uri:
                    existing = session.execute(
                        select(Skill).where(Skill.esco_uri == esco_uri)
                    ).scalar_one_or_none()
                if existing is None:
                    existing = session.execute(
                        select(Skill).where(Skill.canonical_name == canonical)
                    ).scalar_one_or_none()

                if existing is None:
                    skill = Skill(
                        canonical_name=canonical,
                        canonical_name_en=canonical_en,
                        esco_uri=esco_uri,
                        skill_type=skill_type,
                        nsp_code=nsp_code,
                        family=family,
                    )
                    session.add(skill)
                    session.flush()
                    skill_id = skill.id
                else:
                    session.execute(
                        update(Skill)
                        .where(Skill.id == existing.id)
                        .values(
                            canonical_name_en=canonical_en or existing.canonical_name_en,
                            esco_uri=esco_uri or existing.esco_uri,
                            skill_type=skill_type or existing.skill_type,
                            nsp_code=nsp_code or existing.nsp_code,
                            family=family or existing.family,
                        )
                    )
                    skill_id = existing.id
                canonical_to_id[canonical] = skill_id
                skills_written += 1

    if aliases_csv is not None and aliases_csv.exists():
        with aliases_csv.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            with get_session() as session:
                for row in reader:
                    alias = (row.get("alias") or "").strip()
                    canonical = (row.get("canonical_name") or "").strip()
                    lang = (row.get("lang") or "en").strip() or "en"
                    source = (row.get("source") or "manual").strip() or "manual"
                    if not alias or not canonical:
                        continue
                    skill_id = canonical_to_id.get(canonical)
                    if skill_id is None:
                        skill = session.execute(
                            select(Skill).where(Skill.canonical_name == canonical)
                        ).scalar_one_or_none()
                        if skill is None:
                            continue
                        skill_id = skill.id
                        canonical_to_id[canonical] = skill_id

                    exists = session.execute(
                        select(SkillAlias.id).where(
                            SkillAlias.alias == alias,
                            SkillAlias.lang == lang,
                            SkillAlias.source == source,
                        )
                    ).scalar_one_or_none()
                    if exists:
                        continue
                    session.add(
                        SkillAlias(
                            alias=alias,
                            canonical_id=skill_id,
                            lang=lang,
                            source=source,
                        )
                    )
                    aliases_written += 1

    return {"skills": skills_written, "aliases": aliases_written}


def main() -> int:
    parser = argparse.ArgumentParser(description="Load ESCO into SQLite.")
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=None,
        help=(
            "Root of the unpacked ESCO ZIP (data/raw_esco/). When set, "
            "ingests skills_*.csv + skillGroups_*.csv."
        ),
    )
    parser.add_argument(
        "--skills-csv",
        type=Path,
        default=None,
        help="Legacy: simplified export-CSV path (used by Cloud fallback).",
    )
    parser.add_argument(
        "--aliases-csv",
        type=Path,
        default=None,
        help="Legacy: simplified aliases-CSV path.",
    )
    args = parser.parse_args()

    if args.raw_dir is not None:
        if not args.raw_dir.exists():
            print(f"Missing raw_dir: {args.raw_dir}", file=sys.stderr)
            return 1
        counts = load_raw_esco(args.raw_dir)
        print(
            f"Loaded {counts['skills']} skills + {counts['skill_groups']} groups, "
            f"{counts['aliases']} aliases."
        )
        return 0

    if args.skills_csv is not None:
        if not args.skills_csv.exists():
            print(f"Missing CSV: {args.skills_csv}", file=sys.stderr)
            return 1
        counts = load_csv_subset(args.skills_csv, args.aliases_csv)
        print(f"Loaded {counts['skills']} skills, {counts['aliases']} new aliases.")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
