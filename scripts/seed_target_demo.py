#!/usr/bin/env python3
"""Seed the single-target-job demo: one ad + N pre-walked candidates.

Pipeline (all LLM-backed steps require ANTHROPIC_API_KEY — run this
yourself, the agent harness scrubs the key):

  1. Resolve the target ad ("Datový analytik") and turn it into the demo
     role in place: rename the employer to a made-up firm, lightly
     paraphrase the opening, and enrich the (empty-from-scrape) skill
     lists with realistic data-analyst must/nice-to-have skills +
     a Czech language requirement. Idempotent — skips if already done.
  2. Generate the role-specific question template ONCE (LLM). Every
     candidate then answers the same questions.
  3. For each CV in data/raw_cv_samples/{students,experienced}/:
       - run_generic_pass  → candidate persisted
       - express_interest('interested') → fixed Qs + prefill suggestions
       - submit_role_specific(...) using the prefills as accept-as-is;
         any "missing" prefill is fabricated with one extra LLM call so
         the seed is self-contained.
  4. Print a per-CV summary.

Idempotent: cv_hash dedup means re-running updates rather than
duplicates. Safe to re-run after adding more sample CVs.

Usage:
    python -m scripts.seed_target_demo
    python -m scripts.seed_target_demo --target-title "Datový analytik"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from cv_bau_students import llm
from cv_bau_students.jobads.repo import find_ad_by_title_substring, set_ad_fields_and_skills
from cv_bau_students.models import LanguageRequirement
from cv_bau_students.pipeline import (
    express_interest,
    run_generic_pass,
    submit_role_specific,
)

load_dotenv()

STUDENTS_DIR = Path("data/raw_cv_samples/students")
EXPERIENCED_DIR = Path("data/raw_cv_samples/experienced")

DEMO_EMPLOYER = "ApexFinance s.r.o."
DEMO_MUST_HAVE = ["SQL", "Python", "Power BI", "Excel"]
DEMO_NICE_TO_HAVE = ["Tableau", "statistics"]
DEMO_LANGUAGES = [LanguageRequirement(language="Czech", min_level="C1")]

# Prepended sentence that re-frames the scraped opening as our own firm's
# ad without copying the original employer's exact pitch.
DEMO_INTRO = (
    f"Společnost {DEMO_EMPLOYER} hledá datového analytika / datovou "
    f"analytičku do interního týmu Business Intelligence. "
)


def _modify_target_ad(ad) -> None:
    """Turn the scraped row into the demo target — idempotent."""
    if ad.employer == DEMO_EMPLOYER:
        print(f"  target ad {ad.id} already prepared — skipping modify.")
        return
    new_raw = DEMO_INTRO + (ad.raw_text or "")
    set_ad_fields_and_skills(
        ad.id,
        employer=DEMO_EMPLOYER,
        raw_text=new_raw,
        must_have=DEMO_MUST_HAVE,
        nice_to_have=DEMO_NICE_TO_HAVE,
        languages_required=DEMO_LANGUAGES,
    )
    print(
        f"  modified ad {ad.id}: employer={DEMO_EMPLOYER}, "
        f"must_have={DEMO_MUST_HAVE}, nice={DEMO_NICE_TO_HAVE}"
    )


def _fabricate_answer(profile_summary: str, question_text: str) -> str:
    """One LLM call to write a plausible answer when the CV had nothing.

    Only used by the seed so the demo candidates all have complete role
    answers; the live UI leaves missing prefills for the user to write.
    """
    prompt = (
        "Napiš realistickou 2-3větnou odpověď z pohledu tohoto kandidáta "
        "na otázku v přihlášce. Drž se jeho profilu, nepřeháněj.\n\n"
        f"Profil (shrnutí): {profile_summary}\n\n"
        f"Otázka: {question_text}\n\nOdpověď:"
    )
    msg = llm._client().messages.create(
        model=llm.LLM_MODEL,
        max_tokens=300,
        temperature=0.6,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text").strip()


def _process_cv(path: Path, ad_id: int) -> dict:
    """Walk one CV through the full interested journey. Returns a summary."""
    file_bytes = path.read_bytes()
    gen = run_generic_pass(file_bytes, path.name)
    if gen.status == "needs_completion":
        return {
            "file": path.name,
            "status": "needs_completion",
            "candidate_id": gen.candidate_id,
            "note": "BAU-mandatory fields missing; skipped role-specific.",
        }

    interest = express_interest(gen.candidate_id, ad_id, "interested")

    # Build the answer set from prefills; fabricate where missing.
    answers: dict[str, str] = {}
    prefilled_set: set[str] = set()
    fabricated: list[str] = []
    summary = gen.profile.summary or gen.profile.name or path.stem
    for q in interest.prefilled_questions:
        if q.prefilled_answer:
            answers[q.slot] = q.prefilled_answer
            prefilled_set.add(q.slot)
        else:
            answers[q.slot] = _fabricate_answer(summary, q.question_text)
            fabricated.append(q.slot)

    result = submit_role_specific(
        gen.candidate_id,
        ad_id,
        answers=answers,
        prefilled_set=prefilled_set,
        edited_set=set(),  # seed accepts prefills as-is
    )
    return {
        "file": path.name,
        "status": "matched",
        "candidate_id": gen.candidate_id,
        "kind": gen.profile.candidate_type,
        "total": round(result.match.total, 1),
        "skill_fit": round(result.match.skill_fit, 1),
        "bridge_fit": round(result.match.bridge_fit, 1),
        "personal_fit": round(result.match.personal_fit, 1),
        "prefilled_slots": sorted(prefilled_set),
        "fabricated_slots": fabricated,
    }


def run_seed(target_title: str = "Datový analytik") -> int:
    """Core seed routine — argv-free so tests can drive it."""
    ad = find_ad_by_title_substring(target_title)
    if ad is None:
        print(
            f"No ad matching {target_title!r}. Is the DB seeded? "
            f"Run ensure_seeded() / load the scraped ads first.",
            file=sys.stderr,
        )
        return 1
    print(f"Target ad: id={ad.id} title={ad.title!r}")
    _modify_target_ad(ad)

    # Refresh the ad (employer/skills changed) for the Q generator.
    ad = find_ad_by_title_substring(target_title)

    # Generate the fixed role-specific question template once.
    from cv_bau_students.pipeline import ensure_role_specific_questions

    questions = ensure_role_specific_questions(ad.id)
    print(f"  role-specific questions ({len(questions)}):")
    for q in questions:
        print(f"    - [{q.slot}] {q.question_text}")

    cv_paths = sorted(STUDENTS_DIR.glob("*.txt")) + sorted(EXPERIENCED_DIR.glob("*.txt"))
    if not cv_paths:
        print(
            f"No CV samples in {STUDENTS_DIR} / {EXPERIENCED_DIR}. "
            f"Run scripts/generate_student_cvs.py + fetch_hf_resume_samples.py, "
            f"or use the committed demo set.",
            file=sys.stderr,
        )
        return 1

    print(f"\nProcessing {len(cv_paths)} CV(s)...")
    summaries = []
    for path in cv_paths:
        try:
            summary = _process_cv(path, ad.id)
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED {path.name}: {exc}", file=sys.stderr)
            continue
        summaries.append(summary)
        if summary["status"] == "matched":
            print(
                f"  {path.name}: {summary['kind']} total={summary['total']} "
                f"(skill={summary['skill_fit']} bridge={summary['bridge_fit']} "
                f"personal={summary['personal_fit']}) "
                f"fabricated={summary['fabricated_slots']}"
            )
        else:
            print(f"  {path.name}: {summary['status']} — {summary.get('note', '')}")

    matched = [s for s in summaries if s["status"] == "matched"]
    print(f"\nDone. {len(matched)}/{len(cv_paths)} candidates matched + stored for ad {ad.id}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the single-target demo.")
    parser.add_argument("--target-title", type=str, default="Datový analytik")
    args = parser.parse_args()
    return run_seed(args.target_title)


if __name__ == "__main__":
    sys.exit(main())
