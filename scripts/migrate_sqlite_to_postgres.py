#!/usr/bin/env python3
"""One-time data pour: local SQLite → Postgres (persistent deploy).

Streamlit Community Cloud has an ephemeral filesystem, so the bundled
`seed.sqlite.gz` (ESCO + NSP + occupations + ads + demo candidates) and any
uploaded CVs are wiped on restart. To persist, point the app at an external
Postgres via `CV_BAU_STUDENTS_DB_URL` — but a fresh Postgres is empty, because
the seed-snapshot restore in `bootstrap.py` is SQLite-only. This script copies
the whole local SQLite DB into the target Postgres once.

Run AFTER `scripts/seed_target_demo.py` (so the SQLite holds the full demo:
ESCO/NSP taxonomy + ad 341 + the 6 demo candidates + matches).

Usage:
    python -m scripts.migrate_sqlite_to_postgres --target "postgresql://user:pass@host/db?sslmode=require"
    python -m scripts.migrate_sqlite_to_postgres --target "$CV_BAU_STUDENTS_TARGET_URL" --truncate

  --source   SQLAlchemy URL of the source (default: config.DB_URL, the local SQLite).
  --target   SQLAlchemy URL of the destination Postgres (or env CV_BAU_STUDENTS_TARGET_URL).
  --truncate Delete existing rows in the target first (FK-safe order) so re-runs are clean.

Idempotency: without --truncate the copy appends, which can violate PK/unique
constraints on a re-run — use --truncate to re-pour.
"""

from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import create_engine, delete, func, insert, select

from cv_bau_students import config
from cv_bau_students.db_models import Base

# Tables holding irreplaceable user data (uploaded CVs + their scores). Taxonomy
# tables (skills/ads/occupations) are re-pourable from the seed, so a --truncate
# that only touches those is harmless; one that would wipe these is not.
_USER_DATA_TABLES = ("candidates", "matches")


class TruncateGuardError(RuntimeError):
    """Raised when --truncate would delete existing candidate data without
    explicit --confirm-destroy. Prevents a wrong --target silently wiping
    uploaded CVs."""


def _count_user_rows(engine, tables) -> int:
    """Total rows across the irreplaceable user-data tables in `engine`."""
    by_name = {t.name: t for t in tables}
    total = 0
    with engine.connect() as conn:
        for name in _USER_DATA_TABLES:
            table = by_name.get(name)
            if table is None:
                continue
            total += conn.execute(select(func.count()).select_from(table)).scalar_one() or 0
    return total


def migrate(
    source_url: str,
    target_url: str,
    *,
    truncate: bool = False,
    confirm_destroy: bool = False,
    verbose: bool = True,
) -> dict[str, int]:
    """Copy every ORM table from `source_url` to `target_url`. Returns row counts.

    `truncate` wipes the target first (FK-safe). When the target already holds
    candidate/match rows, that is refused unless `confirm_destroy=True` — a
    guard against a mistyped --target silently destroying uploaded CVs.
    """
    source = create_engine(source_url, future=True)
    target = create_engine(target_url, future=True, pool_pre_ping=True)

    Base.metadata.create_all(target)  # build the schema on the destination

    tables = list(Base.metadata.sorted_tables)  # parent-before-child (FK-safe)
    counts: dict[str, int] = {}

    if truncate and not confirm_destroy:
        existing = _count_user_rows(target, tables)
        if existing:
            raise TruncateGuardError(
                f"Refusing --truncate: target {target.url.host or target_url!r} already "
                f"holds {existing} candidate/match row(s) — this would PERMANENTLY delete "
                "uploaded CVs. Re-run with --confirm-destroy if you really mean it."
            )

    with source.connect() as src, target.begin() as dst:
        if truncate:
            # Children first (reverse) so FK constraints don't block the deletes.
            for table in reversed(tables):
                dst.execute(delete(table))
        for table in tables:
            rows = [dict(r._mapping) for r in src.execute(select(table))]
            if rows:
                dst.execute(insert(table), rows)
            counts[table.name] = len(rows)
            if verbose:
                print(f"  {table.name:28} {len(rows):>7} rows")

    total = sum(counts.values())
    if verbose:
        dest = target.url.host or target_url
        print(f"\nDone. Copied {total} rows across {len(tables)} tables → {dest}")
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy local SQLite → Postgres (one-time).")
    parser.add_argument(
        "--source", default=config.DB_URL, help="Source SQLAlchemy URL (default: local SQLite)."
    )
    parser.add_argument(
        "--target",
        default=os.environ.get("CV_BAU_STUDENTS_TARGET_URL"),
        help="Destination Postgres URL (or env CV_BAU_STUDENTS_TARGET_URL).",
    )
    parser.add_argument("--truncate", action="store_true", help="Wipe target rows first (re-pour).")
    parser.add_argument(
        "--confirm-destroy",
        action="store_true",
        help="Required alongside --truncate when the target already holds candidate data.",
    )
    args = parser.parse_args()

    if not args.target:
        print("No --target given (and CV_BAU_STUDENTS_TARGET_URL unset).", file=sys.stderr)
        return 2
    try:
        migrate(
            args.source,
            args.target,
            truncate=args.truncate,
            confirm_destroy=args.confirm_destroy,
        )
    except TruncateGuardError as exc:
        print(f"ABORT: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
