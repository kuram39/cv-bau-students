#!/usr/bin/env python3
"""Retag `source_type='other'` capabilities that actually came from real work.

Before the `work` evidence tier existed, the translator dumped every
employment-derived capability into `other` (→ weak evidence → falsely low
"doloženost" for experienced candidates). The prompt now emits `work`, but
already-translated rows (the bundled seed, Neon) still say `other`.

This is a **deterministic, no-LLM** backfill: a capability is retagged `other` →
`work` when its `evidence_quote` is a verbatim substring of a NON-brigáda
`work_experience` entry in the candidate's latest profile (the translator copies
evidence verbatim from the profile JSON, so this is a safe match). Summary-only
claims and project/thesis/brigáda evidence are left untouched.

Usage:
    python -m scripts.retag_work_evidence                 # default DB (config.DB_URL)
    python -m scripts.retag_work_evidence --source sqlite:///./data/cv_bau_students.sqlite
    python -m scripts.retag_work_evidence --rescore-ad 341   # refresh doloženost after
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from cv_bau_students.db import get_session, init_db, reset_engine_for_tests
from cv_bau_students.db_models import ProfileVersion, TranslatedCapabilityRow


def _work_descriptions(profile_json: dict) -> list[str]:
    """Lower-cased descriptions of NON-brigáda work_experience entries."""
    out: list[str] = []
    for w in profile_json.get("work_experience") or []:
        if w.get("is_brigada"):
            continue
        desc = (w.get("description") or "").strip().lower()
        if desc:
            out.append(desc)
    return out


def retag(db_url: str | None = None) -> int:
    """Retag matching `other` capabilities to `work`. Returns rows changed."""
    if db_url:
        reset_engine_for_tests(db_url)
    init_db()
    changed = 0
    with get_session() as session:
        rows = (
            session.execute(
                select(TranslatedCapabilityRow).where(
                    TranslatedCapabilityRow.source_type == "other"
                )
            )
            .scalars()
            .all()
        )
        # Cache latest profile work-descriptions per candidate.
        cache: dict[int, list[str]] = {}
        for cap in rows:
            cid = cap.candidate_id
            if cid not in cache:
                pv = session.execute(
                    select(ProfileVersion)
                    .where(ProfileVersion.candidate_id == cid)
                    .order_by(ProfileVersion.round.desc())
                    .limit(1)
                ).scalar_one_or_none()
                cache[cid] = _work_descriptions(pv.profile_json) if pv else []
            quote = (cap.evidence_quote or "").strip().lower()
            if quote and any(quote in desc for desc in cache[cid]):
                cap.source_type = "work"
                changed += 1
    return changed


def main() -> int:
    p = argparse.ArgumentParser(description="Retag work-derived capabilities (other → work).")
    p.add_argument("--source", default=None, help="Source SQLAlchemy URL (default: config.DB_URL).")
    p.add_argument("--rescore-ad", type=int, default=None, help="rescore_ad(ID) after retag.")
    args = p.parse_args()
    n = retag(args.source)
    print(f"Retagged {n} capabilities other → work.")
    if args.rescore_ad is not None:
        from cv_bau_students.candidates.repo import rescore_ad

        print(f"Rescored {rescore_ad(args.rescore_ad)} candidates on ad {args.rescore_ad}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
