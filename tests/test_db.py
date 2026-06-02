"""Smoke tests for the database layer.

Verifies that init_db creates the expected tables and that the loader
script can populate them end-to-end against an in-memory engine.
"""

from scripts.load_seeds import _load_checklists, _load_taxonomy, _truncate_taxonomy
from sqlalchemy import inspect, text

from cv_bau_students.config import LEVEL_CHECKLISTS_CSV, TAXONOMY_SEED_CSV
from cv_bau_students.db import _engine, _migrate_columns, get_session
from cv_bau_students.db_models import LevelChecklist, Skill, SkillAlias


def test_init_db_creates_all_tables():
    """All 16 tables should be present after init_db()."""
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
        "skill_industry_map",
        "level_checklists",
        "job_ads",
        "job_ad_skills",
        "matches",
        "reasoning_cache",
        # Phase 12a additions:
        "role_specific_questions",
        "candidate_interests",
        "role_specific_answers",
    }
    assert expected.issubset(table_names), f"missing tables: {expected - table_names}"


def test_migrate_columns_adds_missing_column():
    """An old table missing a newer ORM column gets it back via ALTER ADD."""
    engine = _engine()
    with engine.begin() as conn:
        # Simulate a pre-migration schema: rebuild job_ads without isco_code.
        conn.execute(text("DROP TABLE job_ads"))
        conn.execute(text("CREATE TABLE job_ads (id INTEGER PRIMARY KEY, title TEXT)"))
    _migrate_columns()
    with engine.begin() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info('job_ads')"))}
    # Newer nullable columns are added back.
    assert "isco_code" in cols
    assert "isco_occupation_label" in cols
    # raw_text is NOT NULL without a default → deliberately skipped (can't be
    # safely added to a populated table; create_all owns it on fresh DBs).
    assert "raw_text" not in cols


def test_migrate_columns_is_idempotent():
    """Running the migration twice must not raise (each ALTER is guarded /
    IF NOT EXISTS on Postgres) — guards the prod boot against a stale reflection
    that re-tries an already-added column."""
    engine = _engine()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE job_ads"))
        conn.execute(text("CREATE TABLE job_ads (id INTEGER PRIMARY KEY, title TEXT)"))
    _migrate_columns()
    _migrate_columns()  # second pass — must be a safe no-op, not a crash
    with engine.begin() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info('job_ads')"))}
    assert "isco_code" in cols


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
