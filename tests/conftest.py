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
    reset_engine_for_tests("sqlite:///:memory:")
    init_db()
    yield
    _engine.cache_clear()
    _session_factory.cache_clear()
