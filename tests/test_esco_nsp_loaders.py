"""Tests for ESCO + NSP taxonomy loaders.

ESCO loader is exercised against a mocked HTTP response (no live network
in CI). NSP loader runs against the committed local JSON fixture.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from cv_bau_students.db import get_session
from cv_bau_students.db_models import Skill, SkillAlias
from cv_bau_students.taxonomy.repo import resolve_skill
from scripts import load_esco, load_nsp

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
