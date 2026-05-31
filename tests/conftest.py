"""Shared pytest fixtures.

Key fixture: in-memory SQLite engine per test, schema rebuilt fresh.
Each test claims its own in-memory DB via `reset_engine_for_tests`;
on teardown we just clear the engine cache — the next test creates a
fresh one. No drop_all needed because `:memory:` dies with its
connection.
"""

import pytest

from cv_bau_students.db import _engine, _session_factory, init_db, reset_engine_for_tests


@pytest.fixture(autouse=True)
def _isolated_sqlite():
    _clear_taxonomy_caches()  # don't inherit a prior test's in-memory index
    reset_engine_for_tests("sqlite:///:memory:")
    init_db()
    yield
    _engine.cache_clear()
    _session_factory.cache_clear()
    _clear_taxonomy_caches()


def _clear_taxonomy_caches() -> None:
    """The ESCO index + translate call are lru_cached on DB state; each test
    gets a fresh in-memory DB, so the caches must be dropped between tests."""
    from cv_bau_students.taxonomy.repo import (
        _esco_index,
        _seed_skill_index,
        canonical_for_alias,
        resolve_skill,
        resolve_skill_esco,
    )
    from cv_bau_students.translator.translate import _translate_raw

    _esco_index.cache_clear()
    _seed_skill_index.cache_clear()
    canonical_for_alias.cache_clear()
    resolve_skill.cache_clear()
    resolve_skill_esco.cache_clear()
    _translate_raw.cache_clear()
