"""Tests for ESCO + NSP taxonomy loaders.

ESCO loader is exercised against a mocked HTTP response (no live network
in CI). NSP loader runs against the committed local JSON fixture.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from scripts import load_esco, load_nsp

from cv_bau_students.db import get_session
from cv_bau_students.db_models import Skill, SkillAlias
from cv_bau_students.taxonomy.repo import resolve_skill

# Minimal ESCO API page shape — matches what /resource/skill returns.
_FAKE_EN_PAGE = {
    "_embedded": {
        "http://data.europa.eu/esco/skill/abc": {
            "uri": "http://data.europa.eu/esco/skill/abc",
            "preferredLabel": {"en": "Python programming"},
            "alternativeLabel": {"en": ["Python coding", "scripting in Python"]},
            "skillType": [{"uri": "http://data.europa.eu/esco/skill-type/knowledge"}],
        },
        "http://data.europa.eu/esco/skill/def": {
            "uri": "http://data.europa.eu/esco/skill/def",
            "preferredLabel": {"en": "stakeholder management"},
            "alternativeLabel": {"en": ["managing stakeholders"]},
            "skillType": [{"uri": "http://data.europa.eu/esco/skill-type/skill"}],
        },
    },
}

_FAKE_CS_BULK = {
    "_embedded": {
        "http://data.europa.eu/esco/skill/abc": {
            "uri": "http://data.europa.eu/esco/skill/abc",
            "preferredLabel": {"cs": "programování v Pythonu"},
            "alternativeLabel": {"cs": ["psaní v Pythonu"]},
        },
        # "def" deliberately omitted — exercises missing-CS fallback path.
    },
}


def test_esco_loader_ingests_skills_and_aliases():
    with (
        patch.object(load_esco, "_fetch_page", return_value=_FAKE_EN_PAGE),
        patch.object(load_esco, "_fetch_by_uris", return_value=_FAKE_CS_BULK),
    ):
        rc = load_esco.main_args(limit=2, page_size=2, languages=["cs", "en"])
    assert rc == 0

    py = resolve_skill("Python programming")
    assert py is not None
    py_id, py_canonical = py
    # CS preferred wins over EN when both present.
    assert py_canonical == "programování v Pythonu"

    # Alias-roundtrip via Czech alt label.
    assert resolve_skill("psaní v Pythonu") == (py_id, "programování v Pythonu")
    # EN alt label also resolves.
    assert resolve_skill("Python coding") == (py_id, "programování v Pythonu")

    # Skill with no CS fallback uses EN as canonical.
    stk = resolve_skill("stakeholder management")
    assert stk is not None
    assert stk[1] == "stakeholder management"

    # esco_uri populated on the row.
    with get_session() as s:
        row = s.get(Skill, py_id)
        assert row.esco_uri == "http://data.europa.eu/esco/skill/abc"
        assert row.canonical_name_en == "Python programming"
        assert row.skill_type == "knowledge"


def test_esco_loader_is_idempotent_on_rerun():
    with (
        patch.object(load_esco, "_fetch_page", return_value=_FAKE_EN_PAGE),
        patch.object(load_esco, "_fetch_by_uris", return_value=_FAKE_CS_BULK),
    ):
        load_esco.main_args(limit=2, page_size=2, languages=["cs", "en"])
        # Counts before second run.
        with get_session() as s:
            skills_n1 = s.query(Skill).filter(Skill.esco_uri.is_not(None)).count()
            aliases_n1 = s.query(SkillAlias).filter(SkillAlias.source == "esco").count()
        # Re-run.
        load_esco.main_args(limit=2, page_size=2, languages=["cs", "en"])
        with get_session() as s:
            skills_n2 = s.query(Skill).filter(Skill.esco_uri.is_not(None)).count()
            aliases_n2 = s.query(SkillAlias).filter(SkillAlias.source == "esco").count()
    assert skills_n1 == skills_n2 == 2
    assert aliases_n1 == aliases_n2  # UniqueConstraint dedupe


def test_nsp_loader_against_local_fixture(tmp_path):
    fixture = tmp_path / "nsp.json"
    fixture.write_text(
        json.dumps(
            [
                {
                    "kod": "k-test-1",
                    "nazev": "Datová analýza",
                    "synonyma": ["analytika dat", "práce s daty"],
                    "typ": "odborná dovednost",
                    "cz_isco": ["25210"],
                }
            ]
        ),
        encoding="utf-8",
    )
    rc = load_nsp.main_args(source=fixture)
    assert rc == 0
    match = resolve_skill("analytika dat")
    assert match is not None
    skill_id, canonical = match
    assert canonical == "Datová analýza"
    with get_session() as s:
        row = s.get(Skill, skill_id)
        assert row.nsp_code == "k-test-1"


def test_nsp_loader_attaches_to_existing_esco_match():
    """If NSP nazev matches an ESCO skill, NSP code is stitched onto it."""
    with (
        patch.object(load_esco, "_fetch_page", return_value=_FAKE_EN_PAGE),
        patch.object(load_esco, "_fetch_by_uris", return_value=_FAKE_CS_BULK),
    ):
        load_esco.main_args(limit=2, page_size=2, languages=["cs", "en"])

    # NSP record naming the same Czech canonical the ESCO loader inserted.
    load_nsp._persist_competency(
        {
            "kod": "k-nsp-py",
            "nazev": "programování v Pythonu",
            "synonyma": ["Python coding"],  # already an ESCO alias — should dedupe
            "typ": "odborná dovednost",
        }
    )
    match = resolve_skill("programování v Pythonu")
    assert match is not None
    with get_session() as s:
        row = s.get(Skill, match[0])
        assert row.esco_uri is not None  # still tagged ESCO
        assert row.nsp_code == "k-nsp-py"  # got NSP code too


# Raw CDK list shapes — what /cdk/soft-skill and /cdk/digi `data` items look like.
_FAKE_CDK_SOFT = [
    {
        "id": 1,
        "title": "Kompetence k flexibilitě",
        "description": "...",
        "partialCompetence": "...",
        "type": 1,
        "legacySoftSkillCode": "a04",
        "code": "1.2",
    }
]
_FAKE_CDK_DIGI = [
    {
        "id": 1,
        "titleEn": "evaluating data, information and digital content",
        "title": "Hodnocení dat, informací a digitálního obsahu",
        "description": "...",
        "type": 1,
        "code": "1.2",
    }
]


def _fake_fetch_list(endpoint: str):
    if endpoint == "soft-skill":
        return _FAKE_CDK_SOFT
    if endpoint == "digi":
        return _FAKE_CDK_DIGI
    raise AssertionError(f"unexpected endpoint {endpoint}")


def test_nsp_api_path_persists_cdk_competencies():
    """The --api path transforms CDK items and persists them as cs/nsp skills.

    Mocks the urllib boundary (`_fetch_list`) — no live network.
    """
    with patch.object(load_nsp, "_fetch_list", side_effect=_fake_fetch_list):
        rc = load_nsp.main_args(api=True)
    assert rc == 0

    # Soft-skill -> transversal skill, resolvable by its Czech title.
    soft = resolve_skill("Kompetence k flexibilitě")
    assert soft is not None
    with get_session() as s:
        soft_row = s.get(Skill, soft[0])
        assert soft_row.skill_type == "transversal"
        assert soft_row.nsp_code == "1.2"

    # Digi -> "skill" type, resolvable by its Czech title.
    digi = resolve_skill("Hodnocení dat, informací a digitálního obsahu")
    assert digi is not None
    with get_session() as s:
        digi_row = s.get(Skill, digi[0])
        assert digi_row.skill_type == "skill"

    # A cs alias with source="nsp" exists for the title (lowercased).
    with get_session() as s:
        alias = (
            s.query(SkillAlias)
            .filter(
                SkillAlias.alias == "kompetence k flexibilitě",
                SkillAlias.lang == "cs",
                SkillAlias.source == "nsp",
            )
            .one_or_none()
        )
        assert alias is not None
        assert alias.canonical_id == soft[0]


def test_nsp_api_path_handles_fetch_failure_without_hanging():
    """Any urllib/transport error -> clean non-zero exit, no exception."""
    import urllib.error

    with patch.object(
        load_nsp,
        "_fetch_list",
        side_effect=urllib.error.URLError("boom"),
    ):
        rc = load_nsp.main_args(api=True)
    assert rc == 1


def _seed_one_esco_skill(name: str) -> int:
    with get_session() as s:
        row = Skill(canonical_name=name, canonical_name_en=name, esco_uri=f"uri:{name}")
        s.add(row)
        s.flush()
        return row.id


def test_aliases_only_skips_unmatched_competencies():
    """In aliases-only mode, a competency with no ESCO match is dropped — no
    inert stand-alone Skill row is created."""
    sid = _seed_one_esco_skill("data analysis")
    with get_session() as s:
        before = s.query(Skill).count()

    # Matches an ESCO skill → alias attached.
    t1, a1 = load_nsp._persist_competency(
        {"kod": "x1", "nazev": "data analysis", "synonyma": ["data analysis"]},
        aliases_only=True,
    )
    # No ESCO match → skipped entirely.
    t2, a2 = load_nsp._persist_competency(
        {"kod": "x2", "nazev": "naprosto specifická česká kompetence bez ESCO"},
        aliases_only=True,
    )

    assert (t1, t2) == (1, 0)
    with get_session() as s:
        assert s.query(Skill).count() == before  # no standalone row added
        alias = (
            s.query(SkillAlias)
            .filter(SkillAlias.source == "nsp", SkillAlias.canonical_id == sid)
            .one_or_none()
        )
        assert alias is not None


def test_include_hard_skills_pulls_paginated_competence():
    """--include-hard-skills folds /cdk/competence into the api pull."""
    _seed_one_esco_skill("data mining")
    fake_hard = [
        {
            "kod": "m15._.0058",
            "nazev": "data mining",
            "synonyma": ["data mining"],
            "typ": "odborná dovednost",
            "cz_isco": [],
        },
    ]
    with (
        patch.object(load_nsp, "_fetch_list", side_effect=_fake_fetch_list),
        patch.object(load_nsp, "_fetch_competence_paginated", return_value=fake_hard) as m,
    ):
        rc = load_nsp.main_args(api=True, include_hard=True, aliases_only=True)
    assert rc == 0
    m.assert_called_once()
    with get_session() as s:
        alias = (
            s.query(SkillAlias)
            .filter(SkillAlias.alias == "data mining", SkillAlias.source == "nsp")
            .one_or_none()
        )
        assert alias is not None
