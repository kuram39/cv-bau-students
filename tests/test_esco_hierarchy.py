"""Tests for `scripts.load_esco_hierarchy` — populates SkillHierarchy
from broaderRelationsSkillPillar.csv.
"""

from __future__ import annotations

import csv
from pathlib import Path

from scripts.load_esco_csv import DEFAULT_EN_SUBDIR
from scripts.load_esco_hierarchy import load_hierarchy

from cv_bau_students.db import get_session
from cv_bau_students.db_models import Skill, SkillHierarchy

HIERARCHY_HEADER = [
    "conceptType",
    "conceptUri",
    "conceptLabel",
    "broaderType",
    "broaderUri",
    "broaderLabel",
]


def _write_csv(path: Path, header: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in header})


def _prepare_skills(uris_and_names: list[tuple[str, str]]) -> dict[str, int]:
    """Insert minimal Skill rows for the URIs we want to link."""
    name_to_id: dict[str, int] = {}
    with get_session() as session:
        for uri, name in uris_and_names:
            s = Skill(canonical_name=name, esco_uri=uri, skill_type="skill")
            session.add(s)
            session.flush()
            name_to_id[name] = s.id
    return name_to_id


def test_load_hierarchy_inserts_edges(tmp_path):
    _prepare_skills(
        [
            ("uri:python", "Python"),
            ("uri:scripting", "scripting languages"),
            ("uri:programming", "programming"),
        ]
    )
    rows = [
        # Python → scripting → programming
        {
            "conceptUri": "uri:python",
            "broaderUri": "uri:scripting",
            "broaderType": "KnowledgeSkillCompetence",
        },
        {
            "conceptUri": "uri:scripting",
            "broaderUri": "uri:programming",
            "broaderType": "KnowledgeSkillCompetence",
        },
    ]
    en_dir = tmp_path / DEFAULT_EN_SUBDIR
    _write_csv(en_dir / "broaderRelationsSkillPillar_en.csv", HIERARCHY_HEADER, rows)
    counts = load_hierarchy(tmp_path, verbose=False)
    assert counts["edges"] == 2
    with get_session() as s:
        edges = s.query(SkillHierarchy).count()
    assert edges == 2


def test_load_hierarchy_skips_unknown_uris(tmp_path):
    _prepare_skills([("uri:known", "known skill")])
    rows = [
        # parent unknown
        {"conceptUri": "uri:known", "broaderUri": "uri:doesnotexist"},
        # both unknown
        {"conceptUri": "uri:a", "broaderUri": "uri:b"},
    ]
    en_dir = tmp_path / DEFAULT_EN_SUBDIR
    _write_csv(en_dir / "broaderRelationsSkillPillar_en.csv", HIERARCHY_HEADER, rows)
    counts = load_hierarchy(tmp_path, verbose=False)
    assert counts["edges"] == 0
    assert counts["skipped_unknown_uri"] == 2


def test_load_hierarchy_is_idempotent(tmp_path):
    _prepare_skills([("uri:a", "a"), ("uri:b", "b")])
    rows = [{"conceptUri": "uri:a", "broaderUri": "uri:b"}]
    en_dir = tmp_path / DEFAULT_EN_SUBDIR
    _write_csv(en_dir / "broaderRelationsSkillPillar_en.csv", HIERARCHY_HEADER, rows)
    load_hierarchy(tmp_path, verbose=False)
    load_hierarchy(tmp_path, verbose=False)
    with get_session() as s:
        edges = s.query(SkillHierarchy).count()
    assert edges == 1  # composite PK prevents dup
