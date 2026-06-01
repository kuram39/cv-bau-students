"""Tests for scripts.migrate_sqlite_to_postgres.

No Postgres server in CI, so we exercise the table-copy SQLite→SQLite (the
migration is dialect-agnostic — same SQLAlchemy core path). Validates row
copy, a sample row's fidelity, and --truncate re-run idempotency.
"""

from __future__ import annotations

import pytest
from scripts.migrate_sqlite_to_postgres import TruncateGuardError, migrate
from sqlalchemy import create_engine, func, insert, select

from cv_bau_students.db_models import Base, Candidate, JobAdRow, Skill


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


def test_truncate_refuses_to_wipe_candidate_data_without_confirm(tmp_path):
    """R6 guard: --truncate over a target holding candidate rows must abort
    unless --confirm-destroy; taxonomy-only targets are unaffected."""
    src = f"sqlite:///{tmp_path}/src.sqlite"
    dst = f"sqlite:///{tmp_path}/dst.sqlite"
    _seed_source(src)
    # Seed a candidate directly into the TARGET (simulates a populated prod DB).
    dst_eng = create_engine(dst, future=True)
    Base.metadata.create_all(dst_eng)
    with dst_eng.begin() as conn:
        conn.execute(
            insert(Candidate), [{"id": 1, "cv_hash": "h", "language": "cs", "type": "student"}]
        )

    # No confirm → abort, candidate row untouched.
    with pytest.raises(TruncateGuardError):
        migrate(src, dst, truncate=True, verbose=False)
    assert _count(dst, Candidate) == 1

    # With confirm → proceeds (candidate wiped, source poured in).
    migrate(src, dst, truncate=True, confirm_destroy=True, verbose=False)
    assert _count(dst, Skill) == 2
    assert _count(dst, Candidate) == 0  # source had no candidates


def test_truncate_allowed_on_taxonomy_only_target_without_confirm(tmp_path):
    """A target with no candidate/match rows (fresh or taxonomy-only) re-pours
    freely — the guard only protects irreplaceable user data."""
    src = f"sqlite:///{tmp_path}/src.sqlite"
    dst = f"sqlite:///{tmp_path}/dst.sqlite"
    _seed_source(src)
    migrate(src, dst, verbose=False)  # dst now has skills+ads, no candidates
    migrate(src, dst, truncate=True, verbose=False)  # no confirm needed → no raise
    assert _count(dst, Skill) == 2
