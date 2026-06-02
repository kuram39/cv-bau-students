#!/usr/bin/env python3
"""Measure how well candidate skill phrases resolve against the taxonomy.

Deep-research #6 (docs/research/06-vendor-tool-taxonomies.md) hinges on a number
that was only ever *inferred*: "~33% Czech skill resolution". Before spending
effort on an ESCO Czech-alias load / embeddings fallback, quantify the real
coverage from data already in the DB.

For every distinct candidate skill phrase (`translated_capabilities.skill_canonical`,
plus `esco_term` when present), try `resolve_skill` (seed namespace) then
`resolve_skill_esco` (ESCO namespace). Report overall + Czech-only resolution %
and dump the unresolved tail so the gap is concrete, not folklore.

Pure read, no LLM key. Usage:
    python -m scripts.measure_resolution                      # default DB (config.DB_URL)
    python -m scripts.measure_resolution --source sqlite:///./data/cv_bau_students.sqlite
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import text

from cv_bau_students import config
from cv_bau_students.db import get_session, reset_engine_for_tests
from cv_bau_students.taxonomy.repo import resolve_skill, resolve_skill_esco

# Czech-specific letters — a phrase carrying any of these is where the
# diacritics fallback / Czech aliasing actually matters.
_CZECH_CHARS = set("áčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ")


def _is_czechish(phrase: str) -> bool:
    return any(ch in _CZECH_CHARS for ch in phrase)


def _resolves(phrase: str) -> bool:
    return resolve_skill(phrase) is not None or resolve_skill_esco(phrase) is not None


def collect_phrases(db_url: str | None = None) -> list[str]:
    """Distinct candidate skill phrases from translated_capabilities."""
    if db_url:
        reset_engine_for_tests(db_url)  # public reset; also used by the test conftest
    phrases: set[str] = set()
    with get_session() as session:
        rows = session.execute(
            text("SELECT skill_canonical, esco_term FROM translated_capabilities")
        ).all()
    for canonical, esco_term in rows:
        for p in (canonical, esco_term):
            if p and p.strip():
                phrases.add(p.strip())
    return sorted(phrases)


def summarize(phrases: list[str]) -> dict:
    """Resolution stats over the given phrases. Pure — easy to unit-test."""
    total = len(phrases)
    resolved = [p for p in phrases if _resolves(p)]
    czech = [p for p in phrases if _is_czechish(p)]
    czech_resolved = [p for p in czech if _resolves(p)]
    unresolved = [p for p in phrases if p not in set(resolved)]
    return {
        "total": total,
        "resolved": len(resolved),
        "resolved_pct": round(100.0 * len(resolved) / total, 1) if total else 0.0,
        "czech_total": len(czech),
        "czech_resolved": len(czech_resolved),
        "czech_resolved_pct": (
            round(100.0 * len(czech_resolved) / len(czech), 1) if czech else 0.0
        ),
        "unresolved": unresolved,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Measure candidate-skill resolution rate.")
    p.add_argument("--source", default=None, help="Source SQLAlchemy URL (default: config.DB_URL).")
    p.add_argument(
        "--limit-tail", type=int, default=40, help="How many unresolved phrases to dump."
    )
    args = p.parse_args()

    phrases = collect_phrases(args.source)
    if not phrases:
        print(
            f"No candidate skill phrases found in {args.source or config.DB_URL}.\n"
            "Seed the demo (scripts.seed_target_demo) or point --source at a populated DB."
        )
        return 1

    s = summarize(phrases)
    print(f"Source: {args.source or config.DB_URL}")
    print(f"Distinct candidate skill phrases: {s['total']}")
    print(f"  resolved (seed OR esco):       {s['resolved']}  ({s['resolved_pct']} %)")
    print(f"  Czech-diacritic phrases:       {s['czech_total']}")
    print(f"  …of those resolved:            {s['czech_resolved']}  ({s['czech_resolved_pct']} %)")
    if s["unresolved"]:
        print(f"\nUnresolved tail (first {args.limit_tail}):")
        for phrase in s["unresolved"][: args.limit_tail]:
            mark = "cs" if _is_czechish(phrase) else "  "
            print(f"  [{mark}] {phrase}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
