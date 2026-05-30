#!/usr/bin/env python3
"""Export the loaded ESCO + NSP taxonomy to git-trackable CSVs.

Streamlit Cloud spawns a fresh container per deploy with empty SQLite —
re-running the 18-min ESCO API fetch on every cold start is unacceptable.
This script dumps the local SQLite into two CSV files that get committed
and re-loaded on boot in ~10 seconds.

Output:
    src/cv_bau_students/data/esco_skills.csv   — all skills with ESCO URI
    src/cv_bau_students/data/esco_aliases.csv  — all ESCO + NSP aliases

The manual `taxonomy_seed.csv` + `level_checklists.csv` stay as-is —
they're the hand-edited source of truth for the bridge-plan rubric and
must never be silently overwritten by an ESCO export.

Usage:
    python scripts/export_esco_subset.py
    python scripts/export_esco_subset.py --skill-types skill,knowledge
    python scripts/export_esco_subset.py --it-business-only

`--it-business-only` filters via a keyword allow-list on canonical_name_en
to keep the CSV under ~5k rows for fast Cloud boot. The allow-list is
deliberately broad and conservative — anything matching IT, business,
marketing, analytics, design, project management terms is kept.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from sqlalchemy import select

from cv_bau_students.db import get_session, init_db
from cv_bau_students.db_models import Skill, SkillAlias

# Keyword roots for the IT + business subset. Matched as case-insensitive
# substrings against canonical_name_en. Generous on purpose — false
# positives are cheap (one extra CSV row), false negatives hurt match
# quality.
IT_BUSINESS_KEYWORDS = {
    # IT / software
    "software",
    "program",
    "code",
    "develop",
    "engineer",
    "data",
    "database",
    "sql",
    "python",
    "javascript",
    "java",
    "kubernetes",
    "docker",
    "cloud",
    "devops",
    "linux",
    "git",
    "api",
    "rest",
    "microservice",
    "framework",
    "library",
    "frontend",
    "backend",
    "web",
    "mobile",
    "ios",
    "android",
    "machine learning",
    "artificial intelligence",
    "neural",
    "model",
    "algorithm",
    "test",
    "qa",
    "quality assurance",
    "security",
    "cyber",
    "network",
    # Data / analytics
    "analyt",
    "statistic",
    "visualis",
    "visualiz",
    "tableau",
    "power bi",
    "excel",
    "spreadsheet",
    "report",
    "dashboard",
    "etl",
    "warehouse",
    # Business / management
    "manage",
    "lead",
    "stakeholder",
    "project",
    "product",
    "strategy",
    "business",
    "operation",
    "process",
    "agile",
    "scrum",
    "kanban",
    "negotiate",
    "communicate",
    "present",
    "facilitate",
    "coach",
    # Marketing / sales
    "marketing",
    "sales",
    "customer",
    "client",
    "campaign",
    "advertis",
    "brand",
    "content",
    "social media",
    "seo",
    "crm",
    # Finance / ops
    "financ",
    "account",
    "budget",
    "audit",
    "controlling",
    "compliance",
    "gdpr",
    "regulation",
    "risk",
    "procurement",
    "supply chain",
    "logistic",
    # HR / people
    "recruit",
    "hire",
    "interview",
    "talent",
    "human resource",
    "hr",
    "training",
    "onboard",
    "performance",
    # Design / UX
    "design",
    "ux",
    "ui",
    "user experience",
    "user interface",
    "figma",
    "prototype",
    "wireframe",
}


def _matches_it_business(name_en: str | None) -> bool:
    if not name_en:
        return False
    lowered = name_en.lower()
    return any(kw in lowered for kw in IT_BUSINESS_KEYWORDS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export ESCO + NSP to CSV.")
    parser.add_argument(
        "--skill-types",
        type=str,
        default=None,
        help="Comma-separated skillType allow-list (e.g. 'skill,knowledge').",
    )
    parser.add_argument(
        "--it-business-only",
        action="store_true",
        help="Keep only rows matching IT/business keyword allow-list.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("src/cv_bau_students/data"),
        help="Output directory (default: package data dir, so package-data ships it).",
    )
    args = parser.parse_args()

    init_db()
    skill_types = {t.strip() for t in args.skill_types.split(",")} if args.skill_types else None

    args.out_dir.mkdir(parents=True, exist_ok=True)
    skills_path = args.out_dir / "esco_skills.csv"
    aliases_path = args.out_dir / "esco_aliases.csv"

    with get_session() as session:
        skill_rows = session.execute(select(Skill)).scalars().all()

        kept_ids: set[int] = set()
        with skills_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "canonical_name",
                    "canonical_name_en",
                    "esco_uri",
                    "skill_type",
                    "nsp_code",
                    "family",
                ]
            )
            for row in skill_rows:
                # Keep manual seed rows unconditionally — they're the
                # bridge-plan anchor and shouldn't get filtered out by an
                # ESCO export rule.
                from_manual = row.esco_uri is None and row.family is not None
                if not from_manual:
                    if skill_types and row.skill_type not in skill_types:
                        continue
                    if args.it_business_only and not _matches_it_business(row.canonical_name_en):
                        continue
                writer.writerow(
                    [
                        row.canonical_name,
                        row.canonical_name_en or "",
                        row.esco_uri or "",
                        row.skill_type or "",
                        row.nsp_code or "",
                        row.family or "",
                    ]
                )
                kept_ids.add(row.id)

        alias_rows = (
            session.execute(select(SkillAlias).where(SkillAlias.canonical_id.in_(kept_ids)))
            .scalars()
            .all()
        )
        with aliases_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["alias", "canonical_name", "lang", "source"])
            for alias in alias_rows:
                skill = session.get(Skill, alias.canonical_id)
                if skill is None:
                    continue
                writer.writerow([alias.alias, skill.canonical_name, alias.lang, alias.source])

    print(f"Wrote {len(kept_ids)} skills → {skills_path}")
    print(f"Wrote {len(alias_rows)} aliases → {aliases_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
