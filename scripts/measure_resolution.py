#!/usr/bin/env python3
"""Measure how well candidate skill phrases resolve against the taxonomy.

Deep-research #6 (docs/research/06-vendor-tool-taxonomies.md) hinges on a number
that was only ever *inferred*: "~33% Czech skill resolution". Before spending
effort on an ESCO Czech-alias load / embeddings fallback, quantify the real
coverage from data already in the DB.

Two rates, because they answer different questions:

* **runtime-effective** — resolve each capability the way the pipeline does:
  ``esco_term or skill_canonical`` (the translator stores an English ``esco_term``
  and the matcher resolves on it). This is the coverage the matcher actually gets.
* **raw skill_canonical** — resolve the candidate's *display* phrase alone (often
  Czech). This is where diacritics/aliasing matters, and the unresolved tail here
  is the ground truth for any alias/embeddings decision.

Pure read, no LLM key. Usage:
    python -m scripts.measure_resolution                      # default DB (config.DB_URL)
    python -m scripts.measure_resolution --source sqlite:///./data/cv_bau_students.sqlite
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import text

from cv_bau_students import config
from cv_bau_students.db import get_session, init_db, reset_engine_for_tests
from cv_bau_students.taxonomy.repo import resolve_skill, resolve_skill_esco

# Czech-specific letters — a phrase carrying any of these is *detectably* Czech.
# NB: a diacritics-stripped Czech phrase ("datove modelovani") is undetectable
# here, so the Czech subset is a lower bound; the unresolved tail is the truth.
_CZECH_CHARS = set("áčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ")


def _is_czechish(phrase: str) -> bool:
    return any(ch in _CZECH_CHARS for ch in phrase)


def _resolves(phrase: str) -> bool:
    return resolve_skill(phrase) is not None or resolve_skill_esco(phrase) is not None


def collect_rows(db_url: str | None = None) -> list[tuple[str, str | None]]:
    """`(skill_canonical, esco_term)` rows from translated_capabilities.

    Calls `init_db()` first so a fresh/unseeded DB doesn't crash on a missing
    table (matches how the other repo scripts bootstrap before reading)."""
    if db_url:
        reset_engine_for_tests(db_url)  # public reset; also used by the test conftest
    init_db()  # idempotent: create tables (+ migrate) so the SELECT can't 500
    with get_session() as session:
        rows = session.execute(
            text("SELECT skill_canonical, esco_term FROM translated_capabilities")
        ).all()
    return [(c, e) for c, e in rows if c and c.strip()]


def summarize(rows: list[tuple[str, str | None]]) -> dict:
    """Resolution stats over capability rows. Pure — easy to unit-test.

    `runtime_*` resolves `esco_term or skill_canonical` per row (what the matcher
    does); `raw_*` resolves the distinct `skill_canonical` display phrases (where
    Czech lives) and reports the detectable-Czech subset + the unresolved tail."""
    # Runtime-effective: one value per capability row, esco_term preferred.
    runtime_phrases = {(e.strip() if e and e.strip() else c.strip()) for c, e in rows}
    runtime_resolved = {p for p in runtime_phrases if _resolves(p)}

    # Raw display phrases (skill_canonical only).
    raw = sorted({c.strip() for c, _ in rows})
    raw_resolved = {p for p in raw if _resolves(p)}
    czech = [p for p in raw if _is_czechish(p)]
    czech_resolved = [p for p in czech if _resolves(p)]
    unresolved = [p for p in raw if p not in raw_resolved]

    def pct(n: int, d: int) -> float:
        return round(100.0 * n / d, 1) if d else 0.0

    return {
        "rows": len(rows),
        "runtime_total": len(runtime_phrases),
        "runtime_resolved": len(runtime_resolved),
        "runtime_pct": pct(len(runtime_resolved), len(runtime_phrases)),
        "raw_total": len(raw),
        "raw_resolved": len(raw_resolved),
        "raw_pct": pct(len(raw_resolved), len(raw)),
        "czech_total": len(czech),
        "czech_resolved": len(czech_resolved),
        "czech_pct": pct(len(czech_resolved), len(czech)),
        "unresolved": unresolved,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Measure candidate-skill resolution rate.")
    p.add_argument("--source", default=None, help="Source SQLAlchemy URL (default: config.DB_URL).")
    p.add_argument(
        "--limit-tail", type=int, default=40, help="How many unresolved phrases to dump."
    )
    args = p.parse_args()

    rows = collect_rows(args.source)
    if not rows:
        print(
            f"No candidate skill phrases found in {args.source or config.DB_URL}.\n"
            "Seed the demo (scripts.seed_target_demo) or point --source at a populated DB."
        )
        return 1

    s = summarize(rows)
    print(f"Source: {args.source or config.DB_URL}")
    print(f"Capability rows: {s['rows']}")
    print(
        f"  runtime-effective (esco_term or skill): "
        f"{s['runtime_resolved']}/{s['runtime_total']}  ({s['runtime_pct']} %)"
    )
    print(
        f"  raw skill_canonical only:               "
        f"{s['raw_resolved']}/{s['raw_total']}  ({s['raw_pct']} %)"
    )
    print(
        f"    …detectable-Czech subset (raw):       "
        f"{s['czech_resolved']}/{s['czech_total']}  ({s['czech_pct']} %)"
    )
    if s["unresolved"]:
        print(f"\nUnresolved raw tail (first {args.limit_tail}; inspect for diacritic-less Czech):")
        for phrase in s["unresolved"][: args.limit_tail]:
            mark = "cs" if _is_czechish(phrase) else "  "
            print(f"  [{mark}] {phrase}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
