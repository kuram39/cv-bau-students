"""Single source of truth for the SQLAlchemy engine and session factory.

Mirrors how `llm.py` centralises Anthropic calls. Every module that
needs DB access imports `get_session()` from here. The default backend
is SQLite (file path from `config.DB_URL`); production deploys point
`CV_BAU_STUDENTS_DB_URL` at a Postgres DSN — zero code change needed.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from cv_bau_students import config
from cv_bau_students.db_models import Base


@lru_cache(maxsize=1)
def _engine() -> Engine:
    # Read DB_URL at call time, not import time — `reset_engine_for_tests`
    # mutates the config module's attribute.
    url = config.DB_URL
    connect_args: dict = {}
    pool_kwargs: dict = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        if ":memory:" in url:
            # StaticPool reuses one connection so a per-test :memory: DB
            # persists across the test (otherwise each session would get
            # a fresh, empty DB).
            pool_kwargs["poolclass"] = StaticPool
    engine = create_engine(url, connect_args=connect_args, future=True, **pool_kwargs)
    return engine


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker:
    return sessionmaker(bind=_engine(), expire_on_commit=False, future=True)


def init_db() -> None:
    """Create all tables. Idempotent — safe to call on every app start.

    For file-backed SQLite, ensures the parent directory exists. Schema
    migrations beyond the prototype need alembic; for now the schema is
    small enough that `create_all` is the contract.
    """
    url = config.DB_URL
    if url.startswith("sqlite:///") and ":memory:" not in url:
        from pathlib import Path

        db_path = Path(url.replace("sqlite:///", "", 1))
        db_path.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(_engine())


def drop_db() -> None:
    """Drop all tables. Only used by the test fixture."""
    Base.metadata.drop_all(_engine())


@contextmanager
def get_session() -> Iterator[Session]:
    """Context-manager session. Commits on clean exit, rolls back on error.

    Usage:
        with get_session() as s:
            s.add(...)
    """
    session = _session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine_for_tests(db_url: str) -> None:
    """Force-reload the engine + session factory against a new URL.

    Only intended for the conftest fixture that swaps in an in-memory
    SQLite DB before each test.
    """
    _engine.cache_clear()
    _session_factory.cache_clear()
    # Mutate the module-level URL for the cached helpers' next read.
    import cv_bau_students.config as cfg

    cfg.DB_URL = db_url
