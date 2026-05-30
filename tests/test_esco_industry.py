"""Tests for `scripts.load_esco_occupations` + `expected_skills_for_isco`.

Builds tmp_path fixtures mimicking occupations_en.csv +
occupationSkillRelations_en.csv, runs the loader, then exercises the
matcher-facing repository helper.
"""

from __future__ import annotations

import csv
from pathlib import Path

from scripts.load_esco_csv import DEFAULT_EN_SUBDIR
from scripts.load_esco_occupations import load_occupations

from cv_bau_students.db import get_session
from cv_bau_students.db_models import Skill, SkillIndustryMap
from cv_bau_students.taxonomy.repo import expected_skills_for_isco

OCCUPATIONS_HEADER = [
    "conceptType",
    "conceptUri",
    "iscoGroup",
    "preferredLabel",
    "altLabels",
    "hiddenLabels",
    "status",
    "modifiedDate",
    "regulatedProfessionNote",
    "scopeNote",
    "definition",
    "inScheme",
    "description",
    "code",
    "naceCode",
]
RELATIONS_HEADER = [
    "occupationUri",
    "occupationLabel",
    "relationType",
    "skillType",
    "skillUri",
    "skillLabel",
]


def _write_csv(path: Path, header: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in header})


def _seed_skills(uri_to_name: dict[str, str]) -> dict[str, int]:
    out: dict[str, int] = {}
    with get_session() as session:
        for uri, name in uri_to_name.items():
            s = Skill(canonical_name=name, esco_uri=uri, skill_type="skill")
            session.add(s)
            session.flush()
            out[uri] = s.id
    return out


def _make_raw(tmp_path: Path, *, occupations: list[dict], relations: list[dict]) -> Path:
    en_dir = tmp_path / DEFAULT_EN_SUBDIR
    _write_csv(en_dir / "occupations_en.csv", OCCUPATIONS_HEADER, occupations)
    _write_csv(en_dir / "occupationSkillRelations_en.csv", RELATIONS_HEADER, relations)
    return tmp_path


def test_load_occupations_maps_essential_skills_to_isco(tmp_path):
    skill_ids = _seed_skills({"uri:py": "Python", "uri:sql": "SQL"})
    occupations = [
        {
            "conceptUri": "uri:occ-dev",
            "iscoGroup": "2512",
            "preferredLabel": "software developer",
        }
    ]
    relations = [
        {
            "occupationUri": "uri:occ-dev",
            "skillUri": "uri:py",
            "relationType": "essential",
        },
        {
            "occupationUri": "uri:occ-dev",
            "skillUri": "uri:sql",
            "relationType": "optional",
        },
    ]
    counts = load_occupations(
        _make_raw(tmp_path, occupations=occupations, relations=relations),
        verbose=False,
    )
    assert counts["rows"] == 2
    assert counts["skipped_unknown_skill"] == 0
    assert counts["skipped_no_isco"] == 0

    essentials = expected_skills_for_isco("2512", "essential")
    assert essentials == [skill_ids["uri:py"]]
    optionals = expected_skills_for_isco("2512", "optional")
    assert optionals == [skill_ids["uri:sql"]]
    all_ = expected_skills_for_isco("2512", "")
    assert sorted(all_) == sorted([skill_ids["uri:py"], skill_ids["uri:sql"]])


def test_expected_skills_for_isco_returns_empty_for_unknown_code(tmp_path):
    _seed_skills({"uri:py": "Python"})
    occupations = [{"conceptUri": "uri:occ", "iscoGroup": "9999", "preferredLabel": "test"}]
    relations = [{"occupationUri": "uri:occ", "skillUri": "uri:py", "relationType": "essential"}]
    load_occupations(
        _make_raw(tmp_path, occupations=occupations, relations=relations), verbose=False
    )
    assert expected_skills_for_isco("0000") == []
    assert expected_skills_for_isco("") == []


def test_load_occupations_skips_unknown_skill(tmp_path):
    _seed_skills({"uri:known": "known"})
    occupations = [{"conceptUri": "uri:occ", "iscoGroup": "1234", "preferredLabel": "x"}]
    relations = [
        {"occupationUri": "uri:occ", "skillUri": "uri:unknown", "relationType": "essential"}
    ]
    counts = load_occupations(
        _make_raw(tmp_path, occupations=occupations, relations=relations), verbose=False
    )
    assert counts["rows"] == 0
    assert counts["skipped_unknown_skill"] == 1


def test_load_occupations_is_idempotent(tmp_path):
    _seed_skills({"uri:py": "Python"})
    occupations = [{"conceptUri": "uri:occ", "iscoGroup": "2512", "preferredLabel": "dev"}]
    relations = [{"occupationUri": "uri:occ", "skillUri": "uri:py", "relationType": "essential"}]
    raw = _make_raw(tmp_path, occupations=occupations, relations=relations)
    load_occupations(raw, verbose=False)
    load_occupations(raw, verbose=False)
    with get_session() as s:
        assert s.query(SkillIndustryMap).count() == 1
