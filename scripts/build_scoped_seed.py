#!/usr/bin/env python3
"""Build a ROLE-SCOPED copy of the DB — only the data the single-target demo needs.

The full taxonomy (~14k skills, 90k aliases, 70k occupation→skill rows, 6k
occupations, 481 ads) is universal coverage. This single-target demo scores
every CV against ONE data-analyst ad (ISCO 2511), so the bulk of that data is
never read — yet a Postgres deploy pulls it all over the network on every cold
start (~10s). This script derives the kept skill set S = the data-role family +
the demo's own skills, and writes a scoped SQLite with only those rows.

`skill_industry_map` is keyed on occupation_uri; ISCO 2511 aggregates dozens of
occupations (520 skills, mostly noise). We scope to the three relevant DATA
occupations (analyst + scientist + engineer ≈ 102 skills), which is both tighter
and captures the real overlap a data-analyst candidate is judged on. The result
(~2k rows) makes cold-start sub-second and focuses the recruiter skill-picker.

Usage:
    python -m scripts.build_scoped_seed                 # default: ad 341, data roles
    python -m scripts.build_scoped_seed --out /tmp/scoped.sqlite --source sqlite:///./data/cv_bau_students.sqlite
Then: build_cloud_seed on the scoped DB (gz), and migrate it to Postgres.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import bindparam, create_engine, insert, select, text

from cv_bau_students import config
from cv_bau_students.db_models import Base

# The data-role family: ESCO occupation URIs whose skill sets define "relevant
# for a data-analyst hire". Configurable — add e.g. database admin (2521) here.
DATA_ROLE_URIS = [
    "http://data.europa.eu/esco/occupation/d3edb8f8-3a06-47a0-8fb9-9b212c006aa2",  # data analyst
    "http://data.europa.eu/esco/occupation/258e46f9-0075-4a2e-adae-1ff0477e0f30",  # data scientist
    "http://data.europa.eu/esco/occupation/2079755f-d809-49e6-8037-4de6180e54c0",  # data engineer
]


def _scalars(conn, sql: str, params: dict | None = None) -> set[int]:
    return {r[0] for r in conn.execute(text(sql), params or {}) if r[0] is not None}


def _compute_kept_skill_ids(conn, *, ad_id: int, occ_uris: list[str], domain: str) -> set[int]:
    """S = data-role family skills ∪ the demo's own referenced skills ∪ hand-seed."""
    in_uris = text(
        "SELECT DISTINCT skill_id FROM skill_industry_map WHERE occupation_uri IN :u"
    ).bindparams(bindparam("u", expanding=True))
    s: set[int] = {r[0] for r in conn.execute(in_uris, {"u": occ_uris})}
    s |= _scalars(conn, "SELECT skill_id FROM job_ad_skills WHERE ad_id = :a", {"a": ad_id})
    s |= _scalars(conn, "SELECT skill_id FROM ad_target_skills WHERE ad_id = :a", {"a": ad_id})
    s |= _scalars(conn, "SELECT skill_id FROM level_checklists WHERE domain = :d", {"d": domain})
    s |= _scalars(conn, "SELECT esco_skill_id FROM translated_capabilities")
    # Hand-seed taxonomy (CSV-loaded Python/SQL/…): no esco_uri, but must/nice +
    # explicit_skills resolve to these via resolve_skill (seed namespace).
    s |= _scalars(conn, "SELECT id FROM skills WHERE esco_uri IS NULL")
    return s


def _row_filter(table_name: str, *, ad_id: int, occ_uris: list[str], domain: str, kept: set[int]):
    """Return (where_sql, params) for a table, or None to copy ALL rows."""
    kept_list = list(kept)
    filters = {
        "skills": ("id IN :k", {"k": kept_list}),
        "skill_aliases": ("canonical_id IN :k", {"k": kept_list}),
        "skill_hierarchy": ("parent_id IN :k AND child_id IN :k", {"k": kept_list}),
        "skill_industry_map": (
            "occupation_uri IN :u AND skill_id IN :k",
            {"u": occ_uris, "k": kept_list},
        ),
        "occupations": ("occupation_uri IN :u", {"u": occ_uris}),
        "job_ads": ("id = :a", {"a": ad_id}),
        "job_ad_skills": ("ad_id = :a", {"a": ad_id}),
        "level_checklists": ("domain = :d", {"d": domain}),
    }
    return filters.get(table_name)


def _dedup_history(table_name: str, rows: list[dict]) -> list[dict]:
    """Collapse rerun cruft so the bundled seed is a CLEAN demo.

    Re-running seed_target_demo on a non-empty DB APPENDS history: a new
    `profile_versions` round per candidate + extra `reasoning_cache` rows. Left
    as-is, `meta/reflect` reads `len(profile_versions) - 1` as phantom completion
    rounds. Keep only the latest profile version per candidate (renumbered to
    round 0) and the latest reasoning_cache per (candidate, ad)."""
    if table_name == "profile_versions":
        latest: dict[int, dict] = {}
        for r in rows:
            cid = r["candidate_id"]
            if cid not in latest or r.get("round", 0) > latest[cid].get("round", 0):
                latest[cid] = r
        out = []
        for r in latest.values():
            r = dict(r)
            r["round"] = 0  # single canonical version in the seed
            out.append(r)
        return out
    if table_name == "reasoning_cache":
        latest: dict[tuple, dict] = {}
        for r in rows:
            key = (r.get("candidate_id"), r.get("ad_id"))
            if key not in latest or (r.get("id") or 0) > (latest[key].get("id") or 0):
                latest[key] = r
        return list(latest.values())
    return rows


def build_scoped(
    source_url: str,
    out_path: Path,
    *,
    ad_id: int = 341,
    occ_uris: list[str] | None = None,
    domain: str = "data-analyst",
    verbose: bool = True,
) -> dict[str, int]:
    """Write a scoped SQLite at out_path. Returns per-table row counts."""
    occ_uris = occ_uris or DATA_ROLE_URIS
    if out_path.exists():
        out_path.unlink()
    src = create_engine(source_url, future=True)
    out = create_engine(f"sqlite:///{out_path}", future=True)
    Base.metadata.create_all(out)
    tables = list(Base.metadata.sorted_tables)
    counts: dict[str, int] = {}

    with src.connect() as s, out.begin() as d:
        kept = _compute_kept_skill_ids(s, ad_id=ad_id, occ_uris=occ_uris, domain=domain)
        if verbose:
            print(f"  kept skill ids: {len(kept)}")
        for table in tables:
            flt = _row_filter(table.name, ad_id=ad_id, occ_uris=occ_uris, domain=domain, kept=kept)
            if flt is None:
                stmt = select(table)  # candidate-side tables: copy all
            else:
                where_sql, params = flt
                expanding = {k: v for k, v in params.items() if isinstance(v, list)}
                stmt = select(table).where(
                    text(where_sql).bindparams(*[bindparam(k, expanding=True) for k in expanding])
                )
                stmt = stmt.params(**params)
            rows = [dict(r._mapping) for r in s.execute(stmt)]
            rows = _dedup_history(table.name, rows)
            if rows:
                d.execute(insert(table), rows)
            counts[table.name] = len(rows)
            if verbose:
                print(f"  {table.name:28} {len(rows):>7} rows")

    total = sum(counts.values())
    if verbose:
        print(f"\nDone. Scoped DB → {out_path} ({total} rows across {len(tables)} tables).")
    return counts


def _default_source() -> str:
    return config.DB_URL


def main() -> int:
    p = argparse.ArgumentParser(description="Build a role-scoped copy of the DB.")
    p.add_argument("--source", default=_default_source(), help="Source SQLAlchemy URL (full DB).")
    p.add_argument(
        "--out", default="data/cv_bau_students_scoped.sqlite", help="Output SQLite path."
    )
    p.add_argument("--ad", type=int, default=341, help="Target ad id to keep.")
    p.add_argument("--domain", default="data-analyst", help="Level-checklist domain to keep.")
    args = p.parse_args()
    build_scoped(args.source, Path(args.out), ad_id=args.ad, domain=args.domain)
    return 0


if __name__ == "__main__":
    sys.exit(main())
