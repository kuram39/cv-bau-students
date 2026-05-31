"""Tests for scripts.migrate_sqlite_to_postgres.

No Postgres server in CI, so we exercise the table-copy SQLite→SQLite (the
migration is dialect-agnostic — same SQLAlchemy core path). Validates row
copy, a sample row's fidelity, and --truncate re-run idempotency.
"""

from __future__ import annotations

from scripts.migrate_sqlite_to_postgres import migrate
from sqlalchemy import create_engine, func, insert, select

from cv_bau_students.db_models import Base, JobAdRow, Skill


def _seed_source(url: str) -> None:
    eng = create_engine(url, future=True)
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        conn.execute(
            insert(Skill),
            [
                {"id": 1, "canonical_name": "SQL", "esco_uri": "uri:sql"},
                {"id": 2, "canonical_name": "Python", "esco_uri": "uri:py"},
            ],
        )
        conn.execute(
            insert(JobAdRow),
            [
                {
                    "id": 341,
                    "title": "Datový analytik",
                    "location": "Praha",
                    "remote_mode": "hybrid",
                    "level": "medior",
                    "domain": "data-analyst",
                    "source": "scraped",
                    "raw_text": "...",
                    "isco_code": "2511",
                }
            ],
        )


def _count(url: str, table) -> int:
    with create_engine(url, future=True).connect() as conn:
        return conn.execute(select(func.count()).select_from(table)).scalar_one()


def test_migrate_copies_all_rows(tmp_path):
    src = f"sqlite:///{tmp_path}/src.sqlite"
    dst = f"sqlite:///{tmp_path}/dst.sqlite"
    _seed_source(src)

    counts = migrate(src, dst, verbose=False)

    assert counts["skills"] == 2
    assert counts["job_ads"] == 1
    assert _count(dst, Skill) == 2
    assert _count(dst, JobAdRow) == 1
    # sample-row fidelity
    with create_engine(dst, future=True).connect() as conn:
        ad = conn.execute(select(JobAdRow.title, JobAdRow.isco_code)).first()
    assert ad == ("Datový analytik", "2511")


def test_migrate_truncate_is_idempotent(tmp_path):
    src = f"sqlite:///{tmp_path}/src.sqlite"
    dst = f"sqlite:///{tmp_path}/dst.sqlite"
    _seed_source(src)

    migrate(src, dst, truncate=True, verbose=False)
    counts = migrate(src, dst, truncate=True, verbose=False)  # re-pour, no PK clash

    assert counts["skills"] == 2
    assert _count(dst, Skill) == 2  # not doubled
