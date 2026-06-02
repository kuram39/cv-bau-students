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
from cv_bau_students.bootstrap import ensure_seeded
from cv_bau_students.db import get_session, init_db, reset_engine_for_tests
from cv_bau_students.taxonomy.repo import resolve_skill, resolve_skill_esco

# Czech-specific letters — a phrase carrying any of these is *detectably* Czech.
# NB: a diacritics-stripped Czech phrase ("datove modelovani") is undetectable
# here, so the Czech subset is a lower bound; the unresolved tail is the truth.
_CZECH_CHARS = set("áčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ")


def _is_czechish(phrase: str) -> bool:
    return any(ch in _CZECH_CHARS for ch in phrase)


def _resolves(phrase: str) -> bool:
    """Resolves in EITHER namespace — for the 'does this phrase land anywhere' raw
    signal (the alias/embeddings decision)."""
    return resolve_skill(phrase) is not None or resolve_skill_esco(phrase) is not None


def _resolves_esco(phrase: str) -> bool:
    """ESCO-only — mirrors the runtime path: the translator stores an
    `esco_skill_id` from `resolve_skill_esco(esco_term or skill)` (translate.py
    `_link_to_esco`), and the matcher scores in ESCO space. A seed-only hit does
    NOT give the matcher a usable id, so it must not count as runtime coverage."""
    return resolve_skill_esco(phrase) is not None


def collect_rows(db_url: str | None = None) -> list[tuple[str, str | None, int | None]]:
    """`(skill_canonical, esco_term, esco_skill_id)` rows from translated_capabilities.

    For the DEFAULT DB, restore the bundled demo seed (`ensure_seeded`) so a fresh
    checkout measures real data instead of an empty schema. For an explicit
    `--source`, only `init_db()` (create/migrate tables) — NEVER `ensure_seeded`,
    because `_restore_from_seed_snapshot` overwrites a SQLite file ≤64 KiB and
    would clobber a small user-supplied DB with the bundled seed."""
    if db_url:
        reset_engine_for_tests(db_url)  # public reset; also used by the test conftest
        init_db()  # tables only — do NOT snapshot-restore over an explicit source
    else:
        ensure_seeded()  # default DB: restore seed.sqlite.gz if empty + create/migrate
    with get_session() as session:
        rows = session.execute(
            text("SELECT skill_canonical, esco_term, esco_skill_id FROM translated_capabilities")
        ).all()
    return [(c, e, sid) for c, e, sid in rows if c and c.strip()]


def summarize(rows: list[tuple[str, str | None, int | None]]) -> dict:
    """Resolution stats over capability rows. Pure — easy to unit-test.

    `runtime_*` mirrors the matcher exactly: per ROW, a row counts as covered
    when it has a persisted `esco_skill_id` OR `esco_term or skill_canonical`
    resolves in the ESCO namespace (the matcher credits the stored id first, then
    falls back to `resolve_skill_esco`). NB this models the CURATED / ISCO target
    path (ESCO space); an ad with NO recruiter-curated set is scored by
    `_skill_fit` in SEED space instead, so `raw_*` is the better proxy there.
    `raw_*` resolves the distinct `skill_canonical` display phrases (where Czech
    lives) and reports the detectable-Czech subset + tail."""
    # Runtime-effective: per capability row (NOT deduped — dup capabilities across
    # candidates each cost a resolution), honoring the persisted esco_skill_id.
    runtime_phrases = rows
    runtime_resolved = sum(
        1
        for c, e, sid in rows
        if sid is not None or _resolves_esco(e.strip() if e and e.strip() else c.strip())
    )

    # Raw display phrases (skill_canonical only).
    raw = sorted({c.strip() for c, _e, _s in rows})
    raw_resolved = {p for p in raw if _resolves(p)}
    czech = [p for p in raw if _is_czechish(p)]
    czech_resolved = [p for p in czech if _resolves(p)]
    unresolved = [p for p in raw if p not in raw_resolved]

    def pct(n: int, d: int) -> float:
        return round(100.0 * n / d, 1) if d else 0.0

    return {
        "rows": len(rows),
        "runtime_total": len(runtime_phrases),
        "runtime_resolved": runtime_resolved,
        "runtime_pct": pct(runtime_resolved, len(runtime_phrases)),
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
        f"  runtime-effective (translated_capabilities only): "
        f"{s['runtime_resolved']}/{s['runtime_total']}  ({s['runtime_pct']} %)"
    )
    print(
        "    (NB excludes CandidateProfile.explicit_skills, which the matcher also "
        "credits — so this is a lower bound on true runtime coverage.)"
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
