"""Tests for the raw ESCO CSV ingest path (`scripts.load_esco_csv`).

Uses a tmp_path fixture that mimics the official ESCO v1.2.x CSV
layout: two subdirectories (cs / en) with skills_*.csv and
skillGroups_*.csv files. No live network — no real ESCO download
needed in CI.
"""

from __future__ import annotations

import csv
from pathlib import Path

from scripts.load_esco_csv import (
    DEFAULT_CS_SUBDIR,
    DEFAULT_EN_SUBDIR,
    load_raw_esco,
)

from cv_bau_students.db import get_session
from cv_bau_students.db_models import Skill, SkillAlias
from cv_bau_students.taxonomy.repo import resolve_skill

SKILLS_HEADER = [
    "conceptType",
    "conceptUri",
    "skillType",
    "reuseLevel",
    "preferredLabel",
    "altLabels",
    "hiddenLabels",
    "status",
    "modifiedDate",
    "scopeNote",
    "definition",
    "inScheme",
    "description",
]
GROUPS_HEADER = [
    "conceptType",
    "conceptUri",
    "preferredLabel",
    "altLabels",
    "hiddenLabels",
    "status",
    "modifiedDate",
    "scopeNote",
    "inScheme",
    "description",
    "code",
]


def _write_csv(path: Path, header: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in header})


def _make_raw_dir(
    tmp_path: Path,
    *,
    en_rows: list[dict],
    cs_rows: list[dict],
    group_en_rows: list[dict] | None = None,
    group_cs_rows: list[dict] | None = None,
) -> Path:
    raw = tmp_path / "raw_esco"
    en_dir = raw / DEFAULT_EN_SUBDIR
    cs_dir = raw / DEFAULT_CS_SUBDIR
    _write_csv(en_dir / "skills_en.csv", SKILLS_HEADER, en_rows)
    _write_csv(cs_dir / "skills_cs.csv", SKILLS_HEADER, cs_rows)
    if group_en_rows is not None:
        _write_csv(en_dir / "skillGroups_en.csv", GROUPS_HEADER, group_en_rows)
    if group_cs_rows is not None:
        _write_csv(cs_dir / "skillGroups_cs.csv", GROUPS_HEADER, group_cs_rows)
    return raw


def test_load_raw_esco_joins_cs_and_en_on_concept_uri(tmp_path):
    en = [
        {
            "conceptUri": "http://data.europa.eu/esco/skill/abc",
            "preferredLabel": "Python programming",
            "altLabels": "Python coding\nscripting in Python",
            "skillType": "skill/competence",
        },
    ]
    cs = [
        {
            "conceptUri": "http://data.europa.eu/esco/skill/abc",
            "preferredLabel": "programování v Pythonu",
            "altLabels": "psaní v Pythonu",
            "skillType": "skill/competence",
        },
    ]
    counts = load_raw_esco(_make_raw_dir(tmp_path, en_rows=en, cs_rows=cs), verbose=False)
    assert counts["skills"] == 1
    assert counts["aliases"] == 3  # 2 EN + 1 CS

    # CS preferred wins over EN as canonical.
    match = resolve_skill("programování v Pythonu")
    assert match is not None
    skill_id, canonical = match
    assert canonical == "programování v Pythonu"

    # EN preferred resolves to the same row.
    assert resolve_skill("Python programming") == (skill_id, canonical)
    # CS altLabel resolves.
    assert resolve_skill("psaní v Pythonu") == (skill_id, canonical)
    # EN altLabel resolves.
    assert resolve_skill("Python coding") == (skill_id, canonical)

    with get_session() as s:
        row = s.get(Skill, skill_id)
        assert row.esco_uri == "http://data.europa.eu/esco/skill/abc"
        assert row.canonical_name_en == "Python programming"
        assert row.skill_type == "skill"


def test_load_raw_esco_falls_back_to_en_when_cs_missing(tmp_path):
    """ESCO has 14k EN-only-no-CS skills. Loader uses EN as canonical."""
    en = [
        {
            "conceptUri": "http://data.europa.eu/esco/skill/xyz",
            "preferredLabel": "stakeholder management",
            "altLabels": "managing stakeholders",
            "skillType": "skill/competence",
        },
    ]
    # CS file empty.
    counts = load_raw_esco(_make_raw_dir(tmp_path, en_rows=en, cs_rows=[]), verbose=False)
    assert counts["skills"] == 1

    match = resolve_skill("stakeholder management")
    assert match is not None
    skill_id, canonical = match
    assert canonical == "stakeholder management"

    with get_session() as s:
        row = s.get(Skill, skill_id)
        assert row.canonical_name_en == "stakeholder management"


def test_load_raw_esco_loads_skill_groups(tmp_path):
    """SkillGroups must land in `skills` table (Phase 11c hierarchy FKs them)."""
    group_en = [
        {
            "conceptUri": "http://data.europa.eu/esco/isced-f/0613",
            "preferredLabel": "Software and applications development and analysis",
            "altLabels": "software engineering",
        },
    ]
    group_cs = [
        {
            "conceptUri": "http://data.europa.eu/esco/isced-f/0613",
            "preferredLabel": "Vývoj software a aplikací",
            "altLabels": "softwarové inženýrství",
        },
    ]
    counts = load_raw_esco(
        _make_raw_dir(
            tmp_path,
            en_rows=[],
            cs_rows=[],
            group_en_rows=group_en,
            group_cs_rows=group_cs,
        ),
        verbose=False,
    )
    assert counts["skill_groups"] == 1
    match = resolve_skill("software engineering")
    assert match is not None
    with get_session() as s:
        row = s.get(Skill, match[0])
        assert row.skill_type == "skillGroup"


def test_load_raw_esco_is_idempotent(tmp_path):
    en = [
        {
            "conceptUri": "http://data.europa.eu/esco/skill/def",
            "preferredLabel": "data analysis",
            "altLabels": "analytics\nanalysing data",
            "skillType": "knowledge",
        },
    ]
    raw = _make_raw_dir(tmp_path, en_rows=en, cs_rows=[])
    load_raw_esco(raw, verbose=False)
    with get_session() as s:
        n_skills_1 = s.query(Skill).count()
        n_aliases_1 = s.query(SkillAlias).count()

    # Re-run identical input — no duplicates.
    load_raw_esco(raw, verbose=False)
    with get_session() as s:
        n_skills_2 = s.query(Skill).count()
        n_aliases_2 = s.query(SkillAlias).count()

    assert n_skills_1 == n_skills_2 == 1
    assert n_aliases_1 == n_aliases_2 == 2


def test_load_raw_esco_classifies_knowledge_vs_skill(tmp_path):
    en = [
        {
            "conceptUri": "http://data.europa.eu/esco/skill/k1",
            "preferredLabel": "machine learning",
            "altLabels": "",
            "skillType": "knowledge",
        },
        {
            "conceptUri": "http://data.europa.eu/esco/skill/s1",
            "preferredLabel": "train a team",
            "altLabels": "",
            "skillType": "skill/competence",
        },
    ]
    load_raw_esco(_make_raw_dir(tmp_path, en_rows=en, cs_rows=[]), verbose=False)
    with get_session() as s:
        ml = s.query(Skill).filter(Skill.canonical_name == "machine learning").one()
        tt = s.query(Skill).filter(Skill.canonical_name == "train a team").one()
    assert ml.skill_type == "knowledge"
    assert tt.skill_type == "skill"


def test_load_raw_esco_errors_on_missing_en_dir(tmp_path):
    """Hard error when the EN dir is missing — load is meaningless without it."""
    import pytest

    with pytest.raises(FileNotFoundError) as exc:
        load_raw_esco(tmp_path / "nonexistent", verbose=False)
    assert "ESCO EN directory" in str(exc.value)
