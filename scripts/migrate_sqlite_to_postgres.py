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

from sqlalchemy import create_engine, delete, insert, select

from cv_bau_students import config
from cv_bau_students.db_models import Base


def migrate(
    source_url: str, target_url: str, *, truncate: bool = False, verbose: bool = True
) -> dict[str, int]:
    """Copy every ORM table from `source_url` to `target_url`. Returns row counts."""
    source = create_engine(source_url, future=True)
    target = create_engine(target_url, future=True, pool_pre_ping=True)

    Base.metadata.create_all(target)  # build the schema on the destination

    tables = list(Base.metadata.sorted_tables)  # parent-before-child (FK-safe)
    counts: dict[str, int] = {}

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
    args = parser.parse_args()

    if not args.target:
        print("No --target given (and CV_BAU_STUDENTS_TARGET_URL unset).", file=sys.stderr)
        return 2
    migrate(args.source, args.target, truncate=args.truncate)
    return 0


if __name__ == "__main__":
    sys.exit(main())
