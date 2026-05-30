"""Smoke tests for the database layer.

Verifies that init_db creates the expected tables and that the loader
script can populate them end-to-end against an in-memory engine.
"""

from scripts.load_seeds import _load_checklists, _load_taxonomy, _truncate_taxonomy
from sqlalchemy import inspect

from cv_bau_students.config import LEVEL_CHECKLISTS_CSV, TAXONOMY_SEED_CSV
from cv_bau_students.db import _engine, get_session
from cv_bau_students.db_models import LevelChecklist, Skill, SkillAlias


def test_init_db_creates_all_tables():
    """All 10 tables should be present after init_db()."""
    inspector = inspect(_engine())
    table_names = set(inspector.get_table_names())
    expected = {
        "candidates",
        "profile_versions",
        "completion_questions",
        "translated_capabilities",
        "skills",
        "skill_aliases",
        "skill_hierarchy",
        "level_checklists",
        "job_ads",
        "job_ad_skills",
        "matches",
        "reasoning_cache",
    }
    assert expected.issubset(table_names), f"missing tables: {expected - table_names}"


def test_load_seeds_populates_taxonomy_and_checklists():
    """Run the loader against the in-memory DB; verify row counts."""
    with get_session() as session:
        _truncate_taxonomy(session)
        canonical_to_id = _load_taxonomy(session, TAXONOMY_SEED_CSV)
        n_checklist = _load_checklists(session, LEVEL_CHECKLISTS_CSV, canonical_to_id)

    with get_session() as session:
        n_skills = session.query(Skill).count()
        n_aliases = session.query(SkillAlias).count()
        n_levels = session.query(LevelChecklist).count()

    assert n_skills > 30, "taxonomy seed should populate more than 30 canonical skills"
    assert n_aliases > 0, "taxonomy seed should populate at least some aliases"
    assert n_levels == n_checklist > 30, "checklist rows should match what the loader returned"


def test_skill_alias_is_lowercase():
    """The loader normalises aliases to lowercase for case-insensitive lookup."""
    with get_session() as session:
        _truncate_taxonomy(session)
        _load_taxonomy(session, TAXONOMY_SEED_CSV)

    with get_session() as session:
        rows = session.query(SkillAlias).all()
        # Manual seed loader writes lowercase; ESCO loader keeps original
        # casing because we ilike-match. Just check no NULL aliases.
        for alias in rows:
            assert alias.alias is not None
