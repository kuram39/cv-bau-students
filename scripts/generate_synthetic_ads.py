#!/usr/bin/env python3
"""Generate synthetic job ads to fill the (domain × level) matrix.

Calls the LLM via the existing wrapper, validates each ad against the
`JobAd` Pydantic schema, persists via the `jobads` repository. Idempotent
in the sense that re-running just appends more ads — wipe the
`job_ads` / `job_ad_skills` tables first if you want a clean rebuild.
"""

import argparse
import json
import sys
from itertools import product

from cv_bau_students import llm
from cv_bau_students.db import init_db
from cv_bau_students.jobads.repo import store_ad
from cv_bau_students.models import JobAd

DEFAULT_DOMAINS = [
    "data-analyst",
    "frontend-developer",
    "backend-developer",
    "marketing-analyst",
    "ux-designer",
    "project-manager",
    "controller",
    "qa-engineer",
]
DEFAULT_LEVELS = ["junior", "medior", "senior"]
DEFAULT_LANGUAGES = ["cs", "en"]
DEFAULT_REMOTE_MODES = ["onsite", "hybrid", "remote"]


def main() -> int:
    parser = argparse.ArgumentParser(description="LLM-generate synthetic job ads.")
    parser.add_argument(
        "--per-cell",
        type=int,
        default=1,
        help="How many ads to generate per (domain × level × language) cell.",
    )
    parser.add_argument(
        "--domains",
        nargs="+",
        default=DEFAULT_DOMAINS,
        help="Override the default domain list.",
    )
    parser.add_argument(
        "--levels",
        nargs="+",
        default=DEFAULT_LEVELS,
        help="Override the default level list.",
    )
    parser.add_argument(
        "--languages",
        nargs="+",
        default=DEFAULT_LANGUAGES,
        help="Languages to generate in (cs / en).",
    )
    args = parser.parse_args()

    init_db()

    written = 0
    for domain, level, language in product(args.domains, args.levels, args.languages):
        for cell in range(args.per_cell):
            remote_mode = DEFAULT_REMOTE_MODES[cell % len(DEFAULT_REMOTE_MODES)]
            try:
                ad = _generate_one(domain, level, language, remote_mode)
            except Exception as exc:  # noqa: BLE001 — surface to console
                print(
                    f"WARN: could not generate {domain}/{level}/{language}: {exc}",
                    file=sys.stderr,
                )
                continue
            store_ad(ad)
            written += 1
            print(f"  + [{ad.source}] {ad.title} ({ad.level}, {ad.location})")

    print(f"\nWrote {written} synthetic ads.")
    return 0


def _generate_one(domain: str, level: str, language: str, remote_mode: str) -> JobAd:
    prompt = llm.render_prompt(
        "generate_synthetic_ad",
        domain=domain,
        level=level,
        language=language,
        remote_mode=remote_mode,
    )
    payload = llm.call_json(prompt)
    payload.setdefault("source", "synthetic")
    payload.setdefault("ad_url", None)
    return JobAd.model_validate(payload)


def dump_one(domain: str, level: str, language: str, remote_mode: str = "hybrid") -> None:
    """Convenience entry for the dev loop: pretty-print a single ad to stdout
    without persisting it.
    """
    ad = _generate_one(domain, level, language, remote_mode)
    print(json.dumps(ad.model_dump(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
