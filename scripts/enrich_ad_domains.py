#!/usr/bin/env python3
"""Backfill better `domain` classifications on already-ingested ads.

Walks `job_ads` rows where `domain = 'general'` (or another user-
supplied filter) and asks the LLM to classify them. Updates the
domain column in place. Idempotent — re-runs on the same ads return
the same classifications (low temperature, frozen prompt).

Usage:
    python scripts/enrich_ad_domains.py [--only-general] [--min-confidence 0.5]
    python scripts/enrich_ad_domains.py --dry-run

Cost: one LLM call per ad. For 481 ads at ~$0.0005/call ≈ $0.25
one-time. Caches under (title, raw_text first 1200 chars) via lru_cache
so re-running in the same process is free.
"""

import argparse
import sys
from functools import lru_cache

from sqlalchemy import select, update

from cv_bau_students import llm
from cv_bau_students.db import get_session, init_db
from cv_bau_students.db_models import JobAdRow

KNOWN_DOMAINS = {
    "data-analyst",
    "frontend-developer",
    "backend-developer",
    "marketing-analyst",
    "ux-designer",
    "project-manager",
    "controller",
    "qa-engineer",
    "general",
}


@lru_cache(maxsize=1024)
def _classify(title: str, body_snippet: str, employer: str) -> tuple[str, float, str]:
    prompt = llm.render_prompt(
        "classify_ad_domain",
        title=title,
        employer=employer,
        raw_text=body_snippet,
    )
    payload = llm.call_json(prompt)
    domain = (payload.get("domain") or "general").strip().lower()
    if domain not in KNOWN_DOMAINS:
        domain = "general"
    confidence = float(payload.get("confidence", 0.0) or 0.0)
    reason = payload.get("reason", "")
    return domain, confidence, reason


def main() -> int:
    parser = argparse.ArgumentParser(description="LLM-classify ad domains.")
    parser.add_argument(
        "--only-general",
        action="store_true",
        help="Only touch ads whose current domain is 'general'.",
    )
    parser.add_argument("--min-confidence", type=float, default=0.5)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print proposed changes without writing the DB.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap the number of ads to process (useful for testing).",
    )
    args = parser.parse_args()

    init_db()

    with get_session() as session:
        stmt = select(JobAdRow)
        if args.only_general:
            stmt = stmt.where(JobAdRow.domain == "general")
        if args.limit:
            stmt = stmt.limit(args.limit)
        rows = session.execute(stmt).scalars().all()

    print(f"Processing {len(rows)} ads…")
    updates = 0
    skipped_low_conf = 0
    for row in rows:
        snippet = (row.raw_text or "")[:1200]
        try:
            domain, confidence, reason = _classify(row.title or "", snippet, row.employer or "")
        except Exception as exc:  # noqa: BLE001 — surface + continue
            print(f"  WARN: ad {row.id} classification failed: {exc}", file=sys.stderr)
            continue
        if domain == row.domain:
            continue
        if confidence < args.min_confidence:
            skipped_low_conf += 1
            continue
        if args.dry_run:
            short = (row.title or "")[:55]
            print(
                f"  [{row.id}] {short:55} | {row.domain:20}"
                f" → {domain:20} ({confidence:.2f}: {reason[:40]})"
            )
        else:
            with get_session() as session:
                session.execute(update(JobAdRow).where(JobAdRow.id == row.id).values(domain=domain))
        updates += 1

    print(
        f"\n{'Would update' if args.dry_run else 'Updated'} {updates} ads "
        f"(skipped {skipped_low_conf} below confidence floor)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
